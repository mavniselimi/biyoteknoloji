# -*- coding: utf-8 -*-
"""Loading and applying the WP-12 published JSON Schemas.

Standard library only, and in the application layer for the reason
:mod:`pgx.application.rules_schema` is: reading a file is an environment
concern, and :mod:`pgx.engine` stays a pure engine package.

The validator is WP-06's :func:`~pgx.application.snapshot_schema.
validate_against_schema`, which **raises on any keyword it does not
implement**. A validator that quietly ignored an unknown keyword would report
a document as valid while not checking the constraint its author wrote.

Four documents are published, and each asserts in the schema what a
hand-edited file would most usefully lie about:

* a profile keeps every gene it was given, including the ones it could not
  interpret, and carries no attention, coverage, dose or risk field;
* a normalisation result that failed carries a reason code and no phenotype,
  so no reader can find a phenotype on a failure;
* a match result carries the comparison and nothing about its consequences;
* a regression report cannot omit its unexpected differences, and cannot hide
  an allowlisted difference that has stopped occurring.
"""

from __future__ import annotations

import io
import json
import os
from typing import Any, Mapping, Optional, Tuple

from pgx.application.snapshot_schema import validate_against_schema

__all__ = [
    "PHENOTYPE_MATCH_RESULT_SCHEMA_PATH",
    "PHENOTYPE_NORMALIZATION_RESULT_SCHEMA_PATH",
    "PHENOTYPE_PROFILE_SCHEMA_PATH",
    "PHENOTYPE_REGRESSION_REPORT_SCHEMA_PATH",
    "WP12_SCHEMA_PATHS",
    "load_schema",
    "validate_phenotype_match_result",
    "validate_phenotype_normalization_result",
    "validate_phenotype_profile",
    "validate_phenotype_regression_report",
]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_SCHEMAS = os.path.join(_REPO_ROOT, "schemas")

PHENOTYPE_PROFILE_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "phenotype-profile.schema.json")
PHENOTYPE_NORMALIZATION_RESULT_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "phenotype-normalization-result.schema.json")
PHENOTYPE_MATCH_RESULT_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "phenotype-match-result.schema.json")
PHENOTYPE_REGRESSION_REPORT_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "phenotype-regression-report.schema.json")

#: Every schema WP-12 publishes, in the order the documents are produced.
WP12_SCHEMA_PATHS: Tuple[str, ...] = (
    PHENOTYPE_PROFILE_SCHEMA_PATH,
    PHENOTYPE_NORMALIZATION_RESULT_SCHEMA_PATH,
    PHENOTYPE_MATCH_RESULT_SCHEMA_PATH,
    PHENOTYPE_REGRESSION_REPORT_SCHEMA_PATH,
)


def load_schema(path: str) -> Mapping[str, Any]:
    """Read one published schema."""
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _validate(payload: Mapping[str, Any], path: str,
              schema: Optional[Mapping[str, Any]]) -> Tuple[str, ...]:
    return validate_against_schema(
        payload, schema if schema is not None else load_schema(path))


def validate_phenotype_profile(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way one profile fails the published profile schema."""
    return _validate(payload, PHENOTYPE_PROFILE_SCHEMA_PATH, schema)


def validate_phenotype_normalization_result(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way one normalisation result fails its schema."""
    return _validate(payload, PHENOTYPE_NORMALIZATION_RESULT_SCHEMA_PATH,
                     schema)


def validate_phenotype_match_result(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way one match decision fails its schema."""
    return _validate(payload, PHENOTYPE_MATCH_RESULT_SCHEMA_PATH, schema)


def validate_phenotype_regression_report(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way one regression report fails its schema."""
    return _validate(payload, PHENOTYPE_REGRESSION_REPORT_SCHEMA_PATH, schema)
