# -*- coding: utf-8 -*-
"""SQLAlchemy adapters for the WP-10 curation workflow ports.

Repositories and a unit of work, not ORM classes: every mapped class in this
project lives in :mod:`pgx.infrastructure.db.models`, and the boundary test
that asserts it is worth more than the convenience of defining one here.

Three things about this module are load-bearing.

**The guarded update is one statement.** ``guarded_update`` issues::

    UPDATE curation_work_items
       SET status = :new_status, version = version + 1, ...
     WHERE work_item_id = :id
       AND status = :expected_status
       AND version = :expected_version

and returns ``rowcount``. Read-then-write would leave a window in which two
callers both read version 3 and both write version 4; this cannot, because the
predicate is evaluated by the database at write time. The method returns the
count rather than a boolean so the caller can distinguish "somebody moved
first" (0) from "the store is not a keyed table" (more than 1), which are
different problems and should not share an error.

**The append-only repositories have no update method.** Not a private one, not
a disabled one: the method does not exist, so a caller reaching for it gets an
``AttributeError`` at the point of the mistake. Migration 0007's triggers are
what enforce this against a psql session; these classes are what enforce it
against a colleague.

**The audit event is written in the same session as the change.** There is one
session, one transaction, one commit. A failed operation rolls back the work
item, the review and the audit event together, so the trail can never describe
something that did not happen.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from typing import Any, Dict, List, Mapping, Optional, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from pgx.curation.vocabulary import CurationRole
from pgx.curation.workflow.errors import AuditIntegrityError, WorkflowError
from pgx.curation.workflow.models import (WORKFLOW_MODEL_VERSION,
                                          AdjudicationRecord, CurationReview,
                                          CurationRevision, CurationWorkItem,
                                          EvidenceSelectionSnapshot,
                                          ProvenanceVerification,
                                          ReviewDecision)
from pgx.domain.enums import CurationStatus
from pgx.infrastructure.db.models import (AuditEventORM,
                                          CurationAdjudicationORM,
                                          CurationProvenanceVerificationORM,
                                          CurationReviewORM,
                                          CurationRevisionORM,
                                          CurationRoleAssignmentORM,
                                          CurationWorkItemORM)

__all__ = [
    "SqlAlchemyCurationAdjudicationRepository",
    "SqlAlchemyCurationAuditSink",
    "SqlAlchemyCurationProvenanceRepository",
    "SqlAlchemyCurationReviewRepository",
    "SqlAlchemyCurationRevisionRepository",
    "SqlAlchemyCurationWorkItemRepository",
    "SqlAlchemyCurationWorkflowUnitOfWork",
    "SqlAlchemyRoleProvider",
]


# ---------------------------------------------------------------------------
# mapping
# ---------------------------------------------------------------------------

def _work_item_to_domain(row: CurationWorkItemORM) -> CurationWorkItem:
    return CurationWorkItem(
        work_item_id=row.work_item_id,
        status=CurationStatus(row.status),
        version=row.version,
        question_id=row.question_id,
        gene_canonical_key=row.gene_canonical_key,
        drug_canonical_key=row.drug_canonical_key,
        created_at=row.created_at,
        created_by=row.created_by,
        current_revision_id=row.current_revision_id,
        submitted_revision_id=row.submitted_revision_id,
        tags=tuple(row.tags or ()),
        legacy_proposal_id=row.legacy_proposal_id,
        legacy_values=dict(row.legacy_values or {}),
        updated_at=row.updated_at)


def _revision_to_domain(row: CurationRevisionORM) -> CurationRevision:
    evidence = dict(row.evidence or {})
    return CurationRevision(
        work_item_id=row.work_item_id,
        revision_number=row.revision_number,
        parent_revision_id=row.parent_revision_id,
        payload=dict(row.payload or {}),
        protocol_version=row.protocol_version,
        protocol_content_hash=row.protocol_content_hash,
        evidence=EvidenceSelectionSnapshot(
            evidence_record_uuids=tuple(
                evidence.get("evidence_record_uuids") or ()),
            excluded_record_uuids=tuple(
                evidence.get("excluded_record_uuids") or ()),
            evidence_build_key=evidence.get("evidence_build_key", ""),
            evidence_build_content_hash=evidence.get(
                "evidence_build_content_hash", ""),
            dataset_public_id=evidence.get("dataset_public_id", "")),
        authored_by=row.authored_by,
        authored_by_role=CurationRole(row.authored_by_role),
        authored_at=row.authored_at,
        revision_id=row.revision_id,
        workflow_model_version=row.workflow_model_version)


def _review_to_domain(row: CurationReviewORM) -> CurationReview:
    return CurationReview(
        work_item_id=row.work_item_id,
        revision_id=row.revision_id,
        revision_content_hash=row.revision_content_hash,
        decision=ReviewDecision(row.decision),
        reviewed_by=row.reviewed_by,
        reviewed_by_role=CurationRole(row.reviewed_by_role),
        reviewed_at=row.reviewed_at,
        author_actor_id=row.author_actor_id,
        rationale=row.rationale,
        protocol_content_hash=row.protocol_content_hash,
        evidence_build_content_hash=row.evidence_build_content_hash,
        findings=tuple(row.findings or ()),
        review_id=row.review_id)


def _adjudication_to_domain(row: CurationAdjudicationORM) -> AdjudicationRecord:
    return AdjudicationRecord(
        work_item_id=row.work_item_id,
        revision_id=row.revision_id,
        revision_content_hash=row.revision_content_hash,
        adjudicated_by=row.adjudicated_by,
        adjudicated_by_role=CurationRole(row.adjudicated_by_role),
        adjudicated_at=row.adjudicated_at,
        decision=ReviewDecision(row.decision),
        rationale=row.rationale,
        curator_position=dict(row.curator_position or {}),
        reviewer_position=dict(row.reviewer_position or {}),
        disputed_evidence_uuids=tuple(row.disputed_evidence_uuids or ()),
        adjudication_id=row.adjudication_id)


def _provenance_to_domain(
        row: CurationProvenanceVerificationORM) -> ProvenanceVerification:
    return ProvenanceVerification(
        verified_by=row.verified_by,
        verified_by_role=CurationRole(row.verified_by_role),
        verified_at=row.verified_at,
        evidence_record_uuids=tuple(row.evidence_record_uuids or ()),
        all_traces_verified=row.all_traces_verified,
        problems=tuple(row.problems or ()),
        note=row.note or "")


def _next_id(session: Session, model, column, prefix: str) -> str:
    """Allocate the next id in a per-table sequence.

    Derived from the row count under the same transaction rather than from a
    database sequence, so the id a caller sees is the id that is stored - a
    sequence would advance on a rolled-back insert and leave gaps that look
    like deleted records in an append-only table.
    """
    count = session.execute(
        select(func.count()).select_from(model)).scalar_one()
    return "%s%06d" % (prefix, count + 1)


# ---------------------------------------------------------------------------
# repositories
# ---------------------------------------------------------------------------

class SqlAlchemyCurationWorkItemRepository:
    """Work items, with the guarded update as the only state-change path."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, item: CurationWorkItem) -> None:
        self._session.add(CurationWorkItemORM(
            id=uuid.uuid4(),
            work_item_id=item.work_item_id,
            status=item.status.value,
            version=item.version,
            question_id=item.question_id,
            gene_canonical_key=item.gene_canonical_key,
            drug_canonical_key=item.drug_canonical_key,
            current_revision_id=item.current_revision_id,
            submitted_revision_id=item.submitted_revision_id,
            tags=list(item.tags),
            legacy_proposal_id=item.legacy_proposal_id,
            legacy_values=dict(item.legacy_values),
            created_by=item.created_by,
            created_at=item.created_at,
            updated_at=item.updated_at))
        self._session.flush()

    def get(self, work_item_id: str) -> Optional[CurationWorkItem]:
        row = self._session.execute(
            select(CurationWorkItemORM).where(
                CurationWorkItemORM.work_item_id == work_item_id)
        ).scalar_one_or_none()
        return _work_item_to_domain(row) if row else None

    def list_by_status(self, status: CurationStatus,
                       limit: int = 100) -> Sequence[CurationWorkItem]:
        rows = self._session.execute(
            select(CurationWorkItemORM)
            .where(CurationWorkItemORM.status == status.value)
            .order_by(CurationWorkItemORM.work_item_id)
            .limit(limit)).scalars().all()
        return [_work_item_to_domain(row) for row in rows]

    def count_by_status(self) -> Mapping[str, int]:
        rows = self._session.execute(
            select(CurationWorkItemORM.status, func.count())
            .group_by(CurationWorkItemORM.status)).all()
        return {status: count for status, count in rows}

    def guarded_update(self, work_item_id: str, *,
                       expected_status: CurationStatus,
                       expected_version: int,
                       new_status: CurationStatus,
                       current_revision_id: Optional[str] = None,
                       submitted_revision_id: Optional[str] = None,
                       updated_at: Optional[_dt.datetime] = None) -> int:
        """One statement; returns the number of rows it changed.

        The three-part predicate - id, expected status, expected version - is
        what makes "somebody moved first" a fact the database reports rather
        than a race the application loses silently. ``version + 1`` is computed
        by the database for the same reason.
        """
        statement = (
            update(CurationWorkItemORM)
            .where(CurationWorkItemORM.work_item_id == work_item_id,
                   CurationWorkItemORM.status == expected_status.value,
                   CurationWorkItemORM.version == expected_version)
            .values(status=new_status.value,
                    version=CurationWorkItemORM.version + 1,
                    current_revision_id=current_revision_id,
                    submitted_revision_id=submitted_revision_id,
                    updated_at=updated_at or _dt.datetime.now(
                        tz=_dt.timezone.utc))
            .execution_options(synchronize_session=False))
        result = self._session.execute(statement)
        return int(result.rowcount)


