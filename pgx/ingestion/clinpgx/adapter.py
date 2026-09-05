# -*- coding: utf-8 -*-
"""Acquiring one endpoint, page by page, honestly (WP-04).

Standard library only. No network call is made here directly: every request
goes through the injected transport, which is why the whole adapter is testable
against a scripted fake.

**The shape of one endpoint acquisition:**

1. build the request for the next page from the endpoint's declaration;
2. compute its deterministic request key;
3. serve it from cache, or fetch it with bounded retry;
4. store the raw bytes and hash them - **before** parsing;
5. validate the content type and shape, and extract records;
6. decide whether to continue, and record *why* it stopped;
7. return an :class:`EndpointCompletion` that states plainly whether the
   endpoint finished.

**Step 6 is where honesty lives.** Stopping because the source said there is
nothing more is completion. Stopping because the page budget ran out, because a
cursor repeated, or because a request failed is *not*, and
:class:`~pgx.ingestion.common.models.PaginationState.terminal` records the
difference. Everything downstream - the manifest status, whether the run is
publishable - reads that one field.

Failures are returned, not raised. A failed endpoint still produces a completion
record with everything known about it, so one bad endpoint cannot destroy the
account of the other seven.
"""

from __future__ import annotations

import datetime as _dt
import random
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Set, Tuple

from pgx.ingestion.clinpgx.catalog import (
    CLINPGX_BASE_URL, EndpointDeclaration,
)
from pgx.ingestion.clinpgx.parsers import (
    extract_records, parse_json_body, validate_content_type,
)
from pgx.ingestion.common.cache import ResponseCache, sha256_bytes
from pgx.ingestion.common.errors import (
    CacheCorruptionError, CacheMissError, ConfigurationError, IngestionError,
    PaginationError, ResponseValidationError, SecurityPolicyError,
)
from pgx.ingestion.common.http import parse_rate_limit, request_key
from pgx.ingestion.common.models import (
    CacheState, EndpointCompletion, EndpointOutcome, HttpRequest, PaginationState,
    ParseStatus, RateLimitInfo, RetrievalRecord,
)
from pgx.ingestion.common.pagination import (
    PaginationStrategy, TerminationReason, next_page_request, read_next_cursor,
)
from pgx.ingestion.common.retry import RetryPolicy, execute_with_retry

__all__ = ["AcquisitionContext", "acquire_endpoint", "build_page_request"]


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _sleep(seconds: float) -> None:  # pragma: no cover - replaced in tests
    import time

    time.sleep(seconds)


@dataclass
class AcquisitionContext:
    """Everything one endpoint acquisition needs, all injected.

    ``transport`` may be ``None`` only in cache-only mode; a cache-only run that
    could fall back to the network would not be cache-only, so the attribute is
    absent rather than unused.
    """

    cache: ResponseCache
    transport: Any = None
    retry_policy: RetryPolicy = None
    base_url: str = CLINPGX_BASE_URL
    timeout_seconds: float = 30.0
    cache_only: bool = False
    refresh: bool = False
    clock: Callable[[], _dt.datetime] = _utc_now
    sleeper: Callable[[float], None] = _sleep
    random_source: Callable[[], float] = random.random

    def __post_init__(self) -> None:
        if self.retry_policy is None:
            self.retry_policy = RetryPolicy()
        if self.cache_only and self.refresh:
            raise ConfigurationError(
                "cache_only and refresh are contradictory: one forbids the "
                "network, the other insists on it")
        if not self.cache_only and self.transport is None:
            raise ConfigurationError(
                "a transport is required unless the run is cache-only")


def build_page_request(
    endpoint: EndpointDeclaration,
    parameters: Mapping[str, Any],
    base_url: str,
    timeout_seconds: float,
    page_number: int,
    cursor: Optional[str],
    records_seen: int,
) -> HttpRequest:
    """Build the request for one page.

    Pure: no clock, no network, no global state. That is what lets
    ``plan_acquisition`` show an operator the exact first request of every
    endpoint without touching anything.
    """
    page = next_page_request(endpoint.pagination, page_number, cursor, records_seen)
    query = endpoint.query_for(parameters) + page.query
    return HttpRequest(
        method="GET",
        base_url=base_url,
        path=endpoint.path_for(parameters),
        endpoint_id=endpoint.endpoint_id,
        query=query,
        headers={"Accept": "application/json"},
        timeout_seconds=timeout_seconds,
        expected_content_type="application/json")


