# -*- coding: utf-8 -*-
"""WP-06 immutable raw snapshot and dataset-build linkage schema.

Revision ID: 0004_wp06_raw_snapshots
Revises: 0003_wp05_source_policy
Create Date: 2026-08-30

Hand-written and reviewed, not blind autogenerate output. ``0001``, ``0002``
and ``0003`` are not touched: this revision only adds, plus one *widening* of
an existing check constraint described below.

Scope - two tables:

    raw_snapshots, raw_artifacts

plus one trigger that keeps a sealed snapshot's identity fixed, and one
constraint replacement that admits the new audit action.

**Why the audit constraint is replaced rather than left alone.**
``0002`` created ``ck_audit_events_action_enum`` over the five actions that
existed then. WP-06 adds ``DATASET_BUILD_REGISTERED``, so the constraint is
dropped and recreated with six. This is a widening, not a weakening: every
value the old constraint admitted is still admitted, nothing else is, and the
downgrade restores the exact five-value list. The append-only trigger on
``audit_events`` is untouched.

Three things here are load-bearing:

**A sealed snapshot's identity cannot be edited.**
``trg_raw_snapshots_identity_immutable`` refuses any ``UPDATE`` that changes the
dataset ID, either hash, the artifact count, the byte count, the kind or the
seal instant, and refuses every ``DELETE``. The one field an update may change
is ``dataset_version_id``, because registration legitimately happens after
sealing - and may happen on a retry after a failed one. Application code
promises not to rewrite a snapshot row; only the trigger survives someone with
a ``psql`` prompt.

**A quarantined or legacy snapshot can never be publication eligible.**
``ck_raw_snapshots_quarantine_not_publishable`` says so in the database, so the
rule holds even if a future service forgets it.

**Artifact paths are relative and traversal-free.**
``ck_raw_artifacts_relative_path`` refuses a leading separator, a ``..``
segment and a backslash. A manifest is validated in Python before it is
written; this is the same rule stated where a hand-written ``INSERT`` also
meets it.

``downgrade()`` removes exactly these objects, children before parents, drops
the trigger *and* its function, and restores the ``0002`` audit-action list.
Nothing from ``0001``, ``0002`` or ``0003`` is dropped, so
``0003 -> 0004 -> 0003 -> 0004`` is clean on a database that holds no WP-06
audit events.

**One documented downgrade limitation.** On a database that has already
recorded a ``DATASET_BUILD_REGISTERED`` event, the downgrade is *refused*:
restoring the five-value constraint fails because an existing row violates it,
and ``audit_events`` is append-only so the row cannot be deleted to make room.
That refusal is the correct outcome, not a defect - retro-narrowing a
constraint over an immutable audit trail would mean either lying about the
constraint or destroying history. An operator who genuinely needs to downgrade
such a database must decide explicitly what happens to those events; the
migration will not decide it for them. Verified on PostgreSQL 16.13; see
``docs/evidence/wp06-snapshot-verification.md``.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_wp06_raw_snapshots"
down_revision: Union[str, None] = "0003_wp05_source_policy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SHA256_DIGEST_REGEX = r"^sha256:[0-9a-f]{64}$"
DATASET_PUBLIC_ID_REGEX = r"^PGX-DATA-[0-9]{8}-[0-9]{3}$"

SNAPSHOT_KINDS = "'ACQUISITION', 'CACHE_REPLAY', 'LEGACY_IMPORT'"
SNAPSHOT_STATES = "'STAGING', 'SEALED', 'QUARANTINED'"
ARTIFACT_KINDS = "'RESPONSE_BODY', 'REQUEST_LOG', 'LEGACY_FILE'"

#: The audit actions ``0002`` created. Restored verbatim by ``downgrade()``.
AUDIT_ACTIONS_0002 = ("'RELEASE_REGISTERED', 'RELEASE_ACTIVATED', "
                      "'RELEASE_ROLLED_BACK', 'RELEASE_RETIRED', "
                      "'LEGACY_BASELINE_REGISTERED'")

#: The same list, widened by the one action WP-06 introduces. Written out in
#: full rather than concatenated: a migration is read years later by someone
#: asking "what exactly did this constraint permit", and the answer should be
#: on the line, not assembled from another one.
AUDIT_ACTIONS_0004 = ("'RELEASE_REGISTERED', 'RELEASE_ACTIVATED', "
                      "'RELEASE_ROLLED_BACK', 'RELEASE_RETIRED', "
                      "'LEGACY_BASELINE_REGISTERED', 'DATASET_BUILD_REGISTERED'")

_IDENTITY_FUNCTION = """
CREATE OR REPLACE FUNCTION pgx_raw_snapshots_identity_immutable()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'raw_snapshots rows are not deletable: a sealed snapshot is '
            'evidence, and evidence that can be removed answers no question '
            'worth asking.'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.dataset_public_id IS DISTINCT FROM OLD.dataset_public_id
       OR NEW.source_key IS DISTINCT FROM OLD.source_key
       OR NEW.snapshot_kind IS DISTINCT FROM OLD.snapshot_kind
       OR NEW.snapshot_content_hash IS DISTINCT FROM OLD.snapshot_content_hash
       OR NEW.manifest_hash IS DISTINCT FROM OLD.manifest_hash
       OR NEW.artifact_count IS DISTINCT FROM OLD.artifact_count
       OR NEW.total_byte_count IS DISTINCT FROM OLD.total_byte_count
       OR NEW.sealed_at IS DISTINCT FROM OLD.sealed_at THEN
        RAISE EXCEPTION
            'a sealed snapshot identity is immutable: only dataset_version_id '
            'and registration metadata may change after sealing.'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_IDENTITY_TRIGGER = """
CREATE TRIGGER trg_raw_snapshots_identity_immutable
BEFORE UPDATE OR DELETE ON raw_snapshots
FOR EACH ROW EXECUTE FUNCTION pgx_raw_snapshots_identity_immutable();
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
    """Create the WP-06 snapshot schema."""

    # -- raw_snapshots ----------------------------------------------------
    # dataset_version_id is nullable on purpose. Sealing a directory and
    # committing a row cannot be one transaction, so a snapshot may legitimately
    # exist, verified, with no dataset registered against it yet. Recording that
    # state is better than pretending the pair is atomic.
    op.create_table(
        "raw_snapshots",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("dataset_public_id", sa.String(length=64), nullable=False),
        sa.Column("source_key", sa.String(length=200), nullable=False),
        sa.Column("snapshot_kind", sa.String(length=24), nullable=False),
        sa.Column("snapshot_state", sa.String(length=24), nullable=False),
        sa.Column("snapshot_content_hash", sa.String(length=80), nullable=False),
        sa.Column("manifest_hash", sa.String(length=80), nullable=False),
        sa.Column("root_relative_path", sa.String(length=512), nullable=False),
        sa.Column("artifact_count", sa.Integer(), nullable=False),
        sa.Column("total_byte_count", sa.BigInteger(), nullable=False),
        sa.Column("acquisition_run_id", sa.String(length=128), nullable=True),
        sa.Column("acquisition_status", sa.String(length=32), nullable=True),
        sa.Column("acquisition_content_hash", sa.String(length=80), nullable=True),
        sa.Column("source_policy_status", sa.String(length=40), nullable=True),
        sa.Column("source_policy_content_hash", sa.String(length=80), nullable=True),
        sa.Column("publication_eligible", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("publication_gate", _jsonb(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("complete", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("warnings", _jsonb(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("limitations", _jsonb(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("legacy_origin", _jsonb(), nullable=True),
        sa.Column("sealed_at", _timestamptz(), nullable=False),
        sa.Column("registered_at", _timestamptz(), nullable=True),
        sa.Column("registered_by", sa.String(length=256), nullable=True),
        sa.Column("dataset_version_id", _uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"],
            name="fk_raw_snapshots_dataset_version_id_dataset_versions",
            ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_raw_snapshots"),
        sa.UniqueConstraint("dataset_public_id",
                            name="uq_raw_snapshots_dataset_public_id"),
        sa.UniqueConstraint("root_relative_path",
                            name="uq_raw_snapshots_root_relative_path"),
        sa.CheckConstraint("snapshot_kind IN (%s)" % SNAPSHOT_KINDS,
                           name="ck_raw_snapshots_kind_enum"),
        sa.CheckConstraint("snapshot_state IN (%s)" % SNAPSHOT_STATES,
                           name="ck_raw_snapshots_state_enum"),
        sa.CheckConstraint("dataset_public_id ~ '%s'" % DATASET_PUBLIC_ID_REGEX,
                           name="ck_raw_snapshots_dataset_id_format"),
        sa.CheckConstraint("snapshot_content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_raw_snapshots_content_hash_format"),
        sa.CheckConstraint("manifest_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_raw_snapshots_manifest_hash_format"),
        sa.CheckConstraint("artifact_count >= 0",
                           name="ck_raw_snapshots_artifact_count_positive"),
        sa.CheckConstraint("total_byte_count >= 0",
                           name="ck_raw_snapshots_byte_count_positive"),
        # A row is never written while the directory is still staging: staging
        # lives in a temporary path that no snapshot row may ever name.
        sa.CheckConstraint("snapshot_state <> 'STAGING'",
                           name="ck_raw_snapshots_never_staging"),
        # Quarantined and legacy snapshots can never be publication eligible.
        sa.CheckConstraint(
            "publication_eligible = false"
            " OR (snapshot_state <> 'QUARANTINED'"
            "     AND snapshot_kind <> 'LEGACY_IMPORT')",
            name="ck_raw_snapshots_quarantine_not_publishable"),
        # A legacy import has no WP-04 run. Recording one would be a fabrication.
        sa.CheckConstraint(
            "snapshot_kind <> 'LEGACY_IMPORT'"
            " OR (acquisition_run_id IS NULL AND acquisition_status IS NULL"
            "     AND acquisition_content_hash IS NULL)",
            name="ck_raw_snapshots_legacy_has_no_acquisition"),
        # And it must say what it cannot answer.
        sa.CheckConstraint(
            "snapshot_kind <> 'LEGACY_IMPORT'"
            " OR jsonb_array_length(limitations) > 0",
            name="ck_raw_snapshots_legacy_states_limitations"),
        # Registration metadata arrives together or not at all.
        sa.CheckConstraint(
            "(dataset_version_id IS NULL AND registered_at IS NULL"
            "  AND registered_by IS NULL)"
            " OR (dataset_version_id IS NOT NULL AND registered_at IS NOT NULL"
            "     AND registered_by IS NOT NULL"
            "     AND length(trim(registered_by)) > 0)",
            name="ck_raw_snapshots_registration_is_complete"),
        sa.CheckConstraint(
            "root_relative_path !~ '(^/)|(^[A-Za-z]:)|(\\.\\.)|(\\\\)'",
            name="ck_raw_snapshots_root_path_relative"),
    )
    op.create_index("ix_raw_snapshots_source_key", "raw_snapshots",
                    ["source_key"], unique=False)
    op.create_index("ix_raw_snapshots_content_hash", "raw_snapshots",
                    ["snapshot_content_hash"], unique=False)

    # -- raw_artifacts -----------------------------------------------------
    op.create_table(
        "raw_artifacts",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("snapshot_id", _uuid(), nullable=False),
        sa.Column("relative_path", sa.String(length=1024), nullable=False),
        sa.Column("artifact_kind", sa.String(length=24), nullable=False),
        sa.Column("byte_length", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=80), nullable=False),
        sa.Column("request_key", sa.String(length=80), nullable=True),
        sa.Column("endpoint_id", sa.String(length=200), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("content_type", sa.String(length=200), nullable=True),
        sa.Column("retrieval_ref", sa.String(length=80), nullable=True),
        sa.Column("source_relative_path", sa.String(length=1024), nullable=True),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["raw_snapshots.id"],
            name="fk_raw_artifacts_snapshot_id_raw_snapshots",
            ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_raw_artifacts"),
        sa.UniqueConstraint("snapshot_id", "relative_path",
                            name="uq_raw_artifacts_snapshot_id_relative_path"),
        sa.CheckConstraint("artifact_kind IN (%s)" % ARTIFACT_KINDS,
                           name="ck_raw_artifacts_kind_enum"),
        sa.CheckConstraint("sha256 ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_raw_artifacts_sha256_format"),
        sa.CheckConstraint(
            "request_key IS NULL OR request_key ~ '%s'" % SHA256_DIGEST_REGEX,
            name="ck_raw_artifacts_request_key_format"),
        sa.CheckConstraint("byte_length >= 0",
                           name="ck_raw_artifacts_byte_length_positive"),
        sa.CheckConstraint("length(trim(relative_path)) > 0",
                           name="ck_raw_artifacts_path_not_blank"),
        # Relative, traversal-free, forward-slash only. The same rule the
        # Python path guard applies, stated where a hand-written INSERT meets it.
        sa.CheckConstraint(
            "relative_path !~ '(^/)|(^[A-Za-z]:)|(\\.\\.)|(\\\\)'",
            name="ck_raw_artifacts_relative_path"),
        sa.CheckConstraint(
            "source_relative_path IS NULL"
            " OR source_relative_path !~ '(^/)|(^[A-Za-z]:)|(\\.\\.)|(\\\\)'",
            name="ck_raw_artifacts_source_path_relative"),
        # A response body came from a request; a legacy file did not.
        sa.CheckConstraint(
            "artifact_kind <> 'RESPONSE_BODY' OR request_key IS NOT NULL",
            name="ck_raw_artifacts_response_names_request"),
        sa.CheckConstraint(
            "artifact_kind <> 'LEGACY_FILE' OR request_key IS NULL",
            name="ck_raw_artifacts_legacy_has_no_request"),
    )
    op.create_index("ix_raw_artifacts_snapshot_id", "raw_artifacts",
                    ["snapshot_id"], unique=False)
    op.create_index("ix_raw_artifacts_sha256", "raw_artifacts", ["sha256"],
                    unique=False)

    # -- audit action parity ------------------------------------------------
    # Widened, never weakened: every previously permitted value still passes.
    op.drop_constraint("ck_audit_events_action_enum", "audit_events",
                       type_="check")
    op.create_check_constraint(
        "ck_audit_events_action_enum", "audit_events",
        sa.text("action IN (%s)" % AUDIT_ACTIONS_0004))

    # -- sealed identity guard ----------------------------------------------
    op.execute(_IDENTITY_FUNCTION)
    op.execute(_IDENTITY_TRIGGER)


def downgrade() -> None:
    """Drop exactly the WP-06 objects, children before parents.

    The trigger and its function go first: a downgrade that left the function
    behind would make the next upgrade fail on ``CREATE FUNCTION``. The audit
    action list is restored to the five values ``0002`` created. Nothing
    belonging to ``0001``, ``0002`` or ``0003`` is dropped.
    """
    op.execute("DROP TRIGGER IF EXISTS trg_raw_snapshots_identity_immutable "
               "ON raw_snapshots")
    op.execute("DROP FUNCTION IF EXISTS pgx_raw_snapshots_identity_immutable()")

    op.drop_constraint("ck_audit_events_action_enum", "audit_events",
                       type_="check")
    op.create_check_constraint(
        "ck_audit_events_action_enum", "audit_events",
        sa.text("action IN (%s)" % AUDIT_ACTIONS_0002))

    op.drop_index("ix_raw_artifacts_sha256", table_name="raw_artifacts")
    op.drop_index("ix_raw_artifacts_snapshot_id", table_name="raw_artifacts")
    op.drop_table("raw_artifacts")

    op.drop_index("ix_raw_snapshots_content_hash", table_name="raw_snapshots")
    op.drop_index("ix_raw_snapshots_source_key", table_name="raw_snapshots")
    op.drop_table("raw_snapshots")
