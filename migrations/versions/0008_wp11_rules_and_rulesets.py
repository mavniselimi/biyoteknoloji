# -*- coding: utf-8 -*-
"""WP-11 governed computable rules and immutable rulesets.

Revision ID: 0008_wp11_rules_and_rulesets
Revises: 0007_wp10_curation_workflow
Create Date: 2026-09-03

Hand-written and reviewed, not autogenerate output. ``0001`` through ``0007``
are not rewritten: this revision **extends** the tables they created and adds
new ones beside them.

**Why it extends rather than replaces.** ``0001`` created ``computable_rules``
and ``rule_evidence``; ``0002`` created ``ruleset_versions`` and
``ruleset_rules``. Those are the right tables for what WP-11 governs, and
creating ``wp11_rules`` beside them would leave two answers to "what rules
exist" - which is exactly the drift the release registry exists to stop. So
this migration adds the columns WP-11 needs, and adds ``rule_lifecycle``,
``ruleset_builds`` and ``ruleset_approvals`` for state and provenance the
earlier tables never modelled.

**Which layer enforces which invariant.** Stated here because "enforced" with
no named enforcer is how an invariant quietly stops holding.

| Invariant | Enforced by |
|---|---|
| legal rule status transition | ``trg_computable_rules_guarded`` |
| validated/deprecated rule content is immutable | ``trg_computable_rules_guarded`` |
| a status change advances the lifecycle version | ``trg_computable_rules_guarded`` |
| one family/version pair exists once | ``uq_computable_rules_family_version`` |
| a validated rule cites evidence | ``trg_computable_rules_guarded`` (counts ``rule_evidence``) |
| a validated rule pins a curation revision and hash | check constraint |
| legal ruleset status transition | ``trg_ruleset_versions_guarded`` |
| frozen membership is immutable | ``trg_ruleset_rules_frozen_immutable`` |
| frozen manifest and hash are immutable | ``trg_ruleset_versions_guarded`` |
| a member is VALIDATED when pinned | ``trg_ruleset_rules_member_validated`` |
| no duplicate membership | ``pk_ruleset_rules`` (from ``0002``) |
| build and approval records are append-only | ``trg_*_append_only`` |
| audit events are append-only | ``trg_audit_events_append_only`` (``0002``) |
| conflict detection across members | the application (a set-level property no row constraint can see) |
| deterministic artifact hashing | the application and the artifact's own checksums |

The last two are deliberately not in the database: a conflicting-outcome
between two rules is a property of a *set*, and PostgreSQL cannot express it in
a row constraint without a trigger that re-derives the whole comparison on
every insert. Saying so here is better than implying the database checks it.

**Advisory locks.** Ruleset validation and freezing take
``pg_advisory_xact_lock`` on a key derived from the ruleset id, so two
concurrent freezes of one ruleset serialise rather than racing. The helper
``pgx_ruleset_lock_key`` is created here; the application calls it.

``downgrade()`` drops exactly these objects, children before parents, drops
each trigger *and* its function, and removes the added columns. Nothing from
``0001`` through ``0007`` is otherwise touched.

**Documented downgrade refusal.** The downgrade refuses, in a single
transaction that changes nothing, when the database holds a ``VALIDATED`` or
``DEPRECATED`` rule or a ``FROZEN`` ruleset. Those rows record that named
people approved a scientific claim, and a frozen ruleset may be cited by a
release or a historical assessment; dropping the columns holding their
provenance would destroy the only evidence the approval happened. A database
holding only drafts downgrades cleanly.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_wp11_rules_and_rulesets"
down_revision: Union[str, None] = "0007_wp10_curation_workflow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SHA256_DIGEST_REGEX = r"^sha256:[0-9a-f]{64}$"

RULE_STATUSES = "'DRAFT', 'CURATED', 'VALIDATED', 'DEPRECATED'"
RULE_IMMUTABLE_STATUSES = "'VALIDATED', 'DEPRECATED'"
RULESET_STATUSES = "'BUILDING', 'VALIDATED', 'FROZEN', 'RETIRED'"

#: Levels a rule may author. NOT_ASSESSED is absent: it is a downstream
#: coverage result meaning "we did not look", and a rule asserting it in
#: advance would be making a claim about a case it has not seen.
RULE_OUTCOME_LEVELS = "'NO_ACTIVE_ATTENTION', 'LOW', 'MEDIUM', 'HIGH'"

BUILD_OUTCOMES = "'SUCCEEDED', 'REFUSED', 'FAILED'"

#: The ``0007`` audit action list, restored verbatim by ``downgrade()``.
AUDIT_ACTIONS_0007 = ("'RELEASE_REGISTERED', 'RELEASE_ACTIVATED', "
                      "'RELEASE_ROLLED_BACK', 'RELEASE_RETIRED', "
                      "'LEGACY_BASELINE_REGISTERED', 'DATASET_BUILD_REGISTERED', "
                      "'DATASET_QUALITY_CHECKED', "
                      "'CURATION_WORK_ITEM_IMPORTED', "
                      "'CURATION_REVISION_CREATED', "
                      "'CURATION_REVISION_SUBMITTED', "
                      "'CURATION_CHANGES_REQUESTED', 'CURATION_APPROVED', "
                      "'CURATION_REJECTED', "
                      "'CURATION_REFERRED_TO_ADJUDICATION', "
                      "'CURATION_ADJUDICATED'")

#: The same list plus the thirteen WP-11 actions. Written out in full rather
#: than concatenated, for the same reason 0004, 0005 and 0007 wrote theirs out:
#: the actions this constraint admits should be on the page a reader is looking
#: at, not one indirection away.
AUDIT_ACTIONS_0008 = ("'RELEASE_REGISTERED', 'RELEASE_ACTIVATED', "
                      "'RELEASE_ROLLED_BACK', 'RELEASE_RETIRED', "
                      "'LEGACY_BASELINE_REGISTERED', 'DATASET_BUILD_REGISTERED', "
                      "'DATASET_QUALITY_CHECKED', "
                      "'CURATION_WORK_ITEM_IMPORTED', "
                      "'CURATION_REVISION_CREATED', "
                      "'CURATION_REVISION_SUBMITTED', "
                      "'CURATION_CHANGES_REQUESTED', 'CURATION_APPROVED', "
                      "'CURATION_REJECTED', "
                      "'CURATION_REFERRED_TO_ADJUDICATION', "
                      "'CURATION_ADJUDICATED', "
                      "'RULE_DRAFTED', 'RULE_CURATED', 'RULE_VALIDATED', "
                      "'RULE_DEPRECATED', 'RULE_VALIDATION_REFUSED', "
                      "'RULESET_CREATED', 'RULESET_MEMBER_ADDED', "
                      "'RULESET_MEMBER_REMOVED', 'RULESET_VALIDATED', "
                      "'RULESET_VALIDATION_REFUSED', 'RULESET_REOPENED', "
                      "'RULESET_FROZEN', 'RULESET_RETIRED'")

# ---------------------------------------------------------------------------
# functions and triggers
# ---------------------------------------------------------------------------

_LOCK_KEY_FUNCTION = """
CREATE OR REPLACE FUNCTION pgx_ruleset_lock_key(ruleset uuid)
RETURNS bigint AS $$
    -- A stable 63-bit key from the ruleset's identity, so two sessions
    -- validating or freezing one ruleset serialise on the same lock. Derived
    -- rather than stored: a lock table would be one more thing to keep in
    -- step with the rows it protects.
    SELECT ('x' || substr(md5(ruleset::text), 1, 15))::bit(60)::bigint;
