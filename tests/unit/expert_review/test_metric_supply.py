# -*- coding: utf-8 -*-
"""What WP-21 receives, and the three things it must never receive.

An incomplete review, a post-reveal amendment, and a record about a different
release. The first two are refused at construction; the third refuses the
whole benchmark input rather than being dropped.
"""

from __future__ import annotations

import unittest

from pgx.expert_review.ports import (CompletedReview,
                                     CompletedReviewDecisionPort,
                                     CompletedReviewJudgmentPort,
                                     EligibilityError,
                                     eligible_completed_reviews)
from pgx.expert_review.vocabulary import ReviewState
from pgx.validation.vocabulary import ValidationCaseRole as Role
from tests.fixtures.wp22 import blind_review as F


def _completed(decision: str = "AGREE", *, ratings=None,
               case_id: str = F.CASE_ID, reviewer: str = F.REVIEWER):
    """Run one review to completion and return its four records."""
    store = F.InMemoryReviewStore(
        (F.assignment(case_id=case_id, reviewer=reviewer),))
    service = F.service(store=store)
    expectation = service.record_expectation(
        case_id=case_id, actor=reviewer, role="EXPERT_REVIEWER",
        body=F.EXPECTED_BODY)
    reveal = service.reveal(case_id=case_id, actor=reviewer,
                            role="EXPERT_REVIEWER")
    completion = service.complete(
        case_id=case_id, actor=reviewer, role="EXPERT_REVIEWER",
        body={"decision": decision, "ratings": ratings or {}})
    assignment = store.assignment_for(case_id=case_id, actor=reviewer)
    return CompletedReview(assignment, expectation, reveal, completion), \
        service, store


class TestOnlyCompletedReviewsBecomeEvidence(unittest.TestCase):

    def test_an_assigned_review_cannot_be_wrapped(self):
        store = F.InMemoryReviewStore((F.assignment(),))
        service = F.service(store=store)
        expectation = service.record_expectation(
            case_id=F.CASE_ID, actor=F.REVIEWER, role="EXPERT_REVIEWER",
            body=F.EXPECTED_BODY)
        reveal = service.reveal(case_id=F.CASE_ID, actor=F.REVIEWER,
                                role="EXPERT_REVIEWER")
        assignment = store.assignment_for(case_id=F.CASE_ID,
                                          actor=F.REVIEWER)
        self.assertIs(assignment.state, ReviewState.RESULT_REVEALED)
        with self.assertRaises(EligibilityError):
            CompletedReview(assignment, expectation, reveal, None)  # type: ignore

    def test_a_revealed_but_uncompleted_review_cannot_be_wrapped(self):
        store = F.InMemoryReviewStore((F.assignment(),))
        service = F.service(store=store)
        expectation = service.record_expectation(
            case_id=F.CASE_ID, actor=F.REVIEWER, role="EXPERT_REVIEWER",
            body=F.EXPECTED_BODY)
        reveal = service.reveal(case_id=F.CASE_ID, actor=F.REVIEWER,
                                role="EXPERT_REVIEWER")
        completion = None
        assignment = store.assignment_for(case_id=F.CASE_ID,
                                          actor=F.REVIEWER)
        with self.assertRaises(EligibilityError):
            CompletedReview(assignment, expectation, reveal, completion)  # type: ignore

    def test_a_completed_review_wraps(self):
        review, _, _ = _completed()
        self.assertEqual(review.case_id, F.CASE_ID)
        self.assertEqual(review.role, "EXPERT_HOLDOUT")


