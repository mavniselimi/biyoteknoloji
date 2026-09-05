# -*- coding: utf-8 -*-
"""The curation field dictionary (WP-09).

For every field a curation record carries, this states who owns it, what its
absence means, and what it may never be read as. The last two matter most.

**Null is not a value.** A missing origin source and an origin of "none" are
different facts, and a dictionary that did not say which is which would let a
later stage treat absence as a finding. Every entry names what null means.

**Prohibited interpretations are written down.** A field is misused most often
by being read as something adjacent - a source's significance flag read as the
curator's conclusion, an insufficiency read as a low risk. Naming the misuse is
the only way a reviewer can check for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from pgx.curation.errors import ProtocolError
from pgx.curation.vocabulary import (Applicability, ConclusionState,
                                     ConflictState, EffectDimension,
                                     EvidenceRelationship, ExclusionReason,
                                     InterpretationStatus, vocabulary_members)
from pgx.domain.enums import Phenotype

__all__ = [
    "FIELD_DICTIONARY",
    "FIELD_DICTIONARY_VERSION",
    "FieldDefinition",
    "FieldOwner",
    "field_definition",
    "field_dictionary_json",
]

FIELD_DICTIONARY_VERSION = "pgx-curation-field-dictionary/1"


class FieldOwner(str):
    """Who is responsible for a field's content.

    A plain string subclass rather than an enum, so the three permitted values
    read as what they are at every use site.
    """


SOURCE = FieldOwner("SOURCE")
CURATOR = FieldOwner("CURATOR")
SYSTEM = FieldOwner("SYSTEM")


@dataclass(frozen=True)
class FieldDefinition:
    """One field, completely described.

    Every attribute is required. A field with no stated null meaning, or no
    stated prohibited interpretation, is a field a later stage will read
    however it finds convenient.
    """

    name: str
    owner: FieldOwner
    type_name: str
    required: bool
    allowed_values: Optional[Tuple[str, ...]]
    null_meaning: str
    validation: str
    provenance_requirement: str
    human_judgement_required: bool
    may_enter_rule: bool
    prohibited_interpretations: Tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("name", "type_name", "null_meaning", "validation",
                     "provenance_requirement"):
            if not str(getattr(self, name)).strip():
                raise ProtocolError(
                    "field %r: %s is required" % (self.name, name),
                    code="CUR_FIELD_DEFINITION_MISSING")
        if self.owner not in ("SOURCE", "CURATOR", "SYSTEM"):
            raise ProtocolError(
                "field %r: owner must be SOURCE, CURATOR or SYSTEM"
                % self.name, code="CUR_FIELD_OWNER_INVALID")
        if not self.prohibited_interpretations:
            raise ProtocolError(
                "field %r states no prohibited interpretation; every field "
                "here is misreadable in some specific way and naming it is "
                "what lets a reviewer check" % self.name,
                code="CUR_FIELD_DEFINITION_MISSING")

    def to_json(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "owner": str(self.owner),
            "type": self.type_name,
            "required": self.required,
            "allowed_values": (list(self.allowed_values)
                               if self.allowed_values else None),
            "null_meaning": self.null_meaning,
            "validation": self.validation,
            "provenance_requirement": self.provenance_requirement,
            "human_judgement_required": self.human_judgement_required,
            "may_enter_rule": self.may_enter_rule,
            "prohibited_interpretations": list(self.prohibited_interpretations),
        }


def _field(name, owner, type_name, required, allowed_values, null_meaning,
           validation, provenance_requirement, human_judgement_required,
           may_enter_rule, prohibited_interpretations):
    return FieldDefinition(
        name=name, owner=owner, type_name=type_name, required=required,
        allowed_values=allowed_values, null_meaning=null_meaning,
        validation=validation, provenance_requirement=provenance_requirement,
        human_judgement_required=human_judgement_required,
        may_enter_rule=may_enter_rule,
        prohibited_interpretations=tuple(prohibited_interpretations))


FIELD_DICTIONARY: Tuple[FieldDefinition, ...] = (
    _field("record_id", SYSTEM, "string", True, None,
           "Never null. A record without an identifier cannot be cited.",
           "Non-empty; unique within a protocol version.",
           "Assigned by the tooling, not by a curator.",
           False, False,
           ["Not a scientific identifier and not stable across protocol "
            "versions."]),
    _field("protocol_version", SYSTEM, "string", True, None,
           "Never null. A conclusion with no protocol version cannot be "
           "read under the rules it was made under.",
           "Must match a published protocol version.",
           "Copied from the protocol document in force at authoring time.",
           False, True,
           ["Not a data version and not a source version."]),
    _field("question", CURATOR, "object", True, None,
           "Never null. A conclusion with no question answers nothing.",
           "Gene and drug canonical keys, effect dimension, question text; "
           "phenotype scope and population optional.",
           "Gene and drug keys must exist in the canonical build.",
           True, True,
           ["Not a gene/drug pair key: a pair-level conclusion must not be "
            "applied to every annotation sharing that pair."]),
    _field("question.phenotype_scope", CURATOR, "array<Phenotype>", False,
           tuple(item.value for item in Phenotype),
           "Empty means the conclusion is not scoped to a phenotype - not "
           "that it applies to every phenotype.",
           "Exact Phenotype members; no aliases; RAPID and ULTRARAPID are "
           "distinct members and must both be listed to cover both.",
           "Normalization must be explained in the rationale.",
           True, True,
           ["An empty scope is not a wildcard.",
            "RAPID must never be read as covering ULTRARAPID "
            "(SAFETY-INV-004)."]),
    _field("status", CURATOR, "InterpretationStatus", True,
           vocabulary_members(InterpretationStatus),
           "Never null. Defaults to DRAFT, which means nobody has reviewed "
           "it.",
           "CURATED additionally requires rationale and a distinct named "
           "reviewer.",
           "Each transition records who made it and when.",
           True, False,
           ["DRAFT is not a rejection.",
            "The persisted CurationStatus spells DRAFT as RAW; they are the "
            "same state under two names, not two states."]),
    _field("conclusion_state", CURATOR, "ConclusionState", True,
           vocabulary_members(ConclusionState),
           "Never null. Absence of a conclusion is expressed as "
           "INSUFFICIENT, with a statement of what is missing.",
           "INSUFFICIENT requires an insufficiency statement; CONFLICTING "
           "requires a recorded conflict.",
           "Must follow from the cited evidence via the rationale.",
           True, True,
           ["Not ordered: INSUFFICIENT is not a weak SUPPORTED.",
            "INSUFFICIENT is never low risk, no risk, no effect, safe, "
            "normal or negative evidence (SAFETY-INV-001).",
            "CONFLICTING does not mean the disagreement was resolved."]),
    _field("conclusion_text", CURATOR, "string", True, None,
           "Never null. A state with no sentence cannot be reviewed.",
           "Substantive text; screened for reassuring language when the "
           "state is INSUFFICIENT or CONFLICTING.",
           "Written by the named author.",
           True, False,
           ["Not patient-facing text.",
            "Not a recommendation, and not advice."]),
    _field("applicability", CURATOR, "Applicability", True,
           vocabulary_members(Applicability),
           "Never null. UNCLEAR is the honest answer when the population is "
           "not established; it is not a null.",
           "One controlled member.",
           "The population statement in the rationale must support it.",
           True, True,
           ["APPLICABLE does not mean applicable to every population - it "
            "means applicable to the one stated."]),
    _field("effect_dimension", CURATOR, "EffectDimension", True,
           vocabulary_members(EffectDimension),
           "Never null. INSUFFICIENT_TO_CLASSIFY is the answer when the "
           "dimension is not established.",
           "One controlled member.",
           "Normalization from the source's wording must be explained.",
           True, True,
           ["Not a treatment instruction.",
            "Not a direction of risk: ACTIVATION says what changed, not "
            "whether that is good or bad for a patient."]),
    _field("evidence", CURATOR, "array<EvidenceSelection>", True, None,
           "Never empty. A conclusion with no evidence is untraceable.",
           "At least one included record; no repeats; each with a written "
           "rationale.",
           "Every UUID must exist in the sealed evidence build.",
           True, True,
           ["Not a bibliography: each entry states a relationship to this "
            "conclusion."]),
    _field("evidence[].relationship", CURATOR, "EvidenceRelationship", True,
           vocabulary_members(EvidenceRelationship),
           "Never null.",
           "EXCLUDED requires an exclusion_reason; every other value forbids "
           "one.",
           "The relationship is the curator's assessment, not the source's.",
           True, True,
           ["CONTRADICTS is not a reason to delete the record.",
            "CONTEXT_ONLY does not mean irrelevant."]),
    _field("evidence[].exclusion_reason", CURATOR, "ExclusionReason", False,
           vocabulary_members(ExclusionReason),
           "Null means the record was not excluded. It never means excluded "
           "for an unstated reason.",
           "Required exactly when relationship is EXCLUDED.",
           "Accompanied by written rationale in the same entry.",
           True, False,
           ["Not a category that may be applied automatically: "
            "contradictory, older, other-organisation and unknown-version "
            "evidence must never be excluded by rule."]),
    _field("evidence[].trace_verified", SYSTEM, "boolean", False, None,
           "Null means the trace was not checked, which is different from a "
           "check that failed. Neither may be reported as verified.",
           "Set only by a verification run against the sealed build.",
           "Derived from pgx-evidence verify.",
           False, True,
           ["Null is not False and False is not 'probably fine'."]),
    _field("evidence[].source_version_status", SOURCE, "string", True, None,
           "Never null. UNKNOWN_LEGACY records that a version existed and "
           "was lost; SOURCE_UNVERSIONED records that the source has none.",
           "Copied verbatim from the evidence record.",
           "Comes from the evidence build, never from the curator.",
           False, True,
           ["UNKNOWN_LEGACY must not be hidden behind a confidence label.",
            "An unknown version is not an old version."]),
    _field("source_reported", SOURCE, "array<SourceReportedValues>", False,
           None,
           "Empty means no source-reported value was recorded for "
           "comparison. It does not mean the source reported nothing.",
           "Copied unchanged from the evidence record's own payload.",
           "Each entry names the evidence record it came from.",
           False, False,
           ["significance=yes is not ConclusionState.SUPPORTED.",
            "A ClinPGx score is not confidence, importance, strength or "
            "risk, and must not be mapped to any of them.",
            "polarity is not a direction of patient risk."]),
    _field("conflict", CURATOR, "ConflictAnalysis", True, None,
           "Never null. NONE_IDENTIFIED means nobody found a conflict, not "
           "that none exists.",
           "Any state other than NONE_IDENTIFIED requires at least two "
           "evidence records, a disputed field, materiality and analysis.",
           "Every conflicting record stays cited.",
           True, True,
           ["NONE_IDENTIFIED is not a finding of agreement.",
            "There is no precedence field, and adding one would be a change "
            "to this project's scientific position."]),
    _field("conflict.material", CURATOR, "boolean", False, None,
           "Null is refused on a recorded conflict: undetermined materiality "
           "is expressed as UNRESOLVED with material=False and an "
           "explanation.",
           "Required whenever state is not NONE_IDENTIFIED.",
           "Judged by a named curator.",
           True, True,
           ["Immaterial does not mean absent.",
            "Materiality is not severity."]),
    _field("insufficiency", CURATOR, "InsufficiencyStatement", False, None,
           "Null means the conclusion is not INSUFFICIENT. It never means "
           "sufficiency was established.",
           "Required exactly when conclusion_state is INSUFFICIENT; screened "
           "for reassuring language.",
           "Must list the evidence actually reviewed.",
           True, False,
           ["Not a low-risk finding.",
            "Not a negative result: nothing was ruled out."]),
    _field("rationale", CURATOR, "Rationale", False, None,
           "Null means the conclusion has not been argued, so it cannot be "
           "CURATED.",
           "Eleven named parts, each substantive; placeholder and circular "
           "text refused.",
           "Names the author, and the reviewer once reviewed.",
           True, False,
           ["Not a summary of the conclusion.",
            "A source's own wording quoted here is not an argument for the "
            "conclusion."]),
    _field("rationale.authored_by", CURATOR, "ReviewSignature", False, None,
           "Null means unauthored. An unauthored conclusion is not "
           "reviewable.",
           "Named person, scientific role, UTC instant, written reason.",
           "The person is accountable for the conclusion.",
           True, False,
           ["A team name, a role name or a system name is not an author."]),
    _field("rationale.reviewed_by", CURATOR, "ReviewSignature", False, None,
           "Null means not independently reviewed, which blocks CURATED.",
           "Must be a different person from the author, in a reviewing role.",
           "Recorded with instant and reason.",
           True, False,
           ["The author re-reading their own work is not an independent "
            "review."]),
    _field("unresolved_references", SYSTEM, "array<string>", False, None,
           "Empty means nothing was left dangling, not that everything "
           "resolved successfully.",
           "Populated from the evidence build's unresolved references.",
           "Carried forward from WP-07's resolution queue.",
           False, True,
           ["An unresolved reference is not a resolved-to-nothing "
            "reference."]),
    _field("content_hash", SYSTEM, "string", True, None,
           "Never null.",
           "sha256 over the record's content identity, excluding operational "
           "timestamps.",
           "Deterministic; two identical records hash alike.",
           False, False,
           ["Not a signature and not an approval."]),
    _field("is_rule_eligible", SYSTEM, "boolean", True, None,
           "Never null. False is the default and the safe answer.",
           "True only for a CURATED, SUPPORTED conclusion with no blocking "
           "conflict, no insufficiency and no unresolved reference.",
           "Derived, never set by a curator.",
           False, True,
           ["Eligibility is not approval: WP-11 still requires its own "
            "review before a rule exists."]),
)


def field_definition(name: str) -> FieldDefinition:
    """Look one field up by name, or raise saying it is undefined."""
    for item in FIELD_DICTIONARY:
        if item.name == name:
            return item
    raise ProtocolError("no field definition for %r" % name,
                        code="CUR_FIELD_DEFINITION_MISSING")


def field_dictionary_json() -> Dict[str, Any]:
    """The dictionary as a published artifact."""
    return {
        "field_dictionary_version": FIELD_DICTIONARY_VERSION,
        "status": "DRAFT_AWAITING_EXPERT_REVIEW",
        "field_count": len(FIELD_DICTIONARY),
        "fields": [item.to_json() for item in FIELD_DICTIONARY],
        "note": ("Every field states an owner and a null meaning. Null is a "
                 "distinct fact, never a value, and never a reassurance."),
    }
