# -*- coding: utf-8 -*-
"""What may become a snapshot, and how a snapshot is sealed.

Two halves. The first is the gate on the acquisition run: only a run whose
required endpoints demonstrably completed may become a snapshot, and the
demonstration is recomputed here rather than read from the manifest's own
status field. The second is finalisation: a staging directory beside the final
path, an atomic rename into it, and a refusal to touch anything that already
exists.
"""

from __future__ import annotations

import io
import os
import stat
import unittest

from pgx.ingestion.common.manifest import build_acquisition_manifest
from pgx.ingestion.common.models import (
    AcquisitionRunId, AcquisitionStatus, EndpointCompletion, EndpointOutcome,
    PaginationState,
)
from pgx.ingestion.snapshots import (
    SnapshotBuildRequest,
    SnapshotError,
    SnapshotIssueCode,
    SnapshotKind,
    SnapshotManager,
)
from pgx.verification.filesystem import MutationOutcome, denies_all_writers

from tests.unit.snapshots import _builders as builders
from tests.unit.snapshots._support import SnapshotTestCase


def _codes(result):
    return {issue.code for issue in result.issues}


class TestOnlyACompleteRunMayBecomeASnapshot(SnapshotTestCase):

    def test_a_complete_run_is_accepted(self):
        result = self.sealed()
        self.assertTrue(result.manifest.complete)
        self.assertEqual(result.manifest.warnings, ())

    def test_the_completeness_basis_says_it_was_recomputed(self):
        result = self.sealed()
        self.assertIn("recomputed", result.manifest.completeness_basis)

    def test_a_run_with_optional_warnings_is_accepted_and_keeps_them(self):
        cache, manifest = builders.run_with_optional_warning(
            os.path.join(self.root, "warned"))
        self.assertIs(manifest.status, AcquisitionStatus.COMPLETE_WITH_WARNINGS)
        result = self.sealed("PGX-DATA-20260830-001", cache=cache,
                             manifest=manifest)
        self.assertTrue(result.manifest.complete)
        self.assertEqual(len(result.manifest.warnings), 1)
        self.assertIn("optional_endpoint", result.manifest.warnings[0])

    def test_an_incomplete_required_endpoint_is_refused(self):
        cache, manifest = builders.run_with_incomplete_required(
            os.path.join(self.root, "partial"))
        result = self.build_acquisition("PGX-DATA-20260830-001", cache=cache,
                                        manifest=manifest)
        self.assertFalse(result.sealed)
        self.assertIn(SnapshotIssueCode.ACQUISITION_NOT_COMPLETE, _codes(result))

    def test_non_terminal_pagination_is_named_as_such(self):
        cache, manifest = builders.run_with_incomplete_required(
            os.path.join(self.root, "partial"))
        result = self.build_acquisition("PGX-DATA-20260830-001", cache=cache,
                                        manifest=manifest)
        self.assertIn(SnapshotIssueCode.PAGINATION_NOT_TERMINAL, _codes(result))

    def test_a_failed_run_is_refused(self):
        cache, _ = self.complete_run("failed")
        failed = build_acquisition_manifest(
            run_id=AcquisitionRunId("fixture-run-failed"),
            source_id=builders.SOURCE_KEY, started_at=builders.NOW,
            completed_at=builders.LATER,
            endpoints=(EndpointCompletion(
                endpoint_id="required_endpoint", required=True,
                outcome=EndpointOutcome.FAILED,
                pagination=PaginationState(0, 0, False, "request failed"),
                error_detail="fixture failure"),))
        self.assertIs(failed.status, AcquisitionStatus.FAILED)
        result = self.build_acquisition("PGX-DATA-20260830-001", cache=cache,
                                        manifest=failed)
        self.assertFalse(result.sealed)
        self.assertIn(SnapshotIssueCode.ACQUISITION_NOT_COMPLETE, _codes(result))

    def test_a_run_producing_nothing_is_refused(self):
        cache, _ = self.complete_run("empty")
        empty = build_acquisition_manifest(
            run_id=AcquisitionRunId("fixture-run-empty"),
            source_id=builders.SOURCE_KEY, started_at=builders.NOW,
            completed_at=builders.LATER,
            endpoints=(EndpointCompletion(
                endpoint_id="optional_endpoint", required=False,
                outcome=EndpointOutcome.SKIPPED,
                pagination=PaginationState(0, 0, True, "skipped")),))
        result = self.build_acquisition("PGX-DATA-20260830-001", cache=cache,
                                        manifest=empty)
        self.assertFalse(result.sealed)
        self.assertIn(SnapshotIssueCode.NO_ARTIFACTS, _codes(result))

    def test_nothing_is_written_when_the_run_is_refused(self):
        cache, manifest = builders.run_with_incomplete_required(
            os.path.join(self.root, "partial"))
        self.build_acquisition("PGX-DATA-20260830-001", cache=cache,
                               manifest=manifest)
        self.assertFalse(os.path.exists(
            self.manager.snapshot_path(builders.SOURCE_KEY,
                                       "PGX-DATA-20260830-001")))


