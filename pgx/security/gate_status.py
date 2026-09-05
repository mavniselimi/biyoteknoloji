# -*- coding: utf-8 -*-
"""The WP-23 gate: the software exists; nothing is operating (WP-23).

Three answers that must not be collapsed, and this document reports them in
separate fields so they can disagree - which they currently do:

- **Is the security software implemented?** Yes. Argon2id hashing, local
  users, server-side sessions, session-bound CSRF, an explicit RBAC registry,
  declared rate limits, a hash-linked canonical audit trail, a secret scanner
  and a backup plan all exist and are tested.
- **Is it configured?** No. There is no database, no Argon2 package installed
  here, no HTTPS termination, no secret configuration and no composed
  service.
- **Is it operating?** No. There are no users, no sessions have been created,
  no audit chain has been verified against a real store, and no backup or
  restore has run.

Collapsing any two of those produces the sentence this whole work package is
arranged to avoid: "security: done". A reader of a single boolean would be
told the third answer while being shown the first.

Nothing here is asserted. The implementation state comes from importing the
modules and walking the tree; the configuration state comes from the injected
provider and the environment; the operational state comes from a store, or is
``null`` when no store was inspected.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, Optional, Tuple

from pgx.domain.claims import DEFAULT_CLAIM_BOUNDARY
from pgx.infrastructure.audit.vocabulary import (AUDIT_ACTIONS,
                                                 AUDIT_EVENT_VERSION)
from pgx.security.backup import backup_status
from pgx.security.passwords import (ACTIVE_POLICY, argon2_available,
                                    argon2_unavailable_reason)
from pgx.security.rate_limit import POLICY_IDS, RATE_LIMIT_POLICY_VERSION
from pgx.security.rbac import (PERMISSION_IDS, RBAC_REGISTRY_VERSION,
                               registry_digest)
from pgx.security.secret_scan import SECRET_SCAN_VERSION, scan_repository
from pgx.security.sessions import SessionPolicy
from pgx.security.vocabulary import VOCABULARY_VERSION

__all__ = [
    "GATE_STATUS_VERSION",
    "MODULE_MARKERS",
    "SECURITY_BLOCKER_CODES",
    "build_wp23_gate_status",
    "security_gate_state",
    "security_module_markers",
]

GATE_STATUS_VERSION = "pgx-wp23-gate-status/1"

#: What constitutes WP-23 on disk. Checked as a set: a partial set reports as
#: not implemented rather than implemented-with-gaps, because a security layer
#: missing its audit trail or its migration is not a security layer.
MODULE_MARKERS: Tuple[str, ...] = (
    "pgx/security/passwords.py",
    "pgx/security/users.py",
    "pgx/security/sessions.py",
    "pgx/security/csrf.py",
    "pgx/security/rbac.py",
    "pgx/security/rate_limit.py",
    "pgx/security/service.py",
    "pgx/security/secret_scan.py",
    "pgx/security/backup.py",
    "pgx/infrastructure/audit/models.py",
    "pgx/infrastructure/audit/service.py",
    "pgx/infrastructure/db/security.py",
    "migrations/versions/0011_wp23_auth_audit.py",
    "apps/api/auth.py",
    "docs/architecture/wp23-auth-audit.md",
)

SECURITY_BLOCKER_CODES: Mapping[str, Mapping[str, str]] = {
    "SECURITY_ARGON2_UNAVAILABLE": {
        "meaning": "the argon2-cffi package is not installed, so no password "
                   "can be hashed or verified and there is no weaker "
                   "algorithm to fall back to",
        "owner": "deployment"},
    "SECURITY_DATABASE_UNAVAILABLE": {
        "meaning": "no PostgreSQL is configured, so there is no user store, "
                   "no session store and no audit store",
        "owner": "deployment"},
    "SECURITY_MIGRATION_NOT_EXECUTED": {
        "meaning": "migration 0011 has been written and not executed; the "
                   "security tables do not exist in any database",
        "owner": "deployment"},
    "SECURITY_NO_REAL_USERS": {
        "meaning": "no account has been provisioned; there is no default "
                   "user and no bootstrap has been run",
        "owner": "an administrator running pgx-auth bootstrap-admin"},
    "SECURITY_AUTHENTICATION_NOT_CONFIGURED": {
        "meaning": "no authentication provider is composed, so every "
                   "authenticated route reports the server unready",
        "owner": "deployment"},
    "SECURITY_HTTPS_NOT_OBSERVED": {
        "meaning": "no HTTPS termination has been observed; the session "
                   "cookie is Secure and will not be sent over plain HTTP",
        "owner": "WP-24 staging deployment"},
    "SECURITY_AUDIT_CHAIN_NOT_VERIFIED": {
        "meaning": "no governed audit chain has been verified against a real "
                   "store, because there is no store",
        "owner": "deployment"},
    "SECURITY_BACKUP_NOT_EXECUTED": {
        "meaning": "the backup and restore procedure is documented and has "
                   "not been executed or verified",
        "owner": "WP-24 operation"},
    "SECURITY_SECRET_SCAN_FINDINGS": {
        "meaning": "the secret scan reported at least one unclassified "
                   "finding",
        "owner": "whoever committed it"},
    "SECURITY_CLAIM_BOUNDARY_NOT_APPROVED": {
        "meaning": "the claim boundary awaits human and scientific review",
        "owner": "named human and scientific reviewers"},
}


def security_module_markers(root: str) -> Tuple[str, ...]:
    """The WP-23 files that exist, read from the tree rather than imported.

    Read from disk for the reason WP-20, WP-21 and WP-22 all read theirs that
    way: an ImportError in an unrelated module must not turn a truthful
    answer into a crash inside a gate builder.
    """
    return tuple(path for path in MODULE_MARKERS
                 if os.path.exists(os.path.join(root, *path.split("/"))))


def security_gate_state(*, implemented: bool, argon2: bool,
                        database: bool, migration_executed: bool,
                        real_users: int, authentication_configured: bool,
                        https_observed: bool, audit_chain_verified: bool,
                        backup_verified: bool, secret_findings: int) -> str:
    """``PASS`` only when the software is implemented *and* operating."""
    if not implemented or secret_findings:
        return "FAILED" if secret_findings else "BLOCKED"
    if not (argon2 and database and migration_executed
            and authentication_configured and https_observed):
        return "BLOCKED"
    if real_users <= 0 or not audit_chain_verified or not backup_verified:
        return "BLOCKED"
    return "PASS"


def build_wp23_gate_status(root: str = None,
                           environ: Optional[Mapping[str, str]] = None,
                           provider: Optional[Any] = None,
                           user_store: Optional[Any] = None,
                           audit_reader: Optional[Any] = None,
                           run_secret_scan: bool = True) -> Dict[str, Any]:
    """The committed WP-23 gate status, measured from this repository."""
    if root is None:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                            "..", ".."))
    values = os.environ if environ is None else environ
    markers = security_module_markers(root)
    implemented = len(markers) == len(MODULE_MARKERS)
    argon2 = argon2_available()
    database = bool(values.get("DATABASE_URL"))
    boundary = DEFAULT_CLAIM_BOUNDARY

    capabilities = (provider.security_capabilities if provider is not None
                    else {})
    authentication_configured = bool(
        capabilities.get("authentication_service_composed", False))

    # ``None`` rather than ``0`` throughout: nobody inspected a store, so
    # nothing was counted. A reader must be able to tell "we did not look"
    # from "we looked and found none".
    real_users: Optional[int] = None
    if user_store is not None:
        real_users = int(user_store.count())

    audit_event_count: Optional[int] = None
    audit_chain_verified: Optional[bool] = None
    if audit_reader is not None:
        from pgx.infrastructure.audit.models import verify_chain
        events = tuple(audit_reader.all_events())
        audit_event_count = len(events)
        audit_chain_verified = bool(verify_chain(events)[0])

    scan: Dict[str, Any] = {}
    if run_secret_scan:
        scan = scan_repository(root)
    secret_findings = int(scan.get("finding_count", 0))

    backup = backup_status(root, values)

    blockers: List[Dict[str, Any]] = []

    def _block(code: str, detail: str) -> None:
        blockers.append({"code": code, "blocking": True, "detail": detail,
                         "owner": SECURITY_BLOCKER_CODES[code]["owner"]})

    if not argon2:
        _block("SECURITY_ARGON2_UNAVAILABLE",
               argon2_unavailable_reason() or "argon2-cffi is unavailable")
    if not database:
        _block("SECURITY_DATABASE_UNAVAILABLE",
               "DATABASE_URL is unset; no user, session or audit store exists")
    _block("SECURITY_MIGRATION_NOT_EXECUTED",
           "migration 0011 is written and has not been executed against any "
           "PostgreSQL server")
    _block("SECURITY_NO_REAL_USERS",
           "no user store was inspected, so no account was counted"
           if real_users is None
           else "%d account(s) exist in the inspected store" % real_users)
    if not authentication_configured:
        _block("SECURITY_AUTHENTICATION_NOT_CONFIGURED",
               "no authentication service is composed in this deployment")
    _block("SECURITY_HTTPS_NOT_OBSERVED",
           "no HTTPS termination has been observed; WP-24 owns staging")
    _block("SECURITY_AUDIT_CHAIN_NOT_VERIFIED",
           "no audit store was inspected, so no chain was verified"
           if audit_chain_verified is None
           else "the inspected chain verified: %s" % audit_chain_verified)
    _block("SECURITY_BACKUP_NOT_EXECUTED",
           "the procedure is documented; no backup or restore has run")
    if secret_findings:
        _block("SECURITY_SECRET_SCAN_FINDINGS",
               "%d unclassified finding(s); see the scan report for paths"
               % secret_findings)
    if not boundary.is_approved:
        _block("SECURITY_CLAIM_BOUNDARY_NOT_APPROVED",
               "claim boundary status is %s" % boundary.status)
    blockers.sort(key=lambda item: (item["code"], item["detail"]))

    state = security_gate_state(
        implemented=implemented, argon2=argon2, database=database,
        migration_executed=False, real_users=real_users or 0,
        authentication_configured=authentication_configured,
        https_observed=False, audit_chain_verified=bool(audit_chain_verified),
        backup_verified=bool(backup["restore_verified"]),
        secret_findings=secret_findings)

    return {
        "gate_status_schema_version": GATE_STATUS_VERSION,
        "work_package": "WP-23",
        "implementation_status": ("IMPLEMENTED" if implemented
                                  else "NOT_IMPLEMENTED"),
        "implementation_note": (
            "Argon2id hashing, local user lifecycle, server-side sessions, "
            "session-bound CSRF, the explicit RBAC registry, declared rate "
            "limits, the hash-linked canonical audit trail, the secret "
            "scanner and the backup plan are implemented. That is a "
            "statement about software. Whether this deployment is running "
            "any of it is the separate question below, and the answer is no."),
        "security_gate_status": state,
        "release_may_proceed": state == "PASS",

        # -- implemented ---------------------------------------------------
        "security_software_implemented": implemented,
        "module_marker_paths": list(MODULE_MARKERS),
        "module_marker_present_count": len(markers),
        "security_vocabulary_version": VOCABULARY_VERSION,
        "authentication_software_implemented": implemented,
        "session_management_implemented": implemented,
        "csrf_implemented": implemented,
        "rate_limiting_implemented": implemented,
        "canonical_audit_implemented": implemented,
        "audit_event_schema_version": AUDIT_EVENT_VERSION,
        "governed_audit_action_count": len(AUDIT_ACTIONS),
        "rbac_registry_version": RBAC_REGISTRY_VERSION,
        "rbac_registry_digest": registry_digest(),
        "permission_count": len(PERMISSION_IDS),
        "role_hierarchy": None,
        "password_policy": ACTIVE_POLICY.to_json(),
        "session_policy": SessionPolicy().to_json(),
        "rate_limit_policy_version": RATE_LIMIT_POLICY_VERSION,
        "rate_limit_policy_count": len(POLICY_IDS),

        # -- configured ----------------------------------------------------
        "argon2_dependency_declared": True,
        "argon2_available": argon2,
        "argon2_unavailable_reason": argon2_unavailable_reason(),
        "database_available": database,
        "migration_0011_present": os.path.exists(os.path.join(
            root, "migrations", "versions", "0011_wp23_auth_audit.py")),
        "migration_0011_executed": False,
        "session_store_available": database,
        "audit_store_available": database,
        "authentication_configured": authentication_configured,
        "csrf_operational": bool(
            capabilities.get("csrf_service_composed", False)),
        "rate_limiting_operational": bool(
            capabilities.get("rate_limiter_composed", False)),
        "https_termination_observed": False,
        "provider_capabilities": dict(capabilities),

        # -- operating -----------------------------------------------------
        "real_users_configured": real_users,
        "real_user_count_source": (
            "null rather than zero: no user store was inspected, so no "
            "account was counted" if real_users is None
            else "counted from the supplied user store"),
        "session_authentication_exercised_operationally": False,
        "governed_audit_event_count": audit_event_count,
        "audit_chain_verified": audit_chain_verified,
        "secret_scan_status": scan.get("status", "NOT_RUN"),
        "secret_scan_finding_count": scan.get("finding_count"),
        "secret_scan_classified_count": scan.get("classified_finding_count"),
        "secret_scan_version": SECRET_SCAN_VERSION,
        "backup_procedure_documented": backup["backup_procedure_documented"],
        "backup_executed": backup["backup_executed"],
        "restore_executed": backup["restore_executed"],
        "restore_verified": backup["restore_verified"],
        "backup_operational_status": backup["operational_status"],

        # -- unchanged by WP-23 --------------------------------------------
        "expert_review_performed": False,
        "clinical_validation_performed": False,
        "claim_boundary_status": boundary.status,
        "claim_boundary_approved": boundary.is_approved,

        "blockers": blockers,
        "blocking_count": sum(1 for item in blockers if item["blocking"]),
        "implemented_is_not_operational": (
            "Every field above is one of three kinds: what the software can "
            "do, what this deployment has composed, and what has actually "
            "happened. They are separate because collapsing any two produces "
            "the sentence this work package exists to avoid - a reader shown "
            "the first answer while being told the third."),
        "not_a_security_certification": (
            "This document describes an authentication, authorisation and "
            "audit implementation and its current unconfigured state. It is "
            "not a penetration test, a security audit, a certification or "
            "evidence that this system is safe to expose. No such assessment "
            "has been performed."),
    }
