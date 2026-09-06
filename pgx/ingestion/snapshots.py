# -*- coding: utf-8 -*-
"""Immutable raw snapshots (WP-06).

Standard library plus ``pgx.domain``, ``pgx.scientific`` and
:mod:`pgx.ingestion.common`. No SQLAlchemy, no network: a snapshot is a
directory of bytes and a manifest, and building one must be exercisable with
nothing installed.

**What a snapshot is.** The exact bytes one acquisition run retrieved, copied
once into a write-once directory, with a checksum for every file and a manifest
that says what was copied and what it is *not*::

    data/raw/<source-key>/<dataset-id>/
        manifest.json
        requests.ndjson
        responses/<request-key>.json
        checksums.sha256

**Three identities, deliberately separate** (section 7 of the WP-06 brief):

* *artifact hash* - SHA-256 of one file's exact bytes;
* *snapshot content hash* - a digest over the sorted artifact content
  identities, excluding creation time, staging path, cache hit/miss state,
  retry timing **and the dataset ID**. A network run and a cache replay of the
  same data therefore produce the same content hash, and so do two snapshots
  built under different dataset IDs;
* *manifest hash* - the canonical digest of the manifest payload, which *does*
  include the dataset ID and the creation instant. Two dataset IDs share a
  content hash and differ in manifest hash.

**Bytes are copied, never reparsed.** Nothing here calls ``json.loads`` on a
response body. Reserialising a response to make it look tidier would silently
change key order, number formatting and whitespace, and the artifact hash would
then describe this project's formatting rather than the source's answer.

**What "immutable" means here, precisely.** The project enforces that no
supported API reopens a sealed snapshot for writing; that files and directories
are made read-only where the platform permits; that a dataset ID cannot be
claimed twice; and that verification detects any post-seal change. It does not
and cannot provide WORM storage: an operating-system owner can still chmod a
directory back and edit it. That is why verification exists, and why the
manifest records the hashes needed to run it.
"""

from __future__ import annotations

import datetime as _dt
import errno
import hashlib
import io
import json
import os
import stat
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.domain.hashing import canonical_json, ensure_utc, sha256_digest
from pgx.domain.identifiers import DatasetPublicId
from pgx.ingestion.common.cache import ResponseCache
from pgx.ingestion.common.errors import IngestionError
from pgx.ingestion.common.manifest import AcquisitionManifest
from pgx.ingestion.common.models import AcquisitionStatus

__all__ = [
    "ArtifactKind",
    "CHECKSUMS_FILE",
    "MANIFEST_FILE",
    "REQUESTS_FILE",
    "RESPONSES_DIR",
    "RawArtifactDescriptor",
    "SNAPSHOT_CONTENT_VERSION",
    "SNAPSHOT_MANIFEST_VERSION",
    "SnapshotBuildRequest",
    "SnapshotBuildResult",
    "SnapshotError",
    "SnapshotIssue",
    "SnapshotIssueCode",
    "SnapshotKind",
    "SnapshotManager",
    "SnapshotManifest",
    "SnapshotState",
    "SnapshotVerificationResult",
    "snapshot_content_hash",
    "snapshot_manifest_hash",
]

#: Manifest shape version. Part of the hashed payload, so a shape change cannot
#: silently collide with an older snapshot's identity.
SNAPSHOT_MANIFEST_VERSION = "pgx-raw-snapshot/1"

#: Content-identity payload version, hashed separately from the manifest.
SNAPSHOT_CONTENT_VERSION = "pgx-raw-snapshot-content/1"

MANIFEST_FILE = "manifest.json"
REQUESTS_FILE = "requests.ndjson"
CHECKSUMS_FILE = "checksums.sha256"
RESPONSES_DIR = "responses"

#: Files a sealed snapshot may contain at its root. Anything else is an
#: unexpected file and fails verification.
_ROOT_FILES = (MANIFEST_FILE, REQUESTS_FILE, CHECKSUMS_FILE)

#: Read-only modes applied after sealing, where the platform permits.
_READ_ONLY_FILE = 0o444
_READ_ONLY_DIR = 0o555

#: Characters that must never appear in a relative artifact path.
_FORBIDDEN_PATH_CHARS = ("\x00", "\\", "\n", "\r", "\t")

_MAX_PATH_SEGMENTS = 8
_MAX_SEGMENT_LENGTH = 200


class SnapshotError(IngestionError):
    """A snapshot could not be built, sealed or read.

    A subclass of :class:`~pgx.ingestion.common.errors.IngestionError` because a
    snapshot is the terminal step of acquisition: the same operator, the same
    run, the same failure vocabulary.
    """

    def __init__(self, message: str, code: "SnapshotIssueCode" = None) -> None:
        super().__init__(message)
        self.code = code


class SnapshotKind(str, Enum):
    """How a snapshot's bytes were obtained.

    The distinction is not cosmetic. ``ACQUISITION`` and ``CACHE_REPLAY`` come
    from a WP-04 run with full retrieval metadata and are gated by WP-05 source
    policy. ``LEGACY_IMPORT`` does not: it is a directory of files whose
    provenance predates the adapter, and it is quarantined precisely because
    that metadata does not exist and must not be invented.
    """

    ACQUISITION = "ACQUISITION"
    CACHE_REPLAY = "CACHE_REPLAY"
    LEGACY_IMPORT = "LEGACY_IMPORT"
    #: Content this project transcribed from a source it read one published
    #: document at a time, sealed with the same integrity discipline as any
    #: other snapshot and making none of the other three claims.
    #:
    #: ``ACQUISITION`` and ``CACHE_REPLAY`` both assert a WP-04 run with full
    #: retrieval metadata behind the bytes. ``LEGACY_IMPORT`` asserts the files
    #: predate the adapter and came from the frozen legacy probe scripts. A
    #: transcription capture asserts none of that: the bytes are this project's
    #: own rendering of what it read, the retrieval is recorded as
    #: ``AcquisitionMode.AGENT_TARGETED_RETRIEVAL``, and no upstream response
    #: body exists to hash.
    #:
    #: The name is 21 characters because ``snapshot_kind`` is ``String(24)``.
    TRANSCRIPTION_CAPTURE = "TRANSCRIPTION_CAPTURE"

    def __str__(self) -> str:
        return self.value


class SnapshotState(str, Enum):
    """Where a snapshot directory is in its one-way lifecycle.

    ``STAGING`` exists only inside a temporary directory that is either renamed
    into place or removed. There is no transition out of ``SEALED`` or
    ``QUARANTINED``: a snapshot is not reopened, it is superseded by a new
    dataset ID.
    """

    STAGING = "STAGING"
    SEALED = "SEALED"
    QUARANTINED = "QUARANTINED"

    def __str__(self) -> str:
        return self.value


class ArtifactKind(str, Enum):
    """What one file in a snapshot is."""

    #: Exact bytes of one HTTP response body.
    RESPONSE_BODY = "RESPONSE_BODY"
    #: The deterministic request log, ``requests.ndjson``.
    REQUEST_LOG = "REQUEST_LOG"
    #: A file copied verbatim from a legacy output directory.
    LEGACY_FILE = "LEGACY_FILE"

    def __str__(self) -> str:
        return self.value


class SnapshotIssueCode(str, Enum):
    """Stable machine-readable codes for build and verification failures.

    A public contract: renaming one is a breaking change, because an operator
    script or a CI job may be keyed on it.
    """

    # -- acquisition input ------------------------------------------------
    ACQUISITION_NOT_COMPLETE = "ACQUISITION_NOT_COMPLETE"
    ACQUISITION_RUNNING = "ACQUISITION_RUNNING"
    REQUIRED_ENDPOINT_INCOMPLETE = "REQUIRED_ENDPOINT_INCOMPLETE"
    PAGINATION_NOT_TERMINAL = "PAGINATION_NOT_TERMINAL"
    CONTENT_HASH_MISMATCH = "CONTENT_HASH_MISMATCH"
    MANIFEST_CLAIM_DISAGREES = "MANIFEST_CLAIM_DISAGREES"
    NO_ARTIFACTS = "NO_ARTIFACTS"

    # -- cache and bytes ---------------------------------------------------
    CACHE_BLOB_MISSING = "CACHE_BLOB_MISSING"
    CACHE_BLOB_CORRUPT = "CACHE_BLOB_CORRUPT"
    ARTIFACT_HASH_MISMATCH = "ARTIFACT_HASH_MISMATCH"
    ARTIFACT_LENGTH_MISMATCH = "ARTIFACT_LENGTH_MISMATCH"
    MISSING_RESPONSE_BODY = "MISSING_RESPONSE_BODY"
    REQUEST_KEY_COLLISION = "REQUEST_KEY_COLLISION"
    DUPLICATE_ARTIFACT_PATH = "DUPLICATE_ARTIFACT_PATH"
    CASE_COLLIDING_ARTIFACT_PATH = "CASE_COLLIDING_ARTIFACT_PATH"

    # -- path safety --------------------------------------------------------
    CREDENTIAL_IN_REQUEST_METADATA = "CREDENTIAL_IN_REQUEST_METADATA"
    UNSAFE_PATH = "UNSAFE_PATH"
    ABSOLUTE_PATH = "ABSOLUTE_PATH"
    PATH_TRAVERSAL = "PATH_TRAVERSAL"
    SYMLINK_PRESENT = "SYMLINK_PRESENT"
    SPECIAL_FILE_PRESENT = "SPECIAL_FILE_PRESENT"
    HARD_LINK_PRESENT = "HARD_LINK_PRESENT"

    # -- finalisation --------------------------------------------------------
    SNAPSHOT_ALREADY_EXISTS = "SNAPSHOT_ALREADY_EXISTS"
    DATASET_ID_ALREADY_CLAIMED = "DATASET_ID_ALREADY_CLAIMED"
    FINALIZE_FAILED = "FINALIZE_FAILED"
    STAGING_WRITE_FAILED = "STAGING_WRITE_FAILED"
    CROSS_FILESYSTEM_STAGING = "CROSS_FILESYSTEM_STAGING"

    # -- verification --------------------------------------------------------
    MANIFEST_MISSING = "MANIFEST_MISSING"
    MANIFEST_CORRUPT = "MANIFEST_CORRUPT"
    MANIFEST_UNKNOWN_FIELD = "MANIFEST_UNKNOWN_FIELD"
    MANIFEST_SCHEMA_VERSION = "MANIFEST_SCHEMA_VERSION"
    MANIFEST_HASH_MISMATCH = "MANIFEST_HASH_MISMATCH"
    SNAPSHOT_CONTENT_HASH_MISMATCH = "SNAPSHOT_CONTENT_HASH_MISMATCH"
    CHECKSUMS_MISSING = "CHECKSUMS_MISSING"
    CHECKSUMS_MALFORMED = "CHECKSUMS_MALFORMED"
    CHECKSUM_ESCAPES_ROOT = "CHECKSUM_ESCAPES_ROOT"
    UNSUPPORTED_HASH_ALGORITHM = "UNSUPPORTED_HASH_ALGORITHM"
    ARTIFACT_MISSING = "ARTIFACT_MISSING"
    UNEXPECTED_FILE = "UNEXPECTED_FILE"
    REQUESTS_LOG_MISSING = "REQUESTS_LOG_MISSING"
    REQUESTS_LOG_MALFORMED = "REQUESTS_LOG_MALFORMED"

    # -- policy ---------------------------------------------------------------
    SOURCE_POLICY_BLOCKED = "SOURCE_POLICY_BLOCKED"
    SOURCE_POLICY_UNAVAILABLE = "SOURCE_POLICY_UNAVAILABLE"
    STORAGE_NOT_PERMITTED = "STORAGE_NOT_PERMITTED"
    ACQUISITION_NOT_PERMITTED = "ACQUISITION_NOT_PERMITTED"

    # -- legacy import ---------------------------------------------------------
    LEGACY_SOURCE_MISSING = "LEGACY_SOURCE_MISSING"
    LEGACY_SOURCE_EMPTY = "LEGACY_SOURCE_EMPTY"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class SnapshotIssue:
    """One problem found while building or verifying a snapshot."""

    code: SnapshotIssueCode
    detail: str
    subject: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        return {"code": self.code.value, "detail": self.detail,
                "subject": self.subject}

    def render(self) -> str:
        return "%-34s %-44s %s" % (
            self.code.value, self.subject or "-", self.detail)


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


