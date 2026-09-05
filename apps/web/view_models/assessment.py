"""The assessment screen's model.

Built from one validated WP-16 response and checked against it before it can
be rendered. The construction is deliberately mechanical: for each medication
in the order the response gave, pair the status, keep the axes in the order the
response gave, keep the findings in the order the response gave, and attach a
label to each governed code.

Three things this module refuses to do, each of which would be an easy line of
code:

**It does not sort medications.** Not by attention, not by finding count, not
by coverage. The engine's order is canonical and alphabetical; any other order
is a ranking, and a ranking of medicines is what SAFETY-INV-005 forbids.

**It does not summarise.** There is no "worst" medication, no overall score,
no count of high-attention findings presented as a headline. A reader who
wants to know how many findings there are can count the rows.

**It does not fill an absence.** ``effect_code`` and ``explanation_code`` are
``None`` in the governed outcome, and they arrive here as ``None`` and are
rendered as an explicit absence marker. A blank cell would read as "nothing to
say"; the marker reads as "no governed code exists", which is what is true.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from apps.web.labels import (attention_label, coverage_label,
                             coverage_reason_label, observation_state_label,
                             ui)
from apps.web.routes import web_route
from apps.web.view_models.base import StatusPair, build_status_pair, display
from apps.web.view_models.preservation import require_preserved

__all__ = [
    "AssessmentAxisView",
    "AssessmentFindingView",
    "AssessmentMedicationView",
    "AssessmentObservationView",
    "AssessmentPageModel",
    "build_assessment_page",
]

#: What is shown where a governed code is absent. A marker, not a blank: a
#: blank cell reads as "nothing to report", and the truth is "no code exists".
ABSENT_MARKER = "—"


@dataclass(frozen=True, slots=True)
class AssessmentAxisView:
    """One gene-medication axis, evaluated or not."""

    gene: str
    drug: str
    coverage_code: str
    coverage_label: str
    reason_codes: Tuple[str, ...]
    reason_labels: Tuple[str, ...]
    observed_phenotype: Optional[str]
    observation_state: str
    observation_state_label: str
    declaration_id: Optional[str]
    evidence_references: Tuple[str, ...]
    evidence_urls: Tuple[str, ...]
    conflict_references: Tuple[str, ...]

    @property
    def is_evaluated(self) -> bool:
        return self.coverage_code == "FULL"

    @property
    def is_conflicted(self) -> bool:
        return self.coverage_code == "SOURCE_CONFLICT"

    def fact_projection(self) -> Dict[str, Any]:
        return {
            "gene": self.gene,
            "drug": self.drug,
            "coverage": self.coverage_code,
            "reason_codes": list(self.reason_codes),
            "observed_phenotype": self.observed_phenotype,
            "observation_state": self.observation_state,
            "declaration_id": self.declaration_id,
            "evidence_references": list(self.evidence_references),
            "conflict_references": list(self.conflict_references),
        }


@dataclass(frozen=True, slots=True)
class AssessmentFindingView:
    """One finding, with the whole trace that makes it citable."""

    gene: str
    drug: str
    phenotype: str
    attention_code: str
    attention_label: str
    rule_id: str
    rule_family_id: str
    rule_version: Any
    rule_content_hash: str
    rationale_reference: str
    curation_revision_id: str
    curation_revision_hash: str
    effect_code: Optional[str]
    explanation_code: Optional[str]
    evidence_references: Tuple[str, ...]
    evidence_urls: Tuple[str, ...]

    @property
    def effect_display(self) -> str:
        return self.effect_code if self.effect_code else ABSENT_MARKER

    @property
    def explanation_display(self) -> str:
        return (self.explanation_code if self.explanation_code
                else ABSENT_MARKER)

    def fact_projection(self) -> Dict[str, Any]:
        return {
            "gene": self.gene,
            "drug": self.drug,
            "phenotype": self.phenotype,
            "attention": self.attention_code,
            "rule_id": self.rule_id,
            "rule_family_id": self.rule_family_id,
            "rule_version": self.rule_version,
            "rule_content_hash": self.rule_content_hash,
            "rationale_reference": self.rationale_reference,
            "curation_revision_id": self.curation_revision_id,
            "curation_revision_hash": self.curation_revision_hash,
            "effect_code": self.effect_code,
            "explanation_code": self.explanation_code,
            "evidence_references": list(self.evidence_references),
        }


@dataclass(frozen=True, slots=True)
class AssessmentMedicationView:
    """One requested medication and everything the engine said about it."""

    drug: str
    requested_value: str
    status: StatusPair
    axis_count: Any
    conflicted_axis_count: Any
    axes: Tuple[AssessmentAxisView, ...]
    findings: Tuple[AssessmentFindingView, ...]
    no_findings_note: str

    @property
    def evaluated_axes(self) -> Tuple[AssessmentAxisView, ...]:
        """The axes a rule could be executed on. A filter, not a judgement."""
        return tuple(axis for axis in self.axes if axis.is_evaluated)

    @property
    def unevaluated_axes(self) -> Tuple[AssessmentAxisView, ...]:
        """The rest - shown, and shown with their reasons.

        Displayed as prominently as the evaluated ones. An interface that
        listed only what it could evaluate would present a partial answer as a
        complete one, which is the failure SAFETY-INV-001 describes.
        """
        return tuple(axis for axis in self.axes if not axis.is_evaluated)

    def fact_projection(self) -> Dict[str, Any]:
        return {
            "drug": self.drug,
            "requested_value": self.requested_value,
            "status": {"attention": self.status.attention_code,
                       "coverage": self.status.coverage_code,
                       "reason_codes": list(self.status.reason_codes)},
            "axis_count": self.axis_count,
            "conflicted_axis_count": self.conflicted_axis_count,
            "axes": [axis.fact_projection() for axis in self.axes],
            "findings": [item.fact_projection() for item in self.findings],
        }


@dataclass(frozen=True, slots=True)
class AssessmentObservationView:
    """One recorded observation. Carries no raw supplied token.

    The WP-16 response does not include the caller's original text and this
    model does not reconstruct it. A value that could not be interpreted is
    shown by its governed state and reason code, which is what a reader needs
    and what cannot be an injection vector.
    """

    gene: str
    state_code: str
    state_label: str
    phenotype: Optional[str]
    reason_code: Optional[str]

    @property
    def phenotype_display(self) -> str:
        return self.phenotype if self.phenotype else ABSENT_MARKER

    @property
    def reason_display(self) -> str:
        return self.reason_code if self.reason_code else ABSENT_MARKER

    def fact_projection(self) -> Dict[str, Any]:
        return {
            "gene": self.gene,
            "status": self.state_code,
            "phenotype": self.phenotype,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True, slots=True)
class AssessmentPageModel:
    """The whole assessment screen."""

    assessment_id: str
    mode: str
    input_kind: str
    case_id: Optional[str]
    created_at: str
    input_hash: str
    output_hash: str
    coverage_result_hash: str
    persisted: bool
    status: StatusPair
    medications: Tuple[AssessmentMedicationView, ...]
    observations: Tuple[AssessmentObservationView, ...]
    release: Mapping[str, Any]
    release_rows: Tuple[Tuple[str, str], ...]
    warnings: Tuple[str, ...]
    clinical_warning: str
    self_url: str

    def fact_projection(self) -> Dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "mode": self.mode,
            "input_kind": self.input_kind,
            "case_id": self.case_id,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "coverage_result_hash": self.coverage_result_hash,
            "persisted": self.persisted,
            "status": {"attention": self.status.attention_code,
                       "coverage": self.status.coverage_code,
                       "reason_codes": list(self.status.reason_codes)},
            "medications": [item.fact_projection()
                            for item in self.medications],
            "observations": [item.fact_projection()
                             for item in self.observations],
            "release": dict(self.release),
            "warnings": list(self.warnings),
        }


def _evidence_urls(references: Sequence[str]) -> Tuple[str, ...]:
    """Internal links to each cited record, built from the route table.

    A link per reference, in the reference's order. Built rather than
    concatenated so a page cannot link outside the application, and so the
    evidence path changing changes here only.
    """
    route = web_route("web.evidence")
    return tuple(route.url(evidence_id=reference) for reference in references)


def _axis_view(axis: Mapping[str, Any], locale: str) -> AssessmentAxisView:
    codes = tuple(str(code) for code in axis.get("coverage_reason_codes")
                  or ())
    references = tuple(str(item)
                       for item in axis.get("evidence_references") or ())
    state = str(axis.get("observation_state") or "")
    return AssessmentAxisView(
        gene=display(axis.get("gene"), location="$.axes.gene"),
        drug=display(axis.get("drug"), location="$.axes.drug"),
        coverage_code=str(axis.get("coverage") or ""),
        coverage_label=coverage_label(str(axis.get("coverage") or ""), locale),
        reason_codes=codes,
        reason_labels=tuple(coverage_reason_label(code, locale)
                            for code in codes),
        observed_phenotype=axis.get("observed_phenotype"),
        observation_state=state,
        observation_state_label=observation_state_label(state, locale)
        if state else "",
        declaration_id=axis.get("declaration_id"),
        evidence_references=references,
        evidence_urls=_evidence_urls(references),
        conflict_references=tuple(
            str(item) for item in axis.get("conflict_references") or ()))


def _finding_view(finding: Mapping[str, Any],
                  locale: str) -> AssessmentFindingView:
    references = tuple(str(item)
                       for item in finding.get("evidence_references") or ())
    return AssessmentFindingView(
        gene=display(finding.get("gene"), location="$.findings.gene"),
        drug=display(finding.get("drug"), location="$.findings.drug"),
        phenotype=str(finding.get("phenotype") or ""),
        attention_code=str(finding.get("attention") or ""),
        attention_label=attention_label(str(finding.get("attention") or ""),
                                        locale),
        rule_id=display(finding.get("rule_id"), location="$.findings.rule_id"),
        rule_family_id=display(finding.get("rule_family_id"),
                               location="$.findings.rule_family_id"),
        rule_version=finding.get("rule_version"),
        rule_content_hash=display(finding.get("rule_content_hash"),
                                  location="$.findings.rule_content_hash"),
        rationale_reference=display(finding.get("rationale_reference"),
                                    location="$.findings.rationale_reference"),
        curation_revision_id=display(
            finding.get("curation_revision_id"),
            location="$.findings.curation_revision_id"),
        curation_revision_hash=display(
            finding.get("curation_revision_hash"),
            location="$.findings.curation_revision_hash"),
        effect_code=finding.get("effect_code"),
        explanation_code=finding.get("explanation_code"),
        evidence_references=references,
        evidence_urls=_evidence_urls(references))


def _release_rows(release: Mapping[str, Any],
                  locale: str) -> Tuple[Tuple[str, str], ...]:
    """The provenance table, in the order the contract declares it.

    The order comes from the ``ReleaseProvenanceResponse`` model - the
    published contract - rather than from the adapter that happens to build
    the document. An adapter's field list is an implementation detail, and a
    view model reading one would break the rule that the interface consumes
    the contract and nothing behind it.

    Every field, including the ones that are empty: a provenance table that
    omitted a blank row would let a missing dataset hash look like a field
    nobody thought to show.
    """
    from apps.api.contracts.spec import model

    rows = []
    for name in model("ReleaseProvenanceResponse").field_names:
        value = release.get(name)
        rows.append((name, display(value, location="$.release.%s" % name)))
    return tuple(rows)


def build_assessment_page(document: Mapping[str, Any], *,
                          locale: str = "tr") -> AssessmentPageModel:
    """Build the assessment screen, and prove it lost nothing.

    Raises:
        FactPreservationError: the built model does not carry every protected
            fact the response carried. Raised before the model is returned, so
            an incomplete page cannot be rendered.
    """
    medications = []
    for medication in document.get("medications") or ():
        medications.append(AssessmentMedicationView(
            drug=display(medication.get("drug"),
                         location="$.medications.drug"),
            requested_value=display(medication.get("requested_value"),
                                    location="$.medications.requested_value"),
            status=build_status_pair(medication.get("status") or {}, locale),
            axis_count=medication.get("axis_count"),
            conflicted_axis_count=medication.get("conflicted_axis_count"),
            axes=tuple(_axis_view(axis, locale)
                       for axis in medication.get("axes") or ()),
            findings=tuple(_finding_view(item, locale)
                           for item in medication.get("findings") or ()),
            no_findings_note=ui("assessment.no_findings", locale)))

    observations = []
    for observation in document.get("observations") or ():
        state = str(observation.get("status") or "")
        observations.append(AssessmentObservationView(
            gene=display(observation.get("gene"),
                         location="$.observations.gene"),
            state_code=state,
            state_label=observation_state_label(state, locale) if state else "",
            phenotype=observation.get("phenotype"),
            reason_code=observation.get("reason_code")))

    release = dict(document.get("release") or {})
    model = AssessmentPageModel(
        assessment_id=display(document.get("assessment_id"),
                              location="$.assessment_id", allow_none=False),
        mode=str(document.get("mode") or ""),
        input_kind=str(document.get("input_kind") or ""),
        case_id=document.get("case_id"),
        created_at=display(document.get("created_at"),
                           location="$.created_at"),
        input_hash=display(document.get("input_hash"),
                           location="$.input_hash", allow_none=False),
        output_hash=display(document.get("output_hash"),
                            location="$.output_hash", allow_none=False),
        coverage_result_hash=display(document.get("coverage_result_hash"),
                                     location="$.coverage_result_hash"),
        persisted=bool(document.get("persisted")),
        status=build_status_pair(document.get("status") or {}, locale),
        medications=tuple(medications),
        observations=tuple(observations),
        release=release,
        release_rows=_release_rows(release, locale),
        warnings=tuple(str(item) for item in document.get("warnings") or ()),
        clinical_warning=str(document.get("clinical_warning") or ""),
        self_url=web_route("web.assessment").url(
            assessment_id=str(document.get("assessment_id") or "")))

    require_preserved(document, model)
    return model
