# -*- coding: utf-8 -*-
"""``pgx-evidence`` - build, verify and trace evidence stores (WP-08).

Console entry point: ``pgx-evidence``. ``scripts/evidence.py`` is a thin
wrapper that delegates here, so the logic exists once and the installed
package owns it.

Rules this CLI follows, each for a reason:

* **No network.** Nothing here fetches anything. An evidence build is derived
  from a sealed raw snapshot and a sealed canonical build that already exist
  on disk. There is no ``--fetch``, no ``--enrich`` and no PubMed lookup: a
  publication this project cannot identify from the bytes it was given stays
  unidentified and says so.
* **Explicit dataset identity.** ``--dataset-id`` is required and is checked
  against what the inputs actually declare. A run that was pointed at the
  wrong snapshot fails rather than producing a correct-looking build of the
  wrong dataset.
* **Explicit input paths.** ``--snapshot`` and ``--canonical-build`` are both
  required. Neither is discovered, guessed, or defaulted to "the latest".
* **Explicit identity allocation.** ``build`` mints UUIDs only when
  ``--allocate-new-identities`` is passed. Reproducing an earlier build means
  passing ``--allocation`` and no allocation flag, so a run that expected to
  reproduce and instead invented identities fails rather than succeeding
  quietly.
* **No implicit overwrite, and no ``--force``.** There is no flag that
  rewrites a sealed build. Two builds of one dataset go to two output roots
  and are compared with ``compare-builds``.
* **No promotion of any kind.** There is no ``approve``, no ``publish``, no
  ``activate``, no ``curate``, no ``approve-curation``, no ``generate-rules``,
  no source-policy approval and no dataset lifecycle transition. The dataset
  stays ``BUILDING``, and nothing in this package can change that.
  ``extract-draft-curation`` produces unreviewed migration candidates outside
  the evidence store; it creates no ``CuratedInterpretation`` and names no
  reviewer, because a command-line flag cannot supply a person who looked.

Exit codes:

===  =========================================================
0    success
1    the build was refused, verification found a problem, or a
     lookup found corruption
2    configuration failure - bad path, unreadable input, an
     argument that contradicts the inputs
3    the named snapshot, build or record does not exist
===  =========================================================
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

from pgx.application.evidence_schema import (validate_draft_curation_proposal,
                                             validate_evidence_build_manifest,
                                             validate_evidence_record)
from pgx.evidence.build import (EVIDENCE_BUILD_FILES, EvidenceBuildRequest,
                                ImportMode, build_evidence,
                                compare_evidence_builds, read_evidence_manifest,
                                verify_evidence_build, write_evidence_build)
from pgx.evidence.detail import (ArtifactEvidenceDetailRepository,
                                 DuplicateNaturalKeyError)
from pgx.evidence.draft_curation import extract_draft_curation
from pgx.evidence.errors import (EvidenceBuildError, EvidenceError,
                                 EvidenceGateError)
from pgx.evidence.models import EvidenceRecordType

__all__ = [
    "DEFAULT_CANONICAL_ROOT",
    "DEFAULT_EVIDENCE_ROOT",
    "DEFAULT_RAW_ROOT",
    "EXIT_CONFIGURATION_FAILURE",
    "EXIT_NOT_FOUND",
    "EXIT_OK",
    "EXIT_REFUSED",
    "ROW_FILES",
    "build_parser",
    "main",
]

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_CONFIGURATION_FAILURE = 2
EXIT_NOT_FOUND = 3

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

#: Rooted in the repository rather than in the working directory: a default
#: that moved with the shell's ``cwd`` would scatter immutable evidence.
DEFAULT_RAW_ROOT = os.path.join(_REPO_ROOT, "data", "raw")
DEFAULT_CANONICAL_ROOT = os.path.join(_REPO_ROOT, "data", "canonical")
DEFAULT_EVIDENCE_ROOT = os.path.join(_REPO_ROOT, "data", "evidence")

#: What ``render-rows`` writes, one file per table migration 0006 declares.
#: Named here so a reader can see that the set is fixed and that no table
#: outside 0006 is written.
ROW_FILES = (
    "evidence_builds.ndjson",
    "evidence_records.ndjson",
    "evidence_genes.ndjson",
    "evidence_drugs.ndjson",
    "evidence_text_fragments.ndjson",
    "publication_references.ndjson",
    "evidence_publications.ndjson",
    "evidence_provenance.ndjson",
    "evidence_import_issues.ndjson",
)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser. Separated so tests can exercise it alone."""
    parser = argparse.ArgumentParser(
        prog="pgx-evidence",
        description=("Build, verify and trace evidence stores. This tool "
                     "never approves, curates, publishes or releases "
                     "anything, and never invents a version, an origin or a "
                     "publication identity."))

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--text", action="store_true",
                        help="Human-readable output instead of JSON.")

    build = _sub(parser, "build", common,
                 "Assemble an evidence build from a sealed snapshot and a "
                 "sealed canonical build, and seal it. Refuses to overwrite.")
    build.add_argument("--dataset-id", required=True,
                       help="The dataset this build must be of, stated "
                            "explicitly and checked against the inputs.")
    build.add_argument("--snapshot", required=True,
                       help="Path to the sealed raw snapshot directory.")
    build.add_argument("--canonical-build", required=True,
                       help="Path to the sealed canonical build directory.")
    build.add_argument("--out", default=None,
                       help="Evidence root (default: data/evidence).")
    build.add_argument("--mode", choices=[item.value for item in ImportMode],
                       default=ImportMode.PRODUCTION.value,
                       help="PRODUCTION fails closed on any blocking finding. "
                            "LEGACY_MIGRATION stores the blockers visibly and "
                            "quarantines the build; it does not downgrade "
                            "them to warnings.")
    build.add_argument("--allocation", default=None,
                       help="Existing evidence-identity-allocation.json to "
                            "reuse. Required to reproduce an earlier build.")
    build.add_argument("--allocate-new-identities", action="store_true",
                       help="Permit this run to mint UUIDs for natural keys "
                            "that have none. Without it, a missing identity "
                            "is an error rather than a silent new UUID.")
    build.add_argument("--source-policy-status", default=None,
                       help="The recorded source-policy status for this "
                            "dataset. Omitted means no approval is on record. "
                            "This flag reports a status; it cannot set one.")
    build.add_argument("--note", default=None,
                       help="One factual sentence recorded in the manifest.")

    verify = _sub(parser, "verify", common,
                  "Re-hash a sealed evidence build and, given the snapshot, "
                  "re-derive traces from the raw bytes.")
    verify.add_argument("--build", required=True,
                        help="Path to the sealed evidence build directory.")
    verify.add_argument("--snapshot", default=None,
                        help="Raw snapshot to re-verify traces against. "
                             "Omitted, only the build's own digests are "
                             "checked.")
    verify.add_argument("--trace-limit", type=int, default=25,
                        help="How many records to re-derive from raw bytes "
                             "(default 25). 0 means every record.")

    inspect = _sub(parser, "inspect", common,
                   "Print a sealed build's manifest without re-hashing it.")
    inspect.add_argument("--build", required=True,
                         help="Path to the sealed evidence build directory.")

    listing = _sub(parser, "list", common,
                   "List evidence records. Read-only, and every filter is an "
                   "exact match on a source-declared value.")
    listing.add_argument("--build", required=True,
                         help="Path to the sealed evidence build directory.")
    listing.add_argument("--gene", default=None,
                         help="Canonical gene key, e.g. GENE:CYP2C19.")
    listing.add_argument("--drug", default=None,
                         help="Canonical drug key, e.g. DRUG:clopidogrel.")
    listing.add_argument("--provider-source", default=None,
                         help="Where the bytes were retrieved from.")
    listing.add_argument("--origin-source", default=None,
                         help="Who the record itself says asserted it.")
    listing.add_argument("--publication", default=None,
                         help="pmid:<digits> or doi:<doi>. Titles are "
                              "refused: two records printing one title have "
                              "not been shown to cite one article.")
    listing.add_argument("--record-type", default=None,
                         choices=[item.value for item in EvidenceRecordType],
                         help="Filter by resolved record type.")
    listing.add_argument("--mapping-status", default=None,
                         help="CONFIRMED, PENDING_REVIEW or UNMAPPED.")
    listing.add_argument("--version-status", default=None,
                         help="KNOWN, SOURCE_UNVERSIONED, UNKNOWN_LEGACY, "
                              "MISSING or INVALID.")
    listing.add_argument("--origin-status", default=None,
                         help="STATED_BY_SOURCE, NOT_STATED_BY_SOURCE, "
                              "AMBIGUOUS or UNREGISTERED.")
    listing.add_argument("--production-eligible", action="store_true",
                         help="Only records eligible for production use.")
    listing.add_argument("--limit", type=int, default=50,
                         help="Maximum records to print (default 50). "
                              "0 means all. A truncated listing says so.")

    trace = _sub(parser, "trace", common,
                 "Print the whole chain from one evidence record back to the "
                 "raw bytes it was read from.")
    trace.add_argument("--build", required=True,
                       help="Path to the sealed evidence build directory.")
    trace.add_argument("--record", default=None,
                       help="Evidence record UUID.")
    trace.add_argument("--natural-key", default=None,
                       help="Natural key. Two records under one key is "
                            "corruption and is reported as such, not "
                            "resolved by returning the first.")
    trace.add_argument("--verify-against-raw", default=None,
                       help="Raw snapshot path. Re-reads the artifact, "
                            "re-hashes it, re-resolves the pointer and "
                            "re-derives the payload hash.")

    issues = _sub(parser, "issues", common,
                  "List import issues. Blocking issues stay blocking in "
                  "every mode; quarantine stores them, it does not soften "
                  "them.")
    issues.add_argument("--build", required=True,
                        help="Path to the sealed evidence build directory.")
    issues.add_argument("--code", default=None, help="Exact issue code.")
    issues.add_argument("--severity", default=None,
                        help="BLOCKING, ADVISORY or INFORMATIONAL.")
    issues.add_argument("--limit", type=int, default=50,
                        help="Maximum issues to print (default 50). 0 = all.")
    issues.add_argument("--counts-only", action="store_true",
                        help="Print the code and severity tallies only.")

    draft = _sub(parser, "extract-draft-curation", common,
                 "Read the legacy project interpretations into unreviewed "
                 "migration candidates. Creates no curation and approves "
                 "nothing.")
    draft.add_argument("--repo-root", default=None,
                       help="Repository root holding the legacy files "
                            "(default: this checkout).")
    draft.add_argument("--build", default=None,
                       help="Sealed evidence build, used only to link a "
                            "proposal to the evidence it would be about.")
    draft.add_argument("--out", required=True,
                       help="Where to write draft-curation-proposals.ndjson. "
                            "Outside the evidence store, on purpose: an "
                            "unreviewed proposal is not evidence.")

    rows = _sub(parser, "render-rows", common,
                "Render the operational rows migration 0006 declares, one "
                "NDJSON per table. Renders only: this package has no "
                "evidence-store persistence adapter and claims none.")
    rows.add_argument("--build", required=True,
                      help="Path to the sealed evidence build directory.")
    rows.add_argument("--out", required=True,
                      help="Directory to write the row files into. Refuses "
                           "to overwrite an existing file.")

    compare = _sub(parser, "compare-builds", common,
                   "Compare two sealed evidence builds file by file and by "
                   "content hash. This is how a reproducibility claim is "
                   "checked.")
    compare.add_argument("--left", required=True, help="First build directory.")
    compare.add_argument("--right", required=True,
                         help="Second build directory.")

    # Deliberately absent, and named here so their absence is visible in this
    # file rather than only in a document: approve, publish, activate,
    # retire, curate, approve-curation, generate-rules, quality-approve,
    # source-policy-approve, and any --force, --overwrite or --reviewer flag.
    return parser


