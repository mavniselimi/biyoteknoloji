"""The capability container, framework-free on purpose.

Every capability the application layer may need, and none that it must have.
Factories rather than instances for anything holding a database session: a
session belongs to one request, and an application-scoped one would be shared
across concurrent requests by every worker that imported this module.

**It lives apart from the FastAPI dependency functions**, and that separation
is load-bearing rather than tidy. A provider is what *composition* produces -
and composition happens in a CLI, in a test, in the server-rendered web layer
and in an ASGI application. Keeping the container in a module that imports
FastAPI would mean none of the first three could describe what they are
composed with unless a web framework were installed. It is re-exported from
:mod:`apps.api.dependencies`, so the ASGI side is unchanged.

The missing case is where the safety content is. A caller that asked for the
assessment service and received ``None`` could easily go on to do something
reasonable-looking; instead, asking for a capability this deployment does not
have raises the typed 503 for that capability. An operator gets
``DATABASE_UNAVAILABLE`` or ``ACTIVE_RELEASE_UNAVAILABLE`` rather than a
``NoneType`` traceback, and a caller never gets a partial answer assembled
from whatever happened to be configured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from apps.api.config import ApiSettings
from apps.api.errors import NotReadyError
from apps.api.readiness import ReadinessProbes
from apps.api.security import PrincipalResolver, UnconfiguredAuthentication
from pgx.domain.claims import DEFAULT_CLAIM_BOUNDARY

__all__ = ["ServiceProvider"]


@dataclass(frozen=True, slots=True)
class ServiceProvider:
    """Every capability the API layer may need, and none that it must have.

    Factories rather than instances for anything that holds a database
    session: a session belongs to one request, and an application-scoped one
    would be shared across concurrent requests by every worker that imported
    this module.
    """

    settings: ApiSettings
    claim_boundary: Any = DEFAULT_CLAIM_BOUNDARY
    principals: PrincipalResolver = field(
        default_factory=UnconfiguredAuthentication)
    assessment_service: Optional[Callable[[], Any]] = None
    assessment_reader: Optional[Callable[[], Any]] = None
    release_resolver: Optional[Callable[[], Any]] = None
    evidence_repository: Optional[Callable[[], Any]] = None
    drug_aliases: Optional[Callable[[], Any]] = None
    #: WP-22's blind review service. ``None`` in this repository and in any
    #: deployment without a review store, and the routes answer 503 rather
    #: than constructing a service that would refuse every call anyway.
    expert_review_service: Optional[Any] = None
    #: WP-23 capabilities. Factories, not instances, for everything that holds
    #: a database session: a session belongs to one request, and an
    #: application-scoped one would be shared across every concurrent request
    #: in the worker - which for an authentication service means one caller's
    #: transaction could commit another caller's login.
    authentication_service: Optional[Callable[[], Any]] = None
    #: The CSRF service is a value rather than a factory: it holds no session
    #: and no state, and the per-request binding is supplied as an argument.
    csrf_service: Optional[Any] = None
    rate_limiter: Optional[Callable[[], Any]] = None
    audit_sink: Optional[Callable[[], Any]] = None
    audit_reader: Optional[Callable[[], Any]] = None
    user_administration: Optional[Callable[[], Any]] = None
    readiness_probes: ReadinessProbes = field(default_factory=ReadinessProbes)

    # -- capability accessors --------------------------------------------
    #
    # Each returns the capability or raises the 503 that names it. Written out
    # rather than generated so that the error code for each missing capability
    # is visible in the source next to the capability it belongs to.

    def require_assessment_service(self) -> Any:
        if self.assessment_service is None:
            raise NotReadyError("SERVICE_NOT_READY",
                                details={"components": ["assessment_service"]})
        return self.assessment_service()

    def require_assessment_reader(self) -> Any:
        if self.assessment_reader is None:
            raise NotReadyError("DATABASE_UNAVAILABLE",
                                details={"components": ["database"]})
        return self.assessment_reader()

    def require_release(self) -> Any:
        if self.release_resolver is None:
            raise NotReadyError("ACTIVE_RELEASE_UNAVAILABLE",
                                details={"components": ["active_release"]})
        pinned = self.release_resolver()
        if pinned is None:
            raise NotReadyError("ACTIVE_RELEASE_UNAVAILABLE",
                                details={"components": ["active_release"]})
        return pinned

    def require_evidence_repository(self) -> Any:
        if self.evidence_repository is None:
            raise NotReadyError("EVIDENCE_BUILD_UNAVAILABLE",
                                details={"components": ["evidence_build"]})
        return self.evidence_repository()

    def require_authentication_service(self) -> Any:
        if self.authentication_service is None:
            raise NotReadyError(
                "AUTHENTICATION_NOT_CONFIGURED",
                details={"components": ["authentication"]})
        return self.authentication_service()

    def require_rate_limiter(self) -> Any:
        """Fail closed. A governed mutation must not run unmetered because
        the limiter was never composed."""
        if self.rate_limiter is None:
            raise NotReadyError("SERVICE_NOT_READY",
                                details={"components": ["rate_limiter"]})
        return self.rate_limiter()

    def require_audit_sink(self) -> Any:
        """Fail closed. A governed state change with nowhere to record it
        must not happen: a success nobody can account for is worse than a
        refusal, because the refusal tells the operator something."""
        if self.audit_sink is None:
            raise NotReadyError("SERVICE_NOT_READY",
                                details={"components": ["governed_audit"]})
        return self.audit_sink()

    def require_audit_reader(self) -> Any:
        if self.audit_reader is None:
            raise NotReadyError("SERVICE_NOT_READY",
                                details={"components": ["governed_audit"]})
        return self.audit_reader()

    @property
    def security_capabilities(self) -> dict:
        """Which WP-23 capabilities this deployment actually composed.

        Read by the readiness and gate-status documents. Every value is a
        measurement of what was injected, never a restatement of what the
        code supports - the difference between "implemented" and "configured"
        is the whole point of the field set.
        """
        return {
            "authentication_service_composed":
                self.authentication_service is not None,
            "csrf_service_composed": self.csrf_service is not None,
            "rate_limiter_composed": self.rate_limiter is not None,
            "audit_sink_composed": self.audit_sink is not None,
            "audit_reader_composed": self.audit_reader is not None,
            "user_administration_composed":
                self.user_administration is not None,
        }

    def aliases_for_drugs(self) -> Any:
        """Approved aliases, or none. The one capability whose absence is fine.

        A catalogue without aliases is a smaller catalogue, not a wrong one,
        so this returns an empty mapping instead of refusing.
        """
        return {} if self.drug_aliases is None else self.drug_aliases()
