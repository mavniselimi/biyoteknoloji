# -*- coding: utf-8 -*-
"""``pgx-evidence``: what it does, and what it has no way to do (WP-08).

The absences are asserted as carefully as the behaviour. A CLI that grew an
``--approve`` flag would be a route from a quarantined legacy import to a
publishable claim, and no document would stop it.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from pgx.application import evidence_cli
from pgx.application.evidence_cli import (EXIT_CONFIGURATION_FAILURE,
                                          EXIT_NOT_FOUND, EXIT_OK,
                                          EXIT_REFUSED, ROW_FILES,
                                          build_parser, main)

from tests.unit.evidence._support import (CANONICAL_BUILD, DATASET_ID,
                                          EVIDENCE_BUILD, REPO_ROOT,
                                          SNAPSHOT_ROOT, source)

CLI = os.path.join("pgx", "application", "evidence_cli.py")


def run(argv):
    """Run the CLI, returning ``(exit_code, parsed_json_or_text)``."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(argv)
    text = out.getvalue()
    try:
        return code, json.loads(text)
    except ValueError:
        return code, text


class TestTheCliOffersNoRouteToAnApproval(unittest.TestCase):

    FORBIDDEN_COMMANDS = ("approve", "publish", "activate", "retire",
                          "rollback", "curate", "approve-curation",
                          "generate-rules", "quality-approve",
                          "source-policy-approve", "seed", "import-to-db")
    FORBIDDEN_FLAGS = ("--force", "--overwrite", "--reviewer", "--approve",
                       "--as", "--yes", "--no-verify", "--skip-gates",
                       "--allow-conflicts", "--take-first", "--resolve")

    def setUp(self):
        self.parser = build_parser()
        self.commands = set()
        for action in self.parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                self.commands.update(action.choices)

    def test_the_command_set_is_exactly_what_wp08_needs(self):
        self.assertEqual(sorted(self.commands), [
            "build", "compare-builds", "extract-draft-curation", "inspect",
            "issues", "list", "render-rows", "trace", "verify"])

    def test_no_promotion_command_exists(self):
        for name in self.FORBIDDEN_COMMANDS:
            self.assertNotIn(name, self.commands)

    def test_no_subcommand_offers_a_forbidden_flag(self):
        """Read from the parser, not from the source text: a flag added by a
        helper would not appear as a literal anywhere in the file."""
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

    def test_the_module_imports_no_infrastructure(self):
        tree = ast.parse(source(CLI), filename=CLI)
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                self.assertFalse(module.startswith("pgx.infrastructure"),
                                 "%s imports %s" % (CLI, module))
                self.assertNotEqual(module.split(".")[0], "sqlalchemy")

    def test_it_reaches_no_network(self):
        tree = ast.parse(source(CLI), filename=CLI)
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    names.update(alias.name.split(".")[0]
                                 for alias in node.names)
                elif node.module:
                    names.add(node.module.split(".")[0])
        for forbidden in ("requests", "urllib", "http", "socket", "httpx",
                          "aiohttp"):
            self.assertNotIn(forbidden, names)


class TestArgumentsThatMustBeExplicit(unittest.TestCase):

    def _required(self, command):
        parser = build_parser()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                sub = action.choices[command]
                return {option.dest for option in sub._actions
                        if getattr(option, "required", False)}
        return set()

    def test_build_requires_the_dataset_and_both_input_paths(self):
        required = self._required("build")
        for name in ("dataset_id", "snapshot", "canonical_build"):
            self.assertIn(name, required)

    def test_identity_allocation_is_opt_in_and_defaults_to_refusing(self):
        parser = build_parser()
        args = parser.parse_args(["build", "--dataset-id", DATASET_ID,
                                  "--snapshot", "s", "--canonical-build", "c"])
        self.assertFalse(args.allocate_new_identities)
        self.assertIsNone(args.allocation)

    def test_the_default_mode_is_the_one_that_fails_closed(self):
        parser = build_parser()
        args = parser.parse_args(["build", "--dataset-id", DATASET_ID,
                                  "--snapshot", "s", "--canonical-build", "c"])
        self.assertEqual(args.mode, "PRODUCTION")

    def test_output_is_json_unless_text_is_asked_for(self):
        parser = build_parser()
        args = parser.parse_args(["inspect", "--build", "b"])
        self.assertFalse(args.text)


