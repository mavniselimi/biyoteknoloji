# -*- coding: utf-8 -*-
"""The security tables, the constraints and migration 0011 - structurally.

PostgreSQL is unavailable in this environment. These tests read the SQLAlchemy
metadata and the migration's syntax tree; **no statement has been executed
against a server**, and nothing here should be read as saying otherwise. The
database-backed behaviour tests are marked skipped with that reason.

What can be checked without a server is more than it might seem: that the
password-hash column will only accept an argon2id string, that a session row
cannot hold a raw token, that no deletion cascades toward an audit row, that
the append-only trigger is installed, and that the downgrade refuses while
evidence exists.
"""

from __future__ import annotations

import ast
import io
import os
import unittest

from pgx.infrastructure.audit.vocabulary import AUDIT_ACTIONS
from pgx.infrastructure.db.base import metadata
# Imported for the side effect of registering their tables on the shared
# metadata. Without them the "historical tables are untouched" assertions
# below would pass by looking at a metadata object that simply never learned
# those tables existed - which is a much weaker statement than the one
# intended, and would keep passing if the tables were dropped.
import pgx.infrastructure.db.models  # noqa: F401
import pgx.infrastructure.db.expert_reviews  # noqa: F401
from pgx.infrastructure.db.security import (GOVERNED_AUDIT_TABLES,
                                            SECURITY_TABLES,
                                            SqlAlchemyAuditRepository,
                                            SqlAlchemySessionRepository,
                                            SqlAlchemyUserRepository)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                         "..", "..", ".."))
MIGRATION = os.path.join(REPO_ROOT, "migrations", "versions",
                         "0011_wp23_auth_audit.py")

_NO_DATABASE = ("PostgreSQL is not available in this environment, so no "
                "statement can be executed against a server")


def _table(name):
    return metadata.tables[name]


def _constraint_names(name):
    """Constraint and index names, as the naming convention renders them."""
    table = _table(name)
    names = {item.name for item in table.constraints if item.name}
    names |= {item.name for item in table.indexes}
    return names


def _has_constraint(table_name, suffix):
    return any(str(item).endswith(suffix)
               for item in _constraint_names(table_name))


def _migration_source():
    with io.open(MIGRATION, encoding="utf-8") as handle:
        return handle.read()


class TestTheTablesExist(unittest.TestCase):

    def test_every_declared_table_is_in_the_metadata(self):
        for name in SECURITY_TABLES + GOVERNED_AUDIT_TABLES:
            with self.subTest(table=name):
                self.assertIn(name, metadata.tables)

    def test_the_historical_audit_table_is_untouched(self):
        """``audit_events`` from migration 0002 keeps its name and its rows.

        The canonical stream is a *successor*, not a replacement. A migration
        that renamed or absorbed the old table would make every historical row
        look like it had been written under the new contract.
        """
        self.assertIn("audit_events", metadata.tables)
        self.assertNotEqual("audit_events", "governed_audit_events")
        columns = set(_table("audit_events").columns.keys())
        self.assertNotIn("auth_assurance", columns)
        self.assertNotIn("session_reference", columns)

    def test_wp22_review_tables_are_untouched(self):
        self.assertIn("expert_review_audit_events", metadata.tables)


class TestTheUserTableRefusesAWeakHash(unittest.TestCase):

    def test_the_password_hash_column_demands_argon2id(self):
        """The database is the layer that survives a refactor. A row holding
        a bcrypt or PBKDF2 hash would mean some other code path wrote it."""
        self.assertTrue(_has_constraint("security_users",
                                        "password_hash_is_argon2id"))

    def test_the_password_hash_is_not_nullable(self):
        self.assertFalse(_table("security_users").columns[
            "password_hash"].nullable)

    def test_the_username_is_unique_and_canonical(self):
        self.assertTrue(_has_constraint("security_users", "username"))
        self.assertTrue(_has_constraint("security_users",
                                        "username_is_canonical"))

    def test_role_and_status_are_constrained_to_the_vocabularies(self):
        for suffix in ("role_enum", "status_enum"):
            with self.subTest(constraint=suffix):
                self.assertTrue(_has_constraint("security_users", suffix))

    def test_only_a_locked_account_carries_a_lock_expiry(self):
        self.assertTrue(_has_constraint(
            "security_users", "only_a_locked_account_has_a_lock_expiry"))

    def test_the_generation_counter_cannot_go_below_one(self):
        self.assertTrue(_has_constraint("security_users",
                                        "generation_positive"))


