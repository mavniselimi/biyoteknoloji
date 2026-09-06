"""Compose the application. Connect to nothing.

:func:`create_app` builds a FastAPI application from a settings object and a
service provider. It registers routers, installs middleware and installs the
exception handlers, and it performs no I/O: no database connection, no active
release resolution, no fixture load, no file read. ``import apps.api.main``
therefore imports an application that is ready to be served and has touched
nothing, which is what makes the layers above it testable without an
environment.

Startup is where connections would be opened, and this lifespan opens only
what the provider was configured with. A failure there must leave the process
unable to serve assessments rather than able to serve them badly: the
consequence of a failed startup is a provider without an assessment
capability, and asking for one raises the typed 503. There is no path in which
a partially-initialised application answers ``POST /assessments`` with
anything but a refusal.

The OpenAPI document is our own generator's, installed over FastAPI's. One
declaration produces the routes, the models and the document, so the served
document cannot describe an API different from the one serving it - and the
contract test that compares the served document with the committed artifact is
comparing two things that are supposed to be identical rather than two
independently-written descriptions that happen to agree.
"""

from __future__ import annotations

import contextlib
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from apps.api import API_TITLE, API_VERSION
from apps.api.config import ApiSettings, load_settings
from apps.api.dependencies import ServiceProvider
from apps.api.errors import (ApiError, ERROR_CATALOGUE, error_envelope,
                             map_exception,
                             status_for_code)
from apps.api.middleware import (BodySizeLimitMiddleware,
                                 ProhibitedFieldMiddleware,
                                 RequestContextMiddleware,
                                 SecurityHeadersMiddleware)
from apps.api.openapi import build_document
from apps.api.request_id import REQUEST_ID_HEADER, generate_request_id
from apps.api.routers import (assessments, catalogue, evidence, expert_review,
                              health, system)

__all__ = ["create_app"]


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or generate_request_id()


def _respond(request: Request, code: str, details: Any = None) -> JSONResponse:
    request_id = _request_id(request)
    response = JSONResponse(
        status_code=status_for_code(code),
        content=error_envelope(code, request_id, details=details))
    response.headers[REQUEST_ID_HEADER] = request_id
    response.headers["Cache-Control"] = "no-store"
    return response


