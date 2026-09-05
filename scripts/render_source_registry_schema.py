#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render schemas/scientific-source-registry.schema.json from the vocabularies.

The schema's enumerations are generated from :mod:`pgx.scientific.models` rather
than typed twice. A hand-maintained copy would drift from the code the first
time a member was added, and the drift would show up as a config file that
validates against the schema and fails to load - the worst possible ordering.

Usage::

    python3 scripts/render_source_registry_schema.py          # write it
    python3 scripts/render_source_registry_schema.py --check  # verify
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

from pgx.domain.enums import SourceRole  # noqa: E402
from pgx.scientific.models import (  # noqa: E402
    AcquisitionMode,
    ClaimCategory,
    ConflictMateriality,
    ConflictStatus,
    EvidenceType,
    EvidenceVerificationStatus,
    REUSE_DIMENSIONS,
    ReusePermission,
    ReviewDecision,
    SourcePolicyStatus,
)
from pgx.scientific.policy import SOURCE_REGISTRY_SCHEMA_VERSION  # noqa: E402

SCHEMA_PATH = os.path.join(REPO_ROOT, "schemas",
                           "scientific-source-registry.schema.json")

DIGEST_PATTERN = "^sha256:[0-9a-f]{64}$"
INSTANT_PATTERN = (r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
                   r"(\.[0-9]+)?(Z|\+00:00)$")


def _values(enum_cls) -> list:
    return [member.value for member in enum_cls]


