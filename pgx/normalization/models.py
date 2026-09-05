# -*- coding: utf-8 -*-
"""Canonical entities, locators and resolution records (WP-07).

Standard library plus ``pgx.domain`` and :mod:`pgx.normalization.normalize`.

**What a canonical entity is here.** The WP-02 :class:`~pgx.domain.models.Gene`
and :class:`~pgx.domain.models.Drug` already carry identity, normalised value,
preferred name, aliases and external IDs. WP-07 does not replace them; it adds
the build-time record that says *where each one came from* and *which dataset it
belongs to*, and it adds the alias review state the resolver needs.

**The identity rule this module protects.** ``GeneId`` and ``DrugId`` have no
``derive()``, and none is added. A scientific UUID must not be a function of a
name or an external ID, because two curation runs that observed the same source
would then silently collide on one row. Identity comes from an explicit
allocation step (:mod:`pgx.normalization.allocation`); nothing here mints one.

**Nothing here is an interpretation.** There is no significance, no polarity, no
score, no severity, no phenotype-to-risk mapping and no treatment field. Those
are the columns the legacy CSVs mixed in with source facts, and a test asserts
they never appear on a canonical record.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Tuple

from pgx.domain.hashing import ensure_utc, sha256_digest
from pgx.normalization.errors import CanonicalizationError
from pgx.normalization.normalize import (
    ExternalIdentifier,
    normalize_drug_name,
    normalize_gene_symbol,
)

__all__ = [
    "AliasProposal",
    "AliasStatus",
    "CanonicalDrug",
    "CanonicalEntity",
    "CanonicalGene",
    "DuplicateClass",
    "DuplicateGroup",
    "DuplicateMember",
    "EntityType",
    "RawLocator",
    "ResolutionMethod",
    "ResolutionOutcome",
    "ResolutionQueueItem",
    "ResolutionStatus",
    "ReasonCode",
    "canonical_key_for",
    "payload_digest",
]


class EntityType(str, Enum):
    """The two canonical entity kinds P0 resolves."""

    GENE = "GENE"
    DRUG = "DRUG"

    def __str__(self) -> str:
        return self.value


class AliasStatus(str, Enum):
    """Where an alias stands in review.

    Only ``APPROVED`` participates in resolution. An alternative name observed
    upstream is a *proposal*: recording it is useful, and letting it resolve an
    entity because a source happened to print it would make the source, not a
    reviewer, decide what this project treats as the same thing.
    """

    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DEPRECATED = "DEPRECATED"

    def __str__(self) -> str:
        return self.value


#: The only status a resolver may match on.
RESOLVING_ALIAS_STATUSES: Tuple[AliasStatus, ...] = (AliasStatus.APPROVED,)


class ResolutionStatus(str, Enum):
    """The outcome of one resolution attempt."""

    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"
    INVALID_INPUT = "INVALID_INPUT"
    BROKEN_REFERENCE = "BROKEN_REFERENCE"

    def __str__(self) -> str:
        return self.value


class ResolutionMethod(str, Enum):
    """Which stage produced the outcome.

    The order of the members is the order the stages run in, and
    :mod:`pgx.normalization.resolver` iterates this vocabulary rather than a
    separate list, so a stage cannot be added without appearing here.
    """

    EXTERNAL_ID = "EXTERNAL_ID"
    PREFERRED_NAME = "PREFERRED_NAME"
    APPROVED_ALIAS = "APPROVED_ALIAS"
    CROSS_REFERENCE = "CROSS_REFERENCE"
    NONE = "NONE"

    def __str__(self) -> str:
        return self.value


#: The four matching stages, in the exact order ``architecture.md`` 8.3 fixes.
RESOLUTION_STAGES: Tuple[ResolutionMethod, ...] = (
    ResolutionMethod.EXTERNAL_ID,
    ResolutionMethod.PREFERRED_NAME,
    ResolutionMethod.APPROVED_ALIAS,
    ResolutionMethod.CROSS_REFERENCE,
)


class ReasonCode(str, Enum):
    """Stable machine-readable reasons. Renaming one is a breaking change."""

    MATCHED_EXTERNAL_ID = "MATCHED_EXTERNAL_ID"
    MATCHED_PREFERRED_NAME = "MATCHED_PREFERRED_NAME"
    MATCHED_APPROVED_ALIAS = "MATCHED_APPROVED_ALIAS"
    MATCHED_CROSS_REFERENCE = "MATCHED_CROSS_REFERENCE"
    AMBIGUOUS_EXTERNAL_ID = "AMBIGUOUS_EXTERNAL_ID"
    AMBIGUOUS_PREFERRED_NAME = "AMBIGUOUS_PREFERRED_NAME"
    AMBIGUOUS_APPROVED_ALIAS = "AMBIGUOUS_APPROVED_ALIAS"
    AMBIGUOUS_CROSS_REFERENCE = "AMBIGUOUS_CROSS_REFERENCE"
    NO_CANDIDATE_FOUND = "NO_CANDIDATE_FOUND"
    NOT_NORMALIZABLE = "NOT_NORMALIZABLE"
    MISSING_VALUE = "MISSING_VALUE"
    REFERENCED_ENTITY_ABSENT = "REFERENCED_ENTITY_ABSENT"
    ALIAS_NOT_APPROVED = "ALIAS_NOT_APPROVED"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class RawLocator:
    """Exactly where in the raw snapshot one parsed value came from.

    Every field is required except the source record ID, which some records
    genuinely lack - and that absence is itself a data-quality finding rather
    than something to paper over with a generated value.

    The snapshot manifest hash and the artifact digest are both carried so that
    a locator remains checkable after the fact: an artifact that changed since
    the build is detectable without re-reading the whole snapshot.
    """

    dataset_public_id: str
    snapshot_manifest_hash: str
    artifact_path: str
    artifact_sha256: str
    pointer: str
    source_record_id: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("dataset_public_id", "snapshot_manifest_hash",
                     "artifact_path", "artifact_sha256", "pointer"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise CanonicalizationError(
                    "RawLocator.%s must be a non-empty string" % name)
        if self.artifact_path.startswith("/") or ".." in self.artifact_path:
            raise CanonicalizationError(
                "RawLocator.artifact_path must be a relative, traversal-free "
                "path, got %r" % self.artifact_path)

    def to_json(self) -> Dict[str, Any]:
        return {
            "dataset_public_id": self.dataset_public_id,
            "snapshot_manifest_hash": self.snapshot_manifest_hash,
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "pointer": self.pointer,
            "source_record_id": self.source_record_id,
        }

    @property
    def key(self) -> Tuple[str, str, str]:
        """Sort key: artifact, then pointer, then record ID."""
        return (self.artifact_path, self.pointer, self.source_record_id or "")


@dataclass(frozen=True, slots=True)
class AliasProposal:
    """An alternative name observed upstream, with its review state.

    Created ``PENDING_REVIEW`` and stays there. There is no method that
    approves one, and a test asserts the absence: approval is a human decision
    recorded deliberately, and a convenience wrapper would become the route
    everyone used.
    """

    normalized_alias: str
    display_alias: str
    status: AliasStatus = AliasStatus.PENDING_REVIEW
    locator: Optional[RawLocator] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[_dt.datetime] = None
    note: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, AliasStatus):
            raise CanonicalizationError("status must be an AliasStatus")
        for name in ("normalized_alias", "display_alias"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise CanonicalizationError(
                    "AliasProposal.%s must be a non-empty string" % name)
        if self.reviewed_at is not None:
            object.__setattr__(self, "reviewed_at",
                               ensure_utc(self.reviewed_at, "reviewed_at"))
        # An approval that names nobody is not an approval.
        if self.status is AliasStatus.APPROVED:
            if not (self.reviewed_by and self.reviewed_by.strip()):
                raise CanonicalizationError(
                    "an APPROVED alias must name the reviewer who approved it; "
                    "an unattributed approval cannot be re-examined")
            if self.reviewed_at is None:
                raise CanonicalizationError(
                    "an APPROVED alias must record when it was approved")

    @property
    def resolves(self) -> bool:
        """True only for an approved alias."""
        return self.status in RESOLVING_ALIAS_STATUSES

    def to_json(self) -> Dict[str, Any]:
        return {
            "normalized_alias": self.normalized_alias,
            "display_alias": self.display_alias,
            "status": self.status.value,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": (self.reviewed_at.isoformat().replace("+00:00", "Z")
                            if self.reviewed_at else None),
            "note": self.note,
            "locator": self.locator.to_json() if self.locator else None,
        }


@dataclass(frozen=True, slots=True)
class CanonicalEntity:
    """One canonical gene or drug as a build produced it.

    ``canonical_key`` is the deterministic natural key - ``GENE:CYP2C19``,
    ``DRUG:clopidogrel`` - and is what the identity allocation maps to a UUID.
    It is *not* the UUID and is never used as one: two builds of the same
    snapshot share canonical keys and share UUIDs only because the allocation
    artifact says so.

    ``source_display`` keeps the source's own spelling. A canonical record that
    discarded it could not be checked against the source again.
    """

    entity_type: EntityType
    canonical_key: str
    normalized_value: str
    preferred_display: str
    source_display: str
    entity_uuid: Optional[str] = None
    external_ids: Tuple[ExternalIdentifier, ...] = ()
    aliases: Tuple[AliasProposal, ...] = ()
    locators: Tuple[RawLocator, ...] = ()
    findings: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.entity_type, EntityType):
            raise CanonicalizationError("entity_type must be an EntityType")
        expected = canonical_key_for(self.entity_type, self.normalized_value)
        if self.canonical_key != expected:
            raise CanonicalizationError(
                "canonical_key %r does not match the normalised value (%r)"
                % (self.canonical_key, expected))
        if self.entity_type is EntityType.GENE:
            if self.normalized_value != normalize_gene_symbol(self.normalized_value):
                raise CanonicalizationError(
                    "a canonical gene must carry an already-normalised symbol")
        else:
            if self.normalized_value != normalize_drug_name(self.normalized_value):
                raise CanonicalizationError(
                    "a canonical drug must carry an already-normalised name")
        object.__setattr__(self, "external_ids", tuple(
            sorted(set(self.external_ids), key=lambda item: (item[0], item[1]))))
        object.__setattr__(self, "aliases", tuple(
            sorted(self.aliases, key=lambda item: item.normalized_alias)))
        object.__setattr__(self, "locators", tuple(
            sorted(self.locators, key=lambda item: item.key)))
        object.__setattr__(self, "findings", tuple(sorted(set(self.findings))))
        if not self.locators:
            raise CanonicalizationError(
                "a canonical entity must carry at least one raw locator; an "
                "entity with no provenance cannot be traced to a source")

    @property
    def approved_aliases(self) -> Tuple[AliasProposal, ...]:
        return tuple(alias for alias in self.aliases if alias.resolves)

    def content_identity(self) -> Dict[str, Any]:
        """What a rebuild of the same snapshot must reproduce.

        Excludes the allocated UUID, so two projects that allocated different
        identities to the same source data still agree on what the data *is*.
        """
        return {
            "entity_type": self.entity_type.value,
            "canonical_key": self.canonical_key,
            "normalized_value": self.normalized_value,
            "preferred_display": self.preferred_display,
            "source_display": self.source_display,
            "external_ids": [item.to_json() for item in self.external_ids],
            "alias_count": len(self.aliases),
            "locator_count": len(self.locators),
            "findings": list(self.findings),
        }

    def to_json(self) -> Dict[str, Any]:
        payload = self.content_identity()
        payload["entity_uuid"] = self.entity_uuid
        payload["aliases"] = [alias.to_json() for alias in self.aliases]
        payload["locators"] = [locator.to_json() for locator in self.locators]
        return payload


def canonical_key_for(entity_type: EntityType, normalized_value: str) -> str:
    """The deterministic natural key for an entity.

    Deliberately human-readable and deliberately not a UUID. It is stable
    across rebuilds, which is what lets an identity allocation be reused; it
    carries no scientific identity of its own.
    """
    return "%s:%s" % (entity_type.value, normalized_value)


#: Aliases kept for readability at call sites.
CanonicalGene = CanonicalEntity
CanonicalDrug = CanonicalEntity


@dataclass(frozen=True, slots=True)
class ResolutionOutcome:
    """The complete answer to one resolution attempt.

    ``candidate_keys`` holds **every** candidate when the outcome is ambiguous,
    not a selection from them. That is the difference between reporting an
    ambiguity and hiding one, and it is why the resolver returns a record
    rather than an optional entity.
    """

    entity_type: EntityType
    submitted_value: str
    normalized_value: Optional[str]
    status: ResolutionStatus
    method: ResolutionMethod
    reason: ReasonCode
    canonical_key: Optional[str] = None
    candidate_keys: Tuple[str, ...] = ()
    matched_field: Optional[str] = None
    locator: Optional[RawLocator] = None
    detail: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_keys",
                           tuple(sorted(set(self.candidate_keys))))
        if self.status is ResolutionStatus.RESOLVED and not self.canonical_key:
            raise CanonicalizationError(
                "a RESOLVED outcome must name the canonical key it resolved to")
        if self.status is ResolutionStatus.AMBIGUOUS and len(self.candidate_keys) < 2:
            raise CanonicalizationError(
                "an AMBIGUOUS outcome must carry every candidate; %d is not an "
                "ambiguity" % len(self.candidate_keys))
        if self.status is ResolutionStatus.RESOLVED and self.candidate_keys:
            if tuple(self.candidate_keys) != (self.canonical_key,):
                raise CanonicalizationError(
                    "a RESOLVED outcome may not carry candidates it did not "
                    "choose; that would be a silent selection")

    @property
    def is_resolved(self) -> bool:
        return self.status is ResolutionStatus.RESOLVED

    @property
    def needs_review(self) -> bool:
        """True for every outcome that must reach the resolution queue."""
        return self.status is not ResolutionStatus.RESOLVED

    def to_json(self) -> Dict[str, Any]:
        return {
            "entity_type": self.entity_type.value,
            "submitted_value": self.submitted_value,
            "normalized_value": self.normalized_value,
            "status": self.status.value,
            "method": self.method.value,
            "reason": self.reason.value,
            "canonical_key": self.canonical_key,
            "candidate_keys": list(self.candidate_keys),
            "matched_field": self.matched_field,
            "locator": self.locator.to_json() if self.locator else None,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ResolutionQueueItem:
    """One thing a human has to look at, with everything they need to look at it.

    There is no ``decision`` field carrying a machine decision. The decision
    fields exist only to model a real human's answer, and WP-07 creates none:
    an item whose candidate set narrowed to one through later filtering is
    still unresolved, because nobody chose.
    """

    queue_key: str
    dataset_public_id: str
    canonical_build_key: str
    outcome: ResolutionOutcome
    created_at: _dt.datetime
    decided_by: Optional[str] = None
    decided_at: Optional[_dt.datetime] = None
    decision_rationale: Optional[str] = None
    chosen_canonical_key: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at",
                           ensure_utc(self.created_at, "created_at"))
        if self.decided_at is not None:
            object.__setattr__(self, "decided_at",
                               ensure_utc(self.decided_at, "decided_at"))
        decided = any((self.decided_by, self.decided_at,
                       self.decision_rationale, self.chosen_canonical_key))
        if decided:
            missing = [name for name in ("decided_by", "decided_at",
                                         "decision_rationale")
                       if not getattr(self, name)]
            if missing:
                raise CanonicalizationError(
                    "a queue decision needs a named reviewer, an instant and a "
                    "rationale; missing %s" % ", ".join(missing))
            if (self.chosen_canonical_key
                    and self.outcome.candidate_keys
                    and self.chosen_canonical_key not in self.outcome.candidate_keys):
                raise CanonicalizationError(
                    "a decision may only choose one of the candidates that "
                    "were actually ambiguous")

    @property
    def is_decided(self) -> bool:
        return self.decided_by is not None

    def to_json(self) -> Dict[str, Any]:
        return {
            "queue_key": self.queue_key,
            "dataset_public_id": self.dataset_public_id,
            "canonical_build_key": self.canonical_build_key,
            "entity_type": self.outcome.entity_type.value,
            "submitted_value": self.outcome.submitted_value,
            "normalized_value": self.outcome.normalized_value,
            "status": self.outcome.status.value,
            "stage": self.outcome.method.value,
            "reason": self.outcome.reason.value,
            "candidate_keys": list(self.outcome.candidate_keys),
            "locator": (self.outcome.locator.to_json()
                        if self.outcome.locator else None),
            "detail": self.outcome.detail,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "decided_by": self.decided_by,
            "decided_at": (self.decided_at.isoformat().replace("+00:00", "Z")
                           if self.decided_at else None),
            "decision_rationale": self.decision_rationale,
            "chosen_canonical_key": self.chosen_canonical_key,
        }


class DuplicateClass(str, Enum):
    """How two records that look alike actually relate.

    The third member is the one that matters. Two records claiming the same
    source identity while disagreeing about their content are not duplicates in
    any useful sense - one of them is wrong, and discarding either would hide
    which.
    """

    EXACT = "EXACT"
    SEMANTIC = "SEMANTIC"
    CONFLICTING_IDENTITY = "CONFLICTING_IDENTITY"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class DuplicateMember:
    """One raw observation inside a duplicate group."""

    locator: RawLocator
    payload_digest: str
    container_spelling: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "locator": self.locator.to_json(),
            "payload_digest": self.payload_digest,
            "container_spelling": self.container_spelling,
        }


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    """Every observation of one record, and how they relate.

    A representative is named for storage convenience only. Every member's
    locator is retained, and a test asserts that choosing a representative
    never drops one: provenance is the thing a duplicate group exists to keep.
    """

    group_key: str
    record_type: str
    dedup_key_version: str
    classification: DuplicateClass
    representative_digest: str
    members: Tuple[DuplicateMember, ...]
    differences: Tuple[str, ...] = ()
    blocking: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "members", tuple(
            sorted(self.members, key=lambda item: item.locator.key)))
        # A bare string here would be exploded into single characters by the
        # set() below, producing a "difference list" of the alphabet. Refusing
        # it turns a missed comma into an error rather than into nonsense that
        # still serialises.
        if isinstance(self.differences, str):
            raise CanonicalizationError(
                "DuplicateGroup.differences must be a sequence of strings, not "
                "one string; a bare string would be split into characters")
        object.__setattr__(self, "differences", tuple(sorted(set(self.differences))))
        if len(self.members) < 2:
            raise CanonicalizationError(
                "a duplicate group needs at least two observations, got %d"
                % len(self.members))
        if self.classification is DuplicateClass.CONFLICTING_IDENTITY:
            if not self.blocking:
                raise CanonicalizationError(
                    "a conflicting identity collision is always blocking: two "
                    "records claiming one identity while disagreeing cannot be "
                    "resolved by discarding one")
            if not self.differences:
                raise CanonicalizationError(
                    "a conflicting identity collision must say what differs")

    @property
    def member_count(self) -> int:
        return len(self.members)

    @property
    def container_spellings(self) -> Tuple[str, ...]:
        return tuple(sorted({member.container_spelling
                             for member in self.members
                             if member.container_spelling}))

    def to_json(self) -> Dict[str, Any]:
        return {
            "group_key": self.group_key,
            "record_type": self.record_type,
            "dedup_key_version": self.dedup_key_version,
            "classification": self.classification.value,
            "representative_digest": self.representative_digest,
            "member_count": self.member_count,
            "container_spellings": list(self.container_spellings),
            "members": [member.to_json() for member in self.members],
            "differences": list(self.differences),
            "blocking": self.blocking,
        }


def payload_digest(payload: Any) -> str:
    """Canonical digest of a record payload, for duplicate comparison.

    Uses the project's one canonical encoding, so a payload that differs only
    in key order or incidental whitespace digests identically - which is what
    makes "the same record spelled two ways" detectable.
    """
    return sha256_digest(payload)
