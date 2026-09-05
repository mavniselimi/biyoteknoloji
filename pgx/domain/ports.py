# -*- coding: utf-8 -*-
"""Repository and transaction ports (WP-02, extended by WP-03).

Standard library only. These protocols are the *only* way the domain describes
persistence. Three rules make them load-bearing rather than decorative:

1. **One port per entity.** There is no ``save(Any)``: each protocol accepts
   exactly the domain type it owns, so an evidence repository cannot be handed
   an assessment.
2. **No infrastructure types.** No SQLAlchemy ``Session``, no ORM class, and no
   connection object appears in any signature. Implementations live in
   ``pgx.infrastructure.db`` and depend on this module, never the reverse.
3. **Repositories do not commit.** Transaction control belongs to
   :class:`UnitOfWork`, so a partially written aggregate cannot be committed by
   a repository acting alone.

Because ``Protocol`` is structural, these are compile-time contracts. The
runtime half of the guarantee is implemented by the repositories themselves,
which type-check their arguments and raise
:class:`~pgx.domain.errors.RepositoryTypeError`.
"""

from __future__ import annotations

import datetime as _dt
from types import TracebackType
from typing import Optional, Protocol, Sequence, Type, runtime_checkable

from pgx.domain.enums import CurationStatus, ReleaseStatus
from pgx.domain.identifiers import (
    AssessmentId,
    ComputableRuleId,
    CuratedInterpretationId,
    DatasetVersionId,
    DrugId,
    EvidenceRecordId,
    GeneId,
    ReleaseBundleId,
    ReleasePublicId,
    RulesetVersionId,
    SoftwareVersionId,
    SourceRegistryEntryId,
)
from pgx.domain.models import (
    ActiveRelease,
    Assessment,
    AuditEvent,
    ComputableRule,
    CuratedInterpretation,
    DatasetVersion,
    Drug,
    EvidenceRecord,
    Gene,
    ReleaseBundle,
    RulesetVersion,
    SoftwareVersion,
    SourceRegistryEntry,
)

__all__ = [
    "ActiveReleaseRepository",
    "AssessmentRepository",
    "AuditEventRepository",
    "DatasetVersionRepository",
    "DrugRepository",
    "EvidenceRepository",
    "GeneRepository",
    "InterpretationRepository",
    "ReleaseBundleRepository",
    "RuleRepository",
    "RulesetVersionRepository",
    "SoftwareVersionRepository",
    "SourceRegistryRepository",
    "UnitOfWork",
]


@runtime_checkable
class SourceRegistryRepository(Protocol):
    """Persistence port for :class:`SourceRegistryEntry` only."""

    def add(self, entry: SourceRegistryEntry) -> None:
        """Stage a new source registry entry."""

    def get(self, entry_id: SourceRegistryEntryId) -> Optional[SourceRegistryEntry]:
        """Return the entry with this identity, or ``None``."""

    def get_by_source_key(self, source_key: str) -> Optional[SourceRegistryEntry]:
        """Return the entry with this unique source key, or ``None``."""

    def list_active(self) -> Sequence[SourceRegistryEntry]:
        """Return every active entry, deterministically ordered."""


@runtime_checkable
class GeneRepository(Protocol):
    """Persistence port for :class:`Gene` only."""

    def add(self, gene: Gene) -> None:
        """Stage a new gene."""

    def get(self, gene_id: GeneId) -> Optional[Gene]:
        """Return the gene with this identity, or ``None``."""

    def get_by_normalized_symbol(self, normalized_symbol: str) -> Optional[Gene]:
        """Return the gene whose canonical symbol matches, or ``None``."""

    def find_by_alias(self, normalized_alias: str) -> Sequence[Gene]:
        """Return every gene carrying this alias.

        A sequence, not a single gene: an ambiguous alias must surface as
        ambiguity for a resolution queue, never be silently resolved to the
        first match.
        """


@runtime_checkable
class DrugRepository(Protocol):
    """Persistence port for :class:`Drug` only."""

    def add(self, drug: Drug) -> None:
        """Stage a new drug."""

    def get(self, drug_id: DrugId) -> Optional[Drug]:
        """Return the drug with this identity, or ``None``."""

    def get_by_normalized_name(self, normalized_name: str) -> Optional[Drug]:
        """Return the drug whose canonical name matches, or ``None``."""

    def find_by_alias(self, normalized_alias: str) -> Sequence[Drug]:
        """Return every drug carrying this alias; ambiguity is not resolved here."""


