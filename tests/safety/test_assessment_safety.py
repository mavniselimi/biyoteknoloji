# -*- coding: utf-8 -*-
"""The coverage/attention safety matrix (sections D and F).

This is the file that would have prevented `LEGACY-BUG-002`. The legacy engine
reported "we did not look" as *"Düşük / uyarı yok"* - low, no warning - and
every test here exists to make that unreachable.

The central assertion is a property rather than an example: **no absence path
yields `LOW` or `NO_ACTIVE_ATTENTION`**. It is checked over every coverage
status, every coverage reason code, and every combination of them the engine
can actually produce - so a new reason code, or a new path to an old one, is
held to the rule without anybody remembering to add a case.

`NO_ACTIVE_ATTENTION` is reachable from exactly one place: `FULL` coverage with
every expected axis evaluated and no rule producing a level. Everything else
terminates in `NOT_ASSESSED`, which is not a low level - it is not a level at
all, and is excluded from every maximum.
"""

from __future__ import annotations

import dataclasses
import unittest

from pgx.domain.enums import (AttentionLevel, CoverageReasonCode,
                              CoverageStatus)
from pgx.engine.risk import calculate_assessment
from pgx.engine.risk_errors import AssessmentEngineError
from pgx.engine.risk_models import (ATTENTION_AGGREGATION_TABLE,
                                    ATTENTION_PRECEDENCE, CalculatedFinding,
                                    MedicationAssessment, aggregate_attention,
                                    attention_table)
from tests.fixtures.wp13.synthetic import (DRUG_1, DRUG_2, GENE_1, GENE_2,
                                           GENE_3, UNKNOWN_DRUG,
                                           synthetic_conflict)
from tests.unit.application._assessment_support import SyntheticAssessmentWorld

REASSURING = (AttentionLevel.LOW, AttentionLevel.NO_ACTIVE_ATTENTION)


class SafetyMatrixCase(unittest.TestCase):
    """Every coverage situation the engine can reach, built once."""

    @classmethod
    def setUpClass(cls):
        cls.partial = SyntheticAssessmentWorld(expected_extra_gene=True,
                                               persist=False)
        cls.complete = SyntheticAssessmentWorld(expected_extra_gene=False,
                                                persist=False)
        #: Rules carrying NO_ACTIVE_ATTENTION, so the reassuring answer can be
        #: reached the only way it legitimately can: a governed rule that
        #: looked and said so.
        cls.quiet = SyntheticAssessmentWorld(
            expected_extra_gene=False, persist=False,
            attention_levels=(AttentionLevel.NO_ACTIVE_ATTENTION,
                              AttentionLevel.NO_ACTIVE_ATTENTION))
        cls.mixed = SyntheticAssessmentWorld(
            expected_extra_gene=False, persist=False,
            attention_levels=(AttentionLevel.LOW, AttentionLevel.HIGH))
        cls.cases = {
            # coverage FULL with every axis covered and matched
            "full_with_findings": cls.complete.dry_run(
                medications=[DRUG_1],
                phenotypes={GENE_1: "POOR", GENE_2: "POOR"}),
            # coverage FULL, every axis evaluated, every rule said so
            "full_no_active_attention": cls.quiet.dry_run(
                medications=[DRUG_1],
                phenotypes={GENE_1: "POOR", GENE_2: "POOR"}),
            "full_mixed_levels": cls.mixed.dry_run(
                medications=[DRUG_1],
                phenotypes={GENE_1: "POOR", GENE_2: "POOR"}),
            "partial_with_finding": cls.partial.dry_run(
                medications=[DRUG_1],
                phenotypes={GENE_1: "POOR", GENE_2: "POOR", GENE_3: "POOR"}),
            "insufficient": cls.partial.dry_run(
                medications=[DRUG_2], phenotypes={GENE_1: "POOR"}),
            "unsupported_drug": cls.partial.dry_run(
                medications=[UNKNOWN_DRUG], phenotypes={GENE_1: "POOR"}),
            "unsupported_phenotype": cls.complete.dry_run(
                medications=[DRUG_1],
                phenotypes={GENE_1: "poor metabolizer", GENE_2: "*1/*2"}),
            "phenotype_not_provided": cls.complete.dry_run(
                medications=[DRUG_1], phenotypes={}),
        }

    @classmethod
    def tearDownClass(cls):
        cls.partial.close()
        cls.complete.close()
        cls.quiet.close()
        cls.mixed.close()

    def levels(self, computation):
        yield "overall", computation.overall_attention, \
            computation.overall_coverage
        for medication in computation.medications:
            yield ("medication:%s" % medication.drug_canonical_key,
                   medication.attention_level, medication.coverage_status)


