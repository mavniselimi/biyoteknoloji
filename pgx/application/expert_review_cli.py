# -*- coding: utf-8 -*-
"""``pgx-expert-review`` - the blind expert validation protocol and module.

Five subcommands:

``protocol``
    Print the protocol manifest: which document, which digest, who signed it.
    Nobody has, so this exits blocked.

``workflow``
    Print the state machine, its refusal codes and the ordering guarantee.
    Available now: the workflow is defined before any review exists, which is
    the whole design.

``gate-status``
    Two answers, separately: the review machinery is implemented; no expert
    reviewed anything.

``summary``
    Print the public aggregate. Every field is null, because zero completed
    reviews produce no rate rather than a rate of zero.

``artifacts``
    Regenerate every committed WP-22 document, deterministically.

Exit codes:

``0``  the requested document was produced and its subject is satisfied
``1``  an invariant, schema or calculation failure
``2``  blocked: a precondition outside this command's control is unmet
``3``  invalid usage

``protocol``, ``gate-status`` and ``summary`` exit ``2`` in this repository.
That is the correct outcome and not a defect: ``0`` from ``gate-status`` would
mean an expert had completed a review.

There is deliberately no ``--approve``, ``--signatory`` or
``--use-test-protocol`` flag. The TEST-ONLY approved protocol that lets the
workflow tests exercise the positive path is constructed inside the test suite
and injected; a production switch that substituted it would put the approval
of a clinical protocol one command-line typo away.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from pgx.application.expert_review_schema import (build_schemas,
                                                  validate_protocol_manifest,
                                                  validate_public_summary,
                                                  validate_review_workflow,
                                                  validate_wp22_gate_status)
from pgx.expert_review.artifacts import (GATE_STATUS_PATH,
                                         PROTOCOL_MANIFEST_PATH,
                                         PUBLIC_SUMMARY_PATH, WORKFLOW_PATH,
                                         build_artifacts,
                                         build_protocol_manifest,
                                         build_public_summary,
                                         build_review_workflow,
                                         write_document)
from pgx.expert_review.gate_status import build_wp22_gate_status

__all__ = ["ARTIFACT_PATHS", "EXIT_BLOCKED", "EXIT_FAILED", "EXIT_OK",
           "EXIT_USAGE", "main"]

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_BLOCKED = 2
EXIT_USAGE = 3

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

ARTIFACT_PATHS: Tuple[str, ...] = (
    PROTOCOL_MANIFEST_PATH, WORKFLOW_PATH, PUBLIC_SUMMARY_PATH,
    GATE_STATUS_PATH,
) + tuple(sorted(build_schemas()))


def _out(stream, text: str = "") -> None:
    stream.write(text + "\n")


def _count(value: Optional[int]) -> str:
    """A nullable count, printed so null cannot be read as zero."""
    return ("null (no review store was inspected)" if value is None
            else str(value))


# -- subcommands ---------------------------------------------------------

def _cmd_protocol(args, stream) -> int:
    root = args.root or _REPO_ROOT
    manifest = build_protocol_manifest(root)
    problems = validate_protocol_manifest(manifest)
    if problems:
        for problem in problems:
            _out(stream, "SCHEMA: %s" % problem)
        return EXIT_FAILED
    if args.write:
        write_document(root, PROTOCOL_MANIFEST_PATH, manifest)
    if args.json:
        _out(stream, json.dumps(manifest, indent=2, sort_keys=True,
                                ensure_ascii=True))
    else:
        _out(stream, "protocol version    %s" % manifest["protocol_version"])
        _out(stream, "document            %s" % manifest["document_path"])
        _out(stream, "document digest     %s" % manifest["document_digest"])
        _out(stream, "documented          %s" % manifest["documented"])
        _out(stream, "status              %s" % manifest["status"])
        _out(stream, "approved            %s" % manifest["approved"])
        _out(stream, "signatories         %d of %d required role(s)"
             % (manifest["signatory_count"],
                len(manifest["required_signatory_roles"])))
        _out(stream, "")
        for role in manifest["missing_signatory_roles"]:
            _out(stream, "  MISSING SIGNATORY  %s" % role)
        _out(stream, "")
        _out(stream, manifest["generated_note"])
    return EXIT_OK if manifest["approved"] else EXIT_BLOCKED


def _cmd_workflow(args, stream) -> int:
    root = args.root or _REPO_ROOT
    workflow = build_review_workflow(root)
    problems = validate_review_workflow(workflow)
    if problems:
        for problem in problems:
            _out(stream, "SCHEMA: %s" % problem)
        return EXIT_FAILED
    if args.write:
        write_document(root, WORKFLOW_PATH, workflow)
    if args.json:
        _out(stream, json.dumps(workflow, indent=2, sort_keys=True,
                                ensure_ascii=True))
        return EXIT_OK
    _out(stream, "vocabulary          %s" % workflow["vocabulary_version"])
    _out(stream, "initial state       %s" % workflow["initial_state"])
    _out(stream, "")
    for state in workflow["states"]:
        targets = workflow["transitions"].get(state, [])
        _out(stream, "  %-22s -> %s"
             % (state, ", ".join(targets) if targets else "(terminal)"))
    _out(stream, "")
    _out(stream, "refusal codes       %d" % workflow["error_code_count"])
    _out(stream, "likert dimensions   %s"
         % ", ".join(workflow["likert_dimensions"]))
    _out(stream, "")
    _out(stream, workflow["ordering_note"])
    # The workflow is defined and available; exit 0 says the definition
    # exists, never that a review happened.
    return EXIT_OK


def _cmd_gate_status(args, stream) -> int:
    root = args.root or _REPO_ROOT
    status = build_wp22_gate_status(root)
    problems = validate_wp22_gate_status(status)
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
        _out(stream, "work package        %s" % status["work_package"])
        _out(stream, "implementation      %s"
             % status["implementation_status"])
        _out(stream, "expert review gate  %s"
             % status["expert_review_gate_status"])
        _out(stream, "module implemented  %s"
             % status["expert_review_module_implemented"])
        _out(stream, "protocol documented %s" % status["protocol_documented"])
        _out(stream, "protocol approved   %s" % status["protocol_approved"])
        _out(stream, "protocol status     %s" % status["protocol_status"])
        _out(stream, "named reviewers     %d" % status["named_reviewer_count"])
        # "null" rather than Python's "None", and said out loud: a reader
        # must be able to tell "no store was inspected" from "a store was
        # inspected and held none".
        _out(stream, "assigned reviews    %s" % _count(
            status["assigned_review_count"]))
        _out(stream, "completed reviews   %s" % _count(
            status["completed_review_count"]))
        _out(stream, "expert holdout      %d"
             % status["expert_holdout_case_count"])
        _out(stream, "active release      %s"
             % status["active_release_available"])
        _out(stream, "restricted storage  %s"
             % status["restricted_storage_configured"])
        _out(stream, "production auth     %s"
             % status["production_authentication_available"])
        _out(stream, "expert review done  %s"
             % status["expert_review_performed"])
        _out(stream, "clinical validation %s"
             % status["clinical_validation_performed"])
        _out(stream, "release may proceed %s" % status["release_may_proceed"])
        _out(stream, "")
        for blocker in status["blockers"]:
            _out(stream, "  %-48s %s" % (blocker["code"], blocker["owner"]))
    return (EXIT_OK if status["expert_review_gate_status"] == "PASS"
            else EXIT_BLOCKED)


def _cmd_summary(args, stream) -> int:
    root = args.root or _REPO_ROOT
    summary = build_public_summary(root)
    problems = validate_public_summary(summary)
    if problems:
        for problem in problems:
            _out(stream, "SCHEMA: %s" % problem)
        return EXIT_FAILED
    if args.write:
        write_document(root, PUBLIC_SUMMARY_PATH, summary)
    if args.json:
        _out(stream, json.dumps(summary, indent=2, sort_keys=True,
                                ensure_ascii=True))
    else:
        _out(stream, "completed reviews   %d"
             % summary["completed_review_count"])
        _out(stream, "reviewers           %d" % summary["reviewer_count"])
        _out(stream, "expert holdout      %d"
             % summary["expert_holdout_case_count"])
        _out(stream, "agreement           %s"
             % summary["agreement_distribution"])
        _out(stream, "likert summaries    %s" % summary["likert_summaries"])
        _out(stream, "")
        _out(stream, summary["generated_note"])
    # Zero completed reviews is a blocked outcome, not a successful summary.
    return (EXIT_OK if summary["completed_review_count"] > 0
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
    # The gate status is written by its own subcommand because it reads the
    # environment; regenerating it here would make `artifacts` non-reproducible
    # across machines and break WP-19's byte comparison.
    return EXIT_OK


_COMMANDS = {
    "protocol": _cmd_protocol,
    "workflow": _cmd_workflow,
    "gate-status": _cmd_gate_status,
    "summary": _cmd_summary,
    "artifacts": _cmd_artifacts,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pgx-expert-review",
        description="WP-22 blind expert validation protocol and review "
                    "module. Reports no expert review unless an expert "
                    "actually completed one.")
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
