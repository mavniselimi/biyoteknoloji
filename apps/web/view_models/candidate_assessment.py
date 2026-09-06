# -*- coding: utf-8 -*-
"""The candidate assessment screen's model (Wave 4B).

Frozen, built from one already-validated document, and adding labels and
nothing else - the same rules the governed assessment model follows, for the
same reason: a template that could compute would be a second place where the
answer is decided.

**Three things this model keeps separate that a careless one would merge.**

*Attention is not coverage.* An axis can be fully covered and carry no
attention, or carry attention on a partial coverage. One field each, always
both rendered.

*A refusal is not an attention level.* ``NO_ACTIVE_ATTENTION`` means the rules
ran and found nothing to raise. ``CARE_SETTING_NOT_DECLARED`` means they never
ran. Presenting the second as the first is the single most dangerous thing
this screen could do, so refusal codes are their own list, rendered whether or
not any attention exists, and :attr:`CandidateAssessmentModel.refused` is true
whenever one is present.

*Provisional is not approved.* The release identity, the authority state, the
review state and the claim-boundary status are all on the page, unabbreviated,
because a screenshot of this page will outlive the conversation that explains
it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

from apps.web.labels import field_label, ui
from apps.web.view_models.assessment import ABSENT_MARKER
from apps.web.view_models.base import display

__all__ = [
    "CandidateAssessmentModel",
    "CandidateAxisRow",
    "CandidateMedicationBlock",
    "build_candidate_assessment_page",
]


@dataclass(frozen=True, slots=True)
class CandidateAxisRow:
    """One gene x drug axis, with the lineage that produced it."""

    axis_key: str
    genes: str
    coverage_status: str
    attention_level: str
    is_joint: bool
    interpretation_key: str
    matched_rule_key: str
    rule_content_hash: str
    capture_record_ids: Tuple[str, ...]
    citations: Tuple[str, ...]
    reason_codes: Tuple[str, ...]
    detail: str

    @property
    def refused(self) -> bool:
        return bool(self.reason_codes)


@dataclass(frozen=True, slots=True)
class CandidateMedicationBlock:
    drug: str
    care_setting: str
    coverage_status: str
    attention_level: str
    reason_codes: Tuple[str, ...]
    axes: Tuple[CandidateAxisRow, ...]

    @property
    def refused(self) -> bool:
        return bool(self.reason_codes)


@dataclass(frozen=True, slots=True)
class CandidateAssessmentModel:
    """Everything the candidate assessment page may display."""

    attention_level: str
    attention_label: str
    coverage_status: str
    refusal_codes: Tuple[str, ...]
    medications: Tuple[CandidateMedicationBlock, ...]

    release_public_id: str
    manifest_hash: str
    dataset_public_id: str
    ruleset_key: str
    ruleset_content_hash: str

    authority_state: str
    review_state: str
    claim_boundary_status: str
    claim_boundary_is_approved: bool
    governed_registry_note: str

    input_hash: str
    output_hash: str
    computed_at: str
    case_id: str
    warning: str
    demo_notice: str
    refusal_notice: str

    @property
    def refused(self) -> bool:
        """Whether anything at all was refused.

        Read by the template to render the refusal block. Deliberately not
        derived from ``attention_level``: an assessment can be refused on one
        axis and raise attention on another, and a page that showed only one
        of those would be describing a different assessment.
        """
        return bool(self.refusal_codes)


def _axis(document: Mapping[str, Any]) -> CandidateAxisRow:
    return CandidateAxisRow(
        axis_key=display(document.get("axis_key"), location="$.axis_key"),
        genes=", ".join(str(gene) for gene in document.get("gene_keys") or ())
        or ABSENT_MARKER,
        coverage_status=display(document.get("status"), location="$.status"),
        attention_level=display(document.get("attention_level"),
                                location="$.attention_level"),
        is_joint=bool(document.get("is_joint")),
        interpretation_key=display(document.get("interpretation_key"),
                                   location="$.interpretation_key"),
        matched_rule_key=display(document.get("matched_rule_key"),
                                 location="$.matched_rule_key"),
        rule_content_hash=display(document.get("rule_content_hash"),
                                  location="$.rule_content_hash"),
        capture_record_ids=tuple(
            str(item) for item in document.get("capture_record_ids") or ()),
        citations=tuple(str(item) for item in document.get("citations") or ()),
        reason_codes=tuple(str(item)
                           for item in document.get("reason_codes") or ()),
        detail=display(document.get("detail"), location="$.detail"))


def _medication(document: Mapping[str, Any]) -> CandidateMedicationBlock:
    return CandidateMedicationBlock(
        drug=display(document.get("drug_canonical_key"),
                     location="$.drug_canonical_key"),
        care_setting=display(document.get("care_setting"),
                             location="$.care_setting") or ABSENT_MARKER,
        coverage_status=display(document.get("status"), location="$.status"),
        attention_level=display(document.get("attention_level"),
                                location="$.attention_level"),
        reason_codes=tuple(str(item)
                           for item in document.get("reason_codes") or ()),
        axes=tuple(_axis(axis) for axis in document.get("axes") or ()))


def build_candidate_assessment_page(document: Mapping[str, Any], *,
                                    locale: str = "tr"
                                    ) -> CandidateAssessmentModel:
    """Build the model from one candidate assessment document."""
    from pgx.reporting.templates import label

    attention = str(document.get("attention_level") or "")
    try:
        attention_label = label(attention, locale) if attention else ""
    except Exception:  # noqa: BLE001 - an unknown code shows as its code
        attention_label = attention

    return CandidateAssessmentModel(
        attention_level=attention or ABSENT_MARKER,
        attention_label=attention_label or ABSENT_MARKER,
        coverage_status=display(document.get("status"), location="$.status"),
        refusal_codes=tuple(str(item)
                            for item in document.get("refusal_codes") or ()),
        medications=tuple(_medication(item)
                          for item in document.get("medications") or ()),
        release_public_id=display(document.get("release_public_id"),
                                  location="$.release_public_id"),
        manifest_hash=display(document.get("manifest_hash"),
                              location="$.manifest_hash"),
        dataset_public_id=display(document.get("dataset_public_id"),
                                  location="$.dataset_public_id"),
        ruleset_key=display(document.get("ruleset_key"),
                            location="$.ruleset_key"),
        ruleset_content_hash=display(document.get("ruleset_content_hash"),
                                     location="$.ruleset_content_hash"),
        authority_state=display(document.get("authority_state"),
                                location="$.authority_state"),
        review_state=display(document.get("review_state"),
                             location="$.review_state"),
        claim_boundary_status=display(document.get("claim_boundary_status"),
                                      location="$.claim_boundary_status"),
        claim_boundary_is_approved=bool(
            document.get("claim_boundary_is_approved")),
        governed_registry_note=display(document.get("governed_registry_note"),
                                       location="$.governed_registry_note"),
        input_hash=display(document.get("input_hash"), location="$.input_hash"),
        output_hash=display(document.get("output_hash"),
                            location="$.output_hash"),
        computed_at=display(document.get("computed_at"),
                            location="$.computed_at"),
        case_id=display(document.get("case_id"), location="$.case_id")
        or ABSENT_MARKER,
        warning=display(document.get("warning"), location="$.warning"),
        demo_notice=ui("candidate.demo_notice", locale),
        refusal_notice=ui("candidate.refusal_notice", locale))
