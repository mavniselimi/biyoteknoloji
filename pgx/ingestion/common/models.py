# -*- coding: utf-8 -*-
"""Request, response and run records (WP-04).

Standard library only. Frozen dataclasses throughout, for the same reason the
domain uses them: a retrieval record that could be edited after the fact is not
a record.

The central distinction in this module is between **content identity** and
**operational metadata**, and it is worth being explicit about because getting
it wrong would undermine the whole work package.

*Content identity* is what was asked for and what came back: the canonical
request key, the endpoint, the raw SHA-256, the byte length. Two runs that ask
the same questions and receive the same bytes have the same content identity,
whether one hit the network and the other replayed from cache.

*Operational metadata* is how the run went: timestamps, how many attempts it
took, whether the cache was hit, what the rate-limit headers said. It belongs in
the manifest, and it must never reach a content hash - otherwise a cache replay
would produce a different "identity" for identical data, and the determinism
guarantee would be worthless.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Tuple

from pgx.domain.hashing import ensure_utc
from pgx.domain.immutable import EMPTY_MAPPING, freeze_json

__all__ = [
    "AcquisitionRunId",
    "AcquisitionStatus",
    "CacheState",
    "EndpointCompletion",
    "EndpointOutcome",
    "HttpRequest",
    "HttpResponse",
    "PaginationState",
    "ParseStatus",
    "RateLimitInfo",
    "RetrievalAttempt",
    "RetrievalRecord",
]


@dataclass(frozen=True, slots=True)
class AcquisitionRunId:
    """Identity of one acquisition run.

    Deliberately a wrapper rather than a bare UUID, matching the domain's
    identifier policy: a run identity is minted by an explicit call, never as a
    side effect of constructing something else.
    """

    value: uuid.UUID

    @classmethod
    def new(cls) -> "AcquisitionRunId":
        """Explicitly mint a fresh run identity."""
        return cls(uuid.uuid4())

    @classmethod
    def parse(cls, raw: str) -> "AcquisitionRunId":
        """Parse a canonical UUID string."""
        return cls(uuid.UUID(raw))

    def to_json(self) -> str:
        """Stable string form."""
        return str(self.value)

    def __str__(self) -> str:
        return str(self.value)


class AcquisitionStatus(str, Enum):
    """How a run ended.

    ``COMPLETE_WITH_WARNINGS`` exists for one narrow case: every *required*
    endpoint finished, and an *optional* one did not. A missing required
    endpoint or an unfinished required pagination is never a warning - it is
    ``FAILED``, because the alternative is publishing an unknown fraction of a
    source and calling it the source.
    """

    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    COMPLETE_WITH_WARNINGS = "COMPLETE_WITH_WARNINGS"
    FAILED = "FAILED"

    @property
    def is_publishable(self) -> bool:
        """True only when every required endpoint finished.

        The one question a downstream work package should ever ask of a run.
        """
        return self in (AcquisitionStatus.COMPLETE,
                        AcquisitionStatus.COMPLETE_WITH_WARNINGS)


class CacheState(str, Enum):
    """Where a response came from."""

    MISS = "MISS"
    HIT = "HIT"
    BYPASS = "BYPASS"


class ParseStatus(str, Enum):
    """What happened when the raw bytes were interpreted.

    ``NOT_ATTEMPTED`` is a real state: the bytes are stored and hashed before
    anything tries to parse them, so a body that never got as far as parsing
    still has a complete retrieval record.
    """

    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    OK = "OK"
    INVALID_JSON = "INVALID_JSON"
    UNEXPECTED_SHAPE = "UNEXPECTED_SHAPE"
    UNEXPECTED_CONTENT_TYPE = "UNEXPECTED_CONTENT_TYPE"


class EndpointOutcome(str, Enum):
    """How one endpoint's acquisition ended."""

    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True, slots=True)
class RateLimitInfo:
    """Rate-limit metadata a response advertised.

    All fields optional: most responses carry none of this, and inventing
    values would be worse than recording their absence.
    """

    limit: Optional[int] = None
    remaining: Optional[int] = None
    reset_seconds: Optional[float] = None
    retry_after_seconds: Optional[float] = None

    @property
    def is_empty(self) -> bool:
        """True when the response advertised no rate-limit information."""
        return all(value is None for value in
                   (self.limit, self.remaining, self.reset_seconds,
                    self.retry_after_seconds))

    def to_json(self) -> Mapping[str, Any]:
        """Machine-readable form."""
        return {"limit": self.limit, "remaining": self.remaining,
                "reset_seconds": self.reset_seconds,
                "retry_after_seconds": self.retry_after_seconds}


