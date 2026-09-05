# -*- coding: utf-8 -*-
"""Immutable values the assessment engine produces (WP-14).

Three levels - finding, medication, computation - plus the attention
aggregation table they share.

**Attention is a table, not a number.** ``AttentionLevel`` has no ordering and
must never acquire one. ``ATTENTION_PRECEDENCE`` is an explicitly written
tuple, and ``NOT_ASSESSED`` is deliberately absent from it: it means *we did
not look*, which is not a magnitude and cannot be compared with ``LOW``.
Selecting a maximum over a list that included it would silently decide that
not looking ranks somewhere, and every possible answer to "where" is wrong.

**A finding is a calculated fact with its whole chain attached.** Rule
identity, version, content hash, the rationale reference, the evidence, and
the artifacts it was computed against. A finding that cannot name them is not
a weaker finding; it is not a finding (``SAFETY-INV-006``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from pgx.domain.enums import (AttentionLevel, CoverageReasonCode,
                              CoverageStatus)
from pgx.domain.hashing import sha256_digest
from pgx.domain.immutable import freeze_json
from pgx.engine.risk_errors import AssessmentEngineError

__all__ = [
    "ATTENTION_PRECEDENCE",
    "ATTENTION_AGGREGATION_TABLE",
    "CALCULATED_ATTENTION_LEVELS",
    "CalculatedFinding",
    "FINDING_SCHEMA_VERSION",
    "MEDICATION_ASSESSMENT_SCHEMA_VERSION",
    "MedicationAssessment",
    "aggregate_attention",
    "attention_table",
]

FINDING_SCHEMA_VERSION = "pgx-assessment-finding/1"
MEDICATION_ASSESSMENT_SCHEMA_VERSION = "pgx-medication-assessment/1"

#: The order a maximum is selected in. Written out rather than derived, and
#: read top to bottom: the first level present wins.
#:
#: ``NOT_ASSESSED`` is not here, and its absence is the specification. It is
#: excluded from every maximum, so a medication with one HIGH finding and one
#: unassessed axis is HIGH *with PARTIAL coverage beside it* - never HIGH
#: because absence lost a comparison, and never NOT_ASSESSED because absence
#: won one.
ATTENTION_PRECEDENCE: Tuple[AttentionLevel, ...] = (
    AttentionLevel.HIGH,
    AttentionLevel.MEDIUM,
    AttentionLevel.LOW,
    AttentionLevel.NO_ACTIVE_ATTENTION,
)

#: Levels a validated rule may produce. Identical to WP-11's
#: ``RULE_OUTCOME_LEVELS`` by construction, restated here as the engine's own
#: precondition so a change on either side is a visible disagreement.
CALCULATED_ATTENTION_LEVELS: Tuple[AttentionLevel, ...] = ATTENTION_PRECEDENCE


def _require_digest(value: Any, field_name: str) -> str:
    from pgx.domain.hashing import is_canonical_digest
    if not isinstance(value, str) or not is_canonical_digest(value):
        raise AssessmentEngineError(
            "%s must be a sha256:<hex> digest, got %r" % (field_name, value),
            code="ASSESSMENT_INPUT_INVALID", location="$." + field_name)
    return value


def aggregate_attention(levels: Sequence[AttentionLevel], *,
                        coverage: CoverageStatus) -> AttentionLevel:
    """The attention for one medication or one whole assessment.

    ``levels`` are the *calculated* levels only - the ones a validated matched
    rule produced. Absence is not represented in them, because absence has no
    level; it is represented by ``coverage``.

    Two rules, and the second is the one that matters:

    1. If any calculated level is present, the answer is the first entry of
       ``ATTENTION_PRECEDENCE`` that appears among them. Coverage does not
       weaken it: a real finding on a covered axis survives beside an axis
       nobody could evaluate, and the incompleteness is reported as coverage
       rather than by lowering the level.
    2. If none is present, the answer is ``NO_ACTIVE_ATTENTION`` when coverage
       is ``FULL`` and ``NOT_ASSESSED`` otherwise. That is the whole of
       ``SAFETY-INV-001`` in one branch: *we looked and found nothing* and *we
       did not look* are different answers, and only the first is reassuring.
    """
    if not isinstance(coverage, CoverageStatus):
        raise AssessmentEngineError(
            "coverage must be a CoverageStatus", code="ASSESSMENT_INPUT_INVALID",
            location="$.coverage")
    present = []
    for level in levels:
        if not isinstance(level, AttentionLevel):
            raise AssessmentEngineError(
                "attention levels are AttentionLevel members, got %r" % (level,),
                code="ASSESSMENT_INPUT_INVALID", location="$.levels")
        if level is AttentionLevel.NOT_ASSESSED:
            raise AssessmentEngineError(
                "NOT_ASSESSED is not a calculated level and may not enter an "
                "aggregation. It means 'we did not look', which has no place "
                "in a maximum over things that were looked at.",
                code="ASSESSMENT_INPUT_INVALID", location="$.levels")
        present.append(level)
    for level in ATTENTION_PRECEDENCE:
        if level in present:
            return level
    if coverage is CoverageStatus.FULL:
        return AttentionLevel.NO_ACTIVE_ATTENTION
    return AttentionLevel.NOT_ASSESSED


#: Every row of the aggregation rule, as data, so the CLI, the tests and the
#: documentation read one table instead of three descriptions of it.
ATTENTION_AGGREGATION_TABLE: Tuple[Mapping[str, Any], ...] = (
    {"case": "calculated_findings_present",
     "when": "at least one validated matched rule produced a level",
     "coverage": "any",
     "result": "the first level in ATTENTION_PRECEDENCE that is present",
     "note": "coverage never lowers a calculated level; incompleteness is "
             "reported as coverage, beside it"},
    {"case": "no_finding_full_coverage",
     "when": "no calculated level, and coverage is FULL",
     "coverage": CoverageStatus.FULL.value,
     "result": AttentionLevel.NO_ACTIVE_ATTENTION.value,
     "note": "the only path to a reassuring answer: everything expected was "
             "evaluated and nothing was found"},
    {"case": "no_finding_partial_coverage",
     "when": "no calculated level, and coverage is PARTIAL",
     "coverage": CoverageStatus.PARTIAL.value,
     "result": AttentionLevel.NOT_ASSESSED.value,
     "note": "some axes were evaluated and produced nothing, others were not "
             "evaluated at all; the second fact governs"},
    {"case": "no_finding_insufficient",
     "when": "no calculated level, and coverage is INSUFFICIENT",
     "coverage": CoverageStatus.INSUFFICIENT.value,
     "result": AttentionLevel.NOT_ASSESSED.value,
     "note": "nothing was evaluated"},
    {"case": "no_finding_unsupported_drug",
     "when": "no calculated level, and the dataset lacks the drug",
     "coverage": CoverageStatus.UNSUPPORTED_DRUG.value,
     "result": AttentionLevel.NOT_ASSESSED.value,
     "note": "recognition is not coverage, and absence is not reassurance"},
    {"case": "no_finding_unsupported_phenotype",
     "when": "no calculated level, and the phenotype could not be used",
     "coverage": CoverageStatus.UNSUPPORTED_PHENOTYPE.value,
     "result": AttentionLevel.NOT_ASSESSED.value,
     "note": "a value was supplied and could not be read"},
    {"case": "no_finding_source_conflict",
     "when": "no calculated level, and validated sources disagree",
     "coverage": CoverageStatus.SOURCE_CONFLICT.value,
     "result": AttentionLevel.NOT_ASSESSED.value,
     "note": "a disagreement is not resolved by reporting the absence of a "
             "finding as an absence of concern (SAFETY-INV-008)"},
)


def attention_table() -> Dict[str, Any]:
    """The aggregation rule as one published document."""
    return {
        "precedence": [level.value for level in ATTENTION_PRECEDENCE],
        "excluded_from_maximum": [AttentionLevel.NOT_ASSESSED.value],
        "rows": [dict(row) for row in ATTENTION_AGGREGATION_TABLE],
        "note": (
            "The precedence tuple is read top to bottom and the first level "
            "present wins. No level is compared with another: AttentionLevel "
            "has no ordering and NOT_ASSESSED is excluded from the comparison "
            "entirely, because it is not a magnitude. NO_ACTIVE_ATTENTION is "
            "reachable only from FULL coverage; every other absence path "
            "terminates in NOT_ASSESSED (SAFETY-INV-001)."),
    }


@dataclass(frozen=True, slots=True)
class CalculatedFinding:
    """One attention level, calculated on one covered axis, fully traceable.

    Every field but the two scientific codes is required, and the two codes
    are optional because the governed rule outcome does not carry them: WP-11
    approves an attention level and a ``rationale_reference``, and inventing
    an effect code to fill the gap would manufacture a reviewed-looking claim
    nobody reviewed. Their absence is the honest value.
    """

    drug_canonical_key: str
    gene_canonical_key: str
    phenotype: Any
    attention_level: AttentionLevel
    rule_id: str
    rule_family_id: str
    rule_version: int
    rule_content_hash: str
    rationale_reference: str
    evidence_references: Tuple[str, ...]
    curation_revision_id: str
    curation_revision_hash: str
    ruleset_public_id: str
    ruleset_content_hash: str
    dataset_public_id: str
    canonical_build_content_hash: str
    coverage_manifest_hash: str
    effect_code: Optional[str] = None
    explanation_code: Optional[str] = None
    finding_schema_version: str = FINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.attention_level, AttentionLevel):
            raise AssessmentEngineError(
                "attention_level must be an AttentionLevel",
                code="ASSESSMENT_INPUT_INVALID", location="$.attention_level")
        if self.attention_level is AttentionLevel.NOT_ASSESSED:
            raise AssessmentEngineError(
                "a finding is a calculated result and cannot be "
                "NOT_ASSESSED; absence is expressed as coverage, not as a "
                "finding that says nothing",
                code="ASSESSMENT_INPUT_INVALID", location="$.attention_level")
        if self.attention_level not in CALCULATED_ATTENTION_LEVELS:
            raise AssessmentEngineError(
                "%s may not be authored by a rule" % self.attention_level.value,
                code="ASSESSMENT_INPUT_INVALID", location="$.attention_level")
        for name in ("drug_canonical_key", "gene_canonical_key", "rule_id",
                     "rule_family_id", "rationale_reference",
                     "curation_revision_id", "ruleset_public_id",
                     "dataset_public_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise AssessmentEngineError(
                    "%s must be a non-empty string" % name,
                    code="ASSESSMENT_INPUT_INVALID", location="$." + name)
        for name in ("rule_content_hash", "curation_revision_hash",
                     "ruleset_content_hash", "canonical_build_content_hash",
                     "coverage_manifest_hash"):
            _require_digest(getattr(self, name), name)
        if not isinstance(self.rule_version, int) or \
                isinstance(self.rule_version, bool) or self.rule_version < 1:
            raise AssessmentEngineError(
                "rule_version counts from 1", code="ASSESSMENT_INPUT_INVALID",
                location="$.rule_version")
        if not self.evidence_references:
            raise AssessmentEngineError(
                "every calculated finding cites at least one evidence record "
                "(SAFETY-INV-006). A conclusion whose evidence cannot be "
                "retrieved is not one anybody can check.",
                code="ASSESSMENT_EVIDENCE_MISSING",
                location="$.evidence_references")
        object.__setattr__(self, "evidence_references",
                           tuple(sorted(set(self.evidence_references))))
        for name in ("effect_code", "explanation_code"):
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, str) or not value.strip():
                raise AssessmentEngineError(
                    "%s is optional; a supplied one must be non-empty" % name,
                    code="ASSESSMENT_INPUT_INVALID", location="$." + name)

    @property
    def sort_key(self) -> Tuple[str, str, str]:
        return (self.drug_canonical_key, self.gene_canonical_key,
                self.phenotype.value)

    def to_json(self) -> Dict[str, Any]:
        return {
            "finding_schema_version": self.finding_schema_version,
            "drug_id": self.drug_canonical_key,
            "gene_id": self.gene_canonical_key,
            "phenotype": self.phenotype.value,
            "attention_level": self.attention_level.value,
            "rule_id": self.rule_id,
            "rule_family_id": self.rule_family_id,
            "rule_version": self.rule_version,
            "rule_content_hash": self.rule_content_hash,
            "rationale_reference": self.rationale_reference,
            "evidence_references": list(self.evidence_references),
            "curation_revision_id": self.curation_revision_id,
            "curation_revision_hash": self.curation_revision_hash,
            "ruleset_public_id": self.ruleset_public_id,
            "ruleset_content_hash": self.ruleset_content_hash,
            "dataset_public_id": self.dataset_public_id,
            "canonical_build_content_hash": self.canonical_build_content_hash,
            "coverage_manifest_hash": self.coverage_manifest_hash,
            "effect_code": self.effect_code,
            "explanation_code": self.explanation_code,
        }

    def content_hash(self) -> str:
        return sha256_digest(self.to_json())


@dataclass(frozen=True, slots=True)
class MedicationAssessment:
    """What was calculated for one requested medication, and what was not.

    Carries the WP-13 coverage verbatim beside the calculated attention. The
    two are separate first-class outputs and neither is derived from the
    other: a reader who sees ``HIGH`` must also see ``PARTIAL``, because
    "the worst of what we could evaluate" and "how much we could evaluate"
    are different facts and one is not a summary of the other.
    """

    drug_canonical_key: str
    requested_value: str
    attention_level: AttentionLevel
    coverage_status: CoverageStatus
    coverage_reason_codes: Tuple[CoverageReasonCode, ...]
    findings: Tuple[CalculatedFinding, ...] = ()
    axis_count: int = 0
    conflicted_axis_count: int = 0
    medication_assessment_schema_version: str = \
        MEDICATION_ASSESSMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.attention_level, AttentionLevel):
            raise AssessmentEngineError(
                "attention_level must be an AttentionLevel",
                code="ASSESSMENT_INPUT_INVALID", location="$.attention_level")
        if not isinstance(self.coverage_status, CoverageStatus):
            raise AssessmentEngineError(
                "coverage_status must be a CoverageStatus",
                code="ASSESSMENT_INPUT_INVALID", location="$.coverage_status")
        object.__setattr__(
            self, "findings",
            tuple(sorted(self.findings, key=lambda item: item.sort_key)))
        # SAFETY-INV-001, enforced in the type so a caller assembling one by
        # hand meets the same rule the engine does.
        if self.attention_level is AttentionLevel.NO_ACTIVE_ATTENTION and \
                self.coverage_status is not CoverageStatus.FULL:
            raise AssessmentEngineError(
                "NO_ACTIVE_ATTENTION requires FULL coverage; coverage %s means "
                "something was not evaluated, and reporting that as 'no active "
                "attention' is the false-reassurance failure this system exists "
                "to prevent" % self.coverage_status.value,
                code="ASSESSMENT_INPUT_INVALID", location="$.attention_level")
        if self.attention_level is AttentionLevel.NOT_ASSESSED and self.findings:
            raise AssessmentEngineError(
                "a medication with a calculated finding is not NOT_ASSESSED; "
                "the finding would be invisible behind a level that says "
                "nothing was looked at",
                code="ASSESSMENT_INPUT_INVALID", location="$.attention_level")
        if self.attention_level is not AttentionLevel.NOT_ASSESSED and \
                self.attention_level is not AttentionLevel.NO_ACTIVE_ATTENTION \
                and not self.findings:
            raise AssessmentEngineError(
                "attention %s is a calculated level and requires the finding "
                "that calculated it" % self.attention_level.value,
                code="ASSESSMENT_INPUT_INVALID", location="$.findings")
        if self.coverage_status is not CoverageStatus.FULL and \
                not self.coverage_reason_codes:
            raise AssessmentEngineError(
                "coverage %s requires at least one reason code"
                % self.coverage_status.value,
                code="ASSESSMENT_INPUT_INVALID",
                location="$.coverage_reason_codes")
        if self.coverage_status is CoverageStatus.FULL and \
                self.coverage_reason_codes:
            raise AssessmentEngineError(
                "FULL coverage carries no failure reason",
                code="ASSESSMENT_INPUT_INVALID",
                location="$.coverage_reason_codes")

    def to_json(self) -> Dict[str, Any]:
        return {
            "medication_assessment_schema_version":
                self.medication_assessment_schema_version,
            "drug_id": self.drug_canonical_key,
            "requested_value": self.requested_value,
            "attention_level": self.attention_level.value,
            "coverage_status": self.coverage_status.value,
            "coverage_reason_codes": [code.value
                                      for code in self.coverage_reason_codes],
            "axis_count": self.axis_count,
            "conflicted_axis_count": self.conflicted_axis_count,
            "finding_count": len(self.findings),
            "findings": [item.to_json() for item in self.findings],
        }

    def content_hash(self) -> str:
        return sha256_digest(self.to_json())
