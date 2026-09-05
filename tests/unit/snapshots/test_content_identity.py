# -*- coding: utf-8 -*-
"""The three hash identities WP-06 keeps apart.

* *artifact hash* - SHA-256 of one file's exact bytes;
* *snapshot content hash* - what was captured, independent of where and when;
* *manifest hash* - this document, dataset ID and creation instant included.

The property that matters most is the second one's independence. A cache replay
must produce the same content hash as the network run it replays, or "we have
the same data" would be unanswerable without re-downloading it. Everything
below is a way of checking that the things which should not affect content
identity do not.
"""

from __future__ import annotations

import datetime as _dt
import io
import os
import unittest

from pgx.ingestion.common.models import CacheState
from pgx.ingestion.snapshots import (
    ArtifactKind,
    RawArtifactDescriptor,
    SnapshotKind,
    SnapshotManager,
    snapshot_content_hash,
    snapshot_manifest_hash,
)

from tests.unit.snapshots import _builders as builders
from tests.unit.snapshots._support import SnapshotTestCase


class TestArtifactHashes(SnapshotTestCase):

    def test_the_same_bytes_give_the_same_artifact_hash(self):
        first = self.sealed("PGX-DATA-20260830-001")
        second = self.sealed("PGX-DATA-20260830-002")
        self.assertEqual(
            [item.sha256 for item in first.manifest.artifacts],
            [item.sha256 for item in second.manifest.artifacts])

    def test_the_artifact_hash_is_of_the_bytes_on_disk(self):
        import hashlib
        result = self.sealed()
        for descriptor in result.manifest.artifacts:
            path = os.path.join(result.snapshot_path,
                                *descriptor.relative_path.split("/"))
            with io.open(path, "rb") as handle:
                digest = "sha256:" + hashlib.sha256(handle.read()).hexdigest()
            with self.subTest(artifact=descriptor.relative_path):
                self.assertEqual(digest, descriptor.sha256)

    def test_raw_bytes_are_preserved_exactly(self):
        """Nothing is parsed and reserialised on the way in."""
        result = self.sealed()
        expected = {builders.body(1), builders.body(2)}
        found = set()
        for descriptor in result.manifest.artifacts:
            path = os.path.join(result.snapshot_path,
                                *descriptor.relative_path.split("/"))
            with io.open(path, "rb") as handle:
                found.add(handle.read())
        self.assertEqual(found, expected)


