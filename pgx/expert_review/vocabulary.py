# -*- coding: utf-8 -*-
"""Controlled vocabularies for the blind expert review (WP-22).

Every string in this module reaches an append-only audit row that is meant to
outlive the code, so each is named once here and nowhere else.

The design decision worth stating up front: the review lifecycle is an enum
with exactly three forward transitions and no reverse edge. Not a status
column somebody sets, not a boolean pair, not a timestamp whose presence
implies a phase. The blind protocol's entire evidential value is the *order*
in which two things happened - the expert wrote down what they expected, and
only afterwards saw what the system produced - and an ordering that a caller
can express as "set status = COMPLETED" is not an ordering at all.

``INVALIDATED`` exists and is terminal. It records that a protocol or release
condition broke during a review, which is a real thing that happens and must
be distinguishable from both "still in progress" and "finished". It is not a
retry: a review that was invalidated stays invalidated, and a fresh assignment
is a fresh review with its own identity.
"""

from __future__ import annotations

from enum import Enum
from typing import FrozenSet, Mapping, Tuple

__all__ = [
    "CORRECTION_KINDS",
    "DECISION_VALUES",
    "INVALIDATION_REASONS",
    "LIKERT_DIMENSIONS",
    "LIKERT_MAXIMUM",
    "LIKERT_MINIMUM",
    "PERMITTED_STAGES",
    "RATIONALE_CODES",
    "REVIEW_ERROR_CODES",
    "TERMINAL_STATES",
    "TRANSITIONS",
    "VOCABULARY_VERSION",
    "AuditAction",
    "CorrectionKind",
    "ExpertDecision",
    "InvalidationReason",
    "RationaleCode",
    "ReviewState",
    "may_transition",
]

VOCABULARY_VERSION = "pgx-wp22-expert-review-vocabulary/1"


class _ReviewEnum(str, Enum):
    """String-valued and unordered, following the project convention.

    Ordering is disabled deliberately here too, and for a sharper reason than
    usual: ``PARTIAL`` is not halfway between ``AGREE`` and ``DISAGREE``. It is
    a third answer. Any code that sorted or averaged these would be inventing
    a scale the protocol does not have, and the first thing built on that
    scale would be a "mean agreement score".
    """

    def __str__(self) -> str:
        return self.value

    def __lt__(self, other: object) -> bool:  # pragma: no cover - guard
        raise TypeError("%s values are not ordered" % type(self).__name__)

    __le__ = __lt__
    __gt__ = __lt__
    __ge__ = __lt__


class ReviewState(_ReviewEnum):
    """Where one review is in the blind protocol.

    ``ASSIGNED``
        A named reviewer holds a named case under a named protocol and
        release. Nothing has been recorded and nothing has been shown.

    ``EXPECTATION_RECORDED``
        The reviewer's expected response is stored, hashed and timestamped by
        the server. This is the moment the review becomes evidence: from here
        on, what the reviewer thought *before* seeing the answer is fixed.

    ``RESULT_REVEALED``
        The system result has been shown, pinned to the exact expectation
        revision, release and case manifest that were in force. Reveal is the
        one-way door.

    ``COMPLETED``
        The reviewer has recorded AGREE / PARTIAL / DISAGREE and any ratings.
        The record is immutable; later changes are append-only corrections
        that annotate it and never replace it.

    ``INVALIDATED``
        A protocol or release condition broke - the release changed under the
        review, the protocol approval was withdrawn, the case manifest moved.
        Terminal. The review's records are kept, because the fact that a
        review was attempted and spoiled is itself worth knowing.
    """

    ASSIGNED = "ASSIGNED"
    EXPECTATION_RECORDED = "EXPECTATION_RECORDED"
    RESULT_REVEALED = "RESULT_REVEALED"
    COMPLETED = "COMPLETED"
    INVALIDATED = "INVALIDATED"


#: The only forward moves. Written as a mapping rather than as conditionals in
#: the service, so the whole machine is readable in one place and a new edge
#: cannot be added by accident in a branch nobody reviews.
TRANSITIONS: Mapping[str, FrozenSet[str]] = {
    ReviewState.ASSIGNED.value: frozenset({
        ReviewState.EXPECTATION_RECORDED.value,
        ReviewState.INVALIDATED.value}),
    ReviewState.EXPECTATION_RECORDED.value: frozenset({
        ReviewState.RESULT_REVEALED.value,
        ReviewState.INVALIDATED.value}),
    ReviewState.RESULT_REVEALED.value: frozenset({
        ReviewState.COMPLETED.value,
        ReviewState.INVALIDATED.value}),
    ReviewState.COMPLETED.value: frozenset(),
    ReviewState.INVALIDATED.value: frozenset(),
}

