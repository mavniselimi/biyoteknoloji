# -*- coding: utf-8 -*-
"""The active candidate release, and how the assessment path resolves it.

Implements the :class:`~pgx.application.assessment_service.ReleaseContextResolver`
contract, which had no production implementation before this wave: the only
implementations in the repository were test fixtures, and
``apps/api/provider.py`` raised ``ACTIVE_RELEASE_UNAVAILABLE`` because nothing
supplied one.

The resolver reads the active pointer once, verifies every hash the pointer
names against the artifacts on disk, and refuses on any mismatch. It refuses a
release that is not ``ACTIVE``, a manifest whose digest has moved, a ruleset
whose bytes have moved, and a dataset whose data-quality decision no longer
permits a candidate release. Each of those is a way the runtime could end up
executing something nobody decided on.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import io
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from pgx.domain.authority import CandidateAuthorityState
from pgx.domain.hashing import sha256_digest
from pgx.normalization.quality_decision import (LEDGER_PATH, load_ledger)
from pgx.rules.candidate import (CandidateRuleset, PERMITTED_CANDIDATE_MODES,
                                 load_candidate_ruleset)

__all__ = [
    "CANDIDATE_RELEASE_SCHEMA_VERSION",
    "CandidateReleaseError",
    "CandidateReleaseResolver",
    "PinnedCandidateRelease",
    "build_candidate_release_manifest",
    "load_active_candidate_release",
]

CANDIDATE_RELEASE_SCHEMA_VERSION = "pgx-candidate-release/1"

RELEASE_ROOT = os.path.join("data", "releases")
ACTIVE_POINTER = os.path.join(RELEASE_ROOT, "active-candidate-release.json")


class CandidateReleaseError(RuntimeError):
    """A candidate release could not be resolved, and why."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _read(path: str) -> Dict[str, Any]:
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _digest_file(path: str) -> str:
    with io.open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def build_candidate_release_manifest(
        *, release_public_id: str, repo_root: str, dataset_public_id: str,
        ruleset_key: str, built_by: str) -> Dict[str, Any]:
    """Assemble the manifest that binds a candidate release together.

    Every hash is measured from the artifact on disk at build time, never
    copied from another manifest. A release that repeated a hash it was told
    would verify itself against the telling rather than the artifact.
    """
    canonical = os.path.join(repo_root, "data", "canonical",
                             dataset_public_id)
    snapshot_root = os.path.join(repo_root, "data", "raw",
                                 "cpic-guideline-capture", dataset_public_id)
    ruleset_dir = os.path.join(repo_root, "data", "candidate-rulesets",
                               ruleset_key)

    dataset_manifest = _read(os.path.join(canonical, "manifest.json"))
    snapshot_manifest = _read(os.path.join(snapshot_root, "manifest.json"))
    ruleset_manifest = _read(os.path.join(ruleset_dir, "manifest.json"))

    ledger = load_ledger(os.path.join(repo_root, LEDGER_PATH))
    superseded = {row.supersedes for row in ledger if row.supersedes}
    current = [row for row in ledger
               if row.dataset_public_id == dataset_public_id
               and row.decision_id not in superseded]
    if len(current) != 1:
        raise CandidateReleaseError(
            "expected exactly one current data-quality decision for %s, "
            "found %d" % (dataset_public_id, len(current)),
            code="CANDIDATE_RELEASE_DQ_AMBIGUOUS")
    decision = current[0]
    if not decision.decision.permits_candidate_release:
        raise CandidateReleaseError(
            "the current data-quality decision for %s is %s, which does not "
            "permit a candidate release"
            % (dataset_public_id, decision.decision.value),
            code="CANDIDATE_RELEASE_DQ_REFUSES")

    body = {
        "authority_state":
            CandidateAuthorityState.PROJECT_TEAM_PROVISIONAL.value,
        "canonical_build_content_hash": dataset_manifest["content_hash"],
        "canonical_build_key": dataset_manifest["canonical_build_key"],
        "capture_snapshot_content_hash":
            snapshot_manifest["snapshot_content_hash"],
        "capture_snapshot_manifest_hash": snapshot_manifest["manifest_hash"],
        "dataset_public_id": dataset_public_id,
        "dq_decision": decision.decision.value,
        "dq_decision_id": decision.decision_id,
        "dq_report_hash": decision.dq_artifact_hash,
        "is_governed_release": False,
        "limitations": [
            "This is a candidate release. It is not a governed release "
            "bundle, is not registered through the WP-13 release service, and "
            "is executable in DEMO and VALIDATION only.",
            "Its dataset's data-quality gate did not pass; the accepting "
            "decision names the blocking issues it accepted over.",
            "Its rules, interpretations and validation results have been "
            "reviewed by nobody outside this project.",
            "It supports four drugs and two genes and refuses everything "
            "else, including a CYP2D6 rapid metabolizer, an indeterminate "
            "phenotype, and clopidogrel without a declared care setting.",
        ],
        "permitted_modes": list(PERMITTED_CANDIDATE_MODES),
        "prohibited_modes": ["PILOT"],
        "release_public_id": release_public_id,
        "release_schema_version": CANDIDATE_RELEASE_SCHEMA_VERSION,
        "review_state":
            CandidateAuthorityState.PENDING_EXTERNAL_EXPERT_REVIEW.value,
        "ruleset_content_hash": ruleset_manifest["content_hash"],
        "ruleset_file_digests": {
            name: _digest_file(os.path.join(ruleset_dir, name))
            for name in sorted(os.listdir(ruleset_dir))},
        "ruleset_key": ruleset_key,
        "source_policy_content_hash": decision.source_policy_hash,
        "status": "ACTIVE",
    }
    body["manifest_hash"] = sha256_digest(body)
    body["built_by"] = built_by
    return body


