# -*- coding: utf-8 -*-
"""Roles, gates, and why nothing in this repository can be approved (WP-10).

Two subjects, kept in one file because they are one argument: a conclusion
reaches CURATED only when a qualified person who is not its author says so and
every gate is open, and in this repository neither half holds.
"""

from __future__ import annotations

import datetime as _dt
import unittest

from pgx.curation.vocabulary import (ConflictState, CurationRole,
                                     ProtocolStatus)
from pgx.curation.workflow.errors import (ActorError, GateBlockedError,
                                          RoleViolationError)
from pgx.curation.workflow.models import ProvenanceVerification, ReviewDecision
from pgx.curation.workflow.policy import (GATE_CODES, WorkflowPolicy,
                                          evaluate_curated_gates)
from pgx.curation.workflow.roles import (EMPTY_ROLE_ASSIGNMENTS,
                                         SYNTHETIC_ACTOR_PREFIX, ActorContext,
                                         StaticRoleProvider, require_role)
from tests.support.workflow_fixtures import (SYNTHETIC_ACTORS,
                                             SYNTHETIC_EVIDENCE_UUIDS,
                                             TEST_CURATOR, TEST_REVIEWER,
                                             TEST_STEWARD, build_service,
                                             evidence_snapshot,
                                             raw_work_item,
                                             real_repository_policy, seed_raw,
                                             steward_verification,
                                             synthetic_policy,
                                             synthetic_role_provider)


class TestTheProductionRoleSetIsEmpty(unittest.TestCase):
    """No real identity holds any role, and that is the shipped state."""

    def test_the_default_assignment_set_is_empty(self):
        self.assertEqual(dict(EMPTY_ROLE_ASSIGNMENTS), {})

    def test_a_provider_with_no_arguments_grants_nothing(self):
        provider = StaticRoleProvider()
        self.assertTrue(provider.is_empty)
        self.assertEqual(len(provider), 0)

    def test_looking_up_any_actor_raises(self):
        with self.assertRaises(ActorError) as caught:
            StaticRoleProvider().for_actor("anybody")
        self.assertIn("production role assignment set is empty",
                      str(caught.exception))

    def test_no_shipped_module_assigns_a_role_to_a_named_person(self):
        """Every actor this codebase can construct is synthetic."""
        for actor_id in SYNTHETIC_ACTORS:
            with self.subTest(actor=actor_id):
                self.assertTrue(actor_id.startswith(SYNTHETIC_ACTOR_PREFIX))


class TestActorContextCannotBeForged(unittest.TestCase):

    def test_a_context_cannot_be_constructed_with_roles_directly(self):
        with self.assertRaises(ActorError) as caught:
            ActorContext(actor_id="TEST-someone", display_name="Someone",
                         roles=frozenset({CurationRole.ADJUDICATOR}),
                         synthetic=True)
        self.assertIn("issued by a RoleProvider", str(caught.exception))

    def test_the_synthetic_flag_must_match_the_prefix(self):
        provider = synthetic_role_provider()
        actor = provider.for_actor(TEST_CURATOR)
        self.assertTrue(actor.synthetic)
        self.assertTrue(actor.actor_id.startswith(SYNTHETIC_ACTOR_PREFIX))

    def test_the_service_refuses_a_context_passed_as_an_actor_id(self):
        """A caller supplying its own ActorContext would be asserting its own
        permissions. The service takes an id and looks the roles up."""
        service, _store = build_service()
        issued = synthetic_role_provider().for_actor(TEST_CURATOR)
        for candidate in (issued, ActorContext):
            with self.subTest(candidate=type(candidate).__name__):
                with self.assertRaises(ActorError) as caught:
                    service._actor(candidate)
                self.assertIn("pass an actor id", str(caught.exception))

    def test_require_role_names_the_role_it_wanted(self):
        actor = synthetic_role_provider().for_actor(TEST_CURATOR)
        with self.assertRaises(RoleViolationError) as caught:
            require_role(actor, CurationRole.ADJUDICATOR, "adjudicate")
        self.assertIn("ADJUDICATOR", str(caught.exception))


