# -*- coding: utf-8 -*-
"""The controlled WP-01 manifest amendment (WP-02 corrective, section 7).

One WP-01 evidence file - a regression test - became obsolete when WP-02
legitimately introduced ``pyproject.toml`` and the ``pgx`` package. The human
reviewer authorised amending that single test and re-pinning its hash, with
explicit limits: no rebuild, no new artifacts, the 64 legacy and 22 evidence
counts preserved, and an audit record in the manifest.

These tests live in the WP-02 suite on purpose. The WP-01 regression suite
hashes its own files, so adding assertions there would have widened the change
beyond the one file that was authorised.

What is proven here:

* the amendment record exists and carries reason, date, old hash, new hash and
  the agreed note;
* the recorded new hash is the file actually on disk;
* the legacy artifact count and the evidence artifact count are untouched;
* no WP-02 path was absorbed into either artifact list;
* the amendment tool refuses to touch a legacy artifact, refuses to invent an
  entry, and refuses to run when anything other than the amended file drifted.

Standard library only.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

MANIFEST_PATH = os.path.join(REPO_ROOT, "data", "legacy-baseline", "manifest.json")

AMENDED_PATH = "tests/regression/legacy/test_legacy_reproduction.py"
AGREED_NOTE = "WP-02 phase transition; legacy artifacts unchanged"
OLD_SHA = "474e1793360182295ce2f671209e93da795229fd5cdfaf8063fe615297220681"

EXPECTED_LEGACY = 64
EXPECTED_EVIDENCE = 22

#: Paths created by WP-02 that must never enter the WP-01 baseline.
WP02_PATHS = (
    "pyproject.toml", "README.md", "docker-compose.yml", ".env.example",
    "alembic.ini", "pgx/domain/models.py", "pgx/domain/immutable.py",
    "pgx/infrastructure/db/config.py", "pgx/infrastructure/db/cli_seed.py",
    "migrations/versions/0001_wp02_foundation.py",
    "scripts/amend_legacy_manifest.py",
)

HAVE_MANIFEST = os.path.isfile(MANIFEST_PATH)


def _manifest() -> dict:
    with io.open(MANIFEST_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def _sha256(relative: str) -> str:
    digest = hashlib.sha256()
    with io.open(os.path.join(REPO_ROOT, relative), "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class BaselineRequired(unittest.TestCase):
    """Fails - never skips - when the baseline is missing.

    The baseline is a committed WP-01 artifact. A skip here would read as a
    pass in a report, which is exactly the failure mode this project rejects.
    """

    @classmethod
    def setUpClass(cls):
        if not HAVE_MANIFEST:
            raise AssertionError(
                "the WP-01 baseline manifest is missing at %s; it is a required "
                "committed artifact, so this is a failure, not a skip"
                % MANIFEST_PATH)
        cls.manifest = _manifest()


class TestTheAmendmentIsRecorded(BaselineRequired):

    def _record(self) -> dict:
        records = [item for item in self.manifest.get("amendments", [])
                   if item["path"] == AMENDED_PATH]
        self.assertEqual(len(records), 1,
                         "expected exactly one amendment for %s" % AMENDED_PATH)
        return records[0]

    def test_the_manifest_carries_an_amendments_list(self):
        self.assertIsInstance(self.manifest.get("amendments"), list)

    def test_the_record_names_the_amended_file(self):
        self.assertEqual(self._record()["path"], AMENDED_PATH)

    def test_the_record_carries_a_reason(self):
        reason = self._record()["reason"]
        self.assertGreater(len(reason), 40, "the reason must be explanatory")

    def test_the_record_carries_the_agreed_note(self):
        self.assertEqual(self._record()["note"], AGREED_NOTE)

    def test_the_record_carries_an_iso_date(self):
        stamp = self._record()["amended_at_utc"]
        self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}$")

    def test_the_record_carries_the_old_hash(self):
        self.assertEqual(self._record()["old_sha256"], OLD_SHA)

    def test_the_record_carries_a_different_new_hash(self):
        record = self._record()
        self.assertNotEqual(record["new_sha256"], record["old_sha256"])

    def test_the_record_states_that_no_rebuild_was_performed(self):
        self.assertIs(self._record()["rebuild_performed"], False)

    def test_the_record_states_how_many_legacy_artifacts_were_verified(self):
        self.assertEqual(self._record()["legacy_artifacts_verified_unchanged"],
                         EXPECTED_LEGACY)


class TestTheAmendedEntryMatchesDisk(BaselineRequired):

    def _entry(self) -> dict:
        entries = [item for item in self.manifest["evidence_artifacts"]
                   if item["path"] == AMENDED_PATH]
        self.assertEqual(len(entries), 1)
        return entries[0]

    def test_the_pinned_hash_is_the_file_on_disk(self):
        self.assertEqual(self._entry()["sha256"], _sha256(AMENDED_PATH))

    def test_the_pinned_size_is_the_file_on_disk(self):
        self.assertEqual(self._entry()["size_bytes"],
                         os.path.getsize(os.path.join(REPO_ROOT, AMENDED_PATH)))

    def test_the_pinned_hash_matches_the_amendment_record(self):
        record = [item for item in self.manifest["amendments"]
                  if item["path"] == AMENDED_PATH][0]
        self.assertEqual(self._entry()["sha256"], record["new_sha256"])

    def test_the_entry_kept_its_role_and_required_flag(self):
        entry = self._entry()
        self.assertEqual(entry["evidence_role"], "wp01_regression_test")
        self.assertIs(entry["required"], True)


class TestTheBaselineScopeIsUnchanged(BaselineRequired):

    def test_the_legacy_artifact_count_is_unchanged(self):
        self.assertEqual(len(self.manifest["artifacts"]), EXPECTED_LEGACY)

    def test_the_evidence_artifact_count_is_unchanged(self):
        self.assertEqual(len(self.manifest["evidence_artifacts"]),
                         EXPECTED_EVIDENCE)

    def test_the_declared_counts_agree_with_the_lists(self):
        counts = self.manifest["artifact_counts"]
        self.assertEqual(counts["legacy_and_wp00"], EXPECTED_LEGACY)
        self.assertEqual(counts["wp01_evidence"], EXPECTED_EVIDENCE)

    def test_every_legacy_artifact_hash_still_matches_disk(self):
        mismatched = []
        for entry in self.manifest["artifacts"]:
            absolute = os.path.join(REPO_ROOT, entry["path"])
            if not os.path.isfile(absolute):
                mismatched.append((entry["path"], "MISSING"))
            elif _sha256(entry["path"]) != entry["sha256"]:
                mismatched.append((entry["path"], "SHA256"))
        self.assertEqual(mismatched, [])

    def test_no_legacy_artifact_was_amended(self):
        amended = {item["path"] for item in self.manifest.get("amendments", [])}
        legacy = {entry["path"] for entry in self.manifest["artifacts"]}
        self.assertEqual(amended & legacy, set())

    def test_no_wp02_path_entered_the_baseline(self):
        owned = ({entry["path"] for entry in self.manifest["artifacts"]}
                 | {entry["path"] for entry in self.manifest["evidence_artifacts"]})
        for path in WP02_PATHS:
            with self.subTest(path=path):
                self.assertNotIn(path, owned)

    def test_no_infrastructure_or_migration_path_is_owned(self):
        owned = ({entry["path"] for entry in self.manifest["artifacts"]}
                 | {entry["path"] for entry in self.manifest["evidence_artifacts"]})
        for path in owned:
            self.assertFalse(path.startswith("pgx/infrastructure/"), path)
            self.assertFalse(path.startswith("migrations/"), path)


class TestTheAmendmentToolRefusesUnsafeChanges(BaselineRequired):
    """The guard rails, exercised on a copy so the real manifest is untouched."""

    def setUp(self):
        import tempfile

        import amend_legacy_manifest as tool

        self.tool = tool
        self.directory = tempfile.mkdtemp(prefix="wp02-amendment-")
        self.copy = os.path.join(self.directory, "manifest.json")
        with io.open(self.copy, "w", encoding="utf-8") as handle:
            json.dump(_manifest(), handle)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.directory, ignore_errors=True)

    def _amend(self, path, apply_changes=False):
        # The tool prints a human-readable summary; keep it out of test output.
        with contextlib.redirect_stdout(io.StringIO()):
            return self.tool.amend(
                self.copy, path, "reason", "note", apply_changes)

    def test_it_refuses_to_amend_a_legacy_artifact(self):
        legacy_path = self.manifest["artifacts"][0]["path"]
        with self.assertRaises(self.tool.AmendmentRefused) as caught:
            self._amend(legacy_path)
        self.assertIn("legacy", str(caught.exception))

    def test_it_refuses_to_invent_an_entry(self):
        with self.assertRaises(self.tool.AmendmentRefused) as caught:
            self._amend("pyproject.toml")
        self.assertIn("expected exactly 1", str(caught.exception))

    def test_it_refuses_when_the_file_already_matches(self):
        with self.assertRaises(self.tool.AmendmentRefused) as caught:
            self._amend(AMENDED_PATH)
        self.assertIn("nothing to amend", str(caught.exception))

    def test_it_refuses_when_a_second_evidence_file_also_drifted(self):
        document = _manifest()
        others = [entry for entry in document["evidence_artifacts"]
                  if entry["path"] != AMENDED_PATH]
        others[0]["sha256"] = "0" * 64
        entry = [item for item in document["evidence_artifacts"]
                 if item["path"] == AMENDED_PATH][0]
        entry["sha256"] = "1" * 64
        with io.open(self.copy, "w", encoding="utf-8") as handle:
            json.dump(document, handle)
        with self.assertRaises(self.tool.AmendmentRefused) as caught:
            self._amend(AMENDED_PATH)
        self.assertIn("exactly one file", str(caught.exception))

    def test_it_refuses_when_the_legacy_scope_already_changed(self):
        document = _manifest()
        document["artifacts"] = document["artifacts"][:-1]
        with io.open(self.copy, "w", encoding="utf-8") as handle:
            json.dump(document, handle)
        with self.assertRaises(self.tool.AmendmentRefused) as caught:
            self._amend(AMENDED_PATH)
        self.assertIn("legacy artifact count", str(caught.exception))

    def test_a_dry_run_writes_nothing(self):
        document = _manifest()
        entry = [item for item in document["evidence_artifacts"]
                 if item["path"] == AMENDED_PATH][0]
        entry["sha256"] = OLD_SHA
        entry["size_bytes"] = 17810
        with io.open(self.copy, "w", encoding="utf-8") as handle:
            json.dump(document, handle)
        with io.open(self.copy, encoding="utf-8") as handle:
            before = handle.read()
        record = self._amend(AMENDED_PATH, apply_changes=False)
        self.assertEqual(record["old_sha256"], OLD_SHA)
        with io.open(self.copy, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), before)

    def test_it_never_re_runs_the_baseline_builder(self):
        """Checked against imports and code, not the docstring that says so."""
        with io.open(os.path.join(SCRIPTS_DIR, "amend_legacy_manifest.py"),
                     encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertNotIn("build_legacy_baseline", imported)
        self.assertNotIn("subprocess", imported)
        called = {node.func.id for node in ast.walk(tree)
                  if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Name)}
        self.assertNotIn("collect_artifacts", called)
        self.assertNotIn("build_manifest", called)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
