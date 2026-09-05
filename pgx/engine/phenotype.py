# -*- coding: utf-8 -*-
"""Exact phenotype matching (WP-12).

One question, answered one way: does this normalised phenotype satisfy this
WP-11 phenotype condition? ``EXACT`` is satisfied by equality with its single
declared value. ``ONE_OF`` is satisfied by membership in its explicitly listed
set. Nothing else is satisfied by anything.

What is absent here is the point of the module. There is no default arm, no
wildcard, no priority, no ordering, no most-severe-wins, no proximity, no
synonym table, and no expansion of a broad functional group. Legacy
``phenotype_matches`` has all of those through ``PROFILE_MATCH_GROUPS``, which
is how ``RAPID`` comes to satisfy a rule written for ``ULTRARAPID``
(``LEGACY-BUG-001``): implicit equivalence is an unreviewed scientific claim,
and ``SAFETY-INV-004`` forbids it.

Three input statuses reach the decision unchanged - missing, indeterminate and
unsupported. None of them is a match, and none of them is a ``NO_MATCH``
either. "This rule does not apply to POOR" and "we could not tell what the
phenotype was" are different answers, and only the first is a statement about
the input. Collapsing them here would erase, at the earliest possible point,
the distinction ``SAFETY-INV-001`` exists to protect downstream.

**Scope.** Given a whole :class:`~pgx.rules.conditions.RuleCondition`, this
module evaluates only the profile's phenotype for that condition's *gene*. It
does not look at the drug, does not decide whether the condition as a whole
applies, and does not read the rule's outcome or evidence. Selecting drugs and
evaluating a complete axis are WP-14's; a matcher that read the outcome could
let the answer depend on what the answer would cause.
"""

from __future__ import annotations

from typing import Optional, Tuple, Union

from pgx.domain.enums import Phenotype
from pgx.engine.phenotype_errors import PhenotypeMatchError
from pgx.engine.phenotype_models import MatchDecision, PhenotypeObservation
from pgx.rules.conditions import PhenotypeMatch, RuleCondition

__all__ = [
    "MATCHER_CONTRACT_VERSION",
    "match_condition",
    "match_observation",
    "truth_matrix",
]

#: The matcher's own contract version. Separate from the input contract: how a
#: value is read and how it is compared are two decisions, and either could be
#: revised without the other.
MATCHER_CONTRACT_VERSION = "pgx-phenotype-matcher/1"

#: Reason codes the matcher adds on top of the normaliser's. Both describe the
#: input rather than the rule, because a rule that does not apply is not a
#: failure of anything.
_GENE_ABSENT = "PHENOTYPE_INPUT_MISSING"


def _declared(condition: Union[PhenotypeMatch, RuleCondition]
              ) -> Tuple[str, Tuple[Phenotype, ...], str, str]:
    """Pull ``(operator, values, condition_hash, gene_key)`` out of either
    accepted type, refusing anything else.

    A raw dictionary is refused rather than interpreted. WP-11 owns the
    condition grammar, and a matcher that parsed conditions itself would be a
    second grammar with no reviewer - which is precisely how a wildcard would
    eventually get in.
    """
    if isinstance(condition, RuleCondition):
        return (condition.phenotype.operator, condition.phenotype.values,
                condition.content_hash(), condition.gene_canonical_key)
    if isinstance(condition, PhenotypeMatch):
        return (condition.operator, condition.values,
                _phenotype_match_hash(condition), "")
    raise PhenotypeMatchError(
        "expected a WP-11 PhenotypeMatch or RuleCondition, got %s. A raw "
        "mapping is not parsed here: WP-11 owns the condition grammar, and a "
        "second parser would be a second grammar nobody reviewed."
        % type(condition).__name__,
        code="PHENOTYPE_CONDITION_UNSUPPORTED_TYPE", location="$.condition")


def _phenotype_match_hash(match: PhenotypeMatch) -> str:
    from pgx.domain.hashing import sha256_digest
    return sha256_digest(match.to_json())