$$ LANGUAGE sql IMMUTABLE;
"""

_RULE_GUARD_FUNCTION = """
CREATE OR REPLACE FUNCTION pgx_computable_rules_guarded()
RETURNS TRIGGER AS $$
DECLARE
    evidence_count integer;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'computable_rules rows are not deletable: a rule may be cited by a '
            'frozen ruleset and by historical assessments, and deleting it '
            'would make those unexplainable. Withdrawal is DEPRECATED.'
            USING ERRCODE = 'restrict_violation';
    END IF;

    -- Content is fixed once a rule is validated. A correction is a new
    -- version in the same family, so the approval that named version 2
    -- cannot be read as covering version 3.
    IF OLD.status IN ('VALIDATED', 'DEPRECATED') THEN
        IF NEW.condition_json IS DISTINCT FROM OLD.condition_json
           OR NEW.attention_level IS DISTINCT FROM OLD.attention_level
           OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
           OR NEW.interpretation_id IS DISTINCT FROM OLD.interpretation_id
           OR NEW.curation_revision_id IS DISTINCT FROM OLD.curation_revision_id
           OR NEW.curation_revision_hash IS DISTINCT FROM OLD.curation_revision_hash
           OR NEW.rule_family_id IS DISTINCT FROM OLD.rule_family_id
           OR NEW.rule_version IS DISTINCT FROM OLD.rule_version THEN
            RAISE EXCEPTION
                'rule % is % and its scientific content is immutable. A '
                'correction is a new rule version in the same family, never an '
                'edit of an approved one.', OLD.id, OLD.status
                USING ERRCODE = 'restrict_violation';
        END IF;
    END IF;

    IF NEW.status IS DISTINCT FROM OLD.status THEN
        IF NOT (
            (OLD.status = 'DRAFT' AND NEW.status = 'CURATED') OR
            (OLD.status = 'CURATED' AND NEW.status = 'VALIDATED') OR
            (OLD.status = 'VALIDATED' AND NEW.status = 'DEPRECATED')
        ) THEN
            RAISE EXCEPTION
                'rule %: % is not a transition this lifecycle has. Permitted: '
                'DRAFT->CURATED, CURATED->VALIDATED, VALIDATED->DEPRECATED.',
                OLD.id, OLD.status || '->' || NEW.status
                USING ERRCODE = 'check_violation';
        END IF;

        IF NEW.lifecycle_version <= OLD.lifecycle_version THEN
            RAISE EXCEPTION
                'rule %: a status change must advance lifecycle_version (was '
                '%, offered %). Optimistic concurrency is what stops two '
                'reviewers from both deciding the same state.',
                OLD.id, OLD.lifecycle_version, NEW.lifecycle_version
                USING ERRCODE = 'check_violation';
        END IF;

        -- SAFETY-INV-006: a validated rule cites evidence that resolves.
        IF NEW.status = 'VALIDATED' THEN
            SELECT count(*) INTO evidence_count
            FROM rule_evidence WHERE rule_id = NEW.id;
            IF evidence_count = 0 THEN
                RAISE EXCEPTION
                    'rule % cannot be validated with no evidence reference. A '
                    'finding without a resolvable citation is an assertion '
                    '(SAFETY-INV-006).', NEW.id
                    USING ERRCODE = 'check_violation';
            END IF;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_RULE_GUARD_TRIGGER = """
CREATE TRIGGER trg_computable_rules_guarded
BEFORE UPDATE OR DELETE ON computable_rules
FOR EACH ROW EXECUTE FUNCTION pgx_computable_rules_guarded();
"""

