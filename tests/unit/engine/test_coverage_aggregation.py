# -*- coding: utf-8 -*-
"""Medication and overall aggregation (sections C and D).

Aggregation is where a careful per-axis answer is most easily thrown away. The
property every test here defends is that combining results loses nothing: a
covered axis is still visible inside a PARTIAL medication, an uncovered one is
still visible inside a PARTIAL result, and an unresolved disagreement is still
visible at the top.

``CoverageStatus`` has no ordering and must never acquire one, so the tables
are checked behaviourally as well as structurally. Several tests below would
pass under ``max()`` over the enum's declaration order; the ones that matter
are the ones that would not, and they are marked.
"""

from __future__ import annotations

import unittest

from pgx.domain.enums import CoverageReasonCode, CoverageStatus, Phenotype
from pgx.engine.coverage import (MEDICATION_DECISION_TABLE,
                                 OVERALL_DECISION_TABLE, aggregate_medication,
                                 aggregate_overall, evaluate_coverage,
                                 resolve_medication)
from pgx.engine.coverage_errors import CoverageInputError
from pgx.engine.coverage_models import (REASON_CODE_ORDER, AxisCoverage,
                                        MedicationCoverage,
                                        MedicationReference, order_reasons)
from tests.fixtures.wp13.synthetic import (DRUG_1, DRUG_2, GENE_1, GENE_2,
                                           GENE_3, UNKNOWN_DRUG,
                                           synthetic_conflict)
from tests.unit.engine._coverage_support import SyntheticWorld

FULL = CoverageStatus.FULL
PARTIAL = CoverageStatus.PARTIAL
INSUFFICIENT = CoverageStatus.INSUFFICIENT
UNSUPPORTED_DRUG = CoverageStatus.UNSUPPORTED_DRUG
UNSUPPORTED_PHENOTYPE = CoverageStatus.UNSUPPORTED_PHENOTYPE
SOURCE_CONFLICT = CoverageStatus.SOURCE_CONFLICT

SOME_AXES = CoverageReasonCode.SOME_AXES_NOT_COVERED
NO_RULE = CoverageReasonCode.NO_VALIDATED_RULE_FOR_AXIS
NOT_PROVIDED = CoverageReasonCode.PHENOTYPE_NOT_PROVIDED
NOT_SUPPORTED = CoverageReasonCode.PHENOTYPE_NOT_SUPPORTED
NOT_IN_DATASET = CoverageReasonCode.DRUG_NOT_IN_CANONICAL_DATASET
CONFLICT = CoverageReasonCode.VALIDATED_RULES_CONFLICT
MISMATCH = CoverageReasonCode.DATASET_RULESET_MISMATCH


def medication(status, *reasons, key=DRUG_1, axes=()):
    """A ``MedicationCoverage`` assembled directly, for the overall table."""
    if status is FULL and not axes:
        axes = (AxisCoverage(drug_canonical_key=key,
                             gene_canonical_key=GENE_1, status=FULL,
                             observed_phenotype=Phenotype.POOR,
                             rule_references=({"rule_id": "r"},),
                             evidence_references=("e",)),)
    return MedicationCoverage(
        medication=MedicationReference(requested_value=key, state="RECOGNIZED",
                                       drug_canonical_key=key),
        status=status, reason_codes=reasons, axes=axes)


class AggregationCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.world = SyntheticWorld(expected_extra_gene=True)
        #: Expected scope exactly equal to the genes with rules. The validator
        #: reports that shape for review (it is what copying structural axes
        #: produces); the engine still evaluates it, and it is the only way to
        #: reach an all-axes-FULL medication in this fixture.
        cls.complete = SyntheticWorld(expected_extra_gene=False)

    @classmethod
    def tearDownClass(cls):
        cls.world.close()
        cls.complete.close()

    def medication_for(self, world=None, drug=DRUG_1, **kwargs):
        world = world or self.world
        request = world.request(**kwargs)
        return aggregate_medication(
            request=request,
            medication=resolve_medication(drug, request.drug_catalogue))

    def assertCoverage(self, result, status, *reasons):
        self.assertEqual(result.status, status)
        for code in reasons:
            self.assertIn(code, result.reason_codes)


