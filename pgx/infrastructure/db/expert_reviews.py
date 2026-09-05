# -*- coding: utf-8 -*-
"""WP-22 expert review persistence: seven append-only tables.

The decomposition follows the protocol's phases rather than convenience,
because each phase's record answers a different evidential question and
merging two would let one be edited under cover of the other:

| Table | Answers |
|---|---|
| ``expert_review_assignments`` | who was asked to review what, under which release and protocol |
| ``expert_review_expectations`` | what they predicted, and exactly when |
| ``expert_review_reveals`` | what they were shown, and which prediction it was pinned to |
| ``expert_review_completions`` | what they concluded afterwards |
| ``expert_review_ratings`` | optional structured scores |
| ``expert_review_corrections`` | every amendment, appended |
| ``expert_review_audit_events`` | the chained record of every act |

**Every table is append-only**, enforced by a trigger in the migration rather
than by discipline here. The repository below has no update and no delete
method: a store that offered one would make immutability something the service
must remember instead of something the schema cannot express.

**No payload is copied here.** The tables hold identifiers, hashes, controlled
vocabulary values and bounded notes. A case's inputs stay in restricted
storage; copying them into a review table would put holdout material in a
database that reviewers, auditors and operators all reach.

**PostgreSQL is unavailable in this environment.** The mappings, constraints
and migration are written and unit-tested against the metadata; no statement
has been executed against a server, and nothing here claims otherwise.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy import (Boolean, CheckConstraint, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from pgx.expert_review.vocabulary import (CORRECTION_KINDS, DECISION_VALUES,
                                          INVALIDATION_REASONS,
                                          LIKERT_DIMENSIONS, LIKERT_MAXIMUM,
                                          LIKERT_MINIMUM, RATIONALE_CODES,
                                          ReviewState)
from pgx.infrastructure.db.base import Base
from pgx.infrastructure.db.models import SHA256_DIGEST_REGEX, _in_list, _uuid_pk

__all__ = [
    "EXPERT_REVIEW_AUDIT_ACTIONS",
    "EXPERT_REVIEW_TABLES",
    "ExpertReviewAssignmentRow",
    "ExpertReviewAuditEventRow",
    "ExpertReviewCompletionRow",
    "ExpertReviewCorrectionRow",
    "ExpertReviewExpectationRow",
    "ExpertReviewRatingRow",
    "ExpertReviewRevealRow",
    "SqlAlchemyExpertReviewRepository",
]

_STATES: Tuple[str, ...] = tuple(item.value for item in ReviewState)

#: The audit actions this work package writes. Named so the migration's
#: check constraint and the service agree by construction.
EXPERT_REVIEW_AUDIT_ACTIONS: Tuple[str, ...] = (
    "REVIEW_ASSIGNED", "REVIEW_EXPECTATION_RECORDED", "REVIEW_RESULT_REVEALED",
    "REVIEW_COMPLETED", "REVIEW_INVALIDATED", "REVIEW_CORRECTION_APPENDED",
    "REVIEW_PERMIT_ISSUED", "REVIEW_PERMIT_REFUSED",
)

EXPERT_REVIEW_TABLES: Tuple[str, ...] = (
    "expert_review_assignments", "expert_review_expectations",
    "expert_review_reveals", "expert_review_completions",
    "expert_review_ratings", "expert_review_corrections",
    "expert_review_audit_events",
)


def _digest(name: str) -> CheckConstraint:
    return CheckConstraint("%s ~ '%s'" % (name, SHA256_DIGEST_REGEX),
                           name="%s_format" % name)


class ExpertReviewAssignmentRow(Base):
    """One reviewer, one case, one release, one protocol.

    ``state`` is a column and the only one in these tables that a later
    statement changes - a transition is a state move, and the migration's
    trigger permits exactly that one column to change and only forwards.
    Everything else about an assignment is fixed at creation.
    """

    __tablename__ = "expert_review_assignments"

    id: Mapped[uuid.UUID] = _uuid_pk()
    assignment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    review_id: Mapped[str] = mapped_column(String(128), nullable=False)
    case_id: Mapped[str] = mapped_column(String(128), nullable=False)
    case_role: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewer_actor: Mapped[str] = mapped_column(String(256), nullable=False)
    reviewer_role: Mapped[str] = mapped_column(String(48), nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(128), nullable=False)
    protocol_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    release_public_id: Mapped[str] = mapped_column(String(128), nullable=False)
    release_manifest_hash: Mapped[str] = mapped_column(String(80),
                                                       nullable=False)
    software_version: Mapped[str] = mapped_column(String(128), nullable=False)
    software_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    dataset_public_id: Mapped[str] = mapped_column(String(128), nullable=False)
    dataset_content_hash: Mapped[str] = mapped_column(String(80),
                                                      nullable=False)
    ruleset_public_id: Mapped[str] = mapped_column(String(128), nullable=False)
    ruleset_content_hash: Mapped[str] = mapped_column(String(80),
                                                      nullable=False)
    case_manifest_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    assigned_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)
    invalidation_reason: Mapped[Optional[str]] = mapped_column(String(48),
                                                               nullable=True)

    __table_args__ = (
        UniqueConstraint("assignment_id", name="assignment_id"),
        UniqueConstraint("review_id", name="review_id"),
        # One live assignment per reviewer, case and release. A second would
        # let the same person review the same case twice under one release,
        # and two independent-looking opinions from one reviewer is exactly
        # the thing a blind protocol must not produce.
        UniqueConstraint("case_id", "reviewer_actor", "release_public_id",
                         name="case_reviewer_release"),
        # Only EXPERT_HOLDOUT is assignable. Development cases shaped the
        # software; internal holdout belongs to a different protocol.
        CheckConstraint("case_role = 'EXPERT_HOLDOUT'",
                        name="case_role_is_expert_holdout"),
        # Exactly the reviewer role. ADMIN does not imply it here either.
        CheckConstraint("reviewer_role = 'EXPERT_REVIEWER'",
                        name="reviewer_role_is_expert_reviewer"),
        CheckConstraint(_in_list("state", _STATES), name="state_enum"),
        CheckConstraint(
            "(invalidation_reason IS NULL) = (state <> 'INVALIDATED')",
            name="invalidated_names_its_reason"),
        CheckConstraint(
            "invalidation_reason IS NULL OR %s"
            % _in_list("invalidation_reason", INVALIDATION_REASONS),
            name="invalidation_reason_enum"),
        _digest("protocol_hash"), _digest("release_manifest_hash"),
        _digest("software_hash"), _digest("dataset_content_hash"),
        _digest("ruleset_content_hash"), _digest("case_manifest_hash"),
        Index("ix_expert_review_assignments_reviewer", "reviewer_actor"),
        Index("ix_expert_review_assignments_case_id", "case_id"),
    )


class ExpertReviewExpectationRow(Base):
    """A locked pre-reveal expectation revision. Never updated.

    ``revision`` increases; a new revision is a new row. The reveal names the
    hash of the revision it pinned, so which one counted is a fact rather than
    a convention.
    """

    __tablename__ = "expert_review_expectations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    revision_id: Mapped[str] = mapped_column(String(128), nullable=False)
    review_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("expert_review_assignments.review_id",
                   ondelete="RESTRICT"),
        nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_attention_level: Mapped[str] = mapped_column(String(48),
                                                          nullable=False)
    expected_coverage_status: Mapped[str] = mapped_column(String(48),
                                                          nullable=False)
    expected_coverage_reason: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True)
    expected_rule_id: Mapped[Optional[str]] = mapped_column(String(128),
                                                            nullable=True)
    requires_traceable_evidence: Mapped[bool] = mapped_column(Boolean,
                                                              nullable=False)
    rationale_codes: Mapped[list] = mapped_column(JSONB, nullable=False,
                                                  default=list)
    reviewer_note: Mapped[str] = mapped_column(Text, nullable=False,
                                               default="")
    #: Server-generated. A client-supplied timestamp would let a reviewer
    #: backdate a prediction, which is the one thing the protocol measures.
    recorded_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    revision_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    previous_hash: Mapped[Optional[str]] = mapped_column(String(80),
                                                         nullable=True)

    __table_args__ = (
        UniqueConstraint("revision_id", name="revision_id"),
        UniqueConstraint("review_id", "revision", name="review_revision"),
        UniqueConstraint("revision_hash", name="revision_hash"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        CheckConstraint("length(reviewer_note) <= 1000", name="note_bounded"),
        CheckConstraint("jsonb_typeof(rationale_codes) = 'array'",
                        name="rationale_codes_is_array"),
        _digest("content_hash"), _digest("revision_hash"),
        Index("ix_expert_review_expectations_review_id", "review_id"),
    )


class ExpertReviewRevealRow(Base):
    """The one-way door. Exactly one per review, by unique constraint."""

    __tablename__ = "expert_review_reveals"

    id: Mapped[uuid.UUID] = _uuid_pk()
    reveal_id: Mapped[str] = mapped_column(String(128), nullable=False)
    review_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("expert_review_assignments.review_id",
                   ondelete="RESTRICT"),
        nullable=False)
    expectation_revision_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("expert_review_expectations.revision_id",
                   ondelete="RESTRICT"),
        nullable=False)
    expectation_revision_hash: Mapped[str] = mapped_column(String(80),
                                                           nullable=False)
    result_attention_level: Mapped[str] = mapped_column(String(48),
                                                        nullable=False)
    result_coverage_status: Mapped[str] = mapped_column(String(48),
                                                        nullable=False)
    result_coverage_reason: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True)
    result_firing_rule_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True)
    result_finding_count: Mapped[int] = mapped_column(Integer, nullable=False)
    result_traceable_finding_count: Mapped[int] = mapped_column(
        Integer, nullable=False)
    result_output_hash: Mapped[str] = mapped_column(String(80),
                                                    nullable=False)
    revealed_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)
    reveal_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    previous_hash: Mapped[Optional[str]] = mapped_column(String(80),
                                                         nullable=True)

    __table_args__ = (
        UniqueConstraint("reveal_id", name="reveal_id"),
        # One reveal per review. A second could show a different result, and
        # the reviewer's decision would then be about something nobody can
        # identify afterwards.
        UniqueConstraint("review_id", name="one_reveal_per_review"),
        CheckConstraint(
            "result_traceable_finding_count <= result_finding_count",
            name="traceable_within_findings"),
        CheckConstraint("result_finding_count >= 0",
                        name="finding_count_non_negative"),
        _digest("expectation_revision_hash"), _digest("result_output_hash"),
        _digest("reveal_hash"),
    )


class ExpertReviewCompletionRow(Base):
    """The post-reveal decision. One per review, only after a reveal."""

    __tablename__ = "expert_review_completions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    completion_id: Mapped[str] = mapped_column(String(128), nullable=False)
    review_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("expert_review_assignments.review_id",
                   ondelete="RESTRICT"),
        nullable=False)
    reveal_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("expert_review_reveals.reveal_id", ondelete="RESTRICT"),
        nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewer_note: Mapped[str] = mapped_column(Text, nullable=False,
                                               default="")
    completed_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)
    completion_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    previous_hash: Mapped[Optional[str]] = mapped_column(String(80),
                                                         nullable=True)

    __table_args__ = (
        UniqueConstraint("completion_id", name="completion_id"),
        UniqueConstraint("review_id", name="one_completion_per_review"),
        # The foreign key to a reveal is what makes completion-before-reveal
        # unrepresentable: there is no reveal id to reference.
        CheckConstraint(_in_list("decision", DECISION_VALUES),
                        name="decision_enum"),
        CheckConstraint("length(reviewer_note) <= 1000", name="note_bounded"),
        _digest("completion_hash"),
    )


class ExpertReviewRatingRow(Base):
    """One optional Likert value on one declared dimension."""

    __tablename__ = "expert_review_ratings"

    id: Mapped[uuid.UUID] = _uuid_pk()
    completion_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("expert_review_completions.completion_id",
                   ondelete="RESTRICT"),
        nullable=False)
    dimension: Mapped[str] = mapped_column(String(48), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        # One rating per dimension per completion. Two would have to be
        # reconciled by something, and nothing may reconcile an opinion.
        UniqueConstraint("completion_id", "dimension",
                         name="completion_dimension"),
        CheckConstraint(_in_list("dimension", LIKERT_DIMENSIONS),
                        name="dimension_enum"),
        CheckConstraint("value BETWEEN %d AND %d"
                        % (LIKERT_MINIMUM, LIKERT_MAXIMUM),
                        name="value_bounded"),
    )


class ExpertReviewCorrectionRow(Base):
    """An appended amendment. The corrected row is never touched."""

    __tablename__ = "expert_review_corrections"

    id: Mapped[uuid.UUID] = _uuid_pk()
    correction_id: Mapped[str] = mapped_column(String(128), nullable=False)
    review_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("expert_review_assignments.review_id",
                   ondelete="RESTRICT"),
        nullable=False)
    target_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(256), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(48), nullable=False)
    replacement: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    after_reveal: Mapped[bool] = mapped_column(Boolean, nullable=False)
    recorded_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)
    correction_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    previous_hash: Mapped[Optional[str]] = mapped_column(String(80),
                                                         nullable=True)

    __table_args__ = (
        UniqueConstraint("correction_id", name="correction_id"),
        UniqueConstraint("correction_hash", name="correction_hash"),
        CheckConstraint(_in_list("kind", CORRECTION_KINDS), name="kind_enum"),
        CheckConstraint("actor_role = 'EXPERT_REVIEWER'",
                        name="corrector_is_the_reviewer"),
        _digest("target_hash"), _digest("correction_hash"),
        Index("ix_expert_review_corrections_review_id", "review_id"),
    )


class ExpertReviewAuditEventRow(Base):
    """One chained event per governed act. Hashes and codes, never content."""

    __tablename__ = "expert_review_audit_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    review_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("expert_review_assignments.review_id",
                   ondelete="RESTRICT"),
        nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    actor: Mapped[str] = mapped_column(String(256), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(48), nullable=False)
    #: Always false until WP-23 changes identity assurance and this column's
    #: check constraint in one visible migration.
    actor_authenticated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    occurred_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)
    previous_state: Mapped[Optional[str]] = mapped_column(String(32),
                                                          nullable=True)
    new_state: Mapped[Optional[str]] = mapped_column(String(32),
                                                     nullable=True)
    outcome_code: Mapped[str] = mapped_column(String(64), nullable=False)
    protocol_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    release_manifest_hash: Mapped[str] = mapped_column(String(80),
                                                       nullable=False)
    case_manifest_hash: Mapped[str] = mapped_column(String(80),
                                                    nullable=False)
    record_hashes: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                                default=dict)
    previous_hash: Mapped[Optional[str]] = mapped_column(String(80),
                                                         nullable=True)
    event_hash: Mapped[str] = mapped_column(String(80), nullable=False)

    __table_args__ = (
        UniqueConstraint("event_id", name="event_id"),
        UniqueConstraint("review_id", "sequence", name="review_sequence"),
        UniqueConstraint("event_hash", name="event_hash"),
        CheckConstraint(_in_list("action", EXPERT_REVIEW_AUDIT_ACTIONS),
                        name="action_enum"),
        # Pinned false. WP-23 owns identity assurance and will change this
        # constraint in the open when it can be satisfied.
        CheckConstraint("actor_authenticated = false",
                        name="no_p0_principal_is_authenticated"),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        CheckConstraint(
            "previous_state IS NULL OR %s" % _in_list("previous_state",
                                                      _STATES),
            name="previous_state_enum"),
        CheckConstraint(
            "new_state IS NULL OR %s" % _in_list("new_state", _STATES),
            name="new_state_enum"),
        # The first event claims no predecessor; every later one must.
        CheckConstraint("(sequence = 1) = (previous_hash IS NULL)",
                        name="first_event_starts_the_chain"),
        _digest("protocol_hash"), _digest("release_manifest_hash"),
        _digest("case_manifest_hash"), _digest("event_hash"),
        Index("ix_expert_review_audit_events_review_id", "review_id"),
    )


class SqlAlchemyExpertReviewRepository:
    """Reads and appends. No update, no delete, and no commit.

    The unit of work owns the transaction; this stages rows in a session it
    was given. That is the project's convention and it matters more here than
    elsewhere: the audit event and the act it describes must land in one
    transaction, and a repository that committed would make that impossible to
    arrange from outside.
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    # -- reads -----------------------------------------------------------

    def assignment_row(self, *, case_id: str, actor: str):
        from sqlalchemy import select
        statement = (select(ExpertReviewAssignmentRow)
                     .where(ExpertReviewAssignmentRow.case_id == case_id)
                     .where(ExpertReviewAssignmentRow.reviewer_actor == actor))
        return self._session.execute(statement).scalars().first()

    def assignment_row_for_update(self, review_id: str):
        """Row-locked read, so two concurrent requests cannot both transition.

        ``with_for_update`` is what makes "one expectation, one reveal, one
        completion" hold under concurrency. The unique constraints are the
        second line; without the lock, two simultaneous reveals would both
        pass their state check and one would fail on insert - correct, but
        with a confusing error rather than a clean serialisation.
        """
        from sqlalchemy import select
        statement = (select(ExpertReviewAssignmentRow)
                     .where(ExpertReviewAssignmentRow.review_id == review_id)
                     .with_for_update())
        return self._session.execute(statement).scalars().first()

    def expectation_rows(self, review_id: str):
        from sqlalchemy import select
        statement = (select(ExpertReviewExpectationRow)
                     .where(ExpertReviewExpectationRow.review_id == review_id)
                     .order_by(ExpertReviewExpectationRow.revision))
        return list(self._session.execute(statement).scalars())

    def reveal_row(self, review_id: str):
        from sqlalchemy import select
        statement = (select(ExpertReviewRevealRow)
                     .where(ExpertReviewRevealRow.review_id == review_id))
        return self._session.execute(statement).scalars().first()

    def completion_row(self, review_id: str):
        from sqlalchemy import select
        statement = (select(ExpertReviewCompletionRow)
                     .where(ExpertReviewCompletionRow.review_id == review_id))
        return self._session.execute(statement).scalars().first()

    def correction_rows(self, review_id: str):
        from sqlalchemy import select
        statement = (select(ExpertReviewCorrectionRow)
                     .where(ExpertReviewCorrectionRow.review_id == review_id)
                     .order_by(ExpertReviewCorrectionRow.recorded_at))
        return list(self._session.execute(statement).scalars())

    def audit_rows(self, review_id: str):
        from sqlalchemy import select
        statement = (select(ExpertReviewAuditEventRow)
                     .where(ExpertReviewAuditEventRow.review_id == review_id)
                     .order_by(ExpertReviewAuditEventRow.sequence))
        return list(self._session.execute(statement).scalars())

    # -- the single append path -------------------------------------------

    def append(self, rows: Sequence[Any]) -> None:
        """Stage rows. The caller's unit of work commits them together."""
        for row in rows:
            self._session.add(row)
