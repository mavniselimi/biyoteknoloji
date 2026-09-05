# -*- coding: utf-8 -*-
"""Transport protocol, request keys, and a stdlib production transport (WP-04).

Standard library only - the production transport uses ``urllib``, so acquiring
data adds no dependency to a project that already cannot reach a package index.

Three things live here.

**The transport protocol.** One method: request in, response out, typed errors.
Everything above it - retry, cache, pagination, the whole ClinPGx adapter - is
written against this protocol, which is why the entire acquisition path can be
tested with a scripted fake and no socket.

**The request key.** A SHA-256 over a canonical description of *what was asked
for*. Two properties make it useful, and both are enforced rather than assumed:
the same semantic request always produces the same key regardless of query
order, and **no credential can ever reach it**. The second matters because the
key is the cache filename and appears in every manifest; a key derived from an
Authorization header would write the token to disk.

**Transport safety policy.** HTTPS only, an explicit host allowlist, redirects
refused across hosts, a mandatory bounded timeout, and a response size limit.
Credentials are added at send time from injected configuration and never appear
in an :class:`~pgx.ingestion.common.models.HttpRequest`, so they cannot leak
into a key, a cache entry, a manifest, or a log line.

Importing this module opens no connection.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Protocol, Tuple, runtime_checkable
from urllib.parse import urlencode, urlsplit

from pgx.ingestion.common.errors import (
    ConfigurationError, PermanentTransportError, ResponseTooLargeError,
    SecurityPolicyError, TransientTransportError,
)
from pgx.ingestion.common.models import HttpRequest, HttpResponse, RateLimitInfo

__all__ = [
    "CREDENTIAL_HEADER_NAMES",
    "DEFAULT_MAX_RESPONSE_BYTES",
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_TIMEOUT_SECONDS",
    "REQUEST_KEY_VERSION",
    "HttpTransport",
    "TransportPolicy",
    "UrllibTransport",
    "parse_rate_limit",
    "parse_retry_after",
    "request_key",
]

#: Part of the hashed payload. Bumping it deliberately invalidates every cached
#: entry, which is what you want when the meaning of a key changes.
REQUEST_KEY_VERSION = "pgx-request-key/1"

DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 120.0

#: 64 MiB. An unbounded read is a denial-of-service against ourselves.
DEFAULT_MAX_RESPONSE_BYTES = 64 * 1024 * 1024

#: Headers that carry credentials. Never hashed, never cached, never logged,
#: never placed on an HttpRequest - the transport adds them at send time.
CREDENTIAL_HEADER_NAMES = frozenset({
    "authorization", "proxy-authorization", "cookie", "set-cookie",
    "x-api-key", "api-key", "x-auth-token", "authentication",
})

#: Headers that change the *meaning* of a request and therefore belong in its
#: key. ``User-Agent`` is deliberately absent: it varies between environments
#: and identifies the client, not the question being asked.
_SEMANTIC_HEADER_NAMES = frozenset({"accept", "accept-language"})


@runtime_checkable
class HttpTransport(Protocol):
    """The one thing the acquisition path needs from the network.

    Implementations raise :class:`TransientTransportError` for conditions worth
    retrying and :class:`PermanentTransportError` for conditions that are not.
    Returning a 4xx/5xx response rather than raising is also permitted; the
    retry layer classifies by status code either way.
    """

    def send(self, request: HttpRequest) -> HttpResponse:
        """Perform one request. No retry, no caching, no pagination."""


def _canonical_query(query: Tuple[Tuple[str, str], ...]) -> list:
    """Sorted query pairs, so ordering cannot change the key."""
    return sorted([list(pair) for pair in query])


def _semantic_headers(headers: Mapping[str, str]) -> dict:
    """Only headers that change what is being asked for.

    A credential header reaching this function would be a bug upstream; it is
    filtered here as well, because the cost of the redundancy is nothing and
    the cost of a leak is a token on disk.
    """
    return {
        name.lower(): str(value)
        for name, value in headers.items()
        if name.lower() in _SEMANTIC_HEADER_NAMES
        and name.lower() not in CREDENTIAL_HEADER_NAMES
    }


def request_key(request: HttpRequest) -> str:
    """Return the deterministic ``sha256:`` key identifying this request.

    Included: method, scheme, host, path, sorted query, endpoint ID, the
    expected response shape version, and semantic headers.

    Excluded, deliberately: credentials of any kind, ``User-Agent``, the wall
    clock, the cache or output directory, and the retry attempt number. Every
    one of those would make the same question produce a different key, which
    would defeat the cache; the credential exclusions would additionally write
    secrets into filenames.
    """
    parts = urlsplit(request.url)
    payload = {
        "version": REQUEST_KEY_VERSION,
        "method": request.method.upper(),
        "scheme": (parts.scheme or "").lower(),
        "host": (parts.hostname or "").lower(),
        "port": parts.port,
        "path": parts.path or "/",
        "query": _canonical_query(request.query),
        "endpoint_id": request.endpoint_id,
        "response_shape_version": request.response_shape_version,
        "headers": _semantic_headers(request.headers),
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def parse_retry_after(value: Optional[str],
                      now: Optional[_dt.datetime] = None) -> Optional[float]:
    """Return ``Retry-After`` as seconds, or ``None`` if it is unusable.

    Both RFC 7231 forms are accepted: a delay in seconds, and an HTTP-date. A
    date in the past yields ``0.0`` rather than a negative delay. Anything
    unparseable returns ``None``, so the caller falls back to its own backoff
    rather than trusting a malformed header.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        seconds = float(text)
        return max(0.0, seconds)
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        when = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=_dt.timezone.utc)
    reference = now or _dt.datetime.now(_dt.timezone.utc)
    return max(0.0, (when - reference).total_seconds())


