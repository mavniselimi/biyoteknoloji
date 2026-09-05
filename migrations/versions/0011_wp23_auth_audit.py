# -*- coding: utf-8 -*-
"""WP-23 authentication, sessions and the canonical governed audit trail.

Revision ID: 0011_wp23_auth_audit
Revises: 0010_wp22_expert_reviews
Create Date: 2026-09-05

Hand-written and reviewed, not autogenerate output. Five new tables beside the
existing schema, plus one widening of WP-22's ``actor_authenticated``
constraint.

**Nothing historical is rewritten.** ``audit_events`` from 0002, the curation
trail from 0007 and WP-22's review trail from 0010 keep every row and every
meaning. There is no backfill into the canonical stream, and there must never
be one: those rows were written by a system with no authentication, and giving
them an actor and an assurance level would be manufacturing provenance - the
exact failure an audit trail exists to prevent.

**Which layer enforces which invariant.** Stated here because "enforced" with
no named enforcer is how an invariant quietly stops holding.

| Invariant | Enforced by |
|---|---|
| one account per canonical username | `uq_security_users_username` |
| a username is already lowercased | `ck_security_users_username_is_canonical` |
| a stored hash is argon2id, never bcrypt or PBKDF2 | `ck_security_users_password_hash_is_argon2id` |
| an active account has a hash | `password_hash NOT NULL` |
| only a locked account carries a lock expiry | `ck_security_users_only_a_locked_account_has_a_lock_expiry` |
| one session per token digest | `uq_security_sessions_token_digest` |
| a session row never holds a raw token | `ck_security_sessions_token_digest_format` |
| the absolute bound is not before the idle bound | `ck_security_sessions_absolute_bound_is_not_before_idle_bound` |
| a revoked session names why | `ck_security_sessions_revocation_names_its_reason` |
| a user is never deleted out from under a session | `fk_security_sessions_user_id_security_users` (`ON DELETE RESTRICT`) |
| only a real session may claim SESSION assurance | `ck_governed_audit_events_only_a_session_carries_session_assurance` |
| a session-authenticated event names its session | `ck_governed_audit_events_a_session_event_names_its_session` |
| the chain starts once and links | `ck_governed_audit_events_first_event_starts_the_chain`, `uq_governed_audit_events_stream_sequence` |
| **audit rows cannot be edited or removed** | `trg_governed_audit_events_append_only` |
| **two appenders cannot fork the chain** | `governed_audit_stream_head` + `SELECT ... FOR UPDATE` |
| rate-limit buckets are keyed by digest | `ck_security_rate_limit_counters_key_digest_format` |

**The head table is the concurrency story.** Deriving the tail with ``SELECT
max(sequence)`` and then inserting is a read-then-write race whose losing side
is a forked chain: two events at the same sequence, each linking to the same
predecessor, both of which verify in isolation. One row per stream, locked
``FOR UPDATE`` before the append, makes that impossible rather than unlikely.
The trigger below additionally refuses any insert whose sequence does not
follow the recorded head, so a caller that skipped the lock is refused by the
server rather than trusted.

**Users are never deleted.** There is no cascade anywhere near
``security_users``: the session foreign key is ``ON DELETE RESTRICT``, and
audit rows reference an actor by value rather than by key precisely so that no
deletion could ever orphan or remove one.

**WP-22's constraint changes in the open.** ``ck_expert_review_audit_events_
no_p0_principal_is_authenticated`` pinned ``actor_authenticated = false``
because WP-22 had no authentication to justify a true. This migration replaces
it with a constraint permitting true, which is the visible, reviewed change
that comment asked for. Static development tokens still record false - that is
enforced in the service, because the database cannot see which mechanism
produced a row.

**Documented downgrade refusal.** ``downgrade()`` refuses, in a single
transaction that changes nothing, when the database holds any user, session or
governed audit event. Dropping those tables would destroy the account history
and the integrity chain together, which is the single most destructive
statement this repository could contain. An empty database downgrades cleanly.

**This migration has not been executed.** No PostgreSQL server is available in
this environment. The structure, constraints and triggers are written and
their shape is unit-tested against the metadata; no statement has run against
a server and nothing here claims otherwise.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_wp23_auth_audit"
down_revision: Union[str, None] = "0010_wp22_expert_reviews"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SHA256_DIGEST_REGEX = r"^sha256:[0-9a-f]{64}$"

GOVERNED_ROLES = "'ADMIN', 'DEMO_USER', 'EXPERT_REVIEWER'"
USER_STATUSES = "'ACTIVE', 'DISABLED', 'LOCKED'"
AUTH_MECHANISMS = "'NONE', 'STATIC_TOKEN', 'SESSION'"
AUTH_ASSURANCES = "'NONE', 'TEST_STATIC_TOKEN', 'SESSION'"
AUDIT_OUTCOMES = "'SUCCESS', 'REFUSED', 'FAILED'"
REVOCATION_REASONS = (
    "'LOGOUT', 'ROTATED_ON_LOGIN', 'PASSWORD_CHANGED', 'ROLE_CHANGED', "
    "'USER_DISABLED', 'USER_LOCKED', 'ADMIN_REVOKED', 'IDLE_EXPIRED', "
    "'ABSOLUTE_EXPIRED', 'GENERATION_SUPERSEDED'")

OBJECT_TYPES = (
    "'USER', 'SESSION', 'ASSESSMENT', 'RELEASE_BUNDLE', "
    "'CURATION_WORK_ITEM', 'CURATION_REVISION', 'COMPUTABLE_RULE', "
    "'RULESET_VERSION', 'EXPERT_REVIEW', 'AUDIT_STREAM'")

GOVERNED_AUDIT_ACTIONS = (
    "'USER_BOOTSTRAPPED', 'USER_CREATED', 'USER_DISABLED', 'USER_ENABLED', "
    "'USER_LOCKED', 'USER_UNLOCKED', 'USER_ROLE_CHANGED', "
    "'USER_PASSWORD_CHANGED', 'LOGIN_SUCCEEDED', 'LOGIN_FAILED', 'LOGOUT', "
    "'SESSION_CREATED', 'SESSION_REVOKED', 'SESSION_EXPIRED', "
    "'ASSESSMENT_REQUESTED', 'ASSESSMENT_COMPLETED', 'ASSESSMENT_REFUSED', "
    "'RELEASE_REGISTERED', 'RELEASE_ACTIVATED', 'RELEASE_ROLLED_BACK', "
    "'RELEASE_RETIRED', 'RELEASE_REFUSED', 'CURATION_REVISION_CREATED', "
    "'CURATION_REVISION_SUBMITTED', 'CURATION_REVIEWED', "
    "'CURATION_APPROVED', 'CURATION_REJECTED', 'CURATION_ADJUDICATED', "
    "'RULE_VALIDATED', 'RULE_DEPRECATED', 'RULESET_VALIDATED', "
    "'RULESET_FROZEN', 'RULESET_REOPENED', 'RULESET_RETIRED', "
    "'REVIEW_ASSIGNED', 'REVIEW_EXPECTATION_RECORDED', "
    "'REVIEW_RESULT_REVEALED', 'REVIEW_COMPLETED', "
    "'REVIEW_CORRECTION_APPENDED', 'REVIEW_INVALIDATED', "
    "'AUDIT_CHAIN_VERIFIED'")

#: Tables that refuse UPDATE and DELETE outright. The head row is excluded
#: because advancing the chain *is* an update to it - and that update is
#: itself guarded, by the row lock and by the sequence check in the append
#: trigger.
APPEND_ONLY_TABLES = ("governed_audit_events",)

AUDIT_STREAM_ID = "pgx-governed"


def _digest(column: str) -> str:
    return "%s IS NULL OR %s ~ '%s'" % (column, column, SHA256_DIGEST_REGEX)


def upgrade() -> None:
    # -- users -----------------------------------------------------------
    op.create_table(
        "security_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("password_policy_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default=sa.text("'ACTIVE'")),
        sa.Column("auth_generation", sa.Integer(), nullable=False,
                  server_default=sa.text("1")),
        sa.Column("failed_login_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("locked_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("is_bootstrap_admin", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("password_changed_at", sa.TIMESTAMP(timezone=True),
                  nullable=False),
        sa.UniqueConstraint("user_id", name="uq_security_users_user_id"),
        sa.UniqueConstraint("username", name="uq_security_users_username"),
        sa.CheckConstraint("role IN (%s)" % GOVERNED_ROLES,
                           name="ck_security_users_role_enum"),
        sa.CheckConstraint("status IN (%s)" % USER_STATUSES,
                           name="ck_security_users_status_enum"),
        sa.CheckConstraint("username = lower(username)",
                           name="ck_security_users_username_is_canonical"),
        # argon2id specifically. A row holding a bcrypt or PBKDF2 hash would
        # mean some other code path wrote it, which is the thing there must
        # not be - and the database is the layer that survives a refactor.
        sa.CheckConstraint("password_hash LIKE '$argon2id$%'",
                           name="ck_security_users_password_hash_is_argon2id"),
        sa.CheckConstraint("auth_generation >= 1",
                           name="ck_security_users_generation_positive"),
        sa.CheckConstraint("failed_login_count >= 0",
                           name="ck_security_users_failure_count_not_negative"),
        sa.CheckConstraint(
            "status = 'LOCKED' OR locked_until IS NULL",
            name="ck_security_users_only_a_locked_account_has_a_lock_expiry"),
    )
    op.create_index("ix_security_users_status", "security_users", ["status"])

    # -- sessions --------------------------------------------------------
    op.create_table(
        "security_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("token_digest", sa.String(80), nullable=False),
        sa.Column("csrf_secret", sa.String(128), nullable=False),
        sa.Column("auth_generation", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True),
                  nullable=False),
        sa.Column("idle_expires_at", sa.TIMESTAMP(timezone=True),
                  nullable=False),
        sa.Column("absolute_expires_at", sa.TIMESTAMP(timezone=True),
                  nullable=False),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(32), nullable=True),
        # RESTRICT, never CASCADE. Deleting a user out from under their
        # sessions would remove the evidence that the sessions existed.
        sa.ForeignKeyConstraint(
            ["user_id"], ["security_users.user_id"],
            name="fk_security_sessions_user_id_security_users",
            ondelete="RESTRICT"),
        sa.UniqueConstraint("session_id",
                            name="uq_security_sessions_session_id"),
        sa.UniqueConstraint("token_digest",
                            name="uq_security_sessions_token_digest"),
        sa.CheckConstraint("role IN (%s)" % GOVERNED_ROLES,
                           name="ck_security_sessions_role_enum"),
        sa.CheckConstraint("token_digest ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_security_sessions_token_digest_format"),
        sa.CheckConstraint(
            "absolute_expires_at >= idle_expires_at",
            name="ck_security_sessions_absolute_bound_not_before_idle"),
        sa.CheckConstraint("auth_generation >= 1",
                           name="ck_security_sessions_generation_positive"),
        sa.CheckConstraint(
            "(revoked_at IS NULL) = (revocation_reason IS NULL)",
            name="ck_security_sessions_revocation_names_its_reason"),
        sa.CheckConstraint(
            "revocation_reason IS NULL OR revocation_reason IN (%s)"
            % REVOCATION_REASONS,
            name="ck_security_sessions_revocation_reason_enum"),
    )
    op.create_index("ix_security_sessions_user_id", "security_sessions",
                    ["user_id"])
    op.create_index("ix_security_sessions_absolute_expires_at",
                    "security_sessions", ["absolute_expires_at"])

    # -- rate-limit counters ---------------------------------------------
    op.create_table(
        "security_rate_limit_counters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("policy_id", sa.String(64), nullable=False),
        sa.Column("key_digest", sa.String(80), nullable=False),
        sa.Column("window_start", sa.TIMESTAMP(timezone=True),
                  nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.UniqueConstraint("policy_id", "key_digest", "window_start",
                            name="uq_security_rate_limit_counters_bucket"),
        sa.CheckConstraint(
            "key_digest ~ '%s'" % SHA256_DIGEST_REGEX,
            name="ck_security_rate_limit_counters_key_digest_format"),
        sa.CheckConstraint(
            "hit_count >= 0",
            name="ck_security_rate_limit_counters_hit_count_not_negative"),
    )
    op.create_index("ix_security_rate_limit_counters_window_start",
                    "security_rate_limit_counters", ["window_start"])

    # -- the canonical audit stream --------------------------------------
    op.create_table(
        "governed_audit_stream_head",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("stream_id", sa.String(64), nullable=False),
        sa.Column("head_sequence", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("head_event_hash", sa.String(80), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.UniqueConstraint("stream_id",
                            name="uq_governed_audit_stream_head_stream_id"),
        sa.CheckConstraint(
            "head_sequence >= 0",
            name="ck_governed_audit_stream_head_head_sequence_positive"),
        sa.CheckConstraint(
            "(head_sequence = 0) = (head_event_hash IS NULL)",
            name="ck_governed_audit_stream_head_empty_stream_has_no_hash"),
    )
    op.execute(
        "INSERT INTO governed_audit_stream_head "
        "(id, stream_id, head_sequence, head_event_hash, updated_at) "
        "VALUES (gen_random_uuid(), '%s', 0, NULL, now());"
        % AUDIT_STREAM_ID)

    op.create_table(
        "governed_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("stream_id", sa.String(64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("result_code", sa.String(64), nullable=False),
        sa.Column("object_type", sa.String(32), nullable=False),
        sa.Column("object_id", sa.String(128), nullable=False),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=True),
        sa.Column("actor_role", sa.String(32), nullable=True),
        sa.Column("auth_mechanism", sa.String(24), nullable=False,
                  server_default=sa.text("'NONE'")),
        sa.Column("auth_assurance", sa.String(24), nullable=False,
                  server_default=sa.text("'NONE'")),
        sa.Column("session_reference", sa.String(128), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("input_hash", sa.String(80), nullable=True),
        sa.Column("output_hash", sa.String(80), nullable=True),
        sa.Column("software_id", sa.String(128), nullable=True),
        sa.Column("software_hash", sa.String(80), nullable=True),
        sa.Column("dataset_id", sa.String(128), nullable=True),
        sa.Column("dataset_hash", sa.String(80), nullable=True),
        sa.Column("ruleset_id", sa.String(128), nullable=True),
        sa.Column("ruleset_hash", sa.String(80), nullable=True),
        sa.Column("release_id", sa.String(128), nullable=True),
        sa.Column("release_manifest_hash", sa.String(80), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("previous_hash", sa.String(80), nullable=True),
        sa.Column("event_hash", sa.String(80), nullable=False),
        sa.UniqueConstraint("event_id",
                            name="uq_governed_audit_events_event_id"),
        sa.UniqueConstraint("stream_id", "sequence",
                            name="uq_governed_audit_events_stream_sequence"),
        sa.UniqueConstraint("event_hash",
                            name="uq_governed_audit_events_event_hash"),
        sa.CheckConstraint("action IN (%s)" % GOVERNED_AUDIT_ACTIONS,
                           name="ck_governed_audit_events_action_enum"),
        sa.CheckConstraint("outcome IN (%s)" % AUDIT_OUTCOMES,
                           name="ck_governed_audit_events_outcome_enum"),
        sa.CheckConstraint("object_type IN (%s)" % OBJECT_TYPES,
                           name="ck_governed_audit_events_object_type_enum"),
        sa.CheckConstraint("auth_mechanism IN (%s)" % AUTH_MECHANISMS,
                           name="ck_governed_audit_events_mechanism_enum"),
        sa.CheckConstraint("auth_assurance IN (%s)" % AUTH_ASSURANCES,
                           name="ck_governed_audit_events_assurance_enum"),
        sa.CheckConstraint(
            "actor_role IS NULL OR actor_role IN (%s)" % GOVERNED_ROLES,
            name="ck_governed_audit_events_actor_role_enum"),
        # A fixture may never claim to be a person. Enforced in the database
        # as well as in the model, because the model can be bypassed by a
        # direct insert and the database cannot.
        sa.CheckConstraint(
            "auth_assurance <> 'SESSION' OR auth_mechanism = 'SESSION'",
            name="ck_governed_audit_events_only_a_session_has_assurance"),
        sa.CheckConstraint(
            "auth_mechanism <> 'SESSION' OR session_reference IS NOT NULL",
            name="ck_governed_audit_events_session_event_names_its_session"),
        sa.CheckConstraint("sequence >= 1",
                           name="ck_governed_audit_events_sequence_positive"),
        sa.CheckConstraint(
            "(sequence = 1) = (previous_hash IS NULL)",
            name="ck_governed_audit_events_first_event_starts_the_chain"),
        sa.CheckConstraint("event_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_governed_audit_events_event_hash_format"),
        sa.CheckConstraint(_digest("previous_hash"),
                           name="ck_governed_audit_events_previous_format"),
        sa.CheckConstraint(_digest("input_hash"),
                           name="ck_governed_audit_events_input_format"),
        sa.CheckConstraint(_digest("output_hash"),
                           name="ck_governed_audit_events_output_format"),
    )
    op.create_index("ix_governed_audit_events_occurred_at",
                    "governed_audit_events", ["occurred_at"])
    op.create_index("ix_governed_audit_events_object",
                    "governed_audit_events", ["object_type", "object_id"])
    op.create_index("ix_governed_audit_events_actor_id",
                    "governed_audit_events", ["actor_id"])

    # -- append-only enforcement -----------------------------------------
    #
    # The application repository has no update and no delete method. This is
    # the half that survives somebody with a psql prompt.
    op.execute("""
        CREATE OR REPLACE FUNCTION pgx_governed_audit_append_only()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'the governed audit trail is append-only: % on % is refused. '
                'An audit record that can be edited answers no question.',
                TG_OP, TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
    """)
    for table in APPEND_ONLY_TABLES:
        op.execute("""
            CREATE TRIGGER trg_%s_append_only
            BEFORE UPDATE OR DELETE ON %s
            FOR EACH ROW EXECUTE FUNCTION pgx_governed_audit_append_only();
        """ % (table, table))

    # -- chain-head enforcement ------------------------------------------
    #
    # Belt and braces over the row lock. A caller that read the head without
    # locking it, or skipped the head entirely, is refused by the server: the
    # inserted sequence must be exactly head + 1 and the predecessor hash must
    # be exactly the recorded head hash. The trigger then advances the head in
    # the same statement, so the two can never disagree.
    op.execute("""
        CREATE OR REPLACE FUNCTION pgx_governed_audit_chain_guard()
        RETURNS trigger AS $$
        DECLARE
            current_sequence integer;
            current_hash text;
        BEGIN
            SELECT head_sequence, head_event_hash
              INTO current_sequence, current_hash
              FROM governed_audit_stream_head
             WHERE stream_id = NEW.stream_id
               FOR UPDATE;

            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'no audit stream head exists for stream %; the chain '
                    'cannot be extended without one', NEW.stream_id
                    USING ERRCODE = 'restrict_violation';
            END IF;

            IF NEW.sequence <> current_sequence + 1 THEN
                RAISE EXCEPTION
                    'audit sequence % does not follow the recorded head %; '
                    'the append is refused rather than forking the chain',
                    NEW.sequence, current_sequence
                    USING ERRCODE = 'restrict_violation';
            END IF;

            IF NEW.previous_hash IS DISTINCT FROM current_hash THEN
                RAISE EXCEPTION
                    'the predecessor hash at sequence % is not the recorded '
                    'head; the append is refused', NEW.sequence
                    USING ERRCODE = 'restrict_violation';
            END IF;

            UPDATE governed_audit_stream_head
               SET head_sequence = NEW.sequence,
                   head_event_hash = NEW.event_hash,
                   updated_at = now()
             WHERE stream_id = NEW.stream_id;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER trg_governed_audit_events_chain_guard
        BEFORE INSERT ON governed_audit_events
        FOR EACH ROW EXECUTE FUNCTION pgx_governed_audit_chain_guard();
    """)

    # -- WP-22's constraint changes, in the open --------------------------
    #
    # 0010 pinned actor_authenticated = false with a comment saying WP-23
    # would change it in a migration somebody reviews. This is that migration.
    # A session-authenticated review action may now record true; a static
    # development token still records false, enforced in the service because
    # the database cannot see which mechanism produced a row.
    op.drop_constraint(
        "ck_expert_review_audit_events_no_p0_principal_is_authenticated",
        "expert_review_audit_events", type_="check")
    op.create_check_constraint(
        "ck_expert_review_audit_events_authentication_is_boolean",
        "expert_review_audit_events",
        sa.text("actor_authenticated IN (true, false)"))


def downgrade() -> None:
    """Refuse while any account, session or audit event exists.

    Dropping these tables would destroy the account history and the integrity
    chain together. That is the single most destructive statement this
    repository could contain, and a downgrade that did it silently would be
    worse than one that refuses. Removing real security history requires
    exporting it and deleting the rows explicitly - which the append-only
    trigger also refuses, so it needs a deliberate, reviewed migration of its
    own.
    """
    connection = op.get_bind()
    for table, noun in (("governed_audit_events", "governed audit event"),
                        ("security_sessions", "session"),
                        ("security_users", "user account")):
        stored = connection.execute(
            sa.text("SELECT count(*) FROM %s" % table)).scalar()
        if stored:
            raise RuntimeError(
                "refusing to downgrade: %d %s row(s) exist. Security history "
                "and the audit chain are evidence, and this migration will "
                "not destroy them silently." % (stored, noun))

    op.drop_constraint(
        "ck_expert_review_audit_events_authentication_is_boolean",
        "expert_review_audit_events", type_="check")
    op.create_check_constraint(
        "ck_expert_review_audit_events_no_p0_principal_is_authenticated",
        "expert_review_audit_events", sa.text("actor_authenticated = false"))

    op.execute("DROP TRIGGER IF EXISTS "
               "trg_governed_audit_events_chain_guard "
               "ON governed_audit_events;")
    op.execute("DROP FUNCTION IF EXISTS pgx_governed_audit_chain_guard();")
    for table in APPEND_ONLY_TABLES:
        op.execute("DROP TRIGGER IF EXISTS trg_%s_append_only ON %s;"
                   % (table, table))
    op.execute("DROP FUNCTION IF EXISTS pgx_governed_audit_append_only();")

    op.drop_index("ix_governed_audit_events_actor_id",
                  table_name="governed_audit_events")
    op.drop_index("ix_governed_audit_events_object",
                  table_name="governed_audit_events")
    op.drop_index("ix_governed_audit_events_occurred_at",
                  table_name="governed_audit_events")
    op.drop_table("governed_audit_events")
    op.drop_table("governed_audit_stream_head")
    op.drop_index("ix_security_rate_limit_counters_window_start",
                  table_name="security_rate_limit_counters")
    op.drop_table("security_rate_limit_counters")
    op.drop_index("ix_security_sessions_absolute_expires_at",
                  table_name="security_sessions")
    op.drop_index("ix_security_sessions_user_id",
                  table_name="security_sessions")
    op.drop_table("security_sessions")
    op.drop_index("ix_security_users_status", table_name="security_users")
    op.drop_table("security_users")
