# -*- coding: utf-8 -*-
"""Published JSON Schemas for WP-22.

Ten schemas, and as in WP-21 the constraints that matter are the negative
ones. A schema that only described the happy shape would accept a protocol
manifest claiming approval with no signatories, or a public summary reporting
"92% agreement" over zero completed reviews - which are exactly the two
documents nobody should be able to publish.

So these schemas pin, with ``const`` where the value is a fact about this
repository rather than a variable:

- ``expert_review_performed``, ``clinical_validation_performed`` and
  ``scientific_validation_performed`` are ``false``. Flipping any of them
  needs this file to change in the open.
- An approved protocol manifest must carry all four required signatory roles
  and a non-empty signatory list. ``approved: true`` with an empty list is
  unrepresentable.
- A public summary whose ``completed_review_count`` is zero must carry a
  ``null`` agreement distribution and null Likert summaries. The "0%" that
  means "nobody reviewed anything" cannot be written down.
- An audit event may claim ``actor_authenticated: true`` only alongside
  ``auth_assurance: SESSION``. WP-22 pinned the field ``const: false``
  because no authentication existed; WP-23 supplied one, and changed the pin
  here rather than deleting it - a fixture still cannot describe itself as a
  person.
- A reveal record must name the expectation revision hash it pinned. There is
  no reveal shape without one, so a result cannot be attached to a review
  whose expectation is unidentified.

Written against the supported subset of JSON Schema that
``pgx.application.snapshot_schema.validate_against_schema`` implements - no
``patternProperties``, so keyed maps are described as objects rather than
pattern matched.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from pgx.application.snapshot_schema import validate_against_schema
from pgx.expert_review.gate_status import GATE_STATUS_VERSION
from pgx.expert_review.audit import AUDIT_EVENT_VERSION
from pgx.expert_review.permits import PERMIT_VERSION
from pgx.expert_review.protocol import (PROTOCOL_VERSION,
                                        REQUIRED_SIGNATORY_ROLES)
from pgx.expert_review.vocabulary import (AuditAction, CorrectionKind,
                                          ExpertDecision, InvalidationReason,
                                          LIKERT_DIMENSIONS, LIKERT_MAXIMUM,
                                          LIKERT_MINIMUM, RationaleCode,
                                          REVIEW_ERROR_CODES, ReviewState,
                                          VOCABULARY_VERSION)

__all__ = [
    "ASSIGNMENT_SCHEMA_PATH",
    "AUDIT_EVENT_SCHEMA_PATH",
    "COMPLETION_SCHEMA_PATH",
    "CORRECTION_SCHEMA_PATH",
    "EXPECTATION_SCHEMA_PATH",
    "GATE_STATUS_SCHEMA_PATH",
    "PERMIT_SCHEMA_PATH",
    "PROTOCOL_MANIFEST_SCHEMA_PATH",
    "PUBLIC_SUMMARY_SCHEMA_PATH",
    "REVEAL_SCHEMA_PATH",
    "WORKFLOW_SCHEMA_PATH",
    "build_schemas",
    "validate_audit_event",
    "validate_completion",
    "validate_correction",
    "validate_expectation",
    "validate_payload_permit",
    "validate_protocol_manifest",
    "validate_public_summary",
    "validate_review_assignment",
    "validate_review_workflow",
    "validate_reveal_record",
    "validate_wp22_gate_status",
]

PROTOCOL_MANIFEST_SCHEMA_PATH = "schemas/wp22/expert-protocol-manifest.schema.json"
WORKFLOW_SCHEMA_PATH = "schemas/wp22/review-workflow.schema.json"
ASSIGNMENT_SCHEMA_PATH = "schemas/wp22/review-assignment.schema.json"
EXPECTATION_SCHEMA_PATH = "schemas/wp22/expectation-revision.schema.json"
REVEAL_SCHEMA_PATH = "schemas/wp22/reveal-record.schema.json"
COMPLETION_SCHEMA_PATH = "schemas/wp22/completion-decision.schema.json"
CORRECTION_SCHEMA_PATH = "schemas/wp22/review-correction.schema.json"
AUDIT_EVENT_SCHEMA_PATH = "schemas/wp22/review-audit-event.schema.json"
PERMIT_SCHEMA_PATH = "schemas/wp22/payload-permit.schema.json"
PUBLIC_SUMMARY_SCHEMA_PATH = "schemas/wp22/review-public-summary.schema.json"
GATE_STATUS_SCHEMA_PATH = "schemas/wp22/wp22-gate-status.schema.json"

_BASE = "https://pgx.local/schemas/wp22/"
_DRAFT = "https://json-schema.org/draft/2020-12/schema"

_DIGEST = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
_NULLABLE_DIGEST = {"anyOf": [_DIGEST, {"type": "null"}]}
_NULLABLE_INT = {"anyOf": [{"type": "integer", "minimum": 0},
                           {"type": "null"}]}
_NULLABLE_STRING = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_NULLABLE_OBJECT = {"anyOf": [{"type": "object"}, {"type": "null"}]}
_TIMESTAMP = {"type": "string",
              "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z$"}

_STATES = [item.value for item in ReviewState]
_DECISIONS = [item.value for item in ExpertDecision]
_RATIONALES = [item.value for item in RationaleCode]
_CORRECTION_KINDS = [item.value for item in CorrectionKind]
_INVALIDATIONS = [item.value for item in InvalidationReason]
_AUDIT_ACTIONS = [item.value for item in AuditAction]

#: The ten pins every governed record echoes back unchanged. Listed once,
#: required in every record schema: a record that could omit one would be a
#: record whose subject is not fully identified.
_PIN_PROPERTIES: Dict[str, Any] = {
    "protocol_hash": _DIGEST,
    "release_public_id": {"type": "string", "minLength": 1},
    "release_manifest_hash": _DIGEST,
    "software_version": {"type": "string", "minLength": 1},
    "software_hash": _DIGEST,
    "dataset_public_id": {"type": "string", "minLength": 1},
    "dataset_content_hash": _DIGEST,
    "ruleset_public_id": {"type": "string", "minLength": 1},
    "ruleset_content_hash": _DIGEST,
    "case_manifest_hash": _DIGEST,
}


def _envelope(name: str, title: str, description: str) -> Dict[str, Any]:
    return {"$id": _BASE + name, "$schema": _DRAFT, "title": title,
            "description": description}


def _protocol_manifest_schema() -> Dict[str, Any]:
    """The protocol and who signed it.

    The ``if/then`` is the whole schema: ``approved`` may be ``true`` only
    alongside a documented digest, every required signatory role and a
    non-empty list. An approval assembled out of blanks is not expressible.
    """
    schema = _envelope(
        "expert-protocol-manifest.schema.json",
        "WP-22 blind review protocol manifest",
        "The protocol document, its digest, and the named people who "
        "approved it. Approval is a list of signatories rather than a "
        "boolean, so it cannot be set - only supplied.")
    schema.update({
        "type": "object",
        "required": ["protocol_version", "document_path", "document_digest",
                     "documented", "status", "approved",
                     "required_signatory_roles", "signatory_count",
                     "missing_signatory_roles", "signatories",
                     "protocol_hash"],
        "additionalProperties": True,
        "properties": {
            "protocol_version": {"const": PROTOCOL_VERSION},
            "document_path": {"type": "string", "minLength": 1},
            "document_digest": _NULLABLE_DIGEST,
            "documented": {"type": "boolean"},
            "status": {"type": "string", "minLength": 3},
            "approved": {"type": "boolean"},
            "required_signatory_roles": {
                "type": "array",
                "items": {"type": "string",
                          "enum": list(REQUIRED_SIGNATORY_ROLES)}},
            "signatory_count": {"type": "integer", "minimum": 0},
            "missing_signatory_roles": {"type": "array",
                                        "items": {"type": "string"}},
            "signatories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "affiliation", "role", "decided_on",
                                 "approved_document_digest",
                                 "record_reference"],
                    "additionalProperties": True,
                    "properties": {
                        "name": {"type": "string", "minLength": 2},
                        "affiliation": {"type": "string", "minLength": 2},
                        "role": {"type": "string",
                                 "enum": list(REQUIRED_SIGNATORY_ROLES)},
                        "decided_on": {"type": "string",
                                       "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
                        "approved_document_digest": _DIGEST,
                        "record_reference": {"type": "string",
                                             "minLength": 2}}}},
            "protocol_hash": _DIGEST,
            "note": {"type": "string"},
        },
        "allOf": [{
            "if": {"properties": {"approved": {"const": True}},
                   "required": ["approved"]},
            "then": {"properties": {
                "documented": {"const": True},
                "document_digest": _DIGEST,
                "signatory_count": {"type": "integer",
                                    "minimum": len(REQUIRED_SIGNATORY_ROLES)},
                "missing_signatory_roles": {"type": "array", "maxItems": 0},
                "signatories": {"type": "array",
                                "minItems": len(REQUIRED_SIGNATORY_ROLES)}}},
        }],
    })
    return schema


def _workflow_schema() -> Dict[str, Any]:
    """The state machine, published so a reader need not read the code."""
    schema = _envelope(
        "review-workflow.schema.json",
        "WP-22 blind review workflow",
        "States, permitted transitions, refusal codes and the ordering the "
        "protocol depends on. Published so the order is auditable without "
        "reading the implementation.")
    schema.update({
        "type": "object",
        "required": ["schema_version", "vocabulary_version", "states",
                     "transitions", "terminal_states", "error_codes",
                     "ordering_note"],
        "additionalProperties": True,
        "properties": {
            "schema_version": {"type": "string", "minLength": 3},
            "vocabulary_version": {"const": VOCABULARY_VERSION},
            "states": {"type": "array", "minItems": len(_STATES),
                       "items": {"type": "string", "enum": _STATES}},
            "transitions": {"type": "object"},
            "terminal_states": {"type": "array",
                                "items": {"type": "string", "enum": _STATES}},
            "decisions": {"type": "array",
                          "items": {"type": "string", "enum": _DECISIONS}},
            "rationale_codes": {"type": "array",
                                "items": {"type": "string",
                                          "enum": _RATIONALES}},
            "correction_kinds": {"type": "array",
                                 "items": {"type": "string",
                                           "enum": _CORRECTION_KINDS}},
            "invalidation_reasons": {"type": "array",
                                     "items": {"type": "string",
                                               "enum": _INVALIDATIONS}},
            "audit_actions": {"type": "array",
                              "items": {"type": "string",
                                        "enum": _AUDIT_ACTIONS}},
            "likert_dimensions": {"type": "array",
                                  "items": {"type": "string",
                                            "enum": list(LIKERT_DIMENSIONS)}},
            "likert_minimum": {"const": LIKERT_MINIMUM},
            "likert_maximum": {"const": LIKERT_MAXIMUM},
            "error_codes": {"type": "object"},
            "error_code_count": {"type": "integer",
                                 "minimum": len(REVIEW_ERROR_CODES)},
            "ordering_note": {"type": "string", "minLength": 20},
        },
    })
    return schema


def _assignment_schema() -> Dict[str, Any]:
    schema = _envelope(
        "review-assignment.schema.json",
        "WP-22 review assignment",
        "One expert-holdout case assigned to one reviewer under one pinned "
        "release. Every pin is required: an assignment that could omit one "
        "would not identify what was reviewed.")
    properties: Dict[str, Any] = {
        "assignment_id": {"type": "string", "minLength": 1},
        "review_id": {"type": "string", "minLength": 1},
        "case_id": {"type": "string", "minLength": 1},
        "case_role": {"const": "EXPERT_HOLDOUT"},
        "reviewer_actor": {"type": "string", "minLength": 1},
        "reviewer_role": {"const": "EXPERT_REVIEWER"},
        "protocol_version": {"const": PROTOCOL_VERSION},
        "assigned_at": _TIMESTAMP,
        "state": {"type": "string", "enum": _STATES},
    }
    properties.update(_PIN_PROPERTIES)
    schema.update({
        "type": "object",
        "required": sorted(properties),
        "additionalProperties": True,
        "properties": properties,
    })
    return schema


def _expectation_schema() -> Dict[str, Any]:
    """One recorded expectation revision.

    Note what is absent: there is no field here in which a system result
    could be written. The blinding is a property of the shape, not of a
    filtering step somewhere upstream.
    """
    schema = _envelope(
        "expectation-revision.schema.json",
        "WP-22 expected response revision",
        "What the reviewer expected, recorded before anything was revealed. "
        "There is no field for a system result: a revision that could carry "
        "one would not be a blinded record.")
    schema.update({
        "type": "object",
        "required": ["revision_id", "review_id", "revision", "recorded_at",
                     "content_hash", "revision_hash", "previous_hash",
                     "expected_attention_level", "expected_coverage_status",
                     "expected_coverage_reason", "expected_rule_id",
                     "requires_traceable_evidence", "rationale_codes",
                     "reviewer_note"],
        "additionalProperties": False,
        "properties": {
            "revision_id": {"type": "string", "minLength": 1},
            "review_id": {"type": "string", "minLength": 1},
            "revision": {"type": "integer", "minimum": 1},
            "recorded_at": _TIMESTAMP,
            "content_hash": _DIGEST,
            "revision_hash": _DIGEST,
            "previous_hash": _NULLABLE_DIGEST,
            "expected_attention_level": {"type": "string", "minLength": 1},
            "expected_coverage_status": {"type": "string", "minLength": 1},
            "expected_coverage_reason": _NULLABLE_STRING,
            "expected_rule_id": _NULLABLE_STRING,
            "requires_traceable_evidence": {"type": "boolean"},
            "rationale_codes": {"type": "array",
                                "items": {"type": "string",
                                          "enum": _RATIONALES}},
            "reviewer_note": {"type": "string", "maxLength": 1000},
        },
    })
    return schema


def _reveal_schema() -> Dict[str, Any]:
    schema = _envelope(
        "reveal-record.schema.json",
        "WP-22 reveal record",
        "The one-way door and what it pinned. The expectation revision hash "
        "is required, so a revealed result is always attached to the exact "
        "prediction that preceded it and not to one appended afterwards.")
    schema.update({
        "type": "object",
        "required": ["reveal_id", "review_id", "expectation_revision_id",
                     "expectation_revision_hash", "revealed_at",
                     "reveal_hash", "previous_hash", "attention_level",
                     "coverage_status", "coverage_reason", "firing_rule_id",
                     "finding_count", "traceable_finding_count",
                     "output_hash"],
        "additionalProperties": False,
        "properties": {
            "reveal_id": {"type": "string", "minLength": 1},
            "review_id": {"type": "string", "minLength": 1},
            "expectation_revision_id": {"type": "string", "minLength": 1},
            "expectation_revision_hash": _DIGEST,
            "revealed_at": _TIMESTAMP,
            "reveal_hash": _DIGEST,
            "previous_hash": _DIGEST,
            "attention_level": {"type": "string", "minLength": 1},
            "coverage_status": {"type": "string", "minLength": 1},
            "coverage_reason": _NULLABLE_STRING,
            "firing_rule_id": _NULLABLE_STRING,
            "finding_count": {"type": "integer", "minimum": 0},
            "traceable_finding_count": {"type": "integer", "minimum": 0},
            "output_hash": _DIGEST,
        },
    })
    return schema


def _completion_schema() -> Dict[str, Any]:
    schema = _envelope(
        "completion-decision.schema.json",
        "WP-22 completion decision",
        "AGREE, PARTIAL or DISAGREE, with optional Likert ratings. PARTIAL "
        "is a third answer rather than a midpoint, so no schema here orders "
        "or averages the three.")
    schema.update({
        "type": "object",
        "required": ["completion_id", "review_id", "reveal_id", "decision",
                     "ratings", "reviewer_note", "completed_at",
                     "completion_hash", "previous_hash"],
        "additionalProperties": False,
        "properties": {
            "completion_id": {"type": "string", "minLength": 1},
            "review_id": {"type": "string", "minLength": 1},
            # Required and non-null: a completion that did not name a reveal
            # would be a judgement of something never shown.
            "reveal_id": {"type": "string", "minLength": 1},
            "decision": {"type": "string", "enum": _DECISIONS},
            "ratings": {
                "type": "array",
                "maxItems": len(LIKERT_DIMENSIONS),
                "items": {
                    "type": "object",
                    "required": ["dimension", "value"],
                    "additionalProperties": False,
                    "properties": {
                        "dimension": {"type": "string",
                                      "enum": list(LIKERT_DIMENSIONS)},
                        "value": {"type": "integer",
                                  "minimum": LIKERT_MINIMUM,
                                  "maximum": LIKERT_MAXIMUM}}}},
            "reviewer_note": {"type": "string", "maxLength": 1000},
            "completed_at": _TIMESTAMP,
            "completion_hash": _DIGEST,
            "previous_hash": _DIGEST,
        },
    })
    return schema


def _correction_schema() -> Dict[str, Any]:
    schema = _envelope(
        "review-correction.schema.json",
        "WP-22 review correction",
        "An appended amendment. The corrected record is never touched, and "
        "a correction appended after a reveal carries after_reveal true so "
        "it can never be read as the original prediction.")
    schema.update({
        "type": "object",
        "required": ["correction_id", "review_id", "target_hash", "kind",
                     "reason_code", "actor", "actor_role", "recorded_at",
                     "replacement", "after_reveal", "correction_hash",
                     "previous_hash"],
        "additionalProperties": False,
        "properties": {
            "correction_id": {"type": "string", "minLength": 1},
            "review_id": {"type": "string", "minLength": 1},
            "target_hash": _DIGEST,
            "kind": {"type": "string", "enum": _CORRECTION_KINDS},
            "reason_code": {"type": "string", "minLength": 1},
            "actor": {"type": "string", "minLength": 1},
            "actor_role": {"type": "string", "minLength": 1},
            "recorded_at": _TIMESTAMP,
            "replacement": _NULLABLE_OBJECT,
            "after_reveal": {"type": "boolean"},
            "correction_hash": _DIGEST,
            "previous_hash": _NULLABLE_DIGEST,
        },
    })
    return schema


def _audit_event_schema() -> Dict[str, Any]:
    schema = _envelope(
        "review-audit-event.schema.json",
        "WP-22 review audit event",
        "One hash-linked event. actor_authenticated may be true only for a "
        "validated server-side session; a static development token records "
        "TEST_STATIC_TOKEN assurance and stays distinguishable from a person "
        "forever.")
    schema.update({
        "type": "object",
        "required": ["schema_version", "event_id", "sequence", "review_id",
                     "action", "actor", "actor_role", "actor_authenticated",
                     "auth_assurance",
                     "occurred_at", "previous_state", "new_state",
                     "outcome_code", "protocol_hash", "release_manifest_hash",
                     "case_manifest_hash", "record_hashes", "previous_hash",
                     "event_hash"],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"const": AUDIT_EVENT_VERSION},
            "event_id": {"type": "string", "minLength": 1},
            "sequence": {"type": "integer", "minimum": 1},
            "review_id": {"type": "string", "minLength": 1},
            "action": {"type": "string", "enum": _AUDIT_ACTIONS},
            "actor": {"type": "string", "minLength": 1},
            "actor_role": {"type": "string", "minLength": 1},
            # WP-22 pinned this ``const: False`` and said WP-23 would change
            # it in the open. This is that change. It is not simply loosened
            # to ``boolean``: the if/then below requires SESSION assurance
            # alongside a true, so a development fixture still cannot claim
            # to be a person.
            "actor_authenticated": {"type": "boolean"},
            "auth_assurance": {"type": "string",
                               "enum": ["NONE", "TEST_STATIC_TOKEN",
                                        "SESSION"]},
            "occurred_at": _TIMESTAMP,
            "previous_state": {"type": "string", "enum": _STATES},
            "new_state": {"type": "string", "enum": _STATES},
            "outcome_code": {"type": "string", "minLength": 1},
            "protocol_hash": _DIGEST,
            "release_manifest_hash": _DIGEST,
            "case_manifest_hash": _DIGEST,
            "record_hashes": {"type": "object"},
            "previous_hash": _NULLABLE_DIGEST,
            "event_hash": _DIGEST,
        },
        "allOf": [
            {
                # The first event has no predecessor; every later one does. A
                # chain whose second event claimed no predecessor would be two
                # chains presented as one.
                "if": {"properties": {"sequence": {"const": 1}},
                       "required": ["sequence"]},
                "then": {"properties": {"previous_hash": {"type": "null"}}},
            },
            {
                # WP-23. An authenticated actor requires session assurance.
                "if": {"properties": {"actor_authenticated": {"const": True}},
                       "required": ["actor_authenticated"]},
                "then": {"properties":
                         {"auth_assurance": {"const": "SESSION"}}},
            },
        ],
    })
    return schema


def _permit_schema() -> Dict[str, Any]:
    schema = _envelope(
        "payload-permit.schema.json",
        "WP-22 payload permit",
        "A value, never a bearer token: it names the assignment, case, "
        "actor, stage, protocol and release it belongs to, so it authorises "
        "exactly one reviewer to read exactly one case at one stage.")
    schema.update({
        "type": "object",
        "required": ["permit_version", "assignment_id", "review_id",
                     "case_id", "actor", "actor_role", "stage",
                     "protocol_hash", "release_manifest_hash",
                     "case_manifest_hash", "issued_at", "permit_hash"],
        "additionalProperties": False,
        "properties": {
            "permit_version": {"const": PERMIT_VERSION},
            "assignment_id": {"type": "string", "minLength": 1},
            "review_id": {"type": "string", "minLength": 1},
            "case_id": {"type": "string", "minLength": 1},
            "actor": {"type": "string", "minLength": 1},
            "actor_role": {"const": "EXPERT_REVIEWER"},
            "stage": {"type": "string", "enum": _STATES},
            "protocol_hash": _DIGEST,
            "release_manifest_hash": _DIGEST,
            "case_manifest_hash": _DIGEST,
            "issued_at": _TIMESTAMP,
            "permit_hash": _DIGEST,
        },
    })
    return schema


def _public_summary_schema() -> Dict[str, Any]:
    """The aggregate that may be published.

    The ``if/then`` is the point: with zero completed reviews every summary
    field must be ``null``. A distribution over an empty set is not a
    distribution, and "0% agreement" over nobody is the single most
    misleading number this work package could emit.
    """
    schema = _envelope(
        "review-public-summary.schema.json",
        "WP-22 public review summary",
        "The aggregate that may be shown outside the review system. Zero "
        "completed reviews forces every summary to null: a distribution "
        "over an empty set is not a distribution, and a percentage over "
        "nobody is a claim about nobody.")
    schema.update({
        "type": "object",
        "required": ["schema_version", "protocol_version", "generated_note",
                     "completed_review_count", "reviewer_count",
                     "expert_holdout_case_count", "agreement_distribution",
                     "likert_summaries", "expert_review_performed",
                     "clinical_validation_performed",
                     "scientific_validation_performed",
                     "not_clinical_validation"],
        "additionalProperties": True,
        "properties": {
            "schema_version": {"type": "string", "minLength": 3},
            "protocol_version": {"const": PROTOCOL_VERSION},
            "protocol_approved": {"type": "boolean"},
            "generated_note": {"type": "string", "minLength": 20},
            "completed_review_count": {"type": "integer", "minimum": 0},
            "reviewer_count": {"type": "integer", "minimum": 0},
            "expert_holdout_case_count": {"type": "integer", "minimum": 0},
            "invalidated_review_count": _NULLABLE_INT,
            "agreement_distribution": _NULLABLE_OBJECT,
            "likert_summaries": _NULLABLE_OBJECT,
            "free_text_included": {"const": False},
            "reviewer_identities_included": {"const": False},
            # Neither is producible by this work package, whatever it counts.
            "expert_review_performed": {"const": False},
            "clinical_validation_performed": {"const": False},
            "scientific_validation_performed": {"const": False},
            "not_clinical_validation": {"type": "string", "minLength": 20},
        },
        "allOf": [{
            "if": {"properties": {"completed_review_count": {"const": 0}},
                   "required": ["completed_review_count"]},
            "then": {"properties": {
                "agreement_distribution": {"type": "null"},
                "likert_summaries": {"type": "null"},
                "reviewer_count": {"const": 0}}},
        }],
    })
    return schema


def _gate_status_schema() -> Dict[str, Any]:
    schema = _envelope(
        "wp22-gate-status.schema.json",
        "WP-22 gate status",
        "Two separate answers: the review machinery is implemented, and no "
        "expert has reviewed anything. The if/then below makes PASS demand "
        "every precondition at once.")
    schema.update({
        "type": "object",
        "required": ["gate_status_schema_version", "work_package",
                     "implementation_status", "expert_review_gate_status",
                     "release_may_proceed", "expert_review_module_implemented",
                     "protocol_documented", "protocol_approved",
                     "protocol_status", "expert_review_performed",
                     "clinical_validation_performed",
                     "scientific_validation_performed",
                     "completed_review_count", "assigned_review_count",
                     "named_reviewer_count", "expert_holdout_case_count",
                     "active_release_available",
                     "restricted_storage_configured",
                     "production_authentication_available",
                     "authentication_boundary_note", "blockers",
                     "blocking_count", "not_clinical_validation"],
        "additionalProperties": True,
        "properties": {
            "gate_status_schema_version": {"const": GATE_STATUS_VERSION},
            "work_package": {"const": "WP-22"},
            "implementation_status": {"type": "string",
                                      "enum": ["IMPLEMENTED",
                                               "NOT_IMPLEMENTED"]},
            "expert_review_gate_status": {"type": "string",
                                          "enum": ["PASS", "BLOCKED",
                                                   "FAILED"]},
            "release_may_proceed": {"type": "boolean"},
            "expert_review_module_implemented": {"type": "boolean"},
            "module_marker_paths": {"type": "array",
                                    "items": {"type": "string"}},
            "module_marker_present_count": {"type": "integer", "minimum": 0},
            "protocol": {"type": "object"},
            "protocol_documented": {"type": "boolean"},
            "protocol_approved": {"type": "boolean"},
            "protocol_status": {"type": "string", "minLength": 3},
            "required_signatory_roles": {"type": "array",
                                         "items": {"type": "string"}},
            "protocol_signatory_count": {"type": "integer", "minimum": 0},
            "missing_signatory_roles": {"type": "array",
                                        "items": {"type": "string"}},
            "named_reviewer_count": {"type": "integer", "minimum": 0},
            # Nullable on purpose: null means no store was inspected, zero
            # means an inspected store held none. Collapsing the two would
            # let "we did not look" read as "we looked and found none".
            "assigned_review_count": _NULLABLE_INT,
            "completed_review_count": _NULLABLE_INT,
            "review_count_source": {"type": "string"},
            "expert_holdout_case_count": {"type": "integer", "minimum": 0},
            "development_case_count": {"type": "integer", "minimum": 0},
            "active_release_available": {"type": "boolean"},
            "restricted_storage_configured": {"type": "boolean"},
            "production_authentication_available": {"type": "boolean"},
            "authentication_boundary_note": {"type": "string",
                                             "minLength": 20},
            "expert_review_performed": {"const": False},
            "clinical_validation_performed": {"const": False},
            "scientific_validation_performed": {"const": False},
            "claim_boundary_approved": {"type": "boolean"},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "blocking_count": {"type": "integer", "minimum": 0},
            "not_clinical_validation": {"type": "string", "minLength": 20},
        },
        "allOf": [{
            "if": {"properties": {"expert_review_gate_status":
                                  {"const": "PASS"}},
                   "required": ["expert_review_gate_status"]},
            "then": {"properties": {
                "protocol_approved": {"const": True},
                "active_release_available": {"const": True},
                "restricted_storage_configured": {"const": True},
                "production_authentication_available": {"const": True},
                "expert_holdout_case_count": {"type": "integer",
                                              "minimum": 1},
                "named_reviewer_count": {"type": "integer", "minimum": 1},
                "completed_review_count": {"type": "integer", "minimum": 1}}},
        }],
    })
    return schema


def build_schemas() -> Dict[str, Dict[str, Any]]:
    """Every WP-22 schema, by committed path."""
    return {
        PROTOCOL_MANIFEST_SCHEMA_PATH: _protocol_manifest_schema(),
        WORKFLOW_SCHEMA_PATH: _workflow_schema(),
        ASSIGNMENT_SCHEMA_PATH: _assignment_schema(),
        EXPECTATION_SCHEMA_PATH: _expectation_schema(),
        REVEAL_SCHEMA_PATH: _reveal_schema(),
        COMPLETION_SCHEMA_PATH: _completion_schema(),
        CORRECTION_SCHEMA_PATH: _correction_schema(),
        AUDIT_EVENT_SCHEMA_PATH: _audit_event_schema(),
        PERMIT_SCHEMA_PATH: _permit_schema(),
        PUBLIC_SUMMARY_SCHEMA_PATH: _public_summary_schema(),
        GATE_STATUS_SCHEMA_PATH: _gate_status_schema(),
    }


def _validate(document: Mapping[str, Any],
              schema: Mapping[str, Any]) -> List[str]:
    return list(validate_against_schema(document, schema))


def validate_protocol_manifest(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _protocol_manifest_schema())


def validate_review_workflow(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _workflow_schema())


def validate_review_assignment(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _assignment_schema())


def validate_expectation(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _expectation_schema())


def validate_reveal_record(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _reveal_schema())


def validate_completion(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _completion_schema())


def validate_correction(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _correction_schema())


def validate_audit_event(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _audit_event_schema())


def validate_payload_permit(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _permit_schema())


def validate_public_summary(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _public_summary_schema())


def validate_wp22_gate_status(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _gate_status_schema())
