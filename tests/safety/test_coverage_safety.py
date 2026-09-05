# -*- coding: utf-8 -*-
"""The coverage engine's safety properties (section E).

Not examples: properties, asserted over every reason code the engine can
produce. A test that checks one insufficient case proves that one case was
written correctly. These build a result exhibiting each of the eight reason
codes and then assert the same invariants across all of them, so a new code -
or a new path to an old one - is held to the same rules without anybody
remembering to add a test.

The invariants, in the safety contract's own terms:

* ``SAFETY-INV-001`` missing data is never reported as low or absent concern.
  Here: every non-FULL status carries at least one machine-readable reason,
  and nothing that was not evaluated is ever FULL.
* ``SAFETY-INV-003`` only validated rules support a coverage claim.
* ``SAFETY-INV-005`` no candidate is preferred, ranked or scored.
* ``SAFETY-INV-006`` a claim names evidence that resolves.
* ``SAFETY-INV-008`` an unresolved source conflict is never reassurance.
"""

from __future__ import annotations

import dataclasses
import json
import unittest

from pgx.domain.enums import CoverageReasonCode, CoverageStatus
from pgx.engine.coverage_models import (AxisCoverage, CoverageResult,
                                        MedicationCoverage)
from tests.fixtures.wp13.synthetic import (DRUG_1, DRUG_2, GENE_1, GENE_2,
                                           GENE_3, UNKNOWN_DRUG,
                                           synthetic_conflict)
from tests.unit.engine._coverage_support import SyntheticWorld

#: Names no coverage model, schema or result may contain, at any depth. WP-13
#: answers what could be evaluated; every one of these belongs to the question
#: it does not answer, and the strongest guarantee that it never emits one is
#: that there is nowhere to put it.
FORBIDDEN_KEYS = ("attention", "overall_attention", "risk", "risk_level",
                  "risk_score", "severity", "dose", "recommendation",
                  "preferred", "safer", "suitability_score", "treatment",
                  "score", "rank", "priority", "confidence")


def keys_of(payload, found=None):
    """Every mapping key anywhere inside a JSON-shaped value."""
    found = set() if found is None else found
    if isinstance(payload, dict):
        for key, value in payload.items():
            found.add(key)
            keys_of(value, found)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            keys_of(item, found)
    return found


class CoverageSafetyCase(unittest.TestCase):
    """Every reason code, each reached by a different real path."""

    @classmethod
    def setUpClass(cls):
        cls.world = SyntheticWorld(expected_extra_gene=True)
        cls.complete = SyntheticWorld(expected_extra_gene=False)
        world, complete = cls.world, cls.complete
        mismatched = dataclasses.replace(
            world.manifest, ruleset_content_hash="sha256:" + "a" * 64)
        cls.results = {
            CoverageReasonCode.DRUG_NOT_IN_CANONICAL_DATASET:
                world.evaluate(medications=[UNKNOWN_DRUG],
                               phenotypes={GENE_1: "POOR"}),
            CoverageReasonCode.PHENOTYPE_NOT_PROVIDED:
                complete.evaluate(medications=[DRUG_1], phenotypes={}),
            CoverageReasonCode.PHENOTYPE_NOT_SUPPORTED:
                complete.evaluate(medications=[DRUG_1],
                                  phenotypes={GENE_1: "poor metabolizer",
                                              GENE_2: "*1/*2"}),
            CoverageReasonCode.NO_VALIDATED_RULE_FOR_AXIS:
                world.evaluate(medications=[DRUG_2],
                               phenotypes={GENE_1: "POOR"}),
            CoverageReasonCode.SOME_AXES_NOT_COVERED:
                world.evaluate(medications=[DRUG_1],
                               phenotypes={GENE_1: "POOR", GENE_2: "POOR",
                                           GENE_3: "POOR"}),
            CoverageReasonCode.VALIDATED_RULES_CONFLICT:
                world.evaluate(medications=[DRUG_1],
                               phenotypes={GENE_1: "POOR"},
                               conflicts=(synthetic_conflict(),)),
            CoverageReasonCode.DATASET_RULESET_MISMATCH:
                world.evaluate(medications=[DRUG_1],
                               phenotypes={GENE_1: "POOR"},
                               manifest=mismatched),
            CoverageReasonCode.EVIDENCE_REFERENCE_MISSING:
                complete.evaluate(medications=[DRUG_1],
                                  phenotypes={GENE_1: "POOR",
                                              GENE_2: "POOR"},
                                  resolver=lambda reference: False),
        }
        cls.covered = complete.evaluate(
            medications=[DRUG_1], phenotypes={GENE_1: "POOR",
                                              GENE_2: "POOR"})

    @classmethod
    def tearDownClass(cls):
        cls.world.close()
        cls.complete.close()

    def levels(self, result):
        """Every level of one result: overall, medication, axis."""
        yield "overall", result
        for item in result.medications:
            yield "medication:%s" % item.medication.requested_value, item
            for axis in item.axes:
                yield "axis:%s" % (axis.axis_key,), axis


