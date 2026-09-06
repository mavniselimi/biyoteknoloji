#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The demo environment bootstrap (Wave 4B).

A jury cannot log in to a deployment with no accounts, and this repository
ships none - deliberately. A committed account is a committed credential, and a
credential in version control is a credential forever.

So this command creates the demo accounts at setup time, on the operator's
machine, from passwords the operator supplies or that are generated here and
written once to a file outside the repository. Nothing it produces is
committable and nothing it prints is a secret.

**What it will not do.**

* It creates no hard-coded universal administrator. Every account it creates is
  named on the command line with an explicit governed role, and ``ADMIN`` is
  refused unless ``--allow-admin`` is passed, so the powerful account cannot be
  created by a demonstrator who copied a command from a runbook.
* It bypasses nothing. Accounts are ordinary ``UserRecord`` rows, hashed with
  the deployment's own composed Argon2id hasher under ``ACTIVE_POLICY``, saved
  through the deployment's own store, inside the deployment's own governed
  transaction, and each creation appends a ``USER_CREATED`` audit event that
  rolls the creation back if it cannot be written. There is no flag here that
  disables CSRF, authorisation, rate limiting or audit, and no code path that
  writes a session.
* It never prints a password, a hash, or a database URL. ``check`` prints
  readiness and nothing else; ``setup`` prints usernames, roles, and the path
  it wrote credentials to.

Usage::

    export DATABASE_URL=postgresql+psycopg://.../pgx
    export PGX_RUNTIME_TRACK=CANDIDATE
    python3 scripts/bootstrap_demo_environment.py setup \
        --user jury:DEMO_USER --user reviewer:EXPERT_REVIEWER \
        --credentials-out ~/pgx-demo-credentials.txt
    python3 scripts/bootstrap_demo_environment.py check