_RULESET_GUARD_FUNCTION = """
CREATE OR REPLACE FUNCTION pgx_ruleset_versions_guarded()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'ruleset_versions rows are not deletable: a release or a '
            'historical assessment may cite this ruleset. Withdrawal is '
            'RETIRED, which keeps the artifact.'
            USING ERRCODE = 'restrict_violation';
    END IF;

    -- A frozen ruleset's identity is fixed. Retiring it is permitted and
    -- changes only the status and the retirement metadata.
    IF OLD.status = 'FROZEN' THEN
        IF NEW.manifest_hash IS DISTINCT FROM OLD.manifest_hash
           OR NEW.ruleset_content_hash IS DISTINCT FROM OLD.ruleset_content_hash
           OR NEW.public_id IS DISTINCT FROM OLD.public_id
           OR NEW.frozen_at IS DISTINCT FROM OLD.frozen_at
           OR NEW.frozen_by IS DISTINCT FROM OLD.frozen_by THEN
            RAISE EXCEPTION
                'ruleset % is FROZEN: its manifest, hash and identity are '
                'immutable. A correction is a new ruleset identity and a new '
                'build, so whatever cited this hash still resolves to what it '
                'cited.', OLD.id
                USING ERRCODE = 'restrict_violation';
        END IF;
    END IF;

    IF NEW.status IS DISTINCT FROM OLD.status THEN
        IF NOT (
            (OLD.status = 'BUILDING' AND NEW.status = 'VALIDATED') OR
            (OLD.status = 'VALIDATED' AND NEW.status IN ('FROZEN', 'BUILDING')) OR
            (OLD.status = 'FROZEN' AND NEW.status = 'RETIRED')
        ) THEN
            RAISE EXCEPTION
                'ruleset %: % is not a transition this lifecycle has. There is '
                'deliberately no BUILDING->FROZEN edge: validating and freezing '
                'are two audited acts, and collapsing them would let a set '
                'become permanent without anybody deciding it should.',
                OLD.id, OLD.status || '->' || NEW.status
                USING ERRCODE = 'check_violation';
        END IF;

        IF NEW.lifecycle_version <= OLD.lifecycle_version THEN
            RAISE EXCEPTION
                'ruleset %: a status change must advance lifecycle_version '
                '(was %, offered %).',
                OLD.id, OLD.lifecycle_version, NEW.lifecycle_version
                USING ERRCODE = 'check_violation';
        END IF;

        IF NEW.status = 'FROZEN' THEN
            IF NEW.ruleset_content_hash IS NULL OR NEW.manifest_hash IS NULL THEN
                RAISE EXCEPTION
                    'ruleset % cannot be frozen without a manifest hash and a '
                    'content hash; a frozen ruleset nobody can verify is not '
                    'frozen.', OLD.id
                    USING ERRCODE = 'check_violation';
            END IF;
            IF (SELECT count(*) FROM ruleset_rules WHERE ruleset_id = NEW.id) = 0 THEN
                RAISE EXCEPTION
                    'ruleset % cannot be frozen with no members. An empty '
                    'frozen ruleset would let a release claim rule membership '
                    'it does not have.', OLD.id
                    USING ERRCODE = 'check_violation';
            END IF;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_RULESET_GUARD_TRIGGER = """
CREATE TRIGGER trg_ruleset_versions_guarded
BEFORE UPDATE OR DELETE ON ruleset_versions
FOR EACH ROW EXECUTE FUNCTION pgx_ruleset_versions_guarded();
"""

_MEMBERSHIP_FUNCTION = """
CREATE OR REPLACE FUNCTION pgx_ruleset_rules_guarded()
RETURNS TRIGGER AS $$
DECLARE
    ruleset_status text;
    member_status text;
    member_hash text;
    target_ruleset uuid;
BEGIN
    target_ruleset := COALESCE(NEW.ruleset_id, OLD.ruleset_id);
    SELECT status INTO ruleset_status FROM ruleset_versions WHERE id = target_ruleset;

    -- Membership changes only while a ruleset is BUILDING. A validated set has
    -- had its membership checked; a frozen one has been published.
    IF ruleset_status IS DISTINCT FROM 'BUILDING' THEN
        RAISE EXCEPTION
            'ruleset % is %: membership changes only while a ruleset is '
            'BUILDING. A frozen membership is what a release pins.',
            target_ruleset, ruleset_status
            USING ERRCODE = 'restrict_violation';
    END IF;

    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        SELECT status, content_hash INTO member_status, member_hash
        FROM computable_rules WHERE id = NEW.rule_id;

        IF member_status IS DISTINCT FROM 'VALIDATED' THEN
            RAISE EXCEPTION
                'rule % is %; only VALIDATED rules enter a ruleset '
                '(SAFETY-INV-003).', NEW.rule_id, COALESCE(member_status, 'absent')
                USING ERRCODE = 'check_violation';
        END IF;

        -- Membership pins the content hash, so a member altered afterwards is
        -- detectable rather than invisible.
        IF NEW.member_content_hash IS DISTINCT FROM member_hash THEN
            RAISE EXCEPTION
                'membership pins content hash % for rule %, which hashes to %.',
                NEW.member_content_hash, NEW.rule_id, member_hash
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;

    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;
