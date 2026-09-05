# -*- coding: utf-8 -*-
"""Schema contract checks for the WP-05 migration (needs no database driver).

The Alembic migration is the authority. These tests read it directly and read
the SQL rendered from it, so the structural guarantees hold in an environment
where Alembic and SQLAlchemy cannot be installed.

What is asserted here, beyond shape:

* **0003 only adds.** It drops nothing belonging to 0001 or 0002, and it alters
  no earlier table. A migration that tidied an earlier one would rewrite
  history that other environments have already applied.
* **A row cannot approve itself.** The check constraint tying an approving
  status to a review is present in the rendered DDL, so the invariant survives
  someone bypassing the Python layer.
* **Reviews and verdicts are append-only in the database**, not only in the
  application, which is a promise rather than a guarantee.
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
from render_wp05_schema import render_schema  # noqa: E402

MIGRATION_PATH = os.path.join(REPO_ROOT, "migrations", "versions",
                              "0003_wp05_source_policy.py")

EXPECTED_TABLES = (
    "source_policy_reviews", "source_policies", "source_policy_evidence",
    "source_conflicts", "dataset_publication_evaluations",
)

EARLIER_TABLES = (
    "source_registry", "dataset_versions", "genes", "drugs",
    "evidence_records", "curated_interpretations", "computable_rules",
    "software_versions", "ruleset_versions", "release_bundles",
    "active_release", "audit_events",
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

    def test_exactly_the_five_source_policy_tables_are_created(self):
        self.assertEqual(_called("upgrade", "create_table"), list(EXPECTED_TABLES))

    def test_downgrade_drops_every_table_in_reverse_order(self):
        self.assertEqual(_called("downgrade", "drop_table"),
                         list(EXPECTED_TABLES)[::-1])

    def test_downgrade_drops_every_index_it_created(self):
        self.assertEqual(set(_called("upgrade", "create_index")),
                         set(_called("downgrade", "drop_index")))

    def test_it_follows_the_wp03_migration_and_declares_a_single_head(self):
        assignments = {}
        for node in _tree().body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                try:
                    assignments[node.target.id] = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    pass
        self.assertEqual(assignments.get("revision"), "0003_wp05_source_policy")
        self.assertEqual(assignments.get("down_revision"),
                         "0002_wp03_release_registry")
        self.assertIsNone(assignments.get("branch_labels"))

    def test_the_revision_chain_has_exactly_one_head(self):
        directory = os.path.join(REPO_ROOT, "migrations", "versions")
        revisions, parents = set(), set()
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".py"):
                continue
            with io.open(os.path.join(directory, name), encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=name)
            for node in tree.body:
                if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    try:
                        value = ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        continue
                    if node.target.id == "revision":
                        revisions.add(value)
                    elif node.target.id == "down_revision" and value:
                        parents.add(value)
        # 0003 was the head when WP-05 shipped; WP-06 added 0004 on top of it.
        # The invariant is that the chain stays linear with exactly one head,
        # not that any particular revision is it.
        heads = revisions - parents
        self.assertEqual(len(heads), 1, "the revision chain must have one head")
        self.assertIn("0003_wp05_source_policy", parents,
                      "0003 must still be somebody's parent")

    def test_it_opens_no_connection_at_import_time(self):
        for node in _tree().body:
            if isinstance(node, ast.Expr):
                self.assertIsInstance(node.value, ast.Constant)
                continue
            self.assertIsInstance(
                node, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign,
                       ast.FunctionDef, ast.ClassDef),
                "module level must only declare, never execute")
        with io.open(MIGRATION_PATH, encoding="utf-8") as handle:
            source = handle.read()
        for forbidden in ("create_engine", "psycopg.connect", "requests."):
            self.assertNotIn(forbidden, source)


class TestItOnlyAdds(unittest.TestCase):
    """0001 and 0002 are history; a later migration does not rewrite them."""

    def test_it_drops_no_earlier_table(self):
        dropped = set(_called("upgrade", "drop_table"))
        self.assertEqual(dropped, set())

    def test_the_downgrade_touches_no_earlier_table(self):
        for table in _called("downgrade", "drop_table"):
            with self.subTest(table=table):
                self.assertNotIn(table, EARLIER_TABLES)

    def test_it_alters_no_earlier_table(self):
        altered = set()
        for node in ast.walk(_tree()):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "attr", "").startswith(
                        ("alter_", "drop_column", "add_column"))
                    and node.args and isinstance(node.args[0], ast.Constant)):
                altered.add(node.args[0].value)
        self.assertEqual(altered & set(EARLIER_TABLES), set())

    def test_the_earlier_migrations_are_untouched_by_this_one(self):
        with io.open(MIGRATION_PATH, encoding="utf-8") as handle:
            source = handle.read()
        for earlier in ("0001_wp02_foundation.py", "0002_wp03_release_registry.py"):
            self.assertNotIn(earlier, source)


class TestIdentifierLimits(unittest.TestCase):
    """PostgreSQL truncates identifiers at 63 bytes, which breaks downgrade()."""

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

    def test_a_row_cannot_approve_itself(self):
        self.assertIn("ck_source_policies_approving_needs_review", self.sql)
        self.assertIn("review_id IS NOT NULL", self.sql)

    def test_an_unapproved_row_cannot_claim_categories(self):
        self.assertIn("ck_source_policies_categories_need_approval", self.sql)

    def test_an_approving_review_must_cite_evidence(self):
        self.assertIn("ck_source_policy_reviews_approval_needs_evidence", self.sql)
        self.assertIn("jsonb_array_length(evidence_urls) > 0", self.sql)

    def test_a_settled_conflict_must_name_who_settled_it(self):
        self.assertIn("ck_source_conflicts_settled_has_resolution", self.sql)
        self.assertIn("resolved_by IS NOT NULL", self.sql)

    def test_an_eligible_verdict_cannot_carry_a_blocker(self):
        self.assertIn("ck_publication_evaluations_eligible_has_no_blocker",
                      self.sql)

    def test_a_verified_retrieval_must_name_what_and_when(self):
        self.assertIn("ck_source_policy_evidence_verified_is_specific", self.sql)

    def test_a_blocked_retrieval_must_say_why(self):
        self.assertIn("ck_source_policy_evidence_block_has_reason", self.sql)

    def test_reviews_and_verdicts_are_append_only_in_the_database(self):
        self.assertIn("CREATE OR REPLACE FUNCTION pgx_wp05_append_only()",
                      self.sql)
        self.assertIn("BEFORE UPDATE OR DELETE ON source_policy_reviews",
                      self.sql)
        self.assertIn("BEFORE UPDATE OR DELETE ON dataset_publication_evaluations",
                      self.sql)

    def test_the_downgrade_removes_the_triggers_and_their_function(self):
        with io.open(MIGRATION_PATH, encoding="utf-8") as handle:
            source = handle.read()
        downgrade = source.split("def downgrade()", 1)[1]
        self.assertIn("DROP TRIGGER IF EXISTS trg_source_policy_reviews_append_only",
                      downgrade)
        self.assertIn("DROP TRIGGER IF EXISTS trg_publication_evaluations_append_only",
                      downgrade)
        self.assertIn("DROP FUNCTION IF EXISTS pgx_wp05_append_only()", downgrade)

    def test_timestamps_are_timezone_aware(self):
        self.assertNotIn("TIMESTAMP,", self.sql)
        self.assertIn("TIMESTAMP WITH TIME ZONE", self.sql)

    def test_json_columns_use_jsonb(self):
        self.assertNotIn(" JSON ", self.sql)
        self.assertIn("JSONB", self.sql)

    def test_digests_are_format_checked(self):
        self.assertIn("sha256:[0-9a-f]{64}", self.sql)

    def test_no_later_work_package_table_is_rendered(self):
        for forbidden in ("raw_snapshots", "raw_artifacts", "ingestion_runs",
                          "dataset_artifacts", "assessments"):
            self.assertNotIn("CREATE TABLE %s (" % forbidden, self.sql)

    def test_no_policy_row_carries_a_copy_of_a_terms_page(self):
        """A summary column exists; a full-text column deliberately does not."""
        for forbidden in ("terms_text", "license_text", "full_text",
                          "terms_body"):
            self.assertNotIn(forbidden, self.sql)

    def test_rendering_is_deterministic(self):
        self.assertEqual(render_schema(), self.sql)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
