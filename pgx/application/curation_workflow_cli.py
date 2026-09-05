# -*- coding: utf-8 -*-
"""Offline CLI for the curation workflow (WP-10).

    python3 -m pgx.application.curation_workflow_cli gate-status CWI-LEGACY-...

Reads the migration artifacts from disk into an in-memory store and runs the
real ``CurationWorkflowService`` over them. No database connection, no network,
no server: the point is that an operator can ask "why can nothing be approved"
and get the thirteen answers without standing up infrastructure.

Against the checked-in artifacts every mutating command refuses, and the
refusals are the deliverable. The default role provider is empty - this project
has no authenticated identity - so ``submit``, ``review`` and ``adjudicate``
fail before they reach the state machine, and ``gate-status`` reports which
gates are shut and who owns each. That is not the tool being broken; it is the
tool reporting the state of the science.

**No role self-elevation.** There is no ``--role``, no ``--as``, no
``--reviewer`` and no ``--force``. ``--actor`` names who is acting; what they
may do comes from the role provider. Supplying a role assignment file is
possible with ``--roles``, and it is refused unless every actor in it is
synthetic (``TEST-`` prefixed), because a file that could name a person would
be an authentication system written in JSON.

Deliberately absent, named here so their absence is visible in this file and
not only in a document: approve-protocol, create-rule, validate-rule,
publish-dataset, curate, auto-review, resolve-conflict, and every flag that
would let a caller assert a permission rather than hold one.

Exit codes are stable:

    0  the command answered
    1  refused - a gate, a role, a state or a version said no
    2  configuration failure - a file is missing or malformed
    3  not found - no such work item
"""

from __future__ import annotations

import argparse
import datetime as _dt
import io
import json
import os
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

from pgx.curation.errors import CurationError
from pgx.curation.vocabulary import ConflictState, CurationRole, ProtocolStatus
from pgx.curation.workflow.errors import WorkflowError
from pgx.curation.workflow.forms import (ReadOnlyWorkflowView, handle)
from pgx.curation.workflow.legacy import (LEGACY_VALUE_NAMESPACE,
                                          build_work_items, read_proposals)
from pgx.curation.workflow.memory import (InMemoryWorkflowStore,
                                          InMemoryWorkflowUnitOfWork)
from pgx.curation.workflow.models import (CurationWorkItem,
                                          EvidenceSelectionSnapshot,
                                          ReviewDecision)
from pgx.curation.workflow.policy import GATE_CODES, WorkflowPolicy
from pgx.curation.workflow.roles import (SYNTHETIC_ACTOR_PREFIX, ActorError,
                                         StaticRoleProvider)
from pgx.curation.workflow.service import CurationWorkflowService
from pgx.domain.enums import CurationStatus

__all__ = [
    "EXIT_CONFIGURATION_FAILURE",
    "EXIT_NOT_FOUND",
    "EXIT_OK",
    "EXIT_REFUSED",
    "REFUSED_FLAGS",
    "build_parser",
    "main",
    "refuse_self_elevation",
]

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_CONFIGURATION_FAILURE = 2
EXIT_NOT_FOUND = 3

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

DEFAULT_WORK_ITEMS = os.path.join(_REPO_ROOT, "data", "migration", "wp10",
                                  "legacy-work-items.ndjson")
DEFAULT_PROPOSALS = os.path.join(_REPO_ROOT, "data", "migration", "wp08",
                                 "draft-curation-proposals.ndjson")
DEFAULT_PROTOCOL = os.path.join(_REPO_ROOT, "config", "curation",
                                "protocol-v1.json")


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def _real_policy(protocol_path: str) -> WorkflowPolicy:
    """The policy describing this repository as it actually is.

    Read from the checked-in protocol rather than asserted, so if somebody
    approves the protocol tomorrow this tool notices. Every other input is
    pinned to its blocked value because that is what it is: the evidence build
    is quarantined, and no source policy has human approval.
    """
    document: Dict[str, Any] = {}
    if os.path.isfile(protocol_path):
        with io.open(protocol_path, encoding="utf-8") as handle:
            document = json.load(handle)
    status_name = str(document.get("status") or "DRAFT")
    try:
        status = ProtocolStatus(status_name)
    except ValueError:
        status = ProtocolStatus.DRAFT
    return WorkflowPolicy(
        protocol_status=status,
        protocol_version=str(document.get("protocol_version")
                             or "curation-protocol/1"),
        protocol_content_hash=str(document.get("content_hash")
                                  or ("sha256:" + "0" * 64)),
        protocol_approved_by=document.get("approved_by"),
        evidence_build_quarantined=True,
        evidence_build_lifecycle_labels=("QUARANTINED",
                                         "NOT_PUBLICATION_ELIGIBLE"),
        source_policy_status=None)


