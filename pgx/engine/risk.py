# -*- coding: utf-8 -*-
"""The deterministic assessment engine (WP-14).

One question: *given a coverage result that says which axes could be
evaluated, what did the governed rules actually say about them?*

Not: what could be evaluated - that is WP-13, and this module consumes its
answer rather than recomputing it. Not: how to say any of it to a person -
that is WP-15, and there is no prose here.

**Coverage is the gate, and it is not re-derived.** A finding may be emitted
only where ``AxisCoverage.status`` is ``FULL``. This module never asks whether
a rule exists for an axis WP-13 called uncovered, because "a rule exists" and
"this ruleset is declared able to evaluate this axis" are different questions
and answering the second with the first is what coverage was built to stop.

**A FULL axis that does not verify is corruption, not absence.** WP-13 said
the axis was covered by a specific validated rule with a specific content
hash. If that rule is missing, changed, unapproved, or does not match, then
coverage and the ruleset disagree, and neither can be trusted. The assessment
fails closed. Quietly downgrading the axis to "not assessed" would hide a
disagreement between two governed artifacts behind an answer that looks
routine.

**Nothing here reads a clock, a network, a CSV or the active release
pointer.** The engine is a pure function of the request it is handed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from pgx.domain.enums import (AttentionLevel, CoverageReasonCode,
                              CoverageStatus)
from pgx.domain.hashing import sha256_digest
from pgx.engine.coverage_models import AxisCoverage, CoverageResult
from pgx.engine.phenotype import match_observation
from pgx.engine.risk_errors import (AssessmentArtifactError,
                                    AssessmentEngineError,
                                    AssessmentExecutionError,
                                    AssessmentInputError)
from pgx.engine.risk_models import (ATTENTION_AGGREGATION_TABLE,
                                    ATTENTION_PRECEDENCE, CalculatedFinding,
                                    MedicationAssessment, aggregate_attention,
                                    attention_table)

__all__ = [
    "ASSESSMENT_ENGINE_CONTRACT_VERSION",
    "COMPUTATION_ENVELOPE_KEYS",
    "POINTER_AUDIT_FIELDS",
    "AssessmentComputation",
    "CalculationRequest",
    "calculate_assessment",
    "embedded_coverage_result",
    "engine_contract",
    "hashed_projection",
    "evaluate_axis_finding",
]

ASSESSMENT_ENGINE_CONTRACT_VERSION = "pgx-assessment-engine/2"
COMPUTATION_SCHEMA_VERSION = "pgx-assessment-computation/2"

#: Keys a stored computation document carries *around* the hashed projection.
#: ``to_json`` writes them, ``semantic_content`` does not, and anything that
#: recomputes an output hash from a stored document has to remove exactly
#: these and no others. Published as data so the CLI, the read model and the
#: reporting layer strip the same list rather than three drifting copies of it.
COMPUTATION_ENVELOPE_KEYS: Tuple[str, ...] = (
    "output_hash", "note", "pointer_audit", "assessment_id", "persisted")

#: Provenance fields that are **recorded** on every assessment and **excluded**
#: from the hashed projection of its facts.
#:
#: ``active_pointer_generation`` says where in the WP-03 pointer's history a
#: release was pinned. That is audit metadata about *this execution*, not a
#: fact about the case: the same question, against the same release bundle
#: with the same content hashes, produces the same answer whether it was
#: pinned at generation 3 or at generation 40. Including it in the output hash
#: made an unrelated activation elsewhere in the system look like a change to
#: the assessment, which destroys the one comparison the hash exists to
#: support - *same input, same release, same answer?* The generation is still
#: written to the assessment row, still returned in ``to_json``, and still
#: reportable; it simply does not enter the hash.
POINTER_AUDIT_FIELDS: Tuple[str, ...] = ("active_pointer_generation",)


@dataclass(frozen=True, slots=True)
class CalculationRequest:
    """Everything the engine reads, as one immutable value.

    Assembled by the application service, which owns pinning. The engine
    reaches for nothing: no registry, no repository, no filesystem, no clock,
    and above all no active-release pointer. What it is given is what it
    evaluates, which is what makes two runs of the same request identical.
    """

    profile: Any
    coverage: CoverageResult
    frozen_ruleset: Any
    provenance: Any
    evidence_resolver: Any = None

    def __post_init__(self) -> None:
        if not isinstance(self.coverage, CoverageResult):
            raise AssessmentInputError(
                "coverage must be a WP-13 CoverageResult; this engine does not "
                "compute coverage and cannot accept a substitute for it",
                code="ASSESSMENT_INPUT_INVALID", location="$.coverage")
        if self.frozen_ruleset is None:
            raise AssessmentInputError(
                "a calculation names the frozen ruleset it executes",
                code="ASSESSMENT_RULESET_ARTIFACT_INVALID",
                location="$.frozen_ruleset")
        if self.provenance is None:
            raise AssessmentInputError(
                "a calculation names every version it ran against "
                "(SAFETY-INV-007)",
                code="ASSESSMENT_VERSION_MISMATCH", location="$.provenance")


def _member_rules(frozen_ruleset) -> Mapping[str, Any]:
    return {definition.rule_id.to_json(): definition
            for definition in frozen_ruleset.rules()}


def _approval_records(frozen_ruleset) -> Mapping[str, Any]:
    return {record.rule_id.to_json(): record
            for record in frozen_ruleset.approvals}


def evaluate_axis_finding(*, axis: AxisCoverage, request: CalculationRequest
                          ) -> CalculatedFinding:
    """The finding for one FULL axis, or a refusal.

    Called only for axes WP-13 reported ``FULL``. Every check below re-verifies
    something coverage already checked, on purpose: coverage was computed
    against a manifest, this runs against the artifact itself, and the point of
    doing it twice is to catch the case where the two disagree.

    Raises:
        AssessmentExecutionError: coverage and the ruleset disagree about this
            axis. Never downgraded to an absence.
    """
    if axis.status is not CoverageStatus.FULL:
        raise AssessmentExecutionError(
            "only a FULL axis may produce a finding; %s was asked to"
            % axis.status.value,
            code="ASSESSMENT_RULE_NOT_EXECUTABLE",
            location="$.axes[%s/%s]" % axis.axis_key)

    references = tuple(axis.rule_references)
    if len(references) != 1:
        raise AssessmentExecutionError(
            "axis %s names %d supporting rules. One axis is covered by exactly "
            "one validated rule; WP-11 refuses a ruleset in which two cover the "
            "same axis, and this engine will not pick between them."
            % (axis.axis_key, len(references)),
            code="ASSESSMENT_CONFLICT_UNRESOLVED",
            location="$.axes[%s/%s].rule_references" % axis.axis_key,
            detail={"axis": list(axis.axis_key)})

    reference = references[0]
    rule_id = reference.get("rule_id")
    members = _member_rules(request.frozen_ruleset)
    definition = members.get(rule_id)
    if definition is None:
        raise AssessmentExecutionError(
            "coverage reports axis %s FULL on rule %s, which is not a member "
            "of the frozen ruleset. Coverage and the artifact disagree; "
            "neither may be trusted for this run."
            % (axis.axis_key, rule_id),
            code="ASSESSMENT_RULE_NOT_EXECUTABLE",
            location="$.axes[%s/%s]" % axis.axis_key,
            detail={"rule_id": rule_id})

    if definition.content_hash() != reference.get("rule_content_hash"):
        raise AssessmentExecutionError(
            "rule %s hashes to %s; coverage recorded %s. The ruleset changed "
            "underneath the coverage manifest."
            % (rule_id, definition.content_hash(),
               reference.get("rule_content_hash")),
            code="ASSESSMENT_RULE_HASH_MISMATCH",
            location="$.axes[%s/%s]" % axis.axis_key)

    approval = _approval_records(request.frozen_ruleset).get(rule_id)
    if approval is None or approval.rule_content_hash != definition.content_hash():
        raise AssessmentExecutionError(
            "rule %s carries no approval record evidencing that this exact "
            "content was validated. Membership is not validation "
            "(SAFETY-INV-003)." % rule_id,
            code="ASSESSMENT_RULE_NOT_EXECUTABLE",
            location="$.axes[%s/%s]" % axis.axis_key)

    condition = definition.condition
    if condition.drug_canonical_key != axis.drug_canonical_key or \
            condition.gene_canonical_key != axis.gene_canonical_key:
        raise AssessmentExecutionError(
            "rule %s is about %s/%s, not axis %s"
            % (rule_id, condition.drug_canonical_key,
               condition.gene_canonical_key, axis.axis_key),
            code="ASSESSMENT_RULE_NOT_EXECUTABLE",
            location="$.axes[%s/%s]" % axis.axis_key)

    observation = request.profile.observation_for(axis.gene_canonical_key)
    if observation is None:
        raise AssessmentExecutionError(
            "coverage reports axis %s FULL, but the profile has no observation "
            "for that gene" % (axis.axis_key,),
            code="ASSESSMENT_RULE_DID_NOT_MATCH",
            location="$.axes[%s/%s]" % axis.axis_key)

    # WP-12 decides equality. A second matcher here would be a second place
    # for RAPID to start meaning ULTRARAPID (SAFETY-INV-004).
    decision = match_observation(observation, condition)
    if not decision.matched:
        raise AssessmentExecutionError(
            "coverage reports axis %s FULL, but rule %s does not match the "
            "observed phenotype. A rule is executed because it was declared to "
            "cover the axis and then matched - never because it merely matched, "
            "and never because coverage said so alone."
            % (axis.axis_key, rule_id),
            code="ASSESSMENT_RULE_DID_NOT_MATCH",
            location="$.axes[%s/%s]" % axis.axis_key)

    evidence = tuple(axis.evidence_references)
    if not evidence:
        raise AssessmentExecutionError(
            "axis %s cites no evidence (SAFETY-INV-006)" % (axis.axis_key,),
            code="ASSESSMENT_EVIDENCE_MISSING",
            location="$.axes[%s/%s]" % axis.axis_key)
    if request.evidence_resolver is not None:
        unresolved = sorted(item for item in evidence
                            if not request.evidence_resolver(item))
        if unresolved:
            raise AssessmentExecutionError(
                "axis %s cites evidence that does not resolve in the pinned "
                "build: %s" % (axis.axis_key, ", ".join(unresolved)),
                code="ASSESSMENT_EVIDENCE_MISSING",
                location="$.axes[%s/%s]" % axis.axis_key,
                detail={"unresolved": unresolved})

    outcome = definition.outcome
    provenance = definition.provenance
    return CalculatedFinding(
        drug_canonical_key=axis.drug_canonical_key,
        gene_canonical_key=axis.gene_canonical_key,
        phenotype=observation.phenotype,
        attention_level=outcome.attention_level,
        rule_id=rule_id,
        rule_family_id=definition.family_id.to_json(),
        rule_version=definition.rule_version,
        rule_content_hash=definition.content_hash(),
        rationale_reference=outcome.rationale_reference,
        evidence_references=evidence,
        curation_revision_id=provenance.curation_revision_id,
        curation_revision_hash=provenance.curation_revision_hash,
        ruleset_public_id=request.provenance.ruleset_public_id,
        ruleset_content_hash=request.provenance.ruleset_content_hash,
        dataset_public_id=request.provenance.dataset_public_id,
        canonical_build_content_hash=(
            request.provenance.canonical_build_content_hash),
        coverage_manifest_hash=request.provenance.coverage_manifest_hash,
        # The governed outcome carries no scientific codes. Left absent
        # rather than filled with something plausible.
        effect_code=None,
        explanation_code=None)


@dataclass(frozen=True, slots=True)
class AssessmentComputation:
    """The calculated facts of one assessment, and nothing else.

    Carries no assessment UUID, no actor, no timestamp and no duration - not
    because they are unimportant, but because they are not *facts about the
    case*, and a hash that included them would make two identical assessments
    look different. Those live on the persisted row beside this, where they
    can be read without being mistaken for part of the answer.
    """

    input_hash: str
    overall_coverage: CoverageStatus
    overall_attention: AttentionLevel
    overall_coverage_reason_codes: Tuple[CoverageReasonCode, ...]
    medications: Tuple[MedicationAssessment, ...]
    coverage_result: CoverageResult
    provenance: Any
    warnings: Tuple[str, ...] = ()
    computation_schema_version: str = COMPUTATION_SCHEMA_VERSION
    note: str = (
        "Calculated structured facts. Not a report, not a recommendation, and "
        "not a statement about any medicine. Attention says what the governed "
        "rules said about the axes that could be evaluated; coverage says how "
        "much could be evaluated. Neither summarises the other, and neither "
        "may be displayed without the other.")

    def __post_init__(self) -> None:
        if not self.medications:
            raise AssessmentInputError(
                "an assessment covers at least one requested medication",
                code="ASSESSMENT_INPUT_INVALID", location="$.medications")
        object.__setattr__(
            self, "medications",
            tuple(sorted(self.medications,
                         key=lambda item: (item.drug_canonical_key,
                                           item.requested_value))))
        if self.overall_attention is AttentionLevel.NO_ACTIVE_ATTENTION and \
                self.overall_coverage is not CoverageStatus.FULL:
            raise AssessmentInputError(
                "NO_ACTIVE_ATTENTION requires FULL overall coverage "
                "(SAFETY-INV-001)",
                code="ASSESSMENT_INPUT_INVALID", location="$.overall_attention")

    @property
    def findings(self) -> Tuple[CalculatedFinding, ...]:
        """Every finding, in one deterministic order."""
        found = [finding for medication in self.medications
                 for finding in medication.findings]
        return tuple(sorted(found, key=lambda item: item.sort_key))

    def semantic_release_provenance(self) -> Dict[str, Any]:
        """The pinned versions, minus the pointer audit metadata.

        Every identity and every content hash the run executed against stays
        in: change the ruleset, the dataset, the release manifest or the
        coverage manifest and the output hash changes, which is what makes a
        version claim verifiable. What leaves is
        :data:`POINTER_AUDIT_FIELDS` - see that constant for why.
        """
        document = dict(self.provenance.to_json())
        for name in POINTER_AUDIT_FIELDS:
            document.pop(name, None)
        return document

    def pointer_audit_metadata(self) -> Dict[str, Any]:
        """The recorded-but-unhashed provenance fields, kept reachable.

        Excluded from the hash is not the same as discarded. This is where a
        reader gets them, and it is why the exclusion does not cost anything
        an auditor needs.
        """
        document = self.provenance.to_json()
        return {name: document.get(name) for name in POINTER_AUDIT_FIELDS}

    def semantic_content(self) -> Dict[str, Any]:
        """The calculated facts, canonically ordered.

        This is what ``output_hash`` covers. Everything excluded from it is
        excluded deliberately: assessment id, actor, clock, insertion order,
        file paths, process identity, durations, any rendered text, and the
        active pointer generation (:data:`POINTER_AUDIT_FIELDS`).

        **The coverage result is embedded whole, not summarised.** A hash of
        it proves two results are the same result; it cannot tell a reader
        *which* axes were covered, which phenotype was observed on each, which
        reason codes explain the rest, or which conflicts were preserved. A
        report is required to show all of that, and a report that had to
        recompute it would be deriving governed facts from an input it was
        given - which is the one thing the reporting layer must never do. The
        hash is kept beside the document so the embedded copy can be checked
        against it rather than trusted.
        """
        return {
            "computation_schema_version": self.computation_schema_version,
            "assessment_engine_contract_version":
                ASSESSMENT_ENGINE_CONTRACT_VERSION,
            "input_hash": self.input_hash,
            "overall_coverage": self.overall_coverage.value,
            "overall_attention": self.overall_attention.value,
            "overall_coverage_reason_codes":
                [code.value for code in self.overall_coverage_reason_codes],
            "medication_count": len(self.medications),
            "medications": [item.to_json() for item in self.medications],
            "finding_count": len(self.findings),
            "coverage_result_hash": self.coverage_result.content_hash(),
            "coverage_result": self.coverage_result.to_json(),
            "release_provenance": self.semantic_release_provenance(),
            "warnings": list(self.warnings),
        }

    def output_hash(self) -> str:
        return sha256_digest(self.semantic_content())

    def to_json(self) -> Dict[str, Any]:
        payload = self.semantic_content()
        payload["note"] = self.note
        payload["pointer_audit"] = self.pointer_audit_metadata()
        payload["output_hash"] = self.output_hash()
        return payload


def calculate_assessment(request: CalculationRequest) -> AssessmentComputation:
    """Calculate one assessment from a coverage result and a frozen ruleset.

    Deterministic and total over its input: given the same request it returns
    the same object, and it either returns a complete result or raises. There
    is no partial success, because a partly-verified assessment is one whose
    trustworthy half cannot be told from its other half.
    """
    if not isinstance(request, CalculationRequest):
        raise AssessmentInputError(
            "calculate_assessment takes a CalculationRequest",
            code="ASSESSMENT_INPUT_INVALID", location="$.request")

    medications = []
    for medication_coverage in request.coverage.medications:
        reference = medication_coverage.medication
        findings = []
        conflicted = 0
        for axis in medication_coverage.axes:
            if axis.status is CoverageStatus.SOURCE_CONFLICT:
                # Preserved, never resolved. The conflict carries no governed
                # outcome, so there is nothing here to calculate from - and
                # picking a side, an average, or the first rule would each be
                # an adjudication this engine has no standing to make
                # (SAFETY-INV-008).
                conflicted += 1
                continue
            if axis.status is not CoverageStatus.FULL:
                continue
            findings.append(evaluate_axis_finding(axis=axis, request=request))

        attention = aggregate_attention(
            [finding.attention_level for finding in findings],
            coverage=medication_coverage.status)
        medications.append(MedicationAssessment(
            drug_canonical_key=(reference.drug_canonical_key
                                or reference.requested_value),
            requested_value=reference.requested_value,
            attention_level=attention,
            coverage_status=medication_coverage.status,
            coverage_reason_codes=medication_coverage.reason_codes,
            findings=tuple(findings),
            axis_count=len(medication_coverage.axes),
            conflicted_axis_count=conflicted))

    calculated = [item.attention_level for item in medications
                  if item.attention_level is not AttentionLevel.NOT_ASSESSED]
    overall = aggregate_attention(calculated,
                                  coverage=request.coverage.status)

    return AssessmentComputation(
        input_hash=request.coverage.profile_content_hash,
        overall_coverage=request.coverage.status,
        overall_attention=overall,
        overall_coverage_reason_codes=request.coverage.reason_codes,
        medications=tuple(medications),
        coverage_result=request.coverage,
        provenance=request.provenance)


def hashed_projection(document: Mapping[str, Any]) -> Dict[str, Any]:
    """The part of a stored computation document that ``output_hash`` covers.

    Removes :data:`COMPUTATION_ENVELOPE_KEYS` and nothing else. A caller that
    guessed the list would eventually guess wrong in the safe-looking
    direction - dropping a fact and still matching - so the list is published
    rather than repeated.
    """
    if not isinstance(document, Mapping):
        raise AssessmentInputError(
            "a computation document is an object",
            code="ASSESSMENT_INPUT_INVALID", location="$")
    return {key: value for key, value in document.items()
            if key not in COMPUTATION_ENVELOPE_KEYS}


def embedded_coverage_result(document: Mapping[str, Any]) -> Dict[str, Any]:
    """The coverage result carried in a hashed computation document, verified.

    Reads the embedded copy back out and checks it against the
    ``coverage_result_hash`` recorded beside it. The two are written together
    and so always agree at write time; they can stop agreeing afterwards,
    which is exactly when a reader must find out rather than render.

    Raises:
        AssessmentArtifactError: the document carries no coverage result, or
            the embedded result does not hash to what the document records.
    """
    if not isinstance(document, Mapping):
        raise AssessmentInputError(
            "a computation document is an object",
            code="ASSESSMENT_INPUT_INVALID", location="$")
    embedded = document.get("coverage_result")
    recorded = document.get("coverage_result_hash")
    if not isinstance(embedded, Mapping):
        raise AssessmentArtifactError(
            "the stored computation carries no coverage result. A coverage "
            "hash alone cannot say which axes were covered, and a reader that "
            "recomputed the answer would be deriving a governed fact.",
            code="ASSESSMENT_COVERAGE_MANIFEST_INVALID",
            location="$.coverage_result")
    carried = embedded.get("content_hash")
    if carried != recorded:
        raise AssessmentArtifactError(
            "the embedded coverage result hashes to %s; the computation "
            "records %s" % (carried, recorded),
            code="ASSESSMENT_COVERAGE_MANIFEST_INVALID",
            location="$.coverage_result_hash")
    recomputed = sha256_digest({key: value for key, value in embedded.items()
                                if key != "content_hash"})
    if recomputed != recorded:
        raise AssessmentArtifactError(
            "the embedded coverage result recomputes to %s; the computation "
            "records %s. The stored result changed after it was written."
            % (recomputed, recorded),
            code="ASSESSMENT_COVERAGE_MANIFEST_INVALID",
            location="$.coverage_result")
    return dict(embedded)


def engine_contract() -> Dict[str, Any]:
    """The engine's published rules, as one document."""
    return {
        "assessment_engine_contract_version":
            ASSESSMENT_ENGINE_CONTRACT_VERSION,
        "attention": attention_table(),
        "finding_gate": {
            "rule": "a finding may be emitted only for an axis WP-13 reported "
                    "FULL",
            "checks": [
                "the axis names exactly one supporting rule",
                "that rule is a member of the pinned frozen ruleset",
                "its content hash equals what coverage recorded",
                "the frozen artifact carries an approval record for that "
                "exact content (SAFETY-INV-003)",
                "its condition names this exact drug and gene",
                "WP-12's exact matcher reports MATCH (SAFETY-INV-004)",
                "its evidence is non-empty and resolves (SAFETY-INV-006)",
            ],
            "on_disagreement": "the assessment fails closed. A FULL axis whose "
                               "rule does not verify is corruption, not "
                               "absence, and is never downgraded to "
                               "NOT_ASSESSED",
        },
        "conflict": {
            "rule": "a SOURCE_CONFLICT axis emits no finding and is never "
                    "resolved",
            "note": "no lower level, no higher level, no average, no rule "
                    "order. An independent covered axis keeps its finding; if "
                    "none exists the medication is NOT_ASSESSED "
                    "(SAFETY-INV-008)",
        },
        "excluded_from_output_hash": [
            "assessment_id", "created_at", "completed_at", "actor",
            "database insertion order", "local paths", "wall-clock time",
            "process id", "runtime duration", "UI labels", "report prose",
            "active_pointer_generation",
        ],
        "recorded_but_not_hashed": {
            "fields": list(POINTER_AUDIT_FIELDS),
            "rule": "the pointer generation is audit metadata about this "
                    "execution, not a fact about the case. The same question "
                    "against the same release bundle and the same content "
                    "hashes gives the same output hash whatever the pointer "
                    "had reached, and the generation is still written to the "
                    "assessment row",
        },
        "note": (
            "This engine calculates structured facts. It renders no prose, "
            "recommends no medication, ranks nothing, calculates no dose, and "
            "makes no statement about whether any medicine is appropriate for "
            "anybody."),
    }
