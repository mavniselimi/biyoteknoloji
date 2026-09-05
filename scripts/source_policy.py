#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thin wrapper around ``pgx-source-policy`` for a checkout without an install.

The logic lives in :mod:`pgx.application.source_policy_cli` so that the
installed console script and this file cannot drift apart.
"""

from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from pgx.application.source_policy_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
