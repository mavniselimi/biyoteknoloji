# -*- coding: utf-8 -*-
"""WP-23 authentication, session and canonical audit persistence.

Five tables, and the decomposition follows what each one is evidence *of*:

| Table | Answers |
|---|---|
| ``security_users`` | who may act, in what role, and whether they still may |
| ``security_sessions`` | which browser sessions the server issued and which are still live |
| ``security_rate_limit_counters`` | how many attempts a keyed bucket has seen |
| ``governed_audit_events`` | the hash-linked record of every governed act |
| ``governed_audit_stream_head`` | the chain tail, locked when appending |

**The head table is not redundant.** Deriving the tail with ``SELECT max(
sequence)`` and then inserting is a read-then-write race whose losing side is
a forked chain - two events at the same sequence, both valid-looking. One row
per stream, locked ``FOR UPDATE`` before the append, makes the fork
impossible rather than unlikely.

**Nothing here stores a raw credential.** ``security_users`` holds an encoded
Argon2id PHC string; ``security_sessions`` holds ``sha256(token)`` and a
per-session CSRF secret, never the cookie value. A database dump therefore
contains nothing replayable, which is the difference between a leaked backup
and a compromised fleet.

**Historical audit tables are untouched.** ``audit_events`` from migration
0002, the curation trail from 0007 and WP-22's review trail from 0010 all keep
their rows and their meaning. Nothing is backfilled into the canonical stream:
a historical row was written by a system with no authentication, and giving it
an actor and an assurance level would be manufacturing provenance.

**PostgreSQL is unavailable in this environment.** The mappings, constraints
and migration are written and unit-tested against the metadata; no statement
has been executed against a server, and nothing here claims otherwise.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import (Boolean, CheckConstraint, ForeignKey, Index, Integer,
                        String, UniqueConstraint, select)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from pgx.infrastructure.audit.vocabulary import (AUDIT_ACTIONS, OBJECT_TYPES,
                                                 AuditOutcome)
from pgx.infrastructure.db.base import Base
from pgx.infrastructure.db.models import SHA256_DIGEST_REGEX, _in_list, _uuid_pk
from pgx.security.vocabulary import (AUTH_ASSURANCE_VALUES, GOVERNED_ROLES,
                                     AuthMechanism, SessionRevocationReason,
                                     UserStatus)

__all__ = [
    "GOVERNED_AUDIT_TABLES",
    "GovernedAuditEventRow",
    "GovernedAuditStreamHeadRow",
    "SECURITY_TABLES",
    "SecurityRateLimitCounterRow",
    "SecuritySessionRow",
    "SecurityUserRow",
    "SqlAlchemyAuditRepository",
    "SqlAlchemySessionRepository",
    "SqlAlchemyUserRepository",
]

_USER_STATUSES = tuple(item.value for item in UserStatus)
_MECHANISMS = tuple(item.value for item in AuthMechanism)
_REVOCATION_REASONS = tuple(item.value for item in SessionRevocationReason)
_OUTCOMES = tuple(item.value for item in AuditOutcome)

SECURITY_TABLES: Tuple[str, ...] = (
    "security_users", "security_sessions", "security_rate_limit_counters")
GOVERNED_AUDIT_TABLES: Tuple[str, ...] = (
    "governed_audit_events", "governed_audit_stream_head")


def _digest_check(column: str) -> str:
    return "%s IS NULL OR %s ~ '%s'" % (column, column, SHA256_DIGEST_REGEX)


class SecurityUserRow(Base):
    """One local account.

    ``username`` is unique and already canonical - lowercased once, in
    :func:`pgx.security.users.canonical_username`, so "Alice" and "alice"
    cannot become two accounts that look like one in an audit row.

    ``auth_generation`` is the revocation lever. A session records the
    generation it was created under, and every account change that must
    invalidate sessions increments it; the session check then fails on the
    next request without a sweep that could be interrupted halfway.
    """

    __tablename__ = "security_users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    # Never nullable. An ACTIVE account with no hash would be an account whose
    # login path has nothing to compare against, and that branch is exactly
    # the one an attacker wants to reach.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    password_policy_version: Mapped[str] = mapped_column(
        String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        server_default="ACTIVE")
    auth_generation: Mapped[int] = mapped_column(Integer, nullable=False,
                                                 server_default="1")
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False,
                                                    server_default="0")
    locked_until: Mapped[Optional[_dt.datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True)
    is_bootstrap_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false")
    created_by: Mapped[Optional[str]] = mapped_column(String(128),
                                                      nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)
    updated_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)
    password_changed_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_security_users_user_id"),
        UniqueConstraint("username", name="uq_security_users_username"),
        CheckConstraint(_in_list("role", sorted(GOVERNED_ROLES)),
                        name="role_enum"),
        CheckConstraint(_in_list("status", _USER_STATUSES),
                        name="status_enum"),
        CheckConstraint("username = lower(username)",
                        name="username_is_canonical"),
        # The stored hash is an encoded PHC string and, specifically,
        # argon2id. A row holding a bcrypt or PBKDF2 hash would mean some
        # other code path wrote it, which is the thing there must not be.
        CheckConstraint("password_hash LIKE '$argon2id$%'",
                        name="password_hash_is_argon2id"),
        CheckConstraint("auth_generation >= 1", name="generation_positive"),
        CheckConstraint("failed_login_count >= 0",
                        name="failure_count_not_negative"),
        # A locked account names when the lock ends; an unlocked one does not
        # carry a stale timestamp that a later reader could misinterpret.
        CheckConstraint("status = 'LOCKED' OR locked_until IS NULL",
                        name="only_a_locked_account_has_a_lock_expiry"),
        Index("ix_security_users_status", "status"),
    )


class SecuritySessionRow(Base):
    """One server-side session. Holds a digest; never a token.

    ``token_digest`` is unique: two sessions sharing one digest would mean two
    rows a single cookie authenticates, which is either a collision or a bug
    and is not something the schema should permit either way.
    """

    __tablename__ = "security_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("security_users.user_id", ondelete="RESTRICT"),
        nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    token_digest: Mapped[str] = mapped_column(String(80), nullable=False)
    csrf_secret: Mapped[str] = mapped_column(String(128), nullable=False)
    auth_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)
    last_seen_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)
    idle_expires_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)
    absolute_expires_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[_dt.datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True)
    revocation_reason: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True)

    __table_args__ = (
        UniqueConstraint("session_id", name="uq_security_sessions_session_id"),
        UniqueConstraint("token_digest",
                         name="uq_security_sessions_token_digest"),
        CheckConstraint(_in_list("role", sorted(GOVERNED_ROLES)),
                        name="role_enum"),
        CheckConstraint("token_digest ~ '%s'" % SHA256_DIGEST_REGEX,
                        name="token_digest_format"),
        CheckConstraint("absolute_expires_at >= idle_expires_at",
                        name="absolute_bound_not_before_idle"),
        CheckConstraint("auth_generation >= 1", name="generation_positive"),
        # A revoked session names why, and an unrevoked one names nothing.
        # Either half alone would let a row say "revoked for no reason" or
        # "not revoked, reason: LOGOUT".
        CheckConstraint(
            "(revoked_at IS NULL) = (revocation_reason IS NULL)",
            name="revocation_names_its_reason"),
        CheckConstraint(
            "revocation_reason IS NULL OR " +
            _in_list("revocation_reason", _REVOCATION_REASONS),
            name="revocation_reason_enum"),
        Index("ix_security_sessions_user_id", "user_id"),
        Index("ix_security_sessions_absolute_expires_at",
              "absolute_expires_at"),
    )


class SecurityRateLimitCounterRow(Base):
    """One keyed bucket in one fixed window.

    ``key_digest`` is a digest of the identity, never the identity. A leaked
    rate-limit table therefore says some key was tried n times and names
    nobody.
    """

    __tablename__ = "security_rate_limit_counters"

    id: Mapped[uuid.UUID] = _uuid_pk()
    policy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    key_digest: Mapped[str] = mapped_column(String(80), nullable=False)
    window_start: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False,
                                           server_default="0")

    __table_args__ = (
        UniqueConstraint("policy_id", "key_digest", "window_start",
                         name="uq_security_rate_limit_counters_bucket"),
        CheckConstraint("key_digest ~ '%s'" % SHA256_DIGEST_REGEX,
                        name="key_digest_format"),
        CheckConstraint("hit_count >= 0", name="hit_count_not_negative"),
        Index("ix_security_rate_limit_counters_window_start", "window_start"),
    )


class GovernedAuditEventRow(Base):
    """One hash-linked governed audit event. Append-only, forever.

    Separate from ``audit_events`` (migration 0002) on purpose. That table is
    the release trail written by a system with no authentication; its rows
    stay exactly as they are and mean exactly what they meant. This is the
    successor stream, and it starts empty.
    """

    __tablename__ = "governed_audit_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    stream_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    result_code: Mapped[str] = mapped_column(String(64), nullable=False)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)
    actor_id: Mapped[Optional[str]] = mapped_column(String(128),
                                                    nullable=True)
    actor_role: Mapped[Optional[str]] = mapped_column(String(32),
                                                      nullable=True)
    auth_mechanism: Mapped[str] = mapped_column(String(24), nullable=False,
                                                server_default="NONE")
    auth_assurance: Mapped[str] = mapped_column(String(24), nullable=False,
                                                server_default="NONE")
    session_reference: Mapped[Optional[str]] = mapped_column(String(128),
                                                             nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(64),
                                                      nullable=True)
    input_hash: Mapped[Optional[str]] = mapped_column(String(80),
                                                      nullable=True)
    output_hash: Mapped[Optional[str]] = mapped_column(String(80),
                                                       nullable=True)
    software_id: Mapped[Optional[str]] = mapped_column(String(128),
                                                       nullable=True)
    software_hash: Mapped[Optional[str]] = mapped_column(String(80),
                                                         nullable=True)
    dataset_id: Mapped[Optional[str]] = mapped_column(String(128),
                                                      nullable=True)
    dataset_hash: Mapped[Optional[str]] = mapped_column(String(80),
                                                        nullable=True)
    ruleset_id: Mapped[Optional[str]] = mapped_column(String(128),
                                                      nullable=True)
    ruleset_hash: Mapped[Optional[str]] = mapped_column(String(80),
                                                        nullable=True)
    release_id: Mapped[Optional[str]] = mapped_column(String(128),
                                                      nullable=True)
    release_manifest_hash: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True)
    event_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict)
    previous_hash: Mapped[Optional[str]] = mapped_column(String(80),
                                                         nullable=True)
    event_hash: Mapped[str] = mapped_column(String(80), nullable=False)

    __table_args__ = (
        UniqueConstraint("event_id", name="uq_governed_audit_events_event_id"),
        UniqueConstraint("stream_id", "sequence",
                         name="uq_governed_audit_events_stream_sequence"),
        UniqueConstraint("event_hash",
                         name="uq_governed_audit_events_event_hash"),
        CheckConstraint(_in_list("action", AUDIT_ACTIONS), name="action_enum"),
        CheckConstraint(_in_list("outcome", _OUTCOMES), name="outcome_enum"),
        CheckConstraint(_in_list("object_type", OBJECT_TYPES),
                        name="object_type_enum"),
        CheckConstraint(_in_list("auth_mechanism", _MECHANISMS),
                        name="mechanism_enum"),
        CheckConstraint(_in_list("auth_assurance", AUTH_ASSURANCE_VALUES),
                        name="assurance_enum"),
        CheckConstraint("actor_role IS NULL OR " +
                        _in_list("actor_role", sorted(GOVERNED_ROLES)),
                        name="actor_role_enum"),
        # The pairing that stops a fixture claiming to be a person, enforced
        # in the database as well as in the model. A row asserting SESSION
        # assurance without the SESSION mechanism is refused by the server.
        CheckConstraint(
            "auth_assurance <> 'SESSION' OR auth_mechanism = 'SESSION'",
            name="only_a_session_has_assurance"),
        CheckConstraint(
            "auth_mechanism <> 'SESSION' OR session_reference IS NOT NULL",
            name="session_event_names_its_session"),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        CheckConstraint("(sequence = 1) = (previous_hash IS NULL)",
                        name="first_event_starts_the_chain"),
        CheckConstraint("event_hash ~ '%s'" % SHA256_DIGEST_REGEX,
                        name="event_hash_format"),
        CheckConstraint(_digest_check("previous_hash"),
                        name="previous_format"),
        CheckConstraint(_digest_check("input_hash"), name="input_format"),
        CheckConstraint(_digest_check("output_hash"),
                        name="output_format"),
        Index("ix_governed_audit_events_occurred_at", "occurred_at"),
        Index("ix_governed_audit_events_object", "object_type", "object_id"),
        Index("ix_governed_audit_events_actor_id", "actor_id"),
    )


class GovernedAuditStreamHeadRow(Base):
    """The chain tail, one row per stream, locked before every append.

    Exists solely to make concurrent appends safe. ``SELECT max(sequence)``
    followed by an insert is a read-then-write race whose losing side is a
    forked chain: two events at the same sequence, each linking to the same
    predecessor, both of which verify in isolation. Locking this row first
    makes the second appender wait and then see the real tail.
    """

    __tablename__ = "governed_audit_stream_head"

    id: Mapped[uuid.UUID] = _uuid_pk()
    stream_id: Mapped[str] = mapped_column(String(64), nullable=False)
    head_sequence: Mapped[int] = mapped_column(Integer, nullable=False,
                                               server_default="0")
    head_event_hash: Mapped[Optional[str]] = mapped_column(String(80),
                                                           nullable=True)
    updated_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("stream_id",
                         name="uq_governed_audit_stream_head_stream_id"),
        CheckConstraint("head_sequence >= 0", name="head_sequence_positive"),
        CheckConstraint("(head_sequence = 0) = (head_event_hash IS NULL)",
                        name="empty_stream_has_no_hash"),
    )


# ---------------------------------------------------------------------------
# Repositories. Reads and appends. No update of an audit row, ever.
# ---------------------------------------------------------------------------


class SqlAlchemyUserRepository:
    """Read and replace user rows. Never delete one.

    ``save`` writes the whole record rather than patching fields, which is
    what the in-memory store does too - so a test against the fake exercises
    the same shape the real adapter uses.
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    def by_username(self, username: str) -> Optional[SecurityUserRow]:
        return self._session.execute(
            select(SecurityUserRow).where(
                SecurityUserRow.username == username)).scalar_one_or_none()

    def by_id(self, user_id: str) -> Optional[SecurityUserRow]:
        return self._session.execute(
            select(SecurityUserRow).where(
                SecurityUserRow.user_id == user_id)).scalar_one_or_none()

    def count(self) -> int:
        from sqlalchemy import func
        return int(self._session.execute(
            select(func.count()).select_from(SecurityUserRow)).scalar() or 0)

    def add(self, row: SecurityUserRow) -> SecurityUserRow:
        self._session.add(row)
        return row


