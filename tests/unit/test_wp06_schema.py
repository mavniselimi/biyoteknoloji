# -*- coding: utf-8 -*-
"""Schema contract checks for the WP-06 migration (needs no database driver).

The Alembic migration is the authority. These tests read it directly and read
the SQL rendered from it, so the structural guarantees hold in an environment
where Alembic and SQLAlchemy cannot be installed.

Two things beyond shape are asserted here.

**0004 only adds, except for one widening it declares.** It creates two tables
and replaces one check constraint with a strictly larger permitted set. Every
value the old constraint admitted still passes; nothing else does.

**A sealed snapshot's identity is immutable in the database.** Only
``dataset_version_id`` and its registration metadata may change after sealing,
because registration legitimately happens later and may be retried.
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
    POSTGRES_IDENTIFIER_LIMIT, over_length_identifiers,
)
from render_wp06_schema import render_schema  # noqa: E402

MIGRATION_PATH = os.path.join(REPO_ROOT, "migrations", "versions",
                              "0004_wp06_raw_snapshots.py")

EXPECTED_TABLES = ("raw_snapshots", "raw_artifacts")

EARLIER_TABLES = (
    "source_registry", "dataset_versions", "genes", "drugs",
    "evidence_records", "computable_rules", "software_versions",
    "ruleset_versions", "release_bundles", "active_release", "audit_events",
    "source_policies", "source_policy_evidence", "source_policy_reviews",
    "source_conflicts", "dataset_publication_evaluations",
)


def _tree() -> ast.Module:
    with io.open(MIGRATION_PATH, encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=MIGRATION_PATH)


def _called(function_name: str, call_attr: str):
    target = [node for node in _tree().body
              if isinstance(node, ast.FunctionDef) and node.name == function_name]
    names = []
    for node in ast.walk(target[0]):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == call_attr and node.args
                and isinstance(node.args[0], ast.Constant)):
            names.append(node.args[0].value)
    return names


class TestMigrationShape(unittest.TestCase):

    def test_exactly_the_two_snapshot_tables_are_created(self):
        self.assertEqual(_called("upgrade", "create_table"), list(EXPECTED_TABLES))

    def test_downgrade_drops_every_table_in_reverse_order(self):
        self.assertEqual(_called("downgrade", "drop_table"),
                         list(EXPECTED_TABLES)[::-1])

    def test_downgrade_drops_every_index_it_created(self):
        self.assertEqual(set(_called("upgrade", "create_index")),
                         set(_called("downgrade", "drop_index")))

    def test_it_follows_the_wp05_migration(self):
        assignments = {}
        for node in _tree().body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                try:
                    assignments[node.target.id] = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    pass
        self.assertEqual(assignments.get("revision"), "0004_wp06_raw_snapshots")
        self.assertEqual(assignments.get("down_revision"),
                         "0003_wp05_source_policy")

    def test_the_revision_chain_has_exactly_one_head(self):
        directory = os.path.join(REPO_ROOT, "migrations", "versions")
        revisions, parents = set(), set()
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".py"):
                continue
            with io.open(os.path.join(directory, name), encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=name)
            for node in tree.body:
                if isinstance(node, ast.AnnAssign) and isinstance(node.target,
                                                                  ast.Name):
                    try:
                        value = ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        continue
                    if node.target.id == "revision":
                        revisions.add(value)
                    elif node.target.id == "down_revision" and value:
                        parents.add(value)
        # One head, whichever revision currently holds it. Naming ``0004`` here
        # would have made this test fail on the day WP-07 added ``0005`` - a
        # failure that says nothing about WP-06's chain. What the test is for is
        # that the chain never *forks*, and that ``0004`` is still on it.
        heads = revisions - parents
        self.assertEqual(len(heads), 1,
                         "the revision chain has forked: %s" % sorted(heads))
        self.assertIn("0004_wp06_raw_snapshots", revisions)
        self.assertIn("0003_wp05_source_policy", parents,
                      "0004 must still descend from 0003")

    def test_it_opens_no_connection_at_import_time(self):
        for node in _tree().body:
            if isinstance(node, ast.Expr):
                self.assertIsInstance(node.value, ast.Constant)
                continue
            self.assertIsInstance(
                node, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign,
                       ast.FunctionDef, ast.ClassDef))


class TestItOnlyAdds(unittest.TestCase):

    def test_it_drops_no_earlier_table(self):
        self.assertEqual(set(_called("upgrade", "drop_table")), set())

    def test_the_downgrade_touches_no_earlier_table(self):
        for table in _called("downgrade", "drop_table"):
            with self.subTest(table=table):
                self.assertNotIn(table, EARLIER_TABLES)

    def test_the_earlier_migration_files_are_not_referenced(self):
        with io.open(MIGRATION_PATH, encoding="utf-8") as handle:
            source = handle.read()
        for earlier in ("0001_wp02_foundation.py", "0002_wp03_release_registry.py",
                        "0003_wp05_source_policy.py"):
            self.assertNotIn(earlier, source)

    def test_the_only_constraint_it_replaces_is_the_audit_action_list(self):
        dropped = _called("upgrade", "drop_constraint")
        self.assertEqual(dropped, ["ck_audit_events_action_enum"])

    def test_the_replacement_is_a_widening(self):
        """Every previously permitted action still passes."""
        constants = {}
        for node in _tree().body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0],
                                                           ast.Name):
                try:
                    constants[node.targets[0].id] = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    continue
        old = set(constants["AUDIT_ACTIONS_0002"].split(", "))
        new = set(constants["AUDIT_ACTIONS_0004"].split(", "))
        self.assertTrue(old.issubset(new))
        self.assertEqual(new - old, {"'DATASET_BUILD_REGISTERED'"})

    def test_the_downgrade_restores_the_earlier_action_list(self):
        with io.open(MIGRATION_PATH, encoding="utf-8") as handle:
            downgrade = handle.read().split("def downgrade()", 1)[1]
        self.assertIn("AUDIT_ACTIONS_0002", downgrade)
        self.assertNotIn("AUDIT_ACTIONS_0004", downgrade)

    def test_the_audit_append_only_trigger_is_not_touched(self):
        with io.open(MIGRATION_PATH, encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("trg_audit_events_append_only", source)
        self.assertNotIn("pgx_audit_events_append_only", source)


class TestIdentifierLimits(unittest.TestCase):

    def test_no_identifier_exceeds_the_postgres_limit(self):
        offenders = over_length_identifiers(render_schema())
        self.assertEqual(
            offenders, [],
            "PostgreSQL truncates these to %d bytes: %s"
            % (POSTGRES_IDENTIFIER_LIMIT, offenders))


class TestRenderedSchemaContent(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.sql = render_schema()

    def test_every_table_is_rendered(self):
        for table in EXPECTED_TABLES:
            self.assertIn("CREATE TABLE %s (" % table, self.sql)

    def test_a_quarantined_snapshot_cannot_be_publication_eligible(self):
        self.assertIn("ck_raw_snapshots_quarantine_not_publishable", self.sql)

    def test_a_legacy_import_cannot_carry_acquisition_metadata(self):
        self.assertIn("ck_raw_snapshots_legacy_has_no_acquisition", self.sql)
        self.assertIn("acquisition_run_id IS NULL", self.sql)

    def test_a_legacy_import_must_state_its_limitations(self):
        self.assertIn("ck_raw_snapshots_legacy_states_limitations", self.sql)

    def test_no_row_may_claim_a_staging_state(self):
        self.assertIn("ck_raw_snapshots_never_staging", self.sql)

    def test_registration_metadata_arrives_together_or_not_at_all(self):
        self.assertIn("ck_raw_snapshots_registration_is_complete", self.sql)

    def test_artifact_paths_are_relative_and_traversal_free(self):
        self.assertIn("ck_raw_artifacts_relative_path", self.sql)

    def test_a_response_body_must_name_its_request(self):
        self.assertIn("ck_raw_artifacts_response_names_request", self.sql)

    def test_a_legacy_file_may_not_claim_a_request(self):
        self.assertIn("ck_raw_artifacts_legacy_has_no_request", self.sql)

    def test_a_snapshot_identity_is_immutable_in_the_database(self):
        self.assertIn(
            "CREATE OR REPLACE FUNCTION pgx_raw_snapshots_identity_immutable()",
            self.sql)
        self.assertIn("BEFORE UPDATE OR DELETE ON raw_snapshots", self.sql)

    def test_the_registration_link_is_the_one_field_that_may_change(self):
        self.assertIn("dataset_version_id", self.sql)
        self.assertNotIn("NEW.dataset_version_id IS DISTINCT FROM", self.sql)

    def test_the_audit_action_list_is_widened_in_the_rendered_sql(self):
        self.assertIn("DATASET_BUILD_REGISTERED", self.sql)
        self.assertIn("LEGACY_BASELINE_REGISTERED", self.sql)

    def test_timestamps_are_timezone_aware(self):
        self.assertNotIn("TIMESTAMP,", self.sql)
        self.assertIn("TIMESTAMP WITH TIME ZONE", self.sql)

    def test_digests_are_format_checked(self):
        self.assertIn("sha256:[0-9a-f]{64}", self.sql)

    def test_no_later_work_package_table_is_rendered(self):
        for forbidden in ("canonical_genes", "canonical_drugs",
                          "resolution_queue", "dq_reports", "assessments"):
            self.assertNotIn("CREATE TABLE %s (" % forbidden, self.sql)

    def test_rendering_is_deterministic(self):
        self.assertEqual(render_schema(), self.sql)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
