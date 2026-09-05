# -*- coding: utf-8 -*-
"""``pgx-verify`` returns something a machine can branch on.

The exit code is the part a CI job reads, and it is the part that must never
be a guess. Several negative tests print ``CONFIGURATION_FAILURE`` while
passing, so a job that read stdout would fail a green suite; a job that read
an exit code of 0 from a command that ran nothing would ship a release nobody
verified.
"""

from __future__ import annotations

import contextlib
import io
import json
import unittest

from pgx.application.verification_cli import (
    EXIT_BLOCKED,
    EXIT_FAILED,
    EXIT_OK,
    EXIT_USAGE,
    _exit_code,
    _parser,
    main,
)
from pgx.verification.model import Outcome, ProfileResult, SuiteSummary
from pgx.verification.profiles import profile_names

from tests.unit.verification._support import REPO_ROOT


def _run(*argv):
    stream = io.StringIO()
    code = main(["--root", REPO_ROOT] + list(argv), out=stream)
    return code, stream.getvalue()


def _result(outcome):
    return ProfileResult(
        profile="x", outcome=outcome,
        summary=SuiteSummary(1, 1, 1, 0, 0, 0, 0, 0))


class TestExitCodesAreDistinct(unittest.TestCase):

    def test_the_four_codes_are_different_numbers(self):
        self.assertEqual(len({EXIT_OK, EXIT_FAILED, EXIT_BLOCKED,
                              EXIT_USAGE}), 4)

    def test_only_success_is_zero(self):
        self.assertEqual(EXIT_OK, 0)
        for code in (EXIT_FAILED, EXIT_BLOCKED, EXIT_USAGE):
            self.assertNotEqual(code, 0)

    def test_a_failing_required_profile_returns_failed(self):
        self.assertEqual(_exit_code(_result(Outcome.FAIL), True), EXIT_FAILED)
        self.assertEqual(_exit_code(_result(Outcome.ERROR), True), EXIT_FAILED)

    def test_a_blocked_required_profile_returns_blocked_not_failed(self):
        """Nothing is known about it, which is not the same as it being
        broken, and a job that treated the two alike would either ignore real
        failures or block on every machine without PostgreSQL."""
        self.assertEqual(_exit_code(_result(Outcome.BLOCKED), True),
                         EXIT_BLOCKED)

    def test_a_passing_profile_returns_zero(self):
        self.assertEqual(_exit_code(_result(Outcome.PASS), True), EXIT_OK)

    def test_an_optional_profile_does_not_block_a_release(self):
        """The database profile. Its real state is still reported by the gate
        status as BLOCKED; what it does not do is stop the command."""
        self.assertEqual(_exit_code(_result(Outcome.BLOCKED), False), EXIT_OK)
        self.assertEqual(_exit_code(_result(Outcome.FAIL), False), EXIT_OK)

    def test_no_subcommand_at_all_is_a_usage_error(self):
        code, text = _run()
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("pgx-verify", text)


class TestTheOutputIsMachineReadable(unittest.TestCase):

    def test_the_inventory_emits_valid_json(self):
        code, text = _run("--format", "json", "inventory")
        self.assertEqual(code, EXIT_OK)
        document = json.loads(text)
        self.assertGreater(document["discovered_test_count"], 5000)

    def test_the_matrix_emits_valid_json(self):
        code, text = _run("--format", "json", "matrix")
        document = json.loads(text)
        self.assertIn("uncovered_requirements", document)
        self.assertEqual(code, EXIT_OK)

    def test_the_profiles_emit_valid_json(self):
        code, text = _run("--format", "json", "profiles")
        document = json.loads(text)
        self.assertEqual({item["name"] for item in document["profiles"]},
                         set(profile_names()))

    def test_the_text_form_is_readable_and_not_json(self):
        code, text = _run("profiles")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("fast", text)
        with self.assertRaises(ValueError):
            json.loads(text)

    def test_the_json_is_the_same_document_the_artifact_holds(self):
        """One data source for both, so a CI job reading the command and a
        person reading the file cannot see different numbers."""
        from pgx.verification.artifacts import INVENTORY_PATH, build_artifacts
        _, text = _run("--format", "json", "inventory")
        built = build_artifacts(REPO_ROOT)[INVENTORY_PATH]
        self.assertEqual(json.loads(text), json.loads(built))


class TestTheParser(unittest.TestCase):

    def test_every_profile_is_selectable(self):
        for name in profile_names():
            with self.subTest(profile=name):
                arguments = _parser().parse_args(["run", "--profile", name])
                self.assertEqual(arguments.profile, name)

    def test_an_unknown_profile_is_rejected_by_the_parser(self):
        """argparse writes its complaint to stderr, which is redirected here
        so a passing suite does not print a usage error."""
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                _parser().parse_args(["run", "--profile",
                                      "definitely-not-real"])

    def test_the_default_root_is_the_repository(self):
        arguments = _parser().parse_args(["inventory"])
        self.assertTrue(arguments.root)

    def test_the_format_choices_are_text_and_json(self):
        arguments = _parser().parse_args(["--format", "json", "inventory"])
        self.assertEqual(arguments.format, "json")
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                _parser().parse_args(["--format", "yaml", "inventory"])