class TestTheCacheIsReVerifiedWhileCopying(SnapshotTestCase):

    def test_a_missing_cache_blob_is_refused(self):
        cache, manifest = self.complete_run("gone")
        blob = cache.blob_path(manifest.endpoints[0].records[0].raw_sha256)
        os.chmod(os.path.dirname(blob), 0o700)
        os.unlink(blob)
        result = self.build_acquisition("PGX-DATA-20260830-001", cache=cache,
                                        manifest=manifest)
        self.assertFalse(result.sealed)
        self.assertIn(SnapshotIssueCode.CACHE_BLOB_MISSING, _codes(result))

    def test_a_corrupt_cache_blob_is_refused(self):
        cache, manifest = self.complete_run("corrupt")
        blob = cache.blob_path(manifest.endpoints[0].records[0].raw_sha256)
        os.chmod(os.path.dirname(blob), 0o700)
        with io.open(blob, "wb") as handle:
            handle.write(b'{"tampered": true}')
        result = self.build_acquisition("PGX-DATA-20260830-001", cache=cache,
                                        manifest=manifest)
        self.assertFalse(result.sealed)
        self.assertTrue(
            {SnapshotIssueCode.CACHE_BLOB_CORRUPT,
             SnapshotIssueCode.ARTIFACT_HASH_MISMATCH} & _codes(result))

    def test_a_byte_length_disagreement_is_refused(self):
        """The digest is right and the recorded length is not."""
        cache, manifest = self.complete_run("length")
        record = manifest.endpoints[0].records[0]
        lying = builders.record(record.request_key, builders.body(1))
        lying = type(lying)(
            **{**{field: getattr(lying, field)
                  for field in lying.__slots__}, "byte_length": 9999})
        broken = build_acquisition_manifest(
            run_id=AcquisitionRunId("fixture-run-length"),
            source_id=builders.SOURCE_KEY, started_at=builders.NOW,
            completed_at=builders.LATER,
            endpoints=(builders.endpoint([lying]),))
        result = self.build_acquisition("PGX-DATA-20260830-001", cache=cache,
                                        manifest=broken)
        self.assertFalse(result.sealed)
        self.assertIn(SnapshotIssueCode.ARTIFACT_LENGTH_MISMATCH, _codes(result))

    def test_two_records_sharing_a_key_with_different_content_are_refused(self):
        cache, _ = self.complete_run("collide")
        key = builders.request_key("page-1")
        first = builders.record(key, builders.body(1))
        second = builders.record(key, builders.body(2), page_number=2)
        builders.store(cache, key, builders.body(2))
        colliding = build_acquisition_manifest(
            run_id=AcquisitionRunId("fixture-run-collide"),
            source_id=builders.SOURCE_KEY, started_at=builders.NOW,
            completed_at=builders.LATER,
            endpoints=(builders.endpoint([first, second]),))
        result = self.build_acquisition("PGX-DATA-20260830-001", cache=cache,
                                        manifest=colliding)
        self.assertFalse(result.sealed)
        self.assertIn(SnapshotIssueCode.REQUEST_KEY_COLLISION, _codes(result))

    def test_two_records_sharing_a_key_with_identical_content_are_one_artifact(self):
        cache, _ = self.complete_run("dedupe")
        key = builders.request_key("page-1")
        data = builders.body(1)
        twice = builders.endpoint([builders.record(key, data),
                                   builders.record(key, data, page_number=2)])
        manifest = build_acquisition_manifest(
            run_id=AcquisitionRunId("fixture-run-dedupe"),
            source_id=builders.SOURCE_KEY, started_at=builders.NOW,
            completed_at=builders.LATER, endpoints=(twice,))
        result = self.sealed("PGX-DATA-20260830-001", cache=cache,
                             manifest=manifest)
        self.assertEqual(result.manifest.artifact_count, 1)


