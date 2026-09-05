# -*- coding: utf-8 -*-
"""The checked-in ``clinpgx_outputs_v2`` legacy snapshot.

Read-only throughout. This module verifies the real snapshot that ships with
the repository and never modifies it: a corruption drill against the actual
evidence would destroy the thing it was meant to check, so those drills live in
``test_snapshot_verification.py`` and run against temporary copies.

The assertions fall into two groups. The first is integrity - the bytes are
still what they were, and they are byte-identical to the legacy directory. The
second is honesty - the snapshot claims nothing about acquisition provenance,
completeness or approval that it cannot support.
"""

from __future__ import annotations

import hashlib
import io
import os
import unittest

from pgx.application.snapshot_schema import validate_snapshot_manifest
from pgx.ingestion.snapshots import (
    ArtifactKind,
    SnapshotKind,
    SnapshotManager,
    SnapshotState,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
RAW_ROOT = os.path.join(REPO_ROOT, "data", "raw")
SOURCE_KEY = "clinpgx-legacy-v2"
DATASET_ID = "PGX-DATA-20260830-900"
LEGACY_DIR = os.path.join(REPO_ROOT, "clinpgx_outputs_v2")


def _digest(path: str) -> str:
    digest = hashlib.sha256()
    with io.open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class LegacySnapshotTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.manager = SnapshotManager(RAW_ROOT)
        if not cls.manager.exists(SOURCE_KEY, DATASET_ID):
            raise unittest.SkipTest(
                "the legacy snapshot has not been built; run "
                "python3 scripts/import_legacy_snapshot.py")
        cls.manifest = cls.manager.inspect(SOURCE_KEY, DATASET_ID)
        cls.path = cls.manager.snapshot_path(SOURCE_KEY, DATASET_ID)


class TestItVerifies(LegacySnapshotTestCase):

    def test_it_verifies_intact(self):
        result = self.manager.verify(SOURCE_KEY, DATASET_ID)
        self.assertTrue(result.ok, [issue.render() for issue in result.issues])

    def test_it_satisfies_the_published_schema(self):
        self.assertEqual(validate_snapshot_manifest(self.manifest.payload()), ())

    def test_verification_recomputes_both_hashes(self):
        result = self.manager.verify(SOURCE_KEY, DATASET_ID,
                                     schema_validator=validate_snapshot_manifest)
        self.assertTrue(result.ok)
        self.assertEqual(result.manifest.manifest_hash,
                         self.manifest.manifest_hash)

    def test_the_checksum_file_covers_every_artifact(self):
        listed = set()
        with io.open(os.path.join(self.path, "checksums.sha256"),
                     encoding="utf-8") as handle:
            for line in handle.read().splitlines():
                listed.add(line.split("  ", 1)[1])
        expected = {item.relative_path for item in self.manifest.artifacts}
        expected.add("requests.ndjson")
        self.assertEqual(listed, expected)


class TestBytesArePreservedExactly(LegacySnapshotTestCase):

    def test_every_legacy_file_is_present_byte_for_byte(self):
        for name in sorted(os.listdir(LEGACY_DIR)):
            source = os.path.join(LEGACY_DIR, name)
            if not os.path.isfile(source):
                continue
            copied = os.path.join(self.path, "responses", name)
            with self.subTest(file=name):
                self.assertTrue(os.path.isfile(copied), copied)
                self.assertEqual(_digest(source), _digest(copied))

    def test_the_artifact_count_matches_the_legacy_directory(self):
        expected = len([name for name in os.listdir(LEGACY_DIR)
                        if os.path.isfile(os.path.join(LEGACY_DIR, name))])
        self.assertEqual(self.manifest.artifact_count, expected)

    def test_every_artifact_records_where_it_came_from(self):
        for descriptor in self.manifest.artifacts:
            with self.subTest(artifact=descriptor.relative_path):
                self.assertIsNotNone(descriptor.source_relative_path)
                self.assertEqual(descriptor.artifact_kind,
                                 ArtifactKind.LEGACY_FILE)

    def test_nothing_is_hard_linked_to_the_legacy_directory(self):
        """A hard link would let an edit to the original rewrite the snapshot."""
        for descriptor in self.manifest.artifacts:
            path = os.path.join(self.path, *descriptor.relative_path.split("/"))
            with self.subTest(artifact=descriptor.relative_path):
                self.assertEqual(os.stat(path).st_nlink, 1)

    def test_nothing_in_the_snapshot_is_a_symlink(self):
        for current, directories, files in os.walk(self.path, followlinks=False):
            for name in directories + files:
                with self.subTest(entry=name):
                    self.assertFalse(os.path.islink(os.path.join(current, name)))


class TestItIsQuarantinedAndHonest(LegacySnapshotTestCase):

    def test_it_is_marked_a_legacy_import(self):
        self.assertIs(self.manifest.snapshot_kind, SnapshotKind.LEGACY_IMPORT)

    def test_it_is_quarantined(self):
        self.assertIs(self.manifest.snapshot_state, SnapshotState.QUARANTINED)

    def test_it_is_not_publication_eligible(self):
        self.assertFalse(self.manifest.publication_eligible)

    def test_it_does_not_claim_completeness(self):
        self.assertFalse(self.manifest.complete)
        self.assertIn("unknown", self.manifest.completeness_basis.lower())

    def test_it_invents_no_acquisition_run(self):
        self.assertIsNone(self.manifest.acquisition_run_id)
        self.assertIsNone(self.manifest.acquisition_status)
        self.assertIsNone(self.manifest.acquisition_content_hash)
        self.assertIsNone(self.manifest.acquisition_manifest_hash)

    def test_the_request_log_is_empty_rather_than_reconstructed(self):
        """No request chronology exists, so none is invented."""
        self.assertIsNotNone(self.manifest.request_log)
        self.assertEqual(self.manifest.request_log.byte_length, 0)
        with io.open(os.path.join(self.path, "requests.ndjson"), "rb") as handle:
            self.assertEqual(handle.read(), b"")

    def test_no_artifact_claims_a_request_key(self):
        for descriptor in self.manifest.artifacts:
            with self.subTest(artifact=descriptor.relative_path):
                self.assertIsNone(descriptor.request_key)
                self.assertIsNone(descriptor.endpoint_id)
                self.assertIsNone(descriptor.page_number)

    def test_it_records_what_it_cannot_answer(self):
        self.assertGreaterEqual(len(self.manifest.limitations), 5)
        joined = " ".join(self.manifest.limitations).lower()
        for expected in ("acquisition run", "chronology", "completeness",
                         "policy", "canonical"):
            with self.subTest(topic=expected):
                self.assertIn(expected, joined)

    def test_it_names_its_origin_without_claiming_wp04(self):
        origin = self.manifest.legacy_origin
        self.assertIsNotNone(origin)
        self.assertEqual(origin["source_directory"], "clinpgx_outputs_v2")
        self.assertIn("legacy probe", origin["produced_by"])

    def test_it_is_not_registered_against_a_scientific_source_key(self):
        """The bytes are a project artifact of unknown provenance."""
        from pgx.scientific.policy import load_registry
        registry = load_registry()
        self.assertIsNone(registry.get(SOURCE_KEY))

    def test_the_scope_note_says_these_are_raw_bytes(self):
        note = self.manifest.payload()["scope_note"].lower()
        self.assertIn("raw source bytes", note)
        self.assertIn("not", note)


class TestTheLegacyDirectoryIsUntouched(LegacySnapshotTestCase):

    def test_every_legacy_file_still_exists(self):
        self.assertTrue(os.path.isdir(LEGACY_DIR))
        self.assertGreater(len(os.listdir(LEGACY_DIR)), 0)

    def test_the_snapshot_lives_outside_the_legacy_directory(self):
        self.assertFalse(os.path.abspath(self.path).startswith(
            os.path.abspath(LEGACY_DIR) + os.sep))

    def test_no_snapshot_metadata_was_written_into_the_legacy_directory(self):
        for name in ("manifest.json", "checksums.sha256", "requests.ndjson"):
            with self.subTest(file=name):
                self.assertFalse(os.path.exists(os.path.join(LEGACY_DIR, name)))


class TestTheDatasetIdentity(LegacySnapshotTestCase):

    def test_it_uses_the_documented_legacy_identifier(self):
        self.assertEqual(self.manifest.dataset_public_id, DATASET_ID)

    def test_it_does_not_collide_with_the_wp01_baseline_identity(self):
        from pgx.application.legacy_baseline import LEGACY_DATASET_PUBLIC_ID
        self.assertNotEqual(DATASET_ID, LEGACY_DATASET_PUBLIC_ID)

    def test_the_importer_pins_the_identity_rather_than_deriving_it(self):
        import ast
        path = os.path.join(REPO_ROOT, "scripts", "import_legacy_snapshot.py")
        with io.open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        assigned = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0],
                                                           ast.Name):
                try:
                    assigned[node.targets[0].id] = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    continue
        self.assertEqual(assigned.get("LEGACY_DATASET_PUBLIC_ID"), DATASET_ID)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
