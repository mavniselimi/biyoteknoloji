# -*- coding: utf-8 -*-
"""Locating and loading the release manifest JSON Schema (WP-03).

This lives in the application layer, not the domain, for one reason: the domain
does not read the filesystem. :mod:`pgx.domain.release_manifest` owns the
*rules* a manifest must satisfy and checks them against an in-memory payload; a
path on disk is an environment concern, and a dependency test enforces that the
domain never grows one.
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

__all__ = [
    "RELEASE_MANIFEST_SCHEMA_PATH",
    "load_release_manifest_schema",
]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: The JSON Schema that ``pgx.domain.release_manifest`` output conforms to.
RELEASE_MANIFEST_SCHEMA_PATH = os.path.join(
    _REPO_ROOT, "schemas", "release-manifest.schema.json")


def load_release_manifest_schema(path: str = RELEASE_MANIFEST_SCHEMA_PATH) -> Mapping[str, Any]:
    """Load the JSON Schema document from disk."""
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)
