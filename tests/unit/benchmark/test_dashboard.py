# -*- coding: utf-8 -*-
"""The page: unavailable never renders as zero, development never as evidence.

Two things are proven here that nothing else can prove. First, that the real
page shows the truthful blocked state with no percentage anywhere. Second,
that the same template, handed a TEST-ONLY synthetic feed, renders a correct
numerical table - so "the dashboard shows nothing" is a fact about this
repository rather than a limitation of the page.
"""

from __future__ import annotations

import unittest

from apps.web.validation_feed import load_dashboard_feed
from apps.web.view_models.pages import build_validation_board
from pgx.validation.benchmark import BenchmarkEngine
from pgx.validation.benchmark_report import build_validation_report
from pgx.validation.dashboard_feed import build_dashboard_feed
from pgx.validation.vocabulary import ValidationCaseRole as Role
from tests.fixtures.wp21 import synthetic_release as S
from tests.unit.benchmark._support import REPO_ROOT


def _synthetic_feed():
    engine = BenchmarkEngine(observation_port=S.SyntheticObservationPort(),
                             judgment_port=S.SyntheticJudgmentPort())
    run = engine.execute(S.plan(), cases=[])
    values = engine.compute(run)
    report = build_validation_report(
        plan=run.plan, values_by_role=values,
        case_counts={"DEVELOPMENT": S.DEVELOPMENT_CASE_COUNT,
                     "INTERNAL_HOLDOUT": S.INTERNAL_CASE_COUNT,
                     "EXPERT_HOLDOUT": S.EXPERT_CASE_COUNT},
        observation_counts={role: len(run.for_role(Role(role)))
                            for role in values},
        separation_audit={}, blockers=[], benchmark_executed=True,
        active_release_available=True, run=run)
    return build_dashboard_feed(report)


