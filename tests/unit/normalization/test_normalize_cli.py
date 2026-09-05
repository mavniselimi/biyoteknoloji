# -*- coding: utf-8 -*-
"""``pgx-normalize`` (WP-07).

The CLI is where a shortcut would be easiest to add and hardest to notice, so
most of what follows checks what it *cannot* do: approve an alias, name a
reviewer, settle an ambiguity, overwrite a sealed build, publish a dataset or
reach the network.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import io
import json
import os
import unittest

from pgx.application import normalize_cli
from pgx.application.normalize_cli import (EXIT_CONFIGURATION_FAILURE,
                                           EXIT_NOT_FOUND, EXIT_OK,
                                           EXIT_REFUSED, build_parser, main)

from tests.unit.normalization._snapshot import (REPO_ROOT, RealSnapshotTestCase,
                                                make_writable)

CLI = os.path.join("pgx", "application", "normalize_cli.py")
WRAPPER = os.path.join("scripts", "normalize.py")


def _source(relative: str) -> str:
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


def _run(argv):
    """Run the CLI, capturing stdout and returning ``(code, text)``."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(argv)
    return code, buffer.getvalue()


class TestTheParserOffersNoShortcut(unittest.TestCase):

    def _all_options(self):
        options = set()

        def walk(parser):
            for action in parser._actions:
                options.update(action.option_strings)
                if isinstance(action, argparse._SubParsersAction):
                    for sub in action.choices.values():
                        walk(sub)

        walk(build_parser())
        return options

    def test_there_is_no_force_or_overwrite_flag(self):
        options = self._all_options()
        for forbidden in ("--force", "-f", "--overwrite", "--replace",
                          "--clobber"):
            with self.subTest(option=forbidden):
                self.assertNotIn(forbidden, options)

    def test_there_is_no_reviewer_or_approval_flag(self):
        options = self._all_options()
        for forbidden in ("--reviewer", "--approve", "--approved-by",
                          "--as", "--approve-alias", "--sign-off",
                          "--quality-approve"):
            with self.subTest(option=forbidden):
                self.assertNotIn(forbidden, options)

    def test_there_is_no_pick_first_or_ranking_flag(self):
        options = self._all_options()
        for forbidden in ("--take-first", "--resolve-ambiguity", "--pick",
                          "--prefer-source", "--rank", "--auto-resolve"):
            with self.subTest(option=forbidden):
                self.assertNotIn(forbidden, options)

    def test_the_commands_are_exactly_the_documented_set(self):
        parser = build_parser()
        commands = set()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                commands.update(action.choices)
        self.assertEqual(commands, {
            "build", "verify", "inspect", "queue", "dq", "compare-legacy",
            "compare-builds", "quality-check"})

    def test_there_is_no_publish_or_activate_command(self):
        parser = build_parser()
        commands = set()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                commands.update(action.choices)
        for forbidden in ("publish", "activate", "release", "approve",
                          "promote", "decide"):
            with self.subTest(command=forbidden):
                self.assertNotIn(forbidden, commands)

    def test_minting_identities_requires_an_explicit_flag(self):
        parser = build_parser()
        args = parser.parse_args(["build", "--snapshot", "x"])
        self.assertFalse(args.allocate_new_identities)


class TestTheModuleReachesNoNetwork(unittest.TestCase):

    def test_it_imports_no_networking_module(self):
        tree = ast.parse(_source(CLI), filename=CLI)
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        for forbidden in ("requests", "urllib", "urllib.request", "http",
                          "http.client", "socket", "httpx", "aiohttp"):
            with self.subTest(module=forbidden):
                self.assertNotIn(forbidden, modules)

    def test_the_wrapper_only_delegates(self):
        tree = ast.parse(_source(WRAPPER), filename=WRAPPER)
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        self.assertLessEqual(len(calls), 6, "the wrapper should only delegate")
        self.assertIn("normalize_cli", _source(WRAPPER))


