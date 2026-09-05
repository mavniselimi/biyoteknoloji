#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render schemas/raw-snapshot-manifest.schema.json from the WP-06 vocabularies.

The enumerations and the required-key list are generated from
:mod:`pgx.ingestion.snapshots` rather than typed twice. A hand-maintained copy
would drift the first time a member was added, and the drift would surface as a
manifest that validates against the schema and then fails to load - the worst
possible ordering.

Usage::

    python3 scripts/render_snapshot_manifest_schema.py          # write it
    python3 scripts/render_snapshot_manifest_schema.py --check  # verify
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from pgx.ingestion.snapshots import (  # noqa: E402
    SNAPSHOT_MANIFEST_VERSION,
    ArtifactKind,
    SnapshotKind,
    SnapshotState,
)

SCHEMA_PATH = os.path.join(REPO_ROOT, "schemas", "raw-snapshot-manifest.schema.json")

DIGEST_PATTERN = "^sha256:[0-9a-f]{64}$"
DATASET_ID_PATTERN = "^PGX-DATA-[0-9]{8}-[0-9]{3}$"
INSTANT_PATTERN = (r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
                   r"(\.[0-9]+)?(Z|\+00:00)$")
#: Relative, normalised, forward-slash paths with no traversal and no leading
#: separator. Enforced here as well as in code so a manifest that a validator
#: accepted can never carry a path the loader would refuse.
RELATIVE_PATH_PATTERN = r"^(?!/)(?!.*(^|/)\.\.?(/|$))[^\\\x00]+$"


def _values(enum_cls) -> list:
    return [member.value for member in enum_cls]


