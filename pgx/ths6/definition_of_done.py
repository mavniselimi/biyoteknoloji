# -*- coding: utf-8 -*-
"""The P0 Definition of Done, all fifteen items (WP-25).

``architecture.md`` section 21 enumerates fifteen bullets. WP-25's own brief
describes them as "all 14 THS 6 Definition of Done items". Those two counts
disagree, and this module resolves the disagreement in the only direction that
cannot lose a requirement: **all fifteen are implemented and evaluated**, and
the discrepancy is emitted as a finding with an owner rather than quietly
reconciled by merging two bullets or renumbering the list.

That choice deserves a sentence of defence. Merging bullets 5 and 6 - or
folding "rollback works" into "independently versioned" - would have produced
a registry matching the declared count, and would have made a requirement
disappear from a document whose purpose is to show that no requirement
disappeared. A visible disagreement is cheaper than a missing obligation.

Each item carries the architecture bullet **verbatim**, so a reader with the
architecture document open can check the transcription, and separately an
*observable condition*: what would have to be true, written so that it can be
read from an artifact rather than argued about.

Nothing here aggregates. There is no "13 of 15 satisfied, therefore mostly
done" - the registry reports each item and the counts, and only a gate is
permitted to draw a conjunction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.ths6.gate_matrix import evaluate_gate, GATES
from pgx.ths6.models import DefinitionOfDoneItem, Finding
from pgx.ths6.vocabulary import Blocker, GateResult

__all__ = [
    "ARCHITECTURE_SECTION",
    "DECLARED_COUNT_IN_WP25_PROSE",
    "DOD_REGISTRY_VERSION",
    "DOD_SPECS",
    "build_definition_of_done",
    "count_mismatch_finding",
]

DOD_REGISTRY_VERSION = "pgx-wp25-definition-of-done/1"

#: Where the bullets are enumerated.
ARCHITECTURE_SECTION = ("architecture.md, section 21, "
                        "Definition of Done for the complete P0 program")

#: What WP-25's own prose declared. Kept as a named constant so the
#: discrepancy is data rather than a sentence in a report.
DECLARED_COUNT_IN_WP25_PROSE = 14


@dataclass(frozen=True)
class DodSpec:
    """One bullet before evaluation."""

    dod_id: str
    architecture_text: str
    observable_condition: str
    gate_ids: Tuple[str, ...]
    #: The gate conditions whose failure makes this item unsatisfied. Named
    #: individually so an item is not marked unsatisfied merely because its
    #: gate is blocked for an unrelated reason.
    condition_ids: Tuple[str, ...]
    owner: str
    notes: str = ""


#: The fifteen bullets, transcribed verbatim from section 21 in order.
DOD_SPECS: Tuple[DodSpec, ...] = (
    DodSpec(
        "P0-DOD-001",
        "One integrated web prototype runs the representative workflow.",
        "the web prototype computes and displays an assessment produced from "
        "governed content, end to end, at least once",
        ("GATE-C",), ("C9", "C1"), "platform owner",
        "the prototype exists and renders; what it has never rendered is a "
        "result computed from an approved dataset and ruleset"),
    DodSpec(
        "P0-DOD-002",
        "Assessment facts are deterministic for the same release and input.",
        "the same input, evaluated twice against the same release, produces "
        "byte-identical facts - which requires a release to exist",
        ("GATE-C",), ("C8", "C1"), "release approver",
        "determinism is demonstrated over fixtures; 'for the same release' "
        "has no referent while no release is active"),
    DodSpec(
        "P0-DOD-003",
        "Every finding has traceable evidence.",
        "each finding in a produced report resolves to a governed evidence "
        "record",
        ("GATE-C",), ("C4",), "curation lead",
        "no report has been produced, so the property holds vacuously and is "
        "recorded as unsatisfied rather than as met"),
    DodSpec(
        "P0-DOD-004",
        "Missing data is never shown as low/no risk; coverage is separate.",
        "coverage is computed over governed content and rendered as its own "
        "axis, never folded into a risk value",
        ("GATE-C",), ("C2", "C3"), "curation lead",
        "the invariant is implemented and proven over fixtures; it has never "
        "been exercised over governed content because none exists"),
    DodSpec(
        "P0-DOD-005",
        "Software, dataset, and ruleset are independently versioned and "
        "rollback works.",
        "three independent version identifiers exist for one running system, "
        "and a rollback between two released versions has been executed",
        ("GATE-A", "GATE-B", "GATE-E"), ("A2", "B5", "E6"),
        "release approver",
        "the registry design is implemented; no dataset is published, no "
        "ruleset is frozen, and no rollback has been executed"),
    DodSpec(
        "P0-DOD-006",
        "At least 50 serious validation cases exist, with a preference for "
        "100+.",
        "the validation case store holds at least fifty authored cases",
        ("GATE-D",), ("D1",), "validation owner",
        "zero exist; the seven development cases are excluded by contract "
        "and must never be counted towards this bullet"),
    DodSpec(
        "P0-DOD-007",
        "An independent holdout set was not used for rule development.",
        "a holdout set exists and the separation audit shows no case in it "
        "influenced rule development",
        ("GATE-D",), ("D2",), "validation owner",
        "the separation audit runs and passes over seven development cases, "
        "which is a check with nothing to separate them from"),
    DodSpec(
        "P0-DOD-008",
        "All safety invariants pass in CI.",
        "a continuous integration provider has executed the safety gate and "
        "recorded every invariant passing",
        ("GATE-C",), ("C6", "C5"), "platform owner",
        "twelve invariants execute locally and pass; the workflow file is "
        "configured and has never been run by a provider"),
    DodSpec(
        "P0-DOD-009",
        "Blind-first expert review is completed under the approved protocol.",
        "the protocol carries a signatory and at least one blind-first "
        "review is recorded complete",
        ("GATE-D",), ("D6", "D8"), "expert review chair",
        "the review machinery is implemented and empty; no protocol "
        "signatory and no named reviewer exist"),
    DodSpec(
        "P0-DOD-010",
        "Experts use the representative workflow, not only static reports.",
        "a completed review records that the reviewer used the interactive "
        "workflow",
        ("GATE-D",), ("D7", "D9"), "expert review chair",
        "an eight-step workflow is implemented; nobody has walked it"),
    DodSpec(
        "P0-DOD-011",
        "Benchmark metrics are release-specific.",
        "at least one metric has a computed value attributed to a named "
        "release",
        ("GATE-D",), ("D3", "D5"), "validation owner",
        "fifteen metric definitions exist and no metric has a value; a "
        "definition is not a measurement"),
    DodSpec(
        "P0-DOD-012",
        "Audit records actor/time/input hash/version bundle/output hash.",
        "governed audit events exist in a real store and the hash chain "
        "verifies",
        ("GATE-E",), ("E4", "E2"), "platform owner",
        "41 governed actions and the chain structure are implemented; no "
        "audit store has ever existed to write one"),
    DodSpec(
        "P0-DOD-013",
        "A staging prototype, health checks, and basic reliability report "
        "exist.",
        "a staging environment has been deployed, its health endpoint "
        "observed answering, and a reliability report produced from executed "
        "drills",
        ("GATE-E",), ("E9", "E7"), "platform owner",
        "the Dockerfile, compose topology, health endpoints and drill "
        "catalogue are implemented; no runtime answered, so nothing was "
        "deployed or measured"),
    DodSpec(
        "P0-DOD-014",
        "Every THS 6 claim links to a concrete artifact or metric.",
        "every registered claim names required evidence, and each named item "
        "resolves to an artifact present in the repository",
        ("GATE-F",), (), "WP-25 evidence owner",
        "this is the one bullet WP-25 itself can satisfy: the claim registry "
        "links every claim to named artifacts, and the traceability matrix "
        "refuses a dangling identifier"),
    DodSpec(
        "P0-DOD-015",
        "Core demo completes with network unavailable, LLM off, and every P1 "
        "feature off.",
        "the representative demonstration runs to completion offline, with "
        "the language model disabled and every P1 feature off, and produces "
        "a result rather than an empty state",
        ("GATE-F",), ("F4",), "platform owner",
        "the interface renders offline with the model off, which is half the "
        "bullet; it renders an empty state because there is no governed "
        "content to display"),
)


def count_mismatch_finding() -> Finding:
    """The declared-versus-enumerated discrepancy, as a first-class finding."""
    return Finding(
        code="THS6_DOD_DECLARED_COUNT_MISMATCH",
        detail="WP-25's own prose declares 14 Definition of Done items; %s "
               "enumerates %d. The two counts disagree."
               % (ARCHITECTURE_SECTION, len(DOD_SPECS)),
        owner="architecture/document owner",
        resolution="all %d enumerated bullets are implemented as P0-DOD-001 "
                   "through P0-DOD-%03d and evaluated separately. No bullet "
                   "was merged, renumbered or discarded to reach the "
                   "declared count. The discrepancy is visible and it "
                   "permits no item to be ignored."
                   % (len(DOD_SPECS), len(DOD_SPECS)),
        blocking=False,
        references=("architecture.md",))


def _pack_links_every_claim(root: str) -> bool:
    """Whether every claim names evidence and no reference dangles.

    This is the observable condition of P0-DOD-014, and the one Definition of
    Done bullet this work package can discharge by itself. Discharging it
    says nothing whatever about the other fourteen.
    """
    from pgx.ths6.claim_registry import CLAIMS
    from pgx.ths6.traceability import dangling_references

    if not all(item.required_evidence_ids for item in CLAIMS):
        return False
    dangling = dangling_references(root)
    return not any(dangling[key] for key in sorted(dangling))


def build_definition_of_done(root: str = ".") -> Mapping[str, object]:
    """Evaluate all fifteen bullets against the gate conditions."""
    conditions: Dict[str, object] = {}
    blockers_by_condition: Dict[str, Blocker] = {}
    for spec in GATES:
        record = evaluate_gate(root, spec)
        for condition in record.conditions:
            conditions[condition.condition_id] = condition.met
        for blocker in record.blockers:
            key = blocker.detail.split(":", 1)[0].strip()
            blockers_by_condition[key] = blocker
    items: List[DefinitionOfDoneItem] = []
    for spec in DOD_SPECS:
        states = [conditions.get(condition_id)
                  for condition_id in spec.condition_ids]
        if not spec.condition_ids:
            # P0-DOD-014 is answered by this pack's own structure rather than
            # by a source artifact: every claim names required evidence and
            # nothing dangles. It is *computed*, not asserted - the import is
            # lazy because traceability imports this module, and a
            # module-level import in both directions would be a cycle.
            satisfied: Optional[bool] = _pack_links_every_claim(root)
        elif any(state is None for state in states):
            satisfied = None
        else:
            satisfied = all(bool(state) for state in states)
        blockers = tuple(
            blockers_by_condition[condition_id]
            for condition_id in spec.condition_ids
            if conditions.get(condition_id) is False
            and condition_id in blockers_by_condition)
        items.append(DefinitionOfDoneItem(
            dod_id=spec.dod_id, architecture_text=spec.architecture_text,
            observable_condition=spec.observable_condition,
            satisfied=satisfied, gate_ids=spec.gate_ids, blockers=blockers,
            owner=spec.owner, notes=spec.notes))
    satisfied_ids = [item.dod_id for item in items if item.satisfied is True]
    unsatisfied_ids = [item.dod_id for item in items
                       if item.satisfied is False]
    unevaluated_ids = [item.dod_id for item in items
                       if item.satisfied is None]
    return {
        "definition_of_done_version": DOD_REGISTRY_VERSION,
        "architecture_section": ARCHITECTURE_SECTION,
        "enumerated_count": len(DOD_SPECS),
        "declared_count_in_wp25_prose": DECLARED_COUNT_IN_WP25_PROSE,
        "count_matches_declaration":
            len(DOD_SPECS) == DECLARED_COUNT_IN_WP25_PROSE,
        "satisfied_count": len(satisfied_ids),
        "unsatisfied_count": len(unsatisfied_ids),
        "unevaluated_count": len(unevaluated_ids),
        "satisfied_dod_ids": satisfied_ids,
        "unsatisfied_dod_ids": unsatisfied_ids,
        "unevaluated_dod_ids": unevaluated_ids,
        "all_items_satisfied": len(satisfied_ids) == len(DOD_SPECS),
        "items": [item.to_json() for item in items],
        "findings": [count_mismatch_finding().to_json()],
        "note": (
            "Every enumerated bullet is evaluated separately. An unevaluated "
            "item is not a satisfied one, and no aggregate here rounds "
            "anything up."),
    }
