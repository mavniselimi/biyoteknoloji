#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seal Wave 3's candidate evidence set (WP-C05, candidate track).

**Why this is not a raw snapshot.** ``pgx.ingestion.snapshots`` seals raw
source bytes, and its ``SnapshotKind`` has three members: ``ACQUISITION`` and
``CACHE_REPLAY`` both assert a WP-04 acquisition run with full retrieval
metadata behind the bytes, and ``LEGACY_IMPORT`` asserts the files predate the
adapter and came from the frozen legacy probe scripts. Wave 3's retrieval is
none of those. It produced rendered page text through a browser agent, with no
HTTP response bodies preserved and no acquisition run to cite, and neither
execution environment available to this project can reach the publisher to
perform one.

Labelling the transcription ``ACQUISITION`` would claim retrieval metadata that
does not exist; labelling it ``LEGACY_IMPORT`` would claim an origin that is
false. So this script does not write a snapshot at all. It seals what this
project actually has - its own transcription - under its own identity, with the
same integrity discipline (per-file digests, a content hash over the set, a
manifest that states its own limits) and none of the claims.

The output is deliberately not placed under ``data/raw/`` or
``data/canonical/``. A directory in either of those trees is read by tooling
that is entitled to assume things this content cannot support.
**No build instant is recorded here.** Following the convention
``ComputableRuleDefinition.semantic_content`` already sets in this repository -
who wrote something and when are recorded, audited, and not part of what was
claimed - the seal carries no wall-clock field. The consequence is that a
rebuild is byte-identical, so "is the committed artifact the one this code
produces" is a question a test can answer. When the seal happened is git's to
record.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pgx.closure.authority import CandidateAuthorityState  # noqa: E402
from pgx.closure.candidate_curation import (CURATIONS, JOINT_CHECKS,  # noqa: E402
                                            joint_consistency_failures)
from pgx.closure.candidate_ruleset import (REFUSALS,  # noqa: E402
                                           build_candidate_ruleset)
from pgx.closure.source_grounding import (INTERFACES, LICENCE_BASES,  # noqa: E402
                                          RETRIEVAL_CLASSIFICATION,
                                          RETRIEVAL_LIMITS, RETRIEVALS,
                                          extraction_digest)
from pgx.closure.source_rows import (AMITRIPTYLINE_JOINT_ROWS, ROWS,  # noqa: E402
                                     unrepresentable_rows)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_ROOT = os.path.join(REPO, "data", "closure", "wave-03-candidate-evidence")

EVIDENCE_SET_ID = "PGX-CANDIDATE-EVIDENCE-WAVE03"

#: Stated on the manifest, so that a reader who opens only the manifest still
#: learns the things a reader who opens only the data would miss.
LIMITATIONS = RETRIEVAL_LIMITS + (
    "this is not a WP-04 raw snapshot and must not be read as one: no "
    "acquisition run backs it and no SnapshotKind describes it",
    "this is not a canonical dataset: it has not been through WP-06 "
    "normalization, identity allocation or duplicate resolution",
    "the interpretation of each recommendation into an attention level is "
    "this project's own and has been reviewed by nobody outside it",
)


def _canonical(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"


def _write(relative: str, payload: object) -> dict:
    path = os.path.join(OUTPUT_ROOT, relative)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = _canonical(payload)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    raw = text.encode("utf-8")
    return {
        "relative_path": relative,
        "byte_length": len(raw),
        "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
    }


def main() -> int:
    failures = joint_consistency_failures()
    if failures:
        sys.stderr.write(
            "refusing to seal: %d amitriptyline combination(s) would be "
            "understated\n" % len(failures))
        return 2

    ruleset = build_candidate_ruleset()
    os.makedirs(OUTPUT_ROOT, exist_ok=True)

    artifacts = [
        _write("licence-bases.json",
               [item.to_json() for item in LICENCE_BASES]),
        _write("interfaces.json",
               [item.to_json() for item in INTERFACES]),
        _write("retrievals.json",
               [item.to_json() for item in RETRIEVALS]),
        _write("source-rows.json", [row.to_json() for row in ROWS]),
        _write("amitriptyline-joint-table.json",
               [cell.to_json() for cell in AMITRIPTYLINE_JOINT_ROWS]),
        _write("unrepresentable-rows.json",
               [row.to_json() for row in unrepresentable_rows()]),
        _write("curations.json", [item.to_json() for item in CURATIONS]),
        _write("joint-consistency-checks.json",
               [check.to_json() for check in JOINT_CHECKS]),
        _write("refusals.json", [item.to_json() for item in REFUSALS]),
        _write("candidate-ruleset.json", ruleset.to_json()),
    ]

    content_hash = extraction_digest(
        [{"relative_path": item["relative_path"], "sha256": item["sha256"]}
         for item in artifacts])

    manifest = {
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "authority_state":
            CandidateAuthorityState.SOURCE_GROUNDED_INTERNAL_DECISION.value,
        "candidate_ruleset_content_hash": ruleset.content_hash(),
        "content_hash": content_hash,
        "curation_count": len(CURATIONS),
        "evidence_set_id": EVIDENCE_SET_ID,
        "evidence_set_version": "pgx-wave03-candidate-evidence/1",
        "is_canonical_dataset": False,
        "is_raw_snapshot": False,
        "joint_check_count": len(JOINT_CHECKS),
        "joint_understatement_count": 0,
        "limitations": list(LIMITATIONS),
        "refusal_count": len(REFUSALS),
        "retrieval_classification": RETRIEVAL_CLASSIFICATION,
        "retrieval_count": len(RETRIEVALS),
        "review_state":
            CandidateAuthorityState.PENDING_EXTERNAL_EXPERT_REVIEW.value,
        "rule_count": len(ruleset.rules),
        "source_row_count": len(ROWS),
        "total_byte_count": sum(item["byte_length"] for item in artifacts),
        "unrepresentable_row_count": len(unrepresentable_rows()),
    }
    manifest_entry = _write("manifest.json", manifest)

    lines = ["%s  %s" % (item["sha256"].split(":", 1)[1],
                         item["relative_path"])
             for item in artifacts + [manifest_entry]]
    with io.open(os.path.join(OUTPUT_ROOT, "checksums.sha256"), "w",
                 encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(sorted(lines)) + "\n")

    sys.stdout.write(
        "sealed %s: %d artifacts, %d bytes\ncontent hash: %s\n"
        "ruleset hash: %s\n"
        "not a raw snapshot, not a canonical dataset, reviewed by nobody\n"
        % (EVIDENCE_SET_ID, len(artifacts), manifest["total_byte_count"],
           content_hash, ruleset.content_hash()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
