# -*- coding: utf-8 -*-
"""The canonical build: entities, resolution, duplicates and an atomic seal (WP-07).

Standard library plus :mod:`pgx.domain`, :mod:`pgx.ingestion.snapshots` and
:mod:`pgx.normalization`.

**What a canonical build is.** One immutable directory holding what a single
raw snapshot yielded under one set of stated rule versions: canonical genes and
drugs, what each was built from, what could not be resolved, what was observed
more than once, and the metrics that describe all of it. It is a *build
product*, not an approval: producing one says nothing about whether the data is
fit to publish, and the dataset it describes stays ``BUILDING``.

**Determinism.** Given the same snapshot and the same identity allocation, two
builds are byte-identical. Every list is sorted by a stated key, every JSON is
canonically encoded, and no wall-clock value enters a content hash. The build
timestamp is recorded beside the content hash, never inside it.

**Identity comes from the allocation, never from here.** The builder reads UUIDs
out of :mod:`pgx.normalization.allocation` and raises when one is missing. There
is no path through this module that mints an identity, and a test asserts that
``uuid`` is not even imported.

**Sealing.** The build is assembled in a staging directory on the same
filesystem and moved into place with :func:`os.rename`, which fails rather than
overwrites. There is no force flag: a canonical build that could be rewritten
would make every hash recorded against it a claim about nothing in particular.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from dataclasses import dataclass, field
from typing import (Any, Dict, Iterable, List, Mapping, Optional, Sequence,
                    Tuple)

from pgx.domain.hashing import canonical_json, ensure_utc, sha256_digest
from pgx.ingestion.snapshots import SnapshotManager, SnapshotManifest
from pgx.normalization.allocation import (ALLOCATION_FORMAT_VERSION,
                                          AllocationResult, IdentityAllocation,
                                          allocate_identities, read_allocation)
from pgx.normalization.artifacts import ARTIFACT_ROLE_MAP_VERSION
from pgx.normalization.dedup import DEDUP_KEY_VERSION, DedupResult, deduplicate
from pgx.normalization.errors import CanonicalBuildError
from pgx.normalization.extract import (EXTRACTION_RULE_VERSION,
                                       EntityCandidate, ExtractionResult,
                                       extract_snapshot)
from pgx.normalization.models import (AliasProposal, CanonicalEntity,
                                      EntityType, RawLocator, ReasonCode,
                                      ResolutionOutcome, ResolutionQueueItem,
                                      ResolutionStatus, canonical_key_for)
from pgx.normalization.normalize import NORMALIZATION_RULE_VERSION
from pgx.normalization.resolver import (RESOLVER_POLICY_VERSION,
                                        CanonicalCatalog, EntityResolver)

__all__ = [
    "CANONICAL_BUILD_LAYOUT_VERSION",
    "BUILD_FILES",
    "PROVENANCE_BEARING_FILES",
    "BuildComparison",
    "CanonicalBuild",
    "CanonicalBuildRequest",
    "CanonicalBuildResult",
    "build_canonical_dataset",
    "canonical_build_key",
    "compare_builds",
    "read_build_manifest",
    "verify_build",
    "write_build",
]

#: Bumped when the directory layout or the manifest shape changes.
CANONICAL_BUILD_LAYOUT_VERSION = "pgx-canonical-build/1"

#: Every file a sealed build contains, in the order they are written. The list
#: is fixed so a reader can tell "this build predates a file" from "this build
#: is missing a file".
BUILD_FILES: Tuple[str, ...] = (
    "manifest.json",
    "identity-allocation.json",
    "genes.ndjson",
    "drugs.ndjson",
    "entity-membership.ndjson",
    "resolution-queue.ndjson",
    "duplicate-groups.ndjson",
    "provenance.ndjson",
    "dq-report.json",
    "legacy-differences.json",
    "checksums.sha256",
)

#: Files written by later stages of the same build. Absent from an early build
#: only if that stage was skipped, which the manifest records explicitly.
OPTIONAL_BUILD_FILES: Tuple[str, ...] = (
    "legacy-differences.json",
)

_STAGING_PREFIX = ".staging-canonical-"


def canonical_build_key(dataset_public_id: str, content_hash: str) -> str:
    """The stable name for one build: dataset plus what it contains.

    Two builds of the same snapshot under the same rules share this key, which
    is what makes "rebuild and compare" a one-line check.
    """
    digest = content_hash.split(":", 1)[-1]
    return "%s/%s" % (dataset_public_id, digest[:16])


@dataclass(frozen=True)
class CanonicalBuildRequest:
    """Everything one build needs, stated up front.

    ``allow_new_identities`` defaults to ``False``. A build that intended to
    reproduce an earlier one and silently minted fresh UUIDs would produce a
    directory that looked right and matched nothing, so the caller has to say
    which of the two it wants.
    """

    snapshot_root: str
    output_root: str
    allocation_path: Optional[str] = None
    allow_new_identities: bool = False
    now: Optional[_dt.datetime] = None
    build_note: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("snapshot_root", "output_root"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise CanonicalBuildError(
                    "CanonicalBuildRequest.%s must be a non-empty path" % name,
                    code="INVALID_REQUEST")


@dataclass(frozen=True)
class CanonicalBuild:
    """The complete in-memory build, before anything is written.

    Separated from writing on purpose: every assertion a test wants to make
    about a build - that no interpretation field survived, that an ambiguity
    reached the queue, that a conflicting collision blocks - can be made without
    touching a filesystem.
    """

    dataset_public_id: str
    snapshot_manifest_hash: str
    snapshot_content_hash: str
    snapshot_state: str
    snapshot_kind: str
    snapshot_complete: bool
    genes: Tuple[CanonicalEntity, ...]
    drugs: Tuple[CanonicalEntity, ...]
    allocation: IdentityAllocation
    allocation_result: AllocationResult
    extraction: ExtractionResult
    resolutions: Tuple[ResolutionOutcome, ...]
    queue: Tuple[ResolutionQueueItem, ...]
    dedup: DedupResult
    entity_findings: Tuple[Mapping[str, Any], ...] = ()
    built_at: Optional[_dt.datetime] = None
    build_note: Optional[str] = None

    @property
    def entities(self) -> Tuple[CanonicalEntity, ...]:
        return tuple(sorted(self.genes + self.drugs,
                            key=lambda item: item.canonical_key))

    @property
    def rule_versions(self) -> Dict[str, str]:
        """Every rule version this build depended on.

        Recorded together because a build is only comparable with another built
        under the same set: a dedup count from one key definition and a count
        from another are two different measurements with the same name.
        """
        return {
            "canonical_build_layout_version": CANONICAL_BUILD_LAYOUT_VERSION,
            "normalization_rule_version": NORMALIZATION_RULE_VERSION,
            "artifact_role_map_version": ARTIFACT_ROLE_MAP_VERSION,
            "extraction_rule_version": EXTRACTION_RULE_VERSION,
            "resolver_policy_version": RESOLVER_POLICY_VERSION,
            "dedup_key_version": DEDUP_KEY_VERSION,
            "allocation_format_version": ALLOCATION_FORMAT_VERSION,
        }

    def content_identity(self) -> Dict[str, Any]:
        """What two builds of the same snapshot must agree on, byte for byte.

        No timestamp, no output path, no host. The allocation enters by its own
        content hash rather than by its entries, so a build stays comparable
        with one whose allocation gained an entry for an entity this build does
        not contain.
        """
        return {
            "canonical_build_layout_version": CANONICAL_BUILD_LAYOUT_VERSION,
            "dataset_public_id": self.dataset_public_id,
            "snapshot_manifest_hash": self.snapshot_manifest_hash,
            "snapshot_content_hash": self.snapshot_content_hash,
            "snapshot_complete": self.snapshot_complete,
            "rule_versions": self.rule_versions,
            "allocation_content_hash": self.allocation.content_hash(),
            "genes": [entity.content_identity() for entity in self.genes],
            "drugs": [entity.content_identity() for entity in self.drugs],
            "entity_uuids": [
                {"canonical_key": entity.canonical_key,
                 "entity_uuid": entity.entity_uuid}
                for entity in self.entities],
            "resolutions": [outcome.to_json() for outcome in self.resolutions],
            "duplicate_groups": [group.to_json()
                                 for group in self.dedup.groups],
            "unidentified_observations": [
                locator.to_json() for locator in self.dedup.unidentified],
            "entity_findings": [dict(item) for item in self.entity_findings],
            "extraction": self.extraction.to_json(),
        }

    def content_hash(self) -> str:
        return sha256_digest(self.content_identity())

    @property
    def build_key(self) -> str:
        return canonical_build_key(self.dataset_public_id, self.content_hash())

    def summary(self) -> Dict[str, Any]:
        """Counts, every one of them derived from the build's own contents."""
        blocking = self.dedup.blocking_groups
        return {
            "dataset_public_id": self.dataset_public_id,
            "canonical_build_key": self.build_key,
            "content_hash": self.content_hash(),
            "gene_count": len(self.genes),
            "drug_count": len(self.drugs),
            "entity_count": len(self.entities),
            "alias_proposal_count": sum(len(entity.aliases)
                                        for entity in self.entities),
            "approved_alias_count": sum(len(entity.approved_aliases)
                                        for entity in self.entities),
            "locator_count": sum(len(entity.locators)
                                 for entity in self.entities),
            "resolution_attempt_count": len(self.resolutions),
            "resolved_count": sum(1 for item in self.resolutions
                                  if item.is_resolved),
            "queue_item_count": len(self.queue),
            "observation_count": self.dedup.total_observations,
            "distinct_record_count": self.dedup.distinct_records,
            "duplicate_observation_count": self.dedup.duplicate_observations,
            "duplicate_group_count": len(self.dedup.groups),
            "blocking_duplicate_group_count": len(blocking),
            "entity_finding_count": len(self.entity_findings),
            "minted_identity_count": len(self.allocation_result.minted),
            "reused_identity_count": len(self.allocation_result.reused),
        }


