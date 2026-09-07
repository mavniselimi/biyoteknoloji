#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rebuild every Wave 5 artifact, in the one order that converges.

The four builders have a dependency chain and no cycle:

    expert package   hashes the sixteen documents and the reviewer workflow
          |          and binds them to the frozen version record
          v
    WP-C14B intake   writes the empty feedback register and impact matrix
          |
          v
    WP-C15 inventory hashes both of the above, among nineteen artifacts
          |
          v
    Wave 5 status    checks all of it and hashes the package manifest

Run out of order and a downstream artifact records an upstream hash that is
already stale, which the tests catch. Running this script is how not to.
It exits non-zero if any step does.
"""

from __future__ import annotations

import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STEPS = (
    ("expert package", "build_expert_package.py"),
    ("WP-C14B register", "wp_c14b_intake.py"),
    ("WP-C15 inventory", "build_wp_c15_inventory.py"),
    ("Wave 5 status", "build_wave05_status.py"),
)


def main() -> int:
    for label, script in STEPS:
        print("== %s (%s)" % (label, script))
        result = subprocess.run(
            [sys.executable, os.path.join("scripts", script)], cwd=REPO)
        if result.returncode:
            sys.stderr.write("%s failed with %d; stopping\n"
                             % (script, result.returncode))
            return result.returncode
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
