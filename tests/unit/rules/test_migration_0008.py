# -*- coding: utf-8 -*-
"""Migration 0008, read as source and as rendered SQL (WP-11).

Alembic and SQLAlchemy cannot be installed in this environment, so the
migration cannot be *run* here. What can be checked is what it says: the
revision chain, the columns, constraints, functions and triggers it declares,
that it extends the existing rule tables rather than creating parallel ones,
and that its downgrade refuses on data it must not destroy. The rendered SQL
is executed against a real PostgreSQL server separately;
``docs/evidence/wp11-schema-validation.md`` records that run and what it does
and does not prove.

The invariants this migration puts in the database are the ones that must hold
even when application code is bypassed: a VALIDATED rule names a validator who
is not its author, a FROZEN ruleset names its artifact, and a build or
approval record can never be edited after the fact.
"""

from __future__ import annotations

import ast
import os
import unittest

from tests.unit.rules._support import MIGRATION_0008, REPO_ROOT, source, tree

MIGRATIONS = os.path.join(REPO_ROOT, "migrations", "versions")


def _function(name):
    for node in tree(MIGRATION_0008).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("no %s() in 0008" % name)


def _calls(node, attribute):
    found = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and \
                getattr(child.func, "attr", None) == attribute:
            found.append(child)
    return found


def _first_arg(call):
    if call.args and isinstance(call.args[0], ast.Constant):
        return call.args[0].value
    return None


class TestTheRevisionChain(unittest.TestCase):

    def test_0008_follows_0007(self):
        text = source(MIGRATION_0008)
        self.assertIn('revision: str = "0008_wp11_rules_and_rulesets"', text)
        self.assertIn('down_revision: Union[str, None] = '
                      '"0007_wp10_curation_workflow"', text)

    def test_the_chain_is_linear_and_0008_has_exactly_one_child(self):
        """0008 stopped being the head when WP-14 added 0009 behind it.

        What the head assertion was protecting is the property that matters
        and is checked here instead: the chain is linear. Every revision but
        the newest is some revision's parent, no revision is claimed as parent
        twice, and 0008's single child is 0009. A fork would mean two
        migrations both claiming to follow 0008, and Alembic would have no
        single upgrade path.

        Read with the AST rather than by matching text: ``down_revision:
        Union[str, None] = "..."`` contains the word None in its *annotation*,
        and a line-matching version of this test silently found no parents at
        all and passed for the wrong reason."""
        downs = set()
        revisions = set()
        for name in sorted(os.listdir(MIGRATIONS)):
            if not name.endswith(".py") or name.startswith("__"):
                continue
            for node in tree(os.path.join(MIGRATIONS, name)).body:
                if not isinstance(node, ast.AnnAssign) or \
                        not isinstance(node.target, ast.Name):
                    continue
                if not isinstance(node.value, ast.Constant) or \
                        node.value.value is None:
                    continue
                if node.target.id == "revision":
                    revisions.add(node.value.value)
                elif node.target.id == "down_revision":
                    downs.add(node.value.value)
        # The count is derived rather than pinned. It was 9, and WP-22's
        # review tables made it 10; a pinned total turns every later work
        # package's legitimate migration into a failure in this file, which
        # is exactly what the head assertion above was corrected for once
        # already. What matters is the shape, and the shape is checked below.
        self.assertEqual(len(revisions), len([
            name for name in os.listdir(MIGRATIONS)
            if name.endswith(".py") and not name.startswith("__")]))
        # Exactly one head, and it is not 0008. The head used to be named
        # here as a literal - first 0009, then 0010 - and each work package
        # that added a migration had to come back and edit this line. That is
        # the same pinning the count above was corrected for. The durable
        # statement is the shape: one head, and 0008 is not it.
        heads = revisions - downs
        self.assertEqual(len(heads), 1)
        self.assertNotIn("0008_wp11_rules_and_rulesets", heads)
        # The head is the last revision in filename order, so the chain and
        # the numbering agree; a migration inserted out of order fails here.
        newest = sorted(
            name for name in os.listdir(MIGRATIONS)
            if name.endswith(".py") and not name.startswith("__"))[-1]
        self.assertEqual(heads, {newest[:-len(".py")]})
        # 0008 is still in the chain, and exactly one revision follows it.
        self.assertIn("0008_wp11_rules_and_rulesets", downs)
        children = []
        for name in sorted(os.listdir(MIGRATIONS)):
            if not name.endswith(".py") or name.startswith("__"):
                continue
            parent = revision = None
            for node in tree(os.path.join(MIGRATIONS, name)).body:
                if not isinstance(node, ast.AnnAssign) or \
                        not isinstance(node.target, ast.Name) or \
                        not isinstance(node.value, ast.Constant):
                    continue
                if node.target.id == "revision":
                    revision = node.value.value
                elif node.target.id == "down_revision":
                    parent = node.value.value
            if parent == "0008_wp11_rules_and_rulesets":
                children.append(revision)
        self.assertEqual(children, ["0009_wp14_assessments"])
        self.assertEqual(downs - revisions, set())


