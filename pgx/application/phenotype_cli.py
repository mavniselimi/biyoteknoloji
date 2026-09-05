# -*- coding: utf-8 -*-
"""Offline CLI for the phenotype engine (WP-12).

    python3 -m pgx.application.phenotype_cli truth-matrix --text

Every command is a pure function of its input. Nothing here reaches a network,
a clock, a database or a model; nothing loads a rule that is not already a
verified frozen artifact; and nothing produces an attention level, a coverage
status or an assessment, because this package computes none of those.

Deliberately absent, named here so the absence is visible in this file rather
than only in a document: ``assess``, ``calculate-attention``,
``calculate-coverage``, ``infer-phenotype``, ``normalize-genotype`` and every
flag that would let a caller widen a match.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

from pgx.application.phenotype_schema import (
    validate_phenotype_match_result, validate_phenotype_profile,
    validate_phenotype_regression_report)
from pgx.domain.enums import Phenotype
from pgx.engine.phenotype import (MATCHER_CONTRACT_VERSION, match_observation,
                                  truth_matrix)
from pgx.engine.phenotype_errors import PhenotypeEngineError
from pgx.engine.phenotype_legacy import (build_regression_report,
                                         expected_difference_allowlist)
from pgx.engine.phenotype_models import NORMALIZATION_REASON_CODES
from pgx.engine.phenotype_normalization import (INPUT_CONTRACT_VERSION,
                                                normalize_phenotype,
                                                normalize_profile)
from pgx.rules.conditions import PhenotypeMatch
from pgx.rules.errors import ConditionGrammarError

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
    "data", "migration", "wp12", "phenotype-regression-report.json")
ALLOWLIST_RELATIVE = os.path.join(
    "data", "migration", "wp12", "phenotype-regression-allowlist.json")

#: Flags a caller might reach for to loosen matching or to get an answer this
#: package does not compute. None exists, and each is refused by name so the
#: message explains why rather than leaving argparse to say "unrecognized
#: arguments" about a flag whose absence is the whole point.
REFUSED_FLAGS: Mapping[str, str] = {
    "--fuzzy": "there is no fuzzy matching; a value is a canonical token or "
               "it is unsupported",
    "--nearest": "there is no nearest phenotype; proximity is not equality",
    "--synonyms": "the v1 input contract has no synonym vocabulary, and one "
                  "would be a scientific claim rather than a flag",
    "--infer-from-genotype": "phenotype is not inferred from genotype, "
                             "diplotype or star alleles here or anywhere",
    "--assume-normal": "an uninterpretable value is never assumed normal; "
                       "that is the false-reassurance failure mode",
    "--expand-groups": "broad functional groups are not expanded into POOR or "
                       "INTERMEDIATE",
    "--attention": "attention is calculated by WP-14, not here",
    "--coverage": "coverage is calculated by WP-13, not here",
}


def refuse_unsafe_flags(argv: Sequence[str]) -> Optional[str]:
    for argument in argv:
        flag = argument.split("=", 1)[0]
        if flag in REFUSED_FLAGS:
            return "%s is not a flag this tool has: %s." % (
                flag, REFUSED_FLAGS[flag])
    return None


def build_parser() -> argparse.ArgumentParser:
    # allow_abbrev=False for the reason the WP-11 CLI gives: with argparse's
    # default prefix matching a refused flag could be absorbed as an
    # abbreviation of a longer one and silently accepted.
    parser = argparse.ArgumentParser(
        allow_abbrev=False, prog="pgx-phenotype",
        description=("Normalise phenotype input and compare it, exactly, with "
                     "a validated rule condition. Calculates no attention, no "
                     "coverage and no assessment."))
    common = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    common.add_argument("--text", action="store_true",
                        help="Human-readable output instead of JSON.")
    common.add_argument("--repo-root", default=_REPO_ROOT)

    group = parser.add_subparsers(dest="command", required=True)

    def _sub(name, help_text):
        return group.add_parser(name, parents=[common], allow_abbrev=False,
                                help=help_text)

    token = _sub("normalize-token",
                 "Normalise one phenotype token. Read-only.")
    token.add_argument("value")
    token.add_argument("--gene", default="CYP2D6")

    profile = _sub("normalize-profile",
                   "Normalise a phenotype profile JSON document.")
    profile.add_argument("path")
    profile.add_argument("--profile-id", default=None)
    profile.add_argument("--require-known-genes", action="store_true",
                         help="Validate genes against --gene-catalogue. Fails "
                              "closed if the catalogue is empty.")
    profile.add_argument("--gene-catalogue", default=None,
                         help="Path to a JSON list of canonical gene keys.")

    compare = _sub("compare",
                   "Compare one phenotype value with an EXACT/ONE_OF "
                   "condition. Evaluates phenotype equality only.")
    compare.add_argument("value")
    compare.add_argument("--operator", choices=("EXACT", "ONE_OF"),
                         default="EXACT")
    compare.add_argument("--declared", nargs="+", required=True,
                         help="The phenotypes the condition lists.")
    compare.add_argument("--gene", default="CYP2D6")

    _sub("truth-matrix",
         "Print the exact-match truth matrix: every input phenotype against "
         "every EXACT rule phenotype.")

    regression = _sub("legacy-regression",
                      "Generate the legacy P1-P6 phenotype regression report.")
    regression.add_argument("--out", default=None,
                            help="Write the report here instead of printing.")

    verify = _sub("verify-regression",
                  "Regenerate the report and compare it with the file on disk.")
    verify.add_argument("--path", default=None)

    _sub("list-reason-codes",
         "Print every normalisation reason code and what it means.")

    # Deliberately absent: assess, calculate-attention, calculate-coverage,
    # infer-phenotype, normalize-genotype, apply-ruleset.
    return parser


def _emit(payload: Any, text: bool, lines: Optional[List[str]] = None) -> None:
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

    parser = build_parser()
    args = parser.parse_args(supplied)

    try:
        if args.command == "normalize-token":
            from pgx.engine.phenotype_normalization import normalize_gene_key
            gene = normalize_gene_key(args.gene)
            observation = normalize_phenotype(args.value,
                                              gene_canonical_key=gene)
            _emit(observation.to_json(), args.text, [
                "%s %s" % (gene, observation.status),
                "  phenotype : %s" % (observation.phenotype.value
                                      if observation.phenotype else "-"),
                "  reason    : %s" % (observation.reason_code or "-")])
            return EXIT_OK if observation.is_normalized else EXIT_REFUSED

        if args.command == "normalize-profile":
            document = _read_json(args.path)
            phenotypes = document.get("phenotypes", document)
            catalogue = None
            if args.gene_catalogue:
                catalogue = _read_json(args.gene_catalogue)
            profile = normalize_profile(
                phenotypes, profile_id=args.profile_id,
                known_gene_keys=catalogue,
                require_known_genes=args.require_known_genes)
            payload = profile.to_json()
            problems = validate_phenotype_profile(payload)
            if problems:
                return _error("SCHEMA_VIOLATION", "; ".join(problems))
            _emit(payload, args.text, [
                "profile %s (%s)" % (profile.profile_id or "-",
                                     profile.content_hash()[:23])] + [
                "  %-16s %-13s %s" % (item.gene_canonical_key, item.status,
                                      item.phenotype.value
                                      if item.phenotype else
                                      (item.reason_code or "-"))
                for item in profile.observations])
            unresolved = [item for item in profile.observations
                          if not item.is_normalized]
            return EXIT_REFUSED if unresolved else EXIT_OK

        if args.command == "compare":
            from pgx.engine.phenotype_normalization import normalize_gene_key
            gene = normalize_gene_key(args.gene)
            try:
                declared = tuple(Phenotype(value.strip().upper())
                                 for value in args.declared)
            except ValueError as error:
                return _error("PHENOTYPE_UNKNOWN", str(error))
            condition = PhenotypeMatch(operator=args.operator,
                                       values=declared)
            observation = normalize_phenotype(args.value,
                                              gene_canonical_key=gene)
            decision = match_observation(observation, condition)
            payload = decision.to_json()
            problems = validate_phenotype_match_result(payload)
            if problems:
                return _error("SCHEMA_VIOLATION", "; ".join(problems))
            _emit(payload, args.text, [
                "%s %s{%s}" % (gene, args.operator,
                               ",".join(item.value for item in declared)),
                "  observed : %s (%s)" % (
                    decision.observed_phenotype.value
                    if decision.observed_phenotype else "-",
                    decision.observation_status),
                "  status   : %s" % decision.status])
            return EXIT_OK if decision.matched else EXIT_REFUSED

        if args.command == "truth-matrix":
            rows = truth_matrix()
            payload = {"matcher_contract_version": MATCHER_CONTRACT_VERSION,
                       "input_contract_version": INPUT_CONTRACT_VERSION,
                       "row_count": len(rows), "rows": list(rows),
                       "note": ("Equality and nothing else. Every row whose "
                                "observed value differs from its declared "
                                "value is NO_MATCH, and INDETERMINATE matches "
                                "nothing at all.")}
            _emit(payload, args.text,
                  ["%-14s %-8s %-14s %s" % (row["observed"], row["operator"],
                                            ",".join(row["declared"]),
                                            row["expected_status"])
                   for row in rows])
            return EXIT_OK

        if args.command == "legacy-regression":
            report = build_regression_report(args.repo_root)
            problems = validate_phenotype_regression_report(report)
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
                    "profiles              : %d" % report["profile_count"],
                    "unexpected differences: %d"
                    % len(report["unexpected_differences"]),
                    "content hash          : %s" % report["content_hash"]])
            return (EXIT_REFUSED if report["unexpected_differences"]
                    or report["expected_differences_not_observed"] else EXIT_OK)

        if args.command == "verify-regression":
            path = args.path or os.path.join(args.repo_root,
                                             REGRESSION_REPORT_RELATIVE)
            if not os.path.isfile(path):
                return _error("REPORT_MISSING", "no report at %s" % path)
            stored = _read_json(path)
            rebuilt = build_regression_report(args.repo_root)
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

        if args.command == "list-reason-codes":
            payload = {
                "input_contract_version": INPUT_CONTRACT_VERSION,
                "reason_codes": dict(sorted(NORMALIZATION_REASON_CODES.items())),
                "expected_differences": expected_difference_allowlist(),
            }
            _emit(payload, args.text,
                  ["%-42s %s" % (code, meaning)
                   for code, meaning in sorted(
                       NORMALIZATION_REASON_CODES.items())])
            return EXIT_OK

    except FileNotFoundError as error:
        return _error("FILE_NOT_FOUND", str(error))
    except json.JSONDecodeError as error:
        return _error("INVALID_JSON", str(error))
    except ConditionGrammarError as error:
        return _error(error.code, str(error))
    except PhenotypeEngineError as error:
        return _error(error.code, str(error))

    return _error("UNKNOWN_COMMAND", "no such command: %r" % args.command)


if __name__ == "__main__":
    raise SystemExit(main())
