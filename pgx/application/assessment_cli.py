# -*- coding: utf-8 -*-
"""``pgx-assess`` - a thin, offline, read-mostly CLI for WP-14.

What it cannot do is the specification. There is no ``--force-release``, no
``--bypass-approval``, no ``--allow-draft-rule``, no ``--ignore-coverage``, no
``--ignore-evidence``, no ``--assume-normal``, no clinical or patient mode and
no dose or recommendation flag. Each is refused **by name** before argument
parsing, so a caller reaching for one gets a stated refusal rather than an
unrecognised-argument message that reads like an oversight.

The default real path refuses. ``execute`` and ``dry-run`` require a synthetic
world that only the tests construct: the claim boundary shipped in this
repository is DRAFT, and this module contains nothing that changes it.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from typing import Any, List, Mapping, Optional, Sequence

from pgx.application.assessment_gate_status import (
    BLOCKER_CODES, build_assessment_gate_status)
from pgx.application.assessment_schema import (
    validate_assessment_computation, validate_assessment_input,
    validate_assessment_regression_report, validate_wp14_gate_status)
from pgx.engine.risk import ASSESSMENT_ENGINE_CONTRACT_VERSION, engine_contract
from pgx.engine.risk_errors import FAILURE_CODES, AssessmentEngineError
from pgx.engine.risk_legacy import (assessment_expected_difference_allowlist,
                                    build_assessment_regression_report)
from pgx.engine.risk_models import attention_table

__all__ = ["REFUSED_FLAGS", "build_parser", "main", "refuse_unsafe_flags"]

EXIT_OK = 0
EXIT_CONFIGURATION_FAILURE = 1
EXIT_REFUSED = 2

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

REGRESSION_REPORT_RELATIVE = os.path.join(
    "data", "migration", "wp14", "assessment-regression-report.json")
GATE_STATUS_RELATIVE = os.path.join("data", "assessments",
                                    "wp14-real-gate-status.json")

#: Flags a caller might reach for to make an assessment run that should not.
#: None exists, and each says why rather than only that.
REFUSED_FLAGS: Mapping[str, str] = {
    "--force-release": "a release is pinned because it is ACTIVE and verifies, "
                       "never because a flag said so",
    "--bypass-approval": "approval is an act by named people, not a flag",
    "--allow-draft-rule": "only VALIDATED member rules of a FROZEN ruleset "
                          "execute (SAFETY-INV-003)",
    "--ignore-coverage": "coverage is what decides whether an axis may produce "
                         "a finding; ignoring it is how absence becomes a "
                         "result",
    "--ignore-evidence": "a finding without resolvable evidence is not a "
                         "finding (SAFETY-INV-006)",
    "--assume-normal": "assuming an unsupplied phenotype is NORMAL is false "
                       "reassurance in its purest form (SAFETY-INV-001)",
    "--clinical-mode": "this product is not for clinical use and has no "
                       "clinical mode",
    "--patient-mode": "there is no patient-facing mode; the intended purpose "
                      "names expert users",
    "--dose": "this system calculates no dose",
    "--recommend": "this system recommends no medication",
    "--rank": "this system ranks no medication (SAFETY-INV-005)",
    "--as-approver": "nobody assigns themselves a scientific role here; "
                     "WP-23 owns identity",
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
        allow_abbrev=False, prog="pgx-assess",
        description=("Validate assessment documents and report what the "
                     "assessment gate permits. Calculates structured facts "
                     "only; renders no report prose."))
    common = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    common.add_argument("--text", action="store_true",
                        help="Human-readable output instead of JSON.")
    common.add_argument("--repo-root", default=_REPO_ROOT)

    group = parser.add_subparsers(dest="command", required=True)

    def _sub(name, help_text):
        return group.add_parser(name, parents=[common], allow_abbrev=False,
                                help=help_text)

    validate = _sub("validate-input",
                    "Validate an assessment input document. Read-only.")
    validate.add_argument("path")

    verify = _sub("verify-hashes",
                  "Recompute the input and output hashes of a stored "
                  "computation and compare them with the document.")
    verify.add_argument("path")

    retrieve = _sub("show-assessment",
                    "Validate and print a stored assessment computation.")
    retrieve.add_argument("path")

    _sub("gate-status",
         "Report whether real assessment execution is possible, and what "
         "blocks it.")
    _sub("attention-table",
         "Print the attention aggregation table and the engine contract.")
    _sub("list-failure-codes",
         "Print every assessment failure code and what it means.")

    regression = _sub("legacy-regression",
                      "Generate the legacy comparison report.")
    regression.add_argument("--out", default=None)

    verify_regression = _sub(
        "verify-regression",
        "Regenerate the comparison and compare it with the file on disk.")
    verify_regression.add_argument("--path", default=None)

    dry_run = _sub("dry-run",
                   "Calculate an assessment from an explicit document without "
                   "persisting anything. Refuses while the claim boundary is "
                   "unapproved.")
    dry_run.add_argument("path")

    execute = _sub("execute",
                   "Execute an assessment through the service. Refuses while "
                   "the claim boundary is unapproved.")
    execute.add_argument("path")

    # Deliberately absent: approve-boundary, activate-release, seed-assessment,
    # render-report, recommend, rank.
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


def _refuse_execution() -> int:
    """The default real path. There is no argument that changes this."""
    from pgx.domain.claims import DEFAULT_CLAIM_BOUNDARY
    sys.stdout.write(json.dumps({
        "refused": True,
        "code": "ASSESSMENT_CLAIM_BOUNDARY_NOT_APPROVED",
        "meaning": FAILURE_CODES["ASSESSMENT_CLAIM_BOUNDARY_NOT_APPROVED"],
        "claim_boundary_status": DEFAULT_CLAIM_BOUNDARY.status,
        "error": (
            "the claim boundary is %r. No assessment executes until named "
            "humans have approved the intended purpose, and no flag in this "
            "tool sets that approval. Synthetic execution is exercised by the "
            "test suite against an explicitly synthetic boundary."
            % DEFAULT_CLAIM_BOUNDARY.status),
    }, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return EXIT_REFUSED


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
        if args.command in ("dry-run", "execute"):
            return _refuse_execution()

        if args.command == "validate-input":
            document = _read_json(args.path)
            problems = validate_assessment_input(document)
            _emit({"path": args.path, "passed": not problems,
                   "issue_count": len(problems), "issues": list(problems),
                   "note": ("schema validation only. Whether the input may "
                            "execute depends on the claim boundary, the mode "
                            "and the pinned release, none of which this "
                            "command reads.")},
                  args.text,
                  ["%s: %s" % (args.path,
                               "valid" if not problems else "INVALID")]
                  + list(problems))
            return EXIT_OK if not problems else EXIT_REFUSED

        if args.command in ("show-assessment", "verify-hashes"):
            document = _read_json(args.path)
            problems = validate_assessment_computation(document)
            if problems:
                return _error("SCHEMA_VIOLATION", "; ".join(problems))
            if args.command == "show-assessment":
                _emit(document, args.text, [
                    "overall coverage : %s" % document["overall_coverage"],
                    "overall attention: %s" % document["overall_attention"],
                    "medications      : %d" % document["medication_count"],
                    "findings         : %d" % document["finding_count"],
                    "output hash      : %s" % document["output_hash"]])
                return EXIT_OK
            from pgx.domain.hashing import sha256_digest
            from pgx.engine.risk import hashed_projection
            recomputed = sha256_digest(hashed_projection(document))
            matches = recomputed == document["output_hash"]
            _emit({"path": args.path, "matches": matches,
                   "declared_output_hash": document["output_hash"],
                   "recomputed_output_hash": recomputed,
                   "input_hash": document["input_hash"],
                   "note": ("the output hash covers the calculated facts and "
                            "the pinned versions, and excludes the assessment "
                            "id, the actor, the clock and any rendered text")},
                  args.text,
                  ["declared  : %s" % document["output_hash"],
                   "recomputed: %s" % recomputed,
                   "matches   : %s" % matches])
            return EXIT_OK if matches else EXIT_REFUSED

        if args.command == "attention-table":
            payload = {"assessment_engine_contract_version":
                       ASSESSMENT_ENGINE_CONTRACT_VERSION,
                       "attention": attention_table(),
                       "engine_contract": engine_contract()}
            lines = ["precedence: %s"
                     % ", ".join(payload["attention"]["precedence"]),
                     "excluded  : %s"
                     % ", ".join(payload["attention"]["excluded_from_maximum"]),
                     ""]
            for row in payload["attention"]["rows"]:
                lines.append("  %-34s %-22s -> %s"
                             % (row["case"], row["coverage"], row["result"]))
            _emit(payload, args.text, lines)
            return EXIT_OK

        if args.command == "list-failure-codes":
            _emit({"failure_codes": dict(sorted(FAILURE_CODES.items())),
                   "gate_blocker_codes": dict(sorted(
                       (code, entry["meaning"])
                       for code, entry in BLOCKER_CODES.items())),
                   "refused_flags": dict(sorted(REFUSED_FLAGS.items())),
                   "expected_differences":
                       assessment_expected_difference_allowlist()},
                  args.text,
                  ["%-46s %s" % (code, meaning)
                   for code, meaning in sorted(FAILURE_CODES.items())])
            return EXIT_OK

        if args.command == "legacy-regression":
            report = build_assessment_regression_report(args.repo_root)
            problems = validate_assessment_regression_report(report)
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
            rebuilt = build_assessment_regression_report(args.repo_root)
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
            status = build_assessment_gate_status(args.repo_root).to_json()
            problems = validate_wp14_gate_status(status)
            if problems:
                return _error("SCHEMA_VIOLATION", "; ".join(problems))
            _emit(status, args.text,
                  ["assessment: %s" % status["assessment"]]
                  + ["  %-46s %s" % (item["code"], item["detail"])
                     for item in status["blockers"]])
            return EXIT_REFUSED if status["blockers"] else EXIT_OK

    except FileNotFoundError as error:
        return _error("FILE_NOT_FOUND", str(error))
    except json.JSONDecodeError as error:
        return _error("INVALID_JSON", str(error))
    except KeyError as error:
        return _error("DOCUMENT_INCOMPLETE", "missing key: %s" % error)
    except AssessmentEngineError as error:
        return _error(error.code, str(error))

    return _error("UNKNOWN_COMMAND", "no such command: %r" % args.command)


if __name__ == "__main__":
    raise SystemExit(main())