def _sub(parser: argparse.ArgumentParser, name: str,
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
        "list": _cmd_list,
        "trace": _cmd_trace,
        "issues": _cmd_issues,
        "extract-draft-curation": _cmd_extract_draft_curation,
        "render-rows": _cmd_render_rows,
        "compare-builds": _cmd_compare_builds,
    }
    try:
        return handlers[args.command](args)
    except EvidenceGateError as exc:
        _emit(args, {"error": str(exc),
                     "code": "IMPORT_REFUSED",
                     "issues": [issue.to_json() for issue in exc.issues]},
              "\n".join(["import refused: %s" % exc]
                        + ["  %s  %s" % (issue.severity, issue.code)
                           for issue in exc.issues]))
        return EXIT_REFUSED
    except DuplicateNaturalKeyError as exc:
        _emit(args, {"error": str(exc), "code": "DUPLICATE_NATURAL_KEY"},
              str(exc))
        return EXIT_REFUSED
    except EvidenceBuildError as exc:
        code = getattr(exc, "code", None)
        _emit(args, {"error": str(exc), "code": code}, str(exc))
        if code in ("BUILD_MISSING", "MANIFEST_MISSING"):
            return EXIT_NOT_FOUND
        return EXIT_REFUSED
    except EvidenceError as exc:
        _emit(args, {"error": str(exc), "code": getattr(exc, "code", None)},
              str(exc))
        return EXIT_REFUSED
    except (OSError, ValueError) as exc:
        _emit(args, {"error": str(exc), "code": "CONFIGURATION_FAILURE"},
              "CONFIGURATION_FAILURE: %s" % exc)
        return EXIT_CONFIGURATION_FAILURE


