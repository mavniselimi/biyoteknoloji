# -*- coding: utf-8 -*-
"""Controlled vocabularies for the curation protocol (WP-09).

Every vocabulary here is **non-ordered**. There is no ``<``, no rank, no
numeric mapping and no "worse than". ``INSUFFICIENT`` is not a low
``SUPPORTED``; ``CONFLICTING`` is not a middling one. A scale would let a
later stage sort these into a severity, which is precisely the false
reassurance ``SAFETY-INV-001`` and ``SAFETY-INV-008`` exist to prevent.

None of these vocabularies carries a number. There is no confidence score, no
risk score, no safety score and no strength weight anywhere in this module,
because a number invites arithmetic and arithmetic over scientific judgement
produces a result nobody reviewed.

Every vocabulary and every definition in this package is
``DRAFT / AWAITING EXPERT REVIEW`` until a named scientific expert approves
the protocol. Nothing here is settled science.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, FrozenSet, Mapping, Tuple

from pgx.curation.errors import VocabularyError

__all__ = [
    "VOCABULARY_STATUS",
    "VOCABULARY_VERSION",
    "Applicability",
    "CaseRole",
    "ConclusionState",
    "ConflictState",
    "CurationRole",
    "EffectDimension",
    "EvidenceRelationship",
    "ExclusionReason",
    "InterpretationStatus",
    "LegacyReviewState",
    "ProtocolStatus",
    "REASSURING_TERMS",
    "SCIENTIFIC_APPROVAL_ROLES",
    "vocabulary_members",
    "vocabulary_registry",
]

#: Bumped when any member is added, removed or renamed. A conclusion recorded
#: under one vocabulary version is not comparable with one recorded under
#: another without somebody checking what changed.
VOCABULARY_VERSION = "pgx-curation-vocabulary/1"

#: Applies to every member below, and is repeated in every published artifact.
VOCABULARY_STATUS = "DRAFT_AWAITING_EXPERT_REVIEW"


class _CurationEnum(str, Enum):
    """A string enum that refuses to be ordered.

    ``str`` gives free JSON serialisation and equality with the wire value.
    The comparison operators are removed because ``str`` supplies them and
    they would silently answer "is INSUFFICIENT less than SUPPORTED" with a
    lexicographic accident.
    """

    def __str__(self) -> str:
        return self.value

    def __lt__(self, other):  # noqa: D105 - see class docstring
        raise VocabularyError(
            "%s is not ordered: comparing %r with %r would invent a scale "
            "this protocol deliberately does not define"
            % (type(self).__name__, self.value, other))

    __le__ = __gt__ = __ge__ = __lt__


class InterpretationStatus(_CurationEnum):
    """Lifecycle of one curation record.

    ``DRAFT`` is the protocol's name for the first state. The persisted
    :class:`pgx.domain.enums.CurationStatus` spells the same state ``RAW``;
    the delta is recorded for WP-10 rather than resolved here, because
    renaming a persisted enum is a migration and WP-09 does not own one.
    """

    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    CURATED = "CURATED"
    REJECTED = "REJECTED"


class ConclusionState(_CurationEnum):
    """What the curator concluded, after reviewing the selected evidence.

    ``INSUFFICIENT`` is a first-class answer, not a failure to answer. It
    means the evidence reviewed does not support a stronger statement, and it
    must never be rendered as low risk, no risk, no effect, safe, normal, or
    negative evidence.
    """

    SUPPORTED = "SUPPORTED"
    CONFLICTING = "CONFLICTING"
    INSUFFICIENT = "INSUFFICIENT"
    NOT_INTERPRETABLE = "NOT_INTERPRETABLE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class EvidenceRelationship(_CurationEnum):
    """How one evidence record relates to the conclusion.

    ``CONTRADICTS`` is a relationship, not a reason to drop the record. A
    conclusion whose contradicting evidence disappeared is a conclusion nobody
    can check.
    """

    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    CONTEXT_ONLY = "CONTEXT_ONLY"
    EXCLUDED = "EXCLUDED"


class Applicability(_CurationEnum):
    """Whether the conclusion applies to the population and context stated."""

    APPLICABLE = "APPLICABLE"
    PARTIALLY_APPLICABLE = "PARTIALLY_APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNCLEAR = "UNCLEAR"


class ConflictState(_CurationEnum):
    """Whether the selected evidence disagrees, and what that requires.

    ``NONE_IDENTIFIED`` says nobody found a conflict. It does not say there is
    none, and it is not a reassurance.
    """

    NONE_IDENTIFIED = "NONE_IDENTIFIED"
    PRESENT = "PRESENT"
    UNRESOLVED = "UNRESOLVED"
    ADJUDICATION_REQUIRED = "ADJUDICATION_REQUIRED"


class EffectDimension(_CurationEnum):
    """What dimension of behaviour the evidence speaks to.

    Neutral and non-prescriptive by construction. These name *what was
    observed to differ*, never what to do about it. There is no member for a
    dose, a treatment choice, an avoidance, a preference or a risk level, and
    a later stage that needed one would have to add it here in the open.
    """

    EXPOSURE = "EXPOSURE"
    CLEARANCE = "CLEARANCE"
    ACTIVATION = "ACTIVATION"
    RESPONSE_ASSOCIATION = "RESPONSE_ASSOCIATION"
    ADVERSE_EVENT_ASSOCIATION = "ADVERSE_EVENT_ASSOCIATION"
    FUNCTIONAL_ACTIVITY = "FUNCTIONAL_ACTIVITY"
    OTHER = "OTHER"
    INSUFFICIENT_TO_CLASSIFY = "INSUFFICIENT_TO_CLASSIFY"


class ExclusionReason(_CurationEnum):
    """Why a reviewed evidence record was excluded from the conclusion.

    Every member requires a written rationale beside it. None of these is a
    licence to exclude a category of evidence automatically: a record is not
    excludable for contradicting the conclusion, for being older, for coming
    from a different guideline organisation, or for having an unknown version.
    Those conditions stay visible and argued.
    """

    WRONG_ENTITY = "WRONG_ENTITY"
    WRONG_PHENOTYPE_SCOPE = "WRONG_PHENOTYPE_SCOPE"
    WRONG_POPULATION = "WRONG_POPULATION"
    DUPLICATE_SOURCE_RECORD = "DUPLICATE_SOURCE_RECORD"
    SUPERSEDED_SOURCE_VERSION = "SUPERSEDED_SOURCE_VERSION"
    INSUFFICIENT_DETAIL = "INSUFFICIENT_DETAIL"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    UNRESOLVED_PROVENANCE = "UNRESOLVED_PROVENANCE"
    OTHER_WITH_RATIONALE = "OTHER_WITH_RATIONALE"


class CurationRole(_CurationEnum):
    """Who may do what. Enforcement is WP-10's; the definition is here."""

    PROTOCOL_OWNER = "PROTOCOL_OWNER"
    SCIENTIFIC_CURATOR = "SCIENTIFIC_CURATOR"
    INDEPENDENT_SCIENTIFIC_REVIEWER = "INDEPENDENT_SCIENTIFIC_REVIEWER"
    ADJUDICATOR = "ADJUDICATOR"
    DATA_PROVENANCE_STEWARD = "DATA_PROVENANCE_STEWARD"
    ENGINEERING_OBSERVER = "ENGINEERING_OBSERVER"