def _load_roles(path: Optional[str]) -> StaticRoleProvider:
    """Load role assignments, refusing any that name a non-synthetic actor.

    An empty provider is the default and the production answer. A file may be
    supplied for exercising the workflow, and every actor in it must carry the
    ``TEST-`` prefix: a file that could name a person would be an
    authentication system written in JSON, and this is not one.
    """
    if not path:
        return StaticRoleProvider()
    with io.open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, Mapping):
        raise ValueError("a role file maps actor ids to role names")
    assignments = {}
    for actor_id, roles in raw.items():
        if not str(actor_id).startswith(SYNTHETIC_ACTOR_PREFIX):
            raise ValueError(
                "%r is not a synthetic actor. This tool loads roles only for "
                "ids prefixed %r; assigning a role to a named person is "
                "authentication, which WP-23 owns and this file is not."
                % (actor_id, SYNTHETIC_ACTOR_PREFIX))
        names = [roles] if isinstance(roles, str) else list(roles)
        assignments[actor_id] = frozenset(
            CurationRole(str(name)) for name in names)
    return StaticRoleProvider(assignments)


def _load_store(work_items_path: str) -> InMemoryWorkflowStore:
    store = InMemoryWorkflowStore()
    if not os.path.isfile(work_items_path):
        raise ValueError(
            "no work-item file at %s. Run scripts/build_wp10_migration.py "
            "first." % work_items_path)
    with InMemoryWorkflowUnitOfWork(store) as uow:
        with io.open(work_items_path, encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    continue
                row = json.loads(text)
                uow.work_items.add(CurationWorkItem(
                    work_item_id=row["work_item_id"],
                    status=CurationStatus(row["status"]),
                    version=int(row["version"]),
                    question_id=row["question_id"],
                    gene_canonical_key=row["gene_canonical_key"],
                    drug_canonical_key=row["drug_canonical_key"],
                    created_at=_dt.datetime.fromisoformat(
                        row["created_at"].replace("Z", "+00:00")),
                    created_by=row["created_by"],
                    current_revision_id=row.get("current_revision_id"),
                    submitted_revision_id=row.get("submitted_revision_id"),
                    tags=tuple(row.get("tags") or ()),
                    legacy_proposal_id=row.get("legacy_proposal_id"),
                    legacy_values=dict(row.get("legacy_values") or {})))
        uow.commit()
    return store


def _service(args) -> CurationWorkflowService:
    store = _load_store(args.work_items)
    args._store = store
    return CurationWorkflowService(
        uow_factory=lambda: InMemoryWorkflowUnitOfWork(store),
        role_provider=_load_roles(getattr(args, "roles", None)),
        policy=_real_policy(args.protocol))


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    # allow_abbrev=False is load-bearing, not tidiness. With argparse's
    # default prefix matching, `--role ADJUDICATOR` is accepted as an
    # abbreviation of `--roles` and its value is read as a filename - so a
    # flag this tool deliberately does not have was silently absorbed by one
    # it does. Abbreviation is off everywhere below for the same reason.
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        prog="pgx-curation-workflow",
        description=("Move curation work items, and report why they will not "
                     "move. This tool approves no protocol, creates no rule, "
                     "publishes no dataset, and grants no role."))

    common = argparse.ArgumentParser(add_help=False,
                                     allow_abbrev=False)
    common.add_argument("--text", action="store_true",
                        help="Human-readable output instead of JSON.")
    common.add_argument("--work-items", default=DEFAULT_WORK_ITEMS,
                        help="Work-item NDJSON from the WP-10 migration.")
    common.add_argument("--protocol", default=DEFAULT_PROTOCOL,
                        help="Protocol document, read-only.")
    common.add_argument(
        "--roles", default=None,
        help=("Optional role assignments, synthetic actors only. Omitted, "
              "no actor holds any role, which is this repository's real "
              "state."))

    actor = argparse.ArgumentParser(add_help=False,
                                    allow_abbrev=False)
    actor.add_argument("--actor", required=True,
                       help=("Who is acting. Names the actor; grants nothing. "
                             "Roles come from the provider."))

    imp = _sub(parser, "import-legacy", common,
               "Build RAW work items from the WP-08 proposals and report the "
               "counts. Creates no revision, reviewer or approval.")
    imp.add_argument("--proposals", default=DEFAULT_PROPOSALS)

    listing = _sub(parser, "list", common,
                   "List work items by state. Read-only.")
    listing.add_argument("--status", default=None,
                         help="RAW, UNDER_REVIEW, CURATED or REJECTED.")
    listing.add_argument("--limit", type=int, default=20,
                         help="0 prints all.")

    show = _sub(parser, "show", common, "Print one work item. Read-only.")
    show.add_argument("work_item_id")

    history = _sub(parser, "history", common,
                   "Every revision, review and adjudication for one work "
                   "item, including superseded ones. Read-only.")
    history.add_argument("work_item_id")

    gates = _sub(parser, "gate-status", common,
                 "Evaluate the thirteen approval gates without attempting "
                 "anything. Read-only.")
    gates.add_argument("work_item_id")
    gates.add_argument("--reviewer", default=None,
                       help="Evaluate as if this actor were reviewing.")

    draft = _sub(parser, "validate-draft", common,
                 "Check a draft revision payload against the protocol. "
                 "Reports; curates nothing.")
    draft.add_argument("work_item_id")
    draft.add_argument("--payload", required=True,
                       help="JSON file holding the draft payload.")

    form = _sub(parser, "render-form", common,
                "Render one console page to stdout. Read-only; starts no "
                "server and listens on nothing.")
    form.add_argument("route", choices=("list", "detail", "editor",
                                        "evidence", "review-form", "history"))
    form.add_argument("--work-item", default=None)
    form.add_argument("--reviewer", default=None)

    submit = _sub(parser, "submit", common,
                  "Submit a revision for independent review.", [actor])
    submit.add_argument("work_item_id")
    submit.add_argument("--revision", required=True)
    submit.add_argument("--expected-version", type=int, required=True)

    review = _sub(parser, "review", common,
                  "Record one independent review decision.", [actor])
    review.add_argument("work_item_id")
    review.add_argument("--revision", required=True)
    review.add_argument("--expected-version", type=int, required=True)
    review.add_argument("--decision", required=True,
                        choices=[d.value for d in ReviewDecision])
    review.add_argument("--rationale", required=True)

    adjudicate = _sub(parser, "adjudicate", common,
                      "Settle a referred dispute, preserving both positions.",
                      [actor])
    adjudicate.add_argument("work_item_id")
    adjudicate.add_argument("--revision", required=True)
    adjudicate.add_argument("--expected-version", type=int, required=True)
    adjudicate.add_argument("--decision", required=True,
                            choices=["APPROVE", "REQUEST_CHANGES", "REJECT"])
    adjudicate.add_argument("--rationale", required=True)
    adjudicate.add_argument("--curator-position", required=True,
                            help="JSON file holding the curator's position.")
    adjudicate.add_argument("--reviewer-position", required=True,
                            help="JSON file holding the reviewer's position.")

    # Deliberately absent, named so their absence is visible here and not only
    # in a document: --role, --as, --reviewer-role, --force, --skip-gates,
    # approve-protocol, create-rule, validate-rule, publish-dataset, curate,
    # auto-review and resolve-conflict.
    return parser


