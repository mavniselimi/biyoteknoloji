# -*- coding: utf-8 -*-
"""The three kinds of nothing, and the one kind of zero.

The distinction this module defends: a measured zero, a zero denominator and
an unexecuted benchmark are three different facts and must remain three
different documents. Every failure mode of a validation dashboard starts with
one of them being rendered as another.
"""

from __future__ import annotations

import unittest

from pgx.validation.metric_definitions import (MetricStatus, UnavailableReason,
                                               definitions_by_id)
from pgx.validation.metrics import (MetricError, MetricValue, blocked,
                                    distribution, format_rate,
                                    measured_count, measured_rate,
                                    not_executed, unavailable)

_D = definitions_by_id()
_RATE = _D["PGX-VAL-004"]
_COUNT = _D["PGX-VAL-003"]
_DIST = _D["PGX-VAL-011"]


class TestMeasuredZeroIsARealNumber(unittest.TestCase):
    """Requirement 3: a positive denominator with no hits is a finding."""

    def test_zero_over_eight_is_available_and_zero(self):
        value = measured_rate(_RATE, "INTERNAL_HOLDOUT",
                              numerator=0, denominator=8)
        self.assertIs(value.status, MetricStatus.AVAILABLE)
        self.assertEqual(value.value, "0.0000")
        self.assertEqual(value.denominator, 8)
        self.assertIsNone(value.reason)

    def test_a_zero_count_is_available(self):
        value = measured_count(_COUNT, "INTERNAL_HOLDOUT",
                               numerator=0, denominator=8)
        self.assertIs(value.status, MetricStatus.AVAILABLE)
        self.assertEqual(value.value, "0")


class TestZeroDenominatorIsNotZeroPercent(unittest.TestCase):
    """Requirement 4, and the single most important assertion in WP-21."""

    def test_it_becomes_unavailable_with_a_reason(self):
        value = measured_rate(_RATE, "EXPERT_HOLDOUT",
                              numerator=0, denominator=0)
        self.assertIs(value.status, MetricStatus.UNAVAILABLE)
        self.assertIsNone(value.value)
        self.assertIs(value.reason, UnavailableReason.ZERO_DENOMINATOR)

    def test_it_keeps_the_real_zero_denominator_it_counted(self):
        """Unlike NOT_EXECUTED: something was counted, and it was zero."""
        value = measured_rate(_RATE, "EXPERT_HOLDOUT",
                              numerator=0, denominator=0)
        self.assertEqual(value.denominator, 0)

    def test_formatting_a_zero_denominator_raises(self):
        with self.assertRaises(MetricError):
            format_rate(0, 0)

    def test_an_available_rate_over_zero_cannot_be_constructed(self):
        from pgx.validation.metric_definitions import MetricKind
        with self.assertRaises(MetricError):
            MetricValue(metric_id="PGX-VAL-004", role="EXPERT_HOLDOUT",
                        status=MetricStatus.AVAILABLE, kind=MetricKind.RATE,
                        numerator=0, denominator=0, value="0.0000")


class TestNobodyLookedIsNotWeFoundZero(unittest.TestCase):
    """Requirement 5. NOT_EXECUTED reports null denominators, deliberately."""

    def test_not_executed_carries_no_counts_at_all(self):
        value = not_executed(_RATE, "INTERNAL_HOLDOUT")
        self.assertIs(value.status, MetricStatus.NOT_EXECUTED)
        self.assertIsNone(value.value)
        self.assertIsNone(value.numerator)
        self.assertIsNone(value.denominator)
        self.assertIs(value.reason, UnavailableReason.BENCHMARK_NOT_EXECUTED)

    def test_not_executed_with_a_denominator_is_refused(self):
        from pgx.validation.metric_definitions import MetricKind
        with self.assertRaises(MetricError):
            MetricValue(metric_id="PGX-VAL-004", role="DEVELOPMENT",
                        status=MetricStatus.NOT_EXECUTED,
                        kind=MetricKind.RATE, denominator=0,
                        reason=UnavailableReason.BENCHMARK_NOT_EXECUTED)

    def test_the_three_states_serialise_differently(self):
        measured = measured_rate(_RATE, "INTERNAL_HOLDOUT",
                                 numerator=0, denominator=8).to_json()
        empty = measured_rate(_RATE, "INTERNAL_HOLDOUT",
                              numerator=0, denominator=0).to_json()
        absent = not_executed(_RATE, "INTERNAL_HOLDOUT").to_json()
        self.assertEqual((measured["value"], measured["denominator"]),
                         ("0.0000", 8))
        self.assertEqual((empty["value"], empty["denominator"]), (None, 0))
        self.assertEqual((absent["value"], absent["denominator"]),
                         (None, None))


