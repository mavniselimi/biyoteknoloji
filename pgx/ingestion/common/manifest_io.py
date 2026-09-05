# -*- coding: utf-8 -*-
"""Reading a WP-04 run manifest back from disk (WP-06).

Standard library plus ``pgx.domain`` and :mod:`pgx.ingestion.common`.

WP-04 writes acquisition manifests. Nothing until now read one back, because
nothing needed to: the service that produced a manifest still had the objects
in memory. WP-06 does need to - a snapshot is built from a manifest that was
written by an earlier process - and that changes the trust model completely.

**A manifest on disk is untrusted input.** It is a JSON file somebody could
have edited. So this module does not merely parse it; it rebuilds the typed
records and lets :meth:`IngestionService.validate_run` recompute completeness
and the content hash from those records. In particular:

* ``status`` is **not** trusted. It is recomputed from the endpoint outcomes by
  the same rules WP-04 used, and a mismatch is an error.
* ``is_publishable`` is **not** trusted. It is a derived property in the typed
  model, so the deserialised manifest computes its own; the serialised flag is
  compared against it and a disagreement is an error.
* ``content_hash`` is **not** trusted. It is recomputed from the retrieval
  records.
* ``duration_seconds``, ``retry_count``, ``record_count`` and the other derived
  fields in the JSON are ignored entirely rather than being read back and
  believed.

Unknown keys are refused. A manifest carrying a field this build does not
understand may have been written by a different version whose meaning differs,
and half-reading it is worse than refusing it.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
from typing import Any, Mapping, Optional, Sequence, Tuple

from pgx.ingestion.common.errors import ResponseShapeError
from pgx.ingestion.common.manifest import (
    CONTENT_MANIFEST_VERSION,
    RUN_MANIFEST_VERSION,
    AcquisitionManifest,
    build_acquisition_manifest,
)
from pgx.ingestion.common.models import (
    AcquisitionRunId,
    CacheState,
    EndpointCompletion,
    EndpointOutcome,
    PaginationState,
    ParseStatus,
    RateLimitInfo,
    RetrievalAttempt,
    RetrievalRecord,
)

__all__ = [
    "ManifestDeserializationError",
    "load_acquisition_manifest",
    "read_acquisition_manifest",
]


class ManifestDeserializationError(ResponseShapeError):
    """A stored acquisition manifest cannot be read back as written.

    A subclass of :class:`ResponseShapeError` because the failure is the same
    kind: bytes arrived and are not the shape they claim to be. Retrying will
    not change that.
    """


#: Keys the run manifest may carry. Anything else is refused rather than
#: ignored: a field this build does not understand may change what the
#: manifest means.
_RUN_KEYS = frozenset({
    "run_manifest_version", "run_id", "source_id", "status", "is_publishable",
    "started_at", "completed_at", "duration_seconds", "cache_root",
    "cache_only", "endpoint_count", "required_endpoint_count", "total_pages",
    "total_records", "content_hash", "content_manifest", "endpoints",
    "warnings", "failures", "scope_note",
})

_ENDPOINT_KEYS = frozenset({
    "endpoint_id", "required", "outcome", "pagination", "record_count",
    "records", "error_code", "error_detail",
})

_PAGINATION_KEYS = frozenset({
    "pages_fetched", "records_seen", "terminal", "termination_reason",
    "last_cursor",
})

_RECORD_KEYS = frozenset({
    "request_key", "endpoint_id", "method", "url", "safe_query", "page_number",
    "cursor", "started_at", "completed_at", "status_code", "raw_sha256",
    "byte_length", "content_type", "cache_state", "cache_blob_ref",
    "parse_status", "record_count", "retry_count", "attempts", "rate_limit",
    "error_code", "error_detail",
})

_ATTEMPT_KEYS = frozenset({
    "attempt_number", "started_at", "status_code", "error_code",
    "retry_reason", "delay_before_seconds", "retry_after_seconds",
})

_RATE_LIMIT_KEYS = frozenset({
    "limit", "remaining", "reset_seconds", "retry_after_seconds",
})


def _require_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestDeserializationError(
            "%s must be a JSON object, got %s" % (where, type(value).__name__))
    return value


def _reject_unknown(payload: Mapping[str, Any], allowed, where: str) -> None:
    unknown = sorted(set(payload) - set(allowed))
    if unknown:
        raise ManifestDeserializationError(
            "%s carries unknown key(s): %s. A manifest written against another "
            "shape is refused rather than half-read."
            % (where, ", ".join(unknown)))


def _require_str(payload: Mapping[str, Any], key: str, where: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestDeserializationError(
            "%s.%s must be a non-empty string" % (where, key))
    return value


def _optional_str(payload: Mapping[str, Any], key: str, where: str) -> Optional[str]:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ManifestDeserializationError(
            "%s.%s must be a string or null" % (where, key))
    return value


def _require_int(payload: Mapping[str, Any], key: str, where: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestDeserializationError(
            "%s.%s must be an integer" % (where, key))
    return value


def _optional_int(payload: Mapping[str, Any], key: str, where: str) -> Optional[int]:
    value = payload.get(key)
    if value is None:
        return None
    return _require_int(payload, key, where)


def _optional_float(payload: Mapping[str, Any], key: str, where: str) -> Optional[float]:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestDeserializationError(
            "%s.%s must be a number or null" % (where, key))
    return float(value)


def _require_bool(payload: Mapping[str, Any], key: str, where: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ManifestDeserializationError(
            "%s.%s must be a boolean" % (where, key))
    return value


def _require_instant(payload: Mapping[str, Any], key: str, where: str) -> _dt.datetime:
    text = _require_str(payload, key, where)
    normalised = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = _dt.datetime.fromisoformat(normalised)
    except ValueError:
        raise ManifestDeserializationError(
            "%s.%s is not a valid ISO-8601 instant: %r" % (where, key, text)) from None
    if parsed.tzinfo is None:
        raise ManifestDeserializationError(
            "%s.%s has no UTC offset; a naive timestamp names no instant"
            % (where, key))
    return parsed.astimezone(_dt.timezone.utc)


def _enum(cls, value: Any, where: str):
    if not isinstance(value, str):
        raise ManifestDeserializationError("%s must be a string" % where)
    try:
        return cls(value)
    except ValueError:
        raise ManifestDeserializationError(
            "%s: %r is not a valid %s; permitted values are %s"
            % (where, value, cls.__name__,
               ", ".join(member.value for member in cls))) from None


def _rate_limit(payload: Any, where: str) -> RateLimitInfo:
    if payload is None:
        return RateLimitInfo()
    mapping = _require_mapping(payload, where)
    _reject_unknown(mapping, _RATE_LIMIT_KEYS, where)
    return RateLimitInfo(
        limit=_optional_int(mapping, "limit", where),
        remaining=_optional_int(mapping, "remaining", where),
        reset_seconds=_optional_float(mapping, "reset_seconds", where),
        retry_after_seconds=_optional_float(mapping, "retry_after_seconds", where))


def _attempt(payload: Any, where: str) -> RetrievalAttempt:
    mapping = _require_mapping(payload, where)
    _reject_unknown(mapping, _ATTEMPT_KEYS, where)
    return RetrievalAttempt(
        attempt_number=_require_int(mapping, "attempt_number", where),
        started_at=_require_instant(mapping, "started_at", where),
        status_code=_optional_int(mapping, "status_code", where),
        error_code=_optional_str(mapping, "error_code", where),
        retry_reason=_optional_str(mapping, "retry_reason", where),
        delay_before_seconds=float(mapping.get("delay_before_seconds") or 0.0),
        retry_after_seconds=(None if mapping.get("retry_after_seconds") is None
                             else float(mapping["retry_after_seconds"])))


def _safe_query(payload: Any, where: str) -> Tuple[Tuple[str, str], ...]:
    """Read the repeated-parameter query back without collapsing duplicates.

    Stored as a list of pairs rather than an object precisely so that
    ``?id=1&id=2`` survives. Reading it into a dict here would undo that.
    """
    if payload is None:
        return ()
    if isinstance(payload, Mapping) or not isinstance(payload, (list, tuple)):
        raise ManifestDeserializationError(
            "%s must be a list of [name, value] pairs; an object would collapse "
            "repeated query parameters" % where)
    pairs = []
    for index, item in enumerate(payload):
        if isinstance(item, str) or not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ManifestDeserializationError(
                "%s[%d] must be a two-element [name, value] pair" % (where, index))
        pairs.append((str(item[0]), str(item[1])))
    return tuple(pairs)


def _record(payload: Any, where: str) -> RetrievalRecord:
    mapping = _require_mapping(payload, where)
    _reject_unknown(mapping, _RECORD_KEYS, where)
    attempts_payload = mapping.get("attempts") or ()
    if isinstance(attempts_payload, (str, Mapping)) or not isinstance(
            attempts_payload, (list, tuple)):
        raise ManifestDeserializationError("%s.attempts must be a list" % where)
    return RetrievalRecord(
        request_key=_require_str(mapping, "request_key", where),
        endpoint_id=_require_str(mapping, "endpoint_id", where),
        method=_require_str(mapping, "method", where),
        url=_require_str(mapping, "url", where),
        safe_query=_safe_query(mapping.get("safe_query"), "%s.safe_query" % where),
        page_number=_require_int(mapping, "page_number", where),
        cursor=_optional_str(mapping, "cursor", where),
        started_at=_require_instant(mapping, "started_at", where),
        completed_at=_require_instant(mapping, "completed_at", where),
        status_code=_optional_int(mapping, "status_code", where),
        raw_sha256=_optional_str(mapping, "raw_sha256", where),
        byte_length=_require_int(mapping, "byte_length", where),
        content_type=mapping.get("content_type") or "",
        cache_state=_enum(CacheState, mapping.get("cache_state"),
                          "%s.cache_state" % where),
        cache_blob_ref=_optional_str(mapping, "cache_blob_ref", where),
        parse_status=_enum(ParseStatus, mapping.get("parse_status"),
                           "%s.parse_status" % where),
        record_count=_optional_int(mapping, "record_count", where),
        attempts=tuple(_attempt(item, "%s.attempts[%d]" % (where, index))
                       for index, item in enumerate(attempts_payload)),
        rate_limit=_rate_limit(mapping.get("rate_limit"), "%s.rate_limit" % where),
        error_code=_optional_str(mapping, "error_code", where),
        error_detail=_optional_str(mapping, "error_detail", where))


def _pagination(payload: Any, where: str) -> PaginationState:
    mapping = _require_mapping(payload, where)
    _reject_unknown(mapping, _PAGINATION_KEYS, where)
    return PaginationState(
        pages_fetched=_require_int(mapping, "pages_fetched", where),
        records_seen=_require_int(mapping, "records_seen", where),
        terminal=_require_bool(mapping, "terminal", where),
        termination_reason=_require_str(mapping, "termination_reason", where),
        last_cursor=_optional_str(mapping, "last_cursor", where))


def _endpoint(payload: Any, where: str) -> EndpointCompletion:
    mapping = _require_mapping(payload, where)
    _reject_unknown(mapping, _ENDPOINT_KEYS, where)
    records_payload = mapping.get("records") or ()
    if isinstance(records_payload, (str, Mapping)) or not isinstance(
            records_payload, (list, tuple)):
        raise ManifestDeserializationError("%s.records must be a list" % where)
    return EndpointCompletion(
        endpoint_id=_require_str(mapping, "endpoint_id", where),
        required=_require_bool(mapping, "required", where),
        outcome=_enum(EndpointOutcome, mapping.get("outcome"), "%s.outcome" % where),
        pagination=_pagination(mapping.get("pagination"), "%s.pagination" % where),
        records=tuple(_record(item, "%s.records[%d]" % (where, index))
                      for index, item in enumerate(records_payload)),
        error_code=_optional_str(mapping, "error_code", where),
        error_detail=_optional_str(mapping, "error_detail", where))


def read_acquisition_manifest(payload: Mapping[str, Any]) -> AcquisitionManifest:
    """Rebuild a typed manifest from a parsed run-manifest document.

    The returned manifest's ``status`` and ``content_hash`` are **recomputed**
    by :func:`build_acquisition_manifest` from the endpoint records, never read
    from the document. The document's own claims are then compared against the
    recomputed ones, and a disagreement raises: a stored manifest asserting
    ``COMPLETE`` over a failed required endpoint is exactly the forgery this
    catches.
    """
    document = _require_mapping(payload, "acquisition manifest")
    _reject_unknown(document, _RUN_KEYS, "acquisition manifest")

    version = document.get("run_manifest_version")
    if version != RUN_MANIFEST_VERSION:
        raise ManifestDeserializationError(
            "acquisition manifest declares run_manifest_version %r; this build "
            "understands %r" % (version, RUN_MANIFEST_VERSION))

    content_manifest = _require_mapping(
        document.get("content_manifest"), "acquisition manifest.content_manifest")
    content_version = content_manifest.get("content_manifest_version")
    if content_version != CONTENT_MANIFEST_VERSION:
        raise ManifestDeserializationError(
            "content manifest declares version %r; this build understands %r"
            % (content_version, CONTENT_MANIFEST_VERSION))

    endpoints_payload = document.get("endpoints")
    if not isinstance(endpoints_payload, list):
        raise ManifestDeserializationError(
            "acquisition manifest.endpoints must be an array")

    endpoints = tuple(
        _endpoint(item, "acquisition manifest.endpoints[%d]" % index)
        for index, item in enumerate(endpoints_payload))

    rebuilt = build_acquisition_manifest(
        run_id=AcquisitionRunId(_require_str(document, "run_id", "acquisition manifest")),
        source_id=_require_str(document, "source_id", "acquisition manifest"),
        started_at=_require_instant(document, "started_at", "acquisition manifest"),
        completed_at=_require_instant(document, "completed_at", "acquisition manifest"),
        endpoints=endpoints,
        cache_root=_optional_str(document, "cache_root", "acquisition manifest"),
        cache_only=bool(document.get("cache_only", False)))

    _compare_claims(document, rebuilt)
    return rebuilt


def _compare_claims(document: Mapping[str, Any], rebuilt: AcquisitionManifest) -> None:
    """Refuse a stored manifest whose own claims disagree with its contents.

    Three claims are checked, and all three are ones a hand-edited manifest
    would have to get right to slip through: the declared status, the declared
    publishability, and the declared content hash.
    """
    declared_status = document.get("status")
    if declared_status is not None and declared_status != rebuilt.status.value:
        raise ManifestDeserializationError(
            "acquisition manifest declares status %r, but its endpoint outcomes "
            "recompute to %s. The stored status is not trusted."
            % (declared_status, rebuilt.status.value))

    declared_publishable = document.get("is_publishable")
    if (declared_publishable is not None
            and bool(declared_publishable) != rebuilt.is_publishable):
        raise ManifestDeserializationError(
            "acquisition manifest declares is_publishable=%r, but its recomputed "
            "status %s gives %r. A serialised flag never decides publishability."
            % (declared_publishable, rebuilt.status.value, rebuilt.is_publishable))

    declared_hash = document.get("content_hash")
    if declared_hash is not None and declared_hash != rebuilt.content_hash:
        raise ManifestDeserializationError(
            "acquisition manifest declares content_hash %s, but its retrieval "
            "records recompute to %s" % (declared_hash, rebuilt.content_hash))


def load_acquisition_manifest(path: str) -> AcquisitionManifest:
    """Read, parse and revalidate a run manifest from a file."""
    try:
        with io.open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise ManifestDeserializationError(
            "cannot read acquisition manifest %s: %s" % (path, exc)) from exc
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise ManifestDeserializationError(
            "acquisition manifest %s is not valid JSON: %s" % (path, exc)) from exc
    return read_acquisition_manifest(payload)


def endpoint_ids(manifest: AcquisitionManifest) -> Sequence[str]:
    """Every endpoint the manifest names, in canonical order."""
    return tuple(sorted(endpoint.endpoint_id for endpoint in manifest.endpoints))