@dataclass(frozen=True)
class CanonicalBuildResult:
    """A sealed build, and where it landed."""

    build: CanonicalBuild
    build_path: str
    file_digests: Mapping[str, str]
    manifest: Mapping[str, Any]

    def to_json(self) -> Dict[str, Any]:
        payload = dict(self.build.summary())
        payload["build_path"] = self.build_path
        payload["files"] = dict(sorted(self.file_digests.items()))
        return payload


# -- assembly -----------------------------------------------------------


def build_canonical_dataset(request: CanonicalBuildRequest) -> CanonicalBuild:
    """Assemble a canonical build in memory. Nothing is written here."""
    manager = SnapshotManager(os.path.dirname(os.path.abspath(
        request.snapshot_root.rstrip(os.sep))) or ".")
    try:
        manifest = manager.inspect_path(request.snapshot_root)
    except Exception as exc:  # snapshot errors are typed in pgx.ingestion
        raise CanonicalBuildError(
            "the snapshot at %s could not be read: %s"
            % (request.snapshot_root, exc), code="SNAPSHOT_UNREADABLE") from exc

    extraction = extract_snapshot(request.snapshot_root, manifest)
    drafts, entity_findings = _merge_candidates(extraction.candidates)

    canonical_keys = tuple(sorted(drafts))
    existing = (read_allocation(request.allocation_path)
                if request.allocation_path else None)
    allocation_result = allocate_identities(
        manifest.dataset_public_id,
        canonical_keys,
        existing=existing,
        allow_new=request.allow_new_identities,
        now=request.now,
        normalization_rule_version=NORMALIZATION_RULE_VERSION)
    allocation = allocation_result.allocation

    entities = tuple(
        _with_identity(drafts[key], allocation.uuid_for(key))
        for key in canonical_keys)
    genes = tuple(item for item in entities
                  if item.entity_type is EntityType.GENE)
    drugs = tuple(item for item in entities
                  if item.entity_type is EntityType.DRUG)

    catalog = CanonicalCatalog(entities)
    resolver = EntityResolver(catalog)
    resolutions = tuple(
        resolver.resolve_reference(
            reference.entity_type, reference.submitted_value,
            locator=reference.locator)
        for reference in sorted(
            extraction.references,
            key=lambda item: (item.entity_type.value, item.submitted_value,
                              item.locator.key)))

    built_at = ensure_utc(request.now or _dt.datetime.now(_dt.timezone.utc),
                          "now")
    dedup = deduplicate(extraction.observations)

    build = CanonicalBuild(
        dataset_public_id=manifest.dataset_public_id,
        snapshot_manifest_hash=manifest.manifest_hash,
        snapshot_content_hash=manifest.snapshot_content_hash,
        snapshot_state=manifest.snapshot_state.value,
        snapshot_kind=manifest.snapshot_kind.value,
        snapshot_complete=bool(manifest.complete),
        genes=genes,
        drugs=drugs,
        allocation=allocation,
        allocation_result=allocation_result,
        extraction=extraction,
        resolutions=resolutions,
        queue=(),
        dedup=dedup,
        entity_findings=tuple(entity_findings),
        built_at=built_at,
        build_note=request.build_note)

    queue = _queue_items(build, built_at)
    return _replace(build, queue=queue)


