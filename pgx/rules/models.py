# -*- coding: utf-8 -*-
"""Immutable rule and ruleset domain objects (WP-11).

Scientific content and lifecycle state are separate types on purpose.

:class:`ComputableRuleDefinition` is what was claimed and what it rests on -
the condition, the outcome, and the provenance pinning the interpretation,
revision, protocol, dataset, evidence build and approval envelope it descends
from. It is hashed, and that hash is the rule's identity as a *claim*.

:class:`RuleLifecycleRecord` is where that claim has got to. It changes; the
definition does not. Keeping them apart is what makes "the content a reviewer
approved" answerable after the rule has been validated, superseded, and
deprecated: the definition still hashes to what the approval named.

Every mapping and sequence exposed here is deeply immutable, through the WP-02
:func:`~pgx.domain.immutable.freeze_json` conventions. A frozen dataclass alone
would only stop rebinding an attribute, and a rule whose condition dictionary
could be mutated after approval is a rule whose approval means nothing.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from pgx.domain.enums import AttentionLevel, RuleStatus, RulesetStatus
from pgx.domain.errors import DomainInvariantError, LifecycleError
from pgx.domain.hashing import ensure_utc, is_canonical_digest, sha256_digest
from pgx.domain.identifiers import (ComputableRuleId, CuratedInterpretationId,
                                    DatasetPublicId, RulesetPublicId,
                                    RulesetVersionId, require_id)
from pgx.domain.immutable import EMPTY_MAPPING, FrozenMapping, freeze_json
from pgx.rules.conditions import (CONDITION_SCHEMA_VERSION, CanonicalAxis,
                                  RuleCondition)
from pgx.rules.errors import (RuleImmutabilityError, RuleLifecycleError,
                              RulesetLifecycleError)
from pgx.rules.identifiers import RuleFamilyId, RulesetBuildId

__all__ = [
    "RULESET_SCHEMA_VERSION",
    "RULE_OUTCOME_LEVELS",
    "RULE_SCHEMA_VERSION",
    "ComputableRuleDefinition",
    "FrozenRuleset",
    "RuleLifecycleRecord",
    "RuleOutcome",
    "RuleProvenance",
    "RulesetApprovalRecord",
    "RulesetBuildRecord",
    "RulesetDefinition",
    "RulesetManifest",
    "RulesetMember",
    "allowed_rule_transitions",
    "allowed_ruleset_transitions",
]

#: Bumped when the persisted or published shape of a rule changes.
RULE_SCHEMA_VERSION = "pgx-computable-rule/1"

#: Bumped when the manifest shape changes.
RULESET_SCHEMA_VERSION = "pgx-ruleset-manifest/1"

#: Levels a rule may author. ``NOT_ASSESSED`` is absent: it means "we did not
#: look", which is a downstream coverage result about a particular case, not
#: something a rule can assert in advance. A rule that could author it would be
#: claiming, at authoring time, that a case it has never seen is unassessable.
RULE_OUTCOME_LEVELS: Tuple[AttentionLevel, ...] = (
    AttentionLevel.NO_ACTIVE_ATTENTION,
    AttentionLevel.LOW,
    AttentionLevel.MEDIUM,
    AttentionLevel.HIGH,
)

#: Fields a rule outcome may never carry. Refused by name so the refusal is
#: legible: each of these would turn an attention finding into a clinical
#: instruction, which is the boundary the whole project is built around.
_PROHIBITED_OUTCOME_FIELDS: Mapping[str, str] = {
    "dose": "the system does not calculate, recommend or adjust a dose",
    "dosage": "the system does not calculate, recommend or adjust a dose",
    "dose_adjustment": "the system does not calculate, recommend or adjust a dose",
    "recommendation": "the system does not recommend an action",
    "recommended_action": "the system does not recommend an action",
    "alternative": "the system does not select or suggest a medication",
    "alternative_drug": "the system does not select or suggest a medication",
    "replacement": "the system does not select or suggest a medication",
    "treatment": "the system does not select a treatment",
    "safe": "the system never declares a drug or combination safe",
    "is_safe": "the system never declares a drug or combination safe",
    "safety": "the system never declares a drug or combination safe",
    "risk_score": "attention is not a score and is not ordered numerically",
    "score": "attention is not a score and is not ordered numerically",
    "rank": "the system does not rank medications",
    "priority": "the system does not rank medications",
    "instruction": "the system does not issue clinician instructions",
    "diagnosis": "the system does not diagnose",
}


def _require_text(value: Any, field_name: str, minimum: int = 1) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise DomainInvariantError(
            "%s must be text of at least %d characters" % (field_name, minimum))
    return value.strip()


def _require_digest(value: Any, field_name: str) -> str:
    if not is_canonical_digest(value):
        raise DomainInvariantError(
            "%s must be a canonical sha256:<hex> digest, got %r"
            % (field_name, value))
    return value


def allowed_rule_transitions() -> Mapping[RuleStatus, Tuple[RuleStatus, ...]]:
    """The rule lifecycle, as data.

    Forward only. Written once here so the service, the database trigger and
    the documentation describe the same machine and a test can compare them.
    """
    return {
        RuleStatus.DRAFT: (RuleStatus.CURATED,),
        RuleStatus.CURATED: (RuleStatus.VALIDATED,),
        RuleStatus.VALIDATED: (RuleStatus.DEPRECATED,),
        RuleStatus.DEPRECATED: (),
    }


def allowed_ruleset_transitions() -> Mapping[RulesetStatus, Tuple[RulesetStatus, ...]]:
    """The ruleset lifecycle, as data.

    Note the absence of ``BUILDING -> FROZEN``. Validating and freezing are two
    audited acts by design: validation decides the set is coherent, freezing
    publishes an artifact nobody may edit, and collapsing them would let a set
    become permanent without anybody deciding it should.
    """
    return {
        RulesetStatus.BUILDING: (RulesetStatus.VALIDATED,),
        RulesetStatus.VALIDATED: (RulesetStatus.FROZEN, RulesetStatus.BUILDING),
        RulesetStatus.FROZEN: (RulesetStatus.RETIRED,),
        RulesetStatus.RETIRED: (),
    }


@dataclass(frozen=True, slots=True)
class RuleOutcome:
    """What a matching rule contributes: one attention level, and nothing else.

    ``rationale_reference`` points at the approved curated interpretation whose
    reasoning justifies the level. It is a reference, never prose the engine
    could render as an instruction: the explanation belongs to the curation
    record, where it was reviewed, and stays there.
    """

    attention_level: AttentionLevel
    rationale_reference: str

    def __post_init__(self) -> None:
        if not isinstance(self.attention_level, AttentionLevel):
            raise DomainInvariantError("attention_level must be an AttentionLevel")
        if self.attention_level not in RULE_OUTCOME_LEVELS:
            raise DomainInvariantError(
                "%s may not be authored by a rule. It is a downstream coverage "
                "result meaning 'we did not look', and a rule asserting it in "
                "advance would be making a claim about a case it has not seen."
                % self.attention_level.value)
        _require_text(self.rationale_reference, "rationale_reference")

    def to_json(self) -> Dict[str, Any]:
        return {
            "attention_level": self.attention_level.value,
            "rationale_reference": self.rationale_reference,
        }

    @classmethod
    def parse(cls, payload: Any) -> "RuleOutcome":
        if not isinstance(payload, Mapping):
            raise DomainInvariantError("outcome must be an object")
        prohibited = sorted(set(payload) & set(_PROHIBITED_OUTCOME_FIELDS))
        if prohibited:
            raise DomainInvariantError(
                "outcome carries prohibited field(s): %s"
                % "; ".join("%s (%s)" % (name, _PROHIBITED_OUTCOME_FIELDS[name])
                            for name in prohibited))
        unknown = sorted(set(payload) - {"attention_level", "rationale_reference"})
        if unknown:
            raise DomainInvariantError(
                "outcome carries unknown field(s): %s. A rule outcome is one "
                "attention level and a reference to the reasoning behind it."
                % ", ".join(unknown))
        try:
            level = AttentionLevel(payload["attention_level"])
        except (KeyError, ValueError) as exc:
            raise DomainInvariantError(
                "outcome attention_level is missing or not a known level: %s" % exc
            ) from None
        return cls(attention_level=level,
                   rationale_reference=payload.get("rationale_reference", ""))


@dataclass(frozen=True, slots=True)
class RuleProvenance:
    """Everything a rule descends from, pinned by identity and by hash.

    Identity alone is not enough. A revision id says *which* record; the
    revision hash says what that record contained when it was approved. Storing
    both is what makes an after-the-fact edit detectable rather than invisible.
    """

    interpretation_id: CuratedInterpretationId
    curation_work_item_id: str
    curation_revision_id: str
    curation_revision_hash: str
    approval_envelope_hash: str
    protocol_version: str
    protocol_content_hash: str
    dataset_public_id: DatasetPublicId
    canonical_build_key: str
    canonical_build_content_hash: str
    evidence_build_key: str
    evidence_build_content_hash: str
    source_policy_version: str
    source_policy_content_hash: str
    evidence_record_uuids: Tuple[str, ...]

    def __post_init__(self) -> None:
        require_id(self.interpretation_id, CuratedInterpretationId,
                   "RuleProvenance.interpretation_id")
        if not isinstance(self.dataset_public_id, DatasetPublicId):
            raise DomainInvariantError("dataset_public_id must be a DatasetPublicId")
        for name in ("curation_work_item_id", "curation_revision_id",
                     "protocol_version", "canonical_build_key",
                     "evidence_build_key", "source_policy_version"):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        for name in ("curation_revision_hash", "approval_envelope_hash",
                     "protocol_content_hash", "canonical_build_content_hash",
                     "evidence_build_content_hash", "source_policy_content_hash"):
            _require_digest(getattr(self, name), name)
        object.__setattr__(self, "evidence_record_uuids",
                           tuple(self.evidence_record_uuids))
        if not self.evidence_record_uuids:
            raise DomainInvariantError(
                "a rule cites at least one evidence record (SAFETY-INV-006); a "
                "finding without a resolvable citation is an assertion")
        if len(set(self.evidence_record_uuids)) != len(self.evidence_record_uuids):
            raise DomainInvariantError(
                "evidence references repeat; a duplicated citation inflates how "
                "much evidence there appears to be")
        for index, value in enumerate(self.evidence_record_uuids):
            _require_text(value, "evidence_record_uuids[%d]" % index)
        # Canonical order so the rule hash does not depend on selection order.
        object.__setattr__(self, "evidence_record_uuids",
                           tuple(sorted(self.evidence_record_uuids)))

    def semantic_content(self) -> Dict[str, Any]:
        """Provenance as it enters the rule's content hash.

        ``approval_envelope_hash`` is excluded, and the exclusion is load-
        bearing rather than an oversight. The envelope pins the rule's content
        hash - that is how an approval names exactly what it approved - so if
        the content hash also covered the envelope hash, neither could be
        computed: changing one would change the other forever.

        The binding is therefore mutual but acyclic. The envelope says "I
        approve content X"; the rule says "my approval is envelope Y". The
        validator checks both directions, so an envelope approving different
        bytes, or a rule pointing at a different envelope, is caught - while
        each hash stays computable on its own.
        """
        payload = self.to_json()
        payload.pop("approval_envelope_hash")
        return payload

    def to_json(self) -> Dict[str, Any]:
        return {
            "interpretation_id": self.interpretation_id.to_json(),
            "curation_work_item_id": self.curation_work_item_id,
            "curation_revision_id": self.curation_revision_id,
            "curation_revision_hash": self.curation_revision_hash,
            "approval_envelope_hash": self.approval_envelope_hash,
            "protocol_version": self.protocol_version,
            "protocol_content_hash": self.protocol_content_hash,
            "dataset_public_id": self.dataset_public_id.to_json(),
            "canonical_build_key": self.canonical_build_key,
            "canonical_build_content_hash": self.canonical_build_content_hash,
            "evidence_build_key": self.evidence_build_key,
            "evidence_build_content_hash": self.evidence_build_content_hash,
            "source_policy_version": self.source_policy_version,
            "source_policy_content_hash": self.source_policy_content_hash,
            "evidence_record_uuids": list(self.evidence_record_uuids),
        }

    def boundary_key(self) -> Tuple[str, ...]:
        """The pins two rules must share to belong in one ruleset.

        Rules built against different canonical builds, evidence builds,
        protocols or source policies are answering under different assumptions.
        Mixing them silently would produce a ruleset whose members disagree
        about what the world is, which is not a set anybody reviewed.
        """
        return (
            self.dataset_public_id.to_json(),
            self.canonical_build_content_hash,
            self.evidence_build_content_hash,
            self.protocol_version,
            self.protocol_content_hash,
            self.source_policy_version,
            self.source_policy_content_hash,
        )


@dataclass(frozen=True, slots=True)
class ComputableRuleDefinition:
    """The immutable scientific content of one rule version.

    Contains no lifecycle state. Its hash covers exactly the semantic content -
    identity, condition, outcome and provenance - and nothing operational, so
    the same claim authored twice on different machines at different times
    hashes the same.
    """

    rule_id: ComputableRuleId
    family_id: RuleFamilyId
    rule_version: int
    condition: RuleCondition
    outcome: RuleOutcome
    provenance: RuleProvenance
    created_by: str
    created_at: _dt.datetime
    supersedes_rule_id: Optional[ComputableRuleId] = None
    rule_schema_version: str = RULE_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=lambda: EMPTY_MAPPING)

    def __post_init__(self) -> None:
        require_id(self.rule_id, ComputableRuleId, "ComputableRuleDefinition.rule_id")
        require_id(self.family_id, RuleFamilyId, "ComputableRuleDefinition.family_id")
        if self.supersedes_rule_id is not None:
            require_id(self.supersedes_rule_id, ComputableRuleId,
                       "ComputableRuleDefinition.supersedes_rule_id")
            if self.supersedes_rule_id == self.rule_id:
                raise DomainInvariantError("a rule cannot supersede itself")
        if isinstance(self.rule_version, bool) or \
                not isinstance(self.rule_version, int) or self.rule_version < 1:
            raise DomainInvariantError("rule_version counts from 1")
        if self.rule_version == 1 and self.supersedes_rule_id is not None:
            raise DomainInvariantError(
                "version 1 supersedes nothing; naming a predecessor here would "
                "claim a lineage that does not exist")
        if self.rule_version > 1 and self.supersedes_rule_id is None:
            raise DomainInvariantError(
                "version %d must name the rule version it supersedes, or its "
                "lineage is unreconstructible" % self.rule_version)
        if not isinstance(self.condition, RuleCondition):
            raise DomainInvariantError("condition must be a RuleCondition")
        if not isinstance(self.outcome, RuleOutcome):
            raise DomainInvariantError("outcome must be a RuleOutcome")
        if not isinstance(self.provenance, RuleProvenance):
            raise DomainInvariantError("provenance must be a RuleProvenance")
        if self.rule_schema_version != RULE_SCHEMA_VERSION:
            raise DomainInvariantError(
                "rule_schema_version %r is not %r"
                % (self.rule_schema_version, RULE_SCHEMA_VERSION))
        object.__setattr__(self, "created_by", _require_text(self.created_by, "created_by", 2))
        object.__setattr__(self, "created_at", ensure_utc(self.created_at, "created_at"))
        object.__setattr__(self, "metadata", freeze_json(dict(self.metadata or {})))

    # -- canonical content ----------------------------------------------

    def semantic_content(self) -> Dict[str, Any]:
        """Exactly the fields the content hash covers.

        ``approval_envelope_hash`` is not here either; see
        :meth:`RuleProvenance.semantic_content` for why the binding between a
        rule and its approval has to run one way only.

        ``created_at`` and ``created_by`` are **not** here. Two curators writing
        the identical claim under the identical provenance have made the same
        claim, and a hash that disagreed would make "did this rule change"
        unanswerable. Who wrote it and when is recorded, audited, and not part
        of what was claimed.
        """
        return {
            "rule_schema_version": self.rule_schema_version,
            "condition_schema_version": CONDITION_SCHEMA_VERSION,
            "rule_id": self.rule_id.to_json(),
            "family_id": self.family_id.to_json(),
            "rule_version": self.rule_version,
            "supersedes_rule_id": (self.supersedes_rule_id.to_json()
                                   if self.supersedes_rule_id else None),
            "condition": self.condition.to_json(),
            "outcome": self.outcome.to_json(),
            "provenance": self.provenance.semantic_content(),
        }

    def content_hash(self) -> str:
        return sha256_digest(self.semantic_content())

    def to_json(self) -> Dict[str, Any]:
        """The full serialised rule.

        Carries the *complete* provenance, including the approval envelope
        hash that :meth:`semantic_content` excludes from the digest. A stored
        rule that dropped its approval reference would be a rule nobody could
        trace to the act that approved it - the hash leaves it out, the record
        does not.
        """
        payload = self.semantic_content()
        payload["provenance"] = self.provenance.to_json()
        payload["created_by"] = self.created_by
        payload["created_at"] = self.created_at.isoformat().replace("+00:00", "Z")
        payload["metadata"] = dict(self.metadata)
        payload["content_hash"] = self.content_hash()
        return payload

    def axes(self) -> Tuple[CanonicalAxis, ...]:
        """Every canonical axis this rule covers, for comparison only."""
        return self.condition.expand()

    def sort_key(self) -> Tuple[Any, ...]:
        """Stable semantic ordering key for deterministic builds.

        Semantic first - gene, drug, phenotypes - so a manifest reads in an
        order a scientist can scan, and identity last so the order is total
        even when two rules cover the same axis.
        """
        return (
            self.condition.gene_canonical_key,
            self.condition.drug_canonical_key,
            tuple(value.value for value in self.condition.phenotype.values),
            self.family_id.to_json(),
            self.rule_version,
            self.rule_id.to_json(),
        )


@dataclass(frozen=True, slots=True)
class RuleLifecycleRecord:
    """Where one rule version has got to, and who moved it there.

    Separate from the definition so that advancing a rule does not rewrite the
    content an approval named. ``version`` is the optimistic-concurrency
    counter, in the WP-10 style.
    """

    rule_id: ComputableRuleId
    status: RuleStatus
    version: int
    content_hash: str
    created_at: _dt.datetime
    updated_at: Optional[_dt.datetime] = None
    validated_by: Optional[str] = None
    validated_at: Optional[_dt.datetime] = None
    validation_result_hash: Optional[str] = None
    deprecated_by: Optional[str] = None
    deprecated_at: Optional[_dt.datetime] = None
    deprecation_reason: Optional[str] = None

    def __post_init__(self) -> None:
        require_id(self.rule_id, ComputableRuleId, "RuleLifecycleRecord.rule_id")
        if not isinstance(self.status, RuleStatus):
            raise DomainInvariantError("status must be a RuleStatus")
        if isinstance(self.version, bool) or not isinstance(self.version, int) \
                or self.version < 0:
            raise DomainInvariantError("version is a non-negative integer")
        _require_digest(self.content_hash, "content_hash")
        object.__setattr__(self, "created_at", ensure_utc(self.created_at, "created_at"))
        for name in ("updated_at", "validated_at", "deprecated_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, ensure_utc(value, name))
        if self.status is RuleStatus.VALIDATED or (
                self.status is RuleStatus.DEPRECATED and self.validated_at):
            missing = [name for name in ("validated_by", "validated_at",
                                         "validation_result_hash")
                       if not getattr(self, name)]
            if self.status is RuleStatus.VALIDATED and missing:
                raise LifecycleError(
                    "a VALIDATED rule records %s; validation may never be "
                    "implied" % ", ".join(missing))
        if self.status is RuleStatus.DEPRECATED:
            missing = [name for name in ("deprecated_by", "deprecated_at",
                                         "deprecation_reason")
                       if not getattr(self, name)]
            if missing:
                raise LifecycleError(
                    "a DEPRECATED rule records %s; a rule withdrawn without a "
                    "named person and a stated reason cannot be reviewed"
                    % ", ".join(missing))
        if self.validation_result_hash is not None:
            _require_digest(self.validation_result_hash, "validation_result_hash")

    @property
    def is_executable(self) -> bool:
        """``SAFETY-INV-003``: only VALIDATED rules may ever execute.

        Membership of a FROZEN ruleset is additionally required; this property
        states the rule-level half of the contract.
        """
        return self.status is RuleStatus.VALIDATED

    @property
    def is_immutable(self) -> bool:
        """Content is fixed from VALIDATED onwards."""
        return self.status in (RuleStatus.VALIDATED, RuleStatus.DEPRECATED)

    def require_transition(self, target: RuleStatus) -> None:
        permitted = allowed_rule_transitions()[self.status]
        if target not in permitted:
            raise RuleLifecycleError(
                "a %s rule cannot move to %s; permitted: %s"
                % (self.status.value, target.value,
                   ", ".join(item.value for item in permitted)
                   or "nothing, this state is terminal"),
                current=self.status.value, requested=target.value)

    def require_content_unchanged(self, content_hash: str) -> None:
        if self.is_immutable and content_hash != self.content_hash:
            raise RuleImmutabilityError(
                "rule %s is %s and its content is fixed; the stored hash is %s "
                "and the supplied content hashes to %s. A correction is a new "
                "rule version in the same family, never an edit of an approved "
                "one." % (self.rule_id, self.status.value,
                          self.content_hash, content_hash))

    def to_json(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id.to_json(),
            "status": self.status.value,
            "version": self.version,
            "content_hash": self.content_hash,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "updated_at": (self.updated_at.isoformat().replace("+00:00", "Z")
                           if self.updated_at else None),
            "validated_by": self.validated_by,
            "validated_at": (self.validated_at.isoformat().replace("+00:00", "Z")
                             if self.validated_at else None),
            "validation_result_hash": self.validation_result_hash,
            "deprecated_by": self.deprecated_by,
            "deprecated_at": (self.deprecated_at.isoformat().replace("+00:00", "Z")
                              if self.deprecated_at else None),
            "deprecation_reason": self.deprecation_reason,
            "is_executable": self.is_executable,
        }


@dataclass(frozen=True, slots=True)
class RulesetMember:
    """One rule pinned into one ruleset, by identity **and** by hash."""

    rule_id: ComputableRuleId
    family_id: RuleFamilyId
    rule_version: int
    content_hash: str

    def __post_init__(self) -> None:
        require_id(self.rule_id, ComputableRuleId, "RulesetMember.rule_id")
        require_id(self.family_id, RuleFamilyId, "RulesetMember.family_id")
        if isinstance(self.rule_version, bool) or \
                not isinstance(self.rule_version, int) or self.rule_version < 1:
            raise DomainInvariantError("rule_version counts from 1")
        _require_digest(self.content_hash, "content_hash")

    def to_json(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id.to_json(),
            "family_id": self.family_id.to_json(),
            "rule_version": self.rule_version,
            "content_hash": self.content_hash,
        }

    def sort_key(self) -> Tuple[Any, ...]:
        return (self.family_id.to_json(), self.rule_version, self.rule_id.to_json())


@dataclass(frozen=True, slots=True)
class RulesetDefinition:
    """A ruleset and where it has got to.

    Membership is explicit and duplicate-free. A ruleset that named its members
    indirectly - "whatever is validated today" - could not pin a release,
    because the set it denotes changes underneath whatever cited it.
    """

    ruleset_id: RulesetVersionId
    public_id: RulesetPublicId
    status: RulesetStatus
    version: int
    created_by: str
    created_at: _dt.datetime
    members: Tuple[RulesetMember, ...] = ()
    manifest_hash: Optional[str] = None
    ruleset_content_hash: Optional[str] = None
    frozen_at: Optional[_dt.datetime] = None
    frozen_by: Optional[str] = None
    retired_at: Optional[_dt.datetime] = None
    retired_by: Optional[str] = None
    retirement_reason: Optional[str] = None
    updated_at: Optional[_dt.datetime] = None

    def __post_init__(self) -> None:
        require_id(self.ruleset_id, RulesetVersionId, "RulesetDefinition.ruleset_id")
        if not isinstance(self.public_id, RulesetPublicId):
            raise DomainInvariantError("public_id must be a RulesetPublicId")
        if not isinstance(self.status, RulesetStatus):
            raise DomainInvariantError("status must be a RulesetStatus")
        if isinstance(self.version, bool) or not isinstance(self.version, int) \
                or self.version < 0:
            raise DomainInvariantError("version is a non-negative integer")
        object.__setattr__(self, "created_by",
                           _require_text(self.created_by, "created_by", 2))
        object.__setattr__(self, "created_at", ensure_utc(self.created_at, "created_at"))
        for name in ("updated_at", "frozen_at", "retired_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, ensure_utc(value, name))
        seen = set()
        for member in self.members:
            if not isinstance(member, RulesetMember):
                raise DomainInvariantError("members must be RulesetMember records")
            if member.rule_id in seen:
                raise DomainInvariantError(
                    "rule %s appears twice in membership; a rule counted twice "
                    "would be weighted twice by anything reading the set"
                    % member.rule_id)
            seen.add(member.rule_id)
        object.__setattr__(self, "members",
                           tuple(sorted(self.members, key=lambda item: item.sort_key())))
        for name in ("manifest_hash", "ruleset_content_hash"):
            value = getattr(self, name)
            if value is not None:
                _require_digest(value, name)
        if self.status is RulesetStatus.FROZEN:
            if not self.members:
                raise LifecycleError(
                    "a FROZEN ruleset pins at least one rule. An empty frozen "
                    "ruleset would let a release claim rule membership it does "
                    "not have.")
            missing = [name for name in ("manifest_hash", "ruleset_content_hash",
                                         "frozen_by", "frozen_at")
                       if not getattr(self, name)]
            if missing:
                raise LifecycleError(
                    "a FROZEN ruleset records %s" % ", ".join(missing))
        if self.status is RulesetStatus.RETIRED:
            missing = [name for name in ("retired_by", "retired_at",
                                         "retirement_reason")
                       if not getattr(self, name)]
            if missing:
                raise LifecycleError(
                    "a RETIRED ruleset records %s" % ", ".join(missing))

    @property
    def member_count(self) -> int:
        return len(self.members)

    @property
    def is_executable(self) -> bool:
        """Only FROZEN. A merely VALIDATED ruleset is coherent, not published."""
        return self.status is RulesetStatus.FROZEN

    def require_transition(self, target: RulesetStatus) -> None:
        permitted = allowed_ruleset_transitions()[self.status]
        if target not in permitted:
            extra = ""
            if self.status is RulesetStatus.BUILDING and \
                    target is RulesetStatus.FROZEN:
                extra = (" Validating and freezing are two audited acts: a set "
                         "cannot become permanent without somebody deciding it "
                         "is coherent first.")
            raise RulesetLifecycleError(
                "a %s ruleset cannot move to %s; permitted: %s.%s"
                % (self.status.value, target.value,
                   ", ".join(item.value for item in permitted)
                   or "nothing, this state is terminal", extra),
                current=self.status.value, requested=target.value)

    def require_membership_open(self) -> None:
        if self.status is not RulesetStatus.BUILDING:
            raise RulesetLifecycleError(
                "membership changes while a ruleset is BUILDING; this one is "
                "%s. A validated set has had its membership checked, and a "
                "frozen one has been published." % self.status.value,
                current=self.status.value)

    def to_json(self) -> Dict[str, Any]:
        return {
            "ruleset_id": self.ruleset_id.to_json(),
            "public_id": self.public_id.to_json(),
            "status": self.status.value,
            "version": self.version,
            "member_count": self.member_count,
            "members": [member.to_json() for member in self.members],
            "manifest_hash": self.manifest_hash,
            "ruleset_content_hash": self.ruleset_content_hash,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "updated_at": (self.updated_at.isoformat().replace("+00:00", "Z")
                           if self.updated_at else None),
            "frozen_by": self.frozen_by,
            "frozen_at": (self.frozen_at.isoformat().replace("+00:00", "Z")
                          if self.frozen_at else None),
            "retired_by": self.retired_by,
            "retired_at": (self.retired_at.isoformat().replace("+00:00", "Z")
                           if self.retired_at else None),
            "retirement_reason": self.retirement_reason,
            "is_executable": self.is_executable,
        }


@dataclass(frozen=True, slots=True)
class RulesetApprovalRecord:
    """One rule's approval chain, as it enters a ruleset.

    Copied into the ruleset's approval list so a frozen artifact carries its
    own evidence of governance. A list that referred back to a mutable table
    would let a ruleset's approvals change after it was frozen.
    """

    rule_id: ComputableRuleId
    family_id: RuleFamilyId
    rule_version: int
    rule_content_hash: str
    approval_envelope_hash: str
    curation_revision_id: str
    curation_revision_hash: str
    created_by: str
    reviewed_by: str
    approved_by: str
    validated_by: str
    validated_at: _dt.datetime

    def __post_init__(self) -> None:
        require_id(self.rule_id, ComputableRuleId, "RulesetApprovalRecord.rule_id")
        require_id(self.family_id, RuleFamilyId, "RulesetApprovalRecord.family_id")
        for name in ("created_by", "reviewed_by", "approved_by", "validated_by",
                     "curation_revision_id"):
            object.__setattr__(self, name, _require_text(getattr(self, name), name, 2))
        for name in ("rule_content_hash", "approval_envelope_hash",
                     "curation_revision_hash"):
            _require_digest(getattr(self, name), name)
        object.__setattr__(self, "validated_at",
                           ensure_utc(self.validated_at, "validated_at"))
        lowered = {self.created_by.lower(), self.reviewed_by.lower()}
        if len(lowered) != 2:
            raise DomainInvariantError(
                "%s both created and reviewed this rule; one person checking "
                "their own work is not an independent review" % self.created_by)
        if self.approved_by.lower() == self.created_by.lower():
            raise DomainInvariantError(
                "%s both created and approved this rule; an author approving "
                "their own rule is self-release" % self.created_by)

    def to_json(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id.to_json(),
            "family_id": self.family_id.to_json(),
            "rule_version": self.rule_version,
            "rule_content_hash": self.rule_content_hash,
            "approval_envelope_hash": self.approval_envelope_hash,
            "curation_revision_id": self.curation_revision_id,
            "curation_revision_hash": self.curation_revision_hash,
            "created_by": self.created_by,
            "reviewed_by": self.reviewed_by,
            "approved_by": self.approved_by,
            "validated_by": self.validated_by,
            "validated_at": self.validated_at.isoformat().replace("+00:00", "Z"),
        }


@dataclass(frozen=True, slots=True)
class RulesetManifest:
    """What a frozen ruleset *is*, pinned by hash.

    Contains no operational metadata. Build duration, host, path and process
    live in the build log, because a manifest whose hash moved when the machine
    changed would make "is this the ruleset that was approved" unanswerable.

    ``structural_axes`` is an inventory of what the member rules are keyed on.
    It is deliberately not called coverage: the existence of a rule for a
    gene/drug/phenotype triple says a rule exists, not that the axis is
    clinically covered, and conflating the two is ``LEGACY-BUG-005``.
    """

    ruleset_schema_version: str
    rule_schema_version: str
    condition_schema_version: str
    ruleset_id: RulesetVersionId
    public_id: RulesetPublicId
    ruleset_version: int
    members: Tuple[RulesetMember, ...]
    dataset_public_id: DatasetPublicId
    canonical_build_key: str
    canonical_build_content_hash: str
    evidence_build_key: str
    evidence_build_content_hash: str
    protocol_version: str
    protocol_content_hash: str
    source_policy_version: str
    source_policy_content_hash: str
    structural_axes: Tuple[CanonicalAxis, ...]
    approval_list_hash: str
    note: str = (
        "structural_axes lists the gene/drug/phenotype triples the member rules "
        "are keyed on. It is a membership inventory, not a claim of clinical "
        "coverage: the existence of a rule for an axis does not mean the axis "
        "is adequately covered.")

    def __post_init__(self) -> None:
        require_id(self.ruleset_id, RulesetVersionId, "RulesetManifest.ruleset_id")
        if not isinstance(self.public_id, RulesetPublicId):
            raise DomainInvariantError("public_id must be a RulesetPublicId")
        if not isinstance(self.dataset_public_id, DatasetPublicId):
            raise DomainInvariantError("dataset_public_id must be a DatasetPublicId")
        if not self.members:
            raise DomainInvariantError("a manifest describes at least one member")
        object.__setattr__(self, "members",
                           tuple(sorted(self.members, key=lambda item: item.sort_key())))
        object.__setattr__(self, "structural_axes",
                           tuple(sorted(set(self.structural_axes))))
        for name in ("canonical_build_content_hash", "evidence_build_content_hash",
                     "protocol_content_hash", "source_policy_content_hash",
                     "approval_list_hash"):
            _require_digest(getattr(self, name), name)

    def semantic_content(self) -> Dict[str, Any]:
        """Everything the ruleset hash covers, and nothing operational."""
        return {
            "ruleset_schema_version": self.ruleset_schema_version,
            "rule_schema_version": self.rule_schema_version,
            "condition_schema_version": self.condition_schema_version,
            "ruleset_id": self.ruleset_id.to_json(),
            "public_id": self.public_id.to_json(),
            "ruleset_version": self.ruleset_version,
            "member_count": len(self.members),
            "members": [member.to_json() for member in self.members],
            "dataset_public_id": self.dataset_public_id.to_json(),
            "canonical_build_key": self.canonical_build_key,
            "canonical_build_content_hash": self.canonical_build_content_hash,
            "evidence_build_key": self.evidence_build_key,
            "evidence_build_content_hash": self.evidence_build_content_hash,
            "protocol_version": self.protocol_version,
            "protocol_content_hash": self.protocol_content_hash,
            "source_policy_version": self.source_policy_version,
            "source_policy_content_hash": self.source_policy_content_hash,
            "structural_axes": [axis.to_json() for axis in self.structural_axes],
            "approval_list_hash": self.approval_list_hash,
        }

    def content_hash(self) -> str:
        return sha256_digest(self.semantic_content())

    def to_json(self) -> Dict[str, Any]:
        payload = self.semantic_content()
        payload["manifest_hash"] = self.content_hash()
        payload["note"] = self.note
        return payload


@dataclass(frozen=True, slots=True)
class RulesetBuildRecord:
    """One build attempt: what was built, when, and whether it verified.

    Operational by design, and kept out of the manifest for exactly that
    reason. Timestamps and durations belong here; nothing here feeds a semantic
    hash.
    """

    build_id: RulesetBuildId
    ruleset_id: RulesetVersionId
    started_at: _dt.datetime
    completed_at: _dt.datetime
    built_by: str
    outcome: str
    manifest_hash: Optional[str] = None
    ruleset_content_hash: Optional[str] = None
    member_count: int = 0
    issue_codes: Tuple[str, ...] = ()
    artifact_relative_path: Optional[str] = None

    def __post_init__(self) -> None:
        require_id(self.build_id, RulesetBuildId, "RulesetBuildRecord.build_id")
        require_id(self.ruleset_id, RulesetVersionId, "RulesetBuildRecord.ruleset_id")
        object.__setattr__(self, "started_at", ensure_utc(self.started_at, "started_at"))
        object.__setattr__(self, "completed_at",
                           ensure_utc(self.completed_at, "completed_at"))
        if self.completed_at < self.started_at:
            raise DomainInvariantError("a build cannot finish before it started")
        object.__setattr__(self, "built_by", _require_text(self.built_by, "built_by", 2))
        if self.outcome not in ("SUCCEEDED", "REFUSED", "FAILED"):
            raise DomainInvariantError(
                "build outcome must be SUCCEEDED, REFUSED or FAILED")
        object.__setattr__(self, "issue_codes", tuple(sorted(set(self.issue_codes))))

    def to_json(self) -> Dict[str, Any]:
        return {
            "build_id": self.build_id.to_json(),
            "ruleset_id": self.ruleset_id.to_json(),
            "started_at": self.started_at.isoformat().replace("+00:00", "Z"),
            "completed_at": self.completed_at.isoformat().replace("+00:00", "Z"),
            "built_by": self.built_by,
            "outcome": self.outcome,
            "manifest_hash": self.manifest_hash,
            "ruleset_content_hash": self.ruleset_content_hash,
            "member_count": self.member_count,
            "issue_codes": list(self.issue_codes),
            "artifact_relative_path": self.artifact_relative_path,
            "note": ("Operational record. Nothing in this file feeds a semantic "
                     "hash: a ruleset's identity must not change because it was "
                     "rebuilt on another machine at another time."),
        }


@dataclass(frozen=True, slots=True)
class FrozenRuleset:
    """A verified, immutable ruleset as the engine will see it.

    Produced only by loading a frozen artifact whose every checksum verified,
    whose manifest hash matched its content, whose approval list was complete,
    and whose every member hashed to what the manifest pinned. Anything less
    raises rather than returning a partially verified object: an engine handed
    "most of a ruleset" would produce findings nobody could account for.
    """

    manifest: RulesetManifest
    definitions: Tuple[ComputableRuleDefinition, ...]
    approvals: Tuple[RulesetApprovalRecord, ...]
    ruleset_content_hash: str
    verified_at: _dt.datetime

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, RulesetManifest):
            raise DomainInvariantError("manifest must be a RulesetManifest")
        if not self.definitions:
            raise DomainInvariantError("a frozen ruleset carries at least one rule")
        _require_digest(self.ruleset_content_hash, "ruleset_content_hash")
        object.__setattr__(self, "definitions",
                           tuple(sorted(self.definitions,
                                        key=lambda item: item.sort_key())))
        object.__setattr__(self, "approvals",
                           tuple(sorted(self.approvals,
                                        key=lambda item: item.rule_id.to_json())))
        object.__setattr__(self, "verified_at",
                           ensure_utc(self.verified_at, "verified_at"))

    @property
    def ruleset_id(self) -> RulesetVersionId:
        return self.manifest.ruleset_id

    @property
    def public_id(self) -> RulesetPublicId:
        return self.manifest.public_id

    @property
    def member_count(self) -> int:
        return len(self.definitions)

    def rules(self) -> Tuple[ComputableRuleDefinition, ...]:
        """The executable member rules, immutable and in canonical order."""
        return self.definitions

    def to_json(self) -> Dict[str, Any]:
        return {
            "ruleset_id": self.ruleset_id.to_json(),
            "public_id": self.public_id.to_json(),
            "manifest_hash": self.manifest.content_hash(),
            "ruleset_content_hash": self.ruleset_content_hash,
            "member_count": self.member_count,
            "verified_at": self.verified_at.isoformat().replace("+00:00", "Z"),
        }