class SqlAlchemySessionRepository:
    """Read, create and revoke sessions. Never delete one.

    A deleted session row removes the evidence that a session existed, which
    is the row an investigation of a compromised account starts from.
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    def by_token_digest(self, digest: str) -> Optional[SecuritySessionRow]:
        return self._session.execute(
            select(SecuritySessionRow).where(
                SecuritySessionRow.token_digest
                == digest)).scalar_one_or_none()

    def by_id(self, session_id: str) -> Optional[SecuritySessionRow]:
        return self._session.execute(
            select(SecuritySessionRow).where(
                SecuritySessionRow.session_id
                == session_id)).scalar_one_or_none()

    def live_for_user(self, user_id: str) -> Sequence[SecuritySessionRow]:
        return list(self._session.execute(
            select(SecuritySessionRow).where(
                SecuritySessionRow.user_id == user_id,
                SecuritySessionRow.revoked_at.is_(None))).scalars())

    def add(self, row: SecuritySessionRow) -> SecuritySessionRow:
        self._session.add(row)
        return row


class SqlAlchemyAuditRepository:
    """Append and read. There is no update and no delete method.

    Not a private one either. A repository that could express a mutation and
    merely chose not to perform one proves nothing; one that cannot express it
    proves that no code in this process can, and the trigger installed by
    migration 0011 proves that no ``psql`` prompt can either.
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    def head_for_update(self, stream_id: str
                        ) -> Optional[GovernedAuditStreamHeadRow]:
        """Lock the head row before appending.

        ``with_for_update`` is the whole concurrency story. Without it two
        transactions read the same tail and produce two events at the same
        sequence, each of which verifies in isolation.
        """
        return self._session.execute(
            select(GovernedAuditStreamHeadRow)
            .where(GovernedAuditStreamHeadRow.stream_id == stream_id)
            .with_for_update()).scalar_one_or_none()

    def append(self, row: GovernedAuditEventRow) -> GovernedAuditEventRow:
        self._session.add(row)
        return row

    def recent(self, limit: int = 50) -> Sequence[GovernedAuditEventRow]:
        bounded = max(1, min(int(limit), 500))
        return list(self._session.execute(
            select(GovernedAuditEventRow)
            .order_by(GovernedAuditEventRow.sequence.desc())
            .limit(bounded)).scalars())

    def all_events(self) -> Sequence[GovernedAuditEventRow]:
        return list(self._session.execute(
            select(GovernedAuditEventRow)
            .order_by(GovernedAuditEventRow.sequence.asc())).scalars())
