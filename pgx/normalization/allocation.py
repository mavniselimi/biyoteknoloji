# -*- coding: utf-8 -*-
"""Explicit identity allocation for canonical entities (WP-07).

Standard library plus :mod:`pgx.domain` and :mod:`pgx.normalization`.

**Why this module exists at all.** ``GeneId`` and ``DrugId`` have no
``derive()``. That is deliberate: a scientific UUID derived from a name or an
external ID would make two independent curation runs that happened to observe
the same string collapse onto one row, and would let a source's spelling decide
this project's identity. But a build must still be reproducible - rebuilding the
same snapshot must produce the same UUIDs - and those two requirements can only
be reconciled by writing the mapping down.

So identity allocation is a **separate, explicit, state-changing step**. It
mints ``uuid4`` for canonical keys that have never been seen, records the
mapping in an immutable artifact, and every later build reads that artifact
instead of minting anything. The resolver mints nothing; the builder mints
nothing; :func:`allocate_identities` is the only place a canonical entity
identity is created, and it refuses to create one unless the caller passed
``allow_new=True``.

**Nothing is ever removed.** A canonical key that disappears from a later
snapshot keeps its allocated UUID. Reclaiming it would mean that a key which
reappeared later got a *different* identity than it had before, which is exactly
the silent divergence the artifact exists to prevent. Unused entries are
reported, not deleted.

**The allocation is not a decision about science.** It says "this project refers
to ``GENE:CYP2C19`` by this UUID". It says nothing about whether CYP2C19 is
curated, approved, clinically relevant, or usable.
"""

from __future__ import annotations

import datetime as _dt
import uuid as _uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from pgx.domain.hashing import ensure_utc, sha256_digest
from pgx.normalization.errors import AllocationError, NormalizationError
from pgx.normalization.models import EntityType, canonical_key_for
from pgx.normalization.normalize import normalize_drug_name, normalize_gene_symbol

__all__ = [
    "ALLOCATION_FORMAT_VERSION",
    "AllocationEntry",
    "AllocationResult",
    "IdentityAllocation",
    "allocate_identities",
    "read_allocation",
]

#: Bumped when the artifact layout or the allocation rules change. Recorded in
#: the artifact and in every canonical manifest that used it.
ALLOCATION_FORMAT_VERSION = "pgx-identity-allocation/1"

#: The tool identity written into ``allocated_by``. It names a program, never a
#: person: allocation is mechanical bookkeeping, and putting a human name on it
#: would fabricate a review that nobody performed.
ALLOCATOR_TOOL_ID = "pgx-normalize/allocate"


@dataclass(frozen=True, slots=True)
class AllocationEntry:
    """One canonical key and the UUID this project uses for it.

    ``first_allocated_at`` records when the mapping was created and is carried
    for auditability. It is excluded from the content hash, so a rebuild that
    reuses this entry is byte-identical to the build that created it.
    """

    entity_type: EntityType
    canonical_key: str
    entity_uuid: str
    first_allocated_at: _dt.datetime

    def __post_init__(self) -> None:
        if not isinstance(self.entity_type, EntityType):
            raise AllocationError("entity_type must be an EntityType")
        if not isinstance(self.canonical_key, str) or not self.canonical_key.strip():
            raise AllocationError("canonical_key must be a non-empty string")
        if not self.canonical_key.startswith(self.entity_type.value + ":"):
            raise AllocationError(
                "canonical key %r does not belong to entity type %s"
                % (self.canonical_key, self.entity_type.value))
        object.__setattr__(self, "entity_uuid",
                           _canonical_uuid(self.entity_uuid, self.canonical_key))
        object.__setattr__(self, "first_allocated_at",
                           ensure_utc(self.first_allocated_at,
                                      "first_allocated_at"))

    def content_identity(self) -> Dict[str, Any]:
        """The part a rebuild must reproduce: no timestamp."""
        return {
            "entity_type": self.entity_type.value,
            "canonical_key": self.canonical_key,
            "entity_uuid": self.entity_uuid,
        }

    def to_json(self) -> Dict[str, Any]:
        payload = self.content_identity()
        payload["first_allocated_at"] = _iso(self.first_allocated_at)
        return payload

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "AllocationEntry":
        try:
            entity_type = EntityType(payload["entity_type"])
        except (KeyError, ValueError) as exc:
            raise AllocationError(
                "allocation entry has a missing or unknown entity_type: %s" % exc
            ) from exc
        for field in ("canonical_key", "entity_uuid", "first_allocated_at"):
            if field not in payload:
                raise AllocationError(
                    "allocation entry is missing %r" % field)
        return cls(
            entity_type=entity_type,
            canonical_key=payload["canonical_key"],
            entity_uuid=payload["entity_uuid"],
            first_allocated_at=_parse_instant(payload["first_allocated_at"],
                                              "first_allocated_at"))


