"""The active release, reported as one release.

``GET /system/version`` answers from a single pinned context. The active
pointer is read once, by the release service, before this function is called;
this module receives what that read produced and reports it.

The rule it enforces is that two releases never appear in one answer. A
version endpoint that read the pointer for the release id and then loaded the
ruleset hash separately could, under an activation committing between the two
reads, report release A's identity beside release B's ruleset - and every
field would look individually correct. Taking one provenance object as the
only source makes that impossible rather than unlikely.

``active_pointer_generation`` is reported here and nowhere else. It is pointer
audit metadata, excluded from the assessment output hash on purpose; it
belongs in an answer *about the pointer*, and would be misleading beside an
assessment's pinned provenance, where a reader could take it for part of the
pinned identity.
"""

from __future__ import annotations

from typing import Any, Dict

from apps.api import API_VERSION
from apps.api.contracts.spec import CONTRACT_VERSION

__all__ = ["system_version_document"]

_PROVENANCE_FIELDS = (
    "release_public_id", "release_manifest_hash", "active_pointer_generation",
    "software_version", "software_source_tree_hash", "dataset_public_id",
    "canonical_build_content_hash", "ruleset_public_id",
    "ruleset_content_hash", "evidence_build_key",
    "evidence_build_content_hash", "coverage_manifest_hash",
    "protocol_version", "source_policy_version")


def system_version_document(provenance: Any, *, claim_boundary: Any
                            ) -> Dict[str, Any]:
    """Report the active release and the claim boundary in force.

    Args:
        provenance: the pinned provenance for the active release - the single
            object every version field is read from.
        claim_boundary: the boundary this deployment runs under. Reported
            because a client that can see the versions can also see whether
            the product is permitted to answer at all, and discovering that
            only by receiving a 503 from the assessment endpoint is a worse
            way to learn it.
    """
    document = provenance.to_json() if hasattr(provenance, "to_json") \
        else dict(provenance)
    payload: Dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "api_version": API_VERSION,
    }
    for name in _PROVENANCE_FIELDS:
        payload[name] = document.get(name)
    payload["claim_boundary_phase"] = getattr(
        getattr(claim_boundary, "phase", None), "value", None)
    payload["claim_boundary_approved"] = bool(
        getattr(claim_boundary, "is_approved", False))
    return payload