def _install_exception_handlers(app: FastAPI) -> None:
    """One mapper, three entry points into it.

    FastAPI raises its own validation error and Starlette raises its own HTTP
    exception; neither is an application error, and both would otherwise
    produce a body in a shape this API promises never to emit. They are
    converted here rather than anywhere else, so there is exactly one function
    that decides what an error response looks like.
    """

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request,
                          error: RequestValidationError) -> JSONResponse:
        # Locations normalised into the same ``$.a.b[0]`` form the
        # framework-free validator emits, and codes only - never the rejected
        # value, which for this endpoint could be a phenotype token or a
        # medication name.
        issues = []
        for item in error.errors()[:20]:
            location = "$"
            for part in item.get("loc", ())[1:]:
                location += ("[%d]" % part if isinstance(part, int)
                             else ".%s" % part)
            issues.append({"location": location,
                           "code": str(item.get("type", "invalid")).upper()})
        return _respond(request, "REQUEST_CONTRACT_VIOLATION",
                        {"issues": issues})

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request,
                    error: StarletteHTTPException) -> JSONResponse:
        by_status = {404: "RESOURCE_NOT_FOUND", 405: "REQUEST_MALFORMED",
                     401: "UNAUTHENTICATED", 403: "FORBIDDEN_ROLE",
                     413: "REQUEST_TOO_LARGE", 422: "REQUEST_MALFORMED"}
        return _respond(request,
                        by_status.get(error.status_code, "INTERNAL_ERROR"))

    @app.exception_handler(ApiError)
    async def _refusal(request: Request, error: ApiError) -> JSONResponse:
        """A typed refusal is an answer, not a server error.

        Registered separately from the catch-all below, and the difference is
        not cosmetic. Starlette routes a handler registered for ``Exception``
        through ``ServerErrorMiddleware``, which logs the traceback at ERROR
        level before delegating. Every anonymous ``GET /cases`` therefore
        printed a full ASGI exception group ending in
        ``UnauthenticatedError: UNAUTHENTICATED`` - for the single most
        ordinary event in the application's life, a request from somebody who
        is not logged in.

        Handled here, the same refusal produces the same 401 body with no
        traceback, and the catch-all keeps its job: an exception nobody
        planned for is still logged, loudly.
        """
        return _respond(request, error.code, dict(error.details))

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, error: Exception) -> JSONResponse:
        # ``map_exception`` is total: a known application or engine failure
        # keeps its code, and anything else becomes INTERNAL_ERROR with the
        # catalogue's fixed message. ``str(error)`` is never read here - an
        # unexpected exception's text is the one place a SQL fragment, a path
        # or a connection string is most likely to be.
        code, details = map_exception(error)
        return _respond(request, code, details)


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open what is configured; close it again. Resolve no release.

    Deliberately not the place to warm a cache of the active release: a
    release resolved at startup is a release that goes stale, and an
    assessment must pin the pointer at the moment it runs.
    """
    opener = getattr(app.state.provider, "open", None)
    if callable(opener):
        opener()
    try:
        yield
    finally:
        closer = getattr(app.state.provider, "close", None)
        if callable(closer):
            closer()


def create_app(settings: Optional[ApiSettings] = None,
               provider: Optional[ServiceProvider] = None) -> FastAPI:
    """Build the application.

    Args:
        settings: configuration. Loaded from the environment when omitted,
            which is the production path; passed explicitly by every test, so
            that no test depends on process environment.
        provider: the capabilities to serve with. Defaults to one that has
            none, which produces an application whose health routes answer and
            whose every other route reports the typed unavailability for what
            it needed. That is the correct behaviour for an unconfigured
            deployment, and it is the default rather than a special case.
    """
    settings = settings or load_settings()
    provider = provider or ServiceProvider(settings=settings)

    app = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        lifespan=_lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.state.provider = provider
    app.state.settings = settings

    # Order matters: the outermost middleware runs first on the way in, and
    # `add_middleware` prepends, so the last one added is the outermost. The
    # correlation id must exist before anything can refuse a request, so that
    # even a refusal from the size limiter carries one.
    #
    # The prohibited-field scan is added first, which makes it the innermost
    # of these and therefore the last thing before routing. Deliberate on both
    # sides: it must run *after* the size limiter, so an unbounded body is
    # disconnected rather than buffered and parsed here, and *before* FastAPI
    # resolves the endpoint's parameters, because Pydantic would otherwise
    # classify a genotype as an unknown field and the authoritative refusal
    # would never be reached.
    app.add_middleware(ProhibitedFieldMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(BodySizeLimitMiddleware,
                       max_body_bytes=settings.max_body_bytes)
    app.add_middleware(RequestContextMiddleware)

    if settings.cors_enabled:
        from starlette.middleware.cors import CORSMiddleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_allowed_origins),
            allow_credentials=settings.cors_allow_credentials,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type",
                           REQUEST_ID_HEADER],
            expose_headers=[REQUEST_ID_HEADER],
            max_age=600)

    _install_exception_handlers(app)

    for module in (health, system, assessments, catalogue, evidence,
                   expert_review):
        app.include_router(module.router)

    def _openapi() -> dict:
        # The runtime-verification block reflects recorded evidence, read here
        # rather than at import so that building the application still touches
        # nothing. Both this and `apps.api.artifacts` read the same evidence,
        # so the served document and the committed artifact agree about their
        # own verification status in every state - unverified, verified, and
        # verified-then-invalidated - and the byte-for-byte comparison test
        # stays meaningful instead of failing on a field about itself.
        from apps.api.runtime_verification import verified_runtime_status

        return build_document(
            runtime_verified=verified_runtime_status()[
                "openapi_runtime_verified"])

    app.openapi = _openapi  # type: ignore[method-assign]
    return app
