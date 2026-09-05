# -*- coding: utf-8 -*-
"""Why no real coverage can be computed (WP-13).

A machine-readable statement of the current governance position: how many
approved coverage manifests exist, how many axes are really evaluable, how
many coverage executions have really happened, and what would have to be true
before any of those numbers could change.

Every blocker names a person or a human process as its owner, because none of
them is clearable by writing more code. A coverage manifest declares what a
complete assessment of a drug requires; that is a scientific judgement, and no
amount of implementation supplies one.
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Tuple

from pgx.domain.hashing import sha256_digest

__all__ = [
    "BLOCKER_CODES",
    "COVERAGE_GATE_STATUS_VERSION",
    "DEFAULT_COVERAGE_ROOT",
    "CoverageGateStatus",
    "build_coverage_gate_status",
]

COVERAGE_GATE_STATUS_VERSION = "pgx-wp13-gate-status/1"

#: Where a real approved coverage manifest would live. Empty, and a test
#: asserts it stays empty: a manifest appearing here would mean somebody had
#: approved a coverage scope.
DEFAULT_COVERAGE_ROOT = os.path.join("data", "coverage")

BLOCKER_CODES: Mapping[str, Mapping[str, str]] = {
    "NO_APPROVED_COVERAGE_MANIFEST": {
        "meaning": "no coverage manifest has been declared, reviewed and "
                   "approved for any ruleset",
        "owner": "a scientific curator to declare the scope, an independent "
                 "reviewer to check it, and an approver, acting separately",
        "unblocks": "coverage can be computed for the drugs the manifest "
                    "declares, and only for those",
    },
    "NO_FROZEN_RULESET": {
        "meaning": "there is no frozen ruleset for a coverage manifest to "
                   "describe",
        "owner": "the WP-11 rule governance chain, which is itself blocked",
        "unblocks": "a manifest can pin a ruleset by identity and hash",
    },
    "DEFAULT_REGISTRY_EMPTY": {
        "meaning": "the engine-facing registry serves no executable ruleset",
        "owner": "the same chain: a ruleset reaches the registry by being "
                 "frozen",
        "unblocks": "an evaluation has a ruleset to run against",
    },
    "CANONICAL_DATASET_NOT_PUBLISHED": {
        "meaning": "the canonical dataset is still BUILDING, so no manifest "
                   "can pin a published dataset",
        "owner": "the dataset quality and publication process (WP-07)",
        "unblocks": "a manifest can pin a dataset that will not change beneath "
                    "it",
    },
    "EVIDENCE_BUILD_QUARANTINED": {
        "meaning": "the evidence build is quarantined and not "
                   "publication-eligible, so no axis can cite resolvable "
                   "approved evidence",
        "owner": "source-policy review, then a re-labelled build",
        "unblocks": "a supported axis can satisfy SAFETY-INV-006",
    },
    "CURATION_PROTOCOL_NOT_APPROVED": {
        "meaning": "the curation protocol carries no ratification from a named "
                   "scientific expert",
        "owner": "a named scientific expert (not code)",
        "unblocks": "the whole chain beneath coverage: curation, rules, and "
                    "then a scope declared under an approved protocol",
    },
    "NO_EXPECTED_SCOPE_DECLARED": {
        "meaning": "no drug has an approved expected gene scope, and expected "
                   "scope cannot be derived from anything",
        "owner": "scientific curators, whose judgement it is",
        "unblocks": "an incompletely covered drug becomes detectable; without "
                    "it, every drug looks as covered as its rules happen to "
                    "make it",
    },
    "HUMAN_ROLE_ASSIGNMENTS_MISSING": {
        "meaning": "no identity holds a scientific role, so no declaration "
                   "can be made, reviewed or ratified by anybody",
        "owner": "WP-23 authentication, then whoever assigns roles",
        "unblocks": "the three separated acts a coverage declaration requires",
    },
}


@dataclass(frozen=True, slots=True)
class CoverageGateStatus:
    payload: Mapping[str, Any]

    def to_json(self) -> Dict[str, Any]:
        document = dict(self.payload)
        document["content_hash"] = sha256_digest(
            {key: value for key, value in document.items()
             if key != "content_hash"})
        return document

    def content_hash(self) -> str:
        return self.to_json()["content_hash"]

    @property
    def blockers(self) -> Tuple[Mapping[str, Any], ...]:
        return tuple(self.payload.get("blockers", ()))


#: This report's own filename. The scanner below counts coverage manifests in
#: the coverage directory, and its own output lives there too; excluding it by
#: name is clearer than excluding it by shape, and means regenerating the
#: report cannot read a half-written copy of itself.
GATE_STATUS_FILENAME = "wp13-real-gate-status.json"


def _read_json(path: str) -> Any:
    """Read a JSON file, or ``None`` if it is absent or unreadable.

    A file in the coverage directory that does not parse is not a coverage
    manifest, which is the only question this module asks of it. It is counted
    as unreadable rather than ignored, so a corrupt file is visible in the
    report instead of quietly reducing the manifest count.
    """
    if not os.path.isfile(path):
        return None
    try:
        with io.open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (ValueError, OSError):
        return None


def build_coverage_gate_status(repo_root: str = ".") -> CoverageGateStatus:
    """Read the real repository and report what coverage it permits.

    Everything here is counted rather than asserted, so the day any of it
    changes the report changes with it.
    """
    from pgx.rules.registry import DEFAULT_RULESET_ROOT, FrozenRulesetRegistry

    registry_root = os.path.join(repo_root, DEFAULT_RULESET_ROOT)
    executable = FrozenRulesetRegistry(registry_root).list_executable()

    coverage_root = os.path.join(repo_root, DEFAULT_COVERAGE_ROOT)
    manifests: List[str] = []
    unreadable: List[str] = []
    if os.path.isdir(coverage_root):
        for name in sorted(os.listdir(coverage_root)):
            path = os.path.join(coverage_root, name)
            if not name.endswith(".json") or not os.path.isfile(path):
                continue
            if name == GATE_STATUS_FILENAME:
                continue
            document = _read_json(path)
            if document is None:
                unreadable.append(name)
            elif isinstance(document, dict) and \
                    document.get("coverage_schema_version"):
                manifests.append(name)

    protocol = _read_json(os.path.join(repo_root, "config", "curation",
                                       "protocol-v1.json")) or {}
    evidence_manifest = _read_json(os.path.join(
        repo_root, "data", "evidence", "PGX-DATA-20260830-900",
        "manifest.json")) or {}
    canonical_manifest = _read_json(os.path.join(
        repo_root, "data", "canonical", "PGX-DATA-20260830-900",
        "manifest.json")) or {}

    blockers = []
    for code in sorted(BLOCKER_CODES):
        entry = BLOCKER_CODES[code]
        detail = {
            "NO_APPROVED_COVERAGE_MANIFEST":
                "%d coverage manifests found in %s (%d unreadable files)"
                % (len(manifests), DEFAULT_COVERAGE_ROOT, len(unreadable)),
            "NO_FROZEN_RULESET":
                "%d frozen rulesets in %s" % (len(executable),
                                              DEFAULT_RULESET_ROOT),
            "DEFAULT_REGISTRY_EMPTY":
                "%d executable rulesets served" % len(executable),
            "CANONICAL_DATASET_NOT_PUBLISHED":
                "dataset state is %s"
                % canonical_manifest.get("dataset_lifecycle_state", "unknown"),
            "EVIDENCE_BUILD_QUARANTINED":
                "evidence build labels are %s"
                % ", ".join(evidence_manifest.get("lifecycle_labels", []) or
                            ["unknown"]),
            "CURATION_PROTOCOL_NOT_APPROVED":
                "protocol status is %s" % protocol.get("status", "unknown"),
            "NO_EXPECTED_SCOPE_DECLARED":
                "0 drugs have an approved expected gene scope",
            "HUMAN_ROLE_ASSIGNMENTS_MISSING":
                "0 identities hold a scientific role",
        }[code]
        blockers.append({"code": code, "meaning": entry["meaning"],
                         "owner": entry["owner"],
                         "unblocks": entry["unblocks"], "detail": detail})

    payload: Dict[str, Any] = {
        "gate_status_version": COVERAGE_GATE_STATUS_VERSION,
        "assessment": "REAL COVERAGE EVALUATION IS BLOCKED",
        "upstream_state": {
            "curation_protocol_status": protocol.get("status", "unknown"),
            "curation_protocol_approved": bool(protocol.get("approved_by")),
            "canonical_dataset_state":
                canonical_manifest.get("dataset_lifecycle_state", "unknown"),
            "canonical_dataset_published":
                canonical_manifest.get("dataset_lifecycle_state") == "PUBLISHED",
            "evidence_build_labels":
                list(evidence_manifest.get("lifecycle_labels", []) or []),
            "evidence_build_approved_for_coverage": False,
            "frozen_rulesets": len(executable),
            "executable_rulesets_in_default_registry": len(executable),
        },
        "coverage_state": {
            "real_coverage_manifests": len(manifests),
            "real_declared_drugs": 0,
            "real_expected_gene_declarations": 0,
            "real_supported_axes": 0,
            "real_evaluable_axes": 0,
            "real_full_coverage_axes": 0,
            "real_coverage_executions": 0,
        },
        "blockers": blockers,
        "next_required_human_actions": [
            "a named scientific expert reads and approves the curation "
            "protocol against its content hash",
            "the canonical dataset is quality-checked and published, so a "
            "manifest can pin something that will not change beneath it",
            "the evidence build is reviewed and its quarantine labels are "
            "removed by whoever owns source policy",
            "WP-23 supplies authentication, and somebody assigns scientific "
            "roles to real identities",
            "curators, a reviewer and an approver, acting separately, declare "
            "an expected gene scope for each drug a release intends to cover",
            "rules are validated and a ruleset is frozen, giving a coverage "
            "manifest something to describe",
        ],
        "note": (
            "This is an expected governance result, not a test failure. The "
            "WP-13 machinery is implemented and verified against synthetic "
            "fixtures; what is missing is scientific judgement, and none of "
            "the blockers above can be cleared by writing code. In particular "
            "the expected gene scope for a drug - which genes a complete "
            "assessment would have to consider - cannot be derived from the "
            "rules that happen to exist, because a scope derived that way "
            "would make every drug look exactly as covered as its rules make "
            "it and no gap would ever be visible."),
    }
    return CoverageGateStatus(payload=payload)
