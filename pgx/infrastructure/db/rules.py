# -*- coding: utf-8 -*-
"""SQLAlchemy adapters for the WP-11 rule and ruleset ports.

Repositories and a unit of work, not ORM classes: every mapped class lives in
:mod:`pgx.infrastructure.db.models`, and the boundary test asserting it is
worth more than the convenience of defining one here.

Three things are load-bearing.

**Guarded updates are one statement.** A rule or ruleset advances through an
``UPDATE ... WHERE id = :id AND status = :expected AND lifecycle_version =
:expected_version``, returning ``rowcount``. Read-then-write would leave a
window in which two reviewers both read version 3 and both write version 4;
this cannot, because the predicate is evaluated by the database at write time.

**Freezing takes an advisory lock.** ``pg_advisory_xact_lock`` on the key
``pgx_ruleset_lock_key`` derives from the ruleset id, so two sessions freezing
one ruleset serialise rather than racing to write the same artifact path. The
lock is transaction-scoped, so it is released by commit or rollback and cannot
be leaked.

**Append-only repositories have no update method.** Not a private one, not a
disabled one: the method does not exist, so a caller reaching for it gets an
``AttributeError`` at the point of the mistake.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from pgx.domain.enums import AttentionLevel, RuleStatus, RulesetStatus
from pgx.domain.identifiers import (ComputableRuleId, CuratedInterpretationId,
                                    DatasetPublicId, RulesetPublicId,
                                    RulesetVersionId)
from pgx.domain.immutable import thaw_json
from pgx.infrastructure.db.models import (AuditEventORM, ComputableRuleORM,
                                          RuleEvidenceORM,
                                          RuleLifecycleEventORM,
                                          RulesetApprovalORM, RulesetBuildORM,
                                          RulesetRuleORM, RulesetVersionORM)
from pgx.rules.conditions import parse_condition
from pgx.rules.identifiers import RuleFamilyId, RulesetBuildId
from pgx.rules.models import (ComputableRuleDefinition, RuleLifecycleRecord,
                              RuleOutcome, RuleProvenance,
                              RulesetApprovalRecord, RulesetBuildRecord,
                              RulesetDefinition, RulesetMember)

__all__ = [
    "SqlAlchemyRuleAuditSink",
    "SqlAlchemyRuleRepository",
    "SqlAlchemyRuleWorkflowUnitOfWork",
    "SqlAlchemyRulesetRepository",
]


# ---------------------------------------------------------------------------
# mapping
# ---------------------------------------------------------------------------

def _definition_from_row(row: ComputableRuleORM,
                         evidence_uuids: Sequence[str]
                         ) -> ComputableRuleDefinition:
    return ComputableRuleDefinition(
        rule_id=ComputableRuleId(row.id),
        family_id=RuleFamilyId(row.rule_family_id),
        rule_version=row.rule_version,
        condition=parse_condition(dict(row.condition_json or {})),
        outcome=RuleOutcome(
            attention_level=AttentionLevel(row.attention_level),
            rationale_reference="%s/%s" % (row.curation_work_item_id,
                                           row.curation_revision_id)),
        provenance=RuleProvenance(
            interpretation_id=CuratedInterpretationId(row.interpretation_id),
            curation_work_item_id=row.curation_work_item_id,
            curation_revision_id=row.curation_revision_id,
            curation_revision_hash=row.curation_revision_hash,
            approval_envelope_hash=row.approval_envelope_hash,
            protocol_version=row.protocol_version,
            protocol_content_hash=row.protocol_content_hash,
            dataset_public_id=DatasetPublicId(row.dataset_public_id),
            canonical_build_key=row.canonical_build_key or "",
            canonical_build_content_hash=row.canonical_build_content_hash,
            evidence_build_key=row.evidence_build_key or "",
            evidence_build_content_hash=row.evidence_build_content_hash,
            source_policy_version=row.source_policy_version,
            source_policy_content_hash=row.source_policy_content_hash,
            evidence_record_uuids=tuple(evidence_uuids)),
        created_by=row.created_by, created_at=row.created_at,
        supersedes_rule_id=(ComputableRuleId(row.supersedes_rule_id)
                            if row.supersedes_rule_id else None))


def _lifecycle_from_row(row: ComputableRuleORM) -> RuleLifecycleRecord:
    return RuleLifecycleRecord(
        rule_id=ComputableRuleId(row.id), status=RuleStatus(row.status),
        version=row.lifecycle_version, content_hash=row.content_hash,
        created_at=row.created_at, updated_at=row.updated_at,
        validated_by=row.validated_by, validated_at=row.validated_at,
        validation_result_hash=row.validation_result_hash,
        deprecated_by=row.deprecated_by, deprecated_at=row.deprecated_at,
        deprecation_reason=row.deprecation_reason)


def _ruleset_from_row(row: RulesetVersionORM,
                      members: Sequence[RulesetMember]) -> RulesetDefinition:
    return RulesetDefinition(
        ruleset_id=RulesetVersionId(row.id),
        public_id=RulesetPublicId(row.public_id),
        status=RulesetStatus(row.status), version=row.lifecycle_version,
        created_by=row.created_by or "unknown", created_at=row.created_at,
        members=tuple(members), manifest_hash=row.manifest_hash,
        ruleset_content_hash=row.ruleset_content_hash,
        frozen_at=row.frozen_at, frozen_by=row.frozen_by,
        retired_at=row.retired_at, retired_by=row.retired_by,
        retirement_reason=row.retirement_reason, updated_at=row.updated_at)


# ---------------------------------------------------------------------------
# repositories
# ---------------------------------------------------------------------------

class SqlAlchemyRuleRepository:
    """Rules, with the guarded update as the only state-change path."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _evidence_uuids(self, rule_id: uuid.UUID) -> Tuple[str, ...]:
        rows = self._session.execute(
            select(RuleEvidenceORM.evidence_record_id)
            .where(RuleEvidenceORM.rule_id == rule_id)).scalars().all()
        return tuple(sorted(str(value) for value in rows))

    def add(self, definition: ComputableRuleDefinition,
            lifecycle: RuleLifecycleRecord) -> None:
        provenance = definition.provenance
        self._session.add(ComputableRuleORM(
            id=definition.rule_id.value,
            interpretation_id=provenance.interpretation_id.value,
            condition_json=thaw_json(definition.condition.to_json()),
            attention_level=definition.outcome.attention_level.value,
            status=lifecycle.status.value,
            rule_version=definition.rule_version,
            created_by=definition.created_by,
            created_at=definition.created_at,
            rule_family_id=definition.family_id.value,
            supersedes_rule_id=(definition.supersedes_rule_id.value
                                if definition.supersedes_rule_id else None),
            rule_schema_version=definition.rule_schema_version,
            condition_schema_version=definition.condition.condition_schema_version,
            content_hash=definition.content_hash(),
            lifecycle_version=lifecycle.version,
            gene_canonical_key=definition.condition.gene_canonical_key,
            drug_canonical_key=definition.condition.drug_canonical_key,
            curation_work_item_id=provenance.curation_work_item_id,
            curation_revision_id=provenance.curation_revision_id,
            curation_revision_hash=provenance.curation_revision_hash,
            approval_envelope_hash=provenance.approval_envelope_hash,
            protocol_version=provenance.protocol_version,
            protocol_content_hash=provenance.protocol_content_hash,
            dataset_public_id=provenance.dataset_public_id.to_json(),
            canonical_build_content_hash=provenance.canonical_build_content_hash,
            evidence_build_content_hash=provenance.evidence_build_content_hash,
            source_policy_version=provenance.source_policy_version,
            source_policy_content_hash=provenance.source_policy_content_hash))
        for value in provenance.evidence_record_uuids:
            self._session.add(RuleEvidenceORM(
                rule_id=definition.rule_id.value,
                evidence_record_id=uuid.UUID(value)))
        self._session.flush()

    def get(self, rule_id: ComputableRuleId
            ) -> Optional[Tuple[ComputableRuleDefinition, RuleLifecycleRecord]]:
        row = self._session.execute(
            select(ComputableRuleORM)
            .where(ComputableRuleORM.id == rule_id.value)).scalar_one_or_none()
        if row is None:
            return None
        return (_definition_from_row(row, self._evidence_uuids(row.id)),
                _lifecycle_from_row(row))

    def list_by_status(self, status: RuleStatus,
                       limit: int = 100) -> Sequence[ComputableRuleDefinition]:
        rows = self._session.execute(
            select(ComputableRuleORM)
            .where(ComputableRuleORM.status == status.value)
            .order_by(ComputableRuleORM.gene_canonical_key,
                      ComputableRuleORM.drug_canonical_key,
                      ComputableRuleORM.id)
            .limit(limit)).scalars().all()
        return [_definition_from_row(row, self._evidence_uuids(row.id))
                for row in rows]

    def list_family(self, family_id: str
                    ) -> Sequence[Tuple[ComputableRuleDefinition,
                                        RuleLifecycleRecord]]:
        rows = self._session.execute(
            select(ComputableRuleORM)
            .where(ComputableRuleORM.rule_family_id == uuid.UUID(family_id))
            .order_by(ComputableRuleORM.rule_version)).scalars().all()
        return [(_definition_from_row(row, self._evidence_uuids(row.id)),
                 _lifecycle_from_row(row)) for row in rows]

    def count_by_status(self) -> Mapping[str, int]:
        rows = self._session.execute(
            select(ComputableRuleORM.status, func.count())
            .group_by(ComputableRuleORM.status)).all()
        return {status: count for status, count in rows}

    def guarded_status_update(self, rule_id: ComputableRuleId, *,
                              expected_status: RuleStatus,
                              expected_version: int,
                              new_status: RuleStatus,
                              content_hash: str,
                              actor: str,
                              at: _dt.datetime,
                              validation_result_hash: Optional[str] = None,
                              reason: Optional[str] = None) -> int:
        """One statement; returns the number of rows it changed.

        The content hash is part of the predicate, not only of the payload: a
        caller acting on a rule whose content changed underneath them is as
        stale as one acting on the wrong version, and both must fail the same
        way.
        """
        values: Dict[str, Any] = {
            "status": new_status.value,
            "lifecycle_version": ComputableRuleORM.lifecycle_version + 1,
            "updated_at": at,
        }
        if new_status is RuleStatus.VALIDATED:
            values.update(validated_by=actor, validated_at=at,
                          validation_result_hash=validation_result_hash,
                          approved_by=actor, approved_at=at)
        if new_status is RuleStatus.DEPRECATED:
            values.update(deprecated_by=actor, deprecated_at=at,
                          deprecation_reason=reason)
        statement = (
            update(ComputableRuleORM)
            .where(ComputableRuleORM.id == rule_id.value,
                   ComputableRuleORM.status == expected_status.value,
                   ComputableRuleORM.lifecycle_version == expected_version,
                   ComputableRuleORM.content_hash == content_hash)
            .values(**values)
            .execution_options(synchronize_session=False))
        return int(self._session.execute(statement).rowcount)

    def record_lifecycle_event(self, *, rule_id: ComputableRuleId,
                               from_status: Optional[RuleStatus],
                               to_status: RuleStatus, actor: str,
                               actor_role: str, at: _dt.datetime,
                               content_hash: str,
                               reason: Optional[str] = None,
                               validation_result_hash: Optional[str] = None,
                               audit_event_id: Optional[uuid.UUID] = None) -> str:
        """Append one lifecycle event. There is no update method."""
        event_id = uuid.uuid4()
        self._session.add(RuleLifecycleEventORM(
            id=event_id, rule_id=rule_id.value,
            from_status=from_status.value if from_status else None,
            to_status=to_status.value, actor=actor, actor_role=actor_role,
            occurred_at=at, reason=reason, content_hash=content_hash,
            validation_result_hash=validation_result_hash,
            audit_event_id=audit_event_id))
        self._session.flush()
        return str(event_id)


