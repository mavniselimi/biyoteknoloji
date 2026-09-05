# -*- coding: utf-8 -*-
"""Public manifests: what may be said about a case set in the open (WP-18).

A manifest is the thing that gets committed, diffed and read by people who may
not read the cases it describes. So it holds identities, roles, counts,
fingerprints and provenance summaries, and it structurally cannot hold a
payload or an answer: it is built from
:class:`~pgx.validation.cases.ValidationCaseMetadata`, which has no field for
either.

That is checked twice, not once. Building from the public half is the
structural guarantee; :func:`assert_public_manifest_is_safe` re-checks the
rendered document against the prohibited-field list before it is written,
because the failure being guarded against is somebody adding a field in six
months' time and everybody agreeing it looks harmless.

**Counts are counts, not targets.** ``target_case_count`` and
``case_count`` are separate fields and the manifest reports the gap between
them as a number. The P0 Definition of Done asks for at least 50 serious
cases; this repository has none, and a manifest that rendered the target where
the count belongs would be the single most misleading thing in it.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.domain.hashing import sha256_digest
from pgx.validation.cases import (PROHIBITED_CASE_FIELDS,
                                  ValidationCaseMetadata,
                                  assert_no_prohibited_fields)
from pgx.validation.errors import RestrictedContentError
from pgx.validation.vocabulary import (HOLDOUT_ROLES, PayloadAvailability,
                                       ValidationCaseRole)

__all__ = [
    "CASE_MANIFEST_VERSION",
    "P0_TARGET_CASE_COUNT",
    "assert_public_manifest_is_safe",
    "build_case_manifest",
    "build_holdout_manifest",
    "manifest_digest",
]

CASE_MANIFEST_VERSION = "pgx-wp18-validation-case-manifest/1"

#: From the P0 Definition of Done in architecture.md: "At least 50 serious
#: validation cases exist, with a preference for 100+." A target, carried in
#: the manifest as a target and never as an achievement.
P0_TARGET_CASE_COUNT = 50

#: Fields that would make a public manifest a leak. Checked over the rendered
#: document, so a nested one is caught too.
_MANIFEST_PROHIBITED: Tuple[str, ...] = PROHIBITED_CASE_FIELDS + (
    "payload", "payload_content", "content", "observations", "medications",
    "restricted_payload", "answers",
)


def assert_public_manifest_is_safe(document: Mapping[str, Any]) -> None:
    """Refuse a manifest carrying anything reserved for restricted storage.

    Raises :class:`~pgx.validation.errors.RestrictedContentError` naming the
    field and never the value: an error message explaining that it refused to
    publish an expected answer, by quoting it, would publish it.
    """
    try:
        assert_no_prohibited_fields(document, _MANIFEST_PROHIBITED)
    except Exception as error:  # noqa: BLE001 - re-typed, message reused
        raise RestrictedContentError(
            "a public manifest may not carry restricted content: %s"
            % str(error).split(";")[0]) from None


def _case_entry(case: ValidationCaseMetadata) -> Dict[str, Any]:
    """One case, as a manifest publishes it.

    A deliberate subset of the metadata. ``payload_reference`` is included
    because a reference is a location and not a content, and a validation run
    needs it; ``payload_hash`` is included because it is what makes a later
    import checkable.
    """
    entry: Dict[str, Any] = {
        "case_id": case.case_id.value,
        "role": case.role.value,
        "classification": case.classification.value,
        "visibility": case.visibility.value,
        "is_holdout": case.is_holdout,
        "is_validation_evidence": case.is_validation_evidence,
        "content_fingerprint": case.content_fingerprint,
        "derivation_family_fingerprint":
            case.provenance.family_fingerprint,
        "source_identity": case.provenance.source_identity,
        "derivation_method": case.provenance.derivation_method,
        "derived_from_development": case.provenance.derived_from_development,
        "no_pii_assertion": case.no_pii_assertion,
        "created_at": case.created_at.isoformat().replace("+00:00", "Z"),
        "compatibility": case.compatibility.to_json(),
        "metadata_hash": case.metadata_hash(),
    }
    for name in ("payload_hash", "payload_reference", "title"):
        value = getattr(case, name)
        if value is not None:
            entry[name] = value
    if case.provenance.source_digest is not None:
        entry["source_digest"] = case.provenance.source_digest
    if case.provenance.citation is not None:
        entry["citation"] = case.provenance.citation
    return entry


def build_case_manifest(cases: Sequence[ValidationCaseMetadata], *,
                        partition: str, note: str,
                        payload_availability: PayloadAvailability =
                        PayloadAvailability.NOT_CONFIGURED
                        ) -> Dict[str, Any]:
    """The public manifest for one partition.

    One partition per manifest, on purpose. A single document listing
    development and holdout side by side is one copy-paste away from a
    denominator that includes both, and the separation this work package
    exists for should be visible in the file layout as well as in the code.
    """
    entries = [_case_entry(case) for case in
               sorted(cases, key=lambda item: item.case_id.value)]
    roles = {case.role for case in cases}
    if partition == "DEVELOPMENT" and roles - {ValidationCaseRole.DEVELOPMENT}:
        raise RestrictedContentError(
            "a development manifest may list development cases only")
    if partition == "HOLDOUT" and roles - set(HOLDOUT_ROLES):
        raise RestrictedContentError(
            "a holdout manifest may list holdout cases only")

    document: Dict[str, Any] = {
        "schema_version": CASE_MANIFEST_VERSION,
        "partition": partition,
        "case_count": len(entries),
        "development_count": sum(
            1 for case in cases
            if case.role is ValidationCaseRole.DEVELOPMENT),
        "internal_holdout_count": sum(
            1 for case in cases
            if case.role is ValidationCaseRole.INTERNAL_HOLDOUT),
        "expert_holdout_count": sum(
            1 for case in cases
            if case.role is ValidationCaseRole.EXPERT_HOLDOUT),
        "is_validation_evidence": partition != "DEVELOPMENT",
        "payload_availability": payload_availability.value,
        "target_case_count": P0_TARGET_CASE_COUNT,
        "cases": entries,
        "note": note,
    }
    if partition != "DEVELOPMENT":
        shortfall = max(0, P0_TARGET_CASE_COUNT - len(entries))
        document["target_shortfall"] = shortfall
        document["meets_p0_target"] = shortfall == 0
    assert_public_manifest_is_safe(document)
    return document


def build_holdout_manifest(cases: Sequence[ValidationCaseMetadata] = (), *,
                           payload_availability: PayloadAvailability =
                           PayloadAvailability.NOT_CONFIGURED,
                           note: str = "") -> Dict[str, Any]:
    """The holdout manifest, which in this repository lists nothing.

    An empty holdout manifest is a real document with a real meaning, and it
    is not the same document as a missing one: it says the structure exists,
    the storage is not configured, and the count is zero *because no case has
    been authored*, not because a query failed.
    """
    return build_case_manifest(
        cases, partition="HOLDOUT",
        payload_availability=payload_availability,
        note=note or (
            "No holdout case exists in this repository. Authoring one is "
            "scientific work: it needs a source, a derivation a reviewer can "
            "follow, and - for an expert holdout - a named expert working it "
            "under the WP-22 protocol. None of that can be generated, and "
            "generating it would produce exactly the fabricated evidence this "
            "architecture exists to make impossible. The count below is zero "
            "and the P0 target is 50; the gap is reported, not closed."))


def manifest_digest(document: Mapping[str, Any]) -> str:
    return sha256_digest(document)
