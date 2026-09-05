# -*- coding: utf-8 -*-
"""WP-05 scientific source policy, review, conflict and gate-verdict schema.

Revision ID: 0003_wp05_source_policy
Revises: 0002_wp03_release_registry
Create Date: 2026-08-30

Hand-written and reviewed, not blind autogenerate output. ``0001`` and ``0002``
are not touched: this revision only adds. Forward-only in the sense that
matters - nothing here rewrites an earlier migration to make the final schema
read more tidily.

Scope - five tables:

    source_policies, source_policy_evidence, source_policy_reviews,
    source_conflicts, dataset_publication_evaluations

plus one trigger function guarding two of them.

**Why a database schema when the policy lives in a JSON file.** The file is
where a policy is *decided*: it is reviewed, committed, and a change to a
licensing conclusion appears as a diff with an author against it. These tables
are the *operational record* - which policy content hash was in force when a
dataset was published, which review was cited, which conflicts were open. That
has to sit next to the release it justifies, because a release whose
justification exists only in somebody's working tree cannot be audited later.

Three things here are load-bearing and easy to lose in a refactor:

**A row cannot approve itself.** ``ck_source_policies_approving_needs_review``
requires ``review_id`` to be present whenever ``status`` is an approving one,
and ``source_policy_reviews`` in turn requires a reviewer name, a decision
instant and at least one cited evidence URL. So the path from a row to "this
source is approved" runs through a named human at the database level, not only
in Python.

**Reviews and gate verdicts are append-only.** ``trg_*_append_only`` raises on
``UPDATE`` and ``DELETE``. A review decision that could be edited afterwards is
not evidence of anything, and a publication verdict that could be rewritten
could not answer "what did the policy say when we shipped this?". The
application never offers either operation, but that is a promise; only the
trigger survives someone with a ``psql`` prompt.

**Unsettled conflicts cannot carry a resolution, and settled ones must.**
``ck_source_conflicts_settled_has_resolution`` makes "RESOLVED" and "a named
human decided something" the same fact, so a status field cannot quietly settle
a disagreement nobody looked at.

``downgrade()`` removes exactly these objects, children before parents, and
drops the triggers *and* their function - a downgrade that leaves a function
behind makes the next upgrade fail on ``CREATE FUNCTION``. Nothing from ``0001``
or ``0002`` is dropped, so ``0002 -> 0003 -> 0002 -> 0003`` is clean.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_wp05_source_policy"
down_revision: Union[str, None] = "0002_wp03_release_registry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Canonical digest spelling produced by pgx.domain.hashing.sha256_digest.
SHA256_DIGEST_REGEX = r"^sha256:[0-9a-f]{64}$"

# Vocabularies. Spelled out rather than imported so the migration keeps working
# if the Python vocabulary is later renamed: a migration must describe the
# schema as it was created, not as the current code would create it.
POLICY_STATUSES = ("'UNREGISTERED', 'PENDING_REVIEW', 'UNDER_REVIEW', "
                   "'APPROVED', 'APPROVED_WITH_RESTRICTIONS', 'REJECTED', "
                   "'SUSPENDED'")
APPROVING_STATUSES = "'APPROVED', 'APPROVED_WITH_RESTRICTIONS'"
ACQUISITION_MODES = ("'NOT_DETERMINED', 'MANUAL_DOWNLOAD', 'OFFICIAL_API', "
                     "'LICENSED_BULK_EXPORT', 'PUBLICATION_TRANSCRIPTION', "
                     "'INTERNAL_DERIVATION'")
SOURCE_ROLES = ("'PRIMARY_GUIDELINE', 'SUPPORTING_ANNOTATION', "
                "'REFERENCE_ONLY', 'INTERNAL_SYSTEM'")
EVIDENCE_TYPES = ("'NOT_OBTAINED', 'OFFICIAL_TERMS_PAGE', "
                  "'OFFICIAL_LICENSE_FILE', 'OFFICIAL_API_DOCUMENTATION', "
                  "'OFFICIAL_PUBLICATION', 'DIRECT_WRITTEN_PERMISSION'")
VERIFICATION_STATUSES = "'NOT_ATTEMPTED', 'BLOCKED', 'VERIFIED', 'STALE'"
REVIEW_DECISIONS = ("'APPROVE', 'APPROVE_WITH_RESTRICTIONS', 'REJECT', "
                    "'REQUEST_MORE_INFORMATION'")
APPROVING_DECISIONS = "'APPROVE', 'APPROVE_WITH_RESTRICTIONS'"
CONFLICT_STATUSES = "'OPEN', 'UNDER_REVIEW', 'RESOLVED', 'ACCEPTED_VARIANCE'"
SETTLED_CONFLICT_STATUSES = "'RESOLVED', 'ACCEPTED_VARIANCE'"
CONFLICT_MATERIALITIES = "'MATERIAL', 'NON_MATERIAL', 'UNDETERMINED'"
PUBLICATION_DECISIONS = "'ELIGIBLE', 'BLOCKED'"

_APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION pgx_wp05_append_only()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'table % is append-only: % is not permitted. A review decision or a '
        'publication verdict that can be rewritten is not evidence of anything.',
        TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

_REVIEWS_APPEND_ONLY_TRIGGER = """
CREATE TRIGGER trg_source_policy_reviews_append_only
BEFORE UPDATE OR DELETE ON source_policy_reviews
FOR EACH ROW EXECUTE FUNCTION pgx_wp05_append_only();
"""

_EVALUATIONS_APPEND_ONLY_TRIGGER = """
CREATE TRIGGER trg_publication_evaluations_append_only
BEFORE UPDATE OR DELETE ON dataset_publication_evaluations
FOR EACH ROW EXECUTE FUNCTION pgx_wp05_append_only();
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
    """Create the WP-05 source-governance schema."""

    # -- source_policy_reviews -------------------------------------------
    # Created first: source_policies references it. A review is the record of a
    # human decision, so every column that a forged approval would have to
    # invent is NOT NULL, and the approving decisions additionally require
    # cited evidence.
    op.create_table(
        "source_policy_reviews",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("source_key", sa.String(length=128), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("reviewer_name", sa.String(length=256), nullable=False),
        sa.Column("reviewer_role", sa.String(length=256), nullable=False),
        sa.Column("decided_at", _timestamptz(), nullable=False),
        sa.Column("evidence_urls", _jsonb(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("restrictions", _jsonb(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("expires_at", _timestamptz(), nullable=True),
        sa.Column("recorded_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_source_policy_reviews"),
        sa.CheckConstraint("decision IN (%s)" % REVIEW_DECISIONS,
                           name="ck_source_policy_reviews_decision_enum"),
        sa.CheckConstraint("length(trim(source_key)) > 0",
                           name="ck_source_policy_reviews_source_key_not_blank"),
        sa.CheckConstraint("length(trim(reviewer_name)) > 0",
                           name="ck_source_policy_reviews_reviewer_not_blank"),
        sa.CheckConstraint("length(trim(reviewer_role)) > 0",
                           name="ck_source_policy_reviews_role_not_blank"),
        sa.CheckConstraint("jsonb_typeof(evidence_urls) = 'array'",
                           name="ck_source_policy_reviews_evidence_is_array"),
        sa.CheckConstraint("jsonb_typeof(restrictions) = 'array'",
                           name="ck_source_policy_reviews_restrictions_array"),
        # An approval with no cited evidence is an assertion, not a review.
        sa.CheckConstraint(
            "decision NOT IN (%s) OR jsonb_array_length(evidence_urls) > 0"
            % APPROVING_DECISIONS,
            name="ck_source_policy_reviews_approval_needs_evidence"),
        # A restricted approval that names no restriction restricts nothing.
        sa.CheckConstraint(
            "decision <> 'APPROVE_WITH_RESTRICTIONS'"
            " OR jsonb_array_length(restrictions) > 0",
            name="ck_source_policy_reviews_restricted_names_terms"),
        # A review that expired before it was decided was never in force.
        sa.CheckConstraint("expires_at IS NULL OR expires_at > decided_at",
                           name="ck_source_policy_reviews_expiry_after_decision"),
    )
    op.create_index("ix_source_policy_reviews_source_key",
                    "source_policy_reviews", ["source_key"], unique=False)
    op.create_index("ix_source_policy_reviews_decided_at",
                    "source_policy_reviews", ["decided_at"], unique=False)

    # -- source_policies --------------------------------------------------
    # source_registry_id is nullable on purpose: a policy may legitimately exist
    # for a source the operational registry has no row for yet - registering a
    # drug-label authority before any evidence has been ingested from it is the
    # normal order of events, not an anomaly.
    op.create_table(
        "source_policies",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("source_key", sa.String(length=128), nullable=False),
        sa.Column("source_registry_id", _uuid(), nullable=True),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False,
                  server_default=sa.text("'PENDING_REVIEW'")),
        sa.Column("acquisition_mode", sa.String(length=32), nullable=False,
                  server_default=sa.text("'NOT_DETERMINED'")),
        sa.Column("provider", sa.String(length=256), nullable=True),
        sa.Column("jurisdiction", sa.String(length=128), nullable=True),
        sa.Column("version_policy", sa.Text(), nullable=True),
        sa.Column("citation_policy", sa.Text(), nullable=True),
        sa.Column("license_identifier", sa.String(length=256), nullable=True),
        sa.Column("reuse", _jsonb(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("permitted_claim_categories", _jsonb(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("legacy_aliases", _jsonb(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("blocking_reasons", _jsonb(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("interpretation_summary", sa.Text(), nullable=True),
        sa.Column("interpreted_by", sa.String(length=256), nullable=True),
        sa.Column("interpreted_at", _timestamptz(), nullable=True),
        sa.Column("review_id", _uuid(), nullable=True),
        sa.Column("registry_content_hash", sa.String(length=80), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("recorded_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("recorded_by", sa.String(length=256), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_registry_id"], ["source_registry.id"],
            name="fk_source_policies_registry_id_source_registry",
            ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["review_id"], ["source_policy_reviews.id"],
            name="fk_source_policies_review_id_source_policy_reviews",
            ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_source_policies"),
        sa.UniqueConstraint("source_key", name="uq_source_policies_source_key"),
        sa.CheckConstraint("status IN (%s)" % POLICY_STATUSES,
                           name="ck_source_policies_status_enum"),
        sa.CheckConstraint("acquisition_mode IN (%s)" % ACQUISITION_MODES,
                           name="ck_source_policies_acquisition_mode_enum"),
        sa.CheckConstraint("role IN (%s)" % SOURCE_ROLES,
                           name="ck_source_policies_role_enum"),
        sa.CheckConstraint("length(trim(source_key)) > 0",
                           name="ck_source_policies_source_key_not_blank"),
        sa.CheckConstraint("jsonb_typeof(reuse) = 'object'",
                           name="ck_source_policies_reuse_is_object"),
        sa.CheckConstraint(
            "jsonb_typeof(permitted_claim_categories) = 'array'",
            name="ck_source_policies_claim_categories_array"),
        sa.CheckConstraint("jsonb_typeof(legacy_aliases) = 'array'",
                           name="ck_source_policies_legacy_aliases_array"),
        sa.CheckConstraint("jsonb_typeof(blocking_reasons) = 'array'",
                           name="ck_source_policies_blocking_reasons_array"),
        sa.CheckConstraint("registry_content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_source_policies_registry_hash_format"),
        # The invariant this whole table exists for: a row cannot approve
        # itself. An approving status must point at a review, and a review
        # cannot exist without a named human, an instant and cited evidence.
        sa.CheckConstraint(
            "status NOT IN (%s) OR review_id IS NOT NULL" % APPROVING_STATUSES,
            name="ck_source_policies_approving_needs_review"),
        # What a source may be cited for is decided at review. An unapproved
        # row claiming categories would be an approval by another spelling.
        sa.CheckConstraint(
            "status IN (%s)"
            " OR jsonb_array_length(permitted_claim_categories) = 0"
            % APPROVING_STATUSES,
            name="ck_source_policies_categories_need_approval"),
        # Technical bookkeeping can never be scientific evidence. The same rule
        # already guards source_registry in 0001.
        sa.CheckConstraint(
            "role <> 'INTERNAL_SYSTEM'"
            " OR permitted_claim_categories = '[]'::jsonb"
            " OR permitted_claim_categories = '[\"INTERNAL_BOOKKEEPING\"]'::jsonb",
            name="ck_source_policies_internal_system_claims"),
        # An interpretation is attributed or it is not recorded: an unsigned
        # conclusion cannot be re-examined with its author.
        sa.CheckConstraint(
            "interpretation_summary IS NULL"
            " OR (interpreted_by IS NOT NULL AND interpreted_at IS NOT NULL)",
            name="ck_source_policies_interpretation_attributed"),
    )
    op.create_index("ix_source_policies_status", "source_policies", ["status"],
                    unique=False)

    # -- source_policy_evidence -------------------------------------------
    # One row per artefact the policy points at. The artefact's text is
    # deliberately not stored: a second copy in this database would go stale
    # without anybody noticing which one was right.
    op.create_table(
        "source_policy_evidence",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("source_policy_id", _uuid(), nullable=False),
        sa.Column("evidence_type", sa.String(length=40), nullable=False),
        sa.Column("official_url", sa.Text(), nullable=True),
        sa.Column("retrieved_at", _timestamptz(), nullable=True),
        sa.Column("content_hash", sa.String(length=80), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("verification", sa.String(length=24), nullable=False,
                  server_default=sa.text("'NOT_ATTEMPTED'")),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("recorded_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["source_policy_id"], ["source_policies.id"],
            name="fk_source_policy_evidence_policy_id_source_policies",
            ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_source_policy_evidence"),
        sa.CheckConstraint("evidence_type IN (%s)" % EVIDENCE_TYPES,
                           name="ck_source_policy_evidence_type_enum"),
        sa.CheckConstraint("verification IN (%s)" % VERIFICATION_STATUSES,
                           name="ck_source_policy_evidence_verification_enum"),
        sa.CheckConstraint(
            "content_hash IS NULL OR content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
            name="ck_source_policy_evidence_hash_format"),
        sa.CheckConstraint(
            "official_url IS NULL OR official_url LIKE 'https://%'",
            name="ck_source_policy_evidence_url_is_https"),
        # Claiming to have read a document means naming it and saying when.
        sa.CheckConstraint(
            "verification <> 'VERIFIED'"
            " OR (official_url IS NOT NULL AND retrieved_at IS NOT NULL)",
            name="ck_source_policy_evidence_verified_is_specific"),
        # An unexplained block is indistinguishable from an untried retrieval.
        sa.CheckConstraint(
            "verification <> 'BLOCKED'"
            " OR (blocked_reason IS NOT NULL AND length(trim(blocked_reason)) > 0)",
            name="ck_source_policy_evidence_block_has_reason"),
        # Nothing unobtained was ever verified.
        sa.CheckConstraint(
            "evidence_type <> 'NOT_OBTAINED' OR verification <> 'VERIFIED'",
            name="ck_source_policy_evidence_unobtained_not_verified"),
    )
    op.create_index("ix_source_policy_evidence_policy_id",
                    "source_policy_evidence", ["source_policy_id"], unique=False)

    # -- source_conflicts --------------------------------------------------
    op.create_table(
        "source_conflicts",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("conflict_key", sa.String(length=512), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column("source_keys", _jsonb(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("materiality", sa.String(length=24), nullable=False,
                  server_default=sa.text("'UNDETERMINED'")),
        sa.Column("status", sa.String(length=24), nullable=False,
                  server_default=sa.text("'OPEN'")),
        sa.Column("detected_at", _timestamptz(), nullable=True),
        sa.Column("resolution_summary", sa.Text(), nullable=True),
        sa.Column("resolution_rationale", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.String(length=256), nullable=True),
        sa.Column("resolved_at", _timestamptz(), nullable=True),
        sa.Column("preferred_source_key", sa.String(length=128), nullable=True),
        sa.Column("created_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_source_conflicts"),
        sa.UniqueConstraint("conflict_key", name="uq_source_conflicts_key"),
        sa.CheckConstraint("status IN (%s)" % CONFLICT_STATUSES,
                           name="ck_source_conflicts_status_enum"),
        sa.CheckConstraint("materiality IN (%s)" % CONFLICT_MATERIALITIES,
                           name="ck_source_conflicts_materiality_enum"),
        sa.CheckConstraint("jsonb_typeof(source_keys) = 'array'",
                           name="ck_source_conflicts_source_keys_array"),
        # A conflict needs at least two sources to disagree.
        sa.CheckConstraint("jsonb_array_length(source_keys) >= 2",
                           name="ck_source_conflicts_needs_two_sources"),
        # Settled means a named human decided, with a reason. A status field
        # alone cannot settle a disagreement nobody looked at.
        sa.CheckConstraint(
            "status NOT IN (%s) OR ("
            " resolution_summary IS NOT NULL"
            " AND resolution_rationale IS NOT NULL"
            " AND resolved_by IS NOT NULL AND length(trim(resolved_by)) > 0"
            " AND resolved_at IS NOT NULL)" % SETTLED_CONFLICT_STATUSES,
            name="ck_source_conflicts_settled_has_resolution"),
        # And the converse: an unsettled conflict carrying a resolution would
        # be a decision hidden behind the wrong status.
        sa.CheckConstraint(
            "status IN (%s) OR ("
            " resolution_summary IS NULL AND resolution_rationale IS NULL"
            " AND resolved_by IS NULL AND resolved_at IS NULL)"
            % SETTLED_CONFLICT_STATUSES,
            name="ck_source_conflicts_unsettled_has_no_resolution"),
    )
    op.create_index("ix_source_conflicts_status", "source_conflicts", ["status"],
                    unique=False)

    # -- dataset_publication_evaluations -----------------------------------
    # The gate's verdicts. Stored so a release can cite the evaluation it
    # passed, and so a BLOCKED verdict is as durable as an ELIGIBLE one.
    op.create_table(
        "dataset_publication_evaluations",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("dataset_key", sa.String(length=128), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("evaluated_at", _timestamptz(), nullable=False),
        sa.Column("registry_content_hash", sa.String(length=80), nullable=False),
        sa.Column("evaluated_source_keys", _jsonb(), nullable=False),
        sa.Column("issues", _jsonb(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("evaluation_digest", sa.String(length=80), nullable=False),
        sa.Column("recorded_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("recorded_by", sa.String(length=256), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_publication_evaluations"),
        sa.UniqueConstraint("evaluation_digest",
                            name="uq_publication_evaluations_digest"),
        sa.CheckConstraint("decision IN (%s)" % PUBLICATION_DECISIONS,
                           name="ck_publication_evaluations_decision_enum"),
        sa.CheckConstraint("length(trim(dataset_key)) > 0",
                           name="ck_publication_evaluations_dataset_not_blank"),
        sa.CheckConstraint("registry_content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_publication_evaluations_registry_hash"),
        sa.CheckConstraint("evaluation_digest ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_publication_evaluations_digest_format"),
        sa.CheckConstraint("jsonb_typeof(evaluated_source_keys) = 'array'",
                           name="ck_publication_evaluations_sources_array"),
        sa.CheckConstraint("jsonb_typeof(issues) = 'array'",
                           name="ck_publication_evaluations_issues_array"),
        # An ELIGIBLE verdict with blocking issues recorded against it would be
        # the gate contradicting its own evidence.
        sa.CheckConstraint(
            "decision <> 'ELIGIBLE'"
            " OR NOT (issues @> '[{\"severity\": \"BLOCKER\"}]'::jsonb)",
            name="ck_publication_evaluations_eligible_has_no_blocker"),
    )
    op.create_index("ix_publication_evaluations_dataset_key",
                    "dataset_publication_evaluations", ["dataset_key"],
                    unique=False)
    op.create_index("ix_publication_evaluations_evaluated_at",
                    "dataset_publication_evaluations", ["evaluated_at"],
                    unique=False)

    # -- append-only guards -------------------------------------------------
    op.execute(_APPEND_ONLY_FUNCTION)
    op.execute(_REVIEWS_APPEND_ONLY_TRIGGER)
    op.execute(_EVALUATIONS_APPEND_ONLY_TRIGGER)


def downgrade() -> None:
    """Drop exactly the WP-05 objects, children before parents.

    The triggers and their shared function go first: a downgrade that left the
    function behind would make the next upgrade fail on ``CREATE FUNCTION``.
    Nothing belonging to ``0001`` or ``0002`` is touched.
    """
    op.execute("DROP TRIGGER IF EXISTS trg_publication_evaluations_append_only "
               "ON dataset_publication_evaluations")
    op.execute("DROP TRIGGER IF EXISTS trg_source_policy_reviews_append_only "
               "ON source_policy_reviews")
    op.execute("DROP FUNCTION IF EXISTS pgx_wp05_append_only()")

    op.drop_index("ix_publication_evaluations_evaluated_at",
                  table_name="dataset_publication_evaluations")
    op.drop_index("ix_publication_evaluations_dataset_key",
                  table_name="dataset_publication_evaluations")
    op.drop_table("dataset_publication_evaluations")

    op.drop_index("ix_source_conflicts_status", table_name="source_conflicts")
    op.drop_table("source_conflicts")

    op.drop_index("ix_source_policy_evidence_policy_id",
                  table_name="source_policy_evidence")
    op.drop_table("source_policy_evidence")

    # source_policies references source_policy_reviews, so it goes first.
    op.drop_index("ix_source_policies_status", table_name="source_policies")
    op.drop_table("source_policies")

    op.drop_index("ix_source_policy_reviews_decided_at",
                  table_name="source_policy_reviews")
    op.drop_index("ix_source_policy_reviews_source_key",
                  table_name="source_policy_reviews")
    op.drop_table("source_policy_reviews")
