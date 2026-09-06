"""Compose the interface. Connect to nothing.

:func:`create_web_app` builds a FastAPI application that serves the eleven
pages and the two local asset directories. Like the API's factory it performs
no I/O at import: no database connection, no release resolution, no template
compilation and no catalogue read. The catalogue is read per request through
the provider, so a deployment whose sealed artifact is missing serves a page
saying so rather than failing to start.

:func:`create_combined_app` is the deployment architecture.md describes - one
image serving both. It builds the API application first and adds the page
routes to it, which means the API paths, the health paths and the OpenAPI
document are exactly what WP-16 produced. The document cannot acquire an HTML
route even in principle: ``apps.api.openapi.build_document`` is generated from
the API route table, and no page is in that table.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import FastAPI

from apps.api.config import ApiSettings
from apps.api.provider import ServiceProvider
from apps.web import WEB_TITLE, WEB_VERSION
from apps.api.errors import ApiError
from apps.web.config import WebSettings, load_web_settings
from apps.web.dependencies import WebProvider
from apps.web.routers import pages as page_router

__all__ = ["create_combined_app", "create_web_app", "mount_web"]

_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "static")


def _install_static(app: FastAPI, settings: WebSettings) -> None:
    """Serve the interface's own CSS and JavaScript, and nothing else.

    Two files from one directory inside this package. There is no upload
    location, no user-writable path and no directory listing; the
    content-security policy allows scripts and styles from this origin only,
    so a page cannot reference anything this mount does not serve.
    """
    from fastapi.staticfiles import StaticFiles

    app.mount("/static", StaticFiles(directory=_STATIC_DIR, html=False),
              name="static")


def _install_error_handler(app: FastAPI) -> None:
    """Render an HTML error page for a **page route's** failure.

    An operator who followed a link expects a page, and a JSON envelope in a
    browser window is a worse failure than the one it reports. The page is
    built by the same controlled builder every other error uses, so no handler
    composes a message.

    The qualifier is load-bearing in the combined deployment. FastAPI keeps
    one handler per exception type, so installing these replaces the API's -
    and an unqualified HTML handler turned every API failure into an HTML
    page. ``GET /api/v1/system/version`` on an unconfigured deployment came
    back ``503 text/html``, which breaks the one thing the API contract
    promises unconditionally: a JSON error envelope, always, for every API
    path. A client parsing that response gets a syntax error instead of a
    governed code.

    So the handler asks which surface the request was for, and answers in that
    surface's shape. There is no third behaviour and no default: a path is
    either the interface's or it is not.
    """
    from fastapi import Request
    from fastapi.responses import HTMLResponse, JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from apps.api.errors import error_envelope, map_exception, status_for_code
    from apps.api.request_id import REQUEST_ID_HEADER
    from apps.web.pages import PageEnvironment, render_error_page
    from apps.web.routes import RESERVED_PATH_PREFIXES

    def _is_page_request(request: Request) -> bool:
        """Whether this path belongs to the interface rather than the API.

        Decided by the reserved prefixes the web route table already refuses
        to shadow, so the two answers cannot drift: if a page may not live
        under a prefix, a failure under that prefix is not a page's failure.
        """
        path = request.url.path
        for prefix in RESERVED_PATH_PREFIXES:
            if path == prefix or path.startswith(prefix):
                return False
        return True

    def _json_failure(request: Request, code: str,
                      details: Any = None) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "") or ""
        response = JSONResponse(
            status_code=status_for_code(code),
            content=error_envelope(code, request_id, details=details))
        if request_id:
            response.headers[REQUEST_ID_HEADER] = request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    def _environment(request: Request) -> PageEnvironment:
        provider = getattr(request.app.state, "web_provider", None)
        settings = getattr(provider, "settings", None)
        return PageEnvironment(
            locale=getattr(settings, "locale", "tr"),
            environment=getattr(getattr(settings, "environment", None),
                                "value", ""),
            request_id=getattr(request.state, "request_id", "") or "",
            asset_version=getattr(settings, "static_asset_version", "1"))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, error: StarletteHTTPException):
        by_status = {404: "RESOURCE_NOT_FOUND", 405: "REQUEST_MALFORMED",
                     401: "UNAUTHENTICATED", 403: "FORBIDDEN_ROLE",
                     413: "REQUEST_TOO_LARGE", 422: "REQUEST_MALFORMED"}
        code = by_status.get(error.status_code, "INTERNAL_ERROR")
        if not _is_page_request(request):
            return _json_failure(request, code)
        result = render_error_page(_environment(request), code=code)
        return HTMLResponse(result.html, status_code=result.status,
                            headers=result.headers)

    @app.exception_handler(ApiError)
    async def _refusal(request: Request, error: ApiError):
        """A typed refusal renders its page without a server-error traceback.

        The same reasoning as the API's handler: a handler registered for
        ``Exception`` is routed through ``ServerErrorMiddleware``, which logs
        the traceback at ERROR level first. An anonymous visitor reaching a
        page that needs a session is not a server error, and a log full of
        them is a log nobody reads when something real breaks.
        """
        code, details = map_exception(error)
        if not _is_page_request(request):
            return _json_failure(request, code, details)
        result = render_error_page(_environment(request), code=code)
        return HTMLResponse(result.html, status_code=result.status,
                            headers=result.headers)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, error: Exception):
        # map_exception never reads str(error). Whatever went wrong, the
        # response carries a catalogue code and a request id and nothing else
        # - as a page for the interface, as an envelope for the API.
        code, details = map_exception(error)
        if not _is_page_request(request):
            return _json_failure(request, code, details)
        result = render_error_page(_environment(request), code=code)
        return HTMLResponse(result.html, status_code=result.status,
                            headers=result.headers)


def mount_web(app: FastAPI, provider: WebProvider, *,
              api_provider: Optional[ServiceProvider] = None) -> FastAPI:
    """Add the page routes and assets to an existing application.

    Two providers, because a page needs two different things and they belong
    to different layers. The :class:`WebProvider` supplies what the interface
    owns - the client, the case catalogue, the CSRF verifier. The API's
    :class:`ServiceProvider` supplies the principal resolver, because every
    page route is guarded by WP-16's own ``require_access`` and the interface
    is not permitted to establish an identity the API would not.

    ``app.state.provider`` is set only when it is absent. In
    :func:`create_combined_app` the API application has already set its own
    and that one must win: two providers in one process, with the pages using
    a different resolver from the API, is precisely the split identity this
    arrangement exists to prevent.
    """
    app.state.web_provider = provider
    app.state.web_settings = provider.settings
    if getattr(app.state, "provider", None) is None:
        app.state.provider = api_provider or ServiceProvider(
            settings=provider.settings.api)
    app.include_router(page_router.router)
    _install_static(app, provider.settings)
    _install_error_handler(app)
    return app


def create_web_app(settings: Optional[WebSettings] = None,
                   provider: Optional[WebProvider] = None,
                   api_provider: Optional[ServiceProvider] = None) -> FastAPI:
    """Build a web-only application.

    Useful when the API runs elsewhere: compose this with an
    :class:`~apps.web.client.HttpApiClient` and it serves pages against a
    remote application. Defaults to a provider with no client at all, which
    produces an interface whose pages state what is missing.

    ``api_provider`` is the principal resolver's home. A web-only deployment
    still needs one even though its assessment capability lives elsewhere:
    every page route is guarded by WP-16's ``require_access``, which resolves
    a principal through it. Left unset, one is built from ``settings.api`` -
    which is the fail-closed arrangement, not a convenience, because a
    ``ServiceProvider`` with nothing configured refuses rather than admits.
    """
    settings = settings or load_web_settings()
    provider = provider or WebProvider(settings=settings)

    app = FastAPI(
        title=WEB_TITLE,
        version=WEB_VERSION,
        # No OpenAPI document for the web application. Its routes are HTML
        # pages, not an API, and publishing a schema for them would invite a
        # client to treat a page as an interface contract.
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    return mount_web(app, provider, api_provider=api_provider)


def create_combined_app(api_settings: Optional[ApiSettings] = None,
                        api_provider: Optional[ServiceProvider] = None,
                        web_provider: Optional[WebProvider] = None
                        ) -> FastAPI:
    """One image serving the API and the interface.

    The API application is built first and unchanged: its paths, its health
    routes, its middleware, its exception handlers and its OpenAPI document
    are WP-16's. The pages are added to it, under paths the web route table
    refuses to let collide with an API path.
    """
    from apps.api.config import load_settings as load_api_settings
    from apps.api.factory import create_app

    api_settings = api_settings or load_api_settings()
    api_provider = api_provider or ServiceProvider(settings=api_settings)
    app = create_app(api_settings, api_provider)

    if web_provider is None:
        web_provider = WebProvider(
            settings=load_web_settings(api=api_settings))
    return mount_web(app, web_provider)
