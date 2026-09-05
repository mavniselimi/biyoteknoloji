# -*- coding: utf-8 -*-
"""No system result exists anywhere until the expectation is locked.

The assertions here scan the serialised object, not the fields a caller
happens to read. A hidden value is still disclosure - a reviewer who opens the
JSON, or the page source, has seen it.
"""

from __future__ import annotations

import json
import unittest

from pgx.expert_review.service import ReviewView
from tests.fixtures.wp22 import blind_review as F

#: Every string that would tell a blinded reviewer what the system concluded.
_RESULT_MARKERS = ("attention_level", "coverage_status", "coverage_reason",
                   "firing_rule_id", "finding_count",
                   "traceable_finding_count", "output_hash", "result")
_RESULT_VALUES = ("HIGH", "FULL", "TEST-ONLY-RULE-1", F.RESULT_OUTPUT_HASH)


class TestThePreRevealViewHasNowhereToPutAResult(unittest.TestCase):
    """A structural claim, not a filtering one.

    ``ReviewView.result`` returns ``None`` while ``_reveal`` is unset, and
    ``to_json`` omits the key entirely. There is no code path that populates
    it without a ``RevealRecord``, which only the reveal operation creates.
    """

    def setUp(self):
        self.service = F.service()

    def test_the_assigned_view_carries_no_result_key(self):
        view = self.service.view(case_id=F.CASE_ID, actor=F.REVIEWER,
                                 role="EXPERT_REVIEWER")
        payload = view.to_json()
        self.assertTrue(view.blinded)
        self.assertNotIn("result", payload)
        self.assertIsNone(view.result)

    def test_the_expectation_recorded_view_still_carries_none(self):
        self.service.record_expectation(case_id=F.CASE_ID, actor=F.REVIEWER,
                                        role="EXPERT_REVIEWER",
                                        body=F.EXPECTED_BODY)
        view = self.service.view(case_id=F.CASE_ID, actor=F.REVIEWER,
                                 role="EXPERT_REVIEWER")
        self.assertTrue(view.blinded)
        self.assertNotIn("result", view.to_json())

    def test_no_result_marker_appears_in_the_serialised_pre_reveal_view(self):
        for stage in ("assigned", "expectation"):
            if stage == "expectation":
                self.service.record_expectation(
                    case_id=F.CASE_ID, actor=F.REVIEWER,
                    role="EXPERT_REVIEWER", body=F.EXPECTED_BODY)
            payload = json.dumps(self.service.view(
                case_id=F.CASE_ID, actor=F.REVIEWER,
                role="EXPERT_REVIEWER").to_json())
            for marker in _RESULT_MARKERS:
                with self.subTest(stage=stage, marker=marker):
                    self.assertNotIn('"%s"' % marker, payload)
            for value in _RESULT_VALUES:
                with self.subTest(stage=stage, value=value):
                    self.assertNotIn(value, payload)

    def test_the_expectation_the_reviewer_wrote_is_not_a_result(self):
        """The expectation says HIGH/FULL too. The view must not echo it in a
        shape a template could mistake for the system's answer."""
        self.service.record_expectation(case_id=F.CASE_ID, actor=F.REVIEWER,
                                        role="EXPERT_REVIEWER",
                                        body=F.EXPECTED_BODY)
        payload = self.service.view(case_id=F.CASE_ID, actor=F.REVIEWER,
                                    role="EXPERT_REVIEWER").to_json()
        self.assertTrue(payload["expectation_recorded"])
        self.assertNotIn("expected_attention_level", payload)


class TestTheResultPortIsNotConsultedBeforeReveal(unittest.TestCase):
    """The strongest form of the guarantee: the result is never fetched.

    A view that fetched the result and then filtered it would leak on the
    first logging statement, exception traceback or debugging change. This
    never asks.
    """

    def setUp(self):
        self.store = F.InMemoryReviewStore((F.assignment(),))
        self.port = F.StaticResultPort()
        from pgx.expert_review.service import ExpertReviewService
        self.service = ExpertReviewService(
            protocol=F.approved_protocol(), store=self.store,
            result_port=self.port, clock=F.CountingClock(),
            id_factory=F.SequentialIds())

    def test_viewing_an_assigned_review_never_asks_for_the_result(self):
        self.service.view(case_id=F.CASE_ID, actor=F.REVIEWER,
                          role="EXPERT_REVIEWER")
        self.assertEqual(self.port.call_count, 0)

    def test_recording_an_expectation_never_asks_for_the_result(self):
        self.service.record_expectation(case_id=F.CASE_ID, actor=F.REVIEWER,
                                        role="EXPERT_REVIEWER",
                                        body=F.EXPECTED_BODY)
        self.assertEqual(self.port.call_count, 0)

    def test_the_result_is_fetched_exactly_once_at_reveal(self):
        self.service.record_expectation(case_id=F.CASE_ID, actor=F.REVIEWER,
                                        role="EXPERT_REVIEWER",
                                        body=F.EXPECTED_BODY)
        self.service.reveal(case_id=F.CASE_ID, actor=F.REVIEWER,
                            role="EXPERT_REVIEWER")
        self.assertEqual(self.port.call_count, 1)

    def test_a_refused_second_reveal_does_not_recalculate(self):
        self.service.record_expectation(case_id=F.CASE_ID, actor=F.REVIEWER,
                                        role="EXPERT_REVIEWER",
                                        body=F.EXPECTED_BODY)
        self.service.reveal(case_id=F.CASE_ID, actor=F.REVIEWER,
                            role="EXPERT_REVIEWER")
        try:
            self.service.reveal(case_id=F.CASE_ID, actor=F.REVIEWER,
                                role="EXPERT_REVIEWER")
        except Exception:
            pass
        self.assertEqual(self.port.call_count, 1)


