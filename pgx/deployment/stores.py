# -*- coding: utf-8 -*-
"""Row-to-record adapters (WP-24).

WP-23 defined its ports in terms of frozen dataclasses - ``UserRecord``,
``SessionRecord``, ``GovernedAuditEvent`` - and WP-02's persistence layer
speaks ORM rows. Neither side should know about the other: the security
services must stay testable with no database, and the ORM must stay free of
domain rules. This module is the seam, and it is the only place in the project
where a row and a record are both in scope.

Two things it deliberately does not do:

**It does not cache.** A record handed out here is built from the row as it is
now, inside the caller's transaction. A cache would serve a revoked session
after the revocation committed, which is the failure mode the
``auth_generation`` lever exists to make impossible.

**It does not open or close transactions.** Every store here is constructed
with a *session*, not a factory, and that session belongs to one request. The
commit is the caller's, so a governed change and the audit record of it are
committed together or not at all - which is the whole atomicity requirement,
implemented by not having a transaction of its own to get wrong.

The one exception is documented where it lives: the rate-limit counter in
:mod:`pgx.deployment.rate_limit_store` keeps its own transaction, because a
refused login must still be counted after its transaction rolls back.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from typing import Any, Optional, Sequence, Tuple

from pgx.infrastructure.audit.models import (AUDIT_STREAM_ID,
                                             GovernedAuditEvent)
from pgx.infrastructure.audit.ports import AuditReader, AuditSink
from pgx.infrastructure.audit.vocabulary import AuditOutcome, GovernedAction
from pgx.infrastructure.db.security import (GovernedAuditEventRow,
                                            GovernedAuditStreamHeadRow,
                                            SecuritySessionRow,
                                            SecurityUserRow,
                                            SqlAlchemyAuditRepository,
                                            SqlAlchemySessionRepository,
                                            SqlAlchemyUserRepository)
from pgx.security.sessions import SessionRecord
from pgx.security.users import UserRecord
from pgx.security.vocabulary import (AuthAssurance, AuthMechanism,
                                     SessionRevocationReason, UserStatus)

__all__ = [
    "SqlAlchemyAuditStore",
    "SqlAlchemySessionStore",
    "SqlAlchemyUserStore",
    "audit_event_to_row",
    "row_to_audit_event",
    "row_to_session_record",
    "row_to_user_record",
]


def _aware(value: Optional[_dt.datetime]) -> Optional[_dt.datetime]:
    """Attach UTC to a naive timestamp read back from the database.

    ``TIMESTAMP(timezone=True)`` returns aware values from PostgreSQL, but a
    driver or a dialect that returned naive ones would make every expiry
    comparison in ``SessionRecord`` raise. Normalising here means the security
    layer never has to ask which it got.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=_dt.timezone.utc)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def row_to_user_record(row: SecurityUserRow) -> UserRecord:
    return UserRecord(
        user_id=row.user_id,
        username=row.username,
        role=row.role,
        password_hash=row.password_hash,
        status=UserStatus(row.status),
        auth_generation=int(row.auth_generation),
        failed_login_count=int(row.failed_login_count),
        locked_until=_aware(row.locked_until),
        created_at=_aware(row.created_at),  # type: ignore[arg-type]
        updated_at=_aware(row.updated_at),  # type: ignore[arg-type]
        password_changed_at=_aware(  # type: ignore[arg-type]
            row.password_changed_at),
        created_by=row.created_by,
        is_bootstrap_admin=bool(row.is_bootstrap_admin),
    )


def _apply_user_record(row: SecurityUserRow, record: UserRecord) -> None:
    """Copy a record onto a row. ``user_id`` and ``username`` are not copied.

    Changing either would turn an update into an impersonation: every audit
    row already written names this actor, and rewriting the identity under
    them would silently reattribute their history. A rename is a new account.
    """
    row.role = record.role
    row.password_hash = record.password_hash
    row.status = record.status.value
    row.auth_generation = record.auth_generation
    row.failed_login_count = record.failed_login_count
    row.locked_until = record.locked_until
    row.updated_at = record.updated_at
    row.password_changed_at = record.password_changed_at
    row.is_bootstrap_admin = record.is_bootstrap_admin


