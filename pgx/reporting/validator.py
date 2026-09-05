# -*- coding: utf-8 -*-
"""Fact preservation and safe status rendering (WP-15).

Two checks stand between a calculated assessment and a published document,
and both of them fail closed.

**Nothing may be lost.** :func:`build_fact_ledger` enumerates, from the
canonical result alone, every fact the report is obliged to carry: each
medication, each axis, each finding, each evidence reference, each rule
reference, each unresolved conflict reference, each coverage reason code, each
pinned version. :func:`validate_fact_preservation` then checks the built
report against that ledger, and :func:`validate_rendered_report` checks the
rendered text as well - because a fact present in a structure and absent from
the page is still a fact the reader does not have.

The ledger is machine-checkable on purpose. "The report looks complete" is not
a property two people evaluate the same way, and a report that dropped one
evidence reference looks exactly like one that never had it.

**Nothing may read as reassurance.** :func:`validate_safe_status_rendering`
enforces the presentation half of ``SAFETY-INV-001``:

* attention and coverage are always adjacent and equally visible;
* ``NOT_ASSESSED`` is never displayed as low, no risk, safe, no warning,
  normal or suitable - it is displayed as *not assessed / outside the assessed
  scope*, and nothing else;
* ``PARTIAL`` is displayed with its reasons and its missing axes, not as a
  footnote;
* a level over incomplete coverage carries the controlled sentence saying it
  is the worst level among the evaluated subset;
* ``SOURCE_CONFLICT`` is displayed with every conflict reference
  (``SAFETY-INV-008``);
* ``FULL`` carries no invented failure reason.

The legacy renderer failed the second of these literally: its label table
mapped the absence of a rule to *"Düşük / uyarı yok"* - low, no warning - and
printed it for an axis nothing had been evaluated on.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.domain.hashing import sha256_digest
from pgx.reporting.errors import ReportFactError
from pgx.reporting.models import CanonicalAssessmentResult
from pgx.reporting.structured import StructuredReport

__all__ = [
    "FACT_LEDGER_SCHEMA_VERSION",
    "REQUIRED_PROVENANCE_FIELDS",
    "UNSAFE_LINE_TOKENS",
    "build_fact_ledger",
    "validate_fact_preservation",
    "validate_rendered_report",
    "validate_safe_status_rendering",
]

FACT_LEDGER_SCHEMA_VERSION = "pgx-report-fact-ledger/1"

#: Every pinned version a report must name (``SAFETY-INV-007``). A report
#: missing one of these cannot be traced back to what produced it, which is
#: the whole reason the assessment recorded them.
REQUIRED_PROVENANCE_FIELDS: Tuple[str, ...] = (
    "release_public_id", "release_manifest_hash", "software_version",
    "software_source_tree_hash", "dataset_public_id",
    "canonical_build_content_hash", "ruleset_public_id",
    "ruleset_content_hash", "evidence_build_key",
    "evidence_build_content_hash", "coverage_manifest_hash",
    "protocol_version", "protocol_content_hash", "source_policy_version",
    "source_policy_content_hash")

#: Tokens that must never share a rendered line with ``NOT_ASSESSED``.
#:
#: Deliberately narrower than the full reassurance vocabulary. The controlled
#: not-assessed sentence itself says the result "carries no level, no
#: assurance and no negative finding", and a check that fired on the word
#: "negative" inside its own denial would push the denial out of the report -
#: which is the failure it exists to prevent, arrived at from the other side.
UNSAFE_LINE_TOKENS: Tuple[str, ...] = (
    "dusuk", "risk yok", "uyari yok", "guvenli", "uygun", "temiz",
    "low", "no risk", "no warning", "safe", "suitable")

_FOLD = {
    ord("Ç"): "c", ord("ç"): "c", ord("Ğ"): "g", ord("ğ"): "g",
    ord("İ"): "i", ord("ı"): "i", ord("I"): "i", ord("Ö"): "o",
    ord("ö"): "o", ord("Ş"): "s", ord("ş"): "s", ord("Ü"): "u",
    ord("ü"): "u", ord("Â"): "a", ord("â"): "a", ord("Î"): "i",
    ord("î"): "i", ord("Û"): "u", ord("û"): "u",
}


def _fold(text: str) -> str:
    return text.translate(_FOLD).lower()


def _refuse(message: str, *, code: str, location: str,
            detail: Optional[Mapping[str, Any]] = None) -> None:
    raise ReportFactError(message, code=code, location=location,
                          detail=detail)


def build_fact_ledger(result: CanonicalAssessmentResult) -> Dict[str, Any]:
    """Enumerate every fact a report of this result must carry.

    Built from the result, never from the report, so it cannot be satisfied by
    a report that shaped the question to fit its answer. Hashed, so a ledger
    stored beside a published artifact can be shown to be the ledger that was
    checked.
    """
    if not isinstance(result, CanonicalAssessmentResult):
        _refuse("a fact ledger is built from a CanonicalAssessmentResult",
                code="REPORT_INPUT_INVALID", location="$.result")
    medications = []
    axes = []
    findings = []
    for medication in result.medications:
        medications.append({
            "drug_canonical_key": medication.drug_canonical_key,
            "requested_value": medication.requested_value,
            "attention_code": medication.attention_level,
            "coverage_code": medication.coverage_status,
            "coverage_reason_codes": list(medication.coverage_reason_codes),
        })
        for axis in medication.axes:
            axes.append({
                "axis": "%s/%s" % (axis.drug_canonical_key,
                                   axis.gene_canonical_key),
                "coverage_code": axis.coverage_status,
                "reason_codes": list(axis.coverage_reason_codes),
                "observed_phenotype": axis.observed_phenotype,
                "evidence_references": list(axis.evidence_references),
                "conflict_references": list(axis.conflict_references),
            })
        for finding in medication.findings:
            findings.append({
                "finding": "%s/%s" % (finding.drug_canonical_key,
                                      finding.gene_canonical_key),
                "attention_code": finding.attention_level,
                "phenotype": finding.phenotype,
                "rule_id": finding.rule_id,
                "rule_version": finding.rule_version,
                "rule_content_hash": finding.rule_content_hash,
                "rationale_reference": finding.rationale_reference,
                "evidence_references": list(finding.evidence_references),
                "effect_code": finding.effect_code,
                "explanation_code": finding.explanation_code,
            })
    provenance = dict(result.release_provenance)
    ledger = {
        "fact_ledger_schema_version": FACT_LEDGER_SCHEMA_VERSION,
        "assessment_id": result.assessment_id,
        "input_hash": result.input_hash,
        "output_hash": result.output_hash,
        "coverage_result_hash": result.coverage_result_hash,
        "canonical_result_hash": result.content_hash(),
        "overall_attention": result.overall_attention,
        "overall_coverage": result.overall_coverage,
        "overall_coverage_reason_codes":
            list(result.overall_coverage_reason_codes),
        "medications": medications,
        "axes": axes,
        "findings": findings,
        "evidence_references": list(result.evidence_references),
        "conflict_references": list(result.conflict_references),
        "observations": [item.get("gene_id")
                         for item in result.profile_observations],
        "release_provenance": {name: provenance.get(name)
                               for name in REQUIRED_PROVENANCE_FIELDS},
        "counts": {
            "medications": len(result.medications),
            "axes": len(axes),
            "findings": len(findings),
            "evidence_references": len(result.evidence_references),
            "conflict_references": len(result.conflict_references),
            "observations": len(result.profile_observations),
        },
    }
    ledger["ledger_hash"] = sha256_digest(ledger)
    return ledger


def validate_fact_preservation(result: CanonicalAssessmentResult,
                               report: StructuredReport) -> Dict[str, Any]:
    """Check that a report carries every fact its assessment recorded.

    Returns the ledger it checked against, so a caller can record it beside
    the artifact.

    Raises:
        ReportFactError: a fact was lost, a reference points at an entity the
            assessment does not contain, or a hash disagrees.
    """
    ledger = build_fact_ledger(result)

    if report.output_hash != result.output_hash:
        _refuse("the report records output hash %s and the assessment "
                "records %s" % (report.output_hash, result.output_hash),
                code="REPORT_HASH_MISMATCH", location="$.output_hash")
    if report.coverage_result_hash != result.coverage_result_hash:
        _refuse("the report and the assessment disagree about the coverage "
                "result hash", code="REPORT_COVERAGE_UNVERIFIABLE",
                location="$.coverage_result_hash")
    if report.canonical_result_hash != result.content_hash():
        _refuse("the report was built from a different set of facts than the "
                "one it is being checked against",
                code="REPORT_HASH_MISMATCH",
                location="$.canonical_result_hash")

    provenance = dict(report.release_provenance)
    missing_versions = tuple(name for name in REQUIRED_PROVENANCE_FIELDS
                             if not provenance.get(name))
    if missing_versions:
        _refuse("the report does not name %s (SAFETY-INV-007)"
                % ", ".join(missing_versions),
                code="REPORT_RELEASE_PROVENANCE_MISSING",
                location="$.release_provenance",
                detail={"missing": list(missing_versions)})
    for name in REQUIRED_PROVENANCE_FIELDS:
        if provenance.get(name) != ledger["release_provenance"][name]:
            _refuse("the report names %s=%r and the assessment pinned %r"
                    % (name, provenance.get(name),
                       ledger["release_provenance"][name]),
                    code="REPORT_RELEASE_PROVENANCE_MISSING",
                    location="$.release_provenance.%s" % name)

    expected_drugs = {item["drug_canonical_key"] for item in
                      ledger["medications"]}
    present_drugs = {section.drug_canonical_key
                     for section in report.medications}
    lost = tuple(sorted(expected_drugs - present_drugs))
    if lost:
        _refuse("the report omits medication(s) the assessment covered: %s"
                % ", ".join(lost), code="REPORT_FACT_LOST",
                location="$.medications", detail={"missing": list(lost)})
    invented = tuple(sorted(present_drugs - expected_drugs))
    if invented:
        _refuse("the report names medication(s) the assessment does not "
                "contain: %s" % ", ".join(invented),
                code="REPORT_ENTITY_NOT_PRESENT", location="$.medications",
                detail={"unknown": list(invented)})

    expected_axes = {item["axis"] for item in ledger["axes"]}
    present_axes = {"%s/%s" % (axis.drug_canonical_key,
                               axis.gene_canonical_key)
                    for axis in report.axes}
    lost = tuple(sorted(expected_axes - present_axes))
    if lost:
        _refuse("the report omits axis/axes the assessment recorded: %s"
                % ", ".join(lost), code="REPORT_FACT_LOST", location="$.axes",
                detail={"missing": list(lost)})

    expected_findings = {item["finding"] for item in ledger["findings"]}
    present_findings = {"%s/%s" % (finding.drug_canonical_key,
                                   finding.gene_canonical_key)
                        for finding in report.findings}
    lost = tuple(sorted(expected_findings - present_findings))
    if lost:
        _refuse("the report omits finding(s) the assessment calculated: %s"
                % ", ".join(lost), code="REPORT_FACT_LOST",
                location="$.findings", detail={"missing": list(lost)})

    expected_evidence = set(ledger["evidence_references"])
    present_evidence = set(report.evidence_references)
    lost = tuple(sorted(expected_evidence - present_evidence))
    if lost:
        _refuse("the report omits evidence reference(s) a finding rests on: "
                "%s (SAFETY-INV-006)" % ", ".join(lost),
                code="REPORT_EVIDENCE_MISSING",
                location="$.evidence_references",
                detail={"missing": list(lost)})

    expected_conflicts = set(ledger["conflict_references"])
    present_conflicts = set(report.conflict_references)
    lost = tuple(sorted(expected_conflicts - present_conflicts))
    if lost:
        _refuse("the report omits unresolved source conflict(s) the "
                "assessment preserved: %s (SAFETY-INV-008)" % ", ".join(lost),
                code="REPORT_CONFLICT_REFERENCE_LOST",
                location="$.conflict_references",
                detail={"missing": list(lost)})

    for item in ledger["findings"]:
        key = item["finding"]
        match = [finding for finding in report.findings
                 if "%s/%s" % (finding.drug_canonical_key,
                               finding.gene_canonical_key) == key]
        if not match:  # pragma: no cover - covered by the check above
            continue
        finding = match[0]
        if not finding.rule_id or finding.rule_id != item["rule_id"] or \
                finding.rule_content_hash != item["rule_content_hash"] or \
                finding.rule_version != item["rule_version"]:
            _refuse("finding %s does not name the governed rule, version and "
                    "content that produced it" % key,
                    code="REPORT_RULE_PROVENANCE_MISSING",
                    location="$.findings[%s]" % key)
        if set(finding.evidence_references) != set(item["evidence_references"]):
            _refuse("finding %s displays different evidence from what the "
                    "assessment recorded" % key,
                    code="REPORT_EVIDENCE_MISSING",
                    location="$.findings[%s].evidence_references" % key)
        if finding.effect_code != item["effect_code"] or \
                finding.explanation_code != item["explanation_code"]:
            _refuse("finding %s displays effect/explanation codes the "
                    "assessment did not record" % key,
                    code="REPORT_FACT_LOST",
                    location="$.findings[%s]" % key)

    for item in ledger["medications"]:
        section = report.section_for(item["drug_canonical_key"])
        if section.status.attention_code != item["attention_code"] or \
                section.status.coverage_code != item["coverage_code"]:
            _refuse("the report displays %s as %s/%s and the assessment "
                    "calculated %s/%s"
                    % (item["drug_canonical_key"],
                       section.status.attention_code,
                       section.status.coverage_code,
                       item["attention_code"], item["coverage_code"]),
                    code="REPORT_FACT_LOST",
                    location="$.medications[%s]" % item["drug_canonical_key"])
        if list(section.status.reason_codes) != item["coverage_reason_codes"]:
            _refuse("the report displays different coverage reasons for %s "
                    "than the assessment recorded" % item["drug_canonical_key"],
                    code="REPORT_FACT_LOST",
                    location="$.medications[%s].reason_codes"
                             % item["drug_canonical_key"])

    if report.overall.attention_code != ledger["overall_attention"] or \
            report.overall.coverage_code != ledger["overall_coverage"]:
        _refuse("the report's overall status is not the calculated one",
                code="REPORT_FACT_LOST", location="$.overall")
    if list(report.overall.reason_codes) != \
            ledger["overall_coverage_reason_codes"]:
        _refuse("the report's overall coverage reasons are not the calculated "
                "ones", code="REPORT_FACT_LOST",
                location="$.overall.reason_codes")

    present_observations = {item.get("gene_id")
                            for item in report.profile_observations}
    lost = tuple(sorted(set(ledger["observations"]) - present_observations))
    if lost:
        _refuse("the report omits phenotype observation(s) the assessment "
                "recorded: %s" % ", ".join(lost), code="REPORT_FACT_LOST",
                location="$.profile_observations",
                detail={"missing": list(lost)})
    return ledger


def validate_safe_status_rendering(report: StructuredReport) -> Dict[str, Any]:
    """Check how every status is displayed, not just what it says.

    Raises:
        ReportFactError: a status would be displayed in a way that reads as
            reassurance, or a required qualifier is absent.
    """
    from pgx.reporting.templates import ATTENTION_LABELS, statement

    checked: List[str] = []
    blocks = [("$.overall", report.overall)] + [
        ("$.medications[%s]" % section.drug_canonical_key, section.status)
        for section in report.medications]

    for location, status in blocks:
        if not status.attention_code or not status.coverage_code:
            _refuse("attention and coverage are displayed together, always",
                    code="REPORT_STATUS_RENDERING_UNSAFE", location=location)
        if not status.adjacency_note:
            _refuse("the block does not say that attention and coverage are "
                    "separate results", code="REPORT_STATUS_RENDERING_UNSAFE",
                    location=location)
        expected = ATTENTION_LABELS[status.attention_code][report.locale]
        if status.attention_label != expected:
            _refuse("attention %s is displayed as %r rather than the "
                    "controlled label %r"
                    % (status.attention_code, status.attention_label,
                       expected),
                    code="REPORT_STATUS_RENDERING_UNSAFE",
                    location=location + ".attention_label")
        folded = _fold(status.attention_label)
        if status.attention_code == "NOT_ASSESSED":
            for token in UNSAFE_LINE_TOKENS:
                if token in folded:
                    _refuse("NOT_ASSESSED is displayed with %r in its label; "
                            "missing data is never low, safe, normal or "
                            "suitable (SAFETY-INV-001)" % token,
                            code="REPORT_STATUS_RENDERING_UNSAFE",
                            location=location + ".attention_label")
            if not status.carries(statement("not_assessed", report.locale)):
                _refuse("NOT_ASSESSED is displayed without the controlled "
                        "sentence stating what it means",
                        code="REPORT_STATUS_RENDERING_UNSAFE",
                        location=location + ".qualifier_statements")
        if status.attention_code == "NO_ACTIVE_ATTENTION" and \
                status.coverage_code != "FULL":
            _refuse("NO_ACTIVE_ATTENTION is displayed beside %s coverage "
                    "(SAFETY-INV-001)" % status.coverage_code,
                    code="REPORT_STATUS_RENDERING_UNSAFE", location=location)
        if status.coverage_code == "FULL":
            if status.reason_codes:
                _refuse("FULL coverage is displayed with failure reason(s) "
                        "nothing recorded",
                        code="REPORT_STATUS_RENDERING_UNSAFE",
                        location=location + ".reason_codes")
        else:
            if not status.reason_codes:
                _refuse("coverage %s is displayed without a reason; "
                        "unexplained absence is how absence becomes "
                        "reassurance" % status.coverage_code,
                        code="REPORT_STATUS_RENDERING_UNSAFE",
                        location=location + ".reason_codes")
            if not status.qualifier_statements:
                _refuse("incomplete coverage is displayed without the "
                        "controlled sentence qualifying it",
                        code="REPORT_STATUS_RENDERING_UNSAFE",
                        location=location + ".qualifier_statements")
        if status.attention_code in ("HIGH", "MEDIUM", "LOW") and \
                status.coverage_code != "FULL" and \
                not status.carries(statement(
                    "high_attention_partial_coverage", report.locale)):
            _refuse("a level over incomplete coverage is displayed without "
                    "the controlled sentence saying it is the worst level "
                    "among the evaluated subset",
                    code="REPORT_STATUS_RENDERING_UNSAFE",
                    location=location + ".qualifier_statements")
        if status.coverage_code == "SOURCE_CONFLICT" and \
                not status.carries(statement("source_conflict",
                                             report.locale)):
            _refuse("a source conflict is displayed without the controlled "
                    "sentence saying it is preserved and unresolved "
                    "(SAFETY-INV-008)",
                    code="REPORT_STATUS_RENDERING_UNSAFE",
                    location=location + ".qualifier_statements")
        checked.append(location)

    for section in report.medications:
        if section.conflict_axes and not section.conflict_references:
            _refuse("a source-conflict axis is displayed without the conflict "
                    "it preserves (SAFETY-INV-008)",
                    code="REPORT_CONFLICT_REFERENCE_LOST",
                    location="$.medications[%s].conflict_references"
                             % section.drug_canonical_key)
        uncovered = [axis for axis in section.axes if not axis.is_covered]
        if uncovered and not section.not_assessed_axes:
            _refuse("a medication with uncovered axes displays no "
                    "not-assessed block", code="REPORT_STATUS_RENDERING_UNSAFE",
                    location="$.medications[%s].not_assessed_axes"
                             % section.drug_canonical_key)
        for axis in section.not_assessed_axes:
            if not axis.reason_codes:
                _refuse("an uncovered axis is displayed without a reason",
                        code="REPORT_STATUS_RENDERING_UNSAFE",
                        location="$.medications[%s].not_assessed_axes[%s]"
                                 % (section.drug_canonical_key,
                                    axis.gene_canonical_key))
    return {"checked_blocks": checked,
            "unsafe_tokens": list(UNSAFE_LINE_TOKENS)}


def validate_rendered_report(report: StructuredReport, text: str,
                             ledger: Optional[Mapping[str, Any]] = None
                             ) -> Dict[str, Any]:
    """Check the rendered document, not only the structure behind it.

    A fact present in a structure and absent from the page is a fact the
    reader does not have, so the references, codes and hashes are looked for
    in the text itself.
    """
    if not isinstance(text, str) or not text.strip():
        _refuse("a rendered report is non-empty text",
                code="REPORT_INPUT_INVALID", location="$.text")
    required: List[Tuple[str, str]] = [("output_hash", report.output_hash),
                                       ("input_hash", report.input_hash)]
    for name in REQUIRED_PROVENANCE_FIELDS:
        value = dict(report.release_provenance).get(name)
        if value:
            required.append(("release_provenance.%s" % name, str(value)))
    for reference in report.evidence_references:
        required.append(("evidence", reference))
    for reference in report.conflict_references:
        required.append(("conflict", reference))
    for finding in report.findings:
        required.append(("rule", finding.rule_id))
        required.append(("rationale", finding.rationale_reference))
    for section in report.medications:
        required.append(("medication", section.drug_canonical_key))
        for axis in section.axes:
            required.append(("axis", axis.gene_canonical_key))
            for code in axis.reason_codes:
                required.append(("axis_reason", code))
    for code in report.overall.reason_codes:
        required.append(("overall_reason", code))

    from pgx.reporting.render import escape_markdown

    def _shown(value: str) -> bool:
        """Present in either form the renderer may have used.

        A governed value inside a code span is printed literally; the same
        value in running text is backslash-escaped. Checking only one form
        would make this validator agree with one half of the renderer and
        silently stop checking the other.
        """
        return value in text or escape_markdown(value) in text

    missing = [(kind, value) for kind, value in required
               if not _shown(value)]
    if missing:
        _refuse("the rendered report does not show %d recorded fact(s), "
                "starting with %s=%r"
                % (len(missing), missing[0][0], missing[0][1]),
                code="REPORT_FACT_LOST", location="$.rendered",
                detail={"missing": [list(item) for item in missing[:20]]})

    if report.canonical_warning not in text and \
            escape_markdown(report.canonical_warning) not in text:
        _refuse("the rendered report does not carry the canonical clinical "
                "warning", code="REPORT_STATUS_RENDERING_UNSAFE",
                location="$.rendered.canonical_warning")

    for number, line in enumerate(text.splitlines(), start=1):
        if "NOT_ASSESSED" not in line:
            continue
        folded = _fold(line)
        for token in UNSAFE_LINE_TOKENS:
            if token in folded:
                _refuse("line %d displays NOT_ASSESSED beside %r; missing "
                        "data is never low, safe, normal or suitable "
                        "(SAFETY-INV-001)" % (number, token),
                        code="REPORT_STATUS_RENDERING_UNSAFE",
                        location="$.rendered.line[%d]" % number)

    for section in report.medications:
        if section.status.coverage_code != "PARTIAL":
            continue
        for axis in section.not_assessed_axes:
            if not _shown(axis.gene_canonical_key):
                _refuse("a partially covered medication does not show the "
                        "axis %s it could not evaluate"
                        % axis.gene_canonical_key,
                        code="REPORT_FACT_LOST",
                        location="$.rendered.medications[%s]"
                                 % section.drug_canonical_key)
    return {
        "checked_facts": len(required),
        "ledger_hash": (dict(ledger).get("ledger_hash")
                        if ledger is not None else None),
        "rendered_length": len(text),
    }