# -- commands -----------------------------------------------------------


def _cmd_build(args) -> int:
    """Assemble, check the dataset identity, then seal.

    The dataset check happens after assembly and before writing. Assembly is
    what reads the inputs' declared identity, and writing is what makes a
    wrong answer permanent, so the check belongs between them.
    """
    output_root = args.out or DEFAULT_EVIDENCE_ROOT
    for label, path in (("snapshot", args.snapshot),
                        ("canonical build", args.canonical_build)):
        if not os.path.isdir(path):
            _emit(args, {"error": "no %s at %s" % (label, path),
                         "code": "INPUT_MISSING"},
                  "no %s at %s" % (label, path))
            return EXIT_NOT_FOUND

    request = EvidenceBuildRequest(
        snapshot_root=args.snapshot,
        canonical_build_path=args.canonical_build,
        output_root=output_root,
        mode=ImportMode(args.mode),
        allocation_path=args.allocation,
        allow_new_identities=args.allocate_new_identities,
        source_policy_status=args.source_policy_status,
        build_note=args.note)
    build = build_evidence(request)

    if build.dataset_public_id != args.dataset_id:
        _emit(args, {"error": ("--dataset-id says %s but the inputs declare "
                               "%s. Nothing was written."
                               % (args.dataset_id, build.dataset_public_id)),
                     "code": "DATASET_ID_MISMATCH",
                     "requested_dataset_id": args.dataset_id,
                     "input_dataset_id": build.dataset_public_id},
              "DATASET_ID_MISMATCH: --dataset-id says %s but the inputs "
              "declare %s. Nothing was written."
              % (args.dataset_id, build.dataset_public_id))
        return EXIT_CONFIGURATION_FAILURE

    result = write_evidence_build(build, output_root)
    ok, problems = verify_evidence_build(result.build_path)

    payload = result.to_json()
    payload["build_path"] = result.build_path
    payload["checksums_match"] = ok
    payload["checksum_problems"] = list(problems)
    payload["dataset_lifecycle_state"] = "BUILDING"

    text = "\n".join(
        ["evidence build sealed at %s" % result.build_path,
         "  build key      %s" % build.build_key,
         "  content hash   %s" % build.content_hash(),
         "  mode           %s" % build.mode.value,
         "  records        %d" % len(build.records),
         "  issues         %d (%d blocking)"
         % (len(build.all_issues), len(build.blocking_issues)),
         "  identities     %d minted, %d reused"
         % (len(build.allocation_result.minted),
            len(build.allocation_result.reused)),
         "  labels         %s" % ", ".join(build.lifecycle_labels),
         "  dataset        BUILDING (a build is not an approval)"]
        + ["    - %s" % problem for problem in problems])
    _emit(args, payload, text)
    return EXIT_OK if ok else EXIT_REFUSED


