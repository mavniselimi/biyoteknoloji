# -*- coding: utf-8 -*-
"""The real deployment composition (WP-24).

WP-23 built a security layer and composed none of it: ``apps/api/main.py``
constructed a ``ServiceProvider`` with every optional capability left ``None``.
This module is what fills them in, and the difficult part is not the wiring -
it is the transaction boundary.

Three rules, and each one is a bug that would otherwise be found in
production:

**One session per request, closed when the request ends.** A session opened at
import and shared is the classic web bug: two concurrent requests interleave
inside one transaction, and one caller's commit publishes another caller's
half-finished work. Sessions here live in a :class:`RequestScope` held in a
``ContextVar``, which is per-task by construction, and the scope closes its
session in a ``finally``.

**A governed change and its audit record share one transaction.** Not "are
both written". Share one. :meth:`RequestScope.governed_transaction` commits
only when the body completes, so an audit append that raises takes the change
it was recording down with it. A system that could record a change it did not
make - or make one it did not record - has an audit trail that answers no
question.

**A rate-limit hit does not share that transaction.** It is the one thing that
must survive the rollback: a failed login is refused, its transaction is rolled
back, and the attempt must still be counted or the limiter is off for exactly
the caller it is watching. That is why
:class:`~pgx.deployment.rate_limit_store.SqlAlchemyRateLimitStore` takes a
factory and commits for itself.

Nothing here connects at import, and nothing here runs a migration. The engine
is created lazily on first use and a migration is an operator command,
forever: an application that upgraded its own schema on start-up would apply
``0011`` from whichever replica booted first, concurrently, on a database
whose downgrade path refuses to run.
"""

from __future__ import annotations

import datetime as _dt
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional

from pgx.deployment.errors import DeploymentBlocked
from pgx.deployment.secrets import read_secret
from pgx.deployment.vocabulary import DeploymentBlocker, blocker

__all__ = [
    "CompositionResult",
    "DeploymentComposition",
    "RequestScope",
    "compose_from_environment",
    "current_scope",
]

#: The active request's scope. A ``ContextVar`` rather than a thread-local:
#: Starlette runs async endpoints as tasks in one thread, so a thread-local
#: would be shared between concurrent requests - the precise failure this is
#: chosen to prevent. Sync endpoints run in a worker thread that anyio seeds
#: with a copy of this context, so reads work there too.
_CURRENT_SCOPE: ContextVar[Optional["RequestScope"]] = ContextVar(
    "pgx_request_scope", default=None)


def current_scope() -> "RequestScope":
    """The scope for the request being handled.

    Raises rather than opening one. A capability reached outside a request has
    nothing to close its session, and an implicit scope here would leak one
    connection per call until the pool was exhausted - which presents as a
    deployment that works and then stops.
    """
    scope = _CURRENT_SCOPE.get()
    if scope is None:
        raise DeploymentBlocked(
            "DEPLOY_COMPOSITION_INCOMPLETE",
            owner="the deployment composition",
            detail=("a database-backed capability was requested outside a "
                    "request scope; nothing would close its session"))
    return scope


