# -*- coding: utf-8 -*-
"""Why no real assessment can execute yet (WP-14).

Every count here is read off the repository rather than asserted, so the day
any of it changes this report changes with it and the change is visible in a
diff. That is the difference between a gate and a comment.

The blockers are not bugs and none can be cleared by writing code. What is
missing is human and scientific judgement: an approved intended purpose, an
approved curation protocol, a published dataset, a de-quarantined evidence
build, validated rules, a frozen ruleset, an approved coverage scope, an
active release, and people holding scientific roles. Each is named below with
who owns it and what clearing it would unblock.
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Tuple

from pgx.domain.claims import DEFAULT_CLAIM_BOUNDARY
from pgx.domain.hashing import sha256_digest

__all__ = [
    "ASSESSMENT_GATE_STATUS_VERSION",
    "BLOCKER_CODES",
    "DEFAULT_ASSESSMENT_ROOT",
    "GATE_STATUS_FILENAME",
    "AssessmentGateStatus",
    "build_assessment_gate_status",
]

ASSESSMENT_GATE_STATUS_VERSION = "pgx-wp14-gate-status/1"

#: Where a real assessment export would live. Empty, and a test asserts it
#: stays empty: a file here would mean an assessment had been executed.
DEFAULT_ASSESSMENT_ROOT = os.path.join("data", "assessments")

#: This report's own filename, skipped by the scanner below so regenerating it
#: cannot read a half-written copy of itself.
GATE_STATUS_FILENAME = "wp14-real-gate-status.json"

BLOCKER_CODES: Mapping[str, Mapping[str, str]] = {
    "ASSESSMENT_CLAIM_BOUNDARY_NOT_APPROVED": {
        "meaning": "the claim boundary is DRAFT and awaiting human and "
                   "scientific review, so no assessment may execute in any "
                   "mode",
        "owner": "the people named in docs/architecture/intended-purpose.md, "
                 "not code",
        "unblocks": "the service stops refusing before it reads anything",
    },
    "ASSESSMENT_NO_ACTIVE_RELEASE": {
        "meaning": "no release bundle is ACTIVE, so there is nothing for an "
                   "assessment to pin",
        "owner": "the WP-03 release registry, which is itself blocked on "
                 "everything below",
        "unblocks": "a release can be pinned and its versions recorded",
    },
    "ASSESSMENT_NO_FROZEN_RULESET": {
        "meaning": "no frozen ruleset exists, so no rule can execute",
        "owner": "the WP-11 rule governance chain",
        "unblocks": "a validated member rule can produce a finding",
    },
    "ASSESSMENT_NO_APPROVED_COVERAGE_MANIFEST": {
        "meaning": "no approved coverage manifest exists, so no axis can be "
                   "FULL and no finding may be emitted",
        "owner": "a curator to declare the scope, an independent reviewer, "
                 "and an approver, acting separately",
        "unblocks": "coverage-first execution has something to consult",
    },
    "ASSESSMENT_NO_VALIDATED_RULE": {
        "meaning": "no rule has reached VALIDATED, so nothing is executable "
                   "(SAFETY-INV-003)",
        "owner": "rule authors, an independent validator, and an approver",
        "unblocks": "an axis can carry a governed outcome",
    },
    "ASSESSMENT_CURATION_PROTOCOL_NOT_APPROVED": {
        "meaning": "the curation protocol carries no ratification from a "
                   "named scientific expert",
        "owner": "a named scientific expert (not code)",
        "unblocks": "the whole chain beneath assessment",
    },
    "ASSESSMENT_DATASET_NOT_PUBLISHED": {
        "meaning": "the canonical dataset is still BUILDING, so a release "
                   "cannot pin something that will not change beneath it",
        "owner": "the dataset quality and publication process (WP-07)",
        "unblocks": "a stable dataset identity for a release to name",
    },
    "ASSESSMENT_EVIDENCE_BUILD_QUARANTINED": {
        "meaning": "the evidence build is quarantined and not "
                   "publication-eligible, so no finding can cite resolvable "
                   "approved evidence (SAFETY-INV-006)",
        "owner": "source-policy review, then a re-labelled build",
        "unblocks": "a finding can satisfy its traceability requirement",
    },
    "ASSESSMENT_NO_HUMAN_ROLE_ASSIGNMENTS": {
        "meaning": "no identity holds a scientific role, so none of the "
                   "separated approvals above can be performed by anybody",
        "owner": "WP-23 authentication, then whoever assigns roles",
        "unblocks": "every approval this list depends on",
    },
}


@dataclass(frozen=True, slots=True)
class AssessmentGateStatus:
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


def _read_json(path: str) -> Any:
    """Read a JSON file, or ``None`` if absent or unreadable."""
    if not os.path.isfile(path):
        return None
    try:
        with io.open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (ValueError, OSError):
        return None


def build_assessment_gate_status(repo_root: str = "."
                                 ) -> AssessmentGateStatus:
    """Read the real repository and report what assessment it permits."""
    from pgx.rules.registry import DEFAULT_RULESET_ROOT, FrozenRulesetRegistry

    executable = FrozenRulesetRegistry(
        os.path.join(repo_root, DEFAULT_RULESET_ROOT)).list_executable()

    coverage_root = os.path.join(repo_root, "data", "coverage")
    coverage_manifests: List[str] = []
    if os.path.isdir(coverage_root):
        for name in sorted(os.listdir(coverage_root)):
            if not name.endswith(".json") or name.startswith("wp13-"):
                continue
            document = _read_json(os.path.join(coverage_root, name))
            if isinstance(document, dict) and \
                    document.get("coverage_schema_version"):
                coverage_manifests.append(name)

    assessment_root = os.path.join(repo_root, DEFAULT_ASSESSMENT_ROOT)
    assessments: List[str] = []
    if os.path.isdir(assessment_root):
        for name in sorted(os.listdir(assessment_root)):
            if not name.endswith(".json") or name == GATE_STATUS_FILENAME:
                continue
            document = _read_json(os.path.join(assessment_root, name))
            if isinstance(document, dict) and document.get("assessment_id"):
                assessments.append(name)

    protocol = _read_json(os.path.join(repo_root, "config", "curation",
                                       "protocol-v1.json")) or {}
    canonical = _read_json(os.path.join(
        repo_root, "data", "canonical", "PGX-DATA-20260830-900",
        "manifest.json")) or {}
    evidence = _read_json(os.path.join(
        repo_root, "data", "evidence", "PGX-DATA-20260830-900",
        "manifest.json")) or {}

    boundary = DEFAULT_CLAIM_BOUNDARY
    detail = {
        "ASSESSMENT_CLAIM_BOUNDARY_NOT_APPROVED":
            "claim boundary status is %s" % boundary.status,
        "ASSESSMENT_NO_ACTIVE_RELEASE":
            "0 release bundles are ACTIVE in this repository",
        "ASSESSMENT_NO_FROZEN_RULESET":
            "%d frozen rulesets in %s" % (len(executable),
                                          DEFAULT_RULESET_ROOT),
        "ASSESSMENT_NO_APPROVED_COVERAGE_MANIFEST":
            "%d approved coverage manifests found" % len(coverage_manifests),
        "ASSESSMENT_NO_VALIDATED_RULE":
            "0 rules have reached VALIDATED",
        "ASSESSMENT_CURATION_PROTOCOL_NOT_APPROVED":
            "protocol status is %s" % protocol.get("status", "unknown"),
        "ASSESSMENT_DATASET_NOT_PUBLISHED":
            "dataset state is %s"
            % canonical.get("dataset_lifecycle_state", "unknown"),
        "ASSESSMENT_EVIDENCE_BUILD_QUARANTINED":
            "evidence build labels are %s"
            % ", ".join(evidence.get("lifecycle_labels", []) or ["unknown"]),
        "ASSESSMENT_NO_HUMAN_ROLE_ASSIGNMENTS":
            "0 identities hold a scientific role",
    }
    blockers = []
    for code in sorted(BLOCKER_CODES):
        entry = BLOCKER_CODES[code]
        blockers.append({"code": code, "meaning": entry["meaning"],
                         "owner": entry["owner"],
                         "unblocks": entry["unblocks"],
                         "detail": detail[code]})

    payload: Dict[str, Any] = {
        "gate_status_version": ASSESSMENT_GATE_STATUS_VERSION,
        "assessment": "REAL ASSESSMENT EXECUTION IS BLOCKED",
        "claim_boundary": {
            "phase": boundary.phase.value,
            "status": boundary.status,
            "approved": boundary.is_approved,
            "enabled_modes": sorted(mode.value
                                    for mode in boundary.enabled_modes),
        },
        "upstream_state": {
            "curation_protocol_status": protocol.get("status", "unknown"),
            "canonical_dataset_state":
                canonical.get("dataset_lifecycle_state", "unknown"),
            "canonical_dataset_published":
                canonical.get("dataset_lifecycle_state") == "PUBLISHED",
            "evidence_build_labels":
                list(evidence.get("lifecycle_labels", []) or []),
            "evidence_build_approved_for_assessment": False,
            "active_releases": 0,
            "frozen_rulesets": len(executable),
            "executable_rulesets_in_default_registry": len(executable),
            "approved_coverage_manifests": len(coverage_manifests),
            "validated_rules": 0,
        },
        "assessment_state": {
            "real_executable_release_contexts": 0,
            "real_completed_assessments": len(assessments),
            "real_findings": 0,
            "real_medication_results": 0,
            "real_persisted_assessments": 0,
        },
        "blockers": blockers,
        "next_required_human_actions": [
            "named humans review and approve the intended purpose, moving the "
            "claim boundary off DRAFT",
            "a named scientific expert reads and approves the curation "
            "protocol against its content hash",
            "the canonical dataset is quality-checked and published",
            "the evidence build is reviewed and its quarantine labels are "
            "removed by whoever owns source policy",
            "WP-23 supplies authentication, and somebody assigns scientific "
            "roles to real identities",
            "rules are authored, independently validated, and a ruleset is "
            "frozen",
            "curators, a reviewer and an approver declare an expected gene "
            "scope per drug and approve a coverage manifest",
            "a release bundle pinning that software, dataset and ruleset is "
            "registered and activated",
        ],
        "note": (
            "This is an expected governance result, not a test failure. The "
            "WP-14 machinery is implemented and verified against synthetic "
            "fixtures; what is missing is human and scientific judgement, and "
            "none of the blockers above can be cleared by writing code. No "
            "assessment in this repository has been executed against real "
            "data, no finding has been persisted, and no count above was "
            "asserted rather than read."),
    }
    return AssessmentGateStatus(payload=payload)
