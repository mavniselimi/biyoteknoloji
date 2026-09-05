# -*- coding: utf-8 -*-
"""``pgx-dataset``: what it does, and what it deliberately cannot do.

The negative assertions matter most. There is no ``publish`` command, no
``--force`` that rewrites a sealed snapshot, no argument that names a reviewer,
and no import that could reach the network. Each absence is checked by reading
the parser's own AST, so a flag added later fails here rather than in
production.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import unittest

from pgx.application import dataset_cli as cli

from tests.unit.snapshots import _builders as builders
from tests.unit.snapshots._support import SnapshotTestCase

CLI_PATH = os.path.abspath(cli.__file__)


def _run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CliTestCase(SnapshotTestCase):

    def legacy_dir(self) -> str:
        source = os.path.join(self.root, "legacy")
        os.makedirs(source, exist_ok=True)
        for name, data in (("a.json", b'{"a": 1}'), ("b.csv", b"x,y\n1,2\n")):
            with io.open(os.path.join(source, name), "wb") as handle:
                handle.write(data)
        return source

    def import_legacy(self, dataset_id="PGX-DATA-20260830-900"):
        return _run("import-legacy", "--dataset-id", dataset_id,
                    "--source-key", "legacy", "--source-dir", self.legacy_dir(),
                    "--raw-root", self.raw_root)


class TestImportLegacy(CliTestCase):

    def test_it_seals_and_exits_zero(self):
        code, out, _ = self.import_legacy()
        self.assertEqual(code, cli.EXIT_OK)
        self.assertTrue(json.loads(out)["snapshot"]["sealed"])

    def test_the_snapshot_is_quarantined_and_unpublishable(self):
        _code, out, _ = self.import_legacy()
        summary = json.loads(out)["snapshot"]["manifest"]
        self.assertEqual(summary["snapshot_state"], "QUARANTINED")
        self.assertEqual(summary["snapshot_kind"], "LEGACY_IMPORT")
        self.assertFalse(summary["publication_eligible"])

    def test_default_limitations_are_recorded(self):
        _code, out, _ = self.import_legacy()
        self.assertGreater(
            json.loads(out)["snapshot"]["manifest"]["limitation_count"], 0)

    def test_a_missing_source_directory_exits_not_found(self):
        code, _out, err = _run("import-legacy", "--dataset-id",
                               "PGX-DATA-20260830-900", "--source-key", "legacy",
                               "--source-dir", os.path.join(self.root, "nope"),
                               "--raw-root", self.raw_root)
        self.assertEqual(code, cli.EXIT_NOT_FOUND)
        self.assertEqual(json.loads(err)["error"], "not_found")

    def test_a_second_import_of_the_same_id_is_refused(self):
        self.import_legacy()
        code, out, _ = self.import_legacy()
        self.assertEqual(code, cli.EXIT_REFUSED)
        codes = {issue["code"] for issue in json.loads(out)["snapshot"]["issues"]}
        self.assertIn("SNAPSHOT_ALREADY_EXISTS", codes)


class TestVerifyInspectStatus(CliTestCase):

    def setUp(self):
        super().setUp()
        self.import_legacy()

    def test_verify_exits_zero_on_an_intact_snapshot(self):
        code, out, _ = _run("verify", "--dataset-id", "PGX-DATA-20260830-900",
                            "--source-key", "legacy", "--raw-root", self.raw_root)
        self.assertEqual(code, cli.EXIT_OK)
        self.assertTrue(json.loads(out)["ok"])

    def test_verify_exits_non_zero_and_names_every_problem(self):
        path = self.manager.snapshot_path("legacy", "PGX-DATA-20260830-900")
        self.flip_one_byte(path, "responses/a.json")
        self.add_file(path, "responses/intruder.json")
        code, out, _ = _run("verify", "--dataset-id", "PGX-DATA-20260830-900",
                            "--source-key", "legacy", "--raw-root", self.raw_root)
        self.assertEqual(code, cli.EXIT_REFUSED)
        codes = {issue["code"] for issue in json.loads(out)["issues"]}
        self.assertIn("ARTIFACT_HASH_MISMATCH", codes)
        self.assertIn("UNEXPECTED_FILE", codes)

    def test_inspect_prints_the_manifest(self):
        code, out, _ = _run("inspect", "--dataset-id", "PGX-DATA-20260830-900",
                            "--source-key", "legacy", "--raw-root", self.raw_root)
        self.assertEqual(code, cli.EXIT_OK)
        payload = json.loads(out)
        self.assertEqual(payload["dataset_public_id"], "PGX-DATA-20260830-900")
        self.assertIn("scope_note", payload)

    def test_verify_on_a_missing_snapshot_exits_not_found(self):
        """"There is no snapshot" and "this one is damaged" are different."""
        code, _out, err = _run("verify", "--dataset-id", "PGX-DATA-20260830-901",
                               "--source-key", "legacy", "--raw-root",
                               self.raw_root)
        self.assertEqual(code, cli.EXIT_NOT_FOUND)
        self.assertEqual(json.loads(err)["error"], "not_found")

    def test_inspect_on_a_missing_snapshot_exits_not_found(self):
        code, _out, _err = _run("inspect", "--dataset-id",
                                "PGX-DATA-20260830-901", "--source-key", "legacy",
                                "--raw-root", self.raw_root)
        self.assertEqual(code, cli.EXIT_NOT_FOUND)

    def test_status_reports_both_halves_and_changes_nothing(self):
        code, out, _ = _run("status", "--dataset-id", "PGX-DATA-20260830-900",
                            "--source-key", "legacy", "--raw-root", self.raw_root)
        self.assertEqual(code, cli.EXIT_OK)
        document = json.loads(out)
        self.assertTrue(document["snapshot_sealed"])
        self.assertIsNone(document["dataset_registered"])

    def test_register_without_a_database_reports_sealed_unregistered(self):
        code, out, _ = _run("register", "--dataset-id", "PGX-DATA-20260830-900",
                            "--source-key", "legacy", "--actor", "ops",
                            "--raw-root", self.raw_root)
        self.assertEqual(code, cli.EXIT_SEALED_UNREGISTERED)
        self.assertEqual(json.loads(out)["registration"], "SEALED_UNREGISTERED")

    def test_the_text_form_works_for_every_read_command(self):
        for command in ("verify", "inspect", "status"):
            with self.subTest(command=command):
                _code, out, _ = _run(command, "--dataset-id",
                                     "PGX-DATA-20260830-900", "--source-key",
                                     "legacy", "--raw-root", self.raw_root,
                                     "--text")
                self.assertTrue(out.strip())

    def test_no_output_contains_an_absolute_cache_or_home_path(self):
        _code, out, _ = _run("inspect", "--dataset-id", "PGX-DATA-20260830-900",
                             "--source-key", "legacy", "--raw-root",
                             self.raw_root)
        payload = json.loads(out)
        for descriptor in payload["artifacts"]:
            with self.subTest(artifact=descriptor["relative_path"]):
                self.assertFalse(descriptor["relative_path"].startswith("/"))


class TestBuildFromRun(CliTestCase):

    def test_a_missing_manifest_exits_not_found(self):
        code, _out, err = _run(
            "build-from-run", "--dataset-id", "PGX-DATA-20260830-001",
            "--source-key", builders.SOURCE_KEY,
            "--acquisition-manifest", os.path.join(self.root, "nope.json"),
            "--cache-dir", self.root, "--raw-root", self.raw_root)
        self.assertEqual(code, cli.EXIT_NOT_FOUND)
        self.assertEqual(json.loads(err)["error"], "not_found")

    def test_a_corrupt_manifest_is_refused(self):
        path = os.path.join(self.root, "bad.json")
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        code, _out, err = _run(
            "build-from-run", "--dataset-id", "PGX-DATA-20260830-001",
            "--source-key", builders.SOURCE_KEY,
            "--acquisition-manifest", path, "--cache-dir", self.root,
            "--raw-root", self.raw_root)
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertEqual(json.loads(err)["error"], "acquisition_manifest_invalid")

    def test_the_real_source_policy_refuses_a_build_today(self):
        cache, manifest = self.complete_run("cli")
        path = os.path.join(self.root, "run.json")
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(manifest.to_json()))
        code, out, _ = _run(
            "build-from-run", "--dataset-id", "PGX-DATA-20260830-001",
            "--source-key", "cpic.database", "--acquisition-manifest", path,
            "--cache-dir", cache.root, "--raw-root", self.raw_root)
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertFalse(json.loads(out)["snapshot"]["sealed"])


class TestTheCliCannotPublishOrOverwrite(unittest.TestCase):
    """The absence is the contract."""

    @classmethod
    def setUpClass(cls):
        with io.open(CLI_PATH, encoding="utf-8") as handle:
            cls.tree = ast.parse(handle.read(), filename=CLI_PATH)

    def _subcommands(self):
        return {node.args[0].value for node in ast.walk(self.tree)
                if isinstance(node, ast.Call)
                and getattr(node.func, "attr", None) == "add_parser"
                and node.args and isinstance(node.args[0], ast.Constant)}

    def _flags(self):
        flags = set()
        for node in ast.walk(self.tree):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "attr", None) == "add_argument"):
                for argument in node.args:
                    if isinstance(argument, ast.Constant) and isinstance(
                            argument.value, str):
                        flags.add(argument.value)
        return flags

    def test_the_subcommands_are_exactly_the_six_wp06_operations(self):
        self.assertEqual(
            self._subcommands(),
            {"build-from-run", "import-legacy", "verify", "inspect", "register",
             "status"})

    def test_there_is_no_publish_or_quality_check_command(self):
        for forbidden in ("publish", "quality-check", "approve", "promote",
                          "activate", "delete", "remove"):
            with self.subTest(subcommand=forbidden):
                self.assertNotIn(forbidden, self._subcommands())

    def test_there_is_no_force_or_overwrite_flag(self):
        for forbidden in ("--force", "--overwrite", "--replace", "--publish",
                          "--approved-by", "--reviewer", "--quality-checked"):
            with self.subTest(flag=forbidden):
                self.assertNotIn(forbidden, self._flags())

    def test_the_dataset_id_is_always_required(self):
        required = [node for node in ast.walk(self.tree)
                    if isinstance(node, ast.Call)
                    and getattr(node.func, "attr", None) == "add_argument"
                    and node.args
                    and getattr(node.args[0], "value", None) == "--dataset-id"]
        self.assertTrue(required)
        for node in required:
            keywords = {kw.arg: getattr(kw.value, "value", None)
                        for kw in node.keywords}
            self.assertTrue(keywords.get("required"))

    def test_it_opens_no_network_connection(self):
        modules = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        for forbidden in ("urllib", "urllib.request", "http", "http.client",
                          "socket", "ssl", "requests", "httpx"):
            with self.subTest(module=forbidden):
                self.assertNotIn(forbidden, modules)

    def test_it_needs_no_database_to_import(self):
        modules = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        for module in modules:
            with self.subTest(module=module):
                self.assertNotEqual(module.split(".")[0], "sqlalchemy")

    def test_the_default_raw_root_is_inside_the_repository(self):
        self.assertTrue(cli.DEFAULT_RAW_ROOT.endswith(os.path.join("data", "raw")))

    def test_the_wrapper_script_holds_no_logic(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        path = os.path.join(repo_root, "scripts", "dataset.py")
        with io.open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        defined = [node.name for node in ast.walk(tree)
                   if isinstance(node, (ast.FunctionDef, ast.ClassDef))]
        self.assertEqual(defined, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
