# -*- coding: utf-8 -*-
"""Rollback: returning to a release that was previously in force (WP-03).

Rollback is deliberately narrower than activation, and the tests here are
mostly about what it *refuses*. A "rollback" that can reach a release which
never ran is an activation wearing the wrong name, and it would let an operator
reach a never-validated release through a path with softer expectations.

The property the whole work package exists for is at the bottom: an assessment
records the exact release it ran under, and rolling the active pointer back
does not change that record. History is not rewritten.

Standard library only.
"""

from __future__ import annotations

import dataclasses
import unittest

from pgx.application.release_service import (
    ReleaseNotActivatableError, ReleaseService, RollbackNotPermittedError,
)
from pgx.domain.claims import OperationMode
from pgx.domain.enums import AuditAction, DatasetStatus, ReleaseStatus
from pgx.domain.identifiers import AssessmentId, ReleaseBundleId
from pgx.domain.models import Assessment

from tests.unit.application._scenario import (
    CountingEventIds, NOW, Scenario, StepClock,
    fixture_source_policy,
)

ACTOR = "ops@example.org"
REASON = "regression found in the newer release"


def _service(scenario: Scenario) -> ReleaseService:
    return ReleaseService(scenario.world.factory, clock=StepClock(),
                          new_event_id=CountingEventIds(),
                          source_policy=fixture_source_policy)


class RollbackTestCase(unittest.TestCase):
    """Two releases; the first is activated, then the second."""

    def setUp(self):
        self.scenario = Scenario()
        self.service = _service(self.scenario)
        self.first = self.scenario.release
        self.second = self.scenario.add_release("PGX-REL-20260829-002")
        self.service.activate_release(self.first.id, ACTOR, "initial release")
        self.service.activate_release(self.second.id, ACTOR, "promote the next build")

    @property
    def store(self):
        return self.scenario.world.store


class TestRollbackRestoresThePreviousRelease(RollbackTestCase):

    def test_the_pointer_returns_to_the_first_release(self):
        self.service.rollback_release(self.first.id, ACTOR, REASON)
        self.assertEqual(self.store.pointer.release_id, self.first.id)

    def test_the_generation_advances_rather_than_rewinding(self):
        """Rollback is a new event in history, not an undo of an old one."""
        before = self.store.pointer.generation
        self.service.rollback_release(self.first.id, ACTOR, REASON)
        self.assertEqual(self.store.pointer.generation, before + 1)

    def test_the_target_becomes_active_again(self):
        self.service.rollback_release(self.first.id, ACTOR, REASON)
        self.assertIs(self.store.releases[self.first.id].status, ReleaseStatus.ACTIVE)

    def test_the_release_being_left_becomes_rolled_back(self):
        self.service.rollback_release(self.first.id, ACTOR, REASON)
        self.assertIs(self.store.releases[self.second.id].status,
                      ReleaseStatus.ROLLED_BACK)

    def test_one_audit_event_naming_both_sides(self):
        before = len(self.store.audit)
        self.service.rollback_release(self.first.id, ACTOR, REASON)
        self.assertEqual(len(self.store.audit), before + 1)
        event = self.store.audit[-1]
        self.assertIs(event.action, AuditAction.RELEASE_ROLLED_BACK)
        self.assertEqual(event.previous_release_id, self.second.id)
        self.assertEqual(event.new_release_id, self.first.id)
        self.assertEqual(event.reason, REASON)

    def test_the_result_reports_the_change(self):
        result = self.service.rollback_release(self.first.id, ACTOR, REASON)
        self.assertTrue(result.changed)
        self.assertEqual(result.action, "rollback")
        self.assertEqual(result.previous_release_id, self.second.id.to_json())

    def test_rolling_forward_again_is_permitted(self):
        """The second release was active once, so it is a legitimate target."""
        self.service.rollback_release(self.first.id, ACTOR, REASON)
        self.service.rollback_release(self.second.id, ACTOR, "fix shipped")
        self.assertEqual(self.store.pointer.release_id, self.second.id)


