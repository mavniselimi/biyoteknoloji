# -*- coding: utf-8 -*-
"""WP-10 curation workflow: work items, revisions, reviews, adjudication.

Revision ID: 0007_wp10_curation_workflow
Revises: 0006_wp08_evidence_store
Create Date: 2026-09-03

Hand-written and reviewed, not autogenerate output. ``0001`` through ``0006``
are not rewritten: this revision adds tables, widens one check constraint on
``audit_events``, and adds triggers.

Scope - seven tables:

    curation_work_items, curation_revisions, curation_reviews,
    curation_adjudications, curation_provenance_verifications,
    curation_work_item_evidence_links, curation_role_assignments

plus four triggers and the ``audit_events`` action widening.

**Why the state machine is in the database.**
``curation_work_items.status`` is not a column the application may set freely.
``trg_curation_work_items_guarded`` refuses any ``UPDATE`` that moves a work
item along an edge the machine does not have, that changes its state without
advancing ``version``, or that touches a row in a terminal state at all. A
service is one process among several - a migration script, a psql session, a
future job - and "we always go through the service" is a claim about developer
behaviour rather than about the data. The same machine is written down three
times deliberately: in ``allowed_transitions()``, in the service, and here.

**Why revisions, reviews and adjudications have no UPDATE path.**
``trg_curation_revisions_immutable`` and its two siblings refuse every
``UPDATE`` and every ``DELETE``. Nothing in the application offers one either -
the repository ports have no update method - but a trigger is what makes the
guarantee survive somebody connecting with psql. A review that could be edited
after the fact is not a record of what a reviewer concluded; it is a record of
what somebody last wanted it to say.

**Why the author/reviewer separation is a check constraint.**
``ck_curation_reviews_reviewer_not_author`` compares ``reviewed_by`` with
``author_actor_id`` on the review row itself, case-insensitively. The reviewer
and the author are both stored on the review precisely so this is checkable
without a join: a constraint that had to join to ``curation_revisions`` could
be satisfied at insert time and then falsified by a later change elsewhere.
``curation_adjudications`` carries the same rule against both parties.

**Why there are no approval defaults.**
No column here defaults to an approved, verified or reviewed value.
``all_traces_verified`` has no server default, ``curation_role_assignments``
is created empty, and ``ck_curation_work_items_terminal_needs_revision``
requires that a CURATED or REJECTED work item names the revision that was
decided. A default would mean that a row inserted by a script that forgot a
column would carry a claim nobody made.

**Why role assignments start empty and are marked synthetic.**
``curation_role_assignments`` is created with no rows. This project has no
authenticated identities: WP-23 owns that, and until it exists there is nobody
to assign a role to. The table exists so the empty set is explicit and
queryable rather than implied by absence. ``ck_curation_role_assignments_synthetic_prefix`` requires that ``synthetic`` is true exactly when
``actor_id`` starts with ``TEST-``, so a test fixture cannot be mistaken for a
person and a person cannot be given a test actor's id.

**Why legacy values are namespaced in the database too.**
``trg_curation_work_items_legacy_namespaced`` requires every key of
``legacy_values`` to begin with ``legacy.``. It is a trigger rather than a
check constraint because PostgreSQL refuses a subquery inside ``CHECK`` and
"every key of this document" cannot be written without one; it fires on
``INSERT`` as well as ``UPDATE``, which is the operation that matters, since
the legacy import is a bulk insert. WP-08 removed these fields from
the evidence store because they were the old project's interpretations sitting
where evidence belonged. They come back here as visibly-unreviewed input, and
the prefix is what stops a later query for curated content from matching one.

``downgrade()`` drops exactly these objects, children before parents, drops
each trigger *and* its function, and restores ``0006``'s ``audit_events``
action list. Nothing from ``0001`` through ``0006`` is otherwise touched.

**Documented downgrade refusals.** The downgrade refuses, in a single
transaction that changes nothing, when the database holds a CURATED or REJECTED
work item, any review, or any adjudication. Those rows are the record of a
scientific decision by named people; dropping the tables holding them would
destroy the only evidence that the decision was made, and no migration should
do that on an operator's behalf. Every check runs before any drop, so a refusal
leaves the schema exactly as it was rather than half-dismantled. A database
holding only RAW legacy work items downgrades cleanly, because those assert
nothing.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_wp10_curation_workflow"
down_revision: Union[str, None] = "0006_wp08_evidence_store"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SHA256_DIGEST_REGEX = r"^sha256:[0-9a-f]{64}$"

#: The persisted states. Identical to WP-02's ``CurationStatus``: WP-09's
#: ``DRAFT`` is not a fourth state, it is what a revision's content is while
#: its work item is RAW.
WORK_ITEM_STATES = "'RAW', 'UNDER_REVIEW', 'CURATED', 'REJECTED'"

TERMINAL_STATES = "'CURATED', 'REJECTED'"

REVIEW_DECISIONS = ("'APPROVE', 'REQUEST_CHANGES', 'REJECT', "
                    "'REFER_TO_ADJUDICATION'")

#: An adjudicator settles a dispute. Referring it onward again would be a loop
#: with no exit, so the referral decision is absent from this list.
ADJUDICATION_DECISIONS = "'APPROVE', 'REQUEST_CHANGES', 'REJECT'"

CURATION_ROLES = ("'PROTOCOL_OWNER', 'SCIENTIFIC_CURATOR', "
                  "'INDEPENDENT_SCIENTIFIC_REVIEWER', 'ADJUDICATOR', "
                  "'DATA_PROVENANCE_STEWARD', 'ENGINEERING_OBSERVER'")

AUTHOR_ROLES = "'SCIENTIFIC_CURATOR'"
REVIEWER_ROLES = "'INDEPENDENT_SCIENTIFIC_REVIEWER', 'ADJUDICATOR'"

SYNTHETIC_ACTOR_PREFIX = "TEST-"
LEGACY_VALUE_NAMESPACE = "legacy."

#: The ``0006`` action list, restored verbatim by ``downgrade()``.
AUDIT_ACTIONS_0006 = ("'RELEASE_REGISTERED', 'RELEASE_ACTIVATED', "
                      "'RELEASE_ROLLED_BACK', 'RELEASE_RETIRED', "
                      "'LEGACY_BASELINE_REGISTERED', 'DATASET_BUILD_REGISTERED', "
                      "'DATASET_QUALITY_CHECKED'")

#: The same list plus the eight WP-10 curation actions. Written out in full
#: rather than concatenated onto the previous constant, for the same reason
#: 0004 and 0005 wrote theirs out: the actions this constraint admits should be
#: on the page a reader is looking at, not one indirection away.
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

# ---------------------------------------------------------------------------
# triggers
# ---------------------------------------------------------------------------

#: One function, three tables. The message names the table it fired for, so an
#: operator sees which record they tried to change rather than a generic
#: refusal.
_APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION pgx_curation_record_immutable()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        '% on %.% is not permitted: a curation record states what a named '
        'person concluded at a moment that has passed. A correction is a new '
        'revision or a new work item citing this one, never an edit of it.',
        TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

_REVISIONS_IMMUTABLE_TRIGGER = """
CREATE TRIGGER trg_curation_revisions_immutable
BEFORE UPDATE OR DELETE ON curation_revisions
FOR EACH ROW EXECUTE FUNCTION pgx_curation_record_immutable();
"""

_REVIEWS_IMMUTABLE_TRIGGER = """
CREATE TRIGGER trg_curation_reviews_immutable
BEFORE UPDATE OR DELETE ON curation_reviews
FOR EACH ROW EXECUTE FUNCTION pgx_curation_record_immutable();
"""

_ADJUDICATIONS_IMMUTABLE_TRIGGER = """
CREATE TRIGGER trg_curation_adjudications_immutable
BEFORE UPDATE OR DELETE ON curation_adjudications
FOR EACH ROW EXECUTE FUNCTION pgx_curation_record_immutable();
"""

_PROVENANCE_IMMUTABLE_TRIGGER = """
CREATE TRIGGER trg_curation_provenance_verifications_immutable
BEFORE UPDATE OR DELETE ON curation_provenance_verifications
FOR EACH ROW EXECUTE FUNCTION pgx_curation_record_immutable();
"""

#: Legacy values stay visibly unreviewed in the database, not only in the
#: application. A check constraint cannot express this - it would need a
#: subquery over ``jsonb_object_keys`` - so it is a trigger, which also runs on
#: INSERT, which is the operation that matters here: the legacy import is a
#: bulk insert, and a rule that only ran on UPDATE would never fire for it.
_LEGACY_NAMESPACE_FUNCTION = """
CREATE OR REPLACE FUNCTION pgx_curation_work_items_legacy_namespaced()
RETURNS TRIGGER AS $$
DECLARE
    offending text;