class TestMedicationAggregation(AggregationCase):

    def test_a_drug_outside_the_dataset_is_unsupported(self):
        result = self.medication_for(drug=UNKNOWN_DRUG,
                                     medications=[UNKNOWN_DRUG],
                                     phenotypes={GENE_1: "POOR"})
        self.assertCoverage(result, UNSUPPORTED_DRUG, NOT_IN_DATASET)

    def test_no_axis_is_fabricated_for_a_drug_the_dataset_lacks(self):
        result = self.medication_for(drug=UNKNOWN_DRUG,
                                     medications=[UNKNOWN_DRUG],
                                     phenotypes={GENE_1: "POOR"})
        self.assertEqual(result.axes, ())

    def test_an_unreadable_reference_is_unsupported_not_ignored(self):
        result = self.medication_for(drug="Plavix", medications=["Plavix"],
                                     phenotypes={GENE_1: "POOR"})
        self.assertCoverage(result, UNSUPPORTED_DRUG, NOT_IN_DATASET)

    def test_a_recognised_drug_with_no_declared_scope_is_insufficient(self):
        """The codeine case: the dataset has the chemical and nobody has
        declared what a complete assessment of it would require. Recognition
        is not coverage (architecture.md 6.2)."""
        result = self.medication_for(drug=DRUG_2, medications=[DRUG_2],
                                     phenotypes={GENE_1: "POOR"})
        self.assertCoverage(result, INSUFFICIENT, NO_RULE)
        self.assertEqual(result.axes, ())

    def test_every_expected_axis_is_full_gives_full(self):
        result = self.medication_for(world=self.complete, medications=[DRUG_1],
                                     phenotypes={GENE_1: "POOR",
                                                 GENE_2: "POOR"})
        self.assertEqual(result.status, FULL)
        self.assertEqual(result.reason_codes, ())
        self.assertEqual(len(result.axes), 2)

    def test_some_axes_full_gives_partial_with_some_axes_not_covered(self):
        result = self.medication_for(medications=[DRUG_1],
                                     phenotypes={GENE_1: "POOR",
                                                 GENE_2: "POOR"})
        self.assertCoverage(result, PARTIAL, SOME_AXES)
        self.assertEqual(len(result.axes), 3)

    def test_a_partial_medication_keeps_both_kinds_of_axis(self):
        """A PARTIAL that dropped its covered axes would be indistinguishable
        from an insufficient one; one that dropped its uncovered axes would
        look complete."""
        result = self.medication_for(medications=[DRUG_1],
                                     phenotypes={GENE_1: "POOR",
                                                 GENE_2: "POOR",
                                                 GENE_3: "POOR"})
        statuses = [axis.status for axis in result.axes]
        self.assertIn(FULL, statuses)
        self.assertIn(INSUFFICIENT, statuses)
        self.assertEqual(result.status, PARTIAL)

    def test_a_partial_medication_preserves_the_underlying_axis_reasons(self):
        result = self.medication_for(medications=[DRUG_1],
                                     phenotypes={GENE_1: "POOR",
                                                 GENE_2: "POOR",
                                                 GENE_3: "POOR"})
        self.assertIn(SOME_AXES, result.reason_codes)
        self.assertIn(NO_RULE, result.reason_codes)

    def test_every_failure_being_an_unusable_phenotype_keeps_that_status(self):
        result = self.medication_for(
            world=self.complete, medications=[DRUG_1],
            phenotypes={GENE_1: "poor metabolizer", GENE_2: "*1/*2"})
        self.assertCoverage(result, UNSUPPORTED_PHENOTYPE, NOT_SUPPORTED)

    def test_mixed_failures_with_nothing_covered_are_insufficient(self):
        result = self.medication_for(
            world=self.complete, medications=[DRUG_1],
            phenotypes={GENE_1: "poor metabolizer"})
        self.assertEqual(result.status, INSUFFICIENT)
        self.assertIn(NOT_SUPPORTED, result.reason_codes)
        self.assertIn(NOT_PROVIDED, result.reason_codes)

    def test_any_conflicting_axis_makes_the_medication_conflicting(self):
        result = self.medication_for(medications=[DRUG_1],
                                     phenotypes={GENE_1: "POOR",
                                                 GENE_2: "POOR"},
                                     conflicts=(synthetic_conflict(),))
        self.assertCoverage(result, SOURCE_CONFLICT, CONFLICT)

    def test_a_conflicting_medication_still_carries_its_other_reasons(self):
        """Conflict preservation, not conflict replacement."""
        result = self.medication_for(medications=[DRUG_1],
                                     phenotypes={GENE_1: "POOR",
                                                 GENE_2: "POOR"},
                                     conflicts=(synthetic_conflict(),))
        self.assertIn(CONFLICT, result.reason_codes)
        self.assertIn(NOT_PROVIDED, result.reason_codes)
        self.assertEqual(len(result.axes), 3)

    def test_a_boundary_mismatch_reaches_the_medication_level(self):
        import dataclasses
        result = self.medication_for(
            medications=[DRUG_1], phenotypes={GENE_1: "POOR"},
            manifest=dataclasses.replace(
                self.world.manifest,
                ruleset_content_hash="sha256:" + "a" * 64))
        self.assertCoverage(result, INSUFFICIENT, MISMATCH)

    def test_the_axes_are_ordered_deterministically(self):
        result = self.medication_for(medications=[DRUG_1],
                                     phenotypes={GENE_3: "POOR",
                                                 GENE_1: "POOR",
                                                 GENE_2: "POOR"})
        keys = [axis.axis_key for axis in result.axes]
        self.assertEqual(keys, sorted(keys))

    def test_the_result_hashes_the_same_however_the_input_was_ordered(self):
        one = self.medication_for(medications=[DRUG_1],
                                  phenotypes={GENE_1: "POOR", GENE_2: "POOR",
                                              GENE_3: "POOR"})
        two = self.medication_for(medications=[DRUG_1],
                                  phenotypes={GENE_3: "POOR", GENE_2: "POOR",
                                              GENE_1: "POOR"})
        self.assertEqual(one.content_hash(), two.content_hash())

    def test_every_declared_medication_case_is_reachable(self):
        import dataclasses
        observed = {
            "drug_not_in_dataset": self.medication_for(
                drug=UNKNOWN_DRUG, medications=[UNKNOWN_DRUG],
                phenotypes={GENE_1: "POOR"}),
            "drug_not_declared": self.medication_for(
                drug=DRUG_2, medications=[DRUG_2],
                phenotypes={GENE_1: "POOR"}),
            "any_conflict": self.medication_for(
                medications=[DRUG_1], phenotypes={GENE_1: "POOR"},
                conflicts=(synthetic_conflict(),)),
            "all_axes_full": self.medication_for(
                world=self.complete, medications=[DRUG_1],
                phenotypes={GENE_1: "POOR", GENE_2: "POOR"}),
            "some_axes_full": self.medication_for(
                medications=[DRUG_1],
                phenotypes={GENE_1: "POOR", GENE_2: "POOR"}),
            "all_unsupported_phenotype": self.medication_for(
                world=self.complete, medications=[DRUG_1],
                phenotypes={GENE_1: "nope", GENE_2: "also nope"}),
            "nothing_covered": self.medication_for(
                world=self.complete, medications=[DRUG_1],
                phenotypes={GENE_1: "nope"}),
        }
        rows = {row["case"]: row for row in MEDICATION_DECISION_TABLE}
        self.assertEqual(set(observed), set(rows))
        for case, result in observed.items():
            with self.subTest(case=case):
                self.assertEqual(result.status, rows[case]["status"])
                for code in rows[case]["reasons"]:
                    self.assertIn(code, result.reason_codes)


