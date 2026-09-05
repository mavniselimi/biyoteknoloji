# -*- coding: utf-8 -*-
"""SQLAlchemy ORM models - the ONLY module where mapped classes are defined.

These are persistence records, not domain objects. They never subclass a domain
dataclass and are never returned past the repository boundary: repositories
convert them through :mod:`pgx.infrastructure.db.mappers`.

Design choices that the migration and the constraint tests depend on:

* ``UUID(as_uuid=True)`` - identity is supplied by the application, so no
  server-side extension (``pgcrypto``/``uuid-ossp``) is required;
* ``JSONB`` for structured columns, so they are queryable and indexable;
* ``TIMESTAMP(timezone=True)`` everywhere - no naive instant is storable;
* named ``CheckConstraint``s carrying the lifecycle invariants, so the database
  refuses an unapproved ``VALIDATED`` row even if application code is bypassed.

Scope: WP-02 foundation tables, the WP-03 release registry, the WP-10 curation
workflow, the WP-11 rule and ruleset governance tables, and the WP-14
assessment tables. Users, validation cases and ingestion runs belong to later
work packages and are deliberately absent.

The WP-14 tables are append-only in the strongest sense the database can
express: migration 0009 installs triggers refusing ``UPDATE`` and ``DELETE`` on
every one of them. A completed assessment is a record of what a versioned
system calculated at a moment; editing one would make the audit trail describe
a calculation that never happened.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from typing import Any, List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pgx.infrastructure.db.base import Base

__all__ = [
    "ActiveReleaseORM",
    "AssessmentAxisORM",
    "AssessmentFindingEvidenceORM",
    "AssessmentFindingORM",
    "AssessmentMedicationORM",
    "AssessmentORM",
    "AuditEventORM",
    "RuleLifecycleEventORM",
    "RulesetApprovalORM",
    "RulesetBuildORM",
    "CurationAdjudicationORM",
    "CurationProvenanceVerificationORM",
    "CurationReviewORM",
    "CurationRevisionORM",
    "CurationRoleAssignmentORM",
    "CurationWorkItemEvidenceLinkORM",
    "CurationWorkItemORM",
    "ComputableRuleORM",
    "CuratedInterpretationORM",
    "DatasetVersionORM",
    "DrugAliasORM",
    "DrugORM",
    "EvidenceRecordORM",
    "GeneAliasORM",
    "GeneORM",
    "InterpretationEvidenceORM",
    "ReleaseBundleORM",
    "RuleEvidenceORM",
    "RulesetRuleORM",
    "RulesetVersionORM",
    "SoftwareVersionORM",
    "SourceRegistryORM",
    "SHA256_DIGEST_REGEX",
]

#: Canonical digest spelling enforced in the database, matching
#: pgx.domain.hashing.sha256_digest output.
SHA256_DIGEST_REGEX = r"^sha256:[0-9a-f]{64}$"

_DATASET_PUBLIC_ID_REGEX = r"^PGX-DATA-[0-9]{8}-[0-9]{3}$"
_RULESET_PUBLIC_ID_REGEX = r"^PGX-RULESET-[0-9]{8}-[0-9]{3}$"
_RELEASE_PUBLIC_ID_REGEX = r"^PGX-REL-[0-9]{8}-[0-9]{3}$"

_CURATION_STATUSES = ("RAW", "UNDER_REVIEW", "CURATED", "REJECTED")
_RULE_STATUSES = ("DRAFT", "CURATED", "VALIDATED", "DEPRECATED")
_DATASET_STATUSES = ("BUILDING", "QUALITY_CHECKED", "PUBLISHED", "RETIRED")
_SOURCE_ROLES = ("PRIMARY_GUIDELINE", "SUPPORTING_ANNOTATION", "REFERENCE_ONLY",
                 "INTERNAL_SYSTEM")
_ATTENTION_LEVELS = ("NOT_ASSESSED", "NO_ACTIVE_ATTENTION", "LOW", "MEDIUM", "HIGH")

#: What a *rule* may assert, which is narrower than what an assessment may
#: report. NOT_ASSESSED is a downstream coverage result meaning "we did not
#: look"; a rule authored to assert it in advance would be making a claim
#: about a case it has never seen. Migration 0008 carries the same list in
#: ``ck_computable_rules_outcome_is_authorable``.
_RULE_OUTCOME_LEVELS = ("NO_ACTIVE_ATTENTION", "LOW", "MEDIUM", "HIGH")
_RULESET_STATUSES = ("BUILDING", "VALIDATED", "FROZEN", "RETIRED")

#: How a ruleset build ended. Closed, and closed the same way in three places:
#: ``RulesetBuildRecord.__post_init__`` in ``pgx/rules/models.py`` refuses any
#: other value in the domain, migration 0008 carries the identical list in its
#: ``BUILD_OUTCOMES`` constant, and ``schemas/ruleset-build-log.schema.json``
#: publishes it. Spelled here rather than imported for the same reason every
#: other vocabulary above is: this module maps a *schema*, and a table
#: definition that changed because a domain module was refactored would be a
#: schema that drifted from its migration without a migration.
#:
#: REFUSED and FAILED are both kept because they are different facts. A refused
#: build is one the gates declined; a failed build is one that broke. A
#: vocabulary that collapsed them would make "why is there no artifact?"
#: unanswerable from the row.
_RULESET_BUILD_OUTCOMES = ("SUCCEEDED", "REFUSED", "FAILED")
_RELEASE_STATUSES = ("DRAFT", "ACTIVE", "ROLLED_BACK", "RETIRED")
_AUDIT_ACTIONS = ("RELEASE_REGISTERED", "RELEASE_ACTIVATED", "RELEASE_ROLLED_BACK",
                  "RELEASE_RETIRED", "LEGACY_BASELINE_REGISTERED",
                  "DATASET_BUILD_REGISTERED", "DATASET_QUALITY_CHECKED",
                  # WP-10 curation workflow. Widening only: every action that
                  # satisfied the previous list still satisfies this one.
                  "CURATION_WORK_ITEM_IMPORTED", "CURATION_REVISION_CREATED",
                  "CURATION_REVISION_SUBMITTED", "CURATION_CHANGES_REQUESTED",
                  "CURATION_APPROVED", "CURATION_REJECTED",
                  "CURATION_REFERRED_TO_ADJUDICATION", "CURATION_ADJUDICATED",
                  # WP-11 rule and ruleset lifecycle, widening again for the
                  # same reason. The two refusal actions are here deliberately:
                  # a validation that was refused is a thing that happened, and
                  # an audit trail that recorded only successes would be a
                  # record of what the system was willing to admit.
                  "RULE_DRAFTED", "RULE_CURATED", "RULE_VALIDATED",
                  "RULE_DEPRECATED", "RULE_VALIDATION_REFUSED",
                  "RULESET_CREATED", "RULESET_MEMBER_ADDED",
                  "RULESET_MEMBER_REMOVED", "RULESET_VALIDATED",
                  "RULESET_VALIDATION_REFUSED", "RULESET_REOPENED",
                  "RULESET_FROZEN", "RULESET_RETIRED",
                  # WP-14 assessment execution, widening once more. A refusal
                  # is recorded for the same reason WP-11's is: "what did this
                  # system decline to do, and why" is a question an audit log
                  # that held only successes could not answer.
                  "ASSESSMENT_COMPLETED", "ASSESSMENT_REFUSED")

#: WP-10 curation workflow vocabularies, spelled here so the ORM refuses the
#: same values migration 0007 refuses.
_REVIEW_DECISIONS = ("APPROVE", "REQUEST_CHANGES", "REJECT",
                     "REFER_TO_ADJUDICATION")
_ADJUDICATION_DECISIONS = ("APPROVE", "REQUEST_CHANGES", "REJECT")
_CURATION_ROLES = ("PROTOCOL_OWNER", "SCIENTIFIC_CURATOR",
                   "INDEPENDENT_SCIENTIFIC_REVIEWER", "ADJUDICATOR",
                   "DATA_PROVENANCE_STEWARD", "ENGINEERING_OBSERVER")
_REVIEWER_ROLES = ("INDEPENDENT_SCIENTIFIC_REVIEWER", "ADJUDICATOR")

#: The active-release pointer is a singleton. The row's primary key is pinned to
#: this value by a CHECK constraint, so a second pointer cannot be inserted and
#: activation always locks the same row.
ACTIVE_RELEASE_SINGLETON_ID = 1


def _in_list(column: str, values: tuple) -> str:
    """Render a SQL IN (...) predicate for a lifecycle CHECK constraint."""
    return "%s IN (%s)" % (column, ", ".join("'%s'" % value for value in values))


def _uuid_pk() -> Mapped[uuid.UUID]:
    """Primary key column: application-supplied UUID, no server default."""
    return mapped_column(UUID(as_uuid=True), primary_key=True)


def _created_at() -> Mapped[_dt.datetime]:
    """Timezone-aware creation timestamp."""
    return mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class SourceRegistryORM(Base):
    """Registered scientific or technical source."""

    __tablename__ = "source_registry"

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    version_policy: Mapped[str] = mapped_column(String(256), nullable=False)
    license_policy: Mapped[str] = mapped_column(String(256), nullable=False)
    citation_policy: Mapped[str] = mapped_column(String(256), nullable=False)
    release_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[_dt.datetime] = _created_at()
    legacy_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        CheckConstraint(_in_list("role", _SOURCE_ROLES), name="role_enum"),
        CheckConstraint("length(trim(source_key)) > 0", name="source_key_not_blank"),
        # A technical bookkeeping source can never back a release.
        CheckConstraint(
            "role <> 'INTERNAL_SYSTEM' OR release_eligible = false",
            name="internal_source_not_release_eligible"),
    )


class DatasetVersionORM(Base):
    """Immutable dataset build."""

    __tablename__ = "dataset_versions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    public_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    dq_report_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[_dt.datetime] = _created_at()
    approved_by: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    approved_at: Mapped[Optional[_dt.datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True)
    legacy_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        CheckConstraint(_in_list("status", _DATASET_STATUSES), name="status_enum"),
        CheckConstraint(
            "public_id ~ '%s'" % _DATASET_PUBLIC_ID_REGEX, name="public_id_format"),
        CheckConstraint(
            "manifest_hash ~ '%s'" % SHA256_DIGEST_REGEX, name="manifest_hash_format"),
        # A published dataset must name its approver and the moment of approval.
        CheckConstraint(
            "status <> 'PUBLISHED' OR ("
            " approved_by IS NOT NULL AND length(trim(approved_by)) > 0"
            " AND approved_at IS NOT NULL)",
            name="published_requires_approval"),
    )


class GeneORM(Base):
    """Canonical gene."""

    __tablename__ = "genes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    normalized_symbol: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True)
    preferred_name: Mapped[str] = mapped_column(String(256), nullable=False)
    external_ids: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict)
    created_at: Mapped[_dt.datetime] = _created_at()
    legacy_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    aliases: Mapped[List["GeneAliasORM"]] = relationship(
        back_populates="gene", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "normalized_symbol = upper(trim(normalized_symbol))",
            name="symbol_normalized"),
        CheckConstraint("length(trim(normalized_symbol)) > 0", name="symbol_not_blank"),
    )


class GeneAliasORM(Base):
    """Alternative spelling for a gene.

    An alias is unique *within* a gene, not globally: the same alias may
    legitimately point at two genes. That ambiguity is preserved for a WP-07
    resolution queue rather than being collapsed to whichever row was inserted
    first.
    """

    __tablename__ = "gene_aliases"

    gene_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("genes.id", ondelete="CASCADE"), primary_key=True)
    normalized_alias: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_alias: Mapped[str] = mapped_column(String(128), nullable=False)

    gene: Mapped["GeneORM"] = relationship(back_populates="aliases")

    __table_args__ = (
        UniqueConstraint("gene_id", "normalized_alias", name="uq_gene_aliases_gene_alias"),
        Index("ix_gene_aliases_normalized_alias", "normalized_alias"),
        CheckConstraint(
            "normalized_alias = upper(trim(normalized_alias))", name="alias_normalized"),
    )


class DrugORM(Base):
    """Canonical drug."""

    __tablename__ = "drugs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    normalized_name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    preferred_name: Mapped[str] = mapped_column(String(256), nullable=False)
    external_ids: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict)
    created_at: Mapped[_dt.datetime] = _created_at()
    legacy_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    aliases: Mapped[List["DrugAliasORM"]] = relationship(
        back_populates="drug", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "normalized_name = lower(trim(normalized_name))", name="name_normalized"),
        CheckConstraint("length(trim(normalized_name)) > 0", name="name_not_blank"),
    )


class DrugAliasORM(Base):
    """Alternative spelling for a drug; ambiguity is preserved, not resolved."""

    __tablename__ = "drug_aliases"

    drug_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drugs.id", ondelete="CASCADE"), primary_key=True)
    normalized_alias: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_alias: Mapped[str] = mapped_column(String(128), nullable=False)

    drug: Mapped["DrugORM"] = relationship(back_populates="aliases")

    __table_args__ = (
        UniqueConstraint("drug_id", "normalized_alias", name="uq_drug_aliases_drug_alias"),
        Index("ix_drug_aliases_normalized_alias", "normalized_alias"),
        CheckConstraint(
            "normalized_alias = lower(trim(normalized_alias))", name="alias_normalized"),
    )


class EvidenceRecordORM(Base):
    """Source truth. Carries no attention, risk, dose, or treatment column."""

    __tablename__ = "evidence_records"

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_registry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_registry.id", ondelete="RESTRICT"),
        nullable=False)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_versions.id", ondelete="RESTRICT"),
        nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(256), nullable=False)
    source_record_version: Mapped[str] = mapped_column(String(64), nullable=False)
    gene_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("genes.id", ondelete="RESTRICT"), nullable=True)
    drug_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drugs.id", ondelete="RESTRICT"), nullable=True)
    raw_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    source_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict)
    publication_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict)
    created_at: Mapped[_dt.datetime] = _created_at()
    legacy_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        # One source record version, from one source, in one dataset build.
        UniqueConstraint(
            "dataset_version_id", "source_registry_id", "source_record_id",
            "source_record_version", name="uq_evidence_records_provenance"),
        CheckConstraint("raw_hash ~ '%s'" % SHA256_DIGEST_REGEX, name="raw_hash_format"),
        CheckConstraint(
            "length(trim(source_record_id)) > 0", name="source_record_id_not_blank"),
        Index("ix_evidence_records_dataset_version_id", "dataset_version_id"),
        Index("ix_evidence_records_gene_id_drug_id", "gene_id", "drug_id"),
    )


class CuratedInterpretationORM(Base):
    """Human curation decision over evidence."""

    __tablename__ = "curated_interpretations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_phenotype: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    normalized_effect: Mapped[str] = mapped_column(String(128), nullable=False)
    significance: Mapped[str] = mapped_column(String(128), nullable=False)
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[_dt.datetime] = _created_at()
    reviewed_at: Mapped[Optional[_dt.datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True)
    legacy_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    evidence_links: Mapped[List["InterpretationEvidenceORM"]] = relationship(
        back_populates="interpretation", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        CheckConstraint(_in_list("status", _CURATION_STATUSES), name="status_enum"),
        CheckConstraint(
            "normalized_phenotype IS NULL OR normalized_phenotype IN "
            "('POOR', 'INTERMEDIATE', 'NORMAL', 'RAPID', 'ULTRARAPID', 'INDETERMINATE')",
            name="phenotype_enum"),
        # Curation must record who decided and why.
        CheckConstraint(
            "status <> 'CURATED' OR ("
            " rationale IS NOT NULL AND length(trim(rationale)) > 0"
            " AND reviewed_by IS NOT NULL AND length(trim(reviewed_by)) > 0"
            " AND reviewed_at IS NOT NULL)",
            name="curated_requires_review_metadata"),
    )


class InterpretationEvidenceORM(Base):
    """Link table: interpretation to the evidence it interprets."""

    __tablename__ = "interpretation_evidence"

    interpretation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("curated_interpretations.id", ondelete="CASCADE"), primary_key=True)
    evidence_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evidence_records.id", ondelete="RESTRICT"), primary_key=True)

    interpretation: Mapped["CuratedInterpretationORM"] = relationship(
        back_populates="evidence_links")

    __table_args__ = (
        Index("ix_interpretation_evidence_evidence_record_id", "evidence_record_id"),
    )


class ComputableRuleORM(Base):
    """Machine-evaluable rule derived from exactly one curated interpretation."""

    __tablename__ = "computable_rules"

    id: Mapped[uuid.UUID] = _uuid_pk()
    interpretation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("curated_interpretations.id", ondelete="RESTRICT"), nullable=False)
    condition_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    attention_level: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    approved_by: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[_dt.datetime] = _created_at()
    approved_at: Mapped[Optional[_dt.datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True)
    legacy_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # -- WP-11 -----------------------------------------------------------
    # Version lineage, the provenance a rule descends from pinned by identity
    # *and* by hash, and lifecycle state kept separate from content. Nullable
    # in the mapping because 0001 rows predate every one of them; 0008's check
    # constraints require each from the state at which it starts to mean
    # something, which is where the real enforcement belongs. A column that is
    # NOT NULL here but conditionally required there would be enforced twice
    # and consistently in neither place.
    rule_family_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True)
    supersedes_rule_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("computable_rules.id", ondelete="RESTRICT"),
        nullable=True)
    rule_schema_version: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True)
    condition_schema_version: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    # Bumped on every guarded UPDATE; the optimistic-concurrency token. Zero is
    # the pre-WP-11 value, so a stale row can never masquerade as a fresh one.
    lifecycle_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0")
    gene_canonical_key: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True)
    drug_canonical_key: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True)
    curation_work_item_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True)
    curation_revision_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True)
    curation_revision_hash: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True)
    approval_envelope_hash: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True)
    protocol_version: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    protocol_content_hash: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True)
    dataset_public_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    canonical_build_key: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True)
    canonical_build_content_hash: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True)
    evidence_build_key: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True)
    evidence_build_content_hash: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True)
    source_policy_version: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True)
    source_policy_content_hash: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True)
    validation_result_hash: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True)
    validated_by: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    validated_at: Mapped[Optional[_dt.datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True)
    deprecated_by: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    deprecated_at: Mapped[Optional[_dt.datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True)
    deprecation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[Optional[_dt.datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True)

    evidence_links: Mapped[List["RuleEvidenceORM"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        CheckConstraint(_in_list("status", _RULE_STATUSES), name="status_enum"),
        CheckConstraint(
            _in_list("attention_level", _ATTENTION_LEVELS), name="attention_level_enum"),
        # Narrower than the enum above, and deliberately a second constraint
        # rather than a replacement: the column's domain is the attention
        # vocabulary, and what a rule may *author* within it is a separate
        # rule that deserves its own name in a failure message.
        CheckConstraint(
            _in_list("attention_level", _RULE_OUTCOME_LEVELS),
            name="outcome_is_authorable"),
        CheckConstraint("rule_version >= 1", name="rule_version_positive"),
        # Approval may never be implied.
        CheckConstraint(
            "status <> 'VALIDATED' OR ("
            " approved_by IS NOT NULL AND length(trim(approved_by)) > 0"
            " AND approved_at IS NOT NULL)",
            name="validated_requires_approval"),
        UniqueConstraint("interpretation_id", "rule_version",
                         name="uq_computable_rules_interpretation_version"),
        Index("ix_computable_rules_status", "status"),
    )


class RuleEvidenceORM(Base):
    """Link table: rule to the evidence backing it (``SAFETY-INV-006``)."""

    __tablename__ = "rule_evidence"

    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("computable_rules.id", ondelete="CASCADE"), primary_key=True)
    evidence_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evidence_records.id", ondelete="RESTRICT"), primary_key=True)

    rule: Mapped["ComputableRuleORM"] = relationship(back_populates="evidence_links")

    __table_args__ = (
        Index("ix_rule_evidence_evidence_record_id", "evidence_record_id"),
    )


# ---------------------------------------------------------------------------
# WP-03 - version registry, release bundles, active pointer, audit trail
# ---------------------------------------------------------------------------


class SoftwareVersionORM(Base):
    """One registered build of this software.

    ``source_tree_hash`` is unique, not ``version``: two builds may legitimately
    declare the same version string, and the source tree is what actually
    distinguishes them. Making the declared version unique instead would refuse
    a real rebuild while allowing two different trees to share an identity.
    """

    __tablename__ = "software_versions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_commit: Mapped[str] = mapped_column(String(128), nullable=False)
    source_tree_hash: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    manifest_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    built_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)
    created_at: Mapped[_dt.datetime] = _created_at()
    build_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint("length(trim(version)) > 0", name="version_not_blank"),
        CheckConstraint("length(trim(source_commit)) > 0", name="source_commit_not_blank"),
        CheckConstraint(
            "source_tree_hash ~ '%s'" % SHA256_DIGEST_REGEX,
            name="source_tree_hash_format"),
        CheckConstraint(
            "manifest_hash ~ '%s'" % SHA256_DIGEST_REGEX, name="manifest_hash_format"),
    )


class RulesetVersionORM(Base):
    """Immutable, versioned collection of rules."""

    __tablename__ = "ruleset_versions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    public_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[_dt.datetime] = _created_at()
    approved_by: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    approved_at: Mapped[Optional[_dt.datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True)
    legacy_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # -- WP-11 -----------------------------------------------------------
    # ``manifest_hash`` (WP-03) is the hash of the published manifest document;
    # ``ruleset_content_hash`` is the semantic hash of the membership, which is
    # what determinism is asserted about. They are deliberately two columns:
    # collapsing them would make a manifest formatting change look like a
    # membership change, and a membership change look like nothing at all.
    ruleset_content_hash: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True)
    ruleset_schema_version: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True)
    lifecycle_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0")
    dataset_public_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    canonical_build_key: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True)
    canonical_build_content_hash: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True)
    evidence_build_key: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True)
    evidence_build_content_hash: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True)
    protocol_version: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    protocol_content_hash: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True)
    source_policy_version: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True)
    source_policy_content_hash: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True)
    approval_list_hash: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True)
    artifact_relative_path: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    frozen_by: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    frozen_at: Mapped[Optional[_dt.datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True)
    retired_by: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    retired_at: Mapped[Optional[_dt.datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True)
    retirement_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[Optional[_dt.datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True)

    members: Mapped[List["RulesetRuleORM"]] = relationship(
        back_populates="ruleset", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        CheckConstraint(_in_list("status", _RULESET_STATUSES), name="status_enum"),
        CheckConstraint(
            "public_id ~ '%s'" % _RULESET_PUBLIC_ID_REGEX, name="public_id_format"),
        CheckConstraint(
            "manifest_hash ~ '%s'" % SHA256_DIGEST_REGEX, name="manifest_hash_format"),
        # A frozen or validated ruleset must name its approver.
        CheckConstraint(
            "status NOT IN ('VALIDATED', 'FROZEN') OR ("
            " approved_by IS NOT NULL AND length(trim(approved_by)) > 0"
            " AND approved_at IS NOT NULL)",
            name="approved_requires_approval_metadata"),
    )


class RulesetRuleORM(Base):
    """Pinned membership: exactly which rules a ruleset version contains.

    The composite primary key is what forbids duplicate membership - a rule
    counted twice would be weighted twice by anything that reads the set.

    ``ondelete`` is asymmetric on purpose. Deleting a ruleset takes its
    membership rows with it (``CASCADE``): the rows describe that ruleset and
    mean nothing without it. Deleting a *rule* that a ruleset pins is refused
    (``RESTRICT``): a released ruleset that silently loses a member is exactly
    the drift the version registry exists to prevent.
    """

    __tablename__ = "ruleset_rules"

    ruleset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ruleset_versions.id", ondelete="CASCADE"), primary_key=True)
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("computable_rules.id", ondelete="RESTRICT"), primary_key=True)

    # -- WP-11 -----------------------------------------------------------
    # The membership row pins the *content* of the rule it admits, not just its
    # identity. A rule row edited after admission would keep the same id and
    # break this hash, which is how a frozen ruleset detects drift it would
    # otherwise inherit silently.
    member_content_hash: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True)
    rule_family_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True)
    rule_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    added_by: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    added_at: Mapped[_dt.datetime] = _created_at()

    ruleset: Mapped["RulesetVersionORM"] = relationship(back_populates="members")

    __table_args__ = (
        Index("ix_ruleset_rules_rule_id", "rule_id"),
    )


class ReleaseBundleORM(Base):
    """The pinned (software, dataset, ruleset) triple.

    Every foreign key is ``RESTRICT``: deleting a software build, dataset or
    ruleset that a release pins would leave the release naming something that
    no longer exists, and a release that cannot say what it ran is worse than
    no release at all.
    """

    __tablename__ = "release_bundles"

    id: Mapped[uuid.UUID] = _uuid_pk()
    public_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    software_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("software_versions.id", ondelete="RESTRICT"), nullable=False)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dataset_versions.id", ondelete="RESTRICT"), nullable=False)
    ruleset_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ruleset_versions.id", ondelete="RESTRICT"), nullable=False)
    manifest_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[_dt.datetime] = _created_at()
    activated_at: Mapped[Optional[_dt.datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True)
    activated_by: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    legacy_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(_in_list("status", _RELEASE_STATUSES), name="status_enum"),
        CheckConstraint(
            "public_id ~ '%s'" % _RELEASE_PUBLIC_ID_REGEX, name="public_id_format"),
        CheckConstraint(
            "manifest_hash ~ '%s'" % SHA256_DIGEST_REGEX, name="manifest_hash_format"),
        # A release that reached ACTIVE must record who put it there and when;
        # a DRAFT release must not pretend it ever ran.
        CheckConstraint(
            "(status IN ('ACTIVE', 'ROLLED_BACK') AND activated_at IS NOT NULL"
            " AND activated_by IS NOT NULL AND length(trim(activated_by)) > 0)"
            " OR (status = 'DRAFT' AND activated_at IS NULL AND activated_by IS NULL)"
            " OR status = 'RETIRED'",
            name="activation_metadata_matches_status"),
        Index("ix_release_bundles_status", "status"),
    )


class ActiveReleaseORM(Base):
    """The singleton pointer naming the release currently in force.

    One row, forever. ``singleton_id`` is constrained to a single legal value,
    so a second pointer cannot be inserted and every activation locks the same
    row with ``SELECT ... FOR UPDATE``. Without that constraint, two pointers
    could exist and each activation would lock a different one - which is to
    say, nothing would be locked at all.

    ``release_id`` is nullable: before the first activation there genuinely is
    no active release, and saying so is better than pointing somewhere
    arbitrary.
    """

    __tablename__ = "active_release"

    singleton_id: Mapped[int] = mapped_column(Integer, primary_key=True,
                                              autoincrement=False)
    release_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("release_bundles.id", ondelete="RESTRICT"), nullable=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[_dt.datetime] = _created_at()
    updated_by: Mapped[str] = mapped_column(String(256), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "singleton_id = %d" % ACTIVE_RELEASE_SINGLETON_ID, name="singleton"),
        CheckConstraint("generation >= 0", name="generation_not_negative"),
        CheckConstraint(
            "length(trim(updated_by)) > 0", name="updated_by_not_blank"),
        # A pointer that has moved must name the release it moved to.
        CheckConstraint(
            "generation = 0 OR release_id IS NOT NULL",
            name="moved_pointer_names_a_release"),
    )


class AuditEventORM(Base):
    """Append-only record of a release lifecycle event.

    Append-only is enforced in three places, deliberately: the port offers no
    update or delete, the repository implements neither, and migration 0002
    installs a trigger that refuses ``UPDATE`` and ``DELETE`` outright. The
    first two are application promises; only the third survives someone with a
    ``psql`` prompt.
    """

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(256), nullable=False)
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[str] = mapped_column(String(128), nullable=False)
    previous_release_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("release_bundles.id", ondelete="RESTRICT"), nullable=True)
    new_release_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("release_bundles.id", ondelete="RESTRICT"), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    event_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict)
    occurred_at: Mapped[_dt.datetime] = _created_at()

    __table_args__ = (
        CheckConstraint(_in_list("action", _AUDIT_ACTIONS), name="action_enum"),
        CheckConstraint("length(trim(actor)) > 0", name="actor_not_blank"),
        CheckConstraint("length(trim(object_type)) > 0", name="object_type_not_blank"),
        CheckConstraint("length(trim(object_id)) > 0", name="object_id_not_blank"),
        # An event claiming a pointer change must name the release it moved to.
        CheckConstraint(
            "action NOT IN ('RELEASE_ACTIVATED', 'RELEASE_ROLLED_BACK')"
            " OR new_release_id IS NOT NULL",
            name="pointer_event_names_new_release"),
        Index("ix_audit_events_object_type_object_id", "object_type", "object_id"),
        Index("ix_audit_events_occurred_at", "occurred_at"),
    )


# ---------------------------------------------------------------------------
# WP-10 curation workflow
# ---------------------------------------------------------------------------
#
# These mirror migration 0007. The constraints are repeated here rather than
# left to the migration alone because these classes are what a developer reads
# when they wonder what a column may hold, and a model that admitted values the
# database refuses would send them looking in the wrong place. The migration
# stays authoritative; a test compares the two.


class CurationWorkItemORM(Base):
    """One curation question, and where it has got to.

    ``version`` is the optimistic-concurrency counter. Nothing in this codebase
    writes ``status`` with a plain ``UPDATE``: the repository issues a guarded
    statement that names the expected status and version, and migration 0007
    installs a trigger that refuses an update advancing neither. Two reviewers
    deciding one state is the failure this prevents.
    """

    __tablename__ = "curation_work_items"

    id: Mapped[uuid.UUID] = _uuid_pk()
    work_item_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False,
                                        server_default="RAW")
    version: Mapped[int] = mapped_column(Integer, nullable=False,
                                         server_default="0")
    question_id: Mapped[str] = mapped_column(String(128), nullable=False)
    gene_canonical_key: Mapped[str] = mapped_column(String(128), nullable=False)
    drug_canonical_key: Mapped[str] = mapped_column(String(128), nullable=False)
    current_revision_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True)
    submitted_revision_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    legacy_proposal_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True)
    legacy_values: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                                default=dict)
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[_dt.datetime] = _created_at()
    updated_at: Mapped[Optional[_dt.datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("work_item_id", name="work_item_id"),
        UniqueConstraint("legacy_proposal_id", name="legacy_proposal_id"),
        CheckConstraint(_in_list("status", _CURATION_STATUSES),
                        name="status_enum"),
        CheckConstraint("version >= 0", name="version_non_negative"),
        CheckConstraint("length(trim(work_item_id)) > 0", name="id_not_blank"),
        CheckConstraint("length(trim(created_by)) > 0",
                        name="created_by_not_blank"),
        # An item under review names what is under review; a decided one names
        # what was decided. Without it, "which conclusion was approved" has no
        # answer on the row that claims one was.
        CheckConstraint(
            "status <> 'UNDER_REVIEW' OR submitted_revision_id IS NOT NULL",
            name="under_review_names_revision"),
        CheckConstraint(
            "status NOT IN ('CURATED', 'REJECTED')"
            " OR submitted_revision_id IS NOT NULL",
            name="terminal_needs_revision"),
        CheckConstraint("jsonb_typeof(legacy_values) = 'object'",
                        name="legacy_values_object"),
        Index("ix_curation_work_items_status", "status"),
        Index("ix_curation_work_items_entities", "gene_canonical_key",
              "drug_canonical_key"),
        Index("ix_curation_work_items_question_id", "question_id"),
    )


class CurationRevisionORM(Base):
    """One immutable version of a curation payload.

    There is no update path: the repository offers ``add`` and reads, and
    migration 0007 refuses ``UPDATE`` and ``DELETE`` at the row. A revision
    records what somebody claimed at a moment; editing it would make every
    review that pinned its hash describe content that no longer exists.
    """

    __tablename__ = "curation_revisions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    revision_id: Mapped[str] = mapped_column(String(128), nullable=False)
    work_item_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("curation_work_items.work_item_id", ondelete="RESTRICT"),
        nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_revision_id: Mapped[Optional[str]] = mapped_column(
        String(128),
        ForeignKey("curation_revisions.revision_id", ondelete="RESTRICT"),
        nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(128), nullable=False)
    protocol_content_hash: Mapped[str] = mapped_column(String(80),
                                                       nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
    evidence_build_content_hash: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True)
    authored_by: Mapped[str] = mapped_column(String(256), nullable=False)
    authored_by_role: Mapped[str] = mapped_column(String(48), nullable=False)
    authored_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    workflow_model_version: Mapped[str] = mapped_column(String(64),
                                                        nullable=False)

    __table_args__ = (
        UniqueConstraint("revision_id", name="revision_id"),
        UniqueConstraint("work_item_id", "revision_number",
                         name="work_item_number"),
        UniqueConstraint("work_item_id", "content_hash",
                         name="work_item_content"),
        CheckConstraint("revision_number >= 1", name="number_from_one"),
        # Revision 1 has no parent; every later one names its parent. A lineage
        # with a gap cannot be reconstructed, and reconstructing it is the
        # whole point of keeping superseded revisions.
        CheckConstraint(
            "(revision_number = 1 AND parent_revision_id IS NULL)"
            " OR (revision_number > 1 AND parent_revision_id IS NOT NULL)",
            name="lineage_complete"),
        CheckConstraint("parent_revision_id IS DISTINCT FROM revision_id",
                        name="not_own_parent"),
        CheckConstraint("authored_by_role = 'SCIENTIFIC_CURATOR'",
                        name="author_role"),
        CheckConstraint("length(trim(authored_by)) > 0",
                        name="author_not_blank"),
        CheckConstraint("content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                        name="content_hash_format"),
        CheckConstraint("protocol_content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                        name="protocol_hash_format"),
        CheckConstraint("jsonb_typeof(payload) = 'object'",
                        name="payload_object"),
        CheckConstraint(
            "jsonb_array_length(evidence -> 'evidence_record_uuids') >= 1",
            name="cites_evidence"),
        Index("ix_curation_revisions_work_item_id", "work_item_id"),
        Index("ix_curation_revisions_content_hash", "content_hash"),
    )


class CurationReviewORM(Base):
    """One independent reviewer's decision about one submitted revision.

    ``author_actor_id`` is stored on the review so the separation rule is a
    single-row check. A constraint that had to join to ``curation_revisions``
    could be satisfied at insert and falsified later; this one cannot.
    """

    __tablename__ = "curation_reviews"

    id: Mapped[uuid.UUID] = _uuid_pk()
    review_id: Mapped[str] = mapped_column(String(128), nullable=False)
    work_item_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("curation_work_items.work_item_id", ondelete="RESTRICT"),
        nullable=False)
    revision_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("curation_revisions.revision_id", ondelete="RESTRICT"),
        nullable=False)
    revision_content_hash: Mapped[str] = mapped_column(String(80),
                                                       nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewed_by: Mapped[str] = mapped_column(String(256), nullable=False)
    reviewed_by_role: Mapped[str] = mapped_column(String(48), nullable=False)
    reviewed_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)
    author_actor_id: Mapped[str] = mapped_column(String(256), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    findings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    protocol_content_hash: Mapped[str] = mapped_column(String(80),
                                                       nullable=False)
    evidence_build_content_hash: Mapped[str] = mapped_column(String(80),
                                                             nullable=False)
    work_item_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)

    __table_args__ = (
        UniqueConstraint("review_id", name="review_id"),
        # One reviewer decides one work-item version once. A second row would
        # be a reviewer changing their mind by inserting rather than by
        # reviewing the next version.
        UniqueConstraint("work_item_id", "work_item_version", "reviewed_by",
                         name="version_reviewer"),
        CheckConstraint(_in_list("decision", _REVIEW_DECISIONS),
                        name="decision_enum"),
        CheckConstraint(_in_list("reviewed_by_role", _REVIEWER_ROLES),
                        name="reviewer_role"),
        CheckConstraint(
            "lower(btrim(reviewed_by)) <> lower(btrim(author_actor_id))",
            name="reviewer_not_author"),
        CheckConstraint("length(trim(rationale)) >= 24",
                        name="rationale_substantive"),
        CheckConstraint("content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                        name="content_hash_format"),
        CheckConstraint("revision_content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                        name="revision_hash_format"),
        CheckConstraint("work_item_version >= 0", name="version_non_negative"),
        Index("ix_curation_reviews_work_item_id", "work_item_id"),
        Index("ix_curation_reviews_revision_id", "revision_id"),
    )


class CurationAdjudicationORM(Base):
    """A third named person settling a dispute, with both positions kept.

    ``curator_position`` and ``reviewer_position`` are required non-empty
    documents. An adjudication that replaced them would erase the disagreement
    it was called to settle, and nobody could later check the adjudicator's
    reasoning against what the two actually said.
    """

    __tablename__ = "curation_adjudications"

    id: Mapped[uuid.UUID] = _uuid_pk()
    adjudication_id: Mapped[str] = mapped_column(String(128), nullable=False)
    work_item_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("curation_work_items.work_item_id", ondelete="RESTRICT"),
        nullable=False)
    revision_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("curation_revisions.revision_id", ondelete="RESTRICT"),
        nullable=False)
    revision_content_hash: Mapped[str] = mapped_column(String(80),
                                                       nullable=False)
    adjudicated_by: Mapped[str] = mapped_column(String(256), nullable=False)
    adjudicated_by_role: Mapped[str] = mapped_column(String(48),
                                                     nullable=False)
    adjudicated_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    curator_actor_id: Mapped[str] = mapped_column(String(256), nullable=False)
    reviewer_actor_id: Mapped[str] = mapped_column(String(256), nullable=False)
    curator_position: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reviewer_position: Mapped[dict] = mapped_column(JSONB, nullable=False)
    disputed_evidence_uuids: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list)
    work_item_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)

    __table_args__ = (
        UniqueConstraint("adjudication_id", name="adjudication_id"),
        CheckConstraint(_in_list("decision", _ADJUDICATION_DECISIONS),
                        name="decision_enum"),
        CheckConstraint("adjudicated_by_role = 'ADJUDICATOR'", name="role"),
        # Somebody breaking a tie they are a side of is not adjudication.
        CheckConstraint(
            "lower(btrim(adjudicated_by)) NOT IN ("
            "lower(btrim(curator_actor_id)), lower(btrim(reviewer_actor_id)))",
            name="adjudicator_is_third_party"),
        CheckConstraint(
            "lower(btrim(curator_actor_id)) <> lower(btrim(reviewer_actor_id))",
            name="parties_differ"),
        CheckConstraint("jsonb_typeof(curator_position) = 'object'"
                        " AND curator_position <> '{}'::jsonb",
                        name="curator_position_present"),
        CheckConstraint("jsonb_typeof(reviewer_position) = 'object'"
                        " AND reviewer_position <> '{}'::jsonb",
                        name="reviewer_position_present"),
        CheckConstraint("length(trim(rationale)) >= 24", name="rationale"),
        CheckConstraint("content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                        name="hash_format"),
        Index("ix_curation_adjudications_work_item_id", "work_item_id"),
    )


class CurationProvenanceVerificationORM(Base):
    """A steward's statement that the cited evidence traces back to raw bytes.

    ``all_traces_verified`` has no default. A steward states whether the traces
    verified; a default would answer for them, and "nobody said" would become
    indistinguishable from "somebody checked".
    """

    __tablename__ = "curation_provenance_verifications"

    id: Mapped[uuid.UUID] = _uuid_pk()
    verification_id: Mapped[str] = mapped_column(String(128), nullable=False)
    work_item_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("curation_work_items.work_item_id", ondelete="RESTRICT"),
        nullable=False)
    verified_by: Mapped[str] = mapped_column(String(256), nullable=False)
    verified_by_role: Mapped[str] = mapped_column(String(48), nullable=False)
    verified_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)
    evidence_record_uuids: Mapped[list] = mapped_column(JSONB, nullable=False)
    all_traces_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    problems: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("verification_id", name="verification_id"),
        CheckConstraint("verified_by_role = 'DATA_PROVENANCE_STEWARD'",
                        name="role"),
        CheckConstraint("all_traces_verified = false OR problems = '[]'::jsonb",
                        name="verified_has_no_problems"),
        CheckConstraint("jsonb_array_length(evidence_record_uuids) >= 1",
                        name="names_records"),
        Index("ix_curation_provenance_work_item_id", "work_item_id"),
    )


class CurationWorkItemEvidenceLinkORM(Base):
    """Which evidence a work item is about, as far as anyone currently knows.

    ``reviewed`` defaults to false. The links imported from WP-08 record what
    an old interpretation was about; nobody has confirmed that the evidence
    supports anything, and a default of true would assert that they had.
    """

    __tablename__ = "curation_work_item_evidence_links"

    work_item_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("curation_work_items.work_item_id", ondelete="CASCADE"),
        primary_key=True)
    evidence_record_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evidence_records.id", ondelete="RESTRICT"),
        primary_key=True)
    link_basis: Mapped[str] = mapped_column(Text, nullable=False)
    reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                           server_default="false")
    linked_at: Mapped[_dt.datetime] = _created_at()

    __table_args__ = (
        Index("ix_curation_links_evidence_record_uuid", "evidence_record_uuid"),
    )


class CurationRoleAssignmentORM(Base):
    """Who may do what. Empty in this repository, and that is the point.

    No production identity exists to assign a role to; WP-23 owns
    authentication. The table exists so the empty set is queryable rather than
    implied by absence, and ``synthetic_prefix`` requires ``synthetic`` to be
    true exactly for ids beginning ``TEST-`` - so a fixture cannot pose as a
    person and a person cannot be handed a fixture's id.
    """

    __tablename__ = "curation_role_assignments"

    actor_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    role: Mapped[str] = mapped_column(String(48), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False)
    assigned_by: Mapped[str] = mapped_column(String(256), nullable=False)
    assigned_at: Mapped[_dt.datetime] = _created_at()
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(_in_list("role", _CURATION_ROLES), name="role_enum"),
        CheckConstraint("length(trim(display_name)) > 0", name="named"),
        CheckConstraint("synthetic = (actor_id LIKE 'TEST-%')",
                        name="synthetic_prefix"),
        Index("ix_curation_role_assignments_role", "role"),
    )


# ---------------------------------------------------------------------------
# WP-11 governed rules and immutable rulesets
# ---------------------------------------------------------------------------
#
# The rule and ruleset tables themselves were created by 0001 and 0002 and are
# mapped above; migration 0008 adds columns to them, and these three classes
# map the tables 0008 creates. Splitting the mapping this way keeps one answer
# to "what rules exist" rather than a WP-11 shadow of the same data.


class RuleLifecycleEventORM(Base):
    """One recorded rule transition: who moved it, from where, and why.

    Append-only, enforced by ``trg_rule_lifecycle_events_append_only``. It
    duplicates a little of what the audit trail holds, deliberately: the audit
    trail answers "what happened in this system", and this table answers "how
    did this rule reach its current state", which is the question a scientist
    reviewing a rule actually asks.
    """

    __tablename__ = "rule_lifecycle_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("computable_rules.id", ondelete="RESTRICT"), nullable=False)
    from_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(256), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(48), nullable=False)
    occurred_at: Mapped[_dt.datetime] = _created_at()
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    validation_result_hash: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True)
    audit_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_events.id", ondelete="RESTRICT"),
        nullable=True)

    __table_args__ = (
        CheckConstraint(_in_list("to_status", _RULE_STATUSES),
                        name="to_status_enum"),
        CheckConstraint(
            "from_status IS NULL OR " + _in_list("from_status", _RULE_STATUSES),
            name="from_status_enum"),
        CheckConstraint("length(trim(actor)) > 0", name="actor_not_blank"),
        CheckConstraint("content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                        name="content_hash_format"),
        Index("ix_rule_lifecycle_events_rule_id", "rule_id"),
    )


class RulesetBuildORM(Base):
    """One build attempt of one ruleset.

    Operational, and kept out of the manifest for that reason: a ruleset's
    identity must not change because it was rebuilt on another machine at
    another time. Append-only, so a build that refused stays on the record.
    """

    __tablename__ = "ruleset_builds"

    id: Mapped[uuid.UUID] = _uuid_pk()
    ruleset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ruleset_versions.id", ondelete="RESTRICT"), nullable=False)
    started_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)
    completed_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)
    built_by: Mapped[str] = mapped_column(String(256), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    manifest_hash: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    ruleset_content_hash: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False,
                                              server_default="0")
    issue_codes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    artifact_relative_path: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True)

    __table_args__ = (
        CheckConstraint(_in_list("outcome", _RULESET_BUILD_OUTCOMES),
                        name="outcome_enum"),
        CheckConstraint("completed_at >= started_at",
                        name="completed_after_started"),
        # A successful build produced an artifact; a refused one did not, and
        # a row claiming both would describe a build that did not happen.
        CheckConstraint(
            "outcome <> 'SUCCEEDED' OR (manifest_hash IS NOT NULL"
            " AND ruleset_content_hash IS NOT NULL"
            " AND artifact_relative_path IS NOT NULL AND member_count > 0)",
            name="succeeded_has_artifact"),
        Index("ix_ruleset_builds_ruleset_id", "ruleset_id"),
    )


class RulesetApprovalORM(Base):
    """One member rule's approval chain, captured into one ruleset.

    Copied rather than referenced so a frozen artifact carries its own evidence
    of governance: a list that pointed back at a mutable table would let a
    ruleset's approvals change after it was frozen.
    """

    __tablename__ = "ruleset_approvals"

    id: Mapped[uuid.UUID] = _uuid_pk()
    ruleset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ruleset_versions.id", ondelete="RESTRICT"), nullable=False)
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("computable_rules.id", ondelete="RESTRICT"), nullable=False)
    rule_family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                                      nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    approval_envelope_hash: Mapped[str] = mapped_column(String(80),
                                                        nullable=False)
    curation_revision_id: Mapped[str] = mapped_column(String(128), nullable=False)
    curation_revision_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    reviewed_by: Mapped[str] = mapped_column(String(256), nullable=False)
    approved_by: Mapped[str] = mapped_column(String(256), nullable=False)
    validated_by: Mapped[str] = mapped_column(String(256), nullable=False)
    validated_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("ruleset_id", "rule_id", name="ruleset_rule"),
        # Separation of duties, on the row, without a join.
        CheckConstraint("lower(btrim(created_by)) <> lower(btrim(reviewed_by))",
                        name="reviewer_is_not_author"),
        CheckConstraint("lower(btrim(created_by)) <> lower(btrim(approved_by))",
                        name="approver_is_not_author"),
        CheckConstraint("lower(btrim(created_by)) <> lower(btrim(validated_by))",
                        name="validator_is_not_author"),
        CheckConstraint("rule_content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                        name="rule_hash_format"),
        CheckConstraint("approval_envelope_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                        name="envelope_hash_format"),
        Index("ix_ruleset_approvals_rule_id", "rule_id"),
    )


# ---------------------------------------------------------------------------
# WP-14 - deterministic assessments
# ---------------------------------------------------------------------------


class AssessmentORM(Base):
    """One completed assessment, immutable after insert.

    Carries the whole pinned version set as NOT NULL columns rather than as a
    JSON blob, because ``SAFETY-INV-007`` is a *constraint*: an assessment
    that cannot name the software, dataset and ruleset it ran against is not
    reproducible and must not be storable. A nullable column would make that a
    convention.

    ``input_snapshot`` and ``output_snapshot`` hold the canonical documents the
    hashes cover, so a stored assessment can be re-verified later without
    trusting the row: recompute the digest and compare.
    """

    __tablename__ = "assessments"

    id: Mapped[uuid.UUID] = _uuid_pk()
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("release_bundles.id", ondelete="RESTRICT"), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    input_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    case_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    actor: Mapped[str] = mapped_column(String(256), nullable=False)

    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    output_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB,
                                                            nullable=False)
    output_hash: Mapped[str] = mapped_column(String(80), nullable=False)

    overall_coverage: Mapped[str] = mapped_column(String(32), nullable=False)
    overall_attention: Mapped[str] = mapped_column(String(32), nullable=False)

    # -- the pinned version set (SAFETY-INV-007) -------------------------
    release_public_id: Mapped[str] = mapped_column(String(128), nullable=False)
    release_manifest_hash: Mapped[str] = mapped_column(String(80),
                                                       nullable=False)
    active_pointer_generation: Mapped[int] = mapped_column(Integer,
                                                           nullable=False)
    software_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("software_versions.id", ondelete="RESTRICT"),
        nullable=False)
    software_version: Mapped[str] = mapped_column(String(128), nullable=False)
    software_source_tree_hash: Mapped[str] = mapped_column(String(80),
                                                           nullable=False)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dataset_versions.id", ondelete="RESTRICT"), nullable=False)
    dataset_public_id: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_build_content_hash: Mapped[str] = mapped_column(String(80),
                                                              nullable=False)
    ruleset_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ruleset_versions.id", ondelete="RESTRICT"), nullable=False)
    ruleset_public_id: Mapped[str] = mapped_column(String(128), nullable=False)
    ruleset_content_hash: Mapped[str] = mapped_column(String(80),
                                                      nullable=False)
    evidence_build_key: Mapped[str] = mapped_column(String(256),
                                                    nullable=False)
    evidence_build_content_hash: Mapped[str] = mapped_column(String(80),
                                                             nullable=False)
    coverage_manifest_hash: Mapped[str] = mapped_column(String(80),
                                                        nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(128), nullable=False)
    protocol_content_hash: Mapped[str] = mapped_column(String(80),
                                                       nullable=False)
    source_policy_version: Mapped[str] = mapped_column(String(128),
                                                       nullable=False)
    source_policy_content_hash: Mapped[str] = mapped_column(String(80),
                                                            nullable=False)

    created_at: Mapped[_dt.datetime] = _created_at()
    completed_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)

    medications: Mapped[List["AssessmentMedicationORM"]] = relationship(
        back_populates="assessment")

    __table_args__ = (
        # PILOT is disabled in P0, so it is not storable. A row that could
        # express one would outlive the runtime check that refuses it.
        CheckConstraint("mode IN ('DEMO', 'VALIDATION')", name="mode_enum"),
        CheckConstraint(
            "input_kind IN ('SYNTHETIC_PHENOTYPE_PROFILE', "
            "'PROTOCOL_DEFINED_PHENOTYPE_PROFILE', 'PUBLIC_DEMO_PROFILE', "
            "'VERSIONED_VALIDATION_CASE', 'MEDICATION_NAME_LIST')",
            name="input_kind_enum"),
        CheckConstraint(
            "overall_coverage IN ('FULL', 'PARTIAL', 'INSUFFICIENT', "
            "'UNSUPPORTED_DRUG', 'UNSUPPORTED_PHENOTYPE', 'SOURCE_CONFLICT')",
            name="overall_coverage_enum"),
        CheckConstraint(
            "overall_attention IN ('NOT_ASSESSED', 'NO_ACTIVE_ATTENTION', "
            "'LOW', 'MEDIUM', 'HIGH')", name="overall_attention_enum"),
        # SAFETY-INV-001, on the row: a reassuring overall level may accompany
        # only FULL overall coverage.
        CheckConstraint(
            "overall_attention <> 'NO_ACTIVE_ATTENTION' "
            "OR overall_coverage = 'FULL'",
            name="no_active_attention_requires_full_coverage"),
        # ... and the reverse: FULL coverage means everything expected was
        # evaluated, which cannot coexist with "we did not look".
        CheckConstraint(
            "overall_coverage <> 'FULL' OR overall_attention <> 'NOT_ASSESSED'",
            name="full_coverage_is_not_unassessed"),
        CheckConstraint("input_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                        name="input_hash_format"),
        CheckConstraint("output_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                        name="output_hash_format"),
        CheckConstraint("release_manifest_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                        name="release_manifest_hash_format"),
        CheckConstraint("ruleset_content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                        name="ruleset_content_hash_format"),
        CheckConstraint("coverage_manifest_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                        name="coverage_manifest_hash_format"),
        CheckConstraint("active_pointer_generation >= 0",
                        name="pointer_generation_non_negative"),
        Index("ix_assessments_release_id", "release_id"),
        Index("ix_assessments_output_hash", "output_hash"),
        Index("ix_assessments_input_hash", "input_hash"),
    )


class AssessmentMedicationORM(Base):
    """One requested medication's calculated result."""

    __tablename__ = "assessment_medications"

    id: Mapped[uuid.UUID] = _uuid_pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    drug_canonical_key: Mapped[str] = mapped_column(String(256),
                                                    nullable=False)
    requested_value: Mapped[str] = mapped_column(String(256), nullable=False)
    attention_level: Mapped[str] = mapped_column(String(32), nullable=False)
    coverage_status: Mapped[str] = mapped_column(String(32), nullable=False)
    coverage_reason_codes: Mapped[list[Any]] = mapped_column(JSONB,
                                                             nullable=False)
    axis_count: Mapped[int] = mapped_column(Integer, nullable=False)
    conflicted_axis_count: Mapped[int] = mapped_column(Integer, nullable=False)

    assessment: Mapped["AssessmentORM"] = relationship(
        back_populates="medications")

    __table_args__ = (
        UniqueConstraint("assessment_id", "drug_canonical_key",
                         name="assessment_drug"),
        UniqueConstraint("assessment_id", "ordinal",
                         name="assessment_ordinal"),
        CheckConstraint(
            "attention_level IN ('NOT_ASSESSED', 'NO_ACTIVE_ATTENTION', "
            "'LOW', 'MEDIUM', 'HIGH')", name="attention_enum"),
        CheckConstraint(
            "coverage_status IN ('FULL', 'PARTIAL', 'INSUFFICIENT', "
            "'UNSUPPORTED_DRUG', 'UNSUPPORTED_PHENOTYPE', 'SOURCE_CONFLICT')",
            name="coverage_enum"),
        CheckConstraint(
            "attention_level <> 'NO_ACTIVE_ATTENTION' "
            "OR coverage_status = 'FULL'",
            name="no_active_attention_needs_full"),
        # A non-FULL coverage row carries at least one machine-readable
        # reason; unexplained absence is how absence becomes reassurance.
        CheckConstraint(
            "coverage_status = 'FULL' "
            "OR jsonb_array_length(coverage_reason_codes) >= 1",
            name="non_full_coverage_has_reasons"),
        CheckConstraint(
            "coverage_status <> 'FULL' "
            "OR jsonb_array_length(coverage_reason_codes) = 0",
            name="full_coverage_has_no_reason"),
        CheckConstraint("ordinal >= 0", name="ordinal_non_negative"),
        Index("ix_assessment_medications_assessment_id", "assessment_id"),
    )