BEGIN
    SELECT string_agg(key, ', ') INTO offending
    FROM jsonb_object_keys(NEW.legacy_values) AS key
    WHERE key NOT LIKE 'legacy.%';

    IF offending IS NOT NULL THEN
        RAISE EXCEPTION
            'work item %: legacy field(s) % are not namespaced. Legacy values '
            'are the old project''s unreviewed interpretations; under a '
            'legacy. prefix they stay visibly upstream, and a query for '
            'curated content cannot match one by accident.',
            NEW.work_item_id, offending
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_LEGACY_NAMESPACE_TRIGGER = """
CREATE TRIGGER trg_curation_work_items_legacy_namespaced
BEFORE INSERT OR UPDATE ON curation_work_items
FOR EACH ROW EXECUTE FUNCTION pgx_curation_work_items_legacy_namespaced();
"""

#: The state machine, enforced on the row.
#:
#: Three separate refusals, because they fail for three different reasons and
#: an operator needs to know which: a move the machine does not have, a move
#: that did not advance the version, and any change at all to a decided
#: conclusion.
_GUARDED_UPDATE_FUNCTION = """
CREATE OR REPLACE FUNCTION pgx_curation_work_items_guarded()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'curation_work_items rows are not deletable: audit events, '
            'revisions and reviews reference this question, and deleting it '
            'would orphan the record of what was decided about it.'
            USING ERRCODE = 'restrict_violation';
    END IF;

    IF OLD.status IN ('CURATED', 'REJECTED') AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION
            'work item % is %: a decided conclusion is immutable. A '
            'correction is a new work item whose lineage cites this one.',
            OLD.work_item_id, OLD.status
            USING ERRCODE = 'restrict_violation';
    END IF;

    IF NEW.status IS DISTINCT FROM OLD.status THEN
        IF NOT (
            (OLD.status = 'RAW' AND NEW.status = 'UNDER_REVIEW') OR
            (OLD.status = 'UNDER_REVIEW' AND NEW.status IN
                ('CURATED', 'REJECTED', 'RAW'))
        ) THEN
            RAISE EXCEPTION
                'work item %: % is not a transition this workflow has. '
                'Permitted: RAW->UNDER_REVIEW, UNDER_REVIEW->CURATED, '
                'UNDER_REVIEW->REJECTED, UNDER_REVIEW->RAW.',
                OLD.work_item_id, OLD.status || '->' || NEW.status
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;

    IF NEW IS DISTINCT FROM OLD AND NEW.version <= OLD.version THEN
        RAISE EXCEPTION
            'work item %: an update must advance version (was %, offered '
            '%). Optimistic concurrency is what stops two reviewers from '
            'both deciding the same state.',
            OLD.work_item_id, OLD.version, NEW.version
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_GUARDED_UPDATE_TRIGGER = """
CREATE TRIGGER trg_curation_work_items_guarded
BEFORE UPDATE OR DELETE ON curation_work_items
FOR EACH ROW EXECUTE FUNCTION pgx_curation_work_items_guarded();
"""

#: Refuse a review by somebody who is not the work item's submitted reviewer's
#: peer - specifically, a review of a revision whose author is the reviewer.
#: The row-level check constraint already compares the two columns; this
#: trigger checks the reviewer against the *stored revision*, so a review row
#: that lied about ``author_actor_id`` is refused too.
_REVIEW_SEPARATION_FUNCTION = """
CREATE OR REPLACE FUNCTION pgx_curation_reviews_independent()
RETURNS TRIGGER AS $$
DECLARE
    stored_author text;
    stored_hash text;
