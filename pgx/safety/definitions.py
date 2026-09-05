# -*- coding: utf-8 -*-
"""The twelve safety invariants, as immutable data.

This is the authoritative machine-readable form of section 2 of
``docs/risk-management/safety-contract.md``. The document is the normative
text; this file is what a build can execute. They are kept in step by
``tests/unit/safety/test_registry.py``, which reads the document's headings and
fails if the two disagree - a registry that had quietly drifted from the
contract would be worse than no registry, because it would look authoritative.

Every entry carries what a reviewer needs to answer four questions without
leaving the file:

* **What must be true?** ``title`` and ``requirement_reference``.
* **Where is it enforced?** ``required_surfaces`` and ``current_surfaces``. The
  two differ where a later work package owns part of the enforcement, and the
  difference is the blocker.
* **How do we know the check works?** ``test_selectors`` for the safe control,
  ``negative_controls`` for the unsafe one. A selector that matches nothing is
  a registry error, not a passing row.
* **What did the legacy system get wrong?** ``legacy_bugs``. Seven of the
  twelve exist because something in ``risk_engine.py`` did the unsafe thing.

``NOT_PRESENT`` appears twice - the LLM gateway and candidate exploration - and
both carry ``absence_markers``. Those are the paths whose *appearance* must
invalidate the evidence. Enforcing the safe absence of a feature is a
legitimate P0 answer; leaving it unenforced once the feature ships is not, so
the markers are checked on every run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

from pgx.safety.vocabulary import (
    BlockerOwner,
    ComplianceState,
    EnforcementSurface,
    InvariantId,
    Severity,
)

__all__ = [
    "Blocker",
    "InvariantDefinition",
    "INVARIANT_DEFINITIONS",
    "definitions_by_id",
    "DETECTOR_EVIDENCE_DISCLAIMER",
]

#: Repeated verbatim into every artifact that reports control detection.
DETECTOR_EVIDENCE_DISCLAIMER = (
    "Detecting an unsafe negative control proves that this software detector "
    "rejects that unsafe state. It is not clinical validation, scientific "
    "validation, expert review, or evidence that the system is safe for any "
    "patient. Those are produced by people under WP-21 and WP-22 and cannot be "
    "produced by running tests.")


@dataclass(frozen=True)
class Blocker:
    """Something outside this work package that stops full enforcement."""

    code: str
    owner: BlockerOwner
    detail: str

    def as_document(self) -> Dict[str, Any]:
        return {"code": self.code, "detail": self.detail,
                "owner": self.owner.value}


@dataclass(frozen=True)
class InvariantDefinition:
    """One safety invariant. Immutable, and complete on its own."""

    invariant_id: InvariantId
    title: str
    #: Where the normative text lives. A section, not a paraphrase.
    requirement_reference: str
    severity: Severity
    #: Everywhere the contract says this must be enforced.
    required_surfaces: Tuple[EnforcementSurface, ...]
    #: Everywhere it *is* enforced today. A subset when a later WP owns part.
    current_surfaces: Tuple[EnforcementSurface, ...]
    owning_work_packages: Tuple[str, ...]
    #: Modules whose tests exercise the safe control. Resolved against real
    #: discovery on every run; one that matches nothing is a registry error.
    test_selectors: Tuple[str, ...]
    #: Identifiers in the negative-control catalogue. At least one, always.
    negative_controls: Tuple[str, ...]
    #: Legacy defects this invariant exists to prevent recurring.
    legacy_bugs: Tuple[str, ...]
    #: The stable code a violation is reported under. A CI job keys on this.
    refusal_code: str
    implementation_state: ComplianceState
    blockers: Tuple[Blocker, ...] = ()
    #: Import paths whose *existence* means a NOT_PRESENT answer has expired.
    absence_markers: Tuple[str, ...] = ()
    note: str = ""

    def as_document(self) -> Dict[str, Any]:
        return {
            "absence_markers": list(self.absence_markers),
            "blockers": [item.as_document() for item in self.blockers],
            "current_surfaces": [s.value for s in self.current_surfaces],
            "implementation_state": self.implementation_state.value,
            "invariant_id": self.invariant_id.value,
            "legacy_bugs": list(self.legacy_bugs),
            "negative_controls": list(self.negative_controls),
            "note": self.note,
            "owning_work_packages": list(self.owning_work_packages),
            "refusal_code": self.refusal_code,
            "required_surfaces": [s.value for s in self.required_surfaces],
            "requirement_reference": self.requirement_reference,
            "severity": self.severity.value,
            "test_selectors": list(self.test_selectors),
            "title": self.title,
        }

    @property
    def surface_gap(self) -> Tuple[EnforcementSurface, ...]:
        """Surfaces the contract requires that nothing enforces yet."""
        current = set(self.current_surfaces)
        return tuple(s for s in self.required_surfaces if s not in current)


_S = EnforcementSurface
_C = ComplianceState


INVARIANT_DEFINITIONS: Tuple[InvariantDefinition, ...] = (
    InvariantDefinition(
        invariant_id=InvariantId.INV_001,
        title="Missing data must never produce LOW or NO_ACTIVE_ATTENTION",
        requirement_reference="docs/risk-management/safety-contract.md "
                              "section 2, SAFETY-INV-001; section 4",
        severity=Severity.CRITICAL_PATIENT_FACING,
        required_surfaces=(_S.DOMAIN_VALUES, _S.COVERAGE_ENGINE,
                           _S.ASSESSMENT_ENGINE, _S.DETERMINISTIC_REPORT,
                           _S.API_SERIALIZATION, _S.WEB_RENDERING),
        current_surfaces=(_S.DOMAIN_VALUES, _S.COVERAGE_ENGINE,
                          _S.ASSESSMENT_ENGINE, _S.DETERMINISTIC_REPORT,
                          _S.API_SERIALIZATION, _S.WEB_RENDERING),
        owning_work_packages=("WP-13", "WP-14", "WP-15"),
        test_selectors=("tests.safety.test_coverage_safety",
                        "tests.safety.test_assessment_safety",
                        "tests.unit.engine.test_coverage_aggregation",
                        "tests.unit.safety.test_invariant_001"),
        negative_controls=("NC-INV-001-ABSENCE-MAPPED-TO-LOW",
                           "NC-INV-001-NOT-ASSESSED-IN-MAXIMUM"),
        legacy_bugs=("LEGACY-BUG-002",),
        refusal_code="SAFETY_FALSE_REASSURANCE",
        implementation_state=_C.COMPLIANT,
        note="The highest-consequence failure mode of a PGx tool is false "
             "reassurance: a clinician reading 'no risk' where the correct "
             "reading is 'we did not look'. Measured as a corpus with a target "
             "of exactly zero unsafe outputs - a software count, never a "
             "clinical false-negative rate.",
    ),
    InvariantDefinition(
        invariant_id=InvariantId.INV_002,
        title="An optional LLM must never alter calculated facts",
        requirement_reference="docs/risk-management/safety-contract.md "
                              "section 2, SAFETY-INV-002; section 6",
        severity=Severity.CRITICAL_PATIENT_FACING,
        required_surfaces=(_S.LLM_ABSENCE, _S.DETERMINISTIC_REPORT,
                           _S.CLAIM_SCANNER),
        current_surfaces=(_S.LLM_ABSENCE, _S.DETERMINISTIC_REPORT,
                          _S.CLAIM_SCANNER),
        owning_work_packages=("WP-15", "P1-06"),
        test_selectors=("tests.unit.reporting.test_fact_preservation",
                        "tests.unit.reporting.test_injection",
                        "tests.unit.safety.test_invariant_002"),
        negative_controls=("NC-INV-002-RENDERER-CHANGES-ATTENTION",
                           "NC-INV-002-RENDERER-INVENTS-DOSE",
                           "NC-INV-002-RENDERER-DROPS-VERSION"),
        legacy_bugs=(),
        refusal_code="SAFETY_LLM_ALTERED_FACT",
        implementation_state=_C.NOT_PRESENT,
        absence_markers=("pgx/reporting/llm_gateway.py",
                         "pgx/reporting/narration_provider.py",
                         "apps/api/routers/narration.py"),
        blockers=(Blocker("SAFETY_LLM_RENDERER_IS_A_P1_FEATURE",
                          BlockerOwner.P1_FEATURE,
                          "P1-06 owns the optional narration renderer. P0 "
                          "ships none, the default is disabled, and the "
                          "deterministic report needs no model at all. The "
                          "adversarial fixtures here are test-only doubles."),),
        note="Enforced structurally: no LLM is required for deterministic "
             "output and the default is off. The negative controls drive "
             "test-only adversarial renderer outputs through the same fact "
             "post-check, so the detector is proven before the feature exists.",
    ),
    InvariantDefinition(
        invariant_id=InvariantId.INV_003,
        title="Draft, rejected, superseded or deprecated rules must never "
              "execute; only VALIDATED rules from the pinned ruleset may "
              "participate",
        requirement_reference="docs/risk-management/safety-contract.md "
                              "section 2, SAFETY-INV-003",
        severity=Severity.CRITICAL_EVIDENTIAL,
        required_surfaces=(_S.RULESET_PINNING, _S.ASSESSMENT_ENGINE,
                           _S.COVERAGE_ENGINE),
        current_surfaces=(_S.RULESET_PINNING, _S.ASSESSMENT_ENGINE,
                          _S.COVERAGE_ENGINE),
        owning_work_packages=("WP-11", "WP-14"),
        test_selectors=("tests.unit.rules.test_rule_lifecycle",
                        "tests.unit.rules.test_ruleset_lifecycle",
                        "tests.safety.test_coverage_safety",
                        "tests.unit.safety.test_invariant_003"),
        negative_controls=("NC-INV-003-DRAFT-RULE-FIRES",
                           "NC-INV-003-DEPRECATED-RULE-FIRES",
                           "NC-INV-003-UNPINNED-RULESET-ACCEPTED"),
        legacy_bugs=("LEGACY-BUG-006",),
        refusal_code="SAFETY_UNVALIDATED_RULE_EXECUTED",
        implementation_state=_C.COMPLIANT,
        note="An invalid ruleset must fail closed. Silently filtering the "
             "unsafe rules and returning a reassuring answer would be the "
             "worst of both: the governance is bypassed and nobody is told.",
    ),
    InvariantDefinition(
        invariant_id=InvariantId.INV_004,
        title="RAPID must not implicitly match ULTRARAPID",
        requirement_reference="docs/risk-management/safety-contract.md "
                              "section 2, SAFETY-INV-004",
        severity=Severity.CRITICAL_PATIENT_FACING,
        required_surfaces=(_S.DOMAIN_VALUES, _S.PHENOTYPE_NORMALIZATION,
                           _S.ASSESSMENT_ENGINE),
        current_surfaces=(_S.DOMAIN_VALUES, _S.PHENOTYPE_NORMALIZATION,
                          _S.ASSESSMENT_ENGINE),
        owning_work_packages=("WP-07", "WP-12"),
        test_selectors=("tests.unit.engine.test_truth_matrix",
                        "tests.unit.engine.test_profile",
                        "tests.unit.rules.test_exact_semantics",
                        "tests.unit.safety.test_invariant_004"),
        negative_controls=("NC-INV-004-PREFIX-MATCHER",
                           "NC-INV-004-SYNONYM-TABLE",
                           "NC-INV-004-ORDINAL-PROXIMITY"),
        legacy_bugs=("LEGACY-BUG-001",),
        refusal_code="SAFETY_PHENOTYPE_CROSS_MATCH",
        implementation_state=_C.COMPLIANT,
        note="The legacy matcher let RAPID and ULTRARAPID match each other, "
             "applying a rule outside its evidence. Implicit equivalence is an "
             "unreviewed scientific claim. The whole 6x6 matrix is exercised.",
    ),
    InvariantDefinition(
        invariant_id=InvariantId.INV_005,
        title="A candidate must not be labelled safer, preferred, suitable or "
              "recommended, and must not receive a clinical suitability score",
        requirement_reference="docs/risk-management/safety-contract.md "
                              "section 2, SAFETY-INV-005; section 7",
        severity=Severity.CRITICAL_PATIENT_FACING,
        required_surfaces=(_S.CANDIDATE_ABSENCE, _S.CLAIM_SCANNER,
                           _S.DETERMINISTIC_REPORT, _S.API_SERIALIZATION,
                           _S.WEB_RENDERING),
        current_surfaces=(_S.CANDIDATE_ABSENCE, _S.CLAIM_SCANNER,
                          _S.DETERMINISTIC_REPORT, _S.API_SERIALIZATION,
                          _S.WEB_RENDERING),
        owning_work_packages=("WP-00", "WP-15", "P1-02"),
        test_selectors=("tests.safety.test_coverage_safety",
                        "tests.adversarial.test_report_claims",
                        "tests.unit.test_claims",
                        "tests.unit.safety.test_invariant_005"),
        negative_controls=("NC-INV-005-SAFETY-SCORE",
                           "NC-INV-005-ORDERED-BY-ATTENTION",
                           "NC-INV-005-PREFERRED-LABEL"),
        legacy_bugs=("LEGACY-BUG-009",),
        refusal_code="SAFETY_CANDIDATE_PREFERENCE",
        implementation_state=_C.NOT_PRESENT,
        absence_markers=("pgx/engine/candidates.py",
                         "pgx/engine/alternatives.py",
                         "apps/api/routers/candidates.py",
                         "apps/web/routers/candidates.py"),
        blockers=(Blocker("SAFETY_CANDIDATE_EXPLORATION_IS_A_P1_FEATURE",
                          BlockerOwner.P1_FEATURE,
                          "P1-02 owns candidate exploration. P0 ships none. "
                          "The legacy 0-100 suitability score is removed and "
                          "must not return."),),
        note="A ranked list is read as a recommendation regardless of "
             "disclaimers. The legacy score mixed 'we have data' with 'this is "
             "a good option', which is precisely the confusion that harms "
             "patients.",
    ),
    InvariantDefinition(
        invariant_id=InvariantId.INV_006,
        title="Every calculated finding must carry resolvable, pinned evidence",
        requirement_reference="docs/risk-management/safety-contract.md "
                              "section 2, SAFETY-INV-006",
        severity=Severity.CRITICAL_EVIDENTIAL,
        required_surfaces=(_S.EVIDENCE_RESOLUTION, _S.ASSESSMENT_ENGINE,
                           _S.COVERAGE_ENGINE, _S.DETERMINISTIC_REPORT),
        current_surfaces=(_S.EVIDENCE_RESOLUTION, _S.ASSESSMENT_ENGINE,
                          _S.COVERAGE_ENGINE, _S.DETERMINISTIC_REPORT),
        owning_work_packages=("WP-08", "WP-14", "WP-15"),
        test_selectors=("tests.safety.test_assessment_safety",
                        "tests.unit.evidence.test_traceability",
                        "tests.unit.safety.test_invariant_006"),
        negative_controls=("NC-INV-006-DANGLING-EVIDENCE-REFERENCE",
                           "NC-INV-006-FINDING-WITHOUT-EVIDENCE",
                           "NC-INV-006-EVIDENCE-OUTSIDE-PINNED-DATASET"),
        legacy_bugs=("LEGACY-BUG-005",),
        refusal_code="SAFETY_EVIDENCE_NOT_RESOLVABLE",
        implementation_state=_C.COMPLIANT,
        note="Without a resolvable citation an 'explainable' output is an "
             "assertion. A missing reference must remove the finding and "
             "degrade coverage with EVIDENCE_REFERENCE_MISSING - never leave "
             "the finding standing with a broken chain.",
    ),
    InvariantDefinition(
        invariant_id=InvariantId.INV_007,
        title="Assessment persistence requires the complete pinned release "
              "bundle plus input and output hashes",
        requirement_reference="docs/risk-management/safety-contract.md "
                              "section 2, SAFETY-INV-007; section 9",
        severity=Severity.CRITICAL_EVIDENTIAL,
        required_surfaces=(_S.RELEASE_PINNING, _S.PERSISTENCE_BOUNDARY,
                           _S.ASSESSMENT_ENGINE),
        current_surfaces=(_S.RELEASE_PINNING, _S.PERSISTENCE_BOUNDARY,
                          _S.ASSESSMENT_ENGINE),
        owning_work_packages=("WP-03", "WP-14", "WP-23"),
        test_selectors=("tests.unit.application.test_release_pinning",
                        "tests.unit.infrastructure.test_assessment_persistence",
                        "tests.unit.safety.test_invariant_007",
                        "tests.unit.audit.test_governed_audit"),
        negative_controls=("NC-INV-007-MISSING-RELEASE-FIELD",
                           "NC-INV-007-MISSING-INPUT-HASH",
                           "NC-INV-007-MISSING-OUTPUT-HASH",
                           "NC-INV-007-PARTIAL-PERSISTENCE"),
        legacy_bugs=("LEGACY-BUG-007",),
        refusal_code="SAFETY_RELEASE_BUNDLE_INCOMPLETE",
        implementation_state=_C.COMPLIANT,
        # Replaced at WP-23. The implementation blocker is gone: the
        # canonical governed audit event carries actor, role, session
        # reference, authentication mechanism, assurance and correlation id,
        # and refuses to be constructed without them where they apply. What
        # remains true is operational rather than owed - the enforcement
        # exists and no deployment is running it, which is a different fact
        # and belongs to a different owner.
        blockers=(Blocker("SAFETY_AUDIT_IDENTITY_NOT_OPERATIONAL",
                          BlockerOwner.WP_24_CI_DEPLOY,
                          "The canonical audit record enforces actor, role, "
                          "session reference, authentication assurance and "
                          "correlation id. WP-24 has now built the "
                          "composition that would run it: a request-scoped "
                          "session, an audit sink backed by it, and one "
                          "transaction in which a governed change and its "
                          "record either both commit or neither does. What "
                          "is still absent is an environment - no PostgreSQL "
                          "server, no image and no deployment exist here, so "
                          "no row has ever been written. The mechanism is "
                          "implemented, composed and unexercised, which is a "
                          "narrower blocker than it was and is still a "
                          "blocker."),),
        note="Each required field is omitted individually rather than as a "
             "set, so a single missing hash cannot slip through a check that "
             "only counts.",
    ),
    InvariantDefinition(
        invariant_id=InvariantId.INV_008,
        title="A source or rule conflict must not collapse into a reassuring "
              "result",
        requirement_reference="docs/risk-management/safety-contract.md "
                              "section 2, SAFETY-INV-008",
        severity=Severity.CRITICAL_PATIENT_FACING,
        required_surfaces=(_S.COVERAGE_ENGINE, _S.ASSESSMENT_ENGINE,
                           _S.DETERMINISTIC_REPORT),
        current_surfaces=(_S.COVERAGE_ENGINE, _S.ASSESSMENT_ENGINE,
                          _S.DETERMINISTIC_REPORT),
        owning_work_packages=("WP-13", "WP-14", "P1-03"),
        test_selectors=("tests.safety.test_coverage_safety",
                        "tests.unit.rules.test_conflicts",
                        "tests.unit.safety.test_invariant_008"),
        negative_controls=("NC-INV-008-CONFLICT-TAKES-LOWER-LEVEL",
                           "NC-INV-008-CONFLICT-AVERAGED",
                           "NC-INV-008-CONFLICTING-RULE-DROPPED"),
        legacy_bugs=(),
        refusal_code="SAFETY_CONFLICT_COLLAPSED",
        implementation_state=_C.COMPLIANT,
        note="Conflict is information. Silent resolution manufactures a false "
             "consensus and hides exactly the case a clinician most needs to "
             "see. A conflict with no independent valid finding must not "
             "manufacture attention either.",
    ),
    InvariantDefinition(
        invariant_id=InvariantId.INV_009,
        title="DEVELOPMENT, INTERNAL_HOLDOUT and EXPERT_HOLDOUT must not "
              "overlap or be pooled",
        requirement_reference="docs/risk-management/safety-contract.md "
                              "section 2, SAFETY-INV-009; section 8",
        severity=Severity.CRITICAL_EVIDENTIAL,
        required_surfaces=(_S.VALIDATION_PARTITION,),
        current_surfaces=(_S.VALIDATION_PARTITION,),
        owning_work_packages=("WP-18",),
        test_selectors=("tests.unit.validation.test_separation",
                        "tests.failure.test_wp18_partition_violations",
                        "tests.unit.safety.test_invariant_009"),
        negative_controls=("NC-INV-009-ID-IN-TWO-ROLES",
                           "NC-INV-009-CONTENT-DUPLICATE-ACROSS-PARTITIONS",
                           "NC-INV-009-DERIVATION-FAMILY-SPLIT"),
        legacy_bugs=(),
        refusal_code="SAFETY_PARTITION_OVERLAP",
        implementation_state=_C.COMPLIANT,
        blockers=(Blocker("SAFETY_NO_HOLDOUT_CASES_EXIST",
                          BlockerOwner.SCIENTIFIC_CURATORS,
                          "The separation mechanism is enforced and proven. "
                          "There are zero holdout cases to separate, which is "
                          "a scientific blocker WP-18 reports and no code can "
                          "close."),
                  # SAFETY_POOLED_METRIC_CHECK_OWNED_BY_WP21 was removed at
                  # WP-21, and only that one. It said the pooling and
                  # zero-denominator questions were unanswerable until metrics
                  # existed; they exist now and both are enforced -
                  # `MetricDefinition` refuses an evidence metric that accepts
                  # DEVELOPMENT, `measured_rate` turns a zero denominator into
                  # UNAVAILABLE rather than 0%, and the published report
                  # schema pins `combined_overall_metric` to null so a pooled
                  # figure has no field to live in.
                  #
                  # The blocker above stays. Zero holdout cases is a
                  # scientific fact no code closes, and removing both would
                  # have turned a real gap into a green row.
                  ),
        note="Reuses WP-18's audit_partition rather than re-deciding "
             "separation. Independence is the entire evidential value of a "
             "holdout set; once it leaks, no later analysis can undo it.",
    ),
    InvariantDefinition(
        invariant_id=InvariantId.INV_010,
        title="Prohibited claim text must block release of user-facing output",
        requirement_reference="docs/risk-management/safety-contract.md "
                              "section 2, SAFETY-INV-010; section 3",
        severity=Severity.CRITICAL_PATIENT_FACING,
        required_surfaces=(_S.CLAIM_SCANNER, _S.DETERMINISTIC_REPORT,
                           _S.API_SERIALIZATION, _S.WEB_RENDERING),
        current_surfaces=(_S.CLAIM_SCANNER, _S.DETERMINISTIC_REPORT,
                          _S.API_SERIALIZATION, _S.WEB_RENDERING),
        owning_work_packages=("WP-00", "WP-15", "WP-16", "WP-17"),
        test_selectors=("tests.unit.test_claims",
                        "tests.adversarial.test_report_claims",
                        "tests.unit.reporting.test_safe_status_rendering",
                        "tests.unit.safety.test_invariant_010"),
        negative_controls=("NC-INV-010-REPORT-CARRIES-RECOMMENDATION",
                           "NC-INV-010-API-STRING-CARRIES-DOSE",
                           "NC-INV-010-TEMPLATE-CARRIES-REASSURANCE"),
        legacy_bugs=("LEGACY-BUG-012",),
        refusal_code="SAFETY_PROHIBITED_CLAIM",
        implementation_state=_C.COMPLIANT,
        note="The scanner is a lexical last line, not an NLP system, and its "
             "documented limits are carried into the report rather than "
             "quietly dropped. Structural checks supplement it. A blocking "
             "claim prevents release; the text is never auto-edited into "
             "compliance.",
    ),
    InvariantDefinition(
        invariant_id=InvariantId.INV_011,
        title="Real patient or genomic data must not enter P0",
        requirement_reference="docs/risk-management/safety-contract.md "
                              "section 2, SAFETY-INV-011; "
                              "docs/architecture/intended-purpose.md section 3",
        severity=Severity.CRITICAL_SCOPE,
        required_surfaces=(_S.INPUT_BOUNDARY, _S.API_SERIALIZATION,
                           _S.VALIDATION_PARTITION, _S.CLAIM_SCANNER),
        current_surfaces=(_S.INPUT_BOUNDARY, _S.API_SERIALIZATION,
                          _S.VALIDATION_PARTITION, _S.CLAIM_SCANNER),
        owning_work_packages=("WP-00", "WP-16", "WP-18"),
        test_selectors=("tests.unit.test_claims",
                        "tests.unit.validation.test_cases",
                        "tests.unit.api.test_security_boundary",
                        "tests.unit.safety.test_invariant_011"),
        negative_controls=("NC-INV-011-NESTED-GENOTYPE-FIELD",
                           "NC-INV-011-PATIENT-IDENTIFIER",
                           "NC-INV-011-RAW-SEQUENCING-PAYLOAD",
                           "NC-INV-011-PILOT-MODE-REQUESTED"),
        legacy_bugs=(),
        refusal_code="SAFETY_REAL_PATIENT_DATA",
        implementation_state=_C.COMPLIANT,
        note="Prohibited field names are refused at any nesting depth, not "
             "only at the top level. Public gene nomenclature - CYP2D6, a drug "
             "name - is not patient data and must not be refused; the "
             "distinction is tested in both directions. PILOT stays disabled.",
    ),
    InvariantDefinition(
        invariant_id=InvariantId.INV_012,
        title="Released results must be deterministic and auditable",
        requirement_reference="docs/risk-management/safety-contract.md "
                              "section 2, SAFETY-INV-012; section 9",
        severity=Severity.CRITICAL_EVIDENTIAL,
        required_surfaces=(_S.ASSESSMENT_ENGINE, _S.RELEASE_PINNING,
                           _S.PERSISTENCE_BOUNDARY, _S.DETERMINISTIC_REPORT),
        current_surfaces=(_S.ASSESSMENT_ENGINE, _S.RELEASE_PINNING,
                          _S.DETERMINISTIC_REPORT),
        owning_work_packages=("WP-14", "WP-23", "WP-24"),
        test_selectors=("tests.unit.application.test_assessment_determinism",
                        "tests.unit.reporting.test_determinism",
                        "tests.unit.safety.test_invariant_012",
                        "tests.unit.audit.test_governed_audit"),
        negative_controls=("NC-INV-012-SHUFFLED-INPUT-CHANGES-OUTPUT",
                           "NC-INV-012-MID-RUN-RELEASE-CHANGE",
                           "NC-INV-012-WALL-CLOCK-IN-OUTPUT"),
        legacy_bugs=("LEGACY-BUG-007",),
        refusal_code="SAFETY_NON_DETERMINISTIC_RESULT",
        implementation_state=_C.COMPLIANT,
        # Replaced at WP-23, on the same terms as SAFETY-INV-007. Audit
        # completeness is now enforced: the event refuses to omit a required
        # trace field, the chain detects edit, deletion, insertion and
        # reordering, the repository has no update or delete method, and a
        # governed success whose audit append fails rolls back. What is still
        # missing is a deployment running it - and that is WP-24's, not a
        # gap in the enforcement.
        blockers=(Blocker("SAFETY_AUDIT_COMPLETENESS_NOT_OPERATIONAL",
                          BlockerOwner.WP_24_CI_DEPLOY,
                          "The append-only, hash-linked audit record enforces "
                          "every required trace field and is atomic with the "
                          "governed change. WP-24 has composed the store and "
                          "the transaction around it, and has written the "
                          "verification command; no chain has been verified "
                          "against real rows because no server exists here "
                          "to hold any. Implemented, composed, and never "
                          "run."),
                  Blocker("SAFETY_OPERATIONAL_REPEATABILITY_OWNED_BY_WP24",
                          BlockerOwner.WP_24_CI_DEPLOY,
                          "Repeat-run determinism across deployments and over "
                          "time is a CI property. WP-20 proves it within one "
                          "process and one machine. WP-24 has now written the "
                          "pipeline that would prove the rest, and no "
                          "provider has run it: this repository has no "
                          "commits, so there has been nothing to run "
                          "against."),),
        note="Determinism is proven by re-running the same pinned input with "
             "ordering variations and comparing structured bytes and hashes. "
             "The audit half stays explicitly blocked.",
    ),
)


def definitions_by_id() -> Mapping[str, InvariantDefinition]:
    """The registry keyed by identifier string."""
    return {definition.invariant_id.value: definition
            for definition in INVARIANT_DEFINITIONS}