def safe_relative_path(value: str, where: str = "artifact path") -> str:
    """Return ``value`` if it is a safe, normalised, relative POSIX path.

    Refused: absolute paths, drive letters, backslashes, ``..`` and ``.``
    segments, empty segments, NUL and control characters, trailing separators,
    and anything that does not survive normalisation unchanged.

    The last rule is the one that matters most. Checking for ``..`` and then
    normalising would accept ``a/b/../c`` and store it as ``a/c``, so the
    manifest would describe a path the writer never wrote.
    """
    if not isinstance(value, str) or not value:
        raise SnapshotError("%s must be a non-empty string" % where,
                            SnapshotIssueCode.UNSAFE_PATH)
    for character in _FORBIDDEN_PATH_CHARS:
        if character in value:
            raise SnapshotError(
                "%s %r contains a forbidden character" % (where, value),
                SnapshotIssueCode.UNSAFE_PATH)
    if any(ord(character) < 32 for character in value):
        raise SnapshotError(
            "%s %r contains a control character" % (where, value),
            SnapshotIssueCode.UNSAFE_PATH)
    if value.startswith("/") or (len(value) > 1 and value[1] == ":"):
        raise SnapshotError(
            "%s %r is absolute; a snapshot manifest records relative paths only"
            % (where, value), SnapshotIssueCode.ABSOLUTE_PATH)
    segments = value.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        code = (SnapshotIssueCode.PATH_TRAVERSAL if ".." in segments
                else SnapshotIssueCode.UNSAFE_PATH)
        raise SnapshotError(
            "%s %r contains an empty, '.' or '..' segment" % (where, value), code)
    if len(segments) > _MAX_PATH_SEGMENTS:
        raise SnapshotError(
            "%s %r is nested %d levels deep; the limit is %d"
            % (where, value, len(segments), _MAX_PATH_SEGMENTS),
            SnapshotIssueCode.UNSAFE_PATH)
    for segment in segments:
        if len(segment) > _MAX_SEGMENT_LENGTH:
            raise SnapshotError(
                "%s %r has a segment longer than %d characters"
                % (where, value, _MAX_SEGMENT_LENGTH),
                SnapshotIssueCode.UNSAFE_PATH)
    if os.path.normpath(value) != value:
        raise SnapshotError(
            "%s %r is not in normalised form" % (where, value),
            SnapshotIssueCode.UNSAFE_PATH)
    return value


