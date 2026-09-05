# -*- coding: utf-8 -*-
"""SAFETY-INV-004: RAPID must not implicitly match ULTRARAPID.

``LEGACY-BUG-001``. The safe control is exact membership, which is what the
engine does; the whole 6x6 phenotype matrix is swept in both directions,
because the legacy defect was *asymmetric* - ``"RAPID" in "ULTRARAPID"`` is
true and the reverse is not, so a one-directional test would have passed.
"""

from __future__ import annotations

import unittest

from pgx.domain.enums import Phenotype
from pgx.safety.controls import controls_for
from pgx.safety.evaluators import evaluate_phenotype_matching_is_exact
from pgx.safety.vocabulary import InvariantId
from tests.fixtures.wp20 import unsafe_matcher
from tests.unit.safety._support import phenotype_values, production_matcher


def _evaluate(matcher):
    return evaluate_phenotype_matching_is_exact(matcher, phenotype_values())


class TestExactMatchingIsSafe(unittest.TestCase):

    def setUp(self):
        self.verdict = _evaluate(production_matcher())

    def test_it_is_compliant(self):
        self.assertTrue(self.verdict.compliant, self.verdict.violations)

    def test_the_whole_matrix_was_swept(self):
        count = len(list(Phenotype))
        self.assertGreaterEqual(self.verdict.examined, count * count)

    def test_rapid_and_ultrarapid_do_not_match_each_other(self):
        match = production_matcher()
        self.assertFalse(match(Phenotype.RAPID, [Phenotype.ULTRARAPID]))
        self.assertFalse(match(Phenotype.ULTRARAPID, [Phenotype.RAPID]))

    def test_an_explicit_set_still_covers_both(self):
        """A rule may apply to two phenotypes - by saying so, not by accident."""
        match = production_matcher()
        both = [Phenotype.RAPID, Phenotype.ULTRARAPID]
        self.assertTrue(match(Phenotype.RAPID, both))
        self.assertTrue(match(Phenotype.ULTRARAPID, both))


class TestEveryNegativeControlIsDetected(unittest.TestCase):

    def test_each_over_matching_matcher_is_rejected(self):
        for control in controls_for(InvariantId.INV_004):
            with self.subTest(control=control.control_id):
                subject = unsafe_matcher.UNSAFE_SUBJECTS[control.control_id]
                verdict = _evaluate(subject)
                self.assertFalse(verdict.compliant,
                                 "%s was NOT detected" % control.control_id)
                self.assertEqual(verdict.refusal_code,
                                 "SAFETY_PHENOTYPE_CROSS_MATCH")

    def test_the_prefix_matcher_really_cross_matches(self):
        self.assertTrue(unsafe_matcher.prefix_matcher(
            Phenotype.RAPID, [Phenotype.ULTRARAPID]))

    def test_the_catalogue_and_the_fixtures_agree(self):
        declared = {c.control_id for c in controls_for(InvariantId.INV_004)}
        self.assertEqual(declared, set(unsafe_matcher.UNSAFE_SUBJECTS))

    def test_the_legacy_defect_is_mapped(self):
        controls = {c.control_id: c for c in controls_for(InvariantId.INV_004)}
        self.assertEqual(controls["NC-INV-004-PREFIX-MATCHER"].legacy_bug,
                         "LEGACY-BUG-001")
