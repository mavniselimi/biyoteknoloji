# -*- coding: utf-8 -*-
"""WP-14 deterministic assessments.

Revision ID: 0009_wp14_assessments
Revises: 0008_wp11_rules_and_rulesets
Create Date: 2026-09-03

Hand-written and reviewed, not autogenerate output. ``0001`` through ``0008``
are not rewritten: this revision creates five new tables beside them and
widens exactly one existing constraint - the audit action list.

**Why the tables are new rather than an extension.** ``0001`` deliberately did
not create ``assessments`` or ``assessment_findings``; its docstring says so,
and the reason it gives is the reason they arrive now: an assessment implies a
release identity, and the release registry did not exist yet. It does now, so
the foreign keys those tables need are real.

**Which layer enforces which invariant.** Stated here because "enforced" with
no named enforcer is how an invariant quietly stops holding.

| Invariant | Enforced by |
|---|---|
| complete release metadata (`SAFETY-INV-007`) | `NOT NULL` on every pinned column |
| the pinned release still exists | `fk_assessments_release_id_release_bundles` `ON DELETE RESTRICT` |
| `NO_ACTIVE_ATTENTION` only with `FULL` coverage (`SAFETY-INV-001`) | `ck_*_no_active_attention_requires_full_coverage`, on assessment and medication rows |
| `FULL` coverage is never `NOT_ASSESSED` | `ck_assessments_full_coverage_is_not_unassessed` |
| non-`FULL` coverage carries a reason | `ck_*_non_full_coverage_has_reasons` |
| `FULL` coverage carries no reason | `ck_*_full_coverage_has_no_reason` |
| a finding is never `NOT_ASSESSED` | `ck_assessment_findings_attention_is_calculated` |
| every finding cites evidence (`SAFETY-INV-006`) | `trg_assessment_findings_require_evidence` (deferred constraint trigger) |
| a conflicted axis names its conflict | `ck_assessment_axes_conflict_names_its_references` |
| `PILOT` is not storable | `ck_assessments_mode_enum` |
| hashes have canonical format | `ck_*_hash_format` |
| one finding identity per assessment | `uq_assessment_findings_assessment_finding_identity` |
| every child row belongs to its parent's assessment | `trg_*_same_assessment` |
| assessments and children are immutable | `trg_*_append_only` |
| a cited evidence record cannot be deleted | `fk_assessment_finding_evidence_evidence_id` `ON DELETE RESTRICT` |
| a cited rule cannot be deleted | `fk_assessment_findings_rule_id_computable_rules` `ON DELETE RESTRICT` |

The evidence requirement is a **deferred** constraint trigger rather than a
row check, because a finding and its evidence links are inserted in the same
transaction and the check is only meaningful once both are present. Deferring
it to commit time means the invariant holds over the transaction rather than
over statement order.

**Immutability.** Every one of the five tables gets a trigger refusing
``UPDATE`` and ``DELETE``. A completed assessment records what a versioned
system calculated at a moment; editing one would make the audit trail describe
a calculation that never happened, and deleting one would remove the only
evidence that a result was ever issued. ``ON DELETE CASCADE`` on the child
foreign keys is therefore unreachable in practice: the parent cannot be
deleted either. It is declared so that the *intent* is unambiguous if a future
migration ever adds an explicit, audited destruction path.

**Documented downgrade refusal.** ``downgrade()`` refuses, in a single
transaction that changes nothing, when the database holds any assessment. A
stored assessment may have been issued to somebody; dropping the table would
destroy the only record of what was calculated and against which versions.
A database holding no assessment downgrades cleanly. Deliberately destroying
history requires exporting it and then removing the rows explicitly - this
migration will not do it silently.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_wp14_assessments"
down_revision: Union[str, None] = "0008_wp11_rules_and_rulesets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SHA256_DIGEST_REGEX = r"^sha256:[0-9a-f]{64}$"

#: P0 modes. PILOT is absent, not merely refused at runtime: a row that could
#: express a PILOT assessment would outlive the check that refuses one.
ASSESSMENT_MODES = "'DEMO', 'VALIDATION'"
INPUT_KINDS = ("'SYNTHETIC_PHENOTYPE_PROFILE', "
               "'PROTOCOL_DEFINED_PHENOTYPE_PROFILE', 'PUBLIC_DEMO_PROFILE', "
               "'VERSIONED_VALIDATION_CASE', 'MEDICATION_NAME_LIST'")
COVERAGE_STATUSES = ("'FULL', 'PARTIAL', 'INSUFFICIENT', 'UNSUPPORTED_DRUG', "
                     "'UNSUPPORTED_PHENOTYPE', 'SOURCE_CONFLICT'")
ATTENTION_LEVELS = ("'NOT_ASSESSED', 'NO_ACTIVE_ATTENTION', 'LOW', 'MEDIUM', "
                    "'HIGH'")
CALCULATED_ATTENTION = "'NO_ACTIVE_ATTENTION', 'LOW', 'MEDIUM', 'HIGH'"
RULE_PHENOTYPES = "'POOR', 'INTERMEDIATE', 'NORMAL', 'RAPID', 'ULTRARAPID'"
ALL_PHENOTYPES = RULE_PHENOTYPES + ", 'INDETERMINATE'"

AUDIT_ACTIONS_0008 = (
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
    "'RULESET_RETIRED'")

AUDIT_ACTIONS_0009 = (AUDIT_ACTIONS_0008
                      + ", 'ASSESSMENT_COMPLETED', 'ASSESSMENT_REFUSED'")

ASSESSMENT_TABLES = ("assessments", "assessment_medications",
                     "assessment_axes", "assessment_findings",
                     "assessment_finding_evidence")

APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION pgx_assessment_append_only()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'assessment records are immutable: % on % is refused. A completed '
        'assessment records what a versioned system calculated at a moment; '
        'editing one would make the audit trail describe a calculation that '
        'never happened.',
        TG_OP, TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;
"""

