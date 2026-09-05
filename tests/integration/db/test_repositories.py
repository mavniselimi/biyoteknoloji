# -*- coding: utf-8 -*-
"""Repository mapping round trips on real PostgreSQL (WP-02)."""

from __future__ import annotations

import datetime as _dt
import unittest

from tests.integration.db._support import PostgresTestCase

NOW = _dt.datetime(2026, 8, 29, 12, 0, tzinfo=_dt.timezone.utc)
DIGEST = "sha256:" + "a" * 64


def _uow(engine):
    from pgx.infrastructure.db.session import create_session_factory
    from pgx.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
    return SqlAlchemyUnitOfWork(create_session_factory(engine))


class TestRoundTrips(PostgresTestCase):

    def test_gene_round_trip_returns_a_domain_object(self):
        from pgx.domain.identifiers import GeneId
        from pgx.domain.models import Gene
        from pgx.infrastructure.db.models import GeneORM

        gene = Gene(id=GeneId.new(), normalized_symbol="CYP2C19",
                    preferred_name="Cytochrome P450 2C19", created_at=NOW,
                    aliases=("CPCJ", "P450IIC19"))
        with _uow(self.engine) as uow:
            uow.genes.add(gene)
            uow.commit()

        with _uow(self.engine) as uow:
            loaded = uow.genes.get(gene.id)

        self.assertIsInstance(loaded, Gene)
        self.assertNotIsInstance(loaded, GeneORM)
        self.assertEqual(loaded.normalized_symbol, "CYP2C19")
        self.assertEqual(loaded.aliases, ("CPCJ", "P450IIC19"))
        self.assertEqual(loaded.created_at, NOW)

    def test_domain_object_is_usable_after_the_session_closes(self):
        from pgx.domain.identifiers import DrugId
        from pgx.domain.models import Drug

        drug = Drug(id=DrugId.new(), normalized_name="clopidogrel",
                    preferred_name="Clopidogrel", created_at=NOW, aliases=("Plavix",))
        with _uow(self.engine) as uow:
            uow.drugs.add(drug)
            uow.commit()
        with _uow(self.engine) as uow:
            loaded = uow.drugs.get(drug.id)
        # Session is closed here; reading must not trigger a lazy load.
        self.assertEqual(loaded.aliases, ("Plavix",))
        self.assertEqual(loaded.preferred_name, "Clopidogrel")

    def test_ambiguous_alias_returns_every_match(self):
        from pgx.domain.identifiers import GeneId
        from pgx.domain.models import Gene

        with _uow(self.engine) as uow:
            for symbol in ("GENEA", "GENEB"):
                uow.genes.add(Gene(id=GeneId.new(), normalized_symbol=symbol,
                                   preferred_name=symbol, created_at=NOW,
                                   aliases=("SHARED",)))
            uow.commit()
        with _uow(self.engine) as uow:
            matches = uow.genes.find_by_alias("SHARED")
        self.assertEqual(len(matches), 2)

    def test_wrong_domain_type_is_rejected_at_runtime(self):
        from pgx.domain.errors import RepositoryTypeError
        from pgx.domain.identifiers import AssessmentId, ReleaseBundleId
        from pgx.domain.models import Assessment

        assessment = Assessment(id=AssessmentId.new(),
                                release_bundle_id=ReleaseBundleId.new(), mode="DEMO",
                                input_hash=DIGEST, created_at=NOW)
        with _uow(self.engine) as uow:
            with self.assertRaises(RepositoryTypeError):
                uow.evidence.add(assessment)
            with self.assertRaises(RepositoryTypeError):
                uow.rules.add(assessment)

    def test_full_evidence_interpretation_rule_chain_in_one_transaction(self):
        from pgx.domain.enums import (
            AttentionLevel, CurationStatus, DatasetStatus, RuleStatus, SourceRole,
        )
        from pgx.domain.identifiers import (
            ComputableRuleId, CuratedInterpretationId, DatasetPublicId, DatasetVersionId,
            EvidenceRecordId, SourceRegistryEntryId,
        )
        from pgx.domain.models import (
            ComputableRule, CuratedInterpretation, DatasetVersion, EvidenceRecord,
            SourceRegistryEntry,
        )
        from sqlalchemy import text

        source_id = SourceRegistryEntryId.new()
        dataset_id = DatasetVersionId.new()
        evidence_id = EvidenceRecordId.new()
        interpretation_id = CuratedInterpretationId.new()

        with _uow(self.engine) as uow:
            uow.source_registry.add(SourceRegistryEntry(
                id=source_id, source_key="chain-src", display_name="Chain",
                role=SourceRole.PRIMARY_GUIDELINE, version_policy="pinned",
                license_policy="recorded", citation_policy="recorded",
                release_eligible=True, active=True, created_at=NOW))
            uow.session.add(_dataset_row(dataset_id, DatasetStatus, DatasetPublicId,
                                         DatasetVersion))
            uow.evidence.add(EvidenceRecord(
                id=evidence_id, source_registry_id=source_id,
                dataset_version_id=dataset_id, source_record_id="R1",
                source_record_version="1", raw_hash=DIGEST, created_at=NOW))
            uow.interpretations.add(CuratedInterpretation(
                id=interpretation_id, evidence_record_ids=(evidence_id,),
                status=CurationStatus.CURATED, normalized_effect="DECREASED_ACTIVATION",
                significance="documented", created_by="curator", created_at=NOW,
                rationale="Reviewed.", reviewed_by="reviewer", reviewed_at=NOW))
            uow.rules.add(ComputableRule(
                id=ComputableRuleId.new(), interpretation_id=interpretation_id,
                evidence_record_ids=(evidence_id,),
                condition={"gene": "CYP2C19", "phenotype_in": ["POOR"]},
                attention_level=AttentionLevel.HIGH, status=RuleStatus.VALIDATED,
                rule_version=1, created_by="curator", created_at=NOW,
                approved_by="approver", approved_at=NOW))
            uow.commit()

        with _uow(self.engine) as uow:
            validated = uow.rules.list_validated()
            self.assertEqual(len(validated), 1)
            self.assertTrue(validated[0].is_executable)
            self.assertEqual(validated[0].evidence_record_ids, (evidence_id,))
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.execute(text("SELECT count(*) FROM rule_evidence")).scalar_one(), 1)


def _dataset_row(dataset_id, DatasetStatus, DatasetPublicId, DatasetVersion):
    from pgx.infrastructure.db.mappers import dataset_version_to_orm
    return dataset_version_to_orm(DatasetVersion(
        id=dataset_id, public_id=DatasetPublicId("PGX-DATA-20260829-001"),
        status=DatasetStatus.BUILDING, manifest_hash=DIGEST, created_at=NOW))


if __name__ == "__main__":
    unittest.main(verbosity=2)
