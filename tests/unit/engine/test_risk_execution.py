# -*- coding: utf-8 -*-
"""Rule execution on a covered axis (section C).

A finding is emitted only when every one of seven things is true: the axis
names exactly one supporting rule, that rule is a member of the pinned frozen
ruleset, its content hash equals what coverage recorded, the frozen artifact
carries an approval record for that exact content, its condition names this
drug and gene, WP-12's matcher reports MATCH, and its evidence resolves.

Each of those is re-checked here even though coverage checked it already, and
the reason is the case where the two disagree. Coverage was computed against a
manifest; this runs against the artifact. A FULL axis whose rule does not
verify means one of the two governed documents is wrong, and **neither may be
trusted for this run**. So the assessment fails closed rather than quietly
reporting the axis as unassessed - which would hide a disagreement between two
approved artifacts behind an answer that looks routine.
"""

from __future__ import annotations

import dataclasses
import unittest

from pgx.domain.enums import AttentionLevel, CoverageStatus
from pgx.engine.coverage_models import AxisCoverage, CoverageResult
from pgx.engine.risk import (CalculationRequest, calculate_assessment,
                             evaluate_axis_finding)
from pgx.engine.risk_errors import (AssessmentEngineError,
                                    AssessmentExecutionError,
                                    AssessmentInputError)
from tests.fixtures.wp13.synthetic import (DRUG_1, DRUG_2, GENE_1, GENE_2,
                                           GENE_3, UNKNOWN_DRUG,
                                           synthetic_conflict)
from tests.unit.application._assessment_support import SyntheticAssessmentWorld


class ExecutionCase(unittest.TestCase):

    def setUp(self):
        self.world = SyntheticAssessmentWorld(expected_extra_gene=True)
        self.addCleanup(self.world.close)
        self.pinned = self.world.resolver.resolve()

    def request(self, *, medications=(DRUG_1,), phenotypes=None,
                coverage=None, frozen=None, resolver="default"):
        assessment_input = self.world.input(medications=medications,
                                            phenotypes=phenotypes)
        if coverage is None:
            from pgx.engine.coverage import CoverageRequest, evaluate_coverage
            coverage = evaluate_coverage(CoverageRequest(
                profile=assessment_input.profile,
                medications=assessment_input.medications,
                manifest=self.pinned.coverage_manifest,
                frozen_ruleset=self.pinned.frozen_ruleset,
                drug_catalogue=self.pinned.drug_catalogue,
                evidence_resolver=self.pinned.evidence_resolver))
        return CalculationRequest(
            profile=assessment_input.profile, coverage=coverage,
            frozen_ruleset=(frozen if frozen is not None
                            else self.pinned.frozen_ruleset),
            provenance=self.pinned.provenance,
            evidence_resolver=(self.pinned.evidence_resolver
                               if resolver == "default" else resolver))

    def coverage_for(self, **kwargs):
        return self.request(**kwargs).coverage

    def with_axis(self, replace, **kwargs):
        """A coverage result with its first FULL axis altered."""
        coverage = self.coverage_for(**kwargs)
        medications = []
        for medication in coverage.medications:
            axes = []
            for axis in medication.axes:
                if axis.status is CoverageStatus.FULL and replace is not None:
                    axis = dataclasses.replace(axis, **replace)
                    replace = None
                axes.append(axis)
            medications.append(dataclasses.replace(medication,
                                                   axes=tuple(axes)))
        return dataclasses.replace(coverage, medications=tuple(medications))


class TestAValidatedMemberRuleExecutes(ExecutionCase):

    def test_a_full_axis_produces_a_finding(self):
        computation = calculate_assessment(
            self.request(phenotypes={GENE_1: "POOR", GENE_2: "POOR"}))
        self.assertEqual(len(computation.findings), 2)

    def test_the_finding_carries_the_governed_attention_level(self):
        computation = calculate_assessment(
            self.request(phenotypes={GENE_1: "POOR"}))
        finding = computation.findings[0]
        self.assertIsInstance(finding.attention_level, AttentionLevel)
        self.assertIsNot(finding.attention_level, AttentionLevel.NOT_ASSESSED)

    def test_the_finding_carries_the_rule_it_executed(self):
        computation = calculate_assessment(
            self.request(phenotypes={GENE_1: "POOR"}))
        finding = computation.findings[0]
        members = {item.rule_id.to_json(): item
                   for item in self.world.frozen.rules()}
        self.assertIn(finding.rule_id, members)
        self.assertEqual(finding.rule_content_hash,
                         members[finding.rule_id].content_hash())
        self.assertGreaterEqual(finding.rule_version, 1)
        self.assertTrue(finding.rule_family_id)

    def test_the_finding_carries_the_rationale_reference(self):
        """What WP-11's governed outcome actually contains, carried through
        unchanged rather than reworded."""
        computation = calculate_assessment(
            self.request(phenotypes={GENE_1: "POOR"}))
        finding = computation.findings[0]
        member = [item for item in self.world.frozen.rules()
                  if item.rule_id.to_json() == finding.rule_id][0]
        self.assertEqual(finding.rationale_reference,
                         member.outcome.rationale_reference)

    def test_no_scientific_code_is_invented(self):
        """The governed outcome carries none. Absence is the honest value."""
        computation = calculate_assessment(
            self.request(phenotypes={GENE_1: "POOR", GENE_2: "POOR"}))
        for finding in computation.findings:
            with self.subTest(gene=finding.gene_canonical_key):
                self.assertIsNone(finding.effect_code)
                self.assertIsNone(finding.explanation_code)

    def test_the_finding_carries_its_curation_provenance(self):
        computation = calculate_assessment(
            self.request(phenotypes={GENE_1: "POOR"}))
        finding = computation.findings[0]
        self.assertTrue(finding.curation_revision_id)
        self.assertTrue(finding.curation_revision_hash.startswith("sha256:"))


