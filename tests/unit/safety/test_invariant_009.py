# -*- coding: utf-8 -*-
"""SAFETY-INV-009: development and holdout partitions must not overlap.

The safe control is WP-18's **real** ``audit_partition``, so a regression in
shipped separation logic fails here.

Three ways a partition leaks, and they need three different checks - which is
the point of the mutants. An identifier check misses two copies of one case
under different IDs; a content check misses two *different* cases derived from
one source. The third leak is invisible to both.
"""

from __future__ import annotations

import unittest

from pgx.safety.controls import controls_for
from pgx.safety.evaluators import evaluate_partition_separation
from pgx.safety.vocabulary import InvariantId
from tests.fixtures.wp18 import synthetic as wp18
from tests.fixtures.wp20 import unsafe_partition
from tests.unit.safety._support import production_partition_auditor


def _case_sets():
    """``(label, cases, expected_clean)`` - one clean set and three leaks."""
    clean = [wp18.development_case("PGX-VAL-DEV-CLEAN-1"),
             wp18.internal_holdout_case("PGX-VAL-INT-CLEAN-1")]

    same_id = [wp18.development_case("PGX-VAL-DEV-SHARED-1"),
               wp18.internal_holdout_case("PGX-VAL-DEV-SHARED-1")]

    # Identical content under two identifiers, one each side of the line.
    shared_body = wp18.content()
    duplicated = [
        wp18.development_case("PGX-VAL-DEV-DUP-1", body=shared_body),
        wp18.internal_holdout_case("PGX-VAL-INT-DUP-1", body=shared_body),
    ]

    # Different content, same derivation family: two cases built from one
    # source by one method. Neither an identifier nor a content check sees it.
    family = "SHARED-DERIVATION-SOURCE/1"
    split_family = [
        wp18.development_case(
            "PGX-VAL-DEV-FAM-1",
            prov=wp18.provenance(development=True, source=family)),
        wp18.internal_holdout_case(
            "PGX-VAL-INT-FAM-1",
            prov=wp18.provenance(development=False, source=family)),
    ]

    return (
        ("clean/separated", clean, True),
        ("leak/same-identifier", same_id, False),
        ("leak/duplicate-content", duplicated, False),
        ("leak/split-derivation-family", split_family, False),
    )


class TestTheShippedAuditorSeparates(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.sets = _case_sets()
        cls.verdict = evaluate_partition_separation(
            production_partition_auditor(), cls.sets)

    def test_it_is_compliant(self):
        self.assertTrue(self.verdict.compliant, self.verdict.violations)

    def test_all_four_sets_were_examined(self):
        self.assertEqual(self.verdict.examined, 4)

    def test_a_correctly_separated_set_is_not_flagged(self):
        """An auditor that flagged everything would be useless in the other
        direction, and would be switched off."""
        audit = production_partition_auditor()(list(self.sets[0][1]))
        self.assertTrue(audit.is_clean)

    def test_each_leak_is_caught_by_the_real_auditor(self):
        for label, cases, expected_clean in self.sets[1:]:
            with self.subTest(label=label):
                audit = production_partition_auditor()(list(cases))
                self.assertFalse(audit.is_clean)


class TestEveryNegativeControlIsDetected(unittest.TestCase):
    """Each weakened auditor misses exactly one kind of leak."""

    @classmethod
    def setUpClass(cls):
        cls.sets = _case_sets()

    def _evaluate(self, auditor):
        return evaluate_partition_separation(auditor, self.sets)

    def test_each_weakened_auditor_is_rejected(self):
        for control in controls_for(InvariantId.INV_009):
            with self.subTest(control=control.control_id):
                subject = unsafe_partition.UNSAFE_SUBJECTS[control.control_id]
                verdict = self._evaluate(subject)
                self.assertFalse(verdict.compliant,
                                 "%s was NOT detected" % control.control_id)
                self.assertEqual(verdict.refusal_code,
                                 "SAFETY_PARTITION_OVERLAP")

    def test_an_identifier_only_auditor_misses_duplicate_content(self):
        verdict = self._evaluate(unsafe_partition.identifier_only_auditor)
        self.assertTrue(
            any("duplicate-content" in v for v in verdict.violations),
            verdict.violations)

    def test_a_content_auditor_still_misses_a_split_family(self):
        """Neither an identifier nor a content check can see this one, and it
        leaks the source just as thoroughly."""
        verdict = self._evaluate(
            unsafe_partition.content_blind_to_family_auditor)
        self.assertTrue(
            any("derivation-family" in v for v in verdict.violations),
            verdict.violations)

    def test_the_catalogue_and_the_fixtures_agree(self):
        declared = {c.control_id for c in controls_for(InvariantId.INV_009)}
        self.assertEqual(declared, set(unsafe_partition.UNSAFE_SUBJECTS))

    def test_no_wp21_metric_is_computed_here(self):
        """WP-20 checks separation. It does not calculate a rate, and must not
        start pooling denominators to do so."""
        import ast
        import inspect

        from pgx.safety import evaluators

        tree = ast.parse(inspect.getsource(evaluators))
        names = {node.name.lower() for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)}
        for forbidden in ("sensitivity", "specificity", "concordance",
                          "precision", "recall"):
            self.assertFalse(any(forbidden in name for name in names))