class SqlAlchemyUserStore:
    """``UserStore`` over one request's session."""

    def __init__(self, session: Any) -> None:
        self._session = session
        self._repository = SqlAlchemyUserRepository(session)

    def by_username(self, username: str) -> Optional[UserRecord]:
        row = self._repository.by_username(username)
        return None if row is None else row_to_user_record(row)

    def by_id(self, user_id: str) -> Optional[UserRecord]:
        row = self._repository.by_id(user_id)
        return None if row is None else row_to_user_record(row)

    def count(self) -> int:
        return self._repository.count()

    def save(self, user: UserRecord) -> UserRecord:
        """Update in place, or insert when the account does not yet exist.

        No ``delete``. WP-23's lifecycle has no ``DELETED`` status and this
        store offers no way to invent one.
        """
        row = self._repository.by_id(user.user_id)
        if row is None:
            row = SecurityUserRow(
                id=uuid.uuid4(),
                user_id=user.user_id,
                username=user.username,
                role=user.role,
                password_hash=user.password_hash,
                password_policy_version="",
                status=user.status.value,
                auth_generation=user.auth_generation,
                failed_login_count=user.failed_login_count,
                locked_until=user.locked_until,
                is_bootstrap_admin=user.is_bootstrap_admin,
                created_by=user.created_by,
                created_at=user.created_at,
                updated_at=user.updated_at,
                password_changed_at=user.password_changed_at,
            )
            from pgx.security.passwords import ACTIVE_POLICY
            row.password_policy_version = ACTIVE_POLICY.version
            self._repository.add(row)
        else:
            _apply_user_record(row, user)
        self._session.flush()
        return user


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def row_to_session_record(row: SecuritySessionRow) -> SessionRecord:
    reason = (SessionRevocationReason(row.revocation_reason)
              if row.revocation_reason else None)
    return SessionRecord(
        session_id=row.session_id,
        user_id=row.user_id,
        role=row.role,
        token_digest=row.token_digest,
        csrf_secret=row.csrf_secret,
        auth_generation=int(row.auth_generation),
        created_at=_aware(row.created_at),  # type: ignore[arg-type]
        last_seen_at=_aware(row.last_seen_at),  # type: ignore[arg-type]
        idle_expires_at=_aware(  # type: ignore[arg-type]
            row.idle_expires_at),
        absolute_expires_at=_aware(  # type: ignore[arg-type]
            row.absolute_expires_at),
        revoked_at=_aware(row.revoked_at),
        revocation_reason=reason,
    )


class SqlAlchemySessionStore:
    """``SessionStore`` over one request's session."""

    def __init__(self, session: Any) -> None:
        self._session = session
        self._repository = SqlAlchemySessionRepository(session)

    def by_token_digest(self, digest: str) -> Optional[SessionRecord]:
        row = self._repository.by_token_digest(digest)
        return None if row is None else row_to_session_record(row)

    def save(self, session_record: SessionRecord) -> SessionRecord:
        row = self._repository.by_id(session_record.session_id)
        if row is None:
            row = SecuritySessionRow(
                id=uuid.uuid4(),
                session_id=session_record.session_id,
                user_id=session_record.user_id,
                role=session_record.role,
                token_digest=session_record.token_digest,
                csrf_secret=session_record.csrf_secret,
                auth_generation=session_record.auth_generation,
                created_at=session_record.created_at,
                last_seen_at=session_record.last_seen_at,
                idle_expires_at=session_record.idle_expires_at,
                absolute_expires_at=session_record.absolute_expires_at,
                revoked_at=session_record.revoked_at,
                revocation_reason=(session_record.revocation_reason.value
                                   if session_record.revocation_reason
                                   else None),
            )
            self._repository.add(row)
        else:
            # The token digest is never rewritten. A session's identity is the
            # token that created it; changing it would let one row impersonate
            # another session's cookie.
            row.role = session_record.role
            row.auth_generation = session_record.auth_generation
            row.last_seen_at = session_record.last_seen_at
            row.idle_expires_at = session_record.idle_expires_at
            row.absolute_expires_at = session_record.absolute_expires_at
            row.revoked_at = session_record.revoked_at
            row.revocation_reason = (session_record.revocation_reason.value
                                     if session_record.revocation_reason
                                     else None)
        self._session.flush()
        return session_record

    def revoke_all_for_user(self, user_id: str, *, now: _dt.datetime,
                            reason: SessionRevocationReason) -> int:
        """Mark every live session for this user revoked. Returns the count.

        A sweep is used here *in addition to* the ``auth_generation`` lever
        rather than instead of it: the generation makes revocation correct
        even for a row this sweep missed, and the sweep makes the reason
        visible to whoever reads the table.
        """
        revoked = 0
        for row in self._repository.live_for_user(user_id):
            row.revoked_at = now
            row.revocation_reason = reason.value
            revoked += 1
        self._session.flush()
        return revoked


# ---------------------------------------------------------------------------
# Governed audit
# ---------------------------------------------------------------------------

def audit_event_to_row(event: GovernedAuditEvent) -> GovernedAuditEventRow:
    return GovernedAuditEventRow(
        id=uuid.uuid4(),
        event_id=event.event_id,
        schema_version=event.schema_version,
        stream_id=event.stream_id,
        sequence=event.sequence,
        action=str(event.action),
        outcome=str(event.outcome),
        result_code=event.result_code,
        object_type=event.object_type,
        object_id=event.object_id,
        occurred_at=event.occurred_at,
        actor_id=event.actor_id,
        actor_role=event.actor_role,
        auth_mechanism=str(event.auth_mechanism),
        auth_assurance=str(event.auth_assurance),
        session_reference=event.session_reference,
        request_id=event.request_id,
        input_hash=event.input_hash,
        output_hash=event.output_hash,
        software_id=event.software_id,
        software_hash=event.software_hash,
        dataset_id=event.dataset_id,
        dataset_hash=event.dataset_hash,
        ruleset_id=event.ruleset_id,
        ruleset_hash=event.ruleset_hash,
        release_id=event.release_id,
        release_manifest_hash=event.release_manifest_hash,
        event_metadata=dict(event.metadata),
        previous_hash=event.previous_hash,
        event_hash=event.event_hash(),
    )