class TestOverallAggregation(AggregationCase):

    def test_every_medication_full_gives_full(self):
        status, reasons = aggregate_overall([medication(FULL),
                                             medication(FULL, key=DRUG_2)])
        self.assertEqual(status, FULL)
        self.assertEqual(reasons, ())

    def test_any_conflict_anywhere_is_reported_at_the_top(self):
        status, reasons = aggregate_overall(
            [medication(FULL), medication(SOURCE_CONFLICT, CONFLICT,
                                          key=DRUG_2)])
        self.assertEqual(status, SOURCE_CONFLICT)
        self.assertIn(CONFLICT, reasons)

    def test_a_conflict_does_not_erase_the_other_medications_reasons(self):
        status, reasons = aggregate_overall(
            [medication(INSUFFICIENT, NO_RULE),
             medication(SOURCE_CONFLICT, CONFLICT, key=DRUG_2)])
        self.assertEqual(status, SOURCE_CONFLICT)
        self.assertIn(CONFLICT, reasons)
        self.assertIn(NO_RULE, reasons)

    def test_something_covered_and_something_not_gives_partial(self):
        status, reasons = aggregate_overall(
            [medication(FULL), medication(INSUFFICIENT, NO_RULE, key=DRUG_2)])
        self.assertEqual(status, PARTIAL)
        self.assertIn(SOME_AXES, reasons)
        self.assertIn(NO_RULE, reasons)

    def test_a_partial_medication_counts_as_something_covered(self):
        status, _reasons = aggregate_overall(
            [medication(PARTIAL, SOME_AXES),
             medication(UNSUPPORTED_DRUG, NOT_IN_DATASET, key=DRUG_2)])
        self.assertEqual(status, PARTIAL)

    def test_every_drug_absent_from_the_dataset_keeps_that_status(self):
        status, reasons = aggregate_overall(
            [medication(UNSUPPORTED_DRUG, NOT_IN_DATASET),
             medication(UNSUPPORTED_DRUG, NOT_IN_DATASET, key=DRUG_2)])
        self.assertEqual(status, UNSUPPORTED_DRUG)
        self.assertEqual(reasons, (NOT_IN_DATASET,))

    def test_every_failure_being_an_unusable_phenotype_keeps_that_status(self):
        status, reasons = aggregate_overall(
            [medication(UNSUPPORTED_PHENOTYPE, NOT_SUPPORTED),
             medication(UNSUPPORTED_PHENOTYPE, NOT_SUPPORTED, key=DRUG_2)])
        self.assertEqual(status, UNSUPPORTED_PHENOTYPE)
        self.assertEqual(reasons, (NOT_SUPPORTED,))

    def test_mixed_failures_are_insufficient_and_keep_every_reason(self):
        status, reasons = aggregate_overall(
            [medication(UNSUPPORTED_DRUG, NOT_IN_DATASET),
             medication(INSUFFICIENT, NO_RULE, key=DRUG_2)])
        self.assertEqual(status, INSUFFICIENT)
        self.assertIn(NOT_IN_DATASET, reasons)
        self.assertIn(NO_RULE, reasons)

    def test_an_empty_aggregation_is_refused(self):
        """Returning FULL for nothing would be the emptiest possible
        reassurance."""
        with self.assertRaises(CoverageInputError) as caught:
            aggregate_overall([])
        self.assertEqual(caught.exception.code, "COVERAGE_REQUEST_EMPTY")

    def test_every_declared_overall_case_is_reachable(self):
        observed = {
            "any_conflict": [medication(SOURCE_CONFLICT, CONFLICT)],
            "all_full": [medication(FULL)],
            "some_covered": [medication(FULL),
                             medication(INSUFFICIENT, NO_RULE, key=DRUG_2)],
            "all_unsupported_drug": [medication(UNSUPPORTED_DRUG,
                                                NOT_IN_DATASET)],
            "all_unsupported_phenotype": [medication(UNSUPPORTED_PHENOTYPE,
                                                     NOT_SUPPORTED)],
            "nothing_covered": [medication(UNSUPPORTED_DRUG, NOT_IN_DATASET),
                                medication(INSUFFICIENT, NO_RULE,
                                           key=DRUG_2)],
        }
        rows = {row["case"]: row for row in OVERALL_DECISION_TABLE}
        self.assertEqual(set(observed), set(rows))
        for case, medications in observed.items():
            with self.subTest(case=case):
                status, reasons = aggregate_overall(medications)
                self.assertEqual(status, rows[case]["status"])
                for code in rows[case]["reasons"]:
                    self.assertIn(code, reasons)