class TestFinalisation(SnapshotTestCase):

    def test_the_final_directory_holds_exactly_the_expected_entries(self):
        result = self.sealed()
        self.assertEqual(sorted(os.listdir(result.snapshot_path)),
                         ["checksums.sha256", "manifest.json", "requests.ndjson",
                          "responses"])

    def test_no_staging_directory_survives_a_successful_build(self):
        result = self.sealed()
        parent = os.path.dirname(result.snapshot_path)
        self.assertEqual([n for n in os.listdir(parent)
                          if n.startswith(".staging")], [])

    def test_no_claim_file_survives_a_successful_build(self):
        result = self.sealed()
        parent = os.path.dirname(result.snapshot_path)
        self.assertEqual([n for n in os.listdir(parent)
                          if n.endswith(".claim")], [])

    def test_no_staging_directory_survives_a_failed_build(self):
        cache, manifest = self.complete_run("gone")
        blob = cache.blob_path(manifest.endpoints[0].records[0].raw_sha256)
        os.chmod(os.path.dirname(blob), 0o700)
        os.unlink(blob)
        self.build_acquisition("PGX-DATA-20260830-001", cache=cache,
                               manifest=manifest)
        parent = os.path.join(self.raw_root, builders.SOURCE_KEY)
        leftovers = [n for n in os.listdir(parent)] if os.path.isdir(parent) else []
        self.assertEqual(leftovers, [])

    def test_an_existing_snapshot_is_never_overwritten(self):
        first = self.sealed("PGX-DATA-20260830-001")
        before = self._digest(first.snapshot_path)
        second = self.build_acquisition("PGX-DATA-20260830-001")
        self.assertFalse(second.sealed)
        self.assertIn(SnapshotIssueCode.SNAPSHOT_ALREADY_EXISTS, _codes(second))
        self.assertEqual(self._digest(first.snapshot_path), before)

    def test_identical_content_still_cannot_reclaim_a_dataset_id(self):
        """"The bytes are the same" is not a reason to reopen an identity."""
        self.sealed("PGX-DATA-20260830-001")
        again = self.build_acquisition("PGX-DATA-20260830-001")
        self.assertIn(SnapshotIssueCode.SNAPSHOT_ALREADY_EXISTS, _codes(again))

    def test_an_existing_empty_directory_also_blocks(self):
        """``os.rename`` would silently replace an empty target."""
        path = self.manager.snapshot_path(builders.SOURCE_KEY,
                                          "PGX-DATA-20260830-001")
        os.makedirs(path)
        result = self.build_acquisition("PGX-DATA-20260830-001")
        self.assertFalse(result.sealed)
        self.assertIn(SnapshotIssueCode.SNAPSHOT_ALREADY_EXISTS, _codes(result))

    def test_a_held_claim_blocks_a_concurrent_builder(self):
        path = self.manager.snapshot_path(builders.SOURCE_KEY,
                                          "PGX-DATA-20260830-001")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with io.open(path + ".claim", "wb") as handle:
            handle.write(b"")
        result = self.build_acquisition("PGX-DATA-20260830-001")
        self.assertFalse(result.sealed)
        self.assertIn(SnapshotIssueCode.DATASET_ID_ALREADY_CLAIMED,
                      _codes(result))

    def test_the_sealed_tree_is_read_only_where_supported(self):
        """The representation half: no writer has a write bit.

        Asserted as "no write bit for owner, group or other" as well as the
        exact ``0o444``, because the second is how it is spelled and the first
        is what is meant. Neither depends on who is running the suite, so
        neither is ever skipped where ``chmod`` sticks. The mutation half moved
        to the test below, which used to fail as ``uid 0``.
        """
        if not self.supports_permissions():
            self.skipTest("this filesystem ignores chmod; see docs/data/"
                          "raw-snapshot-format.md on the limits of the claim")
        result = self.sealed()
        manifest_path = os.path.join(result.snapshot_path, "manifest.json")
        self.assertEqual(stat.S_IMODE(os.stat(manifest_path).st_mode), 0o444)
        self.assertTrue(denies_all_writers(manifest_path),
                        "a sealed artifact must carry no write bit at all")

    def test_a_writer_subject_to_the_mode_bits_is_refused(self):
        """The mutation half, performed by somebody the bits apply to.

        This is the test that used to fail as ``uid 0``: the superuser is
        exempt from mode-bit checks, so the append succeeded on a perfectly
        well sealed tree. It is not repaired by deleting the attempt or by
        accepting either result - it is repaired by making the attempt from a
        process the bits actually govern, which on a root host means forking
        and dropping privileges.

        The skip that remains is narrow and names the missing capability. It
        cannot hide a writable tree: ``TestThePortabilityHandlingCannotHideA
        WritableTree`` below builds one and asserts this same helper reports it
        as ``PERMITTED``.
        """
        if not self.supports_permissions():
            self.skipTest("this filesystem ignores chmod; see docs/data/"
                          "raw-snapshot-format.md on the limits of the claim")
        result = self.sealed()
        manifest_path = os.path.join(result.snapshot_path, "manifest.json")
        attempt = self.mutation_attempt(manifest_path)
        if attempt.outcome is MutationOutcome.NOT_ATTEMPTABLE:
            self.skipTest("no writer subject to these mode bits can be "
                          "arranged on this host: %s" % attempt.detail)
        self.assertTrue(attempt.discriminating,
                        "an attempt that could not tell a writable tree apart "
                        "is not evidence: %s" % attempt.detail)
        self.assertIs(attempt.outcome, MutationOutcome.REFUSED, attempt.detail)

    @staticmethod
    def _digest(root: str) -> str:
        import hashlib
        digest = hashlib.sha256()
        for current, directories, files in os.walk(root):
            directories.sort()
            for name in sorted(files):
                path = os.path.join(current, name)
                digest.update(os.path.relpath(path, root).encode("utf-8"))
                with io.open(path, "rb") as handle:
                    digest.update(handle.read())
        return digest.hexdigest()