#: Every child row must belong to the same assessment as its parent. A join
#: across two parents cannot be expressed as a row CHECK, so it is a trigger.
SAME_ASSESSMENT_FUNCTION = """
CREATE OR REPLACE FUNCTION pgx_assessment_child_matches_parent()
RETURNS trigger AS $$
DECLARE
    parent_assessment uuid;
BEGIN
    SELECT assessment_id INTO parent_assessment
      FROM assessment_medications
     WHERE id = NEW.medication_id;
    IF parent_assessment IS NULL THEN
        RAISE EXCEPTION
            'medication % does not exist; a child row cannot reference a '
            'medication that is not part of any assessment', NEW.medication_id;
    END IF;
    IF parent_assessment <> NEW.assessment_id THEN
        RAISE EXCEPTION
            'row claims assessment % but its medication belongs to %; child '
            'rows of one assessment must all name that assessment',
            NEW.assessment_id, parent_assessment;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

#: SAFETY-INV-006 across two tables, checked at commit so the insert order
#: within one transaction does not matter.
REQUIRE_EVIDENCE_FUNCTION = """
CREATE OR REPLACE FUNCTION pgx_assessment_finding_requires_evidence()
RETURNS trigger AS $$
DECLARE
    evidence_count integer;
BEGIN
    SELECT count(*) INTO evidence_count
      FROM assessment_finding_evidence
     WHERE finding_id = NEW.id;
    IF evidence_count = 0 THEN
        RAISE EXCEPTION
            'finding % cites no evidence record. Every calculated finding '
            'must carry traceable evidence (SAFETY-INV-006): a conclusion '
            'whose evidence cannot be retrieved is not one anybody can check.',
            NEW.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def _digest_check(column: str) -> str:
    return "%s ~ '%s'" % (column, SHA256_DIGEST_REGEX)


