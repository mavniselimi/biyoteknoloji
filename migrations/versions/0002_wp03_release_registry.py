# -*- coding: utf-8 -*-
"""WP-03 release registry schema.

Revision ID: 0002_wp03_release_registry
Revises: 0001_wp02_foundation
Create Date: 2026-08-29

Hand-written and reviewed, not blind autogenerate output. ``0001`` is not
touched: this revision only adds.

Scope - six tables:

    software_versions, ruleset_versions, ruleset_rules, release_bundles,
    active_release, audit_events

plus one trigger that makes ``audit_events`` genuinely append-only.

Two things here are load-bearing and easy to get wrong:

**The singleton pointer is created by this migration.** ``active_release`` gets
its one row here, with ``release_id`` NULL and ``generation`` 0. Activation can
then always ``SELECT ... FOR UPDATE`` the same row. If the row were created
lazily on first activation, two concurrent first activations would each find
nothing to lock, both insert, and the "singleton" would have been a singleton
only after the race it was supposed to prevent.

**Append-only is enforced in the database.** ``trg_audit_events_append_only``
raises on ``UPDATE`` and ``DELETE``. The port omits both methods and the
repository implements neither, but those are application promises; only the
trigger survives someone with a ``psql`` prompt.

``downgrade()`` removes exactly these objects, children before parents, and
drops the trigger *and* its function - a downgrade that leaves a function
behind makes the next upgrade fail on ``CREATE FUNCTION``. Nothing from
``0001`` is dropped, so ``0001 -> 0002 -> 0001 -> 0002`` is clean.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_wp03_release_registry"
down_revision: Union[str, None] = "0001_wp02_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Canonical digest spelling produced by pgx.domain.hashing.sha256_digest.
SHA256_DIGEST_REGEX = r"^sha256:[0-9a-f]{64}$"
RULESET_PUBLIC_ID_REGEX = r"^PGX-RULESET-[0-9]{8}-[0-9]{3}$"
RELEASE_PUBLIC_ID_REGEX = r"^PGX-REL-[0-9]{8}-[0-9]{3}$"

RULESET_STATUSES = "'BUILDING', 'VALIDATED', 'FROZEN', 'RETIRED'"
RELEASE_STATUSES = "'DRAFT', 'ACTIVE', 'ROLLED_BACK', 'RETIRED'"
AUDIT_ACTIONS = ("'RELEASE_REGISTERED', 'RELEASE_ACTIVATED', 'RELEASE_ROLLED_BACK', "
                 "'RELEASE_RETIRED', 'LEGACY_BASELINE_REGISTERED'")

#: The one legal primary key of the active-release pointer row.
ACTIVE_RELEASE_SINGLETON_ID = 1

#: Actor recorded on the pointer row the migration seeds. It is not a person:
#: the row exists so activation has something to lock, and it names no release.
BOOTSTRAP_ACTOR = "system:migration/0002_wp03_release_registry"

_APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION pgx_audit_events_append_only()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'audit_events is append-only: % is not permitted. An audit trail that '
        'can be rewritten answers no question worth asking.', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

_APPEND_ONLY_TRIGGER = """
CREATE TRIGGER trg_audit_events_append_only
BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION pgx_audit_events_append_only();
"""


def _uuid() -> postgresql.UUID:
    """Application-supplied UUID; no server extension is required."""
    return postgresql.UUID(as_uuid=True)


def _timestamptz() -> postgresql.TIMESTAMP:
    """Timezone-aware timestamp; a naive instant is not storable."""
    return postgresql.TIMESTAMP(timezone=True)


def upgrade() -> None:
    """Create the WP-03 release registry."""

    # -- software_versions ----------------------------------------------
    # source_tree_hash is unique, not version: two builds may legitimately
    # declare the same version string and differ in code.
    op.create_table(
        "software_versions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("source_commit", sa.String(length=128), nullable=False),
        sa.Column("source_tree_hash", sa.String(length=80), nullable=False),
        sa.Column("manifest_hash", sa.String(length=80), nullable=False),
        sa.Column("built_at", _timestamptz(), nullable=False),
        sa.Column("created_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("build_metadata", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint("id", name="pk_software_versions"),
        sa.UniqueConstraint("source_tree_hash",
                            name="uq_software_versions_source_tree_hash"),
        sa.CheckConstraint("length(trim(version)) > 0",
                           name="ck_software_versions_version_not_blank"),
        sa.CheckConstraint("length(trim(source_commit)) > 0",
                           name="ck_software_versions_source_commit_not_blank"),
        sa.CheckConstraint("source_tree_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_software_versions_source_tree_hash_format"),
        sa.CheckConstraint("manifest_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_software_versions_manifest_hash_format"),
    )

    # -- ruleset_versions -----------------------------------------------
    op.create_table(
        "ruleset_versions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("manifest_hash", sa.String(length=80), nullable=False),
        sa.Column("created_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("approved_by", sa.String(length=256), nullable=True),
        sa.Column("approved_at", _timestamptz(), nullable=True),
        sa.Column("legacy_id", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ruleset_versions"),
        sa.UniqueConstraint("public_id", name="uq_ruleset_versions_public_id"),
        sa.CheckConstraint("status IN (%s)" % RULESET_STATUSES,
                           name="ck_ruleset_versions_status_enum"),
        sa.CheckConstraint("public_id ~ '%s'" % RULESET_PUBLIC_ID_REGEX,
                           name="ck_ruleset_versions_public_id_format"),
        sa.CheckConstraint("manifest_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_ruleset_versions_manifest_hash_format"),
        sa.CheckConstraint(
            "status NOT IN ('VALIDATED', 'FROZEN') OR ("
            " approved_by IS NOT NULL AND length(trim(approved_by)) > 0"
            " AND approved_at IS NOT NULL)",
            name="ck_ruleset_versions_approved_requires_approval_metadata"),
    )

    # -- ruleset_rules ---------------------------------------------------
    # The composite primary key is what forbids duplicate membership.
    # Asymmetric ondelete: dropping a ruleset takes its membership with it;
    # dropping a rule a ruleset pins is refused, because a released ruleset
    # that silently loses a member is the drift this registry exists to stop.
    op.create_table(
        "ruleset_rules",
        sa.Column("ruleset_id", _uuid(), nullable=False),
        sa.Column("rule_id", _uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ruleset_id"], ["ruleset_versions.id"],
            name="fk_ruleset_rules_ruleset_id_ruleset_versions", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["rule_id"], ["computable_rules.id"],
            name="fk_ruleset_rules_rule_id_computable_rules", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("ruleset_id", "rule_id", name="pk_ruleset_rules"),
    )
    op.create_index("ix_ruleset_rules_rule_id", "ruleset_rules", ["rule_id"],
                    unique=False)

    # -- release_bundles -------------------------------------------------
    op.create_table(
        "release_bundles",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("software_version_id", _uuid(), nullable=False),
        sa.Column("dataset_version_id", _uuid(), nullable=False),
        sa.Column("ruleset_version_id", _uuid(), nullable=False),
        sa.Column("manifest_json", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False),
        sa.Column("manifest_hash", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("activated_at", _timestamptz(), nullable=True),
        sa.Column("activated_by", sa.String(length=256), nullable=True),
        sa.Column("legacy_id", sa.String(length=128), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["software_version_id"], ["software_versions.id"],
            name="fk_release_bundles_software_version_id_software_versions",
            ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"],
            name="fk_release_bundles_dataset_version_id_dataset_versions",
            ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["ruleset_version_id"], ["ruleset_versions.id"],
            name="fk_release_bundles_ruleset_version_id_ruleset_versions",
            ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_release_bundles"),
        sa.UniqueConstraint("public_id", name="uq_release_bundles_public_id"),
        sa.CheckConstraint("status IN (%s)" % RELEASE_STATUSES,
                           name="ck_release_bundles_status_enum"),
        sa.CheckConstraint("public_id ~ '%s'" % RELEASE_PUBLIC_ID_REGEX,
                           name="ck_release_bundles_public_id_format"),
        sa.CheckConstraint("manifest_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_release_bundles_manifest_hash_format"),
        sa.CheckConstraint(
            "(status IN ('ACTIVE', 'ROLLED_BACK') AND activated_at IS NOT NULL"
            " AND activated_by IS NOT NULL AND length(trim(activated_by)) > 0)"
            " OR (status = 'DRAFT' AND activated_at IS NULL AND activated_by IS NULL)"
            " OR status = 'RETIRED'",
            name="ck_release_bundles_activation_metadata_matches_status"),
    )
    op.create_index("ix_release_bundles_status", "release_bundles", ["status"],
                    unique=False)

    # -- active_release --------------------------------------------------
    op.create_table(
        "active_release",
        sa.Column("singleton_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("release_id", _uuid(), nullable=True),
        sa.Column("generation", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("updated_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_by", sa.String(length=256), nullable=False),
        sa.ForeignKeyConstraint(
            ["release_id"], ["release_bundles.id"],
            name="fk_active_release_release_id_release_bundles", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("singleton_id", name="pk_active_release"),
        sa.CheckConstraint("singleton_id = %d" % ACTIVE_RELEASE_SINGLETON_ID,
                           name="ck_active_release_singleton"),
        sa.CheckConstraint("generation >= 0",
                           name="ck_active_release_generation_not_negative"),
        sa.CheckConstraint("length(trim(updated_by)) > 0",
                           name="ck_active_release_updated_by_not_blank"),
        sa.CheckConstraint("generation = 0 OR release_id IS NOT NULL",
                           name="ck_active_release_moved_pointer_names_a_release"),
    )

    # The one row, created now rather than lazily: activation must always have
    # the same row to lock, including the very first activation.
    op.execute(
        sa.text(
            "INSERT INTO active_release "
            "(singleton_id, release_id, generation, updated_at, updated_by) "
            "VALUES (:singleton_id, NULL, 0, now(), :actor)"
        ).bindparams(singleton_id=ACTIVE_RELEASE_SINGLETON_ID, actor=BOOTSTRAP_ACTOR)
    )

    # -- audit_events ----------------------------------------------------
    op.create_table(
        "audit_events",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=256), nullable=False),
        sa.Column("object_type", sa.String(length=64), nullable=False),
        sa.Column("object_id", sa.String(length=128), nullable=False),
        sa.Column("previous_release_id", _uuid(), nullable=True),
        sa.Column("new_release_id", _uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("occurred_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["previous_release_id"], ["release_bundles.id"],
            name="fk_audit_events_previous_release_id_release_bundles",
            ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["new_release_id"], ["release_bundles.id"],
            name="fk_audit_events_new_release_id_release_bundles",
            ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
        sa.CheckConstraint("action IN (%s)" % AUDIT_ACTIONS,
                           name="ck_audit_events_action_enum"),
        sa.CheckConstraint("length(trim(actor)) > 0",
                           name="ck_audit_events_actor_not_blank"),
        sa.CheckConstraint("length(trim(object_type)) > 0",
                           name="ck_audit_events_object_type_not_blank"),
        sa.CheckConstraint("length(trim(object_id)) > 0",
                           name="ck_audit_events_object_id_not_blank"),
        sa.CheckConstraint(
            "action NOT IN ('RELEASE_ACTIVATED', 'RELEASE_ROLLED_BACK')"
            " OR new_release_id IS NOT NULL",
            name="ck_audit_events_pointer_event_names_new_release"),
    )
    op.create_index("ix_audit_events_object_type_object_id", "audit_events",
                    ["object_type", "object_id"], unique=False)
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"],
                    unique=False)

    # Append-only, enforced by the database rather than only by the application.
    op.execute(_APPEND_ONLY_FUNCTION)
    op.execute(_APPEND_ONLY_TRIGGER)


def downgrade() -> None:
    """Drop exactly the WP-03 objects, children before parents.

    The trigger and its function go first: a downgrade that left the function
    behind would make the next upgrade fail on ``CREATE FUNCTION``. Nothing
    belonging to ``0001`` is touched.
    """
    op.execute("DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS pgx_audit_events_append_only()")

    op.drop_index("ix_audit_events_occurred_at", table_name="audit_events")
    op.drop_index("ix_audit_events_object_type_object_id", table_name="audit_events")
    op.drop_table("audit_events")

    # The pointer references release_bundles, so it goes before them.
    op.drop_table("active_release")

    op.drop_index("ix_release_bundles_status", table_name="release_bundles")
    op.drop_table("release_bundles")

    op.drop_index("ix_ruleset_rules_rule_id", table_name="ruleset_rules")
    op.drop_table("ruleset_rules")

    op.drop_table("ruleset_versions")
    op.drop_table("software_versions")
