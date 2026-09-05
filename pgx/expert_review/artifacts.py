# -*- coding: utf-8 -*-
"""The committed WP-22 artifacts (WP-22).

Four documents plus eleven schemas, all deterministic functions of this
repository, so WP-19's reproducibility checker can build them twice and
compare bytes.

Two of the four deserve a note.

``wp22-protocol-manifest.json`` records ``approved: false`` with an empty
signatory list. That is not a stub awaiting a fixture: :func:`load_protocol`
has no code path that reads signatories from disk, so the only way this file
can ever say ``true`` is for four named people to sign the exact document
digest and for that arrival to be a visible, reviewed change.

``wp22-public-summary.json`` is the aggregate that may be shown outside the
review system, and every summary field in it is ``null`` rather than zero.
Zero completed reviews does not produce a 0% agreement rate; it produces no
rate at all. The published schema enforces that, so the misleading document
cannot be written even by a later caller who wanted to.
"""

from __future__ import annotations

import io
import os
from typing import Any, Dict, Mapping, Optional

from pgx.expert_review.gate_status import build_wp22_gate_status
from pgx.expert_review.protocol import PROTOCOL_VERSION, load_protocol
from pgx.expert_review.vocabulary import (CORRECTION_KINDS, DECISION_VALUES,
                                          INVALIDATION_REASONS,
                                          LIKERT_DIMENSIONS, LIKERT_MAXIMUM,
                                          LIKERT_MINIMUM, PERMITTED_STAGES,
                                          RATIONALE_CODES,
                                          REVIEW_ERROR_CODES, TERMINAL_STATES,
                                          TRANSITIONS, VOCABULARY_VERSION,
                                          AuditAction, ReviewState)

__all__ = [
    "DETERMINISTIC_ARTIFACT_PATHS",
    "GATE_STATUS_PATH",
    "PROTOCOL_MANIFEST_PATH",
    "PUBLIC_SUMMARY_PATH",
    "PUBLIC_SUMMARY_VERSION",
    "WORKFLOW_PATH",
    "WORKFLOW_VERSION",
    "build_artifacts",
    "build_protocol_manifest",
    "build_public_summary",
    "build_review_workflow",
    "write_document",
]

PROTOCOL_MANIFEST_PATH = "data/expert-review/wp22-protocol-manifest.json"
WORKFLOW_PATH = "data/expert-review/wp22-review-workflow.json"
PUBLIC_SUMMARY_PATH = "data/expert-review/wp22-public-summary.json"
GATE_STATUS_PATH = "data/expert-review/wp22-real-gate-status.json"

WORKFLOW_VERSION = "pgx-wp22-review-workflow/1"
PUBLIC_SUMMARY_VERSION = "pgx-wp22-public-review-summary/1"

#: Everything a reproducibility check may rebuild and compare. The gate status
#: is excluded for the same reason WP-19 and WP-21 exclude their own: it reads
#: the environment, so two builds on different machines legitimately differ.
DETERMINISTIC_ARTIFACT_PATHS = (PROTOCOL_MANIFEST_PATH, WORKFLOW_PATH,
                                PUBLIC_SUMMARY_PATH)


def _render(document: Mapping[str, Any], root: str) -> str:
    from pgx.verification.scrub import safe_render
    return safe_render(document, root)


def build_protocol_manifest(root: str) -> Dict[str, Any]:
    """The protocol as this repository holds it: documented, not approved."""
    protocol = load_protocol(root)
    document = dict(protocol.to_json())
    document["generated_note"] = (
        "The protocol document exists and has not been approved. Approval "
        "requires four named people - a product technical owner, a "
        "scientific advisor, a risk-management owner and an independent "
        "reviewer - each signing the exact document digest above. No code "
        "path in this repository can supply them, and the TEST-ONLY approved "
        "protocol used by the workflow tests is constructed inside the test "
        "suite and never read from disk.")
    document["not_clinical_validation"] = (
        "This manifest describes a document and its approval state. It is "
        "not clinical validation, scientific validation or evidence of "
        "either.")
    return document


