# -*- coding: utf-8 -*-
"""Wiring the deployment composition into the ASGI application (WP-24).

:mod:`pgx.deployment.composition` is framework-free by design - the direction
rule is one-way, and a composition module that imported FastAPI could not be
used by a CLI or a test. This module is the other half: it takes what
composition produced and turns it into the objects the ASGI layer speaks -
a middleware, a principal resolver, a set of readiness probes and a
``ServiceProvider``.

The load-bearing piece is :class:`RequestScopeMiddleware`. Every capability
factory in the composition resolves through a ``ContextVar``, and this
middleware is what sets it, per request, and clears it afterwards whether the
handler returned or raised. Without it a capability would raise
``DEPLOY_COMPOSITION_INCOMPLETE`` rather than quietly sharing a session - which
is the right failure, and this is what makes it never happen.

The middleware is added *only* when a composition exists. An unconfigured
deployment carries no extra layer, opens no session, and answers exactly as it
did before WP-24: health routes honestly, everything else with the typed 503
for what is missing.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from apps.api.config import ApiSettings
from apps.api.provider import ServiceProvider
from apps.api.readiness import ReadinessProbes
from apps.api.security import UnconfiguredAuthentication

__all__ = [
    "RequestScopeMiddleware",
    "RequestScopedSessionAuthentication",
    "build_deployment_probes",
    "build_deployment_provider",
]


class RequestScopedSessionAuthentication:
    """A principal resolver that builds its service inside the request.

    WP-23's :class:`~apps.api.auth.SessionAuthentication` takes a *service*,
    and its own docstring says why one must not be constructed at composition
    time: it would hold an application-scoped database session shared by every
    concurrent request in the worker.

    This subclass closes that gap by resolving the service from the current
    request scope at the moment ``resolve`` is called. The result is that the
    session validating a cookie is the same session the rest of that request
    writes through - which is what makes the login audit append and the
    session row one transaction.
    """

    def __init__(self, composition: Any) -> None:
        from apps.api.auth import SessionAuthentication

        self._composition = composition
        # Delegation rather than inheritance-with-a-mutable-field: the base
        # class stores its service on the instance, and an instance shared by
        # every request must not have per-request state written onto it.
        self._make = SessionAuthentication

    @property
    def mode(self) -> Any:
        from apps.api.security import AuthMode
        return AuthMode.SESSION

    @property
    def configured(self) -> bool:
        return self._composition is not None

    def resolve(self, credential: Optional[str]) -> Any:
        from pgx.deployment.composition import current_scope

        scope = current_scope()
        return self._make(scope.authentication_service()).resolve(credential)


def _probe_database(composition: Any) -> Tuple[bool, str]:
    """One trivial statement against the configured engine.

    Bounded by the engine's own connect timeout rather than by a timer here:
    a probe that raced a connection attempt would report failure while the
    connection was still being made, and the next probe would report success,
    which is how a readiness endpoint starts flapping.
    """
    try:
        from sqlalchemy import text

        with composition.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, "ok"
    except ImportError:
        return False, "driver_missing"
    except Exception:  # noqa: BLE001 - the reason is a key, never a message
        return False, "database_unreachable"


def _probe_migrations(composition: Any, expected_head: Optional[str]
                      ) -> Tuple[bool, str]:
    """Compare the database's Alembic head with the one this build expects.

    Reads ``alembic_version`` directly instead of importing Alembic: a health
    check that imported a migration framework would load every revision module
    on every probe, and a broken revision file would then take readiness down
    for a reason that has nothing to do with the database.
    """
    try:
        from sqlalchemy import text

        with composition.engine.connect() as connection:
            rows = list(connection.execute(
                text("SELECT version_num FROM alembic_version")).scalars())
    except Exception:  # noqa: BLE001
        return False, "migrations_unknown"
    if len(rows) != 1:
        # Zero means no migration has run. More than one means a branched
        # history was stamped, and "which head are we at" has no answer.
        return False, "migrations_unknown"
    if expected_head and rows[0] != expected_head:
        return False, "migrations_behind"
    return True, "ok"


def _probe_password_hashing() -> Tuple[bool, str]:
    from pgx.security.passwords import argon2_available

    return (True, "ok") if argon2_available() else (False, "argon2_missing")


def _probe_session_store(composition: Any) -> Tuple[bool, str]:
    """Whether a session row can actually be looked up.

    Deliberately a *query*, not a check that a class was imported. The store
    being composed is what WP-23's provider already reports; what readiness
    adds is that the table this deployment would read is there.
    """
    try:
        from sqlalchemy import text

        with composition.engine.connect() as connection:
            connection.execute(
                text("SELECT 1 FROM security_sessions LIMIT 1"))
        return True, "ok"
    except Exception:  # noqa: BLE001
        return False, "session_store_missing"


def _probe_governed_audit(composition: Any) -> Tuple[bool, str]:
    """The audit stream must exist and must have exactly one head row.

    Two head rows would mean two chains. Verifying either would succeed, and
    the verification would say nothing about the other - so this is checked
    where an operator will see it rather than discovered during an audit.
    """
    try:
        from sqlalchemy import text

        with composition.engine.connect() as connection:
            heads = list(connection.execute(
                text("SELECT stream_id FROM governed_audit_stream_head")
            ).scalars())
    except Exception:  # noqa: BLE001
        return False, "audit_sink_missing"
    return (True, "ok") if len(heads) == 1 else (False, "audit_sink_missing")


def _probe_rate_limiter(composition: Any) -> Tuple[bool, str]:
    try:
        from sqlalchemy import text

        with composition.engine.connect() as connection:
            connection.execute(
                text("SELECT 1 FROM security_rate_limit_counters LIMIT 1"))
        return True, "ok"
    except Exception:  # noqa: BLE001
        return False, "rate_limiter_missing"


def build_deployment_probes(composition: Any, *,
                            expected_head: Optional[str] = None,
                            existing: Optional[ReadinessProbes] = None
                            ) -> ReadinessProbes:
    """Real probes over a real engine.

    ``existing`` carries through anything already supplied - the active
    release and evidence build probes belong to WP-03 and WP-08 and are not
    this module's to invent.
    """
    base = existing or ReadinessProbes()
    return ReadinessProbes(
        database=lambda: _probe_database(composition),
        migrations=lambda: _probe_migrations(composition, expected_head),
        active_release=base.active_release,
        evidence_build=base.evidence_build,
        session_store=lambda: _probe_session_store(composition),
        password_hashing=_probe_password_hashing,
        governed_audit=lambda: _probe_governed_audit(composition),
        rate_limiter=lambda: _probe_rate_limiter(composition),
    )


class RequestScopeMiddleware:
    """Open one request scope per request and close it afterwards.

    Raw ASGI rather than ``BaseHTTPMiddleware``: the latter runs the handler
    in a separate task, and a ``ContextVar`` set in the middleware's task is
    then not visible in the handler's. That failure is silent - every
    capability raises "outside a request scope" - and it is exactly the kind
    of thing that works in a unit test and not under a server.
    """

    def __init__(self, app: Any, composition: Any) -> None:
        self.app = app
        self._composition = composition

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        with self._composition.request_scope():
            await self.app(scope, receive, send)


def build_deployment_provider(
        settings: ApiSettings, composition: Any, *,
        base: Optional[ServiceProvider] = None) -> ServiceProvider:
    """A provider carrying every capability this composition actually built.

    The principal resolver is chosen from what was composed, never from the
    configured mode alone: a deployment that names ``SESSION`` but composed
    nothing gets :class:`UnconfiguredAuthentication`, so its authenticated
    routes answer 503 rather than 401. The difference matters to whoever is
    paged - 401 says the caller is wrong, 503 says the deployment is.
    """
    from dataclasses import replace

    capabilities = dict(composition.capabilities())
    principals: Any
    if composition is not None:
        principals = RequestScopedSessionAuthentication(composition)
    else:  # pragma: no cover - callers pass a composition
        principals = UnconfiguredAuthentication()

    provider = base or ServiceProvider(settings=settings)
    return replace(
        provider,
        settings=settings,
        principals=principals,
        authentication_service=capabilities["authentication_service"],
        csrf_service=capabilities["csrf_service"],
        rate_limiter=capabilities["rate_limiter"],
        audit_sink=capabilities["audit_sink"],
        audit_reader=capabilities["audit_reader"],
        user_administration=capabilities["user_administration"],
        readiness_probes=build_deployment_probes(
            composition,
            expected_head=settings.expected_migration_head or None,
            existing=provider.readiness_probes),
    )
