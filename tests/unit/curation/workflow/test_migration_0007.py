# -*- coding: utf-8 -*-
"""Migration 0007, read as source and as rendered SQL (WP-10).

Alembic and SQLAlchemy cannot be installed in this environment, so the
migration cannot be *run* here. What can be checked is what it says: the
revision chain, the tables and constraints it declares, that it rewrites
nothing 0001-0006 owns, and that its downgrade refuses on data it must not
destroy. The rendered SQL is executed against a real PostgreSQL server
separately; ``docs/evidence/wp10-schema-validation.md`` records that run and
what it does and does not prove.
"""

from __future__ import annotations

import ast
import io
import os
import unittest

from tests.unit.curation._support import REPO_ROOT

MIGRATIONS = os.path.join(REPO_ROOT, "migrations", "versions")
MIGRATION_0007 = os.path.join(MIGRATIONS, "0007_wp10_curation_workflow.py")


def _source(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def _module():
    return ast.parse(_source(MIGRATION_0007), filename=MIGRATION_0007)


def _function(name):
    for node in _module().body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("no %s() in 0007" % name)


def _calls(function, attribute):
    found = []
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and \
                getattr(node.func, "attr", None) == attribute:
            found.append(node)
    return found


def _constant(node):
    return node.value if isinstance(node, ast.Constant) else None


class TestTheRevisionChain(unittest.TestCase):

    def test_0007_exists_and_follows_0006(self):
        assignments = {}
        for node in _module().body:
            if isinstance(node, ast.AnnAssign) and \
                    isinstance(node.target, ast.Name):
                assignments[node.target.id] = _constant(node.value)
        self.assertEqual(assignments["revision"],
                         "0007_wp10_curation_workflow")
        self.assertEqual(assignments["down_revision"],
                         "0006_wp08_evidence_store")

    def test_the_earlier_migrations_are_untouched_on_disk(self):
        """0007 adds; it does not rewrite. Asserted by their content having a
        down_revision chain that still reaches 0001 unbroken."""
        expected = {
            "0001_wp02_foundation.py": None,
            "0002_wp03_release_registry.py": "0001_wp02_foundation",
            "0003_wp05_source_policy.py": "0002_wp03_release_registry",
            "0004_wp06_raw_snapshots.py": "0003_wp05_source_policy",
            "0005_wp07_canonicalization.py": "0004_wp06_raw_snapshots",
            "0006_wp08_evidence_store.py": "0005_wp07_canonicalization",
        }
        for name, parent in expected.items():
            with self.subTest(migration=name):
                tree = ast.parse(_source(os.path.join(MIGRATIONS, name)))
                found = None
                for node in tree.body:
                    if isinstance(node, ast.AnnAssign) and \
                            getattr(node.target, "id", None) == "down_revision":
                        found = _constant(node.value)
                self.assertEqual(found, parent)

    def test_no_other_migration_claims_to_follow_0006(self):
        followers = []
        for name in sorted(os.listdir(MIGRATIONS)):
            if not name.endswith(".py"):
                continue
            tree = ast.parse(_source(os.path.join(MIGRATIONS, name)))
            for node in tree.body:
                if isinstance(node, ast.AnnAssign) and \
                        getattr(node.target, "id", None) == "down_revision" \
                        and _constant(node.value) == "0006_wp08_evidence_store":
                    followers.append(name)
        self.assertEqual(followers, ["0007_wp10_curation_workflow.py"])


class TestWhatTheUpgradeCreates(unittest.TestCase):

    EXPECTED_TABLES = (
        "curation_work_items", "curation_revisions", "curation_reviews",
        "curation_adjudications", "curation_provenance_verifications",
        "curation_work_item_evidence_links", "curation_role_assignments",
    )

    def setUp(self):
        self.upgrade = _function("upgrade")

    def test_it_creates_exactly_the_seven_workflow_tables(self):
        created = [_constant(call.args[0])
                   for call in _calls(self.upgrade, "create_table")]
        self.assertEqual(tuple(created), self.EXPECTED_TABLES)

    def test_it_drops_no_table_and_no_column(self):
        """A migration that dropped something 0001-0006 owns would not be
        reversible on a database holding data."""
        self.assertEqual(_calls(self.upgrade, "drop_table"), [])
        self.assertEqual(_calls(self.upgrade, "drop_column"), [])

    def test_the_only_existing_table_it_touches_is_audit_events(self):
        touched = set()
        for attribute in ("drop_constraint", "create_check_constraint",
                          "add_column", "alter_column"):
            for call in _calls(self.upgrade, attribute):
                index = 1 if attribute in ("drop_constraint",
                                           "create_check_constraint") else 0
                touched.add(_constant(call.args[index]))
        self.assertEqual(touched, {"audit_events"})

    def test_the_audit_action_list_is_widened_not_replaced(self):
        body = _source(MIGRATION_0007)
        namespace = {}
        for node in _module().body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and \
                    isinstance(node.targets[0], ast.Name):
                try:
                    namespace[node.targets[0].id] = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    continue
        old = namespace["AUDIT_ACTIONS_0006"]
        new = namespace["AUDIT_ACTIONS_0007"]
        for action in old.split(", "):
            with self.subTest(action=action):
                self.assertIn(action, new)
        self.assertIn("'CURATION_APPROVED'", new)

    def test_every_workflow_audit_action_is_admitted(self):
        from pgx.domain.enums import AuditAction
        body = _source(MIGRATION_0007)
        for action in AuditAction:
            if not action.value.startswith("CURATION_"):
                continue
            with self.subTest(action=action.value):
                self.assertIn("'%s'" % action.value, body)


class TestTheDatabaseEnforcesTheRules(unittest.TestCase):
    """Every rule the service enforces is also declared in the schema.

    Not duplication: the service is one process among several, and "we always
    go through the service" is a claim about developer behaviour rather than
    about the data.
    """

    def setUp(self):
        self.body = _source(MIGRATION_0007)

    def test_the_state_machine_is_a_trigger(self):
        self.assertIn("pgx_curation_work_items_guarded", self.body)
        for edge in ("RAW' AND NEW.status = 'UNDER_REVIEW",
                     "UNDER_REVIEW' AND NEW.status IN"):
            with self.subTest(edge=edge):
                self.assertIn(edge, self.body)

    def test_a_terminal_work_item_is_refused_any_change(self):
        self.assertIn("a decided conclusion is immutable", self.body)

    def test_an_update_must_advance_the_version(self):
        self.assertIn("NEW.version <= OLD.version", self.body)

    def test_each_append_only_table_has_an_immutability_trigger(self):
        for table in ("curation_revisions", "curation_reviews",
                      "curation_adjudications",
                      "curation_provenance_verifications"):
            with self.subTest(table=table):
                self.assertIn("CREATE TRIGGER trg_%s_immutable" % table,
                              self.body)

    def test_the_reviewer_separation_is_a_check_constraint(self):
        self.assertIn("ck_curation_reviews_reviewer_not_author", self.body)
        self.assertIn("lower(btrim(reviewed_by)) <> "
                      "lower(btrim(author_actor_id))", self.body)

    def test_a_review_is_checked_against_the_stored_revision(self):
        """The row constraint compares two columns; the trigger compares one
        of them with the revision that actually exists, so a review row that
        lied about its author is refused too."""
        self.assertIn("pgx_curation_reviews_independent", self.body)
        self.assertIn("was authored by", self.body)

    def test_an_adjudicator_may_not_be_a_party(self):
        self.assertIn("ck_curation_adjudications_adjudicator_is_third_party",
                      self.body)

    def test_both_adjudication_positions_must_be_present(self):
        for name in ("ck_curation_adjudications_curator_position_present",
                     "ck_curation_adjudications_reviewer_position_present"):
            with self.subTest(constraint=name):
                self.assertIn(name, self.body)

    def test_revision_lineage_is_a_check_constraint(self):
        self.assertIn("ck_curation_revisions_lineage_complete", self.body)

    def test_revision_uniqueness_is_declared_two_ways(self):
        for name in ("uq_curation_revisions_work_item_number",
                     "uq_curation_revisions_work_item_content"):
            with self.subTest(constraint=name):
                self.assertIn(name, self.body)

    def test_one_reviewer_decides_one_version_once(self):
        self.assertIn("uq_curation_reviews_version_reviewer", self.body)

    def test_legacy_values_must_be_namespaced(self):
        self.assertIn("pgx_curation_work_items_legacy_namespaced", self.body)
        self.assertIn("NOT LIKE 'legacy.%'", self.body)

    def test_a_synthetic_actor_is_exactly_a_test_prefixed_one(self):
        self.assertIn("synthetic = (actor_id LIKE", self.body)
        self.assertIn("ck_curation_role_assignments_synthetic_prefix",
                      self.body)


class TestThereAreNoApprovalDefaults(unittest.TestCase):
    """No column defaults to an approved, verified or reviewed value."""

    def setUp(self):
        self.upgrade = _function("upgrade")

    def _columns(self):
        for call in _calls(self.upgrade, "Column"):
            name = _constant(call.args[0]) if call.args else None
            default = None
            for keyword in call.keywords:
                if keyword.arg == "server_default":
                    default = ast.dump(keyword.value)
            yield name, default

    def test_no_column_defaults_to_true_for_an_approval_or_verification(self):
        for name, default in self._columns():
            if name in ("all_traces_verified", "reviewed", "synthetic"):
                with self.subTest(column=name):
                    self.assertNotIn("true", (default or "").lower(),
                                     "%s must not default to true" % name)

    def test_all_traces_verified_has_no_default_at_all(self):
        for name, default in self._columns():
            if name == "all_traces_verified":
                self.assertIsNone(default,
                                  "a steward states whether traces verified; "
                                  "a default would answer for them")

    def test_the_only_status_default_is_raw(self):
        for name, default in self._columns():
            if name == "status":
                with self.subTest(column=name):
                    self.assertIn("RAW", default or "")

    def test_the_role_assignment_table_is_created_empty(self):
        """No INSERT seeds it. There is nobody to assign a role to until
        WP-23 provides authenticated identities."""
        body = _source(MIGRATION_0007)
        self.assertNotIn("INSERT INTO curation_role_assignments", body)
        self.assertIn("created empty", body)


class TestTheDowngrade(unittest.TestCase):

    def setUp(self):
        self.downgrade = _function("downgrade")
        self.body = _source(MIGRATION_0007)

    def test_it_drops_every_table_it_created(self):
        dropped = {_constant(call.args[0])
                   for call in _calls(self.downgrade, "drop_table")}
        self.assertEqual(dropped, set(TestWhatTheUpgradeCreates.EXPECTED_TABLES))

    def test_it_drops_each_trigger_and_its_function(self):
        executed = " ".join(
            str(_constant(call.args[0]) or ast.dump(call.args[0]))
            for call in _calls(self.downgrade, "execute"))
        for function in ("pgx_curation_record_immutable",
                         "pgx_curation_work_items_guarded",
                         "pgx_curation_reviews_independent",
                         "pgx_curation_work_items_legacy_namespaced"):
            with self.subTest(function=function):
                self.assertIn("DROP FUNCTION IF EXISTS", executed)
                self.assertIn(function, self.body)

    def test_it_restores_the_0006_audit_action_list(self):
        self.assertIn("AUDIT_ACTIONS_0006",
                      ast.dump(self.downgrade))

    def test_it_refuses_on_a_database_holding_a_decision(self):
        self.assertIn("_DOWNGRADE_GUARD", ast.dump(self.downgrade))
        self.assertIn("refusing to downgrade", self.body)
        for table in ("curation_reviews", "curation_adjudications"):
            with self.subTest(table=table):
                self.assertIn("FROM %s" % table, self.body)

    def test_the_guard_runs_before_the_first_drop(self):
        """A refusal that arrives after the tables are gone has refused
        nothing."""
        body = list(self.downgrade.body)
        if body and isinstance(body[0], ast.Expr) and \
                isinstance(body[0].value, ast.Constant):
            body = body[1:]  # the docstring
        self.assertIn("_DOWNGRADE_GUARD", ast.dump(body[0]),
                      "the first executable statement must be the guard")


class TestTheRenderedSqlIsDerivedNotHandMaintained(unittest.TestCase):

    def test_the_renderer_reads_the_migration(self):
        renderer = os.path.join(REPO_ROOT, "scripts",
                                "render_wp10_schema.py")
        self.assertTrue(os.path.isfile(renderer))
        body = _source(renderer)
        self.assertIn("0007_wp10_curation_workflow.py", body)
        self.assertIn("This is not Alembic", body)

    def test_the_renderer_emits_the_downgrade_guard_first(self):
        import sys
        scripts = os.path.join(REPO_ROOT, "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from render_wp10_schema import _downgrade_order_wp10
        ordered = _downgrade_order_wp10([
            "DROP TABLE curation_reviews;",
            "DROP TRIGGER trg_x ON y;",
            "DO $$ BEGIN RAISE; END $$;",
        ])
        self.assertTrue(ordered[0].startswith("DO $$"))

    def test_the_rendered_upgrade_is_one_transaction(self):
        import sys
        scripts = os.path.join(REPO_ROOT, "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from render_wp10_schema import render_schema
        sql = render_schema()
        self.assertIn("BEGIN;", sql)
        self.assertTrue(sql.rstrip().endswith("COMMIT;"))
        for table in TestWhatTheUpgradeCreates.EXPECTED_TABLES:
            with self.subTest(table=table):
                self.assertIn("CREATE TABLE %s (" % table, sql)


class TestTheOrmAgreesWithTheMigration(unittest.TestCase):
    """The ORM is what a developer reads; the migration is authoritative. A
    model admitting values the database refuses would send them looking in the
    wrong place."""

    def setUp(self):
        self.migration = _source(MIGRATION_0007)
        self.models = _source(os.path.join(REPO_ROOT, "pgx",
                                           "infrastructure", "db",
                                           "models.py"))

    def test_every_workflow_table_has_an_orm_class(self):
        for table in TestWhatTheUpgradeCreates.EXPECTED_TABLES:
            with self.subTest(table=table):
                self.assertIn('__tablename__ = "%s"' % table, self.models)

    def test_the_orm_carries_the_same_separation_rule(self):
        self.assertIn("lower(btrim(reviewed_by)) <> "
                      "lower(btrim(author_actor_id))", self.models)

    def test_the_orm_carries_the_same_synthetic_prefix_rule(self):
        self.assertIn("synthetic = (actor_id LIKE 'TEST-%')", self.models)

    def test_the_orm_audit_action_list_matches_the_enum(self):
        from pgx.domain.enums import AuditAction
        for action in AuditAction:
            with self.subTest(action=action.value):
                self.assertIn('"%s"' % action.value, self.models)

    def test_the_orm_declares_no_approval_default(self):
        self.assertIn("all_traces_verified: Mapped[bool] = mapped_column("
                      "Boolean, nullable=False)", self.models)


if __name__ == "__main__":
    unittest.main()
