# -*- coding: utf-8 -*-
"""Comparing WP-15 reporting with the legacy report path (WP-15).

Two legacy programs produced documents: ``render_markdown_report`` in
``risk_engine.py``, and ``gemini_report_generator.py``, which builds a payload,
sends it to a model, and falls back to a deterministic renderer when it
cannot. This harness reads both **as source**, records what they do, and states
what WP-15 does instead.

**No model is called, and none can be.** This module does not import
``gemini_report_generator``, does not read an API key, does not build a prompt
and opens no socket. What it reads about the Gemini path is that path's source
text plus the recorded offline observation in
``data/legacy-baseline/snapshots/recorded-report-observation.json``, which was
itself produced with the key stripped from the environment and ``used_api``
false.

**Only layout was ported.** A section per medication, a table of genes and
phenotypes, the warning in a block quote near the top: those are presentation
ideas and WP-15 keeps them. Nothing else crossed. In particular the legacy
label table is not ported, because its central entry is the defect: ``"none"``
- meaning *the drug is unknown*, or *no rule matched*, or *there was nothing
to report* - rendered as **"Düşük / uyarı yok"**, low, no warning
(``LEGACY-BUG-002``). WP-15 renders those three situations as coverage
statuses with reason codes and an attention level of ``NOT_ASSESSED``, and the
controlled sentence beside it says what that does and does not mean.

**Status loss is documented, not repaired.** The legacy documents carry no
coverage concept at all, so a legacy report cannot be upgraded into a WP-15
report: the information a WP-15 report is required to show was never computed.
That is recorded as a loss, and no legacy scientific value is described here
as validated or approved. The legacy values are the evidence that something
needed correcting; editing them would delete the evidence.
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Tuple

from pgx.domain.hashing import sha256_digest
from pgx.reporting.errors import ReportError

__all__ = [
    "LEGACY_REPORT_ALLOWLIST_SCHEMA_VERSION",
    "LEGACY_REPORT_REGRESSION_VERSION",
    "PORTED_LAYOUT_CONCEPTS",
    "REPORT_EXPECTED_DIFFERENCES",
    "LegacyReportDifference",
    "build_report_regression_report",
    "legacy_report_difference_allowlist",
]

LEGACY_REPORT_REGRESSION_VERSION = "pgx-report-regression-report/1"
LEGACY_REPORT_ALLOWLIST_SCHEMA_VERSION = "pgx-report-regression-allowlist/1"

LEGACY_RENDERER_RELATIVE = "risk_engine.py"
LEGACY_GENERATOR_RELATIVE = "gemini_report_generator.py"
RECORDED_OBSERVATION_RELATIVE = os.path.join(
    "data", "legacy-baseline", "snapshots", "recorded-report-observation.json")

#: Layout ideas WP-15 keeps, and nothing more. Named so the claim "we ported
#: only safe layout concepts" is a list somebody can check rather than a
#: reassurance in a document.
PORTED_LAYOUT_CONCEPTS: Tuple[Tuple[str, str], ...] = (
    ("warning_near_the_top",
     "the canonical warning is rendered as a block quote before anything "
     "else, so a reader meets it before a finding"),
    ("section_per_medication",
     "one section per requested medication, in canonical order"),
    ("gene_phenotype_table",
     "a table of genes and observed phenotypes"),
    ("finding_detail_rows",
     "a labelled row per attribute of a finding rather than a paragraph"),
)

#: Things the legacy documents did that WP-15 deliberately does not do.
NOT_PORTED: Tuple[Tuple[str, str], ...] = (
    ("risk_label_table",
     "the legacy label table maps the absence of a rule to a reassuring "
     "phrase; the compaction is the defect (LEGACY-BUG-002)"),
    ("numeric_score",
     "the legacy candidate path prints a 0-100 suitability score "
     "(LEGACY-BUG-009); WP-15 prints no score, no ranking and no preference"),
    ("free_prose_fields",
     "plain_language, guideline_summaries, effect_direction and risk_meaning "
     "are free scientific text no governed rule carries; WP-15 renders the "
     "governed rationale reference and evidence references instead"),
    ("model_generated_narration",
     "the Gemini path sends a compacted payload to a model and renders what "
     "comes back (LEGACY-BUG-003, LEGACY-BUG-012); WP-15 calls no model"),
)


@dataclass(frozen=True, slots=True)
class LegacyReportDifference:
    """One intentional divergence from the legacy report path."""

    difference_id: str
    legacy_bug_id: str
    observed_legacy_behavior: str
    required_v2_behavior: str
    safety_rationale: str
    reference: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "difference_id": self.difference_id,
            "legacy_bug_id": self.legacy_bug_id,
            "observed_legacy_behavior": self.observed_legacy_behavior,
            "required_v2_behavior": self.required_v2_behavior,
            "safety_rationale": self.safety_rationale,
            "reference": self.reference,
        }


REPORT_EXPECTED_DIFFERENCES: Tuple[LegacyReportDifference, ...] = (
    LegacyReportDifference(
        difference_id="REPORT-ABSENCE-NOT-RENDERED-AS-LOW",
        legacy_bug_id="LEGACY-BUG-002",
        observed_legacy_behavior=(
            "risk_engine.RISK_LABEL_TR maps the level 'none' to a phrase "
            "meaning low with no warning, and render_markdown_report prints "
            "it for a drug that is unknown, for a drug no rule matched, and "
            "for a drug with nothing to report"),
        required_v2_behavior=(
            "WP-15 renders those three situations as three different coverage "
            "statuses, each with its own machine-readable reason code, beside "
            "an attention level of NOT_ASSESSED and a controlled sentence "
            "stating that the item was not assessed and that this carries no "
            "level and no assurance"),
        safety_rationale=(
            "SAFETY-INV-001: missing data is not a low result. A reader who "
            "sees a reassuring phrase where nothing was evaluated has been "
            "told something the system never computed"),
        reference="docs/risk-management/safety-contract.md"),
    LegacyReportDifference(
        difference_id="REPORT-NO-COVERAGE-CONCEPT-IN-LEGACY",
        legacy_bug_id="LEGACY-BUG-002",
        observed_legacy_behavior=(
            "the legacy documents contain no coverage status, no coverage "
            "reason code and no statement of what was outside scope; a reader "
            "cannot tell a complete evaluation from a partial one"),
        required_v2_behavior=(
            "every WP-15 report displays coverage beside attention at every "
            "level, with reason codes, an explicit not-assessed block per "
            "medication and an uncertainty section"),
        safety_rationale=(
            "coverage and attention are separate first-class outputs; a "
            "document showing one without the other lets absence be read as "
            "a result"),
        reference="architecture.md sections 9.2 and 9.3"),
    LegacyReportDifference(
        difference_id="REPORT-NO-MODEL-IN-THE-CANONICAL-PATH",
        legacy_bug_id="LEGACY-BUG-003",
        observed_legacy_behavior=(
            "gemini_report_generator compacts the result into a prompt "
            "payload, sends it to an external model and renders the returned "
            "text, falling back to a deterministic renderer when it cannot"),
        required_v2_behavior=(
            "WP-15 implements no provider, imports no SDK, reads no API key "
            "and opens no socket; the offline document is the report rather "
            "than a fallback"),
        safety_rationale=(
            "a model restates a not-assessed medication as fluent "
            "reassurance, invents a mechanism where a rule carries no effect "
            "code, and drops a partial-coverage caveat that reads badly - and "
            "none of that is visible in a hash"),
        reference="docs/migration/legacy-inventory.md C.5"),
    LegacyReportDifference(
        difference_id="REPORT-NO-FREE-SCIENTIFIC-PROSE",
        legacy_bug_id="LEGACY-BUG-012",
        observed_legacy_behavior=(
            "the legacy renderer prints plain_language, guideline summaries, "
            "effect_direction and risk_meaning straight from the seed rows; "
            "source summaries in that data carry dosing language"),
        required_v2_behavior=(
            "WP-15 renders no free scientific text. A finding shows its "
            "governed rationale reference and its evidence references; where "
            "the ruleset carries no effect or explanation code, a controlled "
            "sentence says so"),
        safety_rationale=(
            "SAFETY-INV-010: text nobody governs is text nobody reviewed, and "
            "a dosing sentence copied out of a source summary is a dose "
            "recommendation whatever the surrounding layout says"),
        reference="docs/risk-management/safety-contract.md"),
    LegacyReportDifference(
        difference_id="REPORT-NO-SCORE-NO-RANKING",
        legacy_bug_id="LEGACY-BUG-009",
        observed_legacy_behavior=(
            "the legacy candidate path computes and prints a 0-100 "
            "suitability score beside drug names"),
        required_v2_behavior=(
            "no WP-15 report carries a score, a rank, a preference, a "
            "comparison between medications or a suitability label; the "
            "report types have nowhere to put one"),
        safety_rationale=(
            "SAFETY-INV-005: a number beside a drug name is read as a "
            "recommendation however it is captioned"),
        reference="docs/architecture/intended-purpose.md"),
)


def legacy_report_difference_allowlist() -> Dict[str, Any]:
    """The published allowlist of intentional report differences."""
    return {
        "allowlist_schema_version": LEGACY_REPORT_ALLOWLIST_SCHEMA_VERSION,
        "difference_count": len(REPORT_EXPECTED_DIFFERENCES),
        "differences": [entry.to_json()
                        for entry in REPORT_EXPECTED_DIFFERENCES],
        "note": ("Each entry is a difference this work package intends. A "
                 "difference outside this list is a regression, not a "
                 "decision."),
    }


def _read_text(path: str) -> str:
    if not os.path.isfile(path):
        raise ReportError("legacy artifact %s is not present" % path,
                          code="REPORT_INPUT_INVALID", location="$." + path)
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def _read_json(path: str) -> Any:
    return json.loads(_read_text(path))


def _legacy_compacts_absence(source: str) -> bool:
    """Whether the legacy label table still renders absence reassuringly.

    Looks for the ``"none"`` entry of ``RISK_LABEL_TR`` and asks whether its
    value carries a reassuring word. The legacy file is never edited, so this
    is expected to be true; it is checked rather than asserted so the report
    describes the file that is actually there.
    """
    marker = "RISK_LABEL_TR"
    if marker not in source:
        return False
    start = source.index(marker)
    table = source[start:start + 400]
    lowered = table.lower()
    return '"none"' in lowered and ("dusuk" in lowered or "düşük" in lowered
                                    or "uyarı yok" in lowered
                                    or "uyari yok" in lowered)


def _legacy_renders_free_prose(source: str) -> Tuple[str, ...]:
    return tuple(sorted(name for name in
                        ("plain_language", "guideline_summaries",
                         "effect_direction", "risk_meaning")
                        if name in source))


def _legacy_has_no_coverage_concept(source: str) -> bool:
    lowered = source.lower()
    return not any(token in lowered
                   for token in ("coverage_status", "coverage_reason",
                                 "not_assessed"))


def _generator_calls_a_model(source: str) -> Tuple[str, ...]:
    return tuple(sorted(name for name in
                        ("call_gemini_api", "build_prompt", "GEMINI_API_KEY",
                         "render_fallback_report")
                        if name in source))


def _v2_reporting_modules() -> Tuple[str, ...]:
    return (
        os.path.join("pgx", "reporting", "models.py"),
        os.path.join("pgx", "reporting", "structured.py"),
        os.path.join("pgx", "reporting", "render.py"),
        os.path.join("pgx", "reporting", "validator.py"),
        os.path.join("pgx", "reporting", "gate.py"),
        os.path.join("pgx", "reporting", "artifacts.py"),
        os.path.join("pgx", "reporting", "llm.py"),
        os.path.join("pgx", "application", "report_service.py"),
    )


def build_report_regression_report(repo_root: str = ".") -> Dict[str, Any]:
    """The deterministic legacy-versus-WP-15 report comparison.

    Sorted throughout, carrying no timestamp, no path outside the repository
    and no host. Runs offline: it reads three files and calls nothing.
    """
    renderer_source = _read_text(os.path.join(repo_root,
                                              LEGACY_RENDERER_RELATIVE))
    generator_source = _read_text(os.path.join(repo_root,
                                               LEGACY_GENERATOR_RELATIVE))
    observation = _read_json(os.path.join(repo_root,
                                          RECORDED_OBSERVATION_RELATIVE))

    covered: Dict[str, int] = {entry.difference_id: 0
                               for entry in REPORT_EXPECTED_DIFFERENCES}
    cases: List[Dict[str, Any]] = []

    compacts = _legacy_compacts_absence(renderer_source)
    if compacts:
        covered["REPORT-ABSENCE-NOT-RENDERED-AS-LOW"] += 1
    cases.append({
        "case_id": "RENDERER-absence-label",
        "source": LEGACY_RENDERER_RELATIVE,
        "subject": "RISK_LABEL_TR['none']",
        "legacy_behaviour_present": compacts,
        "legacy_rendered_as_reassuring": compacts,
        "v2_behaviour": ("NOT_ASSESSED with a coverage status, a reason code "
                         "and the controlled not-assessed sentence"),
        "expected_difference_id": ("REPORT-ABSENCE-NOT-RENDERED-AS-LOW"
                                   if compacts else None),
    })

    no_coverage = _legacy_has_no_coverage_concept(renderer_source)
    if no_coverage:
        covered["REPORT-NO-COVERAGE-CONCEPT-IN-LEGACY"] += 1
    cases.append({
        "case_id": "RENDERER-coverage-absent",
        "source": LEGACY_RENDERER_RELATIVE,
        "subject": "coverage",
        "legacy_behaviour_present": no_coverage,
        "legacy_rendered_as_reassuring": False,
        "v2_behaviour": ("coverage is displayed beside attention at every "
                         "level, with reason codes and an explicit "
                         "not-assessed block"),
        "status_loss": ("a legacy document cannot be upgraded into a WP-15 "
                        "report: coverage, reason codes, rule identity, rule "
                        "content hash, curation revision and evidence "
                        "references were never computed or recorded by the "
                        "legacy path"),
        "expected_difference_id": ("REPORT-NO-COVERAGE-CONCEPT-IN-LEGACY"
                                   if no_coverage else None),
    })

    prose = _legacy_renders_free_prose(renderer_source)
    if prose:
        covered["REPORT-NO-FREE-SCIENTIFIC-PROSE"] += 1
    cases.append({
        "case_id": "RENDERER-free-prose",
        "source": LEGACY_RENDERER_RELATIVE,
        "subject": "free scientific text fields",
        "legacy_fields": list(prose),
        "legacy_behaviour_present": bool(prose),
        "legacy_rendered_as_reassuring": False,
        "v2_behaviour": ("governed rationale reference and evidence "
                         "references only; a controlled sentence where the "
                         "ruleset carries no effect or explanation code"),
        "expected_difference_id": ("REPORT-NO-FREE-SCIENTIFIC-PROSE"
                                   if prose else None),
    })

    legacy_prints_a_number = "risk_score" in renderer_source
    if legacy_prints_a_number:
        covered["REPORT-NO-SCORE-NO-RANKING"] += 1
    cases.append({
        "case_id": "RENDERER-numeric-score",
        "source": LEGACY_RENDERER_RELATIVE,
        "subject": "risk_score",
        "legacy_behaviour_present": legacy_prints_a_number,
        "legacy_rendered_as_reassuring": False,
        "v2_behaviour": "no numeric value, no ordering, no preference and no "
                        "comparison between medications",
        "expected_difference_id": ("REPORT-NO-SCORE-NO-RANKING"
                                   if legacy_prints_a_number else None),
    })

    model_symbols = _generator_calls_a_model(generator_source)
    if model_symbols:
        covered["REPORT-NO-MODEL-IN-THE-CANONICAL-PATH"] += 1
    v2_modules_naming_the_generator = []
    for relative in _v2_reporting_modules():
        path = os.path.join(repo_root, relative)
        if not os.path.isfile(path):
            continue
        text = _read_text(path)
        if "import gemini_report_generator" in text or \
                "from gemini_report_generator" in text:
            v2_modules_naming_the_generator.append(relative)
    cases.append({
        "case_id": "GENERATOR-model-call",
        "source": LEGACY_GENERATOR_RELATIVE,
        "subject": "external model call",
        "legacy_symbols": list(model_symbols),
        "legacy_behaviour_present": bool(model_symbols),
        "legacy_rendered_as_reassuring": False,
        "v2_behaviour": ("no provider is implemented; %d of %d WP-15 "
                         "reporting modules import the legacy generator"
                         % (len(v2_modules_naming_the_generator),
                            len(_v2_reporting_modules()))),
        "v2_modules_importing_the_legacy_generator":
            sorted(v2_modules_naming_the_generator),
        "expected_difference_id": ("REPORT-NO-MODEL-IN-THE-CANONICAL-PATH"
                                   if model_symbols else None),
    })

    recorded = observation.get("offline_fallback_observation", {}) or {}
    cases.append({
        "case_id": "GENERATOR-recorded-observation",
        "source": RECORDED_OBSERVATION_RELATIVE,
        "subject": "recorded legacy report artifacts",
        "legacy_behaviour_present": True,
        "legacy_rendered_as_reassuring": False,
        "api_call_made": bool(observation.get("no_api_call_made")) is False,
        "network_used": bool(recorded.get("network_used")),
        "used_api": bool((recorded.get("status_non_volatile_fields") or {})
                         .get("used_api")),
        "v2_behaviour": ("WP-15 reads this observation as evidence and calls "
                         "nothing; the recorded artifacts were produced with "
                         "the key stripped from the environment"),
        "expected_difference_id": None,
    })

    unexpected = [case for case in cases
                  if case.get("legacy_rendered_as_reassuring")
                  and not case.get("expected_difference_id")]
    report = {
        "report_version": LEGACY_REPORT_REGRESSION_VERSION,
        "allowlist": legacy_report_difference_allowlist(),
        "ported_layout_concepts": [
            {"concept": name, "description": text}
            for name, text in PORTED_LAYOUT_CONCEPTS],
        "not_ported": [{"concept": name, "reason": text}
                       for name, text in NOT_PORTED],
        "case_count": len(cases),
        "cases": sorted(cases, key=lambda item: item["case_id"]),
        "difference_coverage": {key: covered[key] for key in sorted(covered)},
        "uncovered_expected_differences":
            sorted(key for key, count in covered.items() if count == 0),
        "unexpected_difference_count": len(unexpected),
        "unexpected_differences": unexpected,
        "live_model_calls": 0,
        "network_used": False,
        "note": ("A deterministic, offline comparison of the legacy report "
                 "path with WP-15. No model was called and no key was read. "
                 "The legacy values recorded here are the evidence that "
                 "something needed correcting; none of them is described as "
                 "validated, approved or clinically meaningful."),
    }
    report["content_hash"] = sha256_digest(report)
    return report
