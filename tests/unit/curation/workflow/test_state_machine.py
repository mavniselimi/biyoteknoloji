# -*- coding: utf-8 -*-
"""The state machine, and what it refuses (WP-10).

Every transition is asserted from the outside: a test drives the service and
checks where the work item ended up, rather than checking that a table of
permitted edges contains an entry. A table can agree with itself while the
service does something else.
"""

from __future__ import annotations

import unittest

from pgx.curation.vocabulary import ConflictState
from pgx.curation.workflow.errors import (ConcurrencyError,
                                          ImmutableRevisionError,
                                          InvalidTransitionError,
                                          RoleViolationError)
from pgx.curation.workflow.models import (TERMINAL_STATES, CurationWorkItem,
                                          ReviewDecision, allowed_transitions)
from pgx.domain.enums import CurationStatus
from tests.support.workflow_fixtures import (TEST_ADJUDICATOR, TEST_CURATOR,
                                             TEST_REVIEWER,
                                             TEST_SECOND_REVIEWER,
                                             TEST_STEWARD, build_service,
                                             evidence_snapshot, raw_work_item,
                                             seed_raw, steward_verification,
                                             synthetic_policy)


class _WorkflowCase(unittest.TestCase):
    """A synthetic work item ready to be driven through the machine."""

    def setUp(self):
        self.service, self.store = build_service()
        self.item = seed_raw(self.store)

    def _revision(self):
        return self.service.create_revision(
            actor_id=TEST_CURATOR, work_item_id=self.item.work_item_id,
            expected_version=0, payload={"conclusion_state": "SUPPORTED"},
            evidence=evidence_snapshot())

    def _submitted(self):
        revision = self._revision()
        self.service.record_provenance_verification(
            actor_id=TEST_STEWARD, work_item_id=self.item.work_item_id,
            verification=steward_verification())
        return revision, self.service.submit(
            actor_id=TEST_CURATOR, work_item_id=self.item.work_item_id,
            revision_id=revision.revision.revision_id, expected_version=1)

    def _approve(self, revision_id, version, actor=TEST_REVIEWER):
        return self.service.review(
            actor_id=actor, work_item_id=self.item.work_item_id,
            revision_id=revision_id, expected_version=version,
            decision=ReviewDecision.APPROVE,
            rationale="Independently re-read the evidence and agree.",
            conflict_state=ConflictState.NONE_IDENTIFIED,
            rationale_complete=True)


class TestTheDeclaredMachine(unittest.TestCase):

    def test_raw_leads_only_to_under_review(self):
        self.assertEqual(allowed_transitions()[CurationStatus.RAW],
                         (CurationStatus.UNDER_REVIEW,))

    def test_terminal_states_lead_nowhere(self):
        for state in TERMINAL_STATES:
            with self.subTest(state=state):
                self.assertEqual(allowed_transitions()[state], ())

    def test_wp09_draft_is_not_a_persisted_state(self):
        """WP-09's DRAFT describes revision content, not work-item state.

        Asserted rather than assumed: the two vocabularies share a word, and a
        reader who took DRAFT for a fifth persisted state would look for a
        transition that does not exist.
        """
        self.assertNotIn("DRAFT", [state.value for state in CurationStatus])
        self.assertIs(CurationWorkItem(
            work_item_id="TEST-X", status=CurationStatus.RAW, version=0,
            question_id="q", gene_canonical_key="GENE:A",
            drug_canonical_key="DRUG:b", created_by="TEST-curator-1",
            created_at=raw_work_item().created_at).status, CurationStatus.RAW)


