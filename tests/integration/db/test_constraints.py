# -*- coding: utf-8 -*-
"""Database-enforced constraints on real PostgreSQL (WP-02)."""

from __future__ import annotations

import datetime as _dt
import unittest
import uuid

from tests.integration.db._support import PostgresTestCase

NOW = _dt.datetime(2026, 8, 29, 12, 0, tzinfo=_dt.timezone.utc)
DIGEST = "sha256:" + "a" * 64


class TestConstraints(PostgresTestCase):

    def _insert(self, sql, **params):
        from sqlalchemy import text
        with self.engine.begin() as connection:
            connection.execute(text(sql), params)

    def _source(self, key="src-1", role="REFERENCE_ONLY", eligible=False):
        source_id = uuid.uuid4()
        self._insert(
            "INSERT INTO source_registry (id, source_key, display_name, role,"
            " version_policy, license_policy, citation_policy, release_eligible,"
            " active, created_at) VALUES (:id, :k, 'n', :r, 'p', 'l', 'c', :e, true, :t)",
            id=source_id, k=key, r=role, e=eligible, t=NOW)
        return source_id

    def _dataset(self, public_id="PGX-DATA-20260829-001", status="BUILDING",
                 manifest=DIGEST):
        dataset_id = uuid.uuid4()
        self._insert(
            "INSERT INTO dataset_versions (id, public_id, status, manifest_hash,"
            " created_at) VALUES (:id, :p, :s, :m, :t)",
            id=dataset_id, p=public_id, s=status, m=manifest, t=NOW)
        return dataset_id

    # -- uniqueness ------------------------------------------------------

    def test_duplicate_source_key_is_rejected(self):
        from sqlalchemy.exc import IntegrityError
        self._source(key="dup")
        with self.assertRaises(IntegrityError):
            self._source(key="dup")

    def test_duplicate_gene_symbol_is_rejected(self):
        from sqlalchemy.exc import IntegrityError

        def add(symbol):
            self._insert(
                "INSERT INTO genes (id, normalized_symbol, preferred_name, external_ids,"
                " created_at) VALUES (:id, :s, 'n', '{}'::jsonb, :t)",
                id=uuid.uuid4(), s=symbol, t=NOW)

        add("CYP2C19")
        with self.assertRaises(IntegrityError):
            add("CYP2C19")

    def test_duplicate_alias_within_one_gene_is_rejected(self):
        from sqlalchemy.exc import IntegrityError
        gene_id = uuid.uuid4()
        self._insert(
            "INSERT INTO genes (id, normalized_symbol, preferred_name, external_ids,"
            " created_at) VALUES (:id, 'CYP2D6', 'n', '{}'::jsonb, :t)",
            id=gene_id, t=NOW)

        def alias():
            self._insert(
                "INSERT INTO gene_aliases (gene_id, normalized_alias, display_alias)"
                " VALUES (:g, 'CPD6', 'CPD6')", g=gene_id)

        alias()
        with self.assertRaises(IntegrityError):
            alias()

    def test_the_same_alias_may_belong_to_two_different_genes(self):
        """Ambiguity is preserved for WP-07 resolution, not collapsed."""
        from sqlalchemy import text
        first, second = uuid.uuid4(), uuid.uuid4()
        for gene_id, symbol in ((first, "GENEA"), (second, "GENEB")):
            self._insert(
                "INSERT INTO genes (id, normalized_symbol, preferred_name, external_ids,"
                " created_at) VALUES (:id, :s, 'n', '{}'::jsonb, :t)",
                id=gene_id, s=symbol, t=NOW)
            self._insert(
                "INSERT INTO gene_aliases (gene_id, normalized_alias, display_alias)"
                " VALUES (:g, 'SHARED', 'shared')", g=gene_id)
        with self.engine.connect() as connection:
            count = connection.execute(text(
                "SELECT count(*) FROM gene_aliases WHERE normalized_alias = 'SHARED'"
            )).scalar_one()
        self.assertEqual(count, 2)

    # -- format and lifecycle -------------------------------------------

    def test_invalid_dataset_public_id_is_rejected(self):
        from sqlalchemy.exc import IntegrityError
        for bad in ("PGX-DATA-2026-001", "pgx-data-20260829-001", "PGX-REL-20260829-001"):
            with self.assertRaises(IntegrityError, msg=bad):
                self._dataset(public_id=bad)

    def test_invalid_sha256_is_rejected(self):
        from sqlalchemy.exc import IntegrityError
        for bad in ("a" * 64, "sha256:" + "A" * 64, "sha1:" + "a" * 40):
            with self.assertRaises(IntegrityError, msg=bad):
                self._dataset(public_id="PGX-DATA-20260829-%03d" % (hash(bad) % 900 + 1),
                              manifest=bad)

    def test_published_dataset_without_approval_is_rejected(self):
        from sqlalchemy.exc import IntegrityError
        with self.assertRaises(IntegrityError):
            self._dataset(status="PUBLISHED")

    def test_invalid_lifecycle_string_is_rejected(self):
        from sqlalchemy.exc import IntegrityError
        with self.assertRaises(IntegrityError):
            self._dataset(status="NOT_A_STATUS")

    def test_internal_system_source_cannot_be_release_eligible(self):
        from sqlalchemy.exc import IntegrityError
        with self.assertRaises(IntegrityError):
            self._source(key="internal", role="INTERNAL_SYSTEM", eligible=True)

    def test_curated_interpretation_without_reviewer_is_rejected(self):
        from sqlalchemy.exc import IntegrityError
        with self.assertRaises(IntegrityError):
            self._insert(
                "INSERT INTO curated_interpretations (id, status, normalized_effect,"
                " significance, created_by, created_at)"
                " VALUES (:id, 'CURATED', 'e', 's', 'u', :t)", id=uuid.uuid4(), t=NOW)

    def test_validated_rule_without_approval_is_rejected(self):
        from sqlalchemy.exc import IntegrityError
        interpretation_id = uuid.uuid4()
        self._insert(
            "INSERT INTO curated_interpretations (id, status, normalized_effect,"
            " significance, rationale, reviewed_by, reviewed_at, created_by, created_at)"
            " VALUES (:id, 'CURATED', 'e', 's', 'r', 'rev', :t, 'u', :t)",
            id=interpretation_id, t=NOW)
        with self.assertRaises(IntegrityError):
            self._insert(
                "INSERT INTO computable_rules (id, interpretation_id, condition_json,"
                " attention_level, status, rule_version, created_by, created_at)"
                " VALUES (:id, :i, '{}'::jsonb, 'HIGH', 'VALIDATED', 1, 'u', :t)",
                id=uuid.uuid4(), i=interpretation_id, t=NOW)

    def test_rule_requires_an_interpretation(self):
        from sqlalchemy.exc import IntegrityError
        with self.assertRaises(IntegrityError):
            self._insert(
                "INSERT INTO computable_rules (id, interpretation_id, condition_json,"
                " attention_level, status, rule_version, created_by, created_at)"
                " VALUES (:id, NULL, '{}'::jsonb, 'HIGH', 'DRAFT', 1, 'u', :t)",
                id=uuid.uuid4(), t=NOW)

    # -- link tables -----------------------------------------------------

    def test_orphan_link_is_rejected(self):
        from sqlalchemy.exc import IntegrityError
        with self.assertRaises(IntegrityError):
            self._insert(
                "INSERT INTO rule_evidence (rule_id, evidence_record_id)"
                " VALUES (:r, :e)", r=uuid.uuid4(), e=uuid.uuid4())

    def test_duplicate_association_is_rejected(self):
        from sqlalchemy.exc import IntegrityError
        source_id = self._source(key="link-src")
        dataset_id = self._dataset(public_id="PGX-DATA-20260829-500")
        evidence_id = uuid.uuid4()
        interpretation_id = uuid.uuid4()
        self._insert(
            "INSERT INTO evidence_records (id, source_registry_id, dataset_version_id,"
            " source_record_id, source_record_version, raw_hash, evidence_metadata,"
            " publication_metadata, created_at)"
            " VALUES (:id, :s, :d, 'R1', '1', :h, '{}'::jsonb, '{}'::jsonb, :t)",
            id=evidence_id, s=source_id, d=dataset_id, h=DIGEST, t=NOW)
        self._insert(
            "INSERT INTO curated_interpretations (id, status, normalized_effect,"
            " significance, created_by, created_at)"
            " VALUES (:id, 'RAW', 'e', 's', 'u', :t)", id=interpretation_id, t=NOW)

        def link():
            self._insert(
                "INSERT INTO interpretation_evidence (interpretation_id, evidence_record_id)"
                " VALUES (:i, :e)", i=interpretation_id, e=evidence_id)

        link()
        with self.assertRaises(IntegrityError):
            link()


if __name__ == "__main__":
    unittest.main(verbosity=2)
