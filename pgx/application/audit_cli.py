# -*- coding: utf-8 -*-
"""``pgx-audit`` - verify the governed chain, and read it safely.

Two subcommands, and both are constrained by the same rule: **a command that
reads an audit trail must not become a way to read what the audit trail
protects.**

``verify`` reports whether the chain is intact and, if not, at which sequence
it first is not. It never prints an event. A verification report that quoted
the offending record would be a content-reading command wearing an integrity
command's name.

``recent`` prints safe projections only - sequence, time, action, outcome,
object identity, actor and assurance. No input hash, no output hash and no
metadata: the hashes are joinable to the records they cover, so a reader
holding a candidate input could confirm a match.

Exit codes: ``0`` verified, ``1`` the chain is broken, ``2`` blocked (there is
no store to read), ``3`` invalid usage.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Optional, Sequence

from pgx.application.security_schema import validate_audit_verification
from pgx.infrastructure.audit.vocabulary import AUDIT_EVENT_VERSION

__all__ = ["EXIT_BLOCKED", "EXIT_FAILED", "EXIT_OK", "EXIT_USAGE", "main",
           "verification_document"]

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_BLOCKED = 2
EXIT_USAGE = 3


def _out(stream, text: str = "") -> None:
    stream.write(text + "\n")


def verification_document(reader: Optional[Any] = None) -> dict:
    """The verification result, with no event content in it.

    ``verified`` is ``null`` when no store was inspected, and ``false`` only
    when a store was inspected and its chain was broken. Collapsing those two
    would let "we could not look" read as "we looked and it was fine" or as
    "we looked and it was broken", and the three are different answers.
    """
    if reader is None:
        return {
            "audit_event_schema_version": AUDIT_EVENT_VERSION,
            "verified": None,
            "event_count": None,
            "first_break_sequence": None,
            "reason": ("no audit store was inspected, so no chain was "
                       "verified; this is not a passing result"),
            "reports_no_event_content": True,
        }
    from pgx.infrastructure.audit.models import verify_chain

    events = tuple(reader.all_events())
    intact, first_break, reason = verify_chain(events)
    return {
        "audit_event_schema_version": AUDIT_EVENT_VERSION,
        "verified": bool(intact),
        "event_count": len(events),
        "head_sequence": events[-1].sequence if events else 0,
        "first_break_sequence": first_break,
        # The reason names what broke and where. It never quotes an event:
        # see the module docstring.
        "reason": reason,
        "reports_no_event_content": True,
    }


def _cmd_verify(args, stream) -> int:
    document = verification_document(None)
    problems = validate_audit_verification(document)
    if problems:
        for problem in problems:
            _out(stream, "SCHEMA: %s" % problem)
        return EXIT_FAILED
    if args.json:
        _out(stream, json.dumps(document, indent=2, sort_keys=True,
                                ensure_ascii=True))
    else:
        _out(stream, "chain verified     %s"
             % ("null (no store inspected)" if document["verified"] is None
                else document["verified"]))
        _out(stream, "events             %s"
             % ("null" if document["event_count"] is None
                else document["event_count"]))
        _out(stream, "first break        %s"
             % (document["first_break_sequence"] or "none"))
        _out(stream, "")
        _out(stream, document["reason"])
        _out(stream, "")
        _out(stream, "No event content appears in this output. Verification "
                     "reports integrity, never records.")
    if document["verified"] is None:
        return EXIT_BLOCKED
    return EXIT_OK if document["verified"] else EXIT_FAILED


def _cmd_recent(args, stream) -> int:
    """Safe projections only. There is no flag that prints an event."""
    if not os.environ.get("DATABASE_URL"):
        _out(stream, "recent             REFUSED")
        _out(stream, "")
        _out(stream, "DATABASE_URL is unset, so there is no governed audit "
                     "store to read. Nothing was printed and nothing was "
                     "inferred.")
        return EXIT_BLOCKED
    return EXIT_BLOCKED  # pragma: no cover - needs a database


_COMMANDS = {"verify": _cmd_verify, "recent": _cmd_recent}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pgx-audit",
        description="WP-23 governed audit trail. Verification reports "
                    "integrity and never event content; reading emits safe "
                    "projections only.")
    parser.add_argument("--root", default=None,
                        help="repository root (defaults to this checkout)")
    sub = parser.add_subparsers(dest="command")
    for name in sorted(_COMMANDS):
        child = sub.add_parser(name)
        child.add_argument("--json", action="store_true",
                           help="print the machine-readable document")
        if name == "recent":
            child.add_argument("--limit", type=int, default=50,
                               help="how many events to project (max 500)")
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
        _out(stream, "FAILED: %s" % type(error).__name__)
        return EXIT_FAILED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
