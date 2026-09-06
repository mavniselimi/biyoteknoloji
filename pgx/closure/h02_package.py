# -*- coding: utf-8 -*-
"""WP-C03/H02: the clinical pharmacogenomics decisions, laid out for review.

A reviewer should not have to reconstruct this repository's history to make a
decision. Each record below separates seven things that are routinely
conflated, and the separation is the point:

``source_observation``
    What the authoritative source actually states. Not a summary of what the
    project wants it to say.
``repository_assumption``
    What this repository currently assumes, whether or not that matches.
``owner_direction``
    What the project owner has directed as product scope. The owner's
    authority is repository ownership and product direction, not clinical or
    scientific judgement, so these are marked
    ``PROJECT_OWNER_DIRECTION / PENDING_CLINICAL_CONFIRMATION`` and remain
    open until a qualified reviewer confirms or overrides them.
``proposed_representation``
    How the project proposes to encode the answer. A proposal, not a design
    decision already taken.
``safety_consequence``
    What goes wrong clinically if this is decided wrongly. Written as a
    consequence, not a probability.
``open_question``
    The scientific question nobody here can answer.
``decision_requested``
    Exactly what the reviewer is being asked to say.

**Mehmet Yetiş's H01 approval is not an H02 approval.** H01 was a decision
about which sources this project may use and on what terms. Nothing in it
speaks to how a source's content is turned into a clinical representation,
and it must not be reused here.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

__all__ = ["H02_DECISIONS", "OWNER_DIRECTION_STATUS", "covered_contradictions",
           "decision_ids"]

#: The status every project-owner direction carries until a clinician rules.
OWNER_DIRECTION_STATUS = "PROJECT_OWNER_DIRECTION / PENDING_CLINICAL_CONFIRMATION"

H02_DECISIONS: Tuple[Dict[str, Any], ...] = (
    {
        "decision_id": "H02-D01",
        "covers_scope_contradictions": (),
        "subject": "approve the curation protocol and its vocabularies",
        "source_observation":
            "Not a source question. The protocol is this project's own "
            "document and it declares itself unapproved: its `approval` "
            "field is null and every vocabulary is marked "
            "DRAFT_AWAITING_EXPERT_REVIEW.",
        "repository_assumption":
            "Every curation work item is RAW and none may proceed. The "
            "repository is behaving correctly; it simply cannot start.",
        "owner_direction": "none; this is not the owner's to direct",
        "proposed_representation":
            "Approve the protocol as written, or name the changes required. "
            "Approval is recorded against the protocol's content hash so a "
            "later edit does not inherit it.",
        "safety_consequence":
            "A curator working to a draft vocabulary produces drafts that "
            "look like conclusions. Every downstream artifact would inherit "
            "definitions nobody had agreed.",
        "open_question":
            "Are the field definitions and vocabularies adequate for the "
            "five declared axes, or do they need changes first?",
        "decision_requested":
            "APPROVE the protocol against its content hash, or REJECT with "
            "the specific changes required.",
    },
    {
        "decision_id": "H02-D02",
        "covers_scope_contradictions": ("SC-01",),
        "subject": "amitriptyline as a joint CYP2C19 + CYP2D6 matrix",
        "source_observation":
            "CPIC states amitriptyline recommendations for a CYP2D6 and "
            "CYP2C19 pair together. Every recommendation record carries both "
            "gene keys; there is no single-gene amitriptyline "
            "recommendation to read off.",
        "repository_assumption":
            "The declared scope names CYP2C19::amitriptyline and "
            "CYP2D6::amitriptyline as two independent axes, which the source "
            "does not support.",
        "owner_direction":
            "Amitriptyline stays in the first release and must be "
            "represented as a joint CYP2C19 + CYP2D6 decision when the "
            "authoritative source requires both genes. Missing either gene "
            "must fail closed or return an explicit insufficient-data "
            "result.",
        "proposed_representation":
            "One axis keyed by the pair, not two. A profile carrying only "
            "one of the two genes returns an explicit insufficient-data "
            "outcome naming the missing gene, and never a partial answer.",
        "safety_consequence":
            "Answering for one gene when the source answered for both is not "
            "a subset of the recommendation; it is a different claim. A "
            "CYP2C19 normal metabolizer who is a CYP2D6 poor metabolizer "
            "would be shown a reassuring single-gene result the source never "
            "made.",
        "open_question":
            "Which cells of the joint matrix are in first-release scope, and "
            "is an explicit insufficient-data result acceptable clinically "
            "where only one gene is known?",
        "decision_requested":
            "Confirm the joint representation and the fail-closed behaviour, "
            "or direct a different model. Do not fill in the matrix cells "
            "here; that is curation.",
    },
    {
        "decision_id": "H02-D03",
        "covers_scope_contradictions": ("SC-02",),
        "subject": "clopidogrel restricted to an explicit ACS/PCI context",
        "source_observation":
            "CPIC states clopidogrel recommendations separately for "
            "cardiovascular indications with acute coronary syndrome and "
            "percutaneous coronary intervention, for other cardiovascular "
            "indications, and for neurovascular indications. They are not "
            "the same recommendation.",
        "repository_assumption":
            "The declared scope has no indication axis, so the three would "
            "collapse into one.",
        "owner_direction":
            "Clopidogrel is restricted to an explicitly represented ACS/PCI "
            "context.",
        "proposed_representation":
            "Carry the indication explicitly and answer only for ACS/PCI in "
            "the first release. A request without a stated indication "
            "returns insufficient data rather than the ACS/PCI answer.",
        "safety_consequence":
            "Collapsing three population-specific recommendations into one "
            "loses the condition each was stated under. Presenting the "
            "strongest as the answer would overstate the source for a "
            "neurovascular patient.",
        "open_question":
            "Is restricting the first release to ACS/PCI clinically "
            "coherent, and how must the restriction be shown to a reader?",
        "decision_requested":
            "Confirm the ACS/PCI restriction and the refusal to answer "
            "without a stated indication, or direct otherwise.",
    },
    {
        "decision_id": "H02-D04",
        "covers_scope_contradictions": ("SC-03",),
        "subject": "CYP2D6 phenotype and activity-score representation",
        "source_observation":
            "CPIC assigns no RAPID phenotype for CYP2D6. It does emit Likely "
            "Poor, Likely Intermediate and Indeterminate, and its CYP2D6 "
            "recommendations are keyed by activity score rather than by a "
            "phenotype label alone.",
        "repository_assumption":
            "A five-value vocabulary - POOR, INTERMEDIATE, NORMAL, RAPID, "
            "ULTRARAPID - which cannot express three of the values the "
            "source emits and carries one the source does not assign.",
        "owner_direction":
            "CYP2D6 RAPID is not an expected phenotype. Likely, "
            "Indeterminate and unrepresentable activity-score states must "
            "fail closed and must not be mapped to a neighbouring "
            "phenotype.",
        "proposed_representation":
            "Carry the activity score where the source keys on it. Represent "
            "unrepresentable states as an explicit refusal, never as the "
            "nearest available value.",
        "safety_consequence":
            "Silent coercion of Likely Poor to Poor is a clinical claim "
            "nobody made. Coercion in the other direction hides a real "
            "signal. Both are invisible to the reader.",
        "open_question":
            "Should the vocabulary be extended to the source's own values, "
            "or should the activity score be the key with phenotype as a "
            "derived label?",
        "decision_requested":
            "Decide the CYP2D6 representation and confirm the fail-closed "
            "behaviour for every state the vocabulary cannot express.",
    },
    {
        "decision_id": "H02-D05",
        "covers_scope_contradictions": ("SC-04",),
        "subject": "how the absence of a regulator source is shown",
        "source_observation":
            "FDA labelling addresses four of the five declared axes. "
            "CYP2C19 with amitriptyline is absent entirely. Of those it does "
            "address, only clopidogrel and codeine carry "
            "boxed-warning-strength language.",
        "repository_assumption":
            "Nothing distinguishes an axis with regulator support from one "
            "without it.",
        "owner_direction":
            "An axis absent from FDA evidence must not be shown as "
            "FDA-supported.",
        "proposed_representation":
            "Record regulator coverage per axis as a first-class value with "
            "three states - stated, stated with a boxed warning, absent - "
            "and show absence explicitly rather than by omission.",
        "safety_consequence":
            "A reader who sees four axes with regulator backing will assume "
            "the fifth has it too. Omission reads as support.",
        "open_question":
            "May an axis with no regulator labelling be released at all, and "
            "if so how must that be presented?",
        "decision_requested":
            "Confirm that regulator absence is displayed explicitly, and "
            "decide whether an axis without it may ship.",
    },
    {
        "decision_id": "H02-D06",
        "covers_scope_contradictions": ("SC-05",),
        "subject": "clopidogrel label extraction keyed on loss-of-function",
        "source_observation":
            "The current clopidogrel boxed warning is worded around carrying "
            "two loss-of-function alleles of CYP2C19, not around the "
            "phenotype term.",
        "repository_assumption":
            "No extraction exists yet, so nothing is currently wrong - but "
            "the obvious implementation keys on the phenotype term.",
        "owner_direction":
            "Extraction must distinguish a genuine absence from an "
            "extraction failure, and must not depend on the obsolete phrase "
            "'poor metabolizer'.",
        "proposed_representation":
            "Key on the structured warning section and on loss-of-function "
            "allele language. Return three distinct outcomes - found, "
            "genuinely absent, extraction failed - and never conflate the "
            "last two.",
        "safety_consequence":
            "An extraction keyed on the phenotype term returns nothing for "
            "the single most important warning in the first release, and "
            "silence looks exactly like absence.",
        "open_question":
            "What is the authoritative list of loss-of-function alleles for "
            "this purpose, and who maintains it?",
        "decision_requested":
            "Confirm the extraction basis and the three-outcome contract.",
    },
    {
        "decision_id": "H02-D07",
        "covers_scope_contradictions": (),
        "subject": "the 13 in-scope unlinked legacy candidates",
        "source_observation":
            "Not a source question. These 13 rows name no upstream record at "
            "all; they are the previous project's own manual normalization "
            "and hand-written hints.",
        "repository_assumption":
            "All 13 are dispositioned MISSING_EVIDENCE_REQUIRES_CURATOR and "
            "are visibly blocked on a curator. Nothing promotes them.",
        "owner_direction": "none",
        "proposed_representation":
            "A curator sources evidence for the axis from an approved source "
            "and writes a revision citing it. The legacy row's own wording is "
            "not the starting point and is not evidence.",
        "safety_consequence":
            "Starting from the legacy text would launder an unreviewed "
            "opinion into a curated interpretation, and the citation would "
            "point at nothing.",
        "open_question":
            "Are these 13 axes worth curating at all in the first release, "
            "given that the same axes will be curated from CPIC directly?",
        "decision_requested":
            "Confirm that these are curated from source rather than from "
            "legacy text, or direct that they be closed as superseded.",
    },
)


def decision_ids() -> Tuple[str, ...]:
    return tuple(item["decision_id"] for item in H02_DECISIONS)


def covered_contradictions() -> Tuple[str, ...]:
    """Which WP-C04 scope contradictions these decisions answer.

    Declared rather than inferred from wording, so the H02 package can be
    rewritten for a reader without a coverage test silently passing on a
    string that happens to still match.
    """
    found = set()
    for item in H02_DECISIONS:
        found.update(item.get("covers_scope_contradictions") or ())
    return tuple(sorted(found))
