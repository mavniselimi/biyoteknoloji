# -*- coding: utf-8 -*-
"""The acquisition manifest, and the content hash inside it (WP-04).

Standard library only.

A run produces **two** views of itself, and keeping them apart is the point of
this module.

**The run manifest** is the operational account: when it started, how many
attempts each request took, which pages came from cache, what the rate-limit
headers said, which endpoints failed and whether they were required. It is what
an operator reads.

**The content manifest** is the identity of what was acquired: canonical request
keys, endpoint IDs, page identities, raw digests and byte lengths - sorted, so
the order pages happened to arrive in cannot change it. Its SHA-256 is the
answer to "did we get the same data?".

The separation is what makes the determinism guarantee real. A network run and a
cache-only replay of the same data differ in every operational field and agree
exactly on the content hash. If timestamps or retry counts reached the content
hash, replay would produce a different identity for identical bytes and the
guarantee would be worthless.

**Completeness is computed, not asserted.** :func:`build_acquisition_manifest`
derives the status from the endpoint outcomes. A required endpoint that failed,
or one whose pagination never reached a terminal state, forces ``FAILED`` - it
cannot be downgraded to a warning, and no caller can pass in a status of its own.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence, Tuple

from pgx.domain.hashing import ensure_utc, sha256_digest
from pgx.ingestion.common.models import (
    AcquisitionRunId, AcquisitionStatus, EndpointCompletion, EndpointOutcome,
)

__all__ = [
    "CONTENT_MANIFEST_VERSION",
    "RUN_MANIFEST_VERSION",
    "AcquisitionManifest",
    "build_acquisition_manifest",
    "build_content_manifest",
    "content_manifest_hash",
]

#: Part of the hashed content payload, so a shape change cannot silently
#: collide with an older run's identity.
CONTENT_MANIFEST_VERSION = "pgx-acquisition-content/1"

RUN_MANIFEST_VERSION = "pgx-acquisition-run/1"


def build_content_manifest(
    source_id: str,
    endpoints: Sequence[EndpointCompletion],
) -> Mapping[str, Any]:
    """Return the deterministic identity of what was acquired.

    Contains only content identity: request key, endpoint, page, cursor, raw
    digest, byte length. No timestamp, no attempt count, no cache state, no run
    ID - a re-run is a different *run* and must still be the same *content*.

    Entries are sorted by request key, so the order pages arrived in cannot
    change the hash. Failed retrievals are excluded: they produced no content
    to identify, and including them would make the hash depend on how the
    failure went.
    """
    entries = []
    for endpoint in sorted(endpoints, key=lambda item: item.endpoint_id):
        for record in endpoint.records:
            if record.raw_sha256 is None:
                continue
            entries.append(dict(record.content_identity()))
    entries.sort(key=lambda item: (item["request_key"], item["page_number"]))
    return {
        "content_manifest_version": CONTENT_MANIFEST_VERSION,
        "source_id": source_id,
        "entry_count": len(entries),
        "entries": entries,
    }


def content_manifest_hash(content_manifest: Mapping[str, Any]) -> str:
    """Return the canonical digest of a content manifest.

    Reuses :func:`pgx.domain.hashing.sha256_digest`, so acquisition identity
    and every other identity in the system share one canonical encoding.
    """
    return sha256_digest(content_manifest)


@dataclass(frozen=True)
class AcquisitionManifest:
    """The complete, machine-readable account of one run."""

    run_id: AcquisitionRunId
    source_id: str
    status: AcquisitionStatus
    started_at: _dt.datetime
    completed_at: _dt.datetime
    endpoints: Tuple[EndpointCompletion, ...]
    content_manifest: Mapping[str, Any]
    content_hash: str
    warnings: Tuple[str, ...] = ()
    failures: Tuple[str, ...] = ()
    cache_root: Optional[str] = None
    cache_only: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "started_at", ensure_utc(self.started_at, "started_at"))
        object.__setattr__(self, "completed_at",
                           ensure_utc(self.completed_at, "completed_at"))
        object.__setattr__(self, "endpoints", tuple(self.endpoints))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "failures", tuple(self.failures))

    @property
    def is_publishable(self) -> bool:
        """True only when every required endpoint finished.

        The single question a later work package should ask. It is a property
        of the computed status, not a separate flag that could disagree with it.
        """
        return self.status.is_publishable

    @property
    def required_endpoints(self) -> Tuple[EndpointCompletion, ...]:
        """Only the endpoints whose failure blocks completion."""
        return tuple(item for item in self.endpoints if item.required)

    @property
    def total_records(self) -> int:
        """How many raw records were retrieved across all endpoints."""
        return sum(endpoint.pagination.records_seen for endpoint in self.endpoints)

    @property
    def total_pages(self) -> int:
        """How many pages were retrieved across all endpoints."""
        return sum(endpoint.pagination.pages_fetched for endpoint in self.endpoints)

    def to_json(self) -> Mapping[str, Any]:
        """The full run manifest, operational metadata included."""
        return {
            "run_manifest_version": RUN_MANIFEST_VERSION,
            "run_id": self.run_id.to_json(),
            "source_id": self.source_id,
            "status": self.status.value,
            "is_publishable": self.is_publishable,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_seconds": (self.completed_at - self.started_at).total_seconds(),
            "cache_root": self.cache_root,
            "cache_only": self.cache_only,
            "endpoint_count": len(self.endpoints),
            "required_endpoint_count": len(self.required_endpoints),
            "total_pages": self.total_pages,
            "total_records": self.total_records,
            "content_hash": self.content_hash,
            "content_manifest": dict(self.content_manifest),
            "endpoints": [endpoint.to_json() for endpoint in self.endpoints],
            "warnings": list(self.warnings),
            "failures": list(self.failures),
            "scope_note": (
                "Acquisition only. These are raw source responses. Nothing here "
                "asserts scientific validity, canonical resolution, curation "
                "status, or release eligibility."
            ),
        }

    def summary(self) -> Mapping[str, Any]:
        """A short view, for a CLI that should not print every record."""
        return {
            "run_id": self.run_id.to_json(),
            "source_id": self.source_id,
            "status": self.status.value,
            "is_publishable": self.is_publishable,
            "content_hash": self.content_hash,
            "endpoint_count": len(self.endpoints),
            "total_pages": self.total_pages,
            "total_records": self.total_records,
            "warning_count": len(self.warnings),
            "failure_count": len(self.failures),
        }


def build_acquisition_manifest(
    run_id: AcquisitionRunId,
    source_id: str,
    started_at: _dt.datetime,
    completed_at: _dt.datetime,
    endpoints: Sequence[EndpointCompletion],
    cache_root: Optional[str] = None,
    cache_only: bool = False,
) -> AcquisitionManifest:
    """Assemble a manifest and **compute** its status.

    The status is derived here and nowhere else. There is deliberately no
    parameter for it: a caller that could pass ``COMPLETE`` alongside a failed
    required endpoint would make every completeness guarantee in this work
    package advisory.

    The rules:

    * any required endpoint not ``COMPLETE``, or whose pagination is not
      terminal, gives ``FAILED``;
    * otherwise, any failed optional endpoint gives
      ``COMPLETE_WITH_WARNINGS``;
    * otherwise ``COMPLETE``.
    """
    warnings = []
    failures = []

    for endpoint in endpoints:
        if endpoint.blocks_completion:
            if endpoint.outcome is not EndpointOutcome.COMPLETE:
                failures.append(
                    "required endpoint %r did not complete: %s"
                    % (endpoint.endpoint_id,
                       endpoint.error_detail or endpoint.outcome.value))
            else:
                failures.append(
                    "required endpoint %r finished with non-terminal pagination "
                    "(%s after %d page(s)); the collected pages are an unknown "
                    "fraction of the endpoint"
                    % (endpoint.endpoint_id,
                       endpoint.pagination.termination_reason,
                       endpoint.pagination.pages_fetched))
        elif endpoint.outcome is EndpointOutcome.FAILED:
            warnings.append(
                "optional endpoint %r failed: %s"
                % (endpoint.endpoint_id,
                   endpoint.error_detail or "no detail recorded"))
        elif endpoint.outcome is EndpointOutcome.SKIPPED:
            warnings.append("optional endpoint %r was skipped" % endpoint.endpoint_id)
        elif not endpoint.pagination.terminal:
            warnings.append(
                "optional endpoint %r finished with non-terminal pagination (%s)"
                % (endpoint.endpoint_id, endpoint.pagination.termination_reason))

    if failures:
        status = AcquisitionStatus.FAILED
    elif warnings:
        status = AcquisitionStatus.COMPLETE_WITH_WARNINGS
    else:
        status = AcquisitionStatus.COMPLETE

    content_manifest = build_content_manifest(source_id, endpoints)
    return AcquisitionManifest(
        run_id=run_id, source_id=source_id, status=status,
        started_at=started_at, completed_at=completed_at,
        endpoints=tuple(endpoints), content_manifest=content_manifest,
        content_hash=content_manifest_hash(content_manifest),
        warnings=tuple(warnings), failures=tuple(failures),
        cache_root=cache_root, cache_only=cache_only)
