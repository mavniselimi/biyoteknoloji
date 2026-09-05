# -*- coding: utf-8 -*-
"""The exact-match truth matrix (WP-12, sections B and C).

Every phenotype against every ``EXACT`` rule phenotype, exhaustively, plus
``INDETERMINATE`` against all of them. Thirty-six cases, five of which match.

Exhaustive rather than illustrative on purpose. A hand-picked set of cases
proves that the pairs somebody thought of behave correctly; this proves that
no pair anybody did *not* think of behaves incorrectly, which is the property
``SAFETY-INV-004`` actually needs.
"""

from __future__ import annotations

import itertools
import unittest

from pgx.domain.enums import Phenotype
from pgx.engine.phenotype import match_observation, truth_matrix
from pgx.engine.phenotype_models import MATCH_STATUSES
from pgx.rules.conditions import RULE_PHENOTYPES
from tests.fixtures.wp12.synthetic import DETERMINATE, exact, observation, one_of


class TestEveryExactPair(unittest.TestCase):

    def test_every_determinate_pair_matches_only_itself(self):
        for observed in DETERMINATE:
            for declared in RULE_PHENOTYPES:
                with self.subTest(observed=observed.value,
                                  declared=declared.value):
                    decision = match_observation(observation(observed.value),
                                                 exact(declared))
                    if observed is declared:
                        self.assertEqual(decision.status, "MATCH")
                        self.assertTrue(decision.matched)
                    else:
                        self.assertEqual(decision.status, "NO_MATCH")
                        self.assertFalse(decision.matched)

    def test_exactly_five_of_the_twenty_five_pairs_match(self):
        matches = sum(
            1 for observed in DETERMINATE for declared in RULE_PHENOTYPES
            if match_observation(observation(observed.value),
                                 exact(declared)).matched)
        self.assertEqual(matches, len(DETERMINATE))

    def test_indeterminate_matches_no_rule_phenotype(self):
        for declared in RULE_PHENOTYPES:
            with self.subTest(declared=declared.value):
                decision = match_observation(observation("INDETERMINATE"),
                                             exact(declared))
                self.assertEqual(decision.status, "INPUT_INDETERMINATE")
                self.assertFalse(decision.matched)

    def test_the_matrix_covers_every_phenotype_in_the_enum(self):
        rows = truth_matrix()
        self.assertEqual({row["observed"] for row in rows},
                         {member.value for member in Phenotype})
        self.assertEqual(len(rows), len(Phenotype) * len(RULE_PHENOTYPES))

    def test_the_published_matrix_agrees_with_the_matcher(self):
        """The table the CLI and the documentation print is the table the
        matcher actually implements, not a description of it."""
        for row in truth_matrix():
            decision = match_observation(observation(row["observed"]),
                                         exact(Phenotype(row["declared"][0])))
            with self.subTest(observed=row["observed"],
                              declared=row["declared"]):
                self.assertEqual(decision.status, row["expected_status"])


class TestOneOfMatchesOnlyWhatItLists(unittest.TestCase):

    def test_a_one_of_matches_each_listed_phenotype(self):
        listed = (Phenotype.POOR, Phenotype.INTERMEDIATE)
        for observed in listed:
            with self.subTest(observed=observed.value):
                self.assertEqual(
                    match_observation(observation(observed.value),
                                      one_of(*listed)).status, "MATCH")

    def test_a_one_of_matches_nothing_it_did_not_list(self):
        listed = (Phenotype.POOR, Phenotype.INTERMEDIATE)
        for observed in DETERMINATE:
            if observed in listed:
                continue
            with self.subTest(observed=observed.value):
                self.assertEqual(
                    match_observation(observation(observed.value),
                                      one_of(*listed)).status, "NO_MATCH")

    def test_every_subset_matches_exactly_its_members(self):
        """Over every subset of the vocabulary, so this cannot pass by
        coincidence on the one combination a reader thought of."""
        for size in (1, 2, 3, 4, 5):
            for listed in itertools.combinations(RULE_PHENOTYPES, size):
                match = one_of(*listed) if size > 1 else exact(listed[0])
                for observed in DETERMINATE:
                    expected = "MATCH" if observed in listed else "NO_MATCH"
                    with self.subTest(listed=[p.value for p in listed],
                                      observed=observed.value):
                        self.assertEqual(
                            match_observation(observation(observed.value),
                                              match).status, expected)

    def test_declaration_order_does_not_change_the_answer(self):
        forward = one_of(Phenotype.POOR, Phenotype.ULTRARAPID)
        backward = one_of(Phenotype.ULTRARAPID, Phenotype.POOR)
        for observed in DETERMINATE:
            with self.subTest(observed=observed.value):
                self.assertEqual(
                    match_observation(observation(observed.value),
                                      forward).status,
                    match_observation(observation(observed.value),
                                      backward).status)