class SqlAlchemyCurationRevisionRepository:
    """Append-only. There is no update method, by design."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, revision: CurationRevision) -> str:
        revision_id = revision.revision_id or _next_id(
            self._session, CurationRevisionORM,
            CurationRevisionORM.revision_id, "REV-")
        self._session.add(CurationRevisionORM(
            id=uuid.uuid4(),
            revision_id=revision_id,
            work_item_id=revision.work_item_id,
            revision_number=revision.revision_number,
            parent_revision_id=revision.parent_revision_id,
            payload=dict(revision.payload),
            protocol_version=revision.protocol_version,
            protocol_content_hash=revision.protocol_content_hash,
            evidence=revision.evidence.to_json(),
            evidence_build_content_hash=(
                revision.evidence.evidence_build_content_hash or None),
            authored_by=revision.authored_by,
            authored_by_role=revision.authored_by_role.value,
            authored_at=revision.authored_at,
            content_hash=revision.content_hash(),
            workflow_model_version=revision.workflow_model_version))
        self._session.flush()
        return revision_id

    def get(self, revision_id: str) -> Optional[CurationRevision]:
        row = self._session.execute(
            select(CurationRevisionORM).where(
                CurationRevisionORM.revision_id == revision_id)
        ).scalar_one_or_none()
        return _revision_to_domain(row) if row else None

    def list_for_work_item(self,
                           work_item_id: str) -> Sequence[CurationRevision]:
        rows = self._session.execute(
            select(CurationRevisionORM)
            .where(CurationRevisionORM.work_item_id == work_item_id)
            .order_by(CurationRevisionORM.revision_number)).scalars().all()
        return [_revision_to_domain(row) for row in rows]

    def next_revision_number(self, work_item_id: str) -> int:
        highest = self._session.execute(
            select(func.max(CurationRevisionORM.revision_number))
            .where(CurationRevisionORM.work_item_id == work_item_id)
        ).scalar()
        return int(highest or 0) + 1


class SqlAlchemyCurationReviewRepository:
    """Append-only. No review ever overwrites another."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, review: CurationReview,
            work_item_version: int = 0) -> str:
        review_id = review.review_id or _next_id(
            self._session, CurationReviewORM, CurationReviewORM.review_id,
            "RVW-")
        self._session.add(CurationReviewORM(
            id=uuid.uuid4(),
            review_id=review_id,
            work_item_id=review.work_item_id,
            revision_id=review.revision_id,
            revision_content_hash=review.revision_content_hash,
            decision=review.decision.value,
            reviewed_by=review.reviewed_by,
            reviewed_by_role=review.reviewed_by_role.value,
            reviewed_at=review.reviewed_at,
            author_actor_id=review.author_actor_id,
            rationale=review.rationale,
            findings=list(review.findings),
            protocol_content_hash=review.protocol_content_hash,
            evidence_build_content_hash=review.evidence_build_content_hash,
            work_item_version=work_item_version,
            content_hash=review.content_hash()))
        self._session.flush()
        return review_id

    def list_for_work_item(self,
                           work_item_id: str) -> Sequence[CurationReview]:
        rows = self._session.execute(
            select(CurationReviewORM)
            .where(CurationReviewORM.work_item_id == work_item_id)
            .order_by(CurationReviewORM.reviewed_at,
                      CurationReviewORM.review_id)).scalars().all()
        return [_review_to_domain(row) for row in rows]

    def list_for_revision(self, revision_id: str) -> Sequence[CurationReview]:
        rows = self._session.execute(
            select(CurationReviewORM)
            .where(CurationReviewORM.revision_id == revision_id)
            .order_by(CurationReviewORM.reviewed_at,
                      CurationReviewORM.review_id)).scalars().all()
        return [_review_to_domain(row) for row in rows]


