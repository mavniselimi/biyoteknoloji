# -*- coding: utf-8 -*-
"""Three forward edges, and nothing else."""

from __future__ import annotations

import unittest

from pgx.expert_review.errors import ExpertReviewError
from pgx.expert_review.vocabulary import (DECISION_VALUES, ReviewState,
                                          TERMINAL_STATES, TRANSITIONS,
                                          ExpertDecision, may_transition)
from tests.fixtures.wp22 import blind_review as F


class TestTheLifecycleHasExactlyThreeForwardEdges(unittest.TestCase):

    def test_the_permitted_forward_moves(self):
        self.assertTrue(may_transition(ReviewState.ASSIGNED,
                                       ReviewState.EXPECTATION_RECORDED))
        self.assertTrue(may_transition(ReviewState.EXPECTATION_RECORDED,
                                       ReviewState.RESULT_REVEALED))
        self.assertTrue(may_transition(ReviewState.RESULT_REVEALED,
                                       ReviewState.COMPLETED))

    def test_no_state_moves_backwards(self):
        order = [ReviewState.ASSIGNED, ReviewState.EXPECTATION_RECORDED,
                 ReviewState.RESULT_REVEALED, ReviewState.COMPLETED]
        for index, later in enumerate(order):
            for earlier in order[:index]:
                with self.subTest(frm=later.value, to=earlier.value):
                    self.assertFalse(may_transition(later, earlier))

    def test_no_state_skips_a_phase(self):
        self.assertFalse(may_transition(ReviewState.ASSIGNED,
                                        ReviewState.RESULT_REVEALED))
        self.assertFalse(may_transition(ReviewState.ASSIGNED,
                                        ReviewState.COMPLETED))
        self.assertFalse(may_transition(ReviewState.EXPECTATION_RECORDED,
                                        ReviewState.COMPLETED))

    def test_no_state_repeats_itself(self):
        for state in ReviewState:
            with self.subTest(state=state.value):
                self.assertFalse(may_transition(state, state))

    def test_terminal_states_lead_nowhere(self):
        for name in sorted(TERMINAL_STATES):
            with self.subTest(state=name):
                self.assertEqual(TRANSITIONS[name], frozenset())

    def test_invalidation_is_reachable_from_every_live_state(self):
        """A protocol or release breakage can happen at any point before the
        end, and pretending otherwise would leave a spoiled review looking
        like a live one."""
        for state in (ReviewState.ASSIGNED, ReviewState.EXPECTATION_RECORDED,
                      ReviewState.RESULT_REVEALED):
            with self.subTest(state=state.value):
                self.assertTrue(may_transition(state,
                                               ReviewState.INVALIDATED))

    def test_invalidation_is_not_a_retry(self):
        self.assertEqual(TRANSITIONS[ReviewState.INVALIDATED.value],
                         frozenset())


class TestTheDecisionVocabularyIsExactlyThree(unittest.TestCase):

    def test_three_values(self):
        self.assertEqual(DECISION_VALUES, ("AGREE", "PARTIAL", "DISAGREE"))

    def test_decisions_are_unordered(self):
        """PARTIAL is a third answer, not a midpoint. Sorting would invent a
        scale, and the first thing built on it would be a mean agreement."""
        with self.assertRaises(TypeError):
            _ = ExpertDecision.AGREE < ExpertDecision.PARTIAL

    def test_an_unknown_decision_is_refused(self):
        service = F.service()
        service.record_expectation(case_id=F.CASE_ID, actor=F.REVIEWER,
                                   role="EXPERT_REVIEWER",
                                   body=F.EXPECTED_BODY)
        service.reveal(case_id=F.CASE_ID, actor=F.REVIEWER,
                       role="EXPERT_REVIEWER")
        for bad in ("MOSTLY_AGREE", "agree", "YES", "4", ""):
            with self.subTest(decision=bad):
                with self.assertRaises(ExpertReviewError):
                    service.complete(case_id=F.CASE_ID, actor=F.REVIEWER,
                                     role="EXPERT_REVIEWER",
                                     body={"decision": bad})


