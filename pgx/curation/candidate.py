# -*- coding: utf-8 -*-
"""Provisional interpretations on the candidate track (WP-C07, core).

A distinct type from :class:`pgx.domain.models.CuratedInterpretation` and from
:class:`pgx.curation.models.CurationRecordDraft`, and the reason is a field in
each of them rather than a preference.

``CuratedInterpretation`` reaches ``CurationStatus.CURATED`` only with a
``reviewed_by`` and a ``reviewed_at``: a second person. ``CurationRecordDraft``
carries a ``Rationale`` whose ``authored_by`` is a ``ReviewSignature``, and
``ReviewSignature.PLACEHOLDER_NAMES`` refuses "ai", "llm", "claude" and "gpt"
by name. Both refusals exist precisely to stop an automated pass being recorded
as a human curator, and both are correct. Slipping past either one - by
recording a process in a person's field, or by leaving a record permanently at
``RAW`` so the check never fires - would be defeating a guard rather than
respecting it.

So the candidate track gets its own record, in the core curation package where
the services can see it, carrying the authority state on its face. It is
convertible into a governed record later by a human doing the review; it is not
convertible by anything here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from pgx.domain.authority import CandidateAuthorityState
from pgx.domain.enums import Phenotype
from pgx.domain.hashing import sha256_digest

__all__ = [
    "CANDIDATE_INTERPRETATION_VERSION",
    "CandidateInterpretation",
]

CANDIDATE_INTERPRETATION_VERSION = "pgx-candidate-interpretation/1"


@dataclass(frozen=True, slots=True)
class CandidateInterpretation:
    """One provisional interpretation of one source row.

    Deliberately carries **no attention level**. Turning a recommendation into
    an attention level is a rule-construction act, and this package's own
    boundary test refuses a curation module that computes one - correctly: a
    curation record states what the source says and what the curator concluded
    about it, and the encoding into a four-valued signal happens in WP-11 where
    a rule can carry it with its own provenance.

    The source's own wording is kept verbatim in ``source_recommendation``, so
    a reviewer can disagree with any later reading of it without having to
    find the guideline again.
    """

    interpretation_key: str
    gene_canonical_key: str
    drug_canonical_key: str
    phenotype: Phenotype
    context: str
    rationale: str
    source_recommendation: str
    source_classification: str
    capture_record_id: str
    annotation_id: str
    citation: str
    curated_by: str
    authority_state: CandidateAuthorityState = \
        CandidateAuthorityState.SOURCE_GROUNDED_INTERNAL_DECISION
    review_state: CandidateAuthorityState = \
        CandidateAuthorityState.PENDING_EXTERNAL_EXPERT_REVIEW
    revision: int = 1
    supersedes: Optional[str] = None
    schema_version: str = CANDIDATE_INTERPRETATION_VERSION

    def __post_init__(self) -> None:
        for name in ("interpretation_key", "gene_canonical_key",
                     "drug_canonical_key", "context", "rationale",
                     "source_recommendation", "source_classification",
                     "capture_record_id", "annotation_id", "citation",
                     "curated_by"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError("%s must be a non-empty string" % name)
        if not isinstance(self.phenotype, Phenotype):
            raise TypeError("phenotype must be a Phenotype")
        if self.phenotype is Phenotype.INDETERMINATE:
            raise ValueError(
                "INDETERMINATE describes an input rather than a phenotype an "
                "interpretation can be about; the source states no "
                "recommendation for it and encoding one would be this "
                "project's invention")
        if self.review_state is not \
                CandidateAuthorityState.PENDING_EXTERNAL_EXPERT_REVIEW:
            raise ValueError(
                "review_state may only be PENDING_EXTERNAL_EXPERT_REVIEW")
        if "NOT A HUMAN" not in self.curated_by:
            raise ValueError(
                "curated_by must say plainly that it is not a human curator; "
                "this field is read by people who will not go looking for the "
                "authority state to find out")

    def semantic_content(self) -> Dict[str, Any]:
        return {
            "annotation_id": self.annotation_id,
            "authority_state": self.authority_state.value,
            "capture_record_id": self.capture_record_id,
            "context": self.context,
            "drug_id": self.drug_canonical_key,
            "gene_id": self.gene_canonical_key,
            "interpretation_key": self.interpretation_key,
            "phenotype": self.phenotype.value,
            "review_state": self.review_state.value,
            "revision": self.revision,
            "schema_version": self.schema_version,
            "source_classification": self.source_classification,
            "source_recommendation": self.source_recommendation,
            "supersedes": self.supersedes,
        }

    def content_hash(self) -> str:
        """Digest of what is claimed. Excludes who wrote it and the rationale.

        The same reading of the same row is the same interpretation whoever
        recorded it, which is the rule ``ComputableRuleDefinition`` already
        applies to ``created_by``. The rationale is excluded for the same
        reason: rewording an explanation does not change the claim, and a hash
        that moved would make "did this interpretation change" unanswerable.
        """
        return sha256_digest(self.semantic_content())

    def to_json(self) -> Dict[str, Any]:
        payload = dict(self.semantic_content())
        payload["citation"] = self.citation
        payload["content_hash"] = self.content_hash()
        payload["curated_by"] = self.curated_by
        payload["rationale"] = self.rationale
        return payload