class TestAValueWithoutAReasonIsRefused(unittest.TestCase):

    def test_unavailable_needs_a_reason_its_definition_lists(self):
        with self.assertRaises(MetricError):
            unavailable(_RATE, "INTERNAL_HOLDOUT",
                        UnavailableReason.NO_COMPLETED_EXPERT_REVIEWS)

    def test_blocked_needs_a_listed_reason_too(self):
        with self.assertRaises(MetricError):
            blocked(_RATE, "INTERNAL_HOLDOUT",
                    UnavailableReason.NO_COMPLETED_EXPERT_REVIEWS)

    def test_a_listed_reason_is_accepted(self):
        value = blocked(_RATE, "INTERNAL_HOLDOUT",
                        UnavailableReason.NO_ACTIVE_RELEASE)
        self.assertIs(value.status, MetricStatus.BLOCKED)
        self.assertIsNone(value.value)


class TestDecimalSerialisationIsDeterministic(unittest.TestCase):
    """No float repr anywhere: the artifact bytes must not vary by platform."""

    def test_known_ratios(self):
        self.assertEqual(format_rate(1, 3), "0.3333")
        self.assertEqual(format_rate(2, 3), "0.6667")
        self.assertEqual(format_rate(1, 8), "0.1250")
        self.assertEqual(format_rate(7, 8), "0.8750")
        self.assertEqual(format_rate(8, 8), "1.0000")

    def test_banker_rounding_does_not_drift_upward(self):
        self.assertEqual(format_rate(1, 2, places=0), "0")
        self.assertEqual(format_rate(3, 2 * 3, places=0), "0")

    def test_a_rate_above_one_is_refused(self):
        with self.assertRaises(MetricError):
            format_rate(9, 8)

    def test_values_are_strings_not_floats(self):
        value = measured_rate(_RATE, "INTERNAL_HOLDOUT",
                              numerator=1, denominator=3)
        self.assertIsInstance(value.value, str)


class TestDistributionsKeepEveryCategory(unittest.TestCase):

    def test_a_missing_category_is_filled_with_zero(self):
        value = distribution(_DIST, "EXPERT_HOLDOUT",
                             counts={"AGREE": 3, "DISAGREE": 1},
                             denominator=4)
        self.assertEqual(value.categories,
                         {"AGREE": 3, "PARTIAL": 0, "DISAGREE": 1})

    def test_an_undeclared_category_is_refused(self):
        with self.assertRaises(MetricError):
            distribution(_DIST, "EXPERT_HOLDOUT", counts={"MAYBE": 1},
                         denominator=1)

    def test_counts_must_sum_to_the_denominator(self):
        with self.assertRaises(MetricError):
            distribution(_DIST, "EXPERT_HOLDOUT", counts={"AGREE": 2},
                         denominator=5)

    def test_a_zero_denominator_distribution_is_unavailable(self):
        value = distribution(_DIST, "EXPERT_HOLDOUT", counts={},
                             denominator=0)
        self.assertIs(value.status, MetricStatus.UNAVAILABLE)


class TestEvidenceFlagFollowsRoleAndDefinition(unittest.TestCase):

    def test_a_development_value_is_never_evidence(self):
        value = measured_count(_D["PGX-VAL-007"], "DEVELOPMENT",
                               numerator=7, denominator=7)
        self.assertFalse(value.is_validation_evidence)

    def test_a_regression_metric_is_not_evidence_even_on_a_holdout(self):
        value = measured_count(_D["PGX-VAL-007"], "INTERNAL_HOLDOUT",
                               numerator=7, denominator=8)
        self.assertFalse(value.is_validation_evidence)

    def test_an_evidence_metric_on_a_holdout_is_evidence(self):
        value = measured_rate(_D["PGX-VAL-001"], "INTERNAL_HOLDOUT",
                              numerator=6, denominator=8)
        self.assertTrue(value.is_validation_evidence)