class SqlAlchemyCurationAdjudicationRepository:
    """Append-only. Both positions are stored in full."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, record: AdjudicationRecord,
            work_item_version: int = 0) -> str:
        adjudication_id = record.adjudication_id or _next_id(
            self._session, CurationAdjudicationORM,
            CurationAdjudicationORM.adjudication_id, "ADJ-")
        self._session.add(CurationAdjudicationORM(
            id=uuid.uuid4(),
            adjudication_id=adjudication_id,
            work_item_id=record.work_item_id,
            revision_id=record.revision_id,
            revision_content_hash=record.revision_content_hash,
            adjudicated_by=record.adjudicated_by,
            adjudicated_by_role=record.adjudicated_by_role.value,
            adjudicated_at=record.adjudicated_at,
            decision=record.decision.value,
            rationale=record.rationale,
            curator_actor_id=str(record.curator_position.get("actor_id") or ""),
            reviewer_actor_id=str(
                record.reviewer_position.get("actor_id") or ""),
            curator_position=dict(record.curator_position),
            reviewer_position=dict(record.reviewer_position),
            disputed_evidence_uuids=list(record.disputed_evidence_uuids),
            work_item_version=work_item_version,
            content_hash=record.content_hash()))
        self._session.flush()
        return adjudication_id

    def list_for_work_item(self,
                           work_item_id: str) -> Sequence[AdjudicationRecord]:
        rows = self._session.execute(
            select(CurationAdjudicationORM)
            .where(CurationAdjudicationORM.work_item_id == work_item_id)
            .order_by(CurationAdjudicationORM.adjudicated_at)).scalars().all()
        return [_adjudication_to_domain(row) for row in rows]


class SqlAlchemyCurationProvenanceRepository:
    """Append-only steward verifications."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, verification: ProvenanceVerification,
            work_item_id: str = "") -> str:
        verification_id = _next_id(
            self._session, CurationProvenanceVerificationORM,
            CurationProvenanceVerificationORM.verification_id, "PRV-")
        self._session.add(CurationProvenanceVerificationORM(
            id=uuid.uuid4(),
            verification_id=verification_id,
            work_item_id=work_item_id,
            verified_by=verification.verified_by,
            verified_by_role=verification.verified_by_role.value,
            verified_at=verification.verified_at,
            evidence_record_uuids=list(verification.evidence_record_uuids),
            all_traces_verified=verification.all_traces_verified,
            problems=list(verification.problems),
            note=verification.note or None))
        self._session.flush()
        return verification_id

    def latest_for_work_item(
            self, work_item_id: str) -> Optional[ProvenanceVerification]:
        row = self._session.execute(
            select(CurationProvenanceVerificationORM)
            .where(CurationProvenanceVerificationORM.work_item_id
                   == work_item_id)
            .order_by(CurationProvenanceVerificationORM.verified_at.desc())
            .limit(1)).scalar_one_or_none()
        return _provenance_to_domain(row) if row else None


