# -*- coding: utf-8 -*-
"""Builders for the WP-09 tests.

Small explicit factories, so a test asserting that a rationale is rejected
shows the rationale in the test body. Every default here is *valid*, which is
what lets a test change one thing and attribute the failure to that thing.
"""

from __future__ import annotations

import datetime as _dt
import io
import os
from typing import Any, Mapping, Optional, Sequence

from pgx.curation.models import (RATIONALE_PARTS, ConflictAnalysis,
                                 CurationQuestion, CurationRecordDraft,
                                 EvidenceSelection, InsufficiencyStatement,
                                 Rationale, ReviewSignature,
                                 SourceReportedValues)
from pgx.curation.vocabulary import (Applicability, ConclusionState,
                                     ConflictState, CurationRole,
                                     EffectDimension, EvidenceRelationship,
                                     ExclusionReason, InterpretationStatus)
from pgx.domain.enums import Phenotype

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

EVIDENCE_BUILD = os.path.join(REPO_ROOT, "data", "evidence",
                              "PGX-DATA-20260830-900")
PROPOSALS = os.path.join(REPO_ROOT, "data", "migration", "wp08",
                         "draft-curation-proposals.ndjson")
EXERCISE_DIR = os.path.join(REPO_ROOT, "data", "curation", "protocol-v1",
                            "exercises")
PROTOCOL_JSON = os.path.join(REPO_ROOT, "config", "curation",
                             "protocol-v1.json")
FIELD_DICTIONARY_JSON = os.path.join(REPO_ROOT, "config", "curation",
                                     "field-dictionary-v1.json")

#: Distinguishes "the caller did not mention this" from "the caller asked for
#: none". Without it, record(rationale_obj=None) silently got the default.
UNSPECIFIED = object()

NOW = _dt.datetime(2026, 9, 2, 12, 0, tzinfo=_dt.timezone.utc)
PROTOCOL_VERSION = "pgx-curation-protocol/1"

AUTHOR = "Dr Ayse Yilmaz"
REVIEWER = "Dr Mehmet Kaya"


def source_text(relative: str) -> str:
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


def signature(person: str = AUTHOR,
              role: CurationRole = CurationRole.SCIENTIFIC_CURATOR,
              rationale: str = "Selected and assessed the cited evidence "
                               "against the stated question.") -> ReviewSignature:
    return ReviewSignature(person=person, role=role, at=NOW,
                           rationale=rationale)


def question(effect: EffectDimension = EffectDimension.ACTIVATION,
             phenotypes: Sequence[Phenotype] = (Phenotype.POOR,),
             gene: str = "GENE:CYP2C19",
             drug: str = "DRUG:clopidogrel") -> CurationQuestion:
    return CurationQuestion(
        question_id="Q-CYP2C19-CLOPIDOGREL-ACTIVATION",
        gene_canonical_key=gene, drug_canonical_key=drug,
        effect_dimension=effect,
        question_text="Does the stated CYP2C19 phenotype scope alter "
                      "clopidogrel activation, per the cited evidence?",
        phenotype_scope=tuple(phenotypes))


def selection(uuid_value: str = "uuid-1",
              relationship: EvidenceRelationship = EvidenceRelationship.SUPPORTS,
              exclusion_reason: Optional[ExclusionReason] = None,
              rationale: str = "A guideline annotation naming this gene and "
                               "drug, with a stated origin and known version.",
              version_status: str = "KNOWN") -> EvidenceSelection:
    return EvidenceSelection(
        evidence_record_uuid=uuid_value,
        natural_key="PGX-DATA-20260830-900|clinpgx.api|GUIDELINE_ANNOTATION|"
                    "PA166104948|0",
        relationship=relationship, rationale=rationale,
        source_version_status=version_status,
        provider_source_key="clinpgx.api",
        origin_source_key="cpic.publications",
        origin_status="STATED_BY_SOURCE", trace_verified=True,
        exclusion_reason=exclusion_reason)


