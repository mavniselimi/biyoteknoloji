# -*- coding: utf-8 -*-
"""Duplicate detection that keeps every provenance link (WP-07).

Standard library plus :mod:`pgx.normalization`.

**A gene/drug pair is never a dedup key.** Several distinct annotations
legitimately describe the same pair - a CPIC guideline and a DPWG guideline for
CYP2C19 and clopidogrel are two records, not one seen twice. Deduplicating by
pair would delete real science, so every dedup key here is per record type and
is anchored on the *source's own record identity*.

**Three relationships, not one.**

* ``EXACT`` - one source record, one payload, observed at several locators.
  Nothing is lost by keeping one copy, provided every locator is kept.
* ``SEMANTIC`` - one source record and one payload, reached through different
  container spellings. This is ``LEGACY-BUG-004``: the pair endpoint returns
  the same list under ``variantAnnotation`` and ``VariantAnnotation``, and the
  legacy pipeline counted both.
* ``CONFLICTING_IDENTITY`` - one source record identity, **different payloads**.
  Not a duplicate in any useful sense: one of the two is wrong, and discarding
  either would hide which. Always blocking, never merged.

**A record without a source identity is never merged.** Two payloads that
happen to be equal are not evidence that they are the same record, and merging
on content alone would silently collapse independent observations. Such records
are reported and kept apart.

**Choosing a representative deletes nothing.** The representative is a storage
convenience - the smallest digest, chosen for determinism, not for quality.
Every member's locator survives in the group, and a test asserts it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from pgx.domain.immutable import freeze_json
from pgx.normalization.models import (
    DuplicateClass,
    DuplicateGroup,
    DuplicateMember,
    RawLocator,
    payload_digest,
)

__all__ = [
    "DEDUP_KEY_VERSION",
    "DedupResult",
    "RecordObservation",
    "deduplicate",
]

#: Bumped when a dedup key definition changes. Recorded on every group, so a
#: group produced under an older definition is never silently compared with a
#: newer one.
DEDUP_KEY_VERSION = "pgx-dedup/1"


@dataclass(frozen=True, slots=True)
class RecordObservation:
    """One sighting of one source record, at one place in the raw snapshot.

    ``semantic_key`` is what the caller considers the record's meaning-bearing
    identity beyond its ID - for the pair endpoint, the case-folded container
    family. ``container_spelling`` keeps the source's exact wording, which is
    what makes a case-variant duplicate reportable rather than merely fixed.
    """

    record_type: str
    source_record_id: Optional[str]
    semantic_key: str
    payload: Any
    locator: RawLocator
    container_spelling: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("record_type", "semantic_key"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    "RecordObservation.%s must be a non-empty string" % name)
        if not isinstance(self.locator, RawLocator):
            raise ValueError("RecordObservation.locator must be a RawLocator")
        object.__setattr__(self, "payload", freeze_json(self.payload))

    @property
    def digest(self) -> str:
        """Canonical digest of the payload.

        Canonical means key order and incidental whitespace cannot make two
        identical records look different - which is precisely what a
        case-variant container would otherwise do.
        """
        return payload_digest(self.payload)

    @property
    def identity_key(self) -> Optional[Tuple[str, str, str]]:
        """The dedup key, or ``None`` when the record has no source identity."""
        if self.source_record_id is None:
            return None
        return (self.record_type, self.semantic_key, self.source_record_id)


@dataclass(frozen=True)
class DedupResult:
    """Every duplicate group found, plus what could not be grouped at all.

    ``unidentified`` counts observations with no source record ID. They are not
    a duplicate finding - they are the reason a duplicate finding could not be
    made - and reporting them separately keeps that distinction visible.
    """

    groups: Tuple[DuplicateGroup, ...]
    distinct_records: int
    total_observations: int
    unidentified: Tuple[RawLocator, ...] = ()

    def of_class(self, classification: DuplicateClass) -> Tuple[DuplicateGroup, ...]:
        return tuple(group for group in self.groups
                     if group.classification is classification)

    @property
    def blocking_groups(self) -> Tuple[DuplicateGroup, ...]:
        return tuple(group for group in self.groups if group.blocking)

    def member_count(self, classification: DuplicateClass) -> int:
        return sum(group.member_count
                   for group in self.of_class(classification))

    @property
    def duplicate_observations(self) -> int:
        """Observations beyond the first in every group.

        This is the number the legacy pipeline would have processed twice, and
        it is derived from the groups rather than counted alongside them.
        """
        return sum(group.member_count - 1 for group in self.groups)

    def to_json(self) -> Dict[str, Any]:
        return {
            "dedup_key_version": DEDUP_KEY_VERSION,
            "total_observations": self.total_observations,
            "distinct_records": self.distinct_records,
            "duplicate_observations": self.duplicate_observations,
            "group_count": len(self.groups),
            "exact_group_count": len(self.of_class(DuplicateClass.EXACT)),
            "exact_member_count": self.member_count(DuplicateClass.EXACT),
            "semantic_group_count": len(self.of_class(DuplicateClass.SEMANTIC)),
            "semantic_member_count": self.member_count(DuplicateClass.SEMANTIC),
            "conflicting_identity_group_count":
                len(self.of_class(DuplicateClass.CONFLICTING_IDENTITY)),
            "conflicting_identity_member_count":
                self.member_count(DuplicateClass.CONFLICTING_IDENTITY),
            "unidentified_observation_count": len(self.unidentified),
        }


def deduplicate(observations: Iterable[RecordObservation]) -> DedupResult:
    """Group observations by source record identity and classify each group.

    Deterministic throughout: groups are ordered by key, members by locator,
    and the representative is the smallest digest. Two runs over the same
    observations produce byte-identical output whatever order they arrived in.
    """
    by_identity: Dict[Tuple[str, str, str], List[RecordObservation]] = {}
    unidentified: List[RawLocator] = []

    for observation in observations:
        key = observation.identity_key
        if key is None:
            unidentified.append(observation.locator)
            continue
        by_identity.setdefault(key, []).append(observation)

    groups: List[DuplicateGroup] = []
    for key in sorted(by_identity):
        members = by_identity[key]
        if len(members) < 2:
            continue
        groups.append(_classify(key, members))

    distinct = len(by_identity) + len(unidentified)
    total = sum(len(v) for v in by_identity.values()) + len(unidentified)
    return DedupResult(
        groups=tuple(groups),
        distinct_records=distinct,
        total_observations=total,
        unidentified=tuple(sorted(unidentified, key=lambda item: item.key)))


def _classify(key: Tuple[str, str, str],
              members: Sequence[RecordObservation]) -> DuplicateGroup:
    """Decide what a set of same-identity observations actually is."""
    record_type, semantic_key, source_record_id = key
    digests = sorted({member.digest for member in members})
    spellings = sorted({member.container_spelling for member in members
                        if member.container_spelling})

    duplicate_members = tuple(
        DuplicateMember(member.locator, member.digest, member.container_spelling)
        for member in members)
    group_key = "%s|%s|%s" % (record_type, semantic_key, source_record_id)

    if len(digests) > 1:
        return DuplicateGroup(
            group_key=group_key,
            record_type=record_type,
            dedup_key_version=DEDUP_KEY_VERSION,
            classification=DuplicateClass.CONFLICTING_IDENTITY,
            representative_digest=digests[0],
            members=duplicate_members,
            differences=(
                "source record %s carries %d different payloads: %s"
                % (source_record_id, len(digests), ", ".join(digests)),
            ),
            blocking=True)

    classification = (DuplicateClass.SEMANTIC if len(spellings) > 1
                      else DuplicateClass.EXACT)
    differences = ()
    if classification is DuplicateClass.SEMANTIC:
        differences = (
            "the same record was returned under %d container spellings: %s. "
            "The payloads are identical; only the source's capitalisation "
            "differs (LEGACY-BUG-004)." % (len(spellings), ", ".join(spellings)),
        )
    return DuplicateGroup(
        group_key=group_key,
        record_type=record_type,
        dedup_key_version=DEDUP_KEY_VERSION,
        classification=classification,
        representative_digest=digests[0],
        members=duplicate_members,
        differences=differences,
        blocking=False)
