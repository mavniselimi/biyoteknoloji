# -*- coding: utf-8 -*-
"""Schema contract checks that need no database driver (WP-02).

The Alembic migration is the authority. These tests read it directly, so the
schema's structural guarantees are verified even where SQLAlchemy and Alembic
cannot be installed.
"""

from __future__ import annotations

import ast
import io
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for path in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

from render_wp02_schema import (  # noqa: E402
    POSTGRES_IDENTIFIER_LIMIT, over_length_identifiers, render_schema,
)

MIGRATION_PATH = os.path.join(REPO_ROOT, "migrations", "versions",
                              "0001_wp02_foundation.py")
ORM_PATH = os.path.join(REPO_ROOT, "pgx", "infrastructure", "db", "models.py")

EXPECTED_TABLES = (
    "source_registry", "dataset_versions", "genes", "gene_aliases", "drugs",
    "drug_aliases", "evidence_records", "curated_interpretations",
    "interpretation_evidence", "computable_rules", "rule_evidence",
)


def _migration_tree() -> ast.Module:
    with io.open(MIGRATION_PATH, encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=MIGRATION_PATH)


def _called_tables(function_name: str, call_attr: str):
    tree = _migration_tree()
    target = [node for node in tree.body
              if isinstance(node, ast.FunctionDef) and node.name == function_name]
    names = []
    for node in ast.walk(target[0]):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == call_attr and node.args:
            names.append(node.args[0].value)
    return names


class TestMigrationShape(unittest.TestCase):

    def test_exactly_the_eleven_foundation_tables_are_created(self):
        self.assertEqual(_called_tables("upgrade", "create_table"),
                         list(EXPECTED_TABLES))

    def test_downgrade_drops_every_table_in_reverse_order(self):
        created = _called_tables("upgrade", "create_table")
        dropped = _called_tables("downgrade", "drop_table")
        self.assertEqual(dropped, created[::-1])

    def test_downgrade_drops_every_index_it_created(self):
        created = set(_called_tables("upgrade", "create_index"))
        dropped = set(_called_tables("downgrade", "drop_index"))
        self.assertEqual(created, dropped)

    def test_migration_declares_a_single_head(self):
        tree = _migration_tree()
        assignments = {}
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                try:
                    assignments[node.target.id] = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    pass
        self.assertEqual(assignments.get("revision"), "0001_wp02_foundation")
        self.assertIsNone(assignments.get("down_revision"))

    def test_migration_opens_no_connection_at_import_time(self):
        """Importing the migration must not touch the network or a database."""
        tree = _migration_tree()
        for node in tree.body:
            if isinstance(node, ast.Expr):
                # A docstring is the only permitted bare module-level expression.
                self.assertIsInstance(node.value, ast.Constant, ast.dump(node)[:60])
                self.assertIsInstance(node.value.value, str)
                continue
            self.assertIsInstance(
                node, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign,
                       ast.FunctionDef, ast.ClassDef),
                "module level must only declare, never execute: %s"
                % ast.dump(node)[:60])
        with io.open(MIGRATION_PATH, encoding="utf-8") as handle:
            source = handle.read()
        for forbidden in ("create_engine", "psycopg.connect", "requests."):
            self.assertNotIn(forbidden, source)


class TestIdentifierLimits(unittest.TestCase):
    """PostgreSQL truncates identifiers at 63 bytes, which breaks downgrade()."""

    def test_no_migration_identifier_exceeds_the_postgres_limit(self):
        sql = render_schema()
        offenders = over_length_identifiers(sql)
        self.assertEqual(
            offenders, [],
            "PostgreSQL truncates these to %d bytes, so downgrade() would not "
            "find them: %s" % (POSTGRES_IDENTIFIER_LIMIT, offenders))

    def test_orm_constraint_names_stay_within_the_limit(self):
        """The naming convention expands a short suffix into ck_<table>_<suffix>.

        Each suffix is paired with the table that actually declares it, not with
        every table, so the check reflects the names PostgreSQL will really see.
        """
        with io.open(ORM_PATH, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=ORM_PATH)

        checked = 0
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            table = None
            for item in node.body:
                if isinstance(item, ast.Assign) and len(item.targets) == 1 \
                        and isinstance(item.targets[0], ast.Name) \
                        and item.targets[0].id == "__tablename__":
                    table = ast.literal_eval(item.value)
            if table is None:
                continue
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                constraint = call.func.id if isinstance(call.func, ast.Name) else \
                    getattr(call.func, "attr", "")
                if constraint not in ("CheckConstraint", "UniqueConstraint", "Index"):
                    continue
                for keyword in call.keywords:
                    if keyword.arg != "name":
                        continue
                    suffix = ast.literal_eval(keyword.value)
                    expanded = ("ck_%s_%s" % (table, suffix)
                                if constraint == "CheckConstraint" else suffix)
                    self.assertLessEqual(
                        len(expanded), POSTGRES_IDENTIFIER_LIMIT,
                        "%s.%s expands to %r (%d bytes), which PostgreSQL would "
                        "truncate" % (table, suffix, expanded, len(expanded)))
                    checked += 1
        self.assertGreater(checked, 10, "expected to check many constraint names")


class TestRenderedSchemaContent(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.sql = render_schema()

    def test_every_table_is_rendered(self):
        for table in EXPECTED_TABLES:
            self.assertIn("CREATE TABLE %s (" % table, self.sql)

    def test_timestamps_are_timezone_aware(self):
        self.assertIn("TIMESTAMP WITH TIME ZONE", self.sql)
        self.assertNotIn("TIMESTAMP NOT NULL", self.sql)

    def test_json_columns_use_jsonb(self):
        self.assertIn("JSONB", self.sql)
        self.assertNotIn(" JSON ", self.sql)

    def test_lifecycle_constraints_are_present(self):
        for constraint in (
                "ck_curated_interpretations_curated_requires_review_metadata",
                "ck_computable_rules_validated_requires_approval",
                "ck_dataset_versions_published_requires_approval",
                "ck_source_registry_internal_source_not_release_eligible"):
            self.assertIn(constraint, self.sql)

    def test_rapid_and_ultrarapid_are_separate_values(self):
        self.assertIn("'RAPID', 'ULTRARAPID'", self.sql)

    def test_rule_interpretation_is_not_nullable(self):
        block = self.sql.split("CREATE TABLE computable_rules (")[1].split(");")[0]
        self.assertIn("interpretation_id UUID NOT NULL", block)

    def test_evidence_table_has_no_clinical_conclusion_column(self):
        block = self.sql.split("CREATE TABLE evidence_records (")[1].split(");")[0]
        for forbidden in ("attention_level", "risk_level", "severity", "dose",
                          "treatment", "recommendation", "score"):
            self.assertNotIn(forbidden, block)

    def test_no_later_work_package_table_is_rendered(self):
        for forbidden in ("assessments", "assessment_findings", "release_bundles",
                          "active_release", "ruleset_versions", "software_versions"):
            self.assertNotIn("CREATE TABLE %s (" % forbidden, self.sql)

    def test_rendering_is_deterministic(self):
        self.assertEqual(render_schema(), self.sql)


if __name__ == "__main__":
    unittest.main(verbosity=2)
