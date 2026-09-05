# -*- coding: utf-8 -*-
"""SAFETY-INV-008: a conflict must not collapse into a reassuring result.

Conflict is information. When two validated rules disagree, that disagreement
is the case a clinician most needs to see - and it is where the software is
under the most pressure to produce something tidy.

All three mutants produce a *cleaner* answer than the truth, and each is the
kind of thing somebody writes for a defensible-sounding reason.
"""

from __future__ import annotations

import unittest

from pgx.safety.controls import controls_for
from pgx.safety.evaluators import evaluate_conflict_is_preserved
from pgx.safety.vocabulary import InvariantId
from tests.fixtures.wp20 import unsafe_conflict


def _evaluate(resolver):
    return evaluate_conflict_is_preserved(
        resolver, unsafe_conflict.conflict_groups(), unsafe_conflict.PRECEDENCE)


class TestDisagreementIsPreserved(unittest.TestCase):

    def setUp(self):
        self.verdict = _evaluate(unsafe_conflict.SAFE_SUBJECT)

    def test_it_is_compliant(self):
        self.assertTrue(self.verdict.compliant, self.verdict.violations)

    def test_the_conflict_surfaces_as_its_own_coverage_status(self):
        outcome = unsafe_conflict.SAFE_SUBJECT(
            unsafe_conflict.conflict_groups()[0])
        self.assertEqual(outcome["coverage"], "SOURCE_CONFLICT")

    def test_the_higher_level_is_kept(self):
        outcome = unsafe_conflict.SAFE_SUBJECT(
            unsafe_conflict.conflict_groups()[0])
        self.assertEqual(outcome["attention"], "HIGH")

    def test_every_disagreeing_finding_is_retained(self):
        for group in unsafe_conflict.conflict_groups():
            with self.subTest(size=len(group)):
                outcome = unsafe_conflict.SAFE_SUBJECT(group)
                self.assertEqual(len(outcome["retained"]), len(group))

    def test_the_engine_has_the_vocabulary_for_this(self):
        from pgx.domain.enums import CoverageReasonCode, CoverageStatus
        self.assertIn("SOURCE_CONFLICT", [c.value for c in CoverageStatus])
        self.assertIn("VALIDATED_RULES_CONFLICT",
                      [c.value for c in CoverageReasonCode])


class TestEveryNegativeControlIsDetected(unittest.TestCase):

    def test_each_collapsing_resolver_is_rejected(self):
        for control in controls_for(InvariantId.INV_008):
            with self.subTest(control=control.control_id):
                subject = unsafe_conflict.UNSAFE_SUBJECTS[control.control_id]
                verdict = _evaluate(subject)
                self.assertFalse(verdict.compliant,
                                 "%s was NOT detected" % control.control_id)
                self.assertEqual(verdict.refusal_code,
                                 "SAFETY_CONFLICT_COLLAPSED")

    def test_taking_the_lower_level_is_caught(self):
        verdict = _evaluate(unsafe_conflict.takes_lower_level)
        self.assertTrue(any("lower level" in v for v in verdict.violations),
                        verdict.violations)

    def test_averaging_is_caught_as_an_invented_finding(self):
        verdict = _evaluate(unsafe_conflict.averages_levels)
        self.assertFalse(verdict.compliant)

    def test_dropping_the_disagreeing_rule_is_caught(self):
        """The output looks like an ordinary single-rule result; nothing in it
        says a second validated rule disagreed."""
        verdict = _evaluate(unsafe_conflict.drops_conflicting_rule)
        self.assertTrue(any("retained" in v for v in verdict.violations),
                        verdict.violations)

    def test_the_catalogue_and_the_fixtures_agree(self):
        declared = {c.control_id for c in controls_for(InvariantId.INV_008)}
        self.assertEqual(declared, set(unsafe_conflict.UNSAFE_SUBJECTS))