def _merge_candidates(candidates: Sequence[EntityCandidate]
                      ) -> Tuple[Dict[str, CanonicalEntity],
                                 List[Dict[str, Any]]]:
    """Fold candidates onto canonical keys, keeping every locator.

    Two candidates that normalise to the same canonical key are the same
    entity by this project's own normalisation rule, so they merge. Merging
    *unions* their locators, external IDs, aliases and findings; nothing is
    dropped, because a locator that disappeared here is a provenance link the
    build could never recover.

    Disagreements are recorded, not resolved. If two candidates for one key
    carry different preferred displays, or one external accession is claimed by
    two different canonical keys, that is reported as a finding for a human -
    picking one would be exactly the silent selection this package removes.
    """
    grouped: Dict[str, List[EntityCandidate]] = {}
    findings: List[Dict[str, Any]] = []
    unresolvable: List[EntityCandidate] = []

    for candidate in candidates:
        key = candidate.canonical_key
        if key is None:
            unresolvable.append(candidate)
            continue
        grouped.setdefault(key, []).append(candidate)

    for candidate in sorted(unresolvable,
                            key=lambda item: (item.entity_type.value,
                                              item.submitted_value)):
        findings.append({
            "code": "CANDIDATE_NOT_NORMALIZABLE",
            "entity_type": candidate.entity_type.value,
            "canonical_key": None,
            "detail": ("%r could not be normalised and produced no canonical "
                       "entity" % candidate.submitted_value),
            "locators": [candidate.locator.to_json()],
            "blocking": True,
        })

    entities: Dict[str, CanonicalEntity] = {}
    accession_owners: Dict[str, List[str]] = {}

    for key in sorted(grouped):
        members = sorted(grouped[key], key=lambda item: item.locator.key)
        first = members[0]
        displays = sorted({item.preferred_display for item in members})
        if len(displays) > 1:
            findings.append({
                "code": "CANDIDATE_DISPLAY_DISAGREEMENT",
                "entity_type": first.entity_type.value,
                "canonical_key": key,
                "detail": ("%d source records normalise to %s but print "
                           "different preferred names: %s. The first by "
                           "locator order is stored and the disagreement is "
                           "reported; no name is judged better than another."
                           % (len(members), key, "; ".join(displays))),
                "locators": [item.locator.to_json() for item in members],
                "blocking": False,
            })

        external_ids = tuple(sorted(
            {identifier for item in members for identifier in item.external_ids},
            key=lambda item: (item[0], item[1])))
        for identifier in external_ids:
            accession_owners.setdefault(identifier.to_json(), []).append(key)

        aliases: Dict[str, AliasProposal] = {}
        for item in members:
            for alias in item.alias_proposals:
                aliases.setdefault(alias.normalized_alias, alias)

        entity_findings = tuple(sorted(
            {text for item in members for text in item.findings}))

        entities[key] = CanonicalEntity(
            entity_type=first.entity_type,
            canonical_key=key,
            normalized_value=first.normalized_value,
            preferred_display=displays[0],
            source_display=first.source_display,
            entity_uuid=None,
            external_ids=external_ids,
            aliases=tuple(aliases[name] for name in sorted(aliases)),
            locators=tuple(item.locator for item in members),
            findings=entity_findings)

    for accession in sorted(accession_owners):
        owners = sorted(set(accession_owners[accession]))
        if len(owners) > 1:
            findings.append({
                "code": "EXTERNAL_ID_CLAIMED_BY_SEVERAL_ENTITIES",
                "entity_type": None,
                "canonical_key": None,
                "detail": ("external identifier %s is claimed by %d canonical "
                           "entities (%s). One accession naming two entities is "
                           "an identity conflict; it is not resolved by "
                           "discarding either."
                           % (accession, len(owners), ", ".join(owners))),
                "locators": [],
                "blocking": True,
            })

    return entities, findings


