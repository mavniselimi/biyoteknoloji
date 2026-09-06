# -*- coding: utf-8 -*-
"""What each raw snapshot artifact is, and what it may be used for (WP-07).

Standard library only.

**A role map, not a parser loop.** Twelve files sit in the WP-06 snapshot and
they are not twelve independent sources of scientific record. Two are the
least-derived entity representation; two are CSVs derived from those same two
JSON documents; two more are a P1 candidate feature that must never enter the
P0 canonical dataset; one is an API schema. Walking the directory and parsing
whatever is there would count the same five genes twice and would import
candidate drugs nobody approved.

**Unknown artifacts are reported, never guessed at.** An artifact absent from
this map produces an ``UNRECOGNISED_ARTIFACT`` finding and is not read. A build
that silently interpreted an unfamiliar file would invent records whose origin
nobody could explain afterwards.

**Derivation is recorded, so a derived file can be used honestly.** A CSV
derived from a JSON document is genuinely useful - as a consistency check
against the document it came from, and as the legacy comparison baseline. It is
not a second observation of the same fact, and ``counts_as_evidence`` says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Mapping, Optional, Tuple

__all__ = [
    "ARTIFACT_ROLE_MAP",
    "ARTIFACT_ROLE_MAP_VERSION",
    "ArtifactRole",
    "ArtifactRoleEntry",
    "classify_artifacts",
    "role_of",
]

#: Bumped when the map changes. Recorded in the canonical manifest so a build
#: can be read years later without guessing which classification produced it.
ARTIFACT_ROLE_MAP_VERSION = "pgx-artifact-roles/2"

#: The artifact family a WP-06 ClinPGx probe snapshot carries.
LEGACY_PROBE_ARTIFACT_SET = "clinpgx-legacy-probe"

#: The artifact family a Wave 3B transcription capture carries.
CAPTURE_ARTIFACT_SET = "cpic-guideline-capture"


class ArtifactRole(str, Enum):
    """What a raw artifact is permitted to contribute to a canonical build."""

    #: The least-derived representation of canonical entities. Genes and drugs
    #: are proposed from these and from nothing else.
    ENTITY_CANDIDATE_INPUT = "ENTITY_CANDIDATE_INPUT"
    #: Relationships between entities, referenced by external ID. Resolved
    #: against the canonical catalog; never a source of new entities.
    RELATIONSHIP_REFERENCE_INPUT = "RELATIONSHIP_REFERENCE_INPUT"
    #: Raw annotation payloads. Counted and deduplicated; not interpreted.
    RAW_ANNOTATION_INPUT = "RAW_ANNOTATION_INPUT"
    #: A file the legacy pipeline derived from another artifact in this
    #: snapshot. Used for comparison and consistency, never as evidence.
    DERIVED_LEGACY_COMPARISON = "DERIVED_LEGACY_COMPARISON"
    #: The source's own API description. Reference only.
    API_SCHEMA_REFERENCE = "API_SCHEMA_REFERENCE"
    #: P1 candidate-exploration data. Explicitly excluded from P0.
    OUT_OF_SCOPE_P1_CANDIDATE_DATA = "OUT_OF_SCOPE_P1_CANDIDATE_DATA"
    #: Present in the snapshot and absent from this map.
    UNRECOGNISED = "UNRECOGNISED"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ArtifactRoleEntry:
    """One artifact's classification, with the reasoning attached.

    ``rationale`` is not decoration. Somebody reading a canonical build in two
    years needs to know why ``resolved_genes.csv`` contributed no entities, and
    "it is derived from the JSON beside it" is the whole answer.
    """

    file_name: str
    role: ArtifactRole
    rationale: str
    derived_from: Optional[str] = None
    record_type: Optional[str] = None
    #: Which family of snapshots is expected to carry this artifact.
    #:
    #: Added because "missing" is only meaningful relative to what a given
    #: snapshot was ever going to contain. Before this field, the map was one
    #: flat list and every snapshot was judged against all of it - which was
    #: harmless while exactly one snapshot shape existed and became wrong the
    #: moment a second did: a transcription capture would be reported as
    #: missing four ClinPGx probe files it was never going to have, and the
    #: legacy probe snapshot would simultaneously be reported as missing four
    #: capture files. Both reports would have been nonsense, and the
    #: evidence-role ones would have blocked.
    artifact_set: str = "clinpgx-legacy-probe"

    @property
    def counts_as_evidence(self) -> bool:
        """True when this artifact may contribute records to the build.

        A derived file never does, whatever it contains: counting a CSV and the
        JSON it was written from would double every record in it.
        """
        return self.role in (ArtifactRole.ENTITY_CANDIDATE_INPUT,
                             ArtifactRole.RELATIONSHIP_REFERENCE_INPUT,
                             ArtifactRole.RAW_ANNOTATION_INPUT)

    def to_json(self) -> Dict[str, object]:
        return {
            "file_name": self.file_name,
            "role": self.role.value,
            "rationale": self.rationale,
            "derived_from": self.derived_from,
            "record_type": self.record_type,
            "artifact_set": self.artifact_set,
            "counts_as_evidence": self.counts_as_evidence,
        }


#: The classification of every artifact in the WP-06 legacy snapshot.
#:
#: Each entry was decided by inspecting the file, not by its name. The two
#: ``resolved_*.csv`` files carry exactly the identifier sets of the JSON
#: documents beside them, which is what makes the derivation claim checkable
#: rather than assumed - and a consistency check in the builder re-verifies it
#: on every run.
ARTIFACT_ROLE_MAP: Tuple[ArtifactRoleEntry, ...] = (
    # -- Wave 3B transcription-capture artifacts ----------------------------
    #
    # These four names belong to a TRANSCRIPTION_CAPTURE snapshot, not to a
    # WP-04 acquisition. They are separate names rather than reuses of the
    # ``resolved_*`` / ``pair_probe_raw`` / ``variant_annotation_*`` names
    # above, and that separation is the point: those names mean "this is what
    # the ClinPGx endpoint returned", and a guideline recommendation table read
    # from a published page is not that. Giving this content those names would
    # have made the misdescription invisible at every later read.
    ArtifactRoleEntry(
        "capture_genes.json", ArtifactRole.ENTITY_CANDIDATE_INPUT,
        "Genes named by the captured guideline tables, keyed by symbol. The "
        "capture carries no external gene accession, because a guideline "
        "recommendation table does not publish one; the records therefore "
        "propose an entity and no cross-reference.",
        record_type="gene", artifact_set=CAPTURE_ARTIFACT_SET),
    ArtifactRoleEntry(
        "capture_chemicals.json", ArtifactRole.ENTITY_CANDIDATE_INPUT,
        "Drugs named by the captured guideline tables, keyed by name. As with "
        "the genes, no external accession is claimed.",
        record_type="drug", artifact_set=CAPTURE_ARTIFACT_SET),
    ArtifactRoleEntry(
        "capture_axes.json", ArtifactRole.RELATIONSHIP_REFERENCE_INPUT,
        "The gene-drug axes the captured guidelines cover, keyed GENE::drug. "
        "References only: an axis resolves against the canonical catalog and "
        "never creates the entities it names.",
        record_type="capture_axis", artifact_set=CAPTURE_ARTIFACT_SET),
    ArtifactRoleEntry(
        "capture_recommendation_rows.json", ArtifactRole.RAW_ANNOTATION_INPUT,
        "One record per transcribed recommendation row, including the rows "
        "this project's phenotype vocabulary cannot carry. Counted and "
        "deduplicated; not interpreted here. The interpretation into an "
        "attention level happens in curation, under its own authority state.",
        record_type="capture_recommendation_row",
        artifact_set=CAPTURE_ARTIFACT_SET),
    ArtifactRoleEntry(
        "resolved_genes.json", ArtifactRole.ENTITY_CANDIDATE_INPUT,
        "Least-derived gene representation: a mapping of queried symbol to the "
        "source's own gene object, external ID included. Canonical genes are "
        "proposed from here.",
        record_type="gene"),
    ArtifactRoleEntry(
        "resolved_chemicals.json", ArtifactRole.ENTITY_CANDIDATE_INPUT,
        "Least-derived chemical representation, external ID included. "
        "Canonical drugs are proposed from here. Recognising a chemical says "
        "nothing about pharmacogenetic coverage.",
        record_type="drug"),
    ArtifactRoleEntry(
        "resolved_genes.csv", ArtifactRole.DERIVED_LEGACY_COMPARISON,
        "A flattening of resolved_genes.json: identical identifier set, fewer "
        "fields. Used to check the JSON was flattened faithfully; contributes "
        "no entities.",
        derived_from="resolved_genes.json", record_type="gene"),
    ArtifactRoleEntry(
        "resolved_chemicals.csv", ArtifactRole.DERIVED_LEGACY_COMPARISON,
        "A flattening of resolved_chemicals.json: identical identifier set. "
        "Consistency check only.",
        derived_from="resolved_chemicals.json", record_type="drug"),
    ArtifactRoleEntry(
        "pair_probe_raw.json", ArtifactRole.RELATIONSHIP_REFERENCE_INPUT,
        "The pair endpoint's raw response per gene::drug query. Its 'pair' "
        "section carries the same records under case-variant container names, "
        "which is LEGACY-BUG-004 and the primary deduplication input.",
        record_type="pair_container_record"),
    ArtifactRoleEntry(
        "variant_annotation_filtered_raw.json", ArtifactRole.RAW_ANNOTATION_INPUT,
        "Variant annotations retrieved per gene from the data endpoint. Raw "
        "payloads: counted, deduplicated and referenced, never interpreted.",
        record_type="variant_annotation"),
    ArtifactRoleEntry(
        "guideline_annotation_rows.csv", ArtifactRole.DERIVED_LEGACY_COMPARISON,
        "Legacy flattening of guideline annotations, carrying project-derived "
        "columns (significance, score, polarity) that are interpretation and "
        "belong to WP-08 and later. Comparison only.",
        record_type="guideline_annotation"),
    ArtifactRoleEntry(
        "variant_annotation_filtered_rows.csv", ArtifactRole.DERIVED_LEGACY_COMPARISON,
        "Legacy flattening of variant_annotation_filtered_raw.json with the "
        "same project-derived columns. Comparison only.",
        derived_from="variant_annotation_filtered_raw.json",
        record_type="variant_annotation"),
    ArtifactRoleEntry(
        "pair_annotation_rows.csv", ArtifactRole.DERIVED_LEGACY_COMPARISON,
        "Legacy flattening of pair_probe_raw.json's pair section, one row per "
        "container member. Used to cross-check the observed collision counts "
        "against the JSON they were derived from.",
        derived_from="pair_probe_raw.json", record_type="pair_container_record"),
    ArtifactRoleEntry(
        "mvp_candidate_drug_gene_edges.json",
        ArtifactRole.OUT_OF_SCOPE_P1_CANDIDATE_DATA,
        "Candidate drug-gene edge exploration. A P1 feature; importing it into "
        "P0 would add drugs no reviewer selected. Counted and excluded.",
        record_type="candidate_edge"),
    ArtifactRoleEntry(
        "mvp_candidate_drug_gene_edges.csv",
        ArtifactRole.OUT_OF_SCOPE_P1_CANDIDATE_DATA,
        "Flattening of the candidate edge JSON. Excluded for the same reason "
        "and derived besides.",
        derived_from="mvp_candidate_drug_gene_edges.json",
        record_type="candidate_edge"),
    ArtifactRoleEntry(
        "openapi_snapshot.json", ArtifactRole.API_SCHEMA_REFERENCE,
        "The source's own OpenAPI description. Documents what the endpoints "
        "were; carries no scientific record.",
        record_type=None),
)

_BY_NAME: Mapping[str, ArtifactRoleEntry] = {
    entry.file_name: entry for entry in ARTIFACT_ROLE_MAP}


def role_of(file_name: str) -> ArtifactRoleEntry:
    """Return the classification for one artifact file name.

    An unmapped name returns an ``UNRECOGNISED`` entry rather than raising: the
    build reports it and carries on with what it does understand, which is more
    useful than refusing to produce any report at all.
    """
    entry = _BY_NAME.get(file_name)
    if entry is not None:
        return entry
    return ArtifactRoleEntry(
        file_name, ArtifactRole.UNRECOGNISED,
        "This artifact is not in the WP-07 role map. It was not read, and no "
        "record was derived from it. Classify it before relying on it.")


def classify_artifacts(file_names) -> Tuple[Tuple[ArtifactRoleEntry, ...],
                                            Tuple[str, ...]]:
    """Classify a snapshot's artifacts, and name what the map expected and lost.

    Returns ``(entries, missing)``. ``missing`` lists mapped artifacts that the
    snapshot does not contain - a snapshot short of an entity input is a
    different build from one that merely lacks a comparison file, and only the
    caller can judge which.
    """
    present = tuple(sorted(file_names))
    entries = tuple(role_of(name) for name in present)
    observed_sets = {entry.artifact_set for entry in entries
                     if entry.role is not ArtifactRole.UNRECOGNISED}
    if not observed_sets:
        # Nothing recognised at all. Reporting every mapped name as missing
        # would bury the real finding, which is that this snapshot matches no
        # known artifact family.
        return entries, ()
    expected = {name for name, entry in _BY_NAME.items()
                if entry.artifact_set in observed_sets}
    missing = tuple(sorted(expected - set(present)))
    return entries, missing