class TestExitCodesAreStable(unittest.TestCase):

    def setUp(self):
        if not os.path.isdir(EVIDENCE_BUILD):
            self.skipTest("no sealed evidence build in this checkout")

    def test_a_missing_build_is_not_found(self):
        code, _ = run(["inspect", "--build", "/nonexistent/build"])
        self.assertEqual(code, EXIT_NOT_FOUND)

    def test_a_missing_record_is_not_found(self):
        code, payload = run(["trace", "--build", EVIDENCE_BUILD,
                             "--record", "no-such-uuid"])
        self.assertEqual(code, EXIT_NOT_FOUND)
        self.assertEqual(payload["code"], "RECORD_NOT_FOUND")

    def test_two_record_selectors_is_a_configuration_failure(self):
        code, _ = run(["trace", "--build", EVIDENCE_BUILD,
                       "--record", "a", "--natural-key", "b"])
        self.assertEqual(code, EXIT_CONFIGURATION_FAILURE)

    def test_neither_record_selector_is_a_configuration_failure(self):
        code, _ = run(["trace", "--build", EVIDENCE_BUILD])
        self.assertEqual(code, EXIT_CONFIGURATION_FAILURE)

    def test_two_entity_selectors_is_a_configuration_failure(self):
        code, payload = run(["list", "--build", EVIDENCE_BUILD,
                             "--gene", "GENE:CYP2C19",
                             "--drug", "DRUG:clopidogrel"])
        self.assertEqual(code, EXIT_CONFIGURATION_FAILURE)
        self.assertEqual(payload["code"], "AMBIGUOUS_SELECTION")

    def test_a_title_is_refused_as_a_publication_address(self):
        code, _ = run(["list", "--build", EVIDENCE_BUILD,
                       "--publication", "Some paper title"])
        self.assertEqual(code, EXIT_REFUSED)

    def test_inspect_succeeds_and_reports_the_quarantine(self):
        code, payload = run(["inspect", "--build", EVIDENCE_BUILD])
        self.assertEqual(code, EXIT_OK)
        self.assertFalse(payload["production_eligible"])
        self.assertIn("QUARANTINED", payload["lifecycle_labels"])
        self.assertEqual(payload["dataset_lifecycle_state"], "BUILDING")

    def test_a_dataset_id_that_contradicts_the_inputs_writes_nothing(self):
        if not (os.path.isdir(SNAPSHOT_ROOT)
                and os.path.isdir(CANONICAL_BUILD)):
            self.skipTest("no sealed inputs")
        out = tempfile.mkdtemp(prefix="wp08-cli-mismatch-")
        self.addCleanup(shutil.rmtree, out, True)
        code, payload = run(["build", "--dataset-id", "PGX-DATA-19990101-001",
                             "--mode", "LEGACY_MIGRATION",
                             "--snapshot", SNAPSHOT_ROOT,
                             "--canonical-build", CANONICAL_BUILD,
                             "--out", out, "--allocate-new-identities"])
        self.assertEqual(code, EXIT_CONFIGURATION_FAILURE)
        self.assertEqual(payload["code"], "DATASET_ID_MISMATCH")
        self.assertEqual(os.listdir(out), [])

    def test_production_mode_refuses_the_quarantined_snapshot(self):
        if not (os.path.isdir(SNAPSHOT_ROOT)
                and os.path.isdir(CANONICAL_BUILD)):
            self.skipTest("no sealed inputs")
        out = tempfile.mkdtemp(prefix="wp08-cli-production-")
        self.addCleanup(shutil.rmtree, out, True)
        code, payload = run(["build", "--dataset-id", DATASET_ID,
                             "--snapshot", SNAPSHOT_ROOT,
                             "--canonical-build", CANONICAL_BUILD,
                             "--out", out, "--allocate-new-identities"])
        self.assertEqual(code, EXIT_REFUSED)
        self.assertEqual(payload["code"], "IMPORT_REFUSED")
        self.assertEqual(os.listdir(out), [])


class TestReadOnlyCommandsOverTheRealBuild(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(EVIDENCE_BUILD):
            raise unittest.SkipTest("no sealed evidence build")

    def test_list_reports_what_it_truncated(self):
        code, payload = run(["list", "--build", EVIDENCE_BUILD, "--limit", "3"])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["shown"], 3)
        self.assertTrue(payload["truncated"])
        self.assertGreater(payload["matched"], 3)

    def test_a_listing_line_carries_no_source_text(self):
        _, payload = run(["list", "--build", EVIDENCE_BUILD, "--limit", "2"])
        for row in payload["records"]:
            for forbidden in ("text", "source_text", "summary", "fragments"):
                self.assertNotIn(forbidden, row)

    def test_issues_counts_are_reported_by_code(self):
        code, payload = run(["issues", "--build", EVIDENCE_BUILD,
                             "--counts-only"])
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(payload["counts_by_code"])
        self.assertIn("BLOCKING", payload["counts_by_severity"])

    def test_render_rows_writes_one_file_per_table_and_refuses_a_second_run(self):
        out = tempfile.mkdtemp(prefix="wp08-rows-")
        shutil.rmtree(out)
        self.addCleanup(shutil.rmtree, out, True)
        code, payload = run(["render-rows", "--build", EVIDENCE_BUILD,
                             "--out", out])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(sorted(os.listdir(out)), sorted(ROW_FILES))
        self.assertGreater(payload["total_rows"], 0)

        code, payload = run(["render-rows", "--build", EVIDENCE_BUILD,
                             "--out", out])
        self.assertEqual(code, EXIT_REFUSED)
        self.assertEqual(payload["code"], "OUTPUT_EXISTS")

    def test_render_rows_records_a_relative_build_path(self):
        out = tempfile.mkdtemp(prefix="wp08-rows-rel-")
        shutil.rmtree(out)
        self.addCleanup(shutil.rmtree, out, True)
        run(["render-rows", "--build", EVIDENCE_BUILD, "--out", out])
        with io.open(os.path.join(out, "evidence_builds.ndjson"),
                     encoding="utf-8") as handle:
            row = json.loads(handle.readline())
        self.assertFalse(os.path.isabs(row["build_relative_path"]))
        self.assertNotIn("..", row["build_relative_path"])

    def test_a_trace_re_derives_from_the_raw_bytes_when_asked(self):
        if not os.path.isdir(SNAPSHOT_ROOT):
            self.skipTest("no sealed snapshot")
        _, listing = run(["list", "--build", EVIDENCE_BUILD, "--limit", "1"])
        record_uuid = listing["records"][0]["record_uuid"]
        code, payload = run(["trace", "--build", EVIDENCE_BUILD,
                             "--record", record_uuid,
                             "--verify-against-raw", SNAPSHOT_ROOT])
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(payload["trace_ok"])
        self.assertEqual(payload["trace_problems"], [])
