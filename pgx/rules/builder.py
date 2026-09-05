# -*- coding: utf-8 -*-
"""The deterministic ruleset builder (WP-11).

A build takes a ``VALIDATED`` ruleset and produces four files plus a checksum
file. Rebuilding from identical semantic inputs produces an identical semantic
hash, on any machine, at any time.

**What determinism costs, and why it is worth it.** Every step below exists to
remove one source of variation:

* members are sorted by semantic key, so a shuffled database result cannot
  change the output;
* every document is serialised with sorted keys and fixed separators, so
  dictionary iteration order cannot;
* the hashed payload contains no path, no timestamp, no duration, no hostname
  and no process id, so the machine cannot;
* the build verifies its own output before publishing, so a corrupted write
  cannot become a frozen artifact.

What that buys is the ability to answer "is this the ruleset that was
approved?" by re-running the build and comparing one hash. Without it the
question can only be answered by trusting the filesystem.

**Operational metadata is separated, not suppressed.** The build log records
when the build ran, how long it took and who ran it, because an operator needs
that. It sits outside every hashed payload, so knowing when a ruleset was built
and knowing what it contains are two independent questions.
"""

from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass
from typing import (Any, Callable, Dict, List, Mapping, Optional, Sequence,
                    Tuple)

from pgx.domain.enums import RuleStatus, RulesetStatus
from pgx.domain.hashing import sha256_digest
from pgx.rules.conditions import CONDITION_SCHEMA_VERSION
from pgx.rules.errors import (ArtifactIntegrityError, RuleValidationError,
                              RulesetLifecycleError)
from pgx.rules.identifiers import RulesetBuildId
from pgx.rules.models import (RULESET_SCHEMA_VERSION, RULE_SCHEMA_VERSION,
                              ComputableRuleDefinition, RuleLifecycleRecord,
                              RulesetApprovalRecord, RulesetBuildRecord,
                              RulesetDefinition, RulesetManifest,
                              RulesetMember)
from pgx.rules.serialization import (ARTIFACT_FILES, CHECKSUM_FILE,
                                     canonical_bytes, canonical_ndjson_bytes,
                                     publish_atomically, write_checksum_file)
from pgx.rules.validator import ValidationReport, validate_ruleset_members

__all__ = [
    "BuildResult",
    "BuildInputs",
    "build_ruleset",
    "compose_artifact",
    "ruleset_content_hash",
]


@dataclass(frozen=True)
class BuildInputs:
    """Everything a build reads, supplied explicitly.

    Assembled by the caller from repositories, so the builder itself touches no
    database and no clock beyond the one it is given. That is what makes a
    build reproducible in a test.
    """

    ruleset: RulesetDefinition
    definitions: Tuple[ComputableRuleDefinition, ...]
    lifecycles: Mapping[str, RuleLifecycleRecord]
    approvals: Tuple[RulesetApprovalRecord, ...]
    dataset_public_id: Any
    canonical_build_key: str
    canonical_build_content_hash: str
    evidence_build_key: str
    evidence_build_content_hash: str
    protocol_version: str
    protocol_content_hash: str
    source_policy_version: str
    source_policy_content_hash: str


@dataclass(frozen=True)
class BuildResult:
    """What a build produced, verified."""

    manifest: RulesetManifest
    files: Mapping[str, bytes]
    ruleset_content_hash: str
    record: RulesetBuildRecord
    report: ValidationReport

    @property
    def succeeded(self) -> bool:
        return self.record.outcome == "SUCCEEDED"


def ruleset_content_hash(manifest: RulesetManifest,
                         definitions: Sequence[ComputableRuleDefinition]) -> str:
    """The semantic identity of a built ruleset.

    Covers the manifest and the canonical content of every member. Two builds
    of the same members under the same pins agree; changing one member's
    condition, outcome or provenance changes it.
    """
    return sha256_digest({
        "manifest": manifest.semantic_content(),
        "rules": [definition.semantic_content()
                  for definition in sorted(definitions,
                                           key=lambda item: item.sort_key())],
    })


