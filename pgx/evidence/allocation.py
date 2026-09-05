# -*- coding: utf-8 -*-
"""Explicit identity allocation for evidence records (WP-08).

Standard library plus :mod:`pgx.domain` and :mod:`pgx.evidence`.

The same reasoning WP-07 applies to genes and drugs applies here, for the same
reason. ``EvidenceRecordId`` has no ``derive()`` and none is added: a UUID
computed from a record's content would change whenever the source fixed a typo,
so "the same statement" and "the same bytes" would become one concept, and two
independent imports that happened to see the same source record would collapse
onto one row.

Reproducibility is reconciled with that by writing the mapping down. Identity
is allocated once, against the record's **natural key** - dataset, provider,
record type, source record ID, version part - and every later build reads the
artifact instead of minting anything.

**Natural-key change is visible, not silent.** A record whose version moves
from ``UNKNOWN_LEGACY`` to ``2`` has a different natural key and therefore a
new identity. That is correct: it is a different statement of the source, and
quietly reusing the old UUID would make one row appear to have changed its
content.

**Nothing is ever reclaimed.** A record that disappears from a later snapshot
keeps its allocated UUID, so a record that reappears gets the identity it had.
Unused entries are reported, never deleted.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import uuid as _uuid
from dataclasses import dataclass
from typing import (Any, Callable, Dict, Iterable, List, Mapping, Optional,
                    Tuple)

from pgx.domain.hashing import ensure_utc, sha256_digest
from pgx.evidence.errors import EvidenceAllocationError
from pgx.evidence.models import EvidenceNaturalKey

__all__ = [
    "EVIDENCE_ALLOCATION_FORMAT_VERSION",
    "EVIDENCE_ALLOCATOR_TOOL_ID",
    "EvidenceAllocation",
    "EvidenceAllocationEntry",
    "EvidenceAllocationResult",
    "allocate_evidence_identities",
    "read_evidence_allocation",
]

#: Bumped when the artifact layout or the allocation rules change.
EVIDENCE_ALLOCATION_FORMAT_VERSION = "pgx-evidence-identity-allocation/1"

#: Written into ``allocated_by``. Names a program, never a person: allocation
#: is mechanical bookkeeping, and a human name on it would fabricate a review.
EVIDENCE_ALLOCATOR_TOOL_ID = "pgx-evidence/allocate"


@dataclass(frozen=True, slots=True)
class EvidenceAllocationEntry:
    """One evidence natural key and the UUID this project uses for it."""

    natural_key: str
    record_uuid: str
    first_allocated_at: _dt.datetime

    def __post_init__(self) -> None:
        if not isinstance(self.natural_key, str) or not self.natural_key.strip():
            raise EvidenceAllocationError(
                "natural_key must be a non-empty string")
        # Parsed rather than pattern-matched: a key that cannot be read back
        # into its five parts is not a key this allocation may hold.
        EvidenceNaturalKey.parse(self.natural_key)
        object.__setattr__(self, "record_uuid",
                           _canonical_uuid(self.record_uuid, self.natural_key))
        object.__setattr__(self, "first_allocated_at",
                           ensure_utc(self.first_allocated_at,
                                      "first_allocated_at"))

    def content_identity(self) -> Dict[str, Any]:
        """The part a rebuild must reproduce: no timestamp."""
        return {"natural_key": self.natural_key,
                "record_uuid": self.record_uuid}

    def to_json(self) -> Dict[str, Any]:
        payload = self.content_identity()
        payload["first_allocated_at"] = _iso(self.first_allocated_at)
        return payload

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "EvidenceAllocationEntry":
        for field_name in ("natural_key", "record_uuid", "first_allocated_at"):
            if field_name not in payload:
                raise EvidenceAllocationError(
                    "allocation entry is missing %r" % field_name)
        return cls(
            natural_key=payload["natural_key"],
            record_uuid=payload["record_uuid"],
            first_allocated_at=_parse_instant(payload["first_allocated_at"],
                                              "first_allocated_at"))


@dataclass(frozen=True)
class EvidenceAllocation:
    """The complete, immutable natural-key to UUID map for one dataset.

    Bound to a dataset public ID. An allocation from one dataset is refused for
    another: their natural keys were not produced under a checked-equal
    extraction, and reusing the map across them would assert an equivalence
    nobody verified.
    """

    dataset_public_id: str
    entries: Tuple[EvidenceAllocationEntry, ...]
    created_at: _dt.datetime
    allocation_format_version: str = EVIDENCE_ALLOCATION_FORMAT_VERSION
    allocated_by: str = EVIDENCE_ALLOCATOR_TOOL_ID
    extraction_rule_version: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.dataset_public_id, str) \
                or not self.dataset_public_id.strip():
            raise EvidenceAllocationError(
                "dataset_public_id must be a non-empty string")
        object.__setattr__(self, "created_at",
                           ensure_utc(self.created_at, "created_at"))
        ordered = tuple(sorted(self.entries, key=lambda item: item.natural_key))
        object.__setattr__(self, "entries", ordered)

        by_key: Dict[str, EvidenceAllocationEntry] = {}
        by_uuid: Dict[str, str] = {}
        for entry in ordered:
            previous = by_key.get(entry.natural_key)
            if previous is not None:
                raise EvidenceAllocationError(
                    "natural key %r is allocated twice (%s and %s); one key "
                    "names one identity"
                    % (entry.natural_key, previous.record_uuid,
                       entry.record_uuid))
            by_key[entry.natural_key] = entry
            owner = by_uuid.get(entry.record_uuid)
            if owner is not None:
                raise EvidenceAllocationError(
                    "UUID %s is allocated to both %r and %r; two evidence "
                    "records sharing one identity would merge two source "
                    "statements silently"
                    % (entry.record_uuid, owner, entry.natural_key))
            by_uuid[entry.record_uuid] = entry.natural_key
        object.__setattr__(self, "_by_key", by_key)

    # -- lookup ----------------------------------------------------------

    def __len__(self) -> int:
        return len(self.entries)

    def __contains__(self, natural_key: object) -> bool:
        return natural_key in self._by_key

    @property
    def natural_keys(self) -> Tuple[str, ...]:
        return tuple(entry.natural_key for entry in self.entries)

    def uuid_for(self, natural_key: str) -> str:
        """Return the allocated UUID, or raise.

        Raising is correct. A build that reached a record with no allocated
        identity has found a gap in the artifact, and minting one on the spot
        is the behaviour this module exists to prevent.
        """
        entry = self._by_key.get(natural_key)
        if entry is None:
            raise EvidenceAllocationError(
                "no identity is allocated for %r in dataset %s. Allocation is "
                "an explicit step: run it before building, rather than minting "
                "an identity during an import."
                % (natural_key, self.dataset_public_id))
        return entry.record_uuid

    def get(self, natural_key: str) -> Optional[str]:
        entry = self._by_key.get(natural_key)
        return entry.record_uuid if entry is not None else None

    def missing_for(self, natural_keys: Iterable[str]) -> Tuple[str, ...]:
        return tuple(sorted({key for key in natural_keys
                             if key not in self._by_key}))

    def unused_for(self, natural_keys: Iterable[str]) -> Tuple[str, ...]:
        """Allocated keys this build does not use, sorted.

        Reported, never deleted: reclaiming an identity would give a record
        that reappeared in a later snapshot a different UUID than it had.
        """
        used = set(natural_keys)
        return tuple(sorted(key for key in self._by_key if key not in used))

    # -- serialisation ---------------------------------------------------

    def content_identity(self) -> Dict[str, Any]:
        """What a rebuild must reproduce byte for byte. No timestamps."""
        return {
            "allocation_format_version": self.allocation_format_version,
            "dataset_public_id": self.dataset_public_id,
            "extraction_rule_version": self.extraction_rule_version,
            "entries": [entry.content_identity() for entry in self.entries],
        }

    def content_hash(self) -> str:
        return sha256_digest(self.content_identity())

    def to_json(self) -> Dict[str, Any]:
        return {
            "allocation_format_version": self.allocation_format_version,
            "dataset_public_id": self.dataset_public_id,
            "extraction_rule_version": self.extraction_rule_version,
            "allocated_by": self.allocated_by,
            "created_at": _iso(self.created_at),
            "entry_count": len(self.entries),
            "content_hash": self.content_hash(),
            "entries": [entry.to_json() for entry in self.entries],
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "EvidenceAllocation":
        """Read an allocation artifact and re-verify its own content hash.

        The recorded hash is recomputed rather than trusted. An artifact whose
        stored hash disagrees with its entries has been edited, and an edited
        identity map is the one file in a build that must never be accepted on
        its own say-so.
        """
        if not isinstance(payload, Mapping):
            raise EvidenceAllocationError(
                "an allocation artifact must be a JSON object")
        version = payload.get("allocation_format_version")
        if version != EVIDENCE_ALLOCATION_FORMAT_VERSION:
            raise EvidenceAllocationError(
                "allocation artifact declares format %r; this build reads %r. "
                "Formats are not silently upgraded."
                % (version, EVIDENCE_ALLOCATION_FORMAT_VERSION))
        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, list):
            raise EvidenceAllocationError(
                "allocation artifact has no entries list")
        for field_name in ("dataset_public_id", "created_at"):
            if field_name not in payload:
                raise EvidenceAllocationError(
                    "allocation artifact is missing %r" % field_name)

        allocation = cls(
            dataset_public_id=payload["dataset_public_id"],
            entries=tuple(EvidenceAllocationEntry.from_json(item)
                          for item in raw_entries),
            created_at=_parse_instant(payload["created_at"], "created_at"),
            allocation_format_version=version,
            allocated_by=payload.get("allocated_by",
                                     EVIDENCE_ALLOCATOR_TOOL_ID),
            extraction_rule_version=payload.get("extraction_rule_version"))
        recorded = payload.get("content_hash")
        if recorded is not None and recorded != allocation.content_hash():
            raise EvidenceAllocationError(
                "allocation artifact content hash disagrees with its entries "
                "(recorded %s, recomputed %s); the file has been edited"
                % (recorded, allocation.content_hash()))
        recorded_count = payload.get("entry_count")
        if recorded_count is not None and recorded_count != len(allocation):
            raise EvidenceAllocationError(
                "allocation artifact records %r entries but carries %d"
                % (recorded_count, len(allocation)))
        return allocation


@dataclass(frozen=True, slots=True)
class EvidenceAllocationResult:
    """What one allocation run did, stated so a caller can refuse it."""

    allocation: EvidenceAllocation
    minted: Tuple[str, ...] = ()
    reused: Tuple[str, ...] = ()
    unused: Tuple[str, ...] = ()

    @property
    def is_rebuild(self) -> bool:
        return not self.minted

    def to_json(self) -> Dict[str, Any]:
        return {
            "dataset_public_id": self.allocation.dataset_public_id,
            "content_hash": self.allocation.content_hash(),
            "entry_count": len(self.allocation),
            "minted_count": len(self.minted),
            "reused_count": len(self.reused),
            "unused_count": len(self.unused),
            "unused": list(self.unused),
        }


def allocate_evidence_identities(
    dataset_public_id: str,
    natural_keys: Iterable[str],
    *,
    existing: Optional[EvidenceAllocation] = None,
    allow_new: bool = False,
    now: Optional[_dt.datetime] = None,
    extraction_rule_version: Optional[str] = None,
    uuid_factory: Callable[[], _uuid.UUID] = _uuid.uuid4,
) -> EvidenceAllocationResult:
    """Return an allocation covering every given natural key.

    Args:
        dataset_public_id: the dataset this allocation belongs to.
        natural_keys: every evidence natural key needing an identity.
        existing: a previously written allocation to extend. Its entries are
            reused verbatim and never renumbered or dropped.
        allow_new: whether this run may mint identities. Defaults to ``False``,
            so a run that merely intended to reproduce an earlier build fails
            loudly instead of quietly acquiring new UUIDs.
        uuid_factory: injected for tests. Production always uses ``uuid4``;
            there is no path that derives a UUID from a natural key.
    """
    if not isinstance(dataset_public_id, str) or not dataset_public_id.strip():
        raise EvidenceAllocationError(
            "dataset_public_id must be a non-empty string")

    requested = tuple(sorted(set(natural_keys)))
    for key in requested:
        parsed = EvidenceNaturalKey.parse(key)
        if parsed.dataset_public_id != dataset_public_id:
            raise EvidenceAllocationError(
                "natural key %r belongs to dataset %s, not %s"
                % (key, parsed.dataset_public_id, dataset_public_id))

    if existing is not None:
        if existing.dataset_public_id != dataset_public_id:
            raise EvidenceAllocationError(
                "the existing allocation belongs to dataset %s, not %s. An "
                "identity map is not portable between datasets."
                % (existing.dataset_public_id, dataset_public_id))
        entries: List[EvidenceAllocationEntry] = list(existing.entries)
        known = set(existing.natural_keys)
    else:
        entries = []
        known = set()

    missing = tuple(key for key in requested if key not in known)
    if missing and not allow_new:
        raise EvidenceAllocationError(
            "%d evidence natural key(s) have no allocated identity and this "
            "run may not mint one: %s. Allocation is a deliberate state "
            "change; run it explicitly rather than letting an import create "
            "identities."
            % (len(missing), ", ".join(missing[:5])
               + ("..." if len(missing) > 5 else "")))

    stamp = ensure_utc(now or _dt.datetime.now(_dt.timezone.utc), "now")
    minted: List[str] = []
    used = {entry.record_uuid for entry in entries}
    for key in missing:
        value = _mint(uuid_factory, used, key)
        entries.append(EvidenceAllocationEntry(
            natural_key=key, record_uuid=value, first_allocated_at=stamp))
        used.add(value)
        minted.append(key)

    allocation = EvidenceAllocation(
        dataset_public_id=dataset_public_id,
        entries=tuple(entries),
        created_at=(existing.created_at if existing is not None else stamp),
        extraction_rule_version=(
            extraction_rule_version if extraction_rule_version is not None
            else (existing.extraction_rule_version
                  if existing is not None else None)))
    return EvidenceAllocationResult(
        allocation=allocation,
        minted=tuple(sorted(minted)),
        reused=tuple(key for key in requested if key in known),
        unused=allocation.unused_for(requested))


def read_evidence_allocation(path: str) -> EvidenceAllocation:
    """Read an allocation artifact from disk.

    Separated from :meth:`EvidenceAllocation.from_json` so that "the file is
    unreadable" and "the file says something inconsistent" are distinguishable
    at the call site.
    """
    if not os.path.isfile(path):
        raise EvidenceAllocationError(
            "no evidence identity allocation at %s. An evidence build cannot "
            "proceed without one, and will not create one implicitly." % path)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        raise EvidenceAllocationError(
            "evidence identity allocation at %s could not be read: %s"
            % (path, exc)) from exc
    return EvidenceAllocation.from_json(payload)


# -- internals ----------------------------------------------------------


def _mint(uuid_factory: Callable[[], _uuid.UUID], used: set,
          natural_key: str) -> str:
    """Mint one identity, refusing a factory that repeats itself."""
    for _ in range(8):
        candidate = uuid_factory()
        if not isinstance(candidate, _uuid.UUID):
            raise EvidenceAllocationError(
                "the uuid factory returned %r, not a uuid.UUID"
                % type(candidate).__name__)
        text = str(candidate)
        if text not in used:
            return text
    raise EvidenceAllocationError(
        "the uuid factory kept returning identities already allocated while "
        "allocating %r; refusing to reuse an identity" % natural_key)


def _canonical_uuid(value: object, natural_key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceAllocationError(
            "the identity for %r must be a UUID string" % natural_key)
    try:
        parsed = _uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise EvidenceAllocationError(
            "the identity %r for %r is not a UUID: %s"
            % (value, natural_key, exc)) from exc
    text = str(parsed)
    if text != value:
        raise EvidenceAllocationError(
            "the identity %r for %r is not in canonical UUID spelling (%r)"
            % (value, natural_key, text))
    return text


def _iso(value: _dt.datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_instant(value: object, field_name: str) -> _dt.datetime:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceAllocationError("%s must be an ISO-8601 instant"
                                      % field_name)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise EvidenceAllocationError(
            "%s is not a readable instant: %r" % (field_name, value)) from exc
    if parsed.tzinfo is None:
        raise EvidenceAllocationError(
            "%s must carry a timezone offset; a naive instant has no defined "
            "moment" % field_name)
    return ensure_utc(parsed, field_name)