def _cmd_verify(args) -> int:
    """Three independent checks, reported separately.

    The bytes changed; the manifest disagrees with the files beside it; or a
    record's chain no longer reaches the raw bytes it claims. They fail for
    different reasons and a single boolean would hide which.
    """
    ok, problems = verify_evidence_build(args.build)
    manifest = read_evidence_manifest(args.build)

    present = sorted(name for name in EVIDENCE_BUILD_FILES
                     if os.path.isfile(os.path.join(args.build, name)))
    absent = [name for name in EVIDENCE_BUILD_FILES if name not in present]

    # The published schemas, applied to the documents they describe. A schema
    # nothing validates against is a description; a schema the build is checked
    # against is a contract.
    schema_problems: List[str] = list(
        "manifest.json: %s" % problem
        for problem in validate_evidence_build_manifest(manifest))
    records = _read_ndjson(os.path.join(args.build, "evidence-records.ndjson"))
    invalid_records = 0
    for row in records:
        problems_here = validate_evidence_record(row)
        if problems_here:
            invalid_records += 1
            if len(schema_problems) < 20:
                schema_problems.append(
                    "evidence-records.ndjson[%s]: %s"
                    % ((row.get("natural_key") or {}).get("natural_key"),
                       problems_here[0]))

    trace_problems: List[str] = []
    traced = 0
    if args.snapshot:
        if not os.path.isdir(args.snapshot):
            _emit(args, {"error": "no snapshot at %s" % args.snapshot,
                         "code": "INPUT_MISSING"},
                  "no snapshot at %s" % args.snapshot)
            return EXIT_NOT_FOUND
        repository = ArtifactEvidenceDetailRepository(args.build)
        records = repository.list_for_build()
        if args.trace_limit > 0:
            records = records[:args.trace_limit]
        for detail in records:
            traced += 1
            trace_problems.extend(
                "%s: %s" % (detail["natural_key"], problem)
                for problem in repository.verify_trace(detail["record_uuid"],
                                                       args.snapshot))

    payload = {
        "build_path": args.build,
        "evidence_build_key": manifest.get("evidence_build_key"),
        "checksums_match": ok,
        "checksum_problems": list(problems),
        "files_present": present,
        "files_absent": absent,
        "traces_verified": traced,
        "trace_problems": trace_problems,
        "records_checked": len(records),
        "records_failing_schema": invalid_records,
        "schema_valid": not schema_problems,
        "schema_problems": schema_problems,
        "lifecycle_labels": list(manifest.get("lifecycle_labels") or ()),
        "production_eligible": manifest.get("production_eligible"),
        "ok": bool(ok and not absent and not trace_problems
                   and not schema_problems),
    }
    lines = ["verify %s" % args.build,
             "  checksums          %s" % ("ok" if ok else "FAILED"),
             "  files              %s"
             % ("ok" if not absent else "MISSING: " + ", ".join(absent)),
             "  published schemas  %s"
             % ("ok (%d records)" % len(records) if not schema_problems
                else "FAILED (%d records)" % invalid_records),
             "  traces re-derived  %s"
             % ("not requested" if not args.snapshot
                else "%d checked, %s" % (traced, "ok" if not trace_problems
                                         else "%d PROBLEMS"
                                         % len(trace_problems)))]
    for problem in list(problems) + schema_problems + trace_problems:
        lines.append("    - %s" % problem)
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK if payload["ok"] else EXIT_REFUSED


def _cmd_inspect(args) -> int:
    manifest = read_evidence_manifest(args.build)
    present = sorted(name for name in EVIDENCE_BUILD_FILES
                     if os.path.isfile(os.path.join(args.build, name)))
    manifest["files_present"] = present
    manifest["files_absent"] = [name for name in EVIDENCE_BUILD_FILES
                                if name not in present]
    summary = manifest.get("summary") or {}
    lines = [
        "evidence build %s" % manifest.get("evidence_build_key"),
        "  dataset        %s" % manifest.get("dataset_public_id"),
        "  content hash   %s" % manifest.get("content_hash"),
        "  mode           %s" % manifest.get("mode"),
        "  snapshot       %s (%s)" % (manifest.get("snapshot_manifest_hash"),
                                      manifest.get("snapshot_state")),
        "  canonical      %s" % manifest.get("canonical_build_key"),
        "  records        %s" % summary.get("record_count"),
        "  blocking       %s" % summary.get("blocking_issue_count"),
        "  eligible       %s" % manifest.get("production_eligible"),
        "  labels         %s" % ", ".join(manifest.get("lifecycle_labels")
                                          or ()),
        "  lifecycle      %s" % manifest.get("dataset_lifecycle_state"),
    ]
    _emit(args, manifest, "\n".join(lines))
    return EXIT_OK


