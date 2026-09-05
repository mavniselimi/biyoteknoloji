"""The combined ASGI entry point.

``app`` is built at import and connects to nothing, so a server, a test or a
documentation tool can load this module with no database reachable.

In a deployment with nothing configured - which is this repository - the
result is an application whose health routes answer, whose API refuses with
typed unavailability, and whose pages render and say what is missing. That is
a working application reporting an incomplete environment.
"""

from __future__ import annotations

from typing import Optional

from apps.api.config import ApiSettings, load_settings as load_api_settings
from apps.api.provider import ServiceProvider
from apps.web.config import WebSettings, load_web_settings
from apps.web.dependencies import WebProvider
from apps.web.factory import create_combined_app

__all__ = ["app", "build_combined_app", "build_web_provider",
           "run"]


def build_web_provider(web_settings: WebSettings,
                       api_provider: ServiceProvider) -> WebProvider:
    """Compose the interface over the in-process API.

    The client talks to the API in this process, which is what one image
    means. Nothing is constructed that connects: the client resolves its
    capabilities from the same provider the API routes use, per request.
    """
    from apps.web.client import InProcessApiClient
    from apps.web.demo_cases import load_development_cases

    csrf_factory = None
    authentication_service = None
    if api_provider.authentication_service is not None and \
            api_provider.csrf_service is not None:
        # Composed only when the session authentication service genuinely
        # exists. A verifier without one would mint tokens for a login form
        # that cannot authenticate anybody - a control that looks live and
        # fails after the operator has typed a password into it.
        from apps.web.security import SessionBoundCsrfVerifier

        def csrf_factory(binding: str, secret: str):  # noqa: F811
            return SessionBoundCsrfVerifier(binding=binding, secret=secret)

        authentication_service = api_provider.authentication_service

    return WebProvider(
        settings=web_settings,
        client=InProcessApiClient(api_provider),
        # A callable, so a missing artifact is a page that says so rather than
        # an application that will not start.
        case_catalog=load_development_cases,
        csrf_factory=csrf_factory,
        authentication_service=authentication_service,
    )


def build_combined_app(api_settings, web_settings):
    """The combined application, with the WP-24 request scope when composed.

    One image serves the API and the pages, so there is one scope per request
    and both halves of a request share it - which is what lets a form
    submission's governed change and its audit record be one transaction
    rather than two.
    """
    from apps.api.main import composition_result

    result = composition_result(api_settings)
    if result.composition is None:
        provider = ServiceProvider(settings=api_settings)
        return create_combined_app(
            api_settings, provider,
            build_web_provider(web_settings, provider)), result
    from apps.api.deployment import (RequestScopeMiddleware,
                                     build_deployment_provider)

    provider = build_deployment_provider(api_settings, result.composition)
    built = create_combined_app(api_settings, provider,
                                build_web_provider(web_settings, provider))
    built.add_middleware(RequestScopeMiddleware,
                         composition=result.composition)
    return built, result


api_settings = load_api_settings()
web_settings = load_web_settings(api=api_settings)
app, _composition = build_combined_app(api_settings, web_settings)


def run() -> None:
    """Serve the combined application. The console entry point."""
    try:
        import uvicorn
    except ImportError:  # pragma: no cover - depends on the environment
        raise SystemExit(
            "an ASGI server is required to serve this application; install "
            "the 'web' extra") from None
    uvicorn.run("apps.web.main:app", host="127.0.0.1", port=8000,
                reload=False)
