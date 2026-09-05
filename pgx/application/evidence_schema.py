# -*- coding: utf-8 -*-
"""Loading and applying the WP-08 published JSON Schemas.

Standard library only. Lives in the application layer for the same reason
:mod:`pgx.application.canonical_schema` does: reading a file is an environment
concern, and neither the domain nor the evidence package grows a filesystem
dependency for it.

The validator itself is not reimplemented here. It is the one WP-06 wrote -
:func:`pgx.application.snapshot_schema.validate_against_schema` - which
implements a fixed subset of JSON Schema and **raises on any keyword it does
not implement**. That rule is the important one: a validator that quietly
ignored an unknown keyword would report a document as valid while not checking
the constraint the schema author wrote, which is worse than having no validator
at all.

Three documents are published:

* ``evidence-build-manifest.schema.json`` - the manifest of a sealed build.
* ``evidence-record.schema.json`` - one stored record.
* ``draft-curation-proposal.schema.json`` - one unreviewed migration candidate.

Each schema asserts in the schema, rather than only in prose, the thing a
hand-edited file would most usefully lie about: a build's lifecycle state is
``BUILDING``; a record's ``normalized_metadata`` holds no project conclusion;
and a proposal carries the unreviewed status and all four warnings. A document
that edited those into something friendlier does not validate.
"""

from __future__ import annotations

import io
import json
import os
from typing import Any, Mapping, Optional, Tuple

from pgx.application.snapshot_schema import validate_against_schema

__all__ = [
    "DRAFT_CURATION_PROPOSAL_SCHEMA_PATH",
    "EVIDENCE_BUILD_MANIFEST_SCHEMA_PATH",
    "EVIDENCE_RECORD_SCHEMA_PATH",
    "load_draft_curation_proposal_schema",
    "load_evidence_build_manifest_schema",
    "load_evidence_record_schema",
    "validate_draft_curation_proposal",
    "validate_evidence_build_manifest",
    "validate_evidence_record",
]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

EVIDENCE_BUILD_MANIFEST_SCHEMA_PATH = os.path.join(
    _REPO_ROOT, "schemas", "evidence-build-manifest.schema.json")
EVIDENCE_RECORD_SCHEMA_PATH = os.path.join(
    _REPO_ROOT, "schemas", "evidence-record.schema.json")
DRAFT_CURATION_PROPOSAL_SCHEMA_PATH = os.path.join(
    _REPO_ROOT, "schemas", "draft-curation-proposal.schema.json")


def _load(path: str) -> Mapping[str, Any]:
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_evidence_build_manifest_schema(
    path: str = EVIDENCE_BUILD_MANIFEST_SCHEMA_PATH,
) -> Mapping[str, Any]:
    """Read the published evidence build manifest schema."""
    return _load(path)


def load_evidence_record_schema(
    path: str = EVIDENCE_RECORD_SCHEMA_PATH,
) -> Mapping[str, Any]:
    """Read the published evidence record schema."""
    return _load(path)


def load_draft_curation_proposal_schema(
    path: str = DRAFT_CURATION_PROPOSAL_SCHEMA_PATH,
) -> Mapping[str, Any]:
    """Read the published draft curation proposal schema."""
    return _load(path)


def validate_evidence_build_manifest(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Return every way ``payload`` fails the published manifest schema.

    An empty tuple means it validates. Problems are collected rather than
    raised on the first one, because a manifest under repair should show the
    whole list.
    """
    return validate_against_schema(
        payload, schema if schema is not None
        else load_evidence_build_manifest_schema())


def validate_evidence_record(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Return every way one stored evidence record fails its schema."""
    return validate_against_schema(
        payload, schema if schema is not None
        else load_evidence_record_schema())


def validate_draft_curation_proposal(
    payload: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, ...]:
    """Return every way one draft curation proposal fails its schema."""
    return validate_against_schema(
        payload, schema if schema is not None
        else load_draft_curation_proposal_schema())
