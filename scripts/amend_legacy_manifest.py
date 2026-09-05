#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Controlled, single-file amendment of the WP-01 legacy baseline manifest.

This tool exists because a WP-01 *evidence* file (a regression test) had to be
corrected during the WP-02 phase transition, and the manifest that pins its
hash must be updated without re-collecting the baseline.

It is deliberately narrow:

* It amends exactly one ``evidence_artifacts`` entry per invocation.
* It refuses to touch the 64 legacy/WP-00 ``artifacts`` entries at all - not
  their hashes, not their metadata, not their count.
* It refuses to run if *any* legacy artifact hash no longer matches disk, or if
  any evidence artifact other than the amended one no longer matches disk. An
  amendment therefore certifies "one intentional change, nothing else moved".
* It never adds, removes or renames entries, so WP-02 files cannot be absorbed
  into the WP-01 baseline through this path.
* It appends an audit record to ``manifest["amendments"]`` carrying the reason,
  the UTC date, the old and new digests, and a free-text note.

It does NOT re-run ``build_legacy_baseline.py``; a full re-collection would
silently re-bless whatever else had drifted.

Usage (dry run first, --apply to write):

    python3 scripts/amend_legacy_manifest.py \
        --path tests/regression/legacy/test_legacy_reproduction.py \
        --reason "<why>" --note "<note>" [--apply]
"""

from __future__ import annotations

import argparse
import datetime
import io
import os
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPTS_DIR)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from legacy_baseline_lib import (  # noqa: E402
    dump_json, is_safe_manifest_path, read_json, resolve_within_repo, sha256_file,
)

MANIFEST_PATH = os.path.join(REPO_ROOT, "data", "legacy-baseline", "manifest.json")

EXPECTED_LEGACY_ARTIFACTS = 64
EXPECTED_EVIDENCE_ARTIFACTS = 22

AMENDMENT_SCHEMA_VERSION = "wp01-manifest-amendment/1"


class AmendmentRefused(Exception):
    """Raised when the preconditions for a controlled amendment do not hold."""


def _digest(relative_path):
    absolute = resolve_within_repo(REPO_ROOT, relative_path)
    if not os.path.isfile(absolute):
        raise AmendmentRefused("file does not exist on disk: %s" % relative_path)
    return sha256_file(absolute), os.path.getsize(absolute)


def _drifted(entries):
    """Return [(path, manifest_sha, disk_sha)] for entries whose hash moved."""
    drift = []
    for entry in entries:
        path = entry["path"]
        if not is_safe_manifest_path(path):
            raise AmendmentRefused("unsafe manifest path: %r" % path)
        absolute = resolve_within_repo(REPO_ROOT, path)
        if not os.path.isfile(absolute):
            drift.append((path, entry["sha256"], "MISSING"))
            continue
        actual = sha256_file(absolute)
        if actual != entry["sha256"]:
            drift.append((path, entry["sha256"], actual))
    return drift


def amend(manifest_path, target_path, reason, note, apply_changes, today=None):
    document = read_json(manifest_path)

    legacy = document.get("artifacts", [])
    evidence = document.get("evidence_artifacts", [])

    if len(legacy) != EXPECTED_LEGACY_ARTIFACTS:
        raise AmendmentRefused(
            "legacy artifact count is %d, expected %d - refusing to amend a "
            "baseline whose scope already changed"
            % (len(legacy), EXPECTED_LEGACY_ARTIFACTS))
    if len(evidence) != EXPECTED_EVIDENCE_ARTIFACTS:
        raise AmendmentRefused(
            "evidence artifact count is %d, expected %d"
            % (len(evidence), EXPECTED_EVIDENCE_ARTIFACTS))

    if any(entry["path"] == target_path for entry in legacy):
        raise AmendmentRefused(
            "%s is a legacy/WP-00 artifact; this tool never amends legacy "
            "artifact hashes" % target_path)

    matches = [entry for entry in evidence if entry["path"] == target_path]
    if len(matches) != 1:
        raise AmendmentRefused(
            "%s matches %d evidence artifacts; expected exactly 1 (this tool "
            "never adds new entries)" % (target_path, len(matches)))
    target = matches[0]

    legacy_drift = _drifted(legacy)
    if legacy_drift:
        raise AmendmentRefused(
            "%d legacy artifact(s) no longer match disk; amendment refused: %s"
            % (len(legacy_drift), ", ".join(item[0] for item in legacy_drift)))

    other_drift = _drifted([e for e in evidence if e["path"] != target_path])
    if other_drift:
        raise AmendmentRefused(
            "%d evidence artifact(s) other than the amended file changed; a "
            "controlled amendment covers exactly one file: %s"
            % (len(other_drift), ", ".join(item[0] for item in other_drift)))

    old_sha = target["sha256"]
    old_size = target["size_bytes"]
    new_sha, new_size = _digest(target_path)

    if new_sha == old_sha:
        raise AmendmentRefused(
            "%s already matches the manifest; nothing to amend" % target_path)

    stamp = today or datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    record = {
        "amended_at_utc": stamp,
        "amendment_schema_version": AMENDMENT_SCHEMA_VERSION,
        "legacy_artifacts_verified_unchanged": len(legacy),
        "new_sha256": new_sha,
        "new_size_bytes": new_size,
        "note": note,
        "old_sha256": old_sha,
        "old_size_bytes": old_size,
        "path": target_path,
        "reason": reason,
        "rebuild_performed": False,
    }

    print("controlled amendment")
    print("  path      : %s" % target_path)
    print("  old sha256: %s (%d bytes)" % (old_sha, old_size))
    print("  new sha256: %s (%d bytes)" % (new_sha, new_size))
    print("  legacy artifacts verified unchanged: %d/%d"
          % (len(legacy), EXPECTED_LEGACY_ARTIFACTS))
    print("  evidence artifacts (count preserved): %d/%d"
          % (len(evidence), EXPECTED_EVIDENCE_ARTIFACTS))
    print("  rebuild performed: no")

    if not apply_changes:
        print("  DRY RUN - manifest not written (pass --apply to write)")
        return record

    target["sha256"] = new_sha
    target["size_bytes"] = new_size
    document.setdefault("amendments", []).append(record)

    if len(document["artifacts"]) != EXPECTED_LEGACY_ARTIFACTS:
        raise AmendmentRefused("post-write legacy artifact count changed")
    if len(document["evidence_artifacts"]) != EXPECTED_EVIDENCE_ARTIFACTS:
        raise AmendmentRefused("post-write evidence artifact count changed")

    dump_json(document, manifest_path)
    print("  APPLIED - manifest rewritten")
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", default=MANIFEST_PATH)
    parser.add_argument("--path", required=True,
                        help="repository-relative path of the evidence artifact")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--apply", action="store_true",
                        help="write the manifest (default is a dry run)")
    args = parser.parse_args(argv)

    try:
        amend(args.manifest, args.path, args.reason, args.note, args.apply)
    except AmendmentRefused as exc:
        sys.stderr.write("AMENDMENT REFUSED: %s\n" % exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
