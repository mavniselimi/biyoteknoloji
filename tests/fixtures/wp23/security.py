# -*- coding: utf-8 -*-
"""In-memory stores, a fake hasher and a wired service (WP-23, TEST-ONLY).

Two design choices here carry weight.

**The stores have no update-in-place and no delete.** ``save`` replaces a
whole record, which is what the SQL adapter does too; there is no method that
mutates a field and none that removes a row. A test proving append-only
behaviour against a store that *could* delete proves only that this code did
not ask.

**The fake hasher is not a weaker hasher.** It produces a string that is not a
PHC hash and it is used only where the test is about the *service*'s ordering,
never about hashing. Every test that is about hashing skips when
``argon2-cffi`` is absent, with a named reason, rather than silently passing
against a substitute - a substitute would let "passwords are Argon2id" pass in
an environment where no Argon2 exists.
"""

from __future__ import annotations

import datetime as _dt
import itertools
from typing import Dict, List, Optional

from pgx.infrastructure.audit.ports import InMemoryAuditStore
from pgx.infrastructure.audit.service import GovernedAuditService
from pgx.security.passwords import Password, PasswordHasher
from pgx.security.rate_limit import InMemoryRateLimitStore, RateLimiter
from pgx.security.service import (AuthenticationService, SessionStore,
                                  UserStore)
from pgx.security.sessions import SessionPolicy, SessionRecord
from pgx.security.users import UserRecord
from pgx.security.vocabulary import SessionRevocationReason, UserStatus

__all__ = [
    "ADMIN_PASSWORD",
    "DEMO_PASSWORD",
    "InMemorySessionStore",
    "InMemoryUserStore",
    "NOW",
    "RECORDING_HASHER_PREFIX",
    "RecordingHasher",
    "REVIEWER_PASSWORD",
    "SequentialIds",
    "StepClock",
    "make_service",
    "user",
]

NOW = _dt.datetime(2026, 9, 5, 12, 0, tzinfo=_dt.timezone.utc)

#: TEST-ONLY passwords. Literal strings in a public repository, matching no
#: deployment, and marked so the secret scanner classifies rather than ignores
#: them. Long enough to satisfy the policy bound, which is the only reason
#: they are not shorter.
ADMIN_PASSWORD = "TEST-ONLY-admin-passphrase-0001"
REVIEWER_PASSWORD = "TEST-ONLY-reviewer-passphrase-0001"
DEMO_PASSWORD = "TEST-ONLY-demo-passphrase-0001"

RECORDING_HASHER_PREFIX = "$test-only-not-a-real-hash$"


class StepClock:
    """A clock a test moves by hand. No sleeping, no flakiness."""

    def __init__(self, start: _dt.datetime = NOW) -> None:
        self.now = start

    def __call__(self) -> _dt.datetime:
        return self.now

    def advance(self, seconds: int) -> _dt.datetime:
        self.now = self.now + _dt.timedelta(seconds=seconds)
        return self.now


class SequentialIds:
    """Deterministic identifiers so audit hashes are reproducible."""

    def __init__(self) -> None:
        self._counters: Dict[str, int] = {}

    def __call__(self, prefix: str = "EVT") -> str:
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return "%s-TEST-ONLY-%04d" % (prefix, self._counters[prefix])


class RecordingHasher(PasswordHasher):
    """A stand-in for tests about *ordering*, never about hashing.

    Counts ``dummy_verify`` calls so the enumeration-resistance test can
    assert the unknown-username path paid the cost, which is a stronger claim
    than "both responses looked the same".
    """

    def __init__(self, *, obsolete: bool = False) -> None:
        self.dummy_calls = 0
        self.verify_calls = 0
        self._obsolete = obsolete

    def hash(self, password: Password) -> str:
        return RECORDING_HASHER_PREFIX + password.reveal()[::-1]

    def verify(self, encoded: str, password: Password) -> bool:
        self.verify_calls += 1
        return encoded == self.hash(password)

    def needs_rehash(self, encoded: str) -> bool:
        del encoded
        return self._obsolete

    def dummy_verify(self) -> None:
        self.dummy_calls += 1


