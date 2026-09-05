# -*- coding: utf-8 -*-
"""Running the safety checks, and recording what actually happened.

Execution reuses WP-19 rather than building a second test runner. The
invariants' safe and negative controls are ordinary unittest modules; WP-19
already knows how to discover them, run them in an isolated subprocess with a
fixed hash seed, and report exact per-test outcomes. Duplicating that here
would produce two enumerations of one suite that could disagree, and the first
time they disagreed nobody would know which to believe.

What this module adds is the part WP-19 deliberately does not do: deciding, per
invariant, whether the invariant is **enforced** - which needs the negative
controls to have been detected, not merely for the tests to have passed.

Four states come out of it, and they are kept apart:

* ``PASS`` - the safe control ran and held, every negative control was
  detected, and no relevant test failed, errored or skipped without permission.
* ``FAIL`` - something ran and did not hold.
* ``BLOCKED`` - a later work package or an absent dependency owns part of the
  enforcement.
* ``NOT_EXECUTED`` - nothing ran. Never folded into ``PASS``; a gate that
  reports success for checks it never performed is worse than no gate, because
  it is trusted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.safety.definitions import InvariantDefinition
from pgx.safety.registry import SafetyRegistry
from pgx.safety.vocabulary import (
    ComplianceState,
    ExecutionState,
    InvariantId,
    Severity,
)

__all__ = [
    "ControlOutcome",
    "InvariantExecution",
    "SafetyExecution",
    "build_invariant_execution",
    "summarise",
]


@dataclass(frozen=True)
class ControlOutcome:
    """What happened to one control."""

    control_id: str
    #: ``SAFE`` controls must pass; ``NEGATIVE`` controls must be *detected*.
    kind: str
    detected: Optional[bool]
    expected_refusal_code: str = ""
    observed_refusal_code: str = ""
    detail: str = ""

    @property
    def satisfied(self) -> bool:
        """Whether this control did what it was supposed to.

        ``None`` - the control did not run - is never satisfied. That is the
        distinction between "the mutant was caught" and "nobody tried".
        """
        if self.detected is None:
            return False
        if self.kind == "SAFE":
            return self.detected is False        # the safe case was accepted
        return (self.detected is True
                and self.observed_refusal_code == self.expected_refusal_code)

    def as_document(self) -> Dict[str, Any]:
        return {
            "control_id": self.control_id,
            "detail": self.detail,
            "detected": self.detected,
            "expected_refusal_code": self.expected_refusal_code,
            "kind": self.kind,
            "observed_refusal_code": self.observed_refusal_code,
            "satisfied": self.satisfied,
        }


@dataclass(frozen=True)
class InvariantExecution:
    """One invariant's complete result, with nothing collapsed."""

    invariant_id: InvariantId
    registered: bool
    execution_state: ExecutionState
    compliance_state: ComplianceState
    severity: Severity
    #: Tests that exercise the safe control, and what they did.
    tests_executed: int
    tests_passed: int
    tests_failed: int
    tests_errored: int
    tests_skipped: int
    unexplained_skips: int
    controls: Tuple[ControlOutcome, ...]
    blockers: Tuple[Mapping[str, Any], ...] = ()
    refusal_code: str = ""
    reason: str = ""

    @property
    def negative_controls(self) -> Tuple[ControlOutcome, ...]:
        return tuple(c for c in self.controls if c.kind == "NEGATIVE")

    @property
    def detected_count(self) -> int:
        return sum(1 for c in self.negative_controls if c.satisfied)

    @property
    def all_controls_satisfied(self) -> bool:
        return bool(self.controls) and all(c.satisfied for c in self.controls)

    def as_document(self) -> Dict[str, Any]:
        return {
            "all_controls_satisfied": self.all_controls_satisfied,
            "blockers": [dict(b) for b in self.blockers],
            "compliance_state": self.compliance_state.value,
            "control_count": len(self.controls),
            "controls": [c.as_document() for c in self.controls],
            "detected_negative_controls": self.detected_count,
            "execution_state": self.execution_state.value,
            "invariant_id": self.invariant_id.value,
            "negative_control_count": len(self.negative_controls),
            "reason": self.reason,
            "refusal_code": self.refusal_code,
            "registered": self.registered,
            "severity": self.severity.value,
            "tests": {
                "errored": self.tests_errored,
                "executed": self.tests_executed,
                "failed": self.tests_failed,
                "passed": self.tests_passed,
                "skipped": self.tests_skipped,
                "unexplained_skips": self.unexplained_skips,
            },
        }


