# -*- coding: utf-8 -*-
"""WP-08 evidence store: provenance, attribution, links and import issues.

Revision ID: 0006_wp08_evidence_store
Revises: 0005_wp07_canonicalization
Create Date: 2026-08-30

Hand-written and reviewed, not blind autogenerate output. ``0001`` through
``0005`` are not rewritten: this revision adds tables and columns, plus the
column and constraint changes on ``evidence_records`` described below.

Scope - eight tables:

    evidence_builds, evidence_genes, evidence_drugs, evidence_text_fragments,
    publication_references, evidence_publications, evidence_provenance,
    evidence_import_issues

thirteen columns added to ``evidence_records``, one trigger that keeps a
finalized evidence record and its trace immutable, and the constraint work
described next.

**Why ``source_record_version`` must stop being NOT NULL.**
``0001`` declared it ``NOT NULL``, which leaves an importer two options for a
legacy record whose version metadata was never retained: invent a string, or
refuse the record. Inventing one is worse than refusing: a fabricated ``v1``
is indistinguishable from a real version a year later, and every comparison
after that silently rests on it.

So ``0006`` makes the column nullable and adds
``source_record_version_status``, a structured state - ``KNOWN``,
``SOURCE_UNVERSIONED``, ``UNKNOWN_LEGACY``, ``MISSING``, ``INVALID``.
``ck_evidence_records_version_status_consistent`` then requires that ``KNOWN``
carries a value and that **no other status does**, so "unknown" can never be
stored as a version string that later reads like a real one.

Dropping ``NOT NULL`` is a widening; every row that satisfied the old contract
still satisfies the new one. The check constraint beside it is what makes the
result stricter than before rather than looser.

**Why the provenance unique constraint is replaced.**
``0001`` created ``uq_evidence_records_provenance`` over
``(dataset_version_id, source_registry_id, source_record_id,
source_record_version)``. With a nullable version column that constraint stops
working: PostgreSQL treats ``NULL`` as distinct from ``NULL``, so two rows for
one unversioned record would both be admitted. It is replaced by
``uq_evidence_records_natural_key`` over the evidence natural key, whose
version part is the status name when there is no value. That is the same
identity WP-08's allocation artifact uses, so the database and the build agree
on what makes two records the same record.

**Provider and origin are separate columns.**
``source_registry_id`` keeps its ``0001`` meaning and is the *provider* - where
the bytes came from. ``origin_source_id`` is nullable and names the body the
record itself says asserted it, with ``origin_source_status`` recording why it
is null when it is. ``ck_evidence_records_origin_consistent`` requires that a
key is present exactly when the status is ``STATED_BY_SOURCE``, so an origin
can never be half-recorded.

**Four hashes, four columns.**
``raw_hash`` keeps its ``0001`` meaning. ``source_payload_hash`` is the digest
of the extracted source record, ``evidence_content_hash`` is the digest of this
project's rendering of it, and the raw artifact's own byte digest lives on each
``evidence_provenance`` row. Overloading one column with all four would make
every verification ambiguous about what it had checked.

**Multi-entity links replace the scalar columns.**
``gene_id`` and ``drug_id`` from ``0001`` are left in place and unused by
WP-08 rather than dropped, because dropping a column is not reversible on a
database holding data. ``evidence_genes`` and ``evidence_drugs`` carry the real
links, each with the role and source field the association came from, so a
guideline naming three genes is one record with three links instead of three
records.

**Finalized evidence is immutable.**
``trg_evidence_records_finalized_immutable`` refuses any ``UPDATE`` that
changes a finalized record's identity, hashes or attribution, and refuses every
``DELETE``. ``finalized_at`` is the switch: a row may be assembled and then
finalized once, after which only nothing may change. The provenance, link,
fragment and publication tables cascade from the record and are protected by
the same rule through their foreign keys.

``downgrade()`` removes exactly these objects, children before parents, drops
the trigger *and* its function, restores ``0001``'s provenance unique
constraint and its ``NOT NULL``, then drops the added columns. Nothing from
``0001`` through ``0005`` is otherwise touched.

**Two documented downgrade limitations.** On a database holding evidence rows
whose ``source_record_version`` is null - which is every legacy-migration
record - restoring ``0001``'s ``NOT NULL`` fails. That refusal is correct: the
only way to satisfy the old contract is to write a version nobody knows, and
this migration will not do that on an operator's behalf. Equally, a database
holding finalized evidence cannot drop the immutability trigger without an
operator deciding explicitly what protection replaces it.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_wp08_evidence_store"
down_revision: Union[str, None] = "0005_wp07_canonicalization"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SHA256_DIGEST_REGEX = r"^sha256:[0-9a-f]{64}$"
DATASET_PUBLIC_ID_REGEX = r"^PGX-DATA-[0-9]{8}-[0-9]{3}$"

EVIDENCE_RECORD_TYPES = ("'GUIDELINE_ANNOTATION', 'VARIANT_ANNOTATION', "
                         "'DRUG_LABEL_ANNOTATION', 'CLINICAL_ANNOTATION', "
                         "'PUBLICATION_REFERENCE', 'OTHER_SOURCE_RECORD', "
                         "'UNKNOWN'")
RECORD_TYPE_MAPPING_STATUSES = "'CONFIRMED', 'PENDING_REVIEW', 'UNMAPPED'"
VERSION_STATUSES = ("'KNOWN', 'SOURCE_UNVERSIONED', 'UNKNOWN_LEGACY', "
                    "'MISSING', 'INVALID'")
ORIGIN_STATUSES = ("'STATED_BY_SOURCE', 'NOT_STATED_BY_SOURCE', 'AMBIGUOUS', "
                   "'UNREGISTERED'")
IMPORT_MODES = "'PRODUCTION', 'LEGACY_MIGRATION'"
ISSUE_SEVERITIES = "'BLOCKING', 'ADVISORY', 'INFORMATIONAL'"
ENTITY_LINK_ROLES = "'RELATED_ENTITY', 'QUERY_CONTEXT', 'MENTIONED_IN_TEXT'"

#: The ``0001`` provenance rule, restored verbatim by ``downgrade()``. Written
#: out as a list rather than assembled from a tuple, so the columns it names
#: are on the line where a reader looking for them will be.
PROVENANCE_UNIQUE_0001 = ["dataset_version_id", "source_registry_id",
                          "source_record_id", "source_record_version"]

_FINALIZED_IMMUTABLE_FUNCTION = """
CREATE OR REPLACE FUNCTION pgx_evidence_records_finalized_immutable()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'evidence_records rows are not deletable: an evidence record is '
            'what a source stated at a moment that has passed, and every '
            'curation, rule and finding that cites it would be orphaned.'
            USING ERRCODE = 'restrict_violation';
    END IF;
    -- Whole-row comparison, not a list of protected columns. An enumerated
    -- list is an allowlist by omission: every column it does not name stays
    -- editable, and every column added later is editable by default, which is
    -- the wrong default for an append-only table. An earlier version of this
    -- trigger named thirteen columns and let an UPDATE rewrite source_text on
    -- a finalized record - the source's own wording, under a content hash
    -- that would no longer describe it.
    IF OLD.finalized_at IS NOT NULL AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION
            'a finalized evidence record is immutable: it describes bytes '
            'that already exist under a recorded hash. A corrected source '
            'statement is a new record, not an edit of this one.'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_FINALIZED_IMMUTABLE_TRIGGER = """
CREATE TRIGGER trg_evidence_records_finalized_immutable
BEFORE UPDATE OR DELETE ON evidence_records
FOR EACH ROW EXECUTE FUNCTION pgx_evidence_records_finalized_immutable();
"""