class TestSeparationOfDuties(unittest.TestCase):

    def setUp(self):
        self.service, self.store = build_service()
        self.item = seed_raw(self.store)
        self.revision = self.service.create_revision(
            actor_id=TEST_CURATOR, work_item_id=self.item.work_item_id,
            expected_version=0, payload={"c": 1}, evidence=evidence_snapshot())
        self.service.record_provenance_verification(
            actor_id=TEST_STEWARD, work_item_id=self.item.work_item_id,
            verification=steward_verification())
        self.submitted = self.service.submit(
            actor_id=TEST_CURATOR, work_item_id=self.item.work_item_id,
            revision_id=self.revision.revision.revision_id,
            expected_version=1)

    def test_a_review_pins_the_author_it_was_checked_against(self):
        result = self.service.review(
            actor_id=TEST_REVIEWER, work_item_id=self.item.work_item_id,
            revision_id=self.revision.revision.revision_id,
            expected_version=self.submitted.work_item.version,
            decision=ReviewDecision.APPROVE,
            rationale="Independently re-read the cited evidence and agree.",
            conflict_state=ConflictState.NONE_IDENTIFIED,
            rationale_complete=True)
        self.assertEqual(result.review.author_actor_id, TEST_CURATOR)
        self.assertNotEqual(result.review.reviewed_by,
                            result.review.author_actor_id)

    def test_a_review_pins_the_content_hash_it_read(self):
        result = self.service.review(
            actor_id=TEST_REVIEWER, work_item_id=self.item.work_item_id,
            revision_id=self.revision.revision.revision_id,
            expected_version=self.submitted.work_item.version,
            decision=ReviewDecision.REJECT,
            rationale="The cited evidence does not support this conclusion.")
        self.assertEqual(result.review.revision_content_hash,
                         self.revision.revision.content_hash())

    def test_the_separation_rule_lives_on_the_review_record(self):
        """Checked by the record's own constructor, not only at the call site.
        A review row that failed this could not have been legitimate however
        it was created."""
        from pgx.curation.workflow.models import CurationReview
        from pgx.curation.workflow.errors import WorkflowError
        with self.assertRaises(WorkflowError) as caught:
            CurationReview(
                work_item_id="TEST-WI-0001", revision_id="REV-1",
                revision_content_hash="sha256:" + "a" * 64,
                decision=ReviewDecision.APPROVE, reviewed_by="TEST-curator-1",
                reviewed_by_role=CurationRole.INDEPENDENT_SCIENTIFIC_REVIEWER,
                reviewed_at=_dt.datetime(2026, 1, 1,
                                         tzinfo=_dt.timezone.utc),
                author_actor_id="test-Curator-1",
                rationale="A rationale long enough to count as one.",
                protocol_content_hash="sha256:" + "b" * 64,
                evidence_build_content_hash="sha256:" + "c" * 64)
        self.assertIn("not an independent review", str(caught.exception))


