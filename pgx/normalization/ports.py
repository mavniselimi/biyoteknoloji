# -*- coding: utf-8 -*-
"""Persistence ports for canonicalization (WP-07).

Standard library plus :mod:`pgx.normalization` models only. The same three
rules that govern :mod:`pgx.domain.ports` and :mod:`pgx.scientific.ports`
apply, for the same reasons:

1. **One port per record type.** No ``save(Any)``: a duplicate-group repository
   cannot be handed a queue item.
2. **No infrastructure types.** No session, no ORM class, no connection appears
   in any signature. Implementations depend on this module, never the reverse.
3. **Repositories do not commit.** Transaction control stays with the unit of
   work that owns it.

**Why these ports exist when the build already lives on disk.** The sealed
build directory is the artifact; these ports describe the *operational record*
of it - which build a dataset was built from, which alias proposals are waiting
for a reviewer, which ambiguities nobody has settled. That record has to be
queryable next to the dataset it describes, because "what is still unresolved"
is a question somebody asks from an application, not by reading NDJSON.

**Two absences are load-bearing.**

*No approval method.* There is no ``approve_alias``, no ``decide``, no
``mark_quality_checked``. Every one of those is a human decision, and a
convenience wrapper for one becomes the route everybody uses.
:meth:`AliasReviewRepository.record_decision` and
:meth:`ResolutionQueueRepository.record_decision` exist, and both *require* the
reviewer, the instant and the rationale as arguments - there is no signature
that lets a caller omit them, so a decision without an author cannot be
expressed, let alone stored.

*No update or delete on a recorded build.* A canonical build describes bytes
that already exist. Superseding one means recording another.

**Ambiguity is returned, never resolved.** Every lookup that could match more
than one entity returns a sequence. A port that returned an optional entity
would have had to choose between two candidates somewhere, and there would be
no place in this file to show where.
"""

from __future__ import annotations

import datetime as _dt
from typing import (Any, Mapping, Optional, Protocol, Sequence,
                    runtime_checkable)

from pgx.normalization.models import (AliasProposal, AliasStatus,
                                      CanonicalEntity, DuplicateGroup,
                                      EntityType, ResolutionQueueItem,
                                      ResolutionStatus)

__all__ = [
    "AliasReviewRepository",
    "CanonicalBuildRecord",
    "CanonicalBuildRepository",
    "CanonicalEntityRepository",
    "DatasetLifecycleRepository",
    "DuplicateGroupRepository",
    "NormalizationUnitOfWork",
    "ResolutionQueueRepository",
]


class CanonicalBuildRecord(Protocol):
    """The operational row for one sealed build.

    A protocol rather than a dataclass: the fields an implementation needs are
    exactly the ones the migration declares, and restating them as a second
    model here would create two definitions to keep in step.
    """

    dataset_public_id: str
    canonical_build_key: str
    content_hash: str
    snapshot_manifest_hash: str
    allocation_content_hash: str
    build_relative_path: str
    rule_versions: Mapping[str, Any]
    summary: Mapping[str, Any]
    dq_gate_passed: bool
    dq_blocking_codes: Sequence[str]
    built_at: _dt.datetime


@runtime_checkable
class CanonicalBuildRepository(Protocol):
    """Persistence port for recorded canonical builds only.

    There is no ``update`` and no ``delete``. A recorded build describes bytes
    that already exist on disk under a content hash; editing the row would make
    the row and the directory disagree, and the database enforces the same rule
    with a trigger so the promise does not depend on this file being obeyed.
    """

    def get_by_build_key(self, canonical_build_key: str
                         ) -> Optional[CanonicalBuildRecord]:
        """Return the recorded build with this key, or ``None``."""

    def list_for_dataset(self, dataset_public_id: str
                         ) -> Sequence[CanonicalBuildRecord]:
        """Every recorded build for a dataset, newest last."""

    def add(self, record: CanonicalBuildRecord) -> None:
        """Record a sealed build. Raises if the build key already exists."""

    def attach_quality_report(self, canonical_build_key: str,
                              dq_report_hash: str, gate_passed: bool,
                              blocking_codes: Sequence[str]) -> None:
        """Attach a DQ report to a recorded build.

        Permitted after the fact because computing quality metrics and sealing
        a directory are not one transaction. It changes no identity field, and
        recording a passing gate alongside blocking codes is refused by the
        database rather than by convention.

        Attaching a report is not an approval. It records what the gate said.
        """