class TestItExtendsRatherThanDuplicates(unittest.TestCase):
    """``computable_rules`` and ``ruleset_versions`` already existed. Creating
    ``wp11_rules`` beside them would leave two answers to "what rules exist",
    which is the drift the release registry exists to prevent."""

    def test_it_creates_only_the_three_genuinely_new_tables(self):
        created = {_first_arg(call)
                   for call in _calls(_function("upgrade"), "create_table")}
        self.assertEqual(created, {"rule_lifecycle_events", "ruleset_builds",
                                   "ruleset_approvals"})

    def test_it_creates_no_parallel_rule_table(self):
        created = {_first_arg(call)
                   for call in _calls(_function("upgrade"), "create_table")}
        for forbidden in ("wp11_rules", "rules", "computable_rules_v2",
                          "rulesets", "ruleset_versions_v2"):
            with self.subTest(table=forbidden):
                self.assertNotIn(forbidden, created)

    def test_it_adds_columns_to_the_existing_tables(self):
        altered = {_first_arg(call)
                   for call in _calls(_function("upgrade"), "add_column")}
        self.assertEqual(altered, {"computable_rules", "ruleset_versions",
                                   "ruleset_rules"})

    def test_it_drops_no_column_any_earlier_migration_created(self):
        dropped = _calls(_function("upgrade"), "drop_column")
        self.assertEqual(dropped, [])

    def test_it_drops_no_earlier_table(self):
        self.assertEqual(_calls(_function("upgrade"), "drop_table"), [])


class TestTheDatabaseEnforcesTheLifecycleRules(unittest.TestCase):
    """Every one of these is a rule the application also enforces. They are
    here as well because "the application always uses the service" is an
    assumption, and a psql session is a counter-example."""

    REQUIRED = (
        ("ck_computable_rules_validated_records_validator",
         "a VALIDATED rule names who validated it and when"),
        ("ck_computable_rules_validator_is_not_author",
         "the validator is not the author: separation of duties"),
        ("ck_computable_rules_validated_pins_provenance",
         "a VALIDATED rule pins its revision, envelope, protocol and builds"),
        ("ck_computable_rules_curated_pins_revision",
         "a CURATED rule names the exact revision it encodes"),
        ("ck_computable_rules_outcome_is_authorable",
         "NOT_ASSESSED is not an authorable outcome"),
        ("ck_computable_rules_not_own_predecessor",
         "a rule does not supersede itself"),
        ("ck_computable_rules_deprecated_records_reason",
         "a withdrawal states why"),
        ("ck_ruleset_versions_frozen_pins_artifact",
         "a FROZEN ruleset names the artifact behind it"),
        ("ck_ruleset_versions_artifact_path_relative",
         "an absolute path would differ per machine"),
        ("ck_ruleset_versions_retired_records_reason",
         "a retirement states why"),
        ("ck_ruleset_approvals_reviewer_is_not_author",
         "separation of duties, in the approval record"),
        ("ck_ruleset_approvals_approver_is_not_author", "the same, for approval"),
        ("ck_ruleset_approvals_validator_is_not_author",
         "the same, for validation"),
        ("ck_ruleset_builds_succeeded_has_artifact",
         "a build that succeeded produced something"),
        ("ck_ruleset_builds_completed_after_started",
         "a build does not finish before it starts"),
    )

    def test_every_named_constraint_is_declared(self):
        text = source(MIGRATION_0008)
        for name, reason in self.REQUIRED:
            with self.subTest(constraint=name, because=reason):
                self.assertIn(name, text)

    def test_the_audit_action_list_is_widened_not_replaced(self):
        """Every action that satisfied 0007's constraint must still satisfy
        0008's, or an existing audit row would become invalid."""
        text = source(MIGRATION_0008)
        for action in ("RELEASE_REGISTERED", "DATASET_BUILD_REGISTERED",
                       "CURATION_APPROVED", "CURATION_ADJUDICATED"):
            with self.subTest(action=action):
                self.assertIn("'%s'" % action, text)
        for action in ("RULE_DRAFTED", "RULE_VALIDATED",
                       "RULE_VALIDATION_REFUSED", "RULESET_FROZEN",
                       "RULESET_VALIDATION_REFUSED", "RULESET_RETIRED"):
            with self.subTest(action=action):
                self.assertIn("'%s'" % action, text)

    def test_the_three_new_tables_are_append_only_by_trigger(self):
        text = source(MIGRATION_0008)
        for table in ("rule_lifecycle_events", "ruleset_builds",
                      "ruleset_approvals"):
            with self.subTest(table=table):
                self.assertIn("trg_%s_append_only" % table, text)

    def test_the_guarded_update_functions_exist(self):
        text = source(MIGRATION_0008)
        for function in ("pgx_computable_rules_guarded",
                         "pgx_ruleset_versions_guarded",
                         "pgx_ruleset_rules_guarded",
                         "pgx_rule_record_append_only",
                         "pgx_ruleset_lock_key"):
            with self.subTest(function=function):
                self.assertIn(function, text)


