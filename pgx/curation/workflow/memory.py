# -*- coding: utf-8 -*-
"""An in-memory unit of work for the curation workflow (WP-10).

Not a test double bolted on afterwards - it is the reference implementation of
the ports, and it is what makes the service exercisable in an environment with
no database driver. Every rule the SQLAlchemy adapter delegates to PostgreSQL
is enforced here in Python, so the two can be compared:

* revisions, reviews and adjudications are **append-only** - there is no
  update or delete method to call;
* ``guarded_update`` matches on id, status and version together and returns an
  affected-row count, exactly as the SQL does;
* a failed operation rolls back the work items, the appended rows **and** the
  audit events together, because the audit list participates in the same
  snapshot.

The rollback is real rather than nominal: entering the unit of work snapshots
every collection, and ``__exit__`` without a commit restores them. A store
that dropped only the work-item change on failure would leave an audit event
describing something that did not happen.
"""

from __future__ import annotations

import copy
import datetime as _dt
import itertools
from typing import (Any, Dict, List, Mapping, Optional, Sequence)

from pgx.curation.workflow.errors import ImmutableRevisionError, WorkflowError
from pgx.curation.workflow.models import (AdjudicationRecord, CurationRevision,
                                          CurationReview, CurationWorkItem)
from pgx.domain.enums import CurationStatus

__all__ = ["InMemoryWorkflowStore", "InMemoryWorkflowUnitOfWork"]


class InMemoryWorkflowStore:
    """The shared state several units of work operate on."""

    def __init__(self) -> None:
        self.work_items: Dict[str, CurationWorkItem] = {}
        self.revisions: Dict[str, CurationRevision] = {}
        self.reviews: Dict[str, CurationReview] = {}
        self.adjudications: Dict[str, AdjudicationRecord] = {}
        self.provenance: Dict[str, Any] = {}
        # The work-item version each decision was taken at. Kept beside the
        # record rather than inside it: the version is a fact about the
        # transaction, not part of the scientific claim, so it must not enter
        # the content hash.
        self.review_versions: Dict[str, int] = {}
        self.adjudication_versions: Dict[str, int] = {}
        self.audit: List[Dict[str, Any]] = []
        self._ids = itertools.count(1)

    def next_id(self, prefix: str) -> str:
        return "%s-%06d" % (prefix, next(self._ids))

    def snapshot(self) -> Dict[str, Any]:
        return {
            "work_items": dict(self.work_items),
            "revisions": dict(self.revisions),
            "reviews": dict(self.reviews),
            "adjudications": dict(self.adjudications),
            "provenance": dict(self.provenance),
            "review_versions": dict(self.review_versions),
            "adjudication_versions": dict(self.adjudication_versions),
            "audit": list(self.audit),
        }

    def restore(self, snapshot: Mapping[str, Any]) -> None:
        self.work_items = dict(snapshot["work_items"])
        self.revisions = dict(snapshot["revisions"])
        self.reviews = dict(snapshot["reviews"])
        self.adjudications = dict(snapshot["adjudications"])
        self.provenance = dict(snapshot["provenance"])
        self.review_versions = dict(snapshot["review_versions"])
        self.adjudication_versions = dict(snapshot["adjudication_versions"])
        self.audit = list(snapshot["audit"])


