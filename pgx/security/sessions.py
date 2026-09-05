# -*- coding: utf-8 -*-
"""Opaque server-side sessions (WP-23).

A session here is a random value the server issued and a row the server owns.
It is not a JWT, not a signed cookie and not anything the client can construct
or inspect: the browser holds an opaque string, and every fact about the
session - who it belongs to, when it expires, whether it was revoked - is read
from the server on each request.

Three properties are structural rather than procedural.

**The raw token exists in exactly two places and neither is storage.** It is
returned once by :func:`new_session_token`, placed in a ``Set-Cookie`` header,
and then forgotten. What the store holds is ``sha256(token)``. A database dump
therefore contains nothing that can be replayed, which is the difference
between a leaked backup and a compromised fleet.
:class:`SessionRecord` has no field for the raw token, so a caller cannot
accidentally persist one, and its repr prints the digest prefix rather than
anything usable.

**Expiry is a boundary, not a duration.** ``now >= expires_at`` is expired.
Written once here and used everywhere, because "expired" implemented twice
eventually becomes ``>`` in one place and ``>=`` in the other, and the session
that lives one extra second is the one nobody can reproduce.

**Both clocks run.** Idle expiry moves forward as the session is used;
absolute expiry does not move at all. A session that is touched every four
minutes forever is exactly the session an absolute bound exists to end.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import secrets
from dataclasses import dataclass, replace
from typing import Optional, Tuple

from pgx.security.errors import SessionInvalid
from pgx.security.vocabulary import SessionRevocationReason

__all__ = [
    "DEFAULT_ABSOLUTE_SECONDS",
    "DEFAULT_IDLE_SECONDS",
    "SESSION_TOKEN_BYTES",
    "SessionPolicy",
    "SessionRecord",
    "new_session_token",
    "token_digest",
]

#: 32 bytes = 256 bits, the floor the work package names. ``token_urlsafe``
#: produces 43 characters from this, all cookie-safe.
SESSION_TOKEN_BYTES = 32

#: Idle: how long an unused session survives. Absolute: how long any session
#: survives however heavily used. The absolute bound is what makes a stolen
#: cookie a finite problem.
DEFAULT_IDLE_SECONDS = 30 * 60
DEFAULT_ABSOLUTE_SECONDS = 12 * 60 * 60


def new_session_token() -> str:
    """A fresh opaque token. Returned once; never stored, logged or audited."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def token_digest(token: str) -> str:
    """The one-way value the store holds.

    Plain SHA-256 rather than a password KDF, deliberately. The input is 256
    bits of ``secrets`` output, so there is no dictionary to attack and no
    entropy to stretch; the cost of a KDF here would be paid on *every
    authenticated request* and would buy nothing.
    """
    if not isinstance(token, str) or not token:
        raise SessionInvalid("no session token was presented",
                             code="SESSION_INVALID")
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SessionPolicy:
    """How long sessions live, and the cookie attributes they demand."""

    idle_seconds: int = DEFAULT_IDLE_SECONDS
    absolute_seconds: int = DEFAULT_ABSOLUTE_SECONDS
    cookie_secure: bool = True
    cookie_http_only: bool = True
    cookie_same_site: str = "Strict"
    cookie_path: str = "/"

    def __post_init__(self) -> None:
        if self.idle_seconds < 60 or self.idle_seconds > 24 * 3600:
            raise ValueError("idle expiry is between one minute and a day")
        if self.absolute_seconds < self.idle_seconds:
            raise ValueError(
                "an absolute bound below the idle bound would make the idle "
                "bound unreachable and the policy misleading")
        if self.absolute_seconds > 7 * 24 * 3600:
            raise ValueError("an absolute session bound is at most a week")
        # These three are not configurable downward. A deployment that could
        # turn off Secure or HttpOnly by configuration is a deployment where
        # one environment variable removes the protection entirely, and the
        # variable will eventually be set by someone testing over plain HTTP.
        if not self.cookie_secure or not self.cookie_http_only:
            raise ValueError(
                "session cookies are always Secure and HttpOnly; a "
                "configuration that could relax either would be relaxed")
        if self.cookie_same_site not in ("Strict", "Lax"):
            raise ValueError("SameSite is Strict or Lax, never None")
        if self.cookie_path != "/":
            raise ValueError(
                "the __Host- cookie prefix requires Path=/ and no Domain")

    def to_json(self) -> dict:
        return {"idle_seconds": self.idle_seconds,
                "absolute_seconds": self.absolute_seconds,
                "cookie_secure": self.cookie_secure,
                "cookie_http_only": self.cookie_http_only,
                "cookie_same_site": self.cookie_same_site,
                "cookie_path": self.cookie_path}


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """One server-side session. Holds a digest; never a token.

    ``csrf_secret`` is per-session material used to derive that session's CSRF
    tokens. It lives here rather than in a global setting so that rotating the
    session rotates the CSRF binding in the same write - which is what makes
    "a token for one session must not work for another" true by construction
    rather than by a check somebody could forget.
    """

    session_id: str
    user_id: str
    role: str
    token_digest: str
    csrf_secret: str
    auth_generation: int
    created_at: _dt.datetime
    last_seen_at: _dt.datetime
    idle_expires_at: _dt.datetime
    absolute_expires_at: _dt.datetime
    revoked_at: Optional[_dt.datetime] = None
    revocation_reason: Optional[SessionRevocationReason] = None

    def __post_init__(self) -> None:
        if not self.token_digest.startswith("sha256:"):
            raise SessionInvalid(
                "a session row stores a one-way token digest, never a token",
                code="SESSION_INVALID")
        if self.absolute_expires_at < self.idle_expires_at:
            raise SessionInvalid(
                "the absolute bound precedes the idle bound, which would make "
                "the idle bound unreachable", code="SESSION_INVALID")
        if (self.revoked_at is None) != (self.revocation_reason is None):
            raise SessionInvalid(
                "a revoked session names why, and an unrevoked one names "
                "nothing", code="SESSION_INVALID")

    @property
    def expires_at(self) -> _dt.datetime:
        """The earlier of the two bounds. One value, one comparison."""
        return min(self.idle_expires_at, self.absolute_expires_at)

    def is_expired_at(self, now: _dt.datetime) -> bool:
        """``now >= expires_at``. The boundary is expired, not still valid."""
        return now >= self.expires_at

    def expiry_reason_at(self, now: _dt.datetime
                         ) -> Optional[SessionRevocationReason]:
        """Which bound ended it, for the audit row. ``None`` if still live."""
        if now >= self.absolute_expires_at:
            return SessionRevocationReason.ABSOLUTE_EXPIRED
        if now >= self.idle_expires_at:
            return SessionRevocationReason.IDLE_EXPIRED
        return None

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def touched(self, now: _dt.datetime,
                policy: SessionPolicy) -> "SessionRecord":
        """Slide the idle bound forward. The absolute bound never moves."""
        return replace(
            self, last_seen_at=now,
            idle_expires_at=min(
                now + _dt.timedelta(seconds=policy.idle_seconds),
                self.absolute_expires_at))

    def revoked(self, now: _dt.datetime,
                reason: SessionRevocationReason) -> "SessionRecord":
        if self.is_revoked:
            return self
        return replace(self, revoked_at=now, revocation_reason=reason)

    def session_reference(self) -> str:
        """A stable, non-secret handle for audit rows.

        The session id, not the token and not the token digest. A digest in an
        audit row would be a verifier for the cookie: anyone holding both the
        row and a captured token could confirm they matched.
        """
        return self.session_id

    def safe_projection(self) -> dict:
        """What may be shown or published. No token, no digest, no secret."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "role": self.role,
            "auth_generation": self.auth_generation,
            "created_at": _iso(self.created_at),
            "last_seen_at": _iso(self.last_seen_at),
            "idle_expires_at": _iso(self.idle_expires_at),
            "absolute_expires_at": _iso(self.absolute_expires_at),
            "revoked": self.is_revoked,
            "revocation_reason": (None if self.revocation_reason is None
                                  else self.revocation_reason.value),
        }

    def __repr__(self) -> str:
        """No digest, no CSRF secret. A dataclass repr would print both."""
        return ("<SessionRecord id=%s user=%s role=%s revoked=%s>"
                % (self.session_id, self.user_id, self.role, self.is_revoked))


def matches_token(record: SessionRecord, token: str) -> bool:
    """Constant-time comparison of a presented token against a stored digest."""
    try:
        presented = token_digest(token)
    except SessionInvalid:
        return False
    return hmac.compare_digest(record.token_digest, presented)


def build_session(*, session_id: str, user_id: str, role: str, token: str,
                  csrf_secret: str, auth_generation: int,
                  now: _dt.datetime, policy: SessionPolicy) -> SessionRecord:
    """Construct a session from a token, storing only its digest."""
    return SessionRecord(
        session_id=session_id, user_id=user_id, role=role,
        token_digest=token_digest(token), csrf_secret=csrf_secret,
        auth_generation=auth_generation, created_at=now, last_seen_at=now,
        idle_expires_at=now + _dt.timedelta(seconds=policy.idle_seconds),
        absolute_expires_at=now + _dt.timedelta(
            seconds=policy.absolute_seconds))


def _iso(value: Optional[_dt.datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.astimezone(_dt.timezone.utc).isoformat().replace(
        "+00:00", "Z")