class TestSnapshotContentHash(SnapshotTestCase):

    def test_a_cache_replay_matches_the_network_run(self):
        network = self.sealed(
            "PGX-DATA-20260830-001",
            **dict(zip(("cache", "manifest"),
                       self.complete_run("net", cache_state=CacheState.MISS))))
        replay_cache, replay_manifest = self.complete_run(
            "replay", cache_state=CacheState.HIT)
        replay = self.sealed("PGX-DATA-20260830-002", cache=replay_cache,
                             manifest=replay_manifest,
                             kind=SnapshotKind.CACHE_REPLAY)
        self.assertEqual(network.manifest.snapshot_content_hash,
                         replay.manifest.snapshot_content_hash)

    def test_the_dataset_id_does_not_change_content_identity(self):
        first = self.sealed("PGX-DATA-20260830-001")
        second = self.sealed("PGX-DATA-20260830-002")
        self.assertEqual(first.manifest.snapshot_content_hash,
                         second.manifest.snapshot_content_hash)

    def test_the_dataset_id_does_change_manifest_identity(self):
        first = self.sealed("PGX-DATA-20260830-001")
        second = self.sealed("PGX-DATA-20260830-002")
        self.assertNotEqual(first.manifest.manifest_hash,
                            second.manifest.manifest_hash)

    def test_the_staging_directory_does_not_change_content_identity(self):
        one = SnapshotManager(os.path.join(self.root, "a"),
                              clock=lambda: builders.NOW,
                              token_factory=lambda: "alpha")
        two = SnapshotManager(os.path.join(self.root, "b"),
                              clock=lambda: builders.NOW,
                              token_factory=lambda: "omega")
        first = self.sealed("PGX-DATA-20260830-001", manager=one)
        second = self.sealed("PGX-DATA-20260830-001", manager=two)
        self.assertEqual(first.manifest.snapshot_content_hash,
                         second.manifest.snapshot_content_hash)
        self.assertNotEqual(first.snapshot_path, second.snapshot_path)

    def test_the_creation_instant_does_not_change_content_identity(self):
        later = builders.NOW + _dt.timedelta(days=400)
        other = SnapshotManager(os.path.join(self.root, "later"),
                                clock=lambda: later)
        first = self.sealed("PGX-DATA-20260830-001")
        second = self.sealed("PGX-DATA-20260830-001", manager=other)
        self.assertEqual(first.manifest.snapshot_content_hash,
                         second.manifest.snapshot_content_hash)
        self.assertNotEqual(first.manifest.manifest_hash,
                            second.manifest.manifest_hash)

    def test_retry_counts_do_not_change_content_identity(self):
        """A run that needed four attempts captured the same bytes."""
        cache, quick = self.complete_run("quick")
        data = builders.body(1)
        key = builders.request_key("page-1")
        patient = builders.record(key, data, attempts=4)
        from pgx.ingestion.common.manifest import build_acquisition_manifest
        from pgx.ingestion.common.models import AcquisitionRunId
        retried = build_acquisition_manifest(
            run_id=AcquisitionRunId("fixture-run-retry"),
            source_id=builders.SOURCE_KEY, started_at=builders.NOW,
            completed_at=builders.LATER,
            endpoints=(builders.endpoint([patient]),))
        one_page_cache, one_page = self.complete_run("one", pages=1)
        plain = self.sealed("PGX-DATA-20260830-001", cache=one_page_cache,
                            manifest=one_page)
        retried_result = self.sealed("PGX-DATA-20260830-002",
                                     cache=one_page_cache, manifest=retried)
        self.assertEqual(plain.manifest.snapshot_content_hash,
                         retried_result.manifest.snapshot_content_hash)

    def test_artifact_order_does_not_change_content_identity(self):
        """Descriptors are sorted, so the order they were produced in is lost."""
        descriptors = [
            RawArtifactDescriptor("responses/b.json", ArtifactKind.RESPONSE_BODY,
                                  2, "sha256:" + "1" * 64),
            RawArtifactDescriptor("responses/a.json", ArtifactKind.RESPONSE_BODY,
                                  1, "sha256:" + "0" * 64),
        ]
        self.assertEqual(snapshot_content_hash("s", descriptors),
                         snapshot_content_hash("s", list(reversed(descriptors))))

    def test_the_request_log_is_outside_the_content_hash(self):
        """It carries retrieval timestamps, which are provenance not content."""
        descriptors = [
            RawArtifactDescriptor("responses/a.json", ArtifactKind.RESPONSE_BODY,
                                  1, "sha256:" + "0" * 64),
        ]
        with_log = descriptors + [
            RawArtifactDescriptor("requests.ndjson", ArtifactKind.REQUEST_LOG,
                                  9, "sha256:" + "2" * 64)]
        self.assertEqual(snapshot_content_hash("s", descriptors),
                         snapshot_content_hash("s", with_log))

    def test_a_different_source_key_gives_a_different_content_hash(self):
        descriptors = [
            RawArtifactDescriptor("responses/a.json", ArtifactKind.RESPONSE_BODY,
                                  1, "sha256:" + "0" * 64)]
        self.assertNotEqual(snapshot_content_hash("one", descriptors),
                            snapshot_content_hash("two", descriptors))

    def test_one_changed_byte_changes_the_content_hash(self):
        first = self.sealed("PGX-DATA-20260830-001")
        cache, manifest = self.complete_run("other", pages=3)
        second = self.sealed("PGX-DATA-20260830-002", cache=cache,
                             manifest=manifest)
        self.assertNotEqual(first.manifest.snapshot_content_hash,
                            second.manifest.snapshot_content_hash)


