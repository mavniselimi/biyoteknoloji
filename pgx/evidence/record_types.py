# -*- coding: utf-8 -*-
"""Mapping a source object class to a record type this project reads (WP-08).

Standard library plus :mod:`pgx.evidence.models`.

**The container is not the type.** ClinPGx's pair endpoint takes the result
type as a *path parameter*, and ``clinpgx_probe_v2.py`` sent a list of guessed
spellings (``PAIR_RESULT_TYPES``). The probe then stored each response under
the parameter it had sent. So a ``pair`` container name records what this
project's legacy script asked for, not what the source called the record.

The evidence for that reading is checkable and is recorded in
:data:`CONTAINER_FINDINGS`: the ``variantAnnotation`` container alone returns
three different object classes - ``Variant Phenotype Annotation`` (1,937),
``Variant Drug Annotation`` (1,285) and ``Variant Functional Assay
Annotation`` (126). A container-derived record type would be wrong for most of
them.

So the normalized record type is decided from the source's own ``objCls``, and
the container spelling is preserved beside it as the request that produced the
response.

**The ``label`` / ``DrugLabel`` question is left open, deliberately.** Three
facts point at a transport alias: the two containers' payloads are identical,
both declare ``objCls: "Label Annotation"``, and the source's own OpenAPI
document lists ``label`` in the ``resultType`` enum while not listing
``DrugLabel`` at all - so ``DrugLabel`` is an undocumented request spelling the
API happened to accept. That is strong, and it is not proof: the API's
behaviour on an undocumented enum value is undocumented by definition, and the
WP-07 handoff left these records for review rather than folding them.

They are therefore mapped to ``DRUG_LABEL_ANNOTATION`` with status
``PENDING_REVIEW``, which quarantines them from production evidence while
keeping both original container spellings and reporting the count. Nothing is
merged, and nothing is discarded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple

from pgx.evidence.models import (RECORD_TYPE_MAP_VERSION, EvidenceRecordType,
                                 RecordTypeMapping, RecordTypeMappingStatus)

__all__ = [
    "CONTAINER_FINDINGS",
    "OBJECT_CLASS_MAP",
    "UNRESOLVED_ALIAS_CONTAINERS",
    "ContainerFinding",
    "map_record_type",
    "normalize_container_family",
]


@dataclass(frozen=True, slots=True)
class ContainerFinding:
    """One checkable observation about how the pair containers behave.

    Recorded as data rather than prose so the reasoning behind a
    ``PENDING_REVIEW`` mapping can be cited, argued with, and re-verified
    against the snapshot.
    """

    finding_id: str
    statement: str
    supports: str
    evidence: str

    def to_json(self) -> Dict[str, str]:
        return {
            "finding_id": self.finding_id,
            "statement": self.statement,
            "supports": self.supports,
            "evidence": self.evidence,
        }


#: What was observed about the container names, and what each observation
#: does and does not establish.
CONTAINER_FINDINGS: Tuple[ContainerFinding, ...] = (
    ContainerFinding(
        "CONTAINER-IS-A-REQUEST-PARAMETER",
        "The pair container names are the resultType path parameter the "
        "legacy probe sent, not names the source chose for the records.",
        "reading the container as a request artifact rather than a source "
        "taxonomy",
        "clinpgx_probe_v2.py PAIR_RESULT_TYPES lists the spellings it tried, "
        "and openapi_snapshot.json documents resultType as a path parameter "
        "of /report/pair/{firstObjId}/{secondObjId}/{resultType}."),
    ContainerFinding(
        "CONTAINER-DOES-NOT-DETERMINE-TYPE",
        "One container returns several object classes.",
        "deciding the record type from objCls rather than from the container",
        "the variantAnnotation container returns Variant Phenotype "
        "Annotation, Variant Drug Annotation and Variant Functional Assay "
        "Annotation."),
    ContainerFinding(
        "CASE-VARIANTS-ARE-ONE-DOCUMENTED-VALUE",
        "variantAnnotation/VariantAnnotation and "
        "guidelineAnnotation/GuidelineAnnotation are case spellings of a "
        "single documented enum value.",
        "folding those pairs, as WP-07 already does",
        "openapi_snapshot.json lists 'variantAnnotation' and "
        "'guidelineAnnotation' in the resultType enum; the other spellings "
        "differ only in case."),
    ContainerFinding(
        "DRUGLABEL-IS-UNDOCUMENTED",
        "DrugLabel is not a case variant of label and is absent from the "
        "documented enum, yet returned identical payloads.",
        "recording an unresolved alias question rather than folding them",
        "the resultType enum documents 'label' and not 'DrugLabel'; the two "
        "containers' payloads compare equal and both declare "
        "objCls 'Label Annotation'."),
)

#: Containers whose relationship to another container is not settled. Records
#: arriving under one of these are mapped PENDING_REVIEW and quarantined.
UNRESOLVED_ALIAS_CONTAINERS: Tuple[str, ...] = ("label", "DrugLabel")

_ALIAS_RATIONALE = (
    "The 'label' and 'DrugLabel' containers return identical payloads and both "
    "declare objCls 'Label Annotation', and the source's OpenAPI document "
    "lists 'label' in the resultType enum while omitting 'DrugLabel'. That is "
    "strong evidence of an undocumented request alias and it is not proof, so "
    "the mapping stays PENDING_REVIEW, both container spellings are kept, and "
    "these records are quarantined from production evidence."
)

#: The source's object classes and the record type this project reads each as.
#: Keyed by the exact ``objCls`` string, because that is what the source wrote.
OBJECT_CLASS_MAP: Mapping[str, Tuple[EvidenceRecordType, str]] = {
    "Guideline Annotation": (
        EvidenceRecordType.GUIDELINE_ANNOTATION,
        "A guideline body's annotation, carrying its own 'source' field naming "
        "the asserting body."),
    "Variant Phenotype Annotation": (
        EvidenceRecordType.VARIANT_ANNOTATION,
        "A variant-to-phenotype association as the source stated it."),
    "Variant Drug Annotation": (
        EvidenceRecordType.VARIANT_ANNOTATION,
        "A variant-to-drug association as the source stated it."),
    "Variant Functional Assay Annotation": (
        EvidenceRecordType.VARIANT_ANNOTATION,
        "A functional assay observation as the source stated it."),
    "Label Annotation": (
        EvidenceRecordType.DRUG_LABEL_ANNOTATION,
        "An annotation of a regulator's drug label. The labelling authority is "
        "named only in free text, so the origin source is not stated."),
    "Literature": (
        EvidenceRecordType.PUBLICATION_REFERENCE,
        "A cited publication. Imported as a publication reference on the "
        "record that cites it, never as a standalone evidence record."),
}


def normalize_container_family(container: Optional[str]) -> Optional[str]:
    """Case-fold a container name into its family.

    Folds case only. ``label`` and ``DrugLabel`` do not fold together, which is
    the point: they are different names, and treating them as one would be a
    synonym claim this module does not make.
    """
    if container is None:
        return None
    return container.strip().casefold() or None


def map_record_type(object_class: Optional[str],
                    requested_container: Optional[str] = None
                    ) -> RecordTypeMapping:
    """Decide the record type from the source's object class.

    An unknown object class maps to ``UNKNOWN``/``UNMAPPED`` rather than to a
    guess. A record whose kind nobody has classified must not silently become
    an ``OTHER_SOURCE_RECORD`` that later reads as deliberate.
    """
    key = (object_class or "").strip()
    entry = OBJECT_CLASS_MAP.get(key)
    if entry is None:
        return RecordTypeMapping(
            source_object_class=object_class,
            requested_container=requested_container,
            record_type=EvidenceRecordType.UNKNOWN,
            status=RecordTypeMappingStatus.UNMAPPED,
            map_version=RECORD_TYPE_MAP_VERSION,
            rationale=("objCls %r is not in the WP-08 record-type map. It was "
                       "not interpreted; classify it before relying on it."
                       % (object_class,)))

    record_type, rationale = entry
    if requested_container in UNRESOLVED_ALIAS_CONTAINERS:
        return RecordTypeMapping(
            source_object_class=object_class,
            requested_container=requested_container,
            record_type=record_type,
            status=RecordTypeMappingStatus.PENDING_REVIEW,
            map_version=RECORD_TYPE_MAP_VERSION,
            rationale=_ALIAS_RATIONALE)

    return RecordTypeMapping(
        source_object_class=object_class,
        requested_container=requested_container,
        record_type=record_type,
        status=RecordTypeMappingStatus.CONFIRMED,
        map_version=RECORD_TYPE_MAP_VERSION,
        rationale=rationale)
