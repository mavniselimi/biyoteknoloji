# -*- coding: utf-8 -*-
"""Loading and applying the WP-07 published JSON Schemas.

Standard library only. Lives in the application layer for the same reason
:mod:`pgx.application.snapshot_schema` does: reading a file is an environment
concern, and neither the domain nor the normalization package grows a
filesystem dependency for it.

The validator itself is not reimplemented here. It is the one WP-06 wrote -
:func:`pgx.application.snapshot_schema.validate_against_schema` - which
implements a fixed subset of JSON Schema and **raises on any keyword it does
not implement**. That rule is the important one: a validator that quietly
ignored an unknown keyword would report a document as valid while not checking
the constraint the schema author wrote, which is worse than having no validator
at all.

Two documents are published:

* ``canonical-dataset-manifest.schema.json`` - the manifest of a sealed build.
* ``data-quality-report.schema.json`` - the DQ report inside it.

Both schemas assert, in the schema rather than only in prose, that a build's
lifecycle state is ``BUILDING`` and that every reconciliation balances. A
report that lost records between two counters cannot be published through this
schema.
"""

from __future__ import annotations

import io
import json
import os
from typing import Any, Mapping, Tuple

from pgx.application.snapshot_schema import validate_against_schema

__all__ = [
    "CANONICAL_MANIFEST_SCHEMA_PATH",
    "DQ_REPORT_SCHEMA_PATH",
    "load_canonical_manifest_schema",
    "load_dq_report_schema",
    "validate_canonical_manifest",
    "validate_dq_report",
]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

CANONICAL_MANIFEST_SCHEMA_PATH = os.path.join(
    _REPO_ROOT, "schemas", "canonical-dataset-manifest.schema.json")
DQ_REPORT_SCHEMA_PATH = os.path.join(
    _REPO_ROOT, "schemas", "data-quality-report.schema.json")


def _load(path: str) -> Mapping[str, Any]:
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_canonical_manifest_schema(
    path: str = CANONICAL_MANIFEST_SCHEMA_PATH,
) -> Mapping[str, Any]:
    """Read the published canonical build manifest schema."""
    return _load(path)


def load_dq_report_schema(
    path: str = DQ_REPORT_SCHEMA_PATH,
) -> Mapping[str, Any]:
    """Read the published data quality report schema."""
    return _load(path)


def validate_canonical_manifest(
    payload: Mapping[str, Any],
    schema: Mapping[str, Any] = None,
) -> Tuple[str, ...]:
    """Return every way ``payload`` fails the published manifest schema.

    An empty tuple means it validates. Problems are collected rather than
    raised on the first one, because a manifest under repair should show the
    whole list.
    """
    return validate_against_schema(
        payload, schema if schema is not None
        else load_canonical_manifest_schema())


def validate_dq_report(
    payload: Mapping[str, Any],
    schema: Mapping[str, Any] = None,
) -> Tuple[str, ...]:
    """Return every way ``payload`` fails the published DQ report schema."""
    return validate_against_schema(
        payload, schema if schema is not None else load_dq_report_schema())
