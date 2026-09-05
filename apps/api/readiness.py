"""Whether every blocking dependency is ready, component by component.

Liveness and readiness answer two different questions and this module answers
only the second. ``/health/live`` asks whether the process can serve; it stays
200 while every dependency here is down, because restarting a working process
does not fix a database. ``/health/ready`` asks whether this instance should
receive traffic, and it is 200 only when every blocking component is ready.

Four properties are enforced here rather than left to each probe.

**Independent.** Every component is probed on its own and reported on its own.
A readiness response that collapsed to one boolean would tell an operator that
something is wrong and nothing about what, which is the state in which people
restart processes at random.

**Bounded.** Each probe is given a deadline and every exception it can raise is
caught. A readiness endpoint that can hang is one an orchestrator cannot act
on, and a readiness endpoint that can 500 is one that reports "unknown" as
"broken in an unrelated way".

**Silent about specifics.** ``detail`` is chosen from :data:`DETAILS`, a fixed
catalogue of controlled strings. Never a DSN, never a path, never a hostname,
never ``str(exception)``. An unauthenticated caller can read this endpoint, so
everything in it is written as though a stranger will.

**Read-only.** No probe writes, migrates, activates or assesses. In
particular, executing an assessment as a health check would create a real
stored assessment on a schedule, from a synthetic input, in the same table
real ones live in - and the count of real assessments is something this
project has to be able to state honestly.

External sources are not components. ClinPGx, any network dependency and any
model provider are deliberately absent from this list: P0 readiness must not
depend on a third party's availability, and a probe that reached one would
make an outage elsewhere look like an outage here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from apps.api.contracts.spec import CONTRACT_VERSION

__all__ = [
    "BLOCKING_COMPONENTS",
    "ComponentResult",
    "DETAILS",
    "ReadinessProbes",
    "evaluate_readiness",
    "liveness_document",
]

#: Every controlled phrase a readiness response may contain.
#:
#: A fixed catalogue rather than formatted messages: formatting is how a
#: hostname, a path or a driver's exception text ends up in a public response,
#: and every one of these has been read as though by a stranger.
DETAILS: Mapping[str, str] = {
    "ok": "Ready.",
    "not_checked": "Not checked in this deployment.",
    "config_invalid": "Application configuration is incomplete or refused.",
    "database_not_configured": "No database connection is configured.",
    # WP-23. One controlled string per security dependency. A probe cannot
    # invent a message, so a probe cannot leak one - and an unauthenticated
    # caller can read this endpoint.
    "session_store_missing": "No server-side session store is composed, so "
                             "no session can be created or validated.",
    "argon2_missing": "Argon2id password hashing is unavailable, and there "
                      "is no weaker algorithm to fall back to.",
    "audit_sink_missing": "No canonical governed audit sink is composed, so "
                          "no governed state change may proceed.",
    "audit_chain_unverified": "The governed audit chain has not been "
                              "verified in this deployment.",
    "rate_limiter_missing": "No rate-limit backend is composed; login and "
                            "governed mutations fail closed.",
    "database_unreachable": "The database did not answer within the probe "
                            "budget.",
    "driver_missing": "The database driver is not installed in this "
                      "deployment.",
    "migrations_behind": "The database schema is not at the revision this "
                         "build expects.",
    "migrations_unknown": "The schema revision could not be determined.",
    "release_missing": "No active release is registered.",
    "release_invalid": "The active release did not verify against its "
                       "recorded hashes.",
    "claim_boundary_not_approved": "The claim boundary has not been approved "
                                   "by the named human and scientific "
                                   "reviewers. This is a governance gate, not "
                                   "a fault.",
    "auth_not_configured": "No authentication provider is configured.",
    "auth_not_permitted": "The configured authentication provider is not "
                          "permitted in this environment.",
    "composition_incomplete": "A service this environment requires is not "
                              "configured.",
    "evidence_build_missing": "No evidence build is configured, so evidence "
                              "records cannot be read.",
    "probe_failed": "The check did not complete.",
}

#: The components that must all be ready for this instance to serve. Named in
#: §14 of the work package; listed here so the response, the documentation and
#: the tests read one list.
BLOCKING_COMPONENTS: Tuple[str, ...] = (
    "configuration",
    "database",
    "migrations",
    "active_release",
    "claim_boundary",
    "authentication",
    "service_composition",
)

#: Reported, and does not block. The evidence endpoint needs it; an assessment
#: does not, because an assessment reads evidence through the pinned release.
ADVISORY_COMPONENTS: Tuple[str, ...] = ("evidence_build",)


@dataclass(frozen=True, slots=True)
class ComponentResult:
    """One component's answer: ready or not, blocking or not, and one phrase."""

    component: str
    ready: bool
    blocking: bool
    detail: str

    def to_json(self) -> Dict[str, Any]:
        return {"component": self.component, "ready": self.ready,
                "blocking": self.blocking, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class ReadinessProbes:
    """The capability each component check needs, injected.

    Probes are supplied rather than imported so that this module can be tested
    exhaustively without a database, and so that a deployment that has no
    migration story yet reports ``migrations_unknown`` instead of importing
    Alembic at health-check time.

    Each probe returns ``(ready, detail_key)``. Returning a *key* rather than a
    message is what keeps :data:`DETAILS` the only source of response text: a
    probe cannot invent a string, so a probe cannot leak one.
    """

    database: Optional[Callable[[], Tuple[bool, str]]] = None
    migrations: Optional[Callable[[], Tuple[bool, str]]] = None
    active_release: Optional[Callable[[], Tuple[bool, str]]] = None
    evidence_build: Optional[Callable[[], Tuple[bool, str]]] = None
    #: WP-23. Each is blocking for authenticated routes and each reports
    #: separately, because "authentication is implemented" and "this
    #: deployment can authenticate somebody" are different facts and a single
    #: boolean covering both would read as the second while meaning the first.
    session_store: Optional[Callable[[], Tuple[bool, str]]] = None
    password_hashing: Optional[Callable[[], Tuple[bool, str]]] = None
    governed_audit: Optional[Callable[[], Tuple[bool, str]]] = None
    rate_limiter: Optional[Callable[[], Tuple[bool, str]]] = None


def _detail(key: str) -> str:
    return DETAILS.get(key, DETAILS["probe_failed"])


def _run(probe: Optional[Callable[[], Tuple[bool, str]]], *,
         component: str, blocking: bool, deadline: float,
         missing_key: str) -> ComponentResult:
    """Run one probe inside the budget, or report why it did not answer.

    Every exception is caught, including ``ImportError`` - which is the honest
    answer in a deployment where the driver was never installed, and is far
    more useful than a 500 that says the readiness endpoint itself is broken.
    """
    if probe is None:
        return ComponentResult(component, False, blocking, _detail(missing_key))
    if time.monotonic() > deadline:
        return ComponentResult(component, False, blocking,
                               _detail("probe_failed"))
    try:
        ready, key = probe()
    except ImportError:
        return ComponentResult(component, False, blocking,
                               _detail("driver_missing"))
    except Exception:  # noqa: BLE001 - a probe never propagates
        return ComponentResult(component, False, blocking,
                               _detail("probe_failed"))
    return ComponentResult(component, bool(ready), blocking, _detail(key))


def _configuration_result(settings: Any) -> ComponentResult:
    ready = settings is not None
    return ComponentResult("configuration", ready, True,
                           _detail("ok" if ready else "config_invalid"))


def _claim_boundary_result(claim_boundary: Any) -> ComponentResult:
    """The governance gate, reported as a gate.

    An unapproved claim boundary is the expected state of this repository, and
    reporting it as not-ready is correct: the product must not answer clinical
    questions before named humans have approved that it may. The detail says
    so in words, because an operator who reads "not ready" and starts checking
    the database will not find anything wrong with it.
    """
    approved = bool(getattr(claim_boundary, "is_approved", False))
    return ComponentResult("claim_boundary", approved, True,
                           _detail("ok" if approved
                                   else "claim_boundary_not_approved"))


def _authentication_result(settings: Any) -> ComponentResult:
    """Whether a principal can be established at all.

    Not configured is not ready. That is the fail-closed default and it is
    deliberate: a deployment with no authentication provider must not serve
    authenticated routes, and must not be rescued by defaulting to a demo
    principal.
    """
    from apps.api.security import AuthMode

    mode = getattr(settings, "auth_mode", AuthMode.UNCONFIGURED)
    if mode is AuthMode.UNCONFIGURED:
        return ComponentResult("authentication", False, True,
                               _detail("auth_not_configured"))
    if mode is AuthMode.STATIC_TOKEN and \
            getattr(settings.environment, "is_production", False):
        # Unreachable through load_settings, which refuses this combination.
        # Kept because readiness is also reachable with a hand-built settings
        # object, and a check that exists only in the constructor is a check
        # that a test double can walk around.
        return ComponentResult("authentication", False, True,
                               _detail("auth_not_permitted"))
    return ComponentResult("authentication", True, True, _detail("ok"))


def _composition_result(settings: Any,
                        results: Sequence[ComponentResult]) -> ComponentResult:
    """Whether this environment has everything it requires configured.

    Distinct from the individual components: each of those says whether one
    dependency answered, and this says whether the *set* a production
    deployment needs is present. A staging instance missing an evidence build
    is fine; a production instance missing a database is not, even in the
    moment before the database probe has failed.
    """
    required = ("configuration", "database", "active_release",
                "authentication")
    by_name = {item.component: item for item in results}
    missing = [name for name in required
               if not getattr(by_name.get(name), "ready", False)]
    if not getattr(settings, "database_url_configured", False):
        missing.append("database_url")
    ready = not missing
    return ComponentResult("service_composition", ready, True,
                           _detail("ok" if ready else "composition_incomplete"))


def evaluate_readiness(settings: Any, *, claim_boundary: Any,
                       probes: Optional[ReadinessProbes] = None,
                       budget_seconds: Optional[float] = None
                       ) -> Dict[str, Any]:
    """Probe every component once and report the result.

    Returns:
        A ``ReadinessResponse`` document. ``status`` is ``READY`` only when
        every blocking component is ready; the caller maps that to 200 and
        anything else to 503.
    """
    probes = probes or ReadinessProbes()
    budget = (budget_seconds if budget_seconds is not None
              else float(getattr(settings, "readiness_timeout_seconds", 2.0)))
    deadline = time.monotonic() + budget

    results: List[ComponentResult] = [_configuration_result(settings)]
    results.append(_run(probes.database, component="database", blocking=True,
                        deadline=deadline,
                        missing_key="database_not_configured"))
    results.append(_run(probes.migrations, component="migrations",
                        blocking=True, deadline=deadline,
                        missing_key="migrations_unknown"))
    results.append(_run(probes.active_release, component="active_release",
                        blocking=True, deadline=deadline,
                        missing_key="release_missing"))
    results.append(_claim_boundary_result(claim_boundary))
    results.append(_authentication_result(settings))
    results.append(_composition_result(settings, results))
    results.append(_run(probes.evidence_build, component="evidence_build",
                        blocking=False, deadline=deadline,
                        missing_key="evidence_build_missing"))
    # WP-23. Blocking, because a deployment that cannot hash a password,
    # cannot store a session, cannot record a governed act or cannot meter a
    # login is a deployment that must not serve authenticated routes. Each is
    # reported by name so an operator learns which one is missing rather than
    # that "security" is unavailable.
    results.append(_run(probes.password_hashing, component="password_hashing",
                        blocking=True, deadline=deadline,
                        missing_key="argon2_missing"))
    results.append(_run(probes.session_store, component="session_store",
                        blocking=True, deadline=deadline,
                        missing_key="session_store_missing"))
    results.append(_run(probes.governed_audit, component="governed_audit",
                        blocking=True, deadline=deadline,
                        missing_key="audit_sink_missing"))
    results.append(_run(probes.rate_limiter, component="rate_limiter",
                        blocking=True, deadline=deadline,
                        missing_key="rate_limiter_missing"))

    ordered = sorted(results, key=lambda item: item.component)
    blocking_failures = sorted(item.component for item in ordered
                               if item.blocking and not item.ready)
    return {
        "status": "READY" if not blocking_failures else "NOT_READY",
        "components": [item.to_json() for item in ordered],
        "blocking_failures": blocking_failures,
    }


def liveness_document() -> Dict[str, Any]:
    """The liveness answer.

    One field. No version, no release, no dependency and no build identity: a
    liveness probe that reported a version would be making a claim it has not
    checked, and one that reported a release would be reading the pointer -
    which is a database call, which is the thing liveness must not do.
    """
    return {"status": "LIVE"}


#: Reported by the OpenAPI description so a reader of the document learns the
#: same thing a reader of this module does.
READINESS_CONTRACT_VERSION = CONTRACT_VERSION
