# -*- coding: utf-8 -*-
"""Declared rate-limit policies and a fail-closed limiter (WP-23).

Policies are declared here, before any result is observed, for the same reason
WP-21 declares metrics before any benchmark runs: a limit chosen after seeing
traffic is a limit chosen to permit the traffic.

Three properties carry the safety content.

**Failure is denial.** If the backend cannot answer - the table is gone, the
connection dropped, the query timed out - :class:`RateLimiter` raises rather
than allowing the request. Login and governed mutations must not proceed
unmetered because the meter broke, and the alternative ("allow on error") is
the design that turns a database blip into an unlimited password-guessing
window.

**A limiter can only deny.** Nothing in this module returns "allowed" in a way
that a caller could mistake for an authorisation. ``check`` either returns
``None`` or raises; there is no truthy value to accidentally treat as a
permission, and no code path where consulting the limiter turns a refused
action into a permitted one.

**Keys are digests, never identities.** A login limit is keyed by
``sha256(username)`` and ``sha256(origin_key)``. The stored row therefore
names no user and no address, so a rate-limit table that leaks tells an
attacker how often *some* key was tried and nothing about whom. Unknown and
known usernames take the identical path, so the limiter is not an enumeration
oracle either.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple

from pgx.security.errors import RateLimited

__all__ = [
    "POLICIES",
    "POLICY_IDS",
    "RATE_LIMIT_POLICY_VERSION",
    "InMemoryRateLimitStore",
    "RateLimitPolicy",
    "RateLimitStore",
    "RateLimiter",
    "policy_document",
    "scope_key",
]

RATE_LIMIT_POLICY_VERSION = "pgx-wp23-rate-limit-policy/1"


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    """One declared limit. Fixed window, stable id.

    Fixed windows rather than sliding ones, deliberately: a sliding window
    needs per-request history, which is a table of timestamps keyed by the
    thing being limited - and that table is a far better log of who tried what
    than the audit trail is allowed to be.
    """

    policy_id: str
    title: str
    scope: str
    limit: int
    window_seconds: int
    retry_after_seconds: int
    rationale: str

    def __post_init__(self) -> None:
        if self.limit < 1 or self.window_seconds < 1:
            raise ValueError("a policy permits at least one call per window")
        if self.retry_after_seconds < 1 or \
                self.retry_after_seconds > self.window_seconds:
            raise ValueError(
                "Retry-After is bounded by the window; a larger value would "
                "tell a client to wait longer than the limit lasts")

    def to_json(self) -> dict:
        return {"policy_id": self.policy_id, "title": self.title,
                "scope": self.scope, "limit": self.limit,
                "window_seconds": self.window_seconds,
                "retry_after_seconds": self.retry_after_seconds,
                "rationale": self.rationale}


POLICIES: Tuple[RateLimitPolicy, ...] = (
    RateLimitPolicy(
        policy_id="LOGIN_PER_USERNAME", title="Login attempts per username",
        scope="username_digest", limit=5, window_seconds=300,
        retry_after_seconds=60,
        rationale="Slows online password guessing against one account. Runs "
                  "before the user is looked up, so an unknown username is "
                  "limited exactly like a known one and the limiter cannot "
                  "be used to enumerate accounts."),
    RateLimitPolicy(
        policy_id="LOGIN_PER_ORIGIN", title="Login attempts per origin",
        scope="origin_digest", limit=20, window_seconds=300,
        retry_after_seconds=60,
        rationale="Slows guessing spread across many usernames from one "
                  "source, which the per-username limit alone does not see."),
    RateLimitPolicy(
        policy_id="ASSESSMENT_PER_ACTOR", title="Assessments per actor",
        scope="actor_digest", limit=60, window_seconds=300,
        retry_after_seconds=30,
        rationale="An assessment pins a release and writes a persisted row. "
                  "Bounded per actor so one authenticated client cannot fill "
                  "the assessment table."),
    RateLimitPolicy(
        policy_id="EXPERT_REVIEW_MUTATION_PER_ACTOR",
        title="Expert-review mutations per actor",
        scope="actor_digest", limit=30, window_seconds=300,
        retry_after_seconds=30,
        rationale="Every review mutation appends immutable records that "
                  "cannot be removed. A loop here is a permanent one."),
    RateLimitPolicy(
        policy_id="ADMIN_MUTATION_PER_ACTOR",
        title="Administrative mutations per actor",
        scope="actor_digest", limit=30, window_seconds=300,
        retry_after_seconds=30,
        rationale="Release activation, user administration and rule "
                  "governance each move governed state and append audit "
                  "rows."),
)

POLICY_IDS: Tuple[str, ...] = tuple(item.policy_id for item in POLICIES)

_BY_ID: Mapping[str, RateLimitPolicy] = {item.policy_id: item
                                         for item in POLICIES}


def scope_key(value: str) -> str:
    """The stored key: a digest, never the identity itself.

    Applied to usernames, actor identifiers and network-origin keys alike. A
    rate-limit table that leaks then reveals that *some* key was tried n
    times, which is close to useless to an attacker and exactly enough for
    the limiter.
    """
    return "sha256:" + hashlib.sha256(
        ("pgx-wp23-rate-limit|" + str(value)).encode("utf-8")).hexdigest()


class RateLimitStore:
    """Port: count one hit in one window and report the running total.

    Deliberately one method. A store with separate ``read`` and ``write``
    invites a caller to read, decide, and write - which is a race whose losing
    side is an unmetered attempt.
    """

    def hit(self, *, policy_id: str, key: str, window_start: _dt.datetime
            ) -> int:  # pragma: no cover - protocol
        raise NotImplementedError


class InMemoryRateLimitStore(RateLimitStore):
    """The test adapter. Deterministic, and able to fail on demand.

    ``fail_next`` exists so the fail-closed path is exercised rather than
    assumed: a limiter that is *said* to fail closed and never tested doing so
    is a limiter nobody has run in the state that matters.
    """

    def __init__(self) -> None:
        self._counts: Dict[Tuple[str, str, str], int] = {}
        self.fail_next = False

    def hit(self, *, policy_id: str, key: str,
            window_start: _dt.datetime) -> int:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("the rate-limit backend is unavailable")
        bucket = (policy_id, key, window_start.isoformat())
        self._counts[bucket] = self._counts.get(bucket, 0) + 1
        return self._counts[bucket]


class RateLimiter:
    """Apply a declared policy, and deny when it cannot be applied.

    The clock is injected so window boundaries and resets are tested rather
    than waited for.
    """

    def __init__(self, store: Optional[RateLimitStore] = None,
                 clock=None) -> None:
        self._store = store
        self._clock = clock or (
            lambda: _dt.datetime.now(_dt.timezone.utc))

    @property
    def configured(self) -> bool:
        return self._store is not None

    def check(self, policy_id: str, identity: str) -> None:
        """Count this attempt; raise if the policy is exceeded or unknown.

        Returns ``None`` on success. There is no truthy return value, so no
        call site can treat "the limiter said fine" as an authorisation.
        """
        policy = _BY_ID.get(policy_id)
        if policy is None:
            raise KeyError(
                "%r is not a declared rate-limit policy; an undeclared policy "
                "would silently not limit anything" % policy_id)
        if self._store is None:
            # Fail closed. A deployment with no limiter must not run an
            # unmetered login path while reporting that rate limiting is
            # implemented.
            raise RateLimited(
                "no rate-limit backend is composed",
                policy_id=policy.policy_id,
                retry_after_seconds=policy.retry_after_seconds,
                code="RATE_LIMIT_UNAVAILABLE")
        now = self._clock()
        window_start = _window_start(now, policy.window_seconds)
        try:
            count = self._store.hit(policy_id=policy.policy_id,
                                    key=scope_key(identity),
                                    window_start=window_start)
        except Exception as error:  # noqa: BLE001 - any failure denies
            raise RateLimited(
                "the rate-limit backend could not answer",
                policy_id=policy.policy_id,
                retry_after_seconds=policy.retry_after_seconds,
                code="RATE_LIMIT_UNAVAILABLE") from error
        if count > policy.limit:
            raise RateLimited(
                "the rate-limit policy was exceeded",
                policy_id=policy.policy_id,
                retry_after_seconds=policy.retry_after_seconds)


def _window_start(now: _dt.datetime, window_seconds: int) -> _dt.datetime:
    epoch = int(now.timestamp())
    return _dt.datetime.fromtimestamp(
        epoch - (epoch % window_seconds), tz=_dt.timezone.utc)


def policy_document() -> dict:
    """The published policy table."""
    return {
        "rate_limit_policy_version": RATE_LIMIT_POLICY_VERSION,
        "policy_count": len(POLICIES),
        "policies": [item.to_json() for item in POLICIES],
        "window_semantics": (
            "Fixed windows aligned to the epoch: a window starts at "
            "floor(now / window_seconds) * window_seconds. The count is "
            "incremented before the decision, so the attempt that exceeds "
            "the limit is itself counted."),
        "key_semantics": (
            "Every key is sha256('pgx-wp23-rate-limit|' + identity). No "
            "username, actor identifier or network address is stored, so a "
            "leaked rate-limit table names nobody."),
        "failure_semantics": (
            "A backend that cannot answer denies. Login and governed "
            "mutations fail closed rather than running unmetered, and the "
            "refusal carries RATE_LIMIT_UNAVAILABLE so an operator can tell "
            "a broken limiter from a busy client."),
        "proxy_header_policy": (
            "X-Forwarded-For is not trusted and is not read. Until a "
            "trusted-proxy policy is explicitly configured, the origin key "
            "is whatever the server itself observed; a spoofable header used "
            "as a limit key is a limit an attacker sets."),
        "no_performance_claim": (
            "This document declares limits. It reports no throughput, "
            "latency or load result: WP-24 owns those."),
    }