BEGIN
    SELECT authored_by, content_hash INTO stored_author, stored_hash
    FROM curation_revisions WHERE revision_id = NEW.revision_id;

    IF stored_author IS NULL THEN
        RAISE EXCEPTION
            'review names revision % which does not exist', NEW.revision_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    IF lower(btrim(NEW.author_actor_id)) <> lower(btrim(stored_author)) THEN
        RAISE EXCEPTION
            'review records author % but revision % was authored by %; '
            'the separation check would be made against the wrong person.',
            NEW.author_actor_id, NEW.revision_id, stored_author
            USING ERRCODE = 'check_violation';
    END IF;

    IF lower(btrim(NEW.reviewed_by)) = lower(btrim(stored_author)) THEN
        RAISE EXCEPTION
            '% authored revision % and cannot review it: one person '
            'checking their own conclusion is not an independent review.',
            NEW.reviewed_by, NEW.revision_id
            USING ERRCODE = 'check_violation';
    END IF;

    IF NEW.revision_content_hash <> stored_hash THEN
        RAISE EXCEPTION
            'review pins content hash % but revision % hashes to %; the '
            'review would not be about the content that is stored.',
            NEW.revision_content_hash, NEW.revision_id, stored_hash
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_REVIEW_SEPARATION_TRIGGER = """
CREATE TRIGGER trg_curation_reviews_independent
BEFORE INSERT ON curation_reviews
FOR EACH ROW EXECUTE FUNCTION pgx_curation_reviews_independent();
"""

