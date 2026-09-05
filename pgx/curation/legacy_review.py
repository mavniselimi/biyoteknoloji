# -*- coding: utf-8 -*-
"""The legacy manual-hint review queue (WP-09).

WP-08 recovered 1,559 conclusions this project had reached before any review
protocol existed. They are a **queue of historical project interpretations**,
not scientific truth, and this module builds the inventory that keeps them
accounted for while nobody has reviewed them.

Three properties matter.

**Every proposal is accounted for.** Not a sample. A proposal that dropped out
of the inventory would be a conclusion this project once made and can no longer
find, which is how an unreviewed claim survives by being forgotten.

**Nothing here reviews anything.** The only state this module may assign is
``NOT_REVIEWED``, plus ``SELECTED_FOR_EXERCISE`` for the cases a human is asked
to look at. Every other state names a decision, and a decision needs a person.

**The legacy conclusion never becomes the answer.** ``demo_risk_level``,
``risk_meaning``, ``plain_language_mvp`` and the effect hints are carried as
what they are - a previous project's values, kept for later comparison - and
are blinded from the curator during initial review.
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from pgx.curation.errors import CurationError
from pgx.curation.vocabulary import LegacyReviewState
from pgx.domain.hashing import sha256_digest

__all__ = [
    "LEGACY_REVIEW_INVENTORY_VERSION",
    "LEGACY_PROJECT_VALUE_FIELDS",
    "LegacyProposalEntry",
    "LegacyReviewInventory",
    "build_review_inventory",
    "read_proposals",
]

LEGACY_REVIEW_INVENTORY_VERSION = "pgx-curation-legacy-review/1"

#: The legacy project's own conclusion fields. Listed so the inventory can
#: report which conclusions are waiting on review, and so a test can assert
#: none of them reaches a completed curation record.
LEGACY_PROJECT_VALUE_FIELDS: Tuple[str, ...] = (
    "demo_risk_level", "drug_behavior_hint", "effect_direction",
    "evidence_strength", "evidence_tier", "manual_drug_behavior",
    "manual_effect_direction", "manual_phenotypes", "manual_plain_language",
    "manual_risk_level", "manual_risk_meaning", "normalized_phenotype_group",
    "plain_language_mvp", "risk_meaning", "usable_for_mvp",
)


@dataclass(frozen=True)
class LegacyProposalEntry:
    """One historical project interpretation, awaiting a human.

    ``legacy_values`` is retained rather than summarised: the point of the
    review is for a scientist to see exactly what the project previously
    claimed, and a summary would decide in advance which parts mattered.
    """

    proposal_id: str
    subject: str
    review_state: LegacyReviewState
    linked_evidence: Tuple[str, ...]
    linked_record_uuids: Tuple[str, ...]
    legacy_values: Mapping[str, Any]
    warnings: Tuple[str, ...]
    origins: Tuple[Mapping[str, Any], ...]
    linkage_note: Optional[str] = None
    reviewed_by: Optional[str] = None
    review_note: Optional[str] = None

    def __post_init__(self) -> None:
        if not str(self.proposal_id).strip():
            raise CurationError("proposal_id is required")
        if not isinstance(self.review_state, LegacyReviewState):
            raise CurationError("review_state must be a LegacyReviewState")
        object.__setattr__(self, "linked_evidence", tuple(self.linked_evidence))
        object.__setattr__(self, "linked_record_uuids",
                           tuple(self.linked_record_uuids))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "origins", tuple(self.origins))
        object.__setattr__(self, "legacy_values",
                           dict(sorted((self.legacy_values or {}).items())))

        # The states that name a decision require the person who made it. This
        # module never supplies one, so in practice it can only ever build
        # NOT_REVIEWED and SELECTED_FOR_EXERCISE entries - which is the point.
        decided = (LegacyReviewState.ACCEPTED_AS_DRAFT_INPUT,
                   LegacyReviewState.REJECTED_AS_DRAFT_INPUT,
                   LegacyReviewState.NEEDS_MORE_EVIDENCE)
        if self.review_state in decided and not (self.reviewed_by or "").strip():
            raise CurationError(
                "%s requires the name of the person who decided it; a legacy "
                "conclusion cannot be accepted or rejected by a program"
                % self.review_state.value)

    @property
    def is_linked(self) -> bool:
        return bool(self.linked_evidence)

    @property
    def is_reviewed(self) -> bool:
        return self.review_state is not LegacyReviewState.NOT_REVIEWED

    def content_identity(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "subject": self.subject,
            "review_state": self.review_state.value,
            "linked_evidence": list(self.linked_evidence),
            "linked_record_uuids": list(self.linked_record_uuids),
            "legacy_values": dict(self.legacy_values),
            "warnings": list(self.warnings),
            "origins": [dict(sorted(item.items())) for item in self.origins],
            "linkage_note": self.linkage_note,
            "reviewed_by": self.reviewed_by,
            "review_note": self.review_note,
        }

    def to_json(self) -> Dict[str, Any]:
        return self.content_identity()


@dataclass(frozen=True)
class LegacyReviewInventory:
    """Every legacy proposal, with what is known and what is not.

    ``content_hash`` covers the entries only, so regenerating the inventory
    from the same proposals produces the same hash and a difference means the
    proposals changed.
    """

    entries: Tuple[LegacyProposalEntry, ...]
    source_path: str
    source_sha256: str
    inventory_version: str = LEGACY_REVIEW_INVENTORY_VERSION

    def __post_init__(self) -> None:
        ids = [item.proposal_id for item in self.entries]
        if len(set(ids)) != len(ids):
            raise CurationError("a proposal id appears twice in the inventory")

    def counts(self) -> Dict[str, Any]:
        by_state: Dict[str, int] = {}
        by_field: Dict[str, int] = {}
        for entry in self.entries:
            key = entry.review_state.value
            by_state[key] = by_state.get(key, 0) + 1
            for name in entry.legacy_values:
                by_field[name] = by_field.get(name, 0) + 1
        return {
            "proposal_count": len(self.entries),
            "linked_count": sum(1 for item in self.entries if item.is_linked),
            "unlinked_count": sum(1 for item in self.entries
                                  if not item.is_linked),
            "reviewed_count": sum(1 for item in self.entries
                                  if item.is_reviewed),
            "by_review_state": dict(sorted(by_state.items())),
            "legacy_value_fields": dict(sorted(by_field.items())),
        }

    def content_identity(self) -> Dict[str, Any]:
        return {
            "inventory_version": self.inventory_version,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "entries": [item.content_identity() for item in self.entries],
        }

    def content_hash(self) -> str:
        return sha256_digest(self.content_identity())

    def to_json(self) -> Dict[str, Any]:
        payload = self.content_identity()
        payload["counts"] = self.counts()
        payload["content_hash"] = self.content_hash()
        payload["note"] = (
            "A queue of historical project interpretations, not scientific "
            "truth. Every entry is NOT_REVIEWED unless a named human moved "
            "it, and no legacy value here may enter a completed curation "
            "conclusion.")
        return payload


def read_proposals(path: str) -> Tuple[List[Mapping[str, Any]], str]:
    """Read the WP-08 proposal file, returning rows and the file digest.

    The digest is recorded in the inventory so a later reader can tell whether
    the queue was built from the file they are looking at.
    """
    if not os.path.isfile(path):
        raise CurationError("no draft-curation proposals at %s" % path)
    with io.open(path, "rb") as handle:
        data = handle.read()
    import hashlib
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    rows = [json.loads(line) for line in data.decode("utf-8").splitlines()
            if line.strip()]
    return rows, digest


def build_review_inventory(
    proposals_path: str,
    selected_proposal_ids: Sequence[str] = (),
) -> LegacyReviewInventory:
    """Build the review queue from the WP-08 proposals.

    Every proposal in the file becomes an entry, in the file's own order. None
    is filtered out - a proposal that is unlinked, or whose legacy values look
    unusable, is exactly the kind a reviewer needs to see.

    ``selected_proposal_ids`` marks the ones a human is being asked to look at
    as ``SELECTED_FOR_EXERCISE``. That is a scheduling statement, not a review
    outcome, which is why it is the one other state this function may assign.
    """
    rows, digest = read_proposals(proposals_path)
    selected = frozenset(selected_proposal_ids)
    entries = []
    for row in rows:
        proposal_id = str(row.get("proposal_id"))
        state = (LegacyReviewState.SELECTED_FOR_EXERCISE
                 if proposal_id in selected else LegacyReviewState.NOT_REVIEWED)
        entries.append(LegacyProposalEntry(
            proposal_id=proposal_id,
            subject=str(row.get("subject") or ""),
            review_state=state,
            linked_evidence=tuple(row.get("linked_evidence") or ()),
            linked_record_uuids=tuple(row.get("linked_record_uuids") or ()),
            legacy_values=row.get("legacy_values") or {},
            warnings=tuple(row.get("warnings") or ()),
            origins=tuple(row.get("origins") or ()),
            linkage_note=row.get("linkage_note")))

    unknown = selected - {item.proposal_id for item in entries}
    if unknown:
        raise CurationError(
            "selected proposal id(s) not present in %s: %s"
            % (proposals_path, ", ".join(sorted(unknown))))

    return LegacyReviewInventory(
        entries=tuple(entries),
        source_path=os.path.relpath(proposals_path, os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ).replace(os.sep, "/"),
        source_sha256=digest)
