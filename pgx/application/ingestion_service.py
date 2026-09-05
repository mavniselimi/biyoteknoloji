# -*- coding: utf-8 -*-
"""Orchestrating an acquisition run (WP-04).

Standard library plus the ingestion package. **No database.** Acquisition
writes raw responses to a cache and produces a manifest; persisting any of it is
WP-06 and WP-08, and a service that reached for a session here would tie
acquisition to a schema that does not yet describe it.

Five operations, and the split between them is the useful part:

* :func:`plan_acquisition` builds every first request **without a transport at
  all**, so an operator can see exactly what a run would ask for before it asks;
* :func:`acquire` runs it;
* :func:`replay_from_cache` runs it again with the network structurally
  unavailable;
* :func:`validate_run` re-reads a manifest and re-checks the claim it makes;
* :func:`validate_cache` re-hashes every stored blob.

**A failure returns, it does not raise.** One endpoint failing must not destroy
the account of the others, so `acquire` returns a manifest whose status is
``FAILED`` and whose endpoint records explain why. The exceptions are
configuration and safety errors, which mean the run should not have started -
those raise before any request.
"""

from __future__ import annotations

import datetime as _dt
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.ingestion.clinpgx.adapter import (
    AcquisitionContext, acquire_endpoint, build_page_request,
)
from pgx.ingestion.clinpgx.catalog import (
    CLINPGX_BASE_URL, CLINPGX_SOURCE_ID, EndpointDeclaration, catalog_ids,
    clinpgx_catalog, get_endpoint,
)
from pgx.ingestion.common.cache import ResponseCache
from pgx.ingestion.common.errors import ConfigurationError
from pgx.ingestion.common.http import request_key
from pgx.ingestion.common.manifest import (
    AcquisitionManifest, build_acquisition_manifest, build_content_manifest,
    content_manifest_hash,
)
from pgx.ingestion.common.models import AcquisitionRunId, AcquisitionStatus
from pgx.ingestion.common.retry import RetryPolicy

__all__ = [
    "AcquisitionPlan",
    "IngestionService",
    "PlannedRequest",
    "RunValidation",
]


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _sleep(seconds: float) -> None:  # pragma: no cover - replaced in tests
    import time

    time.sleep(seconds)


@dataclass(frozen=True)
class PlannedRequest:
    """One request a run would make, computed without making it."""

    endpoint_id: str
    required: bool
    method: str
    url: str
    safe_query: Tuple[Tuple[str, str], ...]
    request_key: str
    pagination_strategy: str
    cached: bool

    def to_json(self) -> Mapping[str, Any]:
        """Machine-readable form."""
        return {
            "endpoint_id": self.endpoint_id,
            "required": self.required,
            "method": self.method,
            "url": self.url,
            "safe_query": [list(pair) for pair in self.safe_query],
            "request_key": self.request_key,
            "pagination_strategy": self.pagination_strategy,
            "cached": self.cached,
        }


@dataclass(frozen=True)
class AcquisitionPlan:
    """What a run would do, before it does anything."""

    source_id: str
    requests: Tuple[PlannedRequest, ...]
    cache_root: str

    @property
    def required_count(self) -> int:
        """How many planned requests are for required endpoints."""
        return sum(1 for item in self.requests if item.required)

    @property
    def cached_count(self) -> int:
        """How many first pages the cache could already answer."""
        return sum(1 for item in self.requests if item.cached)

    def to_json(self) -> Mapping[str, Any]:
        """Machine-readable form."""
        return {
            "source_id": self.source_id,
            "cache_root": self.cache_root,
            "request_count": len(self.requests),
            "required_request_count": self.required_count,
            "cached_first_pages": self.cached_count,
            "requests": [item.to_json() for item in self.requests],
            "scope_note": (
                "A plan describes intent only. No request has been made and no "
                "network connection has been opened."
            ),
        }