class TestAggregationIsATableAndNotAComparison(AggregationCase):
    """The tests that would fail if aggregation were ``max()`` over the enum.

    ``CoverageStatus`` is declared FULL, PARTIAL, INSUFFICIENT,
    UNSUPPORTED_DRUG, UNSUPPORTED_PHENOTYPE, SOURCE_CONFLICT. A maximum over
    that order gets several of these cases right by coincidence, which is
    exactly why the coincidence is worth separating out.
    """

    def test_full_plus_insufficient_is_partial_not_insufficient(self):
        status, _ = aggregate_overall(
            [medication(FULL), medication(INSUFFICIENT, NO_RULE, key=DRUG_2)])
        self.assertEqual(status, PARTIAL)
        self.assertNotEqual(status, INSUFFICIENT)

    def test_full_plus_unsupported_drug_is_partial_not_unsupported(self):
        status, _ = aggregate_overall(
            [medication(FULL),
             medication(UNSUPPORTED_DRUG, NOT_IN_DATASET, key=DRUG_2)])
        self.assertEqual(status, PARTIAL)

    def test_partial_plus_unsupported_phenotype_is_partial(self):
        status, _ = aggregate_overall(
            [medication(PARTIAL, SOME_AXES),
             medication(UNSUPPORTED_PHENOTYPE, NOT_SUPPORTED, key=DRUG_2)])
        self.assertEqual(status, PARTIAL)

    def test_the_answer_does_not_depend_on_the_order_of_the_medications(self):
        pairs = ((FULL, INSUFFICIENT), (FULL, UNSUPPORTED_DRUG),
                 (PARTIAL, SOURCE_CONFLICT), (INSUFFICIENT, UNSUPPORTED_DRUG),
                 (UNSUPPORTED_PHENOTYPE, SOURCE_CONFLICT),
                 (FULL, SOURCE_CONFLICT))
        reasons = {FULL: (), PARTIAL: (SOME_AXES,),
                   INSUFFICIENT: (NO_RULE,),
                   UNSUPPORTED_DRUG: (NOT_IN_DATASET,),
                   UNSUPPORTED_PHENOTYPE: (NOT_SUPPORTED,),
                   SOURCE_CONFLICT: (CONFLICT,)}
        for one, two in pairs:
            with self.subTest(pair=(one.value, two.value)):
                first = medication(one, *reasons[one])
                second = medication(two, *reasons[two], key=DRUG_2)
                self.assertEqual(aggregate_overall([first, second]),
                                 aggregate_overall([second, first]))

    def test_conflict_precedence_is_preservation_not_severity(self):
        """The table's own words, checked against the table.

        The note says the other statuses survive; this asserts they do, which
        is what distinguishes preserving a fact from ranking a status.
        """
        row = [item for item in OVERALL_DECISION_TABLE
               if item["case"] == "any_conflict"][0]
        self.assertIn("not severity", row["note"])
        status, reasons = aggregate_overall(
            [medication(SOURCE_CONFLICT, CONFLICT),
             medication(UNSUPPORTED_DRUG, NOT_IN_DATASET, key=DRUG_2)])
        self.assertEqual(status, SOURCE_CONFLICT)
        self.assertIn(NOT_IN_DATASET, reasons)

    def test_the_status_enum_has_acquired_no_ordering(self):
        with self.assertRaises(TypeError):
            _ = FULL < INSUFFICIENT
        for status in CoverageStatus:
            with self.subTest(status=status.value):
                self.assertIsInstance(status.value, str)
                self.assertFalse(hasattr(status, "severity"))
                self.assertFalse(hasattr(status, "rank"))

    def test_the_reason_order_is_declared_not_derived(self):
        self.assertEqual(len(REASON_CODE_ORDER), len(list(CoverageReasonCode)))
        self.assertEqual(set(REASON_CODE_ORDER), set(CoverageReasonCode))

    def test_reason_ordering_is_stable_and_deduplicating(self):
        one = order_reasons([SOME_AXES, NO_RULE, SOME_AXES, CONFLICT])
        two = order_reasons([CONFLICT, SOME_AXES, NO_RULE])
        self.assertEqual(one, two)
        self.assertEqual(len(one), 3)

    def test_an_unknown_reason_value_is_refused(self):
        from pgx.engine.coverage_errors import CoverageEngineError
        with self.assertRaises(CoverageEngineError) as caught:
            order_reasons(["SOME_AXES_NOT_COVERED"])
        self.assertEqual(caught.exception.code, "COVERAGE_REASON_UNKNOWN")


