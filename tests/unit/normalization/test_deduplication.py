# -*- coding: utf-8 -*-
"""Duplicate detection that keeps every provenance link (WP-07).

Three relationships, three outcomes, and one rule that governs all of them:
nothing is ever discarded. A duplicate group exists to make a collapse
reversible, so a member that vanished here would defeat the point.
"""

from __future__ import annotations

import ast
import io
import os
import unittest

from pgx.normalization.dedup import (DEDUP_KEY_VERSION, RecordObservation,
                                     deduplicate)
from pgx.normalization.models import DuplicateClass

from tests.unit.normalization._support import REPO_ROOT, locator

DEDUP = os.path.join("pgx", "normalization", "dedup.py")


def _source(relative: str) -> str:
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


def observation(pointer, record_id="981351915", payload=None,
                spelling="variantAnnotation",
                semantic="CYP2C19::clopidogrel|variantannotation",
                record_type="pair_container_record"):
    return RecordObservation(
        record_type=record_type,
        source_record_id=record_id,
        semantic_key=semantic,
        payload=payload if payload is not None else {"id": 981351915, "x": 1},
        locator=locator(pointer=pointer,
                        artifact_path="responses/pair_probe_raw.json",
                        source_record_id=record_id),
        container_spelling=spelling)


class TestExactDuplicates(unittest.TestCase):

    def test_one_record_at_two_locators_with_one_spelling_is_exact(self):
        result = deduplicate([observation("/a"), observation("/b")])
        self.assertEqual(len(result.groups), 1)
        self.assertIs(result.groups[0].classification, DuplicateClass.EXACT)
        self.assertFalse(result.groups[0].blocking)

    def test_both_locators_survive(self):
        result = deduplicate([observation("/a"), observation("/b")])
        pointers = [member.locator.pointer for member in result.groups[0].members]
        self.assertEqual(pointers, ["/a", "/b"])


class TestSemanticDuplicates(unittest.TestCase):

    def test_one_record_under_two_container_spellings_is_semantic(self):
        """LEGACY-BUG-004, reduced to two records."""
        result = deduplicate([
            observation("/a", spelling="variantAnnotation"),
            observation("/b", spelling="VariantAnnotation"),
        ])
        self.assertEqual(len(result.groups), 1)
        self.assertIs(result.groups[0].classification, DuplicateClass.SEMANTIC)

    def test_it_names_both_spellings_and_says_the_payloads_match(self):
        result = deduplicate([
            observation("/a", spelling="variantAnnotation"),
            observation("/b", spelling="VariantAnnotation"),
        ])
        group = result.groups[0]
        self.assertEqual(group.container_spellings,
                         ("VariantAnnotation", "variantAnnotation"))
        self.assertIn("LEGACY-BUG-004", " ".join(group.differences))

    def test_a_semantic_duplicate_does_not_block(self):
        """The payloads are identical; nothing is in doubt."""
        result = deduplicate([
            observation("/a", spelling="variantAnnotation"),
            observation("/b", spelling="VariantAnnotation"),
        ])
        self.assertEqual(result.blocking_groups, ())


class TestConflictingIdentity(unittest.TestCase):

    def _conflict(self):
        return deduplicate([
            observation("/a", payload={"id": 1, "value": "left"}),
            observation("/b", payload={"id": 1, "value": "right"}),
        ])

    def test_one_identity_with_two_payloads_is_a_conflict_not_a_duplicate(self):
        result = self._conflict()
        self.assertIs(result.groups[0].classification,
                      DuplicateClass.CONFLICTING_IDENTITY)

    def test_a_conflict_always_blocks(self):
        self.assertEqual(len(self._conflict().blocking_groups), 1)

    def test_neither_record_is_discarded(self):
        """Discarding either would hide which of the two is wrong."""
        group = self._conflict().groups[0]
        self.assertEqual(group.member_count, 2)
        digests = {member.payload_digest for member in group.members}
        self.assertEqual(len(digests), 2)

    def test_it_states_what_differs(self):
        group = self._conflict().groups[0]
        self.assertTrue(group.differences)
        self.assertIn("different payloads", " ".join(group.differences))


