# -*- coding: utf-8 -*-
"""Audit events, and what can never be edited (WP-10).

The rule these tests protect: the record of what happened and the thing that
happened travel together, or neither exists. An audit trail describing a
transition that rolled back is worse than no trail, because somebody would
believe it.
"""

from __future__ import annotations

import ast
import datetime as _dt
import io
import os
import unittest

from pgx.curation.vocabulary import ConflictState, CurationRole
from pgx.curation.workflow import ports
from pgx.curation.workflow.errors import (ConcurrencyError, GateBlockedError,
                                          WorkflowError)
from pgx.curation.workflow.models import (CurationRevision,
                                          EvidenceSelectionSnapshot,
                                          ReviewDecision)
from pgx.domain.enums import AuditAction, CurationStatus
from tests.support.workflow_fixtures import (TEST_CURATOR, TEST_REVIEWER,
                                             TEST_STEWARD, build_service,
                                             evidence_snapshot, raw_work_item,
                                             real_repository_policy, seed_raw,
                                             steward_verification)
from tests.unit.curation._support import REPO_ROOT

WORKFLOW_DIR = os.path.join(REPO_ROOT, "pgx", "curation", "workflow")


class TestEveryOperationWritesOneAuditEvent(unittest.TestCase):

    def setUp(self):
        self.service, self.store = build_service()
        self.item = seed_raw(self.store)

    def _walk(self):
        revision = self.service.create_revision(
            actor_id=TEST_CURATOR, work_item_id=self.item.work_item_id,
            expected_version=0, payload={"c": 1}, evidence=evidence_snapshot())
        self.service.record_provenance_verification(
            actor_id=TEST_STEWARD, work_item_id=self.item.work_item_id,
            verification=steward_verification())
        submitted = self.service.submit(
            actor_id=TEST_CURATOR, work_item_id=self.item.work_item_id,
            revision_id=revision.revision.revision_id, expected_version=1)
        approved = self.service.review(
            actor_id=TEST_REVIEWER, work_item_id=self.item.work_item_id,
            revision_id=revision.revision.revision_id,
            expected_version=submitted.work_item.version,
            decision=ReviewDecision.APPROVE,
            rationale="Independently re-read the cited evidence and agree.",
            conflict_state=ConflictState.NONE_IDENTIFIED,
            rationale_complete=True)
        return revision, submitted, approved

    def test_the_full_walk_writes_one_event_per_transition(self):
        self._walk()
        self.assertEqual([event["action"] for event in self.store.audit],
                         ["CURATION_REVISION_CREATED",
                          "CURATION_REVISION_SUBMITTED",
                          "CURATION_APPROVED"])

    def test_provenance_verification_is_not_a_transition(self):
        """A steward confirms plumbing. That opens a gate; it does not move a
        conclusion, and it must not look like it did."""
        self.service.create_revision(
            actor_id=TEST_CURATOR, work_item_id=self.item.work_item_id,
            expected_version=0, payload={"c": 1}, evidence=evidence_snapshot())
        before = self.store.work_items[self.item.work_item_id]
        self.service.record_provenance_verification(
            actor_id=TEST_STEWARD, work_item_id=self.item.work_item_id,
            verification=steward_verification())
        after = self.store.work_items[self.item.work_item_id]
        self.assertIs(after.status, before.status)
        self.assertEqual(after.version, before.version)

    def test_each_decision_records_its_own_action(self):
        expected = {
            ReviewDecision.APPROVE: AuditAction.CURATION_APPROVED,
            ReviewDecision.REJECT: AuditAction.CURATION_REJECTED,
            ReviewDecision.REQUEST_CHANGES:
                AuditAction.CURATION_CHANGES_REQUESTED,
            ReviewDecision.REFER_TO_ADJUDICATION:
                AuditAction.CURATION_REFERRED_TO_ADJUDICATION,
        }
        for decision, action in expected.items():
            with self.subTest(decision=decision):
                service, store = build_service()
                item = seed_raw(store, raw_work_item("TEST-WI-%s"
                                                     % decision.value[:7]))
                revision = service.create_revision(
                    actor_id=TEST_CURATOR, work_item_id=item.work_item_id,
                    expected_version=0, payload={"c": 1},
                    evidence=evidence_snapshot())
                service.record_provenance_verification(
                    actor_id=TEST_STEWARD, work_item_id=item.work_item_id,
                    verification=steward_verification())
                service.submit(actor_id=TEST_CURATOR,
                               work_item_id=item.work_item_id,
                               revision_id=revision.revision.revision_id,
                               expected_version=1)
                result = service.review(
                    actor_id=TEST_REVIEWER, work_item_id=item.work_item_id,
                    revision_id=revision.revision.revision_id,
                    expected_version=2, decision=decision,
                    rationale="A rationale long enough to be a rationale.",
                    conflict_state=ConflictState.NONE_IDENTIFIED,
                    rationale_complete=True)
                self.assertEqual(result.audit_action, action.value)

    def test_an_audit_event_names_the_actor_and_the_object(self):
        self._walk()
        approval = self.store.audit[-1]
        self.assertEqual(approval["actor"], TEST_REVIEWER)
        self.assertEqual(approval["object_id"], self.item.work_item_id)
        self.assertEqual(approval["metadata"]["author_actor_id"], TEST_CURATOR)

    def test_the_approval_event_pins_the_revision_hash(self):
        revision, _submitted, _approved = self._walk()
        self.assertEqual(self.store.audit[-1]["metadata"][
            "revision_content_hash"], revision.revision.content_hash())


