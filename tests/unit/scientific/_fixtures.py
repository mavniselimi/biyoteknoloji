# -*- coding: utf-8 -*-
"""Synthetic source policies for the WP-05 tests.

Every reviewer name here is ``TEST_SCIENTIFIC_REVIEWER`` and every URL points at
``.invalid``, which is reserved by RFC 2606 and can never resolve. That is
deliberate: WP-05 forbids inventing a reviewer or a licensing conclusion to make
a test pass, and the way to exercise an approval mechanism without doing so is
to make the fixture unmistakably fictional.

Nothing here describes CPIC, DPWG, ClinPGx or any other real source, and no
fixture is ever loaded from ``config/``.
"""

from __future__ import annotations

import datetime as _dt

from pgx.domain.enums import SourceRole
from pgx.domain.hashing import sha256_digest
from pgx.scientific.models import (
    AcquisitionMode,
    ClaimCategory,
    EvidenceType,
    EvidenceVerificationStatus,
    ReuseDimension,
    ReuseMatrix,
    ReusePermission,
    ReviewDecision,
    ReviewRecord,
    SourceEvidenceReference,
    SourcePolicyRecord,
    SourcePolicyStatus,
)
from pgx.scientific.policy import SourcePolicyRegistry

NOW = _dt.datetime(2026, 8, 30, 12, 0, 0, tzinfo=_dt.timezone.utc)
LATER = _dt.datetime(2027, 8, 30, 12, 0, 0, tzinfo=_dt.timezone.utc)

TEST_SCIENTIFIC_REVIEWER = "TEST_SCIENTIFIC_REVIEWER"
FIXTURE_TERMS_URL = "https://fixture.invalid/terms"


def verified_evidence() -> SourceEvidenceReference:
    """An evidence reference this project pretends to have retrieved."""
    return SourceEvidenceReference(
        evidence_type=EvidenceType.OFFICIAL_TERMS_PAGE,
        official_url=FIXTURE_TERMS_URL,
        retrieved_at=NOW,
        content_hash=sha256_digest({"fixture": "terms"}),
        summary="Synthetic fixture terms.",
        verification=EvidenceVerificationStatus.VERIFIED)


def blocked_evidence() -> SourceEvidenceReference:
    """A retrieval that failed - the state the real registry is in today."""
    return SourceEvidenceReference(
        evidence_type=EvidenceType.NOT_OBTAINED,
        official_url=FIXTURE_TERMS_URL,
        verification=EvidenceVerificationStatus.BLOCKED,
        blocked_reason="synthetic fixture: retrieval refused")


def approving_review(expires_at=None) -> ReviewRecord:
    return ReviewRecord(
        decision=ReviewDecision.APPROVE,
        reviewer_name=TEST_SCIENTIFIC_REVIEWER,
        reviewer_role="synthetic fixture reviewer",
        decided_at=NOW,
        evidence_urls=(FIXTURE_TERMS_URL,),
        expires_at=expires_at)


def permissive_matrix() -> ReuseMatrix:
    return ReuseMatrix({d: ReusePermission.ALLOWED for d in ReuseDimension})


def approved_source(
    source_key: str = "fixture.approved",
    categories=(ClaimCategory.PRIMARY_GUIDELINE_RECOMMENDATION,),
    reuse=None,
    expires_at=None,
) -> SourcePolicyRecord:
    """A complete, approved, synthetic source that passes every check."""
    return SourcePolicyRecord(
        source_key=source_key,
        display_name="Fixture approved source (synthetic)",
        role=SourceRole.PRIMARY_GUIDELINE,
        status=SourcePolicyStatus.APPROVED,
        acquisition_mode=AcquisitionMode.MANUAL_DOWNLOAD,
        version_policy="fixture: pinned by the test",
        citation_policy="fixture: cited as a fixture",
        license_identifier="FIXTURE-NOT-A-REAL-LICENCE",
        reuse=reuse if reuse is not None else permissive_matrix(),
        permitted_claim_categories=tuple(categories),
        evidence=(verified_evidence(),),
        review=approving_review(expires_at=expires_at))


def pending_source(source_key: str = "fixture.pending") -> SourcePolicyRecord:
    """The default shape: registered, unreviewed, nothing permitted."""
    return SourcePolicyRecord(
        source_key=source_key,
        display_name="Fixture pending source (synthetic)",
        role=SourceRole.SUPPORTING_ANNOTATION,
        evidence=(blocked_evidence(),),
        blocking_reasons=("no official terms have been retrieved",))


def registry(*records) -> SourcePolicyRegistry:
    return SourcePolicyRegistry(records=tuple(records))