def parse_rate_limit(response: HttpResponse,
                     now: Optional[_dt.datetime] = None) -> RateLimitInfo:
    """Extract whatever rate-limit metadata a response advertised.

    Several spellings are in circulation and none is universal, so each is
    tried and absence is recorded as absence. Nothing is inferred.
    """
    def _int(name: str) -> Optional[int]:
        raw = response.header(name)
        if raw is None:
            return None
        try:
            return int(str(raw).strip())
        except ValueError:
            return None

    def _float(name: str) -> Optional[float]:
        raw = response.header(name)
        if raw is None:
            return None
        try:
            return float(str(raw).strip())
        except ValueError:
            return None

    limit = _int("x-ratelimit-limit")
    if limit is None:
        limit = _int("ratelimit-limit")
    remaining = _int("x-ratelimit-remaining")
    if remaining is None:
        remaining = _int("ratelimit-remaining")
    reset = _float("x-ratelimit-reset")
    if reset is None:
        reset = _float("ratelimit-reset")
    return RateLimitInfo(
        limit=limit, remaining=remaining, reset_seconds=reset,
        retry_after_seconds=parse_retry_after(response.header("retry-after"), now))


@dataclass(frozen=True)
class TransportPolicy:
    """What a transport is allowed to do.

    Every field is a refusal, and each has a specific failure in mind:

    * ``allowed_hosts`` - an empty allowlist is a configuration error, not
      "allow everything". A typo in a base URL should not silently send a
      request somewhere else.
    * ``require_https`` - credentials and scientific payloads never travel in
      clear text.
    * ``allow_cross_host_redirects`` defaults to ``False``, so a redirect
      cannot walk the request off the allowlist.
    * ``max_response_bytes`` - a bounded read.
    * ``max_timeout_seconds`` - a bound on the bound, so no caller can disable
      the timeout by making it enormous.
    """

    allowed_hosts: Tuple[str, ...]
    require_https: bool = True
    allow_cross_host_redirects: bool = False
    max_redirects: int = 3
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    max_timeout_seconds: float = MAX_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.allowed_hosts:
            raise ConfigurationError(
                "TransportPolicy requires an explicit host allowlist. An empty "
                "list is not 'allow everything': a mistyped base URL must fail "
                "rather than reach an unintended host.")
        object.__setattr__(self, "allowed_hosts",
                           tuple(host.lower() for host in self.allowed_hosts))

    def check_url(self, url: str) -> None:
        """Raise unless ``url`` is one this transport may contact."""
        parts = urlsplit(url)
        scheme = (parts.scheme or "").lower()
        if self.require_https and scheme != "https":
            raise SecurityPolicyError(
                "refusing a %s:// request to %s: HTTPS is required"
                % (scheme or "(no scheme)", parts.hostname or "(no host)"))
        host = (parts.hostname or "").lower()
        if host not in self.allowed_hosts:
            raise SecurityPolicyError(
                "host %r is not in the allowlist %s"
                % (host, ", ".join(self.allowed_hosts)))

    def check_timeout(self, timeout_seconds: float) -> None:
        """Raise unless the timeout is present, positive and bounded."""
        if timeout_seconds is None or timeout_seconds <= 0:
            raise ConfigurationError(
                "a positive timeout is required; an unbounded request can hang "
                "a run indefinitely")
        if timeout_seconds > self.max_timeout_seconds:
            raise ConfigurationError(
                "timeout %.1fs exceeds the maximum %.1fs"
                % (timeout_seconds, self.max_timeout_seconds))

    def check_redirect(self, origin_url: str, target_url: str) -> None:
        """Raise unless following this redirect is permitted."""
        if self.allow_cross_host_redirects:
            self.check_url(target_url)
            return
        origin_host = (urlsplit(origin_url).hostname or "").lower()
        target_host = (urlsplit(target_url).hostname or "").lower()
        if origin_host != target_host:
            raise SecurityPolicyError(
                "refusing a redirect from %s to %s: cross-host redirects are "
                "disabled, so a redirect cannot walk a request off the "
                "allowlist" % (origin_host, target_host))
        self.check_url(target_url)


