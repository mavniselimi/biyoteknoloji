# -*- coding: utf-8 -*-
"""SQLAlchemy repository implementations (WP-02, extended by WP-03).

Each repository owns exactly one domain type and enforces that ownership at
runtime, not only in type annotations. Handing an :class:`Assessment` to
:class:`SqlAlchemyEvidenceRepository` raises
:class:`~pgx.domain.errors.RepositoryTypeError`; a static checker would catch
it too, but the boundary must hold for untyped callers as well.

Two further rules:

* **No repository commits.** They stage work in the session; the unit of work
  decides the transaction outcome.
* **No ORM instance escapes.** Every public method returns domain objects, so a
  caller can never hold a detached row and trigger a lazy load later.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence, Type, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from pgx.domain.enums import CurationStatus, ReleaseStatus, RuleStatus
from pgx.domain.errors import DomainError, RepositoryTypeError
from pgx.domain.identifiers import (
    AuditEventId,
    ComputableRuleId,
    CuratedInterpretationId,
    DatasetVersionId,
    DrugId,
    EvidenceRecordId,
    GeneId,
    ReleaseBundleId,
    RulesetVersionId,
    SoftwareVersionId,
    SourceRegistryEntryId,
    require_id,
)
from pgx.domain.models import (
    ActiveRelease,
    AuditEvent,
    ComputableRule,
    CuratedInterpretation,
    DatasetVersion,
    Drug,
    EvidenceRecord,
    Gene,
    ReleaseBundle,
    RulesetVersion,
    SoftwareVersion,
    SourceRegistryEntry,
)
from pgx.infrastructure.db import mappers
from pgx.infrastructure.db.models import (
    ACTIVE_RELEASE_SINGLETON_ID,
    ActiveReleaseORM,
    AuditEventORM,
    ComputableRuleORM,
    CuratedInterpretationORM,
    DatasetVersionORM,
    DrugAliasORM,
    DrugORM,
    EvidenceRecordORM,
    GeneAliasORM,
    GeneORM,
    ReleaseBundleORM,
    RulesetVersionORM,
    SourceRegistryORM,
)

__all__ = [
    "SqlAlchemyActiveReleaseRepository",
    "SqlAlchemyAuditEventRepository",
    "SqlAlchemyDatasetVersionRepository",
    "SqlAlchemyDrugRepository",
    "SqlAlchemyEvidenceRepository",
    "SqlAlchemyGeneRepository",
    "SqlAlchemyInterpretationRepository",
    "SqlAlchemyReleaseBundleRepository",
    "SqlAlchemyRuleRepository",
    "SqlAlchemyRulesetVersionRepository",
    "SqlAlchemySoftwareVersionRepository",
    "SqlAlchemySourceRegistryRepository",
    "StaleActiveReleaseError",
]


class StaleActiveReleaseError(DomainError):
    """The active pointer moved between reading it and writing it back.

    Raised by :class:`SqlAlchemyActiveReleaseRepository` when the generation
    guard fails. The service turns it into a
    :class:`~pgx.application.release_service.StaleActivationError`.
    """

_T = TypeVar("_T")


def _require_exact(value: Any, expected: Type[_T], repository: str) -> _T:
    """Reject anything that is not exactly ``expected``.

    An exact type check, not ``isinstance``: a subclass of a domain model is
    not the model, and accepting one would let a caller smuggle extra state
    past the boundary.
    """
    if type(value) is not expected:
        raise RepositoryTypeError(
            "%s accepts only %s, got %s. Each repository owns exactly one domain "
            "type so that, for example, evidence storage can never accept an "
            "assessment." % (repository, expected.__name__, type(value).__name__))
    return value


def _require_id(value: Any, expected: type, repository: str) -> Any:
    if type(value) is not expected:
        raise RepositoryTypeError(
            "%s requires %s, got %s" % (repository, expected.__name__, type(value).__name__))
    return value


class SqlAlchemySourceRegistryRepository:
    """Persistence for :class:`SourceRegistryEntry`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, entry: SourceRegistryEntry) -> None:
        """Stage a new source registry entry."""
        _require_exact(entry, SourceRegistryEntry, "SourceRegistryRepository.add")
        self._session.add(mappers.source_registry_to_orm(entry))

    def get(self, entry_id: SourceRegistryEntryId) -> Optional[SourceRegistryEntry]:
        """Return the entry with this identity, or ``None``."""
        _require_id(entry_id, SourceRegistryEntryId, "SourceRegistryRepository.get")
        row = self._session.get(SourceRegistryORM, entry_id.value)
        return None if row is None else mappers.source_registry_to_domain(row)

    def get_by_source_key(self, source_key: str) -> Optional[SourceRegistryEntry]:
        """Return the entry with this unique source key, or ``None``."""
        row = self._session.execute(
            select(SourceRegistryORM).where(SourceRegistryORM.source_key == source_key)
        ).scalar_one_or_none()
        return None if row is None else mappers.source_registry_to_domain(row)

    def list_active(self) -> Sequence[SourceRegistryEntry]:
        """Return every active entry, ordered by source key for determinism."""
        rows = self._session.execute(
            select(SourceRegistryORM)
            .where(SourceRegistryORM.active.is_(True))
            .order_by(SourceRegistryORM.source_key)
        ).scalars().all()
        return [mappers.source_registry_to_domain(row) for row in rows]


