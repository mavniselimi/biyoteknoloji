# -*- coding: utf-8 -*-
"""Deterministic value normalisation (WP-07).

The rules here decide what this project treats as the same string. Each test
below states not only what the rule does but which mistake it prevents, because
a normalisation rule that quietly did more than it claimed - stripping a salt,
repairing a typo - would be a scientific claim disguised as string cleaning.
"""

from __future__ import annotations

import unicodedata
import unittest

from pgx.normalization.errors import NormalizationError
from pgx.normalization.normalize import (ExternalIdentifier,
                                         NORMALIZATION_RULE_VERSION,
                                         normalize_drug_name,
                                         normalize_endpoint_container,
                                         normalize_external_id,
                                         normalize_gene_symbol)


class TestGeneSymbols(unittest.TestCase):

    def test_case_and_surrounding_whitespace_are_normalised(self):
        for raw in ("cyp2c19", "  CYP2C19 ", "Cyp2C19", "\tCYP2C19\n"):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_gene_symbol(raw), "CYP2C19")

    def test_internal_whitespace_is_collapsed_never_deleted(self):
        """Collapsing is not deleting.

        A symbol with an internal space is not a valid symbol. What matters is
        that it is *refused* rather than silently squashed into ``HLAB``, which
        would invent a symbol nobody wrote.
        """
        for raw in ("HLA B", "HLA  B", "CYP 2C19"):
            with self.subTest(raw=raw):
                with self.assertRaises(NormalizationError):
                    normalize_gene_symbol(raw)

    def test_compatibility_forms_are_folded(self):
        """NFKC, so a full-width or ligature spelling is the same symbol."""
        fullwidth = unicodedata.normalize("NFKD", "CYP2C19")
        self.assertEqual(normalize_gene_symbol(fullwidth), "CYP2C19")
        self.assertEqual(normalize_gene_symbol("ＣＹＰ２Ｃ１９"), "CYP2C19")

    def test_a_blank_symbol_is_refused_rather_than_returned_empty(self):
        for raw in ("", "   ", "\n"):
            with self.subTest(raw=raw):
                with self.assertRaises(NormalizationError):
                    normalize_gene_symbol(raw)

    def test_a_non_string_is_refused(self):
        for raw in (None, 42, [], {}):
            with self.subTest(raw=raw):
                with self.assertRaises(NormalizationError):
                    normalize_gene_symbol(raw)

    def test_an_unusable_symbol_is_refused_not_repaired(self):
        """No fuzzy repair. A value that is not a symbol raises."""
        for raw in ("CYP2C19!", "*CYP2C19", "cyp/2c19", "-CYP2C19"):
            with self.subTest(raw=raw):
                with self.assertRaises(NormalizationError):
                    normalize_gene_symbol(raw)

    def test_normalisation_is_idempotent(self):
        once = normalize_gene_symbol(" cyp2d6 ")
        self.assertEqual(normalize_gene_symbol(once), once)


class TestDrugNames(unittest.TestCase):

    def test_case_folding_is_locale_independent(self):
        self.assertEqual(normalize_drug_name("CLOPIDOGREL"), "clopidogrel")
        # casefold, not lower: the German sharp s and the Greek final sigma
        # are the cases where the two disagree.
        self.assertEqual(normalize_drug_name("STRASSE"), "strasse")
        self.assertEqual(normalize_drug_name("Straße"), "strasse")

    def test_salts_and_formulations_are_preserved(self):
        """Reducing both to 'metoprolol' would be a scientific claim."""
        self.assertEqual(normalize_drug_name("Metoprolol Tartrate"),
                         "metoprolol tartrate")
        self.assertEqual(normalize_drug_name("Metoprolol Succinate"),
                         "metoprolol succinate")
        self.assertNotEqual(normalize_drug_name("Metoprolol Tartrate"),
                            normalize_drug_name("Metoprolol"))

    def test_meaningful_punctuation_survives(self):
        self.assertEqual(normalize_drug_name("Trimethoprim/Sulfamethoxazole"),
                         "trimethoprim/sulfamethoxazole")
        self.assertEqual(normalize_drug_name("5-fluorouracil"), "5-fluorouracil")

    def test_internal_whitespace_is_collapsed(self):
        self.assertEqual(normalize_drug_name("acetyl   salicylic  acid"),
                         "acetyl salicylic acid")

    def test_a_blank_name_is_refused(self):
        with self.assertRaises(NormalizationError):
            normalize_drug_name("   ")


class TestContainerNames(unittest.TestCase):

    def test_case_variant_containers_fold_to_one_family(self):
        """This is what makes LEGACY-BUG-004 detectable."""
        self.assertEqual(normalize_endpoint_container("variantAnnotation"),
                         normalize_endpoint_container("VariantAnnotation"))
        self.assertEqual(normalize_endpoint_container("guidelineAnnotation"),
                         normalize_endpoint_container("GuidelineAnnotation"))

    def test_differently_named_containers_stay_apart(self):
        """'label' and 'DrugLabel' are not case variants of each other.

        Folding them would be a synonym claim, and this package makes none.
        """
        self.assertNotEqual(normalize_endpoint_container("label"),
                            normalize_endpoint_container("DrugLabel"))


class TestExternalIdentifiers(unittest.TestCase):

    def test_a_bare_value_is_never_compared_across_namespaces(self):
        left, _ = normalize_external_id("clinpgx", "PA124")
        right, _ = normalize_external_id("drugbank", "PA124")
        self.assertNotEqual(left, right)
        self.assertNotEqual(left.to_json(), right.to_json())

    def test_a_wellformed_identifier_reports_no_problem(self):
        for namespace, value in (("clinpgx", "PA124"), ("hgnc", "HGNC:2621"),
                                 ("rxnorm", "32968"), ("drugbank", "DB00758"),
                                 ("atc", "B01AC04")):
            with self.subTest(namespace=namespace):
                identifier, problem = normalize_external_id(namespace, value)
                self.assertIsNone(problem)
                self.assertEqual(identifier.namespace, namespace)

    def test_a_malformed_value_is_returned_with_its_problem_not_discarded(self):
        """A broken reference must not look like an absent one."""
        identifier, problem = normalize_external_id("clinpgx", "not-an-id")
        self.assertIsNotNone(problem)
        self.assertEqual(identifier.value, "not-an-id")

    def test_an_unknown_namespace_is_recorded_and_flagged_unchecked(self):
        identifier, problem = normalize_external_id("someregistry", "XYZ-1")
        self.assertEqual(identifier.namespace, "someregistry")
        self.assertIn("no validation rule", problem)

    def test_an_unusable_namespace_raises_rather_than_guessing(self):
        for namespace in ("", "  ", "9registry", "reg istry"):
            with self.subTest(namespace=namespace):
                with self.assertRaises(NormalizationError):
                    normalize_external_id(namespace, "PA124")

    def test_the_json_spelling_is_namespace_colon_value(self):
        identifier = ExternalIdentifier("clinpgx", "PA124")
        self.assertEqual(identifier.to_json(), "clinpgx:PA124")


class TestRuleVersion(unittest.TestCase):

    def test_the_rule_version_is_a_non_empty_string(self):
        """Recorded on every build, so two builds are only comparable when it
        matches. A blank version would make that check vacuous."""
        self.assertTrue(NORMALIZATION_RULE_VERSION.strip())
        self.assertIn("/", NORMALIZATION_RULE_VERSION)


if __name__ == "__main__":
    unittest.main()