def build_review_workflow(root: str = None) -> Dict[str, Any]:
    """The state machine, published so the ordering is auditable.

    Exported rather than described, because the ordering is the protocol: an
    expectation before any reveal, a reveal before any completion, and no
    transition out of a terminal state. A reader can check the transition map
    here against the protocol document without reading the implementation.
    """
    return {
        "schema_version": WORKFLOW_VERSION,
        "vocabulary_version": VOCABULARY_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "states": [item.value for item in ReviewState],
        "initial_state": ReviewState.ASSIGNED.value,
        "transitions": {name: sorted(targets)
                        for name, targets in sorted(TRANSITIONS.items())},
        "terminal_states": sorted(TERMINAL_STATES),
        "permitted_permit_stages": list(PERMITTED_STAGES),
        "decisions": list(DECISION_VALUES),
        "rationale_codes": list(RATIONALE_CODES),
        "correction_kinds": list(CORRECTION_KINDS),
        "invalidation_reasons": list(INVALIDATION_REASONS),
        "audit_actions": [item.value for item in AuditAction],
        "likert_dimensions": list(LIKERT_DIMENSIONS),
        "likert_minimum": LIKERT_MINIMUM,
        "likert_maximum": LIKERT_MAXIMUM,
        "error_codes": dict(sorted(REVIEW_ERROR_CODES.items())),
        "error_code_count": len(REVIEW_ERROR_CODES),
        "ordering_note": (
            "The order is enforced by referential integrity rather than by "
            "rules a caller could skip. A reveal row must name an "
            "expectation revision that exists; a completion row must name a "
            "reveal that exists. There is no identifier to supply for a "
            "record that was never written, so the out-of-order operation is "
            "not refused - it is unexpressible."),
        "blinding_note": (
            "Before a reveal record exists there is no field in the view, "
            "the page model or the API response in which a system result "
            "could sit, including a hidden one. The result port is not "
            "consulted until the reveal transition succeeds."),
        "single_refusal_note": (
            "An unknown case, a case that is not expert-holdout and a case "
            "assigned to another reviewer all return "
            "EXPERT_REVIEW_NOT_ASSIGNED with empty details. Distinguishing "
            "them would enumerate the holdout set."),
        "not_clinical_validation": (
            "This document describes a workflow. It is not clinical "
            "validation, scientific validation or evidence of either."),
    }


def build_public_summary(root: str, *,
                         review_store: Optional[Any] = None) -> Dict[str, Any]:
    """The aggregate that may leave the review system. Currently all null.

    Note what is *not* here: no call to any aggregation over decisions. There
    are no completed reviews, and running a distribution over an empty list
    would produce a document of zeros that looks almost identical while
    meaning something different - "we summarised and everyone disagreed"
    rather than "nobody reviewed anything". The distinction is the point, so
    the empty case returns nulls by a separate path.
    """
    gate = build_wp22_gate_status(root, review_store=review_store)
    completed = gate["completed_review_count"] or 0
    reviewers = gate["named_reviewer_count"]
    return {
        "schema_version": PUBLIC_SUMMARY_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_approved": gate["protocol_approved"],
        "protocol_status": gate["protocol_status"],
        "completed_review_count": completed,
        "reviewer_count": reviewers,
        "expert_holdout_case_count": gate["expert_holdout_case_count"],
        "invalidated_review_count": None,
        # Null, not an empty distribution and not zeros. A distribution over
        # an empty set is not a distribution.
        "agreement_distribution": None,
        "likert_summaries": None,
        "free_text_included": False,
        "free_text_note": (
            "A reviewer's note is never aggregated, summarised or published. "
            "No language model reads, rewrites or scores one; a note leaves "
            "the review system only as the reviewer typed it, to a human "
            "auditor."),
        "reviewer_identities_included": False,
        "reviewer_identity_note": (
            "No reviewer name, actor string or affiliation appears in this "
            "summary, whatever the completed count becomes."),
        "generated_note": (
            "No expert review has been completed. Every summary field is "
            "null rather than zero, because a rate over zero reviews is not "
            "a low rate - it is no rate. The published schema refuses a "
            "document that pairs a zero count with a distribution."),
        "expert_review_performed": False,
        "clinical_validation_performed": False,
        "scientific_validation_performed": False,
        "not_clinical_validation": (
            "This document reports how many reviews were completed and, "
            "currently, that none were. A completed review would be one "
            "expert's opinion about one case under one release; it would not "
            "be clinical validation, and no number of them published here "
            "becomes one."),
    }


def build_artifacts(root: str) -> Dict[str, str]:
    """Every deterministic artifact, rendered. WP-19's generator signature."""
    from pgx.application.expert_review_schema import build_schemas

    documents: Dict[str, str] = {
        PROTOCOL_MANIFEST_PATH: _render(build_protocol_manifest(root), root),
        WORKFLOW_PATH: _render(build_review_workflow(root), root),
        PUBLIC_SUMMARY_PATH: _render(build_public_summary(root), root),
    }
    for relative, schema in build_schemas().items():
        documents[relative] = _render(schema, root)
    return documents


def write_document(root: str, relative: str,
                   document: Mapping[str, Any]) -> str:
    rendered = _render(document, root)
    path = os.path.join(root, *relative.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(rendered)
    return rendered
