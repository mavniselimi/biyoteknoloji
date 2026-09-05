# -*- coding: utf-8 -*-
"""The legacy baseline is a reference, never an operational release (WP-03).

WP-01 froze the legacy MVP's dataset and rule table. WP-03 needs to be able to
point at that state - "this is what the old system had" - without any of it
becoming executable. These tests are the guarantee that pointing at it stays
harmless.

The strongest checks here are the negative ones: no legacy row is imported, the
ruleset pins nothing, and the release is refused by both activation and
rollback. A comparison baseline that could quietly become the active release
would be the single worst outcome of this work package.

Standard library only.
"""

from __future__ import annotations

import unittest

from pgx.application.legacy_baseline import (
    LEGACY_BASELINE_NOTE, LEGACY_DATASET_PUBLIC_ID, LEGACY_RELEASE_PUBLIC_ID,
    LEGACY_RULESET_PUBLIC_ID, register_legacy_baseline, wp01_manifest_hash,
)
from pgx.application.release_service import (
    ReleaseNotActivatableError, ReleaseService, RollbackNotPermittedError,
)
from pgx.domain.enums import (
    AuditAction, DatasetStatus, ReleaseStatus, RulesetStatus,
)
from pgx.domain.identifiers import ReleasePublicId

from tests.unit.application._scenario import (
    CountingEventIds, Scenario, StepClock,
    fixture_source_policy,
)

ACTOR = "ops@example.org"


class LegacyBaselineTestCase(unittest.TestCase):

    def setUp(self):
        self.scenario = Scenario()
        self.result = register_legacy_baseline(
            uow_factory=self.scenario.world.factory,
            software_version_id=self.scenario.software.id,
            actor=ACTOR, clock=StepClock(), new_event_id=CountingEventIds())
        self.store = self.scenario.world.store
        self.release = self._registered_release()

    def _registered_release(self):
        """Find the release the registration created, by its reserved public ID."""
        for release in self.store.releases.values():
            if str(release.public_id) == LEGACY_RELEASE_PUBLIC_ID:
                return release
        raise AssertionError("the legacy release was not registered")


class TestRegistration(LegacyBaselineTestCase):

    def test_it_reports_that_it_created_the_baseline(self):
        self.assertTrue(self.result.created)
        self.assertEqual(self.result.release_public_id, LEGACY_RELEASE_PUBLIC_ID)

    def test_it_records_the_wp01_manifest_hash(self):
        self.assertEqual(self.result.wp01_manifest_hash, wp01_manifest_hash())
        self.assertTrue(self.result.wp01_manifest_hash.startswith("sha256:"))

    def test_it_writes_one_audit_event(self):
        events = [event for event in self.store.audit
                  if event.action is AuditAction.LEGACY_BASELINE_REGISTERED]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].metadata["imported_legacy_rule_rows"], 0)
        self.assertIs(events[0].metadata["comparison_only"], True)
        self.assertIs(events[0].metadata["executable"], False)

    def test_the_audit_event_moves_no_pointer(self):
        event = self.store.audit[-1]
        self.assertIsNone(event.previous_release_id)
        self.assertIsNone(event.new_release_id)

    def test_registration_is_idempotent(self):
        second = register_legacy_baseline(
            uow_factory=self.scenario.world.factory,
            software_version_id=self.scenario.software.id,
            actor=ACTOR, clock=StepClock(), new_event_id=CountingEventIds())
        self.assertFalse(second.created)
        self.assertEqual(second.release_id, self.result.release_id)

    def test_a_second_run_writes_no_second_audit_event(self):
        before = len(self.store.audit)
        register_legacy_baseline(
            uow_factory=self.scenario.world.factory,
            software_version_id=self.scenario.software.id,
            actor=ACTOR, clock=StepClock(), new_event_id=CountingEventIds())
        self.assertEqual(len(self.store.audit), before)

    def test_a_second_run_creates_no_second_release(self):
        before = len(self.store.releases)
        register_legacy_baseline(
            uow_factory=self.scenario.world.factory,
            software_version_id=self.scenario.software.id,
            actor=ACTOR, clock=StepClock(), new_event_id=CountingEventIds())
        self.assertEqual(len(self.store.releases), before)

    def test_it_refuses_an_unregistered_software_build(self):
        from pgx.domain.identifiers import SoftwareVersionId

        fresh = Scenario()
        with self.assertRaises(ValueError):
            register_legacy_baseline(
                uow_factory=fresh.world.factory,
                software_version_id=SoftwareVersionId.new(), actor=ACTOR)