class TestTheWholeResult(AggregationCase):

    def test_a_request_with_no_medication_is_refused(self):
        with self.assertRaises(CoverageInputError) as caught:
            self.world.request(medications=[])
        self.assertEqual(caught.exception.code, "COVERAGE_REQUEST_EMPTY")

    def test_a_duplicated_medication_is_refused_not_merged(self):
        with self.assertRaises(CoverageInputError) as caught:
            self.world.request(medications=[DRUG_1, DRUG_1])
        self.assertEqual(caught.exception.code, "COVERAGE_REQUEST_DUPLICATE")

    def test_the_result_pins_everything_it_was_computed_against(self):
        result = self.world.evaluate(medications=[DRUG_1],
                                     phenotypes={GENE_1: "POOR"})
        for field in ("profile_content_hash", "coverage_manifest_hash",
                      "ruleset_public_id", "ruleset_content_hash",
                      "dataset_public_id", "canonical_build_content_hash",
                      "evidence_build_key", "evidence_build_content_hash"):
            with self.subTest(field=field):
                self.assertTrue(getattr(result, field))

    def test_the_same_request_evaluated_twice_hashes_identically(self):
        one = self.world.evaluate(medications=[DRUG_1, DRUG_2],
                                  phenotypes={GENE_1: "POOR"})
        two = self.world.evaluate(medications=[DRUG_1, DRUG_2],
                                  phenotypes={GENE_1: "POOR"})
        self.assertEqual(one.content_hash(), two.content_hash())

    def test_the_hash_does_not_depend_on_the_request_order(self):
        one = self.world.evaluate(medications=[DRUG_1, DRUG_2],
                                  phenotypes={GENE_1: "POOR"})
        two = self.world.evaluate(medications=[DRUG_2, DRUG_1],
                                  phenotypes={GENE_1: "POOR"})
        self.assertEqual(one.content_hash(), two.content_hash())

    def test_the_result_is_serialisable(self):
        import json
        result = self.world.evaluate(medications=[DRUG_1, UNKNOWN_DRUG],
                                     phenotypes={GENE_1: "POOR"})
        payload = json.loads(json.dumps(result.to_json(), sort_keys=True))
        self.assertEqual(payload["content_hash"], result.content_hash())
        self.assertEqual(payload["medication_count"], 2)

    def test_the_result_carries_a_note_saying_what_it_is_not(self):
        result = self.world.evaluate(medications=[DRUG_1],
                                     phenotypes={GENE_1: "POOR"})
        lowered = result.note.lower()
        self.assertIn("not an attention level", lowered)
        self.assertIn("recommendation", lowered)

    def test_evaluate_coverage_refuses_anything_but_a_request(self):
        with self.assertRaises(CoverageInputError) as caught:
            evaluate_coverage({"medications": [DRUG_1]})
        self.assertEqual(caught.exception.code, "COVERAGE_REQUEST_INVALID")


if __name__ == "__main__":
    unittest.main()
