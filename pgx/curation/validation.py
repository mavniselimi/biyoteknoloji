# -*- coding: utf-8 -*-
"""Protocol completeness validation (WP-09).

Pure and deterministic: given the same protocol, dictionary, inventory and
packet, this produces the same report, and it reads nothing but what it is
handed plus files whose paths it is given.

**Two verdicts, never one.** ``technical_completeness`` says whether the
protocol is structurally whole. ``expert_approval`` says whether a named
scientist has signed it. A structurally perfect protocol nobody approved is
``PASS`` and ``BLOCKED``, and collapsing those into a single boolean would let
completeness stand in for approval - which is the failure this whole work
package exists to prevent.

Issue codes are stable strings. A code is what a document, a test and a
checklist item cite when they mean the same problem, so renaming one is a
breaking change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.curation.exercises import (EXERCISE_STATUS_AWAITING, ExercisePacket)
from pgx.curation.fields import FIELD_DICTIONARY, FieldDefinition
from pgx.curation.legacy_review import LegacyReviewInventory
from pgx.curation.models import (PROHIBITED_CURATION_FIELDS, RATIONALE_PARTS)
from pgx.curation.protocol import (PROTOCOL_REQUIREMENTS, CaseAssignment,
                                   ProtocolDocument, check_case_separation)
from pgx.curation.vocabulary import (LegacyReviewState, ProtocolStatus,
                                     vocabulary_registry)
from pgx.domain.enums import Phenotype

__all__ = [
    "ISSUE_CODES",
    "VALIDATION_VERSION",
    "ValidationIssue",
    "ValidationReport",
    "validate_protocol",
]

VALIDATION_VERSION = "pgx-curation-validation/1"

#: Every issue this validator can report, and what it means. Declared as data
#: so a test can assert that every requirement's ``validation_code`` is one of
#: these, and that no code exists without a requirement behind it.
ISSUE_CODES: Mapping[str, str] = {
    "CUR_APPROVAL_ABSENT":
        "No genuine expert approval exists for this protocol.",
    "CUR_APPROVAL_METADATA_INCOMPLETE":
        "Approval metadata is present but incomplete or placeholder.",
    "CUR_APPROVAL_STATUS_MISMATCH":
        "The declared status and the approval record disagree.",
    "CUR_ADJUDICATION_REPLACES_RESPONSES":
        "An adjudication does not preserve both original responses.",
    "CUR_CASE_ROLE_OVERLAP":
        "One case holds more than one role.",
    "CUR_COMPARISON_ADJUDICATES":
        "The comparison output decides an outcome rather than reporting one.",
    "CUR_COMPARISON_INCOMPLETE_INPUT":
        "A comparison was attempted over responses that are not complete.",
    "CUR_CONFLICT_NOT_BLOCKING":
        "An unresolved material conflict does not block rule construction.",
    "CUR_CONTRADICTION_HIDDEN":
        "Contradicting evidence is absent from a conclusion that has some.",
    "CUR_ENGINEERING_APPROVAL":
        "A non-scientific role is permitted to approve scientific meaning.",
    "CUR_EVIDENCE_MISSING":
        "A conclusion cites no evidence.",
    "CUR_EXCLUSION_UNREASONED":
        "Evidence is excluded without a controlled reason.",
    "CUR_EXECUTABLE_FIELD_PRESENT":
        "A rule condition, dose or treatment field appears in the protocol.",
    "CUR_EXERCISE_EVIDENCE_MISSING":
        "An exercise case references evidence that is not in the build.",
    "CUR_EXERCISE_NOT_PENDING":
        "The real exercise claims completion without two named curators.",
    "CUR_FIELD_DEFINITION_MISSING":
        "A field has no definition, or a definition is incomplete.",
    "CUR_FIELD_NULL_SEMANTICS_MISSING":
        "A field definition does not say what its absence means.",
    "CUR_FIELD_OWNER_INVALID":
        "A field owner is not SOURCE, CURATOR or SYSTEM.",
    "CUR_GRANULARITY_UNDEFINED":
        "The unit of curation is not defined.",
    "CUR_INSUFFICIENT_AS_REASSURANCE":
        "An insufficient conclusion is expressed as low or no risk.",
    "CUR_LEGACY_AUTO_REVIEWED":
        "A legacy proposal was reviewed without a named human.",
    "CUR_LEGACY_HINT_NOT_BLINDED":
        "An exercise case reveals the legacy conclusion.",
    "CUR_LEGACY_PROPOSAL_MISSING":
        "A legacy proposal is not accounted for in the inventory.",
    "CUR_NUMERIC_SCORE_PRESENT":
        "A numeric risk, confidence or safety score exists.",
    "CUR_PHENOTYPE_COLLAPSED":
        "RAPID and ULTRARAPID are treated as one.",
    "CUR_RATIONALE_PLACEHOLDER":
        "A rationale is absent, placeholder or circular.",
    "CUR_REQUIREMENT_ID_DUPLICATE":
        "Two requirements share an identifier.",
    "CUR_REQUIREMENT_UNMAPPED":
        "A requirement names no implementation, test or checklist item.",
    "CUR_ROLE_SEPARATION_MISSING":
        "Author and independent reviewer separation is not defined.",
    "CUR_SIGNIFICANCE_MAPPED_DIRECTLY":
        "A source's significance is mapped straight to a conclusion.",
    "CUR_SOURCE_CONCLUSION_MERGED":
        "Source facts and curator conclusions share a field.",
    "CUR_SOURCE_PRECEDENCE_ENCODED":
        "A source is preferred by rule rather than by argument.",
    "CUR_VOCABULARY_MISMATCH":
        "A published vocabulary disagrees with the code.",
    "CUR_ARTIFACT_MISSING":
        "A required protocol artifact is absent.",
}


@dataclass(frozen=True)
class ValidationIssue:
    """One problem, with the code a document and a test can both cite."""

    code: str
    severity: str
    subject: str
    detail: str

    def __post_init__(self) -> None:
        if self.code not in ISSUE_CODES:
            raise KeyError(
                "%r is not a declared issue code; an undeclared code cannot be "
                "cited by a document or a test" % self.code)
        if self.severity not in ("BLOCKING", "ADVISORY", "INFORMATIONAL"):
            raise ValueError("severity must be BLOCKING, ADVISORY or "
                             "INFORMATIONAL")

    @property
    def sort_key(self) -> Tuple[str, str, str]:
        return (self.code, self.subject, self.detail)

    def to_json(self) -> Dict[str, Any]:
        return {"code": self.code, "severity": self.severity,
                "subject": self.subject, "detail": self.detail,
                "meaning": ISSUE_CODES[self.code]}


@dataclass(frozen=True)
class ValidationReport:
    """The two verdicts, and everything behind them."""

    issues: Tuple[ValidationIssue, ...]
    protocol_version: str
    protocol_content_hash: str
    protocol_status: str
    checks_run: Tuple[str, ...]
    counts: Mapping[str, Any]

    @property
    def blocking_issues(self) -> Tuple[ValidationIssue, ...]:
        return tuple(item for item in self.issues
                     if item.severity == "BLOCKING")

    @property
    def technical_completeness(self) -> str:
        """Whether the protocol is structurally whole.

        Approval absence is deliberately excluded: it is reported by the other
        verdict, and letting it fail this one would make a complete protocol
        look broken instead of unapproved.
        """
        structural = [item for item in self.blocking_issues
                      if item.code != "CUR_APPROVAL_ABSENT"]
        return "PASS" if not structural else "FAIL"

    @property
    def expert_approval(self) -> str:
        approved = not any(item.code in ("CUR_APPROVAL_ABSENT",
                                         "CUR_APPROVAL_METADATA_INCOMPLETE",
                                         "CUR_APPROVAL_STATUS_MISMATCH")
                           for item in self.issues)
        return "APPROVED" if approved else "BLOCKED"

    def to_json(self) -> Dict[str, Any]:
        return {
            "validation_version": VALIDATION_VERSION,
            "protocol_version": self.protocol_version,
            "protocol_content_hash": self.protocol_content_hash,
            "protocol_status": self.protocol_status,
            "technical_completeness": self.technical_completeness,
            "expert_approval": self.expert_approval,
            "checks_run": list(self.checks_run),
            "counts": dict(self.counts),
            "issues": [item.to_json() for item in self.issues],
            "note": (
                "Technical completeness and expert approval are separate "
                "verdicts. A protocol may be structurally complete and still "
                "unapproved; that is not a defect to be fixed in code, it is "
                "a person who has not yet read it."),
        }


#: Every check this validator runs, named so the report can say what was
#: actually examined rather than only what failed.
CHECKS = (
    "required_artifacts_exist",
    "requirement_ids_unique",
    "requirements_fully_mapped",
    "vocabularies_match_code",
    "field_definitions_complete",
    "field_null_semantics_present",
    "evidence_and_rationale_required",
    "conflict_behaviour_explicit",
    "insufficiency_behaviour_explicit",
    "role_separation_defined",
    "case_separation_defined",
    "approval_metadata_matches_status",
    "exercise_references_real_evidence",
    "exercise_hints_blinded",
    "exercise_awaiting_humans",
    "legacy_proposals_accounted_for",
    "legacy_hints_unreviewed",
    "no_executable_rule_condition",
    "no_numeric_risk_score",
    "phenotype_distinctions_preserved",
)


def validate_protocol(
    document: ProtocolDocument,
    fields: Sequence[FieldDefinition] = FIELD_DICTIONARY,
    inventory: Optional[LegacyReviewInventory] = None,
    packet: Optional[ExercisePacket] = None,
    evidence_record_uuids: Optional[Sequence[str]] = None,
    expected_proposal_count: Optional[int] = None,
    artifact_paths: Sequence[str] = (),
) -> ValidationReport:
    """Check the protocol and its artifacts, returning a deterministic report.

    Every argument beyond ``document`` is optional, and an absent one produces
    an informational issue rather than a silent pass: "the inventory was not
    checked" and "the inventory is correct" are different statements, and a
    report that could not tell them apart would be useless for exactly the
    thing it is for.
    """
    issues: List[ValidationIssue] = []

    def add(code, severity, subject, detail):
        issues.append(ValidationIssue(code=code, severity=severity,
                                      subject=subject, detail=detail))

    # -- artifacts ------------------------------------------------------
    for path in artifact_paths:
        if not os.path.exists(path):
            add("CUR_ARTIFACT_MISSING", "BLOCKING", path,
                "a required protocol artifact is absent from this checkout")

    # -- requirements ---------------------------------------------------
    ids = [item.requirement_id for item in document.requirements]
    for duplicate in sorted({value for value in ids if ids.count(value) > 1}):
        add("CUR_REQUIREMENT_ID_DUPLICATE", "BLOCKING", duplicate,
            "two requirements share this identifier")
    for requirement in document.requirements:
        unmapped = [name for name in ("implementation", "validation_code",
                                      "test_reference", "checklist_item")
                    if not str(getattr(requirement, name)).strip()]
        if unmapped:
            add("CUR_REQUIREMENT_UNMAPPED", "BLOCKING",
                requirement.requirement_id,
                "names no %s, so the principle is stated but not enforced"
                % ", ".join(unmapped))
        if requirement.validation_code not in ISSUE_CODES:
            add("CUR_REQUIREMENT_UNMAPPED", "BLOCKING",
                requirement.requirement_id,
                "cites validation code %r, which this validator cannot emit"
                % requirement.validation_code)

    # -- vocabularies ---------------------------------------------------
    live = vocabulary_registry()
    for name, members in sorted(live.items()):
        published = tuple(document.vocabularies.get(name) or ())
        if published != members:
            add("CUR_VOCABULARY_MISMATCH", "BLOCKING", name,
                "published members %s differ from the code's %s"
                % (list(published), list(members)))

    # -- field dictionary -----------------------------------------------
    defined = {item.name for item in fields}
    for item in fields:
        if not str(item.null_meaning).strip():
            add("CUR_FIELD_NULL_SEMANTICS_MISSING", "BLOCKING", item.name,
                "does not say what its absence means")
        if str(item.owner) not in ("SOURCE", "CURATOR", "SYSTEM"):
            add("CUR_FIELD_OWNER_INVALID", "BLOCKING", item.name,
                "owner %r is not SOURCE, CURATOR or SYSTEM" % item.owner)
        if not item.prohibited_interpretations:
            add("CUR_FIELD_DEFINITION_MISSING", "BLOCKING", item.name,
                "states no prohibited interpretation")

    # The fields the protocol cannot function without.
    for required_field in ("evidence", "rationale", "conflict",
                           "insufficiency", "conclusion_state",
                           "source_reported", "question"):
        if required_field not in defined:
            add("CUR_FIELD_DEFINITION_MISSING", "BLOCKING", required_field,
                "is used by the protocol and has no definition")

    # -- separation of source fact and curator conclusion ---------------
    source_owned = {item.name for item in fields
                    if str(item.owner) == "SOURCE"}
    curator_owned = {item.name for item in fields
                     if str(item.owner) == "CURATOR"}
    shared = sorted(source_owned & curator_owned)
    for name in shared:
        add("CUR_SOURCE_CONCLUSION_MERGED", "BLOCKING", name,
            "is owned by both the source and the curator, so a source's word "
            "could become this project's claim without anyone deciding to")
    if "source_reported" in defined:
        definition = next(item for item in fields
                          if item.name == "source_reported")
        joined = " ".join(definition.prohibited_interpretations).lower()
        if "significance" not in joined:
            add("CUR_SIGNIFICANCE_MAPPED_DIRECTLY", "BLOCKING",
                "source_reported",
                "does not prohibit reading the source's significance flag as "
                "the curator's conclusion")

    # -- evidence, rationale, conflict, insufficiency --------------------
    if len(RATIONALE_PARTS) < 8:
        add("CUR_RATIONALE_PLACEHOLDER", "BLOCKING", "Rationale",
            "the structured rationale has too few parts to be an argument")
    requirement_codes = {item.validation_code for item in document.requirements}
    for code, subject in (("CUR_EVIDENCE_MISSING", "evidence requirement"),
                          ("CUR_RATIONALE_PLACEHOLDER", "rationale requirement"),
                          ("CUR_EXCLUSION_UNREASONED", "exclusion requirement"),
                          ("CUR_CONFLICT_NOT_BLOCKING", "conflict behaviour"),
                          ("CUR_INSUFFICIENT_AS_REASSURANCE",
                           "insufficiency behaviour"),
                          ("CUR_SOURCE_PRECEDENCE_ENCODED",
                           "source precedence prohibition"),
                          ("CUR_ROLE_SEPARATION_MISSING", "role separation"),
                          ("CUR_CASE_ROLE_OVERLAP", "case separation"),
                          ("CUR_PHENOTYPE_COLLAPSED", "phenotype distinction"),
                          ("CUR_NUMERIC_SCORE_PRESENT", "numeric score "
                                                        "prohibition"),
                          ("CUR_EXECUTABLE_FIELD_PRESENT", "executable field "
                                                           "prohibition")):
        if code not in requirement_codes:
            add("CUR_REQUIREMENT_UNMAPPED", "BLOCKING", subject,
                "no requirement in this protocol carries code %s, so the "
                "behaviour is undefined" % code)

    # -- roles ----------------------------------------------------------
    approvers = [item for item in document.roles if item.may_approve_science]
    if not approvers:
        add("CUR_ROLE_SEPARATION_MISSING", "BLOCKING", "roles",
            "no role may approve scientific meaning, so nothing can ever be "
            "approved")
    for item in document.roles:
        if item.may_author_conclusion and item.may_review_conclusion:
            add("CUR_ROLE_SEPARATION_MISSING", "BLOCKING", item.role.value,
                "may both author and independently review, which is not "
                "independence")
        if item.role.value == "ENGINEERING_OBSERVER" and item.may_approve_science:
            add("CUR_ENGINEERING_APPROVAL", "BLOCKING", item.role.value,
                "an engineering role may not approve scientific meaning")
    if not document.case_rules:
        add("CUR_CASE_ROLE_OVERLAP", "BLOCKING", "case_rules",
            "no case separation rules are defined")

    # -- prohibited content in the protocol itself ----------------------
    numeric_names = ("confidence", "confidence_score", "risk_level",
                     "safety_score", "severity_score", "quality_score")
    executable_names = ("condition", "rule_condition", "dose",
                        "recommendation", "contraindication")
    for item in fields:
        if item.name in numeric_names:
            add("CUR_NUMERIC_SCORE_PRESENT", "BLOCKING", item.name,
                "a numeric judgement field is defined in the curation "
                "protocol")
        if item.name in executable_names:
            add("CUR_EXECUTABLE_FIELD_PRESENT", "BLOCKING", item.name,
                "an executable or prescriptive field is defined in the "
                "curation protocol")
    for name in numeric_names + executable_names:
        if name not in PROHIBITED_CURATION_FIELDS:
            add("CUR_NUMERIC_SCORE_PRESENT", "BLOCKING", name,
                "is not on the prohibited-field list, so a record could "
                "carry it")

    # -- phenotype -------------------------------------------------------
    members = {item.name for item in Phenotype}
    if not {"RAPID", "ULTRARAPID"} <= members:
        add("CUR_PHENOTYPE_COLLAPSED", "BLOCKING", "Phenotype",
            "RAPID and ULTRARAPID are not both present as distinct members")

    # -- approval --------------------------------------------------------
    if document.approval is None:
        add("CUR_APPROVAL_ABSENT",
            "BLOCKING" if document.status is ProtocolStatus.APPROVED
            else "INFORMATIONAL",
            document.protocol_version,
            "no named scientific expert has approved this protocol; it "
            "remains %s" % document.status.value)
    else:
        if document.status is not ProtocolStatus.APPROVED:
            add("CUR_APPROVAL_STATUS_MISMATCH", "BLOCKING",
                document.protocol_version,
                "an approval record exists while the status is %s"
                % document.status.value)
        if document.approval.protocol_content_hash != document.content_hash():
            add("CUR_APPROVAL_METADATA_INCOMPLETE", "BLOCKING",
                document.protocol_version,
                "the approval's content hash does not match this document")

    # -- legacy inventory ------------------------------------------------
    if inventory is None:
        add("CUR_LEGACY_PROPOSAL_MISSING", "INFORMATIONAL", "inventory",
            "no legacy review inventory was supplied, so proposal accounting "
            "was not checked")
    else:
        counts = inventory.counts()
        if expected_proposal_count is not None and \
                counts["proposal_count"] != expected_proposal_count:
            add("CUR_LEGACY_PROPOSAL_MISSING", "BLOCKING", "inventory",
                "%d proposals accounted for, expected %d"
                % (counts["proposal_count"], expected_proposal_count))
        for entry in inventory.entries:
            if entry.review_state not in (LegacyReviewState.NOT_REVIEWED,
                                          LegacyReviewState.SELECTED_FOR_EXERCISE):
                if not (entry.reviewed_by or "").strip():
                    add("CUR_LEGACY_AUTO_REVIEWED", "BLOCKING",
                        entry.proposal_id,
                        "is %s with no named reviewer"
                        % entry.review_state.value)

    # -- exercise --------------------------------------------------------
    if packet is None:
        add("CUR_EXERCISE_EVIDENCE_MISSING", "INFORMATIONAL", "exercise",
            "no exercise packet was supplied, so its evidence references were "
            "not checked")
    else:
        if packet.status != EXERCISE_STATUS_AWAITING:
            add("CUR_EXERCISE_NOT_PENDING", "BLOCKING", packet.exercise_id,
                "claims status %r; the real exercise stays %s until two named "
                "curators complete it"
                % (packet.status, EXERCISE_STATUS_AWAITING))
        for case in packet.cases:
            if not case.legacy_hint_blinded:
                add("CUR_LEGACY_HINT_NOT_BLINDED", "BLOCKING", case.case_id,
                    "reveals the legacy conclusion before the curator answers")
            if evidence_record_uuids is not None:
                known = frozenset(evidence_record_uuids)
                for uuid_value in case.evidence_record_uuids:
                    if uuid_value not in known:
                        add("CUR_EXERCISE_EVIDENCE_MISSING", "BLOCKING",
                            case.case_id,
                            "references evidence %s, which is not in the "
                            "build" % uuid_value)
        assignments_problems = check_case_separation([
            CaseAssignment(case_id=case.case_id, role=case.case_role,
                           origin="exercise packet %s" % packet.exercise_id)
            for case in packet.cases])
        for problem in assignments_problems:
            add("CUR_CASE_ROLE_OVERLAP", "BLOCKING", packet.exercise_id,
                problem)

    ordered = tuple(sorted(issues, key=lambda item: item.sort_key))
    return ValidationReport(
        issues=ordered,
        protocol_version=document.protocol_version,
        protocol_content_hash=document.content_hash(),
        protocol_status=document.status.value,
        checks_run=CHECKS,
        counts={
            "requirements": len(document.requirements),
            "roles": len(document.roles),
            "fields": len(fields),
            "vocabularies": len(document.vocabularies),
            "issues": len(ordered),
            "blocking": sum(1 for item in ordered
                            if item.severity == "BLOCKING"),
            "advisory": sum(1 for item in ordered
                            if item.severity == "ADVISORY"),
            "informational": sum(1 for item in ordered
                                 if item.severity == "INFORMATIONAL"),
            "legacy_proposals": (inventory.counts()["proposal_count"]
                                 if inventory else None),
            "exercise_cases": len(packet.cases) if packet else None,
        })
