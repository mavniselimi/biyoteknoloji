# -*- coding: utf-8 -*-
"""Published JSON Schemas for WP-21.

Six schemas, and the interesting constraints are the negative ones. A schema
that only described the happy shape would accept a report claiming a numeric
holdout pass rate with no release pinned - which is exactly the document
nobody should be able to publish.

So these schemas pin, with ``const`` where the value is a fact about this
repository rather than a variable:

- ``clinical_validation_performed`` and ``expert_review_performed`` are
  ``false``. Flipping either needs this file to change in the open.
- ``combined_overall_metric`` is ``null``. There is no field in which a pooled
  development-plus-holdout figure could be published.
- A metric that is not ``AVAILABLE`` must carry a null ``value`` and a reason
  code; an ``AVAILABLE`` rate must carry a positive integer denominator. The
  ``0%`` that means "we never looked" is unrepresentable.

Written against the supported subset of JSON Schema that
``pgx.application.snapshot_schema.validate_against_schema`` implements - no
``patternProperties``, so category maps are described rather than pattern
matched.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from pgx.application.snapshot_schema import validate_against_schema
from pgx.validation.benchmark_gate_status import GATE_STATUS_VERSION
from pgx.validation.benchmark_models import BENCHMARK_PROTOCOL_VERSION
from pgx.validation.benchmark_report import REPORT_SCHEMA_VERSION
from pgx.validation.dashboard_feed import FEED_SCHEMA_VERSION
from pgx.validation.metric_definitions import (METRIC_IDS,
                                               METRIC_REGISTRY_VERSION)

__all__ = [
    "DASHBOARD_FEED_SCHEMA_PATH",
    "FAILURE_PATH_SCHEMA_PATH",
    "GATE_STATUS_SCHEMA_PATH",
    "METRIC_DEFINITIONS_SCHEMA_PATH",
    "PLAN_SCHEMA_PATH",
    "REPORT_SCHEMA_PATH",
    "build_schemas",
    "validate_benchmark_plan",
    "validate_dashboard_feed",
    "validate_failure_paths",
    "validate_metric_definitions",
    "validate_validation_report",
    "validate_wp21_gate_status",
]

METRIC_DEFINITIONS_SCHEMA_PATH = "schemas/wp21/metric-definitions.schema.json"
FAILURE_PATH_SCHEMA_PATH = "schemas/wp21/failure-path-catalogue.schema.json"
PLAN_SCHEMA_PATH = "schemas/wp21/benchmark-plan.schema.json"
REPORT_SCHEMA_PATH = "schemas/wp21/validation-report.schema.json"
DASHBOARD_FEED_SCHEMA_PATH = "schemas/wp21/dashboard-feed.schema.json"
GATE_STATUS_SCHEMA_PATH = "schemas/wp21/wp21-gate-status.schema.json"

_BASE = "https://pgx.local/schemas/wp21/"

_DIGEST = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
_NULLABLE_DIGEST = {"anyOf": [_DIGEST, {"type": "null"}]}
_NULLABLE_INT = {"anyOf": [{"type": "integer", "minimum": 0},
                           {"type": "null"}]}
_NULLABLE_STRING = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_ROLES = ["DEVELOPMENT", "INTERNAL_HOLDOUT", "EXPERT_HOLDOUT"]
_STATUSES = ["AVAILABLE", "UNAVAILABLE", "NOT_EXECUTED", "BLOCKED",
             "NOT_APPLICABLE"]
_KINDS = ["COUNT", "RATE", "DISTRIBUTION"]


def _metric_value_schema() -> Dict[str, Any]:
    """One metric value, with the availability rules enforced by ``if/then``.

    ``AVAILABLE`` requires a value and a denominator; anything else forbids a
    value and requires a reason. Those two rules are the whole point of the
    schema and are stated as constraints rather than left to the producer.
    """
    return {
        "type": "object",
        "required": ["metric_id", "role", "status", "kind", "numerator",
                     "denominator", "value", "unavailable_reason",
                     "is_validation_evidence"],
        "additionalProperties": True,
        "properties": {
            "metric_id": {"type": "string", "enum": list(METRIC_IDS)},
            "role": {"type": "string", "enum": _ROLES},
            "status": {"type": "string", "enum": _STATUSES},
            "kind": {"type": "string", "enum": _KINDS},
            "numerator": _NULLABLE_INT,
            "denominator": _NULLABLE_INT,
            "value": _NULLABLE_STRING,
            "unavailable_reason": _NULLABLE_STRING,
            "detail": {"type": "string"},
            "is_validation_evidence": {"type": "boolean"},
            "categories": {"type": "object"},
        },
        "allOf": [
            {
                "if": {"properties": {"status": {"const": "AVAILABLE"}},
                       "required": ["status"]},
                "then": {"properties": {
                    "unavailable_reason": {"type": "null"},
                    "denominator": {"type": "integer", "minimum": 0}}},
                "else": {"properties": {
                    "value": {"type": "null"},
                    "unavailable_reason": {"type": "string",
                                           "minLength": 3}}},
            },
            {
                "if": {"properties": {"status": {"const": "NOT_EXECUTED"}},
                       "required": ["status"]},
                "then": {"properties": {
                    "numerator": {"type": "null"},
                    "denominator": {"type": "null"}}},
            },
        ],
    }


def _partition_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "required": ["section", "role", "is_validation_evidence",
                     "case_count", "observation_count", "metrics"],
        "additionalProperties": True,
        "properties": {
            "section": {"type": "string",
                        "enum": ["DEVELOPMENT_REGRESSION",
                                 "INTERNAL_HOLDOUT", "EXPERT_HOLDOUT"]},
            "role": {"type": "string", "enum": _ROLES},
            "is_validation_evidence": {"type": "boolean"},
            "evidence_note": {"type": "string"},
            "case_count": _NULLABLE_INT,
            "observation_count": _NULLABLE_INT,
            "metric_count": {"type": "integer", "minimum": 0},
            "available_metric_count": {"type": "integer", "minimum": 0},
            "status_counts": {"type": "object"},
            "metrics": {"type": "array", "items": _metric_value_schema()},
        },
        "allOf": [{
            # The structural exclusion, stated in the schema: a document that
            # marked the development section as validation evidence is
            # rejected before anyone reads it.
            "if": {"properties": {"section":
                                  {"const": "DEVELOPMENT_REGRESSION"}},
                   "required": ["section"]},
            "then": {"properties": {
                "is_validation_evidence": {"const": False},
                "role": {"const": "DEVELOPMENT"}}},
        }],
    }


def _metric_definitions_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "metric-definitions.schema.json",
        "title": "WP-21 metric definitions",
        "description": "Every metric defined before any result exists. No "
                       "definition carries a threshold; a threshold without "
                       "predeclared provenance is an implementer's opinion.",
        "type": "object",
        "required": ["schema_version", "metric_registry_version",
                     "metric_registry_digest", "metric_count",
                     "thresholds_declared", "metrics"],
        "additionalProperties": True,
        "properties": {
            "schema_version": {"const": "pgx-wp21-metric-definitions/1"},
            "metric_registry_version": {"const": METRIC_REGISTRY_VERSION},
            "metric_registry_digest": _DIGEST,
            "metric_count": {"type": "integer", "minimum": 10},
            "thresholds_declared": {"const": 0},
            "threshold_policy": {"type": "string", "minLength": 40},
            "unavailable_reasons": {"type": "object"},
            "metrics": {
                "type": "array", "minItems": 10,
                "items": {
                    "type": "object",
                    "required": ["metric_id", "title", "kind", "numerator",
                                 "denominator", "eligible_roles",
                                 "is_validation_evidence", "threshold",
                                 "unavailable_when"],
                    "additionalProperties": True,
                    "properties": {
                        "metric_id": {"type": "string",
                                      "pattern": "^PGX-VAL-[0-9]{3}$"},
                        "title": {"type": "string", "minLength": 3},
                        "plain_meaning": {"type": "string", "minLength": 10},
                        "kind": {"type": "string", "enum": _KINDS},
                        "numerator": {"type": "string", "minLength": 5},
                        "denominator": {"type": "string", "minLength": 5},
                        "eligible_roles": {
                            "type": "array", "minItems": 1,
                            "items": {"type": "string", "enum": _ROLES}},
                        "is_validation_evidence": {"type": "boolean"},
                        "requires_expert_review": {"type": "boolean"},
                        "threshold": {"type": "null"},
                        "threshold_provenance": {"type": "null"},
                        "unavailable_when": {
                            "type": "array", "minItems": 1,
                            "items": {"type": "string"}},
                        "decimal_places": {"type": "integer", "minimum": 0,
                                           "maximum": 8},
                        "categories": {"type": "array",
                                       "items": {"type": "string"}},
                    },
                },
            },
        },
    }


def _failure_path_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "failure-path-catalogue.schema.json",
        "title": "WP-21 failure-path catalogue",
        "description": "The predeclared denominator for failure-path "
                       "coverage. A run that exercised two paths reports two "
                       "out of the catalogue size, never two out of two.",
        "type": "object",
        "required": ["schema_version", "failure_path_catalogue_version",
                     "failure_path_count", "failure_paths"],
        "additionalProperties": True,
        "properties": {
            "schema_version": {"const": "pgx-wp21-failure-paths/1"},
            "failure_path_catalogue_version": {"type": "string"},
            "failure_path_count": {"type": "integer", "minimum": 10},
            "denominator_policy": {"type": "string", "minLength": 40},
            "failure_paths": {
                "type": "array", "minItems": 10,
                "items": {
                    "type": "object",
                    "required": ["path_id", "title", "meaning",
                                 "expected_refusal"],
                    "additionalProperties": False,
                    "properties": {
                        "path_id": {"type": "string",
                                    "pattern": "^FP-[0-9]{3}$"},
                        "title": {"type": "string", "minLength": 3},
                        "meaning": {"type": "string", "minLength": 10},
                        "expected_refusal": {"type": "string",
                                             "minLength": 10},
                    },
                },
            },
        },
    }


def _plan_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "benchmark-plan.schema.json",
        "title": "WP-21 benchmark plan",
        "description": "What a run will measure, pinned before it measures. "
                       "Every hash is required: a plan that could omit one "
                       "would let a result name a release it did not use.",
        "type": "object",
        "required": ["protocol_version", "plan_id", "pinned_release", "roles",
                     "case_manifest_hashes", "declared_metric_ids",
                     "metric_registry_version", "metric_registry_digest",
                     "failure_path_catalogue_version", "repeat_count"],
        "additionalProperties": True,
        "properties": {
            "protocol_version": {"const": BENCHMARK_PROTOCOL_VERSION},
            "plan_id": {"type": "string", "minLength": 3},
            "pinned_release": {
                "type": "object",
                "required": ["release_public_id", "release_manifest_hash",
                             "software_version", "software_hash",
                             "dataset_public_id", "dataset_content_hash",
                             "ruleset_public_id", "ruleset_content_hash",
                             "resolved_at"],
                "additionalProperties": True,
                "properties": {
                    "release_public_id": {"type": "string", "minLength": 3},
                    "release_manifest_hash": _DIGEST,
                    "software_version": {"type": "string", "minLength": 1},
                    "software_hash": _DIGEST,
                    "dataset_public_id": {"type": "string", "minLength": 3},
                    "dataset_content_hash": _DIGEST,
                    "ruleset_public_id": {"type": "string", "minLength": 3},
                    "ruleset_content_hash": _DIGEST,
                    "resolved_at": {"type": "string", "minLength": 20},
                    "active_pointer_generation": _NULLABLE_INT,
                },
            },
            "roles": {"type": "array", "minItems": 1, "uniqueItems": True,
                      "items": {"type": "string", "enum": _ROLES}},
            "case_manifest_hashes": {"type": "object", "minProperties": 1},
            "declared_metric_ids": {
                "type": "array", "minItems": 1, "uniqueItems": True,
                "items": {"type": "string", "enum": list(METRIC_IDS)}},
            "metric_registry_version": {"const": METRIC_REGISTRY_VERSION},
            "metric_registry_digest": _DIGEST,
            "failure_path_catalogue_version": {"type": "string"},
            "repeat_count": {"type": "integer", "minimum": 1},
            "note": {"type": "string"},
        },
    }


def _report_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "validation-report.schema.json",
        "title": "WP-21 public validation report",
        "description": "Partition-level aggregates only. No case identifier, "
                       "observation, expected answer or expert response, and "
                       "no combined development-plus-holdout figure.",
        "type": "object",
        "required": ["report_schema_version", "work_package",
                     "benchmark_executed", "active_release_available",
                     "pinned_release", "partitions",
                     "combined_overall_metric",
                     "clinical_validation_performed",
                     "expert_review_performed",
                     "restricted_case_evidence_artifact", "blockers"],
        "additionalProperties": True,
        "properties": {
            "report_schema_version": {"const": REPORT_SCHEMA_VERSION},
            "work_package": {"const": "WP-21"},
            "protocol_version": _NULLABLE_STRING,
            "metric_registry_version": {"const": METRIC_REGISTRY_VERSION},
            "metric_registry_digest": _DIGEST,
            "benchmark_executed": {"type": "boolean"},
            "active_release_available": {"type": "boolean"},
            "pinned_release": {"anyOf": [{"type": "object"},
                                         {"type": "null"}]},
            "plan_id": _NULLABLE_STRING,
            "plan_hash": _NULLABLE_DIGEST,
            "run_scientific_digest": _NULLABLE_DIGEST,
            "case_manifest_hashes": {"type": "object"},
            "repeat_count": _NULLABLE_INT,
            "declared_metric_ids": {"type": "array",
                                    "items": {"type": "string"}},
            "separation_audit": {"type": "object"},
            "partitions": {"type": "array", "minItems": 3,
                           "items": _partition_schema()},
            # Pinned null. There is no shape in which a pooled figure could be
            # published, so publishing one would need this schema to change.
            "combined_overall_metric": {"type": "null"},
            "combined_overall_note": {"type": "string", "minLength": 40},
            "numeric_validation_metric_count": {"type": "integer",
                                                "minimum": 0},
            "restricted_case_evidence_artifact": _NULLABLE_STRING,
            "clinical_validation_performed": {"const": False},
            "expert_review_performed": {"const": False},
            "not_clinical_validation": {"type": "string", "minLength": 60},
            "blocker_count": {"type": "integer", "minimum": 0},
            "blockers": {"type": "array", "items": {"type": "object"}},
        },
        "allOf": [{
            # No run, no pinned release. A report claiming execution with a
            # null release would be naming nothing as its subject.
            "if": {"properties": {"benchmark_executed": {"const": True}},
                   "required": ["benchmark_executed"]},
            "then": {"properties": {"pinned_release": {"type": "object"},
                                    "plan_hash": _DIGEST}},
        }],
    }


def _feed_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "dashboard-feed.schema.json",
        "title": "WP-21 dashboard feed",
        "description": "The public aggregate feed the validation page reads. "
                       "The web layer sees this and nothing else.",
        "type": "object",
        "required": ["feed_schema_version", "work_package",
                     "benchmark_executed", "active_release_available",
                     "sections", "combined_overall_metric",
                     "clinical_validation_performed",
                     "expert_review_performed"],
        "additionalProperties": True,
        "properties": {
            "feed_schema_version": {"const": FEED_SCHEMA_VERSION},
            "work_package": {"const": "WP-21"},
            "metric_registry_version": {"const": METRIC_REGISTRY_VERSION},
            "metric_registry_digest": _NULLABLE_DIGEST,
            "benchmark_executed": {"type": "boolean"},
            "active_release_available": {"type": "boolean"},
            "release_public_id": _NULLABLE_STRING,
            "release_manifest_hash": _NULLABLE_DIGEST,
            "dataset_public_id": _NULLABLE_STRING,
            "ruleset_public_id": _NULLABLE_STRING,
            "software_version": _NULLABLE_STRING,
            "plan_hash": _NULLABLE_DIGEST,
            "run_scientific_digest": _NULLABLE_DIGEST,
            "report_digest": _DIGEST,
            "combined_overall_metric": {"type": "null"},
            "numeric_validation_metric_count": {"type": "integer",
                                                "minimum": 0},
            "clinical_validation_performed": {"const": False},
            "expert_review_performed": {"const": False},
            "blocker_count": {"type": "integer", "minimum": 0},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "sections": {
                "type": "array", "minItems": 3,
                "items": {
                    "type": "object",
                    "required": ["section", "role", "is_validation_evidence",
                                 "is_development_regression", "metrics"],
                    "additionalProperties": True,
                    "properties": {
                        "section": {"type": "string"},
                        "role": {"type": "string", "enum": _ROLES},
                        "is_validation_evidence": {"type": "boolean"},
                        "is_development_regression": {"type": "boolean"},
                        "case_count": _NULLABLE_INT,
                        "observation_count": _NULLABLE_INT,
                        "metric_count": {"type": "integer", "minimum": 0},
                        "available_metric_count": {"type": "integer",
                                                   "minimum": 0},
                        "metrics": {"type": "array",
                                    "items": _metric_value_schema()},
                    },
                    "allOf": [{
                        "if": {"properties": {
                            "is_development_regression": {"const": True}},
                            "required": ["is_development_regression"]},
                        "then": {"properties": {
                            "is_validation_evidence": {"const": False}}},
                    }],
                },
            },
        },
    }


def _gate_status_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "wp21-gate-status.schema.json",
        "title": "WP-21 gate status",
        "description": "Two separate answers: the metric machinery is "
                       "implemented, and no release has been validated.",
        "type": "object",
        "required": ["gate_status_schema_version", "work_package",
                     "implementation_status", "benchmark_gate_status",
                     "release_may_proceed", "metric_framework_implemented",
                     "benchmark_executed_against_active_release",
                     "active_release_available", "development_case_count",
                     "internal_holdout_case_count",
                     "expert_holdout_case_count",
                     "validation_evidence_case_count",
                     "numeric_validation_metric_count", "threshold_count",
                     "release_validation_result_available",
                     "clinical_validation_performed",
                     "expert_review_performed", "blockers"],
        "additionalProperties": True,
        "properties": {
            "gate_status_schema_version": {"const": GATE_STATUS_VERSION},
            "work_package": {"const": "WP-21"},
            "implementation_status": {"type": "string",
                                      "enum": ["IMPLEMENTED", "PARTIAL",
                                               "NOT_STARTED"]},
            "benchmark_gate_status": {"type": "string",
                                      "enum": ["PASS", "BLOCKED", "FAILED"]},
            "release_may_proceed": {"type": "boolean"},
            "metric_framework_implemented": {"type": "boolean"},
            "metric_definition_count": {"type": "integer", "minimum": 10},
            "validation_evidence_metric_count": {"type": "integer",
                                                 "minimum": 1},
            "computed_metric_value_count": {"type": "integer", "minimum": 0},
            "numeric_validation_metric_count": {"type": "integer",
                                                "minimum": 0},
            "benchmark_executed_against_active_release": {"type": "boolean"},
            "active_release_available": {"type": "boolean"},
            "metric_registry_digest": _DIGEST,
            "failure_path_count": {"type": "integer", "minimum": 10},
            # Pinned. WP-21 invents no threshold, and a document saying
            # otherwise fails validation rather than being believed.
            "threshold_count": {"const": 0},
            "development_case_count": {"type": "integer", "minimum": 0},
            "internal_holdout_case_count": {"type": "integer", "minimum": 0},
            "expert_holdout_case_count": {"type": "integer", "minimum": 0},
            "validation_evidence_case_count": {"type": "integer",
                                               "minimum": 0},
            "reference_judgment_count": {"type": "integer", "minimum": 0},
            "restricted_storage_configured": {"type": "boolean"},
            "separation_audit_clean": {"type": "boolean"},
            "release_validation_result_available": {"type": "boolean"},
            # WP-21 cannot produce either of these, whatever it computes.
            "clinical_validation_performed": {"const": False},
            "expert_review_performed": {"const": False},
            "claim_boundary_approved": {"type": "boolean"},
            "wp21_markers_found": {"type": "array",
                                   "items": {"type": "string"}},
            "wp22_started": {"type": "boolean"},
            "blocker_count": {"type": "integer", "minimum": 0},
            "blockers": {"type": "array", "items": {"type": "object"}},
        },
        "allOf": [{
            # PASS demands every precondition at once. A gate that could pass
            # with no release or no holdout case would be the gate not working.
            "if": {"properties": {"benchmark_gate_status": {"const": "PASS"}},
                   "required": ["benchmark_gate_status"]},
            "then": {"properties": {
                "active_release_available": {"const": True},
                "benchmark_executed_against_active_release": {"const": True},
                "validation_evidence_case_count": {"type": "integer",
                                                   "minimum": 1},
                "numeric_validation_metric_count": {"type": "integer",
                                                    "minimum": 1}}},
        }],
    }


def build_schemas() -> Dict[str, Dict[str, Any]]:
    """Every WP-21 schema, by committed path."""
    return {
        METRIC_DEFINITIONS_SCHEMA_PATH: _metric_definitions_schema(),
        FAILURE_PATH_SCHEMA_PATH: _failure_path_schema(),
        PLAN_SCHEMA_PATH: _plan_schema(),
        REPORT_SCHEMA_PATH: _report_schema(),
        DASHBOARD_FEED_SCHEMA_PATH: _feed_schema(),
        GATE_STATUS_SCHEMA_PATH: _gate_status_schema(),
    }


def _validate(document: Mapping[str, Any],
              schema: Mapping[str, Any]) -> List[str]:
    return list(validate_against_schema(document, schema))


def validate_metric_definitions(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _metric_definitions_schema())


def validate_failure_paths(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _failure_path_schema())


def validate_benchmark_plan(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _plan_schema())


def validate_validation_report(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _report_schema())


def validate_dashboard_feed(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _feed_schema())


def validate_wp21_gate_status(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _gate_status_schema())
