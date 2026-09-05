# -*- coding: utf-8 -*-
"""Schema contract checks for the WP-08 migration (needs no database driver).

The Alembic migration is the authority. These tests read it directly and read
the SQL rendered from it, so the structural guarantees hold in an environment
where Alembic and SQLAlchemy cannot be installed.

Five things beyond shape are asserted here.

**0006 adds and never rewrites 0001-0005.** It creates eight tables, widens
``evidence_records``, and replaces exactly one constraint - the provenance
uniqueness that a nullable version made unrepresentable.

**An unknown legacy version is representable honestly.** ``NOT NULL`` is
dropped from ``source_record_version`` and a status column carries the reason,
under a constraint that lets only ``KNOWN`` hold a value. A fake ``v1`` is
refused by the database, not by a convention in a service.

**Every check constraint is total.** SQL three-valued logic makes a CHECK pass
when it evaluates to NULL, so a disjunct over a nullable column silently admits
the rows it was written to refuse. Two constraints did exactly that and are
asserted here by shape.

**A finalized record is immutable in every column.** The trigger compares whole
rows rather than a list of protected columns, because a named list is an
allowlist by omission and every column added later would default to mutable.

**No project interpretation column appears anywhere.** Not in the tables, not
in the rendered DDL.
"""

from __future__ import annotations

import ast
import io
import os
import re
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
from render_wp08_schema import render_schema  # noqa: E402

MIGRATION_PATH = os.path.join(REPO_ROOT, "migrations", "versions",
                              "0006_wp08_evidence_store.py")

EXPECTED_TABLES = ("evidence_builds", "evidence_genes", "evidence_drugs",
                   "evidence_text_fragments", "publication_references",
                   "evidence_publications", "evidence_provenance",
                   "evidence_import_issues")

ADDED_COLUMNS = ("evidence_build_id", "natural_key", "record_type",
                 "source_object_class", "record_type_mapping_status",
                 "source_record_version_status", "source_record_id_raw_type",
                 "origin_source_id", "origin_source_status",
                 "raw_origin_value", "source_payload_hash",
                 "evidence_content_hash", "production_eligible",
                 "finalized_at")

PROJECT_COLUMNS = ("risk", "risk_level", "demo_risk_level", "risk_meaning",
                   "attention_level", "plain_language", "plain_language_mvp",
                   "evidence_strength", "usable_for_mvp",
                   "drug_behavior_hint", "effect_direction",
                   "normalized_phenotype", "normalized_phenotype_group",
                   "candidate_score", "candidate_preference",
                   "treatment_selection", "matcher_condition")


def _text() -> str:
    with io.open(MIGRATION_PATH, encoding="utf-8") as handle:
        return handle.read()


def _tree() -> ast.Module:
    return ast.parse(_text(), filename=MIGRATION_PATH)


def _upgrade_sql() -> str:
    return render_schema(direction="upgrade")


def _downgrade_sql() -> str:
    return render_schema(direction="downgrade")


class TestMigrationShape(unittest.TestCase):

    def test_it_declares_0005_as_its_parent(self):
        assignments = {}
        for node in _tree().body:
            if isinstance(node, ast.AnnAssign) and \
                    isinstance(node.target, ast.Name):
                try:
                    assignments[node.target.id] = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    continue
        self.assertEqual(assignments.get("revision"),
                         "0006_wp08_evidence_store")
        self.assertEqual(assignments.get("down_revision"),
                         "0005_wp07_canonicalization")

    def test_it_creates_exactly_the_eight_expected_tables(self):
        sql = _upgrade_sql()
        created = set(re.findall(r"CREATE TABLE (\w+)", sql))
        self.assertEqual(created, set(EXPECTED_TABLES))

    def test_it_adds_every_column_the_evidence_record_contract_needs(self):
        sql = _upgrade_sql()
        for column in ADDED_COLUMNS:
            with self.subTest(column=column):
                self.assertIn("ADD COLUMN %s" % column, sql)

    def test_it_rewrites_no_earlier_migration(self):
        directory = os.path.join(REPO_ROOT, "migrations", "versions")
        earlier = [name for name in sorted(os.listdir(directory))
                   if name.endswith(".py") and name < "0006"]
        self.assertTrue(earlier)
        for name in earlier:
            with io.open(os.path.join(directory, name),
                         encoding="utf-8") as handle:
                body = handle.read()
            self.assertNotIn("wp08", body.lower(),
                             "%s mentions WP-08, so it was edited" % name)

    def test_it_opens_no_connection_at_import_time(self):
        for node in _tree().body:
            if isinstance(node, ast.Expr):
                self.assertIsInstance(node.value, ast.Constant)
                continue
            self.assertIsInstance(
                node, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign,
                       ast.FunctionDef, ast.ClassDef))

    def test_every_identifier_fits_postgres(self):
        """A truncated identifier would make downgrade() drop nothing."""
        too_long = over_length_identifiers(_upgrade_sql())
        self.assertEqual(too_long, [],
                         "identifiers over %d bytes: %s"
                         % (POSTGRES_IDENTIFIER_LIMIT, too_long))


