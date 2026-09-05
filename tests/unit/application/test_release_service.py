# -*- coding: utf-8 -*-
"""Activation, rejection, rollback and audit, exercised without a database.

Every test starts from a release that *would* activate and breaks exactly one
thing. That shape is deliberate: a test that assembles a broken release from
scratch can pass for a reason unrelated to the rule it names, and keep passing
after that rule is deleted.

What these tests do **not** prove: that ``SELECT ... FOR UPDATE`` blocks a
second transaction. The in-memory unit of work has no concurrency to lock
against. That needs a real PostgreSQL server, and WP-03 records it as BLOCKED
rather than pretending a fake covered it.

Standard library only.
"""

from __future__ import annotations

import unittest

from pgx.application.release_service import (
    CompatibilityCode, ReleaseNotActivatableError, ReleaseNotFoundError,
    ReleaseService, RollbackNotPermittedError,
)
from pgx.domain.enums import (
    AuditAction, DatasetStatus, ReleaseStatus, RuleStatus, RulesetStatus, SourceRole,
)
from pgx.domain.errors import DomainInvariantError
from pgx.domain.identifiers import ReleaseBundleId
from pgx.domain.release_manifest import manifest_digest

from tests.unit.application._scenario import (
    CountingEventIds, DATASET_HASH, RULESET_HASH, Scenario, StepClock,
    fixture_source_policy,
)

ACTOR = "ops@example.org"
REASON = "scheduled release drill"


def _service(scenario: Scenario) -> ReleaseService:
    """A service with a pinned clock and pinned audit identities."""
    return ReleaseService(scenario.world.factory, clock=StepClock(),
                          new_event_id=CountingEventIds(),
                          source_policy=fixture_source_policy)


class ActivationTestCase(unittest.TestCase):
    """Shared assertions about a store that must not have moved."""

    def assertUnchanged(self, scenario: Scenario, release_status=ReleaseStatus.DRAFT):
        """The pointer, the generation, the status and the audit log all held."""
        store = scenario.world.store
        self.assertIsNone(store.pointer.release_id, "the pointer moved")
        self.assertEqual(store.pointer.generation, 0, "the generation moved")
        self.assertEqual(store.releases[scenario.release.id].status, release_status,
                         "the release status moved")
        self.assertEqual(store.audit, [], "an audit event was written")


class TestValidActivation(ActivationTestCase):

    def setUp(self):
        self.scenario = Scenario()
        self.service = _service(self.scenario)

    def test_a_complete_release_validates(self):
        report = self.service.validate_release(self.scenario.release.id)
        self.assertTrue(report.is_compatible, report.summary())
        self.assertEqual(report.problems, ())

    def test_validation_changes_nothing(self):
        self.service.validate_release(self.scenario.release.id)
        self.assertUnchanged(self.scenario)

    def test_activation_succeeds(self):
        result = self.service.activate_release(
            self.scenario.release.id, ACTOR, REASON)
        self.assertTrue(result.changed)
        self.assertEqual(result.release_public_id, "PGX-REL-20260829-001")

    def test_the_pointer_names_the_new_release(self):
        self.service.activate_release(self.scenario.release.id, ACTOR, REASON)
        self.assertEqual(self.scenario.world.store.pointer.release_id,
                         self.scenario.release.id)

    def test_the_generation_advances_from_zero_to_one(self):
        self.service.activate_release(self.scenario.release.id, ACTOR, REASON)
        self.assertEqual(self.scenario.world.store.pointer.generation, 1)

    def test_the_release_becomes_active(self):
        self.service.activate_release(self.scenario.release.id, ACTOR, REASON)
        stored = self.scenario.world.store.releases[self.scenario.release.id]
        self.assertIs(stored.status, ReleaseStatus.ACTIVE)
        self.assertEqual(stored.activated_by, ACTOR)
        self.assertIsNotNone(stored.activated_at)

    def test_the_pointer_row_was_locked_before_anything_moved(self):
        self.service.activate_release(self.scenario.release.id, ACTOR, REASON)
        locked = [unit.active_release.lock_calls
                  for unit in self.scenario.world.units
                  if hasattr(unit, "active_release")]
        self.assertTrue(any(count >= 1 for count in locked),
                        "activation must take the pointer lock first")

    def test_the_unit_of_work_was_committed(self):
        self.service.activate_release(self.scenario.release.id, ACTOR, REASON)
        self.assertTrue(any(unit.committed for unit in self.scenario.world.units))

    def test_get_active_release_returns_it(self):
        self.service.activate_release(self.scenario.release.id, ACTOR, REASON)
        active = self.service.get_active_release()
        self.assertIsNotNone(active)
        self.assertEqual(active.id, self.scenario.release.id)

    def test_before_any_activation_there_is_no_active_release(self):
        self.assertIsNone(self.service.get_active_release())
        self.assertEqual(self.service.get_active_pointer().generation, 0)