class TestOnlyThePinnedExpectationIsSupplied(unittest.TestCase):
    """The heart of the blind protocol, on the consumption side."""

    def test_an_expectation_the_reveal_did_not_pin_is_refused(self):
        review, service, store = _completed()
        import dataclasses
        amended = dataclasses.replace(
            review.expectation, expected_attention_level="LOW")
        with self.assertRaises(EligibilityError) as caught:
            CompletedReview(review.assignment, amended, review.reveal,
                            review.completion)
        self.assertIn("not the revision the reveal pinned",
                      str(caught.exception))

    def test_the_supplied_judgment_is_what_was_locked(self):
        review, _, _ = _completed()
        port = CompletedReviewJudgmentPort(
            [review], pins=review.assignment.pins())
        judgment = port.judgments(role=Role.EXPERT_HOLDOUT)[F.CASE_ID]
        self.assertEqual(judgment.expected_attention_level,
                         F.EXPECTED_BODY["expected_attention_level"])

    def test_the_judgment_names_the_protocol_not_the_reviewer(self):
        """A metric artifact is published; a reviewer's name in one would say
        who judged which case."""
        review, _, _ = _completed()
        port = CompletedReviewJudgmentPort(
            [review], pins=review.assignment.pins())
        judgment = port.judgments(role=Role.EXPERT_HOLDOUT)[F.CASE_ID]
        self.assertIn("blind expert review", judgment.provenance)
        self.assertNotIn(F.REVIEWER, judgment.provenance)


class TestJudgmentsAndDecisionsAreNotInterchangeable(unittest.TestCase):

    def setUp(self):
        self.review, _, _ = _completed(
            "PARTIAL", ratings={"CLARITY": 4, "SAFETY_FRAMING": 5})
        self.pins = self.review.assignment.pins()

    def test_the_judgment_port_supplies_no_decision(self):
        port = CompletedReviewJudgmentPort([self.review], pins=self.pins)
        judgment = port.judgments(role=Role.EXPERT_HOLDOUT)[F.CASE_ID]
        self.assertFalse(hasattr(judgment, "decision"))

    def test_the_decision_port_supplies_no_expectation(self):
        port = CompletedReviewDecisionPort([self.review], pins=self.pins)
        decisions = port.decisions(role=Role.EXPERT_HOLDOUT)
        self.assertEqual(decisions, {F.CASE_ID: "PARTIAL"})
        self.assertNotIn("expected_attention_level", str(decisions))

    def test_ratings_are_separate_from_decisions(self):
        port = CompletedReviewDecisionPort([self.review], pins=self.pins)
        self.assertEqual(port.ratings(role=Role.EXPERT_HOLDOUT),
                         {F.CASE_ID: {"CLARITY": 4, "SAFETY_FRAMING": 5}})

    def test_an_unrated_review_is_absent_from_ratings(self):
        """So the Likert denominator counts ratings, not reviews."""
        unrated, _, _ = _completed("AGREE")
        port = CompletedReviewDecisionPort([unrated],
                                           pins=unrated.assignment.pins())
        self.assertEqual(port.ratings(role=Role.EXPERT_HOLDOUT), {})
        self.assertEqual(len(port.decisions(role=Role.EXPERT_HOLDOUT)), 1)


class TestAMismatchRefusesRatherThanSkips(unittest.TestCase):

    def test_a_release_mismatch_refuses_the_input(self):
        review, _, _ = _completed()
        pins = dict(review.assignment.pins(),
                    release_manifest_hash="sha256:" + "e" * 64)
        with self.assertRaises(EligibilityError) as caught:
            eligible_completed_reviews([review], pins=pins)
        self.assertEqual(caught.exception.details["field"],
                         "release_manifest_hash")

    def test_a_protocol_mismatch_refuses_the_input(self):
        review, _, _ = _completed()
        pins = dict(review.assignment.pins(),
                    protocol_hash="sha256:" + "f" * 64)
        with self.assertRaises(EligibilityError):
            eligible_completed_reviews([review], pins=pins)

    def test_a_case_manifest_mismatch_refuses_the_input(self):
        review, _, _ = _completed()
        pins = dict(review.assignment.pins(),
                    case_manifest_hash="sha256:" + "a" * 64)
        with self.assertRaises(EligibilityError):
            eligible_completed_reviews([review], pins=pins)

    def test_the_refusal_names_the_field_and_the_review(self):
        review, _, _ = _completed()
        pins = dict(review.assignment.pins(),
                    dataset_content_hash="sha256:" + "b" * 64)
        try:
            eligible_completed_reviews([review], pins=pins)
        except EligibilityError as error:
            self.assertEqual(error.details["field"], "dataset_content_hash")
            self.assertIn("review_id", error.details)

    def test_a_role_filter_selects_rather_than_refuses(self):
        """Filtering by role is selection; a pin mismatch is a contradiction.
        Conflating them would either drop real evidence or refuse a run for a
        case that simply belongs to another partition."""
        review, _, _ = _completed()
        selected = eligible_completed_reviews(
            [review], pins=review.assignment.pins(),
            case_role="INTERNAL_HOLDOUT")
        self.assertEqual(selected, ())


