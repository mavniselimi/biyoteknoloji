# -*- coding: utf-8 -*-
"""Session-bound CSRF tokens (WP-23).

WP-17 shipped a port with two implementations: one that refuses everything and
one development fixture holding a single process-global token. The fixture was
honest about being a fixture - a fixed token shared by every request protects
nothing once an attacker has seen one page - and this module replaces it with
something that does.

**A token is bound to a session, cryptographically.** The token is
``HMAC-SHA256(session_csrf_secret, session_id || issued_bucket)``, and the
secret lives on the session row. So a token minted for session A cannot verify
against session B: not because a check compares session ids, but because the
key is different and the MAC does not match. Rotating the session on login
mints a new secret, which is what makes "the previous token stops working"
structural rather than a cleanup step somebody could omit.

**Login is not exempt.** A login form with no CSRF protection lets an attacker
log a victim into the attacker's account, and everything the victim then does
happens in a session the attacker controls. There is no session yet at that
point, so the pre-auth token is bound to a short-lived host-scoped cookie
instead - the same construction with a different key source, and the same
refusal when it is absent.

**Verification is constant-time and refuses first.** ``hmac.compare_digest``
throughout, and the CSRF check runs before the governed action reads anything,
so a request that fails it has not touched the store.
"""

from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Optional

from pgx.security.errors import CsrfFailure

__all__ = [
    "CSRF_TOKEN_VERSION",
    "DEFAULT_CSRF_LIFETIME_SECONDS",
    "CsrfService",
    "SessionBoundCsrf",
    "new_csrf_secret",
]

CSRF_TOKEN_VERSION = "1"

#: How long one minted token stays acceptable. Short enough that a token
#: scraped from a stale page is useless, long enough that a form left open
#: while somebody reads the page still submits.
DEFAULT_CSRF_LIFETIME_SECONDS = 3600

_BUCKET_SECONDS = 60


def new_csrf_secret() -> str:
    """Per-session CSRF key material. Never leaves the server."""
    return secrets.token_urlsafe(32)


def _bucket(now: _dt.datetime) -> int:
    return int(now.timestamp()) // _BUCKET_SECONDS


def _mac(secret: str, binding: str, bucket: int) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        ("%s|%s|%d" % (CSRF_TOKEN_VERSION, binding, bucket)).encode("utf-8"),
        hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


class CsrfService:
    """Port: mint and verify a token bound to one request's session."""

    configured: bool = False

    def issue(self, *, binding: str, secret: str,
              now: _dt.datetime) -> str:  # pragma: no cover - protocol
        raise NotImplementedError

    def verify(self, token: Optional[str], *, binding: str, secret: str,
               now: _dt.datetime) -> None:  # pragma: no cover - protocol
        raise NotImplementedError


@dataclass(frozen=True)
class SessionBoundCsrf(CsrfService):
    """The real implementation. One key per session, one MAC per token.

    ``lifetime_seconds`` is enforced by accepting a bounded window of buckets
    rather than by embedding a timestamp the client could edit. A token
    carries no readable expiry: it either verifies against one of the accepted
    buckets or it does not.
    """

    lifetime_seconds: int = DEFAULT_CSRF_LIFETIME_SECONDS
    configured: bool = True

    def __post_init__(self) -> None:
        if self.lifetime_seconds < _BUCKET_SECONDS or \
                self.lifetime_seconds > 24 * 3600:
            raise ValueError(
                "a CSRF token lifetime is between one minute and a day")

    def issue(self, *, binding: str, secret: str, now: _dt.datetime) -> str:
        """The token a form carries. Contains no session id and no secret.

        The binding value is *mixed into the MAC*, not embedded in the token,
        so the rendered HTML never carries a session identifier. That matters:
        a page cached, screenshotted or pasted into a bug report would
        otherwise hand over the session's name.
        """
        if not secret:
            raise CsrfFailure("no session CSRF secret is available",
                              code="CSRF_NOT_CONFIGURED")
        return "%s.%s" % (CSRF_TOKEN_VERSION, _mac(secret, binding,
                                                   _bucket(now)))

    def verify(self, token: Optional[str], *, binding: str, secret: str,
               now: _dt.datetime) -> None:
        """Refuse unless the token verifies against this session's key.

        Missing, malformed, expired and mismatched all raise the same error
        with the same code. A caller that could tell "expired" from "wrong
        session" could probe the binding.
        """
        if not secret:
            raise CsrfFailure("no session CSRF secret is available",
                              code="CSRF_NOT_CONFIGURED")
        if not token or not isinstance(token, str):
            raise CsrfFailure("the request carried no CSRF token")
        version, _, mac = token.partition(".")
        if version != CSRF_TOKEN_VERSION or not mac:
            raise CsrfFailure("the CSRF token is malformed")
        current = _bucket(now)
        oldest = current - max(1, self.lifetime_seconds // _BUCKET_SECONDS)
        # Every candidate is compared, and the loop does not break early on a
        # match: an early exit would make the number of comparisons depend on
        # which bucket matched, which is a (small) timing signal about when
        # the token was minted.
        matched = False
        for bucket in range(oldest, current + 1):
            if hmac.compare_digest(_mac(secret, binding, bucket), mac):
                matched = True
        if not matched:
            raise CsrfFailure(
                "the CSRF token did not verify against this session")


class UnconfiguredCsrfService(CsrfService):
    """The default. Mints nothing and accepts nothing.

    A deployment with no session store has no per-session secret, so there is
    nothing to bind a token to. Rendering a form against this yields a control
    with no token, which the page renders as unavailable rather than as a
    button that fails after the operator has filled the form in.
    """

    configured = False

    def issue(self, *, binding: str, secret: str, now: _dt.datetime) -> str:
        del binding, secret, now
        raise CsrfFailure(
            "no CSRF service is composed in this deployment",
            code="CSRF_NOT_CONFIGURED")

    def verify(self, token: Optional[str], *, binding: str, secret: str,
               now: _dt.datetime) -> None:
        del token, binding, secret, now
        raise CsrfFailure(
            "no CSRF service is composed in this deployment",
            code="CSRF_NOT_CONFIGURED")
