# -*- coding: utf-8 -*-
"""Axis-level coverage (section B).

One drug, one gene: could this governed ruleset have evaluated it, and if not,
why not. Every case in ``AXIS_DECISION_TABLE`` is exercised here, in the order
the table declares, because the order is part of the answer - a boundary
mismatch is checked before anything else because a mismatched pin makes every
later answer meaningless, and a conflict is checked before the phenotype
because a disagreement about an axis is a fact about the axis whatever was
observed.

The distinction this file is most careful about is the one WP-12 was careful
about one layer earlier: *nothing was supplied* and *what was supplied is not
a phenotype* are different failures, and neither is *a rule looked and did not
apply*. Collapsing any of them yields the same sentence for "we could not
look" and "we looked and found nothing to say".
"""

from __future__ import annotations

import dataclasses
import unittest

from pgx.domain.enums import CoverageReasonCode, CoverageStatus
from pgx.engine.coverage import (AXIS_DECISION_TABLE, evaluate_axis,
                                 resolve_medication)
from tests.fixtures.wp13.synthetic import (DRUG_1, DRUG_2, GENE_1, GENE_2,
                                           GENE_3, UNKNOWN_DRUG,
                                           synthetic_conflict,
                                           synthetic_manifest)
from tests.unit.engine._coverage_support import SyntheticWorld

FULL = CoverageStatus.FULL
INSUFFICIENT = CoverageStatus.INSUFFICIENT
UNSUPPORTED_PHENOTYPE = CoverageStatus.UNSUPPORTED_PHENOTYPE
SOURCE_CONFLICT = CoverageStatus.SOURCE_CONFLICT


class AxisCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.world = SyntheticWorld(expected_extra_gene=True)

    @classmethod
    def tearDownClass(cls):
        cls.world.close()

    def axis(self, gene=GENE_1, drug=DRUG_1, **kwargs):
        return evaluate_axis(request=self.world.request(**kwargs),
                             drug_canonical_key=drug,
                             gene_canonical_key=gene)

    def assertAxis(self, axis, status, *reasons):
        self.assertEqual(axis.status, status)
        self.assertEqual(set(axis.reason_codes), set(reasons))


class TestTheCoveredCase(AxisCase):
    """Case D: the exact axis is declared, a validated member rule covers the
    observed phenotype, and its evidence resolves."""

    def test_a_declared_axis_with_a_matching_phenotype_is_full(self):
        axis = self.axis(medications=[DRUG_1],
                         phenotypes={GENE_1: "POOR", GENE_2: "POOR"})
        self.assertAxis(axis, FULL)
        self.assertEqual(axis.reason_codes, ())

    def test_a_full_axis_names_its_rule_its_evidence_and_its_phenotype(self):
        axis = self.axis(medications=[DRUG_1], phenotypes={GENE_1: "POOR"})
        self.assertTrue(axis.rule_references)
        self.assertTrue(axis.evidence_references)
        self.assertEqual(axis.observed_phenotype.value, "POOR")
        self.assertEqual(axis.observation_state, "NORMALIZED")
        self.assertTrue(axis.declaration_id)

    def test_a_full_axis_pins_what_it_was_computed_against(self):
        axis = self.axis(medications=[DRUG_1], phenotypes={GENE_1: "POOR"})
        for field in ("ruleset_public_id", "ruleset_content_hash",
                      "dataset_public_id", "canonical_build_content_hash",
                      "coverage_manifest_hash"):
            with self.subTest(field=field):
                self.assertTrue(getattr(axis, field))

    def test_the_same_axis_evaluated_twice_hashes_identically(self):
        one = self.axis(medications=[DRUG_1], phenotypes={GENE_1: "POOR"})
        two = self.axis(medications=[DRUG_1], phenotypes={GENE_1: "POOR"})
        self.assertEqual(one.content_hash(), two.content_hash())

    def test_case_folding_of_the_input_does_not_change_the_answer(self):
        """WP-12 owns transport-level formatting; coverage inherits it rather
        than re-deciding it."""
        one = self.axis(medications=[DRUG_1], phenotypes={GENE_1: "POOR"})
        two = self.axis(medications=[DRUG_1], phenotypes={GENE_1: " poor "})
        self.assertEqual(one.content_hash(), two.content_hash())


