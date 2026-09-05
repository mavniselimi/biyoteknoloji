# -*- coding: utf-8 -*-
"""Reading a WP-04 run manifest back, and refusing to believe it.

A manifest on disk is a JSON file somebody could have edited. So the reader
rebuilds the typed records and recomputes the status, the publishability and
the content hash from those records; the document's own claims are then
compared against the recomputed ones and a disagreement is an error.

The test that matters most is the forged one: a manifest that says ``COMPLETE``
over a required endpoint that failed must not become a snapshot.
"""

from __future__ import annotations

import io
import json
import os
import unittest

from pgx.ingestion.common.manifest_io import (
    ManifestDeserializationError,
    load_acquisition_manifest,
    read_acquisition_manifest,
)
from pgx.ingestion.common.models import AcquisitionStatus

from tests.unit.snapshots._support import SnapshotTestCase

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
EXAMPLES = os.path.join(REPO_ROOT, "docs", "examples", "wp04")


class TestRoundTrip(SnapshotTestCase):

    def test_a_manifest_survives_a_round_trip(self):
        _cache, manifest = self.complete_run("io")
        rebuilt = read_acquisition_manifest(manifest.to_json())
        self.assertEqual(rebuilt.content_hash, manifest.content_hash)
        self.assertIs(rebuilt.status, manifest.status)
        self.assertEqual(len(rebuilt.endpoints), len(manifest.endpoints))

    def test_repeated_query_parameters_survive(self):
        _cache, manifest = self.complete_run("io")
        rebuilt = read_acquisition_manifest(manifest.to_json())
        self.assertEqual(rebuilt.endpoints[0].records[0].safe_query,
                         (("cursor", "abc"), ("cursor", "def")))

    def test_the_checked_in_examples_all_read_back(self):
        for name in sorted(os.listdir(EXAMPLES)):
            if not name.endswith(".json"):
                continue
            with self.subTest(example=name):
                manifest = load_acquisition_manifest(
                    os.path.join(EXAMPLES, name))
                self.assertIsNotNone(manifest.content_hash)

    def test_the_network_and_replay_examples_share_a_content_hash(self):
        network = load_acquisition_manifest(
            os.path.join(EXAMPLES, "acquisition-manifest-complete.json"))
        replay = load_acquisition_manifest(
            os.path.join(EXAMPLES, "acquisition-manifest-replay.json"))
        self.assertEqual(network.content_hash, replay.content_hash)


class TestStoredClaimsAreNotTrusted(SnapshotTestCase):

    def _document(self):
        _cache, manifest = self.complete_run("claims")
        return json.loads(json.dumps(manifest.to_json()))

    def test_a_forged_status_is_refused(self):
        document = self._document()
        document["endpoints"][0]["outcome"] = "FAILED"
        with self.assertRaises(ManifestDeserializationError) as caught:
            read_acquisition_manifest(document)
        self.assertIn("recompute", str(caught.exception))

    def test_a_forged_publishable_flag_is_refused(self):
        document = self._document()
        document["is_publishable"] = False
        with self.assertRaises(ManifestDeserializationError):
            read_acquisition_manifest(document)

    def test_a_forged_content_hash_is_refused(self):
        document = self._document()
        document["content_hash"] = "sha256:" + "0" * 64
        with self.assertRaises(ManifestDeserializationError):
            read_acquisition_manifest(document)

    def test_an_edited_retrieval_digest_changes_the_recomputed_hash(self):
        document = self._document()
        document["endpoints"][0]["records"][0]["raw_sha256"] = "sha256:" + "1" * 64
        with self.assertRaises(ManifestDeserializationError):
            read_acquisition_manifest(document)

    def test_a_forged_complete_status_over_a_failed_endpoint_is_refused(self):
        """The exact forgery the reader exists to catch."""
        document = self._document()
        document["endpoints"][0]["pagination"]["terminal"] = False
        document["status"] = AcquisitionStatus.COMPLETE.value
        with self.assertRaises(ManifestDeserializationError):
            read_acquisition_manifest(document)


class TestMalformedDocuments(unittest.TestCase):

    def test_an_unknown_top_level_key_is_refused(self):
        with self.assertRaises(ManifestDeserializationError):
            read_acquisition_manifest({"run_manifest_version": "x",
                                       "surprise": 1})

    def test_an_unknown_manifest_version_is_refused(self):
        with self.assertRaises(ManifestDeserializationError) as caught:
            read_acquisition_manifest({"run_manifest_version": "other/9"})
        self.assertIn("understands", str(caught.exception))

    def test_a_non_object_is_refused(self):
        with self.assertRaises(ManifestDeserializationError):
            read_acquisition_manifest([])

    def test_a_naive_timestamp_is_refused(self):
        with self.assertRaises(ManifestDeserializationError):
            read_acquisition_manifest({
                "run_manifest_version": "pgx-acquisition-run/1",
                "run_id": "r", "source_id": "s",
                "started_at": "2026-08-30T12:00:00",
                "completed_at": "2026-08-30T12:00:00Z",
                "content_manifest": {
                    "content_manifest_version": "pgx-acquisition-content/1"},
                "endpoints": []})

    def test_a_query_recorded_as_an_object_is_refused(self):
        """An object would collapse ``?id=1&id=2`` into one value."""
        from pgx.ingestion.common.manifest_io import _safe_query
        with self.assertRaises(ManifestDeserializationError):
            _safe_query({"cursor": "abc"}, "$.safe_query")

    def test_a_missing_file_is_refused(self):
        with self.assertRaises(ManifestDeserializationError):
            load_acquisition_manifest("/no/such/manifest.json")

    def test_a_file_that_is_not_json_is_refused(self):
        import tempfile
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        try:
            handle.write("{not json")
            handle.close()
            with self.assertRaises(ManifestDeserializationError):
                load_acquisition_manifest(handle.name)
        finally:
            os.unlink(handle.name)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
