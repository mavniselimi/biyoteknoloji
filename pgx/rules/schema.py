# -*- coding: utf-8 -*-
"""The strict external rule representation (WP-11).

:mod:`pgx.rules.models` defines what a rule *is* in memory. This module defines
what one looks like as JSON on disk or across a boundary, and - more
importantly - what a document has to satisfy before it is allowed to become a
rule at all.

Two properties matter.

**Unknown fields are refused, not ignored.** A parser that skipped a field its
author believed in would store a rule that means something other than what was
written, and give it a hash asserting the two agree. There is no
forward-compatibility escape hatch here because the repository has no
established one; adding a field is a schema version bump somebody reviews.

**Every required field is required for a stated reason.** :data:`RULE_FIELDS`
carries the reason beside the name, so the schema, the failure message and the
documentation cite one list and a field cannot be quietly dropped by editing
prose.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.domain.enums import AttentionLevel
from pgx.domain.errors import DomainInvariantError
from pgx.domain.hashing import is_canonical_digest
from pgx.domain.identifiers import (ComputableRuleId, CuratedInterpretationId,
                                    DatasetPublicId)
from pgx.rules.conditions import CONDITION_SCHEMA_VERSION, parse_condition
from pgx.rules.errors import ConditionGrammarError, RuleValidationError
from pgx.rules.identifiers import RuleFamilyId
from pgx.rules.models import (RULE_SCHEMA_VERSION, ComputableRuleDefinition,
                              RuleOutcome, RuleProvenance)

__all__ = [
    "PROVENANCE_FIELDS",
    "RULE_FIELDS",
    "RULE_SCHEMA_VERSION",
    "parse_rule_document",
    "rule_document_issues",
]

#: Every top-level field a rule document must carry, and why.
RULE_FIELDS: Mapping[str, str] = {
    "rule_schema_version":
        "identifies the contract the document was written against; a reader "
        "that guessed would store something other than what was authored",
    "rule_id":
        "names the rule; an approval of an unnamed rule cannot be checked "
        "against the rule that ships",
    "family_id":
        "names the version lineage, so a superseded rule and its replacement "
        "are visibly the same question answered twice",
    "rule_version":
        "an approval is of one version; without it a later edit inherits an "
        "approval it never received",
    "condition":
        "what the rule applies to, in the declarative grammar a reviewer reads",
    "outcome":
        "the single controlled attention level the rule contributes",
    "provenance":
        "everything the rule descends from, pinned by identity and by hash",
    "created_by":
        "who authored this version; an anonymous rule cannot be checked "
        "against the separation of duties its approval claims",
    "created_at":
        "when it was authored, so the rule can be placed against the protocol "
        "and the evidence build that were in force at that moment",
}

#: Every provenance field, and why it is required.
PROVENANCE_FIELDS: Mapping[str, str] = {
    "interpretation_id":
        "the curated interpretation this rule encodes",
    "curation_work_item_id":
        "the workflow record the interpretation came from",
    "curation_revision_id":
        "which revision was approved, not merely which work item",
    "curation_revision_hash":
        "proves the rule descends from the revision that was actually "
        "reviewed rather than from a later edit of it",
    "approval_envelope_hash":
        "binds the rule to the WP-10 approval that named it",
    "protocol_version":
        "the curation protocol the conclusion was reached under",
    "protocol_content_hash":
        "pins the protocol bytes; a protocol amended afterwards did not "
        "govern this conclusion",
    "dataset_public_id":
        "the canonical dataset the entities were resolved in",
    "canonical_build_key": "which canonical build",
    "canonical_build_content_hash": "and its exact content",
    "evidence_build_key": "which evidence build the citations live in",
    "evidence_build_content_hash": "and its exact content",
    "source_policy_version":
        "the source policy that permitted using these sources",
    "source_policy_content_hash": "and its exact content",
    "evidence_record_uuids":
        "the evidence itself, enumerated rather than summarised "
        "(SAFETY-INV-006)",
}

#: Optional top-level fields, with the shape each must take when present.
_OPTIONAL_RULE_FIELDS = frozenset({
    "supersedes_rule_id", "metadata", "content_hash", "condition_schema_version",
})


def _parse_moment(value: Any, field: str, issues: List[Dict[str, Any]]
                  ) -> Optional[_dt.datetime]:
    if isinstance(value, _dt.datetime):
        moment = value
    elif isinstance(value, str) and value.strip():
        try:
            moment = _dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            issues.append({"code": "RULE_DOC_TIMESTAMP_INVALID", "location": "$." + field,
                           "severity": "ERROR",
                           "message": "%s is not an ISO-8601 timestamp" % field})
            return None
    else:
        issues.append({"code": "RULE_DOC_TIMESTAMP_INVALID", "location": "$." + field,
                       "severity": "ERROR",
                       "message": "%s is missing or not a timestamp" % field})
        return None
    if moment.tzinfo is None:
        issues.append({"code": "RULE_DOC_TIMESTAMP_NAIVE", "location": "$." + field,
                       "severity": "ERROR",
                       "message": "%s has no timezone; a naive timestamp is not "
                                  "a point in time" % field})
        return None
    return moment.astimezone(_dt.timezone.utc)


def rule_document_issues(payload: Any) -> Tuple[Dict[str, Any], ...]:
    """Every structural problem with a rule document, not merely the first.

    Returned as data - code, location, severity, message - so a CLI can branch
    and an author can fix everything in one pass rather than one round-trip per
    field.
    """
    issues: List[Dict[str, Any]] = []
    if not isinstance(payload, Mapping):
        return ({"code": "RULE_DOC_NOT_OBJECT", "location": "$", "severity": "ERROR",
                 "message": "a rule document is a JSON object, got %r"
                            % type(payload).__name__},)

    unknown = sorted(set(payload) - set(RULE_FIELDS) - _OPTIONAL_RULE_FIELDS)
    if unknown:
        issues.append({
            "code": "RULE_DOC_UNKNOWN_FIELD", "location": "$", "severity": "ERROR",
            "message": "unknown field(s): %s. A field this reader skipped would "
                       "be a claim nobody checked." % ", ".join(unknown)})

    for name, reason in RULE_FIELDS.items():
        if name not in payload:
            issues.append({
                "code": "RULE_DOC_MISSING_FIELD", "location": "$." + name,
                "severity": "ERROR",
                "message": "%s is required: %s" % (name, reason)})

    version = payload.get("rule_schema_version")
    if version is not None and version != RULE_SCHEMA_VERSION:
        issues.append({
            "code": "RULE_DOC_SCHEMA_VERSION", "location": "$.rule_schema_version",
            "severity": "ERROR",
            "message": "document declares %r; this reader implements %r and will "
                       "not guess at the difference" % (version, RULE_SCHEMA_VERSION)})

    condition = payload.get("condition")
    if condition is not None:
        try:
            parse_condition(condition)
        except ConditionGrammarError as exc:
            issues.append({"code": exc.code, "location": "$.condition" + exc.location[1:],
                           "severity": "ERROR", "message": str(exc)})

    outcome = payload.get("outcome")
    if outcome is not None:
        try:
            RuleOutcome.parse(outcome)
        except DomainInvariantError as exc:
            issues.append({"code": "RULE_DOC_OUTCOME_INVALID", "location": "$.outcome",
                           "severity": "ERROR", "message": str(exc)})

    provenance = payload.get("provenance")
    if provenance is not None:
        if not isinstance(provenance, Mapping):
            issues.append({"code": "RULE_DOC_PROVENANCE_INVALID",
                           "location": "$.provenance", "severity": "ERROR",
                           "message": "provenance must be an object"})
        else:
            extra = sorted(set(provenance) - set(PROVENANCE_FIELDS))
            if extra:
                issues.append({"code": "RULE_DOC_UNKNOWN_FIELD",
                               "location": "$.provenance", "severity": "ERROR",
                               "message": "unknown provenance field(s): %s"
                                          % ", ".join(extra)})
            for name, reason in PROVENANCE_FIELDS.items():
                value = provenance.get(name)
                if value is None or (isinstance(value, str) and not value.strip()) \
                        or (isinstance(value, (list, tuple)) and not value):
                    issues.append({
                        "code": "RULE_DOC_MISSING_FIELD",
                        "location": "$.provenance." + name, "severity": "ERROR",
                        "message": "provenance.%s is required: %s" % (name, reason)})
            for name in ("curation_revision_hash", "approval_envelope_hash",
                         "protocol_content_hash", "canonical_build_content_hash",
                         "evidence_build_content_hash", "source_policy_content_hash"):
                value = provenance.get(name)
                if value is not None and not is_canonical_digest(value):
                    issues.append({
                        "code": "RULE_DOC_DIGEST_INVALID",
                        "location": "$.provenance." + name, "severity": "ERROR",
                        "message": "%s is not a sha256:<hex> digest; an unpinned "
                                   "hash pins nothing" % name})
            records = provenance.get("evidence_record_uuids")
            if isinstance(records, (list, tuple)):
                cleaned = [str(item).strip() for item in records if str(item).strip()]
                if len(set(cleaned)) != len(cleaned):
                    issues.append({
                        "code": "RULE_DOC_EVIDENCE_DUPLICATE",
                        "location": "$.provenance.evidence_record_uuids",
                        "severity": "ERROR",
                        "message": "an evidence record is cited twice; a "
                                   "duplicated citation inflates how much "
                                   "evidence there appears to be"})

    _parse_moment(payload.get("created_at"), "created_at", issues)

    raw_version = payload.get("rule_version")
    if raw_version is not None and (isinstance(raw_version, bool)
                                    or not isinstance(raw_version, int)
                                    or raw_version < 1):
        issues.append({"code": "RULE_DOC_VERSION_INVALID", "location": "$.rule_version",
                       "severity": "ERROR",
                       "message": "rule_version counts from 1"})

    declared = payload.get("content_hash")
    if declared is not None and not is_canonical_digest(declared):
        issues.append({"code": "RULE_DOC_DIGEST_INVALID", "location": "$.content_hash",
                       "severity": "ERROR",
                       "message": "content_hash is not a sha256:<hex> digest"})

    return tuple(sorted(issues, key=lambda item: (item["location"], item["code"])))


def parse_rule_document(payload: Any) -> ComputableRuleDefinition:
    """Parse a rule document, or raise with every issue found.

    When the document declares a ``content_hash``, the parsed rule is required
    to hash to it. A document whose declared hash disagrees with its content is
    refused rather than re-hashed: silently correcting it would erase the
    evidence that something was altered after it was written.
    """
    issues = rule_document_issues(payload)
    if issues:
        raise RuleValidationError(
            "rule document is not valid: %s"
            % "; ".join("%s at %s" % (item["code"], item["location"])
                        for item in issues),
            issues=issues)

    provenance = payload["provenance"]
    definition = ComputableRuleDefinition(
        rule_id=ComputableRuleId.parse(str(payload["rule_id"])),
        family_id=RuleFamilyId.parse(str(payload["family_id"])),
        rule_version=int(payload["rule_version"]),
        condition=parse_condition(payload["condition"]),
        outcome=RuleOutcome.parse(payload["outcome"]),
        provenance=RuleProvenance(
            interpretation_id=CuratedInterpretationId.parse(
                str(provenance["interpretation_id"])),
            curation_work_item_id=str(provenance["curation_work_item_id"]),
            curation_revision_id=str(provenance["curation_revision_id"]),
            curation_revision_hash=str(provenance["curation_revision_hash"]),
            approval_envelope_hash=str(provenance["approval_envelope_hash"]),
            protocol_version=str(provenance["protocol_version"]),
            protocol_content_hash=str(provenance["protocol_content_hash"]),
            dataset_public_id=DatasetPublicId(str(provenance["dataset_public_id"])),
            canonical_build_key=str(provenance["canonical_build_key"]),
            canonical_build_content_hash=str(
                provenance["canonical_build_content_hash"]),
            evidence_build_key=str(provenance["evidence_build_key"]),
            evidence_build_content_hash=str(provenance["evidence_build_content_hash"]),
            source_policy_version=str(provenance["source_policy_version"]),
            source_policy_content_hash=str(provenance["source_policy_content_hash"]),
            evidence_record_uuids=tuple(
                str(item) for item in provenance["evidence_record_uuids"])),
        created_by=str(payload["created_by"]),
        created_at=_dt.datetime.fromisoformat(
            str(payload["created_at"]).replace("Z", "+00:00")),
        supersedes_rule_id=(ComputableRuleId.parse(str(payload["supersedes_rule_id"]))
                            if payload.get("supersedes_rule_id") else None),
        metadata=payload.get("metadata") or {})

    declared = payload.get("content_hash")
    if declared is not None and declared != definition.content_hash():
        raise RuleValidationError(
            "rule document declares content_hash %s but its content hashes to "
            "%s. The document was altered after it was written, or was written "
            "against a different schema; either way it is not re-hashed here."
            % (declared, definition.content_hash()),
            issues=({"code": "RULE_DOC_HASH_MISMATCH", "location": "$.content_hash",
                     "severity": "ERROR",
                     "message": "declared %s, computed %s"
                                % (declared, definition.content_hash())},))
    return definition
