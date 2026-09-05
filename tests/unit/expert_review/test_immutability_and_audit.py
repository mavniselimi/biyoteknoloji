# -*- coding: utf-8 -*-
"""Nothing is edited, nothing is deleted, and the chain proves it.

The strongest assertions here are the negative ones about *shape*: the store
port has no update or delete method, the records are frozen dataclasses, and
the correction path appends. An implementation could still be careless; a type
that cannot express the operation cannot be.
"""

from __future__ import annotations

import dataclasses
import unittest

from pgx.expert_review.audit import verify_chain
from pgx.expert_review.errors import AuditChainError, ExpertReviewError
from pgx.expert_review.models import (CompletionDecision, Correction,
                                      ExpectedResponse, RevealRecord,
                                      ReviewAssignment)
from pgx.expert_review.service import ReviewStore
from pgx.expert_review.vocabulary import AuditAction, CorrectionKind
from tests.fixtures.wp22 import blind_review as F

_RECORD_TYPES = (ReviewAssignment, ExpectedResponse, RevealRecord,
                 CompletionDecision, Correction)


class TestTheRecordsCannotBeMutated(unittest.TestCase):

    def test_every_record_type_is_frozen(self):
        for record_type in _RECORD_TYPES:
            with self.subTest(record=record_type.__name__):
                self.assertTrue(
                    record_type.__dataclass_params__.frozen)

    def test_assigning_to_a_field_raises(self):
        expectation = F.service().record_expectation(
            case_id=F.CASE_ID, actor=F.REVIEWER, role="EXPERT_REVIEWER",
            body=F.EXPECTED_BODY)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            expectation.expected_attention_level = "LOW"  # type: ignore

    def test_the_store_port_offers_no_update_or_delete(self):
        """Immutability as a shape rather than a discipline.

        A store with an ``update`` that nobody calls is one refactor away from
        somebody calling it. This one cannot express the operation.
        """
        names = {name for name in dir(ReviewStore)
                 if not name.startswith("_")}
        for forbidden in ("update", "delete", "remove", "replace", "save",
                          "overwrite", "set_state", "edit"):
            with self.subTest(method=forbidden):
                self.assertNotIn(forbidden, names)

    def test_the_in_memory_store_offers_none_either(self):
        names = {name for name in dir(F.InMemoryReviewStore)
                 if not name.startswith("_")}
        for forbidden in ("update", "delete", "remove", "replace"):
            with self.subTest(method=forbidden):
                self.assertNotIn(forbidden, names)

    def test_a_state_change_creates_a_new_assignment_object(self):
        from pgx.expert_review.vocabulary import ReviewState
        original = F.assignment()
        moved = original.with_state(ReviewState.EXPECTATION_RECORDED)
        self.assertIs(original.state, ReviewState.ASSIGNED)
        self.assertIsNot(original, moved)


class TestCorrectionsAppend(unittest.TestCase):

    def setUp(self):
        self.service = F.service()
        self.expectation = self.service.record_expectation(
            case_id=F.CASE_ID, actor=F.REVIEWER, role="EXPERT_REVIEWER",
            body=F.EXPECTED_BODY)

    def _append(self, **overrides):
        body = {"target_hash": self.expectation.revision_hash(),
                "kind": "TYPOGRAPHIC", "reason_code": "TYPO"}
        body.update(overrides)
        return self.service.append_correction(
            case_id=F.CASE_ID, actor=F.REVIEWER, role="EXPERT_REVIEWER",
            body=body)

    def test_the_corrected_record_is_unchanged(self):
        before = self.expectation.revision_hash()
        self._append()
        stored = self.service._store.expectations(F.review_id_for())
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].revision_hash(), before)

    def test_a_correction_names_what_it_corrects(self):
        correction = self._append()
        self.assertEqual(correction.target_hash,
                         self.expectation.revision_hash())

    def test_corrections_chain_to_each_other(self):
        first = self._append()
        second = self._append(reason_code="SECOND")
        self.assertIsNone(first.previous_hash)
        self.assertEqual(second.previous_hash, first.correction_hash())

    def test_a_pre_reveal_correction_is_marked_as_such(self):
        self.assertFalse(self._append().after_reveal)

    def test_a_post_reveal_correction_is_annotation_only(self):
        self.service.reveal(case_id=F.CASE_ID, actor=F.REVIEWER,
                            role="EXPERT_REVIEWER")
        correction = self._append(kind="DECISION_ANNOTATED",
                                  reason_code="CLARIFY")
        self.assertTrue(correction.after_reveal)

    def test_a_post_reveal_correction_cannot_change_the_metric_reference(self):
        """The reveal pinned a hash. Nothing appended afterwards moves it."""
        reveal = self.service.reveal(case_id=F.CASE_ID, actor=F.REVIEWER,
                                     role="EXPERT_REVIEWER")
        pinned = reveal.expectation_revision_hash
        self._append(kind="EXPECTATION_AMENDED", reason_code="CHANGED_MIND",
                     replacement={"expected_attention_level": "LOW"})
        stored = self.service._store.reveal(F.review_id_for())
        self.assertEqual(stored.expectation_revision_hash, pinned)

    def test_a_correction_replacement_cannot_carry_a_clinical_directive(self):
        with self.assertRaises(ExpertReviewError) as caught:
            self._append(kind="RATIONALE_AMENDED", reason_code="X",
                         replacement={"recommendation": "switch drug"})
        self.assertEqual(caught.exception.code,
                         "EXPERT_REVIEW_FORGED_FIELD")

    def test_only_the_assigned_reviewer_may_correct(self):
        with self.assertRaises(ExpertReviewError) as caught:
            self.service.append_correction(
                case_id=F.CASE_ID, actor=F.ADMIN_ACTOR, role="ADMIN",
                body={"target_hash": self.expectation.revision_hash(),
                      "kind": "TYPOGRAPHIC", "reason_code": "X"})
        self.assertEqual(caught.exception.code,
                         "EXPERT_REVIEW_ROLE_REQUIRED")

    def test_a_correction_cannot_backdate_itself(self):
        """The timestamp is the server's. A body supplying one is refused."""
        with self.assertRaises(ExpertReviewError) as caught:
            self._append(recorded_at="2020-01-01T00:00:00Z")
        self.assertEqual(caught.exception.code,
                         "EXPERT_REVIEW_FORGED_FIELD")


