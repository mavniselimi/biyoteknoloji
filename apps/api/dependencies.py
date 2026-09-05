"""What a request needs, injected, with a typed answer for what is missing.

Every capability the routers use arrives through :class:`ServiceProvider`.
Nothing is imported at module scope from the infrastructure layer, nothing is
constructed at import, and every field is optional - so composing an
application that has no database, no evidence build or no authentication is a
supported configuration rather than an import error.

The missing case is where the safety content is. A router that asked for the
assessment service and received ``None`` could easily go on to do something
reasonable-looking; instead, asking for a capability this deployment does not
have raises the typed 503 for that capability. An operator gets
``DATABASE_UNAVAILABLE`` or ``ACTIVE_RELEASE_UNAVAILABLE`` rather than a
``NoneType`` traceback, and a caller never gets a partial answer assembled
from whatever happened to be configured.

Overriding for tests goes through FastAPI's ``dependency_overrides`` on the
provider getter, which is one seam rather than one per capability.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from fastapi import Depends, Request

from apps.api.config import ApiSettings, load_settings
from apps.api.errors import ApiError, NotReadyError, UnauthenticatedError
from apps.api.provider import ServiceProvider
from apps.api.readiness import ReadinessProbes
from apps.api.security import (AccessPolicy, Principal, PrincipalResolver,
                               UnconfiguredAuthentication, authorize)
from pgx.application.execution_context import (ExecutionChannel,
                                               ExecutionContext)
from pgx.domain.claims import DEFAULT_CLAIM_BOUNDARY

__all__ = [
    "ServiceProvider",
    "get_audit_context",
    "get_execution_context",
    "get_principal",
    "get_provider",
    "get_request_id",
    "get_settings",
    "parameter",
    "require_access",
]


def parameter(route: Any, name: str) -> Any:
    """Build the FastAPI parameter that :mod:`apps.api.routes` declares.

    Every path and query parameter is declared once, with its pattern or its
    numeric range, and the OpenAPI document is generated from that
    declaration. This turns the same declaration into the object that actually
    enforces it, so the documented contract and the enforced one are the same
    contract rather than two that agree today.

    Without this the gap is quiet and expensive: a path declared as a UUID but
    typed as a bare ``str`` reaches the domain parser, which raises for a
    malformed value, and a malformed value the contract already documented as
    unacceptable comes back as a 500 instead of a 4xx.
    """
    from fastapi import Path, Query

    for spec in route.parameters:
        if spec.name != name:
            continue
        constraints: Dict[str, Any] = {"description": spec.description}
        if spec.pattern is not None:
            constraints["pattern"] = spec.pattern
        if spec.max_length is not None:
            constraints["max_length"] = spec.max_length
        if spec.minimum is not None:
            constraints["ge"] = spec.minimum
        if spec.maximum is not None:
            constraints["le"] = spec.maximum
        if spec.location == "path":
            return Path(..., **constraints)
        return Query(spec.default, **constraints)
    raise KeyError(  # pragma: no cover - a routing mistake, caught at import
        "%s declares no parameter named %r" % (route.operation_id, name))


def get_provider(request: Request) -> ServiceProvider:
    """The provider this application was composed with.

    The single seam a test overrides. Everything else in this module reads
    through it, so one ``dependency_overrides[get_provider]`` replaces the
    whole environment.
    """
    provider = getattr(request.app.state, "provider", None)
    if provider is None:  # pragma: no cover - create_app always sets it
        raise NotReadyError("SERVICE_NOT_READY",
                            details={"components": ["application"]})
    return provider


def get_settings(provider: ServiceProvider = Depends(get_provider)
                 ) -> ApiSettings:
    return provider.settings


def get_request_id(request: Request) -> str:
    """The correlation id the middleware established for this request.

    Read from request state rather than from the header, so that the value in
    a response body is by construction the value in the response header: two
    independent reads of the header could differ if anything rewrote it.
    """
    return getattr(request.state, "request_id", "")


def get_principal(request: Request,
                  provider: ServiceProvider = Depends(get_provider)
                  ) -> Optional[Principal]:
    """Establish the caller's principal from the source the mode names.

    WP-16 read the ``Authorization`` header unconditionally, which was correct
    when the only resolver was a development fixture. WP-23 makes the origin
    depend on the configured mode, and that dependency is the security
    content: under ``SESSION`` this reads the governed session cookie and
    nothing else, and under ``STATIC_TOKEN`` it reads the bearer header and
    nothing else.

    It deliberately does **not** try both and use whichever works. That
    version would leave a production deployment honouring development tokens,
    and it would do so silently - the routes would keep working, so nobody
    would look.

    Nothing here decides who anyone is. The whole of this function's
    contribution is that the value it passes on comes from a transport the
    server controls the interpretation of, never from a request body.
    """
    from pgx.security.vocabulary import SESSION_COOKIE_NAME

    mode = getattr(provider.principals, "mode", None)
    credential = None
    if mode is not None and getattr(mode, "reads_session_cookie", False):
        credential = request.cookies.get(SESSION_COOKIE_NAME)
    elif mode is not None and getattr(mode, "reads_bearer_token", False):
        header = request.headers.get("authorization")
        if header:
            scheme, _, rest = header.partition(" ")
            credential = rest.strip() if scheme.lower() == "bearer" else None
    return provider.principals.resolve(credential)


def require_access(policy: AccessPolicy, operation_id: str) -> Callable:
    """Build the dependency that enforces one route's access policy.

    A factory rather than a decorator so that the policy comes from the route
    table: a route's permitted roles are declared in one place and enforced
    from that same place, and a router cannot quietly widen them.
    """

    def _dependency(request: Request,
                    provider: ServiceProvider = Depends(get_provider)
                    ) -> Optional[Principal]:
        if policy.public:
            return None
        principal = get_principal(request, provider)
        return authorize(policy, principal, operation_id=operation_id)

    return _dependency


def get_execution_context(request: Request, principal: Principal
                          ) -> ExecutionContext:
    """The audited circumstances of this call.

    Built from the authenticated principal and the server-established request
    id. There is no parameter here that a request body could reach, which is
    the mechanical reason a client cannot forge an actor or a role.
    """
    return ExecutionContext(
        actor=principal.actor,
        role=principal.role.value,
        channel=ExecutionChannel.API,
        request_id=getattr(request.state, "request_id", None) or None,
        authenticated_by=principal.authenticated_by,
        assurance=principal.assurance,
        session_reference=principal.session_reference)


def get_audit_context(request: Request, principal: Principal):
    """The canonical audit context for this call (WP-23).

    Built from the authenticated principal, exactly like the execution
    context above and for the same reason: there is no parameter here a
    request body could reach, which is the mechanical reason a client cannot
    forge an actor, a role, a session reference or an assurance level.
    """
    from pgx.infrastructure.audit.service import AuditContext
    from pgx.security.vocabulary import AuthAssurance, AuthMechanism

    assurance = AuthAssurance(principal.assurance)
    mechanism = {
        AuthAssurance.SESSION: AuthMechanism.SESSION,
        AuthAssurance.TEST_STATIC_TOKEN: AuthMechanism.STATIC_TOKEN,
        AuthAssurance.NONE: AuthMechanism.NONE,
    }[assurance]
    return AuditContext(
        actor_id=principal.actor, actor_role=principal.role.value,
        auth_mechanism=mechanism, auth_assurance=assurance,
        session_reference=principal.session_reference,
        request_id=getattr(request.state, "request_id", None) or None)