class TestUnknownVersionsAreRepresentableHonestly(unittest.TestCase):

    def test_the_not_null_on_the_version_column_is_dropped(self):
        self.assertIn("ALTER COLUMN source_record_version DROP NOT NULL",
                      _upgrade_sql())

    def test_a_status_column_carries_the_reason(self):
        sql = _upgrade_sql()
        self.assertIn("ADD COLUMN source_record_version_status", sql)
        self.assertIn("UNKNOWN_LEGACY", sql)

    def test_only_a_known_version_may_carry_a_value(self):
        """This is what refuses a fabricated ``v1`` in the database."""
        sql = _upgrade_sql()
        constraint = self._constraint(
            sql, "ck_evidence_records_version_status_consistent")
        self.assertIn("KNOWN", constraint)
        self.assertIn("source_record_version IS NULL", constraint)

    def test_the_provenance_unique_constraint_is_replaced_not_kept(self):
        """0001's key included the version. With the version nullable, that
        key stops being unique, so it is replaced by the natural key."""
        sql = _upgrade_sql()
        self.assertIn("DROP CONSTRAINT uq_evidence_records_provenance", sql)
        self.assertIn("uq_evidence_records_natural_key", sql)

    @staticmethod
    def _constraint(sql, name):
        for line in sql.splitlines():
            if name in line:
                return line
        raise AssertionError("no constraint named %s in the rendered DDL"
                             % name)


class TestEveryCheckConstraintIsTotal(unittest.TestCase):
    """SQL admits a row whose CHECK evaluates to NULL, not just to true.

    So a disjunct like ``identity = 'doi:' || doi`` is not a refusal when
    ``doi`` is NULL - it is silence, and the row is accepted. Both places this
    happened are asserted by shape here, because a database is needed to
    observe the behaviour but the shape is checkable without one.
    """

    def _constraint(self, name):
        for line in _upgrade_sql().splitlines():
            if name in line:
                return line
        raise AssertionError("no constraint named %s" % name)

    def test_publication_identity_guards_each_column_for_null(self):
        constraint = self._constraint(
            "ck_publication_references_identity_matches")
        self.assertIn("pmid IS NOT NULL", constraint)
        self.assertIn("doi IS NOT NULL", constraint)

    def test_production_eligibility_guards_the_nullable_mapping_status(self):
        constraint = self._constraint("ck_evidence_records_eligible_is_complete")
        self.assertIn("record_type_mapping_status IS NOT NULL", constraint)

    def test_every_nullable_column_named_in_a_check_is_null_guarded(self):
        """A structural sweep, so a constraint added later cannot reintroduce
        the same hole without this failing."""
        sql = _upgrade_sql()
        offences = []
        for line in sql.splitlines():
            if "CHECK" not in line or "||" not in line:
                continue
            for column in re.findall(r"\|\|\s*(\w+)", line):
                if "%s IS NOT NULL" % column not in line:
                    offences.append((line.strip()[:70], column))
        self.assertEqual(offences, [])


class TestAFinalizedRecordIsImmutable(unittest.TestCase):

    def test_the_trigger_compares_whole_rows(self):
        """Not a list of protected columns: an omitted column is an allowlist
        entry nobody wrote down, and a column added later defaults to mutable."""
        sql = _upgrade_sql()
        self.assertIn("NEW IS DISTINCT FROM OLD", sql)

    def test_the_trigger_names_no_individual_column_to_protect(self):
        sql = _upgrade_sql()
        function = sql[sql.index("pgx_evidence_records_finalized_immutable"):]
        function = function[:function.index("$$ LANGUAGE plpgsql")]
        for column in ("NEW.natural_key", "NEW.source_record_id",
                       "NEW.raw_hash", "NEW.evidence_content_hash"):
            self.assertNotIn(column, function)

    def test_deletion_is_refused_outright(self):
        sql = _upgrade_sql()
        self.assertIn("TG_OP = 'DELETE'", sql)
        self.assertIn("BEFORE UPDATE OR DELETE ON evidence_records", sql)


