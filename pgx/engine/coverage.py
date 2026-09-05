# -*- coding: utf-8 -*-
"""The coverage engine (WP-13).

One question: *what could this governed ruleset evaluate, and why could it not
evaluate the rest?*

Not: what attention level should be reported. There is no attention level
anywhere in this module, no risk score, no recommendation and no field one
could be written into. Coverage and attention are separate first-class
outputs, and WP-13 computes exactly one of them (`architecture.md` 9.2, 9.3).

**Aggregation is a decision table, not a comparison.** `CoverageStatus` has no
ordering and must never acquire one, so nothing here uses `max`, `min`,
`sorted` or enum declaration order to combine statuses. The tables below are
written out case by case, which is longer and is the point: somebody reviewing
"what happens when one axis is covered and another conflicts" should be able
to find the answer rather than derive it.

**Conflict preservation is a safety rule, not a severity rule.** When an
unresolved disagreement is present anywhere, the result says so, and every
other status and reason is preserved alongside it. That is not `SOURCE_CONFLICT`
being "worse" than `PARTIAL`; it is the one fact that must not disappear into
an aggregate (`SAFETY-INV-008`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from pgx.domain.enums import CoverageReasonCode, CoverageStatus, Phenotype
from pgx.engine.coverage_errors import (CoverageBoundaryError,
                                        CoverageEngineError, CoverageInputError)
from pgx.engine.coverage_models import (AxisCoverage, CoverageResult,
                                        MedicationCoverage, MedicationReference,
                                        SourceConflictSignal, order_reasons)
from pgx.engine.phenotype import match_observation
from pgx.rules.conditions import PhenotypeMatch

__all__ = [
    "COVERAGE_ENGINE_CONTRACT_VERSION",
    "CoverageRequest",
    "MEDICATION_DECISION_TABLE",
    "OVERALL_DECISION_TABLE",
    "aggregate_medication",
    "aggregate_overall",
    "evaluate_axis",
    "evaluate_coverage",
    "resolve_medication",
    "truth_table",
]

COVERAGE_ENGINE_CONTRACT_VERSION = "pgx-coverage-engine/1"

#: The axis-level table, as data. Each row is (condition, status, reasons),
#: and the conditions are checked in this order because they are checked in
#: this order in ``evaluate_axis`` - the table is the documentation of that
#: function, published so the CLI and the tests read the same one.
#:
#: The order matters and is deliberate: a boundary mismatch is checked before
#: anything else because a mismatched pin makes every other answer meaningless,
#: and an unresolved conflict is checked before the phenotype because a
#: disagreement about an axis is a fact about the axis regardless of what was
#: observed.
AXIS_DECISION_TABLE: Tuple[Mapping[str, Any], ...] = (
    {"case": "boundary_mismatch",
     "when": "the manifest, ruleset or dataset supplied are not the ones each "
             "other pins",
     "status": CoverageStatus.INSUFFICIENT,
     "reasons": (CoverageReasonCode.DATASET_RULESET_MISMATCH,)},
    {"case": "unresolved_conflict",
     "when": "an unresolved source conflict names this exact axis",
     "status": CoverageStatus.SOURCE_CONFLICT,
     "reasons": (CoverageReasonCode.VALIDATED_RULES_CONFLICT,)},
    {"case": "phenotype_absent",
     "when": "the profile says nothing about this gene, or was given an empty "
             "value for it",
     "status": CoverageStatus.INSUFFICIENT,
     "reasons": (CoverageReasonCode.PHENOTYPE_NOT_PROVIDED,)},
    {"case": "phenotype_unusable",
     "when": "a value was supplied and is indeterminate or not a phenotype",
     "status": CoverageStatus.UNSUPPORTED_PHENOTYPE,
     "reasons": (CoverageReasonCode.PHENOTYPE_NOT_SUPPORTED,)},
    {"case": "no_declared_axis",
     "when": "the manifest declares no supported axis for this exact "
             "gene/phenotype",
     "status": CoverageStatus.INSUFFICIENT,
     "reasons": (CoverageReasonCode.NO_VALIDATED_RULE_FOR_AXIS,)},
    {"case": "rule_not_in_ruleset",
     "when": "the declared rule is not a member of the supplied frozen ruleset, "
             "or its content hash disagrees",
     "status": CoverageStatus.INSUFFICIENT,
     "reasons": (CoverageReasonCode.DATASET_RULESET_MISMATCH,)},
    {"case": "rule_does_not_cover_axis",
     "when": "the member rule's condition does not match the observed "
             "phenotype exactly",
     "status": CoverageStatus.INSUFFICIENT,
     "reasons": (CoverageReasonCode.NO_VALIDATED_RULE_FOR_AXIS,)},
    {"case": "evidence_unresolvable",
     "when": "the supporting evidence cannot be resolved in the pinned build",
     "status": CoverageStatus.INSUFFICIENT,
     "reasons": (CoverageReasonCode.EVIDENCE_REFERENCE_MISSING,)},
    {"case": "covered",
     "when": "the exact axis is declared, a validated member rule covers the "
             "observed phenotype, and its evidence resolves",
     "status": CoverageStatus.FULL,
     "reasons": ()},
)

#: The medication table. Read top to bottom; the first matching row wins.
MEDICATION_DECISION_TABLE: Tuple[Mapping[str, Any], ...] = (
    {"case": "drug_not_in_dataset",
     "when": "the pinned canonical dataset does not contain the drug",
     "status": CoverageStatus.UNSUPPORTED_DRUG,
     "reasons": (CoverageReasonCode.DRUG_NOT_IN_CANONICAL_DATASET,),
     "note": "no axis is fabricated for a drug the dataset does not have"},
    {"case": "drug_not_declared",
     "when": "the drug is recognised but the coverage manifest declares no "
             "scope for it",
     "status": CoverageStatus.INSUFFICIENT,
     "reasons": (CoverageReasonCode.NO_VALIDATED_RULE_FOR_AXIS,),
     "note": "recognition is not coverage (architecture.md 6.2)"},
    {"case": "any_conflict",
     "when": "any axis carries an unresolved source conflict",
     "status": CoverageStatus.SOURCE_CONFLICT,
     "reasons": (CoverageReasonCode.VALIDATED_RULES_CONFLICT,),
     "note": "every other axis status and reason is preserved alongside it"},
    {"case": "all_axes_full",
     "when": "every expected axis is FULL",
     "status": CoverageStatus.FULL,
     "reasons": (),
     "note": "the only status that carries no reason"},
    {"case": "some_axes_full",
     "when": "at least one axis is FULL and at least one is not",
     "status": CoverageStatus.PARTIAL,
     "reasons": (CoverageReasonCode.SOME_AXES_NOT_COVERED,),
     "note": "underlying axis reasons are preserved as well"},
    {"case": "all_unsupported_phenotype",
     "when": "no axis is FULL and every failure is an unusable phenotype",
     "status": CoverageStatus.UNSUPPORTED_PHENOTYPE,
     "reasons": (CoverageReasonCode.PHENOTYPE_NOT_SUPPORTED,),
     "note": "homogeneous failures keep their specific status"},
    {"case": "nothing_covered",
     "when": "no axis is FULL and the failures are mixed",
     "status": CoverageStatus.INSUFFICIENT,
     "reasons": (),
     "note": "reasons come from the axes themselves"},
)

#: The overall table. Same shape, same rule: first match wins.
OVERALL_DECISION_TABLE: Tuple[Mapping[str, Any], ...] = (
    {"case": "any_conflict",
     "when": "any medication carries an unresolved source conflict",
     "status": CoverageStatus.SOURCE_CONFLICT,
     "reasons": (CoverageReasonCode.VALIDATED_RULES_CONFLICT,),
     "note": "conflict preservation, not severity: every other medication "
             "status and reason survives in the result"},
    {"case": "all_full",
     "when": "every medication is FULL",
     "status": CoverageStatus.FULL,
     "reasons": (),
     "note": "the only status that carries no reason"},
    {"case": "some_covered",
     "when": "at least one medication is FULL or PARTIAL, and at least one is "
             "not FULL",
     "status": CoverageStatus.PARTIAL,
     "reasons": (CoverageReasonCode.SOME_AXES_NOT_COVERED,),
     "note": "underlying medication reasons are preserved"},
    {"case": "all_unsupported_drug",
     "when": "nothing is covered and every drug is absent from the dataset",
     "status": CoverageStatus.UNSUPPORTED_DRUG,
     "reasons": (CoverageReasonCode.DRUG_NOT_IN_CANONICAL_DATASET,),
     "note": "homogeneous failures keep their specific status"},
    {"case": "all_unsupported_phenotype",
     "when": "nothing is covered and every failure is an unusable phenotype",
     "status": CoverageStatus.UNSUPPORTED_PHENOTYPE,
     "reasons": (CoverageReasonCode.PHENOTYPE_NOT_SUPPORTED,),
     "note": "homogeneous failures keep their specific status"},
    {"case": "nothing_covered",
     "when": "nothing is covered and the failures are mixed",
     "status": CoverageStatus.INSUFFICIENT,
     "reasons": (),
     "note": "reasons come from the medications themselves"},
)


@dataclass(frozen=True, slots=True)
class CoverageRequest:
    """Everything an evaluation reads, as one immutable value.

    Assembled by the caller, so the engine reaches for nothing: no registry, no
    filesystem, no clock. What it is given is what it evaluates.
    """

    profile: Any
    medications: Tuple[str, ...]
    manifest: Any
    frozen_ruleset: Any
    drug_catalogue: Tuple[str, ...]
    evidence_resolver: Any = None
    conflicts: Tuple[SourceConflictSignal, ...] = ()

    def __post_init__(self) -> None:
        if not self.medications:
            raise CoverageInputError(
                "a coverage request names at least one medication",
                code="COVERAGE_REQUEST_EMPTY", location="$.medications")
        seen = []
        for value in self.medications:
            if not isinstance(value, str) or not value.strip():
                continue
            key = value.strip()
            if key in seen:
                raise CoverageInputError(
                    "medication %r is requested twice. Duplicates are refused "
                    "rather than merged: a caller that asked twice may have "
                    "meant two different things, and collapsing them answers a "
                    "question nobody asked." % key,
                    code="COVERAGE_REQUEST_DUPLICATE",
                    location="$.medications", detail={"medication": key})
            seen.append(key)
        object.__setattr__(self, "medications", tuple(self.medications))
        object.__setattr__(self, "drug_catalogue",
                           tuple(sorted(set(self.drug_catalogue))))
        object.__setattr__(self, "conflicts", tuple(self.conflicts))


def _boundary_problem(manifest, frozen_ruleset) -> Optional[str]:
    """Whether the manifest and the ruleset describe each other.

    Checked by hash as well as identity: a manifest naming the right ruleset
    id but the wrong content hash was written against a ruleset that has since
    been rebuilt, and it describes coverage that no longer exists.
    """
    ruleset_manifest = frozen_ruleset.manifest
    if manifest.ruleset_public_id != ruleset_manifest.public_id.to_json():
        return "ruleset identity"
    if manifest.ruleset_content_hash != frozen_ruleset.ruleset_content_hash:
        return "ruleset content hash"
    if manifest.dataset_public_id != ruleset_manifest.dataset_public_id.to_json():
        return "dataset identity"
    if manifest.canonical_build_content_hash != \
            ruleset_manifest.canonical_build_content_hash:
        return "canonical build hash"
    if manifest.evidence_build_content_hash != \
            ruleset_manifest.evidence_build_content_hash:
        return "evidence build hash"
    return None


def resolve_medication(value: Any, drug_catalogue: Sequence[str]
                       ) -> MedicationReference:
    """Look one requested medication up in the pinned catalogue.

    A lookup, not an interpretation. Free-text aliases are not normalised
    here: resolving a brand name to a canonical drug is WP-07's work, and a
    coverage engine that guessed would be inventing the subject of its own
    answer.
    """
    if not isinstance(value, str) or not value.strip():
        return MedicationReference(
            requested_value="" if not isinstance(value, str) else value,
            state="INVALID",
            reason="a medication reference is a non-empty canonical drug key")
    text = value.strip()
    if not text.startswith("DRUG:"):
        return MedicationReference(
            requested_value=text, state="INVALID",
            reason="a medication reference is a canonical drug key beginning "
                   "'DRUG:'; this engine does not normalise free text")
    if text not in set(drug_catalogue):
        return MedicationReference(
            requested_value=text, state="NOT_IN_CANONICAL_DATASET",
            drug_canonical_key=text,
            reason="the pinned canonical dataset does not contain this drug")
    return MedicationReference(requested_value=text, state="RECOGNIZED",
                               drug_canonical_key=text)


def _conflict_for(conflicts, drug: str, gene: str,
                  phenotype: Optional[Phenotype]) -> Tuple[SourceConflictSignal, ...]:
    """Conflicts naming this axis.

    When no phenotype was observed, a conflict on the drug/gene pair still
    counts: the disagreement is about the axis, not about the input, and
    hiding it because the input was unusable would be exactly the collapse
    SAFETY-INV-008 forbids.
    """
    found = []
    for conflict in conflicts:
        if conflict.drug_canonical_key != drug:
            continue
        if conflict.gene_canonical_key != gene:
            continue
        if phenotype is not None and conflict.phenotype is not phenotype:
            continue
        found.append(conflict)
    return tuple(found)


def evaluate_axis(*, request: CoverageRequest, drug_canonical_key: str,
                  gene_canonical_key: str) -> AxisCoverage:
    """Coverage for one drug-gene axis.

    Follows ``AXIS_DECISION_TABLE`` top to bottom. Uses WP-12's matcher for
    phenotype equality and does not reimplement it: a second equality rule
    would be a second place for RAPID to start meaning ULTRARAPID.
    """
    manifest = request.manifest
    frozen = request.frozen_ruleset
    common = {
        "drug_canonical_key": drug_canonical_key,
        "gene_canonical_key": gene_canonical_key,
        "ruleset_public_id": manifest.ruleset_public_id,
        "ruleset_content_hash": manifest.ruleset_content_hash,
        "dataset_public_id": manifest.dataset_public_id,
        "canonical_build_content_hash": manifest.canonical_build_content_hash,
        "coverage_manifest_hash": manifest.content_hash(),
    }

    # 1. boundary. A mismatched pin makes every other answer meaningless.
    problem = _boundary_problem(manifest, frozen)
    if problem is not None:
        return AxisCoverage(
            status=CoverageStatus.INSUFFICIENT,
            reason_codes=(CoverageReasonCode.DATASET_RULESET_MISMATCH,),
            observation_state="NOT_EVALUATED", **common)

    observation = request.profile.observation_for(gene_canonical_key)
    observed = observation.phenotype if observation is not None else None

    # 2. an unresolved disagreement about this axis, whatever the input was.
    conflicts = _conflict_for(request.conflicts, drug_canonical_key,
                              gene_canonical_key, observed)
    if conflicts:
        rule_references = []
        evidence = []
        declaration = manifest.declaration_for(drug_canonical_key)
        if declaration is not None and observed is not None:
            for axis in declaration.supported_axes:
                if axis.gene_canonical_key == gene_canonical_key and \
                        axis.phenotype is observed:
                    rule_references.append({"rule_id": axis.rule_id,
                                            "rule_version": axis.rule_version,
                                            "rule_content_hash":
                                                axis.rule_content_hash})
                    evidence.extend(axis.evidence_references)
        for conflict in conflicts:
            evidence.extend(conflict.evidence_references)
            for rule_id in conflict.rule_ids:
                rule_references.append({"rule_id": rule_id,
                                        "rule_version": 0,
                                        "rule_content_hash": ""})
        return AxisCoverage(
            status=CoverageStatus.SOURCE_CONFLICT,
            reason_codes=(CoverageReasonCode.VALIDATED_RULES_CONFLICT,),
            observed_phenotype=observed,
            observation_state=(observation.status if observation is not None
                               else "ABSENT"),
            declaration_id=(declaration.declaration_id
                            if declaration is not None else None),
            rule_references=tuple(rule_references),
            evidence_references=tuple(evidence),
            conflict_references=tuple(item.conflict_id for item in conflicts),
            **common)

    # 3. and 4. what WP-12 made of the input.
    if observation is None or observation.status == "MISSING":
        return AxisCoverage(
            status=CoverageStatus.INSUFFICIENT,
            reason_codes=(CoverageReasonCode.PHENOTYPE_NOT_PROVIDED,),
            observation_state=(observation.status if observation is not None
                               else "ABSENT"), **common)
    if observation.status in ("UNSUPPORTED", "INDETERMINATE"):
        return AxisCoverage(
            status=CoverageStatus.UNSUPPORTED_PHENOTYPE,
            reason_codes=(CoverageReasonCode.PHENOTYPE_NOT_SUPPORTED,),
            observation_state=observation.status, **common)

    # 5. is this exact axis declared?
    declaration = manifest.declaration_for(drug_canonical_key)
    supported = None
    if declaration is not None:
        for axis in declaration.supported_axes:
            if axis.gene_canonical_key == gene_canonical_key and \
                    axis.phenotype is observation.phenotype:
                supported = axis
                break
    if supported is None:
        return AxisCoverage(
            status=CoverageStatus.INSUFFICIENT,
            reason_codes=(CoverageReasonCode.NO_VALIDATED_RULE_FOR_AXIS,),
            observed_phenotype=observation.phenotype,
            observation_state=observation.status,
            declaration_id=(declaration.declaration_id
                            if declaration is not None else None), **common)

    # 6. is the declared rule really in this ruleset, unchanged?
    member = None
    for definition in frozen.rules():
        if definition.rule_id.to_json() == supported.rule_id:
            member = definition
            break
    if member is None or member.content_hash() != supported.rule_content_hash:
        return AxisCoverage(
            status=CoverageStatus.INSUFFICIENT,
            reason_codes=(CoverageReasonCode.DATASET_RULESET_MISMATCH,),
            observed_phenotype=observation.phenotype,
            observation_state=observation.status,
            declaration_id=declaration.declaration_id, **common)

    # 7. does it actually cover the observed phenotype? WP-12 decides.
    decision = match_observation(observation, member.condition)
    if not decision.matched:
        return AxisCoverage(
            status=CoverageStatus.INSUFFICIENT,
            reason_codes=(CoverageReasonCode.NO_VALIDATED_RULE_FOR_AXIS,),
            observed_phenotype=observation.phenotype,
            observation_state=observation.status,
            declaration_id=declaration.declaration_id, **common)

    # 8. does its evidence resolve?
    evidence = tuple(supported.evidence_references)
    if request.evidence_resolver is not None:
        unresolved = [item for item in evidence
                      if not request.evidence_resolver(item)]
        if unresolved or not evidence:
            return AxisCoverage(
                status=CoverageStatus.INSUFFICIENT,
                reason_codes=(CoverageReasonCode.EVIDENCE_REFERENCE_MISSING,),
                observed_phenotype=observation.phenotype,
                observation_state=observation.status,
                declaration_id=declaration.declaration_id,
                rule_references=({"rule_id": supported.rule_id,
                                  "rule_version": supported.rule_version,
                                  "rule_content_hash":
                                      supported.rule_content_hash},),
                **common)

    # 9. covered.
    return AxisCoverage(
        status=CoverageStatus.FULL, reason_codes=(),
        observed_phenotype=observation.phenotype,
        observation_state=observation.status,
        declaration_id=declaration.declaration_id,
        rule_references=({"rule_id": supported.rule_id,
                          "rule_version": supported.rule_version,
                          "rule_content_hash": supported.rule_content_hash},),
        evidence_references=evidence, **common)


def aggregate_medication(*, request: CoverageRequest,
                         medication: MedicationReference) -> MedicationCoverage:
    """Coverage for one requested medication, per ``MEDICATION_DECISION_TABLE``."""
    if medication.state == "INVALID":
        return MedicationCoverage(
            medication=medication, status=CoverageStatus.UNSUPPORTED_DRUG,
            reason_codes=(CoverageReasonCode.DRUG_NOT_IN_CANONICAL_DATASET,))
    if not medication.is_recognized:
        return MedicationCoverage(
            medication=medication, status=CoverageStatus.UNSUPPORTED_DRUG,
            reason_codes=(CoverageReasonCode.DRUG_NOT_IN_CANONICAL_DATASET,))

    drug = medication.drug_canonical_key
    declaration = request.manifest.declaration_for(drug)
    if declaration is None:
        # Recognised, and nothing is declared about it. This is the codeine
        # case: the dataset has the chemical and no scope was ever approved.
        return MedicationCoverage(
            medication=medication, status=CoverageStatus.INSUFFICIENT,
            reason_codes=(CoverageReasonCode.NO_VALIDATED_RULE_FOR_AXIS,))

    axes = tuple(evaluate_axis(request=request, drug_canonical_key=drug,
                               gene_canonical_key=gene)
                 for gene in declaration.expected_gene_keys)

    statuses = [axis.status for axis in axes]
    reasons = [code for axis in axes for code in axis.reason_codes]

    if CoverageStatus.SOURCE_CONFLICT in statuses:
        return MedicationCoverage(
            medication=medication, status=CoverageStatus.SOURCE_CONFLICT,
            reason_codes=order_reasons(
                [CoverageReasonCode.VALIDATED_RULES_CONFLICT] + reasons),
            axes=axes)
    full = [status for status in statuses if status is CoverageStatus.FULL]
    if full and len(full) == len(statuses):
        return MedicationCoverage(medication=medication,
                                  status=CoverageStatus.FULL, axes=axes)
    if full:
        return MedicationCoverage(
            medication=medication, status=CoverageStatus.PARTIAL,
            reason_codes=order_reasons(
                [CoverageReasonCode.SOME_AXES_NOT_COVERED] + reasons),
            axes=axes)
    if statuses and all(status is CoverageStatus.UNSUPPORTED_PHENOTYPE
                        for status in statuses):
        return MedicationCoverage(
            medication=medication, status=CoverageStatus.UNSUPPORTED_PHENOTYPE,
            reason_codes=order_reasons(reasons), axes=axes)
    return MedicationCoverage(
        medication=medication, status=CoverageStatus.INSUFFICIENT,
        reason_codes=order_reasons(
            reasons or [CoverageReasonCode.NO_VALIDATED_RULE_FOR_AXIS]),
        axes=axes)


def aggregate_overall(medications: Sequence[MedicationCoverage]
                      ) -> Tuple[CoverageStatus, Tuple[CoverageReasonCode, ...]]:
    """Overall coverage, per ``OVERALL_DECISION_TABLE``."""
    if not medications:
        raise CoverageInputError(
            "an overall coverage result aggregates at least one medication",
            code="COVERAGE_REQUEST_EMPTY", location="$.medications")
    statuses = [item.status for item in medications]
    reasons = [code for item in medications for code in item.reason_codes]

    if CoverageStatus.SOURCE_CONFLICT in statuses:
        return (CoverageStatus.SOURCE_CONFLICT,
                order_reasons([CoverageReasonCode.VALIDATED_RULES_CONFLICT]
                              + reasons))
    if all(status is CoverageStatus.FULL for status in statuses):
        return CoverageStatus.FULL, ()
    covered = [status for status in statuses
               if status in (CoverageStatus.FULL, CoverageStatus.PARTIAL)]
    if covered:
        return (CoverageStatus.PARTIAL,
                order_reasons([CoverageReasonCode.SOME_AXES_NOT_COVERED]
                              + reasons))
    if all(status is CoverageStatus.UNSUPPORTED_DRUG for status in statuses):
        return (CoverageStatus.UNSUPPORTED_DRUG,
                order_reasons([CoverageReasonCode.DRUG_NOT_IN_CANONICAL_DATASET]))
    if all(status is CoverageStatus.UNSUPPORTED_PHENOTYPE
           for status in statuses):
        return (CoverageStatus.UNSUPPORTED_PHENOTYPE,
                order_reasons([CoverageReasonCode.PHENOTYPE_NOT_SUPPORTED]))
    return (CoverageStatus.INSUFFICIENT,
            order_reasons(reasons or
                          [CoverageReasonCode.NO_VALIDATED_RULE_FOR_AXIS]))


def evaluate_coverage(request: CoverageRequest) -> CoverageResult:
    """The whole answer for one request."""
    if not isinstance(request, CoverageRequest):
        raise CoverageInputError(
            "evaluate_coverage takes a CoverageRequest",
            code="COVERAGE_REQUEST_INVALID", location="$.request")
    manifest = request.manifest
    medications = tuple(
        aggregate_medication(
            request=request,
            medication=resolve_medication(value, request.drug_catalogue))
        for value in request.medications)
    status, reasons = aggregate_overall(medications)
    return CoverageResult(
        status=status, reason_codes=reasons, medications=medications,
        profile_content_hash=request.profile.content_hash(),
        coverage_manifest_hash=manifest.content_hash(),
        ruleset_public_id=manifest.ruleset_public_id,
        ruleset_content_hash=manifest.ruleset_content_hash,
        dataset_public_id=manifest.dataset_public_id,
        canonical_build_content_hash=manifest.canonical_build_content_hash,
        evidence_build_key=manifest.evidence_build_key,
        evidence_build_content_hash=manifest.evidence_build_content_hash)


def truth_table() -> Dict[str, Any]:
    """The three decision tables, as one published document.

    Returned as data so the CLI, the tests and the documentation read the same
    tables instead of three descriptions of them.
    """
    def _rows(table):
        return [{"case": row["case"], "when": row["when"],
                 "status": row["status"].value,
                 "reason_codes": [code.value for code in row["reasons"]],
                 "note": row.get("note", "")}
                for row in table]

    return {
        "coverage_engine_contract_version": COVERAGE_ENGINE_CONTRACT_VERSION,
        "axis": _rows(AXIS_DECISION_TABLE),
        "medication": _rows(MEDICATION_DECISION_TABLE),
        "overall": _rows(OVERALL_DECISION_TABLE),
        "note": (
            "Every table is read top to bottom and the first matching row "
            "wins. No status is compared with another: CoverageStatus has no "
            "ordering, and conflict precedence is a safety rule about not "
            "losing a disagreement, not a claim that one status outranks "
            "another. No row produces an attention level, because this engine "
            "computes none."),
    }