class _WorkItems:
    def __init__(self, store: InMemoryWorkflowStore) -> None:
        self._store = store

    def add(self, item: CurationWorkItem) -> None:
        if item.work_item_id in self._store.work_items:
            raise WorkflowError(
                "work item %s already exists; add never overwrites"
                % item.work_item_id)
        self._store.work_items[item.work_item_id] = item

    def get(self, work_item_id: str) -> Optional[CurationWorkItem]:
        return self._store.work_items.get(work_item_id)

    def list_by_status(self, status: CurationStatus,
                       limit: Optional[int] = None) -> Sequence[CurationWorkItem]:
        rows = sorted((item for item in self._store.work_items.values()
                       if item.status is status),
                      key=lambda item: item.work_item_id)
        return rows if not limit else rows[:limit]

    def count_by_status(self) -> Mapping[str, int]:
        counts: Dict[str, int] = {}
        for item in self._store.work_items.values():
            counts[item.status.value] = counts.get(item.status.value, 0) + 1
        return dict(sorted(counts.items()))

    def guarded_update(self, work_item_id: str, *,
                       expected_status: CurationStatus, expected_version: int,
                       new_status: CurationStatus,
                       current_revision_id: Optional[str] = None,
                       submitted_revision_id: Optional[str] = None,
                       updated_at: Optional[_dt.datetime] = None) -> int:
        """Match on id, status and version together; report rows affected.

        The same three-part predicate the SQL uses. Zero means the caller's
        view is stale, and saying so with a count rather than an exception is
        what lets the service distinguish "somebody moved first" from "the
        store is broken".
        """
        item = self._store.work_items.get(work_item_id)
        if item is None:
            return 0
        if item.status is not expected_status or item.version != expected_version:
            return 0
        self._store.work_items[work_item_id] = CurationWorkItem(
            work_item_id=item.work_item_id, status=new_status,
            version=item.version + 1, question_id=item.question_id,
            gene_canonical_key=item.gene_canonical_key,
            drug_canonical_key=item.drug_canonical_key,
            created_at=item.created_at, created_by=item.created_by,
            current_revision_id=(current_revision_id
                                 if current_revision_id is not None
                                 else item.current_revision_id),
            submitted_revision_id=submitted_revision_id,
            tags=item.tags, legacy_proposal_id=item.legacy_proposal_id,
            legacy_values=item.legacy_values,
            updated_at=updated_at or item.updated_at)
        return 1


class _Revisions:
    def __init__(self, store: InMemoryWorkflowStore) -> None:
        self._store = store

    def add(self, revision: CurationRevision) -> str:
        key = (revision.work_item_id, revision.revision_number)
        for existing in self._store.revisions.values():
            if (existing.work_item_id, existing.revision_number) == key:
                raise ImmutableRevisionError(
                    "revision %d of %s already exists; revisions are appended, "
                    "never replaced" % key[::-1])
        revision_id = self._store.next_id("REV")
        self._store.revisions[revision_id] = CurationRevision(
            work_item_id=revision.work_item_id,
            revision_number=revision.revision_number,
            parent_revision_id=revision.parent_revision_id,
            payload=revision.payload,
            protocol_version=revision.protocol_version,
            protocol_content_hash=revision.protocol_content_hash,
            evidence=revision.evidence, authored_by=revision.authored_by,
            authored_by_role=revision.authored_by_role,
            authored_at=revision.authored_at, revision_id=revision_id)
        return revision_id

    def get(self, revision_id: str) -> Optional[CurationRevision]:
        return self._store.revisions.get(revision_id)

    def list_for_work_item(self, work_item_id: str
                           ) -> Sequence[CurationRevision]:
        return sorted((item for item in self._store.revisions.values()
                       if item.work_item_id == work_item_id),
                      key=lambda item: item.revision_number)

    def next_revision_number(self, work_item_id: str) -> int:
        existing = self.list_for_work_item(work_item_id)
        return (existing[-1].revision_number + 1) if existing else 1


