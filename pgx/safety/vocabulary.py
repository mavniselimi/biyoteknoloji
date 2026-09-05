# -*- coding: utf-8 -*-
"""The WP-20 safety vocabulary: identifiers, severities, and the states.

Standard library only. The thing that decides whether a release is safe must
run where nothing can be installed, or it only ever judges the environments
that happened to be complete.

The states here are the reason this file exists. A safety gate is under
constant pressure to answer one boolean, and every one of these distinctions
was collapsed at some point in some project's history with a bad outcome:

* ``PASS`` and ``NOT_EXECUTED`` - "no failures" from a run that never happened.
* ``FAIL`` and ``BLOCKED`` - a violated invariant and an unreachable database
  both turn a light red, and treating them alike teaches people to ignore it.
* ``COMPLIANT`` and ``NOT_PRESENT`` - a rule that is enforced, and a feature
  that does not exist yet so cannot break the rule. The second is a legitimate
  P0 answer for an LLM gateway or a candidate ranker, and a dangerous one the
  moment that feature ships.
* ``STALE`` - a real PASS, about code that has since changed.

None of them is ordered, and none is a boolean.
"""

from __future__ import annotations

from enum import Enum
from typing import Tuple

__all__ = [
    "REGISTRY_VERSION",
    "INVARIANT_IDS",
    "InvariantId",
    "Severity",
    "ExecutionState",
    "ComplianceState",
    "ControlKind",
    "EnforcementSurface",
    "BlockerOwner",
    "is_release_permitting",
]

#: Bumped when the *shape* of the registry changes, never for content.
REGISTRY_VERSION = "pgx-wp20-safety-registry/1"

#: The twelve, written out. The architecture asks for "at least 010"; the
#: safety contract defines twelve, and a registry that quietly stopped at ten
#: would drop real-patient-data and determinism - two of the three invariants
#: with the widest blast radius.
INVARIANT_IDS: Tuple[str, ...] = tuple(
    "SAFETY-INV-%03d" % number for number in range(1, 13))


class _SafetyEnum(str, Enum):
    """String-valued, stable in JSON, and explicitly not ordered.

    Ordering is disabled for the same reason WP-19 disables it: the moment
    ``BLOCKED < PASS`` type-checks, somebody writes ``max(states)`` and an
    unverified invariant becomes a verified one.
    """

    def __str__(self) -> str:
        return self.value

    def __lt__(self, other: object) -> bool:  # pragma: no cover - guard
        raise TypeError(
            "%s values are not ordered; ranking safety states as magnitudes is "
            "how an unenforced invariant becomes an enforced one"
            % type(self).__name__)

    __le__ = __lt__
    __gt__ = __lt__
    __ge__ = __lt__


class InvariantId(_SafetyEnum):
    """The twelve invariants, as an enum so a typo cannot invent a thirteenth."""

    INV_001 = "SAFETY-INV-001"
    INV_002 = "SAFETY-INV-002"
    INV_003 = "SAFETY-INV-003"
    INV_004 = "SAFETY-INV-004"
    INV_005 = "SAFETY-INV-005"
    INV_006 = "SAFETY-INV-006"
    INV_007 = "SAFETY-INV-007"
    INV_008 = "SAFETY-INV-008"
    INV_009 = "SAFETY-INV-009"
    INV_010 = "SAFETY-INV-010"
    INV_011 = "SAFETY-INV-011"
    INV_012 = "SAFETY-INV-012"


class Severity(_SafetyEnum):
    """How bad a violation is. Every one of the twelve blocks a release.

    The field exists to say *why* something blocks, not whether it does. There
    is deliberately no ``ADVISORY`` level: an invariant that could be waived
    would be a guideline, and this registry is not for guidelines.
    """

    #: A violation can produce false reassurance about a person's medication.
    CRITICAL_PATIENT_FACING = "CRITICAL_PATIENT_FACING"
    #: A violation destroys traceability, reproducibility or the evidence chain.
    CRITICAL_EVIDENTIAL = "CRITICAL_EVIDENTIAL"
    #: A violation breaks the scope the whole product is validated against.
    CRITICAL_SCOPE = "CRITICAL_SCOPE"


