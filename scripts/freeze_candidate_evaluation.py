#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freeze the exact candidate version demonstrated in WP-C14 (Wave 5, B1).

One record, written once, naming every artifact the external expert will be
asked to judge and the hash of each. Its purpose is narrow and important: after
this file exists, no later change to the repository can be mistaken for the
version that was sent out. A reviewer's comment about "the clopidogrel rule"
means the rule whose content hash is written here, not whatever that rule
becomes afterwards.

It computes nothing about quality and asserts nothing about approval. Every
field is either a hash of a file on disk, an identifier read from one, or the
commit the working tree is at.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(REPO, "data", "closure",
                      "wave-05-frozen-candidate-version.json")

#: Every artifact the evaluation package rests on. Each entry is a path
#: relative to the repository root; a directory is hashed file by file, sorted,
#: so the record is stable and a single changed byte anywhere is visible.
FROZEN_PATHS = (
    "data/releases/active-candidate-release.json",
    "data/releases/PGX-CANDIDATE-REL-20260906-001",
    "data/candidate-rulesets/PGX-CANDIDATE-RULESET-WAVE03B",
    "data/canonical/PGX-DATA-20260906-001",
    "data/raw/cpic-guideline-capture/PGX-DATA-20260906-001",
    "data/closure/wave-04-catalogue",
    "data/closure/wave-04-benchmark",
    "data/closure/wave-04-execution-manifest.json",
    "data/closure/wave-04-operational-evidence.json",
    "data/closure/wave-04-performance.json",
    "data/closure/wave-03b-integration-manifest.json",
    "data/closure/wave-04b-runtime-product-manifest.json",
    "data/closure/wave-04b-browser",
    "data/closure/h01-source-policy-decision.json",
    "data/canonical/dataset-quality-decisions.ndjson",
)


def _digest_file(path):
    with io.open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def _entries():
    rows = []
    for relative in FROZEN_PATHS:
        absolute = os.path.join(REPO, relative)
        if os.path.isfile(absolute):
            rows.append({"path": relative, "sha256": _digest_file(absolute)})
        elif os.path.isdir(absolute):
            for base, directories, names in os.walk(absolute):
                directories[:] = [d for d in directories if d != "__pycache__"]
                for name in sorted(names):
                    full = os.path.join(base, name)
                    rows.append({
                        "path": os.path.relpath(full, REPO)
                        .replace(os.sep, "/"),
                        "sha256": _digest_file(full)})
        else:
            rows.append({"path": relative, "sha256": None,
                         "note": "absent from this tree"})
    return sorted(rows, key=lambda row: row["path"])


def _read(*parts):
    with io.open(os.path.join(REPO, *parts), encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO,
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:  # noqa: BLE001
        commit = ""

    release = _read("data", "releases", "active-candidate-release.json")
    wave04b = _read("data", "closure", "wave-04b-runtime-product-manifest.json")
    catalogue = _read("data", "closure", "wave-04-catalogue", "manifest.json")
    metrics = _read("data", "closure", "wave-04-benchmark", "metrics.json")
    composition = wave04b.get("composition", {})

    entries = _entries()
    combined = hashlib.sha256()
    for row in entries:
        combined.update(row["path"].encode("utf-8"))
        combined.update((row["sha256"] or "ABSENT").encode("utf-8"))
        combined.update(b"\0")

    payload = {
        "schema_version": "pgx-wave05-frozen-candidate-version/1",
        "frozen_for": "WP-C12 external expert evaluation",
        "status": "PRE-EXPERT / NOT FINAL",
        "commit": commit,
        "demonstrated_commit": "0ff8871",
        "demonstrated_commit_note": (
            "The WP-C14 demonstration ran against the tree at 0ff8871. The "
            "commit above may be later; anything after 0ff8871 that is not "
            "listed in this record's artifacts did not change what was "
            "demonstrated, and anything that did would change a hash here."),
        "release_public_id": release["release_public_id"],
        "release_manifest_hash": release["manifest_hash"],
        "dataset_public_id": composition.get("dataset_public_id"),
        "ruleset_key": composition.get("ruleset_key"),
        "ruleset_content_hash": composition.get("ruleset_content_hash"),
        "authority_state": composition.get("authority_state"),
        "review_state": composition.get("review_state"),
        "claim_boundary_status": composition.get("claim_boundary_status"),
        "claim_boundary_is_approved":
            composition.get("claim_boundary_is_approved"),
        "validation_catalogue": {
            "case_total": catalogue.get("case_total"),
            "development_count": catalogue.get("development_count"),
            "internal_holdout_count": catalogue.get("internal_holdout_count"),
            "expert_reserved_count": catalogue.get("expert_holdout_count"),
            "expert_reserved_carry_no_expected_answer":
                catalogue.get("expert_reserved_carry_no_expected_answer"),
        },
        "benchmark": {
            "scored_case_count": metrics.get("scored_case_count"),
            "failed_case_count": metrics.get("failed_case_count"),
            "unsafe_false_reassurance_count":
                metrics.get("unsafe_false_reassurance_count"),
            "expert_reserved_payloads_read":
                metrics.get("expert_reserved_payloads_read"),
        },
        "work_package_verdicts": wave04b.get("work_packages"),
        "artifacts": entries,
        "artifact_count": len(entries),
        "combined_hash": "sha256:" + combined.hexdigest(),
        "what_this_record_is_not": [
            "It is not an approval, and freezing a version approves nothing.",
            "No external expert has seen any of this.",
            "The twelve expert-reserved cases remain sealed and carry no "
            "expected answers; this record hashes them without opening them.",
            "The candidate source policy is still PENDING_REVIEW and the "
            "ordinary DQ gate still fails.",
            "The candidate DQ decision keeps permits_transition = false.",
            "The candidate release is not registered in the WP-13 governed "
            "release registry.",
        ],
    }

    with io.open(OUTPUT, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True,
                                ensure_ascii=False) + "\n")
    print("frozen artifacts: %d" % len(entries))
    print("combined hash:    %s" % payload["combined_hash"])
    print("release:          %s" % payload["release_public_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