class SqlAlchemyRulesetRepository:
    """Rulesets, their membership, their builds and their approval lists."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _members(self, ruleset_id: uuid.UUID) -> Tuple[RulesetMember, ...]:
        rows = self._session.execute(
            select(RulesetRuleORM)
            .where(RulesetRuleORM.ruleset_id == ruleset_id)).scalars().all()
        return tuple(RulesetMember(
            rule_id=ComputableRuleId(row.rule_id),
            family_id=RuleFamilyId(row.rule_family_id),
            rule_version=row.rule_version,
            content_hash=row.member_content_hash) for row in rows)

    def lock(self, ruleset_id: RulesetVersionId) -> None:
        """Serialise concurrent validation or freezing of one ruleset.

        Transaction-scoped, so it is released by commit or rollback and cannot
        be leaked by a caller who forgot to unlock.
        """
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(pgx_ruleset_lock_key(:id))"),
            {"id": str(ruleset_id.value)})

    def add(self, ruleset: RulesetDefinition) -> None:
        self._session.add(RulesetVersionORM(
            id=ruleset.ruleset_id.value,
            public_id=ruleset.public_id.to_json(),
            status=ruleset.status.value,
            manifest_hash=ruleset.manifest_hash or ("sha256:" + "0" * 64),
            created_at=ruleset.created_at, created_by=ruleset.created_by,
            lifecycle_version=ruleset.version))
        self._session.flush()

    def get(self, ruleset_id: RulesetVersionId) -> Optional[RulesetDefinition]:
        row = self._session.execute(
            select(RulesetVersionORM)
            .where(RulesetVersionORM.id == ruleset_id.value)).scalar_one_or_none()
        if row is None:
            return None
        return _ruleset_from_row(row, self._members(row.id))

    def list_by_status(self, status: RulesetStatus,
                       limit: int = 100) -> Sequence[RulesetDefinition]:
        rows = self._session.execute(
            select(RulesetVersionORM)
            .where(RulesetVersionORM.status == status.value)
            .order_by(RulesetVersionORM.public_id).limit(limit)).scalars().all()
        return [_ruleset_from_row(row, self._members(row.id)) for row in rows]

    def add_member(self, ruleset_id: RulesetVersionId, member: RulesetMember,
                   *, expected_version: int, actor: str,
                   at: _dt.datetime) -> int:
        bumped = self._session.execute(
            update(RulesetVersionORM)
            .where(RulesetVersionORM.id == ruleset_id.value,
                   RulesetVersionORM.status == RulesetStatus.BUILDING.value,
                   RulesetVersionORM.lifecycle_version == expected_version)
            .values(lifecycle_version=RulesetVersionORM.lifecycle_version + 1,
                    updated_at=at)
            .execution_options(synchronize_session=False)).rowcount
        if bumped != 1:
            return 0
        self._session.add(RulesetRuleORM(
            ruleset_id=ruleset_id.value, rule_id=member.rule_id.value,
            member_content_hash=member.content_hash,
            rule_family_id=member.family_id.value,
            rule_version=member.rule_version, added_by=actor, added_at=at))
        self._session.flush()
        return 1

    def remove_member(self, ruleset_id: RulesetVersionId,
                      rule_id: ComputableRuleId, *, expected_version: int,
                      actor: str, at: _dt.datetime, reason: str) -> int:
        bumped = self._session.execute(
            update(RulesetVersionORM)
            .where(RulesetVersionORM.id == ruleset_id.value,
                   RulesetVersionORM.status == RulesetStatus.BUILDING.value,
                   RulesetVersionORM.lifecycle_version == expected_version)
            .values(lifecycle_version=RulesetVersionORM.lifecycle_version + 1,
                    updated_at=at)
            .execution_options(synchronize_session=False)).rowcount
        if bumped != 1:
            return 0
        removed = self._session.execute(
            RulesetRuleORM.__table__.delete().where(
                RulesetRuleORM.ruleset_id == ruleset_id.value,
                RulesetRuleORM.rule_id == rule_id.value)).rowcount
        return 1 if removed else 0

    def guarded_status_update(self, ruleset_id: RulesetVersionId, *,
                              expected_status: RulesetStatus,
                              expected_version: int,
                              new_status: RulesetStatus,
                              actor: str,
                              at: _dt.datetime,
                              manifest_hash: Optional[str] = None,
                              ruleset_content_hash: Optional[str] = None,
                              reason: Optional[str] = None) -> int:
        values: Dict[str, Any] = {
            "status": new_status.value,
            "lifecycle_version": RulesetVersionORM.lifecycle_version + 1,
            "updated_at": at,
        }
        if new_status in (RulesetStatus.VALIDATED, RulesetStatus.FROZEN):
            values.update(approved_by=actor, approved_at=at)
        if new_status is RulesetStatus.FROZEN:
            values.update(frozen_by=actor, frozen_at=at,
                          ruleset_content_hash=ruleset_content_hash)
            if manifest_hash:
                values["manifest_hash"] = manifest_hash
        if new_status is RulesetStatus.RETIRED:
            values.update(retired_by=actor, retired_at=at,
                          retirement_reason=reason)
        statement = (
            update(RulesetVersionORM)
            .where(RulesetVersionORM.id == ruleset_id.value,
                   RulesetVersionORM.status == expected_status.value,
                   RulesetVersionORM.lifecycle_version == expected_version)
            .values(**values)
            .execution_options(synchronize_session=False))
        return int(self._session.execute(statement).rowcount)

    def record_build(self, record: RulesetBuildRecord) -> str:
        """Append one build attempt. There is no update method."""
        self._session.add(RulesetBuildORM(
            id=record.build_id.value, ruleset_id=record.ruleset_id.value,
            started_at=record.started_at, completed_at=record.completed_at,
            built_by=record.built_by, outcome=record.outcome,
            manifest_hash=record.manifest_hash,
            ruleset_content_hash=record.ruleset_content_hash or None,
            member_count=record.member_count,
            issue_codes=list(record.issue_codes),
            artifact_relative_path=record.artifact_relative_path))
        self._session.flush()
        return record.build_id.to_json()

    def record_approvals(self, ruleset_id: RulesetVersionId,
                         approvals: Sequence[RulesetApprovalRecord]) -> None:
        """Append the approval list. There is no update method."""
        for record in approvals:
            self._session.add(RulesetApprovalORM(
                id=uuid.uuid4(), ruleset_id=ruleset_id.value,
                rule_id=record.rule_id.value,
                rule_family_id=record.family_id.value,
                rule_version=record.rule_version,
                rule_content_hash=record.rule_content_hash,
                approval_envelope_hash=record.approval_envelope_hash,
                curation_revision_id=record.curation_revision_id,
                curation_revision_hash=record.curation_revision_hash,
                created_by=record.created_by, reviewed_by=record.reviewed_by,
                approved_by=record.approved_by,
                validated_by=record.validated_by,
                validated_at=record.validated_at))
        self._session.flush()


class SqlAlchemyRuleAuditSink:
    """Append-only audit events, written in the caller's transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, *, action: str, actor: str, object_type: str,
               object_id: str, occurred_at: _dt.datetime,
               reason: Optional[str] = None,
               metadata: Optional[Mapping[str, Any]] = None) -> str:
        event_id = uuid.uuid4()
        self._session.add(AuditEventORM(
            id=event_id, action=action, actor=actor, object_type=object_type,
            object_id=object_id, occurred_at=occurred_at, reason=reason,
            event_metadata=thaw_json(dict(metadata or {}))))
        self._session.flush()
        return str(event_id)


class SqlAlchemyRuleWorkflowUnitOfWork:
    """One session, one transaction, one commit.

    Rollback is the default: leaving the context without ``commit()`` rolls
    back, so a failed operation cannot leave a rule change without its audit
    event, or an audit event without the change it describes.
    """

    def __init__(self, session_factory: "sessionmaker[Session]") -> None:
        self._session_factory = session_factory
        self._session: Optional[Session] = None
        self._committed = False

    def __enter__(self) -> "SqlAlchemyRuleWorkflowUnitOfWork":
        self._session = self._session_factory()
        self._committed = False
        self.rules = SqlAlchemyRuleRepository(self._session)
        self.rulesets = SqlAlchemyRulesetRepository(self._session)
        self.audit = SqlAlchemyRuleAuditSink(self._session)
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
                "SqlAlchemyRuleWorkflowUnitOfWork must be used as a context "
                "manager")
        return self._session

    def commit(self) -> None:
        self.session.commit()
        self._committed = True

    def rollback(self) -> None:
        if self._session is not None:
            self._session.rollback()
