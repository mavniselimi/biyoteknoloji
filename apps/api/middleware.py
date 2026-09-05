"""Correlation, size limits and response headers.

Three middlewares, each doing one thing that has to happen for every request
whether or not a router runs.

They return errors themselves rather than raising. Starlette applies
registered exception handlers *inside* the user middleware stack, so an
exception raised here would escape them and surface as an unhandled 500 with
whatever body the server chose - which for a request that was refused for
being too large would be the one shape this API promises never to emit. Each
middleware therefore builds the same envelope
:func:`~apps.api.errors.error_envelope` builds, from the same catalogue.

What is *not* here matters too. No middleware resolves a release, opens a
database session, reads the active pointer or touches an assessment. Work that
depends on the pinned release belongs after the release is pinned, inside the
service; doing any of it here would mean a request whose release was resolved
before the route decided whether it needed one.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Mapping, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from apps.api.contracts.spec import LIMITS
from apps.api.contracts.validate import find_prohibited_fields
from apps.api.errors import error_envelope, status_for_code
from apps.api.request_id import (REQUEST_ID_HEADER, generate_request_id,
                                 is_valid_request_id)

__all__ = [
    "SECURITY_HEADERS",
    "BodySizeLimitMiddleware",
    "ProhibitedFieldMiddleware",
    "RequestContextMiddleware",
    "SecurityHeadersMiddleware",
]

#: Conservative and static. Aimed at a JSON API rather than copied from a
#: web-page checklist: this API serves no HTML, so the policy that matters is
#: the one that stops a browser from treating a response as anything but data.
SECURITY_HEADERS: Mapping[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    # No script, no style, no frame, no form target. A JSON response should
    # never execute anything, and a policy that says so costs nothing.
    "Content-Security-Policy": ("default-src 'none'; frame-ancestors 'none'; "
                                "base-uri 'none'; form-action 'none'"),
}


def _envelope_response(code: str, request_id: str, *,
                       details: Any = None) -> JSONResponse:
    response = JSONResponse(
        status_code=status_for_code(code),
        content=error_envelope(code, request_id, details=details))
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Establish the correlation id, and put it on every response.

    The id is placed on ``request.state`` before the route runs and echoed in
    the header afterwards, so the body and the header of any response - a
    success, a refusal, or a 500 - carry the same value.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        supplied = request.headers.get(REQUEST_ID_HEADER)
        if supplied is not None and not is_valid_request_id(supplied):
            # Refused rather than replaced: see apps/api/request_id.py for the
            # contract and why silently substituting one is worse.
            request_id = generate_request_id()
            request.state.request_id = request_id
            return _envelope_response(
                "REQUEST_ID_INVALID", request_id,
                details={"issues": [{"location": "$.headers." +
                                     REQUEST_ID_HEADER,
                                     "code": "PATTERN_MISMATCH"}]})

        request_id = supplied or generate_request_id()
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Refuse an oversized body before anything reads it.

    Checks the declared ``Content-Length`` and then the bytes actually read,
    because a declared length is a claim: a chunked request declares nothing,
    and a lying one declares the wrong thing. Reading is capped, so a client
    streaming an unbounded body is disconnected rather than buffered.
    """

    def __init__(self, app: Any, *, max_body_bytes: int) -> None:
        super().__init__(app)
        self._limit = int(max_body_bytes)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = getattr(request.state, "request_id",
                             None) or generate_request_id()
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > self._limit:
                    return _envelope_response(
                        "REQUEST_TOO_LARGE", request_id,
                        details={"limit": self._limit})
            except ValueError:
                return _envelope_response(
                    "REQUEST_MALFORMED", request_id,
                    details={"issues": [{"location": "$.headers.Content-Length",
                                         "code": "TYPE_INVALID"}]})

        if request.method in ("POST", "PUT", "PATCH"):
            body = await request.body()
            if len(body) > self._limit:
                return _envelope_response("REQUEST_TOO_LARGE", request_id,
                                          details={"limit": self._limit})
        return await call_next(request)


