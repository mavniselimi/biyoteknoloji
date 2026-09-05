# -*- coding: utf-8 -*-
"""Reading canonical inputs out of a raw snapshot (WP-07).

Standard library plus :mod:`pgx.domain`, :mod:`pgx.ingestion.snapshots` and
:mod:`pgx.normalization`.

This module is the only place that knows the *shape* of the legacy ClinPGx
files. Everything downstream works on :class:`EntityCandidate`,
:class:`ReferenceObservation` and
:class:`~pgx.normalization.dedup.RecordObservation`, so a second source can be
added by writing a second extractor rather than by touching the resolver, the
deduplicator or the builder.

**What it refuses to read.** Artifacts the role map classifies as derived, as
out-of-scope P1 candidate data, or as API schema reference contribute no
records. An artifact the map does not recognise at all is reported by name and
left unread - guessing at an unknown file would invent entities nobody put in
the snapshot.

**What it refuses to carry.** No significance, polarity, score, severity, risk,
phenotype-to-risk mapping, recommendation or plain-language conclusion crosses
this boundary. The legacy CSVs mix those project-derived columns in with source
facts; that is precisely why those CSVs are comparison inputs and not evidence.

**What it does not decide.** It proposes; it never resolves. A gene symbol read
here becomes a candidate with a locator attached, and whether it becomes a
canonical entity is the resolver's and the builder's business.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import (Any, Dict, Iterable, List, Mapping, Optional, Sequence,
                    Tuple)

from pgx.ingestion.snapshots import RawArtifactDescriptor, SnapshotManifest
from pgx.normalization.artifacts import (ARTIFACT_ROLE_MAP,
                                         ARTIFACT_ROLE_MAP_VERSION,
                                         ArtifactRole, ArtifactRoleEntry,
                                         classify_artifacts)
from pgx.normalization.dedup import RecordObservation
from pgx.normalization.errors import ArtifactRoleError, NormalizationError
from pgx.normalization.models import (AliasProposal, AliasStatus, EntityType,
                                      RawLocator)
from pgx.normalization.normalize import (ExternalIdentifier,
                                         normalize_drug_name,
                                         normalize_endpoint_container,
                                         normalize_external_id,
                                         normalize_gene_symbol)

__all__ = [
    "EXTRACTION_RULE_VERSION",
    "ArtifactReadReport",
    "DerivationCheck",
    "EntityCandidate",
    "ExtractionResult",
    "ReferenceObservation",
    "extract_snapshot",
    "json_pointer",
]

#: Bumped when the field selection or the record shaping changes.
EXTRACTION_RULE_VERSION = "pgx-extraction/1"

#: The source's own namespace for its internal accession IDs.
SOURCE_ID_NAMESPACE = "clinpgx"

#: Keys carrying project-derived interpretation in the legacy flattenings. They
#: are named here so a test can assert that none of them reaches a canonical
#: record, and so a future extractor cannot quietly start reading one.
FORBIDDEN_INTERPRETATION_KEYS: Tuple[str, ...] = (
    "alternative_drug",
    "candidate_score",
    "clinical_conclusion",
    "effect_hint",
    "manual_effect_hint",
    "polarity",
    "recommendation",
    "risk",
    "risk_level",
    "score",
    "severity",
    "significance",
)


def json_pointer(*parts: object) -> str:
    """Build an RFC 6901 JSON Pointer.

    Escaped properly, because a container name is source data: a key containing
    a slash would otherwise produce a pointer that addresses something else.
    """
    out = []
    for part in parts:
        text = str(part)
        out.append(text.replace("~", "~0").replace("/", "~1"))
    return "/" + "/".join(out) if out else ""


@dataclass(frozen=True, slots=True)
class EntityCandidate:
    """A gene or drug proposed by one artifact, with where it came from.

    A candidate is not an entity. It carries the source's spelling, the
    normalised form (or ``None`` when the value could not be normalised at all),
    and every finding raised while reading it. The builder decides what becomes
    canonical; nothing here does.
    """

    entity_type: EntityType
    submitted_value: str
    normalized_value: Optional[str]
    preferred_display: str
    source_display: str
    locator: RawLocator
    external_ids: Tuple[ExternalIdentifier, ...] = ()
    alias_proposals: Tuple[AliasProposal, ...] = ()
    findings: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "external_ids", tuple(
            sorted(set(self.external_ids), key=lambda item: (item[0], item[1]))))
        object.__setattr__(self, "alias_proposals", tuple(
            sorted(self.alias_proposals, key=lambda item: item.normalized_alias)))
        object.__setattr__(self, "findings", tuple(sorted(set(self.findings))))

    @property
    def canonical_key(self) -> Optional[str]:
        if self.normalized_value is None:
            return None
        return "%s:%s" % (self.entity_type.value, self.normalized_value)

    def to_json(self) -> Dict[str, Any]:
        return {
            "entity_type": self.entity_type.value,
            "submitted_value": self.submitted_value,
            "normalized_value": self.normalized_value,
            "canonical_key": self.canonical_key,
            "preferred_display": self.preferred_display,
            "source_display": self.source_display,
            "external_ids": [item.to_json() for item in self.external_ids],
            "alias_proposals": [item.to_json() for item in self.alias_proposals],
            "locator": self.locator.to_json(),
            "findings": list(self.findings),
        }


@dataclass(frozen=True, slots=True)
class ReferenceObservation:
    """A place where one artifact refers to an entity by name.

    The pair endpoint keys its response by ``SYMBOL::drug``. Each half is a
    reference that must resolve to a canonical entity, and a half that does not
    is a ``BROKEN_REFERENCE`` - a data-quality finding, never a reason to create
    the entity it names.
    """

    entity_type: EntityType
    submitted_value: str
    locator: RawLocator
    context: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "entity_type": self.entity_type.value,
            "submitted_value": self.submitted_value,
            "context": self.context,
            "locator": self.locator.to_json(),
        }


@dataclass(frozen=True, slots=True)
class DerivationCheck:
    """Whether a derived artifact really is derived from the one it claims.

    ``resolved_genes.csv`` is treated as a comparison file because it carries
    exactly the identifier set of ``resolved_genes.json``. That claim is
    re-verified on every build: if the CSV ever gains a row the JSON lacks, the
    "derived, therefore not evidence" reasoning has stopped holding and the
    build says so instead of silently dropping data.
    """

    derived_artifact: str
    source_artifact: str
    derived_identifier_count: int
    source_identifier_count: int
    only_in_derived: Tuple[str, ...] = ()
    only_in_source: Tuple[str, ...] = ()
    note: Optional[str] = None

    @property
    def consistent(self) -> bool:
        return not self.only_in_derived and not self.only_in_source

    def to_json(self) -> Dict[str, Any]:
        return {
            "derived_artifact": self.derived_artifact,
            "source_artifact": self.source_artifact,
            "derived_identifier_count": self.derived_identifier_count,
            "source_identifier_count": self.source_identifier_count,
            "only_in_derived": list(self.only_in_derived),
            "only_in_source": list(self.only_in_source),
            "consistent": self.consistent,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class ArtifactReadReport:
    """What happened to one artifact during extraction."""

    file_name: str
    relative_path: str
    role: ArtifactRole
    read: bool
    record_count: int = 0
    entity_candidate_count: int = 0
    note: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "file_name": self.file_name,
            "relative_path": self.relative_path,
            "role": self.role.value,
            "read": self.read,
            "record_count": self.record_count,
            "entity_candidate_count": self.entity_candidate_count,
            "note": self.note,
        }


@dataclass(frozen=True)
class ExtractionResult:
    """Everything one snapshot yielded, and everything it could not."""

    dataset_public_id: str
    snapshot_manifest_hash: str
    extraction_rule_version: str
    artifact_role_map_version: str
    candidates: Tuple[EntityCandidate, ...]
    references: Tuple[ReferenceObservation, ...]
    observations: Tuple[RecordObservation, ...]
    reports: Tuple[ArtifactReadReport, ...]
    derivation_checks: Tuple[DerivationCheck, ...]
    unrecognised_artifacts: Tuple[str, ...] = ()
    missing_artifacts: Tuple[str, ...] = ()
    excluded_record_counts: Mapping[str, int] = field(default_factory=dict)
    records_without_source_id: Mapping[str, int] = field(default_factory=dict)
    container_synonyms: Tuple[Mapping[str, Any], ...] = ()
    source_observed_axes: Mapping[str, Any] = field(default_factory=dict)
    findings: Tuple[str, ...] = ()

    def candidates_of(self, entity_type: EntityType) -> Tuple[EntityCandidate, ...]:
        return tuple(item for item in self.candidates
                     if item.entity_type is entity_type)

    def to_json(self) -> Dict[str, Any]:
        return {
            "dataset_public_id": self.dataset_public_id,
            "snapshot_manifest_hash": self.snapshot_manifest_hash,
            "extraction_rule_version": self.extraction_rule_version,
            "artifact_role_map_version": self.artifact_role_map_version,
            "candidate_count": len(self.candidates),
            "reference_count": len(self.references),
            "observation_count": len(self.observations),
            "unrecognised_artifacts": list(self.unrecognised_artifacts),
            "missing_artifacts": list(self.missing_artifacts),
            "excluded_record_counts": dict(sorted(
                self.excluded_record_counts.items())),
            "records_without_source_id": dict(sorted(
                self.records_without_source_id.items())),
            "container_synonyms": [dict(item) for item in self.container_synonyms],
            "source_observed_axes": dict(self.source_observed_axes),
            "artifacts": [report.to_json() for report in self.reports],
            "derivation_checks": [check.to_json()
                                  for check in self.derivation_checks],
            "findings": list(self.findings),
        }


def extract_snapshot(snapshot_root: str,
                     manifest: SnapshotManifest) -> ExtractionResult:
    """Read one sealed snapshot into candidates, references and observations.

    The manifest is the index: artifacts are located through it, and every
    locator produced here carries the artifact's recorded digest, so a locator
    stays checkable after the fact.
    """
    if not os.path.isdir(snapshot_root):
        raise ArtifactRoleError(
            "no snapshot directory at %s" % snapshot_root)

    by_name: Dict[str, RawArtifactDescriptor] = {}
    for descriptor in manifest.artifacts:
        name = os.path.basename(descriptor.relative_path)
        if name in by_name:
            raise ArtifactRoleError(
                "two artifacts share the base name %r (%s and %s); the role map "
                "is keyed by base name and cannot distinguish them"
                % (name, by_name[name].relative_path, descriptor.relative_path),
                artifacts=(by_name[name].relative_path,
                           descriptor.relative_path))
        by_name[name] = descriptor

    entries, missing = classify_artifacts(by_name)
    unrecognised = tuple(entry.file_name for entry in entries
                         if entry.role is ArtifactRole.UNRECOGNISED)

    state = _ExtractionState(
        root=snapshot_root,
        manifest=manifest,
        descriptors=by_name)

    for entry in entries:
        state.handle(entry)

    state.check_derivations()

    findings: List[str] = list(state.findings)
    for file_name, count in sorted(state.missing_id_counts.items()):
        findings.append(
            "%d record(s) in %s carry no source record identity. They are "
            "counted and kept apart: two payloads that happen to be equal are "
            "not evidence that they are the same record."
            % (count, file_name))
    if unrecognised:
        findings.append(
            "%d artifact(s) are not in the WP-07 role map and were not read: %s. "
            "They are reported rather than interpreted."
            % (len(unrecognised), ", ".join(unrecognised)))
    if missing:
        findings.append(
            "%d artifact(s) the role map expects are absent from this snapshot: "
            "%s." % (len(missing), ", ".join(missing)))

    return ExtractionResult(
        dataset_public_id=manifest.dataset_public_id,
        snapshot_manifest_hash=manifest.manifest_hash,
        extraction_rule_version=EXTRACTION_RULE_VERSION,
        artifact_role_map_version=ARTIFACT_ROLE_MAP_VERSION,
        candidates=tuple(state.candidates),
        references=tuple(state.references),
        observations=tuple(state.observations),
        reports=tuple(sorted(state.reports, key=lambda item: item.file_name)),
        derivation_checks=tuple(sorted(state.derivation_checks,
                                       key=lambda item: item.derived_artifact)),
        unrecognised_artifacts=unrecognised,
        missing_artifacts=missing,
        excluded_record_counts=dict(sorted(state.excluded.items())),
        records_without_source_id=dict(sorted(state.missing_id_counts.items())),
        container_synonyms=tuple(state.container_synonyms),
        source_observed_axes=state.axes(),
        findings=tuple(findings))


# -- extraction state ---------------------------------------------------


class _ExtractionState:
    """Mutable scratch space for one extraction run.

    Kept private: the result is immutable, and nothing outside this module
    should be able to add a candidate after the fact.
    """

    def __init__(self, root: str, manifest: SnapshotManifest,
                 descriptors: Mapping[str, RawArtifactDescriptor]) -> None:
        self.root = root
        self.manifest = manifest
        self.descriptors = descriptors
        self.candidates: List[EntityCandidate] = []
        self.references: List[ReferenceObservation] = []
        self.observations: List[RecordObservation] = []
        self.reports: List[ArtifactReadReport] = []
        self.derivation_checks: List[DerivationCheck] = []
        self.excluded: Dict[str, int] = {}
        self.findings: List[str] = []
        self._identifier_sets: Dict[str, Tuple[str, ...]] = {}
        self._pair_keys: List[str] = []
        self._container_spellings: Dict[str, set] = {}
        self._missing_id_counts: Dict[str, int] = {}
        self._families_by_record: Dict[Tuple[str, str], set] = {}
        self.container_synonyms: List[Dict[str, Any]] = []

    # -- dispatch -------------------------------------------------------

    def handle(self, entry: ArtifactRoleEntry) -> None:
        handler = {
            "resolved_genes.json": self._read_genes,
            "resolved_chemicals.json": self._read_chemicals,
            "pair_probe_raw.json": self._read_pairs,
            "variant_annotation_filtered_raw.json": self._read_variant_annotations,
        }.get(entry.file_name)

        if handler is not None and entry.counts_as_evidence:
            handler(entry)
            return

        if entry.role is ArtifactRole.DERIVED_LEGACY_COMPARISON:
            self._read_derived_identifiers(entry)
            return
        if entry.role is ArtifactRole.OUT_OF_SCOPE_P1_CANDIDATE_DATA:
            self._count_excluded(entry)
            return

        note = {
            ArtifactRole.API_SCHEMA_REFERENCE:
                "Reference only: the source's own API description carries no "
                "scientific record.",
            ArtifactRole.UNRECOGNISED:
                "Not in the role map. Left unread and reported.",
        }.get(entry.role, "No extraction handler is registered for this role.")
        self.reports.append(ArtifactReadReport(
            file_name=entry.file_name,
            relative_path=self._relative_path(entry.file_name),
            role=entry.role, read=False, note=note))

    # -- entity inputs --------------------------------------------------

    def _read_genes(self, entry: ArtifactRoleEntry) -> None:
        payload = self._load_json(entry.file_name)
        if not isinstance(payload, Mapping):
            raise ArtifactRoleError(
                "%s should be an object keyed by queried symbol, got %s"
                % (entry.file_name, type(payload).__name__),
                artifacts=(entry.file_name,))

        identifiers: List[str] = []
        count = 0
        for queried in sorted(payload):
            record = payload[queried]
            pointer = json_pointer(queried)
            locator = self._locator(entry.file_name, pointer,
                                    _source_record_id(record))
            if not isinstance(record, Mapping):
                self.findings.append(
                    "%s at %s is not an object and was skipped"
                    % (entry.file_name, pointer))
                continue
            candidate = self._gene_candidate(queried, record, locator)
            if candidate is not None:
                self.candidates.append(candidate)
                count += 1
            source_id = _source_record_id(record)
            if source_id:
                identifiers.append(source_id)

        self._identifier_sets[entry.file_name] = tuple(sorted(set(identifiers)))
        self.reports.append(ArtifactReadReport(
            file_name=entry.file_name,
            relative_path=self._relative_path(entry.file_name),
            role=entry.role, read=True, record_count=len(payload),
            entity_candidate_count=count))

    def _gene_candidate(self, queried: str, record: Mapping[str, Any],
                        locator: RawLocator) -> Optional[EntityCandidate]:
        findings: List[str] = []
        symbol = _string_or_none(record, "symbol") or queried
        try:
            normalized = normalize_gene_symbol(symbol)
        except NormalizationError as exc:
            findings.append("gene symbol is not normalisable: %s" % exc)
            normalized = None

        external_ids, id_findings = self._external_ids(record)
        findings.extend(id_findings)

        aliases: List[AliasProposal] = []
        for observed in _alias_strings(record, queried, symbol):
            try:
                alias_normalized = normalize_gene_symbol(observed)
            except NormalizationError:
                findings.append(
                    "alternative gene name %r could not be normalised and is "
                    "recorded unproposed" % observed)
                continue
            if normalized is not None and alias_normalized == normalized:
                continue
            aliases.append(AliasProposal(
                normalized_alias=alias_normalized,
                display_alias=observed,
                status=AliasStatus.PENDING_REVIEW,
                locator=locator,
                note="observed in the source response; not reviewed"))

        return EntityCandidate(
            entity_type=EntityType.GENE,
            submitted_value=symbol,
            normalized_value=normalized,
            preferred_display=_string_or_none(record, "name") or symbol,
            source_display=symbol,
            locator=locator,
            external_ids=external_ids,
            alias_proposals=tuple(aliases),
            findings=tuple(findings))

    def _read_chemicals(self, entry: ArtifactRoleEntry) -> None:
        payload = self._load_json(entry.file_name)
        if not isinstance(payload, Mapping):
            raise ArtifactRoleError(
                "%s should be an object keyed by queried name, got %s"
                % (entry.file_name, type(payload).__name__),
                artifacts=(entry.file_name,))

        identifiers: List[str] = []
        count = 0
        for queried in sorted(payload):
            record = payload[queried]
            pointer = json_pointer(queried)
            locator = self._locator(entry.file_name, pointer,
                                    _source_record_id(record))
            if not isinstance(record, Mapping):
                self.findings.append(
                    "%s at %s is not an object and was skipped"
                    % (entry.file_name, pointer))
                continue
            candidate = self._drug_candidate(queried, record, locator)
            if candidate is not None:
                self.candidates.append(candidate)
                count += 1
            source_id = _source_record_id(record)
            if source_id:
                identifiers.append(source_id)

        self._identifier_sets[entry.file_name] = tuple(sorted(set(identifiers)))
        self.reports.append(ArtifactReadReport(
            file_name=entry.file_name,
            relative_path=self._relative_path(entry.file_name),
            role=entry.role, read=True, record_count=len(payload),
            entity_candidate_count=count))

    def _drug_candidate(self, queried: str, record: Mapping[str, Any],
                        locator: RawLocator) -> Optional[EntityCandidate]:
        findings: List[str] = []
        name = _string_or_none(record, "name") or queried
        try:
            normalized = normalize_drug_name(name)
        except NormalizationError as exc:
            findings.append("drug name is not normalisable: %s" % exc)
            normalized = None

        external_ids, id_findings = self._external_ids(record)
        findings.extend(id_findings)

        aliases: List[AliasProposal] = []
        for observed in _alias_strings(record, queried, name):
            try:
                alias_normalized = normalize_drug_name(observed)
            except NormalizationError:
                findings.append(
                    "alternative drug name %r could not be normalised and is "
                    "recorded unproposed" % observed)
                continue
            if normalized is not None and alias_normalized == normalized:
                continue
            aliases.append(AliasProposal(
                normalized_alias=alias_normalized,
                display_alias=observed,
                status=AliasStatus.PENDING_REVIEW,
                locator=locator,
                note="observed in the source response; not reviewed"))

        return EntityCandidate(
            entity_type=EntityType.DRUG,
            submitted_value=name,
            normalized_value=normalized,
            preferred_display=name,
            source_display=name,
            locator=locator,
            external_ids=external_ids,
            alias_proposals=tuple(aliases),
            findings=tuple(findings))

    # -- relationship and annotation inputs -----------------------------

    def _read_pairs(self, entry: ArtifactRoleEntry) -> None:
        payload = self._load_json(entry.file_name)
        if not isinstance(payload, Mapping):
            raise ArtifactRoleError(
                "%s should be an object keyed by GENE::drug, got %s"
                % (entry.file_name, type(payload).__name__),
                artifacts=(entry.file_name,))

        records = 0
        for pair_key in sorted(payload):
            entry_payload = payload[pair_key]
            self._pair_keys.append(pair_key)
            self._pair_references(entry.file_name, pair_key)
            if not isinstance(entry_payload, Mapping):
                self.findings.append(
                    "pair entry %r is not an object and was skipped" % pair_key)
                continue
            containers = entry_payload.get("pair")
            if not isinstance(containers, Mapping):
                self.findings.append(
                    "pair entry %r carries no 'pair' object" % pair_key)
                continue
            for spelling in sorted(containers):
                members = containers[spelling]
                if not isinstance(members, list):
                    continue
                family = normalize_endpoint_container(spelling)
                self._container_spellings.setdefault(family, set()).add(spelling)
                for index, member in enumerate(members):
                    pointer = json_pointer(pair_key, "pair", spelling, index)
                    source_id = _source_record_id(member)
                    self.observations.append(RecordObservation(
                        record_type="pair_container_record",
                        source_record_id=source_id,
                        semantic_key="%s|%s" % (pair_key, family),
                        payload=member,
                        locator=self._locator(entry.file_name, pointer,
                                              source_id),
                        container_spelling=spelling))
                    records += 1
                    if source_id is None:
                        self._count_missing_id(entry.file_name)
                    else:
                        self._families_by_record.setdefault(
                            (pair_key, source_id), set()).add(family)

        self._report_container_synonyms()
        self.reports.append(ArtifactReadReport(
            file_name=entry.file_name,
            relative_path=self._relative_path(entry.file_name),
            role=entry.role, read=True, record_count=records,
            note="Pair-scoped container members. Each is a raw source record; "
                 "none is interpreted."))

    def _pair_references(self, file_name: str, pair_key: str) -> None:
        """Record the gene and drug a pair key names, without creating them."""
        pointer = json_pointer(pair_key)
        locator = self._locator(file_name, pointer, None)
        if "::" not in pair_key:
            self.findings.append(
                "pair key %r is not in GENE::drug form" % pair_key)
            return
        gene_part, _, drug_part = pair_key.partition("::")
        self.references.append(ReferenceObservation(
            entity_type=EntityType.GENE, submitted_value=gene_part,
            locator=locator, context=pair_key))
        self.references.append(ReferenceObservation(
            entity_type=EntityType.DRUG, submitted_value=drug_part,
            locator=locator, context=pair_key))

    def _read_variant_annotations(self, entry: ArtifactRoleEntry) -> None:
        payload = self._load_json(entry.file_name)
        if not isinstance(payload, Mapping):
            raise ArtifactRoleError(
                "%s should be an object keyed by gene symbol, got %s"
                % (entry.file_name, type(payload).__name__),
                artifacts=(entry.file_name,))

        records = 0
        for gene_key in sorted(payload):
            members = payload[gene_key]
            pointer_base = json_pointer(gene_key)
            self.references.append(ReferenceObservation(
                entity_type=EntityType.GENE, submitted_value=gene_key,
                locator=self._locator(entry.file_name, pointer_base, None),
                context="variant annotation grouping"))
            if not isinstance(members, list):
                self.findings.append(
                    "%s at %s is not a list and was skipped"
                    % (entry.file_name, pointer_base))
                continue
            for index, member in enumerate(members):
                pointer = json_pointer(gene_key, index)
                source_id = _source_record_id(member)
                if source_id is None:
                    self._count_missing_id(entry.file_name)
                self.observations.append(RecordObservation(
                    record_type="variant_annotation",
                    source_record_id=source_id,
                    semantic_key=normalize_endpoint_container(gene_key),
                    payload=member,
                    locator=self._locator(entry.file_name, pointer, source_id),
                    container_spelling=gene_key))
                records += 1

        self.reports.append(ArtifactReadReport(
            file_name=entry.file_name,
            relative_path=self._relative_path(entry.file_name),
            role=entry.role, read=True, record_count=records,
            note="Raw variant annotation payloads, grouped by the gene they "
                 "were retrieved for. Counted and deduplicated, not read for "
                 "meaning."))

    # -- non-evidence artifacts -----------------------------------------

    def _read_derived_identifiers(self, entry: ArtifactRoleEntry) -> None:
        """Read a derived file's identifier set only, for the derivation check.

        Nothing else is taken from it. Reading its identifiers is how the
        "derived, therefore not evidence" claim stays checkable; reading its
        columns would import the project-derived interpretation this package
        exists to keep out.
        """
        path = self._path(entry.file_name)
        identifiers: List[str] = []
        rows = 0
        note = None
        if entry.file_name.endswith(".csv"):
            import csv
            try:
                with open(path, "r", encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    columns = tuple(reader.fieldnames or ())
                    id_column = _identifier_column(columns)
                    for row in reader:
                        rows += 1
                        if id_column:
                            value = (row.get(id_column) or "").strip()
                            if value:
                                identifiers.append(value)
            except (OSError, UnicodeDecodeError, csv.Error) as exc:
                self.findings.append(
                    "derived artifact %s could not be read for comparison: %s"
                    % (entry.file_name, exc))
                note = "unreadable; comparison skipped"
            else:
                forbidden = tuple(sorted(
                    column for column in columns
                    if _looks_interpretive(column)))
                if forbidden:
                    note = ("carries project-derived interpretation columns "
                            "(%s); comparison only, never evidence"
                            % ", ".join(forbidden))
        else:
            payload = self._load_json(entry.file_name)
            if isinstance(payload, Mapping):
                rows = len(payload)
                for value in payload.values():
                    source_id = _source_record_id(value)
                    if source_id:
                        identifiers.append(source_id)
            elif isinstance(payload, list):
                rows = len(payload)
                for value in payload:
                    source_id = _source_record_id(value)
                    if source_id:
                        identifiers.append(source_id)

        self._identifier_sets[entry.file_name] = tuple(sorted(set(identifiers)))
        self.reports.append(ArtifactReadReport(
            file_name=entry.file_name,
            relative_path=self._relative_path(entry.file_name),
            role=entry.role, read=False, record_count=rows,
            note=note or ("identifier set read for the derivation check only; "
                          "no record was taken from it")))

    def _count_excluded(self, entry: ArtifactRoleEntry) -> None:
        """Count out-of-scope candidate data without importing any of it."""
        path = self._path(entry.file_name)
        count = 0
        if entry.file_name.endswith(".csv"):
            try:
                with open(path, "r", encoding="utf-8", newline="") as handle:
                    count = max(sum(1 for _ in handle) - 1, 0)
            except (OSError, UnicodeDecodeError) as exc:
                self.findings.append(
                    "excluded artifact %s could not be counted: %s"
                    % (entry.file_name, exc))
        else:
            payload = self._load_json(entry.file_name)
            if isinstance(payload, (list, Mapping)):
                count = len(payload)
        key = entry.record_type or entry.file_name
        self.excluded[key] = self.excluded.get(key, 0) + count
        self.reports.append(ArtifactReadReport(
            file_name=entry.file_name,
            relative_path=self._relative_path(entry.file_name),
            role=entry.role, read=False, record_count=count,
            note="P1 candidate-onboarding data. Counted so the exclusion is "
                 "visible; no record enters the P0 canonical dataset."))

    def _count_missing_id(self, file_name: str) -> None:
        """Count a record with no source identity, without a finding per record.

        Aggregated deliberately: one finding per record would produce thousands
        of lines saying the same thing, and a report nobody reads is a report
        that hides its own contents.
        """
        self._missing_id_counts[file_name] = (
            self._missing_id_counts.get(file_name, 0) + 1)

    def _report_container_synonyms(self) -> None:
        """Report one record reached through two differently *named* containers.

        Case-variant containers are folded (``variantAnnotation`` and
        ``VariantAnnotation`` are one family). Differently *named* containers -
        ``label`` and ``DrugLabel`` - are not: treating them as one would be a
        synonym claim, and this package makes none. So the fact is reported,
        the containers stay separate, and a human decides.
        """
        synonyms: Dict[Tuple[str, ...], List[str]] = {}
        for (pair_key, source_id), families in self._families_by_record.items():
            if len(families) < 2:
                continue
            synonyms.setdefault(tuple(sorted(families)), []).append(
                "%s/%s" % (pair_key, source_id))
        for families, examples in sorted(synonyms.items()):
            self.container_synonyms.append({
                "container_families": list(families),
                "record_count": len(examples),
                "examples": sorted(examples)[:5],
            })
            self.findings.append(
                "%d source record(s) appear under differently named containers "
                "(%s) within one pair query. The names are not case variants, "
                "so they are not folded; whether they denote the same container "
                "is a review question, not a string question."
                % (len(examples), ", ".join(families)))

    # -- checks and summaries -------------------------------------------

    def check_derivations(self) -> None:
        """Re-verify every derived-from claim the role map makes."""
        for entry in ARTIFACT_ROLE_MAP:
            if entry.derived_from is None:
                continue
            derived = self._identifier_sets.get(entry.file_name)
            source = self._identifier_sets.get(entry.derived_from)
            if derived is None or source is None:
                continue
            only_derived = tuple(sorted(set(derived) - set(source)))
            only_source = tuple(sorted(set(source) - set(derived)))
            note = None
            if only_derived:
                note = ("the derived file carries identifiers its source does "
                        "not; the derivation claim no longer holds and this "
                        "artifact must be reclassified before it is trusted")
                self.findings.append(
                    "%s carries %d identifier(s) absent from %s"
                    % (entry.file_name, len(only_derived), entry.derived_from))
            self.derivation_checks.append(DerivationCheck(
                derived_artifact=entry.file_name,
                source_artifact=entry.derived_from,
                derived_identifier_count=len(derived),
                source_identifier_count=len(source),
                only_in_derived=only_derived,
                only_in_source=only_source,
                note=note))

    @property
    def missing_id_counts(self) -> Dict[str, int]:
        return dict(self._missing_id_counts)

    def axes(self) -> Dict[str, Any]:
        """Counts of what the source was observed to contain.

        Deliberately named for observation. These are not validated coverage,
        not clinical coverage, not supported treatments, not safe alternatives
        and not executable rules: they are how many things the snapshot
        mentions.
        """
        genes = sorted({item.normalized_value
                        for item in self.candidates
                        if item.entity_type is EntityType.GENE
                        and item.normalized_value})
        drugs = sorted({item.normalized_value
                        for item in self.candidates
                        if item.entity_type is EntityType.DRUG
                        and item.normalized_value})
        return {
            "source_observed_gene_count": len(genes),
            "source_observed_drug_count": len(drugs),
            "source_observed_pair_query_count": len(set(self._pair_keys)),
            "source_observed_record_count": len(self.observations),
            "source_observed_container_families": {
                family: sorted(spellings)
                for family, spellings in sorted(self._container_spellings.items())
            },
            "basis": ("counts of what this snapshot mentions. Not validated "
                      "coverage, not clinical coverage, not supported "
                      "treatment, not safe alternatives, not executable rules."),
        }

    # -- io helpers -----------------------------------------------------

    def _relative_path(self, file_name: str) -> str:
        descriptor = self.descriptors.get(file_name)
        return descriptor.relative_path if descriptor else file_name

    def _path(self, file_name: str) -> str:
        return os.path.join(self.root, self._relative_path(file_name))

    def _load_json(self, file_name: str) -> Any:
        path = self._path(file_name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError as exc:
            raise ArtifactRoleError(
                "artifact %s is listed in the manifest but absent from %s"
                % (file_name, self.root), artifacts=(file_name,)) from exc
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            raise ArtifactRoleError(
                "artifact %s could not be parsed as JSON: %s" % (file_name, exc),
                artifacts=(file_name,)) from exc

    def _locator(self, file_name: str, pointer: str,
                 source_record_id: Optional[str]) -> RawLocator:
        descriptor = self.descriptors.get(file_name)
        if descriptor is None:
            raise ArtifactRoleError(
                "no manifest descriptor for %s; a locator without an artifact "
                "digest could not be checked later" % file_name,
                artifacts=(file_name,))
        return RawLocator(
            dataset_public_id=self.manifest.dataset_public_id,
            snapshot_manifest_hash=self.manifest.manifest_hash,
            artifact_path=descriptor.relative_path,
            artifact_sha256=descriptor.sha256,
            pointer=pointer,
            source_record_id=source_record_id)

    def _external_ids(self, record: Mapping[str, Any]
                      ) -> Tuple[Tuple[ExternalIdentifier, ...], Tuple[str, ...]]:
        """Read the source's own accession plus any declared cross-references."""
        identifiers: List[ExternalIdentifier] = []
        findings: List[str] = []
        source_id = _source_record_id(record)
        if source_id:
            identifier, problem = normalize_external_id(SOURCE_ID_NAMESPACE,
                                                        source_id)
            identifiers.append(identifier)
            if problem:
                findings.append("source identifier %s: %s"
                                % (identifier.to_json(), problem))
        for reference in record.get("crossReferences") or ():
            if not isinstance(reference, Mapping):
                continue
            resource = _string_or_none(reference, "resource")
            value = _string_or_none(reference, "resourceId")
            if not resource or not value:
                continue
            try:
                identifier, problem = normalize_external_id(resource, value)
            except NormalizationError as exc:
                findings.append("cross reference %r/%r is unusable: %s"
                                % (resource, value, exc))
                continue
            identifiers.append(identifier)
            if problem:
                findings.append("cross reference %s: %s"
                                % (identifier.to_json(), problem))
        return tuple(identifiers), tuple(findings)


