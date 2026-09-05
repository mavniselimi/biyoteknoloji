# -*- coding: utf-8 -*-
"""A complete, activatable release, and the knobs to break it one rule at a time.

Every rejection test in this suite starts from a release that *would* activate
and breaks exactly one thing. That shape matters: a test that builds a broken
release from scratch can pass because of an unrelated defect, and then keeps
passing after the rule it was meant to cover is deleted.

Nothing here is scientific content. The gene, drug and rule condition are
placeholders chosen to be obviously synthetic; the source is a fixture marked
release-eligible so the *mechanism* can be tested, and it asserts nothing about
any real scientific source.
"""

from __future__ import annotations

import datetime as _dt
from typing import Optional

from pgx.domain.enums import (
    AttentionLevel, CurationStatus, DatasetStatus, ReleaseStatus, RuleStatus,
    RulesetStatus, SourceRole,
)
from pgx.domain.hashing import sha256_digest
from pgx.domain.identifiers import (
    AuditEventId, ComputableRuleId, CuratedInterpretationId, DatasetPublicId,
    DatasetVersionId, DrugId, EvidenceRecordId, GeneId, ReleaseBundleId,
    ReleasePublicId, RulesetPublicId, RulesetVersionId, SoftwareVersionId,
    SourceRegistryEntryId,
)
from pgx.domain.models import (
    ComputableRule, DatasetVersion, EvidenceRecord, ReleaseBundle, RulesetVersion,
    SoftwareVersion, SourceRegistryEntry,
)
from pgx.domain.release_manifest import build_release_manifest, manifest_digest

from pgx.scientific.models import (
    AcquisitionMode, ClaimCategory, EvidenceType, EvidenceVerificationStatus,
    ReuseDimension, ReuseMatrix, ReusePermission, ReviewDecision, ReviewRecord,
    SourceEvidenceReference, SourcePolicyRecord, SourcePolicyStatus,
)
from pgx.scientific.policy import SourcePolicyRegistry

from tests.unit.application._fakes import FakeWorld

NOW = _dt.datetime(2026, 8, 29, 12, 0, 0, tzinfo=_dt.timezone.utc)
LATER = _dt.datetime(2026, 8, 29, 13, 0, 0, tzinfo=_dt.timezone.utc)

DATASET_HASH = sha256_digest({"fixture": "dataset"})
RULESET_HASH = sha256_digest({"fixture": "ruleset"})
SOFTWARE_TREE_HASH = sha256_digest({"fixture": "source-tree"})
SOFTWARE_MANIFEST_HASH = sha256_digest({"fixture": "software-manifest"})
EVIDENCE_HASH = sha256_digest({"fixture": "evidence"})

#: Reviewer identity used by the release fixtures. Deliberately shouted and
#: obviously synthetic: WP-05 forbids inventing a reviewer to make a test pass,
#: and the way to honour that while still exercising the mechanism is to use a
#: name no reader could mistake for a person. Nothing in ``config/`` carries it.
TEST_SCIENTIFIC_REVIEWER = "TEST_SCIENTIFIC_REVIEWER"

#: The one source key the fixture registry approves.
FIXTURE_SOURCE_KEY = "fixture-source"


def fixture_source_policy() -> SourcePolicyRegistry:
    """A registry that approves only the synthetic fixture source.

    WP-05 makes ``source_registry.release_eligible`` insufficient on its own: a
    release may cite a source only when the reviewed policy approves it. The
    WP-03 fixtures therefore need a policy, and this is it - complete enough to
    pass the gate, and about a source that does not exist.

    It asserts nothing about any real scientific source. The checked-in
    ``config/scientific-sources.json`` stays entirely unapproved, and a test
    asserts that too.
    """
    review = ReviewRecord(
        decision=ReviewDecision.APPROVE,
        reviewer_name=TEST_SCIENTIFIC_REVIEWER,
        reviewer_role="synthetic reviewer for release-service fixtures",
        decided_at=NOW,
        evidence_urls=("https://fixture.invalid/terms",),
        notes="Fixture only. No real source was reviewed to produce this record.")
    evidence = SourceEvidenceReference(
        evidence_type=EvidenceType.OFFICIAL_TERMS_PAGE,
        official_url="https://fixture.invalid/terms",
        retrieved_at=NOW,
        content_hash=sha256_digest({"fixture": "terms"}),
        summary="Synthetic fixture terms; not a real source's wording.",
        verification=EvidenceVerificationStatus.VERIFIED)
    permitted = {dimension: ReusePermission.ALLOWED for dimension in ReuseDimension}
    record = SourcePolicyRecord(
        source_key=FIXTURE_SOURCE_KEY,
        display_name="Fixture source (synthetic, not a real scientific source)",
        role=SourceRole.PRIMARY_GUIDELINE,
        status=SourcePolicyStatus.APPROVED,
        acquisition_mode=AcquisitionMode.MANUAL_DOWNLOAD,
        version_policy="fixture: pinned by the test",
        citation_policy="fixture: cited as a fixture",
        license_identifier="FIXTURE-NOT-A-REAL-LICENCE",
        reuse=ReuseMatrix(permitted),
        permitted_claim_categories=(ClaimCategory.PRIMARY_GUIDELINE_RECOMMENDATION,),
        evidence=(evidence,),
        review=review)
    return SourcePolicyRegistry(records=(record,))


