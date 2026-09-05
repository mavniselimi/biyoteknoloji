# -*- coding: utf-8 -*-
"""Assembling, gating and sealing an evidence build (WP-08).

Standard library plus :mod:`pgx.domain`, :mod:`pgx.ingestion`,
:mod:`pgx.normalization` and :mod:`pgx.evidence`.

**What an evidence build is.** One immutable directory holding every source
record read out of one raw snapshot, against one canonical build, under one set
of stated rule versions: the records, their exact source wording, their
canonical entity links, their publications, every raw locator that contributed,
and every issue found while reading them.

**What it is not.** Not a curation, not a rule, not an approval. Producing one
says nothing about whether the source statements are correct, and the dataset
it describes stays ``BUILDING``.

**Two modes, and the difference matters.** ``PRODUCTION`` fails closed: any
blocking finding refuses the build outright. ``LEGACY_MIGRATION`` proceeds and
stores every blocking finding visibly, marking the build and each affected
record ineligible for production. Quarantine records blockers - it does not
downgrade them to warnings, and a caller cannot ask for production eligibility
it has not earned.

**Determinism.** Given the same snapshot, the same canonical build and the same
identity allocation, two builds are byte-identical apart from the manifest's
``built_at`` and the checksums file that covers it. Every list is sorted by a
stated key, every JSON is canonically encoded, and no wall-clock value enters a
content hash.

**Sealing.** Assembled in a staging directory on the same filesystem and moved
with :func:`os.rename`, which fails rather than overwrites. ``os.replace`` is
deliberately not used, and there is no force flag: an evidence build that could
be rewritten would make every hash recorded against it a claim about nothing.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import (Any, Dict, Iterable, List, Mapping, Optional, Sequence,
                    Tuple)

from pgx.domain.hashing import canonical_json, ensure_utc, sha256_digest
from pgx.ingestion.snapshots import SnapshotManager
from pgx.normalization.build import read_build_manifest, verify_build
from pgx.evidence.allocation import (EVIDENCE_ALLOCATION_FORMAT_VERSION,
                                     EvidenceAllocation,
                                     EvidenceAllocationResult,
                                     allocate_evidence_identities,
                                     read_evidence_allocation)
from pgx.evidence.errors import EvidenceBuildError, EvidenceGateError
from pgx.evidence.extract import (EXTRACTION_RULE_VERSION, CanonicalIndex,
                                  ExtractionResult, extract_source_records)
from pgx.evidence.models import (EVIDENCE_RECORD_VERSION,
                                 RECORD_TYPE_MAP_VERSION, EvidenceRecordDraft,
                                 EvidenceRecordType, ImportIssue,
                                 ImportIssueCode, IssueSeverity)
from pgx.evidence.publications import PUBLICATION_PARSER_VERSION

__all__ = [
    "EVIDENCE_BUILD_FILES",
    "EVIDENCE_BUILD_LAYOUT_VERSION",
    "PROVENANCE_BEARING_FILES",
    "EvidenceBuild",
    "EvidenceBuildComparison",
    "EvidenceBuildRequest",
    "EvidenceBuildResult",
    "ImportMode",
    "build_evidence",
    "compare_evidence_builds",
    "evidence_build_key",
    "read_evidence_manifest",
    "verify_evidence_build",
    "write_evidence_build",
]

#: Bumped when the directory layout or the manifest shape changes.
EVIDENCE_BUILD_LAYOUT_VERSION = "pgx-evidence-build/1"

#: Every file a sealed evidence build contains. Fixed, so a reader can tell
#: "this build predates a file" from "this build is missing a file".
EVIDENCE_BUILD_FILES: Tuple[str, ...] = (
    "manifest.json",
    "evidence-identity-allocation.json",
    "evidence-records.ndjson",
    "evidence-text-fragments.ndjson",
    "evidence-entity-links.ndjson",
    "evidence-provenance.ndjson",
    "publication-references.ndjson",
    "import-issues.ndjson",
    "checksums.sha256",
)

#: Files that legitimately differ between two builds of identical content.
#: ``manifest.json`` carries ``built_at``; ``checksums.sha256`` covers it.
PROVENANCE_BEARING_FILES: Tuple[str, ...] = (
    "manifest.json",
    "checksums.sha256",
)

_STAGING_PREFIX = ".staging-evidence-"


class ImportMode(str, Enum):
    """Whether this import may produce production-eligible evidence."""

    #: Fails closed. Any blocking finding refuses the build.
    PRODUCTION = "PRODUCTION"
    #: Proceeds and quarantines. Blocking findings are stored, counted, and
    #: make the build and the affected records production-ineligible.
    LEGACY_MIGRATION = "LEGACY_MIGRATION"

    def __str__(self) -> str:
        return self.value


def evidence_build_key(dataset_public_id: str, content_hash: str) -> str:
    """The stable name for one build: dataset plus what it contains."""
    digest = content_hash.split(":", 1)[-1]
    return "%s/%s" % (dataset_public_id, digest[:16])


@dataclass(frozen=True)
class EvidenceBuildRequest:
    """Everything one evidence build needs, stated up front."""

    snapshot_root: str
    canonical_build_path: str
    output_root: str
    mode: ImportMode = ImportMode.PRODUCTION
    allocation_path: Optional[str] = None
    allow_new_identities: bool = False
    source_policy_status: Optional[str] = None
    now: Optional[_dt.datetime] = None
    build_note: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("snapshot_root", "canonical_build_path", "output_root"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise EvidenceBuildError(
                    "EvidenceBuildRequest.%s must be a non-empty path" % name,
                    code="INVALID_REQUEST")
        if not isinstance(self.mode, ImportMode):
            raise EvidenceBuildError("mode must be an ImportMode",
                                     code="INVALID_REQUEST")


@dataclass(frozen=True)
class EvidenceBuild:
    """The complete in-memory build, before anything is written.

    Separated from writing on purpose: every assertion a test wants to make -
    that no project field survived, that a conflict blocked, that a locator was
    retained - can be made without touching a filesystem.
    """

    dataset_public_id: str
    mode: ImportMode
    snapshot_manifest_hash: str
    snapshot_content_hash: str
    snapshot_state: str
    snapshot_kind: str
    canonical_build_key: str
    canonical_build_content_hash: str
    records: Tuple[EvidenceRecordDraft, ...]
    allocation: EvidenceAllocation
    allocation_result: EvidenceAllocationResult
    extraction: ExtractionResult
    gate_issues: Tuple[ImportIssue, ...]
    source_policy_status: Optional[str] = None
    built_at: Optional[_dt.datetime] = None
    build_note: Optional[str] = None

    @property
    def rule_versions(self) -> Dict[str, str]:
        """Every rule version this build depended on.

        Recorded together because a build is only comparable with one produced
        under the same set: a record count from one extraction rule and a count
        from another are two measurements sharing a name.
        """
        return {
            "evidence_build_layout_version": EVIDENCE_BUILD_LAYOUT_VERSION,
            "evidence_record_version": EVIDENCE_RECORD_VERSION,
            "record_type_map_version": RECORD_TYPE_MAP_VERSION,
            "extraction_rule_version": EXTRACTION_RULE_VERSION,
            "publication_parser_version": PUBLICATION_PARSER_VERSION,
            "allocation_format_version": EVIDENCE_ALLOCATION_FORMAT_VERSION,
        }

    @property
    def all_issues(self) -> Tuple[ImportIssue, ...]:
        return tuple(sorted(
            tuple(self.gate_issues) + tuple(self.extraction.issues)
            + self.extraction.record_issues,
            key=lambda item: item.key))

    @property
    def blocking_issues(self) -> Tuple[ImportIssue, ...]:
        return tuple(item for item in self.all_issues if item.blocking)

    @property
    def production_eligible_records(self) -> Tuple[EvidenceRecordDraft, ...]:
        """Records that could support a rule, if the build itself could.

        A record is only eligible when the *build* is: a quarantined snapshot
        makes every record in it quarantined, whatever the record itself says.
        """
        if not self.is_production_eligible:
            return ()
        return tuple(item for item in self.records
                     if item.is_production_eligible)

    @property
    def is_production_eligible(self) -> bool:
        """Whether this build may supply evidence to a rule.

        A build in migration mode is never eligible, and neither is one with a
        blocking gate finding. There is no argument that overrides either.
        """
        return (self.mode is ImportMode.PRODUCTION
                and not self.blocking_issues)

    @property
    def lifecycle_labels(self) -> Tuple[str, ...]:
        """What this build is, stated as labels a reader cannot miss."""
        labels = ["NOT_CURATED", "NOT_EXECUTABLE"]
        if self.mode is ImportMode.LEGACY_MIGRATION:
            labels.insert(0, "LEGACY_MIGRATION")
        if not self.is_production_eligible:
            labels.insert(0, "QUARANTINED")
            labels.append("NOT_PUBLICATION_ELIGIBLE")
        return tuple(labels)

    def content_identity(self) -> Dict[str, Any]:
        """What two builds of the same inputs must agree on, byte for byte."""
        return {
            "evidence_build_layout_version": EVIDENCE_BUILD_LAYOUT_VERSION,
            "dataset_public_id": self.dataset_public_id,
            "mode": self.mode.value,
            "snapshot_manifest_hash": self.snapshot_manifest_hash,
            "snapshot_content_hash": self.snapshot_content_hash,
            "canonical_build_key": self.canonical_build_key,
            "canonical_build_content_hash": self.canonical_build_content_hash,
            "rule_versions": self.rule_versions,
            "allocation_content_hash": self.allocation.content_hash(),
            "source_policy_status": self.source_policy_status,
            "records": [record.content_identity() for record in self.records],
            "record_identities": [
                {"natural_key": record.natural_key.to_string(),
                 "record_uuid": record.record_uuid}
                for record in self.records],
            "gate_issues": [issue.to_json() for issue in self.gate_issues],
        }

    def content_hash(self) -> str:
        return sha256_digest(self.content_identity())

    @property
    def build_key(self) -> str:
        return evidence_build_key(self.dataset_public_id, self.content_hash())

    def summary(self) -> Dict[str, Any]:
        """Counts, every one derived from the build's own contents."""
        by_type = {
            record_type.value: sum(
                1 for item in self.records
                if item.natural_key.record_type is record_type)
            for record_type in EvidenceRecordType}
        return {
            "dataset_public_id": self.dataset_public_id,
            "evidence_build_key": self.build_key,
            "content_hash": self.content_hash(),
            "mode": self.mode.value,
            "record_count": len(self.records),
            "record_counts_by_type": {name: count
                                      for name, count in sorted(by_type.items())
                                      if count},
            "production_eligible_record_count":
                len(self.production_eligible_records),
            "quarantined_record_count":
                len(self.records) - len(self.production_eligible_records),
            "locator_count": sum(len(item.locators) for item in self.records),
            "entity_link_count": sum(len(item.entity_links)
                                     for item in self.records),
            "gene_link_count": sum(len(item.genes) for item in self.records),
            "drug_link_count": sum(len(item.drugs) for item in self.records),
            "multi_gene_record_count": sum(1 for item in self.records
                                           if len(item.genes) > 1),
            "multi_drug_record_count": sum(1 for item in self.records
                                           if len(item.drugs) > 1),
            "text_fragment_count": sum(len(item.text_fragments)
                                       for item in self.records),
            "publication_reference_count": sum(len(item.publications)
                                               for item in self.records),
            "identified_publication_count": sum(
                1 for item in self.records for reference in item.publications
                if reference.identity),
            "issue_count": len(self.all_issues),
            "blocking_issue_count": len(self.blocking_issues),
            "issue_counts": _count_codes(self.all_issues),
            "version_status_counts": _count_attr(
                self.records, lambda item: item.version.status.value),
            "origin_status_counts": _count_attr(
                self.records, lambda item: item.attribution.origin_status.value),
            "origin_source_counts": _count_attr(
                self.records,
                lambda item: item.attribution.origin_source_key or "-"),
            "record_type_mapping_status_counts": _count_attr(
                self.records,
                lambda item: item.record_type_mapping.status.value),
            "payload_relation_counts": _count_attr(
                self.records,
                lambda item: str(item.normalized_metadata.get(
                    "payload_relation"))),
            "identity_minted_count": len(self.allocation_result.minted),
            "identity_reused_count": len(self.allocation_result.reused),
            "identity_allocation_size": len(self.allocation),
        }


