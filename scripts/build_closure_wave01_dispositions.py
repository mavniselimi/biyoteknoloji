#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the WP-C00 disposition report for the unlinked legacy candidates.

    python3 scripts/build_closure_wave01_dispositions.py

Writes, deterministically:

* ``data/closure/wp-c00-legacy-candidate-dispositions.json``
* ``docs/closure/wp-c00-legacy-candidate-dispositions.md``

Every value is read from the repository's own migration and evidence
artifacts. Re-running over unchanged inputs produces identical bytes, so a
diff means the repository's state changed rather than that the script ran
again.

This script creates no link, no rule and no interpretation.
"""

from __future__ import annotations

import argparse
import io
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from pgx.closure.legacy_dispositions import (build_report,  # noqa: E402
                                             canonical_json, render_markdown)

REPORT = os.path.join("data", "closure",
                      "wp-c00-legacy-candidate-dispositions.json")
SUMMARY = os.path.join("docs", "closure",
                       "wp-c00-legacy-candidate-dispositions.md")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=REPO_ROOT)
    args = parser.parse_args()

    payload = build_report(args.repo_root)
    for relative, text in ((REPORT, canonical_json(payload)),
                           (SUMMARY, render_markdown(payload))):
        target = os.path.join(args.repo_root, relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with io.open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)

    counts = payload["counts"]
    sys.stdout.write("unlinked legacy candidates: %d\n"
                     % counts["unlinked_candidates"])
    for name, total in sorted(counts["by_disposition"].items()):
        if total:
            sys.stdout.write("  %-46s %d\n" % (name, total))
    sys.stdout.write("origins resolving: %d/%d; naming an upstream record: "
                     "%d\n" % (counts["origins_resolving"],
                               counts["unlinked_candidates"],
                               counts["naming_an_upstream_record"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