def acquire_endpoint(
    endpoint: EndpointDeclaration,
    parameters: Mapping[str, Any],
    context: AcquisitionContext,
) -> EndpointCompletion:
    """Acquire every page of one endpoint and report honestly on the result."""
    records: List[RetrievalRecord] = []
    seen_cursors: Set[str] = set()
    seen_keys: Set[str] = set()
    spec = endpoint.pagination

    page_number = spec.first_page_number
    cursor: Optional[str] = None
    records_seen = 0
    pages_fetched = 0
    termination = TerminationReason.ERROR
    error_code: Optional[str] = None
    error_detail: Optional[str] = None

    while True:
        if pages_fetched >= spec.max_pages:
            termination = TerminationReason.MAX_PAGES_REACHED
            error_code = "MAX_PAGES_REACHED"
            error_detail = (
                "stopped after %d page(s) without reaching the end of the "
                "endpoint; the collected pages are an unknown fraction of it"
                % pages_fetched)
            break

        try:
            request = build_page_request(
                endpoint, parameters, context.base_url, context.timeout_seconds,
                page_number, cursor, records_seen)
        except ConfigurationError as exc:
            termination = TerminationReason.ERROR
            error_code = "CONFIGURATION_ERROR"
            error_detail = str(exc)
            break

        key = request_key(request)
        if key in seen_keys:
            # The same question twice means the cursor or page counter is not
            # advancing. Following it would loop until a budget ran out and
            # then look like a budget problem.
            termination = TerminationReason.REPEATED_REQUEST_KEY
            error_code = "REPEATED_REQUEST_KEY"
            error_detail = (
                "page %d repeats an earlier request key; pagination is not "
                "advancing" % page_number)
            break
        seen_keys.add(key)

        record, payload, failed = _fetch_one_page(
            endpoint, request, key, page_number, cursor, context)
        records.append(record)
        pages_fetched += 1

        if failed:
            termination = TerminationReason.ERROR
            error_code = record.error_code
            error_detail = record.error_detail
            break

        page_records = payload["records"]
        records_seen += len(page_records)

        if not spec.paginates:
            termination = TerminationReason.SINGLE_PAGE
            break

        if not page_records:
            termination = TerminationReason.EMPTY_PAGE
            break

        if records_seen >= spec.max_records:
            termination = TerminationReason.MAX_RECORDS_REACHED
            error_code = "MAX_RECORDS_REACHED"
            error_detail = (
                "stopped after %d record(s) without reaching the end of the "
                "endpoint" % records_seen)
            break

        if spec.strategy in (PaginationStrategy.CURSOR, PaginationStrategy.NEXT_LINK):
            try:
                next_cursor = read_next_cursor(spec, payload["parsed"])
            except PaginationError as exc:
                termination = TerminationReason.MALFORMED_CURSOR
                error_code = "MALFORMED_CURSOR"
                error_detail = str(exc)
                break
            if next_cursor is None:
                termination = TerminationReason.NO_NEXT_CURSOR
                break
            if next_cursor in seen_cursors:
                termination = TerminationReason.REPEATED_CURSOR
                error_code = "REPEATED_CURSOR"
                error_detail = (
                    "cursor %r was already followed; the source is looping"
                    % next_cursor)
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        page_number += 1

    pagination = PaginationState(
        pages_fetched=pages_fetched,
        records_seen=records_seen,
        terminal=termination.is_terminal,
        termination_reason=termination.value,
        last_cursor=cursor)

    outcome = (EndpointOutcome.COMPLETE if termination.is_terminal
               else EndpointOutcome.FAILED)
    return EndpointCompletion(
        endpoint_id=endpoint.endpoint_id,
        required=endpoint.required,
        outcome=outcome,
        pagination=pagination,
        records=tuple(records),
        error_code=error_code,
        error_detail=error_detail)


