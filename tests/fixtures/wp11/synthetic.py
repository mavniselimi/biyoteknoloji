# -*- coding: utf-8 -*-
"""SYNTHETIC WP-11 rule fixtures. TEST ONLY. NOT CLINICAL DATA.

NOT FOR REAL ASSESSMENT. Every gene, drug, phenotype, attention level, actor,
hash and approval below is invented for the purpose of exercising the state
machine. No value here was reviewed by anybody, and none of it is a statement
about any medicine.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, Mapping, Optional, Tuple

from pgx.curation.vocabulary import (Applicability, ConclusionState,
                                     ConflictState, CurationRole)
from pgx.domain.enums import (AttentionLevel, CurationStatus, Phenotype,
                              RuleStatus, RulesetStatus)
from pgx.domain.hashing import sha256_digest
from pgx.domain.identifiers import (ComputableRuleId, CuratedInterpretationId,
                                    DatasetPublicId, RulesetPublicId,
                                    RulesetVersionId)
from pgx.rules.conditions import PhenotypeMatch, RuleCondition
from pgx.rules.identifiers import RuleFamilyId
from pgx.rules.models import (ComputableRuleDefinition, RuleLifecycleRecord,
                              RuleOutcome, RuleProvenance,
                              RulesetApprovalRecord, RulesetDefinition,
                              RulesetMember)
from pgx.rules.validator import ValidationContext

#: Stamped into every synthetic artifact this module produces.
SYNTHETIC_MARKERS: Tuple[str, ...] = (
    "SYNTHETIC", "TEST ONLY", "NOT CLINICAL DATA", "NOT FOR REAL ASSESSMENT")

# -- a world that does not exist --------------------------------------------

SYNTHETIC_DATASET = DatasetPublicId("PGX-DATA-29991231-001")
SYNTHETIC_CANONICAL_KEY = "TEST-CANONICAL-BUILD/synthetic"
SYNTHETIC_CANONICAL_HASH = "sha256:" + "1" * 64
SYNTHETIC_EVIDENCE_KEY = "TEST-EVIDENCE-BUILD/synthetic"
SYNTHETIC_EVIDENCE_HASH = "sha256:" + "2" * 64
SYNTHETIC_PROTOCOL_VERSION = "test-protocol/9.9.9-synthetic"
SYNTHETIC_PROTOCOL_HASH = "sha256:" + "3" * 64
SYNTHETIC_SOURCE_POLICY_VERSION = "test-source-policy/9.9.9-synthetic"
SYNTHETIC_SOURCE_POLICY_HASH = "sha256:" + "4" * 64
SYNTHETIC_REVISION_ID = "TEST-REV-000001"
SYNTHETIC_REVISION_HASH = "sha256:" + "5" * 64

#: Deliberately not a real gene or drug in this project's canonical dataset.
#: A fixture naming CYP2C19 and clopidogrel would read as a claim about them.
SYNTHETIC_GENE = "GENE:TESTGENE1"
SYNTHETIC_DRUG = "DRUG:testdrug-alpha"

SYNTHETIC_EVIDENCE_UUIDS: Tuple[str, ...] = (
    "aaaaaaaa-0000-4000-8000-000000000001",
    "aaaaaaaa-0000-4000-8000-000000000002",
)

TEST_AUTHOR = "TEST-rule-author-1"
TEST_REVIEWER = "TEST-rule-reviewer-1"
TEST_APPROVER = "TEST-rule-approver-1"
TEST_VALIDATOR = "TEST-rule-validator-1"
TEST_BUILDER = "TEST-rule-builder-1"

#: Who these invented actors are allowed to be. Each holds exactly one role,
#: so a test that passes the wrong actor fails on the role rather than
#: succeeding by accident - which is also what keeps separation of duties
#: assertable: no fixture actor can perform two separated acts.
SYNTHETIC_ROLES: Mapping[str, Any] = {
    TEST_AUTHOR: [CurationRole.SCIENTIFIC_CURATOR],
    TEST_REVIEWER: [CurationRole.INDEPENDENT_SCIENTIFIC_REVIEWER],
    TEST_APPROVER: [CurationRole.PROTOCOL_OWNER],
    TEST_VALIDATOR: [CurationRole.INDEPENDENT_SCIENTIFIC_REVIEWER],
    TEST_BUILDER: [CurationRole.ADJUDICATOR],
}

MOMENT = _dt.datetime(2099, 1, 1, 12, 0, tzinfo=_dt.timezone.utc)


def synthetic_condition(gene: str = SYNTHETIC_GENE,
                        drug: str = SYNTHETIC_DRUG,
                        operator: str = "EXACT",
                        phenotypes: Tuple[Phenotype, ...] = (Phenotype.POOR,)
                        ) -> RuleCondition:
    return RuleCondition(
        gene_canonical_key=gene, drug_canonical_key=drug,
        phenotype=PhenotypeMatch(operator=operator, values=phenotypes))


def synthetic_provenance(**overrides: Any) -> RuleProvenance:
    values: Dict[str, Any] = {
        "interpretation_id": CuratedInterpretationId.parse(
            "bbbbbbbb-0000-4000-8000-000000000001"),
        "curation_work_item_id": "TEST-WI-SYNTHETIC-1",
        "curation_revision_id": SYNTHETIC_REVISION_ID,
        "curation_revision_hash": SYNTHETIC_REVISION_HASH,
        "approval_envelope_hash": "sha256:" + "6" * 64,
        "protocol_version": SYNTHETIC_PROTOCOL_VERSION,
        "protocol_content_hash": SYNTHETIC_PROTOCOL_HASH,
        "dataset_public_id": SYNTHETIC_DATASET,
        "canonical_build_key": SYNTHETIC_CANONICAL_KEY,
        "canonical_build_content_hash": SYNTHETIC_CANONICAL_HASH,
        "evidence_build_key": SYNTHETIC_EVIDENCE_KEY,
        "evidence_build_content_hash": SYNTHETIC_EVIDENCE_HASH,
        "source_policy_version": SYNTHETIC_SOURCE_POLICY_VERSION,
        "source_policy_content_hash": SYNTHETIC_SOURCE_POLICY_HASH,
        "evidence_record_uuids": SYNTHETIC_EVIDENCE_UUIDS,
    }
    values.update(overrides)
    return RuleProvenance(**values)


def synthetic_envelope(definition: "ComputableRuleDefinition",
                       **overrides: Any) -> Dict[str, Any]:
    """A WP-10 approval envelope naming this exact rule version."""
    from pgx.curation.workflow.approval import RULE_APPROVAL_ENVELOPE_VERSION
    payload: Dict[str, Any] = {
        "envelope_version": RULE_APPROVAL_ENVELOPE_VERSION,
        "rule_public_id": definition.rule_id.to_json(),
        "rule_version": str(definition.rule_version),
        "rule_content_hash": definition.content_hash(),
        "curated_interpretation_id":
            definition.provenance.interpretation_id.to_json(),
        "curated_interpretation_status": "CURATED",
        "curation_work_item_id": definition.provenance.curation_work_item_id,
        "curation_revision_id": definition.provenance.curation_revision_id,
        "curation_revision_content_hash":
            definition.provenance.curation_revision_hash,
        "protocol_version": definition.provenance.protocol_version,
        "protocol_content_hash": definition.provenance.protocol_content_hash,
        "evidence_record_uuids": list(definition.provenance.evidence_record_uuids),
        "evidence_build_content_hash":
            definition.provenance.evidence_build_content_hash,
        "source_versions": {"test.synthetic.source": "9.9.9"},
        "created_by": TEST_AUTHOR,
        "created_at": "2099-01-01T10:00:00Z",
        "reviewed_by": TEST_REVIEWER,
        "reviewed_at": "2099-01-02T10:00:00Z",
        "approved_by": TEST_APPROVER,
        "approved_at": "2099-01-03T10:00:00Z",
        "approval_rationale":
            "SYNTHETIC TEST ONLY: this envelope approves a fixture, not a "
            "conclusion about any medicine.",
    }
    payload.update(overrides)
    return payload


def synthetic_rule(rule_id: Optional[ComputableRuleId] = None,
                   family_id: Optional[RuleFamilyId] = None,
                   condition: Optional[RuleCondition] = None,
                   attention: AttentionLevel = AttentionLevel.MEDIUM,
                   rule_version: int = 1,
                   supersedes: Optional[ComputableRuleId] = None,
                   provenance: Optional[RuleProvenance] = None,
                   created_by: str = TEST_AUTHOR,
                   ) -> ComputableRuleDefinition:
    """One synthetic rule, with its approval envelope hash already consistent.

    Built in two passes: the envelope names the rule's content hash, and the
    rule pins the envelope's hash, so the pair is internally consistent the way
    a real approved rule would be.
    """
    draft = ComputableRuleDefinition(
        rule_id=rule_id or ComputableRuleId.new(),
        family_id=family_id or RuleFamilyId.new(),
        rule_version=rule_version,
        condition=condition or synthetic_condition(),
        outcome=RuleOutcome(
            attention_level=attention,
            rationale_reference="TEST-WI-SYNTHETIC-1/%s" % SYNTHETIC_REVISION_ID),
        provenance=provenance or synthetic_provenance(),
        created_by=created_by, created_at=MOMENT,
        supersedes_rule_id=supersedes,
        metadata={"synthetic": True, "markers": list(SYNTHETIC_MARKERS)})
    envelope = synthetic_envelope(draft)
    return ComputableRuleDefinition(
        rule_id=draft.rule_id, family_id=draft.family_id,
        rule_version=draft.rule_version, condition=draft.condition,
        outcome=draft.outcome,
        provenance=synthetic_provenance(
            **dict({"approval_envelope_hash": sha256_digest(envelope)},
                   **({"interpretation_id": draft.provenance.interpretation_id}
                      if provenance is None else {
                          name: getattr(draft.provenance, name)
                          for name in ("interpretation_id",
                                       "curation_work_item_id",
                                       "curation_revision_id",
                                       "curation_revision_hash",
                                       "protocol_version",
                                       "protocol_content_hash",
                                       "dataset_public_id",
                                       "canonical_build_key",
                                       "canonical_build_content_hash",
                                       "evidence_build_key",
                                       "evidence_build_content_hash",
                                       "source_policy_version",
                                       "source_policy_content_hash",
                                       "evidence_record_uuids")}))),
        created_by=draft.created_by, created_at=draft.created_at,
        supersedes_rule_id=draft.supersedes_rule_id,
        metadata=draft.metadata)


def synthetic_context(definition: ComputableRuleDefinition,
                      **overrides: Any) -> ValidationContext:
    """A world in which this rule would validate. It does not exist."""
    envelope = synthetic_envelope(definition)
    values: Dict[str, Any] = {
        "known_gene_keys": frozenset({definition.condition.gene_canonical_key}),
        "known_drug_keys": frozenset({definition.condition.drug_canonical_key}),
        "known_dataset_public_ids": frozenset({SYNTHETIC_DATASET.to_json()}),
        "known_evidence_uuids": frozenset(
            definition.provenance.evidence_record_uuids),
        "interpretation_status": CurationStatus.CURATED,
        "curation_revision_id": definition.provenance.curation_revision_id,
        "curation_revision_hash": definition.provenance.curation_revision_hash,
        "conclusion_state": ConclusionState.SUPPORTED,
        "applicability": Applicability.APPLICABLE,
        "conflict_state": ConflictState.NONE_IDENTIFIED,
        "conflict_material": False,
        "protocol_version": definition.provenance.protocol_version,
        "protocol_content_hash": definition.provenance.protocol_content_hash,
        "source_policy_version": definition.provenance.source_policy_version,
        "source_policy_content_hash":
            definition.provenance.source_policy_content_hash,
        "source_policy_permits_rules": True,
        "evidence_build_content_hash":
            definition.provenance.evidence_build_content_hash,
        "evidence_build_approved_for_rules": True,
        "approval_envelope": envelope,
        "envelope_role_lookup": SYNTHETIC_ROLES,
        "actor_id": TEST_VALIDATOR,
        "actor_roles": frozenset({CurationRole.INDEPENDENT_SCIENTIFIC_REVIEWER}),
    }
    values.update(overrides)
    return ValidationContext(**values)


def synthetic_lifecycle(definition: ComputableRuleDefinition,
                        status: RuleStatus = RuleStatus.VALIDATED,
                        version: int = 2) -> RuleLifecycleRecord:
    extra: Dict[str, Any] = {}
    if status in (RuleStatus.VALIDATED, RuleStatus.DEPRECATED):
        extra.update(validated_by=TEST_VALIDATOR, validated_at=MOMENT,
                     validation_result_hash="sha256:" + "7" * 64)
    if status is RuleStatus.DEPRECATED:
        extra.update(deprecated_by=TEST_VALIDATOR, deprecated_at=MOMENT,
                     deprecation_reason="SYNTHETIC TEST ONLY: withdrawn by a "
                                        "fixture, not by a scientist.")
    return RuleLifecycleRecord(
        rule_id=definition.rule_id, status=status, version=version,
        content_hash=definition.content_hash(), created_at=MOMENT, **extra)


def synthetic_approval_record(definition: ComputableRuleDefinition
                              ) -> RulesetApprovalRecord:
    return RulesetApprovalRecord(
        rule_id=definition.rule_id, family_id=definition.family_id,
        rule_version=definition.rule_version,
        rule_content_hash=definition.content_hash(),
        approval_envelope_hash=definition.provenance.approval_envelope_hash,
        curation_revision_id=definition.provenance.curation_revision_id,
        curation_revision_hash=definition.provenance.curation_revision_hash,
        created_by=TEST_AUTHOR, reviewed_by=TEST_REVIEWER,
        approved_by=TEST_APPROVER, validated_by=TEST_VALIDATOR,
        validated_at=MOMENT)


def synthetic_ruleset(definitions: Tuple[ComputableRuleDefinition, ...],
                      status: RulesetStatus = RulesetStatus.VALIDATED,
                      version: int = 1,
                      public_id: str = "PGX-RULESET-29991231-001",
                      **overrides: Any) -> RulesetDefinition:
    members = tuple(RulesetMember(
        rule_id=definition.rule_id, family_id=definition.family_id,
        rule_version=definition.rule_version,
        content_hash=definition.content_hash()) for definition in definitions)
    values: Dict[str, Any] = {
        "ruleset_id": RulesetVersionId.parse(
            "cccccccc-0000-4000-8000-000000000001"),
        "public_id": RulesetPublicId(public_id),
        "status": status, "version": version, "members": members,
        "created_by": TEST_BUILDER, "created_at": MOMENT,
    }
    # A FROZEN or RETIRED ruleset must carry the record of who froze or retired
    # it: the model refuses one that does not, which is why these are supplied
    # here rather than left for each caller. Supplying them is not a way around
    # the invariant - a ruleset still cannot reach either state except through
    # the audited transitions - it is what lets a test construct the state it
    # wants to assert *about*.
    if status in (RulesetStatus.FROZEN, RulesetStatus.RETIRED):
        values.update(manifest_hash="sha256:" + "a" * 64,
                      ruleset_content_hash="sha256:" + "b" * 64,
                      frozen_by=TEST_BUILDER, frozen_at=MOMENT)
        if not members:
            values["members"] = (RulesetMember(
                rule_id=ComputableRuleId.parse(
                    "eeeeeeee-0000-4000-8000-000000000001"),
                family_id=RuleFamilyId.parse(
                    "ffffffff-0000-4000-8000-000000000001"),
                rule_version=1, content_hash="sha256:" + "c" * 64),)
    if status is RulesetStatus.RETIRED:
        values.update(retired_by=TEST_BUILDER, retired_at=MOMENT,
                      retirement_reason="SYNTHETIC TEST ONLY: retired by a "
                                        "fixture, not by anybody.")
    values.update(overrides)
    return RulesetDefinition(**values)


def synthetic_build_inputs(definitions: Tuple[ComputableRuleDefinition, ...],
                           ruleset: Optional[RulesetDefinition] = None):
    from pgx.rules.builder import BuildInputs
    ruleset = ruleset or synthetic_ruleset(definitions)
    return BuildInputs(
        ruleset=ruleset, definitions=definitions,
        lifecycles={definition.rule_id.to_json(): synthetic_lifecycle(definition)
                    for definition in definitions},
        approvals=tuple(synthetic_approval_record(definition)
                        for definition in definitions),
        dataset_public_id=SYNTHETIC_DATASET,
        canonical_build_key=SYNTHETIC_CANONICAL_KEY,
        canonical_build_content_hash=SYNTHETIC_CANONICAL_HASH,
        evidence_build_key=SYNTHETIC_EVIDENCE_KEY,
        evidence_build_content_hash=SYNTHETIC_EVIDENCE_HASH,
        protocol_version=SYNTHETIC_PROTOCOL_VERSION,
        protocol_content_hash=SYNTHETIC_PROTOCOL_HASH,
        source_policy_version=SYNTHETIC_SOURCE_POLICY_VERSION,
        source_policy_content_hash=SYNTHETIC_SOURCE_POLICY_HASH)


def synthetic_rule_role_provider():
    """A provider knowing only ``TEST-`` actors.

    The production provider knows nobody: this repository assigns no real
    scientific role to anybody, which is why no real rule can be drafted,
    curated, validated or frozen. Everything below exists so the state machine
    can be exercised, not so it can be bypassed.
    """
    from pgx.curation.workflow.roles import StaticRoleProvider
    return StaticRoleProvider(dict(SYNTHETIC_ROLES))


def synthetic_clock(start: Optional[_dt.datetime] = None,
                    step_seconds: int = 1):
    """A monotonic fake clock, so audit order is assertable."""
    state = {"now": start or MOMENT}
    step = _dt.timedelta(seconds=step_seconds)

    def _clock() -> _dt.datetime:
        value = state["now"]
        state["now"] = value + step
        return value

    return _clock


def build_rule_service(clock=None):
    """A ``RuleService`` over an in-memory store. Returns (service, store)."""
    from pgx.application.rule_service import RuleService
    from pgx.rules.memory import InMemoryRuleStore, InMemoryRuleUnitOfWork
    store = InMemoryRuleStore()
    service = RuleService(
        uow_factory=lambda: InMemoryRuleUnitOfWork(store),
        role_provider=synthetic_rule_role_provider(),
        clock=clock or synthetic_clock())
    return service, store


def build_ruleset_service(store=None, clock=None):
    """A ``RulesetService`` over an in-memory store. Returns (service, store)."""
    from pgx.application.ruleset_service import RulesetService
    from pgx.rules.memory import InMemoryRuleStore, InMemoryRuleUnitOfWork
    store = store if store is not None else InMemoryRuleStore()
    service = RulesetService(
        uow_factory=lambda: InMemoryRuleUnitOfWork(store),
        role_provider=synthetic_rule_role_provider(),
        clock=clock or synthetic_clock())
    return service, store


def synthetic_inputs_factory(ruleset, definitions, lifecycles, approvals):
    """The ``inputs_factory`` a synthetic freeze needs.

    Takes the definitions and lifecycles the service loaded from the store, so
    the build is over what was actually admitted rather than over what the
    test happened to have in hand.
    """
    from pgx.rules.builder import BuildInputs
    return BuildInputs(
        ruleset=ruleset, definitions=tuple(definitions),
        lifecycles=dict(lifecycles), approvals=tuple(approvals),
        dataset_public_id=SYNTHETIC_DATASET,
        canonical_build_key=SYNTHETIC_CANONICAL_KEY,
        canonical_build_content_hash=SYNTHETIC_CANONICAL_HASH,
        evidence_build_key=SYNTHETIC_EVIDENCE_KEY,
        evidence_build_content_hash=SYNTHETIC_EVIDENCE_HASH,
        protocol_version=SYNTHETIC_PROTOCOL_VERSION,
        protocol_content_hash=SYNTHETIC_PROTOCOL_HASH,
        source_policy_version=SYNTHETIC_SOURCE_POLICY_VERSION,
        source_policy_content_hash=SYNTHETIC_SOURCE_POLICY_HASH)


def validated_rules(count: int = 1, service=None, store=None):
    """``count`` rules taken all the way to VALIDATED. Returns
    ``(rule_service, store, definitions)``.

    Each rule is drafted by the author, curated by the author, and validated
    by a *different* actor. That separation is not a fixture convenience: the
    service refuses the alternative, and a fixture that could do it in one
    identity would be testing a system nobody would accept.
    """
    genes = ("GENE:TESTGENE1", "GENE:TESTGENE2", "GENE:TESTGENE3",
             "GENE:TESTGENE4", "GENE:TESTGENE5")
    if service is None:
        service, store = build_rule_service()
    definitions = []
    for index in range(count):
        definition = synthetic_rule(
            condition=synthetic_condition(gene=genes[index % len(genes)]))
        service.draft_rule(actor_id=TEST_AUTHOR, definition=definition,
                           reason="SYNTHETIC TEST ONLY")
        service.mark_curated(actor_id=TEST_AUTHOR,
                             rule_id=definition.rule_id, expected_version=0,
                             context=synthetic_context(definition),
                             reason="SYNTHETIC TEST ONLY")
        service.validate(actor_id=TEST_VALIDATOR, rule_id=definition.rule_id,
                         expected_version=1,
                         context=synthetic_context(definition),
                         reason="SYNTHETIC TEST ONLY")
        definitions.append(definition)
    return service, store, tuple(definitions)


def frozen_ruleset(destination: str, count: int = 2):
    """One synthetic ruleset taken DRAFT -> ... -> FROZEN on disk.

    Returns ``(ruleset_service, store, definitions, result)``. ``destination``
    is the artifact directory; it must not already exist, because publishing
    over a frozen artifact is refused.
    """
    rule_service, store, definitions = validated_rules(count)
    service, _store = build_ruleset_service(store=store)
    ruleset = synthetic_ruleset((), status=RulesetStatus.BUILDING)
    result = service.create(actor_id=TEST_BUILDER, ruleset=ruleset,
                            reason="SYNTHETIC TEST ONLY")
    for definition in definitions:
        result = service.add_member(
            actor_id=TEST_BUILDER, ruleset_id=ruleset.ruleset_id,
            rule_id=definition.rule_id,
            expected_version=result.ruleset.version,
            reason="SYNTHETIC TEST ONLY")
    result = service.validate(actor_id=TEST_BUILDER,
                              ruleset_id=ruleset.ruleset_id,
                              expected_version=result.ruleset.version,
                              reason="SYNTHETIC TEST ONLY")
    result = service.build_and_freeze(
        actor_id=TEST_BUILDER, ruleset_id=ruleset.ruleset_id,
        expected_version=result.ruleset.version, destination=destination,
        inputs_factory=synthetic_inputs_factory,
        approvals=tuple(synthetic_approval_record(definition)
                        for definition in definitions),
        reason="SYNTHETIC TEST ONLY")
    return service, store, definitions, result