@dataclass(frozen=True)
class EvidenceBuildResult:
    """A sealed evidence build, and where it landed."""

    build: EvidenceBuild
    build_path: str
    file_digests: Mapping[str, str]
    manifest: Mapping[str, Any]

    def to_json(self) -> Dict[str, Any]:
        payload = dict(self.build.summary())
        payload["build_path"] = self.build_path
        payload["files"] = dict(sorted(self.file_digests.items()))
        payload["lifecycle_labels"] = list(self.build.lifecycle_labels)
        return payload


# -- assembly -----------------------------------------------------------


def build_evidence(request: EvidenceBuildRequest) -> EvidenceBuild:
    """Verify the inputs, read the records and allocate their identities.

    Nothing is written here. The gates run first, in a fixed order, so that a
    build refused for a corrupt input never proceeds to read it.
    """
    gate_issues: List[ImportIssue] = []

    manager = SnapshotManager(os.path.dirname(os.path.abspath(
        request.snapshot_root.rstrip(os.sep))) or ".")
    verification = manager.verify_path(request.snapshot_root)
    if not verification.ok:
        gate_issues.append(ImportIssue(
            code=ImportIssueCode.RAW_SNAPSHOT_UNVERIFIED,
            severity=IssueSeverity.BLOCKING,
            subject=request.snapshot_root,
            detail=("the raw snapshot does not verify against its own "
                    "checksums: %s" % ", ".join(verification.codes))))
    manifest = manager.inspect_path(request.snapshot_root)

    if manifest.snapshot_state.value == "QUARANTINED":
        gate_issues.append(ImportIssue(
            code=ImportIssueCode.RAW_SNAPSHOT_QUARANTINED,
            severity=IssueSeverity.BLOCKING,
            subject=manifest.dataset_public_id,
            detail=("the raw snapshot is QUARANTINED. Importing evidence from "
                    "it is allowed so the data can be examined; producing "
                    "production evidence from it is not.")))
    if manifest.snapshot_kind.value == "LEGACY_IMPORT":
        gate_issues.append(ImportIssue(
            code=ImportIssueCode.RAW_SNAPSHOT_NOT_ACQUIRED,
            severity=IssueSeverity.BLOCKING,
            subject=manifest.dataset_public_id,
            detail=("the snapshot is a LEGACY_IMPORT: no acquisition run "
                    "records which endpoints were called or whether the "
                    "responses were complete, so this evidence set's "
                    "completeness relative to the source is unknown.")))

    canonical_ok, canonical_problems = verify_build(request.canonical_build_path)
    if not canonical_ok:
        gate_issues.append(ImportIssue(
            code=ImportIssueCode.CANONICAL_BUILD_UNVERIFIED,
            severity=IssueSeverity.BLOCKING,
            subject=request.canonical_build_path,
            detail=("the canonical build does not verify against its own "
                    "checksums: %s" % "; ".join(canonical_problems[:5]))))
    canonical_manifest = read_build_manifest(request.canonical_build_path)

    if canonical_manifest.get("dataset_public_id") != manifest.dataset_public_id:
        gate_issues.append(ImportIssue(
            code=ImportIssueCode.DATASET_ID_MISMATCH,
            severity=IssueSeverity.BLOCKING,
            subject=manifest.dataset_public_id,
            detail=("the canonical build describes dataset %r and the raw "
                    "snapshot is %r; evidence may not straddle two datasets"
                    % (canonical_manifest.get("dataset_public_id"),
                       manifest.dataset_public_id))))
    if canonical_manifest.get("snapshot_manifest_hash") != manifest.manifest_hash:
        gate_issues.append(ImportIssue(
            code=ImportIssueCode.MANIFEST_HASH_MISMATCH,
            severity=IssueSeverity.BLOCKING,
            subject=manifest.dataset_public_id,
            detail=("the canonical build was derived from snapshot manifest %s "
                    "and this snapshot's manifest is %s"
                    % (canonical_manifest.get("snapshot_manifest_hash"),
                       manifest.manifest_hash))))

    if request.source_policy_status is None:
        gate_issues.append(ImportIssue(
            code=ImportIssueCode.SOURCE_POLICY_MISSING,
            severity=IssueSeverity.BLOCKING,
            subject=manifest.dataset_public_id,
            detail=("no source-policy approval is on record for this dataset. "
                    "An unregistered source has no permissions rather than "
                    "unlimited ones.")))
    elif request.source_policy_status != "APPROVED":
        gate_issues.append(ImportIssue(
            code=ImportIssueCode.SOURCE_POLICY_NOT_APPROVED,
            severity=IssueSeverity.BLOCKING,
            subject=manifest.dataset_public_id,
            detail="the source policy status is %r, not APPROVED"
                   % request.source_policy_status))

    if request.mode is ImportMode.PRODUCTION and gate_issues:
        raise EvidenceGateError(
            "%d blocking finding(s) refuse a production evidence import: %s. "
            "The gate fails closed; use LEGACY_MIGRATION mode to record them "
            "and produce a quarantined build instead."
            % (len(gate_issues),
               ", ".join(sorted({item.code.value for item in gate_issues}))),
            issues=tuple(gate_issues))

    index = CanonicalIndex.from_build(request.canonical_build_path)
    extraction = extract_source_records(
        request.snapshot_root, manifest, index,
        str(canonical_manifest.get("canonical_build_key")),
        str(canonical_manifest.get("content_hash")))

    natural_keys = [draft.natural_key.to_string() for draft in extraction.drafts]
    duplicates = _duplicate_keys(natural_keys)
    for key in duplicates:
        gate_issues.append(ImportIssue(
            code=ImportIssueCode.DUPLICATE_NATURAL_KEY,
            severity=IssueSeverity.BLOCKING, subject=key,
            detail=("two extracted records share the natural key %r; one key "
                    "names one evidence record" % key)))

    existing = (read_evidence_allocation(request.allocation_path)
                if request.allocation_path else None)
    allocation_result = allocate_evidence_identities(
        manifest.dataset_public_id, natural_keys, existing=existing,
        allow_new=request.allow_new_identities, now=request.now,
        extraction_rule_version=EXTRACTION_RULE_VERSION)
    allocation = allocation_result.allocation

    records = tuple(
        draft.with_identity(allocation.uuid_for(draft.natural_key.to_string()))
        for draft in extraction.drafts)

    return EvidenceBuild(
        dataset_public_id=manifest.dataset_public_id,
        mode=request.mode,
        snapshot_manifest_hash=manifest.manifest_hash,
        snapshot_content_hash=manifest.snapshot_content_hash,
        snapshot_state=manifest.snapshot_state.value,
        snapshot_kind=manifest.snapshot_kind.value,
        canonical_build_key=str(canonical_manifest.get("canonical_build_key")),
        canonical_build_content_hash=str(canonical_manifest.get("content_hash")),
        records=records,
        allocation=allocation,
        allocation_result=allocation_result,
        extraction=extraction,
        gate_issues=tuple(sorted(gate_issues, key=lambda item: item.key)),
        source_policy_status=request.source_policy_status,
        built_at=ensure_utc(request.now or _dt.datetime.now(_dt.timezone.utc),
                            "now"),
        build_note=request.build_note)