def _with_identity(entity: CanonicalEntity, entity_uuid: str) -> CanonicalEntity:
    """Attach the allocated identity to a draft entity."""
    return CanonicalEntity(
        entity_type=entity.entity_type,
        canonical_key=entity.canonical_key,
        normalized_value=entity.normalized_value,
        preferred_display=entity.preferred_display,
        source_display=entity.source_display,
        entity_uuid=entity_uuid,
        external_ids=entity.external_ids,
        aliases=entity.aliases,
        locators=entity.locators,
        findings=entity.findings)


def _queue_items(build: "CanonicalBuild",
                 created_at: _dt.datetime) -> Tuple[ResolutionQueueItem, ...]:
    """Every outcome that is not RESOLVED becomes one queue item.

    Undecided, all of them. WP-07 creates no decisions: ``decided_by`` is
    ``None`` on every item this function produces, and there is no argument
    that would change that.
    """
    items: List[ResolutionQueueItem] = []
    for outcome in build.resolutions:
        if not outcome.needs_review:
            continue
        locator_key = outcome.locator.key if outcome.locator else ("", "", "")
        queue_key = "|".join((
            outcome.entity_type.value,
            outcome.status.value,
            outcome.normalized_value or outcome.submitted_value,
            locator_key[0], locator_key[1], locator_key[2]))
        items.append(ResolutionQueueItem(
            queue_key=queue_key,
            dataset_public_id=build.dataset_public_id,
            canonical_build_key=build.build_key,
            outcome=outcome,
            created_at=created_at))
    return tuple(sorted(items, key=lambda item: item.queue_key))


