# -*- coding: utf-8 -*-
"""Failures the expert-review workflow raises (WP-22).

One base class and a handful of specific types, each carrying a stable code
from :data:`~pgx.expert_review.vocabulary.REVIEW_ERROR_CODES`.

Two rules every message in this module obeys, because these strings are logged
and returned to callers:

- **No expert content.** Never an expected response, a rationale, a decision
  or a rating. The whole point of the blinded record is that it is not
  readable by the wrong party at the wrong time, and an error message that
  quoted it would be the easiest possible leak.
- **No case-existence signal.** ``NotAssignedError`` reads the same whether
  the case is unknown, exists but is not expert-holdout, or exists and belongs
  to a different reviewer. A caller who could distinguish those three has been
  handed a lookup tool for the holdout set.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from pgx.expert_review.vocabulary import REVIEW_ERROR_CODES

__all__ = [
    "AuditChainError",
    "ExpertReviewError",
    "InvalidTransitionError",
    "NotAssignedError",
    "PermitError",
    "PinMismatchError",
    "ProtocolNotApprovedError",
    "ReviewUnavailableError",
    "ForgedFieldError",
]


class ExpertReviewError(Exception):
    """Base class. Always carries a code the API and CLI can map."""

    default_code = "EXPERT_REVIEW_NOT_AVAILABLE"

    def __init__(self, message: str = "", *, code: Optional[str] = None,
                 details: Optional[Mapping[str, Any]] = None) -> None:
        self.code = code or self.default_code
        if self.code not in REVIEW_ERROR_CODES:
            raise ValueError("unknown expert-review error code %r" % self.code)
        self.details = dict(details or {})
        super().__init__(message or REVIEW_ERROR_CODES[self.code])

    def to_json(self) -> Mapping[str, Any]:
        return {"code": self.code, "meaning": REVIEW_ERROR_CODES[self.code],
                "details": dict(self.details)}


class ReviewUnavailableError(ExpertReviewError):
    """The service, its store or a dependency is absent.

    The default state of this repository. Distinct from every other error
    here: it says nothing about any case or reviewer, because nothing was
    consulted.
    """

    default_code = "EXPERT_REVIEW_NOT_AVAILABLE"


class NotAssignedError(ExpertReviewError):
    """No active assignment for this actor and case.

    Deliberately the same error for "no such case", "not an expert-holdout
    case" and "assigned to somebody else". Three codes here would let anyone
    with reviewer credentials enumerate the holdout set by probing.
    """

    default_code = "EXPERT_REVIEW_NOT_ASSIGNED"


class ProtocolNotApprovedError(ExpertReviewError):
    """The protocol is not approved, so no review may proceed.

    This repository's permanent state until named humans approve
    ``docs/validation/expert-protocol.md``. Raised before anything is read or
    written, so an unapproved protocol cannot produce a partial record.
    """

    default_code = "EXPERT_REVIEW_PROTOCOL_NOT_APPROVED"


class InvalidTransitionError(ExpertReviewError):
    """The requested move is not permitted from the current state."""

    default_code = "EXPERT_REVIEW_INVALID_TRANSITION"


class PinMismatchError(ExpertReviewError):
    """A pinned identity no longer matches.

    The release moved, the case manifest changed, or the protocol hash
    differs. Any of the three means the review is now measuring something
    other than what it began measuring, so it is refused rather than
    continued.
    """

    default_code = "EXPERT_REVIEW_RELEASE_MISMATCH"


class PermitError(ExpertReviewError):
    """No assignment-scoped permit authorises this payload read."""

    default_code = "EXPERT_REVIEW_PERMIT_INVALID"


class ForgedFieldError(ExpertReviewError):
    """The request supplied a field the server owns.

    Actor, role, timestamps, status, hashes and audit metadata all come from
    the server-side principal and the pinned assignment. A request carrying
    any of them is refused outright rather than having them stripped: a caller
    who tried to set their own timestamp has told you something, and silently
    ignoring it loses that.
    """

    default_code = "EXPERT_REVIEW_FORGED_FIELD"


class AuditChainError(ExpertReviewError):
    """The audit chain is broken, or an event could not be appended.

    Raised on append failure *and* on verification failure. Both mean the same
    thing operationally: the record of what happened cannot be trusted, so the
    governed action it accompanies must not stand.
    """

    default_code = "EXPERT_REVIEW_AUDIT_FAILED"
