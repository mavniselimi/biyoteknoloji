# -*- coding: utf-8 -*-
"""Failures the validation dataset architecture raises (WP-18).

Separate types, because the callers differ and the right response differs. A
malformed case is a programming error a developer fixes. A separation
violation is a scientific fault that invalidates a measurement nobody has
taken yet, and the only correct response is refusal. A refused access is a
policy decision that must leak nothing about what was refused.

Every message in this module is written on the assumption that it may be
logged. None of them interpolates a payload, an expected answer, a phenotype
or a filesystem path.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

__all__ = [
    "AccessDeniedError",
    "CompatibilityError",
    "FingerprintError",
    "ImportRefusedError",
    "ProvenanceError",
    "RestrictedContentError",
    "SeparationError",
    "ValidationCaseError",
    "ValidationDatasetError",
    "VisibilityError",
]


class ValidationDatasetError(Exception):
    """Base class for every WP-18 failure."""


class ValidationCaseError(ValidationDatasetError):
    """A case is malformed, incomplete, or carries a prohibited field."""


class ProvenanceError(ValidationDatasetError):
    """Where a case came from is absent, unverifiable, or self-referential.

    A holdout with no provenance cannot be shown to be independent, and
    "cannot be shown to be independent" is the same thing as "is not
    independent" for the purpose of a validation claim.
    """


class SeparationError(ValidationDatasetError):
    """Development and holdout would overlap.

    ``SAFETY-INV-009``. Raised rather than reported when a single operation
    would create the overlap; :func:`~pgx.validation.separation.audit_partition`
    returns the whole list instead, because somebody repairing a case set
    wants every problem at once.
    """

    def __init__(self, message: str,
                 issue_codes: Optional[Sequence[str]] = None) -> None:
        super().__init__(message)
        self.issue_codes: Tuple[str, ...] = tuple(sorted(set(issue_codes
                                                             or ())))


class FingerprintError(ValidationDatasetError):
    """A content fingerprint could not be computed over the given value."""


class RestrictedContentError(ValidationDatasetError):
    """Restricted content appeared where only public metadata may go.

    The message names the *field*, never the value. An error that quoted the
    expected answer it was refusing to publish would publish it.
    """


class VisibilityError(ValidationDatasetError):
    """A visibility policy is malformed or self-contradictory."""


class AccessDeniedError(ValidationDatasetError):
    """This access context may not see this case.

    Carries a reason code and the case identifier, and deliberately nothing
    else. In particular it does not say whether a restricted payload exists,
    because a caller who could tell "denied, and there is an answer" from
    "denied, and there is not" would have learned something from being
    refused.
    """

    def __init__(self, case_id: str, reason_code: str) -> None:
        super().__init__("access refused for %s (%s)" % (case_id, reason_code))
        self.case_id = case_id
        self.reason_code = reason_code


class CompatibilityError(ValidationDatasetError):
    """A release/version compatibility declaration is malformed or unmet."""


class ImportRefusedError(ValidationDatasetError):
    """A restricted import was refused; nothing was written.

    Carries controlled issue codes rather than an underlying exception. The
    exception a filesystem raises may quote a path, and a path is one of the
    things this boundary exists not to disclose.
    """

    def __init__(self, issue_codes: Sequence[str],
                 detail: str = "") -> None:
        codes = tuple(sorted(set(issue_codes)))
        super().__init__("restricted import refused: %s%s"
                         % (", ".join(codes),
                            " (%s)" % detail if detail else ""))
        self.issue_codes = codes
        self.detail = detail