def build_invariant_execution(definition: InvariantDefinition,
                              controls: Sequence[ControlOutcome],
                              test_counts: Mapping[str, int]
                              ) -> InvariantExecution:
    """Decide one invariant's state from its controls and its test results.

    The order of the checks is the order of the questions somebody would ask,
    and each one can only make the answer worse:

    1. Did anything run at all?          -> ``NOT_EXECUTED``
    2. Did a relevant test break?        -> ``FAIL``
    3. Was a negative control missed?    -> ``FAIL``
    4. Does a later WP own part of it?   -> ``BLOCKED``
    5. Otherwise                          -> ``PASS``

    Step 3 is the one that distinguishes this gate from an ordinary test run. A
    suite where every test passes but a mutant slipped through has *not*
    demonstrated the invariant; it has demonstrated that the tests agree with
    the code, which is a much weaker statement.
    """
    executed = int(test_counts.get("executed", 0))
    failed = int(test_counts.get("failed", 0))
    errored = int(test_counts.get("errored", 0))
    skipped = int(test_counts.get("skipped", 0))
    unexplained = int(test_counts.get("unexplained_skips", 0))
    passed = int(test_counts.get("passed", 0))

    blockers = tuple(blocker.as_document() for blocker in definition.blockers)
    negative = [c for c in controls if c.kind == "NEGATIVE"]
    undetected = [c for c in negative if not c.satisfied]
    unsatisfied_safe = [c for c in controls
                        if c.kind == "SAFE" and not c.satisfied]

    if executed == 0 or not controls:
        return InvariantExecution(
            definition.invariant_id, True, ExecutionState.NOT_EXECUTED,
            ComplianceState.UNKNOWN, definition.severity, executed, passed,
            failed, errored, skipped, unexplained, tuple(controls), blockers,
            definition.refusal_code,
            "nothing was executed for this invariant; a gate that reports "
            "success for a check it never performed is worse than no gate")

    if failed or errored or unexplained:
        return InvariantExecution(
            definition.invariant_id, True, ExecutionState.FAIL,
            ComplianceState.VIOLATED, definition.severity, executed, passed,
            failed, errored, skipped, unexplained, tuple(controls), blockers,
            definition.refusal_code,
            "%d failed, %d errored, %d skipped without permission"
            % (failed, errored, unexplained))

    if undetected:
        return InvariantExecution(
            definition.invariant_id, True, ExecutionState.FAIL,
            ComplianceState.VIOLATED, definition.severity, executed, passed,
            failed, errored, skipped, unexplained, tuple(controls), blockers,
            definition.refusal_code,
            "the detector accepted %d negative control(s) it exists to "
            "reject: %s" % (len(undetected),
                            ", ".join(c.control_id for c in undetected)))

    if unsatisfied_safe:
        return InvariantExecution(
            definition.invariant_id, True, ExecutionState.FAIL,
            ComplianceState.VIOLATED, definition.severity, executed, passed,
            failed, errored, skipped, unexplained, tuple(controls), blockers,
            definition.refusal_code,
            "the safe control was rejected by its own detector: %s"
            % ", ".join(c.control_id for c in unsatisfied_safe))

    if blockers:
        return InvariantExecution(
            definition.invariant_id, True, ExecutionState.BLOCKED,
            definition.implementation_state, definition.severity, executed,
            passed, failed, errored, skipped, unexplained, tuple(controls),
            blockers, definition.refusal_code,
            "every executable check passed; enforcement is incomplete because "
            "%s" % "; ".join(str(b.get("detail", "")) for b in blockers))

    return InvariantExecution(
        definition.invariant_id, True, ExecutionState.PASS,
        definition.implementation_state, definition.severity, executed,
        passed, failed, errored, skipped, unexplained, tuple(controls),
        blockers, "", "")


@dataclass(frozen=True)
class SafetyExecution:
    """Every invariant's result from one run of the gate."""

    invariants: Tuple[InvariantExecution, ...]
    inputs: Mapping[str, str]
    environment: Mapping[str, Any]
    #: True only when the run reached the end. A run that died halfway must
    #: never be written as evidence, or an interrupted build silently becomes
    #: a passing one.
    complete: bool = False

    def by_id(self) -> Mapping[str, InvariantExecution]:
        return {item.invariant_id.value: item for item in self.invariants}

    def as_document(self) -> Dict[str, Any]:
        return {
            "complete": self.complete,
            "environment": dict(self.environment),
            "inputs": dict(self.inputs),
            "invariants": [item.as_document() for item in self.invariants],
        }


def summarise(execution: SafetyExecution) -> Dict[str, Any]:
    """Counts across all twelve, each independent of the others."""
    states: Dict[str, int] = {}
    for item in execution.invariants:
        key = item.execution_state.value
        states[key] = states.get(key, 0) + 1
    negative = [c for item in execution.invariants
                for c in item.negative_controls]
    return {
        "detected_negative_control_count": sum(1 for c in negative
                                               if c.satisfied),
        "execution_states": dict(sorted(states.items())),
        "executed_invariant_count": sum(
            1 for item in execution.invariants
            if item.execution_state is not ExecutionState.NOT_EXECUTED),
        "negative_control_count": len(negative),
        "registered_invariant_count": len(execution.invariants),
        "tests_executed": sum(item.tests_executed
                              for item in execution.invariants),
    }
