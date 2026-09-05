# -*- coding: utf-8 -*-
"""SAFETY-INV-001: absence must never read as reassurance.

The safe control is the **shipped aggregator**, so a regression in
``pgx.engine.risk_models.aggregate_attention`` fails this test - not only a
mutant would.

The two negative controls are the legacy behaviour, restored: absence mapped to
``LOW`` (``LEGACY-BUG-002``, rendered as *"Düşük / uyarı yok"*), and
``NOT_ASSESSED`` treated as a level low enough to fall through to a reassuring
answer. Both go through the same evaluator as the real aggregator.
"""

from __future__ import annotations

import unittest

from pgx.domain.enums import AttentionLevel, CoverageStatus
from pgx.safety.controls import controls_for
from pgx.safety.evaluators import evaluate_absence_never_reassures
from pgx.safety.vocabulary import InvariantId
from tests.fixtures.wp20 import unsafe_engine
from tests.unit.safety._support import (attention_values, coverage_values,
                                        full_coverage, production_aggregator)


def _evaluate(aggregator):
    return evaluate_absence_never_reassures(
        aggregator, coverage_values(), attention_values(), full_coverage())


class TestTheShippedAggregatorIsSafe(unittest.TestCase):

    def setUp(self):
        self.verdict = _evaluate(production_aggregator())

    def test_it_is_compliant(self):
        self.assertTrue(self.verdict.compliant, self.verdict.violations)

    def test_something_was_actually_examined(self):
        """A verdict from an empty sweep is not a pass."""
        self.assertTrue(self.verdict.is_meaningful)
        self.assertGreaterEqual(self.verdict.examined, len(CoverageStatus))

    def test_no_absence_path_is_reassuring(self):
        """The property, asserted directly as well as through the evaluator."""
        aggregate = production_aggregator()
        for coverage in CoverageStatus:
            with self.subTest(coverage=coverage.value):
                answer = aggregate([], coverage=coverage)
                if coverage is CoverageStatus.FULL:
                    self.assertIs(answer, AttentionLevel.NO_ACTIVE_ATTENTION)
                else:
                    self.assertIs(answer, AttentionLevel.NOT_ASSESSED)

    def test_no_active_attention_is_reachable_from_full_coverage_only(self):
        aggregate = production_aggregator()
        reachable = [coverage for coverage in CoverageStatus
                     if aggregate([], coverage=coverage)
                     is AttentionLevel.NO_ACTIVE_ATTENTION]
        self.assertEqual(reachable, [CoverageStatus.FULL])

    def test_a_real_finding_survives_incomplete_coverage(self):
        """Incomplete coverage is reported as coverage, never by lowering the
        level - the other half of the same contract."""
        aggregate = production_aggregator()
        for coverage in CoverageStatus:
            with self.subTest(coverage=coverage.value):
                self.assertIs(aggregate([AttentionLevel.HIGH],
                                        coverage=coverage),
                              AttentionLevel.HIGH)


class TestEveryNegativeControlIsDetected(unittest.TestCase):
    """The half that proves the detector works."""

    def test_each_unsafe_aggregator_is_rejected(self):
        for control in controls_for(InvariantId.INV_001):
            with self.subTest(control=control.control_id):
                subject = unsafe_engine.UNSAFE_SUBJECTS[control.control_id]
                verdict = _evaluate(subject)
                self.assertFalse(
                    verdict.compliant,
                    "%s was NOT detected; the detector accepts the unsafe "
                    "state it exists to reject" % control.control_id)
                self.assertEqual(verdict.refusal_code,
                                 control.expected_refusal_code)
                self.assertTrue(verdict.violations)

    def test_the_catalogue_and_the_fixtures_agree(self):
        declared = {c.control_id for c in controls_for(InvariantId.INV_001)}
        self.assertEqual(declared, set(unsafe_engine.UNSAFE_SUBJECTS))

    def test_the_legacy_defect_is_the_one_reproduced(self):
        """NC-INV-001-ABSENCE-MAPPED-TO-LOW is LEGACY-BUG-002, not a new idea."""
        control = {c.control_id: c
                   for c in controls_for(InvariantId.INV_001)}
        self.assertEqual(
            control["NC-INV-001-ABSENCE-MAPPED-TO-LOW"].legacy_bug,
            "LEGACY-BUG-002")

    def test_the_unsafe_aggregator_really_does_return_low(self):
        """Naming the mutant is not enough; it has to be unsafe."""
        answer = unsafe_engine.absence_mapped_to_low(
            [], coverage=CoverageStatus.UNSUPPORTED_DRUG)
        self.assertIs(answer, AttentionLevel.LOW)