def build_schema() -> dict:
    reuse_properties = {
        dimension.value: {
            "description": "Permission for %s." % dimension.value,
            "$ref": "#/$defs/permission",
        }
        for dimension in REUSE_DIMENSIONS
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": ("https://pgx-platform.invalid/schemas/"
                "scientific-source-registry.schema.json"),
        "title": "PGx scientific source registry",
        "description": (
            "The project's recorded position on every scientific source (WP-05). "
            "This document is a reviewed artefact kept in version control: a "
            "change to a licensing conclusion must appear as a diff with an "
            "author against it. It separates what a source published, this "
            "project's interpretation of it, and the approval decision a named "
            "human made. Absence is never permission: a source with no record "
            "here, or a reuse dimension left unanswered, blocks publication."),
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "sources"],
        "properties": {
            "schema_version": {
                "description": (
                    "Registry shape version. A file declaring another version is "
                    "refused rather than half-understood."),
                "const": SOURCE_REGISTRY_SCHEMA_VERSION,
            },
            "generated_note": {
                "description": "Free-text note about how this file was produced.",
                "type": "string",
            },
            "policy_owner": {
                "description": (
                    "Who maintains this document. Not an approver: approval is "
                    "recorded per source, in a review record."),
                "type": "string",
            },
            "sources": {
                "description": "One policy record per source key.",
                "type": "array",
                "items": {"$ref": "#/$defs/source"},
            },
            "conflicts": {
                "description": (
                    "Recorded disagreements between registered sources. An "
                    "unsettled conflict blocks publication for the sources it "
                    "names, including one whose materiality is undetermined."),
                "type": "array",
                "items": {"$ref": "#/$defs/conflict"},
            },
        },
        "$defs": {
            "digest": {
                "description": "Canonical SHA-256 spelling used across the project.",
                "type": "string",
                "pattern": DIGEST_PATTERN,
            },
            "instant": {
                "description": (
                    "ISO-8601 UTC instant. An offset is required: a naive "
                    "timestamp names no instant and cannot be audited."),
                "type": "string",
                "pattern": INSTANT_PATTERN,
            },
            "permission": {
                "description": (
                    "One answer for one reuse question. UNKNOWN and PROHIBITED "
                    "both block; they differ only in what a reviewer does next."),
                "enum": _values(ReusePermission),
            },
            "evidence": {
                "description": (
                    "A pointer to something the source itself published. The "
                    "artefact's text is deliberately not stored here: a copy in "
                    "this repository would go stale without anybody noticing."),
                "type": "object",
                "additionalProperties": False,
                "required": ["evidence_type"],
                "properties": {
                    "evidence_type": {"enum": _values(EvidenceType)},
                    "official_url": {
                        "description": "The source's own https URL.",
                        "type": ["string", "null"],
                        "pattern": "^https://",
                    },
                    "retrieved_at": {
                        "oneOf": [{"$ref": "#/$defs/instant"}, {"type": "null"}]},
                    "content_hash": {
                        "oneOf": [{"$ref": "#/$defs/digest"}, {"type": "null"}]},
                    "summary": {
                        "description": (
                            "A short factual summary in this project's words. Not "
                            "a copy of the source's terms."),
                        "type": ["string", "null"],
                        "maxLength": 1000,
                    },
                    "verification": {"enum": _values(EvidenceVerificationStatus)},
                    "blocked_reason": {
                        "description": (
                            "Why retrieval failed. Required when verification is "
                            "BLOCKED: an unexplained block is indistinguishable "
                            "from an untried one."),
                        "type": ["string", "null"],
                        "maxLength": 500,
                    },
                },
            },
            "interpretation": {
                "description": (
                    "What this project concluded the source's terms mean. Held "
                    "apart from the source's own wording so a conclusion can be "
                    "re-examined. Not legal advice."),
                "type": "object",
                "additionalProperties": False,
                "required": ["summary", "interpreted_by", "interpreted_at"],
                "properties": {
                    "summary": {"type": "string", "minLength": 1, "maxLength": 2000},
                    "interpreted_by": {"type": "string", "minLength": 1},
                    "interpreted_at": {"$ref": "#/$defs/instant"},
                    "open_questions": {
                        "type": "array", "items": {"type": "string", "minLength": 1}},
                },
            },
            "review": {
                "description": (
                    "The decision a named human made. An approving decision "
                    "requires cited evidence; APPROVE_WITH_RESTRICTIONS requires "
                    "the restrictions to be named."),
                "type": "object",
                "additionalProperties": False,
                "required": ["decision", "reviewer_name", "reviewer_role",
                             "decided_at"],
                "properties": {
                    "decision": {"enum": _values(ReviewDecision)},
                    "reviewer_name": {"type": "string", "minLength": 1},
                    "reviewer_role": {"type": "string", "minLength": 1},
                    "decided_at": {"$ref": "#/$defs/instant"},
                    "evidence_urls": {
                        "type": "array", "items": {"type": "string", "minLength": 1}},
                    "restrictions": {
                        "type": "array", "items": {"type": "string", "minLength": 1}},
                    "notes": {"type": ["string", "null"]},
                    "expires_at": {
                        "oneOf": [{"$ref": "#/$defs/instant"}, {"type": "null"}]},
                },
            },
            "source": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source_key", "display_name", "role", "status"],
                "properties": {
                    "source_key": {
                        "description": (
                            "Stable machine key. Lower-case, dot-separated: "
                            "provider, then the specific interface or product."),
                        "type": "string",
                        "pattern": "^[a-z0-9]+([._-][a-z0-9]+)*$",
                        "maxLength": 120,
                    },
                    "display_name": {"type": "string", "minLength": 1},
                    "role": {"enum": _values(SourceRole)},
                    "status": {"enum": _values(SourcePolicyStatus)},
                    "acquisition_mode": {"enum": _values(AcquisitionMode)},
                    "provider": {"type": ["string", "null"]},
                    "jurisdiction": {
                        "description": (
                            "Where a drug-label source's authority applies. Null "
                            "where the question does not arise."),
                        "type": ["string", "null"],
                    },
                    "version_policy": {"type": ["string", "null"]},
                    "citation_policy": {"type": ["string", "null"]},
                    "license_identifier": {
                        "description": (
                            "The licence the source itself names, verbatim. Never "
                            "guessed from context, never inferred from a similar "
                            "source."),
                        "type": ["string", "null"],
                    },
                    "reuse": {
                        "description": (
                            "One permission per reuse dimension. Any dimension "
                            "omitted reads as UNKNOWN, which blocks."),
                        "type": "object",
                        "additionalProperties": False,
                        "properties": reuse_properties,
                    },
                    "permitted_claim_categories": {
                        "description": (
                            "What the source may be cited for. Must be empty "
                            "unless the record carries an approving review: what "
                            "a source is cleared for is decided at review."),
                        "type": "array",
                        "items": {"enum": _values(ClaimCategory)},
                    },
                    "evidence": {"type": "array", "items": {"$ref": "#/$defs/evidence"}},
                    "interpretation": {
                        "oneOf": [{"$ref": "#/$defs/interpretation"}, {"type": "null"}]},
                    "review": {
                        "oneOf": [{"$ref": "#/$defs/review"}, {"type": "null"}]},
                    "legacy_aliases": {
                        "description": (
                            "Exact strings the frozen legacy files use for this "
                            "source. Recorded one spelling at a time so that "
                            "matching legacy data to a policy is a reviewed "
                            "decision, not a fuzzy match."),
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                    },
                    "blocking_reasons": {
                        "description": (
                            "Plain statements of what is outstanding. Written for "
                            "the reviewer who picks this up next."),
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                    },
                    "notes": {"type": ["string", "null"]},
                    "active": {"type": "boolean"},
                },
            },
            "conflict": {
                "type": "object",
                "additionalProperties": False,
                "required": ["conflict_key", "subject", "source_keys", "description"],
                "properties": {
                    "conflict_key": {"type": "string", "minLength": 1},
                    "subject": {"type": "string", "minLength": 1},
                    "source_keys": {
                        "type": "array",
                        "minItems": 2,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "description": {"type": "string", "minLength": 1},
                    "materiality": {"enum": _values(ConflictMateriality)},
                    "status": {"enum": _values(ConflictStatus)},
                    "detected_at": {
                        "oneOf": [{"$ref": "#/$defs/instant"}, {"type": "null"}]},
                    "resolution": {
                        "description": (
                            "Required once the status is RESOLVED or "
                            "ACCEPTED_VARIANCE. A conflict is settled by a named "
                            "human, not by a status field."),
                        "oneOf": [
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["decision_summary", "rationale",
                                             "decided_by", "decided_at"],
                                "properties": {
                                    "decision_summary": {"type": "string",
                                                         "minLength": 1},
                                    "rationale": {"type": "string", "minLength": 1},
                                    "decided_by": {"type": "string", "minLength": 1},
                                    "decided_at": {"$ref": "#/$defs/instant"},
                                    "preferred_source_key": {
                                        "type": ["string", "null"]},
                                },
                            },
                            {"type": "null"},
                        ],
                    },
                },
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
                "schemas/scientific-source-registry.schema.json is stale; "
                "re-run scripts/render_source_registry_schema.py\n")
            return 1
        sys.stdout.write("schema is current\n")
        return 0
    with io.open(SCHEMA_PATH, "w", encoding="utf-8") as handle:
        handle.write(text)
    sys.stdout.write("wrote %s\n" % SCHEMA_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
