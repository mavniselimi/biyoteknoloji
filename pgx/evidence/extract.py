# -*- coding: utf-8 -*-
"""Reading source records out of the raw snapshot (WP-08).

Standard library plus :mod:`pgx.domain`, :mod:`pgx.ingestion.snapshots` and
:mod:`pgx.evidence`.

This module is the only place that knows the *shape* of the ClinPGx raw files.
Everything downstream works on :class:`~pgx.evidence.models.EvidenceRecordDraft`,
so a second source is added by writing a second extractor rather than by
touching the builder, the allocator or the repository.

**What it reads, and why those three.**

* ``pair_probe_raw.json`` → the **top-level** ``guidelineAnnotation`` section.
  This is where the substantial guideline records live: the asserting body in
  ``source``, the cited literature, the related genes and drugs, the summary
  and full text, and a ``history`` carrying real versions. WP-07 never read
  this section - it deduplicated the ``pair`` containers only.
* ``variant_annotation_filtered_raw.json`` → full variant annotations.
* ``pair_probe_raw.json`` → the ``pair.*`` containers. These are narrower views
  of records the two sources above also carry, plus the label annotations. They
  contribute locators and, for labels, records.

The derived CSVs are read by nothing here. A record imported from both the raw
JSON and the CSV derived from it would be one statement counted twice.

**One distinct source record becomes one evidence record.** Grouping is by
``(record type, source record id)`` across the whole snapshot, and every
contributing locator is retained. Records are never grouped because they share
a gene/drug pair: a CPIC and a DPWG guideline for CYP2C19 and clopidogrel are
two statements, and merging them would delete one.

**Several payloads for one identity are classified, not chosen.** See
:mod:`pgx.evidence.payloads`. A narrower view is folded into the wider one
because that discards nothing; a genuine disagreement keeps both payloads,
chooses neither, and raises a blocking issue.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import (Any, Dict, Iterable, List, Mapping, Optional, Sequence,
                    Tuple)

from pgx.domain.hashing import sha256_digest
from pgx.ingestion.snapshots import RawArtifactDescriptor, SnapshotManifest
from pgx.evidence.errors import SourceRecordError
from pgx.evidence.models import (EvidenceEntityLink, EvidenceEntityRole,
                                 EvidenceNaturalKey, EvidenceRecordDraft,
                                 EvidenceRecordType, ImportIssue,
                                 ImportIssueCode, IssueSeverity, OriginStatus,
                                 RawRecordLocator, SourceAttribution,
                                 SourceRecordVersion, SourceTextFragment,
                                 TextLanguage, VersionStatus,
                                 normalize_source_record_id)
from pgx.evidence.payloads import (PayloadRelation, choose_maximal_payload,
                                   describe_payload_difference)
from pgx.evidence.publications import parse_literature_objects
from pgx.evidence.record_types import map_record_type
from pgx.normalization.normalize import normalize_drug_name, normalize_gene_symbol

__all__ = [
    "EXTRACTION_RULE_VERSION",
    "GUIDELINE_SOURCE_REGISTRY_MAP",
    "PROVIDER_SOURCE_KEY",
    "SOURCE_ID_NAMESPACE",
    "CanonicalIndex",
    "ExtractionResult",
    "SourceRecordObservation",
    "extract_source_records",
    "json_pointer",
]

#: Bumped when the field selection or the record shaping changes.
EXTRACTION_RULE_VERSION = "pgx-evidence-extraction/1"

#: Where these bytes were retrieved from. The provider, never the asserter.
PROVIDER_SOURCE_KEY = "clinpgx.api"

#: The provider's own namespace for its accession identifiers.
SOURCE_ID_NAMESPACE = "clinpgx"

#: Guideline ``source`` values seen in this snapshot, mapped to registered
#: source keys. Exact values only: a body the source names and this map does
#: not know produces ``UNREGISTERED`` and an issue, never a nearest match.
GUIDELINE_SOURCE_REGISTRY_MAP: Mapping[str, str] = {
    "CPIC": "cpic.publications",
    "DPWG": "dpwg.knmp",
    "RNPGx": "rnpgx.publications",
    "AHA": "aha.publications",
    "AusNZ": "ausnz.publications",
    "CPNDS": "cpnds.publications",
}

#: Which fields carry source wording, per record type. The field name is kept
#: on every fragment, because a quotation that cannot say which field it came
#: from is not a citation.
_TEXT_FIELDS: Mapping[EvidenceRecordType, Tuple[Tuple[str, str], ...]] = {
    EvidenceRecordType.GUIDELINE_ANNOTATION: (
        ("name", "text/plain"),
        ("summaryMarkdown.html", "text/html"),
        ("textMarkdown.html", "text/html"),
    ),
    EvidenceRecordType.VARIANT_ANNOTATION: (
        ("sentence", "text/plain"),
        ("description", "text/plain"),
    ),
    EvidenceRecordType.DRUG_LABEL_ANNOTATION: (
        ("name", "text/plain"),
    ),
}


def json_pointer(*parts: object) -> str:
    """Build an RFC 6901 JSON Pointer, escaping properly.

    A container name is source data. An unescaped ``/`` inside one would
    produce a pointer that addresses something else entirely.
    """
    out = []
    for part in parts:
        text = str(part)
        out.append(text.replace("~", "~0").replace("/", "~1"))
    return "/" + "/".join(out) if out else ""


@dataclass(frozen=True, slots=True)
class SourceRecordObservation:
    """One sighting of one source record at one place in the raw snapshot."""

    record_type: EvidenceRecordType
    source_record_id: str
    source_record_id_raw: Any
    source_record_id_raw_type: str
    object_class: Optional[str]
    requested_container: Optional[str]
    payload: Mapping[str, Any]
    locator: RawRecordLocator
    query_gene: Optional[str] = None
    query_drug: Optional[str] = None

    @property
    def group_key(self) -> Tuple[str, str]:
        return (self.record_type.value, self.source_record_id)


class CanonicalIndex:
    """The WP-07 canonical entities, indexed for exact lookup only.

    Every index maps a key to a **sorted tuple** of canonical keys, never to one
    entity, for the reason WP-07 gives: a lookup returning a single entity would
    have had to choose between two, and there would be nowhere to show where.

    Built from ``entity-membership.ndjson``, so the links an evidence record
    carries are links into a specific canonical build rather than into whatever
    the database happens to hold.
    """

    def __init__(self, rows: Iterable[Mapping[str, Any]]) -> None:
        self._by_key: Dict[str, Mapping[str, Any]] = {}
        by_external: Dict[str, List[str]] = {}
        by_value: Dict[Tuple[str, str], List[str]] = {}

        for row in rows:
            canonical_key = row.get("canonical_key")
            if not canonical_key:
                continue
            if canonical_key in self._by_key:
                raise SourceRecordError(
                    "canonical key %r appears twice in the canonical build"
                    % canonical_key)
            self._by_key[canonical_key] = row
            entity_type = str(row.get("entity_type") or "")
            _, _, value = str(canonical_key).partition(":")
            by_value.setdefault((entity_type, value), []).append(canonical_key)
            for identifier in row.get("external_ids") or ():
                by_external.setdefault(str(identifier), []).append(canonical_key)

        self._by_external = {key: tuple(sorted(set(value)))
                             for key, value in by_external.items()}
        self._by_value = {key: tuple(sorted(set(value)))
                          for key, value in by_value.items()}

    @classmethod
    def from_build(cls, build_path: str) -> "CanonicalIndex":
        path = os.path.join(build_path, "entity-membership.ndjson")
        if not os.path.isfile(path):
            raise SourceRecordError(
                "no entity-membership.ndjson in %s; evidence cannot link to a "
                "canonical build it cannot read" % build_path)
        rows = []
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if text:
                    rows.append(json.loads(text))
        return cls(rows)

    def __len__(self) -> int:
        return len(self._by_key)

    def get(self, canonical_key: str) -> Optional[Mapping[str, Any]]:
        return self._by_key.get(canonical_key)

    def by_external_id(self, namespace: str, value: str) -> Tuple[str, ...]:
        return self._by_external.get("%s:%s" % (namespace, value), ())

    def by_normalized_value(self, entity_type: str,
                            value: str) -> Tuple[str, ...]:
        return self._by_value.get((entity_type, value), ())


@dataclass(frozen=True)
class ExtractionResult:
    """Everything the snapshot yielded, and everything it could not."""

    dataset_public_id: str
    snapshot_manifest_hash: str
    canonical_build_key: str
    canonical_build_content_hash: str
    extraction_rule_version: str
    drafts: Tuple[EvidenceRecordDraft, ...]
    issues: Tuple[ImportIssue, ...]
    observation_count: int
    artifacts_read: Tuple[str, ...]
    excluded_artifacts: Mapping[str, str] = field(default_factory=dict)

    def of_type(self, record_type: EvidenceRecordType
                ) -> Tuple[EvidenceRecordDraft, ...]:
        return tuple(item for item in self.drafts
                     if item.natural_key.record_type is record_type)

    @property
    def blocking_issues(self) -> Tuple[ImportIssue, ...]:
        return tuple(item for item in self.issues if item.blocking)

    @property
    def record_issues(self) -> Tuple[ImportIssue, ...]:
        """Every issue raised against a record, flattened.

        Kept separate from :attr:`issues`, which holds problems with the
        extraction itself. "This artifact is not an object" and "this record's
        origin is not stated" are different kinds of finding and a caller
        reports them differently.
        """
        return tuple(issue for draft in self.drafts for issue in draft.issues)

    def issue_counts(self) -> Dict[str, int]:
        """Every issue code and how often it fired, records included."""
        counts: Dict[str, int] = {}
        for issue in tuple(self.issues) + self.record_issues:
            counts[issue.code.value] = counts.get(issue.code.value, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def production_eligible(self) -> Tuple[EvidenceRecordDraft, ...]:
        return tuple(item for item in self.drafts if item.is_production_eligible)

    def to_json(self) -> Dict[str, Any]:
        return {
            "dataset_public_id": self.dataset_public_id,
            "snapshot_manifest_hash": self.snapshot_manifest_hash,
            "canonical_build_key": self.canonical_build_key,
            "extraction_rule_version": self.extraction_rule_version,
            "observation_count": self.observation_count,
            "record_count": len(self.drafts),
            "record_counts_by_type": {
                record_type.value: len(self.of_type(record_type))
                for record_type in EvidenceRecordType
                if self.of_type(record_type)},
            "artifacts_read": list(self.artifacts_read),
            "excluded_artifacts": dict(sorted(self.excluded_artifacts.items())),
            "extraction_issue_count": len(self.issues),
            "record_issue_count": len(self.record_issues),
            "blocking_record_count": sum(
                1 for item in self.drafts if item.blocking_issues),
            "production_eligible_record_count": len(self.production_eligible),
            "issue_counts": self.issue_counts(),
            "locator_count": sum(len(item.locators) for item in self.drafts),
            "entity_link_count": sum(len(item.entity_links)
                                     for item in self.drafts),
            "text_fragment_count": sum(len(item.text_fragments)
                                       for item in self.drafts),
            "publication_reference_count": sum(len(item.publications)
                                               for item in self.drafts),
        }


def extract_source_records(snapshot_root: str, manifest: SnapshotManifest,
                           canonical_index: CanonicalIndex,
                           canonical_build_key: str,
                           canonical_build_content_hash: str
                           ) -> ExtractionResult:
    """Read one sealed snapshot into evidence record drafts."""
    if not os.path.isdir(snapshot_root):
        raise SourceRecordError("no snapshot directory at %s" % snapshot_root)

    state = _ExtractionState(
        root=snapshot_root, manifest=manifest, index=canonical_index,
        canonical_build_key=canonical_build_key,
        canonical_build_content_hash=canonical_build_content_hash)

    state.read_pair_probe()
    state.read_variant_annotation_file()
    drafts = state.assemble()

    return ExtractionResult(
        dataset_public_id=manifest.dataset_public_id,
        snapshot_manifest_hash=manifest.manifest_hash,
        canonical_build_key=canonical_build_key,
        canonical_build_content_hash=canonical_build_content_hash,
        extraction_rule_version=EXTRACTION_RULE_VERSION,
        drafts=drafts,
        issues=tuple(sorted(state.issues, key=lambda item: item.key)),
        observation_count=len(state.observations),
        artifacts_read=tuple(sorted(state.artifacts_read)),
        excluded_artifacts=dict(sorted(state.excluded.items())))


# -- extraction state ---------------------------------------------------


class _ExtractionState:
    """Mutable scratch space for one extraction run."""

    #: Artifacts deliberately not read, and why. Named so the exclusion is
    #: visible in the build rather than implied by absence.
    EXCLUDED = {
        "guideline_annotation_rows.csv":
            "derived from pair_probe_raw.json's guideline section and carrying "
            "project-authored columns; comparison input only",
        "variant_annotation_filtered_rows.csv":
            "derived from variant_annotation_filtered_raw.json and carrying "
            "project-authored columns; comparison input only",
        "pair_annotation_rows.csv":
            "derived from pair_probe_raw.json's pair section; comparison input "
            "only",
        "resolved_genes.csv": "derived; WP-07 canonical entity comparison input",
        "resolved_chemicals.csv":
            "derived; WP-07 canonical entity comparison input",
        "resolved_genes.json":
            "WP-07 canonical entity input; entities are read from the canonical "
            "build, not re-derived here",
        "resolved_chemicals.json":
            "WP-07 canonical entity input; entities are read from the canonical "
            "build, not re-derived here",
        "mvp_candidate_drug_gene_edges.json":
            "P1 candidate-onboarding data, excluded from P0",
        "mvp_candidate_drug_gene_edges.csv":
            "P1 candidate-onboarding data, excluded from P0",
        "openapi_snapshot.json":
            "the source's API description; carries no scientific record",
    }

    def __init__(self, root: str, manifest: SnapshotManifest,
                 index: CanonicalIndex, canonical_build_key: str,
                 canonical_build_content_hash: str) -> None:
        self.root = root
        self.manifest = manifest
        self.index = index
        self.canonical_build_key = canonical_build_key
        self.canonical_build_content_hash = canonical_build_content_hash
        self.observations: List[SourceRecordObservation] = []
        self.issues: List[ImportIssue] = []
        self.artifacts_read: List[str] = []
        self.excluded: Dict[str, str] = dict(self.EXCLUDED)
        self._descriptors = {
            os.path.basename(item.relative_path): item
            for item in manifest.artifacts}
        self._missing_id_counts: Dict[str, int] = {}

    # -- readers ---------------------------------------------------------

    def read_pair_probe(self) -> None:
        """Read both the guideline section and the pair containers."""
        name = "pair_probe_raw.json"
        payload = self._load_json(name)
        if not isinstance(payload, Mapping):
            self._issue(ImportIssueCode.PAYLOAD_NOT_AN_OBJECT,
                        IssueSeverity.BLOCKING, name,
                        "expected an object keyed by GENE::drug")
            return
        self.artifacts_read.append(name)

        for pair_key in sorted(payload):
            entry = payload[pair_key]
            if not isinstance(entry, Mapping):
                continue
            gene_symbol, drug_name = _split_pair_key(pair_key)

            for index, record in enumerate(entry.get("guidelineAnnotation")
                                           or ()):
                self._observe(
                    record, name,
                    json_pointer(pair_key, "guidelineAnnotation", index),
                    requested_container="guidelineAnnotation",
                    query_gene=gene_symbol, query_drug=drug_name)

            containers = entry.get("pair")
            if not isinstance(containers, Mapping):
                continue
            for container in sorted(containers):
                members = containers[container]
                if not isinstance(members, list):
                    continue
                for index, record in enumerate(members):
                    self._observe(
                        record, name,
                        json_pointer(pair_key, "pair", container, index),
                        requested_container=container,
                        query_gene=gene_symbol, query_drug=drug_name)

    def read_variant_annotation_file(self) -> None:
        name = "variant_annotation_filtered_raw.json"
        payload = self._load_json(name)
        if not isinstance(payload, Mapping):
            self._issue(ImportIssueCode.PAYLOAD_NOT_AN_OBJECT,
                        IssueSeverity.BLOCKING, name,
                        "expected an object keyed by gene symbol")
            return
        self.artifacts_read.append(name)

        for gene_symbol in sorted(payload):
            members = payload[gene_symbol]
            if not isinstance(members, list):
                continue
            for index, record in enumerate(members):
                self._observe(record, name, json_pointer(gene_symbol, index),
                              requested_container=None,
                              query_gene=gene_symbol, query_drug=None)

    def _observe(self, record: Any, file_name: str, pointer: str,
                 requested_container: Optional[str],
                 query_gene: Optional[str],
                 query_drug: Optional[str]) -> None:
        """Record one sighting, or report why it could not be one."""
        locator = self._locator(file_name, pointer, requested_container)
        if not isinstance(record, Mapping):
            self._issue(ImportIssueCode.PAYLOAD_NOT_AN_OBJECT,
                        IssueSeverity.BLOCKING, file_name,
                        "%s is a %s, not an object"
                        % (pointer, type(record).__name__), locator=locator)
            return

        object_class = record.get("objCls")
        mapping = map_record_type(object_class, requested_container)
        record_id, raw_type = normalize_source_record_id(record.get("id"))
        if record_id is None:
            key = "%s/%s" % (file_name, requested_container or "-")
            self._missing_id_counts[key] = self._missing_id_counts.get(key,
                                                                       0) + 1
            self._issue(
                ImportIssueCode.SOURCE_RECORD_ID_MISSING,
                IssueSeverity.BLOCKING, file_name,
                "%s carries no usable source record id (raw type %s); it "
                "cannot be identified, so it is reported rather than imported"
                % (pointer, raw_type), locator=locator)
            return

        self.observations.append(SourceRecordObservation(
            record_type=mapping.record_type,
            source_record_id=record_id,
            source_record_id_raw=record.get("id"),
            source_record_id_raw_type=raw_type,
            object_class=object_class if isinstance(object_class, str) else None,
            requested_container=requested_container,
            payload=record,
            locator=locator,
            query_gene=query_gene,
            query_drug=query_drug))

    # -- assembly --------------------------------------------------------

    def assemble(self) -> Tuple[EvidenceRecordDraft, ...]:
        """Group observations into one draft per distinct source record."""
        grouped: Dict[Tuple[str, str], List[SourceRecordObservation]] = {}
        for observation in self.observations:
            grouped.setdefault(observation.group_key, []).append(observation)

        drafts: List[EvidenceRecordDraft] = []
        for key in sorted(grouped):
            draft = self._draft(grouped[key])
            if draft is not None:
                drafts.append(draft)
        return tuple(sorted(
            drafts, key=lambda item: item.natural_key.to_string()))

    def _draft(self, observations: Sequence[SourceRecordObservation]
               ) -> Optional[EvidenceRecordDraft]:
        first = observations[0]
        issues: List[ImportIssue] = []
        locators = tuple(item.locator for item in observations)

        relation, payload = choose_maximal_payload(
            [dict(item.payload) for item in observations])
        if payload is None:
            differences = ()
            payloads = [dict(item.payload) for item in observations]
            if len(payloads) > 1:
                differences = describe_payload_difference(payloads[0],
                                                          payloads[1])
            issues.append(ImportIssue(
                code=ImportIssueCode.CONFLICTING_SOURCE_IDENTITY,
                severity=IssueSeverity.BLOCKING,
                subject=first.source_record_id,
                detail=("source record %s carries payloads that disagree (%s). "
                        "Both are kept and neither is chosen: one of them is "
                        "wrong, and discarding either would hide which. "
                        "Differences: %s"
                        % (first.source_record_id, relation.value,
                           "; ".join(differences) or "no shared path compared")),
                locator=first.locator))
            # The record is still emitted, carrying every locator and the
            # blocking issue, so the conflict is visible rather than absent.
            payload = dict(first.payload)

        mapping = map_record_type(
            payload.get("objCls") if isinstance(payload.get("objCls"), str)
            else first.object_class,
            first.requested_container)
        if mapping.status.value == "PENDING_REVIEW":
            issues.append(ImportIssue(
                code=ImportIssueCode.RECORD_TYPE_PENDING_REVIEW,
                severity=IssueSeverity.BLOCKING,
                subject=first.source_record_id,
                detail=mapping.rationale, locator=first.locator))
        elif mapping.status.value == "UNMAPPED":
            issues.append(ImportIssue(
                code=ImportIssueCode.RECORD_TYPE_UNMAPPED,
                severity=IssueSeverity.BLOCKING,
                subject=first.source_record_id,
                detail=mapping.rationale, locator=first.locator))

        version = _read_version(payload)
        if version.status is VersionStatus.UNKNOWN_LEGACY:
            issues.append(ImportIssue(
                code=ImportIssueCode.SOURCE_VERSION_UNKNOWN_LEGACY,
                severity=IssueSeverity.BLOCKING,
                subject=first.source_record_id,
                detail=("no version metadata survives for this record. It is "
                        "recorded as UNKNOWN_LEGACY rather than given a "
                        "fabricated version, and it cannot support production "
                        "evidence until a versioned acquisition replaces it."),
                locator=first.locator))

        attribution, attribution_issue = _read_attribution(payload,
                                                           mapping.record_type)
        if attribution_issue is not None:
            code, severity, detail = attribution_issue
            issues.append(ImportIssue(code=code, severity=severity,
                                      subject=first.source_record_id,
                                      detail=detail, locator=first.locator))

        natural_key = EvidenceNaturalKey(
            dataset_public_id=self.manifest.dataset_public_id,
            provider_source_key=PROVIDER_SOURCE_KEY,
            record_type=mapping.record_type,
            source_record_id=first.source_record_id,
            version_part=version.key_part)

        links, link_issues = self._entity_links(payload, observations,
                                                mapping.record_type)
        issues.extend(link_issues)
        if not links:
            issues.append(ImportIssue(
                code=ImportIssueCode.NO_REQUIRED_ENTITY_LINK,
                severity=IssueSeverity.BLOCKING,
                subject=first.source_record_id,
                detail=("no canonical gene or drug could be linked to this "
                        "record; it is kept with its provenance and cannot "
                        "support anything until a link is resolved"),
                locator=first.locator))

        fragments = _text_fragments(payload, mapping.record_type, first.locator)
        if not fragments:
            issues.append(ImportIssue(
                code=ImportIssueCode.SOURCE_TEXT_ABSENT,
                severity=IssueSeverity.ADVISORY,
                subject=first.source_record_id,
                detail="the record carries no readable source wording",
                locator=first.locator))

        parsed = parse_literature_objects(payload.get("literature"))
        for problem in parsed.issues:
            issues.append(ImportIssue(
                code=ImportIssueCode.PUBLICATION_FIELD_COUNT_MISMATCH,
                severity=IssueSeverity.ADVISORY,
                subject=first.source_record_id, detail=problem,
                locator=first.locator))
        for reference in parsed.references:
            for problem in reference.issues:
                issues.append(ImportIssue(
                    code=ImportIssueCode.PUBLICATION_IDENTIFIER_INVALID,
                    severity=IssueSeverity.ADVISORY,
                    subject="%s publication %d"
                            % (first.source_record_id, reference.ordinal),
                    detail=problem, locator=first.locator))

        # Normalized metadata holds only facts about the *reading*, never a
        # judgement about the science. Every project-authored field name is
        # refused by EvidenceRecordDraft, so this stays checkable.
        normalized_metadata = {
            "extraction_rule_version": EXTRACTION_RULE_VERSION,
            "observation_count": len(observations),
            "payload_relation": relation.value,
            "requested_containers": sorted(
                {item.requested_container for item in observations
                 if item.requested_container}),
            "source_object_class": mapping.source_object_class,
            "publication_reference_count": len(parsed.references),
            "publication_identified_count": len(parsed.identified),
            "source_text_fragment_count": len(fragments),
        }

        return EvidenceRecordDraft(
            natural_key=natural_key,
            record_type_mapping=mapping,
            attribution=attribution,
            version=version,
            source_record_id_raw=first.source_record_id_raw,
            source_record_id_raw_type=first.source_record_id_raw_type,
            raw_source_payload=payload,
            locators=locators,
            canonical_build_key=self.canonical_build_key,
            canonical_build_content_hash=self.canonical_build_content_hash,
            entity_links=tuple(links),
            text_fragments=tuple(fragments),
            publications=parsed.references,
            normalized_metadata=normalized_metadata,
            issues=tuple(issues))

    # -- entity linking --------------------------------------------------

    def _entity_links(self, payload: Mapping[str, Any],
                      observations: Sequence[SourceRecordObservation],
                      record_type: EvidenceRecordType
                      ) -> Tuple[List[EvidenceEntityLink], List[ImportIssue]]:
        """Resolve every entity the record names, and every query it arrived under.

        A record naming three genes produces three links. Nothing is duplicated
        per pair, and an ambiguous reference is reported rather than attached to
        whichever entity sorted first.
        """
        links: Dict[Tuple[str, str, str], EvidenceEntityLink] = {}
        issues: List[ImportIssue] = []
        record_id = observations[0].source_record_id
        locator = observations[0].locator

        for field_name, entity_type in (("relatedGenes", "GENE"),
                                        ("relatedChemicals", "DRUG")):
            for entry in payload.get(field_name) or ():
                if not isinstance(entry, Mapping):
                    continue
                link, issue = self._resolve_entity(
                    entity_type=entity_type,
                    accession=entry.get("id"),
                    name=(entry.get("symbol") if entity_type == "GENE"
                          else entry.get("name")),
                    role=EvidenceEntityRole.RELATED_ENTITY,
                    source_field=field_name, record_id=record_id,
                    locator=locator)
                if link is not None:
                    links.setdefault(link.key, link)
                if issue is not None:
                    issues.append(issue)

        for observation in observations:
            for value, entity_type, field_name in (
                    (observation.query_gene, "GENE", "pair query gene"),
                    (observation.query_drug, "DRUG", "pair query drug")):
                if not value:
                    continue
                link, issue = self._resolve_entity(
                    entity_type=entity_type, accession=None, name=value,
                    role=EvidenceEntityRole.QUERY_CONTEXT,
                    source_field=field_name, record_id=record_id,
                    locator=observation.locator)
                if link is not None:
                    links.setdefault(link.key, link)
                if issue is not None:
                    issues.append(issue)

        return (sorted(links.values(), key=lambda item: item.key),
                issues)

    def _resolve_entity(self, entity_type: str, accession: Any,
                        name: Any, role: EvidenceEntityRole,
                        source_field: str, record_id: str,
                        locator: RawRecordLocator
                        ) -> Tuple[Optional[EvidenceEntityLink],
                                   Optional[ImportIssue]]:
        """Exact lookup only: accession first, then normalised name.

        Two stages, in that order, each returning every candidate. More than
        one candidate is an ambiguity and stops there - it is never settled by
        taking the first, and there is no fuzzy fallback.
        """
        raw_value = str(accession or name or "").strip() or None
        candidates: Tuple[str, ...] = ()
        if isinstance(accession, str) and accession.strip():
            candidates = self.index.by_external_id(SOURCE_ID_NAMESPACE,
                                                   accession.strip())
        if not candidates and name:
            try:
                normalized = (normalize_gene_symbol(str(name))
                              if entity_type == "GENE"
                              else normalize_drug_name(str(name)))
            except Exception:
                normalized = None
            if normalized:
                candidates = self.index.by_normalized_value(entity_type,
                                                            normalized)

        if len(candidates) == 1:
            canonical_key = candidates[0]
            row = self.index.get(canonical_key) or {}
            return EvidenceEntityLink(
                entity_type=entity_type, canonical_key=canonical_key,
                entity_uuid=str(row.get("entity_uuid")),
                role=role, source_field=source_field,
                raw_value=raw_value), None
        if len(candidates) > 1:
            return None, ImportIssue(
                code=ImportIssueCode.ENTITY_REFERENCE_AMBIGUOUS,
                severity=IssueSeverity.BLOCKING, subject=record_id,
                detail=("%s %r matched %d canonical entities (%s); it is not "
                        "settled by choosing one"
                        % (source_field, raw_value, len(candidates),
                           ", ".join(candidates))),
                locator=locator)
        return None, ImportIssue(
            code=ImportIssueCode.ENTITY_REFERENCE_UNRESOLVED,
            severity=IssueSeverity.ADVISORY, subject=record_id,
            detail=("%s %r matched no entity in this canonical build. The "
                    "reference is reported; no entity is created for it."
                    % (source_field, raw_value)),
            locator=locator)

    # -- io helpers ------------------------------------------------------

    def _relative_path(self, file_name: str) -> str:
        descriptor = self._descriptors.get(file_name)
        return descriptor.relative_path if descriptor else file_name

    def _load_json(self, file_name: str) -> Any:
        path = os.path.join(self.root, self._relative_path(file_name))
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError as exc:
            raise SourceRecordError(
                "artifact %s is listed in the manifest and absent from %s"
                % (file_name, self.root)) from exc
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            raise SourceRecordError(
                "artifact %s could not be parsed as JSON: %s"
                % (file_name, exc)) from exc

    def _locator(self, file_name: str, pointer: str,
                 requested_container: Optional[str]) -> RawRecordLocator:
        descriptor = self._descriptors.get(file_name)
        if descriptor is None:
            raise SourceRecordError(
                "no manifest descriptor for %s; a locator without an artifact "
                "digest could not be checked later" % file_name)
        return RawRecordLocator(
            dataset_public_id=self.manifest.dataset_public_id,
            snapshot_manifest_hash=self.manifest.manifest_hash,
            artifact_path=descriptor.relative_path,
            artifact_sha256=descriptor.sha256,
            pointer=pointer,
            artifact_id=descriptor.request_key,
            requested_container=requested_container)

    def _issue(self, code: ImportIssueCode, severity: IssueSeverity,
               subject: str, detail: str,
               locator: Optional[RawRecordLocator] = None) -> None:
        self.issues.append(ImportIssue(code=code, severity=severity,
                                       subject=subject, detail=detail,
                                       locator=locator))


# -- record readers -----------------------------------------------------


def _read_version(payload: Mapping[str, Any]) -> SourceRecordVersion:
    """Read the version the source stated, or say plainly that there is none.

    ClinPGx records carry a ``history`` list whose entries hold a ``version``.
    The highest is the record's current version. A record with no history gets
    ``UNKNOWN_LEGACY`` - never ``v1``, never ``0``, and never the count of
    history entries.
    """
    history = payload.get("history")
    if history is None:
        return SourceRecordVersion(
            status=VersionStatus.UNKNOWN_LEGACY, raw_value=None,
            basis=("the record carries no history; this legacy snapshot "
                   "retained no version metadata for it"))
    if not isinstance(history, list):
        return SourceRecordVersion(
            status=VersionStatus.INVALID, raw_value=str(history)[:200],
            basis="history is a %s, not a list" % type(history).__name__)
    versions = [entry.get("version") for entry in history
                if isinstance(entry, Mapping)
                and isinstance(entry.get("version"), int)
                and not isinstance(entry.get("version"), bool)]
    if not versions:
        return SourceRecordVersion(
            status=VersionStatus.MISSING, raw_value=None,
            basis=("history is present with %d entries and none states a "
                   "version" % len(history)))
    return SourceRecordVersion(
        status=VersionStatus.KNOWN, value=str(max(versions)),
        raw_value=max(versions),
        basis="the highest version in the record's own history")


def _read_attribution(payload: Mapping[str, Any],
                      record_type: EvidenceRecordType
                      ) -> Tuple[SourceAttribution,
                                 Optional[Tuple[ImportIssueCode, IssueSeverity,
                                                str]]]:
    """Read who the record says asserted it, or record that it does not say.

    Only an explicit ``source`` field produces an origin. A label annotation
    names its regulator inside a prose ``name`` such as "Annotation of FDA
    Label for clopidogrel and CYP2C19"; reading "FDA" out of that sentence
    would be inference, so the origin stays not-stated and the raw name is
    preserved.
    """
    raw = payload.get("source")
    if isinstance(raw, str) and raw.strip():
        value = raw.strip()
        registry_key = GUIDELINE_SOURCE_REGISTRY_MAP.get(value)
        if registry_key is None:
            return (SourceAttribution(
                provider_source_key=PROVIDER_SOURCE_KEY,
                origin_status=OriginStatus.UNREGISTERED,
                raw_origin_value=value, origin_field="source"),
                (ImportIssueCode.ORIGIN_SOURCE_UNREGISTERED,
                 IssueSeverity.BLOCKING,
                 "the record names %r as its source and no registered source "
                 "key matches it exactly; the raw value is preserved and no "
                 "nearest match is guessed" % value))
        return (SourceAttribution(
            provider_source_key=PROVIDER_SOURCE_KEY,
            origin_status=OriginStatus.STATED_BY_SOURCE,
            origin_source_key=registry_key, raw_origin_value=value,
            origin_field="source"), None)

    detail = ("the record carries no source field, so who asserted it is not "
              "stated. Nothing is inferred from its prose.")
    if record_type is EvidenceRecordType.DRUG_LABEL_ANNOTATION:
        detail = ("a label annotation names its regulator only inside its "
                  "free-text name; reading it out of that sentence would be "
                  "inference, so the origin stays not-stated.")
    return (SourceAttribution(
        provider_source_key=PROVIDER_SOURCE_KEY,
        origin_status=OriginStatus.NOT_STATED_BY_SOURCE,
        raw_origin_value=(str(payload.get("name"))[:300]
                          if payload.get("name") else None),
        origin_field=None),
        (ImportIssueCode.ORIGIN_SOURCE_NOT_STATED, IssueSeverity.BLOCKING,
         detail))


def _text_fragments(payload: Mapping[str, Any],
                    record_type: EvidenceRecordType,
                    locator: RawRecordLocator) -> List[SourceTextFragment]:
    """Pull the source's own wording, field by field, unchanged.

    Fields are never concatenated. The ClinPGx summary for CYP2C19 and
    clopidogrel begins "Avoid clopidogrel use in patients who are CYP2C19 poor
    metabolizers"; that is the source's sentence and it is preserved as such.
    Nothing here promotes it to a recommendation this project makes.
    """
    fragments: List[SourceTextFragment] = []
    for ordinal, (path, text_format) in enumerate(
            _TEXT_FIELDS.get(record_type, ())):
        value = _dig(payload, path)
        if not isinstance(value, str) or not value.strip():
            continue
        fragments.append(SourceTextFragment(
            field_name=path, text=value, ordinal=ordinal, locator=locator,
            language=TextLanguage.UNKNOWN, text_format=text_format))
    return fragments


def _dig(payload: Mapping[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _split_pair_key(pair_key: str) -> Tuple[Optional[str], Optional[str]]:
    if "::" not in pair_key:
        return None, None
    gene, _, drug = pair_key.partition("::")
    return (gene.strip() or None), (drug.strip() or None)