class ProhibitedFieldMiddleware(BaseHTTPMiddleware):
    """Refuse a prohibited field before the request model is validated.

    The contract says the recursive prohibited-field scan runs **first**:
    before any shape is checked, the whole document is walked to any depth for
    the names in ``PROHIBITED_REQUEST_FIELDS``, and a request carrying one is
    refused whole rather than partly used. The framework-free validator in
    ``apps/api/contracts/validate.py`` does exactly that, and it was the only
    thing that did.

    In a running deployment it never got the chance. Pydantic parses the body
    while FastAPI is resolving the endpoint's parameters, and a model that
    forbids extra fields rejects ``genotype`` as an unknown key - so the
    request came back ``REQUEST_CONTRACT_VIOLATION``, classified by a
    framework rule that knows nothing about why that field is refused. The
    difference is not cosmetic. ``PROHIBITED_INPUT_FIELD`` is the code that
    says *this product does not accept this kind of data*; a caller filtering
    their logs for it would have seen nothing, and a reviewer asking "has
    anyone ever sent us a genotype" would have got the wrong answer.

    So the scan runs here, in front of routing and in front of Pydantic, and
    the classification is the contract's rather than the framework's.

    **Only declared body-bearing routes are scanned.** Running on every path
    would answer 422 for a POST to a path that does not exist, which tells an
    anonymous caller that something is there - and turns a scan meant to
    protect input into a path-enumeration oracle. The route table already says
    which operations accept a body; that is the gate.

    **It runs before authentication, deliberately.** A prohibited field is
    refused whoever sent it: the product does not accept the data, and
    accepting it far enough to check a bearer token first would be accepting
    it. The body-size limiter already refuses ahead of authentication for the
    same reason, so this is the established order rather than a new one. What
    an unauthenticated caller learns is only that a route they already knew
    the address of dislikes a field they themselves sent.

    **No value is echoed, ever.** The response carries normalised locations
    and the code, which is all ``find_prohibited_fields`` returns - it is
    written to return locations and never values, precisely so that a rejected
    genotype cannot reach a log, a browser history or a screenshot after
    having been refused.
    """

    #: Content types whose body is a JSON document. A body this middleware
    #: cannot parse is passed through untouched: guessing at a shape here
    #: would be a second parser, and the endpoint's own refusal is already
    #: correct for it.
    JSON_TYPES = ("application/json", "application/problem+json")

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self._scanned = _body_bearing_routes()

    def _is_scanned(self, method: str, path: str) -> bool:
        if method not in ("POST", "PUT", "PATCH"):
            return False
        for candidate_method, pattern in self._scanned:
            if candidate_method == method and pattern.match(path):
                return True
        return False

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self._is_scanned(request.method, request.url.path):
            return await call_next(request)

        media_type = (request.headers.get("content-type") or "").split(";")[0]
        if media_type.strip().lower() not in self.JSON_TYPES:
            return await call_next(request)

        body = await request.body()
        if not body:
            return await call_next(request)
        try:
            document = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            # Malformed JSON is already a contract violation with its own
            # code. Classifying it here would mean this middleware decided
            # what a broken body means, which is not its question.
            return await call_next(request)

        prohibited = find_prohibited_fields(document)
        if not prohibited:
            return await call_next(request)

        request_id = getattr(request.state, "request_id",
                             None) or generate_request_id()
        return _envelope_response(
            "PROHIBITED_INPUT_FIELD", request_id,
            details={"issues": [{"location": location,
                                 "code": "PROHIBITED_FIELD"}
                                for location in
                                prohibited[:LIMITS["max_detail_entries"]]]})


def _body_bearing_routes() -> Tuple[Tuple[str, "re.Pattern"], ...]:
    """Every declared operation that accepts a request document.

    Built from the route table rather than listed, so an operation that grows
    a request model is scanned without anybody remembering to add it here -
    and an operation that loses one stops being scanned for the same reason.
    """
    from apps.api.routes import ROUTES

    compiled = []
    for route in ROUTES:
        if route.request_model is None:
            continue
        pattern = "^" + re.sub(r"\{[^}]+\}", "[^/]+",
                               re.escape(route.path).replace("\\{", "{")
                               .replace("\\}", "}")) + "$"
        compiled.append((route.method, re.compile(pattern)))
    return tuple(compiled)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach the static security headers and the caching policy.

    ``no-store`` for everything by default. An assessment response carries a
    case's governed facts, and an error response carries a correlation id; a
    shared cache holding either is a disclosure that nobody configured on
    purpose. An immutable caching policy for a stored assessment is defensible
    - the document really is immutable - but it has to be proven per route
    rather than assumed here, so the default is the conservative one.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        response.headers.setdefault("Cache-Control", "no-store")
        return response