class InMemoryUserStore(UserStore):
    """Faithful to the real contract: replace whole records, never delete."""

    def __init__(self, users: Optional[List[UserRecord]] = None) -> None:
        self._by_id: Dict[str, UserRecord] = {}
        for item in users or ():
            self._by_id[item.user_id] = item

    def by_username(self, username: str) -> Optional[UserRecord]:
        for item in self._by_id.values():
            if item.username == username:
                return item
        return None

    def by_id(self, user_id: str) -> Optional[UserRecord]:
        return self._by_id.get(user_id)

    def save(self, user: UserRecord) -> UserRecord:
        self._by_id[user.user_id] = user
        return user

    def count(self) -> int:
        return len(self._by_id)

    def all_users(self):
        return tuple(self._by_id.values())


class InMemorySessionStore(SessionStore):
    """Keyed by token digest, because that is what the real table is keyed by."""

    def __init__(self) -> None:
        self._by_id: Dict[str, SessionRecord] = {}
        self.fail_next_save = False

    def by_token_digest(self, digest: str) -> Optional[SessionRecord]:
        for item in self._by_id.values():
            if item.token_digest == digest:
                return item
        return None

    def by_id(self, session_id: str) -> Optional[SessionRecord]:
        return self._by_id.get(session_id)

    def save(self, session: SessionRecord) -> SessionRecord:
        if self.fail_next_save:
            self.fail_next_save = False
            raise RuntimeError("the session store is unavailable")
        self._by_id[session.session_id] = session
        return session

    def revoke_all_for_user(self, user_id: str, *, now: _dt.datetime,
                            reason: SessionRevocationReason) -> int:
        revoked = 0
        for key, item in list(self._by_id.items()):
            if item.user_id == user_id and not item.is_revoked:
                self._by_id[key] = item.revoked(now, reason)
                revoked += 1
        return revoked

    def all_sessions(self):
        return tuple(self._by_id.values())


def user(*, user_id: str = "TEST-ONLY-user-1", username: str = "test-admin",
         role: str = "ADMIN", password: str = ADMIN_PASSWORD,
         status: UserStatus = UserStatus.ACTIVE, generation: int = 1,
         hasher: Optional[PasswordHasher] = None,
         now: _dt.datetime = NOW) -> UserRecord:
    """One TEST-ONLY user, hashed by whichever hasher the test supplies."""
    hasher = hasher or RecordingHasher()
    return UserRecord(
        user_id=user_id, username=username, role=role,
        password_hash=hasher.hash(Password(password)), status=status,
        auth_generation=generation, failed_login_count=0, locked_until=None,
        created_at=now, updated_at=now, password_changed_at=now,
        created_by="TEST-ONLY-bootstrap")


class _NotAHash(str):
    """A hash whose prefix check the record must accept in fixtures."""


def make_service(*, users=None, hasher: Optional[PasswordHasher] = None,
                 limiter: Optional[RateLimiter] = None,
                 clock: Optional[StepClock] = None,
                 policy: Optional[SessionPolicy] = None):
    """A wired TEST-ONLY authentication service and every store it holds."""
    clock = clock or StepClock()
    hasher = hasher or RecordingHasher()
    user_store = InMemoryUserStore(list(users or []))
    session_store = InMemorySessionStore()
    audit_store = InMemoryAuditStore()
    ids = SequentialIds()
    audit = GovernedAuditService(audit_store, clock=clock,
                                 id_factory=lambda: ids("EVT"))
    service = AuthenticationService(
        users=user_store, sessions=session_store, hasher=hasher, audit=audit,
        policy=policy or SessionPolicy(), limiter=limiter, clock=clock,
        id_factory=ids, token_factory=_sequential_tokens())
    return service, user_store, session_store, audit_store, clock, hasher


def _sequential_tokens():
    """Deterministic tokens so a test can assert digests, never entropy.

    Entropy is asserted separately, against the *real* generator: a
    deterministic token here would make that test vacuous, so the two are
    never the same function.
    """
    counter = itertools.count(1)
    return lambda: "TEST-ONLY-session-token-%08d-%s" % (
        next(counter), "x" * 24)
