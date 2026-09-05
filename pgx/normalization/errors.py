# -*- coding: utf-8 -*-
"""Typed canonicalization failures (WP-07).

Standard library only.

The split is functional. A caller reacts differently to "this input cannot be
normalised at all", "this artifact is not what the role map says it is" and
"this build cannot be written", so those are three types rather than one.

Nothing here inherits from the domain error tree. Canonicalization is a
build-pipeline concern, not a pharmacogenetic domain rule, and a handler
written for domain invariants must not swallow a corrupt-artifact failure.
"""

from __future__ import annotations

from typing import Optional, Sequence

__all__ = [
    "AllocationError",
    "ArtifactRoleError",
    "CanonicalBuildError",
    "CanonicalizationError",
    "NormalizationError",
    "QualityGateError",
]


class CanonicalizationError(Exception):
    """Base class for every canonical-build failure."""


class NormalizationError(CanonicalizationError):
    """A value cannot be normalised deterministically.

    Raised only for input that is not a string, is empty after trimming, or
    carries characters no normalisation rule accepts. It is never raised
    because a value failed to *match* something: an unmatched value is an
    ``UNRESOLVED`` resolution outcome, which is data, not an exception.
    """


class ArtifactRoleError(CanonicalizationError):
    """A raw artifact is missing, unrecognised, or not the shape its role claims.

    Unrecognised artifacts are reported rather than guessed at. A build that
    silently parsed an unknown file as if it were an entity source would invent
    entities nobody put there.
    """

    def __init__(self, message: str, artifacts: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.artifacts = tuple(artifacts)


class AllocationError(CanonicalizationError):
    """The identity allocation is missing, unreadable, or does not cover the build.

    Allocation is an explicit state-changing step. A build that minted a UUID
    because the map lacked one would make "the same snapshot rebuilds
    identically" false, so a gap raises instead.
    """


class CanonicalBuildError(CanonicalizationError):
    """A canonical build could not be written, sealed or read back."""

    def __init__(self, message: str, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


class QualityGateError(CanonicalizationError):
    """A dataset lifecycle transition was refused.

    Carries the blocking issues so a caller can report all of them rather than
    the first. A refused quality check is an ordinary outcome in this project,
    not an exceptional one, so services return a report and raise this only
    when a caller asked for the transition itself.
    """

    def __init__(self, message: str, issues: Sequence = ()) -> None:
        super().__init__(message)
        self.issues = tuple(issues)