def upgrade() -> None:
    # -- assessments ----------------------------------------------------
    op.create_table(
        "assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("release_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("input_kind", sa.String(64), nullable=False),
        sa.Column("case_id", sa.String(128), nullable=True),
        sa.Column("actor", sa.String(256), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("input_hash", sa.String(80), nullable=False),
        sa.Column("output_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("output_hash", sa.String(80), nullable=False),
        sa.Column("overall_coverage", sa.String(32), nullable=False),
        sa.Column("overall_attention", sa.String(32), nullable=False),
        # The pinned version set. Every one NOT NULL: SAFETY-INV-007 is a
        # constraint, and a nullable column would make it a convention.
        sa.Column("release_public_id", sa.String(128), nullable=False),
        sa.Column("release_manifest_hash", sa.String(80), nullable=False),
        sa.Column("active_pointer_generation", sa.Integer, nullable=False),
        sa.Column("software_version_id", postgresql.UUID(as_uuid=True),
                  nullable=False),
        sa.Column("software_version", sa.String(128), nullable=False),
        sa.Column("software_source_tree_hash", sa.String(80), nullable=False),
        sa.Column("dataset_version_id", postgresql.UUID(as_uuid=True),
                  nullable=False),
        sa.Column("dataset_public_id", sa.String(128), nullable=False),
        sa.Column("canonical_build_content_hash", sa.String(80),
                  nullable=False),
        sa.Column("ruleset_version_id", postgresql.UUID(as_uuid=True),
                  nullable=False),
        sa.Column("ruleset_public_id", sa.String(128), nullable=False),
        sa.Column("ruleset_content_hash", sa.String(80), nullable=False),
        sa.Column("evidence_build_key", sa.String(256), nullable=False),
        sa.Column("evidence_build_content_hash", sa.String(80),
                  nullable=False),
        sa.Column("coverage_manifest_hash", sa.String(80), nullable=False),
        sa.Column("protocol_version", sa.String(128), nullable=False),
        sa.Column("protocol_content_hash", sa.String(80), nullable=False),
        sa.Column("source_policy_version", sa.String(128), nullable=False),
        sa.Column("source_policy_content_hash", sa.String(80), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["release_id"], ["release_bundles.id"], ondelete="RESTRICT",
            name="fk_assessments_release_id_release_bundles"),
        sa.ForeignKeyConstraint(
            ["software_version_id"], ["software_versions.id"],
            ondelete="RESTRICT",
            name="fk_assessments_software_version_id_software_versions"),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"],
            ondelete="RESTRICT",
            name="fk_assessments_dataset_version_id_dataset_versions"),
        sa.ForeignKeyConstraint(
            ["ruleset_version_id"], ["ruleset_versions.id"],
            ondelete="RESTRICT",
            name="fk_assessments_ruleset_version_id_ruleset_versions"),
        sa.CheckConstraint("mode IN (%s)" % ASSESSMENT_MODES,
                           name="ck_assessments_mode_enum"),
        sa.CheckConstraint("input_kind IN (%s)" % INPUT_KINDS,
                           name="ck_assessments_input_kind_enum"),
        sa.CheckConstraint("overall_coverage IN (%s)" % COVERAGE_STATUSES,
                           name="ck_assessments_overall_coverage_enum"),
        sa.CheckConstraint("overall_attention IN (%s)" % ATTENTION_LEVELS,
                           name="ck_assessments_overall_attention_enum"),
        sa.CheckConstraint(
            "overall_attention <> 'NO_ACTIVE_ATTENTION' "
            "OR overall_coverage = 'FULL'",
            name="ck_assessments_no_active_attention_requires_full_coverage"),
        sa.CheckConstraint(
            "overall_coverage <> 'FULL' OR overall_attention <> 'NOT_ASSESSED'",
            name="ck_assessments_full_coverage_is_not_unassessed"),
        sa.CheckConstraint(_digest_check("input_hash"),
                           name="ck_assessments_input_hash_format"),
        sa.CheckConstraint(_digest_check("output_hash"),
                           name="ck_assessments_output_hash_format"),
        sa.CheckConstraint(_digest_check("release_manifest_hash"),
                           name="ck_assessments_release_manifest_hash_format"),
        sa.CheckConstraint(_digest_check("software_source_tree_hash"),
                           name="ck_assessments_software_hash_format"),
        sa.CheckConstraint(_digest_check("canonical_build_content_hash"),
                           name="ck_assessments_canonical_hash_format"),
        sa.CheckConstraint(_digest_check("ruleset_content_hash"),
                           name="ck_assessments_ruleset_hash_format"),
        sa.CheckConstraint(_digest_check("evidence_build_content_hash"),
                           name="ck_assessments_evidence_hash_format"),
        sa.CheckConstraint(_digest_check("coverage_manifest_hash"),
                           name="ck_assessments_coverage_manifest_hash_format"),
        sa.CheckConstraint(_digest_check("protocol_content_hash"),
                           name="ck_assessments_protocol_hash_format"),
        sa.CheckConstraint(_digest_check("source_policy_content_hash"),
                           name="ck_assessments_source_policy_hash_format"),
        sa.CheckConstraint("active_pointer_generation >= 0",
                           name="ck_assessments_pointer_generation_non_negative"),
        sa.CheckConstraint("length(btrim(actor)) > 0",
                           name="ck_assessments_actor_not_blank"),
    )
    op.create_index("ix_assessments_release_id", "assessments", ["release_id"])
    op.create_index("ix_assessments_output_hash", "assessments",
                    ["output_hash"])
    op.create_index("ix_assessments_input_hash", "assessments", ["input_hash"])

    # -- assessment_medications -----------------------------------------
    op.create_table(
        "assessment_medications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True),
                  nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("drug_canonical_key", sa.String(256), nullable=False),
        sa.Column("requested_value", sa.String(256), nullable=False),
        sa.Column("attention_level", sa.String(32), nullable=False),
        sa.Column("coverage_status", sa.String(32), nullable=False),
        sa.Column("coverage_reason_codes", postgresql.JSONB, nullable=False),
        sa.Column("axis_count", sa.Integer, nullable=False),
        sa.Column("conflicted_axis_count", sa.Integer, nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["assessments.id"], ondelete="CASCADE",
            name="fk_assessment_medications_assessment_id_assessments"),
        sa.UniqueConstraint("assessment_id", "drug_canonical_key",
                            name="uq_assessment_medications_assessment_drug"),
        sa.UniqueConstraint("assessment_id", "ordinal",
                            name="uq_assessment_medications_assessment_ordinal"),
        sa.CheckConstraint("attention_level IN (%s)" % ATTENTION_LEVELS,
                           name="ck_assessment_medications_attention_enum"),
        sa.CheckConstraint("coverage_status IN (%s)" % COVERAGE_STATUSES,
                           name="ck_assessment_medications_coverage_enum"),
        sa.CheckConstraint(
            "attention_level <> 'NO_ACTIVE_ATTENTION' "
            "OR coverage_status = 'FULL'",
            name="ck_assessment_medications_no_active_attention_requires_full"),
        sa.CheckConstraint(
            "coverage_status = 'FULL' "
            "OR jsonb_array_length(coverage_reason_codes) >= 1",
            name="ck_assessment_medications_non_full_coverage_has_reasons"),
        sa.CheckConstraint(
            "coverage_status <> 'FULL' "
            "OR jsonb_array_length(coverage_reason_codes) = 0",
            name="ck_assessment_medications_full_coverage_has_no_reason"),
        sa.CheckConstraint("ordinal >= 0",
                           name="ck_assessment_medications_ordinal_non_negative"),
        sa.CheckConstraint("axis_count >= 0",
                           name="ck_assessment_medications_axis_count_non_negative"),
    )
    op.create_index("ix_assessment_medications_assessment_id",
                    "assessment_medications", ["assessment_id"])

    # -- assessment_axes ------------------------------------------------
    op.create_table(
        "assessment_axes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True),
                  nullable=False),
        sa.Column("medication_id", postgresql.UUID(as_uuid=True),
                  nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("drug_canonical_key", sa.String(256), nullable=False),
        sa.Column("gene_canonical_key", sa.String(128), nullable=False),
        sa.Column("observed_phenotype", sa.String(32), nullable=True),
        sa.Column("observation_state", sa.String(32), nullable=False),
        sa.Column("coverage_status", sa.String(32), nullable=False),
        sa.Column("coverage_reason_codes", postgresql.JSONB, nullable=False),
        sa.Column("rule_references", postgresql.JSONB, nullable=False),
        sa.Column("evidence_references", postgresql.JSONB, nullable=False),
        sa.Column("conflict_references", postgresql.JSONB, nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["assessments.id"], ondelete="CASCADE",
            name="fk_assessment_axes_assessment_id_assessments"),
        sa.ForeignKeyConstraint(
            ["medication_id"], ["assessment_medications.id"],
            ondelete="CASCADE",
            name="fk_assessment_axes_medication_id_assessment_medications"),
        sa.UniqueConstraint("assessment_id", "drug_canonical_key",
                            "gene_canonical_key",
                            name="uq_assessment_axes_assessment_axis"),
        sa.CheckConstraint("coverage_status IN (%s)" % COVERAGE_STATUSES,
                           name="ck_assessment_axes_coverage_enum"),
        sa.CheckConstraint(
            "coverage_status = 'FULL' "
            "OR jsonb_array_length(coverage_reason_codes) >= 1",
            name="ck_assessment_axes_non_full_coverage_has_reasons"),
        sa.CheckConstraint(
            "coverage_status <> 'FULL' "
            "OR jsonb_array_length(coverage_reason_codes) = 0",
            name="ck_assessment_axes_full_coverage_has_no_reason"),
        sa.CheckConstraint(
            "coverage_status <> 'SOURCE_CONFLICT' "
            "OR jsonb_array_length(conflict_references) >= 1",
            name="ck_assessment_axes_conflict_names_its_references"),
        sa.CheckConstraint(
            "observed_phenotype IS NULL "
            "OR observed_phenotype IN (%s)" % ALL_PHENOTYPES,
            name="ck_assessment_axes_phenotype_enum"),
        sa.CheckConstraint("ordinal >= 0",
                           name="ck_assessment_axes_ordinal_non_negative"),
    )
    op.create_index("ix_assessment_axes_assessment_id", "assessment_axes",
                    ["assessment_id"])
    op.create_index("ix_assessment_axes_medication_id", "assessment_axes",
                    ["medication_id"])

    # -- assessment_findings --------------------------------------------
    op.create_table(
        "assessment_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True),
                  nullable=False),
        sa.Column("medication_id", postgresql.UUID(as_uuid=True),
                  nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("drug_canonical_key", sa.String(256), nullable=False),
        sa.Column("gene_canonical_key", sa.String(128), nullable=False),
        sa.Column("phenotype", sa.String(32), nullable=False),
        sa.Column("attention_level", sa.String(32), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_family_id", sa.String(128), nullable=False),
        sa.Column("rule_version", sa.Integer, nullable=False),
        sa.Column("rule_content_hash", sa.String(80), nullable=False),
        sa.Column("rationale_reference", sa.String(512), nullable=False),
        sa.Column("curation_revision_id", sa.String(128), nullable=False),
        sa.Column("curation_revision_hash", sa.String(80), nullable=False),
        # Nullable, and that is the honest shape: the governed rule outcome
        # carries an attention level and a rationale reference and no
        # scientific codes at all. NOT NULL here would have forced every row
        # to invent one.
        sa.Column("effect_code", sa.String(128), nullable=True),
        sa.Column("explanation_code", sa.String(128), nullable=True),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["assessments.id"], ondelete="CASCADE",
            name="fk_assessment_findings_assessment_id_assessments"),
        sa.ForeignKeyConstraint(
            ["medication_id"], ["assessment_medications.id"],
            ondelete="CASCADE",
            name="fk_assessment_findings_medication_id_assessment_medications"),
        sa.ForeignKeyConstraint(
            ["rule_id"], ["computable_rules.id"], ondelete="RESTRICT",
            name="fk_assessment_findings_rule_id_computable_rules"),
        sa.UniqueConstraint(
            "assessment_id", "drug_canonical_key", "gene_canonical_key",
            "phenotype",
            name="uq_assessment_findings_assessment_finding_identity"),
        sa.CheckConstraint("attention_level IN (%s)" % CALCULATED_ATTENTION,
                           name="ck_assessment_findings_attention_is_calculated"),
        sa.CheckConstraint("phenotype IN (%s)" % RULE_PHENOTYPES,
                           name="ck_assessment_findings_phenotype_enum"),
        sa.CheckConstraint(_digest_check("rule_content_hash"),
                           name="ck_assessment_findings_rule_hash_format"),
        sa.CheckConstraint(_digest_check("curation_revision_hash"),
                           name="ck_assessment_findings_revision_hash_format"),
        sa.CheckConstraint("rule_version >= 1",
                           name="ck_assessment_findings_rule_version_positive"),
        sa.CheckConstraint("btrim(rationale_reference) <> ''",
                           name="ck_assessment_findings_rationale_present"),
        sa.CheckConstraint("effect_code IS NULL OR btrim(effect_code) <> ''",
                           name="ck_assessment_findings_effect_code_not_blank"),
        sa.CheckConstraint(
            "explanation_code IS NULL OR btrim(explanation_code) <> ''",
            name="ck_assessment_findings_explanation_code_not_blank"),
        sa.CheckConstraint("ordinal >= 0",
                           name="ck_assessment_findings_ordinal_non_negative"),
    )
    op.create_index("ix_assessment_findings_assessment_id",
                    "assessment_findings", ["assessment_id"])
    op.create_index("ix_assessment_findings_rule_id", "assessment_findings",
                    ["rule_id"])

    # -- assessment_finding_evidence ------------------------------------
    op.create_table(
        "assessment_finding_evidence",
        sa.Column("finding_id", postgresql.UUID(as_uuid=True),
                  primary_key=True),
        sa.Column("evidence_record_id", postgresql.UUID(as_uuid=True),
                  primary_key=True),
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True),
                  nullable=False),
        sa.ForeignKeyConstraint(
            ["finding_id"], ["assessment_findings.id"], ondelete="CASCADE",
            name="fk_assessment_finding_evidence_finding_id_assessment_findings"),
        sa.ForeignKeyConstraint(
            ["evidence_record_id"], ["evidence_records.id"],
            ondelete="RESTRICT",
            name="fk_assessment_finding_evidence_evidence_id"),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["assessments.id"], ondelete="CASCADE",
            name="fk_assessment_finding_evidence_assessment_id_assessments"),
    )
    op.create_index("ix_assessment_finding_evidence_assessment_id",
                    "assessment_finding_evidence", ["assessment_id"])
    op.create_index("ix_assessment_finding_evidence_evidence_record_id",
                    "assessment_finding_evidence", ["evidence_record_id"])

    # -- cross-row invariants -------------------------------------------
    op.execute(SAME_ASSESSMENT_FUNCTION)
    for table in ("assessment_axes", "assessment_findings"):
        op.execute(
            "CREATE TRIGGER trg_%s_same_assessment "
            "BEFORE INSERT ON %s FOR EACH ROW "
            "EXECUTE FUNCTION pgx_assessment_child_matches_parent();"
            % (table, table))

    op.execute(REQUIRE_EVIDENCE_FUNCTION)
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_assessment_findings_require_evidence "
        "AFTER INSERT ON assessment_findings "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION pgx_assessment_finding_requires_evidence();")

    # -- immutability ---------------------------------------------------
    op.execute(APPEND_ONLY_FUNCTION)
    for table in ASSESSMENT_TABLES:
        op.execute(
            "CREATE TRIGGER trg_%s_append_only "
            "BEFORE UPDATE OR DELETE ON %s FOR EACH ROW "
            "EXECUTE FUNCTION pgx_assessment_append_only();" % (table, table))

    # -- widen the audit vocabulary -------------------------------------
    op.drop_constraint("ck_audit_events_action_enum", "audit_events",
                       type_="check")
    op.create_check_constraint(
        "ck_audit_events_action_enum", "audit_events",
        sa.text("action IN (%s)" % AUDIT_ACTIONS_0009))


