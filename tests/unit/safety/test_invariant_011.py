# -*- coding: utf-8 -*-
"""SAFETY-INV-011: real patient or genomic data must not enter P0.

The safe control is the **shipped** prohibited-field walker,
``apps.api.contracts.validate.find_prohibited_fields``, which descends at any
depth.

The permitted direction matters as much as the prohibited one. ``CYP2D6`` is
public gene nomenclature and a drug name is a drug name; a detector that
refused those would make the product unusable for the thing it exists to do.
Both directions are swept.

Nothing in the fixtures is real. The prohibited payloads carry the *field
names* with the literal value ``"NEGATIVE-CONTROL"`` - no genotype, no person,
no laboratory result.
"""

from __future__ import annotations

import unittest

from pgx.safety.controls import controls_for
from pgx.safety.evaluators import evaluate_no_real_patient_data
from pgx.safety.vocabulary import InvariantId
from tests.fixtures.wp20 import unsafe_input
from tests.unit.safety._support import production_input_detector


def _evaluate(detector, payloads=None):
    return evaluate_no_real_patient_data(
        detector, payloads if payloads is not None
        else unsafe_input.payload_cases())


class TestTheShippedDetectorRefusesRealData(unittest.TestCase):

    def setUp(self):
        self.verdict = _evaluate(production_input_detector())

    def test_it_is_compliant(self):
        self.assertTrue(self.verdict.compliant, self.verdict.violations)

    def test_both_directions_were_swept(self):
        expected = {case[2] for case in unsafe_input.payload_cases()}
        self.assertEqual(expected, {True, False})

    def test_a_nested_genotype_field_is_found(self):
        """Four levels down, where a top-level scan misses it."""
        found = production_input_detector()(
            unsafe_input.nested_genotype_payload())
        self.assertTrue(found)

    def test_public_gene_nomenclature_is_not_patient_data(self):
        found = production_input_detector()(unsafe_input.permitted_payload())
        self.assertEqual(tuple(found), ())

    def test_pilot_mode_is_disabled(self):
        from pgx.domain.claims import (ModeNotEnabledError, OperationMode,
                                       is_mode_enabled, require_mode_enabled)
        self.assertFalse(is_mode_enabled(OperationMode.PILOT))
        with self.assertRaises(ModeNotEnabledError):
            require_mode_enabled(OperationMode.PILOT)

    def test_the_claim_scanner_carries_the_category(self):
        from pgx.domain.claims import ProhibitedClaimCategory
        self.assertIn("REAL_PATIENT_DATA",
                      [c.value for c in ProhibitedClaimCategory])

    def test_the_validation_case_schema_refuses_the_same_shapes(self):
        """WP-18's partition is the other input boundary, and it refuses the
        field rather than merely not listing it."""
        from pgx.validation.cases import PROHIBITED_CASE_FIELDS
        folded = {str(name).lower() for name in PROHIBITED_CASE_FIELDS}
        for field_name in ("patient_name", "vcf", "diplotype"):
            with self.subTest(field=field_name):
                self.assertIn(field_name, folded)


class TestEveryNegativeControlIsDetected(unittest.TestCase):

    def test_each_prohibited_payload_is_refused_by_the_real_detector(self):
        detect = production_input_detector()
        for control in controls_for(InvariantId.INV_011):
            if control.control_id == "NC-INV-011-PILOT-MODE-REQUESTED":
                continue        # a mode gate, not a field walk; see below
            with self.subTest(control=control.control_id):
                payload = unsafe_input.UNSAFE_SUBJECTS[control.control_id]()
                found = detect(payload)
                self.assertTrue(
                    found,
                    "%s: a prohibited real-data field was accepted"
                    % control.control_id)

    def test_pilot_mode_is_refused_by_the_mode_gate(self):
        from pgx.domain.claims import (ModeNotEnabledError, OperationMode,
                                       require_mode_enabled)
        payload = unsafe_input.pilot_mode_payload()
        with self.assertRaises(ModeNotEnabledError):
            require_mode_enabled(OperationMode(payload["mode"]))

    def test_a_top_level_only_detector_is_rejected(self):
        """The mutant is the detector: a walker that stops at depth one."""
        verdict = _evaluate(unsafe_input.top_level_only_detector)
        self.assertFalse(verdict.compliant)
        self.assertEqual(verdict.refusal_code, "SAFETY_REAL_PATIENT_DATA")
        self.assertTrue(any("nested-genotype" in v
                            for v in verdict.violations), verdict.violations)

    def test_an_over_refusing_detector_is_also_rejected(self):
        verdict = _evaluate(lambda payload: ("$.everything",))
        self.assertFalse(verdict.compliant)
        self.assertTrue(any("permitted input was refused" in v
                            for v in verdict.violations), verdict.violations)

    def test_the_catalogue_and_the_fixtures_agree(self):
        declared = {c.control_id for c in controls_for(InvariantId.INV_011)}
        self.assertEqual(declared, set(unsafe_input.UNSAFE_SUBJECTS))

    def test_no_fixture_carries_anything_that_looks_real(self):
        """The shapes are prohibited; the values are placeholders."""
        import json
        for name, build in unsafe_input.UNSAFE_SUBJECTS.items():
            rendered = json.dumps(build())
            with self.subTest(fixture=name):
                # No sequence coordinates, no allele strings, nothing that
                # could be mistaken for real genomic content.
                self.assertNotIn("chr", rendered.lower())
                self.assertNotIn("rs", rendered.lower().replace("_", ""))
                if name == "NC-INV-011-PILOT-MODE-REQUESTED":
                    # This one carries no prohibited *field* at all - it is a
                    # request for a disabled operating mode, refused by the
                    # mode gate rather than by the field walker.
                    self.assertEqual(build()["mode"], "PILOT")
                    continue
                self.assertIn("NEGATIVE-CONTROL", rendered)