@runtime_checkable
class CanonicalEntityRepository(Protocol):
    """Membership of canonical entities in a build.

    Every lookup that could match more than one entity returns a sequence -
    ``find_by_external_id`` and ``find_by_normalized_value`` included. Two
    entities sharing an external accession is an identity conflict this project
    must be able to see; a port returning one of them would hide it here, in
    the layer least likely to be read.
    """

    def get(self, canonical_build_key: str,
            canonical_key: str) -> Optional[CanonicalEntity]:
        """Return one entity by its canonical key within one build."""

    def list_for_build(self, canonical_build_key: str,
                       entity_type: Optional[EntityType] = None
                       ) -> Sequence[CanonicalEntity]:
        """Every entity in a build, ordered by canonical key."""

    def find_by_external_id(self, canonical_build_key: str,
                            namespace: str, value: str
                            ) -> Sequence[CanonicalEntity]:
        """Every entity carrying this exact namespaced identifier."""

    def find_by_normalized_value(self, canonical_build_key: str,
                                 entity_type: EntityType,
                                 normalized_value: str
                                 ) -> Sequence[CanonicalEntity]:
        """Every entity whose canonical value is exactly this."""

    def add_all(self, canonical_build_key: str,
                entities: Sequence[CanonicalEntity]) -> None:
        """Record a build's entities. Raises if the build already has any."""


@runtime_checkable
class AliasReviewRepository(Protocol):
    """Alias proposals and their review state.

    ``find_by_alias`` returns a sequence for the reason stated on
    :class:`~pgx.domain.ports.GeneRepository`: an alias belonging to two
    entities is an ambiguity for a human, and the schema deliberately carries no
    globally unique alias constraint so that it can be stored rather than
    refused.
    """

    def list_proposals(self, entity_type: EntityType,
                       status: Optional[AliasStatus] = None
                       ) -> Sequence[AliasProposal]:
        """Alias proposals, optionally filtered by review state."""

    def find_by_alias(self, entity_type: EntityType,
                      normalized_alias: str) -> Sequence[str]:
        """Every canonical key carrying this alias, whatever its status.

        A sequence, not one key. Status filtering is the caller's business,
        because "which entities claim this alias" and "which entities this
        alias resolves" are different questions and only the second one is
        restricted to approved aliases.
        """

    def add_proposals(self, entity_type: EntityType, canonical_key: str,
                      proposals: Sequence[AliasProposal]) -> None:
        """Record observed alternative names as ``PENDING_REVIEW`` proposals.

        Implementations must refuse a proposal that arrives already
        ``APPROVED``: approval is a decision, and a decision does not arrive
        through a bulk insert.
        """

    def record_decision(self, entity_type: EntityType, canonical_key: str,
                        normalized_alias: str, status: AliasStatus,
                        reviewed_by: str, reviewed_at: _dt.datetime,
                        note: str) -> None:
        """Record a human's review of one alias proposal.

        Every argument is required. There is no default reviewer, no implicit
        instant and no optional rationale, so a decision with no author cannot
        be expressed through this port at all - and the database refuses one
        that arrives by another route.
        """


@runtime_checkable
class ResolutionQueueRepository(Protocol):
    """Everything a human still has to look at."""

    def list_open(self, canonical_build_key: str,
                  status: Optional[ResolutionStatus] = None
                  ) -> Sequence[ResolutionQueueItem]:
        """Undecided queue items, optionally filtered by status."""

    def list_all(self, canonical_build_key: str
                 ) -> Sequence[ResolutionQueueItem]:
        """Every queue item for a build, decided or not."""

    def add_all(self, canonical_build_key: str,
                items: Sequence[ResolutionQueueItem]) -> None:
        """Record a build's queue. Implementations refuse decided items.

        A build produces no decisions, so an item arriving here with a reviewer
        already attached came from somewhere it should not have.
        """

    def record_decision(self, canonical_build_key: str, queue_key: str,
                        chosen_canonical_key: Optional[str],
                        decided_by: str, decided_at: _dt.datetime,
                        rationale: str) -> None:
        """Record a human's decision on one queue item.

        ``chosen_canonical_key`` may be ``None`` - "none of these" is a real
        answer - but the reviewer, the instant and the rationale are required,
        and a chosen key that was never among the candidates is refused.
        """


