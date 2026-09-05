# -*- coding: utf-8 -*-
"""The condition language, and everything it refuses (WP-11, section A).

A rule condition is the narrowest thing in this system: one canonical gene,
one canonical drug, and phenotypes written out by name. Every test here exists
because the alternative is a rule whose scope nobody reviewed. A wildcard, a
default arm, a negation or a regular expression would each let one reviewed
sentence apply to cases no reviewer ever saw, and an executable expression
would let the condition mean something different tomorrow.

The refusals are asserted by *code*, not by message text: a test that matched
prose would pass after someone changed the rule and reworded the error.
"""

from __future__ import annotations

import unittest

from pgx.domain.enums import Phenotype
from pgx.rules.conditions import (CONDITION_KIND, CONDITION_SCHEMA_VERSION,
                                  PHENOTYPE_OPERATORS,
                                  PROHIBITED_CONDITION_CONSTRUCTS,
                                  RULE_PHENOTYPES, CanonicalAxis,
                                  PhenotypeMatch, RuleCondition,
                                  parse_condition)
from pgx.rules.errors import ConditionGrammarError
from tests.fixtures.wp11.synthetic import (SYNTHETIC_DRUG, SYNTHETIC_GENE,
                                           synthetic_condition)


def _document(**overrides):
    payload = {
        "condition_schema_version": CONDITION_SCHEMA_VERSION,
        "kind": CONDITION_KIND,
        "gene_id": SYNTHETIC_GENE,
        "drug_id": SYNTHETIC_DRUG,
        "phenotype": {"operator": "EXACT", "values": ["POOR"]},
    }
    payload.update(overrides)
    return payload


class TestOnlyTwoOperatorsExist(unittest.TestCase):

    def test_the_operator_list_is_exactly_exact_and_one_of(self):
        self.assertEqual(PHENOTYPE_OPERATORS, ("EXACT", "ONE_OF"))

    def test_exact_matches_exactly_one_value(self):
        match = PhenotypeMatch(operator="EXACT", values=(Phenotype.POOR,))
        self.assertEqual(match.values, (Phenotype.POOR,))

    def test_exact_refuses_a_second_value(self):
        with self.assertRaises(ConditionGrammarError) as caught:
            PhenotypeMatch(operator="EXACT",
                           values=(Phenotype.POOR, Phenotype.RAPID))
        self.assertEqual(caught.exception.code, "RULE_COND_EXACT_CARDINALITY")

    def test_one_of_requires_at_least_one_value(self):
        with self.assertRaises(ConditionGrammarError) as caught:
            PhenotypeMatch(operator="ONE_OF", values=())
        self.assertEqual(caught.exception.code, "RULE_COND_PHENOTYPE_EMPTY")

    def test_one_of_refuses_a_repeated_value(self):
        with self.assertRaises(ConditionGrammarError) as caught:
            PhenotypeMatch(operator="ONE_OF",
                           values=(Phenotype.POOR, Phenotype.POOR))
        self.assertEqual(caught.exception.code, "RULE_COND_PHENOTYPE_DUPLICATE")

    def test_an_unknown_operator_is_refused(self):
        for operator in ("MATCHES", "REGEX", "IN", "NOT", "ANY", "exact"):
            with self.subTest(operator=operator):
                with self.assertRaises(ConditionGrammarError) as caught:
                    PhenotypeMatch(operator=operator, values=(Phenotype.POOR,))
                self.assertEqual(caught.exception.code,
                                 "RULE_COND_OPERATOR_UNSUPPORTED")


