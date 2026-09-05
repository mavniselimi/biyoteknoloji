# -*- coding: utf-8 -*-
"""The release manifest: what a release pins, and its canonical digest (WP-03).

Standard library only.

A release manifest answers one question: *which exact software, dataset and
ruleset does this release bind together?* It is the payload whose SHA-256
digest becomes ``ReleaseBundle.manifest_hash``, and it is what lets a stored
release be re-verified later without trusting the row it was read from.

Three properties make the digest worth having, and each is enforced here rather
than left to convention:

* **No wall-clock time.** Nothing in :func:`build_release_manifest` reads the
  clock. Building the same manifest twice, a week apart, produces the same
  bytes. A timestamp folded into a hashed payload would make every release
  unique for a reason that has nothing to do with what it contains.
* **Key order is irrelevant.** Hashing goes through
  :func:`pgx.domain.hashing.sha256_digest`, which sorts keys. Two manifests
  that differ only in the order their keys were inserted hash identically.
* **The payload is deeply immutable.** :func:`freeze_json` converts it before it
  is returned, so nothing can edit the object after its digest was taken.

Array order, by contrast, *is* significant, and ruleset membership is sorted by
the domain before it reaches this module, so the ordering is a property of the
ruleset rather than of whoever queried it.

``schemas/release-manifest.schema.json`` is the JSON Schema describing this
shape. :func:`validate_release_manifest` checks a manifest against the parts of
that schema that matter, using only the standard library - the project has no
reachable package index, and a manifest check that cannot run offline would
never run at all. Loading that file is *not* done here: the domain layer does
not read the filesystem, so :mod:`pgx.application.release_schema` owns the path
and the loader.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

from pgx.domain.errors import DomainInvariantError
from pgx.domain.hashing import is_canonical_digest, sha256_digest
from pgx.domain.identifiers import (
    DatasetPublicId,
    ReleasePublicId,
    RulesetPublicId,
)
from pgx.domain.immutable import freeze_json, thaw_json
from pgx.domain.models import DatasetVersion, ReleaseBundle, RulesetVersion, SoftwareVersion

__all__ = [
    "RELEASE_MANIFEST_SCHEMA_VERSION",
    "ManifestValidationError",
    "build_release_manifest",
    "manifest_digest",
    "validate_release_manifest",
    "verify_release_manifest",
]

#: Bumped whenever the manifest shape changes. It is part of the hashed
#: payload, so a shape change cannot silently produce a colliding digest.
RELEASE_MANIFEST_SCHEMA_VERSION = "pgx-release-manifest/1"

_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class ManifestValidationError(DomainInvariantError):
    """A release manifest does not satisfy the manifest contract."""


def build_release_manifest(
    *,
    release_public_id: ReleasePublicId,
    software: SoftwareVersion,
    dataset: DatasetVersion,
    ruleset: RulesetVersion,
) -> Mapping[str, Any]:
    """Return the deeply immutable manifest payload for a release.

    Deterministic by construction: every value comes from the four arguments,
    and the clock is never read. The same four records always produce the same
    payload and therefore the same digest.

    Ruleset membership is included as rule identity strings. It is what makes
    the manifest a real pin rather than a label: two rulesets with the same
    public ID and different members produce different digests.
    """
    if not isinstance(release_public_id, ReleasePublicId):
        raise ManifestValidationError(
            "release_public_id must be a ReleasePublicId, got %r"
            % type(release_public_id).__name__)
    for value, expected, name in ((software, SoftwareVersion, "software"),
                                  (dataset, DatasetVersion, "dataset"),
                                  (ruleset, RulesetVersion, "ruleset")):
        if not isinstance(value, expected):
            raise ManifestValidationError(
                "%s must be a %s, got %r" % (name, expected.__name__,
                                             type(value).__name__))

    payload: Dict[str, Any] = {
        "schema_version": RELEASE_MANIFEST_SCHEMA_VERSION,
        "release": {
            "public_id": release_public_id.to_json(),
        },
        "software": {
            "id": software.id.to_json(),
            "version": software.version,
            "source_commit": software.source_commit,
            "source_tree_hash": software.source_tree_hash,
            "manifest_hash": software.manifest_hash,
        },
        "dataset": {
            "id": dataset.id.to_json(),
            "public_id": dataset.public_id.to_json(),
            "status": dataset.status.value,
            "manifest_hash": dataset.manifest_hash,
        },
        "ruleset": {
            "id": ruleset.id.to_json(),
            "public_id": ruleset.public_id.to_json(),
            "status": ruleset.status.value,
            "manifest_hash": ruleset.manifest_hash,
            "member_count": ruleset.member_count,
            "rule_ids": [rule_id.to_json() for rule_id in ruleset.rule_ids],
        },
    }
    return freeze_json(payload, "$")


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    """Return the canonical ``sha256:`` digest of a manifest payload.

    Thin on purpose: the canonical encoding lives in one place
    (:mod:`pgx.domain.hashing`) and this module does not invent a second one.
    """
    if not isinstance(manifest, Mapping):
        raise ManifestValidationError(
            "manifest must be a mapping, got %r" % type(manifest).__name__)
    return sha256_digest(manifest)


def _require(condition: bool, message: str, problems: List[str]) -> bool:
    if not condition:
        problems.append(message)
    return condition


def _check_object(manifest: Mapping[str, Any], key: str,
                  problems: List[str]) -> Optional[Mapping[str, Any]]:
    value = manifest.get(key)
    if not isinstance(value, Mapping):
        problems.append("%r is missing or is not an object" % key)
        return None
    return value


def _check_digest(container: Mapping[str, Any], key: str, path: str,
                  problems: List[str]) -> None:
    value = container.get(key)
    if not isinstance(value, str) or not _DIGEST_PATTERN.match(value):
        problems.append(
            "%s.%s must be a canonical sha256:<64 hex> digest, got %r"
            % (path, key, value))


def _check_text(container: Mapping[str, Any], key: str, path: str,
                problems: List[str]) -> None:
    value = container.get(key)
    if not isinstance(value, str) or not value.strip():
        problems.append("%s.%s must be a non-empty string, got %r" % (path, key, value))


def _check_public_id(container: Mapping[str, Any], key: str, path: str,
                     kind: type, problems: List[str]) -> None:
    value = container.get(key)
    if not isinstance(value, str):
        problems.append("%s.%s must be a string, got %r" % (path, key, value))
        return
    try:
        kind(value)
    except Exception as exc:  # noqa: BLE001 - reported as a validation problem
        problems.append("%s.%s is not a valid %s: %s" % (path, key, kind.__name__, exc))


def validate_release_manifest(manifest: Any) -> Tuple[str, ...]:
    """Return every problem found in ``manifest``; empty means valid.

    A tuple of problems rather than a boolean, and rather than raising on the
    first one: an operator fixing a manifest wants the whole list, not a
    guessing game. :func:`verify_release_manifest` is the raising wrapper.

    This is a structural check written against
    ``schemas/release-manifest.schema.json`` using only the standard library.
    It deliberately does not pull in a JSON Schema implementation: there is no
    reachable package index in this environment, and a validator that cannot
    run offline would simply never run.
    """
    problems: List[str] = []
    if not isinstance(manifest, Mapping):
        return ("manifest must be an object, got %r" % type(manifest).__name__,)

    if manifest.get("schema_version") != RELEASE_MANIFEST_SCHEMA_VERSION:
        problems.append(
            "schema_version must be %r, got %r"
            % (RELEASE_MANIFEST_SCHEMA_VERSION, manifest.get("schema_version")))

    known = {"schema_version", "release", "software", "dataset", "ruleset"}
    unknown = sorted(set(manifest) - known)
    if unknown:
        problems.append(
            "unknown top-level key(s) %s; a manifest with fields nothing reads "
            "cannot be verified, so they are refused rather than ignored"
            % ", ".join(repr(key) for key in unknown))

    release = _check_object(manifest, "release", problems)
    if release is not None:
        _check_public_id(release, "public_id", "release", ReleasePublicId, problems)

    software = _check_object(manifest, "software", problems)
    if software is not None:
        _check_text(software, "id", "software", problems)
        _check_text(software, "version", "software", problems)
        _check_text(software, "source_commit", "software", problems)
        _check_digest(software, "source_tree_hash", "software", problems)
        _check_digest(software, "manifest_hash", "software", problems)

    dataset = _check_object(manifest, "dataset", problems)
    if dataset is not None:
        _check_text(dataset, "id", "dataset", problems)
        _check_public_id(dataset, "public_id", "dataset", DatasetPublicId, problems)
        _check_text(dataset, "status", "dataset", problems)
        _check_digest(dataset, "manifest_hash", "dataset", problems)

    ruleset = _check_object(manifest, "ruleset", problems)
    if ruleset is not None:
        _check_text(ruleset, "id", "ruleset", problems)
        _check_public_id(ruleset, "public_id", "ruleset", RulesetPublicId, problems)
        _check_text(ruleset, "status", "ruleset", problems)
        _check_digest(ruleset, "manifest_hash", "ruleset", problems)
        rule_ids = ruleset.get("rule_ids")
        if not isinstance(rule_ids, (list, tuple)):
            problems.append("ruleset.rule_ids must be an array, got %r" % (rule_ids,))
        else:
            if not all(isinstance(item, str) for item in rule_ids):
                problems.append("ruleset.rule_ids must contain only strings")
            if len(set(rule_ids)) != len(rule_ids):
                problems.append("ruleset.rule_ids contains a duplicate")
            member_count = ruleset.get("member_count")
            if member_count != len(rule_ids):
                problems.append(
                    "ruleset.member_count is %r but rule_ids has %d entries; a "
                    "count that disagrees with the list it counts makes the "
                    "manifest self-contradictory"
                    % (member_count, len(rule_ids)))
    return tuple(problems)


def verify_release_manifest(
    manifest: Mapping[str, Any],
    expected_hash: Optional[str] = None,
) -> None:
    """Raise unless ``manifest`` is structurally valid and matches its digest.

    Args:
        manifest: The payload to check.
        expected_hash: When given, the stored digest to compare against. The
            digest is recomputed from the payload rather than trusted, so a row
            whose hash was edited out of band is caught.

    Raises:
        ManifestValidationError: on any structural problem or digest mismatch.
    """
    problems = validate_release_manifest(manifest)
    if problems:
        raise ManifestValidationError(
            "release manifest is invalid: %s" % "; ".join(problems))
    if expected_hash is not None:
        if not is_canonical_digest(expected_hash):
            raise ManifestValidationError(
                "expected_hash is not a canonical digest: %r" % (expected_hash,))
        actual = manifest_digest(manifest)
        if actual != expected_hash:
            raise ManifestValidationError(
                "release manifest hash mismatch: stored %s, recomputed %s. The "
                "payload does not match the digest recorded with it."
                % (expected_hash, actual))


def manifest_matches_release(bundle: ReleaseBundle) -> None:
    """Raise unless a stored bundle's manifest still hashes to its recorded digest."""
    if not isinstance(bundle, ReleaseBundle):
        raise ManifestValidationError(
            "expected a ReleaseBundle, got %r" % type(bundle).__name__)
    verify_release_manifest(bundle.manifest, bundle.manifest_hash)


def as_plain_json(manifest: Mapping[str, Any]) -> Any:
    """Return a plain ``dict``/``list`` copy, for JSON output and JSONB storage."""
    return thaw_json(manifest)