def rationale_parts(**overrides: str) -> Mapping[str, str]:
    """Eleven substantive parts, each overridable by name."""
    base = {
        "curation_question":
            "Whether CYP2C19 poor metaboliser status alters clopidogrel "
            "activation, scoped to that phenotype alone.",
        "selected_evidence":
            "One CPIC guideline annotation with a stated origin and a known "
            "source version, cited for its own description of the pathway.",
        "excluded_evidence":
            "No record was excluded; every reviewed record bears on the "
            "question as stated.",
        "source_to_conclusion":
            "The annotation describes reduced formation of the active "
            "metabolite in carriers of no-function alleles, which is the "
            "activation dimension this question asks about, and it names the "
            "phenotype scope explicitly rather than by inference.",
        "phenotype_normalization":
            "The source names poor metabolisers directly, so the scope maps "
            "to POOR without inference and no other member is implied.",
        "effect_normalization":
            "Reduced formation of an active metabolite is the ACTIVATION "
            "dimension; no exposure or clearance claim is made here.",
        "significance_explanation":
            "The source reports its own significance flag; that flag is not "
            "this conclusion, and the conclusion rests on the described "
            "pathway rather than on the flag's value.",
        "applicability_statement":
            "Applies to the adult population the cited annotation describes; "
            "no paediatric or pregnancy scope was reviewed.",
        "conflict_assessment":
            "No cited record contradicts another on the activation "
            "dimension; no source disagreement was identified in this set.",
        "uncertainty_and_limitations":
            "One annotation supports this; the breadth of the underlying "
            "study population was not independently assessed here.",
        "missing_data_statement":
            "No allele-level functional assay evidence was reviewed, so "
            "allele-specific scope remains unaddressed.",
    }
    base.update(overrides)
    return base


def rationale(author: str = AUTHOR, reviewer: Optional[str] = REVIEWER,
              **overrides: str) -> Rationale:
    return Rationale(
        parts=rationale_parts(**overrides),
        protocol_version=PROTOCOL_VERSION,
        authored_by=signature(author),
        reviewed_by=(signature(
            reviewer, CurationRole.INDEPENDENT_SCIENTIFIC_REVIEWER,
            "Independently re-read the cited evidence and the reasoning.")
            if reviewer else None))


def no_conflict() -> ConflictAnalysis:
    return ConflictAnalysis(state=ConflictState.NONE_IDENTIFIED)


def unresolved_conflict(uuids: Sequence[str] = ("uuid-1", "uuid-2"),
                        material: bool = True) -> ConflictAnalysis:
    return ConflictAnalysis(
        state=ConflictState.UNRESOLVED,
        conflicting_evidence_uuids=tuple(uuids),
        disputed_field="direction of the activation effect",
        source_versions={"cpic.publications": "0", "dpwg.knmp": "1"},
        material=material,
        curator_analysis="The two annotations describe the activation "
                         "direction differently and neither supersedes the "
                         "other; a named adjudicator is required.",
        adjudication_required=True)


def insufficiency(**overrides: Any) -> InsufficiencyStatement:
    base = dict(
        missing_information="No evidence addresses the intermediate "
                            "metaboliser scope for this drug.",
        evidence_reviewed_uuids=("uuid-1",),
        why_no_stronger_conclusion="The single cited record speaks only to "
                                   "poor metabolisers, so nothing supports a "
                                   "statement about the asked scope.",
        unresolved_scope="Intermediate and rapid metaboliser scopes remain "
                         "unaddressed by any reviewed record.",
        additional_evidence_required=True)
    base.update(overrides)
    return InsufficiencyStatement(**base)


def record(status: InterpretationStatus = InterpretationStatus.CURATED,
           conclusion_state: ConclusionState = ConclusionState.SUPPORTED,
           evidence: Optional[Sequence[EvidenceSelection]] = None,
           conflict: Optional[ConflictAnalysis] = None,
           rationale_obj: Any = UNSPECIFIED,
           insufficiency_obj: Optional[InsufficiencyStatement] = None,
           conclusion_text: Optional[str] = None,
           phenotypes: Sequence[Phenotype] = (Phenotype.POOR,),
           source_reported: Sequence[SourceReportedValues] = (),
           **overrides: Any) -> CurationRecordDraft:
    """A complete, valid record. Every part is overridable."""
    if conclusion_text is None:
        conclusion_text = (
            "The cited guideline annotation describes reduced formation of "
            "the active metabolite in CYP2C19 poor metabolisers.")
    payload = dict(
        record_id="CUR-0001",
        question=question(),
        status=status,
        conclusion_state=conclusion_state,
        conclusion_text=conclusion_text,
        applicability=Applicability.APPLICABLE,
        effect_dimension=EffectDimension.ACTIVATION,
        evidence=tuple(evidence if evidence is not None else (selection(),)),
        conflict=conflict if conflict is not None else no_conflict(),
        protocol_version=PROTOCOL_VERSION,
        normalized_phenotypes=tuple(phenotypes),
        source_reported=tuple(source_reported),
        rationale=(rationale_obj if rationale_obj is not UNSPECIFIED
                   else (rationale() if status is InterpretationStatus.CURATED
                         else None)),
        insufficiency=insufficiency_obj)
    payload.update(overrides)
    return CurationRecordDraft(**payload)
