# -*- coding: utf-8 -*-
"""Persistence ports for source governance (WP-05).

Standard library plus :mod:`pgx.scientific.models` only. The same three rules
that govern :mod:`pgx.domain.ports` apply here, for the same reasons:

1. **One port per record type.** No ``save(Any)``: a review repository cannot
   be handed a conflict.
2. **No infrastructure types.** No session, no ORM class, no connection appears
   in any signature. Implementations depend on this module, never the reverse.
3. **Repositories do not commit.** Transaction control stays with the unit of
   work that owns it.

**Why these ports exist at all when the policy lives in a file.** The registry
file is where a policy is *decided*, in version control, with an author against
the change. These ports describe the *operational record*: which policy content
hash was in force when a dataset was published, which review was cited, which
conflicts were open at the time. That record has to survive in the database
next to the release it justifies, because a release whose justification lives
only in a working tree is a release nobody can audit later.

**No mutation, by omission.** There is no ``update`` and no ``delete`` on the
review or evaluation ports. A review decision that could be edited after the
fact is not evidence of anything; a superseding decision is a new record.
"""

from __future__ import annotations

import datetime as _dt
from typing import Optional, Protocol, Sequence, runtime_checkable

from pgx.scientific.models import (
    SourceConflict,
    SourcePolicyRecord,
)
from pgx.scientific.publication_gate import PublicationEligibility

__all__ = [
    "PublicationEvaluationRepository",
    "SourceConflictRepository",
    "SourcePolicyRepository",
    "SourcePolicySnapshotRepository",
]


@runtime_checkable
class SourcePolicyRepository(Protocol):
    """Persistence port for :class:`SourcePolicyRecord` only.

    ``upsert_from_registry`` takes the whole registry content rather than one
    record at a time: a policy file is reviewed and applied as a document, and
    applying half of it would leave the database asserting a policy that no
    reviewer ever saw.
    """

    def get(self, source_key: str) -> Optional[SourcePolicyRecord]:
        """Return the stored policy for this key, or ``None`` if unregistered."""

    def list_all(self) -> Sequence[SourcePolicyRecord]:
        """Return every stored policy, ordered by ``source_key``."""

    def upsert_from_registry(
        self, records: Sequence[SourcePolicyRecord], registry_content_hash: str
    ) -> None:
        """Stage the whole reviewed registry, tagged with its content digest."""


@runtime_checkable
class SourcePolicySnapshotRepository(Protocol):
    """Records which registry content was in force, and when.

    Append-only by omission: there is no ``update``. A snapshot that could be
    rewritten could not answer "what did we believe when we published this?".
    """

    def record(
        self,
        registry_content_hash: str,
        recorded_at: _dt.datetime,
        recorded_by: str,
        note: Optional[str],
    ) -> None:
        """Stage one snapshot of the registry's content digest."""

    def get_latest(self) -> Optional[str]:
        """Return the most recently recorded content digest, or ``None``."""

    def list_recent(self, limit: int) -> Sequence[str]:
        """Return recent content digests, newest first."""


@runtime_checkable
class SourceConflictRepository(Protocol):
    """Persistence port for :class:`SourceConflict` only."""

    def add(self, conflict: SourceConflict) -> None:
        """Stage a newly detected conflict."""

    def get(self, conflict_key: str) -> Optional[SourceConflict]:
        """Return the conflict with this key, or ``None``."""

    def list_open(self) -> Sequence[SourceConflict]:
        """Return every conflict no named human has settled, in key order."""

    def list_for_sources(self, source_keys: Sequence[str]) -> Sequence[SourceConflict]:
        """Return conflicts touching any of these sources, in key order."""

    def resolve(self, conflict: SourceConflict) -> None:
        """Stage a settled replacement for an existing conflict.

        Takes the whole settled record rather than a status argument: a
        resolution carries a decider, an instant and a rationale, and a method
        that accepted only a new status would let those go missing.
        """


@runtime_checkable
class PublicationEvaluationRepository(Protocol):
    """Stores the gate's verdicts so a release can cite the one it passed.

    No ``update`` and no ``delete``: a verdict is a historical fact about what
    the policy said at one instant.
    """

    def add(self, evaluation: PublicationEligibility) -> None:
        """Stage one evaluation result."""

    def get_latest_for_dataset(
        self, dataset_key: str
    ) -> Optional[PublicationEligibility]:
        """Return the newest evaluation for this dataset, or ``None``."""

    def list_recent(self, limit: int) -> Sequence[PublicationEligibility]:
        """Return recent evaluations, newest first."""
