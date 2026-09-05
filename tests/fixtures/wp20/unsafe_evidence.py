# -*- coding: utf-8 -*-
"""SAFETY-INV-006 negative controls: findings with a broken evidence chain.

``LEGACY-BUG-005``: legacy attached evidence strength to the mere existence of
a drug-gene pair rather than to a specific interpretation. Without a resolvable
citation an "explainable" output is an assertion with a footnote shape.

The correct behaviour on a missing reference is to drop the finding and degrade
coverage with ``EVIDENCE_REFERENCE_MISSING`` - never to emit it anyway.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence

PINNED_DATASET = "PGX-DATA-TEST-001"
OTHER_DATASET = "PGX-DATA-TEST-002"


def evidence_index() -> Mapping[str, Any]:
    """Two resolvable records, one of them in the wrong dataset version."""
    return {
        "EV-1": {"evidence_id": "EV-1", "dataset_id": PINNED_DATASET},
        "EV-2": {"evidence_id": "EV-2", "dataset_id": PINNED_DATASET},
        "EV-STALE": {"evidence_id": "EV-STALE", "dataset_id": OTHER_DATASET},
    }


def candidate_findings() -> Sequence[Dict[str, Any]]:
    """Four candidates: one good, three that must not survive."""
    return (
        {"finding_id": "F-OK", "evidence_refs": ["EV-1", "EV-2"]},
        {"finding_id": "F-DANGLING", "evidence_refs": ["EV-MISSING"]},
        {"finding_id": "F-EMPTY", "evidence_refs": []},
        {"finding_id": "F-STALE-DATASET", "evidence_refs": ["EV-STALE"]},
    )


def safe_emitter(findings, index):
    """The safe control: emit only what resolves inside the pinned dataset."""
    kept = []
    for finding in findings:
        refs = list(finding.get("evidence_refs", ()))
        if not refs:
            continue
        if all((index.get(ref) or {}).get("dataset_id") == PINNED_DATASET
               for ref in refs):
            kept.append(finding)
    return kept


def emits_dangling_reference(findings, index):
    """NC-INV-006-DANGLING-EVIDENCE-REFERENCE - the reference is not checked.

    The finding carries an evidence ID, so a check that only asked "is the list
    non-empty" is satisfied. Nobody asked whether the ID resolves.
    """
    return [f for f in findings if f.get("evidence_refs")]


def emits_finding_without_evidence(findings, index):
    """NC-INV-006-FINDING-WITHOUT-EVIDENCE - the check is skipped entirely."""
    return list(findings)


def emits_evidence_from_another_dataset(findings, index):
    """NC-INV-006-EVIDENCE-OUTSIDE-PINNED-DATASET - resolvable, wrong version.

    The hardest of the three to notice: every reference resolves. They resolve
    into a dataset this release did not pin, so the citation supports a claim
    about different data.
    """
    return [f for f in findings
            if f.get("evidence_refs")
            and all(index.get(ref) is not None
                    for ref in f["evidence_refs"])]


UNSAFE_SUBJECTS = {
    "NC-INV-006-DANGLING-EVIDENCE-REFERENCE": emits_dangling_reference,
    "NC-INV-006-FINDING-WITHOUT-EVIDENCE": emits_finding_without_evidence,
    "NC-INV-006-EVIDENCE-OUTSIDE-PINNED-DATASET":
        emits_evidence_from_another_dataset,
}

SAFE_SUBJECT = safe_emitter
