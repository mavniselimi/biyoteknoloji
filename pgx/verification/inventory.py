# -*- coding: utf-8 -*-
"""Turning discovered tests into described tests.

Discovery says *what exists*. The inventory says *what it is for*: which of the
sixteen categories it belongs to, which work package owns it, which
requirements it serves, what it needs at runtime, and whether it may skip.

The assignment is done by an ordered rule table rather than by 206 hand-written
module entries. A table is reviewable in one screen, cannot drift out of sync
with a renamed test, and records *which rule fired* on every entry, so an
operator asking "why is this categorised as SNAPSHOT" gets an answer instead of
a shrug. A hand-written list of every test would be more precise on the day it
was written and wrong by the end of the week.

Two properties make the table safe to rely on:

**Totality is checked, not assumed.** Every discovered test must match a rule.
A test in a directory nobody has classified is reported as unmapped and fails
the inventory, rather than falling into ``UNIT`` because that is the friendliest
default. Adding ``tests/unit/verification`` without a rule would be a silent
reclassification of a whole package; here it is an error with the package name
in it.

**Specificity is explicit.** Rules are tried in order, and the first match
wins. Module rules come before package rules, so ``test_snapshot_security``
lands in ``SECURITY_BOUNDARY`` rather than in ``SNAPSHOT`` with the rest of its
directory, and the entry records that it was the module rule that decided.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.verification.discovery import Discovery, DiscoveredTest
from pgx.verification.errors import InventoryError
from pgx.verification.model import (
    Category,
    Criticality,
    SkipPolicy,
    TestEntry,
)
from pgx.verification.requirements import REQUIREMENTS, selectors_match

__all__ = [
    "CategoryRule",
    "CATEGORY_RULES",
    "Inventory",
    "build_inventory",
]

#: Reasons a test is permitted to skip, keyed by the dependency it names. The
#: text is matched case-insensitively as a substring of the observed skip
#: reason: an exact match would break on a message that gained a sentence,
#: and a looser match would let any skip claim any excuse.
_POSTGRES_REASON = "postgresql integration tests require psycopg"
_BROWSER_REASON = "browser"
_CHMOD_REASON = "ignores chmod"
_CAPABILITY_REASON = "no writer subject to these mode bits"
_PRESENT_DEPENDENCY_REASON = "installed"


@dataclass(frozen=True)
class CategoryRule:
    """One classification rule.

    ``selector`` matches a module exactly or as a dotted prefix, exactly as a
    requirement selector does. ``name`` is what gets recorded in the entry's
    ``assigned_by``, so it is written for a human reading an artifact.
    """

    name: str
    selector: str
    category: Category
    work_package: str
    criticality: Criticality = Criticality.IMPORTANT
    dependencies: Tuple[str, ...] = ()
    offline: bool = True
    synthetic_fixtures: bool = False
    skip_policy: SkipPolicy = SkipPolicy.NEVER
    permitted_skip_reasons: Tuple[str, ...] = ()
    evidence: Tuple[str, ...] = ()

    def matches(self, module: str) -> bool:
        return module == self.selector or module.startswith(self.selector + ".")


# ---------------------------------------------------------------------------
# The rule table. Module rules first, then package rules. Order is the whole
# semantics: the first match wins, and nothing below can reclaim a test above.
# ---------------------------------------------------------------------------

_MODULE_RULES: Tuple[CategoryRule, ...] = (
    # -- database, migration, runtime: the ones with real dependencies -------
    CategoryRule(
        "postgres-migration", "tests.integration.db.test_migrations",
        Category.MIGRATION, "WP-02", Criticality.P0_CRITICAL,
        dependencies=("psycopg", "postgresql"),
        skip_policy=SkipPolicy.ENVIRONMENT_DEPENDENCY,
        permitted_skip_reasons=(_POSTGRES_REASON,),
        evidence=("docs/architecture/wp02-domain-and-db.md",)),
    CategoryRule(
        "migration-0007", "tests.unit.curation.workflow.test_migration_0007",
        Category.MIGRATION, "WP-10", Criticality.IMPORTANT),
    CategoryRule(
        "migration-0008", "tests.unit.rules.test_migration_0008",
        Category.MIGRATION, "WP-11", Criticality.IMPORTANT),
    CategoryRule(
        "asgi-api", "tests.integration.api.test_asgi_runtime",
        Category.ASGI_RUNTIME, "WP-16", Criticality.P0_CRITICAL,
        dependencies=("fastapi", "starlette", "httpx", "pydantic"),
        skip_policy=SkipPolicy.INVERTED,
        permitted_skip_reasons=(_PRESENT_DEPENDENCY_REASON,),
        evidence=("data/api/wp16-runtime-verification.json",)),
    CategoryRule(
        "asgi-web", "tests.integration.web.test_asgi_web",
        Category.ASGI_RUNTIME, "WP-17", Criticality.P0_CRITICAL,
        dependencies=("fastapi", "starlette", "httpx", "jinja2"),
        skip_policy=SkipPolicy.ENVIRONMENT_DEPENDENCY,
        permitted_skip_reasons=(_PRESENT_DEPENDENCY_REASON,)),
    CategoryRule(
        "browser-e2e", "tests.integration.web.test_browser_e2e",
        Category.BROWSER_E2E, "WP-17", Criticality.IMPORTANT,
        dependencies=("playwright", "chromium"),
        skip_policy=SkipPolicy.ENVIRONMENT_DEPENDENCY,
        permitted_skip_reasons=(_BROWSER_REASON,),
        evidence=("tests/fixtures/wp17/browser/",)),
    CategoryRule(
        "web-client-inverted", "tests.unit.web.test_client",
        Category.UNIT, "WP-17", Criticality.SUPPORTING,
        skip_policy=SkipPolicy.INVERTED,
        permitted_skip_reasons=(_PRESENT_DEPENDENCY_REASON,)),

    # -- offline independence ------------------------------------------------
    CategoryRule(
        "offline-curation",
        "tests.unit.curation.workflow.test_offline_operation",
        Category.OFFLINE_INDEPENDENCE, "WP-10", Criticality.IMPORTANT),
    CategoryRule(
        "offline-rules", "tests.unit.rules.test_offline_operation",
        Category.OFFLINE_INDEPENDENCE, "WP-11", Criticality.IMPORTANT),
    CategoryRule(
        "offline-verification", "tests.unit.verification.test_offline",
        Category.OFFLINE_INDEPENDENCE, "WP-19", Criticality.P0_CRITICAL),
    # WP-19's own inverted skip. Two tests here cover the same question from
    # opposite sides - what happens when coverage.py is present, and what
    # happens when it is absent - so exactly one of them stands down in any
    # environment. Declaring the permitted reason is what stops that skip
    # being counted as unexplained, and getting it wrong would be caught by
    # the unexplained-skip check running against this very suite.
    CategoryRule(
        "coverage-and-database",
        "tests.unit.verification.test_coverage_and_database",
        Category.UNIT, "WP-19", Criticality.P0_CRITICAL,
        dependencies=("coverage",),
        skip_policy=SkipPolicy.INVERTED,
        permitted_skip_reasons=("coverage.py",)),

    # -- reproducibility -----------------------------------------------------
    CategoryRule(
        "repro-reporting", "tests.unit.reporting.test_determinism",
        Category.REPRODUCIBILITY, "WP-15", Criticality.P0_CRITICAL),
    CategoryRule(
        "repro-assessment",
        "tests.unit.application.test_assessment_determinism",
        Category.REPRODUCIBILITY, "WP-14", Criticality.P0_CRITICAL),
    CategoryRule(
        "repro-ingestion", "tests.unit.ingestion.test_replay_and_determinism",
        Category.REPRODUCIBILITY, "WP-04", Criticality.IMPORTANT),
    CategoryRule(
        "repro-rules", "tests.unit.rules.test_deterministic_artifacts",
        Category.REPRODUCIBILITY, "WP-11", Criticality.IMPORTANT),
    CategoryRule(
        "repro-snapshot-identity", "tests.unit.snapshots.test_content_identity",
        Category.REPRODUCIBILITY, "WP-06", Criticality.P0_CRITICAL),
    CategoryRule(
        "repro-verification", "tests.unit.verification.test_reproducibility",
        Category.REPRODUCIBILITY, "WP-19", Criticality.P0_CRITICAL),

    # -- security boundaries -------------------------------------------------
    CategoryRule(
        "security-api", "tests.unit.api.test_security_boundary",
        Category.SECURITY_BOUNDARY, "WP-16", Criticality.P0_CRITICAL),
    CategoryRule(
        "security-web", "tests.unit.web.test_security",
        Category.SECURITY_BOUNDARY, "WP-17", Criticality.P0_CRITICAL),
    CategoryRule(
        "security-snapshot", "tests.unit.snapshots.test_snapshot_security",
        Category.SECURITY_BOUNDARY, "WP-06", Criticality.P0_CRITICAL),
    CategoryRule(
        "security-configuration",
        "tests.unit.infrastructure.test_configuration_policy",
        Category.SECURITY_BOUNDARY, "WP-02", Criticality.P0_CRITICAL),
    CategoryRule(
        "security-seed", "tests.unit.infrastructure.test_seed_and_cleanup_safety",
        Category.SECURITY_BOUNDARY, "WP-02", Criticality.P0_CRITICAL),
    CategoryRule(
        "security-injection", "tests.unit.reporting.test_injection",
        Category.SECURITY_BOUNDARY, "WP-15", Criticality.P0_CRITICAL),
    CategoryRule(
        "security-normalization-build",
        "tests.unit.normalization.test_build_safety",
        Category.SECURITY_BOUNDARY, "WP-07", Criticality.IMPORTANT),
    CategoryRule(
        "security-verification", "tests.unit.verification.test_scrub",
        Category.SECURITY_BOUNDARY, "WP-19", Criticality.P0_CRITICAL),
    # The portable sealed-tree probe. Three honest reasons to stand down, all
    # of them about what the host can do rather than about the software: a
    # filesystem that ignores chmod, a user model where no writer subject to
    # the bits can be arranged, and a platform that can or cannot drop
    # privileges. Each is named, so a fourth reason invented later is
    # UNEXPLAINED rather than quietly accepted.
    CategoryRule(
        "filesystem-capability",
        "tests.unit.verification.test_filesystem_capability",
        Category.SNAPSHOT, "WP-19", Criticality.P0_CRITICAL,
        skip_policy=SkipPolicy.CAPABILITY,
        permitted_skip_reasons=(
            "ignores chmod",
            "no writer subject to these mode bits",
            "this user is subject to mode bits",
            "no non-root account is available",
            "this platform can drop privileges"),
        evidence=("docs/data/raw-snapshot-format.md",)),

    # -- domain invariants ---------------------------------------------------
    CategoryRule(
        "invariant-claims", "tests.unit.test_claims",
        Category.DOMAIN_INVARIANT, "WP-00", Criticality.P0_CRITICAL),
    CategoryRule(
        "invariant-rules", "tests.unit.rules.test_safety_invariants",
        Category.DOMAIN_INVARIANT, "WP-11", Criticality.P0_CRITICAL),
    CategoryRule(
        "invariant-api", "tests.unit.api.test_safety",
        Category.DOMAIN_INVARIANT, "WP-16", Criticality.P0_CRITICAL),
    CategoryRule(
        "invariant-web", "tests.unit.web.test_safety",
        Category.DOMAIN_INVARIANT, "WP-17", Criticality.P0_CRITICAL),
    CategoryRule(
        "invariant-truth-matrix", "tests.unit.engine.test_truth_matrix",
        Category.DOMAIN_INVARIANT, "WP-12", Criticality.P0_CRITICAL),
    CategoryRule(
        "invariant-safe-rendering",
        "tests.unit.reporting.test_safe_status_rendering",
        Category.DOMAIN_INVARIANT, "WP-15", Criticality.P0_CRITICAL),
    CategoryRule(
        "invariant-fail-closed", "tests.unit.scientific.test_fail_closed",
        Category.DOMAIN_INVARIANT, "WP-05", Criticality.P0_CRITICAL),
    # WP-20. The safety gate's own suite: twelve invariants, each with a safe
    # control and a negative control driven through the same evaluator. These
    # are DOMAIN_INVARIANT rather than UNIT because what they assert is a named
    # requirement from the safety contract, not the behaviour of one module.
    CategoryRule(
        "invariant-wp20-registry", "tests.unit.safety.test_registry",
        Category.DOMAIN_INVARIANT, "WP-20", Criticality.P0_CRITICAL,
        evidence=("data/safety/wp20-invariant-registry.json",)),
    CategoryRule(
        "invariant-wp20-gate", "tests.unit.safety.test_gate",
        Category.DOMAIN_INVARIANT, "WP-20", Criticality.P0_CRITICAL,
        evidence=("data/safety/wp20-real-gate-status.json",)),
    CategoryRule(
        "artifact-wp20", "tests.unit.safety.test_artifacts",
        Category.ARTIFACT_SCHEMA, "WP-20", Criticality.P0_CRITICAL,
        evidence=("data/safety/wp20-safety-report.json",)),
    CategoryRule(
        "invariant-wp20-boundaries", "tests.unit.safety.test_boundaries",
        Category.SECURITY_BOUNDARY, "WP-20", Criticality.P0_CRITICAL),

    # WP-21. The benchmark and metric suite. Split by what each module
    # actually asserts rather than filed wholesale under one category: the
    # metric registry is a domain invariant (a metric that pooled roles would
    # be a safety defect, not a wrong number), the artifacts are schema work,
    # and the boundary module guards an import direction.
    CategoryRule(
        "invariant-wp21-definitions",
        "tests.unit.benchmark.test_metric_definitions",
        Category.DOMAIN_INVARIANT, "WP-21", Criticality.P0_CRITICAL,
        evidence=("data/validation/wp21-metric-definitions.json",)),
    CategoryRule(
        "invariant-wp21-values", "tests.unit.benchmark.test_metric_values",
        Category.DOMAIN_INVARIANT, "WP-21", Criticality.P0_CRITICAL),
    CategoryRule(
        "invariant-wp21-computation",
        "tests.unit.benchmark.test_metric_computation",
        Category.DOMAIN_INVARIANT, "WP-21", Criticality.P0_CRITICAL,
        synthetic_fixtures=True),
    CategoryRule(
        "invariant-wp21-contract",
        "tests.unit.benchmark.test_benchmark_contract",
        Category.FAILURE_NEGATIVE, "WP-21", Criticality.P0_CRITICAL,
        synthetic_fixtures=True),
    CategoryRule(
        "artifact-wp21", "tests.unit.benchmark.test_report_and_feed",
        Category.ARTIFACT_SCHEMA, "WP-21", Criticality.P0_CRITICAL,
        evidence=("data/validation/wp21-validation-report.json",),
        synthetic_fixtures=True),
    CategoryRule(
        "invariant-wp21-boundaries",
        "tests.unit.benchmark.test_wp21_boundaries",
        Category.SECURITY_BOUNDARY, "WP-21", Criticality.P0_CRITICAL),
    CategoryRule(
        "cli-wp21", "tests.unit.benchmark.test_cli",
        Category.UNIT, "WP-21", Criticality.P0_CRITICAL),
    CategoryRule(
        # SNAPSHOT rather than a UI category, which this inventory does not
        # have: what these assert is that the rendered page matches a
        # committed snapshot and shows no false zero.
        "ui-wp21-dashboard", "tests.unit.benchmark.test_dashboard",
        Category.SNAPSHOT, "WP-21", Criticality.P0_CRITICAL,
        evidence=("data/validation/wp21-dashboard-feed.json",),
        synthetic_fixtures=True),

    # WP-22. The blind expert review suite. Categorised by what each module
    # asserts, not filed wholesale: the state machine and the blinding are
    # domain invariants (a result visible before an expectation is locked is
    # a protocol failure, not a wrong value), the authorisation and payload
    # modules guard access boundaries, and the persistence module carries the
    # append-only triggers no test in this environment can execute.
    CategoryRule(
        "invariant-wp22-state-machine",
        "tests.unit.expert_review.test_state_machine",
        Category.DOMAIN_INVARIANT, "WP-22", Criticality.P0_CRITICAL,
        synthetic_fixtures=True,
        evidence=("data/expert-review/wp22-review-workflow.json",)),
    CategoryRule(
        "invariant-wp22-blinding",
        "tests.unit.expert_review.test_blinding",
        Category.DOMAIN_INVARIANT, "WP-22", Criticality.P0_CRITICAL,
        synthetic_fixtures=True,
        evidence=("docs/validation/expert-protocol.md",)),
    CategoryRule(
        "invariant-wp22-immutability",
        "tests.unit.expert_review.test_immutability_and_audit",
        Category.DOMAIN_INVARIANT, "WP-22", Criticality.P0_CRITICAL,
        synthetic_fixtures=True),
    CategoryRule(
        "security-wp22-authorisation",
        "tests.unit.expert_review.test_authorisation",
        Category.SECURITY_BOUNDARY, "WP-22", Criticality.P0_CRITICAL,
        synthetic_fixtures=True),
    CategoryRule(
        "security-wp22-payload-access",
        "tests.unit.expert_review.test_payload_access",
        Category.SECURITY_BOUNDARY, "WP-22", Criticality.P0_CRITICAL,
        synthetic_fixtures=True),
    CategoryRule(
        "invariant-wp22-metric-supply",
        "tests.unit.expert_review.test_metric_supply",
        Category.VALIDATION_PARTITION, "WP-22", Criticality.P0_CRITICAL,
        synthetic_fixtures=True),
    # Two of these stand down where SQLAlchemy's PostgreSQL dialect cannot be
    # reached: the append-only triggers are DDL this environment has no server
    # to execute. The reasons are named so a third, invented later, is
    # UNEXPLAINED rather than quietly accepted.
    CategoryRule(
        "migration-0010", "tests.unit.expert_review.test_persistence",
        Category.MIGRATION, "WP-22", Criticality.P0_CRITICAL,
        skip_policy=SkipPolicy.ENVIRONMENT_DEPENDENCY,
        permitted_skip_reasons=("PostgreSQL", "psycopg", "no database"),
        evidence=("migrations/versions/0010_wp22_expert_reviews.py",)),
    CategoryRule(
        "ui-wp22-review-flow", "tests.unit.web.test_expert_review_flow",
        Category.SNAPSHOT, "WP-22", Criticality.P0_CRITICAL,
        synthetic_fixtures=True,
        skip_policy=SkipPolicy.ENVIRONMENT_DEPENDENCY,
        permitted_skip_reasons=("Jinja2",)),

    # WP-23. The security and audit suite. Categorised by what each module
    # asserts: password hashing and the login ordering are domain invariants
    # (a login that leaked which usernames exist is a safety defect, not a
    # wrong value), RBAC and CSRF guard access boundaries, and the audit
    # chain is a domain invariant because a chain that verified while broken
    # would make every record it covers worthless.
    CategoryRule(
        "invariant-wp23-passwords", "tests.unit.security.test_passwords",
        Category.DOMAIN_INVARIANT, "WP-23", Criticality.P0_CRITICAL,
        dependencies=("argon2",),
        skip_policy=SkipPolicy.ENVIRONMENT_DEPENDENCY,
        permitted_skip_reasons=("argon2-cffi is not installed",),
        evidence=("docs/security/authentication-and-session-policy.md",)),
    CategoryRule(
        "invariant-wp23-users-sessions",
        "tests.unit.security.test_users_and_sessions",
        Category.DOMAIN_INVARIANT, "WP-23", Criticality.P0_CRITICAL,
        synthetic_fixtures=True),
    CategoryRule(
        "invariant-wp23-authentication",
        "tests.unit.security.test_authentication_service",
        Category.DOMAIN_INVARIANT, "WP-23", Criticality.P0_CRITICAL,
        synthetic_fixtures=True),
    CategoryRule(
        "security-wp23-rbac", "tests.unit.security.test_rbac",
        Category.SECURITY_BOUNDARY, "WP-23", Criticality.P0_CRITICAL,
        evidence=("data/security/wp23-rbac-registry.json",)),
    CategoryRule(
        "security-wp23-csrf-rate-limit",
        "tests.unit.security.test_csrf_and_rate_limit",
        Category.SECURITY_BOUNDARY, "WP-23", Criticality.P0_CRITICAL,
        synthetic_fixtures=True,
        evidence=("data/security/wp23-rate-limit-policy.json",)),
    CategoryRule(
        "security-wp23-secret-scan",
        "tests.unit.security.test_secret_scan_and_backup",
        Category.SECURITY_BOUNDARY, "WP-23", Criticality.P0_CRITICAL,
        evidence=("data/security/wp23-secret-scan-report.json",)),
    CategoryRule(
        "invariant-wp23-audit", "tests.unit.audit.test_governed_audit",
        Category.DOMAIN_INVARIANT, "WP-23", Criticality.P0_CRITICAL,
        synthetic_fixtures=True,
        evidence=("data/security/wp23-audit-action-registry.json",)),
    # Two of these stand down where SQLAlchemy's PostgreSQL dialect cannot be
    # reached: the append-only and chain-guard triggers are DDL this
    # environment has no server to execute.
    CategoryRule(
        "migration-0011", "tests.unit.security.test_persistence",
        Category.MIGRATION, "WP-23", Criticality.P0_CRITICAL,
        skip_policy=SkipPolicy.ENVIRONMENT_DEPENDENCY,
        permitted_skip_reasons=("PostgreSQL", "psycopg", "no database"),
        evidence=("migrations/versions/0011_wp23_auth_audit.py",)),
    CategoryRule(
        "artifact-wp23", "tests.unit.security.test_artifacts_and_gate",
        Category.ARTIFACT_SCHEMA, "WP-23", Criticality.P0_CRITICAL,
        evidence=("data/security/wp23-real-gate-status.json",)),

    # WP-24. The deployment suite. Categorised by what each module asserts
    # rather than by what it is about: the composition tests are domain
    # invariants because a session shared between requests or a governed
    # change committed without its audit record are safety defects rather
    # than wrong values; the honest-reporting tests are a security boundary
    # because the thing they defend is a document nobody can be misled by.
    CategoryRule(
        "invariant-wp24-composition",
        "tests.unit.deployment.test_composition",
        Category.DOMAIN_INVARIANT, "WP-24", Criticality.P0_CRITICAL,
        synthetic_fixtures=True,
        evidence=("docs/architecture/wp24-deployment-reliability.md",)),
    CategoryRule(
        "security-wp24-honest-reporting",
        "tests.unit.deployment.test_honest_reporting",
        Category.SECURITY_BOUNDARY, "WP-24", Criticality.P0_CRITICAL,
        evidence=("data/deployment/wp24-real-gate-status.json",)),
    CategoryRule(
        "security-wp24-container-and-build",
        "tests.unit.deployment.test_container_and_build",
        Category.SECURITY_BOUNDARY, "WP-24", Criticality.P0_CRITICAL,
        skip_policy=SkipPolicy.ENVIRONMENT_DEPENDENCY,
        permitted_skip_reasons=("hatchling", "lockfile", "docker"),
        evidence=("Dockerfile", ".dockerignore")),
    CategoryRule(
        "security-wp24-cli-and-ci", "tests.unit.deployment.test_cli_and_ci",
        Category.SECURITY_BOUNDARY, "WP-24", Criticality.P0_CRITICAL,
        skip_policy=SkipPolicy.ENVIRONMENT_DEPENDENCY,
        permitted_skip_reasons=("every action is pinned", "a lockfile"),
        evidence=(".github/workflows/build-and-verify.yml",
                  ".github/workflows/release-validation.yml")),
    CategoryRule(
        "artifact-wp24",
        "tests.unit.deployment.test_schemas_and_persistence",
        Category.ARTIFACT_SCHEMA, "WP-24", Criticality.P0_CRITICAL,
        evidence=("data/deployment/wp24-release-validation.json",)),

    # WP-25. The evidence pack suite. Categorised by what each module
    # defends rather than by subject. Four of the six are security
    # boundaries in the same sense WP-24's honest-reporting tests are: the
    # thing they defend is a document nobody can be misled by. The
    # vocabulary module is a domain invariant because the substitution it
    # prevents - a passing test presenting as scientific evidence - is a
    # safety defect rather than a wrong value.
    CategoryRule(
        "invariant-wp25-vocabulary",
        "tests.unit.ths6.test_vocabulary_and_models",
        Category.DOMAIN_INVARIANT, "WP-25", Criticality.P0_CRITICAL,
        evidence=("architecture.md",)),
    CategoryRule(
        "security-wp25-registries", "tests.unit.ths6.test_registries",
        Category.SECURITY_BOUNDARY, "WP-25", Criticality.P0_CRITICAL,
        evidence=("data/ths6/wp25-evidence-registry.json",
                  "data/ths6/wp25-claim-registry.json")),
    CategoryRule(
        "security-wp25-gates", "tests.unit.ths6.test_gates_and_dod",
        Category.SECURITY_BOUNDARY, "WP-25", Criticality.P0_CRITICAL,
        evidence=("data/ths6/wp25-gate-matrix.json",
                  "data/ths6/wp25-definition-of-done.json")),
    CategoryRule(
        "security-wp25-demo", "tests.unit.ths6.test_demo_and_contingency",
        Category.SECURITY_BOUNDARY, "WP-25", Criticality.P0_CRITICAL,
        evidence=("data/ths6/wp25-demo-preflight.json",
                  "data/ths6/wp25-contingency-matrix.json")),
    CategoryRule(
        "security-wp25-pack", "tests.unit.ths6.test_integrity_and_pack",
        Category.SECURITY_BOUNDARY, "WP-25", Criticality.P0_CRITICAL,
        evidence=("data/ths6/wp25-evidence-pack-manifest.json",)),
    CategoryRule(
        "artifact-wp25", "tests.unit.ths6.test_cli_and_schemas",
        Category.ARTIFACT_SCHEMA, "WP-25", Criticality.P0_CRITICAL,
        evidence=("data/ths6/wp25-ths6-status.json",)),

    # -- failure and negative ------------------------------------------------
    CategoryRule(
        "failure-engine", "tests.unit.engine.test_failure_modes",
        Category.FAILURE_NEGATIVE, "WP-13", Criticality.P0_CRITICAL),

    # -- legacy regression ---------------------------------------------------
    CategoryRule(
        "legacy-engine", "tests.unit.engine.test_legacy_regression",
        Category.LEGACY_REGRESSION, "WP-01", Criticality.IMPORTANT),
    CategoryRule(
        "legacy-coverage", "tests.unit.engine.test_coverage_legacy_regression",
        Category.LEGACY_REGRESSION, "WP-01", Criticality.IMPORTANT),
    CategoryRule(
        "legacy-risk", "tests.unit.engine.test_risk_legacy_regression",
        Category.LEGACY_REGRESSION, "WP-01", Criticality.IMPORTANT),
    CategoryRule(
        "legacy-report", "tests.unit.reporting.test_legacy_report_regression",
        Category.LEGACY_REGRESSION, "WP-01", Criticality.IMPORTANT),
    CategoryRule(
        "legacy-normalization",
        "tests.unit.normalization.test_legacy_differences",
        Category.LEGACY_REGRESSION, "WP-01", Criticality.IMPORTANT),
    CategoryRule(
        "legacy-baseline", "tests.unit.application.test_legacy_baseline",
        Category.LEGACY_REGRESSION, "WP-01", Criticality.IMPORTANT),
    CategoryRule(
        "legacy-curation-review", "tests.unit.curation.test_legacy_review",
        Category.LEGACY_REGRESSION, "WP-01", Criticality.SUPPORTING),
    CategoryRule(
        "legacy-curation-migration",
        "tests.unit.curation.workflow.test_legacy_migration",
        Category.LEGACY_REGRESSION, "WP-01", Criticality.SUPPORTING),
    CategoryRule(
        "legacy-rule-inventory", "tests.unit.rules.test_legacy_inventory",
        Category.LEGACY_REGRESSION, "WP-01", Criticality.SUPPORTING),
    CategoryRule(
        "legacy-source-inventory",
        "tests.unit.scientific.test_legacy_inventory",
        Category.LEGACY_REGRESSION, "WP-01", Criticality.SUPPORTING),

    # -- documentation checks ------------------------------------------------
    # These read a document and assert it describes what the code does. They
    # protect against a doc going stale, which is worth catching and is not a
    # release blocker, so they are SUPPORTING wherever their package is not.
    CategoryRule(
        "doc-wp07", "tests.unit.normalization.test_wp07_documentation",
        Category.UNIT, "WP-07", Criticality.SUPPORTING),
    CategoryRule(
        "doc-wp08", "tests.unit.evidence.test_wp08_documentation",
        Category.UNIT, "WP-08", Criticality.SUPPORTING),
    CategoryRule(
        "doc-wp09", "tests.unit.curation.test_wp09_documentation",
        Category.UNIT, "WP-09", Criticality.SUPPORTING),
    CategoryRule(
        "doc-wp10", "tests.unit.curation.workflow.test_wp10_documentation",
        Category.UNIT, "WP-10", Criticality.SUPPORTING),
    CategoryRule(
        "doc-wp11", "tests.unit.rules.test_wp11_documentation",
        Category.UNIT, "WP-11", Criticality.SUPPORTING),
    CategoryRule(
        "doc-wp12", "tests.unit.engine.test_wp12_documentation",
        Category.UNIT, "WP-12", Criticality.SUPPORTING),
    CategoryRule(
        "doc-wp13", "tests.unit.engine.test_wp13_documentation",
        Category.UNIT, "WP-13", Criticality.SUPPORTING),
    CategoryRule(
        "doc-wp14", "tests.unit.engine.test_wp14_documentation",
        Category.UNIT, "WP-14", Criticality.SUPPORTING),
    CategoryRule(
        "doc-wp15", "tests.unit.reporting.test_wp15_documentation",
        Category.UNIT, "WP-15", Criticality.SUPPORTING),
    CategoryRule(
        "doc-wp16", "tests.unit.api.test_wp16_documentation",
        Category.UNIT, "WP-16", Criticality.SUPPORTING),
    CategoryRule(
        "doc-packaging",
        "tests.unit.infrastructure.test_packaging_and_environment",
        Category.UNIT, "WP-02", Criticality.SUPPORTING),

    # -- artifact and schema -------------------------------------------------
    CategoryRule(
        "schema-wp05", "tests.unit.test_wp05_schema",
        Category.ARTIFACT_SCHEMA, "WP-05", Criticality.IMPORTANT),
    CategoryRule(
        "schema-wp06", "tests.unit.test_wp06_schema",
        Category.ARTIFACT_SCHEMA, "WP-06", Criticality.IMPORTANT),
    CategoryRule(
        "schema-wp07", "tests.unit.test_wp07_schema",
        Category.ARTIFACT_SCHEMA, "WP-07", Criticality.IMPORTANT),
    CategoryRule(
        "schema-wp08", "tests.unit.test_wp08_schema",
        Category.ARTIFACT_SCHEMA, "WP-08", Criticality.IMPORTANT),
    CategoryRule(
        "schema-rendering", "tests.unit.test_schema_rendering",
        Category.ARTIFACT_SCHEMA, "WP-02", Criticality.IMPORTANT),
    CategoryRule(
        "schema-manifest-amendment", "tests.unit.test_manifest_amendment",
        Category.ARTIFACT_SCHEMA, "WP-03", Criticality.IMPORTANT),
    CategoryRule(
        "schema-snapshot", "tests.unit.snapshots.test_snapshot_schema",
        Category.ARTIFACT_SCHEMA, "WP-06", Criticality.IMPORTANT),
    CategoryRule(
        "schema-rules", "tests.unit.rules.test_published_schemas",
        Category.ARTIFACT_SCHEMA, "WP-11", Criticality.IMPORTANT),
    CategoryRule(
        "schema-curation", "tests.unit.curation.workflow.test_published_schemas",
        Category.ARTIFACT_SCHEMA, "WP-10", Criticality.IMPORTANT),
    CategoryRule(
        "artifact-reporting", "tests.unit.reporting.test_artifacts",
        Category.ARTIFACT_SCHEMA, "WP-15", Criticality.IMPORTANT),
    CategoryRule(
        "artifact-rules-gate", "tests.unit.rules.test_real_gate_status",
        Category.ARTIFACT_SCHEMA, "WP-11", Criticality.IMPORTANT),
    CategoryRule(
        "artifact-validation", "tests.unit.validation.test_artifacts",
        Category.ARTIFACT_SCHEMA, "WP-18", Criticality.IMPORTANT),
    CategoryRule(
        "artifact-runtime-verification",
        "tests.unit.api.test_runtime_verification",
        Category.ARTIFACT_SCHEMA, "WP-16", Criticality.P0_CRITICAL),
    CategoryRule(
        "artifact-verification", "tests.unit.verification.test_artifacts",
        Category.ARTIFACT_SCHEMA, "WP-19", Criticality.P0_CRITICAL),

    # -- snapshot ------------------------------------------------------------
    CategoryRule(
        "snapshot-web-html", "tests.unit.web.test_snapshots",
        Category.SNAPSHOT, "WP-17", Criticality.IMPORTANT),
    CategoryRule(
        "snapshot-sealed-tree", "tests.unit.snapshots.test_snapshot_build",
        Category.SNAPSHOT, "WP-06", Criticality.P0_CRITICAL,
        skip_policy=SkipPolicy.CAPABILITY,
        permitted_skip_reasons=(_CHMOD_REASON,),
        evidence=("docs/data/raw-snapshot-format.md",)),

    # -- integration ---------------------------------------------------------
    CategoryRule(
        "integration-rules-e2e", "tests.unit.rules.test_synthetic_end_to_end",
        Category.INTEGRATION, "WP-11", Criticality.IMPORTANT,
        synthetic_fixtures=True),
    CategoryRule(
        "integration-web-flow", "tests.unit.web.test_e2e_flow",
        Category.INTEGRATION, "WP-17", Criticality.IMPORTANT,
        synthetic_fixtures=True),
)


_PACKAGE_RULES: Tuple[CategoryRule, ...] = (
    CategoryRule(
        "package-postgres", "tests.integration.db",
        Category.POSTGRESQL_INTEGRATION, "WP-02", Criticality.P0_CRITICAL,
        dependencies=("psycopg", "postgresql"),
        skip_policy=SkipPolicy.ENVIRONMENT_DEPENDENCY,
        permitted_skip_reasons=(_POSTGRES_REASON,)),
    CategoryRule(
        "package-contract", "tests.contract",
        Category.API_CONTRACT, "WP-12..WP-15", Criticality.P0_CRITICAL),
    CategoryRule(
        "package-api-unit", "tests.unit.api",
        Category.API_CONTRACT, "WP-16", Criticality.P0_CRITICAL),
    CategoryRule(
        "package-failure", "tests.failure",
        Category.FAILURE_NEGATIVE, "WP-02..WP-18", Criticality.P0_CRITICAL),
    CategoryRule(
        "package-adversarial", "tests.adversarial",
        Category.FAILURE_NEGATIVE, "WP-15", Criticality.P0_CRITICAL),
    CategoryRule(
        "package-safety", "tests.safety",
        Category.DOMAIN_INVARIANT, "WP-13/WP-14", Criticality.P0_CRITICAL),
    CategoryRule(
        "package-domain", "tests.unit.domain",
        Category.DOMAIN_INVARIANT, "WP-02", Criticality.P0_CRITICAL),
    CategoryRule(
        "package-legacy-regression", "tests.regression.legacy",
        Category.LEGACY_REGRESSION, "WP-01", Criticality.IMPORTANT),
    CategoryRule(
        "package-validation", "tests.unit.validation",
        Category.VALIDATION_PARTITION, "WP-18", Criticality.P0_CRITICAL,
        synthetic_fixtures=True),
    CategoryRule(
        "package-validation-integration", "tests.integration.validation",
        Category.VALIDATION_PARTITION, "WP-18", Criticality.P0_CRITICAL,
        synthetic_fixtures=True),
    CategoryRule(
        "package-snapshots", "tests.unit.snapshots",
        Category.SNAPSHOT, "WP-06", Criticality.P0_CRITICAL),
    CategoryRule(
        "package-integration-engine", "tests.integration.engine",
        Category.INTEGRATION, "WP-12..WP-14", Criticality.P0_CRITICAL,
        synthetic_fixtures=True),
    CategoryRule(
        "package-integration-reporting", "tests.integration.reporting",
        Category.INTEGRATION, "WP-15", Criticality.P0_CRITICAL,
        synthetic_fixtures=True),
    CategoryRule(
        "package-verification", "tests.unit.verification",
        Category.UNIT, "WP-19", Criticality.P0_CRITICAL),
    # Everything else under tests/unit/safety is one invariant's own module.
    CategoryRule(
        "package-wp20-safety", "tests.unit.safety",
        Category.DOMAIN_INVARIANT, "WP-20", Criticality.P0_CRITICAL,
        evidence=("docs/evidence/wp20-safety-report.md",)),
    # Everything else under tests/unit/benchmark. Falls back to
    # VALIDATION_PARTITION because that is what a metric ultimately asserts
    # about: which cases may be counted, and against what.
    CategoryRule(
        "package-wp21-benchmark", "tests.unit.benchmark",
        Category.VALIDATION_PARTITION, "WP-21", Criticality.P0_CRITICAL,
        evidence=("docs/evidence/wp21-validation-report.md",),
        synthetic_fixtures=True),
    CategoryRule(
        "package-engine", "tests.unit.engine",
        Category.UNIT, "WP-12/WP-13/WP-14", Criticality.P0_CRITICAL),
    CategoryRule(
        "package-application", "tests.unit.application",
        Category.UNIT, "WP-03/WP-14/WP-15", Criticality.P0_CRITICAL),
    CategoryRule(
        "package-rules", "tests.unit.rules",
        Category.UNIT, "WP-11", Criticality.P0_CRITICAL),
    CategoryRule(
        "package-curation", "tests.unit.curation",
        Category.UNIT, "WP-09/WP-10", Criticality.P0_CRITICAL),
    CategoryRule(
        "package-reporting", "tests.unit.reporting",
        Category.UNIT, "WP-15", Criticality.P0_CRITICAL),
    CategoryRule(
        "package-web", "tests.unit.web",
        Category.UNIT, "WP-17", Criticality.P0_CRITICAL),
    CategoryRule(
        "package-evidence", "tests.unit.evidence",
        Category.UNIT, "WP-08", Criticality.IMPORTANT),
    CategoryRule(
        "package-normalization", "tests.unit.normalization",
        Category.UNIT, "WP-07", Criticality.IMPORTANT),
    CategoryRule(
        "package-ingestion", "tests.unit.ingestion",
        Category.UNIT, "WP-04", Criticality.IMPORTANT),
    CategoryRule(
        "package-scientific", "tests.unit.scientific",
        Category.UNIT, "WP-05", Criticality.IMPORTANT),
    CategoryRule(
        "package-infrastructure", "tests.unit.infrastructure",
        Category.UNIT, "WP-02", Criticality.IMPORTANT),
)

#: Module rules first. The order is the semantics; see the module docstring.
CATEGORY_RULES: Tuple[CategoryRule, ...] = _MODULE_RULES + _PACKAGE_RULES


@dataclass(frozen=True)
class Inventory:
    """Every discovered test, described, plus what could not be described."""

    entries: Tuple[TestEntry, ...]
    unmapped: Tuple[str, ...]
    load_failures: Tuple[Tuple[str, str], ...]

    def by_id(self) -> Dict[str, TestEntry]:
        return {entry.test_id: entry for entry in self.entries}

    def by_category(self) -> Dict[Category, Tuple[TestEntry, ...]]:
        found: Dict[Category, List[TestEntry]] = {}
        for entry in self.entries:
            found.setdefault(entry.category, []).append(entry)
        return {category: tuple(items) for category, items in found.items()}

    def ids_for_category(self, category: Category) -> Tuple[str, ...]:
        return tuple(entry.test_id for entry in self.entries
                     if entry.category is category)

    @property
    def count(self) -> int:
        return len(self.entries)


def _rule_for(module: str) -> Optional[CategoryRule]:
    for rule in CATEGORY_RULES:
        if rule.matches(module):
            return rule
    return None


def _requirements_for(module: str) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """The requirement ids and mapped safety invariants for ``module``."""
    requirement_ids: List[str] = []
    invariants: List[str] = []
    for requirement in REQUIREMENTS:
        if selectors_match(module, requirement.selectors):
            requirement_ids.append(requirement.requirement_id)
            invariants.extend(requirement.safety_invariants)
    return (tuple(sorted(set(requirement_ids))), tuple(sorted(set(invariants))))


def _command_for(entry_module: str) -> str:
    """How a person runs exactly this module, with no discovery in between."""
    return "python -m unittest %s -v" % entry_module


def build_inventory(discovery: Discovery,
                    rules: Sequence[CategoryRule] = CATEGORY_RULES
                    ) -> Inventory:
    """Describe every discovered test, or say which ones could not be.

    Raises ``InventoryError`` listing every unmapped module at once rather than
    one per round trip. A single missing rule usually means a whole new package
    arrived, and an operator wants to see that as one fact.
    """
    entries: List[TestEntry] = []
    unmapped: List[str] = []
    resolved: Dict[str, Optional[CategoryRule]] = {}

    for test in discovery.tests:
        if test.module not in resolved:
            resolved[test.module] = _first_match(test.module, rules)
        rule = resolved[test.module]
        if rule is None:
            unmapped.append(test.module)
            continue
        requirement_ids, invariants = _requirements_for(test.module)
        entries.append(TestEntry(
            test_id=test.test_id,
            module=test.module,
            category=rule.category,
            work_package=rule.work_package,
            criticality=rule.criticality,
            requirements=requirement_ids,
            safety_invariants=invariants,
            command=_command_for(test.module),
            dependencies=rule.dependencies,
            offline=rule.offline,
            synthetic_fixtures=rule.synthetic_fixtures,
            skip_policy=rule.skip_policy,
            permitted_skip_reasons=rule.permitted_skip_reasons,
            evidence=rule.evidence,
            assigned_by=rule.name,
        ))

    if unmapped:
        raise InventoryError(
            "%d test module(s) match no category rule, so their tests would be "
            "silently uncategorised" % len(sorted(set(unmapped))),
            sorted(set(unmapped)))

    entries.sort(key=lambda entry: entry.test_id)
    return Inventory(tuple(entries), tuple(sorted(set(unmapped))),
                     discovery.load_failures)


def _first_match(module: str,
                 rules: Sequence[CategoryRule]) -> Optional[CategoryRule]:
    for rule in rules:
        if rule.matches(module):
            return rule
    return None
