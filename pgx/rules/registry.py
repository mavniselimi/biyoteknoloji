# -*- coding: utf-8 -*-
"""The engine-facing registry (WP-11).

This is the entire surface WP-12's engine will be given. It exposes verified,
frozen, immutable rulesets and nothing else - no draft, no curated-but-unvalidated
rule, no deprecated member, no ``BUILDING`` or merely ``VALIDATED`` ruleset, no
legacy CSV row, no ORM object and no database session.

**Loading fails closed.** Every one of these refuses:

* the directory is not a frozen ruleset artifact;
* the checksum file is missing, malformed, or disagrees with any file;
* a listed file is absent, or an unlisted file is present;
* the manifest hash does not match the manifest's own content;
* the approval list hash does not match the manifest's pin;
* a member in the manifest is absent from ``rules.ndjson``, or vice versa;
* any member's content hashes to something other than what the manifest pins;
* the recomputed ruleset content hash disagrees with the manifest;
* a member has no approval entry;
* the pinned dataset, evidence, protocol or source-policy identity is missing.

A partially verified ruleset is not a ruleset. An engine handed "most of one"
would produce findings that cannot be accounted for, and accounting for
findings is the entire claim of this system.

**The default registry is empty.** :data:`DEFAULT_RULESET_ROOT` points at
``data/rulesets``, which contains no frozen artifact and will not until real
human approvals exist. Synthetic test fixtures live under ``tests/``, which the
default root does not reach - so a test cannot accidentally make the production
registry executable.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.domain.hashing import sha256_digest
from pgx.rules.errors import (ArtifactIntegrityError, RegistryLoadError,
                              RuleValidationError)
from pgx.rules.models import (ComputableRuleDefinition, FrozenRuleset,
                              RulesetApprovalRecord, RulesetManifest,
                              RulesetMember)
from pgx.rules.schema import parse_rule_document
from pgx.rules.serialization import ARTIFACT_FILES, verify_checksums

__all__ = [
    "DEFAULT_RULESET_ROOT",
    "FrozenRulesetRegistry",
    "load_frozen_ruleset",
]

#: Where the production registry looks. It holds no frozen artifact today, and
#: the gate reports in the same directory say why.
DEFAULT_RULESET_ROOT = os.path.join("data", "rulesets")


def _read_json(directory: str, name: str) -> Any:
    with io.open(os.path.join(directory, name), encoding="utf-8") as handle:
        return json.load(handle)


def _parse_manifest(payload: Mapping[str, Any]) -> Tuple[RulesetManifest, str]:
    """Rebuild the manifest object and check its own declared hash."""
    from pgx.domain.identifiers import (DatasetPublicId, RulesetPublicId,
                                        RulesetVersionId, ComputableRuleId)
    from pgx.domain.enums import Phenotype
    from pgx.rules.conditions import CanonicalAxis
    from pgx.rules.identifiers import RuleFamilyId

    try:
        members = tuple(
            RulesetMember(
                rule_id=ComputableRuleId.parse(str(entry["rule_id"])),
                family_id=RuleFamilyId.parse(str(entry["family_id"])),
                rule_version=int(entry["rule_version"]),
                content_hash=str(entry["content_hash"]))
            for entry in payload["members"])
        axes = tuple(
            CanonicalAxis(gene_canonical_key=str(entry["gene_id"]),
                          drug_canonical_key=str(entry["drug_id"]),
                          phenotype=Phenotype(str(entry["phenotype"])))
            for entry in payload.get("structural_axes") or ())
        manifest = RulesetManifest(
            ruleset_schema_version=str(payload["ruleset_schema_version"]),
            rule_schema_version=str(payload["rule_schema_version"]),
            condition_schema_version=str(payload["condition_schema_version"]),
            ruleset_id=RulesetVersionId.parse(str(payload["ruleset_id"])),
            public_id=RulesetPublicId(str(payload["public_id"])),
            ruleset_version=int(payload["ruleset_version"]),
            members=members,
            dataset_public_id=DatasetPublicId(str(payload["dataset_public_id"])),
            canonical_build_key=str(payload["canonical_build_key"]),
            canonical_build_content_hash=str(payload["canonical_build_content_hash"]),
            evidence_build_key=str(payload["evidence_build_key"]),
            evidence_build_content_hash=str(payload["evidence_build_content_hash"]),
            protocol_version=str(payload["protocol_version"]),
            protocol_content_hash=str(payload["protocol_content_hash"]),
            source_policy_version=str(payload["source_policy_version"]),
            source_policy_content_hash=str(payload["source_policy_content_hash"]),
            structural_axes=axes,
            approval_list_hash=str(payload["approval_list_hash"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise ArtifactIntegrityError(
            "manifest.json is not a readable ruleset manifest: %s" % exc,
            code="ARTIFACT_MANIFEST_MALFORMED") from None

    declared = payload.get("manifest_hash")
    if declared is not None and declared != manifest.content_hash():
        raise ArtifactIntegrityError(
            "manifest declares hash %s but its content hashes to %s; the "
            "manifest was altered after it was written"
            % (str(declared)[:23], manifest.content_hash()[:23]),
            code="ARTIFACT_MANIFEST_HASH_MISMATCH",
            detail={"declared": declared, "computed": manifest.content_hash()})
    return manifest, manifest.content_hash()


def load_frozen_ruleset(directory: str) -> FrozenRuleset:
    """Load one frozen ruleset artifact, verifying everything.

    Raises rather than returning a partially verified object.
    """
    if not os.path.isdir(directory):
        raise RegistryLoadError(
            "%s is not a ruleset artifact directory" % directory,
            code="REGISTRY_ARTIFACT_MISSING")

    verify_checksums(directory)

    manifest_payload = _read_json(directory, "manifest.json")
    manifest, manifest_hash = _parse_manifest(manifest_payload)

    approval_payload = _read_json(directory, "approval-list.json")
    approval_hash = sha256_digest(approval_payload)
    if approval_hash != manifest.approval_list_hash:
        raise ArtifactIntegrityError(
            "the approval list hashes to %s but the manifest pins %s; the "
            "governance record was altered after the ruleset was frozen"
            % (approval_hash[:23], manifest.approval_list_hash[:23]),
            code="ARTIFACT_APPROVAL_LIST_MISMATCH")

    definitions: List[ComputableRuleDefinition] = []
    with io.open(os.path.join(directory, "rules.ndjson"), encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                definitions.append(parse_rule_document(json.loads(text)))
            except (ValueError, RuleValidationError) as exc:
                raise ArtifactIntegrityError(
                    "rules.ndjson line %d is not a valid rule: %s" % (number, exc),
                    code="ARTIFACT_MEMBER_MALFORMED",
                    detail={"line": number}) from None

    pinned = {member.rule_id.to_json(): member for member in manifest.members}
    present = {definition.rule_id.to_json(): definition for definition in definitions}

    missing = sorted(set(pinned) - set(present))
    if missing:
        raise ArtifactIntegrityError(
            "the manifest pins %d rule(s) that rules.ndjson does not contain: "
            "%s" % (len(missing), ", ".join(missing[:3])),
            code="ARTIFACT_MEMBER_MISSING", detail={"rule_ids": missing})
    extra = sorted(set(present) - set(pinned))
    if extra:
        raise ArtifactIntegrityError(
            "rules.ndjson contains %d rule(s) the manifest does not pin: %s. An "
            "unpinned rule in a frozen artifact is a rule nobody approved into "
            "it." % (len(extra), ", ".join(extra[:3])),
            code="ARTIFACT_MEMBER_UNPINNED", detail={"rule_ids": extra})

    for rule_id, member in sorted(pinned.items()):
        definition = present[rule_id]
        actual = definition.content_hash()
        if actual != member.content_hash:
            raise ArtifactIntegrityError(
                "rule %s hashes to %s but the manifest pins %s; a member was "
                "altered after the ruleset was frozen"
                % (rule_id, actual[:23], member.content_hash[:23]),
                code="ARTIFACT_MEMBER_HASH_MISMATCH",
                detail={"rule_id": rule_id, "expected": member.content_hash,
                        "actual": actual})
        if definition.rule_version != member.rule_version:
            raise ArtifactIntegrityError(
                "rule %s is version %d but the manifest pins version %d"
                % (rule_id, definition.rule_version, member.rule_version),
                code="ARTIFACT_MEMBER_VERSION_MISMATCH")

    approvals: List[RulesetApprovalRecord] = []
    approved_ids = set()
    for entry in approval_payload.get("entries") or ():
        approved_ids.add(str(entry.get("rule_id")))
    unapproved = sorted(set(pinned) - approved_ids)
    if unapproved:
        raise ArtifactIntegrityError(
            "%d member(s) have no approval entry: %s. A member without a "
            "recorded approval chain is a rule nobody is accountable for."
            % (len(unapproved), ", ".join(unapproved[:3])),
            code="ARTIFACT_APPROVAL_INCOMPLETE", detail={"rule_ids": unapproved})

    from pgx.domain.identifiers import ComputableRuleId
    from pgx.rules.identifiers import RuleFamilyId
    for entry in sorted(approval_payload.get("entries") or (),
                        key=lambda item: str(item.get("rule_id"))):
        try:
            approvals.append(RulesetApprovalRecord(
                rule_id=ComputableRuleId.parse(str(entry["rule_id"])),
                family_id=RuleFamilyId.parse(str(entry["family_id"])),
                rule_version=int(entry["rule_version"]),
                rule_content_hash=str(entry["rule_content_hash"]),
                approval_envelope_hash=str(entry["approval_envelope_hash"]),
                curation_revision_id=str(entry["curation_revision_id"]),
                curation_revision_hash=str(entry["curation_revision_hash"]),
                created_by=str(entry["created_by"]),
                reviewed_by=str(entry["reviewed_by"]),
                approved_by=str(entry["approved_by"]),
                validated_by=str(entry["validated_by"]),
                validated_at=_dt.datetime.fromisoformat(
                    str(entry["validated_at"]).replace("Z", "+00:00"))))
        except (KeyError, ValueError, TypeError) as exc:
            raise ArtifactIntegrityError(
                "approval-list.json entry for %s is malformed: %s"
                % (entry.get("rule_id"), exc),
                code="ARTIFACT_APPROVAL_MALFORMED") from None

    from pgx.rules.builder import ruleset_content_hash
    content_hash = ruleset_content_hash(manifest, definitions)

    build_log = _read_json(directory, "build-log.json")
    declared_content = build_log.get("ruleset_content_hash")
    if declared_content is not None and declared_content != content_hash:
        raise ArtifactIntegrityError(
            "the build log records ruleset content hash %s; the artifact's "
            "content hashes to %s"
            % (str(declared_content)[:23], content_hash[:23]),
            code="ARTIFACT_CONTENT_HASH_MISMATCH")

    for name in ("dataset_public_id", "canonical_build_content_hash",
                 "evidence_build_content_hash", "protocol_content_hash",
                 "source_policy_content_hash"):
        if not manifest_payload.get(name):
            raise ArtifactIntegrityError(
                "the manifest does not pin %s; a ruleset that does not say what "
                "it was built against cannot be bound to a release" % name,
                code="ARTIFACT_PROVENANCE_INCOMPLETE")

    boundaries = {definition.provenance.boundary_key() for definition in definitions}
    if len(boundaries) > 1:
        raise ArtifactIntegrityError(
            "members pin %d different dataset/protocol boundaries; they "
            "disagree about what the world is" % len(boundaries),
            code="ARTIFACT_PROVENANCE_MISMATCH")

    return FrozenRuleset(
        manifest=manifest, definitions=tuple(definitions),
        approvals=tuple(approvals), ruleset_content_hash=content_hash,
        verified_at=_dt.datetime.now(tz=_dt.timezone.utc))


class FrozenRulesetRegistry:
    """A registry over one directory of frozen ruleset artifacts.

    The default root is the production one, which is empty. A caller wanting
    the synthetic fixtures must name their directory explicitly, so making the
    registry non-empty is always a visible decision at the call site.
    """

    def __init__(self, root: str = DEFAULT_RULESET_ROOT) -> None:
        self._root = root
        self._cache: Dict[str, FrozenRuleset] = {}

    @property
    def root(self) -> str:
        return self._root

    def _candidates(self) -> Dict[str, str]:
        """Directories that look like a frozen artifact, by public id.

        A directory is a candidate only if it carries all four artifact files
        and a checksum file. A directory holding some of them is not treated as
        a damaged ruleset to be repaired; it is not a ruleset.
        """
        found: Dict[str, str] = {}
        if not os.path.isdir(self._root):
            return found
        for name in sorted(os.listdir(self._root)):
            directory = os.path.join(self._root, name)
            if not os.path.isdir(directory):
                continue
            if not all(os.path.isfile(os.path.join(directory, member))
                       for member in ARTIFACT_FILES):
                continue
            found[name] = directory
        return found

    def list_executable(self) -> Sequence[str]:
        """Identities this registry can serve, each fully verified.

        Verification happens here rather than at load time only, so listing
        cannot advertise a ruleset that loading would refuse. A corrupt
        artifact is absent from the listing, not present-and-broken.
        """
        executable: List[str] = []
        for name, directory in self._candidates().items():
            try:
                ruleset = load_frozen_ruleset(directory)
            except (ArtifactIntegrityError, RegistryLoadError):
                continue
            self._cache[ruleset.public_id.to_json()] = ruleset
            executable.append(ruleset.public_id.to_json())
        return tuple(sorted(executable))

    def load(self, public_id: str) -> FrozenRuleset:
        """Load and fully verify one frozen ruleset, or raise."""
        if public_id in self._cache:
            return self._cache[public_id]
        for name, directory in self._candidates().items():
            try:
                ruleset = load_frozen_ruleset(directory)
            except (ArtifactIntegrityError, RegistryLoadError):
                continue
            if ruleset.public_id.to_json() == public_id:
                self._cache[public_id] = ruleset
                return ruleset
        raise RegistryLoadError(
            "no verified frozen ruleset %r under %s. A ruleset that is "
            "BUILDING, merely VALIDATED, or whose artifact does not verify is "
            "not executable and is not served here."
            % (public_id, self._root),
            code="REGISTRY_NOT_FROZEN")