class TestOnlyGovernedRulesMayExecute(ExecutionCase):

    def test_a_rule_with_no_approval_record_is_refused(self):
        """Membership is not validation. A rule inside a frozen artifact whose
        approval record is absent is a rule nobody is recorded as having
        validated (SAFETY-INV-003)."""
        stripped = dataclasses.replace(self.world.frozen, approvals=())
        with self.assertRaises(AssessmentExecutionError) as caught:
            calculate_assessment(self.request(phenotypes={GENE_1: "POOR"},
                                              frozen=stripped))
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_RULE_NOT_EXECUTABLE")

    def test_an_approval_evidencing_other_content_is_refused(self):
        altered = tuple(
            dataclasses.replace(record,
                                rule_content_hash="sha256:" + "e" * 64)
            for record in self.world.frozen.approvals)
        frozen = dataclasses.replace(self.world.frozen, approvals=altered)
        with self.assertRaises(AssessmentExecutionError) as caught:
            calculate_assessment(self.request(phenotypes={GENE_1: "POOR"},
                                              frozen=frozen))
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_RULE_NOT_EXECUTABLE")

    def test_a_rule_that_is_not_a_member_is_refused(self):
        coverage = self.with_axis(
            {"rule_references": ({"rule_id":
                                  "00000000-0000-4000-8000-000000000000",
                                  "rule_version": 1,
                                  "rule_content_hash": "sha256:" + "1" * 64},)},
            phenotypes={GENE_1: "POOR"})
        with self.assertRaises(AssessmentExecutionError) as caught:
            calculate_assessment(self.request(coverage=coverage,
                                              phenotypes={GENE_1: "POOR"}))
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_RULE_NOT_EXECUTABLE")

    def test_a_rule_whose_content_changed_is_refused(self):
        member = self.world.frozen.rules()[0]
        coverage = self.with_axis(
            {"rule_references": ({"rule_id": member.rule_id.to_json(),
                                  "rule_version": member.rule_version,
                                  "rule_content_hash": "sha256:" + "2" * 64},)},
            phenotypes={GENE_1: "POOR", GENE_2: "POOR"})
        with self.assertRaises(AssessmentExecutionError) as caught:
            calculate_assessment(self.request(
                coverage=coverage, phenotypes={GENE_1: "POOR", GENE_2: "POOR"}))
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_RULE_HASH_MISMATCH")

    def test_an_axis_naming_two_rules_fails_closed(self):
        """WP-11 refuses a ruleset in which two rules cover one axis. If one
        appears anyway, this engine will not pick between them."""
        member = self.world.frozen.rules()[0]
        reference = {"rule_id": member.rule_id.to_json(),
                     "rule_version": member.rule_version,
                     "rule_content_hash": member.content_hash()}
        other = dict(reference)
        other["rule_id"] = "00000000-0000-4000-8000-000000000009"
        coverage = self.with_axis({"rule_references": (reference, other)},
                                  phenotypes={GENE_1: "POOR", GENE_2: "POOR"})
        with self.assertRaises(AssessmentExecutionError) as caught:
            calculate_assessment(self.request(
                coverage=coverage, phenotypes={GENE_1: "POOR", GENE_2: "POOR"}))
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_CONFLICT_UNRESOLVED")

    def test_a_disagreement_is_never_downgraded_to_not_assessed(self):
        """The whole point of failing closed. A FULL axis whose rule is absent
        is corruption; reporting it as absence would make two governed
        artifacts disagreeing look like an ordinary uncovered gene."""
        coverage = self.with_axis(
            {"rule_references": ({"rule_id":
                                  "00000000-0000-4000-8000-000000000000",
                                  "rule_version": 1,
                                  "rule_content_hash": "sha256:" + "3" * 64},)},
            phenotypes={GENE_1: "POOR"})
        with self.assertRaises(AssessmentEngineError):
            calculate_assessment(self.request(coverage=coverage,
                                              phenotypes={GENE_1: "POOR"}))


