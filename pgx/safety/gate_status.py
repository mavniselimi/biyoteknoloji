# -*- coding: utf-8 -*-
"""The WP-20 gate status: twelve invariants, reported without collapsing.

Every field here could be folded into ``release_may_proceed``, and folding any
of them would make the document worse. The gate can be in a state where every
executable check passes, every mutant is caught, and a release still must not
proceed - because the claim boundary is unapproved, PostgreSQL was never
reached, and WP-23 owns half of SAFETY-INV-012. A single boolean cannot say
that, and a reader who saw ``false`` without the fields above it would
reasonably conclude the software is broken.

``release_may_proceed`` is therefore computed last, from the fields, and is
false whenever anything is failed, blocked, stale or unexecuted - even when
nothing is *wrong*.

Anything nobody measured is ``null``, never ``0``. WP-18's rule, kept: zero
means somebody looked and found none.
"""

from __future__ import annotations

import io
import os
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.safety.definitions import DETECTOR_EVIDENCE_DISCLAIMER
from pgx.safety.execution import SafetyExecution, summarise
from pgx.safety.freshness import compare_fingerprints, fingerprint_inputs
from pgx.safety.registry import SafetyRegistry
from pgx.safety.vocabulary import (
    ComplianceState,
    ExecutionState,
    InvariantId,
    is_release_permitting,
)

__all__ = [
    "GATE_STATUS_SCHEMA_VERSION",
    "GATE_STATUS_PATH",
    "BLOCKER_CODES",
    "build_wp20_gate_status",
    "safety_gate_state",
]

GATE_STATUS_SCHEMA_VERSION = "pgx-wp20-gate-status/1"
GATE_STATUS_PATH = "data/safety/wp20-real-gate-status.json"

#: Stable, controlled. A CI job keys on these; the wording of a detail may
#: change and the code may not.
BLOCKER_CODES: Tuple[str, ...] = (
    "SAFETY_INVARIANT_FAILED",
    "SAFETY_INVARIANT_NOT_EXECUTED",
    "SAFETY_INVARIANT_BLOCKED_BY_LATER_WP",
    "SAFETY_NEGATIVE_CONTROL_UNDETECTED",
    "SAFETY_EVIDENCE_STALE",
    "SAFETY_EVIDENCE_ABSENT",
    "SAFETY_CLAIM_BOUNDARY_NOT_APPROVED",
    "SAFETY_POSTGRESQL_NOT_EXERCISED",
    "SAFETY_NO_ACTIVE_RELEASE",
    "SAFETY_NO_HOLDOUT_CASES",
    "SAFETY_CI_JOB_NOT_EXECUTED",
    "SAFETY_CLAIM_SCANNER_KNOWN_GAPS",
)

_OWNERS: Mapping[str, str] = {
    "SAFETY_INVARIANT_FAILED": "whoever owns the failing surface",
    "SAFETY_INVARIANT_NOT_EXECUTED": "whoever runs the safety gate",
    "SAFETY_INVARIANT_BLOCKED_BY_LATER_WP": "the later work package named",
    "SAFETY_NEGATIVE_CONTROL_UNDETECTED": "whoever owns the detector",
    "SAFETY_EVIDENCE_STALE": "whoever runs the safety gate",
    "SAFETY_EVIDENCE_ABSENT": "whoever runs the safety gate",
    "SAFETY_CLAIM_BOUNDARY_NOT_APPROVED":
        "named human and scientific reviewers",
    "SAFETY_POSTGRESQL_NOT_EXERCISED":
        "deployment (start the disposable test database)",
    "SAFETY_NO_ACTIVE_RELEASE": "WP-03 operation",
    "SAFETY_NO_HOLDOUT_CASES": "scientific curators",
    "SAFETY_CI_JOB_NOT_EXECUTED": "WP-24 / a CI provider",
    "SAFETY_CLAIM_SCANNER_KNOWN_GAPS": "WP-00 claim registry reviewers",
}

