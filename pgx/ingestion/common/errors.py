# -*- coding: utf-8 -*-
"""Typed ingestion failures (WP-04).

Standard library only.

The type hierarchy is the retry policy's input, so the split is functional
rather than decorative:

* :class:`TransientTransportError` - worth retrying. A timeout or a reset
  connection says nothing about whether the request was valid.
* :class:`PermanentTransportError` - never retried. A 404 will still be a 404
  in eight seconds, and retrying it wastes the budget that a genuinely
  transient failure needs.
* :class:`ConfigurationError` - the run should not have started. Raised before
  any request, and never retried.
* :class:`ResponseValidationError` and its subclasses - the bytes arrived and
  are unusable. Retrying corrupt JSON just fetches corrupt JSON again.

A failure that cannot be classified is **not** retried. Guessing "probably
transient" turns one bad request into a storm of them.
"""

from __future__ import annotations

from typing import Optional

__all__ = [
    "CacheCorruptionError",
    "CacheError",
    "CacheMissError",
    "CacheWriteConflictError",
    "ConfigurationError",
    "ContentTypeError",
    "IngestionError",
    "PaginationError",
    "PermanentTransportError",
    "ResponseShapeError",
    "ResponseTooLargeError",
    "ResponseValidationError",
    "RetryBudgetExhaustedError",
    "SecurityPolicyError",
    "TransientTransportError",
    "TransportError",
]


class IngestionError(Exception):
    """Base class for every acquisition failure."""


# ---------------------------------------------------------------------------
# Configuration and safety - raised before or instead of a request
# ---------------------------------------------------------------------------


class ConfigurationError(IngestionError):
    """The run is misconfigured and must not start.

    Never retried: a missing base URL or an unusable cache root will not fix
    itself between attempts.
    """


class SecurityPolicyError(ConfigurationError):
    """A request or redirect would leave the allowed host or scheme.

    A subclass of :class:`ConfigurationError` on purpose: a request that
    violates the transport policy is a configuration mistake, not a network
    condition, and must fail the run rather than be retried into submission.
    """


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


class TransportError(IngestionError):
    """A request did not produce a usable response."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TransientTransportError(TransportError):
    """A failure that may not recur: timeout, reset connection, 5xx, 429."""


class PermanentTransportError(TransportError):
    """A failure that will recur: 400, 401, 403, 404.

    Retrying these is not merely useless. A retried 401 looks like a
    brute-force attempt from the far end, and a retried 429 that was really a
    quota exhaustion makes the quota worse.
    """


class RetryBudgetExhaustedError(TransportError):
    """Every permitted attempt was made and all of them failed.

    Terminal and explicit. The distinction from
    :class:`TransientTransportError` matters: "this attempt failed" and "we are
    out of attempts" call for different operator responses.
    """

    def __init__(self, message: str, attempts: int = 0,
                 status_code: Optional[int] = None) -> None:
        super().__init__(message, status_code)
        self.attempts = attempts


# ---------------------------------------------------------------------------
# Response validation - the bytes arrived and are unusable
# ---------------------------------------------------------------------------


class ResponseValidationError(IngestionError):
    """A response cannot be used, whatever its status code said."""


class ContentTypeError(ResponseValidationError):
    """The response is not the media type the endpoint declared."""


class ResponseShapeError(ResponseValidationError):
    """The parsed body is not the shape the endpoint declared.

    Deliberately a failure rather than a shrug. The legacy probe's
    ``flatten_items`` tried six container keys in turn and fell back to wrapping
    the whole payload in a list, so a completely unexpected response still
    produced "one record" and the run still looked fine.
    """


class ResponseTooLargeError(ResponseValidationError):
    """The body exceeded the configured byte limit.

    The limit exists because an unbounded read is a denial-of-service against
    ourselves: one endpoint answering with a gigabyte would exhaust memory
    before any other check could run.
    """


class PaginationError(ResponseValidationError):
    """Pagination could not reach a terminal state.

    Covers a malformed cursor, a cursor that repeats, a page limit reached with
    more pages outstanding, and a next-link that does not resolve. Every one of
    them means the collected pages are an unknown fraction of the whole, so
    reporting them as a complete endpoint would be a lie.
    """


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class CacheError(IngestionError):
    """The cache could not satisfy or record a request."""


class CacheMissError(CacheError):
    """Cache-only mode was asked for something the cache does not hold.

    An explicit failure, never a silent fall-through to the network: the whole
    point of cache-only mode is that it makes no requests.
    """


class CacheCorruptionError(CacheError):
    """A stored blob is missing, unreadable, or does not match its digest.

    Never treated as a miss. A corrupt cache that degrades to a cache miss
    hides the corruption and re-fetches, which is how a broken cache stays
    broken and unnoticed for months.
    """


class CacheWriteConflictError(CacheError):
    """A blob already exists at this digest with different bytes.

    Under SHA-256 that is either a hash collision or a bug in the caller. Both
    warrant stopping rather than overwriting.
    """
