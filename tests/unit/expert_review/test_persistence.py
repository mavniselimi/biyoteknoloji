# -*- coding: utf-8 -*-
"""The tables, the constraints and the migration - structurally.

PostgreSQL is unavailable in this environment. These tests read the SQLAlchemy
metadata and the migration's syntax tree; **no statement has been executed
against a server**, and nothing here should be read as saying otherwise. The
database-backed behaviour tests are marked skipped with that reason.

What can be checked without a server is more than it might seem: which
constraints exist, which columns they cover, that the ordering invariants are
expressed as foreign keys rather than as rules, and that the migration creates
and drops exactly what it says it does.
"""

from __future__ import annotations

import ast
import io
import os
import unittest

from pgx.infrastructure.db.base import metadata
from pgx.infrastructure.db.expert_reviews import (EXPERT_REVIEW_AUDIT_ACTIONS,
                                                  EXPERT_REVIEW_TABLES,
                                                  SqlAlchemyExpertReviewRepository)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                         "..", "..", ".."))
MIGRATION = os.path.join(REPO_ROOT, "migrations", "versions",
                         "0010_wp22_expert_reviews.py")


def _table(name):
    return metadata.tables[name]


def _constraint_names(name):
    """Constraint and index names, as the naming convention renders them.

    The convention prefixes everything (``ck_<table>_<name>``), so tests match
    on the distinctive suffix rather than retyping the prefix at every call
    site - which would make a convention change look like fifteen failures
    instead of one.
    """
    table = _table(name)
    return {item.name for item in table.constraints if item.name} | \
        {index.name for index in table.indexes}


def _has_constraint(table_name: str, suffix: str) -> bool:
    return any(name.endswith(suffix) for name in _constraint_names(table_name))


class TestTheTablesExist(unittest.TestCase):

    def test_all_seven_are_mapped(self):
        for name in EXPERT_REVIEW_TABLES:
            with self.subTest(table=name):
                self.assertIn(name, metadata.tables)

    def test_no_table_holds_a_payload_column(self):
        """Case inputs stay in restricted storage. Copying one here would put
        holdout material in a database reviewers and operators both reach."""
        forbidden = ("payload", "phenotype", "medication", "genotype", "vcf",
                     "patient", "report_text", "case_content")
        for name in EXPERT_REVIEW_TABLES:
            columns = {column.name.lower() for column in _table(name).columns}
            for term in forbidden:
                with self.subTest(table=name, term=term):
                    self.assertFalse([column for column in columns
                                      if term in column])


class TestOrderingIsReferentialRatherThanARule(unittest.TestCase):
    """The neatest part of the schema, and worth asserting directly."""

    def test_a_reveal_must_name_an_expectation_revision_that_exists(self):
        targets = {list(key.elements)[0].target_fullname
                   for key in _table("expert_review_reveals")
                   .foreign_key_constraints}
        self.assertIn("expert_review_expectations.revision_id", targets)

    def test_a_completion_must_name_a_reveal_that_exists(self):
        table = _table("expert_review_completions")
        targets = {list(key.elements)[0].target_fullname
                   for key in table.foreign_key_constraints}
        self.assertIn("expert_review_reveals.reveal_id", targets)

    def test_every_foreign_key_restricts_deletion(self):
        """No cascade silently destroys review evidence."""
        for name in EXPERT_REVIEW_TABLES:
            for key in _table(name).foreign_key_constraints:
                with self.subTest(table=name, key=key.name):
                    self.assertEqual(key.ondelete, "RESTRICT")


class TestTheUniquenessInvariants(unittest.TestCase):

    def test_one_reveal_per_review(self):
        self.assertTrue(_has_constraint("expert_review_reveals", "one_reveal_per_review"))

    def test_one_completion_per_review(self):
        self.assertTrue(_has_constraint("expert_review_completions", "one_completion_per_review"))

    def test_one_live_assignment_per_reviewer_case_and_release(self):
        self.assertTrue(_has_constraint("expert_review_assignments", "case_reviewer_release"))

    def test_one_expectation_revision_number_per_review(self):
        self.assertTrue(_has_constraint("expert_review_expectations", "review_revision"))

    def test_one_rating_per_dimension_per_completion(self):
        self.assertTrue(_has_constraint("expert_review_ratings", "completion_dimension"))

    def test_one_audit_sequence_per_review(self):
        self.assertTrue(_has_constraint("expert_review_audit_events", "review_sequence"))


class TestTheControlledVocabulariesArePinned(unittest.TestCase):

    def test_only_expert_holdout_is_assignable(self):
        self.assertTrue(_has_constraint("expert_review_assignments", "case_role_is_expert_holdout"))

    def test_only_the_reviewer_role_holds_an_assignment(self):
        self.assertTrue(_has_constraint("expert_review_assignments", "reviewer_role_is_expert_reviewer"))

    def test_the_decision_vocabulary_is_constrained(self):
        self.assertTrue(_has_constraint("expert_review_completions", "decision_enum"))

    def test_ratings_are_bounded_and_named(self):
        for suffix in ("dimension_enum", "value_bounded"):
            with self.subTest(constraint=suffix):
                self.assertTrue(_has_constraint("expert_review_ratings",
                                                suffix))

    def test_no_p0_principal_is_recorded_as_authenticated(self):
        self.assertTrue(_has_constraint("expert_review_audit_events",
                                        "no_p0_principal_is_authenticated"))

    def test_the_first_audit_event_starts_the_chain(self):
        self.assertTrue(_has_constraint("expert_review_audit_events", "first_event_starts_the_chain"))

    def test_an_invalidated_assignment_names_its_reason(self):
        self.assertTrue(_has_constraint("expert_review_assignments", "invalidated_names_its_reason"))


