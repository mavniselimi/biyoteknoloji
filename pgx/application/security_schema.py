# -*- coding: utf-8 -*-
"""Published JSON Schemas for WP-23.

Nine schemas, and as in WP-21 and WP-22 the constraints that carry the safety
content are the negative ones. A schema describing only the happy shape would
accept a user projection carrying a password hash, an audit event claiming
session assurance from a fixture, or a backup status reporting a verified
restore that never ran - which are the three documents nobody should be able
to publish.

These schemas pin, with ``const`` where the value is a fact about this
repository rather than a variable:

- ``backup_executed``, ``restore_executed`` and ``restore_verified`` are
  ``false``, and ``operational_status`` may not be ``EXECUTED_VERIFIED``
  while they are. Flipping any of them needs this file to change in the open.
- A user or session projection has ``additionalProperties: false`` and no
  property a hash, token or secret could occupy. Absence by construction,
  not by a producer remembering to drop a field.
- An audit event carrying ``auth_assurance: SESSION`` must carry
  ``auth_mechanism: SESSION`` and a session reference. A fixture cannot
  describe itself as a person.
- ``role_hierarchy`` is ``null``, not an empty object. There is no hierarchy
  to describe, and an empty object would read as one that happens to be
  empty today.

Written against the supported subset of JSON Schema that
``pgx.application.snapshot_schema.validate_against_schema`` implements - no
``patternProperties``, so keyed maps are described rather than pattern
matched.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from pgx.application.snapshot_schema import validate_against_schema
from pgx.infrastructure.audit.vocabulary import (AUDIT_ACTIONS,
                                                 AUDIT_EVENT_VERSION,
                                                 OBJECT_TYPES)
from pgx.security.backup import BACKUP_PLAN_VERSION, OperationalStatus
from pgx.security.gate_status import GATE_STATUS_VERSION
from pgx.security.passwords import PASSWORD_POLICY_VERSION
from pgx.security.rate_limit import RATE_LIMIT_POLICY_VERSION
from pgx.security.rbac import PERMISSION_IDS, RBAC_REGISTRY_VERSION
from pgx.security.secret_scan import SECRET_SCAN_VERSION
from pgx.security.vocabulary import (AUTH_ASSURANCE_VALUES, GOVERNED_ROLES,
                                     UserStatus)

__all__ = [
    "AUDIT_EVENT_SCHEMA_PATH",
    "AUDIT_VERIFICATION_SCHEMA_PATH",
    "BACKUP_STATUS_SCHEMA_PATH",
    "GATE_STATUS_SCHEMA_PATH",
    "RATE_LIMIT_SCHEMA_PATH",
    "RBAC_REGISTRY_SCHEMA_PATH",
    "SECRET_SCAN_SCHEMA_PATH",
    "SESSION_PROJECTION_SCHEMA_PATH",
    "USER_PROJECTION_SCHEMA_PATH",
    "build_schemas",
    "validate_audit_event",
    "validate_audit_verification",
    "validate_backup_status",
    "validate_rate_limit_policy",
    "validate_rbac_registry",
    "validate_secret_scan_report",
    "validate_session_projection",
    "validate_user_projection",
    "validate_wp23_gate_status",
]

USER_PROJECTION_SCHEMA_PATH = "schemas/wp23/user-safe-projection.schema.json"
SESSION_PROJECTION_SCHEMA_PATH = \
    "schemas/wp23/session-safe-projection.schema.json"
RBAC_REGISTRY_SCHEMA_PATH = "schemas/wp23/rbac-registry.schema.json"
AUDIT_EVENT_SCHEMA_PATH = "schemas/wp23/governed-audit-event.schema.json"
AUDIT_VERIFICATION_SCHEMA_PATH = \
    "schemas/wp23/audit-verification-result.schema.json"
RATE_LIMIT_SCHEMA_PATH = "schemas/wp23/rate-limit-policy.schema.json"
SECRET_SCAN_SCHEMA_PATH = "schemas/wp23/secret-scan-report.schema.json"
BACKUP_STATUS_SCHEMA_PATH = "schemas/wp23/backup-restore-status.schema.json"
GATE_STATUS_SCHEMA_PATH = "schemas/wp23/wp23-gate-status.schema.json"

_BASE = "https://pgx.local/schemas/wp23/"
_DRAFT = "https://json-schema.org/draft/2020-12/schema"

_DIGEST = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
_NULLABLE_DIGEST = {"anyOf": [_DIGEST, {"type": "null"}]}
_NULLABLE_INT = {"anyOf": [{"type": "integer", "minimum": 0},
                           {"type": "null"}]}
_NULLABLE_BOOL = {"anyOf": [{"type": "boolean"}, {"type": "null"}]}
_NULLABLE_STRING = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_TIMESTAMP = {"type": "string",
              "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z$"}

_ROLES = sorted(GOVERNED_ROLES)
_STATUSES = [item.value for item in UserStatus]

#: Every property name a published security document is forbidden to have.
#: Listed once and asserted by a test against every schema here, so a new
#: schema cannot quietly introduce one.
FORBIDDEN_PROPERTY_NAMES = (
    "password", "password_hash", "passphrase", "secret", "csrf_secret",
    "token", "session_token", "raw_token", "token_digest", "cookie",
    "authorization", "api_key", "private_key", "dsn", "database_url")


def _envelope(name: str, title: str, description: str) -> Dict[str, Any]:
    return {"$id": _BASE + name, "$schema": _DRAFT, "title": title,
            "description": description}


def _user_projection_schema() -> Dict[str, Any]:
    """What may be shown about an account.

    ``additionalProperties: false`` is the point. The password hash is absent
    by construction rather than by a producer remembering to drop it, and a
    document that carried one would be refused by the schema rather than
    published and noticed later.
    """
    schema = _envelope(
        "user-safe-projection.schema.json", "WP-23 user safe projection",
        "What may be shown, logged or returned about a local account. The "
        "password hash has no property to occupy, and neither does any "
        "personal detail - this system stores no name, email address or "
        "telephone number.")
    schema.update({
        "type": "object",
        "required": ["user_id", "username", "role", "status",
                     "auth_generation", "locked", "created_at", "updated_at",
                     "password_changed_at", "is_bootstrap_admin"],
        "additionalProperties": False,
        "properties": {
            "user_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "username": {"type": "string",
                         "pattern": "^[a-z0-9][a-z0-9._-]{2,63}$"},
            "role": {"type": "string", "enum": _ROLES},
            "status": {"type": "string", "enum": _STATUSES},
            "auth_generation": {"type": "integer", "minimum": 1},
            "locked": {"type": "boolean"},
            "created_at": _TIMESTAMP,
            "updated_at": _TIMESTAMP,
            "password_changed_at": _TIMESTAMP,
            "created_by": _NULLABLE_STRING,
            "is_bootstrap_admin": {"type": "boolean"},
        },
    })
    return schema


def _session_projection_schema() -> Dict[str, Any]:
    schema = _envelope(
        "session-safe-projection.schema.json",
        "WP-23 session safe projection",
        # Worded so that no credential-shaped phrase appears in the text.
        # An earlier draft used the word for key material immediately
        # followed by a colon and a value, which is precisely the shape both
        # WP-19's scrubber and this work package's own SEC-004 rule look for
        # - and both were right to flag it. The fix is prose that does not
        # look like an assignment, never a weaker rule.
        "What may be shown about a server-side session. It has no property "
        "for the token, for the token digest, or for the per-session CSRF "
        "key material. A digest in a published document would be a verifier "
        "for the cookie.")
    schema.update({
        "type": "object",
        "required": ["session_id", "user_id", "role", "auth_generation",
                     "created_at", "last_seen_at", "idle_expires_at",
                     "absolute_expires_at", "revoked"],
        "additionalProperties": False,
        "properties": {
            "session_id": {"type": "string", "minLength": 1},
            "user_id": {"type": "string", "minLength": 1},
            "role": {"type": "string", "enum": _ROLES},
            "auth_generation": {"type": "integer", "minimum": 1},
            "created_at": _TIMESTAMP,
            "last_seen_at": _TIMESTAMP,
            "idle_expires_at": _TIMESTAMP,
            "absolute_expires_at": _TIMESTAMP,
            "revoked": {"type": "boolean"},
            "revocation_reason": _NULLABLE_STRING,
        },
    })
    return schema


def _rbac_registry_schema() -> Dict[str, Any]:
    schema = _envelope(
        "rbac-registry.schema.json", "WP-23 RBAC registry",
        "Every governed permission and its exact holders. role_hierarchy is "
        "null: there is nothing to describe, and an empty object would read "
        "as a hierarchy that happens to be empty today.")
    schema.update({
        "type": "object",
        "required": ["rbac_registry_version", "registry_digest", "roles",
                     "role_hierarchy", "permission_count", "permissions",
                     "matrix", "permissions_by_role"],
        "additionalProperties": True,
        "properties": {
            "rbac_registry_version": {"const": RBAC_REGISTRY_VERSION},
            "registry_digest": _DIGEST,
            "roles": {"type": "array", "minItems": 3,
                      "items": {"type": "string", "enum": _ROLES}},
            # Null, not an object and not an empty array. There is no
            # hierarchy, and a schema permitting one would be a schema that
            # accepts the document describing one.
            "role_hierarchy": {"type": "null"},
            "permission_count": {"type": "integer",
                                 "minimum": len(PERMISSION_IDS)},
            "permissions": {
                "type": "array",
                "minItems": len(PERMISSION_IDS),
                "items": {
                    "type": "object",
                    "required": ["permission_id", "title", "area",
                                 "rationale", "holders"],
                    "additionalProperties": False,
                    "properties": {
                        "permission_id": {"type": "string", "minLength": 3},
                        "title": {"type": "string", "minLength": 3},
                        "area": {"type": "string", "minLength": 3},
                        "rationale": {"type": "string", "minLength": 40},
                        "holders": {"type": "array", "minItems": 1,
                                    "items": {"type": "string",
                                              "enum": _ROLES}}}}},
            "matrix": {"type": "object"},
            "permissions_by_role": {"type": "object"},
            "admin_is_not_a_reviewer": {"type": "string", "minLength": 40},
        },
    })
    return schema


def _audit_event_schema() -> Dict[str, Any]:
    schema = _envelope(
        "governed-audit-event.schema.json", "WP-23 governed audit event",
        "One hash-linked record of one governed action. Session assurance "
        "requires the session mechanism and a named session, so a static "
        "development token cannot describe itself as a person.")
    schema.update({
        "type": "object",
        "required": ["schema_version", "event_id", "stream_id", "sequence",
                     "action", "outcome", "result_code", "object_type",
                     "object_id", "occurred_at", "actor_id", "actor_role",
                     "auth_mechanism", "auth_assurance", "session_reference",
                     "request_id", "input_hash", "output_hash", "software_id",
                     "software_hash", "dataset_id", "dataset_hash",
                     "ruleset_id", "ruleset_hash", "release_id",
                     "release_manifest_hash", "metadata", "previous_hash",
                     "event_hash"],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"const": AUDIT_EVENT_VERSION},
            "event_id": {"type": "string", "minLength": 1},
            "stream_id": {"type": "string", "minLength": 1},
            "sequence": {"type": "integer", "minimum": 1},
            "action": {"type": "string", "enum": list(AUDIT_ACTIONS)},
            "outcome": {"type": "string",
                        "enum": ["SUCCESS", "REFUSED", "FAILED"]},
            "result_code": {"type": "string", "minLength": 1},
            "object_type": {"type": "string", "enum": list(OBJECT_TYPES)},
            "object_id": {"type": "string", "minLength": 1},
            "occurred_at": _TIMESTAMP,
            "actor_id": _NULLABLE_STRING,
            "actor_role": {"anyOf": [{"type": "string", "enum": _ROLES},
                                     {"type": "null"}]},
            "auth_mechanism": {"type": "string",
                               "enum": ["NONE", "STATIC_TOKEN", "SESSION"]},
            "auth_assurance": {"type": "string",
                               "enum": list(AUTH_ASSURANCE_VALUES)},
            "session_reference": _NULLABLE_STRING,
            "request_id": _NULLABLE_STRING,
            "input_hash": _NULLABLE_DIGEST,
            "output_hash": _NULLABLE_DIGEST,
            "software_id": _NULLABLE_STRING,
            "software_hash": _NULLABLE_DIGEST,
            "dataset_id": _NULLABLE_STRING,
            "dataset_hash": _NULLABLE_DIGEST,
            "ruleset_id": _NULLABLE_STRING,
            "ruleset_hash": _NULLABLE_DIGEST,
            "release_id": _NULLABLE_STRING,
            "release_manifest_hash": _NULLABLE_DIGEST,
            "metadata": {"type": "object"},
            "previous_hash": _NULLABLE_DIGEST,
            "event_hash": _DIGEST,
        },
        "allOf": [
            {
                "if": {"properties": {"auth_assurance": {"const": "SESSION"}},
                       "required": ["auth_assurance"]},
                "then": {"properties": {
                    "auth_mechanism": {"const": "SESSION"},
                    "session_reference": {"type": "string", "minLength": 1}}},
            },
            {
                # The first event starts the chain and nothing precedes it.
                "if": {"properties": {"sequence": {"const": 1}},
                       "required": ["sequence"]},
                "then": {"properties": {"previous_hash": {"type": "null"}}},
            },
        ],
    })
    return schema


def _audit_verification_schema() -> Dict[str, Any]:
    schema = _envelope(
        "audit-verification-result.schema.json",
        "WP-23 audit verification result",
        "Whether the chain is intact and, if not, where it first is not. It "
        "carries no event content: a verification report that quoted the "
        "offending record would be a way to read the trail through a command "
        "that only checks it.")
    schema.update({
        "type": "object",
        "required": ["audit_event_schema_version", "verified",
                     "event_count", "first_break_sequence", "reason",
                     "reports_no_event_content"],
        "additionalProperties": False,
        "properties": {
            "audit_event_schema_version": {"const": AUDIT_EVENT_VERSION},
            "verified": _NULLABLE_BOOL,
            "event_count": _NULLABLE_INT,
            "head_sequence": _NULLABLE_INT,
            "first_break_sequence": _NULLABLE_INT,
            "reason": {"type": "string", "minLength": 3},
            "reports_no_event_content": {"const": True},
        },
        "allOf": [{
            "if": {"properties": {"verified": {"const": True}},
                   "required": ["verified"]},
            "then": {"properties": {"first_break_sequence": {"type": "null"}}},
        }],
    })
    return schema


def _rate_limit_schema() -> Dict[str, Any]:
    schema = _envelope(
        "rate-limit-policy.schema.json", "WP-23 rate-limit policy",
        "Declared limits, before any result is observed. Reports no "
        "throughput, latency or load figure: WP-24 owns those.")
    schema.update({
        "type": "object",
        "required": ["rate_limit_policy_version", "policy_count", "policies",
                     "window_semantics", "key_semantics",
                     "failure_semantics", "proxy_header_policy"],
        "additionalProperties": True,
        "properties": {
            "rate_limit_policy_version": {"const": RATE_LIMIT_POLICY_VERSION},
            "policy_count": {"type": "integer", "minimum": 3},
            "policies": {
                "type": "array", "minItems": 3,
                "items": {
                    "type": "object",
                    "required": ["policy_id", "title", "scope", "limit",
                                 "window_seconds", "retry_after_seconds",
                                 "rationale"],
                    "additionalProperties": False,
                    "properties": {
                        "policy_id": {"type": "string", "minLength": 3},
                        "title": {"type": "string", "minLength": 3},
                        "scope": {"type": "string",
                                  "enum": ["username_digest",
                                           "origin_digest", "actor_digest"]},
                        "limit": {"type": "integer", "minimum": 1},
                        "window_seconds": {"type": "integer", "minimum": 1},
                        "retry_after_seconds": {"type": "integer",
                                                "minimum": 1,
                                                "maximum": 3600},
                        "rationale": {"type": "string", "minLength": 40}}}},
            "window_semantics": {"type": "string", "minLength": 40},
            "key_semantics": {"type": "string", "minLength": 40},
            "failure_semantics": {"type": "string", "minLength": 40},
            "proxy_header_policy": {"type": "string", "minLength": 40},
        },
    })
    return schema


def _secret_scan_schema() -> Dict[str, Any]:
    schema = _envelope(
        "secret-scan-report.schema.json", "WP-23 secret scan report",
        "Locations and rule ids. A finding has a path, a line and a rule and "
        "no property a matched value could occupy - a scanner that printed "
        "what it found would be the disclosure it exists to prevent.")
    finding = {
        "type": "object",
        "required": ["path", "line", "rule_id", "severity", "classification",
                     "matched_length"],
        # The whole schema. There is no `value`, `match`, `snippet` or
        # `context` property, and additionalProperties is false so one cannot
        # be added by a producer.
        "additionalProperties": False,
        "properties": {
            "path": {"type": "string", "minLength": 1},
            "line": {"type": "integer", "minimum": 0},
            "rule_id": {"type": "string", "minLength": 3},
            "severity": {"type": "string",
                         "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"]},
            "classification": {"type": "string",
                               "enum": ["FINDING", "ALLOWLISTED",
                                        "NEGATIVE_FIXTURE"]},
            "matched_length": {"type": "integer", "minimum": 0},
        },
    }
    schema.update({
        "type": "object",
        "required": ["secret_scan_version", "rule_count", "rules",
                     "allowlist", "scanned_file_count", "finding_count",
                     "findings", "status", "no_value_is_reported",
                     "allowlist_policy"],
        "additionalProperties": True,
        "properties": {
            "secret_scan_version": {"const": SECRET_SCAN_VERSION},
            "rule_count": {"type": "integer", "minimum": 1},
            "rules": {
                "type": "array", "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["rule_id", "title", "severity",
                                 "rationale"],
                    # No `pattern` property. A published regex is a published
                    # description of what the scanner does not catch.
                    "additionalProperties": False,
                    "properties": {
                        "rule_id": {"type": "string", "minLength": 3},
                        "title": {"type": "string", "minLength": 3},
                        "severity": {"type": "string", "minLength": 3},
                        "rationale": {"type": "string", "minLength": 40}}}},
            "allowlist": {"type": "array", "items": {"type": "object"}},
            "allowlist_count": {"type": "integer", "minimum": 0},
            "negative_fixtures": {"type": "array",
                                  "items": {"type": "object"}},
            "negative_fixture_count": {"type": "integer", "minimum": 0},
            "scanned_file_count": {"type": "integer", "minimum": 0},
            "finding_count": {"type": "integer", "minimum": 0},
            "findings": {"type": "array", "items": finding},
            "classified_finding_count": {"type": "integer", "minimum": 0},
            "classified_findings": {"type": "array", "items": finding},
            "status": {"type": "string", "enum": ["CLEAN", "FINDINGS"]},
            "no_value_is_reported": {"type": "string", "minLength": 40},
            "allowlist_policy": {"type": "string", "minLength": 40},
        },
        "allOf": [{
            "if": {"properties": {"status": {"const": "CLEAN"}},
                   "required": ["status"]},
            "then": {"properties": {"finding_count": {"const": 0},
                                    "findings": {"type": "array",
                                                 "maxItems": 0}}},
        }],
    })
    return schema


def _backup_status_schema() -> Dict[str, Any]:
    schema = _envelope(
        "backup-restore-status.schema.json", "WP-23 backup and restore status",
        "The documented plan and what has actually run. Nothing has: the "
        "three execution flags are const false, so a document claiming a "
        "verified restore cannot be published without changing this file.")
    schema.update({
        "type": "object",
        "required": ["backup_plan_version", "backup_procedure_documented",
                     "runbook", "scope_item_count", "scope",
                     "encrypted_storage_required", "backup_executed",
                     "restore_executed", "restore_verified",
                     "operational_status", "owner_split",
                     "restore_verification_procedure"],
        "additionalProperties": True,
        "properties": {
            "backup_plan_version": {"const": BACKUP_PLAN_VERSION},
            "backup_procedure_documented": {"type": "boolean"},
            "runbook": {"type": "string", "minLength": 5},
            "scope_item_count": {"type": "integer", "minimum": 1},
            "scope": {
                "type": "array", "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["item_id", "title", "kind",
                                 "encrypted_at_rest_required",
                                 "retention_days", "rotation",
                                 "loss_consequence"],
                    "additionalProperties": False,
                    "properties": {
                        "item_id": {"type": "string", "minLength": 3},
                        "title": {"type": "string", "minLength": 3},
                        "kind": {"type": "string",
                                 "enum": ["POSTGRESQL", "ARTIFACT",
                                          "RESTRICTED"]},
                        "encrypted_at_rest_required": {"type": "boolean"},
                        "retention_days": {"type": "integer", "minimum": 1},
                        "rotation": {"type": "string", "minLength": 3},
                        "loss_consequence": {"type": "string",
                                             "minLength": 40}}}},
            "encrypted_storage_required": {"type": "boolean"},
            # Nothing has run. These are const rather than boolean because a
            # boolean is a field a caller can set, and the only way to set
            # these truthfully is to have executed something.
            "backup_executed": {"const": False},
            "restore_executed": {"const": False},
            "restore_verified": {"const": False},
            "operational_status": {
                "type": "string",
                "enum": list(OperationalStatus.ALL)},
            "preflight": {"type": "object"},
            "owner_split": {"type": "string", "minLength": 40},
            "restore_verification_procedure": {"type": "string",
                                               "minLength": 40},
        },
        "allOf": [{
            "if": {"properties": {"operational_status":
                                  {"const": "EXECUTED_VERIFIED"}},
                   "required": ["operational_status"]},
            "then": {"properties": {"backup_executed": {"const": True},
                                    "restore_executed": {"const": True},
                                    "restore_verified": {"const": True}}},
        }],
    })
    return schema


def _gate_status_schema() -> Dict[str, Any]:
    schema = _envelope(
        "wp23-gate-status.schema.json", "WP-23 gate status",
        "Three separate answers: the security software is implemented, this "
        "deployment has configured none of it, and nothing is operating. "
        "PASS demands every operational precondition at once.")
    schema.update({
        "type": "object",
        "required": ["gate_status_schema_version", "work_package",
                     "implementation_status", "security_gate_status",
                     "release_may_proceed", "security_software_implemented",
                     "authentication_software_implemented",
                     "session_management_implemented", "csrf_implemented",
                     "rate_limiting_implemented",
                     "canonical_audit_implemented",
                     "argon2_dependency_declared", "argon2_available",
                     "database_available", "authentication_configured",
                     "csrf_operational", "rate_limiting_operational",
                     "https_termination_observed", "real_users_configured",
                     "audit_chain_verified", "secret_scan_status",
                     "backup_procedure_documented", "backup_executed",
                     "restore_executed", "restore_verified",
                     "expert_review_performed",
                     "clinical_validation_performed", "role_hierarchy",
                     "blockers", "blocking_count",
                     "implemented_is_not_operational",
                     "not_a_security_certification"],
        "additionalProperties": True,
        "properties": {
            "gate_status_schema_version": {"const": GATE_STATUS_VERSION},
            "work_package": {"const": "WP-23"},
            "implementation_status": {"type": "string",
                                      "enum": ["IMPLEMENTED",
                                               "NOT_IMPLEMENTED"]},
            "security_gate_status": {"type": "string",
                                     "enum": ["PASS", "BLOCKED", "FAILED"]},
            "release_may_proceed": {"type": "boolean"},
            "security_software_implemented": {"type": "boolean"},
            "authentication_software_implemented": {"type": "boolean"},
            "session_management_implemented": {"type": "boolean"},
            "csrf_implemented": {"type": "boolean"},
            "rate_limiting_implemented": {"type": "boolean"},
            "canonical_audit_implemented": {"type": "boolean"},
            "password_policy": {"type": "object"},
            "session_policy": {"type": "object"},
            "role_hierarchy": {"type": "null"},
            "argon2_dependency_declared": {"const": True},
            "argon2_available": {"type": "boolean"},
            "database_available": {"type": "boolean"},
            "migration_0011_present": {"type": "boolean"},
            "migration_0011_executed": {"const": False},
            "authentication_configured": {"type": "boolean"},
            "csrf_operational": {"type": "boolean"},
            "rate_limiting_operational": {"type": "boolean"},
            "https_termination_observed": {"type": "boolean"},
            # Nullable on purpose: null means no store was inspected, zero
            # means an inspected store held none. Collapsing them would let
            # "we did not look" read as "we looked and found none".
            "real_users_configured": _NULLABLE_INT,
            "governed_audit_event_count": _NULLABLE_INT,
            "audit_chain_verified": _NULLABLE_BOOL,
            "session_authentication_exercised_operationally": {
                "type": "boolean"},
            "secret_scan_status": {"type": "string",
                                   "enum": ["CLEAN", "FINDINGS", "NOT_RUN"]},
            "secret_scan_finding_count": _NULLABLE_INT,
            "backup_procedure_documented": {"type": "boolean"},
            "backup_executed": {"const": False},
            "restore_executed": {"const": False},
            "restore_verified": {"const": False},
            # WP-23 cannot produce either of these, whatever it configures.
            "expert_review_performed": {"const": False},
            "clinical_validation_performed": {"const": False},
            "claim_boundary_approved": {"type": "boolean"},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "blocking_count": {"type": "integer", "minimum": 0},
            "implemented_is_not_operational": {"type": "string",
                                               "minLength": 40},
            "not_a_security_certification": {"type": "string",
                                             "minLength": 40},
        },
        "allOf": [{
            "if": {"properties": {"security_gate_status": {"const": "PASS"}},
                   "required": ["security_gate_status"]},
            "then": {"properties": {
                "argon2_available": {"const": True},
                "database_available": {"const": True},
                "migration_0011_executed": {"const": True},
                "authentication_configured": {"const": True},
                "https_termination_observed": {"const": True},
                "audit_chain_verified": {"const": True},
                "restore_verified": {"const": True},
                "real_users_configured": {"type": "integer", "minimum": 1}}},
        }],
    })
    return schema


def build_schemas() -> Dict[str, Dict[str, Any]]:
    """Every WP-23 schema, by committed path."""
    return {
        USER_PROJECTION_SCHEMA_PATH: _user_projection_schema(),
        SESSION_PROJECTION_SCHEMA_PATH: _session_projection_schema(),
        RBAC_REGISTRY_SCHEMA_PATH: _rbac_registry_schema(),
        AUDIT_EVENT_SCHEMA_PATH: _audit_event_schema(),
        AUDIT_VERIFICATION_SCHEMA_PATH: _audit_verification_schema(),
        RATE_LIMIT_SCHEMA_PATH: _rate_limit_schema(),
        SECRET_SCAN_SCHEMA_PATH: _secret_scan_schema(),
        BACKUP_STATUS_SCHEMA_PATH: _backup_status_schema(),
        GATE_STATUS_SCHEMA_PATH: _gate_status_schema(),
    }


def _validate(document: Mapping[str, Any],
              schema: Mapping[str, Any]) -> List[str]:
    return list(validate_against_schema(document, schema))


def validate_user_projection(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _user_projection_schema())


def validate_session_projection(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _session_projection_schema())


def validate_rbac_registry(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _rbac_registry_schema())


def validate_audit_event(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _audit_event_schema())


def validate_audit_verification(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _audit_verification_schema())


def validate_rate_limit_policy(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _rate_limit_schema())


def validate_secret_scan_report(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _secret_scan_schema())


def validate_backup_status(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _backup_status_schema())


def validate_wp23_gate_status(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _gate_status_schema())
