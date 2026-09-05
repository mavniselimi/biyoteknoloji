# -*- coding: utf-8 -*-
"""SYNTHETIC WP-14 assessment fixtures. TEST ONLY. NOT CLINICAL DATA.

NOT FOR REAL ASSESSMENT. Every claim boundary, release, dataset, ruleset,
coverage manifest, actor and approval below is invented so that the assessment
engine can be executed end to end. Nothing here was reviewed by anybody, and
none of it is a statement about any medicine.

Two things in this file would be dangerous if they escaped, and both are
deliberately shaped so they cannot.

**The approved claim boundary.** ``synthetic_claim_boundary()`` builds a
``ClaimBoundary`` whose status reads as approved, which is the one thing
``DEFAULT_CLAIM_BOUNDARY`` must never do. It is constructed here, in a test
fixture, and returned to a caller who passes it explicitly into a service. It
is never installed as a default, never written to configuration, and a
boundary test asserts that no module under ``pgx/`` constructs one.

**The active release.** The synthetic release is ACTIVE in an object graph
held in memory by one test. There is no active release in this repository's
database and this fixture does not create one.
"""

from __future__ import annotations

import datetime as _dt
import os
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from pgx.application.assessment_models import (CanonicalEntityIndex,
                                               PinnedAssessmentRelease)
from pgx.domain.claims import (CANONICAL_CLINICAL_WARNING, ClaimBoundary,
                               ClaimPhase, OperationMode, PermittedInputKind,
                               ProhibitedClaimCategory)
from pgx.domain.enums import ReleaseStatus
from pgx.domain.hashing import sha256_digest
from pgx.domain.identifiers import (DatasetVersionId, ReleaseBundleId,
                                    ReleasePublicId, RulesetVersionId,
                                    SoftwareVersionId)
from pgx.domain.models import PinnedReleaseProvenance, ReleaseBundle

SYNTHETIC_MARKERS: Tuple[str, ...] = (
    "SYNTHETIC", "TEST ONLY", "NOT CLINICAL DATA", "NOT FOR REAL ASSESSMENT")

#: A status string that reads as approved. ``ClaimBoundary.is_approved`` is
#: false whenever the status contains DRAFT or AWAITING, so this deliberately
#: contains neither - and says TEST ONLY instead, so a human reading a log
#: line cannot mistake it for the real thing.
SYNTHETIC_BOUNDARY_STATUS = "SYNTHETIC-APPROVED (TEST ONLY, NOT A REAL APPROVAL)"
SYNTHETIC_BOUNDARY_VERSION = "test-claim-boundary/9.9.9-synthetic"

TEST_ACTOR = "TEST-assessment-actor-1"
SYNTHETIC_RELEASE_PUBLIC_ID = "PGX-REL-29991231-001"
SYNTHETIC_SOFTWARE_VERSION = "0.0.0-test-synthetic"

NOW = _dt.datetime(2099, 1, 4, 10, 0, 0, tzinfo=_dt.timezone.utc)

#: The identities the synthetic canonical dataset holds. Written out as a
#: literal table rather than derived from the keys, because that is what the
#: real thing is: identity is minted once when a canonical dataset is built,
#: and everything afterwards looks it up. A fixture that computed these from
#: the names would be exercising a derivation the production code refuses to
#: have.
#:
#: ``DRUG:testdrug-omega`` is deliberately absent. A medication the pinned
#: dataset does not contain must still be assessable - and reported as
#: unsupported - so the index has to be able to not know something.
SYNTHETIC_DRUG_IDS: Mapping[str, str] = {
    "DRUG:testdrug-alpha": "a55e55ed-0000-4000-8000-00000000d001",
    "DRUG:testdrug-beta": "a55e55ed-0000-4000-8000-00000000d002",
}

SYNTHETIC_GENE_IDS: Mapping[str, str] = {
    "GENE:TESTGENE1": "a55e55ed-0000-4000-8000-00000000e001",
    "GENE:TESTGENE2": "a55e55ed-0000-4000-8000-00000000e002",
    "GENE:TESTGENE3": "a55e55ed-0000-4000-8000-00000000e003",
    "GENE:TESTGENE4": "a55e55ed-0000-4000-8000-00000000e004",
    "GENE:TESTGENE5": "a55e55ed-0000-4000-8000-00000000e005",
}