class TestRollbackRefusals(RollbackTestCase):

    def test_a_release_that_was_never_active_is_refused(self):
        never = self.scenario.add_release("PGX-REL-20260829-003")
        with self.assertRaises(RollbackNotPermittedError) as caught:
            self.service.rollback_release(never.id, ACTOR, REASON)
        self.assertIn("never been activated", str(caught.exception))

    def test_a_retired_release_is_refused(self):
        self.store.releases[self.first.id] = dataclasses.replace(
            self.store.releases[self.first.id], status=ReleaseStatus.RETIRED)
        with self.assertRaises(RollbackNotPermittedError) as caught:
            self.service.rollback_release(self.first.id, ACTOR, REASON)
        self.assertIn("RETIRED", str(caught.exception))

    def test_rolling_back_to_the_current_release_is_refused(self):
        with self.assertRaises(RollbackNotPermittedError) as caught:
            self.service.rollback_release(self.second.id, ACTOR, REASON)
        self.assertIn("already the active release", str(caught.exception))

    def test_an_unknown_release_is_refused(self):
        from pgx.application.release_service import ReleaseNotFoundError
        with self.assertRaises(ReleaseNotFoundError):
            self.service.rollback_release(ReleaseBundleId.new(), ACTOR, REASON)

    def test_a_target_that_no_longer_passes_the_rules_is_refused(self):
        """Valid a month ago is not valid now: the checks run again in full."""
        self.store.datasets[self.scenario.dataset.id] = dataclasses.replace(
            self.store.datasets[self.scenario.dataset.id],
            status=DatasetStatus.RETIRED, approved_by=None, approved_at=None)
        with self.assertRaises(ReleaseNotActivatableError):
            self.service.rollback_release(self.first.id, ACTOR, REASON)

    def test_an_actor_and_a_reason_are_required(self):
        from pgx.domain.errors import DomainInvariantError
        with self.assertRaises(DomainInvariantError):
            self.service.rollback_release(self.first.id, "", REASON)
        with self.assertRaises(DomainInvariantError):
            self.service.rollback_release(self.first.id, ACTOR, "")


class TestFailedRollbackLeavesNothingBehind(RollbackTestCase):

    def setUp(self):
        super().setUp()
        self.pointer_before = self.store.pointer
        self.audit_before = list(self.store.audit)
        self.statuses_before = {
            release_id: release.status
            for release_id, release in self.store.releases.items()}

    def _assert_frozen(self):
        self.assertEqual(self.store.pointer.release_id,
                         self.pointer_before.release_id)
        self.assertEqual(self.store.pointer.generation,
                         self.pointer_before.generation)
        self.assertEqual(len(self.store.audit), len(self.audit_before))
        for release_id, status in self.statuses_before.items():
            self.assertIs(self.store.releases[release_id].status, status)

    def test_a_never_activated_target_changes_nothing(self):
        never = self.scenario.add_release("PGX-REL-20260829-003")
        self.statuses_before[never.id] = never.status
        with self.assertRaises(RollbackNotPermittedError):
            self.service.rollback_release(never.id, ACTOR, REASON)
        self._assert_frozen()

    def test_an_incompatible_target_changes_nothing(self):
        self.store.datasets[self.scenario.dataset.id] = dataclasses.replace(
            self.store.datasets[self.scenario.dataset.id],
            status=DatasetStatus.RETIRED, approved_by=None, approved_at=None)
        with self.assertRaises(ReleaseNotActivatableError):
            self.service.rollback_release(self.first.id, ACTOR, REASON)
        self._assert_frozen()


