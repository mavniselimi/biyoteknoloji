# -*- coding: utf-8 -*-
"""Appending governed audit events, atomically (WP-23).

One class, and the whole of its contribution is the ordering guarantee: the
event is built from the store's *current* head and appended inside the
caller's transaction, so a governed state change and its audit row commit
together or not at all.

Two failure directions are handled differently, on purpose.

**A successful governed change whose audit append fails must roll back.**
:meth:`GovernedAuditService.record` raises :class:`AuditAppendError`, the
caller's ``with`` block exits without committing, and the state change is
gone. A success nobody can account for is worse than a refusal: the refusal
tells the operator something happened.

**A refused operation whose audit append fails must stay refused.**
:meth:`record_refusal` swallows its own failure and returns ``False``. If it
raised, an audit outage would convert every controlled refusal into a 500 -
and a 500 is a different answer from a refusal, which is how "the audit
system is down" turns into "the request was actually processed".
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Callable, Mapping, Optional

from pgx.infrastructure.audit.models import GovernedAuditEvent, next_event
from pgx.infrastructure.audit.ports import AuditSink
from pgx.infrastructure.audit.vocabulary import (GOVERNED_ACTION_REGISTRY,
                                                 AuditOutcome, GovernedAction)
from pgx.security.errors import AuditAppendError
from pgx.security.vocabulary import AuthAssurance, AuthMechanism

__all__ = ["AuditContext", "GovernedAuditService"]


class AuditContext:
    """Who is acting and under what assurance, for one unit of work.

    Built on the server from an authenticated principal. There is no
    constructor argument here that a request body could reach, which is the
    mechanical reason a client cannot forge an actor, a role, a session
    reference or an assurance level.
    """

    __slots__ = ("actor_id", "actor_role", "auth_mechanism", "auth_assurance",
                 "session_reference", "request_id")

    def __init__(self, *, actor_id: Optional[str] = None,
                 actor_role: Optional[str] = None,
                 auth_mechanism: AuthMechanism = AuthMechanism.NONE,
                 auth_assurance: AuthAssurance = AuthAssurance.NONE,
                 session_reference: Optional[str] = None,
                 request_id: Optional[str] = None) -> None:
        self.actor_id = actor_id
        self.actor_role = actor_role
        self.auth_mechanism = auth_mechanism
        self.auth_assurance = auth_assurance
        self.session_reference = session_reference
        self.request_id = request_id

    @property
    def is_session_authenticated(self) -> bool:
        """Whether a validated server-side session established this actor.

        WP-22's review audit reads exactly this to decide whether
        ``actor_authenticated`` may be true. A static development token
        answers ``False`` here forever.
        """
        return (self.auth_mechanism is AuthMechanism.SESSION
                and self.auth_assurance is AuthAssurance.SESSION)

    def fields(self) -> dict:
        return {"actor_id": self.actor_id, "actor_role": self.actor_role,
                "auth_mechanism": self.auth_mechanism,
                "auth_assurance": self.auth_assurance,
                "session_reference": self.session_reference,
                "request_id": self.request_id}

    def __repr__(self) -> str:  # pragma: no cover - fixed on purpose
        return ("<AuditContext actor=%s role=%s assurance=%s>"
                % (self.actor_id, self.actor_role, self.auth_assurance.value))


class GovernedAuditService:
    """Append canonical events. Clock and id factory injected for tests."""

    def __init__(self, sink: Optional[AuditSink] = None, *,
                 clock: Optional[Callable[[], _dt.datetime]] = None,
                 id_factory: Optional[Callable[[], str]] = None) -> None:
        self._sink = sink
        self._clock = clock or (
            lambda: _dt.datetime.now(_dt.timezone.utc))
        self._id_factory = id_factory or _uuid_id

    @property
    def available(self) -> bool:
        return self._sink is not None

    def record(self, action: GovernedAction, *, outcome: AuditOutcome,
               result_code: str, object_type: str, object_id: str,
               context: Optional[AuditContext] = None,
               metadata: Optional[Mapping[str, Any]] = None,
               **identity: Any) -> GovernedAuditEvent:
        """Append one event, or raise so the caller rolls back.

        ``identity`` carries the input/output and software/dataset/ruleset/
        release fields. Passed through rather than enumerated so that adding a
        pinned identity to the event model does not require editing every call
        site - and refused by the event's own constructor if it is not a
        declared field.
        """
        if action.value not in GOVERNED_ACTION_REGISTRY:  # pragma: no cover
            raise AuditAppendError(
                "%s is not a registered governed action" % action.value)
        if self._sink is None:
            raise AuditAppendError(
                "no canonical audit sink is composed, so this governed action "
                "cannot be recorded and must not proceed",
                code="AUDIT_APPEND_FAILED")
        ctx = context or AuditContext()
        try:
            event = next_event(
                self._sink.head(),
                event_id=self._id_factory(),
                action=action, outcome=outcome, result_code=result_code,
                object_type=object_type, object_id=object_id,
                occurred_at=self._clock(),
                metadata=dict(metadata or {}),
                **ctx.fields(), **identity)
            return self._sink.append(event)
        except AuditAppendError:  # pragma: no cover - already typed
            raise
        except Exception as error:  # noqa: BLE001 - every failure rolls back
            raise AuditAppendError(
                "the canonical audit append failed, so the governed action "
                "was rolled back", code="AUDIT_APPEND_FAILED") from error

    def record_refusal(self, action: GovernedAction, *, result_code: str,
                       object_type: str, object_id: str,
                       context: Optional[AuditContext] = None,
                       metadata: Optional[Mapping[str, Any]] = None,
                       outcome: AuditOutcome = AuditOutcome.REFUSED) -> bool:
        """Best-effort record of a refusal. Never raises.

        Returns whether the event was written, so a caller can report the gap
        without changing what it returns to the client. The refusal itself is
        already decided by the time this runs; nothing here may alter it.
        """
        try:
            self.record(action, outcome=outcome, result_code=result_code,
                        object_type=object_type, object_id=object_id,
                        context=context, metadata=metadata)
            return True
        except Exception:  # noqa: BLE001 - a refusal stays a refusal
            return False


def _uuid_id() -> str:
    import uuid
    return "EVT-" + uuid.uuid4().hex
