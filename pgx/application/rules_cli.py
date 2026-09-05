# -*- coding: utf-8 -*-
"""Offline CLI for the rule and ruleset layer (WP-11).

    python3 -m pgx.application.rules_cli gate-status --text

A thin shell over the application services. Every state-changing command goes
through a service, which resolves roles through the injected provider, checks
policy, runs the validator and writes an audit event; nothing here reaches a
repository directly.

Against this repository every mutating command refuses, and the refusal is the
deliverable: the production role assignment set is empty, so no actor holds a
role, and no rule can be drafted, curated, validated or frozen.

Deliberately absent, named here so their absence is visible in this file rather
than only in a document: ``approve-rule``, ``force-freeze``, ``promote-legacy``,
``assign-role``, ``ignore-evidence``, ``skip-validation``, and every flag that
would let a caller assert a permission rather than hold one.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import io
import json
import os
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

from pgx.application.rule_gate_status import (BLOCKER_CODES, build_gate_status,
                                              build_real_build_attempt)
from pgx.curation.workflow.errors import ActorError, RoleViolationError
from pgx.curation.workflow.roles import SYNTHETIC_ACTOR_PREFIX, StaticRoleProvider
from pgx.rules.conflicts import CONFLICT_KINDS, detect_conflicts
from pgx.rules.errors import (ArtifactIntegrityError, ConditionGrammarError,
                              RegistryLoadError, RuleError, RuleValidationError)
from pgx.rules.legacy import build_inventory
from pgx.rules.registry import DEFAULT_RULESET_ROOT, FrozenRulesetRegistry
from pgx.rules.schema import parse_rule_document, rule_document_issues
from pgx.rules.serialization import verify_checksums
from pgx.rules.validator import ISSUE_CODES

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

#: Flags a caller might reach for to assert a permission or bypass a gate. None
#: of them exists, and each is refused by name so the message explains why
#: rather than leaving argparse to say "unrecognized arguments" about a flag
#: whose absence is the whole point.
REFUSED_FLAGS: Mapping[str, str] = {
    "--role": "roles come from the injected provider, never from the caller",
    "--as": "there is no acting-as; --actor names you, it does not elevate you",
    "--grant": "this tool grants nothing; WP-23 owns identity",
    "--force": "there is no override for a failed validation",
    "--force-freeze": "a ruleset is frozen by validating and building, not by "
                      "asserting it",
    "--skip-validation": "there is no route around validation",
    "--ignore-evidence": "evidence errors are not ignorable (SAFETY-INV-006)",
    "--promote-legacy": "legacy rows are inventoried, never promoted",
    "--approve": "approval is an act by named people recorded in WP-10, not a "
                 "flag",
}


def refuse_self_elevation(argv: Sequence[str]) -> Optional[str]:
    for argument in argv:
        flag = argument.split("=", 1)[0]
        if flag in REFUSED_FLAGS:
            return "%s is not a flag this tool has: %s." % (flag, REFUSED_FLAGS[flag])
    return None


def build_parser() -> argparse.ArgumentParser:
    # allow_abbrev=False: with argparse's default prefix matching, `--role`
    # would be accepted as an abbreviation of a longer flag and silently
    # absorbed. Abbreviation is off everywhere for that reason.
    parser = argparse.ArgumentParser(
        allow_abbrev=False, prog="pgx-rules",
        description=("Inspect, validate and build governed computable rules. "
                     "This tool approves nothing, promotes no legacy row, and "
                     "creates no rule from a CSV."))

    common = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    common.add_argument("--text", action="store_true",
                        help="Human-readable output instead of JSON.")
    common.add_argument("--repo-root", default=_REPO_ROOT)

    inspect = _sub(parser, "inspect-rule", common,
                   "Print one rule document from a file. Read-only.")
    inspect.add_argument("path")

    validate = _sub(parser, "validate-rule", common,
                    "Structurally validate one rule document. Reports every "
                    "issue; validates nothing into existence.")
    validate.add_argument("path")

    issues = _sub(parser, "list-issue-codes", common,
                  "Print every validation issue code, its layer and meaning.")

    conflicts = _sub(parser, "detect-conflicts", common,
                     "Classify duplicates, overlaps and conflicting outcomes "
                     "across a set of rule documents. Resolves nothing.")
    conflicts.add_argument("paths", nargs="+")

    inspect_rs = _sub(parser, "inspect-ruleset", common,
                      "Print a frozen ruleset artifact's manifest. Read-only.")
    inspect_rs.add_argument("directory")

    verify = _sub(parser, "verify-ruleset", common,
                  "Verify a frozen ruleset artifact: checksums, manifest, "
                  "members, approval list.")
    verify.add_argument("directory")

    listing = _sub(parser, "list-executable", common,
                   "List the frozen rulesets the engine-facing registry can "
                   "serve.")
    listing.add_argument("--root", default=DEFAULT_RULESET_ROOT)

    _sub(parser, "gate-status", common,
         "Report whether real rule creation is possible, and what blocks it.")

    _sub(parser, "build-attempt", common,
         "Attempt a real ruleset build and report where it stopped.")

    inventory = _sub(parser, "legacy-inventory", common,
                     "Report the legacy rule-candidate inventory. Promotes "
                     "nothing.")
    inventory.add_argument("--verify", action="store_true",
                           help="Regenerate and compare against the file on "
                                "disk instead of printing counts.")

    # Deliberately absent: approve-rule, force-freeze, promote-legacy,
    # assign-role, create-rule-from-csv, skip-validation.
    return parser


def _sub(parser, name, common, help_text, extra=()):
    group = getattr(parser, "_pgx_subparsers", None)
    if group is None:
        group = parser.add_subparsers(dest="command", required=True)
        setattr(parser, "_pgx_subparsers", group)
    return group.add_parser(name, parents=[common] + list(extra),
                            allow_abbrev=False, help=help_text)


def main(argv: Optional[List[str]] = None) -> int:
    supplied = list(sys.argv[1:] if argv is None else argv)
    refusal = refuse_self_elevation(supplied)
    if refusal:
        sys.stdout.write(json.dumps(
            {"refused": True, "code": "RoleViolationError", "detail": refusal},
            indent=2, sort_keys=True) + "\n")
        return EXIT_REFUSED

    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "inspect-rule": _cmd_inspect_rule,
        "validate-rule": _cmd_validate_rule,
        "list-issue-codes": _cmd_list_issue_codes,
        "detect-conflicts": _cmd_detect_conflicts,
        "inspect-ruleset": _cmd_inspect_ruleset,
        "verify-ruleset": _cmd_verify_ruleset,
        "list-executable": _cmd_list_executable,
        "gate-status": _cmd_gate_status,
        "build-attempt": _cmd_build_attempt,
        "legacy-inventory": _cmd_legacy_inventory,
    }
    try:
        return handlers[args.command](args)
    except (RuleError, ActorError, RoleViolationError) as exc:
        _emit(args, _refusal(exc), "REFUSED: %s" % exc)
        return EXIT_REFUSED
    except (OSError, ValueError, KeyError) as exc:
        _emit(args, {"error": str(exc), "code": "CONFIGURATION_FAILURE"},
              "CONFIGURATION_FAILURE: %s" % exc)
        return EXIT_CONFIGURATION_FAILURE


def _refusal(exc: Exception) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"refused": True, "code": type(exc).__name__,
                               "detail": str(exc)}
    issues = getattr(exc, "issues", None)
    if issues:
        payload["issues"] = [item.to_json() if hasattr(item, "to_json") else item
                             for item in issues]
    for attribute in ("code", "location", "current", "requested"):
        value = getattr(exc, attribute, None)
        if value is not None and attribute != "code":
            payload[attribute] = value
    return payload


# -- commands ---------------------------------------------------------------

def _load_document(path: str) -> Dict[str, Any]:
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _cmd_inspect_rule(args) -> int:
    payload = _load_document(args.path)
    definition = parse_rule_document(payload)
    result = definition.to_json()
    lines = ["%s v%d  %s" % (definition.rule_id, definition.rule_version,
                             definition.condition),
             "outcome: %s" % definition.outcome.attention_level.value,
             "content hash: %s" % definition.content_hash(),
             "evidence: %d record(s)"
             % len(definition.provenance.evidence_record_uuids)]
    _emit(args, result, "\n".join(lines))
    return EXIT_OK


def _cmd_validate_rule(args) -> int:
    payload = _load_document(args.path)
    issues = rule_document_issues(payload)
    result = {"path": args.path, "issue_count": len(issues),
              "passed": not issues, "issues": list(issues),
              "note": ("Structural validation only. Reaching VALIDATED "
                       "additionally requires an approval envelope, a CURATED "
                       "interpretation and resolvable evidence, none of which "
                       "a file on disk can supply.")}
    lines = ["%d structural issue(s)" % len(issues)]
    lines.extend("  %-34s %s" % (item["code"], item["message"][:80])
                 for item in issues)
    _emit(args, result, "\n".join(lines))
    return EXIT_OK if not issues else EXIT_REFUSED


def _cmd_list_issue_codes(args) -> int:
    result = {"issue_codes": {code: dict(entry)
                              for code, entry in sorted(ISSUE_CODES.items())},
              "conflict_kinds": {kind: dict(entry)
                                 for kind, entry in sorted(CONFLICT_KINDS.items())}}
    lines = ["%d validation issue codes" % len(ISSUE_CODES)]
    lines.extend("  %-38s [%s] %s" % (code, entry["layer"], entry["meaning"])
                 for code, entry in sorted(ISSUE_CODES.items()))
    lines.append("%d conflict kinds" % len(CONFLICT_KINDS))
    lines.extend("  %-28s %s" % (kind, entry["meaning"])
                 for kind, entry in sorted(CONFLICT_KINDS.items()))
    _emit(args, result, "\n".join(lines))
    return EXIT_OK


def _cmd_detect_conflicts(args) -> int:
    definitions = [parse_rule_document(_load_document(path))
                   for path in args.paths]
    report = detect_conflicts(definitions)
    lines = ["%d finding(s), %d blocking"
             % (len(report.findings), len(report.blocking))]
    lines.extend("  %-22s %s" % (finding.kind, finding.detail[:80])
                 for finding in report.findings)
    _emit(args, report.to_json(), "\n".join(lines))
    return EXIT_OK if report.clean else EXIT_REFUSED


def _cmd_inspect_ruleset(args) -> int:
    from pgx.rules.registry import load_frozen_ruleset
    ruleset = load_frozen_ruleset(args.directory)
    payload = ruleset.manifest.to_json()
    lines = ["%s  %d member(s)" % (ruleset.public_id, ruleset.member_count),
             "manifest hash: %s" % ruleset.manifest.content_hash(),
             "ruleset hash:  %s" % ruleset.ruleset_content_hash,
             "structural axes: %d (membership inventory, not coverage)"
             % len(ruleset.manifest.structural_axes)]
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK


def _cmd_verify_ruleset(args) -> int:
    from pgx.rules.registry import load_frozen_ruleset
    checksums = verify_checksums(args.directory)
    ruleset = load_frozen_ruleset(args.directory)
    payload = {"directory": args.directory, "verified": True,
               "public_id": ruleset.public_id.to_json(),
               "member_count": ruleset.member_count,
               "manifest_hash": ruleset.manifest.content_hash(),
               "ruleset_content_hash": ruleset.ruleset_content_hash,
               "files": checksums}
    lines = ["verified %s" % args.directory,
             "  %d file(s), %d member(s)" % (len(checksums), ruleset.member_count),
             "  ruleset hash %s" % ruleset.ruleset_content_hash]
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK


def _cmd_list_executable(args) -> int:
    registry = FrozenRulesetRegistry(root=args.root)
    executable = list(registry.list_executable())
    payload = {"root": args.root, "executable_rulesets": executable,
               "count": len(executable),
               "note": ("Only fully verified FROZEN rulesets appear here. A "
                        "BUILDING or merely VALIDATED ruleset is not "
                        "executable, and an artifact that does not verify is "
                        "absent rather than present-and-broken.")}
    lines = ["%d executable ruleset(s) under %s" % (len(executable), args.root)]
    lines.extend("  %s" % item for item in executable)
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK


def _cmd_gate_status(args) -> int:
    report = build_gate_status(args.repo_root)
    payload = report.to_json()
    lines = [payload["assessment"], ""]
    lines.append("%d blocker(s):" % len(payload["blockers"]))
    for entry in payload["blockers"]:
        lines.append("  %-34s %s" % (entry["code"], entry["detail"]))
        lines.append("      owner: %s" % entry["owner"])
    lines.append("")
    lines.append("real rules: %d validated, %d frozen rulesets"
                 % (payload["rule_state"]["real_validated_rules"],
                    payload["rule_state"]["real_frozen_rulesets"]))
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK if not payload["blockers"] else EXIT_REFUSED


def _cmd_build_attempt(args) -> int:
    report = build_real_build_attempt(args.repo_root)
    payload = report.to_json()
    lines = ["%s -> %s (stopped at %s)"
             % (payload["attempt"], payload["outcome"], payload["stopped_at"])]
    for step in payload["steps"]:
        lines.append("  %-52s %s" % (step["step"], step["result"]))
    _emit(args, payload, "\n".join(lines))
    return EXIT_REFUSED


def _cmd_legacy_inventory(args) -> int:
    inventory = build_inventory(args.repo_root)
    generated = inventory.to_json()
    path = os.path.join(args.repo_root, "data", "migration", "wp11",
                        "legacy-rule-candidate-inventory.json")
    if args.verify:
        if not os.path.isfile(path):
            _emit(args, {"error": "no inventory at %s" % path,
                         "code": "NOT_FOUND"}, "NOT_FOUND: %s" % path)
            return EXIT_NOT_FOUND
        with io.open(path, encoding="utf-8") as handle:
            stored = json.load(handle)
        matches = stored.get("content_hash") == generated["content_hash"]
        payload = {"path": path, "matches": matches,
                   "stored_hash": stored.get("content_hash"),
                   "regenerated_hash": generated["content_hash"]}
        _emit(args, payload,
              "inventory %s" % ("matches" if matches
                                else "DIFFERS from the regenerated content"))
        return EXIT_OK if matches else EXIT_REFUSED

    counts = generated["counts"]
    lines = ["%d legacy rule candidates" % counts["candidates"],
             "  %d linked, %d unlinked" % (counts["linked"], counts["unlinked"]),
             "  eligible for rule creation: %d"
             % counts["eligible_for_rule_creation"],
             "  rules created: %d, validated: %d, frozen rulesets: %d"
             % (counts["rules_created"], counts["validated_rules"],
                counts["frozen_rulesets"]),
             "blockers:"]
    lines.extend("  %-38s %d" % (code, count)
                 for code, count in sorted(counts["by_blocker_code"].items()))
    _emit(args, generated, "\n".join(lines))
    return EXIT_OK


def _emit(args, payload: Mapping[str, Any], text: str) -> None:
    if getattr(args, "text", False):
        sys.stdout.write(text.rstrip("\n") + "\n")
    else:
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True,
                                    ensure_ascii=False, default=str) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