class TestTheFullCoverageCases(SafetyMatrixCase):

    def test_full_coverage_with_a_matched_rule_reports_the_level(self):
        computation = self.cases["full_with_findings"]
        self.assertIs(computation.overall_coverage, CoverageStatus.FULL)
        self.assertIn(computation.overall_attention,
                      (AttentionLevel.LOW, AttentionLevel.MEDIUM,
                       AttentionLevel.HIGH,
                       AttentionLevel.NO_ACTIVE_ATTENTION))
        self.assertTrue(computation.findings)

    def test_no_active_attention_comes_from_a_rule_that_said_so(self):
        """The one path to a reassuring answer, and it is worth being precise
        about which path it is.

        Under coverage-first execution a FULL axis always carries a validated
        rule that matched, and a matched rule always has a governed outcome -
        so ``NO_ACTIVE_ATTENTION`` here is a level a curator approved, not the
        residue of nothing having happened. The engine never reaches "FULL
        coverage and silence"; it reaches "FULL coverage and a rule that
        looked".
        """
        computation = self.cases["full_no_active_attention"]
        self.assertIs(computation.overall_coverage, CoverageStatus.FULL)
        self.assertIs(computation.overall_attention,
                      AttentionLevel.NO_ACTIVE_ATTENTION)
        self.assertTrue(computation.findings)
        for finding in computation.findings:
            with self.subTest(gene=finding.gene_canonical_key):
                self.assertIs(finding.attention_level,
                              AttentionLevel.NO_ACTIVE_ATTENTION)
                self.assertTrue(finding.rationale_reference)
                self.assertTrue(finding.evidence_references)

    def test_the_maximum_is_taken_over_independent_covered_axes(self):
        computation = self.cases["full_mixed_levels"]
        levels = {finding.attention_level
                  for finding in computation.findings}
        self.assertEqual(levels, {AttentionLevel.LOW, AttentionLevel.HIGH})
        self.assertIs(computation.overall_attention, AttentionLevel.HIGH)

    def test_low_arises_only_from_an_applicable_validated_rule(self):
        """It is a calculated level, never a default and never a downgrade."""
        world = SyntheticAssessmentWorld(
            expected_extra_gene=False, persist=False,
            attention_levels=(AttentionLevel.LOW, AttentionLevel.LOW))
        self.addCleanup(world.close)
        computation = world.dry_run(medications=[DRUG_1],
                                    phenotypes={GENE_1: "POOR",
                                                GENE_2: "POOR"})
        self.assertIs(computation.overall_attention, AttentionLevel.LOW)
        for finding in computation.findings:
            with self.subTest(gene=finding.gene_canonical_key):
                self.assertIs(finding.attention_level, AttentionLevel.LOW)
                self.assertTrue(finding.rule_id)

    def test_every_calculated_level_is_reachable_from_full_coverage(self):
        """FULL + each of NO_ACTIVE_ATTENTION / LOW / MEDIUM / HIGH, built
        through the aggregator rather than hoped for from a fixture."""
        for level in ATTENTION_PRECEDENCE:
            with self.subTest(level=level.value):
                self.assertIs(
                    aggregate_attention([level], coverage=CoverageStatus.FULL),
                    level)


