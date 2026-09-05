# -*- coding: utf-8 -*-
"""Loading and applying the WP-11 published JSON Schemas.

Standard library only, and in the application layer for the same reason
:mod:`pgx.application.curation_workflow_schema` is: reading a file is an
environment concern, and :mod:`pgx.rules` stays a pure domain package.

The validator is WP-06's :func:`~pgx.application.snapshot_schema.
validate_against_schema`, which **raises on any keyword it does not
implement**. A validator that quietly ignored an unknown keyword would report
a document as valid while not checking the constraint its author wrote.

Six documents are published. Each asserts in the schema, rather than only in
prose, the thing a hand-edited file would most usefully lie about:

* a rule's condition names one gene, one drug and explicitly listed
  phenotypes, and its outcome carries an attention level and nothing that
  resembles a dose, a recommendation, a drug choice or a safety claim;
* a manifest pins every member by content hash and presents its axis list as
  membership rather than coverage;
* a build log carries the operational facts that are excluded from the
  semantic hash, which is what makes determinism assertable;
* an approval list names four separated roles per member rule, in the
  artifact itself rather than in a table that can change afterwards;
* a gate status cannot be edited into an all-clear: an empty blocker list is
  refused and every real count is required;
* a legacy inventory promotes nothing: a candidate claiming eligibility must
  carry no blockers, and legacy clinical text stays under ``raw_`` keys with
  no field it could become an outcome in.

These schemas describe documents, so validating one proves the document is
well formed. It proves nothing about whether the people it names are real,
hold the roles claimed, or performed the acts recorded. That is authentication
and governance work, owned by people and by WP-23, and no schema can stand in
for it.
"""

from __future__ import annotations

import io
import json
import os
from typing import Any, Mapping, Optional, Tuple

from pgx.application.snapshot_schema import validate_against_schema

__all__ = [
    "COMPUTABLE_RULE_SCHEMA_PATH",
    "LEGACY_RULE_CANDIDATE_INVENTORY_SCHEMA_PATH",
    "RULESET_APPROVAL_LIST_SCHEMA_PATH",
    "RULESET_BUILD_LOG_SCHEMA_PATH",
    "RULESET_MANIFEST_SCHEMA_PATH",
    "WP11_GATE_STATUS_SCHEMA_PATH",
    "WP11_SCHEMA_PATHS",
    "load_schema",
    "validate_computable_rule",
    "validate_legacy_rule_candidate_inventory",
    "validate_ruleset_approval_list",
    "validate_ruleset_build_log",
    "validate_ruleset_manifest",
    "validate_wp11_gate_status",
]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_SCHEMAS = os.path.join(_REPO_ROOT, "schemas")

COMPUTABLE_RULE_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "computable-rule.schema.json")
RULESET_MANIFEST_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "ruleset-manifest.schema.json")
RULESET_BUILD_LOG_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "ruleset-build-log.schema.json")
RULESET_APPROVAL_LIST_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "ruleset-approval-list.schema.json")
WP11_GATE_STATUS_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "wp11-gate-status.schema.json")
LEGACY_RULE_CANDIDATE_INVENTORY_SCHEMA_PATH = os.path.join(
    _SCHEMAS, "legacy-rule-candidate-inventory.schema.json")

#: Every schema WP-11 publishes, in the order the documents are produced.
WP11_SCHEMA_PATHS: Tuple[str, ...] = (
    COMPUTABLE_RULE_SCHEMA_PATH,
    RULESET_MANIFEST_SCHEMA_PATH,
    RULESET_BUILD_LOG_SCHEMA_PATH,
    RULESET_APPROVAL_LIST_SCHEMA_PATH,
    WP11_GATE_STATUS_SCHEMA_PATH,
    LEGACY_RULE_CANDIDATE_INVENTORY_SCHEMA_PATH,
)


def load_schema(path: str) -> Mapping[str, Any]:
    """Read one published schema."""
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _validate(payload: Mapping[str, Any], path: str,
              schema: Optional[Mapping[str, Any]]) -> Tuple[str, ...]:
    return validate_against_schema(
        payload, schema if schema is not None else load_schema(path))


def validate_computable_rule(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way one rule document fails the published rule schema."""
    return _validate(payload, COMPUTABLE_RULE_SCHEMA_PATH, schema)


def validate_ruleset_manifest(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way one manifest fails the published manifest schema."""
    return _validate(payload, RULESET_MANIFEST_SCHEMA_PATH, schema)


def validate_ruleset_build_log(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way one build log fails the published build-log schema."""
    return _validate(payload, RULESET_BUILD_LOG_SCHEMA_PATH, schema)


def validate_ruleset_approval_list(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way one approval list fails the published approval schema."""
    return _validate(payload, RULESET_APPROVAL_LIST_SCHEMA_PATH, schema)


def validate_wp11_gate_status(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way one gate status fails the published gate-status schema."""
    return _validate(payload, WP11_GATE_STATUS_SCHEMA_PATH, schema)


def validate_legacy_rule_candidate_inventory(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Every way one inventory fails the published inventory schema."""
    return _validate(payload, LEGACY_RULE_CANDIDATE_INVENTORY_SCHEMA_PATH,
                     schema)
