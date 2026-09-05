# -*- coding: utf-8 -*-
"""Schema contract checks for the WP-07 migration (needs no database driver).

The Alembic migration is the authority. These tests read it directly and read
the SQL rendered from it, so the structural guarantees hold in an environment
where Alembic and SQLAlchemy cannot be installed.

Four things beyond shape are asserted here.

**0005 adds, and declares its two constraint replacements.** One is a widening
of the audit-action list; the other is a *narrowing* of the dataset approval
rule, and the migration says so in its own docstring.

**No globally unique alias constraint appears.** Two entities may share an
alias, and a constraint that refused to store that would remove this project's
ability to see the ambiguity rather than the ambiguity itself.

**A conflicting-identity duplicate group blocks in the database.** Not by
convention in a service, where a later caller could forget.

**A quality decision names a human.** A queue decision without a reviewer, an
instant and a rationale is refused, and a chosen key that was never a candidate
is refused too.
"""

from __future__ import annotations

import ast
import io
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
for path in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

from render_wp02_schema import (  # noqa: E402
    POSTGRES_IDENTIFIER_LIMIT, over_length_identifiers,
)
from render_wp07_schema import render_schema  # noqa: E402

MIGRATION_PATH = os.path.join(REPO_ROOT, "migrations", "versions",
                              "0005_wp07_canonicalization.py")

EXPECTED_TABLES = ("canonical_builds", "canonical_build_entities",
                   "resolution_queue_items", "duplicate_groups",
                   "duplicate_group_members")

EXPECTED_COLUMNS = ("status", "reviewed_by", "reviewed_at", "review_note")


def _text() -> str:
    with io.open(MIGRATION_PATH, encoding="utf-8") as handle:
        return handle.read()


def _tree() -> ast.Module:
    return ast.parse(_text(), filename=MIGRATION_PATH)


def _function(name: str) -> ast.FunctionDef:
    for node in _tree().body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("no %s() in %s" % (name, MIGRATION_PATH))


def _calls(function: ast.FunctionDef, attribute: str):
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and \
                isinstance(node.func, ast.Attribute) and \
                node.func.attr == attribute:
            yield node


def _first_string(node: ast.Call) -> str:
    return node.args[0].value if node.args else ""


class TestMigrationShape(unittest.TestCase):

    def test_it_follows_the_wp06_migration(self):
        assignments = {}
        for node in _tree().body:
            if isinstance(node, ast.AnnAssign) and \
                    isinstance(node.target, ast.Name):
                try:
                    assignments[node.target.id] = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    pass
        self.assertEqual(assignments.get("revision"),
                         "0005_wp07_canonicalization")
        self.assertEqual(assignments.get("down_revision"),
                         "0004_wp06_raw_snapshots")

    def test_the_revision_chain_still_has_exactly_one_head(self):
        directory = os.path.join(REPO_ROOT, "migrations", "versions")
        revisions, parents = set(), set()
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".py"):
                continue
            with io.open(os.path.join(directory, name),
                         encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=name)
            for node in tree.body:
                if isinstance(node, ast.AnnAssign) and \
                        isinstance(node.target, ast.Name):
                    try:
                        value = ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        continue
                    if node.target.id == "revision":
                        revisions.add(value)
                    elif node.target.id == "down_revision" and value:
                        parents.add(value)
        # Exactly one head, and 0005 is in the chain rather than at its end.
        # Naming the head literally made this assertion expire the moment
        # 0006 landed; what it was actually protecting - a linear chain with a
        # single head - is asserted directly instead, so a later migration
        # that forked the chain still fails here.
        heads = revisions - parents
        self.assertEqual(len(heads), 1, "the revision chain has %d heads: %s"
                         % (len(heads), sorted(heads)))
        self.assertIn("0005_wp07_canonicalization", revisions)
        self.assertIn("0005_wp07_canonicalization", parents,
                      "0005 must have a child once a later migration exists")

    def test_it_opens_no_connection_at_import_time(self):
        for node in _tree().body:
            if isinstance(node, ast.Expr):
                self.assertIsInstance(node.value, ast.Constant)
                continue
            self.assertIsInstance(
                node, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign,
                       ast.FunctionDef, ast.ClassDef))

    def test_every_identifier_fits_postgres(self):
        """A truncated identifier would break ``downgrade()``."""
        too_long = over_length_identifiers(render_schema())
        self.assertEqual(too_long, [],
                         "PostgreSQL truncates at %d bytes"
                         % POSTGRES_IDENTIFIER_LIMIT)