class _Reviews:
    def __init__(self, store: InMemoryWorkflowStore) -> None:
        self._store = store

    def add(self, review: CurationReview,
            work_item_version: int = 0) -> str:
        review_id = self._store.next_id("REVIEW")
        self._store.review_versions[review_id] = work_item_version
        self._store.reviews[review_id] = CurationReview(
            work_item_id=review.work_item_id, revision_id=review.revision_id,
            revision_content_hash=review.revision_content_hash,
            decision=review.decision, reviewed_by=review.reviewed_by,
            reviewed_by_role=review.reviewed_by_role,
            reviewed_at=review.reviewed_at,
            author_actor_id=review.author_actor_id,
            rationale=review.rationale,
            protocol_content_hash=review.protocol_content_hash,
            evidence_build_content_hash=review.evidence_build_content_hash,
            findings=review.findings, review_id=review_id)
        return review_id

    def list_for_work_item(self, work_item_id: str) -> Sequence[CurationReview]:
        return sorted((item for item in self._store.reviews.values()
                       if item.work_item_id == work_item_id),
                      key=lambda item: item.reviewed_at)

    def list_for_revision(self, revision_id: str) -> Sequence[CurationReview]:
        return sorted((item for item in self._store.reviews.values()
                       if item.revision_id == revision_id),
                      key=lambda item: item.reviewed_at)


class _Adjudications:
    def __init__(self, store: InMemoryWorkflowStore) -> None:
        self._store = store

    def add(self, record: AdjudicationRecord,
            work_item_version: int = 0) -> str:
        adjudication_id = self._store.next_id("ADJ")
        self._store.adjudications[adjudication_id] = record
        self._store.adjudication_versions[adjudication_id] = work_item_version
        return adjudication_id

    def list_for_work_item(self, work_item_id: str
                           ) -> Sequence[AdjudicationRecord]:
        return sorted((item for item in self._store.adjudications.values()
                       if item.work_item_id == work_item_id),
                      key=lambda item: item.adjudicated_at)


class _Provenance:
    def __init__(self, store: InMemoryWorkflowStore) -> None:
        self._store = store

    def add(self, verification: Any, work_item_id: str = "") -> str:
        key = self._store.next_id("PROV")
        # Stored against the work item it verifies. An earlier version kept
        # only the verification and returned the most recent one for every
        # query, which meant a steward verifying item A opened the trace gate
        # on item B - the exact cross-contamination the gates exist to catch.
        self._store.provenance[key] = (work_item_id, verification)
        return key

    def latest_for_work_item(self, work_item_id: str) -> Optional[Any]:
        rows = [record for owner, record in self._store.provenance.values()
                if owner == work_item_id]
        return rows[-1] if rows else None


class _Audit:
    def __init__(self, store: InMemoryWorkflowStore) -> None:
        self._store = store

    def record(self, *, action: str, actor: str, object_type: str,
               object_id: str, occurred_at: _dt.datetime,
               reason: Optional[str] = None,
               metadata: Optional[Mapping[str, Any]] = None) -> str:
        event_id = self._store.next_id("AUDIT")
        self._store.audit.append({
            "audit_event_id": event_id, "action": action, "actor": actor,
            "object_type": object_type, "object_id": object_id,
            "occurred_at": occurred_at.isoformat().replace("+00:00", "Z"),
            "reason": reason, "metadata": dict(metadata or {}),
        })
        return event_id


class InMemoryWorkflowUnitOfWork:
    """One transaction over an :class:`InMemoryWorkflowStore`.

    Rollback restores the snapshot taken on entry, so a failed operation
    leaves no work-item change, no appended row and **no audit event**. The
    audit list is part of the snapshot for exactly that reason.
    """

    def __init__(self, store: InMemoryWorkflowStore) -> None:
        self._store = store
        self._snapshot: Optional[Mapping[str, Any]] = None
        self._committed = False
        self.work_items = _WorkItems(store)
        self.revisions = _Revisions(store)
        self.reviews = _Reviews(store)
        self.adjudications = _Adjudications(store)
        self.provenance = _Provenance(store)
        self.audit = _Audit(store)

    def __enter__(self) -> "InMemoryWorkflowUnitOfWork":
        self._snapshot = self._store.snapshot()
        self._committed = False
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self._committed:
            self.rollback()

    def commit(self) -> None:
        self._committed = True
        self._snapshot = None

    def rollback(self) -> None:
        if self._snapshot is not None:
            self._store.restore(self._snapshot)
            self._snapshot = None
