# -*- coding: utf-8 -*-
"""Published schemas for the validation dataset, and their validators (WP-18).

Five documents get schemas, and each is a place somebody could otherwise write
something that ought to be impossible:

``validation-case``
    One case's public metadata. Its ``not`` clause is the load-bearing part:
    the schema *refuses* an expected-answer field rather than merely not
    listing one, so a document carrying one fails validation instead of
    passing with an extra key.

``validation-case-manifest``
    A partition's public listing. Same refusal, plus the separation between
    ``case_count`` and ``target_case_count`` that stops a target being
    rendered as an achievement.

``validation-access-event``
    One who-has-seen record. ``actor_authenticated`` is pinned to ``false``
    by ``const``, so a future writer cannot record an unverified actor as a
    verified one without changing a published schema in the open.

``validation-separation-audit``
    The audit result: issue codes, counts, and no content.

``wp18-gate-status``
    What this repository can say about validation. Counts that may be unknown
    are ``["integer", "null"]``, because null and zero are different answers.

The validator is WP-06's supported subset. Every keyword used here is one it
actually checks - a published constraint that is not checked is a false
assurance, and this module would rather say less than pretend more.
"""

from __future__ import annotations

import io
import json
import os
from typing import Any, Dict, Mapping, Optional, Tuple

from pgx.application.snapshot_schema import validate_against_schema
from pgx.validation.cases import CASE_SCHEMA_VERSION
from pgx.validation.gate_status import GATE_STATUS_VERSION
from pgx.validation.manifests import CASE_MANIFEST_VERSION
from pgx.validation.separation import SEPARATION_AUDIT_VERSION
from pgx.validation.access import ACCESS_EVENT_VERSION

__all__ = [
    "ACCESS_EVENT_SCHEMA_PATH",
    "CASE_MANIFEST_SCHEMA_PATH",
    "CASE_SCHEMA_PATH",
    "GATE_STATUS_SCHEMA_PATH",
    "SEPARATION_AUDIT_SCHEMA_PATH",
    "WP18_SCHEMA_PATHS",
    "build_schemas",
    "load_schema",
    "validate_access_event",
    "validate_case_manifest",
    "validate_separation_audit",
    "validate_validation_case",
    "validate_wp18_gate_status",
]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_SCHEMAS = os.path.join(_REPO_ROOT, "schemas")
_BASE = "https://pgx-platform.invalid/schemas/"

CASE_SCHEMA_PATH = os.path.join(_SCHEMAS, "validation-case.schema.json")
CASE_MANIFEST_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "validation-case-manifest.schema.json")
ACCESS_EVENT_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "validation-access-event.schema.json")
SEPARATION_AUDIT_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "validation-separation-audit.schema.json")
GATE_STATUS_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "wp18-gate-status.schema.json")

WP18_SCHEMA_PATHS: Tuple[str, ...] = (
    CASE_SCHEMA_PATH, CASE_MANIFEST_SCHEMA_PATH, ACCESS_EVENT_SCHEMA_PATH,
    SEPARATION_AUDIT_SCHEMA_PATH, GATE_STATUS_SCHEMA_PATH,
)

_ROLE_ENUM = ["DEVELOPMENT", "INTERNAL_HOLDOUT", "EXPERT_HOLDOUT"]
_DIGEST = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}

#: Field names a public document must not carry. Rendered into the schemas as
#: a ``not``/``required`` refusal, one per name, so validation fails on the
#: presence of the key rather than on its value.
_REFUSED_PUBLIC_FIELDS = (
    "expected_result", "expected_attention", "expected_coverage",
    "expected_findings", "expected_answer", "gold_standard", "ground_truth",
    "reference_answer", "answer_key", "score", "concordance", "accuracy",
    "pass_rate", "payload", "payload_content", "observations", "medications",
    "genotype", "diplotype", "vcf", "patient_name", "mrn", "diagnosis", "dose",
)


def _refuses_public_fields() -> Dict[str, Any]:
    """``not: anyOf[required: [field]]`` - one clause per refused name.

    Spelled as a refusal rather than as ``additionalProperties: false`` alone
    because the message differs: "this document must not carry an expected
    answer" is a statement a reader can act on, and a bare unknown-property
    error is not.
    """
    return {"not": {"anyOf": [{"required": [name]}
                              for name in _REFUSED_PUBLIC_FIELDS]}}


def _compatibility_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "is_pinned_to_release"],
        "properties": {
            "schema_version": {"type": "string"},
            "is_pinned_to_release": {"type": "boolean"},
            "software_version": {"type": "string"},
            "dataset_public_id": {"type": "string",
                                  "pattern": "^PGX-DATA-\\d{8}-\\d{3}$"},
            "ruleset_public_id": {"type": "string",
                                  "pattern": "^PGX-RULESET-\\d{8}-\\d{3}$"},
            "release_public_id": {"type": "string",
                                  "pattern": "^PGX-REL-\\d{8}-\\d{3}$"},
            "release_manifest_hash": dict(_DIGEST),
            "note": {"type": "string"},
        },
    }