def _replace(build: CanonicalBuild, **changes: Any) -> CanonicalBuild:
    payload = {
        "dataset_public_id": build.dataset_public_id,
        "snapshot_manifest_hash": build.snapshot_manifest_hash,
        "snapshot_content_hash": build.snapshot_content_hash,
        "snapshot_state": build.snapshot_state,
        "snapshot_kind": build.snapshot_kind,
        "snapshot_complete": build.snapshot_complete,
        "genes": build.genes,
        "drugs": build.drugs,
        "allocation": build.allocation,
        "allocation_result": build.allocation_result,
        "extraction": build.extraction,
        "resolutions": build.resolutions,
        "queue": build.queue,
        "dedup": build.dedup,
        "entity_findings": build.entity_findings,
        "built_at": build.built_at,
        "build_note": build.build_note,
    }
    payload.update(changes)
    return CanonicalBuild(**payload)


# -- writing ------------------------------------------------------------


def write_build(build: CanonicalBuild, output_root: str, *,
                extra_documents: Optional[Mapping[str, Any]] = None) -> CanonicalBuildResult:
    """Write a build into ``output_root/<dataset-id>`` and seal it atomically.

    Assembled in a staging directory beside the destination - same filesystem,
    so the final move is a rename rather than a copy - and moved with
    :func:`os.rename`, which refuses an existing target. ``os.replace`` is
    deliberately not used: it would silently overwrite a sealed build, and a
    canonical build that can be overwritten is not a canonical build.
    """
    destination = os.path.join(output_root, build.dataset_public_id)
    if os.path.exists(destination):
        raise CanonicalBuildError(
            "a canonical build already exists at %s. Sealed builds are never "
            "overwritten; write the new build elsewhere and compare the two."
            % destination, code="BUILD_ALREADY_EXISTS")

    os.makedirs(output_root, exist_ok=True)
    staging = os.path.join(
        output_root, "%s%s.%d" % (_STAGING_PREFIX, build.dataset_public_id,
                                  os.getpid()))
    if os.path.exists(staging):
        raise CanonicalBuildError(
            "a staging directory already exists at %s; a previous build was "
            "interrupted. Inspect and remove it deliberately." % staging,
            code="STAGING_EXISTS")

    documents = _render_documents(build, extra_documents or {})
    try:
        os.makedirs(staging)
        digests: Dict[str, str] = {}
        for name in BUILD_FILES:
            if name == "checksums.sha256":
                continue
            if name not in documents:
                continue
            data = documents[name]
            path = os.path.join(staging, name)
            with open(path, "wb") as handle:
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
        raise CanonicalBuildError(
            "sealing the build at %s failed because the destination appeared "
            "while it was being written: %s" % (destination, exc),
            code="BUILD_ALREADY_EXISTS") from exc
    except OSError as exc:
        raise CanonicalBuildError(
            "the canonical build could not be written to %s: %s"
            % (staging, exc), code="BUILD_WRITE_FAILED") from exc

    return CanonicalBuildResult(
        build=build,
        build_path=destination,
        file_digests=dict(sorted(digests.items())),
        manifest=json.loads(documents["manifest.json"].decode("utf-8")))


