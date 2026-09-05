# -*- coding: utf-8 -*-
"""Published schemas for the WP-19 verification documents, and validators.

Six documents get schemas, and each one is a place where a later reader - a CI
job, an auditor, a WP-24 pipeline - would otherwise have to trust a shape
nobody wrote down.

``verification-plan``
    The test inventory. Every suite carries its category, owner, requirements,
    skip policy and a digest over the test identifiers it contains.

``requirement-matrix``
    What is claimed to verify what, and everything that is not covered. The
    gap fields are ``required``, so a matrix document that simply omitted them
    fails validation rather than reading as "nothing was missing".

``verification-result``
    One profile's outcome. ``outcome`` is an ``enum`` of exactly the five
    words, so no producer can invent a sixth that a reader would have to guess
    at, and the count fields are separate integers rather than one total.

``coverage-summary``
    Every percentage is ``["number", "null"]``. Null is what a measurement
    nobody took looks like; zero is what a measurement that found nothing
    executed looks like, and the schema keeps them different.

``reproducibility-report`` and ``flaky-report``
    What was rebuilt, what was repeated, and what disagreed.

``wp19-gate-status``
    Every component separately, and ``release_may_proceed`` as one more field
    beside them rather than instead of them.

The validator is WP-06's supported subset. Every keyword used here is one it
actually checks: a published constraint that nothing enforces is a false
assurance, and this module would rather say less than pretend more.
"""

from __future__ import annotations

import io
import json
import os
from typing import Any, Dict, Mapping, Optional, Tuple

from pgx.application.snapshot_schema import validate_against_schema
from pgx.verification.coverage_report import COVERAGE_SCHEMA_VERSION
from pgx.verification.flaky import FLAKY_SCHEMA_VERSION
from pgx.verification.gate_status import GATE_STATUS_SCHEMA_VERSION
from pgx.verification.matrix import MATRIX_SCHEMA_VERSION
from pgx.verification.model import (
    Category,
    Criticality,
    Outcome,
    PLAN_SCHEMA_VERSION,
    RESULT_SCHEMA_VERSION,
    SkipClassification,
    SkipPolicy,
)
from pgx.verification.reproducibility import REPRODUCIBILITY_SCHEMA_VERSION

__all__ = [
    "WP19_SCHEMA_PATHS",
    "PLAN_SCHEMA_PATH",
    "MATRIX_SCHEMA_PATH",
    "RESULT_SCHEMA_PATH",
    "COVERAGE_SCHEMA_PATH",
    "REPRODUCIBILITY_SCHEMA_PATH",
    "FLAKY_SCHEMA_PATH",
    "GATE_STATUS_SCHEMA_PATH",
    "build_schemas",
    "load_schema",
    "validate_verification_plan",
    "validate_requirement_matrix",
    "validate_verification_result",
    "validate_coverage_summary",
    "validate_reproducibility_report",
    "validate_flaky_report",
    "validate_wp19_gate_status",
]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_REPO_ROOT)
_SCHEMAS = os.path.join(_REPO_ROOT, "schemas")

PLAN_SCHEMA_PATH = "schemas/wp19/verification-plan.schema.json"
MATRIX_SCHEMA_PATH = "schemas/wp19/requirement-matrix.schema.json"
RESULT_SCHEMA_PATH = "schemas/wp19/verification-result.schema.json"
COVERAGE_SCHEMA_PATH = "schemas/wp19/coverage-summary.schema.json"
REPRODUCIBILITY_SCHEMA_PATH = (
    "schemas/wp19/reproducibility-report.schema.json")
FLAKY_SCHEMA_PATH = "schemas/wp19/flaky-report.schema.json"
GATE_STATUS_SCHEMA_PATH = "schemas/wp19/wp19-gate-status.schema.json"

WP19_SCHEMA_PATHS: Tuple[str, ...] = (
    COVERAGE_SCHEMA_PATH,
    FLAKY_SCHEMA_PATH,
    GATE_STATUS_SCHEMA_PATH,
    MATRIX_SCHEMA_PATH,
    PLAN_SCHEMA_PATH,
    REPRODUCIBILITY_SCHEMA_PATH,
    RESULT_SCHEMA_PATH,
)