_NOT_CLINICAL = (
    "This is a software safety gate. Every result in it describes software "
    "detectors and software behaviour. It is not clinical validation, "
    "scientific validation, expert review, or evidence that the system is safe "
    "for any patient. No holdout result, metric, expert opinion or human "
    "approval is asserted or implied.")


def _claim_boundary(root: str) -> Tuple[bool, str]:
    """Read the claim boundary's status line rather than asserting it."""
    path = os.path.join(root, "docs", "architecture", "intended-purpose.md")
    if not os.path.exists(path):
        return (False, "docs/architecture/intended-purpose.md is missing")
    with io.open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("| Status |"):
                status = line.split("|")[2].strip().strip("*")
                return (status.upper().startswith("APPROVED"), status)
    return (False, "no status line found in the intended-purpose document")


def _validation_metrics_implemented(root: str) -> bool:
    """Whether WP-21's metric machinery exists, measured from the tree.

    Read from disk rather than imported. WP-20 must be able to report this
    from a checkout where ``pgx.validation`` fails to import for an unrelated
    reason; an ImportError here would turn a truthful "not implemented" into
    a crash in the safety gate.
    """
    return all(os.path.exists(os.path.join(root, *path.split("/")))
               for path in ("pgx/validation/metric_definitions.py",
                            "pgx/validation/metrics.py",
                            "pgx/validation/benchmark.py"))


def _later_packages(root: str) -> Dict[str, Any]:
    """Whether WP-21 or later has begun. Measured, not asserted."""
    markers = {
        # Corrected at WP-21. The metric engine lives in ``pgx/validation``
        # because it depends on the partition it must not violate; the two
        # package names guessed here were never built.
        "wp21": ("pgx/validation/benchmark.py", "pgx/validation/metrics.py",
                 "docs/architecture/wp21-validation-metrics.md"),
        # Corrected at WP-22, in step with WP-18's and WP-21's lists: a bare
        # package directory would report started for an empty
        # ``__init__.py``. The protocol document is part of the module.
        "wp22": ("pgx/expert_review/service.py",
                 "pgx/expert_review/protocol.py",
                 "docs/validation/expert-protocol.md",
                 "docs/architecture/wp22-expert-review.md"),
        # Corrected at WP-23, in step with the other marker lists: a bare
        # package directory would report started for an empty
        # ``__init__.py``. These are the files that actually constitute the
        # security layer, and the migration is one of them - an auth system
        # without its tables is not one.
        "wp23": ("pgx/security/service.py", "pgx/security/passwords.py",
                 "pgx/infrastructure/audit/models.py",
                 "migrations/versions/0011_wp23_auth_audit.py",
                 "apps/api/auth.py",
                 "docs/architecture/wp23-auth-audit.md"),
        "wp24": (".github/workflows/ci.yml",
                 "docs/architecture/wp24-ci.md"),
    }
    found: Dict[str, Any] = {}
    for name, paths in markers.items():
        present = sorted(path for path in paths
                         if os.path.exists(os.path.join(root,
                                                        *path.split("/"))))
        found["%s_markers_found" % name] = present
        found["%s_started" % name] = bool(present)
    return found


def _ci_job(root: str) -> Dict[str, Any]:
    """Whether a safety CI job is configured - and whether it ever ran.

    Configured and executed are different facts. A workflow file in the
    repository proves somebody wrote one; it proves nothing about a CI provider
    having run it, and reporting the second from the first would be exactly the
    fabrication this package exists to prevent.
    """
    path = os.path.join(root, ".github", "workflows", "safety-gate.yml")
    configured = os.path.exists(path)
    return {
        "ci_job_configured": configured,
        "ci_job_path": ".github/workflows/safety-gate.yml" if configured
                       else None,
        # Never inferred from the file. Only a CI provider can set this, and
        # nothing in this repository has observed one.
        "ci_job_executed": False,
        "ci_job_execution_note":
            "A workflow file is CONFIGURED, not EXECUTED. No CI provider run "
            "has been observed by this repository, so this stays false until "
            "one is recorded.",
    }


