# -*- coding: utf-8 -*-
"""Candidate authority states and the bridge to the existing gates (WP-C07..C09).

Wave 3 asks for a candidate scientific build that is honest about what has and
has not happened to it. The repository already has a complete authority model
built for a world where named external humans - an independent scientific
reviewer, an adjudicator, a physician - have signed things. That model is
correct and stays exactly as it is. Nothing in this module edits it, relaxes
it, or fills one of its fields with an identity that is not the person it names.

What this module adds is a *parallel* vocabulary for the states a candidate
artifact can honestly be in **before** any external expert has looked at it,
plus a table saying, gate by gate, which existing requirement a candidate
artifact can satisfy today and which it provably cannot.

The distinction that makes this safe to have at all:

* The existing states (``VALIDATED`` rule, ``FROZEN`` ruleset, ``ACTIVE``
  release) are *production* authority. They keep their existing meaning and
  their existing human requirements.
* The states here are *candidate* authority. A candidate artifact is one the
  project team built and checked internally. It has no external endorsement,
  and every state below says so in its own name.

The five terms this project must never apply to a candidate artifact are
assembled at runtime in :data:`PROHIBITED_AUTHORITY_TERMS` rather than written
as literals. That is not obfuscation - it is so that a repository-wide search
for those literals is a real test. A module that spelled them out in prose
would match its own explanation and the check would pass for the wrong reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, Mapping, Tuple

__all__ = [
    "AUTHORITY_VOCABULARY_VERSION",
    "BRIDGE_ENTRIES",
    "CANDIDATE_STATE_MEANINGS",
    "PERMITTED_PRE_EXPERT_STATES",
    "PROHIBITED_AUTHORITY_TERMS",
    "AuthorityBridgeEntry",
    "CandidateAuthorityState",
    "CandidateDecisionRecord",
    "SatisfiabilityVerdict",
    "bridge_table",
    "contains_prohibited_term",
    "describe_state",
]

AUTHORITY_VOCABULARY_VERSION = "pgx-wave03-candidate-authority/1"


def _forbidden_terms() -> Tuple[str, ...]:
    """The five claims a pre-expert artifact must never make.

    Assembled from fragments so this file does not itself contain the literal
    strings. The scanner in the tests greps the repository for them; if they
    were written out here the scanner would find its own definition and report
    a clean tree while still matching, which is the failure mode that has bitten
    this project repeatedly with substring rules.
    """
    expert = "EXPERT"
    approved = "APPROVED"
    validated = "VALIDATED"
    reviewed = "REVIEWED"
    return (
        expert + "_" + approved,
        "PHYSICIAN" + "_" + approved,
        "CLINICALLY" + "_" + validated,
        "INDEPENDENTLY" + "_" + validated,
        "EXTERNAL" + "_" + reviewed,
    )


#: Terms that may not name the authority of any candidate artifact, and may not
#: appear as a state value anywhere Wave 3 writes.
PROHIBITED_AUTHORITY_TERMS: Tuple[str, ...] = _forbidden_terms()


class _AuthorityEnum(str, Enum):
    """String-valued and unordered, following the project convention.

    Ordering is refused here for a specific reason: it is tempting to read the
    states below as a ladder from weak to strong, and then to write code that
    asks whether an artifact is "at least" some level. There is no such ladder.
    ``SOFTWARE_VERIFICATION`` and ``INTERNAL_VALIDATION`` are claims about
    different things - that the code does what it says, and that the content
    survived an internal check - and neither implies the other.
    """

    def __str__(self) -> str:
        return self.value

    def __lt__(self, other: object) -> bool:  # pragma: no cover - guard
        raise TypeError("%s values are not ordered" % type(self).__name__)

    __le__ = __lt__
    __gt__ = __lt__
    __ge__ = __lt__


class CandidateAuthorityState(_AuthorityEnum):
    """What has actually happened to a candidate artifact.

    Each member names an act that was really performed, by someone or something
    this repository can identify. None of them names an external expert,
    because no external expert has seen any of this.
    """

    SOURCE_GROUNDED_INTERNAL_DECISION = "SOURCE_GROUNDED_INTERNAL_DECISION"
    PROJECT_TEAM_PROVISIONAL = "PROJECT_TEAM_PROVISIONAL"
    PENDING_EXTERNAL_EXPERT_REVIEW = "PENDING_EXTERNAL_EXPERT_REVIEW"
    INTERNAL_VALIDATION = "INTERNAL_VALIDATION"
    LITERATURE_DERIVED_VALIDATION = "LITERATURE_DERIVED_VALIDATION"
    SOFTWARE_VERIFICATION = "SOFTWARE_VERIFICATION"


PERMITTED_PRE_EXPERT_STATES: Tuple[str, ...] = tuple(
    item.value for item in CandidateAuthorityState)


#: What each state claims, and - more importantly - what it does not claim.
#: Written out because the second half is the part that gets dropped when a
#: state name is copied into a report.
CANDIDATE_STATE_MEANINGS: Mapping[str, Tuple[str, str]] = {
    CandidateAuthorityState.SOURCE_GROUNDED_INTERNAL_DECISION.value: (
        "the project team read a named authoritative source at a recorded "
        "instant and decided something on the strength of it",
        "nobody outside the project agreed with the reading, and the source's "
        "authors have not been consulted"),
    CandidateAuthorityState.PROJECT_TEAM_PROVISIONAL.value: (
        "the project team made a working decision so that build could "
        "continue",
        "it is provisional by construction and is expected to be revisited"),
    CandidateAuthorityState.PENDING_EXTERNAL_EXPERT_REVIEW.value: (
        "the artifact is finished enough to be handed to an external expert",
        "no external expert has been engaged, scheduled, or shown anything"),
    CandidateAuthorityState.INTERNAL_VALIDATION.value: (
        "an internal check compared the artifact against an expectation the "
        "project team wrote down",
        "the expectation and the artifact share an author, so agreement "
        "between them is not independent evidence"),
    CandidateAuthorityState.LITERATURE_DERIVED_VALIDATION.value: (
        "the artifact was checked against a published source rather than "
        "against the project's own expectation",
        "the check was performed by the project team, and a reading of a "
        "guideline is not the guideline's endorsement"),
    CandidateAuthorityState.SOFTWARE_VERIFICATION.value: (
        "executable checks show the software behaves as its specification "
        "says",
        "this is a statement about code, not about whether the science "
        "encoded in it is right"),
}


def describe_state(state: CandidateAuthorityState) -> Tuple[str, str]:
    """Return ``(claims, does_not_claim)`` for one state."""
    if not isinstance(state, CandidateAuthorityState):
        raise TypeError("describe_state takes a CandidateAuthorityState")
    return CANDIDATE_STATE_MEANINGS[state.value]


def contains_prohibited_term(text: str) -> Tuple[str, ...]:
    """Which prohibited authority terms appear in ``text``.

    Case-sensitive on purpose. The prohibition is on the token this project
    uses as a state value, not on the English words; a sentence explaining that
    something has *not* been approved by an expert is exactly the sentence
    Wave 3 wants written.
    """
    if not isinstance(text, str):
        raise TypeError("contains_prohibited_term takes a string")
    return tuple(term for term in PROHIBITED_AUTHORITY_TERMS if term in text)


class SatisfiabilityVerdict(_AuthorityEnum):
    """Whether a candidate artifact can meet one existing requirement today."""

    SATISFIED_BY_CANDIDATE_TRACK = "SATISFIED_BY_CANDIDATE_TRACK"
    BLOCKED_REQUIRES_EXTERNAL_HUMAN = "BLOCKED_REQUIRES_EXTERNAL_HUMAN"
    BLOCKED_REQUIRES_SECOND_INTERNAL_HUMAN = \
        "BLOCKED_REQUIRES_SECOND_INTERNAL_HUMAN"
    NOT_APPLICABLE_TO_CANDIDATE_TRACK = "NOT_APPLICABLE_TO_CANDIDATE_TRACK"


@dataclass(frozen=True, slots=True)
class AuthorityBridgeEntry:
    """One existing requirement, where it lives, and what a candidate can do.

    ``candidate_path`` is deliberately allowed to be empty. An entry whose
    verdict is ``BLOCKED_REQUIRES_EXTERNAL_HUMAN`` and whose candidate path is
    "" is the most useful kind of row in this table: it names a gate that
    Wave 3 must not try to open.
    """

    requirement_id: str
    requirement: str
    module: str
    symbol: str
    verdict: SatisfiabilityVerdict
    candidate_path: str
    note: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "requirement": self.requirement,
            "module": self.module,
            "symbol": self.symbol,
            "verdict": self.verdict.value,
            "candidate_path": self.candidate_path,
            "note": self.note,
        }


# -- the bridge table --------------------------------------------------------
#
# Each row names one requirement that already exists in this repository, says
# where it lives so a reader can open the file and disagree, and states what a
# Wave 3 candidate artifact can honestly do about it.
#
# The rows that matter most are the blocked ones. A table that only listed what
# Wave 3 could clear would read as a plan; listing what it cannot clear is what
# makes it a boundary.

BRIDGE_ENTRIES: Tuple[AuthorityBridgeEntry, ...] = (
    AuthorityBridgeEntry(
        requirement_id="AB-01",
        requirement=(
            "A rule may leave CURATED only when a complete WP-10 rule approval "
            "envelope names the rule version and separates creator, reviewer "
            "and approver, and the validator is not the rule's author."),
        module="pgx/rules/lifecycle.py",
        symbol="RULE_TRANSITION_REQUIREMENTS[('CURATED', 'VALIDATED')]",
        verdict=SatisfiabilityVerdict.BLOCKED_REQUIRES_SECOND_INTERNAL_HUMAN,
        candidate_path="",
        note=(
            "Three distinct people are required and the project has one named "
            "reviewer. A single AI pass cannot supply the second and third: it "
            "is one process with one set of priors, so 'creator' and "
            "'reviewer' would be the same judgement recorded twice. Wave 3 "
            "therefore leaves every candidate rule outside this transition "
            "entirely rather than entering it with a manufactured envelope."),
    ),
    AuthorityBridgeEntry(
        requirement_id="AB-02",
        requirement=(
            "A ruleset may leave BUILDING only when every member is a "
            "VALIDATED rule."),
        module="pgx/rules/lifecycle.py",
        symbol="RULESET_TRANSITION_REQUIREMENTS[('BUILDING', 'VALIDATED')]",
        verdict=SatisfiabilityVerdict.BLOCKED_REQUIRES_SECOND_INTERNAL_HUMAN,
        candidate_path="",
        note=(
            "Follows from AB-01 and is listed separately because it is the "
            "gate somebody would be tempted to open first. A candidate "
            "ruleset is built and frozen on its own track with its own "
            "identity; it never claims RulesetStatus.VALIDATED."),
    ),
    AuthorityBridgeEntry(
        requirement_id="AB-03",
        requirement=(
            "An interpretation may be curated only under an approved curation "
            "protocol, and the protocol must be approved by a named expert."),
        module="pgx/ths6/vocabulary.py",
        symbol="BLOCKER_CODES['THS6_CURATION_PROTOCOL_NOT_APPROVED']",
        verdict=SatisfiabilityVerdict.BLOCKED_REQUIRES_EXTERNAL_HUMAN,
        candidate_path="",
        note=(
            "The named expert is exactly the person Wave 3 is forbidden to "
            "invent. Wave 3's curation is recorded as internal curation "
            "against the retrieved sources and is never written into the "
            "WP-10 curation store."),
    ),
    AuthorityBridgeEntry(
        requirement_id="AB-04",
        requirement=(
            "The expert review protocol requires a signatory, a named "
            "reviewer, and a completed review before any review-derived claim "
            "may be made."),
        module="pgx/ths6/vocabulary.py",
        symbol=("BLOCKER_CODES['THS6_EXPERT_PROTOCOL_NOT_APPROVED'], "
                "['THS6_NO_NAMED_REVIEWER'], ['THS6_NO_COMPLETED_REVIEW']"),
        verdict=SatisfiabilityVerdict.BLOCKED_REQUIRES_EXTERNAL_HUMAN,
        candidate_path="",
        note=(
            "Wave 3 does not touch pgx.expert_review at all. Its state "
            "machine is correct and its emptiness is the accurate record."),
    ),
    AuthorityBridgeEntry(
        requirement_id="AB-05",
        requirement=(
            "The claim boundary is a draft awaiting human and scientific "
            "review; no role on the sign-off matrix has signed."),
        module="pgx/ths6/vocabulary.py",
        symbol=("BLOCKER_CODES['THS6_CLAIM_BOUNDARY_NOT_APPROVED'], "
                "['THS6_NO_HUMAN_SIGNOFF']"),
        verdict=SatisfiabilityVerdict.BLOCKED_REQUIRES_EXTERNAL_HUMAN,
        candidate_path="",
        note=(
            "Unchanged by Wave 3 and expected to stay unchanged until the "
            "external evaluation this build is being prepared for."),
    ),
    AuthorityBridgeEntry(
        requirement_id="AB-06",
        requirement=(
            "A source policy record may hold an approving status only when it "
            "carries a ReviewRecord with a named reviewer, a decision instant "
            "and at least one official evidence reference."),
        module="pgx/scientific/models.py",
        symbol="SourcePolicyRecord.is_approved / ReviewRecord",
        verdict=SatisfiabilityVerdict.SATISFIED_BY_CANDIDATE_TRACK,
        candidate_path=(
            "Wave 3 retrieved the four first-release guideline annotations "
            "itself and recorded, per retrieval, the official URL, the "
            "retrieval instant, a content hash and the licence basis. That is "
            "the evidence the H01 decision could not cite in Wave 1."),
        note=(
            "Satisfied as to *evidence*, not as to *registry mutation*. See "
            "AB-07: the registry cannot yet describe how the evidence was "
            "obtained, so config/scientific-sources.json stays byte-identical "
            "and the evidence lives on the candidate track."),
    ),
    AuthorityBridgeEntry(
        requirement_id="AB-07",
        requirement=(
            "Every source policy record must classify how the project is "
            "permitted to obtain records from the source, using a member of "
            "the AcquisitionMode vocabulary."),
        module="pgx/scientific/models.py",
        symbol="AcquisitionMode",
        verdict=SatisfiabilityVerdict.BLOCKED_REQUIRES_EXTERNAL_HUMAN,
        candidate_path=(
            "The smallest honest change is additive: one new AcquisitionMode "
            "member for agent-assisted targeted retrieval, deliberately "
            "excluded from AUTOMATED_ACQUISITION_MODES, plus one additive "
            "migration widening ck_source_policies_acquisition_mode_enum. The "
            "member name must be at most 32 characters to fit the existing "
            "column."),
        note=(
            "Wave 3 did NOT make that change. None of the six existing "
            "members describes what happened: MANUAL_DOWNLOAD and "
            "PUBLICATION_TRANSCRIPTION both say a human did it, OFFICIAL_API "
            "and LICENSED_BULK_EXPORT say an agreed interface did, "
            "INTERNAL_DERIVATION says no external source was involved, and "
            "NOT_DETERMINED says nobody decided. Choosing any of them would "
            "misdescribe the retrieval, and widening the production source "
            "vocabulary is a decision about what this project is permitted to "
            "do - which belongs to a human, not to the wave that wants the "
            "permission."),
    ),
    AuthorityBridgeEntry(
        requirement_id="AB-08",
        requirement=(
            "A canonical dataset must be published before anything downstream "
            "may treat it as authoritative."),
        module="pgx/ths6/vocabulary.py",
        symbol="BLOCKER_CODES['THS6_DATASET_NOT_PUBLISHED']",
        verdict=SatisfiabilityVerdict.SATISFIED_BY_CANDIDATE_TRACK,
        candidate_path=(
            "WP-C05 builds a new dataset through the existing canonical "
            "mechanism, with its own identifier, sealed raw snapshots and a "
            "data-quality report."),
        note=(
            "Publication of the dataset is a mechanical act with a "
            "deterministic definition; it is not a scientific endorsement, "
            "and the dataset-quality decision that accompanies it is recorded "
            "as PROJECT_TEAM_PROVISIONAL."),
    ),
    AuthorityBridgeEntry(
        requirement_id="AB-09",
        requirement=(
            "An executable ruleset must be registered before any assessment "
            "can be computed from governed content."),
        module="pgx/ths6/vocabulary.py",
        symbol="BLOCKER_CODES['THS6_NO_EXECUTABLE_RULESET']",
        verdict=SatisfiabilityVerdict.SATISFIED_BY_CANDIDATE_TRACK,
        candidate_path=(
            "WP-C08 freezes a candidate ruleset with its own identity, "
            "executable in DEMO and VALIDATION only."),
        note=(
            "Registering a candidate ruleset does not clear the THS-6 "
            "blocker, which asks about a governed ruleset built from "
            "VALIDATED rules. The two are separate evaluations and the gate "
            "matrix is not touched."),
    ),
    AuthorityBridgeEntry(
        requirement_id="AB-10",
        requirement=(
            "Fewer validation cases exist than the P0 target requires, and no "
            "independent holdout set exists."),
        module="pgx/ths6/vocabulary.py",
        symbol=("BLOCKER_CODES['THS6_INSUFFICIENT_VALIDATION_CASES'], "
                "['THS6_NO_HOLDOUT_SET']"),
        verdict=SatisfiabilityVerdict.SATISFIED_BY_CANDIDATE_TRACK,
        candidate_path=(
            "WP-C10 builds the case catalogue with sealed internal holdout "
            "and a reserved external-expert partition that nothing in this "
            "wave may open."),
        note=(
            "The cases are authored by the same process that authored the "
            "rules, so agreement between them is INTERNAL_VALIDATION and "
            "never independent evidence. The reserved partition exists "
            "precisely so that a later external reviewer has material the "
            "build has not seen."),
    ),
    AuthorityBridgeEntry(
        requirement_id="AB-11",
        requirement=(
            "Only VALIDATED rules from the active ruleset may ever execute "
            "(SAFETY-INV-003)."),
        module="pgx/domain/enums.py",
        symbol="RuleStatus",
        verdict=SatisfiabilityVerdict.NOT_APPLICABLE_TO_CANDIDATE_TRACK,
        candidate_path=(
            "The candidate ruleset is not the active production ruleset and "
            "does not execute in any production channel. Its execution is "
            "confined to DEMO and VALIDATION."),
        note=(
            "This row is NOT a way around SAFETY-INV-003. The invariant "
            "governs what may execute against a real patient-facing path, and "
            "the candidate track has no such path. If a candidate rule ever "
            "reached one, the invariant would be violated and the answer "
            "would be to stop, not to reclassify."),
    ),
    AuthorityBridgeEntry(
        requirement_id="AB-12",
        requirement=(
            "Gate F cannot pass while any of Gates A to E is not PASS, and "
            "there is no override."),
        module="pgx/ths6/gate_matrix.py",
        symbol="build_gate_matrix",
        verdict=SatisfiabilityVerdict.NOT_APPLICABLE_TO_CANDIDATE_TRACK,
        candidate_path="",
        note=(
            "Candidate readiness is evaluated separately and reported "
            "separately. Wave 3 does not write to the gate matrix, does not "
            "add a condition to it, and does not change any value it reads."),
    ),
)


def bridge_table() -> Tuple[Dict[str, Any], ...]:
    """The bridge as plain JSON-ready rows, ordered by requirement id."""
    return tuple(entry.to_json()
                 for entry in sorted(BRIDGE_ENTRIES,
                                     key=lambda item: item.requirement_id))


@dataclass(frozen=True, slots=True)
class CandidateDecisionRecord:
    """One versioned internal decision, with its authority stated on its face.

    ``authority_state`` is required and is checked against the permitted set at
    construction. There is no default: a record whose author did not think
    about what authority it carries is exactly the record that later gets read
    as more than it is.

    ``superseded_by`` makes the record versioned rather than mutable. A changed
    decision is a new record naming the old one; the old one stays readable,
    because the question "what did the project believe when it built this
    ruleset" has to remain answerable after the belief changes.
    """

    decision_id: str
    subject: str
    decision: str
    authority_state: CandidateAuthorityState
    rationale: str
    decided_at: str
    decided_by: str
    review_state: CandidateAuthorityState = \
        CandidateAuthorityState.PENDING_EXTERNAL_EXPERT_REVIEW
    evidence_keys: Tuple[str, ...] = ()
    supersedes: Tuple[str, ...] = ()
    revision: int = 1

    def __post_init__(self) -> None:
        for name in ("decision_id", "subject", "decision", "rationale",
                     "decided_at", "decided_by"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError("%s must be a non-empty string" % name)
        if not isinstance(self.authority_state, CandidateAuthorityState):
            raise TypeError(
                "authority_state must be a CandidateAuthorityState; the "
                "permitted pre-expert set is closed")
        if self.review_state is not \
                CandidateAuthorityState.PENDING_EXTERNAL_EXPERT_REVIEW:
            raise ValueError(
                "review_state may only be PENDING_EXTERNAL_EXPERT_REVIEW: no "
                "external expert has seen anything this wave produced")
        if not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("revision must be a positive integer")
        offending = contains_prohibited_term(
            " ".join((self.subject, self.decision, self.rationale,
                      self.decided_by)))
        if offending:
            raise ValueError(
                "a candidate decision may not claim %s"
                % ", ".join(offending))

    def to_json(self) -> Dict[str, Any]:
        claims, does_not_claim = describe_state(self.authority_state)
        return {
            "authority_state": self.authority_state.value,
            "authority_state_claims": claims,
            "authority_state_does_not_claim": does_not_claim,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
            "decision": self.decision,
            "decision_id": self.decision_id,
            "evidence_keys": list(self.evidence_keys),
            "rationale": self.rationale,
            "revision": self.revision,
            "review_state": self.review_state.value,
            "subject": self.subject,
            "supersedes": list(self.supersedes),
            "vocabulary_version": AUTHORITY_VOCABULARY_VERSION,
        }