class TestRapidIsNotUltrarapid(unittest.TestCase):
    """``SAFETY-INV-004`` and ``LEGACY-BUG-001``, as executable evidence.

    The legacy matcher answers True to the second and fourth cases below,
    because ``PROFILE_MATCH_GROUPS`` lists each phenotype in the other's set.
    """

    def test_rapid_matches_exact_rapid(self):
        self.assertEqual(
            match_observation(observation("RAPID"),
                              exact(Phenotype.RAPID)).status, "MATCH")

    def test_rapid_does_not_match_exact_ultrarapid(self):
        self.assertEqual(
            match_observation(observation("RAPID"),
                              exact(Phenotype.ULTRARAPID)).status, "NO_MATCH")

    def test_ultrarapid_matches_exact_ultrarapid(self):
        self.assertEqual(
            match_observation(observation("ULTRARAPID"),
                              exact(Phenotype.ULTRARAPID)).status, "MATCH")

    def test_ultrarapid_does_not_match_exact_rapid(self):
        self.assertEqual(
            match_observation(observation("ULTRARAPID"),
                              exact(Phenotype.RAPID)).status, "NO_MATCH")

    def test_a_one_of_naming_both_matches_both(self):
        both = one_of(Phenotype.RAPID, Phenotype.ULTRARAPID)
        for observed in (Phenotype.RAPID, Phenotype.ULTRARAPID):
            with self.subTest(observed=observed.value):
                self.assertEqual(
                    match_observation(observation(observed.value),
                                      both).status, "MATCH")

    def test_a_one_of_naming_only_one_matches_only_that_one(self):
        for listed, other in ((Phenotype.RAPID, Phenotype.ULTRARAPID),
                              (Phenotype.ULTRARAPID, Phenotype.RAPID)):
            match = one_of(listed, Phenotype.POOR)
            with self.subTest(listed=listed.value):
                self.assertEqual(
                    match_observation(observation(listed.value),
                                      match).status, "MATCH")
                self.assertEqual(
                    match_observation(observation(other.value),
                                      match).status, "NO_MATCH")

    def test_the_two_phenotypes_cannot_be_ordered(self):
        """Ordering would invite "at least as fast as", which the vocabulary
        does not claim."""
        with self.assertRaises(TypeError):
            sorted([Phenotype.RAPID, Phenotype.ULTRARAPID])


class TestTheDecisionVocabularyIsClosed(unittest.TestCase):

    def test_the_five_statuses(self):
        self.assertEqual(MATCH_STATUSES,
                         ("MATCH", "NO_MATCH", "INPUT_MISSING",
                          "INPUT_INDETERMINATE", "INPUT_UNSUPPORTED"))

    def test_only_match_counts_as_matched(self):
        for value, expected in (("POOR", True), ("NORMAL", False),
                                (None, False), ("INDETERMINATE", False),
                                ("PM", False)):
            with self.subTest(value=repr(value)):
                decision = match_observation(observation(value),
                                             exact(Phenotype.POOR))
                self.assertEqual(decision.matched, expected)


if __name__ == "__main__":
    unittest.main()