def synthetic_entity_index(*, drugs: Optional[Mapping[str, str]] = None,
                           genes: Optional[Mapping[str, str]] = None,
                           **overrides: Any) -> CanonicalEntityIndex:
    """The canonical identity lookup for the synthetic dataset. TEST ONLY."""
    return CanonicalEntityIndex.from_pairs(
        drugs=tuple((SYNTHETIC_DRUG_IDS if drugs is None else drugs).items()),
        genes=tuple((SYNTHETIC_GENE_IDS if genes is None else genes).items()),
        dataset_public_id=overrides.get("dataset_public_id",
                                        "PGX-DATA-29991231-001"),
        canonical_build_content_hash=overrides.get(
            "canonical_build_content_hash", "sha256:" + "5" * 64))


def synthetic_claim_boundary(**overrides: Any) -> ClaimBoundary:
    """A claim boundary that permits execution. TEST ONLY.

    Every prohibited category still applies and PILOT is still disabled: an
    approved boundary is not an unrestricted one, and a fixture that relaxed
    the prohibitions as well would be testing a product nobody proposed.
    """
    values: Dict[str, Any] = {
        "phase": ClaimPhase.P0,
        "enabled_modes": frozenset({OperationMode.DEMO,
                                    OperationMode.VALIDATION}),
        "prohibited_categories": frozenset(ProhibitedClaimCategory),
        "permitted_input_kinds": frozenset(PermittedInputKind),
        "version": SYNTHETIC_BOUNDARY_VERSION,
        "status": SYNTHETIC_BOUNDARY_STATUS,
        "warning_by_language": CANONICAL_CLINICAL_WARNING,
    }
    values.update(overrides)
    return ClaimBoundary(**values)


def synthetic_release_manifest(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "release_public_id": SYNTHETIC_RELEASE_PUBLIC_ID,
        "software_version": SYNTHETIC_SOFTWARE_VERSION,
        "note": "SYNTHETIC TEST ONLY. NOT FOR REAL ASSESSMENT.",
    }
    payload.update(overrides)
    return payload


def synthetic_release_bundle(*, status: ReleaseStatus = ReleaseStatus.ACTIVE,
                             manifest: Optional[Mapping[str, Any]] = None,
                             manifest_hash: Optional[str] = None,
                             **overrides: Any) -> ReleaseBundle:
    """An ACTIVE synthetic release bundle held in memory. TEST ONLY."""
    document = dict(manifest if manifest is not None
                    else synthetic_release_manifest())
    values: Dict[str, Any] = {
        "id": ReleaseBundleId.new(),
        "public_id": ReleasePublicId(SYNTHETIC_RELEASE_PUBLIC_ID),
        "software_version_id": SoftwareVersionId.new(),
        "dataset_version_id": DatasetVersionId.new(),
        "ruleset_version_id": RulesetVersionId.new(),
        "manifest": document,
        "manifest_hash": manifest_hash or sha256_digest(document),
        "status": status,
        "created_at": NOW,
    }
    if status in (ReleaseStatus.ACTIVE, ReleaseStatus.ROLLED_BACK):
        values["activated_at"] = NOW
        values["activated_by"] = TEST_ACTOR
    values.update(overrides)
    return ReleaseBundle(**values)


def synthetic_provenance(*, release: ReleaseBundle, coverage_manifest,
                         frozen_ruleset, generation: int = 1,
                         **overrides: Any) -> PinnedReleaseProvenance:
    """The pinned version set, derived from the synthetic artifacts."""
    values: Dict[str, Any] = {
        "release_public_id": release.public_id.to_json(),
        "release_manifest_hash": release.manifest_hash,
        "active_pointer_generation": generation,
        "software_version_id": release.software_version_id,
        "software_version": SYNTHETIC_SOFTWARE_VERSION,
        "software_source_tree_hash": "sha256:" + "7" * 64,
        "dataset_version_id": release.dataset_version_id,
        "dataset_public_id": coverage_manifest.dataset_public_id,
        "canonical_build_content_hash":
            coverage_manifest.canonical_build_content_hash,
        "ruleset_version_id": release.ruleset_version_id,
        "ruleset_public_id": coverage_manifest.ruleset_public_id,
        "ruleset_content_hash": coverage_manifest.ruleset_content_hash,
        "evidence_build_key": coverage_manifest.evidence_build_key,
        "evidence_build_content_hash":
            coverage_manifest.evidence_build_content_hash,
        "coverage_manifest_hash": coverage_manifest.content_hash(),
        "protocol_version": coverage_manifest.protocol_version,
        "protocol_content_hash": coverage_manifest.protocol_content_hash,
        "source_policy_version": coverage_manifest.source_policy_version,
        "source_policy_content_hash":
            coverage_manifest.source_policy_content_hash,
    }
    values.update(overrides)
    return PinnedReleaseProvenance(**values)


