# -*- coding: utf-8 -*-
"""What leaves the building: aggregates, no leaks, no invented numbers."""

from __future__ import annotations

import json
import unittest

from pgx.application.benchmark_schema import (build_schemas,
                                              validate_dashboard_feed,
                                              validate_failure_paths,
                                              validate_metric_definitions,
                                              validate_validation_report,
                                              validate_wp21_gate_status)
from pgx.validation.benchmark import BenchmarkEngine, DEVELOPMENT_SECTION
from pgx.validation.benchmark_artifacts import (build_real_feed,
                                                build_real_report)
from pgx.validation.benchmark_report import (ReportSafetyError,
                                             assert_public_report_is_safe,
                                             build_failure_path_document,
                                             build_metric_definitions_document,
                                             build_validation_report)
from pgx.validation.dashboard_feed import build_dashboard_feed
from pgx.validation.metric_definitions import METRIC_IDS
from pgx.validation.vocabulary import ValidationCaseRole as Role
from tests.fixtures.wp21 import synthetic_release as S
from tests.unit.benchmark._support import REPO_ROOT, metrics_of


class TestTheRealReportCarriesNoNumber(unittest.TestCase):
    """A16 and A17: the real repository reports no validation percentage."""

    @classmethod
    def setUpClass(cls):
        cls.report = build_real_report(REPO_ROOT)

    def test_it_validates(self):
        self.assertEqual(validate_validation_report(self.report), [])

    def test_every_metric_is_not_executed(self):
        for partition in self.report["partitions"]:
            for metric in partition["metrics"]:
                with self.subTest(role=partition["role"],
                                  metric=metric["metric_id"]):
                    self.assertEqual(metric["status"], "NOT_EXECUTED")
                    self.assertIsNone(metric["value"])
                    self.assertIsNone(metric["denominator"])

    def test_no_percentage_or_rate_string_appears_anywhere(self):
        payload = json.dumps(self.report)
        self.assertNotIn("%", payload)
        self.assertNotIn("0.0000", payload)
        self.assertNotIn("100", payload.replace('"minLength": 100', ""))

    def test_it_reports_no_benchmark_and_no_release(self):
        self.assertFalse(self.report["benchmark_executed"])
        self.assertFalse(self.report["active_release_available"])
        self.assertIsNone(self.report["pinned_release"])
        self.assertIsNone(self.report["plan_hash"])

    def test_the_three_partitions_are_present_and_separate(self):
        sections = [partition["section"]
                    for partition in self.report["partitions"]]
        self.assertEqual(sections, [DEVELOPMENT_SECTION, "INTERNAL_HOLDOUT",
                                    "EXPERT_HOLDOUT"])

    def test_development_is_named_and_flagged(self):
        development = self.report["partitions"][0]
        self.assertEqual(development["section"], "DEVELOPMENT_REGRESSION")
        self.assertFalse(development["is_validation_evidence"])
        self.assertEqual(development["case_count"], 7)

    def test_both_holdout_partitions_report_zero_cases(self):
        for partition in self.report["partitions"][1:]:
            with self.subTest(role=partition["role"]):
                self.assertEqual(partition["case_count"], 0)
                self.assertTrue(partition["is_validation_evidence"])

    def test_there_is_no_combined_figure(self):
        self.assertIsNone(self.report["combined_overall_metric"])

    def test_restricted_case_evidence_is_absent_not_fabricated(self):
        self.assertIsNone(self.report["restricted_case_evidence_artifact"])

    def test_clinical_and_expert_claims_are_false(self):
        self.assertFalse(self.report["clinical_validation_performed"])
        self.assertFalse(self.report["expert_review_performed"])