@dataclass(frozen=True)
class IdentityAllocation:
    """The complete, immutable canonical-key to UUID map for one dataset.

    Bound to a dataset public ID. An allocation from one dataset is refused for
    another, because the two datasets' canonical keys are not guaranteed to have
    been produced under the same normalisation rules, and reusing the map across
    them would assert an equivalence nobody checked.
    """

    dataset_public_id: str
    entries: Tuple[AllocationEntry, ...]
    created_at: _dt.datetime
    allocation_format_version: str = ALLOCATION_FORMAT_VERSION
    allocated_by: str = ALLOCATOR_TOOL_ID
    normalization_rule_version: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.dataset_public_id, str) \
                or not self.dataset_public_id.strip():
            raise AllocationError("dataset_public_id must be a non-empty string")
        object.__setattr__(self, "created_at",
                           ensure_utc(self.created_at, "created_at"))
        ordered = tuple(sorted(self.entries,
                               key=lambda item: item.canonical_key))
        object.__setattr__(self, "entries", ordered)

        by_key: Dict[str, AllocationEntry] = {}
        by_uuid: Dict[str, str] = {}
        for entry in ordered:
            previous = by_key.get(entry.canonical_key)
            if previous is not None:
                raise AllocationError(
                    "canonical key %r is allocated twice (%s and %s); one key "
                    "names one identity"
                    % (entry.canonical_key, previous.entity_uuid,
                       entry.entity_uuid))
            by_key[entry.canonical_key] = entry
            owner = by_uuid.get(entry.entity_uuid)
            if owner is not None:
                raise AllocationError(
                    "UUID %s is allocated to both %r and %r; two canonical keys "
                    "sharing one identity would merge two entities silently"
                    % (entry.entity_uuid, owner, entry.canonical_key))
            by_uuid[entry.entity_uuid] = entry.canonical_key
        object.__setattr__(self, "_by_key", by_key)

    # -- lookup ---------------------------------------------------------

    def __len__(self) -> int:
        return len(self.entries)

    def __contains__(self, canonical_key: object) -> bool:
        return canonical_key in self._by_key

    @property
    def canonical_keys(self) -> Tuple[str, ...]:
        return tuple(entry.canonical_key for entry in self.entries)

    def uuid_for(self, canonical_key: str) -> str:
        """Return the allocated UUID, or raise.

        Raising is correct here. A build that reached a canonical key with no
        allocated identity has found a gap in the artifact, and inventing one on
        the spot is precisely the behaviour this module exists to prevent.
        """
        entry = self._by_key.get(canonical_key)
        if entry is None:
            raise AllocationError(
                "no identity is allocated for %r in dataset %s. Allocation is "
                "an explicit step: run it before building, rather than minting "
                "an identity during a build."
                % (canonical_key, self.dataset_public_id))
        return entry.entity_uuid

    def get(self, canonical_key: str) -> Optional[str]:
        entry = self._by_key.get(canonical_key)
        return entry.entity_uuid if entry is not None else None

    def missing_for(self, canonical_keys: Iterable[str]) -> Tuple[str, ...]:
        """Canonical keys this allocation does not cover, sorted."""
        return tuple(sorted({key for key in canonical_keys
                             if key not in self._by_key}))

    def unused_for(self, canonical_keys: Iterable[str]) -> Tuple[str, ...]:
        """Allocated keys the given build does not use, sorted.

        Reported, never deleted: reclaiming an identity would give a key that
        reappeared in a later snapshot a different UUID than it had before.
        """
        used = set(canonical_keys)
        return tuple(sorted(key for key in self._by_key if key not in used))

    def entries_of(self, entity_type: EntityType) -> Tuple[AllocationEntry, ...]:
        return tuple(entry for entry in self.entries
                     if entry.entity_type is entity_type)

    # -- serialisation --------------------------------------------------

    def content_identity(self) -> Dict[str, Any]:
        """What a rebuild must reproduce byte for byte.

        Excludes ``created_at`` and every ``first_allocated_at``: when the map
        was written is a fact about the run, not about the mapping, and folding
        it in would make every rebuild differ from every other.
        """
        return {
            "allocation_format_version": self.allocation_format_version,
            "dataset_public_id": self.dataset_public_id,
            "normalization_rule_version": self.normalization_rule_version,
            "entries": [entry.content_identity() for entry in self.entries],
        }

    def content_hash(self) -> str:
        return sha256_digest(self.content_identity())

    def to_json(self) -> Dict[str, Any]:
        return {
            "allocation_format_version": self.allocation_format_version,
            "dataset_public_id": self.dataset_public_id,
            "normalization_rule_version": self.normalization_rule_version,
            "allocated_by": self.allocated_by,
            "created_at": _iso(self.created_at),
            "entry_count": len(self.entries),
            "content_hash": self.content_hash(),
            "entries": [entry.to_json() for entry in self.entries],
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "IdentityAllocation":
        """Read an allocation artifact and re-verify its own content hash.

        The recorded hash is recomputed rather than trusted. An artifact whose
        stored hash disagrees with its entries has been edited, and an edited
        identity map is the one file in a build that must never be accepted on
        its own say-so.
        """
        if not isinstance(payload, Mapping):
            raise AllocationError("an allocation artifact must be a JSON object")
        version = payload.get("allocation_format_version")
        if version != ALLOCATION_FORMAT_VERSION:
            raise AllocationError(
                "allocation artifact declares format %r; this build reads %r. "
                "Formats are not silently upgraded."
                % (version, ALLOCATION_FORMAT_VERSION))
        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, list):
            raise AllocationError("allocation artifact has no entries list")
        for field in ("dataset_public_id", "created_at"):
            if field not in payload:
                raise AllocationError("allocation artifact is missing %r" % field)

        allocation = cls(
            dataset_public_id=payload["dataset_public_id"],
            entries=tuple(AllocationEntry.from_json(item)
                          for item in raw_entries),
            created_at=_parse_instant(payload["created_at"], "created_at"),
            allocation_format_version=version,
            allocated_by=payload.get("allocated_by", ALLOCATOR_TOOL_ID),
            normalization_rule_version=payload.get("normalization_rule_version"),
        )
        recorded = payload.get("content_hash")
        if recorded is not None and recorded != allocation.content_hash():
            raise AllocationError(
                "allocation artifact content hash disagrees with its entries "
                "(recorded %s, recomputed %s); the file has been edited"
                % (recorded, allocation.content_hash()))
        recorded_count = payload.get("entry_count")
        if recorded_count is not None and recorded_count != len(allocation):
            raise AllocationError(
                "allocation artifact records %r entries but carries %d"
                % (recorded_count, len(allocation)))
        return allocation


