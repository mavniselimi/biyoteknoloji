# -*- coding: utf-8 -*-
"""``pgx-curation-protocol`` - inspect and validate the curation protocol (WP-09).

Console entry point: ``pgx-curation-protocol``. ``scripts/curation_protocol.py``
is a thin wrapper that delegates here.

Rules this CLI follows, each for a reason:

* **No network, no database.** Everything it reads is a file in this
  repository. Curation is a judgement about evidence already on disk.
* **No ``approve`` command.** There is no flag, subcommand or environment
  variable that approves the protocol, a curation or a legacy hint. Approval
  names a scientist who read something, and a command line cannot supply one.
* **No curation.** Nothing here produces a conclusion, selects evidence on a
  curator's behalf, or fills in a response template.
* **No mutation of evidence.** Every path into ``data/evidence`` is opened
  read-only. An evidence record is what a source stated at a moment that has
  passed.
* **No rules, no risk, no attention.** Those belong to WP-11 and later and
  have their own approval.
* **Deterministic output.** The same repository produces the same JSON, so a
  difference between two runs means something changed.

``approval-status`` reports ``BLOCKED`` while genuine expert metadata is
absent, which is the state this repository is in and is expected to stay in
until a named scientist reviews the protocol.

Exit codes:

===  =========================================================
0    success, and for ``validate`` the protocol is technically
     complete
1    validation failed, or a comparison was refused
2    configuration failure - bad path, unreadable input
3    the named artifact, field or response does not exist
===  =========================================================
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from typing import Any, Dict, List, Mapping, Optional

from pgx.application.curation_schema import (
    validate_curation_field_dictionary, validate_curation_protocol,
    validate_inter_curator_comparison, validate_inter_curator_exercise,
)
from pgx.curation.errors import CurationError
from pgx.curation.exercises import (EXERCISE_STATUS_AWAITING, CuratorResponse,
                                    build_exercise_packet, compare_responses)
from pgx.curation.fields import (FIELD_DICTIONARY, field_definition,
                                 field_dictionary_json)
from pgx.curation.legacy_review import build_review_inventory
from pgx.curation.protocol import build_protocol_document
from pgx.curation.validation import validate_protocol

__all__ = [
    "DEFAULT_EVIDENCE_BUILD",
    "DEFAULT_PROPOSALS",
    "EXIT_CONFIGURATION_FAILURE",
    "EXIT_NOT_FOUND",
    "EXIT_OK",
    "EXIT_REFUSED",
    "build_parser",
    "main",
]

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_CONFIGURATION_FAILURE = 2
EXIT_NOT_FOUND = 3

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

DEFAULT_EVIDENCE_BUILD = os.path.join(_REPO_ROOT, "data", "evidence",
                                      "PGX-DATA-20260830-900")
DEFAULT_PROPOSALS = os.path.join(_REPO_ROOT, "data", "migration", "wp08",
                                 "draft-curation-proposals.ndjson")
DEFAULT_PROTOCOL = os.path.join(_REPO_ROOT, "config", "curation",
                                "protocol-v1.json")
DEFAULT_FIELD_DICTIONARY = os.path.join(_REPO_ROOT, "config", "curation",
                                        "field-dictionary-v1.json")
DEFAULT_EXERCISE_DIR = os.path.join(_REPO_ROOT, "data", "curation",
                                    "protocol-v1", "exercises")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser. Separated so tests can exercise it alone."""
    parser = argparse.ArgumentParser(
        prog="pgx-curation-protocol",
        description=("Inspect and validate the scientific curation protocol. "
                     "This tool approves nothing, curates nothing, and "
                     "produces no rule, risk level or recommendation."))

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--text", action="store_true",
                        help="Human-readable output instead of JSON.")

    validate = _sub(parser, "validate", common,
                    "Check the protocol and its artifacts. Reports technical "
                    "completeness and expert approval separately.")
    validate.add_argument("--evidence-build", default=DEFAULT_EVIDENCE_BUILD,
                          help="Sealed evidence build, read-only, used to "
                               "check that exercise cases cite real records.")
    validate.add_argument("--proposals", default=DEFAULT_PROPOSALS,
                          help="WP-08 draft-curation proposals.")
    validate.add_argument("--expect-proposals", type=int, default=1559,
                          help="How many legacy proposals must be accounted "
                               "for (default 1559).")

    inspect = _sub(parser, "inspect", common,
                   "Print the protocol: version, status, requirements, roles "
                   "and vocabularies.")
    inspect.add_argument("--requirement", default=None,
                         help="Print one requirement by id, e.g. CUR-PROT-009.")

    field = _sub(parser, "field", common,
                 "Print one field's definition: owner, null meaning, "
                 "validation and prohibited interpretations.")
    field.add_argument("name", help="Field name, e.g. conclusion_state.")

    legacy = _sub(parser, "legacy-inventory", common,
                  "Report the legacy manual-hint review queue. Read-only: "
                  "this command reviews nothing.")
    legacy.add_argument("--proposals", default=DEFAULT_PROPOSALS)
    legacy.add_argument("--state", default=None,
                        help="Filter by review state.")
    legacy.add_argument("--limit", type=int, default=20,
                        help="Maximum entries to print (default 20). 0 = all.")

    exercise = _sub(parser, "exercise", common,
                    "Print the inter-curator exercise packet and its status.")
    exercise.add_argument("--evidence-build", default=DEFAULT_EVIDENCE_BUILD)
    exercise.add_argument("--proposals", default=DEFAULT_PROPOSALS)

    compare = _sub(parser, "compare", common,
                   "Compare two completed curator responses field by field. "
                   "Reports differences; decides nothing.")
    compare.add_argument("response_a", help="Completed response A.")
    compare.add_argument("response_b", help="Completed response B.")
    compare.add_argument("--evidence-build", default=DEFAULT_EVIDENCE_BUILD)
    compare.add_argument("--proposals", default=DEFAULT_PROPOSALS)

    approval = _sub(parser, "approval-status", common,
                    "Report whether a named scientific expert has approved "
                    "the protocol, and what is blocking if not.")

    # Deliberately absent, and named here so their absence is visible in this
    # file rather than only in a document: approve, approve-protocol,
    # approve-curation, accept-hint, reject-hint, curate, generate,
    # auto-review, resolve-conflict, publish, and any --force, --reviewer or
    # --as flag.
    return parser


