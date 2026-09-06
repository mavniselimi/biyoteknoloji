#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the WP-C05 acquisition matrix and the manual checklist.

    python3 scripts/build_closure_wave02_acquisition.py

Writes, deterministically:

* ``data/closure/wp-c05-acquisition-plan.json``
* ``docs/closure/wp-c05-manual-acquisition-checklist.md``

The plan is derived from the recorded H01 decision and is refused if that
decision is not in the RECORDED state. It acquires nothing: every approved
mode is manual, so what this produces is the matrix and the checklist a
person works through.
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

from pgx.closure.acquisition_plan import (build_plan,  # noqa: E402
                                          render_checklist)

PLAN = os.path.join("data", "closure", "wp-c05-acquisition-plan.json")
CHECKLIST = os.path.join("docs", "closure",
                         "wp-c05-manual-acquisition-checklist.md")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=REPO_ROOT)
    args = parser.parse_args()

    payload = build_plan(args.repo_root)
    if payload["derived_from"]["h01_decision_state"] != "RECORDED":
        sys.stdout.write("H01 is %s; no acquisition plan is derived from an "
                         "unrecorded decision\n"
                         % payload["derived_from"]["h01_decision_state"])
        return 3

    for relative, text in ((PLAN, json.dumps(payload, indent=2,
                                             sort_keys=True,
                                             ensure_ascii=False) + "\n"),
                           (CHECKLIST, render_checklist(payload))):
        target = os.path.join(args.repo_root, relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with io.open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)

    sys.stdout.write("sources in plan: %d; acquisition executed: %s\n"
                     % (len(payload["rows"]), payload["acquisition_executed"]))
    for row in payload["rows"]:
        sys.stdout.write("  %-20s %-18s automation permitted: %s\n"
                         % (row["source_key"],
                            ",".join(row["permitted_acquisition_modes"]),
                            row["automation_permitted"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
