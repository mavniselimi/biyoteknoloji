# -*- coding: utf-8 -*-
"""Coverage and attention for a candidate release (WP-C09 runtime).

This is not a second engine. It reuses this package's own models and, above
all, its own aggregation rule: :func:`pgx.engine.risk_models.aggregate_attention`
decides the answer here exactly as it does for a governed release, so the two
paths cannot drift on the one question where drifting would matter.

What it does differently is what candidate rules actually differ in:

* a candidate rule carries no WP-10 approval envelope, so
  :func:`pgx.engine.risk.evaluate_axis_finding` - which verifies one - cannot
  execute it;
* a candidate rule's condition may name two genes at once, and the governed
  axis model is keyed by a single ``(gene, drug)`` pair.

Three refusals are the whole point of the module:

**A drug whose evidence is care-setting-specific is refused without one.**
Clopidogrel's guideline answers ACS/PCI and non-ACS/non-PCI differently and
this release transcribed one column. A clopidogrel request that does not
declare its care setting gets ``NOT_ASSESSED``, never a finding.

**A joint rule needs every gene it names.** One axis missing refuses the whole
medication rather than answering from the axis that was present.

**No match is a refusal, never reassurance.** An unmatched phenotype produces
``NOT_ASSESSED`` with a reason, and never ``NO_ACTIVE_ATTENTION`` - which would
say "we looked and there is nothing" about a combination nobody encoded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.domain.enums import (AttentionLevel, CoverageReasonCode,
                              CoverageStatus, Phenotype)
from pgx.engine.risk_models import aggregate_attention

__all__ = [
    "CANDIDATE_EVALUATION_VERSION",
    "CandidateAxisResult",
    "CandidateEvaluation",
    "CandidateMedicationResult",
    "evaluate_candidate",
]

CANDIDATE_EVALUATION_VERSION = "pgx-candidate-evaluation/1"


@dataclass(frozen=True, slots=True)
class CandidateAxisResult:
    """What one rule family said about one medication, or why it did not."""

    axis_key: str
    gene_keys: Tuple[str, ...]
    status: CoverageStatus
    reason_codes: Tuple[str, ...]
    detail: str
    matched_rule_key: Optional[str] = None
    attention_level: Optional[AttentionLevel] = None
    rule_content_hash: Optional[str] = None
    interpretation_key: Optional[str] = None
    citations: Tuple[str, ...] = ()
    capture_record_ids: Tuple[str, ...] = ()
    is_joint: bool = False

    def to_json(self) -> Dict[str, Any]:
        return {
            "attention_level": (self.attention_level.value
                                if self.attention_level else None),
            "axis_key": self.axis_key,
            "capture_record_ids": list(self.capture_record_ids),
            "citations": list(self.citations),
            "detail": self.detail,
            "gene_keys": list(self.gene_keys),
            "interpretation_key": self.interpretation_key,
            "is_joint": self.is_joint,
            "matched_rule_key": self.matched_rule_key,
            "reason_codes": list(self.reason_codes),
            "rule_content_hash": self.rule_content_hash,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class CandidateMedicationResult:
    drug_canonical_key: str
    status: CoverageStatus
    attention_level: AttentionLevel
    reason_codes: Tuple[str, ...]
    axes: Tuple[CandidateAxisResult, ...]
    care_setting: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "attention_level": self.attention_level.value,
            "axes": [item.to_json() for item in self.axes],
            "care_setting": self.care_setting,
            "drug_canonical_key": self.drug_canonical_key,
            "reason_codes": list(self.reason_codes),
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    status: CoverageStatus
    attention_level: AttentionLevel
    medications: Tuple[CandidateMedicationResult, ...]
    ruleset_key: str
    ruleset_content_hash: str
    dataset_public_id: str
    release_public_id: str
    evaluation_version: str = CANDIDATE_EVALUATION_VERSION

    def to_json(self) -> Dict[str, Any]:
        return {
            "attention_level": self.attention_level.value,
            "dataset_public_id": self.dataset_public_id,
            "evaluation_version": self.evaluation_version,
            "medications": [item.to_json() for item in self.medications],
            "release_public_id": self.release_public_id,
            "ruleset_content_hash": self.ruleset_content_hash,
            "ruleset_key": self.ruleset_key,
            "status": self.status.value,
        }


def _observed(profile) -> Dict[str, Phenotype]:
    """Gene key -> phenotype, for observations that normalised to one.

    An observation whose status is not ``NORMALIZED`` contributes nothing, and
    that includes ``INDETERMINATE``: the condition grammar refuses
    ``INDETERMINATE`` as a rule phenotype, so an indeterminate input can only
    ever fail to match, which is the correct outcome and is reported as a
    refusal rather than as an absence of risk.
    """
    observed: Dict[str, Phenotype] = {}
    for item in getattr(profile, "observations", ()) or ():
        if getattr(item, "status", None) != "NORMALIZED":
            continue
        value = getattr(item, "phenotype", None)
        if isinstance(value, Phenotype) and value is not Phenotype.INDETERMINATE:
            observed[item.gene_canonical_key] = value
    return observed


def _axis_for(rules, observed: Mapping[str, Phenotype], *,
              axis_key: str) -> CandidateAxisResult:
    family = [rule for rule in rules if rule.axis_key == axis_key]
    gene_keys = family[0].gene_keys
    is_joint = family[0].is_joint

    missing = tuple(key for key in gene_keys if key not in observed)
    if missing:
        return CandidateAxisResult(
            axis_key=axis_key, gene_keys=gene_keys,
            status=CoverageStatus.INSUFFICIENT,
            reason_codes=(CoverageReasonCode.PHENOTYPE_NOT_PROVIDED.value,),
            detail=("no usable phenotype for %s. %s"
                    % (", ".join(missing),
                       "Every gene a joint rule names must be present; the "
                       "release does not answer from the axis that was."
                       if is_joint else
                       "The release does not answer an axis it cannot see.")),
            is_joint=is_joint)

    matched = [rule for rule in family if rule.matches(observed)]
    if len(matched) > 1:
        return CandidateAxisResult(
            axis_key=axis_key, gene_keys=gene_keys,
            status=CoverageStatus.SOURCE_CONFLICT,
            reason_codes=(CoverageReasonCode.VALIDATED_RULES_CONFLICT.value,),
            detail=("%d candidate rules match this observation; this engine "
                    "will not pick between them" % len(matched)),
            is_joint=is_joint)
    if not matched:
        return CandidateAxisResult(
            axis_key=axis_key, gene_keys=gene_keys,
            status=CoverageStatus.UNSUPPORTED_PHENOTYPE,
            reason_codes=(CoverageReasonCode.PHENOTYPE_NOT_SUPPORTED.value,),
            detail=("the observed phenotype combination is not one this "
                    "release encodes. That is a refusal, not a finding of no "
                    "risk: no rule was evaluated."),
            is_joint=is_joint)

    rule = matched[0]
    return CandidateAxisResult(
        axis_key=axis_key, gene_keys=gene_keys,
        status=CoverageStatus.FULL, reason_codes=(),
        detail="one candidate rule matched",
        matched_rule_key=rule.rule_key,
        attention_level=rule.outcome.attention_level,
        rule_content_hash=rule.content_hash(),
        interpretation_key=rule.provenance.interpretation_key,
        citations=rule.provenance.citations,
        capture_record_ids=rule.provenance.capture_record_ids,
        is_joint=is_joint)


def evaluate_candidate(*, ruleset, profile, medications: Sequence[str],
                       care_setting: Optional[str],
                       dataset_public_id: str,
                       release_public_id: str) -> CandidateEvaluation:
    """Evaluate one request against a frozen candidate ruleset."""
    observed = _observed(profile)
    results: List[CandidateMedicationResult] = []

    for drug in sorted(set(medications)):
        family = ruleset.rules_for(drug)
        if not family:
            results.append(CandidateMedicationResult(
                drug_canonical_key=drug,
                status=CoverageStatus.UNSUPPORTED_DRUG,
                attention_level=AttentionLevel.NOT_ASSESSED,
                reason_codes=(
                    CoverageReasonCode.DRUG_NOT_IN_CANONICAL_DATASET.value,),
                axes=()))
            continue

        required = tuple(ruleset.care_setting_required.get(drug, ()))
        if required and care_setting not in required:
            results.append(CandidateMedicationResult(
                drug_canonical_key=drug,
                status=CoverageStatus.INSUFFICIENT,
                attention_level=AttentionLevel.NOT_ASSESSED,
                reason_codes=("CARE_SETTING_NOT_DECLARED",),
                axes=(),
                care_setting=care_setting))
            continue

        axes = tuple(_axis_for(family, observed, axis_key=key)
                     for key in sorted({rule.axis_key for rule in family}))
        levels = tuple(axis.attention_level for axis in axes
                       if axis.attention_level is not None)
        if all(axis.status is CoverageStatus.FULL for axis in axes):
            status = CoverageStatus.FULL
            reasons: Tuple[str, ...] = ()
        else:
            status = CoverageStatus.INSUFFICIENT
            reasons = tuple(sorted({code for axis in axes
                                    for code in axis.reason_codes}))
        # Deliberately not "the levels we did get": a medication whose axes are
        # not all covered reports NOT_ASSESSED, because a partial answer that
        # looks whole is the failure this release exists to avoid.
        level = (aggregate_attention(levels, coverage=CoverageStatus.FULL)
                 if status is CoverageStatus.FULL and levels
                 else AttentionLevel.NOT_ASSESSED)
        results.append(CandidateMedicationResult(
            drug_canonical_key=drug, status=status, attention_level=level,
            reason_codes=reasons, axes=axes, care_setting=care_setting))

    calculated = tuple(item.attention_level for item in results
                       if item.attention_level is not AttentionLevel.NOT_ASSESSED)
    overall_status = (CoverageStatus.FULL
                      if results and all(item.status is CoverageStatus.FULL
                                         for item in results)
                      else CoverageStatus.PARTIAL if calculated
                      else CoverageStatus.INSUFFICIENT)
    overall = aggregate_attention(calculated, coverage=overall_status)

    return CandidateEvaluation(
        status=overall_status, attention_level=overall,
        medications=tuple(results), ruleset_key=ruleset.ruleset_key,
        ruleset_content_hash=ruleset.content_hash(),
        dataset_public_id=dataset_public_id,
        release_public_id=release_public_id)