"""

_MEMBERSHIP_TRIGGER = """
CREATE TRIGGER trg_ruleset_rules_guarded
BEFORE INSERT OR UPDATE OR DELETE ON ruleset_rules
FOR EACH ROW EXECUTE FUNCTION pgx_ruleset_rules_guarded();
"""

_APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION pgx_rule_record_append_only()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        '% on %.% is not permitted: build and approval records state what '
        'happened at a moment that has passed. A later build is a new record.',
        TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

_BUILDS_APPEND_ONLY_TRIGGER = """
CREATE TRIGGER trg_ruleset_builds_append_only
BEFORE UPDATE OR DELETE ON ruleset_builds
FOR EACH ROW EXECUTE FUNCTION pgx_rule_record_append_only();
"""

_APPROVALS_APPEND_ONLY_TRIGGER = """
CREATE TRIGGER trg_ruleset_approvals_append_only
BEFORE UPDATE OR DELETE ON ruleset_approvals
FOR EACH ROW EXECUTE FUNCTION pgx_rule_record_append_only();
"""

_LIFECYCLE_APPEND_ONLY_TRIGGER = """
CREATE TRIGGER trg_rule_lifecycle_events_append_only
BEFORE UPDATE OR DELETE ON rule_lifecycle_events
FOR EACH ROW EXECUTE FUNCTION pgx_rule_record_append_only();
"""

_DOWNGRADE_GUARD = """
DO $$
DECLARE
    approved bigint;
    frozen bigint;
BEGIN
    SELECT count(*) INTO approved FROM computable_rules
        WHERE status IN ('VALIDATED', 'DEPRECATED');
    SELECT count(*) INTO frozen FROM ruleset_versions WHERE status = 'FROZEN';

    IF approved > 0 OR frozen > 0 THEN
        RAISE EXCEPTION
            'refusing to downgrade: this database holds % approved rule(s) and '
            '% frozen ruleset(s). Those rows record that named people approved '
            'a scientific claim, and a frozen ruleset may be cited by a release '
            'or a historical assessment. Export them and decide explicitly what '
            'replaces this schema.', approved, frozen
            USING ERRCODE = 'restrict_violation';
    END IF;
