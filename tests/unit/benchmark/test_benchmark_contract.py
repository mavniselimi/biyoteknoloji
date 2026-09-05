# -*- coding: utf-8 -*-
"""Pinning, mismatch and separation: the run refuses before it computes.

Every test here is about a refusal. That is the shape of the work package: the
easy failure is a benchmark that produces a number for a run it cannot
describe, so most of the contract is about the conditions under which no
number is produced at all.
"""

from __future__ import annotations

import datetime as _dt
import unittest

from pgx.validation.benchmark import (BenchmarkEngine, SeparationNotCleanError,
                                      verify_observation)
from pgx.validation.benchmark_models import (BenchmarkError, BenchmarkPlan,
                                             BenchmarkRun, PinMismatchError,
                                             PinnedRelease, UnpinnedError)
from pgx.validation.vocabulary import ValidationCaseRole as Role
from tests.fixtures.wp21 import synthetic_release as S


class TestAPlanPinsEverything(unittest.TestCase):
    """Requirements 11 and 12."""

    def test_a_plan_names_the_release_and_all_four_hashes(self):
        plan = S.plan()
        pinned = plan.pinned_release
        self.assertEqual(pinned.release_public_id, S.RELEASE_PUBLIC_ID)
        for name in ("release_manifest_hash", "software_hash",
                     "dataset_content_hash", "ruleset_content_hash"):
            with self.subTest(field=name):
                self.assertRegex(getattr(pinned, name),
                                 r"^sha256:[0-9a-f]{64}$")

    def test_a_missing_release_hash_is_refused(self):
        with self.assertRaises(UnpinnedError):
            PinnedRelease(
                release_public_id=S.RELEASE_PUBLIC_ID,
                release_manifest_hash="", software_version=S.SOFTWARE_VERSION,
                software_hash=S.SOFTWARE_HASH,
                dataset_public_id=S.DATASET_PUBLIC_ID,
                dataset_content_hash=S.DATASET_HASH,
                ruleset_public_id=S.RULESET_PUBLIC_ID,
                ruleset_content_hash=S.RULESET_HASH,
                resolved_at=_dt.datetime(2026, 1, 1,
                                         tzinfo=_dt.timezone.utc))

    def test_a_role_without_a_case_manifest_hash_is_refused(self):
        with self.assertRaises(UnpinnedError):
            BenchmarkPlan(plan_id="TEST-ONLY-PLAN-X",
                          pinned_release=S.pinned_release(),
                          roles=(Role.INTERNAL_HOLDOUT, Role.EXPERT_HOLDOUT),
                          case_manifest_hashes={
                              Role.INTERNAL_HOLDOUT.value:
                                  S.MANIFEST_HASHES[
                                      Role.INTERNAL_HOLDOUT.value]},
                          declared_metric_ids=("PGX-VAL-001",))

    def test_a_plan_declaring_no_metric_is_refused(self):
        with self.assertRaises(UnpinnedError):
            BenchmarkPlan(plan_id="TEST-ONLY-PLAN-Y",
                          pinned_release=S.pinned_release(),
                          roles=(Role.INTERNAL_HOLDOUT,),
                          case_manifest_hashes={
                              Role.INTERNAL_HOLDOUT.value:
                                  S.MANIFEST_HASHES[
                                      Role.INTERNAL_HOLDOUT.value]},
                          declared_metric_ids=())

    def test_the_plan_hash_covers_the_pins(self):
        first = S.plan()
        second = S.plan(release=S.pinned_release(
            release_public_id="TEST-ONLY-REL-0002"))
        self.assertNotEqual(first.plan_hash(), second.plan_hash())


class TestAMismatchBlocksTheWholeRun(unittest.TestCase):
    """Requirements 13 and 14. Not the row - the run."""

    def setUp(self):
        self.plan = S.plan()

    def test_a_release_hash_mismatch_is_refused(self):
        other = S.pinned_release(release_public_id="TEST-ONLY-REL-0002")
        observation = S.internal_holdout_observations(other)[0]
        with self.assertRaises(PinMismatchError) as caught:
            verify_observation(observation, self.plan)
        self.assertEqual(caught.exception.field_name, "release_public_id")

    def test_a_case_manifest_hash_mismatch_is_refused(self):
        import dataclasses
        original = S.internal_holdout_observations()[0]
        tampered = dataclasses.replace(
            original,
            case_manifest_hash="sha256:" + "0" * 64)
        with self.assertRaises(PinMismatchError):
            verify_observation(tampered, self.plan)

    def test_one_bad_observation_refuses_every_metric(self):
        """The run raises, so no partial table is produced."""
        good = S.internal_holdout_observations()
        other = S.pinned_release(release_public_id="TEST-ONLY-REL-0002")
        bad = S.internal_holdout_observations(other)[:1]
        port = S.SyntheticObservationPort(overrides={
            Role.INTERNAL_HOLDOUT.value: tuple(good) + tuple(bad)})
        engine = BenchmarkEngine(observation_port=port)
        with self.assertRaises(PinMismatchError):
            engine.execute(S.plan(roles=(Role.INTERNAL_HOLDOUT,)), cases=[])

    def test_a_midrun_release_change_cannot_reach_a_pinned_run(self):
        """The plan holds the release; nothing re-reads a pointer.

        Mutating the resolver after planning must change nothing, because the
        run never consults it again.
        """
        resolver = S.SyntheticReleaseResolver()
        plan = BenchmarkPlan(
            plan_id="TEST-ONLY-PLAN-PIN", pinned_release=resolver.resolve(),
            roles=(Role.INTERNAL_HOLDOUT,),
            case_manifest_hashes={
                Role.INTERNAL_HOLDOUT.value:
                    S.MANIFEST_HASHES[Role.INTERNAL_HOLDOUT.value]},
            declared_metric_ids=("PGX-VAL-001",), repeat_count=2)
        before = plan.plan_hash()
        resolver._release = S.pinned_release(
            release_public_id="TEST-ONLY-REL-9999")
        engine = BenchmarkEngine(
            observation_port=S.SyntheticObservationPort(),
            judgment_port=S.SyntheticJudgmentPort())
        run = engine.execute(plan, cases=[])
        self.assertEqual(plan.plan_hash(), before)
        self.assertEqual(run.plan.pinned_release.release_public_id,
                         S.RELEASE_PUBLIC_ID)


