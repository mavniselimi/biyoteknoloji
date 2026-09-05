# -*- coding: utf-8 -*-
"""The governed security vocabulary (WP-23).

Every value a security record may hold, defined once. These strings reach
append-only audit rows that outlive this code, so adding one is an
architecture change rather than a configuration change - the same rule
``apps.api.security.Role`` already states about the three roles.

Ordering is disabled on every enum here, following the project convention and
for a sharper reason than usual: ``LOCKED`` is not "more than" ``DISABLED``,
and ``SESSION`` assurance is not "two levels above" ``NONE``. Any code that
sorted or compared these would be inventing a scale the policy does not have,
and the first thing built on that scale would be ``assurance >= 1``.
"""

from __future__ import annotations

from enum import Enum
from typing import FrozenSet, Mapping, Tuple

__all__ = [
    "ACTOR_PATTERN",
    "AUTH_ASSURANCE_VALUES",
    "GOVERNED_ROLES",
    "PASSWORD_MAX_BYTES",
    "PASSWORD_MIN_LENGTH",
    "SECURITY_ERROR_CODES",
    "SESSION_COOKIE_NAME",
    "PREAUTH_COOKIE_NAME",
    "USERNAME_PATTERN",
    "VOCABULARY_VERSION",
    "AuthAssurance",
    "AuthMechanism",
    "SessionRevocationReason",
    "UserStatus",
]

VOCABULARY_VERSION = "pgx-wp23-security-vocabulary/1"


class _SecurityEnum(str, Enum):
    """String-valued and unordered, following the project convention."""

    def __str__(self) -> str:
        return self.value

    def __lt__(self, other: object) -> bool:  # pragma: no cover - guard
        raise TypeError("%s values are not ordered" % type(self).__name__)

    __gt__ = __le__ = __ge__ = __lt__


class UserStatus(_SecurityEnum):
    """Where a local account is in its lifecycle.

    There is no ``DELETED``. A deleted user would take their audit history's
    subject with them, and an audit trail whose actors can vanish answers no
    question worth asking. Accounts are disabled, never erased.
    """

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    LOCKED = "LOCKED"


class AuthMechanism(_SecurityEnum):
    """How a principal was established, recorded on every audit row."""

    #: Nothing vouched for this actor. CLI and internal callers.
    NONE = "NONE"
    #: WP-16's development fixture. Never production.
    STATIC_TOKEN = "STATIC_TOKEN"
    #: A validated server-side session created by a password login.
    SESSION = "SESSION"


class AuthAssurance(_SecurityEnum):
    """How much the mechanism is worth. Never a number, never ordered.

    The distinction that matters is between ``TEST_STATIC_TOKEN`` and
    ``SESSION``: WP-22's review audit may record ``actor_authenticated: true``
    only for the second. A fixture token proves that a test ran, not that a
    person acted, and an audit row that could not tell them apart would let a
    development run masquerade as evidence.
    """

    NONE = "NONE"
    TEST_STATIC_TOKEN = "TEST_STATIC_TOKEN"
    SESSION = "SESSION"

    @property
    def is_production_capable(self) -> bool:
        return self is AuthAssurance.SESSION


AUTH_ASSURANCE_VALUES: Tuple[str, ...] = tuple(
    item.value for item in AuthAssurance)


class SessionRevocationReason(_SecurityEnum):
    """Why a session stopped being usable. Recorded, never guessed."""

    LOGOUT = "LOGOUT"
    ROTATED_ON_LOGIN = "ROTATED_ON_LOGIN"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"
    ROLE_CHANGED = "ROLE_CHANGED"
    USER_DISABLED = "USER_DISABLED"
    USER_LOCKED = "USER_LOCKED"
    ADMIN_REVOKED = "ADMIN_REVOKED"
    IDLE_EXPIRED = "IDLE_EXPIRED"
    ABSOLUTE_EXPIRED = "ABSOLUTE_EXPIRED"
    GENERATION_SUPERSEDED = "GENERATION_SUPERSEDED"


#: The three governed roles, named identically to ``apps.api.security.Role``
#: and ``pgx.application.execution_context.GOVERNED_ACTOR_ROLES``. Held here
#: as strings so this package does not import the transport that happens to
#: produce them; a test asserts all three spellings are the same set.
GOVERNED_ROLES: FrozenSet[str] = frozenset(
    {"DEMO_USER", "EXPERT_REVIEWER", "ADMIN"})

#: A username is a governed identifier, not a person. No email, no personal
#: name, no phone number: none is needed to authorise a route or fill an audit
#: row, and each would be personal data in a system that has no reason to hold
#: any. Bounded and printable so it can be written to an audit row unescaped.
USERNAME_PATTERN = r"^[a-z0-9][a-z0-9._-]{2,63}$"

#: The actor identifier written to audit rows. Same shape the API already
#: enforces on ``Principal.actor``.
ACTOR_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:@-]{1,63}$"

#: Bounds applied *before* hashing. Argon2 cost is a function of its
#: parameters rather than of input length, but the input still has to be
#: encoded and copied, so an unbounded password is a cheap way to make a
#: server do expensive work. 8 is a floor, not a policy claim: this system has
#: no password-strength meter and does not pretend to.
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_BYTES = 1024

#: Host-scoped cookie names. The ``__Host-`` prefix is enforced by the browser
#: itself: it requires Secure, Path=/ and no Domain attribute, so a
#: misconfiguration that widened the cookie's scope would stop the cookie
#: being accepted at all rather than silently broadening it.
SESSION_COOKIE_NAME = "__Host-pgx_session"
PREAUTH_COOKIE_NAME = "__Host-pgx_preauth"

SECURITY_ERROR_CODES: Mapping[str, str] = {
    "AUTHENTICATION_FAILED":
        "the credential did not authenticate; returned identically for an "
        "unknown username, a wrong password, a disabled account and a locked "
        "account",
    "AUTHENTICATION_NOT_CONFIGURED":
        "this deployment has no authentication provider composed",
    "PASSWORD_HASHING_UNAVAILABLE":
        "Argon2id is not available, and there is no weaker algorithm to fall "
        "back to",
    "PASSWORD_POLICY_VIOLATION":
        "the supplied password violated a declared bound; the value is never "
        "quoted",
    "SESSION_INVALID":
        "the presented session is absent, expired, revoked or superseded",
    "SESSION_STORE_UNAVAILABLE":
        "the server-side session store cannot be reached, so no session can "
        "be validated or created",
    "PERMISSION_DENIED":
        "the principal's role does not hold the required permission",
    "CSRF_TOKEN_INVALID":
        "the state-changing request carried no valid session-bound token",
    "CSRF_NOT_CONFIGURED":
        "no CSRF service is composed, so no state-changing request is "
        "accepted",
    "RATE_LIMITED":
        "a declared rate-limit policy was reached",
    "RATE_LIMIT_UNAVAILABLE":
        "the rate-limit backend could not answer; login and governed "
        "mutations fail closed rather than proceeding unmetered",
    "USER_ADMINISTRATION_REFUSED":
        "a user-lifecycle operation was refused",
    "AUDIT_APPEND_FAILED":
        "the canonical audit append or chain-head update failed, so the "
        "governed state change was rolled back",
}
