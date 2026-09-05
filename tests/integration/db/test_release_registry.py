# -*- coding: utf-8 -*-
"""The release registry against real PostgreSQL (WP-03).

Everything here needs a database. Without one the suite **skips with an explicit
reason**, and the reason says so: a skip is not a pass, and the WP-03 acceptance
report records these criteria as BLOCKED rather than green.

What only a real server can prove, and therefore what lives here rather than in
the offline suite:

* the ``0001 -> 0002 -> 0001 -> 0002`` migration cycle actually runs under
  Alembic, including ``alembic_version`` stamping;
* the singleton, generation, activation-metadata and audit CHECK constraints
  reject what they are meant to reject;
* the append-only trigger refuses ``UPDATE`` and ``DELETE``;
* ``SELECT ... FOR UPDATE`` on the pointer blocks a second transaction, and two
  activations reading the same generation cannot both commit.

The offline suite proves the *rules*; this suite proves the *mechanisms*.
"""

from __future__ import annotations

import datetime as _dt
import unittest

from tests.integration.db._support import (
    ALL_TABLES, PostgresTestCase, WP02_TABLES, WP03_TABLES, alembic_config,
    drop_wp02_objects, make_test_engine, require_postgres_dependencies,
)

ACTOR = "ops@example.org"
REASON = "integration drill"


class TestMigrationChain(unittest.TestCase):
    """0001 -> 0002 -> 0001 -> 0002 under the real Alembic runner."""

    @classmethod
    def setUpClass(cls):
        require_postgres_dependencies()
        cls.engine = make_test_engine()
        drop_wp02_objects(cls.engine)

    @classmethod
    def tearDownClass(cls):
        drop_wp02_objects(cls.engine)
        cls.engine.dispose()

    def _tables(self):
        from sqlalchemy import inspect
        return set(inspect(self.engine).get_table_names())

    def test_there_is_a_single_head_and_it_is_0002(self):
        from alembic.script import ScriptDirectory

        heads = ScriptDirectory.from_config(alembic_config()).get_heads()
        self.assertEqual(len(heads), 1, "expected one head, got %s" % (heads,))
        self.assertEqual(heads[0], "0002_wp03_release_registry")

    def test_0002_declares_0001_as_its_parent(self):
        from alembic.script import ScriptDirectory

        script = ScriptDirectory.from_config(alembic_config())
        revision = script.get_revision("0002_wp03_release_registry")
        self.assertEqual(revision.down_revision, "0001_wp02_foundation")

    def test_upgrading_to_0001_creates_only_the_foundation(self):
        from alembic import command

        command.upgrade(alembic_config(), "0001_wp02_foundation")
        tables = self._tables()
        self.assertTrue(set(WP02_TABLES) <= tables)
        self.assertEqual(set(WP03_TABLES) & tables, set(),
                         "0001 must not create the release registry")

    def test_upgrading_to_0002_adds_the_release_registry(self):
        from alembic import command

        command.upgrade(alembic_config(), "head")
        self.assertTrue(set(ALL_TABLES) <= self._tables())

    def test_the_singleton_pointer_row_exists_after_upgrade(self):
        from alembic import command
        from sqlalchemy import text

        command.upgrade(alembic_config(), "head")
        with self.engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT singleton_id, release_id, generation FROM active_release"
            )).all()
        self.assertEqual(len(rows), 1, "the pointer must be a singleton")
        self.assertEqual(rows[0][0], 1)
        self.assertIsNone(rows[0][1])
        self.assertEqual(rows[0][2], 0)

    def test_downgrading_to_0001_removes_only_the_release_registry(self):
        from alembic import command

        command.upgrade(alembic_config(), "head")
        command.downgrade(alembic_config(), "0001_wp02_foundation")
        tables = self._tables()
        self.assertEqual(set(WP03_TABLES) & tables, set())
        self.assertTrue(set(WP02_TABLES) <= tables,
                        "the downgrade must not touch 0001's tables")

    def test_the_downgrade_leaves_no_trigger_function_behind(self):
        from alembic import command
        from sqlalchemy import text

        command.upgrade(alembic_config(), "head")
        command.downgrade(alembic_config(), "0001_wp02_foundation")
        with self.engine.connect() as connection:
            count = connection.execute(text(
                "SELECT count(*) FROM pg_proc "
                "WHERE proname = 'pgx_audit_events_append_only'")).scalar_one()
        self.assertEqual(count, 0,
                         "a leftover function makes the next upgrade fail")

    def test_the_full_cycle_is_repeatable(self):
        from alembic import command

        config = alembic_config()
        command.upgrade(config, "head")
        command.downgrade(config, "0001_wp02_foundation")
        command.upgrade(config, "head")
        self.assertTrue(set(ALL_TABLES) <= self._tables())

    def test_no_identifier_would_be_truncated(self):
        from sqlalchemy import text

        from alembic import command

        command.upgrade(alembic_config(), "head")
        with self.engine.connect() as connection:
            over = connection.execute(text(
                "SELECT count(*) FROM ("
                " SELECT conname AS n FROM pg_constraint"
                "  WHERE connamespace = 'public'::regnamespace"
                " UNION ALL SELECT indexname FROM pg_indexes"
                "  WHERE schemaname = 'public'"
                ") x WHERE length(n) >= 63")).scalar_one()
        self.assertEqual(over, 0)