class TestRapidIsNotUltrarapid(unittest.TestCase):
    """``SAFETY-INV-004``. The two are separate phenotypes and neither
    implies the other, so each must be written out to be matched."""

    def test_a_rule_on_rapid_expands_to_rapid_alone(self):
        condition = synthetic_condition(phenotypes=(Phenotype.RAPID,))
        self.assertEqual(tuple(axis.phenotype for axis in condition.expand()), (Phenotype.RAPID,))

    def test_a_rule_on_ultrarapid_expands_to_ultrarapid_alone(self):
        condition = synthetic_condition(phenotypes=(Phenotype.ULTRARAPID,))
        self.assertEqual(tuple(axis.phenotype for axis in condition.expand()),
                         (Phenotype.ULTRARAPID,))

    def test_matching_both_requires_naming_both(self):
        condition = synthetic_condition(
            operator="ONE_OF",
            phenotypes=(Phenotype.RAPID, Phenotype.ULTRARAPID))
        self.assertEqual({axis.phenotype for axis in condition.expand()},
                         {Phenotype.RAPID, Phenotype.ULTRARAPID})

    def test_no_operator_or_helper_expands_one_into_the_other(self):
        """Asserted over the whole vocabulary rather than one pair: any
        implicit widening at all would be found here."""
        for phenotype in RULE_PHENOTYPES:
            for operator in PHENOTYPE_OPERATORS:
                with self.subTest(phenotype=phenotype.value,
                                  operator=operator):
                    condition = synthetic_condition(operator=operator,
                                                    phenotypes=(phenotype,))
                    self.assertEqual(
                        tuple(axis.phenotype for axis in condition.expand()),
                        (phenotype,))


class TestIndeterminateIsNotARuleKey(unittest.TestCase):
    """``SAFETY-INV-001``. INDETERMINATE is the absence of a determination;
    a rule keyed on it would fire on missing data."""

    def test_indeterminate_is_not_in_the_rule_vocabulary(self):
        self.assertNotIn(Phenotype.INDETERMINATE, RULE_PHENOTYPES)

    def test_a_condition_on_indeterminate_is_refused(self):
        with self.assertRaises(ConditionGrammarError) as caught:
            PhenotypeMatch(operator="EXACT",
                           values=(Phenotype.INDETERMINATE,))
        self.assertEqual(caught.exception.code, "RULE_COND_PHENOTYPE_UNSUPPORTED")


class TestEveryProhibitedConstructIsRefused(unittest.TestCase):

    def test_the_prohibited_list_covers_the_named_categories(self):
        for construct in ("*", "ANY", "ALL", "DEFAULT", "NOT", "REGEX",
                          "RANGE", "BETWEEN", "LIKE", "EXPR", "EVAL", "SQL",
                          "TEMPLATE", "AND", "OR"):
            with self.subTest(construct=construct):
                self.assertIn(construct, PROHIBITED_CONDITION_CONSTRUCTS)

    def test_each_prohibited_construct_says_why_it_is_prohibited(self):
        for construct, reason in PROHIBITED_CONDITION_CONSTRUCTS.items():
            with self.subTest(construct=construct):
                self.assertGreater(len(reason), 20)

    def test_a_prohibited_construct_in_a_gene_field_is_refused(self):
        for construct in sorted(PROHIBITED_CONDITION_CONSTRUCTS):
            with self.subTest(construct=construct):
                with self.assertRaises(ConditionGrammarError):
                    parse_condition(_document(gene_id=construct))

    def test_a_wildcard_drug_is_refused(self):
        with self.assertRaises(ConditionGrammarError):
            parse_condition(_document(drug_id="*"))


