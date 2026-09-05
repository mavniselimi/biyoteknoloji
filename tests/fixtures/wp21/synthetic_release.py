# -*- coding: utf-8 -*-
"""A TEST-ONLY synthetic release, case set and observations for WP-21.

Read the package docstring first: none of this is real. It exists to prove one
claim - that given a pinned release and eligible observations, the engine
computes a numerical validation table with correct arithmetic - and that claim
cannot be proven against a repository that has neither.

The numbers are chosen so the assertions are not all the same shape:

- INTERNAL_HOLDOUT: 8 cases, 6 concordant, 1 false reassurance, 2 repeats each
  with one case disagreeing between repeats, 20 findings of which 18 traceable.
- EXPERT_HOLDOUT: 3 cases, kept deliberately smaller than the internal set so
  a test can show that pooling them would change the answer - which is why
  there is no pooling.
- DEVELOPMENT: 7 cases, computed for regression only, every value marked
  ``is_validation_evidence: false``.

Any test that asserts an exact number should read it from here rather than
retyping it, so a change to the fixture cannot leave a stale expectation
passing.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
from typing import Dict, List, Mapping, Sequence, Tuple

from pgx.validation.benchmark_models import (BenchmarkObservation,
                                             BenchmarkPlan, PinnedRelease,
                                             ReferenceJudgment,
                                             ReferenceJudgmentPort,
                                             ReleaseResolutionPort,
                                             RestrictedObservationPort)
from pgx.validation.metric_definitions import METRIC_IDS
from pgx.validation.vocabulary import ValidationCaseRole

RELEASE_PUBLIC_ID = "TEST-ONLY-REL-0001"
DATASET_PUBLIC_ID = "TEST-ONLY-DS-0001"
RULESET_PUBLIC_ID = "TEST-ONLY-RS-0001"
SOFTWARE_VERSION = "TEST-ONLY-0.0.0"

#: Expected results, stated once so tests read them instead of retyping.
INTERNAL_CASE_COUNT = 8
INTERNAL_CONCORDANT = 6
INTERNAL_FALSE_REASSURANCE = 1
INTERNAL_FINDINGS = 20
INTERNAL_TRACEABLE_FINDINGS = 18
INTERNAL_REPEAT_AGREEMENTS = 7
EXPERT_CASE_COUNT = 3
EXPERT_CONCORDANT = 2
DEVELOPMENT_CASE_COUNT = 7


def _digest(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


RELEASE_MANIFEST_HASH = _digest("TEST-ONLY release manifest")
SOFTWARE_HASH = _digest("TEST-ONLY software")
DATASET_HASH = _digest("TEST-ONLY dataset")
RULESET_HASH = _digest("TEST-ONLY ruleset")
MANIFEST_HASHES: Mapping[str, str] = {
    ValidationCaseRole.DEVELOPMENT.value: _digest("TEST-ONLY dev manifest"),
    ValidationCaseRole.INTERNAL_HOLDOUT.value:
        _digest("TEST-ONLY internal manifest"),
    ValidationCaseRole.EXPERT_HOLDOUT.value:
        _digest("TEST-ONLY expert manifest"),
}


def pinned_release(*, release_public_id: str = RELEASE_PUBLIC_ID
                   ) -> PinnedRelease:
    return PinnedRelease(
        release_public_id=release_public_id,
        release_manifest_hash=RELEASE_MANIFEST_HASH,
        software_version=SOFTWARE_VERSION, software_hash=SOFTWARE_HASH,
        dataset_public_id=DATASET_PUBLIC_ID,
        dataset_content_hash=DATASET_HASH,
        ruleset_public_id=RULESET_PUBLIC_ID,
        ruleset_content_hash=RULESET_HASH,
        resolved_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc),
        active_pointer_generation=4)


def plan(*, roles: Sequence[ValidationCaseRole] = None,
         repeat_count: int = 2, release: PinnedRelease = None,
         metric_ids: Sequence[str] = None) -> BenchmarkPlan:
    roles = tuple(roles or (ValidationCaseRole.DEVELOPMENT,
                            ValidationCaseRole.INTERNAL_HOLDOUT,
                            ValidationCaseRole.EXPERT_HOLDOUT))
    return BenchmarkPlan(
        plan_id="TEST-ONLY-PLAN-0001",
        pinned_release=release or pinned_release(),
        roles=roles,
        case_manifest_hashes={role.value: MANIFEST_HASHES[role.value]
                              for role in roles},
        declared_metric_ids=tuple(metric_ids or METRIC_IDS),
        repeat_count=repeat_count,
        note="TEST-ONLY synthetic plan; names no real release")


def _observation(case_id: str, role: ValidationCaseRole, *,
                 attention: str, coverage: str,
                 coverage_reason: str = None, rule_id: str = None,
                 findings: int = 2, traceable: int = 2,
                 conflict: bool = False, repeats: int = 2,
                 repeats_agree: bool = True,
                 failure_paths: Sequence[str] = (),
                 release: PinnedRelease = None) -> BenchmarkObservation:
    release = release or pinned_release()
    hashes: List[str] = []
    for index in range(repeats):
        seed = case_id if repeats_agree else "%s-%d" % (case_id, index)
        hashes.append(_digest("TEST-ONLY output " + seed))
    return BenchmarkObservation(
        case_id=case_id, role=role,
        release_public_id=release.release_public_id,
        release_manifest_hash=release.release_manifest_hash,
        software_version=release.software_version,
        software_hash=release.software_hash,
        dataset_public_id=release.dataset_public_id,
        dataset_content_hash=release.dataset_content_hash,
        ruleset_public_id=release.ruleset_public_id,
        ruleset_content_hash=release.ruleset_content_hash,
        case_manifest_hash=MANIFEST_HASHES[role.value],
        attention_level=attention, coverage_status=coverage,
        coverage_reason=coverage_reason, firing_rule_id=rule_id,
        finding_count=findings, traceable_finding_count=traceable,
        unresolved_conflict=conflict, output_hashes=tuple(hashes),
        failure_paths=tuple(failure_paths))


def internal_holdout_observations(release: PinnedRelease = None
                                  ) -> Tuple[BenchmarkObservation, ...]:
    """Eight cases: six concordant, one falsely reassuring, one flaky repeat."""
    role = ValidationCaseRole.INTERNAL_HOLDOUT
    items = [
        _observation("TEST-ONLY-IH-001", role, attention="HIGH",
                     coverage="FULL", rule_id="SYNTH-RULE-1",
                     findings=3, traceable=3, release=release),
        _observation("TEST-ONLY-IH-002", role, attention="MEDIUM",
                     coverage="FULL", rule_id="SYNTH-RULE-2",
                     findings=3, traceable=3, release=release),
        _observation("TEST-ONLY-IH-003", role, attention="NOT_ASSESSED",
                     coverage="PARTIAL", coverage_reason="MISSING_AXIS",
                     findings=2, traceable=2,
                     failure_paths=("FP-002", "FP-004"), release=release),
        _observation("TEST-ONLY-IH-004", role, attention="NOT_ASSESSED",
                     coverage="INSUFFICIENT",
                     coverage_reason="UNSUPPORTED_MEDICATION",
                     findings=2, traceable=2,
                     failure_paths=("FP-001", "FP-005"), release=release),
        _observation("TEST-ONLY-IH-005", role, attention="HIGH",
                     coverage="FULL", rule_id="SYNTH-RULE-3",
                     findings=3, traceable=2, release=release),
        _observation("TEST-ONLY-IH-006", role, attention="LOW",
                     coverage="FULL", rule_id="SYNTH-RULE-4",
                     findings=3, traceable=3, release=release),
        # The one that got it wrong: reassuring words on incomplete coverage.
        _observation("TEST-ONLY-IH-007", role, attention="LOW",
                     coverage="PARTIAL", coverage_reason="MISSING_AXIS",
                     rule_id="SYNTH-RULE-5", findings=2, traceable=1,
                     failure_paths=("FP-004",), release=release),
        # The one whose repeats disagreed.
        _observation("TEST-ONLY-IH-008", role, attention="MEDIUM",
                     coverage="FULL", rule_id="SYNTH-RULE-6",
                     findings=2, traceable=2, repeats_agree=False,
                     conflict=True, failure_paths=("FP-006",),
                     release=release),
    ]
    return tuple(items)


def expert_holdout_observations(release: PinnedRelease = None
                                ) -> Tuple[BenchmarkObservation, ...]:
    role = ValidationCaseRole.EXPERT_HOLDOUT
    return (
        _observation("TEST-ONLY-EH-001", role, attention="HIGH",
                     coverage="FULL", rule_id="SYNTH-RULE-7",
                     findings=2, traceable=2, release=release),
        _observation("TEST-ONLY-EH-002", role, attention="MEDIUM",
                     coverage="FULL", rule_id="SYNTH-RULE-8",
                     findings=2, traceable=2, release=release),
        _observation("TEST-ONLY-EH-003", role, attention="HIGH",
                     coverage="FULL", rule_id="SYNTH-RULE-9",
                     findings=2, traceable=1, release=release),
    )


def development_observations(release: PinnedRelease = None
                             ) -> Tuple[BenchmarkObservation, ...]:
    role = ValidationCaseRole.DEVELOPMENT
    return tuple(
        _observation("TEST-ONLY-DEV-%03d" % index, role,
                     attention="HIGH" if index % 2 else "NOT_ASSESSED",
                     coverage="FULL" if index % 2 else "PARTIAL",
                     coverage_reason=None if index % 2 else "MISSING_AXIS",
                     rule_id="SYNTH-RULE-D%d" % index, findings=2,
                     traceable=2,
                     failure_paths=() if index % 2 else ("FP-002",),
                     release=release)
        for index in range(1, DEVELOPMENT_CASE_COUNT + 1))


def internal_judgments() -> Dict[str, ReferenceJudgment]:
    """Six of the eight match; two deliberately do not."""
    expected = {
        "TEST-ONLY-IH-001": ("HIGH", "FULL", "SYNTH-RULE-1"),
        "TEST-ONLY-IH-002": ("MEDIUM", "FULL", "SYNTH-RULE-2"),
        "TEST-ONLY-IH-003": ("NOT_ASSESSED", "PARTIAL", None),
        "TEST-ONLY-IH-004": ("NOT_ASSESSED", "INSUFFICIENT", None),
        "TEST-ONLY-IH-005": ("HIGH", "FULL", "SYNTH-RULE-3"),
        "TEST-ONLY-IH-006": ("LOW", "FULL", "SYNTH-RULE-4"),
        # The system said LOW/PARTIAL; the reference says it should have
        # refused. This is the disagreement the metric is meant to catch.
        "TEST-ONLY-IH-007": ("NOT_ASSESSED", "PARTIAL", None),
        "TEST-ONLY-IH-008": ("HIGH", "FULL", "SYNTH-RULE-6"),
    }
    return {case_id: ReferenceJudgment(
        case_id=case_id, expected_attention_level=level,
        expected_coverage_status=coverage, expected_rule_id=rule,
        expected_coverage_reason=None, requires_evidence=True,
        provenance="TEST-ONLY synthetic reference judgment; no person "
                   "decided this and it is not evidence about anything")
        for case_id, (level, coverage, rule) in expected.items()}


def expert_judgments() -> Dict[str, ReferenceJudgment]:
    expected = {
        "TEST-ONLY-EH-001": ("HIGH", "FULL", "SYNTH-RULE-7"),
        "TEST-ONLY-EH-002": ("MEDIUM", "FULL", "SYNTH-RULE-8"),
        "TEST-ONLY-EH-003": ("MEDIUM", "FULL", "SYNTH-RULE-9"),
    }
    return {case_id: ReferenceJudgment(
        case_id=case_id, expected_attention_level=level,
        expected_coverage_status=coverage, expected_rule_id=rule,
        requires_evidence=True,
        provenance="TEST-ONLY synthetic reference judgment")
        for case_id, (level, coverage, rule) in expected.items()}


class SyntheticReleaseResolver(ReleaseResolutionPort):
    """Resolves the TEST-ONLY release. Reads nothing and activates nothing."""

    def __init__(self, release: PinnedRelease = None) -> None:
        self._release = release or pinned_release()

    def resolve(self) -> PinnedRelease:
        return self._release


class SyntheticObservationPort(RestrictedObservationPort):
    """Returns the fixture observations for a role."""

    def __init__(self, *, release: PinnedRelease = None,
                 overrides: Mapping[str, Sequence[BenchmarkObservation]] = None
                 ) -> None:
        self._release = release
        self._overrides = dict(overrides or {})

    def observe(self, *, role, plan) -> Sequence[BenchmarkObservation]:
        if role.value in self._overrides:
            return self._overrides[role.value]
        if role is ValidationCaseRole.INTERNAL_HOLDOUT:
            return internal_holdout_observations(self._release)
        if role is ValidationCaseRole.EXPERT_HOLDOUT:
            return expert_holdout_observations(self._release)
        return development_observations(self._release)


class SyntheticJudgmentPort(ReferenceJudgmentPort):
    """Supplies TEST-ONLY reference judgments for the holdout roles."""

    def __init__(self, *, include_expert: bool = True) -> None:
        self._include_expert = include_expert

    def judgments(self, *, role) -> Mapping[str, ReferenceJudgment]:
        if role is ValidationCaseRole.INTERNAL_HOLDOUT:
            return internal_judgments()
        if role is ValidationCaseRole.EXPERT_HOLDOUT and self._include_expert:
            return expert_judgments()
        return {}