class TestReleaseRegistryConstraints(PostgresTestCase):
    """The CHECK, UNIQUE and FOREIGN KEY rules, exercised as SQL."""

    def _execute(self, statement, **parameters):
        from sqlalchemy import text

        with self.engine.begin() as connection:
            return connection.execute(text(statement), parameters)

    def _seed(self):
        """Insert a minimal, valid software/dataset/ruleset/release chain."""
        digest = "sha256:" + "1" * 64
        self._execute(
            "INSERT INTO software_versions (id, version, source_commit,"
            " source_tree_hash, manifest_hash, built_at) VALUES"
            " ('11111111-0000-4000-8000-000000000001', '0.3.0', 'abc',"
            " :tree, :manifest, now())",
            tree="sha256:" + "2" * 64, manifest=digest)
        self._execute(
            "INSERT INTO dataset_versions (id, public_id, status, manifest_hash,"
            " approved_by, approved_at) VALUES"
            " ('22222222-0000-4000-8000-000000000001', 'PGX-DATA-20260829-001',"
            " 'PUBLISHED', :digest, 'approver@example.org', now())",
            digest=digest)
        self._execute(
            "INSERT INTO ruleset_versions (id, public_id, status, manifest_hash,"
            " approved_by, approved_at) VALUES"
            " ('33333333-0000-4000-8000-000000000001', 'PGX-RULESET-20260829-001',"
            " 'FROZEN', :digest, 'approver@example.org', now())",
            digest=digest)
        self._execute(
            "INSERT INTO release_bundles (id, public_id, software_version_id,"
            " dataset_version_id, ruleset_version_id, manifest_json,"
            " manifest_hash, status) VALUES"
            " ('44444444-0000-4000-8000-000000000001', 'PGX-REL-20260829-001',"
            " '11111111-0000-4000-8000-000000000001',"
            " '22222222-0000-4000-8000-000000000001',"
            " '33333333-0000-4000-8000-000000000001', '{}'::jsonb, :digest,"
            " 'DRAFT')", digest=digest)

    def test_a_second_pointer_row_is_refused(self):
        from sqlalchemy.exc import IntegrityError

        with self.assertRaises(IntegrityError):
            self._execute(
                "INSERT INTO active_release (singleton_id, generation, updated_by)"
                " VALUES (2, 0, 'probe')")

    def test_a_negative_generation_is_refused(self):
        from sqlalchemy.exc import IntegrityError

        with self.assertRaises(IntegrityError):
            self._execute(
                "UPDATE active_release SET generation = -1 WHERE singleton_id = 1")

    def test_a_moved_pointer_must_name_a_release(self):
        from sqlalchemy.exc import IntegrityError

        with self.assertRaises(IntegrityError):
            self._execute(
                "UPDATE active_release SET generation = 1 WHERE singleton_id = 1")

    def test_a_draft_release_may_not_carry_activation_metadata(self):
        from sqlalchemy.exc import IntegrityError

        self._seed()
        with self.assertRaises(IntegrityError):
            self._execute(
                "UPDATE release_bundles SET activated_by = 'x' WHERE status = 'DRAFT'")

    def test_an_active_release_must_carry_activation_metadata(self):
        from sqlalchemy.exc import IntegrityError

        self._seed()
        with self.assertRaises(IntegrityError):
            self._execute(
                "UPDATE release_bundles SET status = 'ACTIVE'"
                " WHERE public_id = 'PGX-REL-20260829-001'")

    def test_an_unknown_release_status_is_refused(self):
        from sqlalchemy.exc import IntegrityError

        self._seed()
        with self.assertRaises(IntegrityError):
            self._execute(
                "UPDATE release_bundles SET status = 'NOT_A_STATUS'"
                " WHERE public_id = 'PGX-REL-20260829-001'")

    def test_a_malformed_public_id_is_refused(self):
        from sqlalchemy.exc import IntegrityError

        self._seed()
        with self.assertRaises(IntegrityError):
            self._execute(
                "UPDATE release_bundles SET public_id = 'PGX-REL-BAD'"
                " WHERE public_id = 'PGX-REL-20260829-001'")

    def test_a_duplicate_public_id_is_refused(self):
        from sqlalchemy.exc import IntegrityError

        self._seed()
        with self.assertRaises(IntegrityError):
            self._execute(
                "INSERT INTO release_bundles (id, public_id, software_version_id,"
                " dataset_version_id, ruleset_version_id, manifest_json,"
                " manifest_hash, status) VALUES"
                " ('44444444-0000-4000-8000-000000000002', 'PGX-REL-20260829-001',"
                " '11111111-0000-4000-8000-000000000001',"
                " '22222222-0000-4000-8000-000000000001',"
                " '33333333-0000-4000-8000-000000000001', '{}'::jsonb,"
                " :digest, 'DRAFT')", digest="sha256:" + "1" * 64)

    def test_a_pinned_ruleset_cannot_be_deleted(self):
        from sqlalchemy.exc import IntegrityError

        self._seed()
        with self.assertRaises(IntegrityError):
            self._execute(
                "DELETE FROM ruleset_versions"
                " WHERE public_id = 'PGX-RULESET-20260829-001'")

    def test_duplicate_ruleset_membership_is_refused(self):
        from sqlalchemy import text

        with self.engine.connect() as connection:
            constraint = connection.execute(text(
                "SELECT contype FROM pg_constraint"
                " WHERE conname = 'pk_ruleset_rules'")).scalar_one()
        self.assertEqual(constraint, "p",
                         "membership uniqueness rests on the composite key")

    def test_an_unknown_audit_action_is_refused(self):
        from sqlalchemy.exc import IntegrityError

        with self.assertRaises(IntegrityError):
            self._execute(
                "INSERT INTO audit_events (id, action, actor, object_type,"
                " object_id) VALUES ('55555555-0000-4000-8000-000000000001',"
                " 'NOT_AN_ACTION', 'p', 'release_bundle', 'x')")

    def test_a_pointer_event_must_name_the_new_release(self):
        from sqlalchemy.exc import IntegrityError

        with self.assertRaises(IntegrityError):
            self._execute(
                "INSERT INTO audit_events (id, action, actor, object_type,"
                " object_id) VALUES ('55555555-0000-4000-8000-000000000002',"
                " 'RELEASE_ACTIVATED', 'p', 'release_bundle', 'x')")