def _sub(parser, name, common, help_text):
    group = getattr(parser, "_pgx_subparsers", None)
    if group is None:
        group = parser.add_subparsers(dest="command", required=True)
        setattr(parser, "_pgx_subparsers", group)
    return group.add_parser(name, parents=[common], help=help_text)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "validate": _cmd_validate,
        "inspect": _cmd_inspect,
        "field": _cmd_field,
        "legacy-inventory": _cmd_legacy_inventory,
        "exercise": _cmd_exercise,
        "compare": _cmd_compare,
        "approval-status": _cmd_approval_status,
    }
    try:
        return handlers[args.command](args)
    except CurationError as exc:
        _emit(args, {"error": str(exc), "code": type(exc).__name__}, str(exc))
        return EXIT_REFUSED
    except (OSError, ValueError) as exc:
        _emit(args, {"error": str(exc), "code": "CONFIGURATION_FAILURE"},
              "CONFIGURATION_FAILURE: %s" % exc)
        return EXIT_CONFIGURATION_FAILURE


# -- commands -----------------------------------------------------------


def _cmd_validate(args) -> int:
    document = build_protocol_document()
    inventory = packet = None
    uuids = None

    if os.path.isfile(args.proposals):
        inventory = build_review_inventory(args.proposals)
    if os.path.isdir(args.evidence_build):
        packet = build_exercise_packet(args.evidence_build, args.proposals)
        uuids = [row["record_uuid"] for row in _read_ndjson(
            os.path.join(args.evidence_build, "evidence-records.ndjson"))]

    report = validate_protocol(
        document, inventory=inventory, packet=packet,
        evidence_record_uuids=uuids,
        expected_proposal_count=args.expect_proposals,
        artifact_paths=(DEFAULT_PROTOCOL, DEFAULT_FIELD_DICTIONARY,
                        os.path.join(DEFAULT_EXERCISE_DIR, "manifest.json"),
                        os.path.join(DEFAULT_EXERCISE_DIR, "cases.ndjson")))

    payload = report.to_json()
    payload["schema_problems"] = _schema_problems()
    if payload["schema_problems"]:
        payload["technical_completeness"] = "FAIL"

    lines = [
        "protocol              %s" % report.protocol_version,
        "content hash          %s" % report.protocol_content_hash,
        "status                %s" % report.protocol_status,
        "technical completeness %s" % payload["technical_completeness"],
        "expert approval       %s" % report.expert_approval,
        "checks run            %d" % len(report.checks_run),
        "issues                %d (%d blocking)"
        % (report.counts["issues"], report.counts["blocking"]),
    ]
    for issue in report.issues:
        lines.append("  %-13s %-38s %s"
                     % (issue.severity, issue.code, issue.subject))
    for problem in payload["schema_problems"]:
        lines.append("  SCHEMA        %s" % problem)
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK if payload["technical_completeness"] == "PASS" \
        else EXIT_REFUSED