class TestImmutableArtifactsSurviveRollback(RollbackTestCase):
    """Rollback moves a pointer. It rewrites nothing."""

    def test_the_dataset_is_untouched(self):
        before = self.store.datasets[self.scenario.dataset.id]
        self.service.rollback_release(self.first.id, ACTOR, REASON)
        self.assertEqual(self.store.datasets[self.scenario.dataset.id], before)

    def test_the_ruleset_and_its_membership_are_untouched(self):
        before = self.store.rulesets[self.scenario.ruleset.id]
        self.service.rollback_release(self.first.id, ACTOR, REASON)
        after = self.store.rulesets[self.scenario.ruleset.id]
        self.assertEqual(after, before)
        self.assertEqual(after.rule_ids, before.rule_ids)

    def test_the_rules_are_untouched(self):
        before = dict(self.store.rules)
        self.service.rollback_release(self.first.id, ACTOR, REASON)
        self.assertEqual(self.store.rules, before)

    def test_the_software_build_is_untouched(self):
        before = dict(self.store.software)
        self.service.rollback_release(self.first.id, ACTOR, REASON)
        self.assertEqual(self.store.software, before)

    def test_both_manifests_and_their_hashes_are_untouched(self):
        before = {release_id: (release.manifest, release.manifest_hash)
                  for release_id, release in self.store.releases.items()}
        self.service.rollback_release(self.first.id, ACTOR, REASON)
        for release_id, (manifest, digest) in before.items():
            self.assertEqual(self.store.releases[release_id].manifest, manifest)
            self.assertEqual(self.store.releases[release_id].manifest_hash, digest)

    def test_earlier_audit_events_are_not_rewritten(self):
        before = list(self.store.audit)
        self.service.rollback_release(self.first.id, ACTOR, REASON)
        self.assertEqual(self.store.audit[:len(before)], before)

    def test_the_audit_repository_offers_no_update_or_delete(self):
        """Append-only is enforced by absence, not by convention."""
        with self.scenario.world.factory() as unit:
            for forbidden in ("update", "delete", "remove", "edit", "purge"):
                self.assertFalse(hasattr(unit.audit, forbidden),
                                 "audit repository must not expose %s" % forbidden)


class TestAssessmentKeepsItsExactReleaseId(RollbackTestCase):
    """The point of the whole work package.

    An assessment names the release it ran under. Moving the active pointer
    afterwards - forward or back - must not change what that assessment says it
    used, or the record stops being reproducible.
    """

    def _assessment(self, release_id):
        return Assessment(
            id=AssessmentId.new(), release_bundle_id=release_id,
            mode=OperationMode.DEMO,
            input_hash="sha256:" + "a" * 64, created_at=NOW)

    def test_the_release_id_survives_a_rollback(self):
        assessment = self._assessment(self.second.id)
        self.service.rollback_release(self.first.id, ACTOR, REASON)
        self.assertEqual(assessment.release_bundle_id, self.second.id)

    def test_it_still_names_a_release_that_is_no_longer_active(self):
        assessment = self._assessment(self.second.id)
        self.service.rollback_release(self.first.id, ACTOR, REASON)
        self.assertNotEqual(self.store.pointer.release_id,
                            assessment.release_bundle_id)
        self.assertIsNotNone(self.store.releases[assessment.release_bundle_id])

    def test_the_release_it_names_keeps_its_manifest_and_hash(self):
        assessment = self._assessment(self.second.id)
        before = self.store.releases[self.second.id]
        self.service.rollback_release(self.first.id, ACTOR, REASON)
        after = self.store.releases[assessment.release_bundle_id]
        self.assertEqual(after.manifest_hash, before.manifest_hash)
        self.assertEqual(after.manifest, before.manifest)
        self.assertEqual(after.software_version_id, before.software_version_id)
        self.assertEqual(after.dataset_version_id, before.dataset_version_id)
        self.assertEqual(after.ruleset_version_id, before.ruleset_version_id)

    def test_an_assessment_cannot_exist_without_a_release(self):
        from pgx.domain.errors import IdentifierTypeMismatchError
        with self.assertRaises((IdentifierTypeMismatchError, TypeError)):
            Assessment(id=AssessmentId.new(), release_bundle_id=None,
                       mode=OperationMode.DEMO,
                       input_hash="sha256:" + "a" * 64, created_at=NOW)


class TestReleaseHistory(RollbackTestCase):

    def test_history_returns_events_newest_first(self):
        self.service.rollback_release(self.first.id, ACTOR, REASON)
        events = self.service.release_history()
        self.assertEqual(len(events), 3)
        self.assertIs(events[0].action, AuditAction.RELEASE_ROLLED_BACK)

    def test_history_respects_the_limit(self):
        self.assertEqual(len(self.service.release_history(limit=1)), 1)

    def test_history_is_read_only(self):
        before = list(self.store.audit)
        self.service.release_history()
        self.assertEqual(self.store.audit, before)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