class ExecutionState(_SafetyEnum):
    """What happened when the gate tried to check an invariant."""

    #: The check ran and the invariant held.
    PASS = "PASS"
    #: The check ran and the invariant did not hold.
    FAIL = "FAIL"
    #: The check raised before it could decide. Not a failure - an absence of
    #: an answer, which needs a different repair.
    ERROR = "ERROR"
    #: Something outside the repository prevented the check - no database, no
    #: browser, a later work package that owns the surface. Never a pass.
    BLOCKED = "BLOCKED"
    #: Nothing ran. The single most dangerous state to confuse with PASS.
    NOT_EXECUTED = "NOT_EXECUTED"
    #: It ran and passed, about code that has since changed.
    STALE = "STALE"


class ComplianceState(_SafetyEnum):
    """Whether the current implementation satisfies the invariant."""

    #: The surface exists, is exercised, and behaves.
    COMPLIANT = "COMPLIANT"
    #: The surface exists and does not behave.
    VIOLATED = "VIOLATED"
    #: The feature the invariant governs does not exist in P0, and its absence
    #: is *tested*. Legitimate for the LLM gateway and candidate exploration -
    #: and it comes with an obligation: introducing the feature must make this
    #: evidence stale or fail the gate. ``NOT_PRESENT`` may never be used to
    #: excuse an unsafe feature that actually exists.
    NOT_PRESENT = "NOT_PRESENT"
    #: A later work package owns the surface. Honest, and still blocking.
    DEFERRED_TO_LATER_WP = "DEFERRED_TO_LATER_WP"
    #: Nobody looked.
    UNKNOWN = "UNKNOWN"


class ControlKind(_SafetyEnum):
    """The two halves of proving an invariant is enforced."""

    #: A conforming case that must pass through the real evaluator.
    SAFE = "SAFE"
    #: A deliberately unsafe case that must be *rejected* by the same
    #: evaluator. Without this half, a detector that accepts everything looks
    #: exactly like a detector that works.
    NEGATIVE = "NEGATIVE"


class EnforcementSurface(_SafetyEnum):
    """Where an invariant is actually enforced.

    Named rather than free text so that "which invariants touch the report
    layer" is a query rather than a reading exercise.
    """

    DOMAIN_VALUES = "DOMAIN_VALUES"
    PHENOTYPE_NORMALIZATION = "PHENOTYPE_NORMALIZATION"
    COVERAGE_ENGINE = "COVERAGE_ENGINE"
    ASSESSMENT_ENGINE = "ASSESSMENT_ENGINE"
    EVIDENCE_RESOLUTION = "EVIDENCE_RESOLUTION"
    RULESET_PINNING = "RULESET_PINNING"
    RELEASE_PINNING = "RELEASE_PINNING"
    PERSISTENCE_BOUNDARY = "PERSISTENCE_BOUNDARY"
    DETERMINISTIC_REPORT = "DETERMINISTIC_REPORT"
    CLAIM_SCANNER = "CLAIM_SCANNER"
    API_SERIALIZATION = "API_SERIALIZATION"
    WEB_RENDERING = "WEB_RENDERING"
    VALIDATION_PARTITION = "VALIDATION_PARTITION"
    CANDIDATE_ABSENCE = "CANDIDATE_ABSENCE"
    LLM_ABSENCE = "LLM_ABSENCE"
    INPUT_BOUNDARY = "INPUT_BOUNDARY"


class BlockerOwner(_SafetyEnum):
    """Who can close a blocker. Never "code"."""

    WP_21_METRICS = "WP-21"
    WP_22_EXPERT_REVIEW = "WP-22"
    WP_23_AUTH_AUDIT = "WP-23"
    WP_24_CI_DEPLOY = "WP-24"
    P1_FEATURE = "P1"
    HUMAN_REVIEWERS = "named human and scientific reviewers"
    DEPLOYMENT = "deployment"
    SCIENTIFIC_CURATORS = "scientific curators"


#: The only execution state that lets a release proceed. One member, written as
#: a set so that no caller improvises a second.
_RELEASE_PERMITTING = frozenset({ExecutionState.PASS})


def is_release_permitting(state: ExecutionState) -> bool:
    """Whether ``state`` permits a release. Only ``PASS`` does.

    ``BLOCKED``, ``NOT_EXECUTED`` and ``STALE`` are all "we do not know", and a
    release must not proceed on any of them however green the rest looks.
    """
    return state in _RELEASE_PERMITTING