def _cmd_list(args) -> int:
    repository = ArtifactEvidenceDetailRepository(args.build)
    selectors = [name for name in ("gene", "drug", "provider_source",
                                   "origin_source", "publication")
                 if getattr(args, name)]
    if len(selectors) > 1:
        _emit(args, {"error": ("one entity selector at a time: %s were given. "
                               "Intersecting them here would answer a "
                               "question nobody asked precisely."
                               % ", ".join(sorted(selectors))),
                     "code": "AMBIGUOUS_SELECTION"},
              "AMBIGUOUS_SELECTION: %s" % ", ".join(sorted(selectors)))
        return EXIT_CONFIGURATION_FAILURE

    if args.gene:
        rows: Sequence[Mapping[str, Any]] = repository.list_for_gene(args.gene)
    elif args.drug:
        rows = repository.list_for_drug(args.drug)
    elif args.provider_source:
        rows = repository.list_for_provider_source(args.provider_source)
    elif args.origin_source:
        rows = repository.list_for_origin_source(args.origin_source)
    elif args.publication:
        rows = repository.list_for_publication(args.publication)
    else:
        rows = repository.list_for_build()

    # Applied uniformly after selection rather than pushed into one branch:
    # every selector returns the same shape, so one filter covers them all and
    # a new selector cannot arrive with the type filter quietly missing.
    if args.record_type:
        rows = [row for row in rows if row["record_type"] == args.record_type]
    for attribute, wanted in (("record_type_mapping", args.mapping_status),
                              ("version_status", args.version_status),
                              ("origin_status", args.origin_status)):
        if not wanted:
            continue
        if attribute == "record_type_mapping":
            rows = [row for row in rows
                    if (row.get("record_type_mapping") or {}).get("status")
                    == wanted]
        else:
            rows = [row for row in rows if row.get(attribute) == wanted]
    if args.production_eligible:
        rows = [row for row in rows if row.get("production_eligible")]

    total = len(rows)
    shown = rows if args.limit <= 0 else rows[:args.limit]
    payload = {
        "build_path": args.build,
        "evidence_build_key": repository.evidence_build_key,
        "matched": total,
        "shown": len(shown),
        "truncated": len(shown) < total,
        "records": [_summarize(row) for row in shown],
    }
    lines = ["%d records matched, showing %d" % (total, len(shown)),
             "  %-36s %-22s %-16s %-14s %s"
             % ("SOURCE RECORD", "TYPE", "ORIGIN", "VERSION", "UUID")]
    for row in shown:
        # The source record id, not the natural key: a natural key is mostly
        # the dataset and provider repeated on every line, and truncating it
        # to fit would cut off the one part that differs.
        lines.append("  %-36s %-22s %-16s %-14s %s"
                     % (_source_record_id(row["natural_key"]),
                        row["record_type"],
                        row["origin_source_key"] or "-",
                        row["version_status"], row["record_uuid"]))
    if payload["truncated"]:
        lines.append("  ... %d more not shown (--limit 0 for all)"
                     % (total - len(shown)))
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK


def _cmd_trace(args) -> int:
    if bool(args.record) == bool(args.natural_key):
        _emit(args, {"error": "give exactly one of --record or --natural-key",
                     "code": "AMBIGUOUS_SELECTION"},
              "give exactly one of --record or --natural-key")
        return EXIT_CONFIGURATION_FAILURE

    repository = ArtifactEvidenceDetailRepository(args.build)
    record_uuid = args.record
    if args.natural_key:
        detail = repository.get_by_natural_key(args.natural_key)
        if detail is None:
            _emit(args, {"error": "no evidence record under natural key %s"
                                  % args.natural_key,
                         "code": "RECORD_NOT_FOUND"},
                  "no evidence record under natural key %s" % args.natural_key)
            return EXIT_NOT_FOUND
        record_uuid = detail["record_uuid"]

    chain = repository.trace(record_uuid)
    if chain is None:
        _emit(args, {"error": "no evidence record %s in %s"
                              % (record_uuid, args.build),
                     "code": "RECORD_NOT_FOUND"},
              "no evidence record %s in %s" % (record_uuid, args.build))
        return EXIT_NOT_FOUND

    payload: Dict[str, Any] = dict(chain)
    problems: List[str] = []
    if args.verify_against_raw:
        if not os.path.isdir(args.verify_against_raw):
            _emit(args, {"error": "no snapshot at %s"
                                  % args.verify_against_raw,
                         "code": "INPUT_MISSING"},
                  "no snapshot at %s" % args.verify_against_raw)
            return EXIT_NOT_FOUND
        problems = list(repository.verify_trace(record_uuid,
                                                args.verify_against_raw))
        payload["verified_against_raw"] = args.verify_against_raw
        payload["trace_problems"] = problems
        payload["trace_ok"] = not problems

    _emit(args, payload, _render_trace(chain, args.verify_against_raw,
                                       problems))
    return EXIT_OK if not problems else EXIT_REFUSED


def _cmd_issues(args) -> int:
    rows = _read_ndjson(os.path.join(args.build, "import-issues.ndjson"))
    if args.code:
        rows = [row for row in rows if row.get("code") == args.code]
    if args.severity:
        rows = [row for row in rows if row.get("severity") == args.severity]

    by_code: Dict[str, int] = {}
    by_severity: Dict[str, int] = {}
    for row in rows:
        by_code[str(row.get("code"))] = by_code.get(str(row.get("code")), 0) + 1
        severity = str(row.get("severity"))
        by_severity[severity] = by_severity.get(severity, 0) + 1

    shown = [] if args.counts_only else (
        rows if args.limit <= 0 else rows[:args.limit])
    payload = {
        "build_path": args.build,
        "matched": len(rows),
        "shown": len(shown),
        "truncated": bool(shown) and len(shown) < len(rows),
        "counts_by_code": dict(sorted(by_code.items())),
        "counts_by_severity": dict(sorted(by_severity.items())),
        "issues": shown,
        "note": ("Quarantine stores blocking issues; it does not turn them "
                 "into warnings. A BLOCKING count above zero means this build "
                 "is not production eligible."),
    }
    lines = ["%d issues matched" % len(rows)]
    for code, count in sorted(by_code.items()):
        lines.append("  %-40s %d" % (code, count))
    for row in shown:
        lines.append("  %-10s %-38s %s" % (row.get("severity"),
                                           str(row.get("code"))[:38],
                                           row.get("subject")))
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK


