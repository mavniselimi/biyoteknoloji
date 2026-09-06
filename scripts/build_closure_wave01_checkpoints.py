#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the historical WP-C03 human decision checkpoint packages.

    python3 scripts/build_closure_wave01_checkpoints.py

Writes four packages under ``docs/closure/checkpoints/``, each with the same
seven files, plus an index. Every value is read from the repository - the
source registry, the curation protocol, the claim boundary, the WP-C00
disposition report and Git itself.

An ``approval-form.md`` that a reviewer has filled in is never overwritten.
The producer compares what is on disk with the blank template and leaves
anything else alone, because regenerating over somebody's decision would
destroy the only record of it.

The packages remain audit/review inputs under the 2026-09-06 candidate-first
execution policy. An unsigned form no longer blocks candidate construction;
internal decisions are recorded separately and remain pending final external
expert review. This script approves nothing and records no name, signature or
date.
"""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from pgx.closure.checkpoints import build_all  # noqa: E402


def _git(root: str, *args: str) -> str:
    try:
        out = subprocess.check_output(("git",) + args, cwd=root,
                                      stderr=subprocess.DEVNULL)
    except Exception:  # noqa: BLE001 - a missing repository is a real answer
        return ""
    return out.decode("utf-8", "replace").strip()


def baseline_facts(root: str) -> dict:
    """Measured from Git. Nothing here is written down in advance."""
    tag = _git(root, "describe", "--tags", "--abbrev=0") or "UNKNOWN"
    commit = _git(root, "rev-list", "--max-parents=0", "HEAD") or "UNKNOWN"
    tree = _git(root, "rev-parse", "%s^{tree}" % commit) if commit != \
        "UNKNOWN" else "UNKNOWN"
    files = _git(root, "ls-tree", "-r", "--name-only", commit)
    remotes = _git(root, "remote")
    committed_at = _git(root, "log", "-1", "--format=%cI", commit) or \
        "UNKNOWN"
    if committed_at.endswith("Z"):
        committed_at = committed_at[:-1] + "+00:00"
    return {
        "commit": commit,
        "tree": tree or "UNKNOWN",
        "tag": tag,
        "branch": _git(root, "rev-parse", "--abbrev-ref", "HEAD") or "UNKNOWN",
        "file_count": len([line for line in files.splitlines() if line]),
        "author_name": _git(root, "log", "-1", "--format=%an", commit)
        or "UNKNOWN",
        "author_email": _git(root, "log", "-1", "--format=%ae", commit)
        or "UNKNOWN",
        "committed_at": committed_at,
        "remote_count": len([line for line in remotes.splitlines() if line]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=REPO_ROOT)
    args = parser.parse_args()

    files = build_all(args.repo_root, baseline_facts(args.repo_root))
    written = preserved = 0
    for relative, text in sorted(files.items()):
        target = os.path.join(args.repo_root, *relative.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if relative.endswith("approval-form.md") and os.path.isfile(target):
            with io.open(target, encoding="utf-8") as handle:
                existing = handle.read()
            if existing != text:
                preserved += 1
                sys.stdout.write("preserved (filled in): %s\n" % relative)
                continue
        with io.open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        written += 1

    sys.stdout.write("checkpoint files written: %d; approval forms "
                     "preserved: %d\n" % (written, preserved))
    sys.stdout.write("historical proposals remain PENDING_REVIEW; a preserved "
                     "form is one a person filled in. Candidate execution "
                     "uses separate provisional internal decision records.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