class TestEveryReasonCodeIsProducible(CoverageSafetyCase):

    def test_the_eight_reason_codes_are_each_reachable(self):
        """A published code no path can emit is a promise the system does not
        keep; a path with no code is an absence nobody can act on."""
        self.assertEqual(set(self.results), set(CoverageReasonCode))

    def test_each_result_actually_carries_the_code_it_was_built_for(self):
        for code, result in self.results.items():
            with self.subTest(code=code.value):
                present = set(result.reason_codes)
                for item in result.medications:
                    present.update(item.reason_codes)
                    for axis in item.axes:
                        present.update(axis.reason_codes)
                self.assertIn(code, present)


class TestAbsenceIsNeverReassurance(CoverageSafetyCase):
    """SAFETY-INV-001."""

    def test_every_non_full_status_carries_a_reason_at_every_level(self):
        for code, result in self.results.items():
            for where, value in self.levels(result):
                with self.subTest(code=code.value, level=where):
                    if value.status is CoverageStatus.FULL:
                        continue
                    self.assertTrue(
                        value.reason_codes,
                        "%s at %s has no reason" % (value.status.value, where))

    def test_full_never_carries_a_failure_reason(self):
        for where, value in self.levels(self.covered):
            with self.subTest(level=where):
                if value.status is CoverageStatus.FULL:
                    self.assertEqual(value.reason_codes, ())

    def test_no_result_built_from_a_failure_is_full(self):
        for code, result in self.results.items():
            with self.subTest(code=code.value):
                self.assertNotEqual(result.status, CoverageStatus.FULL)

    def test_a_missing_phenotype_never_produces_a_covered_axis(self):
        result = self.results[CoverageReasonCode.PHENOTYPE_NOT_PROVIDED]
        for _where, value in self.levels(result):
            self.assertNotEqual(value.status, CoverageStatus.FULL)

    def test_the_model_refuses_to_construct_an_unexplained_failure(self):
        """Enforced in the type, not only in the engine, so a future caller
        assembling one by hand meets the same rule."""
        from pgx.engine.coverage_errors import CoverageEngineError
        for status in CoverageStatus:
            if status is CoverageStatus.FULL:
                continue
            with self.subTest(status=status.value):
                with self.assertRaises(CoverageEngineError) as caught:
                    AxisCoverage(drug_canonical_key=DRUG_1,
                                 gene_canonical_key=GENE_1, status=status,
                                 reason_codes=())
                self.assertEqual(caught.exception.code,
                                 "COVERAGE_REASON_MISSING")

    def test_the_model_refuses_a_full_axis_carrying_a_caveat(self):
        from pgx.engine.coverage_errors import CoverageEngineError
        with self.assertRaises(CoverageEngineError) as caught:
            AxisCoverage(
                drug_canonical_key=DRUG_1, gene_canonical_key=GENE_1,
                status=CoverageStatus.FULL,
                reason_codes=(CoverageReasonCode.SOME_AXES_NOT_COVERED,))
        self.assertEqual(caught.exception.code, "COVERAGE_FULL_WITH_REASON")

    def test_a_result_over_no_medication_is_refused(self):
        from pgx.engine.coverage_errors import CoverageInputError
        with self.assertRaises(CoverageInputError):
            CoverageResult(
                status=CoverageStatus.FULL, reason_codes=(), medications=(),
                profile_content_hash="sha256:" + "0" * 64,
                coverage_manifest_hash="", ruleset_public_id="",
                ruleset_content_hash="", dataset_public_id="",
                canonical_build_content_hash="", evidence_build_key="",
                evidence_build_content_hash="")