class UrllibTransport:
    """Production transport built on ``urllib``.

    Chosen because it adds no dependency. It performs exactly one request per
    call: retry, caching and pagination all live above it, so this class stays
    small enough to reason about.

    Credentials arrive through ``credential_headers`` at construction and are
    attached at send time. They are never stored on a request, so they cannot
    reach a request key, a cache entry or a manifest.
    """

    def __init__(
        self,
        policy: TransportPolicy,
        credential_headers: Optional[Mapping[str, str]] = None,
        user_agent: str = "pgx-platform-ingestion/0.4",
        opener: Any = None,
    ) -> None:
        self._policy = policy
        self._credentials = dict(credential_headers or {})
        self._user_agent = user_agent
        self._opener = opener

    def __repr__(self) -> str:
        # Overridden so an accidental repr() in a log cannot print a token.
        return "UrllibTransport(allowed_hosts=%s, credential_headers=%d)" % (
            ",".join(self._policy.allowed_hosts), len(self._credentials))

    __str__ = __repr__

    def send(self, request: HttpRequest) -> HttpResponse:
        """Perform one request, honouring the transport policy."""
        import urllib.error
        import urllib.request

        url = request.url
        self._policy.check_url(url)
        self._policy.check_timeout(request.timeout_seconds)

        if request.query:
            url = "%s?%s" % (url, urlencode(list(request.query)))

        headers = {name: value for name, value in request.headers.items()
                   if name.lower() not in CREDENTIAL_HEADER_NAMES}
        headers.setdefault("Accept", request.expected_content_type)
        headers["User-Agent"] = self._user_agent
        headers.update(self._credentials)

        requested_at = _dt.datetime.now(_dt.timezone.utc)
        urllib_request = urllib.request.Request(
            url, method=request.method, headers=headers)

        opener = self._opener or urllib.request.build_opener(
            _AllowlistRedirectHandler(self._policy))
        try:
            with opener.open(urllib_request,
                             timeout=request.timeout_seconds) as handle:
                body = handle.read(self._policy.max_response_bytes + 1)
                status = getattr(handle, "status", None) or handle.getcode()
                response_headers = dict(handle.headers.items())
                final_url = handle.geturl()
        except urllib.error.HTTPError as exc:
            body = exc.read(self._policy.max_response_bytes + 1)
            return self._build(request, exc.code, body, dict(exc.headers.items()),
                               exc.geturl() or url, requested_at)
        except SecurityPolicyError:
            raise
        except urllib.error.URLError as exc:
            raise TransientTransportError(
                "transport failure contacting %s: %s"
                % (urlsplit(url).hostname, exc.reason)) from exc
        except TimeoutError as exc:
            raise TransientTransportError(
                "request to %s timed out after %.1fs"
                % (urlsplit(url).hostname, request.timeout_seconds)) from exc
        except OSError as exc:
            raise TransientTransportError(
                "transport failure contacting %s: %s"
                % (urlsplit(url).hostname, exc)) from exc

        return self._build(request, status, body, response_headers, final_url,
                           requested_at)

    def _build(self, request, status, body, headers, final_url, requested_at):
        """Turn raw pieces into a response, enforcing the size limit."""
        if len(body) > self._policy.max_response_bytes:
            raise ResponseTooLargeError(
                "response from endpoint %r exceeds the %d byte limit"
                % (request.endpoint_id, self._policy.max_response_bytes))
        return HttpResponse(
            status_code=int(status), body=body, headers=headers,
            final_url=final_url, requested_at=requested_at,
            received_at=_dt.datetime.now(_dt.timezone.utc))


class _AllowlistRedirectHandler:
    """Refuse redirects the policy does not permit.

    Built lazily so importing this module pulls in no ``urllib`` machinery and,
    more importantly, opens nothing.
    """

    def __new__(cls, policy: TransportPolicy):
        import urllib.request

        class _Handler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                policy.check_redirect(req.full_url, newurl)
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        return _Handler()