class SqlAlchemyGeneRepository:
    """Persistence for :class:`Gene`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, gene: Gene) -> None:
        """Stage a new gene and its aliases."""
        _require_exact(gene, Gene, "GeneRepository.add")
        self._session.add(mappers.gene_to_orm(gene))

    def get(self, gene_id: GeneId) -> Optional[Gene]:
        """Return the gene with this identity, or ``None``."""
        _require_id(gene_id, GeneId, "GeneRepository.get")
        row = self._session.get(GeneORM, gene_id.value)
        return None if row is None else mappers.gene_to_domain(row)

    def get_by_normalized_symbol(self, normalized_symbol: str) -> Optional[Gene]:
        """Return the gene whose canonical symbol matches, or ``None``."""
        row = self._session.execute(
            select(GeneORM).where(GeneORM.normalized_symbol == normalized_symbol)
        ).scalar_one_or_none()
        return None if row is None else mappers.gene_to_domain(row)

    def find_by_alias(self, normalized_alias: str) -> Sequence[Gene]:
        """Return every gene carrying this alias.

        Returns all matches on purpose. An alias shared by two genes is real
        ambiguity that belongs in a WP-07 resolution queue; silently returning
        the first row would fabricate a decision.
        """
        rows = self._session.execute(
            select(GeneORM)
            .join(GeneAliasORM, GeneAliasORM.gene_id == GeneORM.id)
            .where(GeneAliasORM.normalized_alias == normalized_alias)
            .order_by(GeneORM.normalized_symbol)
        ).scalars().unique().all()
        return [mappers.gene_to_domain(row) for row in rows]


class SqlAlchemyDrugRepository:
    """Persistence for :class:`Drug`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, drug: Drug) -> None:
        """Stage a new drug and its aliases."""
        _require_exact(drug, Drug, "DrugRepository.add")
        self._session.add(mappers.drug_to_orm(drug))

    def get(self, drug_id: DrugId) -> Optional[Drug]:
        """Return the drug with this identity, or ``None``."""
        _require_id(drug_id, DrugId, "DrugRepository.get")
        row = self._session.get(DrugORM, drug_id.value)
        return None if row is None else mappers.drug_to_domain(row)

    def get_by_normalized_name(self, normalized_name: str) -> Optional[Drug]:
        """Return the drug whose canonical name matches, or ``None``."""
        row = self._session.execute(
            select(DrugORM).where(DrugORM.normalized_name == normalized_name)
        ).scalar_one_or_none()
        return None if row is None else mappers.drug_to_domain(row)

    def find_by_alias(self, normalized_alias: str) -> Sequence[Drug]:
        """Return every drug carrying this alias; ambiguity is not resolved."""
        rows = self._session.execute(
            select(DrugORM)
            .join(DrugAliasORM, DrugAliasORM.drug_id == DrugORM.id)
            .where(DrugAliasORM.normalized_alias == normalized_alias)
            .order_by(DrugORM.normalized_name)
        ).scalars().unique().all()
        return [mappers.drug_to_domain(row) for row in rows]