class TestTheSessionTableCannotHoldAToken(unittest.TestCase):

    def test_the_stored_value_must_be_a_sha256_digest(self):
        self.assertTrue(_has_constraint("security_sessions",
                                        "token_digest_format"))

    def test_there_is_no_column_a_raw_token_could_occupy(self):
        """Blinding by absence, the same construction WP-22 uses: the shape
        has nowhere to put the value."""
        columns = set(_table("security_sessions").columns.keys())
        for forbidden in ("token", "session_token", "raw_token", "cookie",
                          "secret_token"):
            with self.subTest(column=forbidden):
                self.assertNotIn(forbidden, columns)

    def test_the_digest_is_unique(self):
        self.assertTrue(_has_constraint("security_sessions", "token_digest"))

    def test_both_expiry_bounds_are_stored_and_ordered(self):
        columns = _table("security_sessions").columns
        self.assertIn("idle_expires_at", columns)
        self.assertIn("absolute_expires_at", columns)
        self.assertTrue(_has_constraint(
            "security_sessions", "absolute_bound_not_before_idle"))

    def test_a_revoked_session_names_its_reason(self):
        self.assertTrue(_has_constraint("security_sessions",
                                        "revocation_names_its_reason"))
        self.assertTrue(_has_constraint("security_sessions",
                                        "revocation_reason_enum"))


class TestNoDeletionCascadesTowardEvidence(unittest.TestCase):

    def test_every_foreign_key_in_the_security_tables_restricts(self):
        """CASCADE anywhere near a user would delete the sessions that are
        the evidence a compromised account was used."""
        for name in SECURITY_TABLES + GOVERNED_AUDIT_TABLES:
            for key in _table(name).foreign_keys:
                with self.subTest(table=name, column=key.parent.name):
                    self.assertEqual(key.ondelete, "RESTRICT")

    def test_the_audit_table_has_no_foreign_key_at_all(self):
        """An audit row references an actor by value, not by key. A foreign
        key would mean a deletion somewhere could orphan or block an audit
        row, and neither outcome is acceptable for evidence."""
        self.assertEqual(list(_table("governed_audit_events").foreign_keys),
                         [])


class TestTheAuditTableExpressesTheChain(unittest.TestCase):

    def test_the_sequence_is_unique_within_the_stream(self):
        self.assertTrue(_has_constraint("governed_audit_events",
                                        "stream_sequence"))

    def test_the_first_event_starts_the_chain(self):
        self.assertTrue(_has_constraint(
            "governed_audit_events", "first_event_starts_the_chain"))

    def test_the_event_hash_is_unique_and_formatted(self):
        self.assertTrue(_has_constraint("governed_audit_events",
                                        "event_hash"))
        self.assertTrue(_has_constraint("governed_audit_events",
                                        "event_hash_format"))

    def test_only_a_session_may_carry_session_assurance(self):
        """Enforced in the database as well as in the model, because a direct
        insert bypasses the model and cannot bypass the server."""
        self.assertTrue(_has_constraint(
            "governed_audit_events", "only_a_session_has_assurance"))
        self.assertTrue(_has_constraint(
            "governed_audit_events", "session_event_names_its_session"))

    def test_the_action_vocabulary_matches_the_registry(self):
        source = _migration_source()
        for action in AUDIT_ACTIONS:
            with self.subTest(action=action):
                self.assertIn("'%s'" % action, source)

    def test_the_head_table_exists_and_is_one_row_per_stream(self):
        self.assertTrue(_has_constraint("governed_audit_stream_head",
                                        "stream_id"))
        self.assertTrue(_has_constraint(
            "governed_audit_stream_head", "empty_stream_has_no_hash"))


class TestTheRepositoriesCannotMutateEvidence(unittest.TestCase):

    def test_the_audit_repository_exposes_no_update_or_delete(self):
        for name in ("update", "delete", "remove", "truncate", "edit",
                     "rewrite", "purge"):
            with self.subTest(method=name):
                self.assertFalse(hasattr(SqlAlchemyAuditRepository, name))

    def test_the_user_and_session_repositories_expose_no_delete(self):
        for repository in (SqlAlchemyUserRepository,
                           SqlAlchemySessionRepository):
            for name in ("delete", "remove", "purge", "drop"):
                with self.subTest(repository=repository.__name__,
                                  method=name):
                    self.assertFalse(hasattr(repository, name))

    def test_the_audit_repository_locks_the_head_before_appending(self):
        """The concurrency story, asserted in the source: without
        ``with_for_update`` two transactions read the same tail and each
        produce a valid-looking event at the same sequence."""
        import inspect
        source = inspect.getsource(SqlAlchemyAuditRepository.head_for_update)
        self.assertIn("with_for_update", source)


