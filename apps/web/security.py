"""CSRF verification, redirect safety, and the headers a page carries.

Three protections a browser needs that a JSON API does not, and one thing that
is deliberately absent: there is no session here, no cookie, no token minting
and no credential of any kind. WP-23 owns those. What WP-17 owns is the
*shape* of the protection - a port with a fail-closed default - so that WP-23
can supply the mechanism without a template or a route learning how it works.

**The CSRF verifier refuses by default, and that is the feature.** A form that
posted without verification would be safe only for as long as there were no
sessions to ride; the release that adds sessions would silently make every
existing form exploitable. Refusing now means the failure mode is a visibly
disabled button rather than an invisible hole waiting for a dependency.

**Redirects are allowlisted by route name, not by path.** A ``next``
parameter that carried a path would need a parser to decide whether
``//evil.example`` or ``/\\evil.example`` or ``https:/evil.example`` is
internal, and every open-redirect advisory ever written is about a parser that
got one of those wrong. Here the caller names a route; anything that is not a
declared route name is refused, and there is no path to parse.
"""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from typing import Mapping, Optional

from apps.web.routes import WEB_ROUTES_BY_NAME, web_route

__all__ = [
    "CSRF_FIELD_NAME",
    "CSRF_HEADER_NAME",
    "CsrfError",
    "CsrfVerifier",
    "PreAuthCsrfVerifier",
    "RedirectRefusedError",
    "SECURITY_HEADERS",
    "SESSION_COOKIE_ATTRIBUTES",
    "SessionBoundCsrfVerifier",
    "StaticTokenCsrfVerifier",
    "UnconfiguredCsrf",
    "safe_redirect",
    "security_headers",
    "session_cookie_header",
]

CSRF_FIELD_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"


