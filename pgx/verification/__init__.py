# -*- coding: utf-8 -*-
"""WP-19 - the software verification system.

This package is the instrument, not the tests. It discovers what exists, says
what each test verifies, runs named subsets in isolation, and reports outcomes
that cannot be collapsed into a single misleading boolean.

It claims nothing about science. A green run here means the software behaved as
its tests describe; it does not mean a rule is correct, a case is valid, or a
human approved anything. Those live in WP-21, WP-22 and the claim boundary, and
no field in any artifact this package writes may be read as evidence of them.

It also does not own the safety gate. WP-19 *maps* existing tests to
``SAFETY-INV-001``..``010`` so an operator can see which invariants have
executing tests behind them; building the invariant registry and the blocking
job is WP-20's work, and this package must not report that gate as satisfied.
"""

from __future__ import annotations

from pgx.verification.errors import (
    CoverageUnavailable,
    DiscoveryError,
    InventoryError,
    MatrixError,
    ProfileError,
    ReproducibilityMismatch,
    ResultParseError,
    RunnerError,
    ScrubRefusal,
    VerificationError,
)
from pgx.verification.filesystem import (
    MutationAttempt,
    MutationOutcome,
    attempt_append_as_owner_unprivileged,
    attempt_append_here,
    attempt_unprivileged_mutation,
    chmod_is_honoured,
    denies_all_writers,
    file_mode,
    mode_bits_restrict_current_user,
    unprivileged_account,
)
from pgx.verification.model import (
    PLAN_SCHEMA_VERSION,
    REQUIRED_CATEGORIES,
    RESULT_SCHEMA_VERSION,
    Category,
    Criticality,
    Outcome,
    ProfileResult,
    SkipClassification,
    SkipPolicy,
    SuiteSummary,
    TestEntry,
    TestOutcome,
    is_passing,
    worst_outcome,
)

__all__ = [
    "PLAN_SCHEMA_VERSION",
    "REQUIRED_CATEGORIES",
    "RESULT_SCHEMA_VERSION",
    "Category",
    "CoverageUnavailable",
    "Criticality",
    "DiscoveryError",
    "InventoryError",
    "MatrixError",
    "MutationAttempt",
    "MutationOutcome",
    "Outcome",
    "ProfileError",
    "ProfileResult",
    "ReproducibilityMismatch",
    "ResultParseError",
    "RunnerError",
    "ScrubRefusal",
    "SkipClassification",
    "SkipPolicy",
    "SuiteSummary",
    "TestEntry",
    "TestOutcome",
    "VerificationError",
    "attempt_append_as_owner_unprivileged",
    "attempt_append_here",
    "attempt_unprivileged_mutation",
    "chmod_is_honoured",
    "denies_all_writers",
    "file_mode",
    "is_passing",
    "mode_bits_restrict_current_user",
    "unprivileged_account",
    "worst_outcome",
]
