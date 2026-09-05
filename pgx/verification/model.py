# -*- coding: utf-8 -*-
"""The WP-19 verification vocabulary and plan model.

Standard library only, like the domain layer beneath it: the thing that decides
whether the software was verified must run in an environment where nothing can
be installed, or it verifies only the environments that happen to be complete.

Five ideas live here.

``Outcome``
    What can be said about a test, a category, or a whole profile. The five
    values are deliberately not collapsible: ``SKIP`` is not ``PASS``,
    ``BLOCKED`` is not ``FAIL``, and ``MISSING`` is not ``BLOCKED``. A category
    with no executing test reports ``BLOCKED`` (something outside the code
    prevents execution) or ``MISSING`` (nothing was ever written), never
    ``PASS``.

``Category``
    The sixteen kinds of verification WP-19 must distinguish. Every discovered
    test resolves to exactly one; a test that resolves to none is a reported
    defect, not a silent omission.

``Criticality``
    Whether a failure blocks a release. Assigned from the requirement a test
    serves, never from how the test is named.

``SkipPolicy``
    Whether a test may skip at all, and for what. A skip whose reason does not
    match its declared policy is ``UNEXPLAINED`` and fails its profile. This is
    the mechanism that stops "the environment was incomplete" from quietly
    becoming "the suite is green".

``TestEntry`` / ``SuiteSummary`` / ``ProfileResult``
    The records the artifacts are built from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

__all__ = [
    "PLAN_SCHEMA_VERSION",
    "RESULT_SCHEMA_VERSION",
    "Outcome",
    "Category",
    "REQUIRED_CATEGORIES",
    "Criticality",
    "SkipPolicy",
    "SkipClassification",
    "TestEntry",
    "TestOutcome",
    "SuiteSummary",
    "ProfileResult",
    "worst_outcome",
]

#: Bumped when the shape of the inventory document changes, never for content.
PLAN_SCHEMA_VERSION = "pgx-wp19-verification-plan/1"

#: Bumped when the shape of an execution result changes.
RESULT_SCHEMA_VERSION = "pgx-wp19-verification-result/1"


class _VerificationEnum(str, Enum):
    """String-valued, stable in JSON, and explicitly not ordered.

    Ordering is disabled for the same reason the domain enums disable it: the
    moment ``SKIP < PASS`` type-checks, somebody writes ``max(outcomes)`` and a
    blocked category becomes a passing one.
    """

    def __str__(self) -> str:
        return self.value

    def __lt__(self, other: object) -> bool:  # pragma: no cover - guard
        raise TypeError(
            "%s values are not ordered; ranking verification outcomes as "
            "magnitudes is how a blocked result becomes a passing one"
            % type(self).__name__
        )

    __le__ = __lt__
    __gt__ = __lt__
    __ge__ = __lt__


class Outcome(_VerificationEnum):
    """What may be said about a test, a category, or a profile."""

    #: Executed and satisfied its assertions.
    PASS = "PASS"
    #: Executed and did not satisfy them. The software is wrong, or the test is.
    FAIL = "FAIL"
    #: Executed and raised before it could decide. Never counted as a failure,
    #: because "the test broke" and "the code is wrong" need different repairs.
    ERROR = "ERROR"
    #: Did not execute, and said why. Never a pass.
    SKIP = "SKIP"
    #: Could not execute because something outside the repository is absent -
    #: a database, a browser, a package that cannot be installed here. Never a
    #: pass, and distinguished from SKIP because a skip is a decision the test
    #: made and a block is a decision the world made.
    BLOCKED = "BLOCKED"
    #: No test exists for this. Distinguished from BLOCKED because a missing
    #: test is a gap in the suite and a blocked test is a gap in the machine.
    MISSING = "MISSING"


#: Outcomes that permit a release to proceed on their own. Exactly one.
_PASSING = frozenset({Outcome.PASS})


class Category(_VerificationEnum):
    """The kinds of verification the matrix must be able to tell apart."""

    UNIT = "UNIT"
    DOMAIN_INVARIANT = "DOMAIN_INVARIANT"
    FAILURE_NEGATIVE = "FAILURE_NEGATIVE"
    INTEGRATION = "INTEGRATION"
    POSTGRESQL_INTEGRATION = "POSTGRESQL_INTEGRATION"
    MIGRATION = "MIGRATION"
    API_CONTRACT = "API_CONTRACT"
    ASGI_RUNTIME = "ASGI_RUNTIME"
    BROWSER_E2E = "BROWSER_E2E"
    SNAPSHOT = "SNAPSHOT"
    ARTIFACT_SCHEMA = "ARTIFACT_SCHEMA"
    REPRODUCIBILITY = "REPRODUCIBILITY"
    LEGACY_REGRESSION = "LEGACY_REGRESSION"
    VALIDATION_PARTITION = "VALIDATION_PARTITION"
    SECURITY_BOUNDARY = "SECURITY_BOUNDARY"
    OFFLINE_INDEPENDENCE = "OFFLINE_INDEPENDENCE"


#: Every category WP-19 must report on. Written out rather than derived from
#: the enum so that adding a member is a deliberate act with a matrix entry
#: behind it, not something that happens because somebody extended a vocabulary.
REQUIRED_CATEGORIES: Tuple[Category, ...] = (
    Category.UNIT,
    Category.DOMAIN_INVARIANT,
    Category.FAILURE_NEGATIVE,
    Category.INTEGRATION,
    Category.POSTGRESQL_INTEGRATION,
    Category.MIGRATION,
    Category.API_CONTRACT,
    Category.ASGI_RUNTIME,
    Category.BROWSER_E2E,
    Category.SNAPSHOT,
    Category.ARTIFACT_SCHEMA,
    Category.REPRODUCIBILITY,
    Category.LEGACY_REGRESSION,
    Category.VALIDATION_PARTITION,
    Category.SECURITY_BOUNDARY,
    Category.OFFLINE_INDEPENDENCE,
)


class Criticality(_VerificationEnum):
    """Whether a failure here blocks a release."""

    #: On the P0 critical path. A failure blocks.
    P0_CRITICAL = "P0_CRITICAL"
    #: Protects a documented contract but is not on the critical path.
    IMPORTANT = "IMPORTANT"
    #: Scaffolding, documentation checks, and internal consistency.
    SUPPORTING = "SUPPORTING"


class SkipPolicy(_VerificationEnum):
    """What a test is permitted to skip for."""

    #: May never skip. A skip here is unexplained by definition.
    NEVER = "NEVER"
    #: May skip when a declared external dependency is absent - a database, a
    #: driver, a browser binary.
    ENVIRONMENT_DEPENDENCY = "ENVIRONMENT_DEPENDENCY"
    #: May skip when the host cannot perform the operation being tested - a
    #: filesystem that ignores chmod, a user model that cannot be refused.
    CAPABILITY = "CAPABILITY"
    #: Exists to check that *another* test's skip message is honest, and stands
    #: down when the dependency it describes is present. The suite has three.
    INVERTED = "INVERTED"


class SkipClassification(_VerificationEnum):
    """Whether an observed skip was one the inventory permitted."""

    ALLOWED = "ALLOWED"
    UNEXPLAINED = "UNEXPLAINED"


@dataclass(frozen=True)
class TestEntry:
    """One discovered test, described.

    ``test_id`` is the unittest identifier - ``tests.unit.domain.test_hashing``
    ``.TestCanonicalJson.test_it_sorts_keys``. It is stable across runs, unique
    within a tree, and is what every artifact keys on.
    """

    test_id: str
    module: str
    category: Category
    work_package: str
    criticality: Criticality
    requirements: Tuple[str, ...] = ()
    safety_invariants: Tuple[str, ...] = ()
    command: str = ""
    dependencies: Tuple[str, ...] = ()
    offline: bool = True
    synthetic_fixtures: bool = False
    skip_policy: SkipPolicy = SkipPolicy.NEVER
    #: Substrings, any one of which makes an observed skip ALLOWED. A tuple
    #: rather than a single string because one module can have more than one
    #: honest reason to stand down - the filesystem-capability tests skip for
    #: a filesystem that ignores chmod, for a user model that cannot be
    #: refused, and for a platform that cannot drop privileges, and collapsing
    #: those into one phrase would either accept every skip or reject a real
    #: one.
    permitted_skip_reasons: Tuple[str, ...] = ()
    evidence: Tuple[str, ...] = ()
    #: Which rule in the category table assigned this entry. Recorded so an
    #: operator can see *why* a test was categorised, not only how.
    assigned_by: str = ""

    def as_document(self) -> Dict[str, Any]:
        """The JSON shape. Sorted and total: every field appears every time."""
        return {
            "assigned_by": self.assigned_by,
            "category": self.category.value,
            "command": self.command,
            "criticality": self.criticality.value,
            "dependencies": list(self.dependencies),
            "evidence": list(self.evidence),
            "module": self.module,
            "offline": self.offline,
            "permitted_skip_reasons": list(self.permitted_skip_reasons),
            "requirements": list(self.requirements),
            "safety_invariants": list(self.safety_invariants),
            "skip_policy": self.skip_policy.value,
            "synthetic_fixtures": self.synthetic_fixtures,
            "test_id": self.test_id,
            "work_package": self.work_package,
        }


@dataclass(frozen=True)
class TestOutcome:
    """What one test did in one execution.

    ``duration_seconds`` is deliberately absent. Durations are excluded from
    every deterministic comparison WP-19 makes, and the cheapest way to keep
    them out of a hash is to never record them beside the result.
    """

    test_id: str
    outcome: Outcome
    reason: str = ""
    skip_classification: Optional[SkipClassification] = None

    def as_document(self) -> Dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "reason": self.reason,
            "skip_classification": (None if self.skip_classification is None
                                    else self.skip_classification.value),
            "test_id": self.test_id,
        }


@dataclass(frozen=True)
class SuiteSummary:
    """Exact counts for one execution. Never derived from one another.

    ``discovered`` and ``executed`` are separate because they genuinely differ:
    a class-level skip in ``setUpClass`` suppresses every test in the class
    while the runner reports one skip, so ``testsRun`` is not the number of
    tests that exist. Collapsing the two would hide seventy-seven PostgreSQL
    tests behind sixteen skip lines.
    """

    discovered: int
    executed: int
    passed: int
    failed: int
    errored: int
    skipped: int
    unexplained_skips: int
    not_executed: int

    def as_document(self) -> Dict[str, Any]:
        return {
            "discovered": self.discovered,
            "errored": self.errored,
            "executed": self.executed,
            "failed": self.failed,
            "not_executed": self.not_executed,
            "passed": self.passed,
            "skipped": self.skipped,
            "unexplained_skips": self.unexplained_skips,
        }

    @property
    def is_clean(self) -> bool:
        """No failure, no error, no unexplained skip, and something ran.

        Zero executed tests is not clean. A profile that discovers nothing and
        reports success is the single easiest way to build a green light that
        means nothing, so it is refused here rather than in one caller.
        """
        return (self.executed > 0
                and self.failed == 0
                and self.errored == 0
                and self.unexplained_skips == 0)


@dataclass(frozen=True)
class ProfileResult:
    """The outcome of running one named profile."""

    profile: str
    outcome: Outcome
    summary: SuiteSummary
    outcomes: Tuple[TestOutcome, ...] = ()
    blocked_reason: str = ""
    issue_codes: Tuple[str, ...] = ()
    stdout_note: str = ""
    #: Per-category outcome and counts for this run. Carried on the result
    #: rather than derived by each reader, so the profile's single word and the
    #: category table can never be computed from different data. A profile can
    #: be PASS while a category inside it is BLOCKED - that is not a
    #: contradiction, it is the reason the table exists.
    categories: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    @property
    def blocked_categories(self) -> Tuple[str, ...]:
        return tuple(sorted(
            name for name, info in self.categories.items()
            if info.get("outcome") == Outcome.BLOCKED.value))

    def as_document(self, include_outcomes: bool = True) -> Dict[str, Any]:
        document: Dict[str, Any] = {
            "blocked_categories": list(self.blocked_categories),
            "blocked_reason": self.blocked_reason,
            "categories": {name: dict(info)
                           for name, info in sorted(self.categories.items())},
            "issue_codes": list(self.issue_codes),
            "outcome": self.outcome.value,
            "profile": self.profile,
            "stdout_note": self.stdout_note,
            "summary": self.summary.as_document(),
        }
        if include_outcomes:
            document["outcomes"] = [item.as_document()
                                    for item in sorted(self.outcomes,
                                                       key=lambda o: o.test_id)]
        return document


def worst_outcome(outcomes: Sequence[Outcome]) -> Outcome:
    """Combine outcomes without ordering them.

    Explicit precedence rather than ``max``: ERROR beats FAIL beats BLOCKED
    beats MISSING beats SKIP beats PASS. An empty sequence is ``MISSING``, not
    ``PASS`` - nothing observed is not the same as nothing wrong.
    """
    if not outcomes:
        return Outcome.MISSING
    for candidate in (Outcome.ERROR, Outcome.FAIL, Outcome.BLOCKED,
                      Outcome.MISSING, Outcome.SKIP):
        if candidate in outcomes:
            return candidate
    return Outcome.PASS


def is_passing(outcome: Outcome) -> bool:
    """Only ``PASS`` passes. Written as a function so no caller improvises."""
    return outcome in _PASSING


__all__.append("is_passing")
