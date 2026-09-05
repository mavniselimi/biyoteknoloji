# -*- coding: utf-8 -*-
"""Request keys and the content-addressed cache (WP-04).

Two guarantees carry the weight here.

**A key identifies a question, not an occasion.** The same semantic request
always produces the same key - whatever order the query was built in, whatever
time it is, wherever the cache lives. Otherwise the cache never hits.

**A key can never contain a credential.** The key is the cache filename and
appears in every manifest, so a key derived from an Authorization header would
write a token to disk and into every report. The tests assert the absence
directly, by putting a distinctive secret in and searching the output for it.

The cache tests are mostly about failure. A cache that silently degrades a
corrupt blob to a miss stays corrupt and unnoticed; a cache that overwrites a
blob on a digest collision destroys evidence. Both are asserted to raise.

Socket-free; the filesystem work happens in temporary directories.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest

from pgx.ingestion.common.cache import (
    CACHE_METADATA_VERSION, ResponseCache, sha256_bytes,
)
from pgx.ingestion.common.errors import (
    CacheCorruptionError, CacheMissError, CacheWriteConflictError,
    ConfigurationError,
)
from pgx.ingestion.common.http import (
    CREDENTIAL_HEADER_NAMES, REQUEST_KEY_VERSION, request_key,
)
from pgx.ingestion.common.models import HttpRequest, HttpResponse

from tests.unit.ingestion._fakes import EPOCH, json_response, raw_response

SECRET = "tok3n-do-not-store-me"


def _request(**overrides) -> HttpRequest:
    values = dict(
        method="GET", base_url="https://api.clinpgx.org/v1", path="/data/gene",
        endpoint_id="gene_lookup", query=(("symbol", "CYP2C19"), ("view", "base")),
        headers={"Accept": "application/json"}, timeout_seconds=30.0)
    values.update(overrides)
    return HttpRequest(**values)


class TestRequestKeyIdentifiesTheQuestion(unittest.TestCase):

    def test_the_same_request_gives_the_same_key(self):
        self.assertEqual(request_key(_request()), request_key(_request()))

    def test_query_order_does_not_change_the_key(self):
        first = _request(query=(("symbol", "CYP2C19"), ("view", "base")))
        second = _request(query=(("view", "base"), ("symbol", "CYP2C19")))
        self.assertEqual(request_key(first), request_key(second))

    def test_a_different_query_value_changes_the_key(self):
        self.assertNotEqual(
            request_key(_request(query=(("symbol", "CYP2C19"),))),
            request_key(_request(query=(("symbol", "CYP2D6"),))))

    def test_a_different_page_changes_the_key(self):
        self.assertNotEqual(
            request_key(_request(query=(("page", "1"), ("size", "100")))),
            request_key(_request(query=(("page", "2"), ("size", "100")))))

    def test_a_different_cursor_changes_the_key(self):
        self.assertNotEqual(
            request_key(_request(query=(("cursor", "abc"),))),
            request_key(_request(query=(("cursor", "def"),))))

    def test_a_different_path_changes_the_key(self):
        self.assertNotEqual(request_key(_request()),
                            request_key(_request(path="/data/chemical")))

    def test_a_different_endpoint_id_changes_the_key(self):
        """Two endpoints may share a path and mean different things."""
        self.assertNotEqual(
            request_key(_request(endpoint_id="guideline_annotation_by_gene")),
            request_key(_request(endpoint_id="guideline_annotation_by_pair")))

    def test_a_different_shape_version_changes_the_key(self):
        self.assertNotEqual(request_key(_request()),
                            request_key(_request(response_shape_version="v2")))

    def test_the_host_is_case_insensitive(self):
        self.assertEqual(
            request_key(_request(base_url="https://API.ClinPGx.org/v1")),
            request_key(_request(base_url="https://api.clinpgx.org/v1")))

    def test_the_key_is_a_canonical_digest(self):
        key = request_key(_request())
        self.assertTrue(key.startswith("sha256:"))
        self.assertEqual(len(key), len("sha256:") + 64)

    def test_the_key_version_is_part_of_the_payload(self):
        self.assertTrue(REQUEST_KEY_VERSION.startswith("pgx-request-key/"))


class TestRequestKeyExcludesEverythingItShould(unittest.TestCase):

    def test_a_credential_header_does_not_reach_the_key(self):
        for header in ("Authorization", "Cookie", "X-API-Key", "X-Auth-Token"):
            with self.subTest(header=header):
                with_secret = _request(headers={"Accept": "application/json",
                                                header: SECRET})
                self.assertEqual(request_key(with_secret), request_key(_request()))
                self.assertNotIn(SECRET, request_key(with_secret))

    def test_the_user_agent_does_not_reach_the_key(self):
        """It identifies the client, not the question being asked."""
        self.assertEqual(
            request_key(_request(headers={"Accept": "application/json",
                                          "User-Agent": "probe/9.9"})),
            request_key(_request()))

    def test_a_semantic_header_does_reach_the_key(self):
        self.assertNotEqual(
            request_key(_request(headers={"Accept": "application/json"})),
            request_key(_request(headers={"Accept": "text/csv"})))

    def test_the_timeout_does_not_reach_the_key(self):
        """How long we were willing to wait is not part of the question."""
        self.assertEqual(request_key(_request(timeout_seconds=5.0)),
                         request_key(_request(timeout_seconds=120.0)))

    def test_the_wall_clock_does_not_reach_the_key(self):
        import time

        first = request_key(_request())
        time.sleep(0.01)
        self.assertEqual(first, request_key(_request()))

    def test_the_key_never_contains_a_directory_separator(self):
        """It is used as a filename component."""
        key = request_key(_request())
        self.assertNotIn("/", key[len("sha256:"):])
        self.assertNotIn("\\", key)
        self.assertNotIn("..", key)


class CacheTestCase(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="pgx-cache-test-")
        self.cache = ResponseCache(self.directory)
        self.key = request_key(_request())

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)


class TestCacheStoreAndLoad(CacheTestCase):

    def test_a_first_request_is_a_miss(self):
        self.assertFalse(self.cache.has(self.key))
        with self.assertRaises(CacheMissError):
            self.cache.load_entry(self.key)

    def test_storing_then_loading_returns_the_same_bytes(self):
        response = raw_response(b'{"data": [{"id": 1}]}')
        self.cache.store(self.key, response, now=EPOCH)
        self.assertTrue(self.cache.has(self.key))
        self.assertEqual(self.cache.load(self.key).body, response.body)

    def test_bytes_are_preserved_exactly_not_reserialised(self):
        """Whitespace, key order and encoding all survive."""
        body = b'{  "data" : [ {"b": 2, "a": 1} ]  ,  "x": "\xc3\xa7" }'
        self.cache.store(self.key, raw_response(body), now=EPOCH)
        self.assertEqual(self.cache.load(self.key).body, body)

    def test_the_stored_digest_is_the_digest_of_those_bytes(self):
        body = b'{"data": []}'
        entry = self.cache.store(self.key, raw_response(body), now=EPOCH)
        self.assertEqual(entry.raw_sha256, sha256_bytes(body))

    def test_status_and_content_type_survive(self):
        self.cache.store(self.key, raw_response(b"{}", status_code=200),
                         now=EPOCH)
        loaded = self.cache.load(self.key)
        self.assertEqual(loaded.status_code, 200)
        self.assertEqual(loaded.content_type, "application/json")

    def test_two_keys_with_identical_bytes_share_one_blob(self):
        body = b'{"data": []}'
        other = request_key(_request(query=(("symbol", "CYP2D6"),)))
        first = self.cache.store(self.key, raw_response(body), now=EPOCH)
        second = self.cache.store(other, raw_response(body), now=EPOCH)
        self.assertEqual(first.blob_ref, second.blob_ref)
        blobs = [name for _root, _dirs, files in os.walk(
            os.path.join(self.directory, "blobs")) for name in files]
        self.assertEqual(len(blobs), 1)

    def test_re_storing_identical_bytes_is_idempotent(self):
        body = b'{"data": []}'
        self.cache.store(self.key, raw_response(body), now=EPOCH)
        self.cache.store(self.key, raw_response(body), now=EPOCH)
        self.assertEqual(self.cache.load(self.key).body, body)


class TestCacheNeverStoresACredential(CacheTestCase):

    def test_credential_headers_are_stripped_before_storage(self):
        response = raw_response(b"{}", headers={
            "Authorization": "Bearer %s" % SECRET,
            "Set-Cookie": "session=%s" % SECRET,
            "X-API-Key": SECRET})
        self.cache.store(self.key, response, now=EPOCH)
        for root, _dirs, files in os.walk(self.directory):
            for name in files:
                with io.open(os.path.join(root, name), "rb") as handle:
                    self.assertNotIn(SECRET.encode(), handle.read(),
                                     "%s contains a credential" % name)

    def test_safe_headers_do_survive(self):
        self.cache.store(self.key, raw_response(
            b"{}", headers={"X-RateLimit-Limit": "100"}), now=EPOCH)
        entry = self.cache.load_entry(self.key)
        self.assertIn("x-ratelimit-limit", entry.safe_headers)


class TestCacheFailsLoudly(CacheTestCase):

    def _blob_path(self):
        return self.cache.blob_path(self.cache.load_entry(self.key).raw_sha256)

    def test_a_corrupt_blob_raises_rather_than_missing(self):
        """A cache that degrades corruption to a miss stays corrupt."""
        self.cache.store(self.key, raw_response(b'{"data": []}'), now=EPOCH)
        with io.open(self._blob_path(), "wb") as handle:
            handle.write(b'{"data": [999]}')
        with self.assertRaises(CacheCorruptionError) as caught:
            self.cache.load(self.key)
        self.assertIn("does not match its digest", str(caught.exception))

    def test_a_missing_blob_raises_rather_than_missing(self):
        self.cache.store(self.key, raw_response(b"{}"), now=EPOCH)
        os.unlink(self._blob_path())
        with self.assertRaises(CacheCorruptionError):
            self.cache.load(self.key)

    def test_unreadable_metadata_raises(self):
        self.cache.store(self.key, raw_response(b"{}"), now=EPOCH)
        with io.open(self.cache.index_path(self.key), "w") as handle:
            handle.write("not json at all")
        with self.assertRaises(CacheCorruptionError):
            self.cache.load_entry(self.key)

    def test_metadata_from_another_version_is_refused(self):
        self.cache.store(self.key, raw_response(b"{}"), now=EPOCH)
        path = self.cache.index_path(self.key)
        with io.open(path, encoding="utf-8") as handle:
            document = json.load(handle)
        document["metadata_version"] = "pgx-response-cache/0"
        with io.open(path, "w", encoding="utf-8") as handle:
            json.dump(document, handle)
        with self.assertRaises(CacheCorruptionError):
            self.cache.load_entry(self.key)

    def test_a_blob_is_never_overwritten_with_different_bytes(self):
        body = b'{"data": []}'
        self.cache.store(self.key, raw_response(body), now=EPOCH)
        path = self._blob_path()
        digest = self.cache.load_entry(self.key).raw_sha256
        with io.open(path, "wb") as handle:
            handle.write(b"tampered")
        conflicting = raw_response(body)
        with self.assertRaises(CacheWriteConflictError):
            self.cache.store(self.key, conflicting, now=EPOCH)
        with io.open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"tampered",
                             "the existing blob must not be overwritten")

    def test_a_malformed_digest_is_refused(self):
        for bad in ("not-a-digest", "sha256:xyz", "sha1:" + "a" * 40,
                    "sha256:" + "A" * 64):
            with self.subTest(digest=bad):
                with self.assertRaises(CacheCorruptionError):
                    self.cache.blob_path(bad)

    def test_a_path_traversal_key_is_refused(self):
        for bad in ("sha256:../../etc/passwd", "sha256:" + "../" * 10):
            with self.subTest(key=bad):
                with self.assertRaises(CacheCorruptionError):
                    self.cache.index_path(bad)

    def test_a_symlinked_blob_directory_cannot_escape_the_root(self):
        outside = tempfile.mkdtemp(prefix="pgx-outside-")
        try:
            self.cache.store(self.key, raw_response(b"{}"), now=EPOCH)
            digest = self.cache.load_entry(self.key).raw_sha256
            fanout = os.path.dirname(self.cache.blob_path(digest))
            shutil.rmtree(fanout)
            os.symlink(outside, fanout)
            with self.assertRaises(CacheCorruptionError) as caught:
                self.cache.blob_path(digest)
            self.assertIn("escapes the root", str(caught.exception))
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_an_empty_cache_root_is_refused(self):
        for bad in ("", "   ", None):
            with self.subTest(root=bad):
                with self.assertRaises(ConfigurationError):
                    ResponseCache(bad)


class TestAtomicWrites(CacheTestCase):

    def test_no_partial_file_remains_after_a_successful_store(self):
        self.cache.store(self.key, raw_response(b'{"data": []}'), now=EPOCH)
        leftovers = [name for root, _dirs, files in os.walk(self.directory)
                     for name in files if name.startswith(".tmp-")]
        self.assertEqual(leftovers, [])

    def test_a_failed_write_leaves_no_partial_file(self):
        original = os.replace

        def _explode(src, dst):
            raise OSError("simulated failure during rename")

        os.replace = _explode
        try:
            with self.assertRaises(OSError):
                self.cache.store(self.key, raw_response(b"{}"), now=EPOCH)
        finally:
            os.replace = original
        leftovers = [name for root, _dirs, files in os.walk(self.directory)
                     for name in files if name.startswith(".tmp-")]
        self.assertEqual(leftovers, [])


class TestCacheVerification(CacheTestCase):

    def test_a_healthy_cache_verifies(self):
        self.cache.store(self.key, raw_response(b'{"data": []}'), now=EPOCH)
        report = self.cache.verify()
        self.assertTrue(report["healthy"])
        self.assertEqual(report["entries"], 1)
        self.assertEqual(report["verified_blobs"], 1)

    def test_verification_reports_corruption_rather_than_raising(self):
        self.cache.store(self.key, raw_response(b'{"data": []}'), now=EPOCH)
        path = self.cache.blob_path(self.cache.load_entry(self.key).raw_sha256)
        with io.open(path, "wb") as handle:
            handle.write(b"tampered")
        report = self.cache.verify()
        self.assertFalse(report["healthy"])
        self.assertEqual(len(report["problems"]), 1)
        self.assertEqual(report["problems"][0]["error"], "CacheCorruptionError")

    def test_an_empty_cache_verifies_as_healthy(self):
        report = self.cache.verify()
        self.assertTrue(report["healthy"])
        self.assertEqual(report["entries"], 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
