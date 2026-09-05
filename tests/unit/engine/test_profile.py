# -*- coding: utf-8 -*-
"""The canonical phenotype profile (WP-12, section E).

A profile is the input side of an assessment made durable: sorted, immutable,
hashable, and complete. Complete is the word doing the work - a profile keeps
an explicit observation for every gene it was given, including the genes whose
values it could not interpret. A profile that quietly dropped those would look
like a profile with fewer genes rather than a profile with problems.

The hash tests are the ones a later work package will depend on. WP-14 will
pin an assessment to the profile it was computed from, and that pin is only
worth having if two runs over the same observations produce the same digest
regardless of dictionary order, display names or the whitespace somebody typed.
"""

from __future__ import annotations

import unittest

from pgx.domain.enums import Phenotype
from pgx.engine.phenotype_errors import PhenotypeProfileError
from pgx.engine.phenotype_normalization import normalize_profile
from tests.fixtures.wp12.synthetic import (SYNTHETIC_GENE, SYNTHETIC_GENE_2,
                                           profile)


class TestCanonicalOrderingAndCompleteness(unittest.TestCase):

    def test_observations_are_sorted_by_canonical_gene(self):
        built = normalize_profile({"TESTGENE9": "POOR", "TESTGENE1": "NORMAL",
                                   "TESTGENE5": "RAPID"})
        self.assertEqual(list(built.gene_keys), sorted(built.gene_keys))

    def test_input_order_does_not_change_the_profile(self):
        first = normalize_profile({"TESTGENE1": "POOR", "TESTGENE2": "NORMAL"})
        second = normalize_profile({"TESTGENE2": "NORMAL", "TESTGENE1": "POOR"})
        self.assertEqual(first.to_json()["observations"],
                         second.to_json()["observations"])
        self.assertEqual(first.content_hash(), second.content_hash())

    def test_every_supplied_gene_produces_an_observation(self):
        built = normalize_profile({"TESTGENE1": "POOR", "TESTGENE2": "",
                                   "TESTGENE3": "PM", "TESTGENE4": None,
                                   "TESTGENE5": "INDETERMINATE"})
        self.assertEqual(built.observation_count, 5)
        self.assertEqual({item.status for item in built.observations},
                         {"NORMALIZED", "MISSING", "UNSUPPORTED",
                          "INDETERMINATE"})

    def test_an_uninterpretable_gene_is_kept_not_dropped(self):
        """A profile that dropped it would look complete."""
        built = normalize_profile({"TESTGENE1": "POOR", "TESTGENE2": "PM"})
        observation = built.observation_for("GENE:TESTGENE2")
        self.assertIsNotNone(observation)
        self.assertEqual(observation.status, "UNSUPPORTED")

    def test_an_empty_profile_is_allowed_and_says_so(self):
        built = normalize_profile({})
        self.assertEqual(built.observation_count, 0)
        self.assertEqual(built.gene_keys, ())

    def test_a_gene_the_profile_never_mentions_reads_as_none(self):
        """Distinct from an observation whose status is MISSING: that one says
        somebody supplied the gene and left it blank."""
        built = normalize_profile({"TESTGENE1": "POOR"})
        self.assertIsNone(built.observation_for("GENE:TESTGENE9"))
        self.assertIsNotNone(built.observation_for("GENE:TESTGENE1"))


class TestDeterministicHashing(unittest.TestCase):

    def test_the_same_observations_hash_identically(self):
        self.assertEqual(profile().content_hash(), profile().content_hash())

    def test_whitespace_and_case_do_not_change_the_hash(self):
        first = normalize_profile({"TESTGENE1": "POOR"})
        second = normalize_profile({"TESTGENE1": "  poor  "})
        self.assertEqual(first.content_hash(), second.content_hash())

    def test_metadata_does_not_change_the_hash(self):
        """A profile's identity is what was observed, not what somebody
        called it."""
        first = normalize_profile({"TESTGENE1": "POOR"},
                                  metadata={"profile_name": "one"})
        second = normalize_profile({"TESTGENE1": "POOR"},
                                   metadata={"profile_name": "another",
                                             "demo_use": "a long note"})
        self.assertEqual(first.content_hash(), second.content_hash())

    def test_a_narrative_field_does_not_reach_the_hash_or_the_match(self):
        built = normalize_profile(
            {"TESTGENE1": "POOR"},
            metadata={"demo_use": "clinical narrative that must not matter"})
        self.assertNotIn("demo_use", str(built.semantic_content()))

    def test_the_profile_id_does_change_the_hash(self):
        """Two profiles observing the same phenotypes under different ids are
        different profiles: an assessment pinned to one must not verify
        against the other."""
        first = normalize_profile({"TESTGENE1": "POOR"}, profile_id="P1")
        second = normalize_profile({"TESTGENE1": "POOR"}, profile_id="P2")
        self.assertNotEqual(first.content_hash(), second.content_hash())

    def test_a_changed_phenotype_changes_the_hash(self):
        first = normalize_profile({"TESTGENE1": "POOR"})
        second = normalize_profile({"TESTGENE1": "NORMAL"})
        self.assertNotEqual(first.content_hash(), second.content_hash())

    def test_a_changed_failure_reason_changes_the_hash(self):
        """MISSING and UNSUPPORTED are different observations, so a profile
        containing one is not the profile containing the other."""
        first = normalize_profile({"TESTGENE1": None})
        second = normalize_profile({"TESTGENE1": "PM"})
        self.assertNotEqual(first.content_hash(), second.content_hash())


