# -*- coding: utf-8 -*-
"""``pgx-verify`` - the WP-19 command line.

One entry point for the whole verification system: inventory the suite, print
the requirement matrix, run a named profile, measure coverage, repeat a subset
to look for flakiness, check that the deterministic artifacts reproduce, and
write the gate status.

Three properties this command line is built around.

**Machine-readable, by default readable.** Every subcommand takes
``--format json`` and emits the same document the artifacts contain, so WP-24
can consume it without parsing a table. Without the flag it prints something a
person can read, and the two are generated from the same data.

**Exit codes mean something.** ``0`` only when the thing asked for succeeded;
``1`` when a required profile failed; ``2`` when a required component is
blocked; ``3`` when the command itself was wrong. A CI job can branch on those
without reading a word of output - and must, because several negative tests
print ``CONFIGURATION_FAILURE`` on purpose while passing.

**The interpreter is this one.** Every subprocess is started with
``sys.executable``. A verifier that ran whatever ``python`` meant on ``PATH``
would be measuring a different installation than the one being released.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

from pgx.verification.artifacts import (
    ARTIFACT_PATHS,
    COVERAGE_PATH,
    REPRODUCIBILITY_PATH,
    build_inventory_document,
    build_matrix_document,
    build_profiles_document,
    write_artifacts,
    write_document,
)
from pgx.verification.coverage_report import measure_coverage
from pgx.verification.discovery import discover
from pgx.verification.errors import VerificationError
from pgx.verification.flaky import compare_runs
from pgx.verification.gate_status import GATE_STATUS_PATH, build_wp19_gate_status
from pgx.verification.inventory import build_inventory
from pgx.verification.matrix import build_matrix
from pgx.verification.model import Outcome
from pgx.verification.profiles import PROFILES, profile_named, profile_names
from pgx.verification.reproducibility import check_generators
from pgx.verification.results import build_profile_result
from pgx.verification.run_evidence import (
    RUN_EVIDENCE_PATH,
    RUN_EVIDENCE_SCHEMA_VERSION,
    host_fingerprint,
    input_fingerprints,
)
from pgx.verification.runner import (
    DEFAULT_HASH_SEED,
    run_profile,
    run_profile_once,
    select_test_ids,
)

__all__ = [
    "EXIT_OK",
    "EXIT_FAILED",
    "EXIT_BLOCKED",
    "EXIT_USAGE",
    "main",
]

EXIT_OK = 0
#: A required profile failed or errored. The software, or a test, is wrong.
EXIT_FAILED = 1
#: A required component could not run. Nothing is known about it, and that is
#: not the same as it being broken.
EXIT_BLOCKED = 2
#: The command was wrong - an unknown profile, a missing tree. Never confused
#: with a test result.
EXIT_USAGE = 3

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_REPO_ROOT)


def _emit(document: Any, as_json: bool, lines: Sequence[str],
          stream: io.TextIOBase) -> None:
    if as_json:
        stream.write(json.dumps(document, indent=2, sort_keys=True,
                                ensure_ascii=True) + "\n")
        return
    for line in lines:
        stream.write(line + "\n")


def _load(root: str):
    discovery = discover(root)
    inventory = build_inventory(discovery)
    return discovery, inventory, build_matrix(inventory)


# ---------------------------------------------------------------------------
# subcommands
# ---------------------------------------------------------------------------

def _cmd_inventory(args: argparse.Namespace, out: io.TextIOBase) -> int:
    discovery, inventory, _ = _load(args.root)
    if args.by_test:
        document: Dict[str, Any] = {
            "discovered_test_count": discovery.count,
            "tests": [entry.as_document() for entry in inventory.entries],
        }
        lines = ["%s  %s  %s" % (entry.test_id, entry.category.value,
                                 entry.work_package)
                 for entry in inventory.entries]
    else:
        document = build_inventory_document(discovery, inventory)
        lines = ["%d tests in %d suites"
                 % (discovery.count, document["suite_count"]), ""]
        for row in document["suites"]:
            lines.append("%-62s %-24s %5d  %s"
                         % (row["module"], row["category"], row["test_count"],
                            row["work_package"]))
    _emit(document, args.format == "json", lines, out)
    return EXIT_OK


def _cmd_matrix(args: argparse.Namespace, out: io.TextIOBase) -> int:
    _, _, matrix = _load(args.root)
    document = build_matrix_document(matrix)
    lines = ["requirement coverage", ""]
    for item in matrix.requirements:
        lines.append("%-12s %-12s %5d tests  %s"
                     % (item.requirement.requirement_id,
                        item.requirement.criticality.value,
                        len(item.test_ids), item.requirement.title))
    lines.extend(["", "category coverage", ""])
    for item in matrix.categories:
        lines.append("%-26s %5d tests in %3d suites"
                     % (item.category.value, len(item.test_ids),
                        len(item.modules)))
    if matrix.uncovered_requirements:
        lines.extend(["", "UNCOVERED REQUIREMENTS: "
                      + ", ".join(matrix.uncovered_requirements)])
    if matrix.unmapped_critical_modules:
        lines.extend(["", "UNMAPPED CRITICAL MODULES: "
                      + ", ".join(matrix.unmapped_critical_modules)])
    _emit(document, args.format == "json", lines, out)
    return EXIT_OK if matrix.is_complete else EXIT_BLOCKED


def _cmd_profiles(args: argparse.Namespace, out: io.TextIOBase) -> int:
    document = build_profiles_document()
    lines = []
    for profile in PROFILES:
        lines.append("%-16s repeats=%d min=%-5d required=%-5s  %s"
                     % (profile.name, profile.repeats, profile.minimum_tests,
                        profile.required, profile.description))
    _emit(document, args.format == "json", lines, out)
    return EXIT_OK


def _run_one(root: str, name: str, hash_seed: str):
    discovery, inventory, _ = _load(root)
    profile = profile_named(name)
    reports = run_profile(profile, inventory, root, hash_seed)
    results = [build_profile_result(profile, report, inventory,
                                    discovery.count)
               for report in reports]
    return profile, inventory, discovery, results


def _cmd_run(args: argparse.Namespace, out: io.TextIOBase) -> int:
    profile, inventory, discovery, results = _run_one(
        args.root, args.profile, args.hash_seed)
    primary = results[0]
    document: Dict[str, Any] = {
        "profile": profile.as_document(),
        "repetitions": [result.as_document(include_outcomes=False)
                        for result in results],
        "result": primary.as_document(include_outcomes=args.include_outcomes),
    }
    if len(results) > 1:
        document["flaky"] = compare_runs(profile.name, results,
                                         args.hash_seed).as_document()
    summary = primary.summary
    lines = [
        "profile        %s" % profile.name,
        "outcome        %s" % primary.outcome.value,
        "discovered     %d" % summary.discovered,
        "executed       %d" % summary.executed,
        "passed         %d" % summary.passed,
        "failed         %d" % summary.failed,
        "errored        %d" % summary.errored,
        "skipped        %d  (unexplained: %d)"
        % (summary.skipped, summary.unexplained_skips),
        "not executed   %d" % summary.not_executed,
        "issue codes    %s" % (", ".join(primary.issue_codes) or "-"),
        "blocked cats   %s" % (", ".join(primary.blocked_categories) or "-"),
    ]
    _emit(document, args.format == "json", lines, out)

    if args.write:
        _write_run_evidence(args.root, profile.name, primary, args.hash_seed)
    return _exit_code(primary, profile.required)


def _exit_code(result, required: bool) -> int:
    if result.outcome in (Outcome.FAIL, Outcome.ERROR):
        return EXIT_FAILED if required else EXIT_OK
    if result.outcome in (Outcome.BLOCKED, Outcome.MISSING):
        return EXIT_BLOCKED if required else EXIT_OK
    return EXIT_OK


def _write_run_evidence(root: str, profile: str, result, hash_seed: str
                        ) -> Dict[str, Any]:
    """Record that this run happened, in a form that can go stale.

    ``passed`` is the run's own outcome and nothing else. A run that failed is
    recorded as a failed run rather than not recorded: the gate status needs to
    be able to say "the last run failed", which is different from "no run".
    """
    document = {
        "environment": host_fingerprint(),
        "hash_seed": hash_seed,
        "inputs": input_fingerprints(root),
        "issue_codes": list(result.issue_codes),
        "passed": result.outcome is Outcome.PASS,
        "profile": profile,
        "schema_version": RUN_EVIDENCE_SCHEMA_VERSION,
        "summary": result.summary.as_document(),
        "categories": {name: dict(info)
                       for name, info in sorted(result.categories.items())},
        "outcome": result.outcome.value,
    }
    write_document(root, RUN_EVIDENCE_PATH, document)
    return document


def _cmd_coverage(args: argparse.Namespace, out: io.TextIOBase) -> int:
    summary = measure_coverage(args.root, profile="full",
                               timeout=args.timeout)
    document = summary.as_document()
    lines = ["status         %s" % summary.status,
             "line percent   %s" % summary.line_percent,
             "branch percent %s" % summary.branch_percent,
             "tool version   %s" % summary.tool_version]
    if summary.reason:
        lines.append("reason         %s" % summary.reason)
    _emit(document, args.format == "json", lines, out)
    if args.write:
        write_document(args.root, COVERAGE_PATH, document)
    return EXIT_OK if summary.status == "MEASURED" else EXIT_BLOCKED


def _cmd_reproducibility(args: argparse.Namespace, out: io.TextIOBase) -> int:
    report = check_generators(args.root)
    document = report.as_document()
    lines = ["status  %s" % report.status]
    for item in report.generators:
        lines.append("  %-12s %-14s %d artifacts  unstable=%d stale=%d"
                     % (item.generator, item.status, item.artifact_count,
                        len(item.unstable_artifacts),
                        len(item.stale_committed_artifacts)))
    _emit(document, args.format == "json", lines, out)
    if args.write:
        write_document(args.root, REPRODUCIBILITY_PATH, document)
    return EXIT_OK if report.status == "REPRODUCIBLE" else EXIT_FAILED


def _cmd_flaky(args: argparse.Namespace, out: io.TextIOBase) -> int:
    profile, _, _, results = _run_one(args.root, "flaky", args.hash_seed)
    report = compare_runs(profile.name, results, args.hash_seed)
    document = report.as_document()
    lines = ["status       %s" % report.status,
             "repetitions  %d" % report.repetitions,
             "flaky tests  %d" % len(report.flaky)]
    for item in report.flaky:
        lines.append("  %s -> %s" % (item.test_id, ", ".join(item.outcomes)))
    _emit(document, args.format == "json", lines, out)
    return EXIT_OK if report.status == "STABLE" else EXIT_FAILED


def _cmd_artifacts(args: argparse.Namespace, out: io.TextIOBase) -> int:
    written = write_artifacts(args.root)
    document = {"written": sorted(written)}
    _emit(document, args.format == "json",
          ["wrote %s" % path for path in sorted(written)], out)
    return EXIT_OK


def _cmd_gate_status(args: argparse.Namespace, out: io.TextIOBase) -> int:
    discovery, inventory, matrix = _load(args.root)
    results: Dict[str, Any] = {}
    if args.run:
        for name in args.run:
            profile = profile_named(name)
            report = run_profile_once(profile, inventory, args.root,
                                      args.hash_seed)
            results[name] = build_profile_result(profile, report, inventory,
                                                 discovery.count)
    coverage = measure_coverage(args.root, profile="full",
                                timeout=args.timeout)
    reproducibility = check_generators(args.root) if args.reproducibility \
        else None
    flaky = None
    if args.flaky:
        # The documented critical subset, repeated. Left as ``None`` when not
        # asked for, because "nobody looked" and "looked and found nothing"
        # are different answers and the field must not conflate them.
        profile = profile_named("flaky")
        repeats = [build_profile_result(profile, report, inventory,
                                        discovery.count)
                   for report in run_profile(profile, inventory, args.root,
                                             args.hash_seed)]
        flaky = compare_runs(profile.name, repeats, args.hash_seed)
    document = build_wp19_gate_status(args.root, matrix, discovery.count,
                                      results, coverage, flaky,
                                      reproducibility)
    lines = ["work package        WP-19",
             "discovered tests    %d" % document["discovered_test_count"],
             "execution status    %s" % document["execution_status"],
             "run evidence        %s" % document["run_evidence_status"],
             "coverage            %s" % document["coverage"]["status"],
             "postgresql          %s" % document["postgresql_test_status"],
             "asgi runtime        %s" % document["asgi_runtime_status"],
             "browser e2e         %s" % document["browser_e2e_status"],
             "reproducibility     %s" % document["reproducibility_status"],
             "flaky               %s" % document["flaky_repeat_status"],
             "claim boundary      %s" % document["claim_boundary_status"],
             "wp20 started        %s" % document["wp20_started"],
             "release may proceed %s" % document["release_may_proceed"],
             "", "blockers:"]
    for blocker in document["blockers"]:
        lines.append("  %-46s %s" % (blocker["code"], blocker["owner"]))
    _emit(document, args.format == "json", lines, out)
    if args.write:
        write_document(args.root, GATE_STATUS_PATH, document)
    return EXIT_OK if document["release_may_proceed"] else EXIT_BLOCKED


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pgx-verify",
        description="WP-19 software verification: inventory, matrix, "
                    "profiles, coverage, flakiness, reproducibility and gate "
                    "status. This command verifies software. It performs no "
                    "scientific validation and produces no approval.")
    parser.add_argument("--root", default=_REPO_ROOT,
                        help="repository root (default: the installed tree)")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    subparsers = parser.add_subparsers(dest="command")

    inventory = subparsers.add_parser(
        "inventory", help="every discovered test, described")
    inventory.add_argument("--by-test", action="store_true",
                           help="one row per test rather than per suite")
    inventory.set_defaults(handler=_cmd_inventory)

    matrix = subparsers.add_parser(
        "matrix", help="requirement and category coverage")
    matrix.set_defaults(handler=_cmd_matrix)

    profiles = subparsers.add_parser("profiles", help="the profile registry")
    profiles.set_defaults(handler=_cmd_profiles)

    run = subparsers.add_parser("run", help="run one profile")
    run.add_argument("--profile", default="fast", choices=profile_names())
    run.add_argument("--hash-seed", default=DEFAULT_HASH_SEED)
    run.add_argument("--include-outcomes", action="store_true",
                     help="include every per-test outcome in JSON output")
    run.add_argument("--write", action="store_true",
                     help="record this run as verification evidence")
    run.set_defaults(handler=_cmd_run)

    coverage = subparsers.add_parser(
        "coverage", help="measure coverage, or report why it could not be")
    coverage.add_argument("--timeout", type=int, default=3600)
    coverage.add_argument("--write", action="store_true")
    coverage.set_defaults(handler=_cmd_coverage)

    reproducibility = subparsers.add_parser(
        "reproducibility",
        help="rebuild every deterministic artifact twice and compare")
    reproducibility.add_argument("--write", action="store_true")
    reproducibility.set_defaults(handler=_cmd_reproducibility)

    flaky = subparsers.add_parser(
        "flaky", help="repeat the documented critical subset and compare")
    flaky.add_argument("--hash-seed", default=DEFAULT_HASH_SEED)
    flaky.set_defaults(handler=_cmd_flaky)

    artifacts = subparsers.add_parser(
        "artifacts", help="write the deterministic artifacts")
    artifacts.set_defaults(handler=_cmd_artifacts)

    gate = subparsers.add_parser(
        "gate-status", help="what WP-19 may say, field by field")
    gate.add_argument("--run", action="append", default=None,
                      choices=profile_names(),
                      help="run this profile first; may be repeated")
    gate.add_argument("--hash-seed", default=DEFAULT_HASH_SEED)
    gate.add_argument("--timeout", type=int, default=3600)
    gate.add_argument("--reproducibility", action="store_true",
                      help="also check artifact reproducibility")
    gate.add_argument("--flaky", action="store_true",
                      help="also repeat the critical subset and compare")
    gate.add_argument("--write", action="store_true")
    gate.set_defaults(handler=_cmd_gate_status)
    return parser


def main(argv: Optional[List[str]] = None,
         out: Optional[io.TextIOBase] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    stream = out if out is not None else sys.stdout
    if getattr(args, "handler", None) is None:
        parser.print_help(stream)
        return EXIT_USAGE
    try:
        return args.handler(args, stream)
    except VerificationError as exc:
        sys.stderr.write("%s: %s\n" % (type(exc).__name__, exc))
        return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover - a developer entry point
    sys.exit(main())