class TestPhenotypeMatchingIsWp12s(ExecutionCase):

    def test_the_engine_calls_the_wp12_matcher(self):
        from pgx.engine import risk
        import inspect
        source = inspect.getsource(risk)
        self.assertIn("match_observation", source)

    def test_a_rule_that_does_not_match_the_observation_fails_closed(self):
        """Coverage said FULL; the matcher says no. One of the two is wrong."""
        coverage = self.coverage_for(phenotypes={GENE_1: "POOR"})
        other = self.world.input(phenotypes={GENE_1: "NORMAL"}).profile
        request = dataclasses.replace(
            self.request(coverage=coverage, phenotypes={GENE_1: "POOR"}),
            profile=other)
        with self.assertRaises(AssessmentExecutionError) as caught:
            calculate_assessment(request)
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_RULE_DID_NOT_MATCH")

    def test_rapid_never_reaches_an_ultrarapid_rule(self):
        """SAFETY-INV-004, inherited. Coverage refuses the axis first, so no
        finding is produced and attention is NOT_ASSESSED."""
        for value in ("RAPID", "ULTRARAPID"):
            with self.subTest(phenotype=value):
                computation = calculate_assessment(
                    self.request(phenotypes={GENE_1: value, GENE_2: value}))
                self.assertEqual(computation.findings, ())
                self.assertIs(computation.overall_attention,
                              AttentionLevel.NOT_ASSESSED)

    def test_an_exact_phenotype_is_required(self):
        for value in ("NORMAL", "INTERMEDIATE"):
            with self.subTest(phenotype=value):
                computation = calculate_assessment(
                    self.request(phenotypes={GENE_1: value, GENE_2: value}))
                self.assertEqual(computation.findings, ())

    def test_a_missing_observation_on_a_full_axis_fails_closed(self):
        coverage = self.coverage_for(phenotypes={GENE_1: "POOR"})
        empty = self.world.input(phenotypes={GENE_3: "POOR"}).profile
        request = dataclasses.replace(
            self.request(coverage=coverage, phenotypes={GENE_1: "POOR"}),
            profile=empty)
        with self.assertRaises(AssessmentExecutionError) as caught:
            calculate_assessment(request)
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_RULE_DID_NOT_MATCH")


class TestEvidenceMustResolve(ExecutionCase):

    def test_unresolvable_evidence_is_refused_at_a_full_axis(self):
        """Coverage resolves evidence too, so reaching this means the two
        resolvers disagree - which is corruption, not absence."""
        coverage = self.coverage_for(phenotypes={GENE_1: "POOR",
                                                 GENE_2: "POOR"})
        with self.assertRaises(AssessmentExecutionError) as caught:
            calculate_assessment(self.request(
                coverage=coverage, phenotypes={GENE_1: "POOR", GENE_2: "POOR"},
                resolver=lambda reference: False))
        self.assertEqual(caught.exception.code, "ASSESSMENT_EVIDENCE_MISSING")

    def test_a_full_axis_without_evidence_cannot_even_be_represented(self):
        """The engine's evidence check is the second line, not the first.

        ``AxisCoverage`` refuses to construct a FULL axis citing no evidence,
        so the engine can never be handed one - which is a stronger guarantee
        than checking for it, and worth asserting as the reason the engine's
        own check is only a backstop against a future looser model.
        """
        from pgx.engine.coverage_errors import CoverageEngineError
        with self.assertRaises(CoverageEngineError) as caught:
            self.with_axis({"evidence_references": ()},
                           phenotypes={GENE_1: "POOR", GENE_2: "POOR"})
        self.assertEqual(caught.exception.code,
                         "COVERAGE_FULL_WITHOUT_EVIDENCE")

    def test_the_engine_still_checks_evidence_itself(self):
        """The backstop, exercised directly: a finding is refused when the
        resolver cannot retrieve what the axis cites."""
        coverage = self.coverage_for(phenotypes={GENE_1: "POOR",
                                                 GENE_2: "POOR"})
        axis = [item for medication in coverage.medications
                for item in medication.axes
                if item.status is CoverageStatus.FULL][0]
        with self.assertRaises(AssessmentExecutionError) as caught:
            evaluate_axis_finding(
                axis=axis,
                request=self.request(coverage=coverage,
                                     phenotypes={GENE_1: "POOR",
                                                 GENE_2: "POOR"},
                                     resolver=lambda reference: False))
        self.assertEqual(caught.exception.code, "ASSESSMENT_EVIDENCE_MISSING")

    def test_every_finding_names_resolvable_evidence(self):
        computation = calculate_assessment(
            self.request(phenotypes={GENE_1: "POOR", GENE_2: "POOR"}))
        for finding in computation.findings:
            with self.subTest(gene=finding.gene_canonical_key):
                self.assertTrue(finding.evidence_references)
                for reference in finding.evidence_references:
                    self.assertTrue(
                        self.pinned.evidence_resolver(reference))


