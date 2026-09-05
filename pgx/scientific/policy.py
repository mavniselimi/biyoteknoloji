# -*- coding: utf-8 -*-
"""Loading and querying the scientific source registry (WP-05).

Standard library plus ``pgx.domain`` and :mod:`pgx.scientific.models`. No
network, no database, no configuration written back: this module reads a JSON
policy file and answers questions about it.

**Why a file and not a table.** The registry is a reviewed document. It belongs
in version control, where a change to a licensing conclusion shows up in a diff
with an author against it, rather than in a row somebody updated. The database
tables added by the WP-05 migration record *operational* state - which policy
version was in force when a dataset was published - and do not replace this
file as the place a policy is decided.

**Fail-closed lookup.** :meth:`SourcePolicyRegistry.get` returns ``None`` for an
unregistered key and :meth:`SourcePolicyRegistry.require` raises. Neither
invents a default record, because a default record is a policy decision nobody
made. Callers that must not proceed without a policy use ``require``.

**Determinism.** Records are stored in ``source_key`` order and rendered in that
order, so :meth:`SourcePolicyRegistry.content_hash` depends on what the policy
says and not on how the file happened to be written.
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.domain.hashing import sha256_digest
from pgx.scientific.errors import (
    ConflictRegistryError,
    SourcePolicyConfigError,
    SourcePolicyValidationError,
    UnknownSourceError,
)
from pgx.scientific.models import (
    ClaimCategory,
    ReuseDimension,
    ReusePermission,
    SourceConflict,
    SourcePolicyRecord,
    SourcePolicyStatus,
)

__all__ = [
    "CONFIG_FILE_NAME",
    "SOURCE_REGISTRY_SCHEMA_VERSION",
    "SourcePolicyRegistry",
    "default_config_path",
    "load_registry",
    "registry_from_json",
    "render_registry",
    "source_keys_referenced_by",
]

#: Schema identity of the registry file. Present in the file itself, checked on
#: load. A file written against a different schema is refused rather than
#: partially understood.
SOURCE_REGISTRY_SCHEMA_VERSION = "pgx-scientific-source-registry/1"

CONFIG_FILE_NAME = os.path.join("config", "scientific-sources.json")

#: Top-level keys the registry file may carry.
_REGISTRY_KEYS = frozenset({
    "schema_version", "generated_note", "policy_owner", "sources", "conflicts",
})

#: How far up the tree to look for the repository root. Bounded so a missing
#: file fails quickly instead of walking to ``/``.
_MAX_ROOT_SEARCH_DEPTH = 8


def default_config_path(start: Optional[str] = None) -> str:
    """Return the path of the checked-in registry file.

    Walks upward from this module looking for ``config/scientific-sources.json``.
    The file lives in the repository rather than in the wheel: it is a reviewed
    document, and a deployment that needs a different one should pass its path
    explicitly rather than have one silently substituted.

    Raises:
        SourcePolicyConfigError: if no registry file is found. Never returns a
            speculative path, because a caller handed a path that does not exist
            would report "no sources restricted" for the wrong reason.
    """
    here = os.path.dirname(os.path.abspath(start or __file__))
    for _ in range(_MAX_ROOT_SEARCH_DEPTH):
        candidate = os.path.join(here, CONFIG_FILE_NAME)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    raise SourcePolicyConfigError(
        "no %s found above %s. The source registry is required: an absent "
        "policy file is not an absence of restrictions."
        % (CONFIG_FILE_NAME, os.path.dirname(os.path.abspath(start or __file__))))


@dataclass(frozen=True)
class SourcePolicyRegistry:
    """Every source policy the project has recorded, plus known conflicts.

    Immutable. Reloading is how the registry changes, so that no long-lived
    process can be holding a policy that quietly diverged from the file.
    """

    records: Tuple[SourcePolicyRecord, ...]
    conflicts: Tuple[SourceConflict, ...] = ()
    schema_version: str = SOURCE_REGISTRY_SCHEMA_VERSION
    generated_note: Optional[str] = None
    policy_owner: Optional[str] = None
    source_path: Optional[str] = None

    def __post_init__(self) -> None:
        keys: Dict[str, SourcePolicyRecord] = {}
        for record in self.records:
            if not isinstance(record, SourcePolicyRecord):
                raise SourcePolicyValidationError(
                    "registry records must be SourcePolicyRecord instances")
            if record.source_key in keys:
                raise SourcePolicyValidationError(
                    "duplicate source_key %r in the registry; one source key "
                    "must name exactly one policy" % record.source_key)
            keys[record.source_key] = record
        object.__setattr__(
            self, "records",
            tuple(sorted(self.records, key=lambda item: item.source_key)))

        conflict_keys = set()
        for conflict in self.conflicts:
            if not isinstance(conflict, SourceConflict):
                raise ConflictRegistryError(
                    "registry conflicts must be SourceConflict instances")
            if conflict.conflict_key in conflict_keys:
                raise ConflictRegistryError(
                    "duplicate conflict_key %r" % conflict.conflict_key)
            conflict_keys.add(conflict.conflict_key)
            unknown = tuple(key for key in conflict.source_keys if key not in keys)
            if unknown:
                raise ConflictRegistryError(
                    "conflict %r names unregistered source(s): %s. A conflict "
                    "between sources the project has no policy for is a "
                    "registry gap, not a conflict record."
                    % (conflict.conflict_key, ", ".join(sorted(unknown))))
        object.__setattr__(
            self, "conflicts",
            tuple(sorted(self.conflicts, key=lambda item: item.conflict_key)))

    # -- lookup ----------------------------------------------------------

    def get(self, source_key: str) -> Optional[SourcePolicyRecord]:
        """Return the policy for ``source_key``, or ``None`` if unregistered.

        ``None`` means "the project has decided nothing", which every caller
        must treat as blocking. It does not mean "unrestricted".
        """
        for record in self.records:
            if record.source_key == source_key:
                return record
        return None

    def require(self, source_key: str) -> SourcePolicyRecord:
        """Return the policy for ``source_key`` or raise :class:`UnknownSourceError`."""
        record = self.get(source_key)
        if record is None:
            raise UnknownSourceError(
                source_key,
                "the registry carries %d source(s); an unregistered source has "
                "no permissions, not unlimited ones" % len(self.records))
        return record

    def __contains__(self, source_key: object) -> bool:
        return isinstance(source_key, str) and self.get(source_key) is not None

    def __len__(self) -> int:
        return len(self.records)

    @property
    def source_keys(self) -> Tuple[str, ...]:
        """Every registered key, in canonical order."""
        return tuple(record.source_key for record in self.records)

    def with_status(self, status: SourcePolicyStatus) -> Tuple[SourcePolicyRecord, ...]:
        return tuple(r for r in self.records if r.status is status)

    @property
    def approved_records(self) -> Tuple[SourcePolicyRecord, ...]:
        """Records whose approval is backed by a review. Usually empty."""
        return tuple(r for r in self.records if r.is_approved)

    @property
    def unapproved_records(self) -> Tuple[SourcePolicyRecord, ...]:
        return tuple(r for r in self.records if not r.is_approved)

    def conflicts_for(self, source_key: str) -> Tuple[SourceConflict, ...]:
        """Every recorded conflict this source takes part in."""
        return tuple(c for c in self.conflicts if source_key in c.source_keys)

    @property
    def blocking_conflicts(self) -> Tuple[SourceConflict, ...]:
        """Conflicts that are unsettled and could change what is published."""
        return tuple(c for c in self.conflicts if c.blocks_publication)

    # -- derived views ---------------------------------------------------

    def permission(
        self, source_key: str, dimension: ReuseDimension
    ) -> ReusePermission:
        """Return the reuse permission for one source and one dimension.

        An unregistered source answers ``UNKNOWN`` rather than raising, so a
        matrix renderer can show the whole picture including its gaps. Callers
        deciding whether to *act* use :meth:`require` first.
        """
        record = self.get(source_key)
        if record is None:
            return ReusePermission.UNKNOWN
        return record.reuse.permission(dimension)

    def sources_supporting(
        self, category: ClaimCategory, now: Any
    ) -> Tuple[SourcePolicyRecord, ...]:
        """Sources cleared, at ``now``, to support ``category``."""
        return tuple(r for r in self.records if r.may_support_claim(category, now))

    # -- serialisation ---------------------------------------------------

    def to_json(self) -> Dict[str, Any]:
        """Canonical plain-JSON form: sorted records, fixed key order."""
        payload: Dict[str, Any] = {"schema_version": self.schema_version}
        if self.generated_note is not None:
            payload["generated_note"] = self.generated_note
        if self.policy_owner is not None:
            payload["policy_owner"] = self.policy_owner
        payload["sources"] = [record.to_json() for record in self.records]
        payload["conflicts"] = [conflict.to_json() for conflict in self.conflicts]
        return payload

    def content_hash(self) -> str:
        """Digest of the policy content, excluding where the file lives.

        ``source_path`` is deliberately not part of the payload: the same policy
        checked out at two paths is the same policy.
        """
        return sha256_digest(self.to_json())


def registry_from_json(
    payload: Mapping[str, Any], source_path: Optional[str] = None
) -> SourcePolicyRegistry:
    """Build a registry from an already-parsed JSON document.

    Raises:
        SourcePolicyConfigError: the document shape is wrong at the top level.
        SourcePolicyValidationError: a record is invalid.
        ReviewIntegrityError: a record claims an approval it cannot support.
    """
    if not isinstance(payload, Mapping):
        raise SourcePolicyConfigError(
            "the source registry must be a JSON object, got %r"
            % type(payload).__name__)

    unknown = sorted(set(payload) - _REGISTRY_KEYS)
    if unknown:
        raise SourcePolicyConfigError(
            "the source registry carries unknown top-level key(s): %s"
            % ", ".join(unknown))

    schema_version = payload.get("schema_version")
    if schema_version != SOURCE_REGISTRY_SCHEMA_VERSION:
        raise SourcePolicyConfigError(
            "the source registry declares schema_version %r; this build "
            "understands %r. A registry written against another schema is "
            "refused rather than half-read."
            % (schema_version, SOURCE_REGISTRY_SCHEMA_VERSION))

    sources = payload.get("sources")
    if not isinstance(sources, list):
        raise SourcePolicyConfigError(
            "the source registry must carry a 'sources' array")

    records: List[SourcePolicyRecord] = []
    for index, item in enumerate(sources):
        records.append(SourcePolicyRecord.from_json(item, "sources[%d]" % index))

    conflicts_payload = payload.get("conflicts") or []
    if not isinstance(conflicts_payload, list):
        raise SourcePolicyConfigError(
            "'conflicts' must be an array when present")
    conflicts = tuple(
        SourceConflict.from_json(item, "conflicts[%d]" % index)
        for index, item in enumerate(conflicts_payload))

    return SourcePolicyRegistry(
        records=tuple(records),
        conflicts=conflicts,
        schema_version=SOURCE_REGISTRY_SCHEMA_VERSION,
        generated_note=payload.get("generated_note"),
        policy_owner=payload.get("policy_owner"),
        source_path=source_path,
    )


def load_registry(path: Optional[str] = None) -> SourcePolicyRegistry:
    """Read and validate the registry file.

    Args:
        path: registry file to read. Defaults to the checked-in
            ``config/scientific-sources.json``.

    Raises:
        SourcePolicyConfigError: the file is missing, unreadable, or not JSON.
            Never degraded to an empty registry - "the policy file would not
            open" and "no source is restricted" must not produce the same
            behaviour.
    """
    resolved = path or default_config_path()
    try:
        with io.open(resolved, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise SourcePolicyConfigError(
            "cannot read the source registry at %s: %s" % (resolved, exc)) from exc
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise SourcePolicyConfigError(
            "the source registry at %s is not valid JSON: %s" % (resolved, exc)) from exc
    return registry_from_json(payload, source_path=resolved)


def render_registry(registry: SourcePolicyRegistry) -> str:
    """Render a registry back to the file's canonical text form.

    Two spaces of indent, keys in the order :meth:`SourcePolicyRegistry.to_json`
    produces, one trailing newline. Rendering a registry that was loaded from
    disk reproduces the file, so a caller can check the checked-in file is in
    canonical form.
    """
    return json.dumps(registry.to_json(), indent=2, ensure_ascii=False) + "\n"


def source_keys_referenced_by(records: Sequence[SourcePolicyRecord]) -> Tuple[str, ...]:
    """Utility: the sorted, duplicate-free key set of a record sequence."""
    return tuple(sorted({record.source_key for record in records}))
