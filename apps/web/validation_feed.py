# -*- coding: utf-8 -*-
"""Read the committed WP-21 dashboard feed. Nothing else.

The narrowest possible adapter, and the narrowness is the security property.
This module opens one committed JSON file and returns its contents. It does
not import the benchmark engine, does not construct a plan, does not hold a
release resolver, and has no path to restricted storage - so a request handler
that uses it cannot reach a holdout payload even by mistake.

If the file is missing or malformed the adapter returns ``None`` and the page
renders its empty state. It does not fabricate a feed, and it does not fall
back to computing one: a dashboard that quietly recomputed its own numbers
would be the one place in the system where a page could disagree with the
committed evidence.
"""

from __future__ import annotations

import io
import json
import os
from typing import Any, Dict, Mapping, Optional

__all__ = ["FEED_PATH", "load_dashboard_feed"]

FEED_PATH = "data/validation/wp21-dashboard-feed.json"

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                          "..", ".."))

#: Keys that must never appear in something this module hands to a template.
#: A second check, after the one the feed builder already ran: the file on
#: disk could have been edited by hand between the two.
_FORBIDDEN = ("observations", "payload", "phenotypes", "medications",
              "expected_result", "expected_attention", "expected_coverage",
              "gold_standard", "ground_truth", "answer_key", "expert_decision",
              "patient", "genotype", "vcf", "case_id", "case_ids")


def _contains_forbidden(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in _FORBIDDEN:
                return True
            if _contains_forbidden(item):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_forbidden(item) for item in value)
    return False


def load_dashboard_feed(root: Optional[str] = None
                        ) -> Optional[Dict[str, Any]]:
    """The committed feed, or ``None`` when there is nothing safe to show."""
    path = os.path.join(root or _REPO_ROOT, *FEED_PATH.split("/"))
    if not os.path.isfile(path):
        return None
    try:
        with io.open(path, "r", encoding="utf-8") as handle:
            feed = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(feed, dict):
        return None
    if feed.get("feed_schema_version") != "pgx-wp21-dashboard-feed/1":
        return None
    if not isinstance(feed.get("sections"), list):
        return None
    if _contains_forbidden(feed):
        # Refuse rather than filter. A feed carrying restricted material is a
        # broken pipeline, and rendering the safe half of it would hide that.
        return None
    return feed
