# -*- coding: utf-8 -*-
"""Shared helpers for the WP-21 tests."""

from __future__ import annotations

import io
import json
import os
from typing import Any, Dict, Mapping

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                         "..", "..", ".."))


def read_json(relative: str) -> Dict[str, Any]:
    path = os.path.join(REPO_ROOT, *relative.split("/"))
    with io.open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def metrics_of(document: Mapping[str, Any], role: str):
    """Every metric value for one role, from a report or a feed."""
    key = "partitions" if "partitions" in document else "sections"
    for section in document[key]:
        if section.get("role") == role:
            return list(section.get("metrics", ()))
    raise AssertionError("no section for role %r" % role)
