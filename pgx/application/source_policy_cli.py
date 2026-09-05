# -*- coding: utf-8 -*-
"""``pgx-source-policy`` - inspect and enforce scientific source policy (WP-05).

Console entry point: ``pgx-source-policy``. ``scripts/source_policy.py`` is a
thin wrapper that delegates here, so the logic exists once and the installed
package owns it.

Rules this CLI follows, each for a reason:

* **No database.** Every subcommand reads the registry file and the frozen
  legacy CSVs. Source policy is a reviewed document, and a tool that needed a
  running database to answer "may we publish?" could not be run in CI or by a
  reviewer with a checkout.
* **No network.** Nothing here fetches a terms page. Retrieving official
  evidence is a deliberate, recorded act; a CLI that quietly fetched would make
  the difference between "we read the terms" and "a tool once got a 200"
  invisible.
* **It cannot approve anything.** There is no ``approve`` subcommand. Approval
  is a human decision recorded in the registry file, in a commit with an author
  against it, and a command-line flag is not that.
* **Machine-readable by default.** Every subcommand prints one JSON document to
  stdout unless ``--text`` is given. Exit codes are stable so CI can branch on
  *why* something failed.

Exit codes:

===  =========================================================
0    success; for ``validate`` and ``evaluate-publication``, no blocker
1    blocking policy findings exist (the expected result today)
2    configuration failure - the registry is missing or unreadable
3    the named source or file does not exist
4    a generated artefact on disk is stale
===  =========================================================
"""

from __future__ import annotations

import argparse
import datetime as _dt
import io
import json
import os
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

from pgx.scientific.errors import (
    LegacyInventoryError,
    ScientificGovernanceError,
    SourcePolicyConfigError,
    UnknownSourceError,
)
from pgx.scientific.inventory import (
    LEGACY_SOURCE_COLUMNS,
    build_inventory,
    render_markdown,
    unregistered_legacy_values,
)
from pgx.scientific.models import ClaimCategory, ReuseDimension
from pgx.scientific.policy import load_registry
from pgx.scientific.publication_gate import PublicationIntent, evaluate_publication
from pgx.scientific.validation import (
    blocking_issues,
    issue_summary,
    validate_registry,
    validate_source,
)

__all__ = [
    "EXIT_BLOCKED",
    "EXIT_CONFIGURATION_FAILURE",
    "EXIT_NOT_FOUND",
    "EXIT_OK",
    "EXIT_STALE_ARTEFACT",
    "build_parser",
    "main",
]

EXIT_OK = 0
EXIT_BLOCKED = 1
EXIT_CONFIGURATION_FAILURE = 2
EXIT_NOT_FOUND = 3
EXIT_STALE_ARTEFACT = 4

#: Where the generated legacy inventory artefacts live.
INVENTORY_JSON = os.path.join("data", "migration", "legacy-source-inventory.json")
INVENTORY_MARKDOWN = os.path.join("docs", "migration", "legacy-source-inventory.md")
INVENTORY_TITLE = "Legacy source inventory"

