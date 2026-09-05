# -*- coding: utf-8 -*-
"""Governed actions, outcomes and object types (WP-23).

The registry below is the answer to "what must be audited". A test walks the
governed services and fails if any of them performs an action with no entry
here, so the registry cannot quietly fall behind the code it describes.

Actions are named by area and verb, and the area prefix is load-bearing: it is
what lets the coverage test assert that every expert-review transition has a
mapping without listing them one by one, and what lets a reader see a whole
governed surface at once.
"""

from __future__ import annotations

from enum import Enum
from typing import FrozenSet, Mapping, Tuple

__all__ = [
    "AUDIT_ACTIONS",
    "AUDIT_ACTION_AREAS",
    "AUDIT_EVENT_VERSION",
    "GOVERNED_ACTION_REGISTRY",
    "OBJECT_TYPES",
    "PROHIBITED_AUDIT_FIELDS",
    "TYPED_METADATA_KEYS",
    "AuditOutcome",
    "GovernedAction",
    "actions_for_area",
]

AUDIT_EVENT_VERSION = "pgx-wp23-governed-audit-event/1"


class _AuditEnum(str, Enum):
    def __str__(self) -> str:
        return self.value

    def __lt__(self, other: object) -> bool:  # pragma: no cover - guard
        raise TypeError("%s values are not ordered" % type(self).__name__)

    __gt__ = __le__ = __ge__ = __lt__


class AuditOutcome(_AuditEnum):
    """Whether the governed action happened.

    ``REFUSED`` is a first-class outcome, not an absence of one. A trail that
    recorded only successes would answer "what was done" and never "what was
    attempted", and the second question is the one an investigation starts
    with.
    """

    SUCCESS = "SUCCESS"
    REFUSED = "REFUSED"
    FAILED = "FAILED"


class GovernedAction(_AuditEnum):
    """Every action that must produce a canonical audit event."""

    # -- authentication and accounts ------------------------------------
    USER_BOOTSTRAPPED = "USER_BOOTSTRAPPED"
    USER_CREATED = "USER_CREATED"
    USER_DISABLED = "USER_DISABLED"
    USER_ENABLED = "USER_ENABLED"
    USER_LOCKED = "USER_LOCKED"
    USER_UNLOCKED = "USER_UNLOCKED"
    USER_ROLE_CHANGED = "USER_ROLE_CHANGED"
    USER_PASSWORD_CHANGED = "USER_PASSWORD_CHANGED"
    LOGIN_SUCCEEDED = "LOGIN_SUCCEEDED"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    SESSION_CREATED = "SESSION_CREATED"
    SESSION_REVOKED = "SESSION_REVOKED"
    SESSION_EXPIRED = "SESSION_EXPIRED"

    # -- assessment ------------------------------------------------------
    ASSESSMENT_REQUESTED = "ASSESSMENT_REQUESTED"
    ASSESSMENT_COMPLETED = "ASSESSMENT_COMPLETED"
    ASSESSMENT_REFUSED = "ASSESSMENT_REFUSED"

    # -- release ---------------------------------------------------------
    RELEASE_REGISTERED = "RELEASE_REGISTERED"
    RELEASE_ACTIVATED = "RELEASE_ACTIVATED"
    RELEASE_ROLLED_BACK = "RELEASE_ROLLED_BACK"
    RELEASE_RETIRED = "RELEASE_RETIRED"
    RELEASE_REFUSED = "RELEASE_REFUSED"

    # -- curation and rules ----------------------------------------------
    CURATION_REVISION_CREATED = "CURATION_REVISION_CREATED"
    CURATION_REVISION_SUBMITTED = "CURATION_REVISION_SUBMITTED"
    CURATION_REVIEWED = "CURATION_REVIEWED"
    CURATION_APPROVED = "CURATION_APPROVED"
    CURATION_REJECTED = "CURATION_REJECTED"
    CURATION_ADJUDICATED = "CURATION_ADJUDICATED"
    RULE_VALIDATED = "RULE_VALIDATED"
    RULE_DEPRECATED = "RULE_DEPRECATED"
    RULESET_VALIDATED = "RULESET_VALIDATED"
    RULESET_FROZEN = "RULESET_FROZEN"
    RULESET_REOPENED = "RULESET_REOPENED"
    RULESET_RETIRED = "RULESET_RETIRED"

    # -- expert review ---------------------------------------------------
    REVIEW_ASSIGNED = "REVIEW_ASSIGNED"
    REVIEW_EXPECTATION_RECORDED = "REVIEW_EXPECTATION_RECORDED"
    REVIEW_RESULT_REVEALED = "REVIEW_RESULT_REVEALED"
    REVIEW_COMPLETED = "REVIEW_COMPLETED"
    REVIEW_CORRECTION_APPENDED = "REVIEW_CORRECTION_APPENDED"
    REVIEW_INVALIDATED = "REVIEW_INVALIDATED"

    # -- audit itself ----------------------------------------------------
    AUDIT_CHAIN_VERIFIED = "AUDIT_CHAIN_VERIFIED"


