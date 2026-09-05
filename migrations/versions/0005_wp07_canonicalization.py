# -*- coding: utf-8 -*-
"""WP-07 canonical build, alias review, resolution queue and duplicate schema.

Revision ID: 0005_wp07_canonicalization
Revises: 0004_wp06_raw_snapshots
Create Date: 2026-08-30

Hand-written and reviewed, not blind autogenerate output. ``0001`` through
``0004`` are not rewritten: this revision adds tables and columns, plus two
constraint replacements described below.

Scope - five tables:

    canonical_builds, canonical_build_entities, resolution_queue_items,
    duplicate_groups, duplicate_group_members

four columns added to each of ``gene_aliases`` and ``drug_aliases``, one
trigger that keeps a recorded canonical build immutable, and two check
constraint replacements.

**Existing aliases become proposals, not approvals.**
``0001`` created ``gene_aliases`` and ``drug_aliases`` with no review state, and
its own comment reserved alias ambiguity for WP-07. Every row that already
exists is backfilled to ``PENDING_REVIEW``, which is the honest reading: nobody
reviewed them. A ``PENDING_REVIEW`` alias resolves nothing, so the effect of
this migration on an existing database is that observed alternative names stop
being able to decide what an entity is. That is the intended correction.

**No globally unique alias constraint.**
The primary key stays ``(gene_id, normalized_alias)``. The same alias may
legitimately belong to two genes, and a unique index across the table would
make that ambiguity un-storable - which would not remove the ambiguity, only the
project's ability to see it. Ambiguity is data here, and it goes to
``resolution_queue_items``.

**A conflicting-identity duplicate group is blocking, in the database.**
``ck_duplicate_groups_conflict_blocks`` refuses a ``CONFLICTING_IDENTITY`` row
that is not blocking, and refuses one that states no differences. Two records
claiming one source identity while disagreeing about content are not duplicates:
one is wrong, and discarding either hides which.

**A queue decision names a human.**
``ck_resolution_queue_decision_is_complete`` refuses a decision with no
reviewer, no instant or no rationale, and
``ck_resolution_queue_choice_was_a_candidate`` refuses a chosen key that was not
among the recorded candidates. WP-07 writes no decisions at all; the columns
exist so that a real one has somewhere to go.

**Two constraint replacements.**

1. ``ck_audit_events_action_enum`` is *widened* from six actions to seven to
   admit ``DATASET_QUALITY_CHECKED``. Every previously admitted value is still
   admitted. WP-07 emits no such event: the action exists so a future human
   decision can be recorded, and this package provides no way to record one.
2. ``ck_dataset_versions_published_requires_approval`` is *narrowed* and renamed
   to ``ck_dataset_versions_approval_requires_reviewer``, extending the
   requirement from ``PUBLISHED`` to ``QUALITY_CHECKED`` as well. A dataset
   marked quality checked with no named approver and no instant is precisely the
   fake approval this project must not be able to hold.

   A narrowing can fail on existing data, and this one deliberately can: the
   upgrade is refused if any ``QUALITY_CHECKED`` row lacks approval metadata.
   That refusal is the correct outcome - it names a row that claims a review
   nobody performed. No such row exists in this repository's database at the
   time of writing, because no dataset has ever been quality checked.

``downgrade()`` removes exactly these objects, children before parents, drops
the trigger *and* its function, restores the ``0004`` audit-action list and
restores the original ``PUBLISHED``-only approval constraint under its original
name, then drops the alias review columns. Nothing from ``0001`` through
``0004`` is otherwise touched.

**One documented downgrade limitation**, the same shape as ``0004``'s. On a
database that has recorded a ``DATASET_QUALITY_CHECKED`` event, the downgrade is
refused: restoring the six-value constraint fails because an existing row
violates it, and ``audit_events`` is append-only so the row cannot be removed to
make room. Retro-narrowing a constraint over an immutable audit trail would mean
either lying about the constraint or destroying history, and this migration
declines to choose for the operator.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_wp07_canonicalization"
down_revision: Union[str, None] = "0004_wp06_raw_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SHA256_DIGEST_REGEX = r"^sha256:[0-9a-f]{64}$"
DATASET_PUBLIC_ID_REGEX = r"^PGX-DATA-[0-9]{8}-[0-9]{3}$"

ENTITY_TYPES = "'GENE', 'DRUG'"
ALIAS_STATUSES = "'PENDING_REVIEW', 'APPROVED', 'REJECTED', 'DEPRECATED'"
RESOLUTION_STATUSES = ("'RESOLVED', 'AMBIGUOUS', 'UNRESOLVED', "
                       "'INVALID_INPUT', 'BROKEN_REFERENCE'")
RESOLUTION_STAGES = ("'EXTERNAL_ID', 'PREFERRED_NAME', 'APPROVED_ALIAS', "
                     "'CROSS_REFERENCE', 'NONE'")
DUPLICATE_CLASSES = "'EXACT', 'SEMANTIC', 'CONFLICTING_IDENTITY'"

#: The audit actions ``0004`` left in place. Restored verbatim by ``downgrade()``.
AUDIT_ACTIONS_0004 = ("'RELEASE_REGISTERED', 'RELEASE_ACTIVATED', "
                      "'RELEASE_ROLLED_BACK', 'RELEASE_RETIRED', "
                      "'LEGACY_BASELINE_REGISTERED', 'DATASET_BUILD_REGISTERED'")

#: The same list, widened by the one action WP-07 introduces. Written out in
#: full rather than concatenated, so the permitted set is readable on the line.
AUDIT_ACTIONS_0005 = ("'RELEASE_REGISTERED', 'RELEASE_ACTIVATED', "
                      "'RELEASE_ROLLED_BACK', 'RELEASE_RETIRED', "
                      "'LEGACY_BASELINE_REGISTERED', 'DATASET_BUILD_REGISTERED', "
                      "'DATASET_QUALITY_CHECKED'")

#: The ``0001`` approval rule, restored verbatim by ``downgrade()``.
APPROVAL_RULE_0001 = ("status <> 'PUBLISHED' OR (approved_by IS NOT NULL"
                      " AND length(trim(approved_by)) > 0"
                      " AND approved_at IS NOT NULL)")

#: The same rule extended to QUALITY_CHECKED.
APPROVAL_RULE_0005 = ("status NOT IN ('QUALITY_CHECKED', 'PUBLISHED')"
                      " OR (approved_by IS NOT NULL"
                      " AND length(trim(approved_by)) > 0"
                      " AND approved_at IS NOT NULL)")

_BUILD_IMMUTABLE_FUNCTION = """
CREATE OR REPLACE FUNCTION pgx_canonical_builds_immutable()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'canonical_builds rows are not deletable: a recorded build is the '
            'thing every canonical entity, queue item and duplicate group '
            'points at, and removing it would orphan all of them.'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.dataset_public_id IS DISTINCT FROM OLD.dataset_public_id
       OR NEW.canonical_build_key IS DISTINCT FROM OLD.canonical_build_key
       OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
       OR NEW.snapshot_manifest_hash IS DISTINCT FROM OLD.snapshot_manifest_hash
       OR NEW.allocation_content_hash IS DISTINCT FROM OLD.allocation_content_hash
       OR NEW.rule_versions IS DISTINCT FROM OLD.rule_versions
       OR NEW.built_at IS DISTINCT FROM OLD.built_at THEN
        RAISE EXCEPTION
            'a recorded canonical build is immutable: its identity, hashes and '
            'rule versions describe bytes that already exist on disk.'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_BUILD_IMMUTABLE_TRIGGER = """
CREATE TRIGGER trg_canonical_builds_immutable
BEFORE UPDATE OR DELETE ON canonical_builds
FOR EACH ROW EXECUTE FUNCTION pgx_canonical_builds_immutable();
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
    """Create the WP-07 canonicalization schema."""

    # -- alias review state -----------------------------------------------
    # Written out for both tables rather than looped. A migration is read years
    # later by someone asking "what exactly did this do to gene_aliases", and
    # the answer should be on the page rather than assembled from a loop.
    #
    # The column is added NOT NULL with a server default, so a table that
    # already holds rows acquires the value without a separate backfill pass;
    # the explicit UPDATE beside it states the intent for the reader and is a
    # no-op on a fresh database.
    op.add_column("gene_aliases", sa.Column(
        "status", sa.String(length=24), nullable=False,
        server_default=sa.text("'PENDING_REVIEW'")))
    op.add_column("gene_aliases", sa.Column(
        "reviewed_by", sa.String(length=256), nullable=True))
    op.add_column("gene_aliases", sa.Column(
        "reviewed_at", _timestamptz(), nullable=True))
    op.add_column("gene_aliases", sa.Column(
        "review_note", sa.Text(), nullable=True))
    # Every pre-existing alias is a proposal: nobody reviewed it.
    op.execute("UPDATE gene_aliases SET status = 'PENDING_REVIEW' "
               "WHERE status IS DISTINCT FROM 'PENDING_REVIEW'")
    op.create_check_constraint(
        "ck_gene_aliases_status_enum", "gene_aliases",
        sa.text("status IN (%s)" % ALIAS_STATUSES))
    # An approval that names nobody is not an approval.
    op.create_check_constraint(
        "ck_gene_aliases_approval_names_reviewer", "gene_aliases",
        sa.text("status <> 'APPROVED'"
                " OR (reviewed_by IS NOT NULL"
                " AND length(trim(reviewed_by)) > 0"
                " AND reviewed_at IS NOT NULL)"))
    op.create_index("ix_gene_aliases_status", "gene_aliases", ["status"],
                    unique=False)

    op.add_column("drug_aliases", sa.Column(
        "status", sa.String(length=24), nullable=False,
        server_default=sa.text("'PENDING_REVIEW'")))
    op.add_column("drug_aliases", sa.Column(
        "reviewed_by", sa.String(length=256), nullable=True))
    op.add_column("drug_aliases", sa.Column(
        "reviewed_at", _timestamptz(), nullable=True))
    op.add_column("drug_aliases", sa.Column(
        "review_note", sa.Text(), nullable=True))
    op.execute("UPDATE drug_aliases SET status = 'PENDING_REVIEW' "
               "WHERE status IS DISTINCT FROM 'PENDING_REVIEW'")
    op.create_check_constraint(
        "ck_drug_aliases_status_enum", "drug_aliases",
        sa.text("status IN (%s)" % ALIAS_STATUSES))
    op.create_check_constraint(
        "ck_drug_aliases_approval_names_reviewer", "drug_aliases",
        sa.text("status <> 'APPROVED'"
                " OR (reviewed_by IS NOT NULL"
                " AND length(trim(reviewed_by)) > 0"
                " AND reviewed_at IS NOT NULL)"))
    op.create_index("ix_drug_aliases_status", "drug_aliases", ["status"],
                    unique=False)

    # Deliberately NOT created, on either table: a UNIQUE index on
    # normalized_alias alone. Two entities may legitimately share an alias, and
    # a constraint that refused to store that would not remove the ambiguity,
    # only this project's ability to see it. Ambiguity is data here, and it
    # goes to resolution_queue_items.

    # -- canonical_builds --------------------------------------------------
    op.create_table(
        "canonical_builds",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("dataset_public_id", sa.String(length=64), nullable=False),
        sa.Column("canonical_build_key", sa.String(length=128), nullable=False),
        sa.Column("content_hash", sa.String(length=80), nullable=False),
        sa.Column("snapshot_manifest_hash", sa.String(length=80), nullable=False),
        sa.Column("snapshot_content_hash", sa.String(length=80), nullable=False),
        sa.Column("allocation_content_hash", sa.String(length=80), nullable=False),
        sa.Column("build_relative_path", sa.String(length=512), nullable=False),
        sa.Column("rule_versions", _jsonb(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("summary", _jsonb(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("source_observed_axes", _jsonb(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("dq_report_hash", sa.String(length=80), nullable=True),
        sa.Column("dq_gate_passed", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("dq_blocking_codes", _jsonb(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("built_at", _timestamptz(), nullable=False),
        sa.Column("recorded_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("dataset_version_id", _uuid(), nullable=True),
        sa.Column("raw_snapshot_id", _uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"],
            name="fk_canonical_builds_dataset_version_id_dataset_versions",
            ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["raw_snapshot_id"], ["raw_snapshots.id"],
            name="fk_canonical_builds_raw_snapshot_id_raw_snapshots",
            ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_canonical_builds"),
        sa.UniqueConstraint("canonical_build_key",
                            name="uq_canonical_builds_build_key"),
        sa.UniqueConstraint("build_relative_path",
                            name="uq_canonical_builds_build_relative_path"),
        sa.CheckConstraint("dataset_public_id ~ '%s'" % DATASET_PUBLIC_ID_REGEX,
                           name="ck_canonical_builds_dataset_id_format"),
        sa.CheckConstraint("content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_canonical_builds_content_hash_format"),
        sa.CheckConstraint(
            "snapshot_manifest_hash ~ '%s'" % SHA256_DIGEST_REGEX,
            name="ck_canonical_builds_manifest_hash_format"),
        sa.CheckConstraint(
            "snapshot_content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
            name="ck_canonical_builds_snapshot_hash_format"),
        sa.CheckConstraint(
            "allocation_content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
            name="ck_canonical_builds_allocation_hash_format"),
        sa.CheckConstraint(
            "dq_report_hash IS NULL OR dq_report_hash ~ '%s'"
            % SHA256_DIGEST_REGEX,
            name="ck_canonical_builds_dq_hash_format"),
        sa.CheckConstraint(
            "build_relative_path !~ '(^/)|(^[A-Za-z]:)|(\\.\\.)|(\\\\)'",
            name="ck_canonical_builds_path_relative"),
        # A gate that passed lists no blocking codes, and a gate that listed
        # blocking codes did not pass. Storing both would make the record
        # self-contradictory, and the contradiction would be invisible.
        sa.CheckConstraint(
            "(dq_gate_passed = false)"
            " OR jsonb_array_length(dq_blocking_codes) = 0",
            name="ck_canonical_builds_pass_has_no_blocking_codes"),
    )
    op.create_index("ix_canonical_builds_dataset_public_id", "canonical_builds",
                    ["dataset_public_id"], unique=False)
    op.create_index("ix_canonical_builds_content_hash", "canonical_builds",
                    ["content_hash"], unique=False)

    # -- canonical_build_entities -----------------------------------------
    # Membership, not identity: the gene and drug rows themselves live in the
    # 0001 tables. This says which build produced which entity, and with which
    # allocated UUID, so two builds of one dataset can be compared row by row.
    op.create_table(
        "canonical_build_entities",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("canonical_build_id", _uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=8), nullable=False),
        sa.Column("canonical_key", sa.String(length=256), nullable=False),
        sa.Column("normalized_value", sa.String(length=200), nullable=False),
        sa.Column("entity_uuid", _uuid(), nullable=False),
        sa.Column("preferred_display", sa.String(length=512), nullable=False),
        sa.Column("source_display", sa.String(length=512), nullable=False),
        sa.Column("external_ids", _jsonb(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("locator_count", sa.Integer(), nullable=False),
        sa.Column("alias_proposal_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("approved_alias_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("findings", _jsonb(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.ForeignKeyConstraint(
            ["canonical_build_id"], ["canonical_builds.id"],
            name="fk_canonical_build_entities_build_id_canonical_builds",
            ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_canonical_build_entities"),
        sa.UniqueConstraint("canonical_build_id", "canonical_key",
                            name="uq_canonical_build_entities_build_key"),
        sa.CheckConstraint("entity_type IN (%s)" % ENTITY_TYPES,
                           name="ck_canonical_build_entities_type_enum"),
        sa.CheckConstraint(
            "canonical_key = entity_type || ':' || normalized_value",
            name="ck_canonical_build_entities_key_matches_value"),
        sa.CheckConstraint(
            "entity_type <> 'GENE'"
            " OR normalized_value = upper(trim(normalized_value))",
            name="ck_canonical_build_entities_gene_normalized"),
        sa.CheckConstraint(
            "entity_type <> 'DRUG'"
            " OR normalized_value = lower(trim(normalized_value))",
            name="ck_canonical_build_entities_drug_normalized"),
        # An entity with no provenance link cannot be traced to a source.
        sa.CheckConstraint("locator_count >= 1",
                           name="ck_canonical_build_entities_has_provenance"),
        sa.CheckConstraint(
            "approved_alias_count >= 0"
            " AND approved_alias_count <= alias_proposal_count",
            name="ck_canonical_build_entities_alias_counts_consistent"),
    )
    op.create_index("ix_canonical_build_entities_entity_uuid",
                    "canonical_build_entities", ["entity_uuid"], unique=False)
    op.create_index("ix_canonical_build_entities_canonical_key",
                    "canonical_build_entities", ["canonical_key"], unique=False)

    # -- resolution_queue_items -------------------------------------------
    op.create_table(
        "resolution_queue_items",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("canonical_build_id", _uuid(), nullable=False),
        sa.Column("queue_key", sa.String(length=1024), nullable=False),
        sa.Column("entity_type", sa.String(length=8), nullable=False),
        sa.Column("submitted_value", sa.Text(), nullable=False),
        sa.Column("normalized_value", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("stage", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.String(length=48), nullable=False),
        sa.Column("candidate_keys", _jsonb(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("locator", _jsonb(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", _timestamptz(), nullable=False),
        sa.Column("decided_by", sa.String(length=256), nullable=True),
        sa.Column("decided_at", _timestamptz(), nullable=True),
        sa.Column("decision_rationale", sa.Text(), nullable=True),
        sa.Column("chosen_canonical_key", sa.String(length=256), nullable=True),
        sa.ForeignKeyConstraint(
            ["canonical_build_id"], ["canonical_builds.id"],
            name="fk_resolution_queue_items_build_id_canonical_builds",
            ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_resolution_queue_items"),
        sa.UniqueConstraint("canonical_build_id", "queue_key",
                            name="uq_resolution_queue_items_build_queue_key"),
        sa.CheckConstraint("entity_type IN (%s)" % ENTITY_TYPES,
                           name="ck_resolution_queue_items_type_enum"),
        sa.CheckConstraint("status IN (%s)" % RESOLUTION_STATUSES,
                           name="ck_resolution_queue_items_status_enum"),
        sa.CheckConstraint("stage IN (%s)" % RESOLUTION_STAGES,
                           name="ck_resolution_queue_items_stage_enum"),
        # A RESOLVED outcome is not a queue item: it needs no review.
        sa.CheckConstraint("status <> 'RESOLVED'",
                           name="ck_resolution_queue_items_needs_review"),
        # An ambiguity carries every candidate. One candidate is not ambiguous,
        # and storing only the chosen one would be the silent selection this
        # table exists to prevent.
        sa.CheckConstraint(
            "status <> 'AMBIGUOUS' OR jsonb_array_length(candidate_keys) >= 2",
            name="ck_resolution_queue_items_ambiguity_has_candidates"),
        # A decision names a human, an instant and a reason - or does not exist.
        sa.CheckConstraint(
            "(decided_by IS NULL AND decided_at IS NULL"
            "  AND decision_rationale IS NULL AND chosen_canonical_key IS NULL)"
            " OR (decided_by IS NOT NULL AND length(trim(decided_by)) > 0"
            "     AND decided_at IS NOT NULL"
            "     AND decision_rationale IS NOT NULL"
            "     AND length(trim(decision_rationale)) > 0)",
            name="ck_resolution_queue_decision_is_complete"),
        # And it may only choose something that was actually a candidate.
        sa.CheckConstraint(
            "chosen_canonical_key IS NULL"
            " OR jsonb_array_length(candidate_keys) = 0"
            " OR candidate_keys ? chosen_canonical_key",
            name="ck_resolution_queue_choice_was_a_candidate"),
    )
    op.create_index("ix_resolution_queue_items_status",
                    "resolution_queue_items", ["status"], unique=False)
    op.create_index("ix_resolution_queue_items_build_id",
                    "resolution_queue_items", ["canonical_build_id"],
                    unique=False)

    # -- duplicate_groups and members --------------------------------------
    op.create_table(
        "duplicate_groups",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("canonical_build_id", _uuid(), nullable=False),
        sa.Column("group_key", sa.String(length=1024), nullable=False),
        sa.Column("record_type", sa.String(length=64), nullable=False),
        sa.Column("dedup_key_version", sa.String(length=64), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("representative_digest", sa.String(length=80), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("container_spellings", _jsonb(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("differences", _jsonb(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("blocking", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.ForeignKeyConstraint(
            ["canonical_build_id"], ["canonical_builds.id"],
            name="fk_duplicate_groups_build_id_canonical_builds",
            ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_duplicate_groups"),
        sa.UniqueConstraint("canonical_build_id", "group_key",
                            name="uq_duplicate_groups_build_group_key"),
        sa.CheckConstraint("classification IN (%s)" % DUPLICATE_CLASSES,
                           name="ck_duplicate_groups_classification_enum"),
        sa.CheckConstraint(
            "representative_digest ~ '%s'" % SHA256_DIGEST_REGEX,
            name="ck_duplicate_groups_representative_digest_format"),
        # One observation is not a duplicate.
        sa.CheckConstraint("member_count >= 2",
                           name="ck_duplicate_groups_member_count"),
        # A conflicting identity collision always blocks and always says what
        # differs. Discarding one of two records that disagree hides which was
        # wrong, so the database refuses to hold a non-blocking one.
        sa.CheckConstraint(
            "classification <> 'CONFLICTING_IDENTITY'"
            " OR (blocking = true AND jsonb_array_length(differences) > 0)",
            name="ck_duplicate_groups_conflict_blocks"),
    )
    op.create_index("ix_duplicate_groups_classification", "duplicate_groups",
                    ["classification"], unique=False)
    op.create_index("ix_duplicate_groups_build_id", "duplicate_groups",
                    ["canonical_build_id"], unique=False)

    # Every member's locator is kept. Choosing a representative is a storage
    # convenience; the provenance link is the thing a duplicate group exists
    # to preserve, and losing one would make the collapse irreversible.
    op.create_table(
        "duplicate_group_members",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("duplicate_group_id", _uuid(), nullable=False),
        sa.Column("artifact_path", sa.String(length=1024), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=80), nullable=False),
        sa.Column("pointer", sa.Text(), nullable=False),
        sa.Column("source_record_id", sa.String(length=256), nullable=True),
        sa.Column("payload_digest", sa.String(length=80), nullable=False),
        sa.Column("container_spelling", sa.String(length=256), nullable=True),
        sa.ForeignKeyConstraint(
            ["duplicate_group_id"], ["duplicate_groups.id"],
            name="fk_duplicate_group_members_group_id_duplicate_groups",
            ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_duplicate_group_members"),
        sa.UniqueConstraint("duplicate_group_id", "artifact_path", "pointer",
                            name="uq_duplicate_group_members_group_locator"),
        sa.CheckConstraint("artifact_sha256 ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_duplicate_group_members_artifact_digest"),
        sa.CheckConstraint("payload_digest ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_duplicate_group_members_payload_digest"),
        sa.CheckConstraint(
            "artifact_path !~ '(^/)|(^[A-Za-z]:)|(\\.\\.)|(\\\\)'",
            name="ck_duplicate_group_members_path_relative"),
    )
    op.create_index("ix_duplicate_group_members_group_id",
                    "duplicate_group_members", ["duplicate_group_id"],
                    unique=False)

    # -- audit action parity ------------------------------------------------
    # Widened, never weakened: every previously permitted value still passes.
    op.drop_constraint("ck_audit_events_action_enum", "audit_events",
                       type_="check")
    op.create_check_constraint(
        "ck_audit_events_action_enum", "audit_events",
        sa.text("action IN (%s)" % AUDIT_ACTIONS_0005))

    # -- approval parity ----------------------------------------------------
    # Narrowed on purpose. See the module docstring: a QUALITY_CHECKED dataset
    # with no named approver is a fake approval, and the upgrade is refused
    # rather than allowed to keep one.
    op.drop_constraint("ck_dataset_versions_published_requires_approval",
                       "dataset_versions", type_="check")
    op.create_check_constraint(
        "ck_dataset_versions_approval_requires_reviewer", "dataset_versions",
        sa.text(APPROVAL_RULE_0005))

    # -- immutable build guard ----------------------------------------------
    op.execute(_BUILD_IMMUTABLE_FUNCTION)
    op.execute(_BUILD_IMMUTABLE_TRIGGER)


def downgrade() -> None:
    """Drop exactly the WP-07 objects, children before parents.

    The trigger and its function go first, so the next upgrade's
    ``CREATE FUNCTION`` is not met by a leftover. The audit action list and the
    approval constraint are restored to what ``0004`` and ``0001`` left, under
    their original names. Nothing belonging to ``0001`` through ``0004`` is
    otherwise dropped.
    """
    op.execute("DROP TRIGGER IF EXISTS trg_canonical_builds_immutable "
               "ON canonical_builds")
    op.execute("DROP FUNCTION IF EXISTS pgx_canonical_builds_immutable()")

    op.drop_constraint("ck_dataset_versions_approval_requires_reviewer",
                       "dataset_versions", type_="check")
    op.create_check_constraint(
        "ck_dataset_versions_published_requires_approval", "dataset_versions",
        sa.text(APPROVAL_RULE_0001))

    op.drop_constraint("ck_audit_events_action_enum", "audit_events",
                       type_="check")
    op.create_check_constraint(
        "ck_audit_events_action_enum", "audit_events",
        sa.text("action IN (%s)" % AUDIT_ACTIONS_0004))

    op.drop_index("ix_duplicate_group_members_group_id",
                  table_name="duplicate_group_members")
    op.drop_table("duplicate_group_members")

    op.drop_index("ix_duplicate_groups_build_id", table_name="duplicate_groups")
    op.drop_index("ix_duplicate_groups_classification",
                  table_name="duplicate_groups")
    op.drop_table("duplicate_groups")

    op.drop_index("ix_resolution_queue_items_build_id",
                  table_name="resolution_queue_items")
    op.drop_index("ix_resolution_queue_items_status",
                  table_name="resolution_queue_items")
    op.drop_table("resolution_queue_items")

    op.drop_index("ix_canonical_build_entities_canonical_key",
                  table_name="canonical_build_entities")
    op.drop_index("ix_canonical_build_entities_entity_uuid",
                  table_name="canonical_build_entities")
    op.drop_table("canonical_build_entities")

    op.drop_index("ix_canonical_builds_content_hash",
                  table_name="canonical_builds")
    op.drop_index("ix_canonical_builds_dataset_public_id",
                  table_name="canonical_builds")
    op.drop_table("canonical_builds")

    op.drop_index("ix_drug_aliases_status", table_name="drug_aliases")
    op.drop_constraint("ck_drug_aliases_approval_names_reviewer",
                       "drug_aliases", type_="check")
    op.drop_constraint("ck_drug_aliases_status_enum", "drug_aliases",
                       type_="check")
    op.drop_column("drug_aliases", "review_note")
    op.drop_column("drug_aliases", "reviewed_at")
    op.drop_column("drug_aliases", "reviewed_by")
    op.drop_column("drug_aliases", "status")

    op.drop_index("ix_gene_aliases_status", table_name="gene_aliases")
    op.drop_constraint("ck_gene_aliases_approval_names_reviewer",
                       "gene_aliases", type_="check")
    op.drop_constraint("ck_gene_aliases_status_enum", "gene_aliases",
                       type_="check")
    op.drop_column("gene_aliases", "review_note")
    op.drop_column("gene_aliases", "reviewed_at")
    op.drop_column("gene_aliases", "reviewed_by")
    op.drop_column("gene_aliases", "status")