class TestOnlyValidatedRulesWithEvidenceSupportACoverageClaim(
        CoverageSafetyCase):
    """SAFETY-INV-003 and SAFETY-INV-006."""

    def test_every_full_axis_names_a_rule(self):
        for _where, value in self.levels(self.covered):
            if isinstance(value, AxisCoverage) and \
                    value.status is CoverageStatus.FULL:
                self.assertTrue(value.rule_references)

    def test_every_full_axis_names_resolvable_evidence(self):
        for _where, value in self.levels(self.covered):
            if isinstance(value, AxisCoverage) and \
                    value.status is CoverageStatus.FULL:
                self.assertTrue(value.evidence_references)
                for reference in value.evidence_references:
                    self.assertTrue(self.complete.resolver(reference))

    def test_the_model_refuses_a_full_axis_without_a_rule(self):
        from pgx.domain.enums import Phenotype
        from pgx.engine.coverage_errors import CoverageEngineError
        with self.assertRaises(CoverageEngineError) as caught:
            AxisCoverage(drug_canonical_key=DRUG_1,
                         gene_canonical_key=GENE_1,
                         status=CoverageStatus.FULL,
                         observed_phenotype=Phenotype.POOR,
                         evidence_references=("e",))
        self.assertEqual(caught.exception.code, "COVERAGE_FULL_WITHOUT_RULE")

    def test_the_model_refuses_a_full_axis_without_evidence(self):
        from pgx.domain.enums import Phenotype
        from pgx.engine.coverage_errors import CoverageEngineError
        with self.assertRaises(CoverageEngineError) as caught:
            AxisCoverage(drug_canonical_key=DRUG_1,
                         gene_canonical_key=GENE_1,
                         status=CoverageStatus.FULL,
                         observed_phenotype=Phenotype.POOR,
                         rule_references=({"rule_id": "r"},))
        self.assertEqual(caught.exception.code,
                         "COVERAGE_FULL_WITHOUT_EVIDENCE")

    def test_the_model_refuses_a_full_axis_without_a_phenotype(self):
        from pgx.engine.coverage_errors import CoverageEngineError
        with self.assertRaises(CoverageEngineError) as caught:
            AxisCoverage(drug_canonical_key=DRUG_1,
                         gene_canonical_key=GENE_1,
                         status=CoverageStatus.FULL,
                         rule_references=({"rule_id": "r"},),
                         evidence_references=("e",))
        self.assertEqual(caught.exception.code,
                         "COVERAGE_FULL_WITHOUT_PHENOTYPE")

    def test_the_model_refuses_a_full_medication_with_no_axis(self):
        from pgx.engine.coverage_errors import CoverageEngineError
        from pgx.engine.coverage_models import MedicationReference
        with self.assertRaises(CoverageEngineError) as caught:
            MedicationCoverage(
                medication=MedicationReference(requested_value=DRUG_1,
                                               state="RECOGNIZED",
                                               drug_canonical_key=DRUG_1),
                status=CoverageStatus.FULL)
        self.assertEqual(caught.exception.code, "COVERAGE_FULL_WITHOUT_AXES")

    def test_unresolvable_evidence_removes_the_claim(self):
        result = self.results[CoverageReasonCode.EVIDENCE_REFERENCE_MISSING]
        for _where, value in self.levels(result):
            self.assertNotEqual(value.status, CoverageStatus.FULL)


class TestAConflictIsNeverLost(CoverageSafetyCase):
    """SAFETY-INV-008."""

    def test_a_conflicting_axis_reaches_the_top_of_the_result(self):
        result = self.results[CoverageReasonCode.VALIDATED_RULES_CONFLICT]
        self.assertEqual(result.status, CoverageStatus.SOURCE_CONFLICT)
        self.assertIn(CoverageReasonCode.VALIDATED_RULES_CONFLICT,
                      result.reason_codes)

    def test_it_stays_conflicting_at_every_level_that_saw_it(self):
        result = self.results[CoverageReasonCode.VALIDATED_RULES_CONFLICT]
        conflicting = [value for _where, value in self.levels(result)
                       if value.status is CoverageStatus.SOURCE_CONFLICT]
        self.assertGreaterEqual(len(conflicting), 3)

    def test_the_conflicting_axis_still_names_the_conflict(self):
        result = self.results[CoverageReasonCode.VALIDATED_RULES_CONFLICT]
        for item in result.medications:
            for axis in item.axes:
                if axis.status is CoverageStatus.SOURCE_CONFLICT:
                    self.assertTrue(axis.conflict_references)

    def test_the_model_refuses_an_unidentified_conflict(self):
        from pgx.engine.coverage_errors import CoverageEngineError
        with self.assertRaises(CoverageEngineError) as caught:
            AxisCoverage(
                drug_canonical_key=DRUG_1, gene_canonical_key=GENE_1,
                status=CoverageStatus.SOURCE_CONFLICT,
                reason_codes=(CoverageReasonCode.VALIDATED_RULES_CONFLICT,))
        self.assertEqual(caught.exception.code,
                         "COVERAGE_CONFLICT_UNIDENTIFIED")

    def test_a_conflict_is_serialised_as_unresolved(self):
        self.assertFalse(synthetic_conflict().to_json()["resolved"])


