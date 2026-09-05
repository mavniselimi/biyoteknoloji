# -*- coding: utf-8 -*-
"""What the software must do, and which tests are claimed to show it.

Two registries live here, and the difference between them is the point.

``REQUIREMENTS`` is the P0 verification requirement list: the critical
behaviours a release depends on, each with the tests that exercise it. Every
selector is resolved against real discovery, so a requirement whose tests were
renamed or deleted becomes an error rather than a line that still reads well.

``SAFETY_INVARIANT_MAP`` is a *map*, not a gate. WP-00 wrote ten safety
invariants; WP-20 owns the registry that enforces them and the job that blocks
a release on them. What WP-19 can honestly say is "these existing tests relate
to that invariant", so that an operator can see where the coverage is thin
before WP-20 exists. Nothing in this module may be read as the WP-20 gate being
satisfied, and ``pgx.verification.gate_status`` says so in the artifact it
writes.

Selectors are module names or module prefixes, never individual test names.
Pinning a requirement to ``test_it_sorts_keys`` would mean a rename breaks the
matrix; pinning it to the module means the matrix tracks the unit a reviewer
actually reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Sequence, Tuple

from pgx.verification.model import Criticality

__all__ = [
    "REQUIREMENT_REGISTRY_VERSION",
    "Requirement",
    "REQUIREMENTS",
    "SAFETY_INVARIANT_MAP",
    "SAFETY_MAP_DISCLAIMER",
    "requirements_by_id",
    "selectors_match",
]

REQUIREMENT_REGISTRY_VERSION = "pgx-wp19-requirements/1"

#: Repeated verbatim into every artifact that carries the safety map.
SAFETY_MAP_DISCLAIMER = (
    "This is a map from existing tests to the WP-00 safety invariants, not an "
    "assertion that the invariants hold. WP-20 owns the invariant registry and "
    "the blocking job; WP-19 has neither and claims neither.")


@dataclass(frozen=True)
class Requirement:
    """One thing the software must do, and where that is checked."""

    requirement_id: str
    title: str
    #: Where the requirement comes from - a document, not a wish.
    source: str
    #: Work packages that implement it.
    work_packages: Tuple[str, ...]
    #: Module names or dotted prefixes whose tests exercise it.
    selectors: Tuple[str, ...]
    criticality: Criticality
    #: Named safety invariants this requirement relates to. Mapping only.
    safety_invariants: Tuple[str, ...] = ()
    note: str = ""

    def as_document(self) -> Dict[str, object]:
        return {
            "criticality": self.criticality.value,
            "note": self.note,
            "requirement_id": self.requirement_id,
            "safety_invariants": list(self.safety_invariants),
            "selectors": list(self.selectors),
            "source": self.source,
            "title": self.title,
            "work_packages": list(self.work_packages),
        }


def selectors_match(module: str, selectors: Sequence[str]) -> bool:
    """Whether ``module`` is named by one of ``selectors``.

    A selector matches exactly, or as a dotted prefix. ``tests.unit.web``
    matches ``tests.unit.web.test_pages`` but not ``tests.unit.website`` - the
    dot is required, so a selector cannot capture a sibling package by accident.
    """
    for selector in selectors:
        if module == selector or module.startswith(selector + "."):
            return True
    return False


#: The eleven critical P0 requirements, plus the supporting ones that keep the
#: matrix honest about what else is being relied on. Order is stable and is the
#: order they appear in every rendered document.
REQUIREMENTS: Tuple[Requirement, ...] = (
    Requirement(
        requirement_id="VER-REQ-001",
        title="The claim boundary is enforced in code, not only documented",
        source="docs/architecture/intended-purpose.md (DOC-IP-001); "
               "architecture.md sections 2.1-2.3",
        work_packages=("WP-00", "WP-15", "WP-17"),
        selectors=("tests.unit.test_claims",
                   "tests.adversarial.test_report_claims",
                   "tests.unit.reporting.test_safe_status_rendering",
                   "tests.unit.web.test_safety"),
        criticality=Criticality.P0_CRITICAL,
        safety_invariants=("SAFETY-INV-005", "SAFETY-INV-008"),
        note="Enforcement is verified. Approval of the boundary itself is a "
             "human act and is reported as a blocker, never as a test result.",
    ),
    Requirement(
        requirement_id="VER-REQ-002",
        title="Datasets are immutable and carry their provenance",
        source="architecture.md sections 5-6; "
               "docs/data/raw-snapshot-format.md",
        work_packages=("WP-05", "WP-06"),
        selectors=("tests.unit.snapshots",
                   "tests.unit.test_wp05_schema",
                   "tests.unit.test_wp06_schema",
                   "tests.unit.domain.test_immutability"),
        criticality=Criticality.P0_CRITICAL,
        safety_invariants=("SAFETY-INV-010",),
        note="Includes the portable sealed-tree check repaired by WP-19: mode "
             "bits are asserted everywhere chmod is honoured, and the mutation "
             "attempt is made by a writer the bits actually govern.",
    ),
    Requirement(
        requirement_id="VER-REQ-003",
        title="Curation and ruleset approval cannot be self-served",
        source="architecture.md sections 9-11; WP-09/WP-10/WP-11",
        work_packages=("WP-09", "WP-10", "WP-11"),
        selectors=("tests.unit.curation",
                   "tests.unit.rules",
                   "tests.integration.engine.test_wp11_integration",
                   "tests.integration.db.test_wp11_rules"),
        criticality=Criticality.P0_CRITICAL,
        safety_invariants=("SAFETY-INV-003",),
        note="The database half of separation of duties is inside the "
             "PostgreSQL skip and is reported BLOCKED where no server ran.",
    ),
    Requirement(
        requirement_id="VER-REQ-004",
        title="A release pins dataset, ruleset and software before assessment",
        source="architecture.md section 4; docs/architecture/"
               "wp03-release-registry.md",
        work_packages=("WP-03", "WP-14"),
        selectors=("tests.unit.application.test_release_pinning",
                   "tests.unit.application.test_release_manifest",
                   "tests.unit.application.test_release_service",
                   "tests.unit.application.test_release_boundaries",
                   "tests.unit.application.test_rollback",
                   "tests.unit.application.test_release_cli",
                   "tests.unit.application.test_release_source_gate",
                   "tests.integration.db.test_release_registry"),
        criticality=Criticality.P0_CRITICAL,
        safety_invariants=("SAFETY-INV-007", "SAFETY-INV-010"),
    ),
    Requirement(
        requirement_id="VER-REQ-005",
        title="Phenotype matching is exact; RAPID never means ULTRARAPID",
        source="architecture.md section 9.1; SAFETY-INV-004; LEGACY-BUG-001",
        work_packages=("WP-07", "WP-12"),
        selectors=("tests.unit.engine.test_profile",
                   "tests.unit.engine.test_normalization",
                   "tests.unit.engine.test_phenotype_cli",
                   "tests.unit.engine.test_wp12_boundaries",
                   "tests.unit.engine.test_truth_matrix",
                   "tests.contract.test_wp12_schemas"),
        criticality=Criticality.P0_CRITICAL,
        safety_invariants=("SAFETY-INV-004",),
    ),
    Requirement(
        requirement_id="VER-REQ-006",
        title="Coverage is a separate output from attention, and absence "
              "never reads as low risk",
        source="architecture.md section 10; SAFETY-INV-001; LEGACY-BUG-002",
        work_packages=("WP-13",),
        selectors=("tests.unit.engine.test_coverage_aggregation",
                   "tests.unit.engine.test_coverage_axis",
                   "tests.unit.engine.test_coverage_manifest",
                   "tests.unit.engine.test_wp13_boundaries",
                   "tests.unit.engine.test_failure_modes",
                   "tests.unit.application.test_coverage_cli",
                   "tests.safety.test_coverage_safety",
                   "tests.contract.test_wp13_schemas",
                   "tests.integration.engine.test_coverage_end_to_end"),
        criticality=Criticality.P0_CRITICAL,
        safety_invariants=("SAFETY-INV-001",),
    ),
    Requirement(
        requirement_id="VER-REQ-007",
        title="The same input and release bundle produce the same assessment",
        source="architecture.md section 12; SAFETY-INV-006, SAFETY-INV-009",
        work_packages=("WP-14",),
        selectors=("tests.unit.application.test_assessment_determinism",
                   "tests.unit.application.test_assessment_input",
                   "tests.unit.application.test_assessment_preflight",
                   "tests.unit.application.test_assessment_cli",
                   "tests.unit.engine.test_risk_execution",
                   "tests.unit.engine.test_wp14_boundaries",
                   "tests.safety.test_assessment_safety",
                   "tests.contract.test_wp14_schemas",
                   "tests.integration.engine.test_assessment_end_to_end"),
        criticality=Criticality.P0_CRITICAL,
        safety_invariants=("SAFETY-INV-006", "SAFETY-INV-009"),
    ),
    Requirement(
        requirement_id="VER-REQ-008",
        title="Reporting is deterministic and every claim is scanned",
        source="architecture.md section 12.4; docs/architecture/"
               "wp15-deterministic-reporting.md",
        work_packages=("WP-15",),
        selectors=("tests.unit.reporting",
                   "tests.unit.application.test_report_cli",
                   "tests.contract.test_wp15_schemas",
                   "tests.integration.reporting.test_report_end_to_end"),
        criticality=Criticality.P0_CRITICAL,
        safety_invariants=("SAFETY-INV-002", "SAFETY-INV-005",
                           "SAFETY-INV-008"),
    ),
    Requirement(
        requirement_id="VER-REQ-009",
        title="The API's error and security contracts hold",
        source="docs/architecture/wp16-fastapi-application.md; "
               "schemas/wp16/error-contract.schema.json",
        work_packages=("WP-16",),
        selectors=("tests.unit.api",
                   "tests.contract",
                   "tests.integration.api"),
        criticality=Criticality.P0_CRITICAL,
        note="The framework-free half executes everywhere. The ASGI runtime "
             "half is reported from a recorded execution, never inferred from "
             "an installed package.",
    ),
    Requirement(
        requirement_id="VER-REQ-010",
        title="Every rendered page carries the clinical warning, and access "
              "is refused where it must be",
        source="docs/architecture/wp17-server-rendered-web.md",
        work_packages=("WP-17",),
        selectors=("tests.unit.web",
                   "tests.integration.web"),
        criticality=Criticality.P0_CRITICAL,
        safety_invariants=("SAFETY-INV-001", "SAFETY-INV-005"),
    ),
    Requirement(
        requirement_id="VER-REQ-011",
        title="Development and holdout validation cases stay separated",
        source="docs/validation/holdout-separation-policy.md; "
               "docs/architecture/wp18-validation-dataset.md",
        work_packages=("WP-18",),
        selectors=("tests.unit.validation",
                   "tests.failure.test_wp18_partition_violations",
                   "tests.integration.validation"),
        criticality=Criticality.P0_CRITICAL,
        safety_invariants=("SAFETY-INV-009",),
        note="The separation mechanism is verified. There are zero holdout "
             "cases to separate, which is a scientific blocker WP-18 already "
             "reports and WP-19 does not resolve.",
    ),
    Requirement(
        requirement_id="VER-REQ-012",
        title="Every finding resolves to a real evidence record",
        source="architecture.md section 8; SAFETY-INV-006",
        work_packages=("WP-08",),
        selectors=("tests.unit.evidence",
                   "tests.unit.test_wp08_schema"),
        criticality=Criticality.IMPORTANT,
        safety_invariants=("SAFETY-INV-006",),
    ),
    Requirement(
        requirement_id="VER-REQ-013",
        title="The pipeline runs offline: no live source, no LLM, no index",
        source="architecture.md section 5.3; WP-19 acceptance A12",
        work_packages=("WP-04", "WP-10", "WP-11", "WP-19"),
        selectors=("tests.unit.curation.workflow.test_offline_operation",
                   "tests.unit.rules.test_offline_operation",
                   "tests.unit.ingestion.test_transport_and_retry",
                   "tests.unit.verification.test_offline"),
        criticality=Criticality.IMPORTANT,
    ),
    Requirement(
        requirement_id="VER-REQ-014",
        title="Known legacy defects stay fixed and the baseline reproduces",
        source="docs/migration/legacy-inventory.md; scripts/"
               "legacy_bug_registry.py",
        work_packages=("WP-01",),
        selectors=("tests.regression.legacy",
                   "tests.unit.engine.test_legacy_regression",
                   "tests.unit.engine.test_coverage_legacy_regression",
                   "tests.unit.engine.test_risk_legacy_regression",
                   "tests.unit.reporting.test_legacy_report_regression",
                   "tests.unit.normalization.test_legacy_differences",
                   "tests.unit.application.test_legacy_baseline"),
        criticality=Criticality.IMPORTANT,
    ),
    Requirement(
        requirement_id="VER-REQ-015",
        title="The verification system itself cannot report a false green",
        source="architecture.md WP-19; this package",
        work_packages=("WP-19",),
        selectors=("tests.unit.verification",),
        criticality=Criticality.P0_CRITICAL,
        note="A verifier nobody verifies is a decoration. These tests hold "
             "down zero-test execution, unexplained skips, outcome conflation, "
             "stale evidence and scrubbing.",
    ),
    Requirement(
        requirement_id="VER-REQ-016",
        title="The domain layer is standard-library only, immutable, and "
              "carries no ordering it must not have",
        source="architecture.md section 3; docs/architecture/"
               "wp02-domain-and-db.md",
        work_packages=("WP-02",),
        selectors=("tests.unit.domain",
                   "tests.failure.test_domain_layer_violations"),
        criticality=Criticality.P0_CRITICAL,
        safety_invariants=("SAFETY-INV-001", "SAFETY-INV-004",
                           "SAFETY-INV-010"),
        note="Every layer above depends on these being true, so they are "
             "asserted here and re-asserted at each boundary that could leak.",
    ),
    Requirement(
        requirement_id="VER-REQ-017",
        title="Canonicalisation is deterministic and refuses ambiguous input",
        source="architecture.md section 7; docs/evidence/wp07-dq-validation.md",
        work_packages=("WP-07",),
        selectors=("tests.unit.normalization",
                   "tests.unit.test_wp07_schema"),
        criticality=Criticality.IMPORTANT,
    ),
    Requirement(
        requirement_id="VER-REQ-018",
        title="Acquisition is replayable and records where its data came from",
        source="architecture.md sections 4-5; docs/architecture/"
               "wp04-ingestion.md",
        work_packages=("WP-04",),
        selectors=("tests.unit.ingestion",
                   "tests.unit.test_manifest_amendment"),
        criticality=Criticality.IMPORTANT,
        safety_invariants=("SAFETY-INV-010",),
    ),
    Requirement(
        requirement_id="VER-REQ-019",
        title="Source policy decides what may be published, and fails closed",
        source="docs/evidence/wp05-validation.md; config/scientific-sources",
        work_packages=("WP-05",),
        selectors=("tests.unit.scientific",
                   "tests.unit.test_schema_rendering"),
        criticality=Criticality.IMPORTANT,
    ),
    Requirement(
        requirement_id="VER-REQ-020",
        title="Persistence and configuration fail closed, and the seed can "
              "never touch a database it was not pointed at",
        source="architecture.md section 6; docs/architecture/"
               "wp02-domain-and-db.md",
        work_packages=("WP-02",),
        selectors=("tests.unit.infrastructure",
                   "tests.integration.db"),
        criticality=Criticality.P0_CRITICAL,
        safety_invariants=("SAFETY-INV-007",),
        note="The database half runs only against a disposable PostgreSQL and "
             "is reported BLOCKED, with its exact skipped tests, where none "
             "was reachable.",
    ),
    Requirement(
        requirement_id="VER-REQ-021",
        title="Every named safety invariant is enforced, and its detector is "
              "proven by a negative control",
        source="docs/risk-management/safety-contract.md section 2; "
               "docs/architecture/wp20-safety-invariants.md",
        work_packages=("WP-20",),
        selectors=("tests.unit.safety",),
        criticality=Criticality.P0_CRITICAL,
        safety_invariants=("SAFETY-INV-001", "SAFETY-INV-002",
                           "SAFETY-INV-003", "SAFETY-INV-004",
                           "SAFETY-INV-005", "SAFETY-INV-006",
                           "SAFETY-INV-007", "SAFETY-INV-008",
                           "SAFETY-INV-009", "SAFETY-INV-010",
                           "SAFETY-INV-011", "SAFETY-INV-012"),
        note="WP-19 maps tests to invariants. WP-20 enforces them, and this "
             "requirement covers the gate's own suite: a detector that "
             "accepted its mutant would pass every ordinary unit test and "
             "fail here.",
    ),
    Requirement(
        requirement_id="VER-REQ-022",
        title="Every validation metric has a predeclared denominator, and an "
              "unavailable metric is never reported as a zero",
        source="architecture.md section 12.3; "
               "docs/architecture/wp21-validation-metrics.md",
        work_packages=("WP-21",),
        selectors=("tests.unit.benchmark",),
        criticality=Criticality.P0_CRITICAL,
        safety_invariants=("SAFETY-INV-009",),
        note="The failure this covers is not a wrong number - it is a number "
             "where there should be none. A zero denominator rendered as 0%, "
             "or a development case counted as validation evidence, would "
             "read as a result to anyone skimming the dashboard. Mapped to "
             "SAFETY-INV-009 because pooling roles is the same violation the "
             "invariant names, expressed as arithmetic rather than as a case "
             "set.",
    ),
    Requirement(
        requirement_id="VER-REQ-023",
        title="An expert reviewer records an expectation before seeing any "
              "result, and no record is ever edited afterwards",
        source="docs/validation/expert-protocol.md sections 6-11; "
               "docs/architecture/wp22-expert-review.md",
        work_packages=("WP-22",),
        selectors=("tests.unit.expert_review",
                   "tests.unit.web.test_expert_review_flow"),
        criticality=Criticality.P0_CRITICAL,
        safety_invariants=("SAFETY-INV-009",),
        note="The failure this covers is silent. A reviewer who saw the "
             "system's answer first would still produce a complete, "
             "well-formed, hash-linked record - and the resulting agreement "
             "figure would measure nothing but the reviewer having read the "
             "output. So the tests assert structure rather than behaviour: "
             "the pre-reveal view has no field a result could occupy, the "
             "result port is not consulted before the reveal transition "
             "succeeds, and no store in the module has an update or a delete "
             "method to call. Mapped to SAFETY-INV-009 because an unblinded "
             "review entering a validation denominator is the same "
             "contamination the invariant names, expressed as procedure "
             "rather than as a case set.",
    ),
    Requirement(
        requirement_id="VER-REQ-024",
        title="Every governed act names an authenticated actor, and the "
              "record of it cannot be edited",
        source="architecture.md section 13; "
               "docs/architecture/wp23-auth-audit.md; "
               "docs/security/audit-policy.md",
        work_packages=("WP-23",),
        selectors=("tests.unit.security", "tests.unit.audit"),
        criticality=Criticality.P0_CRITICAL,
        safety_invariants=("SAFETY-INV-007", "SAFETY-INV-012"),
        note="Two failures, both silent. The first is an audit trail that "
             "records an actor nobody authenticated - which looks identical "
             "to one that records a person, and is the reason assurance is a "
             "governed value rather than a boolean. The second is a trail "
             "that can be edited, which answers no question at all: a "
             "modified row and a correct one are indistinguishable without a "
             "chain. So the tests assert structure rather than behaviour: "
             "only a validated session may carry SESSION assurance, the "
             "repository has no update or delete method to call, the chain "
             "detects all four tamper shapes, and a governed success whose "
             "audit append fails rolls back. Mapped to SAFETY-INV-007 and "
             "-012 because both name audit completeness as the half WP-23 "
             "owed them.",
    ),
    Requirement(
        requirement_id="VER-REQ-025",
        title="A deployment reports what it has, and every document says "
              "plainly what did not happen",
        source="architecture.md section 14; "
               "docs/architecture/wp24-deployment-reliability.md; "
               "docs/evidence/wp24-build-provenance-report.md",
        work_packages=("WP-24",),
        selectors=("tests.unit.deployment",),
        criticality=Criticality.P0_CRITICAL,
        safety_invariants=("SAFETY-INV-007", "SAFETY-INV-012"),
        note="Two failures, and the second is the one this repository is "
             "actually exposed to. The first is a runtime that shares a "
             "database session between requests or commits a governed change "
             "without the record of it - both invisible in a query and both "
             "asserted here through transaction shape rather than final "
             "state. The second is a report that reads as a success because "
             "a measurement nobody took came back as zero, or because a "
             "rehearsal on a laptop serialised under a name that means "
             "staging. Almost every WP-24 status in this repository is "
             "BLOCKED, so the tests that matter are the ones proving BLOCKED "
             "cannot be mistaken for anything else: null rather than zero, a "
             "rehearsal label that travels into the artifact, and a "
             "TEST_ONLY_REHEARSAL that cannot close a gate. Mapped to "
             "SAFETY-INV-007 and -012 because atomic audit and repeat-run "
             "determinism are the two the WP-20 registry names WP-24 as "
             "owing.",
    ),
    Requirement(
        requirement_id="VER-REQ-026",
        title="The evidence pack reports what this programme has, and no "
              "output can be read as a standard it has not achieved",
        source="architecture.md sections 20 and 21; "
               "docs/ths6/final/README.md; "
               "docs/ths6/final/vocabulary.md",
        work_packages=("WP-25",),
        selectors=("tests.unit.ths6",),
        criticality=Criticality.P0_CRITICAL,
        safety_invariants=("SAFETY-INV-001", "SAFETY-INV-012"),
        note="One failure, in four disguises, and it is the last one this "
             "project is exposed to. A passing test suite presented as "
             "scientific evidence; a gate recorded PASS beside its own unmet "
             "conditions; a sign-off row carrying a name nobody wrote; an "
             "intact evidence pack quoted as an achieved standard. Each is a "
             "document that reads as a success while every underlying "
             "condition is absent, which is the same shape as WP-24's "
             "false-zero and WP-13's missing-data-as-low-risk. So the tests "
             "assert structure rather than values: only REAL_EXECUTED and "
             "REAL_OBSERVED may support a claim, GateRecord refuses to hold "
             "PASS beside an unmet condition, the sign-off schema pins "
             "signatory to null, and pack integrity and THS 6 achievement "
             "are separate fields with separate exit codes. Mapped to "
             "SAFETY-INV-001 because presenting an absence as a result is "
             "the same error that invariant forbids when data is missing, "
             "and to "
             "SAFETY-INV-012 because every gate here is rebuilt from hashed "
             "source artifacts rather than asserted.",
    ),
)


#: Existing tests that relate to each WP-00 safety invariant. A map, never a
#: gate: see ``SAFETY_MAP_DISCLAIMER``. An invariant with an empty tuple has no
#: test mapped to it here, and that emptiness is reported rather than hidden.
SAFETY_INVARIANT_MAP: Mapping[str, Tuple[str, ...]] = {
    # SAFETY-INV-001 - missing data must never read as LOW or
    # NO_ACTIVE_ATTENTION.
    "SAFETY-INV-001": ("tests.safety.test_coverage_safety",
                       "tests.safety.test_assessment_safety",
                       "tests.unit.engine.test_coverage_aggregation",
                       "tests.unit.engine.test_wp13_boundaries",
                       "tests.unit.reporting.test_safe_status_rendering",
                       "tests.unit.web.test_safety",
                       "tests.unit.safety.test_invariant_001"),
    # SAFETY-INV-002 - an LLM must not alter a calculated fact.
    "SAFETY-INV-002": ("tests.unit.reporting.test_fact_preservation",
                       "tests.unit.reporting.test_injection",
                       "tests.unit.safety.test_invariant_002"),
    # SAFETY-INV-003 - only VALIDATED rules from the pinned ruleset execute.
    "SAFETY-INV-003": ("tests.unit.rules.test_rule_lifecycle",
                       "tests.unit.rules.test_ruleset_lifecycle",
                       "tests.unit.rules.test_engine_registry",
                       "tests.integration.db.test_wp11_rules",
                       "tests.unit.safety.test_invariant_003"),
    # SAFETY-INV-004 - RAPID must not implicitly match ULTRARAPID.
    "SAFETY-INV-004": ("tests.unit.engine.test_profile",
                       "tests.unit.engine.test_truth_matrix",
                       "tests.unit.rules.test_exact_semantics",
                       "tests.unit.safety.test_invariant_004"),
    # SAFETY-INV-005 - no candidate is labelled safer, preferred or scored.
    "SAFETY-INV-005": ("tests.adversarial.test_report_claims",
                       "tests.safety.test_coverage_safety",
                       "tests.unit.test_claims",
                       "tests.unit.safety.test_invariant_005"),
    # SAFETY-INV-006 - every finding carries resolvable, pinned evidence.
    "SAFETY-INV-006": ("tests.unit.evidence.test_traceability",
                       "tests.unit.engine.test_risk_execution",
                       "tests.safety.test_assessment_safety",
                       "tests.unit.safety.test_invariant_006"),
    # SAFETY-INV-007 - persistence requires the complete pinned bundle.
    "SAFETY-INV-007": ("tests.unit.application.test_release_pinning",
                       "tests.unit.infrastructure.test_assessment_persistence",
                       "tests.integration.db.test_release_registry",
                       "tests.unit.safety.test_invariant_007"),
    # SAFETY-INV-008 - a conflict must not collapse into a reassuring result.
    #
    # Corrected by WP-20. WP-19 mapped this identifier to the report-injection
    # and claim tests, which are SAFETY-INV-010's subject; conflict handling
    # lives in the coverage engine and the rule conflict tests. The two rows
    # read plausibly and were about the wrong requirements, which is exactly
    # the failure a map nobody resolves against the contract will have.
    "SAFETY-INV-008": ("tests.safety.test_coverage_safety",
                       "tests.unit.rules.test_conflicts",
                       "tests.unit.engine.test_coverage_axis",
                       "tests.unit.safety.test_invariant_008"),
    # SAFETY-INV-009 - development and holdout partitions must not overlap.
    "SAFETY-INV-009": ("tests.unit.validation.test_separation",
                       "tests.failure.test_wp18_partition_violations",
                       "tests.unit.validation.test_cases",
                       "tests.unit.safety.test_invariant_009"),
    # SAFETY-INV-010 - prohibited claim text must block release.
    #
    # Corrected by WP-20; see SAFETY-INV-008 above. WP-19 mapped this to the
    # snapshot and hashing tests, which belong to determinism and immutability,
    # not to the claim scanner.
    "SAFETY-INV-010": ("tests.unit.test_claims",
                       "tests.adversarial.test_report_claims",
                       "tests.unit.reporting.test_injection",
                       "tests.unit.reporting.test_safe_status_rendering",
                       "tests.unit.safety.test_invariant_010"),
    # SAFETY-INV-011 - real patient or genomic data must not enter P0.
    #
    # Added by WP-20. Absent from WP-19's map because that map stopped at ten,
    # following the architecture's "at least 010" rather than the safety
    # contract's twelve.
    "SAFETY-INV-011": ("tests.unit.test_claims",
                       "tests.unit.api.test_security_boundary",
                       "tests.unit.validation.test_cases",
                       "tests.unit.safety.test_invariant_011"),
    # SAFETY-INV-012 - released results are deterministic and auditable.
    #
    # Added by WP-20, and carrying the snapshot and hashing tests that WP-19
    # had filed under SAFETY-INV-010: content identity and canonical hashing
    # are what make a result reproducible and attributable.
    "SAFETY-INV-012": ("tests.unit.application.test_assessment_determinism",
                       "tests.unit.reporting.test_determinism",
                       "tests.unit.domain.test_hashing",
                       "tests.unit.snapshots.test_content_identity",
                       "tests.unit.application.test_release_manifest",
                       "tests.unit.safety.test_invariant_012"),
}


def requirements_by_id() -> Dict[str, Requirement]:
    """The registry keyed by identifier, for lookup rather than iteration."""
    return {requirement.requirement_id: requirement
            for requirement in REQUIREMENTS}
