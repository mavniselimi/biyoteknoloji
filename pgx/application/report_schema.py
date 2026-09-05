# -*- coding: utf-8 -*-
"""Loading and applying the WP-15 published JSON Schemas.

Standard library only, and in the application layer for the same reason
:mod:`pgx.application.assessment_schema` is: reading a file is an environment
concern and :mod:`pgx.reporting` stays a pure projection package.

The validator is WP-06's :func:`~pgx.application.snapshot_schema.
validate_against_schema`, which **raises on any keyword it does not
implement**. That is why none of these schemas uses ``contains``: a schema
asserting something the validator cannot check would report documents as valid
while silently not checking the constraint its author wrote.

Five documents are published. The two that carry the most weight are the
canonical result and the structured report, because ``additionalProperties:
false`` on those is what actually stops a dose, a score, a ranking or an
authored sentence being attached to a report by anything downstream.
"""

from __future__ import annotations

import io
import json
import os
from typing import Any, Mapping, Optional, Tuple

from pgx.application.snapshot_schema import validate_against_schema

__all__ = [
    "CANONICAL_RESULT_SCHEMA_PATH",
    "REPORT_ARTIFACT_MANIFEST_SCHEMA_PATH",
    "REPORT_FACT_LEDGER_SCHEMA_PATH",
    "STRUCTURED_REPORT_SCHEMA_PATH",
    "WP15_GATE_STATUS_SCHEMA_PATH",
    "WP15_SCHEMA_PATHS",
    "load_schema",
    "validate_canonical_assessment_result",
    "validate_report_artifact_manifest",
    "validate_report_fact_ledger",
    "validate_structured_report",
    "validate_wp15_gate_status",
]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_SCHEMAS = os.path.join(_REPO_ROOT, "schemas")

CANONICAL_RESULT_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "canonical-assessment-result.schema.json")
STRUCTURED_REPORT_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "structured-report.schema.json")
REPORT_FACT_LEDGER_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "report-fact-ledger.schema.json")
REPORT_ARTIFACT_MANIFEST_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "report-artifact-manifest.schema.json")
WP15_GATE_STATUS_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "wp15-gate-status.schema.json")

WP15_SCHEMA_PATHS: Tuple[str, ...] = (
    CANONICAL_RESULT_SCHEMA_PATH,
    STRUCTURED_REPORT_SCHEMA_PATH,
    REPORT_FACT_LEDGER_SCHEMA_PATH,
    REPORT_ARTIFACT_MANIFEST_SCHEMA_PATH,
    WP15_GATE_STATUS_SCHEMA_PATH,
)


def load_schema(path: str) -> Mapping[str, Any]:
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _validate(payload: Mapping[str, Any], path: str,
              schema: Optional[Mapping[str, Any]]) -> Tuple[str, ...]:
    return validate_against_schema(
        payload, schema if schema is not None else load_schema(path))


def validate_canonical_assessment_result(payload, schema=None
                                         ) -> Tuple[str, ...]:
    """Every way one canonical result fails its published schema."""
    return _validate(payload, CANONICAL_RESULT_SCHEMA_PATH, schema)


def validate_structured_report(payload, schema=None) -> Tuple[str, ...]:
    """Every way one structured report fails its published schema."""
    return _validate(payload, STRUCTURED_REPORT_SCHEMA_PATH, schema)


def validate_report_fact_ledger(payload, schema=None) -> Tuple[str, ...]:
    """Every way one fact ledger fails its published schema."""
    return _validate(payload, REPORT_FACT_LEDGER_SCHEMA_PATH, schema)


def validate_report_artifact_manifest(payload, schema=None) -> Tuple[str, ...]:
    """Every way one artifact manifest fails its published schema."""
    return _validate(payload, REPORT_ARTIFACT_MANIFEST_SCHEMA_PATH, schema)


def validate_wp15_gate_status(payload, schema=None) -> Tuple[str, ...]:
    """Every way one gate status fails its published schema."""
    return _validate(payload, WP15_GATE_STATUS_SCHEMA_PATH, schema)
