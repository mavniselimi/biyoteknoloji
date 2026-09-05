# -*- coding: utf-8 -*-
"""Synthetic API request documents and a synthetic service provider.

**Nothing here is a real case.** Every identifier begins with ``TEST-`` or
names an entity from the WP-13 synthetic world; every gene is ``TESTGENE``,
every drug is ``testdrug``, and the dates are in 2099. None of it describes a
person, and none of it may be presented as a real API record: the assessment
these fixtures produce is implementation evidence that the wiring works, not
a pharmacogenomic assessment of anyone.

The provider here is a real :class:`~apps.api.dependencies.ServiceProvider`
composed over the WP-14 synthetic world - the same service, the same engine,
the same governed artifacts - so a test that goes through it exercises the
real path and not a mock of it.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

from apps.api.readiness import ReadinessProbes
from apps.api.security import (AuthMode, Principal, PrincipalResolver, Role,
                               StaticTokenAuthentication)
from pgx.engine.phenotype_normalization import INPUT_CONTRACT_VERSION
from tests.fixtures.wp13.synthetic import DRUG_1, DRUG_2, GENE_1, GENE_2

#: Marker carried by every artifact these fixtures produce, so a document that
#: escapes a test can be recognised for what it is.
SYNTHETIC_MARKER = "TEST-SYNTHETIC-WP16"

TEST_CASE_ID = "TEST-CASE-WP16-1"
TEST_PROFILE_ID = "TEST-PROFILE-WP16-1"
TEST_REQUEST_ID = "11111111-1111-4111-8111-111111111111"

#: A development token, not a credential. Sixteen characters because
#: StaticTokenAuthentication refuses anything shorter, and prefixed so that
#: finding this string anywhere outside a test is obviously wrong.
TEST_DEMO_TOKEN = "TEST-TOKEN-demo-user-0001"
TEST_REVIEWER_TOKEN = "TEST-TOKEN-expert-reviewer-0001"
TEST_ADMIN_TOKEN = "TEST-TOKEN-admin-0001"

DEMO_PRINCIPAL = Principal(actor="TEST-demo-user-1", role=Role.DEMO_USER,
                           authenticated_by="static-token/1")
REVIEWER_PRINCIPAL = Principal(actor="TEST-reviewer-1",
                               role=Role.EXPERT_REVIEWER,
                               authenticated_by="static-token/1")
ADMIN_PRINCIPAL = Principal(actor="TEST-admin-1", role=Role.ADMIN,
                            authenticated_by="static-token/1")

TEST_PRINCIPALS: Mapping[str, Principal] = {
    TEST_DEMO_TOKEN: DEMO_PRINCIPAL,
    TEST_REVIEWER_TOKEN: REVIEWER_PRINCIPAL,
    TEST_ADMIN_TOKEN: ADMIN_PRINCIPAL,
}


def create_request(*, medications: Sequence[str] = (DRUG_1,),
                   phenotypes: Optional[Mapping[str, str]] = None,
                   mode: str = "DEMO",
                   input_kind: str = "SYNTHETIC_PHENOTYPE_PROFILE",
                   case_id: Optional[str] = TEST_CASE_ID,
                   requested_release_public_id: Optional[str] = None
                   ) -> Dict[str, Any]:
    """One synthetic ``AssessmentCreateRequest`` document."""
    values = phenotypes if phenotypes is not None else {GENE_1: "POOR",
                                                        GENE_2: "POOR"}
    document: Dict[str, Any] = {
        "mode": mode,
        "input_kind": input_kind,
        "profile": {
            "input_contract_version": INPUT_CONTRACT_VERSION,
            "profile_id": TEST_PROFILE_ID,
            "observations": [{"gene": gene, "value": value}
                             for gene, value in sorted(values.items())],
        },
        "medications": list(medications),
    }
    if case_id is not None:
        document["case_id"] = case_id
    if requested_release_public_id is not None:
        document["requested_release_public_id"] = requested_release_public_id
    return document


def evidence_detail(record_uuid: str = "aaaaaaaa-0000-4000-8000-000000000001"
                    ) -> Dict[str, Any]:
    """One synthetic evidence detail row, shaped like WP-08's repository.

    Deliberately carries a text fragment and a filesystem path. Neither may
    appear in the projection, and a fixture that omitted them could not prove
    that.
    """
    return {
        "record_uuid": record_uuid,
        "natural_key": "TEST-SOURCE/record/1",
        "record_type": "GUIDELINE_ANNOTATION",
        "provider_source_key": "TEST-PROVIDER",
        "origin_source_key": "TEST-ORIGIN",
        "origin_status": "APPROVED",
        "version_status": "PUBLISHED",
        "version_value": "2099.01",
        "source_payload_hash": "sha256:" + "b" * 64,
        "content_hash": "sha256:" + "c" * 64,
        "production_eligible": True,
        "text_fragments": [{"text": "TEST-SYNTHETIC unreviewed source prose"}],
        "publications": [{"identifier_type": "PMID", "identifier": "99999999"}],
        "genes": [{"canonical_key": GENE_1, "source_label": "TestGene1"}],
        "drugs": [{"canonical_key": DRUG_1, "source_label": "TestDrug Alpha"}],
        # The real WP-08 locator keys, including the two this projection must
        # never emit: ``artifact_path`` is a path inside a build directory,
        # and ``requested_container`` is the source's own request vocabulary.
        "locators": [{"snapshot_manifest_hash": "sha256:" + "5" * 64,
                      "artifact_id": "TEST-ART-1",
                      "artifact_sha256": "sha256:" + "d" * 64,
                      "pointer": "/items/0",
                      "dataset_public_id": "PGX-DATA-20990101-001",
                      "requested_container": "TestContainer",
                      "artifact_path": "responses/should-not-leak.json",
                      "csv_row_number": None}],
        "issues": [],
        # The real mapping shape. ``rationale`` is a paragraph of curation
        # prose and must not appear in the projection.
        "record_type_mapping": {
            "record_type": "GUIDELINE_ANNOTATION",
            "status": "CONFIRMED",
            "map_version": "pgx-evidence-record-types/1",
            "production_eligible": True,
            "source_object_class": "Guideline Annotation",
            "requested_container": "TestContainer",
            "rationale": "TEST-SYNTHETIC curation prose that must not leave",
        },
    }


#: Every evidence record the synthetic ruleset cites. Both of them: the WP-11
#: rule fixture references ``...001`` and ``...002``, so an assessment built on
#: that ruleset renders links to both. Seeding only the first made every page
#: correct and the second link a 404 - which nothing noticed until a runtime
#: test followed the links a page actually rendered. A fixture that answers for
#: some of what its own rules cite cannot prove that the interface's links
#: resolve.
SYNTHETIC_EVIDENCE_IDS = ("aaaaaaaa-0000-4000-8000-000000000001",
                          "aaaaaaaa-0000-4000-8000-000000000002")


class SyntheticEvidenceRepository:
    """The evidence detail surface the API uses, over the synthetic records."""

    def __init__(self, records: Optional[Mapping[str, Any]] = None) -> None:
        self._records = dict(records or {
            record_uuid: evidence_detail(record_uuid)
            for record_uuid in SYNTHETIC_EVIDENCE_IDS})

    def get(self, record_uuid: str) -> Optional[Dict[str, Any]]:
        record = self._records.get(str(record_uuid))
        return None if record is None else dict(record)

    def evidence_build_key(self) -> Dict[str, str]:
        return {"evidence_build_key": "TEST-EVIDENCE-BUILD/synthetic",
                "evidence_build_content_hash": "sha256:" + "2" * 64}


def synthetic_provider(world: Any, *, settings: Any,
                       principals: Optional[PrincipalResolver] = None,
                       with_evidence: bool = True,
                       with_reader: bool = True,
                       with_service: bool = True,
                       with_release: bool = True) -> Any:
    """A ``ServiceProvider`` over the WP-14 synthetic world.

    Each capability can be withheld, because "this deployment does not have
    one" is a state the API has to answer correctly and is the state this
    repository is actually in.
    """
    # Imported from the framework-free module so this fixture composes a
    # provider in an environment with no FastAPI - which is this one.
    from apps.api.provider import ServiceProvider

    return ServiceProvider(
        settings=settings,
        claim_boundary=world.boundary,
        principals=principals or StaticTokenAuthentication(TEST_PRINCIPALS),
        assessment_service=(lambda: world.service) if with_service else None,
        assessment_reader=(lambda: world.store) if with_reader else None,
        release_resolver=(lambda: world.resolver.resolve())
        if with_release else None,
        evidence_repository=(lambda: SyntheticEvidenceRepository())
        if with_evidence else None,
        readiness_probes=ReadinessProbes(),
    )