def safety_gate_state(execution: SafetyExecution) -> ExecutionState:
    """One word for the whole gate, chosen without ranking anything.

    Explicit precedence, each step a separate sentence: any failure is FAIL;
    otherwise any unexecuted invariant is NOT_EXECUTED; otherwise any blocked
    one is BLOCKED; otherwise PASS.
    """
    states = [item.execution_state for item in execution.invariants]
    if not states:
        return ExecutionState.NOT_EXECUTED
    for candidate in (ExecutionState.FAIL, ExecutionState.ERROR,
                      ExecutionState.NOT_EXECUTED, ExecutionState.STALE,
                      ExecutionState.BLOCKED):
        if candidate in states:
            return candidate
    return ExecutionState.PASS


def build_wp20_gate_status(root: str,
                           registry: SafetyRegistry,
                           execution: SafetyExecution,
                           report: Mapping[str, Any],
                           evidence_state: str = "ABSENT",
                           evidence_reason: str = "",
                           postgresql_available: Optional[bool] = None,
                           active_release_available: Optional[bool] = None,
                           holdout_case_count: Optional[int] = None
                           ) -> Dict[str, Any]:
    """The WP-20 gate status. Twelve invariants, reported independently."""
    blockers: List[Dict[str, Any]] = []

    def block(code: str, detail: str) -> None:
        blockers.append({"blocking": True, "code": code, "detail": detail,
                         "owner": _OWNERS.get(code, "unassigned")})

    # -- per invariant, six independent facts -----------------------------
    per_invariant: Dict[str, Any] = {}
    for item in execution.invariants:
        identifier = item.invariant_id.value
        definition = registry.definition(item.invariant_id)
        negative = item.negative_controls
        safe = [c for c in item.controls if c.kind == "SAFE"]
        per_invariant[identifier] = {
            "registered": item.registered,
            "safe_control_executed": bool(safe) and safe[0].detected is not None,
            "safe_control_satisfied": bool(safe) and safe[0].satisfied,
            "negative_control_count": len(negative),
            "negative_controls_detected": item.detected_count,
            "negative_controls_all_detected": (
                bool(negative) and item.detected_count == len(negative)),
            "execution_state": item.execution_state.value,
            "compliance_state": item.compliance_state.value,
            "severity": item.severity.value,
            "later_wp_blockers": [b.get("owner") for b in item.blockers],
            "tests_executed": item.tests_executed,
            "refusal_code": definition.refusal_code,
            "reason": item.reason,
        }

        if item.execution_state is ExecutionState.FAIL:
            block("SAFETY_INVARIANT_FAILED",
                  "%s: %s" % (identifier, item.reason))
        elif item.execution_state is ExecutionState.NOT_EXECUTED:
            block("SAFETY_INVARIANT_NOT_EXECUTED",
                  "%s: %s" % (identifier, item.reason))
        elif item.execution_state is ExecutionState.BLOCKED:
            block("SAFETY_INVARIANT_BLOCKED_BY_LATER_WP",
                  "%s: %s" % (identifier, item.reason))
        if negative and item.detected_count < len(negative):
            block("SAFETY_NEGATIVE_CONTROL_UNDETECTED",
                  "%s: %d of %d negative controls were not detected"
                  % (identifier, len(negative) - item.detected_count,
                     len(negative)))

    # -- evidence ---------------------------------------------------------
    if evidence_state == "STALE":
        block("SAFETY_EVIDENCE_STALE", evidence_reason)
    elif evidence_state == "ABSENT":
        block("SAFETY_EVIDENCE_ABSENT", evidence_reason or
              "no safety execution evidence has been recorded; run "
              "`python -m pgx.application.safety_cli check --write`")

    # -- governance and environment ---------------------------------------
    approved, claim_status = _claim_boundary(root)
    if not approved:
        block("SAFETY_CLAIM_BOUNDARY_NOT_APPROVED",
              "claim boundary status is %s" % claim_status)

    if postgresql_available is False:
        block("SAFETY_POSTGRESQL_NOT_EXERCISED",
              "no PostgreSQL server was reached, so the database half of the "
              "persistence and separation invariants did not execute")
    if active_release_available is False:
        block("SAFETY_NO_ACTIVE_RELEASE",
              "no release is registered or active, so no assessment can pin "
              "one")
    if holdout_case_count == 0:
        block("SAFETY_NO_HOLDOUT_CASES",
              "the separation mechanism is enforced and proven; there are "
              "zero holdout cases to separate")

    ci = _ci_job(root)
    if not ci["ci_job_executed"]:
        block("SAFETY_CI_JOB_NOT_EXECUTED", ci["ci_job_execution_note"])

    claims = report.get("prohibited_claim_surfaces", {})
    gap_count = claims.get("known_gap_count")
    if gap_count:
        block("SAFETY_CLAIM_SCANNER_KNOWN_GAPS",
              "%d prohibited phrasing(s) are not matched by the claim "
              "scanner; recorded as a finding for the WP-00 claim registry "
              "rather than patched on an implementer's judgement" % gap_count)

    summary = summarise(execution)
    gate_state = safety_gate_state(execution)
    later = _later_packages(root)

    document: Dict[str, Any] = {
        "active_release_available": active_release_available,
        "blocker_count": len(blockers),
        "blockers": sorted(blockers, key=lambda item: (item["code"],
                                                       item["detail"])),
        "claim_boundary_approved": approved,
        "claim_boundary_status": claim_status,
        "clinical_validation_performed": False,
        "detected_negative_control_count":
            summary["detected_negative_control_count"],
        "detector_evidence_disclaimer": DETECTOR_EVIDENCE_DISCLAIMER,
        "evidence_reason": evidence_reason,
        "evidence_state": evidence_state,
        "executed_invariant_count": summary["executed_invariant_count"],
        "expert_review_performed": False,
        "false_reassurance_corpus_size":
            report.get("false_reassurance", {}).get("corpus_size"),
        "false_reassurance_violation_count":
            report.get("false_reassurance", {}).get("violation_count"),
        "gate_status_schema_version": GATE_STATUS_SCHEMA_VERSION,
        "holdout_case_count": holdout_case_count,
        "implementation_status": "IMPLEMENTED",
        "invariant_status": per_invariant,
        "negative_control_count": summary["negative_control_count"],
        "not_clinical_validation": _NOT_CLINICAL,
        "postgresql_available": postgresql_available,
        "prohibited_claim_surface_count": claims.get("surface_count"),
        "claim_scanner_known_gap_count": claims.get("known_gap_count"),
        "registered_invariant_count": summary["registered_invariant_count"],
        "safety_gate_status": gate_state.value,
        "stale_or_missing_selector_count": 0,
        "tests_executed": summary["tests_executed"],
        "unexplained_skip_count": sum(item.tests_skipped and
                                      item.unexplained_skips
                                      for item in execution.invariants),
        # Changed at WP-21, in step with the published schema. This says the
        # machinery exists - not that a release was validated. The two fields
        # below stay false and stay pinned, because building a metric is not
        # running one and running one is not a clinician's judgement.
        "validation_metrics_implemented": _validation_metrics_implemented(root),
        "validation_metrics_note": (
            "WP-21 implemented the metric registry, the benchmark contract "
            "and the public report. No benchmark has been executed against "
            "any release, so no metric has a value. Implemented is not "
            "computed, and computed would not be validated."),
        "work_package": "WP-20",
    }
    document.update(ci)
    document.update(later)

    # Computed last, from the fields above. False whenever anything is failed,
    # blocked, stale or unexecuted - even when nothing is wrong.
    document["release_may_proceed"] = bool(
        is_release_permitting(gate_state)
        and evidence_state == "CURRENT"
        and not blockers)
    return document
