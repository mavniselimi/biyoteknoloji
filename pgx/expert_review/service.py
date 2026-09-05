# -*- coding: utf-8 -*-
"""The blind review workflow (WP-22).

One class, four governed operations, and a great many refusals.

The shape of every operation is the same, and the order within it is the
safety property:

```
1. protocol approved?          no  -> refuse, write nothing
2. exact EXPERT_REVIEWER role? no  -> refuse (ADMIN does not imply it)
3. assignment for this actor?  no  -> refuse with one code for three cases
4. pins still match?           no  -> refuse; the review now measures
                                       something other than what it began on
5. transition permitted?       no  -> refuse
6. inside one unit of work: write the record, write the new state, append the
   audit event. If the audit append fails, the whole thing rolls back.
```

Step 3 returns ``EXPERT_REVIEW_NOT_ASSIGNED`` for "no such case", "not an
expert-holdout case" and "assigned to somebody else" alike. Three distinct
codes would hand anyone with reviewer credentials a way to enumerate the
holdout set by probing, which is the set whose whole value is that nobody has
seen it.

Step 6 is why the audit append is not "best effort". An audit trail that can
be absent for an act that happened is worse than no audit trail, because it
looks complete. So the append is part of the transaction: either both the act
and its record stand, or neither does.

**The service holds no store.** It is constructed with a repository port and a
clock. In this repository no store implementation is wired, so
:meth:`ExpertReviewService.available` is ``False`` and every operation refuses
with ``EXPERT_REVIEW_NOT_AVAILABLE`` before touching anything. That is the
honest production state, and it is a different refusal from every other one
here because nothing was consulted to produce it.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.expert_review.audit import (ReviewAuditEvent, append_event,
                                     verify_chain)
from pgx.expert_review.errors import (AuditChainError, ExpertReviewError,
                                      InvalidTransitionError, NotAssignedError,
                                      PermitError, PinMismatchError,
                                      ReviewUnavailableError)
from pgx.expert_review.models import (CompletionDecision, Correction,
                                      ExpectedResponse, RatingValue,
                                      RevealRecord, ReviewAssignment,
                                      assert_no_forged_fields)
from pgx.expert_review.permits import PayloadPermit, issue_permit
from pgx.expert_review.protocol import ExpertProtocol, require_approved
from pgx.expert_review.vocabulary import (AuditAction, CorrectionKind,
                                          ExpertDecision, InvalidationReason,
                                          ReviewState, may_transition)

__all__ = [
    "ExpertReviewService",
    "ReviewStore",
    "RevealedResultPort",
    "ReviewView",
]


class ReviewStore:
    """Port: persist review records. Never commits; the unit of work does.

    Deliberately narrow, and deliberately without ``update`` or ``delete``.
    A store that offered them would make immutability a rule the service has
    to remember rather than a shape the persistence layer cannot express.
    """

    def assignment_for(self, *, case_id: str, actor: str
                       ) -> Optional[ReviewAssignment]:  # pragma: no cover
        raise NotImplementedError

    def assignments_for_actor(self, actor: str
                              ) -> Sequence[ReviewAssignment]:  # pragma: no cover
        raise NotImplementedError

    def expectations(self, review_id: str
                     ) -> Sequence[ExpectedResponse]:  # pragma: no cover
        raise NotImplementedError

    def reveal(self, review_id: str
               ) -> Optional[RevealRecord]:  # pragma: no cover
        raise NotImplementedError

    def completion(self, review_id: str
                   ) -> Optional[CompletionDecision]:  # pragma: no cover
        raise NotImplementedError

    def corrections(self, review_id: str
                    ) -> Sequence[Correction]:  # pragma: no cover
        raise NotImplementedError

    def audit_chain(self, review_id: str
                    ) -> Sequence[ReviewAuditEvent]:  # pragma: no cover
        raise NotImplementedError

    def append(self, review_id: str, *, record: Any,
               event: ReviewAuditEvent,
               assignment: Optional[ReviewAssignment] = None
               ) -> None:  # pragma: no cover
        """Write one record, its audit event and any state change, atomically."""
        raise NotImplementedError


class RevealedResultPort:
    """Port: the deterministic system result for one case under one release.

    Consulted **only** by :meth:`ExpertReviewService.reveal`, and never
    earlier. The service holds no cached result and the pre-reveal views have
    no field one could occupy, so there is no path by which a result reaches a
    reviewer before their expectation is locked.
    """

    def result_for(self, *, case_id: str, assignment: ReviewAssignment
                   ) -> Mapping[str, Any]:  # pragma: no cover
        raise NotImplementedError


class ReviewView:
    """What a reviewer may see right now. Two shapes, chosen by state.

    A class rather than a dict so the pre-reveal shape physically lacks the
    result fields. A dict would let a caller write ``view["attention_level"]``
    and a template read it; this cannot hold one until :meth:`with_result` has
    been called, and that only happens after a reveal record exists.
    """

    def __init__(self, assignment: ReviewAssignment, *,
                 expectation: Optional[ExpectedResponse] = None,
                 corrections: Sequence[Correction] = (),
                 completion: Optional[CompletionDecision] = None) -> None:
        self.assignment = assignment
        self.expectation = expectation
        self.corrections = tuple(corrections)
        self.completion = completion
        self._result: Optional[Mapping[str, Any]] = None
        self._reveal: Optional[RevealRecord] = None

    @property
    def state(self) -> ReviewState:
        return self.assignment.state

    @property
    def blinded(self) -> bool:
        return self._reveal is None

    @property
    def result(self) -> Optional[Mapping[str, Any]]:
        return None if self._reveal is None else dict(self._result or {})

    @property
    def reveal_record(self) -> Optional[RevealRecord]:
        return self._reveal

    def with_result(self, reveal: RevealRecord) -> "ReviewView":
        self._reveal = reveal
        self._result = reveal.result()
        return self

    def to_json(self) -> Dict[str, Any]:
        """The API/UI shape. Carries result fields only after a reveal."""
        payload: Dict[str, Any] = {
            "review_id": self.assignment.review_id,
            "assignment_id": self.assignment.assignment_id,
            "case_id": self.assignment.case_id,
            "case_role": self.assignment.case_role,
            "state": self.state.value,
            "blinded": self.blinded,
            "release_public_id": self.assignment.release_public_id,
            "protocol_version": self.assignment.protocol_version,
            "expectation_recorded": self.expectation is not None,
            "expectation_revision": (None if self.expectation is None
                                     else self.expectation.revision),
            "expectation_revision_hash": (
                None if self.expectation is None
                else self.expectation.revision_hash()),
            "correction_count": len(self.corrections),
            "decision": (None if self.completion is None
                         else self.completion.decision.value),
        }
        if self._reveal is not None:
            payload["result"] = dict(self._result or {})
            payload["revealed_at"] = self._reveal.revealed_at.isoformat(
            ).replace("+00:00", "Z")
        return payload


class ExpertReviewService:
    """Execute the blind protocol, or refuse. Holds no state between calls."""

    def __init__(self, *, protocol: ExpertProtocol,
                 store: Optional[ReviewStore] = None,
                 result_port: Optional[RevealedResultPort] = None,
                 uow_factory: Optional[Any] = None,
                 clock: Optional[Any] = None,
                 id_factory: Optional[Any] = None) -> None:
        self._protocol = protocol
        self._store = store
        self._results = result_port
        self._uow_factory = uow_factory
        self._clock = clock or (lambda: _dt.datetime.now(_dt.timezone.utc))
        self._new_id = id_factory or self._default_id

    _counter = 0

    @classmethod
    def _default_id(cls, prefix: str) -> str:
        cls._counter += 1
        return "%s-%012d" % (prefix, cls._counter)

    # -- availability ----------------------------------------------------

    @property
    def available(self) -> bool:
        """Whether anything can be attempted at all.

        Both a store and a result port are required. A service with a store
        and no result port could record expectations it could never reveal,
        which would strand reviewers mid-protocol - worse than refusing them
        at the door.
        """
        return self._store is not None and self._results is not None

    @property
    def protocol(self) -> ExpertProtocol:
        return self._protocol

    def gate_state(self) -> Dict[str, Any]:
        """Why this service may or may not run. No store is consulted."""
        return {
            "service_available": self.available,
            "store_available": self._store is not None,
            "result_port_available": self._results is not None,
            "protocol_documented": self._protocol.is_documented,
            "protocol_approved": self._protocol.is_approved,
            "protocol_status": self._protocol.status,
            "refusal_code": (None if (self.available
                                      and self._protocol.is_approved)
                             else ("EXPERT_REVIEW_NOT_AVAILABLE"
                                   if not self.available
                                   else "EXPERT_REVIEW_PROTOCOL_NOT_APPROVED")),
        }

    # -- shared preconditions ---------------------------------------------

    def _require_service(self) -> Tuple[ReviewStore, RevealedResultPort]:
        if not self.available:
            raise ReviewUnavailableError(
                details={"components": [
                    name for name, present in
                    (("review_store", self._store is not None),
                     ("result_port", self._results is not None))
                    if not present]})
        return self._store, self._results  # type: ignore[return-value]

    @staticmethod
    def _require_reviewer_role(role: str) -> None:
        """Exactly EXPERT_REVIEWER. No hierarchy, no implication.

        ADMIN is not a superset here. An administrator who could act as a
        reviewer would be a person whose blind review nobody could distinguish
        from an operational action, and the protocol's independence claim
        rests on being able to.
        """
        if role != "EXPERT_REVIEWER":
            raise ExpertReviewError(
                "only the exact EXPERT_REVIEWER role may act in the blind "
                "protocol; ADMIN does not imply it",
                code="EXPERT_REVIEW_ROLE_REQUIRED")

    def _load_assignment(self, store: ReviewStore, *, case_id: str,
                         actor: str) -> ReviewAssignment:
        assignment = store.assignment_for(case_id=case_id, actor=actor)
        if assignment is None:
            # One code for three conditions, on purpose. See the module
            # docstring: distinguishable refusals are a lookup tool.
            raise NotAssignedError()
        return assignment

    def _check_pins(self, assignment: ReviewAssignment, *,
                    release_manifest_hash: Optional[str] = None,
                    case_manifest_hash: Optional[str] = None) -> None:
        """Refuse when the world moved under an in-progress review."""
        if assignment.protocol_hash != self._protocol.protocol_hash():
            raise PinMismatchError(
                code="EXPERT_REVIEW_PROTOCOL_MISMATCH",
                details={"pinned": "protocol_hash"})
        if release_manifest_hash is not None and \
                assignment.release_manifest_hash != release_manifest_hash:
            raise PinMismatchError(code="EXPERT_REVIEW_RELEASE_MISMATCH",
                                   details={"pinned": "release_manifest_hash"})
        if case_manifest_hash is not None and \
                assignment.case_manifest_hash != case_manifest_hash:
            raise PinMismatchError(
                code="EXPERT_REVIEW_CASE_MANIFEST_MISMATCH",
                details={"pinned": "case_manifest_hash"})

    @staticmethod
    def _require_transition(assignment: ReviewAssignment,
                            target: ReviewState) -> None:
        current = assignment.state
        if current is ReviewState.INVALIDATED:
            raise ExpertReviewError(code="EXPERT_REVIEW_INVALIDATED")
        if current is ReviewState.COMPLETED:
            raise ExpertReviewError(code="EXPERT_REVIEW_ALREADY_COMPLETED")
        if not may_transition(current, target):
            # A more specific code where one exists, so a reviewer's client can
            # say "record your expectation first" rather than "invalid".
            if target is ReviewState.RESULT_REVEALED and \
                    current is ReviewState.ASSIGNED:
                raise ExpertReviewError(
                    code="EXPERT_REVIEW_EXPECTATION_REQUIRED")
            if target is ReviewState.COMPLETED and \
                    current in (ReviewState.ASSIGNED,
                                ReviewState.EXPECTATION_RECORDED):
                raise ExpertReviewError(code="EXPERT_REVIEW_REVEAL_REQUIRED")
            if target is ReviewState.EXPECTATION_RECORDED and \
                    current is not ReviewState.ASSIGNED:
                raise ExpertReviewError(
                    code="EXPERT_REVIEW_EXPECTATION_ALREADY_LOCKED")
            if target is ReviewState.RESULT_REVEALED and \
                    current is ReviewState.RESULT_REVEALED:
                raise ExpertReviewError(
                    code="EXPERT_REVIEW_RESULT_ALREADY_REVEALED")
            raise InvalidTransitionError(
                details={"from": current.value, "to": target.value})

    def _commit(self, review_id: str, *, record: Any,
                event: ReviewAuditEvent,
                assignment: Optional[ReviewAssignment] = None) -> None:
        """Record, state change and audit event, atomically or not at all.

        The audit append is inside the same unit of work as the act it
        describes. A failure here rolls the act back, so there is no path that
        produces a governed change with no record of it.
        """
        store, _ = self._require_service()
        uow = None
        try:
            if self._uow_factory is not None:
                uow = self._uow_factory()
                uow.__enter__()
            store.append(review_id, record=record, event=event,
                         assignment=assignment)
            if uow is not None:
                uow.commit()
        except ExpertReviewError:
            if uow is not None:
                uow.__exit__(*(None, None, None))
            raise
        except Exception as error:  # noqa: BLE001 - surfaced as an audit failure
            if uow is not None:
                uow.__exit__(type(error), error, None)
            raise AuditChainError(
                "the governed action was rolled back because its audit event "
                "could not be recorded",
                details={"review_id": review_id}) from error
        else:
            if uow is not None:
                uow.__exit__(None, None, None)

    # -- payload access ---------------------------------------------------

    def payload_permit(self, *, case_id: str, actor: str,
                       role: str) -> PayloadPermit:
        """A permit for this reviewer to read this case's payload, or refuse.

        The only way an EXPERT_HOLDOUT payload becomes readable. WP-18's
        blanket refusal is untouched; this issues a value bound to one actor,
        one case, one assignment and one stage, which the access check then
        matches. Nothing is returned to a client.
        """
        require_approved(self._protocol)
        self._require_reviewer_role(role)
        store, _ = self._require_service()
        assignment = self._load_assignment(store, case_id=case_id, actor=actor)
        self._check_pins(assignment)
        return issue_permit(assignment, now=self._clock())

    # -- the four governed operations -------------------------------------

    def view(self, *, case_id: str, actor: str, role: str) -> ReviewView:
        """What this reviewer may see. Blinded until a reveal record exists."""
        require_approved(self._protocol)
        self._require_reviewer_role(role)
        store, _ = self._require_service()
        assignment = self._load_assignment(store, case_id=case_id, actor=actor)
        expectations = list(store.expectations(assignment.review_id))
        view = ReviewView(
            assignment,
            expectation=expectations[-1] if expectations else None,
            corrections=store.corrections(assignment.review_id),
            completion=store.completion(assignment.review_id))
        reveal = store.reveal(assignment.review_id)
        if reveal is not None:
            view.with_result(reveal)
        return view

    def record_expectation(self, *, case_id: str, actor: str, role: str,
                           body: Mapping[str, Any]) -> ExpectedResponse:
        """Lock what the reviewer expects, before anything is revealed."""
        require_approved(self._protocol)
        self._require_reviewer_role(role)
        store, _ = self._require_service()
        assert_no_forged_fields(body)
        assignment = self._load_assignment(store, case_id=case_id, actor=actor)
        self._check_pins(assignment)
        self._require_transition(assignment, ReviewState.EXPECTATION_RECORDED)
        if store.expectations(assignment.review_id):
            # Belt and braces with the state check: a store that somehow held
            # an expectation for an ASSIGNED review must not accept a second.
            raise ExpertReviewError(
                code="EXPERT_REVIEW_EXPECTATION_ALREADY_LOCKED")

        now = self._clock()
        expectation = ExpectedResponse(
            revision_id=self._new_id("EXR"),
            review_id=assignment.review_id,
            revision=1,
            expected_attention_level=str(body["expected_attention_level"]),
            expected_coverage_status=str(body["expected_coverage_status"]),
            expected_coverage_reason=body.get("expected_coverage_reason"),
            expected_rule_id=body.get("expected_rule_id"),
            requires_traceable_evidence=bool(
                body.get("requires_traceable_evidence", True)),
            rationale_codes=tuple(body.get("rationale_codes", ())),
            reviewer_note=str(body.get("reviewer_note", "")),
            recorded_at=now,
            previous_hash=None)
        moved = assignment.with_state(ReviewState.EXPECTATION_RECORDED)
        event = append_event(
            store.audit_chain(assignment.review_id),
            event_id=self._new_id("EVT"),
            review_id=assignment.review_id,
            action=AuditAction.EXPECTATION_RECORDED,
            actor=actor, actor_role=role, occurred_at=now,
            previous_state=assignment.state.value,
            new_state=moved.state.value,
            outcome_code="EXPECTATION_LOCKED",
            protocol_hash=assignment.protocol_hash,
            release_manifest_hash=assignment.release_manifest_hash,
            case_manifest_hash=assignment.case_manifest_hash,
            record_hashes={"expectation_revision_hash":
                           expectation.revision_hash()})
        self._commit(assignment.review_id, record=expectation, event=event,
                     assignment=moved)
        return expectation

    def reveal(self, *, case_id: str, actor: str, role: str,
               body: Optional[Mapping[str, Any]] = None) -> RevealRecord:
        """Show the system result, pinned to the locked expectation."""
        require_approved(self._protocol)
        self._require_reviewer_role(role)
        store, results = self._require_service()
        assert_no_forged_fields(body or {})
        assignment = self._load_assignment(store, case_id=case_id, actor=actor)
        self._check_pins(assignment)
        # Terminal states first. A completed review's most important fact is
        # that it is finished; reporting "already revealed" would be true and
        # would send a client to the wrong remedy.
        self._require_transition(assignment, ReviewState.RESULT_REVEALED)
        if store.reveal(assignment.review_id) is not None:
            raise ExpertReviewError(
                code="EXPERT_REVIEW_RESULT_ALREADY_REVEALED")

        expectations = list(store.expectations(assignment.review_id))
        if not expectations:
            raise ExpertReviewError(
                code="EXPERT_REVIEW_EXPECTATION_REQUIRED")
        # The latest revision at the moment of reveal. Anything appended after
        # this cannot become what the reviewer predicted.
        locked = expectations[-1]

        result = results.result_for(case_id=case_id, assignment=assignment)
        for field_name in ("release_manifest_hash", "case_manifest_hash"):
            if field_name in result:
                self._check_pins(assignment,
                                 **{field_name: result[field_name]})

        now = self._clock()
        reveal = RevealRecord(
            reveal_id=self._new_id("RVL"),
            review_id=assignment.review_id,
            expectation_revision_id=locked.revision_id,
            expectation_revision_hash=locked.revision_hash(),
            result_output_hash=str(result["output_hash"]),
            result_attention_level=str(result["attention_level"]),
            result_coverage_status=str(result["coverage_status"]),
            result_coverage_reason=result.get("coverage_reason"),
            result_firing_rule_id=result.get("firing_rule_id"),
            result_finding_count=int(result.get("finding_count", 0)),
            result_traceable_finding_count=int(
                result.get("traceable_finding_count", 0)),
            revealed_at=now, previous_hash=locked.revision_hash())
        moved = assignment.with_state(ReviewState.RESULT_REVEALED)
        event = append_event(
            store.audit_chain(assignment.review_id),
            event_id=self._new_id("EVT"),
            review_id=assignment.review_id,
            action=AuditAction.RESULT_REVEALED,
            actor=actor, actor_role=role, occurred_at=now,
            previous_state=assignment.state.value,
            new_state=moved.state.value,
            outcome_code="RESULT_REVEALED",
            protocol_hash=assignment.protocol_hash,
            release_manifest_hash=assignment.release_manifest_hash,
            case_manifest_hash=assignment.case_manifest_hash,
            record_hashes={"expectation_revision_hash":
                           locked.revision_hash(),
                           "reveal_hash": reveal.reveal_hash()})
        self._commit(assignment.review_id, record=reveal, event=event,
                     assignment=moved)
        return reveal

    def complete(self, *, case_id: str, actor: str, role: str,
                 body: Mapping[str, Any]) -> CompletionDecision:
        """Record AGREE / PARTIAL / DISAGREE and any ratings. Then immutable."""
        require_approved(self._protocol)
        self._require_reviewer_role(role)
        store, _ = self._require_service()
        assert_no_forged_fields(body)
        assignment = self._load_assignment(store, case_id=case_id, actor=actor)
        self._check_pins(assignment)
        self._require_transition(assignment, ReviewState.COMPLETED)
        reveal = store.reveal(assignment.review_id)
        if reveal is None:
            raise ExpertReviewError(code="EXPERT_REVIEW_REVEAL_REQUIRED")
        if store.completion(assignment.review_id) is not None:
            raise ExpertReviewError(code="EXPERT_REVIEW_ALREADY_COMPLETED")

        raw = body.get("decision")
        try:
            decision = ExpertDecision(str(raw))
        except ValueError:
            raise ExpertReviewError(
                "the decision is exactly AGREE, PARTIAL or DISAGREE",
                code="EXPERT_REVIEW_INVALID_TRANSITION",
                details={"permitted": [item.value
                                       for item in ExpertDecision]}) from None
        ratings = tuple(RatingValue(dimension=str(name), value=int(value))
                        for name, value
                        in sorted(dict(body.get("ratings") or {}).items()))

        now = self._clock()
        completion = CompletionDecision(
            completion_id=self._new_id("CMP"),
            review_id=assignment.review_id,
            reveal_id=reveal.reveal_id,
            decision=decision, ratings=ratings,
            reviewer_note=str(body.get("reviewer_note", "")),
            completed_at=now, previous_hash=reveal.reveal_hash())
        moved = assignment.with_state(ReviewState.COMPLETED)
        event = append_event(
            store.audit_chain(assignment.review_id),
            event_id=self._new_id("EVT"),
            review_id=assignment.review_id,
            action=AuditAction.COMPLETED,
            actor=actor, actor_role=role, occurred_at=now,
            previous_state=assignment.state.value,
            new_state=moved.state.value,
            outcome_code="REVIEW_COMPLETED",
            protocol_hash=assignment.protocol_hash,
            release_manifest_hash=assignment.release_manifest_hash,
            case_manifest_hash=assignment.case_manifest_hash,
            record_hashes={"completion_hash": completion.completion_hash(),
                           "reveal_hash": reveal.reveal_hash()})
        self._commit(assignment.review_id, record=completion, event=event,
                     assignment=moved)
        return completion

    def append_correction(self, *, case_id: str, actor: str, role: str,
                          body: Mapping[str, Any]) -> Correction:
        """Append an amendment. The corrected record is never touched.

        A correction after a reveal is annotation only, and
        ``after_reveal=True`` is recorded on it. WP-21 consumes the expectation
        revision the *reveal* pinned, so a post-reveal amendment - however
        sincere - cannot become the thing the reviewer predicted.
        """
        require_approved(self._protocol)
        self._require_reviewer_role(role)
        store, _ = self._require_service()
        assert_no_forged_fields(body)
        assignment = self._load_assignment(store, case_id=case_id, actor=actor)
        self._check_pins(assignment)
        if assignment.state is ReviewState.INVALIDATED:
            raise ExpertReviewError(code="EXPERT_REVIEW_INVALIDATED")

        revealed = store.reveal(assignment.review_id) is not None
        now = self._clock()
        chain = list(store.corrections(assignment.review_id))
        correction = Correction(
            correction_id=self._new_id("COR"),
            review_id=assignment.review_id,
            target_hash=str(body["target_hash"]),
            kind=CorrectionKind(str(body["kind"])),
            reason_code=str(body.get("reason_code", "")),
            actor=actor, actor_role=role, recorded_at=now,
            replacement=body.get("replacement"),
            after_reveal=revealed,
            previous_hash=(chain[-1].correction_hash() if chain else None))
        event = append_event(
            store.audit_chain(assignment.review_id),
            event_id=self._new_id("EVT"),
            review_id=assignment.review_id,
            action=AuditAction.CORRECTION_APPENDED,
            actor=actor, actor_role=role, occurred_at=now,
            previous_state=assignment.state.value,
            new_state=assignment.state.value,
            outcome_code=("CORRECTION_ANNOTATION" if revealed
                          else "CORRECTION_PRE_REVEAL"),
            protocol_hash=assignment.protocol_hash,
            release_manifest_hash=assignment.release_manifest_hash,
            case_manifest_hash=assignment.case_manifest_hash,
            record_hashes={"correction_hash": correction.correction_hash()})
        self._commit(assignment.review_id, record=correction, event=event)
        return correction

    # -- verification ------------------------------------------------------

    def verify(self, review_id: str) -> Tuple[bool, str]:
        """Whether this review's audit chain is intact."""
        store, _ = self._require_service()
        return verify_chain(store.audit_chain(review_id))