class TestNothingHereRanksOrScoresACandidate(CoverageSafetyCase):
    """SAFETY-INV-005, and the attention separation contract."""

    def test_no_result_contains_a_forbidden_key_at_any_depth(self):
        for code, result in self.results.items():
            present = keys_of(result.to_json())
            for forbidden in FORBIDDEN_KEYS:
                with self.subTest(code=code.value, key=forbidden):
                    for key in present:
                        self.assertNotIn(forbidden, key.lower())

    def test_the_covered_result_contains_none_either(self):
        for key in keys_of(self.covered.to_json()):
            for forbidden in FORBIDDEN_KEYS:
                with self.subTest(key=key, forbidden=forbidden):
                    self.assertNotIn(forbidden, key.lower())

    def test_the_manifest_contains_no_forbidden_key(self):
        for key in keys_of(self.world.manifest.to_json()):
            for forbidden in FORBIDDEN_KEYS:
                with self.subTest(key=key, forbidden=forbidden):
                    self.assertNotIn(forbidden, key.lower())

    def test_no_dataclass_in_the_coverage_models_declares_one(self):
        import pgx.engine.coverage_models as models
        for name in dir(models):
            attribute = getattr(models, name)
            if not dataclasses.is_dataclass(attribute):
                continue
            for field in dataclasses.fields(attribute):
                for forbidden in FORBIDDEN_KEYS:
                    with self.subTest(model=name, field=field.name,
                                      forbidden=forbidden):
                        self.assertNotIn(forbidden, field.name.lower())

    def test_no_dataclass_in_the_manifest_declares_one(self):
        import pgx.engine.coverage_manifest as manifest
        for name in dir(manifest):
            attribute = getattr(manifest, name)
            if not dataclasses.is_dataclass(attribute):
                continue
            for field in dataclasses.fields(attribute):
                for forbidden in FORBIDDEN_KEYS:
                    with self.subTest(model=name, field=field.name,
                                      forbidden=forbidden):
                        self.assertNotIn(forbidden, field.name.lower())

    def test_no_medication_carries_a_number_that_could_be_read_as_a_ranking(
            self):
        """LEGACY-BUG-009 in its general form. A 0-100 number beside a drug
        name reads as suitability however it is labelled."""
        for code, result in self.results.items():
            for item in result.to_json()["medications"]:
                with self.subTest(code=code.value):
                    for key, value in item.items():
                        if isinstance(value, (int, float)) and \
                                not isinstance(value, bool):
                            self.assertIn(key, ("axis_count",),
                                          "%s carries a bare number" % key)

    def test_the_medications_are_not_ordered_by_anything_meaningful(self):
        """Sorted by canonical key. Any other order is a ranking, whether or
        not anybody meant it as one."""
        result = self.world.evaluate(
            medications=[DRUG_2, UNKNOWN_DRUG, DRUG_1],
            phenotypes={GENE_1: "POOR"})
        keys = [item.medication.requested_value
                for item in result.medications]
        self.assertEqual(keys, sorted(keys))


class TestTheResultSaysWhatItIsNot(CoverageSafetyCase):

    def test_the_note_denies_being_an_attention_level(self):
        for code, result in self.results.items():
            with self.subTest(code=code.value):
                self.assertIn("not an attention level", result.note.lower())

    def test_the_note_survives_serialisation(self):
        payload = json.loads(json.dumps(self.covered.to_json()))
        self.assertIn("not an attention level", payload["note"].lower())

    def test_no_status_value_names_an_attention_level(self):
        from pgx.domain.enums import AttentionLevel
        coverage = {status.value for status in CoverageStatus}
        attention = {level.value for level in AttentionLevel}
        self.assertEqual(coverage & attention, set())


if __name__ == "__main__":
    unittest.main()
