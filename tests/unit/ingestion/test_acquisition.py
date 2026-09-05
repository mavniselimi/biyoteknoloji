# -*- coding: utf-8 -*-
"""Pagination, response validation and run completeness (WP-04).

Socket-free: every request goes to a scripted transport.

The through-line of this module is a single claim - **a run that did not finish
must not look finished**. Neither legacy probe paged at all, so one request per
endpoint became "the data" and every run reported success. The tests below take
each way pagination can fail to finish and assert two things: the endpoint is
``FAILED``, and the manifest is not publishable.

The pages already collected are *kept*, deliberately. A failed run is worth
diagnosing and replaying; deleting its evidence would only make the next
investigation start from nothing.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest

from pgx.application.ingestion_service import IngestionService
from pgx.ingestion.clinpgx.catalog import (
    EndpointDeclaration, ResponseShape, get_endpoint,
)
from pgx.ingestion.common.cache import ResponseCache
from pgx.ingestion.common.errors import ConfigurationError, PaginationError
from pgx.ingestion.common.models import (
    AcquisitionRunId, AcquisitionStatus, CacheState, EndpointOutcome, ParseStatus,
)
from pgx.ingestion.common.pagination import (
    PaginationSpec, PaginationStrategy, TerminationReason, read_next_cursor,
)
from pgx.ingestion.common.retry import RetryPolicy

from tests.unit.ingestion._fakes import (
    EPOCH, ForbiddenTransport, RecordingSleeper, ScriptedTransport, StepClock,
    data_page, fixed_random, json_response, raw_response,
)

PARAMETERS = {
    "symbol": "CYP2C19", "name": "clopidogrel",
    "gene_accession_id": "PA124", "chemical_accession_id": "PA449053",
    "view": "base",
}

CURSOR_SPEC = PaginationSpec(
    strategy=PaginationStrategy.CURSOR, cursor_param="cursor",
    limit_param="limit", page_size=2, next_cursor_path=("meta", "next"),
    max_pages=10)


def _endpoint(**overrides) -> EndpointDeclaration:
    values = dict(
        endpoint_id="test_endpoint", path_template="/data/gene", required=True,
        shape=ResponseShape.DATA_LIST, records_path=("data",),
        purpose="fixture", limitations="fixture",
        pagination=PaginationSpec(strategy=PaginationStrategy.PAGE_SIZE,
                                  page_size=2, max_pages=5),
        build_query=lambda parameters: (("symbol", str(parameters["symbol"])),))
    values.update(overrides)
    return EndpointDeclaration(**values)


class AcquisitionTestCase(unittest.TestCase):
    """One temporary cache and a deterministic service per test."""

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="pgx-acq-test-")
        self.cache = ResponseCache(self.directory)
        self.sleeper = RecordingSleeper()

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _service(self, transport, **overrides):
        values = dict(
            cache=self.cache, transport_factory=lambda: transport,
            retry_policy=RetryPolicy(max_attempts=2),
            clock=StepClock(step_seconds=0.0), sleeper=self.sleeper,
            random_source=fixed_random(),
            new_run_id=lambda: AcquisitionRunId.parse(
                "00000000-0000-4000-8000-000000000001"))
        values.update(overrides)
        return IngestionService(**values)

    def _acquire(self, script, endpoint=None, **overrides):
        """Run one endpoint against a scripted transport."""
        from pgx.ingestion.clinpgx.adapter import AcquisitionContext, acquire_endpoint

        transport = ScriptedTransport(script)
        context = AcquisitionContext(
            cache=self.cache, transport=transport,
            retry_policy=RetryPolicy(max_attempts=2),
            clock=StepClock(step_seconds=0.0), sleeper=self.sleeper,
            random_source=fixed_random(), **overrides)
        completion = acquire_endpoint(endpoint or _endpoint(), PARAMETERS, context)
        return completion, transport


class TestPagination(AcquisitionTestCase):

    def test_a_single_page_endpoint_stops_after_one_request(self):
        endpoint = _endpoint(pagination=PaginationSpec(
            strategy=PaginationStrategy.SINGLE_PAGE))
        completion, transport = self._acquire([data_page([{"id": 1}])], endpoint)
        self.assertIs(completion.outcome, EndpointOutcome.COMPLETE)
        self.assertTrue(completion.pagination.terminal)
        self.assertEqual(completion.pagination.termination_reason, "SINGLE_PAGE")
        self.assertEqual(transport.call_count, 1)

    def test_page_size_pagination_follows_to_an_empty_page(self):
        completion, transport = self._acquire([
            data_page([{"id": 1}, {"id": 2}]),
            data_page([{"id": 3}, {"id": 4}]),
            data_page([])])
        self.assertIs(completion.outcome, EndpointOutcome.COMPLETE)
        self.assertTrue(completion.pagination.terminal)
        self.assertEqual(completion.pagination.termination_reason, "EMPTY_PAGE")
        self.assertEqual(completion.pagination.pages_fetched, 3)
        self.assertEqual(completion.pagination.records_seen, 4)
        self.assertEqual(transport.call_count, 3)

    def test_each_page_carries_a_distinct_page_number(self):
        completion, _ = self._acquire([
            data_page([{"id": 1}, {"id": 2}]), data_page([])])
        self.assertEqual([record.page_number for record in completion.records],
                         [1, 2])

    def test_each_page_gets_a_distinct_request_key(self):
        completion, _ = self._acquire([
            data_page([{"id": 1}, {"id": 2}]), data_page([])])
        keys = [record.request_key for record in completion.records]
        self.assertEqual(len(set(keys)), len(keys))

    def test_a_cursor_chain_is_followed_to_the_end(self):
        endpoint = _endpoint(pagination=CURSOR_SPEC)
        completion, transport = self._acquire([
            data_page([{"id": 1}, {"id": 2}], meta={"next": "c1"}),
            data_page([{"id": 3}, {"id": 4}], meta={"next": "c2"}),
            data_page([{"id": 5}], meta={"next": None})], endpoint)
        self.assertIs(completion.outcome, EndpointOutcome.COMPLETE)
        self.assertEqual(completion.pagination.termination_reason,
                         "NO_NEXT_CURSOR")
        self.assertEqual(completion.pagination.records_seen, 5)
        self.assertEqual(transport.call_count, 3)

    def test_the_cursor_is_sent_on_the_next_request(self):
        endpoint = _endpoint(pagination=CURSOR_SPEC)
        _, transport = self._acquire([
            data_page([{"id": 1}, {"id": 2}], meta={"next": "CURSOR-ONE"}),
            data_page([], meta={"next": None})], endpoint)
        self.assertIn(("cursor", "CURSOR-ONE"), transport.requests[1].query)

    def test_offset_limit_pagination_advances_by_records_seen(self):
        endpoint = _endpoint(pagination=PaginationSpec(
            strategy=PaginationStrategy.OFFSET_LIMIT, page_size=2, max_pages=5))
        _, transport = self._acquire([
            data_page([{"id": 1}, {"id": 2}]), data_page([])], endpoint)
        self.assertIn(("offset", "0"), transport.requests[0].query)
        self.assertIn(("offset", "2"), transport.requests[1].query)


class TestPaginationGuards(AcquisitionTestCase):
    """Each guard: the endpoint fails, and it is not terminal."""

    def _assert_not_terminal(self, completion, reason):
        self.assertIs(completion.outcome, EndpointOutcome.FAILED)
        self.assertFalse(completion.pagination.terminal)
        self.assertEqual(completion.pagination.termination_reason, reason)

    def test_the_page_budget_stops_a_run_without_completing_it(self):
        endpoint = _endpoint(pagination=PaginationSpec(
            strategy=PaginationStrategy.PAGE_SIZE, page_size=2, max_pages=2))
        completion, transport = self._acquire([
            data_page([{"id": 1}, {"id": 2}]),
            data_page([{"id": 3}, {"id": 4}])], endpoint)
        self._assert_not_terminal(completion, "MAX_PAGES_REACHED")
        self.assertEqual(transport.call_count, 2)
        self.assertIn("unknown fraction", completion.error_detail)

    def test_the_record_budget_stops_a_run_without_completing_it(self):
        endpoint = _endpoint(pagination=PaginationSpec(
            strategy=PaginationStrategy.PAGE_SIZE, page_size=2, max_pages=10,
            max_records=3))
        completion, _ = self._acquire([
            data_page([{"id": 1}, {"id": 2}]),
            data_page([{"id": 3}, {"id": 4}])], endpoint)
        self._assert_not_terminal(completion, "MAX_RECORDS_REACHED")

    def test_a_repeated_cursor_is_detected(self):
        endpoint = _endpoint(pagination=CURSOR_SPEC)
        completion, transport = self._acquire([
            data_page([{"id": 1}, {"id": 2}], meta={"next": "loop"}),
            data_page([{"id": 3}, {"id": 4}], meta={"next": "loop"})], endpoint)
        self._assert_not_terminal(completion, "REPEATED_CURSOR")
        self.assertIn("looping", completion.error_detail)
        self.assertEqual(transport.call_count, 2)

    def test_a_malformed_cursor_is_an_error_not_an_ending(self):
        endpoint = _endpoint(pagination=CURSOR_SPEC)
        completion, _ = self._acquire([
            data_page([{"id": 1}, {"id": 2}], meta={"next": 42})], endpoint)
        self._assert_not_terminal(completion, "MALFORMED_CURSOR")

    def test_an_empty_string_cursor_is_malformed_not_absent(self):
        with self.assertRaises(PaginationError):
            read_next_cursor(CURSOR_SPEC, {"meta": {"next": "   "}})

    def test_an_absent_cursor_field_ends_pagination_cleanly(self):
        self.assertIsNone(read_next_cursor(CURSOR_SPEC, {"meta": {}}))

    def test_a_non_advancing_page_counter_is_caught_as_a_repeated_key(self):
        """A spec that always builds the same query must not loop forever."""
        endpoint = _endpoint(pagination=PaginationSpec(
            strategy=PaginationStrategy.CURSOR, cursor_param="cursor",
            limit_param="limit", page_size=2, next_cursor_path=("meta", "next"),
            max_pages=10))
        completion, transport = self._acquire([
            data_page([{"id": 1}, {"id": 2}], meta={"next": "same"}),
            data_page([{"id": 3}, {"id": 4}], meta={"next": "same"})], endpoint)
        self.assertIn(completion.pagination.termination_reason,
                      ("REPEATED_CURSOR", "REPEATED_REQUEST_KEY"))
        self.assertFalse(completion.pagination.terminal)

    def test_a_cursor_endpoint_must_declare_where_the_cursor_lives(self):
        with self.assertRaises(ConfigurationError):
            PaginationSpec(strategy=PaginationStrategy.CURSOR,
                           next_cursor_path=())


class TestResponseValidation(AcquisitionTestCase):

    def test_corrupt_json_fails_the_endpoint(self):
        completion, _ = self._acquire([raw_response(b'{"data": [')])
        self.assertIs(completion.outcome, EndpointOutcome.FAILED)
        self.assertIs(completion.records[0].parse_status, ParseStatus.INVALID_JSON)

    def test_the_raw_bytes_of_a_corrupt_response_are_still_preserved(self):
        """A failed run must remain diagnosable."""
        body = b'{"data": ['
        completion, _ = self._acquire([raw_response(body)])
        record = completion.records[0]
        self.assertEqual(record.byte_length, len(body))
        self.assertIsNotNone(record.raw_sha256)
        self.assertIsNotNone(record.cache_blob_ref)
        self.assertEqual(self.cache.load(record.request_key).body, body)

    def test_a_wrong_content_type_fails_the_endpoint(self):
        completion, _ = self._acquire([
            raw_response(b"<html>error</html>", content_type="text/html")])
        self.assertIs(completion.records[0].parse_status,
                      ParseStatus.UNEXPECTED_CONTENT_TYPE)
        self.assertIs(completion.outcome, EndpointOutcome.FAILED)

    def test_a_wrong_top_level_shape_fails_the_endpoint(self):
        completion, _ = self._acquire([json_response([1, 2, 3])])
        self.assertIs(completion.records[0].parse_status,
                      ParseStatus.UNEXPECTED_SHAPE)

    def test_a_missing_records_field_fails_rather_than_guessing(self):
        """The legacy probe wrapped the payload and reported one record."""
        completion, _ = self._acquire([json_response({"items": [{"id": 1}]})])
        self.assertIs(completion.records[0].parse_status,
                      ParseStatus.UNEXPECTED_SHAPE)
        self.assertIn("legacy probe", completion.error_detail)

    def test_a_null_records_field_is_not_an_empty_list(self):
        completion, _ = self._acquire([json_response({"data": None})])
        self.assertIs(completion.records[0].parse_status,
                      ParseStatus.UNEXPECTED_SHAPE)

    def test_an_empty_body_fails(self):
        completion, _ = self._acquire([raw_response(b"")])
        self.assertIs(completion.outcome, EndpointOutcome.FAILED)

    def test_records_are_passed_through_untouched(self):
        record = {"id": "PA1", "unknownField": {"nested": [1, 2]},
                  "symbol": "CYP2C19"}
        completion, _ = self._acquire([data_page([record]), data_page([])])
        stored = self.cache.load(completion.records[0].request_key).body
        import json as _json
        self.assertEqual(_json.loads(stored)["data"][0], record)

    def test_a_response_larger_than_the_limit_is_refused(self):
        from pgx.ingestion.common.errors import ResponseTooLargeError
        from pgx.ingestion.common.http import TransportPolicy, UrllibTransport

        policy = TransportPolicy(allowed_hosts=("api.clinpgx.org",),
                                 max_response_bytes=10)
        transport = UrllibTransport(policy)
        with self.assertRaises(ResponseTooLargeError):
            transport._build(
                _endpoint_request(), 200, b"x" * 11, {}, "https://x", EPOCH)


def _endpoint_request():
    from pgx.ingestion.common.models import HttpRequest

    return HttpRequest(method="GET", base_url="https://api.clinpgx.org/v1",
                       path="/data/gene", endpoint_id="gene_lookup")


class TestCompleteness(AcquisitionTestCase):
    """The central claim: a run that did not finish must not look finished."""

    def _manifest(self, script, endpoint_ids=("gene_lookup",)):
        transport = ScriptedTransport(script)
        service = self._service(transport)
        return service.acquire(PARAMETERS, endpoint_ids), transport

    def test_a_finished_required_endpoint_gives_complete(self):
        manifest, _ = self._manifest([
            data_page([{"id": 1}]), data_page([])])
        self.assertIs(manifest.status, AcquisitionStatus.COMPLETE)
        self.assertTrue(manifest.is_publishable)
        self.assertEqual(manifest.failures, ())

    def test_a_failed_required_endpoint_gives_failed(self):
        manifest, _ = self._manifest([raw_response(b"not json")])
        self.assertIs(manifest.status, AcquisitionStatus.FAILED)
        self.assertFalse(manifest.is_publishable)
        self.assertTrue(manifest.failures)

    def test_incomplete_required_pagination_gives_failed(self):
        """The pages collected are an unknown fraction of the endpoint."""
        service = self._service(ScriptedTransport(
            [data_page([{"id": n}]) for n in range(300)]))
        manifest = service.acquire(PARAMETERS, ["gene_lookup"])
        self.assertIs(manifest.status, AcquisitionStatus.FAILED)
        self.assertTrue(any("unknown fraction" in item
                            for item in manifest.failures))

    def test_a_failed_optional_endpoint_is_a_warning_not_a_failure(self):
        service = self._service(ScriptedTransport([
            data_page([{"id": 1}]), data_page([]),        # required gene
            data_page([{"id": 2}]), data_page([]),        # required chemical
            data_page([{"id": 3}]), data_page([]),        # required pair
            raw_response(b"not json"),                     # optional by-gene
        ]))
        manifest = service.acquire(PARAMETERS, [
            "gene_lookup", "chemical_lookup", "guideline_annotation_by_pair",
            "guideline_annotation_by_gene"])
        self.assertIs(manifest.status, AcquisitionStatus.COMPLETE_WITH_WARNINGS)
        self.assertTrue(manifest.is_publishable)
        self.assertEqual(len(manifest.warnings), 1)
        self.assertIn("guideline_annotation_by_gene", manifest.warnings[0])
        self.assertEqual(manifest.failures, ())

    def test_one_required_failure_outweighs_every_success(self):
        service = self._service(ScriptedTransport([
            data_page([{"id": 1}]), data_page([]),
            raw_response(b"not json"),
        ]))
        manifest = service.acquire(PARAMETERS,
                                   ["gene_lookup", "chemical_lookup"])
        self.assertIs(manifest.status, AcquisitionStatus.FAILED)
        self.assertFalse(manifest.is_publishable)

    def test_the_required_and_optional_split_is_visible_in_the_manifest(self):
        manifest, _ = self._manifest([data_page([{"id": 1}]), data_page([])])
        document = manifest.to_json()
        self.assertIn("required", document["endpoints"][0])
        self.assertTrue(document["endpoints"][0]["required"])

    def test_the_records_of_a_failed_run_are_kept(self):
        manifest, _ = self._manifest([raw_response(b"not json")])
        self.assertEqual(len(manifest.endpoints[0].records), 1)
        self.assertIsNotNone(manifest.endpoints[0].records[0].raw_sha256)

    def test_the_status_cannot_be_supplied_by_a_caller(self):
        """It is computed from the endpoint outcomes and nothing else."""
        import inspect

        from pgx.ingestion.common.manifest import build_acquisition_manifest

        parameters = inspect.signature(build_acquisition_manifest).parameters
        self.assertNotIn("status", parameters)


class TestRetrievalMetadata(AcquisitionTestCase):

    def test_a_successful_record_carries_everything_required(self):
        completion, _ = self._acquire([data_page([{"id": 1}]), data_page([])])
        record = completion.records[0]
        for field in ("request_key", "endpoint_id", "method", "url",
                      "raw_sha256", "cache_blob_ref"):
            self.assertIsNotNone(getattr(record, field), field)
        self.assertEqual(record.status_code, 200)
        self.assertEqual(record.content_type, "application/json")
        self.assertIs(record.parse_status, ParseStatus.OK)
        self.assertEqual(record.record_count, 1)
        self.assertIs(record.cache_state, CacheState.MISS)
        self.assertGreater(record.byte_length, 0)

    def test_retries_are_counted_on_the_record(self):
        completion, _ = self._acquire([
            json_response({}, status_code=503),
            data_page([{"id": 1}]),
            data_page([])])
        self.assertEqual(completion.records[0].retry_count, 1)
        self.assertEqual(len(completion.records[0].attempts), 2)

    def test_rate_limit_metadata_is_recorded(self):
        completion, _ = self._acquire([
            data_page([{"id": 1}]),
            data_page([])],
            _endpoint(pagination=PaginationSpec(
                strategy=PaginationStrategy.SINGLE_PAGE)))
        self.assertTrue(completion.records[0].rate_limit.is_empty)

    def test_the_safe_query_is_recorded_and_carries_no_credential(self):
        completion, _ = self._acquire([data_page([]), ])
        record = completion.records[0]
        rendered = str(record.to_json())
        for token in ("Authorization", "Bearer", "api_key"):
            self.assertNotIn(token, rendered)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