@dataclass(frozen=True)
class RunValidation:
    """The result of re-checking a manifest's own claim."""

    run_id: str
    status: str
    is_publishable: bool
    recomputed_content_hash: str
    content_hash_matches: bool
    problems: Tuple[str, ...]

    @property
    def valid(self) -> bool:
        """True when the manifest is internally consistent."""
        return not self.problems

    def to_json(self) -> Mapping[str, Any]:
        """Machine-readable form."""
        return {
            "run_id": self.run_id,
            "status": self.status,
            "is_publishable": self.is_publishable,
            "recomputed_content_hash": self.recomputed_content_hash,
            "content_hash_matches": self.content_hash_matches,
            "valid": self.valid,
            "problems": list(self.problems),
        }


class IngestionService:
    """Plan, run, replay and validate acquisitions.

    Everything variable is a constructor argument: the cache, the transport
    factory, the retry policy, the clock, the sleeper and the randomness. A run
    can therefore be reproduced exactly in a test, and the suite never sleeps.

    ``transport_factory`` is a callable rather than a transport so that a
    cache-only run can simply never call it - the network is structurally
    unavailable rather than merely unused.
    """

    def __init__(
        self,
        cache: ResponseCache,
        transport_factory: Optional[Callable[[], Any]] = None,
        retry_policy: Optional[RetryPolicy] = None,
        base_url: str = CLINPGX_BASE_URL,
        source_id: str = CLINPGX_SOURCE_ID,
        timeout_seconds: float = 30.0,
        clock: Callable[[], _dt.datetime] = _utc_now,
        sleeper: Callable[[float], None] = _sleep,
        random_source: Callable[[], float] = random.random,
        new_run_id: Callable[[], AcquisitionRunId] = AcquisitionRunId.new,
    ) -> None:
        self._cache = cache
        self._transport_factory = transport_factory
        self._retry_policy = retry_policy or RetryPolicy()
        self._base_url = base_url
        self._source_id = source_id
        self._timeout_seconds = timeout_seconds
        self._clock = clock
        self._sleeper = sleeper
        self._random_source = random_source
        self._new_run_id = new_run_id

    # -- planning --------------------------------------------------------

    def plan_acquisition(
        self,
        parameters: Mapping[str, Any],
        endpoint_ids: Optional[Sequence[str]] = None,
    ) -> AcquisitionPlan:
        """Return the first request of every selected endpoint.

        Makes no request and needs no transport. An operator can read exactly
        what a run would ask for - including whether the cache already holds it
        - before committing to it.
        """
        planned: List[PlannedRequest] = []
        for endpoint in self._select(endpoint_ids):
            request = build_page_request(
                endpoint, parameters, self._base_url, self._timeout_seconds,
                endpoint.pagination.first_page_number, None, 0)
            key = request_key(request)
            planned.append(PlannedRequest(
                endpoint_id=endpoint.endpoint_id,
                required=endpoint.required,
                method=request.method,
                url=request.url,
                safe_query=request.query,
                request_key=key,
                pagination_strategy=endpoint.pagination.strategy.value,
                cached=self._cache.has(key)))
        return AcquisitionPlan(source_id=self._source_id,
                               requests=tuple(planned),
                               cache_root=self._cache.root)

    # -- running ---------------------------------------------------------

    def acquire(
        self,
        parameters: Mapping[str, Any],
        endpoint_ids: Optional[Sequence[str]] = None,
        refresh: bool = False,
    ) -> AcquisitionManifest:
        """Run an acquisition and return its manifest.

        Never raises for a source-side failure. A refused host, a missing
        timeout or an unknown endpoint ID still raises, because those mean the
        run was misconfigured and should not have started.
        """
        return self._run(parameters, endpoint_ids, cache_only=False,
                         refresh=refresh)

    def replay_from_cache(
        self,
        parameters: Mapping[str, Any],
        endpoint_ids: Optional[Sequence[str]] = None,
    ) -> AcquisitionManifest:
        """Re-run entirely from cache, with the network unavailable.

        The transport factory is never called, so a replay cannot silently fall
        back to the network. A page the cache does not hold fails the endpoint
        with ``CACHE_MISS``.

        The resulting manifest differs from the original run in every
        operational field and agrees exactly on ``content_hash``.
        """
        return self._run(parameters, endpoint_ids, cache_only=True,
                         refresh=False)

    def _run(self, parameters, endpoint_ids, cache_only: bool,
             refresh: bool) -> AcquisitionManifest:
        endpoints = self._select(endpoint_ids)
        run_id = self._new_run_id()
        started_at = self._clock()

        context = AcquisitionContext(
            cache=self._cache,
            transport=None if cache_only else self._make_transport(),
            retry_policy=self._retry_policy,
            base_url=self._base_url,
            timeout_seconds=self._timeout_seconds,
            cache_only=cache_only,
            refresh=refresh,
            clock=self._clock,
            sleeper=self._sleeper,
            random_source=self._random_source)

        completions = [acquire_endpoint(endpoint, parameters, context)
                       for endpoint in endpoints]

        return build_acquisition_manifest(
            run_id=run_id, source_id=self._source_id,
            started_at=started_at, completed_at=self._clock(),
            endpoints=completions, cache_root=self._cache.root,
            cache_only=cache_only)

    def _make_transport(self):
        if self._transport_factory is None:
            raise ConfigurationError(
                "a transport factory is required for a network run; use "
                "replay_from_cache() for an offline run")
        return self._transport_factory()

    # -- validation ------------------------------------------------------

    def validate_run(self, manifest: AcquisitionManifest) -> RunValidation:
        """Re-check a manifest against its own contents.

        Recomputes the content hash from the retrieval records rather than
        trusting the stored one, and re-derives the completeness rules. A
        manifest that claims ``COMPLETE`` while a required endpoint failed is
        exactly what this catches.
        """
        problems: List[str] = []
        recomputed = content_manifest_hash(
            build_content_manifest(manifest.source_id, manifest.endpoints))
        matches = recomputed == manifest.content_hash
        if not matches:
            problems.append(
                "content hash mismatch: manifest records %s, recomputed %s"
                % (manifest.content_hash, recomputed))

        blocking = [endpoint.endpoint_id for endpoint in manifest.endpoints
                    if endpoint.blocks_completion]
        if blocking and manifest.status is not AcquisitionStatus.FAILED:
            problems.append(
                "manifest status is %s but required endpoint(s) %s did not "
                "complete" % (manifest.status.value, ", ".join(blocking)))
        if not blocking and manifest.status is AcquisitionStatus.FAILED:
            problems.append(
                "manifest status is FAILED but no required endpoint blocks "
                "completion")

        for endpoint in manifest.endpoints:
            for record in endpoint.records:
                if record.succeeded and record.raw_sha256 is None:
                    problems.append(
                        "endpoint %r page %d succeeded without a raw digest"
                        % (endpoint.endpoint_id, record.page_number))
                if record.succeeded and record.cache_blob_ref is None:
                    problems.append(
                        "endpoint %r page %d succeeded without a cache "
                        "reference" % (endpoint.endpoint_id, record.page_number))

        return RunValidation(
            run_id=manifest.run_id.to_json(),
            status=manifest.status.value,
            is_publishable=manifest.is_publishable,
            recomputed_content_hash=recomputed,
            content_hash_matches=matches,
            problems=tuple(problems))

    def validate_cache(self) -> Mapping[str, Any]:
        """Re-hash every stored blob and report what does not verify."""
        return self._cache.verify()

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _select(endpoint_ids: Optional[Sequence[str]]) -> Tuple[EndpointDeclaration, ...]:
        """Resolve endpoint IDs to declarations, refusing unknown ones.

        Selection is by catalog ID only. Accepting a path or a URL would let a
        caller reach an endpoint nobody declared, which is precisely what the
        catalog exists to prevent.
        """
        if endpoint_ids is None:
            return clinpgx_catalog()
        if not endpoint_ids:
            raise ConfigurationError(
                "no endpoints selected; pass none to use the whole catalog "
                "(%s)" % ", ".join(catalog_ids()))
        return tuple(get_endpoint(str(item)) for item in endpoint_ids)
