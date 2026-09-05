#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Write the WP-09 protocol artifacts from the code that defines them.

Generated rather than hand-written, so a vocabulary added in
:mod:`pgx.curation.vocabulary` cannot drift from the published document that
claims to list it. Re-running this over the same inputs rewrites the same
bytes; the validator checks that the files on disk still match.

Operational timestamps are deliberately absent from every generated file. A
``generated_at`` would change the bytes on every run, which would make "did
this artifact change" unanswerable and the approval hash unverifiable.
"""

from __future__ import annotations

import io
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from pgx.curation.exercises import (  # noqa: E402
    AdjudicationTemplate, build_exercise_packet, response_template,
)
from pgx.curation.fields import field_dictionary_json  # noqa: E402
from pgx.curation.legacy_review import build_review_inventory  # noqa: E402
from pgx.curation.protocol import build_protocol_document  # noqa: E402

EVIDENCE_BUILD = os.path.join(REPO_ROOT, "data", "evidence",
                              "PGX-DATA-20260830-900")
PROPOSALS = os.path.join(REPO_ROOT, "data", "migration", "wp08",
                         "draft-curation-proposals.ndjson")
CONFIG_DIR = os.path.join(REPO_ROOT, "config", "curation")
DATA_DIR = os.path.join(REPO_ROOT, "data", "curation", "protocol-v1")
EXERCISE_DIR = os.path.join(DATA_DIR, "exercises")


def _write_json(path: str, payload) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True,
                                ensure_ascii=False) + "\n")


def _write_ndjson(path: str, rows) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True,
                                    ensure_ascii=False) + "\n")


def main() -> int:
    document = build_protocol_document()
    _write_json(os.path.join(CONFIG_DIR, "protocol-v1.json"),
                document.to_json())
    _write_json(os.path.join(CONFIG_DIR, "field-dictionary-v1.json"),
                field_dictionary_json())

    packet = build_exercise_packet(EVIDENCE_BUILD, PROPOSALS)
    selected = sorted({proposal_id for case in packet.cases
                       for proposal_id in case.linked_legacy_proposal_ids})
    inventory = build_review_inventory(PROPOSALS, selected_proposal_ids=selected)
    _write_json(os.path.join(DATA_DIR, "legacy-hint-review-inventory.json"),
                inventory.to_json())

    manifest = packet.to_json()
    cases = manifest.pop("cases")
    _write_json(os.path.join(EXERCISE_DIR, "manifest.json"), manifest)
    _write_ndjson(os.path.join(EXERCISE_DIR, "cases.ndjson"), cases)
    for label in ("a", "b"):
        _write_json(os.path.join(EXERCISE_DIR, "curator-%s.template.json" % label),
                    response_template(packet, label.upper()))

    # A pending comparison, not an empty one. It records why no comparison
    # exists rather than presenting a comparison of nothing.
    _write_json(os.path.join(EXERCISE_DIR, "comparison.pending.json"), {
        "comparison_version": "pgx-inter-curator-comparison/1",
        "exercise_id": packet.exercise_id,
        "status": "PENDING_TWO_COMPLETED_RESPONSES",
        "curator_a": None,
        "curator_b": None,
        "cases": None,
        "summary": None,
        "blocked_by": [
            "No named curator has completed curator-a.template.json.",
            "No named curator has completed curator-b.template.json.",
        ],
        "note": ("A comparison requires two independently completed responses "
                 "from two different named people. Until then there is "
                 "nothing to compare, and a file showing empty agreement "
                 "would misrepresent that as a result."),
    })

    adjudication = AdjudicationTemplate(
        exercise_id=packet.exercise_id,
        disputed_case_ids=(),
        preserved_responses=(
            {"curator_label": "A", "curator_name": None, "completed": False},
            {"curator_label": "B", "curator_name": None, "completed": False},
        ))
    _write_json(os.path.join(EXERCISE_DIR, "adjudication.template.json"),
                adjudication.to_json())

    _write_json(os.path.join(EXERCISE_DIR, "status.json"), {
        "exercise_id": packet.exercise_id,
        "exercise_version": packet.exercise_version,
        "status": packet.status,
        "case_count": len(packet.cases),
        "content_hash": packet.content_hash(),
        "evidence_build_key": packet.evidence_build_key,
        "evidence_build_content_hash": packet.evidence_build_content_hash,
        "curator_a": {"assigned": False, "name": None, "completed": False},
        "curator_b": {"assigned": False, "name": None, "completed": False},
        "adjudication": {"required": None, "adjudicator": None,
                         "decided": False},
        "blocked_by": [
            "Two named scientific curators have not been assigned.",
            "Neither response has been completed.",
            "The protocol itself is AWAITING_EXPERT_REVIEW.",
        ],
        "note": ("This exercise has not been run. Nothing in this repository "
                 "can move it out of AWAITING_HUMAN_CURATORS, because doing "
                 "so would assert that two scientists reviewed evidence they "
                 "have not seen."),
    })

    sys.stdout.write(
        "protocol      %s  %s\n"
        "requirements  %d\n"
        "fields        %d\n"
        "proposals     %d (selected for exercise: %d)\n"
        "exercise      %d cases, %s\n"
        % (document.protocol_version, document.content_hash(),
           len(document.requirements), len(field_dictionary_json()["fields"]),
           inventory.counts()["proposal_count"], len(selected),
           len(packet.cases), packet.status))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
