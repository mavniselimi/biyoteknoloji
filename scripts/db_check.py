#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thin wrapper around the packaged check CLI.

The implementation lives in :mod:`pgx.infrastructure.db.cli_check`, which is
part of the installed package and is what ``pgx-db-check`` runs. This file
exists only so the check can be run from an uninstalled checkout.
"""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from pgx.infrastructure.db.cli_check import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