class TestThereAreNoApprovalDefaults(unittest.TestCase):

    def test_no_column_defaults_to_an_approval_or_a_validation(self):
        upgrade = _function("upgrade")
        for call in _calls(upgrade, "Column"):
            name = _first_arg(call)
            if name is None:
                continue
            defaults = [keyword for keyword in call.keywords
                        if keyword.arg in ("server_default", "default")]
            if not defaults:
                continue
            with self.subTest(column=name):
                for approval_field in ("approved", "validated", "reviewed",
                                       "frozen"):
                    self.assertNotIn(approval_field, name)

    def test_lifecycle_version_defaults_to_zero_not_to_a_later_state(self):
        text = source(MIGRATION_0008)
        self.assertIn('"lifecycle_version", sa.Integer(), nullable=False,', text)
        self.assertIn('server_default=sa.text("0")', text)


class TestTheDowngradeRefusesToDestroyApprovedWork(unittest.TestCase):

    def test_the_downgrade_guard_runs_first(self):
        downgrade = _function("downgrade")
        first = downgrade.body[1] if len(downgrade.body) > 1 else None
        self.assertIsNotNone(first)
        self.assertIn("_DOWNGRADE_GUARD", ast.unparse(first))

    def test_the_guard_names_approved_rules_and_frozen_rulesets(self):
        text = source(MIGRATION_0008)
        guard = text.split("_DOWNGRADE_GUARD", 1)[1][:2000]
        self.assertIn("VALIDATED", guard)
        self.assertIn("FROZEN", guard)

    def test_the_downgrade_drops_only_what_the_upgrade_created(self):
        created = {_first_arg(call)
                   for call in _calls(_function("upgrade"), "create_table")}
        dropped = {_first_arg(call)
                   for call in _calls(_function("downgrade"), "drop_table")}
        self.assertEqual(created, dropped)

    def test_the_downgrade_removes_every_column_the_upgrade_added(self):
        added = {(_first_arg(call), call.args[1].args[0].value)
                 for call in _calls(_function("upgrade"), "add_column")
                 if len(call.args) > 1 and getattr(call.args[1], "args", None)}
        removed = {(_first_arg(call), call.args[1].value)
                   for call in _calls(_function("downgrade"), "drop_column")
                   if len(call.args) > 1
                   and isinstance(call.args[1], ast.Constant)}
        self.assertEqual(added - removed, set())


