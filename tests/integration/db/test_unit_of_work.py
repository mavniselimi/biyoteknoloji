# -*- coding: utf-8 -*-
"""Transaction boundary and commit-time invariants (WP-02)."""

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


def _gene(symbol="CYP2C19"):
    from pgx.domain.identifiers import GeneId
    from pgx.domain.models import Gene
    return Gene(id=GeneId.new(), normalized_symbol=symbol, preferred_name=symbol,
                created_at=NOW)


class TestTransactionBoundary(PostgresTestCase):

    def _gene_count(self):
        from sqlalchemy import text
        with self.engine.connect() as connection:
            return connection.execute(text("SELECT count(*) FROM genes")).scalar_one()

    def test_commit_persists(self):
        with _uow(self.engine) as uow:
            uow.genes.add(_gene("CYP2C9"))
            uow.commit()
        self.assertEqual(self._gene_count(), 1)

    def test_leaving_the_context_without_commit_rolls_back(self):
        with _uow(self.engine) as uow:
            uow.genes.add(_gene("CYP2D6"))
        self.assertEqual(self._gene_count(), 0)

    def test_an_exception_rolls_back(self):
        class Boom(RuntimeError):
            pass

        with self.assertRaises(Boom):
            with _uow(self.engine) as uow:
                uow.genes.add(_gene("CYP3A4"))
                raise Boom("failure inside the transaction")
        self.assertEqual(self._gene_count(), 0)

    def test_explicit_rollback_discards(self):
        with _uow(self.engine) as uow:
            uow.genes.add(_gene("CYP1A2"))
            uow.rollback()
        self.assertEqual(self._gene_count(), 0)

    def test_repository_use_outside_the_context_fails(self):
        from pgx.infrastructure.db.session import create_session_factory
        from pgx.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

        uow = SqlAlchemyUnitOfWork(create_session_factory(self.engine))
        with self.assertRaises(RuntimeError):
            _ = uow.session


class TestCommitTimeInvariants(PostgresTestCase):
    """Cross-row rules that a single-row CHECK cannot express."""

    def _curated_interpretation(self, uow, status="CURATED"):
        from pgx.domain.enums import CurationStatus, DatasetStatus, SourceRole
        from pgx.domain.identifiers import (
            CuratedInterpretationId, DatasetPublicId, DatasetVersionId,
            EvidenceRecordId, SourceRegistryEntryId,
        )
        from pgx.domain.models import (
            CuratedInterpretation, DatasetVersion, EvidenceRecord, SourceRegistryEntry,
        )
        from pgx.infrastructure.db.mappers import dataset_version_to_orm

        source_id = SourceRegistryEntryId.new()
        dataset_id = DatasetVersionId.new()
        evidence_id = EvidenceRecordId.new()
        interpretation_id = CuratedInterpretationId.new()

        uow.source_registry.add(SourceRegistryEntry(
            id=source_id, source_key="inv-%s" % interpretation_id, display_name="d",
            role=SourceRole.PRIMARY_GUIDELINE, version_policy="p", license_policy="l",
            citation_policy="c", release_eligible=True, active=True, created_at=NOW))
        uow.session.add(dataset_version_to_orm(DatasetVersion(
            id=dataset_id, public_id=DatasetPublicId("PGX-DATA-20260829-002"),
            status=DatasetStatus.BUILDING, manifest_hash=DIGEST, created_at=NOW)))
        uow.evidence.add(EvidenceRecord(
            id=evidence_id, source_registry_id=source_id, dataset_version_id=dataset_id,
            source_record_id="R1", source_record_version="1", raw_hash=DIGEST,
            created_at=NOW))
        extra = {}
        if status == "CURATED":
            extra = {"rationale": "Reviewed.", "reviewed_by": "rev", "reviewed_at": NOW}
        uow.interpretations.add(CuratedInterpretation(
            id=interpretation_id, evidence_record_ids=(evidence_id,),
            status=CurationStatus(status), normalized_effect="e", significance="s",
            created_by="u", created_at=NOW, **extra))
        return interpretation_id, evidence_id

    def test_validated_rule_without_evidence_is_refused_at_commit(self):
        from pgx.domain.enums import AttentionLevel, RuleStatus
        from pgx.domain.errors import TraceabilityError
        from pgx.domain.identifiers import ComputableRuleId
        from pgx.domain.models import ComputableRule

        with self.assertRaises(TraceabilityError):
            with _uow(self.engine) as uow:
                interpretation_id, _ = self._curated_interpretation(uow)
                uow.rules.add(ComputableRule(
                    id=ComputableRuleId.new(), interpretation_id=interpretation_id,
                    evidence_record_ids=(), condition={"g": 1},
                    attention_level=AttentionLevel.HIGH, status=RuleStatus.VALIDATED,
                    rule_version=1, created_by="u", created_at=NOW,
                    approved_by="a", approved_at=NOW))
                uow.commit()

        from sqlalchemy import text
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(
                text("SELECT count(*) FROM computable_rules")).scalar_one(), 0)

    def test_validated_rule_on_an_uncurated_interpretation_is_refused(self):
        from pgx.domain.enums import AttentionLevel, RuleStatus
        from pgx.domain.errors import LifecycleError
        from pgx.domain.identifiers import ComputableRuleId
        from pgx.domain.models import ComputableRule

        with self.assertRaises(LifecycleError):
            with _uow(self.engine) as uow:
                interpretation_id, evidence_id = self._curated_interpretation(
                    uow, status="RAW")
                uow.rules.add(ComputableRule(
                    id=ComputableRuleId.new(), interpretation_id=interpretation_id,
                    evidence_record_ids=(evidence_id,), condition={"g": 1},
                    attention_level=AttentionLevel.HIGH, status=RuleStatus.VALIDATED,
                    rule_version=1, created_by="u", created_at=NOW,
                    approved_by="a", approved_at=NOW))
                uow.commit()

    def test_a_fully_backed_validated_rule_commits(self):
        from pgx.domain.enums import AttentionLevel, RuleStatus
        from pgx.domain.identifiers import ComputableRuleId
        from pgx.domain.models import ComputableRule

        with _uow(self.engine) as uow:
            interpretation_id, evidence_id = self._curated_interpretation(uow)
            uow.rules.add(ComputableRule(
                id=ComputableRuleId.new(), interpretation_id=interpretation_id,
                evidence_record_ids=(evidence_id,), condition={"g": 1},
                attention_level=AttentionLevel.HIGH, status=RuleStatus.VALIDATED,
                rule_version=1, created_by="u", created_at=NOW,
                approved_by="a", approved_at=NOW))
            uow.commit()

        with _uow(self.engine) as uow:
            self.assertEqual(len(uow.rules.list_validated()), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
