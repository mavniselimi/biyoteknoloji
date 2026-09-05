# -*- coding: utf-8 -*-
"""WP-02 foundation schema.

Revision ID: 0001_wp02_foundation
Revises:
Create Date: 2026-08-29

Hand-written and reviewed, not blind autogenerate output.

Scope - eleven foundation tables only:

    source_registry, dataset_versions, genes, gene_aliases, drugs, drug_aliases,
    evidence_records, curated_interpretations, interpretation_evidence,
    computable_rules, rule_evidence

Deliberately NOT created here, because each belongs to a later work package and
creating it now would imply an identity or a capability that does not yet
exist: software_versions, ruleset versions and membership, release_bundles,
active_release, assessments, assessment_findings, users and sessions,
validation cases, expert reviews, ingestion runs and raw artifacts.

``downgrade()`` removes exactly these objects, children before parents, so an
upgrade -> downgrade -> upgrade cycle leaves no debris. No PostgreSQL function
or trigger is created, so none needs dropping.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_wp02_foundation"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Canonical digest spelling produced by pgx.domain.hashing.sha256_digest.
SHA256_DIGEST_REGEX = r"^sha256:[0-9a-f]{64}$"
DATASET_PUBLIC_ID_REGEX = r"^PGX-DATA-[0-9]{8}-[0-9]{3}$"

SOURCE_ROLES = "'PRIMARY_GUIDELINE', 'SUPPORTING_ANNOTATION', 'REFERENCE_ONLY', 'INTERNAL_SYSTEM'"
DATASET_STATUSES = "'BUILDING', 'QUALITY_CHECKED', 'PUBLISHED', 'RETIRED'"
CURATION_STATUSES = "'RAW', 'UNDER_REVIEW', 'CURATED', 'REJECTED'"
RULE_STATUSES = "'DRAFT', 'CURATED', 'VALIDATED', 'DEPRECATED'"
ATTENTION_LEVELS = "'NOT_ASSESSED', 'NO_ACTIVE_ATTENTION', 'LOW', 'MEDIUM', 'HIGH'"
PHENOTYPES = "'POOR', 'INTERMEDIATE', 'NORMAL', 'RAPID', 'ULTRARAPID', 'INDETERMINATE'"


def _uuid() -> postgresql.UUID:
    """Application-supplied UUID; no server extension is required."""
    return postgresql.UUID(as_uuid=True)


def _timestamptz() -> postgresql.TIMESTAMP:
    """Timezone-aware timestamp; a naive instant is not storable."""
    return postgresql.TIMESTAMP(timezone=True)


def upgrade() -> None:
    """Create the WP-02 foundation schema."""

    # -- source_registry ------------------------------------------------
    op.create_table(
        "source_registry",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("source_key", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("version_policy", sa.String(length=256), nullable=False),
        sa.Column("license_policy", sa.String(length=256), nullable=False),
        sa.Column("citation_policy", sa.String(length=256), nullable=False),
        sa.Column("release_eligible", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("legacy_id", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_source_registry"),
        sa.UniqueConstraint("source_key", name="uq_source_registry_source_key"),
        sa.CheckConstraint("role IN (%s)" % SOURCE_ROLES, name="ck_source_registry_role_enum"),
        sa.CheckConstraint("length(trim(source_key)) > 0",
                           name="ck_source_registry_source_key_not_blank"),
        # A technical bookkeeping source may never back a release.
        sa.CheckConstraint("role <> 'INTERNAL_SYSTEM' OR release_eligible = false",
                           name="ck_source_registry_internal_source_not_release_eligible"),
    )

    # -- dataset_versions -----------------------------------------------
    op.create_table(
        "dataset_versions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("manifest_hash", sa.String(length=80), nullable=False),
        sa.Column("dq_report_path", sa.String(length=512), nullable=True),
        sa.Column("created_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("approved_by", sa.String(length=256), nullable=True),
        sa.Column("approved_at", _timestamptz(), nullable=True),
        sa.Column("legacy_id", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_dataset_versions"),
        sa.UniqueConstraint("public_id", name="uq_dataset_versions_public_id"),
        sa.CheckConstraint("status IN (%s)" % DATASET_STATUSES,
                           name="ck_dataset_versions_status_enum"),
        sa.CheckConstraint("public_id ~ '%s'" % DATASET_PUBLIC_ID_REGEX,
                           name="ck_dataset_versions_public_id_format"),
        sa.CheckConstraint("manifest_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_dataset_versions_manifest_hash_format"),
        sa.CheckConstraint(
            "status <> 'PUBLISHED' OR (approved_by IS NOT NULL"
            " AND length(trim(approved_by)) > 0 AND approved_at IS NOT NULL)",
            name="ck_dataset_versions_published_requires_approval"),
    )

    # -- genes and aliases ----------------------------------------------
    op.create_table(
        "genes",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("normalized_symbol", sa.String(length=64), nullable=False),
        sa.Column("preferred_name", sa.String(length=256), nullable=False),
        sa.Column("external_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("legacy_id", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_genes"),
        sa.UniqueConstraint("normalized_symbol", name="uq_genes_normalized_symbol"),
        sa.CheckConstraint("normalized_symbol = upper(trim(normalized_symbol))",
                           name="ck_genes_symbol_normalized"),
        sa.CheckConstraint("length(trim(normalized_symbol)) > 0",
                           name="ck_genes_symbol_not_blank"),
    )
    op.create_table(
        "gene_aliases",
        sa.Column("gene_id", _uuid(), nullable=False),
        sa.Column("normalized_alias", sa.String(length=128), nullable=False),
        sa.Column("display_alias", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(["gene_id"], ["genes.id"], name="fk_gene_aliases_gene_id_genes",
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("gene_id", "normalized_alias", name="pk_gene_aliases"),
        # Unique within a gene only: the same alias may legitimately belong to
        # two genes, and that ambiguity must survive for WP-07 resolution
        # rather than being collapsed to the first inserted row.
        sa.UniqueConstraint("gene_id", "normalized_alias", name="uq_gene_aliases_gene_alias"),
        sa.CheckConstraint("normalized_alias = upper(trim(normalized_alias))",
                           name="ck_gene_aliases_alias_normalized"),
    )
    op.create_index("ix_gene_aliases_normalized_alias", "gene_aliases",
                    ["normalized_alias"], unique=False)

    # -- drugs and aliases ----------------------------------------------
    op.create_table(
        "drugs",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("normalized_name", sa.String(length=128), nullable=False),
        sa.Column("preferred_name", sa.String(length=256), nullable=False),
        sa.Column("external_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("legacy_id", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_drugs"),
        sa.UniqueConstraint("normalized_name", name="uq_drugs_normalized_name"),
        sa.CheckConstraint("normalized_name = lower(trim(normalized_name))",
                           name="ck_drugs_name_normalized"),
        sa.CheckConstraint("length(trim(normalized_name)) > 0",
                           name="ck_drugs_name_not_blank"),
    )
    op.create_table(
        "drug_aliases",
        sa.Column("drug_id", _uuid(), nullable=False),
        sa.Column("normalized_alias", sa.String(length=128), nullable=False),
        sa.Column("display_alias", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(["drug_id"], ["drugs.id"], name="fk_drug_aliases_drug_id_drugs",
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("drug_id", "normalized_alias", name="pk_drug_aliases"),
        sa.UniqueConstraint("drug_id", "normalized_alias", name="uq_drug_aliases_drug_alias"),
        sa.CheckConstraint("normalized_alias = lower(trim(normalized_alias))",
                           name="ck_drug_aliases_alias_normalized"),
    )
    op.create_index("ix_drug_aliases_normalized_alias", "drug_aliases",
                    ["normalized_alias"], unique=False)

    # -- evidence_records -----------------------------------------------
    # Source truth only: no attention, risk, dose or treatment column exists.
    op.create_table(
        "evidence_records",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("source_registry_id", _uuid(), nullable=False),
        sa.Column("dataset_version_id", _uuid(), nullable=False),
        sa.Column("source_record_id", sa.String(length=256), nullable=False),
        sa.Column("source_record_version", sa.String(length=64), nullable=False),
        sa.Column("gene_id", _uuid(), nullable=True),
        sa.Column("drug_id", _uuid(), nullable=True),
        sa.Column("raw_hash", sa.String(length=80), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("evidence_metadata", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("publication_metadata", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("legacy_id", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_registry_id"], ["source_registry.id"],
            name="fk_evidence_records_source_registry_id_source_registry",
            ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"],
            name="fk_evidence_records_dataset_version_id_dataset_versions",
            ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["gene_id"], ["genes.id"],
                                name="fk_evidence_records_gene_id_genes", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["drug_id"], ["drugs.id"],
                                name="fk_evidence_records_drug_id_drugs", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_evidence_records"),
        sa.UniqueConstraint("dataset_version_id", "source_registry_id", "source_record_id",
                            "source_record_version", name="uq_evidence_records_provenance"),
        sa.CheckConstraint("raw_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_evidence_records_raw_hash_format"),
        sa.CheckConstraint("length(trim(source_record_id)) > 0",
                           name="ck_evidence_records_source_record_id_not_blank"),
    )
    op.create_index("ix_evidence_records_dataset_version_id", "evidence_records",
                    ["dataset_version_id"], unique=False)
    op.create_index("ix_evidence_records_gene_id_drug_id", "evidence_records",
                    ["gene_id", "drug_id"], unique=False)

    # -- curated_interpretations ----------------------------------------
    op.create_table(
        "curated_interpretations",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("normalized_phenotype", sa.String(length=32), nullable=True),
        sa.Column("normalized_effect", sa.String(length=128), nullable=False),
        sa.Column("significance", sa.String(length=128), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=256), nullable=False),
        sa.Column("reviewed_by", sa.String(length=256), nullable=True),
        sa.Column("created_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("reviewed_at", _timestamptz(), nullable=True),
        sa.Column("legacy_id", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_curated_interpretations"),
        sa.CheckConstraint("status IN (%s)" % CURATION_STATUSES,
                           name="ck_curated_interpretations_status_enum"),
        sa.CheckConstraint(
            "normalized_phenotype IS NULL OR normalized_phenotype IN (%s)" % PHENOTYPES,
            name="ck_curated_interpretations_phenotype_enum"),
        # Curation must record who decided and why.
        sa.CheckConstraint(
            "status <> 'CURATED' OR (rationale IS NOT NULL"
            " AND length(trim(rationale)) > 0 AND reviewed_by IS NOT NULL"
            " AND length(trim(reviewed_by)) > 0 AND reviewed_at IS NOT NULL)",
            name="ck_curated_interpretations_curated_requires_review_metadata"),
    )

    op.create_table(
        "interpretation_evidence",
        sa.Column("interpretation_id", _uuid(), nullable=False),
        sa.Column("evidence_record_id", _uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["interpretation_id"], ["curated_interpretations.id"],
            name="fk_interpretation_evidence_interpretation_id",
            ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["evidence_record_id"], ["evidence_records.id"],
            name="fk_interpretation_evidence_evidence_record_id_evidence_records",
            ondelete="RESTRICT"),
        # Composite PK also prevents a duplicate association.
        sa.PrimaryKeyConstraint("interpretation_id", "evidence_record_id",
                                name="pk_interpretation_evidence"),
    )
    op.create_index("ix_interpretation_evidence_evidence_record_id",
                    "interpretation_evidence", ["evidence_record_id"], unique=False)

    # -- computable_rules -----------------------------------------------
    op.create_table(
        "computable_rules",
        sa.Column("id", _uuid(), nullable=False),
        # NOT NULL: a rule with no interpretation has no reviewed basis.
        sa.Column("interpretation_id", _uuid(), nullable=False),
        sa.Column("condition_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("attention_level", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_by", sa.String(length=256), nullable=False),
        sa.Column("approved_by", sa.String(length=256), nullable=True),
        sa.Column("created_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("approved_at", _timestamptz(), nullable=True),
        sa.Column("legacy_id", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(
            ["interpretation_id"], ["curated_interpretations.id"],
            name="fk_computable_rules_interpretation_id_curated_interpretations",
            ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_computable_rules"),
        sa.UniqueConstraint("interpretation_id", "rule_version",
                            name="uq_computable_rules_interpretation_version"),
        sa.CheckConstraint("status IN (%s)" % RULE_STATUSES,
                           name="ck_computable_rules_status_enum"),
        sa.CheckConstraint("attention_level IN (%s)" % ATTENTION_LEVELS,
                           name="ck_computable_rules_attention_level_enum"),
        sa.CheckConstraint("rule_version >= 1",
                           name="ck_computable_rules_rule_version_positive"),
        # Approval may never be implied.
        sa.CheckConstraint(
            "status <> 'VALIDATED' OR (approved_by IS NOT NULL"
            " AND length(trim(approved_by)) > 0 AND approved_at IS NOT NULL)",
            name="ck_computable_rules_validated_requires_approval"),
    )
    op.create_index("ix_computable_rules_status", "computable_rules", ["status"],
                    unique=False)

    op.create_table(
        "rule_evidence",
        sa.Column("rule_id", _uuid(), nullable=False),
        sa.Column("evidence_record_id", _uuid(), nullable=False),
        sa.ForeignKeyConstraint(["rule_id"], ["computable_rules.id"],
                                name="fk_rule_evidence_rule_id_computable_rules",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_record_id"], ["evidence_records.id"],
                                name="fk_rule_evidence_evidence_record_id_evidence_records",
                                ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("rule_id", "evidence_record_id", name="pk_rule_evidence"),
    )
    op.create_index("ix_rule_evidence_evidence_record_id", "rule_evidence",
                    ["evidence_record_id"], unique=False)


def downgrade() -> None:
    """Drop exactly the WP-02 objects, children before parents."""
    op.drop_index("ix_rule_evidence_evidence_record_id", table_name="rule_evidence")
    op.drop_table("rule_evidence")

    op.drop_index("ix_computable_rules_status", table_name="computable_rules")
    op.drop_table("computable_rules")

    op.drop_index("ix_interpretation_evidence_evidence_record_id",
                  table_name="interpretation_evidence")
    op.drop_table("interpretation_evidence")
    op.drop_table("curated_interpretations")

    op.drop_index("ix_evidence_records_gene_id_drug_id", table_name="evidence_records")
    op.drop_index("ix_evidence_records_dataset_version_id", table_name="evidence_records")
    op.drop_table("evidence_records")

    op.drop_index("ix_drug_aliases_normalized_alias", table_name="drug_aliases")
    op.drop_table("drug_aliases")
    op.drop_table("drugs")

    op.drop_index("ix_gene_aliases_normalized_alias", table_name="gene_aliases")
    op.drop_table("gene_aliases")
    op.drop_table("genes")

    op.drop_table("dataset_versions")
    op.drop_table("source_registry")
