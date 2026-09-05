# -*- coding: utf-8 -*-
"""Synthetic actors, policies and work items for WP-10 workflow tests.

Two worlds are built here and they must not be confused.

``synthetic_policy()`` describes a world in which the protocol is APPROVED by a
named approver, the evidence build is not quarantined, and the source policy is
APPROVED. No such world exists in this repository. It exists here so that the
successful path - RAW to CURATED with every gate open - can be exercised at
all, because the alternative would be to change the real protocol's approval
state or the real build's quarantine, which the work package forbids and which
would be a lie about the science rather than a test fixture.

``real_repository_policy()`` describes the world as it actually is: protocol
AWAITING_EXPERT_REVIEW, build quarantined, no source policy approval. Tests
assert that under this policy nothing reaches CURATED.

Every actor here is prefixed ``TEST-``. That prefix is enforced by
``ActorContext`` itself: an id starting with it must declare ``synthetic=True``
and an id not starting with it must not. So a synthetic actor cannot be
mistaken for a person in an audit trail, and no name here belongs to anyone on
the project. These are not credentials and they are not authentication; WP-23
owns identity.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, Mapping, Optional, Tuple

from pgx.curation.vocabulary import CurationRole, ProtocolStatus
from pgx.curation.workflow.memory import (InMemoryWorkflowStore,
                                          InMemoryWorkflowUnitOfWork)
from pgx.curation.workflow.models import (CurationWorkItem,
                                          EvidenceSelectionSnapshot,
                                          ProvenanceVerification)
from pgx.curation.workflow.policy import WorkflowPolicy
from pgx.curation.workflow.roles import StaticRoleProvider
from pgx.curation.workflow.service import CurationWorkflowService
from pgx.domain.enums import CurationStatus

__all__ = [
    "SYNTHETIC_ACTORS",
    "SYNTHETIC_BUILD_HASH",
    "SYNTHETIC_BUILD_KEY",
    "SYNTHETIC_DATASET_ID",
    "SYNTHETIC_EVIDENCE_UUIDS",
    "SYNTHETIC_PROTOCOL_HASH",
    "SYNTHETIC_PROTOCOL_VERSION",
    "TEST_ADJUDICATOR",
    "TEST_CURATOR",
    "TEST_REVIEWER",
    "TEST_SECOND_REVIEWER",
    "TEST_STEWARD",
    "FixedClock",
    "build_service",
    "evidence_snapshot",
    "raw_work_item",
    "real_repository_policy",
    "seed_raw",
    "steward_verification",
    "synthetic_policy",
    "synthetic_role_provider",
]

TEST_CURATOR = "TEST-curator-1"
TEST_REVIEWER = "TEST-reviewer-1"
TEST_SECOND_REVIEWER = "TEST-reviewer-2"
TEST_ADJUDICATOR = "TEST-adjudicator-1"
TEST_STEWARD = "TEST-steward-1"

#: Synthetic role assignments. Each actor holds exactly one role, so a test
#: that passes because one identity happened to hold two permissions is not
#: possible here.
SYNTHETIC_ACTORS: Mapping[str, frozenset] = {
    TEST_CURATOR: frozenset({CurationRole.SCIENTIFIC_CURATOR}),
    TEST_REVIEWER: frozenset({CurationRole.INDEPENDENT_SCIENTIFIC_REVIEWER}),
    TEST_SECOND_REVIEWER:
        frozenset({CurationRole.INDEPENDENT_SCIENTIFIC_REVIEWER}),
    TEST_ADJUDICATOR: frozenset({CurationRole.ADJUDICATOR}),
    TEST_STEWARD: frozenset({CurationRole.DATA_PROVENANCE_STEWARD}),
}

#: A synthetic approved protocol. Not the real protocol hash: using the real
#: one alongside status APPROVED would produce a fixture that looks like a
#: claim about the checked-in protocol.
SYNTHETIC_PROTOCOL_VERSION = "test-protocol/9.9.9-synthetic"
#: Well-formed sha256 spellings that are obviously not real digests. They have
#: to be valid hex, because the published schemas check the spelling and a
#: fixture that failed that check would be testing the fixture rather than the
#: code. The repeated nibble makes it clear at a glance that nothing hashed to
#: this.
SYNTHETIC_PROTOCOL_HASH = "sha256:" + ("0" * 64)
SYNTHETIC_BUILD_KEY = "test-evidence-build/synthetic"
SYNTHETIC_BUILD_HASH = "sha256:" + ("1" * 64)
SYNTHETIC_DATASET_ID = "TEST-DATASET-0001"

SYNTHETIC_EVIDENCE_UUIDS: Tuple[str, ...] = (
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
)


class FixedClock:
    """A clock that advances by a fixed step on every call.

    Monotonic rather than constant: audit events must be orderable, and a
    frozen clock would make two events in one operation indistinguishable in
    time while still being distinguishable in fact.
    """

    def __init__(self, start: Optional[_dt.datetime] = None,
                 step_seconds: int = 1) -> None:
        self._now = start or _dt.datetime(2026, 1, 1, 12, 0, 0,
                                          tzinfo=_dt.timezone.utc)
        self._step = _dt.timedelta(seconds=step_seconds)

    def __call__(self) -> _dt.datetime:
        value = self._now
        self._now = self._now + self._step
        return value


def synthetic_role_provider() -> StaticRoleProvider:
    """A provider holding only ``TEST-`` actors."""
    return StaticRoleProvider(SYNTHETIC_ACTORS)


def synthetic_policy(**overrides: Any) -> WorkflowPolicy:
    """The approved world. Exists nowhere but in tests."""
    values: Dict[str, Any] = {
        "protocol_status": ProtocolStatus.APPROVED,
        "protocol_version": SYNTHETIC_PROTOCOL_VERSION,
        "protocol_content_hash": SYNTHETIC_PROTOCOL_HASH,
        "protocol_approved_by": "TEST-protocol-owner-1",
        "protocol_review_due": _dt.date(2099, 12, 31),
        "evidence_build_key": SYNTHETIC_BUILD_KEY,
        "evidence_build_content_hash": SYNTHETIC_BUILD_HASH,
        "dataset_public_id": SYNTHETIC_DATASET_ID,
        "evidence_build_quarantined": False,
        "evidence_build_lifecycle_labels": ("TEST_SYNTHETIC",),
        "known_evidence_uuids": SYNTHETIC_EVIDENCE_UUIDS,
        "source_policy_status": "APPROVED",
    }
    values.update(overrides)
    return WorkflowPolicy(**values)


def real_repository_policy(protocol_content_hash: str = "",
                           **overrides: Any) -> WorkflowPolicy:
    """The world as this repository actually is.

    Nothing reaches CURATED under it, and tests assert exactly that.
    """
    values: Dict[str, Any] = {
        "protocol_status": ProtocolStatus.AWAITING_EXPERT_REVIEW,
        "protocol_version": "curation-protocol/1",
        "protocol_content_hash": (protocol_content_hash
                                  or "sha256:" + "f" * 64),
        "protocol_approved_by": None,
        "evidence_build_quarantined": True,
        "evidence_build_lifecycle_labels": ("QUARANTINED",
                                            "NOT_PUBLICATION_ELIGIBLE"),
        "source_policy_status": None,
    }
    values.update(overrides)
    return WorkflowPolicy(**values)


def evidence_snapshot(**overrides: Any) -> EvidenceSelectionSnapshot:
    values: Dict[str, Any] = {
        "evidence_record_uuids": SYNTHETIC_EVIDENCE_UUIDS,
        "evidence_build_key": SYNTHETIC_BUILD_KEY,
        "evidence_build_content_hash": SYNTHETIC_BUILD_HASH,
        "dataset_public_id": SYNTHETIC_DATASET_ID,
    }
    values.update(overrides)
    return EvidenceSelectionSnapshot(**values)


def steward_verification(**overrides: Any) -> ProvenanceVerification:
    values: Dict[str, Any] = {
        "verified_by": TEST_STEWARD,
        "verified_by_role": CurationRole.DATA_PROVENANCE_STEWARD,
        "verified_at": _dt.datetime(2026, 1, 1, 11, 0,
                                    tzinfo=_dt.timezone.utc),
        "evidence_record_uuids": SYNTHETIC_EVIDENCE_UUIDS,
        "all_traces_verified": True,
    }
    values.update(overrides)
    return ProvenanceVerification(**values)


def raw_work_item(work_item_id: str = "TEST-WI-0001",
                  **overrides: Any) -> CurationWorkItem:
    values: Dict[str, Any] = {
        "work_item_id": work_item_id,
        "status": CurationStatus.RAW,
        "version": 0,
        "question_id": "TEST-Q-0001",
        "gene_canonical_key": "GENE:TEST1",
        "drug_canonical_key": "DRUG:testdrug",
        "created_at": _dt.datetime(2026, 1, 1, 10, 0, tzinfo=_dt.timezone.utc),
        "created_by": TEST_CURATOR,
        "tags": ("TEST_SYNTHETIC",),
    }
    values.update(overrides)
    return CurationWorkItem(**values)


def build_service(policy: Optional[WorkflowPolicy] = None,
                  store: Optional[InMemoryWorkflowStore] = None,
                  clock: Optional[Any] = None):
    """A service wired to an in-memory store. Returns ``(service, store)``."""
    store = store or InMemoryWorkflowStore()
    service = CurationWorkflowService(
        uow_factory=lambda: InMemoryWorkflowUnitOfWork(store),
        role_provider=synthetic_role_provider(),
        policy=policy or synthetic_policy(),
        clock=clock or FixedClock())
    return service, store


def seed_raw(store: InMemoryWorkflowStore,
             item: Optional[CurationWorkItem] = None) -> CurationWorkItem:
    """Put a RAW work item into the store without going through the service.

    Used where the test is about a later transition and the import path is
    covered elsewhere.
    """
    item = item or raw_work_item()
    with InMemoryWorkflowUnitOfWork(store) as uow:
        uow.work_items.add(item)
        uow.commit()
    return item
