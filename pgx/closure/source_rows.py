# -*- coding: utf-8 -*-
"""The recommendation rows Wave 3 read, in the source's own vocabulary.

Every row each retrieved table states is here, including the rows this project
cannot represent. That completeness is the point: the representability verdict
is computed from the recorded rows rather than being decided by which rows
somebody chose to type in, so a phenotype the project cannot carry shows up as
a recorded gap instead of as an absence nobody notices.

Three vocabularies meet in this module and none of them is allowed to
impersonate another:

``source_phenotype``
    exactly the label the guideline table uses, including the labels this
    project has no member for - ``CYP2C19 likely intermediate metabolizer``,
    ``Indeterminate``.

``project_phenotype``
    the :class:`pgx.domain.enums.Phenotype` member that carries it, or ``None``
    when none does. ``None`` is a finding, not a default.

``recommendation_verbatim``
    the therapeutic recommendation as the table states it, quoted so a reviewer
    can compare it against the published guideline without trusting a
    paraphrase.

The attention mapping is deliberately **not** here. Turning "avoid clopidogrel
if possible" into an attention level is an interpretive act by this project,
and it belongs in the curation module where it can carry a rationale and a
curator, not beside the transcription where it would look like something the
guideline said.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from pgx.domain.enums import Phenotype

__all__ = [
    "AMITRIPTYLINE_JOINT_ROWS",
    "ROWS",
    "ROWS_VERSION",
    "UNREPRESENTABLE_REASONS",
    "JointRow",
    "SourceRow",
    "project_phenotype_for",
    "rows_for",
    "unrepresentable_rows",
]

ROWS_VERSION = "pgx-wave03-source-rows/1"


#: Why a source phenotype label has no project member. Each key is a label that
#: really appears in a retrieved table; there is no catch-all entry, so a new
#: label that nobody has classified raises rather than defaulting to a reason.
UNREPRESENTABLE_REASONS: Dict[str, str] = {
    "CYP2C19 likely intermediate metabolizer": (
        "the project's phenotype vocabulary has five determinate members and "
        "no member for a likely assignment. Mapping it to INTERMEDIATE would "
        "assert a determination the source explicitly declined to make, and "
        "the guideline's own footnote says 'likely' marks uncertainty in the "
        "phenotype assignment"),
    "CYP2C19 likely poor metabolizer": (
        "same as likely intermediate: there is no member for a likely "
        "assignment, and POOR would overstate what the source concluded"),
    "Indeterminate": (
        "the source records no recommendation for it, and the project's "
        "condition grammar refuses INDETERMINATE as a rule phenotype because "
        "it describes the input rather than a phenotype a rule is about"),
    "CYP2D6 Indeterminate": (
        "same as Indeterminate: the source states 'No recommendation', which "
        "is not a finding to encode"),
}


def project_phenotype_for(source_phenotype: str) -> Optional[Phenotype]:
    """The project member carrying this source label, or ``None``.

    ``None`` means the label is recorded in :data:`UNREPRESENTABLE_REASONS`.
    A label that is neither mappable nor listed there raises, because an
    unclassified phenotype silently becoming ``None`` is how a representability
    gap turns into an ordinary absence.
    """
    lowered = source_phenotype.lower()
    if "likely" in lowered or "indeterminate" in lowered:
        if source_phenotype not in UNREPRESENTABLE_REASONS:
            raise KeyError(
                "no recorded reason for the unrepresentable label %r"
                % source_phenotype)
        return None
    for member, needle in ((Phenotype.ULTRARAPID, "ultrarapid"),
                           (Phenotype.RAPID, "rapid"),
                           (Phenotype.NORMAL, "normal"),
                           (Phenotype.INTERMEDIATE, "intermediate"),
                           (Phenotype.POOR, "poor")):
        if needle in lowered:
            return member
    raise KeyError("unclassified source phenotype label %r" % source_phenotype)


@dataclass(frozen=True, slots=True)
class SourceRow:
    """One (gene, drug, phenotype) row of a retrieved recommendation table."""

    retrieval_key: str
    gene: str
    drug: str
    source_phenotype: str
    context: str
    recommendation_verbatim: str
    classification: str
    implication_verbatim: str

    @property
    def project_phenotype(self) -> Optional[Phenotype]:
        return project_phenotype_for(self.source_phenotype)

    @property
    def is_representable(self) -> bool:
        return self.project_phenotype is not None

    def to_json(self) -> Dict[str, Any]:
        member = self.project_phenotype
        payload: Dict[str, Any] = {
            "classification": self.classification,
            "context": self.context,
            "drug": self.drug,
            "gene": self.gene,
            "implication_verbatim": self.implication_verbatim,
            "project_phenotype": member.value if member else None,
            "recommendation_verbatim": self.recommendation_verbatim,
            "retrieval_key": self.retrieval_key,
            "source_phenotype": self.source_phenotype,
        }
        if member is None:
            payload["unrepresentable_reason"] = \
                UNREPRESENTABLE_REASONS[self.source_phenotype]
        return payload


_ACS = "ACS and/or PCI"
_STD75 = "use at standard dose (75 mg/day)"
_AVOID_STD = ("Avoid standard dose clopidogrel (75 mg) if possible. Use "
              "prasugrel or ticagrelor at standard dose if no "
              "contraindication.")
_AVOID_CLOP = ("Avoid clopidogrel if possible. Use prasugrel or ticagrelor at "
               "standard dose if no contraindication.")

_PPI_UM = ("Increase starting daily dose by 100%. Daily dose may be given in "
           "divided doses. Monitor for efficacy.")
_PPI_STD = ("Initiate standard starting daily dose. Consider increasing dose "
            "by 50-100% for the treatment of H. pylori infection and erosive "
            "esophagitis. Daily dose may be given in divided doses. Monitor "
            "for efficacy.")
_PPI_RED = ("Initiate standard starting daily dose. For chronic therapy (>12 "
            "weeks) and efficacy achieved, consider 50% reduction in daily "
            "dose and monitor for continued efficacy.")

_COD_AVOID_TOX = ("Avoid codeine use because of potential for serious "
                  "toxicity. If opioid use is warranted, consider a "
                  "non-tramadol opioid.")
_COD_LABEL = "Use codeine label recommended age- or weight-specific dosing"
_COD_LABEL_IM = ("Use codeine label recommended age- or weight-specific "
                 "dosing. If no response and opioid use is warranted, "
                 "consider a non-tramadol opioid")
_COD_AVOID_INEFF = ("Avoid codeine use because of possibility of diminished "
                    "analgesia. If opioid use is warranted, consider a "
                    "non-tramadol opioid.")

_AMI_D6_UM = ("Avoid tricyclic use due to potential lack of efficacy. Consider "
              "alternative drug not metabolized by CYP2D6. If a TCA is "
              "warranted, consider titrating to a higher target dose "
              "(compared to normal metabolizers). Utilize therapeutic drug "
              "monitoring to guide dose adjustments.")
_AMI_START = "Initiate therapy with recommended starting dose."
_AMI_D6_IM = ("Consider 25% reduction of recommended starting dose. Utilize "
              "therapeutic drug monitoring to guide dose adjustments.")
_AMI_D6_PM = ("Avoid tricyclic use due to potential for side effects. "
              "Consider alternative drug not metabolized by CYP2D6. If a TCA "
              "is warranted, consider 50% reduction of recommended starting "
              "dose. Utilize therapeutic drug monitoring to guide dose "
              "adjustments.")
_AMI_C19_AVOID = ("Avoid tertiary amine use due to potential for sub-optimal "
                  "response. Consider alternative drug not metabolized by "
                  "CYP2C19. TCAs without major CYP2C19 metabolism include the "
                  "secondary amines nortriptyline and desipramine. If a "
                  "tertiary amine is warranted, utilize therapeutic drug "
                  "monitoring to guide dose adjustments.")
_AMI_C19_PM = ("Avoid tertiary amine use due to potential for sub-optimal "
               "response. Consider alternative drug not metabolized by "
               "CYP2C19. TCAs without major CYP2C19 metabolism include the "
               "secondary amines nortriptyline and desipramine. For tertiary "
               "amines, consider a 50% reduction of the recommended starting "
               "dose. Utilize therapeutic drug monitoring to guide dose "
               "adjustments.")

_NO_REC = "No recommendation"


ROWS: Tuple[SourceRow, ...] = (
    # -- clopidogrel, CYP2C19, restricted to the ACS/PCI column --------------
    # The guideline's Table 1 carries two independent classification columns
    # and a second table for neurovascular indications. Only the ACS/PCI
    # column is transcribed, because that is the only context the first
    # release claims, and a row lifted out of its column would apply to
    # indications the guideline answers differently.
    SourceRow("cpic.clopidogrel.cyp2c19", "CYP2C19", "clopidogrel",
              "CYP2C19 ultrarapid metabolizer", _ACS, _STD75, "Strong",
              "Normal or increased platelet inhibition"),
    SourceRow("cpic.clopidogrel.cyp2c19", "CYP2C19", "clopidogrel",
              "CYP2C19 rapid metabolizer", _ACS, _STD75, "Strong",
              "Normal or increased platelet inhibition"),
    SourceRow("cpic.clopidogrel.cyp2c19", "CYP2C19", "clopidogrel",
              "CYP2C19 normal metabolizer", _ACS, _STD75, "Strong",
              "Normal platelet inhibition"),
    SourceRow("cpic.clopidogrel.cyp2c19", "CYP2C19", "clopidogrel",
              "CYP2C19 likely intermediate metabolizer", _ACS, _AVOID_STD,
              "Strong",
              "Likely reduced platelet inhibition; likely increased residual "
              "platelet aggregation; likely increased risk for adverse "
              "cardiovascular events"),
    SourceRow("cpic.clopidogrel.cyp2c19", "CYP2C19", "clopidogrel",
              "CYP2C19 intermediate metabolizer", _ACS, _AVOID_STD, "Strong",
              "Reduced platelet inhibition; increased residual platelet "
              "aggregation; increased risk for adverse cardiovascular events"),
    SourceRow("cpic.clopidogrel.cyp2c19", "CYP2C19", "clopidogrel",
              "CYP2C19 likely poor metabolizer", _ACS, _AVOID_CLOP, "Strong",
              "Likely significantly reduced platelet inhibition; likely "
              "increased residual platelet aggregation; likely increased risk "
              "for adverse cardiovascular events"),
    SourceRow("cpic.clopidogrel.cyp2c19", "CYP2C19", "clopidogrel",
              "CYP2C19 poor metabolizer", _ACS, _AVOID_CLOP, "Strong",
              "Significantly reduced platelet inhibition; increased residual "
              "platelet aggregation; increased risk for adverse "
              "cardiovascular events"),
    SourceRow("cpic.clopidogrel.cyp2c19", "CYP2C19", "clopidogrel",
              "Indeterminate", _ACS, _NO_REC, _NO_REC, "n/a"),

    # -- omeprazole, CYP2C19 -------------------------------------------------
    SourceRow("cpic.omeprazole.cyp2c19", "CYP2C19", "omeprazole",
              "CYP2C19 Ultrarapid metabolizer", "all indications", _PPI_UM,
              "Optional",
              "Decreased plasma concentrations of PPIs compared to CYP2C19 "
              "NMs; increased risk of therapeutic failure"),
    SourceRow("cpic.omeprazole.cyp2c19", "CYP2C19", "omeprazole",
              "CYP2C19 Rapid metabolizer", "all indications", _PPI_STD,
              "Moderate",
              "Decreased plasma concentrations of PPIs compared to CYP2C19 "
              "NMs; increased risk of therapeutic failure"),
    SourceRow("cpic.omeprazole.cyp2c19", "CYP2C19", "omeprazole",
              "CYP2C19 Normal metabolizer", "all indications", _PPI_STD,
              "Moderate",
              "Normal PPI metabolism; may be at increased risk of therapeutic "
              "failure compared to CYP2C19 IMs and PMs"),
    SourceRow("cpic.omeprazole.cyp2c19", "CYP2C19", "omeprazole",
              "CYP2C19 likely intermediate metabolizer", "all indications",
              _PPI_RED, "Optional",
              "Likely increased plasma concentration of PPI compared to "
              "CYP2C19 NMs; likely increased chance of efficacy and "
              "potentially toxicity"),
    SourceRow("cpic.omeprazole.cyp2c19", "CYP2C19", "omeprazole",
              "CYP2C19 intermediate metabolizer", "all indications", _PPI_RED,
              "Optional",
              "Increased plasma concentration of PPI compared to CYP2C19 NMs; "
              "increased chance of efficacy and potentially toxicity"),
    SourceRow("cpic.omeprazole.cyp2c19", "CYP2C19", "omeprazole",
              "CYP2C19 likely poor metabolizer", "all indications", _PPI_RED,
              "Moderate",
              "Likely increased plasma concentration of PPI compared to "
              "CYP2C19 NMs; likely increased chance of efficacy and "
              "potentially toxicity"),
    SourceRow("cpic.omeprazole.cyp2c19", "CYP2C19", "omeprazole",
              "CYP2C19 poor metabolizer", "all indications", _PPI_RED,
              "Moderate",
              "Increased plasma concentration of PPI compared to CYP2C19 NMs; "
              "increased chance of efficacy and potentially toxicity"),
    SourceRow("cpic.omeprazole.cyp2c19", "CYP2C19", "omeprazole",
              "Indeterminate", "all indications", _NO_REC, _NO_REC, "N/A"),

    # -- codeine, CYP2D6 -----------------------------------------------------
    # The CYP2D6 axis in this guideline has no rapid metabolizer row. That is
    # not an omission in this transcription: CPIC's CYP2D6 model is an
    # activity-score model whose bands are ultrarapid, normal, intermediate and
    # poor. A CYP2D6 RAPID input therefore has no source row at all.
    SourceRow("cpic.codeine.cyp2d6", "CYP2D6", "codeine",
              "CYP2D6 ultrarapid metabolizer", "all indications",
              _COD_AVOID_TOX, "Strong",
              "Increased formation of morphine leading to higher risk of "
              "toxicity."),
    SourceRow("cpic.codeine.cyp2d6", "CYP2D6", "codeine",
              "CYP2D6 normal metabolizer", "all indications", _COD_LABEL,
              "Strong", "Expected morphine formation"),
    SourceRow("cpic.codeine.cyp2d6", "CYP2D6", "codeine",
              "CYP2D6 intermediate metabolizer", "all indications",
              _COD_LABEL_IM, "Moderate", "Reduced morphine formation."),
    SourceRow("cpic.codeine.cyp2d6", "CYP2D6", "codeine",
              "CYP2D6 poor metabolizer", "all indications", _COD_AVOID_INEFF,
              "Strong",
              "Greatly reduced morphine formation leading to diminished "
              "analgesia"),
    SourceRow("cpic.codeine.cyp2d6", "CYP2D6", "codeine",
              "CYP2D6 Indeterminate", "all indications", _NO_REC, _NO_REC,
              "n/a"),

    # -- amitriptyline, CYP2D6 axis (guideline Table 1) ----------------------
    # This axis has no rapid metabolizer row either, and for the same reason as
    # codeine: CPIC's CYP2D6 model has no such band.
    SourceRow("cpic.amitriptyline.cyp2c19_cyp2d6", "CYP2D6", "amitriptyline",
              "CYP2D6 Ultrarapid metabolizer", "higher initial doses, e.g. "
              "depression", _AMI_D6_UM, "Strong",
              "Increased metabolism of TCAs to less active compounds compared "
              "to normal metabolizers. Lower plasma concentrations of active "
              "drug will increase probability of pharmacotherapy failure."),
    SourceRow("cpic.amitriptyline.cyp2c19_cyp2d6", "CYP2D6", "amitriptyline",
              "CYP2D6 Normal metabolizer", "higher initial doses, e.g. "
              "depression", _AMI_START, "Strong",
              "Normal metabolism of TCAs."),
    SourceRow("cpic.amitriptyline.cyp2c19_cyp2d6", "CYP2D6", "amitriptyline",
              "CYP2D6 Intermediate metabolizer", "higher initial doses, e.g. "
              "depression", _AMI_D6_IM, "Moderate",
              "Reduced metabolism of TCAs to less active compounds when "
              "compared to normal metabolizers. Higher plasma concentrations "
              "of active drug will increase the probability of side effects."),
    SourceRow("cpic.amitriptyline.cyp2c19_cyp2d6", "CYP2D6", "amitriptyline",
              "CYP2D6 Poor metabolizer", "higher initial doses, e.g. "
              "depression", _AMI_D6_PM, "Strong",
              "Greatly reduced metabolism of TCAs to less active compounds "
              "compared to normal metabolizers. Higher plasma concentrations "
              "of active drug will increase the probability of side effects."),

    # -- amitriptyline, CYP2C19 axis (guideline Table 2) ---------------------
    # This table predates CPIC's likely-phenotype labels, so its CYP2C19 axis
    # has five determinate rows and no likely rows at all. A likely CYP2C19
    # assignment therefore has no amitriptyline source row on this axis - a
    # different kind of gap from clopidogrel's, where the row exists and this
    # project cannot carry it.
    SourceRow("cpic.amitriptyline.cyp2c19_cyp2d6", "CYP2C19", "amitriptyline",
              "CYP2C19 Ultrarapid metabolizer", "higher initial doses, e.g. "
              "depression", _AMI_C19_AVOID, "Optional",
              "Increased metabolism of tertiary amines compared to normal "
              "metabolizers. Greater conversion of tertiary amines to "
              "secondary amines may affect response or side effects."),
    SourceRow("cpic.amitriptyline.cyp2c19_cyp2d6", "CYP2C19", "amitriptyline",
              "CYP2C19 Rapid metabolizer", "higher initial doses, e.g. "
              "depression", _AMI_C19_AVOID, "Optional",
              "Increased metabolism of tertiary amines compared to normal "
              "metabolizers. Greater conversion of tertiary amines to "
              "secondary amines may affect response or side effects."),
    SourceRow("cpic.amitriptyline.cyp2c19_cyp2d6", "CYP2C19", "amitriptyline",
              "CYP2C19 Normal metabolizer", "higher initial doses, e.g. "
              "depression", _AMI_START, "Strong",
              "Normal metabolism of tertiary amines."),
    SourceRow("cpic.amitriptyline.cyp2c19_cyp2d6", "CYP2C19", "amitriptyline",
              "CYP2C19 Intermediate metabolizer", "higher initial doses, e.g. "
              "depression", _AMI_START, "Strong",
              "Reduced metabolism of tertiary amines compared to normal "
              "metabolizers."),
    SourceRow("cpic.amitriptyline.cyp2c19_cyp2d6", "CYP2C19", "amitriptyline",
              "CYP2C19 Poor metabolizer", "higher initial doses, e.g. "
              "depression", _AMI_C19_PM, "Moderate",
              "Greatly reduced metabolism of tertiary amines compared to "
              "normal metabolizers. Decreased conversion of tertiary amines "
              "to secondary amines may affect response or side effects."),
)


def rows_for(*, gene: Optional[str] = None,
             drug: Optional[str] = None) -> Tuple[SourceRow, ...]:
    """Recorded rows filtered by gene and/or drug, in recorded order."""
    return tuple(row for row in ROWS
                 if (gene is None or row.gene == gene)
                 and (drug is None or row.drug == drug))


def unrepresentable_rows() -> Tuple[SourceRow, ...]:
    """Every recorded row this project's phenotype vocabulary cannot carry."""
    return tuple(row for row in ROWS if not row.is_representable)


