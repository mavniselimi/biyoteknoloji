# -*- coding: utf-8 -*-
"""The WP-05 gate inside release activation.

The rule WP-05 adds to the release registry, in one sentence: **a database flag
is not an approval.** ``source_registry.release_eligible`` is a boolean somebody
can set; it says nothing about whether a human has read the source's terms. The
four rules below make it insufficient on its own.

Every fixture here uses the synthetic ``fixture-source`` and the shouted
``TEST_SCIENTIFIC_REVIEWER`` identity, and none of them touches
``config/scientific-sources.json`` - which stays entirely unapproved, and which
a companion test in ``tests/unit/scientific`` checks.
"""

from __future__ import annotations

import unittest

from pgx.application.release_service import (
    CompatibilityCode,
    ReleaseNotActivatableError,
    ReleaseService,
)
from pgx.scientific.conflict import SourceStatement, detect_conflicts
from pgx.scientific.errors import SourcePolicyConfigError
from pgx.scientific.models import ClaimCategory, ReuseDimension, ReuseMatrix, ReusePermission
from pgx.scientific.policy import SourcePolicyRegistry

from tests.unit.application._scenario import (
    CountingEventIds, FIXTURE_SOURCE_KEY, Scenario, StepClock,
    fixture_source_policy,
)
from tests.unit.scientific import _fixtures as fx

ACTOR = "ops@example.org"
REASON = "source policy gate drill"


def _service(scenario, source_policy):
    return ReleaseService(scenario.world.factory, clock=StepClock(),
                          new_event_id=CountingEventIds(),
                          source_policy=source_policy)


def _codes(scenario, source_policy):
    service = _service(scenario, source_policy)
    return set(service.validate_release(scenario.release.id).codes())


class TestTheGateIsPartOfTheContract(unittest.TestCase):

    def test_the_new_codes_exist_and_are_stable_strings(self):
        for name in ("SOURCE_POLICY_UNAVAILABLE",
                     "EVIDENCE_SOURCE_POLICY_MISSING",
                     "EVIDENCE_SOURCE_POLICY_NOT_APPROVED",
                     "EVIDENCE_SOURCE_POLICY_INCOMPLETE",
                     "SOURCE_CONFLICT_UNRESOLVED"):
            with self.subTest(code=name):
                self.assertEqual(getattr(CompatibilityCode, name).value, name)

    def test_the_release_eligible_flag_is_still_checked_too(self):
        """WP-05 adds to the WP-03 rule; it does not replace it."""
        scenario = Scenario(source_release_eligible=False)
        self.assertIn(
            CompatibilityCode.EVIDENCE_SOURCE_NOT_RELEASE_ELIGIBLE.value,
            _codes(scenario, fixture_source_policy))


class TestReleaseEligibleAloneIsNotEnough(unittest.TestCase):

    def setUp(self):
        self.scenario = Scenario()

    def test_a_release_eligible_source_with_no_policy_is_refused(self):
        """The exact hole WP-05 closes."""
        self.assertTrue(self.scenario.source.release_eligible)
        codes = _codes(self.scenario, lambda: SourcePolicyRegistry(records=()))
        self.assertIn(CompatibilityCode.EVIDENCE_SOURCE_POLICY_MISSING.value,
                      codes)

    def test_activation_is_refused_outright(self):
        service = _service(self.scenario, lambda: SourcePolicyRegistry(records=()))
        with self.assertRaises(ReleaseNotActivatableError):
            service.activate_release(self.scenario.release.id, ACTOR, REASON)

    def test_a_registered_but_unreviewed_source_is_refused(self):
        registry = SourcePolicyRegistry(
            records=(fx.pending_source(source_key=FIXTURE_SOURCE_KEY),))
        codes = _codes(self.scenario, lambda: registry)
        self.assertIn(
            CompatibilityCode.EVIDENCE_SOURCE_POLICY_NOT_APPROVED.value, codes)

    def test_an_approved_but_incomplete_policy_is_refused(self):
        """Approved, and one reuse question never answered."""
        partial = fx.approved_source(
            source_key=FIXTURE_SOURCE_KEY,
            reuse=ReuseMatrix({ReuseDimension.LOCAL_STORAGE:
                               ReusePermission.ALLOWED}))
        registry = SourcePolicyRegistry(records=(partial,))
        codes = _codes(self.scenario, lambda: registry)
        self.assertIn(
            CompatibilityCode.EVIDENCE_SOURCE_POLICY_INCOMPLETE.value, codes)

    def test_a_complete_approved_policy_lets_the_release_validate(self):
        report = _service(self.scenario, fixture_source_policy).validate_release(
            self.scenario.release.id)
        self.assertTrue(report.is_compatible, report.problems)


