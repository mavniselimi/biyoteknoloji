# -*- coding: utf-8 -*-
"""Ports for the canonical audit stream (WP-23).

Read the class definitions for what is *not* here: there is no ``update``, no
``delete``, no ``truncate`` and no ``rewrite``. Not a private one either. A
repository that could express a mutation and merely chose not to perform one
proves nothing; a repository that cannot express it proves that no code in
this process can perform it, and the database trigger in migration 0011 proves
that no ``psql`` prompt can either.

:class:`AuditSink` is what governed services depend on. It has one method,
which appends and returns the stored event, and it is expected to run inside
the caller's transaction - so a failure propagates and rolls the governed
change back rather than being swallowed into a log line.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence, Tuple

from pgx.infrastructure.audit.models import GovernedAuditEvent

__all__ = [
    "AuditReader",
    "AuditSink",
    "InMemoryAuditStore",
]


class AuditSink:
    """Port: append one event inside the caller's transaction.

    Deliberately not called ``AuditLogger``. A logger is something whose
    failure is tolerable; this is not, and the name is the first thing a
    reader sees.
    """

    def append(self, event: GovernedAuditEvent
               ) -> GovernedAuditEvent:  # pragma: no cover - protocol
        raise NotImplementedError

    def head(self) -> Optional[GovernedAuditEvent]:  # pragma: no cover
        """The current chain tail, for deriving the next sequence."""
        raise NotImplementedError


class AuditReader:
    """Port: read the stream. Read, and verify. Never write."""

    def recent(self, limit: int = 50
               ) -> Sequence[GovernedAuditEvent]:  # pragma: no cover
        raise NotImplementedError

    def all_events(self
                   ) -> Sequence[GovernedAuditEvent]:  # pragma: no cover
        raise NotImplementedError


class InMemoryAuditStore(AuditSink, AuditReader):
    """The test adapter: append-only, with no way to mutate.

    There is no ``update`` and no ``delete``, not even a private one, for the
    same reason WP-22's in-memory review store has none. A test proving
    immutability against a store that *could* mutate proves only that this
    code did not ask - a much weaker statement than the one the SQL trigger
    makes.

    ``fail_next_append`` exists so the atomic-rollback path is exercised
    rather than assumed.
    """

    def __init__(self) -> None:
        self._events: list = []
        self.fail_next_append = False

    def append(self, event: GovernedAuditEvent) -> GovernedAuditEvent:
        if self.fail_next_append:
            self.fail_next_append = False
            raise RuntimeError("the audit store is unavailable")
        tail = self._events[-1] if self._events else None
        expected_sequence = (tail.sequence + 1) if tail else 1
        expected_previous = tail.event_hash() if tail else None
        # The concurrency guard, in the form this adapter can express. The
        # SQL adapter uses a row lock on the chain head; here the check is
        # that the event being appended was built from the tail this store
        # actually holds. Two callers who both read the same tail cannot both
        # append: the second one's sequence no longer matches.
        if event.sequence != expected_sequence or \
                event.previous_hash != expected_previous:
            raise RuntimeError(
                "the audit chain head moved between building this event and "
                "appending it; the append is refused rather than forking the "
                "chain")
        self._events.append(event)
        return event

    def head(self) -> Optional[GovernedAuditEvent]:
        return self._events[-1] if self._events else None

    def recent(self, limit: int = 50) -> Tuple[GovernedAuditEvent, ...]:
        return tuple(self._events[-max(1, min(int(limit), 500)):])

    def all_events(self) -> Tuple[GovernedAuditEvent, ...]:
        return tuple(self._events)

    def __len__(self) -> int:
        return len(self._events)