class TestAbsentAndUnusableInputsStaySeparate(AxisCase):

    def test_a_gene_the_profile_is_silent_about_is_insufficient(self):
        """Case A. Not UNSUPPORTED_PHENOTYPE: nothing was supplied, so there
        is nothing whose support could be in question."""
        axis = self.axis(gene=GENE_2, medications=[DRUG_1],
                         phenotypes={GENE_1: "POOR"})
        self.assertAxis(axis, INSUFFICIENT,
                        CoverageReasonCode.PHENOTYPE_NOT_PROVIDED)
        self.assertEqual(axis.observation_state, "ABSENT")
        self.assertIsNone(axis.observed_phenotype)

    def test_an_empty_value_is_insufficient_not_unsupported(self):
        axis = self.axis(medications=[DRUG_1], phenotypes={GENE_1: ""})
        self.assertAxis(axis, INSUFFICIENT,
                        CoverageReasonCode.PHENOTYPE_NOT_PROVIDED)
        self.assertEqual(axis.observation_state, "MISSING")

    def test_a_value_that_is_not_a_phenotype_is_unsupported(self):
        """Case B. A different status from the one above, and the difference
        is the whole point: something was supplied and could not be read."""
        axis = self.axis(medications=[DRUG_1],
                         phenotypes={GENE_1: "poor metabolizer"})
        self.assertAxis(axis, UNSUPPORTED_PHENOTYPE,
                        CoverageReasonCode.PHENOTYPE_NOT_SUPPORTED)
        self.assertEqual(axis.observation_state, "UNSUPPORTED")

    def test_an_indeterminate_result_is_unsupported_not_missing(self):
        axis = self.axis(medications=[DRUG_1],
                         phenotypes={GENE_1: "INDETERMINATE"})
        self.assertAxis(axis, UNSUPPORTED_PHENOTYPE,
                        CoverageReasonCode.PHENOTYPE_NOT_SUPPORTED)
        self.assertEqual(axis.observation_state, "INDETERMINATE")

    def test_an_unusable_input_carries_no_phenotype(self):
        for value in ("poor metabolizer", "INDETERMINATE", "", "*1/*2"):
            with self.subTest(value=value):
                axis = self.axis(medications=[DRUG_1],
                                 phenotypes={GENE_1: value})
                self.assertIsNone(axis.observed_phenotype)
                self.assertNotEqual(axis.status, FULL)

    def test_no_unusable_input_ever_becomes_normal(self):
        """The false-reassurance failure at its earliest point: a value that
        could not be read must never be treated as an unremarkable one."""
        for value in ("", "unknown", "n/a", "-", "0", "poor metabolizer"):
            with self.subTest(value=value):
                axis = self.axis(medications=[DRUG_1],
                                 phenotypes={GENE_1: value})
                self.assertNotEqual(axis.status, FULL)
                self.assertTrue(axis.reason_codes)