AUDIT_ACTIONS: Tuple[str, ...] = tuple(item.value for item in GovernedAction)

AUDIT_ACTION_AREAS: Mapping[str, Tuple[str, ...]] = {
    "authentication": (
        "USER_BOOTSTRAPPED", "USER_CREATED", "USER_DISABLED", "USER_ENABLED",
        "USER_LOCKED", "USER_UNLOCKED", "USER_ROLE_CHANGED",
        "USER_PASSWORD_CHANGED", "LOGIN_SUCCEEDED", "LOGIN_FAILED", "LOGOUT",
        "SESSION_CREATED", "SESSION_REVOKED", "SESSION_EXPIRED"),
    "assessment": ("ASSESSMENT_REQUESTED", "ASSESSMENT_COMPLETED",
                   "ASSESSMENT_REFUSED"),
    "release": ("RELEASE_REGISTERED", "RELEASE_ACTIVATED",
                "RELEASE_ROLLED_BACK", "RELEASE_RETIRED", "RELEASE_REFUSED"),
    "curation_and_rules": (
        "CURATION_REVISION_CREATED", "CURATION_REVISION_SUBMITTED",
        "CURATION_REVIEWED", "CURATION_APPROVED", "CURATION_REJECTED",
        "CURATION_ADJUDICATED", "RULE_VALIDATED", "RULE_DEPRECATED",
        "RULESET_VALIDATED", "RULESET_FROZEN", "RULESET_REOPENED",
        "RULESET_RETIRED"),
    "expert_review": (
        "REVIEW_ASSIGNED", "REVIEW_EXPECTATION_RECORDED",
        "REVIEW_RESULT_REVEALED", "REVIEW_COMPLETED",
        "REVIEW_CORRECTION_APPENDED", "REVIEW_INVALIDATED"),
    "audit": ("AUDIT_CHAIN_VERIFIED",),
}

#: The object a governed action acts on. A closed vocabulary, so an event
#: cannot name an object type nobody can look up.
OBJECT_TYPES: Tuple[str, ...] = (
    "USER", "SESSION", "ASSESSMENT", "RELEASE_BUNDLE", "CURATION_WORK_ITEM",
    "CURATION_REVISION", "COMPUTABLE_RULE", "RULESET_VERSION",
    "EXPERT_REVIEW", "AUDIT_STREAM",
)

#: Governed actions whose *successful* completion requires the audit append to
#: succeed in the same transaction. Every state change is here; the read-only
#: verification action is not, because a failed append there loses a log line
#: rather than orphaning a state change.
_ATOMIC_EXEMPT: FrozenSet[str] = frozenset({
    "LOGIN_FAILED", "SESSION_EXPIRED", "AUDIT_CHAIN_VERIFIED",
    "ASSESSMENT_REFUSED", "RELEASE_REFUSED"})

GOVERNED_ACTION_REGISTRY: Mapping[str, Mapping[str, object]] = {
    action.value: {
        "area": area,
        "requires_atomic_audit": action.value not in _ATOMIC_EXEMPT,
    }
    for area, names in AUDIT_ACTION_AREAS.items()
    for action in GovernedAction
    if action.value in names
}

#: Keys a caller may place in an event's typed metadata. There is deliberately
#: no free-form bucket: a mapping that accepted arbitrary keys would sooner or
#: later receive a request body, because the place that builds an audit event
#: is the place that has one.
TYPED_METADATA_KEYS: Tuple[str, ...] = (
    "previous_state", "new_state", "policy_id", "refusal_detail_code",
    "session_reference", "target_user_id", "target_role", "revision",
    "revocation_reason", "protocol_hash", "case_manifest_hash",
    "assignment_id", "review_id", "chain_head_sequence", "rehashed",
)

#: Field names an audit event may never carry, at any nesting depth. Checked
#: on construction, so this is a refusal rather than a convention.
PROHIBITED_AUDIT_FIELDS: FrozenSet[str] = frozenset({
    "password", "password_hash", "passphrase", "secret", "token",
    "session_token", "csrf_token", "cookie", "authorization", "auth_header",
    "set_cookie", "credential", "api_key", "private_key", "dsn",
    "database_url", "connection_string",
    "phenotype", "phenotype_profile", "genotype", "diplotype", "vcf",
    "medications", "medication_list", "patient", "patient_id", "mrn",
    "date_of_birth", "ehr", "clinical_record",
    "holdout_payload", "expected_response", "expected_attention_level",
    "expected_coverage_status", "reviewer_note", "correction_replacement",
    "request_body", "body", "payload", "file_path", "filesystem_path",
    "traceback", "stack_trace",
})


def actions_for_area(area: str) -> Tuple[str, ...]:
    if area not in AUDIT_ACTION_AREAS:
        raise KeyError("%r is not a declared audit area" % area)
    return AUDIT_ACTION_AREAS[area]