class TestDuplicateAndConflictingGenes(unittest.TestCase):

    def test_two_spellings_of_one_gene_are_refused(self):
        """Choosing either would invent an observation, and choosing the first
        would make the result depend on dictionary order."""
        with self.assertRaises(PhenotypeProfileError) as caught:
            normalize_profile({"CYP2D6": "POOR", "GENE:CYP2D6": "NORMAL"})
        self.assertEqual(caught.exception.code,
                         "PHENOTYPE_PROFILE_DUPLICATE_GENE")

    def test_duplicates_are_refused_even_when_the_values_agree(self):
        """Agreement is luck. The profile still states the gene twice, and a
        rule that silently accepted it would accept the disagreeing case the
        next time somebody edited one of the two."""
        with self.assertRaises(PhenotypeProfileError):
            normalize_profile({"cyp2d6": "POOR", "CYP2D6": "POOR"})

    def test_the_refusal_names_both_spellings(self):
        with self.assertRaises(PhenotypeProfileError) as caught:
            normalize_profile({"CYP2D6": "POOR", "cyp2d6 ": "NORMAL"})
        self.assertEqual(sorted(caught.exception.detail["spellings"]),
                         ["CYP2D6", "cyp2d6 "])

    def test_a_case_difference_alone_is_a_duplicate(self):
        with self.assertRaises(PhenotypeProfileError):
            normalize_profile({"testgene1": "POOR", "TESTGENE1": "RAPID"})


class TestPinnedGeneCatalogue(unittest.TestCase):

    def test_a_gene_in_the_catalogue_is_accepted(self):
        built = normalize_profile(
            {"TESTGENE1": "POOR"}, require_known_genes=True,
            known_gene_keys=["GENE:TESTGENE1", "GENE:TESTGENE2"])
        self.assertEqual(built.gene_keys, ("GENE:TESTGENE1",))

    def test_a_gene_outside_the_catalogue_is_refused(self):
        with self.assertRaises(PhenotypeProfileError) as caught:
            normalize_profile({"TESTGENE9": "POOR"}, require_known_genes=True,
                              known_gene_keys=["GENE:TESTGENE1"])
        self.assertEqual(caught.exception.code,
                         "PHENOTYPE_GENE_NOT_IN_CATALOGUE")

    def test_an_empty_catalogue_fails_closed(self):
        """An empty catalogue means no gene is known to exist. Passing
        everything would be the opposite of what was asked for."""
        for empty in ([], (), set(), None):
            with self.subTest(catalogue=repr(empty)):
                with self.assertRaises(PhenotypeProfileError) as caught:
                    normalize_profile({"TESTGENE1": "POOR"},
                                      require_known_genes=True,
                                      known_gene_keys=empty)
                self.assertEqual(caught.exception.code,
                                 "PHENOTYPE_CATALOGUE_EMPTY")

    def test_validation_is_off_unless_it_is_asked_for(self):
        built = normalize_profile({"TESTGENE9": "POOR"})
        self.assertEqual(built.gene_keys, ("GENE:TESTGENE9",))


class TestImmutability(unittest.TestCase):

    def test_a_profile_cannot_be_reassigned(self):
        built = profile()
        for attribute in ("observations", "profile_id",
                          "input_contract_version"):
            with self.subTest(attribute=attribute):
                with self.assertRaises(Exception):
                    setattr(built, attribute, None)

    def test_an_observation_cannot_be_reassigned(self):
        observation = profile().observations[0]
        with self.assertRaises(Exception):
            observation.phenotype = Phenotype.NORMAL

    def test_the_metadata_mapping_cannot_be_mutated(self):
        built = profile()
        with self.assertRaises(Exception):
            built.metadata["markers"] = []

    def test_mutating_the_source_mapping_does_not_change_the_profile(self):
        """The caller's dictionary is copied, so a profile cannot change
        under something that already read it."""
        raw = {"TESTGENE1": "POOR"}
        built = normalize_profile(raw)
        before = built.content_hash()
        raw["TESTGENE1"] = "NORMAL"
        raw["TESTGENE2"] = "RAPID"
        self.assertEqual(built.content_hash(), before)
        self.assertEqual(built.gene_keys, ("GENE:TESTGENE1",))
        self.assertIs(built.observations[0].phenotype, Phenotype.POOR)

    def test_the_frozen_view_is_deeply_immutable(self):
        frozen = profile().frozen()
        with self.assertRaises(Exception):
            frozen["profile_id"] = "something else"


class TestMalformedProfileInput(unittest.TestCase):

    def test_a_non_mapping_is_refused(self):
        for value in ([], "POOR", 42, None, ("TESTGENE1", "POOR")):
            with self.subTest(value=repr(value)):
                with self.assertRaises(PhenotypeProfileError):
                    normalize_profile(value)

    def test_an_unusable_gene_key_is_refused(self):
        for key in ("", "   ", "a gene name", "gene!"):
            with self.subTest(key=repr(key)):
                with self.assertRaises(PhenotypeProfileError):
                    normalize_profile({key: "POOR"})


if __name__ == "__main__":
    unittest.main()
