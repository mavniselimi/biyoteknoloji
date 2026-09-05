# -*- coding: utf-8 -*-
"""``pgx-normalize`` - build, verify and report on canonical datasets (WP-07).

Console entry point: ``pgx-normalize``. ``scripts/normalize.py`` is a thin
wrapper that delegates here, so the logic exists once and the installed package
owns it.

Rules this CLI follows, each for a reason:

* **No network.** Nothing here fetches anything. A canonical build is derived
  from a sealed snapshot that already exists on disk.
* **No implicit overwrite, and no ``--force``.** There is no flag that rewrites
  a sealed build. Two builds of one dataset go to two output roots and are
  compared with ``compare-builds``; a build that could be overwritten would
  make every hash recorded against it a claim about nothing in particular.
* **No "pick first" option.** There is no ``--resolve-ambiguity``, no
  ``--take-first``, no ``--prefer-source``. An ambiguity reaches the queue and
  waits for a human, because every automatic tie-break is a scientific claim
  made by a sort order.
* **No alias-approval shortcut and no reviewer argument.** There is no
  ``--approve-alias``, no ``--reviewer``, no ``--as``. An approval names a real
  person who really looked, and a command-line flag cannot supply one.
* **No promotion.** There is no ``publish``, no ``activate``, no ``approve``,
  and ``quality-check`` is report-only: it computes the gate and prints what it
  says. The dataset stays ``BUILDING``, and nothing in this package can change
  that.
* **Explicit identity allocation.** ``build`` mints UUIDs only when
  ``--allocate-new-identities`` is passed. Reproducing an earlier build means
  passing ``--allocation`` and no allocation flag, so a run that expected to
  reproduce and instead invented identities fails rather than succeeding
  quietly.

Exit codes:

===  =========================================================
0    success, and for ``quality-check`` the gate passed
1    the build was refused, verification found a problem, or the
     quality gate is blocked
2    configuration failure - bad path, unreadable input
3    the named snapshot or build does not exist
===  =========================================================
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from typing import Any, Dict, List, Mapping, Optional

from pgx.application.canonical_schema import (validate_canonical_manifest,
                                              validate_dq_report)
from pgx.normalization.allocation import read_allocation
from pgx.normalization.build import (BUILD_FILES, CanonicalBuildRequest,
                                     build_canonical_dataset, compare_builds,
                                     read_build_manifest, verify_build,
                                     write_build)
from pgx.normalization.errors import CanonicalizationError
from pgx.normalization.legacy_diff import build_legacy_difference_report
from pgx.normalization.quality import (compare_with_artifacts, evaluate_quality,
                                       recount_from_build_path)

__all__ = [
    "DEFAULT_CANONICAL_ROOT",
    "DEFAULT_RAW_ROOT",
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

#: Where snapshots and builds live unless overridden. Rooted in the repository
#: rather than in the working directory: a default that moved with the shell's
#: ``cwd`` would scatter immutable evidence.
DEFAULT_RAW_ROOT = os.path.join(_REPO_ROOT, "data", "raw")
DEFAULT_CANONICAL_ROOT = os.path.join(_REPO_ROOT, "data", "canonical")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser. Separated so tests can exercise it alone."""
    parser = argparse.ArgumentParser(
        prog="pgx-normalize",
        description=("Build, verify and report on canonical datasets. This "
                     "tool never approves, publishes or releases anything, and "
                     "never settles an ambiguity."))

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--text", action="store_true",
                        help="Human-readable output instead of JSON.")

    build = subparser(parser, "build", common,
                      "Assemble a canonical build from a sealed snapshot and "
                      "seal it. Refuses to overwrite an existing build.")
    build.add_argument("--snapshot", required=True,
                       help="Path to the sealed snapshot directory.")
    build.add_argument("--out", default=None,
                       help="Canonical root (default: data/canonical).")
    build.add_argument("--allocation", default=None,
                       help="Existing identity-allocation.json to reuse. "
                            "Required to reproduce an earlier build.")
    build.add_argument("--allocate-new-identities", action="store_true",
                       help="Permit this run to mint UUIDs for canonical keys "
                            "that have none. Without it, a missing identity is "
                            "an error rather than a silent new UUID.")
    build.add_argument("--note", default=None,
                       help="One factual sentence recorded in the manifest.")
    build.add_argument("--repo-root", default=None,
                       help="Repository root for the legacy comparison "
                            "(default: this checkout).")
    build.add_argument("--skip-legacy-comparison", action="store_true",
                       help="Omit legacy-differences.json. The manifest records "
                            "that the stage was skipped rather than passing.")

    verify = subparser(parser, "verify", common,
                       "Re-hash a sealed build and check its summary against "
                       "its own artifacts.")
    verify.add_argument("--build", required=True,
                        help="Path to the sealed canonical build directory.")

    inspect = subparser(parser, "inspect", common,
                        "Print a sealed build's manifest without re-hashing it.")
    inspect.add_argument("--build", required=True,
                         help="Path to the sealed canonical build directory.")

    queue = subparser(parser, "queue", common,
                      "List what still needs a human. Read-only: this command "
                      "records no decision and offers no way to make one.")
    queue.add_argument("--build", required=True,
                       help="Path to the sealed canonical build directory.")
    queue.add_argument("--status", default=None,
                       help="Filter by resolution status (AMBIGUOUS, "
                            "UNRESOLVED, BROKEN_REFERENCE, INVALID_INPUT).")
    queue.add_argument("--limit", type=int, default=50,
                       help="Maximum items to print (default 50).")

    dq = subparser(parser, "dq", common,
                   "Print the data-quality report stored in a sealed build.")
    dq.add_argument("--build", required=True,
                    help="Path to the sealed canonical build directory.")

    compare_legacy = subparser(
        parser, "compare-legacy", common,
        "Print the legacy difference report stored in a sealed build.")
    compare_legacy.add_argument("--build", required=True,
                                help="Path to the sealed build directory.")

    compare = subparser(parser, "compare-builds", common,
                        "Compare two sealed builds file by file and by content "
                        "hash. This is how a reproducibility claim is checked.")
    compare.add_argument("--left", required=True, help="First build directory.")
    compare.add_argument("--right", required=True, help="Second build directory.")

    quality = subparser(
        parser, "quality-check", common,
        "Report whether the quality gate passes. Report-only: it records no "
        "decision, names no reviewer and changes no dataset state.")
    quality.add_argument("--build", required=True,
                         help="Path to the sealed canonical build directory.")
    quality.add_argument("--source-policy-status", default=None,
                         help="The recorded source-policy status for this "
                              "dataset. Omitted means no approval is on "
                              "record, which blocks.")

    # Deliberately absent, and named here so their absence is visible in
    # --help's source rather than only in a document: approve-alias, decide,
    # resolve-ambiguity, publish, activate, quality-approve, and any --reviewer
    # or --force flag.
    return parser