class TestEveryAbsencePathIsNotAssessed(SafetyMatrixCase):
    """SAFETY-INV-001, as a property over every case."""

    ABSENCE_CASES = ("insufficient", "unsupported_drug",
                     "unsupported_phenotype", "phenotype_not_provided")

    def test_no_absence_case_reports_a_reassuring_level(self):
        for name in self.ABSENCE_CASES:
            computation = self.cases[name]
            for where, level, coverage in self.levels(computation):
                with self.subTest(case=name, level=where):
                    self.assertNotIn(
                        level, REASSURING,
                        "%s reported %s with coverage %s"
                        % (where, level.value, coverage.value))

    def test_every_absence_case_is_not_assessed(self):
        for name in self.ABSENCE_CASES:
            with self.subTest(case=name):
                self.assertIs(self.cases[name].overall_attention,
                              AttentionLevel.NOT_ASSESSED)

    def test_an_insufficient_medication_is_not_assessed(self):
        self.assertIs(self.cases["insufficient"].overall_coverage,
                      CoverageStatus.INSUFFICIENT)
        self.assertIs(self.cases["insufficient"].overall_attention,
                      AttentionLevel.NOT_ASSESSED)

    def test_an_unsupported_drug_is_not_assessed(self):
        self.assertIs(self.cases["unsupported_drug"].overall_coverage,
                      CoverageStatus.UNSUPPORTED_DRUG)
        self.assertIs(self.cases["unsupported_drug"].overall_attention,
                      AttentionLevel.NOT_ASSESSED)

    def test_an_unsupported_phenotype_is_not_assessed(self):
        self.assertIs(self.cases["unsupported_phenotype"].overall_coverage,
                      CoverageStatus.UNSUPPORTED_PHENOTYPE)
        self.assertIs(self.cases["unsupported_phenotype"].overall_attention,
                      AttentionLevel.NOT_ASSESSED)

    def test_partial_coverage_without_a_finding_is_not_assessed(self):
        """Asserted at the aggregator, because the engine cannot reach it.

        Coverage-first execution makes ``PARTIAL`` imply at least one FULL
        axis, and a FULL axis always carries a validated rule that matched and
        therefore a governed outcome - so a PARTIAL medication always has a
        finding. The branch is a backstop against a future rule vocabulary or
        conflict overlay that produced a covered axis with no level, and it is
        tested directly rather than left unexercised because no fixture
        currently reaches it.
        """
        self.assertIs(aggregate_attention([], coverage=CoverageStatus.PARTIAL),
                      AttentionLevel.NOT_ASSESSED)

    def test_partial_coverage_always_carries_a_finding_today(self):
        """The structural reason the case above is unreachable, stated so a
        reader knows the backstop is a backstop and not dead code."""
        computation = self.cases["partial_with_finding"]
        self.assertIs(computation.overall_coverage, CoverageStatus.PARTIAL)
        self.assertTrue(computation.findings)

    def test_no_coverage_status_but_full_can_reach_a_reassuring_level(self):
        """The property, over every status rather than over the cases that
        happen to exist."""
        for status in CoverageStatus:
            with self.subTest(coverage=status.value):
                result = aggregate_attention([], coverage=status)
                if status is CoverageStatus.FULL:
                    self.assertIs(result, AttentionLevel.NO_ACTIVE_ATTENTION)
                else:
                    self.assertIs(result, AttentionLevel.NOT_ASSESSED)

    def test_no_coverage_reason_code_permits_a_reassuring_level(self):
        """Over every reason code the domain declares. A reason code exists
        because something was not evaluated; none of them may accompany a
        level that says everything was."""
        for code in CoverageReasonCode:
            for status in CoverageStatus:
                if status is CoverageStatus.FULL:
                    continue
                with self.subTest(reason=code.value, coverage=status.value):
                    with self.assertRaises(AssessmentEngineError):
                        MedicationAssessment(
                            drug_canonical_key=DRUG_1,
                            requested_value=DRUG_1,
                            attention_level=AttentionLevel.NO_ACTIVE_ATTENTION,
                            coverage_status=status,
                            coverage_reason_codes=(code,))


