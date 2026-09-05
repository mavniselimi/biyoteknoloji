# -*- coding: utf-8 -*-
"""Adapters supplying WP-21 from completed reviews (WP-22).

Two adapters, and the reason there are two rather than one is the whole
distinction this work package protects:

- :class:`CompletedReviewJudgmentPort` supplies the reviewer's **locked
  pre-reveal expectation** to WP-21's ``ReferenceJudgmentPort``. That is what
  concordance and holdout-pass metrics compare the system against.
- :class:`CompletedReviewDecisionPort` supplies the reviewer's **post-reveal
  AGREE / PARTIAL / DISAGREE** and ratings, which is what the expert
  agreement and Likert metrics summarise.

A codebase where one object served both would eventually report a curator's
prediction as an expert's endorsement.

**Which expectation is supplied.** The one the *reveal* pinned - not the
latest revision. A reviewer may append a correction after seeing the answer,
and it may be entirely sincere; it is not what they predicted, and the metric
that consumes it is measuring prediction.

**Eligibility is checked, and a mismatch refuses.** Every consumed record must
match the plan on case, role, protocol hash and all six release identities. A
record that disagrees is not skipped - the benchmark input is refused, because
a run that quietly dropped disagreeing records would report a denominator that
does not match the set it names.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.expert_review.errors import ExpertReviewError
from pgx.expert_review.models import (CompletionDecision, ExpectedResponse,
                                      RevealRecord, ReviewAssignment)
from pgx.expert_review.vocabulary import ReviewState

__all__ = [
    "CompletedReview",
    "CompletedReviewDecisionPort",
    "CompletedReviewJudgmentPort",
    "EligibilityError",
    "eligible_completed_reviews",
]


class EligibilityError(ExpertReviewError):
    """A completed review does not match the benchmark it was offered to.

    Its own type because the remedy differs from every other refusal here: not
    "the reviewer may not act" but "this evidence is about something else".
    """

    default_code = "EXPERT_REVIEW_RELEASE_MISMATCH"


class CompletedReview:
    """One completed review, assembled from its four immutable records.

    Constructed only for reviews in state ``COMPLETED`` with a reveal and a
    completion present. An incomplete one cannot be built, so there is no
    object a metric could receive that represents a half-finished review.
    """

    def __init__(self, assignment: ReviewAssignment,
                 expectation: ExpectedResponse, reveal: RevealRecord,
                 completion: CompletionDecision) -> None:
        if assignment.state is not ReviewState.COMPLETED:
            raise EligibilityError(
                "only a COMPLETED review is evidence; state is %s"
                % assignment.state.value,
                code="EXPERT_REVIEW_INVALID_TRANSITION")
        if reveal.expectation_revision_hash != expectation.revision_hash():
            raise EligibilityError(
                "the supplied expectation is not the revision the reveal "
                "pinned; a post-reveal amendment is not what the reviewer "
                "predicted",
                code="EXPERT_REVIEW_INVALID_TRANSITION")
        if completion.reveal_id != reveal.reveal_id:
            raise EligibilityError(
                "the completion does not follow this reveal",
                code="EXPERT_REVIEW_INVALID_TRANSITION")
        self.assignment = assignment
        self.expectation = expectation
        self.reveal = reveal
        self.completion = completion

    @property
    def case_id(self) -> str:
        return self.assignment.case_id

    @property
    def role(self) -> str:
        return self.assignment.case_role

    def matches(self, pins: Mapping[str, str]) -> Tuple[bool, str]:
        """Whether this review measures what the plan says it measures."""
        mine = dict(self.assignment.pins())
        for field_name in sorted(pins):
            if field_name not in mine:
                continue
            if mine[field_name] != pins[field_name]:
                return False, field_name
        return True, ""

    def provenance(self) -> str:
        """What WP-21 records about where a judgment came from.

        Names the protocol and the review, never the reviewer. A metric
        artifact is published, and a reviewer's name in one would identify who
        judged which case - which is exactly the linkage a blind protocol
        exists to keep out of the open.
        """
        return ("WP-22 blind expert review %s under protocol %s; expectation "
                "revision %s locked before reveal"
                % (self.assignment.review_id,
                   self.assignment.protocol_version,
                   self.expectation.revision_id))

    def to_public_summary(self) -> Dict[str, Any]:
        """Aggregate-safe fields only. No expectation, no note, no reviewer."""
        return {
            "review_id": self.assignment.review_id,
            "case_role": self.role,
            "decision": self.completion.decision.value,
            "rated_dimensions": sorted(self.completion.rating_map()),
            "protocol_version": self.assignment.protocol_version,
            "release_public_id": self.assignment.release_public_id,
        }


def eligible_completed_reviews(reviews: Sequence[CompletedReview], *,
                               pins: Mapping[str, str],
                               case_role: Optional[str] = None
                               ) -> Tuple[CompletedReview, ...]:
    """Filter by role and **refuse** on any pin mismatch.

    The asymmetry is deliberate. Filtering by role is selection: a review of an
    expert-holdout case is simply not evidence about the internal-holdout
    partition, and leaving it out changes nothing about what remains. A pin
    mismatch is different - it means somebody offered this benchmark a record
    about another release, and continuing without it would produce a report
    whose denominator does not match the set it names.
    """
    selected: List[CompletedReview] = []
    for review in reviews:
        matched, field_name = review.matches(pins)
        if not matched:
            raise EligibilityError(
                "a completed review disagrees with the benchmark on %s. The "
                "run is refused rather than the record dropped: a silently "
                "excluded record makes the denominator describe a different "
                "set than the one the report names." % field_name,
                details={"field": field_name,
                         "review_id": review.assignment.review_id})
        if case_role is not None and review.role != case_role:
            continue
        selected.append(review)
    return tuple(selected)


class CompletedReviewJudgmentPort:
    """WP-21's ``ReferenceJudgmentPort``, backed by locked expectations.

    Supplies the expectation the reveal pinned. Reviews whose role does not
    match the requested partition are filtered out; reviews that disagree with
    the pinned release are refused.
    """

    def __init__(self, reviews: Sequence[CompletedReview] = (), *,
                 pins: Optional[Mapping[str, str]] = None) -> None:
        self._reviews = tuple(reviews)
        self._pins = dict(pins or {})

    def judgments(self, *, role) -> Mapping[str, Any]:
        role_name = getattr(role, "value", str(role))
        eligible = eligible_completed_reviews(self._reviews, pins=self._pins,
                                              case_role=role_name)
        return {review.case_id:
                review.expectation.to_reference_judgment(
                    review.case_id, review.provenance())
                for review in eligible}


class CompletedReviewDecisionPort:
    """WP-21's expert-decision source. Separate from the judgment port.

    Returns post-reveal decisions and ratings. Nothing here can be mistaken
    for an expected response: the two travel through different methods on
    different classes, and the metric that consumes each names which it wants.
    """

    def __init__(self, reviews: Sequence[CompletedReview] = (), *,
                 pins: Optional[Mapping[str, str]] = None) -> None:
        self._reviews = tuple(reviews)
        self._pins = dict(pins or {})

    def decisions(self, *, role) -> Mapping[str, str]:
        """``{case_id: AGREE|PARTIAL|DISAGREE}`` for eligible reviews."""
        role_name = getattr(role, "value", str(role))
        eligible = eligible_completed_reviews(self._reviews, pins=self._pins,
                                              case_role=role_name)
        return {review.case_id: review.completion.decision.value
                for review in eligible}

    def ratings(self, *, role) -> Mapping[str, Mapping[str, int]]:
        """``{case_id: {dimension: value}}`` for eligible reviews.

        A case with no ratings is absent rather than present-and-empty, so a
        Likert denominator counts completed ratings and not completed reviews.
        """
        role_name = getattr(role, "value", str(role))
        eligible = eligible_completed_reviews(self._reviews, pins=self._pins,
                                              case_role=role_name)
        return {review.case_id: dict(review.completion.rating_map())
                for review in eligible if review.completion.ratings}
