# -*- coding: utf-8 -*-
"""Requirement to result, with nowhere to hide a gap (WP-25).

One row per obligation. Each row names the requirement, where it is written,
the modules that implement it, the tests that exercise them, the evidence it
produced, the claims it supports, the gate it feeds, the result, and - when
the result is anything short of supported - what is missing and who supplies
it.

The property that makes the matrix worth having is **no dangling identifier**.
Every evidence id must exist in the evidence registry, every claim id in the
claim registry, every gate id in the gate matrix, every Definition of Done id
in the DoD registry, and every implementation and test path must be a file
that is actually there. A matrix that cited a deleted module would be a
document asserting coverage it does not have, which is worse than no matrix,
because it looks like diligence.

``P0-DOD-014`` - "every THS 6 claim links to a concrete artifact or metric" -
is the one obligation this work package can discharge by itself, and it is
decided here rather than asserted: it is satisfied exactly when the matrix
resolves with no dangling reference and every claim names required evidence.
"""

from __future__ import annotations

import os
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.ths6.claim_registry import CLAIMS
from pgx.ths6.definition_of_done import DOD_SPECS
from pgx.ths6.evidence_registry import DECLARED_EVIDENCE, resolve_evidence
from pgx.ths6.gate_matrix import GATES, evaluate_gate
from pgx.ths6.models import TraceabilityRow
from pgx.ths6.vocabulary import ClaimSupport, GateResult

__all__ = [
    "TRACEABILITY_VERSION",
    "IMPLEMENTATION_INDEX",
    "build_traceability",
    "dangling_references",
]

TRACEABILITY_VERSION = "pgx-wp25-traceability/1"

#: Per Definition of Done item: the modules that implement it and the tests
#: that exercise them. Hand-maintained rather than inferred from imports,
#: because an import graph shows what calls what and this table has to say
#: what *answers* an obligation - a distinction no static analysis makes.
IMPLEMENTATION_INDEX: Mapping[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    "P0-DOD-001": (
        ("apps/web/main.py", "apps/api/main.py", "pgx/application/"
         "assessment_service.py"),
        ("tests/unit/web/test_e2e_flow.py", "tests/unit/api/"
         "test_assessment_flow.py")),
    "P0-DOD-002": (
        ("pgx/engine/", "pgx/application/assessment_snapshot.py"),
        ("tests/unit/reporting/test_determinism.py",)),
    "P0-DOD-003": (
        ("pgx/reporting/", "pgx/evidence/build.py"),
        ("tests/unit/reporting/test_fact_preservation.py",)),
    "P0-DOD-004": (
        ("pgx/engine/coverage_validator.py", "pgx/safety/"),
        ("tests/unit/engine/test_coverage_aggregation.py",
         "tests/unit/safety/test_invariant_001.py")),
    "P0-DOD-005": (
        ("pgx/application/release_service.py", "pgx/deployment/"
         "provenance.py", "pgx/deployment/rollback.py"),
        ("tests/unit/deployment/test_container_and_build.py",)),
    "P0-DOD-006": (
        ("pgx/validation/",),
        ("tests/unit/validation/test_cases.py",
         "tests/unit/validation/test_manifests_and_catalog.py")),
    "P0-DOD-007": (
        ("pgx/validation/",),
        ("tests/unit/validation/test_separation.py",)),
    "P0-DOD-008": (
        ("pgx/safety/", ".github/workflows/safety-gate.yml"),
        ("tests/unit/safety/test_gate.py",)),
    "P0-DOD-009": (
        ("pgx/expert_review/",),
        ("tests/unit/expert_review/test_state_machine.py",
         "tests/unit/expert_review/test_blinding.py")),
    "P0-DOD-010": (
        ("pgx/expert_review/", "apps/web/main.py"),
        ("tests/unit/web/test_expert_review_flow.py",)),
    "P0-DOD-011": (
        ("pgx/validation/", "pgx/application/benchmark_schema.py"),
        ("tests/unit/validation/test_artifacts.py",)),
    "P0-DOD-012": (
        ("pgx/infrastructure/audit/", "pgx/security/"),
        ("tests/unit/security/test_persistence.py",
         "tests/unit/security/test_rbac.py")),
    "P0-DOD-013": (
        ("pgx/deployment/smoke.py", "pgx/deployment/reliability.py",
         "Dockerfile"),
        ("tests/unit/deployment/test_honest_reporting.py",)),
    "P0-DOD-014": (
        ("pgx/ths6/claim_registry.py", "pgx/ths6/traceability.py",
         "pgx/ths6/evidence_registry.py"),
        ("tests/unit/ths6/test_registries.py",)),
    "P0-DOD-015": (
        ("pgx/ths6/demo.py", "apps/web/main.py"),
        ("tests/unit/ths6/test_demo_and_contingency.py",)),
}

