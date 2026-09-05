# -*- coding: utf-8 -*-
"""Loading and applying the WP-13 published JSON Schemas.

Standard library only, and in the application layer for the reason
:mod:`pgx.application.phenotype_schema` is: reading a file is an environment
concern, and :mod:`pgx.engine` stays a pure engine package.

The validator is WP-06's :func:`~pgx.application.snapshot_schema.
validate_against_schema`, which **raises on any keyword it does not
implement**. That is why none of these schemas uses ``contains``: a schema
asserting something the validator cannot check would report documents as valid
while not checking the constraint its author wrote.

Six documents are published. The one that carries the most weight is the
coverage manifest, whose ``expected_gene_keys`` is required and non-empty for
every declared drug: a drug with an empty expected scope can never be
incompletely covered, which is the single thing coverage exists to detect.
"""

from __future__ import annotations

import io
import json
import os
from typing import Any, Mapping, Optional, Tuple

from pgx.application.snapshot_schema import validate_against_schema

__all__ = [
    "AXIS_COVERAGE_SCHEMA_PATH",
    "COVERAGE_REGRESSION_REPORT_SCHEMA_PATH",
    "COVERAGE_RESULT_SCHEMA_PATH",
    "MEDICATION_COVERAGE_SCHEMA_PATH",
    "RULESET_COVERAGE_MANIFEST_SCHEMA_PATH",
    "WP13_GATE_STATUS_SCHEMA_PATH",
    "WP13_SCHEMA_PATHS",
    "load_schema",
    "validate_axis_coverage",
    "validate_coverage_regression_report",
    "validate_coverage_result",
    "validate_medication_coverage",
    "validate_ruleset_coverage_manifest",
    "validate_wp13_gate_status",
]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_SCHEMAS = os.path.join(_REPO_ROOT, "schemas")

RULESET_COVERAGE_MANIFEST_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "ruleset-coverage-manifest.schema.json")
AXIS_COVERAGE_SCHEMA_PATH = os.path.join(_SCHEMAS, "axis-coverage.schema.json")
MEDICATION_COVERAGE_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "medication-coverage.schema.json")
COVERAGE_RESULT_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "coverage-result.schema.json")
COVERAGE_REGRESSION_REPORT_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "coverage-regression-report.schema.json")
WP13_GATE_STATUS_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "wp13-gate-status.schema.json")

WP13_SCHEMA_PATHS: Tuple[str, ...] = (
    RULESET_COVERAGE_MANIFEST_SCHEMA_PATH,
    AXIS_COVERAGE_SCHEMA_PATH,
    MEDICATION_COVERAGE_SCHEMA_PATH,
    COVERAGE_RESULT_SCHEMA_PATH,
    COVERAGE_REGRESSION_REPORT_SCHEMA_PATH,
    WP13_GATE_STATUS_SCHEMA_PATH,
)


def load_schema(path: str) -> Mapping[str, Any]:
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _validate(payload: Mapping[str, Any], path: str,
              schema: Optional[Mapping[str, Any]]) -> Tuple[str, ...]:
    return validate_against_schema(
        payload, schema if schema is not None else load_schema(path))


def validate_ruleset_coverage_manifest(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way one coverage manifest fails its published schema."""
    return _validate(payload, RULESET_COVERAGE_MANIFEST_SCHEMA_PATH, schema)


def validate_axis_coverage(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way one axis result fails its published schema."""
    return _validate(payload, AXIS_COVERAGE_SCHEMA_PATH, schema)


def validate_medication_coverage(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way one medication result fails its published schema."""
    return _validate(payload, MEDICATION_COVERAGE_SCHEMA_PATH, schema)


def validate_coverage_result(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way one coverage result fails its published schema."""
    return _validate(payload, COVERAGE_RESULT_SCHEMA_PATH, schema)


def validate_coverage_regression_report(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way one regression report fails its published schema."""
    return _validate(payload, COVERAGE_REGRESSION_REPORT_SCHEMA_PATH, schema)


def validate_wp13_gate_status(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way one gate status fails its published schema."""
    return _validate(payload, WP13_GATE_STATUS_SCHEMA_PATH, schema)
