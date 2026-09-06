#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Record the human H01 source-policy decision.

    python3 scripts/build_closure_wave01_h01_decision.py

Writes, deterministically:

* ``data/closure/h01-source-policy-decision.json``
* ``docs/closure/checkpoints/H01-source-policy/approval-form.md``

The digests the reviewer attested to are re-measured on every run. If a
reviewed artifact has changed, the approval is **not** transferred: the
record becomes a re-attestation request naming the old and new digests, the
form says so, and the exit code is 3.

This script records a decision a person made. It cannot make one, and it
changes no source's status in ``config/scientific-sources.json``.
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

from pgx.closure.h01_decision import (build_decision,  # noqa: E402
                                      render_approval_form)

RECORD = os.path.join("data", "closure", "h01-source-policy-decision.json")
FORM = os.path.join("docs", "closure", "checkpoints", "H01-source-policy",
                    "approval-form.md")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=REPO_ROOT)
    args = parser.parse_args()

    payload = build_decision(args.repo_root)
    for relative, text in (
            (RECORD, json.dumps(payload, indent=2, sort_keys=True,
                                ensure_ascii=False) + "\n"),
            (FORM, render_approval_form(payload))):
        target = os.path.join(args.repo_root, relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with io.open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)

    binding = payload["hash_binding"]
    for row in binding["rows"]:
        sys.stdout.write("  %-8s %-28s %s\n"
                         % ("MATCH" if row["matches"] else "DIFFERS",
                            row["artifact"].rsplit("/", 1)[-1],
                            row["measured_sha256"] or "absent"))
    sys.stdout.write("state: %s\n" % payload["state"])
    if payload["state"] != "RECORDED":
        sys.stdout.write("the approval was NOT transferred; a fresh "
                         "attestation is required\n")
        return 3
    sys.stdout.write("reviewer: %s (%s); decision: %s\n"
                     % (payload["reviewer"]["name"],
                        payload["reviewer"]["qualification"],
                        payload["reviewer"]["decision"]))
    sys.stdout.write("config/scientific-sources.json changed: no\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
