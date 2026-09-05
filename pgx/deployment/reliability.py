# -*- coding: utf-8 -*-
"""Failure drills (WP-24).

A reliability report that lists the failures a system survived is only worth
reading if somebody caused those failures on purpose. So this module is a
*catalogue* of named drills, each with the behaviour it expects, and a runner
that records what actually happened - including "this drill was not run", which
is the honest answer for most of them in a repository with no deployment.

Two of the expectations are worth stating outright, because they are the ones
that get inverted in practice:

**A database outage must not affect liveness.** Liveness answers whether the
process is alive; readiness answers whether it should receive traffic. A
liveness probe that consulted PostgreSQL would have an orchestrator kill every
replica during a failover that was about to resolve itself, turning a thirty-
second blip into an outage.

**An external source or model outage must not affect P0 at all.** ClinPGx and
any LLM are ingestion-time and P1 concerns. If either could move a readiness
component, the deterministic offline demo that P0's Definition of Done
requires would depend on the internet.

The drills that can be run without a deployment are run here. The rest report
``BLOCKED`` with the environment they need, and none of them reports a
fixture's behaviour as a deployment's.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Sequence, Tuple

from pgx.deployment.vocabulary import (REHEARSAL_LABEL,
                                       DeploymentEnvironmentKind,
                                       ExecutionState, blocker)

__all__ = [
    "RELIABILITY_DRILLS",
    "RELIABILITY_RESULT_VERSION",
    "ReliabilityDrill",
    "drill_catalogue",
    "run_drills",
]

RELIABILITY_RESULT_VERSION = "pgx-wp24-reliability-drill/1"


@dataclass(frozen=True)
class ReliabilityDrill:
    """One named failure and the behaviour it must produce."""

    drill_id: str
    title: str
    #: What is deliberately broken.
    injected_failure: str
    #: What must happen. Written as a claim that can be false.
    expected_behaviour: str
    #: What must be running for this drill to mean anything.
    requires: Tuple[str, ...]
    #: True when the drill can be performed in-process, with no deployment.
    #: These are the ones that run everywhere, including in CI, and they are
    #: the reason the catalogue is not simply a list of things nobody did.
    runnable_in_process: bool = False


RELIABILITY_DRILLS: Tuple[ReliabilityDrill, ...] = (
    ReliabilityDrill(
        "REL-001", "Liveness while PostgreSQL is unavailable",
        "the database is stopped or unreachable",
        "liveness answers 200; the process is alive and an orchestrator must "
        "not restart it for a dependency's outage",
        ("a running application",), runnable_in_process=True),
    ReliabilityDrill(
        "REL-002", "Readiness while PostgreSQL is unavailable",
        "the database is stopped or unreachable",
        "readiness answers NOT_READY and names the database component, so "
        "traffic stops without the process being killed",
        ("a running application",), runnable_in_process=True),
    ReliabilityDrill(
        "REL-003", "Readiness with a migration mismatch",
        "the database is at a revision other than the expected head",
        "readiness answers NOT_READY and names migrations; it must not serve "
        "an assessment against a schema the build was not written for",
        ("a running application", "a PostgreSQL server"),
        runnable_in_process=True),
    ReliabilityDrill(
        "REL-004", "Readiness with no active release",
        "no release is registered or activated",
        "readiness answers NOT_READY and names active_release; no assessment "
        "is performed, because an assessment with no pinned release has "
        "nothing to be traceable to",
        ("a running application",), runnable_in_process=True),
    ReliabilityDrill(
        "REL-005", "External source and model outage",
        "ClinPGx and any LLM endpoint are unreachable",
        "liveness and readiness are unaffected and no P0 capability degrades; "
        "neither is a P0 readiness component and neither may become one",
        (), runnable_in_process=True),
    ReliabilityDrill(
        "REL-006", "Application restart with a persistent database",
        "the application container is stopped and started",
        "the database volume survives, sessions created before the restart "
        "remain valid until their own expiry, and the audit chain verifies "
        "across the restart",
        ("a container runtime", "a PostgreSQL server")),
    ReliabilityDrill(
        "REL-007", "Graceful stop",
        "SIGTERM is delivered to the application",
        "in-flight requests complete within the grace period and the "
        "connection pool is disposed; a pool left open holds connections "
        "PostgreSQL will not free until they time out",
        ("a container runtime",)),
    ReliabilityDrill(
        "REL-008", "Audit chain verification",
        "the governed audit chain is verified against stored rows",
        "the chain verifies, and a chain that does not is reported with the "
        "first broken sequence and no event content",
        ("a PostgreSQL server", "at least one governed audit event")),
    ReliabilityDrill(
        "REL-009", "Rate-limit backend failure",
        "the rate-limit store is unreachable",
        "login and governed mutations are refused with RATE_LIMIT_UNAVAILABLE; "
        "the limiter fails closed, because an unmetered login path is exactly "
        "what the limiter exists to prevent",
        (), runnable_in_process=True),
    ReliabilityDrill(
        "REL-010", "Missing sealed runtime artifact",
        "a runtime asset named by the manifest is removed",
        "the affected page reports the artifact unavailable and no partial "
        "assessment is produced; a refusal, never a partial answer",
        (), runnable_in_process=True),
    ReliabilityDrill(
        "REL-011", "Governed audit append failure",
        "the audit sink raises during a governed mutation",
        "the governed change is rolled back; a change nobody can account for "
        "is worse than a refusal, because the refusal tells the operator "
        "something",
        (), runnable_in_process=True),
    ReliabilityDrill(
        "REL-012", "Image rollback to the previous build",
        "the candidate image is replaced with the previous one",
        "both image identities are recorded, the rollback happens without a "
        "database downgrade, and post-rollback liveness and readiness are "
        "observed",
        ("a container runtime", "two built images")),
    ReliabilityDrill(
        "REL-013", "Backup and restore verification",
        "a backup is taken and restored into a separate database",
        "all four runbook conditions hold: a separate target, the exact "
        "Alembic head, a verified audit chain whose count matches the "
        "separately exported head sequence, and every referenced release "
        "manifest hash resolving against restored manifests",
        ("a PostgreSQL server", "a separate restore target")),
)


def drill_catalogue() -> Mapping[str, object]:
    """The declared drills. Published before any of them is run.

    Declared first for the same reason the performance targets are: a
    catalogue written after the results is a list of the things that happened
    to work.
    """
    return {
        "reliability_drill_version": RELIABILITY_RESULT_VERSION,
        "drill_count": len(RELIABILITY_DRILLS),
        "drills": [
            {"drill_id": drill.drill_id, "title": drill.title,
             "injected_failure": drill.injected_failure,
             "expected_behaviour": drill.expected_behaviour,
             "requires": list(drill.requires),
             "runnable_in_process": drill.runnable_in_process}
            for drill in RELIABILITY_DRILLS],
        "note": (
            "Declared before execution. A drill catalogue written after the "
            "results is a list of the failures that happened to be survived."),
    }


def run_drills(runners: Optional[Mapping[str, Callable[[], Tuple[bool, str]]]]
               = None, *,
               environment: DeploymentEnvironmentKind =
               DeploymentEnvironmentKind.LOCAL_REHEARSAL,
               now: Optional[_dt.datetime] = None) -> Mapping[str, object]:
    """Execute the drills a runner was supplied for; report the rest as
    blocked.

    ``runners`` maps ``drill_id`` to a callable returning
    ``(behaved_as_expected, detail)``. A drill with no runner is *not* a
    failure and is *not* a pass - it is ``BLOCKED``, with the environment it
    needs named.
    """
    supplied = dict(runners or {})
    results = []
    executed = 0
    failed = 0
    for drill in RELIABILITY_DRILLS:
        runner = supplied.get(drill.drill_id)
        if runner is None:
            results.append({
                "drill_id": drill.drill_id, "title": drill.title,
                "state": ExecutionState.BLOCKED.value,
                "behaved_as_expected": None,
                "detail": "no runner was supplied for this drill",
                "requires": list(drill.requires),
            })
            continue
        try:
            behaved, detail = runner()
        except Exception as error:  # noqa: BLE001 - a drill may fail loudly
            behaved, detail = False, type(error).__name__
        executed += 1
        if not behaved:
            failed += 1
        results.append({
            "drill_id": drill.drill_id, "title": drill.title,
            "state": (ExecutionState.VERIFIED.value if behaved
                      else ExecutionState.EXECUTED.value),
            "behaved_as_expected": behaved,
            "detail": detail,
            "requires": list(drill.requires),
        })
    label = (REHEARSAL_LABEL
             if environment is DeploymentEnvironmentKind.LOCAL_REHEARSAL
             else None)
    overall = (ExecutionState.BLOCKED if executed == 0
               else ExecutionState.VERIFIED if failed == 0
               else ExecutionState.EXECUTED)
    blockers = []
    if executed < len(RELIABILITY_DRILLS):
        blockers.append(dict(blocker(
            "DEPLOY_STAGING_NOT_DEPLOYED",
            owner="WP-24 operation on a host with a container runtime",
            detail=("%d of %d drills were not run because the environment "
                    "they need is absent"
                    % (len(RELIABILITY_DRILLS) - executed,
                       len(RELIABILITY_DRILLS)))).to_json()))
    return {
        "reliability_drill_version": RELIABILITY_RESULT_VERSION,
        "state": overall.value,
        "environment_kind": environment.value,
        "rehearsal_label": label,
        "observed_at": (now or _dt.datetime.now(_dt.timezone.utc)).isoformat()
        if executed else None,
        "declared_count": len(RELIABILITY_DRILLS),
        "executed_count": executed,
        "failed_count": failed,
        # Null, not zero: no drill was run, so there is no rate to report.
        "passed_count": (executed - failed) if executed else None,
        "results": results,
        "blockers": blockers,
        "note": (
            "A drill with no runner is BLOCKED, never passed. The three "
            "states - verified, executed-and-wrong, and not run - need "
            "different actions from different people."),
    }
