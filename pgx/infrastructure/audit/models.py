# -*- coding: utf-8 -*-
"""The canonical governed audit event, and its hash chain (WP-23).

One record type, hash-linked, append-only, with every field a governed action
needs to be reconstructed and none that could carry a payload.

**The prohibited-field check is a refusal, not a convention.** Construction
walks the whole event - including nested mappings and sequences - and raises
if any key matches :data:`PROHIBITED_AUDIT_FIELDS`. A convention ("don't put
the medication list in the audit event") is followed until the day somebody
writes ``metadata=dict(request)`` in a hurry. A check that walks the structure
is followed on that day too.

**Metadata is a closed vocabulary.** There is no free-form bucket. Every key a
caller may use is in :data:`TYPED_METADATA_KEYS`, and an unknown key is
refused rather than stored - which is what stops the bucket becoming the place
each new caller stashes "just this one extra field".

**The chain covers everything, including the predecessor.** ``event_hash =
sha256(canonical(previous_hash, payload))``. Editing a field changes the
event's own hash; deleting an event breaks the successor's ``previous_hash``;
inserting one breaks the sequence; reordering breaks both. None of the four is
detectable by a timestamp, which is why the chain exists rather than an
``occurred_at`` index.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple

from pgx.infrastructure.audit.vocabulary import (AUDIT_EVENT_VERSION,
                                                 OBJECT_TYPES,
                                                 PROHIBITED_AUDIT_FIELDS,
                                                 TYPED_METADATA_KEYS,
                                                 AuditOutcome, GovernedAction)
from pgx.security.vocabulary import (ACTOR_PATTERN, GOVERNED_ROLES,
                                     AuthAssurance, AuthMechanism)

__all__ = [
    "AUDIT_STREAM_ID",
    "GovernedAuditEvent",
    "ProhibitedAuditFieldError",
    "canonical_bytes",
    "chain_hash",
    "next_event",
    "verify_chain",
]

#: One stream for the whole deployment. A per-area stream would make each area
#: individually verifiable and the ordering *between* areas unverifiable -
#: and "did the release activate before or after the account was disabled" is
#: exactly the question an investigation asks.
AUDIT_STREAM_ID = "pgx-governed"

_ACTOR = re.compile(ACTOR_PATTERN)
_REQUEST_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")


class ProhibitedAuditFieldError(ValueError):
    """An audit event was built with a field that may never be recorded."""


def _reject_prohibited(value: Any, path: str = "$") -> None:
    """Walk a structure and refuse any prohibited key, at any depth.

    Depth matters. The first version of a check like this looks at top-level
    keys only, and the first thing to defeat it is ``{"context": {"password":
    ...}}``.
    """
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in PROHIBITED_AUDIT_FIELDS:
                raise ProhibitedAuditFieldError(
                    "an audit event may never carry %r (at %s); the value was "
                    "not recorded and is not named here" % (lowered, path))
            _reject_prohibited(item, "%s.%s" % (path, key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_prohibited(item, "%s[%d]" % (path, index))


def canonical_bytes(document: Mapping[str, Any]) -> bytes:
    """Deterministic serialization. The same event hashes the same anywhere.

    Sorted keys, no whitespace variation, ASCII-escaped. A chain whose hashes
    depended on dictionary insertion order would verify on the machine that
    wrote it and fail everywhere else, which is indistinguishable from
    tampering.
    """
    return json.dumps(document, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, default=str).encode("utf-8")


def chain_hash(previous_hash: Optional[str],
               payload: Mapping[str, Any]) -> str:
    """Link one event to its predecessor."""
    return "sha256:" + hashlib.sha256(canonical_bytes(
        {"previous_hash": previous_hash, "payload": payload})).hexdigest()


@dataclass(frozen=True, slots=True)
class GovernedAuditEvent:
    """One immutable, hash-linked record of one governed action."""

    event_id: str
    stream_id: str
    sequence: int
    action: GovernedAction
    outcome: AuditOutcome
    result_code: str
    object_type: str
    object_id: str
    occurred_at: _dt.datetime
    actor_id: Optional[str] = None
    actor_role: Optional[str] = None
    auth_mechanism: AuthMechanism = AuthMechanism.NONE
    auth_assurance: AuthAssurance = AuthAssurance.NONE
    session_reference: Optional[str] = None
    request_id: Optional[str] = None
    input_hash: Optional[str] = None
    output_hash: Optional[str] = None
    software_id: Optional[str] = None
    software_hash: Optional[str] = None
    dataset_id: Optional[str] = None
    dataset_hash: Optional[str] = None
    ruleset_id: Optional[str] = None
    ruleset_hash: Optional[str] = None
    release_id: Optional[str] = None
    release_manifest_hash: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    previous_hash: Optional[str] = None
    schema_version: str = AUDIT_EVENT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.action, GovernedAction):
            raise ValueError("an audit event names a GovernedAction")
        if not isinstance(self.outcome, AuditOutcome):
            raise ValueError("an audit event names an AuditOutcome")
        if self.object_type not in OBJECT_TYPES:
            raise ValueError(
                "an audit event names a known object type: "
                + ", ".join(OBJECT_TYPES))
        if self.sequence < 1:
            raise ValueError("audit sequences start at 1")
        for name in ("event_id", "object_id", "result_code"):
            value = getattr(self, name)
            if not isinstance(value, str) or _SAFE_TEXT.match(value) is None:
                raise ValueError(
                    "%s is a bounded printable identifier that can be written "
                    "to an append-only row unescaped" % name)
        if self.actor_id is not None and _ACTOR.match(self.actor_id) is None:
            raise ValueError("actor_id is a bounded actor identifier")
        if self.actor_role is not None and \
                self.actor_role not in GOVERNED_ROLES:
            raise ValueError("actor_role is a governed role, or absent")
        if not isinstance(self.auth_mechanism, AuthMechanism) or \
                not isinstance(self.auth_assurance, AuthAssurance):
            raise ValueError(
                "an audit event records both the mechanism and its assurance")
        # The pairing that stops a fixture claiming to be a person. A
        # SESSION assurance means a validated server-side session existed;
        # nothing else may claim it.
        if self.auth_assurance is AuthAssurance.SESSION and \
                self.auth_mechanism is not AuthMechanism.SESSION:
            raise ValueError(
                "only a validated session may carry SESSION assurance; a "
                "static development token is TEST_STATIC_TOKEN and stays "
                "distinguishable from it forever")
        if self.auth_mechanism is AuthMechanism.SESSION and \
                self.session_reference is None:
            raise ValueError(
                "a session-authenticated event names the session it acted in")
        if self.request_id is not None and \
                _REQUEST_ID.match(self.request_id) is None:
            raise ValueError("a correlation id is a canonical lowercase UUID")
        for name in ("input_hash", "output_hash", "software_hash",
                     "dataset_hash", "ruleset_hash", "release_manifest_hash",
                     "previous_hash"):
            value = getattr(self, name)
            if value is not None and _DIGEST.match(str(value)) is None:
                raise ValueError("%s is a sha256:<hex> digest, or absent"
                                 % name)
        metadata = dict(self.metadata or {})
        unknown = set(metadata) - set(TYPED_METADATA_KEYS)
        if unknown:
            raise ValueError(
                "audit metadata is a closed vocabulary; %s is not declared. "
                "An open bucket would eventually receive a request body."
                % ", ".join(sorted(unknown)))
        _reject_prohibited(metadata, "$.metadata")
        object.__setattr__(self, "metadata", dict(sorted(metadata.items())))
        object.__setattr__(
            self, "occurred_at",
            self.occurred_at.astimezone(_dt.timezone.utc))

    def payload(self) -> dict:
        """What the chain hash covers. Order-independent by construction."""
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "stream_id": self.stream_id,
            "sequence": self.sequence,
            "action": self.action.value,
            "outcome": self.outcome.value,
            "result_code": self.result_code,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "occurred_at": _iso(self.occurred_at),
            "actor_id": self.actor_id,
            "actor_role": self.actor_role,
            "auth_mechanism": self.auth_mechanism.value,
            "auth_assurance": self.auth_assurance.value,
            "session_reference": self.session_reference,
            "request_id": self.request_id,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "software_id": self.software_id,
            "software_hash": self.software_hash,
            "dataset_id": self.dataset_id,
            "dataset_hash": self.dataset_hash,
            "ruleset_id": self.ruleset_id,
            "ruleset_hash": self.ruleset_hash,
            "release_id": self.release_id,
            "release_manifest_hash": self.release_manifest_hash,
            "metadata": dict(self.metadata),
        }

    def event_hash(self) -> str:
        return chain_hash(self.previous_hash, self.payload())

    def to_json(self) -> dict:
        document = self.payload()
        document["previous_hash"] = self.previous_hash
        document["event_hash"] = self.event_hash()
        return document

    def safe_projection(self) -> dict:
        """What ``pgx-audit recent`` may print.

        Identity, action, outcome and position. No hashes of inputs or
        outputs, because those are joinable to the records they cover and a
        reader with a candidate input could confirm a match.
        """
        return {
            "sequence": self.sequence,
            "occurred_at": _iso(self.occurred_at),
            "action": self.action.value,
            "outcome": self.outcome.value,
            "result_code": self.result_code,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "actor_id": self.actor_id,
            "actor_role": self.actor_role,
            "auth_assurance": self.auth_assurance.value,
        }

    def __repr__(self) -> str:  # pragma: no cover - fixed on purpose
        return ("<GovernedAuditEvent seq=%d action=%s outcome=%s>"
                % (self.sequence, self.action.value, self.outcome.value))


def next_event(previous: Optional[GovernedAuditEvent],
               **fields: Any) -> GovernedAuditEvent:
    """Build the next event, linked to the actual chain tail.

    Sequence and predecessor hash are *derived* here rather than accepted as
    arguments, so a caller cannot insert an event out of order or name a
    predecessor that is not the tail. Getting that wrong is the one mistake
    that produces a chain which verifies while being false.
    """
    fields.setdefault("stream_id", AUDIT_STREAM_ID)
    fields["sequence"] = (previous.sequence + 1) if previous else 1
    fields["previous_hash"] = previous.event_hash() if previous else None
    return GovernedAuditEvent(**fields)


def verify_chain(events: Tuple[GovernedAuditEvent, ...]
                 ) -> Tuple[bool, Optional[int], str]:
    """``(intact, first_break_sequence, reason)``.

    The reason names *what* broke and *where*, and never quotes the event.
    A verification report that printed the offending record would be a way to
    read audit content through a command that is supposed to check integrity.
    """
    previous: Optional[GovernedAuditEvent] = None
    for index, event in enumerate(events):
        expected_sequence = (previous.sequence + 1) if previous else 1
        if event.sequence != expected_sequence:
            return (False, event.sequence,
                    "sequence is not contiguous at position %d: expected %d, "
                    "found %d" % (index, expected_sequence, event.sequence))
        expected_previous = previous.event_hash() if previous else None
        if event.previous_hash != expected_previous:
            return (False, event.sequence,
                    "the predecessor hash at sequence %d does not match the "
                    "preceding event" % event.sequence)
        previous = event
    return (True, None, "the chain is contiguous and every link matches")


def _iso(value: _dt.datetime) -> str:
    return value.astimezone(_dt.timezone.utc).isoformat().replace(
        "+00:00", "Z")