class TestAnUndeclaredAxisIsNotCovered(AxisCase):

    def test_a_gene_in_scope_with_no_rule_is_insufficient(self):
        """Case C. ``GENE_3`` is expected and no rule covers it, which is
        exactly the gap the declared scope exists to make visible."""
        axis = self.axis(gene=GENE_3, medications=[DRUG_1],
                         phenotypes={GENE_3: "POOR"})
        self.assertAxis(axis, INSUFFICIENT,
                        CoverageReasonCode.NO_VALIDATED_RULE_FOR_AXIS)
        self.assertEqual(axis.observed_phenotype.value, "POOR")

    def test_a_declared_gene_on_an_undeclared_phenotype_is_insufficient(self):
        """The axis is drug-gene-*phenotype*. A rule for POOR does not cover
        NORMAL, and reporting the gene as covered would be a claim about a
        comparison nobody made."""
        axis = self.axis(medications=[DRUG_1], phenotypes={GENE_1: "NORMAL"})
        self.assertAxis(axis, INSUFFICIENT,
                        CoverageReasonCode.NO_VALIDATED_RULE_FOR_AXIS)

    def test_rapid_does_not_reach_a_rule_declared_for_ultrarapid(self):
        """SAFETY-INV-004, inherited from WP-12 rather than re-implemented."""
        for value in ("RAPID", "ULTRARAPID"):
            with self.subTest(phenotype=value):
                axis = self.axis(medications=[DRUG_1],
                                 phenotypes={GENE_1: value})
                self.assertAxis(axis, INSUFFICIENT,
                                CoverageReasonCode.NO_VALIDATED_RULE_FOR_AXIS)

    def test_a_drug_with_no_declaration_has_no_declaration_id(self):
        axis = self.axis(drug=DRUG_2, medications=[DRUG_2],
                         phenotypes={GENE_1: "POOR"})
        self.assertAxis(axis, INSUFFICIENT,
                        CoverageReasonCode.NO_VALIDATED_RULE_FOR_AXIS)
        self.assertIsNone(axis.declaration_id)

    def test_an_unrecognised_drug_fabricates_no_axis(self):
        axis = self.axis(drug=UNKNOWN_DRUG, medications=[UNKNOWN_DRUG],
                         phenotypes={GENE_1: "POOR"})
        self.assertNotEqual(axis.status, FULL)
        self.assertEqual(axis.rule_references, ())


class TestEvidenceMustResolve(AxisCase):

    def test_unresolvable_evidence_makes_the_axis_insufficient(self):
        """Case E. SAFETY-INV-006: a conclusion whose evidence cannot be
        retrieved is not a conclusion anybody can check."""
        axis = self.axis(medications=[DRUG_1], phenotypes={GENE_1: "POOR"},
                         resolver=lambda reference: False)
        self.assertAxis(axis, INSUFFICIENT,
                        CoverageReasonCode.EVIDENCE_REFERENCE_MISSING)

    def test_it_still_names_the_rule_it_could_not_support(self):
        axis = self.axis(medications=[DRUG_1], phenotypes={GENE_1: "POOR"},
                         resolver=lambda reference: False)
        self.assertTrue(axis.rule_references)
        self.assertEqual(axis.evidence_references, ())

    def test_partially_resolvable_evidence_is_still_insufficient(self):
        from tests.fixtures.wp11.synthetic import SYNTHETIC_EVIDENCE_UUIDS
        one = SYNTHETIC_EVIDENCE_UUIDS[0]
        axis = self.axis(medications=[DRUG_1], phenotypes={GENE_1: "POOR"},
                         resolver=lambda reference: reference == one)
        self.assertAxis(axis, INSUFFICIENT,
                        CoverageReasonCode.EVIDENCE_REFERENCE_MISSING)