def downgrade() -> None:
    # Refuse before touching anything. One transaction, no partial drop.
    connection = op.get_bind()
    stored = connection.execute(
        sa.text("SELECT count(*) FROM assessments")).scalar_one()
    if stored:
        raise RuntimeError(
            "refusing to downgrade: %d assessment(s) are stored. Each records "
            "what a versioned system calculated and against which artifacts, "
            "and may have been issued to somebody; dropping these tables would "
            "destroy the only evidence that a result was ever produced. Export "
            "the assessments and remove the rows explicitly if that is really "
            "intended - this migration will not do it silently." % stored)

    op.drop_constraint("ck_audit_events_action_enum", "audit_events",
                       type_="check")
    op.create_check_constraint(
        "ck_audit_events_action_enum", "audit_events",
        sa.text("action IN (%s)" % AUDIT_ACTIONS_0008))

    for table in ASSESSMENT_TABLES:
        op.execute("DROP TRIGGER IF EXISTS trg_%s_append_only ON %s;"
                   % (table, table))
    op.execute("DROP FUNCTION IF EXISTS pgx_assessment_append_only();")

    op.execute("DROP TRIGGER IF EXISTS "
               "trg_assessment_findings_require_evidence "
               "ON assessment_findings;")
    op.execute("DROP FUNCTION IF EXISTS "
               "pgx_assessment_finding_requires_evidence();")

    for table in ("assessment_axes", "assessment_findings"):
        op.execute("DROP TRIGGER IF EXISTS trg_%s_same_assessment ON %s;"
                   % (table, table))
    op.execute("DROP FUNCTION IF EXISTS pgx_assessment_child_matches_parent();")

    op.drop_index("ix_assessment_finding_evidence_evidence_record_id",
                  table_name="assessment_finding_evidence")
    op.drop_index("ix_assessment_finding_evidence_assessment_id",
                  table_name="assessment_finding_evidence")
    op.drop_table("assessment_finding_evidence")

    op.drop_index("ix_assessment_findings_rule_id",
                  table_name="assessment_findings")
    op.drop_index("ix_assessment_findings_assessment_id",
                  table_name="assessment_findings")
    op.drop_table("assessment_findings")

    op.drop_index("ix_assessment_axes_medication_id",
                  table_name="assessment_axes")
    op.drop_index("ix_assessment_axes_assessment_id",
                  table_name="assessment_axes")
    op.drop_table("assessment_axes")

    op.drop_index("ix_assessment_medications_assessment_id",
                  table_name="assessment_medications")
    op.drop_table("assessment_medications")

    op.drop_index("ix_assessments_input_hash", table_name="assessments")
    op.drop_index("ix_assessments_output_hash", table_name="assessments")
    op.drop_index("ix_assessments_release_id", table_name="assessments")
    op.drop_table("assessments")
