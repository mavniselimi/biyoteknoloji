"""The ASGI entry point.

``app`` is built at import and connects to nothing, so an ASGI server can load
this module without a database being reachable - and so can a test, and so can
a documentation generator.

The provider this module composes is the one from the environment. In a
deployment with no database, no evidence build and no authentication
configured - which is this repository's current state - the result is an
application that serves its health routes honestly and refuses everything else
with the typed unavailability for what is missing. That is a working
application reporting an incomplete environment, not a broken one.
"""

from __future__ import annotations

from typing import Optional

from apps.api.config import ApiSettings, load_settings
from apps.api.dependencies import ServiceProvider
from apps.api.factory import create_app

__all__ = ["app", "build_app", "build_provider",
           "composition_result", "run"]


def build_provider(settings: Optional[ApiSettings] = None
                   ) -> ServiceProvider:
    """Compose the capabilities this environment actually has.

    Constructs nothing that connects. Each capability is a factory the request
    path calls, so a database session is opened per request by the code that
    needs one - never here, and never at import.

    WP-24 attempts the real composition first. It returns a *result*, not an
    exception, because "this deployment has no database" must be a state the
    application can start in and report: an application that refused to boot
    could not serve the readiness endpoint that says why.

    The provider carries real capabilities only when composition genuinely
    produced them. That is what makes the status field downstream a
    measurement rather than a restatement of ``PGX_API_AUTH_MODE`` - a
    variable can name a configuration this host cannot provide.
    """
    settings = settings or load_settings()
    result = composition_result(settings)
    if result.composition is None:
        return ServiceProvider(settings=settings)
    from apps.api.deployment import build_deployment_provider

    return build_deployment_provider(settings, result.composition)


def composition_result(settings: Optional[ApiSettings] = None):
    """What the deployment composition produced, and what blocked it.

    Kept as a separate entry point so a CLI, a preflight and a readiness
    document can all ask the same question without building an application.
    """
    from pgx.deployment.composition import compose_from_environment

    return compose_from_environment()


def build_app(settings: Optional[ApiSettings] = None):
    """The application, with the request scope installed when one is needed.

    The scope middleware is added *only* when a composition exists. An
    unconfigured deployment therefore carries no extra layer, opens no
    session, and behaves exactly as it did before WP-24 - which is what makes
    "nothing is configured" a supported state rather than a degraded one.
    """
    settings = settings or load_settings()
    result = composition_result(settings)
    if result.composition is None:
        return create_app(settings, ServiceProvider(settings=settings)), result
    from apps.api.deployment import (RequestScopeMiddleware,
                                     build_deployment_provider)

    built = create_app(settings,
                       build_deployment_provider(settings,
                                                 result.composition))
    # Outermost, so every request - including one the body-size limiter
    # refuses - runs inside a scope that is closed afterwards.
    # ``add_middleware`` prepends, so adding it last puts it first.
    built.add_middleware(RequestScopeMiddleware,
                         composition=result.composition)
    return built, result


settings = load_settings()
app, _composition = build_app(settings)


def run() -> None:
    """Serve the real application. The console entry point.

    Imports the server inside the function rather than at module scope, so
    that importing this module - which a test, a generator or another process
    may do - does not require an ASGI server to be installed.
    """
    try:
        import uvicorn
    except ImportError:  # pragma: no cover - depends on the environment
        raise SystemExit(
            "an ASGI server is required to serve this application; install "
            "the 'api' extra") from None
    uvicorn.run("apps.api.main:app", host="127.0.0.1", port=8000,
                reload=False)