class TestItOnlyAddsExceptWhereItSaysOtherwise(unittest.TestCase):

    def test_it_creates_exactly_the_expected_tables(self):
        created = {_first_string(node)
                   for node in _calls(_function("upgrade"), "create_table")}
        self.assertEqual(created, set(EXPECTED_TABLES))

    def test_it_drops_no_table_on_the_way_up(self):
        self.assertEqual(list(_calls(_function("upgrade"), "drop_table")), [])

    def test_it_drops_no_column_on_the_way_up(self):
        self.assertEqual(list(_calls(_function("upgrade"), "drop_column")), [])

    def test_it_adds_the_alias_review_columns_to_both_tables(self):
        added = {}
        for node in _calls(_function("upgrade"), "add_column"):
            table = _first_string(node)
            column = node.args[1].args[0].value
            added.setdefault(table, set()).add(column)
        for table in ("gene_aliases", "drug_aliases"):
            with self.subTest(table=table):
                self.assertEqual(added.get(table), set(EXPECTED_COLUMNS))

    def test_the_only_dropped_constraints_are_the_two_it_replaces(self):
        dropped = {_first_string(node)
                   for node in _calls(_function("upgrade"), "drop_constraint")}
        self.assertEqual(dropped, {
            "ck_audit_events_action_enum",
            "ck_dataset_versions_published_requires_approval"})

    def test_the_audit_widening_keeps_every_previous_action(self):
        text = _text()
        for action in ("RELEASE_REGISTERED", "RELEASE_ACTIVATED",
                       "RELEASE_ROLLED_BACK", "RELEASE_RETIRED",
                       "LEGACY_BASELINE_REGISTERED", "DATASET_BUILD_REGISTERED"):
            with self.subTest(action=action):
                self.assertIn(action, text)
        self.assertIn("DATASET_QUALITY_CHECKED", text)

    def test_the_new_audit_action_matches_the_domain_enum(self):
        from pgx.domain.enums import AuditAction
        self.assertIn("DATASET_QUALITY_CHECKED",
                      {member.value for member in AuditAction})

    def test_the_approval_narrowing_is_declared_in_the_docstring(self):
        docstring = ast.get_docstring(_tree()) or ""
        self.assertIn("narrowed", docstring.casefold())
        self.assertIn("QUALITY_CHECKED", docstring)

    def test_the_downgrade_restores_both_replaced_constraints(self):
        created = {_first_string(node) for node in
                   _calls(_function("downgrade"), "create_check_constraint")}
        self.assertIn("ck_audit_events_action_enum", created)
        self.assertIn("ck_dataset_versions_published_requires_approval", created)

    def test_the_downgrade_drops_every_table_it_created(self):
        dropped = {_first_string(node)
                   for node in _calls(_function("downgrade"), "drop_table")}
        self.assertEqual(dropped, set(EXPECTED_TABLES))

    def test_the_downgrade_removes_the_alias_columns(self):
        dropped = {}
        for node in _calls(_function("downgrade"), "drop_column"):
            dropped.setdefault(_first_string(node), set()).add(node.args[1].value)
        for table in ("gene_aliases", "drug_aliases"):
            with self.subTest(table=table):
                self.assertEqual(dropped.get(table), set(EXPECTED_COLUMNS))

    def test_the_downgrade_drops_the_trigger_and_its_function(self):
        statements = " ".join(
            node.args[0].value for node in _calls(_function("downgrade"), "execute")
            if node.args and isinstance(node.args[0], ast.Constant))
        self.assertIn("DROP TRIGGER", statements)
        self.assertIn("DROP FUNCTION", statements)


class TestAmbiguityStaysStorable(unittest.TestCase):

    def test_no_unique_constraint_on_an_alias_alone_is_created(self):
        """Two entities may share an alias. Refusing to store that would
        remove the project's ability to see the collision, not the collision.
        """
        sql = render_schema()
        for forbidden in ("UNIQUE (normalized_alias)",
                          "CREATE UNIQUE INDEX ix_gene_aliases_normalized_alias",
                          "CREATE UNIQUE INDEX ix_drug_aliases_normalized_alias"):
            with self.subTest(fragment=forbidden):
                self.assertNotIn(forbidden, sql)

    def test_the_alias_index_it_adds_is_not_unique(self):
        sql = render_schema()
        self.assertIn("CREATE INDEX ix_gene_aliases_status", sql)
        self.assertNotIn("CREATE UNIQUE INDEX ix_gene_aliases_status", sql)

    def test_a_resolved_outcome_cannot_sit_in_the_review_queue(self):
        self.assertIn("ck_resolution_queue_items_needs_review", render_schema())

    def test_an_ambiguous_queue_item_must_carry_two_candidates(self):
        sql = render_schema()
        self.assertIn("ck_resolution_queue_items_ambiguity_has_candidates", sql)
        self.assertIn("jsonb_array_length(candidate_keys) >= 2", sql)


