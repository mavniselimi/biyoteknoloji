# -*- coding: utf-8 -*-
"""Deterministic foundation seed on real PostgreSQL (WP-02)."""

from __future__ import annotations

import os
import unittest

from tests.integration.db._support import PostgresTestCase


class TestSeed(PostgresTestCase):

    def _run(self, dry_run=False):
        from scripts.db_seed import run_seed
        return run_seed("TEST_DATABASE_URL", dry_run=dry_run)

    def test_first_run_creates_exactly_one_technical_row(self):
        report = self._run()
        self.assertEqual(report["created_count"], 1)
        self.assertEqual(report["already_present_count"], 0)
        self.assertEqual(report["drift_count"], 0)
        self.assertEqual(report["scientific_rows_created"], 0)

    def test_second_run_is_idempotent_with_the_same_hash(self):
        first = self._run()
        second = self._run()
        self.assertEqual(second["created_count"], 0)
        self.assertEqual(second["already_present_count"], 1)
        self.assertEqual(second["drift_count"], 0)
        self.assertEqual(first["canonical_payload_hash"],
                         second["canonical_payload_hash"])

        from sqlalchemy import text
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(
                text("SELECT count(*) FROM source_registry")).scalar_one(), 1)

    def test_seeded_row_is_not_release_eligible(self):
        self._run()
        from sqlalchemy import text
        with self.engine.connect() as connection:
            row = connection.execute(text(
                "SELECT role, release_eligible, license_policy, citation_policy"
                " FROM source_registry WHERE source_key = 'pgx-internal-system'"
            )).one()
        self.assertEqual(row[0], "INTERNAL_SYSTEM")
        self.assertFalse(row[1])
        self.assertEqual(row[2], "NOT_APPLICABLE_INTERNAL")
        self.assertEqual(row[3], "NOT_APPLICABLE_INTERNAL")

    def test_seed_creates_no_scientific_rows(self):
        self._run()
        from sqlalchemy import text
        with self.engine.connect() as connection:
            for table in ("genes", "drugs", "evidence_records",
                          "curated_interpretations", "computable_rules"):
                count = connection.execute(
                    text("SELECT count(*) FROM %s" % table)).scalar_one()
                self.assertEqual(count, 0, "seed must not populate %s" % table)

    def test_drift_is_reported_and_not_silently_overwritten(self):
        self._run()
        from sqlalchemy import text
        with self.engine.begin() as connection:
            connection.execute(text(
                "UPDATE source_registry SET display_name = 'tampered'"
                " WHERE source_key = 'pgx-internal-system'"))
        report = self._run()
        self.assertEqual(report["drift_count"], 1)
        self.assertEqual(report["created_count"], 0)
        self.assertEqual(report["drift"][0]["field"], "display_name")
        with self.engine.connect() as connection:
            name = connection.execute(text(
                "SELECT display_name FROM source_registry"
                " WHERE source_key = 'pgx-internal-system'")).scalar_one()
        self.assertEqual(name, "tampered", "the seed must not overwrite drift")

    def test_report_never_contains_the_database_password(self):
        report = self._run()
        url = os.environ.get("TEST_DATABASE_URL", "")
        from urllib.parse import urlsplit
        password = urlsplit(url).password
        serialised = repr(report)
        if password:
            self.assertNotIn(password, serialised)
        self.assertIn("***", report["database"]) if password else None

    def test_dry_run_writes_nothing(self):
        report = self._run(dry_run=True)
        self.assertTrue(report["dry_run"])
        from sqlalchemy import text
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(
                text("SELECT count(*) FROM source_registry")).scalar_one(), 0)

    def test_seed_reports_the_schema_revision(self):
        report = self._run()
        self.assertEqual(report["database_schema_revision"], "0001_wp02_foundation")


if __name__ == "__main__":
    unittest.main(verbosity=2)
