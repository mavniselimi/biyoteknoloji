# -*- coding: utf-8 -*-
"""Build the core candidate interpretations and ruleset (WP-C07, WP-C08).

Reads the Wave 3 source grounding and the sealed Wave 3B capture, and produces
core objects: :class:`pgx.curation.candidate.CandidateInterpretation` and
:class:`pgx.rules.candidate.CandidateRuleDefinition`. Nothing here evaluates
anything; the evaluator is the application service.

Two scope decisions are enforced here rather than documented elsewhere.

**Clopidogrel requires an explicit care setting.** The guideline's Table 1
carries two independent classification columns, ACS/PCI and non-ACS/non-PCI,
and answers them differently. The transcription covers the ACS/PCI column only,
so every clopidogrel rule is tagged with that care setting and the application
refuses a clopidogrel assessment that does not declare one. The setting is
never inferred from the drug name - a patient taking clopidogrel is not
thereby in an ACS or PCI setting, and assuming so is precisely the leap this
tag exists to prevent.

**Amitriptyline is one joint rule family, not two single-gene families.** The
guideline states it as a CYP2C19 x CYP2D6 matrix that is not the pointwise
combination of its two single-gene tables. The single-gene amitriptyline rows
are still curated - they are what the source says - but no single-gene
amitriptyline *rule* is emitted, because a ruleset containing both would let a
one-gene answer be produced for a two-gene question.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from pgx.domain.authority import CandidateAuthorityState
from pgx.closure.candidate_curation import (CURATIONS,
                                            attention_for_recommendation)
from pgx.closure.candidate_ruleset import REFUSALS
from pgx.closure.source_grounding import RETRIEVALS
from pgx.closure.source_rows import AMITRIPTYLINE_JOINT_ROWS
from pgx.curation.candidate import CandidateInterpretation
from pgx.domain.enums import Phenotype
from pgx.normalization.models import EntityType, canonical_key_for
from pgx.rules.candidate import (CandidateProvenance, CandidateRuleDefinition,
                                 CandidateRuleset)
from pgx.rules.conditions import (GeneRequirement, JointRuleCondition,
                                  PhenotypeMatch, RuleCondition)
from pgx.rules.models import RuleOutcome

__all__ = [
    "CARE_SETTING_ACS_PCI",
    "CARE_SETTING_REQUIRED_DRUGS",
    "CURATED_BY",
    "JOINT_DRUGS",
    "build_candidate_interpretations",
    "build_core_candidate_ruleset",
]

CURATED_BY = ("pgx-closure-wave03b automated curation pass "
              "(NOT A HUMAN CURATOR)")

#: The one care setting the first release transcribed evidence for.
CARE_SETTING_ACS_PCI = "ACS_OR_PCI"

#: Drugs whose rules apply only inside a declared care setting.
CARE_SETTING_REQUIRED_DRUGS: Mapping[str, Tuple[str, ...]] = {
    "DRUG:clopidogrel": (CARE_SETTING_ACS_PCI,),
}

#: Drugs represented by a joint condition rather than by single-gene rules.
JOINT_DRUGS: Tuple[str, ...] = ("DRUG:amitriptyline",)


def _retrieval(key: str):
    for item in RETRIEVALS:
        if item.retrieval_key == key:
            return item
    raise KeyError(key)


def build_candidate_interpretations() -> Tuple[CandidateInterpretation, ...]:
    """One provisional interpretation per representable curated source row."""
    built: List[CandidateInterpretation] = []
    for item in CURATIONS:
        retrieval = _retrieval(item.retrieval_key)
        gene_key = canonical_key_for(EntityType.GENE, item.gene)
        drug_key = canonical_key_for(EntityType.DRUG, item.drug)
        built.append(CandidateInterpretation(
            interpretation_key="CANDIDATE-INTERP:%s|%s|%s"
                               % (item.drug, item.gene, item.phenotype.value),
            gene_canonical_key=gene_key,
            drug_canonical_key=drug_key,
            phenotype=item.phenotype,
            context=item.context,
            rationale=item.rationale,
            source_recommendation=item.source_recommendation,
            source_classification=item.source_classification,
            capture_record_id="capture:row:%s|%s|%s|%s"
                              % (item.gene, item.drug,
                                 _source_phenotype_label(item), item.context),
            annotation_id=retrieval.annotation_id,
            citation="PMID %s, DOI %s" % (retrieval.pmid, retrieval.doi),
            curated_by=CURATED_BY))
    keys = [item.interpretation_key for item in built]
    if len(set(keys)) != len(keys):
        raise ValueError("two interpretations share one key")
    return tuple(built)


def _source_phenotype_label(curation) -> str:
    """The exact source label the curation came from.

    Reconstructed by looking it back up rather than being remembered, so a
    capture record id that does not exist is an error here instead of a
    dangling reference in a rule's provenance.
    """
    from pgx.closure.source_rows import ROWS
    for row in ROWS:
        if row.gene == curation.gene and row.drug == curation.drug \
                and row.project_phenotype is curation.phenotype \
                and row.context == curation.context:
            return row.source_phenotype
    raise KeyError("no source row for %s" % curation.curation_key)


def _provenance(*, interpretation: CandidateInterpretation,
                extra_interpretations: Sequence[CandidateInterpretation] = (),
                context: Mapping[str, Any]) -> CandidateProvenance:
    members = (interpretation,) + tuple(extra_interpretations)
    return CandidateProvenance(
        interpretation_key=interpretation.interpretation_key,
        interpretation_content_hash=interpretation.content_hash(),
        dataset_public_id=context["dataset_public_id"],
        canonical_build_key=context["canonical_build_key"],
        canonical_build_content_hash=context["canonical_build_content_hash"],
        capture_snapshot_manifest_hash=context["snapshot_manifest_hash"],
        capture_record_ids=tuple(item.capture_record_id for item in members),
        source_annotation_ids=tuple(item.annotation_id for item in members),
        citations=tuple(item.citation for item in members),
        source_policy_status=context["source_policy_status"],
        source_policy_content_hash=context["source_policy_content_hash"],
        dq_decision_id=context["dq_decision_id"])


def _phenotype_match(values: Sequence[Phenotype]) -> PhenotypeMatch:
    ordered = tuple(values)
    return PhenotypeMatch(
        operator="EXACT" if len(ordered) == 1 else "ONE_OF", values=ordered)


def _joint_groups() -> Tuple[Tuple[Tuple[Phenotype, ...],
                                   Tuple[Phenotype, ...], str, str], ...]:
    """The amitriptyline matrix, grouped into the fewest honest rules.

    Cells in one CYP2C19 row that state the *same* recommendation with the
    *same* classification become one rule whose CYP2D6 axis is a ``ONE_OF``
    listing both phenotypes explicitly. That is the grammar's own mechanism for
    "this applies to both", and it lists both names where a reviewer can see
    them - unlike a wildcard, which the grammar refuses.

    Cells that state different recommendations stay separate rules, however
    similar they look.
    """
    grouped: Dict[Tuple[Tuple[Phenotype, ...], str, str],
                  List[Phenotype]] = {}
    order: List[Tuple[Tuple[Phenotype, ...], str, str]] = []
    for cell in AMITRIPTYLINE_JOINT_ROWS:
        d6 = cell.cyp2d6_member()
        c19 = cell.cyp2c19_members()
        if d6 is None or not c19:
            continue
        key = (tuple(c19), cell.recommendation_verbatim, cell.classification)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(d6)
    return tuple((key[0], tuple(grouped[key]), key[1], key[2])
                 for key in order)


def build_core_candidate_ruleset(context: Mapping[str, Any]
                                 ) -> CandidateRuleset:
    """Freeze the core candidate ruleset from the curated interpretations.

    ``context`` carries the identifiers and hashes every rule's provenance
    pins: the dataset, the capture snapshot, the source policy and the
    data-quality decision. Passed in rather than read here, so a ruleset can
    never be built against artifacts the caller did not actually check.
    """
    interpretations = {item.interpretation_key: item
                       for item in build_candidate_interpretations()}
    by_axis: Dict[Tuple[str, str, Phenotype], CandidateInterpretation] = {}
    for item in interpretations.values():
        by_axis[(item.gene_canonical_key, item.drug_canonical_key,
                 item.phenotype)] = item

    rules: List[CandidateRuleDefinition] = []

    # -- single-gene drugs ---------------------------------------------------
    for item in sorted(interpretations.values(),
                       key=lambda x: x.interpretation_key):
        if item.drug_canonical_key in JOINT_DRUGS:
            continue
        condition = RuleCondition(
            gene_canonical_key=item.gene_canonical_key,
            drug_canonical_key=item.drug_canonical_key,
            phenotype=_phenotype_match((item.phenotype,)))
        level, _reason = attention_for_recommendation(
            item.source_recommendation)
        rules.append(CandidateRuleDefinition(
            rule_key="CANDIDATE-RULE:%s" % item.interpretation_key.split(
                ":", 1)[1],
            condition=condition,
            outcome=RuleOutcome(
                attention_level=level,
                rationale_reference=item.interpretation_key),
            provenance=_provenance(interpretation=item, context=context),
            care_setting=(CARE_SETTING_ACS_PCI
                          if item.drug_canonical_key
                          in CARE_SETTING_REQUIRED_DRUGS else None)))

    # -- amitriptyline, as one joint family ---------------------------------
    drug_key = canonical_key_for(EntityType.DRUG, "amitriptyline")
    c19_key = canonical_key_for(EntityType.GENE, "CYP2C19")
    d6_key = canonical_key_for(EntityType.GENE, "CYP2D6")
    for index, (c19_values, d6_values, recommendation, classification) in \
            enumerate(_joint_groups(), 1):
        level, _reason = attention_for_recommendation(recommendation)
        # Provenance cites the single-gene interpretations for both axes: they
        # are what this project actually read and curated, and a joint rule
        # that cited nothing would be untraceable.
        members = [by_axis[(c19_key, drug_key, value)] for value in c19_values]
        members += [by_axis[(d6_key, drug_key, value)] for value in d6_values]
        rules.append(CandidateRuleDefinition(
            rule_key="CANDIDATE-RULE:amitriptyline|JOINT|%02d" % index,
            condition=JointRuleCondition(
                genes=(GeneRequirement(c19_key, _phenotype_match(c19_values)),
                       GeneRequirement(d6_key, _phenotype_match(d6_values))),
                drug_canonical_key=drug_key),
            outcome=RuleOutcome(
                attention_level=level,
                rationale_reference=("CPIC tricyclic antidepressant guideline "
                                     "Table 4, joint CYP2C19 x CYP2D6 cell: "
                                     + recommendation)),
            provenance=_provenance(interpretation=members[0],
                                   extra_interpretations=members[1:],
                                   context=context)))

    expected_scope = {
        "DRUG:amitriptyline": (c19_key, d6_key),
        "DRUG:clopidogrel": (c19_key,),
        "DRUG:codeine": (d6_key,),
        "DRUG:omeprazole": (c19_key,),
    }

    ruleset = CandidateRuleset(
        ruleset_key="PGX-CANDIDATE-RULESET-WAVE03B",
        rules=tuple(rules),
        refusals=tuple(item.to_json() for item in REFUSALS),
        expected_gene_scope=expected_scope,
        care_setting_required=dict(CARE_SETTING_REQUIRED_DRUGS),
        built_by=CURATED_BY)

    _verify(ruleset, expected_scope)
    return ruleset


def _verify(ruleset: CandidateRuleset,
            expected_scope: Mapping[str, Tuple[str, ...]]) -> None:
    """Refuse to hand back a ruleset that could answer a question wrongly."""
    joint_drugs = {rule.drug_canonical_key for rule in ruleset.rules
                   if rule.is_joint}
    for rule in ruleset.rules:
        if rule.is_joint or rule.drug_canonical_key not in joint_drugs:
            continue
        raise ValueError(
            "refusing to freeze: %s carries both a joint rule and the "
            "single-gene rule %s. A ruleset holding both would let a one-gene "
            "answer be produced for a two-gene question."
            % (rule.drug_canonical_key, rule.rule_key))

    for drug, genes in sorted(expected_scope.items()):
        covered = {key for rule in ruleset.rules_for(drug)
                   for key in rule.gene_keys}
        if covered != set(genes):
            raise ValueError(
                "refusing to freeze: %s declares expected genes %s but its "
                "rules cover %s" % (drug, sorted(genes), sorted(covered)))

    for drug in CARE_SETTING_REQUIRED_DRUGS:
        for rule in ruleset.rules_for(drug):
            if rule.care_setting is None:
                raise ValueError(
                    "refusing to freeze: %s requires a care setting but rule "
                    "%s declares none" % (drug, rule.rule_key))

    # No two rules may match the same observation for the same drug.
    for drug in sorted({rule.drug_canonical_key for rule in ruleset.rules}):
        seen: Dict[str, str] = {}
        for rule in ruleset.rules_for(drug):
            for combination in _combinations(rule):
                signature = "|".join(
                    "%s=%s" % pair for pair in sorted(combination.items()))
                if signature in seen:
                    raise ValueError(
                        "refusing to freeze: rules %s and %s both match %s "
                        "for %s; this engine will not pick between two rules"
                        % (seen[signature], rule.rule_key, signature, drug))
                seen[signature] = rule.rule_key


def _combinations(rule: CandidateRuleDefinition
                  ) -> Tuple[Dict[str, str], ...]:
    import itertools
    if rule.is_joint:
        per_gene = [[(item.gene_canonical_key, value.value)
                     for value in item.phenotype.values]
                    for item in rule.condition.genes]
    else:
        per_gene = [[(rule.condition.gene_canonical_key, value.value)
                     for value in rule.condition.phenotype.values]]
    return tuple(dict(pairs) for pairs in itertools.product(*per_gene))