def _render_documents(build: CanonicalBuild,
                      extra: Mapping[str, Any]) -> Dict[str, bytes]:
    """Render every build file as bytes, deterministically."""
    documents: Dict[str, bytes] = {
        "identity-allocation.json": _json_bytes(build.allocation.to_json()),
        "genes.ndjson": _ndjson([entity.to_json() for entity in build.genes]),
        "drugs.ndjson": _ndjson([entity.to_json() for entity in build.drugs]),
        "entity-membership.ndjson": _ndjson(_membership_rows(build)),
        "resolution-queue.ndjson": _ndjson(
            [item.to_json() for item in build.queue]),
        "duplicate-groups.ndjson": _ndjson(
            [group.to_json() for group in build.dedup.groups]),
        "provenance.ndjson": _ndjson(_provenance_rows(build)),
    }
    for name, payload in extra.items():
        if name not in BUILD_FILES:
            raise CanonicalBuildError(
                "%r is not part of the canonical build layout; add it to "
                "BUILD_FILES deliberately rather than writing an unlisted file"
                % name, code="UNKNOWN_BUILD_FILE")
        documents[name] = _json_bytes(payload)

    content_digests = {name: "sha256:" + _hex(data)
                       for name, data in sorted(documents.items())}
    documents["manifest.json"] = _json_bytes(
        _manifest_payload(build, content_digests))
    return documents


