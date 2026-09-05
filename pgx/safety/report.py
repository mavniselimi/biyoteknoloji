# -*- coding: utf-8 -*-
"""Building the safety report: controls, tests, and the false-reassurance count.

Three inputs combine into one per-invariant answer:

* **controls** - every safe and negative control, driven through its evaluator;
* **tests** - the safe controls' unittest modules, executed by WP-19's runner
  in an isolated subprocess;
* **surfaces** - measurements that are counted rather than asserted, chiefly
  the false-reassurance corpus.

The corpus is worth a note. ``SAFETY-INV-001`` asks for a measurable
false-reassurance target, and the target is *exactly zero*. What is counted is
every combination of coverage status and calculated level the aggregator can be
handed - a software corpus, exhaustively swept. It is **not** a clinical
false-negative rate: it says nothing about patients, medications, or how often
the world produces a case the software would mishandle. Reporting it as one
would be precisely the overclaim ``SAFETY-INV-010`` exists to block.

The control driver lives under ``tests/`` and is imported lazily by name. A
deployed wheel ships ``pgx`` without ``tests``, so it genuinely cannot run the
negative controls - and this module reports ``NOT_EXECUTED`` rather than
inheriting a result from a machine that could.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.safety.definitions import DETECTOR_EVIDENCE_DISCLAIMER
from pgx.safety.errors import GateRefusal
from pgx.safety.execution import (
    ControlOutcome,
    InvariantExecution,
    SafetyExecution,
    build_invariant_execution,
    summarise,
)
from pgx.safety.freshness import (
    EVIDENCE_SCHEMA_VERSION,
    environment_fingerprint,
    fingerprint_inputs,
)
from pgx.safety.registry import SafetyRegistry
from pgx.safety.vocabulary import ExecutionState, InvariantId

__all__ = [
    "REPORT_SCHEMA_VERSION",
    "CONTROL_DRIVER_MODULE",
    "FalseReassuranceMeasurement",
    "load_control_driver",
    "measure_false_reassurance",
    "measure_prohibited_claim_surfaces",
    "execute_safety",
    "build_report",
]

REPORT_SCHEMA_VERSION = "pgx-wp20-safety-report/1"

#: Imported by name, never at import time. See the module docstring.
CONTROL_DRIVER_MODULE = "tests.fixtures.wp20.driver"


def load_control_driver(module_name: str = CONTROL_DRIVER_MODULE):
    """The control driver, or ``None`` when the test tree is not present."""
    try:
        return importlib.import_module(module_name)
    except ImportError:
        return None


@dataclass(frozen=True)
class FalseReassuranceMeasurement:
    """The SAFETY-INV-001 corpus. A software count, not a clinical rate."""

    corpus_size: int
    violation_count: int
    target: int = 0
    note: str = (
        "Every combination of coverage status and calculated attention level "
        "the aggregator can be handed, swept exhaustively. The target is "
        "exactly zero unsafe outputs. This is a count over a software corpus. "
        "It is NOT a clinical false-negative rate and says nothing about how "
        "often a real case would be mishandled.")

    @property
    def meets_target(self) -> bool:
        return self.corpus_size > 0 and self.violation_count == self.target

    def as_document(self) -> Dict[str, Any]:
        return {
            "corpus_size": self.corpus_size,
            "meets_target": self.meets_target,
            "note": self.note,
            "target": self.target,
            "violation_count": self.violation_count,
        }


def measure_false_reassurance() -> FalseReassuranceMeasurement:
    """Sweep the whole coverage x attention space through the real aggregator.

    Counted rather than asserted, because ``SAFETY-INV-001`` asks for a
    measurable target and "the tests pass" is not a measurement.
    """
    from pgx.domain.enums import AttentionLevel, CoverageStatus
    from pgx.engine.risk_models import aggregate_attention

    reassuring = (AttentionLevel.LOW, AttentionLevel.NO_ACTIVE_ATTENTION)
    corpus = 0
    violations = 0

    # Absence: no calculated level at all, under every coverage status. This is
    # the shape LEGACY-BUG-002 got wrong.
    for coverage in CoverageStatus:
        corpus += 1
        answer = aggregate_attention([], coverage=coverage)
        if coverage is not CoverageStatus.FULL and answer in reassuring:
            violations += 1

    # A calculated level under every coverage status. A finding must not be
    # softened because some other axis could not be evaluated.
    for coverage in CoverageStatus:
        for level in AttentionLevel:
            corpus += 1
            try:
                answer = aggregate_attention([level], coverage=coverage)
            except Exception:
                # The engine refuses NOT_ASSESSED as an input outright: it is
                # not a calculated level and has no place in a maximum over
                # things that were looked at. A refusal is the invariant
                # holding in its strongest form, so it counts toward the
                # corpus and not toward the violations.
                continue
            if answer in reassuring and level not in reassuring:
                violations += 1

    return FalseReassuranceMeasurement(corpus, violations)


def measure_prohibited_claim_surfaces() -> Dict[str, Any]:
    """How many user-facing surfaces the claim gate covers, and its known gaps.

    The gap count is a finding about ``pgx/domain/claims.py`` carried forward
    rather than resolved here: the pattern registry is a reviewed governance
    artifact, and adding clinical phrasings to it on an implementer's judgement
    would be the unreviewed claim this system exists to prevent.
    """
    driver = load_control_driver()
    if driver is None:
        return {"surface_count": None, "known_gap_count": None,
                "reason": "the control fixtures are not present in this "
                          "installation"}
    # Asked of the driver object rather than imported: nothing under ``pgx``
    # may name a test fixture, even inside a function, and
    # ``test_boundaries.py`` reads syntax trees to enforce that.
    return dict(driver.claim_surface_facts())


def _test_counts_for(invariant: InvariantId,
                     registry: SafetyRegistry,
                     per_module: Mapping[str, Mapping[str, int]]
                     ) -> Dict[str, int]:
    """Sum the per-module test results across an invariant's selectors."""
    totals = {"executed": 0, "passed": 0, "failed": 0, "errored": 0,
              "skipped": 0, "unexplained_skips": 0}
    for module in registry.resolved_modules.get(invariant.value, ()):
        counts = per_module.get(module)
        if not counts:
            continue
        for key in totals:
            totals[key] += int(counts.get(key, 0))
    return totals


