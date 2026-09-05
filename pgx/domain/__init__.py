"""PGx Platform V2 domain layer.

At WP-00 the domain layer contains only the claims boundary contract
(:mod:`pgx.domain.claims`). Domain enums, entities, errors, and ports for
evidence, interpretation, rules, coverage, and assessment are added by
WP-02 and later.

The domain layer must not depend on frameworks, ORMs, HTTP, or external
services in any work package.
"""

from pgx.domain.claims import (  # noqa: F401
    CANONICAL_CLINICAL_WARNING,
    CANONICAL_CLINICAL_WARNING_EN,
    CANONICAL_CLINICAL_WARNING_TR,
    CLAIM_BOUNDARY_STATUS,
    CLAIM_BOUNDARY_VERSION,
    DEFAULT_CLAIM_BOUNDARY,
    P0_CLAIM_BOUNDARY,
    PILOT_DISABLED_REASON,
    ClaimBoundary,
    ClaimPhase,
    ClaimScanResult,
    ClaimViolation,
    ModeNotEnabledError,
    OperationMode,
    ProhibitedClaimCategory,
    ProhibitedClaimError,
    SafeContextKind,
    SuppressedMatch,
    assert_claim_text_allowed,
    canonical_clinical_warning,
    is_mode_enabled,
    prohibited_claim_statements,
    require_mode_enabled,
    scan_claim_text,
)

__all__ = [
    "CANONICAL_CLINICAL_WARNING",
    "CANONICAL_CLINICAL_WARNING_EN",
    "CANONICAL_CLINICAL_WARNING_TR",
    "CLAIM_BOUNDARY_STATUS",
    "CLAIM_BOUNDARY_VERSION",
    "DEFAULT_CLAIM_BOUNDARY",
    "P0_CLAIM_BOUNDARY",
    "PILOT_DISABLED_REASON",
    "ClaimBoundary",
    "ClaimPhase",
    "ClaimScanResult",
    "ClaimViolation",
    "ModeNotEnabledError",
    "OperationMode",
    "ProhibitedClaimCategory",
    "ProhibitedClaimError",
    "SafeContextKind",
    "SuppressedMatch",
    "assert_claim_text_allowed",
    "canonical_clinical_warning",
    "is_mode_enabled",
    "prohibited_claim_statements",
    "require_mode_enabled",
    "scan_claim_text",
]