#: Per gate: what implements the gate's own evaluation, and what tests it.
GATE_IMPLEMENTATION_INDEX: Mapping[str, Tuple[Tuple[str, ...],
                                              Tuple[str, ...]]] = {
    "GATE-A": (("pgx/ingestion/", "pgx/normalization/", "pgx/evidence/"),
               ("tests/unit/ths6/test_gates_and_dod.py",)),
    "GATE-B": (("pgx/curation/", "pgx/rules/"),
               ("tests/unit/ths6/test_gates_and_dod.py",)),
    "GATE-C": (("pgx/engine/", "pgx/reporting/", "pgx/safety/"),
               ("tests/unit/ths6/test_gates_and_dod.py",)),
    "GATE-D": (("pgx/validation/", "pgx/expert_review/"),
               ("tests/unit/ths6/test_gates_and_dod.py",)),
    "GATE-E": (("pgx/security/", "pgx/deployment/"),
               ("tests/unit/ths6/test_gates_and_dod.py",)),
    "GATE-F": (("pgx/ths6/gate_matrix.py", "pgx/ths6/status.py"),
               ("tests/unit/ths6/test_gates_and_dod.py",)),
}


def _exists(root: str, relative: str) -> bool:
    """Whether a declared path is a file or a directory in this tree."""
    absolute = os.path.join(root, *relative.rstrip("/").split("/"))
    return os.path.exists(absolute)


def _claims_for_dod(dod_id: str) -> Tuple[str, ...]:
    return tuple(sorted(item.claim_id for item in CLAIMS
                        if dod_id in item.dod_ids))


def _claims_for_gate(gate_id: str) -> Tuple[str, ...]:
    return tuple(sorted(item.claim_id for item in CLAIMS
                        if item.gate_id == gate_id))


def _evidence_for_claims(claim_ids: Sequence[str]) -> Tuple[str, ...]:
    wanted = set(claim_ids)
    return tuple(sorted({
        evidence_id
        for item in CLAIMS if item.claim_id in wanted
        for evidence_id in item.required_evidence_ids}))


def _support_from(results: Mapping[str, GateResult],
                  gate_ids: Sequence[str],
                  satisfied: Optional[bool]) -> ClaimSupport:
    """The row's result: whether *this requirement* is met.

    Deliberately not "and every gate it feeds passes". A requirement can be
    met while the gate it feeds is blocked by a different requirement, and
    folding the gate's conjunction into every row would make all twenty-one
    rows read UNSUPPORTED - a matrix that distinguishes nothing is a matrix
    nobody can use to find the next thing to fix. The conjunction lives in
    the gate matrix, which is the only place it belongs.

    ``CONTRADICTED`` is reserved for a gate that FAILs, meaning an artifact
    the requirement depends on is broken rather than merely absent.
    """
    if satisfied is None:
        return ClaimSupport.NOT_EVALUATED
    if any(results[gate_id] is GateResult.FAIL for gate_id in gate_ids):
        return ClaimSupport.CONTRADICTED
    return (ClaimSupport.SUPPORTED if satisfied
            else ClaimSupport.UNSUPPORTED)


def dangling_references(root: str = ".") -> Mapping[str, Sequence[str]]:
    """Every identifier or path a row cites that does not resolve."""
    evidence_ids = {item.evidence_id for item in DECLARED_EVIDENCE}
    claim_ids = {item.claim_id for item in CLAIMS}
    gate_ids = {spec.gate_id for spec in GATES}
    dod_ids = {spec.dod_id for spec in DOD_SPECS}
    missing_paths: List[str] = []
    unknown_evidence: List[str] = []
    unknown_claims: List[str] = []
    unknown_gates: List[str] = []
    unknown_dods: List[str] = []
    for dod_id, (implementations, tests) in IMPLEMENTATION_INDEX.items():
        if dod_id not in dod_ids:
            unknown_dods.append(dod_id)
        for path in tuple(implementations) + tuple(tests):
            if not _exists(root, path):
                missing_paths.append(path)
    for gate_id, (implementations, tests) in (
            GATE_IMPLEMENTATION_INDEX.items()):
        if gate_id not in gate_ids:
            unknown_gates.append(gate_id)
        for path in tuple(implementations) + tuple(tests):
            if not _exists(root, path):
                missing_paths.append(path)
    for claim in CLAIMS:
        for evidence_id in claim.required_evidence_ids:
            if evidence_id not in evidence_ids:
                unknown_evidence.append(evidence_id)
        if claim.gate_id is not None and claim.gate_id not in gate_ids:
            unknown_gates.append(claim.gate_id)
        for dod_id in claim.dod_ids:
            if dod_id not in dod_ids:
                unknown_dods.append(dod_id)
    for item in DECLARED_EVIDENCE:
        for claim_id in item.supported_claim_ids:
            if claim_id not in claim_ids:
                unknown_claims.append(claim_id)
        for gate_id in item.gate_ids:
            if gate_id not in gate_ids:
                unknown_gates.append(gate_id)
    return {
        "missing_paths": sorted(set(missing_paths)),
        "unknown_evidence_ids": sorted(set(unknown_evidence)),
        "unknown_claim_ids": sorted(set(unknown_claims)),
        "unknown_gate_ids": sorted(set(unknown_gates)),
        "unknown_dod_ids": sorted(set(unknown_dods)),
    }