class TestAfterRevealTheResultIsAvailable(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.service = F.service()
        cls.service.record_expectation(case_id=F.CASE_ID, actor=F.REVIEWER,
                                       role="EXPERT_REVIEWER",
                                       body=F.EXPECTED_BODY)
        cls.reveal = cls.service.reveal(case_id=F.CASE_ID, actor=F.REVIEWER,
                                        role="EXPERT_REVIEWER")
        cls.view = cls.service.view(case_id=F.CASE_ID, actor=F.REVIEWER,
                                    role="EXPERT_REVIEWER")

    def test_the_view_is_no_longer_blinded(self):
        self.assertFalse(self.view.blinded)

    def test_the_result_is_present_and_complete(self):
        result = self.view.result
        self.assertEqual(result["attention_level"], "HIGH")
        self.assertEqual(result["coverage_status"], "FULL")
        self.assertEqual(result["output_hash"], F.RESULT_OUTPUT_HASH)

    def test_the_locked_expectation_stands_beside_it(self):
        payload = self.view.to_json()
        self.assertIn("result", payload)
        self.assertEqual(payload["expectation_revision_hash"],
                         self.reveal.expectation_revision_hash)


class TestTheRevealPinsWhatItShowed(unittest.TestCase):

    def test_a_release_change_cannot_reach_an_in_progress_review(self):
        """The assignment holds the pins; nothing re-reads a pointer."""
        store = F.InMemoryReviewStore((F.assignment(),))
        moving = F.StaticResultPort(dict(
            F.SYSTEM_RESULT,
            release_manifest_hash="sha256:" + "b" * 64))
        from pgx.expert_review.errors import ExpertReviewError
        from pgx.expert_review.service import ExpertReviewService
        service = ExpertReviewService(
            protocol=F.approved_protocol(), store=store, result_port=moving,
            clock=F.CountingClock(), id_factory=F.SequentialIds())
        service.record_expectation(case_id=F.CASE_ID, actor=F.REVIEWER,
                                   role="EXPERT_REVIEWER",
                                   body=F.EXPECTED_BODY)
        with self.assertRaises(ExpertReviewError) as caught:
            service.reveal(case_id=F.CASE_ID, actor=F.REVIEWER,
                           role="EXPERT_REVIEWER")
        self.assertEqual(caught.exception.code,
                         "EXPERT_REVIEW_RELEASE_MISMATCH")
        self.assertIsNone(store.reveal(F.review_id_for()))

    def test_a_case_manifest_change_refuses_the_reveal(self):
        from pgx.expert_review.errors import ExpertReviewError
        from pgx.expert_review.service import ExpertReviewService
        store = F.InMemoryReviewStore((F.assignment(),))
        service = ExpertReviewService(
            protocol=F.approved_protocol(), store=store,
            result_port=F.StaticResultPort(dict(
                F.SYSTEM_RESULT, case_manifest_hash="sha256:" + "c" * 64)),
            clock=F.CountingClock(), id_factory=F.SequentialIds())
        service.record_expectation(case_id=F.CASE_ID, actor=F.REVIEWER,
                                   role="EXPERT_REVIEWER",
                                   body=F.EXPECTED_BODY)
        with self.assertRaises(ExpertReviewError) as caught:
            service.reveal(case_id=F.CASE_ID, actor=F.REVIEWER,
                           role="EXPERT_REVIEWER")
        self.assertEqual(caught.exception.code,
                         "EXPERT_REVIEW_CASE_MANIFEST_MISMATCH")

    def test_a_protocol_change_refuses_every_operation(self):
        """A review begun under one protocol cannot finish under another.

        The service runs under a *different approved* protocol than the one
        the assignment pinned. Amending an approved protocol would instead
        make it unapproved - correctly, since a document edited after signing
        has not been signed - so testing the mismatch path needs a second
        genuinely-approved protocol rather than a tampered first one.
        """
        from pgx.expert_review.errors import ExpertReviewError
        from pgx.expert_review.service import ExpertReviewService
        store = F.InMemoryReviewStore((F.assignment(),))
        other = F.amended_approved_protocol()
        self.assertTrue(other.is_approved)
        service = ExpertReviewService(
            protocol=other, store=store,
            result_port=F.StaticResultPort(), clock=F.CountingClock(),
            id_factory=F.SequentialIds())
        with self.assertRaises(ExpertReviewError) as caught:
            service.record_expectation(case_id=F.CASE_ID, actor=F.REVIEWER,
                                       role="EXPERT_REVIEWER",
                                       body=F.EXPECTED_BODY)
        self.assertEqual(caught.exception.code,
                         "EXPERT_REVIEW_PROTOCOL_MISMATCH")

    def test_amending_an_approved_protocol_makes_it_unapproved(self):
        """The other half of the same guarantee, stated directly."""
        approved = F.approved_protocol()
        self.assertTrue(approved.is_approved)
        from dataclasses import replace
        amended = replace(approved, document_digest="sha256:" + "d" * 64)
        self.assertFalse(amended.is_approved)