class TestThePublicReportRefusesRestrictedMaterial(unittest.TestCase):
    """Requirement 21."""

    def test_an_expected_answer_is_refused(self):
        with self.assertRaises(ReportSafetyError):
            assert_public_report_is_safe(
                {"partitions": [{"expected_attention": "HIGH"}]})

    def test_case_observations_are_refused(self):
        with self.assertRaises(ReportSafetyError):
            assert_public_report_is_safe({"observations": [{"case_id": "x"}]})

    def test_a_phenotype_payload_is_refused(self):
        with self.assertRaises(ReportSafetyError):
            assert_public_report_is_safe({"a": {"phenotypes": ["CYP2D6 PM"]}})

    def test_a_filesystem_path_in_a_detail_string_is_refused(self):
        with self.assertRaises(ReportSafetyError):
            assert_public_report_is_safe(
                {"note": "generated from /home/someone/repo/data"})

    def test_a_hostname_field_is_refused(self):
        with self.assertRaises(ReportSafetyError):
            assert_public_report_is_safe({"hostname": "build-box-3"})

    def test_the_real_report_and_feed_pass(self):
        assert_public_report_is_safe(build_real_report(REPO_ROOT))
        assert_public_report_is_safe(build_real_feed(REPO_ROOT))

    def test_no_case_identifier_survives_into_a_computed_report(self):
        """Even with real observations, the report stays aggregate."""
        engine = BenchmarkEngine(
            observation_port=S.SyntheticObservationPort(),
            judgment_port=S.SyntheticJudgmentPort())
        run = engine.execute(S.plan(), cases=[])
        values = engine.compute(run)
        report = build_validation_report(
            plan=run.plan, values_by_role=values,
            case_counts={role: None for role in values},
            observation_counts={role: len(run.for_role(Role(role)))
                                for role in values},
            separation_audit={}, blockers=[], benchmark_executed=True,
            active_release_available=True, run=run)
        payload = json.dumps(report)
        for observation in run.observations:
            with self.subTest(case=observation.case_id):
                self.assertNotIn(observation.case_id, payload)


class TestASyntheticReleaseRendersANumericalTable(unittest.TestCase):
    """A15. The capability, proven where proving it is honest."""

    @classmethod
    def setUpClass(cls):
        engine = BenchmarkEngine(
            observation_port=S.SyntheticObservationPort(),
            judgment_port=S.SyntheticJudgmentPort())
        run = engine.execute(S.plan(), cases=[])
        values = engine.compute(run)
        cls.report = build_validation_report(
            plan=run.plan, values_by_role=values,
            case_counts={"DEVELOPMENT": S.DEVELOPMENT_CASE_COUNT,
                         "INTERNAL_HOLDOUT": S.INTERNAL_CASE_COUNT,
                         "EXPERT_HOLDOUT": S.EXPERT_CASE_COUNT},
            observation_counts={role: len(run.for_role(Role(role)))
                                for role in values},
            separation_audit={}, blockers=[], benchmark_executed=True,
            active_release_available=True, run=run)
        cls.feed = build_dashboard_feed(cls.report)

    def test_the_report_validates(self):
        self.assertEqual(validate_validation_report(self.report), [])

    def test_it_pins_the_synthetic_release(self):
        self.assertEqual(self.report["pinned_release"]["release_public_id"],
                         S.RELEASE_PUBLIC_ID)
        self.assertIsNotNone(self.report["plan_hash"])

    def test_holdout_metrics_carry_real_values(self):
        metrics = {item["metric_id"]: item
                   for item in metrics_of(self.report, "INTERNAL_HOLDOUT")}
        self.assertEqual(metrics["PGX-VAL-001"]["value"], "0.7500")
        self.assertEqual(metrics["PGX-VAL-006"]["value"], "0.9000")

    def test_the_feed_validates_and_carries_the_same_numbers(self):
        self.assertEqual(validate_dashboard_feed(self.feed), [])
        rows = {item["metric_id"]: item
                for item in metrics_of(self.feed, "INTERNAL_HOLDOUT")}
        self.assertTrue(rows["PGX-VAL-001"]["has_number"])
        self.assertEqual(rows["PGX-VAL-001"]["value"], "0.7500")
        self.assertEqual(rows["PGX-VAL-001"]["numerator"],
                         S.INTERNAL_CONCORDANT)

    def test_the_feed_marks_development_as_regression(self):
        development = [section for section in self.feed["sections"]
                       if section["role"] == "DEVELOPMENT"][0]
        self.assertTrue(development["is_development_regression"])
        self.assertFalse(development["is_validation_evidence"])

    def test_even_here_there_is_no_combined_figure(self):
        self.assertIsNone(self.report["combined_overall_metric"])
        self.assertIsNone(self.feed["combined_overall_metric"])

    def test_this_fixture_is_unmistakably_test_only(self):
        payload = json.dumps(self.report)
        self.assertIn("TEST-ONLY", payload)

    def test_no_test_only_identifier_is_in_the_committed_report(self):
        """The proof that the fixture stays out of the real artifact."""
        committed = json.dumps(build_real_report(REPO_ROOT))
        self.assertNotIn("TEST-ONLY", committed)
        self.assertNotIn("SYNTH-", committed)


