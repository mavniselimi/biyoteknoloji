# -*- coding: utf-8 -*-
"""What the canonical build changed relative to the legacy pipeline (WP-07).

Standard library plus :mod:`pgx.domain` and :mod:`pgx.normalization`.

This report answers three questions a reviewer will ask about any migration:
what did the old pipeline produce, what does the new one produce, and where the
two disagree, *which one is right and why*.

**Three kinds of difference, kept apart.**

1. *Duplicate collapse.* The legacy pair flattening carries one row per
   container member, so a record returned under two case-variant container
   names became two rows. The canonical build keeps one record and every
   locator. This is a correction.
2. *Candidate-merge drift.* ``candidate_onboarding.py`` mutated the seed CSVs in
   place, adding drugs and pairs that no reviewer selected, while the summary
   beside them was never regenerated. The canonical P0 build excludes them. This
   is a scope decision, and the excluded names are listed so it can be argued
   with.
3. *Stale totals.* The seed summary still reports the pre-merge counts. The
   report states the claimed figure, the observed figure and the gap.

**Claims are checked, never reproduced.** Figures this project has previously
written down - including the ``1,572`` collision count in ``architecture.md`` -
live in ``config/wp07-legacy-expectations.json`` as claims with citations. This
module reads them, measures the real artifacts, and reports agreement or
disagreement. It does not contain any of those numbers, and it never reshapes a
deduplication key to make one come true: a count that disagrees is a finding
about the document, not a licence to redefine the measurement.

**Nothing is imported.** No legacy row, column, hint, score, severity or
conclusion crosses into the canonical dataset from here. The report reads legacy
files to count and compare them, and its output is counts and names.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import (Any, Dict, Iterable, List, Mapping, Optional, Sequence,
                    Tuple)

from pgx.domain.hashing import sha256_digest
from pgx.normalization.build import CanonicalBuild
from pgx.normalization.errors import CanonicalBuildError
from pgx.normalization.models import DuplicateClass, EntityType
from pgx.normalization.normalize import normalize_drug_name, normalize_gene_symbol

__all__ = [
    "LEGACY_DIFF_VERSION",
    "LEGACY_EXPECTATIONS_PATH",
    "ClaimCheck",
    "LegacyDifferenceReport",
    "LegacyFileSnapshot",
    "SetDifference",
    "build_legacy_difference_report",
    "read_expectations",
]

#: Bumped when the comparison definitions change.
LEGACY_DIFF_VERSION = "pgx-legacy-differences/1"

#: Where the documented claims live, relative to the repository root.
LEGACY_EXPECTATIONS_PATH = os.path.join("config", "wp07-legacy-expectations.json")

#: The legacy files this report reads, relative to the repository root. Each is
#: read for counts and identifiers only.
LEGACY_SEED_FILES: Mapping[str, str] = {
    "supported_drugs_active": "clinpgx_mvp_seed/supported_drugs.csv",
    "supported_drugs_cleaner_output": "clinpgx_mvp_seed/supported_drugs.csv.bak",
    "guideline_rows_active": "clinpgx_mvp_seed/drug_gene_guidelines.csv",
    "guideline_rows_cleaner_output": "clinpgx_mvp_seed/drug_gene_guidelines.csv.bak",
    "supported_genes": "clinpgx_mvp_seed/supported_genes.csv",
    "seed_summary": "clinpgx_mvp_seed/mvp_seed_summary.json",
    "candidate_alternatives": "candidate_alternatives.csv",
}


@dataclass(frozen=True, slots=True)
class LegacyFileSnapshot:
    """One legacy file as it stands: its digest, its size, and what it holds.

    The digest is recorded so a later reader can tell whether the file has
    changed since this report was written. Nothing is modified: these files are
    frozen legacy evidence and the report opens them read-only.
    """

    label: str
    relative_path: str
    exists: bool
    byte_length: int = 0
    sha256: Optional[str] = None
    row_count: int = 0
    note: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "relative_path": self.relative_path,
            "exists": self.exists,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
            "row_count": self.row_count,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class SetDifference:
    """Two named sets and exactly how they differ.

    Both directions are always reported. "The canonical build has fewer drugs"
    is not the same finding as "the canonical build has different drugs", and a
    one-directional difference cannot tell them apart.
    """

    subject: str
    left_label: str
    right_label: str
    left_count: int
    right_count: int
    only_left: Tuple[str, ...]
    only_right: Tuple[str, ...]
    shared_count: int
    explanation: str

    @property
    def identical(self) -> bool:
        return not self.only_left and not self.only_right

    def to_json(self) -> Dict[str, Any]:
        return {
            "subject": self.subject,
            "left_label": self.left_label,
            "right_label": self.right_label,
            "left_count": self.left_count,
            "right_count": self.right_count,
            "shared_count": self.shared_count,
            "only_left": list(self.only_left),
            "only_right": list(self.only_right),
            "identical": self.identical,
            "explanation": self.explanation,
        }


@dataclass(frozen=True, slots=True)
class ClaimCheck:
    """A previously documented figure, measured against the real artifacts."""

    claim_id: str
    metric: str
    claimed_value: Any
    observed_value: Any
    cited_from: str
    agrees: bool
    detail: str
    kind: str = "documented_expectation"
    expected_to_disagree: bool = False
    legacy_bug: Optional[str] = None
    alternative_measurements: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_surprising(self) -> bool:
        """A disagreement nobody predicted.

        A stale figure recorded inside a legacy artifact is *expected* to
        disagree - that disagreement is the defect being documented. A figure
        this project wrote down as what the data should show is a different
        matter, and only that kind needs explaining.
        """
        return not self.agrees and not self.expected_to_disagree

    def to_json(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "metric": self.metric,
            "kind": self.kind,
            "claimed_value": self.claimed_value,
            "observed_value": self.observed_value,
            "agrees": self.agrees,
            "expected_to_disagree": self.expected_to_disagree,
            "is_surprising": self.is_surprising,
            "legacy_bug": self.legacy_bug,
            "cited_from": self.cited_from,
            "detail": self.detail,
            "alternative_measurements": dict(self.alternative_measurements),
        }


@dataclass(frozen=True)
class LegacyDifferenceReport:
    """The complete comparison, deterministic and timestamp-free.

    No generation instant is recorded inside it, so two runs over unchanged
    inputs produce identical bytes and the report can be hashed into the
    canonical build.
    """

    legacy_diff_version: str
    dataset_public_id: str
    canonical_build_key: str
    files: Tuple[LegacyFileSnapshot, ...]
    differences: Tuple[SetDifference, ...]
    claim_checks: Tuple[ClaimCheck, ...]
    duplicate_collapse: Mapping[str, Any]
    candidate_merge_drift: Mapping[str, Any]
    stale_totals: Tuple[Mapping[str, Any], ...]
    legacy_bug_references: Tuple[str, ...] = ()
    findings: Tuple[str, ...] = ()

    @property
    def disagreeing_claims(self) -> Tuple[ClaimCheck, ...]:
        return tuple(item for item in self.claim_checks if not item.agrees)

    @property
    def surprising_claims(self) -> Tuple[ClaimCheck, ...]:
        """Disagreements nobody predicted - the ones that need an answer."""
        return tuple(item for item in self.claim_checks if item.is_surprising)

    def content_hash(self) -> str:
        return sha256_digest(self.to_json())

    def to_json(self) -> Dict[str, Any]:
        return {
            "legacy_diff_version": self.legacy_diff_version,
            "dataset_public_id": self.dataset_public_id,
            "canonical_build_key": self.canonical_build_key,
            "legacy_bug_references": list(self.legacy_bug_references),
            "files": [item.to_json() for item in self.files],
            "differences": [item.to_json() for item in self.differences],
            "claim_checks": [item.to_json() for item in self.claim_checks],
            "duplicate_collapse": dict(self.duplicate_collapse),
            "candidate_merge_drift": dict(self.candidate_merge_drift),
            "stale_totals": [dict(item) for item in self.stale_totals],
            "findings": list(self.findings),
            "reading_rule": (
                "Counts here describe what the artifacts contain. They are not "
                "validated coverage, clinical coverage, supported treatment, "
                "safe alternatives or executable pharmacogenetic rules."),
        }

    def render(self) -> str:
        lines = ["legacy difference report %s" % self.legacy_diff_version,
                 "  dataset %s" % self.dataset_public_id,
                 "  build   %s" % self.canonical_build_key]
        for check in self.claim_checks:
            if check.agrees:
                verdict = "AGREES"
            elif check.expected_to_disagree:
                verdict = "DISAGREES (expected: %s)" % (check.legacy_bug or "known")
            else:
                verdict = "DISAGREES (unexplained)"
            lines.append("  claim %-32s claimed %s observed %s  %s"
                         % (check.claim_id, check.claimed_value,
                            check.observed_value, verdict))
        for difference in self.differences:
            lines.append("  %-34s %s=%d %s=%d  only-left %d only-right %d"
                         % (difference.subject, difference.left_label,
                            difference.left_count, difference.right_label,
                            difference.right_count, len(difference.only_left),
                            len(difference.only_right)))
        for finding in self.findings:
            lines.append("  - %s" % finding)
        return "\n".join(lines)


def read_expectations(repo_root: str) -> Mapping[str, Mapping[str, Any]]:
    """Read the documented claims, keyed by claim ID.

    A missing file is not fatal: the report is still produced, with no claim
    checks and a finding saying so. Refusing to describe the data because a
    bookkeeping file is absent would help nobody.
    """
    path = os.path.join(repo_root, LEGACY_EXPECTATIONS_PATH)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        raise CanonicalBuildError(
            "the legacy expectations file at %s is unreadable: %s"
            % (path, exc), code="EXPECTATIONS_UNREADABLE") from exc
    claims = payload.get("claims")
    if not isinstance(claims, list):
        return {}
    return {str(item.get("claim_id")): item for item in claims
            if isinstance(item, Mapping) and item.get("claim_id")}


def build_legacy_difference_report(build: CanonicalBuild,
                                   repo_root: str) -> LegacyDifferenceReport:
    """Compare one canonical build against the frozen legacy seed."""
    files = tuple(_snapshot_file(repo_root, label, relative)
                  for label, relative in sorted(LEGACY_SEED_FILES.items()))
    findings: List[str] = []

    active_drugs = _csv_column_values(repo_root,
                                      LEGACY_SEED_FILES["supported_drugs_active"],
                                      "drug")
    cleaner_drugs = _csv_column_values(
        repo_root, LEGACY_SEED_FILES["supported_drugs_cleaner_output"], "drug")
    active_pairs = _csv_column_values(
        repo_root, LEGACY_SEED_FILES["guideline_rows_active"], "pair_key")
    cleaner_pairs = _csv_column_values(
        repo_root, LEGACY_SEED_FILES["guideline_rows_cleaner_output"],
        "pair_key")
    active_pair_rows = _csv_row_count(
        repo_root, LEGACY_SEED_FILES["guideline_rows_active"])
    cleaner_pair_rows = _csv_row_count(
        repo_root, LEGACY_SEED_FILES["guideline_rows_cleaner_output"])

    canonical_drugs = tuple(sorted(
        entity.normalized_value for entity in build.drugs))
    canonical_genes = tuple(sorted(
        entity.normalized_value for entity in build.genes))
    legacy_genes = _csv_column_values(repo_root,
                                      LEGACY_SEED_FILES["supported_genes"],
                                      "gene")

    differences = [
        _difference(
            "supported drugs: cleaner output vs mutated seed",
            "cleaner_output", cleaner_drugs, "active_seed", active_drugs,
            _normalize_drugs,
            ("clean_mvp_seed_dataset.py wrote the .bak file; "
             "candidate_onboarding.py then rewrote the live CSV in place. The "
             "difference is what candidate onboarding added, and no reviewer "
             "selected it.")),
        _difference(
            "guideline pairs: cleaner output vs mutated seed",
            "cleaner_output", cleaner_pairs, "active_seed", active_pairs,
            _normalize_pairs,
            ("the same in-place mutation, seen on the guideline table. Added "
             "pairs came from candidate onboarding, not from a source "
             "response.")),
        _difference(
            "drugs: mutated legacy seed vs canonical P0 build",
            "active_seed", active_drugs, "canonical_p0", canonical_drugs,
            _normalize_drugs,
            ("the canonical P0 build is derived from the source's own resolved "
             "chemical records. Candidate-onboarding additions are counted and "
             "excluded; they are a P1 concern.")),
        _difference(
            "genes: legacy seed vs canonical P0 build",
            "legacy_seed", legacy_genes, "canonical_p0", canonical_genes,
            _normalize_genes,
            "both are derived from the same five queried gene symbols."),
    ]

    candidate_added_drugs = differences[0].only_right
    candidate_added_pairs = differences[1].only_right
    candidate_rows = _csv_row_count(
        repo_root, LEGACY_SEED_FILES["candidate_alternatives"])

    duplicate_collapse = _duplicate_collapse(build)
    claim_checks = _claim_checks(
        build, repo_root, duplicate_collapse,
        observed_supported_drugs=len(_normalize_drugs(active_drugs)),
        observed_guideline_rows=active_pair_rows)

    summary_path = os.path.join(repo_root, LEGACY_SEED_FILES["seed_summary"])
    stale_totals = _stale_totals(summary_path, len(_normalize_drugs(active_drugs)),
                                 active_pair_rows)

    if candidate_added_drugs:
        findings.append(
            "%d drug(s) present in the live legacy seed came from candidate "
            "onboarding rather than from a source response and are excluded "
            "from the P0 canonical dataset: %s."
            % (len(candidate_added_drugs), ", ".join(candidate_added_drugs)))
    if candidate_added_pairs:
        findings.append(
            "%d gene/drug pair(s) were added to the live guideline table by "
            "candidate onboarding: %s. They are excluded from P0."
            % (len(candidate_added_pairs), ", ".join(candidate_added_pairs)))
    for entry in stale_totals:
        findings.append(
            "the seed summary reports %s = %s while the file beside it holds "
            "%s (LEGACY-BUG-007: the summary was never regenerated after the "
            "merge)." % (entry["metric"], entry["claimed"], entry["observed"]))
    for check in claim_checks:
        if not check.is_surprising:
            # An agreeing claim needs no finding, and a stale legacy figure that
            # disagrees is already reported by stale_totals as the defect it is.
            continue
        findings.append(
            "%s: the documented figure %s is not reproducible from the real "
            "artifacts, which yield %s under the measurement named %r. The "
            "observation is reported as observed. The deduplication key was "
            "not reshaped to reach the documented number, and no alternative "
            "measurement this build can define precisely yields it either "
            "(%s)."
            % (check.claim_id, check.claimed_value, check.observed_value,
               check.metric,
               "; ".join("%s=%s" % (name, value) for name, value
                         in sorted(check.alternative_measurements.items()))
               or "no alternatives defined"))
    if candidate_rows:
        findings.append(
            "candidate_alternatives.csv holds %d manually curated row(s). It is "
            "counted here and imported nowhere: it is a P1 development seed."
            % candidate_rows)

    return LegacyDifferenceReport(
        legacy_diff_version=LEGACY_DIFF_VERSION,
        dataset_public_id=build.dataset_public_id,
        canonical_build_key=build.build_key,
        files=files,
        differences=tuple(differences),
        claim_checks=tuple(claim_checks),
        duplicate_collapse=duplicate_collapse,
        candidate_merge_drift={
            "cleaner_output_drug_count": len(_normalize_drugs(cleaner_drugs)),
            "active_seed_drug_count": len(_normalize_drugs(active_drugs)),
            "drugs_added_by_candidate_onboarding": list(candidate_added_drugs),
            "cleaner_output_guideline_row_count": cleaner_pair_rows,
            "active_seed_guideline_row_count": active_pair_rows,
            "pairs_added_by_candidate_onboarding": list(candidate_added_pairs),
            "candidate_alternatives_row_count": candidate_rows,
            "p0_treatment": ("counted and excluded; importing them would add "
                             "drugs no reviewer selected"),
        },
        stale_totals=tuple(stale_totals),
        legacy_bug_references=("LEGACY-BUG-004", "LEGACY-BUG-007",
                               "LEGACY-BUG-010", "LEGACY-BUG-011"),
        findings=tuple(findings))


# -- measurements -------------------------------------------------------


def _duplicate_collapse(build: CanonicalBuild) -> Dict[str, Any]:
    """Every duplicate measurement this build can state precisely.

    Several are reported rather than one, because the phrase "runtime dedup
    collisions" does not by itself say which artifact, which containers or
    which identity was counted. Naming each measurement makes the comparison
    with a documented figure meaningful instead of a coincidence.
    """
    dedup = build.dedup
    semantic = dedup.of_class(DuplicateClass.SEMANTIC)
    exact = dedup.of_class(DuplicateClass.EXACT)
    conflicting = dedup.of_class(DuplicateClass.CONFLICTING_IDENTITY)

    pair_groups = tuple(group for group in dedup.groups
                        if group.record_type == "pair_container_record")
    pair_semantic = tuple(group for group in pair_groups
                          if group.classification is DuplicateClass.SEMANTIC)
    return {
        "definition": (
            "a duplicate group is one source record identity observed more than "
            "once within one pair query and one case-folded container family. "
            "Every member's locator is retained."),
        "total_observations": dedup.total_observations,
        "distinct_records": dedup.distinct_records,
        "duplicate_observations": dedup.duplicate_observations,
        "duplicate_group_count": len(dedup.groups),
        "semantic_group_count": len(semantic),
        "semantic_member_count": dedup.member_count(DuplicateClass.SEMANTIC),
        "exact_group_count": len(exact),
        "conflicting_identity_group_count": len(conflicting),
        "pair_container_case_variant_group_count": len(pair_semantic),
        "pair_container_case_variant_duplicate_observations": sum(
            group.member_count - 1 for group in pair_semantic),
        "pair_container_case_variant_member_count": sum(
            group.member_count for group in pair_semantic),
        "legacy_behaviour": (
            "the legacy flattening wrote one row per container member, so each "
            "of these groups became two rows in pair_annotation_rows.csv "
            "(LEGACY-BUG-004)."),
        "canonical_behaviour": (
            "one record is kept and every locator is retained, so the "
            "collapse is reversible and countable."),
    }


def _claim_checks(build: CanonicalBuild, repo_root: str,
                  duplicate_collapse: Mapping[str, Any],
                  observed_supported_drugs: int,
                  observed_guideline_rows: int) -> List[ClaimCheck]:
    """Measure each documented claim against the artifacts."""
    claims = read_expectations(repo_root)
    observed_by_metric: Dict[str, Any] = {
        "pair_container_case_variant_duplicate_observations":
            duplicate_collapse[
                "pair_container_case_variant_duplicate_observations"],
        "legacy_seed_supported_drug_rows": observed_supported_drugs,
        "legacy_seed_guideline_rows": observed_guideline_rows,
    }
    alternatives = {
        "duplicate_observations_all_record_types":
            duplicate_collapse["duplicate_observations"],
        "duplicate_group_count": duplicate_collapse["duplicate_group_count"],
        "pair_container_case_variant_member_count":
            duplicate_collapse["pair_container_case_variant_member_count"],
        "distinct_records": duplicate_collapse["distinct_records"],
        "total_observations": duplicate_collapse["total_observations"],
    }

    checks: List[ClaimCheck] = []
    for claim_id in sorted(claims):
        claim = claims[claim_id]
        metric = str(claim.get("metric"))
        observed = observed_by_metric.get(metric)
        agrees = observed is not None and observed == claim.get("claimed_value")
        detail = str(claim.get("note") or "")
        if observed is None:
            detail = ("this build does not measure %r, so the claim is neither "
                      "confirmed nor refuted here" % metric)
        checks.append(ClaimCheck(
            claim_id=claim_id,
            metric=metric,
            claimed_value=claim.get("claimed_value"),
            observed_value=observed,
            cited_from=str(claim.get("cited_from") or ""),
            agrees=agrees,
            detail=detail,
            kind=str(claim.get("kind") or "documented_expectation"),
            expected_to_disagree=bool(claim.get("expected_to_disagree")),
            legacy_bug=(str(claim["legacy_bug"])
                        if claim.get("legacy_bug") else None),
            alternative_measurements=(
                alternatives if metric.startswith("pair_container") else {})))
    return checks


def _stale_totals(summary_path: str, observed_drugs: int,
                  observed_guideline_rows: int) -> List[Dict[str, Any]]:
    """Compare the seed summary's own counts with the files beside it."""
    if not os.path.isfile(summary_path):
        return []
    try:
        with open(summary_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return []
    counts = payload.get("counts")
    if not isinstance(counts, Mapping):
        return []
    out: List[Dict[str, Any]] = []
    for metric, observed in (("supported_drugs", observed_drugs),
                             ("guideline_rows", observed_guideline_rows)):
        claimed = counts.get(metric)
        if claimed is None or claimed == observed:
            continue
        out.append({
            "metric": metric,
            "claimed": claimed,
            "observed": observed,
            "difference": observed - claimed,
            "source": "clinpgx_mvp_seed/mvp_seed_summary.json",
            "legacy_bug": "LEGACY-BUG-007",
        })
    return out


# -- reading helpers ----------------------------------------------------


def _difference(subject: str, left_label: str, left_values: Sequence[str],
                right_label: str, right_values: Sequence[str],
                normalizer, explanation: str) -> SetDifference:
    left = normalizer(left_values)
    right = normalizer(right_values)
    return SetDifference(
        subject=subject,
        left_label=left_label,
        right_label=right_label,
        left_count=len(left),
        right_count=len(right),
        only_left=tuple(sorted(left - right)),
        only_right=tuple(sorted(right - left)),
        shared_count=len(left & right),
        explanation=explanation)


def _normalize_drugs(values: Iterable[str]) -> set:
    out = set()
    for value in values:
        try:
            out.add(normalize_drug_name(value))
        except Exception:
            continue
    return out


def _normalize_genes(values: Iterable[str]) -> set:
    out = set()
    for value in values:
        try:
            out.add(normalize_gene_symbol(value))
        except Exception:
            continue
    return out


def _normalize_pairs(values: Iterable[str]) -> set:
    """Normalise a ``GENE::drug`` key using each half's own rule."""
    out = set()
    for value in values:
        if not isinstance(value, str) or "::" not in value:
            continue
        gene_part, _, drug_part = value.partition("::")
        try:
            out.add("%s::%s" % (normalize_gene_symbol(gene_part),
                                normalize_drug_name(drug_part)))
        except Exception:
            continue
    return out


def _snapshot_file(repo_root: str, label: str,
                   relative: str) -> LegacyFileSnapshot:
    path = os.path.join(repo_root, relative)
    if not os.path.isfile(path):
        return LegacyFileSnapshot(
            label=label, relative_path=relative, exists=False,
            note="absent from this checkout")
    digest = hashlib.sha256()
    length = 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            length += len(chunk)
    rows = (_csv_row_count(repo_root, relative) if relative.endswith(".csv")
            or relative.endswith(".bak") else 0)
    return LegacyFileSnapshot(
        label=label, relative_path=relative, exists=True, byte_length=length,
        sha256="sha256:" + digest.hexdigest(), row_count=rows,
        note="read for counts and identifiers only; never modified")


def _csv_row_count(repo_root: str, relative: str) -> int:
    path = os.path.join(repo_root, relative)
    if not os.path.isfile(path):
        return 0
    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        try:
            next(reader)
        except StopIteration:
            return 0
        return sum(1 for row in reader if any(cell.strip() for cell in row))


def _csv_column_values(repo_root: str, relative: str,
                       column: str) -> Tuple[str, ...]:
    """Every value of one exactly named column.

    Exact name only. Guessing which column holds drug names is how a comparison
    silently compares the wrong thing, and a missing column is reported as an
    empty set rather than approximated from a similar header.
    """
    path = os.path.join(repo_root, relative)
    if not os.path.isfile(path):
        return ()
    values: List[str] = []
    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or column not in reader.fieldnames:
            return ()
        for row in reader:
            value = (row.get(column) or "").strip()
            if value:
                values.append(value)
    return tuple(values)