class TestOnlyCoveredAxesProduceFindings(ExecutionCase):

    def test_evaluate_axis_finding_refuses_a_non_full_axis(self):
        coverage = self.coverage_for(phenotypes={GENE_1: "POOR"})
        axis = [item for medication in coverage.medications
                for item in medication.axes
                if item.status is not CoverageStatus.FULL][0]
        with self.assertRaises(AssessmentExecutionError) as caught:
            evaluate_axis_finding(
                axis=axis,
                request=self.request(phenotypes={GENE_1: "POOR"}))
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_RULE_NOT_EXECUTABLE")

    def test_an_insufficient_axis_produces_nothing(self):
        computation = calculate_assessment(
            self.request(phenotypes={GENE_1: "POOR"}))
        genes = {finding.gene_canonical_key
                 for finding in computation.findings}
        self.assertNotIn(GENE_2, genes)
        self.assertNotIn(GENE_3, genes)

    def test_a_conflicted_axis_produces_nothing_and_is_counted(self):
        from pgx.engine.coverage import CoverageRequest, evaluate_coverage
        assessment_input = self.world.input(medications=[DRUG_1],
                                            phenotypes={GENE_1: "POOR",
                                                        GENE_2: "POOR"})
        coverage = evaluate_coverage(CoverageRequest(
            profile=assessment_input.profile,
            medications=assessment_input.medications,
            manifest=self.pinned.coverage_manifest,
            frozen_ruleset=self.pinned.frozen_ruleset,
            drug_catalogue=self.pinned.drug_catalogue,
            evidence_resolver=self.pinned.evidence_resolver,
            conflicts=(synthetic_conflict(),)))
        computation = calculate_assessment(dataclasses.replace(
            self.request(phenotypes={GENE_1: "POOR", GENE_2: "POOR"}),
            coverage=coverage))
        genes = {finding.gene_canonical_key
                 for finding in computation.findings}
        self.assertNotIn(GENE_1, genes)
        self.assertIn(GENE_2, genes)
        self.assertEqual(computation.medications[0].conflicted_axis_count, 1)

    def test_an_unsupported_drug_produces_nothing(self):
        computation = calculate_assessment(
            self.request(medications=[UNKNOWN_DRUG],
                         phenotypes={GENE_1: "POOR"}))
        self.assertEqual(computation.findings, ())


class TestTheRequestContract(ExecutionCase):

    def test_coverage_must_be_a_wp13_result(self):
        with self.assertRaises(AssessmentInputError) as caught:
            CalculationRequest(profile=None, coverage={"status": "FULL"},
                               frozen_ruleset=self.world.frozen,
                               provenance=self.pinned.provenance)
        self.assertEqual(caught.exception.code, "ASSESSMENT_INPUT_INVALID")

    def test_a_frozen_ruleset_is_required(self):
        with self.assertRaises(AssessmentInputError) as caught:
            CalculationRequest(
                profile=self.world.input().profile,
                coverage=self.coverage_for(phenotypes={GENE_1: "POOR"}),
                frozen_ruleset=None, provenance=self.pinned.provenance)
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_RULESET_ARTIFACT_INVALID")

    def test_provenance_is_required(self):
        with self.assertRaises(AssessmentInputError) as caught:
            CalculationRequest(
                profile=self.world.input().profile,
                coverage=self.coverage_for(phenotypes={GENE_1: "POOR"}),
                frozen_ruleset=self.world.frozen, provenance=None)
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_VERSION_MISMATCH")

    def test_calculate_assessment_refuses_anything_but_a_request(self):
        with self.assertRaises(AssessmentInputError) as caught:
            calculate_assessment({"coverage": None})
        self.assertEqual(caught.exception.code, "ASSESSMENT_INPUT_INVALID")

    def test_the_engine_does_not_recompute_coverage(self):
        """It consumes WP-13's answer. A second coverage calculation here
        would be a second place for coverage to mean something."""
        from pgx.engine import risk
        import inspect
        source = inspect.getsource(risk)
        self.assertNotIn("evaluate_coverage", source)
        self.assertNotIn("CoverageRequest", source)


if __name__ == "__main__":
    unittest.main()