def _sub(parser, name, common, help_text, extra=()):
    group = getattr(parser, "_pgx_subparsers", None)
    if group is None:
        group = parser.add_subparsers(dest="command", required=True)
        setattr(parser, "_pgx_subparsers", group)
    return group.add_parser(name, parents=[common] + list(extra),
                            allow_abbrev=False, help=help_text)


#: Flags a caller might reach for to assert a permission. None of them exists,
#: and each is refused by name so the message explains why rather than leaving
#: argparse to say "unrecognized arguments" about a flag whose absence is the
#: whole point.
REFUSED_FLAGS: Mapping[str, str] = {
    "--role": "roles come from the injected provider, never from the caller",
    "--as": "there is no acting-as; --actor names you, it does not elevate you",
    "--as-role": "roles come from the injected provider",
    "--reviewer-role": "a reviewer's role is looked up, not declared",
    "--grant": "this tool grants nothing; WP-23 owns identity",
    "--force": "there is no override for a closed gate",
    "--skip-gates": "there is no override for a closed gate",
    "--approve": "approval is an act recorded by `review`, not a flag",
}


def refuse_self_elevation(argv: Sequence[str]) -> Optional[str]:
    """Return an explanation if the arguments try to assert a permission."""
    for argument in argv:
        flag = argument.split("=", 1)[0]
        if flag in REFUSED_FLAGS:
            return ("%s is not a flag this tool has: %s."
                    % (flag, REFUSED_FLAGS[flag]))
    return None


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point."""
    supplied = list(sys.argv[1:] if argv is None else argv)
    refusal = refuse_self_elevation(supplied)
    if refusal:
        sys.stdout.write(json.dumps(
            {"refused": True, "code": "RoleViolationError",
             "detail": refusal}, indent=2, sort_keys=True) + "\n")
        return EXIT_REFUSED

    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "import-legacy": _cmd_import_legacy,
        "list": _cmd_list,
        "show": _cmd_show,
        "history": _cmd_history,
        "gate-status": _cmd_gate_status,
        "validate-draft": _cmd_validate_draft,
        "render-form": _cmd_render_form,
        "submit": _cmd_submit,
        "review": _cmd_review,
        "adjudicate": _cmd_adjudicate,
    }
    try:
        return handlers[args.command](args)
    except (WorkflowError, CurationError, ActorError) as exc:
        _emit(args, _refusal(exc), "REFUSED: %s" % exc)
        return EXIT_REFUSED
    except (OSError, ValueError, KeyError) as exc:
        _emit(args, {"error": str(exc), "code": "CONFIGURATION_FAILURE"},
              "CONFIGURATION_FAILURE: %s" % exc)
        return EXIT_CONFIGURATION_FAILURE


def _refusal(exc: Exception) -> Dict[str, Any]:
    """A refusal as structured data, not only prose.

    A caller that has to parse an error message to find out which gate is shut
    will get it wrong; the codes are what a script should branch on.
    """
    payload: Dict[str, Any] = {
        "refused": True,
        "code": type(exc).__name__,
        "detail": str(exc),
    }
    codes = getattr(exc, "codes", None)
    if codes:
        payload["gate_codes"] = sorted(codes)
        payload["blockers"] = [
            {"code": code,
             "requirement": GATE_CODES.get(code, {}).get("requirement", ""),
             "owner": GATE_CODES.get(code, {}).get("owner", "")}
            for code in sorted(codes)]
    for attribute in ("expected_version", "actual_version", "expected_status",
                      "actual_status", "current", "requested", "missing",
                      "violations"):
        value = getattr(exc, attribute, None)
        if value is not None:
            payload[attribute] = list(value) if isinstance(
                value, tuple) else value
    return payload


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def _cmd_import_legacy(args) -> int:
    report = build_work_items(
        read_proposals(args.proposals),
        imported_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc),
        imported_by="pgx-curation-workflow/import-legacy")
    counts = report.counts()
    payload = {
        "counts": counts,
        "legacy_value_namespace": LEGACY_VALUE_NAMESPACE,
        "issue_count": len(report.issues),
        "note": ("Every imported work item is RAW. No revision, reviewer, "
                 "approval or CuratedInterpretation was created, and the "
                 "legacy values travel as unreviewed input."),
    }
    lines = ["%d work items, all %s" % (counts["work_items"],
                                        ", ".join(counts["by_status"]))]
    lines.append("%d linked to evidence, %d unlinked and reported"
                 % (counts["linked_work_items"], counts["unlinked_work_items"]))
    lines.append("revisions %d, reviewers %d, approvals %d, curated "
                 "interpretations %d"
                 % (counts["revisions"], counts["reviewers"],
                    counts["approvals"], counts["curated_interpretations"]))
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK


def _cmd_list(args) -> int:
    service = _service(args)
    store = args._store
    items = sorted(store.work_items.values(),
                   key=lambda item: item.work_item_id)
    if args.status:
        items = [item for item in items if item.status.value == args.status]
    total = len(items)
    if args.limit:
        items = items[:args.limit]
    counts: Dict[str, int] = {}
    for item in store.work_items.values():
        counts[item.status.value] = counts.get(item.status.value, 0) + 1
    payload = {
        "total": total,
        "shown": len(items),
        "counts_by_status": counts,
        "work_items": [item.to_json() for item in items],
    }
    lines = ["%d work item(s)%s" % (total, "" if not args.status
                                    else " in %s" % args.status)]
    lines.extend("%s  %-12s v%-3d %s / %s"
                 % (item.work_item_id, item.status.value, item.version,
                    item.gene_canonical_key, item.drug_canonical_key)
                 for item in items)
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK


def _cmd_show(args) -> int:
    service = _service(args)
    item = args._store.work_items.get(args.work_item_id)
    if item is None:
        _emit(args, {"error": "no work item %s" % args.work_item_id,
                     "code": "NOT_FOUND"},
              "NOT_FOUND: no work item %s" % args.work_item_id)
        return EXIT_NOT_FOUND
    payload = item.to_json()
    lines = ["%s  %s  v%d" % (item.work_item_id, item.status.value,
                              item.version),
             "%s / %s" % (item.gene_canonical_key, item.drug_canonical_key),
             "tags: %s" % (", ".join(item.tags) or "none")]
    if item.legacy_values:
        lines.append("legacy input (unreviewed):")
        lines.extend("  %s = %s" % (key, item.legacy_values[key])
                     for key in sorted(item.legacy_values))
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK


def _cmd_history(args) -> int:
    service = _service(args)
    if args.work_item_id not in args._store.work_items:
        _emit(args, {"error": "no work item %s" % args.work_item_id,
                     "code": "NOT_FOUND"},
              "NOT_FOUND: no work item %s" % args.work_item_id)
        return EXIT_NOT_FOUND
    payload = service.history(args.work_item_id)
    lines = ["%d revision(s), %d review(s)"
             % (payload["revision_count"], payload["review_count"])]
    for review in payload["reviews"]:
        lines.append("  %s by %s: %s" % (review["decision"],
                                         review["reviewed_by"],
                                         review["rationale"][:60]))
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK


def _cmd_gate_status(args) -> int:
    service = _service(args)
    if args.work_item_id not in args._store.work_items:
        _emit(args, {"error": "no work item %s" % args.work_item_id,
                     "code": "NOT_FOUND"},
              "NOT_FOUND: no work item %s" % args.work_item_id)
        return EXIT_NOT_FOUND
    payload = service.gate_status(work_item_id=args.work_item_id,
                                  reviewer_actor_id=args.reviewer)
    if payload.get("gates") is None:
        # Structured, not only prose: a script branching on "can this be
        # approved" must not have to parse a sentence. A work item with no
        # revision cannot be approved, so this is a refusal, not an answer of
        # "yes".
        payload["blockers"] = [{
            "code": "GATE_NO_REVISION",
            "detail": payload["blocked_reason"],
            "owner": "scientific curator",
        }]
        payload["passed"] = False
        _emit(args, payload, payload["blocked_reason"])
        return EXIT_REFUSED
    shut = [gate for gate in payload["gates"] if not gate["passed"]]
    payload["blockers"] = [
        {"code": gate["code"], "detail": gate["detail"],
         "owner": GATE_CODES.get(gate["code"], {}).get("owner", "")}
        for gate in shut]
    lines = ["%s: %d of %d gates shut"
             % (args.work_item_id, len(shut), len(payload["gates"]))]
    lines.extend("  %-38s %s  [%s]"
                 % (gate["code"], gate["detail"],
                    GATE_CODES.get(gate["code"], {}).get("owner", ""))
                 for gate in shut)
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK if not shut else EXIT_REFUSED


def _cmd_validate_draft(args) -> int:
    """Check a draft payload against WP-09's rules without curating anything.

    Two checks, both of which a curator can fix themselves: no field the
    evidence store refuses may appear in a curation payload, and no reassuring
    language may describe a conclusion that does not support reassurance. Both
    come from WP-09 and are reported here rather than re-implemented.
    """
    from pgx.curation.models import (find_prohibited_curation_fields,
                                     find_reassuring_language)

    service = _service(args)
    item = args._store.work_items.get(args.work_item_id)
    if item is None:
        _emit(args, {"error": "no work item %s" % args.work_item_id,
                     "code": "NOT_FOUND"},
              "NOT_FOUND: no work item %s" % args.work_item_id)
        return EXIT_NOT_FOUND
    with io.open(args.payload, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError("a draft payload is a JSON object")

    prohibited = find_prohibited_curation_fields(payload)
    reassuring: List[Dict[str, Any]] = []
    conclusion = str(payload.get("conclusion_state") or "").upper()
    if conclusion in ("INSUFFICIENT", "CONFLICTING"):
        for key, value in sorted(payload.items()):
            if not isinstance(value, str):
                continue
            terms = find_reassuring_language(value)
            if terms:
                reassuring.append({"field": key, "terms": list(terms)})

    findings = (
        [{"code": "CUR_PROHIBITED_FIELD", "field": name,
          "detail": ("%s is refused by the evidence store; a curation payload "
                     "carrying it would reintroduce what WP-08 removed" % name)}
         for name in prohibited]
        + [{"code": "CUR_REASSURING_LANGUAGE", "field": entry["field"],
            "detail": ("%s describes a %s conclusion with reassuring terms "
                       "(%s); missing or conflicting evidence is not a "
                       "low-risk finding"
                       % (entry["field"], conclusion,
                          ", ".join(entry["terms"])))}
           for entry in reassuring])

    result = {
        "work_item_id": args.work_item_id,
        "conclusion_state": conclusion or None,
        "finding_count": len(findings),
        "findings": findings,
        "note": ("A draft with no findings is well formed. It is not "
                 "approved, and this command approves nothing."),
    }
    lines = ["%d finding(s)" % len(findings)]
    lines.extend("  %s: %s" % (item["code"], item["detail"])
                 for item in findings)
    _emit(args, result, "\n".join(lines))
    return EXIT_OK if not findings else EXIT_REFUSED


def _cmd_render_form(args) -> int:
    service = _service(args)
    params: Dict[str, Any] = {"reviewer_actor_id": args.reviewer}
    if args.route == "list":
        items = sorted(args._store.work_items.values(),
                       key=lambda item: item.work_item_id)[:50]
        params["items"] = [item.to_json() for item in items]
    else:
        if not args.work_item:
            raise ValueError("--work-item is required for route %s"
                             % args.route)
        if args.work_item not in args._store.work_items:
            _emit(args, {"error": "no work item %s" % args.work_item,
                         "code": "NOT_FOUND"},
                  "NOT_FOUND: no work item %s" % args.work_item)
            return EXIT_NOT_FOUND
        params["work_item_id"] = args.work_item
    response = handle(args.route, {"method": "GET", "params": params},
                      service=service,
                      read_view=ReadOnlyWorkflowView(service))
    sys.stdout.write(response.body)
    return EXIT_OK if response.status == 200 else EXIT_REFUSED


def _cmd_submit(args) -> int:
    service = _service(args)
    result = service.submit(actor_id=args.actor,
                            work_item_id=args.work_item_id,
                            revision_id=args.revision,
                            expected_version=args.expected_version)
    _emit(args, result.to_json(),
          "%s -> %s v%d" % (args.work_item_id,
                            result.work_item.status.value,
                            result.work_item.version))
    return EXIT_OK


def _cmd_review(args) -> int:
    service = _service(args)
    result = service.review(actor_id=args.actor,
                            work_item_id=args.work_item_id,
                            revision_id=args.revision,
                            expected_version=args.expected_version,
                            decision=ReviewDecision(args.decision),
                            rationale=args.rationale)
    _emit(args, result.to_json(),
          "%s -> %s v%d" % (args.work_item_id,
                            result.work_item.status.value,
                            result.work_item.version))
    return EXIT_OK


def _cmd_adjudicate(args) -> int:
    service = _service(args)
    with io.open(args.curator_position, encoding="utf-8") as handle:
        curator = json.load(handle)
    with io.open(args.reviewer_position, encoding="utf-8") as handle:
        reviewer = json.load(handle)
    result = service.adjudicate(actor_id=args.actor,
                                work_item_id=args.work_item_id,
                                revision_id=args.revision,
                                expected_version=args.expected_version,
                                decision=ReviewDecision(args.decision),
                                rationale=args.rationale,
                                curator_position=curator,
                                reviewer_position=reviewer)
    _emit(args, result.to_json(),
          "%s -> %s v%d" % (args.work_item_id,
                            result.work_item.status.value,
                            result.work_item.version))
    return EXIT_OK


def _emit(args, payload: Mapping[str, Any], text: str) -> None:
    if getattr(args, "text", False):
        sys.stdout.write(text.rstrip("\n") + "\n")
    else:
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True,
                                    ensure_ascii=False, default=str) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
