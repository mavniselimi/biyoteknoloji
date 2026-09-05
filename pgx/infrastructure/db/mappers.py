# -*- coding: utf-8 -*-
"""Explicit domain <-> ORM mapping (WP-02, extended by WP-03).

Every conversion is written out by hand. There is no automap, no reflection,
and no shared base class between the two hierarchies, so a change to a table
cannot silently change a domain model or vice versa - it breaks here, in one
reviewable place.

Direction is symmetric and total: ``to_orm`` builds a persistence row from a
domain object, ``to_domain`` rebuilds the domain object from a row. No ORM
instance ever leaves this module's callers.
"""

from __future__ import annotations

import uuid
from typing import Any, Mapping, Sequence

from pgx.domain.enums import (
    AttentionLevel,
    AuditAction,
    CurationStatus,
    DatasetStatus,
    Phenotype,
    ReleaseStatus,
    RuleStatus,
    RulesetStatus,
    SourceRole,
)
from pgx.domain.immutable import thaw_json
from pgx.domain.identifiers import (
    AuditEventId,
    ComputableRuleId,
    CuratedInterpretationId,
    DatasetPublicId,
    DatasetVersionId,
    DrugId,
    EvidenceRecordId,
    GeneId,
    ReleaseBundleId,
    ReleasePublicId,
    RulesetPublicId,
    RulesetVersionId,
    SoftwareVersionId,
    SourceRegistryEntryId,
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
from pgx.infrastructure.db.models import (
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
    InterpretationEvidenceORM,
    ReleaseBundleORM,
    RuleEvidenceORM,
    RulesetRuleORM,
    RulesetVersionORM,
    SoftwareVersionORM,
    SourceRegistryORM,
)

__all__ = [
    "drug_to_domain",
    "drug_to_orm",
    "evidence_to_domain",
    "evidence_to_orm",
    "gene_to_domain",
    "gene_to_orm",
    "interpretation_to_domain",
    "interpretation_to_orm",
    "rule_to_domain",
    "rule_to_orm",
    "source_registry_to_domain",
    "source_registry_to_orm",
    "dataset_version_to_domain",
    "dataset_version_to_orm",
]


def _metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Convert a frozen domain mapping into the plain dict JSONB needs.

    ``thaw_json`` produces a fresh mutable copy, so the driver can never reach
    back into a domain object and mutate it.
    """
    if value is None:
        return {}
    thawed = thaw_json(value)
    if not isinstance(thawed, dict):  # pragma: no cover - defensive
        raise TypeError("metadata must thaw to a dict, got %r" % type(thawed).__name__)
    return thawed


# ---------------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------------


def source_registry_to_orm(entry: SourceRegistryEntry) -> SourceRegistryORM:
    """Build a persistence row from a :class:`SourceRegistryEntry`."""
    return SourceRegistryORM(
        id=entry.id.value,
        source_key=entry.source_key,
        display_name=entry.display_name,
        role=entry.role.value,
        version_policy=entry.version_policy,
        license_policy=entry.license_policy,
        citation_policy=entry.citation_policy,
        release_eligible=entry.release_eligible,
        active=entry.active,
        created_at=entry.created_at,
        legacy_id=entry.legacy_id,
    )


def source_registry_to_domain(row: SourceRegistryORM) -> SourceRegistryEntry:
    """Rebuild a :class:`SourceRegistryEntry` from a persistence row."""
    return SourceRegistryEntry(
        id=SourceRegistryEntryId(row.id),
        source_key=row.source_key,
        display_name=row.display_name,
        role=SourceRole(row.role),
        version_policy=row.version_policy,
        license_policy=row.license_policy,
        citation_policy=row.citation_policy,
        release_eligible=row.release_eligible,
        active=row.active,
        created_at=row.created_at,
        legacy_id=row.legacy_id,
    )


# ---------------------------------------------------------------------------
# Dataset version
# ---------------------------------------------------------------------------


def dataset_version_to_orm(version: DatasetVersion) -> DatasetVersionORM:
    """Build a persistence row from a :class:`DatasetVersion`."""
    return DatasetVersionORM(
        id=version.id.value,
        public_id=version.public_id.value,
        status=version.status.value,
        manifest_hash=version.manifest_hash,
        dq_report_path=version.dq_report_path,
        created_at=version.created_at,
        approved_by=version.approved_by,
        approved_at=version.approved_at,
        legacy_id=version.legacy_id,
    )


def dataset_version_to_domain(row: DatasetVersionORM) -> DatasetVersion:
    """Rebuild a :class:`DatasetVersion` from a persistence row."""
    return DatasetVersion(
        id=DatasetVersionId(row.id),
        public_id=DatasetPublicId(row.public_id),
        status=DatasetStatus(row.status),
        manifest_hash=row.manifest_hash,
        dq_report_path=row.dq_report_path,
        created_at=row.created_at,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        legacy_id=row.legacy_id,
    )


# ---------------------------------------------------------------------------
# Gene and drug
# ---------------------------------------------------------------------------


def gene_to_orm(gene: Gene) -> GeneORM:
    """Build a gene row plus its alias rows."""
    row = GeneORM(
        id=gene.id.value,
        normalized_symbol=gene.normalized_symbol,
        preferred_name=gene.preferred_name,
        external_ids=_metadata(gene.external_ids),
        created_at=gene.created_at,
        legacy_id=gene.legacy_id,
    )
    row.aliases = [
        GeneAliasORM(
            gene_id=gene.id.value,
            normalized_alias=alias.strip().upper(),
            display_alias=alias,
        )
        for alias in gene.aliases
    ]
    return row


def gene_to_domain(row: GeneORM) -> Gene:
    """Rebuild a :class:`Gene`, with aliases in a deterministic order."""
    return Gene(
        id=GeneId(row.id),
        normalized_symbol=row.normalized_symbol,
        preferred_name=row.preferred_name,
        created_at=row.created_at,
        aliases=tuple(sorted(alias.display_alias for alias in row.aliases)),
        external_ids=dict(row.external_ids or {}),
        legacy_id=row.legacy_id,
    )


def drug_to_orm(drug: Drug) -> DrugORM:
    """Build a drug row plus its alias rows."""
    row = DrugORM(
        id=drug.id.value,
        normalized_name=drug.normalized_name,
        preferred_name=drug.preferred_name,
        external_ids=_metadata(drug.external_ids),
        created_at=drug.created_at,
        legacy_id=drug.legacy_id,
    )
    row.aliases = [
        DrugAliasORM(
            drug_id=drug.id.value,
            normalized_alias=alias.strip().lower(),
            display_alias=alias,
        )
        for alias in drug.aliases
    ]
    return row


def drug_to_domain(row: DrugORM) -> Drug:
    """Rebuild a :class:`Drug`, with aliases in a deterministic order."""
    return Drug(
        id=DrugId(row.id),
        normalized_name=row.normalized_name,
        preferred_name=row.preferred_name,
        created_at=row.created_at,
        aliases=tuple(sorted(alias.display_alias for alias in row.aliases)),
        external_ids=dict(row.external_ids or {}),
        legacy_id=row.legacy_id,
    )


# ---------------------------------------------------------------------------
# Evidence, interpretation, rule
# ---------------------------------------------------------------------------


def evidence_to_orm(record: EvidenceRecord) -> EvidenceRecordORM:
    """Build a persistence row from an :class:`EvidenceRecord`."""
    return EvidenceRecordORM(
        id=record.id.value,
        source_registry_id=record.source_registry_id.value,
        dataset_version_id=record.dataset_version_id.value,
        source_record_id=record.source_record_id,
        source_record_version=record.source_record_version,
        gene_id=record.gene_id.value if record.gene_id is not None else None,
        drug_id=record.drug_id.value if record.drug_id is not None else None,
        raw_hash=record.raw_hash,
        source_text=record.source_text,
        evidence_metadata=_metadata(record.evidence_metadata),
        publication_metadata=_metadata(record.publication_metadata),
        created_at=record.created_at,
        legacy_id=record.legacy_id,
    )


def evidence_to_domain(row: EvidenceRecordORM) -> EvidenceRecord:
    """Rebuild an :class:`EvidenceRecord` from a persistence row."""
    return EvidenceRecord(
        id=EvidenceRecordId(row.id),
        source_registry_id=SourceRegistryEntryId(row.source_registry_id),
        dataset_version_id=DatasetVersionId(row.dataset_version_id),
        source_record_id=row.source_record_id,
        source_record_version=row.source_record_version,
        raw_hash=row.raw_hash,
        created_at=row.created_at,
        gene_id=GeneId(row.gene_id) if row.gene_id is not None else None,
        drug_id=DrugId(row.drug_id) if row.drug_id is not None else None,
        source_text=row.source_text,
        evidence_metadata=dict(row.evidence_metadata or {}),
        publication_metadata=dict(row.publication_metadata or {}),
        legacy_id=row.legacy_id,
    )


def interpretation_to_orm(
    interpretation: CuratedInterpretation,
) -> CuratedInterpretationORM:
    """Build an interpretation row plus its evidence link rows."""
    row = CuratedInterpretationORM(
        id=interpretation.id.value,
        status=interpretation.status.value,
        normalized_phenotype=(
            interpretation.normalized_phenotype.value
            if interpretation.normalized_phenotype is not None else None),
        normalized_effect=interpretation.normalized_effect,
        significance=interpretation.significance,
        rationale=interpretation.rationale,
        created_by=interpretation.created_by,
        reviewed_by=interpretation.reviewed_by,
        created_at=interpretation.created_at,
        reviewed_at=interpretation.reviewed_at,
        legacy_id=interpretation.legacy_id,
    )
    row.evidence_links = [
        InterpretationEvidenceORM(
            interpretation_id=interpretation.id.value,
            evidence_record_id=evidence_id.value,
        )
        for evidence_id in interpretation.evidence_record_ids
    ]
    return row


def _sorted_evidence_ids(links: Sequence[Any]) -> tuple[EvidenceRecordId, ...]:
    """Deterministic evidence ordering, independent of database row order."""
    values: list[uuid.UUID] = [link.evidence_record_id for link in links]
    return tuple(EvidenceRecordId(value) for value in sorted(values, key=str))


def interpretation_to_domain(row: CuratedInterpretationORM) -> CuratedInterpretation:
    """Rebuild a :class:`CuratedInterpretation` from a persistence row."""
    return CuratedInterpretation(
        id=CuratedInterpretationId(row.id),
        evidence_record_ids=_sorted_evidence_ids(row.evidence_links),
        status=CurationStatus(row.status),
        normalized_effect=row.normalized_effect,
        significance=row.significance,
        created_by=row.created_by,
        created_at=row.created_at,
        normalized_phenotype=(
            Phenotype(row.normalized_phenotype)
            if row.normalized_phenotype is not None else None),
        rationale=row.rationale,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        legacy_id=row.legacy_id,
    )


def rule_to_orm(rule: ComputableRule) -> ComputableRuleORM:
    """Build a rule row plus its evidence link rows."""
    row = ComputableRuleORM(
        id=rule.id.value,
        interpretation_id=rule.interpretation_id.value,
        condition_json=_metadata(rule.condition),
        attention_level=rule.attention_level.value,
        status=rule.status.value,
        rule_version=rule.rule_version,
        created_by=rule.created_by,
        approved_by=rule.approved_by,
        created_at=rule.created_at,
        approved_at=rule.approved_at,
        legacy_id=rule.legacy_id,
    )
    row.evidence_links = [
        RuleEvidenceORM(rule_id=rule.id.value, evidence_record_id=evidence_id.value)
        for evidence_id in rule.evidence_record_ids
    ]
    return row


def rule_to_domain(row: ComputableRuleORM) -> ComputableRule:
    """Rebuild a :class:`ComputableRule` from a persistence row."""
    return ComputableRule(
        id=ComputableRuleId(row.id),
        interpretation_id=CuratedInterpretationId(row.interpretation_id),
        evidence_record_ids=_sorted_evidence_ids(row.evidence_links),
        condition=dict(row.condition_json or {}),
        attention_level=AttentionLevel(row.attention_level),
        status=RuleStatus(row.status),
        rule_version=row.rule_version,
        created_by=row.created_by,
        created_at=row.created_at,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        legacy_id=row.legacy_id,
    )


# ---------------------------------------------------------------------------
# WP-03 - version registry, release bundles, active pointer, audit
# ---------------------------------------------------------------------------


def software_version_to_orm(software: SoftwareVersion) -> SoftwareVersionORM:
    """Build a persistence row from a :class:`SoftwareVersion`."""
    return SoftwareVersionORM(
        id=software.id.value,
        version=software.version,
        source_commit=software.source_commit,
        source_tree_hash=software.source_tree_hash,
        manifest_hash=software.manifest_hash,
        built_at=software.built_at,
        created_at=software.created_at,
        build_metadata=thaw_json(software.build_metadata),
    )


def software_version_to_domain(row: SoftwareVersionORM) -> SoftwareVersion:
    """Rebuild a :class:`SoftwareVersion` from a persistence row."""
    return SoftwareVersion(
        id=SoftwareVersionId(row.id),
        version=row.version,
        source_commit=row.source_commit,
        source_tree_hash=row.source_tree_hash,
        manifest_hash=row.manifest_hash,
        built_at=row.built_at,
        created_at=row.created_at,
        build_metadata=row.build_metadata or {},
    )


def ruleset_version_to_orm(ruleset: RulesetVersion) -> RulesetVersionORM:
    """Build a persistence row and its membership rows together.

    Membership travels with the ruleset rather than being written separately:
    a ruleset stored without its members would let a release cite contents
    nobody recorded.
    """
    row = RulesetVersionORM(
        id=ruleset.id.value,
        public_id=ruleset.public_id.value,
        status=ruleset.status.value,
        manifest_hash=ruleset.manifest_hash,
        created_at=ruleset.created_at,
        approved_by=ruleset.approved_by,
        approved_at=ruleset.approved_at,
        legacy_id=ruleset.legacy_id,
    )
    row.members = [
        RulesetRuleORM(ruleset_id=ruleset.id.value, rule_id=rule_id.value)
        for rule_id in ruleset.rule_ids
    ]
    return row


def ruleset_version_to_domain(row: RulesetVersionORM) -> RulesetVersion:
    """Rebuild a :class:`RulesetVersion`, membership included.

    Members are re-sorted by the domain constructor, so a domain object never
    depends on the order the database returned rows in.
    """
    return RulesetVersion(
        id=RulesetVersionId(row.id),
        public_id=RulesetPublicId(row.public_id),
        status=RulesetStatus(row.status),
        manifest_hash=row.manifest_hash,
        created_at=row.created_at,
        rule_ids=tuple(ComputableRuleId(member.rule_id) for member in row.members),
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        legacy_id=row.legacy_id,
    )


def release_bundle_to_orm(release: ReleaseBundle) -> ReleaseBundleORM:
    """Build a persistence row from a :class:`ReleaseBundle`.

    The manifest is thawed into plain containers because psycopg's JSONB
    adapter needs real ``dict``/``list`` objects; the copy is fresh, so the
    driver cannot reach back into the frozen domain value.
    """
    return ReleaseBundleORM(
        id=release.id.value,
        public_id=release.public_id.value,
        software_version_id=release.software_version_id.value,
        dataset_version_id=release.dataset_version_id.value,
        ruleset_version_id=release.ruleset_version_id.value,
        manifest_json=thaw_json(release.manifest),
        manifest_hash=release.manifest_hash,
        status=release.status.value,
        created_at=release.created_at,
        activated_at=release.activated_at,
        activated_by=release.activated_by,
        legacy_id=release.legacy_id,
        notes=release.notes,
    )


def release_bundle_to_domain(row: ReleaseBundleORM) -> ReleaseBundle:
    """Rebuild a :class:`ReleaseBundle` from a persistence row.

    The manifest is re-frozen by the domain constructor, so a caller cannot
    edit a payload whose digest has already been recorded.
    """
    return ReleaseBundle(
        id=ReleaseBundleId(row.id),
        public_id=ReleasePublicId(row.public_id),
        software_version_id=SoftwareVersionId(row.software_version_id),
        dataset_version_id=DatasetVersionId(row.dataset_version_id),
        ruleset_version_id=RulesetVersionId(row.ruleset_version_id),
        manifest=row.manifest_json or {},
        manifest_hash=row.manifest_hash,
        status=ReleaseStatus(row.status),
        created_at=row.created_at,
        activated_at=row.activated_at,
        activated_by=row.activated_by,
        legacy_id=row.legacy_id,
        notes=row.notes,
    )


def active_release_to_domain(row: ActiveReleaseORM) -> ActiveRelease:
    """Rebuild the :class:`ActiveRelease` pointer from its singleton row."""
    return ActiveRelease(
        release_id=None if row.release_id is None else ReleaseBundleId(row.release_id),
        generation=row.generation,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
        singleton_id=row.singleton_id,
    )


def audit_event_to_orm(event: AuditEvent) -> AuditEventORM:
    """Build a persistence row from an :class:`AuditEvent`."""
    return AuditEventORM(
        id=event.id.value,
        action=event.action.value,
        actor=event.actor,
        object_type=event.object_type,
        object_id=event.object_id,
        previous_release_id=(None if event.previous_release_id is None
                             else event.previous_release_id.value),
        new_release_id=(None if event.new_release_id is None
                        else event.new_release_id.value),
        reason=event.reason,
        event_metadata=thaw_json(event.metadata),
        occurred_at=event.occurred_at,
    )


def audit_event_to_domain(row: AuditEventORM) -> AuditEvent:
    """Rebuild an :class:`AuditEvent` from a persistence row."""
    return AuditEvent(
        id=AuditEventId(row.id),
        action=AuditAction(row.action),
        actor=row.actor,
        object_type=row.object_type,
        object_id=row.object_id,
        occurred_at=row.occurred_at,
        reason=row.reason,
        previous_release_id=(None if row.previous_release_id is None
                             else ReleaseBundleId(row.previous_release_id)),
        new_release_id=(None if row.new_release_id is None
                        else ReleaseBundleId(row.new_release_id)),
        metadata=row.event_metadata or {},
    )