def _case_schema() -> Dict[str, Any]:
    schema: Dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "validation-case.schema.json",
        "title": "WP-18 validation case (public metadata)",
        "description": (
            "The publishable half of a validation case. It carries identity, "
            "role, provenance and fingerprints, and it refuses every field an "
            "expected answer could be written into - so a document that "
            "leaked one fails validation rather than passing with an extra "
            "key. The inputs a case presents live in a restricted payload "
            "that is never published and never committed beside the rules it "
            "tests."),
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "case_id", "role", "classification",
                     "visibility", "is_holdout", "is_validation_evidence",
                     "content_fingerprint", "no_pii_assertion", "created_at",
                     "provenance", "compatibility"],
        "properties": {
            "schema_version": {"const": CASE_SCHEMA_VERSION},
            "case_id": {"type": "string",
                        "pattern": "^PGX-VAL-[A-Z0-9][A-Z0-9\\-]{2,46}[A-Z0-9]$"},
            "role": {"enum": _ROLE_ENUM},
            "classification": {"enum": ["SYNTHETIC",
                                        "PUBLISHED_LITERATURE_DERIVED"]},
            "visibility": {"enum": ["PUBLIC_METADATA", "AUTHOR_VISIBLE",
                                    "RESTRICTED"]},
            "is_holdout": {"type": "boolean"},
            "is_validation_evidence": {"type": "boolean"},
            "content_fingerprint": dict(_DIGEST),
            "no_pii_assertion": {"type": "string", "minLength": 16},
            "created_at": {"type": "string", "minLength": 20},
            "payload_hash": dict(_DIGEST),
            "payload_reference": {"type": "string"},
            "title": {"type": "string"},
            "notes": {"type": "string"},
            "extra": {"type": "object"},
            "compatibility": _compatibility_schema(),
            "provenance": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source_identity", "derivation_method",
                             "derived_from_development",
                             "derivation_family_fingerprint"],
                "properties": {
                    "source_identity": {"type": "string", "minLength": 3},
                    "derivation_method": {"type": "string", "minLength": 3},
                    "derived_from_development": {"type": "boolean"},
                    "derivation_family_fingerprint": dict(_DIGEST),
                    "source_digest": dict(_DIGEST),
                    "citation": {"type": "string"},
                    "author": {"type": "string"},
                },
            },
        },
    }
    schema.update(_refuses_public_fields())
    return schema


def _case_manifest_schema() -> Dict[str, Any]:
    schema: Dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "validation-case-manifest.schema.json",
        "title": "WP-18 validation case manifest",
        "description": (
            "One partition's public listing. `case_count` is what exists and "
            "`target_case_count` is what the P0 Definition of Done asks for; "
            "they are separate fields because rendering the target where the "
            "count belongs would be the most misleading thing this document "
            "could do."),
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "partition", "case_count",
                     "is_validation_evidence", "payload_availability",
                     "target_case_count", "cases", "note"],
        "properties": {
            "schema_version": {"const": CASE_MANIFEST_VERSION},
            "partition": {"enum": ["DEVELOPMENT", "HOLDOUT"]},
            "case_count": {"type": "integer", "minimum": 0},
            "development_count": {"type": "integer", "minimum": 0},
            "internal_holdout_count": {"type": "integer", "minimum": 0},
            "expert_holdout_count": {"type": "integer", "minimum": 0},
            "is_validation_evidence": {"type": "boolean"},
            "payload_availability": {"enum": ["NOT_CONFIGURED",
                                              "CONFIGURED_EMPTY",
                                              "CONFIGURED_PRESENT"]},
            "target_case_count": {"type": "integer", "minimum": 0},
            "target_shortfall": {"type": "integer", "minimum": 0},
            "meets_p0_target": {"type": "boolean"},
            "note": {"type": "string", "minLength": 1},
            "cases": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["case_id", "role", "classification",
                                 "visibility", "is_holdout",
                                 "is_validation_evidence",
                                 "content_fingerprint",
                                 "derivation_family_fingerprint",
                                 "source_identity", "derivation_method",
                                 "derived_from_development",
                                 "no_pii_assertion", "created_at",
                                 "compatibility", "metadata_hash"],
                    "properties": {
                        "case_id": {"type": "string"},
                        "role": {"enum": _ROLE_ENUM},
                        "classification": {"type": "string"},
                        "visibility": {"type": "string"},
                        "is_holdout": {"type": "boolean"},
                        "is_validation_evidence": {"type": "boolean"},
                        "content_fingerprint": dict(_DIGEST),
                        "derivation_family_fingerprint": dict(_DIGEST),
                        "source_identity": {"type": "string"},
                        "derivation_method": {"type": "string"},
                        "derived_from_development": {"type": "boolean"},
                        "source_digest": dict(_DIGEST),
                        "citation": {"type": "string"},
                        "no_pii_assertion": {"type": "string"},
                        "created_at": {"type": "string"},
                        "compatibility": _compatibility_schema(),
                        "metadata_hash": dict(_DIGEST),
                        "payload_hash": dict(_DIGEST),
                        "payload_reference": {"type": "string"},
                        "title": {"type": "string"},
                    },
                },
            },
        },
    }
    schema.update(_refuses_public_fields())
    return schema


