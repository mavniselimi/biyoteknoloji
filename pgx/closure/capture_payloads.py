# -*- coding: utf-8 -*-
"""The Wave 3 source grounding, shaped for the core capture snapshot (WP-C05).

This module is a **projection**, not a second source of truth. Every value it
emits is read from :mod:`pgx.closure.source_grounding` and
:mod:`pgx.closure.source_rows`, which Wave 3 sealed and which this wave does
not touch. If the two ever disagree, the projection is wrong.

What it does not do is as important. It does not invent an external accession
for a gene or a drug: a CPIC recommendation table names ``CYP2C19`` and
``clopidogrel`` and publishes no identifier for either, so the capture proposes
entities with no cross-reference rather than borrowing a ClinPGx ``PA`` number
from a page it did not read. It does not drop the rows this project cannot
represent. And it does not reuse the ``resolved_genes.json`` /
``pair_probe_raw.json`` names, which mean "this is what the ClinPGx endpoint
returned" and would make a misdescription invisible at every later read.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Tuple

from pgx.closure.source_grounding import (RETRIEVAL_CLASSIFICATION,
                                          RETRIEVAL_LIMITS, RETRIEVALS)
from pgx.closure.source_rows import ROWS

__all__ = [
    "CAPTURE_LIMITATIONS",
    "CAPTURE_PAYLOAD_VERSION",
    "CAPTURE_SOURCE_KEY",
    "build_capture_files",
    "build_capture_reads",
]

CAPTURE_PAYLOAD_VERSION = "pgx-wave03b-capture-payload/1"

#: The source key the snapshot is filed under. Names the publisher and the
#: interface, not the project, so the raw root stays readable by source.
CAPTURE_SOURCE_KEY = "cpic-guideline-capture"

CAPTURE_LIMITATIONS: Tuple[str, ...] = RETRIEVAL_LIMITS + (
    "this snapshot is a TRANSCRIPTION_CAPTURE: it is not backed by a WP-04 "
    "acquisition run, and its artifacts are this project's transcription "
    "rather than the publisher's response bodies",
    "the capture proposes genes and drugs with no external accession, because "
    "the captured pages publish none for them",
    "completeness relative to the upstream source is unknown: the four "
    "guideline annotations named in the retrieval log were read, and nothing "
    "was crawled to discover whether others exist",
)


def _canonical(payload: Any) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
            + "\n").encode("utf-8")


def build_capture_reads() -> Tuple[Mapping[str, Any], ...]:
    """One record per document read, in a shape the request log accepts."""
    reads: List[Dict[str, Any]] = []
    for index, item in enumerate(sorted(RETRIEVALS,
                                        key=lambda r: r.retrieval_key), 1):
        reads.append({
            "acquisition_mode": "AGENT_TARGETED_RETRIEVAL",
            "annotation_id": item.annotation_id,
            "artifact_path": "responses/capture_recommendation_rows.json",
            "citation": "PMID %s, DOI %s" % (item.pmid, item.doi),
            "guideline_id": item.guideline_id,
            "guideline_version_label": item.guideline_version_label,
            "observed_not_later_than": item.observed_not_later_than,
            "organization": "Clinical Pharmacogenetics Implementation "
                            "Consortium, published via ClinPGx",
            "page_number": index,
            "request_key": item.retrieval_key,
            "response_body_preserved": False,
            "retrieval_classification": RETRIEVAL_CLASSIFICATION,
            "retrieved_on": item.retrieved_on,
            "url": item.annotation_url,
        })
    return tuple(reads)


def build_capture_files() -> Dict[str, bytes]:
    """The four capture artifacts, byte-exact and deterministic."""
    retrievals = {item.retrieval_key: item for item in RETRIEVALS}

    genes: Dict[str, Any] = {}
    chemicals: Dict[str, Any] = {}
    axes: Dict[str, Any] = {}
    rows: List[Dict[str, Any]] = []

    for row in ROWS:
        retrieval = retrievals[row.retrieval_key]
        genes.setdefault(row.gene, {
            "symbol": row.gene,
            "observed_in": [],
        })["observed_in"].append(retrieval.annotation_id)
        chemicals.setdefault(row.drug, {
            "name": row.drug,
            "observed_in": [],
        })["observed_in"].append(retrieval.annotation_id)

        axis_key = "%s::%s" % (row.gene, row.drug)
        axis = axes.setdefault(axis_key, {
            # A record identity this project issues for its own transcription.
            # Deterministic, and namespaced "capture:" so nothing can read it
            # as the publisher's accession - which is why a ClinPGx PA number
            # is not reused here even though one exists for the annotation:
            # that number identifies the page, not this row of this table as
            # this project transcribed it.
            "id": "capture:axis:%s" % axis_key,
            "annotation_id": retrieval.annotation_id,
            "annotation_url": retrieval.annotation_url,
            "drug": row.drug,
            "gene": row.gene,
            "guideline_id": retrieval.guideline_id,
            "guideline_version_label": retrieval.guideline_version_label,
            "row_count": 0,
            "unrepresentable_row_count": 0,
        })
        axis["row_count"] += 1
        if not row.is_representable:
            axis["unrepresentable_row_count"] += 1

        payload = row.to_json()
        payload["id"] = "capture:row:%s|%s|%s|%s" % (
            row.gene, row.drug, row.source_phenotype, row.context)
        payload["annotation_id"] = retrieval.annotation_id
        payload["annotation_url"] = retrieval.annotation_url
        payload["doi"] = retrieval.doi
        payload["guideline_version_label"] = retrieval.guideline_version_label
        payload["pmid"] = retrieval.pmid
        rows.append(payload)

    for table in (genes, chemicals):
        for record in table.values():
            record["observed_in"] = sorted(set(record["observed_in"]))

    rows.sort(key=lambda item: (item["drug"], item["gene"],
                                item["source_phenotype"], item["context"]))

    return {
        "capture_axes.json": _canonical(axes),
        "capture_chemicals.json": _canonical(chemicals),
        "capture_genes.json": _canonical(genes),
        "capture_recommendation_rows.json": _canonical(rows),
    }
