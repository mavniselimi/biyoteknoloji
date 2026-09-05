# -*- coding: utf-8 -*-
"""Bounded retry with exponential backoff and jitter (WP-04).

Standard library only. The clock, the sleeper and the randomness are all
injected, so a test can assert the exact delay sequence and the suite never
actually sleeps.

**What is retried, and why the list is short.** A timeout or a reset connection
says nothing about whether the request was valid, so trying again is reasonable.
A 429 or a 5xx is the server saying "not now". Everything else is not retried:

* 400, 401, 403, 404 will be the same in eight seconds. Worse, a retried 401
  looks like a brute-force attempt from the far end, and a retried 429 that was
  really quota exhaustion makes the quota worse.
* Corrupt JSON and shape errors are properties of the payload, so re-fetching
  produces the same corrupt payload.
* Configuration errors mean the run should not have started.

An error that cannot be classified is **not** retried. Guessing "probably
transient" turns one bad request into a storm of them.

**Two bounds, not one.** ``max_attempts`` caps the number of tries;
``max_elapsed_seconds`` caps the wall-clock spent. Either alone is insufficient:
five attempts against a server answering ``Retry-After: 300`` would block a run
for 25 minutes, and an elapsed cap alone would allow unlimited attempts against
a fast-failing endpoint.

**Retry-After wins over backoff, within limits.** When a server states how long
to wait, guessing is worse than listening - but a server (or a hostile one) can
also state an hour, so the value is clamped to ``max_delay_seconds``.
"""

from __future__ import annotations

import datetime as _dt
import random
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple, Type

from pgx.ingestion.common.errors import (
    ConfigurationError, IngestionError, PermanentTransportError,
    ResponseValidationError, RetryBudgetExhaustedError, SecurityPolicyError,
    TransientTransportError,
)
from pgx.ingestion.common.http import parse_retry_after
from pgx.ingestion.common.models import HttpRequest, HttpResponse, RetrievalAttempt

__all__ = [
    "NON_RETRYABLE_STATUSES",
    "RETRYABLE_STATUSES",
    "RetryOutcome",
    "RetryPolicy",
    "execute_with_retry",
]

#: Server-side conditions worth another attempt.
RETRYABLE_STATUSES: Tuple[int, ...] = (429, 500, 502, 503, 504)

#: Client-side conditions that will not change on their own. Listed
#: explicitly so the intent is reviewable rather than implied by omission.
NON_RETRYABLE_STATUSES: Tuple[int, ...] = (400, 401, 403, 404, 405, 409, 410, 422)


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _no_sleep(seconds: float) -> None:  # pragma: no cover - replaced in tests
    import time

    time.sleep(seconds)


@dataclass(frozen=True)
class RetryPolicy:
    """How many times, how long between, and how long in total."""

    max_attempts: int = 4
    initial_delay_seconds: float = 0.5
    multiplier: float = 2.0
    max_delay_seconds: float = 30.0
    jitter_ratio: float = 0.25
    max_elapsed_seconds: float = 120.0
    retryable_statuses: Tuple[int, ...] = RETRYABLE_STATUSES
    retryable_exceptions: Tuple[Type[BaseException], ...] = (TransientTransportError,)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ConfigurationError("max_attempts must be at least 1")
        if self.initial_delay_seconds < 0:
            raise ConfigurationError("initial_delay_seconds must not be negative")
        if self.multiplier < 1.0:
            raise ConfigurationError(
                "multiplier must be at least 1.0; a shrinking backoff would "
                "retry hardest exactly when the server is most overloaded")
        if not 0.0 <= self.jitter_ratio <= 1.0:
            raise ConfigurationError("jitter_ratio must be between 0 and 1")
        if self.max_delay_seconds < 0:
            raise ConfigurationError("max_delay_seconds must not be negative")

    def base_delay(self, attempt_number: int) -> float:
        """Exponential backoff for ``attempt_number``, capped, before jitter."""
        if attempt_number <= 1:
            return min(self.initial_delay_seconds, self.max_delay_seconds)
        delay = self.initial_delay_seconds * (self.multiplier ** (attempt_number - 1))
        return min(delay, self.max_delay_seconds)

    def apply_jitter(self, delay: float, random_value: float) -> float:
        """Spread a delay by +/- ``jitter_ratio``.

        Jitter matters when several clients back off together: without it they
        all return at the same instant and re-create the overload they were
        waiting out. ``random_value`` is injected, so the result is bounded and
        testable.
        """
        if self.jitter_ratio == 0.0 or delay == 0.0:
            return delay
        spread = delay * self.jitter_ratio
        return max(0.0, delay - spread + (2.0 * spread * random_value))

    def should_retry_status(self, status_code: int) -> bool:
        """True when a status code is worth another attempt."""
        return status_code in self.retryable_statuses

    def should_retry_exception(self, error: BaseException) -> bool:
        """True when an exception is worth another attempt.

        Non-retryable classes are checked first: :class:`SecurityPolicyError`
        subclasses :class:`ConfigurationError`, and a policy that listed
        ``IngestionError`` as retryable must still never retry a refused host.
        """
        if isinstance(error, (ConfigurationError, SecurityPolicyError,
                              PermanentTransportError, ResponseValidationError)):
            return False
        return isinstance(error, self.retryable_exceptions)


@dataclass
class RetryOutcome:
    """The result of a retried request, successful or not.

    Carries every attempt, including failures: a run that succeeded on the
    fourth try after three 503s is operationally different from one that
    succeeded immediately.
    """

    response: Optional[HttpResponse]
    attempts: Tuple[RetrievalAttempt, ...]
    error: Optional[BaseException] = None

    @property
    def succeeded(self) -> bool:
        """True when a response was obtained."""
        return self.response is not None and self.error is None


