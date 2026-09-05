# -*- coding: utf-8 -*-
"""Local user records and their lifecycle (WP-23).

A user here is deliberately small: an identifier, a governed role, a password
hash, a status, and the counters that make revocation and lockout work. There
is no email address, no display name, no telephone number and no personal
detail of any kind, because none of them is needed to authorise a route or
fill an audit row - and each would be personal data held by a system that has
no reason to hold any.

**``auth_generation`` is the whole revocation mechanism.** Every session
records the generation it was created under. Changing a password, changing a
role, disabling an account or locking it increments the generation, and every
session created before that increment stops validating on its next request.
One integer beats a sweep over a session table: the sweep can be interrupted
halfway, and the half that did not run is a set of live sessions belonging to
an account somebody just disabled.

**There is no delete.** ``DISABLED`` is the terminal state, and it is
reversible by an administrator. A deleted user takes the subject of their own
audit history with them, and a trail whose actors can vanish cannot answer the
question it exists for.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, replace
from typing import Optional

from pgx.security.errors import UserAdministrationError
from pgx.security.vocabulary import (ACTOR_PATTERN, GOVERNED_ROLES,
                                     USERNAME_PATTERN, UserStatus)

__all__ = [
    "DEFAULT_LOCK_THRESHOLD",
    "DEFAULT_LOCK_WINDOW_SECONDS",
    "UserRecord",
    "canonical_username",
]

#: Failed attempts before an account locks, and how long the lock holds.
#: Declared here rather than configured, so that a deployment cannot raise the
#: threshold to a number that makes lockout decorative.
DEFAULT_LOCK_THRESHOLD = 5
DEFAULT_LOCK_WINDOW_SECONDS = 900

_USERNAME = re.compile(USERNAME_PATTERN)
_ACTOR = re.compile(ACTOR_PATTERN)


def canonical_username(value: str) -> str:
    """Lowercase and validate a username, or refuse it.

    Case-folding happens here and only here, so "Alice" and "alice" cannot
    become two accounts that look like one in an audit row. It is not
    Unicode-normalised: the pattern admits ASCII only, which removes the whole
    class of homoglyph-confusable identifiers rather than trying to detect
    them.
    """
    if not isinstance(value, str):
        raise UserAdministrationError("a username is a string")
    lowered = value.strip().lower()
    if _USERNAME.match(lowered) is None:
        raise UserAdministrationError(
            "a username is 3-64 lowercase characters from a-z, 0-9, dot, "
            "underscore and hyphen, starting alphanumeric; it is an "
            "identifier for this system and never an email address")
    return lowered


@dataclass(frozen=True, slots=True)
class UserRecord:
    """One local account. Immutable; every change returns a new record.

    The password hash is a field rather than a separate table because a user
    without one cannot log in and must not exist in ``ACTIVE``: the invariant
    "an active password account has a hash" is checkable in one place if the
    two live together, and is a join that can return no rows if they do not.
    """

    user_id: str
    username: str
    role: str
    password_hash: str
    status: UserStatus
    auth_generation: int
    failed_login_count: int
    locked_until: Optional[_dt.datetime]
    created_at: _dt.datetime
    updated_at: _dt.datetime
    password_changed_at: _dt.datetime
    created_by: Optional[str] = None
    is_bootstrap_admin: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, str) or \
                _ACTOR.match(self.user_id) is None:
            raise UserAdministrationError(
                "a user id is a bounded printable identifier that can be "
                "written to an audit row unescaped")
        if _USERNAME.match(self.username) is None:
            raise UserAdministrationError(
                "a stored username is already canonical")
        if self.role not in GOVERNED_ROLES:
            raise UserAdministrationError(
                "a user holds exactly one governed role: "
                + ", ".join(sorted(GOVERNED_ROLES)))
        if not isinstance(self.status, UserStatus):
            raise UserAdministrationError("a user status is a UserStatus")
        # The invariant that makes the ACTIVE state mean something. An active
        # account with no hash would be an account whose login path has
        # nothing to compare against, and the branch that handles it is
        # exactly the branch an attacker wants to reach.
        if self.status is UserStatus.ACTIVE and not self.password_hash:
            raise UserAdministrationError(
                "an ACTIVE password account has a password hash")
        if self.password_hash and not self.password_hash.startswith("$"):
            raise UserAdministrationError(
                "a stored password hash is an encoded PHC string")
        if self.auth_generation < 0 or self.failed_login_count < 0:
            raise UserAdministrationError(
                "generation and failure counters do not go backwards")
        if self.created_by is not None and \
                _ACTOR.match(self.created_by) is None:
            raise UserAdministrationError(
                "created_by is a bounded actor identifier, or absent")

    # -- queries ---------------------------------------------------------

    def is_locked_at(self, now: _dt.datetime) -> bool:
        """Whether the lock is still in force at ``now``.

        A lock whose window has elapsed is no longer a lock. Expressed as a
        time comparison rather than a background job, so a deployment with no
        scheduler still unlocks accounts.
        """
        if self.status is not UserStatus.LOCKED:
            return False
        if self.locked_until is None:
            return True
        return now < self.locked_until

    def may_authenticate_at(self, now: _dt.datetime) -> bool:
        """Whether a correct password would be accepted right now."""
        if self.status is UserStatus.DISABLED:
            return False
        if self.status is UserStatus.LOCKED and self.is_locked_at(now):
            return False
        return bool(self.password_hash)

    def safe_projection(self) -> dict:
        """What may be shown, logged, published or returned by an API.

        The password hash is absent by construction rather than by a caller
        remembering to drop it, which is the difference between a rule and a
        habit.
        """
        return {
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role,
            "status": self.status.value,
            "auth_generation": self.auth_generation,
            "locked": self.status is UserStatus.LOCKED,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "password_changed_at": _iso(self.password_changed_at),
            "created_by": self.created_by,
            "is_bootstrap_admin": self.is_bootstrap_admin,
        }

    def __repr__(self) -> str:
        """Fixed, and never carrying the hash.

        A dataclass repr would print ``password_hash='$argon2id$...'`` into
        every exception traceback that happened to hold a user.
        """
        return ("<UserRecord user_id=%s role=%s status=%s generation=%d>"
                % (self.user_id, self.role, self.status.value,
                   self.auth_generation))

    # -- transitions -----------------------------------------------------
    #
    # Each returns a new record. Every one that could invalidate an existing
    # session increments ``auth_generation``, and that is checked by a test
    # rather than left to each call site to remember.

    def with_password(self, password_hash: str,
                      now: _dt.datetime) -> "UserRecord":
        """A new hash, a new generation, and therefore no live sessions."""
        if not password_hash.startswith("$"):
            raise UserAdministrationError(
                "a stored password hash is an encoded PHC string")
        return replace(self, password_hash=password_hash,
                       auth_generation=self.auth_generation + 1,
                       failed_login_count=0, locked_until=None,
                       status=(UserStatus.ACTIVE
                               if self.status is UserStatus.LOCKED
                               else self.status),
                       password_changed_at=now, updated_at=now)

    def with_role(self, role: str, now: _dt.datetime) -> "UserRecord":
        """A new role, and therefore no live sessions.

        A session carries the role it was created with. Without the generation
        bump, an account demoted from ADMIN to DEMO_USER would keep acting as
        an administrator until its session expired on its own.
        """
        if role not in GOVERNED_ROLES:
            raise UserAdministrationError(
                "a user holds exactly one governed role")
        if role == self.role:
            raise UserAdministrationError(
                "the user already holds that role; a no-op role change would "
                "revoke every session for nothing")
        return replace(self, role=role,
                       auth_generation=self.auth_generation + 1,
                       updated_at=now)

    def disabled(self, now: _dt.datetime) -> "UserRecord":
        return replace(self, status=UserStatus.DISABLED,
                       auth_generation=self.auth_generation + 1,
                       updated_at=now)

    def enabled(self, now: _dt.datetime) -> "UserRecord":
        """Re-enable. The generation still moves: an account coming back
        online should not inherit sessions from before it went away."""
        if not self.password_hash:
            raise UserAdministrationError(
                "an account with no password hash cannot be made ACTIVE")
        return replace(self, status=UserStatus.ACTIVE,
                       auth_generation=self.auth_generation + 1,
                       failed_login_count=0, locked_until=None,
                       updated_at=now)

    def with_failed_login(self, now: _dt.datetime, *,
                          threshold: int = DEFAULT_LOCK_THRESHOLD,
                          window_seconds: int = DEFAULT_LOCK_WINDOW_SECONDS
                          ) -> "UserRecord":
        """Count one failure, and lock at the threshold."""
        count = self.failed_login_count + 1
        if count >= threshold and self.status is UserStatus.ACTIVE:
            return replace(
                self, failed_login_count=count, status=UserStatus.LOCKED,
                locked_until=now + _dt.timedelta(seconds=window_seconds),
                auth_generation=self.auth_generation + 1, updated_at=now)
        return replace(self, failed_login_count=count, updated_at=now)

    def with_successful_login(self, now: _dt.datetime) -> "UserRecord":
        """Clear the failure counter. The generation does **not** move.

        Logging in must not invalidate the session the login just created, so
        this is the one state change in this class that leaves the generation
        alone.
        """
        if self.failed_login_count == 0:
            return self
        return replace(self, failed_login_count=0, updated_at=now)

    def unlocked(self, now: _dt.datetime) -> "UserRecord":
        if self.status is not UserStatus.LOCKED:
            raise UserAdministrationError("the account is not locked")
        return replace(self, status=UserStatus.ACTIVE, failed_login_count=0,
                       locked_until=None,
                       auth_generation=self.auth_generation + 1,
                       updated_at=now)

    def with_revoked_sessions(self, now: _dt.datetime) -> "UserRecord":
        """Revoke every session without otherwise changing the account."""
        return replace(self, auth_generation=self.auth_generation + 1,
                       updated_at=now)


def _iso(value: Optional[_dt.datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.astimezone(_dt.timezone.utc).isoformat().replace(
        "+00:00", "Z")
