# -*- coding: utf-8 -*-
"""``pgx-auth`` - local account administration. Passwords never touch argv.

Seven subcommands, and three constraints shape all of them.

**A password arrives through ``getpass`` or not at all.** There is no
``--password`` flag, and adding one would be a mistake with a long tail: a
command-line argument appears in shell history, in ``ps`` output visible to
every user on the host, in a CI log and in the audit trail of whatever ran it.
The flag does not exist, so it cannot be used by someone in a hurry.

**There is no ``delete-user``.** Accounts are disabled. A deleted user takes
the subject of their own audit history with them, and a trail whose actors can
vanish cannot answer the question it exists for.

**Every command needs a database and says so when there is none.** These
operations write governed rows and append audit events atomically; a command
that "worked" against no store would have changed nothing while reporting
success.

Exit codes: ``0`` done, ``1`` failed, ``2`` blocked (a precondition outside
this command's control is unmet), ``3`` invalid usage. Every subcommand exits
``2`` in this repository, because there is no database and no Argon2.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from typing import Any, Optional, Sequence

__all__ = ["EXIT_BLOCKED", "EXIT_FAILED", "EXIT_OK", "EXIT_USAGE", "main"]

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_BLOCKED = 2
EXIT_USAGE = 3

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


def _out(stream, text: str = "") -> None:
    stream.write(text + "\n")


def _read_password(prompt: str = "Password: ",
                   reader=None) -> "Any":
    """Read a password twice, without echo, and never return it as a str.

    Reads through ``getpass`` so the value is not echoed and does not reach
    the terminal's scrollback. The confirmation is not politeness: a typo in a
    bootstrap password produces an administrator account nobody can log into,
    on a system with no password-reset flow.
    """
    from pgx.security.errors import PasswordPolicyError
    from pgx.security.passwords import Password

    reader = reader or getpass.getpass
    first = reader(prompt)
    second = reader("Confirm: ")
    if first != second:
        raise PasswordPolicyError("the two entries did not match")
    return Password(first)


def _dependencies(stream) -> Optional[str]:
    """The reason this command cannot run, or ``None``.

    Reported by name. An operator learns whether to install a package or
    configure a database, rather than that "authentication is unavailable".
    """
    from pgx.security.passwords import argon2_available, \
        argon2_unavailable_reason

    if not argon2_available():
        return argon2_unavailable_reason()
    if not os.environ.get("DATABASE_URL"):
        return ("DATABASE_URL is unset, so there is no user store to read or "
                "write; every account operation writes a governed row and "
                "appends an audit event in the same transaction")
    return None


def _blocked(stream, reason: str, *, operation: str) -> int:
    _out(stream, "%-20s REFUSED" % operation)
    _out(stream, "")
    _out(stream, reason)
    _out(stream, "")
    _out(stream, "Nothing was created, changed or written. This command does "
                 "not simulate an account.")
    return EXIT_BLOCKED


def _cmd_bootstrap_admin(args, stream) -> int:
    """Create the first administrator. Distinguishable, and audited as such.

    ``USER_BOOTSTRAPPED`` is a different audit action from ``USER_CREATED``
    on purpose: the first administrator is created with no authenticated
    actor behind it, and an audit trail that recorded it identically to an
    ordinary creation would hide the one account whose provenance most needs
    to be visible.
    """
    reason = _dependencies(stream)
    if reason:
        return _blocked(stream, reason, operation="bootstrap-admin")
    return _blocked(  # pragma: no cover - unreachable without a database
        stream, "no store is composed", operation="bootstrap-admin")


def _cmd_create_user(args, stream) -> int:
    reason = _dependencies(stream)
    if reason:
        return _blocked(stream, reason, operation="create-user")
    return _blocked(stream, "no store is composed",  # pragma: no cover
                    operation="create-user")


def _cmd_disable_user(args, stream) -> int:
    reason = _dependencies(stream)
    if reason:
        return _blocked(stream, reason, operation="disable-user")
    return _blocked(stream, "no store is composed",  # pragma: no cover
                    operation="disable-user")


def _cmd_change_role(args, stream) -> int:
    reason = _dependencies(stream)
    if reason:
        return _blocked(stream, reason, operation="change-role")
    return _blocked(stream, "no store is composed",  # pragma: no cover
                    operation="change-role")


def _cmd_set_password(args, stream) -> int:
    reason = _dependencies(stream)
    if reason:
        return _blocked(stream, reason, operation="set-password")
    return _blocked(stream, "no store is composed",  # pragma: no cover
                    operation="set-password")


def _cmd_revoke_sessions(args, stream) -> int:
    reason = _dependencies(stream)
    if reason:
        return _blocked(stream, reason, operation="revoke-sessions")
    return _blocked(stream, "no store is composed",  # pragma: no cover
                    operation="revoke-sessions")


def _cmd_status(args, stream) -> int:
    """What this deployment has, without touching an account.

    The one subcommand that answers something here, because reporting the
    absence of a store needs no store.
    """
    from pgx.security.passwords import (ACTIVE_POLICY, argon2_available,
                                        argon2_unavailable_reason)
    from pgx.security.rbac import PERMISSION_IDS, RBAC_REGISTRY_VERSION
    from pgx.security.sessions import SessionPolicy

    document = {
        "argon2_dependency_declared": True,
        "argon2_available": argon2_available(),
        "argon2_unavailable_reason": argon2_unavailable_reason(),
        "database_configured": bool(os.environ.get("DATABASE_URL")),
        "password_policy": ACTIVE_POLICY.to_json(),
        "session_policy": SessionPolicy().to_json(),
        "rbac_registry_version": RBAC_REGISTRY_VERSION,
        "permission_count": len(PERMISSION_IDS),
        "user_count": None,
        "user_count_note": (
            "null rather than zero: no store was inspected, so no account "
            "was counted. There is no default user and no fixture account in "
            "any deployment."),
        "no_default_credential": (
            "This system ships no default username and no default password. "
            "The first account is created by bootstrap-admin, interactively, "
            "and is audited as a bootstrap rather than as an ordinary "
            "creation."),
    }
    if args.json:
        _out(stream, json.dumps(document, indent=2, sort_keys=True,
                                ensure_ascii=True))
    else:
        _out(stream, "argon2 declared      %s"
             % document["argon2_dependency_declared"])
        _out(stream, "argon2 available     %s" % document["argon2_available"])
        _out(stream, "database configured  %s"
             % document["database_configured"])
        _out(stream, "password policy      %s"
             % ACTIVE_POLICY.to_json()["password_policy_version"])
        _out(stream, "permissions          %d" % len(PERMISSION_IDS))
        _out(stream, "users                null (no store inspected)")
        _out(stream, "")
        _out(stream, document["no_default_credential"])
    return (EXIT_OK if (document["argon2_available"]
                        and document["database_configured"])
            else EXIT_BLOCKED)


_COMMANDS = {
    "bootstrap-admin": _cmd_bootstrap_admin,
    "create-user": _cmd_create_user,
    "disable-user": _cmd_disable_user,
    "change-role": _cmd_change_role,
    "set-password": _cmd_set_password,
    "revoke-sessions": _cmd_revoke_sessions,
    "status": _cmd_status,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pgx-auth",
        description="WP-23 local account administration. Passwords are read "
                    "interactively and never accepted as arguments. There is "
                    "no delete-user: accounts are disabled, never erased.")
    parser.add_argument("--root", default=None,
                        help="repository root (defaults to this checkout)")
    sub = parser.add_subparsers(dest="command")
    for name in sorted(_COMMANDS):
        child = sub.add_parser(name)
        child.add_argument("--json", action="store_true",
                           help="print the machine-readable document")
        if name in ("create-user", "disable-user", "change-role",
                    "set-password", "revoke-sessions"):
            child.add_argument("--username", required=False,
                               help="the account to act on")
        if name in ("create-user", "change-role"):
            child.add_argument("--role", required=False,
                               choices=["DEMO_USER", "EXPERT_REVIEWER",
                                        "ADMIN"],
                               help="the governed role to assign")
    return parser


def main(argv: Optional[Sequence[str]] = None,
         stream: Optional[Any] = None) -> int:
    stream = stream or sys.stdout
    parser = _parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.command:
        parser.print_help(stream)
        return EXIT_USAGE
    handler = _COMMANDS.get(args.command)
    if handler is None:  # pragma: no cover - argparse rejects first
        return EXIT_USAGE
    try:
        return handler(args, stream)
    except Exception as error:  # noqa: BLE001 - surfaced as exit 1
        # The type and a bounded message. Never the exception's arguments,
        # which for a password error would be the password.
        _out(stream, "FAILED: %s" % type(error).__name__)
        return EXIT_FAILED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