def _uuid() -> postgresql.UUID:
    """Application-supplied UUID; no server extension is required."""
    return postgresql.UUID(as_uuid=True)


def _timestamptz() -> postgresql.TIMESTAMP:
    """Timezone-aware timestamp; a naive instant is not storable."""
    return postgresql.TIMESTAMP(timezone=True)


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """Create the WP-08 evidence schema."""

    # -- evidence_builds ---------------------------------------------------
    op.create_table(
        "evidence_builds",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("dataset_public_id", sa.String(length=64), nullable=False),
        sa.Column("evidence_build_key", sa.String(length=128), nullable=False),
        sa.Column("content_hash", sa.String(length=80), nullable=False),
        sa.Column("snapshot_manifest_hash", sa.String(length=80), nullable=False),
        sa.Column("canonical_build_key", sa.String(length=128), nullable=False),
        sa.Column("canonical_build_content_hash", sa.String(length=80),
                  nullable=False),
        sa.Column("allocation_content_hash", sa.String(length=80),
                  nullable=False),
        sa.Column("build_relative_path", sa.String(length=512), nullable=False),
        sa.Column("mode", sa.String(length=24), nullable=False),
        sa.Column("production_eligible", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("lifecycle_labels", _jsonb(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("rule_versions", _jsonb(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("summary", _jsonb(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("source_policy_status", sa.String(length=40), nullable=True),
        sa.Column("record_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("blocking_issue_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("built_at", _timestamptz(), nullable=False),
        sa.Column("recorded_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("dataset_version_id", _uuid(), nullable=True),
        sa.Column("canonical_build_id", _uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"],
            name="fk_evidence_builds_dataset_version_id_dataset_versions",
            ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["canonical_build_id"], ["canonical_builds.id"],
            name="fk_evidence_builds_canonical_build_id_canonical_builds",
            ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_evidence_builds"),
        sa.UniqueConstraint("evidence_build_key",
                            name="uq_evidence_builds_build_key"),
        sa.UniqueConstraint("build_relative_path",
                            name="uq_evidence_builds_build_relative_path"),
        sa.CheckConstraint("dataset_public_id ~ '%s'" % DATASET_PUBLIC_ID_REGEX,
                           name="ck_evidence_builds_dataset_id_format"),
        sa.CheckConstraint("mode IN (%s)" % IMPORT_MODES,
                           name="ck_evidence_builds_mode_enum"),
        sa.CheckConstraint("content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_evidence_builds_content_hash_format"),
        sa.CheckConstraint(
            "snapshot_manifest_hash ~ '%s'" % SHA256_DIGEST_REGEX,
            name="ck_evidence_builds_snapshot_hash_format"),
        sa.CheckConstraint(
            "canonical_build_content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
            name="ck_evidence_builds_canonical_hash_format"),
        sa.CheckConstraint(
            "allocation_content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
            name="ck_evidence_builds_allocation_hash_format"),
        sa.CheckConstraint(
            "build_relative_path !~ '(^/)|(^[A-Za-z]:)|(\\.\\.)|(\\\\)'",
            name="ck_evidence_builds_path_relative"),
        # A migration build is never production eligible. Stated in the
        # database so the rule survives a service that forgets it.
        sa.CheckConstraint(
            "mode <> 'LEGACY_MIGRATION' OR production_eligible = false",
            name="ck_evidence_builds_migration_not_eligible"),
        # And neither is a build that recorded a blocking finding.
        sa.CheckConstraint(
            "production_eligible = false OR blocking_issue_count = 0",
            name="ck_evidence_builds_eligible_has_no_blockers"),
    )
    op.create_index("ix_evidence_builds_dataset_public_id", "evidence_builds",
                    ["dataset_public_id"], unique=False)
    op.create_index("ix_evidence_builds_content_hash", "evidence_builds",
                    ["content_hash"], unique=False)

    # -- evidence_records: provider/origin, version status, hashes ---------
    op.add_column("evidence_records", sa.Column(
        "evidence_build_id", _uuid(), nullable=True))
    op.add_column("evidence_records", sa.Column(
        "natural_key", sa.String(length=512), nullable=True))
    op.add_column("evidence_records", sa.Column(
        "record_type", sa.String(length=32), nullable=True))
    op.add_column("evidence_records", sa.Column(
        "source_object_class", sa.String(length=128), nullable=True))
    op.add_column("evidence_records", sa.Column(
        "record_type_mapping_status", sa.String(length=24), nullable=True))
    op.add_column("evidence_records", sa.Column(
        "source_record_version_status", sa.String(length=32), nullable=False,
        server_default=sa.text("'UNKNOWN_LEGACY'")))
    op.add_column("evidence_records", sa.Column(
        "source_record_id_raw_type", sa.String(length=16), nullable=True))
    op.add_column("evidence_records", sa.Column(
        "origin_source_id", _uuid(), nullable=True))
    op.add_column("evidence_records", sa.Column(
        "origin_source_status", sa.String(length=32), nullable=False,
        server_default=sa.text("'NOT_STATED_BY_SOURCE'")))
    op.add_column("evidence_records", sa.Column(
        "raw_origin_value", sa.Text(), nullable=True))
    op.add_column("evidence_records", sa.Column(
        "source_payload_hash", sa.String(length=80), nullable=True))
    op.add_column("evidence_records", sa.Column(
        "evidence_content_hash", sa.String(length=80), nullable=True))
    op.add_column("evidence_records", sa.Column(
        "production_eligible", sa.Boolean(), nullable=False,
        server_default=sa.text("false")))
    op.add_column("evidence_records", sa.Column(
        "finalized_at", _timestamptz(), nullable=True))

    # An unknown legacy version must be storable as unknown. See the module
    # docstring: the alternative is a fabricated version string.
    op.alter_column("evidence_records", "source_record_version",
                    existing_type=sa.String(length=64), nullable=True)

    op.create_foreign_key(
        "fk_evidence_records_evidence_build_id_evidence_builds",
        "evidence_records", "evidence_builds",
        ["evidence_build_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key(
        "fk_evidence_records_origin_source_id_source_registry",
        "evidence_records", "source_registry",
        ["origin_source_id"], ["id"], ondelete="RESTRICT")

    # The 0001 constraint cannot express a nullable version: PostgreSQL treats
    # NULL as distinct from NULL, so two rows for one unversioned record would
    # both be admitted. Replaced by the natural key, whose version part is the
    # status name when there is no value.
    op.drop_constraint("uq_evidence_records_provenance", "evidence_records",
                       type_="unique")
    op.create_unique_constraint(
        "uq_evidence_records_natural_key", "evidence_records",
        ["evidence_build_id", "natural_key"])

    op.create_check_constraint(
        "ck_evidence_records_type_enum", "evidence_records",
        sa.text("record_type IS NULL OR record_type IN (%s)"
                % EVIDENCE_RECORD_TYPES))
    op.create_check_constraint(
        "ck_evidence_records_mapping_status_enum", "evidence_records",
        sa.text("record_type_mapping_status IS NULL"
                " OR record_type_mapping_status IN (%s)"
                % RECORD_TYPE_MAPPING_STATUSES))
    op.create_check_constraint(
        "ck_evidence_records_version_status_enum", "evidence_records",
        sa.text("source_record_version_status IN (%s)" % VERSION_STATUSES))
    # KNOWN carries a value; nothing else may, so 'unknown' can never be
    # stored as a version string that later reads like a real one.
    op.create_check_constraint(
        "ck_evidence_records_version_status_consistent", "evidence_records",
        sa.text("(source_record_version_status = 'KNOWN'"
                "  AND source_record_version IS NOT NULL"
                "  AND length(trim(source_record_version)) > 0)"
                " OR (source_record_version_status <> 'KNOWN'"
                "     AND source_record_version IS NULL)"))
    op.create_check_constraint(
        "ck_evidence_records_origin_status_enum", "evidence_records",
        sa.text("origin_source_status IN (%s)" % ORIGIN_STATUSES))
    # An origin key is present exactly when the record stated one.
    op.create_check_constraint(
        "ck_evidence_records_origin_consistent", "evidence_records",
        sa.text("(origin_source_status = 'STATED_BY_SOURCE'"
                "  AND origin_source_id IS NOT NULL)"
                " OR (origin_source_status <> 'STATED_BY_SOURCE'"
                "     AND origin_source_id IS NULL)"))
    op.create_check_constraint(
        "ck_evidence_records_source_payload_hash_format", "evidence_records",
        sa.text("source_payload_hash IS NULL"
                " OR source_payload_hash ~ '%s'" % SHA256_DIGEST_REGEX))
    op.create_check_constraint(
        "ck_evidence_records_content_hash_format", "evidence_records",
        sa.text("evidence_content_hash IS NULL"
                " OR evidence_content_hash ~ '%s'" % SHA256_DIGEST_REGEX))
    # A production-eligible record has a settled kind, a citable version and a
    # stated origin. Each alone is disqualifying. record_type_mapping_status
    # is nullable for rows migrated in from 0002, so it is tested for NULL
    # explicitly: NULL = 'CONFIRMED' is NULL, which would make the whole
    # conjunction NULL and let an unmapped record be marked eligible.
    op.create_check_constraint(
        "ck_evidence_records_eligible_is_complete", "evidence_records",
        sa.text("production_eligible = false"
                " OR (record_type_mapping_status IS NOT NULL"
                "     AND record_type_mapping_status = 'CONFIRMED'"
                "     AND source_record_version_status IN"
                "         ('KNOWN', 'SOURCE_UNVERSIONED')"
                "     AND origin_source_status = 'STATED_BY_SOURCE'"
                "     AND finalized_at IS NOT NULL)"))
    op.create_index("ix_evidence_records_natural_key", "evidence_records",
                    ["natural_key"], unique=False)
    op.create_index("ix_evidence_records_evidence_build_id", "evidence_records",
                    ["evidence_build_id"], unique=False)
    op.create_index("ix_evidence_records_origin_source_id", "evidence_records",
                    ["origin_source_id"], unique=False)

    # -- evidence_genes ----------------------------------------------------
    # Many-to-many, so a guideline naming three genes is one record with three
    # links rather than three records that look like three statements.
    op.create_table(
        "evidence_genes",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("evidence_record_id", _uuid(), nullable=False),
        sa.Column("gene_id", _uuid(), nullable=False),
        sa.Column("canonical_key", sa.String(length=256), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("source_field", sa.String(length=128), nullable=True),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["evidence_record_id"], ["evidence_records.id"],
            name="fk_evidence_genes_evidence_record_id_evidence_records",
            ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["gene_id"], ["genes.id"],
                                name="fk_evidence_genes_gene_id_genes",
                                ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_evidence_genes"),
        sa.UniqueConstraint("evidence_record_id", "gene_id", "role",
                            name="uq_evidence_genes_record_gene_role"),
        sa.CheckConstraint("role IN (%s)" % ENTITY_LINK_ROLES,
                           name="ck_evidence_genes_role_enum"),
        sa.CheckConstraint("canonical_key LIKE 'GENE:%'",
                           name="ck_evidence_genes_canonical_key_prefix"),
    )
    op.create_index("ix_evidence_genes_gene_id", "evidence_genes",
                    ["gene_id"], unique=False)
    op.create_index("ix_evidence_genes_evidence_record_id", "evidence_genes",
                    ["evidence_record_id"], unique=False)

    # -- evidence_drugs ----------------------------------------------------
    op.create_table(
        "evidence_drugs",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("evidence_record_id", _uuid(), nullable=False),
        sa.Column("drug_id", _uuid(), nullable=False),
        sa.Column("canonical_key", sa.String(length=256), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("source_field", sa.String(length=128), nullable=True),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["evidence_record_id"], ["evidence_records.id"],
            name="fk_evidence_drugs_evidence_record_id_evidence_records",
            ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["drug_id"], ["drugs.id"],
                                name="fk_evidence_drugs_drug_id_drugs",
                                ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_evidence_drugs"),
        sa.UniqueConstraint("evidence_record_id", "drug_id", "role",
                            name="uq_evidence_drugs_record_drug_role"),
        sa.CheckConstraint("role IN (%s)" % ENTITY_LINK_ROLES,
                           name="ck_evidence_drugs_role_enum"),
        sa.CheckConstraint("canonical_key LIKE 'DRUG:%'",
                           name="ck_evidence_drugs_canonical_key_prefix"),
    )
    op.create_index("ix_evidence_drugs_drug_id", "evidence_drugs",
                    ["drug_id"], unique=False)
    op.create_index("ix_evidence_drugs_evidence_record_id", "evidence_drugs",
                    ["evidence_record_id"], unique=False)

    # -- evidence_text_fragments -------------------------------------------
    # Fields are kept apart. A summary and a recommendation concatenated into
    # one blob cannot afterwards be attributed to the field each came from.
    op.create_table(
        "evidence_text_fragments",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("evidence_record_id", _uuid(), nullable=False),
        sa.Column("field_name", sa.String(length=128), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_format", sa.String(length=64), nullable=False,
                  server_default=sa.text("'text/plain'")),
        sa.Column("language", sa.String(length=32), nullable=False,
                  server_default=sa.text("'UNKNOWN'")),
        sa.Column("language_value", sa.String(length=64), nullable=True),
        sa.Column("text_hash", sa.String(length=80), nullable=False),
        sa.Column("exact_text_hash", sa.String(length=80), nullable=False),
        sa.ForeignKeyConstraint(
            ["evidence_record_id"], ["evidence_records.id"],
            name="fk_evidence_text_fragments_record_id_evidence_records",
            ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_evidence_text_fragments"),
        sa.UniqueConstraint("evidence_record_id", "field_name", "ordinal",
                            name="uq_evidence_text_fragments_record_field"),
        sa.CheckConstraint("length(text) > 0",
                           name="ck_evidence_text_fragments_text_not_empty"),
        sa.CheckConstraint("ordinal >= 0",
                           name="ck_evidence_text_fragments_ordinal_positive"),
        sa.CheckConstraint("text_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_evidence_text_fragments_text_hash_format"),
        sa.CheckConstraint("exact_text_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_evidence_text_fragments_exact_hash_format"),
        # A stated language names the value the source stated.
        sa.CheckConstraint(
            "language <> 'STATED_BY_SOURCE'"
            " OR (language_value IS NOT NULL"
            "     AND length(trim(language_value)) > 0)",
            name="ck_evidence_text_fragments_stated_language_has_value"),
    )
    op.create_index("ix_evidence_text_fragments_record_id",
                    "evidence_text_fragments", ["evidence_record_id"],
                    unique=False)
    op.create_index("ix_evidence_text_fragments_text_hash",
                    "evidence_text_fragments", ["text_hash"], unique=False)

    # -- publication_references --------------------------------------------
    op.create_table(
        "publication_references",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("pmid", sa.String(length=16), nullable=True),
        sa.Column("doi", sa.String(length=256), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("identity", sa.String(length=280), nullable=True),
        sa.Column("raw_value", _jsonb(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("validation_issues", _jsonb(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.PrimaryKeyConstraint("id", name="pk_publication_references"),
        # Identity is a PMID or a DOI, never a title. Two records printing one
        # title have not been shown to cite one article.
        sa.UniqueConstraint("identity", name="uq_publication_references_identity"),
        sa.CheckConstraint("pmid IS NULL OR pmid ~ '^[0-9]{1,9}$'",
                           name="ck_publication_references_pmid_digits"),
        sa.CheckConstraint("doi IS NULL OR doi ~ '^10\\.[0-9]{4,9}/'",
                           name="ck_publication_references_doi_shape"),
        sa.CheckConstraint(
            "publication_year IS NULL"
            " OR (publication_year >= 1800 AND publication_year <= 2200)",
            name="ck_publication_references_year_range"),
        # Each arm names its own column NOT NULL first. Without that guard
        # 'doi:' || NULL is NULL, the disjunction evaluates to NULL rather
        # than false, and a CHECK admits the row: a title-derived identity
        # such as 'title:...' was accepted in drill E21 before this guard.
        sa.CheckConstraint(
            "identity IS NULL"
            " OR (pmid IS NOT NULL AND identity = 'pmid:' || pmid)"
            " OR (doi IS NOT NULL AND identity = 'doi:' || doi)",
            name="ck_publication_references_identity_matches"),
    )
    op.create_index("ix_publication_references_pmid", "publication_references",
                    ["pmid"], unique=False)
    op.create_index("ix_publication_references_doi", "publication_references",
                    ["doi"], unique=False)

    # -- evidence_publications ---------------------------------------------
    op.create_table(
        "evidence_publications",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("evidence_record_id", _uuid(), nullable=False),
        sa.Column("publication_reference_id", _uuid(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_field", sa.String(length=128), nullable=True),
        sa.Column("raw_value", _jsonb(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("validation_issues", _jsonb(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.ForeignKeyConstraint(
            ["evidence_record_id"], ["evidence_records.id"],
            name="fk_evidence_publications_record_id_evidence_records",
            ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["publication_reference_id"], ["publication_references.id"],
            name="fk_evidence_publications_reference_id_publication_references",
            ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_evidence_publications"),
        sa.UniqueConstraint("evidence_record_id", "ordinal",
                            name="uq_evidence_publications_record_ordinal"),
        sa.CheckConstraint("ordinal >= 0",
                           name="ck_evidence_publications_ordinal_positive"),
    )
    op.create_index("ix_evidence_publications_record_id",
                    "evidence_publications", ["evidence_record_id"],
                    unique=False)
    op.create_index("ix_evidence_publications_reference_id",
                    "evidence_publications", ["publication_reference_id"],
                    unique=False)

    # -- evidence_provenance -----------------------------------------------
    # Every contributing locator gets its own row, including all of a WP-07
    # duplicate group's. This is the table that answers "where did this come
    # from", and the answer has to be complete.
    op.create_table(
        "evidence_provenance",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("evidence_record_id", _uuid(), nullable=False),
        sa.Column("raw_artifact_id", _uuid(), nullable=True),
        sa.Column("dataset_public_id", sa.String(length=64), nullable=False),
        sa.Column("snapshot_manifest_hash", sa.String(length=80),
                  nullable=False),
        sa.Column("artifact_path", sa.String(length=1024), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=80), nullable=False),
        sa.Column("json_pointer", sa.Text(), nullable=True),
        sa.Column("csv_row_number", sa.Integer(), nullable=True),
        sa.Column("requested_container", sa.String(length=128), nullable=True),
        sa.Column("source_payload_hash", sa.String(length=80), nullable=False),
        sa.ForeignKeyConstraint(
            ["evidence_record_id"], ["evidence_records.id"],
            name="fk_evidence_provenance_record_id_evidence_records",
            ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["raw_artifact_id"], ["raw_artifacts.id"],
            name="fk_evidence_provenance_raw_artifact_id_raw_artifacts",
            ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_evidence_provenance"),
        sa.UniqueConstraint("evidence_record_id", "artifact_path",
                            "json_pointer",
                            name="uq_evidence_provenance_record_locator"),
        sa.CheckConstraint("artifact_sha256 ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_evidence_provenance_artifact_digest"),
        sa.CheckConstraint("source_payload_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_evidence_provenance_payload_digest"),
        sa.CheckConstraint(
            "artifact_path !~ '(^/)|(^[A-Za-z]:)|(\\.\\.)|(\\\\)'",
            name="ck_evidence_provenance_path_relative"),
        # A locator addresses a record: a JSON pointer or a CSV row, never
        # both and never neither, or the trace stops at the file.
        sa.CheckConstraint(
            "(json_pointer IS NOT NULL AND csv_row_number IS NULL)"
            " OR (json_pointer IS NULL AND csv_row_number IS NOT NULL)",
            name="ck_evidence_provenance_addresses_one_record"),
        sa.CheckConstraint(
            "csv_row_number IS NULL OR csv_row_number >= 1",
            name="ck_evidence_provenance_csv_row_positive"),
    )
    op.create_index("ix_evidence_provenance_record_id", "evidence_provenance",
                    ["evidence_record_id"], unique=False)
    op.create_index("ix_evidence_provenance_artifact_sha256",
                    "evidence_provenance", ["artifact_sha256"], unique=False)

    # -- evidence_import_issues --------------------------------------------
    # Stored rather than logged: an issue that lived only in a log could not be
    # queried when someone later asks why a record is quarantined.
    op.create_table(
        "evidence_import_issues",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("evidence_build_id", _uuid(), nullable=False),
        sa.Column("evidence_record_id", _uuid(), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=24), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("natural_key", sa.String(length=512), nullable=True),
        sa.Column("locator", _jsonb(), nullable=True),
        sa.ForeignKeyConstraint(
            ["evidence_build_id"], ["evidence_builds.id"],
            name="fk_evidence_import_issues_build_id_evidence_builds",
            ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["evidence_record_id"], ["evidence_records.id"],
            name="fk_evidence_import_issues_record_id_evidence_records",
            ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_evidence_import_issues"),
        sa.CheckConstraint("severity IN (%s)" % ISSUE_SEVERITIES,
                           name="ck_evidence_import_issues_severity_enum"),
        sa.CheckConstraint("code ~ '^[A-Z][A-Z0-9_]*$'",
                           name="ck_evidence_import_issues_code_shape"),
        sa.CheckConstraint("length(trim(detail)) > 0",
                           name="ck_evidence_import_issues_detail_not_blank"),
    )
    op.create_index("ix_evidence_import_issues_build_id",
                    "evidence_import_issues", ["evidence_build_id"],
                    unique=False)
    op.create_index("ix_evidence_import_issues_code",
                    "evidence_import_issues", ["code"], unique=False)

    # -- immutability guard -------------------------------------------------
    op.execute(_FINALIZED_IMMUTABLE_FUNCTION)
    op.execute(_FINALIZED_IMMUTABLE_TRIGGER)


def downgrade() -> None:
    """Drop exactly the WP-08 objects, children before parents.

    The trigger and its function go first, so the next upgrade's
    ``CREATE FUNCTION`` is not met by a leftover. The ``0001`` provenance
    constraint and ``NOT NULL`` are restored last, after the columns they
    depend on are gone.
    """
    op.execute("DROP TRIGGER IF EXISTS trg_evidence_records_finalized_immutable "
               "ON evidence_records")
    op.execute("DROP FUNCTION IF EXISTS "
               "pgx_evidence_records_finalized_immutable()")

    op.drop_index("ix_evidence_import_issues_code",
                  table_name="evidence_import_issues")
    op.drop_index("ix_evidence_import_issues_build_id",
                  table_name="evidence_import_issues")
    op.drop_table("evidence_import_issues")

    op.drop_index("ix_evidence_provenance_artifact_sha256",
                  table_name="evidence_provenance")
    op.drop_index("ix_evidence_provenance_record_id",
                  table_name="evidence_provenance")
    op.drop_table("evidence_provenance")

    op.drop_index("ix_evidence_publications_reference_id",
                  table_name="evidence_publications")
    op.drop_index("ix_evidence_publications_record_id",
                  table_name="evidence_publications")
    op.drop_table("evidence_publications")

    op.drop_index("ix_publication_references_doi",
                  table_name="publication_references")
    op.drop_index("ix_publication_references_pmid",
                  table_name="publication_references")
    op.drop_table("publication_references")

    op.drop_index("ix_evidence_text_fragments_text_hash",
                  table_name="evidence_text_fragments")
    op.drop_index("ix_evidence_text_fragments_record_id",
                  table_name="evidence_text_fragments")
    op.drop_table("evidence_text_fragments")

    op.drop_index("ix_evidence_drugs_evidence_record_id",
                  table_name="evidence_drugs")
    op.drop_index("ix_evidence_drugs_drug_id", table_name="evidence_drugs")
    op.drop_table("evidence_drugs")

    op.drop_index("ix_evidence_genes_evidence_record_id",
                  table_name="evidence_genes")
    op.drop_index("ix_evidence_genes_gene_id", table_name="evidence_genes")
    op.drop_table("evidence_genes")

    op.drop_index("ix_evidence_records_origin_source_id",
                  table_name="evidence_records")
    op.drop_index("ix_evidence_records_evidence_build_id",
                  table_name="evidence_records")
    op.drop_index("ix_evidence_records_natural_key",
                  table_name="evidence_records")

    op.drop_constraint("ck_evidence_records_eligible_is_complete",
                       "evidence_records", type_="check")
    op.drop_constraint("ck_evidence_records_content_hash_format",
                       "evidence_records", type_="check")
    op.drop_constraint("ck_evidence_records_source_payload_hash_format",
                       "evidence_records", type_="check")
    op.drop_constraint("ck_evidence_records_origin_consistent",
                       "evidence_records", type_="check")
    op.drop_constraint("ck_evidence_records_origin_status_enum",
                       "evidence_records", type_="check")
    op.drop_constraint("ck_evidence_records_version_status_consistent",
                       "evidence_records", type_="check")
    op.drop_constraint("ck_evidence_records_version_status_enum",
                       "evidence_records", type_="check")
    op.drop_constraint("ck_evidence_records_mapping_status_enum",
                       "evidence_records", type_="check")
    op.drop_constraint("ck_evidence_records_type_enum", "evidence_records",
                       type_="check")

    op.drop_constraint("uq_evidence_records_natural_key", "evidence_records",
                       type_="unique")
    op.drop_constraint("fk_evidence_records_origin_source_id_source_registry",
                       "evidence_records", type_="foreignkey")
    op.drop_constraint("fk_evidence_records_evidence_build_id_evidence_builds",
                       "evidence_records", type_="foreignkey")

    op.drop_column("evidence_records", "finalized_at")
    op.drop_column("evidence_records", "production_eligible")
    op.drop_column("evidence_records", "evidence_content_hash")
    op.drop_column("evidence_records", "source_payload_hash")
    op.drop_column("evidence_records", "raw_origin_value")
    op.drop_column("evidence_records", "origin_source_status")
    op.drop_column("evidence_records", "origin_source_id")
    op.drop_column("evidence_records", "source_record_id_raw_type")
    op.drop_column("evidence_records", "source_record_version_status")
    op.drop_column("evidence_records", "record_type_mapping_status")
    op.drop_column("evidence_records", "source_object_class")
    op.drop_column("evidence_records", "record_type")
    op.drop_column("evidence_records", "natural_key")
    op.drop_column("evidence_records", "evidence_build_id")

    op.alter_column("evidence_records", "source_record_version",
                    existing_type=sa.String(length=64), nullable=False)
    op.create_unique_constraint(
        "uq_evidence_records_provenance", "evidence_records",
        PROVENANCE_UNIQUE_0001)

    op.drop_index("ix_evidence_builds_content_hash",
                  table_name="evidence_builds")
    op.drop_index("ix_evidence_builds_dataset_public_id",
                  table_name="evidence_builds")
    op.drop_table("evidence_builds")
