# -*- coding: utf-8 -*-
"""The immutable review records (WP-22).

Seven frozen dataclasses. None has an update method, a mutable field or a
setter, and the repository layer has no update or delete path either - so
immutability is a property of the type rather than a discipline the caller
must keep.

The record that matters most is :class:`ExpectedResponse`. It is the reviewer's
judgement *before* they saw anything, and everything downstream - the reveal
that pins it, the metrics that consume it - is only meaningful because it
cannot have been written afterwards. Hence: a server-generated timestamp (a
client-supplied one would let a reviewer backdate), a content hash, and a
revision number that only ever increases through appended corrections.

``ExpectedResponse`` and :class:`CompletionDecision` are deliberately different
types. One is a prediction, the other is a comparison. A codebase where the
same object could serve as both is one where a curator's expected answer
eventually gets reported as an expert's endorsement.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from pgx.domain.hashing import sha256_digest
from pgx.expert_review.errors import ExpertReviewError, ForgedFieldError
from pgx.expert_review.vocabulary import (CorrectionKind, ExpertDecision,
                                          InvalidationReason, LIKERT_DIMENSIONS,
                                          LIKERT_MAXIMUM, LIKERT_MINIMUM,
                                          RationaleCode, ReviewState)

__all__ = [
    "PROHIBITED_REQUEST_FIELDS",
    "PROHIBITED_EXPECTATION_FIELDS",
    "CompletionDecision",
    "Correction",
    "ExpectedResponse",
    "RatingValue",
    "ReviewAssignment",
    "RevealRecord",
    "assert_no_forged_fields",
    "chain_hash",
]

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,63}$")

#: Fields the server owns. A request carrying any of them is refused outright
#: rather than having them stripped: a caller who tried to set their own
#: timestamp has told you something, and silently ignoring it loses that.
PROHIBITED_REQUEST_FIELDS: Tuple[str, ...] = (
    "actor", "actor_id", "reviewer", "reviewer_id", "reviewer_actor",
    "role", "reviewer_role", "principal",
    "recorded_at", "revealed_at", "completed_at", "occurred_at", "timestamp",
    "created_at", "server_time",
    "status", "state", "review_state",
    "release_manifest_hash", "software_hash", "dataset_content_hash",
    "ruleset_content_hash", "case_manifest_hash", "protocol_hash",
    "expectation_hash", "reveal_hash", "content_hash", "chain_hash",
    "previous_hash", "revision", "audit", "audit_event", "sequence",
)

#: Fields an expected response may never carry. The first four are WP-18's
#: prohibited list; the rest are WP-22's own, and every one of them is a way
#: for a clinical directive to enter a record that is later published as an
#: aggregate.
PROHIBITED_EXPECTATION_FIELDS: Tuple[str, ...] = (
    "expected_result", "gold_standard", "ground_truth", "answer_key",
    "recommendation", "recommended_drug", "preferred_medication",
    "dose", "dosage", "dose_adjustment", "treatment", "therapy",
    "prescription", "patient", "patient_narrative", "clinical_directive",
    "free_text_advice", "instruction",
)


def assert_no_forged_fields(payload: Mapping[str, Any],
                            prohibited: Sequence[str] = ()) -> None:
    """Refuse a request body that supplied a field the server owns."""
    supplied = {str(key).lower() for key in payload}
    offending = sorted(supplied & set(prohibited or PROHIBITED_REQUEST_FIELDS))
    if offending:
        raise ForgedFieldError(
            "the request supplied server-owned field(s): %s. Identity, "
            "timing, status and every hash come from the authenticated "
            "principal and the pinned assignment."
            % ", ".join(offending),
            details={"fields": offending})


def chain_hash(previous: Optional[str], payload: Mapping[str, Any]) -> str:
    """One link. ``previous`` is ``None`` only for the first event.

    Including the predecessor's hash in each link is what makes deletion and
    reordering detectable: a chain missing its third event has a fourth whose
    ``previous_hash`` names something no longer present, and a reordered chain
    has two links whose recomputed hashes no longer match what is stored.
    """
    return sha256_digest({"previous": previous, "payload": dict(payload)})


def _require_digest(value: object, name: str) -> str:
    text = str(value or "")
    if not _DIGEST.match(text):
        raise ExpertReviewError("%s must be a canonical sha256:<hex>" % name,
                                code="EXPERT_REVIEW_INVALID_TRANSITION")
    return text


def _require_id(value: object, name: str) -> str:
    text = str(value or "")
    if not _ID.match(text):
        raise ExpertReviewError("%s must be a stable identifier" % name,
                                code="EXPERT_REVIEW_INVALID_TRANSITION")
    return text


def _require_utc(value: _dt.datetime, name: str) -> _dt.datetime:
    if not isinstance(value, _dt.datetime) or value.tzinfo is None:
        raise ExpertReviewError("%s must be a timezone-aware UTC datetime"
                                % name,
                                code="EXPERT_REVIEW_INVALID_TRANSITION")
    return value.astimezone(_dt.timezone.utc)


@dataclass(frozen=True, slots=True)
class ReviewAssignment:
    """One reviewer, one case, one release, one protocol. Immutable.

    Everything a later reader needs to say what this review was *about* is
    pinned here at assignment time. A review whose subject could drift is a
    review whose result describes nothing in particular.
    """

    assignment_id: str
    review_id: str
    case_id: str
    case_role: str
    reviewer_actor: str
    reviewer_role: str
    protocol_version: str
    protocol_hash: str
    release_public_id: str
    release_manifest_hash: str
    software_version: str
    software_hash: str
    dataset_public_id: str
    dataset_content_hash: str
    ruleset_public_id: str
    ruleset_content_hash: str
    case_manifest_hash: str
    assigned_at: _dt.datetime
    state: ReviewState = ReviewState.ASSIGNED

    def __post_init__(self) -> None:
        for name in ("assignment_id", "review_id", "case_id"):
            object.__setattr__(self, name,
                               _require_id(getattr(self, name), name))
        for name in ("protocol_hash", "release_manifest_hash",
                     "software_hash", "dataset_content_hash",
                     "ruleset_content_hash", "case_manifest_hash"):
            object.__setattr__(self, name,
                               _require_digest(getattr(self, name), name))
        if self.case_role != "EXPERT_HOLDOUT":
            raise ExpertReviewError(
                "only an EXPERT_HOLDOUT case may be assigned for blind "
                "review; %s cases either shaped the software or belong to a "
                "different protocol" % self.case_role,
                code="EXPERT_REVIEW_CASE_NOT_ELIGIBLE")
        if self.reviewer_role != "EXPERT_REVIEWER":
            raise ExpertReviewError(
                "the assigned role is exactly EXPERT_REVIEWER; ADMIN does "
                "not imply it",
                code="EXPERT_REVIEW_ROLE_REQUIRED")
        object.__setattr__(self, "assigned_at",
                           _require_utc(self.assigned_at, "assigned_at"))
        if not isinstance(self.state, ReviewState):
            raise ExpertReviewError("state is a ReviewState",
                                    code="EXPERT_REVIEW_INVALID_TRANSITION")

    def pins(self) -> Mapping[str, str]:
        """Everything an observation or record must echo back unchanged."""
        return {
            "protocol_hash": self.protocol_hash,
            "release_public_id": self.release_public_id,
            "release_manifest_hash": self.release_manifest_hash,
            "software_version": self.software_version,
            "software_hash": self.software_hash,
            "dataset_public_id": self.dataset_public_id,
            "dataset_content_hash": self.dataset_content_hash,
            "ruleset_public_id": self.ruleset_public_id,
            "ruleset_content_hash": self.ruleset_content_hash,
            "case_manifest_hash": self.case_manifest_hash,
        }

    def with_state(self, state: ReviewState) -> "ReviewAssignment":
        """A new assignment object at a new state. The old one is unchanged.

        Not a mutation. The service persists a fresh row and appends an audit
        event; this returns the value the caller should now hold.
        """
        from dataclasses import replace
        return replace(self, state=state)

    def to_json(self) -> Dict[str, Any]:
        payload = {
            "assignment_id": self.assignment_id,
            "review_id": self.review_id,
            "case_id": self.case_id,
            "case_role": self.case_role,
            "reviewer_actor": self.reviewer_actor,
            "reviewer_role": self.reviewer_role,
            "protocol_version": self.protocol_version,
            "assigned_at": self.assigned_at.isoformat().replace("+00:00", "Z"),
            "state": self.state.value,
        }
        payload.update(self.pins())
        return payload


@dataclass(frozen=True, slots=True)
class ExpectedResponse:
    """What the reviewer expected, recorded before they saw anything.

    The structured fields mirror WP-21's ``ReferenceJudgment`` so a completed
    review can supply one without translation - but this is not that class.
    A ``ReferenceJudgment`` is what WP-21 consumes; this is the governed
    record of a human act, with a reviewer, a protocol and a chain position.

    ``rationale_codes`` is a controlled list rather than prose. Free text in a
    blinded expectation is where a dose instruction would eventually appear.
    """

    revision_id: str
    review_id: str
    revision: int
    expected_attention_level: str
    expected_coverage_status: str
    expected_coverage_reason: Optional[str] = None
    expected_rule_id: Optional[str] = None
    requires_traceable_evidence: bool = True
    rationale_codes: Tuple[str, ...] = field(default_factory=tuple)
    #: Bounded reviewer note. Scanned against the prohibited list, so it can
    #: hold "the CYP2C19 axis is indeterminate here" and not a dose.
    reviewer_note: str = ""
    recorded_at: _dt.datetime = None  # type: ignore[assignment]
    previous_hash: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "revision_id",
                           _require_id(self.revision_id, "revision_id"))
        object.__setattr__(self, "review_id",
                           _require_id(self.review_id, "review_id"))
        if int(self.revision) < 1:
            raise ExpertReviewError("revisions start at 1",
                                    code="EXPERT_REVIEW_INVALID_TRANSITION")
        object.__setattr__(self, "revision", int(self.revision))
        for code in self.rationale_codes:
            if code not in {item.value for item in RationaleCode}:
                raise ExpertReviewError(
                    "unknown rationale code %r" % code,
                    code="EXPERT_REVIEW_INVALID_TRANSITION")
        object.__setattr__(self, "rationale_codes",
                           tuple(sorted(set(self.rationale_codes))))
        note = str(self.reviewer_note or "").strip()[:1000]
        lowered = note.lower()
        for forbidden in PROHIBITED_EXPECTATION_FIELDS:
            if forbidden.replace("_", " ") in lowered:
                raise ExpertReviewError(
                    "an expected response records what the reviewer expected "
                    "the system to output. It is not a place for a treatment "
                    "recommendation, a dose or a clinical directive.",
                    code="EXPERT_REVIEW_FORGED_FIELD")
        object.__setattr__(self, "reviewer_note", note)
        object.__setattr__(self, "recorded_at",
                           _require_utc(self.recorded_at, "recorded_at"))

    def content(self) -> Dict[str, Any]:
        """The judgement itself, without identity or timing.

        Hashed as the expectation's content so two revisions that say the same
        thing are recognisably the same judgement even though they are
        different records.
        """
        return {
            "expected_attention_level": self.expected_attention_level,
            "expected_coverage_status": self.expected_coverage_status,
            "expected_coverage_reason": self.expected_coverage_reason,
            "expected_rule_id": self.expected_rule_id,
            "requires_traceable_evidence": self.requires_traceable_evidence,
            "rationale_codes": list(self.rationale_codes),
            "reviewer_note": self.reviewer_note,
        }

    def content_hash(self) -> str:
        return sha256_digest(self.content())

    def revision_hash(self) -> str:
        """What a reveal pins. Covers identity, content, timing and chain."""
        return chain_hash(self.previous_hash, {
            "revision_id": self.revision_id,
            "review_id": self.review_id,
            "revision": self.revision,
            "content_hash": self.content_hash(),
            "recorded_at": self.recorded_at.isoformat().replace("+00:00", "Z"),
        })

    def to_reference_judgment(self, case_id: str, provenance: str):
        """Adapt to WP-21's contract. A translation, not a reclassification.

        The judgement travels; the reviewer's identity does not. WP-21
        consumes an expected answer with provenance, and provenance here names
        the protocol and the review rather than the person - a metric artifact
        is published, and a reviewer's name in one would identify who judged
        which case.
        """
        from pgx.validation.benchmark_models import ReferenceJudgment
        return ReferenceJudgment(
            case_id=case_id,
            expected_attention_level=self.expected_attention_level,
            expected_coverage_status=self.expected_coverage_status,
            expected_coverage_reason=self.expected_coverage_reason,
            expected_rule_id=self.expected_rule_id,
            requires_evidence=self.requires_traceable_evidence,
            provenance=provenance,
            recorded_at=self.recorded_at)

    def to_json(self) -> Dict[str, Any]:
        payload = {
            "revision_id": self.revision_id,
            "review_id": self.review_id,
            "revision": self.revision,
            "recorded_at": self.recorded_at.isoformat().replace("+00:00", "Z"),
            "content_hash": self.content_hash(),
            "revision_hash": self.revision_hash(),
            "previous_hash": self.previous_hash,
        }
        payload.update(self.content())
        return payload


@dataclass(frozen=True, slots=True)
class RevealRecord:
    """The one-way door, and what it pinned when it opened.

    ``expectation_revision_hash`` is the field that makes the whole protocol
    checkable afterwards. It names the exact revision the reviewer had locked
    at the moment of reveal - so a correction appended later cannot
    retroactively become the thing they predicted, however sincerely it was
    meant.
    """

    reveal_id: str
    review_id: str
    expectation_revision_id: str
    expectation_revision_hash: str
    result_output_hash: str
    result_attention_level: str
    result_coverage_status: str
    result_coverage_reason: Optional[str]
    result_firing_rule_id: Optional[str]
    result_finding_count: int
    result_traceable_finding_count: int
    revealed_at: _dt.datetime
    previous_hash: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("reveal_id", "review_id", "expectation_revision_id"):
            object.__setattr__(self, name,
                               _require_id(getattr(self, name), name))
        for name in ("expectation_revision_hash", "result_output_hash"):
            object.__setattr__(self, name,
                               _require_digest(getattr(self, name), name))
        object.__setattr__(self, "revealed_at",
                           _require_utc(self.revealed_at, "revealed_at"))
        if self.result_traceable_finding_count > self.result_finding_count:
            raise ExpertReviewError(
                "traceable findings exceed findings",
                code="EXPERT_REVIEW_INVALID_TRANSITION")

    def result(self) -> Dict[str, Any]:
        """The revealed system output. Never returned before this record."""
        return {
            "attention_level": self.result_attention_level,
            "coverage_status": self.result_coverage_status,
            "coverage_reason": self.result_coverage_reason,
            "firing_rule_id": self.result_firing_rule_id,
            "finding_count": self.result_finding_count,
            "traceable_finding_count": self.result_traceable_finding_count,
            "output_hash": self.result_output_hash,
        }

    def reveal_hash(self) -> str:
        return chain_hash(self.previous_hash, {
            "reveal_id": self.reveal_id,
            "review_id": self.review_id,
            "expectation_revision_hash": self.expectation_revision_hash,
            "result": self.result(),
            "revealed_at": self.revealed_at.isoformat().replace("+00:00", "Z"),
        })

    def to_json(self) -> Dict[str, Any]:
        payload = {
            "reveal_id": self.reveal_id,
            "review_id": self.review_id,
            "expectation_revision_id": self.expectation_revision_id,
            "expectation_revision_hash": self.expectation_revision_hash,
            "revealed_at": self.revealed_at.isoformat().replace("+00:00", "Z"),
            "reveal_hash": self.reveal_hash(),
            "previous_hash": self.previous_hash,
        }
        payload.update(self.result())
        return payload


@dataclass(frozen=True, slots=True)
class RatingValue:
    """One optional Likert rating on one declared dimension."""

    dimension: str
    value: int

    def __post_init__(self) -> None:
        if self.dimension not in LIKERT_DIMENSIONS:
            raise ExpertReviewError(
                "unknown rating dimension %r; dimensions are declared before "
                "any review exists" % self.dimension,
                code="EXPERT_REVIEW_INVALID_TRANSITION")
        value = int(self.value)
        if not LIKERT_MINIMUM <= value <= LIKERT_MAXIMUM:
            raise ExpertReviewError(
                "a rating is between %d and %d" % (LIKERT_MINIMUM,
                                                   LIKERT_MAXIMUM),
                code="EXPERT_REVIEW_INVALID_TRANSITION")
        object.__setattr__(self, "value", value)

    def to_json(self) -> Dict[str, Any]:
        return {"dimension": self.dimension, "value": self.value}


@dataclass(frozen=True, slots=True)
class CompletionDecision:
    """The post-reveal comparison. Not the expectation, and not a score."""

    completion_id: str
    review_id: str
    reveal_id: str
    decision: ExpertDecision
    ratings: Tuple[RatingValue, ...] = field(default_factory=tuple)
    reviewer_note: str = ""
    completed_at: _dt.datetime = None  # type: ignore[assignment]
    previous_hash: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("completion_id", "review_id", "reveal_id"):
            object.__setattr__(self, name,
                               _require_id(getattr(self, name), name))
        if not isinstance(self.decision, ExpertDecision):
            raise ExpertReviewError(
                "the decision is exactly AGREE, PARTIAL or DISAGREE",
                code="EXPERT_REVIEW_INVALID_TRANSITION")
        seen = set()
        for rating in self.ratings:
            if not isinstance(rating, RatingValue):
                raise ExpertReviewError("ratings are RatingValue values",
                                        code="EXPERT_REVIEW_INVALID_TRANSITION")
            if rating.dimension in seen:
                raise ExpertReviewError(
                    "one rating per dimension; two would have to be "
                    "reconciled by something, and nothing here may reconcile "
                    "a reviewer's opinion",
                    code="EXPERT_REVIEW_INVALID_TRANSITION")
            seen.add(rating.dimension)
        object.__setattr__(self, "ratings",
                           tuple(sorted(self.ratings,
                                        key=lambda item: item.dimension)))
        object.__setattr__(self, "reviewer_note",
                           str(self.reviewer_note or "").strip()[:1000])
        object.__setattr__(self, "completed_at",
                           _require_utc(self.completed_at, "completed_at"))

    def rating_map(self) -> Mapping[str, int]:
        return {item.dimension: item.value for item in self.ratings}

    def completion_hash(self) -> str:
        return chain_hash(self.previous_hash, {
            "completion_id": self.completion_id,
            "review_id": self.review_id,
            "reveal_id": self.reveal_id,
            "decision": self.decision.value,
            "ratings": [item.to_json() for item in self.ratings],
            "reviewer_note": self.reviewer_note,
            "completed_at":
                self.completed_at.isoformat().replace("+00:00", "Z"),
        })

    def to_json(self) -> Dict[str, Any]:
        return {
            "completion_id": self.completion_id,
            "review_id": self.review_id,
            "reveal_id": self.reveal_id,
            "decision": self.decision.value,
            "ratings": [item.to_json() for item in self.ratings],
            "reviewer_note": self.reviewer_note,
            "completed_at":
                self.completed_at.isoformat().replace("+00:00", "Z"),
            "completion_hash": self.completion_hash(),
            "previous_hash": self.previous_hash,
        }


@dataclass(frozen=True, slots=True)
class Correction:
    """An appended amendment. The record it refers to is never touched.

    ``target_hash`` names what is being corrected, so a chain reader can see
    what a correction was about without the corrected record having changed.

    A correction appended *after* a reveal is annotation only. The service
    enforces that; this type records which side of the reveal it fell on so
    the fact survives into the artifact.
    """

    correction_id: str
    review_id: str
    target_hash: str
    kind: CorrectionKind
    reason_code: str
    actor: str
    actor_role: str
    recorded_at: _dt.datetime
    #: Present only for kinds that carry one, and never for a post-reveal
    #: correction to an expectation.
    replacement: Optional[Mapping[str, Any]] = None
    after_reveal: bool = False
    previous_hash: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("correction_id", "review_id"):
            object.__setattr__(self, name,
                               _require_id(getattr(self, name), name))
        object.__setattr__(self, "target_hash",
                           _require_digest(self.target_hash, "target_hash"))
        if not isinstance(self.kind, CorrectionKind):
            raise ExpertReviewError("kind is a CorrectionKind",
                                    code="EXPERT_REVIEW_INVALID_TRANSITION")
        if self.actor_role != "EXPERT_REVIEWER":
            raise ExpertReviewError(
                "only the assigned expert reviewer may append a correction",
                code="EXPERT_REVIEW_ROLE_REQUIRED")
        object.__setattr__(self, "recorded_at",
                           _require_utc(self.recorded_at, "recorded_at"))
        if self.replacement is not None:
            assert_no_forged_fields(self.replacement,
                                    PROHIBITED_EXPECTATION_FIELDS)
            object.__setattr__(self, "replacement", dict(self.replacement))

    def correction_hash(self) -> str:
        return chain_hash(self.previous_hash, {
            "correction_id": self.correction_id,
            "review_id": self.review_id,
            "target_hash": self.target_hash,
            "kind": self.kind.value,
            "reason_code": self.reason_code,
            "actor": self.actor,
            "replacement": self.replacement,
            "after_reveal": self.after_reveal,
            "recorded_at": self.recorded_at.isoformat().replace("+00:00", "Z"),
        })

    def to_json(self) -> Dict[str, Any]:
        return {
            "correction_id": self.correction_id,
            "review_id": self.review_id,
            "target_hash": self.target_hash,
            "kind": self.kind.value,
            "reason_code": self.reason_code,
            "actor": self.actor,
            "actor_role": self.actor_role,
            "recorded_at": self.recorded_at.isoformat().replace("+00:00", "Z"),
            "replacement": (None if self.replacement is None
                            else dict(self.replacement)),
            "after_reveal": self.after_reveal,
            "correction_hash": self.correction_hash(),
            "previous_hash": self.previous_hash,
        }
