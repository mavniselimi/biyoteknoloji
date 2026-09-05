# -*- coding: utf-8 -*-
"""The rule lifecycle, and who may move it (WP-11, section C).

DRAFT -> CURATED -> VALIDATED -> DEPRECATED, one direction, no shortcuts. The
transitions are few enough to list, so they are listed and every path outside
the list is asserted to fail rather than left to inference.

Two rules run through everything here. Nothing executes before VALIDATED
(``SAFETY-INV-003``), and no actor may perform two separated acts on the same
rule: an author who could also validate would be a review process with one
participant.
"""

from __future__ import annotations

import unittest

from pgx.curation.workflow.errors import RoleViolationError
from pgx.domain.enums import RuleStatus
from pgx.rules.errors import RuleLifecycleError
from pgx.rules.lifecycle import RULE_TRANSITION_REQUIREMENTS
from pgx.rules.models import allowed_rule_transitions
from tests.fixtures.wp11.synthetic import (TEST_APPROVER, TEST_AUTHOR,
                                           TEST_REVIEWER, TEST_VALIDATOR,
                                           build_rule_service,
                                           synthetic_context,
                                           synthetic_lifecycle, synthetic_rule)

ALL_STATUSES = tuple(RuleStatus)


def _draft(service=None, store=None, definition=None):
    if service is None:
        service, store = build_rule_service()
    definition = definition or synthetic_rule()
    service.draft_rule(actor_id=TEST_AUTHOR, definition=definition,
                       reason="SYNTHETIC TEST ONLY")
    return service, store, definition


def _validated():
    service, store, definition = _draft()
    context = synthetic_context(definition)
    service.mark_curated(actor_id=TEST_AUTHOR, rule_id=definition.rule_id,
                         expected_version=0, context=context,
                         reason="SYNTHETIC TEST ONLY")
    service.validate(actor_id=TEST_VALIDATOR, rule_id=definition.rule_id,
                     expected_version=1, context=context,
                     reason="SYNTHETIC TEST ONLY")
    return service, store, definition


class TestTheTransitionTableIsClosed(unittest.TestCase):

    def test_the_four_states_and_their_only_successors(self):
        self.assertEqual(
            {source.value: tuple(target.value for target in targets)
             for source, targets in allowed_rule_transitions().items()},
            {"DRAFT": ("CURATED",),
             "CURATED": ("VALIDATED",),
             "VALIDATED": ("DEPRECATED",),
             "DEPRECATED": ()})

    def test_deprecated_is_terminal(self):
        self.assertEqual(allowed_rule_transitions()[RuleStatus.DEPRECATED], ())

    def test_there_is_no_path_back_to_draft(self):
        for targets in allowed_rule_transitions().values():
            self.assertNotIn(RuleStatus.DRAFT, targets)

    def test_every_allowed_transition_states_its_requirements(self):
        for source, targets in allowed_rule_transitions().items():
            for target in targets:
                key = (source.value, target.value)
                with self.subTest(transition=key):
                    self.assertIn(key, RULE_TRANSITION_REQUIREMENTS)
                    requirement = RULE_TRANSITION_REQUIREMENTS[key]
                    self.assertTrue(requirement.roles)
                    self.assertTrue(requirement.requirements)

    def test_every_transition_outside_the_table_is_refused(self):
        for source in ALL_STATUSES:
            allowed = allowed_rule_transitions()[source]
            for target in ALL_STATUSES:
                if target in allowed:
                    continue
                with self.subTest(source=source.value, target=target.value):
                    record = synthetic_lifecycle(synthetic_rule(),
                                                 status=source)
                    with self.assertRaises(RuleLifecycleError):
                        record.require_transition(target)


class TestNothingExecutesBeforeValidated(unittest.TestCase):
    """``SAFETY-INV-003``."""

    def test_only_validated_is_executable(self):
        definition = synthetic_rule()
        for status in ALL_STATUSES:
            record = synthetic_lifecycle(definition, status=status)
            with self.subTest(status=status.value):
                self.assertEqual(record.is_executable,
                                 status is RuleStatus.VALIDATED)

    def test_a_deprecated_rule_stops_being_executable(self):
        definition = synthetic_rule()
        self.assertFalse(
            synthetic_lifecycle(definition,
                                status=RuleStatus.DEPRECATED).is_executable)


