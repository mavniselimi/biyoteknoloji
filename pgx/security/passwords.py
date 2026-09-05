# -*- coding: utf-8 -*-
"""Argon2id password hashing, or an error. There is no third outcome (WP-23).

Read the module for what is *absent*: there is no PBKDF2 branch, no scrypt
branch, no ``hashlib`` import, no development mode that skips hashing and no
"if argon2 is missing, use X" anywhere. The only import of a hashing primitive
in this file is ``argon2``, and if it cannot be imported every entry point
raises :class:`~pgx.security.errors.PasswordPolicyError` with
``PASSWORD_HASHING_UNAVAILABLE``.

That refusal is the design, not a gap in it. A fallback would be reached in
exactly the situation where it must not be: a deployment whose dependency
install silently failed, which would then hash every password with something
weaker while reporting itself healthy. Failing composition instead makes the
missing dependency an operator's problem at start-up rather than a
cryptographic downgrade nobody notices. ``tests/unit/security`` asserts the
absence by parsing this module's AST, so a future edit that adds a fallback
fails a test rather than a review.

**Parameters are a versioned policy, recorded with every hash.** Argon2's
encoded PHC string already carries its own parameters, which is what makes
``check_needs_rehash`` possible; :data:`ACTIVE_POLICY` names the parameters
this deployment *wants*, so an old hash can be recognised as obsolete and
replaced after a successful login rather than being silently accepted forever.

**Nothing here returns, logs, formats or stores a password.** Not in a repr,
not in an exception, not in a ``__str__``. :class:`Password` exists purely so
that a plaintext value travelling between the CLI and the hasher has a type
whose repr is safe.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from pgx.security.errors import PasswordPolicyError
from pgx.security.vocabulary import PASSWORD_MAX_BYTES, PASSWORD_MIN_LENGTH

__all__ = [
    "ACTIVE_POLICY",
    "PASSWORD_POLICY_VERSION",
    "Argon2PasswordHasher",
    "Password",
    "PasswordHasher",
    "PasswordPolicy",
    "argon2_available",
    "argon2_unavailable_reason",
]

PASSWORD_POLICY_VERSION = "pgx-wp23-password-policy/1"


@dataclass(frozen=True)
class PasswordPolicy:
    """The Argon2id parameters this deployment wants, and their version.

    RFC 9106's second recommended option: 64 MiB of memory, three passes, four
    lanes. Chosen over the first (2 GiB) because this is a single-container
    prototype whose readiness budget is two seconds and whose login path must
    not be a memory-exhaustion lever of its own; chosen over anything smaller
    because the whole point of Argon2 is the memory cost.
    """

    version: str = PASSWORD_POLICY_VERSION
    time_cost: int = 3
    memory_cost_kib: int = 65536
    parallelism: int = 4
    hash_length: int = 32
    salt_length: int = 16

    def __post_init__(self) -> None:
        if self.time_cost < 2:
            raise PasswordPolicyError(
                "the password policy requires at least two passes",
                code="PASSWORD_POLICY_VIOLATION")
        if self.memory_cost_kib < 19456:
            # RFC 9106's minimum recommended memory. Below this the algorithm
            # is Argon2id in name and a fast hash in practice.
            raise PasswordPolicyError(
                "the password policy requires at least 19 MiB of memory",
                code="PASSWORD_POLICY_VIOLATION")
        if self.parallelism < 1 or self.hash_length < 16 or \
                self.salt_length < 16:
            raise PasswordPolicyError(
                "the password policy requires at least one lane and 16-byte "
                "salt and hash lengths",
                code="PASSWORD_POLICY_VIOLATION")

    def to_json(self) -> dict:
        """Safe to publish: parameters are not secrets, and knowing them
        does not help an attacker who still has to pay the memory cost."""
        return {"password_policy_version": self.version,
                "algorithm": "argon2id",
                "time_cost": self.time_cost,
                "memory_cost_kib": self.memory_cost_kib,
                "parallelism": self.parallelism,
                "hash_length": self.hash_length,
                "salt_length": self.salt_length}


ACTIVE_POLICY = PasswordPolicy()


class Password:
    """A plaintext password in transit, with a repr that cannot leak it.

    Wrapping the value is worth one small class because the failure it
    prevents is silent: a plain ``str`` reaching a logger, an exception
    formatter, a debugger frame dump or a ``%r`` in a message is a password in
    a log file, and nothing about that failure is visible in review.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str):
            raise PasswordPolicyError("a password is a string")
        # Bounded before anything else touches it. Not trimmed and not
        # normalised: silently changing a password is a way to make a
        # credential that worked once stop working, with no message.
        encoded = value.encode("utf-8")
        if len(encoded) > PASSWORD_MAX_BYTES:
            raise PasswordPolicyError(
                "the password exceeds the %d-byte bound"
                % PASSWORD_MAX_BYTES)
        if len(value) < PASSWORD_MIN_LENGTH:
            raise PasswordPolicyError(
                "the password is shorter than the %d-character minimum"
                % PASSWORD_MIN_LENGTH)
        self._value = value

    def reveal(self) -> str:
        """The plaintext, for the hasher and for nothing else."""
        return self._value

    def __repr__(self) -> str:  # pragma: no cover - the point is it is fixed
        return "<Password redacted>"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        # Constant-time, and only against another Password: comparing a
        # password to a str with == is the shape of a timing oracle.
        if not isinstance(other, Password):
            return NotImplemented
        return hmac.compare_digest(self._value, other._value)

    def __hash__(self) -> int:  # pragma: no cover - never keyed on
        raise TypeError("a password is not a dictionary key")