def compose_artifact(inputs: BuildInputs, *,
                     built_by: str,
                     started_at: _dt.datetime,
                     completed_at: _dt.datetime,
                     build_id: RulesetBuildId,
                     artifact_relative_path: str,
                     ) -> Tuple[RulesetManifest, Dict[str, bytes], str]:
    """Build the artifact bytes, without touching the filesystem.

    Separated from publication so a test can assert determinism by composing
    twice and comparing bytes, and so a build that will be refused never
    reaches the disk at all.
    """
    ordered = tuple(sorted(inputs.definitions, key=lambda item: item.sort_key()))
    members = tuple(RulesetMember(
        rule_id=definition.rule_id, family_id=definition.family_id,
        rule_version=definition.rule_version,
        content_hash=definition.content_hash()) for definition in ordered)

    approvals = tuple(sorted(inputs.approvals,
                             key=lambda item: item.rule_id.to_json()))
    approval_payload = {
        "approval_list_version": "pgx-ruleset-approval-list/1",
        "ruleset_id": inputs.ruleset.ruleset_id.to_json(),
        "public_id": inputs.ruleset.public_id.to_json(),
        "entry_count": len(approvals),
        "entries": [record.to_json() for record in approvals],
        "note": ("Each entry names the people whose separated acts produced one "
                 "member rule. The list is copied into the frozen artifact so "
                 "the artifact carries its own evidence of governance rather "
                 "than pointing at a table that can change."),
    }
    approval_list_hash = sha256_digest(approval_payload)

    axes = tuple(sorted({axis for definition in ordered
                         for axis in definition.axes()}))

    manifest = RulesetManifest(
        ruleset_schema_version=RULESET_SCHEMA_VERSION,
        rule_schema_version=RULE_SCHEMA_VERSION,
        condition_schema_version=CONDITION_SCHEMA_VERSION,
        ruleset_id=inputs.ruleset.ruleset_id,
        public_id=inputs.ruleset.public_id,
        ruleset_version=inputs.ruleset.version,
        members=members,
        dataset_public_id=inputs.dataset_public_id,
        canonical_build_key=inputs.canonical_build_key,
        canonical_build_content_hash=inputs.canonical_build_content_hash,
        evidence_build_key=inputs.evidence_build_key,
        evidence_build_content_hash=inputs.evidence_build_content_hash,
        protocol_version=inputs.protocol_version,
        protocol_content_hash=inputs.protocol_content_hash,
        source_policy_version=inputs.source_policy_version,
        source_policy_content_hash=inputs.source_policy_content_hash,
        structural_axes=axes,
        approval_list_hash=approval_list_hash)

    content_hash = ruleset_content_hash(manifest, ordered)

    build_log = RulesetBuildRecord(
        build_id=build_id, ruleset_id=inputs.ruleset.ruleset_id,
        started_at=started_at, completed_at=completed_at, built_by=built_by,
        outcome="SUCCEEDED", manifest_hash=manifest.content_hash(),
        ruleset_content_hash=content_hash, member_count=len(members),
        artifact_relative_path=artifact_relative_path).to_json()
    build_log["ruleset_schema_version"] = RULESET_SCHEMA_VERSION

    files: Dict[str, bytes] = {
        "manifest.json": canonical_bytes(manifest.to_json()),
        "rules.ndjson": canonical_ndjson_bytes(
            [definition.to_json() for definition in ordered]),
        "approval-list.json": canonical_bytes(approval_payload),
        "build-log.json": canonical_bytes(build_log),
    }
    files[CHECKSUM_FILE] = write_checksum_file(files)
    return manifest, files, content_hash


def build_ruleset(inputs: BuildInputs, *,
                  destination: str,
                  built_by: str,
                  clock: Optional[Callable[[], _dt.datetime]] = None,
                  build_id: Optional[RulesetBuildId] = None,
                  publish: bool = True) -> BuildResult:
    """Validate, compose, verify and publish one ruleset artifact.

    Refuses before writing anything when the ruleset is not ``VALIDATED``, when
    any member fails layer E, or when an artifact already exists at the
    destination. The refusal is a :class:`BuildResult` with outcome ``REFUSED``
    only for the validation case, because that one carries a report an author
    can act on; the others raise, because they are not the author's to fix.
    """
    now = clock or (lambda: _dt.datetime.now(tz=_dt.timezone.utc))
    started_at = now()
    build_id = build_id or RulesetBuildId.new()

    if inputs.ruleset.status is not RulesetStatus.VALIDATED:
        raise RulesetLifecycleError(
            "a ruleset is built from its VALIDATED state; this one is %s. "
            "Building a BUILDING set would freeze a membership nobody checked."
            % inputs.ruleset.status.value,
            current=inputs.ruleset.status.value,
            requested=RulesetStatus.FROZEN.value)

    report = validate_ruleset_members(
        inputs.definitions, inputs.lifecycles,
        pinned_hashes={member.rule_id.to_json(): member.content_hash
                       for member in inputs.ruleset.members})
    if not report.passed:
        completed_at = now()
        record = RulesetBuildRecord(
            build_id=build_id, ruleset_id=inputs.ruleset.ruleset_id,
            started_at=started_at, completed_at=completed_at, built_by=built_by,
            outcome="REFUSED", member_count=len(inputs.definitions),
            issue_codes=report.codes)
        return BuildResult(manifest=None, files={},  # type: ignore[arg-type]
                           ruleset_content_hash="", record=record,
                           report=report)

    # The artifact's own directory name, which is the ruleset's public id.
    # Not os.path.relpath(destination): that resolves against the process's
    # working directory, so the same build run from two directories would
    # record two different paths. The build log is excluded from every hash,
    # but a per-machine value in a published file is a per-machine value
    # whether or not anything hashes it.
    artifact_relative_path = os.path.basename(
        os.path.normpath(destination)).replace(os.sep, "/")
    manifest, files, content_hash = compose_artifact(
        inputs, built_by=built_by, started_at=started_at,
        completed_at=now(), build_id=build_id,
        artifact_relative_path=artifact_relative_path)

    if publish:
        publish_atomically(destination, files)

    completed_at = now()
    record = RulesetBuildRecord(
        build_id=build_id, ruleset_id=inputs.ruleset.ruleset_id,
        started_at=started_at, completed_at=completed_at, built_by=built_by,
        outcome="SUCCEEDED", manifest_hash=manifest.content_hash(),
        ruleset_content_hash=content_hash, member_count=len(manifest.members),
        artifact_relative_path=artifact_relative_path)
    return BuildResult(manifest=manifest, files=files,
                       ruleset_content_hash=content_hash, record=record,
                       report=report)