@dataclass(frozen=True, slots=True)
class PinnedCandidateRelease:
    """One resolved candidate release, with everything it names verified."""

    manifest: Mapping[str, Any]
    ruleset: CandidateRuleset
    pointer_generation: int

    @property
    def release_public_id(self) -> str:
        return self.manifest["release_public_id"]

    @property
    def dataset_public_id(self) -> str:
        return self.manifest["dataset_public_id"]

    @property
    def is_candidate(self) -> bool:
        return True

    def permits_mode(self, mode: str) -> bool:
        return mode in tuple(self.manifest["permitted_modes"])


def load_active_candidate_release(repo_root: str = ".",
                                  ruleset_factory=None
                                  ) -> PinnedCandidateRelease:
    """Read the active pointer once and verify everything it names."""
    pointer_path = os.path.join(repo_root, ACTIVE_POINTER)
    if not os.path.isfile(pointer_path):
        raise CandidateReleaseError(
            "no active candidate release pointer at %s" % pointer_path,
            code="CANDIDATE_RELEASE_NOT_ACTIVE")
    pointer = _read(pointer_path)
    release_id = pointer.get("release_public_id")
    manifest_path = os.path.join(repo_root, RELEASE_ROOT, str(release_id),
                                 "manifest.json")
    if not os.path.isfile(manifest_path):
        raise CandidateReleaseError(
            "the active pointer names %s, which has no manifest" % release_id,
            code="CANDIDATE_RELEASE_MISSING")
    manifest = _read(manifest_path)

    if manifest.get("status") != "ACTIVE":
        raise CandidateReleaseError(
            "release %s is %r, not ACTIVE"
            % (release_id, manifest.get("status")),
            code="CANDIDATE_RELEASE_NOT_ACTIVE")

    recorded = dict(manifest)
    claimed = recorded.pop("manifest_hash", None)
    recorded.pop("built_by", None)
    if sha256_digest(recorded) != claimed:
        raise CandidateReleaseError(
            "release %s does not match its own manifest hash" % release_id,
            code="CANDIDATE_RELEASE_MANIFEST_HASH_MISMATCH")
    if pointer.get("manifest_hash") != claimed:
        raise CandidateReleaseError(
            "the active pointer names manifest hash %r and the manifest is %r"
            % (pointer.get("manifest_hash"), claimed),
            code="CANDIDATE_RELEASE_POINTER_MISMATCH")

    # Deliberately not ``data/rulesets``. That directory is what
    # ``FrozenRulesetRegistry`` scans for *governed* rulesets, and a test
    # asserts it is empty until one exists. A candidate artifact sitting there
    # would be found by the governed registry, which is exactly the confusion
    # the separate directory prevents.
    ruleset_dir = os.path.join(repo_root, "data", "candidate-rulesets",
                               manifest["ruleset_key"])
    artifact = load_candidate_ruleset(ruleset_dir)
    for name, digest in sorted(manifest["ruleset_file_digests"].items()):
        actual = _digest_file(os.path.join(ruleset_dir, name))
        if actual != digest:
            raise CandidateReleaseError(
                "ruleset file %s does not match the digest the release pins"
                % name,
                code="CANDIDATE_RELEASE_RULESET_HASH_MISMATCH")
    if artifact["manifest"]["content_hash"] != manifest["ruleset_content_hash"]:
        raise CandidateReleaseError(
            "the ruleset's content hash is not the one the release pins",
            code="CANDIDATE_RELEASE_RULESET_HASH_MISMATCH")

    ledger = load_ledger(os.path.join(repo_root, LEDGER_PATH))
    superseded = {row.supersedes for row in ledger if row.supersedes}
    current = [row for row in ledger
               if row.dataset_public_id == manifest["dataset_public_id"]
               and row.decision_id not in superseded]
    if len(current) != 1 or current[0].decision_id != manifest["dq_decision_id"]:
        raise CandidateReleaseError(
            "the data-quality decision this release pins is no longer the "
            "current decision for %s" % manifest["dataset_public_id"],
            code="CANDIDATE_RELEASE_DQ_SUPERSEDED")
    if not current[0].decision.permits_candidate_release:
        raise CandidateReleaseError(
            "the current data-quality decision no longer permits a candidate "
            "release", code="CANDIDATE_RELEASE_DQ_REFUSES")

    if ruleset_factory is None:
        from pgx.closure.wave03b_build import build_core_candidate_ruleset
        ruleset_factory = lambda: build_core_candidate_ruleset({  # noqa: E731
            "canonical_build_content_hash":
                manifest["canonical_build_content_hash"],
            "canonical_build_key": manifest["canonical_build_key"],
            "dataset_public_id": manifest["dataset_public_id"],
            "dq_decision_id": manifest["dq_decision_id"],
            "snapshot_manifest_hash":
                manifest["capture_snapshot_manifest_hash"],
            "source_policy_content_hash":
                manifest["source_policy_content_hash"],
            "source_policy_status": "PENDING_REVIEW",
        })
    ruleset = ruleset_factory()
    if ruleset.content_hash() != manifest["ruleset_content_hash"]:
        raise CandidateReleaseError(
            "the ruleset rebuilt from code does not match the frozen "
            "artifact this release pins; the two have drifted",
            code="CANDIDATE_RELEASE_RULESET_DRIFT")

    return PinnedCandidateRelease(
        manifest=manifest, ruleset=ruleset,
        pointer_generation=int(pointer.get("generation", 0)))


class CandidateReleaseResolver:
    """A ``ReleaseContextResolver`` over the active candidate release."""

    def __init__(self, repo_root: str = ".") -> None:
        self._repo_root = repo_root

    def resolve(self, *, requested_release_public_id: Optional[str] = None
                ) -> PinnedCandidateRelease:
        pinned = load_active_candidate_release(self._repo_root)
        if requested_release_public_id and \
                requested_release_public_id != pinned.release_public_id:
            raise CandidateReleaseError(
                "release %s was requested; the active candidate release is %s. "
                "A request for a release that is not active is refused rather "
                "than served by the active one."
                % (requested_release_public_id, pinned.release_public_id),
                code="CANDIDATE_RELEASE_NOT_ACTIVE")
        return pinned
