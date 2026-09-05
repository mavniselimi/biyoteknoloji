# -*- coding: utf-8 -*-
"""Persistence ports for the evidence store (WP-08).

Standard library plus :mod:`pgx.evidence.models` only. The three rules that
govern :mod:`pgx.domain.ports`, :mod:`pgx.scientific.ports` and
:mod:`pgx.normalization.ports` apply here for the same reasons:

1. **One port per record type.** No ``save(Any)``: a publication repository
   cannot be handed a text fragment.
2. **No infrastructure types.** No session, no ORM class, no connection appears
   in any signature. Implementations depend on this module, never the reverse.
3. **Repositories do not commit.** Transaction control stays with the unit of
   work that owns it.

**Two absences are load-bearing.**

*No update and no delete on a finalized record.* An evidence record states what
a source said at a moment that has passed. Correcting it in place would make
every hash recorded against it a claim about different bytes; a corrected
source statement is a new record with a new natural key.

*No method returns a conclusion.* :meth:`EvidenceDetailRepository.trace` returns
what the source said and where it came from. There is no ``summary``, no
``risk``, no ``recommendation`` and no ``interpretation`` on any port here -
those are WP-09's and WP-11's, and a convenience method would make the evidence
layer the place people got them from.

**Ambiguity is returned, never resolved.** Every lookup that could match more
than one record returns a sequence. :meth:`get_by_natural_key` is the exception
and returns at most one - but it *raises* on finding two rather than picking
one, because two rows under a key the schema declares unique is corruption, not
a choice.
"""

from __future__ import annotations

from typing import (Any, Mapping, Optional, Protocol, Sequence,
                    runtime_checkable)

from pgx.evidence.models import (EvidenceRecordType, ImportIssue,
                                 PublicationReference, SourceTextFragment)

__all__ = [
    "EvidenceBuildRecord",
    "EvidenceBuildRepository",
    "EvidenceDetail",
    "EvidenceDetailRepository",
    "EvidenceImportIssueRepository",
    "EvidenceRecordRepository",
    "EvidenceUnitOfWork",
]


class EvidenceBuildRecord(Protocol):
    """The operational row for one sealed evidence build.

    A protocol rather than a dataclass: the fields an implementation needs are
    exactly the ones migration 0006 declares, and restating them as a second
    model here would create two definitions to keep in step.
    """

    dataset_public_id: str
    evidence_build_key: str
    content_hash: str
    snapshot_manifest_hash: str
    canonical_build_key: str
    allocation_content_hash: str
    build_relative_path: str
    mode: str
    production_eligible: bool
    record_count: int


class EvidenceDetail(Protocol):
    """Everything known about one evidence record, assembled for a reader.

    Deliberately a bundle of *source facts and provenance*. There is no field
    here that this project authored about the science.
    """

    record_uuid: str
    natural_key: str
    record_type: EvidenceRecordType
    provider_source_key: str
    origin_source_key: Optional[str]
    origin_status: str
    version_status: str
    version_value: Optional[str]
    source_payload_hash: str
    content_hash: str
    production_eligible: bool
    text_fragments: Sequence[SourceTextFragment]
    publications: Sequence[PublicationReference]
    genes: Sequence[Mapping[str, Any]]
    drugs: Sequence[Mapping[str, Any]]
    locators: Sequence[Mapping[str, Any]]
    issues: Sequence[ImportIssue]


@runtime_checkable
class EvidenceBuildRepository(Protocol):
    """Persistence port for recorded evidence builds only.

    There is no ``update`` and no ``delete``. A recorded build describes bytes
    that already exist on disk under a content hash; editing the row would make
    the row and the directory disagree.
    """

    def get_by_build_key(self, evidence_build_key: str
                         ) -> Optional[EvidenceBuildRecord]:
        """Return the recorded build with this key, or ``None``."""

    def list_for_dataset(self, dataset_public_id: str
                         ) -> Sequence[EvidenceBuildRecord]:
        """Every recorded evidence build for a dataset, newest last."""

    def add(self, record: EvidenceBuildRecord) -> None:
        """Record a sealed build. Raises if the build key already exists."""


