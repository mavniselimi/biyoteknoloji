# -*- coding: utf-8 -*-
"""The stored input snapshot, and what makes it reproducible (WP-15 preflight).

A stored assessment is worth exactly as much as the question it can still be
asked again. WP-14 stored the mode, the input kind, the case id, the requested
medications and the input hash - and not the phenotype profile, which is the
half of the question that decides every finding. Given such a row you can
verify that *some* input hashed to that value; you cannot re-ask the question,
cannot show a reader which phenotypes were observed, and cannot tell an
observation nobody supplied from one that could not be interpreted.

This module stores the whole canonical input document instead, and defines
three things about it.

**It hashes back.** :func:`rebuild_input_semantic_content` reconstructs, from
the snapshot alone, the exact document :meth:`AssessmentInput.semantic_content`
produced, so :func:`verify_input_snapshot` can recompute ``input_hash`` and
compare. A snapshot that does not hash back is refused rather than trusted:
the whole point of persisting it is that it can be checked, and an unchecked
copy of an input is a second version of the truth.

**It carries the verdict, not the keystrokes.** Each observation is recorded
as its canonical gene key, its normalisation status, its phenotype (only where
one was normalised) and its machine-readable reason code. ``raw_value`` is
deliberately absent: it holds whatever the caller typed, and what a caller
typed is exactly where a genotype, a star allele or a fragment of narrative
would arrive. Excluding it is both the privacy decision and the reason the
snapshot hashes back at all, since WP-12 already excludes it from the profile
hash for the same reason.

**It says which contract wrote it.** ``input_snapshot_schema_version`` is
checked on read. A reader that cannot recognise the version refuses instead of
interpreting fields positionally.

Pure functions over plain documents. Nothing here touches a database, a clock
or a network, so a snapshot can be verified anywhere it can be read.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.domain.hashing import sha256_digest
from pgx.engine.risk_errors import AssessmentInputError

__all__ = [
    "ASSESSMENT_INPUT_SNAPSHOT_SCHEMA_VERSION",
    "FORBIDDEN_SNAPSHOT_KEYS",
    "SNAPSHOT_REQUIRED_KEYS",
    "build_input_snapshot",
    "rebuild_input_semantic_content",
    "verify_input_snapshot",
]

ASSESSMENT_INPUT_SNAPSHOT_SCHEMA_VERSION = "pgx-assessment-input-snapshot/1"

#: Every key a complete snapshot carries. Enumerated so an incomplete one is
#: refused by name rather than discovered later as a ``KeyError`` in a report.
SNAPSHOT_REQUIRED_KEYS: Tuple[str, ...] = (
    "input_snapshot_schema_version",
    "input_schema_version",
    "mode",
    "input_kind",
    "case_id",
    "requested_release_public_id",
    "medications",
    "profile",
    "profile_content_hash",
    "input_hash",
)

#: Keys that must never appear anywhere in a snapshot document, at any depth.
#: ``raw_value`` is what the caller typed; the rest name input kinds this
#: product refuses outright. A snapshot holding one of them is refused rather
#: than pruned: something upstream put it there, and quietly deleting it would
#: hide the fact that it was produced at all.
FORBIDDEN_SNAPSHOT_KEYS: Tuple[str, ...] = (
    "raw_value", "genotype", "diplotype", "star_allele", "alleles",
    "activity_score", "vcf", "vcf_path", "ehr", "ehr_id",
    "patient_narrative", "clinical_notes", "narrative", "diagnosis",
    "indication", "dose", "dosage", "patient_name", "date_of_birth", "mrn",
)

#: The four keys one recorded observation carries, and no others. Fixed
#: because this list is what the hash is recomputed over.
_OBSERVATION_KEYS: Tuple[str, ...] = ("gene_id", "status", "phenotype",
                                      "reason_code")

_PROFILE_KEYS: Tuple[str, ...] = ("profile_schema_version",
                                  "input_contract_version", "profile_id",
                                  "observation_count", "observations")

_NOTE = (
    "The complete canonical assessment input. Carries the normalised "
    "phenotype profile and every observation, including the ones that could "
    "not be normalised, so a stored assessment can be re-asked rather than "
    "merely recognised. Carries no raw supplied value, no genotype, no "
    "variant file, no record identifier and no narrative.")


def _refuse(message: str, *, location: str,
            detail: Optional[Mapping[str, Any]] = None) -> None:
    raise AssessmentInputError(message,
                               code="ASSESSMENT_INPUT_SNAPSHOT_INVALID",
                               location=location, detail=detail)


def _forbidden_keys(payload: Any, path: str = "$") -> Tuple[str, ...]:
    """Every forbidden key present anywhere in ``payload``, with its path."""
    found: List[str] = []
    if isinstance(payload, Mapping):
        for key in payload:
            here = "%s.%s" % (path, key)
            if key in FORBIDDEN_SNAPSHOT_KEYS:
                found.append(here)
            found.extend(_forbidden_keys(payload[key], here))
    elif isinstance(payload, (list, tuple)):
        for index, item in enumerate(payload):
            found.extend(_forbidden_keys(item, "%s[%d]" % (path, index)))
    return tuple(sorted(found))


def build_input_snapshot(assessment_input: Any) -> Dict[str, Any]:
    """The complete canonical input document for one assessment.

    Built from the input alone. It deliberately reads nothing from the
    calculation: a snapshot assembled partly from what came *out* would
    describe the answer rather than the question, and could not be used to
    check the answer.
    """
    profile = assessment_input.profile.semantic_content()
    observations = []
    for observation in profile.get("observations", ()):
        observations.append({key: observation.get(key)
                             for key in _OBSERVATION_KEYS})
    profile_document = {
        "profile_schema_version": profile.get("profile_schema_version"),
        "input_contract_version": profile.get("input_contract_version"),
        "profile_id": profile.get("profile_id"),
        "observation_count": profile.get("observation_count"),
        "observations": observations,
    }
    snapshot: Dict[str, Any] = {
        "input_snapshot_schema_version":
            ASSESSMENT_INPUT_SNAPSHOT_SCHEMA_VERSION,
        "input_schema_version": assessment_input.input_schema_version,
        "mode": assessment_input.mode.value,
        "input_kind": assessment_input.input_kind.value,
        "case_id": assessment_input.case_id,
        "requested_release_public_id":
            assessment_input.requested_release_public_id,
        "medications": list(assessment_input.medications),
        "profile": profile_document,
        "profile_content_hash": sha256_digest(profile_document),
        "input_hash": assessment_input.content_hash(),
        "note": _NOTE,
    }
    # Verified here, not only on read. A snapshot that cannot be checked is
    # never written, so a stored one that fails verification means the row
    # changed after it was written rather than that it was built wrong.
    verify_input_snapshot(snapshot, input_hash=snapshot["input_hash"])
    return snapshot


def rebuild_input_semantic_content(snapshot: Mapping[str, Any]
                                   ) -> Dict[str, Any]:
    """Reconstruct exactly what ``AssessmentInput.semantic_content`` produced.

    The reconstruction is mechanical and total: every key comes from the
    snapshot, and the profile hash is recomputed from the stored profile
    rather than copied out of the snapshot's own ``profile_content_hash``. A
    snapshot whose recorded hash disagrees with its recorded profile is
    exactly the corruption this exists to catch, and trusting the recorded
    value would let it through.
    """
    if not isinstance(snapshot, Mapping):
        _refuse("an input snapshot is an object", location="$")
    missing = tuple(name for name in SNAPSHOT_REQUIRED_KEYS
                    if name not in snapshot)
    if missing:
        _refuse("the stored input snapshot is incomplete; it is missing %s"
                % ", ".join(missing), location="$",
                detail={"missing": list(missing)})
    version = snapshot["input_snapshot_schema_version"]
    if version != ASSESSMENT_INPUT_SNAPSHOT_SCHEMA_VERSION:
        _refuse("input snapshot schema version %r is not %r; a reader that "
                "does not know the contract does not guess at the fields"
                % (version, ASSESSMENT_INPUT_SNAPSHOT_SCHEMA_VERSION),
                location="$.input_snapshot_schema_version")
    profile = snapshot["profile"]
    if not isinstance(profile, Mapping):
        _refuse("the snapshot's profile is an object", location="$.profile")
    profile_missing = tuple(name for name in _PROFILE_KEYS
                            if name not in profile)
    if profile_missing:
        _refuse("the stored profile is incomplete; it is missing %s"
                % ", ".join(profile_missing), location="$.profile",
                detail={"missing": list(profile_missing)})
    observations = profile["observations"]
    if not isinstance(observations, (list, tuple)):
        _refuse("the stored profile's observations are a list",
                location="$.profile.observations")
    if len(observations) != profile["observation_count"]:
        _refuse("the stored profile says it holds %r observations and holds "
                "%d. A profile that dropped an observation would look "
                "complete." % (profile["observation_count"],
                               len(observations)),
                location="$.profile.observations")
    for index, observation in enumerate(observations):
        if not isinstance(observation, Mapping):
            _refuse("observation %d is an object" % index,
                    location="$.profile.observations[%d]" % index)
        unexpected = tuple(sorted(set(observation) - set(_OBSERVATION_KEYS)))
        if unexpected:
            _refuse("observation %d carries unknown field(s) %s; a snapshot "
                    "with a field the contract does not name cannot be "
                    "rehashed" % (index, ", ".join(unexpected)),
                    location="$.profile.observations[%d]" % index)
        absent = tuple(name for name in _OBSERVATION_KEYS
                       if name not in observation)
        if absent:
            _refuse("observation %d is missing %s" % (index,
                                                      ", ".join(absent)),
                    location="$.profile.observations[%d]" % index)
    medications = snapshot["medications"]
    if not isinstance(medications, (list, tuple)) or not medications:
        _refuse("the snapshot names at least one medication",
                location="$.medications")
    return {
        "input_schema_version": snapshot["input_schema_version"],
        "mode": snapshot["mode"],
        "input_kind": snapshot["input_kind"],
        "profile_content_hash": sha256_digest(dict(profile)),
        "medications": list(medications),
    }


def verify_input_snapshot(snapshot: Mapping[str, Any], *,
                          input_hash: Optional[str] = None) -> Dict[str, Any]:
    """Check that a stored snapshot is complete, clean and hashes back.

    Args:
        snapshot: the stored document.
        input_hash: the hash the assessment row records. Supplied separately
            on purpose: comparing the snapshot only against the hash it
            carries would prove that it agrees with itself.

    Returns:
        A verification record naming what was recomputed.

    Raises:
        AssessmentInputError: the snapshot is incomplete, is of an unknown
            schema version, carries a value it must not hold, or does not
            hash back to the assessment's input hash.
    """
    forbidden = _forbidden_keys(snapshot)
    if forbidden:
        _refuse("the input snapshot carries value(s) this product does not "
                "store: %s" % ", ".join(forbidden), location="$",
                detail={"forbidden": list(forbidden)})
    semantic = rebuild_input_semantic_content(snapshot)
    recomputed_profile = semantic["profile_content_hash"]
    if recomputed_profile != snapshot["profile_content_hash"]:
        _refuse("the stored profile hashes to %s; the snapshot records %s"
                % (recomputed_profile, snapshot["profile_content_hash"]),
                location="$.profile_content_hash")
    recomputed = sha256_digest(semantic)
    if recomputed != snapshot["input_hash"]:
        _refuse("the stored input snapshot hashes to %s; the snapshot records "
                "%s" % (recomputed, snapshot["input_hash"]),
                location="$.input_hash")
    expected = snapshot["input_hash"] if input_hash is None else input_hash
    if recomputed != expected:
        _refuse("the stored input snapshot hashes to %s; the assessment "
                "records input hash %s. The row and the snapshot describe "
                "different questions." % (recomputed, expected),
                location="$.input_hash")
    return {
        "input_snapshot_schema_version":
            snapshot["input_snapshot_schema_version"],
        "verified": True,
        "recomputed_input_hash": recomputed,
        "recomputed_profile_content_hash": recomputed_profile,
        "observation_count": snapshot["profile"]["observation_count"],
        "medication_count": len(snapshot["medications"]),
    }
