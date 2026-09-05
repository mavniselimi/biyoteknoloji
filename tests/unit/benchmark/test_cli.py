# -*- coding: utf-8 -*-
"""``pgx-benchmark``: the exit codes, and what the real repository returns."""

from __future__ import annotations

import io
import unittest

from pgx.application.benchmark_cli import (EXIT_BLOCKED, EXIT_FAILED, EXIT_OK,
                                           EXIT_USAGE, main)
from tests.unit.benchmark._support import REPO_ROOT


def _run(*argv):
    stream = io.StringIO()
    code = main(["--root", REPO_ROOT] + list(argv), stream=stream)
    return code, stream.getvalue()


class TestTheExitCodesAreStable(unittest.TestCase):

    def test_no_subcommand_is_a_usage_error(self):
        code, _ = _run()
        self.assertEqual(code, EXIT_USAGE)

    def test_definitions_succeed_because_definitions_exist_now(self):
        """The one thing WP-21 can do today without any release."""
        code, output = _run("definitions")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("PGX-VAL-001", output)
        self.assertIn("no metric carries a threshold", output)

    def test_report_is_blocked_because_nothing_was_benchmarked(self):
        code, output = _run("report")
        self.assertEqual(code, EXIT_BLOCKED)
        self.assertIn("DEVELOPMENT_REGRESSION", output)

    def test_gate_status_is_blocked(self):
        code, output = _run("gate-status")
        self.assertEqual(code, EXIT_BLOCKED)
        self.assertIn("BLOCKED", output)
        self.assertIn("release may proceed False", output)

    def test_run_refuses_and_says_what_is_missing(self):
        code, output = _run("run")
        self.assertEqual(code, EXIT_BLOCKED)
        self.assertIn("REFUSED", output)
        self.assertIn("BENCHMARK_NO_ACTIVE_RELEASE", output)
        self.assertIn("BENCHMARK_NO_HOLDOUT_CASES", output)

    def test_a_blocked_run_writes_nothing(self):
        import os
        before = os.path.getmtime(os.path.join(
            REPO_ROOT, "data", "validation", "wp21-validation-report.json"))
        _run("run")
        after = os.path.getmtime(os.path.join(
            REPO_ROOT, "data", "validation", "wp21-validation-report.json"))
        self.assertEqual(before, after)

    def test_feed_is_blocked_too(self):
        code, output = _run("feed")
        self.assertEqual(code, EXIT_BLOCKED)
        self.assertIn("dashboard-feed", output)


class TestTheCliPrintsNoNumber(unittest.TestCase):

    def test_no_percentage_reaches_the_terminal(self):
        for command in ("report", "gate-status", "run"):
            with self.subTest(command=command):
                _, output = _run(command)
                self.assertNotIn("%", output)

    def test_the_report_shows_every_metric_as_not_executed(self):
        _, output = _run("report")
        self.assertIn("NOT_EXECUTED=15", output)

    def test_the_gate_reports_zero_numeric_metrics(self):
        _, output = _run("gate-status")
        self.assertIn("numeric metrics     0", output)


class TestJsonOutputMatchesTheArtifacts(unittest.TestCase):

    def test_report_json_is_the_committed_document(self):
        import json
        code, output = _run("report", "--json")
        self.assertEqual(code, EXIT_BLOCKED)
        from tests.unit.benchmark._support import read_json
        self.assertEqual(json.loads(output),
                         read_json("data/validation/"
                                   "wp21-validation-report.json"))

    def test_gate_status_json_is_the_committed_document(self):
        import json
        from tests.unit.benchmark._support import read_json
        _, output = _run("gate-status", "--json")
        self.assertEqual(json.loads(output),
                         read_json("data/validation/"
                                   "wp21-real-gate-status.json"))
