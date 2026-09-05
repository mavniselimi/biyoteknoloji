# -*- coding: utf-8 -*-
"""``pgx-curation-protocol``: what it does and what it has no way to do (WP-09).

The absences matter as much as the behaviour. A CLI that grew an ``approve``
flag would be a route from an unreviewed protocol to an approved one, and no
document would stop it.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import io
import json
import os
import unittest

from pgx.application.curation_protocol_cli import (EXIT_NOT_FOUND, EXIT_OK,
                                                   EXIT_REFUSED, build_parser,
                                                   main)

from tests.unit.curation._support import (EVIDENCE_BUILD, EXERCISE_DIR,
                                          REPO_ROOT, source_text)

CLI = os.path.join("pgx", "application", "curation_protocol_cli.py")


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(argv)
    text = out.getvalue()
    try:
        return code, json.loads(text)
    except ValueError:
        return code, text


class TestThereIsNoRouteToAnApproval(unittest.TestCase):

    FORBIDDEN_COMMANDS = ("approve", "approve-protocol", "approve-curation",
                          "accept-hint", "reject-hint", "curate", "generate",
                          "auto-review", "resolve-conflict", "publish",
                          "adjudicate", "sign")
    FORBIDDEN_FLAGS = ("--approve", "--approved-by", "--reviewer", "--as",
                       "--force", "--yes", "--auto", "--accept", "--sign")

    def setUp(self):
        self.parser = build_parser()
        self.commands = set()
        for action in self.parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                self.commands.update(action.choices)

    def test_the_command_set_is_exactly_what_wp09_needs(self):
        self.assertEqual(sorted(self.commands), [
            "approval-status", "compare", "exercise", "field",
            "inspect", "legacy-inventory", "validate"])

    def test_no_approving_command_exists(self):
        for name in self.FORBIDDEN_COMMANDS:
            self.assertNotIn(name, self.commands)

    def test_no_subcommand_offers_a_forbidden_flag(self):
        for action in self.parser._actions:
            if not isinstance(action, argparse._SubParsersAction):
                continue
            for name, sub in action.choices.items():
                options = set()
                for option in sub._actions:
                    options.update(option.option_strings)
                for forbidden in self.FORBIDDEN_FLAGS:
                    with self.subTest(command=name, flag=forbidden):
                        self.assertNotIn(forbidden, options)

    def test_it_imports_no_infrastructure(self):
        tree = ast.parse(source_text(CLI), filename=CLI)
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                self.assertFalse(module.startswith("pgx.infrastructure"))
                self.assertNotEqual(module.split(".")[0], "sqlalchemy")


class TestApprovalStatusReportsBlocked(unittest.TestCase):

    def test_it_reports_blocked_and_exits_non_zero(self):
        code, payload = run(["approval-status"])
        self.assertEqual(code, EXIT_REFUSED)
        self.assertEqual(payload["expert_approval"], "BLOCKED")

    def test_it_names_what_is_blocking(self):
        _, payload = run(["approval-status"])
        self.assertTrue(payload["blocked_by"])
        joined = " ".join(payload["blocked_by"]).lower()
        self.assertIn("no named scientific expert", joined)

    def test_it_names_the_human_actions_required(self):
        _, payload = run(["approval-status"])
        self.assertGreaterEqual(len(payload["human_actions_required"]), 3)

    def test_it_says_it_changes_nothing(self):
        _, payload = run(["approval-status"])
        self.assertIn("no approve command", payload["effect"].lower())


class TestValidateSeparatesTheTwoVerdicts(unittest.TestCase):

    def test_it_passes_technically_and_blocks_on_approval(self):
        code, payload = run(["validate"])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["technical_completeness"], "PASS")
        self.assertEqual(payload["expert_approval"], "BLOCKED")

    def test_the_checked_in_artifacts_pass_their_schemas(self):
        _, payload = run(["validate"])
        self.assertEqual(payload["schema_problems"], [])

    def test_a_wrong_expected_proposal_count_fails(self):
        code, payload = run(["validate", "--expect-proposals", "1"])
        self.assertEqual(code, EXIT_REFUSED)
        self.assertEqual(payload["technical_completeness"], "FAIL")

    def test_output_is_deterministic(self):
        first = run(["validate"])[1]
        second = run(["validate"])[1]
        self.assertEqual(first, second)


class TestReadOnlyCommands(unittest.TestCase):

    def test_inspect_prints_the_protocol_and_its_status(self):
        code, payload = run(["inspect"])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["status"], "AWAITING_EXPERT_REVIEW")
        self.assertFalse(payload["expert_approved"])

    def test_inspect_can_print_one_requirement(self):
        code, payload = run(["inspect", "--requirement", "CUR-PROT-009"])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["requirement_id"], "CUR-PROT-009")
        self.assertTrue(payload["test_reference"])

    def test_an_unknown_requirement_is_not_found(self):
        code, _ = run(["inspect", "--requirement", "CUR-PROT-999"])
        self.assertEqual(code, EXIT_NOT_FOUND)

    def test_field_prints_owner_and_null_meaning(self):
        code, payload = run(["field", "conclusion_state"])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["owner"], "CURATOR")
        self.assertTrue(payload["null_meaning"])
        self.assertTrue(payload["prohibited_interpretations"])

    def test_an_unknown_field_is_not_found(self):
        code, payload = run(["field", "no_such_field"])
        self.assertEqual(code, EXIT_NOT_FOUND)
        self.assertIn("available", payload)

    def test_legacy_inventory_reports_the_queue_and_reviews_nothing(self):
        code, payload = run(["legacy-inventory", "--limit", "3"])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["counts"]["proposal_count"], 1559)
        self.assertEqual(payload["counts"]["reviewed_count"], 0)
        self.assertIn("reviews nothing", payload["effect"])

    def test_exercise_reports_the_pending_status(self):
        if not os.path.isdir(EVIDENCE_BUILD):
            self.skipTest("no sealed evidence build")
        code, payload = run(["exercise"])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["status"], "AWAITING_HUMAN_CURATORS")
        self.assertGreater(payload["case_count"], 0)


class TestCompareRefusesIncompleteInput(unittest.TestCase):

    def test_two_blank_templates_are_refused(self):
        if not os.path.isdir(EXERCISE_DIR):
            self.skipTest("no exercise artifacts")
        code, payload = run([
            "compare",
            os.path.join(EXERCISE_DIR, "curator-a.template.json"),
            os.path.join(EXERCISE_DIR, "curator-b.template.json")])
        self.assertEqual(code, EXIT_REFUSED)
        self.assertIn("completed response", payload["error"])

    def test_a_missing_response_file_is_not_found(self):
        code, _ = run(["compare", "/nonexistent/a.json",
                       "/nonexistent/b.json"])
        self.assertEqual(code, EXIT_NOT_FOUND)