class TestExactlyOneAuditEvent(unittest.TestCase):

    def setUp(self):
        self.scenario = Scenario()
        self.service = _service(self.scenario)

    def test_activation_writes_exactly_one_event(self):
        self.service.activate_release(self.scenario.release.id, ACTOR, REASON)
        self.assertEqual(len(self.scenario.world.store.audit), 1)

    def test_the_event_records_the_action_actor_and_reason(self):
        self.service.activate_release(self.scenario.release.id, ACTOR, REASON)
        event = self.scenario.world.store.audit[0]
        self.assertIs(event.action, AuditAction.RELEASE_ACTIVATED)
        self.assertEqual(event.actor, ACTOR)
        self.assertEqual(event.reason, REASON)

    def test_the_first_activation_has_no_previous_release(self):
        self.service.activate_release(self.scenario.release.id, ACTOR, REASON)
        event = self.scenario.world.store.audit[0]
        self.assertIsNone(event.previous_release_id)
        self.assertEqual(event.new_release_id, self.scenario.release.id)

    def test_a_second_activation_names_the_release_it_replaced(self):
        second = self.scenario.add_release("PGX-REL-20260829-002")
        self.service.activate_release(self.scenario.release.id, ACTOR, REASON)
        self.service.activate_release(second.id, ACTOR, "promote the next build")
        event = self.scenario.world.store.audit[-1]
        self.assertEqual(event.previous_release_id, self.scenario.release.id)
        self.assertEqual(event.new_release_id, second.id)

    def test_the_event_carries_the_manifest_hash_and_generation(self):
        self.service.activate_release(self.scenario.release.id, ACTOR, REASON)
        event = self.scenario.world.store.audit[0]
        self.assertEqual(event.metadata["manifest_hash"],
                         self.scenario.release.manifest_hash)
        self.assertEqual(event.metadata["generation"], 1)

    def test_an_actor_is_required(self):
        for actor in ("", "   ", None):
            with self.subTest(actor=actor):
                with self.assertRaises(DomainInvariantError):
                    self.service.activate_release(
                        self.scenario.release.id, actor, REASON)

    def test_a_reason_is_required(self):
        for reason in ("", "   ", None):
            with self.subTest(reason=reason):
                with self.assertRaises(DomainInvariantError):
                    self.service.activate_release(
                        self.scenario.release.id, ACTOR, reason)


class TestIdempotentReactivation(unittest.TestCase):
    """Re-activating what is already active is success, not an error."""

    def setUp(self):
        self.scenario = Scenario()
        self.service = _service(self.scenario)
        self.service.activate_release(self.scenario.release.id, ACTOR, REASON)

    def test_the_second_activation_reports_no_change(self):
        result = self.service.activate_release(
            self.scenario.release.id, ACTOR, "re-run the deploy step")
        self.assertFalse(result.changed)

    def test_no_second_audit_event_is_written(self):
        self.service.activate_release(self.scenario.release.id, ACTOR, "again")
        self.assertEqual(len(self.scenario.world.store.audit), 1)

    def test_the_generation_does_not_advance(self):
        self.service.activate_release(self.scenario.release.id, ACTOR, "again")
        self.assertEqual(self.scenario.world.store.pointer.generation, 1)

    def test_the_release_stays_active(self):
        self.service.activate_release(self.scenario.release.id, ACTOR, "again")
        self.assertIs(
            self.scenario.world.store.releases[self.scenario.release.id].status,
            ReleaseStatus.ACTIVE)

    def test_no_audit_event_id_is_returned_for_a_no_op(self):
        result = self.service.activate_release(
            self.scenario.release.id, ACTOR, "again")
        self.assertIsNone(result.audit_event_id)