_BASE = "https://pgx.local/schemas/wp19/"
_SHA256 = "^[0-9a-f]{64}$"
_STRINGS = {"type": "array", "items": {"type": "string"}}
_INT = {"type": "integer", "minimum": 0}
#: A measurement that may not have been taken. ``null`` and ``0`` are different
#: answers and this is how the difference survives serialisation.
_MAYBE_INT = {"type": ["integer", "null"], "minimum": 0}
_MAYBE_NUMBER = {"type": ["number", "null"], "minimum": 0, "maximum": 100}


def _values(enum_class) -> list:
    return [member.value for member in enum_class]


def _suite_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["suite_id", "module", "category", "work_package",
                     "criticality", "requirements", "safety_invariants",
                     "command", "dependencies", "offline",
                     "synthetic_fixtures", "skip_policy",
                     "permitted_skip_reasons", "evidence", "test_count",
                     "test_id_sha256", "assigned_by"],
        "properties": {
            "assigned_by": {"type": "string", "minLength": 1},
            "category": {"enum": _values(Category)},
            "command": {"type": "string", "minLength": 1},
            "criticality": {"enum": _values(Criticality)},
            "dependencies": _STRINGS,
            "evidence": _STRINGS,
            "module": {"type": "string", "minLength": 1},
            "offline": {"type": "boolean"},
            "permitted_skip_reasons": _STRINGS,
            "requirements": _STRINGS,
            "safety_invariants": _STRINGS,
            "skip_policy": {"enum": _values(SkipPolicy)},
            "suite_id": {"type": "string", "minLength": 1},
            "synthetic_fixtures": {"type": "boolean"},
            "test_count": {"type": "integer", "minimum": 1},
            "test_id_sha256": {"type": "string", "pattern": _SHA256},
            "work_package": {"type": "string", "minLength": 1},
        },
    }


def _plan_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "verification-plan.schema.json",
        "title": "WP-19 verification plan (test inventory)",
        "description": "Every discovered test suite, with the category, "
                       "owner, requirements and skip policy assigned to it. "
                       "Built from unittest's own loader, so this document "
                       "and the suite that runs are the same enumeration.",
        "type": "object",
        "additionalProperties": False,
        "required": ["plan_schema_version", "start_directory", "pattern",
                     "discovered_test_count", "inventoried_test_count",
                     "suite_count", "suites", "unmapped_modules",
                     "load_failures", "stdout_note"],
        "properties": {
            "category_rule_count": {"type": "integer", "minimum": 1},
            "discovered_test_count": _INT,
            "inventoried_test_count": _INT,
            "known_stdout_markers": _STRINGS,
            "load_failures": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["module", "detail"],
                    "properties": {"detail": {"type": "string"},
                                   "module": {"type": "string"}},
                },
            },
            "note": {"type": "string"},
            "pattern": {"type": "string", "minLength": 1},
            "plan_schema_version": {"const": PLAN_SCHEMA_VERSION},
            "requirement_registry_version": {"type": "string"},
            "start_directory": {"type": "string", "minLength": 1},
            "stdout_note": {"type": "string", "minLength": 1},
            "suite_count": _INT,
            "suites": {"type": "array", "items": _suite_schema()},
            # Present and empty is the healthy state. Required, so a document
            # that dropped the key cannot read as "nothing was unmapped".
            "unmapped_modules": _STRINGS,
        },
    }


