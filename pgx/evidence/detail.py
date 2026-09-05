# -*- coding: utf-8 -*-
"""An evidence detail repository backed by a sealed build directory (WP-08).

Standard library plus :mod:`pgx.domain` and :mod:`pgx.evidence`.

SQLAlchemy cannot be installed in this environment, so the database adapters
for migration 0006 do not exist yet. This module implements the same ports
against the sealed build's own files, which is enough to make the behaviour
they promise real and testable now: deterministic ordering, duplicate detection
instead of first-row selection, and a trace that can be walked back to the raw
bytes and re-verified.

**The trace is the point.** :meth:`ArtifactEvidenceDetailRepository.verify_trace`
performs the six checks in order, against the raw snapshot on disk:

1. the raw artifact named by the locator exists;
2. its bytes hash to the digest the locator recorded;
3. the locator's JSON pointer addresses a record inside it;
4. that record's payload hashes to the digest the evidence record recorded;
5. the evidence record's own content hash recomputes from its stored fields;
6. every linked canonical entity is in the canonical build the record names.

Each failure is reported separately, because they mean different things: a
changed artifact, a moved record, an edited evidence store, and a canonical
build that has been rebuilt underneath are four different problems.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from dataclasses import dataclass
from typing import (Any, Dict, Iterable, List, Mapping, Optional, Sequence,
                    Tuple)

from pgx.domain.hashing import sha256_digest
from pgx.evidence.errors import EvidenceBuildError, EvidenceError
from pgx.evidence.models import EvidenceRecordType
from pgx.evidence.payloads import is_projection_of

__all__ = [
    "ArtifactEvidenceDetailRepository",
    "DuplicateNaturalKeyError",
    "resolve_json_pointer",
]


class DuplicateNaturalKeyError(EvidenceError):
    """Two records share a natural key the schema declares unique.

    Raised rather than resolved. Returning either row would turn corruption
    into a plausible-looking answer, and the caller would never learn the store
    had two.
    """


def resolve_json_pointer(document: Any, pointer: str) -> Tuple[bool, Any]:
    """Return ``(found, value)`` for an RFC 6901 pointer.

    ``found`` is false rather than raising, because "the locator no longer
    addresses anything" is a verification finding a caller reports, not an
    exceptional condition.
    """
    if pointer in ("", None):
        return True, document
    if not pointer.startswith("/"):
        return False, None
    current = document
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                return False, None
            current = current[token]
        elif isinstance(current, list):
            if not token.lstrip("-").isdigit():
                return False, None
            index = int(token)
            if index < 0 or index >= len(current):
                return False, None
            current = current[index]
        else:
            return False, None
    return True, current


@dataclass(frozen=True)
class _Row:
    """One evidence record as it was written, plus its side tables."""

    payload: Mapping[str, Any]

    @property
    def record_uuid(self) -> str:
        return str(self.payload.get("record_uuid"))

    @property
    def natural_key(self) -> str:
        return str((self.payload.get("natural_key") or {}).get("natural_key"))


class ArtifactEvidenceDetailRepository:
    """Reads a sealed evidence build and answers the evidence-detail ports.

    Loaded once and read many times. The build is immutable, so caching it is
    safe in a way caching a database result would not be.
    """

    def __init__(self, build_path: str) -> None:
        self.build_path = build_path
        manifest_path = os.path.join(build_path, "manifest.json")
        if not os.path.isfile(manifest_path):
            raise EvidenceBuildError(
                "no evidence build manifest at %s" % manifest_path,
                code="MANIFEST_MISSING")
        with io.open(manifest_path, encoding="utf-8") as handle:
            self.manifest = json.load(handle)

        self._records: List[Mapping[str, Any]] = list(
            _read_ndjson(os.path.join(build_path, "evidence-records.ndjson")))

        by_uuid: Dict[str, Mapping[str, Any]] = {}
        by_key: Dict[str, List[Mapping[str, Any]]] = {}
        for payload in self._records:
            row = _Row(payload)
            by_uuid[row.record_uuid] = payload
            by_key.setdefault(row.natural_key, []).append(payload)
        self._by_uuid = by_uuid
        self._by_key = by_key

        self._fragments = _group(
            _read_ndjson(os.path.join(build_path,
                                      "evidence-text-fragments.ndjson")),
            "record_uuid")
        self._links = _group(
            _read_ndjson(os.path.join(build_path,
                                      "evidence-entity-links.ndjson")),
            "record_uuid")
        self._provenance = _group(
            _read_ndjson(os.path.join(build_path,
                                      "evidence-provenance.ndjson")),
            "record_uuid")
        self._publications = _group(
            _read_ndjson(os.path.join(build_path,
                                      "publication-references.ndjson")),
            "record_uuid")
        self._issues = _group(
            _read_ndjson(os.path.join(build_path, "import-issues.ndjson")),
            "natural_key")

        #: (snapshot_root, artifact_path) -> (digest, document, problem).
        #: Populated by verify_trace; see _raw_artifact for why.
        self._artifact_cache: Dict[Tuple[str, str],
                                   Tuple[Optional[str], Any, Optional[str]]] = {}

    # -- lookups ---------------------------------------------------------

    def __len__(self) -> int:
        return len(self._records)

    @property
    def evidence_build_key(self) -> str:
        return str(self.manifest.get("evidence_build_key"))

    def get(self, record_uuid: str) -> Optional[Mapping[str, Any]]:
        payload = self._by_uuid.get(record_uuid)
        return self._detail(payload) if payload is not None else None

    def get_by_natural_key(self, natural_key: str
                           ) -> Optional[Mapping[str, Any]]:
        """Return the record with this key, or raise on finding two.

        No ``LIMIT 1`` equivalent: the schema declares this key unique, so two
        rows under it is corruption. Choosing one would answer the caller's
        question while hiding that the store cannot be trusted.
        """
        rows = self._by_key.get(natural_key) or []
        if len(rows) > 1:
            raise DuplicateNaturalKeyError(
                "%d evidence records share the natural key %r in %s; one key "
                "names one record, so this store is corrupt and no row is "
                "returned" % (len(rows), natural_key, self.build_path))
        return self._detail(rows[0]) if rows else None

    def list_for_build(self, evidence_build_key: Optional[str] = None,
                       record_type: Optional[EvidenceRecordType] = None
                       ) -> Sequence[Mapping[str, Any]]:
        rows = self._records
        if record_type is not None:
            rows = [row for row in rows
                    if (row.get("natural_key") or {}).get("record_type")
                    == record_type.value]
        return [self._detail(row) for row in _ordered(rows)]

    def list_for_gene(self, canonical_key: str) -> Sequence[Mapping[str, Any]]:
        return self._by_entity("GENE", canonical_key)

    def list_for_drug(self, canonical_key: str) -> Sequence[Mapping[str, Any]]:
        return self._by_entity("DRUG", canonical_key)

    def list_for_provider_source(self, provider_source_key: str
                                 ) -> Sequence[Mapping[str, Any]]:
        return [self._detail(row) for row in _ordered(
            row for row in self._records
            if (row.get("attribution") or {}).get("provider_source_key")
            == provider_source_key)]

    def list_for_origin_source(self, origin_source_key: str
                               ) -> Sequence[Mapping[str, Any]]:
        return [self._detail(row) for row in _ordered(
            row for row in self._records
            if (row.get("attribution") or {}).get("origin_source_key")
            == origin_source_key)]

    def list_for_publication(self, identifier: str
                             ) -> Sequence[Mapping[str, Any]]:
        """Records citing one publication, addressed by PMID or DOI only."""
        wanted = identifier.strip()
        if not wanted.startswith(("pmid:", "doi:")):
            raise EvidenceError(
                "a publication is addressed by 'pmid:<digits>' or 'doi:<doi>'; "
                "%r is neither. Titles are not accepted, because two records "
                "printing one title have not been shown to cite one article."
                % identifier)
        matched = []
        for row in self._records:
            for reference in row.get("publications") or ():
                if reference.get("identity") == wanted:
                    matched.append(row)
                    break
        return [self._detail(row) for row in _ordered(matched)]

    def _by_entity(self, entity_type: str,
                   canonical_key: str) -> Sequence[Mapping[str, Any]]:
        matched = []
        for row in self._records:
            for link in row.get("entity_links") or ():
                if link.get("entity_type") == entity_type and \
                        link.get("canonical_key") == canonical_key:
                    matched.append(row)
                    break
        return [self._detail(row) for row in _ordered(matched)]

    # -- trace -----------------------------------------------------------

    def trace(self, record_uuid: str) -> Optional[Mapping[str, Any]]:
        """The whole chain from one evidence record back to the raw bytes."""
        payload = self._by_uuid.get(record_uuid)
        if payload is None:
            return None
        attribution = payload.get("attribution") or {}
        return {
            "record_uuid": record_uuid,
            "natural_key": (payload.get("natural_key") or {}).get("natural_key"),
            "record_type": (payload.get("natural_key") or {}).get("record_type"),
            "record_type_mapping": payload.get("record_type_mapping"),
            "provider_source": {
                "source_key": attribution.get("provider_source_key"),
                "meaning": "where the bytes were retrieved from"},
            "origin_source": {
                "source_key": attribution.get("origin_source_key"),
                "status": attribution.get("origin_status"),
                "raw_value": attribution.get("raw_origin_value"),
                "meaning": "who the record itself says asserted it"},
            "source_record_version": payload.get("version"),
            "publications": list(payload.get("publications") or ()),
            "canonical_entities": list(payload.get("entity_links") or ()),
            "canonical_build": {
                "canonical_build_key": payload.get("canonical_build_key"),
                "content_hash": payload.get("canonical_build_content_hash")},
            "raw_locators": list(payload.get("locators") or ()),
            "hashes": {
                "raw_artifact_sha256": [
                    locator.get("artifact_sha256")
                    for locator in payload.get("locators") or ()],
                "source_payload_hash": payload.get("source_payload_hash"),
                "evidence_content_hash": payload.get("content_hash"),
                "evidence_build_content_hash":
                    self.manifest.get("content_hash"),
                "snapshot_manifest_hash":
                    self.manifest.get("snapshot_manifest_hash"),
                "meaning": ("four different hashes with four different "
                            "meanings: the artifact's bytes, the extracted "
                            "source record, this project's rendering of it, "
                            "and the whole build"),
            },
            "text_fragments": list(payload.get("text_fragments") or ()),
            "production_eligible": payload.get("production_eligible"),
            "lifecycle_labels": list(self.manifest.get("lifecycle_labels")
                                     or ()),
            "issues": [issue for issue in self._issues.get(
                (payload.get("natural_key") or {}).get("natural_key"), ())],
            "note": ("A trace of what a source stated and where it was found. "
                     "It carries no clinical summary and no project risk "
                     "assessment, because the evidence layer holds neither."),
        }

    def _raw_artifact(self, snapshot_root: str, artifact_path: str
                      ) -> Tuple[Optional[str], Any, Optional[str]]:
        """Return ``(digest, document, problem)`` for one raw artifact.

        Hashed and parsed once per snapshot per repository instance. The
        evidence store holds thousands of records reading a handful of large
        artifacts, so re-hashing and re-parsing per record turned a whole-corpus
        verification into minutes of repeating identical work on identical
        bytes. The digest is still computed from the file - what is cached is
        the answer, not a decision to skip the check - and a file that changes
        mid-run is outside what any single verification pass can observe.
        """
        key = (snapshot_root, artifact_path)
        if key in self._artifact_cache:
            return self._artifact_cache[key]

        path = os.path.join(snapshot_root, artifact_path)
        if not os.path.isfile(path):
            entry = (None, None, "raw artifact %s is missing" % artifact_path)
        else:
            digest = _file_digest(path)
            try:
                with io.open(path, encoding="utf-8") as handle:
                    entry = (digest, json.load(handle), None)
            except (OSError, ValueError) as exc:
                entry = (digest, None,
                         "raw artifact %s is unreadable: %s"
                         % (artifact_path, exc))
        self._artifact_cache[key] = entry
        return entry

    def verify_trace(self, record_uuid: str,
                     snapshot_root: str) -> Tuple[str, ...]:
        """Re-check one record's trace against the raw bytes on disk."""
        payload = self._by_uuid.get(record_uuid)
        if payload is None:
            return ("no evidence record %s in %s"
                    % (record_uuid, self.build_path),)

        problems: List[str] = []
        recorded_payload_hash = payload.get("source_payload_hash")
        found_payloads: List[Any] = []

        for locator in payload.get("locators") or ():
            artifact_path = str(locator.get("artifact_path"))
            digest, document, problem = self._raw_artifact(snapshot_root,
                                                           artifact_path)
            if problem is not None:
                problems.append(problem)
                continue
            if digest != locator.get("artifact_sha256"):
                problems.append(
                    "raw artifact %s does not match the digest the locator "
                    "recorded" % artifact_path)
                continue
            found, value = resolve_json_pointer(document,
                                                str(locator.get("pointer")))
            if not found:
                problems.append(
                    "locator %s does not address a record in %s"
                    % (locator.get("pointer"), artifact_path))
                continue
            found_payloads.append(value)

        if found_payloads:
            # The stored payload is the maximal projection over every locator,
            # so each located payload must project into it. A located payload
            # that says something the stored one does not is a real
            # divergence.
            stored = payload.get("raw_source_payload")
            for index, value in enumerate(found_payloads):
                if not is_projection_of(value, stored):
                    problems.append(
                        "the record found at locator %d says something the "
                        "stored payload does not" % index)
            if sha256_digest(stored) != recorded_payload_hash:
                problems.append(
                    "the stored source payload does not hash to the recorded "
                    "source_payload_hash")

        recomputed = sha256_digest({
            key: value for key, value in payload.items()
            if key not in ("record_uuid", "content_hash", "production_eligible",
                           "blocking_issue_count", "raw_source_payload",
                           "payload_namespace_note")})
        if recomputed != payload.get("content_hash"):
            problems.append(
                "the evidence record's content hash does not recompute from "
                "its stored fields")

        recorded_build = payload.get("canonical_build_key")
        for link in payload.get("entity_links") or ():
            if link.get("canonical_build_key") not in (None, recorded_build):
                problems.append(
                    "entity link %s names canonical build %r and the record "
                    "names %r" % (link.get("canonical_key"),
                                  link.get("canonical_build_key"),
                                  recorded_build))
        return tuple(problems)

    # -- assembly --------------------------------------------------------

    def _detail(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        record_uuid = str(payload.get("record_uuid"))
        natural_key = (payload.get("natural_key") or {}).get("natural_key")
        attribution = payload.get("attribution") or {}
        version = payload.get("version") or {}
        return {
            "record_uuid": record_uuid,
            "natural_key": natural_key,
            "record_type": (payload.get("natural_key") or {}).get("record_type"),
            "provider_source_key": attribution.get("provider_source_key"),
            "origin_source_key": attribution.get("origin_source_key"),
            "origin_status": attribution.get("origin_status"),
            "version_status": version.get("status"),
            "version_value": version.get("value"),
            "source_payload_hash": payload.get("source_payload_hash"),
            "content_hash": payload.get("content_hash"),
            "production_eligible": payload.get("production_eligible"),
            "record_type_mapping": payload.get("record_type_mapping"),
            "text_fragments": self._fragments.get(record_uuid, ()),
            "publications": self._publications.get(record_uuid, ()),
            "genes": [link for link in self._links.get(record_uuid, ())
                      if link.get("entity_type") == "GENE"],
            "drugs": [link for link in self._links.get(record_uuid, ())
                      if link.get("entity_type") == "DRUG"],
            "locators": self._provenance.get(record_uuid, ()),
            "issues": self._issues.get(natural_key, ()),
        }


# -- helpers ------------------------------------------------------------


def _read_ndjson(path: str) -> Iterable[Mapping[str, Any]]:
    if not os.path.isfile(path):
        return []
    rows = []
    with io.open(path, encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if text:
                rows.append(json.loads(text))
    return rows


def _group(rows: Iterable[Mapping[str, Any]],
           key: str) -> Dict[str, List[Mapping[str, Any]]]:
    grouped: Dict[str, List[Mapping[str, Any]]] = {}
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        grouped.setdefault(str(value), []).append(row)
    return grouped


def _ordered(rows: Iterable[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    """Sort by natural key.

    Deterministic ordering is not a nicety here: a caller paging through an
    unordered result silently skips rows, and an evidence set with rows missing
    supports conclusions the full set would not.
    """
    return sorted(rows, key=lambda row: str(
        (row.get("natural_key") or {}).get("natural_key")))


def _file_digest(path: str) -> str:
    digest = hashlib.sha256()
    with io.open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()