@dataclass(frozen=True, slots=True)
class HttpRequest:
    """One request, in the exact form the transport will send it.

    ``query`` is a tuple of pairs rather than a mapping, because a query string
    can legitimately repeat a key and because tuples preserve the order the
    caller chose. The request key sorts them separately, so ordering affects the
    wire format and never the identity.

    ``headers`` carries only safe headers. Credentials never live here: the
    transport adds them at send time from injected configuration, so no
    credential can reach a request key, a cache entry, a manifest or a log.
    """

    method: str
    base_url: str
    path: str
    endpoint_id: str
    query: Tuple[Tuple[str, str], ...] = ()
    headers: Mapping[str, str] = field(default=EMPTY_MAPPING)
    timeout_seconds: float = 30.0
    expected_content_type: str = "application/json"
    response_shape_version: str = "v1"

    def __post_init__(self) -> None:
        if self.method != self.method.upper():
            object.__setattr__(self, "method", self.method.upper())
        object.__setattr__(self, "query", tuple(
            (str(name), str(value)) for name, value in self.query))
        object.__setattr__(self, "headers", freeze_json(dict(self.headers)))

    @property
    def url(self) -> str:
        """The full URL without its query string."""
        return self.base_url.rstrip("/") + "/" + self.path.lstrip("/")

    def with_query(self, query: Tuple[Tuple[str, str], ...]) -> "HttpRequest":
        """Return the same request with a different query. Mutates nothing."""
        import dataclasses

        return dataclasses.replace(self, query=query)


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """One response, with its body kept as raw bytes.

    The body is **bytes**, never a decoded string and never a parsed object.
    Everything downstream - the digest, the cache blob, the manifest entry -
    derives from these exact bytes, so a decode that guessed an encoding would
    silently change the identity of the data.
    """

    status_code: int
    body: bytes
    headers: Mapping[str, str] = field(default=EMPTY_MAPPING)
    final_url: str = ""
    requested_at: Optional[_dt.datetime] = None
    received_at: Optional[_dt.datetime] = None
    redirect_count: int = 0
    redirect_chain: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.body, (bytes, bytearray)):
            raise TypeError(
                "HttpResponse.body must be bytes; a decoded string would change "
                "the identity of the data, got %r" % type(self.body).__name__)
        object.__setattr__(self, "body", bytes(self.body))
        object.__setattr__(self, "headers", freeze_json(
            {str(name).lower(): str(value) for name, value in self.headers.items()}))
        object.__setattr__(self, "redirect_chain", tuple(self.redirect_chain))
        for name in ("requested_at", "received_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, ensure_utc(value, name))

    @property
    def byte_length(self) -> int:
        """Size of the raw body."""
        return len(self.body)

    @property
    def content_type(self) -> str:
        """Media type without parameters, lower-cased."""
        raw = self.headers.get("content-type", "")
        return raw.split(";")[0].strip().lower()

    def header(self, name: str) -> Optional[str]:
        """Case-insensitive header lookup."""
        return self.headers.get(name.lower())


@dataclass(frozen=True, slots=True)
class RetrievalAttempt:
    """One attempt at one request, successful or not.

    Every attempt is recorded, including the ones that failed. A run that
    succeeded on the fourth try after three 503s is operationally different
    from one that succeeded immediately, and an operator deciding whether a
    source is healthy needs to see the difference.
    """

    attempt_number: int
    started_at: _dt.datetime
    status_code: Optional[int] = None
    error_code: Optional[str] = None
    retry_reason: Optional[str] = None
    delay_before_seconds: float = 0.0
    retry_after_seconds: Optional[float] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "started_at", ensure_utc(self.started_at, "started_at"))

    def to_json(self) -> Mapping[str, Any]:
        """Machine-readable form."""
        return {
            "attempt_number": self.attempt_number,
            "started_at": self.started_at.isoformat(),
            "status_code": self.status_code,
            "error_code": self.error_code,
            "retry_reason": self.retry_reason,
            "delay_before_seconds": self.delay_before_seconds,
            "retry_after_seconds": self.retry_after_seconds,
        }


