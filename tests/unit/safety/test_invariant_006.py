# -*- coding: utf-8 -*-
"""SAFETY-INV-006: every finding carries resolvable, pinned evidence.

``LEGACY-BUG-005``: legacy attached evidence strength to the existence of a
drug-gene pair rather than to a specific interpretation. Without a resolvable
citation an "explainable" output is an assertion with a footnote shape.

Three ways the chain breaks, and the third is the one a naive check misses: an
evidence reference that resolves perfectly - into a dataset version this
release never pinned.
"""

from __future__ import annotations

import unittest

from pgx.safety.controls import controls_for
from pgx.safety.evaluators import evaluate_findings_are_evidence_backed
from pgx.safety.vocabulary import InvariantId
from tests.fixtures.wp20 import unsafe_evidence


def _evaluate(emitter):
    return evaluate_findings_are_evidence_backed(
        emitter, unsafe_evidence.candidate_findings(),
        unsafe_evidence.evidence_index(), unsafe_evidence.PINNED_DATASET)


class TestOnlyEvidenceBackedFindingsSurvive(unittest.TestCase):

    def setUp(self):
        self.verdict = _evaluate(unsafe_evidence.SAFE_SUBJECT)

    def test_it_is_compliant(self):
        self.assertTrue(self.verdict.compliant, self.verdict.violations)

    def test_the_good_finding_is_kept(self):
        """Degrading coverage is the correct response to a broken chain -
        dropping every finding is not."""
        kept = unsafe_evidence.SAFE_SUBJECT(
            unsafe_evidence.candidate_findings(),
            unsafe_evidence.evidence_index())
        self.assertEqual([f["finding_id"] for f in kept], ["F-OK"])

    def test_the_coverage_reason_exists_for_this_case(self):
        """The engine has a controlled reason code for it, so the degradation
        is reportable rather than silent."""
        from pgx.domain.enums import CoverageReasonCode
        self.assertIn("EVIDENCE_REFERENCE_MISSING",
                      [c.value for c in CoverageReasonCode])


class TestEveryNegativeControlIsDetected(unittest.TestCase):

    def test_each_permissive_emitter_is_rejected(self):
        for control in controls_for(InvariantId.INV_006):
            with self.subTest(control=control.control_id):
                subject = unsafe_evidence.UNSAFE_SUBJECTS[control.control_id]
                verdict = _evaluate(subject)
                self.assertFalse(verdict.compliant,
                                 "%s was NOT detected" % control.control_id)
                self.assertEqual(verdict.refusal_code,
                                 "SAFETY_EVIDENCE_NOT_RESOLVABLE")

    def test_a_dangling_reference_is_caught(self):
        verdict = _evaluate(unsafe_evidence.emits_dangling_reference)
        self.assertTrue(any("resolves to nothing" in v
                            for v in verdict.violations), verdict.violations)

    def test_evidence_from_another_dataset_version_is_caught(self):
        """Every reference resolves. It resolves into the wrong data."""
        verdict = _evaluate(
            unsafe_evidence.emits_evidence_from_another_dataset)
        self.assertTrue(any("not the pinned" in v for v in verdict.violations),
                        verdict.violations)

    def test_the_catalogue_and_the_fixtures_agree(self):
        declared = {c.control_id for c in controls_for(InvariantId.INV_006)}
        self.assertEqual(declared, set(unsafe_evidence.UNSAFE_SUBJECTS))

    def test_the_legacy_defect_is_mapped(self):
        controls = {c.control_id: c for c in controls_for(InvariantId.INV_006)}
        self.assertEqual(
            controls["NC-INV-006-DANGLING-EVIDENCE-REFERENCE"].legacy_bug,
            "LEGACY-BUG-005")
