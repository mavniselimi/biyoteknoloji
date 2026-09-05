# -*- coding: utf-8 -*-
"""Shared domain test fixtures (WP-02). Standard library only."""

from __future__ import annotations

import datetime as _dt
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from pgx.domain.enums import (  # noqa: E402
    AttentionLevel, CurationStatus, Phenotype, RuleStatus, SourceRole,
)
from pgx.domain.identifiers import (  # noqa: E402
    ComputableRuleId, CuratedInterpretationId, DatasetPublicId, DatasetVersionId,
    DrugId, EvidenceRecordId, GeneId, SourceRegistryEntryId,
)
from pgx.domain.models import (  # noqa: E402
    ComputableRule, CuratedInterpretation, EvidenceRecord, SourceRegistryEntry,
)

REPO_ROOT = _REPO_ROOT

NOW = _dt.datetime(2026, 8, 29, 12, 0, 0, tzinfo=_dt.timezone.utc)
NAIVE = _dt.datetime(2026, 8, 29, 12, 0, 0)
DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64


def make_source_entry(**overrides: object) -> SourceRegistryEntry:
    """A minimal valid source registry entry."""
    values = dict(
        id=SourceRegistryEntryId.new(),
        source_key="test-source",
        display_name="Test source",
        role=SourceRole.REFERENCE_ONLY,
        version_policy="pinned",
        license_policy="recorded",
        citation_policy="recorded",
        release_eligible=False,
        active=True,
        created_at=NOW,
    )
    values.update(overrides)
    return SourceRegistryEntry(**values)  # type: ignore[arg-type]


def make_evidence(**overrides: object) -> EvidenceRecord:
    """A minimal valid evidence record."""
    values = dict(
        id=EvidenceRecordId.new(),
        source_registry_id=SourceRegistryEntryId.new(),
        dataset_version_id=DatasetVersionId.new(),
        source_record_id="REC-1",
        source_record_version="1",
        raw_hash=DIGEST,
        created_at=NOW,
    )
    values.update(overrides)
    return EvidenceRecord(**values)  # type: ignore[arg-type]


def make_interpretation(**overrides: object) -> CuratedInterpretation:
    """A minimal valid RAW interpretation with one evidence reference."""
    values = dict(
        id=CuratedInterpretationId.new(),
        evidence_record_ids=(EvidenceRecordId.new(),),
        status=CurationStatus.RAW,
        normalized_effect="DECREASED_ACTIVATION",
        significance="documented",
        created_by="curator@example.org",
        created_at=NOW,
    )
    values.update(overrides)
    return CuratedInterpretation(**values)  # type: ignore[arg-type]


def make_curated_interpretation(**overrides: object) -> CuratedInterpretation:
    """A valid CURATED interpretation with complete review metadata."""
    values = dict(
        status=CurationStatus.CURATED,
        rationale="Reviewed against the source guideline.",
        reviewed_by="reviewer@example.org",
        reviewed_at=NOW,
    )
    values.update(overrides)
    return make_interpretation(**values)


def make_rule(**overrides: object) -> ComputableRule:
    """A minimal valid DRAFT rule."""
    values = dict(
        id=ComputableRuleId.new(),
        interpretation_id=CuratedInterpretationId.new(),
        evidence_record_ids=(EvidenceRecordId.new(),),
        condition={"gene": "CYP2C19", "phenotype_in": ["POOR"]},
        attention_level=AttentionLevel.HIGH,
        status=RuleStatus.DRAFT,
        rule_version=1,
        created_by="curator@example.org",
        created_at=NOW,
    )
    values.update(overrides)
    return ComputableRule(**values)  # type: ignore[arg-type]


def make_validated_rule(**overrides: object) -> ComputableRule:
    """A valid VALIDATED rule with approval metadata and evidence."""
    values = dict(
        status=RuleStatus.VALIDATED,
        approved_by="approver@example.org",
        approved_at=NOW,
    )
    values.update(overrides)
    return make_rule(**values)


__all__ = [
    "DIGEST", "NAIVE", "NOW", "OTHER_DIGEST", "REPO_ROOT",
    "AttentionLevel", "ComputableRuleId", "CurationStatus", "CuratedInterpretationId",
    "DatasetPublicId", "DatasetVersionId", "DrugId", "EvidenceRecordId", "GeneId",
    "Phenotype", "RuleStatus", "SourceRegistryEntryId", "SourceRole",
    "make_curated_interpretation", "make_evidence", "make_interpretation",
    "make_rule", "make_source_entry", "make_validated_rule",
]