# -- amitriptyline, the joint table (guideline Table 3) ----------------------
#
# Table 3 is a two-dimensional function of CYP2C19 and CYP2D6 together, and it
# is not the pointwise combination of Tables 1 and 2. It is recorded here in
# its own shape rather than being folded into ROWS, because the project's rule
# grammar has exactly one gene per condition and therefore cannot carry a cell
# of this table as a rule. What it is for is checking: a candidate ruleset
# built from the single-gene axes must be compared against this table cell by
# cell, and any cell where the combination would come out weaker than the
# guideline is a cell the ruleset must refuse rather than answer.

_J_AVOID = "Avoid amitriptyline use."
_J_ALT = "Consider alternative drug not metabolized by CYP2C19."
_J_START = "Initiate therapy with recommended starting dose."
_J_25 = "Consider 25% reduction of recommended starting dose."
_J_UM_TITRATE = ("Avoid amitriptyline use. If amitriptyline is warranted, "
                 "consider titrating to a higher target dose (compared to "
                 "normal metabolizers).")
_J_PM_50 = ("Avoid amitriptyline use. If amitriptyline is warranted, consider "
            "50% reduction of recommended starting dose.")
_J_NM_50 = ("Avoid amitriptyline use. If amitriptyline is warranted, consider "
            "a 50% reduction of recommended starting dose.")