#: States from which nothing further may happen. A completed review is
#: evidence; an invalidated one is a record of spoiled evidence. Neither is a
#: starting point.
TERMINAL_STATES: FrozenSet[str] = frozenset({
    ReviewState.COMPLETED.value, ReviewState.INVALIDATED.value})


def may_transition(current: ReviewState, target: ReviewState) -> bool:
    """Whether this exact move is permitted. No inference, no shortcuts."""
    if not isinstance(current, ReviewState) or \
            not isinstance(target, ReviewState):
        raise TypeError("transitions are between ReviewState values")
    return target.value in TRANSITIONS[current.value]


class ExpertDecision(_ReviewEnum):
    """The post-reveal comparison. Exactly three answers, never a score.

    This is *not* the expected response. The expected response is what the
    reviewer thought before seeing anything; this is what they concluded after
    comparing it with the system's output. Reporting one as the other would
    turn a curator's prediction into an expert's endorsement.
    """

    AGREE = "AGREE"
    PARTIAL = "PARTIAL"
    DISAGREE = "DISAGREE"


DECISION_VALUES: Tuple[str, ...] = tuple(item.value for item in ExpertDecision)


class RationaleCode(_ReviewEnum):
    """Why the reviewer expected what they expected.

    A controlled list rather than free text, because free text in a blinded
    expectation is where a treatment recommendation would eventually appear -
    and because a rationale that can be counted is worth more to a later
    analysis than one that has to be read.
    """

    GUIDELINE_DIRECT = "GUIDELINE_DIRECT"
    GUIDELINE_EXTRAPOLATED = "GUIDELINE_EXTRAPOLATED"
    PHENOTYPE_DETERMINATIVE = "PHENOTYPE_DETERMINATIVE"
    INSUFFICIENT_INPUT = "INSUFFICIENT_INPUT"
    NO_APPLICABLE_RULE = "NO_APPLICABLE_RULE"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


RATIONALE_CODES: Tuple[str, ...] = tuple(item.value for item in RationaleCode)


#: Optional rating dimensions. Declared here, before any review exists, for the
#: same reason WP-21's metrics were: a dimension invented after seeing
#: responses describes those responses.
LIKERT_DIMENSIONS: Tuple[str, ...] = (
    "CLARITY",
    "TRACEABILITY",
    "CLINICAL_USEFULNESS",
    "SAFETY_FRAMING",
)

LIKERT_MINIMUM = 1
LIKERT_MAXIMUM = 5


class CorrectionKind(_ReviewEnum):
    """What an append-only correction is correcting.

    Every one of these *adds* a record. None of them edits the record it
    refers to, and the kind exists so a later reader can tell an
    administrative fix from a substantive change of mind - which matter very
    differently to an analysis.
    """

    TYPOGRAPHIC = "TYPOGRAPHIC"
    RATIONALE_AMENDED = "RATIONALE_AMENDED"
    EXPECTATION_AMENDED = "EXPECTATION_AMENDED"
    DECISION_ANNOTATED = "DECISION_ANNOTATED"
    RATING_ANNOTATED = "RATING_ANNOTATED"
    WITHDRAWN_BY_REVIEWER = "WITHDRAWN_BY_REVIEWER"


CORRECTION_KINDS: Tuple[str, ...] = tuple(item.value
                                          for item in CorrectionKind)


class InvalidationReason(_ReviewEnum):
    """Why a review was spoiled. Never "the reviewer changed their mind"."""

    RELEASE_CHANGED = "RELEASE_CHANGED"
    CASE_MANIFEST_CHANGED = "CASE_MANIFEST_CHANGED"
    PROTOCOL_APPROVAL_WITHDRAWN = "PROTOCOL_APPROVAL_WITHDRAWN"
    BLINDING_COMPROMISED = "BLINDING_COMPROMISED"
    REVIEWER_CONFLICT_DECLARED = "REVIEWER_CONFLICT_DECLARED"
    ASSIGNMENT_SUPERSEDED = "ASSIGNMENT_SUPERSEDED"