END $$;
"""


def _uuid() -> postgresql.UUID:
    return postgresql.UUID(as_uuid=True)


def _timestamptz() -> postgresql.TIMESTAMP:
    return postgresql.TIMESTAMP(timezone=True)


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """Extend the rule and ruleset tables, and add WP-11's own."""

    # -- computable_rules: WP-11 provenance and lifecycle -----------------
    op.add_column("computable_rules", sa.Column(
        "rule_family_id", _uuid(), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "supersedes_rule_id", _uuid(), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "rule_schema_version", sa.String(length=64), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "condition_schema_version", sa.String(length=64), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "content_hash", sa.String(length=80), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "lifecycle_version", sa.Integer(), nullable=False,
        server_default=sa.text("0")))
    op.add_column("computable_rules", sa.Column(
        "gene_canonical_key", sa.String(length=128), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "drug_canonical_key", sa.String(length=128), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "curation_work_item_id", sa.String(length=128), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "curation_revision_id", sa.String(length=128), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "curation_revision_hash", sa.String(length=80), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "approval_envelope_hash", sa.String(length=80), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "protocol_version", sa.String(length=128), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "protocol_content_hash", sa.String(length=80), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "dataset_public_id", sa.String(length=64), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "canonical_build_key", sa.String(length=128), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "canonical_build_content_hash", sa.String(length=80), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "evidence_build_key", sa.String(length=128), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "evidence_build_content_hash", sa.String(length=80), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "source_policy_version", sa.String(length=128), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "source_policy_content_hash", sa.String(length=80), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "validation_result_hash", sa.String(length=80), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "validated_by", sa.String(length=256), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "validated_at", _timestamptz(), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "deprecated_by", sa.String(length=256), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "deprecated_at", _timestamptz(), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "deprecation_reason", sa.Text(), nullable=True))
    op.add_column("computable_rules", sa.Column(
        "updated_at", _timestamptz(), nullable=True))

    op.create_foreign_key(
        "fk_computable_rules_supersedes_rule_id_computable_rules",
        "computable_rules", "computable_rules",
        ["supersedes_rule_id"], ["id"], ondelete="RESTRICT")

    # One family/version pair exists once. Two answers claiming to be the same
    # revision of one question is a lineage nobody can order.
    op.create_unique_constraint(
        "uq_computable_rules_family_version", "computable_rules",
        ["rule_family_id", "rule_version"])

    op.create_check_constraint(
        "ck_computable_rules_content_hash_format", "computable_rules",
        sa.text("content_hash IS NULL OR content_hash ~ '%s'"
                % SHA256_DIGEST_REGEX))
    op.create_check_constraint(
        "ck_computable_rules_lifecycle_version_non_negative", "computable_rules",
        sa.text("lifecycle_version >= 0"))
    # A rule may not author NOT_ASSESSED. 0001 admitted every attention level
    # because it did not yet know which ones a rule could produce.
    op.create_check_constraint(
        "ck_computable_rules_outcome_is_authorable", "computable_rules",
        sa.text("attention_level IN (%s)" % RULE_OUTCOME_LEVELS))
    # Reaching CURATED or beyond requires the exact curation revision and its
    # hash: a rule that named only a work item could descend from a later edit.
    op.create_check_constraint(
        "ck_computable_rules_curated_pins_revision", "computable_rules",
        sa.text("status = 'DRAFT' OR (curation_revision_id IS NOT NULL"
                " AND length(trim(curation_revision_id)) > 0"
                " AND curation_revision_hash IS NOT NULL"
                " AND curation_revision_hash ~ '%s')" % SHA256_DIGEST_REGEX))
    op.create_check_constraint(
        "ck_computable_rules_validated_pins_provenance", "computable_rules",
        sa.text("status NOT IN ('VALIDATED', 'DEPRECATED') OR ("
                " content_hash IS NOT NULL"
                " AND approval_envelope_hash IS NOT NULL"
                " AND protocol_content_hash IS NOT NULL"
                " AND evidence_build_content_hash IS NOT NULL"
                " AND dataset_public_id IS NOT NULL"
                " AND rule_family_id IS NOT NULL)"))
    op.create_check_constraint(
        "ck_computable_rules_validated_records_validator", "computable_rules",
        sa.text("status NOT IN ('VALIDATED', 'DEPRECATED') OR ("
                " validated_by IS NOT NULL AND length(trim(validated_by)) > 0"
                " AND validated_at IS NOT NULL"
                " AND validation_result_hash IS NOT NULL)"))
    op.create_check_constraint(
        "ck_computable_rules_deprecated_records_reason", "computable_rules",
        sa.text("status <> 'DEPRECATED' OR ("
                " deprecated_by IS NOT NULL AND length(trim(deprecated_by)) > 0"
                " AND deprecated_at IS NOT NULL"
                " AND deprecation_reason IS NOT NULL"
                " AND length(trim(deprecation_reason)) > 0)"))
    # An author may not be their own validator.
    op.create_check_constraint(
        "ck_computable_rules_validator_is_not_author", "computable_rules",
        sa.text("validated_by IS NULL"
                " OR lower(btrim(validated_by)) <> lower(btrim(created_by))"))
    op.create_check_constraint(
        "ck_computable_rules_not_own_predecessor", "computable_rules",
        sa.text("supersedes_rule_id IS NULL OR supersedes_rule_id <> id"))

    op.create_index("ix_computable_rules_family", "computable_rules",
                    ["rule_family_id"], unique=False)
    op.create_index("ix_computable_rules_content_hash", "computable_rules",
                    ["content_hash"], unique=False)
    op.create_index("ix_computable_rules_axis", "computable_rules",
                    ["gene_canonical_key", "drug_canonical_key"], unique=False)

    # -- ruleset_versions: WP-11 lifecycle and pins -----------------------
    op.add_column("ruleset_versions", sa.Column(
        "ruleset_content_hash", sa.String(length=80), nullable=True))
    op.add_column("ruleset_versions", sa.Column(
        "ruleset_schema_version", sa.String(length=64), nullable=True))
    op.add_column("ruleset_versions", sa.Column(
        "lifecycle_version", sa.Integer(), nullable=False,
        server_default=sa.text("0")))
    op.add_column("ruleset_versions", sa.Column(
        "dataset_public_id", sa.String(length=64), nullable=True))
    op.add_column("ruleset_versions", sa.Column(
        "canonical_build_key", sa.String(length=128), nullable=True))
    op.add_column("ruleset_versions", sa.Column(
        "canonical_build_content_hash", sa.String(length=80), nullable=True))
    op.add_column("ruleset_versions", sa.Column(
        "evidence_build_key", sa.String(length=128), nullable=True))
    op.add_column("ruleset_versions", sa.Column(
        "evidence_build_content_hash", sa.String(length=80), nullable=True))
    op.add_column("ruleset_versions", sa.Column(
        "protocol_version", sa.String(length=128), nullable=True))
    op.add_column("ruleset_versions", sa.Column(
        "protocol_content_hash", sa.String(length=80), nullable=True))
    op.add_column("ruleset_versions", sa.Column(
        "source_policy_version", sa.String(length=128), nullable=True))
    op.add_column("ruleset_versions", sa.Column(
        "source_policy_content_hash", sa.String(length=80), nullable=True))
    op.add_column("ruleset_versions", sa.Column(
        "approval_list_hash", sa.String(length=80), nullable=True))
    op.add_column("ruleset_versions", sa.Column(
        "artifact_relative_path", sa.String(length=512), nullable=True))
    op.add_column("ruleset_versions", sa.Column(
        "created_by", sa.String(length=256), nullable=True))
    op.add_column("ruleset_versions", sa.Column(
        "frozen_by", sa.String(length=256), nullable=True))
    op.add_column("ruleset_versions", sa.Column(
        "frozen_at", _timestamptz(), nullable=True))
    op.add_column("ruleset_versions", sa.Column(
        "retired_by", sa.String(length=256), nullable=True))
    op.add_column("ruleset_versions", sa.Column(
        "retired_at", _timestamptz(), nullable=True))
    op.add_column("ruleset_versions", sa.Column(
        "retirement_reason", sa.Text(), nullable=True))
    op.add_column("ruleset_versions", sa.Column(
        "updated_at", _timestamptz(), nullable=True))

    op.create_check_constraint(
        "ck_ruleset_versions_content_hash_format", "ruleset_versions",
        sa.text("ruleset_content_hash IS NULL OR ruleset_content_hash ~ '%s'"
                % SHA256_DIGEST_REGEX))
    op.create_check_constraint(
        "ck_ruleset_versions_lifecycle_version_non_negative", "ruleset_versions",
        sa.text("lifecycle_version >= 0"))
    op.create_check_constraint(
        "ck_ruleset_versions_frozen_pins_artifact", "ruleset_versions",
        sa.text("status <> 'FROZEN' OR ("
                " ruleset_content_hash IS NOT NULL"
                " AND approval_list_hash IS NOT NULL"
                " AND artifact_relative_path IS NOT NULL"
                " AND frozen_by IS NOT NULL AND frozen_at IS NOT NULL)"))
    op.create_check_constraint(
        "ck_ruleset_versions_retired_records_reason", "ruleset_versions",
        sa.text("status <> 'RETIRED' OR ("
                " retired_by IS NOT NULL AND retired_at IS NOT NULL"
                " AND retirement_reason IS NOT NULL"
                " AND length(trim(retirement_reason)) > 0)"))
    op.create_check_constraint(
        "ck_ruleset_versions_artifact_path_relative", "ruleset_versions",
        sa.text("artifact_relative_path IS NULL OR"
                " artifact_relative_path !~ '(^/)|(^[A-Za-z]:)|(\\.\\.)|(\\\\)'"))

    # -- ruleset_rules: pin the member's content hash ---------------------
    op.add_column("ruleset_rules", sa.Column(
        "member_content_hash", sa.String(length=80), nullable=True))
    op.add_column("ruleset_rules", sa.Column(
        "rule_family_id", _uuid(), nullable=True))
    op.add_column("ruleset_rules", sa.Column(
        "rule_version", sa.Integer(), nullable=True))
    op.add_column("ruleset_rules", sa.Column(
        "added_by", sa.String(length=256), nullable=True))
    op.add_column("ruleset_rules", sa.Column(
        "added_at", _timestamptz(), nullable=False, server_default=sa.text("now()")))
    op.create_check_constraint(
        "ck_ruleset_rules_member_hash_format", "ruleset_rules",
        sa.text("member_content_hash IS NULL OR member_content_hash ~ '%s'"
                % SHA256_DIGEST_REGEX))

    # -- rule_lifecycle_events -------------------------------------------
    op.create_table(
        "rule_lifecycle_events",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("rule_id", _uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=256), nullable=False),
        sa.Column("actor_role", sa.String(length=48), nullable=False),
        sa.Column("occurred_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=80), nullable=False),
        sa.Column("validation_result_hash", sa.String(length=80), nullable=True),
        sa.Column("audit_event_id", _uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["rule_id"], ["computable_rules.id"],
            name="fk_rule_lifecycle_events_rule_id_computable_rules",
            ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["audit_event_id"], ["audit_events.id"],
            name="fk_rule_lifecycle_events_audit_event_id_audit_events",
            ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_rule_lifecycle_events"),
        sa.CheckConstraint("to_status IN (%s)" % RULE_STATUSES,
                           name="ck_rule_lifecycle_events_to_status_enum"),
        sa.CheckConstraint("from_status IS NULL OR from_status IN (%s)"
                           % RULE_STATUSES,
                           name="ck_rule_lifecycle_events_from_status_enum"),
        sa.CheckConstraint("length(trim(actor)) > 0",
                           name="ck_rule_lifecycle_events_actor_not_blank"),
        sa.CheckConstraint("content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_rule_lifecycle_events_content_hash_format"),
    )
    op.create_index("ix_rule_lifecycle_events_rule_id", "rule_lifecycle_events",
                    ["rule_id"], unique=False)

    # -- ruleset_builds ---------------------------------------------------
    op.create_table(
        "ruleset_builds",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("ruleset_id", _uuid(), nullable=False),
        sa.Column("started_at", _timestamptz(), nullable=False),
        sa.Column("completed_at", _timestamptz(), nullable=False),
        sa.Column("built_by", sa.String(length=256), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("manifest_hash", sa.String(length=80), nullable=True),
        sa.Column("ruleset_content_hash", sa.String(length=80), nullable=True),
        sa.Column("member_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("issue_codes", _jsonb(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("artifact_relative_path", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(
            ["ruleset_id"], ["ruleset_versions.id"],
            name="fk_ruleset_builds_ruleset_id_ruleset_versions",
            ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_ruleset_builds"),
        sa.CheckConstraint("outcome IN (%s)" % BUILD_OUTCOMES,
                           name="ck_ruleset_builds_outcome_enum"),
        sa.CheckConstraint("completed_at >= started_at",
                           name="ck_ruleset_builds_completed_after_started"),
        # A successful build produced an artifact; a refused one did not.
        sa.CheckConstraint(
            "outcome <> 'SUCCEEDED' OR (manifest_hash IS NOT NULL"
            " AND ruleset_content_hash IS NOT NULL"
            " AND artifact_relative_path IS NOT NULL AND member_count > 0)",
            name="ck_ruleset_builds_succeeded_has_artifact"),
    )
    op.create_index("ix_ruleset_builds_ruleset_id", "ruleset_builds",
                    ["ruleset_id"], unique=False)

    # -- ruleset_approvals ------------------------------------------------
    op.create_table(
        "ruleset_approvals",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("ruleset_id", _uuid(), nullable=False),
        sa.Column("rule_id", _uuid(), nullable=False),
        sa.Column("rule_family_id", _uuid(), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("rule_content_hash", sa.String(length=80), nullable=False),
        sa.Column("approval_envelope_hash", sa.String(length=80), nullable=False),
        sa.Column("curation_revision_id", sa.String(length=128), nullable=False),
        sa.Column("curation_revision_hash", sa.String(length=80), nullable=False),
        sa.Column("created_by", sa.String(length=256), nullable=False),
        sa.Column("reviewed_by", sa.String(length=256), nullable=False),
        sa.Column("approved_by", sa.String(length=256), nullable=False),
        sa.Column("validated_by", sa.String(length=256), nullable=False),
        sa.Column("validated_at", _timestamptz(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ruleset_id"], ["ruleset_versions.id"],
            name="fk_ruleset_approvals_ruleset_id_ruleset_versions",
            ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["rule_id"], ["computable_rules.id"],
            name="fk_ruleset_approvals_rule_id_computable_rules",
            ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_ruleset_approvals"),
        sa.UniqueConstraint("ruleset_id", "rule_id",
                            name="uq_ruleset_approvals_ruleset_rule"),
        # Separation of duties, on the row, without a join.
        sa.CheckConstraint(
            "lower(btrim(created_by)) <> lower(btrim(reviewed_by))",
            name="ck_ruleset_approvals_reviewer_is_not_author"),
        sa.CheckConstraint(
            "lower(btrim(created_by)) <> lower(btrim(approved_by))",
            name="ck_ruleset_approvals_approver_is_not_author"),
        sa.CheckConstraint(
            "lower(btrim(created_by)) <> lower(btrim(validated_by))",
            name="ck_ruleset_approvals_validator_is_not_author"),
        sa.CheckConstraint("rule_content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_ruleset_approvals_rule_hash_format"),
        sa.CheckConstraint("approval_envelope_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_ruleset_approvals_envelope_hash_format"),
    )
    op.create_index("ix_ruleset_approvals_rule_id", "ruleset_approvals",
                    ["rule_id"], unique=False)

    # -- functions and triggers -------------------------------------------
    op.execute(_LOCK_KEY_FUNCTION)
    op.execute(_RULE_GUARD_FUNCTION)
    op.execute(_RULE_GUARD_TRIGGER)
    op.execute(_RULESET_GUARD_FUNCTION)
    op.execute(_RULESET_GUARD_TRIGGER)
    op.execute(_MEMBERSHIP_FUNCTION)
    op.execute(_MEMBERSHIP_TRIGGER)
    op.execute(_APPEND_ONLY_FUNCTION)
    op.execute(_BUILDS_APPEND_ONLY_TRIGGER)
    op.execute(_APPROVALS_APPEND_ONLY_TRIGGER)
    op.execute(_LIFECYCLE_APPEND_ONLY_TRIGGER)

    # -- audit_events: widen the action list ------------------------------
    op.drop_constraint("ck_audit_events_action_enum", "audit_events",
                       type_="check")
    op.create_check_constraint(
        "ck_audit_events_action_enum", "audit_events",
        sa.text("action IN (%s)" % AUDIT_ACTIONS_0008))


def downgrade() -> None:
    """Drop exactly the WP-11 objects, children before parents."""
    op.execute(_DOWNGRADE_GUARD)

    op.execute("DROP TRIGGER IF EXISTS trg_rule_lifecycle_events_append_only"
               " ON rule_lifecycle_events")
    op.execute("DROP TRIGGER IF EXISTS trg_ruleset_approvals_append_only"
               " ON ruleset_approvals")
    op.execute("DROP TRIGGER IF EXISTS trg_ruleset_builds_append_only"
               " ON ruleset_builds")
    op.execute("DROP FUNCTION IF EXISTS pgx_rule_record_append_only()")
    op.execute("DROP TRIGGER IF EXISTS trg_ruleset_rules_guarded ON ruleset_rules")
    op.execute("DROP FUNCTION IF EXISTS pgx_ruleset_rules_guarded()")
    op.execute("DROP TRIGGER IF EXISTS trg_ruleset_versions_guarded"
               " ON ruleset_versions")
    op.execute("DROP FUNCTION IF EXISTS pgx_ruleset_versions_guarded()")
    op.execute("DROP TRIGGER IF EXISTS trg_computable_rules_guarded"
               " ON computable_rules")
    op.execute("DROP FUNCTION IF EXISTS pgx_computable_rules_guarded()")
    op.execute("DROP FUNCTION IF EXISTS pgx_ruleset_lock_key(uuid)")

    op.drop_index("ix_ruleset_approvals_rule_id", table_name="ruleset_approvals")
    op.drop_table("ruleset_approvals")
    op.drop_index("ix_ruleset_builds_ruleset_id", table_name="ruleset_builds")
    op.drop_table("ruleset_builds")
    op.drop_index("ix_rule_lifecycle_events_rule_id",
                  table_name="rule_lifecycle_events")
    op.drop_table("rule_lifecycle_events")

    op.drop_constraint("ck_ruleset_rules_member_hash_format", "ruleset_rules",
                       type_="check")
    op.drop_column("ruleset_rules", "added_at")
    op.drop_column("ruleset_rules", "added_by")
    op.drop_column("ruleset_rules", "rule_version")
    op.drop_column("ruleset_rules", "rule_family_id")
    op.drop_column("ruleset_rules", "member_content_hash")

    # Written out one statement per line rather than looped. The schema
    # renderer reads this file's AST to emit executable DDL, and a loop
    # variable is not something it can evaluate - but the better reason is
    # that a reader looking for whether a column is dropped should find it
    # on a line, the way 0001 through 0007 write theirs.
    op.drop_constraint("ck_ruleset_versions_artifact_path_relative", "ruleset_versions",
                       type_="check")
    op.drop_constraint("ck_ruleset_versions_retired_records_reason", "ruleset_versions",
                       type_="check")
    op.drop_constraint("ck_ruleset_versions_frozen_pins_artifact", "ruleset_versions",
                       type_="check")
    op.drop_constraint("ck_ruleset_versions_lifecycle_version_non_negative", "ruleset_versions",
                       type_="check")
    op.drop_constraint("ck_ruleset_versions_content_hash_format", "ruleset_versions",
                       type_="check")
    op.drop_column("ruleset_versions", "updated_at")
    op.drop_column("ruleset_versions", "retirement_reason")
    op.drop_column("ruleset_versions", "retired_at")
    op.drop_column("ruleset_versions", "retired_by")
    op.drop_column("ruleset_versions", "frozen_at")
    op.drop_column("ruleset_versions", "frozen_by")
    op.drop_column("ruleset_versions", "created_by")
    op.drop_column("ruleset_versions", "artifact_relative_path")
    op.drop_column("ruleset_versions", "approval_list_hash")
    op.drop_column("ruleset_versions", "source_policy_content_hash")
    op.drop_column("ruleset_versions", "source_policy_version")
    op.drop_column("ruleset_versions", "protocol_content_hash")
    op.drop_column("ruleset_versions", "protocol_version")
    op.drop_column("ruleset_versions", "evidence_build_content_hash")
    op.drop_column("ruleset_versions", "evidence_build_key")
    op.drop_column("ruleset_versions", "canonical_build_content_hash")
    op.drop_column("ruleset_versions", "canonical_build_key")
    op.drop_column("ruleset_versions", "dataset_public_id")
    op.drop_column("ruleset_versions", "lifecycle_version")
    op.drop_column("ruleset_versions", "ruleset_schema_version")
    op.drop_column("ruleset_versions", "ruleset_content_hash")

    op.drop_index("ix_computable_rules_axis", table_name="computable_rules")
    op.drop_index("ix_computable_rules_content_hash",
                  table_name="computable_rules")
    op.drop_index("ix_computable_rules_family", table_name="computable_rules")
    op.drop_constraint("ck_computable_rules_not_own_predecessor",
                       "computable_rules", type_="check")
    op.drop_constraint("ck_computable_rules_validator_is_not_author",
                       "computable_rules", type_="check")
    op.drop_constraint("ck_computable_rules_deprecated_records_reason",
                       "computable_rules", type_="check")
    op.drop_constraint("ck_computable_rules_validated_records_validator",
                       "computable_rules", type_="check")
    op.drop_constraint("ck_computable_rules_validated_pins_provenance",
                       "computable_rules", type_="check")
    op.drop_constraint("ck_computable_rules_curated_pins_revision",
                       "computable_rules", type_="check")
    op.drop_constraint("ck_computable_rules_outcome_is_authorable",
                       "computable_rules", type_="check")
    op.drop_constraint("ck_computable_rules_lifecycle_version_non_negative",
                       "computable_rules", type_="check")
    op.drop_constraint("ck_computable_rules_content_hash_format",
                       "computable_rules", type_="check")
    op.drop_constraint("uq_computable_rules_family_version",
                       "computable_rules", type_="unique")
    op.drop_constraint(
        "fk_computable_rules_supersedes_rule_id_computable_rules",
        "computable_rules", type_="foreignkey")
    op.drop_column("computable_rules", "updated_at")
    op.drop_column("computable_rules", "deprecation_reason")
    op.drop_column("computable_rules", "deprecated_at")
    op.drop_column("computable_rules", "deprecated_by")
    op.drop_column("computable_rules", "validated_at")
    op.drop_column("computable_rules", "validated_by")
    op.drop_column("computable_rules", "validation_result_hash")
    op.drop_column("computable_rules", "source_policy_content_hash")
    op.drop_column("computable_rules", "source_policy_version")
    op.drop_column("computable_rules", "evidence_build_content_hash")
    op.drop_column("computable_rules", "evidence_build_key")
    op.drop_column("computable_rules", "canonical_build_content_hash")
    op.drop_column("computable_rules", "canonical_build_key")
    op.drop_column("computable_rules", "dataset_public_id")
    op.drop_column("computable_rules", "protocol_content_hash")
    op.drop_column("computable_rules", "protocol_version")
    op.drop_column("computable_rules", "approval_envelope_hash")
    op.drop_column("computable_rules", "curation_revision_hash")
    op.drop_column("computable_rules", "curation_revision_id")
    op.drop_column("computable_rules", "curation_work_item_id")
    op.drop_column("computable_rules", "drug_canonical_key")
    op.drop_column("computable_rules", "gene_canonical_key")
    op.drop_column("computable_rules", "lifecycle_version")
    op.drop_column("computable_rules", "content_hash")
    op.drop_column("computable_rules", "condition_schema_version")
    op.drop_column("computable_rules", "rule_schema_version")
    op.drop_column("computable_rules", "supersedes_rule_id")
    op.drop_column("computable_rules", "rule_family_id")

    op.drop_constraint("ck_audit_events_action_enum", "audit_events",
                       type_="check")
    op.create_check_constraint(
        "ck_audit_events_action_enum", "audit_events",
        sa.text("action IN (%s)" % AUDIT_ACTIONS_0007))
