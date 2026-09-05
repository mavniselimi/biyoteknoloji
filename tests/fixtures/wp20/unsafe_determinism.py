# -*- coding: utf-8 -*-
"""SAFETY-INV-012 negative controls: results that do not reproduce.

``LEGACY-BUG-007``: legacy results carried no version metadata, so two runs
could not be compared even in principle. A result that cannot be reproduced
cannot be reviewed, defended, or retracted.

Each engine here is a small deterministic-looking function with exactly one
source of variation. All three are mistakes that survive code review, because
in each case the variation is somewhere nobody was looking.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, Mapping, Sequence


def base_input() -> Dict[str, Any]:
    """One pinned input. Synthetic medications, a fixed release bundle."""
    return {
        "medications": ["SYNTHDRUG-2", "SYNTHDRUG-1", "SYNTHDRUG-3"],
        "phenotypes": {"CYP2D6": "POOR"},
        "release_id": "REL-TEST-001",
        "ruleset_version": "1.0.0",
    }


def orderings() -> Sequence[Sequence[str]]:
    """The same three medications, arriving in different orders."""
    return (
        ["SYNTHDRUG-1", "SYNTHDRUG-2", "SYNTHDRUG-3"],
        ["SYNTHDRUG-3", "SYNTHDRUG-2", "SYNTHDRUG-1"],
        ["SYNTHDRUG-2", "SYNTHDRUG-3", "SYNTHDRUG-1"],
    )


def _digest(parts: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def safe_engine(request: Mapping[str, Any]) -> Dict[str, Any]:
    """The safe control: sorted input, pinned release, no clock.

    Sorting the medication list is the whole difference between this and the
    first mutant. It is one line, and it is the line that makes the result
    attributable.
    """
    medications = sorted(str(m) for m in request.get("medications", ()))
    parts = medications + [str(request.get("release_id")),
                           str(request.get("ruleset_version"))]
    return {"output_hash": _digest(parts), "medications": medications}


def order_dependent_engine(request: Mapping[str, Any]) -> Dict[str, Any]:
    """NC-INV-012-SHUFFLED-INPUT-CHANGES-OUTPUT - the sort is missing.

    Identical in every other respect. Two clinicians entering the same three
    medications in a different order get two different output hashes, and the
    audit trail records them as two different results.
    """
    medications = [str(m) for m in request.get("medications", ())]
    parts = medications + [str(request.get("release_id")),
                           str(request.get("ruleset_version"))]
    return {"output_hash": _digest(parts), "medications": medications}


class MidRunReleaseChangingEngine:
    """NC-INV-012-MID-RUN-RELEASE-CHANGE - the bundle moves under the run.

    Models a release activated while assessments are in flight. Each call reads
    the *current* active release rather than one pinned before calculation
    began, so consecutive identical requests are attributed to different
    bundles and neither result can be defended.
    """

    def __init__(self) -> None:
        self._generation = 0

    def __call__(self, request: Mapping[str, Any]) -> Dict[str, Any]:
        self._generation += 1
        medications = sorted(str(m) for m in request.get("medications", ()))
        parts = medications + ["REL-TEST-%03d" % self._generation,
                               str(request.get("ruleset_version"))]
        return {"output_hash": _digest(parts), "medications": medications}


def wall_clock_engine(request: Mapping[str, Any]) -> Dict[str, Any]:
    """NC-INV-012-WALL-CLOCK-IN-OUTPUT - a timestamp inside the hash.

    Usually arrives as a "generated at" field added for operational
    convenience, then included in the hashed payload by a canonicaliser that
    hashes everything. Two identical runs a nanosecond apart disagree.
    """
    medications = sorted(str(m) for m in request.get("medications", ()))
    parts = medications + [str(request.get("release_id")),
                           str(request.get("ruleset_version")),
                           repr(time.time())]
    return {"output_hash": _digest(parts), "medications": medications}


UNSAFE_SUBJECTS = {
    "NC-INV-012-SHUFFLED-INPUT-CHANGES-OUTPUT": order_dependent_engine,
    "NC-INV-012-MID-RUN-RELEASE-CHANGE": MidRunReleaseChangingEngine,
    "NC-INV-012-WALL-CLOCK-IN-OUTPUT": wall_clock_engine,
}

SAFE_SUBJECT = safe_engine