class SyntheticReleaseResolver:
    """A ``ReleaseContextResolver`` over in-memory synthetic artifacts.

    Reads its pointer exactly once per resolve and counts the reads, so a test
    can assert that the service does not consult it again mid-calculation.
    ``move_pointer`` simulates an activation committing after a pin: it
    advances the generation, and the already-pinned context is unaffected
    because it is a value, not a lookup.
    """

    def __init__(self, *, release: ReleaseBundle, frozen_ruleset,
                 coverage_manifest, drug_catalogue: Sequence[str],
                 evidence_resolver=None, generation: int = 1,
                 coverage_manifests: Optional[Sequence[Any]] = None,
                 entity_index: Optional[CanonicalEntityIndex] = None):
        self.release = release
        self.frozen_ruleset = frozen_ruleset
        self.coverage_manifest = coverage_manifest
        self.coverage_manifests = list(
            coverage_manifests if coverage_manifests is not None
            else [coverage_manifest])
        self.drug_catalogue = tuple(drug_catalogue)
        self.evidence_resolver = evidence_resolver
        self.entity_index = (synthetic_entity_index()
                             if entity_index is None else entity_index)
        self.generation = generation
        self.pointer_reads = 0

    def move_pointer(self, *, release: Optional[ReleaseBundle] = None) -> None:
        """Simulate another activation committing."""
        self.generation += 1
        if release is not None:
            self.release = release

    def resolve(self, *, requested_release_public_id: Optional[str] = None
                ) -> PinnedAssessmentRelease:
        from pgx.engine.risk_errors import (AssessmentArtifactError,
                                            AssessmentReleaseError)
        self.pointer_reads += 1
        release = self.release
        if release is None:
            raise AssessmentReleaseError(
                "no release is active", code="ASSESSMENT_ACTIVE_RELEASE_MISSING",
                location="$.active_release")
        if requested_release_public_id is not None and \
                requested_release_public_id != release.public_id.to_json():
            raise AssessmentReleaseError(
                "release %s is not the active release"
                % requested_release_public_id,
                code="ASSESSMENT_RELEASE_NOT_ACTIVE", location="$.release")
        if release.status is not ReleaseStatus.ACTIVE:
            raise AssessmentReleaseError(
                "release %s is %s, not ACTIVE"
                % (release.public_id.to_json(), release.status.value),
                code="ASSESSMENT_RELEASE_NOT_ACTIVE", location="$.release")
        if sha256_digest(dict(release.manifest)) != release.manifest_hash:
            raise AssessmentArtifactError(
                "the release manifest does not hash to what the release pins",
                code="ASSESSMENT_RELEASE_MANIFEST_INVALID",
                location="$.release.manifest")
        if not self.coverage_manifests:
            raise AssessmentArtifactError(
                "no approved coverage manifest exists for this ruleset",
                code="ASSESSMENT_COVERAGE_MANIFEST_MISSING",
                location="$.coverage_manifest")
        if len(self.coverage_manifests) > 1:
            raise AssessmentArtifactError(
                "%d approved coverage manifests claim this ruleset and "
                "dataset; which one governs is a question this resolver must "
                "not answer by picking" % len(self.coverage_manifests),
                code="ASSESSMENT_COVERAGE_MANIFEST_INVALID",
                location="$.coverage_manifest")
        manifest = self.coverage_manifests[0]
        return PinnedAssessmentRelease(
            release_bundle=release,
            provenance=synthetic_provenance(
                release=release, coverage_manifest=manifest,
                frozen_ruleset=self.frozen_ruleset,
                generation=self.generation),
            frozen_ruleset=self.frozen_ruleset,
            coverage_manifest=manifest,
            drug_catalogue=self.drug_catalogue,
            entity_index=self.entity_index,
            evidence_resolver=self.evidence_resolver)