class TestTheBaselineIsNotOperational(LegacyBaselineTestCase):

    def test_the_release_is_retired(self):
        self.assertIs(self.release.status, ReleaseStatus.RETIRED)

    def test_the_dataset_is_retired_never_published(self):
        dataset = self.store.datasets[self.release.dataset_version_id]
        self.assertIs(dataset.status, DatasetStatus.RETIRED)
        self.assertIsNot(dataset.status, DatasetStatus.PUBLISHED)

    def test_the_ruleset_is_retired_never_frozen(self):
        ruleset = self.store.rulesets[self.release.ruleset_version_id]
        self.assertIs(ruleset.status, RulesetStatus.RETIRED)
        self.assertIsNot(ruleset.status, RulesetStatus.FROZEN)

    def test_the_ruleset_pins_no_rules(self):
        """Nothing in it can execute, because there is nothing in it."""
        ruleset = self.store.rulesets[self.release.ruleset_version_id]
        self.assertEqual(ruleset.rule_ids, ())
        self.assertEqual(ruleset.member_count, 0)

    def test_no_legacy_rule_was_imported(self):
        """The 3,084 legacy rows are not read, converted, or stored."""
        self.assertEqual(len(self.store.rules), 1)  # only the scenario fixture
        self.assertNotIn(self.release.ruleset_version_id,
                         {rule.id for rule in self.store.rules.values()})

    def test_the_limitation_is_recorded_on_the_release(self):
        self.assertEqual(self.release.notes, LEGACY_BASELINE_NOTE)
        for phrase in ("COMPARISON ONLY", "no imported legacy rows",
                       "pins no executable rules", "RETIRED"):
            self.assertIn(phrase, self.release.notes)

    def test_it_claims_no_scientific_approval(self):
        dataset = self.store.datasets[self.release.dataset_version_id]
        ruleset = self.store.rulesets[self.release.ruleset_version_id]
        self.assertIsNone(dataset.approved_by)
        self.assertIsNone(ruleset.approved_by)

    def test_it_carries_the_wp01_baseline_identity(self):
        self.assertEqual(self.release.legacy_id, "WP01-LEGACY-BASELINE-001")


class TestTheBaselineCannotBecomeActive(LegacyBaselineTestCase):
    """The refusal is enforced twice over: RETIRED, and an empty ruleset."""

    def setUp(self):
        super().setUp()
        self.service = ReleaseService(
            self.scenario.world.factory, clock=StepClock(),
            new_event_id=CountingEventIds(),
            source_policy=fixture_source_policy)

    def test_activation_is_refused(self):
        with self.assertRaises(ReleaseNotActivatableError) as caught:
            self.service.activate_release(self.release.id, ACTOR, "try it")
        codes = set(caught.exception.report.codes())
        self.assertIn("RELEASE_RETIRED", codes)

    def test_the_refusal_names_more_than_one_reason(self):
        report = self.service.validate_release(self.release.id)
        codes = set(report.codes())
        self.assertIn("RELEASE_RETIRED", codes)
        self.assertIn("RULESET_NOT_FROZEN", codes)
        self.assertIn("RULESET_MEMBERSHIP_EMPTY", codes)
        self.assertIn("DATASET_NOT_PUBLISHED", codes)

    def test_rollback_to_it_is_refused(self):
        with self.assertRaises(RollbackNotPermittedError):
            self.service.rollback_release(self.release.id, ACTOR, "try it")

    def test_a_failed_activation_leaves_the_pointer_alone(self):
        with self.assertRaises(ReleaseNotActivatableError):
            self.service.activate_release(self.release.id, ACTOR, "try it")
        self.assertIsNone(self.store.pointer.release_id)
        self.assertEqual(self.store.pointer.generation, 0)

    def test_it_does_not_become_active_even_after_a_real_activation(self):
        self.service.activate_release(
            self.scenario.release.id, ACTOR, "the real release")
        self.assertEqual(self.store.pointer.release_id, self.scenario.release.id)
        self.assertNotEqual(self.store.pointer.release_id, self.release.id)


class TestTheWp01ManifestIsOnlyRead(unittest.TestCase):

    def test_the_hash_is_stable_across_calls(self):
        self.assertEqual(wp01_manifest_hash(), wp01_manifest_hash())

    def test_the_module_never_writes_to_the_baseline(self):
        import ast
        import inspect

        from pgx.application import legacy_baseline

        tree = ast.parse(inspect.getsource(legacy_baseline))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                self.assertNotIn(name, ("dump", "dumps_to_file", "write", "unlink",
                                        "remove", "rename", "rmtree"))
        source = inspect.getsource(legacy_baseline)
        self.assertNotIn('"w"', source)
        self.assertNotIn("'w'", source)

    def test_the_public_ids_are_reserved_and_distinct(self):
        ids = {LEGACY_DATASET_PUBLIC_ID, LEGACY_RULESET_PUBLIC_ID,
               LEGACY_RELEASE_PUBLIC_ID}
        self.assertEqual(len(ids), 3)
        self.assertTrue(all(value.endswith("-999") for value in ids),
                        "the -999 sequence is reserved for the legacy baseline")

    def test_the_release_public_id_is_well_formed(self):
        ReleasePublicId(LEGACY_RELEASE_PUBLIC_ID)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