def _access_event_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "validation-access-event.schema.json",
        "title": "WP-18 validation access event",
        "description": (
            "One who-has-seen record, appended and never edited. "
            "`actor_authenticated` is pinned false: WP-18 records the actor a "
            "caller supplied and does not verify it, and a schema that "
            "allowed true would let an unverified name later read as a "
            "verified one. WP-23 owns identity."),
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "case_id", "case_role", "actor",
                     "actor_authenticated", "context_kind", "action",
                     "allowed", "reason_code", "occurred_at",
                     "manifest_hash"],
        "properties": {
            "schema_version": {"const": ACCESS_EVENT_VERSION},
            "case_id": {"type": "string"},
            "case_role": {"enum": _ROLE_ENUM},
            "actor": {"type": "string", "minLength": 2},
            "actor_authenticated": {"const": False},
            "context_kind": {"enum": ["RULE_AUTHORING", "DEVELOPMENT_WORKFLOW",
                                      "DATASET_CURATION", "EXPERT_REVIEW",
                                      "VALIDATION_RUN", "AUDIT"]},
            "purpose": {"type": "string"},
            "action": {"enum": ["LIST_METADATA", "READ_METADATA",
                                "READ_PAYLOAD", "IMPORT_PAYLOAD",
                                "AUDIT_PARTITION"]},
            "allowed": {"type": "boolean"},
            "reason_code": {"type": "string"},
            "occurred_at": {"type": "string", "minLength": 20},
            "manifest_hash": dict(_DIGEST),
        },
    }


def _separation_audit_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "validation-separation-audit.schema.json",
        "title": "WP-18 separation audit",
        "description": (
            "Whether development and holdout are kept apart, and where they "
            "are not. Carries identifiers and issue codes and no content: an "
            "audit is read by people who may not read the cases it describes, "
            "so one that quoted a duplicated payload in order to explain the "
            "duplicate would publish it."),
        "type": "object",
        "additionalProperties": False,
        "required": ["audit_version", "is_clean", "checked_case_count",
                     "development_count", "internal_holdout_count",
                     "expert_holdout_count", "issue_count", "issue_codes",
                     "issues", "checked_rules"],
        "properties": {
            "audit_version": {"const": SEPARATION_AUDIT_VERSION},
            "is_clean": {"type": "boolean"},
            "checked_case_count": {"type": "integer", "minimum": 0},
            "development_count": {"type": "integer", "minimum": 0},
            "internal_holdout_count": {"type": "integer", "minimum": 0},
            "expert_holdout_count": {"type": "integer", "minimum": 0},
            "issue_count": {"type": "integer", "minimum": 0},
            "issue_codes": {"type": "array", "items": {"type": "string"}},
            "checked_rules": {"type": "array", "items": {"type": "string"},
                              "minItems": 1},
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["code", "case_ids", "meaning", "detail"],
                    "properties": {
                        "code": {"type": "string"},
                        "case_ids": {"type": "array",
                                     "items": {"type": "string"}},
                        "meaning": {"type": "string"},
                        "detail": {"type": "string"},
                    },
                },
            },
        },
    }