class TestPairsAreNeverADedupKey(unittest.TestCase):

    def test_two_distinct_records_about_one_pair_stay_separate(self):
        """A CPIC and a DPWG guideline for one pair are two records.

        Deduplicating by gene/drug pair would delete real science.
        """
        result = deduplicate([
            observation("/a", record_id="PA166104948",
                        payload={"id": "PA166104948", "source": "CPIC"},
                        semantic="CYP2C19::clopidogrel|guidelineannotation"),
            observation("/b", record_id="PA166104777",
                        payload={"id": "PA166104777", "source": "DPWG"},
                        semantic="CYP2C19::clopidogrel|guidelineannotation"),
        ])
        self.assertEqual(result.groups, ())
        self.assertEqual(result.distinct_records, 2)

    def test_the_same_id_in_two_record_types_is_two_records(self):
        result = deduplicate([
            observation("/a", record_type="pair_container_record"),
            observation("/b", record_type="variant_annotation"),
        ])
        self.assertEqual(result.groups, ())


class TestRecordsWithoutAnIdentity(unittest.TestCase):

    def test_they_are_never_merged_on_content_alone(self):
        """Two equal payloads are not evidence of one record."""
        result = deduplicate([
            observation("/a", record_id=None),
            observation("/b", record_id=None),
        ])
        self.assertEqual(result.groups, ())
        self.assertEqual(len(result.unidentified), 2)

    def test_they_are_reported_separately_from_duplicates(self):
        result = deduplicate([observation("/a", record_id=None)])
        payload = result.to_json()
        self.assertEqual(payload["unidentified_observation_count"], 1)
        self.assertEqual(payload["group_count"], 0)


class TestDeterminism(unittest.TestCase):

    def _observations(self):
        return [observation("/c"), observation("/a"), observation("/b")]

    def test_input_order_does_not_change_the_output(self):
        forward = deduplicate(self._observations())
        backward = deduplicate(list(reversed(self._observations())))
        self.assertEqual([group.to_json() for group in forward.groups],
                         [group.to_json() for group in backward.groups])

    def test_the_representative_is_deterministic_not_preferential(self):
        """Smallest digest, chosen for stability rather than for quality."""
        result = deduplicate(self._observations())
        digests = sorted(member.payload_digest
                         for member in result.groups[0].members)
        self.assertEqual(result.groups[0].representative_digest, digests[0])

    def test_the_key_version_is_recorded_on_every_group(self):
        result = deduplicate([observation("/a"), observation("/b")])
        self.assertEqual(result.groups[0].dedup_key_version, DEDUP_KEY_VERSION)


class TestCountsAreDerived(unittest.TestCase):

    def test_duplicate_observations_is_computed_from_the_groups(self):
        result = deduplicate([observation("/a"), observation("/b"),
                              observation("/c")])
        self.assertEqual(result.duplicate_observations,
                         sum(group.member_count - 1 for group in result.groups))

    def test_the_totals_reconcile(self):
        result = deduplicate([observation("/a"), observation("/b"),
                              observation("/c", record_id=None)])
        self.assertEqual(
            result.total_observations,
            result.distinct_records + result.duplicate_observations)


class TestNoMergeOrDiscardCodeExists(unittest.TestCase):

    def test_the_module_defines_no_merge_or_drop_helper(self):
        tree = ast.parse(_source(DEDUP), filename=DEDUP)
        names = {node.name for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)}
        for forbidden in ("merge", "merge_payloads", "drop", "discard",
                          "prefer", "pick", "choose_best", "resolve_conflict"):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, names)

    def test_no_fuzzy_comparison_is_referenced(self):
        tree = ast.parse(_source(DEDUP), filename=DEDUP)
        identifiers = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                identifiers.add(node.attr)
            elif isinstance(node, ast.Import):
                identifiers.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                identifiers.add(node.module)
        for token in ("difflib", "SequenceMatcher", "get_close_matches",
                      "levenshtein", "fuzz", "rapidfuzz"):
            with self.subTest(token=token):
                self.assertNotIn(token, identifiers)


if __name__ == "__main__":
    unittest.main()
