# -*- coding: utf-8 -*-
"""Deployment secret configuration (WP-24).

Secrets arrive as *files*, mounted by the orchestrator, and this module is the
only place their contents are read. Everything downstream receives a value it
was handed; nothing downstream knows where it came from, which is what keeps a
path or a filename out of a log line that a value would otherwise follow.

Three rules, each with a reason that has bitten somebody:

**Ambiguity is refused, not resolved.** When both ``X`` and ``X_FILE`` are set,
this raises. Preferring one silently means an operator who rotated the file
and forgot the variable keeps running on the old secret, and nothing anywhere
says so. A precedence rule is a bug that looks like a feature.

**Nothing read here is ever reported.** Not in an exception message, not in a
readiness detail, not in a length, not in a prefix, not in a hash the caller
might later print. The errors below name the *variable* and the *problem*, and
the tests assert that the value never appears in the string.

**A file that cannot be read is not an empty secret.** An unreadable mount is
a configuration failure; treating it as "no secret configured" would start an
application with authentication silently unconfigured, which is the exact
fail-open this project spends its readiness probes preventing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

from pgx.deployment.errors import SecretConfigurationError

__all__ = [
    "FILE_SUFFIX",
    "SECRET_VARIABLES",
    "SecretMaterial",
    "read_secret",
    "secret_configuration_report",
]

#: The suffix that turns a variable into a path. One spelling, everywhere.
FILE_SUFFIX = "_FILE"

#: Every secret this deployment reads, with what it is for. Closed on purpose:
#: an undeclared secret is one no configuration report can enumerate and no
#: operator can be told to mount.
SECRET_VARIABLES: Mapping[str, str] = {
    "DATABASE_URL":
        "the PostgreSQL DSN the application connects with",
    "PGX_CSRF_SECRET":
        "the deployment key from which per-session CSRF keys are derived",
    "PGX_BACKUP_ENCRYPTION_KEY":
        "the key backup material is encrypted with before it leaves the host",
    "PGX_RESTORE_TARGET_URL":
        "the DSN of the separate database a restore is verified into",
}

#: The maximum size of a secret file. A mount that is larger than this is a
#: mistake - a log, a certificate bundle, an entire directory pointed at by
#: accident - and reading it into memory to discover that is the wrong order.
MAX_SECRET_BYTES = 16 * 1024


@dataclass(frozen=True)
class SecretMaterial:
    """A secret value and where it came from - never both in one string.

    ``source`` is ``"file"`` or ``"environment"``. It is safe to log because
    it says which *mechanism* supplied the value and nothing about the value.
    """

    variable: str
    value: str
    source: str

    def __repr__(self) -> str:  # pragma: no cover - fixed on purpose
        return "<SecretMaterial %s from %s, value redacted>" % (
            self.variable, self.source)

    def __str__(self) -> str:  # pragma: no cover - fixed on purpose
        return self.__repr__()


def _read_file(variable: str, path: str) -> str:
    file_variable = variable + FILE_SUFFIX
    if not path.strip():
        raise SecretConfigurationError(
            file_variable, "is set to an empty path")
    try:
        size = os.path.getsize(path)
    except OSError:
        raise SecretConfigurationError(
            file_variable,
            "names a path that cannot be inspected; a secret mount that is "
            "not readable is a configuration failure, not an absent secret"
        ) from None
    if size > MAX_SECRET_BYTES:
        raise SecretConfigurationError(
            file_variable,
            "names a file larger than %d bytes, which is not a secret but "
            "something mounted by accident" % MAX_SECRET_BYTES)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except OSError:
        raise SecretConfigurationError(
            file_variable,
            "names a path that could not be read; a secret mount that is "
            "not readable is a configuration failure, not an absent secret"
        ) from None
    except UnicodeDecodeError:
        raise SecretConfigurationError(
            file_variable, "names a file that is not UTF-8 text") from None
    # Exactly one trailing newline is stripped. `echo secret > file` adds one,
    # and a DSN with a newline in it fails to parse in a way that quotes the
    # DSN back in the error - which is the disclosure this module prevents.
    # Nothing else is trimmed: leading and interior whitespace may be part of
    # a passphrase, and silently changing a secret is worse than rejecting it.
    if raw.endswith("\n"):
        raw = raw[:-1]
    if not raw:
        raise SecretConfigurationError(
            file_variable, "names a file that is empty")
    return raw


def read_secret(variable: str, *,
                environ: Optional[Mapping[str, str]] = None,
                required: bool = False) -> Optional[SecretMaterial]:
    """Read one secret from its ``_FILE`` mount or its variable.

    Returns ``None`` when neither is set and ``required`` is false. Raises
    when both are set, when a named file is unusable, or when a required
    secret is absent.
    """
    if variable not in SECRET_VARIABLES:
        raise SecretConfigurationError(
            variable, "is not a declared deployment secret")
    source = dict(os.environ if environ is None else environ)
    file_variable = variable + FILE_SUFFIX
    raw_value = source.get(variable, "")
    raw_path = source.get(file_variable, "")

    if raw_value.strip() and raw_path.strip():
        raise SecretConfigurationError(
            variable,
            "is set both directly and as %s; a precedence rule here would "
            "let a rotated file be ignored in favour of a stale variable, so "
            "the ambiguity is refused instead" % file_variable)
    if raw_path.strip():
        return SecretMaterial(variable=variable,
                              value=_read_file(variable, raw_path),
                              source="file")
    if raw_value.strip():
        return SecretMaterial(variable=variable, value=raw_value,
                              source="environment")
    if required:
        raise SecretConfigurationError(
            variable,
            "is not configured; set it or mount %s" % file_variable)
    return None


def secret_configuration_report(
        environ: Optional[Mapping[str, str]] = None) -> Mapping[str, object]:
    """Which secrets are configured and by which mechanism.

    Safe to publish. Every field is a boolean or a mechanism name; no value,
    no path, no length and no digest of a secret appears, because a digest of
    a low-entropy secret is a secret.
    """
    source = dict(os.environ if environ is None else environ)
    entries = []
    ambiguous = []
    for variable, purpose in sorted(SECRET_VARIABLES.items()):
        file_variable = variable + FILE_SUFFIX
        has_value = bool(source.get(variable, "").strip())
        has_file = bool(source.get(file_variable, "").strip())
        if has_value and has_file:
            ambiguous.append(variable)
        entries.append({
            "variable": variable,
            "purpose": purpose,
            "configured": has_value or has_file,
            "mechanism": ("ambiguous" if has_value and has_file
                          else "file" if has_file
                          else "environment" if has_value else None),
            "file_preferred": True,
        })
    return {
        "secrets": entries,
        "ambiguous_variables": sorted(ambiguous),
        "file_suffix": FILE_SUFFIX,
        "no_value_is_reported": (
            "This document names variables and mechanisms. No secret value, "
            "path, length or digest appears in it, in any exception raised "
            "by this module, or in any readiness detail derived from it."),
    }


def configured_variables(
        environ: Optional[Mapping[str, str]] = None) -> Tuple[str, ...]:
    """The declared secrets this environment supplies, by either mechanism."""
    source = dict(os.environ if environ is None else environ)
    return tuple(sorted(
        name for name in SECRET_VARIABLES
        if source.get(name, "").strip()
        or source.get(name + FILE_SUFFIX, "").strip()))
