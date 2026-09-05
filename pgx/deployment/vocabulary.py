# -*- coding: utf-8 -*-
"""The operational vocabulary (WP-24).

Eight states, and the reason there are eight rather than two.

A boolean cannot express the difference between "the pipeline file exists",
"a provider ran it", "we watched it answer" and "we checked the answer was
right" - and those four are the entire subject of this work package. Nor can
it express "a named precondition is missing", which is the state almost
everything in this repository is actually in. Collapsing any of them into
``true``/``false`` is how a build report ends up claiming a deployment.

There is deliberately **no ``PASS``**, following WP-23's ``OperationalStatus``.
``VERIFIED`` is the only affirmative state, and it means a specific thing: the
work ran *and* its result was checked against a stated condition. A command
that merely completed reports ``EXECUTED``.

Ordering is disabled. ``OBSERVED`` is not "greater than" ``EXECUTED`` on any
scale that exists; they answer different questions, and the first thing built
on an invented scale would be ``state >= EXECUTED``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet, Mapping, Optional, Tuple

__all__ = [
    "AFFIRMATIVE_STATES",
    "DEPLOYMENT_BLOCKER_CODES",
    "DEPLOYMENT_VOCABULARY_VERSION",
    "EXIT_BLOCKED",
    "EXIT_FAILURE",
    "EXIT_SUCCESS",
    "EXIT_USAGE",
    "NON_OPERATIONAL_STATES",
    "REHEARSAL_LABEL",
    "DeploymentBlocker",
    "DeploymentEnvironmentKind",
    "ExecutionState",
    "exit_code_for",
]

DEPLOYMENT_VOCABULARY_VERSION = "pgx-wp24-deployment-vocabulary/1"

#: The label a locally rehearsed result must carry, verbatim, wherever it is
#: reported. Spelled once so a document, a CLI banner and a test cannot
#: disagree about what a rehearsal is called - and so that searching for this
#: string finds every place a rehearsal could be mistaken for a deployment.
REHEARSAL_LABEL = "LOCAL_STAGING_REHEARSAL"


class _DeploymentEnum(str, Enum):
    """String-valued and unordered, following the project convention."""

    def __str__(self) -> str:
        return self.value

    def __lt__(self, other: object) -> bool:  # pragma: no cover - guard
        raise TypeError("%s values are not ordered" % type(self).__name__)

    __gt__ = __le__ = __ge__ = __lt__


class ExecutionState(_DeploymentEnum):
    """What actually happened to one operational step."""

    #: A file, workflow, service definition or policy exists and has been
    #: reviewed. Nothing has run. This is what "we wrote the pipeline" earns.
    CONFIGURED = "CONFIGURED"
    #: It ran here, in this session, on this host, and completed. It says
    #: nothing about whether the result was correct or whether a remote
    #: environment would behave the same way.
    EXECUTED = "EXECUTED"
    #: A running system was watched answering - a health endpoint returned, a
    #: TLS handshake completed, a container reported healthy. Distinct from
    #: EXECUTED because a command completing is not a system responding.
    OBSERVED = "OBSERVED"
    #: It ran *and* its result was checked against a stated condition. The
    #: only affirmative state. A restore is VERIFIED when the four runbook
    #: conditions hold, not when ``pg_restore`` exits zero.
    VERIFIED = "VERIFIED"
    #: A named precondition is absent. Always carries an owner: the thing that
    #: would unblock it, and who supplies it.
    BLOCKED = "BLOCKED"
    #: Nothing prevented it. It simply has not been run. Kept separate from
    #: BLOCKED because "nobody ran the scanner" and "there is no scanner" are
    #: different problems with different fixes.
    NOT_EXECUTED = "NOT_EXECUTED"
    #: It ran, but against inputs that have since changed. A stale result is
    #: not a result; it is a result about a different thing.
    STALE = "STALE"
    #: The step does not apply to this configuration at all. Not a pass and
    #: not a failure - a question that was not asked.
    NOT_APPLICABLE = "NOT_APPLICABLE"
    #: It ran against deliberately labelled fixtures to prove the machinery
    #: works. Never scientific, operational, expert or THS evidence.
    TEST_ONLY_REHEARSAL = "TEST_ONLY_REHEARSAL"

    @property
    def is_affirmative(self) -> bool:
        """True only for VERIFIED.

        Not for EXECUTED, and not for OBSERVED. A gate that accepted either
        would accept "the command ran" as "the condition holds", which is the
        substitution this whole enum exists to prevent.
        """
        return self is ExecutionState.VERIFIED

    @property
    def is_evidence_of_operation(self) -> bool:
        """True when a real system did something, rehearsals excluded."""
        return self in (ExecutionState.EXECUTED, ExecutionState.OBSERVED,
                        ExecutionState.VERIFIED)

    @property
    def may_close_a_release_gate(self) -> bool:
        """Only VERIFIED may close a gate.

        ``TEST_ONLY_REHEARSAL`` is excluded explicitly rather than by falling
        through: a fixture proving the measurement math is worth recording and
        is worth nothing to a release decision.
        """
        return self is ExecutionState.VERIFIED


#: The states that may appear where a gate asks "did this hold?".
AFFIRMATIVE_STATES: FrozenSet[ExecutionState] = frozenset(
    {ExecutionState.VERIFIED})

#: Everything that is not evidence of a real operation. Named as a set so a
#: report can assert membership rather than enumerate exclusions and miss one.
NON_OPERATIONAL_STATES: FrozenSet[ExecutionState] = frozenset({
    ExecutionState.CONFIGURED,
    ExecutionState.BLOCKED,
    ExecutionState.NOT_EXECUTED,
    ExecutionState.STALE,
    ExecutionState.NOT_APPLICABLE,
    ExecutionState.TEST_ONLY_REHEARSAL,
})


class DeploymentEnvironmentKind(_DeploymentEnum):
    """Where a result came from. The field that stops a rehearsal reading as
    staging."""

    #: This machine, isolated project, throwaway containers. Never reachable
    #: from anywhere else and never presented as an environment anyone else
    #: could visit.
    LOCAL_REHEARSAL = "LOCAL_REHEARSAL"
    #: A CI provider's runner.
    CONTINUOUS_INTEGRATION = "CONTINUOUS_INTEGRATION"
    #: A real staging deployment with a real ingress and a real certificate.
    STAGING = "STAGING"
    #: Not in scope for P0 and present only so a document can say so.
    PRODUCTION = "PRODUCTION"

    @property
    def is_remote(self) -> bool:
        return self in (DeploymentEnvironmentKind.STAGING,
                        DeploymentEnvironmentKind.PRODUCTION)

    @property
    def may_be_called_staging(self) -> bool:
        """A local rehearsal may never be described as staging.

        This is the property behind acceptance A31. It is a method rather than
        a comment because a comment cannot be asserted by a test.
        """
        return self is DeploymentEnvironmentKind.STAGING


@dataclass(frozen=True)
class DeploymentBlocker:
    """One named reason an operational step did not happen.

    ``owner`` is required and is never "the team". A blocker whose owner is
    unnamed is one nobody is going to clear, and the four human blockers this
    repository carries are exactly the ones an engineering plan tends to lose.
    """

    code: str
    detail: str
    owner: str

    def __post_init__(self) -> None:
        if self.code not in DEPLOYMENT_BLOCKER_CODES:
            raise ValueError(
                "%r is not a declared WP-24 blocker code; an undeclared code "
                "is one no document can be searched for" % (self.code,))
        if not self.detail.strip():
            raise ValueError("a blocker states what is missing")
        if not self.owner.strip():
            raise ValueError(
                "a blocker names who supplies the missing thing")

    def to_json(self) -> Mapping[str, object]:
        return {"code": self.code, "detail": self.detail,
                "owner": self.owner, "blocking": True}


#: Every blocker WP-24 may report, with the reason each exists. Closed, for
#: the same reason the governed audit action list is closed: a code that can
#: be invented at the call site is a code no aggregator can enumerate.
DEPLOYMENT_BLOCKER_CODES: Mapping[str, str] = {
    # -- packaging and build ------------------------------------------------
    "DEPLOY_LOCKFILE_ABSENT":
        "no uv.lock exists, so no dependency set is pinned",
    "DEPLOY_LOCKFILE_UNVERIFIED":
        "a lockfile exists but no frozen check has confirmed it matches "
        "pyproject.toml",
    "DEPLOY_PACKAGE_INDEX_UNAVAILABLE":
        "no package index is reachable, so dependencies cannot be resolved "
        "or installed",
    "DEPLOY_BUILD_BACKEND_UNAVAILABLE":
        "the declared PEP 517 build backend is not importable here, so no "
        "wheel or sdist can be produced",
    "DEPLOY_ARGON2_UNAVAILABLE":
        "argon2-cffi is not installed, so the runtime cannot hash a password "
        "and must fail readiness rather than substitute an algorithm",
    # -- container ----------------------------------------------------------
    "DEPLOY_CONTAINER_RUNTIME_UNAVAILABLE":
        "no container runtime answered, so no image can be built or run",
    "DEPLOY_IMAGE_NOT_BUILT":
        "no image was built, so there is no digest, no scan target and no "
        "deployable artifact",
    "DEPLOY_RUNTIME_ASSET_MISSING":
        "a sealed runtime artifact named by the manifest is absent or its "
        "checksum disagrees",
    # -- database and migration --------------------------------------------
    "DEPLOY_DATABASE_UNAVAILABLE":
        "no PostgreSQL server is reachable",
    "DEPLOY_MIGRATION_NOT_EXECUTED":
        "alembic upgrade head has not been run against a server",
    "DEPLOY_MIGRATION_HEAD_MISMATCH":
        "the database head is not the head this build expects",
    # -- runtime ------------------------------------------------------------
    "DEPLOY_COMPOSITION_INCOMPLETE":
        "a required capability was not composed, so the deployment fails "
        "closed rather than serving without it",
    "DEPLOY_STAGING_NOT_DEPLOYED":
        "no staging environment exists to observe",
    "DEPLOY_TLS_NOT_OBSERVED":
        "no TLS handshake was verified against a trusted chain",
    "DEPLOY_SMOKE_NOT_EXECUTED":
        "no running deployment answered a smoke request",
    # -- CI -----------------------------------------------------------------
    "DEPLOY_CI_NOT_EXECUTED":
        "no continuous integration provider has run these workflows",
    # -- supply chain -------------------------------------------------------
    "DEPLOY_SBOM_NOT_GENERATED":
        "no software bill of materials was produced from real locked or "
        "image contents",
    "DEPLOY_VULNERABILITY_SCANNER_UNAVAILABLE":
        "no vulnerability scanner is available, so no scan result exists",
    "DEPLOY_ADVISORY_DATABASE_UNAVAILABLE":
        "no advisory database could be identified, so a scan result would "
        "not say what it was compared against",
    # -- performance --------------------------------------------------------
    "DEPLOY_NO_ELIGIBLE_RELEASE":
        "no active validated release exists to pin a measurement to",
    "DEPLOY_PERFORMANCE_NOT_EXECUTED":
        "the 1000-assessment run has not been executed against an eligible "
        "release",
    # -- reliability and recovery ------------------------------------------
    "DEPLOY_ROLLBACK_NOT_EXERCISED":
        "no rollback was performed between two real identities",
    "DEPLOY_BACKUP_NOT_EXECUTED":
        "no backup was taken to a real destination",
    "DEPLOY_RESTORE_NOT_VERIFIED":
        "no restore satisfied all four runbook conditions",
    # -- science and people -------------------------------------------------
    "DEPLOY_SAFETY_GATE_BLOCKED":
        "the WP-20 safety gate is not PASS",
    "DEPLOY_NO_HOLDOUT_EVIDENCE":
        "no authorized holdout set exists, so the release path stays closed "
        "and development fixtures may not stand in for it",
    "DEPLOY_EXPERT_REVIEW_NOT_PERFORMED":
        "no blind expert review has been completed under the approved "
        "protocol",
    "DEPLOY_CLAIM_BOUNDARY_NOT_APPROVED":
        "the claim boundary has not been approved by the named human and "
        "scientific reviewers",
    "DEPLOY_NO_REAL_USERS":
        "no account exists, because none is created by code",
}

# ---------------------------------------------------------------------------
# Process exit codes
# ---------------------------------------------------------------------------
# The same four the WP-20 and WP-23 CLIs use, for the same reason: a caller
# branches on the code, never on the output, and several commands print the
# word FAILURE while succeeding.

#: The work ran and the condition held.
EXIT_SUCCESS = 0
#: The work ran and something was wrong.
EXIT_FAILURE = 1
#: Blocked, not executed, or stale. Not a failure of the software; a statement
#: that the thing being asked about did not happen.
EXIT_BLOCKED = 2
#: The request itself was malformed - unknown target, missing argument, a
#: contract the command cannot honour.
EXIT_USAGE = 3


def exit_code_for(state: ExecutionState) -> int:
    """The process exit code one state deserves.

    ``EXECUTED`` and ``OBSERVED`` exit 0 because the command genuinely did
    what it was asked. ``TEST_ONLY_REHEARSAL`` also exits 0 - the rehearsal
    succeeded - and the *label* rather than the exit code is what keeps it out
    of a release decision. Everything else exits 2, which is why no CI step
    can treat "not executed" as green by forgetting to read a field.
    """
    if state in (ExecutionState.VERIFIED, ExecutionState.EXECUTED,
                 ExecutionState.OBSERVED,
                 ExecutionState.TEST_ONLY_REHEARSAL):
        return EXIT_SUCCESS
    return EXIT_BLOCKED


def blocker(code: str, *, owner: str,
            detail: Optional[str] = None) -> DeploymentBlocker:
    """Build a blocker, defaulting the detail to the registry's wording."""
    return DeploymentBlocker(code=code,
                             detail=detail or DEPLOYMENT_BLOCKER_CODES[code],
                             owner=owner)


def blocker_codes() -> Tuple[str, ...]:
    return tuple(sorted(DEPLOYMENT_BLOCKER_CODES))
