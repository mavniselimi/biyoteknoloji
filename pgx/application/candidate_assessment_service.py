# -*- coding: utf-8 -*-
"""The application service that executes a candidate release (WP-C09).

**Why this is not** :class:`pgx.application.assessment_service.AssessmentService`.
That service executes a governed release: it pins a ``FrozenRuleset``, and
:func:`pgx.engine.risk.evaluate_axis_finding` verifies a WP-10 approval record
for every rule it runs. A candidate rule has no approval record, by design, so
it cannot go through that path and must not be made to look as though it can.

**Why it is not a second engine.** It builds the same ``AssessmentInput``,
checks it against the same ``ClaimBoundary``, resolves through a
``ReleaseContextResolver`` implementation, and gets its answer from
:func:`pgx.engine.candidate_evaluation.evaluate_candidate`, which uses this
project's own ``aggregate_attention``. There is one attention rule in the
repository and both paths call it.

**Which boundary it uses.** ``P0_CANDIDATE_CLAIM_BOUNDARY``, passed explicitly.
It is not the default anywhere, so a caller cannot end up on the candidate path
by omission - and it reports ``is_approved`` as ``False`` wherever it is
displayed, because it is.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any, Dict, Optional

from pgx.application.assessment_models import AssessmentInput
from pgx.application.candidate_release import (CandidateReleaseError,
                                               CandidateReleaseResolver,
                                               PinnedCandidateRelease)
from pgx.domain.authority import CandidateAuthorityState
from pgx.domain.candidate_claims import (P0_CANDIDATE_CLAIM_BOUNDARY,
                                         execution_basis_of)
from pgx.domain.claims import (CANONICAL_CLINICAL_WARNING, ClaimBoundary,
                               OperationMode)
from pgx.domain.hashing import sha256_digest
from pgx.engine.candidate_evaluation import (CandidateEvaluation,
                                             evaluate_candidate)

__all__ = [
    "CANDIDATE_ASSESSMENT_VERSION",
    "candidate_request_to_input",
    "CandidateAssessmentResult",
    "CandidateAssessmentService",
]

CANDIDATE_ASSESSMENT_VERSION = "pgx-candidate-assessment/1"


@dataclass(frozen=True, slots=True)
class CandidateAssessmentResult:
    evaluation: CandidateEvaluation
    input_hash: str
    output_hash: str
    release_public_id: str
    manifest_hash: str
    warning: str
    authority_state: str
    review_state: str
    claim_boundary_status: str
    claim_boundary_is_approved: bool
    computed_at: _dt.datetime
    schema_version: str = CANDIDATE_ASSESSMENT_VERSION

    def to_json(self) -> Dict[str, Any]:
        return {
            "authority_state": self.authority_state,
            "claim_boundary_is_approved": self.claim_boundary_is_approved,
            "claim_boundary_status": self.claim_boundary_status,
            "computed_at": self.computed_at.isoformat().replace("+00:00", "Z"),
            "evaluation": self.evaluation.to_json(),
            "input_hash": self.input_hash,
            "manifest_hash": self.manifest_hash,
            "output_hash": self.output_hash,
            "release_public_id": self.release_public_id,
            "review_state": self.review_state,
            "schema_version": self.schema_version,
            "warning": self.warning,
        }


class CandidateAssessmentService:
    """Execute one assessment against the active candidate release."""

    def __init__(self, *, release_resolver=None,
                 claim_boundary: ClaimBoundary = P0_CANDIDATE_CLAIM_BOUNDARY,
                 repo_root: str = ".",
                 clock: Optional[Any] = None) -> None:
        self._releases = release_resolver or CandidateReleaseResolver(repo_root)
        self._boundary = claim_boundary
        self._clock = clock or (lambda: _dt.datetime.now(_dt.timezone.utc))

    @property
    def claim_boundary(self) -> ClaimBoundary:
        return self._boundary

    def gate_state(self) -> Dict[str, Any]:
        """What this service will and will not do, without running anything."""
        try:
            pinned = self._releases.resolve()
            release: Optional[str] = pinned.release_public_id
            available = True
            detail = ""
        except CandidateReleaseError as exc:
            release, available, detail = None, False, str(exc)
        return {
            "active_candidate_release": release,
            "claim_boundary_execution_basis": execution_basis_of(
                self._boundary),
            "claim_boundary_is_approved": self._boundary.is_approved,
            "claim_boundary_status": self._boundary.status,
            "detail": detail,
            "enabled_modes": sorted(m.value
                                    for m in self._boundary.enabled_modes),
            "release_available": available,
            "review_state":
                CandidateAuthorityState.PENDING_EXTERNAL_EXPERT_REVIEW.value,
        }

    def execute(self, assessment_input: AssessmentInput,
                *, language: str = "tr") -> CandidateAssessmentResult:
        """Pin the release, evaluate, and return. Refuses before it computes."""
        assessment_input.require_permitted(self._boundary)

        pinned: PinnedCandidateRelease = self._releases.resolve(
            requested_release_public_id=(
                assessment_input.requested_release_public_id))
        if not pinned.permits_mode(assessment_input.mode.value):
            raise CandidateReleaseError(
                "release %s permits %s; %s was requested"
                % (pinned.release_public_id,
                   ", ".join(pinned.manifest["permitted_modes"]),
                   assessment_input.mode.value),
                code="CANDIDATE_RELEASE_MODE_NOT_PERMITTED")

        evaluation = evaluate_candidate(
            ruleset=pinned.ruleset,
            profile=assessment_input.profile,
            medications=assessment_input.medications,
            care_setting=assessment_input.care_setting,
            dataset_public_id=pinned.dataset_public_id,
            release_public_id=pinned.release_public_id)

        payload = evaluation.to_json()
        return CandidateAssessmentResult(
            evaluation=evaluation,
            input_hash=assessment_input.content_hash(),
            output_hash=sha256_digest(payload),
            release_public_id=pinned.release_public_id,
            manifest_hash=pinned.manifest["manifest_hash"],
            warning=CANONICAL_CLINICAL_WARNING[language],
            authority_state=pinned.manifest["authority_state"],
            review_state=pinned.manifest["review_state"],
            claim_boundary_status=self._boundary.status,
            claim_boundary_is_approved=self._boundary.is_approved,
            computed_at=self._clock())


def _observations_to_mapping(observations):
    """The request's list of observations as the normaliser's gene map.

    A list on the wire and a mapping in the application, and the collapse
    refuses a repeated gene rather than letting the later entry win: a caller
    that sent POOR and then NORMAL for one gene would otherwise receive a
    confident assessment of whichever happened to be last.

    Written here rather than imported from ``apps.api.adapters.request``,
    where the same rule lives for the governed wire contract. The application
    layer must not know a transport exists - ``tests/unit/api/
    test_wp16_boundaries.py`` asserts it - and the two are twelve lines each
    rather than one shared dependency pointing the wrong way.
    """
    from pgx.application.assessment_models import AssessmentInputError

    mapping = {}
    for index, entry in enumerate(observations):
        gene = entry["gene"]
        if gene in mapping:
            raise AssessmentInputError(
                "two observations name the same gene",
                code="ASSESSMENT_INPUT_INVALID",
                location="$.profile.observations[%d].gene" % index)
        mapping[gene] = entry["value"]
    return mapping


def candidate_request_to_input(document):
    """One request document to one canonical candidate input.

    The whole conversion in one application-layer function, because the caller
    that needs it most is the server-rendered interface - and
    ``tests/unit/web/test_wp17_boundaries.py`` forbids that layer from
    importing an engine. It is right to: a page that could normalise a
    phenotype profile is a page that could disagree with the service about
    what the profile means.
    """
    from pgx.application.candidate_documents import candidate_assessment_input
    from pgx.domain.claims import PermittedInputKind
    from pgx.engine.phenotype_normalization import normalize_profile

    profile_document = document["profile"]
    profile = normalize_profile(
        _observations_to_mapping(profile_document["observations"]),
        profile_id=profile_document.get("profile_id"),
        contract_version=profile_document.get("input_contract_version")
        or "pgx-phenotype-input/1")
    return candidate_assessment_input(
        document, profile=profile,
        mode=OperationMode(document["mode"]),
        input_kind=PermittedInputKind(document["input_kind"]))
