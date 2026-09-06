# -*- coding: utf-8 -*-
"""Comparing V2 coverage with the legacy engine's risk output (WP-13).

The legacy engine has no coverage concept. It reports a single
``overall_risk_level`` per drug and uses ``"none"`` for three different
situations: the drug is unknown, no rule matched, and there is nothing to
report. ``RISK_LABEL_TR`` then renders ``"none"`` as *"Düşük / uyarı yok"* -
"low / no warning" (`LEGACY-BUG-002`). That is the false-reassurance failure
in its original form: three kinds of "we did not look" presented as one kind
of "we looked and it is fine".

Separately, the legacy candidate path attaches a 0-100 score to prasugrel and
ticagrelor while recording their own data status as
``insufficient_pgx_rule_data`` (`LEGACY-BUG-009`) - a number that reads as
suitability, on candidates with no usable rule.

This harness states, for each of those drugs, what V2 coverage says instead.
It reads the WP-01 legacy snapshots and the *real* pinned canonical catalogue,
which is what makes the result a diagnostic rather than an invention: codeine
and warfarin really are in that catalogue and really have no approved coverage,
and prasugrel and ticagrelor really are absent from it.

**Nothing here is a clinical result.** No real coverage manifest exists, so
every V2 answer below is some flavour of "not assessed, and here is the
machine-readable reason". That is the correction.
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from pgx.domain.enums import CoverageReasonCode, CoverageStatus
from pgx.domain.hashing import sha256_digest
from pgx.engine.coverage_errors import CoverageEngineError

__all__ = [
    "COVERAGE_ALLOWLIST_SCHEMA_VERSION",
    "COVERAGE_REGRESSION_REPORT_VERSION",
    "EXPECTED_DIFFERENCES",
    "build_coverage_regression_report",
    "coverage_expected_difference_allowlist",
    "load_canonical_drug_catalogue",
]

COVERAGE_REGRESSION_REPORT_VERSION = "pgx-coverage-regression-report/1"
COVERAGE_ALLOWLIST_SCHEMA_VERSION = "pgx-coverage-regression-allowlist/1"

P2_SNAPSHOT_RELATIVE = os.path.join("data", "legacy-baseline", "snapshots",
                                    "risk-p2-cyp2c19-poor.json")
CANDIDATE_SNAPSHOT_RELATIVE = os.path.join(
    "data", "legacy-baseline", "snapshots", "alternative-beta-clopidogrel.json")
CANONICAL_ROOT_RELATIVE = os.path.join("data", "canonical")

#: The dataset the WP-14 legacy coverage regression is about.
#:
#: Pinned by name rather than discovered. The loader below used to take the
#: last directory in ``data/canonical`` by sort order and its docstring called
#: the result "the pinned canonical build", which was true only while exactly
#: one build existed. When Wave 3B added a second, the regression silently
#: retargeted itself at the newer dataset and the stored report stopped
#: matching - the failure was loud, but a differently-named dataset would have
#: made it silent, and a regression that quietly changes what it regresses
#: against is worse than one that fails.
LEGACY_REGRESSION_DATASET_ID = "PGX-DATA-20260830-900"


@dataclass(frozen=True, slots=True)
class CoverageExpectedDifference:
    """One intentional divergence from legacy risk-reporting behaviour."""

    difference_id: str
    legacy_bug_id: str
    observed_legacy_behavior: str
    required_v2_behavior: str
    safety_rationale: str
    reference: str
    comparison_selector: Mapping[str, Any]
    expected_coverage_status: str
    expected_reason_code: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "difference_id": self.difference_id,
            "legacy_bug_id": self.legacy_bug_id,
            "observed_legacy_behavior": self.observed_legacy_behavior,
            "required_v2_behavior": self.required_v2_behavior,
            "safety_rationale": self.safety_rationale,
            "reference": self.reference,
            "comparison_selector": dict(self.comparison_selector),
            "expected_coverage_status": self.expected_coverage_status,
            "expected_reason_code": self.expected_reason_code,
        }


EXPECTED_DIFFERENCES: Tuple[CoverageExpectedDifference, ...] = (
    CoverageExpectedDifference(
        difference_id="LEGACY-BUG-002-CODEINE-NONE-TO-INSUFFICIENT",
        legacy_bug_id="LEGACY-BUG-002",
        observed_legacy_behavior=(
            "codeine returns overall_risk_level 'none', which RISK_LABEL_TR "
            "renders as 'Dusuk / uyari yok' - low, no warning - although "
            "nothing was actually evaluated"),
        required_v2_behavior=(
            "coverage INSUFFICIENT with NO_VALIDATED_RULE_FOR_AXIS. The drug "
            "is in the pinned canonical dataset, and no approved coverage "
            "scope exists for it, so the honest answer is that it was not "
            "assessed and why"),
        safety_rationale=(
            "'we did not look' rendered as 'nothing to worry about' is the "
            "highest-consequence failure mode of a pharmacogenomic tool; "
            "coverage exists as a separate first-class output precisely so "
            "that absence cannot be reported as reassurance"),
        reference="SAFETY-INV-001; architecture.md 9.2, 9.3",
        comparison_selector={
            "artifact_id": "risk-p2-cyp2c19-poor.json",
            "drug": "codeine", "legacy_field": "overall_risk_level"},
        expected_coverage_status="INSUFFICIENT",
        expected_reason_code="NO_VALIDATED_RULE_FOR_AXIS"),
    CoverageExpectedDifference(
        difference_id="LEGACY-BUG-002-WARFARIN-NONE-TO-INSUFFICIENT",
        legacy_bug_id="LEGACY-BUG-002",
        observed_legacy_behavior=(
            "warfarin returns overall_risk_level 'none' under the same label, "
            "with finding status 'gene_drug_known_no_profile_match'"),
        required_v2_behavior=(
            "coverage INSUFFICIENT with NO_VALIDATED_RULE_FOR_AXIS, for the "
            "same reason as codeine. It is a separate entry because the legacy "
            "snapshot records it separately, and a fix covering only one drug "
            "would satisfy a single-entry allowlist"),
        safety_rationale=(
            "the same defect on a second drug; both must change or a reader "
            "still sees 'low, no warning' where nothing was assessed"),
        reference="SAFETY-INV-001; architecture.md 9.2, 9.3",
        comparison_selector={
            "artifact_id": "risk-p2-cyp2c19-poor.json",
            "drug": "warfarin", "legacy_field": "overall_risk_level"},
        expected_coverage_status="INSUFFICIENT",
        expected_reason_code="NO_VALIDATED_RULE_FOR_AXIS"),
    CoverageExpectedDifference(
        difference_id="LEGACY-BUG-009-PRASUGREL-SCORE-REMOVED",
        legacy_bug_id="LEGACY-BUG-009",
        observed_legacy_behavior=(
            "prasugrel receives score 59 under 'MVP alternatif uygunluk on "
            "skoru' while its own data status is 'insufficient_pgx_rule_data' "
            "- a suitability-shaped number on a candidate with no usable rule"),
        required_v2_behavior=(
            "no score of any kind. Prasugrel is absent from the pinned "
            "canonical dataset, so coverage is UNSUPPORTED_DRUG with "
            "DRUG_NOT_IN_CANONICAL_DATASET, and there is no field in a "
            "coverage result a score could be written into"),
        safety_rationale=(
            "a number between 0 and 100 beside a drug name reads as a ranking "
            "however it is labelled, and ranking candidates by anything is a "
            "preference claim this system does not make (SAFETY-INV-005)"),
        reference="SAFETY-INV-005; architecture.md 4.4",
        comparison_selector={
            "artifact_id": "alternative-beta-clopidogrel.json",
            "drug": "prasugrel", "legacy_field": "legacy_score_unprotected"},
        expected_coverage_status="UNSUPPORTED_DRUG",
        expected_reason_code="DRUG_NOT_IN_CANONICAL_DATASET"),
    CoverageExpectedDifference(
        difference_id="LEGACY-BUG-009-TICAGRELOR-SCORE-REMOVED",
        legacy_bug_id="LEGACY-BUG-009",
        observed_legacy_behavior=(
            "ticagrelor receives the identical score 59 under the identical "
            "data status, which is itself the tell: the number distinguishes "
            "nothing and still reads as an assessment"),
        required_v2_behavior=(
            "no score. Ticagrelor is absent from the pinned canonical dataset, "
            "so coverage is UNSUPPORTED_DRUG with "
            "DRUG_NOT_IN_CANONICAL_DATASET"),
        safety_rationale=(
            "same defect, second candidate; each is addressed by identity so "
            "a reordered list cannot move one expectation onto the other"),
        reference="SAFETY-INV-005; architecture.md 4.4",
        comparison_selector={
            "artifact_id": "alternative-beta-clopidogrel.json",
            "drug": "ticagrelor", "legacy_field": "legacy_score_unprotected"},
        expected_coverage_status="UNSUPPORTED_DRUG",
        expected_reason_code="DRUG_NOT_IN_CANONICAL_DATASET"),
)


def coverage_expected_difference_allowlist() -> Dict[str, Any]:
    return {
        "allowlist_schema_version": COVERAGE_ALLOWLIST_SCHEMA_VERSION,
        "entry_count": len(EXPECTED_DIFFERENCES),
        "entries": [entry.to_json() for entry in EXPECTED_DIFFERENCES],
        "policy": (
            "An entry records a difference between legacy risk reporting and "
            "V2 coverage that is intended. The harness fails if an entry's "
            "difference stops appearing, if a difference appears that no entry "
            "covers, or if the report is not reproducible byte for byte. "
            "Legacy snapshots are never edited to make V2 agree with them: "
            "the legacy value is the defect, and it is recorded so the change "
            "is visible."),
    }


def _read_json(path: str) -> Any:
    if not os.path.isfile(path):
        raise CoverageEngineError("not found: %s" % path,
                                  code="COVERAGE_LEGACY_ARTIFACT_MISSING",
                                  location=path)
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_canonical_drug_catalogue(
        repo_root: str = ".",
        dataset_public_id: str = LEGACY_REGRESSION_DATASET_ID
) -> Tuple[Tuple[str, ...], Dict[str, Any]]:
    """The drugs in one named canonical build, with the build's identity.

    Read-only. The catalogue is what makes recognition checkable: a drug in it
    is a chemical the dataset has, which is the precondition for asking the
    coverage question and never an answer to it.

    The build is named, never discovered. A caller that wants a different
    dataset says so; a caller that says nothing gets the pinned legacy one and
    an error if it is absent, rather than whichever directory happens to sort
    last.
    """
    root = os.path.join(repo_root, CANONICAL_ROOT_RELATIVE)
    if not os.path.isdir(root):
        raise CoverageEngineError(
            "no canonical dataset at %s" % root,
            code="COVERAGE_LEGACY_ARTIFACT_MISSING", location=root)
    directory = os.path.join(root, dataset_public_id)
    if not os.path.isdir(directory):
        available = sorted(name for name in os.listdir(root)
                           if os.path.isdir(os.path.join(root, name)))
        raise CoverageEngineError(
            "no canonical build %s under %s (present: %s)"
            % (dataset_public_id, root, ", ".join(available) or "none"),
            code="COVERAGE_LEGACY_ARTIFACT_MISSING", location=directory)
    manifest = _read_json(os.path.join(directory, "manifest.json"))
    drugs = set()
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".ndjson"):
            continue
        with io.open(os.path.join(directory, name), encoding="utf-8") as handle:
            for line in handle:
                if "canonical_key" not in line:
                    continue
                key = json.loads(line).get("canonical_key")
                if isinstance(key, str) and key.startswith("DRUG:"):
                    drugs.add(key)
    identity = {
        "dataset_public_id": manifest.get("dataset_public_id"),
        "canonical_build_key": manifest.get("canonical_build_key"),
        "canonical_build_content_hash": manifest.get("content_hash"),
        "dataset_lifecycle_state": manifest.get("dataset_lifecycle_state"),
    }
    return tuple(sorted(drugs)), identity


def _v2_answer(drug_key: str, catalogue) -> Dict[str, Any]:
    """What V2 coverage says about one drug, given today's real state.

    There is no coverage manifest, so a recognised drug is INSUFFICIENT and an
    unrecognised one is UNSUPPORTED_DRUG. Both are computed from the pinned
    catalogue rather than asserted, so the day a manifest exists this report
    changes and the change is visible.
    """
    if drug_key in catalogue:
        return {
            "recognized_in_canonical_dataset": True,
            "coverage_status": CoverageStatus.INSUFFICIENT.value,
            "reason_codes": [
                CoverageReasonCode.NO_VALIDATED_RULE_FOR_AXIS.value],
            "explanation": (
                "the pinned canonical dataset contains this chemical and no "
                "approved coverage scope declares what a complete assessment "
                "of it would require; recognition is not coverage"),
        }
    return {
        "recognized_in_canonical_dataset": False,
        "coverage_status": CoverageStatus.UNSUPPORTED_DRUG.value,
        "reason_codes": [
            CoverageReasonCode.DRUG_NOT_IN_CANONICAL_DATASET.value],
        "explanation": (
            "the pinned canonical dataset does not contain this chemical, so "
            "no axis exists to evaluate and none is fabricated"),
    }


def build_coverage_regression_report(repo_root: str = ".") -> Dict[str, Any]:
    """The deterministic legacy-versus-V2 coverage comparison.

    Sorted throughout, carrying no timestamp, path or host, and pinned to the
    exact canonical build identity it was computed against.
    """
    catalogue, identity = load_canonical_drug_catalogue(repo_root)
    catalogue_set = set(catalogue)
    p2 = _read_json(os.path.join(repo_root, P2_SNAPSHOT_RELATIVE))
    candidates = _read_json(os.path.join(repo_root,
                                         CANDIDATE_SNAPSHOT_RELATIVE))

    legacy_risk = {}
    for row in p2.get("drug_results", []):
        legacy_risk[str(row.get("drug"))] = row.get("overall_risk_level")
    legacy_scores = {}
    for row in candidates.get("candidate_results", []):
        legacy_scores[str(row.get("candidate_drug"))] = {
            "score": row.get("legacy_score_unprotected"),
            "data_status": row.get("mvp_data_status"),
        }

    covered: Dict[str, int] = {entry.difference_id: 0
                               for entry in EXPECTED_DIFFERENCES}
    unexpected = []
    cases = []

    # -- the P2 snapshot drugs -----------------------------------------
    for drug in sorted(legacy_risk):
        key = "DRUG:%s" % drug
        answer = _v2_answer(key, catalogue_set)
        legacy_value = legacy_risk[drug]
        reassuring = legacy_value in ("none", "low")
        differs = reassuring and answer["coverage_status"] != "FULL"
        difference_id = None
        for entry in EXPECTED_DIFFERENCES:
            selector = entry.comparison_selector
            if selector.get("drug") == drug and \
                    selector.get("artifact_id") == "risk-p2-cyp2c19-poor.json":
                difference_id = entry.difference_id
                break
        if differs and difference_id:
            covered[difference_id] += 1
        elif differs:
            unexpected.append({"source": "risk-p2-cyp2c19-poor.json",
                               "drug": drug,
                               "legacy_value": str(legacy_value),
                               "v2_coverage_status": answer["coverage_status"]})
        cases.append({
            "case_id": "P2-%s" % drug,
            "source": "risk-p2-cyp2c19-poor.json",
            "drug_id": key,
            "legacy_overall_risk_level": str(legacy_value),
            "legacy_rendered_as_reassuring": reassuring,
            "legacy_score": None,
            "v2_recognized": answer["recognized_in_canonical_dataset"],
            "v2_coverage_status": answer["coverage_status"],
            "v2_reason_codes": answer["reason_codes"],
            "v2_explanation": answer["explanation"],
            "v2_score": None,
            "expected_difference_id": difference_id if differs else None,
        })

    # -- the candidate snapshot drugs ----------------------------------
    for drug in sorted(legacy_scores):
        key = "DRUG:%s" % drug
        answer = _v2_answer(key, catalogue_set)
        legacy = legacy_scores[drug]
        difference_id = None
        for entry in EXPECTED_DIFFERENCES:
            selector = entry.comparison_selector
            if selector.get("drug") == drug and selector.get("artifact_id") == \
                    "alternative-beta-clopidogrel.json":
                difference_id = entry.difference_id
                break
        differs = legacy["score"] is not None
        if differs and difference_id:
            covered[difference_id] += 1
        elif differs:
            unexpected.append({"source": "alternative-beta-clopidogrel.json",
                               "drug": drug,
                               "legacy_value": str(legacy["score"]),
                               "v2_coverage_status": answer["coverage_status"]})
        cases.append({
            "case_id": "CANDIDATE-%s" % drug,
            "source": "alternative-beta-clopidogrel.json",
            "drug_id": key,
            "legacy_overall_risk_level": None,
            "legacy_rendered_as_reassuring": True,
            "legacy_score": legacy["score"],
            "v2_recognized": answer["recognized_in_canonical_dataset"],
            "v2_coverage_status": answer["coverage_status"],
            "v2_reason_codes": answer["reason_codes"],
            "v2_explanation": answer["explanation"],
            "v2_score": None,
            "expected_difference_id": difference_id if differs else None,
        })

    # -- a drug in no catalogue at all ---------------------------------
    unknown = "DRUG:definitely-not-a-real-chemical"
    unknown_answer = _v2_answer(unknown, catalogue_set)
    cases.append({
        "case_id": "UNKNOWN-DRUG",
        "source": "constructed",
        "drug_id": unknown,
        "legacy_overall_risk_level": "none",
        "legacy_rendered_as_reassuring": True,
        "legacy_score": None,
        "v2_recognized": unknown_answer["recognized_in_canonical_dataset"],
        "v2_coverage_status": unknown_answer["coverage_status"],
        "v2_reason_codes": unknown_answer["reason_codes"],
        "v2_explanation": unknown_answer["explanation"],
        "v2_score": None,
        "expected_difference_id": None,
    })

    missing = sorted(name for name, count in covered.items() if count == 0)
    report = {
        "report_schema_version": COVERAGE_REGRESSION_REPORT_VERSION,
        "canonical_build": identity,
        "canonical_drug_count": len(catalogue),
        "case_count": len(cases),
        "cases": sorted(cases, key=lambda item: item["case_id"]),
        "expected_differences": [entry.to_json()
                                 for entry in EXPECTED_DIFFERENCES],
        "expected_difference_hits": dict(sorted(covered.items())),
        "expected_differences_not_observed": missing,
        "unexpected_differences": sorted(
            unexpected, key=lambda item: (item["source"], item["drug"])),
        "real_coverage_manifests": 0,
        "note": (
            "Migration evidence, not clinical validation. No approved coverage "
            "manifest exists, so every V2 answer here is a form of 'not "
            "assessed, and here is the machine-readable reason'. That is the "
            "correction: the legacy engine reported the same situation as "
            "'low / no warning'. No coverage status in this report asserts "
            "safety, preference or suitability for any medicine, and no score "
            "appears anywhere because a coverage result has no field one "
            "could be written into."),
    }
    report["content_hash"] = sha256_digest(
        {key: value for key, value in report.items() if key != "content_hash"})
    return report
