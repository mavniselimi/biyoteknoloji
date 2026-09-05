# -*- coding: utf-8 -*-
"""Published schemas for the WP-20 safety documents.

Five documents, each a place a later reader - a CI job, an auditor, a WP-24
pipeline - would otherwise have to trust a shape nobody wrote down.

``safety-invariant-registry``
    The twelve. ``invariant_id`` is a ``pattern`` restricted to 001-012, so a
    thirteenth cannot appear without changing a published schema in the open.

``safety-negative-controls``
    Every unsafe fixture and the code its evaluator must return.

``safety-execution-result``
    One run. ``execution_state`` is an ``enum`` of exactly the six words, and
    ``complete`` is required - a document that omitted it could not be told
    from a finished run.

``safety-report``
    Controls, tests, and the false-reassurance corpus. The disclaimer is a
    ``required`` field with ``minLength``, so a report cannot be produced
    without it.

``wp20-gate-status``
    Every component separately. ``clinical_validation_performed`` and
    ``expert_review_performed`` are pinned ``false`` by ``const``, so flipping
    either needs a schema change somebody has to review.

The validator is WP-06's supported subset. Every keyword used here is one it
actually checks: a published constraint nothing enforces is a false assurance.
"""

from __future__ import annotations

import io
import json
import os
from typing import Any, Dict, Mapping, Optional, Tuple

from pgx.application.snapshot_schema import validate_against_schema
from pgx.safety.controls import CONTROL_CATALOGUE_VERSION
from pgx.safety.freshness import EVIDENCE_SCHEMA_VERSION
from pgx.safety.gate_status import GATE_STATUS_SCHEMA_VERSION
from pgx.safety.report import REPORT_SCHEMA_VERSION
from pgx.safety.vocabulary import (
    REGISTRY_VERSION,
    ComplianceState,
    ControlKind,
    EnforcementSurface,
    ExecutionState,
    Severity,
)

__all__ = [
    "WP20_SCHEMA_PATHS",
    "REGISTRY_SCHEMA_PATH",
    "CONTROLS_SCHEMA_PATH",
    "EXECUTION_SCHEMA_PATH",
    "REPORT_SCHEMA_PATH",
    "GATE_STATUS_SCHEMA_PATH",
    "build_schemas",
    "load_schema",
    "validate_invariant_registry",
    "validate_negative_controls",
    "validate_safety_execution",
    "validate_safety_report",
    "validate_wp20_gate_status",
]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_REPO_ROOT)

REGISTRY_SCHEMA_PATH = "schemas/wp20/safety-invariant-registry.schema.json"
CONTROLS_SCHEMA_PATH = "schemas/wp20/safety-negative-controls.schema.json"
EXECUTION_SCHEMA_PATH = "schemas/wp20/safety-execution-result.schema.json"
REPORT_SCHEMA_PATH = "schemas/wp20/safety-report.schema.json"
GATE_STATUS_SCHEMA_PATH = "schemas/wp20/wp20-gate-status.schema.json"

WP20_SCHEMA_PATHS: Tuple[str, ...] = (
    CONTROLS_SCHEMA_PATH, EXECUTION_SCHEMA_PATH, GATE_STATUS_SCHEMA_PATH,
    REGISTRY_SCHEMA_PATH, REPORT_SCHEMA_PATH,
)

_BASE = "https://pgx.local/schemas/wp20/"
#: Exactly 001 through 012. A thirteenth invariant is a change to a reviewed
#: document, and this pattern makes that change visible in the schema too.
_INVARIANT_PATTERN = "^SAFETY-INV-0(0[1-9]|1[0-2])$"
_CONTROL_PATTERN = "^(NC|SC)-.+$"
_STRINGS = {"type": "array", "items": {"type": "string"}}
_INT = {"type": "integer", "minimum": 0}
_MAYBE_INT = {"type": ["integer", "null"], "minimum": 0}
_MAYBE_BOOL = {"type": ["boolean", "null"]}


def _values(enum_class) -> list:
    return [member.value for member in enum_class]


def _blocker_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "required": ["code", "owner", "detail"],
        "properties": {
            "code": {"type": "string", "pattern": "^SAFETY_[A-Z0-9_]+$"},
            "detail": {"type": "string", "minLength": 1},
            # Never "code": every blocker is closed by a person, a machine or a
            # later work package.
            "owner": {"type": "string", "minLength": 1},
        },
    }