class RequestScope:
    """One request's database session and the services built over it.

    Every service is built at most once per scope and memoised, so the
    authentication service and the audit sink a single request uses are backed
    by the *same* session - which is what makes their writes one transaction
    rather than two that happen to succeed together.
    """

    def __init__(self, session_factory: Callable[[], Any], *,
                 hasher: Any, csrf: Any, limiter_factory: Callable[[], Any],
                 policy: Any, clock: Optional[Callable[[], _dt.datetime]]
                 = None) -> None:
        self._session_factory = session_factory
        self._session: Optional[Any] = None
        self._hasher = hasher
        self._csrf = csrf
        self._limiter_factory = limiter_factory
        self._policy = policy
        self._clock = clock
        self._cache: Dict[str, Any] = {}
        self._closed = False

    # -- session ---------------------------------------------------------

    @property
    def session(self) -> Any:
        """Opened on first use, so a request that touches no capability that
        needs a database never takes a connection from the pool."""
        if self._closed:
            raise RuntimeError(
                "this request scope is closed; a capability used after the "
                "response was sent would write outside the request it "
                "belongs to")
        if self._session is None:
            self._session = self._session_factory()
        return self._session

    @property
    def session_opened(self) -> bool:
        return self._session is not None

    def close(self) -> None:
        """Roll back anything uncommitted, then close. Idempotent.

        The rollback is not defensive tidiness: a session returned to the pool
        with an open transaction holds locks the next borrower will wait on.
        """
        self._closed = True
        session = self._session
        self._session = None
        self._cache.clear()
        if session is None:
            return
        try:
            session.rollback()
        finally:
            session.close()

    @contextmanager
    def governed_transaction(self) -> Iterator[Any]:
        """Commit the body as one transaction, or none of it.

        The governed change and the canonical audit append both write through
        ``self.session``, so the commit at the end is the only commit either
        of them gets. An audit append that raises leaves this block by the
        exception path, the rollback runs, and the change is not there.
        """
        session = self.session
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise

    # -- capabilities ----------------------------------------------------

    def _memo(self, key: str, build: Callable[[], Any]) -> Any:
        if key not in self._cache:
            self._cache[key] = build()
        return self._cache[key]

    def user_store(self) -> Any:
        from pgx.deployment.stores import SqlAlchemyUserStore
        return self._memo("users",
                          lambda: SqlAlchemyUserStore(self.session))

    def session_store(self) -> Any:
        from pgx.deployment.stores import SqlAlchemySessionStore
        return self._memo("sessions",
                          lambda: SqlAlchemySessionStore(self.session))

    def audit_store(self) -> Any:
        from pgx.deployment.stores import SqlAlchemyAuditStore
        return self._memo("audit_store",
                          lambda: SqlAlchemyAuditStore(self.session))

    def audit_service(self) -> Any:
        from pgx.infrastructure.audit.service import GovernedAuditService
        return self._memo(
            "audit_service",
            lambda: GovernedAuditService(self.audit_store(),
                                         clock=self._clock))

    def audit_reader(self) -> Any:
        return self.audit_store()

    def rate_limiter(self) -> Any:
        """Built per scope, backed by its own transaction. See the module
        docstring for why that one is not this scope's."""
        return self._memo("limiter", self._limiter_factory)

    def authentication_service(self) -> Any:
        from pgx.security.service import AuthenticationService
        return self._memo("auth", lambda: AuthenticationService(
            users=self.user_store(),
            sessions=self.session_store(),
            hasher=self._hasher,
            audit=self.audit_service(),
            policy=self._policy,
            limiter=self.rate_limiter(),
            clock=self._clock))

    def user_administration(self) -> Any:
        """Administration is the user store plus the audit service.

        Returned as a pair rather than a facade: WP-23's ``pgx-auth`` owns the
        administration *rules*, and a second implementation of them here would
        be a second place for the "no default password" rule to be wrong.
        """
        return {"users": self.user_store(),
                "audit": self.audit_service(),
                "hasher": self._hasher}

    @property
    def csrf_service(self) -> Any:
        return self._csrf


class CompositionResult:
    """What composition produced, and what it could not.

    ``composed`` is derived from objects that were actually built. It is
    deliberately not a reading of an environment variable: a deployment can
    set ``PGX_API_AUTH_MODE=SESSION`` with no database, no driver and no
    Argon2, and a status derived from that variable would report a
    configuration that cannot authenticate anybody.
    """

    def __init__(self, *, composition: Optional["DeploymentComposition"],
                 blockers: List[DeploymentBlocker]) -> None:
        self.composition = composition
        self.blockers = list(blockers)

    @property
    def composed(self) -> bool:
        return self.composition is not None

    @property
    def blocker_codes(self) -> tuple:
        return tuple(sorted(item.code for item in self.blockers))

    def to_json(self) -> Mapping[str, object]:
        return {
            "composed": self.composed,
            "blockers": [dict(item.to_json()) for item in self.blockers],
            "note": (
                "composed is true only when an engine, a password hasher and "
                "a CSRF key were all built. It is never read from an "
                "environment variable, because a variable can name a "
                "configuration the host cannot provide."),
        }


class DeploymentComposition:
    """Engine, session factory and the per-request scopes over them."""

    def __init__(self, *, engine: Any, session_factory: Callable[[], Any],
                 hasher: Any, csrf: Any, policy: Any,
                 limiter_factory: Callable[[], Any],
                 clock: Optional[Callable[[], _dt.datetime]] = None) -> None:
        self._engine = engine
        self._session_factory = session_factory
        self._hasher = hasher
        self._csrf = csrf
        self._policy = policy
        self._limiter_factory = limiter_factory
        self._clock = clock

    @property
    def engine(self) -> Any:
        return self._engine

    @property
    def csrf_service(self) -> Any:
        return self._csrf

    def new_scope(self) -> RequestScope:
        return RequestScope(self._session_factory, hasher=self._hasher,
                            csrf=self._csrf,
                            limiter_factory=self._limiter_factory,
                            policy=self._policy, clock=self._clock)

    @contextmanager
    def request_scope(self) -> Iterator[RequestScope]:
        """Enter a scope, publish it, and close it whatever happens.

        The token-based reset is what makes nesting safe and what makes a
        forgotten scope impossible: the previous value is restored even when
        the body raises, so one request cannot leave its scope visible to the
        next task that runs on this context.
        """
        scope = self.new_scope()
        token = _CURRENT_SCOPE.set(scope)
        try:
            yield scope
        finally:
            _CURRENT_SCOPE.reset(token)
            scope.close()

    def dispose(self) -> None:
        """Release the pool. Called on application shutdown.

        Without this, a container that stops gracefully leaves PostgreSQL
        holding connections until they time out, which shows up as a restart
        that cannot reconnect because the pool is full of its own ghosts.
        """
        disposer = getattr(self._engine, "dispose", None)
        if callable(disposer):
            disposer()

    # -- the ServiceProvider capability set -------------------------------

    def capabilities(self) -> Mapping[str, Any]:
        """The factories ``ServiceProvider`` takes.

        Each reads the *current* scope, so the object a route receives is
        bound to that route's request and to no other. Passing a service
        instance here instead would hand every request the same session.
        """
        return {
            "authentication_service":
                lambda: current_scope().authentication_service(),
            "csrf_service": self._csrf,
            "rate_limiter": lambda: current_scope().rate_limiter(),
            "audit_sink": lambda: current_scope().audit_service(),
            "audit_reader": lambda: current_scope().audit_reader(),
            "user_administration":
                lambda: current_scope().user_administration(),
        }