def _schema_problems() -> List[str]:
    """Validate the checked-in artifacts against the published schemas."""
    problems: List[str] = []
    if os.path.isfile(DEFAULT_PROTOCOL):
        problems.extend("protocol-v1.json: %s" % item for item
                        in validate_curation_protocol(_read_json(DEFAULT_PROTOCOL)))
    if os.path.isfile(DEFAULT_FIELD_DICTIONARY):
        problems.extend(
            "field-dictionary-v1.json: %s" % item for item
            in validate_curation_field_dictionary(
                _read_json(DEFAULT_FIELD_DICTIONARY)))
    manifest_path = os.path.join(DEFAULT_EXERCISE_DIR, "manifest.json")
    cases_path = os.path.join(DEFAULT_EXERCISE_DIR, "cases.ndjson")
    if os.path.isfile(manifest_path) and os.path.isfile(cases_path):
        manifest = _read_json(manifest_path)
        manifest["cases"] = _read_ndjson(cases_path)
        problems.extend("exercise: %s" % item for item
                        in validate_inter_curator_exercise(manifest))
    pending = os.path.join(DEFAULT_EXERCISE_DIR, "comparison.pending.json")
    if os.path.isfile(pending):
        problems.extend("comparison: %s" % item for item
                        in validate_inter_curator_comparison(
                            _read_json(pending)))
    return problems


def _cmd_inspect(args) -> int:
    document = build_protocol_document()
    payload = document.to_json()
    if args.requirement:
        matches = [item for item in document.requirements
                   if item.requirement_id == args.requirement]
        if not matches:
            _emit(args, {"error": "no requirement %s" % args.requirement,
                         "code": "REQUIREMENT_NOT_FOUND"},
                  "no requirement %s" % args.requirement)
            return EXIT_NOT_FOUND
        payload = matches[0].to_json()
        lines = ["%s  %s" % (payload["requirement_id"], payload["title"]),
                 "",
                 payload["statement"],
                 "",
                 "  implementation   %s" % payload["implementation"],
                 "  schema field     %s" % payload["schema_field"],
                 "  validation code  %s" % payload["validation_code"],
                 "  test             %s" % payload["test_reference"],
                 "  checklist        %s" % payload["checklist_item"]]
        _emit(args, payload, "\n".join(lines))
        return EXIT_OK

    lines = [
        "protocol       %s" % payload["protocol_version"],
        "status         %s" % payload["status"],
        "content hash   %s" % payload["content_hash"],
        "vocabularies   %s" % payload["vocabulary_status"],
        "requirements   %d" % len(payload["requirements"]),
        "roles          %d" % len(payload["roles"]),
        "approved       %s" % payload["expert_approved"],
        "",
        "requirements:",
    ]
    for item in payload["requirements"]:
        lines.append("  %-13s %s" % (item["requirement_id"], item["title"]))
    lines.append("")
    lines.append("roles:")
    for item in payload["roles"]:
        lines.append("  %-33s approves science: %s"
                     % (item["role"], item["may_approve_science"]))
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK


def _cmd_field(args) -> int:
    try:
        definition = field_definition(args.name)
    except Exception:
        available = ", ".join(sorted(item.name for item in FIELD_DICTIONARY))
        _emit(args, {"error": "no field definition for %r" % args.name,
                     "code": "FIELD_NOT_FOUND", "available": available},
              "no field definition for %r\navailable: %s"
              % (args.name, available))
        return EXIT_NOT_FOUND
    payload = definition.to_json()
    lines = [
        "field                %s" % payload["name"],
        "owner                %s" % payload["owner"],
        "type                 %s" % payload["type"],
        "required             %s" % payload["required"],
        "null means           %s" % payload["null_meaning"],
        "validation           %s" % payload["validation"],
        "provenance           %s" % payload["provenance_requirement"],
        "human judgement      %s" % payload["human_judgement_required"],
        "may enter a rule     %s" % payload["may_enter_rule"],
        "must not be read as:",
    ]
    for item in payload["prohibited_interpretations"]:
        lines.append("  - %s" % item)
    if payload["allowed_values"]:
        lines.append("allowed values       %s"
                     % ", ".join(payload["allowed_values"]))
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK


def _cmd_legacy_inventory(args) -> int:
    inventory = build_review_inventory(args.proposals)
    entries = list(inventory.entries)
    if args.state:
        entries = [item for item in entries
                   if item.review_state.value == args.state]
    shown = entries if args.limit <= 0 else entries[:args.limit]
    counts = inventory.counts()
    payload = {
        "inventory_version": inventory.inventory_version,
        "source_path": inventory.source_path,
        "source_sha256": inventory.source_sha256,
        "content_hash": inventory.content_hash(),
        "counts": counts,
        "matched": len(entries),
        "shown": len(shown),
        "truncated": len(shown) < len(entries),
        "entries": [item.to_json() for item in shown],
        "effect": ("None. This command reports the queue and reviews nothing. "
                   "Accepting or rejecting a legacy conclusion is a decision "
                   "by a named scientist, and this tool cannot record one."),
    }
    lines = [
        "legacy manual-hint review queue",
        "  proposals        %d" % counts["proposal_count"],
        "  linked           %d" % counts["linked_count"],
        "  unlinked         %d" % counts["unlinked_count"],
        "  reviewed         %d" % counts["reviewed_count"],
        "  by state         %s" % counts["by_review_state"],
    ]
    for item in shown:
        lines.append("  %-22s %-24s %s"
                     % (item.proposal_id[:22], item.review_state.value,
                        item.subject[:40]))
    if payload["truncated"]:
        lines.append("  ... %d more (--limit 0 for all)"
                     % (len(entries) - len(shown)))
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK


def _cmd_exercise(args) -> int:
    packet = build_exercise_packet(args.evidence_build, args.proposals)
    payload = packet.to_json()
    status_path = os.path.join(DEFAULT_EXERCISE_DIR, "status.json")
    payload["recorded_status"] = (_read_json(status_path)
                                  if os.path.isfile(status_path) else None)
    lines = [
        "exercise       %s" % packet.exercise_id,
        "status         %s" % packet.status,
        "cases          %d" % len(packet.cases),
        "content hash   %s" % packet.content_hash(),
        "evidence build %s" % packet.evidence_build_key,
        "",
    ]
    for case in packet.cases:
        lines.append("  %-42s %-22s blinded=%s legacy=%d"
                     % (case.case_id, case.record_types[0],
                        case.legacy_hint_blinded,
                        len(case.linked_legacy_proposal_ids)))
    for item in packet.unmatched_selectors:
        lines.append("  (not covered) %s: %s" % (item["selector"],
                                                 item["note"]))
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK


def _cmd_compare(args) -> int:
    for path in (args.response_a, args.response_b):
        if not os.path.isfile(path):
            _emit(args, {"error": "no response at %s" % path,
                         "code": "RESPONSE_NOT_FOUND"},
                  "no response at %s" % path)
            return EXIT_NOT_FOUND

    packet = build_exercise_packet(args.evidence_build, args.proposals)
    responses = []
    for label, path in (("A", args.response_a), ("B", args.response_b)):
        raw = _read_json(path)
        responses.append(CuratorResponse(
            exercise_id=str(raw.get("exercise_id")),
            curator_label=str(raw.get("curator_label") or label),
            curator_name=raw.get("curator_name"),
            answers=raw.get("answers") or {},
            completed=bool(raw.get("completed"))))

    report = compare_responses(packet, responses[0], responses[1])
    payload = report.to_json()
    payload["status"] = "COMPLETED"
    summary = payload["summary"]
    lines = [
        "comparison     %s" % report.exercise_id,
        "curators       %s / %s" % (report.curator_a_name,
                                    report.curator_b_name),
        "cases          %d" % summary["case_count"],
        "fields agreed  %d of %d" % (summary["fields_in_agreement"],
                                     summary["fields_compared"]),
        "",
    ]
    for case in payload["cases"]:
        differing = case["fields_differing"]
        lines.append("  %-42s %s" % (case["case_id"],
                                     ", ".join(differing) or "no differences"))
    lines.append("")
    lines.append("This report names differences. It does not say who is "
                 "correct, and agreement is not evidence of correctness.")
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK


def _cmd_approval_status(args) -> int:
    document = build_protocol_document()
    status_path = os.path.join(DEFAULT_EXERCISE_DIR, "status.json")
    exercise_status = (_read_json(status_path)
                       if os.path.isfile(status_path) else {})

    blockers = []
    if document.approval is None:
        blockers.append(
            "No named scientific expert has approved %s. Its status is %s."
            % (document.protocol_version, document.status.value))
    if exercise_status.get("status", EXERCISE_STATUS_AWAITING) == \
            EXERCISE_STATUS_AWAITING:
        blockers.append(
            "The inter-curator exercise has not been run: two named curators "
            "have not been assigned and neither response is complete.")
    comparison = os.path.join(DEFAULT_EXERCISE_DIR, "comparison.pending.json")
    if os.path.isfile(comparison):
        blockers.append(
            "No inter-curator comparison or adjudication record exists; the "
            "comparison is still PENDING_TWO_COMPLETED_RESPONSES.")

    payload = {
        "protocol_version": document.protocol_version,
        "protocol_content_hash": document.content_hash(),
        "protocol_status": document.status.value,
        "expert_approval": "APPROVED" if document.is_expert_approved
                           else "BLOCKED",
        "exercise_status": exercise_status.get("status",
                                               EXERCISE_STATUS_AWAITING),
        "blocked_by": blockers,
        "human_actions_required": [
            "A named scientist reviews the protocol and records an approval "
            "against content hash %s." % document.content_hash(),
            "Two named scientific curators independently complete the "
            "exercise response templates.",
            "A named adjudicator resolves any disagreement, preserving both "
            "responses.",
        ],
        "effect": ("None. This command reports a state and cannot change it. "
                   "There is no approve command in this tool."),
    }
    lines = [
        "protocol       %s" % payload["protocol_version"],
        "content hash   %s" % payload["protocol_content_hash"],
        "status         %s" % payload["protocol_status"],
        "expert approval %s" % payload["expert_approval"],
        "exercise       %s" % payload["exercise_status"],
        "",
        "blocked by:",
    ]
    for item in blockers:
        lines.append("  - %s" % item)
    lines.append("")
    lines.append("to unblock, a human must:")
    for item in payload["human_actions_required"]:
        lines.append("  - %s" % item)
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK if payload["expert_approval"] == "APPROVED" \
        else EXIT_REFUSED


# -- helpers ------------------------------------------------------------


def _emit(args, payload: Mapping[str, Any], text: str) -> None:
    if getattr(args, "text", False):
        sys.stdout.write(text.rstrip("\n") + "\n")
    else:
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True,
                                    ensure_ascii=False) + "\n")


def _read_json(path: str) -> Dict[str, Any]:
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _read_ndjson(path: str) -> List[Dict[str, Any]]:
    if not os.path.isfile(path):
        return []
    with io.open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