class TestAFailedOperationWritesNothing(unittest.TestCase):
    """A rollback that dropped the change but kept the audit event would leave
    a trail describing something that did not happen."""

    def test_a_blocked_approval_leaves_no_audit_event(self):
        service, store = build_service(policy=real_repository_policy())
        item = seed_raw(store, raw_work_item("TEST-WI-BLOCKED"))
        revision = service.create_revision(
            actor_id=TEST_CURATOR, work_item_id=item.work_item_id,
            expected_version=0, payload={"c": 1}, evidence=evidence_snapshot())
        service.submit(actor_id=TEST_CURATOR, work_item_id=item.work_item_id,
                       revision_id=revision.revision.revision_id,
                       expected_version=1)
        before = list(store.audit)
        with self.assertRaises(GateBlockedError):
            service.review(
                actor_id=TEST_REVIEWER, work_item_id=item.work_item_id,
                revision_id=revision.revision.revision_id,
                expected_version=2, decision=ReviewDecision.APPROVE,
                rationale="I would like to approve this conclusion now.",
                conflict_state=ConflictState.NONE_IDENTIFIED,
                rationale_complete=True)
        self.assertEqual(store.audit, before)

    def test_a_stale_revision_attempt_leaves_no_audit_event(self):
        service, store = build_service()
        item = seed_raw(store, raw_work_item("TEST-WI-STALE"))
        service.create_revision(
            actor_id=TEST_CURATOR, work_item_id=item.work_item_id,
            expected_version=0, payload={"c": 1}, evidence=evidence_snapshot())
        before = list(store.audit)
        revisions_before = dict(store.revisions)
        with self.assertRaises(ConcurrencyError):
            service.create_revision(
                actor_id=TEST_CURATOR, work_item_id=item.work_item_id,
                expected_version=0, payload={"c": 2},
                evidence=evidence_snapshot())
        self.assertEqual(store.audit, before)
        self.assertEqual(store.revisions, revisions_before,
                         "the rejected revision was written anyway")

    def test_the_unit_of_work_rolls_back_the_audit_list_too(self):
        """Asserted directly, because the audit list is the one collection a
        careless rollback would forget: it is append-only, so 'undo' is not
        something the sink itself can do."""
        from pgx.curation.workflow.memory import (InMemoryWorkflowStore,
                                                  InMemoryWorkflowUnitOfWork)
        store = InMemoryWorkflowStore()
        with InMemoryWorkflowUnitOfWork(store) as uow:
            uow.audit.record(action="CURATION_APPROVED", actor="TEST-x",
                             object_type="curation_work_item", object_id="A",
                             occurred_at=_dt.datetime(2026, 1, 1,
                                                      tzinfo=_dt.timezone.utc))
            # no commit
        self.assertEqual(store.audit, [])