@dataclass(frozen=True, slots=True)
class AllocationResult:
    """What one allocation run did, stated so a caller can refuse it.

    ``minted`` is empty on a pure rebuild. A caller that expected a rebuild and
    received a non-empty ``minted`` has discovered that its input changed, and
    that is worth failing over rather than absorbing.
    """

    allocation: IdentityAllocation
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
            "minted": list(self.minted),
            "unused": list(self.unused),
        }


def allocate_identities(
    dataset_public_id: str,
    canonical_keys: Iterable[str],
    *,
    existing: Optional[IdentityAllocation] = None,
    allow_new: bool = False,
    now: Optional[_dt.datetime] = None,
    normalization_rule_version: Optional[str] = None,
    uuid_factory: Callable[[], _uuid.UUID] = _uuid.uuid4,
) -> AllocationResult:
    """Return an allocation covering every given canonical key.

    Args:
        dataset_public_id: the dataset this allocation belongs to.
        canonical_keys: every canonical key the build needs an identity for.
        existing: a previously written allocation to extend. Its entries are
            reused verbatim and never renumbered or dropped.
        allow_new: whether this run may mint identities. Defaults to ``False``,
            so a build that merely intended to reproduce an earlier one fails
            loudly instead of quietly acquiring new UUIDs.
        now: the instant recorded on newly minted entries.
        uuid_factory: injected for tests. Production always uses ``uuid4``;
            there is no code path that derives a UUID from a canonical key.

    Raises:
        AllocationError: when keys are missing and ``allow_new`` is false, when
            the existing allocation belongs to another dataset, or when a key is
            malformed.
    """
    if not isinstance(dataset_public_id, str) or not dataset_public_id.strip():
        raise AllocationError("dataset_public_id must be a non-empty string")

    requested = tuple(sorted(set(canonical_keys)))
    for key in requested:
        _entity_type_of(key)

    if existing is not None:
        if existing.dataset_public_id != dataset_public_id:
            raise AllocationError(
                "the existing allocation belongs to dataset %s, not %s. An "
                "identity map is not portable between datasets: their canonical "
                "keys were not produced under a checked-equal normalisation."
                % (existing.dataset_public_id, dataset_public_id))
        entries: List[AllocationEntry] = list(existing.entries)
        known = set(existing.canonical_keys)
    else:
        entries = []
        known = set()

    missing = tuple(key for key in requested if key not in known)
    if missing and not allow_new:
        raise AllocationError(
            "%d canonical key(s) have no allocated identity and this run may "
            "not mint one: %s. Allocation is a deliberate state change; run it "
            "explicitly rather than letting a build create identities."
            % (len(missing), ", ".join(missing[:10])
               + ("..." if len(missing) > 10 else "")))

    stamp = ensure_utc(now or _dt.datetime.now(_dt.timezone.utc), "now")
    minted: List[str] = []
    used_uuids = {entry.entity_uuid for entry in entries}
    for key in missing:
        value = _mint(uuid_factory, used_uuids, key)
        entries.append(AllocationEntry(
            entity_type=_entity_type_of(key),
            canonical_key=key,
            entity_uuid=value,
            first_allocated_at=stamp))
        used_uuids.add(value)
        minted.append(key)

    allocation = IdentityAllocation(
        dataset_public_id=dataset_public_id,
        entries=tuple(entries),
        created_at=(existing.created_at if existing is not None else stamp),
        normalization_rule_version=(
            normalization_rule_version
            if normalization_rule_version is not None
            else (existing.normalization_rule_version
                  if existing is not None else None)),
    )
    reused = tuple(key for key in requested if key in known)
    return AllocationResult(
        allocation=allocation,
        minted=tuple(sorted(minted)),
        reused=reused,
        unused=allocation.unused_for(requested))