def subparser(parser: argparse.ArgumentParser, name: str,
              common: argparse.ArgumentParser,
              help_text: str) -> argparse.ArgumentParser:
    """Register one subcommand, creating the subparser group on demand."""
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
        "build": _cmd_build,
        "verify": _cmd_verify,
        "inspect": _cmd_inspect,
        "queue": _cmd_queue,
        "dq": _cmd_dq,
        "compare-legacy": _cmd_compare_legacy,
        "compare-builds": _cmd_compare_builds,
        "quality-check": _cmd_quality_check,
    }
    try:
        return handlers[args.command](args)
    except CanonicalizationError as exc:
        code = getattr(exc, "code", None)
        _emit(args, {"error": str(exc), "code": code}, str(exc))
        if code in ("BUILD_MISSING", "MANIFEST_MISSING", "SNAPSHOT_UNREADABLE"):
            return EXIT_NOT_FOUND
        return EXIT_REFUSED
    except (OSError, ValueError) as exc:
        _emit(args, {"error": str(exc), "code": "CONFIGURATION_FAILURE"},
              "CONFIGURATION_FAILURE: %s" % exc)
        return EXIT_CONFIGURATION_FAILURE


# -- commands -----------------------------------------------------------


def _cmd_build(args) -> int:
    output_root = args.out or DEFAULT_CANONICAL_ROOT
    if not os.path.isdir(args.snapshot):
        _emit(args, {"error": "no snapshot at %s" % args.snapshot,
                     "code": "SNAPSHOT_MISSING"},
              "no snapshot at %s" % args.snapshot)
        return EXIT_NOT_FOUND

    request = CanonicalBuildRequest(
        snapshot_root=args.snapshot,
        output_root=output_root,
        allocation_path=args.allocation,
        allow_new_identities=args.allocate_new_identities,
        build_note=args.note)
    build = build_canonical_dataset(request)

    report = evaluate_quality(build)
    documents: Dict[str, Any] = {"dq-report.json": report.to_json()}
    if not args.skip_legacy_comparison:
        repo_root = args.repo_root or _REPO_ROOT
        differences = build_legacy_difference_report(build, repo_root)
        documents["legacy-differences.json"] = differences.to_json()

    result = write_build(build, output_root, extra_documents=documents)

    ok, problems = compare_with_artifacts(result.build_path)
    payload = result.to_json()
    payload["dq_gate_passed"] = report.decision.passed
    payload["dq_blocking_codes"] = list(report.decision.blocking_codes)
    payload["summary_agrees_with_artifacts"] = ok
    payload["summary_disagreements"] = list(problems)
    payload["legacy_comparison"] = (
        "skipped" if args.skip_legacy_comparison else "written")
    payload["dataset_lifecycle_state"] = "BUILDING"

    text = "\n".join([
        "canonical build sealed at %s" % result.build_path,
        "  build key    %s" % build.build_key,
        "  content hash %s" % build.content_hash(),
        "  identities   %d minted, %d reused"
        % (len(build.allocation_result.minted),
           len(build.allocation_result.reused)),
        "  dataset      BUILDING (a build is not an approval)",
        "",
        report.render(),
    ])
    _emit(args, payload, text)
    return EXIT_OK if ok else EXIT_REFUSED