class SqlAlchemyEvidenceRepository:
    """Persistence for :class:`EvidenceRecord`.

    There is no method here that accepts or returns an assessment or a finding.
    Evidence is source truth; promoting it to a calculated result requires
    curation and rule approval, which are separate repositories.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, record: EvidenceRecord) -> None:
        """Stage a new evidence record."""
        _require_exact(record, EvidenceRecord, "EvidenceRepository.add")
        self._session.add(mappers.evidence_to_orm(record))

    def get(self, record_id: EvidenceRecordId) -> Optional[EvidenceRecord]:
        """Return the evidence record with this identity, or ``None``."""
        _require_id(record_id, EvidenceRecordId, "EvidenceRepository.get")
        row = self._session.get(EvidenceRecordORM, record_id.value)
        return None if row is None else mappers.evidence_to_domain(row)

    def list_for_dataset_version(
        self, dataset_version_id: DatasetVersionId
    ) -> Sequence[EvidenceRecord]:
        """Return every evidence record in a dataset version, deterministically."""
        _require_id(dataset_version_id, DatasetVersionId,
                    "EvidenceRepository.list_for_dataset_version")
        rows = self._session.execute(
            select(EvidenceRecordORM)
            .where(EvidenceRecordORM.dataset_version_id == dataset_version_id.value)
            .order_by(EvidenceRecordORM.source_record_id,
                      EvidenceRecordORM.source_record_version)
        ).scalars().all()
        return [mappers.evidence_to_domain(row) for row in rows]


class SqlAlchemyInterpretationRepository:
    """Persistence for :class:`CuratedInterpretation`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, interpretation: CuratedInterpretation) -> None:
        """Stage a new interpretation and its evidence links."""
        _require_exact(interpretation, CuratedInterpretation,
                       "InterpretationRepository.add")
        self._session.add(mappers.interpretation_to_orm(interpretation))

    def get(
        self, interpretation_id: CuratedInterpretationId
    ) -> Optional[CuratedInterpretation]:
        """Return the interpretation with this identity, or ``None``."""
        _require_id(interpretation_id, CuratedInterpretationId,
                    "InterpretationRepository.get")
        row = self._session.get(CuratedInterpretationORM, interpretation_id.value)
        return None if row is None else mappers.interpretation_to_domain(row)

    def list_by_status(self, status: CurationStatus) -> Sequence[CuratedInterpretation]:
        """Return interpretations in a given curation status."""
        if not isinstance(status, CurationStatus):
            raise RepositoryTypeError(
                "InterpretationRepository.list_by_status requires a CurationStatus, "
                "got %s" % type(status).__name__)
        rows = self._session.execute(
            select(CuratedInterpretationORM)
            .where(CuratedInterpretationORM.status == status.value)
            .order_by(CuratedInterpretationORM.created_at, CuratedInterpretationORM.id)
        ).scalars().all()
        return [mappers.interpretation_to_domain(row) for row in rows]


class SqlAlchemyRuleRepository:
    """Persistence for :class:`ComputableRule`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, rule: ComputableRule) -> None:
        """Stage a new rule and its evidence links."""
        _require_exact(rule, ComputableRule, "RuleRepository.add")
        self._session.add(mappers.rule_to_orm(rule))

    def get(self, rule_id: ComputableRuleId) -> Optional[ComputableRule]:
        """Return the rule with this identity, or ``None``."""
        _require_id(rule_id, ComputableRuleId, "RuleRepository.get")
        row = self._session.get(ComputableRuleORM, rule_id.value)
        return None if row is None else mappers.rule_to_domain(row)

    def list_validated(self) -> Sequence[ComputableRule]:
        """Return only VALIDATED rules (``SAFETY-INV-003``).

        There is deliberately no ``list_all`` returning executable candidates:
        a draft or deprecated rule must never reach an execution path.
        """
        rows = self._session.execute(
            select(ComputableRuleORM)
            .where(ComputableRuleORM.status == RuleStatus.VALIDATED.value)
            .order_by(ComputableRuleORM.created_at, ComputableRuleORM.id)
        ).scalars().all()
        return [mappers.rule_to_domain(row) for row in rows]


# ---------------------------------------------------------------------------
# WP-03 - version registry, release bundles, active pointer, audit
# ---------------------------------------------------------------------------


class SqlAlchemySoftwareVersionRepository:
    """Registered software builds."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, software_version: SoftwareVersion) -> None:
        """Stage a newly registered build."""
        entity = _require_exact(software_version, SoftwareVersion,
                                "SoftwareVersionRepository.add")
        self._session.add(mappers.software_version_to_orm(entity))

    def get(self, software_version_id: SoftwareVersionId) -> Optional[SoftwareVersion]:
        """Return the build with this identity, or ``None``."""
        require_id(software_version_id, SoftwareVersionId,
                   "SoftwareVersionRepository.get")
        row = self._session.get(SoftwareVersionORM, software_version_id.value)
        return None if row is None else mappers.software_version_to_domain(row)

    def get_by_source_tree_hash(self, source_tree_hash: str) -> Optional[SoftwareVersion]:
        """Return the build with this source tree digest, or ``None``."""
        row = self._session.execute(
            select(SoftwareVersionORM)
            .where(SoftwareVersionORM.source_tree_hash == source_tree_hash)
        ).scalar_one_or_none()
        return None if row is None else mappers.software_version_to_domain(row)

    def list_all(self) -> Sequence[SoftwareVersion]:
        """Return every registered build, ordered by build time then identity."""
        rows = self._session.execute(
            select(SoftwareVersionORM)
            .order_by(SoftwareVersionORM.built_at, SoftwareVersionORM.id)
        ).scalars().all()
        return [mappers.software_version_to_domain(row) for row in rows]


