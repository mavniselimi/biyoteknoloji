# -*- coding: utf-8 -*-
"""Typed domain identifiers (WP-02).

Standard library only.

Two identifier families:

* **Internal identity** - immutable UUID wrappers, one distinct type per
  entity. They are not interchangeable: handing a :class:`DrugId` to something
  expecting a :class:`GeneId` raises rather than addressing the wrong row.
* **Public identity** - the human-readable, operator-facing identifiers that
  appear in release documentation (``PGX-DATA-YYYYMMDD-NNN`` and friends).

Identifier construction never generates a random UUID as a hidden side effect.
A caller must supply the value, or call the explicit ``new()`` factory, so that
identity creation is always a visible decision. ``derive()`` produces a
deterministic UUID5 for technical, non-scientific seed rows only.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, ClassVar, Type, TypeVar

from pgx.domain.errors import (
    IdentifierTypeMismatchError,
    InvalidIdentifierError,
    InvalidPublicIdentifierError,
)

__all__ = [
    "PGX_TECHNICAL_NAMESPACE",
    "AssessmentId",
    "AuditEventId",
    "ComputableRuleId",
    "CuratedInterpretationId",
    "DatasetPublicId",
    "DatasetVersionId",
    "DrugId",
    "EntityId",
    "EvidenceRecordId",
    "GeneId",
    "PublicIdentifier",
    "ReleaseBundleId",
    "ReleasePublicId",
    "RulesetPublicId",
    "RulesetVersionId",
    "SoftwareVersionId",
    "SourceRegistryEntryId",
    "ValidationPublicId",
    "require_id",
]

#: Fixed namespace for deterministic technical identifiers. It is deliberately
#: constant so a UUID5 seed identity is reproducible across environments.
#: It carries no scientific meaning.
PGX_TECHNICAL_NAMESPACE = uuid.UUID("6f0f5f3e-0f2a-5b7a-9c1d-2e3f4a5b6c7d")

_T = TypeVar("_T", bound="EntityId")


@dataclass(frozen=True, slots=True)
class EntityId:
    """Immutable, type-distinct UUID identity.

    Subclasses are separate types on purpose. Equality holds only between
    identifiers of the same subclass with the same value, so a ``GeneId`` and a
    ``DrugId`` sharing a UUID are never equal.

    **Identity policy.** Scientific identities are random (UUID4) and are minted
    only through :meth:`new`. Deterministic UUID5 derivation is deliberately
    *not* defined here: it exists on :class:`SourceRegistryEntryId` alone, so a
    gene, drug, evidence record, rule, or assessment cannot be given a
    reproducible identity derived from a string. Two different curation runs
    that observe the same source must produce two distinct evidence records,
    not silently collide on one row.
    """

    value: uuid.UUID

    #: Human-readable label used in error messages.
    entity_name: ClassVar[str] = "entity"

    def __post_init__(self) -> None:
        if not isinstance(self.value, uuid.UUID):
            raise InvalidIdentifierError(
                "%s requires a uuid.UUID, got %r"
                % (type(self).__name__, type(self.value).__name__)
            )

    # -- construction ---------------------------------------------------

    @classmethod
    def new(cls: Type[_T]) -> _T:
        """Explicitly mint a fresh random identity.

        Random generation lives here and nowhere else: no model constructor
        creates identity implicitly.
        """
        return cls(uuid.uuid4())

    @classmethod
    def parse(cls: Type[_T], raw: str) -> _T:
        """Parse a canonical UUID string. Conversion is always explicit."""
        if not isinstance(raw, str):
            raise InvalidIdentifierError(
                "%s.parse requires a str, got %r" % (cls.__name__, type(raw).__name__))
        try:
            parsed = uuid.UUID(raw)
        except (ValueError, AttributeError, TypeError) as exc:
            raise InvalidIdentifierError(
                "%s.parse could not read %r as a UUID: %s" % (cls.__name__, raw, exc)
            ) from exc
        return cls(parsed)

    # -- representation -------------------------------------------------

    def __str__(self) -> str:
        return str(self.value)

    def to_json(self) -> str:
        """Stable string form for JSON, hashing, and transport."""
        return str(self.value)

    def __repr__(self) -> str:
        return "%s(%s)" % (type(self).__name__, self.value)


@dataclass(frozen=True, slots=True)
class SourceRegistryEntryId(EntityId):
    """Identity of a registered scientific or technical source.

    This is the **only** identifier type with deterministic derivation, because
    it is the only one a technical seed must be able to reproduce across
    environments (``scripts``/``pgx.infrastructure.db.cli_seed``).
    """

    entity_name: ClassVar[str] = "source registry entry"

    @classmethod
    def derive(cls, technical_key: str) -> "SourceRegistryEntryId":
        """Deterministic UUID5 identity for a technical bookkeeping source.

        Used only by the foundation seed, so repeated runs address the same
        row. It must never be used to mint scientific identities, and no other
        identifier class exposes it.
        """
        if not isinstance(technical_key, str) or not technical_key.strip():
            raise InvalidIdentifierError(
                "SourceRegistryEntryId.derive requires a non-empty technical key")
        return cls(uuid.uuid5(PGX_TECHNICAL_NAMESPACE, technical_key))


@dataclass(frozen=True, slots=True)
class DatasetVersionId(EntityId):
    """Identity of an immutable dataset version."""

    entity_name: ClassVar[str] = "dataset version"


@dataclass(frozen=True, slots=True)
class GeneId(EntityId):
    """Identity of a canonical gene."""

    entity_name: ClassVar[str] = "gene"


@dataclass(frozen=True, slots=True)
class DrugId(EntityId):
    """Identity of a canonical drug."""

    entity_name: ClassVar[str] = "drug"


@dataclass(frozen=True, slots=True)
class EvidenceRecordId(EntityId):
    """Identity of a single evidence record."""

    entity_name: ClassVar[str] = "evidence record"


@dataclass(frozen=True, slots=True)
class CuratedInterpretationId(EntityId):
    """Identity of a curated interpretation."""

    entity_name: ClassVar[str] = "curated interpretation"


@dataclass(frozen=True, slots=True)
class ComputableRuleId(EntityId):
    """Identity of a computable rule."""

    entity_name: ClassVar[str] = "computable rule"


@dataclass(frozen=True, slots=True)
class RulesetVersionId(EntityId):
    """Identity of a ruleset version."""

    entity_name: ClassVar[str] = "ruleset version"


@dataclass(frozen=True, slots=True)
class ReleaseBundleId(EntityId):
    """Identity of a release bundle. Activation belongs to WP-03."""

    entity_name: ClassVar[str] = "release bundle"


@dataclass(frozen=True, slots=True)
class AssessmentId(EntityId):
    """Identity of a single assessment run."""

    entity_name: ClassVar[str] = "assessment"


@dataclass(frozen=True, slots=True)
class SoftwareVersionId(EntityId):
    """Identity of a registered build of this software (WP-03).

    A release pins the software it ran under by this identity, not by a version
    string: two builds can carry the same declared version and different source
    trees, and only the identity distinguishes them.
    """

    entity_name: ClassVar[str] = "software version"


@dataclass(frozen=True, slots=True)
class AuditEventId(EntityId):
    """Identity of one append-only audit event (WP-03)."""

    entity_name: ClassVar[str] = "audit event"


def require_id(value: Any, expected: Type[_T], field: str) -> _T:
    """Return ``value`` if it is exactly ``expected``, else raise.

    ``isinstance`` is not enough here: every identifier subclasses
    :class:`EntityId`, so an exact type check is what keeps a ``DrugId`` out of
    a gene field.
    """
    if type(value) is not expected:
        raise IdentifierTypeMismatchError(
            "%s requires %s, got %s"
            % (field, expected.__name__, type(value).__name__))
    return value


# ---------------------------------------------------------------------------
# Public (human-readable) identifiers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PublicIdentifier:
    """Operator-facing identifier of the form ``PREFIX-YYYYMMDD-NNN``.

    WP-02 defines the value-object contract only. Allocating the next sequence
    number, and any activation semantics, belong to WP-03.
    """

    value: str

    prefix: ClassVar[str] = "PGX"
    _pattern: ClassVar[re.Pattern] = re.compile(r"^PGX-(\d{8})-(\d{3})$")

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise InvalidPublicIdentifierError(
                "%s requires a str, got %r" % (type(self).__name__, type(self.value).__name__))
        match = type(self)._pattern.match(self.value)
        if match is None:
            raise InvalidPublicIdentifierError(
                "%s must match %s, got %r"
                % (type(self).__name__, type(self).format_hint(), self.value))
        stamp = match.group(1)
        try:
            date(int(stamp[0:4]), int(stamp[4:6]), int(stamp[6:8]))
        except ValueError as exc:
            raise InvalidPublicIdentifierError(
                "%s carries an impossible date %r: %s" % (type(self).__name__, stamp, exc)
            ) from exc
        if match.group(2) == "000":
            raise InvalidPublicIdentifierError(
                "%s sequence must start at 001, got %r" % (type(self).__name__, self.value))

    @classmethod
    def format_hint(cls) -> str:
        """Human-readable format description used in error messages."""
        return "%s-YYYYMMDD-NNN" % cls.prefix

    @classmethod
    def compose(cls, stamp: date, sequence: int) -> "PublicIdentifier":
        """Build an identifier from a date and a 1-based sequence number."""
        if not isinstance(stamp, date):
            raise InvalidPublicIdentifierError("compose requires a datetime.date")
        if (not isinstance(sequence, int) or isinstance(sequence, bool)
                or not 1 <= sequence <= 999):
            raise InvalidPublicIdentifierError(
                "sequence must be an int in 1..999, got %r" % (sequence,))
        return cls("%s-%s-%03d" % (cls.prefix, stamp.strftime("%Y%m%d"), sequence))

    @property
    def issued_on(self) -> date:
        """The date encoded in the identifier."""
        stamp = type(self)._pattern.match(self.value).group(1)  # type: ignore[union-attr]
        return date(int(stamp[0:4]), int(stamp[4:6]), int(stamp[6:8]))

    @property
    def sequence(self) -> int:
        """The sequence number encoded in the identifier."""
        return int(type(self)._pattern.match(self.value).group(2))  # type: ignore[union-attr]

    def __str__(self) -> str:
        return self.value

    def to_json(self) -> str:
        """Stable string form for JSON, hashing, and transport."""
        return self.value


@dataclass(frozen=True, slots=True)
class DatasetPublicId(PublicIdentifier):
    """``PGX-DATA-YYYYMMDD-NNN``."""

    prefix: ClassVar[str] = "PGX-DATA"
    _pattern: ClassVar[re.Pattern] = re.compile(r"^PGX-DATA-(\d{8})-(\d{3})$")


@dataclass(frozen=True, slots=True)
class RulesetPublicId(PublicIdentifier):
    """``PGX-RULESET-YYYYMMDD-NNN``."""

    prefix: ClassVar[str] = "PGX-RULESET"
    _pattern: ClassVar[re.Pattern] = re.compile(r"^PGX-RULESET-(\d{8})-(\d{3})$")


@dataclass(frozen=True, slots=True)
class ReleasePublicId(PublicIdentifier):
    """``PGX-REL-YYYYMMDD-NNN``."""

    prefix: ClassVar[str] = "PGX-REL"
    _pattern: ClassVar[re.Pattern] = re.compile(r"^PGX-REL-(\d{8})-(\d{3})$")


@dataclass(frozen=True, slots=True)
class ValidationPublicId(PublicIdentifier):
    """``PGX-VAL-YYYYMMDD-NNN``."""

    prefix: ClassVar[str] = "PGX-VAL"
    _pattern: ClassVar[re.Pattern] = re.compile(r"^PGX-VAL-(\d{8})-(\d{3})$")
