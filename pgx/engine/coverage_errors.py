# -*- coding: utf-8 -*-
"""Failure types for the coverage engine (WP-13).

Every type carries a stable machine-readable ``code``. A caller distinguishing
"this manifest is malformed" from "this manifest pins a ruleset that is not
the one supplied" must not have to parse a sentence, and the two have very
different consequences: one is an authoring error, the other is a boundary
violation that must fail closed.

Note what is *not* here: there is no error for "the coverage is insufficient".
Insufficient coverage is a result, not a failure - it is the honest answer to
a question, and a caller that could catch it as an exception might be tempted
to swallow it.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

__all__ = [
    "CoverageEngineError",
    "CoverageManifestError",
    "CoverageBoundaryError",
    "CoverageInputError",
]


class CoverageEngineError(Exception):
    """Base class for every coverage-engine failure."""

    def __init__(self, message: str, *, code: str = "COVERAGE_ERROR",
                 location: str = "$",
                 detail: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.location = location
        self.detail = dict(detail or {})


class CoverageManifestError(CoverageEngineError):
    """A coverage manifest could not be built or verified as stated.

    Every one of these is a refusal rather than a repair. A manifest is a
    governed declaration of what a ruleset can evaluate; silently correcting
    one would be editing a scientific claim on its author's behalf.
    """


class CoverageBoundaryError(CoverageEngineError):
    """The manifest, the ruleset, the dataset or the evidence build supplied
    to an evaluation are not the ones each other pins.

    Raised only when the mismatch makes evaluation meaningless before it
    starts. A per-axis mismatch is reported as a coverage *result* with
    ``DATASET_RULESET_MISMATCH`` instead, because a caller has to be able to
    record it against the axis it affects.
    """


class CoverageInputError(CoverageEngineError):
    """A coverage request could not be read.

    A structurally invalid medication reference, a duplicated request, or an
    empty request. Duplicates are refused rather than deduplicated: a caller
    that asked twice may have meant two different things, and quietly
    collapsing them would answer a question nobody asked.
    """