class CsrfError(Exception):
    """A state-changing request was refused for want of verification."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class RedirectRefusedError(Exception):
    """A redirect target was not a declared internal route."""


class CsrfVerifier:
    """Port: decide whether one state-changing request may proceed.

    The token is opaque here on purpose. WP-23 may use a signed double-submit
    cookie, a per-session synchroniser token or something else; what this
    layer needs is that exactly one place decides, and that the place is
    replaceable.
    """

    configured: bool = False

    def verify(self, token: Optional[str]
               ) -> None:  # pragma: no cover - protocol
        raise NotImplementedError

    def issue(self) -> Optional[str]:  # pragma: no cover - protocol
        """The token a form should carry, or ``None`` when none can be."""
        return None


class UnconfiguredCsrf(CsrfVerifier):
    """The default. Refuses every state-changing request.

    It issues no token, so a form rendered against it has nothing to submit
    and is rendered as unavailable rather than as a control that will fail
    after the user has filled it in. It never inspects the token it was given:
    there is nothing here to check one against, and a verifier that returned
    *anything* when it had verified *nothing* is the failure this class exists
    to prevent.
    """

    configured = False

    def verify(self, token: Optional[str]) -> None:
        del token
        raise CsrfError(
            "CSRF_NOT_CONFIGURED",
            "no CSRF verifier is configured in this deployment, so no "
            "state-changing request is accepted")

    def issue(self) -> Optional[str]:
        return None


class SessionBoundCsrfVerifier(CsrfVerifier):
    """WP-23's real verifier, bound to one request's session.

    Constructed per request, holding that request's session binding and
    secret. This is why :class:`~apps.web.dependencies.WebProvider` gained a
    *factory* rather than keeping a verifier instance: a process-global
    verifier holding one session's key material would either verify every
    request against one session or need mutable state shared across
    concurrent requests, and both are worse than the fixture it replaced.

    The token is ``HMAC-SHA256(session_csrf_secret, session_id || bucket)``.
    A token minted for session A cannot verify against session B - not
    because a check compares two identifiers, but because the key differs and
    the MAC does not match. Rotating the session mints new key material in the
    same write, which is what makes "the previous token stops working"
    structural rather than a cleanup step somebody could omit.
    """

    configured = True

    def __init__(self, *, binding: str, secret: str,
                 clock=None, service=None) -> None:
        import datetime as _dt

        from pgx.security.csrf import SessionBoundCsrf

        if not binding or not secret:
            raise ValueError(
                "a session-bound verifier needs the session it is bound to; "
                "one without a binding would verify tokens for any session")
        self._binding = binding
        self._secret = secret
        self._service = service or SessionBoundCsrf()
        self._clock = clock or (
            lambda: _dt.datetime.now(_dt.timezone.utc))

    def verify(self, token: Optional[str]) -> None:
        from pgx.security.errors import CsrfFailure

        try:
            self._service.verify(token, binding=self._binding,
                                 secret=self._secret, now=self._clock())
        except CsrfFailure as error:
            raise CsrfError(error.code, "the request did not carry a valid "
                                        "session-bound token") from None

    def issue(self) -> Optional[str]:
        from pgx.security.errors import CsrfFailure

        try:
            return self._service.issue(binding=self._binding,
                                       secret=self._secret,
                                       now=self._clock())
        except CsrfFailure:  # pragma: no cover - defensive
            return None

    def __repr__(self) -> str:
        """Never prints the secret. A dataclass repr would."""
        return "<SessionBoundCsrfVerifier binding=%s>" % self._binding


class PreAuthCsrfVerifier(SessionBoundCsrfVerifier):
    """The login form's protection, bound to a host-scoped pre-auth cookie.

    Login is not exempt from CSRF, and treating it as exempt is a real
    vulnerability rather than a pedantic one: an attacker who can post to
    ``/login`` with their own credentials logs the victim into the attacker's
    account, and everything the victim then does happens in a session the
    attacker controls and can read.

    There is no session yet at that point, so the binding comes from a
    short-lived ``__Host-pgx_preauth`` cookie the server set when it rendered
    the form. Same construction, different key source, same refusal when it is
    absent - the form renders as unavailable rather than as a control that
    will fail after the operator has typed a password into it.
    """


class StaticTokenCsrfVerifier(CsrfVerifier):
    """A development-only verifier over one fixed token.

    Exists so the synthetic end-to-end flow can exercise a real submission
    path rather than routing around it. It is not a CSRF mechanism: a single
    fixed token shared by every request protects nothing once an attacker has
    seen one page. :class:`~apps.web.config.WebSettings` refuses to call a
    deployment CSRF-configured in production, so this can never be what a
    production form is protected by.

    The comparison is constant-time. The token is not worth protecting; a
    timing-variable comparison copied out of here into WP-23 would be.
    """

    configured = True

    def __init__(self, token: str) -> None:
        if not isinstance(token, str) or len(token) < 16:
            raise ValueError(
                "a development CSRF token is at least 16 characters, so that "
                "a fixture is never mistaken for a real defence")
        self._token = token

    def verify(self, token: Optional[str]) -> None:
        if not token or not hmac.compare_digest(self._token, token):
            raise CsrfError("CSRF_TOKEN_INVALID",
                            "the request did not carry a valid token")

    def issue(self) -> Optional[str]:
        return self._token


#: Sent on every page. Aimed at a server-rendered HTML application that loads
#: only its own assets and runs no third-party script.
SECURITY_HEADERS: Mapping[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    # Everything from this origin, nothing from anywhere else, and no inline
    # script at all. The interface ships one local stylesheet and one local
    # script and needs nothing further; a policy that allowed 'unsafe-inline'
    # to save a style attribute would give up the protection the policy is for.
    "Content-Security-Policy": (
        "default-src 'none'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "form-action 'self'; "
        "base-uri 'none'; "
        "frame-ancestors 'none'"),
    # No page here needs a camera, a microphone, a location or a payment
    # handler, so none is granted.
    "Permissions-Policy": (
        "accelerometer=(), autoplay=(), camera=(), display-capture=(), "
        "geolocation=(), gyroscope=(), microphone=(), payment=(), "
        "usb=()"),
    "Cache-Control": "no-store",
}


def security_headers() -> Mapping[str, str]:
    """A fresh copy of the header set, so a caller cannot mutate the table."""
    return dict(SECURITY_HEADERS)


#: The attributes every session cookie carries, and none of them optional.
#:
#: ``__Host-`` is not decoration: the browser itself refuses a ``__Host-``
#: cookie that is not Secure, is not ``Path=/``, or carries a ``Domain``. So a
#: misconfiguration that tried to widen the cookie's scope makes the cookie
#: stop being accepted rather than silently broadening it - the failure is
#: loud instead of invisible.
SESSION_COOKIE_ATTRIBUTES: Mapping[str, object] = {
    "secure": True,
    "httponly": True,
    "samesite": "strict",
    "path": "/",
    "domain": None,
}


def session_cookie_header(name: str, value: str, *,
                          max_age: Optional[int] = None) -> str:
    """Render one ``Set-Cookie`` value with the mandatory attributes.

    Written here rather than at each call site so that "the logout cookie
    forgot HttpOnly" is not a thing that can happen. ``max_age=0`` with an
    empty value is the clearing form.
    """
    if not name.startswith("__Host-"):
        raise ValueError(
            "a session cookie uses the __Host- prefix, which the browser "
            "enforces as Secure + Path=/ + no Domain")
    parts = ["%s=%s" % (name, value), "Path=/", "SameSite=Strict",
             "Secure", "HttpOnly"]
    if max_age is not None:
        parts.append("Max-Age=%d" % int(max_age))
    return "; ".join(parts)


def safe_redirect(route_name: Optional[str], *,
                  default: str = "web.home", **values: object) -> str:
    """Resolve a redirect target from a declared route name.

    Args:
        route_name: the name a form or query supplied, or ``None``.
        default: the route to use when nothing was supplied.
        **values: path parameter values for the resolved route.

    Raises:
        RedirectRefusedError: the name is not a declared web route. Refused
            rather than falling back to the default, because a request
            carrying an unknown target is a request somebody constructed, and
            quietly sending them somewhere else hides that.
    """
    name = route_name or default
    if name not in WEB_ROUTES_BY_NAME:
        raise RedirectRefusedError(
            "%r is not a declared web route; a redirect target is a route "
            "name, never a path" % name)
    return web_route(name).url(**values)