class SqlAlchemyCurationAuditSink:
    """Append-only audit events, written in the caller's transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, *, action: str, actor: str, object_type: str,
               object_id: str, occurred_at: _dt.datetime,
               reason: Optional[str] = None,
               metadata: Optional[Mapping[str, Any]] = None) -> str:
        event_id = uuid.uuid4()
        self._session.add(AuditEventORM(
            id=event_id, action=action, actor=actor,
            object_type=object_type, object_id=object_id,
            occurred_at=occurred_at, reason=reason,
            event_metadata=dict(metadata or {})))
        self._session.flush()
        return str(event_id)


class SqlAlchemyRoleProvider:
    """Roles read from ``curation_role_assignments``.

    In this repository that table is empty, so every lookup raises and no
    workflow operation can be performed against the real database. That is the
    correct behaviour, not a gap: there is nobody to assign a role to until
    WP-23 provides authenticated identities, and a provider that invented one
    would be the security hole this design exists to avoid.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def _assignments(self, actor_id: str) -> List[CurationRoleAssignmentORM]:
        return list(self._session.execute(
            select(CurationRoleAssignmentORM)
            .where(CurationRoleAssignmentORM.actor_id == actor_id)
        ).scalars().all())

    def is_empty(self) -> bool:
        return self._session.execute(
            select(func.count()).select_from(CurationRoleAssignmentORM)
        ).scalar_one() == 0

    def for_actor(self, actor_id: str):
        from pgx.curation.workflow.roles import StaticRoleProvider
        rows = self._assignments(actor_id)
        assignments = {
            actor_id: frozenset(CurationRole(row.role) for row in rows)
        } if rows else {}
        provider = StaticRoleProvider(assignments)
        return provider.for_actor(actor_id)