def _cmd_verify(args) -> int:
    """Re-hash, re-count, and re-check against the published schemas.

    Three independent checks, reported separately because they fail for
    different reasons: the bytes changed, the recorded summary disagrees with
    the artifacts it describes, or the documents no longer match the schema
    this project publishes.
    """
    ok, problems = verify_build(args.build)
    agrees, disagreements = (True, ())
    if ok:
        agrees, disagreements = compare_with_artifacts(args.build)

    schema_problems: List[str] = []
    manifest_path = os.path.join(args.build, "manifest.json")
    if os.path.isfile(manifest_path):
        schema_problems.extend(
            "manifest.json: %s" % problem for problem in
            validate_canonical_manifest(_read_json(manifest_path, "")))
    report_path = os.path.join(args.build, "dq-report.json")
    if os.path.isfile(report_path):
        schema_problems.extend(
            "dq-report.json: %s" % problem for problem in
            validate_dq_report(_read_json(report_path, "")))

    payload = {
        "build_path": args.build,
        "checksums_match": ok,
        "checksum_problems": list(problems),
        "summary_agrees_with_artifacts": agrees,
        "summary_disagreements": list(disagreements),
        "schema_valid": not schema_problems,
        "schema_problems": schema_problems,
        "recount": recount_from_build_path(args.build),
        "ok": bool(ok and agrees and not schema_problems),
    }
    lines = ["verify %s" % args.build,
             "  checksums              %s" % ("ok" if ok else "FAILED"),
             "  summary vs artifacts   %s" % ("ok" if agrees else "FAILED"),
             "  published schemas      %s" % ("ok" if not schema_problems
                                              else "FAILED")]
    for problem in list(problems) + list(disagreements) + schema_problems:
        lines.append("    - %s" % problem)
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK if payload["ok"] else EXIT_REFUSED


def _cmd_inspect(args) -> int:
    manifest = read_build_manifest(args.build)
    present = sorted(name for name in BUILD_FILES
                     if os.path.isfile(os.path.join(args.build, name)))
    manifest["files_present"] = present
    manifest["files_absent"] = [name for name in BUILD_FILES
                                if name not in present]
    lines = [
        "canonical build %s" % manifest.get("canonical_build_key"),
        "  dataset        %s" % manifest.get("dataset_public_id"),
        "  content hash   %s" % manifest.get("content_hash"),
        "  snapshot       %s (%s)" % (manifest.get("snapshot_manifest_hash"),
                                      manifest.get("snapshot_state")),
        "  lifecycle      %s" % manifest.get("dataset_lifecycle_state"),
        "  files present  %s" % ", ".join(present),
    ]
    absent = manifest["files_absent"]
    if absent:
        lines.append("  files absent   %s" % ", ".join(absent))
    _emit(args, manifest, "\n".join(lines))
    return EXIT_OK


def _cmd_queue(args) -> int:
    rows = _read_ndjson(os.path.join(args.build, "resolution-queue.ndjson"))
    if args.status:
        wanted = args.status.strip().upper()
        rows = [row for row in rows if row.get("status") == wanted]
    payload = {
        "build_path": args.build,
        "filter_status": args.status,
        "item_count": len(rows),
        "decided_count": sum(1 for row in rows if row.get("decided_by")),
        "items": rows[:max(args.limit, 0)],
        "note": ("Read-only. This command records no decision, and this tool "
                 "offers no way to make one: a resolution decision names a "
                 "human who examined the candidates."),
    }
    lines = ["resolution queue: %d item(s)%s"
             % (len(rows), " matching %s" % args.status if args.status else "")]
    for row in rows[:max(args.limit, 0)]:
        lines.append("  %-16s %-6s %-40s candidates=%s"
                     % (row.get("status"), row.get("entity_type"),
                        str(row.get("submitted_value"))[:40],
                        ",".join(row.get("candidate_keys") or ()) or "-"))
    if not rows:
        lines.append("  nothing is waiting for review in this build.")
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK


def _cmd_dq(args) -> int:
    payload = _read_json(os.path.join(args.build, "dq-report.json"),
                         "no dq-report.json in %s" % args.build)
    decision = payload.get("decision") or {}
    lines = ["data quality report for %s" % payload.get("canonical_build_key"),
             "  gate      %s" % ("PASS" if decision.get("passed") else "BLOCKED"),
             "  lifecycle %s" % payload.get("dataset_lifecycle_state")]
    for item in payload.get("reconciliations") or ():
        lines.append("  %-26s input %d = accepted %d + rejected %d + deferred %d%s"
                     % (item.get("stream"), item.get("input_count", 0),
                        item.get("accepted", 0), item.get("rejected", 0),
                        item.get("deferred", 0),
                        "" if item.get("balances") else "   IMBALANCED"))
    for item in payload.get("issues") or ():
        lines.append("  %-14s %-42s %s (%d)"
                     % (item.get("severity"), item.get("code"),
                        item.get("subject"), item.get("count", 0)))
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK if decision.get("passed") else EXIT_REFUSED


def _cmd_compare_legacy(args) -> int:
    payload = _read_json(os.path.join(args.build, "legacy-differences.json"),
                         "no legacy-differences.json in %s. The build may have "
                         "been produced with --skip-legacy-comparison."
                         % args.build)
    lines = ["legacy difference report for %s"
             % payload.get("canonical_build_key")]
    for check in payload.get("claim_checks") or ():
        lines.append("  claim %-32s claimed %s observed %s  %s"
                     % (check.get("claim_id"), check.get("claimed_value"),
                        check.get("observed_value"),
                        "AGREES" if check.get("agrees")
                        else ("DISAGREES (expected)"
                              if check.get("expected_to_disagree")
                              else "DISAGREES (unexplained)")))
    for finding in payload.get("findings") or ():
        lines.append("  - %s" % finding)
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK


def _cmd_compare_builds(args) -> int:
    comparison = compare_builds(args.left, args.right)
    payload = comparison.to_json()
    lines = ["compare %s <-> %s" % (args.left, args.right),
             "  reproducible          %s" % comparison.reproducible,
             "  content hash matches  %s" % comparison.content_hash_matches,
             "  byte-identical apart from provenance  %s"
             % comparison.byte_identical_apart_from_provenance]
    for name in comparison.differing_files:
        lines.append("  differs: %s" % name)
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK if comparison.reproducible else EXIT_REFUSED


def _cmd_quality_check(args) -> int:
    """Report the gate. Deliberately incapable of recording a decision.

    There is no ``--approve``, no ``--reviewer`` and no state transition. The
    command answers "would a quality check pass right now", which is a
    precondition for a human decision and not the decision itself.
    """
    stored = _read_json(os.path.join(args.build, "dq-report.json"),
                        "no dq-report.json in %s" % args.build)
    decision = stored.get("decision") or {}
    passed = bool(decision.get("passed"))
    payload = {
        "build_path": args.build,
        "canonical_build_key": stored.get("canonical_build_key"),
        "gate_passed": passed,
        "blocking_codes": list(decision.get("blocking_codes") or ()),
        "advisory_codes": list(decision.get("advisory_codes") or ()),
        "source_policy_status": args.source_policy_status,
        "dataset_lifecycle_state": stored.get("dataset_lifecycle_state"),
        "effect": ("None. This command reports the gate and changes nothing. "
                   "Marking a dataset QUALITY_CHECKED is a human decision "
                   "recorded with a named reviewer, and this tool cannot "
                   "record one."),
    }
    lines = ["quality gate for %s: %s"
             % (stored.get("canonical_build_key"),
                "PASS" if passed else "BLOCKED")]
    for code in payload["blocking_codes"]:
        lines.append("  blocking  %s" % code)
    for code in payload["advisory_codes"]:
        lines.append("  advisory  %s" % code)
    lines.append("  the dataset remains %s; this command changed nothing."
                 % stored.get("dataset_lifecycle_state"))
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK if passed else EXIT_REFUSED


# -- helpers ------------------------------------------------------------


def _emit(args, payload: Mapping[str, Any], text: str) -> None:
    if getattr(args, "text", False):
        sys.stdout.write(text.rstrip("\n") + "\n")
    else:
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True,
                                    ensure_ascii=False) + "\n")


def _read_json(path: str, missing_message: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        raise ValueError(missing_message)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_ndjson(path: str) -> List[Dict[str, Any]]:
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if text:
                rows.append(json.loads(text))
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