class TestTheStoreHoldsNoProjectInterpretation(unittest.TestCase):

    def test_no_rendered_column_is_a_project_conclusion(self):
        sql = _upgrade_sql()
        columns = set(re.findall(r"^\s+(\w+)\s+(?:VARCHAR|TEXT|INTEGER|"
                                 r"BOOLEAN|JSONB|UUID|TIMESTAMP)",
                                 sql, re.MULTILINE))
        columns.update(re.findall(r"ADD COLUMN (\w+)", sql))
        for forbidden in PROJECT_COLUMNS:
            with self.subTest(column=forbidden):
                self.assertNotIn(forbidden, columns)

    def test_no_table_carries_an_approval_default(self):
        """A default reviewer or approval timestamp would make every row look
        signed off by nobody in particular."""
        sql = _upgrade_sql()
        for forbidden in ("approved_by", "approved_at", "reviewed_by",
                          "curated_by", "signed_off_by"):
            for line in sql.splitlines():
                if "CREATE TABLE" in line or forbidden not in line:
                    continue
                self.assertNotIn("DEFAULT", line,
                                 "%s carries a default: %s"
                                 % (forbidden, line.strip()))


class TestTheDowngradeUndoesExactlyThisMigration(unittest.TestCase):

    def test_it_drops_every_table_this_migration_created(self):
        sql = _downgrade_sql()
        for table in EXPECTED_TABLES:
            with self.subTest(table=table):
                self.assertIn("DROP TABLE %s" % table, sql)

    def test_it_drops_every_column_this_migration_added(self):
        sql = _downgrade_sql()
        for column in ADDED_COLUMNS:
            with self.subTest(column=column):
                self.assertIn("DROP COLUMN %s" % column, sql)

    def test_the_added_columns_go_before_the_created_tables(self):
        """``evidence_build_id`` holds a foreign key into ``evidence_builds``.
        Dropping the table first fails, which an earlier ordering did."""
        sql = _downgrade_sql()
        self.assertLess(sql.index("DROP COLUMN evidence_build_id"),
                        sql.index("DROP TABLE evidence_builds"))

    def test_it_restores_what_0001_owned_last_of_all(self):
        sql = _downgrade_sql()
        self.assertLess(sql.index("DROP COLUMN natural_key"),
                        sql.index("ALTER COLUMN source_record_version "
                                  "SET NOT NULL"))
        self.assertLess(sql.index("ALTER COLUMN source_record_version "
                                  "SET NOT NULL"),
                        sql.index("ADD CONSTRAINT "
                                  "uq_evidence_records_provenance"))

    def test_both_directions_are_one_transaction(self):
        """A refusal has to be total. The downgrade correctly refuses to invent
        a version for an UNKNOWN_LEGACY row - and without a transaction it had
        already dropped eight tables by the time it refused."""
        for direction, sql in (("upgrade", _upgrade_sql()),
                               ("downgrade", _downgrade_sql())):
            with self.subTest(direction=direction):
                self.assertIn("BEGIN;", sql)
                self.assertTrue(sql.rstrip().endswith("COMMIT;"))

    def test_it_drops_the_trigger_and_its_function(self):
        sql = _downgrade_sql()
        self.assertIn("DROP TRIGGER", sql)
        self.assertIn("DROP FUNCTION", sql)


class TestTheRenderedDdlIsPortable(unittest.TestCase):

    def test_no_absolute_path_appears(self):
        for sql in (_upgrade_sql(), _downgrade_sql()):
            self.assertNotIn(REPO_ROOT, sql)

    def test_it_names_the_migration_it_was_rendered_from(self):
        self.assertIn("0006_wp08_evidence_store.py", _upgrade_sql())

    def test_rendering_is_deterministic(self):
        self.assertEqual(_upgrade_sql(), _upgrade_sql())
        self.assertEqual(_downgrade_sql(), _downgrade_sql())