class AssessmentAxisORM(Base):
    """One drug-gene axis: what could be evaluated for it, and why not."""

    __tablename__ = "assessment_axes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False)
    medication_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessment_medications.id", ondelete="CASCADE"),
        nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    drug_canonical_key: Mapped[str] = mapped_column(String(256),
                                                    nullable=False)
    gene_canonical_key: Mapped[str] = mapped_column(String(128),
                                                    nullable=False)
    observed_phenotype: Mapped[Optional[str]] = mapped_column(String(32),
                                                              nullable=True)
    observation_state: Mapped[str] = mapped_column(String(32), nullable=False)
    coverage_status: Mapped[str] = mapped_column(String(32), nullable=False)
    coverage_reason_codes: Mapped[list[Any]] = mapped_column(JSONB,
                                                             nullable=False)
    rule_references: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    evidence_references: Mapped[list[Any]] = mapped_column(JSONB,
                                                           nullable=False)
    conflict_references: Mapped[list[Any]] = mapped_column(JSONB,
                                                           nullable=False)

    __table_args__ = (
        UniqueConstraint("assessment_id", "drug_canonical_key",
                         "gene_canonical_key", name="assessment_axis"),
        CheckConstraint(
            "coverage_status IN ('FULL', 'PARTIAL', 'INSUFFICIENT', "
            "'UNSUPPORTED_DRUG', 'UNSUPPORTED_PHENOTYPE', 'SOURCE_CONFLICT')",
            name="coverage_enum"),
        CheckConstraint(
            "coverage_status = 'FULL' "
            "OR jsonb_array_length(coverage_reason_codes) >= 1",
            name="non_full_coverage_has_reasons"),
        CheckConstraint(
            "coverage_status <> 'FULL' "
            "OR jsonb_array_length(coverage_reason_codes) = 0",
            name="full_coverage_has_no_reason"),
        # A conflicted axis names the conflict it preserves; a conflict with
        # no reference cannot be looked up and is not preserved at all.
        CheckConstraint(
            "coverage_status <> 'SOURCE_CONFLICT' "
            "OR jsonb_array_length(conflict_references) >= 1",
            name="conflict_names_its_references"),
        CheckConstraint(
            "observed_phenotype IS NULL OR observed_phenotype IN "
            "('POOR', 'INTERMEDIATE', 'NORMAL', 'RAPID', 'ULTRARAPID', "
            "'INDETERMINATE')", name="phenotype_enum"),
        Index("ix_assessment_axes_assessment_id", "assessment_id"),
        Index("ix_assessment_axes_medication_id", "medication_id"),
    )