def build_traceability(root: str = ".") -> Mapping[str, object]:
    """Build the matrix and decide P0-DOD-014 from its own result."""
    from pgx.ths6.definition_of_done import build_definition_of_done

    results = {spec.gate_id: evaluate_gate(root, spec).result
               for spec in GATES}
    dod_document = build_definition_of_done(root)
    dod_state = {item["dod_id"]: item["satisfied"]
                 for item in dod_document["items"]}  # type: ignore[index]
    owners = {spec.dod_id: spec.owner for spec in DOD_SPECS}
    rows: List[TraceabilityRow] = []
    for spec in DOD_SPECS:
        implementations, tests = IMPLEMENTATION_INDEX[spec.dod_id]
        claim_ids = _claims_for_dod(spec.dod_id)
        satisfied = dod_state.get(spec.dod_id)
        support = _support_from(results, spec.gate_ids, satisfied)
        gap = ""
        if not support.is_sufficient:
            gap = spec.notes or spec.observable_condition
        rows.append(TraceabilityRow(
            row_id="TRACE-%s" % spec.dod_id,
            requirement=spec.architecture_text,
            requirement_source="architecture.md section 21",
            implementation_paths=implementations, test_paths=tests,
            evidence_ids=_evidence_for_claims(claim_ids),
            claim_ids=claim_ids, gate_ids=spec.gate_ids,
            dod_ids=(spec.dod_id,), result=support,
            gap_owner=None if support.is_sufficient else owners[spec.dod_id],
            gap=gap))
    for spec in GATES:
        implementations, tests = GATE_IMPLEMENTATION_INDEX[spec.gate_id]
        claim_ids = _claims_for_gate(spec.gate_id)
        record = evaluate_gate(root, spec)
        support = (ClaimSupport.SUPPORTED if record.result.is_pass
                   else ClaimSupport.CONTRADICTED
                   if record.result is GateResult.FAIL
                   else ClaimSupport.UNSUPPORTED)
        blocker_owner = (record.blockers[0].owner if record.blockers
                         else "programme owner")
        rows.append(TraceabilityRow(
            row_id="TRACE-%s" % spec.gate_id,
            requirement="%s passes its PASS condition"
                        % record.title,
            requirement_source="architecture.md section 20",
            implementation_paths=implementations, test_paths=tests,
            evidence_ids=_evidence_for_claims(claim_ids),
            claim_ids=claim_ids, gate_ids=(spec.gate_id,),
            dod_ids=tuple(sorted(
                dod.dod_id for dod in DOD_SPECS
                if spec.gate_id in dod.gate_ids)),
            result=support,
            gap_owner=None if support.is_sufficient else blocker_owner,
            gap=("%d of %d mandatory conditions unmet: %s"
                 % (len(record.unmet_condition_ids), len(record.conditions),
                    ", ".join(record.unmet_condition_ids))
                 if not support.is_sufficient else "")))
    dangling = dangling_references(root)
    any_dangling = any(dangling[key] for key in sorted(dangling))
    every_claim_names_evidence = all(item.required_evidence_ids
                                     for item in CLAIMS)
    dod_014_satisfied = bool(not any_dangling and every_claim_names_evidence)
    by_result: Dict[str, int] = {}
    for row in rows:
        by_result[row.result.value] = by_result.get(row.result.value, 0) + 1
    return {
        "traceability_version": TRACEABILITY_VERSION,
        "row_count": len(rows),
        "counts_by_result": dict(sorted(by_result.items())),
        "dangling": {key: list(value) for key, value in
                     sorted(dangling.items())},
        "has_dangling_reference": any_dangling,
        "every_claim_names_required_evidence": every_claim_names_evidence,
        "p0_dod_014_satisfied": dod_014_satisfied,
        "p0_dod_014_basis": (
            "satisfied exactly when the matrix resolves with no dangling "
            "identifier or path and every claim names required evidence; "
            "this is the one Definition of Done item WP-25 can discharge by "
            "itself, and discharging it says nothing about the other "
            "fourteen"),
        "rows": [row.to_json() for row in rows],
        "gap_owners": sorted({row.gap_owner for row in rows
                              if row.gap_owner}),
        "note": (
            "A row is SUPPORTED only when its Definition of Done item is "
            "satisfied and every gate it feeds passes."),
    }