class TestTheWebLayerReadsOnlyTheCommittedFeed(unittest.TestCase):

    def test_the_adapter_returns_the_committed_aggregate(self):
        feed = load_dashboard_feed(REPO_ROOT)
        self.assertIsNotNone(feed)
        self.assertEqual(feed["feed_schema_version"],
                         "pgx-wp21-dashboard-feed/1")

    def test_the_adapter_imports_no_benchmark_engine(self):
        import ast
        import io
        import os
        path = os.path.join(REPO_ROOT, "apps", "web", "validation_feed.py")
        with io.open(path, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                with self.subTest(module=node.module):
                    self.assertFalse(node.module.startswith("pgx."))

    def test_a_feed_carrying_restricted_material_is_refused(self):
        import io
        import json
        import os
        import tempfile
        feed = dict(load_dashboard_feed(REPO_ROOT))
        feed["sections"][0]["observations"] = [{"case_id": "PGX-VAL-INT-1"}]
        with tempfile.TemporaryDirectory() as root:
            target = os.path.join(root, "data", "validation")
            os.makedirs(target)
            with io.open(os.path.join(target, "wp21-dashboard-feed.json"),
                         "w", encoding="utf-8") as handle:
                json.dump(feed, handle)
            self.assertIsNone(load_dashboard_feed(root))

    def test_a_missing_feed_returns_none_rather_than_a_fabricated_one(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(load_dashboard_feed(root))


class TestTheRealPageShowsNoNumber(unittest.TestCase):
    """Requirement 25 and A16."""

    @classmethod
    def setUpClass(cls):
        cls.board = build_validation_board(
            development_case_count=7, feed=load_dashboard_feed(REPO_ROOT),
            locale="tr")

    def test_three_sections_are_rendered_separately(self):
        self.assertEqual([section.section for section in
                          self.board.metric_sections],
                         ["DEVELOPMENT_REGRESSION", "INTERNAL_HOLDOUT",
                          "EXPERT_HOLDOUT"])

    def test_no_row_carries_a_number(self):
        for section in self.board.metric_sections:
            for row in section.rows:
                with self.subTest(section=section.section,
                                  metric=row.metric_id):
                    self.assertFalse(row.has_number)

    def test_every_value_renders_as_unavailable_not_zero(self):
        for section in self.board.metric_sections:
            for row in section.rows:
                with self.subTest(metric=row.metric_id):
                    self.assertEqual(row.value_text, "Kullanılamıyor")
                    self.assertNotIn("0", row.value_text)

    def test_the_reason_survives_to_the_page(self):
        row = self.board.metric_sections[1].rows[0]
        self.assertEqual(row.reason_text, "BENCHMARK_NOT_EXECUTED")

    def test_the_board_says_no_benchmark_ran(self):
        self.assertFalse(self.board.benchmark_executed)
        self.assertTrue(self.board.not_benchmarked_note)


class TestDevelopmentCannotBeMistakenForEvidence(unittest.TestCase):
    """A6 at the presentation layer."""

    @classmethod
    def setUpClass(cls):
        cls.board = build_validation_board(
            development_case_count=7, feed=_synthetic_feed(), locale="en")
        cls.development = cls.board.metric_sections[0]

    def test_the_heading_says_it_is_not_validation_evidence(self):
        self.assertIn("NOT VALIDATION EVIDENCE",
                      self.development.heading.upper())

    def test_it_is_its_own_section_not_a_flag_on_a_shared_table(self):
        self.assertTrue(self.development.is_development_regression)
        self.assertFalse(self.development.is_validation_evidence)
        self.assertNotEqual(self.development.section,
                            self.board.metric_sections[1].section)

    def test_it_carries_its_own_warning(self):
        self.assertIn("shaped the software", self.development.note)

    def test_the_model_refuses_a_development_section_marked_as_evidence(self):
        from apps.web.view_models.pages import (MetricSectionModel,
                                                ValidationBoardModel)
        bad = MetricSectionModel(
            section="DEVELOPMENT_REGRESSION", role="DEVELOPMENT",
            heading="x", is_validation_evidence=True,
            is_development_regression=True, case_count_text="7", note="",
            rows=())
        with self.assertRaises(ValueError):
            ValidationBoardModel(
                development_case_count=7, internal_holdout_count=None,
                expert_holdout_count=None, validation_run_count=None,
                architecture_note="", no_run_note="", metrics_note="",
                separation_note="", no_conclusion_note="", blockers=(),
                metric_sections=(bad,))

    def test_no_development_row_is_marked_evidence_even_with_numbers(self):
        for row in self.development.rows:
            with self.subTest(metric=row.metric_id):
                self.assertFalse(row.is_validation_evidence)


class TestASyntheticFeedRendersNumbers(unittest.TestCase):
    """Requirement 24 and A15: the capability, on the same template."""

    @classmethod
    def setUpClass(cls):
        cls.board = build_validation_board(
            development_case_count=S.DEVELOPMENT_CASE_COUNT,
            feed=_synthetic_feed(), locale="en")
        cls.internal = [section for section in cls.board.metric_sections
                        if section.role == "INTERNAL_HOLDOUT"][0]
        cls.rows = {row.metric_id: row for row in cls.internal.rows}

    def test_the_board_reports_a_benchmark(self):
        self.assertTrue(self.board.benchmark_executed)
        self.assertEqual(self.board.release_text, S.RELEASE_PUBLIC_ID)

    def test_concordance_renders_its_real_value(self):
        row = self.rows["PGX-VAL-001"]
        self.assertTrue(row.has_number)
        self.assertEqual(row.value_text, "0.7500")
        self.assertEqual(row.numerator_text, str(S.INTERNAL_CONCORDANT))
        self.assertEqual(row.denominator_text, str(S.INTERNAL_CASE_COUNT))

    def test_a_measured_zero_renders_as_zero_not_unavailable(self):
        expert = [section for section in self.board.metric_sections
                  if section.role == "EXPERT_HOLDOUT"][0]
        rows = {row.metric_id: row for row in expert.rows}
        row = rows["PGX-VAL-004"]
        self.assertTrue(row.has_number)
        self.assertEqual(row.value_text, "0.0000")

    def test_an_expert_metric_still_renders_as_unavailable(self):
        expert = [section for section in self.board.metric_sections
                  if section.role == "EXPERT_HOLDOUT"][0]
        rows = {row.metric_id: row for row in expert.rows}
        self.assertFalse(rows["PGX-VAL-011"].has_number)
        # Renamed at WP-22: the module is implemented, and the reason a
        # reader needs is that nobody has completed a review under it.
        self.assertEqual(rows["PGX-VAL-011"].reason_text,
                         "NO_COMPLETED_EXPERT_REVIEWS")

    def test_the_two_holdout_sections_show_different_numbers(self):
        expert = [section for section in self.board.metric_sections
                  if section.role == "EXPERT_HOLDOUT"][0]
        expert_rows = {row.metric_id: row for row in expert.rows}
        self.assertNotEqual(self.rows["PGX-VAL-001"].value_text,
                            expert_rows["PGX-VAL-001"].value_text)

    def test_no_case_identifier_reaches_the_board(self):
        payload = repr(self.board)
        for case_id in ("TEST-ONLY-IH-001", "TEST-ONLY-EH-001"):
            with self.subTest(case=case_id):
                self.assertNotIn(case_id, payload)


class TestTheRenderedPageIsSafe(unittest.TestCase):
    """Escaping, the research banner and the absence of holdout identifiers."""

    @classmethod
    def setUpClass(cls):
        import io
        import os
        path = os.path.join(REPO_ROOT, "tests", "fixtures", "wp17",
                            "snapshots", "validation.html")
        with io.open(path, "r", encoding="utf-8") as handle:
            cls.html = handle.read()

    def test_the_research_banner_survives(self):
        self.assertIn("Araştırma", self.html)

    def test_no_percentage_appears(self):
        self.assertNotIn("%", self.html)

    def test_no_metric_value_renders_as_zero(self):
        """The value column carries no number at all on the real page.

        Every metric value cell is a ``<span class="unavailable">``. A
        ``<span class="numeric">`` inside a value cell would mean a metric had
        been given a number, and none has.
        """
        import re
        for match in re.finditer(
                r'<td><span class="(numeric|unavailable)">([^<]*)</span></td>',
                self.html):
            with self.subTest(cell=match.group(0)):
                self.assertEqual(match.group(1), "unavailable")

    def test_the_zero_that_does_appear_is_a_real_case_count(self):
        """There genuinely are zero holdout cases, and saying so is correct.

        This is the distinction the whole work package turns on: a counted
        zero is a measurement and prints as ``0``; an uncomputed metric is not
        and prints as *unavailable*. Both appear on this page, and asserting
        that no ``0`` appears anywhere would have forced the honest count to
        be hidden too.
        """
        self.assertIn('Vaka sayısı: <span class="numeric">0</span>',
                      self.html)
        self.assertIn('Vaka sayısı: <span class="numeric">7</span>',
                      self.html)

    def test_no_percentage_shaped_value_appears(self):
        for shape in (">0%<", "0.0000", "100.0", "%)"):
            with self.subTest(shape=shape):
                self.assertNotIn(shape, self.html)

    def test_the_unavailable_label_is_used_instead(self):
        self.assertIn("Kullanılamıyor", self.html)
        self.assertIn("BENCHMARK_NOT_EXECUTED", self.html)

    def test_no_holdout_case_identifier_is_in_the_html(self):
        for marker in ("TEST-ONLY", "PGX-VAL-INT", "PGX-VAL-EXP",
                       "expected_"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, self.html)

    def test_the_development_section_is_visually_distinct(self):
        self.assertIn("metric-section-development", self.html)
        self.assertIn("metric-section-holdout", self.html)

    def test_the_metric_ids_are_rendered_in_code_elements(self):
        self.assertIn("<code>PGX-VAL-001</code>", self.html)