def _fetch_one_page(
    endpoint: EndpointDeclaration,
    request: HttpRequest,
    key: str,
    page_number: int,
    cursor: Optional[str],
    context: AcquisitionContext,
) -> Tuple[RetrievalRecord, Mapping[str, Any], bool]:
    """Fetch, store and parse one page.

    Returns ``(record, payload, failed)``. The record is complete either way:
    a page whose JSON was corrupt still carries its digest, its byte length and
    its cache reference, because that is exactly what a diagnosis needs.
    """
    started_at = context.clock()
    attempts: Tuple = ()
    rate_limit = RateLimitInfo()
    cache_state = CacheState.MISS
    response = None
    error_code = None
    error_detail = None

    # 1. Cache, unless a refresh was demanded.
    if not context.refresh and context.cache.has(key):
        try:
            response = context.cache.load(key)
            cache_state = CacheState.HIT
        except CacheCorruptionError as exc:
            # Never degraded to a miss: a corrupt cache that silently re-fetches
            # stays corrupt and unnoticed.
            return (_failed_record(
                request, key, page_number, cursor, started_at, context.clock(),
                "CACHE_CORRUPTION", str(exc), cache_state=CacheState.HIT),
                {}, True)

    # 2. Network, if the cache did not answer.
    if response is None:
        if context.cache_only:
            return (_failed_record(
                request, key, page_number, cursor, started_at, context.clock(),
                "CACHE_MISS",
                "cache-only run has no entry for endpoint %r page %d "
                "(request key %s); cache-only mode makes no requests"
                % (endpoint.endpoint_id, page_number, key)),
                {}, True)

        outcome = execute_with_retry(
            transport=context.transport, request=request,
            policy=context.retry_policy, clock=context.clock,
            sleeper=context.sleeper, random_source=context.random_source)
        attempts = outcome.attempts
        if not outcome.succeeded:
            error = outcome.error
            return (_failed_record(
                request, key, page_number, cursor, started_at, context.clock(),
                type(error).__name__ if error else "TRANSPORT_FAILURE",
                str(error) if error else "no response", attempts=attempts),
                {}, True)
        response = outcome.response
        rate_limit = parse_rate_limit(response, started_at)
        cache_state = CacheState.MISS if not context.refresh else CacheState.BYPASS

    # 3. Store the raw bytes and hash them BEFORE parsing. A body that turns
    #    out to be unparseable is still preserved, with its digest.
    digest = sha256_bytes(response.body)
    blob_ref = None
    if cache_state is not CacheState.HIT:
        try:
            entry = context.cache.store(key, response, now=context.clock())
            blob_ref = entry.blob_ref
        except IngestionError as exc:
            return (_failed_record(
                request, key, page_number, cursor, started_at, context.clock(),
                "CACHE_WRITE_FAILURE", str(exc), attempts=attempts,
                raw_sha256=digest, byte_length=len(response.body)),
                {}, True)
    else:
        blob_ref = context.cache.load_entry(key).blob_ref

    completed_at = context.clock()
    base = dict(
        request_key=key, endpoint_id=endpoint.endpoint_id, method=request.method,
        url=request.url, safe_query=request.query, page_number=page_number,
        cursor=cursor, started_at=started_at, completed_at=completed_at,
        status_code=response.status_code, raw_sha256=digest,
        byte_length=len(response.body), content_type=response.content_type,
        cache_state=cache_state, cache_blob_ref=blob_ref, attempts=attempts,
        rate_limit=rate_limit)

    # 4. Only now interpret the bytes.
    try:
        validate_content_type(response, request.expected_content_type)
        parsed = parse_json_body(response)
        page_records = extract_records(parsed, endpoint)
    except ResponseValidationError as exc:
        status = _parse_status_for(exc)
        return (RetrievalRecord(
            parse_status=status, record_count=None,
            error_code=type(exc).__name__, error_detail=str(exc), **base),
            {}, True)

    return (RetrievalRecord(
        parse_status=ParseStatus.OK, record_count=len(page_records), **base),
        {"records": page_records, "parsed": parsed}, False)


def _parse_status_for(error: ResponseValidationError) -> ParseStatus:
    """Map a validation failure to the status recorded on the retrieval."""
    from pgx.ingestion.common.errors import ContentTypeError, ResponseShapeError

    if isinstance(error, ContentTypeError):
        return ParseStatus.UNEXPECTED_CONTENT_TYPE
    if isinstance(error, ResponseShapeError):
        return ParseStatus.UNEXPECTED_SHAPE
    return ParseStatus.INVALID_JSON


def _failed_record(
    request: HttpRequest,
    key: str,
    page_number: int,
    cursor: Optional[str],
    started_at: _dt.datetime,
    completed_at: _dt.datetime,
    error_code: str,
    error_detail: str,
    attempts: Tuple = (),
    cache_state: CacheState = CacheState.MISS,
    raw_sha256: Optional[str] = None,
    byte_length: int = 0,
) -> RetrievalRecord:
    """A retrieval record for a page that did not arrive usable.

    Recorded rather than discarded: a run that failed still has to explain
    which request failed and why.
    """
    return RetrievalRecord(
        request_key=key, endpoint_id=request.endpoint_id, method=request.method,
        url=request.url, safe_query=request.query, page_number=page_number,
        cursor=cursor, started_at=started_at, completed_at=completed_at,
        status_code=None, raw_sha256=raw_sha256, byte_length=byte_length,
        content_type="", cache_state=cache_state, cache_blob_ref=None,
        parse_status=ParseStatus.NOT_ATTEMPTED, record_count=None,
        attempts=attempts, error_code=error_code, error_detail=error_detail)
