# -*- coding: utf-8 -*-
"""Typed evidence-import failures (WP-08).

Standard library only.

The split is functional, exactly as it is in :mod:`pgx.normalization.errors`.
A caller reacts differently to "this raw record cannot be read at all", "this
record carries a field the evidence store must never hold" and "this build
cannot be written", so those are separate types rather than one.

Nothing here inherits from the domain error tree. Evidence import is a
migration-pipeline concern, not a pharmacogenetic domain rule, and a handler
written for domain invariants must not swallow a corrupt-artifact failure.
"""

from __future__ import annotations

from typing import Optional, Sequence

__all__ = [
    "EvidenceAllocationError",
    "EvidenceBuildError",
    "EvidenceError",
    "EvidenceGateError",
    "ProhibitedFieldError",
    "SourceRecordError",
]


class EvidenceError(Exception):
    """Base class for every evidence-import failure."""


class SourceRecordError(EvidenceError):
    """A raw source record cannot be read as the shape its container implies.

    Raised for a payload that is not an object, an identity that is neither a
    string nor an integer, or a container whose contents contradict the
    artifact's declared role. It is never raised because a record failed to
    *resolve* something: an unresolved reference is an import issue, which is
    data, not an exception.
    """


class ProhibitedFieldError(EvidenceError):
    """Normalized evidence metadata carries a project-authored field.

    The one invariant that cannot be downgraded to a reported issue. A risk
    level or a plain-language conclusion sitting in an evidence record is not a
    data-quality problem to be counted; it is the store no longer meaning what
    it says, so construction fails.

    ``field`` names the offender so a caller can report it without parsing the
    message.
    """

    def __init__(self, message: str, field: Optional[str] = None,
                 fields: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.field = field
        self.fields = tuple(fields) or ((field,) if field else ())


class EvidenceAllocationError(EvidenceError):
    """The evidence identity allocation is missing, unreadable or incomplete.

    Allocation is an explicit state-changing step, as it is in WP-07. An import
    that minted a UUID because the map lacked one would make "the same inputs
    rebuild identically" false, so a gap raises instead.
    """


class EvidenceBuildError(EvidenceError):
    """An evidence build could not be written, sealed or read back."""

    def __init__(self, message: str, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


class EvidenceGateError(EvidenceError):
    """An import was refused by the pre-build gates.

    Carries the blocking issues so a caller can report all of them rather than
    the first. A refused import is an ordinary outcome in this project, not an
    exceptional one, so the importer returns a report and raises this only when
    a caller asked for production eligibility it cannot have.
    """

    def __init__(self, message: str, issues: Sequence = ()) -> None:
        super().__init__(message)
        self.issues = tuple(issues)