"""

from __future__ import annotations

import argparse
import datetime as _dt
import io
import json
import os
import secrets
import stat
import sys
import uuid

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

EXIT_OK = 0
EXIT_BLOCKED = 2

#: Long enough that the generated value is not the weak link, and generated
#: from ``secrets`` rather than ``random``.
_GENERATED_PASSWORD_BYTES = 24


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _composition():
    from pgx.deployment.composition import compose_from_environment

    result = compose_from_environment()
    if result.composition is None:
        return None, [b.code for b in result.blockers]
    return result.composition, []


def _parse_user(value: str):
    if ":" not in value:
        raise argparse.ArgumentTypeError(
            "expected username:ROLE, for example jury:DEMO_USER")
    username, _, role = value.partition(":")
    return username.strip(), role.strip()


def _password_for(username: str, environ) -> tuple:
    """The supplied password, or a generated one. Returns (password, source)."""
    variable = "PGX_DEMO_PASSWORD_" + username.upper().replace("-", "_")
    supplied = environ.get(variable)
    if supplied:
        return supplied, "environment:" + variable
    return secrets.token_urlsafe(_GENERATED_PASSWORD_BYTES), "generated"


def _create(composition, username: str, role: str, password: str) -> str:
    """Create one account inside one governed transaction. Returns its id."""
    from pgx.infrastructure.audit.service import AuditContext
    from pgx.infrastructure.audit.vocabulary import (AuditOutcome,
                                                     GovernedAction)
    from pgx.security.vocabulary import AuthAssurance, AuthMechanism
    from pgx.security.passwords import Password
    from pgx.security.users import UserRecord, canonical_username
    from pgx.security.vocabulary import GOVERNED_ROLES, UserStatus

    if role not in GOVERNED_ROLES:
        raise SystemExit("role %r is not one of %s"
                         % (role, ", ".join(sorted(GOVERNED_ROLES))))
    canonical = canonical_username(username)
    user_id = "USR-" + uuid.uuid4().hex[:20]
    moment = _now()

    with composition.request_scope() as scope:
        with scope.governed_transaction():
            capabilities = composition.capabilities()["user_administration"]()
            users = capabilities["users"]
            hasher = capabilities["hasher"]
            audit = capabilities["audit"]
            if users.by_username(canonical) is not None:
                return ""
            record = UserRecord(
                user_id=user_id,
                username=canonical,
                role=role,
                password_hash=hasher.hash(Password(password)),
                status=UserStatus.ACTIVE,
                auth_generation=1,
                failed_login_count=0,
                locked_until=None,
                created_at=moment,
                updated_at=moment,
                password_changed_at=moment,
                created_by="demo-bootstrap",
                is_bootstrap_admin=False)
            users.save(record)
            # In the same transaction as the creation. An account that exists
            # with no record of who made it is the one account an audit trail
            # most needs.
            audit.record(
                GovernedAction.USER_CREATED,
                outcome=AuditOutcome.SUCCESS,
                result_code="CREATED",
                object_type="USER",
                object_id=user_id,
                # NONE / NONE, deliberately. A shell command is not an
                # authenticated principal, and an audit row that claimed
                # SESSION for it would let a setup script masquerade as a
                # person who logged in.
                context=AuditContext(actor_id="demo-bootstrap",
                                     actor_role="ADMIN",
                                     auth_mechanism=AuthMechanism.NONE,
                                     auth_assurance=AuthAssurance.NONE),
                # The audit metadata vocabulary is closed on purpose - an
                # open bucket eventually receives a request body - so the role
                # goes in the declared ``target_role`` key and the username
                # goes nowhere: the event already names the user by id, and a
                # second spelling of the same subject is a second thing to
                # keep in step.
                metadata={"target_role": role,
                          "target_user_id": user_id})
    return user_id


def _cmd_setup(args, stream) -> int:
    composition, blockers = _composition()
    if composition is None:
        _out(stream, "BLOCKED: no deployment composition. " + ", ".join(blockers))
        _out(stream, "Set DATABASE_URL and install the declared dependencies; "
                     "nothing was created.")
        return EXIT_BLOCKED

    requested = [_parse_user(item) for item in args.user]
    if not requested:
        _out(stream, "BLOCKED: no --user given. This command creates only the "
                     "accounts you name, with the roles you name.")
        return EXIT_BLOCKED
    if any(role == "ADMIN" for _, role in requested) and not args.allow_admin:
        _out(stream, "BLOCKED: creating an ADMIN account requires "
                     "--allow-admin. A demonstration does not need one, and an "
                     "administrator created by copying a runbook line is an "
                     "administrator nobody decided to create.")
        return EXIT_BLOCKED

    created, existing, credentials = [], [], []
    for username, role in requested:
        password, source = _password_for(username, os.environ)
        user_id = _create(composition, username, role, password)
        if not user_id:
            existing.append(username)
            continue
        created.append((username, role, source))
        if source == "generated":
            credentials.append((username, password))

    if credentials:
        path = os.path.expanduser(args.credentials_out)
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write("# PGx demo credentials, generated %s\n"
                         "# Delete this file after the demonstration.\n"
                         % _now().isoformat())
            for username, password in credentials:
                handle.write("%s\t%s\n" % (username, password))
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        _out(stream, "Generated credentials written to %s (mode 0600)." % path)
        _out(stream, "They are not printed here and are not in the repository.")

    for username, role, source in created:
        _out(stream, "created %-16s role=%-15s password=%s"
             % (username, role, source))
    for username in existing:
        _out(stream, "unchanged %-14s (an account with this name already "
                     "exists; nothing was overwritten)" % username)
    return EXIT_OK


def _readiness(composition) -> dict:
    """What a demonstrator needs to know, and no secret."""
    from sqlalchemy import text

    from pgx.application.runtime_track import load_runtime_track

    report = {"runtime_track": load_runtime_track().value}
    with composition.engine.connect() as connection:
        report["database_reachable"] = True
        report["migration_head"] = connection.execute(
            text("SELECT version_num FROM alembic_version")).scalar()
        report["accounts"] = [
            {"username": row[0], "role": row[1], "status": row[2]}
            for row in connection.execute(text(
                "SELECT username, role, status FROM security_users "
                "ORDER BY username"))]
        report["audit_events"] = connection.execute(
            text("SELECT count(*) FROM governed_audit_events")).scalar()
    capabilities = composition.capabilities()
    report["composed_capabilities"] = sorted(
        name for name, value in capabilities.items() if value is not None)

    from apps.api.config import load_settings
    from apps.api.main import build_provider

    provider = build_provider(load_settings())
    report["candidate_release"] = None
    if provider.runtime_track.is_candidate:
        pinned = provider.candidate_release_resolver()
        report["candidate_release"] = (
            None if pinned is None else pinned.release_public_id)
    report["ready"] = bool(
        report["database_reachable"] and report["accounts"]
        and report["migration_head"]
        and (report["candidate_release"] is not None
             or report["runtime_track"] != "CANDIDATE"))
    return report


def _cmd_check(args, stream) -> int:
    composition, blockers = _composition()
    if composition is None:
        _out(stream, json.dumps({"ready": False, "blockers": blockers},
                                indent=2, sort_keys=True))
        return EXIT_BLOCKED
    report = _readiness(composition)
    _out(stream, json.dumps(report, indent=2, sort_keys=True))
    return EXIT_OK if report["ready"] else EXIT_BLOCKED


def _out(stream, line: str) -> None:
    stream.write(line + "\n")


_COMMANDS = {"setup": _cmd_setup, "check": _cmd_check}


def main(argv=None, stream=None) -> int:
    stream = stream or sys.stdout
    parser = argparse.ArgumentParser(
        prog="bootstrap-demo-environment",
        description="Create the demo accounts for a candidate demonstration. "
                    "Creates no account you did not name, prints no secret, "
                    "and disables nothing.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup = subparsers.add_parser("setup")
    setup.add_argument("--user", action="append", default=[],
                       help="username:ROLE, repeatable")
    setup.add_argument("--allow-admin", action="store_true",
                       help="permit creating an account with the ADMIN role")
    setup.add_argument("--credentials-out",
                       default="~/pgx-demo-credentials.txt",
                       help="where generated passwords are written (0600)")

    subparsers.add_parser("check")

    args = parser.parse_args(argv)
    return _COMMANDS[args.command](args, stream)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