@dataclass(frozen=True, slots=True)
class RetrievalRecord:
    """Everything known about one retrieved page.

    Split into two halves on purpose - see the module docstring.
    :meth:`content_identity` returns only what a re-run must reproduce;
    :meth:`to_json` returns everything, for the run manifest.
    """

    request_key: str
    endpoint_id: str
    method: str
    url: str
    safe_query: Tuple[Tuple[str, str], ...]
    page_number: int
    cursor: Optional[str]
    started_at: _dt.datetime
    completed_at: _dt.datetime
    status_code: Optional[int]
    raw_sha256: Optional[str]
    byte_length: int
    content_type: str
    cache_state: CacheState
    cache_blob_ref: Optional[str]
    parse_status: ParseStatus
    record_count: Optional[int]
    attempts: Tuple[RetrievalAttempt, ...] = ()
    rate_limit: RateLimitInfo = field(default_factory=RateLimitInfo)
    error_code: Optional[str] = None
    error_detail: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "started_at", ensure_utc(self.started_at, "started_at"))
        object.__setattr__(self, "completed_at",
                           ensure_utc(self.completed_at, "completed_at"))
        object.__setattr__(self, "safe_query", tuple(
            (str(name), str(value)) for name, value in self.safe_query))
        object.__setattr__(self, "attempts", tuple(self.attempts))

    @property
    def succeeded(self) -> bool:
        """True when this page was retrieved and parsed."""
        return self.error_code is None and self.parse_status is ParseStatus.OK

    @property
    def retry_count(self) -> int:
        """How many retries were needed. Zero means it worked first time."""
        return max(0, len(self.attempts) - 1)

    def content_identity(self) -> Mapping[str, Any]:
        """Only what a re-run must reproduce byte for byte.

        No timestamp, no attempt count, no cache state. A network run and a
        cache replay of the same data return identical values here, which is
        what makes the deterministic content manifest meaningful.
        """
        return {
            "request_key": self.request_key,
            "endpoint_id": self.endpoint_id,
            "page_number": self.page_number,
            "cursor": self.cursor,
            "raw_sha256": self.raw_sha256,
            "byte_length": self.byte_length,
        }

    def to_json(self) -> Mapping[str, Any]:
        """Everything, for the run manifest."""
        return {
            "request_key": self.request_key,
            "endpoint_id": self.endpoint_id,
            "method": self.method,
            "url": self.url,
            "safe_query": [list(pair) for pair in self.safe_query],
            "page_number": self.page_number,
            "cursor": self.cursor,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "status_code": self.status_code,
            "raw_sha256": self.raw_sha256,
            "byte_length": self.byte_length,
            "content_type": self.content_type,
            "cache_state": self.cache_state.value,
            "cache_blob_ref": self.cache_blob_ref,
            "parse_status": self.parse_status.value,
            "record_count": self.record_count,
            "retry_count": self.retry_count,
            "attempts": [attempt.to_json() for attempt in self.attempts],
            "rate_limit": self.rate_limit.to_json(),
            "error_code": self.error_code,
            "error_detail": self.error_detail,
        }


@dataclass(frozen=True, slots=True)
class PaginationState:
    """Where an endpoint's pagination ended up.

    ``terminal`` is the field that decides completeness. It is ``True`` only
    when the source said there is nothing more - an empty page, an absent next
    cursor, or a declared last page. Running out of the page budget is not
    terminal, and neither is an error.
    """

    pages_fetched: int
    records_seen: int
    terminal: bool
    termination_reason: str
    last_cursor: Optional[str] = None

    def to_json(self) -> Mapping[str, Any]:
        """Machine-readable form."""
        return {
            "pages_fetched": self.pages_fetched,
            "records_seen": self.records_seen,
            "terminal": self.terminal,
            "termination_reason": self.termination_reason,
            "last_cursor": self.last_cursor,
        }


@dataclass(frozen=True, slots=True)
class EndpointCompletion:
    """Whether one endpoint finished, and whether that matters.

    ``required`` is carried here rather than looked up later so a manifest can
    be read on its own: "this endpoint failed" is meaningless without "and it
    was required".
    """

    endpoint_id: str
    required: bool
    outcome: EndpointOutcome
    pagination: PaginationState
    records: Tuple[RetrievalRecord, ...] = ()
    error_code: Optional[str] = None
    error_detail: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))

    @property
    def blocks_completion(self) -> bool:
        """True when this endpoint's state prevents the run from completing.

        A required endpoint that did not finish, or whose pagination never
        reached a terminal state, blocks. An optional one never does.
        """
        if not self.required:
            return False
        return (self.outcome is not EndpointOutcome.COMPLETE
                or not self.pagination.terminal)

    def to_json(self) -> Mapping[str, Any]:
        """Machine-readable form."""
        return {
            "endpoint_id": self.endpoint_id,
            "required": self.required,
            "outcome": self.outcome.value,
            "pagination": self.pagination.to_json(),
            "record_count": len(self.records),
            "records": [record.to_json() for record in self.records],
            "error_code": self.error_code,
            "error_detail": self.error_detail,
        }
