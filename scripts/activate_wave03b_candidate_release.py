#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create and activate the candidate release (WP-C09)."""

from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pgx.application.candidate_release import (  # noqa: E402
    ACTIVE_POINTER, RELEASE_ROOT, build_candidate_release_manifest,
    load_active_candidate_release)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELEASE_ID = "PGX-CANDIDATE-REL-20260906-001"
DATASET_ID = "PGX-DATA-20260906-001"
RULESET_KEY = "PGX-CANDIDATE-RULESET-WAVE03B"
BUILT_BY = "pgx-closure-wave03b automated pass (NOT A HUMAN)"


def _write(path: str, payload) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True,
                                ensure_ascii=False) + "\n")


def main() -> int:
    manifest_path = os.path.join(REPO, RELEASE_ROOT, RELEASE_ID,
                                 "manifest.json")
    if os.path.exists(manifest_path):
        sys.stdout.write("release manifest already exists\n")
    else:
        manifest = build_candidate_release_manifest(
            release_public_id=RELEASE_ID, repo_root=REPO,
            dataset_public_id=DATASET_ID, ruleset_key=RULESET_KEY,
            built_by=BUILT_BY)
        _write(manifest_path, manifest)

    with io.open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)

    pointer_path = os.path.join(REPO, ACTIVE_POINTER)
    generation = 1
    if os.path.isfile(pointer_path):
        with io.open(pointer_path, encoding="utf-8") as handle:
            existing = json.load(handle)
        if existing.get("release_public_id") != RELEASE_ID or \
                existing.get("manifest_hash") != manifest["manifest_hash"]:
            generation = int(existing.get("generation", 0)) + 1
        else:
            generation = int(existing.get("generation", 1))
    _write(pointer_path, {
        "generation": generation,
        "manifest_hash": manifest["manifest_hash"],
        "note": ("The active candidate release. Not a governed active "
                 "release: the WP-13 active-release pointer is a separate "
                 "record and is untouched, because a candidate release has "
                 "not earned it."),
        "release_public_id": RELEASE_ID,
        "supersedes_standalone_artifact": "PGX-CANDIDATE-RELEASE-WAVE03",
        "supersedes_note": (
            "The Wave 3 standalone release remains as historical evidence. It "
            "was never registered, never active, and is superseded rather "
            "than rewritten."),
    })

    pinned = load_active_candidate_release(REPO)
    sys.stdout.write(
        "active candidate release\n  id           %s\n  dataset      %s\n"
        "  ruleset      %s (%d rules, %d joint)\n  modes        %s\n"
        "  review       %s\n  manifest     %s\n  generation   %d\n"
        % (pinned.release_public_id, pinned.dataset_public_id,
           pinned.ruleset.ruleset_key, len(pinned.ruleset.rules),
           sum(1 for r in pinned.ruleset.rules if r.is_joint),
           ", ".join(pinned.manifest["permitted_modes"]),
           pinned.manifest["review_state"],
           pinned.manifest["manifest_hash"], pinned.pointer_generation))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
