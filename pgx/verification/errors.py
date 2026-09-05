# -*- coding: utf-8 -*-
"""Failures raised by the WP-19 verification system.

These describe faults in the *verification instrument*, not in the software
under test. A test that fails is a result, not an exception; it travels as an
``Outcome``. An exception here means the instrument itself could not produce a
trustworthy answer - the inventory disagreed with the tree, a profile named a
category that does not exist, a worker returned something that is not a result.

Distinguishing the two matters: a broken instrument that raised would otherwise
be indistinguishable from a green suite, and "the verifier crashed" must never
read as "nothing was wrong".
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

__all__ = [
    "VerificationError",
    "DiscoveryError",
    "InventoryError",
    "MatrixError",
    "ProfileError",
    "RunnerError",
    "ResultParseError",
    "CoverageUnavailable",
    "ReproducibilityMismatch",
    "ScrubRefusal",
]


class VerificationError(Exception):
    """Base class for every fault in the verification instrument."""


class DiscoveryError(VerificationError):
    """Test discovery could not enumerate the tree deterministically."""


class InventoryError(VerificationError):
    """The inventory is internally inconsistent.

    Carries every problem at once rather than the first one found: an operator
    fixing a category table wants the whole list, not one round trip per entry.
    """

    def __init__(self, message: str,
                 issues: Optional[Iterable[str]] = None) -> None:
        self.issues: Sequence[str] = tuple(issues or ())
        if self.issues:
            message = "%s: %s" % (message, "; ".join(self.issues))
        super().__init__(message)


class MatrixError(VerificationError):
    """A requirement/test matrix entry does not correspond to a real test."""

    def __init__(self, message: str,
                 issues: Optional[Iterable[str]] = None) -> None:
        self.issues: Sequence[str] = tuple(issues or ())
        if self.issues:
            message = "%s: %s" % (message, "; ".join(self.issues))
        super().__init__(message)


class ProfileError(VerificationError):
    """An execution profile is unknown or names something that does not exist."""


class RunnerError(VerificationError):
    """A verification worker could not be started, or did not report a result.

    Deliberately *not* a failing result. A worker that dies without writing its
    report tells us nothing about the tests it was asked to run, and reporting
    that as ``FAIL`` would invent an outcome; reporting it as ``PASS`` would be
    worse.
    """


class ResultParseError(VerificationError):
    """A worker report could not be read as a verification result."""


class CoverageUnavailable(VerificationError):
    """``coverage.py`` is not importable, so no percentage can be measured.

    Raised only by callers that asked for a measurement. The reporting path
    catches it and records ``BLOCKED`` with the reason and the install command;
    it never substitutes a number.
    """


class ReproducibilityMismatch(VerificationError):
    """Two runs of something declared deterministic produced different bytes."""


class ScrubRefusal(VerificationError):
    """Rendered evidence still contains something that must not be committed.

    A host path, a credential-shaped string, or a clinical payload marker. The
    document is refused rather than written with the offending text removed,
    because silently editing evidence is how evidence stops being evidence.
    """

    def __init__(self, reason: str, sample: str = "") -> None:
        self.reason = reason
        self.sample = sample
        super().__init__(reason if not sample else "%s: %s" % (reason, sample))
