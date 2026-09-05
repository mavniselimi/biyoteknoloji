# -*- coding: utf-8 -*-
"""The workflow's immutable value objects (WP-10).

Every type here is a frozen dataclass with a content hash. That is not
ceremony: a review pins the exact revision hash it read, so "was this reviewed"
is answerable by comparing bytes rather than by trusting a foreign key to have
pointed at the same content all along.

The lifecycle these objects move through:

    RAW  --save-->  revision 1, 2, 3 ...   (each immutable once written)
    RAW  --submit revision N-->  UNDER_REVIEW   (that revision frozen forever)
    UNDER_REVIEW --APPROVE-->          CURATED     (immutable)
    UNDER_REVIEW --REJECT-->           REJECTED    (immutable)
    UNDER_REVIEW --REQUEST_CHANGES-->  RAW         (new revision required)
    UNDER_REVIEW --REFER_TO_ADJUDICATION--> UNDER_REVIEW, adjudication pending

WP-09's ``DRAFT`` is not a persisted state here. It is what a revision's
content is while the work item is ``RAW``, which is why the persisted initial
state is ``RAW`` and the mapping is written down rather than assumed.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from pgx.curation.errors import CurationError
from pgx.curation.vocabulary import CurationRole
from pgx.curation.workflow.errors import (ImmutableRevisionError,
                                          InvalidTransitionError,
                                          WorkflowError)
from pgx.curation.workflow.roles import ActorContext
from pgx.domain.enums import CurationStatus
from pgx.domain.hashing import ensure_utc, sha256_digest

__all__ = [
    "ADJUDICATION_DECISIONS",
    "LEGACY_MIGRATION_TAG",
    "TERMINAL_STATES",
    "WORKFLOW_MODEL_VERSION",
    "AdjudicationRecord",
    "CurationRevision",
    "CurationReview",
    "CurationSubmission",
    "CurationWorkItem",
    "EvidenceSelectionSnapshot",
    "ProvenanceVerification",
    "ReviewDecision",
    "WorkflowTransitionResult",
    "allowed_transitions",
]

WORKFLOW_MODEL_VERSION = "pgx-curation-workflow/1"

#: Every work item created from a WP-08 proposal carries this. It is what
#: makes "these 1,559 came from the legacy seed" answerable by query rather
#: than by remembering.
LEGACY_MIGRATION_TAG = "LEGACY_MIGRATION"

#: States from which nothing moves. A correction to a CURATED conclusion is a
#: new work item citing this one, never an edit of it.
TERMINAL_STATES = (CurationStatus.CURATED, CurationStatus.REJECTED)


class ReviewDecision(str, Enum):
    """What an independent reviewer concluded about one submitted revision."""

    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    REJECT = "REJECT"
    REFER_TO_ADJUDICATION = "REFER_TO_ADJUDICATION"

    def __str__(self) -> str:
        return self.value


#: What an adjudicator may conclude. Deliberately not a superset of
#: ReviewDecision: an adjudicator settles a dispute, and referring it onward
#: again would be a loop with no exit.
ADJUDICATION_DECISIONS = (ReviewDecision.APPROVE, ReviewDecision.REJECT,
                          ReviewDecision.REQUEST_CHANGES)


def allowed_transitions() -> Mapping[CurationStatus, Tuple[CurationStatus, ...]]:
    """The state machine, as data.

    Written once here so the service, the database constraint and the
    documentation all describe the same machine, and a test can compare them.
    """
    return {
        CurationStatus.RAW: (CurationStatus.UNDER_REVIEW,),
        CurationStatus.UNDER_REVIEW: (CurationStatus.CURATED,
                                      CurationStatus.REJECTED,
                                      CurationStatus.RAW),
        CurationStatus.CURATED: (),
        CurationStatus.REJECTED: (),
    }


def _text(value: Any, name: str, minimum: int = 1) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise WorkflowError("%s must be text of at least %d characters"
                            % (name, minimum))
    return value.strip()


@dataclass(frozen=True)
class EvidenceSelectionSnapshot:
    """The evidence a revision selected, frozen at the moment it was written.

    A snapshot rather than a live query. If the selection were re-read at
    review time, a reviewer could approve a set that differs from what the
    author chose, and neither would know.
    """

    evidence_record_uuids: Tuple[str, ...]
    excluded_record_uuids: Tuple[str, ...] = ()
    evidence_build_key: str = ""
    evidence_build_content_hash: str = ""
    dataset_public_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_record_uuids",
                           tuple(self.evidence_record_uuids))
        object.__setattr__(self, "excluded_record_uuids",
                           tuple(self.excluded_record_uuids))
        if not self.evidence_record_uuids:
            raise CurationError(
                "a revision selects at least one evidence record; a "
                "conclusion with none has nothing to interpret")
        overlap = set(self.evidence_record_uuids) & set(
            self.excluded_record_uuids)
        if overlap:
            raise CurationError(
                "%s appear as both included and excluded"
                % ", ".join(sorted(overlap)))

    def content_identity(self) -> Dict[str, Any]:
        return {
            "evidence_record_uuids": sorted(self.evidence_record_uuids),
            "excluded_record_uuids": sorted(self.excluded_record_uuids),
            "evidence_build_key": self.evidence_build_key,
            "evidence_build_content_hash": self.evidence_build_content_hash,
            "dataset_public_id": self.dataset_public_id,
        }

    def to_json(self) -> Dict[str, Any]:
        return self.content_identity()


@dataclass(frozen=True)
class ProvenanceVerification:
    """A steward's statement that the cited evidence traces back to raw bytes.

    Separate from the scientific review on purpose. The steward confirms the
    chain is intact; that is not a statement that the conclusion drawn from it
    is right, and a workflow that let one stand in for the other would be
    treating a plumbing check as a scientific one.
    """

    verified_by: str
    verified_by_role: CurationRole
    verified_at: _dt.datetime
    evidence_record_uuids: Tuple[str, ...]
    all_traces_verified: bool
    problems: Tuple[str, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        _text(self.verified_by, "verified_by", 2)
        if self.verified_by_role is not CurationRole.DATA_PROVENANCE_STEWARD:
            raise WorkflowError(
                "provenance verification is the steward's act; %s cannot "
                "perform it" % getattr(self.verified_by_role, "value",
                                       self.verified_by_role))
        object.__setattr__(self, "verified_at",
                           ensure_utc(self.verified_at, "verified_at"))
        object.__setattr__(self, "evidence_record_uuids",
                           tuple(self.evidence_record_uuids))
        object.__setattr__(self, "problems", tuple(self.problems))
        if self.all_traces_verified and self.problems:
            raise WorkflowError(
                "a verification cannot report problems and claim every trace "
                "verified; one of the two is wrong")

    def content_identity(self) -> Dict[str, Any]:
        return {
            "verified_by": self.verified_by,
            "verified_by_role": self.verified_by_role.value,
            "verified_at": self.verified_at.isoformat().replace("+00:00", "Z"),
            "evidence_record_uuids": sorted(self.evidence_record_uuids),
            "all_traces_verified": self.all_traces_verified,
            "problems": list(self.problems),
            "note": self.note,
        }

    def to_json(self) -> Dict[str, Any]:
        return self.content_identity()


@dataclass(frozen=True)
class CurationRevision:
    """One immutable version of a curation payload.

    Pins everything a later reader needs to know what was being claimed and
    against what: the WP-09 payload, the protocol version and hash it was
    written under, the evidence build, the selected records, and who wrote it.

    Immutability is structural. There is no setter, no ``with_`` helper that
    changes content, and the content hash covers every pinned field, so an
    altered revision is a different revision.
    """

    work_item_id: str
    revision_number: int
    parent_revision_id: Optional[str]
    payload: Mapping[str, Any]
    protocol_version: str
    protocol_content_hash: str
    evidence: EvidenceSelectionSnapshot
    authored_by: str
    authored_by_role: CurationRole
    authored_at: _dt.datetime
    revision_id: Optional[str] = None
    workflow_model_version: str = WORKFLOW_MODEL_VERSION

    def __post_init__(self) -> None:
        _text(self.work_item_id, "work_item_id")
        if isinstance(self.revision_number, bool) or \
                not isinstance(self.revision_number, int) or \
                self.revision_number < 1:
            raise WorkflowError("revision_number counts from 1")
        if self.revision_number == 1 and self.parent_revision_id is not None:
            raise WorkflowError(
                "the first revision has no parent; a parent here would claim "
                "a lineage that does not exist")
        if self.revision_number > 1 and not (self.parent_revision_id or ""):
            raise WorkflowError(
                "revision %d must name the revision it was derived from, or "
                "its lineage is unreconstructible" % self.revision_number)
        if not isinstance(self.payload, Mapping):
            raise WorkflowError("payload must be a mapping")
        _text(self.protocol_version, "protocol_version")
        _text(self.protocol_content_hash, "protocol_content_hash")
        if not isinstance(self.evidence, EvidenceSelectionSnapshot):
            raise WorkflowError("evidence must be an EvidenceSelectionSnapshot")
        _text(self.authored_by, "authored_by", 2)
        if not isinstance(self.authored_by_role, CurationRole):
            raise WorkflowError("authored_by_role must be a CurationRole")
        if self.authored_by_role is not CurationRole.SCIENTIFIC_CURATOR:
            raise WorkflowError(
                "a revision is authored by a scientific curator; %s may not "
                "author one" % self.authored_by_role.value)
        object.__setattr__(self, "authored_at",
                           ensure_utc(self.authored_at, "authored_at"))
        object.__setattr__(self, "payload", dict(self.payload))

    def content_identity(self) -> Dict[str, Any]:
        return {
            "workflow_model_version": self.workflow_model_version,
            "work_item_id": self.work_item_id,
            "revision_number": self.revision_number,
            "parent_revision_id": self.parent_revision_id,
            "payload": dict(self.payload),
            "protocol_version": self.protocol_version,
            "protocol_content_hash": self.protocol_content_hash,
            "evidence": self.evidence.content_identity(),
            "authored_by": self.authored_by,
            "authored_by_role": self.authored_by_role.value,
        }

    def content_hash(self) -> str:
        """Excludes ``authored_at`` and the assigned id.

        Two revisions with identical content written a minute apart are the
        same claim, and a hash that disagreed would make "did this change"
        unanswerable.
        """
        return sha256_digest(self.content_identity())

    def to_json(self) -> Dict[str, Any]:
        payload = self.content_identity()
        payload["revision_id"] = self.revision_id
        payload["authored_at"] = self.authored_at.isoformat().replace(
            "+00:00", "Z")
        payload["content_hash"] = self.content_hash()
        return payload


@dataclass(frozen=True)
class CurationSubmission:
    """The act of putting one revision up for review.

    Records which revision, by whom, and its hash at that moment. The hash is
    what makes tampering detectable: a revision edited after submission no
    longer matches what the submission says was submitted.
    """

    work_item_id: str
    revision_id: str
    revision_content_hash: str
    submitted_by: str
    submitted_by_role: CurationRole
    submitted_at: _dt.datetime
    note: str = ""

    def __post_init__(self) -> None:
        for name in ("work_item_id", "revision_id", "revision_content_hash"):
            _text(getattr(self, name), name)
        _text(self.submitted_by, "submitted_by", 2)
        if self.submitted_by_role is not CurationRole.SCIENTIFIC_CURATOR:
            raise WorkflowError(
                "a revision is submitted by its scientific curator; %s may "
                "not submit one" % self.submitted_by_role.value)
        object.__setattr__(self, "submitted_at",
                           ensure_utc(self.submitted_at, "submitted_at"))

    def content_identity(self) -> Dict[str, Any]:
        return {
            "work_item_id": self.work_item_id,
            "revision_id": self.revision_id,
            "revision_content_hash": self.revision_content_hash,
            "submitted_by": self.submitted_by,
            "submitted_by_role": self.submitted_by_role.value,
            "note": self.note,
        }

    def to_json(self) -> Dict[str, Any]:
        payload = self.content_identity()
        payload["submitted_at"] = self.submitted_at.isoformat().replace(
            "+00:00", "Z")
        return payload


@dataclass(frozen=True)
class CurationReview:
    """One independent reviewer's decision about one submitted revision.

    Pins the revision **and its hash**, so a review is provably about the
    content the reviewer saw rather than about whatever that revision id now
    points to. Pins the author too, so author/reviewer separation is checkable
    from the review alone, without joining back to the revision.

    No review overwrites another. Two reviews of one revision are two records;
    which one governed is decided by the work item's state transitions, not by
    one silently replacing the other.
    """

    work_item_id: str
    revision_id: str
    revision_content_hash: str
    decision: ReviewDecision
    reviewed_by: str
    reviewed_by_role: CurationRole
    reviewed_at: _dt.datetime
    author_actor_id: str
    rationale: str
    protocol_content_hash: str
    evidence_build_content_hash: str
    findings: Tuple[str, ...] = ()
    review_id: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("work_item_id", "revision_id", "revision_content_hash",
                     "protocol_content_hash", "evidence_build_content_hash"):
            _text(getattr(self, name), name)
        if not isinstance(self.decision, ReviewDecision):
            raise WorkflowError("decision must be a ReviewDecision")
        _text(self.reviewed_by, "reviewed_by", 2)
        _text(self.author_actor_id, "author_actor_id", 2)
        _text(self.rationale, "rationale", 24)
        if not isinstance(self.reviewed_by_role, CurationRole):
            raise WorkflowError("reviewed_by_role must be a CurationRole")
        if self.reviewed_by_role not in (
                CurationRole.INDEPENDENT_SCIENTIFIC_REVIEWER,
                CurationRole.ADJUDICATOR):
            raise WorkflowError(
                "%s cannot review a scientific conclusion"
                % self.reviewed_by_role.value)
        # Separation checked on the record itself, not only at the call site.
        # A review row that failed this could not have been legitimate however
        # it was created.
        if self.reviewed_by.strip().lower() == \
                self.author_actor_id.strip().lower():
            raise WorkflowError(
                "%s authored this revision and cannot review it; one person "
                "checking their own conclusion is not an independent review"
                % self.reviewed_by)
        object.__setattr__(self, "reviewed_at",
                           ensure_utc(self.reviewed_at, "reviewed_at"))
        object.__setattr__(self, "findings", tuple(self.findings))

    @property
    def resulting_state(self) -> CurationStatus:
        """Where this decision moves the work item.

        ``REFER_TO_ADJUDICATION`` leaves it ``UNDER_REVIEW``: referring a
        dispute is not deciding it, and moving the item would suggest somebody
        had.
        """
        return {
            ReviewDecision.APPROVE: CurationStatus.CURATED,
            ReviewDecision.REJECT: CurationStatus.REJECTED,
            ReviewDecision.REQUEST_CHANGES: CurationStatus.RAW,
            ReviewDecision.REFER_TO_ADJUDICATION: CurationStatus.UNDER_REVIEW,
        }[self.decision]

    def content_identity(self) -> Dict[str, Any]:
        return {
            "work_item_id": self.work_item_id,
            "revision_id": self.revision_id,
            "revision_content_hash": self.revision_content_hash,
            "decision": self.decision.value,
            "reviewed_by": self.reviewed_by,
            "reviewed_by_role": self.reviewed_by_role.value,
            "author_actor_id": self.author_actor_id,
            "rationale": self.rationale,
            "findings": list(self.findings),
            "protocol_content_hash": self.protocol_content_hash,
            "evidence_build_content_hash": self.evidence_build_content_hash,
        }

    def content_hash(self) -> str:
        return sha256_digest(self.content_identity())

    def to_json(self) -> Dict[str, Any]:
        payload = self.content_identity()
        payload["review_id"] = self.review_id
        payload["reviewed_at"] = self.reviewed_at.isoformat().replace(
            "+00:00", "Z")
        payload["resulting_state"] = self.resulting_state.value
        payload["content_hash"] = self.content_hash()
        return payload


@dataclass(frozen=True)
class AdjudicationRecord:
    """A third named person settling a dispute, with both positions preserved.

    ``curator_position`` and ``reviewer_position`` are required and are stored
    in full. An adjudication that replaced them would erase the disagreement
    it was called to settle, and nobody could later check whether the
    adjudicator was right either.

    The adjudicator may not be either party. Somebody breaking a tie they are
    a side of is not adjudication.
    """

    work_item_id: str
    revision_id: str
    revision_content_hash: str
    adjudicated_by: str
    adjudicated_by_role: CurationRole
    adjudicated_at: _dt.datetime
    decision: ReviewDecision
    rationale: str
    curator_position: Mapping[str, Any]
    reviewer_position: Mapping[str, Any]
    disputed_evidence_uuids: Tuple[str, ...] = ()
    adjudication_id: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("work_item_id", "revision_id", "revision_content_hash"):
            _text(getattr(self, name), name)
        _text(self.adjudicated_by, "adjudicated_by", 2)
        _text(self.rationale, "rationale", 24)
        if self.adjudicated_by_role is not CurationRole.ADJUDICATOR:
            raise WorkflowError(
                "adjudication is the adjudicator's act; %s may not perform it"
                % self.adjudicated_by_role.value)
        if self.decision not in ADJUDICATION_DECISIONS:
            raise WorkflowError(
                "an adjudicator settles a dispute; %s would refer it onward "
                "again" % self.decision.value)
        for name in ("curator_position", "reviewer_position"):
            value = getattr(self, name)
            if not isinstance(value, Mapping) or not value:
                raise WorkflowError(
                    "%s must be preserved in full; an adjudication that drops "
                    "a position erases the disagreement it settled" % name)
            object.__setattr__(self, name, dict(value))
        curator = str(self.curator_position.get("actor_id") or "").lower()
        reviewer = str(self.reviewer_position.get("actor_id") or "").lower()
        if self.adjudicated_by.strip().lower() in (curator, reviewer):
            raise WorkflowError(
                "%s is a party to this dispute and cannot adjudicate it"
                % self.adjudicated_by)
        object.__setattr__(self, "adjudicated_at",
                           ensure_utc(self.adjudicated_at, "adjudicated_at"))
        object.__setattr__(self, "disputed_evidence_uuids",
                           tuple(self.disputed_evidence_uuids))

    @property
    def resulting_state(self) -> CurationStatus:
        return {
            ReviewDecision.APPROVE: CurationStatus.CURATED,
            ReviewDecision.REJECT: CurationStatus.REJECTED,
            ReviewDecision.REQUEST_CHANGES: CurationStatus.RAW,
        }[self.decision]

    def content_identity(self) -> Dict[str, Any]:
        return {
            "work_item_id": self.work_item_id,
            "revision_id": self.revision_id,
            "revision_content_hash": self.revision_content_hash,
            "adjudicated_by": self.adjudicated_by,
            "adjudicated_by_role": self.adjudicated_by_role.value,
            "decision": self.decision.value,
            "rationale": self.rationale,
            "curator_position": dict(self.curator_position),
            "reviewer_position": dict(self.reviewer_position),
            "disputed_evidence_uuids": sorted(self.disputed_evidence_uuids),
        }

    def content_hash(self) -> str:
        return sha256_digest(self.content_identity())

    def to_json(self) -> Dict[str, Any]:
        payload = self.content_identity()
        payload["adjudication_id"] = self.adjudication_id
        payload["adjudicated_at"] = self.adjudicated_at.isoformat().replace(
            "+00:00", "Z")
        payload["resulting_state"] = self.resulting_state.value
        payload["content_hash"] = self.content_hash()
        payload["note"] = (
            "Both original positions are preserved above and are not replaced "
            "by the decision. An adjudication settles which reading the "
            "project adopts; it does not erase the disagreement.")
        return payload


@dataclass(frozen=True)
class CurationWorkItem:
    """One question moving through the workflow.

    ``version`` is the optimistic-concurrency counter, incremented by every
    guarded update. A caller holding version 3 who acts while somebody else
    moved the item to version 4 is refused, so two reviewers cannot both
    decide the same state.

    ``status`` is WP-02's persisted ``CurationStatus``. WP-09's ``DRAFT`` maps
    onto ``RAW``: the protocol's DRAFT describes revision content, and the
    persisted state describes where the item is. They are one state under two
    names, and the mapping is asserted by test rather than assumed.
    """

    work_item_id: str
    status: CurationStatus
    version: int
    question_id: str
    gene_canonical_key: str
    drug_canonical_key: str
    created_at: _dt.datetime
    created_by: str
    current_revision_id: Optional[str] = None
    submitted_revision_id: Optional[str] = None
    tags: Tuple[str, ...] = ()
    legacy_proposal_id: Optional[str] = None
    legacy_values: Mapping[str, Any] = field(default_factory=dict)
    updated_at: Optional[_dt.datetime] = None

    def __post_init__(self) -> None:
        _text(self.work_item_id, "work_item_id")
        if not isinstance(self.status, CurationStatus):
            raise WorkflowError("status must be a CurationStatus")
        if isinstance(self.version, bool) or not isinstance(self.version, int) \
                or self.version < 0:
            raise WorkflowError("version is a non-negative integer")
        for name in ("question_id", "gene_canonical_key",
                     "drug_canonical_key", "created_by"):
            _text(getattr(self, name), name)
        object.__setattr__(self, "created_at",
                           ensure_utc(self.created_at, "created_at"))
        if self.updated_at is not None:
            object.__setattr__(self, "updated_at",
                               ensure_utc(self.updated_at, "updated_at"))
        object.__setattr__(self, "tags", tuple(self.tags))
        object.__setattr__(self, "legacy_values", dict(self.legacy_values))

        if self.status is CurationStatus.UNDER_REVIEW and \
                not (self.submitted_revision_id or ""):
            raise WorkflowError(
                "an UNDER_REVIEW work item names the revision under review; "
                "without it nobody can tell what is being reviewed")
        if self.status in TERMINAL_STATES and \
                not (self.submitted_revision_id or ""):
            raise WorkflowError(
                "a %s work item names the revision that was decided"
                % self.status.value)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATES

    @property
    def is_legacy(self) -> bool:
        return LEGACY_MIGRATION_TAG in self.tags

    def require_transition(self, target: CurationStatus) -> None:
        """Refuse a move this state does not allow.

        Checked here as well as in the service and the database. Three checks
        of one rule is not duplication when the rule is "a decided conclusion
        never silently changes".
        """
        permitted = allowed_transitions()[self.status]
        if target not in permitted:
            raise InvalidTransitionError(
                "a %s work item cannot move to %s; permitted: %s"
                % (self.status.value, target.value,
                   ", ".join(item.value for item in permitted) or "nothing, "
                   "this state is terminal"),
                current=self.status.value, requested=target.value)

    def require_editable(self) -> None:
        """Refuse a new revision unless the item is RAW."""
        if self.status is not CurationStatus.RAW:
            raise ImmutableRevisionError(
                "revisions are added while a work item is RAW; this one is "
                "%s. A correction to a reviewed conclusion is a new revision "
                "after a change request, or a new work item." % self.status.value)

    def to_json(self) -> Dict[str, Any]:
        return {
            "workflow_model_version": WORKFLOW_MODEL_VERSION,
            "work_item_id": self.work_item_id,
            "status": self.status.value,
            "version": self.version,
            "question_id": self.question_id,
            "gene_canonical_key": self.gene_canonical_key,
            "drug_canonical_key": self.drug_canonical_key,
            "current_revision_id": self.current_revision_id,
            "submitted_revision_id": self.submitted_revision_id,
            "tags": list(self.tags),
            "legacy_proposal_id": self.legacy_proposal_id,
            "legacy_values": dict(self.legacy_values),
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "updated_at": (self.updated_at.isoformat().replace("+00:00", "Z")
                           if self.updated_at else None),
            "is_terminal": self.is_terminal,
            "is_legacy": self.is_legacy,
        }


@dataclass(frozen=True)
class WorkflowTransitionResult:
    """What one transition did, including the audit event it wrote.

    The audit event is part of the result rather than a side effect nobody
    sees, so a caller can assert that the change and its record travelled
    together.
    """

    work_item: CurationWorkItem
    previous_status: CurationStatus
    previous_version: int
    audit_action: str
    audit_event_id: Optional[str] = None
    revision: Optional[CurationRevision] = None
    review: Optional[CurationReview] = None
    adjudication: Optional[AdjudicationRecord] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "work_item": self.work_item.to_json(),
            "previous_status": self.previous_status.value,
            "previous_version": self.previous_version,
            "new_status": self.work_item.status.value,
            "new_version": self.work_item.version,
            "audit_action": self.audit_action,
            "audit_event_id": self.audit_event_id,
            "revision": self.revision.to_json() if self.revision else None,
            "review": self.review.to_json() if self.review else None,
            "adjudication": (self.adjudication.to_json()
                             if self.adjudication else None),
        }
