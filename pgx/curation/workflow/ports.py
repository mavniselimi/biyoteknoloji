# -*- coding: utf-8 -*-
"""Persistence ports for the curation workflow (WP-10).

Protocols only. No implementation type appears in any signature, so the
service can be exercised against an in-memory unit of work and against
SQLAlchemy without knowing which it has.

Two shapes deserve comment.

``CurationWorkItemRepository.guarded_update`` returns an **affected row count**
rather than raising or returning the row. That is the optimistic-concurrency
primitive: the caller asserts an expected status and version, and the store
reports how many rows matched. Exactly one means the caller's view was
current; zero means somebody else moved first. A repository that returned the
row instead would have to decide what "somebody else moved first" means, and
that decision belongs to the service.

The revision, review and adjudication repositories offer ``add`` and reads,
and **no update or delete**. Append-only is expressed by the absence of the
method, not by a comment asking callers not to.
"""

from __future__ import annotations

import datetime as _dt
from typing import (Any, Mapping, Optional, Protocol, Sequence,
                    runtime_checkable)

from pgx.curation.workflow.models import (AdjudicationRecord, CurationRevision,
                                          CurationReview, CurationWorkItem)
from pgx.domain.enums import CurationStatus

__all__ = [
    "AuditSink",
    "CurationAdjudicationRepository",
    "CurationRevisionRepository",
    "CurationReviewRepository",
    "CurationWorkItemRepository",
    "CurationWorkflowUnitOfWork",
    "ProvenanceVerificationRepository",
]


@runtime_checkable
class CurationWorkItemRepository(Protocol):
    """Work items, with guarded state changes."""

    def add(self, item: CurationWorkItem) -> None:
        """Insert a new work item. Never used to overwrite an existing one."""

    def get(self, work_item_id: str) -> Optional[CurationWorkItem]:
        """One work item, or None."""

    def list_by_status(self, status: CurationStatus,
                       limit: Optional[int] = None) -> Sequence[CurationWorkItem]:
        """Work items in one state, in a deterministic order."""

    def count_by_status(self) -> Mapping[str, int]:
        """How many work items are in each state."""

    def guarded_update(self, work_item_id: str, *,
                       expected_status: CurationStatus, expected_version: int,
                       new_status: CurationStatus,
                       current_revision_id: Optional[str] = None,
                       submitted_revision_id: Optional[str] = None,
                       updated_at: Optional[_dt.datetime] = None) -> int:
        """Move one work item, returning the number of rows affected.

        The store must match on id, status **and** version together, and
        increment the version. Returning 0 is the store saying the caller's
        view is stale - which is a fact, not an error, and the service decides
        what to do about it.
        """


@runtime_checkable
class CurationRevisionRepository(Protocol):
    """Immutable revisions. No update, no delete."""

    def add(self, revision: CurationRevision) -> str:
        """Store a revision and return its assigned id."""

    def get(self, revision_id: str) -> Optional[CurationRevision]:
        """One revision, or None."""

    def list_for_work_item(self, work_item_id: str
                           ) -> Sequence[CurationRevision]:
        """Every revision of one work item, oldest first."""

    def next_revision_number(self, work_item_id: str) -> int:
        """What the next revision of this item would be numbered."""


@runtime_checkable
class CurationReviewRepository(Protocol):
    """Immutable reviews. No review overwrites another."""

    def add(self, review: CurationReview,
            work_item_version: int = 0) -> str:
        """Store a review and return its assigned id."""

    def list_for_work_item(self, work_item_id: str
                           ) -> Sequence[CurationReview]:
        """Every review of one work item, oldest first."""

    def list_for_revision(self, revision_id: str) -> Sequence[CurationReview]:
        """Every review of one revision - plural, deliberately."""


@runtime_checkable
class CurationAdjudicationRepository(Protocol):
    """Immutable adjudications, each preserving both original positions."""

    def add(self, record: AdjudicationRecord,
            work_item_version: int = 0) -> str:
        """Store an adjudication and return its assigned id."""

    def list_for_work_item(self, work_item_id: str) -> Sequence[Any]:
        """Every adjudication of one work item, oldest first."""


@runtime_checkable
class ProvenanceVerificationRepository(Protocol):
    """Steward verifications of an evidence selection."""

    def add(self, verification: Any,
            work_item_id: str = "") -> str:
        """Store a verification and return its assigned id."""

    def latest_for_work_item(self, work_item_id: str) -> Optional[Any]:
        """The most recent verification, or None."""


@runtime_checkable
class AuditSink(Protocol):
    """Where workflow audit events go.

    Append-only by construction: one method, and it adds. The event is written
    inside the same unit of work as the change it describes, so a committed
    change without its event is not a state this design can reach.
    """

    def record(self, *, action: str, actor: str, object_type: str,
               object_id: str, occurred_at: _dt.datetime,
               reason: Optional[str] = None,
               metadata: Optional[Mapping[str, Any]] = None) -> str:
        """Append one event and return its id."""


@runtime_checkable
class CurationWorkflowUnitOfWork(Protocol):
    """One transaction spanning every workflow repository.

    The point of gathering them is atomicity: a review, the work-item move it
    caused and the audit event recording it either all commit or none do. A
    service that used separate transactions could leave a decided review with
    no state change, or a state change nobody can account for.
    """

    work_items: CurationWorkItemRepository
    revisions: CurationRevisionRepository
    reviews: CurationReviewRepository
    adjudications: CurationAdjudicationRepository
    provenance: ProvenanceVerificationRepository
    audit: AuditSink

    def __enter__(self) -> "CurationWorkflowUnitOfWork": ...

    def __exit__(self, exc_type, exc, tb) -> None: ...

    def commit(self) -> None:
        """Commit every change made in this unit of work."""

    def rollback(self) -> None:
        """Discard every change made in this unit of work."""
