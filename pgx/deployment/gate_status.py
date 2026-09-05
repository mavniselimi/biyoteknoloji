# -*- coding: utf-8 -*-
"""The WP-24 gate status and the Gate E operational status (WP-24).

Two documents, and they answer different questions.

``build_wp24_gate_status`` answers *"what did WP-24 implement, configure and
execute?"* - three separate groups of fields, exactly as WP-23's gate status
separates them, because in this repository the first group is full of ``true``
and the other two are almost entirely ``false`` and that is the finding rather
than an embarrassment.

``build_gate_e_status`` answers architecture.md's Gate E: *"Auth/audit/security,
CI/deploy, rollback/reliability evidence"* across WP-23 and WP-24 together. It
reads both packages' real artifacts and does not infer either from the other.

The implementation markers are read from the filesystem, like WP-20's and
WP-23's. A gate status that asserted its own package existed would pass in a
checkout where the package had been deleted.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import os
from typing import Any, Mapping, Optional, Sequence, Tuple

from pgx.deployment.vocabulary import ExecutionState

__all__ = [
    "GATE_E_STATUS_VERSION",
    "MODULE_MARKERS",
    "WP24_GATE_STATUS_VERSION",
    "build_gate_e_status",
    "build_wp24_gate_status",
]

WP24_GATE_STATUS_VERSION = "pgx-wp24-gate-status/1"
GATE_E_STATUS_VERSION = "pgx-wp24-gate-e-operational-status/1"

#: Every file whose presence means a piece of WP-24 exists. Read from disk
#: rather than asserted, so a checkout missing half the package reports that
#: rather than reporting itself implemented.
MODULE_MARKERS: Tuple[str, ...] = (
    "pgx/deployment/__init__.py",
    "pgx/deployment/vocabulary.py",
    "pgx/deployment/errors.py",
    "pgx/deployment/environment.py",
    "pgx/deployment/secrets.py",
    "pgx/deployment/composition.py",
    "pgx/deployment/stores.py",
    "pgx/deployment/rate_limit_store.py",
    "pgx/deployment/runtime_assets.py",
    "pgx/deployment/provenance.py",
    "pgx/deployment/packaging.py",
    "pgx/deployment/image.py",
    "pgx/deployment/migration.py",
    "pgx/deployment/smoke.py",
    "pgx/deployment/performance.py",
    "pgx/deployment/reliability.py",
    "pgx/deployment/rollback.py",
    "pgx/deployment/backup_execution.py",
    "pgx/deployment/supply_chain.py",
    "pgx/deployment/release_validation.py",
    "pgx/deployment/gate_status.py",
    "pgx/deployment/artifacts.py",
    "pgx/application/deploy_cli.py",
    "pgx/application/deployment_schema.py",
    "apps/api/deployment.py",
    "Dockerfile",
    ".dockerignore",
    "docker-compose.wp24.yml",
    ".github/workflows/build-and-verify.yml",
    ".github/workflows/release-validation.yml",
)


def _present(root: str, relative: str) -> bool:
    return os.path.exists(os.path.join(root, *relative.split("/")))


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


def build_wp24_gate_status(root: str = ".", *,
                           environment: Optional[Mapping[str, Any]] = None,
                           lockfile: Optional[Mapping[str, Any]] = None,
                           distributions: Optional[Mapping[str, Any]] = None,
                           image: Optional[Mapping[str, Any]] = None,
                           migration: Optional[Mapping[str, Any]] = None,
                           smoke: Optional[Mapping[str, Any]] = None,
                           performance: Optional[Mapping[str, Any]] = None,
                           reliability: Optional[Mapping[str, Any]] = None,
                           rollback: Optional[Mapping[str, Any]] = None,
                           backup: Optional[Mapping[str, Any]] = None,
                           supply_chain: Optional[Mapping[str, Any]] = None,
                           release_validation: Optional[Mapping[str, Any]]
                           = None,
                           now: Optional[_dt.datetime] = None
                           ) -> Mapping[str, object]:
    """Implemented, configured, executed - three groups that may disagree."""
    markers = {relative: _present(root, relative)
               for relative in MODULE_MARKERS}
    implemented = all(markers.values())

    def state(document: Optional[Mapping[str, Any]]) -> Optional[str]:
        return None if not document else str(document.get("state") or "") \
            or None

    validation = release_validation or {}
    return {
        "gate_status_schema_version": WP24_GATE_STATUS_VERSION,
        "work_package": "WP-24",
        "generated_at": (now or _dt.datetime.now(_dt.timezone.utc)
                         ).isoformat(),

        # -- implemented: what exists in this repository -------------------
        "implementation_status": ("IMPLEMENTED" if implemented
                                  else "INCOMPLETE"),
        "deployment_package_present": implemented,
        "module_markers_found": sum(1 for value in markers.values() if value),
        "module_markers_expected": len(markers),
        "missing_markers": sorted(name for name, found in markers.items()
                                  if not found),
        "dockerfile_present": _present(root, "Dockerfile"),
        "dockerignore_present": _present(root, ".dockerignore"),
        "compose_topology_present": _present(root, "docker-compose.wp24.yml"),
        "ci_workflows_present": sorted(
            name for name in (
                ".github/workflows/safety-gate.yml",
                ".github/workflows/build-and-verify.yml",
                ".github/workflows/release-validation.yml")
            if _present(root, name)),
        "deploy_cli_present": _present(root, "pgx/application/deploy_cli.py"),
        "runtime_composition_implemented": _present(
            root, "pgx/deployment/composition.py"),

        # -- configured: what this host or deployment actually has ----------
        "container_runtime_available": bool(
            (environment or {}).get("container_runtime_available")),
        "package_index_reachable": bool(
            (environment or {}).get("package_index_reachable")),
        "argon2_available": bool(
            (environment or {}).get("modules", {}).get("argon2")),
        "lockfile_present": os.path.isfile(os.path.join(root, "uv.lock")),
        "lockfile_state": state(lockfile),
        "database_url_configured": bool(
            (environment or {}).get("database_url_configured")),

        # -- executed / observed: what actually ran -------------------------
        "distribution_build_state": state(distributions),
        "image_build_state": state(image),
        "image_digest": (image or {}).get("image_digest"),
        "migration_state": state(migration),
        "migration_executed": bool((migration or {}).get("executed")),
        "staging_smoke_state": state(smoke),
        "staging_environment_kind": (smoke or {}).get("environment_kind"),
        "tls_observed": bool((smoke or {}).get("tls_used")
                             and (smoke or {}).get("environment_kind")
                             == "STAGING"),
        "performance_state": state(performance),
        # Null, not zero. A zero here would say a thousand assessments
        # completed in no time.
        "performance_completed": (performance or {}).get("completed"),
        "reliability_state": state(reliability),
        "reliability_executed_count": (reliability or {}).get(
            "executed_count"),
        "rollback_state": state(rollback),
        "backup_state": state(backup),
        "backup_operational_status": (backup or {}).get(
            "operational_status"),
        "restore_verified": bool((backup or {}).get("restore_verified")),
        "sbom_state": state((supply_chain or {}).get("sbom")),
        "vulnerability_scan_state": state(
            (supply_chain or {}).get("vulnerability_scan")),
        "ci_executed": _ci_executed(),
        "ci_action_pins_resolved": _action_pins_resolved(root),

        # -- the aggregate --------------------------------------------------
        "deployment_gate_status": (
            "PASS" if validation.get("release_may_proceed") else "BLOCKED"),
        "release_may_proceed": bool(validation.get("release_may_proceed")),
        "unmet_required_gates": list(
            validation.get("unmet_required_gates") or []),
        "blockers": list(validation.get("blockers") or []),
        "note": (
            "Implemented, configured and executed are three groups and they "
            "are allowed to disagree. In this repository the first is "
            "complete and the other two are almost entirely absent, which is "
            "the finding rather than a formatting choice."),
    }


def _action_pins_resolved(root: str) -> bool:
    """Whether every third-party action is pinned to a commit SHA."""
    from pgx.deployment.ci_status import action_pins

    return bool(action_pins(root)["all_sha_pinned"])


def _ci_executed() -> Optional[bool]:
    """Whether a CI provider actually ran this pipeline.

    ``None`` unless observed. A workflow file existing proves somebody wrote a
    job; it proves nothing about a provider having run one, and this
    repository has no commit for a provider to have run against.
    """
    if os.environ.get("GITHUB_RUN_ID"):
        return True
    return None


def build_gate_e_status(root: str = ".", *,
                        wp24: Optional[Mapping[str, Any]] = None,
                        now: Optional[_dt.datetime] = None
                        ) -> Mapping[str, object]:
    """Gate E: operational. WP-23 and WP-24 read together, neither inferred.

    architecture.md section 20 defines Gate E as *"Auth/audit/security,
    CI/deploy, rollback/reliability evidence"*. Each half reports its own
    real artifact; a PASS needs both, and neither is derived from the other.
    """
    security = _artifact(root, "data/security/wp23-real-gate-status.json") \
        or {}
    deployment = dict(wp24 or {})
    safety = _artifact(root, "data/safety/wp20-real-gate-status.json") or {}

    security_pass = security.get("security_gate_status") == "PASS"
    deployment_pass = deployment.get("deployment_gate_status") == "PASS"
    gate_pass = bool(security_pass and deployment_pass)
    return {
        "gate_status_schema_version": GATE_E_STATUS_VERSION,
        "gate": "Gate E - Operational",
        "definition_source": "architecture.md section 20",
        "work_packages": ["WP-23", "WP-24"],
        "generated_at": (now or _dt.datetime.now(_dt.timezone.utc)
                         ).isoformat(),

        "wp23_security_gate_status": security.get("security_gate_status"),
        "wp23_implementation_status": security.get("implementation_status"),
        "wp24_deployment_gate_status": deployment.get(
            "deployment_gate_status"),
        "wp24_implementation_status": deployment.get("implementation_status"),

        "authentication_configured": bool(
            security.get("authentication_configured")),
        "canonical_audit_implemented": bool(
            security.get("canonical_audit_implemented")),
        "audit_chain_verified": security.get("audit_chain_verified"),
        "ci_configured": bool(deployment.get("ci_workflows_present")),
        "ci_executed": deployment.get("ci_executed"),
        "image_built": deployment.get("image_build_state") == (
            ExecutionState.EXECUTED.value),
        "image_published": False,
        "staging_deployed": deployment.get("staging_smoke_state") == (
            ExecutionState.OBSERVED.value),
        "staging_is_remote": deployment.get(
            "staging_environment_kind") == "STAGING",
        "tls_observed": bool(deployment.get("tls_observed")),
        "rollback_exercised": deployment.get("rollback_state") == (
            ExecutionState.VERIFIED.value),
        "backup_operational": deployment.get(
            "backup_operational_status") == "VERIFIED",
        "restore_verified": bool(deployment.get("restore_verified")),
        "reliability_evidence": deployment.get("reliability_state"),
        "performance_evidence": deployment.get("performance_state"),

        "claim_boundary_status": safety.get("claim_boundary_status"),
        "gate_e_status": "PASS" if gate_pass else "BLOCKED",
        "release_may_proceed": gate_pass and bool(
            deployment.get("release_may_proceed")),
        "inherits_no_fixture_result": (
            "No field here is derived from a test fixture or a rehearsal. "
            "TEST_ONLY_REHEARSAL never satisfies a gate, and a local "
            "rehearsal is never reported as staging."),
        "note": (
            "Gate E needs both halves. WP-23's security gate and WP-24's "
            "deployment gate are read from their own artifacts, and neither "
            "is inferred from the other - a deployment cannot vouch for the "
            "security layer it is running, and a security layer cannot "
            "vouch for a deployment nobody made."),
    }