def execute_with_retry(
    transport,
    request: HttpRequest,
    policy: RetryPolicy,
    clock: Callable[[], _dt.datetime] = _utc_now,
    sleeper: Callable[[float], None] = _no_sleep,
    random_source: Callable[[], float] = random.random,
) -> RetryOutcome:
    """Send ``request``, retrying within the policy's bounds.

    Returns a :class:`RetryOutcome` rather than raising, so the caller can
    record a failed retrieval alongside successful ones and still produce a
    complete manifest. The only exceptions that propagate are the ones that
    mean the run itself is unsound - configuration and security policy errors.

    Every attempt is recorded with the delay that preceded it, the status or
    error that ended it, any ``Retry-After`` the server sent, and why it was
    retried.
    """
    attempts: List[RetrievalAttempt] = []
    started = clock()
    delay_before = 0.0
    last_error: Optional[BaseException] = None
    last_status: Optional[int] = None

    for attempt_number in range(1, policy.max_attempts + 1):
        attempt_started = clock()
        elapsed = (attempt_started - started).total_seconds()
        if attempt_number > 1 and elapsed > policy.max_elapsed_seconds:
            attempts.append(RetrievalAttempt(
                attempt_number=attempt_number, started_at=attempt_started,
                status_code=last_status, error_code="MAX_ELAPSED_EXCEEDED",
                retry_reason="elapsed %.1fs exceeded the %.1fs budget"
                             % (elapsed, policy.max_elapsed_seconds),
                delay_before_seconds=delay_before))
            return RetryOutcome(
                response=None, attempts=tuple(attempts),
                error=RetryBudgetExhaustedError(
                    "retry budget exhausted for endpoint %r after %.1fs"
                    % (request.endpoint_id, elapsed),
                    attempts=len(attempts), status_code=last_status))

        try:
            response = transport.send(request)
        except (ConfigurationError, SecurityPolicyError):
            # The run is unsound. Retrying a refused host or a missing timeout
            # would only produce the same refusal more times.
            raise
        except IngestionError as exc:
            last_error = exc
            retryable = policy.should_retry_exception(exc)
            attempts.append(RetrievalAttempt(
                attempt_number=attempt_number, started_at=attempt_started,
                error_code=type(exc).__name__,
                retry_reason=(str(exc) if retryable
                              else "not retryable: %s" % type(exc).__name__),
                delay_before_seconds=delay_before))
            if not retryable or attempt_number >= policy.max_attempts:
                return RetryOutcome(
                    response=None, attempts=tuple(attempts),
                    error=(exc if not retryable else RetryBudgetExhaustedError(
                        "retry budget exhausted for endpoint %r after %d "
                        "attempt(s): %s" % (request.endpoint_id,
                                            attempt_number, exc),
                        attempts=attempt_number)))
            delay_before = _next_delay(policy, attempt_number, None,
                                       random_source)
            sleeper(delay_before)
            continue

        last_status = response.status_code
        retry_after = parse_retry_after(response.header("retry-after"),
                                        attempt_started)

        if 200 <= response.status_code < 300:
            attempts.append(RetrievalAttempt(
                attempt_number=attempt_number, started_at=attempt_started,
                status_code=response.status_code,
                delay_before_seconds=delay_before,
                retry_after_seconds=retry_after))
            return RetryOutcome(response=response, attempts=tuple(attempts))

        retryable = policy.should_retry_status(response.status_code)
        attempts.append(RetrievalAttempt(
            attempt_number=attempt_number, started_at=attempt_started,
            status_code=response.status_code,
            error_code="HTTP_%d" % response.status_code,
            retry_reason=("status %d is retryable" % response.status_code
                          if retryable
                          else "status %d is not retryable"
                               % response.status_code),
            delay_before_seconds=delay_before,
            retry_after_seconds=retry_after))

        if not retryable:
            return RetryOutcome(
                response=None, attempts=tuple(attempts),
                error=PermanentTransportError(
                    "endpoint %r returned HTTP %d, which is not retryable"
                    % (request.endpoint_id, response.status_code),
                    status_code=response.status_code))

        if attempt_number >= policy.max_attempts:
            return RetryOutcome(
                response=None, attempts=tuple(attempts),
                error=RetryBudgetExhaustedError(
                    "endpoint %r still failing with HTTP %d after %d attempt(s)"
                    % (request.endpoint_id, response.status_code, attempt_number),
                    attempts=attempt_number, status_code=response.status_code))

        delay_before = _next_delay(policy, attempt_number, retry_after,
                                   random_source)
        sleeper(delay_before)

    # Unreachable: the loop returns on every path.
    return RetryOutcome(  # pragma: no cover - defensive
        response=None, attempts=tuple(attempts),
        error=RetryBudgetExhaustedError(
            "retry loop ended without a result for endpoint %r"
            % request.endpoint_id, attempts=len(attempts)))


def _next_delay(policy: RetryPolicy, attempt_number: int,
                retry_after: Optional[float],
                random_source: Callable[[], float]) -> float:
    """Delay before the next attempt.

    A server-supplied ``Retry-After`` is honoured in preference to our own
    backoff - guessing is worse than listening - but it is clamped to
    ``max_delay_seconds`` so a server cannot park the run for an hour, and it
    is not jittered, because the server named a specific time.
    """
    if retry_after is not None:
        return min(retry_after, policy.max_delay_seconds)
    return policy.apply_jitter(policy.base_delay(attempt_number), random_source())