#: The roles whose holder may approve a scientific conclusion. Engineering and
#: provenance roles are deliberately absent: they can say the pipeline is
#: sound, which is a different claim from the science being right.
SCIENTIFIC_APPROVAL_ROLES: FrozenSet[CurationRole] = frozenset({
    CurationRole.SCIENTIFIC_CURATOR,
    CurationRole.INDEPENDENT_SCIENTIFIC_REVIEWER,
    CurationRole.ADJUDICATOR,
})


class CaseRole(_CurationEnum):
    """What a case may be used for. One case holds exactly one role.

    ``SAFETY-INV-009``: once a holdout case informs development, the metric it
    later produces measures memory rather than generalisation, and no analysis
    afterwards can undo it.
    """

    TRAINING = "TRAINING"
    CALIBRATION = "CALIBRATION"
    DEVELOPMENT = "DEVELOPMENT"
    INTER_CURATOR_EXERCISE = "INTER_CURATOR_EXERCISE"
    INTERNAL_HOLDOUT = "INTERNAL_HOLDOUT"
    EXPERT_HOLDOUT = "EXPERT_HOLDOUT"


class LegacyReviewState(_CurationEnum):
    """Where one legacy migration candidate has got to.

    ``NOT_REVIEWED`` is the only state this package may assign. Every other
    member requires a named human, and nothing here can supply one.
    """

    NOT_REVIEWED = "NOT_REVIEWED"
    SELECTED_FOR_EXERCISE = "SELECTED_FOR_EXERCISE"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED_AS_DRAFT_INPUT = "ACCEPTED_AS_DRAFT_INPUT"
    REJECTED_AS_DRAFT_INPUT = "REJECTED_AS_DRAFT_INPUT"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"


class ProtocolStatus(_CurationEnum):
    """Lifecycle of the protocol document itself."""

    DRAFT = "DRAFT"
    AWAITING_EXPERT_REVIEW = "AWAITING_EXPERT_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


#: Words that must never describe an INSUFFICIENT or CONFLICTING conclusion.
#: Checked against rationale and conclusion text, because the vocabulary can
#: be respected while the prose beside it says "so this is probably fine".
REASSURING_TERMS: Tuple[str, ...] = (
    "low risk", "no risk", "not risky", "risk-free", "risk free",
    "no effect", "without effect", "safe", "safely", "reassuring",
    "normal result", "nothing to worry", "no concern", "no action needed",
    "negative evidence", "rules out", "ruled out", "excludes risk",
)


def vocabulary_registry() -> Mapping[str, Tuple[str, ...]]:
    """Every controlled vocabulary, by name, in declaration order.

    One place, so the published schemas and the protocol document can be
    checked against the code rather than against a second copy of it.
    """
    return {
        "InterpretationStatus": vocabulary_members(InterpretationStatus),
        "ConclusionState": vocabulary_members(ConclusionState),
        "EvidenceRelationship": vocabulary_members(EvidenceRelationship),
        "Applicability": vocabulary_members(Applicability),
        "ConflictState": vocabulary_members(ConflictState),
        "EffectDimension": vocabulary_members(EffectDimension),
        "ExclusionReason": vocabulary_members(ExclusionReason),
        "CurationRole": vocabulary_members(CurationRole),
        "CaseRole": vocabulary_members(CaseRole),
        "LegacyReviewState": vocabulary_members(LegacyReviewState),
        "ProtocolStatus": vocabulary_members(ProtocolStatus),
    }


def vocabulary_members(vocabulary) -> Tuple[str, ...]:
    """The members of one vocabulary, in declaration order.

    Declaration order, not sorted order: sorting would suggest the sequence
    means something, and none of these vocabularies is ordered.
    """
    return tuple(member.value for member in vocabulary)