def _sha256_bytes(data: bytes) -> str:
    """``sha256:<lowercase hex>`` for exactly these bytes."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _sha256_file(path: str) -> Tuple[str, int]:
    """Return ``(digest, byte_length)`` for a file, read in chunks.

    Opened with ``O_NOFOLLOW`` so a symlink planted between the walk and the
    read cannot redirect the hash to another file.
    """
    digest = hashlib.sha256()
    length = 0
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        with io.open(descriptor, "rb", closefd=True) as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
                length += len(chunk)
    except BaseException:
        os.close(descriptor)
        raise
    return "sha256:" + digest.hexdigest(), length


# ---------------------------------------------------------------------------
# Descriptors and manifest
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RawArtifactDescriptor:
    """One file inside a snapshot, and what is known about it.

    ``content_identity`` is the half a rebuild must reproduce byte for byte.
    Everything else - the cache state it came from, when it was retrieved - is
    provenance, and lives in the manifest without entering the content hash.
    """

    relative_path: str
    artifact_kind: ArtifactKind
    byte_length: int
    sha256: str
    request_key: Optional[str] = None
    endpoint_id: Optional[str] = None
    page_number: Optional[int] = None
    cursor: Optional[str] = None
    content_type: Optional[str] = None
    retrieval_ref: Optional[str] = None
    source_relative_path: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "relative_path", safe_relative_path(self.relative_path))
        if not isinstance(self.artifact_kind, ArtifactKind):
            raise SnapshotError("artifact_kind must be an ArtifactKind")
        if isinstance(self.byte_length, bool) or not isinstance(self.byte_length, int):
            raise SnapshotError("byte_length must be an integer")
        if self.byte_length < 0:
            raise SnapshotError("byte_length must not be negative")
        _require_digest(self.sha256, "sha256")
        if self.source_relative_path is not None:
            object.__setattr__(
                self, "source_relative_path",
                safe_relative_path(self.source_relative_path,
                                   "source_relative_path"))

    def content_identity(self) -> Dict[str, Any]:
        """Only what a rebuild of the same bytes must reproduce.

        No content type, no cache state, no timestamp, no dataset ID. A live
        acquisition and a cache replay of the same responses return identical
        values here, which is what makes the snapshot content hash meaningful
        across both.
        """
        return {
            "relative_path": self.relative_path,
            "artifact_kind": self.artifact_kind.value,
            "sha256": self.sha256,
            "byte_length": self.byte_length,
            "request_key": self.request_key,
            "endpoint_id": self.endpoint_id,
            "page_number": self.page_number,
            "cursor": self.cursor,
        }

    def to_json(self) -> Dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "artifact_kind": self.artifact_kind.value,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
            "request_key": self.request_key,
            "endpoint_id": self.endpoint_id,
            "page_number": self.page_number,
            "cursor": self.cursor,
            "content_type": self.content_type,
            "retrieval_ref": self.retrieval_ref,
            "source_relative_path": self.source_relative_path,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any],
                  where: str) -> "RawArtifactDescriptor":
        if not isinstance(payload, Mapping):
            raise SnapshotError("%s must be an object" % where,
                                SnapshotIssueCode.MANIFEST_CORRUPT)
        unknown = sorted(set(payload) - set(cls.__slots__))
        if unknown:
            raise SnapshotError(
                "%s carries unknown key(s): %s" % (where, ", ".join(unknown)),
                SnapshotIssueCode.MANIFEST_UNKNOWN_FIELD)
        kind = payload.get("artifact_kind")
        try:
            artifact_kind = ArtifactKind(kind)
        except ValueError:
            raise SnapshotError(
                "%s.artifact_kind %r is not a known artifact kind" % (where, kind),
                SnapshotIssueCode.MANIFEST_CORRUPT) from None
        return cls(
            relative_path=payload.get("relative_path"),
            artifact_kind=artifact_kind,
            byte_length=payload.get("byte_length"),
            sha256=payload.get("sha256"),
            request_key=payload.get("request_key"),
            endpoint_id=payload.get("endpoint_id"),
            page_number=payload.get("page_number"),
            cursor=payload.get("cursor"),
            content_type=payload.get("content_type"),
            retrieval_ref=payload.get("retrieval_ref"),
            source_relative_path=payload.get("source_relative_path"))


def _require_digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise SnapshotError(
            "%s must be a sha256: digest, got %r" % (field_name, value))
    hex_part = value[len("sha256:"):]
    if len(hex_part) != 64 or any(ch not in "0123456789abcdef" for ch in hex_part):
        raise SnapshotError("%s is not 64 lowercase hex characters: %r"
                            % (field_name, value))
    return value


def snapshot_content_hash(
    source_key: str, descriptors: Sequence[RawArtifactDescriptor]
) -> str:
    """Digest of *what was captured*, independent of where and when.

    Excludes the dataset ID, the creation instant, the staging path, cache
    hit/miss state and retry timing. Entries are sorted by relative path, so
    the order files were written in cannot change the hash.

    The request log is excluded: it carries retrieval timestamps, which are
    provenance rather than content, and including it would make an otherwise
    identical cache replay hash differently.
    """
    entries = [descriptor.content_identity() for descriptor in descriptors
               if descriptor.artifact_kind is not ArtifactKind.REQUEST_LOG]
    entries.sort(key=lambda item: item["relative_path"])
    return sha256_digest({
        "snapshot_content_version": SNAPSHOT_CONTENT_VERSION,
        "source_key": source_key,
        "entry_count": len(entries),
        "entries": entries,
    })


def snapshot_manifest_hash(payload: Mapping[str, Any]) -> str:
    """Canonical digest of a manifest payload, excluding the hash field itself.

    Excluding ``manifest_hash`` is what stops the obvious cycle: a manifest
    cannot contain a digest computed over a document that contains that digest.
    Nothing else is excluded, so the dataset ID and the creation instant are
    both inside - which is why two dataset IDs over identical bytes share a
    content hash and differ here.
    """
    reduced = {key: value for key, value in payload.items()
               if key != "manifest_hash"}
    return sha256_digest(reduced)


#: Every key a snapshot manifest may carry.
_MANIFEST_KEYS = (
    "snapshot_manifest_version", "dataset_public_id", "source_key",
    "source_registry_id", "source_policy_status", "source_policy_content_hash",
    "snapshot_kind", "snapshot_state", "acquisition_run_id",
    "acquisition_status", "acquisition_content_hash", "acquisition_manifest_hash",
    "snapshot_content_hash", "manifest_hash", "created_at", "artifact_count",
    "total_byte_count", "artifacts", "request_log", "complete",
    "completeness_basis", "warnings", "limitations", "legacy_origin",
    "publication_eligible", "publication_gate", "scope_note",
)

SCOPE_NOTE = (
    "Raw source bytes only. These artifacts are exactly what the source "
    "returned; they are not canonical entities, not curated evidence, not "
    "interpretations, and not a scientifically approved dataset. Nothing here "
    "asserts release eligibility."
)


@dataclass(frozen=True)
class SnapshotManifest:
    """The machine-readable account of one snapshot.

    Immutable, and written exactly once - into the staging directory, before
    the atomic rename. There is no API that rewrites a sealed manifest.
    """

    dataset_public_id: str
    source_key: str
    snapshot_kind: SnapshotKind
    snapshot_state: SnapshotState
    created_at: _dt.datetime
    artifacts: Tuple[RawArtifactDescriptor, ...]
    request_log: Optional[RawArtifactDescriptor] = None
    snapshot_content_hash: str = ""
    manifest_hash: str = ""
    source_registry_id: Optional[str] = None
    source_policy_status: Optional[str] = None
    source_policy_content_hash: Optional[str] = None
    acquisition_run_id: Optional[str] = None
    acquisition_status: Optional[str] = None
    acquisition_content_hash: Optional[str] = None
    acquisition_manifest_hash: Optional[str] = None
    complete: bool = False
    completeness_basis: str = ""
    warnings: Tuple[str, ...] = ()
    limitations: Tuple[str, ...] = ()
    legacy_origin: Optional[Mapping[str, Any]] = None
    publication_eligible: bool = False
    publication_gate: Optional[Mapping[str, Any]] = None
    schema_version: str = SNAPSHOT_MANIFEST_VERSION

    def __post_init__(self) -> None:
        DatasetPublicId(self.dataset_public_id)
        object.__setattr__(self, "created_at",
                           ensure_utc(self.created_at, "created_at"))
        object.__setattr__(self, "artifacts", tuple(
            sorted(self.artifacts, key=lambda item: item.relative_path)))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "limitations", tuple(self.limitations))
        if self.publication_eligible and self.snapshot_state is SnapshotState.QUARANTINED:
            raise SnapshotError(
                "a QUARANTINED snapshot can never be publication eligible")
        if self.publication_eligible and self.snapshot_kind is SnapshotKind.LEGACY_IMPORT:
            raise SnapshotError(
                "a LEGACY_IMPORT snapshot can never be publication eligible: its "
                "acquisition provenance does not exist")

    @property
    def total_byte_count(self) -> int:
        """Bytes across every artifact, request log included."""
        total = sum(item.byte_length for item in self.artifacts)
        if self.request_log is not None:
            total += self.request_log.byte_length
        return total

    @property
    def artifact_count(self) -> int:
        """Response and legacy artifacts, excluding the request log."""
        return len(self.artifacts)

    def payload(self) -> Dict[str, Any]:
        """The manifest document, with ``manifest_hash`` as stored.

        Key order is fixed so the rendered file reads the same on every machine.
        The hash itself is computed over this payload minus that one field.
        """
        return {
            "snapshot_manifest_version": self.schema_version,
            "dataset_public_id": self.dataset_public_id,
            "source_key": self.source_key,
            "source_registry_id": self.source_registry_id,
            "source_policy_status": self.source_policy_status,
            "source_policy_content_hash": self.source_policy_content_hash,
            "snapshot_kind": self.snapshot_kind.value,
            "snapshot_state": self.snapshot_state.value,
            "acquisition_run_id": self.acquisition_run_id,
            "acquisition_status": self.acquisition_status,
            "acquisition_content_hash": self.acquisition_content_hash,
            "acquisition_manifest_hash": self.acquisition_manifest_hash,
            "snapshot_content_hash": self.snapshot_content_hash,
            "manifest_hash": self.manifest_hash,
            "created_at": self.created_at.astimezone(
                _dt.timezone.utc).isoformat().replace("+00:00", "Z"),
            "artifact_count": self.artifact_count,
            "total_byte_count": self.total_byte_count,
            "artifacts": [item.to_json() for item in self.artifacts],
            "request_log": (self.request_log.to_json()
                            if self.request_log is not None else None),
            "complete": self.complete,
            "completeness_basis": self.completeness_basis,
            "warnings": list(self.warnings),
            "limitations": list(self.limitations),
            "legacy_origin": (dict(self.legacy_origin)
                              if self.legacy_origin is not None else None),
            "publication_eligible": self.publication_eligible,
            "publication_gate": (dict(self.publication_gate)
                                 if self.publication_gate is not None else None),
            "scope_note": SCOPE_NOTE,
        }

    def with_hashes(self) -> "SnapshotManifest":
        """Return a copy carrying its computed content and manifest hashes."""
        content = snapshot_content_hash(self.source_key, self.artifacts)
        interim = _replace(self, snapshot_content_hash=content, manifest_hash="")
        digest = snapshot_manifest_hash(interim.payload())
        return _replace(interim, manifest_hash=digest)

    def render(self) -> str:
        """Exact manifest file text: two-space indent, one trailing newline."""
        return json.dumps(self.payload(), indent=2, ensure_ascii=False) + "\n"

    def summary(self) -> Dict[str, Any]:
        """A short view for a CLI that should not print every artifact."""
        return {
            "dataset_public_id": self.dataset_public_id,
            "source_key": self.source_key,
            "snapshot_kind": self.snapshot_kind.value,
            "snapshot_state": self.snapshot_state.value,
            "artifact_count": self.artifact_count,
            "total_byte_count": self.total_byte_count,
            "snapshot_content_hash": self.snapshot_content_hash,
            "manifest_hash": self.manifest_hash,
            "complete": self.complete,
            "publication_eligible": self.publication_eligible,
            "warning_count": len(self.warnings),
            "limitation_count": len(self.limitations),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "SnapshotManifest":
        """Rebuild a manifest from a parsed document, refusing unknown keys."""
        if not isinstance(payload, Mapping):
            raise SnapshotError("a snapshot manifest must be a JSON object",
                                SnapshotIssueCode.MANIFEST_CORRUPT)
        unknown = sorted(set(payload) - set(_MANIFEST_KEYS))
        if unknown:
            raise SnapshotError(
                "snapshot manifest carries unknown key(s): %s"
                % ", ".join(unknown), SnapshotIssueCode.MANIFEST_UNKNOWN_FIELD)
        version = payload.get("snapshot_manifest_version")
        if version != SNAPSHOT_MANIFEST_VERSION:
            raise SnapshotError(
                "snapshot manifest declares version %r; this build understands "
                "%r" % (version, SNAPSHOT_MANIFEST_VERSION),
                SnapshotIssueCode.MANIFEST_SCHEMA_VERSION)
        try:
            kind = SnapshotKind(payload.get("snapshot_kind"))
            state = SnapshotState(payload.get("snapshot_state"))
        except ValueError as exc:
            raise SnapshotError("snapshot manifest: %s" % exc,
                                SnapshotIssueCode.MANIFEST_CORRUPT) from None
        created = payload.get("created_at")
        if not isinstance(created, str):
            raise SnapshotError("snapshot manifest.created_at must be a string",
                                SnapshotIssueCode.MANIFEST_CORRUPT)
        text = created[:-1] + "+00:00" if created.endswith("Z") else created
        try:
            created_at = _dt.datetime.fromisoformat(text)
        except ValueError:
            raise SnapshotError(
                "snapshot manifest.created_at is not an ISO-8601 instant: %r"
                % created, SnapshotIssueCode.MANIFEST_CORRUPT) from None
        if created_at.tzinfo is None:
            raise SnapshotError(
                "snapshot manifest.created_at has no UTC offset",
                SnapshotIssueCode.MANIFEST_CORRUPT)
        artifacts_payload = payload.get("artifacts")
        if not isinstance(artifacts_payload, list):
            raise SnapshotError("snapshot manifest.artifacts must be an array",
                                SnapshotIssueCode.MANIFEST_CORRUPT)
        request_log_payload = payload.get("request_log")
        return cls(
            dataset_public_id=payload.get("dataset_public_id"),
            source_key=payload.get("source_key"),
            snapshot_kind=kind,
            snapshot_state=state,
            created_at=created_at,
            artifacts=tuple(
                RawArtifactDescriptor.from_json(item, "artifacts[%d]" % index)
                for index, item in enumerate(artifacts_payload)),
            request_log=(RawArtifactDescriptor.from_json(
                request_log_payload, "request_log")
                if request_log_payload else None),
            snapshot_content_hash=payload.get("snapshot_content_hash") or "",
            manifest_hash=payload.get("manifest_hash") or "",
            source_registry_id=payload.get("source_registry_id"),
            source_policy_status=payload.get("source_policy_status"),
            source_policy_content_hash=payload.get("source_policy_content_hash"),
            acquisition_run_id=payload.get("acquisition_run_id"),
            acquisition_status=payload.get("acquisition_status"),
            acquisition_content_hash=payload.get("acquisition_content_hash"),
            acquisition_manifest_hash=payload.get("acquisition_manifest_hash"),
            complete=bool(payload.get("complete", False)),
            completeness_basis=payload.get("completeness_basis") or "",
            warnings=tuple(payload.get("warnings") or ()),
            limitations=tuple(payload.get("limitations") or ()),
            legacy_origin=payload.get("legacy_origin"),
            publication_eligible=bool(payload.get("publication_eligible", False)),
            publication_gate=payload.get("publication_gate"),
            schema_version=version)


def _replace(manifest: SnapshotManifest, **changes: Any) -> SnapshotManifest:
    """Return a copy of ``manifest`` with the named fields changed.

    Hand-written rather than ``dataclasses.replace`` because the manifest is
    not a slots dataclass and the field list is long enough that a silent
    omission would be easy to miss.
    """
    values = {
        "dataset_public_id": manifest.dataset_public_id,
        "source_key": manifest.source_key,
        "snapshot_kind": manifest.snapshot_kind,
        "snapshot_state": manifest.snapshot_state,
        "created_at": manifest.created_at,
        "artifacts": manifest.artifacts,
        "request_log": manifest.request_log,
        "snapshot_content_hash": manifest.snapshot_content_hash,
        "manifest_hash": manifest.manifest_hash,
        "source_registry_id": manifest.source_registry_id,
        "source_policy_status": manifest.source_policy_status,
        "source_policy_content_hash": manifest.source_policy_content_hash,
        "acquisition_run_id": manifest.acquisition_run_id,
        "acquisition_status": manifest.acquisition_status,
        "acquisition_content_hash": manifest.acquisition_content_hash,
        "acquisition_manifest_hash": manifest.acquisition_manifest_hash,
        "complete": manifest.complete,
        "completeness_basis": manifest.completeness_basis,
        "warnings": manifest.warnings,
        "limitations": manifest.limitations,
        "legacy_origin": manifest.legacy_origin,
        "publication_eligible": manifest.publication_eligible,
        "publication_gate": manifest.publication_gate,
        "schema_version": manifest.schema_version,
    }
    values.update(changes)
    return SnapshotManifest(**values)


# ---------------------------------------------------------------------------
# Request log and checksum file
# ---------------------------------------------------------------------------

#: Query parameter names that must never reach a snapshot. WP-04 already
#: sanitises its query, so this is a second, independent check at the point of
#: writing bytes that will be kept forever.
_CREDENTIAL_NAMES = frozenset({
    "password", "passwd", "pwd", "secret", "token", "access_token",
    "refresh_token", "api_key", "apikey", "auth", "authorization", "key",
    "signature", "sig", "sessionid", "session_id", "credential",
})


def _assert_no_credentials(pairs: Sequence[Tuple[str, str]], subject: str) -> None:
    """Refuse a request log entry carrying a credential-shaped parameter.

    WP-04 sanitises its query before recording it, so reaching this check means
    something has changed upstream. Failing here is right: a snapshot is kept
    forever, and a secret written into one cannot be recalled.
    """
    for name, _value in pairs:
        if name.strip().lower().replace("-", "_") in _CREDENTIAL_NAMES:
            raise SnapshotError(
                "refusing to write request log for %s: query parameter %r looks "
                "like a credential and must never enter a snapshot"
                % (subject, name))


def _strip_query(url: str) -> str:
    """Return the URL without its query string or fragment.

    The parameters are recorded separately, from WP-04's sanitised list. A URL
    copied whole could carry a secret that the sanitised list deliberately
    excluded.
    """
    for separator in ("?", "#"):
        index = url.find(separator)
        if index >= 0:
            url = url[:index]
    return url


def render_requests_ndjson(entries: Sequence[Mapping[str, Any]]) -> str:
    """Render the request log: one canonical JSON object per line.

    Sorted by request key then page number, so two runs over the same responses
    produce the same file. Canonical JSON per line means sorted keys and fixed
    separators, so no incidental whitespace can differ.

    Returns ``""`` for an empty log - a legacy import made no requests, and a
    file containing a lone newline would claim otherwise.
    """
    if not entries:
        return ""
    ordered = sorted(entries, key=lambda item: (str(item.get("request_key") or ""),
                                                item.get("page_number") or 0,
                                                str(item.get("artifact_path") or "")))
    return "".join(canonical_json(entry) + "\n" for entry in ordered)


def render_checksums(entries: Sequence[Tuple[str, str]]) -> str:
    """Render ``checksums.sha256`` in ``sha256sum`` format.

    ``<64 hex>  <relative path>``, two spaces, sorted by path, one trailing
    newline. Deliberately compatible with the system tool, so a reviewer can
    verify a snapshot with ``sha256sum -c`` and no project code at all.

    The file lists ``requests.ndjson`` and every response artifact. It does not
    list ``manifest.json`` and does not list itself: the manifest records the
    checksum file's own digest, and a file that listed itself could never be
    written.
    """
    lines = []
    for relative_path, digest in sorted(entries):
        hex_part = _require_digest(digest, "checksum")[len("sha256:"):]
        lines.append("%s  %s\n" % (hex_part, relative_path))
    return "".join(lines)


def parse_checksums(text: str) -> Tuple[Dict[str, str], Tuple[SnapshotIssue, ...]]:
    """Parse a ``checksums.sha256`` file, reporting every malformed line.

    Reports rather than raises, because verification wants the whole list. A
    line whose path escapes the snapshot root is reported under its own code:
    that is not a typo, it is an attempt to make verification read a file
    outside the snapshot.
    """
    digests: Dict[str, str] = {}
    issues: List[SnapshotIssue] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            issues.append(SnapshotIssue(
                SnapshotIssueCode.CHECKSUMS_MALFORMED,
                "line %d is blank" % number))
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2:
            issues.append(SnapshotIssue(
                SnapshotIssueCode.CHECKSUMS_MALFORMED,
                "line %d is not '<hex>  <path>'" % number, line[:80]))
            continue
        hex_part, relative_path = parts[0].strip(), parts[1]
        if len(hex_part) != 64 or any(ch not in "0123456789abcdef" for ch in hex_part):
            issues.append(SnapshotIssue(
                SnapshotIssueCode.UNSUPPORTED_HASH_ALGORITHM,
                "line %d does not carry a 64-character lowercase SHA-256 digest; "
                "this project uses SHA-256 only" % number, relative_path))
            continue
        try:
            safe_relative_path(relative_path, "checksum path")
        except SnapshotError as exc:
            code = (SnapshotIssueCode.CHECKSUM_ESCAPES_ROOT
                    if exc.code in (SnapshotIssueCode.PATH_TRAVERSAL,
                                    SnapshotIssueCode.ABSOLUTE_PATH)
                    else SnapshotIssueCode.CHECKSUMS_MALFORMED)
            issues.append(SnapshotIssue(code, str(exc), relative_path))
            continue
        if relative_path in digests:
            issues.append(SnapshotIssue(
                SnapshotIssueCode.DUPLICATE_ARTIFACT_PATH,
                "line %d repeats a path already listed" % number, relative_path))
            continue
        digests[relative_path] = "sha256:" + hex_part
    return digests, tuple(issues)


# ---------------------------------------------------------------------------
# Requests and results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SnapshotBuildRequest:
    """Everything one build needs, stated explicitly.

    ``dataset_public_id`` is required and never derived. Scanning the raw root
    for "the next number" would be a race between two builders and would make a
    dataset's identity depend on what else happened to be on disk.
    """

    dataset_public_id: str
    source_key: str
    snapshot_kind: SnapshotKind
    acquisition_manifest: Optional[AcquisitionManifest] = None
    cache: Optional[ResponseCache] = None
    legacy_source_dir: Optional[str] = None
    legacy_origin: Optional[Mapping[str, Any]] = None
    #: For a TRANSCRIPTION_CAPTURE build: artifact base name -> exact bytes.
    #: Passed in memory rather than read from a directory, so the capture that
    #: is sealed is provably the capture the builder produced, with no window
    #: in which something else could edit the files in between.
    capture_files: Optional[Mapping[str, bytes]] = None
    #: One record per document this project read, in the order it read them.
    #: Written to requests.ndjson so the seal carries its own retrieval log.
    capture_reads: Tuple[Mapping[str, Any], ...] = ()
    limitations: Tuple[str, ...] = ()
    source_registry_id: Optional[str] = None
    source_policy_status: Optional[str] = None
    source_policy_content_hash: Optional[str] = None
    publication_gate: Optional[Mapping[str, Any]] = None

    def __post_init__(self) -> None:
        DatasetPublicId(self.dataset_public_id)
        if not isinstance(self.source_key, str) or not self.source_key.strip():
            raise SnapshotError("source_key must be a non-empty string")
        safe_relative_path(self.source_key, "source_key")
        if not isinstance(self.snapshot_kind, SnapshotKind):
            raise SnapshotError("snapshot_kind must be a SnapshotKind")
        object.__setattr__(self, "limitations", tuple(self.limitations))
        object.__setattr__(self, "capture_reads", tuple(self.capture_reads))
        if self.snapshot_kind is SnapshotKind.LEGACY_IMPORT:
            if not self.legacy_source_dir:
                raise SnapshotError(
                    "a LEGACY_IMPORT build needs legacy_source_dir")
        elif self.snapshot_kind is SnapshotKind.TRANSCRIPTION_CAPTURE:
            if not self.capture_files:
                raise SnapshotError(
                    "a TRANSCRIPTION_CAPTURE build needs capture_files")
            if self.acquisition_manifest is not None or self.cache is not None:
                raise SnapshotError(
                    "a TRANSCRIPTION_CAPTURE build has no acquisition run; "
                    "supplying one would claim retrieval metadata that does "
                    "not exist")
            if not self.capture_reads:
                raise SnapshotError(
                    "a TRANSCRIPTION_CAPTURE build must record which "
                    "documents were read; a capture with no retrieval log "
                    "cannot be traced back to anything")
            if not self.limitations:
                raise SnapshotError(
                    "a TRANSCRIPTION_CAPTURE build must state its limitations; "
                    "the whole point of the kind is what it cannot claim")
        else:
            if self.acquisition_manifest is None or self.cache is None:
                raise SnapshotError(
                    "an %s build needs both an acquisition manifest and the "
                    "cache holding its bytes" % self.snapshot_kind.value)


@dataclass(frozen=True)
class SnapshotBuildResult:
    """What a build produced, including a build that got partway.

    ``sealed`` and ``registered`` are separate on purpose. The filesystem seal
    and the database registration cannot be one transaction, so a snapshot can
    legitimately exist on disk while no ``DatasetVersion`` names it. Saying so
    is better than pretending the pair is atomic.
    """

    dataset_public_id: str
    snapshot_path: Optional[str]
    manifest: Optional[SnapshotManifest]
    sealed: bool
    issues: Tuple[SnapshotIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return self.sealed and not self.issues

    def to_json(self) -> Dict[str, Any]:
        return {
            "dataset_public_id": self.dataset_public_id,
            "snapshot_path": self.snapshot_path,
            "sealed": self.sealed,
            "manifest": (self.manifest.summary()
                         if self.manifest is not None else None),
            "issues": [issue.to_json() for issue in self.issues],
        }


@dataclass(frozen=True)
class SnapshotVerificationResult:
    """Whether a sealed snapshot still is what its manifest says.

    Collects every problem rather than stopping at the first. An operator
    investigating a corrupt snapshot needs to know whether one file changed or
    forty did.
    """

    dataset_public_id: Optional[str]
    snapshot_path: str
    manifest: Optional[SnapshotManifest]
    checked_artifacts: int = 0
    issues: Tuple[SnapshotIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def codes(self) -> Tuple[str, ...]:
        return tuple(sorted({issue.code.value for issue in self.issues}))

    def to_json(self) -> Dict[str, Any]:
        return {
            "dataset_public_id": self.dataset_public_id,
            "snapshot_path": self.snapshot_path,
            "ok": self.ok,
            "checked_artifacts": self.checked_artifacts,
            "manifest": (self.manifest.summary()
                         if self.manifest is not None else None),
            "issues": [issue.to_json() for issue in self.issues],
        }

    def render(self) -> str:
        lines = ["snapshot: %s" % self.snapshot_path,
                 "verified: %s" % ("yes" if self.ok else "NO"),
                 "artifacts checked: %d" % self.checked_artifacts]
        for issue in self.issues:
            lines.append("  " + issue.render())
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# The manager
# ---------------------------------------------------------------------------


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


class SnapshotManager:
    """Builds, seals and verifies raw snapshots under one raw root.

    Args:
        raw_root: directory holding ``<source-key>/<dataset-id>/`` trees. An
            explicit argument with no default at this level; the CLI supplies
            ``data/raw`` and a test supplies a temporary directory.
        clock: returns the current UTC instant. Injected so a test can pin the
            manifest's ``created_at`` and compare two builds byte for byte.
        token_factory: names the staging directory. Injected so a failure path
            can be reproduced exactly.

    The manager never mutates a sealed snapshot. There is no method that
    reopens one, and the only write it performs after the atomic rename is the
    ``chmod`` that makes the tree read-only.
    """

    def __init__(
        self,
        raw_root: str,
        clock: Callable[[], _dt.datetime] = _utc_now,
        token_factory: Optional[Callable[[], str]] = None,
    ) -> None:
        if not raw_root or not str(raw_root).strip():
            raise SnapshotError(
                "the raw root must be given explicitly; there is no default "
                "snapshot location")
        self._raw_root = os.path.abspath(os.path.expanduser(str(raw_root)))
        self._clock = clock
        self._token_factory = token_factory or (lambda: os.urandom(8).hex())

    @property
    def raw_root(self) -> str:
        return self._raw_root

    # -- paths ------------------------------------------------------------

    def snapshot_path(self, source_key: str, dataset_public_id: str) -> str:
        """Final directory for one snapshot. Never created by this call."""
        safe_relative_path(source_key, "source_key")
        DatasetPublicId(dataset_public_id)
        return os.path.join(self._raw_root, source_key, dataset_public_id)

    def exists(self, source_key: str, dataset_public_id: str) -> bool:
        """True when anything already occupies that dataset's final path."""
        return os.path.lexists(self.snapshot_path(source_key, dataset_public_id))

    # -- building ----------------------------------------------------------

    def build(self, request: SnapshotBuildRequest) -> SnapshotBuildResult:
        """Build and seal a snapshot, or fail without leaving one behind.

        The order is deliberate: everything that can be checked is checked
        before a byte is written, the bytes are then written into a staging
        directory beside the final one, and only a complete staging directory
        is renamed into place. A build that fails half way leaves no snapshot,
        because a half-snapshot that looked sealed would be worse than none.
        """
        final_path = self.snapshot_path(request.source_key,
                                        request.dataset_public_id)
        if os.path.lexists(final_path):
            return SnapshotBuildResult(
                request.dataset_public_id, final_path, None, False,
                (SnapshotIssue(
                    SnapshotIssueCode.SNAPSHOT_ALREADY_EXISTS,
                    "a snapshot already occupies this path. A dataset ID is "
                    "claimed once; a new acquisition needs a new ID, even when "
                    "the content is identical.", final_path),))

        if request.snapshot_kind is SnapshotKind.LEGACY_IMPORT:
            plan, issues = self._plan_legacy(request)
        elif request.snapshot_kind is SnapshotKind.TRANSCRIPTION_CAPTURE:
            plan, issues = self._plan_capture(request)
        else:
            plan, issues = self._plan_acquisition(request)
        if issues:
            return SnapshotBuildResult(
                request.dataset_public_id, None, None, False, tuple(issues))

        return self._materialise(request, plan, final_path)

    # -- planning ------------------------------------------------------------

    def _plan_acquisition(
        self, request: SnapshotBuildRequest
    ) -> Tuple[List[Tuple[RawArtifactDescriptor, bytes, Mapping[str, Any]]],
               List[SnapshotIssue]]:
        """Decide what an acquisition snapshot will contain, and read the bytes.

        Every check here fails the build rather than warning:

        * the run must be ``COMPLETE`` or ``COMPLETE_WITH_WARNINGS``;
        * every required endpoint must have completed with terminal pagination;
        * the recorded content hash must match one recomputed from the records;
        * every referenced blob must exist in the cache and hash to exactly the
          digest and length the retrieval record claims.
        """
        issues: List[SnapshotIssue] = []
        manifest = request.acquisition_manifest
        cache = request.cache

        if manifest.status is AcquisitionStatus.RUNNING:
            issues.append(SnapshotIssue(
                SnapshotIssueCode.ACQUISITION_RUNNING,
                "the acquisition run has not finished; a snapshot of a run in "
                "progress would capture an arbitrary prefix of it",
                manifest.run_id.to_json()))
        elif manifest.status is AcquisitionStatus.FAILED:
            issues.append(SnapshotIssue(
                SnapshotIssueCode.ACQUISITION_NOT_COMPLETE,
                "the acquisition run FAILED: %s"
                % ("; ".join(manifest.failures) or "no detail recorded"),
                manifest.run_id.to_json()))
        elif manifest.status not in (AcquisitionStatus.COMPLETE,
                                     AcquisitionStatus.COMPLETE_WITH_WARNINGS):
            issues.append(SnapshotIssue(
                SnapshotIssueCode.ACQUISITION_NOT_COMPLETE,
                "acquisition status %s cannot back a snapshot"
                % manifest.status.value, manifest.run_id.to_json()))

        for endpoint in manifest.endpoints:
            if not endpoint.required:
                continue
            if endpoint.blocks_completion:
                code = (SnapshotIssueCode.PAGINATION_NOT_TERMINAL
                        if not endpoint.pagination.terminal
                        else SnapshotIssueCode.REQUIRED_ENDPOINT_INCOMPLETE)
                issues.append(SnapshotIssue(
                    code,
                    "required endpoint did not complete (%s, pagination %s)"
                    % (endpoint.outcome.value,
                       endpoint.pagination.termination_reason),
                    endpoint.endpoint_id))

        if issues:
            return [], issues

        planned: List[Tuple[RawArtifactDescriptor, bytes, Mapping[str, Any]]] = []
        by_path: Dict[str, str] = {}
        by_folded_path: Dict[str, str] = {}

        for endpoint in sorted(manifest.endpoints,
                               key=lambda item: item.endpoint_id):
            for record in endpoint.records:
                if not record.succeeded or record.raw_sha256 is None:
                    continue
                relative_path = _response_path(record.request_key)
                folded = relative_path.casefold()

                if relative_path in by_path:
                    if by_path[relative_path] != record.raw_sha256:
                        issues.append(SnapshotIssue(
                            SnapshotIssueCode.REQUEST_KEY_COLLISION,
                            "two retrieval records share request key %s but "
                            "claim different content (%s and %s). One request "
                            "key names one response."
                            % (record.request_key, by_path[relative_path],
                               record.raw_sha256), relative_path))
                    continue
                if folded in by_folded_path and by_folded_path[folded] != relative_path:
                    issues.append(SnapshotIssue(
                        SnapshotIssueCode.CASE_COLLIDING_ARTIFACT_PATH,
                        "artifact path collides with %r on a case-insensitive "
                        "filesystem" % by_folded_path[folded], relative_path))
                    continue

                data, blob_issue = self._read_blob(cache, record)
                if blob_issue is not None:
                    issues.append(blob_issue)
                    continue

                descriptor = RawArtifactDescriptor(
                    relative_path=relative_path,
                    artifact_kind=ArtifactKind.RESPONSE_BODY,
                    byte_length=len(data),
                    sha256=record.raw_sha256,
                    request_key=record.request_key,
                    endpoint_id=record.endpoint_id,
                    page_number=record.page_number,
                    cursor=record.cursor,
                    content_type=record.content_type or None,
                    retrieval_ref=record.cache_blob_ref)
                try:
                    log_entry = _request_log_entry(record, relative_path)
                except SnapshotError as exc:
                    # Reported rather than raised, so the whole build's problems
                    # arrive together - and deliberately without echoing the
                    # offending value, which is the thing that must not be
                    # written down.
                    issues.append(SnapshotIssue(
                        SnapshotIssueCode.CREDENTIAL_IN_REQUEST_METADATA,
                        str(exc), record.request_key))
                    continue
                planned.append((descriptor, data, log_entry))
                by_path[relative_path] = record.raw_sha256
                by_folded_path[folded] = relative_path

        if not planned and not issues:
            issues.append(SnapshotIssue(
                SnapshotIssueCode.NO_ARTIFACTS,
                "the acquisition run recorded no successful retrieval; there is "
                "nothing to snapshot", manifest.run_id.to_json()))
        return planned, issues

    @staticmethod
    def _read_blob(cache, record):
        """Read one cached body and re-verify it against the retrieval record.

        The stored digest is recomputed from the bytes rather than trusted. A
        cache blob that was edited on disk, or truncated by a failed write, is
        exactly what this catches - and it is caught before those bytes reach a
        snapshot that will be kept forever.
        """
        # A blob that is absent and a blob whose bytes changed are different
        # problems for the operator - one is an incomplete cache, the other is
        # a corrupt one - so they are distinguished before either becomes an
        # issue. The cache reports both as one error type, so the distinction is
        # drawn here from what is actually on disk rather than from its message.
        missing = not os.path.isfile(cache.blob_path(record.raw_sha256))
        try:
            data = cache.load_blob(record.raw_sha256)
        except Exception as exc:  # noqa: BLE001 - cache raises several types
            code = (SnapshotIssueCode.CACHE_BLOB_MISSING if missing
                    else SnapshotIssueCode.CACHE_BLOB_CORRUPT)
            return None, SnapshotIssue(
                code, "cannot read cached body for %s: %s"
                % (record.request_key, exc), record.raw_sha256)

        actual = _sha256_bytes(data)
        if actual != record.raw_sha256:
            return None, SnapshotIssue(
                SnapshotIssueCode.ARTIFACT_HASH_MISMATCH,
                "cached body for %s hashes to %s, but the retrieval record "
                "claims %s" % (record.request_key, actual, record.raw_sha256),
                record.request_key)
        if len(data) != record.byte_length:
            return None, SnapshotIssue(
                SnapshotIssueCode.ARTIFACT_LENGTH_MISMATCH,
                "cached body for %s is %d bytes; the retrieval record claims %d"
                % (record.request_key, len(data), record.byte_length),
                record.request_key)
        return data, None

    def _plan_capture(
        self, request: SnapshotBuildRequest
    ) -> Tuple[List[Tuple[RawArtifactDescriptor, bytes, Mapping[str, Any]]],
               List[SnapshotIssue]]:
        """Decide what a transcription capture will contain.

        The bytes arrive in memory rather than from a directory. That is the
        one real difference from a legacy import, and it removes a window: a
        directory read between planning and writing can change, and a capture
        that sealed different bytes than the ones the builder produced would be
        a seal over something nobody inspected.

        ``ArtifactKind.RESPONSE_BODY`` is deliberately **not** used. These are
        not response bodies - no HTTP response was preserved - and the kind is
        read by anything that wants to know whether an upstream byte stream
        exists. ``LEGACY_FILE`` is the honest choice among the three: a file
        this project holds whose bytes have no upstream counterpart to compare
        against.
        """
        issues: List[SnapshotIssue] = []
        planned: List[Tuple[RawArtifactDescriptor, bytes, Mapping[str, Any]]] = []
        seen: Dict[str, str] = {}
        for name in sorted(request.capture_files or {}):
            data = (request.capture_files or {})[name]
            if not isinstance(data, bytes):
                issues.append(SnapshotIssue(
                    SnapshotIssueCode.MISSING_RESPONSE_BODY,
                    "capture file %r is %s, not bytes; a capture seals exact "
                    "bytes and never a re-encoding of them"
                    % (name, type(data).__name__), name))
                continue
            try:
                artifact_path = safe_relative_path(
                    RESPONSES_DIR + "/" + name, "capture artifact path")
            except SnapshotError as exc:
                issues.append(SnapshotIssue(
                    exc.code or SnapshotIssueCode.UNSAFE_PATH, str(exc), name))
                continue
            folded = artifact_path.casefold()
            if folded in seen:
                issues.append(SnapshotIssue(
                    SnapshotIssueCode.CASE_COLLIDING_ARTIFACT_PATH,
                    "capture file collides with %r on a case-insensitive "
                    "filesystem" % seen[folded], artifact_path))
                continue
            planned.append((
                RawArtifactDescriptor(
                    relative_path=artifact_path,
                    artifact_kind=ArtifactKind.LEGACY_FILE,
                    byte_length=len(data),
                    sha256=_sha256_bytes(data),
                    content_type=_guess_content_type(name),
                    source_relative_path=None),
                data,
                {}))
            seen[folded] = artifact_path

        if not planned and not issues:
            issues.append(SnapshotIssue(
                SnapshotIssueCode.NO_ARTIFACTS,
                "a capture with no artifacts seals nothing", ""))
        return planned, issues

    def _plan_legacy(
        self, request: SnapshotBuildRequest
    ) -> Tuple[List[Tuple[RawArtifactDescriptor, bytes, Mapping[str, Any]]],
               List[SnapshotIssue]]:
        """Decide what a legacy import will contain, reading the source tree.

        The source directory is read and never written. Symlinks and special
        files are refused rather than followed: a snapshot that contains a
        symlink is a snapshot whose contents can change without it changing.
        """
        issues: List[SnapshotIssue] = []
        source_dir = os.path.abspath(os.path.expanduser(request.legacy_source_dir))
        if not os.path.isdir(source_dir):
            return [], [SnapshotIssue(
                SnapshotIssueCode.LEGACY_SOURCE_MISSING,
                "no such legacy directory", source_dir)]

        planned: List[Tuple[RawArtifactDescriptor, bytes, Mapping[str, Any]]] = []
        by_folded_path: Dict[str, str] = {}
        for absolute, relative in _walk_files(source_dir, issues):
            try:
                artifact_path = safe_relative_path(
                    RESPONSES_DIR + "/" + relative, "legacy artifact path")
            except SnapshotError as exc:
                issues.append(SnapshotIssue(
                    exc.code or SnapshotIssueCode.UNSAFE_PATH, str(exc), relative))
                continue
            folded = artifact_path.casefold()
            if folded in by_folded_path:
                issues.append(SnapshotIssue(
                    SnapshotIssueCode.CASE_COLLIDING_ARTIFACT_PATH,
                    "legacy file collides with %r on a case-insensitive "
                    "filesystem" % by_folded_path[folded], artifact_path))
                continue
            digest, length = _sha256_file(absolute)
            with io.open(absolute, "rb") as handle:
                data = handle.read()
            if len(data) != length or _sha256_bytes(data) != digest:
                issues.append(SnapshotIssue(
                    SnapshotIssueCode.ARTIFACT_HASH_MISMATCH,
                    "the legacy file changed while it was being read", relative))
                continue
            planned.append((
                RawArtifactDescriptor(
                    relative_path=artifact_path,
                    artifact_kind=ArtifactKind.LEGACY_FILE,
                    byte_length=length,
                    sha256=digest,
                    content_type=_guess_content_type(relative),
                    source_relative_path=relative),
                data,
                {}))
            by_folded_path[folded] = artifact_path

        if not planned and not issues:
            issues.append(SnapshotIssue(
                SnapshotIssueCode.LEGACY_SOURCE_EMPTY,
                "the legacy directory holds no regular files", source_dir))
        return planned, issues

    # -- materialising -------------------------------------------------------

    def _materialise(
        self,
        request: SnapshotBuildRequest,
        planned: Sequence[Tuple[RawArtifactDescriptor, bytes, Mapping[str, Any]]],
        final_path: str,
    ) -> SnapshotBuildResult:
        """Write the staging tree, then rename it into place atomically.

        Staging lives in the *same parent directory* as the final path, which
        is what makes the rename atomic: a rename across filesystems is a copy
        and a delete, and there is a window in the middle where a reader sees a
        half-written snapshot.

        Finalisation deliberately does not use ``os.replace``. ``replace``
        overwrites its target, and overwriting a sealed snapshot is the one
        thing this module exists to prevent. ``os.rename`` refuses a non-empty
        target, and an *empty* directory left by a concurrent builder is
        excluded by the exclusive claim taken below.
        """
        parent = os.path.dirname(final_path)
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as exc:
            return SnapshotBuildResult(
                request.dataset_public_id, None, None, False,
                (SnapshotIssue(SnapshotIssueCode.STAGING_WRITE_FAILED,
                               "cannot create %s: %s" % (parent, exc), parent),))

        claim_path = final_path + ".claim"
        try:
            claim = os.open(claim_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return SnapshotBuildResult(
                request.dataset_public_id, final_path, None, False,
                (SnapshotIssue(
                    SnapshotIssueCode.DATASET_ID_ALREADY_CLAIMED,
                    "another builder holds the claim on this dataset ID. Two "
                    "builders must not race for one identity; retry with a "
                    "different ID, or remove the stale claim after checking no "
                    "build is running.", claim_path),))
        except OSError as exc:
            return SnapshotBuildResult(
                request.dataset_public_id, None, None, False,
                (SnapshotIssue(SnapshotIssueCode.STAGING_WRITE_FAILED,
                               "cannot claim %s: %s" % (claim_path, exc)),))
        os.close(claim)

        staging = None
        try:
            staging = tempfile.mkdtemp(
                prefix=".staging-%s-%s-" % (request.dataset_public_id,
                                            self._token_factory()),
                dir=parent)
            manifest = self._write_staging(request, planned, staging)

            # Re-check under the claim: a snapshot that appeared while this
            # build was writing must not be replaced.
            if os.path.lexists(final_path):
                raise SnapshotError(
                    "a snapshot appeared at %s while this build was staging"
                    % final_path, SnapshotIssueCode.SNAPSHOT_ALREADY_EXISTS)
            try:
                os.rename(staging, final_path)
            except OSError as exc:
                code = (SnapshotIssueCode.SNAPSHOT_ALREADY_EXISTS
                        if exc.errno in (errno.ENOTEMPTY, errno.EEXIST,
                                         errno.ENOTDIR)
                        else SnapshotIssueCode.FINALIZE_FAILED)
                raise SnapshotError(
                    "cannot finalise %s: %s" % (final_path, exc), code) from exc
            staging = None
            _make_read_only(final_path)
            return SnapshotBuildResult(request.dataset_public_id, final_path,
                                       manifest, True, ())
        except SnapshotError as exc:
            return SnapshotBuildResult(
                request.dataset_public_id, None, None, False,
                (SnapshotIssue(exc.code or SnapshotIssueCode.STAGING_WRITE_FAILED,
                               str(exc), request.dataset_public_id),))
        except OSError as exc:
            return SnapshotBuildResult(
                request.dataset_public_id, None, None, False,
                (SnapshotIssue(SnapshotIssueCode.STAGING_WRITE_FAILED,
                               "write failed while staging: %s" % exc,
                               request.dataset_public_id),))
        finally:
            if staging is not None:
                _remove_tree(staging)
            try:
                os.unlink(claim_path)
            except OSError:  # pragma: no cover - claim already gone
                pass

    def _write_staging(
        self,
        request: SnapshotBuildRequest,
        planned: Sequence[Tuple[RawArtifactDescriptor, bytes, Mapping[str, Any]]],
        staging: str,
    ) -> SnapshotManifest:
        """Write every file of a snapshot into the staging directory.

        Order matters. The response bodies and the request log are written
        first, because the checksum file covers them; the checksum file is
        written next, because the manifest records its digest; the manifest is
        written last, because it records everything else. Nothing points back
        at the manifest, so there is no cycle to special-case.
        """
        checksum_entries: List[Tuple[str, str]] = []
        log_entries: List[Mapping[str, Any]] = []
        descriptors: List[RawArtifactDescriptor] = []

        for descriptor, data, log_entry in planned:
            target = os.path.join(staging, *descriptor.relative_path.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            _write_bytes(target, data)
            written_digest, written_length = _sha256_file(target)
            if written_digest != descriptor.sha256 or written_length != descriptor.byte_length:
                raise SnapshotError(
                    "the bytes written for %s do not match the bytes planned "
                    "(%s/%d written, %s/%d planned)"
                    % (descriptor.relative_path, written_digest, written_length,
                       descriptor.sha256, descriptor.byte_length),
                    SnapshotIssueCode.ARTIFACT_HASH_MISMATCH)
            descriptors.append(descriptor)
            checksum_entries.append((descriptor.relative_path, descriptor.sha256))
            if log_entry:
                log_entries.append(log_entry)

        # A capture's retrieval log is not per-artifact: one document read can
        # contribute rows to several artifacts, and several documents can
        # contribute to one. So the reads are recorded as they happened rather
        # than being reconstructed from the files they ended up in.
        if request.snapshot_kind is SnapshotKind.TRANSCRIPTION_CAPTURE:
            log_entries = list(request.capture_reads)
        requests_text = render_requests_ndjson(log_entries)
        requests_bytes = requests_text.encode("utf-8")
        requests_path = os.path.join(staging, REQUESTS_FILE)
        _write_bytes(requests_path, requests_bytes)
        request_log = RawArtifactDescriptor(
            relative_path=REQUESTS_FILE,
            artifact_kind=ArtifactKind.REQUEST_LOG,
            byte_length=len(requests_bytes),
            sha256=_sha256_bytes(requests_bytes),
            content_type="application/x-ndjson")
        checksum_entries.append((REQUESTS_FILE, request_log.sha256))

        checksums_bytes = render_checksums(checksum_entries).encode("utf-8")
        _write_bytes(os.path.join(staging, CHECKSUMS_FILE), checksums_bytes)

        state = (SnapshotState.QUARANTINED
                 if request.snapshot_kind is SnapshotKind.LEGACY_IMPORT
                 else SnapshotState.SEALED)
        acquisition = request.acquisition_manifest
        complete, basis, warnings = _completeness(request, acquisition)

        manifest = SnapshotManifest(
            dataset_public_id=request.dataset_public_id,
            source_key=request.source_key,
            snapshot_kind=request.snapshot_kind,
            snapshot_state=state,
            created_at=self._clock(),
            artifacts=tuple(descriptors),
            request_log=request_log,
            source_registry_id=request.source_registry_id,
            source_policy_status=request.source_policy_status,
            source_policy_content_hash=request.source_policy_content_hash,
            acquisition_run_id=(acquisition.run_id.to_json()
                                if acquisition is not None else None),
            acquisition_status=(acquisition.status.value
                                if acquisition is not None else None),
            acquisition_content_hash=(acquisition.content_hash
                                      if acquisition is not None else None),
            acquisition_manifest_hash=(sha256_digest(acquisition.to_json())
                                       if acquisition is not None else None),
            complete=complete,
            completeness_basis=basis,
            warnings=warnings,
            limitations=request.limitations,
            legacy_origin=request.legacy_origin,
            publication_eligible=False,
            publication_gate=request.publication_gate).with_hashes()

        _write_bytes(os.path.join(staging, MANIFEST_FILE),
                     manifest.render().encode("utf-8"))
        return manifest

    # -- verification ---------------------------------------------------------

    def verify_path(
        self,
        snapshot_path: str,
        schema_validator: Optional[Callable[[Mapping[str, Any]],
                                            Sequence[str]]] = None,
    ) -> SnapshotVerificationResult:
        """Re-derive everything a sealed snapshot claims, from its own bytes.

        Independent of how the snapshot was built: it reads the manifest, walks
        the tree without following symlinks, re-hashes every file, and compares
        against both the manifest and ``checksums.sha256``. A file that was
        changed, removed or added is reported, and so is a manifest whose own
        digest no longer matches its payload.

        ``schema_validator`` is injected rather than imported. Loading the
        published JSON Schema means reading a file, which belongs to the
        application layer; taking the check as an argument keeps this package
        free of that dependency while still letting the CLI enforce the schema
        on every verification.
        """
        issues: List[SnapshotIssue] = []
        path = os.path.abspath(os.path.expanduser(snapshot_path))
        manifest_path = os.path.join(path, MANIFEST_FILE)
        if not os.path.isdir(path):
            return SnapshotVerificationResult(
                None, path, None, 0,
                (SnapshotIssue(SnapshotIssueCode.MANIFEST_MISSING,
                               "no such snapshot directory", path),))
        if not os.path.isfile(manifest_path):
            return SnapshotVerificationResult(
                None, path, None, 0,
                (SnapshotIssue(SnapshotIssueCode.MANIFEST_MISSING,
                               "no manifest.json in the snapshot", path),))

        try:
            with io.open(manifest_path, encoding="utf-8") as handle:
                payload = json.loads(handle.read())
        except ValueError as exc:
            return SnapshotVerificationResult(
                None, path, None, 0,
                (SnapshotIssue(SnapshotIssueCode.MANIFEST_CORRUPT,
                               "manifest.json is not valid JSON: %s" % exc,
                               manifest_path),))
        except OSError as exc:
            return SnapshotVerificationResult(
                None, path, None, 0,
                (SnapshotIssue(SnapshotIssueCode.MANIFEST_MISSING,
                               "cannot read manifest.json: %s" % exc,
                               manifest_path),))

        try:
            manifest = SnapshotManifest.from_payload(payload)
        except SnapshotError as exc:
            return SnapshotVerificationResult(
                None, path, None, 0,
                (SnapshotIssue(exc.code or SnapshotIssueCode.MANIFEST_CORRUPT,
                               str(exc), manifest_path),))

        if schema_validator is not None:
            for problem in schema_validator(payload):
                issues.append(SnapshotIssue(
                    SnapshotIssueCode.MANIFEST_CORRUPT,
                    "manifest does not satisfy the published schema: %s" % problem,
                    manifest_path))

        issues.extend(_verify_manifest_identity(manifest, payload))
        checksums, checksum_issues = _read_checksums(path)
        issues.extend(checksum_issues)
        checked, walk_issues = _verify_tree(path, manifest, checksums)
        issues.extend(walk_issues)

        return SnapshotVerificationResult(
            manifest.dataset_public_id, path, manifest, checked, tuple(issues))

    def verify(
        self,
        source_key: str,
        dataset_public_id: str,
        schema_validator: Optional[Callable[[Mapping[str, Any]],
                                            Sequence[str]]] = None,
    ) -> SnapshotVerificationResult:
        """Verify the snapshot at the canonical path for this dataset ID."""
        return self.verify_path(
            self.snapshot_path(source_key, dataset_public_id), schema_validator)

    def inspect_path(self, snapshot_path: str) -> SnapshotManifest:
        """Read a snapshot's manifest without re-hashing its files."""
        manifest_path = os.path.join(
            os.path.abspath(os.path.expanduser(snapshot_path)), MANIFEST_FILE)
        try:
            with io.open(manifest_path, encoding="utf-8") as handle:
                payload = json.loads(handle.read())
        except OSError as exc:
            raise SnapshotError("cannot read %s: %s" % (manifest_path, exc),
                                SnapshotIssueCode.MANIFEST_MISSING) from exc
        except ValueError as exc:
            raise SnapshotError("%s is not valid JSON: %s" % (manifest_path, exc),
                                SnapshotIssueCode.MANIFEST_CORRUPT) from exc
        return SnapshotManifest.from_payload(payload)

    def inspect(self, source_key: str, dataset_public_id: str) -> SnapshotManifest:
        """Read the manifest at the canonical path for this dataset ID."""
        return self.inspect_path(self.snapshot_path(source_key, dataset_public_id))

    def list_snapshots(self) -> Tuple[Tuple[str, str], ...]:
        """Return ``(source_key, dataset_public_id)`` for every sealed snapshot."""
        found: List[Tuple[str, str]] = []
        if not os.path.isdir(self._raw_root):
            return ()
        for source_key in sorted(os.listdir(self._raw_root)):
            source_dir = os.path.join(self._raw_root, source_key)
            if not os.path.isdir(source_dir) or os.path.islink(source_dir):
                continue
            for dataset_id in sorted(os.listdir(source_dir)):
                candidate = os.path.join(source_dir, dataset_id)
                if not os.path.isdir(candidate) or os.path.islink(candidate):
                    continue
                if os.path.isfile(os.path.join(candidate, MANIFEST_FILE)):
                    found.append((source_key, dataset_id))
        return tuple(found)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _response_path(request_key: str) -> str:
    """Relative path of the artifact holding one request's response body.

    Named by the request key's hex, so the file name is derived from what was
    asked rather than from the order pages arrived in. A request key is a
    SHA-256 digest, so the name is fixed-length, safe, and free of anything a
    URL might have carried.
    """
    if not isinstance(request_key, str) or not request_key.startswith("sha256:"):
        raise SnapshotError(
            "a request key must be a sha256: digest, got %r" % (request_key,),
            SnapshotIssueCode.UNSAFE_PATH)
    hex_part = request_key[len("sha256:"):]
    if len(hex_part) != 64 or any(ch not in "0123456789abcdef" for ch in hex_part):
        raise SnapshotError("malformed request key %r" % (request_key,),
                            SnapshotIssueCode.UNSAFE_PATH)
    return "%s/%s.json" % (RESPONSES_DIR, hex_part)


def _request_log_entry(record, relative_path: str) -> Dict[str, Any]:
    """One ``requests.ndjson`` line: safe request and provenance metadata.

    The URL's query is stripped and replaced by WP-04's sanitised parameter
    list, which preserves repeated parameters as ordered pairs. Timestamps and
    retry counts stay - they are provenance an operator needs - and they are
    the reason the request log is excluded from the snapshot content hash.
    """
    _assert_no_credentials(record.safe_query, record.request_key)
    return {
        "request_key": record.request_key,
        "endpoint_id": record.endpoint_id,
        "method": record.method,
        "url": _strip_query(record.url),
        "query": [list(pair) for pair in record.safe_query],
        "page_number": record.page_number,
        "cursor": record.cursor,
        "status_code": record.status_code,
        "content_type": record.content_type,
        "byte_length": record.byte_length,
        "artifact_path": relative_path,
        "artifact_sha256": record.raw_sha256,
        "cache_state": record.cache_state.value,
        "retrieved_at": record.completed_at.astimezone(
            _dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "retry_count": record.retry_count,
    }


def _completeness(
    request: SnapshotBuildRequest, acquisition: Optional[AcquisitionManifest]
) -> Tuple[bool, str, Tuple[str, ...]]:
    """Derive the completeness declaration from the inputs, never from a flag.

    A legacy import is never complete: nobody knows what fraction of the
    upstream source it represents, and saying "complete" because a directory
    was fully copied would answer a different question than the one asked.
    """
    if acquisition is None:
        return (False,
                "no acquisition run backs this snapshot; completeness relative "
                "to the upstream source is unknown and is not inferred from "
                "the fact that every file present was copied",
                ())
    warnings = tuple(acquisition.warnings)
    if acquisition.status is AcquisitionStatus.COMPLETE:
        return (True,
                "every required endpoint completed with terminal pagination, "
                "recomputed from the retrieval records rather than read from "
                "the manifest's status field",
                warnings)
    return (True,
            "every required endpoint completed; %d optional-endpoint warning(s) "
            "are preserved and do not affect required completeness"
            % len(warnings),
            warnings)


def _guess_content_type(relative_path: str) -> Optional[str]:
    """A content type inferred from the file extension, or ``None``.

    Only used for legacy imports, where no response header exists. Deliberately
    a tiny fixed table rather than ``mimetypes``: the platform's mapping varies
    between machines, and a manifest field that changed with the host would
    break deterministic rebuilds.
    """
    lowered = relative_path.lower()
    if lowered.endswith(".json"):
        return "application/json"
    if lowered.endswith(".csv"):
        return "text/csv"
    if lowered.endswith(".ndjson"):
        return "application/x-ndjson"
    if lowered.endswith(".txt"):
        return "text/plain"
    return None


def _walk_files(root: str, issues: List[SnapshotIssue]):
    """Yield ``(absolute, relative)`` for every regular file under ``root``.

    Symlinks and special files are reported and skipped, never followed. A
    snapshot built by following a symlink would have contents that can change
    without the snapshot changing, which is the opposite of what it is for.
    """
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        directory_names.sort()
        for name in sorted(directory_names):
            absolute = os.path.join(current, name)
            if os.path.islink(absolute):
                issues.append(SnapshotIssue(
                    SnapshotIssueCode.SYMLINK_PRESENT,
                    "the source tree contains a symlinked directory",
                    os.path.relpath(absolute, root)))
        for name in sorted(file_names):
            absolute = os.path.join(current, name)
            relative = os.path.relpath(absolute, root).replace(os.sep, "/")
            info = os.lstat(absolute)
            if stat.S_ISLNK(info.st_mode):
                issues.append(SnapshotIssue(
                    SnapshotIssueCode.SYMLINK_PRESENT,
                    "the source tree contains a symlink", relative))
                continue
            if not stat.S_ISREG(info.st_mode):
                issues.append(SnapshotIssue(
                    SnapshotIssueCode.SPECIAL_FILE_PRESENT,
                    "the source tree contains a socket, device or FIFO",
                    relative))
                continue
            yield absolute, relative


def _write_bytes(path: str, data: bytes) -> None:
    """Write exactly these bytes, creating no intermediate representation.

    ``O_EXCL`` because every file in a staging tree is written once; a second
    write to the same path would mean two artifacts claimed one name.
    """
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o644)
    with io.open(descriptor, "wb", closefd=True) as handle:
        handle.write(data)


def _make_read_only(root: str) -> None:
    """Make a sealed tree read-only, where the platform permits.

    Best effort and honestly so. This stops an accidental write and a careless
    script; it does not stop the directory's owner, who can chmod it back. That
    is why :meth:`SnapshotManager.verify_path` exists and why the manifest
    carries the hashes it needs.
    """
    for current, directory_names, file_names in os.walk(root, topdown=False,
                                                        followlinks=False):
        for name in file_names:
            try:
                os.chmod(os.path.join(current, name), _READ_ONLY_FILE)
            except OSError:  # pragma: no cover - platform dependent
                pass
        for name in directory_names:
            try:
                os.chmod(os.path.join(current, name), _READ_ONLY_DIR)
            except OSError:  # pragma: no cover - platform dependent
                pass
    try:
        os.chmod(root, _READ_ONLY_DIR)
    except OSError:  # pragma: no cover - platform dependent
        pass


def _remove_tree(root: str) -> None:
    """Remove a *staging* tree. Never called on a sealed snapshot.

    Written out rather than using ``shutil.rmtree`` so the intent is visible at
    the call site: this function exists to clean up after a failed build, and
    the only path it is ever given is a temporary directory this process
    created moments earlier.
    """
    for current, directory_names, file_names in os.walk(root, topdown=False,
                                                        followlinks=False):
        for name in file_names:
            try:
                os.chmod(os.path.join(current, name), 0o600)
            except OSError:  # pragma: no cover - best effort
                pass
            try:
                os.unlink(os.path.join(current, name))
            except OSError:  # pragma: no cover - best effort
                pass
        for name in directory_names:
            try:
                os.rmdir(os.path.join(current, name))
            except OSError:  # pragma: no cover - best effort
                pass
    try:
        os.rmdir(root)
    except OSError:  # pragma: no cover - best effort
        pass


def _verify_manifest_identity(
    manifest: SnapshotManifest, payload: Mapping[str, Any]
) -> List[SnapshotIssue]:
    """Recompute the manifest and content hashes rather than trusting them."""
    issues: List[SnapshotIssue] = []
    recomputed_manifest = snapshot_manifest_hash(payload)
    if manifest.manifest_hash and recomputed_manifest != manifest.manifest_hash:
        issues.append(SnapshotIssue(
            SnapshotIssueCode.MANIFEST_HASH_MISMATCH,
            "the manifest records %s but its payload digests to %s"
            % (manifest.manifest_hash, recomputed_manifest),
            manifest.dataset_public_id))
    recomputed_content = snapshot_content_hash(manifest.source_key,
                                               manifest.artifacts)
    if (manifest.snapshot_content_hash
            and recomputed_content != manifest.snapshot_content_hash):
        issues.append(SnapshotIssue(
            SnapshotIssueCode.SNAPSHOT_CONTENT_HASH_MISMATCH,
            "the manifest records content hash %s but its artifact descriptors "
            "digest to %s" % (manifest.snapshot_content_hash, recomputed_content),
            manifest.dataset_public_id))
    return issues


def _read_checksums(path: str) -> Tuple[Dict[str, str], List[SnapshotIssue]]:
    checksums_path = os.path.join(path, CHECKSUMS_FILE)
    if not os.path.isfile(checksums_path):
        return {}, [SnapshotIssue(SnapshotIssueCode.CHECKSUMS_MISSING,
                                  "no checksums.sha256 in the snapshot", path)]
    try:
        with io.open(checksums_path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        return {}, [SnapshotIssue(SnapshotIssueCode.CHECKSUMS_MISSING,
                                  "cannot read checksums.sha256: %s" % exc, path)]
    digests, issues = parse_checksums(text)
    return digests, list(issues)


def _verify_tree(
    path: str, manifest: SnapshotManifest, checksums: Mapping[str, str]
) -> Tuple[int, List[SnapshotIssue]]:
    """Re-hash every file on disk and reconcile it three ways.

    Against the manifest's descriptors, against ``checksums.sha256``, and
    against the set of files that should exist at all. A file that is missing,
    changed, added, symlinked or hard-linked is reported; nothing is repaired.
    """
    issues: List[SnapshotIssue] = []
    expected: Dict[str, RawArtifactDescriptor] = {
        item.relative_path: item for item in manifest.artifacts}
    if manifest.request_log is not None:
        expected[manifest.request_log.relative_path] = manifest.request_log

    on_disk: Dict[str, Tuple[str, int]] = {}
    for current, directory_names, file_names in os.walk(path, followlinks=False):
        for name in sorted(directory_names):
            absolute = os.path.join(current, name)
            if os.path.islink(absolute):
                issues.append(SnapshotIssue(
                    SnapshotIssueCode.SYMLINK_PRESENT,
                    "a symlinked directory is present in a sealed snapshot",
                    os.path.relpath(absolute, path)))
        for name in sorted(file_names):
            absolute = os.path.join(current, name)
            relative = os.path.relpath(absolute, path).replace(os.sep, "/")
            info = os.lstat(absolute)
            if stat.S_ISLNK(info.st_mode):
                issues.append(SnapshotIssue(
                    SnapshotIssueCode.SYMLINK_PRESENT,
                    "a symlink is present in a sealed snapshot", relative))
                continue
            if not stat.S_ISREG(info.st_mode):
                issues.append(SnapshotIssue(
                    SnapshotIssueCode.SPECIAL_FILE_PRESENT,
                    "a socket, device or FIFO is present in a sealed snapshot",
                    relative))
                continue
            if info.st_nlink > 1:
                issues.append(SnapshotIssue(
                    SnapshotIssueCode.HARD_LINK_PRESENT,
                    "this file has %d hard links; a snapshot's bytes must not "
                    "be reachable through another name, because writing through "
                    "that name would change the snapshot" % info.st_nlink,
                    relative))
            digest, length = _sha256_file(absolute)
            on_disk[relative] = (digest, length)

    for relative in sorted(set(on_disk) - set(expected) - {MANIFEST_FILE,
                                                           CHECKSUMS_FILE}):
        issues.append(SnapshotIssue(
            SnapshotIssueCode.UNEXPECTED_FILE,
            "this file is present but no manifest descriptor names it",
            relative))

    for relative, descriptor in sorted(expected.items()):
        actual = on_disk.get(relative)
        if actual is None:
            code = (SnapshotIssueCode.REQUESTS_LOG_MISSING
                    if relative == REQUESTS_FILE
                    else SnapshotIssueCode.ARTIFACT_MISSING)
            issues.append(SnapshotIssue(
                code, "the manifest names this artifact, but it is not on disk",
                relative))
            continue
        digest, length = actual
        if digest != descriptor.sha256:
            issues.append(SnapshotIssue(
                SnapshotIssueCode.ARTIFACT_HASH_MISMATCH,
                "on disk it hashes to %s; the manifest records %s"
                % (digest, descriptor.sha256), relative))
        if length != descriptor.byte_length:
            issues.append(SnapshotIssue(
                SnapshotIssueCode.ARTIFACT_LENGTH_MISMATCH,
                "on disk it is %d bytes; the manifest records %d"
                % (length, descriptor.byte_length), relative))
        listed = checksums.get(relative)
        if listed is None:
            issues.append(SnapshotIssue(
                SnapshotIssueCode.CHECKSUMS_MALFORMED,
                "checksums.sha256 does not list this artifact", relative))
        elif listed != digest:
            issues.append(SnapshotIssue(
                SnapshotIssueCode.ARTIFACT_HASH_MISMATCH,
                "checksums.sha256 records %s; the file hashes to %s"
                % (listed, digest), relative))

    for relative in sorted(set(checksums) - set(expected)):
        issues.append(SnapshotIssue(
            SnapshotIssueCode.CHECKSUMS_MALFORMED,
            "checksums.sha256 lists a path the manifest does not describe",
            relative))

    return len(expected), issues
