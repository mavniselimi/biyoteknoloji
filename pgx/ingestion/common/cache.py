# -*- coding: utf-8 -*-
"""Content-addressed cache for raw responses (WP-04).

Standard library only.

**Three separate things, deliberately.** A request key, an immutable blob, and
the metadata that connects them:

    <root>/index/<request-key-hex>.json   -> metadata, points at a blob
    <root>/blobs/<aa>/<sha256-hex>        -> the raw bytes, addressed by digest

Keeping them apart is what makes two different requests that return identical
bytes share one blob, and what lets the metadata record *how* a response was
obtained without that ever affecting *what* was obtained.

**Raw bytes, byte for byte.** A blob is written exactly as it arrived - not
decoded, not re-encoded, not pretty-printed, not parsed. Every downstream
digest derives from these bytes, so a well-meaning normalisation would silently
change the identity of the data.

**Corruption is an error, never a miss.** If a blob is missing or its digest no
longer matches, :class:`CacheCorruptionError` is raised. Degrading to a miss
would hide the corruption and re-fetch, which is how a broken cache stays
broken and unnoticed for months.

**Writes are atomic and never overwrite.** Content goes to a temporary file in
the same directory and is renamed into place, so a crash mid-write cannot leave
a half-blob that hashes wrong. If a blob already exists at a digest with
*different* bytes, that is either a SHA-256 collision or a bug in the caller,
and both warrant stopping rather than overwriting.

**No credential is ever stored.** Metadata records only safe headers; the
credential names are filtered on the way in.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import io
import json
import os
import tempfile
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from pgx.ingestion.common.errors import (
    CacheCorruptionError, CacheMissError, CacheWriteConflictError,
    ConfigurationError,
)
from pgx.ingestion.common.http import CREDENTIAL_HEADER_NAMES
from pgx.ingestion.common.models import HttpResponse

__all__ = [
    "CACHE_METADATA_VERSION",
    "CacheEntry",
    "ResponseCache",
    "sha256_bytes",
]

#: Written into every metadata file. A shape change bumps it, so an old entry
#: is refused rather than misread.
CACHE_METADATA_VERSION = "pgx-response-cache/1"

_BLOB_DIR = "blobs"
_INDEX_DIR = "index"


def sha256_bytes(data: bytes) -> str:
    """Return ``sha256:<hex>`` for exactly these bytes."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class CacheEntry:
    """What the cache knows about one stored response."""

    request_key: str
    raw_sha256: str
    byte_length: int
    status_code: int
    content_type: str
    final_url: str
    stored_at: str
    blob_ref: str
    safe_headers: Mapping[str, str]

    def to_json(self) -> Mapping[str, Any]:
        """Machine-readable form, as stored on disk."""
        return {
            "metadata_version": CACHE_METADATA_VERSION,
            "request_key": self.request_key,
            "raw_sha256": self.raw_sha256,
            "byte_length": self.byte_length,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "final_url": self.final_url,
            "stored_at": self.stored_at,
            "blob_ref": self.blob_ref,
            "safe_headers": dict(self.safe_headers),
        }


