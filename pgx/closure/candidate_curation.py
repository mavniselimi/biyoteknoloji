# -*- coding: utf-8 -*-
"""Internal curation of the retrieved rows into attention levels (WP-C07).

This is where the project stops transcribing and starts interpreting. A CPIC
recommendation is a sentence addressed to a prescriber; an
:class:`~pgx.domain.enums.AttentionLevel` is a four-valued signal this system
emits. Turning one into the other is a judgement, and every judgement here
belongs to this project, not to CPIC.

Two design choices carry most of the weight.

**The mapping is per-recommendation, not per-rule-of-thumb.** It would be
shorter to write "any sentence containing 'avoid' is HIGH", and it would be
wrong twice over: omeprazole's normal-metabolizer row contains no 'avoid' and
still asks the prescriber to consider a 50-100% dose increase for two named
indications, while amitriptyline's joint table says "consider an alternative
drug" without ever saying 'avoid'. So each recommendation is mapped
individually, with its own recorded reason, and an unmapped recommendation
raises rather than falling through to a default.

**NO_ACTIVE_ATTENTION is used sparingly and never as a synonym for 'low'.**
It is reserved for rows where the guideline asks for nothing at all: standard
dose, no monitoring qualifier, no indication-specific consideration. Where the
guideline attaches any conditional action - "consider increasing for H. pylori
infection", "if no response, consider a non-tramadol opioid" - the row is LOW,
because something was found and a reader who saw NO_ACTIVE_ATTENTION would not
go looking for it. This is ``SAFETY-INV-001`` applied to the boundary between
"nothing" and "something small", which is the boundary where false reassurance
actually happens.

Nothing in this module writes to ``pgx.curation``. The WP-10 curation store
requires an approved protocol and a named expert (see ``AB-03`` in
:mod:`pgx.closure.authority`), and neither exists. These records are internal
curation on the candidate track and say so in their authority state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from pgx.closure.authority import CandidateAuthorityState
from pgx.closure.source_rows import (AMITRIPTYLINE_JOINT_ROWS, ROWS, JointRow,
                                     SourceRow)
from pgx.domain.enums import AttentionLevel, Phenotype
from pgx.engine.risk_models import ATTENTION_PRECEDENCE

__all__ = [
    "CURATION_VERSION",
    "CURATIONS",
    "JOINT_CHECKS",
    "RECOMMENDATION_MAPPING",
    "CandidateCuration",
    "JointCheck",
    "attention_for_recommendation",
    "curations_for",
    "joint_consistency_failures",
    "single_axis_attention",
]

CURATION_VERSION = "pgx-wave03-candidate-curation/1"

#: The curating identity. Named as a process, not as a person, because that is
#: what it is. Wave 3 is forbidden to invent a human curator and this string is
#: the place that prohibition would first be broken if it were going to be.
CURATED_BY = "pgx-closure-wave03 automated curation pass (no human curator)"


#: Every recommendation sentence that appears in a recorded row, mapped to the
#: level this project assigns it and the reason for that assignment. Keyed by
#: the verbatim sentence so that a change in the source text - a CPIC revision,
#: a transcription slip - surfaces as a KeyError rather than as a silently
#: re-used mapping from the sentence it replaced.
RECOMMENDATION_MAPPING: Mapping[str, Tuple[AttentionLevel, str]] = {
    "use at standard dose (75 mg/day)": (
        AttentionLevel.NO_ACTIVE_ATTENTION,
        "the guideline asks for standard dosing with no qualifier, no "
        "monitoring requirement and no indication-specific consideration: the "
        "genotype was assessed and nothing follows from it"),
    ("Avoid standard dose clopidogrel (75 mg) if possible. Use prasugrel or "
     "ticagrelor at standard dose if no contraindication."): (
        AttentionLevel.HIGH,
        "the guideline directs the prescriber away from the standard dose of "
        "the drug being assessed and names replacement agents"),
    ("Avoid clopidogrel if possible. Use prasugrel or ticagrelor at standard "
     "dose if no contraindication."): (
        AttentionLevel.HIGH,
        "the guideline directs the prescriber away from the drug entirely"),
    ("Increase starting daily dose by 100%. Daily dose may be given in "
     "divided doses. Monitor for efficacy."): (
        AttentionLevel.MEDIUM,
        "a dose change is required rather than considered, and efficacy "
        "monitoring is attached, but the drug itself is not withdrawn"),
    ("Initiate standard starting daily dose. Consider increasing dose by "
     "50-100% for the treatment of H. pylori infection and erosive "
     "esophagitis. Daily dose may be given in divided doses. Monitor for "
     "efficacy."): (
        AttentionLevel.LOW,
        "standard dosing is the instruction, but two named indications carry "
        "a conditional dose increase and efficacy monitoring is attached; "
        "NO_ACTIVE_ATTENTION would hide a consideration the prescriber is "
        "asked to make"),
    ("Initiate standard starting daily dose. For chronic therapy (>12 weeks) "
     "and efficacy achieved, consider 50% reduction in daily dose and monitor "
     "for continued efficacy."): (
        AttentionLevel.LOW,
        "standard dosing is the instruction, with a conditional reduction "
        "that applies only after twelve weeks of therapy; the condition is "
        "real but neither immediate nor certain"),
    ("Avoid codeine use because of potential for serious toxicity. If opioid "
     "use is warranted, consider a non-tramadol opioid."): (
        AttentionLevel.HIGH,
        "the guideline directs the prescriber away from the drug and names "
        "serious toxicity as the reason"),
    "Use codeine label recommended age- or weight-specific dosing": (
        AttentionLevel.NO_ACTIVE_ATTENTION,
        "label dosing with no qualifier: the genotype was assessed and "
        "nothing follows from it"),
    ("Use codeine label recommended age- or weight-specific dosing. If no "
     "response and opioid use is warranted, consider a non-tramadol opioid"): (
        AttentionLevel.LOW,
        "label dosing, with a conditional switch of agent if the patient does "
        "not respond; something follows from the genotype even though no "
        "immediate change does"),
    ("Avoid codeine use because of possibility of diminished analgesia. If "
     "opioid use is warranted, consider a non-tramadol opioid."): (
        AttentionLevel.HIGH,
        "the guideline directs the prescriber away from the drug; that the "
        "harm is failed analgesia rather than toxicity does not lower the "
        "attention a prescriber needs to pay"),
    ("Avoid tricyclic use due to potential lack of efficacy. Consider "
     "alternative drug not metabolized by CYP2D6. If a TCA is warranted, "
     "consider titrating to a higher target dose (compared to normal "
     "metabolizers). Utilize therapeutic drug monitoring to guide dose "
     "adjustments."): (
        AttentionLevel.HIGH,
        "the guideline directs the prescriber away from the drug class and "
        "attaches therapeutic drug monitoring if it is used anyway"),
    "Initiate therapy with recommended starting dose.": (
        AttentionLevel.NO_ACTIVE_ATTENTION,
        "the recommended starting dose with no qualifier attached"),
    ("Consider 25% reduction of recommended starting dose. Utilize "
     "therapeutic drug monitoring to guide dose adjustments."): (
        AttentionLevel.MEDIUM,
        "a specific dose reduction and therapeutic drug monitoring, without "
        "withdrawal of the drug"),
    ("Avoid tricyclic use due to potential for side effects. Consider "
     "alternative drug not metabolized by CYP2D6. If a TCA is warranted, "
     "consider 50% reduction of recommended starting dose. Utilize "
     "therapeutic drug monitoring to guide dose adjustments."): (
        AttentionLevel.HIGH,
        "the guideline directs the prescriber away from the drug class and "
        "halves the dose if it is used anyway"),
    ("Avoid tertiary amine use due to potential for sub-optimal response. "
     "Consider alternative drug not metabolized by CYP2C19. TCAs without "
     "major CYP2C19 metabolism include the secondary amines nortriptyline and "
     "desipramine. If a tertiary amine is warranted, utilize therapeutic drug "
     "monitoring to guide dose adjustments."): (
        AttentionLevel.HIGH,
        "the guideline directs the prescriber away from the drug's chemical "
        "class and names replacement agents"),
    ("Avoid tertiary amine use due to potential for sub-optimal response. "
     "Consider alternative drug not metabolized by CYP2C19. TCAs without "
     "major CYP2C19 metabolism include the secondary amines nortriptyline and "
     "desipramine. For tertiary amines, consider a 50% reduction of the "
     "recommended starting dose. Utilize therapeutic drug monitoring to guide "
     "dose adjustments."): (
        AttentionLevel.HIGH,
        "as above, with a halved dose if the drug is used anyway"),
    # -- joint-table sentences, used only for the consistency check ----------
    "Avoid amitriptyline use.": (
        AttentionLevel.HIGH,
        "the guideline directs the prescriber away from the drug"),
    "Consider alternative drug not metabolized by CYP2C19.": (
        AttentionLevel.HIGH,
        "an instruction to use a different drug is an avoidance instruction "
        "whether or not the word 'avoid' appears in it"),
    ("Avoid amitriptyline use. If amitriptyline is warranted, consider "
     "titrating to a higher target dose (compared to normal metabolizers)."): (
        AttentionLevel.HIGH,
        "avoidance, with a dose direction attached if the drug is used"),
    "Consider 25% reduction of recommended starting dose.": (
        AttentionLevel.MEDIUM,
        "a specific dose reduction without withdrawal of the drug"),
    ("Avoid amitriptyline use. If amitriptyline is warranted, consider 50% "
     "reduction of recommended starting dose."): (
        AttentionLevel.HIGH,
        "avoidance, with a halved dose if the drug is used"),
    ("Avoid amitriptyline use. If amitriptyline is warranted, consider a 50% "
     "reduction of recommended starting dose."): (
        AttentionLevel.HIGH,
        "avoidance, with a halved dose if the drug is used; CPIC words this "
        "cell with an article the neighbouring cell omits, and both spellings "
        "are kept rather than normalised, because normalising source text is "
        "how a transcription starts drifting from its source"),
}


def attention_for_recommendation(
        recommendation: str) -> Tuple[AttentionLevel, str]:
    """The level this project assigns a recommendation, and why.

    Raises on an unmapped sentence. That is the intended behaviour: a
    recommendation nobody has classified must stop the build, because the
    alternative is a rule carrying a level nobody chose.
    """
    try:
        return RECOMMENDATION_MAPPING[recommendation]
    except KeyError:
        raise KeyError(
            "no recorded attention mapping for the recommendation %r. A "
            "recommendation must be classified explicitly; there is no "
            "default." % recommendation) from None


@dataclass(frozen=True, slots=True)
class CandidateCuration:
    """One curated interpretation on the candidate track.

    Deliberately not a :class:`pgx.curation.models.CuratedInterpretation`. That
    type belongs to a store whose entry conditions this project cannot meet,
    and constructing one here would put a record into a governed workflow
    without the approval that workflow exists to require.
    """

    curation_key: str
    gene: str
    drug: str
    phenotype: Phenotype
    context: str
    attention_level: AttentionLevel
    rationale: str
    source_recommendation: str
    source_classification: str
    retrieval_key: str
    curated_by: str = CURATED_BY
    authority_state: CandidateAuthorityState = \
        CandidateAuthorityState.SOURCE_GROUNDED_INTERNAL_DECISION
    review_state: CandidateAuthorityState = \
        CandidateAuthorityState.PENDING_EXTERNAL_EXPERT_REVIEW

    def to_json(self) -> Dict[str, Any]:
        return {
            "attention_level": self.attention_level.value,
            "authority_state": self.authority_state.value,
            "context": self.context,
            "curated_by": self.curated_by,
            "curation_key": self.curation_key,
            "drug": self.drug,
            "gene": self.gene,
            "phenotype": self.phenotype.value,
            "rationale": self.rationale,
            "retrieval_key": self.retrieval_key,
            "review_state": self.review_state.value,
            "source_classification": self.source_classification,
            "source_recommendation": self.source_recommendation,
        }


def _build_curations() -> Tuple[CandidateCuration, ...]:
    built = []
    for row in ROWS:
        member = row.project_phenotype
        if member is None:
            continue
        if row.recommendation_verbatim == "No recommendation":
            continue
        level, reason = attention_for_recommendation(
            row.recommendation_verbatim)
        built.append(CandidateCuration(
            curation_key="%s|%s|%s" % (row.drug, row.gene, member.value),
            gene=row.gene,
            drug=row.drug,
            phenotype=member,
            context=row.context,
            attention_level=level,
            rationale=reason,
            source_recommendation=row.recommendation_verbatim,
            source_classification=row.classification,
            retrieval_key=row.retrieval_key))
    keys = [item.curation_key for item in built]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate curation keys: a (drug, gene, phenotype) "
                         "triple was curated twice")
    return tuple(built)


CURATIONS: Tuple[CandidateCuration, ...] = _build_curations()


def curations_for(*, gene: Optional[str] = None, drug: Optional[str] = None
                  ) -> Tuple[CandidateCuration, ...]:
    return tuple(item for item in CURATIONS
                 if (gene is None or item.gene == gene)
                 and (drug is None or item.drug == drug))


def single_axis_attention(gene: str, drug: str,
                          phenotype: Phenotype) -> Optional[AttentionLevel]:
    """The curated level for one axis, or ``None`` when nothing was curated."""
    for item in CURATIONS:
        if item.gene == gene and item.drug == drug \
                and item.phenotype is phenotype:
            return item.attention_level
    return None


def _precedence_max(levels: Tuple[AttentionLevel, ...]) -> AttentionLevel:
    for level in ATTENTION_PRECEDENCE:
        if level in levels:
            return level
    raise ValueError("no levels to aggregate")


@dataclass(frozen=True, slots=True)
class JointCheck:
    """One cell of the amitriptyline joint table, checked against the axes.

    ``understates`` is the only field that matters operationally. It is true
    when combining the two single-gene rules would produce a level *weaker*
    than the level the guideline's own joint table implies - which is the one
    failure this candidate ruleset may not ship with, because it is the
    false-reassurance case.
    """

    cyp2c19_phenotype: Phenotype
    cyp2d6_phenotype: Phenotype
    joint_recommendation: str
    joint_level: AttentionLevel
    combined_level: AttentionLevel
    understates: bool

    def to_json(self) -> Dict[str, Any]:
        return {
            "combined_level": self.combined_level.value,
            "cyp2c19_phenotype": self.cyp2c19_phenotype.value,
            "cyp2d6_phenotype": self.cyp2d6_phenotype.value,
            "joint_level": self.joint_level.value,
            "joint_recommendation": self.joint_recommendation,
            "understates": self.understates,
        }


def _build_joint_checks() -> Tuple[JointCheck, ...]:
    order = list(ATTENTION_PRECEDENCE)
    checks = []
    for cell in AMITRIPTYLINE_JOINT_ROWS:
        d6_member = cell.cyp2d6_member()
        if d6_member is None:
            continue
        joint_level, _ = attention_for_recommendation(
            cell.recommendation_verbatim)
        for c19_member in cell.cyp2c19_members():
            c19_level = single_axis_attention("CYP2C19", "amitriptyline",
                                              c19_member)
            d6_level = single_axis_attention("CYP2D6", "amitriptyline",
                                             d6_member)
            if c19_level is None or d6_level is None:
                continue
            combined = _precedence_max((c19_level, d6_level))
            checks.append(JointCheck(
                cyp2c19_phenotype=c19_member,
                cyp2d6_phenotype=d6_member,
                joint_recommendation=cell.recommendation_verbatim,
                joint_level=joint_level,
                combined_level=combined,
                understates=order.index(combined) > order.index(joint_level)))
    return tuple(checks)


JOINT_CHECKS: Tuple[JointCheck, ...] = _build_joint_checks()


def joint_consistency_failures() -> Tuple[JointCheck, ...]:
    """Cells where combining the single-gene rules would understate.

    A non-empty result means the candidate ruleset must refuse the affected
    (CYP2C19, CYP2D6) combinations rather than answering them, because on those
    combinations the sum of two correct rules is a wrong answer.
    """
    return tuple(check for check in JOINT_CHECKS if check.understates)
