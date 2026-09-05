# -*- coding: utf-8 -*-
"""The assessment application service (WP-14).

Orchestration only. Every capability arrives as an injected port - a
unit-of-work factory, a release-context resolver, a frozen-ruleset registry, a
coverage-manifest resolver, an evidence resolver, a claim boundary, a clock and
two id allocators - so this module decides *what happens in what order* and
never *how*. That is why it can be tested without a database and why the real
service refuses while a synthetic one runs.

The sequence, and the reason each step is where it is:

1. **Gate first.** Claim boundary, then mode, then input kind. Nothing is read
   from a repository before the product is allowed to answer at all.
2. **Canonicalise the input.** Sorted medications, semantic hash.
3. **Pin the release, reading the active pointer exactly once.** Everything
   after this point works from the frozen context. The pointer is never read
   again, so an activation that commits mid-run cannot change an answer that is
   already being calculated.
4. **Verify the context** - release status, manifest hash, dataset published,
   ruleset frozen, coverage manifest true of both - and fail closed on any
   disagreement.
5. **Calculate coverage** (WP-13), then **calculate findings and attention**
   (WP-14 engine), which may only read what coverage reported.
6. **Hash the output**, over calculated facts and pinned versions only.
7. **Persist everything atomically, or nothing.** Assessment, medications,
   axes, findings, evidence links and one audit event, in one transaction.

A refused assessment is not a completed assessment. Every refusal raises with a
stable code and writes an ``ASSESSMENT_REFUSED`` audit event carrying that code
and no case content; a success writes ``ASSESSMENT_COMPLETED``. Nothing writes
both, and nothing writes a success for a failure.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from pgx.application.assessment_models import (AssessmentInput,
                                               PinnedAssessmentRelease)
from pgx.application.assessment_snapshot import (build_input_snapshot,
                                                 verify_input_snapshot)
from pgx.application.execution_context import (ExecutionContext,
                                               audit_context_fields)
from pgx.domain.claims import DEFAULT_CLAIM_BOUNDARY, ClaimBoundary
from pgx.domain.enums import AttentionLevel, CoverageStatus, ReleaseStatus
from pgx.domain.identifiers import AssessmentId
from pgx.domain.models import Assessment, CoverageAssessment
from pgx.engine.coverage import CoverageRequest, evaluate_coverage
from pgx.engine.risk import (AssessmentComputation, CalculationRequest,
                             calculate_assessment)
from pgx.engine.risk_errors import (AssessmentArtifactError,
                                    AssessmentEngineError,
                                    AssessmentInputError,
                                    AssessmentPersistenceError,
                                    AssessmentReleaseError)

__all__ = [
    "AssessmentResult",
    "AssessmentService",
    "ReleaseContextResolver",
]


@dataclass(frozen=True, slots=True)
class AssessmentResult:
    """A completed assessment: the calculated facts plus what stored them.

    Returned only on success. A failure raises, so a caller cannot receive
    this object holding an empty or partial calculation and mistake it for an
    answer.
    """

    assessment_id: AssessmentId
    computation: AssessmentComputation
    pinned: PinnedAssessmentRelease
    input_hash: str
    output_hash: str
    persisted: bool
    created_at: _dt.datetime

    def to_json(self) -> Dict[str, Any]:
        payload = self.computation.to_json()
        payload["assessment_id"] = self.assessment_id.to_json()
        payload["persisted"] = self.persisted
        return payload


class ReleaseContextResolver:
    """Port: turn a release request into a frozen execution context.

    Separated from the service because *how* a release is found is an
    environment question - a database in production, a fixture in a test - and
    *that it is found exactly once, before calculation* is a safety question.
    This interface exists so the second can be tested without the first.

    An implementation must:

    - read the active-release pointer at most once and report the generation
      it saw;
    - refuse anything that is not ``ACTIVE`` at pin time;
    - verify the release manifest hash against the stored manifest;
    - load the exact dataset, ruleset and software records the release names;
    - load the frozen ruleset artifact through the WP-11 registry;
    - resolve exactly one approved coverage manifest for that ruleset and
      dataset, refusing zero and refusing several;
    - verify every cross-artifact identity and hash.
    """

    def resolve(self, *, requested_release_public_id: Optional[str] = None
                ) -> PinnedAssessmentRelease:  # pragma: no cover - protocol
        raise NotImplementedError


class AssessmentService:
    """Execute one assessment, or refuse with a stable code."""

    def __init__(self, *, release_resolver: ReleaseContextResolver,
                 uow_factory: Optional[Callable[[], Any]] = None,
                 claim_boundary: ClaimBoundary = DEFAULT_CLAIM_BOUNDARY,
                 clock: Optional[Callable[[], _dt.datetime]] = None,
                 assessment_id_factory: Optional[Callable[[], AssessmentId]] = None,
                 audit_sink: Optional[Any] = None) -> None:
        self._releases = release_resolver
        self._uow_factory = uow_factory
        self._boundary = claim_boundary
        self._clock = clock or (lambda: _dt.datetime.now(_dt.timezone.utc))
        self._new_id = assessment_id_factory or AssessmentId.new
        self._audit = audit_sink

    # -- the gate --------------------------------------------------------

    @property
    def claim_boundary(self) -> ClaimBoundary:
        return self._boundary

    def gate_state(self) -> Dict[str, Any]:
        """Whether this service may execute anything at all, and why not."""
        return {
            "claim_boundary_phase": self._boundary.phase.value,
            "claim_boundary_status": self._boundary.status,
            "claim_boundary_approved": self._boundary.is_approved,
            "enabled_modes": sorted(mode.value
                                    for mode in self._boundary.enabled_modes),
            "disabled_modes": sorted(mode.value
                                     for mode in self._boundary.disabled_modes),
            "may_execute": self._boundary.is_approved,
            "refusal_code": (None if self._boundary.is_approved
                             else "ASSESSMENT_CLAIM_BOUNDARY_NOT_APPROVED"),
        }

    # -- execution -------------------------------------------------------

    def dry_run(self, assessment_input: AssessmentInput) -> AssessmentComputation:
        """Calculate without persisting anything.

        The same calculation the persisting path performs, stopping before the
        transaction. Useful for verification, and deliberately unable to leave
        a record: a dry run that could write would be a second way to create an
        assessment, with its own set of checks to forget.
        """
        pinned = self._pin(assessment_input)
        return self._calculate(assessment_input, pinned)

    def execute(self, assessment_input: AssessmentInput, *,
                actor: Optional[str] = None,
                context: Optional[ExecutionContext] = None) -> AssessmentResult:
        """Calculate and persist one assessment, atomically, or refuse.

        Args:
            assessment_input: the canonical question. Everything hashed into
                ``input_hash`` comes from here and from nowhere else.
            actor: who is executing. May be omitted when ``context`` carries
                it, which is the API path; kept as its own argument because
                the CLI and every WP-14 test pass only this.
            context: the audited circumstances - role, channel and correlation
                id - established by the caller from an authenticated
                principal. Recorded beside the assessment and excluded from
                every hash: see
                :mod:`pgx.application.execution_context`.
        """
        actor = self._resolve_actor(actor, context)
        try:
            pinned = self._pin(assessment_input)
            computation = self._calculate(assessment_input, pinned)
        except AssessmentEngineError as error:
            self._audit_refusal(error, actor=actor,
                                assessment_input=assessment_input,
                                context=context)
            raise

        assessment_id = self._new_id()
        created_at = self._clock()
        assessment = self._as_domain_assessment(
            assessment_id=assessment_id, assessment_input=assessment_input,
            computation=computation, pinned=pinned, actor=actor,
            created_at=created_at)

        persisted = False
        if self._uow_factory is not None:
            self._persist(assessment=assessment, computation=computation,
                          assessment_input=assessment_input, pinned=pinned,
                          actor=actor, created_at=created_at, context=context)
            persisted = True

        return AssessmentResult(
            assessment_id=assessment_id, computation=computation,
            pinned=pinned, input_hash=assessment_input.content_hash(),
            output_hash=computation.output_hash(), persisted=persisted,
            created_at=created_at)

    # -- steps -----------------------------------------------------------

    @staticmethod
    def _resolve_actor(actor: Optional[str],
                       context: Optional[ExecutionContext]) -> str:
        """One actor for this execution, from the two places it may arrive.

        A caller may pass ``actor``, or a ``context`` carrying one, or both
        naming the same person. Both naming *different* people is refused
        rather than resolved: choosing between two claimed actors is not a
        decision an audit trail can make on anyone's behalf.
        """
        if context is not None:
            if not isinstance(context, ExecutionContext):
                raise AssessmentInputError(
                    "an execution context is an ExecutionContext",
                    code="ASSESSMENT_INPUT_INVALID", location="$.context")
            if actor is not None and actor != context.actor:
                raise AssessmentInputError(
                    "the actor argument and the execution context name "
                    "different actors",
                    code="ASSESSMENT_INPUT_INVALID", location="$.actor")
            return context.actor
        if not isinstance(actor, str) or not actor.strip():
            raise AssessmentInputError(
                "an assessment records the actor that requested it",
                code="ASSESSMENT_INPUT_INVALID", location="$.actor")
        return actor

    def _pin(self, assessment_input: AssessmentInput) -> PinnedAssessmentRelease:
        """Steps 1-4: gate, then resolve and verify the release exactly once."""
        assessment_input.require_permitted(self._boundary)
        pinned = self._releases.resolve(
            requested_release_public_id=(
                assessment_input.requested_release_public_id))
        if pinned is None:
            raise AssessmentReleaseError(
                "no release could be pinned, so there is nothing to assess "
                "against",
                code="ASSESSMENT_ACTIVE_RELEASE_MISSING", location="$.release")
        if not isinstance(pinned, PinnedAssessmentRelease):
            raise AssessmentReleaseError(
                "the release resolver returned %r rather than a pinned "
                "release context" % type(pinned).__name__,
                code="ASSESSMENT_RELEASE_NOT_ACTIVE", location="$.release")
        self._verify_pinned(pinned)
        return pinned

    @staticmethod
    def _verify_pinned(pinned: PinnedAssessmentRelease) -> None:
        """Re-check the cross-artifact agreement the resolver asserted.

        The resolver has already checked these. They are checked again here
        because the resolver is an injected port: a test double, a future
        implementation, or a refactor could weaken it, and this is the layer
        that must not execute on artifacts that disagree.
        """
        provenance = pinned.provenance
        manifest = pinned.coverage_manifest
        if manifest.ruleset_public_id != provenance.ruleset_public_id or \
                manifest.ruleset_content_hash != provenance.ruleset_content_hash:
            raise AssessmentArtifactError(
                "the coverage manifest pins ruleset %s@%s; the release pins "
                "%s@%s" % (manifest.ruleset_public_id,
                           manifest.ruleset_content_hash,
                           provenance.ruleset_public_id,
                           provenance.ruleset_content_hash),
                code="ASSESSMENT_VERSION_MISMATCH",
                location="$.coverage_manifest")
        if manifest.dataset_public_id != provenance.dataset_public_id or \
                manifest.canonical_build_content_hash != \
                provenance.canonical_build_content_hash:
            raise AssessmentArtifactError(
                "the coverage manifest and the release pin different datasets",
                code="ASSESSMENT_VERSION_MISMATCH",
                location="$.coverage_manifest")
        if manifest.evidence_build_content_hash != \
                provenance.evidence_build_content_hash:
            raise AssessmentArtifactError(
                "the coverage manifest and the release pin different evidence "
                "builds",
                code="ASSESSMENT_VERSION_MISMATCH",
                location="$.coverage_manifest")
        if manifest.content_hash() != provenance.coverage_manifest_hash:
            raise AssessmentArtifactError(
                "the coverage manifest hashes to %s; the pinned context "
                "records %s" % (manifest.content_hash(),
                                provenance.coverage_manifest_hash),
                code="ASSESSMENT_COVERAGE_MANIFEST_INVALID",
                location="$.coverage_manifest")
        ruleset_manifest = pinned.frozen_ruleset.manifest
        if ruleset_manifest.public_id.to_json() != provenance.ruleset_public_id \
                or pinned.frozen_ruleset.ruleset_content_hash != \
                provenance.ruleset_content_hash:
            raise AssessmentArtifactError(
                "the loaded frozen ruleset is not the one the release pins",
                code="ASSESSMENT_RULESET_ARTIFACT_INVALID",
                location="$.frozen_ruleset")

    def _calculate(self, assessment_input: AssessmentInput,
                   pinned: PinnedAssessmentRelease) -> AssessmentComputation:
        """Steps 5-6: coverage first, then findings, then the output hash."""
        coverage = evaluate_coverage(CoverageRequest(
            profile=assessment_input.profile,
            medications=assessment_input.medications,
            manifest=pinned.coverage_manifest,
            frozen_ruleset=pinned.frozen_ruleset,
            drug_catalogue=pinned.drug_catalogue,
            evidence_resolver=pinned.evidence_resolver,
            conflicts=()))
        computation = calculate_assessment(CalculationRequest(
            profile=assessment_input.profile,
            coverage=coverage,
            frozen_ruleset=pinned.frozen_ruleset,
            provenance=pinned.provenance,
            evidence_resolver=pinned.evidence_resolver))
        # The engine hashes the profile; the service hashes the whole question,
        # which additionally pins the mode, the input kind and the medication
        # list. The stored input hash is the second.
        return AssessmentComputation(
            input_hash=assessment_input.content_hash(),
            overall_coverage=computation.overall_coverage,
            overall_attention=computation.overall_attention,
            overall_coverage_reason_codes=(
                computation.overall_coverage_reason_codes),
            medications=computation.medications,
            coverage_result=computation.coverage_result,
            provenance=computation.provenance,
            warnings=computation.warnings)

    @staticmethod
    def _as_domain_assessment(*, assessment_id: AssessmentId,
                              assessment_input: AssessmentInput,
                              computation: AssessmentComputation,
                              pinned: PinnedAssessmentRelease, actor: str,
                              created_at: _dt.datetime) -> Assessment:
        """The WP-02 aggregate, populated from the WP-14 calculation.

        **Identities are resolved, never minted.** Every drug and gene named
        here already exists in the pinned canonical dataset and already has an
        identity; this reads that identity out of the pinned entity index. A
        ``DrugId.new()`` in this path would give two runs of the same question
        two different subjects, which makes the stored assessment unjoinable
        to the entity it is about and makes "did this change" unanswerable.

        The single permitted absence is a medication the pinned dataset does
        not contain: it has no identity, WP-13 already said so with
        ``DRUG_NOT_IN_CANONICAL_DATASET``, and the entry records the canonical
        key without an identity rather than inventing one. An unresolvable key
        that coverage did *not* report as absent is a disagreement between the
        catalogue and the index, and fails closed.
        """
        from pgx.domain.enums import CoverageReasonCode
        from pgx.domain.identifiers import ComputableRuleId, EvidenceRecordId
        from pgx.domain.models import AssessmentFinding

        index = pinned.require_entity_index()

        coverage = []
        for item in computation.medications:
            key = item.drug_canonical_key
            if index.has_drug(key):
                drug_id = index.drug_id(key)
            elif CoverageReasonCode.DRUG_NOT_IN_CANONICAL_DATASET in \
                    item.coverage_reason_codes:
                drug_id = None
            else:
                raise AssessmentArtifactError(
                    "medication %r has no identity in the pinned canonical "
                    "dataset, but coverage did not report it as absent from "
                    "that dataset. The catalogue and the entity index "
                    "disagree, and neither may be trusted for this run." % key,
                    code="ASSESSMENT_ENTITY_NOT_RESOLVABLE",
                    location="$.medications", detail={"canonical_key": key})
            coverage.append(CoverageAssessment(
                drug_id=drug_id,
                status=item.coverage_status,
                reason_codes=item.coverage_reason_codes,
                drug_canonical_key=key))
        coverage = tuple(coverage)

        findings = []
        for finding in computation.findings:
            findings.append(AssessmentFinding(
                gene_id=index.gene_id(finding.gene_canonical_key),
                drug_id=index.drug_id(finding.drug_canonical_key),
                phenotype=finding.phenotype,
                attention_level=finding.attention_level,
                rationale_reference=finding.rationale_reference,
                effect_code=finding.effect_code,
                explanation_code=finding.explanation_code,
                rule_id=ComputableRuleId.parse(finding.rule_id),
                rule_version=finding.rule_version,
                evidence_record_ids=tuple(
                    EvidenceRecordId.parse(reference)
                    for reference in finding.evidence_references)))
        return Assessment(
            id=assessment_id,
            release_bundle_id=pinned.release_bundle.id,
            mode=assessment_input.mode,
            input_hash=assessment_input.content_hash(),
            created_at=created_at,
            findings=tuple(findings),
            coverage=coverage,
            output_hash=computation.output_hash(),
            case_id=assessment_input.case_id,
            release_provenance=pinned.provenance,
            input_kind=assessment_input.input_kind,
            overall_coverage=computation.overall_coverage,
            calculated_overall_attention=computation.overall_attention,
            actor=actor,
            completed_at=created_at)

    def _persist(self, *, assessment: Assessment,
                 computation: AssessmentComputation,
                 assessment_input: AssessmentInput,
                 pinned: PinnedAssessmentRelease, actor: str,
                 created_at: _dt.datetime,
                 context: Optional[ExecutionContext] = None) -> None:
        """Step 7: one transaction, or nothing.

        SAFETY-INV-007 is checked here before the transaction opens, so an
        assessment missing release metadata never reaches a database that
        would have to reject it.
        """
        assessment.require_complete_release_metadata()
        try:
            with self._uow_factory() as uow:
                uow.assessments.add(
                    assessment=assessment, computation=computation,
                    input_snapshot=self._input_snapshot(assessment,
                                                        assessment_input),
                    output_snapshot=computation.to_json(), actor=actor,
                    created_at=created_at, context=context)
                uow.commit()
        except AssessmentEngineError:
            raise
        except Exception as error:  # noqa: BLE001 - re-raised with a code
            raise AssessmentPersistenceError(
                "the calculated assessment could not be stored, so nothing "
                "was stored: %s" % error,
                code="ASSESSMENT_PERSISTENCE_REFUSED",
                location="$.persistence") from error

    @staticmethod
    def _input_snapshot(assessment: Assessment,
                        assessment_input: AssessmentInput) -> Dict[str, Any]:
        """The complete canonical input document, verified before it is sent.

        Built from the input rather than from the calculation, and checked
        against the hash the assessment row will carry, so a snapshot that
        does not describe this assessment never reaches persistence.
        """
        snapshot = build_input_snapshot(assessment_input)
        verify_input_snapshot(snapshot, input_hash=assessment.input_hash)
        return snapshot

    def _audit_refusal(self, error: AssessmentEngineError, *, actor: str,
                       assessment_input: Optional[AssessmentInput],
                       context: Optional[ExecutionContext] = None) -> None:
        """Record that an assessment was refused, and why.

        Carries the stable code and the mode, and nothing else. A refusal audit
        holding a phenotype profile, a case narrative or a medication list
        would put case content into a log that outlives the request and is read
        by people who have no reason to see it.
        """
        if self._audit is None:
            return
        try:
            payload: Dict[str, Any] = {
                "action": "ASSESSMENT_REFUSED",
                "actor": actor,
                "code": error.code,
                "location": error.location,
                "mode": (assessment_input.mode.value
                         if assessment_input is not None else None),
            }
            payload.update(audit_context_fields(context))
            self._audit.record_refusal(payload)
        except Exception:  # noqa: BLE001 - auditing must not mask the refusal
            pass