def _cmd_extract_draft_curation(args) -> int:
    repo_root = args.repo_root or _REPO_ROOT
    records: Sequence[Any] = ()
    if args.build:
        records = [_SealedRecordView(row) for row in _read_ndjson(
            os.path.join(args.build, "evidence-records.ndjson"))]
    result = extract_draft_curation(repo_root, records)

    if os.path.exists(args.out):
        _emit(args, {"error": ("%s already exists. A migration artifact is "
                               "not overwritten in place: write the new run "
                               "elsewhere and compare." % args.out),
                     "code": "OUTPUT_EXISTS"},
              "OUTPUT_EXISTS: %s" % args.out)
        return EXIT_REFUSED
    directory = os.path.dirname(os.path.abspath(args.out))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        for proposal in result.proposals:
            handle.write(json.dumps(proposal.to_json(), sort_keys=True,
                                    ensure_ascii=False) + "\n")

    schema_problems: List[str] = []
    for proposal in result.proposals:
        found = validate_draft_curation_proposal(proposal.to_json())
        if found:
            schema_problems.append("%s: %s" % (proposal.proposal_id, found[0]))
            if len(schema_problems) >= 20:
                break

    payload = result.to_json()
    payload["output_path"] = args.out
    payload["schema_valid"] = not schema_problems
    payload["schema_problems"] = schema_problems
    payload["effect"] = (
        "None on the evidence store. These are unreviewed migration "
        "candidates written outside it. No CuratedInterpretation was created, "
        "no reviewer was named, and nothing here is executable.")
    lines = ["wrote %d draft curation proposals to %s"
             % (len(result.proposals), args.out),
             "  linked to evidence   %d"
             % payload["linked_proposal_count"],
             "  unlinked             %d" % result.unlinked_count,
             "  status               %s" % payload["status"],
             "  warnings             %s" % ", ".join(payload["warnings"]),
             "  content hash         %s" % payload["content_hash"],
             "  published schema     %s" % ("ok" if not schema_problems
                                            else "FAILED")]
    for problem in schema_problems:
        lines.append("    - %s" % problem)
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK if not schema_problems else EXIT_REFUSED


def _cmd_render_rows(args) -> int:
    """Render migration 0006's operational rows from a sealed build.

    Renders and stops. This package ships no evidence-store persistence
    adapter, so a command that claimed to have inserted these rows would be
    claiming something no code here can do. The rows are written where a
    loader - or a constraint drill - can read them.
    """
    manifest = read_evidence_manifest(args.build)
    tables = _row_payloads(args.build, manifest)

    os.makedirs(args.out, exist_ok=True)
    existing = [name for name in ROW_FILES
                if os.path.exists(os.path.join(args.out, name))]
    if existing:
        _emit(args, {"error": ("%s already holds %s. Row files are not "
                               "overwritten." % (args.out,
                                                 ", ".join(existing))),
                     "code": "OUTPUT_EXISTS"},
              "OUTPUT_EXISTS: %s" % ", ".join(existing))
        return EXIT_REFUSED

    counts: Dict[str, int] = {}
    for name in ROW_FILES:
        rows = tables.get(name, [])
        counts[name] = len(rows)
        with open(os.path.join(args.out, name), "w", encoding="utf-8",
                  newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True,
                                        ensure_ascii=False) + "\n")

    payload = {
        "build_path": args.build,
        "evidence_build_key": manifest.get("evidence_build_key"),
        "output_path": args.out,
        "row_counts": counts,
        "total_rows": sum(counts.values()),
        "effect": ("None on any database. These are rendered rows for "
                   "migration 0006's tables; inserting them is a separate "
                   "step and this package performs no insert."),
    }
    lines = ["rendered %d rows into %s" % (payload["total_rows"], args.out)]
    for name in ROW_FILES:
        lines.append("  %-34s %d" % (name, counts[name]))
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK


def _cmd_compare_builds(args) -> int:
    comparison = compare_evidence_builds(args.left, args.right)
    payload = comparison.to_json()
    lines = ["compare %s\n     vs %s" % (args.left, args.right),
             "  reproducible   %s" % payload.get("reproducible"),
             "  content hash   %s" % ("matches"
                                      if payload.get("content_hash_matches")
                                      else "DIFFERS"),
             "  complete       %s" % ("yes" if payload.get("both_complete")
                                      else "NO - files are missing"),
             "  identical      %d files"
             % len(payload.get("identical_files") or ()),
             "  differing      %s"
             % (", ".join(payload.get("differing_files") or ()) or "none"),
             "  only left      %s"
             % (", ".join(payload.get("only_left") or ()) or "none"),
             "  only right     %s"
             % (", ".join(payload.get("only_right") or ()) or "none")]
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK if payload.get("reproducible") else EXIT_REFUSED


class _SealedNaturalKeyView:
    """A natural key read back from a sealed build's NDJSON."""

    __slots__ = ("_payload",)

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._payload = payload

    @property
    def source_record_id(self) -> Optional[str]:
        return self._payload.get("source_record_id")

    def to_string(self) -> str:
        return str(self._payload.get("natural_key"))


class _SealedRecordView:
    """A sealed build's stored record, shaped like an in-memory draft.

    ``extract_draft_curation`` documents the four things it reads from a
    record: the natural key's ``source_record_id``, the key as a string, the
    raw source payload, and the allocated UUID. A sealed build stores all four
    as plain JSON, so this adapter presents them under the names the function
    already expects rather than teaching that function a second input shape.

    Read-only, and it exposes nothing else: a view that quietly offered more
    would invite the linker to start matching on fields nobody chose.
    """

    __slots__ = ("_payload", "natural_key")

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._payload = payload
        self.natural_key = _SealedNaturalKeyView(
            payload.get("natural_key") or {})

    @property
    def record_uuid(self) -> Optional[str]:
        return self._payload.get("record_uuid")

    @property
    def raw_source_payload(self) -> Any:
        return self._payload.get("raw_source_payload")


# -- row rendering ------------------------------------------------------


