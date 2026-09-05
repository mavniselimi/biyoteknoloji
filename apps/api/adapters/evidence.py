"""One evidence record as an immutable provenance projection.

A finding cites evidence by record identity. Years later somebody has to be
able to ask what that identity was, and get an answer about *that* record -
not about whatever record now occupies the same natural key in a newer build.
This module answers by identity, from the evidence build it is given, and it
is the caller's job to give it the pinned one.

What comes back is a chain of identities and hashes: the record's own identity,
the provider and origin the record came from, the source record and version it
was extracted from, the payload and content hashes, the canonical entity links,
the publication identifiers, and the evidence build the projection was read
from. That is what makes a citation auditable.

What deliberately does not come back:

- **raw source payloads and text fragments.** The fragment *count* is
  reported; the fragments are not. Unrestricted third-party source prose in an
  API response is both a licensing question and an unreviewed-claims question,
  and the second is the one that matters here - source text can say things
  about medicines that this product must not say.
- **filesystem paths, artifact URLs and credentials.** A locator is reported
  as snapshot, artifact and digest identity, never as a path into a build
  directory.
- **any newly written clinical advice.** Nothing in this module composes a
  sentence. Every string it emits was already an identifier, a hash or a
  governed status.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from apps.api.contracts.spec import CONTRACT_VERSION, LIMITS

__all__ = [
    "evidence_detail_document",
]

_ENTITY_SECTIONS = (("GENE", "genes"), ("DRUG", "drugs"))


def _entity_links(detail: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Canonical entity links, deduplicated and ordered.

    ``source_label`` is the label the source used for the entity. It is
    reported because an auditor comparing a record against its source needs to
    see what the source called it, and it is bounded and control-character
    checked by the response contract before it leaves - it is the one field
    here that originates outside this system.
    """
    links: List[Dict[str, Any]] = []
    for entity_type, section in _ENTITY_SECTIONS:
        for entry in detail.get(section) or ():
            if isinstance(entry, Mapping):
                canonical_key = entry.get("canonical_key") or entry.get("key")
                source_label = entry.get("source_label") or entry.get("label")
            else:
                canonical_key, source_label = entry, None
            if not canonical_key:
                continue
            links.append({"entity_type": entity_type,
                          "canonical_key": str(canonical_key),
                          "source_label": (None if source_label is None
                                           else str(source_label))})
    links.sort(key=lambda item: (item["entity_type"], item["canonical_key"]))
    return links[:LIMITS["max_collection_items"]]


def _publications(detail: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Publication identifiers, as identifiers only.

    No title, no abstract, no author list: a citation is resolvable from a
    DOI or a PubMed id, and reproducing bibliographic text here would be this
    layer restating a source it has not been licensed or reviewed to restate.
    """
    found: List[Dict[str, Any]] = []
    for entry in detail.get("publications") or ():
        if isinstance(entry, Mapping):
            identifier_type = entry.get("identifier_type") or entry.get("type")
            identifier = entry.get("identifier") or entry.get("value")
        else:
            identifier_type, identifier = "UNKNOWN", entry
        if not identifier:
            continue
        found.append({"identifier_type": str(identifier_type or "UNKNOWN"),
                      "identifier": str(identifier)})
    found.sort(key=lambda item: (item["identifier_type"], item["identifier"]))
    return found[:LIMITS["max_collection_items"]]


def _locators(detail: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Where the record was extracted from, by identity rather than by path.

    A JSON pointer is included because it is a position inside an identified
    artifact, which is meaningless without that artifact and therefore
    discloses nothing on its own. A filesystem path would be the opposite:
    useful to an attacker, useless to an auditor who does not have the host.
    """
    found: List[Dict[str, Any]] = []
    for entry in detail.get("locators") or ():
        if not isinstance(entry, Mapping):
            continue
        # The source keys are WP-08's: a locator names the snapshot by its
        # manifest hash, the artifact by its own hash, and the position by a
        # JSON pointer. ``artifact_path`` is deliberately not read - it is a
        # path inside a build directory, useful to an attacker and useless to
        # an auditor who does not have the host.
        found.append({
            "snapshot_id": entry.get("snapshot_manifest_hash")
            or entry.get("snapshot_id"),
            "artifact_id": entry.get("artifact_id"),
            "artifact_digest": entry.get("artifact_sha256")
            or entry.get("artifact_digest") or entry.get("content_hash"),
            "json_pointer": entry.get("pointer") or entry.get("json_pointer"),
        })
    found.sort(key=lambda item: (str(item["snapshot_id"]),
                                 str(item["artifact_id"]),
                                 str(item["json_pointer"])))
    return found[:LIMITS["max_collection_items"]]


def _record_type_mapping(detail: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """How the source's own record type became a canonical one.

    Four governed fields: the canonical record type, the mapping's status, the
    version of the mapping rules that produced it, and whether it is
    production eligible. That is the raw-to-canonical step of the trace, in
    identifiers.

    ``rationale`` is deliberately absent. It is a paragraph of prose written
    to explain a curation judgement, and prose about a source's records is
    exactly what this endpoint must not emit - a reader would take it for a
    statement about the evidence rather than about the mapping.
    """
    mapping = detail.get("record_type_mapping")
    if not isinstance(mapping, Mapping) or not mapping:
        return None
    return {
        "record_type": mapping.get("record_type"),
        "status": mapping.get("status"),
        "map_version": mapping.get("map_version"),
        "production_eligible": bool(mapping.get("production_eligible")),
    }


def evidence_detail_document(detail: Mapping[str, Any], *,
                             evidence_build_key: str,
                             evidence_build_content_hash: str
                             ) -> Dict[str, Any]:
    """Project one evidence record for the API.

    Args:
        detail: the record as
            :class:`~pgx.evidence.detail.ArtifactEvidenceDetailRepository`
            returns it.
        evidence_build_key: the build this record was read from.
        evidence_build_content_hash: that build's content hash. Reported so a
            reader can tell which build answered, rather than assuming it was
            the one their assessment pinned.
    """
    return {
        "contract_version": CONTRACT_VERSION,
        "record_uuid": str(detail.get("record_uuid")),
        "natural_key": detail.get("natural_key"),
        "record_type": detail.get("record_type"),
        "provider_source_key": detail.get("provider_source_key"),
        "origin_source_key": detail.get("origin_source_key"),
        "origin_status": detail.get("origin_status"),
        "version_status": detail.get("version_status"),
        "version_value": detail.get("version_value"),
        "source_payload_hash": detail.get("source_payload_hash"),
        "content_hash": detail.get("content_hash"),
        "production_eligible": bool(detail.get("production_eligible")),
        "evidence_build_key": evidence_build_key,
        "evidence_build_content_hash": evidence_build_content_hash,
        "genes": [link for link in _entity_links(detail)
                  if link["entity_type"] == "GENE"],
        "drugs": [link for link in _entity_links(detail)
                  if link["entity_type"] == "DRUG"],
        "publications": _publications(detail),
        "locators": _locators(detail),
        "record_type_mapping": _record_type_mapping(detail),
        # The count, not the text. A reader learns that the record has source
        # fragments behind it and can request them through a governed channel;
        # they do not receive unreviewed source prose from an API response.
        "text_fragment_count": len(detail.get("text_fragments") or ()),
    }
