# -*- coding: utf-8 -*-
"""Failures the curation workflow raises (WP-10).

Separate types because the callers differ and the remedies differ. A stale
version is retried; a role violation is not. A closed gate is a fact about the
world that no amount of retrying changes.

Every one of these carries enough structure for a CLI or a form to render the
reason without re-deriving it, because a workflow that refuses without saying
precisely why trains its users to work around it.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

__all__ = [
    "ActorError",
    "AuditIntegrityError",
    "ConcurrencyError",
    "GateBlockedError",
    "ImmutableRevisionError",
    "InvalidTransitionError",
    "RoleViolationError",
    "RuleApprovalError",
    "WorkflowError",
]


class WorkflowError(Exception):
    """Base class for every WP-10 failure."""


class InvalidTransitionError(WorkflowError):
    """The requested transition is not one this state allows.

    Carries the states so a caller can say "this item is UNDER_REVIEW, you
    asked to submit it" rather than only "invalid".
    """

    def __init__(self, message: str, current: Optional[str] = None,
                 requested: Optional[str] = None) -> None:
        super().__init__(message)
        self.current = current
        self.requested = requested


class ImmutableRevisionError(WorkflowError):
    """Something tried to change a revision, review or adjudication that is
    already part of the record.

    A submitted revision is what a reviewer read. Editing it afterwards would
    make every review of it a review of something that no longer exists.
    """


class ConcurrencyError(WorkflowError):
    """The work item changed since the caller last read it.

    Carries both versions so a form can tell the user their copy is stale
    rather than that their decision was wrong.
    """

    def __init__(self, message: str, expected_version: Optional[int] = None,
                 actual_version: Optional[int] = None,
                 expected_status: Optional[str] = None,
                 actual_status: Optional[str] = None) -> None:
        super().__init__(message)
        self.expected_version = expected_version
        self.actual_version = actual_version
        self.expected_status = expected_status
        self.actual_status = actual_status


class RoleViolationError(WorkflowError):
    """The actor's role does not permit this act, or separation was breached.

    Raised for both "an engineering observer cannot approve science" and "the
    author cannot review their own conclusion". They are the same failure seen
    from two angles: somebody is standing in for a check they are the subject
    of.
    """


class ActorError(WorkflowError):
    """The actor is unidentified, or its roles were not supplied by a provider.

    A role that arrived as an argument is not an authorisation. This is raised
    when one tries to.
    """


class GateBlockedError(WorkflowError):
    """One or more approval gates are closed.

    Carries every closed gate rather than the first, because an operator
    fixing them needs the whole list - and because "the protocol is
    unapproved" and "the evidence is quarantined" are different problems with
    different owners.
    """

    def __init__(self, message: str,
                 blocked: Sequence[Mapping[str, Any]] = ()) -> None:
        super().__init__(message)
        self.blocked = tuple(blocked)

    @property
    def codes(self):
        return tuple(str(item.get("code")) for item in self.blocked)


class AuditIntegrityError(WorkflowError):
    """An operation would have changed state without recording that it did.

    Raised by the service rather than discovered later: an audit trail with a
    hole in it is worse than none, because it looks complete.
    """


class RuleApprovalError(WorkflowError):
    """A rule-approval envelope is incomplete or violates separation.

    WP-10 validates envelopes; it creates no rule. This is raised when an
    envelope could not govern one.
    """

    def __init__(self, message: str, missing: Sequence[str] = (),
                 violations: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.missing = tuple(missing)
        self.violations = tuple(violations)