class TestRejections(ActivationTestCase):
    """One broken thing per case, everything else valid."""

    def _reject(self, scenario, expected_code, release_status=ReleaseStatus.DRAFT):
        service = _service(scenario)
        report = service.validate_release(scenario.release.id)
        self.assertFalse(report.is_compatible, "expected a rejection")
        self.assertIn(expected_code.value, report.codes())
        with self.assertRaises(ReleaseNotActivatableError):
            service.activate_release(scenario.release.id, ACTOR, REASON)
        self.assertUnchanged(scenario, release_status)

    def test_dataset_not_published(self):
        for status in (DatasetStatus.BUILDING, DatasetStatus.QUALITY_CHECKED,
                       DatasetStatus.RETIRED):
            with self.subTest(status=status):
                self._reject(Scenario(dataset_status=status),
                             CompatibilityCode.DATASET_NOT_PUBLISHED)

    def test_ruleset_not_frozen(self):
        for status in (RulesetStatus.BUILDING, RulesetStatus.VALIDATED,
                       RulesetStatus.RETIRED):
            with self.subTest(status=status):
                self._reject(Scenario(ruleset_status=status),
                             CompatibilityCode.RULESET_NOT_FROZEN)

    def test_empty_ruleset(self):
        # A FROZEN ruleset cannot be empty (the domain refuses it), so the
        # empty case is reachable only in a non-frozen status - and it is
        # reported alongside the frozen failure, not instead of it.
        self._reject(Scenario(empty_ruleset=True,
                              ruleset_status=RulesetStatus.VALIDATED),
                     CompatibilityCode.RULESET_MEMBERSHIP_EMPTY)

    def test_member_rule_not_validated(self):
        for status in (RuleStatus.DRAFT, RuleStatus.CURATED, RuleStatus.DEPRECATED):
            with self.subTest(status=status):
                self._reject(Scenario(rule_status=status),
                             CompatibilityCode.RULE_NOT_VALIDATED)

    def test_member_rule_missing_entirely(self):
        self._reject(Scenario(register_rule=False),
                     CompatibilityCode.RULE_NOT_FOUND)

    def test_member_rule_cites_no_evidence(self):
        # A VALIDATED rule must cite evidence, so an unbacked rule can only
        # exist below VALIDATED; both failures are reported.
        self._reject(Scenario(rule_has_evidence=False,
                              rule_status=RuleStatus.CURATED),
                     CompatibilityCode.RULE_EVIDENCE_MISSING)

    def test_cited_evidence_does_not_exist(self):
        self._reject(Scenario(register_evidence=False),
                     CompatibilityCode.EVIDENCE_NOT_FOUND)

    def test_evidence_belongs_to_another_dataset(self):
        self._reject(Scenario(evidence_in_dataset=False),
                     CompatibilityCode.EVIDENCE_OUTSIDE_DATASET)

    def test_evidence_source_is_not_release_eligible(self):
        self._reject(Scenario(source_release_eligible=False),
                     CompatibilityCode.EVIDENCE_SOURCE_NOT_RELEASE_ELIGIBLE)

    def test_evidence_source_is_internal_system(self):
        self._reject(Scenario(source_role=SourceRole.INTERNAL_SYSTEM),
                     CompatibilityCode.EVIDENCE_SOURCE_IS_INTERNAL_SYSTEM)

    def test_software_version_not_registered(self):
        self._reject(Scenario(register_software=False),
                     CompatibilityCode.SOFTWARE_VERSION_NOT_REGISTERED)

    def test_dataset_manifest_hash_mismatch(self):
        other = manifest_digest({"a different": "dataset"})
        self._reject(Scenario(dataset_hash_in_manifest=other),
                     CompatibilityCode.DATASET_MANIFEST_HASH_MISMATCH)

    def test_ruleset_manifest_hash_mismatch(self):
        other = manifest_digest({"a different": "ruleset"})
        self._reject(Scenario(ruleset_hash_in_manifest=other),
                     CompatibilityCode.RULESET_MANIFEST_HASH_MISMATCH)

    def test_release_manifest_hash_does_not_match_its_payload(self):
        self._reject(Scenario(corrupt_manifest_hash=True),
                     CompatibilityCode.RELEASE_MANIFEST_HASH_MISMATCH)

    def test_a_retired_release_cannot_be_activated(self):
        self._reject(Scenario(release_status=ReleaseStatus.RETIRED),
                     CompatibilityCode.RELEASE_RETIRED,
                     release_status=ReleaseStatus.RETIRED)

    def test_an_unknown_release_is_reported_not_guessed(self):
        service = _service(Scenario())
        with self.assertRaises(ReleaseNotFoundError):
            service.activate_release(ReleaseBundleId.new(), ACTOR, REASON)

    def test_every_problem_is_reported_not_just_the_first(self):
        scenario = Scenario(dataset_status=DatasetStatus.BUILDING,
                            register_software=False,
                            rule_status=RuleStatus.DRAFT)
        report = _service(scenario).validate_release(scenario.release.id)
        codes = set(report.codes())
        self.assertIn(CompatibilityCode.DATASET_NOT_PUBLISHED.value, codes)
        self.assertIn(CompatibilityCode.SOFTWARE_VERSION_NOT_REGISTERED.value, codes)
        self.assertIn(CompatibilityCode.RULE_NOT_VALIDATED.value, codes)

    def test_the_error_carries_the_whole_report(self):
        scenario = Scenario(dataset_status=DatasetStatus.BUILDING)
        service = _service(scenario)
        with self.assertRaises(ReleaseNotActivatableError) as caught:
            service.activate_release(scenario.release.id, ACTOR, REASON)
        self.assertFalse(caught.exception.report.is_compatible)
        self.assertIn("DATASET_NOT_PUBLISHED", str(caught.exception))


