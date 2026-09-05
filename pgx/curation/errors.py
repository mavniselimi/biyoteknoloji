# -*- coding: utf-8 -*-
"""Failures the curation protocol raises (WP-09).

Separate types rather than one, because the callers differ: a malformed
vocabulary is a programming error, an incomplete rationale is a curator's
unfinished work, and an absent approval is a state nobody may route around.
"""

from __future__ import annotations

from typing import Optional, Sequence

__all__ = [
    "ApprovalError",
    "CaseSeparationError",
    "CurationError",
    "EvidenceSelectionError",
    "ProtocolError",
    "RationaleError",
    "RoleSeparationError",
    "VocabularyError",
]


class CurationError(Exception):
    """Base class for every WP-09 failure."""


class VocabularyError(CurationError):
    """A value outside a controlled vocabulary, or a vocabulary misuse.

    Also raised when a caller treats a non-ordered vocabulary as ordered:
    ``INSUFFICIENT`` is not less than ``SUPPORTED``, and code that compared
    them would be inventing a scale nobody defined.
    """


class EvidenceSelectionError(CurationError):
    """Evidence is missing, unreferenced, or excluded without a reason."""


class RationaleError(CurationError):
    """A rationale is absent, placeholder, or circular.

    Carries the failing parts so a curator sees the whole list rather than
    fixing one and resubmitting.
    """

    def __init__(self, message: str,
                 missing: Sequence[str] = (),
                 rejected: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.missing = tuple(missing)
        self.rejected = tuple(rejected)


class RoleSeparationError(CurationError):
    """Author and independent reviewer are the same person, or a role that
    cannot approve scientific meaning is being used to approve it."""


class CaseSeparationError(CurationError):
    """A case holds two roles, or a holdout is being used as development."""


class ProtocolError(CurationError):
    """The protocol document itself is malformed or internally inconsistent."""

    def __init__(self, message: str, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


class ApprovalError(CurationError):
    """Approval metadata is absent, incomplete, or a placeholder.

    A placeholder is treated as absence rather than as a lesser form of
    approval: 'TEST_REVIEWER' approving a scientific protocol is not a weak
    approval, it is no approval wearing the shape of one.
    """