class TestDuplicateCasesCannotInflateADenominator(unittest.TestCase):
    """Requirement 10."""

    def test_the_same_case_twice_in_one_role_is_refused(self):
        observations = S.internal_holdout_observations()
        with self.assertRaises(BenchmarkError):
            BenchmarkRun(plan=S.plan(roles=(Role.INTERNAL_HOLDOUT,)),
                         observations=observations + (observations[0],),
                         started_at=_dt.datetime(2026, 1, 1,
                                                 tzinfo=_dt.timezone.utc),
                         finished_at=_dt.datetime(2026, 1, 1,
                                                  tzinfo=_dt.timezone.utc))


class TestADirtyAuditStopsEverything(unittest.TestCase):
    """Requirement 9. Not "skip the bad partition" - compute nothing."""

    def _overlapping_cases(self):
        from tests.fixtures.wp18.synthetic import case  # WP-18's helper
        development = case("PGX-VAL-DEV-TEST-1", Role.DEVELOPMENT)
        # Same identifier, two roles: WP-18's ROLE_OVERLAP rule.
        holdout = case("PGX-VAL-DEV-TEST-1", Role.INTERNAL_HOLDOUT)
        return [development, holdout]

    def test_the_engine_refuses_before_observing_anything(self):
        class ExplodingPort(S.SyntheticObservationPort):
            def observe(self, *, role, plan):  # pragma: no cover - must not run
                raise AssertionError("observation must not be attempted after "
                                     "a dirty separation audit")

        engine = BenchmarkEngine(observation_port=ExplodingPort())
        with self.assertRaises(SeparationNotCleanError) as caught:
            engine.execute(S.plan(), cases=self._overlapping_cases())
        self.assertTrue(caught.exception.audit.issue_codes)


class TestInputOrderDoesNotChangeTheResult(unittest.TestCase):
    """Requirements 15 and 16."""

    def _run(self, observations):
        port = S.SyntheticObservationPort(overrides={
            Role.INTERNAL_HOLDOUT.value: observations})
        engine = BenchmarkEngine(observation_port=port,
                                 judgment_port=S.SyntheticJudgmentPort())
        return engine.execute(S.plan(roles=(Role.INTERNAL_HOLDOUT,)), cases=[])

    def test_reordering_observations_gives_the_same_digest(self):
        forward = S.internal_holdout_observations()
        backward = tuple(reversed(forward))
        self.assertEqual(self._run(forward).scientific_digest(),
                         self._run(backward).scientific_digest())

    def test_two_identical_runs_agree(self):
        first = self._run(S.internal_holdout_observations())
        second = self._run(S.internal_holdout_observations())
        self.assertEqual(first.scientific_digest(),
                         second.scientific_digest())

    def test_the_digest_excludes_the_clock(self):
        """Otherwise "did we get the same answer" could never be true."""
        import json
        run = self._run(S.internal_holdout_observations())
        payload = json.dumps(run.to_json())
        self.assertNotIn("started_at", payload)
        self.assertNotIn("finished_at", payload)


class TestAnObservationNamesOnlyCataloguedFailurePaths(unittest.TestCase):
    """Requirement 19, at the input boundary."""

    def test_an_unknown_path_is_refused(self):
        import dataclasses
        observation = S.internal_holdout_observations()[0]
        with self.assertRaises(BenchmarkError):
            dataclasses.replace(observation, failure_paths=("FP-999",))


class TestRepeatabilityNeedsMoreThanOneRepeat(unittest.TestCase):

    def test_a_single_repeat_reports_none_not_true(self):
        import dataclasses
        observation = dataclasses.replace(
            S.internal_holdout_observations()[0],
            output_hashes=("sha256:" + "a" * 64,))
        self.assertIsNone(observation.repeats_agree)

    def test_two_identical_repeats_agree(self):
        self.assertTrue(S.internal_holdout_observations()[0].repeats_agree)

    def test_two_differing_repeats_disagree(self):
        flaky = [item for item in S.internal_holdout_observations()
                 if item.case_id == "TEST-ONLY-IH-008"][0]
        self.assertFalse(flaky.repeats_agree)
