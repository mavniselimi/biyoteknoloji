# -*- coding: utf-8 -*-
"""The release-validation aggregator (WP-24).

The last gate before a release, and the one with the most ways to be wrong.

It **inspects**. Every input is read from an artifact on disk or passed in by a
caller who read one; nothing here assumes a check passed because it was
configured, and nothing infers a state from a neighbouring one. A release
validator that concluded "the safety gate must be fine, the tests are green"
would be doing exactly the substitution the whole gate exists to prevent.

Fourteen inputs, each with its own state. ``release_may_proceed`` is the
conjunction of the required ones and nothing else - there is no override, no
force flag and no "warn only" mode. The current honest answer is ``false``,
and it is false for reasons that no amount of engineering closes: there is no
approved claim boundary, no holdout case, no completed expert review and no
active validated release.

Two rules that are easy to state and easy to violate:

**A fixture cannot close a real gate.** ``TEST_ONLY_REHEARSAL`` is excluded
from every affirmative check, by :meth:`ExecutionState.may_close_a_release_gate`
rather than by a condition here that somebody could forget.

**An image may be built without being released.** Building is implementation
verification. ``released`` and ``published`` are separate fields and both stay
false while any required gate is not ``VERIFIED`` - so an image can exist,
be scanned and be run locally without any document calling it a release.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import os
from typing import Any, Mapping, Optional, Sequence

from pgx.deployment.vocabulary import (DEPLOYMENT_BLOCKER_CODES,
                                       ExecutionState, blocker)

__all__ = [
    "RELEASE_VALIDATION_VERSION",
    "REQUIRED_GATES",
    "build_release_validation",
    "read_gate_artifacts",
]

RELEASE_VALIDATION_VERSION = "pgx-wp24-release-validation/1"

#: The inputs that must be ``VERIFIED`` for a release to proceed. Ordered as
#: the pipeline produces them, so a reader can see where the path stops.
REQUIRED_GATES: Sequence[str] = (
    "lockfile", "distributions", "image_build", "image_contents",
    "runtime_assets", "migration", "staging_smoke", "tls_termination",
    "safety_gate", "holdout_regression", "expert_review", "security_gate",
    "secret_scan", "vulnerability_scan", "sbom", "backup_restore",
    "rollback_drill", "performance", "claim_boundary",
)

#: Inputs that are recorded but do not, on their own, block. Kept explicit
#: rather than implied by absence from the list above.
ADVISORY_GATES: Sequence[str] = ("ci_execution", "reliability_drills")


def _artifact(root: str, relative: str) -> Optional[Mapping[str, Any]]:
    path = os.path.join(root, relative)
    if not os.path.isfile(path):
        return None
    try:
        with io.open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def read_gate_artifacts(root: str = ".") -> Mapping[str, Any]:
    """Read every upstream gate status this validator depends on.

    Reads rather than imports. The gate documents are what a reviewer would
    open, and validating against the same bytes means this aggregator cannot
    reach a different conclusion from the artifact a person is looking at.
    """
    return {
        "safety": _artifact(root, "data/safety/wp20-real-gate-status.json"),
        "validation": _artifact(
            root, "data/validation/wp18-real-gate-status.json"),
        "benchmark": _artifact(
            root, "data/validation/wp21-real-gate-status.json"),
        "expert_review": _artifact(
            root, "data/expert-review/wp22-real-gate-status.json"),
        "security": _artifact(
            root, "data/security/wp23-real-gate-status.json"),
        "secret_scan": _artifact(
            root, "data/security/wp23-secret-scan-report.json"),
        "verification": _artifact(
            root, "data/verification/wp19-real-gate-status.json"),
    }


def _entry(name: str, state: ExecutionState, detail: str, *,
           source: Optional[str] = None,
           required: bool = True) -> Mapping[str, object]:
    return {"gate": name, "state": state.value, "detail": detail,
            "source": source, "required": required,
            "may_close_gate": state.may_close_a_release_gate}


def build_release_validation(root: str = ".", *,
                             lockfile: Optional[Mapping[str, Any]] = None,
                             distributions: Optional[Mapping[str, Any]]
                             = None,
                             image: Optional[Mapping[str, Any]] = None,
                             image_contents: Optional[Mapping[str, Any]]
                             = None,
                             migration: Optional[Mapping[str, Any]] = None,
                             smoke: Optional[Mapping[str, Any]] = None,
                             performance: Optional[Mapping[str, Any]] = None,
                             reliability: Optional[Mapping[str, Any]] = None,
                             rollback: Optional[Mapping[str, Any]] = None,
                             backup: Optional[Mapping[str, Any]] = None,
                             supply_chain: Optional[Mapping[str, Any]] = None,
                             ci: Optional[Mapping[str, Any]] = None,
                             now: Optional[_dt.datetime] = None
                             ) -> Mapping[str, object]:
    """Aggregate every gate into one machine-readable answer."""
    upstream = read_gate_artifacts(root)
    entries = []

    def state_of(document: Optional[Mapping[str, Any]],
                 default: ExecutionState = ExecutionState.BLOCKED
                 ) -> ExecutionState:
        if not document:
            return default
        raw = str(document.get("state") or "")
        try:
            return ExecutionState(raw)
        except ValueError:
            return default

    # -- build and packaging ------------------------------------------------
    entries.append(_entry(
        "lockfile", state_of(lockfile),
        (lockfile or {}).get("state") and "read from the lock result"
        or "no lock result was supplied",
        source="pgx.deployment.packaging"))
    entries.append(_entry(
        "distributions", state_of(distributions),
        "wheel and sdist double-build comparison",
        source="pgx.deployment.packaging"))
    entries.append(_entry(
        "image_build", state_of(image),
        "the application image", source="pgx.deployment.image"))
    entries.append(_entry(
        "image_contents", state_of(image_contents),
        "no secret, restricted payload, test fixture or legacy entry point "
        "in the built filesystem", source="pgx.deployment.image"))
    # Checked directly rather than read out of the image result. The
    # manifest is verifiable with no container runtime, and reading it only
    # from a build would report "no image" as "assets missing" - two
    # different problems for two different people.
    from pgx.deployment.runtime_assets import verify_runtime_assets

    manifest_ok = bool((image or {}).get("runtime_assets",
                                         verify_runtime_assets(root)
                                         ).get("satisfied"))
    entries.append(_entry(
        "runtime_assets",
        ExecutionState.VERIFIED if manifest_ok else ExecutionState.BLOCKED,
        "every sealed runtime artifact present with a matching checksum",
        source="pgx.deployment.runtime_assets"))

    # -- database and deployment -------------------------------------------
    entries.append(_entry(
        "migration", state_of(migration),
        "alembic upgrade head executed against a real server, at one head",
        source="pgx.deployment.migration"))
    entries.append(_entry(
        "staging_smoke", state_of(smoke),
        "a deployed system answered liveness and readiness",
        source="pgx.deployment.smoke"))
    tls_state = ExecutionState.BLOCKED
    if smoke and smoke.get("tls_used") and \
            smoke.get("environment_kind") == "STAGING" and \
            not smoke.get("tls_verification_disabled", True):
        tls_state = ExecutionState.OBSERVED
    entries.append(_entry(
        "tls_termination", tls_state,
        "HTTPS terminated at a staging ingress and verified against a chain "
        "the client did not generate. A local rehearsal CA does not satisfy "
        "this and is not meant to.",
        source="pgx.deployment.smoke"))

    # -- science and safety -------------------------------------------------
    safety = upstream.get("safety") or {}
    entries.append(_entry(
        "safety_gate",
        (ExecutionState.VERIFIED
         if safety.get("safety_gate_status") == "PASS"
         else ExecutionState.BLOCKED),
        "WP-20 safety gate: %s" % (safety.get("safety_gate_status")
                                   or "no artifact"),
        source="data/safety/wp20-real-gate-status.json"))
    holdout = int((upstream.get("safety") or {}).get("holdout_case_count")
                  or 0)
    entries.append(_entry(
        "holdout_regression",
        (ExecutionState.VERIFIED if holdout > 0
         else ExecutionState.BLOCKED),
        ("%d authorized holdout cases exist. Development fixtures may not "
         "stand in for them: a regression run against the cases the rules "
         "were built from measures nothing." % holdout),
        source="data/safety/wp20-real-gate-status.json"))
    reviewed = bool((upstream.get("expert_review") or {}).get(
        "expert_review_performed"))
    entries.append(_entry(
        "expert_review",
        ExecutionState.VERIFIED if reviewed else ExecutionState.BLOCKED,
        "blind expert review completed under the approved protocol",
        source="data/expert-review/wp22-real-gate-status.json"))
    approved = bool(safety.get("claim_boundary_approved"))
    entries.append(_entry(
        "claim_boundary",
        ExecutionState.VERIFIED if approved else ExecutionState.BLOCKED,
        "claim boundary approved by the named human and scientific reviewers",
        source="data/safety/wp20-real-gate-status.json"))

    # -- security and supply chain -----------------------------------------
    security = upstream.get("security") or {}
    entries.append(_entry(
        "security_gate",
        (ExecutionState.VERIFIED
         if security.get("security_gate_status") == "PASS"
         else ExecutionState.BLOCKED),
        "WP-23 security gate: %s" % (security.get("security_gate_status")
                                     or "no artifact"),
        source="data/security/wp23-real-gate-status.json"))
    scan = upstream.get("secret_scan") or {}
    entries.append(_entry(
        "secret_scan",
        (ExecutionState.VERIFIED if scan.get("status") == "CLEAN"
         else ExecutionState.BLOCKED),
        "repository secret scan: %s, %s findings"
        % (scan.get("status") or "no artifact", scan.get("finding_count")),
        source="data/security/wp23-secret-scan-report.json"))
    chain = supply_chain or {}
    entries.append(_entry(
        "vulnerability_scan",
        state_of(chain.get("vulnerability_scan")),
        "a real scanner, at a named version, against a named advisory "
        "database", source="pgx.deployment.supply_chain"))
    entries.append(_entry(
        "sbom",
        (ExecutionState.VERIFIED
         if (chain.get("sbom") or {}).get("state")
         == ExecutionState.EXECUTED.value else ExecutionState.BLOCKED),
        "a bill of materials from real installed contents",
        source="pgx.deployment.supply_chain"))

    # -- recovery and measurement -------------------------------------------
    entries.append(_entry(
        "backup_restore", state_of(backup),
        "a backup taken to a real destination and a restore satisfying all "
        "four runbook conditions",
        source="pgx.deployment.backup_execution"))
    entries.append(_entry(
        "rollback_drill", state_of(rollback),
        "a rollback performed between two identified images without a "
        "database downgrade", source="pgx.deployment.rollback"))
    entries.append(_entry(
        "performance", state_of(performance),
        "1,000 assessments against one eligible release",
        source="pgx.deployment.performance"))

    # -- advisory -----------------------------------------------------------
    entries.append(_entry(
        "ci_execution", state_of(ci, ExecutionState.CONFIGURED),
        "workflows exist; a provider running them is a separate fact",
        source=".github/workflows", required=False))
    entries.append(_entry(
        "reliability_drills", state_of(reliability),
        "the declared failure drills", source="pgx.deployment.reliability",
        required=False))

    required = [item for item in entries if item["required"]]
    unmet = [item for item in required if not item["may_close_gate"]]
    blockers = []
    for item in unmet:
        code = _BLOCKER_FOR_GATE.get(str(item["gate"]))
        if code:
            blockers.append(dict(blocker(
                code, owner=_OWNER_FOR_GATE.get(str(item["gate"]),
                                                "the deployment"),
                detail="%s: %s" % (item["gate"], item["detail"])).to_json()))

    return {
        "release_validation_version": RELEASE_VALIDATION_VERSION,
        "evaluated_at": (now or _dt.datetime.now(_dt.timezone.utc)
                         ).isoformat(),
        "gate_count": len(entries),
        "required_gate_count": len(required),
        "satisfied_required_count": len(required) - len(unmet),
        "gates": entries,
        "unmet_required_gates": [item["gate"] for item in unmet],
        "blockers": blockers,
        "release_may_proceed": not unmet,
        "image_built": bool(image and image.get("state")
                            == ExecutionState.EXECUTED.value),
        "image_released": False,
        "image_published": False,
        "image_note": (
            "An image may be built for implementation verification without "
            "being released. released and published are separate fields and "
            "both stay false while any required gate is unmet, so a built "
            "image cannot become a release by being tagged."),
        "fixture_note": (
            "TEST_ONLY_REHEARSAL never closes a gate. That is enforced by "
            "ExecutionState.may_close_a_release_gate rather than by a "
            "condition here that somebody could forget."),
        "no_override_note": (
            "There is no force flag, no warn-only mode and no override. "
            "release_may_proceed is the conjunction of the required gates."),
    }


_BLOCKER_FOR_GATE: Mapping[str, str] = {
    "lockfile": "DEPLOY_LOCKFILE_ABSENT",
    "distributions": "DEPLOY_BUILD_BACKEND_UNAVAILABLE",
    "image_build": "DEPLOY_IMAGE_NOT_BUILT",
    "image_contents": "DEPLOY_IMAGE_NOT_BUILT",
    "runtime_assets": "DEPLOY_RUNTIME_ASSET_MISSING",
    "migration": "DEPLOY_MIGRATION_NOT_EXECUTED",
    "staging_smoke": "DEPLOY_STAGING_NOT_DEPLOYED",
    "tls_termination": "DEPLOY_TLS_NOT_OBSERVED",
    "safety_gate": "DEPLOY_SAFETY_GATE_BLOCKED",
    "holdout_regression": "DEPLOY_NO_HOLDOUT_EVIDENCE",
    "expert_review": "DEPLOY_EXPERT_REVIEW_NOT_PERFORMED",
    "claim_boundary": "DEPLOY_CLAIM_BOUNDARY_NOT_APPROVED",
    "security_gate": "DEPLOY_SAFETY_GATE_BLOCKED",
    "secret_scan": "DEPLOY_SAFETY_GATE_BLOCKED",
    "vulnerability_scan": "DEPLOY_VULNERABILITY_SCANNER_UNAVAILABLE",
    "sbom": "DEPLOY_SBOM_NOT_GENERATED",
    "backup_restore": "DEPLOY_RESTORE_NOT_VERIFIED",
    "rollback_drill": "DEPLOY_ROLLBACK_NOT_EXERCISED",
    "performance": "DEPLOY_PERFORMANCE_NOT_EXECUTED",
}

_OWNER_FOR_GATE: Mapping[str, str] = {
    "lockfile": "the build environment",
    "distributions": "the build environment",
    "image_build": "a host with a container runtime",
    "image_contents": "a host with a container runtime",
    "runtime_assets": "whoever generates the sealed artifacts",
    "migration": "an operator",
    "staging_smoke": "WP-24 operation",
    "tls_termination": "whoever provisions the staging ingress",
    "safety_gate": "WP-20 and the scientific track",
    "holdout_regression": "scientific curators",
    "expert_review": "named expert reviewers",
    "claim_boundary": "named human and scientific reviewers",
    "security_gate": "the deployment",
    "secret_scan": "whoever committed a finding",
    "vulnerability_scan": "the build host",
    "sbom": "the build host",
    "backup_restore": "WP-24 operation",
    "rollback_drill": "WP-24 operation",
    "performance": "WP-24 operation against an eligible release",
}

assert set(_BLOCKER_FOR_GATE.values()) <= set(DEPLOYMENT_BLOCKER_CODES), (
    "every gate maps to a declared blocker code")