class TestABoundaryMismatchFailsClosed(AxisCase):

    def mismatched(self, **overrides):
        return dataclasses.replace(self.world.manifest, **overrides)

    def test_a_manifest_naming_another_ruleset_yields_a_mismatch(self):
        """Case F, and it is checked first: if the manifest does not describe
        the ruleset supplied, every later question is about something else."""
        axis = self.axis(
            medications=[DRUG_1], phenotypes={GENE_1: "POOR"},
            manifest=self.mismatched(
                ruleset_public_id="PGX-RULESET-29991231-002"))
        self.assertAxis(axis, INSUFFICIENT,
                        CoverageReasonCode.DATASET_RULESET_MISMATCH)
        self.assertEqual(axis.observation_state, "NOT_EVALUATED")

    def test_every_pin_that_can_disagree_yields_a_mismatch(self):
        for field, value in (
                ("ruleset_content_hash", "sha256:" + "a" * 64),
                ("dataset_public_id", "PGX-DATA-19700101-001"),
                ("canonical_build_content_hash", "sha256:" + "b" * 64),
                ("evidence_build_content_hash", "sha256:" + "c" * 64)):
            with self.subTest(field=field):
                axis = self.axis(medications=[DRUG_1],
                                 phenotypes={GENE_1: "POOR"},
                                 manifest=self.mismatched(**{field: value}))
                self.assertAxis(axis, INSUFFICIENT,
                                CoverageReasonCode.DATASET_RULESET_MISMATCH)

    def test_a_mismatch_beats_a_perfectly_good_phenotype(self):
        """Failing closed means the good input does not rescue the bad pin."""
        axis = self.axis(
            medications=[DRUG_1], phenotypes={GENE_1: "POOR"},
            manifest=self.mismatched(ruleset_content_hash="sha256:" + "f" * 64))
        self.assertNotEqual(axis.status, FULL)
        self.assertIsNone(axis.observed_phenotype)

    def test_a_declared_rule_absent_from_the_ruleset_yields_a_mismatch(self):
        declaration = self.world.manifest.declaration_for(DRUG_1)
        altered = dataclasses.replace(
            declaration,
            supported_axes=tuple(
                dataclasses.replace(
                    axis, rule_id="00000000-0000-4000-8000-000000000000")
                for axis in declaration.supported_axes))
        axis = self.axis(
            medications=[DRUG_1], phenotypes={GENE_1: "POOR"},
            manifest=dataclasses.replace(self.world.manifest,
                                         declarations=(altered,)))
        self.assertAxis(axis, INSUFFICIENT,
                        CoverageReasonCode.DATASET_RULESET_MISMATCH)

    def test_a_declared_rule_whose_content_changed_yields_a_mismatch(self):
        declaration = self.world.manifest.declaration_for(DRUG_1)
        altered = dataclasses.replace(
            declaration,
            supported_axes=tuple(
                dataclasses.replace(axis,
                                    rule_content_hash="sha256:" + "d" * 64)
                for axis in declaration.supported_axes))
        axis = self.axis(
            medications=[DRUG_1], phenotypes={GENE_1: "POOR"},
            manifest=dataclasses.replace(self.world.manifest,
                                         declarations=(altered,)))
        self.assertAxis(axis, INSUFFICIENT,
                        CoverageReasonCode.DATASET_RULESET_MISMATCH)


