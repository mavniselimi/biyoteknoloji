# -*- coding: utf-8 -*-
"""Dataset build start: snapshot policy, sealing and registration (WP-06).

Standard library, the domain, WP-05 source policy and
:mod:`pgx.ingestion.snapshots`. No SQLAlchemy import appears here, and a test
asserts it never will: the rules below are the part of this work package that
most needs exercising without a database.

**The lifecycle distinction this module exists to keep.** Six things are often
called "publishing a dataset", and only the first three belong to WP-06:

1. building a snapshot in a staging directory;
2. sealing it with an atomic rename into its final path;
3. registering a ``DatasetVersion`` in ``BUILDING``;
4. quality-checking the dataset - WP-07;
5. moving the dataset to ``PUBLISHED`` - requires 4 and a human approval;
6. activating a release - WP-03 plus everything above.

This module performs 1 to 3 and nothing after. There is no method that sets
``QUALITY_CHECKED``, none that sets ``PUBLISHED``, and none that writes
``approved_by`` or ``approved_at``. A snapshot directory being "published" into
its final location is a *filesystem* transition and says nothing about the
dataset's scientific status.

**Two resources, one operation, no shared transaction.** Sealing a directory
and committing a database row cannot be one atomic act. The order is chosen so
the surviving state is always the safe one: the snapshot is sealed and
verified *first*, then registered. If registration fails, the sealed snapshot
stays exactly where it is and the result says
``SEALED_UNREGISTERED`` - which an operator can retry with ``register``. The
snapshot is never deleted to tidy up a failed registration, because deleting
verified immutable evidence to make a status line look neat is the wrong trade
in every direction.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from pgx.domain.enums import AuditAction, DatasetStatus
from pgx.domain.identifiers import AuditEventId, DatasetPublicId, DatasetVersionId
from pgx.domain.models import AuditEvent, DatasetVersion
from pgx.domain.ports import UnitOfWork
from pgx.ingestion.snapshots import (
    SnapshotBuildRequest,
    SnapshotBuildResult,
    SnapshotIssue,
    SnapshotIssueCode,
    SnapshotKind,
    SnapshotManager,
    SnapshotManifest,
    SnapshotVerificationResult,
)
from pgx.application.snapshot_schema import validate_snapshot_manifest
from pgx.scientific.errors import ScientificGovernanceError
from pgx.scientific.models import ReuseDimension, ReusePermission
from pgx.scientific.publication_gate import PublicationIntent, evaluate_publication

__all__ = [
    "DatasetBuildResult",
    "DatasetService",
    "RegistrationOutcome",
    "SnapshotPolicyDecision",
    "evaluate_snapshot_policy",
]


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


class RegistrationOutcome(str, Enum):
    """What happened to the database half of a dataset build.

    ``SEALED_UNREGISTERED`` is a real, reportable state rather than an error to
    be hidden. It says the immutable evidence exists and the row does not, and
    it is what an operator retries.
    """

    REGISTERED = "REGISTERED"
    ALREADY_REGISTERED = "ALREADY_REGISTERED"
    SEALED_UNREGISTERED = "SEALED_UNREGISTERED"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"

    def __str__(self) -> str:
        return self.value


#: Reuse dimensions a raw snapshot touches by existing at all. Storing bytes on
#: project-controlled storage is the whole operation, so this one is checked by
#: name rather than being left to the general publication gate.
SNAPSHOT_STORAGE_DIMENSION = ReuseDimension.LOCAL_STORAGE


@dataclass(frozen=True)
class SnapshotPolicyDecision:
    """Whether WP-05 permits this snapshot, and the full gate result behind it.

    ``gate`` is the complete
    :class:`~pgx.scientific.publication_gate.PublicationEligibility` document,
    stored in the manifest whatever the decision was. A sealed snapshot must
    never look publication-eligible on its own, so recording the gate's actual
    answer - almost always ``BLOCKED`` today - is what keeps the manifest
    honest.
    """

    permitted: bool
    issues: Tuple[SnapshotIssue, ...]
    gate: Optional[Mapping[str, Any]] = None
    policy_status: Optional[str] = None
    policy_content_hash: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "permitted": self.permitted,
            "policy_status": self.policy_status,
            "policy_content_hash": self.policy_content_hash,
            "issues": [issue.to_json() for issue in self.issues],
            "gate": dict(self.gate) if self.gate is not None else None,
        }


def evaluate_snapshot_policy(
    registry: Any,
    source_key: str,
    snapshot_kind: SnapshotKind,
    now: _dt.datetime,
) -> SnapshotPolicyDecision:
    """Decide whether WP-05 permits acquiring and storing this source's bytes.

    Two questions, kept apart because sources answer them differently:

    * may this project **store** the retrieved records at all
      (``LOCAL_STORAGE``)?
    * may they have been retrieved **by program** (``AUTOMATED_ACQUISITION``),
      which an ``ACQUISITION`` or ``CACHE_REPLAY`` snapshot implies?

    Fail-closed: ``UNKNOWN``, ``RESTRICTED``, ``PROHIBITED``, an unregistered
    source, an unapproved one, an expired review and a registry that will not
    load all block. A legacy import is not gated here - it is quarantined
    instead, because the question "were we allowed to fetch this?" has no
    answer for bytes whose retrieval predates the adapter.
    """
    issues: List[SnapshotIssue] = []
    if registry is None:
        return SnapshotPolicyDecision(False, (SnapshotIssue(
            SnapshotIssueCode.SOURCE_POLICY_UNAVAILABLE,
            "no source policy registry is configured; an absent policy is not "
            "an absence of restrictions", source_key),))

    try:
        record = registry.get(source_key)
    except ScientificGovernanceError as exc:
        return SnapshotPolicyDecision(False, (SnapshotIssue(
            SnapshotIssueCode.SOURCE_POLICY_UNAVAILABLE,
            "the source policy could not be read: %s" % exc, source_key),))

    intent = PublicationIntent(
        dataset_key=source_key,
        source_keys=(source_key,),
        automated_acquisition=snapshot_kind in (SnapshotKind.ACQUISITION,
                                                SnapshotKind.CACHE_REPLAY))
    gate = evaluate_publication(registry, intent, now)

    if record is None:
        issues.append(SnapshotIssue(
            SnapshotIssueCode.SOURCE_POLICY_BLOCKED,
            "the source has no policy record. An unregistered source has no "
            "permissions, not unlimited ones.", source_key))
        return SnapshotPolicyDecision(False, tuple(issues), gate.to_json(),
                                      None, gate.registry_content_hash)

    effective = record.effective_status(now)
    if not record.is_approved or effective.value not in ("APPROVED",
                                                         "APPROVED_WITH_RESTRICTIONS"):
        issues.append(SnapshotIssue(
            SnapshotIssueCode.SOURCE_POLICY_BLOCKED,
            "the source policy is %s; no named human has approved acquiring or "
            "storing this source's records" % effective.value, source_key))
    if not record.active:
        issues.append(SnapshotIssue(
            SnapshotIssueCode.SOURCE_POLICY_BLOCKED,
            "the source is marked inactive", source_key))

    storage = record.reuse.permission(SNAPSHOT_STORAGE_DIMENSION)
    if storage is not ReusePermission.ALLOWED:
        issues.append(SnapshotIssue(
            SnapshotIssueCode.STORAGE_NOT_PERMITTED,
            "LOCAL_STORAGE is %s. A snapshot keeps the source's bytes on "
            "project storage; an unanswered permission blocks exactly as a "
            "refusal does." % storage.value, source_key))

    if intent.automated_acquisition:
        automated = record.reuse.permission(ReuseDimension.AUTOMATED_ACQUISITION)
        if automated is not ReusePermission.ALLOWED:
            issues.append(SnapshotIssue(
                SnapshotIssueCode.ACQUISITION_NOT_PERMITTED,
                "AUTOMATED_ACQUISITION is %s, but this snapshot's bytes were "
                "retrieved by program" % automated.value, source_key))

    return SnapshotPolicyDecision(
        permitted=not issues,
        issues=tuple(issues),
        gate=gate.to_json(),
        policy_status=effective.value,
        policy_content_hash=gate.registry_content_hash)


@dataclass(frozen=True)
class DatasetBuildResult:
    """The whole outcome: the filesystem half and the database half.

    Both halves are reported, always. A result that said only "ok" would hide
    the one case an operator must act on - a sealed snapshot with no row.
    """

    dataset_public_id: str
    snapshot: SnapshotBuildResult
    registration: RegistrationOutcome = RegistrationOutcome.NOT_ATTEMPTED
    dataset_status: Optional[str] = None
    issues: Tuple[SnapshotIssue, ...] = ()
    verification: Optional[SnapshotVerificationResult] = None

    @property
    def ok(self) -> bool:
        return self.snapshot.sealed and not self.issues

    def to_json(self) -> Dict[str, Any]:
        return {
            "dataset_public_id": self.dataset_public_id,
            "snapshot": self.snapshot.to_json(),
            "registration": self.registration.value,
            "dataset_status": self.dataset_status,
            "verification": (self.verification.to_json()
                             if self.verification is not None else None),
            "issues": [issue.to_json() for issue in self.issues],
        }


class DatasetService:
    """Builds snapshots, registers dataset builds, and does nothing after that.

    Args:
        manager: the snapshot manager owning the raw root.
        uow_factory: returns a fresh unit of work. Optional: building and
            verifying a snapshot need no database, and a deployment that has
            not provisioned one can still produce and check evidence.
        clock: returns the current UTC instant. Injected so a test can pin the
            manifest's creation time and compare builds byte for byte.
        new_dataset_id / new_event_id: mint identities. Injected so audit
            records are assertable.
        source_policy: returns the WP-05 registry. Defaults to the reviewed
            file loader; a test passes a synthetic approved registry.
    """

    def __init__(
        self,
        manager: SnapshotManager,
        uow_factory: Optional[Callable[[], UnitOfWork]] = None,
        clock: Callable[[], _dt.datetime] = _utc_now,
        new_dataset_id: Callable[[], DatasetVersionId] = DatasetVersionId.new,
        new_event_id: Callable[[], AuditEventId] = AuditEventId.new,
        source_policy: Optional[Callable[[], object]] = None,
        schema_validator: Optional[Callable[..., Any]] = validate_snapshot_manifest,
    ) -> None:
        self._manager = manager
        self._schema_validator = schema_validator
        self._uow_factory = uow_factory
        self._clock = clock
        self._new_dataset_id = new_dataset_id
        self._new_event_id = new_event_id
        self._source_policy = source_policy

    @property
    def manager(self) -> SnapshotManager:
        return self._manager

    # -- building ------------------------------------------------------------

    def build_from_run(
        self,
        dataset_public_id: str,
        source_key: str,
        acquisition_manifest,
        cache,
        snapshot_kind: SnapshotKind = SnapshotKind.ACQUISITION,
        limitations: Tuple[str, ...] = (),
    ) -> DatasetBuildResult:
        """Seal a snapshot from a revalidated acquisition run.

        The WP-05 gate runs *before* any byte is written. A source this project
        may not store is a source whose bytes must not land on disk in the
        first place, so the check cannot be a post-hoc flag on the manifest.
        """
        now = self._clock()
        registry = self._load_policy()
        decision = evaluate_snapshot_policy(registry, source_key, snapshot_kind, now)
        if not decision.permitted:
            return DatasetBuildResult(
                dataset_public_id,
                SnapshotBuildResult(dataset_public_id, None, None, False,
                                    decision.issues),
                RegistrationOutcome.NOT_ATTEMPTED, None, decision.issues)

        request = SnapshotBuildRequest(
            dataset_public_id=dataset_public_id,
            source_key=source_key,
            snapshot_kind=snapshot_kind,
            acquisition_manifest=acquisition_manifest,
            cache=cache,
            limitations=limitations,
            source_policy_status=decision.policy_status,
            source_policy_content_hash=decision.policy_content_hash,
            publication_gate=decision.gate)
        built = self._manager.build(request)
        return DatasetBuildResult(dataset_public_id, built,
                                  RegistrationOutcome.NOT_ATTEMPTED, None,
                                  built.issues)

    def import_legacy(
        self,
        dataset_public_id: str,
        source_key: str,
        legacy_source_dir: str,
        limitations: Tuple[str, ...],
        legacy_origin: Mapping[str, Any],
    ) -> DatasetBuildResult:
        """Package a legacy output directory as a quarantined snapshot.

        Not gated by the acquisition policy, and deliberately so: asking "were
        we permitted to fetch this?" of bytes whose retrieval predates the
        adapter has no honest answer. The snapshot is ``QUARANTINED`` and
        permanently non-publication-eligible instead, and the unknown policy
        state is recorded as a limitation rather than resolved by assumption.
        """
        request = SnapshotBuildRequest(
            dataset_public_id=dataset_public_id,
            source_key=source_key,
            snapshot_kind=SnapshotKind.LEGACY_IMPORT,
            legacy_source_dir=legacy_source_dir,
            legacy_origin=legacy_origin,
            limitations=limitations)
        built = self._manager.build(request)
        return DatasetBuildResult(dataset_public_id, built,
                                  RegistrationOutcome.NOT_ATTEMPTED, None,
                                  built.issues)

    # -- registration ---------------------------------------------------------

    def register(
        self,
        source_key: str,
        dataset_public_id: str,
        actor: str,
        reason: Optional[str] = None,
    ) -> DatasetBuildResult:
        """Verify a sealed snapshot and register it as a ``BUILDING`` dataset.

        The order is verify-then-register, never the reverse. Registering first
        would create a row pointing at evidence nobody had checked, and the row
        would outlive the discovery that the evidence was corrupt.

        The dataset is created in ``BUILDING`` with no ``approved_by`` and no
        ``approved_at``. Nothing in this method can produce any other status.
        """
        if not actor or not actor.strip():
            raise ValueError("an actor is required: an audit event that does "
                             "not say who acted answers half the question")
        DatasetPublicId(dataset_public_id)
        snapshot_path = self._manager.snapshot_path(source_key, dataset_public_id)
        verification = self._manager.verify(source_key, dataset_public_id,
                                            schema_validator=self._schema_validator)
        stub = SnapshotBuildResult(dataset_public_id, snapshot_path,
                                   verification.manifest,
                                   verification.manifest is not None, ())
        if not verification.ok:
            return DatasetBuildResult(
                dataset_public_id, stub, RegistrationOutcome.SEALED_UNREGISTERED,
                None, verification.issues, verification)

        if self._uow_factory is None:
            return DatasetBuildResult(
                dataset_public_id, stub, RegistrationOutcome.SEALED_UNREGISTERED,
                None,
                (SnapshotIssue(
                    SnapshotIssueCode.FINALIZE_FAILED,
                    "no database is configured, so the snapshot is sealed and "
                    "verified but not registered. The snapshot is kept; retry "
                    "registration when a database is available.",
                    dataset_public_id),), verification)

        manifest = verification.manifest
        try:
            with self._uow_factory() as uow:
                existing = uow.dataset_versions.get_by_public_id(dataset_public_id)
                if existing is not None:
                    return DatasetBuildResult(
                        dataset_public_id, stub,
                        RegistrationOutcome.ALREADY_REGISTERED,
                        existing.status.value, (), verification)

                now = self._clock()
                dataset = DatasetVersion(
                    id=self._new_dataset_id(),
                    public_id=DatasetPublicId(dataset_public_id),
                    status=DatasetStatus.BUILDING,
                    manifest_hash=manifest.manifest_hash,
                    created_at=now)
                uow.dataset_versions.add(dataset)
                uow.audit.append(AuditEvent(
                    id=self._new_event_id(),
                    action=AuditAction.DATASET_BUILD_REGISTERED,
                    actor=actor,
                    object_type="dataset_version",
                    object_id=dataset_public_id,
                    occurred_at=now,
                    reason=reason,
                    metadata=_registration_metadata(manifest, snapshot_path)))
                uow.commit()
        except Exception as exc:  # noqa: BLE001 - any storage failure
            return DatasetBuildResult(
                dataset_public_id, stub, RegistrationOutcome.SEALED_UNREGISTERED,
                None,
                (SnapshotIssue(
                    SnapshotIssueCode.FINALIZE_FAILED,
                    "the snapshot is sealed and verified, but registering it "
                    "failed: %s. The snapshot has been kept exactly as it is; "
                    "retry registration." % exc, dataset_public_id),),
                verification)

        return DatasetBuildResult(
            dataset_public_id, stub, RegistrationOutcome.REGISTERED,
            DatasetStatus.BUILDING.value, (), verification)

    # -- inspection ------------------------------------------------------------

    def status(self, source_key: str, dataset_public_id: str) -> Dict[str, Any]:
        """Report both halves without changing either.

        Safe to run repeatedly. It never creates, re-seals or re-registers
        anything: a status command that could change state would be the one an
        operator ran by reflex during an incident.
        """
        path = self._manager.snapshot_path(source_key, dataset_public_id)
        sealed = self._manager.exists(source_key, dataset_public_id)
        manifest: Optional[SnapshotManifest] = None
        if sealed:
            try:
                manifest = self._manager.inspect(source_key, dataset_public_id)
            except Exception:  # noqa: BLE001 - reported as unreadable below
                manifest = None
        registered = None
        dataset_status = None
        if self._uow_factory is not None:
            try:
                with self._uow_factory() as uow:
                    existing = uow.dataset_versions.get_by_public_id(
                        dataset_public_id)
                registered = existing is not None
                dataset_status = existing.status.value if existing else None
            except Exception:  # noqa: BLE001 - a database outage is reportable
                registered = None
        return {
            "dataset_public_id": dataset_public_id,
            "source_key": source_key,
            "snapshot_path": path,
            "snapshot_sealed": sealed,
            "snapshot_readable": manifest is not None,
            "manifest": manifest.summary() if manifest is not None else None,
            "dataset_registered": registered,
            "dataset_status": dataset_status,
            "note": ("A sealed snapshot is raw input for WP-07. It is not a "
                     "quality-checked or published dataset, and this service "
                     "cannot make it one."),
        }

    # -- helpers ----------------------------------------------------------------

    def _load_policy(self):
        if self._source_policy is None:
            from pgx.scientific.policy import load_registry
            try:
                return load_registry()
            except ScientificGovernanceError:
                return None
        return self._source_policy()


def _registration_metadata(
    manifest: SnapshotManifest, snapshot_path: str
) -> Mapping[str, Any]:
    """Provenance recorded on the audit event.

    The snapshot's *relative* identity, not its absolute path: an audit trail
    that recorded one machine's directory layout would be unreadable on
    another.
    """
    return {
        "snapshot_kind": manifest.snapshot_kind.value,
        "snapshot_state": manifest.snapshot_state.value,
        "source_key": manifest.source_key,
        "snapshot_content_hash": manifest.snapshot_content_hash,
        "manifest_hash": manifest.manifest_hash,
        "artifact_count": manifest.artifact_count,
        "total_byte_count": manifest.total_byte_count,
        "acquisition_run_id": manifest.acquisition_run_id,
        "acquisition_status": manifest.acquisition_status,
        "source_policy_status": manifest.source_policy_status,
        "publication_eligible": manifest.publication_eligible,
        "complete": manifest.complete,
        "limitation_count": len(manifest.limitations),
        "snapshot_directory": "/".join(snapshot_path.replace("\\", "/")
                                       .rstrip("/").split("/")[-3:]),
        "scope_note": ("Registered as a dataset build only. The dataset is "
                       "BUILDING: it is not quality checked, not approved and "
                       "not published."),
    }