class TestTheAuditChainDetectsTampering(unittest.TestCase):

    def setUp(self):
        self.service = F.service()
        self.service.record_expectation(case_id=F.CASE_ID, actor=F.REVIEWER,
                                        role="EXPERT_REVIEWER",
                                        body=F.EXPECTED_BODY)
        self.service.reveal(case_id=F.CASE_ID, actor=F.REVIEWER,
                            role="EXPERT_REVIEWER")
        self.service.complete(case_id=F.CASE_ID, actor=F.REVIEWER,
                              role="EXPERT_REVIEWER",
                              body={"decision": "AGREE"})
        self.chain = list(self.service._store.audit_chain(F.review_id_for()))

    def test_the_intact_chain_verifies(self):
        self.assertEqual(verify_chain(self.chain), (True, ""))

    def test_an_edited_event_breaks_the_chain(self):
        edited = list(self.chain)
        edited[1] = dataclasses.replace(edited[1], outcome_code="TAMPERED")
        clean, reason = verify_chain(edited)
        self.assertFalse(clean)
        self.assertIn("does not name the hash", reason)

    def test_a_deleted_event_breaks_the_chain(self):
        clean, reason = verify_chain(self.chain[:1] + self.chain[2:])
        self.assertFalse(clean)
        self.assertIn("removed or reordered", reason)

    def test_a_reordered_chain_breaks(self):
        swapped = [self.chain[1], self.chain[0], self.chain[2]]
        self.assertFalse(verify_chain(swapped)[0])

    def test_a_truncated_chain_still_verifies_as_a_prefix(self):
        """A prefix is internally consistent, which is why length alone is not
        evidence. The record count is asserted separately by the gate."""
        self.assertEqual(verify_chain(self.chain[:2]), (True, ""))

    def test_an_audit_event_carries_no_expert_content(self):
        import json
        payload = json.dumps([event.to_json() for event in self.chain])
        for forbidden in ("expected_attention_level", "reviewer_note",
                          "decision", "AGREE", "rationale_codes", "HIGH"):
            with self.subTest(term=forbidden):
                self.assertNotIn(forbidden, payload)

    def test_an_event_claiming_authentication_is_refused(self):
        from pgx.expert_review.audit import ReviewAuditEvent
        with self.assertRaises(AuditChainError):
            # Still refused - but now for the WP-23 reason rather than the
            # WP-22 one. The field is no longer pinned false; what is pinned
            # is that only SESSION assurance may accompany a true, and these
            # fixture events carry NONE.
            dataclasses.replace(self.chain[0], actor_authenticated=True)

    def test_an_event_carrying_content_in_its_hashes_is_refused(self):
        with self.assertRaises(AuditChainError):
            dataclasses.replace(
                self.chain[0],
                record_hashes={"reviewer_note": "anything"})


