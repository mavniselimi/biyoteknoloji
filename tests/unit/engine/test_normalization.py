# -*- coding: utf-8 -*-
"""The input boundary, and everything it refuses (WP-12, section A).

Version 1 of the contract accepts transport-level formatting differences and
nothing else. Every test below that asserts a refusal exists because the value
in question is *plausibly* mappable, and mapping it would be a scientific
claim about what somebody meant. ``PM`` almost certainly means poor
metaboliser. Guessing that here, with nobody having reviewed the vocabulary,
is how a rule ends up applied to an input its authors never saw.

The one that matters most is the last class: nothing here ever produces
``NORMAL`` for an input it did not recognise. Falling back to normal is the
false-reassurance failure mode in its purest form.
"""

from __future__ import annotations

import unittest

from pgx.domain.enums import Phenotype
from pgx.engine.phenotype_errors import PhenotypeProfileError
from pgx.engine.phenotype_models import NORMALIZATION_REASON_CODES
from pgx.engine.phenotype_normalization import (
    BROAD_FUNCTION_TOKENS, CANONICAL_PHENOTYPE_TOKENS, INPUT_CONTRACT_VERSION,
    SUPPORTED_INPUT_CONTRACT_VERSIONS, normalize_gene_key, normalize_phenotype)

GENE = "GENE:TESTGENE1"


def _observe(value):
    return normalize_phenotype(value, gene_canonical_key=GENE)


class TestTheContractIsVersioned(unittest.TestCase):

    def test_the_contract_names_a_version(self):
        self.assertEqual(INPUT_CONTRACT_VERSION, "pgx-phenotype-input/1")

    def test_every_observation_records_which_contract_read_it(self):
        self.assertEqual(_observe("POOR").input_contract_version,
                         INPUT_CONTRACT_VERSION)

    def test_a_contract_version_this_module_does_not_implement_is_refused(self):
        """Serving a version 2 document under version 1 rules would answer a
        question nobody asked."""
        with self.assertRaises(PhenotypeProfileError) as caught:
            normalize_phenotype("POOR", gene_canonical_key=GENE,
                                contract_version="pgx-phenotype-input/2")
        self.assertEqual(caught.exception.code,
                         "PHENOTYPE_CONTRACT_UNSUPPORTED")

    def test_only_one_version_is_implemented_today(self):
        self.assertEqual(SUPPORTED_INPUT_CONTRACT_VERSIONS,
                         (INPUT_CONTRACT_VERSION,))


class TestTheSixEnumValues(unittest.TestCase):

    def test_the_token_table_is_derived_from_the_enum(self):
        """Derived, not retyped: a seventh phenotype cannot appear in the enum
        and be missing here, or the reverse."""
        self.assertEqual(set(CANONICAL_PHENOTYPE_TOKENS),
                         {member.value for member in Phenotype})

    def test_the_five_determinate_values_normalize(self):
        for member in Phenotype:
            if member is Phenotype.INDETERMINATE:
                continue
            with self.subTest(phenotype=member.value):
                observation = _observe(member.value)
                self.assertEqual(observation.status, "NORMALIZED")
                self.assertIs(observation.phenotype, member)

    def test_indeterminate_is_its_own_status_not_a_phenotype(self):
        """A rule cannot be written about INDETERMINATE, so an observation
        must not be able to hand it to a matcher as a value."""
        observation = _observe("INDETERMINATE")
        self.assertEqual(observation.status, "INDETERMINATE")
        self.assertIsNone(observation.phenotype)
        self.assertEqual(observation.reason_code,
                         "PHENOTYPE_INPUT_INDETERMINATE")


class TestTransportLevelFormattingOnly(unittest.TestCase):

    def test_case_is_normalized(self):
        for spelling in ("POOR", "poor", "Poor", "pOoR"):
            with self.subTest(spelling=spelling):
                self.assertIs(_observe(spelling).phenotype, Phenotype.POOR)

    def test_surrounding_whitespace_is_trimmed(self):
        for spelling in (" POOR", "POOR ", "  poor  ", "\tPOOR\n"):
            with self.subTest(spelling=repr(spelling)):
                self.assertIs(_observe(spelling).phenotype, Phenotype.POOR)

    def test_internal_whitespace_is_not_repaired_into_a_token(self):
        """``ULTRA RAPID`` is not ``ULTRARAPID``. Removing an internal space
        is a guess about what somebody meant, not a formatting fix."""
        self.assertEqual(_observe("ULTRA RAPID").status, "UNSUPPORTED")


