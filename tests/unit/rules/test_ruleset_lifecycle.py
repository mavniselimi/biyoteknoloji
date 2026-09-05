# -*- coding: utf-8 -*-
"""The ruleset lifecycle (WP-11, section E).

BUILDING -> VALIDATED -> FROZEN -> RETIRED, with one deliberate loop back:
VALIDATED may return to BUILDING when somebody decides the set is not right
yet. There is no direct BUILDING -> FROZEN edge, and that absence is the whole
design: freezing is what makes a set executable, and a set that could be
frozen without first being validated would be a set nobody had to look at.

Nothing unfreezes. A frozen ruleset is a published artifact somebody may have
acted on; the way to change it is to publish a new version and retire this
one, which leaves both readable.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from pgx.curation.workflow.errors import RoleViolationError
from pgx.domain.enums import RulesetStatus
from pgx.rules.errors import RulesetLifecycleError
from pgx.rules.lifecycle import RULESET_TRANSITION_REQUIREMENTS
from pgx.rules.models import allowed_ruleset_transitions
from tests.fixtures.wp11.synthetic import (TEST_APPROVER, TEST_AUTHOR,
                                           TEST_BUILDER,
                                           build_ruleset_service,
                                           frozen_ruleset,
                                           synthetic_approval_record,
                                           synthetic_inputs_factory,
                                           synthetic_ruleset, validated_rules)

ALL_STATUSES = tuple(RulesetStatus)


class TestTheTransitionTableIsClosed(unittest.TestCase):

    def test_the_four_states_and_their_successors(self):
        self.assertEqual(
            {source.value: tuple(target.value for target in targets)
             for source, targets in allowed_ruleset_transitions().items()},
            {"BUILDING": ("VALIDATED",),
             "VALIDATED": ("FROZEN", "BUILDING"),
             "FROZEN": ("RETIRED",),
             "RETIRED": ()})

    def test_there_is_no_direct_building_to_frozen_edge(self):
        self.assertNotIn(RulesetStatus.FROZEN,
                         allowed_ruleset_transitions()[RulesetStatus.BUILDING])

    def test_nothing_unfreezes(self):
        """A frozen ruleset is a published artifact somebody may have acted
        on. It goes to RETIRED and nowhere else; the way to change it is to
        publish a new version, which leaves both readable."""
        self.assertEqual(allowed_ruleset_transitions()[RulesetStatus.FROZEN],
                         (RulesetStatus.RETIRED,))

    def test_only_a_validated_ruleset_may_return_to_building(self):
        for source, targets in allowed_ruleset_transitions().items():
            with self.subTest(source=source.value):
                self.assertEqual(RulesetStatus.BUILDING in targets,
                                 source is RulesetStatus.VALIDATED)

    def test_retired_is_terminal(self):
        self.assertEqual(allowed_ruleset_transitions()[RulesetStatus.RETIRED],
                         ())

    def test_every_allowed_transition_states_its_requirements(self):
        for source, targets in allowed_ruleset_transitions().items():
            for target in targets:
                key = (source.value, target.value)
                with self.subTest(transition=key):
                    self.assertIn(key, RULESET_TRANSITION_REQUIREMENTS)
                    self.assertTrue(
                        RULESET_TRANSITION_REQUIREMENTS[key].requirements)

    def test_every_transition_outside_the_table_is_refused(self):
        for source in ALL_STATUSES:
            allowed = allowed_ruleset_transitions()[source]
            for target in ALL_STATUSES:
                if target in allowed:
                    continue
                with self.subTest(source=source.value, target=target.value):
                    definition = synthetic_ruleset((), status=source)
                    with self.assertRaises(RulesetLifecycleError):
                        definition.require_transition(target)


class TestOnlyAFrozenRulesetIsExecutable(unittest.TestCase):

    def test_executability_is_exactly_frozen(self):
        for status in ALL_STATUSES:
            definition = synthetic_ruleset((), status=status)
            with self.subTest(status=status.value):
                self.assertEqual(definition.is_executable,
                                 status is RulesetStatus.FROZEN)


class TestMembershipIsOnlyOpenWhileBuilding(unittest.TestCase):

    def test_membership_may_change_while_building(self):
        definition = synthetic_ruleset((), status=RulesetStatus.BUILDING)
        definition.require_membership_open()

    def test_membership_is_closed_from_validated_onwards(self):
        for status in (RulesetStatus.VALIDATED, RulesetStatus.FROZEN,
                       RulesetStatus.RETIRED):
            definition = synthetic_ruleset((), status=status)
            with self.subTest(status=status.value):
                with self.assertRaises(RulesetLifecycleError):
                    definition.require_membership_open()

    def test_a_member_cannot_be_added_to_a_validated_ruleset(self):
        rule_service, store, definitions = validated_rules(2)
        service, _store = build_ruleset_service(store=store)
        ruleset = synthetic_ruleset((), status=RulesetStatus.BUILDING)
        result = service.create(actor_id=TEST_BUILDER, ruleset=ruleset)
        result = service.add_member(actor_id=TEST_BUILDER,
                                    ruleset_id=ruleset.ruleset_id,
                                    rule_id=definitions[0].rule_id,
                                    expected_version=result.ruleset.version)
        result = service.validate(actor_id=TEST_BUILDER,
                                  ruleset_id=ruleset.ruleset_id,
                                  expected_version=result.ruleset.version)
        with self.assertRaises(RulesetLifecycleError):
            service.add_member(actor_id=TEST_BUILDER,
                               ruleset_id=ruleset.ruleset_id,
                               rule_id=definitions[1].rule_id,
                               expected_version=result.ruleset.version)

    def test_reopening_a_validated_ruleset_returns_it_to_building(self):
        rule_service, store, definitions = validated_rules(1)
        service, _store = build_ruleset_service(store=store)
        ruleset = synthetic_ruleset((), status=RulesetStatus.BUILDING)
        result = service.create(actor_id=TEST_BUILDER, ruleset=ruleset)
        result = service.add_member(actor_id=TEST_BUILDER,
                                    ruleset_id=ruleset.ruleset_id,
                                    rule_id=definitions[0].rule_id,
                                    expected_version=result.ruleset.version)
        result = service.validate(actor_id=TEST_BUILDER,
                                  ruleset_id=ruleset.ruleset_id,
                                  expected_version=result.ruleset.version)
        result = service.reopen(actor_id=TEST_BUILDER,
                                ruleset_id=ruleset.ruleset_id,
                                expected_version=result.ruleset.version,
                                reason="SYNTHETIC TEST ONLY: reconsidered.")
        self.assertEqual(result.ruleset.status, RulesetStatus.BUILDING)
        result.ruleset.require_membership_open()


class TestFreezingAndAfter(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.destination = os.path.join(self.tmp, "PGX-RULESET-29991231-001")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_the_whole_path_ends_frozen_with_an_artifact(self):
        service, store, definitions, result = frozen_ruleset(self.destination)
        self.assertEqual(result.ruleset.status, RulesetStatus.FROZEN)
        self.assertTrue(result.ruleset.is_executable)
        self.assertEqual(sorted(os.listdir(self.destination)),
                         ["approval-list.json", "build-log.json",
                          "checksums.sha256", "manifest.json",
                          "rules.ndjson"])

    def test_every_step_is_audited_in_order(self):
        _service, store, _definitions, _result = frozen_ruleset(
            self.destination)
        actions = [event["action"] for event in store.snapshot()["audit"]]
        self.assertEqual(
            [action for action in actions if action.startswith("RULESET_")],
            ["RULESET_CREATED", "RULESET_MEMBER_ADDED",
             "RULESET_MEMBER_ADDED", "RULESET_VALIDATED", "RULESET_FROZEN"])

    def test_a_frozen_ruleset_cannot_be_unfrozen(self):
        service, _store, _definitions, result = frozen_ruleset(
            self.destination)
        with self.assertRaises(RulesetLifecycleError):
            service.reopen(actor_id=TEST_BUILDER,
                           ruleset_id=result.ruleset.ruleset_id,
                           expected_version=result.ruleset.version,
                           reason="SYNTHETIC TEST ONLY")

    def test_a_frozen_ruleset_admits_no_further_members(self):
        service, store, _definitions, result = frozen_ruleset(
            self.destination)
        _rule_service, _store, extra = validated_rules(
            1, service=None, store=None)
        with self.assertRaises(RulesetLifecycleError):
            service.add_member(actor_id=TEST_BUILDER,
                               ruleset_id=result.ruleset.ruleset_id,
                               rule_id=extra[0].rule_id,
                               expected_version=result.ruleset.version)

    def test_a_frozen_ruleset_may_only_be_retired(self):
        service, _store, _definitions, result = frozen_ruleset(
            self.destination)
        retired = service.retire(
            actor_id=TEST_BUILDER, ruleset_id=result.ruleset.ruleset_id,
            expected_version=result.ruleset.version,
            reason="SYNTHETIC TEST ONLY: superseded by a later fixture.")
        self.assertEqual(retired.ruleset.status, RulesetStatus.RETIRED)
        self.assertFalse(retired.ruleset.is_executable)

    def test_retiring_leaves_the_artifact_on_disk(self):
        """A retired ruleset is still a record of what was published. Deleting
        the artifact would erase the evidence of what once executed."""
        service, _store, _definitions, result = frozen_ruleset(
            self.destination)
        service.retire(actor_id=TEST_BUILDER,
                       ruleset_id=result.ruleset.ruleset_id,
                       expected_version=result.ruleset.version,
                       reason="SYNTHETIC TEST ONLY")
        self.assertTrue(os.path.isfile(
            os.path.join(self.destination, "manifest.json")))


class TestWhoMayMoveARuleset(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_an_author_may_not_freeze(self):
        rule_service, store, definitions = validated_rules(1)
        service, _store = build_ruleset_service(store=store)
        ruleset = synthetic_ruleset((), status=RulesetStatus.BUILDING)
        with self.assertRaises(RoleViolationError):
            service.create(actor_id=TEST_AUTHOR, ruleset=ruleset)

    def test_a_protocol_owner_holds_no_ruleset_governance_role_here(self):
        rule_service, store, _definitions = validated_rules(1)
        service, _store = build_ruleset_service(store=store)
        with self.assertRaises(RoleViolationError):
            service.create(actor_id=TEST_APPROVER,
                           ruleset=synthetic_ruleset(
                               (), status=RulesetStatus.BUILDING))


class TestAnEmptyRulesetCannotBeValidated(unittest.TestCase):

    def test_validating_an_empty_ruleset_is_refused(self):
        _rule_service, store, _definitions = validated_rules(1)
        service, _store = build_ruleset_service(store=store)
        ruleset = synthetic_ruleset((), status=RulesetStatus.BUILDING)
        result = service.create(actor_id=TEST_BUILDER, ruleset=ruleset)
        with self.assertRaises(Exception):
            service.validate(actor_id=TEST_BUILDER,
                             ruleset_id=ruleset.ruleset_id,
                             expected_version=result.ruleset.version)


if __name__ == "__main__":
    unittest.main()
