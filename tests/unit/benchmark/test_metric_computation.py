# -*- coding: utf-8 -*-
"""The arithmetic, proven against a TEST-ONLY synthetic release.

The numbers here come from ``tests/fixtures/wp21/synthetic_release.py`` and
none of them describe this system. What they prove is narrower and still
worth proving: given real observations under a pinned release, the engine
divides the right things by the right things, keeps the partitions apart, and
never lets a development case reach a validation denominator.
"""

from __future__ import annotations

import unittest

from pgx.validation.benchmark import BenchmarkEngine
from pgx.validation.metric_definitions import MetricStatus, UnavailableReason
from pgx.validation.vocabulary import ValidationCaseRole as Role
from tests.fixtures.wp21 import synthetic_release as S


def _values(engine, run):
    computed = engine.compute(run)
    return {role: {value.metric_id: value for value in values}
            for role, values in computed.items()}


class _Computed(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.engine = BenchmarkEngine(
            observation_port=S.SyntheticObservationPort(),
            judgment_port=S.SyntheticJudgmentPort())
        # Not ``cls.run``: TestCase.run is the method unittest calls.
        cls.bench = cls.engine.execute(S.plan(), cases=[])
        cls.values = _values(cls.engine, cls.bench)


class TestNumeratorAndDenominatorMath(_Computed):
    """Requirement 2, against numbers the fixture states explicitly."""

    def test_concordance_counts_only_judged_observations(self):
        value = self.values["INTERNAL_HOLDOUT"]["PGX-VAL-001"]
        self.assertIs(value.status, MetricStatus.AVAILABLE)
        self.assertEqual(value.numerator, S.INTERNAL_CONCORDANT)
        self.assertEqual(value.denominator, S.INTERNAL_CASE_COUNT)
        self.assertEqual(value.value, "0.7500")

    def test_false_reassurance_needs_both_halves(self):
        """Reassuring level AND incomplete coverage. LOW on FULL is fine."""
        value = self.values["INTERNAL_HOLDOUT"]["PGX-VAL-003"]
        self.assertEqual(value.numerator, S.INTERNAL_FALSE_REASSURANCE)
        self.assertEqual(value.denominator, S.INTERNAL_CASE_COUNT)

    def test_evidence_traceability_divides_findings_not_cases(self):
        value = self.values["INTERNAL_HOLDOUT"]["PGX-VAL-005"]
        self.assertEqual(value.numerator, S.INTERNAL_TRACEABLE_FINDINGS)
        self.assertEqual(value.denominator, S.INTERNAL_FINDINGS)
        self.assertGreater(value.denominator, S.INTERNAL_CASE_COUNT)

    def test_repeatability_counts_agreeing_repeats(self):
        value = self.values["INTERNAL_HOLDOUT"]["PGX-VAL-007"]
        self.assertEqual(value.numerator, S.INTERNAL_REPEAT_AGREEMENTS)
        self.assertEqual(value.denominator, S.INTERNAL_CASE_COUNT)

    def test_the_rate_and_its_count_agree(self):
        count = self.values["INTERNAL_HOLDOUT"]["PGX-VAL-003"]
        rate = self.values["INTERNAL_HOLDOUT"]["PGX-VAL-004"]
        self.assertEqual(count.numerator, rate.numerator)
        self.assertEqual(count.denominator, rate.denominator)
        self.assertEqual(rate.value, "0.1250")

    def test_failure_path_denominator_is_the_catalogue(self):
        from pgx.validation.metric_definitions import FAILURE_PATH_CATALOGUE
        value = self.values["INTERNAL_HOLDOUT"]["PGX-VAL-014"]
        self.assertEqual(value.denominator, len(FAILURE_PATH_CATALOGUE))
        self.assertLess(value.numerator, value.denominator)


class TestPartitionsStaySeparate(_Computed):
    """Requirements 6 and 7."""

    def test_development_produces_no_evidence_metric(self):
        for metric_id in ("PGX-VAL-001", "PGX-VAL-003", "PGX-VAL-009"):
            with self.subTest(metric=metric_id):
                value = self.values["DEVELOPMENT"][metric_id]
                self.assertIsNot(value.status, MetricStatus.AVAILABLE)
                self.assertIsNone(value.value)

    def test_every_development_value_is_marked_not_evidence(self):
        for value in self.values["DEVELOPMENT"].values():
            with self.subTest(metric=value.metric_id):
                self.assertFalse(value.is_validation_evidence)

    def test_development_still_yields_regression_signal(self):
        """Excluding it from evidence must not make it useless."""
        value = self.values["DEVELOPMENT"]["PGX-VAL-007"]
        self.assertIs(value.status, MetricStatus.AVAILABLE)
        self.assertEqual(value.denominator, S.DEVELOPMENT_CASE_COUNT)

    def test_the_two_holdout_roles_are_computed_independently(self):
        internal = self.values["INTERNAL_HOLDOUT"]["PGX-VAL-001"]
        expert = self.values["EXPERT_HOLDOUT"]["PGX-VAL-001"]
        self.assertEqual(internal.denominator, S.INTERNAL_CASE_COUNT)
        self.assertEqual(expert.denominator, S.EXPERT_CASE_COUNT)
        self.assertNotEqual(internal.value, expert.value)

    def test_pooling_would_have_changed_the_answer(self):
        """Why there is no pooled figure, demonstrated rather than asserted.

        Pooling internal and expert concordance gives 8/11, which is neither
        partition's result. A reader shown only that number could not tell
        which partition carried it.
        """
        internal = self.values["INTERNAL_HOLDOUT"]["PGX-VAL-001"]
        expert = self.values["EXPERT_HOLDOUT"]["PGX-VAL-001"]
        pooled = ((internal.numerator + expert.numerator)
                  / (internal.denominator + expert.denominator))
        self.assertNotAlmostEqual(pooled, float(internal.value), places=3)
        self.assertNotAlmostEqual(pooled, float(expert.value), places=3)

    def test_no_combining_operation_exists(self):
        computed = self.engine.compute(self.bench)
        self.assertEqual(set(computed), {"DEVELOPMENT", "INTERNAL_HOLDOUT",
                                         "EXPERT_HOLDOUT"})
        self.assertNotIn("OVERALL", computed)
        self.assertNotIn("ALL", computed)


class TestExpertMetricsWaitForCompletedReviews(_Computed):
    """Requirements 20 and 12 of the acceptance list.

    The class was ``TestExpertMetricsWaitForWp22``, and the reason code was
    ``EXPERT_REVIEW_NOT_IMPLEMENTED``. WP-22 shipped, so both said something
    false: the module exists. What these metrics are actually waiting for is
    a completed review, which is a person's act and not a package - so the
    reason is now ``NO_COMPLETED_EXPERT_REVIEWS`` and the wait continues.
    """

    def test_agreement_distribution_is_unavailable(self):
        value = self.values["EXPERT_HOLDOUT"]["PGX-VAL-011"]
        self.assertIs(value.status, MetricStatus.UNAVAILABLE)
        self.assertIs(value.reason,
                      UnavailableReason.NO_COMPLETED_EXPERT_REVIEWS)

    def test_likert_is_unavailable_too(self):
        value = self.values["EXPERT_HOLDOUT"]["PGX-VAL-012"]
        self.assertIs(value.status, MetricStatus.UNAVAILABLE)

    def test_a_synthetic_reference_judgment_does_not_substitute(self):
        """Judgments exist in the fixture; expert *decisions* still do not.

        The two are different inputs and conflating them would let a curator's
        expected answer be reported as an expert's opinion.
        """
        self.assertTrue(S.expert_judgments())
        self.assertIsNot(self.values["EXPERT_HOLDOUT"]["PGX-VAL-011"].status,
                         MetricStatus.AVAILABLE)


class TestWithoutJudgmentsTheAnswerIsNotZero(unittest.TestCase):
    """Requirement 5, at the metric level rather than the value level."""

    def setUp(self):
        engine = BenchmarkEngine(
            observation_port=S.SyntheticObservationPort(),
            judgment_port=S.SyntheticJudgmentPort(include_expert=False))
        run = engine.execute(S.plan(roles=(Role.EXPERT_HOLDOUT,)), cases=[])
        self.values = _values(engine, run)["EXPERT_HOLDOUT"]

    def test_concordance_reports_no_reference_judgment(self):
        value = self.values["PGX-VAL-001"]
        self.assertIs(value.status, MetricStatus.UNAVAILABLE)
        self.assertIs(value.reason, UnavailableReason.NO_REFERENCE_JUDGMENT)
        self.assertIsNone(value.value)

    def test_holdout_pass_reports_the_same(self):
        self.assertIs(self.values["PGX-VAL-009"].reason,
                      UnavailableReason.NO_REFERENCE_JUDGMENT)

    def test_metrics_needing_no_judgment_still_compute(self):
        """Otherwise a missing answer key would silence real findings."""
        self.assertIs(self.values["PGX-VAL-003"].status,
                      MetricStatus.AVAILABLE)


class TestFalseReassuranceIsNotInheritedFromWp20(unittest.TestCase):
    """Requirement 18. The most tempting substitution in the repository."""

    def test_the_metric_reads_observations_and_nothing_else(self):
        import inspect
        from pgx.validation import benchmark
        source = inspect.getsource(benchmark.BenchmarkEngine._false_reassurance)
        for forbidden in ("safety", "negative_control", "wp20", "detector"):
            with self.subTest(term=forbidden):
                self.assertNotIn(forbidden, source.lower())

    def test_the_validation_package_never_imports_the_safety_gate(self):
        import ast
        import os
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))), "pgx", "validation")
        for name in sorted(os.listdir(root)):
            if not name.endswith(".py"):
                continue
            with self.subTest(module=name):
                with open(os.path.join(root, name), "r",
                          encoding="utf-8") as handle:
                    tree = ast.parse(handle.read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        self.assertFalse(
                            node.module.startswith("pgx.safety"),
                            "%s imports %s" % (name, node.module))

    def test_a_zero_here_is_measured_not_borrowed(self):
        engine = BenchmarkEngine(
            observation_port=S.SyntheticObservationPort(),
            judgment_port=S.SyntheticJudgmentPort())
        run = engine.execute(S.plan(roles=(Role.EXPERT_HOLDOUT,)), cases=[])
        value = _values(engine, run)["EXPERT_HOLDOUT"]["PGX-VAL-003"]
        # Zero, and its denominator says over what.
        self.assertEqual(value.numerator, 0)
        self.assertEqual(value.denominator, S.EXPERT_CASE_COUNT)


class TestAnEmptyRoleIsNotAZero(unittest.TestCase):

    def test_a_role_with_no_observation_reports_unavailable(self):
        port = S.SyntheticObservationPort(overrides={
            Role.INTERNAL_HOLDOUT.value: ()})
        engine = BenchmarkEngine(observation_port=port,
                                 judgment_port=S.SyntheticJudgmentPort())
        run = engine.execute(S.plan(roles=(Role.INTERNAL_HOLDOUT,)), cases=[])
        values = _values(engine, run)["INTERNAL_HOLDOUT"]
        for metric_id, value in sorted(values.items()):
            with self.subTest(metric=metric_id):
                self.assertIsNot(value.status, MetricStatus.AVAILABLE)
                self.assertIsNone(value.value)
