# -*- coding: utf-8 -*-
"""Typed refusals for the security layer (WP-23).

Every error here carries a stable code and a bounded detail mapping. Two rules
apply to all of them and are the reason this module exists rather than a
handful of ``ValueError``s:

**A security error never quotes what it refused.** Not the password, not the
token, not the username on a failed login, not the cookie. An exception
message is a string that ends up in a log aggregator, a stack trace, a bug
report and occasionally an HTTP body, and an exception class that *sometimes*
quotes values is one that eventually quotes the wrong one.

**A failed login is one error, whatever failed.** Unknown username, wrong
password, disabled account and locked account all raise
:class:`AuthenticationFailed` with the same code and empty details. The caller
that needs to distinguish them - the audit sink - is handed the reason
separately by the service, on the server side, and never through the object
that reaches the client.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

__all__ = [
    "AuditAppendError",
    "AuthenticationFailed",
    "AuthorizationDenied",
    "CsrfFailure",
    "PasswordPolicyError",
    "RateLimited",
    "SecurityError",
    "SessionInvalid",
    "UserAdministrationError",
]


class SecurityError(Exception):
    """Base class. Carries a code and bounded details, never a secret."""

    default_code = "SECURITY_ERROR"

    def __init__(self, message: str = "", *, code: Optional[str] = None,
                 details: Optional[Mapping[str, Any]] = None) -> None:
        self.code = code or self.default_code
        self.details = dict(details or {})
        super().__init__(message or self.code)

    def to_json(self) -> dict:
        return {"code": self.code, "details": dict(self.details)}


class AuthenticationFailed(SecurityError):
    """Login did not succeed. Deliberately says nothing about why.

    One class, one code, empty details, for every cause: no such user, wrong
    password, disabled, locked. A caller who could tell them apart could
    enumerate accounts, and the enumeration is worth more to an attacker than
    any single password.
    """

    default_code = "AUTHENTICATION_FAILED"

    def __init__(self, message: str = "authentication failed") -> None:
        super().__init__(message, code=self.default_code, details={})


class SessionInvalid(SecurityError):
    """A presented session is absent, expired, revoked or superseded.

    Carries a reason code because the *server* logs it and the cookie-clearing
    behaviour depends on it. Transports map every value to one client-visible
    outcome.
    """

    default_code = "SESSION_INVALID"


class AuthorizationDenied(SecurityError):
    """A principal exists and does not hold the required permission."""

    default_code = "PERMISSION_DENIED"


class CsrfFailure(SecurityError):
    """A state-changing request carried no valid session-bound token."""

    default_code = "CSRF_TOKEN_INVALID"


class RateLimited(SecurityError):
    """A policy limit was reached, or the limiter could not answer.

    ``retry_after_seconds`` is bounded by the policy rather than computed from
    an attacker-visible clock, so it cannot be used to measure the window.
    """

    default_code = "RATE_LIMITED"

    def __init__(self, message: str = "rate limited", *,
                 policy_id: str = "", retry_after_seconds: int = 1,
                 code: Optional[str] = None) -> None:
        super().__init__(message, code=code or self.default_code,
                         details={"policy_id": policy_id,
                                  "retry_after_seconds": int(
                                      max(1, min(3600, retry_after_seconds)))})
        self.policy_id = policy_id
        self.retry_after_seconds = int(max(1, min(3600, retry_after_seconds)))


class PasswordPolicyError(SecurityError):
    """A password was refused before hashing, or hashing is unavailable.

    Raised for a bound violation and for a missing Argon2 implementation, and
    in neither case does the message contain the password. The unavailable
    case is deliberately an error rather than a fallback: see
    :mod:`pgx.security.passwords`.
    """

    default_code = "PASSWORD_POLICY_VIOLATION"


class UserAdministrationError(SecurityError):
    """A user-lifecycle operation was refused."""

    default_code = "USER_ADMINISTRATION_REFUSED"


class AuditAppendError(SecurityError):
    """The canonical audit append or chain-head update failed.

    Raised so the governed operation rolls back. A governed success whose
    audit row is missing is not a success that was merely poorly recorded - it
    is a state change nobody can account for.
    """

    default_code = "AUDIT_APPEND_FAILED"