class TestTheActAndItsRecordAreAtomic(unittest.TestCase):

    def test_a_failed_append_rolls_the_transition_back(self):
        store = F.InMemoryReviewStore((F.assignment(),))
        service = F.service(store=store)
        store.fail_next_append = True
        with self.assertRaises(AuditChainError) as caught:
            service.record_expectation(case_id=F.CASE_ID, actor=F.REVIEWER,
                                       role="EXPERT_REVIEWER",
                                       body=F.EXPECTED_BODY)
        self.assertEqual(caught.exception.code, "EXPERT_REVIEW_AUDIT_FAILED")
        self.assertEqual(store.expectations(F.review_id_for()), ())
        self.assertEqual(store.audit_chain(F.review_id_for()), ())
        self.assertEqual(
            store.assignment_for(case_id=F.CASE_ID,
                                 actor=F.REVIEWER).state.value, "ASSIGNED")

    def test_the_unit_of_work_is_exited_on_failure(self):
        class RecordingUow:
            entered = exited = committed = False

            def __enter__(self):
                RecordingUow.entered = True
                return self

            def __exit__(self, *exc):
                RecordingUow.exited = True
                return False

            def commit(self):  # pragma: no cover - never reached here
                RecordingUow.committed = True

        store = F.InMemoryReviewStore((F.assignment(),))
        store.fail_next_append = True
        service = F.service(store=store, uow_factory=RecordingUow)
        with self.assertRaises(AuditChainError):
            service.record_expectation(case_id=F.CASE_ID, actor=F.REVIEWER,
                                       role="EXPERT_REVIEWER",
                                       body=F.EXPECTED_BODY)
        self.assertTrue(RecordingUow.entered)
        self.assertTrue(RecordingUow.exited)
        self.assertFalse(RecordingUow.committed)

    def test_a_successful_act_commits_once(self):
        commits = []

        class CountingUow:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def commit(self):
                commits.append(1)

        service = F.service(uow_factory=CountingUow)
        service.record_expectation(case_id=F.CASE_ID, actor=F.REVIEWER,
                                   role="EXPERT_REVIEWER",
                                   body=F.EXPECTED_BODY)
        self.assertEqual(len(commits), 1)


class TestPermitsAreScopedToOneAssignment(unittest.TestCase):

    def setUp(self):
        self.service = F.service()

    def test_the_assigned_reviewer_gets_a_permit(self):
        permit = self.service.payload_permit(case_id=F.CASE_ID,
                                             actor=F.REVIEWER,
                                             role="EXPERT_REVIEWER")
        self.assertEqual(permit.case_id, F.CASE_ID)
        self.assertEqual(permit.reviewer_actor, F.REVIEWER)
        self.assertEqual(permit.stage, "ASSIGNED")

    def test_an_unassigned_reviewer_gets_none(self):
        from pgx.expert_review.errors import NotAssignedError
        with self.assertRaises(NotAssignedError):
            self.service.payload_permit(case_id=F.CASE_ID,
                                        actor=F.OTHER_REVIEWER,
                                        role="EXPERT_REVIEWER")

    def test_an_admin_gets_none(self):
        with self.assertRaises(ExpertReviewError) as caught:
            self.service.payload_permit(case_id=F.CASE_ID,
                                        actor=F.ADMIN_ACTOR, role="ADMIN")
        self.assertEqual(caught.exception.code,
                         "EXPERT_REVIEW_ROLE_REQUIRED")

    def test_a_completed_review_cannot_reopen_the_payload(self):
        """Otherwise "what did they see, and when" stops being answerable."""
        from pgx.expert_review.errors import PermitError
        self.service.record_expectation(case_id=F.CASE_ID, actor=F.REVIEWER,
                                        role="EXPERT_REVIEWER",
                                        body=F.EXPECTED_BODY)
        self.service.reveal(case_id=F.CASE_ID, actor=F.REVIEWER,
                            role="EXPERT_REVIEWER")
        self.service.complete(case_id=F.CASE_ID, actor=F.REVIEWER,
                              role="EXPERT_REVIEWER",
                              body={"decision": "AGREE"})
        with self.assertRaises(PermitError):
            self.service.payload_permit(case_id=F.CASE_ID, actor=F.REVIEWER,
                                        role="EXPERT_REVIEWER")

    def test_a_permit_for_another_case_does_not_match(self):
        from pgx.expert_review.permits import permit_allows
        permit = self.service.payload_permit(case_id=F.CASE_ID,
                                             actor=F.REVIEWER,
                                             role="EXPERT_REVIEWER")
        self.assertFalse(permit_allows(permit, case_id="PGX-VAL-TEST-ONLY-EH-0002",
                                       actor=F.REVIEWER))

    def test_a_permit_for_another_reviewer_does_not_match(self):
        from pgx.expert_review.permits import permit_allows
        permit = self.service.payload_permit(case_id=F.CASE_ID,
                                             actor=F.REVIEWER,
                                             role="EXPERT_REVIEWER")
        self.assertFalse(permit_allows(permit, case_id=F.CASE_ID,
                                       actor=F.OTHER_REVIEWER))

    def test_no_permit_at_all_does_not_match(self):
        from pgx.expert_review.permits import permit_allows
        self.assertFalse(permit_allows(None, case_id=F.CASE_ID,
                                       actor=F.REVIEWER))

    def test_a_permit_is_never_a_bearer_token(self):
        """It is a value the service hands to the access check in the same
        call. Nothing serialises one to a client."""
        permit = self.service.payload_permit(case_id=F.CASE_ID,
                                             actor=F.REVIEWER,
                                             role="EXPERT_REVIEWER")
        payload = permit.to_json()
        self.assertNotIn("secret", payload)
        self.assertNotIn("token", payload)