def _matrix_schema() -> Dict[str, Any]:
    requirement = {
        "type": "object",
        "additionalProperties": False,
        "required": ["requirement_id", "title", "source", "work_packages",
                     "selectors", "criticality", "safety_invariants",
                     "is_covered", "test_count", "modules", "module_count",
                     "categories", "test_id_sha256", "note"],
        "properties": {
            "categories": {"type": "array",
                           "items": {"enum": _values(Category)}},
            "criticality": {"enum": _values(Criticality)},
            "is_covered": {"type": "boolean"},
            "module_count": _INT,
            "modules": _STRINGS,
            "note": {"type": "string"},
            "requirement_id": {"type": "string",
                               "pattern": "^VER-REQ-[0-9]{3}$"},
            "safety_invariants": _STRINGS,
            "selectors": _STRINGS,
            "source": {"type": "string", "minLength": 1},
            "test_count": _INT,
            "test_id_sha256": {"type": "string", "pattern": _SHA256},
            "title": {"type": "string", "minLength": 1},
            "work_packages": _STRINGS,
        },
    }
    category = {
        "type": "object",
        "additionalProperties": False,
        "required": ["category", "test_count", "module_count", "modules",
                     "static_outcome", "test_id_sha256"],
        "properties": {
            "category": {"enum": _values(Category)},
            "module_count": _INT,
            "modules": _STRINGS,
            # Never PASS. Before anything runs, the strongest honest word for
            # a category that has tests is BLOCKED.
            "static_outcome": {"enum": [Outcome.BLOCKED.value,
                                        Outcome.MISSING.value]},
            "test_count": _INT,
            "test_id_sha256": {"type": "string", "pattern": _SHA256},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "requirement-matrix.schema.json",
        "title": "WP-19 requirement and category matrix",
        "description": "Which tests are claimed to verify which requirement, "
                       "and everything that is not covered. The gap fields "
                       "are required so that a document omitting them cannot "
                       "read as a document with no gaps.",
        "type": "object",
        "additionalProperties": False,
        "required": ["matrix_schema_version", "requirements", "categories",
                     "uncovered_requirements", "unmapped_critical_modules",
                     "unmapped_supporting_modules", "empty_categories",
                     "unmapped_safety_invariants", "stale_safety_selectors",
                     "is_complete", "safety_invariant_map",
                     "safety_map_disclaimer"],
        "properties": {
            "categories": {"type": "array", "items": category},
            "empty_categories": {"type": "array",
                                 "items": {"enum": _values(Category)}},
            "is_complete": {"type": "boolean"},
            "matrix_schema_version": {"const": MATRIX_SCHEMA_VERSION},
            "requirement_registry_version": {"type": "string"},
            "requirements": {"type": "array", "items": requirement},
            "safety_invariant_map": {
                "type": "object",
                "propertyNames": {"pattern": "^SAFETY-INV-[0-9]{3}$"},
                "additionalProperties": _STRINGS,
            },
            "safety_map_disclaimer": {"type": "string", "minLength": 1},
            "stale_safety_selectors": _STRINGS,
            "uncovered_requirements": _STRINGS,
            "unmapped_critical_modules": _STRINGS,
            "unmapped_safety_invariants": _STRINGS,
            "unmapped_supporting_modules": _STRINGS,
        },
    }


def _summary_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["discovered", "executed", "passed", "failed", "errored",
                     "skipped", "unexplained_skips", "not_executed"],
        "properties": {
            "discovered": _INT, "errored": _INT, "executed": _INT,
            "failed": _INT, "not_executed": _INT, "passed": _INT,
            "skipped": _INT, "unexplained_skips": _INT,
        },
    }


def _category_result_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["outcome", "executed", "passed", "failed", "errored",
                     "skipped"],
        "properties": {
            "errored": _INT, "executed": _INT, "failed": _INT,
            "inventoried": _INT,
            "outcome": {"enum": _values(Outcome)},
            "passed": _INT, "reason": {"type": "string"}, "skipped": _INT,
        },
    }


