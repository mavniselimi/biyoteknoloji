# -*- coding: utf-8 -*-
"""``pgx-benchmark`` - define, run and publish the WP-21 validation metrics.

Five subcommands:

``definitions``
    Print the metric registry and the failure-path catalogue. Available now:
    definitions exist before results, which is the whole design.

``report``
    Print the public validation report. In this repository every metric is
    ``NOT_EXECUTED`` and no percentage appears.

``gate-status``
    Two answers, separately: the machinery is implemented; no release has been
    validated.

``artifacts``
    Regenerate every committed WP-21 document, deterministically.

``run``
    Execute a benchmark against a pinned release. Refuses here, because there
    is no release to pin, no holdout case to execute and no restricted storage
    to read them from.

Exit codes:

``0``  a report was produced and is eligible
``1``  an invariant, schema or calculation failure
``2``  blocked: a precondition outside this command's control is unmet
``3``  invalid usage

``run`` and ``gate-status`` exit ``2`` in this repository. That is the correct
outcome and not a defect: ``0`` would mean a release had been validated.

There is deliberately no ``--use-test-fixture`` flag. The synthetic release
that proves the engine can render a numerical table lives in the test suite
and is injected there; a production switch that swapped real emptiness for
synthetic numbers would be one command-line typo away from a fabricated
validation result.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.application.benchmark_schema import (build_schemas,
                                              validate_dashboard_feed,
                                              validate_failure_paths,
                                              validate_metric_definitions,
                                              validate_validation_report,
                                              validate_wp21_gate_status)
from pgx.validation.benchmark_artifacts import (DEFINITIONS_PATH,
                                                FAILURE_PATHS_PATH, FEED_PATH,
                                                GATE_STATUS_PATH, REPORT_PATH,
                                                build_artifacts,
                                                build_real_feed,
                                                build_real_report,
                                                write_document)
from pgx.validation.benchmark_gate_status import build_wp21_gate_status
from pgx.validation.benchmark_report import (build_failure_path_document,
                                             build_metric_definitions_document)
from pgx.validation.metric_definitions import (METRIC_DEFINITIONS,
                                               MetricStatus)

__all__ = ["ARTIFACT_PATHS", "EXIT_BLOCKED", "EXIT_FAILED", "EXIT_OK",
           "EXIT_USAGE", "main"]

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_BLOCKED = 2
EXIT_USAGE = 3

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

ARTIFACT_PATHS: Tuple[str, ...] = (
    DEFINITIONS_PATH, FAILURE_PATHS_PATH, REPORT_PATH, FEED_PATH,
    GATE_STATUS_PATH,
) + tuple(sorted(build_schemas()))


def _out(stream, text: str = "") -> None:
    stream.write(text + "\n")


def _write(root: str, relative: str, document: Mapping[str, Any]) -> None:
    write_document(root, relative, document)


# -- subcommands ---------------------------------------------------------

def _cmd_definitions(args, stream) -> int:
    if args.json:
        _out(stream, json.dumps(
            {"metrics": build_metric_definitions_document(),
             "failure_paths": build_failure_path_document()},
            indent=2, sort_keys=True, ensure_ascii=True))
        return EXIT_OK
    _out(stream, "metric registry     %d metric(s), %d threshold(s)"
         % (len(METRIC_DEFINITIONS), 0))
    _out(stream, "")
    for definition in METRIC_DEFINITIONS:
        _out(stream, "  %-12s %-9s %-9s %s"
             % (definition.metric_id, definition.kind.value,
                "evidence" if definition.is_validation_evidence else "regress",
                definition.title))
        _out(stream, "               roles: %s"
             % ", ".join(role.value for role in definition.eligible_roles))
    _out(stream, "")
    _out(stream, "no metric carries a threshold: a threshold needs a "
                 "predeclared, reviewable policy and none exists")
    return EXIT_OK


def _report_exit(report: Mapping[str, Any]) -> int:
    """``0`` only when a benchmark actually produced an eligible result."""
    if not report.get("benchmark_executed"):
        return EXIT_BLOCKED
    if int(report.get("numeric_validation_metric_count") or 0) <= 0:
        return EXIT_BLOCKED
    return EXIT_OK


def _cmd_report(args, stream) -> int:
    root = args.root or _REPO_ROOT
    report = build_real_report(root)
    problems = validate_validation_report(report)
    if problems:
        for problem in problems:
            _out(stream, "SCHEMA: %s" % problem)
        return EXIT_FAILED
    if args.json:
        _out(stream, json.dumps(report, indent=2, sort_keys=True,
                                ensure_ascii=True))
        return _report_exit(report)

    _out(stream, "benchmark executed  %s" % report["benchmark_executed"])
    _out(stream, "active release      %s"
         % report["active_release_available"])
    _out(stream, "numeric validation  %d metric(s)"
         % report["numeric_validation_metric_count"])
    _out(stream, "")
    for partition in report["partitions"]:
        _out(stream, "  %-22s role=%-17s evidence=%-5s cases=%s"
             % (partition["section"], partition["role"],
                partition["is_validation_evidence"],
                partition["case_count"]))
        counts = ", ".join("%s=%d" % item for item
                           in sorted(partition["status_counts"].items()))
        _out(stream, "      %s" % counts)
    _out(stream, "")
    _out(stream, "combined overall    %s (by design)"
         % report["combined_overall_metric"])
    _out(stream, "restricted evidence %s"
         % report["restricted_case_evidence_artifact"])
    _out(stream, "")
    for blocker in report["blockers"]:
        _out(stream, "  %-46s %s" % (blocker["code"], blocker["owner"]))
    return _report_exit(report)


def _cmd_gate_status(args, stream) -> int:
    root = args.root or _REPO_ROOT
    status = build_wp21_gate_status(root)
    problems = validate_wp21_gate_status(status)
    if problems:
        for problem in problems:
            _out(stream, "SCHEMA: %s" % problem)
        return EXIT_FAILED
    if args.write:
        _write(root, GATE_STATUS_PATH, status)
    if args.json:
        _out(stream, json.dumps(status, indent=2, sort_keys=True,
                                ensure_ascii=True))
    else:
        _out(stream, "work package        %s" % status["work_package"])
        _out(stream, "implementation      %s" % status["implementation_status"])
        _out(stream, "benchmark gate      %s" % status["benchmark_gate_status"])
        _out(stream, "metric definitions  %d" % status["metric_definition_count"])
        _out(stream, "failure paths       %d" % status["failure_path_count"])
        _out(stream, "thresholds          %d" % status["threshold_count"])
        _out(stream, "development cases   %d" % status["development_case_count"])
        _out(stream, "internal holdout    %d"
             % status["internal_holdout_case_count"])
        _out(stream, "expert holdout      %d"
             % status["expert_holdout_case_count"])
        _out(stream, "validation evidence %d case(s)"
             % status["validation_evidence_case_count"])
        _out(stream, "numeric metrics     %d"
             % status["numeric_validation_metric_count"])
        _out(stream, "clinical validation %s"
             % status["clinical_validation_performed"])
        _out(stream, "expert review       %s"
             % status["expert_review_performed"])
        _out(stream, "release may proceed %s" % status["release_may_proceed"])
        _out(stream, "")
        for blocker in status["blockers"]:
            _out(stream, "  %-46s %s" % (blocker["code"], blocker["owner"]))
    return (EXIT_OK if status["benchmark_gate_status"] == "PASS"
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


def _cmd_run(args, stream) -> int:
    """Execute a benchmark. Refuses honestly when there is nothing to run.

    Everything this command needs - a release resolver, an observation port,
    a reference-judgment port - is injected in tests and absent in this
    repository. Rather than constructing empty stand-ins and producing a
    result-shaped document, it reports what is missing and exits blocked.
    """
    root = args.root or _REPO_ROOT
    status = build_wp21_gate_status(root)
    _out(stream, "benchmark run       REFUSED")
    _out(stream, "")
    _out(stream, "A run pins exactly one release and executes eligible cases "
                 "through restricted storage.")
    _out(stream, "None of those exist here, so nothing was executed and "
                 "nothing was written.")
    _out(stream, "")
    _out(stream, "  active release            %s"
         % status["active_release_available"])
    _out(stream, "  validation evidence cases %d"
         % status["validation_evidence_case_count"])
    _out(stream, "  reference judgments       %d"
         % status["reference_judgment_count"])
    _out(stream, "  restricted storage        %s"
         % status["restricted_storage_configured"])
    _out(stream, "")
    for blocker in status["blockers"]:
        _out(stream, "  %-46s %s" % (blocker["code"], blocker["owner"]))
    return EXIT_BLOCKED


def _cmd_feed(args, stream) -> int:
    root = args.root or _REPO_ROOT
    feed = build_real_feed(root)
    problems = validate_dashboard_feed(feed)
    if problems:
        for problem in problems:
            _out(stream, "SCHEMA: %s" % problem)
        return EXIT_FAILED
    _out(stream, json.dumps(feed, indent=2, sort_keys=True,
                            ensure_ascii=True))
    return _report_exit({"benchmark_executed": feed["benchmark_executed"],
                         "numeric_validation_metric_count":
                             feed["numeric_validation_metric_count"]})


_COMMANDS = {
    "definitions": _cmd_definitions,
    "report": _cmd_report,
    "gate-status": _cmd_gate_status,
    "artifacts": _cmd_artifacts,
    "run": _cmd_run,
    "feed": _cmd_feed,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pgx-benchmark",
        description="WP-21 benchmark and validation metrics. Produces no "
                    "validation result unless a release was actually "
                    "benchmarked.")
    parser.add_argument("--root", default=None,
                        help="repository root (defaults to this checkout)")
    sub = parser.add_subparsers(dest="command")
    for name in sorted(_COMMANDS):
        child = sub.add_parser(name)
        child.add_argument("--json", action="store_true",
                           help="print the machine-readable document")
        if name == "gate-status":
            child.add_argument("--write", action="store_true",
                               help="also write the committed gate status")
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