# -- writing ------------------------------------------------------------


def write_evidence_build(build: EvidenceBuild,
                         output_root: str) -> EvidenceBuildResult:
    """Write a build into ``output_root/<dataset-id>`` and seal it atomically.

    Assembled in a staging directory beside the destination - same filesystem,
    so the final move is a rename rather than a copy - and moved with
    :func:`os.rename`, which refuses an existing target. ``os.replace`` is
    deliberately not used: it would silently overwrite a sealed build.
    """
    destination = os.path.join(output_root, build.dataset_public_id)
    if os.path.exists(destination):
        raise EvidenceBuildError(
            "an evidence build already exists at %s. Sealed builds are never "
            "overwritten; write the new build elsewhere and compare the two."
            % destination, code="BUILD_ALREADY_EXISTS")

    os.makedirs(output_root, exist_ok=True)
    staging = os.path.join(output_root, "%s%s.%d"
                           % (_STAGING_PREFIX, build.dataset_public_id,
                              os.getpid()))
    if os.path.exists(staging):
        raise EvidenceBuildError(
            "a staging directory already exists at %s; a previous build was "
            "interrupted. Inspect and remove it deliberately." % staging,
            code="STAGING_EXISTS")

    documents = _render_documents(build)
    try:
        os.makedirs(staging)
        digests: Dict[str, str] = {}
        for name in EVIDENCE_BUILD_FILES:
            if name == "checksums.sha256" or name not in documents:
                continue
            data = documents[name]
            with open(os.path.join(staging, name), "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            digests[name] = "sha256:" + _hex(data)

        checksums = _render_checksums(digests)
        with open(os.path.join(staging, "checksums.sha256"), "wb") as handle:
            handle.write(checksums)
            handle.flush()
            os.fsync(handle.fileno())
        digests["checksums.sha256"] = "sha256:" + _hex(checksums)

        _fsync_dir(staging)
        os.rename(staging, destination)
        _fsync_dir(output_root)
    except FileExistsError as exc:
        raise EvidenceBuildError(
            "sealing the build at %s failed because the destination appeared "
            "while it was being written: %s" % (destination, exc),
            code="BUILD_ALREADY_EXISTS") from exc
    except OSError as exc:
        raise EvidenceBuildError(
            "the evidence build could not be written to %s: %s"
            % (staging, exc), code="BUILD_WRITE_FAILED") from exc

    return EvidenceBuildResult(
        build=build, build_path=destination,
        file_digests=dict(sorted(digests.items())),
        manifest=json.loads(documents["manifest.json"].decode("utf-8")))


def _render_documents(build: EvidenceBuild) -> Dict[str, bytes]:
    """Render every build file as bytes, deterministically."""
    documents: Dict[str, bytes] = {
        "evidence-identity-allocation.json":
            _json_bytes(build.allocation.to_json()),
        "evidence-records.ndjson": _ndjson(
            record.to_json() for record in build.records),
        "evidence-text-fragments.ndjson": _ndjson(_fragment_rows(build)),
        "evidence-entity-links.ndjson": _ndjson(_entity_rows(build)),
        "evidence-provenance.ndjson": _ndjson(_provenance_rows(build)),
        "publication-references.ndjson": _ndjson(_publication_rows(build)),
        "import-issues.ndjson": _ndjson(
            issue.to_json() for issue in build.all_issues),
    }
    content_digests = {name: "sha256:" + _hex(data)
                       for name, data in sorted(documents.items())}
    documents["manifest.json"] = _json_bytes(
        _manifest_payload(build, content_digests))
    return documents


def _manifest_payload(build: EvidenceBuild,
                      file_digests: Mapping[str, str]) -> Dict[str, Any]:
    """The evidence build manifest.

    ``content_hash`` covers the build's contents, not the file digests, so it
    is stable across a layout change that only reorders bytes. The file digests
    are recorded beside it so a reader can check the directory it has.
    """
    return {
        "evidence_build_layout_version": EVIDENCE_BUILD_LAYOUT_VERSION,
        "dataset_public_id": build.dataset_public_id,
        "evidence_build_key": build.build_key,
        "content_hash": build.content_hash(),
        "mode": build.mode.value,
        "snapshot_manifest_hash": build.snapshot_manifest_hash,
        "snapshot_content_hash": build.snapshot_content_hash,
        "snapshot_state": build.snapshot_state,
        "snapshot_kind": build.snapshot_kind,
        "canonical_build_key": build.canonical_build_key,
        "canonical_build_content_hash": build.canonical_build_content_hash,
        "allocation_content_hash": build.allocation.content_hash(),
        "source_policy_status": build.source_policy_status,
        "rule_versions": build.rule_versions,
        "identity_minted_count": len(build.allocation_result.minted),
        "identity_reused_count": len(build.allocation_result.reused),
        "built_at": (build.built_at.isoformat().replace("+00:00", "Z")
                     if build.built_at else None),
        "build_note": build.build_note,
        "dataset_lifecycle_state": "BUILDING",
        "production_eligible": build.is_production_eligible,
        "lifecycle_labels": list(build.lifecycle_labels),
        "lifecycle_note": (
            "An evidence build records what sources stated and where each "
            "statement came from. It is not a curation, not a rule and not an "
            "approval, and it asserts nothing about whether the statements are "
            "scientifically correct. The dataset stays BUILDING."),
        "summary": build.summary(),
        "files": dict(sorted(file_digests.items())),
    }


def _fragment_rows(build: EvidenceBuild) -> List[Dict[str, Any]]:
    rows = []
    for record in build.records:
        for fragment in record.text_fragments:
            payload = fragment.to_json()
            payload["record_uuid"] = record.record_uuid
            payload["natural_key"] = record.natural_key.to_string()
            rows.append(payload)
    return sorted(rows, key=lambda row: (row["natural_key"],
                                         row["field_name"], row["ordinal"]))


def _entity_rows(build: EvidenceBuild) -> List[Dict[str, Any]]:
    rows = []
    for record in build.records:
        for link in record.entity_links:
            payload = link.to_json()
            payload["record_uuid"] = record.record_uuid
            payload["natural_key"] = record.natural_key.to_string()
            payload["canonical_build_key"] = record.canonical_build_key
            rows.append(payload)
    return sorted(rows, key=lambda row: (row["natural_key"],
                                         row["entity_type"],
                                         row["canonical_key"], row["role"]))


def _provenance_rows(build: EvidenceBuild) -> List[Dict[str, Any]]:
    """One row per link between an evidence record and a raw locator.

    Every locator survives, including all of a WP-07 duplicate group's. This is
    the file that answers "where did this come from", and the answer has to be
    complete.
    """
    rows = []
    for record in build.records:
        for locator in record.locators:
            payload = locator.to_json()
            payload["record_uuid"] = record.record_uuid
            payload["natural_key"] = record.natural_key.to_string()
            payload["source_payload_hash"] = record.source_payload_hash
            payload["evidence_content_hash"] = record.content_hash()
            rows.append(payload)
    return sorted(rows, key=lambda row: (row["natural_key"],
                                         row["artifact_path"],
                                         row["pointer"] or "",
                                         str(row["csv_row_number"] or "")))


def _publication_rows(build: EvidenceBuild) -> List[Dict[str, Any]]:
    rows = []
    for record in build.records:
        for reference in record.publications:
            payload = reference.to_json()
            payload["record_uuid"] = record.record_uuid
            payload["natural_key"] = record.natural_key.to_string()
            rows.append(payload)
    return sorted(rows, key=lambda row: (row["natural_key"], row["ordinal"]))


# -- reading back -------------------------------------------------------


def read_evidence_manifest(build_path: str) -> Dict[str, Any]:
    """Read a sealed evidence build's manifest."""
    manifest_path = os.path.join(build_path, "manifest.json")
    if not os.path.isfile(manifest_path):
        raise EvidenceBuildError(
            "no evidence build manifest at %s" % manifest_path,
            code="MANIFEST_MISSING")
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        raise EvidenceBuildError(
            "the evidence build manifest at %s is unreadable: %s"
            % (manifest_path, exc), code="MANIFEST_CORRUPT") from exc
    if payload.get("evidence_build_layout_version") != \
            EVIDENCE_BUILD_LAYOUT_VERSION:
        raise EvidenceBuildError(
            "build at %s declares layout %r; this build reads %r"
            % (build_path, payload.get("evidence_build_layout_version"),
               EVIDENCE_BUILD_LAYOUT_VERSION),
            code="LAYOUT_VERSION_MISMATCH")
    return payload


def verify_evidence_build(build_path: str) -> Tuple[bool, Tuple[str, ...]]:
    """Re-check a sealed evidence build against its own recorded digests."""
    problems: List[str] = []
    checksums_path = os.path.join(build_path, "checksums.sha256")
    if not os.path.isfile(checksums_path):
        return False, ("no checksums.sha256 in %s" % build_path,)
    recorded: Dict[str, str] = {}
    with open(checksums_path, "r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            parts = text.split("  ", 1)
            if len(parts) != 2 or len(parts[0]) != 64:
                problems.append("checksums.sha256 line %d is malformed" % number)
                continue
            recorded[parts[1]] = parts[0]

    present = set(_list_files(build_path))
    for name in sorted(recorded):
        path = os.path.join(build_path, name)
        if not os.path.isfile(path):
            problems.append("%s is recorded in checksums.sha256 and absent"
                            % name)
            continue
        if _file_digest(path) != recorded[name]:
            problems.append("%s does not match its recorded digest" % name)
    for name in sorted(present - set(recorded) - {"checksums.sha256"}):
        problems.append("%s is present and not recorded in checksums.sha256"
                        % name)
    return not problems, tuple(problems)


@dataclass(frozen=True)
class EvidenceBuildComparison:
    """Whether two sealed evidence builds are the same build."""

    left_path: str
    right_path: str
    identical_files: Tuple[str, ...]
    differing_files: Tuple[str, ...]
    only_left: Tuple[str, ...]
    only_right: Tuple[str, ...]
    left_content_hash: Optional[str]
    right_content_hash: Optional[str]

    @property
    def content_hash_matches(self) -> bool:
        return (self.left_content_hash is not None
                and self.left_content_hash == self.right_content_hash)

    @property
    def byte_identical_apart_from_provenance(self) -> bool:
        return not tuple(name for name in self.differing_files
                         if name not in PROVENANCE_BEARING_FILES)

    @property
    def both_complete(self) -> bool:
        """Whether both sides hold every file a sealed build must have.

        Checked because the other three conditions are all satisfiable by two
        builds that are equally incomplete: two directories holding only a
        matching manifest agree with each other perfectly and reproduce
        nothing.
        """
        present = set(self.identical_files) | set(self.differing_files)
        return all(name in present for name in EVIDENCE_BUILD_FILES)

    @property
    def reproducible(self) -> bool:
        return (self.content_hash_matches
                and self.byte_identical_apart_from_provenance
                and self.both_complete
                and not self.only_left and not self.only_right)

    def to_json(self) -> Dict[str, Any]:
        return {
            "left_path": self.left_path,
            "right_path": self.right_path,
            "reproducible": self.reproducible,
            "content_hash_matches": self.content_hash_matches,
            "byte_identical_apart_from_provenance":
                self.byte_identical_apart_from_provenance,
            "both_complete": self.both_complete,
            "left_content_hash": self.left_content_hash,
            "right_content_hash": self.right_content_hash,
            "identical_files": list(self.identical_files),
            "differing_files": list(self.differing_files),
            "only_left": list(self.only_left),
            "only_right": list(self.only_right),
            "note": ("manifest.json records built_at and checksums.sha256 "
                     "covers it, so those two differ between runs by design. "
                     "Every other file must match byte for byte."),
        }


def compare_evidence_builds(left_path: str,
                            right_path: str) -> EvidenceBuildComparison:
    """Compare two sealed evidence builds file by file and by content hash."""
    left_files = _list_files(left_path)
    right_files = _list_files(right_path)
    identical, differing = [], []
    for name in sorted(set(left_files) & set(right_files)):
        if _file_digest(os.path.join(left_path, name)) == \
                _file_digest(os.path.join(right_path, name)):
            identical.append(name)
        else:
            differing.append(name)
    return EvidenceBuildComparison(
        left_path=left_path, right_path=right_path,
        identical_files=tuple(identical), differing_files=tuple(differing),
        only_left=tuple(sorted(set(left_files) - set(right_files))),
        only_right=tuple(sorted(set(right_files) - set(left_files))),
        left_content_hash=_content_hash_of(left_path),
        right_content_hash=_content_hash_of(right_path))


# -- helpers ------------------------------------------------------------


def _count_codes(issues: Sequence[ImportIssue]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for issue in issues:
        counts[issue.code.value] = counts.get(issue.code.value, 0) + 1
    return dict(sorted(counts.items()))


def _count_attr(records: Sequence[EvidenceRecordDraft], reader) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for record in records:
        key = reader(record)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _duplicate_keys(keys: Sequence[str]) -> Tuple[str, ...]:
    seen: Dict[str, int] = {}
    for key in keys:
        seen[key] = seen.get(key, 0) + 1
    return tuple(sorted(key for key, count in seen.items() if count > 1))


def _json_bytes(payload: Any) -> bytes:
    return (canonical_json(payload) + "\n").encode("utf-8")


def _ndjson(rows: Iterable[Mapping[str, Any]]) -> bytes:
    lines = [canonical_json(row) for row in rows]
    if not lines:
        return b""
    return ("\n".join(lines) + "\n").encode("utf-8")


def _render_checksums(digests: Mapping[str, str]) -> bytes:
    lines = ["%s  %s" % (digests[name].split(":", 1)[-1], name)
             for name in sorted(digests)]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _hex(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def _file_digest(path: str) -> str:
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _list_files(build_path: str) -> Tuple[str, ...]:
    if not os.path.isdir(build_path):
        raise EvidenceBuildError("no evidence build directory at %s"
                                 % build_path, code="BUILD_MISSING")
    return tuple(sorted(name for name in os.listdir(build_path)
                        if os.path.isfile(os.path.join(build_path, name))))


def _content_hash_of(build_path: str) -> Optional[str]:
    try:
        return read_evidence_manifest(build_path).get("content_hash")
    except EvidenceBuildError:
        return None


def _fsync_dir(path: str) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)