class TestAuditIsAppendOnlyInTheDatabase(PostgresTestCase):
    """Application promises do not survive a psql prompt. The trigger does."""

    def _insert(self):
        from sqlalchemy import text

        with self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO audit_events (id, action, actor, object_type,"
                " object_id) VALUES ('66666666-0000-4000-8000-000000000001',"
                " 'RELEASE_REGISTERED', 'probe@example.org', 'release_bundle',"
                " 'probe')"))

    def test_an_update_is_refused(self):
        from sqlalchemy import text
        from sqlalchemy.exc import DatabaseError

        self._insert()
        with self.assertRaises(DatabaseError):
            with self.engine.begin() as connection:
                connection.execute(text(
                    "UPDATE audit_events SET actor = 'tampered'"
                    " WHERE object_id = 'probe'"))

    def test_a_delete_is_refused(self):
        from sqlalchemy import text
        from sqlalchemy.exc import DatabaseError

        self._insert()
        with self.assertRaises(DatabaseError):
            with self.engine.begin() as connection:
                connection.execute(text(
                    "DELETE FROM audit_events WHERE object_id = 'probe'"))

    def test_the_row_survives_both_attempts(self):
        from sqlalchemy import text
        from sqlalchemy.exc import DatabaseError

        self._insert()
        for statement in ("UPDATE audit_events SET actor = 'tampered'"
                          " WHERE object_id = 'probe'",
                          "DELETE FROM audit_events WHERE object_id = 'probe'"):
            try:
                with self.engine.begin() as connection:
                    connection.execute(text(statement))
            except DatabaseError:
                pass
        with self.engine.connect() as connection:
            actor = connection.execute(text(
                "SELECT actor FROM audit_events WHERE object_id = 'probe'"
            )).scalar_one()
        self.assertEqual(actor, "probe@example.org")

    def test_an_insert_is_still_permitted(self):
        from sqlalchemy import text

        self._insert()
        with self.engine.connect() as connection:
            count = connection.execute(text(
                "SELECT count(*) FROM audit_events")).scalar_one()
        self.assertEqual(count, 1)