class TestTheMigration(unittest.TestCase):

    def setUp(self):
        self.source = _migration_source()
        self.tree = ast.parse(self.source)

    def _assignment(self, name):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == name:
                        return ast.literal_eval(node.value)
                    if isinstance(target, ast.Name):
                        continue
            if isinstance(node, ast.AnnAssign) and \
                    isinstance(node.target, ast.Name) and \
                    node.target.id == name:
                return ast.literal_eval(node.value)
        raise AssertionError("%s is not assigned in the migration" % name)

    def test_it_follows_0010(self):
        self.assertEqual(self._assignment("revision"), "0011_wp23_auth_audit")
        self.assertEqual(self._assignment("down_revision"),
                         "0010_wp22_expert_reviews")

    def test_it_creates_every_declared_table(self):
        for name in SECURITY_TABLES + GOVERNED_AUDIT_TABLES:
            with self.subTest(table=name):
                self.assertIn('"%s"' % name, self.source)

    def test_it_installs_the_append_only_trigger(self):
        """The trigger is created in a loop over ``APPEND_ONLY_TABLES``, so
        the table name is interpolated rather than written out. Assert the
        loop covers the audit table rather than assuming a literal."""
        self.assertIn("pgx_governed_audit_append_only", self.source)
        self.assertIn("BEFORE UPDATE OR DELETE ON %s", self.source)
        self.assertIn('APPEND_ONLY_TABLES = ("governed_audit_events",)',
                      self.source)

    def test_it_installs_the_chain_guard(self):
        """The server-side half of the fork prevention: an insert whose
        sequence does not follow the recorded head is refused."""
        self.assertIn("pgx_governed_audit_chain_guard", self.source)
        self.assertIn("FOR UPDATE", self.source)
        self.assertIn("does not follow the recorded head", self.source)

    def test_it_seeds_exactly_one_stream_head(self):
        self.assertIn("INSERT INTO governed_audit_stream_head", self.source)

    def test_it_changes_wp22s_constraint_in_the_open(self):
        """0010 pinned ``actor_authenticated = false`` and said WP-23 would
        change it in a reviewed migration. This is that change."""
        self.assertIn(
            "ck_expert_review_audit_events_no_p0_principal_is_authenticated",
            self.source)
        self.assertIn(
            "ck_expert_review_audit_events_authentication_is_boolean",
            self.source)

    def test_it_rewrites_no_historical_audit_row(self):
        """No backfill, ever. A historical row was written by a system with
        no authentication, and giving it an assurance level would be
        manufacturing provenance."""
        for forbidden in ("UPDATE audit_events", "INSERT INTO audit_events",
                          "INSERT INTO governed_audit_events SELECT",
                          "DELETE FROM audit_events",
                          "UPDATE expert_review_audit_events"):
            with self.subTest(statement=forbidden):
                self.assertNotIn(forbidden, self.source)

    def test_the_downgrade_refuses_while_evidence_exists(self):
        downgrade = self.source.split("def downgrade()")[1]
        self.assertIn("refusing to downgrade", downgrade)
        for table in ("governed_audit_events", "security_sessions",
                      "security_users"):
            with self.subTest(table=table):
                self.assertIn(table, downgrade)

    def test_it_contains_no_default_user_or_password(self):
        """A2. Not one row of account data is created by this migration."""
        for forbidden in ("INSERT INTO security_users",
                          "INSERT INTO security_sessions",
                          "password_hash) VALUES", "'admin'", "'password'",
                          "changeme", "$argon2id$$"):
            with self.subTest(marker=forbidden):
                self.assertNotIn(forbidden, self.source)

    def test_it_states_that_it_has_not_been_executed(self):
        self.assertIn("has not been executed", self.source)

    def test_every_orm_constraint_name_appears_in_the_migration(self):
        """The ORM and the migration must spell each constraint identically.

        Written after they did not. The session table's ordering constraint
        was ``absolute_bound_is_not_before_idle_bound`` in the model and
        ``absolute_bound_not_before_idle`` in the migration - two names for
        one rule, which is exactly the drift the naming convention exists to
        prevent, arriving by hand instead. A mismatch is invisible until
        somebody writes a migration that drops a constraint by name and finds
        the name is not there.
        """
        for name in SECURITY_TABLES + GOVERNED_AUDIT_TABLES:
            for constraint in _constraint_names(name):
                # Indexes are created by ``op.create_index`` with the same
                # name; check constraints and unique constraints appear as
                # string literals. Either way the rendered name must be in
                # the migration source.
                rendered = str(constraint)
                if rendered.startswith("pk_"):
                    # Primary keys are derived from the naming convention by
                    # Alembic itself; a hand-written migration never spells
                    # one out, so requiring it here would be requiring noise.
                    continue
                with self.subTest(table=name, constraint=rendered):
                    self.assertIn(rendered, self.source)


@unittest.skip(_NO_DATABASE)
class TestAgainstARealDatabase(unittest.TestCase):  # pragma: no cover
    """What a PostgreSQL server would let us check, honestly not run.

    Skipped with a named reason rather than deleted, so the gap between what
    is proven and what is claimed stays visible in the test output.
    """

    def test_the_append_only_trigger_refuses_update_and_delete(self):
        raise AssertionError("requires PostgreSQL")

    def test_two_concurrent_appends_cannot_fork_the_chain(self):
        raise AssertionError("requires PostgreSQL")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