class AssessmentFindingORM(Base):
    """One calculated finding, with the rule and provenance that produced it.

    ``effect_code`` and ``explanation_code`` are nullable, and that is the
    honest shape: WP-11's governed rule outcome carries an attention level and
    a ``rationale_reference`` and no scientific codes at all. A NOT NULL column
    here would have forced every row to invent one.
    """

    __tablename__ = "assessment_findings"

    id: Mapped[uuid.UUID] = _uuid_pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False)
    medication_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessment_medications.id", ondelete="CASCADE"),
        nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    drug_canonical_key: Mapped[str] = mapped_column(String(256),
                                                    nullable=False)
    gene_canonical_key: Mapped[str] = mapped_column(String(128),
                                                    nullable=False)
    phenotype: Mapped[str] = mapped_column(String(32), nullable=False)
    attention_level: Mapped[str] = mapped_column(String(32), nullable=False)

    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("computable_rules.id", ondelete="RESTRICT"), nullable=False)
    rule_family_id: Mapped[str] = mapped_column(String(128), nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    rationale_reference: Mapped[str] = mapped_column(String(512),
                                                     nullable=False)
    curation_revision_id: Mapped[str] = mapped_column(String(128),
                                                      nullable=False)
    curation_revision_hash: Mapped[str] = mapped_column(String(80),
                                                        nullable=False)
    effect_code: Mapped[Optional[str]] = mapped_column(String(128),
                                                       nullable=True)
    explanation_code: Mapped[Optional[str]] = mapped_column(String(128),
                                                            nullable=True)

    __table_args__ = (
        UniqueConstraint("assessment_id", "drug_canonical_key",
                         "gene_canonical_key", "phenotype",
                         name="assessment_finding_identity"),
        # A finding is a calculated result. NOT_ASSESSED means the opposite,
        # and a row asserting both would be unreadable in either direction.
        CheckConstraint(
            "attention_level IN ('NO_ACTIVE_ATTENTION', 'LOW', 'MEDIUM', "
            "'HIGH')", name="attention_is_calculated"),
        CheckConstraint(
            "phenotype IN ('POOR', 'INTERMEDIATE', 'NORMAL', 'RAPID', "
            "'ULTRARAPID')", name="phenotype_enum"),
        CheckConstraint("rule_content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                        name="rule_hash_format"),
        CheckConstraint("curation_revision_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                        name="curation_revision_hash_format"),
        CheckConstraint("rule_version >= 1", name="rule_version_positive"),
        CheckConstraint("btrim(rationale_reference) <> ''",
                        name="rationale_reference_present"),
        # A supplied scientific code may not be blank: absent and
        # present-but-blank must not be confusable.
        CheckConstraint("effect_code IS NULL OR btrim(effect_code) <> ''",
                        name="effect_code_not_blank"),
        CheckConstraint(
            "explanation_code IS NULL OR btrim(explanation_code) <> ''",
            name="explanation_code_not_blank"),
        Index("ix_assessment_findings_assessment_id", "assessment_id"),
        Index("ix_assessment_findings_rule_id", "rule_id"),
    )


class AssessmentFindingEvidenceORM(Base):
    """The evidence behind one finding (``SAFETY-INV-006``).

    A separate table rather than a JSON array so the foreign key is real:
    deleting an evidence record cited by a stored finding is refused by the
    database, not by a convention.
    """

    __tablename__ = "assessment_finding_evidence"

    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessment_findings.id", ondelete="CASCADE"),
        primary_key=True)
    evidence_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evidence_records.id", ondelete="RESTRICT"),
        primary_key=True)
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False)

    __table_args__ = (
        Index("ix_assessment_finding_evidence_assessment_id", "assessment_id"),
        Index("ix_assessment_finding_evidence_evidence_record_id",
              "evidence_record_id"),
    )