class TestThePortabilityHandlingCannotHideAWritableTree(SnapshotTestCase):
    """The guard on the guard.

    Making the immutability test portable introduced a way for it to say
    nothing: a host where no mutation attempt is possible skips, and a skip is
    easy to stop reading. These tests hold the other end down. They build a
    tree that is genuinely writable and require the same helper the real test
    uses to report it as ``PERMITTED``. If that ever stops happening, the
    portable path has become a place where a mutable snapshot can hide, and
    this class fails rather than the sealed-tree test quietly passing.
    """

    def _mutable_copy_of_a_sealed_tree(self, mode: int,
                                       dataset_id: str =
                                       "PGX-DATA-20260830-001") -> str:
        """A sealed snapshot with one artifact deliberately made writable.

        Built by sealing for real and then relaxing one file, so the tree is
        identical to a genuine snapshot in every other respect - the failure
        being simulated is "sealing did not take on this file", which is
        exactly the defect the mutation attempt exists to catch.
        """
        result = self.sealed(dataset_id)
        manifest_path = os.path.join(result.snapshot_path, "manifest.json")
        os.chmod(os.path.dirname(manifest_path), 0o755)
        os.chmod(manifest_path, mode)
        return manifest_path

    def test_a_manifest_left_owner_writable_is_reported_as_permitted(self):
        if not self.supports_permissions():
            self.skipTest("this filesystem ignores chmod")
        manifest_path = self._mutable_copy_of_a_sealed_tree(0o644)
        attempt = self.mutation_attempt(manifest_path)
        if attempt.outcome is MutationOutcome.NOT_ATTEMPTABLE:
            self.skipTest("no writer subject to these mode bits can be "
                          "arranged on this host: %s" % attempt.detail)
        self.assertIs(attempt.outcome, MutationOutcome.PERMITTED,
                      "a writable manifest was reported as %s; the portable "
                      "path can hide a mutable snapshot" % attempt.outcome)

    def test_a_manifest_left_world_writable_is_reported_as_permitted(self):
        if not self.supports_permissions():
            self.skipTest("this filesystem ignores chmod")
        manifest_path = self._mutable_copy_of_a_sealed_tree(0o666)
        attempt = self.mutation_attempt(manifest_path)
        if attempt.outcome is MutationOutcome.NOT_ATTEMPTABLE:
            self.skipTest("no writer subject to these mode bits can be "
                          "arranged on this host: %s" % attempt.detail)
        self.assertIs(attempt.outcome, MutationOutcome.PERMITTED)

    def test_the_bit_level_check_also_refuses_a_writable_manifest(self):
        """And this one cannot skip for a privilege reason at all.

        ``denies_all_writers`` reads the mode. Whatever the host's user model,
        a manifest with a write bit fails here, so the representation half of
        the invariant is protected even where no mutation attempt is possible.
        """
        if not self.supports_permissions():
            self.skipTest("this filesystem ignores chmod")
        modes = (0o644, 0o664, 0o666, 0o446, 0o464)
        for index, mode in enumerate(modes):
            # A distinct dataset id per iteration: an identity is claimed once,
            # so re-sealing the same one is refused - which is a different WP-06
            # invariant, tested elsewhere, and not the subject here.
            dataset_id = "PGX-DATA-20260830-%03d" % (700 + index)
            with self.subTest(mode=oct(mode)):
                manifest_path = self._mutable_copy_of_a_sealed_tree(
                    mode, dataset_id)
                self.assertFalse(denies_all_writers(manifest_path))

    def test_the_probe_leaves_the_artifact_byte_identical(self):
        """It opens for append and closes. It must not be a mutation itself."""
        if not self.supports_permissions():
            self.skipTest("this filesystem ignores chmod")
        result = self.sealed()
        manifest_path = os.path.join(result.snapshot_path, "manifest.json")
        with io.open(manifest_path, "rb") as handle:
            before_bytes = handle.read()
        before = os.stat(manifest_path)
        self.mutation_attempt(manifest_path)
        after = os.stat(manifest_path)
        with io.open(manifest_path, "rb") as handle:
            self.assertEqual(handle.read(), before_bytes)
        self.assertEqual(stat.S_IMODE(after.st_mode),
                         stat.S_IMODE(before.st_mode))
        self.assertEqual(after.st_uid, before.st_uid)
        self.assertEqual(after.st_gid, before.st_gid)
        self.assertEqual(after.st_size, before.st_size)

    def test_the_probe_changes_no_mode_inside_the_sealed_tree(self):
        """It may relax this test's scratch root. Not the snapshot."""
        if not self.supports_permissions():
            self.skipTest("this filesystem ignores chmod")
        result = self.sealed()
        snapshot_path = result.snapshot_path

        def modes():
            found = {}
            for current, directories, files in os.walk(snapshot_path):
                directories.sort()
                for name in sorted(directories) + sorted(files):
                    target = os.path.join(current, name)
                    found[os.path.relpath(target, snapshot_path)] = (
                        stat.S_IMODE(os.stat(target).st_mode))
            found["."] = stat.S_IMODE(os.stat(snapshot_path).st_mode)
            return found

        before = modes()
        self.mutation_attempt(os.path.join(snapshot_path, "manifest.json"))
        self.assertEqual(modes(), before)

    def test_the_probe_writes_no_scratch_into_the_sealed_tree(self):
        """The capability probe needs somewhere to write. Not in here."""
        if not self.supports_permissions():
            self.skipTest("this filesystem ignores chmod")
        result = self.sealed()
        manifest_path = os.path.join(result.snapshot_path, "manifest.json")
        before = sorted(os.listdir(result.snapshot_path))
        self.mutation_attempt(manifest_path)
        self.assertEqual(sorted(os.listdir(result.snapshot_path)), before)