class TestTheGatesFailClosed(unittest.TestCase):

    def _revision(self, **overrides):
        service, store = build_service(**overrides)
        item = seed_raw(store, raw_work_item("TEST-WI-GATE"))
        return service.create_revision(
            actor_id=TEST_CURATOR, work_item_id=item.work_item_id,
            expected_version=0, payload={"c": 1},
            evidence=evidence_snapshot()).revision

    def test_every_declared_gate_is_evaluated(self):
        result = evaluate_curated_gates(synthetic_policy(), self._revision())
        self.assertEqual(len(result.outcomes), len(GATE_CODES))
        self.assertEqual({outcome.code for outcome in result.outcomes},
                         set(GATE_CODES))

    def test_every_gate_is_evaluated_even_after_one_fails(self):
        """Returning on the first shut gate would hide the other twelve and
        make fixing them a round-trip each."""
        result = evaluate_curated_gates(real_repository_policy(),
                                        self._revision())
        self.assertEqual(len(result.outcomes), len(GATE_CODES))
        self.assertGreater(len(result.blocked), 1)

    def test_no_input_at_all_means_every_answerable_gate_is_shut(self):
        result = evaluate_curated_gates(real_repository_policy(),
                                        self._revision())
        for code in ("GATE_PROTOCOL_NOT_APPROVED", "GATE_EVIDENCE_MISSING",
                     "GATE_EVIDENCE_TRACE_UNVERIFIED",
                     "GATE_EVIDENCE_QUARANTINED",
                     "GATE_SOURCE_POLICY_MISSING",
                     "GATE_PROVENANCE_VERIFICATION_MISSING",
                     "GATE_RATIONALE_INCOMPLETE",
                     "GATE_REVIEWER_NOT_INDEPENDENT", "GATE_VERSION_STALE"):
            with self.subTest(gate=code):
                outcome = next(o for o in result.outcomes if o.code == code)
                self.assertFalse(outcome.passed)

    def test_an_approved_protocol_with_no_named_approver_does_not_pass(self):
        """APPROVED is a status; an approval is a person. A status without one
        is a claim nobody made."""
        policy = synthetic_policy(protocol_status=ProtocolStatus.APPROVED,
                                  protocol_approved_by=None)
        self.assertFalse(policy.protocol_is_approved)
        result = evaluate_curated_gates(policy, self._revision())
        outcome = next(o for o in result.outcomes
                       if o.code == "GATE_PROTOCOL_NOT_APPROVED")
        self.assertFalse(outcome.passed)

    def test_a_reviewer_who_authored_the_revision_fails_the_gate(self):
        revision = self._revision()
        actor = synthetic_role_provider().for_actor(TEST_CURATOR)
        result = evaluate_curated_gates(
            synthetic_policy(), revision, reviewer=actor,
            author_actor_id=revision.authored_by)
        outcome = next(o for o in result.outcomes
                       if o.code == "GATE_REVIEWER_NOT_INDEPENDENT")
        self.assertFalse(outcome.passed)
        self.assertIn("authored", outcome.detail)

    def test_a_steward_who_reports_problems_does_not_open_the_trace_gate(self):
        revision = self._revision()
        verification = ProvenanceVerification(
            verified_by=TEST_STEWARD,
            verified_by_role=CurationRole.DATA_PROVENANCE_STEWARD,
            verified_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc),
            evidence_record_uuids=SYNTHETIC_EVIDENCE_UUIDS,
            all_traces_verified=False,
            problems=("one artifact digest no longer matches",))
        result = evaluate_curated_gates(synthetic_policy(), revision,
                                        provenance=verification)
        outcome = next(o for o in result.outcomes
                       if o.code == "GATE_EVIDENCE_TRACE_UNVERIFIED")
        self.assertFalse(outcome.passed)

    def test_every_gate_names_an_owner(self):
        """A shut gate that nobody owns is a shut gate nobody opens."""
        for code, entry in GATE_CODES.items():
            with self.subTest(gate=code):
                self.assertTrue(entry["owner"].strip())
                self.assertTrue(entry["requirement"].strip())

    def test_an_undeclared_gate_code_cannot_be_reported(self):
        from pgx.curation.workflow.policy import GateOutcome
        with self.assertRaises(KeyError):
            GateOutcome(code="GATE_INVENTED", passed=True, detail="")