class ResponseCache:
    """A cache rooted at one explicit directory.

    The root is a constructor argument with no default. The legacy probes wrote
    to a module-level ``OUT_DIR``, so importing them decided where data went and
    two runs in the same process could not use different locations. Here the
    caller decides, every time.
    """

    def __init__(self, root: str) -> None:
        if not root or not str(root).strip():
            raise ConfigurationError(
                "the cache root must be given explicitly; there is no default "
                "output directory")
        self._root = os.path.abspath(os.path.expanduser(str(root)))
        self._real_root: Optional[str] = None

    @property
    def root(self) -> str:
        """The absolute cache root."""
        return self._root

    def __repr__(self) -> str:
        return "ResponseCache(root=%r)" % self._root

    # -- paths -----------------------------------------------------------

    def _ensure_root(self) -> str:
        """Create the root if needed and remember its resolved path.

        The resolved path is what every later containment check compares
        against, so a symlinked root is handled once here rather than being
        mistaken for an escape on every write.
        """
        if self._real_root is None:
            os.makedirs(os.path.join(self._root, _BLOB_DIR), exist_ok=True)
            os.makedirs(os.path.join(self._root, _INDEX_DIR), exist_ok=True)
            self._real_root = os.path.realpath(self._root)
        return self._real_root

    @staticmethod
    def _hex(digest: str) -> str:
        """The hex half of a ``sha256:`` digest, validated."""
        if not isinstance(digest, str) or not digest.startswith("sha256:"):
            raise CacheCorruptionError(
                "expected a sha256: digest, got %r" % (digest,))
        hex_part = digest[len("sha256:"):]
        if len(hex_part) != 64 or any(
                character not in "0123456789abcdef" for character in hex_part):
            raise CacheCorruptionError("malformed digest %r" % (digest,))
        return hex_part

    def _contained(self, path: str) -> str:
        """Return ``path``, or raise if it escapes the cache root.

        Checked on the resolved path, so ``..`` segments and symlinks are both
        caught. A cache key is derived from a hash and should never contain a
        separator, but a path check that only ran when it looked necessary
        would be a check that never ran.
        """
        real_root = self._ensure_root()
        candidate = os.path.realpath(path)
        if candidate != real_root and not candidate.startswith(real_root + os.sep):
            raise CacheCorruptionError(
                "refusing a cache path that escapes the root: %r resolves "
                "outside %r" % (path, real_root))
        return path

    def blob_path(self, raw_sha256: str) -> str:
        """Path of the blob holding these exact bytes.

        Two-level fan-out, so a directory listing stays usable after a few
        hundred thousand responses.
        """
        hex_part = self._hex(raw_sha256)
        return self._contained(os.path.join(
            self._root, _BLOB_DIR, hex_part[:2], hex_part))

    def index_path(self, request_key: str) -> str:
        """Path of the metadata file for this request key."""
        hex_part = self._hex(request_key)
        return self._contained(os.path.join(
            self._root, _INDEX_DIR, hex_part + ".json"))

    # -- reading ---------------------------------------------------------

    def has(self, request_key: str) -> bool:
        """True when this request key has a metadata entry.

        Does not verify the blob: :meth:`load` does that, because a probe that
        verified would make an existence check expensive.
        """
        return os.path.isfile(self.index_path(request_key))

    def load_entry(self, request_key: str) -> CacheEntry:
        """Return the metadata for a request key, or raise."""
        path = self.index_path(request_key)
        if not os.path.isfile(path):
            raise CacheMissError(
                "no cache entry for request key %s" % request_key)
        try:
            with io.open(path, encoding="utf-8") as handle:
                document = json.load(handle)
        except (ValueError, OSError) as exc:
            raise CacheCorruptionError(
                "cache metadata for %s is unreadable: %s" % (request_key, exc)
            ) from exc
        if document.get("metadata_version") != CACHE_METADATA_VERSION:
            raise CacheCorruptionError(
                "cache metadata for %s was written by %r, this build expects %r"
                % (request_key, document.get("metadata_version"),
                   CACHE_METADATA_VERSION))
        return CacheEntry(
            request_key=document["request_key"],
            raw_sha256=document["raw_sha256"],
            byte_length=document["byte_length"],
            status_code=document["status_code"],
            content_type=document.get("content_type", ""),
            final_url=document.get("final_url", ""),
            stored_at=document.get("stored_at", ""),
            blob_ref=document["blob_ref"],
            safe_headers=document.get("safe_headers", {}))

    def load_blob(self, raw_sha256: str) -> bytes:
        """Return the stored bytes, re-verifying their digest.

        The digest is recomputed on every read. Trusting the filename would
        make a corrupted blob indistinguishable from a good one, which defeats
        the point of content addressing.
        """
        path = self.blob_path(raw_sha256)
        if not os.path.isfile(path):
            raise CacheCorruptionError(
                "cache metadata references blob %s, which is missing from disk"
                % raw_sha256)
        try:
            with io.open(path, "rb") as handle:
                data = handle.read()
        except OSError as exc:
            raise CacheCorruptionError(
                "blob %s is unreadable: %s" % (raw_sha256, exc)) from exc
        actual = sha256_bytes(data)
        if actual != raw_sha256:
            raise CacheCorruptionError(
                "blob %s does not match its digest (recomputed %s). The cache "
                "is corrupt; this is reported rather than treated as a miss, "
                "so the corruption cannot pass unnoticed." % (raw_sha256, actual))
        return data

    def load(self, request_key: str) -> HttpResponse:
        """Rebuild the cached response for a request key.

        The returned response carries the original bytes, status and safe
        headers. Timestamps are absent: when the response was first fetched is
        operational metadata belonging to that run, not to this replay.
        """
        entry = self.load_entry(request_key)
        body = self.load_blob(entry.raw_sha256)
        if len(body) != entry.byte_length:
            raise CacheCorruptionError(
                "blob %s is %d bytes but its metadata claims %d"
                % (entry.raw_sha256, len(body), entry.byte_length))
        return HttpResponse(
            status_code=entry.status_code, body=body,
            headers=dict(entry.safe_headers), final_url=entry.final_url)

    # -- writing ---------------------------------------------------------

    def store(self, request_key: str, response: HttpResponse,
              now: Optional[_dt.datetime] = None) -> CacheEntry:
        """Store a response and return its entry.

        Idempotent for identical bytes: a blob that already exists with the
        same digest and the same content is left alone. A blob that exists with
        *different* content raises rather than being overwritten.
        """
        self._ensure_root()
        digest = sha256_bytes(response.body)
        blob_path = self.blob_path(digest)

        if os.path.isfile(blob_path):
            with io.open(blob_path, "rb") as handle:
                existing = handle.read()
            if existing != response.body:
                raise CacheWriteConflictError(
                    "blob %s already exists with different bytes. Under "
                    "SHA-256 that is either a collision or a caller bug; "
                    "neither is a reason to overwrite." % digest)
        else:
            os.makedirs(os.path.dirname(blob_path), exist_ok=True)
            self._atomic_write(blob_path, response.body)

        safe_headers = {
            name: value for name, value in response.headers.items()
            if name.lower() not in CREDENTIAL_HEADER_NAMES
        }
        entry = CacheEntry(
            request_key=request_key,
            raw_sha256=digest,
            byte_length=len(response.body),
            status_code=response.status_code,
            content_type=response.content_type,
            final_url=response.final_url,
            stored_at=(now or _dt.datetime.now(_dt.timezone.utc)).isoformat(),
            blob_ref=os.path.relpath(blob_path, self._root),
            safe_headers=safe_headers)
        self._atomic_write(
            self.index_path(request_key),
            (json.dumps(entry.to_json(), indent=2, sort_keys=True,
                        ensure_ascii=False) + "\n").encode("utf-8"))
        return entry

    def _atomic_write(self, path: str, data: bytes) -> None:
        """Write to a temporary file in the same directory, then rename.

        Same directory so the rename stays on one filesystem and is therefore
        atomic. A crash mid-write leaves a temporary file, never a truncated
        blob that would fail its own digest check on the next read.
        """
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            dir=directory, prefix=".tmp-", suffix=".part", delete=False)
        try:
            with handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(handle.name, path)
        except BaseException:
            try:
                os.unlink(handle.name)
            except OSError:  # pragma: no cover - best effort cleanup
                pass
            raise

    # -- verification ----------------------------------------------------

    def verify(self) -> Mapping[str, Any]:
        """Re-hash every blob and check every entry resolves.

        Returns a report rather than raising, so an operator can see the whole
        picture at once instead of fixing one problem to reveal the next.
        """
        self._ensure_root()
        problems = []
        entries = 0
        blobs = 0
        index_dir = os.path.join(self._root, _INDEX_DIR)
        for name in sorted(os.listdir(index_dir)) if os.path.isdir(index_dir) else []:
            if not name.endswith(".json"):
                continue
            entries += 1
            request_key = "sha256:" + name[: -len(".json")]
            try:
                entry = self.load_entry(request_key)
                self.load_blob(entry.raw_sha256)
                blobs += 1
            except (CacheCorruptionError, CacheMissError) as exc:
                problems.append({"request_key": request_key,
                                 "error": type(exc).__name__,
                                 "detail": str(exc)})
        return {
            "cache_root": self._root,
            "entries": entries,
            "verified_blobs": blobs,
            "problems": problems,
            "healthy": not problems,
        }
