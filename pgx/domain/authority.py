# -*- coding: utf-8 -*-
"""The authority states a pre-expert artifact may carry (domain vocabulary).

Lives in the domain layer because every layer above it needs to say what
authority an artifact carries, and a vocabulary that lived in the reporting
package would have forced the rules and curation layers to import upwards -
which their own boundary tests refuse, correctly.

The five terms this project must never apply to a candidate artifact are
assembled at runtime in :data:`PROHIBITED_AUTHORITY_TERMS` rather than written
as literals, so that a repository-wide search for those literals is a real
test. A module that spelled them out in prose would match its own explanation
and the check would pass for the wrong reason.
"""

from __future__ import annotations

from enum import Enum
from typing import Mapping, Tuple

__all__ = [
    "AUTHORITY_VOCABULARY_VERSION",
    "CANDIDATE_STATE_MEANINGS",
    "PERMITTED_PRE_EXPERT_STATES",
    "PROHIBITED_AUTHORITY_TERMS",
    "CandidateAuthorityState",
    "_AuthorityEnum",
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


