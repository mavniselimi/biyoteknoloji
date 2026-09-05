# -*- coding: utf-8 -*-
"""What a rule matches, and only that (WP-11, section B).

WP-11 does not evaluate anything against a patient - that is WP-12 - but it
does have to say precisely what a rule's condition denotes, because that is
what a reviewer approves. The denotation is checked here as a set of canonical
axes: the gene/drug/phenotype triples the rule covers, enumerated explicitly.

The single most important assertion in this file is that the set is never
larger than what was written. An implicit expansion - RAPID quietly covering
ULTRARAPID, a missing phenotype falling through to a default - would mean a
reviewer approved one sentence and the system executed another.
"""

from __future__ import annotations

import itertools
import unittest

from pgx.domain.enums import Phenotype
from pgx.rules.conditions import RULE_PHENOTYPES, CanonicalAxis
from tests.fixtures.wp11.synthetic import (SYNTHETIC_DRUG, SYNTHETIC_GENE,
                                           synthetic_condition,
                                           synthetic_rule)


class TestTheDenotationIsExactlyWhatWasWritten(unittest.TestCase):

    def test_an_exact_condition_denotes_one_axis(self):
        condition = synthetic_condition(phenotypes=(Phenotype.POOR,))
        self.assertEqual(
            condition.expand(),
            (CanonicalAxis(SYNTHETIC_GENE, SYNTHETIC_DRUG, Phenotype.POOR),))

    def test_a_one_of_condition_denotes_one_axis_per_named_value(self):
        values = (Phenotype.POOR, Phenotype.INTERMEDIATE)
        condition = synthetic_condition(operator="ONE_OF", phenotypes=values)
        self.assertEqual(len(condition.expand()), 2)
        self.assertEqual({axis.phenotype for axis in condition.expand()},
                         set(values))

    def test_no_condition_denotes_a_phenotype_it_did_not_name(self):
        """Over every subset of the vocabulary, so this cannot pass by
        coincidence on the one pair a reader happened to think of."""
        for size in (1, 2, 3):
            for values in itertools.combinations(RULE_PHENOTYPES, size):
                operator = "EXACT" if size == 1 else "ONE_OF"
                condition = synthetic_condition(operator=operator,
                                                phenotypes=values)
                covered = {axis.phenotype for axis in condition.expand()}
                with self.subTest(values=[v.value for v in values]):
                    self.assertEqual(covered, set(values))

    def test_every_axis_carries_the_rules_own_gene_and_drug(self):
        condition = synthetic_condition(operator="ONE_OF",
                                        phenotypes=RULE_PHENOTYPES)
        for axis in condition.expand():
            with self.subTest(phenotype=axis.phenotype.value):
                self.assertEqual(axis.gene_canonical_key, SYNTHETIC_GENE)
                self.assertEqual(axis.drug_canonical_key, SYNTHETIC_DRUG)

    def test_a_rules_axes_are_its_conditions_axes(self):
        definition = synthetic_rule(
            condition=synthetic_condition(operator="ONE_OF",
                                          phenotypes=(Phenotype.POOR,
                                                      Phenotype.RAPID)))
        self.assertEqual(definition.axes(), definition.condition.expand())


