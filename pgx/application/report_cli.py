# -*- coding: utf-8 -*-
"""``pgx-report`` - a thin, offline, read-mostly CLI for WP-15.

What it cannot do is the specification. There is no ``--enable-llm``, no
``--api-key``, no ``--skip-claim-scan``, no ``--force-overwrite``, no
``--suppress-warning``, no ``--recommend``, no ``--rank`` and no ``--dose``.
Each is refused **by name** before argument parsing, so a caller reaching for
one gets a stated refusal rather than an unrecognised-argument message that
reads like an oversight.

The default real path refuses. ``render`` requires a stored assessment and an
approved claim boundary; this repository has neither, and this module contains
nothing that changes either. ``render-synthetic`` exists so the pipeline can
be exercised, is explicit in its name, flags its output as synthetic, and
refuses to write into the production report directory.

Every command is offline. Nothing here opens a socket, reads an API key, or
imports a model SDK.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from typing import Any, List, Mapping, Optional, Sequence

from pgx.application.report_gate_status import (BLOCKER_CODES,
                                                build_report_gate_status)
from pgx.application.report_schema import (validate_canonical_assessment_result,
                                           validate_report_artifact_manifest,
                                           validate_report_fact_ledger,
                                           validate_structured_report,
                                           validate_wp15_gate_status)
from pgx.reporting.errors import REPORT_FAILURE_CODES, ReportError
from pgx.reporting.gate import gate_contract
from pgx.reporting.legacy_regression import (build_report_regression_report,
                                             legacy_report_difference_allowlist)
from pgx.reporting.llm import llm_boundary_contract
from pgx.reporting.templates import (SUPPORTED_LOCALES, TEMPLATE_VERSION,
                                     template_contract)

__all__ = ["REFUSED_FLAGS", "build_parser", "main", "refuse_unsafe_flags"]

EXIT_OK = 0
EXIT_CONFIGURATION_FAILURE = 1
EXIT_REFUSED = 2

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

REGRESSION_REPORT_RELATIVE = os.path.join(
    "data", "migration", "wp15", "report-regression-report.json")

#: Flags a caller might reach for to publish something that should not be
#: published. None exists, and each says why rather than only that.
REFUSED_FLAGS: Mapping[str, str] = {
    "--enable-llm": "no language-model provider is implemented, and the "
                    "offline document is the report rather than a fallback",
    "--gemini": "the legacy Gemini path is not reachable from the WP-15 "
                "reporting path and is not re-entered by a flag",
    "--openai": "no provider is implemented, and adding one is not a flag",
    "--api-key": "nothing in this path authenticates to anything; a key here "
                 "would be a key for a call that does not happen",
    "--skip-claim-scan": "the claim scan is the last check before "
                         "publication; skipping it is how a prohibited claim "
                         "reaches a reader (SAFETY-INV-010)",
    "--ignore-fact-loss": "a report missing a fact is a different and more "
                          "reassuring claim, not a shorter report",
    "--force-overwrite": "a published report is never silently replaced; "
                         "somebody may already have read the one on disk",
    "--suppress-warning": "the canonical clinical warning is not optional and "
                          "no caller may remove it",
    "--mark-safe": "this system states of no medication that it is safe",
    "--prefer": "this system prefers no medication (SAFETY-INV-005)",
    "--rank": "this system ranks no medication (SAFETY-INV-005)",
    "--recommend": "this system recommends no medication",
    "--dose": "this system calculates no dose and accepts none as input",
    "--diagnose": "this system does not diagnose, and a report of one of its "
                  "assessments is not a diagnosis",
    "--approve-boundary": "approval is an act by named people, not a flag",
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
        allow_abbrev=False, prog="pgx-report",
        description=("Render, validate and verify deterministic reports. "
                     "Projects stored assessment facts into a document; "
                     "calculates nothing and calls no model."))
    common = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    common.add_argument("--text", action="store_true",
                        help="Human-readable output instead of JSON.")
    common.add_argument("--repo-root", default=_REPO_ROOT)

    group = parser.add_subparsers(dest="command", required=True)

    def _sub(name, help_text):
        return group.add_parser(name, parents=[common], allow_abbrev=False,
                                help=help_text, description=help_text)

    render = _sub("render",
                  "Render a stored assessment by id. Refuses while the claim "
                  "boundary is unapproved or no assessment is stored.")
    render.add_argument("assessment_id")
    render.add_argument("--locale", default="tr", choices=SUPPORTED_LOCALES)
    render.add_argument("--out", default=None)

    synthetic = _sub("render-synthetic",
                     "Render a synthetic canonical-result document through "
                     "the whole pipeline. Explicitly synthetic; never real "
                     "evidence. Both paths are required and neither has a "
                     "default.")
    synthetic.add_argument("--from", dest="source", default=None)
    synthetic.add_argument("--locale", default="tr", choices=SUPPORTED_LOCALES)
    synthetic.add_argument("--out", default=None)

    verify = _sub("verify-artifact",
                  "Read a published artifact back and verify it against its "
                  "manifest.")
    verify.add_argument("path")

    validate = _sub("validate-report",
                    "Validate a report, canonical result, fact ledger or "
                    "manifest document against its published schema.")
    validate.add_argument("path")
    validate.add_argument("--kind", default="report",
                          choices=("report", "result", "ledger", "manifest"))

    _sub("legacy-regression",
         "Generate the legacy report comparison. Reads source and recorded "
         "observations; calls no model.").add_argument("--out", default=None)

    _sub("verify-regression",
         "Regenerate the legacy comparison and compare it with the file on "
         "disk.").add_argument("--path", default=None)

    _sub("gate-status",
         "Report whether real report publication is possible, and what "
         "blocks it.")
    _sub("template-contract",
         "Print the template contract: versions, locales and what is never "
         "localised.")
    _sub("claim-gate-contract",
         "Print the claim gate contract and the scanner's documented limits.")
    _sub("llm-boundary",
         "Print the language-model boundary contract.")
    _sub("list-failure-codes",
         "Print every report failure code and what it means.")

    # Deliberately absent: publish-real, approve-template, narrate,
    # recommend, rank, compare-medications.
    return parser


def _emit(payload: Mapping[str, Any], text: bool,
          lines: Sequence[str]) -> None:
    if text:
        sys.stdout.write("\n".join(lines) + "\n")
    else:
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True,
                                    ensure_ascii=False) + "\n")


def _read_json(path: str) -> Any:
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: str, payload: Any) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True,
                  ensure_ascii=False)
        handle.write("\n")


def _error(code: str, detail: str) -> int:
    sys.stdout.write(json.dumps(
        {"error": detail, "code": code, "refused": True},
        indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return EXIT_CONFIGURATION_FAILURE


def _refuse_real_report() -> int:
    """The default real path. There is no argument that changes this."""
    from pgx.domain.claims import DEFAULT_CLAIM_BOUNDARY
    sys.stdout.write(json.dumps({
        "refused": True,
        "code": "REPORT_CLAIM_BOUNDARY_NOT_APPROVED",
        "meaning": REPORT_FAILURE_CODES["REPORT_CLAIM_BOUNDARY_NOT_APPROVED"],
        "claim_boundary_status": DEFAULT_CLAIM_BOUNDARY.status,
        "error": (
            "the claim boundary is %r, and no assessment is stored in this "
            "repository. No report of a real assessment is produced until "
            "named humans have approved the intended purpose, and no flag in "
            "this tool sets that approval. The synthetic pipeline is "
            "exercised by render-synthetic and by the test suite."
            % DEFAULT_CLAIM_BOUNDARY.status),
    }, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return EXIT_REFUSED


def _synthetic_destination(out: Optional[str]) -> str:
    if out is None:
        raise ReportError(
            "render-synthetic writes only where it is told to. It has no "
            "default destination, because its default destination would "
            "eventually be a directory somebody reads real reports from.",
            code="REPORT_SYNTHETIC_DESTINATION_REFUSED", location="$.out")
    return out


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
        if args.command == "render":
            return _refuse_real_report()

        if args.command == "render-synthetic":
            from pgx.application.report_service import ReportService
            destination = _synthetic_destination(args.out)
            if args.source is None:
                raise ReportError(
                    "render-synthetic renders a canonical-result document "
                    "supplied with --from. It builds no assessment of its "
                    "own: a production tool that could manufacture facts "
                    "would be a second way to create them.",
                    code="REPORT_ASSESSMENT_NOT_FOUND", location="$.from")
            document = _read_json(args.source)
            produced = ReportService().regenerate_from_document(
                document, locale=args.locale)
            produced = ReportService()._write(produced,
                                              directory=destination)
            payload = produced.to_json()
            payload["synthetic_notice"] = (
                "SYNTHETIC (TEST ONLY, NOT A REAL ASSESSMENT). This document "
                "describes an invented profile against an invented ruleset "
                "and is not evidence of anything about any medicine.")
            _emit(payload, args.text,
                  ["synthetic report rendered",
                   "  locale      : %s" % produced.locale,
                   "  report hash : %s" % produced.report_hash,
                   "  output hash : %s" % produced.output_hash,
                   "  claim scan  : %s" % ("clean"
                                           if payload["claim_scan_is_clean"]
                                           else "BLOCKED"),
                   "  document    : %s" % (produced.artifact or {}).get(
                       "document_path")])
            return EXIT_OK

        if args.command == "verify-artifact":
            from pgx.reporting.artifacts import read_artifact
            record = read_artifact(args.path)
            manifest = record["manifest"]
            problems = validate_report_artifact_manifest(manifest)
            _emit({"path": args.path, "verified": not problems,
                   "issue_count": len(problems), "issues": list(problems),
                   "report_hash": manifest["report_hash"],
                   "output_hash": manifest["output_hash"],
                   "rendered_checksum": manifest["rendered_checksum"],
                   "claim_scan_is_clean":
                       bool(manifest["claim_scan"]["is_clean"])},
                  args.text,
                  ["%s: %s" % (args.path,
                               "verified" if not problems else "INVALID")]
                  + list(problems))
            return EXIT_OK if not problems else EXIT_REFUSED

        if args.command == "validate-report":
            document = _read_json(args.path)
            validator = {
                "report": validate_structured_report,
                "result": validate_canonical_assessment_result,
                "ledger": validate_report_fact_ledger,
                "manifest": validate_report_artifact_manifest,
            }[args.kind]
            problems = validator(document)
            _emit({"path": args.path, "kind": args.kind,
                   "passed": not problems, "issue_count": len(problems),
                   "issues": list(problems),
                   "note": ("schema validation only. Whether the report may "
                            "be published depends on the claim boundary, the "
                            "fact ledger and the claim scan, none of which "
                            "this command runs.")},
                  args.text,
                  ["%s: %s" % (args.path,
                               "valid" if not problems else "INVALID")]
                  + list(problems))
            return EXIT_OK if not problems else EXIT_REFUSED

        if args.command == "legacy-regression":
            report = build_report_regression_report(args.repo_root)
            destination = args.out or os.path.join(args.repo_root,
                                                   REGRESSION_REPORT_RELATIVE)
            _write_json(destination, report)
            _emit({"path": destination,
                   "case_count": report["case_count"],
                   "unexpected_difference_count":
                       report["unexpected_difference_count"],
                   "live_model_calls": report["live_model_calls"],
                   "content_hash": report["content_hash"]},
                  args.text,
                  ["wrote %s" % destination,
                   "cases            : %d" % report["case_count"],
                   "unexpected       : %d"
                   % report["unexpected_difference_count"],
                   "live model calls : %d" % report["live_model_calls"]])
            return EXIT_OK if not report["unexpected_difference_count"] \
                else EXIT_REFUSED

        if args.command == "verify-regression":
            path = args.path or os.path.join(args.repo_root,
                                             REGRESSION_REPORT_RELATIVE)
            stored = _read_json(path)
            rebuilt = build_report_regression_report(args.repo_root)
            same = stored.get("content_hash") == rebuilt["content_hash"]
            _emit({"path": path, "matches": same,
                   "stored_content_hash": stored.get("content_hash"),
                   "rebuilt_content_hash": rebuilt["content_hash"]},
                  args.text,
                  ["stored  : %s" % stored.get("content_hash"),
                   "rebuilt : %s" % rebuilt["content_hash"],
                   "matches : %s" % same])
            return EXIT_OK if same else EXIT_REFUSED

        if args.command == "gate-status":
            status = build_report_gate_status(args.repo_root).to_json()
            problems = validate_wp15_gate_status(status)
            if problems:
                return _error("SCHEMA_VIOLATION", "; ".join(problems))
            _emit(status, args.text,
                  ["real report publication is BLOCKED"]
                  + ["  %-40s %s" % (item["code"], item["detail"])
                     for item in status["blockers"]])
            return EXIT_REFUSED if status["blockers"] else EXIT_OK

        if args.command == "template-contract":
            contract = template_contract()
            _emit(contract, args.text,
                  ["template : %s" % contract["template_version"],
                   "locales  : %s"
                   % ", ".join(contract["supported_locales"])]
                  + ["never localised: %s" % item
                     for item in contract["never_localised"]])
            return EXIT_OK

        if args.command == "claim-gate-contract":
            contract = gate_contract()
            _emit(contract, args.text,
                  ["scanner: %s" % contract["scanner_version"]]
                  + ["limit: %s" % item for item in contract["limits"]])
            return EXIT_OK

        if args.command == "llm-boundary":
            contract = llm_boundary_contract()
            _emit(contract, args.text,
                  ["llm enabled          : %s" % contract["llm_enabled"],
                   "provider implemented : %s"
                   % contract["provider_implemented"],
                   "requires network     : %s" % contract["requires_network"]])
            return EXIT_OK

        if args.command == "list-failure-codes":
            _emit({"failure_codes": dict(REPORT_FAILURE_CODES),
                   "count": len(REPORT_FAILURE_CODES)},
                  args.text,
                  ["%-44s %s" % (code, REPORT_FAILURE_CODES[code])
                   for code in sorted(REPORT_FAILURE_CODES)])
            return EXIT_OK

    except FileNotFoundError as error:
        return _error("FILE_NOT_FOUND", str(error))
    except json.JSONDecodeError as error:
        return _error("INVALID_JSON", str(error))
    except KeyError as error:
        return _error("DOCUMENT_INCOMPLETE", "missing key: %s" % error)
    except ReportError as error:
        # Every ReportError is a refusal by design, so it exits 2 rather than
        # 1. Exit 1 stays for the environment failing the tool - a missing
        # file, unreadable JSON - which is a different thing for a caller to
        # do something about.
        sys.stdout.write(json.dumps(
            {"error": str(error), "code": error.code,
             "meaning": REPORT_FAILURE_CODES.get(error.code, ""),
             "location": error.location, "refused": True},
            indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        return EXIT_REFUSED

    return _error("UNKNOWN_COMMAND", "no such command: %r" % args.command)


if __name__ == "__main__":
    raise SystemExit(main())