def row_to_audit_event(row: GovernedAuditEventRow) -> GovernedAuditEvent:
    return GovernedAuditEvent(
        event_id=row.event_id,
        stream_id=row.stream_id,
        sequence=int(row.sequence),
        action=GovernedAction(row.action),
        outcome=AuditOutcome(row.outcome),
        result_code=row.result_code,
        object_type=row.object_type,
        object_id=row.object_id,
        occurred_at=_aware(row.occurred_at),  # type: ignore[arg-type]
        actor_id=row.actor_id,
        actor_role=row.actor_role,
        # Through their enums, like ``action`` and ``outcome`` above. Passing
        # the raw strings made every read of a stored event raise "an audit
        # event records both the mechanism and its assurance", so the chain
        # could never advance past its first event: appending reads the head
        # first. Nothing caught it because no deployment had ever recorded two
        # governed actions - a real database and a second action is the only
        # thing that surfaces it.
        auth_mechanism=AuthMechanism(row.auth_mechanism),
        auth_assurance=AuthAssurance(row.auth_assurance),
        session_reference=row.session_reference,
        request_id=row.request_id,
        input_hash=row.input_hash,
        output_hash=row.output_hash,
        software_id=row.software_id,
        software_hash=row.software_hash,
        dataset_id=row.dataset_id,
        dataset_hash=row.dataset_hash,
        ruleset_id=row.ruleset_id,
        ruleset_hash=row.ruleset_hash,
        release_id=row.release_id,
        release_manifest_hash=row.release_manifest_hash,
        metadata=dict(row.event_metadata or {}),
        previous_hash=row.previous_hash,
        schema_version=row.schema_version,
    )


class SqlAlchemyAuditStore(AuditSink, AuditReader):
    """Append and read the governed chain, inside the caller's transaction.

    ``append`` locks the stream head row with ``SELECT ... FOR UPDATE`` before
    writing, so two concurrent transactions cannot produce two events at the
    same sequence. The database enforces the same rule again in
    ``pgx_governed_audit_chain_guard``; that is not redundancy for its own
    sake, it is the half of the guarantee that survives a client which does
    not use this class.

    There is no ``update`` and no ``delete``, matching the port and matching
    the trigger.
    """

    def __init__(self, session: Any,
                 *, stream_id: str = AUDIT_STREAM_ID) -> None:
        self._session = session
        self._stream_id = stream_id
        self._repository = SqlAlchemyAuditRepository(session)

    # -- sink ------------------------------------------------------------

    def append(self, event: GovernedAuditEvent) -> GovernedAuditEvent:
        head = self._repository.head_for_update(self._stream_id)
        if head is None:
            raise RuntimeError(
                "the governed audit stream has no head row; migration 0011 "
                "seeds exactly one, and appending without it would start a "
                "second chain nobody would notice")
        expected_sequence = int(head.head_sequence or 0) + 1
        expected_previous = head.head_event_hash
        if event.sequence != expected_sequence or \
                event.previous_hash != expected_previous:
            raise RuntimeError(
                "the audit chain head moved between building this event and "
                "appending it; the append is refused rather than forking the "
                "chain")
        self._repository.append(audit_event_to_row(event))
        # The head is advanced in this transaction too. The database trigger
        # advances it as well; both are correct, and the trigger is what makes
        # the guarantee independent of this code path.
        head.head_sequence = event.sequence
        head.head_event_hash = event.event_hash()
        head.updated_at = event.occurred_at
        self._session.flush()
        return event

    def head(self) -> Optional[GovernedAuditEvent]:
        rows = self._repository.recent(limit=1)
        return row_to_audit_event(rows[0]) if rows else None

    # -- reader ----------------------------------------------------------

    def recent(self, limit: int = 50) -> Tuple[GovernedAuditEvent, ...]:
        rows: Sequence[GovernedAuditEventRow] = self._repository.recent(
            limit=limit)
        # `recent` returns newest first; the chain reads oldest first.
        return tuple(row_to_audit_event(row) for row in reversed(list(rows)))

    def all_events(self) -> Tuple[GovernedAuditEvent, ...]:
        return tuple(row_to_audit_event(row)
                     for row in self._repository.all_events())


def head_row_stream_ids(session: Any) -> Tuple[str, ...]:
    """Every stream the head table knows about.

    Used by readiness: exactly one row is expected, and a second one means two
    chains exist, which no verification of either would reveal.
    """
    from sqlalchemy import select

    return tuple(sorted(
        session.execute(
            select(GovernedAuditStreamHeadRow.stream_id)).scalars()))
