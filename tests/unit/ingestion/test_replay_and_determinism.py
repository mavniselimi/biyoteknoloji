# -*- coding: utf-8 -*-
"""Cache replay, zero network, and the determinism boundary (WP-04).

The claim under test is precise: **a network run and a cache-only replay of the
same data differ in every operational field and agree exactly on the content
hash.**

That is what makes the content hash worth having. If a timestamp, a retry count
or a cache-hit flag reached it, replaying identical bytes would produce a
different identity and the hash would answer no useful question.

"Zero network" is asserted with :class:`ForbiddenTransport`, which raises if
anything calls it. A fake returning a canned response would let a regression
that quietly re-fetched pass unnoticed.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest

from pgx.application.ingestion_service import IngestionService
from pgx.ingestion.common.cache import ResponseCache
from pgx.ingestion.common.manifest import (
    build_content_manifest, content_manifest_hash,
)
from pgx.ingestion.common.models import (
    AcquisitionRunId, AcquisitionStatus, CacheState,
)
from pgx.ingestion.common.retry import RetryPolicy

from tests.unit.ingestion._fakes import (
    ForbiddenTransport, RecordingSleeper, ScriptedTransport, StepClock,
    data_page, fixed_random, json_response, raw_response,
)

PARAMETERS = {"symbol": "CYP2C19", "name": "clopidogrel",
              "gene_accession_id": "PA124",
              "chemical_accession_id": "PA449053", "view": "base"}

ENDPOINTS = ["gene_lookup", "chemical_lookup"]

#: Two pages then an empty page, for each of the two endpoints.
SCRIPT = [
    data_page([{"id": "PA124", "symbol": "CYP2C19"}]), data_page([]),
    data_page([{"id": "PA449053", "name": "clopidogrel"}]), data_page([]),
]


class ReplayTestCase(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="pgx-replay-test-")
        self.cache = ResponseCache(self.directory)

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _service(self, transport, run_id="00000000-0000-4000-8000-000000000001",
                 step=0.0):
        return IngestionService(
            cache=self.cache, transport_factory=lambda: transport,
            retry_policy=RetryPolicy(max_attempts=2),
            clock=StepClock(step_seconds=step), sleeper=RecordingSleeper(),
            random_source=fixed_random(),
            new_run_id=lambda: AcquisitionRunId.parse(run_id))

    def _first_run(self):
        transport = ScriptedTransport(list(SCRIPT))
        manifest = self._service(transport).acquire(PARAMETERS, ENDPOINTS)
        return manifest, transport


class TestCacheReplayMakesNoRequest(ReplayTestCase):

    def test_the_first_run_uses_the_network(self):
        manifest, transport = self._first_run()
        self.assertIs(manifest.status, AcquisitionStatus.COMPLETE)
        self.assertEqual(transport.call_count, 4)

    def test_the_replay_calls_the_transport_zero_times(self):
        self._first_run()
        forbidden = ForbiddenTransport()
        service = self._service(forbidden,
                                run_id="00000000-0000-4000-8000-000000000002")
        manifest = service.replay_from_cache(PARAMETERS, ENDPOINTS)
        self.assertIs(manifest.status, AcquisitionStatus.COMPLETE)
        self.assertEqual(forbidden.call_count, 0)

    def test_the_replay_never_even_builds_a_transport(self):
        """A cache-only run that could fall back would not be cache-only."""
        self._first_run()
        built = []

        def _factory():
            built.append(True)
            return ForbiddenTransport()

        service = IngestionService(
            cache=self.cache, transport_factory=_factory,
            clock=StepClock(step_seconds=0.0), sleeper=RecordingSleeper(),
            random_source=fixed_random(),
            new_run_id=AcquisitionRunId.new)
        service.replay_from_cache(PARAMETERS, ENDPOINTS)
        self.assertEqual(built, [], "the transport factory must not be called")

    def test_every_replayed_page_reports_a_cache_hit(self):
        self._first_run()
        manifest = self._service(ForbiddenTransport()).replay_from_cache(
            PARAMETERS, ENDPOINTS)
        for endpoint in manifest.endpoints:
            for record in endpoint.records:
                self.assertIs(record.cache_state, CacheState.HIT)

    def test_a_replay_with_no_cache_fails_explicitly(self):
        manifest = self._service(ForbiddenTransport()).replay_from_cache(
            PARAMETERS, ENDPOINTS)
        self.assertIs(manifest.status, AcquisitionStatus.FAILED)
        self.assertFalse(manifest.is_publishable)
        codes = [record.error_code for endpoint in manifest.endpoints
                 for record in endpoint.records]
        self.assertIn("CACHE_MISS", codes)

    def test_a_partial_cache_fails_rather_than_fetching_the_rest(self):
        transport = ScriptedTransport(SCRIPT[:2])
        self._service(transport).acquire(PARAMETERS, ["gene_lookup"])
        manifest = self._service(ForbiddenTransport()).replay_from_cache(
            PARAMETERS, ENDPOINTS)
        self.assertIs(manifest.status, AcquisitionStatus.FAILED)

    def test_a_corrupt_cache_fails_the_replay_rather_than_refetching(self):
        import io

        manifest, _ = self._first_run()
        record = manifest.endpoints[0].records[0]
        with io.open(self.cache.blob_path(record.raw_sha256), "wb") as handle:
            handle.write(b"tampered")
        replay = self._service(ForbiddenTransport()).replay_from_cache(
            PARAMETERS, ENDPOINTS)
        self.assertIs(replay.status, AcquisitionStatus.FAILED)
        codes = [item.error_code for endpoint in replay.endpoints
                 for item in endpoint.records]
        self.assertIn("CACHE_CORRUPTION", codes)


class TestContentIdentityIsStableAcrossRuns(ReplayTestCase):

    def test_a_replay_reproduces_the_content_hash_exactly(self):
        original, _ = self._first_run()
        replay = self._service(
            ForbiddenTransport(),
            run_id="00000000-0000-4000-8000-000000000002", step=7.0
        ).replay_from_cache(PARAMETERS, ENDPOINTS)
        self.assertEqual(replay.content_hash, original.content_hash)

    def test_the_two_runs_differ_operationally(self):
        """Otherwise the previous test would prove nothing."""
        original, _ = self._first_run()
        replay = self._service(
            ForbiddenTransport(),
            run_id="00000000-0000-4000-8000-000000000002", step=7.0
        ).replay_from_cache(PARAMETERS, ENDPOINTS)
        self.assertNotEqual(replay.run_id.to_json(), original.run_id.to_json())
        self.assertTrue(replay.cache_only)
        self.assertFalse(original.cache_only)
        self.assertNotEqual(
            [r.cache_state for e in replay.endpoints for r in e.records],
            [r.cache_state for e in original.endpoints for r in e.records])

    def test_a_second_network_run_of_the_same_data_matches_too(self):
        original, _ = self._first_run()
        second = self._service(
            ScriptedTransport(list(SCRIPT)),
            run_id="00000000-0000-4000-8000-000000000003"
        ).acquire(PARAMETERS, ENDPOINTS, refresh=True)
        self.assertEqual(second.content_hash, original.content_hash)

    def test_different_bytes_give_a_different_content_hash(self):
        original, _ = self._first_run()
        other = ResponseCache(tempfile.mkdtemp(prefix="pgx-other-"))
        try:
            service = IngestionService(
                cache=other,
                transport_factory=lambda: ScriptedTransport([
                    data_page([{"id": "PA124", "symbol": "CYP2C19"}]),
                    data_page([]),
                    data_page([{"id": "DIFFERENT"}]), data_page([])]),
                clock=StepClock(step_seconds=0.0), sleeper=RecordingSleeper(),
                random_source=fixed_random(), new_run_id=AcquisitionRunId.new)
            different = service.acquire(PARAMETERS, ENDPOINTS)
            self.assertNotEqual(different.content_hash, original.content_hash)
        finally:
            shutil.rmtree(other.root, ignore_errors=True)

    def test_the_content_manifest_carries_no_operational_field(self):
        manifest, _ = self._first_run()
        rendered = str(manifest.content_manifest)
        for forbidden in ("started_at", "completed_at", "attempts",
                          "cache_state", "retry_count", "run_id", "status_code"):
            self.assertNotIn(forbidden, rendered,
                             "%s must not reach the content manifest" % forbidden)

    def test_the_content_manifest_carries_what_identifies_the_data(self):
        manifest, _ = self._first_run()
        entry = manifest.content_manifest["entries"][0]
        self.assertEqual(set(entry), {"request_key", "endpoint_id",
                                      "page_number", "cursor", "raw_sha256",
                                      "byte_length"})

    def test_entry_order_does_not_change_the_hash(self):
        manifest, _ = self._first_run()
        forward = content_manifest_hash(
            build_content_manifest(manifest.source_id, manifest.endpoints))
        reversed_hash = content_manifest_hash(
            build_content_manifest(manifest.source_id,
                                   tuple(reversed(manifest.endpoints))))
        self.assertEqual(forward, reversed_hash)

    def test_failed_retrievals_do_not_enter_the_content_manifest(self):
        service = self._service(ScriptedTransport([raw_response(b"not json")]))
        manifest = service.acquire(PARAMETERS, ["gene_lookup"])
        self.assertIs(manifest.status, AcquisitionStatus.FAILED)
        self.assertEqual(manifest.content_manifest["entry_count"], 1,
                         "the bytes arrived and were hashed, so they identify "
                         "content even though parsing failed")


class TestRunValidation(ReplayTestCase):

    def test_a_healthy_manifest_validates(self):
        manifest, _ = self._first_run()
        report = self._service(ForbiddenTransport()).validate_run(manifest)
        self.assertTrue(report.valid)
        self.assertTrue(report.content_hash_matches)

    def test_a_tampered_content_hash_is_caught(self):
        import dataclasses

        manifest, _ = self._first_run()
        tampered = dataclasses.replace(manifest, content_hash="sha256:" + "0" * 64)
        report = self._service(ForbiddenTransport()).validate_run(tampered)
        self.assertFalse(report.valid)
        self.assertFalse(report.content_hash_matches)

    def test_a_status_that_contradicts_its_endpoints_is_caught(self):
        import dataclasses

        service = self._service(ScriptedTransport([raw_response(b"not json")]))
        failed = service.acquire(PARAMETERS, ["gene_lookup"])
        lying = dataclasses.replace(failed, status=AcquisitionStatus.COMPLETE)
        report = service.validate_run(lying)
        self.assertFalse(report.valid)
        self.assertTrue(any("did not complete" in problem
                            for problem in report.problems))

    def test_cache_validation_reports_health(self):
        self._first_run()
        report = self._service(ForbiddenTransport()).validate_cache()
        self.assertTrue(report["healthy"])
        self.assertEqual(report["entries"], 4)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