class TestAConflictIsPreservedNotResolved(AxisCase):

    def test_an_unresolved_conflict_yields_source_conflict(self):
        """Case G. SAFETY-INV-008: a disagreement between validated sources is
        not a reason to report less."""
        axis = self.axis(medications=[DRUG_1], phenotypes={GENE_1: "POOR"},
                         conflicts=(synthetic_conflict(),))
        self.assertAxis(axis, SOURCE_CONFLICT,
                        CoverageReasonCode.VALIDATED_RULES_CONFLICT)

    def test_it_names_the_conflict_and_keeps_every_reference(self):
        conflict = synthetic_conflict()
        axis = self.axis(medications=[DRUG_1], phenotypes={GENE_1: "POOR"},
                         conflicts=(conflict,))
        self.assertEqual(axis.conflict_references, (conflict.conflict_id,))
        rule_ids = {item["rule_id"] for item in axis.rule_references}
        for value in conflict.rule_ids:
            with self.subTest(rule=value):
                self.assertIn(value, rule_ids)

    def test_no_side_of_the_disagreement_is_dropped(self):
        conflict = synthetic_conflict(
            rule_ids=("11111111-0000-4000-8000-00000000000%d" % index
                      for index in range(1, 4)))
        axis = self.axis(medications=[DRUG_1], phenotypes={GENE_1: "POOR"},
                         conflicts=(conflict,))
        rule_ids = {item["rule_id"] for item in axis.rule_references}
        self.assertEqual(len(conflict.rule_ids), 3)
        for value in conflict.rule_ids:
            self.assertIn(value, rule_ids)

    def test_a_conflict_beats_a_fully_covered_axis(self):
        """Without the conflict this axis is FULL. Preserving the
        disagreement is the one thing that must not be lost to an aggregate,
        and this is where the loss would happen."""
        covered = self.axis(medications=[DRUG_1], phenotypes={GENE_1: "POOR"})
        self.assertEqual(covered.status, FULL)
        conflicted = self.axis(medications=[DRUG_1],
                               phenotypes={GENE_1: "POOR"},
                               conflicts=(synthetic_conflict(),))
        self.assertEqual(conflicted.status, SOURCE_CONFLICT)

    def test_a_conflict_survives_an_input_nobody_supplied(self):
        """The disagreement is about the axis, not about the input. Hiding it
        because the profile was silent would be the collapse in reverse."""
        axis = self.axis(gene=GENE_2, medications=[DRUG_1],
                         phenotypes={GENE_1: "POOR"},
                         conflicts=(synthetic_conflict(gene=GENE_2),))
        self.assertAxis(axis, SOURCE_CONFLICT,
                        CoverageReasonCode.VALIDATED_RULES_CONFLICT)

    def test_a_conflict_about_another_axis_is_not_applied_here(self):
        axis = self.axis(medications=[DRUG_1], phenotypes={GENE_1: "POOR"},
                         conflicts=(synthetic_conflict(gene=GENE_2),))
        self.assertEqual(axis.status, FULL)

    def test_a_conflict_about_another_drug_is_not_applied_here(self):
        axis = self.axis(medications=[DRUG_1], phenotypes={GENE_1: "POOR"},
                         conflicts=(synthetic_conflict(drug=DRUG_2),))
        self.assertEqual(axis.status, FULL)

    def test_a_conflict_cannot_be_declared_resolved(self):
        from pgx.engine.coverage_errors import CoverageEngineError
        with self.assertRaises(CoverageEngineError) as caught:
            synthetic_conflict(resolved=True)
        self.assertEqual(caught.exception.code, "COVERAGE_CONFLICT_RESOLVED")

    def test_one_rule_disagrees_with_nothing(self):
        from pgx.engine.coverage_errors import CoverageEngineError
        with self.assertRaises(CoverageEngineError) as caught:
            synthetic_conflict(rule_ids=("11111111-0000-4000-8000-000000000001",))
        self.assertEqual(caught.exception.code,
                         "COVERAGE_CONFLICT_INCOMPLETE")

    def test_a_boundary_mismatch_is_still_checked_before_a_conflict(self):
        """Order matters: a mismatched pin means the conflict being reported
        may be about a ruleset nobody supplied."""
        axis = self.axis(
            medications=[DRUG_1], phenotypes={GENE_1: "POOR"},
            conflicts=(synthetic_conflict(),),
            manifest=dataclasses.replace(
                self.world.manifest,
                ruleset_content_hash="sha256:" + "e" * 64))
        self.assertAxis(axis, INSUFFICIENT,
                        CoverageReasonCode.DATASET_RULESET_MISMATCH)