class TestTheCliOnTheRealSnapshot(RealSnapshotTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import shutil
        import tempfile
        cls._root = tempfile.mkdtemp(prefix="pgx-wp07-cli-")
        code, _ = _run(["build", "--snapshot", cls.snapshot_path,
                        "--out", cls._root, "--allocate-new-identities"])
        cls._build_code = code
        cls.build_path = os.path.join(cls._root, "PGX-DATA-20260830-900")

        def cleanup():
            make_writable(cls._root)
            shutil.rmtree(cls._root, ignore_errors=True)

        cls.addClassCleanup(cleanup)

    def test_build_succeeds_and_seals(self):
        self.assertEqual(self._build_code, EXIT_OK)
        self.assertTrue(os.path.isfile(
            os.path.join(self.build_path, "manifest.json")))

    def test_build_writes_the_legacy_difference_report(self):
        self.assertTrue(os.path.isfile(
            os.path.join(self.build_path, "legacy-differences.json")))

    def test_verify_passes_on_the_build_it_just_wrote(self):
        code, text = _run(["verify", "--build", self.build_path])
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(json.loads(text)["ok"])

    def test_inspect_reports_the_lifecycle_state(self):
        code, text = _run(["inspect", "--build", self.build_path])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(json.loads(text)["dataset_lifecycle_state"], "BUILDING")

    def test_quality_check_is_blocked_and_says_it_changed_nothing(self):
        code, text = _run(["quality-check", "--build", self.build_path])
        self.assertEqual(code, EXIT_REFUSED)
        payload = json.loads(text)
        self.assertFalse(payload["gate_passed"])
        self.assertIn("changes nothing", payload["effect"])
        self.assertEqual(payload["dataset_lifecycle_state"], "BUILDING")

    def test_quality_check_does_not_alter_the_build(self):
        before = os.path.getmtime(os.path.join(self.build_path, "manifest.json"))
        _run(["quality-check", "--build", self.build_path])
        after = os.path.getmtime(os.path.join(self.build_path, "manifest.json"))
        self.assertEqual(before, after)

    def test_dq_prints_the_stored_report(self):
        code, text = _run(["dq", "--build", self.build_path])
        self.assertEqual(code, EXIT_REFUSED, "the gate is blocked")
        payload = json.loads(text)
        self.assertEqual(payload["dq_report_version"], "pgx-data-quality/1")

    def test_queue_is_read_only_and_says_so(self):
        code, text = _run(["queue", "--build", self.build_path])
        self.assertEqual(code, EXIT_OK)
        payload = json.loads(text)
        self.assertIn("records no decision", payload["note"])
        self.assertEqual(payload["decided_count"], 0)

    def test_compare_legacy_reports_the_unexplained_claim(self):
        code, text = _run(["compare-legacy", "--build", self.build_path])
        self.assertEqual(code, EXIT_OK)
        payload = json.loads(text)
        checks = {item["claim_id"]: item for item in payload["claim_checks"]}
        self.assertTrue(checks["ARCH-8.3-DEDUP-COLLISIONS"]["is_surprising"])

    def test_rebuilding_over_a_sealed_build_is_refused(self):
        code, text = _run(["build", "--snapshot", self.snapshot_path,
                           "--out", self._root, "--allocate-new-identities"])
        self.assertEqual(code, EXIT_REFUSED)
        self.assertEqual(json.loads(text)["code"], "BUILD_ALREADY_EXISTS")

    def test_building_without_an_allocation_or_permission_is_refused(self):
        code, _ = _run(["build", "--snapshot", self.snapshot_path,
                        "--out", os.path.join(self._root, "second")])
        self.assertEqual(code, EXIT_REFUSED)

    def test_a_missing_snapshot_is_reported_as_not_found(self):
        code, text = _run(["build", "--snapshot", "/nonexistent/snapshot",
                           "--out", os.path.join(self._root, "third")])
        self.assertEqual(code, EXIT_NOT_FOUND)
        self.assertEqual(json.loads(text)["code"], "SNAPSHOT_MISSING")

    def test_a_missing_build_is_a_configuration_failure_not_a_crash(self):
        code, _ = _run(["dq", "--build", "/nonexistent/build"])
        self.assertEqual(code, EXIT_CONFIGURATION_FAILURE)

    def test_compare_builds_reports_reproducibility(self):
        second = os.path.join(self._root, "rebuild")
        code, _ = _run([
            "build", "--snapshot", self.snapshot_path, "--out", second,
            "--allocation", os.path.join(self.build_path,
                                         "identity-allocation.json")])
        self.assertEqual(code, EXIT_OK)
        code, text = _run([
            "compare-builds", "--left", self.build_path,
            "--right", os.path.join(second, "PGX-DATA-20260830-900")])
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(json.loads(text)["reproducible"])

    def test_text_output_never_prints_a_secret_looking_value(self):
        _, text = _run(["inspect", "--build", self.build_path, "--text"])
        for token in ("api_key", "authorization", "password", "token=",
                      "secret"):
            with self.subTest(token=token):
                self.assertNotIn(token, text.casefold())

    def test_the_real_snapshot_directory_is_untouched(self):
        """Every command above ran against the real snapshot; none may write."""
        from pgx.ingestion.snapshots import SnapshotManager
        result = SnapshotManager(
            os.path.join(REPO_ROOT, "data", "raw")).verify_path(
                self.snapshot_path)
        self.assertTrue(result.ok, [issue.render() for issue in result.issues])


if __name__ == "__main__":
    unittest.main()


class TestVerifyChecksThePublishedSchemas(RealSnapshotTestCase):
    """A schema that is published and never applied binds nobody."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import shutil
        import tempfile
        cls._root = tempfile.mkdtemp(prefix="pgx-wp07-schema-")
        _run(["build", "--snapshot", cls.snapshot_path, "--out", cls._root,
              "--allocate-new-identities"])
        cls.build_path = os.path.join(cls._root, "PGX-DATA-20260830-900")

        def cleanup():
            make_writable(cls._root)
            shutil.rmtree(cls._root, ignore_errors=True)

        cls.addClassCleanup(cleanup)

    def test_the_sealed_build_validates_against_both_schemas(self):
        code, text = _run(["verify", "--build", self.build_path])
        self.assertEqual(code, EXIT_OK)
        payload = json.loads(text)
        self.assertTrue(payload["schema_valid"], payload["schema_problems"])

    def test_a_manifest_that_leaves_the_schema_is_reported(self):
        """Edits a copy of the build, never the one the other tests read.

        Restoring by re-serialising would not restore the *bytes*, and the
        checksum check in the next test would fail for a reason that has
        nothing to do with schemas.
        """
        import shutil
        import tempfile
        scratch = tempfile.mkdtemp(prefix="pgx-wp07-schema-edit-")
        self.addCleanup(lambda: (make_writable(scratch),
                                 shutil.rmtree(scratch, ignore_errors=True)))
        copied = os.path.join(scratch, "build")
        shutil.copytree(self.build_path, copied)
        make_writable(copied)

        manifest_path = os.path.join(copied, "manifest.json")
        with io.open(manifest_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["dataset_lifecycle_state"] = "QUALITY_CHECKED"
        with io.open(manifest_path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload))

        code, text = _run(["verify", "--build", copied])
        self.assertEqual(code, EXIT_REFUSED)
        result = json.loads(text)
        self.assertFalse(result["schema_valid"])
        self.assertTrue(any("dataset_lifecycle_state" in problem
                            for problem in result["schema_problems"]))