class TestDecisionsNameAHuman(unittest.TestCase):

    def test_an_approved_alias_must_name_its_reviewer(self):
        sql = render_schema()
        for table in ("gene_aliases", "drug_aliases"):
            with self.subTest(table=table):
                self.assertIn("ck_%s_approval_names_reviewer" % table, sql)

    def test_a_queue_decision_needs_reviewer_instant_and_rationale(self):
        self.assertIn("ck_resolution_queue_decision_is_complete",
                      render_schema())

    def test_a_decision_may_only_choose_an_actual_candidate(self):
        self.assertIn("ck_resolution_queue_choice_was_a_candidate",
                      render_schema())

    def test_a_quality_checked_dataset_must_name_an_approver(self):
        sql = render_schema()
        self.assertIn("ck_dataset_versions_approval_requires_reviewer", sql)
        self.assertIn("status NOT IN ('QUALITY_CHECKED', 'PUBLISHED')", sql)

    def test_existing_aliases_are_migrated_to_pending_review(self):
        statements = " ".join(
            node.args[0].value for node in _calls(_function("upgrade"), "execute")
            if node.args and isinstance(node.args[0], ast.Constant))
        self.assertIn("UPDATE gene_aliases SET status = 'PENDING_REVIEW'",
                      statements)
        self.assertIn("UPDATE drug_aliases SET status = 'PENDING_REVIEW'",
                      statements)
        self.assertNotIn("'APPROVED'", statements)


class TestDuplicatesAndBuildsAreProtected(unittest.TestCase):

    def test_a_conflicting_identity_group_must_block_and_explain(self):
        sql = render_schema()
        self.assertIn("ck_duplicate_groups_conflict_blocks", sql)
        self.assertIn("jsonb_array_length(differences) > 0", sql)

    def test_a_duplicate_group_needs_at_least_two_members(self):
        self.assertIn("ck_duplicate_groups_member_count", render_schema())

    def test_every_member_locator_has_its_own_row(self):
        sql = render_schema()
        self.assertIn("CREATE TABLE duplicate_group_members", sql)
        self.assertIn("uq_duplicate_group_members_group_locator", sql)

    def test_a_recorded_build_is_immutable_and_undeletable(self):
        sql = render_schema()
        self.assertIn("pgx_canonical_builds_immutable", sql)
        self.assertIn("are not deletable", sql)
        self.assertIn("CREATE TRIGGER trg_canonical_builds_immutable", sql)

    def test_a_passing_gate_may_not_carry_blocking_codes(self):
        self.assertIn("ck_canonical_builds_pass_has_no_blocking_codes",
                      render_schema())

    def test_an_entity_row_must_carry_provenance(self):
        self.assertIn("ck_canonical_build_entities_has_provenance",
                      render_schema())

    def test_a_canonical_key_must_match_its_normalised_value(self):
        sql = render_schema()
        self.assertIn("ck_canonical_build_entities_key_matches_value", sql)
        self.assertIn("canonical_key = entity_type || ':' || normalized_value",
                      sql)

    def test_paths_stored_in_this_schema_must_be_relative(self):
        sql = render_schema()
        self.assertIn("ck_canonical_builds_path_relative", sql)
        self.assertIn("ck_duplicate_group_members_path_relative", sql)


class TestRenderedSqlIsComplete(unittest.TestCase):

    def test_every_expected_table_is_rendered(self):
        sql = render_schema()
        for table in EXPECTED_TABLES:
            with self.subTest(table=table):
                self.assertIn("CREATE TABLE %s" % table, sql)

    def test_the_downgrade_direction_renders_too(self):
        sql = render_schema(direction="downgrade")
        self.assertIn("DROP TABLE canonical_builds;", sql)
        self.assertIn("DROP FUNCTION IF EXISTS pgx_canonical_builds_immutable",
                      sql)

    def test_the_rendered_sql_says_it_is_generated(self):
        self.assertIn("GENERATED from", render_schema())

    def test_it_does_not_claim_to_be_alembic_evidence(self):
        with io.open(os.path.join(REPO_ROOT, "scripts",
                                  "render_wp07_schema.py"),
                     encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("This is not Alembic", text)


if __name__ == "__main__":
    unittest.main()