class SqlAlchemyDatasetVersionRepository:
    """Dataset versions. WP-02 created the table; WP-03 needs to read it."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, dataset_version: DatasetVersion) -> None:
        """Stage a new dataset version."""
        entity = _require_exact(dataset_version, DatasetVersion,
                                "DatasetVersionRepository.add")
        self._session.add(mappers.dataset_version_to_orm(entity))

    def get(self, dataset_version_id: DatasetVersionId) -> Optional[DatasetVersion]:
        """Return the dataset version with this identity, or ``None``."""
        require_id(dataset_version_id, DatasetVersionId, "DatasetVersionRepository.get")
        row = self._session.get(DatasetVersionORM, dataset_version_id.value)
        return None if row is None else mappers.dataset_version_to_domain(row)

    def get_by_public_id(self, public_id: str) -> Optional[DatasetVersion]:
        """Return the dataset version with this public identifier, or ``None``."""
        row = self._session.execute(
            select(DatasetVersionORM)
            .where(DatasetVersionORM.public_id == str(public_id))
        ).scalar_one_or_none()
        return None if row is None else mappers.dataset_version_to_domain(row)


class SqlAlchemyRulesetVersionRepository:
    """Ruleset versions together with their pinned membership."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, ruleset_version: RulesetVersion) -> None:
        """Stage a ruleset version and every membership row it pins."""
        entity = _require_exact(ruleset_version, RulesetVersion,
                                "RulesetVersionRepository.add")
        self._session.add(mappers.ruleset_version_to_orm(entity))

    def get(self, ruleset_version_id: RulesetVersionId) -> Optional[RulesetVersion]:
        """Return the ruleset version and its membership, or ``None``."""
        require_id(ruleset_version_id, RulesetVersionId, "RulesetVersionRepository.get")
        row = self._session.get(RulesetVersionORM, ruleset_version_id.value)
        return None if row is None else mappers.ruleset_version_to_domain(row)

    def get_by_public_id(self, public_id: str) -> Optional[RulesetVersion]:
        """Return the ruleset version with this public identifier, or ``None``."""
        row = self._session.execute(
            select(RulesetVersionORM)
            .where(RulesetVersionORM.public_id == str(public_id))
        ).scalar_one_or_none()
        return None if row is None else mappers.ruleset_version_to_domain(row)


class SqlAlchemyReleaseBundleRepository:
    """Release bundles.

    There is no general update. A release's pinned content - the triple, the
    manifest and its digest - is immutable after registration, and offering an
    update method would invite exactly the rewrite the version registry exists
    to prevent. Only :meth:`set_status` moves anything, and only the lifecycle
    fields.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, release: ReleaseBundle) -> None:
        """Stage a newly registered release bundle."""
        entity = _require_exact(release, ReleaseBundle, "ReleaseBundleRepository.add")
        self._session.add(mappers.release_bundle_to_orm(entity))

    def get(self, release_id: ReleaseBundleId) -> Optional[ReleaseBundle]:
        """Return the release bundle with this identity, or ``None``."""
        require_id(release_id, ReleaseBundleId, "ReleaseBundleRepository.get")
        row = self._session.get(ReleaseBundleORM, release_id.value)
        return None if row is None else mappers.release_bundle_to_domain(row)

    def get_by_public_id(self, public_id) -> Optional[ReleaseBundle]:
        """Return the release bundle with this public identifier, or ``None``."""
        row = self._session.execute(
            select(ReleaseBundleORM)
            .where(ReleaseBundleORM.public_id == str(public_id))
        ).scalar_one_or_none()
        return None if row is None else mappers.release_bundle_to_domain(row)

    def set_status(
        self,
        release_id: ReleaseBundleId,
        status: ReleaseStatus,
        activated_at=None,
        activated_by: Optional[str] = None,
    ) -> None:
        """Move a release's lifecycle status, leaving its pinned content alone."""
        require_id(release_id, ReleaseBundleId, "ReleaseBundleRepository.set_status")
        if not isinstance(status, ReleaseStatus):
            raise RepositoryTypeError(
                "status must be a ReleaseStatus, got %r" % type(status).__name__)
        row = self._session.get(ReleaseBundleORM, release_id.value)
        if row is None:
            raise RepositoryTypeError(
                "cannot set the status of release %s: it does not exist" % release_id)
        row.status = status.value
        if activated_at is not None:
            row.activated_at = activated_at
        if activated_by is not None:
            row.activated_by = activated_by

    def list_all(self) -> Sequence[ReleaseBundle]:
        """Return every release bundle, newest first then by identity."""
        rows = self._session.execute(
            select(ReleaseBundleORM)
            .order_by(ReleaseBundleORM.created_at.desc(), ReleaseBundleORM.id)
        ).scalars().all()
        return [mappers.release_bundle_to_domain(row) for row in rows]