# -- small helpers ------------------------------------------------------


def _string_or_none(record: object, key: str) -> Optional[str]:
    if not isinstance(record, Mapping):
        return None
    value = record.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _source_record_id(record: object) -> Optional[str]:
    """The source's own record identity, as a string, or ``None``.

    This source spells identifiers two ways: accession strings such as
    ``PA166104948`` for guideline annotations and labels, and plain integers
    such as ``981351915`` for variant annotations. Both are identities, so both
    are read; an integer is rendered in its exact decimal form and never
    reformatted. Booleans are rejected because ``True`` is an ``int`` in Python
    and would silently become the record ID ``"1"``.

    A ``float`` is refused rather than coerced: ``9.813519e+08`` cannot be
    turned back into the identifier the source meant.
    """
    if not isinstance(record, Mapping):
        return None
    value = record.get("id")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _alias_strings(record: Mapping[str, Any], queried: str,
                   primary: str) -> Tuple[str, ...]:
    """Every alternative spelling the source offers, plus the queried one.

    The queried spelling is included because the legacy pipeline asked for it
    and got this record back; recording that as a *proposal* keeps the link
    without letting the query decide what the entity is.
    """
    out: List[str] = []
    if queried and queried != primary:
        out.append(queried)
    for key in ("altNames", "alternateNames", "synonyms", "genericNames",
                "tradeNames"):
        values = record.get(key)
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, (list, tuple)):
            continue
        for value in values:
            if isinstance(value, str) and value.strip():
                out.append(value.strip())
    seen = set()
    unique: List[str] = []
    for value in out:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return tuple(unique)


def _identifier_column(columns: Sequence[str]) -> Optional[str]:
    """Pick the column carrying the source record ID, by exact name only.

    Exact names, in a fixed order. No fuzzy header matching: guessing which
    column is an identifier is how a comparison silently compares the wrong
    thing.
    """
    lookup = {column.strip(): column for column in columns if column}
    for name in ("id", "gene_id", "chemical_id", "drug_id", "annotation_id",
                 "accession_id", "accessionId", "record_id"):
        if name in lookup:
            return lookup[name]
    return None


def _looks_interpretive(column: str) -> bool:
    """Whether a legacy column name names project-derived interpretation."""
    folded = column.strip().casefold().replace("-", "_").replace(" ", "_")
    return any(token in folded for token in FORBIDDEN_INTERPRETATION_KEYS)
