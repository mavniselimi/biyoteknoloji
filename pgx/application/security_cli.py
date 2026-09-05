# -*- coding: utf-8 -*-
"""``pgx-security`` - secret scan, backup preflight, gate status, artifacts.

Four subcommands, and none of them can report operational success from a
configuration file. That is the constraint the whole module is arranged
around: ``backup-preflight`` reads configuration and reports what is
*missing*; it never runs a dump, and its best outcome is ``NOT_EXECUTED``.

Exit codes:

``0``  the requested document was produced and its subject is satisfied
``1``  an invariant, schema or calculation failure
``2``  blocked: a precondition outside this command's control is unmet
``3``  invalid usage

``gate-status`` and ``backup-preflight`` exit ``2`` in this repository. That
is the correct outcome and not a defect: ``0`` from ``gate-status`` would mean
the security layer was configured, running, and had verified its own audit
chain against a real store.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from typing import Any, Mapping, Optional, Sequence, Tuple

from pgx.application.security_schema import (build_schemas,
                                             validate_backup_status,
                                             validate_secret_scan_report,
                                             validate_wp23_gate_status)
from pgx.security.artifacts import (AUDIT_ACTIONS_PATH, BACKUP_STATUS_PATH,
                                    GATE_STATUS_PATH, RATE_LIMIT_PATH,
                                    RBAC_REGISTRY_PATH, SECRET_SCAN_PATH,
                                    build_artifacts, write_document)
from pgx.security.backup import backup_status, preflight
from pgx.security.gate_status import build_wp23_gate_status
from pgx.security.secret_scan import scan_repository

__all__ = ["ARTIFACT_PATHS", "EXIT_BLOCKED", "EXIT_FAILED", "EXIT_OK",
           "EXIT_USAGE", "main"]

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_BLOCKED = 2
EXIT_USAGE = 3

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

ARTIFACT_PATHS: Tuple[str, ...] = (
    RBAC_REGISTRY_PATH, AUDIT_ACTIONS_PATH, RATE_LIMIT_PATH,
    SECRET_SCAN_PATH, BACKUP_STATUS_PATH, GATE_STATUS_PATH,
) + tuple(sorted(build_schemas()))


def _out(stream, text: str = "") -> None:
    stream.write(text + "\n")


def _count(value: Optional[int]) -> str:
    """A nullable count, printed so null cannot be read as zero."""
    return "null (nothing was inspected)" if value is None else str(value)


def _cmd_secret_scan(args, stream) -> int:
    """Report locations. Never a value.

    The output is the same shape as the committed artifact, because the
    thing a reader checks in CI and the thing committed to the repository
    should be one document rather than two that agree today.
    """
    root = args.root or _REPO_ROOT
    report = scan_repository(root)
    problems = validate_secret_scan_report(report)
    if problems:
        for problem in problems:
            _out(stream, "SCHEMA: %s" % problem)
        return EXIT_FAILED
    if args.write:
        write_document(root, SECRET_SCAN_PATH, report)
    if args.json:
        _out(stream, json.dumps(report, indent=2, sort_keys=True,
                                ensure_ascii=True))
    else:
        _out(stream, "scanned            %d file(s)"
             % report["scanned_file_count"])
        _out(stream, "rules              %d" % report["rule_count"])
        _out(stream, "allowlist          %d exact entr(ies)"
             % report["allowlist_count"])
        _out(stream, "negative fixtures  %d classified file(s)"
             % report["negative_fixture_count"])
        _out(stream, "status             %s" % report["status"])
        _out(stream, "findings           %d" % report["finding_count"])
        _out(stream, "classified         %d"
             % report["classified_finding_count"])
        _out(stream, "")
        for finding in report["findings"]:
            # Path, line, rule. Never the value: printing it here would put
            # the secret into CI logs and terminal scrollback, which is the
            # disclosure this command exists to prevent.
            _out(stream, "  %s:%d  %s  [%s]"
                 % (finding["path"], finding["line"], finding["rule_id"],
                    finding["severity"]))
        _out(stream, "")
        _out(stream, report["no_value_is_reported"])
    return EXIT_OK if report["status"] == "CLEAN" else EXIT_FAILED


def _cmd_backup_preflight(args, stream) -> int:
    """What is configured. Runs no dump and restores nothing."""
    root = args.root or _REPO_ROOT
    checks = preflight(root)
    status = backup_status(root)
    problems = validate_backup_status(status)
    if problems:
        for problem in problems:
            _out(stream, "SCHEMA: %s" % problem)
        return EXIT_FAILED
    if args.write:
        write_document(root, BACKUP_STATUS_PATH, status)
    if args.json:
        _out(stream, json.dumps(status, indent=2, sort_keys=True,
                                ensure_ascii=True))
    else:
        _out(stream, "procedure documented %s"
             % status["backup_procedure_documented"])
        _out(stream, "scope items          %d" % status["scope_item_count"])
        _out(stream, "backup executed      %s" % status["backup_executed"])
        _out(stream, "restore executed     %s" % status["restore_executed"])
        _out(stream, "restore verified     %s" % status["restore_verified"])
        _out(stream, "operational status   %s"
             % status["operational_status"])
        _out(stream, "")
        for check in checks["checks"]:
            _out(stream, "  %-32s %-5s %s"
                 % (check["check_id"], check["satisfied"], check["detail"]))
        _out(stream, "")
        _out(stream, checks["preflight_is_not_a_backup"])
    # Never 0 while nothing has run. A preflight that exited 0 would be read
    # in CI as "the backup is fine".
    return EXIT_OK if status["restore_verified"] else EXIT_BLOCKED


def _cmd_gate_status(args, stream) -> int:
    root = args.root or _REPO_ROOT
    status = build_wp23_gate_status(root)
    problems = validate_wp23_gate_status(status)
    if problems:
        for problem in problems:
            _out(stream, "SCHEMA: %s" % problem)
        return EXIT_FAILED
    if args.write:
        write_document(root, GATE_STATUS_PATH, status)
    if args.json:
        _out(stream, json.dumps(status, indent=2, sort_keys=True,
                                ensure_ascii=True))
    else:
        _out(stream, "work package         %s" % status["work_package"])
        _out(stream, "implementation       %s"
             % status["implementation_status"])
        _out(stream, "security gate        %s"
             % status["security_gate_status"])
        _out(stream, "")
        _out(stream, "-- implemented ------------------------------------")
        for field in ("authentication_software_implemented",
                      "session_management_implemented", "csrf_implemented",
                      "rate_limiting_implemented",
                      "canonical_audit_implemented",
                      "argon2_dependency_declared"):
            _out(stream, "  %-42s %s" % (field, status[field]))
        _out(stream, "")
        _out(stream, "-- configured -------------------------------------")
        for field in ("argon2_available", "database_available",
                      "migration_0011_executed", "authentication_configured",
                      "csrf_operational", "rate_limiting_operational",
                      "https_termination_observed"):
            _out(stream, "  %-42s %s" % (field, status[field]))
        _out(stream, "")
        _out(stream, "-- operating --------------------------------------")
        _out(stream, "  %-42s %s" % ("real_users_configured",
                                     _count(status["real_users_configured"])))
        _out(stream, "  %-42s %s" % ("audit_chain_verified",
                                     status["audit_chain_verified"]))
        _out(stream, "  %-42s %s" % ("secret_scan_status",
                                     status["secret_scan_status"]))
        for field in ("backup_executed", "restore_verified",
                      "expert_review_performed",
                      "clinical_validation_performed",
                      "release_may_proceed"):
            _out(stream, "  %-42s %s" % (field, status[field]))
        _out(stream, "")
        for blocker in status["blockers"]:
            _out(stream, "  %-46s %s" % (blocker["code"], blocker["owner"]))
    return (EXIT_OK if status["security_gate_status"] == "PASS"
            else EXIT_BLOCKED)


def _cmd_artifacts(args, stream) -> int:
    root = args.root or _REPO_ROOT
    documents = build_artifacts(root)
    for relative in sorted(documents):
        path = os.path.join(root, *relative.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(documents[relative])
        _out(stream, "wrote %s" % relative)
    # The secret-scan report and the gate status are written by their own
    # subcommands: one walks the filesystem and the other reads the
    # environment, so regenerating them here would make `artifacts`
    # non-reproducible across machines and break WP-19's byte comparison.
    return EXIT_OK


_COMMANDS = {
    "secret-scan": _cmd_secret_scan,
    "backup-preflight": _cmd_backup_preflight,
    "gate-status": _cmd_gate_status,
    "artifacts": _cmd_artifacts,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pgx-security",
        description="WP-23 security baseline: secret scanning, backup "
                    "preflight and gate status. Reports no operational "
                    "success from configuration alone.")
    parser.add_argument("--root", default=None,
                        help="repository root (defaults to this checkout)")
    sub = parser.add_subparsers(dest="command")
    for name in sorted(_COMMANDS):
        child = sub.add_parser(name)
        child.add_argument("--json", action="store_true",
                           help="print the machine-readable document")
        if name != "artifacts":
            child.add_argument("--write", action="store_true",
                               help="also write the committed document")
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
    if not hasattr(args, "write"):
        args.write = False
    try:
        return handler(args, stream)
    except Exception as error:  # noqa: BLE001 - surfaced as exit 1
        _out(stream, "FAILED: %s: %s" % (type(error).__name__, error))
        return EXIT_FAILED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
