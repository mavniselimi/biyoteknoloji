# -*- coding: utf-8 -*-
"""Evaluating and bundling the candidate release (WP-C09).

The evaluator here is deliberately small and deliberately dumb: it looks up
matching candidate rules by exact canonical gene, drug and phenotype, takes
the precedence maximum of whatever it finds, and reports a refusal when it
finds nothing. It does not fall back, does not widen, and does not treat a
missing rule as a benign answer.

The last of those is the one that matters. When no candidate rule matches, the
answer is ``REFUSED`` with a reason - never ``NO_ACTIVE_ATTENTION``, which
would say *we looked and there is nothing to worry about* about a combination
nobody encoded. That is ``SAFETY-INV-001`` in the one place a candidate build
would most plausibly get it wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from pgx.closure.candidate_ruleset import CandidateRuleset
from pgx.domain.enums import AttentionLevel, Phenotype
from pgx.engine.risk_models import ATTENTION_PRECEDENCE
from pgx.normalization.models import EntityType, canonical_key_for

__all__ = [
    "EVALUATION_VERSION",
    "Evaluation",
    "evaluate",
    "not_weaker_than",
]

EVALUATION_VERSION = "pgx-wave03-candidate-evaluation/1"


@dataclass(frozen=True, slots=True)
class Evaluation:
    """What the candidate ruleset answers for one input."""

    outcome: str
    attention_level: Optional[AttentionLevel]
    matched_rule_keys: Tuple[str, ...]
    axes_without_a_rule: Tuple[str, ...]
    detail: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "attention_level": (self.attention_level.value
                                if self.attention_level else None),
            "axes_without_a_rule": list(self.axes_without_a_rule),
            "detail": self.detail,
            "matched_rule_keys": list(self.matched_rule_keys),
            "outcome": self.outcome,
        }


def not_weaker_than(observed: AttentionLevel,
                    required: AttentionLevel) -> bool:
    """Is ``observed`` at least as strong as ``required``?

    Expressed against ``ATTENTION_PRECEDENCE`` rather than by comparing the
    enum members, because the members refuse ordering on purpose and this
    function is the only place in the candidate track that is allowed to ask
    a ranking question about them.
    """
    order = list(ATTENTION_PRECEDENCE)
    return order.index(observed) <= order.index(required)


def evaluate(ruleset: CandidateRuleset, *, drug: str,
             phenotypes: Mapping[str, Phenotype]) -> Evaluation:
    """Answer one input, or refuse it.

    ``phenotypes`` maps gene symbol to phenotype. Every named gene must find a
    matching rule; one gene without a rule refuses the whole input rather than
    answering from the genes that did match, because a partial answer that
    looks like a whole one is the failure this refusal exists to prevent.
    """
    drug_key = canonical_key_for(EntityType.DRUG, drug)
    matched = []
    missing = []
    for gene, member in sorted(phenotypes.items()):
        gene_key = canonical_key_for(EntityType.GENE, gene)
        hit = None
        for rule in ruleset.rules:
            if rule.condition.gene_canonical_key != gene_key:
                continue
            if rule.condition.drug_canonical_key != drug_key:
                continue
            if member in rule.condition.phenotype.values:
                hit = rule
                break
        if hit is None:
            missing.append("%s|%s|%s" % (gene, drug, member.value))
        else:
            matched.append(hit)

    if missing:
        return Evaluation(
            outcome="REFUSED",
            attention_level=None,
            matched_rule_keys=tuple(rule.rule_key for rule in matched),
            axes_without_a_rule=tuple(missing),
            detail=("no candidate rule covers %s. The candidate release "
                    "refuses rather than answering from the axes that did "
                    "match: a partial answer presented as a whole one is "
                    "indistinguishable from a complete assessment."
                    % ", ".join(missing)))

    levels = [rule.outcome.attention_level for rule in matched]
    for level in ATTENTION_PRECEDENCE:
        if level in levels:
            return Evaluation(
                outcome="ATTENTION",
                attention_level=level,
                matched_rule_keys=tuple(rule.rule_key for rule in matched),
                axes_without_a_rule=(),
                detail=("precedence maximum over %d matched candidate rule(s)"
                        % len(matched)))
    return Evaluation(
        outcome="REFUSED", attention_level=None,
        matched_rule_keys=(), axes_without_a_rule=(),
        detail="no phenotype was supplied, so nothing was assessed")