def read_allocation(path: str) -> IdentityAllocation:
    """Read an allocation artifact from disk.

    Separated from :meth:`IdentityAllocation.from_json` so that "the file is
    unreadable" and "the file says something inconsistent" are distinguishable
    at the call site.
    """
    import json
    import os

    if not os.path.isfile(path):
        raise AllocationError(
            "no identity allocation at %s. A canonical build cannot proceed "
            "without one, and will not create one implicitly." % path)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        raise AllocationError(
            "identity allocation at %s could not be read: %s" % (path, exc)
        ) from exc
    return IdentityAllocation.from_json(payload)


# -- internals ----------------------------------------------------------


def _entity_type_of(canonical_key: str) -> EntityType:
    """Recover the entity type from a canonical key, strictly."""
    if not isinstance(canonical_key, str) or ":" not in canonical_key:
        raise AllocationError(
            "%r is not a canonical key; expected TYPE:value" % (canonical_key,))
    prefix, _, value = canonical_key.partition(":")
    try:
        entity_type = EntityType(prefix)
    except ValueError as exc:
        raise AllocationError(
            "%r names an unknown entity type %r" % (canonical_key, prefix)
        ) from exc
    if not value:
        raise AllocationError(
            "%r carries no normalised value" % (canonical_key,))
    if canonical_key_for(entity_type, value) != canonical_key:
        raise AllocationError(
            "%r is not a well-formed canonical key" % (canonical_key,))
    # The normalised value must already be normalised. A key that merely looks
    # like one - GENE:cyp2c19 - would be allocated its own identity beside
    # GENE:CYP2C19, silently splitting one gene into two.
    normalizer = (normalize_gene_symbol if entity_type is EntityType.GENE
                  else normalize_drug_name)
    try:
        expected = normalizer(value)
    except NormalizationError as exc:
        raise AllocationError(
            "%r does not carry a normalisable value: %s" % (canonical_key, exc)
        ) from exc
    if expected != value:
        raise AllocationError(
            "%r is not in normalised form; the normalised key is %r. Allocating "
            "both would split one entity into two identities."
            % (canonical_key, canonical_key_for(entity_type, expected)))
    return entity_type


def _mint(uuid_factory: Callable[[], _uuid.UUID],
          used: set, canonical_key: str) -> str:
    """Mint one identity, refusing a factory that repeats itself."""
    for _ in range(8):
        candidate = uuid_factory()
        if not isinstance(candidate, _uuid.UUID):
            raise AllocationError(
                "the uuid factory returned %r, not a uuid.UUID"
                % type(candidate).__name__)
        text = str(candidate)
        if text not in used:
            return text
    raise AllocationError(
        "the uuid factory kept returning identities already allocated while "
        "allocating %r; refusing to reuse an identity" % canonical_key)


def _canonical_uuid(value: object, canonical_key: str) -> str:
    """Validate and canonicalise a UUID string."""
    if not isinstance(value, str) or not value.strip():
        raise AllocationError(
            "the identity for %r must be a UUID string" % canonical_key)
    try:
        parsed = _uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise AllocationError(
            "the identity %r for %r is not a UUID: %s"
            % (value, canonical_key, exc)) from exc
    text = str(parsed)
    if text != value:
        raise AllocationError(
            "the identity %r for %r is not in canonical UUID spelling (%r)"
            % (value, canonical_key, text))
    return text


def _iso(value: _dt.datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_instant(value: object, field: str) -> _dt.datetime:
    if not isinstance(value, str) or not value.strip():
        raise AllocationError("%s must be an ISO-8601 instant" % field)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise AllocationError(
            "%s is not a readable instant: %r" % (field, value)) from exc
    if parsed.tzinfo is None:
        raise AllocationError(
            "%s must carry a timezone offset; a naive instant has no defined "
            "moment" % field)
    return ensure_utc(parsed, field)
