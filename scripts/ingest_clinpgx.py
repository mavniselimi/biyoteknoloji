#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thin wrapper around the packaged ``pgx-ingest-clinpgx`` CLI (WP-04).

The implementation lives in :mod:`pgx.application.ingestion_cli` so the
installed package owns it. This file exists only so the command can be run from
a checkout without installing anything.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pgx.application.ingestion_cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
