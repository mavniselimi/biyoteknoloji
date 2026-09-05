# -*- coding: utf-8 -*-
"""The versioned curation protocol document (WP-09).

The protocol is data, not prose. Every requirement is an object with a stable
identifier, so a document, a schema field, a validation issue code, a test and
a checklist item can all point at the same thing and a validator can prove
they still do.

Two states are tracked separately and never collapsed:

* **technical completeness** - whether the protocol is structurally whole;
* **expert approval** - whether a named scientist has signed it.

A structurally perfect protocol that nobody approved is complete and blocked,
and one boolean covering both would let the first stand in for the second.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from pgx.curation.errors import (ApprovalError, CaseSeparationError,
                                 ProtocolError, RoleSeparationError)
from pgx.curation.models import ReviewSignature
from pgx.curation.vocabulary import (CaseRole, CurationRole, ProtocolStatus,
                                     SCIENTIFIC_APPROVAL_ROLES,
                                     VOCABULARY_STATUS, VOCABULARY_VERSION,
                                     vocabulary_registry)
from pgx.domain.hashing import ensure_utc, sha256_digest

__all__ = [
    "CASE_ROLE_RULES",
    "CURATION_PROTOCOL_VERSION",
    "PROTOCOL_REQUIREMENTS",
    "ROLE_DEFINITIONS",
    "ApprovalRecord",
    "CaseAssignment",
    "ProtocolDocument",
    "ProtocolRequirement",
    "RoleDefinition",
    "build_protocol_document",
]

#: The protocol's own version. A curation record names the version it was made
#: under, so a conclusion reached under v1 is never silently re-read as if it
#: had been made under v2.
CURATION_PROTOCOL_VERSION = "pgx-curation-protocol/1"


@dataclass(frozen=True)
class ProtocolRequirement:
    """One numbered obligation the protocol imposes.

    ``requirement_id`` is stable for the life of the protocol version. It is
    what the documentation, the schemas, the validator's issue codes and the
    tests all cite, which is the only way to tell whether a principle written
    in a document is actually enforced anywhere.
    """

    requirement_id: str
    title: str
    statement: str
    implementation: str
    schema_field: Optional[str]
    validation_code: str
    test_reference: str
    checklist_item: str

    def __post_init__(self) -> None:
        for name in ("requirement_id", "title", "statement", "implementation",
                     "validation_code", "test_reference", "checklist_item"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ProtocolError("ProtocolRequirement.%s is required" % name,
                                    code="PROT_REQUIREMENT_INCOMPLETE")
        if not self.requirement_id.startswith("CUR-PROT-"):
            raise ProtocolError(
                "requirement id %r must start with CUR-PROT-"
                % self.requirement_id, code="PROT_REQUIREMENT_ID_SHAPE")

    def to_json(self) -> Dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "title": self.title,
            "statement": self.statement,
            "implementation": self.implementation,
            "schema_field": self.schema_field,
            "validation_code": self.validation_code,
            "test_reference": self.test_reference,
            "checklist_item": self.checklist_item,
        }


@dataclass(frozen=True)
class RoleDefinition:
    """What one role may and may not do.

    ``may_approve_science`` is the field that matters. An engineering observer
    can confirm the pipeline is sound and the provenance steward can confirm
    the chain verifies; neither of those is a statement that the science is
    right, and this flag keeps the two apart.
    """

    role: CurationRole
    responsibility: str
    may_author_conclusion: bool
    may_review_conclusion: bool
    may_approve_science: bool
    may_adjudicate: bool
    notes: str

    def __post_init__(self) -> None:
        if not isinstance(self.role, CurationRole):
            raise RoleSeparationError("role must be a CurationRole")
        for name in ("responsibility", "notes"):
            if not str(getattr(self, name)).strip():
                raise ProtocolError("RoleDefinition.%s is required" % name,
                                    code="PROT_ROLE_INCOMPLETE")
        if self.may_approve_science and self.role not in SCIENTIFIC_APPROVAL_ROLES:
            raise RoleSeparationError(
                "%s is not a scientific approval role" % self.role.value)

    def to_json(self) -> Dict[str, Any]:
        return {
            "role": self.role.value,
            "responsibility": self.responsibility,
            "may_author_conclusion": self.may_author_conclusion,
            "may_review_conclusion": self.may_review_conclusion,
            "may_approve_science": self.may_approve_science,
            "may_adjudicate": self.may_adjudicate,
            "notes": self.notes,
        }


#: The six roles, and exactly what each may do. WP-10 enforces this; WP-09
#: states it.
ROLE_DEFINITIONS: Tuple[RoleDefinition, ...] = (
    RoleDefinition(
        role=CurationRole.PROTOCOL_OWNER,
        responsibility="Owns this document and its versioning; proposes "
                       "changes and records who approved them.",
        may_author_conclusion=False, may_review_conclusion=False,
        may_approve_science=False, may_adjudicate=False,
        notes="Owning the protocol is not approving the science it governs. "
              "The owner may not sign off a conclusion made under it."),
    RoleDefinition(
        role=CurationRole.SCIENTIFIC_CURATOR,
        responsibility="Selects evidence, records the normalized conclusion "
                       "and writes the structured rationale.",
        may_author_conclusion=True, may_review_conclusion=False,
        may_approve_science=True, may_adjudicate=False,
        notes="May not review their own conclusion; the independent reviewer "
              "must be a different person."),
    RoleDefinition(
        role=CurationRole.INDEPENDENT_SCIENTIFIC_REVIEWER,
        responsibility="Independently checks the evidence selection, the "
                       "conclusion and the rationale.",
        may_author_conclusion=False, may_review_conclusion=True,
        may_approve_science=True, may_adjudicate=False,
        notes="Independence means a different person, not a second pass by "
              "the author."),
    RoleDefinition(
        role=CurationRole.ADJUDICATOR,
        responsibility="Resolves a disagreement between curator and reviewer, "
                       "or a material source conflict, with written reasons.",
        may_author_conclusion=False, may_review_conclusion=True,
        may_approve_science=True, may_adjudicate=True,
        notes="Must preserve both original responses. An adjudication that "
              "replaced them would erase the disagreement it settled."),
    RoleDefinition(
        role=CurationRole.DATA_PROVENANCE_STEWARD,
        responsibility="Confirms evidence identity, versions, locators and "
                       "trace verification.",
        may_author_conclusion=False, may_review_conclusion=False,
        may_approve_science=False, may_adjudicate=False,
        notes="Confirms the chain is intact, which is not a statement that "
              "the scientific conclusion is correct."),
    RoleDefinition(
        role=CurationRole.ENGINEERING_OBSERVER,
        responsibility="Maintains the tooling, schemas and validators; "
                       "observes exercises without answering them.",
        may_author_conclusion=False, may_review_conclusion=False,
        may_approve_science=False, may_adjudicate=False,
        notes="An engineering role alone can never approve scientific "
              "meaning. Neither can an automated system or a language model, "
              "which have no role in this vocabulary at all."),
)


#: Which case roles may and may not coexist for one case, and why.
CASE_ROLE_RULES: Mapping[str, str] = {
    "one_role_per_case":
        "A case holds exactly one role. Holding two would let a holdout "
        "result be reported as independent after informing development.",
    "development_and_holdout_disjoint":
        "DEVELOPMENT, INTERNAL_HOLDOUT and EXPERT_HOLDOUT are mutually "
        "exclusive (SAFETY-INV-009).",
    "legacy_and_demo_are_development":
        "Legacy manual hints and demo profiles are DEVELOPMENT or TRAINING "
        "only. They shaped the code that would be measured against them.",
    "derived_cases_are_not_external":
        "A case built from the current evidence set is not independent "
        "external validation, whatever it is labelled.",
    "no_expected_answers_in_blind_packets":
        "An exercise packet carries no expected answer, and no response may "
        "be generated from one.",
    "no_machine_curator":
        "A language model cannot serve as an independent scientific curator. "
        "There is no such role in CurationRole and none may be added without "
        "changing this protocol in the open.",
}


@dataclass(frozen=True)
class CaseAssignment:
    """One case and the single role it holds."""

    case_id: str
    role: CaseRole
    origin: str

    def __post_init__(self) -> None:
        if not str(self.case_id).strip():
            raise CaseSeparationError("case_id is required")
        if not isinstance(self.role, CaseRole):
            raise CaseSeparationError("role must be a CaseRole")
        if not str(self.origin).strip():
            raise CaseSeparationError(
                "case %s must record where it came from; a case of unknown "
                "origin cannot be shown to be independent" % self.case_id)

    def to_json(self) -> Dict[str, Any]:
        return {"case_id": self.case_id, "role": self.role.value,
                "origin": self.origin}


def check_case_separation(assignments: Sequence[CaseAssignment]) -> Tuple[str, ...]:
    """Every way a set of case assignments breaks separation.

    Returned rather than raised, because a caller repairing a case set wants
    the whole list. ``SAFETY-INV-009``: once a holdout informs development the
    metric measures memory, and no later analysis undoes it.
    """
    problems = []
    seen: Dict[str, CaseRole] = {}
    for item in assignments:
        previous = seen.get(item.case_id)
        if previous is not None and previous is not item.role:
            problems.append(
                "case %s holds both %s and %s; a case has exactly one role"
                % (item.case_id, previous.value, item.role.value))
        seen[item.case_id] = item.role
    return tuple(sorted(set(problems)))


@dataclass(frozen=True)
class ApprovalRecord:
    """Genuine expert approval of the protocol, or its documented absence.

    Every field is required together. Partial approval metadata is treated as
    no approval: a signature with no rationale, or a rationale with no name,
    describes an approval nobody can be held to.
    """

    protocol_version: str
    protocol_content_hash: str
    protocol_owner: str
    approver: ReviewSignature
    approval_evidence_reference: str
    effective_date: _dt.date
    review_due_date: _dt.date

    def __post_init__(self) -> None:
        for name in ("protocol_version", "protocol_content_hash",
                     "protocol_owner", "approval_evidence_reference"):
            if not str(getattr(self, name)).strip():
                raise ApprovalError(
                    "approval metadata is incomplete: %s is missing" % name)
        if not isinstance(self.approver, ReviewSignature):
            raise ApprovalError("approver must be a ReviewSignature")
        if self.approver.role not in SCIENTIFIC_APPROVAL_ROLES:
            raise ApprovalError(
                "%s cannot approve a scientific protocol; approval requires a "
                "scientific role" % self.approver.role.value)
        owner = str(self.protocol_owner).strip()
        if owner.lower() in ReviewSignature.PLACEHOLDER_NAMES:
            raise ApprovalError(
                "%r is a placeholder protocol owner, not a person" % owner)
        if owner.lower() == self.approver.person.strip().lower():
            raise ApprovalError(
                "the protocol owner and the scientific approver must be "
                "different people; owning a document is not reviewing it")
        if self.review_due_date <= self.effective_date:
            raise ApprovalError(
                "review_due_date must fall after effective_date; an approval "
                "with no expiry is an approval nobody revisits")

    def to_json(self) -> Dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "protocol_content_hash": self.protocol_content_hash,
            "protocol_owner": self.protocol_owner,
            "approver": self.approver.to_json(),
            "approval_evidence_reference": self.approval_evidence_reference,
            "effective_date": self.effective_date.isoformat(),
            "review_due_date": self.review_due_date.isoformat(),
        }


def _requirement(number: int, title: str, statement: str, implementation: str,
                 schema_field: Optional[str], validation_code: str,
                 test_reference: str, checklist_item: str) -> ProtocolRequirement:
    return ProtocolRequirement(
        requirement_id="CUR-PROT-%03d" % number, title=title,
        statement=statement, implementation=implementation,
        schema_field=schema_field, validation_code=validation_code,
        test_reference=test_reference, checklist_item=checklist_item)


#: Every obligation this protocol imposes, each mapped to the place it is
#: implemented, the schema field that carries it, the validator code that
#: reports its absence, the test that proves it, and the checklist line a
#: reviewer reads. A requirement missing any of those is a principle nobody
#: enforces, and the validator refuses the document.
PROTOCOL_REQUIREMENTS: Tuple[ProtocolRequirement, ...] = (
    _requirement(
        1, "Source facts and curator conclusions are separate objects",
        "A curation record never writes into an evidence record, and never "
        "copies a source's reported value into its own conclusion field. "
        "Source-reported values are held in SourceReportedValues for "
        "comparison only.",
        "pgx.curation.models.SourceReportedValues; "
        "pgx.curation.models.CurationRecordDraft",
        "source_reported",
        "CUR_SOURCE_CONCLUSION_MERGED",
        "tests/unit/curation/test_curation_records.py::"
        "TestSourceAndConclusionStaySeparate",
        "Does the record keep the source's own reported values apart from the "
        "curator's conclusion?"),
    _requirement(
        2, "Source significance does not become a conclusion",
        "significance=yes, a numeric score, a polarity or a recommendation "
        "flag reported by a source is never mapped directly to SUPPORTED, to "
        "confidence, to importance or to risk. The curator explains how the "
        "selected evidence supports the conclusion.",
        "pgx.curation.models.Rationale part 'significance_explanation'",
        "rationale.parts.significance_explanation",
        "CUR_SIGNIFICANCE_MAPPED_DIRECTLY",
        "tests/unit/curation/test_curation_records.py::"
        "TestSourceSignificanceIsNotAConclusion",
        "Does the rationale explain the conclusion rather than repeat the "
        "source's significance flag?"),
    _requirement(
        3, "A conclusion is recorded against an explicit question",
        "The unit of curation is a question: gene, drug, phenotype scope, "
        "effect dimension and population context. A pair-level conclusion is "
        "not applied to every annotation sharing that gene and drug.",
        "pgx.curation.models.CurationQuestion",
        "question",
        "CUR_GRANULARITY_UNDEFINED",
        "tests/unit/curation/test_curation_records.py::TestCurationGranularity",
        "Is the exact question stated, including phenotype scope and effect "
        "dimension?"),
    _requirement(
        4, "Every conclusion cites at least one evidence record",
        "A conclusion with no evidence has nothing to interpret and is "
        "refused at construction.",
        "pgx.curation.models.CurationRecordDraft.__post_init__",
        "evidence",
        "CUR_EVIDENCE_MISSING",
        "tests/unit/curation/test_curation_records.py::"
        "TestEvidenceIsRequired",
        "Does every conclusion cite real evidence record identifiers?"),
    _requirement(
        5, "Evidence inclusions and exclusions are both reasoned",
        "Each cited record carries a relationship and a written rationale. An "
        "exclusion additionally carries a controlled ExclusionReason.",
        "pgx.curation.models.EvidenceSelection",
        "evidence[].exclusion_reason",
        "CUR_EXCLUSION_UNREASONED",
        "tests/unit/curation/test_curation_records.py::"
        "TestExclusionsAreReasoned",
        "Is every exclusion given a controlled reason and a written "
        "rationale?"),
    _requirement(
        6, "Contradictory evidence is retained, never dropped",
        "Evidence that contradicts the conclusion stays in the record with "
        "relationship CONTRADICTS, and the conflict analysis must say "
        "something about it.",
        "pgx.curation.models.CurationRecordDraft."
        "_check_conclusion_consistency",
        "evidence[].relationship",
        "CUR_CONTRADICTION_HIDDEN",
        "tests/unit/curation/test_conflict_and_insufficiency.py::"
        "TestContradictoryEvidenceIsRetained",
        "Is contradicting evidence still present and assessed?"),
    _requirement(
        7, "No source has precedence",
        "There is no rule that CPIC, DPWG, a regulator label, a newer record "
        "or a higher source score wins. Which statement prevails is decided "
        "per disagreement by a named human.",
        "pgx.curation.models.ConflictAnalysis (no precedence field exists)",
        "conflict",
        "CUR_SOURCE_PRECEDENCE_ENCODED",
        "tests/unit/curation/test_conflict_and_insufficiency.py::"
        "TestNoSourcePrecedence",
        "Has any source been preferred by rule rather than by argument?"),
    _requirement(
        8, "Unresolved material conflict blocks rule construction",
        "A conclusion whose conflict is UNRESOLVED, ADJUDICATION_REQUIRED, or "
        "PRESENT and material is not rule-eligible, and cannot be SUPPORTED.",
        "pgx.curation.models.ConflictAnalysis.blocks_rule_construction",
        "conflict.blocks_rule_construction",
        "CUR_CONFLICT_NOT_BLOCKING",
        "tests/unit/curation/test_conflict_and_insufficiency.py::"
        "TestUnresolvedConflictBlocksRules",
        "Does an unresolved material conflict stop this conclusion reaching a "
        "rule?"),
    _requirement(
        9, "INSUFFICIENT is never reassurance",
        "An INSUFFICIENT conclusion states what is missing, what was "
        "reviewed, why nothing stronger holds and what remains unresolved. It "
        "may not read as low risk, no risk, no effect, safe, normal or "
        "negative evidence (SAFETY-INV-001).",
        "pgx.curation.models.InsufficiencyStatement; "
        "pgx.curation.models.find_reassuring_language",
        "insufficiency",
        "CUR_INSUFFICIENT_AS_REASSURANCE",
        "tests/unit/curation/test_conflict_and_insufficiency.py::"
        "TestInsufficientIsNotLowRisk",
        "Does the insufficient conclusion read as absence of knowledge rather "
        "than absence of risk?"),
    _requirement(
        10, "A CURATED conclusion requires a structured, non-placeholder "
            "rationale",
        "Eleven named parts, each substantive. 'Copied from legacy', "
        "'MANUAL_EFFECT_HINTS says so', 'the score is high', 'the AI selected "
        "it', 'clinically known' and blank text are refused, and a rationale "
        "that restates the conclusion is refused as circular.",
        "pgx.curation.models.Rationale",
        "rationale.parts",
        "CUR_RATIONALE_PLACEHOLDER",
        "tests/unit/curation/test_curation_records.py::TestRationaleContract",
        "Does the rationale explain the reasoning rather than restate the "
        "answer?"),
    _requirement(
        11, "Author and independent reviewer are different people",
        "The default protocol rule. One person checking their own conclusion "
        "is not an independent review, and CURATED requires both signatures.",
        "pgx.curation.models.Rationale.__post_init__",
        "rationale.reviewed_by",
        "CUR_ROLE_SEPARATION_MISSING",
        "tests/unit/curation/test_roles_and_cases.py::"
        "TestAuthorReviewerSeparation",
        "Are the author and the independent reviewer different named people?"),
    _requirement(
        12, "An engineering role cannot approve scientific meaning",
        "Only SCIENTIFIC_CURATOR, INDEPENDENT_SCIENTIFIC_REVIEWER and "
        "ADJUDICATOR may approve science. There is no machine curator role.",
        "pgx.curation.vocabulary.SCIENTIFIC_APPROVAL_ROLES; "
        "pgx.curation.protocol.ROLE_DEFINITIONS",
        "roles[].may_approve_science",
        "CUR_ENGINEERING_APPROVAL",
        "tests/unit/curation/test_roles_and_cases.py::"
        "TestOnlyScientificRolesApprove",
        "Did a scientific role, held by a named person, approve this?"),
    _requirement(
        13, "Adjudication preserves both original responses",
        "An adjudicator resolves a disagreement with written reasons and does "
        "not replace the two responses that disagreed.",
        "pgx.curation.exercises.AdjudicationTemplate",
        "adjudication.preserved_responses",
        "CUR_ADJUDICATION_REPLACES_RESPONSES",
        "tests/unit/curation/test_roles_and_cases.py::"
        "TestAdjudicationPreservesResponses",
        "Are both original responses still readable after adjudication?"),
    _requirement(
        14, "One case holds exactly one role",
        "DEVELOPMENT, INTERNAL_HOLDOUT and EXPERT_HOLDOUT are disjoint. "
        "Legacy hints and demo profiles are development or training only. A "
        "case derived from the current evidence set is not external "
        "validation (SAFETY-INV-009).",
        "pgx.curation.protocol.check_case_separation; CASE_ROLE_RULES",
        "cases[].role",
        "CUR_CASE_ROLE_OVERLAP",
        "tests/unit/curation/test_roles_and_cases.py::TestCaseSeparation",
        "Does any case appear under two roles?"),
    _requirement(
        15, "Legacy manual hints stay unreviewed until a human reviews them",
        "All 1,559 WP-08 proposals are accounted for and start at "
        "NOT_REVIEWED. Nothing in this package may set any other state, and "
        "no legacy project value may enter a completed conclusion.",
        "pgx.curation.legacy_review.build_review_inventory",
        "proposals[].review_state",
        "CUR_LEGACY_AUTO_REVIEWED",
        "tests/unit/curation/test_legacy_review.py::"
        "TestLegacyHintsStayUnreviewed",
        "Has any legacy hint been accepted or rejected without a human?"),
    _requirement(
        16, "Legacy hints are blinded during initial evidence review",
        "An exercise case does not carry the legacy conclusion. It is "
        "revealed only afterwards, for migration comparison.",
        "pgx.curation.exercises.build_exercise_packet",
        "cases[].legacy_hint_blinded",
        "CUR_LEGACY_HINT_NOT_BLINDED",
        "tests/unit/curation/test_exercise.py::TestLegacyHintsAreBlinded",
        "Could a curator see the legacy answer before forming their own?"),
    _requirement(
        17, "The inter-curator comparison does not adjudicate",
        "It reports field-level agreement and disagreement between two "
        "independently completed responses. It does not decide who is right, "
        "merge answers, generate consensus, or treat agreement as validity.",
        "pgx.curation.exercises.compare_responses",
        "comparison.fields",
        "CUR_COMPARISON_ADJUDICATES",
        "tests/unit/curation/test_exercise.py::TestComparisonDoesNotAdjudicate",
        "Does the comparison state differences without choosing a winner?"),
    _requirement(
        18, "A comparison requires two genuinely completed responses",
        "A blank template is not a response. Two responses from one person, "
        "or a response generated from an expected answer, are not "
        "independent.",
        "pgx.curation.exercises.CuratorResponse.is_complete; "
        "pgx.curation.exercises.compare_responses",
        "responses[].completed",
        "CUR_COMPARISON_INCOMPLETE_INPUT",
        "tests/unit/curation/test_exercise.py::"
        "TestComparisonRequiresCompletedResponses",
        "Were both responses completed independently by named people?"),
    _requirement(
        19, "No numeric risk, confidence or safety score exists",
        "No vocabulary carries a number and no curation field may hold one. "
        "Arithmetic over scientific judgement produces a result nobody "
        "reviewed.",
        "pgx.curation.models.PROHIBITED_CURATION_FIELDS",
        "-",
        "CUR_NUMERIC_SCORE_PRESENT",
        "tests/unit/curation/test_curation_records.py::"
        "TestNoNumericJudgement",
        "Does any field score, rank or weight a scientific judgement?"),
    _requirement(
        20, "No executable rule or treatment field exists",
        "A curation record carries no rule condition, matcher, dose, "
        "recommendation, contraindication or alternative drug. Those belong "
        "to WP-11 and WP-14 and have their own approval.",
        "pgx.curation.models.PROHIBITED_CURATION_FIELDS",
        "-",
        "CUR_EXECUTABLE_FIELD_PRESENT",
        "tests/unit/curation/test_curation_records.py::"
        "TestNoExecutableOrPrescriptiveFields",
        "Could anything in this record be executed or read as advice?"),
    _requirement(
        21, "RAPID and ULTRARAPID stay distinct",
        "The existing Phenotype enum is reused unchanged. No alias, synonym "
        "or grouping may join them (SAFETY-INV-004).",
        "pgx.domain.enums.Phenotype; "
        "pgx.curation.models.CurationQuestion.phenotype_scope",
        "question.phenotype_scope",
        "CUR_PHENOTYPE_COLLAPSED",
        "tests/unit/curation/test_curation_records.py::"
        "TestRapidAndUltrarapidStayDistinct",
        "Does any scope treat RAPID and ULTRARAPID as one?"),
    _requirement(
        22, "Every controlled field has an owner and a null meaning",
        "The field dictionary states, for every field: owner, type, "
        "requiredness, allowed values, what null means, validation, "
        "provenance requirement, whether human judgement is required, whether "
        "it may enter a future rule, and prohibited interpretations.",
        "pgx.curation.fields.FIELD_DICTIONARY",
        "fields[]",
        "CUR_FIELD_DEFINITION_MISSING",
        "tests/unit/curation/test_protocol_structure.py::"
        "TestFieldDictionaryIsComplete",
        "Does every field say who owns it and what its absence means?"),
    _requirement(
        23, "Protocol approval requires genuine named metadata",
        "APPROVED requires version, content hash, named owner, a different "
        "named scientific approver, role, timestamp, rationale, evidence "
        "reference, effective date and review date. Placeholders are treated "
        "as absence.",
        "pgx.curation.protocol.ApprovalRecord",
        "approval",
        "CUR_APPROVAL_METADATA_INCOMPLETE",
        "tests/unit/curation/test_protocol_structure.py::"
        "TestApprovalMetadataIsGenuine",
        "Is there a real named scientist behind this approval?"),
    _requirement(
        24, "Technical completeness and expert approval are reported apart",
        "A structurally complete protocol that nobody approved reports "
        "completeness PASS and approval BLOCKED. One boolean would let the "
        "first stand in for the second.",
        "pgx.curation.validation.validate_protocol",
        "report.expert_approval",
        "CUR_APPROVAL_ABSENT",
        "tests/unit/curation/test_protocol_structure.py::"
        "TestCompletenessAndApprovalAreSeparate",
        "Is the protocol both structurally complete and actually approved?"),
    _requirement(
        25, "Exercise cases reference real, traceable evidence",
        "Every case names evidence record identifiers that exist in the "
        "sealed build, and the packet is regenerated byte-identically from "
        "the same build.",
        "pgx.curation.exercises.build_exercise_packet",
        "cases[].evidence_record_uuids",
        "CUR_EXERCISE_EVIDENCE_MISSING",
        "tests/unit/curation/test_exercise.py::"
        "TestExerciseReferencesRealEvidence",
        "Do the exercise cases point at evidence that actually exists?"),
)


@dataclass(frozen=True)
class ProtocolDocument:
    """The machine-readable protocol.

    ``content_hash`` covers the protocol's substance and deliberately excludes
    ``generated_at``: an operational timestamp that entered the hash would make
    two identical protocols look different and make the approval hash
    unverifiable a day later.
    """

    protocol_version: str
    status: ProtocolStatus
    requirements: Tuple[ProtocolRequirement, ...]
    roles: Tuple[RoleDefinition, ...]
    case_rules: Mapping[str, str]
    vocabularies: Mapping[str, Tuple[str, ...]]
    field_dictionary_version: str
    approval: Optional[ApprovalRecord] = None
    generated_at: Optional[_dt.datetime] = None
    supersedes: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ProtocolStatus):
            raise ProtocolError("status must be a ProtocolStatus",
                                code="PROT_STATUS_INVALID")
        ids = [item.requirement_id for item in self.requirements]
        duplicates = sorted({value for value in ids if ids.count(value) > 1})
        if duplicates:
            raise ProtocolError(
                "requirement ids must be unique; repeated: %s"
                % ", ".join(duplicates), code="PROT_REQUIREMENT_ID_DUPLICATE")
        if not self.requirements:
            raise ProtocolError("a protocol with no requirements imposes "
                                "nothing", code="PROT_NO_REQUIREMENTS")
        roles = [item.role for item in self.roles]
        if len(set(roles)) != len(roles):
            raise ProtocolError("a role is defined twice",
                                code="PROT_ROLE_DUPLICATE")
        if self.generated_at is not None:
            object.__setattr__(self, "generated_at",
                               ensure_utc(self.generated_at, "generated_at"))

        # The one place where saying APPROVED is checked against being
        # approved. Everything else in this class is structure; this is the
        # claim that matters.
        if self.status is ProtocolStatus.APPROVED and self.approval is None:
            raise ApprovalError(
                "a protocol cannot be APPROVED with no approval record. "
                "Approval names a scientist who read it.")
        if self.approval is not None:
            if self.approval.protocol_version != self.protocol_version:
                raise ApprovalError(
                    "the approval names protocol %s but this document is %s"
                    % (self.approval.protocol_version, self.protocol_version))
            if self.approval.protocol_content_hash != self.content_hash():
                raise ApprovalError(
                    "the approval's content hash does not match this "
                    "document; an approval applies to what was read, not to "
                    "whatever the document later became")

    def content_identity(self) -> Dict[str, Any]:
        """What two protocols must share to be the same protocol.

        Excludes ``generated_at`` and ``approval``: the first is operational,
        and the second is a statement *about* this content which therefore
        cannot be part of it.
        """
        return {
            "protocol_version": self.protocol_version,
            "vocabulary_version": VOCABULARY_VERSION,
            "vocabulary_status": VOCABULARY_STATUS,
            "field_dictionary_version": self.field_dictionary_version,
            "requirements": [item.to_json() for item in self.requirements],
            "roles": [item.to_json() for item in self.roles],
            "case_rules": dict(sorted(self.case_rules.items())),
            "vocabularies": {name: list(values) for name, values
                             in sorted(self.vocabularies.items())},
            "supersedes": self.supersedes,
        }

    def content_hash(self) -> str:
        return sha256_digest(self.content_identity())

    @property
    def is_expert_approved(self) -> bool:
        return bool(self.status is ProtocolStatus.APPROVED
                    and self.approval is not None)

    def to_json(self) -> Dict[str, Any]:
        payload = self.content_identity()
        payload["status"] = self.status.value
        payload["content_hash"] = self.content_hash()
        payload["approval"] = (self.approval.to_json()
                               if self.approval else None)
        payload["expert_approved"] = self.is_expert_approved
        payload["generated_at"] = (
            self.generated_at.isoformat().replace("+00:00", "Z")
            if self.generated_at else None)
        payload["note"] = (
            "This protocol is not scientifically approved. Every vocabulary "
            "and definition in it is DRAFT / AWAITING EXPERT REVIEW until a "
            "named scientist records an approval against this content hash.")
        return payload


def build_protocol_document(
    status: ProtocolStatus = ProtocolStatus.AWAITING_EXPERT_REVIEW,
    approval: Optional[ApprovalRecord] = None,
    field_dictionary_version: str = "pgx-curation-field-dictionary/1",
) -> ProtocolDocument:
    """Assemble the protocol from the requirement and role catalogues.

    The default status is ``AWAITING_EXPERT_REVIEW`` rather than ``DRAFT``,
    because the document is finished and waiting on a person, and rather than
    ``APPROVED`` because no person has read it.
    """
    return ProtocolDocument(
        protocol_version=CURATION_PROTOCOL_VERSION,
        status=status,
        requirements=PROTOCOL_REQUIREMENTS,
        roles=ROLE_DEFINITIONS,
        case_rules=CASE_ROLE_RULES,
        vocabularies=vocabulary_registry(),
        field_dictionary_version=field_dictionary_version,
        approval=approval)
