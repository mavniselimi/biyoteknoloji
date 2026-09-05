# -*- coding: utf-8 -*-
"""Immutable values the coverage engine produces (WP-13).

Three levels of result - axis, medication, overall - plus the medication
reference that enters one. All are frozen dataclasses with canonical JSON
forms and deterministic hashes.

**What is absent is the specification.** No field here holds an attention
level, a risk score, a severity, a dose, a recommendation, a preference, a
suitability score or a treatment, and a test asserts each of those names
against every dataclass in this module. Coverage and attention are separate
first-class outputs (`architecture.md` 9.2, 9.3); WP-13 computes exactly one
of them, and the strongest way to guarantee it never emits the other is to
have nowhere to put it.

``CoverageStatus`` and ``CoverageReasonCode`` come from ``pgx.domain.enums``
unchanged. Neither acquires an ordering here: a numeric severity would make
``max()`` look like a reasonable way to aggregate, and aggregation is a
decision table precisely because it is not a comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

from pgx.domain.enums import CoverageReasonCode, CoverageStatus, Phenotype
from pgx.domain.hashing import sha256_digest
from pgx.domain.immutable import EMPTY_MAPPING, freeze_json
from pgx.engine.coverage_errors import CoverageEngineError, CoverageInputError

__all__ = [
    "AXIS_COVERAGE_SCHEMA_VERSION",
    "COVERAGE_RESULT_SCHEMA_VERSION",
    "MEDICATION_COVERAGE_SCHEMA_VERSION",
    "MEDICATION_REFERENCE_STATES",
    "REASON_CODE_ORDER",
    "AxisCoverage",
    "CoverageResult",
    "MedicationCoverage",
    "MedicationReference",
    "SourceConflictSignal",
    "order_reasons",
]

AXIS_COVERAGE_SCHEMA_VERSION = "pgx-axis-coverage/1"
MEDICATION_COVERAGE_SCHEMA_VERSION = "pgx-medication-coverage/1"
COVERAGE_RESULT_SCHEMA_VERSION = "pgx-coverage-result/1"

#: The order reason codes are reported in. Declared explicitly, and
#: deliberately **not** a severity ranking: it exists so that two runs
#: producing the same set of reasons produce the same sequence, and for no
#: other purpose. Nothing reads a code's position to decide anything.
REASON_CODE_ORDER: Tuple[CoverageReasonCode, ...] = (
    CoverageReasonCode.DATASET_RULESET_MISMATCH,
    CoverageReasonCode.VALIDATED_RULES_CONFLICT,
    CoverageReasonCode.DRUG_NOT_IN_CANONICAL_DATASET,
    CoverageReasonCode.PHENOTYPE_NOT_PROVIDED,
    CoverageReasonCode.PHENOTYPE_NOT_SUPPORTED,
    CoverageReasonCode.NO_VALIDATED_RULE_FOR_AXIS,
    CoverageReasonCode.EVIDENCE_REFERENCE_MISSING,
    CoverageReasonCode.SOME_AXES_NOT_COVERED,
)

#: What a requested medication turned out to be. ``RECOGNIZED`` means only
#: that the pinned canonical dataset contains the drug - it says nothing about
#: whether anything can be evaluated for it (``architecture.md`` 6.2).
MEDICATION_REFERENCE_STATES: Tuple[str, ...] = (
    "RECOGNIZED", "NOT_IN_CANONICAL_DATASET", "INVALID")


def order_reasons(codes) -> Tuple[CoverageReasonCode, ...]:
    """Deduplicate and order reason codes deterministically."""
    seen = []
    for code in codes:
        if not isinstance(code, CoverageReasonCode):
            raise CoverageEngineError(
                "reason codes are CoverageReasonCode members, got %r" % (code,),
                code="COVERAGE_REASON_UNKNOWN")
        if code not in seen:
            seen.append(code)
    index = {code: position for position, code in enumerate(REASON_CODE_ORDER)}
    return tuple(sorted(seen, key=lambda item: index[item]))


def _require_digest(value: Any, field_name: str) -> str:
    from pgx.domain.hashing import is_canonical_digest
    if not isinstance(value, str) or not is_canonical_digest(value):
        raise CoverageEngineError(
            "%s must be a sha256:<hex> digest, got %r" % (field_name, value),
            code="COVERAGE_DIGEST_INVALID", location="$." + field_name)
    return value


@dataclass(frozen=True, slots=True)
class MedicationReference:
    """One requested medication, and what the pinned catalogue made of it.

    The engine does not normalise free-text aliases: resolving "Plavix" to a
    canonical drug is WP-07's job and a caller's responsibility to have done.
    What is recorded here is the outcome of looking the supplied canonical key
    up in the pinned catalogue, which is a lookup, not an interpretation.
    """

    requested_value: str
    state: str
    drug_canonical_key: Optional[str] = None
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        if self.state not in MEDICATION_REFERENCE_STATES:
            raise CoverageInputError(
                "medication state must be one of %s, got %r"
                % (", ".join(MEDICATION_REFERENCE_STATES), self.state),
                code="COVERAGE_MEDICATION_STATE_UNKNOWN", location="$.state")
        if self.state == "INVALID" and self.drug_canonical_key is not None:
            raise CoverageInputError(
                "an INVALID medication reference names no canonical drug",
                code="COVERAGE_MEDICATION_INCONSISTENT",
                location="$.drug_canonical_key")
        if self.state != "INVALID" and not self.drug_canonical_key:
            raise CoverageInputError(
                "a %s medication reference names the canonical key it was "
                "looked up under" % self.state,
                code="COVERAGE_MEDICATION_INCONSISTENT",
                location="$.drug_canonical_key")

    @property
    def is_recognized(self) -> bool:
        """True only when the pinned catalogue contains this drug.

        Recognition is not coverage. It is the precondition for asking the
        coverage question at all.
        """
        return self.state == "RECOGNIZED"

    def to_json(self) -> Dict[str, Any]:
        return {
            "requested_value": self.requested_value,
            "state": self.state,
            "drug_id": self.drug_canonical_key,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class SourceConflictSignal:
    """An unresolved disagreement about one axis, supplied by the caller.

    WP-13 does not detect conflicts and does not resolve them. It is told that
    one exists, and its whole obligation is to carry that fact through to the
    result without letting it collapse into something reassuring
    (``SAFETY-INV-008``).

    ``resolved`` exists and must be ``False``. A resolved conflict is not a
    conflict, and accepting one here would let a caller mark a disagreement
    settled by passing a flag rather than by adjudicating it.
    """

    conflict_id: str
    drug_canonical_key: str
    gene_canonical_key: str
    phenotype: Phenotype
    rule_ids: Tuple[str, ...]
    evidence_references: Tuple[str, ...]
    provenance: str
    resolved: bool = False

    def __post_init__(self) -> None:
        if self.resolved:
            raise CoverageEngineError(
                "a resolved conflict is not a conflict; WP-13 carries only "
                "unresolved disagreements and resolves none of them",
                code="COVERAGE_CONFLICT_RESOLVED", location="$.resolved")
        for name in ("conflict_id", "drug_canonical_key", "gene_canonical_key",
                     "provenance"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise CoverageEngineError(
                    "%s must be a non-empty string" % name,
                    code="COVERAGE_CONFLICT_INCOMPLETE",
                    location="$." + name)
        if not isinstance(self.phenotype, Phenotype):
            raise CoverageEngineError(
                "a conflict names the exact phenotype axis it is about",
                code="COVERAGE_CONFLICT_INCOMPLETE", location="$.phenotype")
        # Materialise before counting. A caller handing this a generator gets
        # a stated refusal rather than a TypeError from len(), and an iterator
        # is not consumed twice into a conflict that appears to name no rules.
        object.__setattr__(self, "rule_ids", tuple(sorted(set(self.rule_ids))))
        object.__setattr__(self, "evidence_references",
                           tuple(sorted(set(self.evidence_references))))
        if len(self.rule_ids) < 2:
            raise CoverageEngineError(
                "a conflict involves at least two rules; one rule disagrees "
                "with nothing",
                code="COVERAGE_CONFLICT_INCOMPLETE", location="$.rule_ids")

    @property
    def axis_key(self) -> Tuple[str, str, str]:
        return (self.drug_canonical_key, self.gene_canonical_key,
                self.phenotype.value)

    def to_json(self) -> Dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "drug_id": self.drug_canonical_key,
            "gene_id": self.gene_canonical_key,
            "phenotype": self.phenotype.value,
            "rule_ids": list(self.rule_ids),
            "evidence_references": list(self.evidence_references),
            "provenance": self.provenance,
            "resolved": False,
        }


@dataclass(frozen=True, slots=True)
class AxisCoverage:
    """What could be evaluated for one drug-gene axis, and why not.

    ``observed_phenotype`` is set only when a phenotype was actually observed.
    ``observation_state`` records what WP-12 concluded about the input, so a
    reader can tell an axis nobody supplied a value for from one where the
    value could not be interpreted - two facts that both prevent coverage and
    mean different things.
    """

    drug_canonical_key: str
    gene_canonical_key: str
    status: CoverageStatus
    reason_codes: Tuple[CoverageReasonCode, ...] = ()
    observed_phenotype: Optional[Phenotype] = None
    observation_state: str = ""
    declaration_id: Optional[str] = None
    rule_references: Tuple[Mapping[str, Any], ...] = ()
    evidence_references: Tuple[str, ...] = ()
    conflict_references: Tuple[str, ...] = ()
    ruleset_public_id: str = ""
    ruleset_content_hash: str = ""
    dataset_public_id: str = ""
    canonical_build_content_hash: str = ""
    coverage_manifest_hash: str = ""
    axis_coverage_schema_version: str = AXIS_COVERAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.status, CoverageStatus):
            raise CoverageEngineError("status must be a CoverageStatus",
                                      code="COVERAGE_STATUS_UNKNOWN",
                                      location="$.status")
        object.__setattr__(self, "reason_codes",
                           order_reasons(self.reason_codes))
        if self.status is CoverageStatus.FULL and self.reason_codes:
            raise CoverageEngineError(
                "FULL coverage carries no failure reason; a reason on a full "
                "axis would be a caveat nobody has to read",
                code="COVERAGE_FULL_WITH_REASON", location="$.reason_codes")
        if self.status is not CoverageStatus.FULL and not self.reason_codes:
            raise CoverageEngineError(
                "coverage %s requires at least one machine-readable reason; "
                "unexplained absence is how absence becomes reassurance"
                % self.status.value,
                code="COVERAGE_REASON_MISSING", location="$.reason_codes")
        if self.status is CoverageStatus.FULL:
            if not self.rule_references:
                raise CoverageEngineError(
                    "a FULL axis names the validated rule that covers it",
                    code="COVERAGE_FULL_WITHOUT_RULE",
                    location="$.rule_references")
            if not self.evidence_references:
                raise CoverageEngineError(
                    "a FULL axis names resolvable evidence (SAFETY-INV-006)",
                    code="COVERAGE_FULL_WITHOUT_EVIDENCE",
                    location="$.evidence_references")
            if self.observed_phenotype is None:
                raise CoverageEngineError(
                    "a FULL axis names the phenotype that was evaluated",
                    code="COVERAGE_FULL_WITHOUT_PHENOTYPE",
                    location="$.observed_phenotype")
        if self.status is CoverageStatus.SOURCE_CONFLICT and \
                not self.conflict_references:
            raise CoverageEngineError(
                "a SOURCE_CONFLICT axis names the conflict it preserves",
                code="COVERAGE_CONFLICT_UNIDENTIFIED",
                location="$.conflict_references")
        object.__setattr__(self, "rule_references",
                           tuple(freeze_json(dict(item))
                                 for item in self.rule_references))
        object.__setattr__(self, "evidence_references",
                           tuple(sorted(set(self.evidence_references))))
        object.__setattr__(self, "conflict_references",
                           tuple(sorted(set(self.conflict_references))))

    @property
    def axis_key(self) -> Tuple[str, str]:
        return (self.drug_canonical_key, self.gene_canonical_key)

    def to_json(self) -> Dict[str, Any]:
        return {
            "axis_coverage_schema_version": self.axis_coverage_schema_version,
            "drug_id": self.drug_canonical_key,
            "gene_id": self.gene_canonical_key,
            "status": self.status.value,
            "reason_codes": [code.value for code in self.reason_codes],
            "observed_phenotype": (self.observed_phenotype.value
                                   if self.observed_phenotype else None),
            "observation_state": self.observation_state,
            "declaration_id": self.declaration_id,
            "rule_references": [dict(item) for item in self.rule_references],
            "evidence_references": list(self.evidence_references),
            "conflict_references": list(self.conflict_references),
            "ruleset_public_id": self.ruleset_public_id,
            "ruleset_content_hash": self.ruleset_content_hash,
            "dataset_public_id": self.dataset_public_id,
            "canonical_build_content_hash": self.canonical_build_content_hash,
            "coverage_manifest_hash": self.coverage_manifest_hash,
        }

    def content_hash(self) -> str:
        return sha256_digest(self.to_json())


@dataclass(frozen=True, slots=True)
class MedicationCoverage:
    """What could be evaluated for one requested medication, and why not.

    Every axis result is preserved, including the ones that succeeded when
    others did not. A ``PARTIAL`` medication that dropped its covered axes
    would be indistinguishable from an insufficient one, and a ``PARTIAL``
    that dropped its uncovered axes would look complete.
    """

    medication: MedicationReference
    status: CoverageStatus
    reason_codes: Tuple[CoverageReasonCode, ...] = ()
    axes: Tuple[AxisCoverage, ...] = ()
    medication_coverage_schema_version: str = MEDICATION_COVERAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.status, CoverageStatus):
            raise CoverageEngineError("status must be a CoverageStatus",
                                      code="COVERAGE_STATUS_UNKNOWN",
                                      location="$.status")
        object.__setattr__(self, "reason_codes",
                           order_reasons(self.reason_codes))
        if self.status is CoverageStatus.FULL and self.reason_codes:
            raise CoverageEngineError(
                "FULL coverage carries no failure reason",
                code="COVERAGE_FULL_WITH_REASON", location="$.reason_codes")
        if self.status is not CoverageStatus.FULL and not self.reason_codes:
            raise CoverageEngineError(
                "coverage %s requires at least one reason" % self.status.value,
                code="COVERAGE_REASON_MISSING", location="$.reason_codes")
        if self.status is CoverageStatus.FULL and not self.axes:
            raise CoverageEngineError(
                "a FULL medication covers at least one axis; a medication with "
                "no axes has not been assessed, it has been skipped",
                code="COVERAGE_FULL_WITHOUT_AXES", location="$.axes")
        object.__setattr__(
            self, "axes",
            tuple(sorted(self.axes, key=lambda item: item.axis_key)))

    def to_json(self) -> Dict[str, Any]:
        return {
            "medication_coverage_schema_version":
                self.medication_coverage_schema_version,
            "medication": self.medication.to_json(),
            "status": self.status.value,
            "reason_codes": [code.value for code in self.reason_codes],
            "axis_count": len(self.axes),
            "axes": [axis.to_json() for axis in self.axes],
        }

    def content_hash(self) -> str:
        return sha256_digest(self.to_json())


@dataclass(frozen=True, slots=True)
class CoverageResult:
    """The whole answer: what could be evaluated across every requested drug.

    Pins the identities everything was computed against, so a stored result
    can be checked against the artifacts that produced it rather than against
    whatever is on disk today.
    """

    status: CoverageStatus
    reason_codes: Tuple[CoverageReasonCode, ...]
    medications: Tuple[MedicationCoverage, ...]
    profile_content_hash: str
    coverage_manifest_hash: str
    ruleset_public_id: str
    ruleset_content_hash: str
    dataset_public_id: str
    canonical_build_content_hash: str
    evidence_build_key: str
    evidence_build_content_hash: str
    note: str = (
        "Coverage states what could be evaluated and why the rest could not. "
        "It is not an attention level, a risk statement or a recommendation, "
        "and it must never be displayed as a substitute for one.")
    coverage_result_schema_version: str = COVERAGE_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.status, CoverageStatus):
            raise CoverageEngineError("status must be a CoverageStatus",
                                      code="COVERAGE_STATUS_UNKNOWN",
                                      location="$.status")
        if not self.medications:
            raise CoverageInputError(
                "a coverage result covers at least one requested medication; "
                "an empty request has no answer, and returning FULL for one "
                "would be the emptiest possible reassurance",
                code="COVERAGE_REQUEST_EMPTY", location="$.medications")
        object.__setattr__(self, "reason_codes",
                           order_reasons(self.reason_codes))
        if self.status is CoverageStatus.FULL and self.reason_codes:
            raise CoverageEngineError(
                "FULL coverage carries no failure reason",
                code="COVERAGE_FULL_WITH_REASON", location="$.reason_codes")
        if self.status is not CoverageStatus.FULL and not self.reason_codes:
            raise CoverageEngineError(
                "coverage %s requires at least one reason" % self.status.value,
                code="COVERAGE_REASON_MISSING", location="$.reason_codes")
        _require_digest(self.profile_content_hash, "profile_content_hash")
        object.__setattr__(
            self, "medications",
            tuple(sorted(self.medications,
                         key=lambda item: (item.medication.drug_canonical_key
                                           or "",
                                           item.medication.requested_value))))

    def to_json(self) -> Dict[str, Any]:
        payload = {
            "coverage_result_schema_version":
                self.coverage_result_schema_version,
            "status": self.status.value,
            "reason_codes": [code.value for code in self.reason_codes],
            "medication_count": len(self.medications),
            "medications": [item.to_json() for item in self.medications],
            "profile_content_hash": self.profile_content_hash,
            "coverage_manifest_hash": self.coverage_manifest_hash,
            "ruleset_public_id": self.ruleset_public_id,
            "ruleset_content_hash": self.ruleset_content_hash,
            "dataset_public_id": self.dataset_public_id,
            "canonical_build_content_hash": self.canonical_build_content_hash,
            "evidence_build_key": self.evidence_build_key,
            "evidence_build_content_hash": self.evidence_build_content_hash,
            "note": self.note,
        }
        payload["content_hash"] = sha256_digest(payload)
        return payload

    def content_hash(self) -> str:
        return self.to_json()["content_hash"]