class TestConcurrentActivationTakesTheRowLock(PostgresTestCase):
    """Two activations reading the same generation must not both commit."""

    def test_a_second_transaction_blocks_on_the_pointer(self):
        from sqlalchemy import text
        from sqlalchemy.exc import OperationalError

        with self.engine.connect() as first:
            first.execute(text("BEGIN"))
            first.execute(text(
                "SELECT generation FROM active_release"
                " WHERE singleton_id = 1 FOR UPDATE"))
            with self.engine.connect() as second:
                second.execute(text("SET lock_timeout = '1000ms'"))
                second.execute(text("BEGIN"))
                with self.assertRaises(OperationalError):
                    second.execute(text(
                        "SELECT generation FROM active_release"
                        " WHERE singleton_id = 1 FOR UPDATE"))
                second.execute(text("ROLLBACK"))
            first.execute(text("ROLLBACK"))

    def test_only_one_generation_guarded_update_can_succeed(self):
        """The generation guard is what makes a lost update *detectable*.

        Both writers intend to move the pointer from generation 0. The first
        succeeds and the pointer becomes generation 1; the second names a
        generation that no longer exists and updates no rows, rather than
        silently overwriting the first writer's work.
        """
        from sqlalchemy import text

        digest = "sha256:" + "1" * 64
        with self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO software_versions (id, version, source_commit,"
                " source_tree_hash, manifest_hash, built_at) VALUES"
                " ('77777777-0000-4000-8000-000000000001', '0.3.0', 'abc',"
                " :tree, :digest, now())"),
                {"tree": "sha256:" + "3" * 64, "digest": digest})
            connection.execute(text(
                "INSERT INTO dataset_versions (id, public_id, status,"
                " manifest_hash, approved_by, approved_at) VALUES"
                " ('77777777-0000-4000-8000-000000000002',"
                " 'PGX-DATA-20260829-007', 'PUBLISHED', :digest,"
                " 'approver@example.org', now())"), {"digest": digest})
            connection.execute(text(
                "INSERT INTO ruleset_versions (id, public_id, status,"
                " manifest_hash, approved_by, approved_at) VALUES"
                " ('77777777-0000-4000-8000-000000000003',"
                " 'PGX-RULESET-20260829-007', 'FROZEN', :digest,"
                " 'approver@example.org', now())"), {"digest": digest})
            connection.execute(text(
                "INSERT INTO release_bundles (id, public_id,"
                " software_version_id, dataset_version_id, ruleset_version_id,"
                " manifest_json, manifest_hash, status, activated_at,"
                " activated_by) VALUES"
                " ('77777777-0000-4000-8000-000000000004',"
                " 'PGX-REL-20260829-007',"
                " '77777777-0000-4000-8000-000000000001',"
                " '77777777-0000-4000-8000-000000000002',"
                " '77777777-0000-4000-8000-000000000003', '{}'::jsonb,"
                " :digest, 'ACTIVE', now(), 'ops@example.org')"),
                {"digest": digest})

        move = (
            "UPDATE active_release SET generation = generation + 1,"
            " release_id = '77777777-0000-4000-8000-000000000004',"
            " updated_at = now(), updated_by = :actor"
            " WHERE singleton_id = 1 AND generation = 0")

        with self.engine.begin() as connection:
            first = connection.execute(text(move), {"actor": "A"}).rowcount
        with self.engine.begin() as connection:
            second = connection.execute(text(move), {"actor": "B"}).rowcount

        self.assertEqual(first, 1, "the first writer must win")
        self.assertEqual(second, 0,
                         "a stale expected_generation must update no rows")

        with self.engine.connect() as connection:
            generation, actor = connection.execute(text(
                "SELECT generation, updated_by FROM active_release"
                " WHERE singleton_id = 1")).one()
        self.assertEqual(generation, 1, "the generation advanced exactly once")
        self.assertEqual(actor, "A")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