#: Checklist the ``review-checklist`` subcommand prints. Numbered because a
#: reviewer works through it in order: evidence before interpretation,
#: interpretation before decision.
REVIEW_CHECKLIST: Sequence[Mapping[str, str]] = (
    {"step": "1", "name": "Identify the exact source",
     "detail": "Name the provider and the specific product or interface. "
               "'CPIC' is a consortium, not a source: the database, the API and "
               "the published guidelines may carry different conditions."},
    {"step": "2", "name": "Retrieve the official terms",
     "detail": "Open the source's own terms, licence or API-conditions "
               "document. Record its https URL, the retrieval instant and a "
               "content hash. Do not copy the document into this repository."},
    {"step": "3", "name": "Reject non-authoritative material",
     "detail": "A search-result snippet, a blog post, an encyclopaedia article "
               "or another project's summary is not licensing authority. If the "
               "official document cannot be reached, record the attempt as "
               "BLOCKED and stop; a failed retrieval is never an approval."},
    {"step": "4", "name": "Write the project interpretation separately",
     "detail": "In your own words, state what you understand the terms to "
               "permit, who you are, and what remains unclear. Keep it apart "
               "from the source's wording so a later reader can check one "
               "against the other. This is not legal advice."},
    {"step": "5", "name": "Answer all ten reuse dimensions",
     "detail": "Every dimension gets ALLOWED, RESTRICTED, PROHIBITED, UNKNOWN "
               "or NOT_APPLICABLE. Leaving one blank is the same as UNKNOWN, "
               "and UNKNOWN blocks. RESTRICTED must name the condition."},
    {"step": "6", "name": "Decide the acquisition mode",
     "detail": "How records may be obtained is a separate question from what "
               "may be done with them. Automated acquisition requires the "
               "AUTOMATED_ACQUISITION dimension to be permitted."},
    {"step": "7", "name": "Record version and citation policy",
     "detail": "How a version of this source is identified, and how it must be "
               "cited. Both are required before publication; neither is ever "
               "inferred."},
    {"step": "8", "name": "Decide the claim categories",
     "detail": "What may this source be cited for? A source cleared for "
               "phenotype mappings has not thereby been cleared to carry a "
               "prescribing recommendation."},
    {"step": "9", "name": "Record the decision under your own name",
     "detail": "decision, reviewer_name, reviewer_role, decided_at, the "
               "evidence URLs relied on, and any restrictions. Set an expiry: a "
               "licence read once is not a licence forever."},
    {"step": "10", "name": "Check for conflicts",
     "detail": "If this source disagrees with another already approved source, "
               "record the conflict. Do not resolve it by choosing a winner "
               "here; a resolution needs its own decision and rationale."},
    {"step": "11", "name": "Re-run the gate",
     "detail": "pgx-source-policy validate, then evaluate-publication for the "
               "dataset in question. Publication stays blocked until the gate "
               "says otherwise."},
)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser. Separated so tests can exercise it alone."""
    parser = argparse.ArgumentParser(
        prog="pgx-source-policy",
        description=("Inspect and enforce the scientific source policy. This "
                     "tool reads policy; it cannot approve a source."))

    # Shared options live on a parent parser rather than at the top level, so
    # they are accepted after the subcommand where a reader expects to type
    # them: `pgx-source-policy validate --text`, git-style.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config", default=None,
        help="Path to the source registry (default: config/scientific-sources.json).")
    common.add_argument(
        "--repo-root", default=None,
        help="Repository root for legacy inputs (default: inferred).")
    common.add_argument(
        "--as-of", default=None,
        help=("ISO-8601 UTC instant to evaluate against (default: now). Pinning "
              "it makes a report reproducible."))
    common.add_argument(
        "--text", action="store_true",
        help="Print a human-readable report instead of JSON.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "validate", parents=[common],
        help="Check every source policy and print the findings.")

    show = subparsers.add_parser(
        "show", parents=[common],
        help="Print one source's policy, or list every source key.")
    show.add_argument("source_key", nargs="?", default=None,
                      help="Source key. Omit to list every registered key.")

    inventory = subparsers.add_parser(
        "inventory-legacy", parents=[common],
        help="Scan the frozen legacy files for the source values they carry.")
    inventory.add_argument(
        "--write", action="store_true",
        help="Write data/migration/legacy-source-inventory.json and its report.")
    inventory.add_argument(
        "--check", action="store_true",
        help="Exit non-zero if the generated artefacts on disk are stale.")

    evaluate = subparsers.add_parser(
        "evaluate-publication", parents=[common],
        help="Decide whether a dataset may be published on the current policy.")
    evaluate.add_argument("--dataset", required=True,
                          help="Dataset key the decision is about.")
    evaluate.add_argument(
        "--source", action="append", default=[], metavar="SOURCE_KEY",
        help="A source the dataset cites. Repeatable.")
    evaluate.add_argument(
        "--claim", action="append", default=[], metavar="CATEGORY",
        help="A claim category the dataset intends to assert. Repeatable.")
    evaluate.add_argument("--displays-source-text", action="store_true",
                          help="Output shows source text to an end user.")
    evaluate.add_argument("--redistributes-aggregated", action="store_true",
                          help="Output publishes aggregated records.")
    evaluate.add_argument("--redistributes-verbatim", action="store_true",
                          help="Output publishes source records verbatim.")
    evaluate.add_argument("--shares-with-third-party", action="store_true",
                          help="Records leave this project.")
    evaluate.add_argument("--commercial-use", action="store_true",
                          help="Use is commercial.")
    evaluate.add_argument("--automated-acquisition", action="store_true",
                          help="Records are retrieved by program.")
    evaluate.add_argument("--bulk-download", action="store_true",
                          help="Whole collections are retrieved.")

    subparsers.add_parser(
        "review-checklist", parents=[common],
        help="Print the source review checklist a human works through.")

    return parser


def _emit(document: Mapping[str, Any]) -> None:
    """Print one JSON document, sorted for a stable diff between runs."""
    sys.stdout.write(json.dumps(document, indent=2, ensure_ascii=False) + "\n")


def _fail(code: str, message: str) -> None:
    sys.stderr.write(json.dumps({"error": code, "message": message}) + "\n")


def _repo_root(args: argparse.Namespace) -> str:
    if args.repo_root:
        return os.path.abspath(args.repo_root)
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return here


def _as_of(args: argparse.Namespace) -> _dt.datetime:
    """Return the evaluation instant, defaulting to now in UTC."""
    if not args.as_of:
        return _dt.datetime.now(_dt.timezone.utc)
    text = args.as_of.strip()
    normalised = text[:-1] + "+00:00" if text.endswith("Z") else text
    parsed = _dt.datetime.fromisoformat(normalised)
    if parsed.tzinfo is None:
        raise ValueError(
            "--as-of must carry a UTC offset; a naive instant names no time")
    return parsed.astimezone(_dt.timezone.utc)


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point. Returns the process exit code rather than calling exit."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except SourcePolicyConfigError as exc:
        _fail("configuration_failure", str(exc))
        return EXIT_CONFIGURATION_FAILURE
    except UnknownSourceError as exc:
        _fail("source_not_found", str(exc))
        return EXIT_NOT_FOUND
    except LegacyInventoryError as exc:
        _fail("legacy_input_failure", str(exc))
        return EXIT_NOT_FOUND
    except ScientificGovernanceError as exc:
        _fail("policy_failure", str(exc))
        return EXIT_CONFIGURATION_FAILURE
    except ValueError as exc:
        _fail("bad_argument", str(exc))
        return EXIT_CONFIGURATION_FAILURE


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "review-checklist":
        return _cmd_review_checklist(args)
    if args.command == "inventory-legacy":
        return _cmd_inventory(args)

    registry = load_registry(args.config)
    now = _as_of(args)

    if args.command == "validate":
        return _cmd_validate(args, registry, now)
    if args.command == "show":
        return _cmd_show(args, registry, now)
    if args.command == "evaluate-publication":
        return _cmd_evaluate(args, registry, now)
    raise ValueError("unhandled command %r" % args.command)  # pragma: no cover


def _cmd_validate(args, registry, now) -> int:
    issues = validate_registry(registry, now)
    blockers = blocking_issues(issues)
    if args.text:
        sys.stdout.write("registry: %s\n" % (registry.source_path or "(in memory)"))
        sys.stdout.write("sources:  %d\n" % len(registry))
        sys.stdout.write("approved: %d\n" % len(registry.approved_records))
        counts = issue_summary(issues)
        sys.stdout.write("findings: %d blocking, %d warning, %d info\n\n"
                         % (counts["BLOCKER"], counts["WARNING"], counts["INFO"]))
        for issue in issues:
            sys.stdout.write(issue.render() + "\n")
    else:
        _emit({
            "registry": registry.source_path,
            "registry_content_hash": registry.content_hash(),
            "source_count": len(registry),
            "approved_source_count": len(registry.approved_records),
            "summary": issue_summary(issues),
            "issues": [issue.to_json() for issue in issues],
        })
    return EXIT_BLOCKED if blockers else EXIT_OK


def _cmd_show(args, registry, now) -> int:
    if args.source_key is None:
        if args.text:
            for record in registry.records:
                sys.stdout.write("%-32s %-24s %s\n" % (
                    record.source_key, record.status.value, record.display_name))
        else:
            _emit({
                "registry": registry.source_path,
                "source_keys": list(registry.source_keys),
                "approved_source_keys": [r.source_key
                                         for r in registry.approved_records],
            })
        return EXIT_OK

    record = registry.require(args.source_key)
    issues = validate_source(record, now)
    document: Dict[str, Any] = {
        "source": record.to_json(),
        "effective_status": record.effective_status(now).value,
        "is_approved": record.is_approved,
        "conflicts": [c.to_json() for c in registry.conflicts_for(record.source_key)],
        "summary": issue_summary(issues),
        "issues": [issue.to_json() for issue in issues],
    }
    if args.text:
        sys.stdout.write("source:   %s\n" % record.source_key)
        sys.stdout.write("name:     %s\n" % record.display_name)
        sys.stdout.write("role:     %s\n" % record.role.value)
        sys.stdout.write("status:   %s (effective %s)\n" % (
            record.status.value, record.effective_status(now).value))
        sys.stdout.write("approved: %s\n\n" % ("yes" if record.is_approved else "no"))
        sys.stdout.write("reuse matrix:\n")
        for dimension in ReuseDimension:
            sys.stdout.write("  %-28s %s\n" % (
                dimension.value, record.reuse.permission(dimension).value))
        sys.stdout.write("\nfindings:\n")
        for issue in issues:
            sys.stdout.write("  " + issue.render() + "\n")
    else:
        _emit(document)
    return EXIT_BLOCKED if blocking_issues(issues) else EXIT_OK


def _cmd_evaluate(args, registry, now) -> int:
    categories = []
    for raw in args.claim:
        categories.append(ClaimCategory.parse(raw, "--claim"))
    intent = PublicationIntent(
        dataset_key=args.dataset,
        source_keys=tuple(args.source),
        claim_categories=tuple(categories),
        displays_source_text=args.displays_source_text,
        redistributes_aggregated=args.redistributes_aggregated,
        redistributes_verbatim=args.redistributes_verbatim,
        shares_with_third_party=args.shares_with_third_party,
        commercial_use=args.commercial_use,
        automated_acquisition=args.automated_acquisition,
        bulk_download=args.bulk_download,
    )
    eligibility = evaluate_publication(registry, intent, now)
    if args.text:
        sys.stdout.write(eligibility.render() + "\n")
    else:
        document = eligibility.to_json()
        document["intent"] = intent.to_json()
        document["eligibility_digest"] = eligibility.digest()
        _emit(document)
    return EXIT_OK if eligibility.is_eligible else EXIT_BLOCKED


def _cmd_inventory(args) -> int:
    root = _repo_root(args)
    inventory = build_inventory(root)
    json_text = inventory.render_json()
    markdown_text = render_markdown(inventory, INVENTORY_TITLE)
    json_path = os.path.join(root, INVENTORY_JSON)
    markdown_path = os.path.join(root, INVENTORY_MARKDOWN)

    if args.write:
        for path, text in ((json_path, json_text), (markdown_path, markdown_text)):
            directory = os.path.dirname(path)
            if directory and not os.path.isdir(directory):
                os.makedirs(directory)
            with io.open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
        sys.stderr.write("wrote %s\n" % INVENTORY_JSON)
        sys.stderr.write("wrote %s\n" % INVENTORY_MARKDOWN)

    if args.check:
        stale = []
        for path, text, label in ((json_path, json_text, INVENTORY_JSON),
                                  (markdown_path, markdown_text, INVENTORY_MARKDOWN)):
            if not os.path.isfile(path):
                stale.append("%s is missing" % label)
                continue
            with io.open(path, encoding="utf-8") as handle:
                if handle.read() != text:
                    stale.append("%s does not match the current legacy inputs" % label)
        if stale:
            _fail("stale_artefact", "; ".join(stale))
            return EXIT_STALE_ARTEFACT

    # Which legacy values have no policy record is a question about the
    # registry, not about the legacy files, so it is reported on stdout and
    # deliberately kept out of the written artefacts: including it would make
    # the inventory change whenever the registry did, and the inventory's whole
    # value is that it changes only when the data does.
    unregistered = ()
    try:
        unregistered = unregistered_legacy_values(inventory, load_registry(args.config))
    except SourcePolicyConfigError:
        unregistered = ()

    if args.text:
        sys.stdout.write(markdown_text)
    elif not args.write:
        document = inventory.to_json()
        document["unregistered_values"] = [i.to_json() for i in unregistered]
        _emit(document)
    else:
        _emit({
            "content_hash": inventory.content_hash(),
            "distinct_values": inventory.distinct_value_count,
            "total_occurrences": inventory.total_occurrences,
            "columns_scanned": len(LEGACY_SOURCE_COLUMNS),
            "unregistered_values": [i.to_json() for i in unregistered],
            "written": [INVENTORY_JSON, INVENTORY_MARKDOWN],
        })
    return EXIT_OK


def _cmd_review_checklist(args) -> int:
    if args.text:
        sys.stdout.write("Source review checklist\n")
        sys.stdout.write("=" * 23 + "\n\n")
        sys.stdout.write(
            "Approval is a human act. This tool cannot perform any of these\n"
            "steps for you, and there is no subcommand that approves a source.\n\n")
        for item in REVIEW_CHECKLIST:
            sys.stdout.write("%s. %s\n" % (item["step"], item["name"]))
            sys.stdout.write("   %s\n\n" % item["detail"])
    else:
        _emit({
            "note": ("Approval is a human act recorded in the registry file. "
                     "This tool has no subcommand that approves a source."),
            "steps": [dict(item) for item in REVIEW_CHECKLIST],
        })
    return EXIT_OK
