# -*- coding: utf-8 -*-
"""A TEST-ONLY approved protocol, assignment, store and result port.

Read the package docstring first: none of this is real, and the signatories
below are not people.

The in-memory store is deliberately faithful to the real contract in one
respect that matters: it has **no update and no delete method**. A test cannot
demonstrate immutability against a store that would have allowed a mutation if
asked; it can only demonstrate that nobody asked. So the store here cannot
express the operation at all, which is what the SQL layer also enforces with
triggers.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import itertools
from typing import Any, Dict, List, Mapping, Optional, Sequence

from pgx.expert_review.audit import ReviewAuditEvent
from pgx.expert_review.models import (CompletionDecision, Correction,
                                      ExpectedResponse, RevealRecord,
                                      ReviewAssignment)
from pgx.expert_review.protocol import (ExpertProtocol, PROTOCOL_VERSION,
                                        ProtocolSignatory,
                                        REQUIRED_SIGNATORY_ROLES)
from pgx.expert_review.service import ReviewStore, RevealedResultPort
from pgx.expert_review.vocabulary import ReviewState

#: A real WP-18 case identifier shape, so the same fixture case can be
#: handed to the validation access policy. Still unmistakably TEST-ONLY.
CASE_ID = "PGX-VAL-TEST-ONLY-EH-0001"
REVIEWER = "TEST-ONLY-reviewer-1"
OTHER_REVIEWER = "TEST-ONLY-reviewer-2"
ADMIN_ACTOR = "TEST-ONLY-admin-1"
RELEASE_PUBLIC_ID = "TEST-ONLY-REL-0001"
DATASET_PUBLIC_ID = "TEST-ONLY-DS-0001"
RULESET_PUBLIC_ID = "TEST-ONLY-RS-0001"
SOFTWARE_VERSION = "TEST-ONLY-0.0.0"
DOCUMENT_DIGEST = "sha256:" + hashlib.sha256(
    b"TEST-ONLY protocol text").hexdigest()


def _digest(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


RELEASE_MANIFEST_HASH = _digest("TEST-ONLY release manifest")
SOFTWARE_HASH = _digest("TEST-ONLY software")
DATASET_HASH = _digest("TEST-ONLY dataset")
RULESET_HASH = _digest("TEST-ONLY ruleset")
CASE_MANIFEST_HASH = _digest("TEST-ONLY expert manifest")
RESULT_OUTPUT_HASH = _digest("TEST-ONLY output")

NOW = _dt.datetime(2026, 6, 1, 12, 0, tzinfo=_dt.timezone.utc)


def approved_protocol() -> ExpertProtocol:
    """A TEST-ONLY approved protocol. These four are not people.

    Constructed in Python on purpose. ``load_protocol`` reads no signatories
    from disk, so there is no file an operator could edit to approve the real
    protocol - approval requires a visible change to that function, reviewed
    as such.
    """
    signatories = tuple(
        ProtocolSignatory(
            name="TEST-ONLY signatory %d" % index,
            affiliation="TEST-ONLY affiliation (not a real organisation)",
            role=role, decided_on="2026-05-01",
            approved_document_digest=DOCUMENT_DIGEST,
            record_reference="TEST-ONLY record; no signature exists")
        for index, role in enumerate(REQUIRED_SIGNATORY_ROLES, start=1))
    return ExpertProtocol(
        protocol_version=PROTOCOL_VERSION,
        document_path="docs/validation/expert-protocol.md",
        document_digest=DOCUMENT_DIGEST,
        status="TEST-ONLY APPROVED (fixture; not a real approval)",
        signatories=signatories,
        note="TEST ONLY. No person approved anything.")


def amended_approved_protocol() -> ExpertProtocol:
    """A different protocol text, also approved by four TEST-ONLY signatories.

    Needed to test the *mismatch* path rather than the *unapproved* path.
    Editing the digest of an approved protocol makes it unapproved - correctly,
    because a document amended after signing has not been signed - so a
    genuinely different-but-approved protocol has to be built from scratch.
    """
    other_digest = _digest("TEST-ONLY amended protocol text")
    signatories = tuple(
        ProtocolSignatory(
            name="TEST-ONLY signatory %d" % index,
            affiliation="TEST-ONLY affiliation (not a real organisation)",
            role=role, decided_on="2026-05-02",
            approved_document_digest=other_digest,
            record_reference="TEST-ONLY record; no signature exists")
        for index, role in enumerate(REQUIRED_SIGNATORY_ROLES, start=1))
    return ExpertProtocol(
        protocol_version=PROTOCOL_VERSION,
        document_path="docs/validation/expert-protocol.md",
        document_digest=other_digest,
        status="TEST-ONLY APPROVED (fixture; a different document)",
        signatories=signatories, note="TEST ONLY")


def unapproved_protocol() -> ExpertProtocol:
    return ExpertProtocol(
        protocol_version=PROTOCOL_VERSION,
        document_path="docs/validation/expert-protocol.md",
        document_digest=DOCUMENT_DIGEST,
        status="DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW",
        signatories=(), note="TEST ONLY")


def review_id_for(case_id: str = CASE_ID) -> str:
    """The review id a fixture assignment carries for a given case."""
    return "TEST-ONLY-RVW-%s" % case_id.rsplit("-", 1)[-1]


def assignment(*, case_id: str = CASE_ID, reviewer: str = REVIEWER,
               state: ReviewState = ReviewState.ASSIGNED,
               protocol: Optional[ExpertProtocol] = None,
               case_role: str = "EXPERT_HOLDOUT",
               release_manifest_hash: str = RELEASE_MANIFEST_HASH,
               case_manifest_hash: str = CASE_MANIFEST_HASH
               ) -> ReviewAssignment:
    protocol = protocol or approved_protocol()
    # Identifiers derived from the case, so a fixture set holding two
    # assignments does not silently collapse them into one.
    suffix = case_id.rsplit("-", 1)[-1]
    return ReviewAssignment(
        assignment_id="TEST-ONLY-ASG-%s" % suffix,
        review_id=review_id_for(case_id),
        case_id=case_id, case_role=case_role,
        reviewer_actor=reviewer, reviewer_role="EXPERT_REVIEWER",
        protocol_version=protocol.protocol_version,
        protocol_hash=protocol.protocol_hash(),
        release_public_id=RELEASE_PUBLIC_ID,
        release_manifest_hash=release_manifest_hash,
        software_version=SOFTWARE_VERSION, software_hash=SOFTWARE_HASH,
        dataset_public_id=DATASET_PUBLIC_ID,
        dataset_content_hash=DATASET_HASH,
        ruleset_public_id=RULESET_PUBLIC_ID,
        ruleset_content_hash=RULESET_HASH,
        case_manifest_hash=case_manifest_hash,
        assigned_at=NOW, state=state)


EXPECTED_BODY: Mapping[str, Any] = {
    "expected_attention_level": "HIGH",
    "expected_coverage_status": "FULL",
    "expected_rule_id": "TEST-ONLY-RULE-1",
    "requires_traceable_evidence": True,
    "rationale_codes": ("GUIDELINE_DIRECT", "PHENOTYPE_DETERMINATIVE"),
    "reviewer_note": "TEST-ONLY note: the axis is determinative here.",
}

#: The system result the fixture port returns. Matches the expectation above,
#: so the default fixture completes as AGREE; tests that want PARTIAL or
#: DISAGREE override the port.
SYSTEM_RESULT: Mapping[str, Any] = {
    "attention_level": "HIGH",
    "coverage_status": "FULL",
    "coverage_reason": None,
    "firing_rule_id": "TEST-ONLY-RULE-1",
    "finding_count": 2,
    "traceable_finding_count": 2,
    "output_hash": RESULT_OUTPUT_HASH,
    "release_manifest_hash": RELEASE_MANIFEST_HASH,
    "case_manifest_hash": CASE_MANIFEST_HASH,
}


class InMemoryReviewStore(ReviewStore):
    """A faithful in-memory store: append-only, with no way to mutate.

    There is no ``update`` and no ``delete``, not even a private one. A test
    proving immutability against a store that *could* mutate would prove only
    that this code did not - which is a much weaker statement than the one the
    SQL triggers make.
    """

    def __init__(self, assignments: Sequence[ReviewAssignment] = ()) -> None:
        self._assignments: Dict[str, ReviewAssignment] = {
            item.review_id: item for item in assignments}
        self._expectations: Dict[str, List[ExpectedResponse]] = {}
        self._reveals: Dict[str, RevealRecord] = {}
        self._completions: Dict[str, CompletionDecision] = {}
        self._corrections: Dict[str, List[Correction]] = {}
        self._audit: Dict[str, List[ReviewAuditEvent]] = {}
        #: Set by a test to make the next append fail, so the rollback path is
        #: exercised rather than assumed.
        self.fail_next_append = False

    # -- reads -----------------------------------------------------------

    def assignment_for(self, *, case_id: str, actor: str):
        for item in self._assignments.values():
            if item.case_id == case_id and item.reviewer_actor == actor:
                return item
        return None

    def assignments_for_actor(self, actor: str):
        return tuple(item for item in self._assignments.values()
                     if item.reviewer_actor == actor)

    def expectations(self, review_id: str):
        return tuple(self._expectations.get(review_id, ()))

    def reveal(self, review_id: str):
        return self._reveals.get(review_id)

    def completion(self, review_id: str):
        return self._completions.get(review_id)

    def corrections(self, review_id: str):
        return tuple(self._corrections.get(review_id, ()))

    def audit_chain(self, review_id: str):
        return tuple(self._audit.get(review_id, ()))

    # -- the single write path -------------------------------------------

    def append(self, review_id: str, *, record, event, assignment=None):
        if self.fail_next_append:
            raise RuntimeError("TEST-ONLY simulated persistence failure")
        if isinstance(record, ExpectedResponse):
            self._expectations.setdefault(review_id, []).append(record)
        elif isinstance(record, RevealRecord):
            if review_id in self._reveals:
                raise RuntimeError("a review reveals once")
            self._reveals[review_id] = record
        elif isinstance(record, CompletionDecision):
            if review_id in self._completions:
                raise RuntimeError("a review completes once")
            self._completions[review_id] = record
        elif isinstance(record, Correction):
            self._corrections.setdefault(review_id, []).append(record)
        else:  # pragma: no cover - defensive
            raise RuntimeError("unknown record type %r" % type(record))
        self._audit.setdefault(review_id, []).append(event)
        if assignment is not None:
            self._assignments[assignment.review_id] = assignment


class StaticResultPort(RevealedResultPort):
    """Returns the fixture system result. Consulted only at reveal."""

    def __init__(self, result: Optional[Mapping[str, Any]] = None) -> None:
        self.result = dict(result or SYSTEM_RESULT)
        self.call_count = 0

    def result_for(self, *, case_id, assignment):
        self.call_count += 1
        return dict(self.result)


class CountingClock:
    """A deterministic clock so records have stable, ordered timestamps."""

    def __init__(self, start: _dt.datetime = NOW) -> None:
        self._counter = itertools.count()

    def __call__(self) -> _dt.datetime:
        return NOW + _dt.timedelta(minutes=next(self._counter))


class SequentialIds:
    """Deterministic identifiers so record hashes are reproducible."""

    def __init__(self) -> None:
        self._counters: Dict[str, int] = {}

    def __call__(self, prefix: str) -> str:
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return "TEST-ONLY-%s-%04d" % (prefix, self._counters[prefix])


def service(*, protocol: Optional[ExpertProtocol] = None,
            store: Optional[InMemoryReviewStore] = None,
            result: Optional[Mapping[str, Any]] = None,
            uow_factory: Optional[Any] = None):
    """A wired TEST-ONLY service holding one assignment."""
    from pgx.expert_review.service import ExpertReviewService
    protocol = protocol or approved_protocol()
    store = store if store is not None else InMemoryReviewStore(
        (assignment(protocol=protocol),))
    return ExpertReviewService(
        protocol=protocol, store=store,
        result_port=StaticResultPort(result), uow_factory=uow_factory,
        clock=CountingClock(), id_factory=SequentialIds())
