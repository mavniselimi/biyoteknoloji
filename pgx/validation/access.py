# -*- coding: utf-8 -*-
"""Who has seen which case, recorded append-only (WP-18).

Two responsibilities, and keeping them apart is most of the design:

**Deciding** whether an access context may read a payload. That is a policy
over the case's role and visibility and the context's declared purpose, and it
fails closed - an unrecognised combination is a refusal, not a permission.

**Recording** that the attempt happened. Every attempt, allowed or refused,
appends one event. A log of successes only would answer "who read this" and
not "who tried", and the second question is the one an investigation asks.

**This package does not authenticate anybody.** The caller supplies an actor
string and a declared purpose, and both are recorded as *claims* - the event
carries ``actor_authenticated: false`` and there is no code path that sets it
true. WP-23 owns identity. Pretending otherwise would put an unverified name
in an audit trail that later reads as a verified one, which is worse than
recording nothing.

**A refusal must teach nothing.** Two rules follow from that and both are
tested. A denied read returns the same error shape whether or not a payload
exists, so a caller cannot probe for the existence of an answer by being
refused. And listing is partition-scoped: there is no call that returns "all
cases", because a count that included holdout would let anybody with metadata
access measure how many answers exist and watch that number move.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.domain.hashing import ensure_utc, sha256_digest
from pgx.validation.cases import ValidationCaseMetadata
from pgx.validation.errors import AccessDeniedError, VisibilityError
from pgx.validation.vocabulary import (AUTHOR_CONTEXTS, AccessAction,
                                       AccessContextKind, HOLDOUT_ROLES,
                                       ValidationCaseRole, VisibilityLevel)

__all__ = [
    "ACCESS_EVENT_VERSION",
    "AccessContext",
    "AccessDecision",
    "AccessEvent",
    "AccessLedger",
    "DENY_REASONS",
    "decide_access",
]

ACCESS_EVENT_VERSION = "pgx-wp18-access-event/1"

_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@\-]{1,63}$")

#: Every reason an access may be refused. Deliberately coarse: a caller
#: learns *that* they were refused and under which broad rule, and cannot
#: distinguish "this holdout has an answer" from "this holdout does not".
DENY_REASONS: Mapping[str, str] = {
    "AUTHOR_CONTEXT_MAY_NOT_READ_HOLDOUT":
        "a rule-authoring or development context may not read a holdout "
        "payload; doing so would end that holdout's independence",
    "EXPERT_HOLDOUT_REQUIRES_PERMITTED_WORKFLOW":
        "an expert-holdout payload is released only through the review "
        "protocol WP-22 owns, which is not implemented",
    "PAYLOAD_NOT_AUTHOR_VISIBLE":
        "this case's payload is not author-visible",
    "UNKNOWN_CONTEXT":
        "the access context is not one this policy recognises",
}


@dataclass(frozen=True, slots=True)
class AccessContext:
    """Who is asking, as they describe themselves. Never verified here.

    ``actor`` is a caller-supplied string. It is recorded because an audit
    trail with no name is not an audit trail, and it is marked unverified
    because recording it as verified would be a lie this package is not in a
    position to check.
    """

    actor: str
    kind: AccessContextKind
    purpose: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, AccessContextKind):
            raise VisibilityError("kind must be an AccessContextKind")
        actor = str(self.actor or "").strip()
        if not _ACTOR.match(actor):
            raise VisibilityError(
                "an access context needs a caller-supplied actor identifier "
                "of 2-64 permitted characters; anonymous access is not "
                "recordable and therefore not allowed")
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "purpose", str(self.purpose or "").strip()[:256])

    @property
    def is_author_context(self) -> bool:
        return self.kind in AUTHOR_CONTEXTS

    def to_json(self) -> Dict[str, Any]:
        return {"actor": self.actor, "context_kind": self.kind.value,
                "purpose": self.purpose,
                # Stated in every event, every time. WP-23 owns making this
                # answerable with anything but False.
                "actor_authenticated": False}


@dataclass(frozen=True, slots=True)
class AccessDecision:
    """Allowed or not, and under which named reason."""

    allowed: bool
    reason_code: str

    def __post_init__(self) -> None:
        if not self.allowed and self.reason_code not in DENY_REASONS:
            raise VisibilityError("unknown deny reason %r" % self.reason_code)


def _permit_authorises(case: ValidationCaseMetadata,
                       context: AccessContext,
                       permit: Optional[Any]) -> bool:
    """Whether a WP-22 permit opens this exact payload for this exact caller.

    Three conditions, all required, and the first is the one that keeps the
    original boundary intact: the context must be an EXPERT_REVIEW context.
    An author or development context presenting a valid permit is still
    refused, because the refusal there is about what the *caller is doing*,
    not about what they hold.

    Imported inside the function. WP-18 does not depend on WP-22; it accepts
    an opaque permit and asks WP-22's own matcher whether it fits. A top-level
    import would invert the dependency and make the validation package
    unimportable without the review package.
    """
    if permit is None:
        return False
    if context.kind is not AccessContextKind.EXPERT_REVIEW:
        return False
    try:
        from pgx.expert_review.permits import permit_allows
    except ImportError:  # pragma: no cover - WP-22 absent
        return False
    return permit_allows(permit, case_id=case.case_id.value,
                         actor=context.actor)


def decide_access(case: ValidationCaseMetadata, context: AccessContext,
                  action: AccessAction,
                  permit: Optional[Any] = None) -> AccessDecision:
    """Whether this context may perform this action on this case.

    Metadata is readable by every recognised context - a case's existence,
    role and provenance summary are what a manifest publishes anyway, and
    hiding them would not hide anything.

    Payload reads are where the partition lives, and the decision never
    consults whether a payload is actually present. That is deliberate: a
    policy that allowed a read when there was nothing to read would answer
    "is there an answer here?" for free.

    ``permit`` is WP-22's assignment-scoped payload permit, and it is the
    **only** widening of this policy. The blanket refusal of every
    EXPERT_HOLDOUT payload below is unchanged: what the permit adds is one
    narrow path for a reviewer who is actually assigned to this exact case.

    "Any expert reviewer" is deliberately *not* that path. The set of people
    holding the role is not the set of people assigned to a case, and a policy
    that conflated them would let a reviewer working case A read case B - the
    two cases they might later be asked to compare. So the permit binds an
    actor, a case, an assignment, a stage, a protocol hash and a release hash,
    and every one of those must match.
    """
    if action in (AccessAction.LIST_METADATA, AccessAction.READ_METADATA,
                  AccessAction.AUDIT_PARTITION):
        return AccessDecision(True, "")

    if case.role is ValidationCaseRole.EXPERT_HOLDOUT:
        if _permit_authorises(case, context, permit):
            return AccessDecision(True, "")
        return AccessDecision(False,
                              "EXPERT_HOLDOUT_REQUIRES_PERMITTED_WORKFLOW")
    if case.role in HOLDOUT_ROLES and context.is_author_context:
        return AccessDecision(False, "AUTHOR_CONTEXT_MAY_NOT_READ_HOLDOUT")
    if case.visibility is VisibilityLevel.AUTHOR_VISIBLE:
        return AccessDecision(True, "")
    if case.visibility is VisibilityLevel.RESTRICTED and \
            not context.is_author_context:
        return AccessDecision(True, "")
    return AccessDecision(False, "PAYLOAD_NOT_AUTHOR_VISIBLE")


@dataclass(frozen=True, slots=True)
class AccessEvent:
    """One attempt. Immutable, and the ledger appends only.

    Carries the case's *metadata* hash rather than any payload identity, so a
    reader of the ledger learns which version of the public record was in
    force and nothing about content.
    """

    case_id: str
    case_role: str
    actor: str
    context_kind: str
    action: str
    allowed: bool
    reason_code: str
    occurred_at: _dt.datetime
    manifest_hash: str
    purpose: str = ""
    schema_version: str = ACCESS_EVENT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "occurred_at",
                           ensure_utc(self.occurred_at, "occurred_at"))

    def to_json(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "case_role": self.case_role,
            "actor": self.actor,
            "actor_authenticated": False,
            "context_kind": self.context_kind,
            "purpose": self.purpose,
            "action": self.action,
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "occurred_at": self.occurred_at.isoformat().replace("+00:00",
                                                                "Z"),
            "manifest_hash": self.manifest_hash,
        }

    def event_hash(self) -> str:
        return sha256_digest(self.to_json())


class AccessLedger:
    """Append-only who-has-seen evidence.

    Append-only is enforced rather than documented: the ledger exposes no way
    to replace or remove an entry, :meth:`events` returns a tuple, and each
    event carries the digest of the one before it. Editing an old event
    therefore breaks the chain from that point on, and :meth:`verify_chain`
    says where.

    In-memory here. Durable storage is a persistence decision this work
    package does not need to make, and making it would mean choosing a
    migration and a table before anyone has written a single holdout case.
    """

    def __init__(self, clock: Optional[Callable[[], _dt.datetime]] = None
                 ) -> None:
        self._events: List[AccessEvent] = []
        self._chain: List[str] = []
        self._clock = clock or (lambda: _dt.datetime.now(_dt.timezone.utc))

    def record(self, case: ValidationCaseMetadata, context: AccessContext,
               action: AccessAction, decision: AccessDecision) -> AccessEvent:
        """Append one event. Returns it; the ledger keeps its own copy."""
        event = AccessEvent(
            case_id=case.case_id.value,
            case_role=case.role.value,
            actor=context.actor,
            context_kind=context.kind.value,
            action=action.value,
            allowed=decision.allowed,
            reason_code=decision.reason_code,
            occurred_at=self._clock(),
            manifest_hash=case.metadata_hash(),
            purpose=context.purpose)
        previous = self._chain[-1] if self._chain else "sha256:" + "0" * 64
        self._events.append(event)
        self._chain.append(sha256_digest({"previous": previous,
                                          "event": event.to_json()}))
        return event

    def attempt(self, case: ValidationCaseMetadata, context: AccessContext,
                action: AccessAction) -> AccessDecision:
        """Decide, record, and return the decision. The normal entry point.

        Recording happens for refusals too, and before the caller can act on
        the answer, so a caller cannot read a payload without leaving a trace
        by ignoring the return value.
        """
        decision = decide_access(case, context, action)
        self.record(case, context, action, decision)
        return decision

    def read_payload(self, case: ValidationCaseMetadata,
                     context: AccessContext,
                     payload_loader: Callable[[], Any]) -> Any:
        """Read a payload if permitted, raising an identical error if not.

        ``payload_loader`` is called only after the decision, so a refused
        read never touches restricted storage - the refusal cannot be timed to
        infer whether a payload is there.
        """
        decision = self.attempt(case, context, AccessAction.READ_PAYLOAD)
        if not decision.allowed:
            raise AccessDeniedError(case.case_id.value, decision.reason_code)
        return payload_loader()

    def events(self) -> Tuple[AccessEvent, ...]:
        return tuple(self._events)

    def events_for(self, case_id: str) -> Tuple[AccessEvent, ...]:
        return tuple(event for event in self._events
                     if event.case_id == case_id)

    def who_has_seen(self, case_id: str) -> Tuple[str, ...]:
        """Actors whose payload read was allowed. Sorted, de-duplicated."""
        return tuple(sorted({event.actor for event in self._events
                             if event.case_id == case_id and event.allowed
                             and event.action ==
                             AccessAction.READ_PAYLOAD.value}))

    def verify_chain(self) -> Tuple[bool, Optional[int]]:
        """``(intact, first_broken_index)``. The append-only proof."""
        previous = "sha256:" + "0" * 64
        for index, event in enumerate(self._events):
            expected = sha256_digest({"previous": previous,
                                      "event": event.to_json()})
            if expected != self._chain[index]:
                return False, index
            previous = self._chain[index]
        return True, None

    def to_json(self) -> Dict[str, Any]:
        return {"schema_version": ACCESS_EVENT_VERSION,
                "event_count": len(self._events),
                "events": [event.to_json() for event in self._events],
                "chain_head": self._chain[-1] if self._chain else None}
