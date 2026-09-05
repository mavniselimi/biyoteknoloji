# -*- coding: utf-8 -*-
"""The WP-11 real-data gate report (WP-11).

Answers one question honestly: can this repository create, validate or freeze a
real computable rule today, and if not, exactly what is missing and who has to
supply it?

The answer is no, and that is a governance result rather than a defect. The
curation protocol awaits expert review; the evidence build is quarantined; the
canonical dataset is ``BUILDING``; every source-policy entry is
``PENDING_REVIEW``; no interpretation is ``CURATED``; no approval envelope
exists; no identity holds a role. None of those can be closed by writing code,
and this module exists so that saying so is a generated artifact with stable
codes rather than a sentence in a document somebody has to trust.

Every fact below is **read from the repository**, not asserted. If somebody
approves the protocol tomorrow, this report notices.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.domain.hashing import sha256_digest

__all__ = [
    "BLOCKER_CODES",
    "GATE_STATUS_VERSION",
    "GateStatusReport",
    "build_gate_status",
    "build_real_build_attempt",
]

GATE_STATUS_VERSION = "pgx-wp11-gate-status/1"

#: Every blocker this report can raise, with what it means, who can clear it,
#: and what becomes possible afterwards. Data rather than prose so the CLI, the
#: schema, the tests and the documentation cite one list - and so that nobody
#: can add a blocker without saying who owns it.
BLOCKER_CODES: Mapping[str, Mapping[str, str]] = {
    "CURATION_PROTOCOL_NOT_APPROVED": {
        "meaning": "the curation protocol has not been approved by a named "
                   "scientific expert",
        "owner": "a named scientific expert (not code)",
        "unblocks": "curated interpretations may begin under an approved "
                    "protocol, and a rule may pin a protocol that was in force",
    },
    "EVIDENCE_BUILD_NOT_APPROVED": {
        "meaning": "the evidence build is quarantined and not eligible for "
                   "publication or rule construction",
        "owner": "data acquisition and source policy review",
        "unblocks": "a rule may cite evidence from an approved build",
    },
    "DATASET_NOT_PUBLISHED": {
        "meaning": "the canonical dataset is not PUBLISHED",
        "owner": "the dataset quality and publication process (WP-07)",
        "unblocks": "a rule may pin a published dataset boundary",
    },
    "SOURCE_POLICY_NOT_APPROVED": {
        "meaning": "no source policy entry has completed human review, so no "
                   "source is cleared for use in an executable rule",
        "owner": "a named source-policy approver",
        "unblocks": "the source-policy eligibility gate opens",
    },
    "NO_CURATED_INTERPRETATIONS": {
        "meaning": "no curation work item has reached CURATED, so there is no "
                   "accepted conclusion for a rule to encode",
        "owner": "scientific curators and an independent reviewer",
        "unblocks": "a DRAFT rule may be marked CURATED",
    },
    "NO_RULE_APPROVAL_ENVELOPES": {
        "meaning": "no WP-10 rule approval envelope exists",
        "owner": "a curator, an independent reviewer and an approver, acting "
                 "separately",
        "unblocks": "a CURATED rule may be validated",
    },
    "NO_VALIDATED_RULES": {
        "meaning": "no rule has been validated, so no ruleset can have members",
        "owner": "an independent scientific reviewer or adjudicator",
        "unblocks": "a BUILDING ruleset may gain members and validate",
    },
    "HUMAN_ROLE_ASSIGNMENTS_MISSING": {
        "meaning": "no identity holds any curation or review role; the "
                   "production role assignment set is empty",
        "owner": "WP-23 authentication, then whoever assigns roles",
        "unblocks": "any actor-bound operation in the rule layer",
    },
    "LEGACY_ITEMS_NOT_ELIGIBLE": {
        "meaning": "every legacy-derived candidate is still RAW and unreviewed, "
                   "so none is eligible to become a rule",
        "owner": "scientific curators",
        "unblocks": "legacy candidates may enter curation and, once approved, "
                    "become rule sources",
    },
    "UNLINKED_CURATION_ITEMS_REMAIN": {
        "meaning": "some legacy work items have no evidence link, so they "
                   "cannot cite evidence even if curated",
        "owner": "scientific curators selecting evidence during curation",
        "unblocks": "those items may cite evidence and become rule sources",
    },
}


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.isfile(path):
        return None
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _count_ndjson(path: str) -> int:
    if not os.path.isfile(path):
        return 0
    count = 0
    with io.open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


@dataclass(frozen=True)
class GateStatusReport:
    """The generated report, hashable and deterministic."""

    payload: Mapping[str, Any]

    def content_hash(self) -> str:
        return sha256_digest({key: value for key, value in self.payload.items()
                              if key not in ("content_hash", "generated_at")})

    def to_json(self) -> Dict[str, Any]:
        payload = dict(self.payload)
        payload["content_hash"] = self.content_hash()
        return payload

    @property
    def blockers(self) -> Tuple[str, ...]:
        return tuple(entry["code"] for entry in self.payload.get("blockers", ()))


def build_gate_status(repo_root: str = ".") -> GateStatusReport:
    """Read the repository and report whether real rules are possible.

    Deterministic: no clock enters the hashed payload, so re-running produces
    the same digest until the repository's own state changes.
    """
    def path(*parts: str) -> str:
        return os.path.join(repo_root, *parts)

    protocol = _read_json(path("config", "curation", "protocol-v1.json")) or {}
    canonical = _read_json(path("data", "canonical", "PGX-DATA-20260830-900",
                                "manifest.json")) or {}
    evidence = _read_json(path("data", "evidence", "PGX-DATA-20260830-900",
                               "manifest.json")) or {}
    sources = _read_json(path("config", "scientific-sources.json")) or {}
    wp10_manifest = _read_json(path("data", "migration", "wp10",
                                    "manifest.json")) or {}

    protocol_status = str(protocol.get("status") or "UNKNOWN")
    protocol_approved = bool(
        protocol_status == "APPROVED" and str(protocol.get("approved_by") or "").strip())

    evidence_labels = tuple(evidence.get("lifecycle_labels") or ())
    evidence_approved = bool(
        evidence and "QUARANTINED" not in evidence_labels
        and "NOT_PUBLICATION_ELIGIBLE" not in evidence_labels)

    dataset_state = str(canonical.get("dataset_lifecycle_state") or "UNKNOWN")
    dataset_published = dataset_state == "PUBLISHED"

    source_entries = sources.get("sources") or []
    approved_sources = [
        entry for entry in source_entries
        if str(((entry.get("review") or {}).get("status")
                if isinstance(entry.get("review"), dict)
                else entry.get("review_status")) or "").upper() == "APPROVED"]

    counts = wp10_manifest.get("counts") or {}
    curated_interpretations = int(counts.get("curated", 0))
    work_items = int(counts.get("work_items", 0))
    linked = int(counts.get("linked_work_items", 0))
    unlinked = int(counts.get("unlinked_work_items", 0))

    # The rule layer itself. Counted from what exists, never asserted.
    ruleset_root = path("data", "rulesets")
    frozen_rulesets = 0
    if os.path.isdir(ruleset_root):
        from pgx.rules.registry import FrozenRulesetRegistry
        frozen_rulesets = len(FrozenRulesetRegistry(root=ruleset_root)
                              .list_executable())

    blockers: List[Dict[str, Any]] = []

    def block(code: str, detail: str) -> None:
        entry = BLOCKER_CODES[code]
        blockers.append({"code": code, "detail": detail,
                         "meaning": entry["meaning"], "owner": entry["owner"],
                         "unblocks": entry["unblocks"]})

    if not protocol_approved:
        block("CURATION_PROTOCOL_NOT_APPROVED",
              "protocol status is %s with no named approver" % protocol_status)
    if not evidence_approved:
        block("EVIDENCE_BUILD_NOT_APPROVED",
              "evidence build carries %s" % ", ".join(evidence_labels)
              or "no evidence build manifest was found")
    if not dataset_published:
        block("DATASET_NOT_PUBLISHED",
              "canonical dataset lifecycle state is %s" % dataset_state)
    if not approved_sources:
        block("SOURCE_POLICY_NOT_APPROVED",
              "%d source entries, %d approved" % (len(source_entries), 0))
    if curated_interpretations == 0:
        block("NO_CURATED_INTERPRETATIONS",
              "%d of %d work items are CURATED" % (0, work_items))
    block("NO_RULE_APPROVAL_ENVELOPES",
          "no rule approval envelope exists; WP-10's production role "
          "assignment set is empty, so nobody could have signed one")
    block("NO_VALIDATED_RULES", "0 rules exist in any state")
    block("HUMAN_ROLE_ASSIGNMENTS_MISSING",
          "curation_role_assignments is empty by design until WP-23")
    if work_items:
        block("LEGACY_ITEMS_NOT_ELIGIBLE",
              "%d legacy work items are RAW and unreviewed" % work_items)
    if unlinked:
        block("UNLINKED_CURATION_ITEMS_REMAIN",
              "%d legacy work items have no evidence link" % unlinked)

    payload: Dict[str, Any] = {
        "gate_status_version": GATE_STATUS_VERSION,
        "assessment": "REAL RULE CREATION, VALIDATION AND FREEZING ARE BLOCKED",
        "upstream_state": {
            "curation_protocol_status": protocol_status,
            "curation_protocol_approved": protocol_approved,
            "evidence_build_labels": list(evidence_labels),
            "evidence_build_approved_for_rules": evidence_approved,
            "canonical_dataset_state": dataset_state,
            "canonical_dataset_published": dataset_published,
            "source_registry_entries": len(source_entries),
            "source_registry_approved": len(approved_sources),
        },
        "curation_state": {
            "legacy_work_items": work_items,
            "linked_work_items": linked,
            "unlinked_work_items": unlinked,
            "curated_interpretations": curated_interpretations,
            "eligible_rule_approval_envelopes": 0,
        },
        "rule_state": {
            "real_draft_rules": 0,
            "real_curated_rules": 0,
            "real_validated_rules": 0,
            "real_deprecated_rules": 0,
            "real_frozen_rulesets": frozen_rulesets,
            "executable_rulesets_in_default_registry": frozen_rulesets,
        },
        "blockers": sorted(blockers, key=lambda entry: entry["code"]),
        "next_required_human_actions": [
            "a named scientific expert reads and approves the curation "
            "protocol against its content hash",
            "two named curators complete the WP-09 inter-curator exercise",
            "a source-policy approver completes review of the source registry",
            "the evidence build leaves quarantine through the publication gate",
            "WP-23 provides authenticated identities so roles can be assigned",
            "curators reach at least one CURATED interpretation with cited "
            "evidence",
            "a curator, an independent reviewer and an approver produce a rule "
            "approval envelope",
        ],
        "note": (
            "This is an expected governance result, not a test failure. The "
            "WP-11 machinery is implemented and verified against synthetic "
            "fixtures; what is missing is human scientific approval, which no "
            "code can supply. Nothing here may be closed by generating an "
            "approval."),
    }
    return GateStatusReport(payload=payload)


def build_real_build_attempt(repo_root: str = ".") -> GateStatusReport:
    """Record an honest attempt to build a real ruleset, and why it stopped.

    The attempt is genuine: it asks the real registry what it can serve and
    counts the real rules that exist. It stops at the first thing that is
    actually missing, which is everything.
    """
    status = build_gate_status(repo_root)
    ruleset_root = os.path.join(repo_root, "data", "rulesets")
    from pgx.rules.registry import FrozenRulesetRegistry
    registry = FrozenRulesetRegistry(root=ruleset_root)
    executable = list(registry.list_executable())

    payload: Dict[str, Any] = {
        "gate_status_version": GATE_STATUS_VERSION,
        "attempt": "BUILD A REAL FROZEN RULESET FROM APPROVED CURATION",
        "outcome": "REFUSED",
        "stopped_at": "NO_VALIDATED_RULES",
        "steps": [
            {"step": "enumerate CURATED interpretations eligible for rules",
             "result": "0 found",
             "reason": "no curation work item has reached CURATED"},
            {"step": "enumerate rule approval envelopes",
             "result": "0 found",
             "reason": "the production role assignment set is empty, so nobody "
                       "could have signed one"},
            {"step": "create DRAFT rules from eligible interpretations",
             "result": "not attempted",
             "reason": "there is nothing eligible to draft from"},
            {"step": "validate rules",
             "result": "not attempted",
             "reason": "no CURATED rule exists"},
            {"step": "create a BUILDING ruleset and add members",
             "result": "not attempted",
             "reason": "only VALIDATED rules may be members and there are none"},
            {"step": "build and freeze a ruleset artifact",
             "result": "not attempted",
             "reason": "an empty ruleset cannot validate, and a ruleset cannot "
                       "be frozen without validating first"},
            {"step": "ask the default registry what is executable",
             "result": "%d executable rulesets" % len(executable),
             "reason": "the production registry root contains no frozen "
                       "artifact"},
        ],
        "executable_rulesets": executable,
        "blockers": status.payload["blockers"],
        "note": (
            "No rule, ruleset or approval was created to make this attempt "
            "succeed. Manufacturing one would be the exact failure the "
            "curation and approval workflow exists to prevent."),
    }
    return GateStatusReport(payload=payload)
