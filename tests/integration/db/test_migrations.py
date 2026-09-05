# -*- coding: utf-8 -*-
"""Alembic migration behaviour on real PostgreSQL (WP-02)."""

from __future__ import annotations

import unittest

from tests.integration.db._support import (
    WP02_TABLES, alembic_config, drop_wp02_objects, make_test_engine,
    require_postgres_dependencies,
)


class TestMigrationLifecycle(unittest.TestCase):
    """upgrade -> downgrade -> upgrade against an empty PostgreSQL database."""

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

    def test_single_head(self):
        from alembic.script import ScriptDirectory
        heads = ScriptDirectory.from_config(alembic_config()).get_heads()
        self.assertEqual(len(heads), 1, "expected exactly one migration head: %s" % (heads,))
        self.assertEqual(heads[0], "0001_wp02_foundation")

    def test_upgrade_downgrade_upgrade_cycle(self):
        from alembic import command
        from sqlalchemy import inspect

        config = alembic_config()

        command.upgrade(config, "head")
        after_first = self._tables()
        for table in WP02_TABLES:
            self.assertIn(table, after_first, "upgrade did not create %s" % table)

        command.downgrade(config, "base")
        after_downgrade = self._tables()
        for table in WP02_TABLES:
            self.assertNotIn(table, after_downgrade,
                             "downgrade left %s behind" % table)

        command.upgrade(config, "head")
        after_second = self._tables()
        self.assertEqual(
            {t for t in after_first if t in WP02_TABLES},
            {t for t in after_second if t in WP02_TABLES})

        inspector = inspect(self.engine)
        self.assertIn("id", {c["name"] for c in inspector.get_columns("source_registry")})

    def test_expected_constraints_and_indexes_exist(self):
        from alembic import command
        from sqlalchemy import inspect

        command.upgrade(alembic_config(), "head")
        inspector = inspect(self.engine)

        unique_names = {
            constraint["name"]
            for table in WP02_TABLES
            for constraint in inspector.get_unique_constraints(table)}
        for expected in ("uq_source_registry_source_key", "uq_dataset_versions_public_id",
                         "uq_genes_normalized_symbol", "uq_drugs_normalized_name",
                         "uq_evidence_records_provenance"):
            self.assertIn(expected, unique_names)

        index_names = {
            index["name"] for table in WP02_TABLES
            for index in inspector.get_indexes(table)}
        for expected in ("ix_gene_aliases_normalized_alias",
                         "ix_drug_aliases_normalized_alias",
                         "ix_evidence_records_dataset_version_id",
                         "ix_computable_rules_status"):
            self.assertIn(expected, index_names)

        foreign_keys = {
            (table, tuple(fk["constrained_columns"]), fk["referred_table"])
            for table in WP02_TABLES
            for fk in inspector.get_foreign_keys(table)}
        self.assertIn(("evidence_records", ("dataset_version_id",), "dataset_versions"),
                      foreign_keys)
        self.assertIn(("computable_rules", ("interpretation_id",),
                       "curated_interpretations"), foreign_keys)
        self.assertIn(("rule_evidence", ("rule_id",), "computable_rules"), foreign_keys)

    def test_timestamps_are_timezone_aware_and_json_is_jsonb(self):
        from alembic import command
        from sqlalchemy import inspect

        command.upgrade(alembic_config(), "head")
        columns = {c["name"]: c for c in inspect(self.engine).get_columns("evidence_records")}
        self.assertTrue(columns["created_at"]["type"].timezone)
        self.assertEqual(columns["evidence_metadata"]["type"].__class__.__name__, "JSONB")

    def test_no_later_work_package_table_is_created(self):
        from alembic import command

        command.upgrade(alembic_config(), "head")
        present = self._tables()
        for forbidden in ("assessments", "assessment_findings", "release_bundles",
                          "active_release", "ruleset_versions", "software_versions",
                          "users", "validation_cases"):
            self.assertNotIn(forbidden, present,
                             "%s belongs to a later work package" % forbidden)


if __name__ == "__main__":
    unittest.main(verbosity=2)
