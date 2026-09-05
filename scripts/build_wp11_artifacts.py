#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the WP-11 inventory and real-data gate reports.

    python3 scripts/build_wp11_artifacts.py

Writes, deterministically:

* ``data/migration/wp11/legacy-rule-candidate-inventory.json``
* ``data/rulesets/wp11-real-gate-status.json``
* ``data/rulesets/wp11-real-build-attempt.json``

Every value is read from the repository's own artifacts. Re-running over
unchanged inputs produces identical bytes, so a diff means the repository's
state changed rather than that the script ran again.

This script creates no rule and no ruleset. It reports why none can exist.
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

from pgx.application.rule_gate_status import (build_gate_status,  # noqa: E402
                                              build_real_build_attempt)
from pgx.rules.legacy import build_inventory  # noqa: E402

INVENTORY = os.path.join("data", "migration", "wp11",
                         "legacy-rule-candidate-inventory.json")
GATE_STATUS = os.path.join("data", "rulesets", "wp11-real-gate-status.json")
BUILD_ATTEMPT = os.path.join("data", "rulesets", "wp11-real-build-attempt.json")


def _write_json(path: str, payload) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=REPO_ROOT)
    args = parser.parse_args()

    inventory = build_inventory(args.repo_root)
    _write_json(os.path.join(args.repo_root, INVENTORY), inventory.to_json())
    counts = inventory.counts()

    status = build_gate_status(args.repo_root)
    _write_json(os.path.join(args.repo_root, GATE_STATUS), status.to_json())

    attempt = build_real_build_attempt(args.repo_root)
    _write_json(os.path.join(args.repo_root, BUILD_ATTEMPT), attempt.to_json())

    sys.stdout.write(
        "legacy candidates: %d (%d linked, %d unlinked); eligible for rule "
        "creation: %d\n" % (counts["candidates"], counts["linked"],
                            counts["unlinked"],
                            counts["eligible_for_rule_creation"]))
    sys.stdout.write("real rules: 0 draft, 0 curated, 0 validated; "
                     "real frozen rulesets: %d\n"
                     % status.payload["rule_state"]["real_frozen_rulesets"])
    sys.stdout.write("blockers: %s\n" % ", ".join(status.blockers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