class RecordingAuditSink:
    """Collects audit records so a test can assert what was written."""

    def __init__(self) -> None:
        self.records: list = []

    def record_refusal(self, payload: Mapping[str, Any]) -> None:
        self.records.append(dict(payload))

    def record_completion(self, payload: Mapping[str, Any]) -> None:
        self.records.append(dict(payload))

    @property
    def actions(self) -> Tuple[str, ...]:
        return tuple(record.get("action", "") for record in self.records)


def frozen_ruleset_with_levels(destination: str, levels):
    """A frozen ruleset whose member rules carry chosen attention levels.

    WP-11's own fixture always builds ``MEDIUM`` rules, which is enough to
    prove a level is carried through but not enough to prove the *aggregation*
    picks the right one. This mirrors that fixture's chain exactly - draft,
    curate, validate by a different actor, assemble, validate, freeze - and
    varies only the governed outcome, so what it exercises is the real path
    rather than a shape resembling it.

    Returns ``(frozen_ruleset, definitions)``.
    """
    from pgx.domain.enums import RulesetStatus
    from pgx.rules.registry import FrozenRulesetRegistry
    from tests.fixtures.wp11.synthetic import (TEST_AUTHOR, TEST_BUILDER,
                                               TEST_VALIDATOR,
                                               build_rule_service,
                                               build_ruleset_service,
                                               synthetic_approval_record,
                                               synthetic_condition,
                                               synthetic_context,
                                               synthetic_inputs_factory,
                                               synthetic_rule,
                                               synthetic_ruleset)

    genes = ("GENE:TESTGENE1", "GENE:TESTGENE2", "GENE:TESTGENE3",
             "GENE:TESTGENE4", "GENE:TESTGENE5")
    rule_service, store = build_rule_service()
    definitions = []
    for index, level in enumerate(levels):
        definition = synthetic_rule(
            condition=synthetic_condition(gene=genes[index % len(genes)]),
            attention=level)
        rule_service.draft_rule(actor_id=TEST_AUTHOR, definition=definition,
                                reason="SYNTHETIC TEST ONLY")
        rule_service.mark_curated(actor_id=TEST_AUTHOR,
                                  rule_id=definition.rule_id,
                                  expected_version=0,
                                  context=synthetic_context(definition),
                                  reason="SYNTHETIC TEST ONLY")
        rule_service.validate(actor_id=TEST_VALIDATOR,
                              rule_id=definition.rule_id, expected_version=1,
                              context=synthetic_context(definition),
                              reason="SYNTHETIC TEST ONLY")
        definitions.append(definition)

    service, _store = build_ruleset_service(store=store)
    ruleset = synthetic_ruleset((), status=RulesetStatus.BUILDING)
    result = service.create(actor_id=TEST_BUILDER, ruleset=ruleset,
                            reason="SYNTHETIC TEST ONLY")
    for definition in definitions:
        result = service.add_member(
            actor_id=TEST_BUILDER, ruleset_id=ruleset.ruleset_id,
            rule_id=definition.rule_id,
            expected_version=result.ruleset.version,
            reason="SYNTHETIC TEST ONLY")
    result = service.validate(actor_id=TEST_BUILDER,
                              ruleset_id=ruleset.ruleset_id,
                              expected_version=result.ruleset.version,
                              reason="SYNTHETIC TEST ONLY")
    service.build_and_freeze(
        actor_id=TEST_BUILDER, ruleset_id=ruleset.ruleset_id,
        expected_version=result.ruleset.version, destination=destination,
        inputs_factory=synthetic_inputs_factory,
        approvals=tuple(synthetic_approval_record(definition)
                        for definition in definitions),
        reason="SYNTHETIC TEST ONLY")
    registry = FrozenRulesetRegistry(os.path.dirname(destination))
    return registry.load("PGX-RULESET-29991231-001"), tuple(definitions)