@runtime_checkable
class EvidenceRepository(Protocol):
    """Persistence port for :class:`EvidenceRecord` only.

    This port has no method that returns, builds, or accepts an
    :class:`Assessment` or an :class:`AssessmentFinding`. Evidence is source
    truth; turning it into a calculated result requires curation and rule
    approval first.
    """

    def add(self, record: EvidenceRecord) -> None:
        """Stage a new evidence record."""

    def get(self, record_id: EvidenceRecordId) -> Optional[EvidenceRecord]:
        """Return the evidence record with this identity, or ``None``."""

    def list_for_dataset_version(
        self, dataset_version_id: DatasetVersionId
    ) -> Sequence[EvidenceRecord]:
        """Return every evidence record belonging to a dataset version."""


@runtime_checkable
class InterpretationRepository(Protocol):
    """Persistence port for :class:`CuratedInterpretation` only."""

    def add(self, interpretation: CuratedInterpretation) -> None:
        """Stage a new curated interpretation and its evidence links."""

    def get(
        self, interpretation_id: CuratedInterpretationId
    ) -> Optional[CuratedInterpretation]:
        """Return the interpretation with this identity, or ``None``."""

    def list_by_status(self, status: CurationStatus) -> Sequence[CuratedInterpretation]:
        """Return interpretations in a given curation status."""


@runtime_checkable
class RuleRepository(Protocol):
    """Persistence port for :class:`ComputableRule` only."""

    def add(self, rule: ComputableRule) -> None:
        """Stage a new computable rule and its evidence links."""

    def get(self, rule_id: ComputableRuleId) -> Optional[ComputableRule]:
        """Return the rule with this identity, or ``None``."""

    def list_validated(self) -> Sequence[ComputableRule]:
        """Return only VALIDATED rules.

        The engine may never read DRAFT, CURATED, or DEPRECATED rules
        (``SAFETY-INV-003``), so the port exposes no method that returns them
        for execution.
        """


@runtime_checkable
class AssessmentRepository(Protocol):
    """Persistence port for :class:`Assessment` only.

    The port is defined here so the domain boundary is complete, but WP-02
    ships **no PostgreSQL implementation and no assessment table**: persisting
    an assessment requires the release registry, which is WP-03. Inventing a
    table now would imply a release identity that does not yet exist
    (``SAFETY-INV-007``).
    """

    def add(self, assessment: Assessment) -> None:
        """Stage a completed assessment."""

    def get(self, assessment_id: AssessmentId) -> Optional[Assessment]:
        """Return the assessment with this identity, or ``None``."""


# ---------------------------------------------------------------------------
# WP-03 - version registry, release bundles, active pointer, audit
# ---------------------------------------------------------------------------


@runtime_checkable
class SoftwareVersionRepository(Protocol):
    """Persistence port for :class:`SoftwareVersion` only."""

    def add(self, software_version: SoftwareVersion) -> None:
        """Stage a newly registered build."""

    def get(self, software_version_id: SoftwareVersionId) -> Optional[SoftwareVersion]:
        """Return the build with this identity, or ``None``."""

    def get_by_source_tree_hash(self, source_tree_hash: str) -> Optional[SoftwareVersion]:
        """Return the build with this source tree digest, or ``None``.

        The lookup key for idempotent registration: the same source tree is the
        same build, whatever version string it declares.
        """

    def list_all(self) -> Sequence[SoftwareVersion]:
        """Return every registered build, deterministically ordered."""


@runtime_checkable
class DatasetVersionRepository(Protocol):
    """Persistence port for :class:`DatasetVersion` only."""

    def add(self, dataset_version: DatasetVersion) -> None:
        """Stage a new dataset version."""

    def get(self, dataset_version_id: DatasetVersionId) -> Optional[DatasetVersion]:
        """Return the dataset version with this identity, or ``None``."""

    def get_by_public_id(self, public_id: str) -> Optional[DatasetVersion]:
        """Return the dataset version with this public identifier, or ``None``."""