def _argon2_module() -> Any:
    """Import argon2, or raise the refusal. The only import site."""
    try:
        import argon2  # noqa: WPS433 - deliberately local and guarded
    except Exception as error:  # noqa: BLE001 - any import failure is the same
        raise PasswordPolicyError(
            "Argon2id is unavailable in this deployment and this system has "
            "no weaker password hash to fall back to",
            code="PASSWORD_HASHING_UNAVAILABLE",
            details={"dependency": "argon2-cffi"}) from error
    return argon2


def argon2_available() -> bool:
    """Whether Argon2id can be used right now. Read by readiness."""
    try:
        _argon2_module()
    except PasswordPolicyError:
        return False
    return True


def argon2_unavailable_reason() -> Optional[str]:
    """A bounded reason string, or ``None`` when Argon2 is available."""
    if argon2_available():
        return None
    return ("the argon2-cffi package is not installed, so no password can be "
            "hashed or verified")


class PasswordHasher:
    """Port: hash and verify. Two methods, no configuration surface."""

    policy: PasswordPolicy = ACTIVE_POLICY

    def hash(self, password: Password) -> str:  # pragma: no cover - protocol
        raise NotImplementedError

    def verify(self, encoded: str,
               password: Password) -> bool:  # pragma: no cover - protocol
        raise NotImplementedError

    def needs_rehash(self, encoded: str) -> bool:  # pragma: no cover
        raise NotImplementedError

    def dummy_verify(self) -> None:  # pragma: no cover - protocol
        raise NotImplementedError


class Argon2PasswordHasher(PasswordHasher):
    """The only implementation. Argon2id through ``argon2-cffi``.

    ``dummy_verify`` is not decoration. Without it, a login for an unknown
    username returns in microseconds while a login for a known one pays 64 MiB
    and three passes, and the difference is measurable from outside - which
    turns the login endpoint into a user-enumeration oracle regardless of how
    identical the response body is. So the service verifies against a fixed
    hash of a value nobody knows, and both paths cost the same.

    That reference hash is computed at construction from ``secrets`` output
    and never leaves the object. It is not a credential: nothing accepts it,
    and it authenticates nobody.
    """

    def __init__(self, policy: PasswordPolicy = ACTIVE_POLICY) -> None:
        argon2 = _argon2_module()
        self.policy = policy
        self._hasher = argon2.PasswordHasher(
            time_cost=policy.time_cost,
            memory_cost=policy.memory_cost_kib,
            parallelism=policy.parallelism,
            hash_len=policy.hash_length,
            salt_len=policy.salt_length,
            type=argon2.low_level.Type.ID)
        self._exceptions = argon2.exceptions
        self._dummy_encoded: Optional[str] = None

    def hash(self, password: Password) -> str:
        """The standard encoded PHC string, carrying its own parameters."""
        if not isinstance(password, Password):
            raise PasswordPolicyError(
                "hashing takes a Password, so a bare string cannot reach the "
                "hasher without passing the bounds check first")
        encoded = self._hasher.hash(password.reveal())
        if not encoded.startswith("$argon2id$"):  # pragma: no cover - guard
            raise PasswordPolicyError(
                "the hasher produced something that is not an argon2id hash",
                code="PASSWORD_HASHING_UNAVAILABLE")
        return encoded

    def verify(self, encoded: str, password: Password) -> bool:
        """``True`` or ``False``. Never raises for a wrong password.

        A verification error and a mismatch are the same answer to the caller,
        because the caller is a login path that must not branch differently on
        a malformed stored hash than on a wrong password.
        """
        if not isinstance(password, Password):
            raise PasswordPolicyError("verification takes a Password")
        try:
            return bool(self._hasher.verify(encoded, password.reveal()))
        except Exception:  # noqa: BLE001 - mismatch and malformed are one answer
            return False

    def needs_rehash(self, encoded: str) -> bool:
        """Whether this stored hash was made under obsolete parameters."""
        try:
            return bool(self._hasher.check_needs_rehash(encoded))
        except Exception:  # noqa: BLE001 - unreadable means replace it
            return True

    def dummy_verify(self) -> None:
        """Pay the verification cost for a username that does not exist."""
        import secrets

        if self._dummy_encoded is None:
            self._dummy_encoded = self._hasher.hash(secrets.token_urlsafe(32))
        try:
            self._hasher.verify(self._dummy_encoded, secrets.token_urlsafe(32))
        except Exception:  # noqa: BLE001 - it always fails; that is the point
            pass

    def __repr__(self) -> str:  # pragma: no cover - fixed on purpose
        return "<Argon2PasswordHasher policy=%s>" % self.policy.version


def describe_hash(encoded: str) -> Tuple[str, bool]:
    """``(algorithm, is_argon2id)`` for a stored hash, without verifying it.

    Used by the security status document and by tests. Returns the algorithm
    segment only - never the salt and never the digest.
    """
    if not isinstance(encoded, str) or not encoded.startswith("$"):
        return ("unknown", False)
    parts = encoded.split("$")
    algorithm = parts[1] if len(parts) > 1 else "unknown"
    return (algorithm, algorithm == "argon2id")