class TestTheSealedApiOffersNoWrite(SnapshotTestCase):
    """The absence is the contract."""

    def test_the_manager_declares_no_mutating_method(self):
        for forbidden in ("write", "update", "append", "delete", "remove",
                          "reopen", "overwrite", "replace", "merge", "seal_again"):
            with self.subTest(name=forbidden):
                self.assertFalse(hasattr(SnapshotManager, forbidden))

    def test_the_manager_never_calls_os_replace(self):
        """``os.replace`` overwrites its target; that is the whole risk."""
        import ast
        import inspect
        from pgx.ingestion import snapshots
        tree = ast.parse(inspect.getsource(snapshots))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "replace":
                if isinstance(node.value, ast.Name) and node.value.id == "os":
                    self.fail("os.replace overwrites its target")

    def test_a_build_request_requires_an_explicit_dataset_id(self):
        with self.assertRaises(Exception):
            SnapshotBuildRequest(dataset_public_id="",
                                 source_key=builders.SOURCE_KEY,
                                 snapshot_kind=SnapshotKind.LEGACY_IMPORT,
                                 legacy_source_dir=self.root)

    def test_a_malformed_dataset_id_is_refused(self):
        with self.assertRaises(Exception):
            SnapshotBuildRequest(dataset_public_id="DATASET-1",
                                 source_key=builders.SOURCE_KEY,
                                 snapshot_kind=SnapshotKind.LEGACY_IMPORT,
                                 legacy_source_dir=self.root)

    def test_an_acquisition_build_needs_a_manifest_and_a_cache(self):
        with self.assertRaises(SnapshotError):
            SnapshotBuildRequest(dataset_public_id="PGX-DATA-20260830-001",
                                 source_key=builders.SOURCE_KEY,
                                 snapshot_kind=SnapshotKind.ACQUISITION)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
