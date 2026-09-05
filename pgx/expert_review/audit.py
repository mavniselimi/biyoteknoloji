# -*- coding: utf-8 -*-
"""The append-only review audit chain (WP-22).

Every governed act appends one event, and each event carries the hash of the
one before it. That chaining is what makes three different kinds of tampering
detectable rather than merely discouraged:

- **editing** an event changes its recomputed hash, so its successor's
  ``previous_hash`` no longer matches;
- **deleting** one leaves a successor naming a predecessor that is not there;
- **reordering** two breaks both links at once.

:func:`verify_chain` finds all three and says which sequence number failed.

The chain holds identifiers, hashes, actors and codes. It holds **no expert
content**: not an expected response, not a rationale, not a decision, not a
rating. An audit trail is read by people who are not the reviewer - and often
before the study is finished - so an event that quoted the blinded record
would defeat the blinding it exists to evidence.

Atomicity is the caller's responsibility and the caller is
:class:`~pgx.expert_review.service.ExpertReviewService`: it appends the event
and writes the state transition inside one unit of work, and rolls the
transition back if the append fails. This module provides the value type and
the verifier; it deliberately owns no transaction.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.expert_review.errors import AuditChainError
from pgx.expert_review.models import chain_hash
from pgx.expert_review.vocabulary import AuditAction

__all__ = [
    "AUDIT_EVENT_VERSION",
    "PROHIBITED_AUDIT_FIELDS",
    "ReviewAuditEvent",
    "append_event",
    "verify_chain",
]

AUDIT_EVENT_VERSION = "pgx-wp22-review-audit-event/1"

#: WP-23's assurance vocabulary, held as strings so this module does not
#: import ``pgx.security`` - WP-22 must stay composable without it. A test
#: asserts the two spellings are one set.
_ASSURANCE_LEVELS = frozenset({"NONE", "TEST_STATIC_TOKEN", "SESSION"})

#: Never permitted in an audit detail map. Checked on construction, because an
#: audit row is the thing most likely to be exported wholesale to somebody who
#: should not read a blinded expectation.
PROHIBITED_AUDIT_FIELDS: Tuple[str, ...] = (
    "expected_attention_level", "expected_coverage_status",
    "expected_coverage_reason", "expected_rule_id", "rationale_codes",
    "reviewer_note", "decision", "ratings", "replacement",
    "attention_level", "coverage_status", "firing_rule_id", "payload",
    "phenotypes", "medications", "report_text",
)


@dataclass(frozen=True, slots=True)
class ReviewAuditEvent:
    """One governed act. Immutable, chained, and content-free."""

    event_id: str
    sequence: int
    review_id: str
    action: AuditAction
    actor: str
    actor_role: str
    #: True only for a validated server-side session (WP-23). Recorded on
    #: every row rather than implied, so an auditor reading a single event
    #: knows the identity assurance behind it without consulting anything
    #: else.
    actor_authenticated: bool
    occurred_at: _dt.datetime
    previous_state: Optional[str]
    new_state: Optional[str]
    outcome_code: str
    protocol_hash: str
    release_manifest_hash: str
    case_manifest_hash: str
    #: WP-23. How much the mechanism is worth. ``NONE`` for an unattributed
    #: caller, ``TEST_STATIC_TOKEN`` for a development fixture, ``SESSION``
    #: for a validated server-side session - and only the last may pair with
    #: ``actor_authenticated: true``. Defaulted, so every existing caller
    #: keeps recording the unauthenticated answer.
    auth_assurance: str = "NONE"
    #: Hashes of the records this act produced. Hashes, never contents.
    record_hashes: Mapping[str, str] = field(default_factory=dict)
    previous_hash: Optional[str] = None
    schema_version: str = AUDIT_EVENT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.action, AuditAction):
            raise AuditChainError("action is an AuditAction")
        # Changed at WP-23, in the open, exactly as the refusal above
        # promised. A review action performed inside a validated server-side
        # session may now record ``actor_authenticated: true``; every other
        # mechanism records false.
        #
        # ``auth_assurance`` is what decides, and it is a governed vocabulary
        # value rather than a boolean the caller sets alongside. Passing
        # ``actor_authenticated=True`` with anything other than SESSION
        # assurance is refused - a development fixture proves that a test
        # ran, not that a person acted, and a review trail that could not
        # tell them apart would let a development run masquerade as evidence.
        if self.actor_authenticated and self.auth_assurance != "SESSION":
            raise AuditChainError(
                "only a validated server-side session may record an "
                "authenticated actor; a static development token records "
                "TEST_STATIC_TOKEN assurance and stays distinguishable from "
                "a person forever")
        if self.auth_assurance not in _ASSURANCE_LEVELS:
            raise AuditChainError(
                "a review audit event records one of the governed assurance "
                "levels: " + ", ".join(sorted(_ASSURANCE_LEVELS)))
        if self.occurred_at.tzinfo is None:
            raise AuditChainError("an audit event carries a UTC timestamp")
        object.__setattr__(self, "occurred_at",
                           self.occurred_at.astimezone(_dt.timezone.utc))
        offending = sorted(set(str(key).lower()
                               for key in (self.record_hashes or {}))
                           & set(PROHIBITED_AUDIT_FIELDS))
        if offending:
            raise AuditChainError(
                "an audit event carries hashes and codes, never expert "
                "content: %s" % ", ".join(offending))
        object.__setattr__(self, "record_hashes",
                           dict(self.record_hashes or {}))
        if int(self.sequence) < 1:
            raise AuditChainError("sequences start at 1")
        object.__setattr__(self, "sequence", int(self.sequence))

    def payload(self) -> Dict[str, Any]:
        """What the chain hash covers. Order-independent by construction."""
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "sequence": self.sequence,
            "review_id": self.review_id,
            "action": self.action.value,
            "actor": self.actor,
            "actor_role": self.actor_role,
            "actor_authenticated": self.actor_authenticated,
            "auth_assurance": self.auth_assurance,
            "occurred_at": self.occurred_at.isoformat().replace("+00:00", "Z"),
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "outcome_code": self.outcome_code,
            "protocol_hash": self.protocol_hash,
            "release_manifest_hash": self.release_manifest_hash,
            "case_manifest_hash": self.case_manifest_hash,
            "record_hashes": dict(sorted(self.record_hashes.items())),
        }

    def event_hash(self) -> str:
        return chain_hash(self.previous_hash, self.payload())

    def to_json(self) -> Dict[str, Any]:
        payload = self.payload()
        payload["previous_hash"] = self.previous_hash
        payload["event_hash"] = self.event_hash()
        return payload


def append_event(chain: Sequence[ReviewAuditEvent],
                 **fields: Any) -> ReviewAuditEvent:
    """Build the next event, linked to the chain's tail.

    Sequence and predecessor hash are derived here rather than supplied, so a
    caller cannot insert an event out of order or claim a predecessor that is
    not the actual tail.
    """
    tail = chain[-1] if chain else None
    fields.setdefault("sequence", (tail.sequence + 1) if tail else 1)
    fields.setdefault("previous_hash", tail.event_hash() if tail else None)
    # Both default to the unauthenticated answer. A caller that forgets to
    # supply them records a fixture, never a person - the failure direction
    # that under-claims.
    fields.setdefault("actor_authenticated", False)
    fields.setdefault("auth_assurance", "NONE")
    return ReviewAuditEvent(**fields)


def verify_chain(chain: Sequence[ReviewAuditEvent]) -> Tuple[bool, str]:
    """``(True, "")`` or ``(False, reason)`` naming the first broken link.

    Checks three things at each position: that the sequence increases by one,
    that the recorded predecessor hash equals the recomputed hash of the
    actual predecessor, and that the first event claims no predecessor. Any
    edit, deletion or reordering fails at least one of them.
    """
    previous: Optional[ReviewAuditEvent] = None
    for index, event in enumerate(chain):
        expected_sequence = index + 1
        if event.sequence != expected_sequence:
            return False, ("sequence %d found at position %d; an event was "
                           "inserted, removed or reordered"
                           % (event.sequence, expected_sequence))
        expected_previous = previous.event_hash() if previous else None
        if event.previous_hash != expected_previous:
            return False, ("event %d does not name the hash of the event "
                           "before it; the chain was edited, truncated or "
                           "reordered" % event.sequence)
        previous = event
    return True, ""