class TestTheOrmAgreesWithTheMigration(unittest.TestCase):
    """The ORM is what a developer reads; the migration is authoritative. A
    model missing a column the database has sends somebody looking in the
    wrong place - and here it would break the SQLAlchemy adapters, which read
    those columns by name."""

    @classmethod
    def setUpClass(cls):
        cls.models = source(os.path.join(REPO_ROOT, "pgx", "infrastructure",
                                         "db", "models.py"))

    def test_every_added_column_is_mapped(self):
        for call in _calls(_function("upgrade"), "add_column"):
            if len(call.args) < 2 or not getattr(call.args[1], "args", None):
                continue
            column = call.args[1].args[0].value
            with self.subTest(table=_first_arg(call), column=column):
                self.assertIn("%s:" % column, self.models)

    def test_every_new_table_has_an_orm_class(self):
        for table in ("rule_lifecycle_events", "ruleset_builds",
                      "ruleset_approvals"):
            with self.subTest(table=table):
                self.assertIn('__tablename__ = "%s"' % table, self.models)

    def test_the_orm_refuses_the_same_outcome_vocabulary(self):
        """The database refuses NOT_ASSESSED on a rule row. The ORM must
        refuse it too, or a developer reading the model would believe it is
        storable and find out from a constraint violation in production."""
        self.assertIn(
            '_RULE_OUTCOME_LEVELS = ("NO_ACTIVE_ATTENTION", "LOW", "MEDIUM", '
            '"HIGH")', self.models)
        self.assertIn('name="outcome_is_authorable"', self.models)

    def test_the_build_outcome_vocabulary_agrees_in_all_three_places(self):
        """SUCCEEDED / REFUSED / FAILED, spelled three times on purpose.

        The domain refuses any other value, migration 0008 refuses it in SQL,
        and the ORM has to refuse it too or a developer reading the model
        believes a fourth outcome is storable. The three are compared rather
        than assumed: this constant was referenced by the ORM's CHECK
        constraint before it was ever defined, which made the whole module
        un-importable, and nothing in the suite noticed until an integration
        test tried to import a repository.
        """
        # The domain, read out of its own guard rather than restated here.
        domain = source(os.path.join(REPO_ROOT, "pgx", "rules", "models.py"))
        self.assertIn(
            'if self.outcome not in ("SUCCEEDED", "REFUSED", "FAILED"):',
            domain)

        # The migration, read out of the constant the CHECK is rendered from.
        migration = source(MIGRATION_0008)
        self.assertIn(
            'BUILD_OUTCOMES = "\'SUCCEEDED\', \'REFUSED\', \'FAILED\'"',
            migration)

        # The ORM, read as source. This module compares declarations without
        # importing them, because the migration and the model must agree on a
        # host with no database driver installed as much as on one with.
        self.assertIn('_RULESET_BUILD_OUTCOMES = ("SUCCEEDED", "REFUSED", '
                      '"FAILED")', self.models)
        self.assertIn('CheckConstraint(_in_list("outcome", '
                      '_RULESET_BUILD_OUTCOMES),', self.models)

    def test_every_vocabulary_the_orm_names_actually_resolves(self):
        """The general form of the bug above, so the next one cannot hide.

        Importing the module is what proves it: a CHECK constraint built from
        an undefined name raises NameError at import, and every table
        definition after it in the file never runs - which is why the visible
        symptom was a duplicate-table error four modules away rather than a
        missing constant here.
        """
        import importlib

        try:
            import sqlalchemy  # noqa: F401
        except ImportError:
            self.skipTest(
                "sqlalchemy is not installed on this host, so the model "
                "cannot be imported. The declaration comparisons above run "
                "regardless; this one needs the import because an import is "
                "exactly what the bug broke.")

        module = importlib.import_module("pgx.infrastructure.db.models")
        vocabularies = [name for name in dir(module)
                        if name.startswith("_") and name.isupper()
                        or (name.startswith("_") and name.upper() == name)]
        self.assertIn("_RULESET_BUILD_OUTCOMES", vocabularies)
        for name in vocabularies:
            value = getattr(module, name)
            if isinstance(value, tuple) and value and all(
                    isinstance(item, str) for item in value):
                with self.subTest(vocabulary=name):
                    self.assertEqual(len(set(value)), len(value),
                                     "%s repeats a value" % name)


class TestTheRenderedSqlIsDerivedNotHandMaintained(unittest.TestCase):

    def test_the_renderer_exists_and_names_the_migration(self):
        path = os.path.join(REPO_ROOT, "scripts", "render_wp11_schema.py")
        self.assertTrue(os.path.isfile(path))
        self.assertIn("0008_wp11_rules_and_rulesets", source(path))

    def test_the_rendered_file_says_it_is_generated(self):
        path = os.path.join(REPO_ROOT, "build", "wp11-schema.sql")
        if not os.path.isfile(path):
            self.skipTest("rendered SQL is a build artifact, not committed")
        text = source(path)
        self.assertIn("GENERATED from", text)
        self.assertIn("Do not edit by hand", text)


if __name__ == "__main__":
    unittest.main()
