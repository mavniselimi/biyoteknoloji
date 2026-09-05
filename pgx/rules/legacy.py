# -*- coding: utf-8 -*-
"""The legacy rule-candidate inventory (WP-11).

An inventory, and only an inventory. Nothing in this module creates a rule,
grants eligibility, or copies a legacy value into an outcome.

**Why the legacy rows cannot be promoted.** ``phenotype_effect_rules.csv``
mixes three things in one row: what a source said, how the old project
normalised it, and what risk the old project decided that meant. Its
``demo_risk_level`` and ``risk_meaning`` columns are the third kind - an
unreviewed interpretation, written by nobody in particular, against no
protocol. WP-08 removed exactly those columns from the evidence store because
they were interpretation sitting where evidence belonged; WP-10 re-imported
them as namespaced ``legacy.*`` input on RAW work items, visibly unreviewed.

Copying ``demo_risk_level: high`` into an ``AttentionLevel`` would launder that
opinion into a governed clinical output in one assignment. So this module reads
those values, records them verbatim as *raw text*, and marks every candidate
ineligible with the specific codes saying why.

**Where the data comes from.** The WP-10 work items and the WP-08 proposals,
not the seed CSV. Those artifacts already carry the source file and row number
for every legacy row, so the provenance this inventory needs is present without
this module reading the legacy seed directory at all - which keeps the
dependency boundary that no post-WP-01 module reads that directory intact.
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass
from typing import (Any, Dict, Iterable, Iterator, List, Mapping, Optional,
                    Sequence, Tuple)

from pgx.domain.hashing import sha256_digest

__all__ = [
    "INVENTORY_VERSION",
    "LEGACY_BLOCKER_CODES",
    "LegacyRuleCandidate",
    "LegacyRuleInventory",
    "build_inventory",
]

INVENTORY_VERSION = "pgx-legacy-rule-candidate-inventory/1"

#: Why each candidate is ineligible. Every one of these is about a decision
#: people have not made, which is why none of them can be cleared by code.
LEGACY_BLOCKER_CODES: Mapping[str, str] = {
    "CURATION_NOT_CURATED":
        "the work item is still RAW; no curator has reached a conclusion",
    "NO_APPROVED_REVISION":
        "no immutable curation revision has been approved, so a rule would "
        "have nothing exact to descend from",
    "NO_APPROVAL_ENVELOPE":
        "no WP-10 rule approval envelope names this candidate",
    "NO_EVIDENCE_LINK":
        "the legacy row could not be linked to an evidence record, so a rule "
        "built from it could cite nothing (SAFETY-INV-006)",
    "EVIDENCE_BUILD_QUARANTINED":
        "the evidence build is quarantined and not a permitted rule source",
    "PROTOCOL_NOT_APPROVED":
        "the curation protocol awaits expert review, so there is no approved "
        "standard to curate against",
    "DATASET_NOT_PUBLISHED":
        "the canonical dataset is still BUILDING",
    "LEGACY_SEVERITY_IS_NOT_AN_OUTCOME":
        "the legacy risk and severity fields are the old project's unreviewed "
        "interpretation; they are recorded here as raw text and are never "
        "copied into a rule outcome",
}


@dataclass(frozen=True, slots=True)
class LegacyRuleCandidate:
    """One legacy rule-like row, described and refused."""

    candidate_id: str
    work_item_id: str
    legacy_proposal_id: str
    source_file: str
    source_rows: Tuple[int, ...]
    gene_canonical_key: str
    drug_canonical_key: str
    linked: bool
    evidence_record_uuids: Tuple[str, ...]
    raw_phenotype_text: str
    raw_effect_text: str
    raw_severity_text: str
    raw_significance_text: str
    curation_status: str
    has_approved_revision: bool
    has_approval_envelope: bool
    blocker_codes: Tuple[str, ...]

    def to_json(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "work_item_id": self.work_item_id,
            "legacy_proposal_id": self.legacy_proposal_id,
            "source_file": self.source_file,
            "source_rows": list(self.source_rows),
            "gene_canonical_key": self.gene_canonical_key,
            "drug_canonical_key": self.drug_canonical_key,
            "linked": self.linked,
            "evidence_record_uuids": list(self.evidence_record_uuids),
            "raw_phenotype_text": self.raw_phenotype_text,
            "raw_effect_text": self.raw_effect_text,
            "raw_severity_text": self.raw_severity_text,
            "raw_significance_text": self.raw_significance_text,
            "curation_status": self.curation_status,
            "has_approved_revision": self.has_approved_revision,
            "has_approval_envelope": self.has_approval_envelope,
            "eligible_for_rule_creation": False,
            "blocker_codes": list(self.blocker_codes),
        }

    def sort_key(self) -> Tuple[str, ...]:
        return (self.gene_canonical_key, self.drug_canonical_key,
                self.candidate_id)


@dataclass(frozen=True)
class LegacyRuleInventory:
    """Every candidate, with counts computed from what was built."""

    candidates: Tuple[LegacyRuleCandidate, ...]
    upstream: Mapping[str, Any]

    def counts(self) -> Dict[str, Any]:
        by_status: Dict[str, int] = {}
        by_blocker: Dict[str, int] = {}
        for candidate in self.candidates:
            by_status[candidate.curation_status] = \
                by_status.get(candidate.curation_status, 0) + 1
            for code in candidate.blocker_codes:
                by_blocker[code] = by_blocker.get(code, 0) + 1
        return {
            "candidates": len(self.candidates),
            "linked": sum(1 for item in self.candidates if item.linked),
            "unlinked": sum(1 for item in self.candidates if not item.linked),
            "eligible_for_rule_creation": 0,
            "rules_created": 0,
            "validated_rules": 0,
            "frozen_rulesets": 0,
            "by_curation_status": dict(sorted(by_status.items())),
            "by_blocker_code": dict(sorted(by_blocker.items())),
        }

    def to_json(self) -> Dict[str, Any]:
        payload = {
            "inventory_version": INVENTORY_VERSION,
            "counts": self.counts(),
            "upstream_state": dict(self.upstream),
            "blocker_code_meanings": dict(LEGACY_BLOCKER_CODES),
            "candidates": [candidate.to_json() for candidate in self.candidates],
            "promotion_policy": (
                "This file is an inventory. It creates no rule, grants no "
                "eligibility, and copies no legacy severity or risk value into "
                "a rule outcome. Those values appear here as raw text under "
                "raw_* fields precisely so that reading them is obviously "
                "reading the old project's unreviewed opinion, not this "
                "project's finding."),
            "note": (
                "Every candidate is ineligible. The blockers are decisions "
                "people have not made yet, and none of them can be cleared by "
                "code."),
        }
        payload["content_hash"] = sha256_digest(payload)
        return payload

    def assert_no_promotion(self) -> None:
        """Refuse to write an inventory that granted eligibility.

        Checked against the built objects rather than the inputs, because what
        must be true is a property of what is about to be written.
        """
        counts = self.counts()
        for name in ("eligible_for_rule_creation", "rules_created",
                     "validated_rules", "frozen_rulesets"):
            if counts[name]:
                raise ValueError(
                    "inventory reports %d %s; no legacy candidate is eligible "
                    "and none may be promoted" % (counts[name], name))
        for candidate in self.candidates:
            if not candidate.blocker_codes:
                raise ValueError(
                    "candidate %s carries no blocker; an inventory entry with "
                    "nothing blocking it would read as eligible"
                    % candidate.candidate_id)


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.isfile(path):
        return None
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _read_ndjson(path: str) -> Iterator[Dict[str, Any]]:
    if not os.path.isfile(path):
        return
    with io.open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def build_inventory(repo_root: str = ".") -> LegacyRuleInventory:
    """Build the inventory from the WP-08 and WP-10 migration artifacts.

    Deterministic: candidates are sorted by gene, drug and identity, and every
    value is copied verbatim from an artifact rather than recomputed.
    """
    def path(*parts: str) -> str:
        return os.path.join(repo_root, *parts)

    proposals = {row["proposal_id"]: row for row in _read_ndjson(
        path("data", "migration", "wp08", "draft-curation-proposals.ndjson"))}
    work_items = list(_read_ndjson(
        path("data", "migration", "wp10", "legacy-work-items.ndjson")))
    links: Dict[str, List[str]] = {}
    for row in _read_ndjson(path("data", "migration", "wp10",
                                 "legacy-work-item-evidence-links.ndjson")):
        links.setdefault(row["work_item_id"], []).append(
            row["evidence_record_uuid"])

    protocol = _read_json(path("config", "curation", "protocol-v1.json")) or {}
    canonical = _read_json(path("data", "canonical", "PGX-DATA-20260830-900",
                                "manifest.json")) or {}
    evidence = _read_json(path("data", "evidence", "PGX-DATA-20260830-900",
                               "manifest.json")) or {}

    protocol_approved = str(protocol.get("status")) == "APPROVED"
    dataset_published = str(canonical.get("dataset_lifecycle_state")) == "PUBLISHED"
    evidence_labels = tuple(evidence.get("lifecycle_labels") or ())
    evidence_quarantined = "QUARANTINED" in evidence_labels

    candidates: List[LegacyRuleCandidate] = []
    for item in work_items:
        proposal_id = item.get("legacy_proposal_id") or ""
        proposal = proposals.get(proposal_id, {})
        origins = proposal.get("origins") or []
        source_file = str((origins[0] or {}).get("relative_path") or "") \
            if origins else ""
        rows = tuple(sorted(int(origin["row_number"]) for origin in origins
                            if origin.get("row_number") is not None))
        legacy = item.get("legacy_values") or {}
        evidence_uuids = tuple(sorted(links.get(item["work_item_id"], ())))
        linked = bool(evidence_uuids)

        blockers: List[str] = []
        status = str(item.get("status") or "UNKNOWN")
        if status != "CURATED":
            blockers.append("CURATION_NOT_CURATED")
        if not item.get("submitted_revision_id"):
            blockers.append("NO_APPROVED_REVISION")
        blockers.append("NO_APPROVAL_ENVELOPE")
        if not linked:
            blockers.append("NO_EVIDENCE_LINK")
        if evidence_quarantined:
            blockers.append("EVIDENCE_BUILD_QUARANTINED")
        if not protocol_approved:
            blockers.append("PROTOCOL_NOT_APPROVED")
        if not dataset_published:
            blockers.append("DATASET_NOT_PUBLISHED")
        if legacy.get("legacy.demo_risk_level") or legacy.get("legacy.risk_meaning"):
            blockers.append("LEGACY_SEVERITY_IS_NOT_AN_OUTCOME")

        candidates.append(LegacyRuleCandidate(
            candidate_id="LRC-" + item["work_item_id"],
            work_item_id=str(item["work_item_id"]),
            legacy_proposal_id=str(proposal_id),
            source_file=source_file,
            source_rows=rows,
            gene_canonical_key=str(item.get("gene_canonical_key") or ""),
            drug_canonical_key=str(item.get("drug_canonical_key") or ""),
            linked=linked,
            evidence_record_uuids=evidence_uuids,
            raw_phenotype_text=str(
                legacy.get("legacy.normalized_phenotype_group") or ""),
            raw_effect_text=str(legacy.get("legacy.effect_direction") or ""),
            raw_severity_text=str(legacy.get("legacy.demo_risk_level") or ""),
            raw_significance_text=str(legacy.get("legacy.risk_meaning") or ""),
            curation_status=status,
            has_approved_revision=bool(item.get("submitted_revision_id")),
            has_approval_envelope=False,
            blocker_codes=tuple(sorted(set(blockers)))))

    inventory = LegacyRuleInventory(
        candidates=tuple(sorted(candidates, key=lambda item: item.sort_key())),
        upstream={
            "curation_protocol_status": str(protocol.get("status") or "UNKNOWN"),
            "curation_protocol_approved": protocol_approved,
            "canonical_dataset_state": str(
                canonical.get("dataset_lifecycle_state") or "UNKNOWN"),
            "evidence_build_labels": list(evidence_labels),
            "wp08_proposals": len(proposals),
            "wp10_work_items": len(work_items),
        })
    inventory.assert_no_promotion()
    return inventory
