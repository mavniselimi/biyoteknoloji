# -*- coding: utf-8 -*-
"""Safety and integrity drills for the canonical layer (WP-07).

Every drill that could damage something runs against a **disposable copy**. The
real raw snapshot is never modified, and the first test in this file proves it
by re-verifying it after all the others have run.
"""

from __future__ import annotations

import io
import os
import shutil
import socket
import tempfile
import unittest

from pgx.ingestion.snapshots import SnapshotManager
from pgx.normalization.build import (CanonicalBuildRequest,
                                     build_canonical_dataset, verify_build,
                                     write_build)
from pgx.normalization.errors import CanonicalizationError
from pgx.normalization.models import RawLocator
from pgx.normalization.quality import evaluate_quality

from tests.unit.normalization._snapshot import (DATASET_ID, RAW_ROOT, REPO_ROOT,
                                                SOURCE_KEY,
                                                RealSnapshotTestCase,
                                                SyntheticSnapshotTestCase,
                                                make_writable)


class TestTheRealSnapshotIsNeverTouched(RealSnapshotTestCase):

    def test_it_verifies_intact(self):
        result = self.manager.verify(SOURCE_KEY, DATASET_ID)
        self.assertTrue(result.ok, [issue.render() for issue in result.issues])

    def test_no_wp07_module_writes_to_the_raw_root(self):
        """Read from the AST: no open-for-write, no makedirs, under data/raw."""
        import ast
        package = os.path.join(REPO_ROOT, "pgx", "normalization")
        for name in sorted(os.listdir(package)):
            if not name.endswith(".py"):
                continue
            with io.open(os.path.join(package, name), encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and \
                        isinstance(node.func, ast.Name) and \
                        node.func.id == "open":
                    modes = [argument.value for argument in node.args[1:]
                             if isinstance(argument, ast.Constant)]
                    for mode in modes:
                        with self.subTest(module=name, mode=mode):
                            self.assertNotIn("w", mode.replace("wb", "W")
                                             if name == "build.py" else mode)

    def test_a_build_leaves_the_snapshot_byte_identical(self):
        before = self.manager.inspect(SOURCE_KEY, DATASET_ID)
        build_canonical_dataset(CanonicalBuildRequest(
            snapshot_root=self.snapshot_path,
            output_root=self.temp_output(),
            allow_new_identities=True))
        after = self.manager.inspect(SOURCE_KEY, DATASET_ID)
        self.assertEqual(before.snapshot_content_hash,
                         after.snapshot_content_hash)
        self.assertEqual(before.manifest_hash, after.manifest_hash)


class TestChangedRawArtifactsAreDetected(SyntheticSnapshotTestCase):
    """On a throwaway snapshot. The real one is never corrupted."""

    FILES = {"responses/resolved_genes.json": {
        "CYP2C19": {"objCls": "Gene", "id": "PA124", "symbol": "CYP2C19",
                    "name": "cytochrome"}}}

    def test_a_flipped_byte_fails_snapshot_verification(self):
        snapshot = self.seal(self.FILES)
        target = os.path.join(snapshot, "responses", "resolved_genes.json")
        make_writable(snapshot)
        with io.open(target, "rb") as handle:
            data = bytearray(handle.read())
        data[-2] = data[-2] ^ 0x01
        with io.open(target, "wb") as handle:
            handle.write(bytes(data))
        result = SnapshotManager(self.raw_root).verify_path(snapshot)
        self.assertFalse(result.ok)
        self.assertIn("ARTIFACT_HASH_MISMATCH", result.codes)

    def test_a_locator_records_the_digest_that_would_expose_the_change(self):
        snapshot = self.seal(self.FILES)
        build = build_canonical_dataset(CanonicalBuildRequest(
            snapshot_root=snapshot, output_root=self.output_root(),
            allow_new_identities=True))
        recorded = {locator.artifact_sha256
                    for entity in build.entities
                    for locator in entity.locators}
        manifest = SnapshotManager(self.raw_root).inspect_path(snapshot)
        expected = {item.sha256 for item in manifest.artifacts}
        self.assertTrue(recorded.issubset(expected))


class TestChangedCanonicalArtifactsAreDetected(SyntheticSnapshotTestCase):

    def _sealed(self):
        snapshot = self.seal({"responses/resolved_genes.json": {
            "CYP2C19": {"objCls": "Gene", "id": "PA124", "symbol": "CYP2C19",
                        "name": "cytochrome"}}})
        root = self.output_root()
        build = build_canonical_dataset(CanonicalBuildRequest(
            snapshot_root=snapshot, output_root=root,
            allow_new_identities=True))
        return write_build(build, root, extra_documents={
            "dq-report.json": evaluate_quality(build).to_json()})

    def test_an_intact_build_verifies(self):
        ok, problems = verify_build(self._sealed().build_path)
        self.assertTrue(ok, problems)

    def test_an_edited_file_is_detected(self):
        result = self._sealed()
        target = os.path.join(result.build_path, "genes.ndjson")
        os.chmod(target, 0o600)
        with io.open(target, "ab") as handle:
            handle.write(b"\n")
        ok, problems = verify_build(result.build_path)
        self.assertFalse(ok)
        self.assertTrue(any("genes.ndjson" in problem for problem in problems))

    def test_a_removed_file_is_detected(self):
        result = self._sealed()
        target = os.path.join(result.build_path, "drugs.ndjson")
        os.chmod(result.build_path, 0o700)
        os.unlink(target)
        ok, problems = verify_build(result.build_path)
        self.assertFalse(ok)
        self.assertTrue(any("drugs.ndjson" in problem for problem in problems))

    def test_an_added_file_is_detected(self):
        result = self._sealed()
        os.chmod(result.build_path, 0o700)
        with io.open(os.path.join(result.build_path, "extra.ndjson"),
                     "w", encoding="utf-8") as handle:
            handle.write("{}\n")
        ok, problems = verify_build(result.build_path)
        self.assertFalse(ok)
        self.assertTrue(any("extra.ndjson" in problem for problem in problems))


class TestUnsafePathsAreRefused(unittest.TestCase):

    def _locator(self, artifact_path):
        return RawLocator(
            dataset_public_id=DATASET_ID,
            snapshot_manifest_hash="sha256:" + "3b" * 32,
            artifact_path=artifact_path,
            artifact_sha256="sha256:" + "7c" * 32,
            pointer="/x")

    def test_an_absolute_path_is_refused(self):
        for path in ("/etc/passwd", "/tmp/x.json"):
            with self.subTest(path=path):
                with self.assertRaises(CanonicalizationError):
                    self._locator(path)

    def test_a_traversing_path_is_refused(self):
        for path in ("../secrets.json", "a/../../b.json", "..", "a/.."):
            with self.subTest(path=path):
                with self.assertRaises(CanonicalizationError):
                    self._locator(path)

    def test_a_relative_path_is_accepted(self):
        self.assertEqual(
            self._locator("responses/resolved_genes.json").artifact_path,
            "responses/resolved_genes.json")


class TestSymlinksInASnapshotAreRefused(SyntheticSnapshotTestCase):

    def test_a_symlinked_artifact_is_refused_at_seal_time(self):
        """WP-06 refuses it; WP-07 therefore never reads one.

        Asserted here rather than assumed, because a canonical build that
        followed a symlink would record a locator pointing at bytes outside the
        snapshot.
        """
        source_dir = os.path.join(self.root, "symlink-source")
        os.makedirs(source_dir, exist_ok=True)
        real = os.path.join(self.root, "outside.json")
        with io.open(real, "w", encoding="utf-8") as handle:
            handle.write("{}")
        link = os.path.join(source_dir, "resolved_genes.json")
        try:
            os.symlink(real, link)
        except (OSError, NotImplementedError):
            self.skipTest("this filesystem does not support symlinks")

        from pgx.ingestion.snapshots import SnapshotBuildRequest, SnapshotKind
        result = self.manager.build(SnapshotBuildRequest(
            dataset_public_id="PGX-DATA-20260830-002",
            source_key="fixture-source",
            snapshot_kind=SnapshotKind.LEGACY_IMPORT,
            legacy_source_dir=source_dir,
            legacy_origin={"source_directory": "symlink-source"},
            limitations=("synthetic",)))
        self.assertFalse(result.sealed)
        self.assertIn("SYMLINK_PRESENT",
                      [issue.code.value for issue in result.issues])


class TestTheBuildMakesNoNetworkCall(SyntheticSnapshotTestCase):
    """Not an AST check: the socket module is disabled while a build runs."""

    def setUp(self):
        super().setUp()
        self._real_socket = socket.socket
        self._real_create = socket.create_connection

        def refuse(*args, **kwargs):
            raise AssertionError("a canonical build attempted a network call")

        socket.socket = refuse
        socket.create_connection = refuse
        self.addCleanup(self._restore)

    def _restore(self):
        socket.socket = self._real_socket
        socket.create_connection = self._real_create

    def test_a_full_build_completes_with_sockets_disabled(self):
        snapshot = self.seal({
            "responses/resolved_genes.json": {
                "CYP2C19": {"objCls": "Gene", "id": "PA124",
                            "symbol": "CYP2C19", "name": "cytochrome"}},
            "responses/resolved_chemicals.json": {
                "clopidogrel": {"objCls": "Chemical", "id": "PA449053",
                                "name": "clopidogrel"}},
        })
        root = self.output_root()
        build = build_canonical_dataset(CanonicalBuildRequest(
            snapshot_root=snapshot, output_root=root,
            allow_new_identities=True))
        report = evaluate_quality(build)
        result = write_build(build, root, extra_documents={
            "dq-report.json": report.to_json()})
        ok, problems = verify_build(result.build_path)
        self.assertTrue(ok, problems)


if __name__ == "__main__":
    unittest.main()
