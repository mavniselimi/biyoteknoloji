# -*- coding: utf-8 -*-
"""Driving every control through its evaluator, for the safety gate.

``pgx/safety`` never imports this module at import time. It is loaded lazily,
by name, when the gate is asked to execute controls - and when it is absent,
the gate reports ``NOT_EXECUTED`` rather than assuming anything.

That is the honest arrangement for a shipped wheel: ``pgx`` ships without
``tests``, so a deployed copy genuinely cannot run the negative controls, and
the gate says so instead of quietly inheriting a result from somebody else's
machine.

Each entry returns a ``ControlOutcome``: for a safe control, "the evaluator
accepted it"; for a negative control, "the evaluator rejected it, with this
code". The evaluator is the same function in both cases - that is the whole
point of the exercise.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Sequence

from pgx.safety.controls import NEGATIVE_CONTROLS, controls_for
from pgx.safety.evaluators import (
    evaluate_absence_never_reassures,
    evaluate_conflict_is_preserved,
    evaluate_deterministic_result,
    evaluate_findings_are_evidence_backed,
    evaluate_no_candidate_preference,
    evaluate_no_prohibited_claim,
    evaluate_no_real_patient_data,
    evaluate_only_validated_rules_execute,
    evaluate_partition_separation,
    evaluate_persistence_requires_complete_bundle,
    evaluate_phenotype_matching_is_exact,
    evaluate_renderer_preserves_facts,
)
from pgx.safety.execution import ControlOutcome
from pgx.safety.vocabulary import InvariantId

from tests.fixtures.wp20 import (unsafe_candidates, unsafe_conflict,
                                 unsafe_determinism, unsafe_engine,
                                 unsafe_evidence, unsafe_input,
                                 unsafe_matcher, unsafe_partition,
                                 unsafe_persistence, unsafe_renderer,
                                 unsafe_ruleset, unsafe_text)


def _instantiate(subject: Any) -> Any:
    """Some unsafe subjects are classes holding state; most are functions."""
    return subject() if isinstance(subject, type) else subject


# -- one closure per invariant: (safe subject, unsafe subject) -> Verdict ----

def _evaluators(root: str) -> Mapping[InvariantId, Dict[str, Any]]:
    from tests.unit.safety import _support as wiring

    return {
        InvariantId.INV_001: {
            "safe": wiring.production_aggregator(),
            "run": lambda subject: evaluate_absence_never_reassures(
                subject, wiring.coverage_values(), wiring.attention_values(),
                wiring.full_coverage()),
            "unsafe": unsafe_engine.UNSAFE_SUBJECTS,
        },
        InvariantId.INV_002: {
            "safe": unsafe_renderer.SAFE_SUBJECT,
            "run": lambda subject: evaluate_renderer_preserves_facts(
                subject, unsafe_renderer.sample_reports()),
            "unsafe": unsafe_renderer.UNSAFE_SUBJECTS,
        },
        InvariantId.INV_003: {
            "safe": wiring.production_rule_selector(),
            "run": lambda subject: evaluate_only_validated_rules_execute(
                subject, unsafe_ruleset.rule_set(),
                unsafe_ruleset.PINNED_RULESET),
            "unsafe": unsafe_ruleset.UNSAFE_SUBJECTS,
        },
        InvariantId.INV_004: {
            "safe": wiring.production_matcher(),
            "run": lambda subject: evaluate_phenotype_matching_is_exact(
                subject, wiring.phenotype_values()),
            "unsafe": unsafe_matcher.UNSAFE_SUBJECTS,
        },
        InvariantId.INV_005: {
            "safe": unsafe_candidates.SAFE_SUBJECT,
            "run": lambda subject: evaluate_no_candidate_preference(
                [subject()]),
            "unsafe": unsafe_candidates.UNSAFE_SUBJECTS,
        },
        InvariantId.INV_006: {
            "safe": unsafe_evidence.SAFE_SUBJECT,
            "run": lambda subject: evaluate_findings_are_evidence_backed(
                subject, unsafe_evidence.candidate_findings(),
                unsafe_evidence.evidence_index(),
                unsafe_evidence.PINNED_DATASET),
            "unsafe": unsafe_evidence.UNSAFE_SUBJECTS,
        },
        InvariantId.INV_007: {
            "safe": unsafe_persistence.SafeStore,
            "run": lambda subject:
                evaluate_persistence_requires_complete_bundle(
                    _instantiate(subject),
                    unsafe_persistence.complete_record()),
            "unsafe": unsafe_persistence.UNSAFE_SUBJECTS,
        },
        InvariantId.INV_008: {
            "safe": unsafe_conflict.SAFE_SUBJECT,
            "run": lambda subject: evaluate_conflict_is_preserved(
                subject, unsafe_conflict.conflict_groups(),
                unsafe_conflict.PRECEDENCE),
            "unsafe": unsafe_conflict.UNSAFE_SUBJECTS,
        },
        InvariantId.INV_009: {
            "safe": wiring.production_partition_auditor(),
            "run": lambda subject: evaluate_partition_separation(
                subject, _partition_sets()),
            "unsafe": unsafe_partition.UNSAFE_SUBJECTS,
        },
        InvariantId.INV_010: {
            "safe": wiring.production_claim_scanner(),
            "run": lambda subject: evaluate_no_prohibited_claim(
                subject, unsafe_text.SURFACES),
            "unsafe": {"NC-INV-010-REPORT-CARRIES-RECOMMENDATION":
                       unsafe_text.permissive_scanner,
                       "NC-INV-010-API-STRING-CARRIES-DOSE":
                       unsafe_text.permissive_scanner,
                       "NC-INV-010-TEMPLATE-CARRIES-REASSURANCE":
                       unsafe_text.permissive_scanner},
        },
        InvariantId.INV_011: {
            "safe": wiring.production_input_detector(),
            "run": lambda subject: evaluate_no_real_patient_data(
                subject, unsafe_input.payload_cases()),
            "unsafe": {"NC-INV-011-NESTED-GENOTYPE-FIELD":
                       unsafe_input.top_level_only_detector,
                       "NC-INV-011-PATIENT-IDENTIFIER":
                       (lambda payload: ()),
                       "NC-INV-011-RAW-SEQUENCING-PAYLOAD":
                       (lambda payload: ()),
                       "NC-INV-011-PILOT-MODE-REQUESTED":
                       (lambda payload: ())},
        },
        InvariantId.INV_012: {
            "safe": wiring.production_canonical_engine(),
            "run": lambda subject: evaluate_deterministic_result(
                _instantiate(subject), unsafe_determinism.base_input(),
                unsafe_determinism.orderings()),
            "unsafe": unsafe_determinism.UNSAFE_SUBJECTS,
        },
    }


def _partition_sets():
    from tests.unit.safety.test_invariant_009 import _case_sets
    return _case_sets()


def run_controls(root: str) -> Mapping[str, Sequence[ControlOutcome]]:
    """Every control, through its evaluator. Keyed by invariant identifier.

    For invariants 010 and 011 the *detector* is the mutant rather than the
    payload: the unsafe case is a scanner whose registry was emptied, or a
    field walker that stops at depth one. Both are recorded against the same
    control identifiers, because the question - "would this be caught?" - is
    the same one.
    """
    wired = _evaluators(root)
    found: Dict[str, List[ControlOutcome]] = {}

    for invariant, spec in wired.items():
        outcomes: List[ControlOutcome] = []

        safe_verdict = spec["run"](_instantiate(spec["safe"]))
        outcomes.append(ControlOutcome(
            control_id="SC-%s" % invariant.value,
            kind="SAFE",
            detected=(not safe_verdict.compliant),
            expected_refusal_code="",
            observed_refusal_code=safe_verdict.refusal_code,
            detail=("the safe control was accepted"
                    if safe_verdict.compliant
                    else "the safe control was REJECTED: %s"
                         % safe_verdict.detail)))

        for control in controls_for(invariant):
            subject = spec["unsafe"].get(control.control_id)
            if subject is None:
                outcomes.append(ControlOutcome(
                    control.control_id, "NEGATIVE", None,
                    control.expected_refusal_code, "",
                    "no unsafe subject is wired for this control"))
                continue
            verdict = spec["run"](subject)
            outcomes.append(ControlOutcome(
                control_id=control.control_id,
                kind="NEGATIVE",
                detected=(not verdict.compliant),
                expected_refusal_code=control.expected_refusal_code,
                observed_refusal_code=verdict.refusal_code,
                detail=verdict.detail))

        found[invariant.value] = outcomes

    return found


def declared_control_count() -> int:
    return len(NEGATIVE_CONTROLS)


def claim_surface_facts() -> Mapping[str, Any]:
    """How many user-facing surfaces the claim gate covers, and its known gaps.

    Lives here rather than in ``pgx.safety.report`` because the surfaces and
    the gap list are fixture data, and nothing under ``pgx`` may name a test
    fixture - not even inside a function.

    ``known_gap_count`` is a finding about ``pgx/domain/claims.py`` carried
    forward rather than resolved: the pattern registry is a reviewed governance
    artifact, and adding clinical phrasings to it on an implementer's judgement
    would be the unreviewed claim the system exists to prevent.
    """
    return {
        "surface_count": len(unsafe_text.SURFACES),
        "blocking_surface_count": sum(1 for _, _, blocking
                                      in unsafe_text.SURFACES if blocking),
        "known_gap_count": len(unsafe_text.KNOWN_SCANNER_GAPS),
        "known_gaps": [label for label, _ in unsafe_text.KNOWN_SCANNER_GAPS],
        "reason": "",
    }