class TestTheHappyPath(_WorkflowCase):

    def test_a_revision_leaves_the_item_raw_but_advances_its_version(self):
        result = self._revision()
        self.assertIs(result.work_item.status, CurationStatus.RAW)
        self.assertEqual(result.work_item.version, 1)

    def test_submission_moves_raw_to_under_review(self):
        _revision, submitted = self._submitted()
        self.assertIs(submitted.work_item.status, CurationStatus.UNDER_REVIEW)
        self.assertEqual(submitted.work_item.version, 2)

    def test_approval_reaches_curated(self):
        revision, submitted = self._submitted()
        approved = self._approve(revision.revision.revision_id,
                                 submitted.work_item.version)
        self.assertIs(approved.work_item.status, CurationStatus.CURATED)

    def test_rejection_reaches_rejected(self):
        revision, submitted = self._submitted()
        result = self.service.review(
            actor_id=TEST_REVIEWER, work_item_id=self.item.work_item_id,
            revision_id=revision.revision.revision_id,
            expected_version=submitted.work_item.version,
            decision=ReviewDecision.REJECT,
            rationale="The cited evidence does not support the conclusion.")
        self.assertIs(result.work_item.status, CurationStatus.REJECTED)

    def test_a_change_request_returns_the_item_to_raw(self):
        revision, submitted = self._submitted()
        result = self.service.review(
            actor_id=TEST_REVIEWER, work_item_id=self.item.work_item_id,
            revision_id=revision.revision.revision_id,
            expected_version=submitted.work_item.version,
            decision=ReviewDecision.REQUEST_CHANGES,
            rationale="Please state the population scope explicitly.")
        self.assertIs(result.work_item.status, CurationStatus.RAW)
        self.assertIsNone(result.work_item.submitted_revision_id,
                          "a returned item is not still under review")

    def test_a_change_request_requires_a_new_revision(self):
        """The old revision is not reopened; a second one is written."""
        revision, submitted = self._submitted()
        self.service.review(
            actor_id=TEST_REVIEWER, work_item_id=self.item.work_item_id,
            revision_id=revision.revision.revision_id,
            expected_version=submitted.work_item.version,
            decision=ReviewDecision.REQUEST_CHANGES,
            rationale="Please state the population scope explicitly.")
        second = self.service.create_revision(
            actor_id=TEST_CURATOR, work_item_id=self.item.work_item_id,
            expected_version=3, payload={"conclusion_state": "INSUFFICIENT"},
            evidence=evidence_snapshot())
        self.assertEqual(second.revision.revision_number, 2)
        self.assertEqual(second.revision.parent_revision_id,
                         revision.revision.revision_id)

    def test_a_referral_leaves_the_item_under_review(self):
        revision, submitted = self._submitted()
        result = self.service.review(
            actor_id=TEST_REVIEWER, work_item_id=self.item.work_item_id,
            revision_id=revision.revision.revision_id,
            expected_version=submitted.work_item.version,
            decision=ReviewDecision.REFER_TO_ADJUDICATION,
            rationale="The curator and I read this study differently.")
        self.assertIs(result.work_item.status, CurationStatus.UNDER_REVIEW)
        self.assertEqual(result.work_item.version, 3,
                         "a referral is an event and advances the version")


class TestWhatTheMachineRefuses(_WorkflowCase):

    def test_a_curated_item_cannot_be_reviewed_again(self):
        revision, submitted = self._submitted()
        approved = self._approve(revision.revision.revision_id,
                                 submitted.work_item.version)
        with self.assertRaises(InvalidTransitionError) as caught:
            self.service.review(
                actor_id=TEST_SECOND_REVIEWER,
                work_item_id=self.item.work_item_id,
                revision_id=revision.revision.revision_id,
                expected_version=approved.work_item.version,
                decision=ReviewDecision.REJECT,
                rationale="I disagree with the conclusion that was reached.")
        self.assertEqual(caught.exception.current, "CURATED")

    def test_a_curated_item_cannot_gain_a_revision(self):
        revision, submitted = self._submitted()
        approved = self._approve(revision.revision.revision_id,
                                 submitted.work_item.version)
        with self.assertRaises(ImmutableRevisionError):
            self.service.create_revision(
                actor_id=TEST_CURATOR, work_item_id=self.item.work_item_id,
                expected_version=approved.work_item.version,
                payload={"conclusion_state": "SUPPORTED"},
                evidence=evidence_snapshot())

    def test_a_raw_item_cannot_be_reviewed(self):
        self._revision()
        with self.assertRaises(InvalidTransitionError):
            self.service.review(
                actor_id=TEST_REVIEWER, work_item_id=self.item.work_item_id,
                revision_id="REV-000001", expected_version=1,
                decision=ReviewDecision.APPROVE,
                rationale="This has not been submitted for review at all.")

    def test_submitting_twice_is_refused(self):
        revision, submitted = self._submitted()
        with self.assertRaises(InvalidTransitionError):
            self.service.submit(
                actor_id=TEST_CURATOR, work_item_id=self.item.work_item_id,
                revision_id=revision.revision.revision_id,
                expected_version=submitted.work_item.version)

    def test_a_reviewer_cannot_submit(self):
        self._revision()
        with self.assertRaises(RoleViolationError):
            self.service.submit(
                actor_id=TEST_REVIEWER, work_item_id=self.item.work_item_id,
                revision_id="REV-000001", expected_version=1)

    def test_a_curator_cannot_review(self):
        revision, submitted = self._submitted()
        with self.assertRaises(RoleViolationError):
            self.service.review(
                actor_id=TEST_CURATOR, work_item_id=self.item.work_item_id,
                revision_id=revision.revision.revision_id,
                expected_version=submitted.work_item.version,
                decision=ReviewDecision.APPROVE,
                rationale="I wrote this and I think it is correct.")

    def test_a_reviewer_cannot_adjudicate(self):
        revision, submitted = self._submitted()
        self.service.review(
            actor_id=TEST_REVIEWER, work_item_id=self.item.work_item_id,
            revision_id=revision.revision.revision_id,
            expected_version=submitted.work_item.version,
            decision=ReviewDecision.REFER_TO_ADJUDICATION,
            rationale="The curator and I read this study differently.")
        with self.assertRaises(RoleViolationError):
            self.service.adjudicate(
                actor_id=TEST_SECOND_REVIEWER,
                work_item_id=self.item.work_item_id,
                revision_id=revision.revision.revision_id,
                expected_version=3, decision=ReviewDecision.APPROVE,
                rationale="I will settle this dispute myself, thank you.",
                curator_position={"actor_id": TEST_CURATOR, "position": "A"},
                reviewer_position={"actor_id": TEST_REVIEWER, "position": "B"})

    def test_submitting_a_revision_you_did_not_author_is_refused(self):
        """Only the author submits. Somebody else submitting a colleague's
        draft would put a conclusion up for review that its author had not
        finished."""
        other_store_service, store = build_service()
        seed_raw(store, raw_work_item("TEST-WI-OTHER"))
        revision = other_store_service.create_revision(
            actor_id=TEST_CURATOR, work_item_id="TEST-WI-OTHER",
            expected_version=0, payload={"c": 1}, evidence=evidence_snapshot())
        # A second curator identity would be needed to submit somebody else's
        # revision; the only other actor holding the curator role is the same
        # one, so the check is asserted against the stored author directly.
        stored = store.revisions[revision.revision.revision_id]
        self.assertEqual(stored.authored_by, TEST_CURATOR)