class TestAPolicyThatWillNotLoadBlocks(unittest.TestCase):
    """"The file would not open" and "nothing is restricted" must differ."""

    def setUp(self):
        self.scenario = Scenario()

    def test_a_load_failure_blocks_rather_than_being_skipped(self):
        def _explode():
            raise SourcePolicyConfigError("fixture: the registry did not load")

        codes = _codes(self.scenario, _explode)
        self.assertIn(CompatibilityCode.SOURCE_POLICY_UNAVAILABLE.value, codes)

    def test_no_configured_policy_blocks(self):
        codes = _codes(self.scenario, lambda: None)
        self.assertIn(CompatibilityCode.SOURCE_POLICY_UNAVAILABLE.value, codes)

    def test_the_problem_detail_names_the_underlying_failure(self):
        def _explode():
            raise SourcePolicyConfigError("fixture: the registry did not load")

        report = _service(self.scenario, _explode).validate_release(
            self.scenario.release.id)
        detail = " ".join(p.detail for p in report.problems)
        self.assertIn("fixture: the registry did not load", detail)


class TestAnUnresolvedConflictBlocksActivation(unittest.TestCase):

    def setUp(self):
        self.scenario = Scenario()
        approved = fx.approved_source(source_key=FIXTURE_SOURCE_KEY)
        other = fx.approved_source(source_key="fixture.other")
        conflicts = detect_conflicts((
            SourceStatement("CYP2C19:fixture-drug", FIXTURE_SOURCE_KEY, "A"),
            SourceStatement("CYP2C19:fixture-drug", "fixture.other", "B")))
        self.registry = SourcePolicyRegistry(records=(approved, other),
                                             conflicts=conflicts)

    def test_the_release_is_refused(self):
        codes = _codes(self.scenario, lambda: self.registry)
        self.assertIn(CompatibilityCode.SOURCE_CONFLICT_UNRESOLVED.value, codes)

    def test_a_conflict_between_other_sources_does_not_block(self):
        approved = fx.approved_source(source_key=FIXTURE_SOURCE_KEY)
        third = fx.approved_source(source_key="fixture.third")
        fourth = fx.approved_source(source_key="fixture.fourth")
        conflicts = detect_conflicts((
            SourceStatement("elsewhere", "fixture.third", "A"),
            SourceStatement("elsewhere", "fixture.fourth", "B")))
        registry = SourcePolicyRegistry(records=(approved, third, fourth),
                                        conflicts=conflicts)
        report = _service(self.scenario, lambda: registry).validate_release(
            self.scenario.release.id)
        self.assertTrue(report.is_compatible, report.problems)


class TestTheGateReportsOncePerSourceNotPerEvidenceRecord(unittest.TestCase):

    def test_one_unreviewed_source_produces_one_finding(self):
        scenario = Scenario()
        registry = SourcePolicyRegistry(
            records=(fx.pending_source(source_key=FIXTURE_SOURCE_KEY),))
        report = _service(scenario, lambda: registry).validate_release(
            scenario.release.id)
        matching = [p for p in report.problems
                    if p.code is CompatibilityCode
                    .EVIDENCE_SOURCE_POLICY_NOT_APPROVED]
        self.assertEqual(len(matching), 1)


class TestTheServiceStillNeedsNoDatabaseOrRegistryFile(unittest.TestCase):

    def test_it_can_be_constructed_with_neither(self):
        self.assertIsNotNone(ReleaseService(lambda: None,
                                            source_policy=lambda: None))

    def test_the_default_policy_provider_is_the_reviewed_file_loader(self):
        from pgx.scientific.policy import load_registry
        import inspect
        signature = inspect.signature(ReleaseService.__init__)
        self.assertIs(signature.parameters["source_policy"].default,
                      load_registry)


class TestAClaimCategoryIsNotGrantedByTheGate(unittest.TestCase):
    """The release gate checks approval; it never widens one."""

    def test_the_fixture_policy_grants_exactly_one_category(self):
        registry = fixture_source_policy()
        record = registry.require(FIXTURE_SOURCE_KEY)
        self.assertEqual(record.permitted_claim_categories,
                         (ClaimCategory.PRIMARY_GUIDELINE_RECOMMENDATION,))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