@runtime_checkable
class RulesetVersionRepository(Protocol):
    """Persistence port for :class:`RulesetVersion` only, membership included.

    :meth:`add` stores the pinned membership alongside the ruleset row, and
    :meth:`get` returns it. Membership that could be loaded separately - or
    forgotten - would let a release cite a ruleset whose contents nobody
    recorded.
    """

    def add(self, ruleset_version: RulesetVersion) -> None:
        """Stage a new ruleset version together with its pinned membership."""

    def get(self, ruleset_version_id: RulesetVersionId) -> Optional[RulesetVersion]:
        """Return the ruleset version and its membership, or ``None``."""

    def get_by_public_id(self, public_id: str) -> Optional[RulesetVersion]:
        """Return the ruleset version with this public identifier, or ``None``."""


@runtime_checkable
class ReleaseBundleRepository(Protocol):
    """Persistence port for :class:`ReleaseBundle` only.

    :meth:`set_status` exists instead of a general update because a release's
    *content* is immutable: the pinned triple, the manifest and the digest never
    change after registration. Status and activation metadata are the only
    mutable part, and they move only through the release service.
    """

    def add(self, release: ReleaseBundle) -> None:
        """Stage a newly registered release bundle."""

    def get(self, release_id: ReleaseBundleId) -> Optional[ReleaseBundle]:
        """Return the release bundle with this identity, or ``None``."""

    def get_by_public_id(self, public_id: ReleasePublicId) -> Optional[ReleaseBundle]:
        """Return the release bundle with this public identifier, or ``None``."""

    def set_status(
        self,
        release_id: ReleaseBundleId,
        status: ReleaseStatus,
        activated_at: Optional[_dt.datetime] = None,
        activated_by: Optional[str] = None,
    ) -> None:
        """Move a release's lifecycle status, leaving its pinned content alone."""

    def list_all(self) -> Sequence[ReleaseBundle]:
        """Return every release bundle, deterministically ordered."""


@runtime_checkable
class ActiveReleaseRepository(Protocol):
    """Persistence port for the singleton :class:`ActiveRelease` pointer.

    Three methods, and the split between the first two is the whole point:

    * :meth:`get` reads the pointer without locking - safe for reporting;
    * :meth:`get_for_update` reads it **and takes a row lock**, so a concurrent
      activation blocks until this transaction ends;
    * :meth:`update` writes the new pointer, but only if the pointer is still
      at ``expected_generation``.

    Locking alone would be enough on PostgreSQL. The generation check is kept
    as well so a lost update is *detectable* rather than merely unlikely, and so
    the same contract can be honoured by a store with weaker locking.
    """

    def get(self) -> ActiveRelease:
        """Return the current pointer without locking."""

    def get_for_update(self) -> ActiveRelease:
        """Return the current pointer, holding a row lock until the transaction ends."""

    def update(self, pointer: ActiveRelease, expected_generation: int) -> None:
        """Write the new pointer, or raise if the generation moved underneath."""


@runtime_checkable
class AuditEventRepository(Protocol):
    """Append-only persistence port for :class:`AuditEvent`.

    There is deliberately **no** ``update`` and **no** ``delete``. That absence
    is the contract: an audit trail that can be rewritten answers no question
    worth asking. A test asserts that this protocol never grows one, and the
    migration installs a database trigger that refuses both as well, so the
    guarantee does not rest on application code alone.
    """

    def append(self, event: AuditEvent) -> None:
        """Stage one new audit event."""

    def list_for_object(self, object_type: str, object_id: str) -> Sequence[AuditEvent]:
        """Return every event about one object, oldest first."""

    def list_recent(self, limit: int = 100) -> Sequence[AuditEvent]:
        """Return the most recent events, newest first."""


@runtime_checkable
class UnitOfWork(Protocol):
    """Transaction boundary.

    Repositories stage work; only the unit of work commits or rolls it back.
    Exiting the context without an explicit :meth:`commit` must roll back, so a
    forgotten commit can never leave a half-written aggregate behind.
    """

    source_registry: SourceRegistryRepository
    genes: GeneRepository
    drugs: DrugRepository
    evidence: EvidenceRepository
    interpretations: InterpretationRepository
    rules: RuleRepository
    software_versions: SoftwareVersionRepository
    dataset_versions: DatasetVersionRepository
    ruleset_versions: RulesetVersionRepository
    releases: ReleaseBundleRepository
    active_release: ActiveReleaseRepository
    audit: AuditEventRepository

    def __enter__(self) -> "UnitOfWork":
        """Begin a transaction."""

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        """Roll back unless :meth:`commit` was called."""

    def commit(self) -> None:
        """Commit the staged work after validating cross-row invariants."""

    def rollback(self) -> None:
        """Discard the staged work."""