class Scenario:
    """A world holding one activatable release, plus its parts."""

    def __init__(
        self,
        *,
        dataset_status: DatasetStatus = DatasetStatus.PUBLISHED,
        ruleset_status: RulesetStatus = RulesetStatus.FROZEN,
        rule_status: RuleStatus = RuleStatus.VALIDATED,
        release_status: ReleaseStatus = ReleaseStatus.DRAFT,
        register_software: bool = True,
        register_rule: bool = True,
        register_evidence: bool = True,
        rule_has_evidence: bool = True,
        evidence_in_dataset: bool = True,
        source_release_eligible: bool = True,
        source_role: SourceRole = SourceRole.PRIMARY_GUIDELINE,
        empty_ruleset: bool = False,
        dataset_hash_in_manifest: Optional[str] = None,
        ruleset_hash_in_manifest: Optional[str] = None,
        corrupt_manifest_hash: bool = False,
        public_id: str = "PGX-REL-20260829-001",
    ) -> None:
        self.world = FakeWorld()
        store = self.world.store

        self.software = SoftwareVersion(
            id=SoftwareVersionId.new(), version="0.3.0.dev0",
            source_commit="0123456789abcdef", source_tree_hash=SOFTWARE_TREE_HASH,
            manifest_hash=SOFTWARE_MANIFEST_HASH, built_at=NOW, created_at=NOW)
        if register_software:
            store.software[self.software.id] = self.software

        self.source = SourceRegistryEntry(
            id=SourceRegistryEntryId.new(), source_key="fixture-source",
            display_name="Fixture source (synthetic, not a real scientific source)",
            role=source_role, version_policy="pinned", license_policy="recorded",
            citation_policy="recorded",
            release_eligible=(source_release_eligible
                              and source_role is not SourceRole.INTERNAL_SYSTEM),
            active=True, created_at=NOW)
        store.sources[self.source.id] = self.source

        self.dataset = DatasetVersion(
            id=DatasetVersionId.new(),
            public_id=DatasetPublicId("PGX-DATA-20260829-001"),
            status=dataset_status, manifest_hash=DATASET_HASH, created_at=NOW,
            approved_by=("approver@example.org"
                         if dataset_status is DatasetStatus.PUBLISHED else None),
            approved_at=NOW if dataset_status is DatasetStatus.PUBLISHED else None)
        store.datasets[self.dataset.id] = self.dataset

        self.other_dataset = DatasetVersion(
            id=DatasetVersionId.new(),
            public_id=DatasetPublicId("PGX-DATA-20260829-002"),
            status=DatasetStatus.PUBLISHED, manifest_hash=DATASET_HASH,
            created_at=NOW, approved_by="approver@example.org", approved_at=NOW)
        store.datasets[self.other_dataset.id] = self.other_dataset

        evidence_dataset = (self.dataset if evidence_in_dataset
                            else self.other_dataset)
        self.evidence = EvidenceRecord(
            id=EvidenceRecordId.new(),
            source_registry_id=self.source.id,
            dataset_version_id=evidence_dataset.id,
            source_record_id="FIXTURE-1", source_record_version="1",
            raw_hash=EVIDENCE_HASH, created_at=NOW)
        if register_evidence:
            store.evidence[self.evidence.id] = self.evidence

        self.rule = ComputableRule(
            id=ComputableRuleId.new(),
            interpretation_id=CuratedInterpretationId.new(),
            evidence_record_ids=((self.evidence.id,) if rule_has_evidence else ()),
            condition={"fixture": True},
            attention_level=AttentionLevel.HIGH,
            status=rule_status, rule_version=1,
            created_by="curator@example.org", created_at=NOW,
            approved_by=("approver@example.org"
                         if rule_status is RuleStatus.VALIDATED else None),
            approved_at=NOW if rule_status is RuleStatus.VALIDATED else None)
        if register_rule:
            store.rules[self.rule.id] = self.rule

        members = () if empty_ruleset else (self.rule.id,)
        self.ruleset = RulesetVersion(
            id=RulesetVersionId.new(),
            public_id=RulesetPublicId("PGX-RULESET-20260829-001"),
            status=ruleset_status, manifest_hash=RULESET_HASH, created_at=NOW,
            rule_ids=members,
            approved_by=("approver@example.org"
                         if ruleset_status in (RulesetStatus.VALIDATED,
                                               RulesetStatus.FROZEN) else None),
            approved_at=(NOW if ruleset_status in (RulesetStatus.VALIDATED,
                                                   RulesetStatus.FROZEN) else None))
        store.rulesets[self.ruleset.id] = self.ruleset

        manifest = build_release_manifest(
            release_public_id=ReleasePublicId(public_id),
            software=self.software, dataset=self.dataset, ruleset=self.ruleset)

        # Rewrite a pinned hash to simulate a release whose manifest and stored
        # records have drifted apart.
        if dataset_hash_in_manifest or ruleset_hash_in_manifest:
            payload = _thaw(manifest)
            if dataset_hash_in_manifest:
                payload["dataset"]["manifest_hash"] = dataset_hash_in_manifest
            if ruleset_hash_in_manifest:
                payload["ruleset"]["manifest_hash"] = ruleset_hash_in_manifest
            manifest = payload

        digest = manifest_digest(manifest)
        if corrupt_manifest_hash:
            digest = sha256_digest({"unrelated": "payload"})

        self.release = ReleaseBundle(
            id=ReleaseBundleId.new(), public_id=ReleasePublicId(public_id),
            software_version_id=self.software.id,
            dataset_version_id=self.dataset.id,
            ruleset_version_id=self.ruleset.id,
            manifest=manifest, manifest_hash=digest,
            status=release_status, created_at=NOW,
            activated_at=(NOW if release_status in (ReleaseStatus.ACTIVE,
                                                    ReleaseStatus.ROLLED_BACK)
                          else None),
            activated_by=("ops@example.org"
                          if release_status in (ReleaseStatus.ACTIVE,
                                                ReleaseStatus.ROLLED_BACK)
                          else None))
        store.releases[self.release.id] = self.release

    def add_release(self, public_id: str) -> ReleaseBundle:
        """Register a second activatable release pinning the same triple."""
        manifest = build_release_manifest(
            release_public_id=ReleasePublicId(public_id),
            software=self.software, dataset=self.dataset, ruleset=self.ruleset)
        release = ReleaseBundle(
            id=ReleaseBundleId.new(), public_id=ReleasePublicId(public_id),
            software_version_id=self.software.id,
            dataset_version_id=self.dataset.id,
            ruleset_version_id=self.ruleset.id,
            manifest=manifest, manifest_hash=manifest_digest(manifest),
            status=ReleaseStatus.DRAFT, created_at=NOW)
        self.world.store.releases[release.id] = release
        return release


def _thaw(value):
    """Plain-container copy, so a fixture can edit a manifest before freezing."""
    from pgx.domain.release_manifest import as_plain_json

    return as_plain_json(value)


class StepClock:
    """A clock that advances one second per call. Deterministic and ordered."""

    def __init__(self, start: _dt.datetime = NOW) -> None:
        self._current = start

    def __call__(self) -> _dt.datetime:
        value = self._current
        self._current = self._current + _dt.timedelta(seconds=1)
        return value


class CountingEventIds:
    """Deterministic audit identities, so a test can name the event it expects."""

    def __init__(self) -> None:
        self.issued = []

    def __call__(self) -> AuditEventId:
        event_id = AuditEventId.parse(
            "00000000-0000-4000-8000-%012d" % (len(self.issued) + 1))
        self.issued.append(event_id)
        return event_id
