# -*- coding: utf-8 -*-
"""Loading and applying the WP-14 published JSON Schemas.

Standard library only, and in the application layer for the reason
:mod:`pgx.application.coverage_schema` is: reading a file is an environment
concern and :mod:`pgx.engine` stays a pure engine package.

The validator is WP-06's :func:`~pgx.application.snapshot_schema.
validate_against_schema`, which **raises on any keyword it does not
implement**. That is why none of these schemas uses ``contains``: a schema
asserting something the validator cannot check would report documents as valid
while silently not checking the constraint its author wrote.

Seven documents are published. The one that carries the most weight is the
computation, because ``additionalProperties: false`` on it is what actually
stops a dose, a recommendation or a rendered sentence being attached to a
calculated result by anything downstream.
"""

from __future__ import annotations

import io
import json
import os
from typing import Any, Mapping, Optional, Tuple

from pgx.application.snapshot_schema import validate_against_schema

__all__ = [
    "ASSESSMENT_COMPUTATION_SCHEMA_PATH",
    "ASSESSMENT_FAILURE_SCHEMA_PATH",
    "ASSESSMENT_FINDING_SCHEMA_PATH",
    "ASSESSMENT_INPUT_SCHEMA_PATH",
    "ASSESSMENT_REGRESSION_REPORT_SCHEMA_PATH",
    "MEDICATION_ASSESSMENT_SCHEMA_PATH",
    "WP14_GATE_STATUS_SCHEMA_PATH",
    "WP14_SCHEMA_PATHS",
    "load_schema",
    "validate_assessment_computation",
    "validate_assessment_failure",
    "validate_assessment_finding",
    "validate_assessment_input",
    "validate_assessment_regression_report",
    "validate_medication_assessment",
    "validate_wp14_gate_status",
]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_SCHEMAS = os.path.join(_REPO_ROOT, "schemas")

ASSESSMENT_INPUT_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "assessment-input.schema.json")
ASSESSMENT_FINDING_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "assessment-finding.schema.json")
MEDICATION_ASSESSMENT_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "medication-assessment.schema.json")
ASSESSMENT_COMPUTATION_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "assessment-computation.schema.json")
ASSESSMENT_FAILURE_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "assessment-failure.schema.json")
ASSESSMENT_REGRESSION_REPORT_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "assessment-regression-report.schema.json")
WP14_GATE_STATUS_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "wp14-gate-status.schema.json")

WP14_SCHEMA_PATHS: Tuple[str, ...] = (
    ASSESSMENT_INPUT_SCHEMA_PATH,
    ASSESSMENT_FINDING_SCHEMA_PATH,
    MEDICATION_ASSESSMENT_SCHEMA_PATH,
    ASSESSMENT_COMPUTATION_SCHEMA_PATH,
    ASSESSMENT_FAILURE_SCHEMA_PATH,
    ASSESSMENT_REGRESSION_REPORT_SCHEMA_PATH,
    WP14_GATE_STATUS_SCHEMA_PATH,
)


def load_schema(path: str) -> Mapping[str, Any]:
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _validate(payload: Mapping[str, Any], path: str,
              schema: Optional[Mapping[str, Any]]) -> Tuple[str, ...]:
    return validate_against_schema(
        payload, schema if schema is not None else load_schema(path))


def validate_assessment_input(payload, schema=None) -> Tuple[str, ...]:
    """Every way one assessment input fails its published schema."""
    return _validate(payload, ASSESSMENT_INPUT_SCHEMA_PATH, schema)


def validate_assessment_finding(payload, schema=None) -> Tuple[str, ...]:
    """Every way one finding fails its published schema."""
    return _validate(payload, ASSESSMENT_FINDING_SCHEMA_PATH, schema)


def validate_medication_assessment(payload, schema=None) -> Tuple[str, ...]:
    """Every way one medication result fails its published schema."""
    return _validate(payload, MEDICATION_ASSESSMENT_SCHEMA_PATH, schema)


def validate_assessment_computation(payload, schema=None) -> Tuple[str, ...]:
    """Every way one computation fails its published schema."""
    return _validate(payload, ASSESSMENT_COMPUTATION_SCHEMA_PATH, schema)


def validate_assessment_failure(payload, schema=None) -> Tuple[str, ...]:
    """Every way one refusal record fails its published schema."""
    return _validate(payload, ASSESSMENT_FAILURE_SCHEMA_PATH, schema)


def validate_assessment_regression_report(payload, schema=None
                                          ) -> Tuple[str, ...]:
    """Every way one regression report fails its published schema."""
    return _validate(payload, ASSESSMENT_REGRESSION_REPORT_SCHEMA_PATH, schema)


def validate_wp14_gate_status(payload, schema=None) -> Tuple[str, ...]:
    """Every way one gate status fails its published schema."""
    return _validate(payload, WP14_GATE_STATUS_SCHEMA_PATH, schema)