def _registry_schema() -> Dict[str, Any]:
    invariant = {
        "type": "object",
        "additionalProperties": False,
        "required": ["invariant_id", "title", "requirement_reference",
                     "severity", "required_surfaces", "current_surfaces",
                     "owning_work_packages", "test_selectors",
                     "negative_controls", "legacy_bugs", "refusal_code",
                     "implementation_state", "blockers", "absence_markers",
                     "note"],
        "properties": {
            "absence_markers": _STRINGS,
            "blockers": {"type": "array", "items": _blocker_schema()},
            "current_surfaces": {"type": "array",
                                 "items": {"enum": _values(EnforcementSurface)}},
            "implementation_state": {"enum": _values(ComplianceState)},
            "invariant_id": {"type": "string", "pattern": _INVARIANT_PATTERN},
            "legacy_bugs": {"type": "array",
                            "items": {"type": "string",
                                      "pattern": "^LEGACY-BUG-[0-9]{3}$"}},
            # At least one, always. A detector nobody has shown to reject
            # anything is a detector nobody has shown to work.
            "negative_controls": {"type": "array", "minItems": 1,
                                  "items": {"type": "string",
                                            "pattern": _CONTROL_PATTERN}},
            "note": {"type": "string"},
            "owning_work_packages": {"type": "array", "minItems": 1,
                                     "items": {"type": "string"}},
            "refusal_code": {"type": "string",
                             "pattern": "^SAFETY_[A-Z0-9_]+$"},
            "required_surfaces": {"type": "array", "minItems": 1,
                                  "items": {"enum":
                                            _values(EnforcementSurface)}},
            "requirement_reference": {"type": "string", "minLength": 1},
            "severity": {"enum": _values(Severity)},
            "test_selectors": {"type": "array", "minItems": 1,
                               "items": {"type": "string"}},
            "title": {"type": "string", "minLength": 1},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "safety-invariant-registry.schema.json",
        "title": "WP-20 safety invariant registry",
        "description": "The twelve invariants of "
                       "docs/risk-management/safety-contract.md section 2, in "
                       "machine-readable form. Exactly twelve: the identifier "
                       "pattern admits 001 through 012 and nothing else, so a "
                       "thirteenth invariant requires this published schema to "
                       "change where somebody will see it.",
        "type": "object",
        "additionalProperties": False,
        "required": ["registry_version", "invariant_count", "invariant_ids",
                     "invariants", "negative_controls", "control_count",
                     "resolved_modules", "note"],
        "properties": {
            "control_catalogue_version": {"const": CONTROL_CATALOGUE_VERSION},
            "control_count": {"type": "integer", "minimum": 12},
            "invariant_count": {"const": 12},
            "invariant_ids": {"type": "array", "minItems": 12, "maxItems": 12,
                              "uniqueItems": True,
                              "items": {"type": "string",
                                        "pattern": _INVARIANT_PATTERN}},
            "invariants": {"type": "array", "minItems": 12, "maxItems": 12,
                           "items": invariant},
            "negative_controls": {"type": "array", "minItems": 12},
            "note": {"type": "string", "minLength": 1},
            "registry_version": {"const": REGISTRY_VERSION},
            "resolved_modules": {"type": "object",
                                 "propertyNames": {"pattern":
                                                   _INVARIANT_PATTERN},
                                 "additionalProperties": _STRINGS},
        },
    }


def _controls_schema() -> Dict[str, Any]:
    control = {
        "type": "object",
        "additionalProperties": False,
        "required": ["control_id", "invariant_id", "description",
                     "expected_refusal_code", "fixture", "kind", "legacy_bug"],
        "properties": {
            "control_id": {"type": "string", "pattern": _CONTROL_PATTERN},
            "description": {"type": "string", "minLength": 1},
            "expected_refusal_code": {"type": "string",
                                      "pattern": "^SAFETY_[A-Z0-9_]+$"},
            "fixture": {"type": "string", "pattern": "^tests\\.fixtures\\."},
            "invariant_id": {"type": "string", "pattern": _INVARIANT_PATTERN},
            "kind": {"enum": _values(ControlKind)},
            "legacy_bug": {"type": "string"},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "safety-negative-controls.schema.json",
        "title": "WP-20 negative control catalogue",
        "description": "Every deliberately unsafe case, the invariant it "
                       "belongs to, and the stable code its evaluator must "
                       "return. The fixture pattern requires tests.fixtures.*: "
                       "a control realised in production code would be a "
                       "mutation of the shipped system rather than a double.",
        "type": "object",
        "additionalProperties": False,
        "required": ["control_catalogue_version", "control_count", "controls",
                     "note"],
        "properties": {
            "control_catalogue_version": {"const": CONTROL_CATALOGUE_VERSION},
            "control_count": {"type": "integer", "minimum": 12},
            "controls": {"type": "array", "minItems": 12, "items": control},
            "note": {"type": "string", "minLength": 1},
        },
    }


def _control_outcome_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["control_id", "kind", "detected", "satisfied",
                     "expected_refusal_code", "observed_refusal_code",
                     "detail"],
        "properties": {
            "control_id": {"type": "string", "pattern": _CONTROL_PATTERN},
            "detail": {"type": "string"},
            # ``null`` means the control did not run, which is never satisfied.
            "detected": {"type": ["boolean", "null"]},
            "expected_refusal_code": {"type": "string"},
            "kind": {"enum": _values(ControlKind)},
            "observed_refusal_code": {"type": "string"},
            "satisfied": {"type": "boolean"},
        },
    }


def _invariant_execution_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["invariant_id", "registered", "execution_state",
                     "compliance_state", "severity", "tests", "controls",
                     "control_count", "negative_control_count",
                     "detected_negative_controls", "all_controls_satisfied",
                     "blockers", "refusal_code", "reason"],
        "properties": {
            "all_controls_satisfied": {"type": "boolean"},
            "blockers": {"type": "array", "items": _blocker_schema()},
            "compliance_state": {"enum": _values(ComplianceState)},
            "control_count": _INT,
            "controls": {"type": "array", "items": _control_outcome_schema()},
            "detected_negative_controls": _INT,
            "execution_state": {"enum": _values(ExecutionState)},
            "invariant_id": {"type": "string", "pattern": _INVARIANT_PATTERN},
            "negative_control_count": _INT,
            "reason": {"type": "string"},
            "refusal_code": {"type": "string"},
            "registered": {"type": "boolean"},
            "severity": {"enum": _values(Severity)},
            "tests": {
                "type": "object",
                "additionalProperties": False,
                "required": ["executed", "passed", "failed", "errored",
                             "skipped", "unexplained_skips"],
                "properties": {"errored": _INT, "executed": _INT,
                               "failed": _INT, "passed": _INT,
                               "skipped": _INT, "unexplained_skips": _INT},
            },
        },
    }


