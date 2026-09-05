# -*- coding: utf-8 -*-
"""``pgx-safety`` - the WP-20 release-blocking safety gate.

Six subcommands, one of which blocks a release:

    pgx-safety registry            the twelve invariants, validated
    pgx-safety negative-controls   every unsafe fixture, through its evaluator
    pgx-safety check               the gate. Non-zero on anything but PASS.
    pgx-safety report              the full report document
    pgx-safety gate-status         every component, reported separately
    pgx-safety artifacts           write the deterministic documents

``check`` is the authoritative one. It returns non-zero on ``FAIL``,
``BLOCKED``, ``NOT_EXECUTED`` **and** ``STALE`` - all four, because a release
must not proceed on "we do not know" any more than on "we know it is broken".
A CI job reads the exit code, never the output: several tests in this
repository print ``CONFIGURATION_FAILURE`` on purpose while passing, and a job
grepping stdout would fail a green suite.

Test execution reuses WP-19's runner rather than building a second one. Two
enumerations of one suite would eventually disagree, and nobody would know
which to believe.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.safety.artifacts import (
    EXECUTION_PATH,
    invalidate_execution,
    write_artifacts,
    write_document,
    write_execution,
)
from pgx.safety.errors import GateRefusal, SafetyError
from pgx.safety.execution import SafetyExecution
from pgx.safety.freshness import compare_fingerprints, fingerprint_inputs
from pgx.safety.gate_status import (
    GATE_STATUS_PATH,
    build_wp20_gate_status,
    safety_gate_state,
)
from pgx.safety.registry import load_registry
from pgx.safety.report import build_report, execute_safety, load_control_driver
from pgx.safety.vocabulary import ExecutionState

__all__ = ["EXIT_OK", "EXIT_FAILED", "EXIT_BLOCKED", "EXIT_USAGE", "main"]

EXIT_OK = 0
#: An invariant failed, or a negative control was not detected.
EXIT_FAILED = 1
#: An invariant is blocked, unexecuted, or its evidence is stale. Nothing is
#: *known* to be wrong - and nothing is known to be right either.
EXIT_BLOCKED = 2
#: The command itself was wrong, or the registry refused to load. Never
#: confused with a safety result.
EXIT_USAGE = 3

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_REPO_ROOT)

#: The WP-19 profile that runs the safety suites. Named here so the CLI and the
#: verification profile registry cannot drift apart.
SAFETY_PROFILE = "safety"


def _emit(document: Any, as_json: bool, lines: Sequence[str],
          stream) -> None:
    if as_json:
        stream.write(json.dumps(document, indent=2, sort_keys=True,
                                ensure_ascii=True) + "\n")
        return
    for line in lines:
        stream.write(line + "\n")


def _run_safety_tests(root: str, registry) -> Tuple[Dict[str, Dict[str, int]],
                                                    str]:
    """Execute the invariants' test modules with WP-19's runner.

    Returns per-module counts and a note. On a runner failure the counts are
    empty, which makes every invariant ``NOT_EXECUTED`` - the honest outcome,
    because a runner that did not report has told us nothing.
    """
    from pgx.verification.discovery import discover
    from pgx.verification.inventory import build_inventory
    from pgx.verification.profiles import Profile
    from pgx.verification.results import build_profile_result
    from pgx.verification.runner import run_profile_once

    modules = sorted({module for modules in registry.resolved_modules.values()
                      for module in modules})
    if not modules:
        return {}, "the registry resolved no test modules"

    discovery = discover(root)
    inventory = build_inventory(discovery)
    profile = Profile(
        name=SAFETY_PROFILE,
        description="Every test module the WP-20 invariant registry names.",
        modules=tuple(modules),
        minimum_tests=200,
        offline=True)

    try:
        report = run_profile_once(profile, inventory, root)
    except Exception as exc:
        return {}, "the verification runner failed: %s" % type(exc).__name__

    result = build_profile_result(profile, report, inventory, discovery.count)
    per_module: Dict[str, Dict[str, int]] = {}
    for outcome in result.outcomes:
        module = outcome.test_id.rsplit(".", 2)[0]
        counts = per_module.setdefault(
            module, {"executed": 0, "passed": 0, "failed": 0, "errored": 0,
                     "skipped": 0, "unexplained_skips": 0})
        counts["executed"] += 1
        name = outcome.outcome.value
        if name == "PASS":
            counts["passed"] += 1
        elif name == "FAIL":
            counts["failed"] += 1
        elif name == "ERROR":
            counts["errored"] += 1
        elif name == "SKIP":
            counts["skipped"] += 1
            classification = outcome.skip_classification
            if classification is not None and classification.value != "ALLOWED":
                counts["unexplained_skips"] += 1
    return per_module, ""


def _evidence_state(root: str) -> Tuple[str, str]:
    """Whether recorded evidence is current, stale, absent or invalidated."""
    path = os.path.join(root, *EXECUTION_PATH.split("/"))
    if not os.path.exists(path):
        return "ABSENT", ("no safety execution evidence has been recorded; "
                          "run `pgx-safety check --write`")
    try:
        with io.open(path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (ValueError, OSError):
        return "ABSENT", "the recorded evidence could not be read"
    if document.get("invalidated"):
        return "INVALIDATED", str(document.get("invalidation_reason", ""))
    if not document.get("complete"):
        return "ABSENT", "the recorded run did not complete"
    changed = compare_fingerprints(document.get("inputs") or {},
                                   fingerprint_inputs(root))
    if changed:
        return "STALE", ("the following inputs changed after the run was "
                         "recorded: %s" % ", ".join(changed))
    return "CURRENT", ""


def _environment_facts(root: str) -> Dict[str, Any]:
    """PostgreSQL, active release and holdout counts - measured, not assumed."""
    facts: Dict[str, Any] = {"postgresql_available": None,
                             "active_release_available": None,
                             "holdout_case_count": None}
    try:
        import psycopg  # noqa: F401
    except ImportError:
        facts["postgresql_available"] = False
    else:
        # The driver is present. A driver is not a database, and WP-20 does not
        # start one, so this stays unknown rather than becoming True.
        facts["postgresql_available"] = bool(os.environ.get(
            "TEST_DATABASE_URL")) or None

    status = os.path.join(root, "data", "validation",
                          "wp18-real-gate-status.json")
    if os.path.exists(status):
        try:
            with io.open(status, "r", encoding="utf-8") as handle:
                wp18 = json.load(handle)
            facts["holdout_case_count"] = wp18.get("holdout_case_count")
            facts["active_release_available"] = wp18.get(
                "active_release_available")
        except (ValueError, OSError):
            pass
    return facts


def _gate(root: str) -> Tuple[Any, Any, Dict[str, Any], Dict[str, Any], str]:
    """Load, execute, report, and build the gate status. Used by three commands."""
    registry = load_registry(root)
    per_module, note = _run_safety_tests(root, registry)
    execution = execute_safety(root, registry, per_module)
    report = build_report(root, registry, execution)
    state, reason = _evidence_state(root)
    facts = _environment_facts(root)
    status = build_wp20_gate_status(
        root, registry, execution, report, evidence_state=state,
        evidence_reason=reason, **facts)
    return registry, execution, report, status, note


# ---------------------------------------------------------------------------
# subcommands
# ---------------------------------------------------------------------------

def _cmd_registry(args, out) -> int:
    from pgx.safety.artifacts import build_registry_document
    registry = load_registry(args.root)
    document = build_registry_document(registry)
    lines = ["%d invariants, %d negative controls"
             % (registry.invariant_count, registry.control_count), ""]
    for definition in registry.definitions:
        lines.append("%-16s %-24s %2d controls  %s"
                     % (definition.invariant_id.value,
                        definition.implementation_state.value,
                        len(definition.negative_controls),
                        definition.title[:56]))
    _emit(document, args.format == "json", lines, out)
    return EXIT_OK


def _cmd_controls(args, out) -> int:
    driver = load_control_driver()
    if driver is None:
        out.write("the control fixtures are not present in this "
                  "installation; nothing was executed\n")
        return EXIT_BLOCKED
    outcomes = driver.run_controls(args.root)
    document = {invariant: [c.as_document() for c in controls]
                for invariant, controls in sorted(outcomes.items())}
    total = detected = 0
    lines = []
    for invariant in sorted(outcomes):
        negative = [c for c in outcomes[invariant] if c.kind == "NEGATIVE"]
        satisfied = sum(1 for c in negative if c.satisfied)
        safe_ok = all(c.satisfied for c in outcomes[invariant]
                      if c.kind == "SAFE")
        total += len(negative)
        detected += satisfied
        lines.append("%-16s safe=%-5s negative %d/%d detected"
                     % (invariant, safe_ok, satisfied, len(negative)))
    lines.extend(["", "negative controls detected: %d / %d" % (detected, total)])
    _emit(document, args.format == "json", lines, out)
    return EXIT_OK if detected == total and total else EXIT_FAILED


def _cmd_check(args, out) -> int:
    """The release-blocking command. Non-zero on anything but PASS."""
    try:
        registry, execution, report, status, note = _gate(args.root)
    except SafetyError as exc:
        if args.write:
            invalidate_execution(args.root, "%s: %s"
                                 % (type(exc).__name__, exc))
        out.write("SAFETY GATE REFUSED: %s: %s\n" % (type(exc).__name__, exc))
        return EXIT_USAGE

    state = safety_gate_state(execution)
    lines = ["safety gate         %s" % state.value,
             "invariants          %d registered, %d executed"
             % (status["registered_invariant_count"],
                status["executed_invariant_count"]),
             "negative controls   %d / %d detected"
             % (status["detected_negative_control_count"],
                status["negative_control_count"]),
             "false reassurance   %s violation(s) over a corpus of %s"
             % (status["false_reassurance_violation_count"],
                status["false_reassurance_corpus_size"]),
             "evidence            %s" % status["evidence_state"],
             "release may proceed %s" % status["release_may_proceed"], ""]
    for identifier in sorted(status["invariant_status"]):
        info = status["invariant_status"][identifier]
        lines.append("  %-16s %-14s %-22s %d/%d controls"
                     % (identifier, info["execution_state"],
                        info["compliance_state"],
                        info["negative_controls_detected"],
                        info["negative_control_count"]))
    if note:
        lines.extend(["", "note: %s" % note])
    lines.append("")
    lines.append("blockers:")
    for blocker in status["blockers"]:
        lines.append("  %-42s %s" % (blocker["code"], blocker["owner"]))

    _emit(status, args.format == "json", lines, out)

    if args.write:
        # The report is a description of what was measured and is written
        # whatever the outcome - a blocked gate still produced 37 control
        # results somebody needs to read. The *execution evidence* is the
        # record freshness is checked against and the only thing that could
        # let a release proceed, so it is written only on PASS and replaced by
        # an explicit invalidation otherwise. Leaving an earlier success in
        # place would let a failing build inherit a passing gate.
        from pgx.safety.artifacts import REPORT_PATH
        write_document(args.root, REPORT_PATH, report)
        if state is ExecutionState.PASS:
            write_execution(args.root, execution, report)
        else:
            invalidate_execution(
                args.root,
                "the safety gate reported %s; previous evidence is no longer "
                "valid" % state.value)
        write_document(args.root, GATE_STATUS_PATH, status)

    if state in (ExecutionState.FAIL, ExecutionState.ERROR):
        return EXIT_FAILED
    if state is not ExecutionState.PASS:
        return EXIT_BLOCKED
    if status["evidence_state"] in ("STALE", "ABSENT", "INVALIDATED"):
        return EXIT_BLOCKED
    return EXIT_OK if status["release_may_proceed"] else EXIT_BLOCKED


def _cmd_report(args, out) -> int:
    registry, execution, report, status, note = _gate(args.root)
    summary = report["summary"]
    lines = ["work package        WP-20",
             "registered          %d" % summary["registered_invariant_count"],
             "executed            %d" % summary["executed_invariant_count"],
             "negative controls   %d / %d detected"
             % (summary["detected_negative_control_count"],
                summary["negative_control_count"]),
             "tests executed      %d" % summary["tests_executed"],
             "false reassurance   %d / %d"
             % (report["false_reassurance"]["violation_count"],
                report["false_reassurance"]["corpus_size"]),
             "", "execution states:"]
    for state, count in sorted(summary["execution_states"].items()):
        lines.append("  %-16s %d" % (state, count))
    _emit(report, args.format == "json", lines, out)
    if args.write:
        write_execution(args.root, execution, report)
    return EXIT_OK


def _cmd_gate_status(args, out) -> int:
    registry, execution, report, status, note = _gate(args.root)
    lines = ["work package        WP-20",
             "safety gate         %s" % status["safety_gate_status"],
             "evidence            %s" % status["evidence_state"],
             "claim boundary      %s" % status["claim_boundary_status"],
             "postgresql          %s" % status["postgresql_available"],
             "active release      %s" % status["active_release_available"],
             "holdout cases       %s" % status["holdout_case_count"],
             "ci job configured   %s" % status["ci_job_configured"],
             "ci job executed     %s" % status["ci_job_executed"],
             "wp21 started        %s" % status["wp21_started"],
             "release may proceed %s" % status["release_may_proceed"],
             "", "blockers:"]
    for blocker in status["blockers"]:
        lines.append("  %-42s %s" % (blocker["code"], blocker["owner"]))
    _emit(status, args.format == "json", lines, out)
    if args.write:
        write_document(args.root, GATE_STATUS_PATH, status)
    return EXIT_OK if status["release_may_proceed"] else EXIT_BLOCKED


def _cmd_artifacts(args, out) -> int:
    written = write_artifacts(args.root)
    _emit({"written": sorted(written)}, args.format == "json",
          ["wrote %s" % path for path in sorted(written)], out)
    return EXIT_OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pgx-safety",
        description="WP-20 safety invariant gate. Twelve invariants, each with "
                    "a safe control and a detected unsafe control. This gate "
                    "verifies software detectors. It performs no clinical or "
                    "scientific validation and approves nothing.")
    parser.add_argument("--root", default=_REPO_ROOT)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    subparsers = parser.add_subparsers(dest="command")

    registry = subparsers.add_parser("registry",
                                     help="the twelve invariants, validated")
    registry.set_defaults(handler=_cmd_registry)

    controls = subparsers.add_parser(
        "negative-controls",
        help="drive every unsafe fixture through its evaluator")
    controls.set_defaults(handler=_cmd_controls)

    check = subparsers.add_parser(
        "check", help="the release-blocking gate; non-zero on anything but PASS")
    check.add_argument("--write", action="store_true",
                       help="record the run as evidence, or invalidate the "
                            "previous one if it did not pass")
    check.set_defaults(handler=_cmd_check)

    report = subparsers.add_parser("report", help="the full safety report")
    report.add_argument("--write", action="store_true")
    report.set_defaults(handler=_cmd_report)

    gate = subparsers.add_parser("gate-status",
                                 help="every component, reported separately")
    gate.add_argument("--write", action="store_true")
    gate.set_defaults(handler=_cmd_gate_status)

    artifacts = subparsers.add_parser(
        "artifacts", help="write the deterministic documents and schemas")
    artifacts.set_defaults(handler=_cmd_artifacts)
    return parser


def main(argv: Optional[List[str]] = None, out=None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    stream = out if out is not None else sys.stdout
    if getattr(args, "handler", None) is None:
        parser.print_help(stream)
        return EXIT_USAGE
    try:
        return args.handler(args, stream)
    except SafetyError as exc:
        sys.stderr.write("%s: %s\n" % (type(exc).__name__, exc))
        return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover - a developer entry point
    sys.exit(main())
