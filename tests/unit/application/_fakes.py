# -*- coding: utf-8 -*-
"""An in-memory unit of work, so the release rules can be tested offline.

The release service talks to ports, never to SQLAlchemy. That is what makes
this possible: every compatibility rule, the transactional shape of activation
and the whole rollback contract can be exercised with no database, no driver
and no container.

Two behaviours are modelled deliberately rather than approximated, because the
tests that matter most are about what happens when something goes wrong:

* **Rollback is real.** The fake takes a deep snapshot on ``__enter__`` and
  restores it unless ``commit()`` was called. A fake that simply mutated a dict
  would let a "failed activation changes nothing" test pass while the real code
  left debris behind.
* **The generation guard is real.** ``update()`` raises when the pointer moved,
  exactly as the SQLAlchemy repository does.

What this fake does **not** model is row locking. ``get_for_update`` records
that it was called and returns the pointer; there is no concurrency here to
lock against. Proving that ``SELECT ... FOR UPDATE`` blocks a second
transaction requires a real PostgreSQL server, and WP-03 records that criterion
as BLOCKED rather than claiming this fake covers it.
"""

from __future__ import annotations

import copy
import datetime as _dt
from typing import Dict, List, Optional, Sequence

from pgx.domain.enums import ReleaseStatus
from pgx.domain.errors import DomainError
from pgx.domain.models import (
    ActiveRelease, AuditEvent, ComputableRule, DatasetVersion, EvidenceRecord,
    ReleaseBundle, RulesetVersion, SoftwareVersion, SourceRegistryEntry,
)

EPOCH = _dt.datetime(2026, 1, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)


class FakeStaleGenerationError(DomainError):
    """Raised when the pointer moved between reading and writing it."""


class _Store:
    """The shared in-memory database behind every unit of work."""

    def __init__(self) -> None:
        self.software: Dict[object, SoftwareVersion] = {}
        self.datasets: Dict[object, DatasetVersion] = {}
        self.rulesets: Dict[object, RulesetVersion] = {}
        self.rules: Dict[object, ComputableRule] = {}
        self.evidence: Dict[object, EvidenceRecord] = {}
        self.sources: Dict[object, SourceRegistryEntry] = {}
        self.releases: Dict[object, ReleaseBundle] = {}
        self.audit: List[AuditEvent] = []
        self.pointer = ActiveRelease(
            release_id=None, generation=0, updated_at=EPOCH,
            updated_by="system:test-bootstrap")

    def snapshot(self) -> dict:
        """Shallow-copy every container; the values themselves are immutable."""
        return {
            "software": dict(self.software),
            "datasets": dict(self.datasets),
            "rulesets": dict(self.rulesets),
            "rules": dict(self.rules),
            "evidence": dict(self.evidence),
            "sources": dict(self.sources),
            "releases": dict(self.releases),
            "audit": list(self.audit),
            "pointer": self.pointer,
        }

    def restore(self, snapshot: dict) -> None:
        """Put every container back as it was. This is what rollback means."""
        self.software = snapshot["software"]
        self.datasets = snapshot["datasets"]
        self.rulesets = snapshot["rulesets"]
        self.rules = snapshot["rules"]
        self.evidence = snapshot["evidence"]
        self.sources = snapshot["sources"]
        self.releases = snapshot["releases"]
        self.audit = snapshot["audit"]
        self.pointer = snapshot["pointer"]


class _Repo:
    def __init__(self, store: _Store) -> None:
        self._store = store


class FakeSoftwareVersionRepository(_Repo):
    def add(self, software_version: SoftwareVersion) -> None:
        self._store.software[software_version.id] = software_version

    def get(self, software_version_id) -> Optional[SoftwareVersion]:
        return self._store.software.get(software_version_id)

    def get_by_source_tree_hash(self, source_tree_hash: str) -> Optional[SoftwareVersion]:
        for item in self._store.software.values():
            if item.source_tree_hash == source_tree_hash:
                return item
        return None

    def list_all(self) -> Sequence[SoftwareVersion]:
        return sorted(self._store.software.values(), key=lambda item: str(item.id))


class FakeDatasetVersionRepository(_Repo):
    def add(self, dataset_version: DatasetVersion) -> None:
        self._store.datasets[dataset_version.id] = dataset_version

    def get(self, dataset_version_id) -> Optional[DatasetVersion]:
        return self._store.datasets.get(dataset_version_id)

    def get_by_public_id(self, public_id) -> Optional[DatasetVersion]:
        for item in self._store.datasets.values():
            if str(item.public_id) == str(public_id):
                return item
        return None


class FakeRulesetVersionRepository(_Repo):
    def add(self, ruleset_version: RulesetVersion) -> None:
        self._store.rulesets[ruleset_version.id] = ruleset_version

    def get(self, ruleset_version_id) -> Optional[RulesetVersion]:
        return self._store.rulesets.get(ruleset_version_id)

    def get_by_public_id(self, public_id) -> Optional[RulesetVersion]:
        for item in self._store.rulesets.values():
            if str(item.public_id) == str(public_id):
                return item
        return None


class FakeRuleRepository(_Repo):
    def add(self, rule: ComputableRule) -> None:
        self._store.rules[rule.id] = rule

    def get(self, rule_id) -> Optional[ComputableRule]:
        return self._store.rules.get(rule_id)

    def list_validated(self) -> Sequence[ComputableRule]:
        return [rule for rule in self._store.rules.values()
                if rule.status.value == "VALIDATED"]