def _execution_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "safety-execution-result.schema.json",
        "title": "WP-20 safety execution result",
        "description": "One run of the safety gate. `complete` is required: a "
                       "document that omitted it could not be told from a "
                       "finished run, and an interrupted build must never "
                       "leave a passing artifact behind.",
        "type": "object",
        "additionalProperties": True,
        "required": ["complete", "invariants", "inputs", "environment"],
        "properties": {
            "complete": {"type": "boolean"},
            "environment": {"type": "object"},
            "inputs": {"type": "object",
                       "additionalProperties": {"type": "string"}},
            "invalidated": {"type": "boolean"},
            "invalidation_reason": {"type": "string"},
            "invariants": {"type": "array",
                           "items": _invariant_execution_schema()},
            "note": {"type": "string"},
        },
    }


def _report_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "safety-report.schema.json",
        "title": "WP-20 safety report",
        "description": "Controls, tests and the false-reassurance corpus. The "
                       "detector-evidence disclaimer is required with a "
                       "minimum length, so a report cannot be produced without "
                       "the sentence saying that catching a mutant is software "
                       "evidence and not clinical validation.",
        "type": "object",
        "additionalProperties": False,
        "required": ["report_schema_version", "work_package", "invariants",
                     "summary", "false_reassurance",
                     "prohibited_claim_surfaces",
                     "detector_evidence_disclaimer"],
        "properties": {
            "detector_evidence_disclaimer": {"type": "string",
                                             "minLength": 80},
            "evidence_schema_version": {"const": EVIDENCE_SCHEMA_VERSION},
            "false_reassurance": {
                "type": "object",
                "additionalProperties": False,
                "required": ["corpus_size", "violation_count", "target",
                             "meets_target", "note"],
                "properties": {
                    "corpus_size": {"type": "integer", "minimum": 1},
                    "meets_target": {"type": "boolean"},
                    "note": {"type": "string", "minLength": 40},
                    "target": {"const": 0},
                    "violation_count": _INT,
                },
            },
            "invariants": {"type": "array", "minItems": 12, "maxItems": 12,
                           "items": _invariant_execution_schema()},
            "prohibited_claim_surfaces": {"type": "object"},
            "report_schema_version": {"const": REPORT_SCHEMA_VERSION},
            "summary": {"type": "object"},
            "work_package": {"const": "WP-20"},
        },
    }