class TestMissingInput(unittest.TestCase):

    def test_none_is_missing(self):
        observation = _observe(None)
        self.assertEqual(observation.status, "MISSING")
        self.assertEqual(observation.reason_code, "PHENOTYPE_INPUT_MISSING")

    def test_an_empty_string_is_missing(self):
        for value in ("", "   ", "\t", "\n"):
            with self.subTest(value=repr(value)):
                self.assertEqual(_observe(value).status, "MISSING")

    def test_a_missing_value_carries_no_phenotype(self):
        self.assertIsNone(_observe(None).phenotype)


class TestUnsupportedInput(unittest.TestCase):

    ABBREVIATIONS = ("PM", "IM", "NM", "RM", "UM", "EM")
    ENGLISH_PROSE = ("poor metabolizer", "rapid metabolizer",
                     "intermediate metaboliser", "ultra-rapid",
                     "normal metabolizer", "likely poor metabolizer")
    OTHER_LANGUAGES = ("zayıf", "hızlı", "orta", "normal metabolizör")
    CLINICAL_PROSE = ("patient appears to be a poor metaboliser",
                      "reduced enzyme activity noted on assay",
                      "see attached report")

    def _refused(self, value, expected_code=None):
        observation = _observe(value)
        self.assertEqual(observation.status, "UNSUPPORTED",
                         "%r was accepted" % (value,))
        self.assertIsNone(observation.phenotype)
        if expected_code:
            self.assertEqual(observation.reason_code, expected_code)
        return observation

    def test_abbreviations_are_unsupported(self):
        for value in self.ABBREVIATIONS:
            with self.subTest(value=value):
                self._refused(value, "PHENOTYPE_INPUT_UNSUPPORTED")

    def test_english_metaboliser_prose_is_unsupported(self):
        for value in self.ENGLISH_PROSE:
            with self.subTest(value=value):
                self._refused(value)

    def test_other_language_terms_are_unsupported(self):
        """Not because they are wrong - because nobody has approved a
        vocabulary that says what they map to."""
        for value in self.OTHER_LANGUAGES:
            with self.subTest(value=value):
                self._refused(value)

    def test_clinical_prose_is_unsupported(self):
        for value in self.CLINICAL_PROSE:
            with self.subTest(value=value):
                self._refused(value)

    def test_broad_functional_groups_are_refused_with_their_own_code(self):
        for value in ("decreased_function", "decreased function",
                      "normal function", "no function", "reduced function",
                      "altered_function", "increased function"):
            with self.subTest(value=value):
                self._refused(value,
                              "PHENOTYPE_INPUT_BROAD_GROUP_NOT_ALLOWED")

    def test_every_broad_token_is_refused(self):
        for token in sorted(BROAD_FUNCTION_TOKENS):
            with self.subTest(token=token):
                self._refused(token,
                              "PHENOTYPE_INPUT_BROAD_GROUP_NOT_ALLOWED")

    def test_genotypes_and_star_alleles_are_refused_with_their_own_code(self):
        for value in ("*1/*2", "*4/*4", "CYP2D6*1/*1", "rs4244285",
                      "diplotype *1/*17", "haplotype B", "allele *3"):
            with self.subTest(value=value):
                self._refused(value,
                              "PHENOTYPE_INPUT_GENOTYPE_NOT_ALLOWED")

    def test_a_genotype_is_never_turned_into_a_phenotype(self):
        """Genotype-to-phenotype inference is an explicit non-goal of this
        work package and a prohibited P0 input."""
        for value in ("*1/*1", "*4/*4", "CYP2C19*2/*2"):
            with self.subTest(value=value):
                self.assertIsNone(_observe(value).phenotype)


class TestNonStringInput(unittest.TestCase):

    def test_numbers_are_unsupported_and_not_coerced(self):
        for value in (0, 1, 2, -1, 3.5):
            with self.subTest(value=value):
                observation = _observe(value)
                self.assertEqual(observation.status, "UNSUPPORTED")
                self.assertEqual(observation.reason_code,
                                 "PHENOTYPE_INPUT_INVALID_TYPE")

    def test_booleans_are_unsupported(self):
        for value in (True, False):
            with self.subTest(value=value):
                self.assertEqual(_observe(value).reason_code,
                                 "PHENOTYPE_INPUT_INVALID_TYPE")

    def test_lists_and_objects_are_unsupported(self):
        for value in ([], ["POOR"], {}, {"phenotype": "POOR"}, ("POOR",)):
            with self.subTest(value=repr(value)):
                self.assertEqual(_observe(value).reason_code,
                                 "PHENOTYPE_INPUT_INVALID_TYPE")

    def test_a_single_element_list_is_not_unwrapped(self):
        """Unwrapping would be a guess about the caller's intent, and the
        caller who meant a list of two would get the first silently."""
        self.assertIsNone(_observe(["POOR"]).phenotype)


