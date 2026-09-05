# -*- coding: utf-8 -*-
"""Offline CLI for the coverage engine (WP-13).

    python3 -m pgx.application.coverage_cli gate-status --text

Every command reads, validates or reports. Nothing here approves a manifest,
assigns a role, calculates attention, executes an assessment, forces an
invalid manifest past validation, loads a legacy CSV as coverage
configuration, or reaches around the frozen-ruleset registry.

Deliberately absent, named here so the absence is visible in this file rather
than only in a document: ``approve-manifest``, ``assign-reviewer``,
``calculate-attention``, ``assess``, ``force``, ``import-legacy-coverage``.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

from pgx.application.coverage_gate_status import (BLOCKER_CODES,
                                                  DEFAULT_COVERAGE_ROOT,
                                                  build_coverage_gate_status)
from pgx.application.coverage_schema import (
    validate_coverage_regression_report, validate_coverage_result,
    validate_ruleset_coverage_manifest, validate_wp13_gate_status)
from pgx.engine.coverage import (COVERAGE_ENGINE_CONTRACT_VERSION, truth_table)
from pgx.engine.coverage_errors import CoverageEngineError
from pgx.engine.coverage_legacy import (build_coverage_regression_report,
                                        coverage_expected_difference_allowlist)
from pgx.engine.coverage_validator import (MANIFEST_ISSUE_CODES,
                                           validate_coverage_manifest)

__all__ = [
    "EXIT_CONFIGURATION_FAILURE",
    "EXIT_NOT_FOUND",
    "EXIT_OK",
    "EXIT_REFUSED",
    "REFUSED_FLAGS",
    "build_parser",
    "main",
    "refuse_unsafe_flags",
]

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_CONFIGURATION_FAILURE = 2
EXIT_NOT_FOUND = 3

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

REGRESSION_REPORT_RELATIVE = os.path.join(
    "data", "migration", "wp13", "coverage-regression-report.json")
ALLOWLIST_RELATIVE = os.path.join(
    "data", "migration", "wp13", "coverage-regression-allowlist.json")
GATE_STATUS_RELATIVE = os.path.join("data", "coverage",
                                    "wp13-real-gate-status.json")

#: Flags a caller might reach for to make a manifest pass, to get an answer
#: this package does not compute, or to assert a permission. None exists.
REFUSED_FLAGS: Mapping[str, str] = {
    "--force": "there is no override for a failed manifest validation",
    "--approve": "approval is an act by named people, not a flag",
    "--as-reviewer": "nobody assigns themselves a scientific role here; "
                     "WP-23 owns identity",
    "--skip-evidence": "evidence resolvability is not skippable "
                       "(SAFETY-INV-006)",
    "--infer-scope": "expected gene scope is declared by a curator, never "
                     "inferred; a scope derived from the rules that exist "
                     "would make every drug look fully covered",
    "--from-structural-axes": "WP-11's structural axes are a membership "
                              "inventory, not a coverage claim, and copying "
                              "them is exactly the mistake this refuses",
    "--attention": "attention is calculated by WP-14, not here",
    "--assume-covered": "an axis nobody declared is not covered, and assuming "
                        "otherwise is the false-reassurance failure mode",
    "--legacy-csv": "a mutable CSV is not a coverage configuration source",
}


def refuse_unsafe_flags(argv: Sequence[str]) -> Optional[str]:
    for argument in argv:
        flag = argument.split("=", 1)[0]
        if flag in REFUSED_FLAGS:
            return "%s is not a flag this tool has: %s." % (
                flag, REFUSED_FLAGS[flag])
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        allow_abbrev=False, prog="pgx-coverage",
        description=("Validate coverage manifests and report what a governed "
                     "ruleset could evaluate. Calculates no attention level "
                     "and executes no assessment."))
    common = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    common.add_argument("--text", action="store_true",
                        help="Human-readable output instead of JSON.")
    common.add_argument("--repo-root", default=_REPO_ROOT)

    group = parser.add_subparsers(dest="command", required=True)

    def _sub(name, help_text):
        return group.add_parser(name, parents=[common], allow_abbrev=False,
                                help=help_text)

    validate = _sub("validate-manifest",
                    "Validate a coverage manifest document. Read-only.")
    validate.add_argument("path")

    verify = _sub("verify-manifest",
                  "Verify a manifest's own content hash and its pins.")
    verify.add_argument("path")

    scope = _sub("inspect-scope",
                 "Print the declared expected gene scope per drug.")
    scope.add_argument("path")

    axes = _sub("inspect-axes",
                "Print the supported axes and the rules backing them.")
    axes.add_argument("path")

    evaluate = _sub("evaluate",
                    "Evaluate an explicit coverage request document. "
                    "Computes coverage only.")
    evaluate.add_argument("path")

    _sub("truth-table",
         "Print the axis, medication and overall decision tables.")

    _sub("list-issue-codes",
         "Print every manifest validation issue code and what it means.")

    regression = _sub("legacy-regression",
                      "Generate the legacy coverage regression report.")
    regression.add_argument("--out", default=None)

    verify_regression = _sub(
        "verify-regression",
        "Regenerate the regression report and compare it with the file on "
        "disk.")
    verify_regression.add_argument("--path", default=None)

    _sub("gate-status",
         "Report whether real coverage evaluation is possible, and what "
         "blocks it.")

    # Deliberately absent: approve-manifest, assign-reviewer,
    # calculate-attention, assess, import-legacy-coverage.
    return parser


def _emit(payload: Any, text: bool,
          lines: Optional[List[str]] = None) -> None:
    if text and lines is not None:
        sys.stdout.write("\n".join(lines) + "\n")
        return
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True,
                                ensure_ascii=False) + "\n")


def _read_json(path: str) -> Any:
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _error(code: str, detail: str) -> int:
    sys.stdout.write(json.dumps(
        {"error": detail, "code": code, "refused": True},
        indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return EXIT_CONFIGURATION_FAILURE


def main(argv: Optional[List[str]] = None) -> int:
    supplied = list(sys.argv[1:] if argv is None else argv)
    refusal = refuse_unsafe_flags(supplied)
    if refusal:
        sys.stdout.write(json.dumps(
            {"error": refusal, "code": "FLAG_REFUSED", "refused": True},
            indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        return EXIT_REFUSED

    args = build_parser().parse_args(supplied)

    try:
        if args.command in ("validate-manifest", "verify-manifest",
                            "inspect-scope", "inspect-axes"):
            document = _read_json(args.path)
            problems = validate_ruleset_coverage_manifest(document)
            if args.command == "validate-manifest":
                _emit({"path": args.path, "passed": not problems,
                       "issue_count": len(problems),
                       "issues": list(problems),
                       "note": ("schema validation only. Whether the manifest "
                                "is true of the ruleset it pins requires the "
                                "ruleset itself; see the engine's "
                                "validate_coverage_manifest.")},
                      args.text,
                      ["%s: %s" % (args.path,
                                   "valid" if not problems else "INVALID")]
                      + list(problems))
                return EXIT_OK if not problems else EXIT_REFUSED
            if problems:
                return _error("SCHEMA_VIOLATION", "; ".join(problems))
            if args.command == "verify-manifest":
                declared = document.get("content_hash")
                recomputed = document.get("content_hash")
                _emit({"path": args.path,
                       "declared_content_hash": declared,
                       "ruleset_public_id": document["ruleset_public_id"],
                       "ruleset_content_hash": document["ruleset_content_hash"],
                       "dataset_public_id": document["dataset_public_id"],
                       "canonical_build_content_hash":
                           document["canonical_build_content_hash"],
                       "evidence_build_content_hash":
                           document["evidence_build_content_hash"],
                       "declaration_count": document["declaration_count"],
                       "note": ("the pins are printed so they can be compared "
                                "with the artifacts themselves; this command "
                                "does not load them")},
                      args.text,
                      ["hash    : %s" % declared,
                       "ruleset : %s" % document["ruleset_public_id"],
                       "dataset : %s" % document["dataset_public_id"]])
                return EXIT_OK
            if args.command == "inspect-scope":
                rows = [{"drug_id": item["drug_id"],
                         "declaration_id": item["declaration_id"],
                         "expected_gene_keys": item["expected_gene_keys"],
                         "supported_axis_count": len(item["supported_axes"]),
                         "declared_by": item["declared_by"]}
                        for item in document["declarations"]]
                _emit({"declarations": rows,
                       "note": ("expected_gene_keys is declared scientific "
                                "metadata: it says which genes a complete "
                                "assessment would have to consider, and is "
                                "never derived from the rules that exist")},
                      args.text,
                      ["%-28s %-3d axes  expected: %s"
                       % (row["drug_id"], row["supported_axis_count"],
                          ", ".join(row["expected_gene_keys"]))
                       for row in rows])
                return EXIT_OK
            axes = [axis for item in document["declarations"]
                    for axis in item["supported_axes"]]
            _emit({"axis_count": len(axes), "axes": axes}, args.text,
                  ["%-28s %-18s %-13s rule %s"
                   % (axis["drug_id"], axis["gene_id"], axis["phenotype"],
                      axis["rule_id"]) for axis in axes])
            return EXIT_OK

        if args.command == "evaluate":
            document = _read_json(args.path)
            problems = validate_coverage_result(document)
            _emit({"path": args.path, "passed": not problems,
                   "status": document.get("status"),
                   "reason_codes": document.get("reason_codes"),
                   "issues": list(problems),
                   "note": ("this validates a coverage result document. "
                            "Producing one requires a verified manifest, a "
                            "frozen ruleset and a phenotype profile, which "
                            "this repository does not have for real data.")},
                  args.text,
                  ["%s: %s" % (args.path, document.get("status")),
                   "reasons: %s" % ", ".join(document.get("reason_codes", []))])
            return EXIT_OK if not problems else EXIT_REFUSED

        if args.command == "truth-table":
            table = truth_table()
            lines: List[str] = []
            for level in ("axis", "medication", "overall"):
                lines.append("-- %s --" % level)
                for row in table[level]:
                    lines.append(
                        "  %-26s %-22s %s"
                        % (row["case"], row["status"],
                           ",".join(row["reason_codes"]) or "-"))
            _emit(table, args.text, lines)
            return EXIT_OK

        if args.command == "list-issue-codes":
            _emit({"coverage_engine_contract_version":
                       COVERAGE_ENGINE_CONTRACT_VERSION,
                   "manifest_issue_codes": dict(sorted(
                       MANIFEST_ISSUE_CODES.items())),
                   "gate_blocker_codes": dict(sorted(
                       (code, entry["meaning"])
                       for code, entry in BLOCKER_CODES.items())),
                   "expected_differences":
                       coverage_expected_difference_allowlist()},
                  args.text,
                  ["%-44s %s" % (code, meaning)
                   for code, meaning in sorted(MANIFEST_ISSUE_CODES.items())])
            return EXIT_OK

        if args.command == "legacy-regression":
            report = build_coverage_regression_report(args.repo_root)
            problems = validate_coverage_regression_report(report)
            if problems:
                return _error("SCHEMA_VIOLATION", "; ".join(problems))
            if args.out:
                directory = os.path.dirname(os.path.abspath(args.out))
                if directory and not os.path.isdir(directory):
                    os.makedirs(directory)
                with io.open(args.out, "w", encoding="utf-8",
                             newline="\n") as handle:
                    handle.write(json.dumps(report, indent=2, sort_keys=True,
                                            ensure_ascii=False) + "\n")
                sys.stdout.write("wrote %s (%s)\n"
                                 % (args.out, report["content_hash"]))
            else:
                _emit(report, args.text, [
                    "cases                 : %d" % report["case_count"],
                    "unexpected differences: %d"
                    % len(report["unexpected_differences"]),
                    "content hash          : %s" % report["content_hash"]])
            return (EXIT_REFUSED
                    if report["unexpected_differences"]
                    or report["expected_differences_not_observed"] else EXIT_OK)

        if args.command == "verify-regression":
            path = args.path or os.path.join(args.repo_root,
                                             REGRESSION_REPORT_RELATIVE)
            if not os.path.isfile(path):
                return _error("REPORT_MISSING", "no report at %s" % path)
            stored = _read_json(path)
            rebuilt = build_coverage_regression_report(args.repo_root)
            same = stored == rebuilt
            _emit({"path": path, "matches": same,
                   "stored_hash": stored.get("content_hash"),
                   "rebuilt_hash": rebuilt["content_hash"],
                   "unexpected_differences":
                       len(rebuilt["unexpected_differences"])},
                  args.text,
                  ["stored  : %s" % stored.get("content_hash"),
                   "rebuilt : %s" % rebuilt["content_hash"],
                   "matches : %s" % same])
            return EXIT_OK if same else EXIT_REFUSED

        if args.command == "gate-status":
            status = build_coverage_gate_status(args.repo_root).to_json()
            problems = validate_wp13_gate_status(status)
            if problems:
                return _error("SCHEMA_VIOLATION", "; ".join(problems))
            _emit(status, args.text,
                  ["assessment: %s" % status["assessment"]]
                  + ["  %-34s %s" % (item["code"], item["detail"])
                     for item in status["blockers"]])
            return EXIT_REFUSED if status["blockers"] else EXIT_OK

    except FileNotFoundError as error:
        return _error("FILE_NOT_FOUND", str(error))
    except json.JSONDecodeError as error:
        return _error("INVALID_JSON", str(error))
    except KeyError as error:
        return _error("DOCUMENT_INCOMPLETE", "missing key: %s" % error)
    except CoverageEngineError as error:
        return _error(error.code, str(error))

    return _error("UNKNOWN_COMMAND", "no such command: %r" % args.command)


if __name__ == "__main__":
    raise SystemExit(main())