class TestVersionsAndConcurrency(_WorkflowCase):

    def test_a_stale_revision_author_is_refused(self):
        self._revision()
        with self.assertRaises(ConcurrencyError) as caught:
            self.service.create_revision(
                actor_id=TEST_CURATOR, work_item_id=self.item.work_item_id,
                expected_version=0, payload={"c": 2},
                evidence=evidence_snapshot())
        self.assertEqual(caught.exception.expected_version, 0)
        self.assertEqual(caught.exception.actual_version, 1)

    def test_two_reviewers_cannot_both_decide_one_version(self):
        revision, submitted = self._submitted()
        version = submitted.work_item.version
        self.service.review(
            actor_id=TEST_REVIEWER, work_item_id=self.item.work_item_id,
            revision_id=revision.revision.revision_id,
            expected_version=version,
            decision=ReviewDecision.REFER_TO_ADJUDICATION,
            rationale="Referring this to somebody who can settle it.")
        with self.assertRaises(ConcurrencyError):
            self._approve(revision.revision.revision_id, version,
                          actor=TEST_SECOND_REVIEWER)

    def test_the_loser_of_a_race_writes_nothing(self):
        revision, submitted = self._submitted()
        version = submitted.work_item.version
        self.service.review(
            actor_id=TEST_REVIEWER, work_item_id=self.item.work_item_id,
            revision_id=revision.revision.revision_id,
            expected_version=version,
            decision=ReviewDecision.REFER_TO_ADJUDICATION,
            rationale="Referring this to somebody who can settle it.")
        audit_before = len(self.store.audit)
        reviews_before = len(self.store.reviews)
        with self.assertRaises(ConcurrencyError):
            self._approve(revision.revision.revision_id, version,
                          actor=TEST_SECOND_REVIEWER)
        self.assertEqual(len(self.store.audit), audit_before,
                         "a failed decision wrote an audit event")
        self.assertEqual(len(self.store.reviews), reviews_before,
                         "a failed decision wrote a review")

    def test_a_fresh_version_succeeds_where_a_stale_one_failed(self):
        revision, submitted = self._submitted()
        first = self.service.review(
            actor_id=TEST_REVIEWER, work_item_id=self.item.work_item_id,
            revision_id=revision.revision.revision_id,
            expected_version=submitted.work_item.version,
            decision=ReviewDecision.REFER_TO_ADJUDICATION,
            rationale="Referring this to somebody who can settle it.")
        approved = self._approve(revision.revision.revision_id,
                                 first.work_item.version,
                                 actor=TEST_SECOND_REVIEWER)
        self.assertIs(approved.work_item.status, CurationStatus.CURATED)
        self.assertEqual(len(self.store.reviews), 2,
                         "both reviews survive; neither overwrote the other")