@dataclass(frozen=True, slots=True)
class JointRow:
    """One cell of the amitriptyline CYP2C19 x CYP2D6 table.

    ``cyp2c19_source_phenotype`` may name two phenotypes at once - the
    guideline's own first row is "CYP2C19 Ultrarapid or Rapid metabolizer".
    :meth:`cyp2c19_members` expands that into the project's separate members
    explicitly, never by treating one as an alias of the other.
    """

    cyp2c19_source_phenotype: str
    cyp2d6_source_phenotype: str
    recommendation_verbatim: str
    classification: str

    def cyp2c19_members(self) -> Tuple[Phenotype, ...]:
        label = self.cyp2c19_source_phenotype
        if "Ultrarapid or Rapid" in label:
            return (Phenotype.ULTRARAPID, Phenotype.RAPID)
        member = project_phenotype_for(label)
        return (member,) if member is not None else ()

    def cyp2d6_member(self) -> Optional[Phenotype]:
        return project_phenotype_for(self.cyp2d6_source_phenotype)

    def to_json(self) -> Dict[str, Any]:
        return {
            "classification": self.classification,
            "cyp2c19_project_phenotypes": [m.value
                                           for m in self.cyp2c19_members()],
            "cyp2c19_source_phenotype": self.cyp2c19_source_phenotype,
            "cyp2d6_project_phenotype": (
                self.cyp2d6_member().value if self.cyp2d6_member() else None),
            "cyp2d6_source_phenotype": self.cyp2d6_source_phenotype,
            "recommendation_verbatim": self.recommendation_verbatim,
        }