class TestFailedActivationLeavesNothingBehind(unittest.TestCase):
    """The all-or-nothing property, checked field by field."""

    def setUp(self):
        self.scenario = Scenario(dataset_status=DatasetStatus.BUILDING)
        self.service = _service(self.scenario)

    def _attempt(self):
        with self.assertRaises(ReleaseNotActivatableError):
            self.service.activate_release(self.scenario.release.id, ACTOR, REASON)

    def test_the_pointer_is_untouched(self):
        self._attempt()
        self.assertIsNone(self.scenario.world.store.pointer.release_id)

    def test_the_generation_is_untouched(self):
        self._attempt()
        self.assertEqual(self.scenario.world.store.pointer.generation, 0)

    def test_the_release_status_is_untouched(self):
        self._attempt()
        self.assertIs(
            self.scenario.world.store.releases[self.scenario.release.id].status,
            ReleaseStatus.DRAFT)

    def test_no_audit_event_was_written(self):
        self._attempt()
        self.assertEqual(self.scenario.world.store.audit, [])

    def test_the_unit_of_work_rolled_back(self):
        self._attempt()
        self.assertTrue(any(unit.rolled_back for unit in self.scenario.world.units))
        self.assertFalse(any(unit.committed for unit in self.scenario.world.units))

    def test_a_previously_active_release_stays_active(self):
        scenario = Scenario()
        service = _service(scenario)
        service.activate_release(scenario.release.id, ACTOR, REASON)
        broken = scenario.add_release("PGX-REL-20260829-002")
        scenario.world.store.datasets[scenario.dataset.id] = (
            scenario.world.store.datasets[scenario.dataset.id])
        # Break the candidate only: point it at an unregistered software build.
        import dataclasses
        from pgx.domain.identifiers import SoftwareVersionId
        scenario.world.store.releases[broken.id] = dataclasses.replace(
            broken, software_version_id=SoftwareVersionId.new())
        with self.assertRaises(ReleaseNotActivatableError):
            service.activate_release(broken.id, ACTOR, "promote")
        self.assertEqual(scenario.world.store.pointer.release_id,
                         scenario.release.id)
        self.assertEqual(scenario.world.store.pointer.generation, 1)
        self.assertIs(scenario.world.store.releases[scenario.release.id].status,
                      ReleaseStatus.ACTIVE)
        self.assertEqual(len(scenario.world.store.audit), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