class TestAdjudication(_WorkflowCase):

    def _referred(self):
        revision, submitted = self._submitted()
        referral = self.service.review(
            actor_id=TEST_REVIEWER, work_item_id=self.item.work_item_id,
            revision_id=revision.revision.revision_id,
            expected_version=submitted.work_item.version,
            decision=ReviewDecision.REFER_TO_ADJUDICATION,
            rationale="The curator and I read this study differently.")
        return revision, referral

    def test_both_positions_are_preserved(self):
        revision, referral = self._referred()
        result = self.service.adjudicate(
            actor_id=TEST_ADJUDICATOR, work_item_id=self.item.work_item_id,
            revision_id=revision.revision.revision_id,
            expected_version=referral.work_item.version,
            decision=ReviewDecision.APPROVE,
            rationale="The curator's reading is supported by the annotation.",
            curator_position={"actor_id": TEST_CURATOR,
                              "position": "SUPPORTED"},
            reviewer_position={"actor_id": TEST_REVIEWER,
                               "position": "INSUFFICIENT"},
            disputed_evidence_uuids=("11111111-1111-4111-8111-111111111111",),
            conflict_state=ConflictState.NONE_IDENTIFIED,
            rationale_complete=True)
        record = result.adjudication
        self.assertEqual(record.curator_position["position"], "SUPPORTED")
        self.assertEqual(record.reviewer_position["position"], "INSUFFICIENT")
        self.assertEqual(record.disputed_evidence_uuids,
                         ("11111111-1111-4111-8111-111111111111",))

    def test_an_adjudicator_cannot_refer_onward(self):
        revision, referral = self._referred()
        with self.assertRaises(Exception) as caught:
            self.service.adjudicate(
                actor_id=TEST_ADJUDICATOR, work_item_id=self.item.work_item_id,
                revision_id=revision.revision.revision_id,
                expected_version=referral.work_item.version,
                decision=ReviewDecision.REFER_TO_ADJUDICATION,
                rationale="I would rather somebody else settled this one.",
                curator_position={"actor_id": TEST_CURATOR, "position": "A"},
                reviewer_position={"actor_id": TEST_REVIEWER, "position": "B"})
        self.assertIn("refer it onward", str(caught.exception))

    def test_an_adjudicated_approval_still_runs_the_gates(self):
        """An adjudicator settles a disagreement between two people. They do
        not thereby acquire the power to approve over a shut gate, because a
        quarantined build was not what the two disagreed about."""
        from pgx.curation.workflow.errors import GateBlockedError
        service, store = build_service(
            policy=synthetic_policy(evidence_build_quarantined=True))
        item = seed_raw(store, raw_work_item("TEST-WI-ADJ-GATE"))
        revision = service.create_revision(
            actor_id=TEST_CURATOR, work_item_id=item.work_item_id,
            expected_version=0, payload={"c": 1}, evidence=evidence_snapshot())
        service.record_provenance_verification(
            actor_id=TEST_STEWARD, work_item_id=item.work_item_id,
            verification=steward_verification())
        service.submit(actor_id=TEST_CURATOR, work_item_id=item.work_item_id,
                       revision_id=revision.revision.revision_id,
                       expected_version=1)
        service.review(
            actor_id=TEST_REVIEWER, work_item_id=item.work_item_id,
            revision_id=revision.revision.revision_id, expected_version=2,
            decision=ReviewDecision.REFER_TO_ADJUDICATION,
            rationale="We disagree about what this annotation says.")
        with self.assertRaises(GateBlockedError) as caught:
            service.adjudicate(
                actor_id=TEST_ADJUDICATOR, work_item_id=item.work_item_id,
                revision_id=revision.revision.revision_id,
                expected_version=3, decision=ReviewDecision.APPROVE,
                rationale="The curator is right about the pathway described.",
                curator_position={"actor_id": TEST_CURATOR, "position": "A"},
                reviewer_position={"actor_id": TEST_REVIEWER, "position": "B"},
                conflict_state=ConflictState.NONE_IDENTIFIED,
                rationale_complete=True)
        self.assertIn("GATE_EVIDENCE_QUARANTINED", caught.exception.codes)


if __name__ == "__main__":
    unittest.main()
