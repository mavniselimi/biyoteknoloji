# -*- coding: utf-8 -*-
"""A frozen candidate ruleset that nobody has approved (WP-C08).

The rules here reuse WP-11's condition grammar exactly - the same
:class:`~pgx.rules.conditions.RuleCondition`, the same
:class:`~pgx.rules.models.RuleOutcome`, the same refusal to express a wildcard,
a negation or an implicit phenotype expansion. What they do **not** reuse is
:class:`~pgx.rules.models.ComputableRuleDefinition`, and the reason is a single
field: ``RuleProvenance.approval_envelope_hash`` is a required sha256 digest,
and the envelope it names is the record of three separated people approving a
rule. Wave 3 has none. Constructing a ``ComputableRuleDefinition`` would mean
inventing that digest, which is precisely the act the execution policy forbids.

So a candidate rule is its own type with its own provenance, and the difference
is legible at the type level rather than resting on a status field somebody
could set. A candidate rule cannot be mistaken for a validated one by a caller
that forgot to check, because it is not the same class and does not fit where
one is expected.

**Fail-closed refusals are first-class.** :data:`REFUSALS` records every
(gene, drug, phenotype) the first release deliberately will not answer, with
the reason. That list is not the complement of the rules - it is built from the
source rows and the vocabulary gaps, so a phenotype that is neither ruled nor
refused is a bug the freeze catches rather than a silent gap.

**Channels.** The ruleset declares DEMO and VALIDATION and nothing else. It is
not the active production ruleset, and ``SAFETY-INV-003`` continues to mean
what it has always meant for the production path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from pgx.closure.authority import CandidateAuthorityState
from pgx.closure.candidate_curation import (CURATED_BY, CURATIONS,
                                            CandidateCuration,
                                            joint_consistency_failures)
from pgx.closure.source_rows import ROWS, UNREPRESENTABLE_REASONS
from pgx.domain.enums import AttentionLevel, Phenotype
from pgx.domain.hashing import sha256_digest
from pgx.normalization.models import EntityType, canonical_key_for
from pgx.rules.conditions import PhenotypeMatch, RuleCondition
from pgx.rules.models import RuleOutcome

__all__ = [
    "CANDIDATE_RULESET_VERSION",
    "PERMITTED_CHANNELS",
    "REFUSALS",
    "CandidateRule",
    "CandidateRuleset",
    "Refusal",
    "build_candidate_ruleset",
]

CANDIDATE_RULESET_VERSION = "pgx-wave03-candidate-ruleset/1"

#: The only channels this ruleset may execute in. Production is absent by
#: construction rather than by configuration.
PERMITTED_CHANNELS: Tuple[str, ...] = ("DEMO", "VALIDATION")


@dataclass(frozen=True, slots=True)
class Refusal:
    """A (gene, drug, phenotype) the candidate release will not answer.

    ``phenotype`` is the *source's* label, not a project member, because the
    commonest refusal is for a phenotype the project has no member for. A
    refusal keyed on a project member could not express "CYP2C19 likely poor
    metabolizer" at all, which is the case it most needs to express.
    """

    gene: str
    drug: str
    source_phenotype: str
    project_phenotype: Optional[str]
    reason_code: str
    reason: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "drug": self.drug,
            "gene": self.gene,
            "project_phenotype": self.project_phenotype,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "source_phenotype": self.source_phenotype,
        }


def _input_member_for(source_phenotype: str) -> Optional[str]:
    """The project member an *input* carrying this label would arrive as.

    Distinct from :func:`pgx.closure.source_rows.project_phenotype_for`, which
    answers a different question: which member a *rule* could be keyed on.
    ``INDETERMINATE`` is a real input the project can receive and must refuse;
    it is not a phenotype a rule can be about. Conflating the two questions is
    how "we cannot write a rule for this" turns into "this input cannot
    happen", and the input very much can.
    """
    if "indeterminate" in source_phenotype.lower():
        return Phenotype.INDETERMINATE.value
    return None


def _build_refusals() -> Tuple[Refusal, ...]:
    built = []
    for row in ROWS:
        member = row.project_phenotype
        if member is None:
            built.append(Refusal(
                gene=row.gene, drug=row.drug,
                source_phenotype=row.source_phenotype,
                project_phenotype=_input_member_for(row.source_phenotype),
                reason_code="PHENOTYPE_NOT_REPRESENTABLE",
                reason=UNREPRESENTABLE_REASONS[row.source_phenotype]))
        elif row.recommendation_verbatim == "No recommendation":
            built.append(Refusal(
                gene=row.gene, drug=row.drug,
                source_phenotype=row.source_phenotype,
                project_phenotype=member.value,
                reason_code="SOURCE_STATES_NO_RECOMMENDATION",
                reason=("the source records no recommendation for this "
                        "phenotype; encoding one would be this project's "
                        "invention rather than the guideline's finding")))

    # CYP2D6 RAPID is refused for every CYP2D6 drug in scope, and the reason is
    # not that the project cannot represent it - the project can. It is that
    # CPIC's CYP2D6 model is an activity-score model whose bands are
    # ultrarapid, normal, intermediate and poor, so no source row exists. An
    # axis absent from the evidence must not be shown as evidence-supported.
    for gene, drug in (("CYP2D6", "codeine"), ("CYP2D6", "amitriptyline")):
        built.append(Refusal(
            gene=gene, drug=drug,
            source_phenotype="(no CYP2D6 rapid metabolizer row exists)",
            project_phenotype=Phenotype.RAPID.value,
            reason_code="AXIS_ABSENT_FROM_SOURCE",
            reason=("CPIC's CYP2D6 phenotype model has no rapid metabolizer "
                    "band; the guideline table states ultrarapid, normal, "
                    "intermediate and poor only. The project's vocabulary has "
                    "a RAPID member, but using it here would present an "
                    "answer the regulator evidence does not contain")))

    # The CYP2C19 likely phenotypes have no amitriptyline row at all: the 2016
    # TCA guideline predates CPIC's likely labels. That is a different gap from
    # clopidogrel's and omeprazole's, where the row exists and cannot be
    # carried, so it is recorded with its own reason rather than folded in.
    for label in ("CYP2C19 likely intermediate metabolizer",
                  "CYP2C19 likely poor metabolizer"):
        built.append(Refusal(
            gene="CYP2C19", drug="amitriptyline",
            source_phenotype=label, project_phenotype=None,
            reason_code="SOURCE_ROW_ABSENT",
            reason=("the 2016 tricyclic antidepressant guideline predates "
                    "CPIC's likely-phenotype labels and states no row for "
                    "this phenotype; there is nothing to carry, and this "
                    "project may not extrapolate one from a neighbouring "
                    "row")))

    built.append(Refusal(
        gene="CYP2C19", drug="amitriptyline",
        source_phenotype="Indeterminate",
        project_phenotype=Phenotype.INDETERMINATE.value,
        reason_code="PHENOTYPE_NOT_REPRESENTABLE",
        reason=UNREPRESENTABLE_REASONS["Indeterminate"]))
    built.append(Refusal(
        gene="CYP2D6", drug="amitriptyline",
        source_phenotype="CYP2D6 Indeterminate",
        project_phenotype=Phenotype.INDETERMINATE.value,
        reason_code="PHENOTYPE_NOT_REPRESENTABLE",
        reason=UNREPRESENTABLE_REASONS["CYP2D6 Indeterminate"]))
    return tuple(built)


REFUSALS: Tuple[Refusal, ...] = _build_refusals()


@dataclass(frozen=True, slots=True)
class CandidateRule:
    """One candidate rule: WP-11 grammar, candidate provenance."""

    rule_key: str
    condition: RuleCondition
    outcome: RuleOutcome
    curation_key: str
    retrieval_key: str
    source_recommendation: str
    source_classification: str
    curated_by: str
    authority_state: CandidateAuthorityState
    review_state: CandidateAuthorityState

    def semantic_content(self) -> Dict[str, Any]:
        """Exactly what this rule claims. No author, no instant, no approval.

        ``curated_by`` is excluded for the same reason WP-11 excludes
        ``created_by``: the same claim made twice is the same claim. The
        authority states are *included*, because a rule that changed from a
        source-grounded decision to something else has changed what it claims
        about itself, and that must move the hash.
        """
        return {
            "authority_state": self.authority_state.value,
            "condition": self.condition.to_json(),
            "curation_key": self.curation_key,
            "outcome": self.outcome.to_json(),
            "retrieval_key": self.retrieval_key,
            "review_state": self.review_state.value,
            "rule_key": self.rule_key,
            "source_classification": self.source_classification,
            "source_recommendation": self.source_recommendation,
        }

    def content_hash(self) -> str:
        return sha256_digest(self.semantic_content())

    def to_json(self) -> Dict[str, Any]:
        payload = dict(self.semantic_content())
        payload["content_hash"] = self.content_hash()
        payload["curated_by"] = self.curated_by
        return payload


def _rule_from_curation(item: CandidateCuration) -> CandidateRule:
    condition = RuleCondition(
        gene_canonical_key=canonical_key_for(EntityType.GENE, item.gene),
        drug_canonical_key=canonical_key_for(EntityType.DRUG, item.drug),
        phenotype=PhenotypeMatch(operator="EXACT", values=(item.phenotype,)))
    outcome = RuleOutcome(
        attention_level=item.attention_level,
        rationale_reference="candidate-curation:%s" % item.curation_key)
    return CandidateRule(
        rule_key="CANDIDATE-RULE:%s" % item.curation_key,
        condition=condition,
        outcome=outcome,
        curation_key=item.curation_key,
        retrieval_key=item.retrieval_key,
        source_recommendation=item.source_recommendation,
        source_classification=item.source_classification,
        curated_by=item.curated_by,
        authority_state=item.authority_state,
        review_state=item.review_state)


@dataclass(frozen=True, slots=True)
class CandidateRuleset:
    """A frozen candidate ruleset. Frozen means the bytes; not endorsed."""

    ruleset_key: str
    rules: Tuple[CandidateRule, ...]
    refusals: Tuple[Refusal, ...]
    permitted_channels: Tuple[str, ...]
    authority_state: CandidateAuthorityState
    review_state: CandidateAuthorityState
    built_by: str
    ruleset_version: str = CANDIDATE_RULESET_VERSION

    def semantic_content(self) -> Dict[str, Any]:
        return {
            "authority_state": self.authority_state.value,
            "permitted_channels": list(self.permitted_channels),
            "refusals": [item.to_json() for item in self.refusals],
            "review_state": self.review_state.value,
            "rules": [item.semantic_content() for item in self.rules],
            "ruleset_key": self.ruleset_key,
            "ruleset_version": self.ruleset_version,
        }

    def content_hash(self) -> str:
        return sha256_digest(self.semantic_content())

    def coverage(self) -> Mapping[str, Tuple[str, ...]]:
        """Which phenotypes each (gene, drug) answers, in declaration order."""
        table: Dict[str, list] = {}
        for rule in self.rules:
            axis = "%s|%s" % (rule.condition.gene_canonical_key,
                              rule.condition.drug_canonical_key)
            for member in rule.condition.phenotype.values:
                table.setdefault(axis, []).append(member.value)
        return {key: tuple(value) for key, value in sorted(table.items())}

    def to_json(self) -> Dict[str, Any]:
        payload = dict(self.semantic_content())
        payload["built_by"] = self.built_by
        payload["content_hash"] = self.content_hash()
        payload["rules"] = [item.to_json() for item in self.rules]
        payload["coverage"] = {key: list(value)
                               for key, value in self.coverage().items()}
        return payload


def build_candidate_ruleset() -> CandidateRuleset:
    """Freeze the candidate ruleset, refusing to build if anything is unsound.

    Three refusals, checked before anything is assembled:

    1. an amitriptyline cell where combining the single-gene rules would
       understate the guideline's joint table;
    2. two rules for the same (gene, drug, phenotype);
    3. a (gene, drug, phenotype) that is neither ruled nor refused.

    The third is the one that earns its keep. A rule set and a refusal list
    maintained independently drift, and the phenotype that falls out of both is
    the one that gets answered by accident.
    """
    understating = joint_consistency_failures()
    if understating:
        raise ValueError(
            "refusing to freeze: %d amitriptyline combination(s) would be "
            "understated by combining the single-gene rules: %s"
            % (len(understating),
               ", ".join("%s+%s" % (c.cyp2c19_phenotype.value,
                                    c.cyp2d6_phenotype.value)
                         for c in understating)))

    rules = tuple(_rule_from_curation(item) for item in CURATIONS)
    keys = [rule.rule_key for rule in rules]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate candidate rule keys")

    ruled = {(item.gene, item.drug, item.phenotype.value)
             for item in CURATIONS}
    refused = {(item.gene, item.drug, item.project_phenotype)
               for item in REFUSALS}
    refused_labels = {(item.gene, item.drug, item.source_phenotype)
                      for item in REFUSALS}
    for gene, drug in sorted({(item.gene, item.drug) for item in CURATIONS}):
        for member in Phenotype:
            triple = (gene, drug, member.value)
            if triple in ruled or triple in refused:
                continue
            raise ValueError(
                "refusing to freeze: %s / %s / %s is neither ruled nor "
                "refused. Every phenotype in scope must have an explicit "
                "answer or an explicit refusal."
                % (gene, drug, member.value))
    if not refused_labels:
        raise ValueError("refusing to freeze: an empty refusal list means "
                         "nothing was found to be out of reach, which has "
                         "not been true of any real guideline")

    return CandidateRuleset(
        ruleset_key="PGX-CANDIDATE-RULESET-WAVE03",
        rules=rules,
        refusals=REFUSALS,
        permitted_channels=PERMITTED_CHANNELS,
        authority_state=CandidateAuthorityState.INTERNAL_VALIDATION,
        review_state=CandidateAuthorityState.PENDING_EXTERNAL_EXPERT_REVIEW,
        built_by=CURATED_BY)