class TestThereIsNoDefaultArm(unittest.TestCase):
    """A phenotype nobody wrote a rule for is not covered by anything. The
    absence is the point: WP-12 must be able to report that nothing matched
    rather than inherit a fallback nobody reviewed."""

    def test_a_phenotype_outside_the_named_set_is_in_no_axis(self):
        condition = synthetic_condition(phenotypes=(Phenotype.POOR,))
        covered = {axis.phenotype for axis in condition.expand()}
        for phenotype in RULE_PHENOTYPES:
            if phenotype is Phenotype.POOR:
                continue
            with self.subTest(phenotype=phenotype.value):
                self.assertNotIn(phenotype, covered)

    def test_indeterminate_is_covered_by_no_condition_at_all(self):
        for operator, values in (("EXACT", (Phenotype.POOR,)),
                                 ("ONE_OF", RULE_PHENOTYPES)):
            condition = synthetic_condition(operator=operator,
                                            phenotypes=values)
            with self.subTest(operator=operator):
                self.assertNotIn(
                    Phenotype.INDETERMINATE,
                    {axis.phenotype for axis in condition.expand()})

    def test_a_different_gene_shares_no_axis(self):
        first = synthetic_condition()
        second = synthetic_condition(gene="GENE:TESTGENE2")
        self.assertEqual(set(first.expand()) & set(second.expand()), set())

    def test_a_different_drug_shares_no_axis(self):
        first = synthetic_condition()
        second = synthetic_condition(drug="DRUG:testdrug-beta")
        self.assertEqual(set(first.expand()) & set(second.expand()), set())


class TestRapidAndUltrarapidStaySeparate(unittest.TestCase):
    """``SAFETY-INV-004``, asserted at the level a rule is written."""

    def test_a_rapid_rule_covers_no_ultrarapid_axis(self):
        condition = synthetic_condition(phenotypes=(Phenotype.RAPID,))
        self.assertNotIn(Phenotype.ULTRARAPID,
                         {axis.phenotype for axis in condition.expand()})

    def test_an_ultrarapid_rule_covers_no_rapid_axis(self):
        condition = synthetic_condition(phenotypes=(Phenotype.ULTRARAPID,))
        self.assertNotIn(Phenotype.RAPID,
                         {axis.phenotype for axis in condition.expand()})

    def test_the_two_rules_are_different_rules(self):
        rapid = synthetic_rule(
            condition=synthetic_condition(phenotypes=(Phenotype.RAPID,)))
        ultra = synthetic_rule(
            condition=synthetic_condition(phenotypes=(Phenotype.ULTRARAPID,)))
        self.assertNotEqual(rapid.content_hash(), ultra.content_hash())
        self.assertEqual(set(rapid.axes()) & set(ultra.axes()), set())


class TestAxesAreDeterministicallyOrdered(unittest.TestCase):

    def test_the_axis_order_does_not_depend_on_how_values_were_written(self):
        forward = synthetic_condition(operator="ONE_OF",
                                      phenotypes=RULE_PHENOTYPES)
        backward = synthetic_condition(
            operator="ONE_OF", phenotypes=tuple(reversed(RULE_PHENOTYPES)))
        self.assertEqual(forward.expand(), backward.expand())

    def test_axes_sort_by_gene_then_drug_then_vocabulary_order(self):
        axes = [
            CanonicalAxis("GENE:TESTGENE2", SYNTHETIC_DRUG, Phenotype.POOR),
            CanonicalAxis(SYNTHETIC_GENE, SYNTHETIC_DRUG,
                          Phenotype.ULTRARAPID),
            CanonicalAxis(SYNTHETIC_GENE, SYNTHETIC_DRUG, Phenotype.POOR),
            CanonicalAxis(SYNTHETIC_GENE, "DRUG:testdrug-beta",
                          Phenotype.POOR),
        ]
        self.assertEqual(
            [(axis.gene_canonical_key, axis.drug_canonical_key,
              axis.phenotype.value) for axis in sorted(axes)],
            [(SYNTHETIC_GENE, SYNTHETIC_DRUG, "POOR"),
             (SYNTHETIC_GENE, SYNTHETIC_DRUG, "ULTRARAPID"),
             (SYNTHETIC_GENE, "DRUG:testdrug-beta", "POOR"),
             ("GENE:TESTGENE2", SYNTHETIC_DRUG, "POOR")])

    def test_the_sort_key_never_compares_phenotype_members(self):
        axis = CanonicalAxis(SYNTHETIC_GENE, SYNTHETIC_DRUG, Phenotype.POOR)
        for part in axis.sort_key():
            with self.subTest(part=part):
                self.assertNotIsInstance(part, Phenotype)


if __name__ == "__main__":
    unittest.main()
