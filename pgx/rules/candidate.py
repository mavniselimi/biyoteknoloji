# -*- coding: utf-8 -*-
"""Executable candidate rules in the core rule package (WP-C08).

Distinct from :class:`pgx.rules.models.ComputableRuleDefinition`, and for one
concrete reason: ``RuleProvenance.approval_envelope_hash`` is a required
``sha256:`` digest naming a WP-10 envelope in which a creator, a reviewer and
an approver are three different people. None exists. Making that field optional
would weaken the governed path for every rule that will ever use it, so instead
the candidate track has its own definition with its own provenance - one that
records what actually backs a candidate rule, which is a capture, an
interpretation and a source citation.

The condition grammar is shared, not reimplemented: a candidate rule carries
either a :class:`~pgx.rules.conditions.RuleCondition` or a
:class:`~pgx.rules.conditions.JointRuleCondition`, both from WP-11, with the
same refusal of wildcards, negation, ranges, implicit expansion and
``INDETERMINATE``.

A candidate ruleset serialises to the same five-file artifact layout a frozen
ruleset uses, into its own directory, so the integrity discipline is the same
one the governed registry already applies.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple, Union

from pgx.domain.authority import CandidateAuthorityState
from pgx.domain.enums import AttentionLevel, Phenotype
from pgx.domain.hashing import sha256_digest
from pgx.rules.conditions import JointRuleCondition, RuleCondition
from pgx.rules.models import RuleOutcome

__all__ = [
    "CANDIDATE_ARTIFACT_FILES",
    "CANDIDATE_RULESET_SCHEMA_VERSION",
    "CANDIDATE_RULE_SCHEMA_VERSION",
    "PERMITTED_CANDIDATE_MODES",
    "CandidateProvenance",
    "CandidateRuleDefinition",
    "CandidateRuleset",
    "load_candidate_ruleset",
    "write_candidate_ruleset",
]

CANDIDATE_RULE_SCHEMA_VERSION = "pgx-candidate-rule/1"
CANDIDATE_RULESET_SCHEMA_VERSION = "pgx-candidate-ruleset/1"

#: The only operation modes a candidate ruleset may execute in. Named here as
#: strings rather than imported from ``pgx.domain.claims`` so the artifact on
#: disk carries the list literally and a reader need not resolve an import to
#: know what it permits.
PERMITTED_CANDIDATE_MODES: Tuple[str, ...] = ("DEMO", "VALIDATION")

CANDIDATE_ARTIFACT_FILES: Tuple[str, ...] = (
    "manifest.json", "rules.ndjson", "provenance.json")
CANDIDATE_CHECKSUM_FILE = "checksums.sha256"

Condition = Union[RuleCondition, JointRuleCondition]


@dataclass(frozen=True, slots=True)
class CandidateProvenance:
    """What a candidate rule descends from, pinned by identity and by hash.

    Every field names something that exists. There is no approval envelope
    field left empty or filled with a placeholder: a record that carried the
    *shape* of an approval with nothing behind it would be read, correctly, as
    an approval by anything that checked for the field rather than its
    contents.
    """

    interpretation_key: str
    interpretation_content_hash: str
    dataset_public_id: str
    canonical_build_key: str
    canonical_build_content_hash: str
    capture_snapshot_manifest_hash: str
    capture_record_ids: Tuple[str, ...]
    source_annotation_ids: Tuple[str, ...]
    citations: Tuple[str, ...]
    source_policy_status: str
    source_policy_content_hash: str
    dq_decision_id: str

    def __post_init__(self) -> None:
        for name in ("interpretation_key", "interpretation_content_hash",
                     "dataset_public_id", "canonical_build_key",
                     "canonical_build_content_hash",
                     "capture_snapshot_manifest_hash", "source_policy_status",
                     "source_policy_content_hash", "dq_decision_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError("%s must be a non-empty string" % name)
        for name in ("capture_record_ids", "source_annotation_ids",
                     "citations"):
            values = tuple(getattr(self, name))
            if not values:
                raise ValueError(
                    "%s must name at least one entry; a candidate rule with "
                    "no traceable source is an assertion" % name)
            object.__setattr__(self, name, tuple(sorted(set(values))))

    def to_json(self) -> Dict[str, Any]:
        return {
            "canonical_build_content_hash": self.canonical_build_content_hash,
            "canonical_build_key": self.canonical_build_key,
            "capture_record_ids": list(self.capture_record_ids),
            "capture_snapshot_manifest_hash":
                self.capture_snapshot_manifest_hash,
            "citations": list(self.citations),
            "dataset_public_id": self.dataset_public_id,
            "dq_decision_id": self.dq_decision_id,
            "interpretation_content_hash": self.interpretation_content_hash,
            "interpretation_key": self.interpretation_key,
            "source_annotation_ids": list(self.source_annotation_ids),
            "source_policy_content_hash": self.source_policy_content_hash,
            "source_policy_status": self.source_policy_status,
        }


@dataclass(frozen=True, slots=True)
class CandidateRuleDefinition:
    """One candidate rule: shared grammar, candidate provenance."""

    rule_key: str
    condition: Condition
    outcome: RuleOutcome
    provenance: CandidateProvenance
    care_setting: Optional[str] = None
    authority_state: CandidateAuthorityState = \
        CandidateAuthorityState.SOURCE_GROUNDED_INTERNAL_DECISION
    review_state: CandidateAuthorityState = \
        CandidateAuthorityState.PENDING_EXTERNAL_EXPERT_REVIEW
    schema_version: str = CANDIDATE_RULE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.rule_key, str) or not self.rule_key.strip():
            raise ValueError("rule_key must be a non-empty string")
        if not isinstance(self.condition, (RuleCondition, JointRuleCondition)):
            raise TypeError(
                "condition must be a RuleCondition or a JointRuleCondition")
        if not isinstance(self.outcome, RuleOutcome):
            raise TypeError("outcome must be a RuleOutcome")
        if not isinstance(self.provenance, CandidateProvenance):
            raise TypeError("provenance must be a CandidateProvenance")
        if self.review_state is not \
                CandidateAuthorityState.PENDING_EXTERNAL_EXPERT_REVIEW:
            raise ValueError(
                "review_state may only be PENDING_EXTERNAL_EXPERT_REVIEW")

    @property
    def is_joint(self) -> bool:
        return isinstance(self.condition, JointRuleCondition)

    @property
    def drug_canonical_key(self) -> str:
        return self.condition.drug_canonical_key

    @property
    def gene_keys(self) -> Tuple[str, ...]:
        if isinstance(self.condition, JointRuleCondition):
            return self.condition.gene_keys
        return (self.condition.gene_canonical_key,)

    @property
    def axis_key(self) -> str:
        if isinstance(self.condition, JointRuleCondition):
            return self.condition.joint_axis_key
        return "%s|%s" % (self.condition.gene_canonical_key,
                          self.condition.drug_canonical_key)

    def matches(self, observed: Mapping[str, Phenotype]) -> bool:
        """Whether this rule applies to an observed phenotype map.

        A simple condition is asked the same way as a joint one, so a caller
        never has to branch on the condition kind to evaluate a rule - which is
        what keeps one evaluation path rather than two.
        """
        if isinstance(self.condition, JointRuleCondition):
            return self.condition.matches(observed)
        value = observed.get(self.condition.gene_canonical_key)
        return value is not None and value in self.condition.phenotype.phenotypes

    def semantic_content(self) -> Dict[str, Any]:
        return {
            "authority_state": self.authority_state.value,
            "care_setting": self.care_setting,
            "condition": self.condition.to_json(),
            "outcome": self.outcome.to_json(),
            "provenance": self.provenance.to_json(),
            "review_state": self.review_state.value,
            "rule_key": self.rule_key,
            "schema_version": self.schema_version,
        }

    def content_hash(self) -> str:
        return sha256_digest(self.semantic_content())

    def to_json(self) -> Dict[str, Any]:
        payload = dict(self.semantic_content())
        payload["axis_key"] = self.axis_key
        payload["content_hash"] = self.content_hash()
        payload["is_joint"] = self.is_joint
        return payload


@dataclass(frozen=True, slots=True)
class CandidateRuleset:
    """A frozen set of candidate rules. Frozen means the bytes."""

    ruleset_key: str
    rules: Tuple[CandidateRuleDefinition, ...]
    refusals: Tuple[Mapping[str, Any], ...]
    expected_gene_scope: Mapping[str, Tuple[str, ...]]
    care_setting_required: Mapping[str, Tuple[str, ...]]
    built_by: str
    permitted_modes: Tuple[str, ...] = PERMITTED_CANDIDATE_MODES
    authority_state: CandidateAuthorityState = \
        CandidateAuthorityState.INTERNAL_VALIDATION
    review_state: CandidateAuthorityState = \
        CandidateAuthorityState.PENDING_EXTERNAL_EXPERT_REVIEW
    schema_version: str = CANDIDATE_RULESET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        keys = [rule.rule_key for rule in self.rules]
        if len(set(keys)) != len(keys):
            raise ValueError("two candidate rules share one rule_key")
        if tuple(self.permitted_modes) != PERMITTED_CANDIDATE_MODES:
            raise ValueError(
                "a candidate ruleset executes in %s and nowhere else"
                % ", ".join(PERMITTED_CANDIDATE_MODES))

    def rules_for(self, drug_canonical_key: str
                  ) -> Tuple[CandidateRuleDefinition, ...]:
        return tuple(rule for rule in self.rules
                     if rule.drug_canonical_key == drug_canonical_key)

    def semantic_content(self) -> Dict[str, Any]:
        return {
            "authority_state": self.authority_state.value,
            "care_setting_required": {
                key: list(value)
                for key, value in sorted(self.care_setting_required.items())},
            "expected_gene_scope": {
                key: list(value)
                for key, value in sorted(self.expected_gene_scope.items())},
            "permitted_modes": list(self.permitted_modes),
            "refusals": [dict(item) for item in self.refusals],
            "review_state": self.review_state.value,
            "rules": [rule.semantic_content() for rule in self.rules],
            "ruleset_key": self.ruleset_key,
            "schema_version": self.schema_version,
        }

    def content_hash(self) -> str:
        return sha256_digest(self.semantic_content())

    def manifest(self) -> Dict[str, Any]:
        return {
            "authority_state": self.authority_state.value,
            "built_by": self.built_by,
            "care_setting_required": {
                key: list(value)
                for key, value in sorted(self.care_setting_required.items())},
            "content_hash": self.content_hash(),
            "expected_gene_scope": {
                key: list(value)
                for key, value in sorted(self.expected_gene_scope.items())},
            "is_governed_ruleset": False,
            "joint_rule_count": sum(1 for r in self.rules if r.is_joint),
            "permitted_modes": list(self.permitted_modes),
            "refusal_count": len(self.refusals),
            "review_state": self.review_state.value,
            "rule_count": len(self.rules),
            "ruleset_key": self.ruleset_key,
            "schema_version": self.schema_version,
            "scope_note": (
                "A candidate ruleset. It is not a governed FROZEN ruleset, is "
                "not registered with WP-11, executes in DEMO and VALIDATION "
                "only, and has been reviewed by nobody outside this project."),
        }


def _canonical(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"


def write_candidate_ruleset(ruleset: CandidateRuleset,
                            destination: str) -> Dict[str, str]:
    """Write the five-file artifact and its checksums. Never overwrites."""
    if os.path.exists(destination):
        raise ValueError(
            "a candidate ruleset already exists at %s; frozen artifacts are "
            "not overwritten" % destination)
    os.makedirs(destination)
    documents = {
        "manifest.json": _canonical(ruleset.manifest()),
        "rules.ndjson": "".join(
            json.dumps(rule.to_json(), sort_keys=True, ensure_ascii=False)
            + "\n" for rule in ruleset.rules),
        "provenance.json": _canonical({
            "note": ("Candidate rules carry no approval envelope, because no "
                     "WP-10 envelope exists. What backs each rule is its "
                     "interpretation, its capture records and its citation, "
                     "all named per rule in rules.ndjson."),
            "refusals": [dict(item) for item in ruleset.refusals],
            "rules": {rule.rule_key: rule.provenance.to_json()
                      for rule in ruleset.rules},
        }),
    }
    import hashlib
    for name, text in sorted(documents.items()):
        with io.open(os.path.join(destination, name), "w", encoding="utf-8",
                     newline="\n") as handle:
            handle.write(text)
    # Digested from the files as written, not from the strings in memory: the
    # checksum has to describe what a later reader will actually open.
    digests: Dict[str, str] = {}
    for name in sorted(documents):
        with io.open(os.path.join(destination, name), "rb") as handle:
            digests[name] = "sha256:" + hashlib.sha256(
                handle.read()).hexdigest()
    with io.open(os.path.join(destination, CANDIDATE_CHECKSUM_FILE), "w",
                 encoding="utf-8", newline="\n") as handle:
        handle.write("".join("%s  %s\n" % (digests[name].split(":", 1)[1],
                                           name)
                             for name in sorted(digests)))
    return digests


def load_candidate_ruleset(directory: str) -> Dict[str, Any]:
    """Read an artifact back and verify every checksum before returning it.

    Fails closed on any mismatch, missing file or extra file, for the same
    reason ``load_frozen_ruleset`` does: an artifact whose bytes are not the
    bytes that were sealed is not the artifact, whatever it contains.
    """
    import hashlib
    if not os.path.isdir(directory):
        raise ValueError("no candidate ruleset at %s" % directory)
    checksum_path = os.path.join(directory, CANDIDATE_CHECKSUM_FILE)
    if not os.path.isfile(checksum_path):
        raise ValueError("no %s in %s" % (CANDIDATE_CHECKSUM_FILE, directory))
    expected: Dict[str, str] = {}
    with io.open(checksum_path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                digest, _, name = line.strip().partition("  ")
                expected[name] = digest
    present = {name for name in os.listdir(directory)
               if name != CANDIDATE_CHECKSUM_FILE}
    if present != set(expected):
        raise ValueError(
            "the artifact directory does not match its checksum file: "
            "unexpected=%s missing=%s"
            % (sorted(present - set(expected)),
               sorted(set(expected) - present)))
    for name, digest in sorted(expected.items()):
        with io.open(os.path.join(directory, name), "rb") as handle:
            actual = hashlib.sha256(handle.read()).hexdigest()
        if actual != digest:
            raise ValueError("%s does not match its recorded digest" % name)
    with io.open(os.path.join(directory, "manifest.json"),
                 encoding="utf-8") as handle:
        manifest = json.load(handle)
    rules = []
    with io.open(os.path.join(directory, "rules.ndjson"),
                 encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rules.append(json.loads(line))
    return {"manifest": manifest, "rules": tuple(rules),
            "directory": directory}
