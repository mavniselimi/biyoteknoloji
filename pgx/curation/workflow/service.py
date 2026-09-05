# -*- coding: utf-8 -*-
"""The curation workflow service (WP-10).

Every operation follows the same shape, and the shape is the design:

1. resolve the actor's roles from the injected provider - never from an
   argument;
2. read the work item and check the requested transition against its state;
3. evaluate whatever gates the operation requires, failing closed;
4. write the new row (revision, review, adjudication) - all append-only;
5. move the work item with a **guarded update** that must affect exactly one
   row;
6. append the audit event **in the same unit of work**;
7. commit once.

Steps 5 and 6 are the ones that matter under concurrency. The guarded update
matches on id, expected status and expected version together, so two reviewers
holding the same version cannot both succeed: the second matches zero rows and
is refused. And because the audit event is written inside the same
transaction, a committed change without its event is not reachable - if
anything raises, the whole unit of work rolls back and there is no event
either.

The service performs no scientific judgement. It refuses acts, records
decisions humans made, and never supplies a decision of its own.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import (Any, Callable, Dict, List, Mapping, Optional, Sequence,
                    Tuple)

from pgx.curation.vocabulary import ConflictState, CurationRole
from pgx.curation.workflow.errors import (ActorError, AuditIntegrityError,
                                          ConcurrencyError, GateBlockedError,
                                          ImmutableRevisionError,
                                          InvalidTransitionError,
                                          RoleViolationError, WorkflowError)
from pgx.curation.workflow.models import (AdjudicationRecord,
                                          CurationRevision, CurationReview,
                                          CurationSubmission,
                                          CurationWorkItem,
                                          EvidenceSelectionSnapshot,
                                          LEGACY_MIGRATION_TAG,
                                          ProvenanceVerification,
                                          ReviewDecision,
                                          WorkflowTransitionResult)
from pgx.curation.workflow.policy import (GateResult, WorkflowPolicy,
                                          evaluate_curated_gates)
from pgx.curation.workflow.roles import ActorContext, RoleProvider, require_role
from pgx.domain.enums import AuditAction, CurationStatus

__all__ = ["CurationWorkflowService"]

#: Which audit action each operation records. One per operation, so an audit
#: query can answer "who approved this" without parsing prose.
_ACTIONS = {
    "import": AuditAction.CURATION_WORK_ITEM_IMPORTED,
    "revise": AuditAction.CURATION_REVISION_CREATED,
    "submit": AuditAction.CURATION_REVISION_SUBMITTED,
    ReviewDecision.APPROVE: AuditAction.CURATION_APPROVED,
    ReviewDecision.REJECT: AuditAction.CURATION_REJECTED,
    ReviewDecision.REQUEST_CHANGES: AuditAction.CURATION_CHANGES_REQUESTED,
    ReviewDecision.REFER_TO_ADJUDICATION:
        AuditAction.CURATION_REFERRED_TO_ADJUDICATION,
    "adjudicate": AuditAction.CURATION_ADJUDICATED,
}


class CurationWorkflowService:
    """Moves curation work items, and refuses to move them wrongly."""

    def __init__(self, uow_factory: Callable[[], Any],
                 role_provider: RoleProvider,
                 policy: WorkflowPolicy,
                 clock: Optional[Callable[[], _dt.datetime]] = None) -> None:
        self._uow_factory = uow_factory
        self._roles = role_provider
        self._policy = policy
        self._clock = clock or (
            lambda: _dt.datetime.now(tz=_dt.timezone.utc))

    # -- helpers --------------------------------------------------------

    def _actor(self, actor_id: str) -> ActorContext:
        """Resolve roles, never accept them.

        The single place an ActorContext enters this service. A caller that
        wanted to supply roles would have to change this line, which is the
        point: self-elevation should require an edit somebody reviews.

        The class itself is refused alongside instances. Passing the class is
        a plausible slip, and without this it would fall through to a role
        lookup whose message talks about missing assignments rather than about
        the actual mistake.
        """
        if isinstance(actor_id, ActorContext) or actor_id is ActorContext:
            raise ActorError(
                "pass an actor id, not an ActorContext. Roles are resolved by "
                "the injected provider so that a caller cannot assert its own "
                "permissions.")
        return self._roles.for_actor(actor_id)

    def _load(self, uow, work_item_id: str) -> CurationWorkItem:
        item = uow.work_items.get(work_item_id)
        if item is None:
            raise WorkflowError("no curation work item %r" % work_item_id)
        return item

    @staticmethod
    def _require_affected_one(affected: int, item: CurationWorkItem,
                              expected_version: int,
                              expected_status: CurationStatus) -> None:
        """Exactly one row, or the caller's view was stale.

        Zero means somebody moved first. More than one is impossible against a
        primary key and would mean the store is not what it claims, so it is
        refused rather than accepted as success.
        """
        if affected == 1:
            return
        if affected == 0:
            raise ConcurrencyError(
                "work item %s was not at %s/version %d when this operation "
                "ran; somebody else moved it first"
                % (item.work_item_id, expected_status.value, expected_version),
                expected_version=expected_version,
                actual_version=item.version,
                expected_status=expected_status.value,
                actual_status=item.status.value)
        raise AuditIntegrityError(
            "a guarded update matched %d rows for one work item id; the store "
            "is not behaving as a keyed table" % affected)

    # -- operations -----------------------------------------------------

    def import_legacy_work_item(self, *, actor_id: str,
                                work_item: CurationWorkItem,
                                reason: str) -> WorkflowTransitionResult:
        """Create one RAW work item from a legacy proposal.

        Imports arrive RAW with no revision, no reviewer and no approval. The
        legacy values ride along under ``legacy_values`` as unreviewed input,
        never as a conclusion.
        """
        actor = self._actor(actor_id)
        if work_item.status is not CurationStatus.RAW:
            raise InvalidTransitionError(
                "an imported legacy work item starts RAW; %s would assert a "
                "review nobody performed" % work_item.status.value,
                requested=work_item.status.value)
        if LEGACY_MIGRATION_TAG not in work_item.tags:
            raise WorkflowError(
                "an imported work item carries the %s tag, so its origin stays "
                "answerable by query" % LEGACY_MIGRATION_TAG)

        with self._uow_factory() as uow:
            uow.work_items.add(work_item)
            event_id = uow.audit.record(
                action=_ACTIONS["import"].value, actor=actor.actor_id,
                object_type="curation_work_item",
                object_id=work_item.work_item_id,
                occurred_at=self._clock(), reason=reason,
                metadata={"legacy_proposal_id": work_item.legacy_proposal_id,
                          "tags": list(work_item.tags)})
            uow.commit()
        return WorkflowTransitionResult(
            work_item=work_item, previous_status=CurationStatus.RAW,
            previous_version=work_item.version,
            audit_action=_ACTIONS["import"].value, audit_event_id=event_id)

    def create_revision(self, *, actor_id: str, work_item_id: str,
                        expected_version: int,
                        payload: Mapping[str, Any],
                        evidence: EvidenceSelectionSnapshot,
                        note: str = "") -> WorkflowTransitionResult:
        """Add an immutable revision to a RAW work item.

        The work item stays RAW - adding a revision is not submitting one -
        but its version still advances, so a reviewer who read version 3
        cannot act on a revision added afterwards without noticing.
        """
        actor = self._actor(actor_id)
        require_role(actor, CurationRole.SCIENTIFIC_CURATOR, "author a revision")

        with self._uow_factory() as uow:
            item = self._load(uow, work_item_id)
            item.require_editable()
            if item.version != expected_version:
                raise ConcurrencyError(
                    "work item %s is at version %d, not %d"
                    % (work_item_id, item.version, expected_version),
                    expected_version=expected_version,
                    actual_version=item.version)

            number = uow.revisions.next_revision_number(work_item_id)
            revision = CurationRevision(
                work_item_id=work_item_id, revision_number=number,
                parent_revision_id=item.current_revision_id,
                payload=payload,
                protocol_version=self._policy.protocol_version,
                protocol_content_hash=self._policy.protocol_content_hash,
                evidence=evidence, authored_by=actor.actor_id,
                authored_by_role=CurationRole.SCIENTIFIC_CURATOR,
                authored_at=self._clock())
            revision_id = uow.revisions.add(revision)

            affected = uow.work_items.guarded_update(
                work_item_id, expected_status=CurationStatus.RAW,
                expected_version=expected_version,
                new_status=CurationStatus.RAW,
                current_revision_id=revision_id,
                updated_at=self._clock())
            self._require_affected_one(affected, item, expected_version,
                                       CurationStatus.RAW)

            event_id = uow.audit.record(
                action=_ACTIONS["revise"].value, actor=actor.actor_id,
                object_type="curation_revision", object_id=revision_id,
                occurred_at=self._clock(), reason=note or None,
                metadata={"work_item_id": work_item_id,
                          "revision_number": number,
                          "revision_content_hash": revision.content_hash()})
            # Re-read rather than reconstruct: a hand-built copy is a second
            # opinion about what was written, and this is what the caller
            # will see next.
            stored = self._load(uow, work_item_id)
            written = uow.revisions.get(revision_id)
            uow.commit()

        return WorkflowTransitionResult(
            work_item=stored, previous_status=CurationStatus.RAW,
            previous_version=expected_version,
            audit_action=_ACTIONS["revise"].value, audit_event_id=event_id,
            revision=written or revision)

    def submit(self, *, actor_id: str, work_item_id: str,
               revision_id: str, expected_version: int,
               note: str = "") -> WorkflowTransitionResult:
        """Put one revision up for review: RAW -> UNDER_REVIEW.

        From here the revision is frozen. Nothing in this service edits a
        submitted revision, and the repositories offer no update to do it
        with.
        """
        actor = self._actor(actor_id)
        require_role(actor, CurationRole.SCIENTIFIC_CURATOR,
                     "submit a revision")

        with self._uow_factory() as uow:
            item = self._load(uow, work_item_id)
            item.require_transition(CurationStatus.UNDER_REVIEW)
            revision = uow.revisions.get(revision_id)
            if revision is None or revision.work_item_id != work_item_id:
                raise WorkflowError(
                    "revision %r does not belong to work item %r"
                    % (revision_id, work_item_id))
            if revision.authored_by.strip().lower() != \
                    actor.actor_id.strip().lower():
                raise RoleViolationError(
                    "%s did not author revision %s and cannot submit it"
                    % (actor.actor_id, revision_id))

            submission = CurationSubmission(
                work_item_id=work_item_id, revision_id=revision_id,
                revision_content_hash=revision.content_hash(),
                submitted_by=actor.actor_id,
                submitted_by_role=CurationRole.SCIENTIFIC_CURATOR,
                submitted_at=self._clock(), note=note)

            affected = uow.work_items.guarded_update(
                work_item_id, expected_status=CurationStatus.RAW,
                expected_version=expected_version,
                new_status=CurationStatus.UNDER_REVIEW,
                current_revision_id=revision_id,
                submitted_revision_id=revision_id, updated_at=self._clock())
            self._require_affected_one(affected, item, expected_version,
                                       CurationStatus.RAW)

            event_id = uow.audit.record(
                action=_ACTIONS["submit"].value, actor=actor.actor_id,
                object_type="curation_work_item", object_id=work_item_id,
                occurred_at=self._clock(), reason=note or None,
                metadata=submission.content_identity())
            moved = self._load(uow, work_item_id)
            uow.commit()

        return WorkflowTransitionResult(
            work_item=moved, previous_status=CurationStatus.RAW,
            previous_version=expected_version,
            audit_action=_ACTIONS["submit"].value, audit_event_id=event_id,
            revision=revision)

    def gate_status(self, *, work_item_id: str,
                    reviewer_actor_id: Optional[str] = None,
                    conflict_state: Optional[ConflictState] = None,
                    conflict_material: Optional[bool] = None,
                    rationale_complete: Optional[bool] = None,
                    expected_version: Optional[int] = None) -> Dict[str, Any]:
        """Evaluate the gates without attempting a transition.

        Read-only and safe to call at any time. It is what a form shows a
        curator before they submit, and what the CLI reports for a blocked
        legacy item, so nobody has to attempt an approval to discover why it
        would fail.
        """
        with self._uow_factory() as uow:
            item = self._load(uow, work_item_id)
            revision = (uow.revisions.get(item.submitted_revision_id
                                          or item.current_revision_id or "")
                        if (item.submitted_revision_id
                            or item.current_revision_id) else None)
            provenance = uow.provenance.latest_for_work_item(work_item_id)

        if revision is None:
            return {
                "work_item_id": work_item_id,
                "status": item.status.value,
                "version": item.version,
                "gates": None,
                "blocked_reason": ("this work item has no revision, so there "
                                   "is no conclusion to evaluate gates "
                                   "against"),
                "policy": self._policy.to_json(),
            }

        reviewer = None
        if reviewer_actor_id:
            try:
                reviewer = self._actor(reviewer_actor_id)
            except ActorError:
                reviewer = None

        result = evaluate_curated_gates(
            self._policy, revision, reviewer=reviewer,
            author_actor_id=revision.authored_by, provenance=provenance,
            conflict_state=conflict_state, conflict_material=conflict_material,
            rationale_complete=rationale_complete,
            expected_version=(expected_version if expected_version is not None
                              else item.version),
            actual_version=item.version)
        payload = result.to_json()
        payload["work_item_id"] = work_item_id
        payload["status"] = item.status.value
        payload["version"] = item.version
        payload["policy"] = self._policy.to_json()
        return payload

    def record_provenance_verification(
        self, *, actor_id: str, work_item_id: str,
        verification: ProvenanceVerification) -> str:
        """Store a steward's trace verification.

        Deliberately not a transition. Verifying provenance opens one gate; it
        does not move the work item, and a steward cannot advance a
        conclusion by confirming its plumbing.
        """
        actor = self._actor(actor_id)
        require_role(actor, CurationRole.DATA_PROVENANCE_STEWARD,
                     "verify provenance")
        if verification.verified_by.strip().lower() != \
                actor.actor_id.strip().lower():
            raise RoleViolationError(
                "the verification names %s but the actor is %s"
                % (verification.verified_by, actor.actor_id))
        with self._uow_factory() as uow:
            self._load(uow, work_item_id)
            verification_id = uow.provenance.add(
                verification, work_item_id=work_item_id)
            uow.commit()
        return verification_id

    def review(self, *, actor_id: str, work_item_id: str,
               revision_id: str, expected_version: int,
               decision: ReviewDecision, rationale: str,
               findings: Sequence[str] = (),
               conflict_state: Optional[ConflictState] = None,
               conflict_material: Optional[bool] = None,
               rationale_complete: Optional[bool] = None
               ) -> WorkflowTransitionResult:
        """Record one independent review and move the work item accordingly.

        An ``APPROVE`` runs every gate first. The other three decisions do
        not: refusing a conclusion, asking for changes, or referring a dispute
        are all things a reviewer must be able to do precisely *when* the
        gates are shut. Only reaching ``CURATED`` requires them open.
        """
        actor = self._actor(actor_id)
        if not isinstance(decision, ReviewDecision):
            raise WorkflowError("decision must be a ReviewDecision")
        require_role(actor, CurationRole.INDEPENDENT_SCIENTIFIC_REVIEWER,
                     "review a curation")

        with self._uow_factory() as uow:
            item = self._load(uow, work_item_id)
            if item.status is not CurationStatus.UNDER_REVIEW:
                raise InvalidTransitionError(
                    "only an UNDER_REVIEW work item can be reviewed; %s is %s"
                    % (work_item_id, item.status.value),
                    current=item.status.value, requested=decision.value)
            if item.submitted_revision_id != revision_id:
                raise WorkflowError(
                    "revision %s is not the one under review (%s)"
                    % (revision_id, item.submitted_revision_id))
            if item.version != expected_version:
                # Diagnosis, not enforcement. The guarded UPDATE below is what
                # actually prevents two people deciding one version; this line
                # exists so the loser is told "somebody moved first" rather
                # than being handed a gate report whose single closed gate is
                # a staleness they cannot fix by improving the science.
                raise ConcurrencyError(
                    "work item %s is at version %d, not %d; somebody else "
                    "acted on it first"
                    % (work_item_id, item.version, expected_version),
                    expected_version=expected_version,
                    actual_version=item.version,
                    expected_status=CurationStatus.UNDER_REVIEW.value,
                    actual_status=item.status.value)
            revision = uow.revisions.get(revision_id)
            if revision is None:
                raise WorkflowError("no revision %r" % revision_id)

            target = {
                ReviewDecision.APPROVE: CurationStatus.CURATED,
                ReviewDecision.REJECT: CurationStatus.REJECTED,
                ReviewDecision.REQUEST_CHANGES: CurationStatus.RAW,
                ReviewDecision.REFER_TO_ADJUDICATION:
                    CurationStatus.UNDER_REVIEW,
            }[decision]
            if target is not CurationStatus.UNDER_REVIEW:
                item.require_transition(target)

            if decision is ReviewDecision.APPROVE:
                provenance = uow.provenance.latest_for_work_item(work_item_id)
                evaluate_curated_gates(
                    self._policy, revision, reviewer=actor,
                    author_actor_id=revision.authored_by,
                    provenance=provenance, conflict_state=conflict_state,
                    conflict_material=conflict_material,
                    rationale_complete=rationale_complete,
                    expected_version=expected_version,
                    actual_version=item.version).raise_if_blocked()

            review = CurationReview(
                work_item_id=work_item_id, revision_id=revision_id,
                revision_content_hash=revision.content_hash(),
                decision=decision, reviewed_by=actor.actor_id,
                reviewed_by_role=CurationRole.INDEPENDENT_SCIENTIFIC_REVIEWER,
                reviewed_at=self._clock(),
                author_actor_id=revision.authored_by, rationale=rationale,
                protocol_content_hash=revision.protocol_content_hash,
                evidence_build_content_hash=(
                    revision.evidence.evidence_build_content_hash),
                findings=tuple(findings))
            review_id = uow.reviews.add(
                review, work_item_version=expected_version)

            # A referral leaves the item UNDER_REVIEW but still advances the
            # version, so the referral is recorded and a stale caller cannot
            # act as though it had not happened.
            affected = uow.work_items.guarded_update(
                work_item_id, expected_status=CurationStatus.UNDER_REVIEW,
                expected_version=expected_version, new_status=target,
                current_revision_id=item.current_revision_id,
                submitted_revision_id=(
                    None if target is CurationStatus.RAW
                    else item.submitted_revision_id),
                updated_at=self._clock())
            self._require_affected_one(affected, item, expected_version,
                                       CurationStatus.UNDER_REVIEW)

            event_id = uow.audit.record(
                action=_ACTIONS[decision].value, actor=actor.actor_id,
                object_type="curation_work_item", object_id=work_item_id,
                occurred_at=self._clock(), reason=rationale,
                metadata={"review_id": review_id, "revision_id": revision_id,
                          "decision": decision.value,
                          "revision_content_hash": revision.content_hash(),
                          "author_actor_id": revision.authored_by})
            moved = self._load(uow, work_item_id)
            uow.commit()

        return WorkflowTransitionResult(
            work_item=moved, previous_status=CurationStatus.UNDER_REVIEW,
            previous_version=expected_version,
            audit_action=_ACTIONS[decision].value, audit_event_id=event_id,
            revision=revision, review=review)

    def adjudicate(self, *, actor_id: str, work_item_id: str,
                   revision_id: str, expected_version: int,
                   decision: ReviewDecision, rationale: str,
                   curator_position: Mapping[str, Any],
                   reviewer_position: Mapping[str, Any],
                   disputed_evidence_uuids: Sequence[str] = (),
                   conflict_state: Optional[ConflictState] = None,
                   conflict_material: Optional[bool] = None,
                   rationale_complete: Optional[bool] = None
                   ) -> WorkflowTransitionResult:
        """Settle a referred dispute, preserving both positions.

        An adjudicated ``APPROVE`` runs the same gates as a reviewed one. An
        adjudicator resolves a disagreement between two people; they do not
        acquire the power to approve over a quarantined build or an unapproved
        protocol, because those blockers are not what the two disagreed about.
        """
        actor = self._actor(actor_id)
        require_role(actor, CurationRole.ADJUDICATOR, "adjudicate a curation")

        with self._uow_factory() as uow:
            item = self._load(uow, work_item_id)
            if item.status is not CurationStatus.UNDER_REVIEW:
                raise InvalidTransitionError(
                    "adjudication settles a review in progress; %s is %s"
                    % (work_item_id, item.status.value),
                    current=item.status.value, requested=decision.value)
            if item.version != expected_version:
                # Diagnosis, not enforcement. The guarded UPDATE below is what
                # actually prevents two people deciding one version; this line
                # exists so the loser is told "somebody moved first" rather
                # than being handed a gate report whose single closed gate is
                # a staleness they cannot fix by improving the science.
                raise ConcurrencyError(
                    "work item %s is at version %d, not %d; somebody else "
                    "acted on it first"
                    % (work_item_id, item.version, expected_version),
                    expected_version=expected_version,
                    actual_version=item.version,
                    expected_status=CurationStatus.UNDER_REVIEW.value,
                    actual_status=item.status.value)
            revision = uow.revisions.get(revision_id)
            if revision is None or revision.work_item_id != work_item_id:
                raise WorkflowError(
                    "revision %r does not belong to work item %r"
                    % (revision_id, work_item_id))

            record = AdjudicationRecord(
                work_item_id=work_item_id, revision_id=revision_id,
                revision_content_hash=revision.content_hash(),
                adjudicated_by=actor.actor_id,
                adjudicated_by_role=CurationRole.ADJUDICATOR,
                adjudicated_at=self._clock(), decision=decision,
                rationale=rationale, curator_position=curator_position,
                reviewer_position=reviewer_position,
                disputed_evidence_uuids=tuple(disputed_evidence_uuids))

            target = record.resulting_state
            item.require_transition(target)

            if decision is ReviewDecision.APPROVE:
                provenance = uow.provenance.latest_for_work_item(work_item_id)
                evaluate_curated_gates(
                    self._policy, revision, reviewer=actor,
                    author_actor_id=revision.authored_by,
                    provenance=provenance, conflict_state=conflict_state,
                    conflict_material=conflict_material,
                    rationale_complete=rationale_complete,
                    expected_version=expected_version,
                    actual_version=item.version).raise_if_blocked()

            adjudication_id = uow.adjudications.add(
                record, work_item_version=expected_version)
            affected = uow.work_items.guarded_update(
                work_item_id, expected_status=CurationStatus.UNDER_REVIEW,
                expected_version=expected_version, new_status=target,
                current_revision_id=item.current_revision_id,
                submitted_revision_id=(
                    None if target is CurationStatus.RAW
                    else item.submitted_revision_id),
                updated_at=self._clock())
            self._require_affected_one(affected, item, expected_version,
                                       CurationStatus.UNDER_REVIEW)

            event_id = uow.audit.record(
                action=_ACTIONS["adjudicate"].value, actor=actor.actor_id,
                object_type="curation_work_item", object_id=work_item_id,
                occurred_at=self._clock(), reason=rationale,
                metadata={"adjudication_id": adjudication_id,
                          "revision_id": revision_id,
                          "decision": decision.value,
                          "curator_actor_id": curator_position.get("actor_id"),
                          "reviewer_actor_id":
                              reviewer_position.get("actor_id")})
            moved = self._load(uow, work_item_id)
            uow.commit()

        return WorkflowTransitionResult(
            work_item=moved, previous_status=CurationStatus.UNDER_REVIEW,
            previous_version=expected_version,
            audit_action=_ACTIONS["adjudicate"].value, audit_event_id=event_id,
            revision=revision, adjudication=record)

    def history(self, work_item_id: str) -> Dict[str, Any]:
        """Everything that happened to one work item, in order.

        Revisions, reviews and adjudications together. Reviews are listed in
        full rather than only the governing one: a review that asked for
        changes before an approval is part of how the conclusion was reached.
        """
        with self._uow_factory() as uow:
            item = self._load(uow, work_item_id)
            revisions = list(uow.revisions.list_for_work_item(work_item_id))
            reviews = list(uow.reviews.list_for_work_item(work_item_id))
            adjudications = list(
                uow.adjudications.list_for_work_item(work_item_id))
        return {
            "work_item": item.to_json(),
            "revisions": [r.to_json() for r in revisions],
            "reviews": [r.to_json() for r in reviews],
            "adjudications": [
                a.to_json() if hasattr(a, "to_json") else dict(a)
                for a in adjudications],
            "revision_count": len(revisions),
            "review_count": len(reviews),
        }