class TestPartialCoveragePreservesAFinding(SafetyMatrixCase):

    def test_a_valid_finding_survives_beside_an_uncovered_axis(self):
        computation = self.cases["partial_with_finding"]
        self.assertIs(computation.overall_coverage, CoverageStatus.PARTIAL)
        self.assertTrue(computation.findings)
        self.assertIsNot(computation.overall_attention,
                         AttentionLevel.NOT_ASSESSED)

    def test_the_coverage_stays_partial_beside_the_calculated_level(self):
        """Coverage is not lowered by a finding and attention is not lowered
        by incomplete coverage. Both facts are reported, and neither
        summarises the other."""
        medication = self.cases["partial_with_finding"].medications[0]
        self.assertIs(medication.coverage_status, CoverageStatus.PARTIAL)
        self.assertIn(CoverageReasonCode.SOME_AXES_NOT_COVERED,
                      medication.coverage_reason_codes)
        self.assertIsNot(medication.attention_level,
                         AttentionLevel.NOT_ASSESSED)

    def test_a_conflicted_axis_keeps_an_independent_finding(self):
        from pgx.engine.coverage import CoverageRequest, evaluate_coverage
        from pgx.engine.risk import CalculationRequest
        pinned = self.partial.resolver.resolve()
        assessment_input = self.partial.input(
            medications=[DRUG_1], phenotypes={GENE_1: "POOR", GENE_2: "POOR"})
        coverage = evaluate_coverage(CoverageRequest(
            profile=assessment_input.profile,
            medications=assessment_input.medications,
            manifest=pinned.coverage_manifest,
            frozen_ruleset=pinned.frozen_ruleset,
            drug_catalogue=pinned.drug_catalogue,
            evidence_resolver=pinned.evidence_resolver,
            conflicts=(synthetic_conflict(),)))
        computation = calculate_assessment(CalculationRequest(
            profile=assessment_input.profile, coverage=coverage,
            frozen_ruleset=pinned.frozen_ruleset,
            provenance=pinned.provenance,
            evidence_resolver=pinned.evidence_resolver))
        self.assertIs(computation.overall_coverage,
                      CoverageStatus.SOURCE_CONFLICT)
        self.assertEqual(len(computation.findings), 1)
        self.assertEqual(computation.findings[0].gene_canonical_key, GENE_2)
        self.assertIsNot(computation.overall_attention,
                         AttentionLevel.NOT_ASSESSED)

    def test_a_conflict_with_no_independent_finding_is_not_assessed(self):
        from pgx.engine.coverage import CoverageRequest, evaluate_coverage
        from pgx.engine.risk import CalculationRequest
        pinned = self.complete.resolver.resolve()
        assessment_input = self.complete.input(
            medications=[DRUG_1], phenotypes={GENE_1: "POOR", GENE_2: "POOR"})
        coverage = evaluate_coverage(CoverageRequest(
            profile=assessment_input.profile,
            medications=assessment_input.medications,
            manifest=pinned.coverage_manifest,
            frozen_ruleset=pinned.frozen_ruleset,
            drug_catalogue=pinned.drug_catalogue,
            evidence_resolver=pinned.evidence_resolver,
            conflicts=(synthetic_conflict(gene=GENE_1),
                       synthetic_conflict(conflict_id="TEST-CONFLICT-2",
                                          gene=GENE_2))))
        computation = calculate_assessment(CalculationRequest(
            profile=assessment_input.profile, coverage=coverage,
            frozen_ruleset=pinned.frozen_ruleset,
            provenance=pinned.provenance,
            evidence_resolver=pinned.evidence_resolver))
        self.assertEqual(computation.findings, ())
        self.assertIs(computation.overall_attention,
                      AttentionLevel.NOT_ASSESSED)
        self.assertIs(computation.overall_coverage,
                      CoverageStatus.SOURCE_CONFLICT)

    def test_no_attention_is_manufactured_from_a_conflict_signal(self):
        """A WP-13 conflict signal carries no governed outcome, so there is
        nothing in it to calculate a level from."""
        conflict = synthetic_conflict()
        for forbidden in ("attention", "attention_level", "outcome", "level"):
            with self.subTest(field=forbidden):
                self.assertFalse(hasattr(conflict, forbidden))