class TestTheDecisionTableIsThePublishedContract(AxisCase):

    def test_every_row_names_a_case_a_condition_and_a_status(self):
        for row in AXIS_DECISION_TABLE:
            with self.subTest(case=row["case"]):
                self.assertTrue(row["case"])
                self.assertGreater(len(row["when"]), 20)
                self.assertIsInstance(row["status"], CoverageStatus)

    def test_only_the_covered_row_carries_no_reason(self):
        for row in AXIS_DECISION_TABLE:
            with self.subTest(case=row["case"]):
                if row["status"] is FULL:
                    self.assertEqual(row["reasons"], ())
                else:
                    self.assertTrue(row["reasons"])

    def test_every_declared_case_is_reachable(self):
        """A table row nothing can produce is documentation of a behaviour
        that does not exist."""
        observed = {
            "boundary_mismatch": self.axis(
                medications=[DRUG_1], phenotypes={GENE_1: "POOR"},
                manifest=dataclasses.replace(
                    self.world.manifest,
                    ruleset_content_hash="sha256:" + "1" * 64)),
            "unresolved_conflict": self.axis(
                medications=[DRUG_1], phenotypes={GENE_1: "POOR"},
                conflicts=(synthetic_conflict(),)),
            "phenotype_absent": self.axis(
                gene=GENE_2, medications=[DRUG_1],
                phenotypes={GENE_1: "POOR"}),
            "phenotype_unusable": self.axis(
                medications=[DRUG_1], phenotypes={GENE_1: "not a phenotype"}),
            "no_declared_axis": self.axis(
                gene=GENE_3, medications=[DRUG_1],
                phenotypes={GENE_3: "POOR"}),
            "evidence_unresolvable": self.axis(
                medications=[DRUG_1], phenotypes={GENE_1: "POOR"},
                resolver=lambda reference: False),
            "covered": self.axis(medications=[DRUG_1],
                                 phenotypes={GENE_1: "POOR"}),
        }
        rows = {row["case"]: row for row in AXIS_DECISION_TABLE}
        for case, axis in observed.items():
            with self.subTest(case=case):
                self.assertEqual(axis.status, rows[case]["status"])
                for code in rows[case]["reasons"]:
                    self.assertIn(code, axis.reason_codes)

    def test_the_two_mismatch_rows_are_reachable_and_agree(self):
        declaration = self.world.manifest.declaration_for(DRUG_1)
        altered = dataclasses.replace(
            declaration,
            supported_axes=tuple(
                dataclasses.replace(
                    item, rule_id="00000000-0000-4000-8000-000000000000")
                for item in declaration.supported_axes))
        axis = self.axis(
            medications=[DRUG_1], phenotypes={GENE_1: "POOR"},
            manifest=dataclasses.replace(self.world.manifest,
                                         declarations=(altered,)))
        row = [item for item in AXIS_DECISION_TABLE
               if item["case"] == "rule_not_in_ruleset"][0]
        self.assertEqual(axis.status, row["status"])
        self.assertEqual(set(axis.reason_codes), set(row["reasons"]))

    def test_the_rule_does_not_cover_axis_row_is_reachable(self):
        axis = self.axis(medications=[DRUG_1], phenotypes={GENE_1: "NORMAL"})
        row = [item for item in AXIS_DECISION_TABLE
               if item["case"] == "rule_does_not_cover_axis"][0]
        self.assertEqual(axis.status, row["status"])
        self.assertEqual(set(axis.reason_codes), set(row["reasons"]))


class TestMedicationResolutionIsALookupNotAnInterpretation(AxisCase):

    def test_a_canonical_key_in_the_catalogue_is_recognised(self):
        reference = resolve_medication(DRUG_1, (DRUG_1, DRUG_2))
        self.assertEqual(reference.state, "RECOGNIZED")
        self.assertTrue(reference.is_recognized)

    def test_a_canonical_key_outside_it_is_not(self):
        reference = resolve_medication(UNKNOWN_DRUG, (DRUG_1, DRUG_2))
        self.assertEqual(reference.state, "NOT_IN_CANONICAL_DATASET")
        self.assertFalse(reference.is_recognized)
        self.assertEqual(reference.drug_canonical_key, UNKNOWN_DRUG)

    def test_free_text_is_not_normalised_into_a_drug(self):
        """Resolving a brand name is WP-07's work. A coverage engine that
        guessed would be inventing the subject of its own answer."""
        for value in ("Plavix", "clopidogrel", "testdrug-alpha", "",
                      "   ", None, 7):
            with self.subTest(value=value):
                reference = resolve_medication(value, (DRUG_1,))
                self.assertEqual(reference.state, "INVALID")
                self.assertIsNone(reference.drug_canonical_key)
                self.assertTrue(reference.reason)

    def test_recognition_is_not_coverage(self):
        """architecture.md 6.2. ``DRUG_2`` is in the catalogue and nothing is
        declared about it."""
        reference = resolve_medication(DRUG_2, (DRUG_1, DRUG_2))
        self.assertTrue(reference.is_recognized)
        axis = self.axis(drug=DRUG_2, medications=[DRUG_2],
                         phenotypes={GENE_1: "POOR"})
        self.assertNotEqual(axis.status, FULL)


if __name__ == "__main__":
    unittest.main()
