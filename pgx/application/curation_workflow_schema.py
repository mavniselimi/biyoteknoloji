# -*- coding: utf-8 -*-
"""Loading and applying the WP-10 published JSON Schemas.

Standard library only, and in the application layer for the same reason
:mod:`pgx.application.curation_schema` is: reading a file is an environment
concern, and :mod:`pgx.curation` stays a pure domain package.

The validator is WP-06's :func:`~pgx.application.snapshot_schema.
validate_against_schema`, which **raises on any keyword it does not
implement**. A validator that quietly ignored an unknown keyword would report
a document as valid while not checking the constraint its author wrote.

Six documents are published. Each asserts in the schema, rather than only in
prose, the thing a hand-edited file would most usefully lie about:

* a RAW work item names no submitted revision, a decided one does, and every
  legacy value is namespaced as unreviewed input;
* a revision is authored by a scientific curator, cites at least one evidence
  record, and carries no risk level, dose, recommendation or reviewer;
* a review pins the revision hash and the author it was checked against, and
  its decision and resulting state agree;
* an adjudication preserves both original positions in full and reports no
  consensus, merged position or agreement score;
* an approval audit event names the revision, its hash and its author;
* a rule approval envelope may only encode a CURATED conclusion, and carries no
  flag that would bypass the process.
"""

from __future__ import annotations

import io
import json
import os
from typing import Any, Mapping, Optional, Tuple

from pgx.application.snapshot_schema import validate_against_schema

__all__ = [
    "CURATION_ADJUDICATION_SCHEMA_PATH",
    "CURATION_AUDIT_EVENT_SCHEMA_PATH",
    "CURATION_REVIEW_SCHEMA_PATH",
    "CURATION_REVISION_SCHEMA_PATH",
    "CURATION_WORK_ITEM_SCHEMA_PATH",
    "RULE_APPROVAL_ENVELOPE_SCHEMA_PATH",
    "load_schema",
    "validate_curation_adjudication",
    "validate_curation_audit_event",
    "validate_curation_review",
    "validate_curation_revision",
    "validate_curation_work_item",
    "validate_rule_approval_envelope_document",
]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_SCHEMAS = os.path.join(_REPO_ROOT, "schemas")

CURATION_WORK_ITEM_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "curation-work-item.schema.json")
CURATION_REVISION_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "curation-revision.schema.json")
CURATION_REVIEW_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "curation-review.schema.json")
CURATION_ADJUDICATION_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "curation-adjudication.schema.json")
CURATION_AUDIT_EVENT_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "curation-audit-event.schema.json")
RULE_APPROVAL_ENVELOPE_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "rule-approval-envelope.schema.json")


def load_schema(path: str) -> Mapping[str, Any]:
    """Read one published schema."""
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _validate(payload: Mapping[str, Any], path: str,
              schema: Optional[Mapping[str, Any]]) -> Tuple[str, ...]:
    return validate_against_schema(
        payload, schema if schema is not None else load_schema(path))


def validate_curation_work_item(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way ``payload`` fails the published work-item schema."""
    return _validate(payload, CURATION_WORK_ITEM_SCHEMA_PATH, schema)


def validate_curation_revision(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way one revision fails the published revision schema."""
    return _validate(payload, CURATION_REVISION_SCHEMA_PATH, schema)


def validate_curation_review(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way one review fails the published review schema."""
    return _validate(payload, CURATION_REVIEW_SCHEMA_PATH, schema)


def validate_curation_adjudication(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way one adjudication fails the published adjudication schema."""
    return _validate(payload, CURATION_ADJUDICATION_SCHEMA_PATH, schema)


def validate_curation_audit_event(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way one audit event fails the published event schema."""
    return _validate(payload, CURATION_AUDIT_EVENT_SCHEMA_PATH, schema)


def validate_rule_approval_envelope_document(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way an envelope fails the published envelope schema.

    Shape only. The semantic checks - separation of duties, timestamp order,
    whether the named parties hold the roles they claim - live in
    :mod:`pgx.curation.workflow.approval`, because a schema cannot express
    "the reviewer is not the author".
    """
    return _validate(payload, RULE_APPROVAL_ENVELOPE_SCHEMA_PATH, schema)