def build_schema() -> dict:
    artifact = {
        "type": "object",
        "additionalProperties": False,
        "required": ["relative_path", "artifact_kind", "byte_length", "sha256"],
        "properties": {
            "relative_path": {
                "description": ("Normalised path relative to the snapshot root. "
                                "Never absolute, never containing '..'."),
                "type": "string",
                "pattern": RELATIVE_PATH_PATTERN,
                "maxLength": 1024,
            },
            "artifact_kind": {"enum": _values(ArtifactKind)},
            "byte_length": {"type": "integer", "minimum": 0},
            "sha256": {"$ref": "#/$defs/digest"},
            "request_key": {
                "description": "The WP-04 request key this body answered.",
                "anyOf": [{"$ref": "#/$defs/digest"}, {"type": "null"}],
            },
            "endpoint_id": {"type": ["string", "null"]},
            "page_number": {"type": ["integer", "null"], "minimum": 0},
            "cursor": {"type": ["string", "null"]},
            "content_type": {"type": ["string", "null"]},
            "retrieval_ref": {
                "description": "Cache blob reference the bytes were copied from.",
                "type": ["string", "null"],
            },
            "source_relative_path": {
                "description": ("For a legacy import, the file's path inside the "
                                "original directory."),
                "type": ["string", "null"],
                "maxLength": 1024,
            },
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": ("https://pgx-platform.invalid/schemas/"
                "raw-snapshot-manifest.schema.json"),
        "title": "PGx immutable raw snapshot manifest",
        "description": (
            "The machine-readable account of one sealed raw snapshot (WP-06). "
            "It records exactly which source bytes were captured, their "
            "individual SHA-256 digests, the aggregate content hash and the "
            "manifest's own canonical digest. It carries no absolute path. A "
            "snapshot is raw source bytes: it is not canonical data, not "
            "curated evidence, not an interpretation, and not a scientifically "
            "approved dataset."),
        "type": "object",
        "additionalProperties": False,
        "required": [
            "snapshot_manifest_version", "dataset_public_id", "source_key",
            "snapshot_kind", "snapshot_state", "snapshot_content_hash",
            "manifest_hash", "created_at", "artifact_count",
            "total_byte_count", "artifacts", "complete", "publication_eligible",
            "scope_note",
        ],
        "properties": {
            "snapshot_manifest_version": {
                "description": ("Manifest shape version, part of the hashed "
                                "payload so a shape change cannot collide with "
                                "an older snapshot's identity."),
                "const": SNAPSHOT_MANIFEST_VERSION,
            },
            "dataset_public_id": {
                "description": "Explicit operator-assigned dataset identity.",
                "type": "string",
                "pattern": DATASET_ID_PATTERN,
            },
            "source_key": {"type": "string", "minLength": 1, "maxLength": 200},
            "source_registry_id": {"type": ["string", "null"]},
            "source_policy_status": {
                "description": ("The WP-05 policy status in force when the "
                                "snapshot was sealed."),
                "type": ["string", "null"],
            },
            "source_policy_content_hash": {
                "anyOf": [{"$ref": "#/$defs/digest"}, {"type": "null"}]},
            "snapshot_kind": {"enum": _values(SnapshotKind)},
            "snapshot_state": {"enum": _values(SnapshotState)},
            "acquisition_run_id": {
                "description": ("The WP-04 run this came from. Null for a legacy "
                                "import, where no such run exists and inventing "
                                "one would be a fabrication."),
                "type": ["string", "null"],
            },
            "acquisition_status": {"type": ["string", "null"]},
            "acquisition_content_hash": {
                "anyOf": [{"$ref": "#/$defs/digest"}, {"type": "null"}]},
            "acquisition_manifest_hash": {
                "anyOf": [{"$ref": "#/$defs/digest"}, {"type": "null"}]},
            "snapshot_content_hash": {
                "description": ("Digest over the sorted artifact content "
                                "identities. Excludes creation time, staging "
                                "path, cache hit/miss state, retry timing and "
                                "the dataset ID, so a cache replay of the same "
                                "bytes matches."),
                "$ref": "#/$defs/digest",
            },
            "manifest_hash": {
                "description": ("Canonical digest of this document with the "
                                "manifest_hash field removed. Includes the "
                                "dataset ID and creation instant, so two "
                                "dataset IDs over identical bytes share a "
                                "content hash and differ here."),
                "$ref": "#/$defs/digest",
            },
            "created_at": {"$ref": "#/$defs/instant"},
            "artifact_count": {"type": "integer", "minimum": 0},
            "total_byte_count": {"type": "integer", "minimum": 0},
            "artifacts": {"type": "array", "items": artifact},
            "request_log": {
                "description": ("Descriptor for requests.ndjson. Null only when "
                                "the snapshot records no request log at all."),
                "anyOf": [artifact, {"type": "null"}],
            },
            "complete": {
                "description": ("Whether every required endpoint completed, "
                                "recomputed from the retrieval records. Always "
                                "false for a legacy import."),
                "type": "boolean",
            },
            "completeness_basis": {
                "description": "How the completeness answer was derived.",
                "type": "string",
            },
            "warnings": {"type": "array", "items": {"type": "string"}},
            "limitations": {
                "description": ("What this snapshot cannot answer. Present and "
                                "non-empty on every legacy import."),
                "type": "array",
                "items": {"type": "string"},
            },
            "legacy_origin": {
                "description": "Where a legacy import came from, factually.",
                "type": ["object", "null"],
            },
            "publication_eligible": {
                "description": ("Always false for a sealed raw snapshot. Sealing "
                                "a directory is a filesystem act; publication "
                                "eligibility is a WP-05 and WP-07 decision."),
                "type": "boolean",
            },
            "publication_gate": {
                "description": ("The complete WP-05 gate result recorded at seal "
                                "time, whatever it said."),
                "type": ["object", "null"],
            },
            "scope_note": {"type": "string", "minLength": 1},
        },
        "$defs": {
            "digest": {
                "description": "Canonical lowercase SHA-256 spelling.",
                "type": "string",
                "pattern": DIGEST_PATTERN,
            },
            "instant": {
                "description": ("ISO-8601 UTC instant. An offset is required: a "
                                "naive timestamp names no instant."),
                "type": "string",
                "pattern": INSTANT_PATTERN,
            },
        },
    }


def render() -> str:
    return json.dumps(build_schema(), indent=2, ensure_ascii=False) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if the checked-in schema is stale")
    args = parser.parse_args(argv)
    text = render()
    if args.check:
        if not os.path.isfile(SCHEMA_PATH):
            sys.stderr.write("schema file is missing: %s\n" % SCHEMA_PATH)
            return 1
        with io.open(SCHEMA_PATH, encoding="utf-8") as handle:
            current = handle.read()
        if current != text:
            sys.stderr.write(
                "schemas/raw-snapshot-manifest.schema.json is stale; re-run "
                "scripts/render_snapshot_manifest_schema.py\n")
            return 1
        sys.stdout.write("schema is current\n")
        return 0
    with io.open(SCHEMA_PATH, "w", encoding="utf-8") as handle:
        handle.write(text)
    sys.stdout.write("wrote %s\n" % SCHEMA_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