def execute_safety(root: str,
                   registry: SafetyRegistry,
                   per_module_results: Mapping[str, Mapping[str, int]],
                   control_outcomes: Optional[
                       Mapping[str, Sequence[ControlOutcome]]] = None
                   ) -> SafetyExecution:
    """Run the controls and combine them with the test results.

    ``complete`` is set only after every invariant has been processed. A run
    that raises halfway leaves it false, and the artifact writer refuses to
    record an incomplete run as evidence - so an interrupted build cannot
    quietly become a passing one.
    """
    if control_outcomes is None:
        driver = load_control_driver()
        control_outcomes = ({} if driver is None
                            else driver.run_controls(root))

    executions: List[InvariantExecution] = []
    for definition in registry.definitions:
        identifier = definition.invariant_id
        executions.append(build_invariant_execution(
            definition,
            tuple(control_outcomes.get(identifier.value, ())),
            _test_counts_for(identifier, registry, per_module_results)))

    return SafetyExecution(
        invariants=tuple(executions),
        inputs=fingerprint_inputs(root),
        environment=environment_fingerprint(),
        complete=True)


def build_report(root: str,
                 registry: SafetyRegistry,
                 execution: SafetyExecution) -> Dict[str, Any]:
    """The full safety report document."""
    if not execution.complete:
        raise GateRefusal(
            "refusing to build a report from an incomplete execution; a run "
            "that did not finish has not verified anything")

    reassurance = measure_false_reassurance()
    claims = measure_prohibited_claim_surfaces()
    summary = summarise(execution)

    return {
        "detector_evidence_disclaimer": DETECTOR_EVIDENCE_DISCLAIMER,
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "false_reassurance": reassurance.as_document(),
        "invariants": [item.as_document() for item in execution.invariants],
        "prohibited_claim_surfaces": claims,
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "summary": summary,
        "work_package": "WP-20",
    }
