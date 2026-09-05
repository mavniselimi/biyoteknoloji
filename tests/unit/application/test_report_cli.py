# -*- coding: utf-8 -*-
"""I. The report CLI.

What it cannot do is the specification. The refused flags are checked by
name, the real path refuses, synthetic mode is explicit in every direction,
and every exit code is asserted rather than assumed.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from pgx.application.report_cli import (EXIT_CONFIGURATION_FAILURE, EXIT_OK,
                                        EXIT_REFUSED, REFUSED_FLAGS,
                                        build_parser, main,
                                        refuse_unsafe_flags)
from tests.unit.reporting._support import REPO_ROOT

FIXTURE = os.path.join(REPO_ROOT, "tests", "fixtures", "wp15",
                       "synthetic-canonical-result.json")


def run(*argv):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(list(argv))
    return code, buffer.getvalue()


def run_json(*argv):
    code, text = run(*argv)
    return code, json.loads(text)


class TestTheRefusedFlags(unittest.TestCase):

    def test_every_refused_flag_exits_refused(self):
        for flag in REFUSED_FLAGS:
            with self.subTest(flag=flag):
                code, payload = run_json(flag, "gate-status")
                self.assertEqual(code, EXIT_REFUSED)
                self.assertEqual(payload["code"], "FLAG_REFUSED")

    def test_every_refusal_says_why(self):
        for flag, reason in REFUSED_FLAGS.items():
            with self.subTest(flag=flag):
                self.assertGreater(len(reason), 30)

    def test_a_refused_flag_with_a_value_is_still_refused(self):
        code, payload = run_json("--api-key=secret", "gate-status")
        self.assertEqual(code, EXIT_REFUSED)
        self.assertEqual(payload["code"], "FLAG_REFUSED")

    def test_the_refusal_happens_before_parsing(self):
        self.assertIsNotNone(refuse_unsafe_flags(["--enable-llm"]))
        self.assertIsNone(refuse_unsafe_flags(["gate-status"]))

    def test_no_refused_flag_is_actually_a_parser_option(self):
        parser = build_parser()
        options = set()
        for action in parser._actions:
            options.update(action.option_strings)
        for flag in REFUSED_FLAGS:
            with self.subTest(flag=flag):
                self.assertNotIn(flag, options)

    def test_abbreviations_are_not_accepted(self):
        """--enable-llm must not be reachable as --enable."""
        self.assertFalse(build_parser().allow_abbrev)


class TestTheRealPathRefuses(unittest.TestCase):

    def test_render_refuses_while_the_boundary_is_unapproved(self):
        code, payload = run_json("render", "some-assessment-id")
        self.assertEqual(code, EXIT_REFUSED)
        self.assertEqual(payload["code"],
                         "REPORT_CLAIM_BOUNDARY_NOT_APPROVED")

    def test_the_refusal_names_the_boundary_status(self):
        _code, payload = run_json("render", "some-assessment-id")
        self.assertIn("DRAFT", payload["claim_boundary_status"])

    def test_no_command_publishes_a_real_report(self):
        parser = build_parser()
        commands = set()
        for action in parser._actions:
            if getattr(action, "choices", None):
                commands.update(action.choices)
        for forbidden in ("publish", "publish-real", "approve-template",
                          "narrate", "recommend", "rank",
                          "compare-medications"):
            with self.subTest(command=forbidden):
                self.assertNotIn(forbidden, commands)


class TestTheReadOnlyCommands(unittest.TestCase):

    def test_gate_status_reports_every_blocker(self):
        from pgx.application.report_gate_status import BLOCKER_CODES
        code, payload = run_json("gate-status")
        self.assertEqual(code, EXIT_REFUSED)
        self.assertEqual(payload["blocker_count"], len(BLOCKER_CODES))
        self.assertFalse(payload["may_publish_real_reports"])

    def test_gate_status_reports_zero_real_reports(self):
        _code, payload = run_json("gate-status")
        self.assertEqual(payload["real_report_count"], 0)
        self.assertEqual(payload["real_assessment_count"], 0)
        self.assertEqual(payload["published_artifact_count"], 0)
        self.assertTrue(payload["synthetic_only"])

    def test_gate_status_validates_against_its_schema(self):
        from pgx.application.report_schema import validate_wp15_gate_status
        _code, payload = run_json("gate-status")
        self.assertEqual(validate_wp15_gate_status(payload), ())

    def test_the_template_contract_names_what_is_never_localised(self):
        code, payload = run_json("template-contract")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("every hash", payload["never_localised"])
        self.assertIn("coverage reason codes", payload["never_localised"])

    def test_the_claim_gate_contract_publishes_the_scanner_limits(self):
        code, payload = run_json("claim-gate-contract")
        self.assertEqual(code, EXIT_OK)
        self.assertGreaterEqual(len(payload["limits"]), 4)

    def test_the_llm_boundary_says_nothing_is_implemented(self):
        code, payload = run_json("llm-boundary")
        self.assertEqual(code, EXIT_OK)
        self.assertFalse(payload["llm_enabled"])
        self.assertFalse(payload["provider_implemented"])
        self.assertFalse(payload["requires_network"])

    def test_list_failure_codes_prints_every_code(self):
        from pgx.reporting.errors import REPORT_FAILURE_CODES
        code, payload = run_json("list-failure-codes")
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["count"], len(REPORT_FAILURE_CODES))

    def test_text_output_is_offered_everywhere(self):
        for command in ("gate-status", "template-contract",
                        "claim-gate-contract", "llm-boundary",
                        "list-failure-codes"):
            with self.subTest(command=command):
                _code, text = run(command, "--text")
                self.assertTrue(text.strip())
                self.assertFalse(text.strip().startswith("{"))


class TestValidateReport(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory, True)

    def test_it_validates_the_checked_in_fixture_as_a_result(self):
        code, payload = run_json("validate-report", FIXTURE, "--kind",
                                 "result")
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(payload["passed"])

    def test_it_refuses_a_document_of_the_wrong_kind(self):
        code, payload = run_json("validate-report", FIXTURE, "--kind",
                                 "report")
        self.assertEqual(code, EXIT_REFUSED)
        self.assertFalse(payload["passed"])
        self.assertTrue(payload["issues"])

    def test_a_missing_file_is_a_configuration_failure_not_a_refusal(self):
        code, payload = run_json("validate-report",
                                 os.path.join(self.directory, "nope.json"))
        self.assertEqual(code, EXIT_CONFIGURATION_FAILURE)
        self.assertEqual(payload["code"], "FILE_NOT_FOUND")

    def test_invalid_json_is_a_configuration_failure(self):
        path = os.path.join(self.directory, "broken.json")
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        code, payload = run_json("validate-report", path)
        self.assertEqual(code, EXIT_CONFIGURATION_FAILURE)
        self.assertEqual(payload["code"], "INVALID_JSON")


class TestRenderSynthetic(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory, True)

    def test_it_renders_the_fixture_and_writes_an_artifact(self):
        code, payload = run_json("render-synthetic", "--from", FIXTURE,
                                 "--out", self.directory)
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(payload["is_synthetic"])
        self.assertTrue(payload["claim_scan_is_clean"])
        self.assertEqual(len(os.listdir(self.directory)), 2)

    def test_its_output_says_it_is_synthetic(self):
        _code, payload = run_json("render-synthetic", "--from", FIXTURE,
                                  "--out", self.directory)
        self.assertIn("SYNTHETIC", payload["synthetic_notice"])
        self.assertIn("NOT A REAL ASSESSMENT", payload["synthetic_notice"])

    def test_it_has_no_default_source(self):
        code, payload = run_json("render-synthetic", "--out", self.directory)
        self.assertEqual(code, EXIT_REFUSED)
        self.assertEqual(payload["code"], "REPORT_ASSESSMENT_NOT_FOUND")

    def test_it_has_no_default_destination(self):
        code, payload = run_json("render-synthetic", "--from", FIXTURE)
        self.assertEqual(code, EXIT_REFUSED)
        self.assertEqual(payload["code"],
                         "REPORT_SYNTHETIC_DESTINATION_REFUSED")

    def test_it_refuses_the_production_report_directory(self):
        code, payload = run_json(
            "render-synthetic", "--from", FIXTURE, "--out",
            os.path.join(self.directory, "data", "reports"))
        self.assertEqual(code, EXIT_REFUSED)
        self.assertEqual(payload["code"],
                         "REPORT_SYNTHETIC_DESTINATION_REFUSED")

    def test_it_renders_both_locales(self):
        for locale in ("tr", "en"):
            with self.subTest(locale=locale):
                code, payload = run_json("render-synthetic", "--from",
                                         FIXTURE, "--out", self.directory,
                                         "--locale", locale)
                self.assertEqual(code, EXIT_OK)
                self.assertEqual(payload["locale"], locale)

    def test_an_unsupported_locale_is_rejected_by_the_parser(self):
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                main(["render-synthetic", "--from", FIXTURE, "--out",
                      self.directory, "--locale", "de"])

    def test_rendering_twice_is_idempotent(self):
        run_json("render-synthetic", "--from", FIXTURE, "--out",
                 self.directory)
        code, _payload = run_json("render-synthetic", "--from", FIXTURE,
                                  "--out", self.directory)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(len(os.listdir(self.directory)), 2)


class TestVerifyArtifact(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory, True)
        run_json("render-synthetic", "--from", FIXTURE, "--out",
                 self.directory)
        self.manifest = os.path.join(
            self.directory,
            [name for name in os.listdir(self.directory)
             if name.endswith(".manifest.json")][0])

    def test_it_verifies_a_published_artifact(self):
        code, payload = run_json("verify-artifact", self.manifest)
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(payload["verified"])
        self.assertTrue(payload["claim_scan_is_clean"])

    def test_it_refuses_an_edited_document(self):
        document = os.path.join(
            self.directory,
            [name for name in os.listdir(self.directory)
             if name.endswith(".md")][0])
        with io.open(document, "a", encoding="utf-8") as handle:
            handle.write("edited\n")
        code, payload = run_json("verify-artifact", self.manifest)
        self.assertEqual(code, EXIT_REFUSED)
        self.assertEqual(payload["code"], "REPORT_ARTIFACT_HASH_MISMATCH")


class TestTheLegacyRegressionCommands(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory, True)

    def test_legacy_regression_writes_a_deterministic_report(self):
        path = os.path.join(self.directory, "report.json")
        code, payload = run_json("legacy-regression", "--out", path)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["live_model_calls"], 0)
        self.assertTrue(os.path.isfile(path))

    def test_verify_regression_matches_the_stored_report(self):
        code, payload = run_json("verify-regression")
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(payload["matches"])

    def test_verify_regression_refuses_a_stale_report(self):
        path = os.path.join(self.directory, "stale.json")
        with io.open(path, "w", encoding="utf-8") as handle:
            json.dump({"content_hash": "sha256:" + "0" * 64}, handle)
        code, payload = run_json("verify-regression", "--path", path)
        self.assertEqual(code, EXIT_REFUSED)
        self.assertFalse(payload["matches"])


if __name__ == "__main__":
    unittest.main()
