#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the Execution Wave 1 manifest.

    python3 scripts/build_closure_wave01_manifest.py

Writes ``data/closure/wave-01-execution-manifest.json``: every artifact the
wave produced or regenerated, hashed, with what it is and what it does not
say. Re-running over unchanged inputs produces identical bytes.

The manifest records the baseline commit, which exists before it runs. It
does not record the Wave 1 commit, because a file cannot contain the hash of
a commit that will contain the file.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join("data", "closure", "wave-01-execution-manifest.json")

#: path -> (work package, what it is, what it does not say)
ARTIFACTS = {
    "data/closure/wp-c00-legacy-candidate-dispositions.json": (
        "WP-C00", "one disposition for each unlinked legacy rule candidate",
        "creates no link, no rule and no scientific judgement"),
    "docs/closure/wp-c00-legacy-candidate-dispositions.md": (
        "WP-C00", "the same dispositions, for a reader",
        "rendered from the JSON; it adds nothing the JSON does not hold"),
    "data/closure/wp-c01-database-verification.json": (
        "WP-C01",
        "migrations executed against a real PostgreSQL server, and the "
        "schema compared with the ORM metadata",
        "the application never connected; no driver could be installed"),
    "data/api/wp16-runtime-verification.json": (
        "WP-C01", "a recorded execution of the ASGI runtime checks",
        "host-bound by design; it is rejected on any other machine"),
    "data/verification/wp19-verification-run.json": (
        "WP-C00", "one execution of the full verification profile",
        "PostgreSQL integration was blocked for want of a driver"),
    "data/verification/wp19-real-gate-status.json": (
        "WP-C00", "what WP-19 may say, field by field, after that run",
        "a document about a run is not a run"),
    "data/verification/wp19-test-inventory.json": (
        "WP-C00", "the suite as discovered and categorised",
        "discovering a test is not running it"),
    "data/web/wp17-real-gate-status.json": (
        "WP-C00", "WP-17's gate status, now satisfying its own schema",
        "the screenshots are real captures; the gate is still blocked"),
    "docs/closure/checkpoints/README.md": (
        "WP-C03", "the index of the four human decision checkpoints",
        "nothing in any checkpoint is approved"),
}

CHECKPOINTS = ("H00-repository-identity", "H01-source-policy",
               "H02-curation-protocol", "H03-claims-boundary")
CHECKPOINT_FILES = ("README.md", "decision-context.md", "evidence-table.csv",
                    "proposed-decisions.csv", "unresolved-questions.md",
                    "risk-summary.md", "approval-form.md")


def _sha256(path):
    digest = hashlib.sha256()
    with io.open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _git(root, *args):
    try:
        return subprocess.check_output(("git",) + args, cwd=root,
                                       stderr=subprocess.DEVNULL) \
            .decode("utf-8", "replace").strip()
    except Exception:  # noqa: BLE001
        return ""


def build(root):
    entries = []
    for relative, (work_package, what, caveat) in sorted(ARTIFACTS.items()):
        absolute = os.path.join(root, *relative.split("/"))
        entries.append({
            "path": relative, "work_package": work_package,
            "present": os.path.isfile(absolute),
            "sha256": _sha256(absolute) if os.path.isfile(absolute) else None,
            "bytes": os.path.getsize(absolute) if os.path.isfile(absolute)
            else 0,
            "what_it_is": what, "what_it_does_not_say": caveat,
        })
    checkpoints = []
    for name in CHECKPOINTS:
        files = []
        for member in CHECKPOINT_FILES:
            relative = "docs/closure/checkpoints/%s/%s" % (name, member)
            absolute = os.path.join(root, *relative.split("/"))
            files.append({"path": relative,
                          "present": os.path.isfile(absolute),
                          "sha256": _sha256(absolute)
                          if os.path.isfile(absolute) else None})
        checkpoints.append({
            "checkpoint": name, "files": files,
            "approved": False,
            "approval_form_blank": True,
            "note": "every proposed decision is PENDING_REVIEW and the "
                    "approval form carries no name, date or verdict",
        })

    run = {}
    run_path = os.path.join(root, "data", "verification",
                            "wp19-verification-run.json")
    if os.path.isfile(run_path):
        with io.open(run_path, encoding="utf-8") as handle:
            document = json.load(handle)
        run = {"outcome": document.get("outcome"),
               "summary": document.get("summary"),
               "environment": document.get("environment")}

    baseline_commit = _git(root, "rev-list", "--max-parents=0", "HEAD")
    payload = {
        "manifest_version": "pgx-closure-wave-01-manifest/1",
        "wave": "EXECUTION WAVE 1",
        "work_packages": ["WP-C00", "WP-C01", "WP-C03", "WP-C04"],
        "baseline": {
            "commit": baseline_commit or "UNKNOWN",
            "tag": _git(root, "describe", "--tags", "--abbrev=0") or "UNKNOWN",
            "note": "the Wave 1 commit is not recorded here: a file cannot "
                    "carry the hash of the commit that will contain it",
        },
        "verification_run": run,
        "artifacts": entries,
        "checkpoints": checkpoints,
        "approvals_recorded": 0,
        "ths6_achieved": False,
        "note": "An intact manifest describing a blocked programme is what "
                "this wave was supposed to produce. Nothing here approves a "
                "source, a protocol, a claim or a release.",
    }
    payload["content_hash"] = "sha256:" + hashlib.sha256(json.dumps(
        payload, indent=2, sort_keys=True,
        ensure_ascii=False).encode("utf-8")).hexdigest()
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=REPO_ROOT)
    args = parser.parse_args()
    payload = build(args.repo_root)
    target = os.path.join(args.repo_root, MANIFEST)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with io.open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True,
                                ensure_ascii=False) + "\n")
    sys.stdout.write("artifacts: %d; checkpoints: %d; approvals recorded: "
                     "%d\n" % (len(payload["artifacts"]),
                               len(payload["checkpoints"]),
                               payload["approvals_recorded"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