class SqlAlchemyActiveReleaseRepository:
    """The singleton active-release pointer.

    :meth:`get_for_update` issues ``SELECT ... FOR UPDATE`` on the one row, so
    a concurrent activation blocks until this transaction ends. :meth:`update`
    additionally guards on the generation it expects, so a lost update is
    *detectable* rather than merely unlikely - and so the same contract could
    be honoured by a store with weaker locking.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def _row(self, for_update: bool = False) -> ActiveReleaseORM:
        statement = select(ActiveReleaseORM).where(
            ActiveReleaseORM.singleton_id == ACTIVE_RELEASE_SINGLETON_ID)
        if for_update:
            statement = statement.with_for_update()
        row = self._session.execute(statement).scalar_one_or_none()
        if row is None:
            raise RepositoryTypeError(
                "the active_release singleton row is missing. Migration 0002 "
                "creates it; a database without it has not been migrated.")
        return row

    def get(self) -> ActiveRelease:
        """Return the current pointer without locking."""
        return mappers.active_release_to_domain(self._row())

    def get_for_update(self) -> ActiveRelease:
        """Return the current pointer, holding a row lock until the transaction ends."""
        return mappers.active_release_to_domain(self._row(for_update=True))

    def update(self, pointer: ActiveRelease, expected_generation: int) -> None:
        """Write the new pointer, or raise if the generation moved underneath."""
        _require_exact(pointer, ActiveRelease, "ActiveReleaseRepository.update")
        row = self._row(for_update=True)
        if row.generation != expected_generation:
            raise StaleActiveReleaseError(
                "the active release pointer moved while this activation was "
                "being prepared: expected generation %d, found %d. Another "
                "activation committed first; retry against the new state."
                % (expected_generation, row.generation))
        row.release_id = None if pointer.release_id is None else pointer.release_id.value
        row.generation = pointer.generation
        row.updated_at = pointer.updated_at
        row.updated_by = pointer.updated_by


class SqlAlchemyAuditEventRepository:
    """Append-only audit trail.

    No update method and no delete method - the absence is the contract. The
    database enforces it too: migration 0002 installs a trigger that refuses
    ``UPDATE`` and ``DELETE`` on this table, so the guarantee survives a
    ``psql`` prompt as well as a code review.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, event: AuditEvent) -> None:
        """Stage one new audit event."""
        entity = _require_exact(event, AuditEvent, "AuditEventRepository.append")
        self._session.add(mappers.audit_event_to_orm(entity))

    def list_for_object(self, object_type: str, object_id: str) -> Sequence[AuditEvent]:
        """Return every event about one object, oldest first."""
        rows = self._session.execute(
            select(AuditEventORM)
            .where(AuditEventORM.object_type == object_type)
            .where(AuditEventORM.object_id == object_id)
            .order_by(AuditEventORM.occurred_at, AuditEventORM.id)
        ).scalars().all()
        return [mappers.audit_event_to_domain(row) for row in rows]

    def list_recent(self, limit: int = 100) -> Sequence[AuditEvent]:
        """Return the most recent events, newest first."""
        rows = self._session.execute(
            select(AuditEventORM)
            .order_by(AuditEventORM.occurred_at.desc(), AuditEventORM.id)
            .limit(limit)
        ).scalars().all()
        return [mappers.audit_event_to_domain(row) for row in rows]