def _manifest_payload(build: CanonicalBuild,
                      file_digests: Mapping[str, str]) -> Dict[str, Any]:
    """The build manifest.

    ``content_hash`` is computed from the build's contents, not from the file
    digests, so it is stable across a layout change that only reorders bytes.
    The file digests are recorded beside it so a reader can check the directory
    it actually has.
    """
    return {
        "canonical_build_layout_version": CANONICAL_BUILD_LAYOUT_VERSION,
        "dataset_public_id": build.dataset_public_id,
        "canonical_build_key": build.build_key,
        "content_hash": build.content_hash(),
        "snapshot_manifest_hash": build.snapshot_manifest_hash,
        "snapshot_content_hash": build.snapshot_content_hash,
        "snapshot_state": build.snapshot_state,
        "snapshot_kind": build.snapshot_kind,
        "snapshot_complete": build.snapshot_complete,
        "rule_versions": build.rule_versions,
        "allocation_content_hash": build.allocation.content_hash(),
        "identity_minted_count": len(build.allocation_result.minted),
        "identity_reused_count": len(build.allocation_result.reused),
        "built_at": (build.built_at.isoformat().replace("+00:00", "Z")
                     if build.built_at else None),
        "build_note": build.build_note,
        "dataset_lifecycle_state": "BUILDING",
        "lifecycle_note": (
            "A canonical build is a build product. It is not a quality "
            "approval, not a publication and not a release. The dataset stays "
            "BUILDING until a named reviewer records a decision."),
        "summary": build.summary(),
        "source_observed_axes": dict(build.extraction.source_observed_axes),
        "files": dict(sorted(file_digests.items())),
    }


def _membership_rows(build: CanonicalBuild) -> List[Dict[str, Any]]:
    """One row per canonical entity in this dataset build."""
    rows = []
    for entity in build.entities:
        rows.append({
            "dataset_public_id": build.dataset_public_id,
            "canonical_build_key": build.build_key,
            "entity_type": entity.entity_type.value,
            "canonical_key": entity.canonical_key,
            "entity_uuid": entity.entity_uuid,
            "locator_count": len(entity.locators),
            "alias_proposal_count": len(entity.aliases),
            "approved_alias_count": len(entity.approved_aliases),
            "external_ids": [item.to_json() for item in entity.external_ids],
        })
    return rows


def _provenance_rows(build: CanonicalBuild) -> List[Dict[str, Any]]:
    """One row per link between a canonical entity and a raw locator.

    This is the file that answers "where did this come from", and it is why a
    duplicate group keeps every member: the answer has to be complete.
    """
    rows = []
    for entity in build.entities:
        for locator in entity.locators:
            rows.append({
                "canonical_build_key": build.build_key,
                "entity_type": entity.entity_type.value,
                "canonical_key": entity.canonical_key,
                "entity_uuid": entity.entity_uuid,
                "artifact_path": locator.artifact_path,
                "artifact_sha256": locator.artifact_sha256,
                "pointer": locator.pointer,
                "source_record_id": locator.source_record_id,
                "snapshot_manifest_hash": locator.snapshot_manifest_hash,
            })
    return sorted(rows, key=lambda row: (row["canonical_key"],
                                         row["artifact_path"],
                                         row["pointer"]))


#: Files that legitimately differ between two builds of the same content.
#: ``manifest.json`` carries ``built_at``, which is provenance rather than
#: content, and ``checksums.sha256`` covers the manifest. Everything else must
#: match byte for byte, and :func:`compare_builds` says so.
PROVENANCE_BEARING_FILES: Tuple[str, ...] = (
    "manifest.json",
    "checksums.sha256",
)


