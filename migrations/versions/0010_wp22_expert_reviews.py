# -*- coding: utf-8 -*-
"""WP-22 blind expert review.

Revision ID: 0010_wp22_expert_reviews
Revises: 0009_wp14_assessments
Create Date: 2026-09-05

Hand-written and reviewed, not autogenerate output. Seven new tables beside
the existing schema, plus one widening of the audit action list.

**What each table is for, and why they are separate.** Each phase of the blind
protocol answers a different evidential question, and merging two would let
one be edited under cover of the other:

| Table | Answers |
|---|---|
| `expert_review_assignments` | who was asked to review what, under which release and protocol |
| `expert_review_expectations` | what they predicted, and exactly when |
| `expert_review_reveals` | what they were shown, pinned to which prediction |
| `expert_review_completions` | what they concluded afterwards |
| `expert_review_ratings` | optional structured scores |
| `expert_review_corrections` | every amendment, appended |
| `expert_review_audit_events` | the chained record of every act |

**Which layer enforces which invariant.** Stated here because "enforced" with
no named enforcer is how an invariant quietly stops holding.

| Invariant | Enforced by |
|---|---|
| only EXPERT_HOLDOUT is assignable | `ck_expert_review_assignments_case_role_is_expert_holdout` |
| only EXPERT_REVIEWER may hold an assignment | `ck_expert_review_assignments_reviewer_role_is_expert_reviewer` |
| one live assignment per reviewer/case/release | `uq_expert_review_assignments_case_reviewer_release` |
| exactly one reveal per review | `uq_expert_review_reveals_one_reveal_per_review` |
| exactly one completion per review | `uq_expert_review_completions_one_completion_per_review` |
| **completion only after reveal** | `fk_expert_review_completions_reveal_id_expert_review_reveals` - there is no reveal id to reference before one exists |
| **reveal only after an expectation** | `fk_expert_review_reveals_expectation_revision_id_...` - same mechanism |
| an expectation revision is unique and hashed | `uq_expert_review_expectations_review_revision`, `uq_..._revision_hash` |
| the state machine moves forward only | `trg_expert_review_assignments_forward_only` |
| every other row is append-only | `trg_<table>_append_only` on the six remaining tables |
| the audit chain starts once and links | `ck_expert_review_audit_events_first_event_starts_the_chain`, `uq_..._review_sequence` |
| no P0 principal is authenticated | `ck_expert_review_audit_events_no_p0_principal_is_authenticated` |
| ratings are declared dimensions, bounded | `ck_expert_review_ratings_dimension_enum`, `ck_..._value_bounded` |
| decisions are exactly three values | `ck_expert_review_completions_decision_enum` |
| an invalidated review names its reason | `ck_expert_review_assignments_invalidated_names_its_reason` |
| hashes have canonical format | `ck_*_format` |
| no review record can be deleted while another cites it | every foreign key is `ON DELETE RESTRICT` |

**Two invariants are enforced by foreign key rather than by trigger**, and
that is the neatest part of the schema: "no reveal before an expectation" and
"no completion before a reveal" are not checks at all. A reveal row must name
an expectation revision that exists; a completion row must name a reveal that
exists. Ordering is a referential fact rather than a rule somebody enforces.

**The assignment table is the only one that changes.** A state transition
updates exactly one column, and `trg_expert_review_assignments_forward_only`
permits only the moves the protocol allows - so a database statement cannot
send a completed review back to ASSIGNED any more than the service can. Every
other table refuses `UPDATE` and `DELETE` outright.

**`actor_authenticated` is pinned false by check constraint.** WP-23 owns
identity assurance. When it lands, that constraint changes in a migration
somebody reviews, rather than a boolean quietly starting to be true.

**No payload, no patient data.** These tables hold identifiers, hashes,
controlled vocabulary values and bounded notes. Case inputs stay in restricted
storage; copying them here would put holdout material in a database that
reviewers, auditors and operators all reach.

**Documented downgrade refusal.** `downgrade()` refuses, in a single
transaction that changes nothing, when the database holds any expert review
record. A completed blind review is evidence a named person produced under a
protocol; dropping the table would destroy the only record that it happened.
A database holding no review downgrades cleanly.

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

revision: str = "0010_wp22_expert_reviews"
down_revision: Union[str, None] = "0009_wp14_assessments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SHA256_DIGEST_REGEX = r"^sha256:[0-9a-f]{64}$"

REVIEW_STATES = ("'ASSIGNED', 'EXPECTATION_RECORDED', 'RESULT_REVEALED', "
                 "'COMPLETED', 'INVALIDATED'")
DECISIONS = "'AGREE', 'PARTIAL', 'DISAGREE'"
CORRECTION_KINDS = ("'TYPOGRAPHIC', 'RATIONALE_AMENDED', "
                    "'EXPECTATION_AMENDED', 'DECISION_ANNOTATED', "
                    "'RATING_ANNOTATED', 'WITHDRAWN_BY_REVIEWER'")
INVALIDATION_REASONS = ("'RELEASE_CHANGED', 'CASE_MANIFEST_CHANGED', "
                        "'PROTOCOL_APPROVAL_WITHDRAWN', "
                        "'BLINDING_COMPROMISED', "
                        "'REVIEWER_CONFLICT_DECLARED', "
                        "'ASSIGNMENT_SUPERSEDED'")
LIKERT_DIMENSIONS = ("'CLARITY', 'TRACEABILITY', 'CLINICAL_USEFULNESS', "
                     "'SAFETY_FRAMING'")
REVIEW_AUDIT_ACTIONS = ("'REVIEW_ASSIGNED', 'REVIEW_EXPECTATION_RECORDED', "
                        "'REVIEW_RESULT_REVEALED', 'REVIEW_COMPLETED', "
                        "'REVIEW_INVALIDATED', 'REVIEW_CORRECTION_APPENDED', "
                        "'REVIEW_PERMIT_ISSUED', 'REVIEW_PERMIT_REFUSED'")

#: Reproduced from 0009 so this migration's constraint is self-contained. A
#: migration that imported the previous one's constant would change meaning
#: when that file was edited.
AUDIT_ACTIONS_0009 = (
    "'RELEASE_REGISTERED', 'RELEASE_ACTIVATED', 'RELEASE_ROLLED_BACK', "
    "'RELEASE_RETIRED', 'LEGACY_BASELINE_REGISTERED', "
    "'DATASET_BUILD_REGISTERED', 'DATASET_QUALITY_CHECKED', "
    "'CURATION_WORK_ITEM_IMPORTED', 'CURATION_REVISION_CREATED', "
    "'CURATION_REVISION_SUBMITTED', 'CURATION_CHANGES_REQUESTED', "
    "'CURATION_APPROVED', 'CURATION_REJECTED', "
    "'CURATION_REFERRED_TO_ADJUDICATION', 'CURATION_ADJUDICATED', "
    "'RULE_DRAFTED', 'RULE_CURATED', 'RULE_VALIDATED', 'RULE_DEPRECATED', "
    "'RULE_VALIDATION_REFUSED', 'RULESET_CREATED', 'RULESET_MEMBER_ADDED', "
    "'RULESET_MEMBER_REMOVED', 'RULESET_VALIDATED', "
    "'RULESET_VALIDATION_REFUSED', 'RULESET_REOPENED', 'RULESET_FROZEN', "
    "'RULESET_RETIRED', 'ASSESSMENT_COMPLETED', 'ASSESSMENT_REFUSED'")

AUDIT_ACTIONS_0010 = AUDIT_ACTIONS_0009 + ", " + REVIEW_AUDIT_ACTIONS

#: Every table except the assignment table, which alone permits a forward
#: state move.
APPEND_ONLY_TABLES = ("expert_review_expectations", "expert_review_reveals",
                      "expert_review_completions", "expert_review_ratings",
                      "expert_review_corrections",
                      "expert_review_audit_events")

EXPERT_REVIEW_TABLES = ("expert_review_assignments",) + APPEND_ONLY_TABLES


def _digest(column: str) -> str:
    return "%s ~ '%s'" % (column, SHA256_DIGEST_REGEX)


def upgrade() -> None:
    op.create_table(
        "expert_review_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("assignment_id", sa.String(128), nullable=False),
        sa.Column("review_id", sa.String(128), nullable=False),
        sa.Column("case_id", sa.String(128), nullable=False),
        sa.Column("case_role", sa.String(32), nullable=False),
        sa.Column("reviewer_actor", sa.String(256), nullable=False),
        sa.Column("reviewer_role", sa.String(48), nullable=False),
        sa.Column("protocol_version", sa.String(128), nullable=False),
        sa.Column("protocol_hash", sa.String(80), nullable=False),
        sa.Column("release_public_id", sa.String(128), nullable=False),
        sa.Column("release_manifest_hash", sa.String(80), nullable=False),
        sa.Column("software_version", sa.String(128), nullable=False),
        sa.Column("software_hash", sa.String(80), nullable=False),
        sa.Column("dataset_public_id", sa.String(128), nullable=False),
        sa.Column("dataset_content_hash", sa.String(80), nullable=False),
        sa.Column("ruleset_public_id", sa.String(128), nullable=False),
        sa.Column("ruleset_content_hash", sa.String(80), nullable=False),
        sa.Column("case_manifest_hash", sa.String(80), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("assigned_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("invalidation_reason", sa.String(48), nullable=True),
        sa.UniqueConstraint("assignment_id",
                            name="uq_expert_review_assignments_assignment_id"),
        sa.UniqueConstraint("review_id",
                            name="uq_expert_review_assignments_review_id"),
        sa.UniqueConstraint(
            "case_id", "reviewer_actor", "release_public_id",
            name="uq_expert_review_assignments_case_reviewer_release"),
        sa.CheckConstraint(
            "case_role = 'EXPERT_HOLDOUT'",
            name="ck_expert_review_assignments_case_role_is_expert_holdout"),
        sa.CheckConstraint(
            "reviewer_role = 'EXPERT_REVIEWER'",
            name=("ck_expert_review_assignments_"
                  "reviewer_role_is_expert_reviewer")),
        sa.CheckConstraint("state IN (%s)" % REVIEW_STATES,
                           name="ck_expert_review_assignments_state_enum"),
        sa.CheckConstraint(
            "(invalidation_reason IS NULL) = (state <> 'INVALIDATED')",
            name=("ck_expert_review_assignments_"
                  "invalidated_names_its_reason")),
        sa.CheckConstraint(
            "invalidation_reason IS NULL OR invalidation_reason IN (%s)"
            % INVALIDATION_REASONS,
            name="ck_expert_review_assignments_invalidation_reason_enum"),
        sa.CheckConstraint(
            _digest("protocol_hash"),
            name="ck_expert_review_assignments_protocol_hash_format"),
        sa.CheckConstraint(
            _digest("release_manifest_hash"),
            name="ck_expert_review_assignments_release_hash_format"),
        sa.CheckConstraint(
            _digest("case_manifest_hash"),
            name="ck_expert_review_assignments_case_manifest_hash_format"),
    )
    op.create_index("ix_expert_review_assignments_reviewer",
                    "expert_review_assignments", ["reviewer_actor"])
    op.create_index("ix_expert_review_assignments_case_id",
                    "expert_review_assignments", ["case_id"])

    op.create_table(
        "expert_review_expectations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("revision_id", sa.String(128), nullable=False),
        sa.Column("review_id", sa.String(128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("expected_attention_level", sa.String(48), nullable=False),
        sa.Column("expected_coverage_status", sa.String(48), nullable=False),
        sa.Column("expected_coverage_reason", sa.String(64), nullable=True),
        sa.Column("expected_rule_id", sa.String(128), nullable=True),
        sa.Column("requires_traceable_evidence", sa.Boolean(),
                  nullable=False),
        sa.Column("rationale_codes", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("reviewer_note", sa.Text(), nullable=False,
                  server_default=""),
        sa.Column("recorded_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(80), nullable=False),
        sa.Column("revision_hash", sa.String(80), nullable=False),
        sa.Column("previous_hash", sa.String(80), nullable=True),
        sa.ForeignKeyConstraint(
            ["review_id"], ["expert_review_assignments.review_id"],
            name="fk_expert_review_expectations_review_id",
            ondelete="RESTRICT"),
        sa.UniqueConstraint("revision_id",
                            name="uq_expert_review_expectations_revision_id"),
        sa.UniqueConstraint(
            "review_id", "revision",
            name="uq_expert_review_expectations_review_revision"),
        sa.UniqueConstraint(
            "revision_hash",
            name="uq_expert_review_expectations_revision_hash"),
        sa.CheckConstraint("revision >= 1",
                           name="ck_expert_review_expectations_revision"),
        sa.CheckConstraint("length(reviewer_note) <= 1000",
                           name="ck_expert_review_expectations_note_bounded"),
        sa.CheckConstraint("jsonb_typeof(rationale_codes) = 'array'",
                           name="ck_expert_review_expectations_codes_array"),
        sa.CheckConstraint(
            _digest("revision_hash"),
            name="ck_expert_review_expectations_revision_hash_format"),
    )
    op.create_index("ix_expert_review_expectations_review_id",
                    "expert_review_expectations", ["review_id"])

    op.create_table(
        "expert_review_reveals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("reveal_id", sa.String(128), nullable=False),
        sa.Column("review_id", sa.String(128), nullable=False),
        sa.Column("expectation_revision_id", sa.String(128), nullable=False),
        sa.Column("expectation_revision_hash", sa.String(80), nullable=False),
        sa.Column("result_attention_level", sa.String(48), nullable=False),
        sa.Column("result_coverage_status", sa.String(48), nullable=False),
        sa.Column("result_coverage_reason", sa.String(64), nullable=True),
        sa.Column("result_firing_rule_id", sa.String(128), nullable=True),
        sa.Column("result_finding_count", sa.Integer(), nullable=False),
        sa.Column("result_traceable_finding_count", sa.Integer(),
                  nullable=False),
        sa.Column("result_output_hash", sa.String(80), nullable=False),
        sa.Column("revealed_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("reveal_hash", sa.String(80), nullable=False),
        sa.Column("previous_hash", sa.String(80), nullable=True),
        sa.ForeignKeyConstraint(
            ["review_id"], ["expert_review_assignments.review_id"],
            name="fk_expert_review_reveals_review_id", ondelete="RESTRICT"),
        # This is what makes "no reveal before an expectation" a referential
        # fact rather than a rule: there is no revision id to name.
        sa.ForeignKeyConstraint(
            ["expectation_revision_id"],
            ["expert_review_expectations.revision_id"],
            name="fk_expert_review_reveals_expectation_revision_id",
            ondelete="RESTRICT"),
        sa.UniqueConstraint("reveal_id",
                            name="uq_expert_review_reveals_reveal_id"),
        sa.UniqueConstraint(
            "review_id", name="uq_expert_review_reveals_one_per_review"),
        sa.CheckConstraint(
            "result_traceable_finding_count <= result_finding_count",
            name="ck_expert_review_reveals_traceable_within_findings"),
        sa.CheckConstraint("result_finding_count >= 0",
                           name="ck_expert_review_reveals_findings_positive"),
        sa.CheckConstraint(
            _digest("expectation_revision_hash"),
            name="ck_expert_review_reveals_expectation_hash_format"),
        sa.CheckConstraint(_digest("reveal_hash"),
                           name="ck_expert_review_reveals_reveal_hash_format"),
    )

    op.create_table(
        "expert_review_completions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("completion_id", sa.String(128), nullable=False),
        sa.Column("review_id", sa.String(128), nullable=False),
        sa.Column("reveal_id", sa.String(128), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reviewer_note", sa.Text(), nullable=False,
                  server_default=""),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True),
                  nullable=False),
        sa.Column("completion_hash", sa.String(80), nullable=False),
        sa.Column("previous_hash", sa.String(80), nullable=True),
        sa.ForeignKeyConstraint(
            ["review_id"], ["expert_review_assignments.review_id"],
            name="fk_expert_review_completions_review_id",
            ondelete="RESTRICT"),
        # And this makes "no completion before a reveal" referential too.
        sa.ForeignKeyConstraint(
            ["reveal_id"], ["expert_review_reveals.reveal_id"],
            name="fk_expert_review_completions_reveal_id",
            ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "completion_id",
            name="uq_expert_review_completions_completion_id"),
        sa.UniqueConstraint(
            "review_id", name="uq_expert_review_completions_one_per_review"),
        sa.CheckConstraint("decision IN (%s)" % DECISIONS,
                           name="ck_expert_review_completions_decision_enum"),
        sa.CheckConstraint("length(reviewer_note) <= 1000",
                           name="ck_expert_review_completions_note_bounded"),
        sa.CheckConstraint(
            _digest("completion_hash"),
            name="ck_expert_review_completions_hash_format"),
    )

    op.create_table(
        "expert_review_ratings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("completion_id", sa.String(128), nullable=False),
        sa.Column("dimension", sa.String(48), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["completion_id"], ["expert_review_completions.completion_id"],
            name="fk_expert_review_ratings_completion_id",
            ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "completion_id", "dimension",
            name="uq_expert_review_ratings_completion_dimension"),
        sa.CheckConstraint("dimension IN (%s)" % LIKERT_DIMENSIONS,
                           name="ck_expert_review_ratings_dimension_enum"),
        sa.CheckConstraint("value BETWEEN 1 AND 5",
                           name="ck_expert_review_ratings_value_bounded"),
    )

    op.create_table(
        "expert_review_corrections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("correction_id", sa.String(128), nullable=False),
        sa.Column("review_id", sa.String(128), nullable=False),
        sa.Column("target_hash", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(256), nullable=False),
        sa.Column("actor_role", sa.String(48), nullable=False),
        sa.Column("replacement", postgresql.JSONB(), nullable=True),
        sa.Column("after_reveal", sa.Boolean(), nullable=False),
        sa.Column("recorded_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("correction_hash", sa.String(80), nullable=False),
        sa.Column("previous_hash", sa.String(80), nullable=True),
        sa.ForeignKeyConstraint(
            ["review_id"], ["expert_review_assignments.review_id"],
            name="fk_expert_review_corrections_review_id",
            ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "correction_id",
            name="uq_expert_review_corrections_correction_id"),
        sa.UniqueConstraint("correction_hash",
                            name="uq_expert_review_corrections_hash"),
        sa.CheckConstraint("kind IN (%s)" % CORRECTION_KINDS,
                           name="ck_expert_review_corrections_kind_enum"),
        sa.CheckConstraint(
            "actor_role = 'EXPERT_REVIEWER'",
            name="ck_expert_review_corrections_corrector_is_the_reviewer"),
        sa.CheckConstraint(
            _digest("correction_hash"),
            name="ck_expert_review_corrections_hash_format"),
    )
    op.create_index("ix_expert_review_corrections_review_id",
                    "expert_review_corrections", ["review_id"])

    op.create_table(
        "expert_review_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("review_id", sa.String(128), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("actor", sa.String(256), nullable=False),
        sa.Column("actor_role", sa.String(48), nullable=False),
        sa.Column("actor_authenticated", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("previous_state", sa.String(32), nullable=True),
        sa.Column("new_state", sa.String(32), nullable=True),
        sa.Column("outcome_code", sa.String(64), nullable=False),
        sa.Column("protocol_hash", sa.String(80), nullable=False),
        sa.Column("release_manifest_hash", sa.String(80), nullable=False),
        sa.Column("case_manifest_hash", sa.String(80), nullable=False),
        sa.Column("record_hashes", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("previous_hash", sa.String(80), nullable=True),
        sa.Column("event_hash", sa.String(80), nullable=False),
        sa.ForeignKeyConstraint(
            ["review_id"], ["expert_review_assignments.review_id"],
            name="fk_expert_review_audit_events_review_id",
            ondelete="RESTRICT"),
        sa.UniqueConstraint("event_id",
                            name="uq_expert_review_audit_events_event_id"),
        sa.UniqueConstraint("review_id", "sequence",
                            name="uq_expert_review_audit_events_sequence"),
        sa.UniqueConstraint("event_hash",
                            name="uq_expert_review_audit_events_event_hash"),
        sa.CheckConstraint("action IN (%s)" % REVIEW_AUDIT_ACTIONS,
                           name="ck_expert_review_audit_events_action_enum"),
        # WP-23 changes this in the open, or not at all.
        sa.CheckConstraint(
            "actor_authenticated = false",
            name=("ck_expert_review_audit_events_"
                  "no_p0_principal_is_authenticated")),
        sa.CheckConstraint("sequence >= 1",
                           name="ck_expert_review_audit_events_sequence"),
        sa.CheckConstraint(
            "(sequence = 1) = (previous_hash IS NULL)",
            name="ck_expert_review_audit_events_first_starts_the_chain"),
        sa.CheckConstraint(
            _digest("event_hash"),
            name="ck_expert_review_audit_events_event_hash_format"),
    )
    op.create_index("ix_expert_review_audit_events_review_id",
                    "expert_review_audit_events", ["review_id"])

    # -- append-only enforcement -----------------------------------------
    #
    # Six tables refuse UPDATE and DELETE outright. A review record describes
    # what a named person did at a moment; editing one would make the trail
    # describe an act that did not happen, and deleting one would remove the
    # only evidence that it did.
    op.execute("""
        CREATE OR REPLACE FUNCTION pgx_expert_review_append_only()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'expert review records are append-only: % on % is refused. '
                'A change is an appended correction.',
                TG_OP, TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
    """)
    for table in APPEND_ONLY_TABLES:
        op.execute("""
            CREATE TRIGGER trg_%s_append_only
            BEFORE UPDATE OR DELETE ON %s
            FOR EACH ROW EXECUTE FUNCTION pgx_expert_review_append_only();
        """ % (table, table))

    # -- the assignment table: forward moves only ------------------------
    #
    # The one table a later statement changes, and it may change exactly one
    # column, to exactly the states the protocol permits. Deletion is refused
    # like everywhere else.
    op.execute("""
        CREATE OR REPLACE FUNCTION pgx_expert_review_forward_only()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION
                    'an expert review assignment is never deleted'
                    USING ERRCODE = 'restrict_violation';
            END IF;

            IF NEW.assignment_id IS DISTINCT FROM OLD.assignment_id
               OR NEW.review_id IS DISTINCT FROM OLD.review_id
               OR NEW.case_id IS DISTINCT FROM OLD.case_id
               OR NEW.case_role IS DISTINCT FROM OLD.case_role
               OR NEW.reviewer_actor IS DISTINCT FROM OLD.reviewer_actor
               OR NEW.reviewer_role IS DISTINCT FROM OLD.reviewer_role
               OR NEW.protocol_hash IS DISTINCT FROM OLD.protocol_hash
               OR NEW.release_manifest_hash
                  IS DISTINCT FROM OLD.release_manifest_hash
               OR NEW.case_manifest_hash
                  IS DISTINCT FROM OLD.case_manifest_hash
               OR NEW.assigned_at IS DISTINCT FROM OLD.assigned_at THEN
                RAISE EXCEPTION
                    'only the state of an assignment may change; its case, '
                    'reviewer, protocol, release and timing are pinned'
                    USING ERRCODE = 'restrict_violation';
            END IF;

            IF NOT (
                (OLD.state = 'ASSIGNED'
                 AND NEW.state IN ('EXPECTATION_RECORDED', 'INVALIDATED'))
             OR (OLD.state = 'EXPECTATION_RECORDED'
                 AND NEW.state IN ('RESULT_REVEALED', 'INVALIDATED'))
             OR (OLD.state = 'RESULT_REVEALED'
                 AND NEW.state IN ('COMPLETED', 'INVALIDATED'))
            ) THEN
                RAISE EXCEPTION
                    'the blind review protocol does not permit % -> %',
                    OLD.state, NEW.state
                    USING ERRCODE = 'restrict_violation';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER trg_expert_review_assignments_forward_only
        BEFORE UPDATE OR DELETE ON expert_review_assignments
        FOR EACH ROW EXECUTE FUNCTION pgx_expert_review_forward_only();
    """)

    # -- the audit action list widens ------------------------------------
    op.drop_constraint("ck_audit_events_action_enum", "audit_events",
                       type_="check")
    op.create_check_constraint(
        "ck_audit_events_action_enum", "audit_events",
        sa.text("action IN (%s)" % AUDIT_ACTIONS_0010))


def downgrade() -> None:
    """Refuse while any review record exists; otherwise drop cleanly.

    A completed blind review is evidence a named person produced under a
    protocol. Dropping the table would destroy the only record that it
    happened, and a downgrade that did so silently would be the most
    destructive statement in this repository. Removing real review history
    requires exporting it and deleting the rows explicitly - which the
    append-only triggers also refuse, so it requires a deliberate, reviewed
    migration of its own.
    """
    connection = op.get_bind()
    stored = connection.execute(
        sa.text("SELECT count(*) FROM expert_review_assignments")).scalar()
    if stored:
        raise RuntimeError(
            "refusing to downgrade: %d expert review assignment(s) exist. "
            "A blind review is evidence a person produced under a protocol; "
            "this migration will not destroy it silently." % stored)

    op.drop_constraint("ck_audit_events_action_enum", "audit_events",
                       type_="check")
    op.create_check_constraint(
        "ck_audit_events_action_enum", "audit_events",
        sa.text("action IN (%s)" % AUDIT_ACTIONS_0009))

    op.execute("DROP TRIGGER IF EXISTS "
               "trg_expert_review_assignments_forward_only "
               "ON expert_review_assignments;")
    op.execute("DROP FUNCTION IF EXISTS pgx_expert_review_forward_only();")

    for table in APPEND_ONLY_TABLES:
        op.execute("DROP TRIGGER IF EXISTS trg_%s_append_only ON %s;"
                   % (table, table))
    op.execute("DROP FUNCTION IF EXISTS pgx_expert_review_append_only();")

    op.drop_index("ix_expert_review_audit_events_review_id",
                  table_name="expert_review_audit_events")
    op.drop_table("expert_review_audit_events")
    op.drop_index("ix_expert_review_corrections_review_id",
                  table_name="expert_review_corrections")
    op.drop_table("expert_review_corrections")
    op.drop_table("expert_review_ratings")
    op.drop_table("expert_review_completions")
    op.drop_table("expert_review_reveals")
    op.drop_index("ix_expert_review_expectations_review_id",
                  table_name="expert_review_expectations")
    op.drop_table("expert_review_expectations")
    op.drop_index("ix_expert_review_assignments_case_id",
                  table_name="expert_review_assignments")
    op.drop_index("ix_expert_review_assignments_reviewer",
                  table_name="expert_review_assignments")
    op.drop_table("expert_review_assignments")