def _gate_status_schema() -> Dict[str, Any]:
    nullable_count = {"type": ["integer", "null"], "minimum": 0}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "wp18-gate-status.schema.json",
        "title": "WP-18 validation dataset gate status",
        "description": (
            "What this repository can honestly say about validation. Counts "
            "that could not be measured are null rather than zero: 'nobody "
            "looked' and 'we looked and found none' are different facts, and "
            "a reader acting on them would act differently. The P0 target and "
            "the actual count are separate fields for the same reason."),
        "type": "object",
        "required": ["gate_status_schema_version", "work_package",
                     "implementation_status", "development_case_count",
                     "internal_holdout_case_count",
                     "expert_holdout_case_count", "holdout_case_count",
                     "real_patient_case_count", "p0_target_case_count",
                     "p0_target_met", "restricted_payload_availability",
                     "separation_audit_clean", "claim_boundary_approved",
                     "active_release_available",
                     "validation_metrics_implemented",
                     "expert_review_implemented",
                     "expert_review_performed", "wp19_started",
                     "wp21_started", "wp22_started", "blockers",
                     "may_report_validation_result"],
        "properties": {
            "gate_status_schema_version": {"const": GATE_STATUS_VERSION},
            "work_package": {"const": "WP-18"},
            "implementation_status": {"enum": ["IMPLEMENTED", "PARTIAL",
                                               "NOT_STARTED"]},
            "development_case_count": {"type": "integer", "minimum": 0},
            "internal_holdout_case_count": {"type": "integer", "minimum": 0},
            "expert_holdout_case_count": {"type": "integer", "minimum": 0},
            "holdout_case_count": {"type": "integer", "minimum": 0},
            "real_patient_case_count": {"const": 0},
            "p0_target_case_count": {"type": "integer", "minimum": 1},
            "p0_target_met": {"type": "boolean"},
            "p0_target_shortfall": {"type": "integer", "minimum": 0},
            "restricted_payload_availability": {
                "enum": ["NOT_CONFIGURED", "CONFIGURED_EMPTY",
                         "CONFIGURED_PRESENT"]},
            "restricted_payload_count": dict(nullable_count),
            "validation_metric_count": dict(nullable_count),
            "expert_reviewed_case_count": dict(nullable_count),
            "separation_audit_clean": {"type": "boolean"},
            "claim_boundary_approved": {"const": False},
            "active_release_available": {"const": False},
            # Changed at WP-21, in the open. This was pinned ``False`` while
            # no metric machinery existed. WP-21 built it, so the field
            # becomes a measured boolean - and the fields that would carry a
            # *result* stay pinned, because building the machinery is not
            # running it. ``validation_metric_count`` remains nullable and is
            # null; a computed count would need a benchmark.
            "validation_metrics_implemented": {"type": "boolean"},
            "validation_metric_definition_count": {"type": "integer",
                                                   "minimum": 0},
            "benchmark_gate_status": {"type": "string",
                                      "enum": ["PASS", "BLOCKED", "FAILED",
                                               "ABSENT"]},
            "benchmark_executed": {"type": "boolean"},
            "numeric_validation_metric_count": {"type": "integer",
                                                "minimum": 0},
            # WP-21 left this alone; WP-22 built the module, so the field
            # is no longer const false - it is a measured boolean. What is
            # still const false is the fact the const was protecting:
            # whether an expert actually reviewed anything. Pinning the
            # implementation flag would have forced a later work package to
            # either edit the schema or leave a true fact unreported; pinning
            # the performance flag cannot be satisfied by writing software.
            "expert_review_implemented": {"type": "boolean"},
            "expert_review_protocol_approved": {"const": False},
            "expert_review_performed": {"const": False},
            "wp19_started": {"type": "boolean"},
            "wp21_started": {"type": "boolean"},
            "wp22_started": {"type": "boolean"},
            "may_report_validation_result": {"const": False},
            "blockers": {"type": "array", "items": {"type": "object"}},
        },
    }


def build_schemas() -> Dict[str, Dict[str, Any]]:
    """Every WP-18 schema, keyed by repository-relative path."""
    return {
        "schemas/validation-case.schema.json": _case_schema(),
        "schemas/validation-case-manifest.schema.json":
            _case_manifest_schema(),
        "schemas/validation-access-event.schema.json": _access_event_schema(),
        "schemas/validation-separation-audit.schema.json":
            _separation_audit_schema(),
        "schemas/wp18-gate-status.schema.json": _gate_status_schema(),
    }


def load_schema(path: str) -> Mapping[str, Any]:
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _validate(payload: Mapping[str, Any], path: str,
              schema: Optional[Mapping[str, Any]]) -> Tuple[str, ...]:
    return validate_against_schema(
        payload, schema if schema is not None else load_schema(path))


def validate_validation_case(payload, schema=None) -> Tuple[str, ...]:
    """Every way one public case document fails its published schema."""
    return _validate(payload, CASE_SCHEMA_PATH, schema)


def validate_case_manifest(payload, schema=None) -> Tuple[str, ...]:
    return _validate(payload, CASE_MANIFEST_SCHEMA_PATH, schema)


def validate_access_event(payload, schema=None) -> Tuple[str, ...]:
    return _validate(payload, ACCESS_EVENT_SCHEMA_PATH, schema)


def validate_separation_audit(payload, schema=None) -> Tuple[str, ...]:
    return _validate(payload, SEPARATION_AUDIT_SCHEMA_PATH, schema)


def validate_wp18_gate_status(payload, schema=None) -> Tuple[str, ...]:
    return _validate(payload, GATE_STATUS_SCHEMA_PATH, schema)