class TestTheRepositoryCannotMutate(unittest.TestCase):

    def test_it_offers_no_update_or_delete(self):
        names = {name for name in dir(SqlAlchemyExpertReviewRepository)
                 if not name.startswith("_")}
        for forbidden in ("update", "delete", "remove", "replace", "merge"):
            with self.subTest(method=forbidden):
                self.assertNotIn(forbidden, names)

    def test_it_does_not_commit(self):
        """The unit of work owns the transaction, so the audit event and the
        act it describes can be made to land together."""
        import inspect
        source = inspect.getsource(SqlAlchemyExpertReviewRepository)
        body = "\n".join(line for line in source.splitlines()
                         if not line.lstrip().startswith("#"))
        self.assertNotIn(".commit()", body)

    def test_it_locks_the_assignment_row_for_a_transition(self):
        """Row locking is what makes one-expectation-one-reveal-one-completion
        hold under concurrency; the unique constraints are the second line."""
        import inspect
        source = inspect.getsource(
            SqlAlchemyExpertReviewRepository.assignment_row_for_update)
        self.assertIn("with_for_update", source)


class TestTheMigration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with io.open(MIGRATION, encoding="utf-8") as handle:
            cls.source = handle.read()
        cls.tree = ast.parse(cls.source)

    def _function(self, name):
        for node in self.tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        raise AssertionError("no %s()" % name)

    def _calls(self, function, attribute):
        return [node for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and getattr(node.func, "attr", None) == attribute]

    def test_it_follows_0009(self):
        assignments = {}
        for node in self.tree.body:
            if isinstance(node, ast.AnnAssign) and \
                    isinstance(node.target, ast.Name) and \
                    isinstance(node.value, ast.Constant):
                assignments[node.target.id] = node.value.value
        self.assertEqual(assignments["revision"], "0010_wp22_expert_reviews")
        self.assertEqual(assignments["down_revision"], "0009_wp14_assessments")

    def test_it_creates_exactly_the_seven_review_tables(self):
        created = [node.args[0].value
                   for node in self._calls(self._function("upgrade"),
                                           "create_table")]
        self.assertEqual(created, list(EXPERT_REVIEW_TABLES))

    def test_it_drops_no_table_or_column_on_upgrade(self):
        upgrade = self._function("upgrade")
        for attribute in ("drop_table", "drop_column"):
            with self.subTest(operation=attribute):
                self.assertEqual(self._calls(upgrade, attribute), [])

    def test_the_only_existing_object_it_touches_is_the_audit_action_list(self):
        upgrade = self._function("upgrade")
        dropped = [node.args[1].value
                   for node in self._calls(upgrade, "drop_constraint")]
        self.assertEqual(dropped, ["audit_events"])

    def test_the_downgrade_drops_every_table_it_created(self):
        created = {node.args[0].value
                   for node in self._calls(self._function("upgrade"),
                                           "create_table")}
        dropped = {node.args[0].value
                   for node in self._calls(self._function("downgrade"),
                                           "drop_table")}
        self.assertEqual(created, dropped)

    def test_the_downgrade_refuses_when_reviews_exist(self):
        downgrade = ast.get_source_segment(self.source,
                                           self._function("downgrade"))
        self.assertIn("refusing to downgrade", downgrade)
        self.assertIn("SELECT count(*) FROM expert_review_assignments",
                      downgrade)

    def test_every_append_only_table_gets_a_trigger(self):
        self.assertIn("pgx_expert_review_append_only", self.source)
        self.assertIn("trg_%s_append_only", self.source)

    def test_the_assignment_table_moves_forward_only(self):
        self.assertIn("pgx_expert_review_forward_only", self.source)
        for forward in ("'ASSIGNED'", "'EXPECTATION_RECORDED'",
                        "'RESULT_REVEALED'", "'COMPLETED'"):
            with self.subTest(state=forward):
                self.assertIn(forward, self.source)

    def test_the_forward_trigger_pins_everything_but_the_state(self):
        self.assertIn("only the state of an assignment may change",
                      self.source)

    def test_the_audit_action_list_widens_rather_than_replaces(self):
        self.assertIn("AUDIT_ACTIONS_0010 = AUDIT_ACTIONS_0009", self.source)
        for action in EXPERT_REVIEW_AUDIT_ACTIONS:
            with self.subTest(action=action):
                self.assertIn("'%s'" % action, self.source)

    def test_it_states_that_it_has_not_been_executed(self):
        """The honesty the environment requires: writing a migration is not
        running one, and the docstring says which happened."""
        self.assertIn("has not been executed", self.source)


class TestPostgresqlWasNotExercised(unittest.TestCase):
    """Reported, not claimed away."""

    def test_no_server_is_available(self):
        try:
            import psycopg  # noqa: F401
        except ImportError:
            available = False
        else:
            available = bool(os.environ.get("PGX_TEST_DATABASE_URL"))
        self.assertFalse(
            available,
            "a database is reachable; the skipped integration tests below "
            "should be enabled and this assertion updated")

    @unittest.skip("no PostgreSQL server is available in this environment; "
                   "the append-only triggers, the forward-only transition "
                   "trigger and the referential ordering constraints are "
                   "written and unit-tested structurally, and have not been "
                   "executed against a server")
    def test_the_triggers_refuse_an_update(self):  # pragma: no cover
        raise AssertionError("unreachable")

    @unittest.skip("no PostgreSQL server is available in this environment")
    def test_a_second_reveal_violates_the_unique_constraint(self):  # pragma: no cover
        raise AssertionError("unreachable")