class TestNothingOffersAnUpdatePath(unittest.TestCase):
    """Append-only expressed structurally: the method does not exist."""

    APPEND_ONLY_PORTS = ("CurationRevisionRepository",
                         "CurationReviewRepository",
                         "CurationAdjudicationRepository",
                         "ProvenanceVerificationRepository", "AuditSink")

    def test_no_append_only_port_declares_a_mutation(self):
        with io.open(os.path.join(WORKFLOW_DIR, "ports.py"),
                     encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name not in self.APPEND_ONLY_PORTS:
                continue
            methods = {child.name for child in node.body
                       if isinstance(child, ast.FunctionDef)}
            for forbidden in ("update", "delete", "remove", "set", "edit",
                              "replace", "amend", "overwrite"):
                with self.subTest(port=node.name, method=forbidden):
                    self.assertNotIn(forbidden, methods)

    def test_the_in_memory_stores_offer_no_mutation_either(self):
        from pgx.curation.workflow.memory import (InMemoryWorkflowStore,
                                                  InMemoryWorkflowUnitOfWork)
        with InMemoryWorkflowUnitOfWork(InMemoryWorkflowStore()) as uow:
            for name in ("revisions", "reviews", "adjudications", "audit"):
                repository = getattr(uow, name)
                for forbidden in ("update", "delete", "remove", "replace"):
                    with self.subTest(repository=name, method=forbidden):
                        self.assertFalse(hasattr(repository, forbidden))

    def test_only_the_work_item_repository_can_change_a_row(self):
        """And it does so only through the guarded statement."""
        from pgx.curation.workflow.memory import (InMemoryWorkflowStore,
                                                  InMemoryWorkflowUnitOfWork)
        with InMemoryWorkflowUnitOfWork(InMemoryWorkflowStore()) as uow:
            self.assertTrue(hasattr(uow.work_items, "guarded_update"))
            self.assertFalse(hasattr(uow.work_items, "update"))
            self.assertFalse(hasattr(uow.work_items, "set_status"))


class TestRevisionsAreImmutable(unittest.TestCase):

    def _revision(self, **overrides):
        payload = dict(
            work_item_id="TEST-WI-0001", revision_number=1,
            parent_revision_id=None, payload={"c": 1},
            protocol_version="p/1",
            protocol_content_hash="sha256:" + "a" * 64,
            evidence=EvidenceSelectionSnapshot(
                evidence_record_uuids=("11111111-1111-4111-8111-111111111111",)),
            authored_by=TEST_CURATOR,
            authored_by_role=CurationRole.SCIENTIFIC_CURATOR,
            authored_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc))
        payload.update(overrides)
        return CurationRevision(**payload)

    def test_a_revision_cannot_be_assigned_to(self):
        revision = self._revision()
        with self.assertRaises(Exception):
            revision.payload = {"c": 2}

    def test_the_content_hash_covers_the_payload(self):
        self.assertNotEqual(self._revision().content_hash(),
                            self._revision(payload={"c": 2}).content_hash())

    def test_the_content_hash_ignores_the_authored_timestamp(self):
        """Two identical claims written a minute apart are one claim, and a
        hash that disagreed would make 'did this change' unanswerable."""
        later = _dt.datetime(2026, 6, 1, tzinfo=_dt.timezone.utc)
        self.assertEqual(self._revision().content_hash(),
                         self._revision(authored_at=later).content_hash())

    def test_the_content_hash_covers_the_evidence_selection(self):
        other = EvidenceSelectionSnapshot(
            evidence_record_uuids=("22222222-2222-4222-8222-222222222222",))
        self.assertNotEqual(self._revision().content_hash(),
                            self._revision(evidence=other).content_hash())

    def test_revision_one_may_not_claim_a_parent(self):
        with self.assertRaises(WorkflowError):
            self._revision(parent_revision_id="REV-0")

    def test_a_later_revision_must_name_its_parent(self):
        with self.assertRaises(WorkflowError):
            self._revision(revision_number=2, parent_revision_id=None)

    def test_a_revision_cites_at_least_one_evidence_record(self):
        with self.assertRaises(Exception):
            EvidenceSelectionSnapshot(evidence_record_uuids=())

    def test_evidence_cannot_be_both_cited_and_excluded(self):
        with self.assertRaises(Exception) as caught:
            EvidenceSelectionSnapshot(
                evidence_record_uuids=("11111111-1111-4111-8111-111111111111",),
                excluded_record_uuids=("11111111-1111-4111-8111-111111111111",))
        self.assertIn("both included and excluded", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
