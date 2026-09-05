# -*- coding: utf-8 -*-
"""Loading and applying the WP-09 published JSON Schemas.

Standard library only, and in the application layer for the same reason
:mod:`pgx.application.evidence_schema` is: reading a file is an environment
concern, and :mod:`pgx.curation` stays a pure domain package.

The validator is WP-06's :func:`~pgx.application.snapshot_schema.
validate_against_schema`, which **raises on any keyword it does not
implement**. A validator that quietly ignored an unknown keyword would report
a document as valid while not checking the constraint its author wrote.

Five documents are published. Each asserts in the schema, rather than only in
prose, the thing a hand-edited file would most usefully lie about:

* the protocol's vocabularies are ``DRAFT_AWAITING_EXPERT_REVIEW``, and only a
  scientific role may appear as its approver;
* every field carries an owner and a null meaning;
* a curation record holds no risk level, confidence score, dose or rule
  condition;
* an exercise case is blinded and holds exactly one case role;
* a comparison has no winner, consensus, merged response or agreement score.
"""

from __future__ import annotations

import io
import json
import os
from typing import Any, Dict, Mapping, Optional, Tuple

from pgx.application.snapshot_schema import validate_against_schema

__all__ = [
    "CURATION_FIELD_DICTIONARY_SCHEMA_PATH",
    "CURATION_PROTOCOL_SCHEMA_PATH",
    "CURATION_RECORD_SCHEMA_PATH",
    "INTER_CURATOR_COMPARISON_SCHEMA_PATH",
    "INTER_CURATOR_EXERCISE_SCHEMA_PATH",
    "load_schema",
    "validate_curation_field_dictionary",
    "validate_curation_protocol",
    "validate_curation_record",
    "validate_inter_curator_comparison",
    "validate_inter_curator_exercise",
]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_SCHEMAS = os.path.join(_REPO_ROOT, "schemas")

CURATION_PROTOCOL_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "curation-protocol.schema.json")
CURATION_FIELD_DICTIONARY_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "curation-field-dictionary.schema.json")
CURATION_RECORD_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "curation-record.schema.json")
INTER_CURATOR_EXERCISE_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "inter-curator-exercise.schema.json")
INTER_CURATOR_COMPARISON_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "inter-curator-comparison.schema.json")


def load_schema(path: str) -> Mapping[str, Any]:
    """Read one published schema."""
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _validate(payload: Mapping[str, Any], path: str,
              schema: Optional[Mapping[str, Any]]) -> Tuple[str, ...]:
    return validate_against_schema(
        payload, schema if schema is not None else load_schema(path))


def validate_curation_protocol(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way ``payload`` fails the published protocol schema."""
    return _validate(payload, CURATION_PROTOCOL_SCHEMA_PATH, schema)


def validate_curation_field_dictionary(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way ``payload`` fails the published field dictionary schema."""
    return _validate(payload, CURATION_FIELD_DICTIONARY_SCHEMA_PATH, schema)


def validate_curation_record(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way one curation record fails the published record schema."""
    return _validate(payload, CURATION_RECORD_SCHEMA_PATH, schema)


def validate_inter_curator_exercise(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way an exercise packet fails the published exercise schema."""
    return _validate(payload, INTER_CURATOR_EXERCISE_SCHEMA_PATH, schema)


def validate_inter_curator_comparison(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way a comparison fails the published comparison schema."""
    return _validate(payload, INTER_CURATOR_COMPARISON_SCHEMA_PATH, schema)