#: Every downgrade refusal, checked before anything is dropped.
_DOWNGRADE_GUARD = """
DO $$
DECLARE
    decided bigint;
    reviews bigint;
    adjudications bigint;
BEGIN
    SELECT count(*) INTO decided FROM curation_work_items
        WHERE status IN ('CURATED', 'REJECTED');
    SELECT count(*) INTO reviews FROM curation_reviews;
    SELECT count(*) INTO adjudications FROM curation_adjudications;

    IF decided > 0 OR reviews > 0 OR adjudications > 0 THEN
        RAISE EXCEPTION
            'refusing to downgrade: this database holds % decided work '
            'item(s), % review(s) and % adjudication(s). Those rows are the '
            'only record that named people reached a scientific conclusion, '
            'and dropping these tables would destroy it. Export them and '
            'decide explicitly what replaces this schema.',
            decided, reviews, adjudications
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
    """Create the WP-10 curation workflow schema."""

    # -- curation_work_items ----------------------------------------------
    op.create_table(
        "curation_work_items",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("work_item_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False,
                  server_default=sa.text("'RAW'")),
        sa.Column("version", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("question_id", sa.String(length=128), nullable=False),
        sa.Column("gene_canonical_key", sa.String(length=128), nullable=False),
        sa.Column("drug_canonical_key", sa.String(length=128), nullable=False),
        sa.Column("current_revision_id", sa.String(length=128), nullable=True),
        sa.Column("submitted_revision_id", sa.String(length=128),
                  nullable=True),
        sa.Column("tags", _jsonb(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("legacy_proposal_id", sa.String(length=128), nullable=True),
        sa.Column("legacy_values", _jsonb(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", sa.String(length=256), nullable=False),
        sa.Column("created_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", _timestamptz(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_curation_work_items"),
        sa.UniqueConstraint("work_item_id",
                            name="uq_curation_work_items_work_item_id"),
        # One open question per gene/drug/legacy proposal. A second work item
        # for the same proposal would mean two people curating the same
        # question without either knowing.
        sa.UniqueConstraint("legacy_proposal_id",
                            name="uq_curation_work_items_legacy_proposal_id"),
        sa.CheckConstraint("status IN (%s)" % WORK_ITEM_STATES,
                           name="ck_curation_work_items_status_enum"),
        sa.CheckConstraint("version >= 0",
                           name="ck_curation_work_items_version_non_negative"),
        sa.CheckConstraint("length(trim(work_item_id)) > 0",
                           name="ck_curation_work_items_id_not_blank"),
        sa.CheckConstraint("length(trim(created_by)) > 0",
                           name="ck_curation_work_items_created_by_not_blank"),
        # An item under review names what is being reviewed.
        sa.CheckConstraint(
            "status <> 'UNDER_REVIEW' OR submitted_revision_id IS NOT NULL",
            name="ck_curation_work_items_under_review_names_revision"),
        # A decided item names the revision that was decided.
        sa.CheckConstraint(
            "status NOT IN (%s) OR submitted_revision_id IS NOT NULL"
            % TERMINAL_STATES,
            name="ck_curation_work_items_terminal_needs_revision"),
        # The legacy-value namespacing rule is a trigger rather than a check
        # constraint: "every key of this jsonb starts with legacy." needs a
        # set-returning function over the document, and PostgreSQL refuses a
        # subquery inside CHECK. See
        # trg_curation_work_items_legacy_namespaced below.
        sa.CheckConstraint("jsonb_typeof(legacy_values) = 'object'",
                           name="ck_curation_work_items_legacy_values_object"),
        sa.CheckConstraint("jsonb_typeof(tags) = 'array'",
                           name="ck_curation_work_items_tags_array"),
    )
    op.create_index("ix_curation_work_items_status", "curation_work_items",
                    ["status"], unique=False)
    op.create_index("ix_curation_work_items_entities", "curation_work_items",
                    ["gene_canonical_key", "drug_canonical_key"], unique=False)
    op.create_index("ix_curation_work_items_question_id",
                    "curation_work_items", ["question_id"], unique=False)

    # -- curation_revisions ------------------------------------------------
    op.create_table(
        "curation_revisions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("revision_id", sa.String(length=128), nullable=False),
        sa.Column("work_item_id", sa.String(length=128), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("parent_revision_id", sa.String(length=128), nullable=True),
        sa.Column("payload", _jsonb(), nullable=False),
        sa.Column("protocol_version", sa.String(length=128), nullable=False),
        sa.Column("protocol_content_hash", sa.String(length=80),
                  nullable=False),
        sa.Column("evidence", _jsonb(), nullable=False),
        sa.Column("evidence_build_content_hash", sa.String(length=80),
                  nullable=True),
        sa.Column("authored_by", sa.String(length=256), nullable=False),
        sa.Column("authored_by_role", sa.String(length=48), nullable=False),
        sa.Column("authored_at", _timestamptz(), nullable=False),
        sa.Column("content_hash", sa.String(length=80), nullable=False),
        sa.Column("workflow_model_version", sa.String(length=64),
                  nullable=False),
        sa.ForeignKeyConstraint(
            ["work_item_id"], ["curation_work_items.work_item_id"],
            name="fk_curation_revisions_work_item_id_curation_work_items",
            ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["parent_revision_id"], ["curation_revisions.revision_id"],
            name="fk_curation_revisions_parent_curation_revisions",
            ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_curation_revisions"),
        sa.UniqueConstraint("revision_id",
                            name="uq_curation_revisions_revision_id"),
        # Revision numbers are dense and unique per work item. Two revision
        # 3s would make "which one did the reviewer read" unanswerable.
        sa.UniqueConstraint("work_item_id", "revision_number",
                            name="uq_curation_revisions_work_item_number"),
        # And one content hash per work item: saving the same content twice is
        # not a new revision, it is the same claim written again.
        sa.UniqueConstraint("work_item_id", "content_hash",
                            name="uq_curation_revisions_work_item_content"),
        sa.CheckConstraint("revision_number >= 1",
                           name="ck_curation_revisions_number_from_one"),
        # Revision 1 has no parent; every later revision names one. A lineage
        # with a gap cannot be reconstructed.
        sa.CheckConstraint(
            "(revision_number = 1 AND parent_revision_id IS NULL)"
            " OR (revision_number > 1 AND parent_revision_id IS NOT NULL)",
            name="ck_curation_revisions_lineage_complete"),
        sa.CheckConstraint("parent_revision_id IS DISTINCT FROM revision_id",
                           name="ck_curation_revisions_not_own_parent"),
        sa.CheckConstraint("authored_by_role IN (%s)" % AUTHOR_ROLES,
                           name="ck_curation_revisions_author_role"),
        sa.CheckConstraint("length(trim(authored_by)) > 0",
                           name="ck_curation_revisions_author_not_blank"),
        sa.CheckConstraint("content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_curation_revisions_content_hash_format"),
        sa.CheckConstraint(
            "protocol_content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
            name="ck_curation_revisions_protocol_hash_format"),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'",
                           name="ck_curation_revisions_payload_object"),
        # A revision selects evidence. A conclusion citing nothing has nothing
        # to interpret.
        sa.CheckConstraint(
            "jsonb_array_length(evidence -> 'evidence_record_uuids') >= 1",
            name="ck_curation_revisions_cites_evidence"),
    )
    op.create_index("ix_curation_revisions_work_item_id", "curation_revisions",
                    ["work_item_id"], unique=False)
    op.create_index("ix_curation_revisions_content_hash", "curation_revisions",
                    ["content_hash"], unique=False)

    # -- curation_reviews --------------------------------------------------
    op.create_table(
        "curation_reviews",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("review_id", sa.String(length=128), nullable=False),
        sa.Column("work_item_id", sa.String(length=128), nullable=False),
        sa.Column("revision_id", sa.String(length=128), nullable=False),
        sa.Column("revision_content_hash", sa.String(length=80),
                  nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("reviewed_by", sa.String(length=256), nullable=False),
        sa.Column("reviewed_by_role", sa.String(length=48), nullable=False),
        sa.Column("reviewed_at", _timestamptz(), nullable=False),
        sa.Column("author_actor_id", sa.String(length=256), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("findings", _jsonb(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("protocol_content_hash", sa.String(length=80),
                  nullable=False),
        sa.Column("evidence_build_content_hash", sa.String(length=80),
                  nullable=False),
        sa.Column("work_item_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=80), nullable=False),
        sa.ForeignKeyConstraint(
            ["work_item_id"], ["curation_work_items.work_item_id"],
            name="fk_curation_reviews_work_item_id_curation_work_items",
            ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["revision_id"], ["curation_revisions.revision_id"],
            name="fk_curation_reviews_revision_id_curation_revisions",
            ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_curation_reviews"),
        sa.UniqueConstraint("review_id", name="uq_curation_reviews_review_id"),
        # One reviewer decides one work-item version once. A second row for
        # the same version would be a reviewer changing their mind by
        # inserting rather than by reviewing again.
        sa.UniqueConstraint("work_item_id", "work_item_version", "reviewed_by",
                            name="uq_curation_reviews_version_reviewer"),
        sa.CheckConstraint("decision IN (%s)" % REVIEW_DECISIONS,
                           name="ck_curation_reviews_decision_enum"),
        sa.CheckConstraint("reviewed_by_role IN (%s)" % REVIEWER_ROLES,
                           name="ck_curation_reviews_reviewer_role"),
        # Separation, on the row, without a join.
        sa.CheckConstraint(
            "lower(btrim(reviewed_by)) <> lower(btrim(author_actor_id))",
            name="ck_curation_reviews_reviewer_not_author"),
        sa.CheckConstraint("length(trim(rationale)) >= 24",
                           name="ck_curation_reviews_rationale_substantive"),
        sa.CheckConstraint("content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_curation_reviews_content_hash_format"),
        sa.CheckConstraint(
            "revision_content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
            name="ck_curation_reviews_revision_hash_format"),
        sa.CheckConstraint("work_item_version >= 0",
                           name="ck_curation_reviews_version_non_negative"),
    )
    op.create_index("ix_curation_reviews_work_item_id", "curation_reviews",
                    ["work_item_id"], unique=False)
    op.create_index("ix_curation_reviews_revision_id", "curation_reviews",
                    ["revision_id"], unique=False)

    # -- curation_adjudications --------------------------------------------
    op.create_table(
        "curation_adjudications",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("adjudication_id", sa.String(length=128), nullable=False),
        sa.Column("work_item_id", sa.String(length=128), nullable=False),
        sa.Column("revision_id", sa.String(length=128), nullable=False),
        sa.Column("revision_content_hash", sa.String(length=80),
                  nullable=False),
        sa.Column("adjudicated_by", sa.String(length=256), nullable=False),
        sa.Column("adjudicated_by_role", sa.String(length=48), nullable=False),
        sa.Column("adjudicated_at", _timestamptz(), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("curator_actor_id", sa.String(length=256), nullable=False),
        sa.Column("reviewer_actor_id", sa.String(length=256), nullable=False),
        sa.Column("curator_position", _jsonb(), nullable=False),
        sa.Column("reviewer_position", _jsonb(), nullable=False),
        sa.Column("disputed_evidence_uuids", _jsonb(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("work_item_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=80), nullable=False),
        sa.ForeignKeyConstraint(
            ["work_item_id"], ["curation_work_items.work_item_id"],
            name="fk_curation_adjudications_work_item_curation_work_items",
            ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["revision_id"], ["curation_revisions.revision_id"],
            name="fk_curation_adjudications_revision_curation_revisions",
            ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_curation_adjudications"),
        sa.UniqueConstraint("adjudication_id",
                            name="uq_curation_adjudications_adjudication_id"),
        sa.CheckConstraint("decision IN (%s)" % ADJUDICATION_DECISIONS,
                           name="ck_curation_adjudications_decision_enum"),
        sa.CheckConstraint("adjudicated_by_role = 'ADJUDICATOR'",
                           name="ck_curation_adjudications_role"),
        # An adjudicator is a third person, not one of the two.
        sa.CheckConstraint(
            "lower(btrim(adjudicated_by)) NOT IN ("
            "lower(btrim(curator_actor_id)), lower(btrim(reviewer_actor_id)))",
            name="ck_curation_adjudications_adjudicator_is_third_party"),
        sa.CheckConstraint(
            "lower(btrim(curator_actor_id)) <> lower(btrim(reviewer_actor_id))",
            name="ck_curation_adjudications_parties_differ"),
        # Both positions are preserved in full. An adjudication that dropped
        # one would erase the disagreement it was called to settle.
        sa.CheckConstraint(
            "jsonb_typeof(curator_position) = 'object'"
            " AND curator_position <> '{}'::jsonb",
            name="ck_curation_adjudications_curator_position_present"),
        sa.CheckConstraint(
            "jsonb_typeof(reviewer_position) = 'object'"
            " AND reviewer_position <> '{}'::jsonb",
            name="ck_curation_adjudications_reviewer_position_present"),
        sa.CheckConstraint("length(trim(rationale)) >= 24",
                           name="ck_curation_adjudications_rationale"),
        sa.CheckConstraint("content_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                           name="ck_curation_adjudications_hash_format"),
    )
    op.create_index("ix_curation_adjudications_work_item_id",
                    "curation_adjudications", ["work_item_id"], unique=False)

    # -- curation_provenance_verifications ---------------------------------
    op.create_table(
        "curation_provenance_verifications",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("verification_id", sa.String(length=128), nullable=False),
        sa.Column("work_item_id", sa.String(length=128), nullable=False),
        sa.Column("verified_by", sa.String(length=256), nullable=False),
        sa.Column("verified_by_role", sa.String(length=48), nullable=False),
        sa.Column("verified_at", _timestamptz(), nullable=False),
        sa.Column("evidence_record_uuids", _jsonb(), nullable=False),
        # No server default. A steward states whether the traces verified;
        # a default would answer for them.
        sa.Column("all_traces_verified", sa.Boolean(), nullable=False),
        sa.Column("problems", _jsonb(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["work_item_id"], ["curation_work_items.work_item_id"],
            name="fk_curation_provenance_work_item_curation_work_items",
            ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_curation_provenance_verifications"),
        sa.UniqueConstraint("verification_id",
                            name="uq_curation_provenance_verification_id"),
        sa.CheckConstraint("verified_by_role = 'DATA_PROVENANCE_STEWARD'",
                           name="ck_curation_provenance_role"),
        # A verification cannot both report problems and claim everything
        # verified; one of the two is wrong.
        sa.CheckConstraint(
            "all_traces_verified = false OR problems = '[]'::jsonb",
            name="ck_curation_provenance_verified_has_no_problems"),
        sa.CheckConstraint(
            "jsonb_array_length(evidence_record_uuids) >= 1",
            name="ck_curation_provenance_names_records"),
    )
    op.create_index("ix_curation_provenance_work_item_id",
                    "curation_provenance_verifications", ["work_item_id"],
                    unique=False)

    # -- curation_work_item_evidence_links ---------------------------------
    op.create_table(
        "curation_work_item_evidence_links",
        sa.Column("work_item_id", sa.String(length=128), nullable=False),
        sa.Column("evidence_record_uuid", _uuid(), nullable=False),
        sa.Column("link_basis", sa.Text(), nullable=False),
        # False, not true. A link inherited from the legacy extraction records
        # which evidence an old interpretation was about; nobody has confirmed
        # that the evidence supports anything.
        sa.Column("reviewed", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("linked_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["work_item_id"], ["curation_work_items.work_item_id"],
            name="fk_curation_links_work_item_curation_work_items",
            ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["evidence_record_uuid"], ["evidence_records.id"],
            name="fk_curation_links_evidence_record_evidence_records",
            ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("work_item_id", "evidence_record_uuid",
                                name="pk_curation_work_item_evidence_links"),
    )
    op.create_index("ix_curation_links_evidence_record_uuid",
                    "curation_work_item_evidence_links",
                    ["evidence_record_uuid"], unique=False)

    # -- curation_role_assignments -----------------------------------------
    op.create_table(
        "curation_role_assignments",
        sa.Column("actor_id", sa.String(length=256), nullable=False),
        sa.Column("role", sa.String(length=48), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("synthetic", sa.Boolean(), nullable=False),
        sa.Column("assigned_by", sa.String(length=256), nullable=False),
        sa.Column("assigned_at", _timestamptz(), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("actor_id", "role",
                                name="pk_curation_role_assignments"),
        sa.CheckConstraint("role IN (%s)" % CURATION_ROLES,
                           name="ck_curation_role_assignments_role_enum"),
        sa.CheckConstraint("length(trim(display_name)) > 0",
                           name="ck_curation_role_assignments_named"),
        # A synthetic actor is exactly one whose id starts with the test
        # prefix. Both directions: a fixture cannot pose as a person, and a
        # person cannot be given a fixture's id.
        sa.CheckConstraint(
            "synthetic = (actor_id LIKE '%s%%')" % SYNTHETIC_ACTOR_PREFIX,
            name="ck_curation_role_assignments_synthetic_prefix"),
    )
    op.create_index("ix_curation_role_assignments_role",
                    "curation_role_assignments", ["role"], unique=False)
    # The table is created empty and stays empty. No production identity
    # exists to assign a role to; WP-23 owns that.

    # -- triggers ----------------------------------------------------------
    op.execute(_APPEND_ONLY_FUNCTION)
    op.execute(_REVISIONS_IMMUTABLE_TRIGGER)
    op.execute(_REVIEWS_IMMUTABLE_TRIGGER)
    op.execute(_ADJUDICATIONS_IMMUTABLE_TRIGGER)
    op.execute(_PROVENANCE_IMMUTABLE_TRIGGER)
    op.execute(_LEGACY_NAMESPACE_FUNCTION)
    op.execute(_LEGACY_NAMESPACE_TRIGGER)
    op.execute(_GUARDED_UPDATE_FUNCTION)
    op.execute(_GUARDED_UPDATE_TRIGGER)
    op.execute(_REVIEW_SEPARATION_FUNCTION)
    op.execute(_REVIEW_SEPARATION_TRIGGER)

    # -- audit_events: widen the action list -------------------------------
    op.drop_constraint("ck_audit_events_action_enum", "audit_events",
                       type_="check")
    op.create_check_constraint(
        "ck_audit_events_action_enum", "audit_events",
        sa.text("action IN (%s)" % AUDIT_ACTIONS_0007))


def downgrade() -> None:
    """Drop exactly the WP-10 objects, children before parents.

    The guard runs first and raises inside the same transaction, so a refusal
    leaves the schema untouched rather than partly dismantled.
    """
    op.execute(_DOWNGRADE_GUARD)

    op.execute("DROP TRIGGER IF EXISTS trg_curation_reviews_independent"
               " ON curation_reviews")
    op.execute("DROP FUNCTION IF EXISTS pgx_curation_reviews_independent()")
    op.execute("DROP TRIGGER IF EXISTS trg_curation_work_items_guarded"
               " ON curation_work_items")
    op.execute("DROP FUNCTION IF EXISTS pgx_curation_work_items_guarded()")
    op.execute("DROP TRIGGER IF EXISTS"
               " trg_curation_work_items_legacy_namespaced"
               " ON curation_work_items")
    op.execute("DROP FUNCTION IF EXISTS"
               " pgx_curation_work_items_legacy_namespaced()")
    op.execute("DROP TRIGGER IF EXISTS"
               " trg_curation_provenance_verifications_immutable"
               " ON curation_provenance_verifications")
    op.execute("DROP TRIGGER IF EXISTS trg_curation_adjudications_immutable"
               " ON curation_adjudications")
    op.execute("DROP TRIGGER IF EXISTS trg_curation_reviews_immutable"
               " ON curation_reviews")
    op.execute("DROP TRIGGER IF EXISTS trg_curation_revisions_immutable"
               " ON curation_revisions")
    op.execute("DROP FUNCTION IF EXISTS pgx_curation_record_immutable()")

    op.drop_index("ix_curation_role_assignments_role",
                  table_name="curation_role_assignments")
    op.drop_table("curation_role_assignments")

    op.drop_index("ix_curation_links_evidence_record_uuid",
                  table_name="curation_work_item_evidence_links")
    op.drop_table("curation_work_item_evidence_links")

    op.drop_index("ix_curation_provenance_work_item_id",
                  table_name="curation_provenance_verifications")
    op.drop_table("curation_provenance_verifications")

    op.drop_index("ix_curation_adjudications_work_item_id",
                  table_name="curation_adjudications")
    op.drop_table("curation_adjudications")

    op.drop_index("ix_curation_reviews_revision_id",
                  table_name="curation_reviews")
    op.drop_index("ix_curation_reviews_work_item_id",
                  table_name="curation_reviews")
    op.drop_table("curation_reviews")

    op.drop_index("ix_curation_revisions_content_hash",
                  table_name="curation_revisions")
    op.drop_index("ix_curation_revisions_work_item_id",
                  table_name="curation_revisions")
    op.drop_table("curation_revisions")

    op.drop_index("ix_curation_work_items_question_id",
                  table_name="curation_work_items")
    op.drop_index("ix_curation_work_items_entities",
                  table_name="curation_work_items")
    op.drop_index("ix_curation_work_items_status",
                  table_name="curation_work_items")
    op.drop_table("curation_work_items")

    # Restore the 0006 action list.
    op.drop_constraint("ck_audit_events_action_enum", "audit_events",
                       type_="check")
    op.create_check_constraint(
        "ck_audit_events_action_enum", "audit_events",
        sa.text("action IN (%s)" % AUDIT_ACTIONS_0006))