class TestTheServiceEnforcesTheOrder(unittest.TestCase):

    def setUp(self):
        self.service = F.service()

    def _codes(self, callable_, **kwargs):
        try:
            callable_(**kwargs)
        except ExpertReviewError as error:
            return error.code
        return None

    def test_reveal_before_an_expectation_is_refused(self):
        code = self._codes(self.service.reveal, case_id=F.CASE_ID,
                           actor=F.REVIEWER, role="EXPERT_REVIEWER")
        self.assertEqual(code, "EXPERT_REVIEW_EXPECTATION_REQUIRED")

    def test_completion_before_a_reveal_is_refused(self):
        self.service.record_expectation(case_id=F.CASE_ID, actor=F.REVIEWER,
                                        role="EXPERT_REVIEWER",
                                        body=F.EXPECTED_BODY)
        code = self._codes(self.service.complete, case_id=F.CASE_ID,
                           actor=F.REVIEWER, role="EXPERT_REVIEWER",
                           body={"decision": "AGREE"})
        self.assertEqual(code, "EXPERT_REVIEW_REVEAL_REQUIRED")

    def test_completion_from_assigned_is_refused(self):
        code = self._codes(self.service.complete, case_id=F.CASE_ID,
                           actor=F.REVIEWER, role="EXPERT_REVIEWER",
                           body={"decision": "AGREE"})
        self.assertEqual(code, "EXPERT_REVIEW_REVEAL_REQUIRED")

    def test_a_second_expectation_is_refused(self):
        self.service.record_expectation(case_id=F.CASE_ID, actor=F.REVIEWER,
                                        role="EXPERT_REVIEWER",
                                        body=F.EXPECTED_BODY)
        code = self._codes(self.service.record_expectation, case_id=F.CASE_ID,
                           actor=F.REVIEWER, role="EXPERT_REVIEWER",
                           body=F.EXPECTED_BODY)
        self.assertEqual(code, "EXPERT_REVIEW_EXPECTATION_ALREADY_LOCKED")

    def test_a_second_reveal_is_refused_and_recalculates_nothing(self):
        self.service.record_expectation(case_id=F.CASE_ID, actor=F.REVIEWER,
                                        role="EXPERT_REVIEWER",
                                        body=F.EXPECTED_BODY)
        first = self.service.reveal(case_id=F.CASE_ID, actor=F.REVIEWER,
                                    role="EXPERT_REVIEWER")
        code = self._codes(self.service.reveal, case_id=F.CASE_ID,
                           actor=F.REVIEWER, role="EXPERT_REVIEWER")
        self.assertEqual(code, "EXPERT_REVIEW_RESULT_ALREADY_REVEALED")
        stored = self.service.view(case_id=F.CASE_ID, actor=F.REVIEWER,
                                   role="EXPERT_REVIEWER").reveal_record
        self.assertEqual(stored.reveal_hash(), first.reveal_hash())

    def test_a_second_completion_is_refused(self):
        self.service.record_expectation(case_id=F.CASE_ID, actor=F.REVIEWER,
                                        role="EXPERT_REVIEWER",
                                        body=F.EXPECTED_BODY)
        self.service.reveal(case_id=F.CASE_ID, actor=F.REVIEWER,
                            role="EXPERT_REVIEWER")
        self.service.complete(case_id=F.CASE_ID, actor=F.REVIEWER,
                              role="EXPERT_REVIEWER",
                              body={"decision": "AGREE"})
        code = self._codes(self.service.complete, case_id=F.CASE_ID,
                           actor=F.REVIEWER, role="EXPERT_REVIEWER",
                           body={"decision": "DISAGREE"})
        self.assertEqual(code, "EXPERT_REVIEW_ALREADY_COMPLETED")

    def test_nothing_may_follow_completion(self):
        self.service.record_expectation(case_id=F.CASE_ID, actor=F.REVIEWER,
                                        role="EXPERT_REVIEWER",
                                        body=F.EXPECTED_BODY)
        self.service.reveal(case_id=F.CASE_ID, actor=F.REVIEWER,
                            role="EXPERT_REVIEWER")
        self.service.complete(case_id=F.CASE_ID, actor=F.REVIEWER,
                              role="EXPERT_REVIEWER",
                              body={"decision": "PARTIAL"})
        for operation, body in (
                (self.service.record_expectation, F.EXPECTED_BODY),
                (self.service.reveal, {})):
            with self.subTest(operation=operation.__name__):
                code = self._codes(operation, case_id=F.CASE_ID,
                                   actor=F.REVIEWER, role="EXPERT_REVIEWER",
                                   body=body)
                self.assertEqual(code, "EXPERT_REVIEW_ALREADY_COMPLETED")


class TestTheHappyPathRecordsWhatItShould(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.service = F.service()
        cls.expectation = cls.service.record_expectation(
            case_id=F.CASE_ID, actor=F.REVIEWER, role="EXPERT_REVIEWER",
            body=F.EXPECTED_BODY)
        cls.reveal = cls.service.reveal(case_id=F.CASE_ID, actor=F.REVIEWER,
                                        role="EXPERT_REVIEWER")
        cls.completion = cls.service.complete(
            case_id=F.CASE_ID, actor=F.REVIEWER, role="EXPERT_REVIEWER",
            body={"decision": "AGREE",
                  "ratings": {"CLARITY": 4, "TRACEABILITY": 5}})

    def test_the_expectation_is_the_first_revision(self):
        self.assertEqual(self.expectation.revision, 1)

    def test_the_expectation_timestamp_is_server_generated(self):
        """A client-supplied one would let a reviewer backdate a prediction."""
        self.assertIsNotNone(self.expectation.recorded_at.tzinfo)
        self.assertLess(self.expectation.recorded_at, self.reveal.revealed_at)

    def test_the_reveal_pins_the_exact_expectation_revision(self):
        self.assertEqual(self.reveal.expectation_revision_hash,
                         self.expectation.revision_hash())
        self.assertEqual(self.reveal.expectation_revision_id,
                         self.expectation.revision_id)

    def test_the_completion_names_the_reveal_it_followed(self):
        self.assertEqual(self.completion.reveal_id, self.reveal.reveal_id)

    def test_the_ratings_are_bounded_and_named(self):
        self.assertEqual(self.completion.rating_map(),
                         {"CLARITY": 4, "TRACEABILITY": 5})

    def test_the_audit_chain_is_intact(self):
        self.assertEqual(self.service.verify(F.review_id_for()), (True, ""))

    def test_the_chain_records_every_transition_in_order(self):
        chain = self.service._store.audit_chain(F.review_id_for())
        self.assertEqual([event.action.value for event in chain],
                         ["REVIEW_EXPECTATION_RECORDED",
                          "REVIEW_RESULT_REVEALED", "REVIEW_COMPLETED"])