def _gate_status_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "wp20-gate-status.schema.json",
        "title": "WP-20 safety gate status",
        "description": "Twelve invariants reported independently, plus the "
                       "environment and governance facts a release depends on. "
                       "`release_may_proceed` sits beside those fields rather "
                       "than instead of them: the gate can be in a state where "
                       "every executable check passes and a release still must "
                       "not proceed.",
        "type": "object",
        "additionalProperties": True,
        "required": ["gate_status_schema_version", "work_package",
                     "registered_invariant_count", "executed_invariant_count",
                     "negative_control_count",
                     "detected_negative_control_count",
                     "false_reassurance_corpus_size",
                     "false_reassurance_violation_count",
                     "prohibited_claim_surface_count",
                     "stale_or_missing_selector_count",
                     "unexplained_skip_count", "ci_job_configured",
                     "ci_job_executed", "claim_boundary_approved",
                     "postgresql_available", "active_release_available",
                     "safety_gate_status", "release_may_proceed",
                     "invariant_status", "blockers", "blocker_count",
                     "clinical_validation_performed",
                     "expert_review_performed",
                     "validation_metrics_implemented",
                     "not_clinical_validation", "evidence_state"],
        "properties": {
            "active_release_available": _MAYBE_BOOL,
            "blocker_count": _INT,
            "blockers": {"type": "array", "items": _blocker_schema()},
            "ci_job_configured": {"type": "boolean"},
            # Never inferred from a workflow file existing. Only an observed
            # CI provider run may set this.
            "ci_job_executed": {"type": "boolean"},
            "claim_boundary_approved": {"type": "boolean"},
            "claim_scanner_known_gap_count": _MAYBE_INT,
            "clinical_validation_performed": {"const": False},
            "detected_negative_control_count": _INT,
            "evidence_state": {"enum": ["CURRENT", "STALE", "ABSENT",
                                        "INVALIDATED"]},
            "executed_invariant_count": _INT,
            "expert_review_performed": {"const": False},
            "false_reassurance_corpus_size": _MAYBE_INT,
            "false_reassurance_violation_count": _MAYBE_INT,
            "gate_status_schema_version": {"const": GATE_STATUS_SCHEMA_VERSION},
            "holdout_case_count": _MAYBE_INT,
            "invariant_status": {"type": "object",
                                 "propertyNames": {"pattern":
                                                   _INVARIANT_PATTERN},
                                 "additionalProperties": {"type": "object"}},
            "negative_control_count": _INT,
            "not_clinical_validation": {"type": "string", "minLength": 80},
            "postgresql_available": _MAYBE_BOOL,
            "prohibited_claim_surface_count": _MAYBE_INT,
            "registered_invariant_count": {"const": 12},
            "release_may_proceed": {"type": "boolean"},
            "safety_gate_status": {"enum": _values(ExecutionState)},
            "stale_or_missing_selector_count": _INT,
            "unexplained_skip_count": _INT,
            # Unpinned at WP-21, in the open, together with the field.
            # ``clinical_validation_performed`` and
            # ``expert_review_performed`` stay pinned ``False`` above: those
            # are people's acts and no work package can flip them.
            "validation_metrics_implemented": {"type": "boolean"},
            "work_package": {"const": "WP-20"},
        },
    }


def build_schemas() -> Dict[str, Dict[str, Any]]:
    return {
        CONTROLS_SCHEMA_PATH: _controls_schema(),
        EXECUTION_SCHEMA_PATH: _execution_schema(),
        GATE_STATUS_SCHEMA_PATH: _gate_status_schema(),
        REGISTRY_SCHEMA_PATH: _registry_schema(),
        REPORT_SCHEMA_PATH: _report_schema(),
    }


def load_schema(path: str, root: str = _REPO_ROOT) -> Mapping[str, Any]:
    with io.open(os.path.join(root, *path.split("/")), "r",
                 encoding="utf-8") as handle:
        return json.load(handle)


def _validate(payload, path, schema=None) -> Tuple[str, ...]:
    return validate_against_schema(
        payload, schema if schema is not None else build_schemas()[path])


def validate_invariant_registry(payload, schema=None) -> Tuple[str, ...]:
    return _validate(payload, REGISTRY_SCHEMA_PATH, schema)


def validate_negative_controls(payload, schema=None) -> Tuple[str, ...]:
    return _validate(payload, CONTROLS_SCHEMA_PATH, schema)


def validate_safety_execution(payload, schema=None) -> Tuple[str, ...]:
    return _validate(payload, EXECUTION_SCHEMA_PATH, schema)


def validate_safety_report(payload, schema=None) -> Tuple[str, ...]:
    return _validate(payload, REPORT_SCHEMA_PATH, schema)


def validate_wp20_gate_status(payload, schema=None) -> Tuple[str, ...]:
    return _validate(payload, GATE_STATUS_SCHEMA_PATH, schema)