INVALIDATION_REASONS: Tuple[str, ...] = tuple(item.value
                                              for item in InvalidationReason)


class AuditAction(_ReviewEnum):
    """Every governed act that appends an audit event.

    There is no ``VIEW`` action for the blinded material, and that absence is
    deliberate: WP-18's access ledger already records payload reads, and
    duplicating them here would create two records of one act that could
    disagree.
    """

    ASSIGNED = "REVIEW_ASSIGNED"
    EXPECTATION_RECORDED = "REVIEW_EXPECTATION_RECORDED"
    RESULT_REVEALED = "REVIEW_RESULT_REVEALED"
    COMPLETED = "REVIEW_COMPLETED"
    INVALIDATED = "REVIEW_INVALIDATED"
    CORRECTION_APPENDED = "REVIEW_CORRECTION_APPENDED"
    PERMIT_ISSUED = "REVIEW_PERMIT_ISSUED"
    PERMIT_REFUSED = "REVIEW_PERMIT_REFUSED"


#: What a permit may authorise. A permit is stage-bound so that a reviewer who
#: has finished cannot re-open the payload: the evidential question "what did
#: they see, and when" has a different answer at each stage.
PERMITTED_STAGES: Tuple[str, ...] = (
    ReviewState.ASSIGNED.value,
    ReviewState.EXPECTATION_RECORDED.value,
    ReviewState.RESULT_REVEALED.value,
)


#: Stable error codes. Deliberately coarse where a finer code would answer a
#: question the caller has not earned: an unassigned reviewer and a
#: nonexistent case both get ``EXPERT_REVIEW_NOT_ASSIGNED``, because a
#: distinguishable pair would make the endpoint a case-existence oracle.
REVIEW_ERROR_CODES: Mapping[str, str] = {
    "EXPERT_REVIEW_NOT_AVAILABLE":
        "the review service, its store or its dependencies are unavailable",
    "EXPERT_REVIEW_NOT_ASSIGNED":
        "this reviewer holds no active assignment for this case; returned "
        "identically whether or not the case exists",
    "EXPERT_REVIEW_PROTOCOL_NOT_APPROVED":
        "the blind review protocol has not been approved by named human and "
        "scientific reviewers",
    "EXPERT_REVIEW_EXPECTATION_REQUIRED":
        "the expected response must be recorded before anything is revealed",
    "EXPERT_REVIEW_EXPECTATION_ALREADY_LOCKED":
        "an expected response is already recorded; it cannot be replaced, "
        "only corrected by appending",
    "EXPERT_REVIEW_REVEAL_REQUIRED":
        "the system result must be revealed before a decision is recorded",
    "EXPERT_REVIEW_RESULT_ALREADY_REVEALED":
        "the result was revealed once; a second reveal cannot recalculate it",
    "EXPERT_REVIEW_ALREADY_COMPLETED":
        "this review is complete and immutable",
    "EXPERT_REVIEW_INVALIDATED":
        "this review was invalidated and cannot be continued",
    "EXPERT_REVIEW_RELEASE_MISMATCH":
        "the pinned release no longer matches the one this review began under",
    "EXPERT_REVIEW_CASE_MANIFEST_MISMATCH":
        "the case manifest hash no longer matches the pinned one",
    "EXPERT_REVIEW_PROTOCOL_MISMATCH":
        "the protocol hash no longer matches the pinned one",
    "EXPERT_REVIEW_AUDIT_FAILED":
        "the audit event could not be appended, so the governed action was "
        "rolled back",
    "EXPERT_REVIEW_INVALID_TRANSITION":
        "the requested move is not permitted from the current state",
    "EXPERT_REVIEW_ROLE_REQUIRED":
        "only the exact EXPERT_REVIEWER role may act; ADMIN does not imply it",
    "EXPERT_REVIEW_CASE_NOT_ELIGIBLE":
        "only an EXPERT_HOLDOUT case may be assigned for blind review",
    "EXPERT_REVIEW_FORGED_FIELD":
        "the request supplied a field the server owns",
    "EXPERT_REVIEW_PERMIT_INVALID":
        "no assignment-scoped permit authorises this actor to read this "
        "case's payload at this stage",
}