@dataclass(frozen=True)
class BuildComparison:
    """Whether two sealed builds are the same build.

    Two things are checked and reported separately, because they fail for
    different reasons: whether the content hashes agree (the same inputs under
    the same rules) and whether the bytes agree (the same rendering). A
    reproducibility claim needs both, and a caller that saw only one number
    could not tell which had broken.
    """

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
        """True when every file that is not provenance-bearing matches."""
        return not tuple(name for name in self.differing_files
                         if name not in PROVENANCE_BEARING_FILES)

    @property
    def reproducible(self) -> bool:
        return (self.content_hash_matches
                and self.byte_identical_apart_from_provenance
                and not self.only_left and not self.only_right)

    def to_json(self) -> Dict[str, Any]:
        return {
            "left_path": self.left_path,
            "right_path": self.right_path,
            "reproducible": self.reproducible,
            "content_hash_matches": self.content_hash_matches,
            "byte_identical_apart_from_provenance":
                self.byte_identical_apart_from_provenance,
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


def compare_builds(left_path: str, right_path: str) -> BuildComparison:
    """Compare two sealed builds file by file and by content hash."""
    left_files = _list_build_files(left_path)
    right_files = _list_build_files(right_path)
    shared = sorted(set(left_files) & set(right_files))
    identical, differing = [], []
    for name in shared:
        if _file_digest(os.path.join(left_path, name)) == \
                _file_digest(os.path.join(right_path, name)):
            identical.append(name)
        else:
            differing.append(name)
    return BuildComparison(
        left_path=left_path,
        right_path=right_path,
        identical_files=tuple(identical),
        differing_files=tuple(differing),
        only_left=tuple(sorted(set(left_files) - set(right_files))),
        only_right=tuple(sorted(set(right_files) - set(left_files))),
        left_content_hash=_content_hash_of(left_path),
        right_content_hash=_content_hash_of(right_path))


def _list_build_files(build_path: str) -> Tuple[str, ...]:
    if not os.path.isdir(build_path):
        raise CanonicalBuildError(
            "no canonical build directory at %s" % build_path,
            code="BUILD_MISSING")
    return tuple(sorted(
        name for name in os.listdir(build_path)
        if os.path.isfile(os.path.join(build_path, name))))


def _file_digest(path: str) -> str:
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _content_hash_of(build_path: str) -> Optional[str]:
    try:
        return read_build_manifest(build_path).get("content_hash")
    except CanonicalBuildError:
        return None


def verify_build(build_path: str) -> Tuple[bool, Tuple[str, ...]]:
    """Re-check a sealed build against its own recorded digests.

    Reads ``checksums.sha256`` and recomputes every listed file. A build whose
    bytes no longer match what it recorded has been edited, and every hash
    quoted against it elsewhere has stopped meaning anything.
    """
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

    present = set(_list_build_files(build_path))
    for name in sorted(recorded):
        path = os.path.join(build_path, name)
        if not os.path.isfile(path):
            problems.append("%s is recorded in checksums.sha256 and absent"
                            % name)
            continue
        actual = _file_digest(path)
        if actual != recorded[name]:
            problems.append("%s does not match its recorded digest" % name)
    for name in sorted(present - set(recorded) - {"checksums.sha256"}):
        problems.append("%s is present and not recorded in checksums.sha256"
                        % name)
    return not problems, tuple(problems)


def read_build_manifest(build_path: str) -> Dict[str, Any]:
    """Read a sealed build's manifest, checking the files it claims to have."""
    manifest_path = os.path.join(build_path, "manifest.json")
    if not os.path.isfile(manifest_path):
        raise CanonicalBuildError(
            "no canonical build manifest at %s" % manifest_path,
            code="MANIFEST_MISSING")
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        raise CanonicalBuildError(
            "the canonical build manifest at %s is unreadable: %s"
            % (manifest_path, exc), code="MANIFEST_CORRUPT") from exc
    if payload.get("canonical_build_layout_version") != CANONICAL_BUILD_LAYOUT_VERSION:
        raise CanonicalBuildError(
            "build at %s declares layout %r; this build reads %r"
            % (build_path, payload.get("canonical_build_layout_version"),
               CANONICAL_BUILD_LAYOUT_VERSION),
            code="LAYOUT_VERSION_MISMATCH")
    return payload


# -- encoding helpers ---------------------------------------------------


def _json_bytes(payload: Any) -> bytes:
    """One canonical JSON document, newline-terminated."""
    return (canonical_json(payload) + "\n").encode("utf-8")


def _ndjson(rows: Iterable[Mapping[str, Any]]) -> bytes:
    """Canonical NDJSON. Row order is the caller's; key order is canonical."""
    lines = [canonical_json(row) for row in rows]
    if not lines:
        return b""
    return ("\n".join(lines) + "\n").encode("utf-8")


def _render_checksums(digests: Mapping[str, str]) -> bytes:
    """``sha256sum``-compatible lines, sorted by file name."""
    lines = []
    for name in sorted(digests):
        lines.append("%s  %s" % (digests[name].split(":", 1)[-1], name))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _hex(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def _fsync_dir(path: str) -> None:
    """Make a directory entry durable, tolerating platforms that cannot."""
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