def compose_from_environment(
        environ: Optional[Mapping[str, str]] = None,
        *, clock: Optional[Callable[[], _dt.datetime]] = None,
        engine_factory: Optional[Callable[..., Any]] = None,
) -> CompositionResult:
    """Build the deployment composition, or say exactly what is missing.

    Returns a result rather than raising, because "this deployment has no
    database" is a state the application must be able to start in and report -
    the readiness endpoint is how an operator learns it, and an application
    that refused to boot could not serve that endpoint.

    No connection is opened here. Reachability is a readiness probe's
    question; composition's question is whether the pieces exist.
    """
    blockers: List[DeploymentBlocker] = []

    # 1. Argon2. First, because there is no point composing an authentication
    #    service that cannot hash a password, and because the failure must be
    #    this one rather than a weaker algorithm.
    hasher = None
    try:
        from pgx.security.passwords import (Argon2PasswordHasher,
                                            argon2_available,
                                            argon2_unavailable_reason)
        if argon2_available():
            hasher = Argon2PasswordHasher()
        else:
            blockers.append(blocker(
                "DEPLOY_ARGON2_UNAVAILABLE",
                owner="the image build",
                detail=argon2_unavailable_reason()))
    except Exception as error:  # noqa: BLE001 - report, never substitute
        blockers.append(blocker("DEPLOY_ARGON2_UNAVAILABLE",
                                owner="the image build",
                                detail=type(error).__name__))

    # 2. The database URL, from its file mount or its variable.
    database_url = None
    try:
        material = read_secret("DATABASE_URL", environ=environ)
        if material is not None:
            database_url = material.value
    except Exception as error:  # noqa: BLE001 - the message names no value
        blockers.append(blocker("DEPLOY_DATABASE_UNAVAILABLE",
                                owner="the deployment configuration",
                                detail=str(error)))
    else:
        if database_url is None:
            blockers.append(blocker(
                "DEPLOY_DATABASE_UNAVAILABLE",
                owner="the deployment configuration",
                detail=("neither DATABASE_URL nor DATABASE_URL_FILE is set, "
                        "so no engine can be created")))

    # 3. The optional deployment CSRF key.
    #
    # Read, validated if present, and *not* required - which is a statement
    # about WP-23's design rather than a relaxation. Its CSRF tokens are keyed
    # per session from ``SessionRecord.csrf_secret``, and the login form is
    # keyed from the short-lived ``__Host-pgx_preauth`` cookie the server just
    # set. Neither derives from a deployment-wide key, so requiring one here
    # would add a secret to rotate, mount and leak that nothing verifies.
    #
    # It stays a declared variable because an operator who mounts it should
    # get a clear answer rather than silence, and because an ambiguous
    # ``PGX_CSRF_SECRET`` alongside ``PGX_CSRF_SECRET_FILE`` is still a
    # configuration mistake worth refusing.
    try:
        read_secret("PGX_CSRF_SECRET", environ=environ)
    except Exception as error:  # noqa: BLE001
        blockers.append(blocker("DEPLOY_COMPOSITION_INCOMPLETE",
                                owner="the deployment configuration",
                                detail=str(error)))

    if blockers:
        return CompositionResult(composition=None, blockers=blockers)

    # 4. Engine and session factory. Created, not connected.
    from pgx.infrastructure.db.config import load_database_config
    from pgx.infrastructure.db.session import (create_database_engine,
                                               create_session_factory)

    config = load_database_config(
        {"DATABASE_URL": database_url} if environ is None
        else {**dict(environ), "DATABASE_URL": database_url})
    factory = engine_factory or create_database_engine
    engine = factory(config)
    session_factory = create_session_factory(engine)

    from pgx.deployment.rate_limit_store import SqlAlchemyRateLimitStore
    from pgx.security.csrf import SessionBoundCsrf
    from pgx.security.rate_limit import RateLimiter
    from pgx.security.sessions import SessionPolicy

    limiter_store = SqlAlchemyRateLimitStore(session_factory)

    return CompositionResult(
        composition=DeploymentComposition(
            engine=engine,
            session_factory=session_factory,
            hasher=hasher,
            csrf=SessionBoundCsrf(),
            policy=SessionPolicy(),
            limiter_factory=lambda: RateLimiter(store=limiter_store,
                                                clock=clock),
            clock=clock),
        blockers=[])