class TestTheAggregationTable(SafetyMatrixCase):

    def test_not_assessed_is_excluded_from_the_precedence(self):
        self.assertNotIn(AttentionLevel.NOT_ASSESSED, ATTENTION_PRECEDENCE)
        self.assertEqual(attention_table()["excluded_from_maximum"],
                         [AttentionLevel.NOT_ASSESSED.value])

    def test_the_precedence_is_written_out_not_derived(self):
        self.assertEqual(
            ATTENTION_PRECEDENCE,
            (AttentionLevel.HIGH, AttentionLevel.MEDIUM, AttentionLevel.LOW,
             AttentionLevel.NO_ACTIVE_ATTENTION))

    def test_passing_not_assessed_into_an_aggregation_is_refused(self):
        """It is not a magnitude. Every possible position for it in a maximum
        is wrong, so it may not enter one."""
        with self.assertRaises(AssessmentEngineError) as caught:
            aggregate_attention([AttentionLevel.NOT_ASSESSED],
                                coverage=CoverageStatus.FULL)
        self.assertEqual(caught.exception.code, "ASSESSMENT_INPUT_INVALID")

    def test_every_row_of_the_table_is_reachable(self):
        observed = {
            "calculated_findings_present": aggregate_attention(
                [AttentionLevel.MEDIUM], coverage=CoverageStatus.PARTIAL),
            "no_finding_full_coverage": aggregate_attention(
                [], coverage=CoverageStatus.FULL),
            "no_finding_partial_coverage": aggregate_attention(
                [], coverage=CoverageStatus.PARTIAL),
            "no_finding_insufficient": aggregate_attention(
                [], coverage=CoverageStatus.INSUFFICIENT),
            "no_finding_unsupported_drug": aggregate_attention(
                [], coverage=CoverageStatus.UNSUPPORTED_DRUG),
            "no_finding_unsupported_phenotype": aggregate_attention(
                [], coverage=CoverageStatus.UNSUPPORTED_PHENOTYPE),
            "no_finding_source_conflict": aggregate_attention(
                [], coverage=CoverageStatus.SOURCE_CONFLICT),
        }
        rows = {row["case"]: row for row in ATTENTION_AGGREGATION_TABLE}
        self.assertEqual(set(observed), set(rows))
        for case, level in observed.items():
            with self.subTest(case=case):
                if rows[case]["result"] in [item.value
                                            for item in AttentionLevel]:
                    self.assertEqual(level.value, rows[case]["result"])

    def test_a_maximum_is_selected_over_independent_findings(self):
        self.assertIs(
            aggregate_attention(
                [AttentionLevel.LOW, AttentionLevel.HIGH,
                 AttentionLevel.MEDIUM], coverage=CoverageStatus.FULL),
            AttentionLevel.HIGH)

    def test_the_order_of_the_levels_supplied_does_not_matter(self):
        levels = [AttentionLevel.LOW, AttentionLevel.MEDIUM,
                  AttentionLevel.HIGH]
        for coverage in CoverageStatus:
            with self.subTest(coverage=coverage.value):
                self.assertIs(
                    aggregate_attention(levels, coverage=coverage),
                    aggregate_attention(list(reversed(levels)),
                                        coverage=coverage))

    def test_the_attention_enum_has_acquired_no_ordering(self):
        with self.assertRaises(TypeError):
            _ = AttentionLevel.LOW < AttentionLevel.HIGH
        for level in AttentionLevel:
            with self.subTest(level=level.value):
                self.assertFalse(hasattr(level, "severity"))
                self.assertFalse(hasattr(level, "rank"))
                self.assertFalse(hasattr(level, "score"))

    def test_no_numeric_score_appears_anywhere_in_a_result(self):
        for name, computation in self.cases.items():
            payload = computation.to_json()
            for medication in payload["medications"]:
                with self.subTest(case=name):
                    for key, value in medication.items():
                        if isinstance(value, (int, float)) and \
                                not isinstance(value, bool):
                            self.assertIn(key, ("axis_count", "finding_count",
                                                "conflicted_axis_count"))