def _row_payloads(build_path: str,
                  manifest: Mapping[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Map a sealed build's files onto migration 0006's columns.

    One place, so that a column added to 0006 and not rendered here shows up
    as a missing key rather than as a silently absent row.

    Publications are deduplicated by identity, because ``publication_references``
    is keyed on identity and two records citing one PMID cite one article. A
    reference with no identity gets its own row and is linked positionally,
    since two unidentified references have *not* been shown to be the same
    article - which is exactly what a fuzzy title match would assume.
    """
    records = _read_ndjson(os.path.join(build_path, "evidence-records.ndjson"))
    summary = manifest.get("summary") or {}
    build_key = str(manifest.get("evidence_build_key"))

    tables: Dict[str, List[Dict[str, Any]]] = {name: [] for name in ROW_FILES}

    tables["evidence_builds.ndjson"].append({
        "dataset_public_id": manifest.get("dataset_public_id"),
        "evidence_build_key": build_key,
        "content_hash": manifest.get("content_hash"),
        "snapshot_manifest_hash": manifest.get("snapshot_manifest_hash"),
        "canonical_build_key": manifest.get("canonical_build_key"),
        "canonical_build_content_hash":
            manifest.get("canonical_build_content_hash"),
        "allocation_content_hash": manifest.get("allocation_content_hash"),
        "build_relative_path": _relative_to_repo(build_path),
        "mode": manifest.get("mode"),
        "production_eligible": manifest.get("production_eligible"),
        "lifecycle_labels": list(manifest.get("lifecycle_labels") or ()),
        "rule_versions": manifest.get("rule_versions"),
        "summary": summary,
        "source_policy_status": manifest.get("source_policy_status"),
        "record_count": summary.get("record_count"),
        "blocking_issue_count": summary.get("blocking_issue_count"),
        "built_at": manifest.get("built_at"),
    })

    for record in records:
        natural = record.get("natural_key") or {}
        attribution = record.get("attribution") or {}
        version = record.get("version") or {}
        mapping = record.get("record_type_mapping") or {}
        tables["evidence_records.ndjson"].append({
            "id": record.get("record_uuid"),
            "evidence_build_key": build_key,
            "natural_key": natural.get("natural_key"),
            "record_type": natural.get("record_type"),
            "source_object_class": mapping.get("source_object_class"),
            "record_type_mapping_status": mapping.get("status"),
            "source_record_id": natural.get("source_record_id"),
            "source_record_id_raw_type": record.get(
                "source_record_id_raw_type"),
            "source_record_version": version.get("value"),
            "source_record_version_status": version.get("status"),
            "provider_source_key": attribution.get("provider_source_key"),
            "origin_source_key": attribution.get("origin_source_key"),
            "origin_source_status": attribution.get("origin_status"),
            "raw_origin_value": attribution.get("raw_origin_value"),
            "source_payload_hash": record.get("source_payload_hash"),
            "evidence_content_hash": record.get("content_hash"),
            "production_eligible": record.get("production_eligible"),
        })

    for row in _read_ndjson(os.path.join(build_path,
                                         "evidence-entity-links.ndjson")):
        target = ("evidence_genes.ndjson" if row.get("entity_type") == "GENE"
                  else "evidence_drugs.ndjson")
        tables[target].append({
            "evidence_record_id": row.get("record_uuid"),
            "canonical_key": row.get("canonical_key"),
            "canonical_entity_uuid": row.get("entity_uuid"),
            "role": row.get("role"),
            "source_field": row.get("source_field"),
            "raw_value": row.get("raw_value"),
        })

    for row in _read_ndjson(os.path.join(build_path,
                                         "evidence-text-fragments.ndjson")):
        tables["evidence_text_fragments.ndjson"].append({
            "evidence_record_id": row.get("record_uuid"),
            "field_name": row.get("field_name"),
            "ordinal": row.get("ordinal"),
            "text": row.get("text"),
            "text_format": row.get("text_format"),
            "language": row.get("language"),
            "language_value": row.get("language_value"),
            "text_hash": row.get("text_hash"),
            "exact_text_hash": row.get("exact_text_hash"),
        })

    publications = _read_ndjson(os.path.join(build_path,
                                             "publication-references.ndjson"))
    by_identity: Dict[str, str] = {}
    unidentified = 0
    for row in publications:
        identity = row.get("identity")
        if identity and identity in by_identity:
            reference_id = by_identity[identity]
        else:
            if identity:
                reference_id = "publication:%s" % identity
                by_identity[identity] = reference_id
            else:
                unidentified += 1
                reference_id = "publication:unidentified:%d" % unidentified
            tables["publication_references.ndjson"].append({
                "id": reference_id,
                "pmid": row.get("pmid"),
                "doi": row.get("doi"),
                "title": row.get("title"),
                "publication_year": row.get("year"),
                "url": row.get("url"),
                "identity": identity,
                "raw_value": row.get("raw_value"),
                "validation_issues": list(row.get("validation_issues") or ()),
            })
        tables["evidence_publications.ndjson"].append({
            "evidence_record_id": row.get("record_uuid"),
            "publication_reference_id": reference_id if identity else None,
            "ordinal": row.get("ordinal"),
            "source_field": row.get("source_field"),
            "raw_value": row.get("raw_value"),
            "validation_issues": list(row.get("validation_issues") or ()),
        })

    for row in _read_ndjson(os.path.join(build_path,
                                         "evidence-provenance.ndjson")):
        tables["evidence_provenance.ndjson"].append({
            "evidence_record_id": row.get("record_uuid"),
            "dataset_public_id": manifest.get("dataset_public_id"),
            "snapshot_manifest_hash": manifest.get("snapshot_manifest_hash"),
            "artifact_path": row.get("artifact_path"),
            "artifact_sha256": row.get("artifact_sha256"),
            "json_pointer": row.get("pointer"),
            "csv_row_number": row.get("csv_row_number"),
            "requested_container": row.get("requested_container"),
            "source_payload_hash": row.get("source_payload_hash"),
        })

    for row in _read_ndjson(os.path.join(build_path,
                                         "import-issues.ndjson")):
        tables["evidence_import_issues.ndjson"].append({
            "evidence_build_key": build_key,
            "code": row.get("code"),
            "severity": row.get("severity"),
            "subject": row.get("subject"),
            "detail": row.get("detail"),
            "natural_key": row.get("natural_key"),
            "locator": row.get("locator"),
        })

    return tables


def _relative_to_repo(path: str) -> str:
    """A build path as the manifest should record it: relative, never absolute.

    An absolute path recorded in a row is a claim about one machine's
    filesystem, and it stops being true the moment the repository is cloned
    somewhere else.
    """
    absolute = os.path.abspath(path)
    try:
        relative = os.path.relpath(absolute, _REPO_ROOT)
    except ValueError:
        return os.path.basename(absolute)
    if relative.startswith(os.pardir):
        return os.path.basename(absolute)
    return relative.replace(os.sep, "/")


# -- helpers ------------------------------------------------------------


def _source_record_id(natural_key: Optional[str]) -> str:
    """The source's own identity out of a natural key, for display only.

    The key is ``dataset|provider|type|source_record_id|version``. Parsed
    positionally rather than by splitting on the last separator, because a
    version string is allowed to be absent and an empty trailing field would
    otherwise make the id look like the version.
    """
    if not natural_key:
        return "-"
    parts = natural_key.split("|")
    return parts[3] if len(parts) >= 4 else natural_key


def _summarize(row: Mapping[str, Any]) -> Dict[str, Any]:
    """One record as a listing line: identity and status, no source text."""
    return {
        "record_uuid": row.get("record_uuid"),
        "natural_key": row.get("natural_key"),
        "record_type": row.get("record_type"),
        "record_type_mapping_status": (row.get("record_type_mapping")
                                       or {}).get("status"),
        "provider_source_key": row.get("provider_source_key"),
        "origin_source_key": row.get("origin_source_key"),
        "origin_status": row.get("origin_status"),
        "version_status": row.get("version_status"),
        "version_value": row.get("version_value"),
        "production_eligible": row.get("production_eligible"),
        "gene_count": len(row.get("genes") or ()),
        "drug_count": len(row.get("drugs") or ()),
        "locator_count": len(row.get("locators") or ()),
        "publication_count": len(row.get("publications") or ()),
        "issue_count": len(row.get("issues") or ()),
    }


def _render_trace(chain: Mapping[str, Any], snapshot: Optional[str],
                  problems: Sequence[str]) -> str:
    hashes = chain.get("hashes") or {}
    origin = chain.get("origin_source") or {}
    provider = chain.get("provider_source") or {}
    version = chain.get("source_record_version") or {}
    lines = [
        "trace %s" % chain.get("record_uuid"),
        "  natural key     %s" % chain.get("natural_key"),
        "  record type     %s (%s)"
        % (chain.get("record_type"),
           (chain.get("record_type_mapping") or {}).get("status")),
        "  retrieved from  %s" % provider.get("source_key"),
        "  asserted by     %s (%s)" % (origin.get("source_key") or "-",
                                       origin.get("status")),
        "  source version  %s (%s)" % (version.get("value") or "-",
                                       version.get("status")),
        "  raw locators    %d" % len(chain.get("raw_locators") or ()),
    ]
    for locator in chain.get("raw_locators") or ():
        lines.append("    %s %s" % (locator.get("artifact_path"),
                                    locator.get("pointer")
                                    or "row %s" % locator.get("csv_row_number")))
    # Distinct digests, not one per locator: seven locators into one file
    # print the same digest seven times, which reads as seven facts.
    artifact_digests = sorted(set(
        str(item) for item in hashes.get("raw_artifact_sha256") or ()))
    labels = tuple(chain.get("lifecycle_labels") or ())
    quarantined = "NOT_PUBLICATION_ELIGIBLE" in labels
    lines.append("  hashes")
    for index, digest in enumerate(artifact_digests):
        lines.append("    raw artifact     %s%s"
                     % (digest, "" if len(artifact_digests) == 1
                        else " (%d of %d distinct)"
                        % (index + 1, len(artifact_digests))))
    lines.extend([
        "    source payload   %s" % hashes.get("source_payload_hash"),
        "    evidence record  %s" % hashes.get("evidence_content_hash"),
        "    evidence build   %s" % hashes.get("evidence_build_content_hash"),
        "    snapshot         %s" % hashes.get("snapshot_manifest_hash"),
        "  entities        %d" % len(chain.get("canonical_entities") or ()),
        "  publications    %d" % len(chain.get("publications") or ()),
        "  text fragments  %d" % len(chain.get("text_fragments") or ()),
        # Two different statements. The record can be complete in itself while
        # the build it belongs to is quarantined, and reporting only the first
        # would read as permission this build does not give.
        "  record complete %s" % chain.get("production_eligible"),
        "  publishable     %s" % (
            "no - the build is quarantined" if quarantined
            else chain.get("production_eligible")),
        "  labels          %s" % ", ".join(labels),
    ])
    if snapshot:
        lines.append("  re-derived from %s: %s"
                     % (snapshot, "ok" if not problems
                        else "%d PROBLEMS" % len(problems)))
        for problem in problems:
            lines.append("    - %s" % problem)
    return "\n".join(lines)


def _emit(args, payload: Mapping[str, Any], text: str) -> None:
    if getattr(args, "text", False):
        sys.stdout.write(text.rstrip("\n") + "\n")
    else:
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True,
                                    ensure_ascii=False) + "\n")


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