class TestSchemasRejectDishonestDocuments(unittest.TestCase):
    """Requirement 23."""

    @classmethod
    def setUpClass(cls):
        cls.report = build_real_report(REPO_ROOT)

    def test_all_six_schemas_exist(self):
        self.assertEqual(len(build_schemas()), 6)

    def test_the_definitions_and_catalogue_validate(self):
        self.assertEqual(
            validate_metric_definitions(build_metric_definitions_document()),
            [])
        self.assertEqual(
            validate_failure_paths(build_failure_path_document()), [])

    def test_an_available_metric_with_no_value_is_rejected(self):
        import copy
        broken = copy.deepcopy(self.report)
        broken["partitions"][1]["metrics"][0]["status"] = "AVAILABLE"
        self.assertTrue(validate_validation_report(broken))

    def test_execution_without_a_pinned_release_is_rejected(self):
        import copy
        broken = copy.deepcopy(self.report)
        broken["benchmark_executed"] = True
        self.assertTrue(validate_validation_report(broken))

    def test_a_development_section_claiming_evidence_is_rejected(self):
        import copy
        broken = copy.deepcopy(self.report)
        broken["partitions"][0]["is_validation_evidence"] = True
        self.assertTrue(validate_validation_report(broken))

    def test_a_combined_overall_figure_is_rejected(self):
        import copy
        broken = copy.deepcopy(self.report)
        broken["combined_overall_metric"] = "0.9500"
        self.assertTrue(validate_validation_report(broken))

    def test_a_report_claiming_clinical_validation_is_rejected(self):
        import copy
        broken = copy.deepcopy(self.report)
        broken["clinical_validation_performed"] = True
        self.assertTrue(validate_validation_report(broken))

    def test_a_definitions_document_with_a_threshold_is_rejected(self):
        import copy
        broken = copy.deepcopy(build_metric_definitions_document())
        broken["metrics"][0]["threshold"] = 0.95
        broken["thresholds_declared"] = 1
        self.assertTrue(validate_metric_definitions(broken))

    def test_a_not_executed_metric_with_a_denominator_is_rejected(self):
        import copy
        broken = copy.deepcopy(self.report)
        broken["partitions"][1]["metrics"][0]["denominator"] = 0
        self.assertTrue(validate_validation_report(broken))


class TestTheGateStatusStaysBlocked(unittest.TestCase):
    """A17, A18, A19, A20."""

    @classmethod
    def setUpClass(cls):
        from pgx.validation.benchmark_gate_status import build_wp21_gate_status
        cls.status = build_wp21_gate_status(REPO_ROOT)

    def test_it_validates(self):
        self.assertEqual(validate_wp21_gate_status(self.status), [])

    def test_the_machinery_is_implemented(self):
        self.assertEqual(self.status["implementation_status"], "IMPLEMENTED")
        self.assertTrue(self.status["metric_framework_implemented"])
        self.assertEqual(self.status["metric_definition_count"],
                         len(METRIC_IDS))

    def test_the_gate_is_blocked_and_release_may_not_proceed(self):
        self.assertEqual(self.status["benchmark_gate_status"], "BLOCKED")
        self.assertFalse(self.status["release_may_proceed"])

    def test_the_two_answers_are_allowed_to_disagree(self):
        """Implemented and blocked at once - the whole point of two fields."""
        self.assertEqual(self.status["implementation_status"], "IMPLEMENTED")
        self.assertNotEqual(self.status["benchmark_gate_status"], "PASS")

    def test_clinical_validation_and_expert_review_remain_false(self):
        self.assertFalse(self.status["clinical_validation_performed"])
        self.assertFalse(self.status["expert_review_performed"])

    def test_no_threshold_is_declared(self):
        self.assertEqual(self.status["threshold_count"], 0)

    def test_counts_match_the_repository(self):
        self.assertEqual(self.status["development_case_count"], 7)
        self.assertEqual(self.status["internal_holdout_case_count"], 0)
        self.assertEqual(self.status["expert_holdout_case_count"], 0)
        self.assertEqual(self.status["validation_evidence_case_count"], 0)
        self.assertEqual(self.status["numeric_validation_metric_count"], 0)

    def test_every_blocker_names_an_owner_who_is_not_the_code(self):
        from pgx.validation.benchmark_gate_status import \
            BENCHMARK_BLOCKER_CODES
        self.assertTrue(self.status["blockers"])
        for blocker in self.status["blockers"]:
            with self.subTest(code=blocker["code"]):
                self.assertIn(blocker["code"], BENCHMARK_BLOCKER_CODES)
                self.assertTrue(blocker["owner"])
                self.assertNotEqual(blocker["owner"], "code")

    def test_a_pass_would_need_every_precondition(self):
        import copy
        broken = copy.deepcopy(self.status)
        broken["benchmark_gate_status"] = "PASS"
        self.assertTrue(validate_wp21_gate_status(broken))

    def test_the_marker_paths_are_the_real_files(self):
        markers = self.status["wp21_markers_found"]
        self.assertIn("pgx/validation/benchmark.py", markers)
        self.assertIn("pgx/validation/metrics.py", markers)