# ---------------------------------------------------------------------------
# unit of work
# ---------------------------------------------------------------------------

class SqlAlchemyCurationWorkflowUnitOfWork:
    """One session, one transaction, one commit.

    Rollback is the default: leaving the context without ``commit()`` rolls
    back, so a failed operation cannot leave a work-item change without its
    review, or an audit event without the thing it describes.
    """

    def __init__(self, session_factory: "sessionmaker[Session]") -> None:
        self._session_factory = session_factory
        self._session: Optional[Session] = None
        self._committed = False

    def __enter__(self) -> "SqlAlchemyCurationWorkflowUnitOfWork":
        self._session = self._session_factory()
        self._committed = False
        self.work_items = SqlAlchemyCurationWorkItemRepository(self._session)
        self.revisions = SqlAlchemyCurationRevisionRepository(self._session)
        self.reviews = SqlAlchemyCurationReviewRepository(self._session)
        self.adjudications = SqlAlchemyCurationAdjudicationRepository(
            self._session)
        self.provenance = SqlAlchemyCurationProvenanceRepository(self._session)
        self.audit = SqlAlchemyCurationAuditSink(self._session)
        self.roles = SqlAlchemyRoleProvider(self._session)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if not self._committed:
                self.rollback()
        finally:
            if self._session is not None:
                self._session.close()
                self._session = None

    @property
    def session(self) -> Session:
        if self._session is None:
            raise RuntimeError(
                "SqlAlchemyCurationWorkflowUnitOfWork must be used as a "
                "context manager")
        return self._session

    def commit(self) -> None:
        self.session.commit()
        self._committed = True

    def rollback(self) -> None:
        if self._session is not None:
            self._session.rollback()
