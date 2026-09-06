#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Assemble the Wave 3 execution manifest from the artifacts themselves.

Every number here is read from a file on disk or computed from the code that
produced it. Nothing is typed in from the report, and the report cites this
manifest rather than the other way round, so a figure that drifts shows up as a
disagreement instead of being copied forward.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pgx.closure.authority import (BRIDGE_ENTRIES,  # noqa: E402
                                   PERMITTED_PRE_EXPERT_STATES,
                                   PROHIBITED_AUTHORITY_TERMS, bridge_table)
from pgx.closure.candidate_curation import (CURATIONS, JOINT_CHECKS,  # noqa: E402
                                            joint_consistency_failures)
from pgx.closure.candidate_ruleset import (REFUSALS,  # noqa: E402
                                           build_candidate_ruleset)
from pgx.closure.source_grounding import (RETRIEVAL_CLASSIFICATION,  # noqa: E402
                                          RETRIEVAL_LIMITS, RETRIEVALS)
from pgx.closure.source_rows import ROWS, unrepresentable_rows  # noqa: E402
from pgx.closure.wave03_residuals import (RESIDUALS,  # noqa: E402
                                          blocked_residuals,
                                          caused_by_this_wave)
from pgx.normalization.quality_decision import (LEDGER_PATH,  # noqa: E402
                                                load_ledger)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(REPO, "data", "closure", "wave-03-execution-manifest.json")
EVIDENCE = os.path.join(REPO, "data", "closure", "wave-03-candidate-evidence")
RELEASE = os.path.join(REPO, "data", "closure", "wave-03-candidate-release")


def _digest(path: str) -> str:
    with io.open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def _read(path: str) -> dict:
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    ruleset = build_candidate_ruleset()
    evidence_manifest = _read(os.path.join(EVIDENCE, "manifest.json"))
    release_manifest = _read(os.path.join(RELEASE, "manifest.json"))
    ledger = load_ledger(os.path.join(REPO, LEDGER_PATH))

    tracked = []
    for root in (EVIDENCE, RELEASE):
        for base, dirs, names in os.walk(root):
            dirs.sort()
            for name in sorted(names):
                full = os.path.join(base, name)
                tracked.append({
                    "path": os.path.relpath(full, REPO).replace(os.sep, "/"),
                    "sha256": _digest(full),
                    "byte_length": os.path.getsize(full),
                })
    for relative in ("data/canonical/dataset-quality-decisions.ndjson",):
        full = os.path.join(REPO, relative)
        tracked.append({"path": relative, "sha256": _digest(full),
                        "byte_length": os.path.getsize(full)})

    verdicts = {}
    for entry in BRIDGE_ENTRIES:
        verdicts[entry.verdict.value] = verdicts.get(entry.verdict.value, 0) + 1

    manifest = {
        "authority_bridge": {
            "entries": bridge_table(),
            "permitted_pre_expert_states": list(PERMITTED_PRE_EXPERT_STATES),
            "prohibited_terms_checked": len(PROHIBITED_AUTHORITY_TERMS),
            "row_count": len(BRIDGE_ENTRIES),
            "verdict_counts": verdicts,
        },
        "candidate_ruleset": {
            "content_hash": ruleset.content_hash(),
            "coverage": {key: list(value)
                         for key, value in ruleset.coverage().items()},
            "permitted_channels": list(ruleset.permitted_channels),
            "refusal_count": len(REFUSALS),
            "rule_count": len(ruleset.rules),
        },
        "curation": {
            "curation_count": len(CURATIONS),
            "joint_check_count": len(JOINT_CHECKS),
            "joint_understatement_count": len(joint_consistency_failures()),
        },
        "dataset_quality_decisions": [
            {"dataset_public_id": row.dataset_public_id,
             "decision": row.decision.value,
             "reviewer_name": row.reviewer_name,
             "reviewer_role": row.reviewer_role}
            for row in ledger],
        "evidence_set": {
            "content_hash": evidence_manifest["content_hash"],
            "evidence_set_id": evidence_manifest["evidence_set_id"],
            "is_canonical_dataset": evidence_manifest["is_canonical_dataset"],
            "is_raw_snapshot": evidence_manifest["is_raw_snapshot"],
        },
        "files": tracked,
        "manifest_version": "pgx-closure-wave03-manifest/1",
        "operational_residuals": {
            "blocked_count": len(blocked_residuals()),
            "caused_by_this_wave_count": len(caused_by_this_wave()),
            "entries": [item.to_json() for item in RESIDUALS],
            "total_count": len(RESIDUALS),
        },
        "release": {
            "is_governed_release": release_manifest["is_governed_release"],
            "release_key": release_manifest["release_key"],
            "review_state": release_manifest["review_state"],
            "summary": release_manifest["summary"],
        },
        "source_grounding": {
            "retrieval_classification": RETRIEVAL_CLASSIFICATION,
            "retrieval_count": len(RETRIEVALS),
            "retrieval_limits": list(RETRIEVAL_LIMITS),
            "row_count": len(ROWS),
            "unrepresentable_row_count": len(unrepresentable_rows()),
        },
    }

    text = json.dumps(manifest, indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"
    with io.open(OUTPUT, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    sys.stdout.write(
        "wave-03-execution-manifest.json: %d files, %d bridge rows, "
        "%d rules, %d refusals, %d residuals (%d blocked)\n"
        % (len(tracked), len(BRIDGE_ENTRIES), len(ruleset.rules),
           len(REFUSALS), len(RESIDUALS), len(blocked_residuals())))
    sys.stdout.write("manifest sha256: %s\n" % _digest(OUTPUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