class TestManifestHash(SnapshotTestCase):

    def test_the_hash_excludes_only_itself(self):
        result = self.sealed()
        payload = result.manifest.payload()
        self.assertEqual(snapshot_manifest_hash(payload),
                         result.manifest.manifest_hash)

    def test_changing_any_other_field_changes_the_hash(self):
        result = self.sealed()
        payload = dict(result.manifest.payload())
        payload["complete"] = not payload["complete"]
        self.assertNotEqual(snapshot_manifest_hash(payload),
                            result.manifest.manifest_hash)

    def test_the_stored_hash_field_is_ignored_when_recomputing(self):
        result = self.sealed()
        payload = dict(result.manifest.payload())
        payload["manifest_hash"] = "sha256:" + "9" * 64
        self.assertEqual(snapshot_manifest_hash(payload),
                         result.manifest.manifest_hash)


class TestDeterministicFiles(SnapshotTestCase):

    def test_two_builds_write_identical_request_logs(self):
        first = self.sealed("PGX-DATA-20260830-001")
        second = self.sealed("PGX-DATA-20260830-002")
        self.assertEqual(self._read(first, "requests.ndjson"),
                         self._read(second, "requests.ndjson"))

    def test_the_request_log_ends_with_exactly_one_newline(self):
        result = self.sealed()
        text = self._read(result, "requests.ndjson")
        self.assertTrue(text.endswith("\n"))
        self.assertFalse(text.endswith("\n\n"))

    def test_every_request_log_line_is_canonical_json(self):
        import json
        result = self.sealed()
        for line in self._read(result, "requests.ndjson").splitlines():
            parsed = json.loads(line)
            with self.subTest(line=line[:40]):
                self.assertEqual(
                    json.dumps(parsed, sort_keys=True, ensure_ascii=False,
                               separators=(",", ":")), line)

    def test_the_request_log_names_its_response_artifact(self):
        import json
        result = self.sealed()
        paths = {descriptor.relative_path
                 for descriptor in result.manifest.artifacts}
        for line in self._read(result, "requests.ndjson").splitlines():
            entry = json.loads(line)
            with self.subTest(request=entry["request_key"][:20]):
                self.assertIn(entry["artifact_path"], paths)

    def test_repeated_query_parameters_survive(self):
        """``?cursor=abc&cursor=def`` is two values, not one."""
        import json
        result = self.sealed()
        entry = json.loads(self._read(result, "requests.ndjson").splitlines()[0])
        self.assertEqual(entry["query"], [["cursor", "abc"], ["cursor", "def"]])

    def test_the_request_log_carries_no_query_string_in_the_url(self):
        import json
        result = self.sealed()
        for line in self._read(result, "requests.ndjson").splitlines():
            self.assertNotIn("?", json.loads(line)["url"])

    def test_two_builds_write_identical_checksum_files(self):
        first = self.sealed("PGX-DATA-20260830-001")
        second = self.sealed("PGX-DATA-20260830-002")
        self.assertEqual(self._read(first, "checksums.sha256"),
                         self._read(second, "checksums.sha256"))

    def test_the_checksum_file_is_sorted_and_sha256sum_shaped(self):
        result = self.sealed()
        lines = self._read(result, "checksums.sha256").splitlines()
        paths = [line.split("  ", 1)[1] for line in lines]
        self.assertEqual(paths, sorted(paths))
        for line in lines:
            digest = line.split("  ", 1)[0]
            with self.subTest(line=line[:30]):
                self.assertEqual(len(digest), 64)
                self.assertTrue(all(c in "0123456789abcdef" for c in digest))

    def test_the_checksum_file_lists_neither_itself_nor_the_manifest(self):
        """A file listing its own digest could never be written."""
        result = self.sealed()
        listed = {line.split("  ", 1)[1]
                  for line in self._read(result, "checksums.sha256").splitlines()}
        self.assertNotIn("checksums.sha256", listed)
        self.assertNotIn("manifest.json", listed)

    def test_the_checksum_file_lists_the_request_log_and_every_response(self):
        result = self.sealed()
        listed = {line.split("  ", 1)[1]
                  for line in self._read(result, "checksums.sha256").splitlines()}
        expected = {item.relative_path for item in result.manifest.artifacts}
        expected.add("requests.ndjson")
        self.assertEqual(listed, expected)

    @staticmethod
    def _read(result, relative: str) -> str:
        with io.open(os.path.join(result.snapshot_path, relative),
                     encoding="utf-8") as handle:
            return handle.read()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
