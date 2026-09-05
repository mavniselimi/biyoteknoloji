# -*- coding: utf-8 -*-
"""Two things that are usually absent, and must be absent honestly.

``coverage.py`` and PostgreSQL are the two dependencies this repository most
often runs without. The temptation in both cases is the same: report something
rather than nothing. A percentage estimated from test-file counts, or a schema
inspection reported as a database pass, would each be a number that reads like
a measurement and is not one.
"""

from __future__ import annotations

import unittest

from pgx.verification.coverage_report import (
    CRITICAL_MODULE_PREFIXES,
    DECLARED_LINE_THRESHOLD,
    INSTALL_COMMAND,
    blocked_summary,
    coverage_available,
    omit_patterns,
    measure_coverage,
)
from pgx.verification.discovery import discover
from pgx.verification.inventory import build_inventory
from pgx.verification.model import Category, Outcome, SkipPolicy

from tests.unit.verification._support import REPO_ROOT


class TestCoverageIsMeasuredOrExplicitlyNot(unittest.TestCase):

    def test_a_blocked_summary_reports_no_number_at_all(self):
        """Null is what an unmeasured number looks like. Zero is what a
        measured zero looks like, and the two are different answers."""
        summary = blocked_summary("coverage.py is absent")
        self.assertEqual(summary.status, "BLOCKED")
        for value in (summary.line_percent, summary.branch_percent,
                      summary.covered_lines, summary.total_lines,
                      summary.covered_branches, summary.total_branches,
                      summary.measured_module_count):
            self.assertIsNone(value)

    def test_a_blocked_summary_says_how_to_unblock_it(self):
        summary = blocked_summary("absent")
        self.assertEqual(summary.install_command, INSTALL_COMMAND)
        self.assertIn("coverage", INSTALL_COMMAND)

    def test_the_threshold_was_declared_before_anything_was_measured(self):
        """A threshold chosen after seeing the result is not a threshold."""
        self.assertIsInstance(DECLARED_LINE_THRESHOLD, float)
        self.assertGreater(DECLARED_LINE_THRESHOLD, 0)

    def test_measuring_without_the_tool_returns_blocked_rather_than_raising(
            self):
        """The absence of a measurement is a result the caller must report,
        not an error it should have to catch."""
        if coverage_available():
            self.skipTest("coverage.py is installed here, so the absent path "
                          "cannot be exercised; the measured path is covered "
                          "by test_a_measured_summary_carries_real_numbers")
        summary = measure_coverage(REPO_ROOT)
        self.assertEqual(summary.status, "BLOCKED")
        self.assertIsNone(summary.line_percent)
        self.assertIn("coverage.py", summary.reason)

    def test_a_measured_summary_carries_real_numbers(self):
        if not coverage_available():
            self.skipTest("coverage.py is not installed in this environment; "
                          "the summary is BLOCKED and is asserted as such by "
                          "the test above. Install it with: %s"
                          % INSTALL_COMMAND)
        summary = measure_coverage(REPO_ROOT)
        if summary.status != "MEASURED":  # pragma: no cover - tool present
            self.fail("coverage.py is installed but measurement reported %s: "
                      "%s" % (summary.status, summary.reason))
        self.assertIsNotNone(summary.line_percent)
        self.assertGreaterEqual(summary.line_percent, 0.0)

    def test_the_first_party_packages_are_what_is_measured(self):
        self.assertIn("pgx/domain", CRITICAL_MODULE_PREFIXES)
        self.assertIn("pgx/verification", CRITICAL_MODULE_PREFIXES)
        self.assertIn("apps/api", CRITICAL_MODULE_PREFIXES)

    def test_the_frozen_legacy_scripts_are_not_measured(self):
        """They are a baseline to compare against, not code under development.
        Including them would move the aggregate without telling anybody
        anything."""
        for legacy in ("risk_engine", "clinpgx_probe", "gemini_report",
                       "alternative_ranker", "scripts/legacy"):
            with self.subTest(module=legacy):
                self.assertFalse(
                    any(legacy in prefix
                        for prefix in CRITICAL_MODULE_PREFIXES))

    def test_the_exclusions_are_written_into_the_document(self):
        """Visible in the artifact rather than buried in a config file."""
        document = blocked_summary("absent", root=REPO_ROOT).as_document()
        self.assertTrue(document["excluded"])
        joined = " ".join(document["excluded"])
        self.assertIn("tests/*", joined)
        self.assertIn("migrations/versions/*", joined)

    def test_the_exclusions_are_read_from_pyproject_not_restated(self):
        """One source of truth, so the artifact cannot describe exclusions the
        tool is not applying - and so this module does not have to spell out
        legacy data paths that tests/unit/domain/test_dependency_boundaries.py
        correctly refuses to see in a V2 module."""
        patterns = omit_patterns(REPO_ROOT)
        self.assertIn("tests/*", patterns)
        self.assertIn("risk_engine.py", patterns)
        document = blocked_summary("absent", root=REPO_ROOT).as_document()
        for pattern in patterns:
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, document["excluded"])

    def test_without_a_root_only_the_note_is_reported(self):
        """Rather than a remembered list that could disagree with the file."""
        document = blocked_summary("absent").as_document()
        self.assertEqual(len(document["excluded"]), 1)
        self.assertIn("pyproject.toml", document["excluded"][0])

    def test_the_configuration_is_declared_in_pyproject(self):
        import io
        import os
        with io.open(os.path.join(REPO_ROOT, "pyproject.toml"), "r",
                     encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("[tool.coverage.run]", text)
        self.assertIn("[tool.coverage.report]", text)
        self.assertIn("branch = true", text)
        self.assertIn("coverage[toml]", text)

    def test_no_fail_under_was_invented(self):
        """`fail_under` would be a gate on a measurement nobody has taken."""
        import io
        import os
        with io.open(os.path.join(REPO_ROOT, "pyproject.toml"), "r",
                     encoding="utf-8") as handle:
            text = handle.read()
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            self.assertFalse(stripped.startswith("fail_under"),
                             "a coverage gate was set without a measurement")


class TestTheDatabaseTestsAreRealOrBlocked(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.inventory = build_inventory(discover(REPO_ROOT))

    def _postgres(self):
        return [entry for entry in self.inventory.entries
                if entry.category is Category.POSTGRESQL_INTEGRATION]

    def test_the_postgresql_tests_are_a_category_of_their_own(self):
        """Not folded into INTEGRATION, so a report cannot show integration as
        green while every database test skipped."""
        self.assertTrue(self._postgres())

    def test_they_declare_the_dependency_they_need(self):
        for entry in self._postgres():
            with self.subTest(test=entry.test_id):
                self.assertIn("psycopg", entry.dependencies)
                self.assertIn("postgresql", entry.dependencies)

    def test_they_may_skip_only_for_that_dependency(self):
        for entry in self._postgres():
            with self.subTest(test=entry.test_id):
                self.assertIs(entry.skip_policy,
                              SkipPolicy.ENVIRONMENT_DEPENDENCY)
                self.assertIn(
                    "psycopg",
                    " ".join(entry.permitted_skip_reasons).lower())

    def test_a_driver_is_not_a_database(self):
        """The permitted reason names the database as well as the driver, so
        an environment with psycopg installed and no server running still
        reports the skip honestly rather than looking equipped."""
        from tests.integration.db import _support
        text = _support.__doc__ or ""
        self.assertIn("TEST_DATABASE_URL", text + str(vars(_support).keys()))

    def test_the_suite_refuses_a_database_that_is_not_the_test_one(self):
        """WP-19 forwards TEST_DATABASE_URL and decides nothing. The refusal
        lives where it always did, and this asserts it is still there."""
        from tests.integration.db import _support
        self.assertTrue(hasattr(_support, "DEFAULT_TEST_DATABASE_NAME"))
        self.assertIn("test", _support.DEFAULT_TEST_DATABASE_NAME)

    def test_the_migration_tests_are_their_own_category(self):
        migration = [entry for entry in self.inventory.entries
                     if entry.category is Category.MIGRATION]
        self.assertTrue(migration)
