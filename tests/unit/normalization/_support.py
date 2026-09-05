# -*- coding: utf-8 -*-
"""Shared builders for the WP-07 tests.

Small, explicit factories rather than fixtures loaded from disk: a test that
asserts an ambiguity is reported should show the two colliding entities in the
test body, where the reader can see why they collide.
"""

from __future__ import annotations

import datetime as _dt
import os
from typing import Optional, Sequence

from pgx.normalization.models import (AliasProposal, AliasStatus,
                                      CanonicalEntity, EntityType, RawLocator,
                                      canonical_key_for)
from pgx.normalization.normalize import ExternalIdentifier

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

DATASET_ID = "PGX-DATA-20260830-900"
MANIFEST_HASH = "sha256:" + "3b" * 32
ARTIFACT_HASH = "sha256:" + "7c" * 32
REVIEWED_AT = _dt.datetime(2026, 8, 30, 12, 0, tzinfo=_dt.timezone.utc)


def locator(pointer: str = "/CYP2C19",
            artifact_path: str = "responses/resolved_genes.json",
            source_record_id: Optional[str] = "PA124") -> RawLocator:
    """A well-formed locator pointing at the legacy snapshot's shape."""
    return RawLocator(
        dataset_public_id=DATASET_ID,
        snapshot_manifest_hash=MANIFEST_HASH,
        artifact_path=artifact_path,
        artifact_sha256=ARTIFACT_HASH,
        pointer=pointer,
        source_record_id=source_record_id)


def approved_alias(normalized: str, display: Optional[str] = None,
                   reviewer: str = "test-reviewer") -> AliasProposal:
    """An alias a named reviewer approved. Requires both, by construction."""
    return AliasProposal(
        normalized_alias=normalized,
        display_alias=display or normalized,
        status=AliasStatus.APPROVED,
        reviewed_by=reviewer,
        reviewed_at=REVIEWED_AT,
        note="approved in a test")


def pending_alias(normalized: str,
                  display: Optional[str] = None) -> AliasProposal:
    """An alias nobody has reviewed. Resolves nothing."""
    return AliasProposal(normalized_alias=normalized,
                         display_alias=display or normalized,
                         status=AliasStatus.PENDING_REVIEW)


def gene(symbol: str = "CYP2C19", *,
         external_ids: Sequence[ExternalIdentifier] = (),
         aliases: Sequence[AliasProposal] = (),
         entity_uuid: Optional[str] = None,
         preferred: Optional[str] = None) -> CanonicalEntity:
    return CanonicalEntity(
        entity_type=EntityType.GENE,
        canonical_key=canonical_key_for(EntityType.GENE, symbol),
        normalized_value=symbol,
        preferred_display=preferred or symbol,
        source_display=symbol,
        entity_uuid=entity_uuid,
        external_ids=tuple(external_ids),
        aliases=tuple(aliases),
        locators=(locator("/%s" % symbol),))


def drug(name: str = "clopidogrel", *,
         external_ids: Sequence[ExternalIdentifier] = (),
         aliases: Sequence[AliasProposal] = (),
         entity_uuid: Optional[str] = None,
         preferred: Optional[str] = None) -> CanonicalEntity:
    return CanonicalEntity(
        entity_type=EntityType.DRUG,
        canonical_key=canonical_key_for(EntityType.DRUG, name),
        normalized_value=name,
        preferred_display=preferred or name,
        source_display=name,
        entity_uuid=entity_uuid,
        external_ids=tuple(external_ids),
        aliases=tuple(aliases),
        locators=(locator("/%s" % name,
                          artifact_path="responses/resolved_chemicals.json",
                          source_record_id="PA449053"),))


def clinpgx(value: str) -> ExternalIdentifier:
    return ExternalIdentifier("clinpgx", value)
