# -*- coding: utf-8 -*-
"""The structured report: a presentation projection and nothing else (WP-15).

A :class:`StructuredReport` is what a renderer is allowed to see. It is built
from a :class:`~pgx.reporting.models.CanonicalAssessmentResult` by a total
function that adds labels, section structure and controlled sentences - and
adds no facts.

**Every governed value appears beside its label, never instead of it.** The
report carries ``attention_code`` *and* ``attention_label``, ``coverage_code``
*and* ``coverage_label``, every reason code and every reason label. A reader
sees the sentence; a machine, an auditor and the next work package see the
code that produced it.

**Attention and coverage are one block, always.** They are constructed
together in :class:`OverallStatus` and in every
:class:`MedicationSection`, so there is no arrangement of this type in which
one is present and the other is not. That is ``SAFETY-INV-001`` expressed as a
shape rather than as a rule somebody has to remember while editing a template.

**Absence is a section, not a silence.** Axes that were not evaluated,
medications with no findings, findings whose ruleset carries no effect code,
and unresolved source conflicts each get an explicit block with its reasons.
A report that simply omitted them would be shorter, would look cleaner, and
would be a different and more reassuring claim.

``report_hash`` covers the whole validated report *including* the template
version, the locale and the report schema version - which is exactly how it
differs from ``output_hash``. Two locales over one assessment share an output
hash and have two report hashes: the first answers "are these the same
facts?", the second answers "is this the same document?".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.domain.claims import canonical_clinical_warning
from pgx.domain.hashing import sha256_digest
from pgx.domain.immutable import freeze_json
from pgx.reporting.errors import ReportInputError, ReportRenderError
from pgx.reporting.models import (AxisFacts, CanonicalAssessmentResult,
                                  FindingFacts, MedicationFacts)
from pgx.reporting.templates import (ATTENTION_LABELS, COVERAGE_LABELS,
                                     COVERAGE_REASON_LABELS,
                                     INPUT_KIND_LABELS, MEDICATION_QUESTIONS,
                                     MODE_LABELS, OBSERVATION_STATE_LABELS,
                                     TEMPLATE_VERSION, label, question_labels,
                                     require_locale, require_template,
                                     statement)

__all__ = [
    "REPORT_SCHEMA_VERSION",
    "UNSAFE_NOT_ASSESSED_WORDS",
    "AxisLine",
    "FindingLine",
    "MedicationSection",
    "OverallStatus",
    "StructuredReport",
    "UncertaintyItem",
    "build_structured_report",
]

REPORT_SCHEMA_VERSION = "pgx-structured-report/1"

#: Words a ``NOT_ASSESSED`` presentation must never sit beside, folded and
#: matched by the safe-status check in :mod:`pgx.reporting.validator`. This is
#: the list the legacy renderer failed: its ``RISK_LABEL_TR["none"]`` was
#: literally "Düşük / uyarı yok" - low, no warning - for an axis nothing had
#: been evaluated on.
UNSAFE_NOT_ASSESSED_WORDS: Tuple[str, ...] = (
    "dusuk", "risk yok", "uyari yok", "guvenli", "normal", "uygun", "temiz",
    "low", "no risk", "no warning", "safe", "suitable", "clear", "fine",
    "negative", "olumsuz bulgu yok",
)


def _refuse(message: str, *, location: str,
            code: str = "REPORT_INPUT_INVALID") -> None:
    raise ReportInputError(message, code=code, location=location)


def _plain(value: Any) -> Any:
    """A JSON-serialisable copy of a deeply frozen value.

    Everything this module holds is frozen so a renderer cannot edit a
    governed fact in place; frozen mappings and tuples are not what ``json``
    writes. The JSON view thaws into a copy, which is the point: a caller may
    do what it likes with the copy and the report is unchanged.
    """
    if isinstance(value, Mapping):
        return {key: _plain(value[key]) for key in value}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class AxisLine:
    """One drug-gene axis, ready to display, with its code and its label."""

    drug_canonical_key: str
    gene_canonical_key: str
    coverage_code: str
    coverage_label: str
    reason_codes: Tuple[str, ...]
    reason_labels: Tuple[str, ...]
    observed_phenotype: Optional[str]
    observation_state_code: str
    observation_state_label: str
    rule_references: Tuple[Mapping[str, Any], ...] = ()
    evidence_references: Tuple[str, ...] = ()
    conflict_references: Tuple[str, ...] = ()
    declaration_id: Optional[str] = None

    def __post_init__(self) -> None:
        if len(self.reason_codes) != len(self.reason_labels):
            _refuse("every reason code is displayed with its own label",
                    location="$.axes")
        object.__setattr__(self, "rule_references",
                           tuple(freeze_json(dict(item))
                                 for item in self.rule_references))

    @property
    def is_covered(self) -> bool:
        return self.coverage_code == "FULL"

    def to_json(self) -> Dict[str, Any]:
        return {
            "drug_canonical_key": self.drug_canonical_key,
            "gene_canonical_key": self.gene_canonical_key,
            "coverage_code": self.coverage_code,
            "coverage_label": self.coverage_label,
            "reason_codes": list(self.reason_codes),
            "reason_labels": list(self.reason_labels),
            "observed_phenotype": self.observed_phenotype,
            "observation_state_code": self.observation_state_code,
            "observation_state_label": self.observation_state_label,
            "rule_references": [_plain(item)
                                for item in self.rule_references],
            "evidence_references": list(self.evidence_references),
            "conflict_references": list(self.conflict_references),
            "declaration_id": self.declaration_id,
        }


@dataclass(frozen=True, slots=True)
class FindingLine:
    """One calculated finding, ready to display, with its whole chain."""

    drug_canonical_key: str
    gene_canonical_key: str
    phenotype: str
    attention_code: str
    attention_label: str
    rule_id: str
    rule_family_id: str
    rule_version: int
    rule_content_hash: str
    rationale_reference: str
    curation_revision_id: str
    curation_revision_hash: str
    evidence_references: Tuple[str, ...]
    effect_code: Optional[str] = None
    explanation_code: Optional[str] = None
    codes_absent_statement: Optional[str] = None

    def __post_init__(self) -> None:
        where = "$.findings[%s/%s]" % (self.drug_canonical_key,
                                       self.gene_canonical_key)
        if not self.evidence_references:
            _refuse("a displayed finding names the evidence behind it "
                    "(SAFETY-INV-006)", location=where,
                    code="REPORT_EVIDENCE_MISSING")
        if not self.rule_id or not self.rule_content_hash:
            _refuse("a displayed finding names the governed rule and the "
                    "exact content that produced it", location=where,
                    code="REPORT_RULE_PROVENANCE_MISSING")
        has_codes = bool(self.effect_code or self.explanation_code)
        if not has_codes and not self.codes_absent_statement:
            _refuse("a finding whose ruleset carries no effect or explanation "
                    "code states that in a controlled sentence rather than "
                    "leaving a blank a reader will fill in", location=where)
        if has_codes and self.codes_absent_statement:
            _refuse("a finding that carries governed codes does not also "
                    "state that it carries none", location=where)

    def to_json(self) -> Dict[str, Any]:
        return {
            "drug_canonical_key": self.drug_canonical_key,
            "gene_canonical_key": self.gene_canonical_key,
            "phenotype": self.phenotype,
            "attention_code": self.attention_code,
            "attention_label": self.attention_label,
            "rule_id": self.rule_id,
            "rule_family_id": self.rule_family_id,
            "rule_version": self.rule_version,
            "rule_content_hash": self.rule_content_hash,
            "rationale_reference": self.rationale_reference,
            "curation_revision_id": self.curation_revision_id,
            "curation_revision_hash": self.curation_revision_hash,
            "evidence_references": list(self.evidence_references),
            "effect_code": self.effect_code,
            "explanation_code": self.explanation_code,
            "codes_absent_statement": self.codes_absent_statement,
        }


@dataclass(frozen=True, slots=True)
class OverallStatus:
    """Attention and coverage, together, at one level of the report.

    One type holding both, rather than two fields anybody could render apart.
    The adjacency note travels with them so no template has to remember to add
    it.
    """

    attention_code: str
    attention_label: str
    coverage_code: str
    coverage_label: str
    reason_codes: Tuple[str, ...]
    reason_labels: Tuple[str, ...]
    adjacency_note: str
    qualifier_statements: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("attention_code", "attention_label", "coverage_code",
                     "coverage_label", "adjacency_note"):
            if not getattr(self, name):
                _refuse("a status block carries %s" % name,
                        location="$.status",
                        code="REPORT_STATUS_RENDERING_UNSAFE")
        if len(self.reason_codes) != len(self.reason_labels):
            _refuse("every coverage reason is displayed with its own label",
                    location="$.status")
        if self.attention_code == "NO_ACTIVE_ATTENTION" and \
                self.coverage_code != "FULL":
            _refuse("NO_ACTIVE_ATTENTION is displayed only beside FULL "
                    "coverage (SAFETY-INV-001)", location="$.status",
                    code="REPORT_STATUS_RENDERING_UNSAFE")
        if self.coverage_code == "FULL":
            if self.reason_codes:
                _refuse("FULL coverage displays no failure reason; a caveat "
                        "on a complete evaluation is one nobody has to read",
                        location="$.status.reason_codes",
                        code="REPORT_STATUS_RENDERING_UNSAFE")
        elif not self.reason_codes:
            _refuse("a status that is not FULL displays at least one reason "
                    "code", location="$.status",
                    code="REPORT_STATUS_RENDERING_UNSAFE")
        object.__setattr__(self, "qualifier_statements",
                           tuple(self.qualifier_statements))
        if not self.qualifier_statements:
            _refuse("a status block carries at least one controlled sentence "
                    "saying what its combination of attention and coverage "
                    "does and does not mean. A bare pair of codes is where a "
                    "reader supplies their own meaning.",
                    location="$.status.qualifier_statements",
                    code="REPORT_STATUS_RENDERING_UNSAFE")

    def carries(self, text: str) -> bool:
        """Whether one controlled sentence is displayed in this block."""
        return text in self.qualifier_statements

    def to_json(self) -> Dict[str, Any]:
        return {
            "attention_code": self.attention_code,
            "attention_label": self.attention_label,
            "coverage_code": self.coverage_code,
            "coverage_label": self.coverage_label,
            "reason_codes": list(self.reason_codes),
            "reason_labels": list(self.reason_labels),
            "adjacency_note": self.adjacency_note,
            "qualifier_statements": list(self.qualifier_statements),
        }


@dataclass(frozen=True, slots=True)
class MedicationSection:
    """One medication, answering all eight required questions."""

    drug_canonical_key: str
    requested_value: str
    status: OverallStatus
    axes: Tuple[AxisLine, ...]
    findings: Tuple[FindingLine, ...]
    not_assessed_axes: Tuple[AxisLine, ...]
    conflict_axes: Tuple[AxisLine, ...]
    conflict_references: Tuple[str, ...]
    evidence_references: Tuple[str, ...]
    rule_references: Tuple[str, ...]
    answers: Mapping[str, Mapping[str, Any]] = field(
        default_factory=lambda: freeze_json({}))
    axis_count: int = 0
    conflicted_axis_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "answers", freeze_json(dict(self.answers)))
        missing = tuple(identifier for identifier, _text in MEDICATION_QUESTIONS
                        if identifier not in self.answers)
        if missing:
            _refuse("the section for %s answers none of: %s. Every medication "
                    "section answers all eight questions, or the reader is "
                    "left to supply the missing one."
                    % (self.drug_canonical_key, ", ".join(missing)),
                    location="$.medications[%s].answers"
                             % self.drug_canonical_key)

    def to_json(self) -> Dict[str, Any]:
        return {
            "drug_canonical_key": self.drug_canonical_key,
            "requested_value": self.requested_value,
            "status": self.status.to_json(),
            "axis_count": self.axis_count,
            "conflicted_axis_count": self.conflicted_axis_count,
            "axes": [axis.to_json() for axis in self.axes],
            "findings": [finding.to_json() for finding in self.findings],
            "not_assessed_axes": [axis.to_json()
                                  for axis in self.not_assessed_axes],
            "conflict_axes": [axis.to_json() for axis in self.conflict_axes],
            "conflict_references": list(self.conflict_references),
            "evidence_references": list(self.evidence_references),
            "rule_references": list(self.rule_references),
            "answers": {key: _plain(value)
                        for key, value in self.answers.items()},
        }


@dataclass(frozen=True, slots=True)
class UncertaintyItem:
    """One thing this report does not know, said out loud."""

    kind: str
    subject: str
    statement_text: str
    codes: Tuple[str, ...] = ()
    references: Tuple[str, ...] = ()

    def to_json(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "subject": self.subject,
            "statement_text": self.statement_text,
            "codes": list(self.codes),
            "references": list(self.references),
        }


@dataclass(frozen=True, slots=True)
class StructuredReport:
    """One immutable report, before it is rendered into any format."""

    assessment_id: str
    locale: str
    template_version: str
    mode_code: str
    mode_label: str
    input_kind_code: str
    input_kind_label: str
    input_hash: str
    output_hash: str
    coverage_result_hash: str
    canonical_result_hash: str
    overall: OverallStatus
    medications: Tuple[MedicationSection, ...]
    profile_observations: Tuple[Mapping[str, Any], ...]
    uncertainty: Tuple[UncertaintyItem, ...]
    release_provenance: Mapping[str, Any]
    pointer_audit: Mapping[str, Any]
    canonical_warning: str
    disclaimer: str
    adjacency_note: str
    profile_note: str
    section_titles: Mapping[str, str]
    question_labels: Mapping[str, str]
    engine_contract_version: str = ""
    computation_schema_version: str = ""
    case_id: Optional[str] = None
    warnings: Tuple[str, ...] = ()
    report_schema_version: str = REPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_locale(self.locale)
        require_template(self.template_version)
        if not self.medications:
            _refuse("a report has at least one medication section",
                    location="$.medications")
        if self.canonical_warning != canonical_clinical_warning(self.locale):
            _refuse("the canonical clinical warning must be the one "
                    "pgx.domain.claims publishes, character for character. A "
                    "report carrying a paraphrase carries a second warning "
                    "nobody approved.", location="$.canonical_warning",
                    code="REPORT_STATUS_RENDERING_UNSAFE")
        if not self.release_provenance:
            _refuse("a report names every version it was produced from "
                    "(SAFETY-INV-007)", location="$.release_provenance",
                    code="REPORT_RELEASE_PROVENANCE_MISSING")
        for name in ("release_provenance", "pointer_audit", "section_titles",
                     "question_labels"):
            object.__setattr__(self, name,
                               freeze_json(dict(getattr(self, name))))
        object.__setattr__(
            self, "profile_observations",
            tuple(freeze_json(dict(item))
                  for item in self.profile_observations))

    # -- reading ---------------------------------------------------------

    @property
    def findings(self) -> Tuple[FindingLine, ...]:
        return tuple(finding for section in self.medications
                     for finding in section.findings)

    @property
    def axes(self) -> Tuple[AxisLine, ...]:
        return tuple(axis for section in self.medications
                     for axis in section.axes)

    @property
    def conflict_references(self) -> Tuple[str, ...]:
        found: List[str] = []
        for section in self.medications:
            for reference in section.conflict_references:
                if reference not in found:
                    found.append(reference)
        return tuple(sorted(found))

    @property
    def evidence_references(self) -> Tuple[str, ...]:
        found: List[str] = []
        for section in self.medications:
            for reference in section.evidence_references:
                if reference not in found:
                    found.append(reference)
        return tuple(sorted(found))

    def section_for(self, drug_canonical_key: str
                    ) -> Optional[MedicationSection]:
        for section in self.medications:
            if section.drug_canonical_key == drug_canonical_key:
                return section
        return None

    # -- identity --------------------------------------------------------

    def semantic_content(self) -> Dict[str, Any]:
        """Everything ``report_hash`` covers.

        Includes the template version, the locale and the report schema
        version, which is precisely what ``output_hash`` excludes. It does
        *not* include the case id, the actor or any timestamp: those label the
        run, and two reports of one assessment must be comparable across them.
        """
        return {
            "report_schema_version": self.report_schema_version,
            "template_version": self.template_version,
            "locale": self.locale,
            "assessment_engine_contract_version": self.engine_contract_version,
            "computation_schema_version": self.computation_schema_version,
            "mode_code": self.mode_code,
            "input_kind_code": self.input_kind_code,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "coverage_result_hash": self.coverage_result_hash,
            "canonical_result_hash": self.canonical_result_hash,
            "overall": self.overall.to_json(),
            "medication_count": len(self.medications),
            "medications": [section.to_json() for section in self.medications],
            "profile_observations": [_plain(item)
                                     for item in self.profile_observations],
            "uncertainty": [item.to_json() for item in self.uncertainty],
            "release_provenance": _plain(self.release_provenance),
            "canonical_warning": self.canonical_warning,
            "disclaimer": self.disclaimer,
            "adjacency_note": self.adjacency_note,
            "warnings": list(self.warnings),
        }

    def report_hash(self) -> str:
        return sha256_digest(self.semantic_content())

    def to_json(self) -> Dict[str, Any]:
        payload = self.semantic_content()
        payload["assessment_id"] = self.assessment_id
        payload["case_id"] = self.case_id
        payload["mode_label"] = self.mode_label
        payload["input_kind_label"] = self.input_kind_label
        payload["pointer_audit"] = _plain(self.pointer_audit)
        payload["profile_note"] = self.profile_note
        payload["section_titles"] = _plain(self.section_titles)
        payload["question_labels"] = _plain(self.question_labels)
        payload["report_hash"] = self.report_hash()
        return payload


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def _axis_line(axis: AxisFacts, locale: str) -> AxisLine:
    reason_labels = tuple(label(COVERAGE_REASON_LABELS, code, locale,
                                table_name="coverage_reason")
                          for code in axis.coverage_reason_codes)
    state = axis.observation_state or "NOT_EVALUATED"
    return AxisLine(
        drug_canonical_key=axis.drug_canonical_key,
        gene_canonical_key=axis.gene_canonical_key,
        coverage_code=axis.coverage_status,
        coverage_label=label(COVERAGE_LABELS, axis.coverage_status, locale,
                             table_name="coverage"),
        reason_codes=tuple(axis.coverage_reason_codes),
        reason_labels=reason_labels,
        observed_phenotype=axis.observed_phenotype,
        observation_state_code=state,
        observation_state_label=label(OBSERVATION_STATE_LABELS, state, locale,
                                      table_name="observation_state"),
        rule_references=axis.rule_references,
        evidence_references=axis.evidence_references,
        conflict_references=axis.conflict_references,
        declaration_id=axis.declaration_id)


def _finding_line(finding: FindingFacts, locale: str) -> FindingLine:
    absent = (None if finding.has_governed_codes
              else statement("no_governed_codes", locale))
    return FindingLine(
        drug_canonical_key=finding.drug_canonical_key,
        gene_canonical_key=finding.gene_canonical_key,
        phenotype=finding.phenotype,
        attention_code=finding.attention_level,
        attention_label=label(ATTENTION_LABELS, finding.attention_level,
                              locale, table_name="attention"),
        rule_id=finding.rule_id,
        rule_family_id=finding.rule_family_id,
        rule_version=finding.rule_version,
        rule_content_hash=finding.rule_content_hash,
        rationale_reference=finding.rationale_reference,
        curation_revision_id=finding.curation_revision_id,
        curation_revision_hash=finding.curation_revision_hash,
        evidence_references=finding.evidence_references,
        effect_code=finding.effect_code,
        explanation_code=finding.explanation_code,
        codes_absent_statement=absent)


#: Which controlled sentences a status combination requires. Every rule is a
#: predicate over the *pair*, because that is what decides what a reader needs
#: told: ``HIGH`` alone is a level, ``HIGH`` over ``PARTIAL`` is a level over
#: a subset, and the difference between them is the whole point.
#:
#: The rules accumulate rather than compete. A ``SOURCE_CONFLICT`` axis whose
#: medication is ``NOT_ASSESSED`` needs both sentences: one says the conflict
#: is preserved and unresolved, the other says the absence of a level is not
#: a result. An earlier version picked the first matching rule and dropped the
#: conflict sentence, which is exactly the kind of quiet omission this layer
#: exists to prevent.
_QUALIFIER_RULES: Tuple[Tuple[str, Any], ...] = (
    ("source_conflict",
     lambda attention, coverage: coverage == "SOURCE_CONFLICT"),
    ("not_assessed",
     lambda attention, coverage: attention == "NOT_ASSESSED"),
    ("full_coverage",
     lambda attention, coverage: coverage == "FULL"),
    ("partial_coverage",
     lambda attention, coverage: coverage == "PARTIAL"),
    ("high_attention_partial_coverage",
     lambda attention, coverage: coverage != "FULL" and attention in
     ("HIGH", "MEDIUM", "LOW")),
)


def _status(attention_code: str, coverage_code: str,
            reason_codes: Sequence[str], locale: str) -> OverallStatus:
    """Attention and coverage, plus every sentence the combination requires.

    See :data:`_QUALIFIER_RULES`. The result always carries at least one
    sentence; :class:`OverallStatus` refuses a block that carries none, so a
    combination nobody wrote a rule for fails loudly rather than rendering as
    a bare pair of codes.
    """
    statements = tuple(statement(key, locale)
                       for key, applies in _QUALIFIER_RULES
                       if applies(attention_code, coverage_code))
    return OverallStatus(
        attention_code=attention_code,
        attention_label=label(ATTENTION_LABELS, attention_code, locale,
                              table_name="attention"),
        coverage_code=coverage_code,
        coverage_label=label(COVERAGE_LABELS, coverage_code, locale,
                             table_name="coverage"),
        reason_codes=tuple(reason_codes),
        reason_labels=tuple(label(COVERAGE_REASON_LABELS, code, locale,
                                  table_name="coverage_reason")
                            for code in reason_codes),
        adjacency_note=statement("attention_and_coverage", locale),
        qualifier_statements=statements)


def _answers(medication: MedicationFacts, section_axes: Sequence[AxisLine],
             findings: Sequence[FindingLine], status: OverallStatus,
             provenance: Mapping[str, Any], locale: str
             ) -> Dict[str, Dict[str, Any]]:
    """The eight answers, built from facts rather than composed as prose."""
    not_assessed = [axis for axis in section_axes if not axis.is_covered]
    rules = sorted({finding.rule_id for finding in findings})
    evidence = sorted({reference for finding in findings
                       for reference in finding.evidence_references})
    conflicts = sorted({reference for axis in section_axes
                        for reference in axis.conflict_references})
    limits = [statement("attention_and_coverage", locale)]
    if status.attention_code == "NOT_ASSESSED":
        limits.append(statement("not_assessed", locale))
    if not findings:
        limits.append(statement("no_findings_for_medication", locale))
    return {
        "which_medication": {
            "values": [medication.requested_value],
            "codes": [medication.drug_canonical_key],
            "references": [], "statements": []},
        "attention_level": {
            "values": [status.attention_label],
            "codes": [status.attention_code],
            "references": [],
            "statements": list(status.qualifier_statements)},
        "coverage": {
            "values": [status.coverage_label],
            "codes": [status.coverage_code] + list(status.reason_codes),
            "references": [axis.gene_canonical_key for axis in section_axes
                           if axis.is_covered],
            "statements": [status.adjacency_note]},
        "not_assessed": {
            "values": [axis.observation_state_label for axis in not_assessed],
            "codes": sorted({code for axis in not_assessed
                             for code in axis.reason_codes}),
            "references": [axis.gene_canonical_key for axis in not_assessed],
            "statements": ([statement("not_assessed", locale)]
                           if not_assessed else
                           [statement("full_coverage", locale)])},
        # A medication with no findings still answers "which rule?" and
        # "which evidence?" - with the controlled sentence saying there is
        # none and why, rather than with a blank a reader fills in. An empty
        # answer is not a short answer; it is an unanswered question in a
        # document that looks complete.
        "rules": {
            "values": [str(finding.rule_version) for finding in findings],
            "codes": rules,
            "references": [finding.rationale_reference
                           for finding in findings],
            "statements": ([] if findings else
                           [statement("no_findings_for_medication",
                                      locale)])},
        "evidence": {
            "values": [], "codes": [], "references": evidence,
            "statements": ([] if evidence else
                           [statement("no_findings_for_medication",
                                      locale)])},
        "versions": {
            "values": [], "references": [],
            "codes": [provenance.get("release_public_id", ""),
                      provenance.get("ruleset_public_id", ""),
                      provenance.get("dataset_public_id", "")],
            "statements": []},
        "limits": {
            "values": [], "codes": list(conflicts), "references": conflicts,
            "statements": limits},
    }


def _uncertainty(result: CanonicalAssessmentResult, locale: str
                 ) -> Tuple[UncertaintyItem, ...]:
    """Everything this report does not know, enumerated rather than implied."""
    items: List[UncertaintyItem] = []
    for medication in result.medications:
        if medication.attention_level == "NOT_ASSESSED":
            items.append(UncertaintyItem(
                kind="MEDICATION_NOT_ASSESSED",
                subject=medication.drug_canonical_key,
                statement_text=statement("not_assessed", locale),
                codes=tuple(medication.coverage_reason_codes)))
        elif medication.coverage_status != "FULL":
            items.append(UncertaintyItem(
                kind="MEDICATION_PARTIALLY_ASSESSED",
                subject=medication.drug_canonical_key,
                statement_text=statement(
                    "high_attention_partial_coverage", locale),
                codes=tuple(medication.coverage_reason_codes),
                references=tuple(axis.gene_canonical_key
                                 for axis in medication.uncovered_axes)))
        for axis in medication.conflicted_axes:
            items.append(UncertaintyItem(
                kind="SOURCE_CONFLICT",
                subject="%s/%s" % (axis.drug_canonical_key,
                                   axis.gene_canonical_key),
                statement_text=statement("source_conflict", locale),
                codes=tuple(axis.coverage_reason_codes),
                references=tuple(axis.conflict_references)))
        for finding in medication.findings:
            if finding.has_governed_codes:
                continue
            items.append(UncertaintyItem(
                kind="NO_GOVERNED_CODES",
                subject="%s/%s" % (finding.drug_canonical_key,
                                   finding.gene_canonical_key),
                statement_text=statement("no_governed_codes", locale),
                references=(finding.rationale_reference,)
                           + tuple(finding.evidence_references)))
    for observation in result.profile_observations:
        if observation.get("status") == "NORMALIZED":
            continue
        items.append(UncertaintyItem(
            kind="OBSERVATION_NOT_NORMALIZED",
            subject=observation.get("gene_id", ""),
            statement_text=label(OBSERVATION_STATE_LABELS,
                                 observation.get("status", "NOT_EVALUATED"),
                                 locale, table_name="observation_state"),
            codes=tuple(code for code in (observation.get("reason_code"),)
                        if code)))
    return tuple(items)


def build_structured_report(result: CanonicalAssessmentResult, *,
                            locale: str = "tr",
                            template_version: str = TEMPLATE_VERSION
                            ) -> StructuredReport:
    """Project one canonical result into one structured report.

    Total and deterministic: same result, same locale, same template, same
    report - including the order of every collection. It reads nothing but the
    result and the label tables, and it computes no fact.
    """
    if not isinstance(result, CanonicalAssessmentResult):
        raise ReportInputError(
            "a report is built from a CanonicalAssessmentResult, not from %r. "
            "Accepting a loose document here would be a second, unchecked way "
            "into the reporting layer." % type(result).__name__,
            code="REPORT_INPUT_INVALID", location="$.result")
    key = require_locale(locale)
    require_template(template_version)

    from pgx.reporting.templates import SECTION_TITLES
    titles = {name: label(SECTION_TITLES, name, key, table_name="section")
              for name in SECTION_TITLES}

    sections: List[MedicationSection] = []
    for medication in result.medications:
        axes = tuple(_axis_line(axis, key) for axis in medication.axes)
        findings = tuple(_finding_line(finding, key)
                         for finding in medication.findings)
        status = _status(medication.attention_level,
                         medication.coverage_status,
                         medication.coverage_reason_codes, key)
        not_assessed = tuple(axis for axis in axes if not axis.is_covered)
        conflicts = tuple(axis for axis in axes
                          if axis.coverage_code == "SOURCE_CONFLICT")
        sections.append(MedicationSection(
            drug_canonical_key=medication.drug_canonical_key,
            requested_value=medication.requested_value,
            status=status,
            axes=axes,
            findings=findings,
            not_assessed_axes=not_assessed,
            conflict_axes=conflicts,
            conflict_references=medication.conflict_references,
            evidence_references=tuple(sorted(
                {reference for finding in findings
                 for reference in finding.evidence_references})),
            rule_references=tuple(sorted({finding.rule_id
                                          for finding in findings})),
            answers=_answers(medication, axes, findings, status,
                             result.release_provenance, key),
            axis_count=medication.axis_count,
            conflicted_axis_count=medication.conflicted_axis_count))

    return StructuredReport(
        assessment_id=result.assessment_id,
        locale=key,
        template_version=template_version,
        mode_code=result.mode,
        mode_label=label(MODE_LABELS, result.mode, key, table_name="mode"),
        input_kind_code=result.input_kind,
        input_kind_label=label(INPUT_KIND_LABELS, result.input_kind, key,
                               table_name="input_kind"),
        input_hash=result.input_hash,
        output_hash=result.output_hash,
        coverage_result_hash=result.coverage_result_hash,
        canonical_result_hash=result.content_hash(),
        overall=_status(result.overall_attention, result.overall_coverage,
                        result.overall_coverage_reason_codes, key),
        medications=tuple(sections),
        profile_observations=result.profile_observations,
        uncertainty=_uncertainty(result, key),
        release_provenance=dict(result.release_provenance),
        pointer_audit=dict(result.pointer_audit),
        canonical_warning=canonical_clinical_warning(key),
        disclaimer=statement("disclaimer", key),
        adjacency_note=statement("attention_and_coverage", key),
        profile_note=statement("profile_note", key),
        section_titles=titles,
        question_labels=question_labels(key),
        engine_contract_version=result.engine_contract_version,
        computation_schema_version=result.computation_schema_version,
        case_id=result.case_id,
        warnings=result.warnings)