class TestWhatAConditionDocumentMayContain(unittest.TestCase):

    def test_the_reference_document_parses(self):
        condition = parse_condition(_document())
        self.assertEqual(condition.gene_canonical_key, SYNTHETIC_GENE)
        self.assertEqual(condition.drug_canonical_key, SYNTHETIC_DRUG)
        self.assertEqual(tuple(axis.phenotype for axis in condition.expand()),
                         (Phenotype.POOR,))

    def test_an_unknown_key_is_refused(self):
        for key in ("unless", "population", "age_range", "note", "priority",
                    "when", "score"):
            with self.subTest(key=key):
                with self.assertRaises(ConditionGrammarError) as caught:
                    parse_condition(_document(**{key: "anything"}))
                self.assertEqual(caught.exception.code,
                                 "RULE_COND_UNKNOWN_KEY")

    def test_a_missing_key_is_refused(self):
        for key in ("kind", "gene_id", "drug_id", "phenotype"):
            with self.subTest(key=key):
                payload = _document()
                payload.pop(key)
                with self.assertRaises(ConditionGrammarError):
                    parse_condition(payload)

    def test_a_condition_naming_a_patient_field_is_refused(self):
        """Nothing in this system reads a patient record, so a condition that
        named one would be a rule that could never be evaluated honestly."""
        for field in ("age", "weight", "egfr", "creatinine", "pregnant",
                      "smoker", "diagnosis"):
            with self.subTest(field=field):
                with self.assertRaises(ConditionGrammarError):
                    parse_condition(_document(**{field: 42}))

    def test_natural_language_in_a_canonical_key_is_refused(self):
        for text in ("any hepatic gene", "CYP2D6 or CYP2C19",
                     "GENE:CYP2D6 unless elderly", "all SSRIs"):
            with self.subTest(text=text):
                with self.assertRaises(ConditionGrammarError):
                    parse_condition(_document(gene_id=text))

    def test_executable_text_in_a_canonical_key_is_refused(self):
        for text in ("__import__('os')", "1 == 1", "SELECT * FROM rules",
                     "{{ gene }}", "lambda x: True", "/^GENE:.*/"):
            with self.subTest(text=text):
                with self.assertRaises(ConditionGrammarError):
                    parse_condition(_document(gene_id=text))

    def test_a_condition_of_another_kind_is_refused(self):
        with self.assertRaises(ConditionGrammarError) as caught:
            parse_condition(_document(kind="PHENOCONVERSION"))
        self.assertEqual(caught.exception.code, "RULE_COND_KIND_UNSUPPORTED")

    def test_a_condition_of_another_schema_version_is_refused(self):
        with self.assertRaises(ConditionGrammarError):
            parse_condition(_document(
                condition_schema_version="pgx-rule-condition/2"))


class TestConditionsAreCanonicalAndComparable(unittest.TestCase):

    def test_value_order_does_not_change_the_document(self):
        first = synthetic_condition(
            operator="ONE_OF",
            phenotypes=(Phenotype.ULTRARAPID, Phenotype.POOR))
        second = synthetic_condition(
            operator="ONE_OF",
            phenotypes=(Phenotype.POOR, Phenotype.ULTRARAPID))
        self.assertEqual(first.to_json(), second.to_json())
        self.assertEqual(first.content_hash(), second.content_hash())

    def test_the_canonical_order_is_the_declared_vocabulary_order(self):
        condition = synthetic_condition(
            operator="ONE_OF", phenotypes=tuple(reversed(RULE_PHENOTYPES)))
        self.assertEqual(tuple(axis.phenotype for axis in condition.expand()),
                         RULE_PHENOTYPES)

    def test_a_document_round_trips(self):
        condition = synthetic_condition(operator="ONE_OF",
                                        phenotypes=(Phenotype.POOR,
                                                    Phenotype.RAPID))
        self.assertEqual(parse_condition(condition.to_json()).to_json(),
                         condition.to_json())

    def test_axes_sort_without_ordering_phenotypes(self):
        """``Phenotype`` refuses ``<`` on purpose - the values are a
        vocabulary, not a scale - so the axis sort key must not compare the
        enum members themselves."""
        axes = [CanonicalAxis(SYNTHETIC_GENE, SYNTHETIC_DRUG, phenotype)
                for phenotype in reversed(RULE_PHENOTYPES)]
        ordered = sorted(axes)
        self.assertEqual([axis.phenotype for axis in ordered],
                         list(RULE_PHENOTYPES))

    def test_comparing_two_phenotypes_directly_still_raises(self):
        with self.assertRaises(TypeError):
            Phenotype.POOR < Phenotype.RAPID  # noqa: B015


class TestRuleConditionIsImmutable(unittest.TestCase):

    def test_a_condition_cannot_be_reassigned(self):
        condition = synthetic_condition()
        with self.assertRaises(Exception):
            condition.gene_canonical_key = "GENE:OTHER"

    def test_the_frozen_view_is_deeply_immutable(self):
        frozen = synthetic_condition().frozen()
        with self.assertRaises(Exception):
            frozen["gene_id"] = "GENE:OTHER"


if __name__ == "__main__":
    unittest.main()
