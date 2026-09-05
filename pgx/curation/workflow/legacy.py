# -*- coding: utf-8 -*-
"""Turning 1,559 legacy proposals into 1,559 questions nobody has answered.

WP-08 extracted the old project's interpretations out of the evidence store,
where they did not belong, into ``draft-curation-proposals.ndjson``. They are
not evidence and they are not conclusions: nobody reviewed them, and the fields
they carry are the ones the evidence store refuses by name.

This module gives each of them a place in the WP-10 workflow. Each proposal
becomes exactly one ``RAW`` work item - a question on the queue - carrying its
legacy values under ``legacy_values`` as **unreviewed input**, namespaced so
that no reader can mistake an old field for a curated one.

What deliberately does not happen here:

* No revision is created. A revision is a claim by a named curator, and no
  curator has looked at any of these.
* No work item reaches ``UNDER_REVIEW``. Nobody submitted anything.
* No reviewer, no approval, no ``CuratedInterpretation``. The whole point of
  WP-08 was that these values were never reviewed; importing them as
  conclusions would put back exactly what that work package removed.
* No P1 candidate data. ``mvp_candidate_drug_gene_edges`` was excluded from P0
  at canonicalisation and is excluded again here, by an explicit refusal rather
  than by not happening to look.

Identity is allocated explicitly and written down. A work item id is derived
from the proposal id by a pure function and recorded in an allocation file, so
re-running the migration produces byte-identical output and a work item keeps
its id across rebuilds. An id that changed between runs would break every audit
event that referenced it.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import uuid
from dataclasses import dataclass, field
from typing import (Any, Dict, Iterable, Iterator, List, Mapping, Optional,
                    Sequence, Set, Tuple)

from pgx.curation.workflow.errors import WorkflowError
from pgx.curation.workflow.models import (LEGACY_MIGRATION_TAG,
                                          CurationWorkItem)
from pgx.domain.enums import CurationStatus
from pgx.domain.hashing import sha256_digest

__all__ = [
    "LEGACY_ALLOCATION_VERSION",
    "LEGACY_MIGRATION_VERSION",
    "LEGACY_VALUE_NAMESPACE",
    "LEGACY_WORK_ITEM_PREFIX",
    "PROHIBITED_LEGACY_SOURCES",
    "LegacyMigrationReport",
    "allocate_work_item_id",
    "build_work_items",
    "namespace_legacy_values",
    "read_proposals",
]

LEGACY_MIGRATION_VERSION = "pgx-legacy-work-item-migration/1"
LEGACY_ALLOCATION_VERSION = "pgx-legacy-work-item-allocation/1"

#: Every legacy field is stored under this prefix. A reader who sees
#: ``legacy.demo_risk_level`` cannot mistake it for a curated field, and a
#: query for curated content cannot match one by accident.
LEGACY_VALUE_NAMESPACE = "legacy."

LEGACY_WORK_ITEM_PREFIX = "CWI-LEGACY-"

#: Artifacts whose contents must never become work items. Named rather than
#: merely absent: the migration refuses them if they appear, so a future change
#: that starts feeding them in fails loudly instead of quietly onboarding P1
#: candidate data into P0.
#:
#: Matched on the distinctive stem rather than on a full path. A path would be
#: defeated by the file moving; the stem would not. It also keeps this module
#: free of any legacy seed *directory* name, which matters because reading that
#: directory is something no post-WP-01 module does, and a refusal list is not
#: worth being the exception that has to be argued about.
PROHIBITED_LEGACY_SOURCES: Tuple[str, ...] = (
    "mvp_candidate_drug_gene_edges",
)

#: The status WP-08 gave every proposal. An input carrying anything else is not
#: what this migration was written for and is refused rather than coerced.
_EXPECTED_PROPOSAL_STATUS = "UNREVIEWED_LEGACY_MIGRATION_CANDIDATE"

#: Fields on the work item that a legacy value may never populate. Listed so
#: the refusal is by name: a legacy row must not be able to claim a reviewer,
#: a rationale or an approval by choosing a field name.
_REFUSED_LEGACY_KEYS: Tuple[str, ...] = (
    "reviewed_by", "reviewed_at", "approved_by", "approved_at", "rationale",
    "status", "curation_status", "version", "confidence", "recommendation",
)


def _canonical_keys(subject: str) -> Tuple[str, str]:
    """Split ``GENE::drug/ACCESSION`` into canonical keys.

    The canonical spellings are the ones WP-07 allocated (``GENE:CYP2C19``,
    ``DRUG:clopidogrel``). Deriving them here rather than looking them up keeps
    the migration a pure function of its input file; whether a key resolves to
    a canonical entity is checked by the linkage report, not silently fixed.
    """
    head = subject.split("/", 1)[0]
    if "::" not in head:
        raise WorkflowError(
            "legacy subject %r is not gene::drug; a work item needs both"
            % subject)
    gene, drug = head.split("::", 1)
    gene = gene.strip()
    drug = drug.strip()
    if not gene or not drug:
        raise WorkflowError("legacy subject %r has an empty side" % subject)
    return "GENE:%s" % gene, "DRUG:%s" % drug


def allocate_work_item_id(proposal_id: str) -> str:
    """A stable id, derived and then recorded.

    Derived from the proposal id by digest rather than by a counter: a counter
    would renumber everything if one proposal were added or removed, and every
    audit event pointing at the old numbers would silently point somewhere
    else. The allocation file records the result so that the derivation can
    change in future without existing ids moving.
    """
    if not str(proposal_id or "").strip():
        raise WorkflowError("a proposal needs an id to allocate against")
    digest = sha256_digest({"proposal_id": str(proposal_id).strip(),
                            "allocation_version": LEGACY_ALLOCATION_VERSION})
    return LEGACY_WORK_ITEM_PREFIX + digest.split(":", 1)[1][:16]


def _question_id(gene_key: str, drug_key: str, proposal_id: str) -> str:
    digest = sha256_digest({"gene": gene_key, "drug": drug_key,
                            "proposal_id": proposal_id})
    return "CQ-LEGACY-" + digest.split(":", 1)[1][:16]


def namespace_legacy_values(values: Mapping[str, Any]) -> Dict[str, Any]:
    """Prefix every legacy field and refuse the ones that would assert review.

    A legacy row is upstream text. Under ``legacy.`` it stays visibly upstream,
    and a row that tried to supply ``reviewed_by`` is refused rather than
    prefixed, because the problem there is not the field's name.
    """
    if not isinstance(values, Mapping):
        raise WorkflowError("legacy_values must be a mapping")
    namespaced: Dict[str, Any] = {}
    for key, value in values.items():
        plain = str(key).strip()
        if plain.lower() in _REFUSED_LEGACY_KEYS:
            raise WorkflowError(
                "legacy field %r would assert a review nobody performed; the "
                "migration refuses it rather than importing it under a prefix"
                % plain)
        namespaced[LEGACY_VALUE_NAMESPACE + plain] = value
    return namespaced


@dataclass(frozen=True)
class LegacyMigrationReport:
    """Counts and issues from one migration run.

    Counts are computed from what was built, never asserted. A report claiming
    1,559 while 1,558 work items exist would be the exact failure this file is
    supposed to make visible.
    """

    work_items: Tuple[CurationWorkItem, ...]
    evidence_links: Tuple[Mapping[str, Any], ...]
    issues: Tuple[Mapping[str, Any], ...]
    allocation: Tuple[Mapping[str, Any], ...]

    @property
    def total(self) -> int:
        return len(self.work_items)

    @property
    def linked(self) -> int:
        return len({link["work_item_id"] for link in self.evidence_links})

    @property
    def unlinked(self) -> int:
        return self.total - self.linked

    def counts(self) -> Dict[str, Any]:
        by_status: Dict[str, int] = {}
        for item in self.work_items:
            by_status[item.status.value] = by_status.get(item.status.value,
                                                         0) + 1
        return {
            "work_items": self.total,
            "linked_work_items": self.linked,
            "unlinked_work_items": self.unlinked,
            "evidence_links": len(self.evidence_links),
            "by_status": by_status,
            "under_review": by_status.get(CurationStatus.UNDER_REVIEW.value, 0),
            "curated": by_status.get(CurationStatus.CURATED.value, 0),
            "rejected": by_status.get(CurationStatus.REJECTED.value, 0),
            "revisions": 0,
            "reviewers": 0,
            "approvals": 0,
            "curated_interpretations": 0,
        }

    def assert_invariants(self) -> None:
        """Refuse to write an import that asserts a review.

        Checked on the built objects rather than on the input, because the
        thing that must be true is a property of what is about to be written.
        """
        counts = self.counts()
        for name in ("under_review", "curated", "rejected", "revisions",
                     "reviewers", "approvals", "curated_interpretations"):
            if counts[name]:
                raise WorkflowError(
                    "legacy migration produced %d %s; every imported work "
                    "item is RAW, unreviewed and unapproved"
                    % (counts[name], name))
        untagged = [item.work_item_id for item in self.work_items
                    if LEGACY_MIGRATION_TAG not in item.tags]
        if untagged:
            raise WorkflowError(
                "%d imported work items are not tagged %s; their origin would "
                "not be answerable by query"
                % (len(untagged), LEGACY_MIGRATION_TAG))
        ids = [item.work_item_id for item in self.work_items]
        if len(set(ids)) != len(ids):
            raise WorkflowError(
                "two work items were allocated the same id; an audit event "
                "would not identify which one it described")


def read_proposals(path: str) -> Iterator[Mapping[str, Any]]:
    """Read the WP-08 proposal file, one JSON object per line."""
    with open(path, "r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                yield json.loads(text)
            except ValueError as exc:
                raise WorkflowError(
                    "line %d of %s is not JSON: %s" % (number, path, exc))


def build_work_items(proposals: Iterable[Mapping[str, Any]],
                     *, imported_at: _dt.datetime,
                     imported_by: str) -> LegacyMigrationReport:
    """Build one RAW work item per proposal, plus links and issues.

    Deterministic: sorted by proposal id, timestamps supplied by the caller,
    ids derived. Two runs over the same file produce identical bytes.
    """
    ordered = sorted(proposals, key=lambda row: str(row.get("proposal_id")))
    items: List[CurationWorkItem] = []
    links: List[Mapping[str, Any]] = []
    issues: List[Mapping[str, Any]] = []
    allocation: List[Mapping[str, Any]] = []
    seen: Set[str] = set()

    for proposal in ordered:
        proposal_id = str(proposal.get("proposal_id") or "").strip()
        if not proposal_id:
            raise WorkflowError("a proposal has no proposal_id")
        if proposal_id in seen:
            raise WorkflowError("proposal %s appears twice" % proposal_id)
        seen.add(proposal_id)

        status = str(proposal.get("status") or "")
        if status != _EXPECTED_PROPOSAL_STATUS:
            raise WorkflowError(
                "proposal %s has status %r; this migration imports only %r, "
                "and coercing anything else would import a claim it did not "
                "make" % (proposal_id, status, _EXPECTED_PROPOSAL_STATUS))

        for origin in proposal.get("origins") or ():
            relative = str((origin or {}).get("relative_path") or "")
            for forbidden in PROHIBITED_LEGACY_SOURCES:
                if forbidden in relative:
                    raise WorkflowError(
                        "proposal %s originates in %s, which is P1 candidate "
                        "data excluded from P0; it must not become a work item"
                        % (proposal_id, relative))

        gene_key, drug_key = _canonical_keys(str(proposal.get("subject") or ""))
        work_item_id = allocate_work_item_id(proposal_id)
        record_uuids = tuple(str(value) for value
                             in (proposal.get("linked_record_uuids") or ()))

        item = CurationWorkItem(
            work_item_id=work_item_id,
            status=CurationStatus.RAW,
            version=0,
            question_id=_question_id(gene_key, drug_key, proposal_id),
            gene_canonical_key=gene_key,
            drug_canonical_key=drug_key,
            created_at=imported_at,
            created_by=imported_by,
            current_revision_id=None,
            submitted_revision_id=None,
            tags=(LEGACY_MIGRATION_TAG,),
            legacy_proposal_id=proposal_id,
            legacy_values=namespace_legacy_values(
                proposal.get("legacy_values") or {}),
        )
        items.append(item)
        allocation.append({
            "proposal_id": proposal_id,
            "work_item_id": work_item_id,
            "question_id": item.question_id,
            "gene_canonical_key": gene_key,
            "drug_canonical_key": drug_key,
            "proposal_content_hash": proposal.get("content_hash"),
        })

        if record_uuids:
            for record_uuid in sorted(set(record_uuids)):
                links.append({
                    "work_item_id": work_item_id,
                    "proposal_id": proposal_id,
                    "evidence_record_uuid": record_uuid,
                    "link_basis": str(proposal.get("linkage_note") or ""),
                    "reviewed": False,
                    "note": ("A link inherited from the legacy extraction. It "
                             "records which evidence the old interpretation "
                             "was about; no curator has confirmed that this "
                             "evidence supports anything."),
                })
        else:
            issues.append({
                "work_item_id": work_item_id,
                "proposal_id": proposal_id,
                "issue": "UNLINKED_LEGACY_PROPOSAL",
                "detail": str(proposal.get("linkage_note") or
                              "no evidence record was linked"),
                "resolution": ("The work item exists and is RAW. A curator "
                               "selects evidence when they write a revision; "
                               "guessing a link here would manufacture a "
                               "citation the source never made."),
            })

    report = LegacyMigrationReport(
        work_items=tuple(items), evidence_links=tuple(links),
        issues=tuple(issues), allocation=tuple(allocation))
    report.assert_invariants()
    return report
