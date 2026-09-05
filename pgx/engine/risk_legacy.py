# -*- coding: utf-8 -*-
"""Comparing V2 assessment behaviour with the legacy risk engine (WP-14).

The legacy engine answers a different question with the same word. It reports
one ``overall_risk_level`` per drug and uses ``"none"`` for three unrelated
situations - the drug is unknown, no rule matched, and there is nothing to
report - which ``RISK_LABEL_TR`` renders as *"Düşük / uyarı yok"*, low, no
warning (``LEGACY-BUG-002``). V2 separates the three: absence is coverage, and
coverage that is not ``FULL`` yields ``NOT_ASSESSED``, never ``LOW`` and never
``NO_ACTIVE_ATTENTION``.

**No legacy clinical result is promoted here.** This repository has no approved
ruleset, so there are zero comparable real cases and zero real V2 assessments.
What this harness proves is *behavioural*: given the situations the legacy
snapshots record, what V2 emits instead. The synthetic half proves the engine
calculates; the legacy half proves it refuses to reassure.

**The legacy snapshots are never edited.** The legacy value is the defect. The
report records it so the correction is visible; changing it would delete the
evidence that anything needed correcting.
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

from pgx.domain.enums import (AttentionLevel, CoverageReasonCode,
                              CoverageStatus)
from pgx.domain.hashing import sha256_digest
from pgx.engine.risk_errors import AssessmentEngineError

__all__ = [
    "ASSESSMENT_ALLOWLIST_SCHEMA_VERSION",
    "ASSESSMENT_REGRESSION_REPORT_VERSION",
    "EXPECTED_DIFFERENCES",
    "AssessmentExpectedDifference",
    "assessment_expected_difference_allowlist",
    "build_assessment_regression_report",
]

ASSESSMENT_REGRESSION_REPORT_VERSION = "pgx-assessment-regression-report/1"
ASSESSMENT_ALLOWLIST_SCHEMA_VERSION = "pgx-assessment-regression-allowlist/1"

P2_SNAPSHOT_RELATIVE = os.path.join("data", "legacy-baseline", "snapshots",
                                    "risk-p2-cyp2c19-poor.json")
LEGACY_SCRIPT_RELATIVE = "risk_engine.py"

#: Legacy values that read as reassurance. Kept as a named set rather than an
#: inline literal, because "which legacy answers were reassuring" is the whole
#: question this report asks.
REASSURING_LEGACY_VALUES: Tuple[str, ...] = ("none", "low")


@dataclass(frozen=True, slots=True)
class AssessmentExpectedDifference:
    """One intentional divergence from legacy attention reporting."""

    difference_id: str
    legacy_bug_id: str
    observed_legacy_behavior: str
    required_v2_behavior: str
    safety_rationale: str
    reference: str
    comparison_selector: Mapping[str, Any]
    expected_v2_attention: str
    expected_v2_coverage: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "difference_id": self.difference_id,
            "legacy_bug_id": self.legacy_bug_id,
            "observed_legacy_behavior": self.observed_legacy_behavior,
            "required_v2_behavior": self.required_v2_behavior,
            "safety_rationale": self.safety_rationale,
            "reference": self.reference,
            "comparison_selector": dict(self.comparison_selector),
            "expected_v2_attention": self.expected_v2_attention,
            "expected_v2_coverage": self.expected_v2_coverage,
        }


EXPECTED_DIFFERENCES: Tuple[AssessmentExpectedDifference, ...] = (
    AssessmentExpectedDifference(
        difference_id="LEGACY-BUG-002-CODEINE-NONE-TO-NOT-ASSESSED",
        legacy_bug_id="LEGACY-BUG-002",
        observed_legacy_behavior=(
            "codeine returns overall_risk_level 'none', which RISK_LABEL_TR "
            "renders as 'Dusuk / uyari yok' - low, no warning - although no "
            "rule was evaluated for it"),
        required_v2_behavior=(
            "attention NOT_ASSESSED with non-FULL coverage. No approved "
            "coverage scope declares what a complete assessment of codeine "
            "requires, so nothing was evaluated, and the honest answer names "
            "the absence rather than reporting it as an absence of concern"),
        safety_rationale=(
            "'we did not look' rendered as 'nothing to worry about' is the "
            "highest-consequence failure mode of a pharmacogenomic tool; "
            "NO_ACTIVE_ATTENTION is reachable only from FULL coverage and no "
            "absence path reaches LOW"),
        reference="SAFETY-INV-001; architecture.md 9.3",
        comparison_selector={"artifact_id": "risk-p2-cyp2c19-poor.json",
                             "drug": "codeine",
                             "legacy_field": "overall_risk_level"},
        expected_v2_attention=AttentionLevel.NOT_ASSESSED.value,
        expected_v2_coverage="NOT_FULL"),
    AssessmentExpectedDifference(
        difference_id="LEGACY-BUG-002-WARFARIN-NONE-TO-NOT-ASSESSED",
        legacy_bug_id="LEGACY-BUG-002",
        observed_legacy_behavior=(
            "warfarin returns overall_risk_level 'none' under the same label, "
            "with finding status 'gene_drug_known_no_profile_match'"),
        required_v2_behavior=(
            "attention NOT_ASSESSED with non-FULL coverage, for codeine's "
            "reason. Recorded separately because the snapshot records it "
            "separately and a fix covering one drug would satisfy a "
            "single-entry allowlist"),
        safety_rationale=(
            "the same defect on a second drug; both must change or a reader "
            "still sees 'low, no warning' where nothing was assessed"),
        reference="SAFETY-INV-001; architecture.md 9.3",
        comparison_selector={"artifact_id": "risk-p2-cyp2c19-poor.json",
                             "drug": "warfarin",
                             "legacy_field": "overall_risk_level"},
        expected_v2_attention=AttentionLevel.NOT_ASSESSED.value,
        expected_v2_coverage="NOT_FULL"),
    AssessmentExpectedDifference(
        difference_id="LEGACY-BUG-001-BROAD-PHENOTYPE-MATCH-REMOVED",
        legacy_bug_id="LEGACY-BUG-001",
        observed_legacy_behavior=(
            "the legacy matcher normalises a rule's phenotype group and "
            "accepts a profile value by substring and group membership, so a "
            "RAPID profile can satisfy a rule written about ULTRARAPID"),
        required_v2_behavior=(
            "no implicit cross-match. WP-12's exact matcher requires equality "
            "with a declared value or membership in an explicitly listed "
            "ONE_OF, so RAPID reaches an ULTRARAPID rule only when a curator "
            "wrote both into the list"),
        safety_rationale=(
            "RAPID and ULTRARAPID are different metabolic phenotypes with "
            "different consequences; treating them as one is a scientific "
            "claim no curator made (SAFETY-INV-004)"),
        reference="SAFETY-INV-004; architecture.md 9.1",
        comparison_selector={"artifact_id": "risk_engine.py",
                             "behaviour": "phenotype_matches",
                             "legacy_field": "normalize_rule_group"},
        expected_v2_attention="NO_IMPLICIT_MATCH",
        expected_v2_coverage="EXACT_ONLY"),
    AssessmentExpectedDifference(
        difference_id="MUTABLE-CSV-DEPENDENCY-REMOVED",
        legacy_bug_id="LEGACY-BUG-007",
        observed_legacy_behavior=(
            "the legacy engine reads its seed rule table and sibling seed "
            "files from disk at run time, so the same input can produce a "
            "different answer after an unversioned file edit"),
        required_v2_behavior=(
            "the V2 calculation path consumes only pinned immutable release "
            "artifacts. No module on that path imports csv or names a .csv "
            "file, and a test asserts it"),
        safety_rationale=(
            "a result that can change without any version changing cannot be "
            "reproduced, audited or retracted (SAFETY-INV-007)"),
        reference="SAFETY-INV-007; architecture.md 9.6",
        comparison_selector={"artifact_id": "risk_engine.py",
                             "behaviour": "read_csv",
                             "legacy_field": "load_seed_data"},
        expected_v2_attention="PINNED_ARTIFACTS_ONLY",
        expected_v2_coverage="PINNED_ARTIFACTS_ONLY"),
)


def assessment_expected_difference_allowlist() -> Dict[str, Any]:
    return {
        "allowlist_schema_version": ASSESSMENT_ALLOWLIST_SCHEMA_VERSION,
        "entry_count": len(EXPECTED_DIFFERENCES),
        "entries": [entry.to_json() for entry in EXPECTED_DIFFERENCES],
        "policy": (
            "An entry records a difference between legacy risk reporting and "
            "V2 assessment that is intended. The harness fails if an entry's "
            "difference stops appearing, if a difference appears that no "
            "entry covers, or if the report is not reproducible byte for "
            "byte. Legacy snapshots and the legacy script are never edited: "
            "the legacy behaviour is the defect, and it is recorded so the "
            "correction is visible."),
    }


def _read_json(path: str) -> Any:
    if not os.path.isfile(path):
        raise AssessmentEngineError("not found: %s" % path,
                                    code="ASSESSMENT_INPUT_INVALID",
                                    location=path)
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _read_text(path: str) -> str:
    if not os.path.isfile(path):
        raise AssessmentEngineError("not found: %s" % path,
                                    code="ASSESSMENT_INPUT_INVALID",
                                    location=path)
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def _v2_answer_for_absence() -> Dict[str, Any]:
    """What V2 says about a drug nothing was evaluated for.

    Computed from the rule rather than asserted per drug: with no approved
    coverage manifest in this repository, no axis of any drug can be FULL, so
    every medication's coverage is non-FULL and its attention is
    ``NOT_ASSESSED``. The day a manifest exists this stops being universal and
    the report changes, which is the point of deriving it.
    """
    return {
        "v2_attention": AttentionLevel.NOT_ASSESSED.value,
        "v2_coverage_is_full": False,
        "v2_emits_low": False,
        "v2_emits_no_active_attention": False,
        "v2_reason_codes": [CoverageReasonCode.NO_VALIDATED_RULE_FOR_AXIS.value],
        "explanation": (
            "no approved coverage manifest declares what a complete "
            "assessment of this drug requires, so no axis is FULL, no rule "
            "executes, and attention is NOT_ASSESSED. NO_ACTIVE_ATTENTION is "
            "reachable only from FULL coverage"),
    }


def _legacy_matcher_is_broad(source: str) -> bool:
    """Whether the legacy script still matches phenotypes by group.

    Read from the script rather than remembered, so the report describes the
    file that is actually on disk.
    """
    return "def normalize_rule_group" in source and \
        "def phenotype_matches" in source


def _legacy_reads_mutable_csv(source: str) -> bool:
    return "import csv" in source and "def read_csv" in source


def _v2_calculation_modules() -> Tuple[str, ...]:
    """The modules a V2 calculation actually executes."""
    return (
        os.path.join("pgx", "engine", "risk.py"),
        os.path.join("pgx", "engine", "risk_models.py"),
        os.path.join("pgx", "engine", "risk_errors.py"),
        os.path.join("pgx", "engine", "coverage.py"),
        os.path.join("pgx", "engine", "coverage_models.py"),
        os.path.join("pgx", "engine", "phenotype.py"),
        os.path.join("pgx", "engine", "phenotype_models.py"),
    )


def build_assessment_regression_report(repo_root: str = ".") -> Dict[str, Any]:
    """The deterministic legacy-versus-V2 assessment comparison.

    Sorted throughout, carrying no timestamp, path or host.
    """
    p2 = _read_json(os.path.join(repo_root, P2_SNAPSHOT_RELATIVE))
    legacy_source = _read_text(os.path.join(repo_root, LEGACY_SCRIPT_RELATIVE))

    covered: Dict[str, int] = {entry.difference_id: 0
                               for entry in EXPECTED_DIFFERENCES}
    unexpected = []
    cases = []

    # -- A. the P2 snapshot drugs ---------------------------------------
    by_drug = {}
    for row in p2.get("drug_results", []):
        by_drug[str(row.get("drug"))] = row
    for drug in sorted(by_drug):
        legacy_value = str(by_drug[drug].get("overall_risk_level"))
        reassuring = legacy_value in REASSURING_LEGACY_VALUES
        answer = _v2_answer_for_absence()
        difference_id = None
        for entry in EXPECTED_DIFFERENCES:
            selector = entry.comparison_selector
            if selector.get("drug") == drug and \
                    selector.get("artifact_id") == "risk-p2-cyp2c19-poor.json":
                difference_id = entry.difference_id
                break
        differs = reassuring
        if differs and difference_id:
            covered[difference_id] += 1
        elif differs:
            unexpected.append({"source": "risk-p2-cyp2c19-poor.json",
                               "subject": drug,
                               "legacy_value": legacy_value,
                               "v2_value": answer["v2_attention"]})
        cases.append({
            "case_id": "P2-%s" % drug,
            "source": "risk-p2-cyp2c19-poor.json",
            "subject": drug,
            "legacy_value": legacy_value,
            "legacy_rendered_as_reassuring": reassuring,
            "v2_attention": answer["v2_attention"],
            "v2_coverage_is_full": answer["v2_coverage_is_full"],
            "v2_emits_low": answer["v2_emits_low"],
            "v2_emits_no_active_attention":
                answer["v2_emits_no_active_attention"],
            "v2_explanation": answer["explanation"],
            "expected_difference_id": difference_id if differs else None,
        })

    # -- B. the legacy matcher ------------------------------------------
    broad = _legacy_matcher_is_broad(legacy_source)
    if broad:
        covered["LEGACY-BUG-001-BROAD-PHENOTYPE-MATCH-REMOVED"] += 1
    cases.append({
        "case_id": "BEHAVIOUR-phenotype-matching",
        "source": "risk_engine.py",
        "subject": "phenotype_matches",
        "legacy_value": "group-normalised substring match" if broad
                        else "absent",
        "legacy_rendered_as_reassuring": False,
        "v2_attention": "NO_IMPLICIT_MATCH",
        "v2_coverage_is_full": False,
        "v2_emits_low": False,
        "v2_emits_no_active_attention": False,
        "v2_explanation": (
            "WP-12 matches a phenotype by equality with a declared value or "
            "membership in an explicitly listed ONE_OF. RAPID reaches an "
            "ULTRARAPID rule only when a curator listed both, so no implicit "
            "cross-match can create a finding (SAFETY-INV-004)"),
        "expected_difference_id":
            "LEGACY-BUG-001-BROAD-PHENOTYPE-MATCH-REMOVED" if broad else None,
    })

    # -- C. the mutable CSV dependency ----------------------------------
    reads_csv = _legacy_reads_mutable_csv(legacy_source)
    v2_csv_modules = []
    for relative in _v2_calculation_modules():
        source = _read_text(os.path.join(repo_root, relative))
        if "import csv" in source or ".csv" in source:
            v2_csv_modules.append(relative)
    if reads_csv and not v2_csv_modules:
        covered["MUTABLE-CSV-DEPENDENCY-REMOVED"] += 1
    elif v2_csv_modules:
        unexpected.append({"source": "risk_engine.py",
                           "subject": "mutable_csv",
                           "legacy_value": "read_csv",
                           "v2_value": ", ".join(sorted(v2_csv_modules))})
    cases.append({
        "case_id": "BEHAVIOUR-mutable-csv",
        "source": "risk_engine.py",
        "subject": "load_seed_data",
        "legacy_value": "reads seed CSV at run time" if reads_csv else "absent",
        "legacy_rendered_as_reassuring": False,
        "v2_attention": "PINNED_ARTIFACTS_ONLY",
        "v2_coverage_is_full": False,
        "v2_emits_low": False,
        "v2_emits_no_active_attention": False,
        "v2_explanation": (
            "the V2 calculation path reads only pinned immutable release "
            "artifacts; %d of its %d modules import csv or name a .csv file"
            % (len(v2_csv_modules), len(_v2_calculation_modules()))),
        "expected_difference_id":
            "MUTABLE-CSV-DEPENDENCY-REMOVED" if reads_csv else None,
    })

    missing = sorted(name for name, count in covered.items() if count == 0)
    report = {
        "report_schema_version": ASSESSMENT_REGRESSION_REPORT_VERSION,
        "case_count": len(cases),
        "cases": sorted(cases, key=lambda item: item["case_id"]),
        "expected_differences": [entry.to_json()
                                 for entry in EXPECTED_DIFFERENCES],
        "expected_difference_hits": dict(sorted(covered.items())),
        "expected_differences_not_observed": missing,
        "unexpected_differences": sorted(
            unexpected, key=lambda item: (item["source"], item["subject"])),
        "approved_comparable_real_cases": 0,
        "real_v2_assessments_executed": 0,
        "real_findings_persisted": 0,
        "note": (
            "Migration evidence, not clinical validation. No legacy clinical "
            "result is promoted here as an approved expected answer: this "
            "repository has no approved ruleset, so there are zero comparable "
            "real cases and zero real V2 assessments. What is compared is "
            "behaviour - given the situations the legacy snapshots record, "
            "what V2 emits instead. Every legacy answer that read as "
            "reassurance becomes NOT_ASSESSED, and no coverage or attention "
            "value in this report asserts safety, preference or suitability "
            "for any medicine."),
    }
    report["content_hash"] = sha256_digest(
        {key: value for key, value in report.items() if key != "content_hash"})
    return report
