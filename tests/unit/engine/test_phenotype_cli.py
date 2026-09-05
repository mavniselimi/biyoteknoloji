# -*- coding: utf-8 -*-
"""The ``pgx-phenotype`` command line (WP-12).

Every command reads, compares or reports. None of them assesses anything,
calculates attention or coverage, loads a rule, or reaches a network.

The refused-flag tests matter more than they look. ``--fuzzy`` and
``--assume-normal`` are exactly what somebody reaches for when a demo will not
produce the output they expected, and the difference between argparse saying
"unrecognized arguments" and this tool explaining that an uninterpretable
value is never assumed normal is the difference between looking for another
flag and understanding why there isn't one.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

from pgx.application.phenotype_cli import (EXIT_CONFIGURATION_FAILURE, EXIT_OK,
                                           EXIT_REFUSED, REFUSED_FLAGS,
                                           build_parser, main)
from tests.unit.engine._support import REGRESSION_REPORT, REPO_ROOT


def _run(*argv):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = main(list(argv))
    return code, buffer.getvalue()


def _json_run(*argv):
    code, output = _run(*argv)
    return code, json.loads(output)


class TestRefusedFlags(unittest.TestCase):

    def test_every_refused_flag_is_refused_by_name(self):
        for flag in REFUSED_FLAGS:
            with self.subTest(flag=flag):
                code, payload = _json_run(flag, "truth-matrix")
                self.assertEqual(code, EXIT_REFUSED)
                self.assertIn(flag, payload["error"])

    def test_each_refusal_explains_why_the_flag_does_not_exist(self):
        for flag, reason in REFUSED_FLAGS.items():
            with self.subTest(flag=flag):
                _code, payload = _json_run(flag, "truth-matrix")
                self.assertIn(reason, payload["error"])

    def test_the_dangerous_ones_are_all_covered(self):
        for flag in ("--fuzzy", "--nearest", "--assume-normal",
                     "--infer-from-genotype", "--expand-groups",
                     "--attention", "--coverage"):
            with self.subTest(flag=flag):
                self.assertIn(flag, REFUSED_FLAGS)

    def test_abbreviations_are_not_accepted(self):
        self.assertFalse(build_parser().allow_abbrev)

    def test_a_refused_flag_with_a_value_is_still_refused(self):
        code, _payload = _json_run("--nearest=POOR", "truth-matrix")
        self.assertEqual(code, EXIT_REFUSED)


class TestTheCommandSurface(unittest.TestCase):

    EXPECTED = ("compare", "legacy-regression", "list-reason-codes",
                "normalize-profile", "normalize-token", "truth-matrix",
                "verify-regression")

    def _commands(self):
        parser = build_parser()
        for action in parser._actions:  # noqa: SLF001 - argparse has no API
            if hasattr(action, "choices") and action.choices:
                return tuple(sorted(action.choices))
        return ()

    def test_exactly_these_commands_exist(self):
        self.assertEqual(self._commands(), self.EXPECTED)

    def test_no_command_assesses_calculates_or_infers(self):
        for command in self._commands():
            with self.subTest(command=command):
                for forbidden in ("assess", "attention", "coverage", "risk",
                                  "infer", "genotype", "recommend", "approve",
                                  "apply"):
                    self.assertNotIn(forbidden, command)


class TestNormalizeCommands(unittest.TestCase):

    def test_a_canonical_token_normalizes_and_exits_zero(self):
        code, payload = _json_run("normalize-token", "poor")
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["status"], "NORMALIZED")
        self.assertEqual(payload["phenotype"], "POOR")

    def test_an_unsupported_token_exits_non_zero(self):
        """Exit 1, not 0: a pipeline treating "unsupported" as success is how
        an uninterpretable value reaches something that assumes it worked."""
        code, payload = _json_run("normalize-token", "PM")
        self.assertEqual(code, EXIT_REFUSED)
        self.assertEqual(payload["status"], "UNSUPPORTED")
        self.assertIsNone(payload["phenotype"])

    def test_a_genotype_reports_its_own_reason_code(self):
        _code, payload = _json_run("normalize-token", "*1/*2")
        self.assertEqual(payload["reason_code"],
                         "PHENOTYPE_INPUT_GENOTYPE_NOT_ALLOWED")

    def test_a_profile_file_normalizes(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "profile.json")
        with io.open(path, "w", encoding="utf-8") as handle:
            json.dump({"phenotypes": {"CYP2C19": "poor", "CYP2D6": "normal"}},
                      handle)
        code, payload = _json_run("normalize-profile", path)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["observation_count"], 2)
        self.assertTrue(payload["content_hash"].startswith("sha256:"))

    def test_a_profile_with_an_uninterpretable_value_exits_non_zero(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "profile.json")
        with io.open(path, "w", encoding="utf-8") as handle:
            json.dump({"phenotypes": {"CYP2C19": "PM"}}, handle)
        code, payload = _json_run("normalize-profile", path)
        self.assertEqual(code, EXIT_REFUSED)
        self.assertEqual(payload["observations"][0]["status"], "UNSUPPORTED")

    def test_a_missing_file_is_a_configuration_failure_not_a_crash(self):
        code, payload = _json_run("normalize-profile", "/nonexistent.json")
        self.assertEqual(code, EXIT_CONFIGURATION_FAILURE)
        self.assertTrue(payload["refused"])

    def test_invalid_json_is_reported_with_a_stable_code(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "broken.json")
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        code, payload = _json_run("normalize-profile", path)
        self.assertEqual(code, EXIT_CONFIGURATION_FAILURE)
        self.assertEqual(payload["code"], "INVALID_JSON")


class TestCompareCommand(unittest.TestCase):

    def test_an_equal_phenotype_matches(self):
        code, payload = _json_run("compare", "poor", "--declared", "POOR")
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["status"], "MATCH")

    def test_rapid_does_not_match_an_ultrarapid_condition(self):
        code, payload = _json_run("compare", "rapid", "--declared",
                                  "ULTRARAPID")
        self.assertEqual(code, EXIT_REFUSED)
        self.assertEqual(payload["status"], "NO_MATCH")

    def test_a_one_of_naming_both_matches_both(self):
        for value in ("rapid", "ultrarapid"):
            with self.subTest(value=value):
                code, payload = _json_run("compare", value, "--operator",
                                          "ONE_OF", "--declared", "RAPID",
                                          "ULTRARAPID")
                self.assertEqual(code, EXIT_OK)
                self.assertEqual(payload["status"], "MATCH")

    def test_an_unsupported_input_reports_its_own_status(self):
        code, payload = _json_run("compare", "PM", "--declared", "POOR")
        self.assertEqual(code, EXIT_REFUSED)
        self.assertEqual(payload["status"], "INPUT_UNSUPPORTED")

    def test_an_indeterminate_input_reports_its_own_status(self):
        _code, payload = _json_run("compare", "INDETERMINATE", "--declared",
                                   "POOR")
        self.assertEqual(payload["status"], "INPUT_INDETERMINATE")

    def test_an_unknown_declared_phenotype_is_refused(self):
        code, payload = _json_run("compare", "poor", "--declared",
                                  "DECREASED_FUNCTION")
        self.assertEqual(code, EXIT_CONFIGURATION_FAILURE)
        self.assertEqual(payload["code"], "PHENOTYPE_UNKNOWN")

    def test_indeterminate_cannot_be_declared_by_a_condition(self):
        code, _payload = _json_run("compare", "poor", "--declared",
                                   "INDETERMINATE")
        self.assertNotEqual(code, EXIT_OK)


class TestReportingCommands(unittest.TestCase):

    def test_the_truth_matrix_prints_every_pair(self):
        code, payload = _json_run("truth-matrix")
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["row_count"], 30)

    def test_the_reason_codes_are_listed_with_the_allowlist(self):
        code, payload = _json_run("list-reason-codes")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("PHENOTYPE_INPUT_BROAD_GROUP_NOT_ALLOWED",
                      payload["reason_codes"])
        self.assertGreaterEqual(
            payload["expected_differences"]["entry_count"], 3)

    def test_the_regression_report_verifies_against_the_published_file(self):
        code, payload = _json_run("verify-regression", "--repo-root",
                                  REPO_ROOT)
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(payload["matches"])

    def test_generating_the_report_twice_produces_identical_bytes(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        first = os.path.join(tmp, "a.json")
        second = os.path.join(tmp, "b.json")
        _run("legacy-regression", "--repo-root", REPO_ROOT, "--out", first)
        _run("legacy-regression", "--repo-root", REPO_ROOT, "--out", second)
        with io.open(first, "rb") as handle:
            first_bytes = handle.read()
        with io.open(second, "rb") as handle:
            second_bytes = handle.read()
        self.assertEqual(first_bytes, second_bytes)
        with io.open(REGRESSION_REPORT, "rb") as handle:
            self.assertEqual(handle.read(), first_bytes)


class TestTheToolIsOffline(unittest.TestCase):

    def test_the_cli_imports_no_client_library(self):
        from tests.unit.engine._support import APPLICATION_DIR, imports_of
        imported = imports_of(os.path.join(APPLICATION_DIR,
                                           "phenotype_cli.py"))
        for forbidden in ("requests", "httpx", "urllib.request", "socket",
                          "sqlalchemy", "psycopg2", "datetime", "time",
                          "random"):
            with self.subTest(module=forbidden):
                self.assertNotIn(forbidden, imported)

    def test_the_cli_runs_with_sockets_broken(self):
        import socket
        saved = (socket.socket, socket.create_connection, socket.getaddrinfo)

        def refuse(*args, **kwargs):
            raise AssertionError("the phenotype CLI reached the network")

        socket.socket = refuse
        socket.create_connection = refuse
        socket.getaddrinfo = refuse
        try:
            code, payload = _json_run("truth-matrix")
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["row_count"], 30)
        finally:
            (socket.socket, socket.create_connection,
             socket.getaddrinfo) = saved


if __name__ == "__main__":
    unittest.main()
