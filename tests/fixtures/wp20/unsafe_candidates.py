# -*- coding: utf-8 -*-
"""SAFETY-INV-005 negative controls: candidate listings that recommend.

``LEGACY-BUG-009``: the legacy ranker produced a 0-100 "suitability score" that
mixed *we have data about this drug* with *this drug is a good choice*. A
ranked list is read as a recommendation regardless of the disclaimer printed
above it, and the disclaimer is the part people skip.

P0 ships no candidate exploration at all. These fixtures exist so the detector
is proven now, and so that shipping the feature with any of these shapes fails
the gate rather than passing it.
"""

from __future__ import annotations

from typing import Any, Dict, Sequence


def safe_listing() -> Dict[str, Any]:
    """The safe control: data status only, no ordering, no label.

    Each candidate says whether the dataset contains it and whether a validated
    rule exists. That is a statement about the system's knowledge, not about
    the drug.
    """
    return {
        "ordered_by": "name",
        "candidates": [
            {"name": "SYNTHDRUG-1", "in_dataset": True,
             "validated_rule_exists": True, "coverage": "FULL",
             "attention": "NOT_ASSESSED"},
            {"name": "SYNTHDRUG-2", "in_dataset": True,
             "validated_rule_exists": False, "coverage": "INSUFFICIENT",
             "attention": "NOT_ASSESSED"},
            {"name": "SYNTHDRUG-3", "in_dataset": False,
             "validated_rule_exists": False, "coverage": "UNSUPPORTED_DRUG",
             "attention": "NOT_ASSESSED"},
        ],
        "rendered_strings": (
            "Data status for three chemicals in the pinned dataset.",
            "Bu bir tedavi onerisi degildir.",
        ),
    }


def with_safety_score() -> Dict[str, Any]:
    """NC-INV-005-SAFETY-SCORE - the legacy 0-100 ranking, restored."""
    listing = safe_listing()
    for index, candidate in enumerate(listing["candidates"]):
        candidate["safety_score"] = 95 - (index * 30)
    listing["ordered_by"] = "safety_score"
    return listing


def ordered_by_attention() -> Dict[str, Any]:
    """NC-INV-005-ORDERED-BY-ATTENTION - no score, still a ranking.

    Subtler than a score and just as readable as one: put the quietest
    candidate first and the list has made a recommendation without ever using
    the word.
    """
    listing = safe_listing()
    listing["ordered_by"] = "attention"
    return listing


def preferred_label() -> Dict[str, Any]:
    """NC-INV-005-PREFERRED-LABEL - the claim said outright, in both languages."""
    listing = safe_listing()
    listing["rendered_strings"] = (
        "SYNTHDRUG-1 is the preferred option for this profile.",
        "SYNTHDRUG-1 bu profil icin daha guvenli bir tercihtir.",
    )
    return listing


UNSAFE_SUBJECTS = {
    "NC-INV-005-SAFETY-SCORE": with_safety_score,
    "NC-INV-005-ORDERED-BY-ATTENTION": ordered_by_attention,
    "NC-INV-005-PREFERRED-LABEL": preferred_label,
}

SAFE_SUBJECT = safe_listing