_C19_UMRM = "CYP2C19 Ultrarapid or Rapid metabolizer"
_C19_NM = "CYP2C19 Normal metabolizer"
_C19_IM = "CYP2C19 Intermediate metabolizer"
_C19_PM = "CYP2C19 Poor metabolizer"
_D6_UM = "CYP2D6 Ultrarapid metabolizer"
_D6_NM = "CYP2D6 Normal metabolizer"
_D6_IM = "CYP2D6 Intermediate metabolizer"
_D6_PM = "CYP2D6 Poor metabolizer"


AMITRIPTYLINE_JOINT_ROWS: Tuple[JointRow, ...] = (
    JointRow(_C19_UMRM, _D6_UM, _J_AVOID, "Optional"),
    JointRow(_C19_UMRM, _D6_NM, _J_ALT, "Optional"),
    JointRow(_C19_UMRM, _D6_IM, _J_ALT, "Optional"),
    JointRow(_C19_UMRM, _D6_PM, _J_AVOID, "Optional"),
    JointRow(_C19_NM, _D6_UM, _J_UM_TITRATE, "Strong"),
    JointRow(_C19_NM, _D6_NM, _J_START, "Strong"),
    JointRow(_C19_NM, _D6_IM, _J_25, "Moderate"),
    JointRow(_C19_NM, _D6_PM, _J_PM_50, "Strong"),
    JointRow(_C19_IM, _D6_UM, _J_AVOID, "Optional"),
    JointRow(_C19_IM, _D6_NM, _J_START, "Strong"),
    JointRow(_C19_IM, _D6_IM, _J_25, "Optional"),
    JointRow(_C19_IM, _D6_PM, _J_PM_50, "Optional"),
    JointRow(_C19_PM, _D6_UM, _J_AVOID, "Optional"),
    JointRow(_C19_PM, _D6_NM, _J_NM_50, "Moderate"),
    JointRow(_C19_PM, _D6_IM, _J_AVOID, "Optional"),
    JointRow(_C19_PM, _D6_PM, _J_AVOID, "Optional"),
)