@runtime_checkable
class DuplicateGroupRepository(Protocol):
    """Duplicate groups and every member locator in them.

    There is no method that merges a group, drops a member or resolves a
    conflicting-identity collision. Two records claiming one identity while
    disagreeing are not reconcilable by storage: one of them is wrong, and only
    a human reading both can say which.
    """

    def list_for_build(self, canonical_build_key: str
                       ) -> Sequence[DuplicateGroup]:
        """Every duplicate group in a build, ordered by group key."""

    def list_blocking(self, canonical_build_key: str
                      ) -> Sequence[DuplicateGroup]:
        """Only the groups that block a quality check."""

    def add_all(self, canonical_build_key: str,
                groups: Sequence[DuplicateGroup]) -> None:
        """Record a build's duplicate groups with every member locator."""


@runtime_checkable
class DatasetLifecycleRepository(Protocol):
    """The one state transition WP-07 is allowed to perform.

    Declared here rather than added to the WP-02
    :class:`~pgx.domain.ports.DatasetVersionRepository`, because the transition
    is a canonicalization concern and WP-02's ports are not rewritten.

    **Only one transition exists.** ``BUILDING -> QUALITY_CHECKED``. There is no
    ``publish``, no ``activate`` and no ``retire`` here; those belong to WP-03's
    release registry and to a human, and adding one would give this package a
    route to a state it has no business setting.

    Every argument of :meth:`record_quality_check` is required. There is no
    default reviewer, no implicit instant and no optional rationale, so a
    transition with no author cannot be expressed through this port - and the
    database refuses one that arrives by another route, because
    ``ck_dataset_versions_approval_requires_reviewer`` demands an approver and
    an instant for a ``QUALITY_CHECKED`` row.
    """

    def get_status(self, dataset_public_id: str) -> Optional[str]:
        """Return the dataset's current lifecycle state, or ``None``.

        Read before the transition so the caller can require the state it
        expected. A transition that did not check would silently re-run on an
        already-checked dataset, or move one that a human had since retired.
        """

    def record_quality_check(self, dataset_public_id: str,
                             expected_current_state: str,
                             dq_report_path: str, dq_report_hash: str,
                             canonical_build_key: str,
                             reviewed_by: str, reviewed_at: _dt.datetime,
                             rationale: str) -> None:
        """Move one dataset from ``expected_current_state`` to QUALITY_CHECKED.

        Implementations must apply the state change conditionally on the
        expected state - as a guarded ``UPDATE ... WHERE status = ...``, not as
        a read followed by an unconditional write - so two concurrent callers
        cannot both believe they performed the transition.

        The DQ report path and hash are recorded with it: a dataset marked
        quality checked against a report nobody can identify is not evidence of
        a quality check.
        """


@runtime_checkable
class NormalizationUnitOfWork(Protocol):
    """Transaction boundary for the canonicalization repositories.

    The same shape as the WP-02 and WP-03 units of work: repositories are
    reached through it, nothing commits on its own, and leaving the context
    without committing rolls back. ``audit`` is the append-only port from
    WP-03; it offers ``append`` and nothing else, which is why a caller cannot
    revise an event after writing it.
    """

    builds: CanonicalBuildRepository
    entities: CanonicalEntityRepository
    aliases: AliasReviewRepository
    queue: ResolutionQueueRepository
    duplicates: DuplicateGroupRepository
    datasets: DatasetLifecycleRepository
    audit: Any

    def __enter__(self) -> "NormalizationUnitOfWork": ...

    def __exit__(self, exc_type, exc, tb) -> None: ...

    def commit(self) -> None:
        """Commit the transaction. Never called implicitly by a repository."""

    def rollback(self) -> None:
        """Abandon the transaction."""
