#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thin wrapper around the packaged seed CLI.

The implementation lives in :mod:`pgx.infrastructure.db.cli_seed`, which is part
of the installed package and is what ``pgx-db-seed`` runs. This file exists only
so the seed can be run from a checkout that has not been installed:

    python3 scripts/db_seed.py --print-manifest

There is no seed logic here, so the two paths cannot drift apart.
"""

from __future__ import annotations

import os
import sys

# Allow direct execution from a checkout that has not been pip/uv installed.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from pgx.infrastructure.db.cli_seed import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
