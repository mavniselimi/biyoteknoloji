# -*- coding: utf-8 -*-
"""Scripted transport, clock and sleeper (WP-04).

The fake transport is a script, not a mock: each entry says what the next call
returns, and the transport records every request it was given. That makes two
things assertable that a mock would obscure - *how many* calls were made (zero
is the whole claim of cache-only mode) and *exactly which* requests they were.

The sleeper records delays instead of sleeping. The suite therefore exercises
real backoff arithmetic and finishes in milliseconds.
"""

from __future__ import annotations

import datetime as _dt
import json
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from pgx.ingestion.common.errors import (
    PermanentTransportError, TransientTransportError,
)
from pgx.ingestion.common.models import HttpRequest, HttpResponse

EPOCH = _dt.datetime(2026, 8, 30, 12, 0, 0, tzinfo=_dt.timezone.utc)


def json_response(payload: Any, status_code: int = 200,
                  headers: Optional[Mapping[str, str]] = None) -> HttpResponse:
    """A JSON response with the exact bytes ``json.dumps`` produces."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    merged = {"Content-Type": "application/json"}
    merged.update(headers or {})
    return HttpResponse(status_code=status_code, body=body, headers=merged,
                        final_url="https://api.clinpgx.org/v1/test")


def raw_response(body: bytes, status_code: int = 200,
                 content_type: str = "application/json",
                 headers: Optional[Mapping[str, str]] = None) -> HttpResponse:
    """A response carrying exactly these bytes."""
    merged = {"Content-Type": content_type}
    merged.update(headers or {})
    return HttpResponse(status_code=status_code, body=body, headers=merged,
                        final_url="https://api.clinpgx.org/v1/test")


def data_page(records: Sequence[Any], **extra: Any) -> HttpResponse:
    """A ``{"data": [...]}`` page, the shape the ClinPGx catalog declares."""
    payload: Dict[str, Any] = {"data": list(records)}
    payload.update(extra)
    return json_response(payload)


class ScriptedTransport:
    """Returns queued responses in order, recording every request.

    A queued entry may be an :class:`HttpResponse` (returned), an exception
    (raised), or a callable (invoked with the request). Running past the end of
    the script is an error rather than a repeat: a test that made more calls
    than it scripted has found something, and silently repeating the last
    response would hide it.
    """

    def __init__(self, script: Optional[Sequence[Any]] = None) -> None:
        self.script: List[Any] = list(script or [])
        self.requests: List[HttpRequest] = []

    @property
    def call_count(self) -> int:
        """How many times ``send`` was called. Zero is a real assertion."""
        return len(self.requests)

    def queue(self, *items: Any) -> "ScriptedTransport":
        """Append entries to the script."""
        self.script.extend(items)
        return self

    def send(self, request: HttpRequest) -> HttpResponse:
        """Return the next scripted result for this request."""
        self.requests.append(request)
        if not self.script:
            raise AssertionError(
                "ScriptedTransport ran past the end of its script on call %d "
                "for endpoint %r; the code under test made more requests than "
                "the test expected" % (self.call_count, request.endpoint_id))
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item(request)
        return item


class ForbiddenTransport:
    """Fails loudly if anything calls it.

    Used where the claim is that no request happens at all. A transport that
    returned a canned response instead would let a cache-only regression pass.
    """

    def __init__(self) -> None:
        self.call_count = 0

    def send(self, request: HttpRequest) -> HttpResponse:
        self.call_count += 1
        raise AssertionError(
            "the transport was called for endpoint %r, but this run must make "
            "no requests" % request.endpoint_id)


class StepClock:
    """Advances one second per call. Deterministic and ordered."""

    def __init__(self, start: _dt.datetime = EPOCH, step_seconds: float = 1.0) -> None:
        self._current = start
        self._step = _dt.timedelta(seconds=step_seconds)
        self.calls = 0

    def __call__(self) -> _dt.datetime:
        value = self._current
        self._current = self._current + self._step
        self.calls += 1
        return value


class FrozenClock:
    """Never advances. For asserting an elapsed budget is not tripped."""

    def __init__(self, at: _dt.datetime = EPOCH) -> None:
        self._at = at

    def __call__(self) -> _dt.datetime:
        return self._at


class RecordingSleeper:
    """Records requested delays instead of sleeping."""

    def __init__(self) -> None:
        self.delays: List[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)

    @property
    def total(self) -> float:
        """Total delay the code asked for, in seconds."""
        return sum(self.delays)


def fixed_random(value: float = 0.5) -> Callable[[], float]:
    """A deterministic stand-in for ``random.random``."""
    return lambda: value