def match_observation(observation: PhenotypeObservation,
                      condition: Union[PhenotypeMatch, RuleCondition],
                      ) -> MatchDecision:
    """Compare one observation with one phenotype condition.

    The observation's own status decides the result whenever it is not
    ``NORMALIZED``; only a normalised phenotype is ever compared with the
    declared set. That ordering is deliberate: an unsupported value must not
    reach the comparison at all, because a comparison would have to decide
    what it is being compared *as*.
    """
    if not isinstance(observation, PhenotypeObservation):
        raise PhenotypeMatchError(
            "expected a PhenotypeObservation, got %s"
            % type(observation).__name__,
            code="PHENOTYPE_OBSERVATION_UNSUPPORTED_TYPE",
            location="$.observation")
    operator, values, condition_hash, gene_key = _declared(condition)
    gene = gene_key or observation.gene_canonical_key

    forced = observation.match_status_for_failure
    if forced:
        return MatchDecision(
            status=forced, gene_canonical_key=gene, operator=operator,
            declared_phenotypes=values, condition_hash=condition_hash,
            observation_status=observation.status,
            reason_code=observation.reason_code)

    phenotype = observation.phenotype
    # Membership in an explicitly declared tuple. There is no other test: no
    # widening, no grouping, no proximity. ``EXACT`` differs from ``ONE_OF``
    # only in how many values WP-11 permitted it to declare, which WP-11 has
    # already enforced, so the comparison itself is identical - and that is
    # why no cross-match can hide in the difference between the two branches.
    matched = phenotype in values
    return MatchDecision(
        status="MATCH" if matched else "NO_MATCH",
        gene_canonical_key=gene, operator=operator,
        declared_phenotypes=values, condition_hash=condition_hash,
        observed_phenotype=phenotype,
        observation_status=observation.status)


def match_condition(profile, condition: RuleCondition) -> MatchDecision:
    """Evaluate a profile's phenotype for the *gene named by the condition*.

    This is the only place a profile and a rule condition meet, and it meets
    them narrowly: the condition's drug is not consulted, and neither is the
    rule the condition belongs to. If the profile says nothing about the gene,
    the result is ``INPUT_MISSING`` - a rule about a gene nobody supplied a
    value for has not been shown not to apply.
    """
    if not isinstance(condition, RuleCondition):
        raise PhenotypeMatchError(
            "match_condition evaluates a WP-11 RuleCondition, got %s"
            % type(condition).__name__,
            code="PHENOTYPE_CONDITION_UNSUPPORTED_TYPE", location="$.condition")
    observation = profile.observation_for(condition.gene_canonical_key)
    if observation is None:
        return MatchDecision(
            status="INPUT_MISSING",
            gene_canonical_key=condition.gene_canonical_key,
            operator=condition.phenotype.operator,
            declared_phenotypes=condition.phenotype.values,
            condition_hash=condition.content_hash(),
            observation_status="ABSENT", reason_code=_GENE_ABSENT)
    return match_observation(observation, condition)


def truth_matrix() -> Tuple[dict, ...]:
    """Every determinate phenotype against every ``EXACT`` rule phenotype.

    Returned as data rather than printed, so the CLI, the tests and the
    documentation all read the same table instead of three descriptions of it.
    The expected answer is equality and nothing else, which is what makes the
    table worth publishing: it is thirty rows of "no", five of "yes", and no
    row anybody has to reason about.
    """
    from pgx.rules.conditions import RULE_PHENOTYPES
    rows = []
    for observed in Phenotype:
        for declared in RULE_PHENOTYPES:
            expected = "MATCH" if observed is declared else "NO_MATCH"
            if observed is Phenotype.INDETERMINATE:
                expected = "INPUT_INDETERMINATE"
            rows.append({
                "observed": observed.value,
                "operator": "EXACT",
                "declared": [declared.value],
                "expected_status": expected,
            })
    return tuple(rows)
