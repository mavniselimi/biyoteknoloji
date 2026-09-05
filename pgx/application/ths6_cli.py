# -*- coding: utf-8 -*-
"""``pgx-ths6`` - reading the evidence, never improving it (WP-25).

Nine subcommands, and every one returns a process exit code a pipeline can
branch on:

    0  the thing asked about is genuinely so
    1  something is invalid, corrupt or failing - an engineering defect
    2  blocked, not executed, or stale - not a software failure, a statement
       that the thing being asked about did not happen
    3  the request was malformed

Two of the nine may exit 0 today, and it is worth being precise about why.
``verify-pack`` and ``build-pack`` ask "is this pack internally sound", and a
sound pack that honestly records six blocked gates is a success for those
commands - refusing to build one would leave the project with no document at
all. Every other command asks about the programme, and while the programme is
blocked they exit 2.

Nothing here can improve a result. There is no ``--force``, no ``--assume``,
no ``--fixture`` and no ``--ignore-blocker``; ``argparse`` would reject them
as unknown arguments, and no code path accepts an override under any other
spelling. The banner every command prints says so, because the most likely
misreading of this tool's output is that producing a pack is an achievement.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Mapping, Optional, Sequence

from pgx.ths6.vocabulary import (EXIT_BLOCKED, EXIT_FAILURE, EXIT_SUCCESS,
                                 EXIT_USAGE, PACK_INTEGRITY_IS_NOT_ACHIEVEMENT)

__all__ = ["main"]

_BANNER = ("pgx-ths6 reads committed evidence. It cannot approve, sign, "
           "execute or improve anything.")


def _emit(document: Mapping[str, Any], *, as_json: bool,
          lines: Sequence[str] = ()) -> None:
    if as_json:
        print(json.dumps(document, indent=2, sort_keys=True,
                         ensure_ascii=True))
        return
    print(_BANNER)
    for line in lines:
        print(line)


def _blocker_lines(blockers: Sequence[Mapping[str, Any]]) -> Sequence[str]:
    lines = []
    for entry in blockers:
        lines.append("  %-40s %s" % (entry.get("code"), entry.get("owner")))
        lines.append("    %s" % entry.get("detail"))
    return lines


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def _cmd_inventory(args) -> int:
    from pgx.ths6.evidence_registry import build_evidence_registry

    document = build_evidence_registry(args.root)
    lines = [
        "evidence items declared   %d" % document["declared_count"],
        "present                   %d" % document["present_count"],
        "absent                    %d" % document["absent_count"],
        "invalid                   %d" % document["invalid_count"],
        "may support a THS 6 claim %d" % document["admissible_count"],
        "",
        "by type:",
    ]
    for name, count in document["counts_by_type"].items():  # type: ignore
        lines.append("  %-26s %d" % (name, count))
    lines.append("")
    lines.append("preliminary WP-local THS documents (preserved, not part "
                 "of the final pack):")
    for path in document["preliminary_ths6_documents"]:  # type: ignore
        lines.append("  %s" % path)
    lines.append("")
    for finding in document["findings"]:  # type: ignore
        lines.append("finding %s (%s)" % (finding["code"], finding["owner"]))
        lines.append("  %s" % finding["detail"])
    _emit(document, as_json=args.json, lines=lines)
    return EXIT_FAILURE if document["invalid_count"] else EXIT_SUCCESS


def _cmd_claims(args) -> int:
    from pgx.ths6.claim_registry import build_claim_registry

    document = build_claim_registry(args.root)
    lines = ["claims %d" % document["claim_count"], ""]
    for name, count in document["counts_by_support"].items():  # type: ignore
        lines.append("  %-22s %d" % (name, count))
    lines.append("")
    for claim in document["claims"]:  # type: ignore
        lines.append("%s  %-22s %s" % (claim["claim_id"], claim["support"],
                                       claim["statement"]))
    _emit(document, as_json=args.json, lines=lines)
    if document["unresolvable_probes"]:
        return EXIT_FAILURE
    if len(document["supported_claim_ids"]) == document["claim_count"]:
        return EXIT_SUCCESS
    return EXIT_BLOCKED


def _cmd_traceability(args) -> int:
    from pgx.ths6.traceability import build_traceability

    document = build_traceability(args.root)
    lines = ["traceability rows %d" % document["row_count"], ""]
    for row in document["rows"]:  # type: ignore
        lines.append("%-24s %-20s %s" % (row["row_id"], row["result"],
                                         row["requirement"][:60]))
    lines.append("")
    lines.append("dangling references: %s"
                 % ("none" if not document["has_dangling_reference"]
                    else json.dumps(document["dangling"], sort_keys=True)))
    _emit(document, as_json=args.json, lines=lines)
    if document["has_dangling_reference"]:
        return EXIT_FAILURE
    supported = document["counts_by_result"].get(  # type: ignore
        "SUPPORTED", 0)
    return (EXIT_SUCCESS if supported == document["row_count"]
            else EXIT_BLOCKED)


def _cmd_gates(args) -> int:
    from pgx.ths6.gate_matrix import build_gate_matrix

    document = build_gate_matrix(args.root)
    lines = []
    for gate in document["gates"]:  # type: ignore
        lines.append("%-8s %-14s %-24s %d/%d conditions met"
                     % (gate["gate_id"], gate["result"], gate["title"],
                        gate["met_condition_count"], gate["condition_count"]))
    lines.append("")
    lines.append("blockers %d, owned by %d role(s)"
                 % (document["total_blocker_count"],
                    len(document["blocker_owners"])))  # type: ignore
    if args.verbose:
        for gate in document["gates"]:  # type: ignore
            if gate["blockers"]:
                lines.append("")
                lines.append("%s blockers:" % gate["gate_id"])
                lines.extend(_blocker_lines(gate["blockers"]))
    if document["source_artifact_disagreements"]:
        lines.append("")
        lines.append("source artifact disagreements (%d), recorded and not "
                     "resolved:" % document["disagreement_count"])
        for entry in document["source_artifact_disagreements"]:  # type: ignore
            lines.append("  %s" % entry["fact"])
            lines.append("    %s = %r" % (entry["left_path"],
                                          entry["left_value"]))
            lines.append("    %s = %r" % (entry["right_path"],
                                          entry["right_value"]))
            lines.append("    owner: %s" % entry["owner"])
    _emit(document, as_json=args.json, lines=lines)
    if document["failing_gate_ids"]:
        return EXIT_FAILURE
    return EXIT_SUCCESS if document["all_gates_pass"] else EXIT_BLOCKED


def _cmd_dod(args) -> int:
    from pgx.ths6.definition_of_done import build_definition_of_done

    document = build_definition_of_done(args.root)
    lines = [
        "enumerated in %s: %d" % (document["architecture_section"],
                                  document["enumerated_count"]),
        "declared in the WP-25 prose: %d"
        % document["declared_count_in_wp25_prose"],
        "counts agree: %s" % document["count_matches_declaration"],
        "",
    ]
    for item in document["items"]:  # type: ignore
        state = {True: "SATISFIED", False: "NOT SATISFIED",
                 None: "NOT EVALUATED"}[item["satisfied"]]
        lines.append("%-12s %-14s %s" % (item["dod_id"], state,
                                         item["architecture_text"]))
    lines.append("")
    for finding in document["findings"]:  # type: ignore
        lines.append("finding %s (%s)" % (finding["code"], finding["owner"]))
        lines.append("  %s" % finding["detail"])
        lines.append("  resolution: %s" % finding["resolution"])
    _emit(document, as_json=args.json, lines=lines)
    return (EXIT_SUCCESS if document["all_items_satisfied"]
            else EXIT_BLOCKED)


def _cmd_demo_preflight(args) -> int:
    from pgx.ths6.demo import run_demo_preflight

    document = run_demo_preflight(args.root)
    lines = ["preflight %s" % document["preflight_state"], ""]
    for condition in document["environment_conditions"]:  # type: ignore
        lines.append("%-14s %-8s %s" % (condition["condition_id"],
                                        condition["met"],
                                        condition["description"]))
    lines.append("")
    for step in document["steps"]:  # type: ignore
        lines.append("%-10s %-20s %s" % (step["step_id"], step["state"],
                                         step["title"]))
    if document["stopped_at_step_id"]:
        lines.append("")
        lines.append("stopped at %s; no later step was evaluated and none "
                     "was executed" % document["stopped_at_step_id"])
        lines.extend(_blocker_lines(document["blockers"]))  # type: ignore
    _emit(document, as_json=args.json, lines=lines)
    return int(document["exit_code"])  # type: ignore[arg-type]


def _cmd_verify_pack(args) -> int:
    from pgx.ths6.pack import verify_pack

    document = verify_pack(args.root)
    lines = _pack_lines(document)
    _emit(document, as_json=args.json, lines=lines)
    return int(document["exit_code"])  # type: ignore[arg-type]


def _cmd_build_pack(args) -> int:
    from pgx.ths6.pack import build_pack

    document = build_pack(args.root)
    lines = ["wrote %d document(s)" % len(document["written_paths"])]
    lines.extend(_pack_lines(document))
    _emit(document, as_json=args.json, lines=lines)
    return int(document["exit_code"])  # type: ignore[arg-type]


def _pack_lines(document: Mapping[str, Any]) -> Sequence[str]:
    lines = [
        "pack members            %s" % document.get("member_count"),
        "pack sha256             %s" % (
            document.get("pack_sha256")
            or (document.get("integrity") or {}).get(
                "recomputed_pack_sha256")),
        "pack integrity          %s" % document.get("pack_integrity_pass"),
        "",
        PACK_INTEGRITY_IS_NOT_ACHIEVEMENT,
        "",
        "ths6_achieved           %s" % document.get("ths6_achieved"),
        "release_may_proceed     %s" % document.get("release_may_proceed"),
    ]
    scan = document.get("scan") or {}
    if scan:
        lines.append("")
        lines.append("absolute path leaks     %s"
                     % scan.get("absolute_path_leak_count"))
        lines.append("secret findings         %s"
                     % scan.get("secret_finding_count"))
    return lines


def _cmd_status(args) -> int:
    from pgx.ths6.pack import verify_pack
    from pgx.ths6.status import build_ths6_status, exit_code_for_status

    integrity = verify_pack(args.root).get("pack_integrity_pass")
    document = build_ths6_status(args.root, pack_integrity=bool(integrity))
    lines = [
        "implementation_status      %s" % document["implementation_status"],
        "evidence_pack_integrity    %s"
        % document["evidence_pack_integrity"],
        "ths6_achieved              %s" % document["ths6_achieved"],
        "release_may_proceed        %s" % document["release_may_proceed"],
        "",
        "gates:",
    ]
    for gate_id, result in document["gate_results"].items():  # type: ignore
        lines.append("  %-8s %s" % (gate_id, result))
    lines.append("")
    lines.append("unmet conditions:")
    for entry in document["unmet_conditions"]:  # type: ignore
        lines.append("  - %s" % entry)
    lines.append("")
    lines.append(document["not_clinical_validation"])  # type: ignore
    _emit(document, as_json=args.json, lines=lines)
    return exit_code_for_status(document)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_COMMANDS = {
    "inventory": (_cmd_inventory,
                  "list every declared artifact, classified and hashed"),
    "claims": (_cmd_claims,
               "evaluate every claim against its required evidence"),
    "traceability": (_cmd_traceability,
                     "requirement to implementation to test to evidence"),
    "gates": (_cmd_gates,
              "rebuild gates A to F from their source artifacts"),
    "dod": (_cmd_dod,
            "evaluate all fifteen P0 Definition of Done items"),
    "demo-preflight": (_cmd_demo_preflight,
                       "check the demonstration's preconditions, in order"),
    "verify-pack": (_cmd_verify_pack,
                    "recompute the pack's hashes and compare"),
    "build-pack": (_cmd_build_pack,
                   "write the twelve artifacts and the manifest"),
    "status": (_cmd_status,
               "pack integrity and THS 6 achievement, as separate answers"),
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pgx-ths6",
        description=(
            "Read the committed evidence and report what it supports. This "
            "command has no override: no --force, no --assume, no --fixture "
            "and no --ignore-blocker. Exit 0 means the thing asked about is "
            "genuinely so; 1 means something is invalid; 2 means it has not "
            "happened; 3 means the request was malformed."))
    parser.add_argument("--root", default=".",
                        help="repository root (default: the current "
                             "directory)")
    parser.add_argument("--json", action="store_true",
                        help="emit the full document as JSON")
    sub = parser.add_subparsers(dest="command")
    for name, (_, help_text) in sorted(_COMMANDS.items()):
        child = sub.add_parser(name, help=help_text, description=help_text)
        child.add_argument("--root", default=".",
                           help="repository root")
        child.add_argument("--json", action="store_true",
                           help="emit the full document as JSON")
        if name == "gates":
            child.add_argument("--verbose", action="store_true",
                               help="print every blocker with its owner")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as exc:  # argparse exits 2 for a usage error
        code = exc.code
        if code in (0, None):
            return EXIT_SUCCESS
        return EXIT_USAGE
    if not args.command:
        parser.print_help()
        return EXIT_USAGE
    if not hasattr(args, "verbose"):
        args.verbose = False
    handler = _COMMANDS[args.command][0]
    return handler(args)


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())