class TestTheHappyPathIsAuditedAtEveryStep(unittest.TestCase):

    def test_draft_curate_validate_deprecate(self):
        service, store, definition = _validated()
        service.deprecate(actor_id=TEST_VALIDATOR,
                          rule_id=definition.rule_id, expected_version=2,
                          reason="SYNTHETIC TEST ONLY: withdrawn by a test.")
        record = service.inspect(definition.rule_id)["lifecycle"]
        self.assertEqual(record["status"], "DEPRECATED")
        self.assertEqual([event["action"] for event in
                          store.snapshot()["audit"]],
                         ["RULE_DRAFTED", "RULE_CURATED", "RULE_VALIDATED",
                          "RULE_DEPRECATED"])

    def test_each_audit_event_names_the_actor_and_the_rule(self):
        _service, store, definition = _validated()
        for event in store.snapshot()["audit"]:
            with self.subTest(action=event["action"]):
                self.assertTrue(event["actor"])
                self.assertEqual(event["object_id"],
                                 definition.rule_id.to_json())

    def test_the_lifecycle_version_advances_on_every_transition(self):
        service, _store, definition = _validated()
        self.assertEqual(
            service.inspect(definition.rule_id)["lifecycle"]["version"], 2)

    def test_validation_records_who_validated_and_against_what(self):
        service, _store, definition = _validated()
        record = service.inspect(definition.rule_id)["lifecycle"]
        self.assertEqual(record["validated_by"], TEST_VALIDATOR)
        self.assertIsNotNone(record["validated_at"])
        self.assertTrue(record["validation_result_hash"])


class TestSeparationOfDuties(unittest.TestCase):

    def test_an_author_may_not_validate_their_own_rule(self):
        service, _store, definition = _draft()
        context = synthetic_context(definition)
        service.mark_curated(actor_id=TEST_AUTHOR, rule_id=definition.rule_id,
                             expected_version=0, context=context)
        with self.assertRaises(RoleViolationError):
            service.validate(actor_id=TEST_AUTHOR, rule_id=definition.rule_id,
                             expected_version=1, context=context)

    def test_a_rule_may_not_be_authored_by_somebody_who_is_not_acting(self):
        service, _store = build_rule_service()
        definition = synthetic_rule(created_by=TEST_REVIEWER)
        with self.assertRaises(RoleViolationError):
            service.draft_rule(actor_id=TEST_AUTHOR, definition=definition)

    def test_an_actor_without_the_curator_role_may_not_draft(self):
        service, _store = build_rule_service()
        definition = synthetic_rule(created_by=TEST_APPROVER)
        with self.assertRaises(RoleViolationError):
            service.draft_rule(actor_id=TEST_APPROVER, definition=definition)

    def test_an_unknown_actor_has_no_roles_at_all(self):
        service, _store = build_rule_service()
        with self.assertRaises(Exception):
            service.draft_rule(actor_id="somebody-not-in-the-provider",
                               definition=synthetic_rule())

    def test_a_caller_may_not_supply_its_own_roles(self):
        """Roles are resolved by the provider. A caller that could pass an
        ``ActorContext`` would be asserting its own permissions."""
        from pgx.curation.workflow.roles import ActorContext
        service, _store = build_rule_service()
        with self.assertRaises(Exception):
            service.draft_rule(actor_id=ActorContext,
                               definition=synthetic_rule())


class TestOptimisticConcurrency(unittest.TestCase):

    def test_a_stale_expected_version_is_refused(self):
        service, _store, definition = _draft()
        context = synthetic_context(definition)
        service.mark_curated(actor_id=TEST_AUTHOR, rule_id=definition.rule_id,
                             expected_version=0, context=context)
        with self.assertRaises(Exception):
            service.mark_curated(actor_id=TEST_AUTHOR,
                                 rule_id=definition.rule_id,
                                 expected_version=0, context=context)

    def test_a_second_validation_of_the_same_version_is_refused(self):
        service, _store, definition = _validated()
        with self.assertRaises(Exception):
            service.validate(actor_id=TEST_VALIDATOR,
                             rule_id=definition.rule_id, expected_version=1,
                             context=synthetic_context(definition))


class TestAValidatedRuleIsImmutable(unittest.TestCase):

    def test_the_content_hash_is_pinned_from_validation_onwards(self):
        definition = synthetic_rule()
        record = synthetic_lifecycle(definition, status=RuleStatus.VALIDATED)
        record.require_content_unchanged(definition.content_hash())
        with self.assertRaises(Exception):
            record.require_content_unchanged("sha256:" + "0" * 64)

    def test_a_validated_record_reports_itself_immutable(self):
        definition = synthetic_rule()
        for status in ALL_STATUSES:
            record = synthetic_lifecycle(definition, status=status)
            with self.subTest(status=status.value):
                self.assertEqual(
                    record.is_immutable,
                    status in (RuleStatus.VALIDATED, RuleStatus.DEPRECATED))

    def test_a_changed_rule_is_a_new_version_not_an_edit(self):
        """Version lineage, not mutation: the family is the same question,
        each version is one answer, and the old answer stays readable."""
        first = synthetic_rule()
        second = synthetic_rule(family_id=first.family_id, rule_version=2,
                                supersedes=first.rule_id)
        self.assertEqual(first.family_id, second.family_id)
        self.assertNotEqual(first.rule_id, second.rule_id)
        self.assertEqual(second.supersedes_rule_id, first.rule_id)
        self.assertNotEqual(first.content_hash(), second.content_hash())


if __name__ == "__main__":
    unittest.main()