class FakeEvidenceRepository(_Repo):
    def add(self, record: EvidenceRecord) -> None:
        self._store.evidence[record.id] = record

    def get(self, record_id) -> Optional[EvidenceRecord]:
        return self._store.evidence.get(record_id)

    def list_for_dataset_version(self, dataset_version_id) -> Sequence[EvidenceRecord]:
        return [item for item in self._store.evidence.values()
                if item.dataset_version_id == dataset_version_id]


class FakeSourceRegistryRepository(_Repo):
    def add(self, entry: SourceRegistryEntry) -> None:
        self._store.sources[entry.id] = entry

    def get(self, entry_id) -> Optional[SourceRegistryEntry]:
        return self._store.sources.get(entry_id)

    def get_by_source_key(self, source_key: str) -> Optional[SourceRegistryEntry]:
        for item in self._store.sources.values():
            if item.source_key == source_key:
                return item
        return None

    def list_active(self) -> Sequence[SourceRegistryEntry]:
        return [item for item in self._store.sources.values() if item.active]


class FakeReleaseBundleRepository(_Repo):
    def add(self, release: ReleaseBundle) -> None:
        self._store.releases[release.id] = release

    def get(self, release_id) -> Optional[ReleaseBundle]:
        return self._store.releases.get(release_id)

    def get_by_public_id(self, public_id) -> Optional[ReleaseBundle]:
        for item in self._store.releases.values():
            if str(item.public_id) == str(public_id):
                return item
        return None

    def set_status(self, release_id, status, activated_at=None,
                   activated_by=None) -> None:
        """Replace the row with a new value carrying the new status.

        Domain objects are frozen, so "mutating" one means constructing the
        next value - which also means the domain's own lifecycle invariants
        run on every status change, exactly as they would through a mapper.
        """
        import dataclasses

        current = self._store.releases[release_id]
        changes = {"status": status}
        if activated_at is not None:
            changes["activated_at"] = activated_at
        if activated_by is not None:
            changes["activated_by"] = activated_by
        self._store.releases[release_id] = dataclasses.replace(current, **changes)

    def list_all(self) -> Sequence[ReleaseBundle]:
        return sorted(self._store.releases.values(),
                      key=lambda item: str(item.public_id))


class FakeActiveReleaseRepository(_Repo):
    """The pointer, with a real generation guard and a recorded lock call."""

    def __init__(self, store: _Store) -> None:
        super().__init__(store)
        self.lock_calls = 0

    def get(self) -> ActiveRelease:
        return self._store.pointer

    def get_for_update(self) -> ActiveRelease:
        # Locking cannot be modelled in-process. The call is counted so a test
        # can assert the service asked for the lock before mutating; whether
        # the lock actually blocks anything is a PostgreSQL question.
        self.lock_calls += 1
        return self._store.pointer

    def update(self, pointer: ActiveRelease, expected_generation: int) -> None:
        if self._store.pointer.generation != expected_generation:
            raise FakeStaleGenerationError(
                "pointer moved: expected generation %d, found %d"
                % (expected_generation, self._store.pointer.generation))
        self._store.pointer = pointer


class FakeAuditEventRepository(_Repo):
    """Append-only, like the real one: no update, no delete."""

    def append(self, event: AuditEvent) -> None:
        self._store.audit.append(event)

    def list_for_object(self, object_type: str, object_id: str) -> Sequence[AuditEvent]:
        return [event for event in self._store.audit
                if event.object_type == object_type and event.object_id == object_id]

    def list_recent(self, limit: int = 100) -> Sequence[AuditEvent]:
        return list(reversed(self._store.audit))[:limit]


class FakeUnitOfWork:
    """In-memory unit of work with real rollback-unless-committed semantics."""

    def __init__(self, store: _Store) -> None:
        self._store = store
        self._snapshot = None
        self.committed = False
        self.rolled_back = False

    def __enter__(self) -> "FakeUnitOfWork":
        self._snapshot = self._store.snapshot()
        self.committed = False
        self.rolled_back = False
        self.software_versions = FakeSoftwareVersionRepository(self._store)
        self.dataset_versions = FakeDatasetVersionRepository(self._store)
        self.ruleset_versions = FakeRulesetVersionRepository(self._store)
        self.rules = FakeRuleRepository(self._store)
        self.evidence = FakeEvidenceRepository(self._store)
        self.source_registry = FakeSourceRegistryRepository(self._store)
        self.releases = FakeReleaseBundleRepository(self._store)
        self.active_release = FakeActiveReleaseRepository(self._store)
        self.audit = FakeAuditEventRepository(self._store)
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if not self.committed:
            self.rollback()

    def commit(self) -> None:
        self.committed = True
        self._snapshot = None

    def rollback(self) -> None:
        if self._snapshot is not None:
            self._store.restore(self._snapshot)
            self._snapshot = None
        self.rolled_back = True


class FakeWorld:
    """A store plus a factory, which is all the service needs."""

    def __init__(self) -> None:
        self.store = _Store()
        self.units: list = []

    def factory(self) -> FakeUnitOfWork:
        unit = FakeUnitOfWork(self.store)
        self.units.append(unit)
        return unit
