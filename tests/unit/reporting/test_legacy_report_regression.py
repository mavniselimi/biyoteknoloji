# -*- coding: utf-8 -*-
"""The legacy report comparison, and the claims it is allowed to make.

The harness reads two legacy programs as source and states what WP-15 does
instead. What these tests check is that it reads the files that are actually
there, that it calls nothing, and that it describes no legacy value as
validated or approved.
"""

from __future__ import annotations

import json
import os
import unittest

from pgx.reporting.legacy_regression import (LEGACY_REPORT_REGRESSION_VERSION,
                                             NOT_PORTED,
                                             PORTED_LAYOUT_CONCEPTS,
                                             REPORT_EXPECTED_DIFFERENCES,
                                             build_report_regression_report,
                                             legacy_report_difference_allowlist)
from tests.unit.reporting._support import REPO_ROOT, source

REPORT_PATH = os.path.join(REPO_ROOT, "data", "migration", "wp15",
                           "report-regression-report.json")


class TestTheComparison(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.report = build_report_regression_report(REPO_ROOT)

    def test_it_names_its_version(self):
        self.assertEqual(self.report["report_version"],
                         LEGACY_REPORT_REGRESSION_VERSION)

    def test_it_is_deterministic(self):
        self.assertEqual(build_report_regression_report(REPO_ROOT)[
            "content_hash"], self.report["content_hash"])

    def test_it_carries_no_timestamp_or_path(self):
        text = json.dumps(self.report)
        for fragment in ("/tmp/", "/home/", "/sessions/", "created_at",
                         "generated_at"):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, text)

    def test_every_expected_difference_is_observed(self):
        self.assertEqual(self.report["uncovered_expected_differences"], [])
        for entry in REPORT_EXPECTED_DIFFERENCES:
            with self.subTest(difference=entry.difference_id):
                self.assertGreater(
                    self.report["difference_coverage"][entry.difference_id],
                    0)

    def test_no_unexpected_difference_is_present(self):
        self.assertEqual(self.report["unexpected_difference_count"], 0)

    def test_it_finds_the_legacy_absence_label(self):
        case = [item for item in self.report["cases"]
                if item["case_id"] == "RENDERER-absence-label"][0]
        self.assertTrue(case["legacy_behaviour_present"])
        self.assertTrue(case["legacy_rendered_as_reassuring"])
        self.assertEqual(case["expected_difference_id"],
                         "REPORT-ABSENCE-NOT-RENDERED-AS-LOW")

    def test_it_records_that_the_legacy_path_has_no_coverage_concept(self):
        case = [item for item in self.report["cases"]
                if item["case_id"] == "RENDERER-coverage-absent"][0]
        self.assertTrue(case["legacy_behaviour_present"])
        self.assertIn("cannot be upgraded", case["status_loss"])

    def test_it_records_the_status_loss_rather_than_repairing_it(self):
        case = [item for item in self.report["cases"]
                if item["case_id"] == "RENDERER-coverage-absent"][0]
        for lost in ("coverage", "reason codes", "rule identity",
                     "evidence references"):
            with self.subTest(lost=lost):
                self.assertIn(lost, case["status_loss"])

    def test_it_finds_the_legacy_free_prose_fields(self):
        case = [item for item in self.report["cases"]
                if item["case_id"] == "RENDERER-free-prose"][0]
        self.assertIn("plain_language", case["legacy_fields"])
        self.assertIn("risk_meaning", case["legacy_fields"])


class TestNoModelIsCalled(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.report = build_report_regression_report(REPO_ROOT)

    def test_the_report_says_no_model_was_called(self):
        self.assertEqual(self.report["live_model_calls"], 0)
        self.assertFalse(self.report["network_used"])

    def test_no_wp15_module_imports_the_legacy_generator(self):
        case = [item for item in self.report["cases"]
                if item["case_id"] == "GENERATOR-model-call"][0]
        self.assertEqual(case["v2_modules_importing_the_legacy_generator"],
                         [])

    def test_the_harness_itself_imports_nothing_from_the_generator(self):
        """Checked against the import list, not the text: the module names
        the generator in order to describe it, and a text scan would fail on
        the description."""
        from tests.unit.reporting._support import imports_of
        modules = imports_of(os.path.join(REPO_ROOT, "pgx", "reporting",
                                          "legacy_regression.py"))
        self.assertNotIn("gemini_report_generator", modules)
        self.assertNotIn("risk_engine", modules)

    def test_the_recorded_observation_was_produced_offline(self):
        case = [item for item in self.report["cases"]
                if item["case_id"] == "GENERATOR-recorded-observation"][0]
        self.assertFalse(case["api_call_made"])
        self.assertFalse(case["network_used"])
        self.assertFalse(case["used_api"])


class TestOnlyLayoutWasPorted(unittest.TestCase):

    def test_the_ported_concepts_are_layout_only(self):
        names = {name for name, _text in PORTED_LAYOUT_CONCEPTS}
        self.assertEqual(names, {"warning_near_the_top",
                                 "section_per_medication",
                                 "gene_phenotype_table",
                                 "finding_detail_rows"})

    def test_the_label_table_is_explicitly_not_ported(self):
        names = {name for name, _text in NOT_PORTED}
        self.assertIn("risk_label_table", names)
        self.assertIn("numeric_score", names)
        self.assertIn("free_prose_fields", names)
        self.assertIn("model_generated_narration", names)

    def test_the_legacy_label_table_is_not_reachable_from_reporting(self):
        """Two modules *name* it - one explaining why it was not ported, one
        detecting it in the legacy source - so this is checked against
        identifiers, where naming it in a docstring does not count and using
        it would."""
        from tests.unit.reporting._support import identifiers_of
        for name in os.listdir(os.path.join(REPO_ROOT, "pgx", "reporting")):
            if not name.endswith(".py"):
                continue
            names = identifiers_of(os.path.join(REPO_ROOT, "pgx",
                                                "reporting", name))
            with self.subTest(module=name):
                self.assertNotIn("RISK_LABEL_TR", names)
                self.assertNotIn("render_markdown_report", names)

    def test_no_legacy_value_is_described_as_validated_or_approved(self):
        text = json.dumps(build_report_regression_report(REPO_ROOT),
                          ensure_ascii=False).lower()
        for phrase in ("legacy value is validated",
                       "legacy value is approved",
                       "clinically validated", "approved for clinical"):
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, text)
        self.assertIn("none of them is described as", text)


class TestTheStoredReportMatches(unittest.TestCase):

    def test_the_stored_report_exists(self):
        self.assertTrue(os.path.isfile(REPORT_PATH))

    def test_it_matches_a_regeneration(self):
        import io as _io
        with _io.open(REPORT_PATH, encoding="utf-8") as handle:
            stored = json.load(handle)
        rebuilt = build_report_regression_report(REPO_ROOT)
        self.assertEqual(stored["content_hash"], rebuilt["content_hash"])

    def test_the_allowlist_is_published_inside_it(self):
        import io as _io
        with _io.open(REPORT_PATH, encoding="utf-8") as handle:
            stored = json.load(handle)
        self.assertEqual(stored["allowlist"]["difference_count"],
                         len(REPORT_EXPECTED_DIFFERENCES))
        self.assertEqual(stored["allowlist"],
                         legacy_report_difference_allowlist())


if __name__ == "__main__":
    unittest.main()
