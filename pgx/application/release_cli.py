# -*- coding: utf-8 -*-
"""``pgx-release`` - inspect, activate and roll back releases (WP-03).

Console entry point: ``pgx-release``. ``scripts/release.py`` is a thin wrapper
that delegates here, so the logic exists once and the installed package owns it.

Design rules this CLI follows, each for a concrete reason:

* **No business logic.** Every subcommand parses arguments, calls
  :class:`~pgx.application.release_service.ReleaseService`, and prints the
  result. A CLI that re-implemented a compatibility check would eventually
  disagree with the service, and the disagreement would surface as a release
  that validated on the command line and failed in production.
* **The database URL comes from the environment, never the command line.** A
  URL in ``argv`` lands in the shell history and the process list.
* **No credential in any output.** Failure text goes through
  ``config.sanitize_message`` first; driver errors quote the connection string
  back, and an unsanitised message would put a password in a CI transcript.
* **Machine-readable output and explicit exit codes.** Every subcommand prints
  one JSON document to stdout. Exit codes are stable and distinct, so a deploy
  script can branch on *why* something failed rather than on stderr text.
* **Actor and reason are mandatory on anything that mutates.** An audit trail
  that records what changed but not who or why answers half the question.

Exit codes:

===  =========================================================
0    success
1    the release is not activatable, or a rollback is refused
2    configuration failure (missing URL, driver, database)
3    the named release does not exist
4    the active pointer moved during the operation
===  =========================================================
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, List, Mapping, Optional

from pgx.domain.errors import DomainError
from pgx.domain.identifiers import ReleaseBundleId, ReleasePublicId

__all__ = [
    "EXIT_CONFIGURATION_FAILURE",
    "EXIT_NOT_ACTIVATABLE",
    "EXIT_OK",
    "EXIT_RELEASE_NOT_FOUND",
    "EXIT_STALE_POINTER",
    "build_parser",
    "main",
]

EXIT_OK = 0
EXIT_NOT_ACTIVATABLE = 1
EXIT_CONFIGURATION_FAILURE = 2
EXIT_RELEASE_NOT_FOUND = 3
EXIT_STALE_POINTER = 4

#: Environment variables the CLI reads. The URL is never an argument.
DATABASE_URL_ENVS = ("DATABASE_URL", "TEST_DATABASE_URL")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser. Separated so tests can exercise it alone."""
    parser = argparse.ArgumentParser(
        prog="pgx-release",
        description="Inspect, validate, activate and roll back PGx releases.")
    parser.add_argument(
        "--database-url-env", default="DATABASE_URL", choices=list(DATABASE_URL_ENVS),
        help="Environment variable holding the PostgreSQL URL. The URL itself is "
             "never accepted on the command line, so it cannot reach the process "
             "list or the shell history.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "show-active", help="Print the release currently in force.")

    inspect = subparsers.add_parser(
        "inspect", help="Print one release bundle and its pinned manifest.")
    _add_release_selector(inspect)

    validate = subparsers.add_parser(
        "validate", help="Run every compatibility rule without changing anything.")
    _add_release_selector(validate)

    activate = subparsers.add_parser(
        "activate", help="Make a release the active release.")
    _add_release_selector(activate)
    _add_actor_and_reason(activate)

    rollback = subparsers.add_parser(
        "rollback", help="Return to a release that was previously in force.")
    _add_release_selector(rollback)
    _add_actor_and_reason(rollback)

    history = subparsers.add_parser("history", help="Print recent release events.")
    history.add_argument("--limit", type=int, default=20,
                         help="How many events to print (default 20).")

    legacy = subparsers.add_parser(
        "register-legacy-baseline",
        help="Record the WP-01 legacy seed as a RETIRED, comparison-only "
             "baseline. It imports no legacy rows and can never be activated.")
    legacy.add_argument("--software-version-id", required=True,
                        help="Identity of the registered build performing this.")
    _add_actor_and_reason(legacy)
    return parser


def _add_release_selector(parser: argparse.ArgumentParser) -> None:
    """A release is named by internal identity or by public identifier."""
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--release-id", help="Internal UUID of the release.")
    group.add_argument("--public-id", help="Public identifier, PGX-REL-YYYYMMDD-NNN.")


def _add_actor_and_reason(parser: argparse.ArgumentParser) -> None:
    """Mutating commands must say who and why."""
    parser.add_argument("--actor", required=True,
                        help="Who is performing this. Recorded in the audit trail.")
    parser.add_argument("--reason", required=True,
                        help="Why. Recorded in the audit trail.")


def _emit(document: Mapping[str, Any]) -> None:
    """Print one JSON document to stdout."""
    sys.stdout.write(json.dumps(document, indent=2, sort_keys=True, default=str) + "\n")


def _fail(code: str, message: str) -> None:
    """Print a machine-readable failure to stderr.

    ``message`` has already been sanitized by the caller.
    """
    sys.stderr.write(json.dumps({"error": code, "detail": message},
                                sort_keys=True) + "\n")


def _resolve_release(uow, args):
    """Return the release named by ``--release-id`` or ``--public-id``."""
    if args.release_id:
        return uow.releases.get(ReleaseBundleId.parse(args.release_id))
    return uow.releases.get_by_public_id(ReleasePublicId(args.public_id))


def _make_service(database_url_env: str):
    """Build the service over a real database. Imported late, on purpose.

    The infrastructure imports live inside this function so that ``--help``,
    argument parsing and the exit-code contract can all be exercised without
    SQLAlchemy installed. A module-level import would make the whole CLI
    untestable in exactly the environment where it most needs testing.
    """
    from pgx.application.release_service import ReleaseService
    from pgx.infrastructure.db.config import load_database_config
    from pgx.infrastructure.db.session import (
        create_database_engine, create_session_factory,
    )
    from pgx.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

    config = load_database_config(
        use_test_database=(database_url_env == "TEST_DATABASE_URL"))
    engine = create_database_engine(config)
    factory = create_session_factory(engine)
    return ReleaseService(lambda: SqlAlchemyUnitOfWork(factory)), engine, factory


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for ``pgx-release``."""
    from pgx.infrastructure.db.config import sanitize_message

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        service, engine, factory = _make_service(args.database_url_env)
    except Exception as exc:  # noqa: BLE001 - surfaced as a precise CLI failure
        _fail("CONFIGURATION_FAILURE",
              "%s: %s" % (type(exc).__name__, sanitize_message(str(exc))))
        return EXIT_CONFIGURATION_FAILURE

    try:
        return _dispatch(args, service, factory, sanitize_message)
    finally:
        engine.dispose()


def _dispatch(args, service, factory, sanitize_message) -> int:
    """Run one subcommand. Split out so the failure mapping is readable."""
    from pgx.application.release_service import (
        ReleaseNotActivatableError, ReleaseNotFoundError, RollbackNotPermittedError,
        StaleActivationError,
    )
    from pgx.infrastructure.db.repositories import StaleActiveReleaseError
    from pgx.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

    def uow():
        return SqlAlchemyUnitOfWork(factory)

    try:
        if args.command == "show-active":
            release = service.get_active_release()
            pointer = service.get_active_pointer()
            _emit({
                "command": "show-active",
                "has_active_release": release is not None,
                "release": None if release is None else _release_json(release),
                "generation": pointer.generation,
                "updated_at": pointer.updated_at,
                "updated_by": pointer.updated_by,
            })
            return EXIT_OK

        if args.command == "history":
            events = service.release_history(limit=args.limit)
            _emit({"command": "history", "count": len(events),
                   "events": [_event_json(event) for event in events]})
            return EXIT_OK

        if args.command == "register-legacy-baseline":
            from pgx.application.legacy_baseline import register_legacy_baseline
            from pgx.domain.identifiers import SoftwareVersionId

            result = register_legacy_baseline(
                uow_factory=uow,
                software_version_id=SoftwareVersionId.parse(args.software_version_id),
                actor=args.actor,
            )
            _emit(dict(result.to_json(), command="register-legacy-baseline"))
            return EXIT_OK

        # The remaining commands all name one release.
        with uow() as unit:
            release = _resolve_release(unit, args)
            if release is None:
                _fail("RELEASE_NOT_FOUND",
                      "no release matching %s"
                      % (args.release_id or args.public_id))
                return EXIT_RELEASE_NOT_FOUND
            release_id = release.id
            snapshot = _release_json(release)

        if args.command == "inspect":
            _emit({"command": "inspect", "release": snapshot})
            return EXIT_OK

        if args.command == "validate":
            report = service.validate_release(release_id)
            _emit(dict(report.to_json(), command="validate"))
            return EXIT_OK if report.is_compatible else EXIT_NOT_ACTIVATABLE

        if args.command == "activate":
            result = service.activate_release(release_id, args.actor, args.reason)
            _emit(dict(result.to_json(), command="activate"))
            return EXIT_OK

        if args.command == "rollback":
            result = service.rollback_release(release_id, args.actor, args.reason)
            _emit(dict(result.to_json(), command="rollback"))
            return EXIT_OK

        _fail("UNKNOWN_COMMAND", "no handler for %r" % args.command)
        return EXIT_CONFIGURATION_FAILURE

    except ReleaseNotFoundError as exc:
        _fail("RELEASE_NOT_FOUND", sanitize_message(str(exc)))
        return EXIT_RELEASE_NOT_FOUND
    except ReleaseNotActivatableError as exc:
        _emit(dict(exc.report.to_json(), command=args.command,
                   error="RELEASE_NOT_ACTIVATABLE"))
        return EXIT_NOT_ACTIVATABLE
    except RollbackNotPermittedError as exc:
        _fail("ROLLBACK_NOT_PERMITTED", sanitize_message(str(exc)))
        return EXIT_NOT_ACTIVATABLE
    except (StaleActivationError, StaleActiveReleaseError) as exc:
        _fail("STALE_POINTER", sanitize_message(str(exc)))
        return EXIT_STALE_POINTER
    except DomainError as exc:
        _fail("DOMAIN_ERROR",
              "%s: %s" % (type(exc).__name__, sanitize_message(str(exc))))
        return EXIT_NOT_ACTIVATABLE
    except Exception as exc:  # noqa: BLE001 - surfaced as a precise CLI failure
        _fail("OPERATION_FAILURE",
              "%s: %s" % (type(exc).__name__, sanitize_message(str(exc))))
        return EXIT_CONFIGURATION_FAILURE


def _release_json(release) -> Mapping[str, Any]:
    """Machine-readable view of one release bundle."""
    from pgx.domain.release_manifest import as_plain_json

    return {
        "id": release.id.to_json(),
        "public_id": release.public_id.to_json(),
        "status": release.status.value,
        "software_version_id": release.software_version_id.to_json(),
        "dataset_version_id": release.dataset_version_id.to_json(),
        "ruleset_version_id": release.ruleset_version_id.to_json(),
        "manifest_hash": release.manifest_hash,
        "manifest": as_plain_json(release.manifest),
        "created_at": release.created_at,
        "activated_at": release.activated_at,
        "activated_by": release.activated_by,
        "notes": release.notes,
    }


def _event_json(event) -> Mapping[str, Any]:
    """Machine-readable view of one audit event."""
    from pgx.domain.release_manifest import as_plain_json

    return {
        "id": event.id.to_json(),
        "action": event.action.value,
        "actor": event.actor,
        "object_type": event.object_type,
        "object_id": event.object_id,
        "previous_release_id": (None if event.previous_release_id is None
                                else event.previous_release_id.to_json()),
        "new_release_id": (None if event.new_release_id is None
                           else event.new_release_id.to_json()),
        "reason": event.reason,
        "metadata": as_plain_json(event.metadata),
        "occurred_at": event.occurred_at,
    }


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