class TestTheMetricsComputeFromCompletedReviews(unittest.TestCase):
    """PGX-VAL-011 and 012 against TEST-ONLY completed reviews."""

    def _engine_and_run(self, reviews, pins):
        from pgx.validation.benchmark import BenchmarkEngine
        from pgx.validation.vocabulary import ValidationCaseRole
        from tests.fixtures.wp21 import synthetic_release as S

        class _Observations:
            def observe(self, *, role, plan):
                if role is ValidationCaseRole.EXPERT_HOLDOUT:
                    return S.expert_holdout_observations()
                return ()

        engine = BenchmarkEngine(
            observation_port=_Observations(),
            judgment_port=S.SyntheticJudgmentPort(),
            decision_port=CompletedReviewDecisionPort(reviews, pins=pins))
        run = engine.execute(
            S.plan(roles=(ValidationCaseRole.EXPERT_HOLDOUT,)), cases=[])
        return engine, run

    def _reviews_for(self, decisions, ratings_by_case=None):
        """Completed reviews whose case ids match WP-21's expert fixture."""
        from tests.fixtures.wp21 import synthetic_release as S
        reviews = []
        cases = [item.case_id for item in S.expert_holdout_observations()]
        for case_id, decision in zip(cases, decisions):
            store = F.InMemoryReviewStore(
                (F.assignment(case_id=case_id),))
            service = F.service(store=store)
            expectation = service.record_expectation(
                case_id=case_id, actor=F.REVIEWER, role="EXPERT_REVIEWER",
                body=F.EXPECTED_BODY)
            reveal = service.reveal(case_id=case_id, actor=F.REVIEWER,
                                    role="EXPERT_REVIEWER")
            completion = service.complete(
                case_id=case_id, actor=F.REVIEWER, role="EXPERT_REVIEWER",
                body={"decision": decision,
                      "ratings": (ratings_by_case or {}).get(case_id, {})})
            reviews.append(CompletedReview(
                store.assignment_for(case_id=case_id, actor=F.REVIEWER),
                expectation, reveal, completion))
        return reviews

    def test_the_agreement_distribution_counts_each_decision(self):
        reviews = self._reviews_for(["AGREE", "AGREE", "DISAGREE"])
        pins = reviews[0].assignment.pins()
        engine, run = self._engine_and_run(reviews, pins)
        values = {value.metric_id: value
                  for value in engine.compute(run)["EXPERT_HOLDOUT"]}
        metric = values["PGX-VAL-011"]
        self.assertEqual(metric.status.value, "AVAILABLE")
        self.assertEqual(metric.categories,
                         {"AGREE": 2, "PARTIAL": 0, "DISAGREE": 1})
        self.assertEqual(metric.denominator, 3)

    def test_every_declared_category_appears_even_at_zero(self):
        """A missing category and a zero category read the same and are not."""
        reviews = self._reviews_for(["AGREE", "AGREE", "AGREE"])
        engine, run = self._engine_and_run(
            reviews, reviews[0].assignment.pins())
        metric = {value.metric_id: value
                  for value in engine.compute(run)["EXPERT_HOLDOUT"]
                  }["PGX-VAL-011"]
        self.assertEqual(metric.categories,
                         {"AGREE": 3, "PARTIAL": 0, "DISAGREE": 0})

    def test_the_likert_denominator_counts_ratings_not_reviews(self):
        from tests.fixtures.wp21 import synthetic_release as S
        cases = [item.case_id for item in S.expert_holdout_observations()]
        reviews = self._reviews_for(
            ["AGREE", "PARTIAL", "AGREE"],
            ratings_by_case={cases[0]: {"CLARITY": 4, "TRACEABILITY": 5},
                             cases[1]: {"CLARITY": 3}})
        engine, run = self._engine_and_run(
            reviews, reviews[0].assignment.pins())
        metric = {value.metric_id: value
                  for value in engine.compute(run)["EXPERT_HOLDOUT"]
                  }["PGX-VAL-012"]
        self.assertEqual(metric.status.value, "AVAILABLE")
        # Three ratings across two reviews; the third review rated nothing.
        self.assertEqual(metric.denominator, 3)
        self.assertEqual(metric.categories,
                         {"1": 0, "2": 0, "3": 1, "4": 1, "5": 1})

    def test_a_case_with_no_review_is_not_counted_as_a_disagreement(self):
        """Counting unreviewed observations would put silence in DISAGREE."""
        reviews = self._reviews_for(["AGREE"])
        engine, run = self._engine_and_run(
            reviews, reviews[0].assignment.pins())
        metric = {value.metric_id: value
                  for value in engine.compute(run)["EXPERT_HOLDOUT"]
                  }["PGX-VAL-011"]
        self.assertEqual(metric.denominator, 1)
        self.assertEqual(metric.categories["DISAGREE"], 0)

    def test_no_decision_port_leaves_the_expert_metrics_unavailable(self):
        from pgx.validation.benchmark import BenchmarkEngine
        from pgx.validation.vocabulary import ValidationCaseRole
        from tests.fixtures.wp21 import synthetic_release as S
        engine = BenchmarkEngine(
            observation_port=S.SyntheticObservationPort(),
            judgment_port=S.SyntheticJudgmentPort())
        run = engine.execute(
            S.plan(roles=(ValidationCaseRole.EXPERT_HOLDOUT,)), cases=[])
        values = {value.metric_id: value
                  for value in engine.compute(run)["EXPERT_HOLDOUT"]}
        for metric_id in ("PGX-VAL-011", "PGX-VAL-012"):
            with self.subTest(metric=metric_id):
                self.assertEqual(values[metric_id].status.value, "UNAVAILABLE")
                self.assertEqual(
                    values[metric_id].reason.value,
                    "NO_COMPLETED_EXPERT_REVIEWS")
                self.assertIsNone(values[metric_id].value)

    def test_an_empty_decision_port_is_also_unavailable_not_zero(self):
        engine, run = self._engine_and_run([], {})
        values = {value.metric_id: value
                  for value in engine.compute(run)["EXPERT_HOLDOUT"]}
        self.assertEqual(values["PGX-VAL-011"].status.value, "UNAVAILABLE")
        self.assertEqual(values["PGX-VAL-011"].denominator, 0)
        self.assertIsNone(values["PGX-VAL-011"].value)


class TestThePublicSummaryCarriesNoReviewerContent(unittest.TestCase):

    def test_the_summary_omits_the_expectation_and_the_notes(self):
        review, _, _ = _completed("PARTIAL", ratings={"CLARITY": 3})
        summary = review.to_public_summary()
        payload = str(summary)
        for forbidden in ("expected_attention_level", "reviewer_note",
                          F.REVIEWER, "determinative"):
            with self.subTest(term=forbidden):
                self.assertNotIn(forbidden, payload)

    def test_the_summary_names_the_decision_and_the_dimensions(self):
        review, _, _ = _completed("PARTIAL", ratings={"CLARITY": 3})
        summary = review.to_public_summary()
        self.assertEqual(summary["decision"], "PARTIAL")
        self.assertEqual(summary["rated_dimensions"], ["CLARITY"])