class TestNoInexactMatchingOfAnyKind(unittest.TestCase):
    """Each of these is a technique the legacy normaliser uses, or one a
    later maintainer might reach for. None of them may accept a value."""

    def test_no_substring_matching(self):
        """Legacy ``normalize_profile_phenotype`` maps anything containing
        "poor" to poor, so ``"poor response"`` becomes a phenotype."""
        for value in ("poor response", "not poor", "poorly documented",
                      "normalish", "rapidly progressing", "ultrarapidly"):
            with self.subTest(value=value):
                self.assertEqual(_observe(value).status, "UNSUPPORTED")

    def test_no_prefix_matching(self):
        for value in ("POO", "POOR_", "NORM", "RAP", "ULTRA"):
            with self.subTest(value=value):
                self.assertEqual(_observe(value).status, "UNSUPPORTED")

    def test_no_edit_distance_repair(self):
        for value in ("POER", "POOOR", "NORMAK", "RAPIDD", "ULTARAPID"):
            with self.subTest(value=value):
                self.assertEqual(_observe(value).status, "UNSUPPORTED")

    def test_no_regex_interpretation_of_the_input(self):
        for value in ("^POOR$", "POOR|NORMAL", ".*", "[A-Z]+"):
            with self.subTest(value=value):
                self.assertEqual(_observe(value).status, "UNSUPPORTED")

    def test_nothing_unknown_ever_becomes_normal(self):
        """The failure this whole module exists to prevent."""
        for value in ("PM", "unknown", "n/a", "?", "-", "TBD", "pending",
                      "not tested", "wild type", "wt", 0, None, [], {}):
            with self.subTest(value=repr(value)):
                self.assertIsNot(_observe(value).phenotype, Phenotype.NORMAL)

    def test_no_unrecognised_value_produces_any_phenotype_at_all(self):
        for value in ("PM", "decreased_function", "*1/*2", "poor response",
                      42, True, ["POOR"]):
            with self.subTest(value=repr(value)):
                self.assertIsNone(_observe(value).phenotype)


class TestEveryReasonCodeIsDocumented(unittest.TestCase):

    def test_every_code_has_a_substantive_explanation(self):
        for code, meaning in NORMALIZATION_REASON_CODES.items():
            with self.subTest(code=code):
                self.assertGreater(len(meaning), 40)

    def test_every_code_a_failure_uses_is_documented(self):
        for value in (None, "", "INDETERMINATE", "PM", "decreased_function",
                      "*1/*2", 42, True, [], {}):
            observation = _observe(value)
            with self.subTest(value=repr(value)):
                self.assertIn(observation.reason_code,
                              NORMALIZATION_REASON_CODES)
                self.assertTrue(observation.reason)


class TestGeneKeyNormalization(unittest.TestCase):

    def test_a_bare_symbol_gets_the_canonical_prefix(self):
        self.assertEqual(normalize_gene_key("CYP2D6"), "GENE:CYP2D6")

    def test_an_already_prefixed_key_is_accepted(self):
        self.assertEqual(normalize_gene_key("GENE:CYP2D6"), "GENE:CYP2D6")

    def test_case_and_whitespace_are_normalized(self):
        for spelling in ("cyp2d6", " CYP2D6 ", "Cyp2D6", "gene:cyp2d6"):
            with self.subTest(spelling=spelling):
                self.assertEqual(normalize_gene_key(spelling), "GENE:CYP2D6")

    def test_punctuation_is_never_stripped(self):
        """``HLA-B`` and ``HLAB`` are different genes; WP-07 says so and this
        layer must not disagree."""
        self.assertEqual(normalize_gene_key("HLA-B"), "GENE:HLA-B")
        self.assertNotEqual(normalize_gene_key("HLA-B"),
                            normalize_gene_key("HLAB"))

    def test_an_unusable_gene_symbol_is_refused(self):
        for value in ("", "   ", None, 42, "a gene", "gene name!"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(PhenotypeProfileError):
                    normalize_gene_key(value)


if __name__ == "__main__":
    unittest.main()