class TestThisRepositoryCannotApprove(unittest.TestCase):
    """The point of the whole work package, asserted once, plainly."""

    def setUp(self):
        self.service, self.store = build_service(
            policy=real_repository_policy())
        self.item = seed_raw(self.store, raw_work_item("TEST-WI-REAL"))
        self.revision = self.service.create_revision(
            actor_id=TEST_CURATOR, work_item_id=self.item.work_item_id,
            expected_version=0, payload={"c": 1}, evidence=evidence_snapshot())
        self.submitted = self.service.submit(
            actor_id=TEST_CURATOR, work_item_id=self.item.work_item_id,
            revision_id=self.revision.revision.revision_id,
            expected_version=1)

    def test_approval_is_blocked_and_says_why(self):
        with self.assertRaises(GateBlockedError) as caught:
            self.service.review(
                actor_id=TEST_REVIEWER, work_item_id=self.item.work_item_id,
                revision_id=self.revision.revision.revision_id,
                expected_version=self.submitted.work_item.version,
                decision=ReviewDecision.APPROVE,
                rationale="I would like to approve this conclusion now.",
                conflict_state=ConflictState.NONE_IDENTIFIED,
                rationale_complete=True)
        codes = set(caught.exception.codes)
        self.assertIn("GATE_PROTOCOL_NOT_APPROVED", codes)
        self.assertIn("GATE_EVIDENCE_QUARANTINED", codes)
        self.assertIn("GATE_SOURCE_POLICY_MISSING", codes)

    def test_a_blocked_approval_leaves_the_item_where_it_was(self):
        with self.assertRaises(GateBlockedError):
            self.service.review(
                actor_id=TEST_REVIEWER, work_item_id=self.item.work_item_id,
                revision_id=self.revision.revision.revision_id,
                expected_version=self.submitted.work_item.version,
                decision=ReviewDecision.APPROVE,
                rationale="I would like to approve this conclusion now.",
                conflict_state=ConflictState.NONE_IDENTIFIED,
                rationale_complete=True)
        stored = self.store.work_items[self.item.work_item_id]
        self.assertEqual(stored.status.value, "UNDER_REVIEW")
        self.assertEqual(stored.version, self.submitted.work_item.version)

    def test_refusing_still_works_when_the_gates_are_shut(self):
        """A reviewer must be able to refuse a conclusion precisely when it
        cannot be approved. Gating rejection behind the approval gates would
        trap every blocked item under review forever."""
        for decision in (ReviewDecision.REJECT,
                         ReviewDecision.REQUEST_CHANGES,
                         ReviewDecision.REFER_TO_ADJUDICATION):
            with self.subTest(decision=decision):
                service, store = build_service(
                    policy=real_repository_policy())
                item = seed_raw(store, raw_work_item("TEST-WI-%s"
                                                     % decision.value[:6]))
                revision = service.create_revision(
                    actor_id=TEST_CURATOR, work_item_id=item.work_item_id,
                    expected_version=0, payload={"c": 1},
                    evidence=evidence_snapshot())
                service.submit(actor_id=TEST_CURATOR,
                               work_item_id=item.work_item_id,
                               revision_id=revision.revision.revision_id,
                               expected_version=1)
                result = service.review(
                    actor_id=TEST_REVIEWER, work_item_id=item.work_item_id,
                    revision_id=revision.revision.revision_id,
                    expected_version=2, decision=decision,
                    rationale="This cannot be approved and I am saying so.")
                self.assertIsNotNone(result.audit_event_id)

    def test_no_curated_interpretation_is_ever_constructed(self):
        """WP-10 moves work items. Creating the WP-02 row is not its job, and
        the identifier appears nowhere in the workflow package."""
        import ast
        import io
        import os
        from tests.unit.curation._support import REPO_ROOT
        directory = os.path.join(REPO_ROOT, "pgx", "curation", "workflow")
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".py"):
                continue
            with io.open(os.path.join(directory, name),
                         encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=name)
            identifiers = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    identifiers.add(node.id)
                elif isinstance(node, ast.Attribute):
                    identifiers.add(node.attr)
                elif isinstance(node, ast.ImportFrom):
                    identifiers.update(alias.name for alias in node.names)
            with self.subTest(module=name):
                self.assertNotIn("CuratedInterpretation", identifiers)


if __name__ == "__main__":
    unittest.main()
