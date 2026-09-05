# -*- coding: utf-8 -*-
"""Rule and ruleset lifecycle policy (WP-11).

The state machines live in :mod:`pgx.rules.models` as data. This module is what
each transition *requires* beyond being legal, expressed as data too, so the
service, the CLI, the database trigger and the documentation cite one list.

The shape of the argument is the same at every step: a transition is never
inferred from fields happening to be present. ``VALIDATED`` is not what a rule
becomes when it has an approver column filled in; it is what a rule becomes
when a named person performed an audited act after every gate below opened.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Mapping, Tuple

from pgx.curation.vocabulary import (Applicability, ConclusionState,
                                     ConflictState, CurationRole)
from pgx.domain.enums import CurationStatus, RuleStatus, RulesetStatus

__all__ = [
    "ELIGIBLE_APPLICABILITY",
    "ELIGIBLE_CONCLUSION_STATES",
    "ELIGIBLE_CONFLICT_STATES",
    "RULESET_TRANSITION_REQUIREMENTS",
    "RULE_TRANSITION_REQUIREMENTS",
    "RULE_VALIDATION_ROLES",
    "TransitionRequirement",
    "ineligible_conclusion_reason",
]


@dataclass(frozen=True, slots=True)
class TransitionRequirement:
    """What one transition needs, and who may perform it."""

    source: str
    target: str
    roles: FrozenSet[CurationRole]
    requirements: Tuple[str, ...]

    def to_json(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "roles": sorted(role.value for role in self.roles),
            "requirements": list(self.requirements),
        }


#: Which curation conclusions a WP-11 condition can honestly encode.
#:
#: ``SUPPORTED`` alone. The others are excluded for a specific reason each:
#:
#: * ``CONFLICTING`` - the sources disagree, and a rule stating one attention
#:   level would hide that (``SAFETY-INV-008``);
#: * ``INSUFFICIENT`` - the evidence does not support a stronger statement, and
#:   encoding it as an attention level would turn "we do not know" into a
#:   finding (``SAFETY-INV-001``);
#: * ``NOT_INTERPRETABLE`` - nobody could read the evidence, so there is
#:   nothing to encode;
#: * ``OUT_OF_SCOPE`` / ``NOT_APPLICABLE`` - the conclusion is about something
#:   this rule grammar is not about.
#:
#: Those cases are not lost: they remain curated conclusions with their
#: rationale, and downstream they become coverage results rather than rules.
ELIGIBLE_CONCLUSION_STATES: FrozenSet[ConclusionState] = frozenset({
    ConclusionState.SUPPORTED,
})

#: Only a conclusion whose applicability the condition can actually express.
#: ``PARTIALLY_APPLICABLE`` is refused because the WP-11 grammar has no way to
#: say "applies to adults but not in pregnancy" - and a rule that dropped the
#: qualifier would apply to populations nobody reviewed.
ELIGIBLE_APPLICABILITY: FrozenSet[Applicability] = frozenset({
    Applicability.APPLICABLE,
})

#: Only a conclusion with no live disagreement. ``PRESENT`` is admitted only
#: when the curator recorded it as immaterial; ``UNRESOLVED`` and
#: ``ADJUDICATION_REQUIRED`` are open questions.
ELIGIBLE_CONFLICT_STATES: FrozenSet[ConflictState] = frozenset({
    ConflictState.NONE_IDENTIFIED,
    ConflictState.PRESENT,
})

#: Who may validate a rule. Not the author: the same separation WP-10 enforces
#: for curation applies to the rule derived from it, because a rule is a second
#: scientific claim about the same evidence.
RULE_VALIDATION_ROLES: FrozenSet[CurationRole] = frozenset({
    CurationRole.INDEPENDENT_SCIENTIFIC_REVIEWER,
    CurationRole.ADJUDICATOR,
})


RULE_TRANSITION_REQUIREMENTS: Mapping[Tuple[str, str], TransitionRequirement] = {
    (RuleStatus.DRAFT.value, RuleStatus.CURATED.value): TransitionRequirement(
        source=RuleStatus.DRAFT.value, target=RuleStatus.CURATED.value,
        roles=frozenset({CurationRole.SCIENTIFIC_CURATOR}),
        requirements=(
            "the referenced curated interpretation is genuinely CURATED in WP-10",
            "the exact curation revision id is named",
            "the stored revision hash matches the revision that was reviewed",
            "the curation protocol version and hash are pinned",
            "at least one evidence record is cited",
        )),
    (RuleStatus.CURATED.value, RuleStatus.VALIDATED.value): TransitionRequirement(
        source=RuleStatus.CURATED.value, target=RuleStatus.VALIDATED.value,
        roles=RULE_VALIDATION_ROLES,
        requirements=(
            "structural, reference, lifecycle, provenance and eligibility "
            "validation all pass",
            "a complete WP-10 rule approval envelope names this rule version",
            "the envelope separates creator, reviewer and approver",
            "the validator is not the rule's author",
            "every evidence reference resolves inside the pinned evidence build",
            "the curated conclusion is SUPPORTED and APPLICABLE",
            "no unresolved conflict is recorded on the conclusion",
        )),
    (RuleStatus.VALIDATED.value, RuleStatus.DEPRECATED.value): TransitionRequirement(
        source=RuleStatus.VALIDATED.value, target=RuleStatus.DEPRECATED.value,
        roles=RULE_VALIDATION_ROLES,
        requirements=(
            "a named actor, their role, an instant and a stated reason",
            "an append-only audit event",
            "the rule is never deleted: frozen rulesets that cite it stay "
            "verifiable",
        )),
}


RULESET_TRANSITION_REQUIREMENTS: Mapping[Tuple[str, str], TransitionRequirement] = {
    (RulesetStatus.BUILDING.value, RulesetStatus.VALIDATED.value):
        TransitionRequirement(
            source=RulesetStatus.BUILDING.value,
            target=RulesetStatus.VALIDATED.value,
            roles=RULE_VALIDATION_ROLES,
            requirements=(
                "the member set is non-empty",
                "every member is a VALIDATED rule",
                "no member is DEPRECATED",
                "no member appears twice",
                "no blocking duplicate, overlap or conflicting outcome",
                "every member pins the same dataset and evidence boundary",
                "every member pins the same protocol and source-policy boundary",
                "every member's stored content hash still matches its definition",
            )),
    (RulesetStatus.VALIDATED.value, RulesetStatus.FROZEN.value):
        TransitionRequirement(
            source=RulesetStatus.VALIDATED.value,
            target=RulesetStatus.FROZEN.value,
            roles=RULE_VALIDATION_ROLES,
            requirements=(
                "a deterministic build produced a manifest, approval list and "
                "build log",
                "the build verified its own output before publication",
                "every checksum matched",
                "no frozen artifact already exists at that identity",
                "membership was unchanged since validation",
            )),
    (RulesetStatus.VALIDATED.value, RulesetStatus.BUILDING.value):
        TransitionRequirement(
            source=RulesetStatus.VALIDATED.value,
            target=RulesetStatus.BUILDING.value,
            roles=RULE_VALIDATION_ROLES,
            requirements=(
                "a named actor and a stated reason for reopening",
                "the validation result is discarded rather than carried over: a "
                "set whose membership changed was not the set that validated",
            )),
    (RulesetStatus.FROZEN.value, RulesetStatus.RETIRED.value):
        TransitionRequirement(
            source=RulesetStatus.FROZEN.value, target=RulesetStatus.RETIRED.value,
            roles=RULE_VALIDATION_ROLES,
            requirements=(
                "a named actor, their role, an instant and a stated reason",
                "an append-only audit event",
                "the frozen artifact is kept: historical assessments that cited "
                "it must stay reproducible",
            )),
}


def ineligible_conclusion_reason(
    conclusion_state: ConclusionState,
    applicability: Applicability,
    conflict_state: ConflictState,
    conflict_material: bool = False,
) -> Tuple[str, ...]:
    """Why this curated conclusion cannot become a validated rule, if it cannot.

    Returns an empty tuple when it can. Each string names the specific reason,
    because "ineligible" on its own tells a curator nothing about what to do.
    """
    reasons = []
    if conclusion_state not in ELIGIBLE_CONCLUSION_STATES:
        explanation = {
            ConclusionState.CONFLICTING:
                "the sources disagree; a rule stating one attention level would "
                "hide that disagreement (SAFETY-INV-008)",
            ConclusionState.INSUFFICIENT:
                "the evidence does not support a stronger statement; encoding "
                "it as an attention level would turn 'we do not know' into a "
                "finding (SAFETY-INV-001)",
            ConclusionState.NOT_INTERPRETABLE:
                "nobody could read the evidence, so there is nothing to encode",
            ConclusionState.OUT_OF_SCOPE:
                "the conclusion is about something outside what this rule "
                "grammar describes",
            ConclusionState.NOT_APPLICABLE:
                "the conclusion states the axis does not apply, which is not a "
                "rule",
        }.get(conclusion_state, "this conclusion state cannot be encoded")
        reasons.append("conclusion_state %s: %s"
                       % (conclusion_state.value, explanation))
    if applicability not in ELIGIBLE_APPLICABILITY:
        reasons.append(
            "applicability %s: the WP-11 condition grammar cannot express a "
            "partial or unclear applicability constraint, and a rule that "
            "dropped the qualifier would apply to populations nobody reviewed"
            % applicability.value)
    if conflict_state not in ELIGIBLE_CONFLICT_STATES:
        reasons.append(
            "conflict_state %s: an open disagreement must be settled by people "
            "before it can be encoded" % conflict_state.value)
    elif conflict_state is ConflictState.PRESENT and conflict_material:
        reasons.append(
            "conflict_state PRESENT and material: the curator recorded that the "
            "disagreement changes the answer, so it is not settled")
    return tuple(reasons)