class TestFindingTraceability(SafetyMatrixCase):
    """Section F. SAFETY-INV-006 over every finding the engine can produce."""

    def all_findings(self):
        for name, computation in self.cases.items():
            for finding in computation.findings:
                yield name, finding

    def test_every_finding_names_its_rule_completely(self):
        seen = 0
        for name, finding in self.all_findings():
            seen += 1
            with self.subTest(case=name, gene=finding.gene_canonical_key):
                self.assertTrue(finding.rule_id)
                self.assertTrue(finding.rule_family_id)
                self.assertGreaterEqual(finding.rule_version, 1)
                self.assertTrue(
                    finding.rule_content_hash.startswith("sha256:"))
        self.assertGreater(seen, 0)

    def test_every_finding_names_evidence(self):
        for name, finding in self.all_findings():
            with self.subTest(case=name, gene=finding.gene_canonical_key):
                self.assertTrue(finding.evidence_references)

    def test_every_finding_names_a_rationale_reference(self):
        for name, finding in self.all_findings():
            with self.subTest(case=name, gene=finding.gene_canonical_key):
                self.assertTrue(finding.rationale_reference.strip())

    def test_every_finding_names_the_artifacts_it_was_computed_against(self):
        for name, finding in self.all_findings():
            with self.subTest(case=name, gene=finding.gene_canonical_key):
                for field in ("ruleset_public_id", "ruleset_content_hash",
                              "dataset_public_id",
                              "canonical_build_content_hash",
                              "coverage_manifest_hash"):
                    self.assertTrue(getattr(finding, field))

    def test_no_finding_invents_a_scientific_code(self):
        for name, finding in self.all_findings():
            with self.subTest(case=name, gene=finding.gene_canonical_key):
                self.assertIsNone(finding.effect_code)
                self.assertIsNone(finding.explanation_code)

    def test_no_finding_is_not_assessed(self):
        for name, finding in self.all_findings():
            with self.subTest(case=name, gene=finding.gene_canonical_key):
                self.assertIsNot(finding.attention_level,
                                 AttentionLevel.NOT_ASSESSED)

    def test_the_model_refuses_a_not_assessed_finding(self):
        from pgx.domain.enums import Phenotype
        with self.assertRaises(AssessmentEngineError) as caught:
            CalculatedFinding(
                drug_canonical_key=DRUG_1, gene_canonical_key=GENE_1,
                phenotype=Phenotype.POOR,
                attention_level=AttentionLevel.NOT_ASSESSED,
                rule_id="r", rule_family_id="f", rule_version=1,
                rule_content_hash="sha256:" + "0" * 64,
                rationale_reference="ref", evidence_references=("e",),
                curation_revision_id="rev",
                curation_revision_hash="sha256:" + "0" * 64,
                ruleset_public_id="rs", ruleset_content_hash="sha256:" + "0" * 64,
                dataset_public_id="ds",
                canonical_build_content_hash="sha256:" + "0" * 64,
                coverage_manifest_hash="sha256:" + "0" * 64)
        self.assertEqual(caught.exception.code, "ASSESSMENT_INPUT_INVALID")

    def test_the_model_refuses_a_finding_without_evidence(self):
        from pgx.domain.enums import Phenotype
        with self.assertRaises(AssessmentEngineError) as caught:
            CalculatedFinding(
                drug_canonical_key=DRUG_1, gene_canonical_key=GENE_1,
                phenotype=Phenotype.POOR,
                attention_level=AttentionLevel.HIGH,
                rule_id="r", rule_family_id="f", rule_version=1,
                rule_content_hash="sha256:" + "0" * 64,
                rationale_reference="ref", evidence_references=(),
                curation_revision_id="rev",
                curation_revision_hash="sha256:" + "0" * 64,
                ruleset_public_id="rs", ruleset_content_hash="sha256:" + "0" * 64,
                dataset_public_id="ds",
                canonical_build_content_hash="sha256:" + "0" * 64,
                coverage_manifest_hash="sha256:" + "0" * 64)
        self.assertEqual(caught.exception.code, "ASSESSMENT_EVIDENCE_MISSING")


class TestNoResultCarriesAProhibitedField(SafetyMatrixCase):

    FORBIDDEN = ("dose", "dosage", "recommendation", "recommend", "preferred",
                 "safer", "suitability", "treatment", "alternative", "rank",
                 "ranking", "score", "diagnosis", "prescription", "advice",
                 "report_text", "narrative", "prose")

    def keys_of(self, payload, found=None):
        found = set() if found is None else found
        if isinstance(payload, dict):
            for key, value in payload.items():
                found.add(key)
                self.keys_of(value, found)
        elif isinstance(payload, (list, tuple)):
            for item in payload:
                self.keys_of(item, found)
        return found

    def test_no_computation_carries_a_prohibited_key(self):
        for name, computation in self.cases.items():
            for key in self.keys_of(computation.to_json()):
                for forbidden in self.FORBIDDEN:
                    with self.subTest(case=name, key=key, field=forbidden):
                        self.assertNotIn(forbidden, key.lower())

    def test_no_wp14_dataclass_declares_a_prohibited_field(self):
        import importlib
        for module_name in ("pgx.engine.risk", "pgx.engine.risk_models",
                            "pgx.application.assessment_models"):
            module = importlib.import_module(module_name)
            for attribute_name in dir(module):
                attribute = getattr(module, attribute_name)
                if not dataclasses.is_dataclass(attribute):
                    continue
                if getattr(attribute, "__module__", "") != module.__name__:
                    continue
                for field in dataclasses.fields(attribute):
                    for forbidden in self.FORBIDDEN:
                        with self.subTest(model=attribute_name,
                                          field=field.name,
                                          forbidden=forbidden):
                            self.assertNotIn(forbidden, field.name.lower())

    def test_the_computation_says_what_it_is_not(self):
        note = self.cases["full_with_findings"].note.lower()
        self.assertIn("not a report", note)
        self.assertIn("not a recommendation", note)
        self.assertIn("not a statement about any medicine", note)


if __name__ == "__main__":
    unittest.main()
