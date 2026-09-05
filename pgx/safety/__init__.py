# -*- coding: utf-8 -*-
"""WP-20 - the safety invariant suite.

Twelve invariants from ``docs/risk-management/safety-contract.md``, as an
authoritative, machine-readable, executable, release-blocking gate.

The question this package answers is not "did the tests pass". WP-19 answers
that. It is: **is each named invariant actually enforced, and can its detector
prove it would catch the unsafe case?** Those come apart - a suite can be
entirely green while an invariant has no detector at all, because nothing fails
when nothing looks.

So every invariant carries two executions that must both happen: a conforming
**safe control** that passes through the real evaluator, and a deliberately
unsafe **negative control** that the same evaluator must reject with a named
code. Asserting that a mutant fixture contains unsafe text proves something
about the fixture and nothing about the detector.

What this package will not claim: detecting a negative control is evidence that
a software detector works. It is not clinical validation, scientific
validation, expert review, or evidence that the system is safe for any patient.

Framework-free by construction: no database, no network, no LLM, no web
framework. The thing that decides whether a release is safe must run where
nothing can be installed.
"""

from __future__ import annotations

from pgx.safety.controls import (
    CONTROL_CATALOGUE_VERSION,
    NEGATIVE_CONTROLS,
    NegativeControl,
    controls_by_id,
    controls_for,
)
from pgx.safety.definitions import (
    DETECTOR_EVIDENCE_DISCLAIMER,
    INVARIANT_DEFINITIONS,
    Blocker,
    InvariantDefinition,
    definitions_by_id,
)
from pgx.safety.errors import (
    DuplicateInvariant,
    EvidenceError,
    GateRefusal,
    InvariantNotRegistered,
    NegativeControlMissing,
    NegativeControlNotDetected,
    RegistryError,
    SafetyError,
    SelectorError,
    StaleEvidence,
    UnknownInvariant,
)
from pgx.safety.registry import (
    SafetyRegistry,
    load_registry,
    selector_matches,
    validate_registry,
)
from pgx.safety.vocabulary import (
    INVARIANT_IDS,
    REGISTRY_VERSION,
    BlockerOwner,
    ComplianceState,
    ControlKind,
    EnforcementSurface,
    ExecutionState,
    InvariantId,
    Severity,
    is_release_permitting,
)

__all__ = [
    "CONTROL_CATALOGUE_VERSION",
    "DETECTOR_EVIDENCE_DISCLAIMER",
    "INVARIANT_DEFINITIONS",
    "INVARIANT_IDS",
    "NEGATIVE_CONTROLS",
    "REGISTRY_VERSION",
    "Blocker",
    "BlockerOwner",
    "ComplianceState",
    "ControlKind",
    "DuplicateInvariant",
    "EnforcementSurface",
    "EvidenceError",
    "ExecutionState",
    "GateRefusal",
    "InvariantDefinition",
    "InvariantId",
    "InvariantNotRegistered",
    "NegativeControl",
    "NegativeControlMissing",
    "NegativeControlNotDetected",
    "RegistryError",
    "SafetyError",
    "SafetyRegistry",
    "SelectorError",
    "Severity",
    "StaleEvidence",
    "UnknownInvariant",
    "controls_by_id",
    "controls_for",
    "definitions_by_id",
    "is_release_permitting",
    "load_registry",
    "selector_matches",
    "validate_registry",
]