def _result_schema() -> Dict[str, Any]:
    outcome = {
        "type": "object",
        "additionalProperties": False,
        "required": ["test_id", "outcome", "reason", "skip_classification"],
        "properties": {
            "outcome": {"enum": _values(Outcome)},
            "reason": {"type": "string"},
            "skip_classification": {
                "enum": _values(SkipClassification) + [None]},
            "test_id": {"type": "string", "minLength": 1},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "verification-result.schema.json",
        "title": "WP-19 verification result",
        "description": "One profile's outcome. The five outcome words are an "
                       "enum, so no producer can invent a sixth; the counts "
                       "are separate integers, so none can be derived from "
                       "another; and `discovered` is not `executed`, because "
                       "a class-level skip suppresses tests the runner never "
                       "reports.",
        "type": "object",
        "additionalProperties": False,
        "required": ["profile", "outcome", "summary", "issue_codes",
                     "stdout_note", "blocked_reason", "categories",
                     "blocked_categories"],
        "properties": {
            "blocked_categories": {"type": "array",
                                   "items": {"enum": _values(Category)}},
            "blocked_reason": {"type": "string"},
            "categories": {
                "type": "object",
                "propertyNames": {"enum": _values(Category)},
                "additionalProperties": _category_result_schema(),
            },
            "issue_codes": {"type": "array",
                            "items": {"type": "string",
                                      "pattern": "^VERIFY_[A-Z0-9_]+$"}},
            "outcome": {"enum": _values(Outcome)},
            "outcomes": {"type": "array", "items": outcome},
            "profile": {"type": "string", "minLength": 1},
            "result_schema_version": {"const": RESULT_SCHEMA_VERSION},
            "stdout_note": {"type": "string", "minLength": 1},
            "summary": _summary_schema(),
        },
    }


def _coverage_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "coverage-summary.schema.json",
        "title": "WP-19 coverage summary",
        "description": "Line and branch coverage, or an explicit statement "
                       "that none was measured. Every percentage may be null, "
                       "because null is what an unmeasured number looks like "
                       "and 0.0 is what a measured zero looks like.",
        "type": "object",
        "additionalProperties": False,
        "required": ["coverage_schema_version", "status", "tool",
                     "line_percent", "branch_percent", "reason",
                     "install_command", "declared_line_threshold", "excluded"],
        "properties": {
            "branch_percent": _MAYBE_NUMBER,
            "covered_branches": _MAYBE_INT,
            "covered_lines": _MAYBE_INT,
            "coverage_schema_version": {"const": COVERAGE_SCHEMA_VERSION},
            "declared_line_threshold": {"type": "number", "minimum": 0,
                                        "maximum": 100},
            "excluded": _STRINGS,
            "install_command": {"type": "string", "minLength": 1},
            "line_percent": _MAYBE_NUMBER,
            "low_coverage_critical_modules": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["module", "line_percent"],
                    "properties": {
                        "line_percent": {"type": "number"},
                        "missing_lines": _MAYBE_INT,
                        "module": {"type": "string"},
                        "statements": _MAYBE_INT,
                    },
                },
            },
            "measured_module_count": _MAYBE_INT,
            "profile": {"type": "string"},
            "reason": {"type": "string"},
            "status": {"enum": ["MEASURED", "BLOCKED"]},
            "tool": {"type": "string", "minLength": 1},
            "tool_version": {"type": ["string", "null"]},
            "total_branches": _MAYBE_INT,
            "total_lines": _MAYBE_INT,
        },
    }