@runtime_checkable
class EvidenceRecordRepository(Protocol):
    """Evidence records and their links.

    Every list method returns a deterministically ordered sequence, so two
    calls with the same arguments return the same rows in the same order. A
    caller that paged through an unordered result would silently skip rows.
    """

    def get(self, record_uuid: str) -> Optional[EvidenceDetail]:
        """Return one record by its allocated identity."""

    def get_by_natural_key(self, natural_key: str) -> Optional[EvidenceDetail]:
        """Return the record with this exact natural key, or ``None``.

        Implementations must **raise** when two rows share the key rather than
        returning either. The schema declares that pair unique; two rows under
        it means the store is corrupt, and returning one would hide it. This is
        also why no implementation may use ``LIMIT 1`` here - a limit turns
        corruption into a plausible-looking answer.
        """

    def list_for_build(self, evidence_build_key: str,
                       record_type: Optional[EvidenceRecordType] = None
                       ) -> Sequence[EvidenceDetail]:
        """Every record in a build, ordered by natural key."""

    def list_for_gene(self, evidence_build_key: str,
                      canonical_key: str) -> Sequence[EvidenceDetail]:
        """Every record linked to one canonical gene, ordered by natural key."""

    def list_for_drug(self, evidence_build_key: str,
                      canonical_key: str) -> Sequence[EvidenceDetail]:
        """Every record linked to one canonical drug, ordered by natural key."""

    def list_for_provider_source(self, evidence_build_key: str,
                                 provider_source_key: str
                                 ) -> Sequence[EvidenceDetail]:
        """Every record whose bytes came from one provider."""

    def list_for_origin_source(self, evidence_build_key: str,
                               origin_source_key: str
                               ) -> Sequence[EvidenceDetail]:
        """Every record whose own source field names one asserting body.

        Distinct from :meth:`list_for_provider_source`, and that distinction is
        the point: "records ClinPGx served" and "records DPWG asserted" are
        different questions with different answers.
        """

    def list_for_publication(self, evidence_build_key: str,
                             identifier: str) -> Sequence[EvidenceDetail]:
        """Every record citing one publication, addressed by PMID or DOI.

        ``identifier`` is ``pmid:<digits>`` or ``doi:<doi>``. Titles are not
        accepted: two records printing one title have not been shown to cite
        one article.
        """

    def add_all(self, evidence_build_key: str,
                records: Sequence[Any]) -> None:
        """Record a build's evidence. Raises if the build already has any."""


@runtime_checkable
class EvidenceDetailRepository(Protocol):
    """The complete raw-to-canonical trace for one record."""

    def trace(self, record_uuid: str) -> Optional[Mapping[str, Any]]:
        """Return the whole chain, or ``None`` when the record is unknown.

        The chain a caller can walk and check: evidence record → provider and
        origin source → publications → canonical genes and drugs → canonical
        build → raw record locator → raw artifact SHA-256 → raw snapshot
        manifest. Every hash in it is a different hash with a different
        meaning, and the trace names which is which.

        It returns no conclusion about the science. A caller wanting a clinical
        summary is asking the wrong layer.
        """

    def verify_trace(self, record_uuid: str, snapshot_root: str
                     ) -> Sequence[str]:
        """Re-check one record's trace against the raw bytes.

        Returns the problems found, empty when the trace holds. Six checks, in
        order: the artifact exists, its bytes hash to the recorded digest, the
        locator addresses a record inside it, that record's payload hashes to
        the recorded payload digest, the record's own content hash recomputes,
        and every linked canonical entity belongs to the recorded build.
        """


@runtime_checkable
class EvidenceImportIssueRepository(Protocol):
    """Findings raised while importing, kept beside the records they concern.

    Stored rather than logged. An issue that lived only in a log could not be
    queried when someone later asks why a record is quarantined.
    """

    def list_for_build(self, evidence_build_key: str,
                       blocking_only: bool = False) -> Sequence[ImportIssue]:
        """Every issue in a build, ordered by code and subject."""

    def list_for_record(self, record_uuid: str) -> Sequence[ImportIssue]:
        """Every issue raised against one record."""

    def add_all(self, evidence_build_key: str,
                issues: Sequence[ImportIssue]) -> None:
        """Record a build's import issues."""


@runtime_checkable
class EvidenceUnitOfWork(Protocol):
    """Transaction boundary for the evidence repositories.

    The same shape as the WP-02, WP-03 and WP-07 units of work: repositories
    are reached through it, nothing commits on its own, and leaving the context
    without committing rolls back.
    """

    builds: EvidenceBuildRepository
    records: EvidenceRecordRepository
    details: EvidenceDetailRepository
    issues: EvidenceImportIssueRepository
    audit: Any

    def __enter__(self) -> "EvidenceUnitOfWork": ...

    def __exit__(self, exc_type, exc, tb) -> None: ...

    def commit(self) -> None:
        """Commit the transaction. Never called implicitly by a repository."""

    def rollback(self) -> None:
        """Abandon the transaction."""
