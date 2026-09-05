# -*- coding: utf-8 -*-
"""The legacy rule-candidate inventory (WP-11, section H).

The repository holds 1,559 legacy rule-like records. This inventory says what
they are and what would have to be true before any of them could become a
computable rule. It promotes nothing, and most of this file exists to keep it
that way.

The counts are asserted against the real repository rather than a fixture. If
they change, that is either a real change to the data or a defect, and either
way somebody should look - which is why the assertion is exact rather than
"greater than zero".
"""

from __future__ import annotations

import io
import json
import unittest

from pgx.rules.legacy import (INVENTORY_VERSION, LEGACY_BLOCKER_CODES,
                              build_inventory)
from tests.unit.rules._support import LEGACY_INVENTORY_JSON, REPO_ROOT

#: The state of the real repository, as reported by WP-08 and WP-10 and
#: re-derived here. Pinned exactly: a change is a fact about the data, not a
#: number to be relaxed until the test passes.
EXPECTED_CANDIDATES = 1559
EXPECTED_LINKED = 1526
EXPECTED_UNLINKED = 33


class TestTheInventoryMatchesTheRealRepository(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.inventory = build_inventory(REPO_ROOT)
        cls.counts = cls.inventory.counts()

    def test_every_legacy_work_item_is_inventoried(self):
        self.assertEqual(self.counts["candidates"], EXPECTED_CANDIDATES)

    def test_the_linked_and_unlinked_split_is_reported(self):
        self.assertEqual(self.counts["linked"], EXPECTED_LINKED)
        self.assertEqual(self.counts["unlinked"], EXPECTED_UNLINKED)
        self.assertEqual(self.counts["linked"] + self.counts["unlinked"],
                         self.counts["candidates"])

    def test_every_candidate_is_still_raw(self):
        self.assertEqual(self.counts["by_curation_status"],
                         {"RAW": EXPECTED_CANDIDATES})

    def test_not_one_candidate_is_eligible(self):
        self.assertEqual(self.counts["eligible_for_rule_creation"], 0)

    def test_no_rule_and_no_ruleset_came_out_of_this(self):
        self.assertEqual(self.counts["rules_created"], 0)
        self.assertEqual(self.counts["validated_rules"], 0)
        self.assertEqual(self.counts["frozen_rulesets"], 0)

    def test_every_candidate_carries_at_least_one_blocker(self):
        """Eligibility is not a stored field on the candidate - it is derived
        from the blockers, so a candidate cannot be marked eligible without
        the blockers actually being gone."""
        for candidate in self.inventory.candidates:
            with self.subTest(candidate=candidate.candidate_id):
                self.assertTrue(candidate.blocker_codes)
                self.assertFalse(
                    candidate.to_json()["eligible_for_rule_creation"])

    def test_every_blocker_used_is_a_documented_blocker(self):
        for code in self.counts["by_blocker_code"]:
            with self.subTest(code=code):
                self.assertIn(code, LEGACY_BLOCKER_CODES)

    def test_every_documented_blocker_says_what_it_means(self):
        for code, meaning in LEGACY_BLOCKER_CODES.items():
            with self.subTest(code=code):
                self.assertGreater(len(meaning), 30)

    def test_the_universal_blockers_apply_to_every_candidate(self):
        """Four things are wrong with every single candidate, and none of
        them is fixable by code: the protocol is unapproved, the dataset is
        unpublished, the evidence build is quarantined, and no curator has
        reached a conclusion."""
        for code in ("PROTOCOL_NOT_APPROVED", "DATASET_NOT_PUBLISHED",
                     "EVIDENCE_BUILD_QUARANTINED", "CURATION_NOT_CURATED"):
            with self.subTest(code=code):
                self.assertEqual(self.counts["by_blocker_code"][code],
                                 EXPECTED_CANDIDATES)


class TestTheInventoryPromotesNothing(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.inventory = build_inventory(REPO_ROOT)

    def test_assert_no_promotion_passes_on_the_real_data(self):
        self.inventory.assert_no_promotion()

    def test_no_candidate_carries_an_attention_level(self):
        """A legacy severity string is not an attention level, and there is
        no field here it could be written into."""
        for candidate in self.inventory.candidates[:50]:
            payload = candidate.to_json()
            with self.subTest(candidate=candidate.candidate_id):
                for absent in ("attention_level", "outcome", "severity",
                               "risk", "risk_level", "recommendation"):
                    self.assertNotIn(absent, payload)

    def test_legacy_clinical_text_stays_under_a_raw_prefix(self):
        for candidate in self.inventory.candidates[:50]:
            payload = candidate.to_json()
            with self.subTest(candidate=candidate.candidate_id):
                self.assertIn("raw_severity_text", payload)
                self.assertIn("raw_phenotype_text", payload)

    def test_a_raw_phenotype_string_is_never_a_canonical_phenotype(self):
        """``other`` and ``unknown`` are legacy vocabulary. Nothing maps them
        onto ``Phenotype``, because that mapping would be a scientific
        judgement made by a string comparison."""
        from pgx.domain.enums import Phenotype
        canonical = {member.value for member in Phenotype}
        for candidate in self.inventory.candidates:
            text = candidate.raw_phenotype_text
            if not text:
                continue
            with self.subTest(candidate=candidate.candidate_id):
                self.assertNotIn(text, canonical)

    def test_the_module_defines_no_promotion_helper(self):
        import pgx.rules.legacy as module
        for name in dir(module):
            lowered = name.lower()
            with self.subTest(name=name):
                self.assertFalse(lowered.startswith("promote"))
                self.assertFalse(lowered.startswith("convert_to_rule"))
                self.assertNotIn("bulk", lowered)


class TestThePublishedInventoryIsReproducible(unittest.TestCase):

    def test_the_published_file_matches_a_fresh_build(self):
        with io.open(LEGACY_INVENTORY_JSON, encoding="utf-8") as handle:
            published = json.load(handle)
        rebuilt = build_inventory(REPO_ROOT).to_json()
        self.assertEqual(published["content_hash"], rebuilt["content_hash"])
        self.assertEqual(published["counts"], rebuilt["counts"])

    def test_the_published_file_declares_its_version(self):
        with io.open(LEGACY_INVENTORY_JSON, encoding="utf-8") as handle:
            published = json.load(handle)
        self.assertEqual(published["inventory_version"], INVENTORY_VERSION)

    def test_the_published_file_states_its_promotion_policy(self):
        with io.open(LEGACY_INVENTORY_JSON, encoding="utf-8") as handle:
            published = json.load(handle)
        self.assertIn("creates no rule", published["promotion_policy"])
        self.assertIn("severity", published["promotion_policy"])

    def test_candidates_are_deterministically_ordered(self):
        first = build_inventory(REPO_ROOT).to_json()["candidates"]
        second = build_inventory(REPO_ROOT).to_json()["candidates"]
        self.assertEqual([item["candidate_id"] for item in first],
                         [item["candidate_id"] for item in second])

    def test_candidates_are_ordered_by_gene_then_drug_then_identity(self):
        """Sorted by what a reader looks things up by, not by identity: an
        inventory ordered by opaque id is one nobody can scan."""
        candidates = build_inventory(REPO_ROOT).candidates
        self.assertEqual(list(candidates),
                         sorted(candidates, key=lambda item: item.sort_key()))


class TestTheInventoryIsNotAnExecutableSource(unittest.TestCase):

    def test_no_rules_module_reads_the_inventory_to_build_a_rule(self):
        """The builder takes definitions, never a legacy file. A path from
        this inventory into a ruleset would be the bulk promotion WP-11 is
        forbidden from performing."""
        from tests.unit.rules._support import RULES_DIR, imports_of
        import os
        for module in ("builder.py", "registry.py", "validator.py",
                       "models.py", "conditions.py"):
            imported = imports_of(os.path.join(RULES_DIR, module))
            with self.subTest(module=module):
                self.assertNotIn("pgx.rules.legacy", imported)


if __name__ == "__main__":
    unittest.main()