def _reproducibility_schema() -> Dict[str, Any]:
    generator = {
        "type": "object",
        "additionalProperties": False,
        "required": ["generator", "module", "status", "artifact_count",
                     "unstable_artifacts", "stale_committed_artifacts",
                     "excluded_from_committed_comparison",
                     "missing_committed_artifacts"],
        "properties": {
            "artifact_count": _INT,
            "excluded_from_committed_comparison": _STRINGS,
            "generator": {"type": "string", "minLength": 1},
            "missing_committed_artifacts": _STRINGS,
            "module": {"type": "string", "minLength": 1},
            "reason": {"type": "string"},
            "stale_committed_artifacts": _STRINGS,
            "status": {"enum": ["REPRODUCIBLE", "MISMATCH", "STALE",
                                "BLOCKED"]},
            "unstable_artifacts": _STRINGS,
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "reproducibility-report.schema.json",
        "title": "WP-19 reproducibility report",
        "description": "Each deterministic generator rebuilt twice under two "
                       "different hash seeds, and compared with the committed "
                       "bytes. Artifacts that record their environment are "
                       "listed as excluded rather than silently skipped.",
        "type": "object",
        "additionalProperties": False,
        "required": ["reproducibility_schema_version", "status", "generators",
                     "hash_seeds", "note"],
        "properties": {
            "generators": {"type": "array", "items": generator,
                           "minItems": 1},
            "hash_seeds": {"type": "array", "items": {"type": "string"},
                           "minItems": 2, "maxItems": 2},
            "note": {"type": "string", "minLength": 1},
            "reproducibility_schema_version": {
                "const": REPRODUCIBILITY_SCHEMA_VERSION},
            "status": {"enum": ["REPRODUCIBLE", "MISMATCH", "STALE",
                                "BLOCKED"]},
        },
    }


def _flaky_schema() -> Dict[str, Any]:
    flaky_test = {
        "type": "object",
        "additionalProperties": False,
        "required": ["test_id", "outcomes_by_repetition", "distinct_outcomes"],
        "properties": {
            "distinct_outcomes": {"type": "array",
                                  "items": {"enum": _values(Outcome)},
                                  "minItems": 2},
            "outcomes_by_repetition": {"type": "array",
                                       "items": {"enum": _values(Outcome)},
                                       "minItems": 2},
            "test_id": {"type": "string", "minLength": 1},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "flaky-report.schema.json",
        "title": "WP-19 flaky-test report",
        "description": "A documented critical subset repeated under one fixed "
                       "hash seed. A test whose outcome differed between "
                       "repetitions is listed with what it produced each "
                       "time; `distinct_outcomes` has minItems 2 because a "
                       "test that agreed with itself is not a flaky test.",
        "type": "object",
        "additionalProperties": False,
        "required": ["flaky_schema_version", "profile", "repetitions",
                     "status", "flaky_tests", "flaky_test_count",
                     "unstable_selection", "hash_seed", "is_stable",
                     "counts_by_repetition"],
        "properties": {
            "counts_by_repetition": {"type": "array",
                                     "items": _summary_schema()},
            "flaky_schema_version": {"const": FLAKY_SCHEMA_VERSION},
            "flaky_test_count": _INT,
            "flaky_tests": {"type": "array", "items": flaky_test},
            "hash_seed": {"type": "string"},
            "is_stable": {"type": "boolean"},
            "note": {"type": "string"},
            "profile": {"type": "string", "minLength": 1},
            "repetitions": _INT,
            "status": {"enum": ["STABLE", "FLAKY", "BLOCKED"]},
            "unstable_selection": _STRINGS,
        },
    }


def _gate_status_schema() -> Dict[str, Any]:
    blocker = {
        "type": "object",
        "additionalProperties": False,
        "required": ["blocking", "code", "detail", "owner"],
        "properties": {
            "blocking": {"const": True},
            "code": {"type": "string",
                     "pattern": "^VERIFICATION_[A-Z0-9_]+$"},
            "detail": {"type": "string", "minLength": 1},
            # Never "code": every blocker below is closed by a person, a
            # machine or a later work package.
            "owner": {"type": "string", "minLength": 1},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "wp19-gate-status.schema.json",
        "title": "WP-19 gate status",
        "description": "What WP-19 may say, component by component. "
                       "`release_may_proceed` is one more field beside the "
                       "others rather than instead of them: the suite can be "
                       "entirely green while PostgreSQL was never reached, "
                       "coverage was never measured and the claim boundary is "
                       "unapproved, and a single boolean cannot say that.",
        "type": "object",
        "additionalProperties": True,
        "required": ["gate_status_schema_version", "work_package",
                     "discovered_test_count", "counts", "execution_status",
                     "category_status", "requirement_status", "coverage",
                     "coverage_tool_available", "postgresql_test_status",
                     "asgi_runtime_status", "browser_e2e_status",
                     "flaky_repeat_status", "reproducibility_status",
                     "run_evidence_status", "claim_boundary_approved",
                     "claim_boundary_status", "scientific_validation_performed",
                     "safety_gate_note", "safety_invariant_map_only",
                     "not_scientific_validation", "wp20_started",
                     "blockers", "blocker_count", "release_may_proceed"],
        "properties": {
            "asgi_runtime_status": {"enum": _values(Outcome)},
            "blocker_count": _INT,
            "blockers": {"type": "array", "items": blocker},
            "browser_e2e_status": {"enum": _values(Outcome)},
            "category_status": {
                "type": "object",
                "propertyNames": {"enum": _values(Category)},
                "additionalProperties": {"type": "object"},
            },
            "claim_boundary_approved": {"type": "boolean"},
            "claim_boundary_status": {"type": "string", "minLength": 1},
            "counts": {
                "type": "object",
                "additionalProperties": False,
                "required": ["discovered", "executed", "passed", "failed",
                             "errored", "skipped", "unexplained_skips",
                             "not_executed"],
                "properties": {
                    "discovered": _INT, "errored": _MAYBE_INT,
                    "executed": _MAYBE_INT, "failed": _MAYBE_INT,
                    "not_executed": _MAYBE_INT, "passed": _MAYBE_INT,
                    "skipped": _MAYBE_INT, "unexplained_skips": _MAYBE_INT,
                },
            },
            "coverage": {"type": "object"},
            "coverage_tool_available": {"type": "boolean"},
            "discovered_test_count": {"type": "integer", "minimum": 1},
            "execution_status": {"enum": _values(Outcome) + ["BLOCKED"]},
            "flaky_repeat_status": {"enum": ["STABLE", "FLAKY", "BLOCKED",
                                             None]},
            "gate_status_schema_version": {"const": GATE_STATUS_SCHEMA_VERSION},
            "not_scientific_validation": {"type": "string", "minLength": 1},
            "postgresql_test_status": {"enum": _values(Outcome)},
            "release_may_proceed": {"type": "boolean"},
            "reproducibility_status": {"enum": ["REPRODUCIBLE", "MISMATCH",
                                                "STALE", "BLOCKED", None]},
            "requirement_status": {"type": "object"},
            "run_evidence_status": {"enum": ["VERIFIED", "BLOCKED",
                                             "RUN_FAILED",
                                             "STALE_EVIDENCE_REJECTED"]},
            "safety_gate_note": {"type": "string", "minLength": 1},
            # Was pinned ``const: True`` while no safety gate existed. WP-20
            # built one, so this became a measurement rather than a
            # declaration - changed here, in a published schema, together with
            # the gate status that sets it and the tests that assert it.
            # ``safety_gate_status`` below carries WP-20's measured result and
            # is never inferred: ABSENT when no WP-20 status is committed.
            "safety_invariant_map_only": {"type": "boolean"},
            "safety_gate_status": {"enum": _values(Outcome) + ["ABSENT"]},
            "safety_invariant_count": _MAYBE_INT,
            "safety_negative_control_count": _MAYBE_INT,
            "safety_negative_controls_detected": _MAYBE_INT,
            # WP-21's measured state, read the same way and equally never
            # inferred. WP-19 reports it and does not block on it: a green
            # test suite is not a validation result, and making one wait on
            # the other would blur exactly the line both packages defend.
            "benchmark_gate_status": {"enum": _values(Outcome)
                                      + ["ABSENT", "BLOCKED"]},
            "validation_metrics_implemented": {"type": "boolean"},
            "validation_metric_definition_count": _MAYBE_INT,
            "numeric_validation_metric_count": _MAYBE_INT,
            "validation_evidence_case_count": _MAYBE_INT,
            "scientific_validation_performed": {"const": False},
            "work_package": {"const": "WP-19"},
            "wp20_started": {"type": "boolean"},
        },
    }


def build_schemas() -> Dict[str, Dict[str, Any]]:
    """Every WP-19 schema, keyed by its repository-relative path."""
    return {
        COVERAGE_SCHEMA_PATH: _coverage_schema(),
        FLAKY_SCHEMA_PATH: _flaky_schema(),
        GATE_STATUS_SCHEMA_PATH: _gate_status_schema(),
        MATRIX_SCHEMA_PATH: _matrix_schema(),
        PLAN_SCHEMA_PATH: _plan_schema(),
        REPRODUCIBILITY_SCHEMA_PATH: _reproducibility_schema(),
        RESULT_SCHEMA_PATH: _result_schema(),
    }


def load_schema(path: str, root: str = _REPO_ROOT) -> Mapping[str, Any]:
    """The committed schema at ``path``."""
    with io.open(os.path.join(root, *path.split("/")), "r",
                 encoding="utf-8") as handle:
        return json.load(handle)


def _validate(payload: Mapping[str, Any], path: str,
              schema: Optional[Mapping[str, Any]] = None) -> Tuple[str, ...]:
    return validate_against_schema(
        payload, schema if schema is not None else build_schemas()[path])


def validate_verification_plan(payload, schema=None) -> Tuple[str, ...]:
    return _validate(payload, PLAN_SCHEMA_PATH, schema)


def validate_requirement_matrix(payload, schema=None) -> Tuple[str, ...]:
    return _validate(payload, MATRIX_SCHEMA_PATH, schema)


def validate_verification_result(payload, schema=None) -> Tuple[str, ...]:
    return _validate(payload, RESULT_SCHEMA_PATH, schema)


def validate_coverage_summary(payload, schema=None) -> Tuple[str, ...]:
    return _validate(payload, COVERAGE_SCHEMA_PATH, schema)


def validate_reproducibility_report(payload, schema=None) -> Tuple[str, ...]:
    return _validate(payload, REPRODUCIBILITY_SCHEMA_PATH, schema)


def validate_flaky_report(payload, schema=None) -> Tuple[str, ...]:
    return _validate(payload, FLAKY_SCHEMA_PATH, schema)


def validate_wp19_gate_status(payload, schema=None) -> Tuple[str, ...]:
    return _validate(payload, GATE_STATUS_SCHEMA_PATH, schema)
