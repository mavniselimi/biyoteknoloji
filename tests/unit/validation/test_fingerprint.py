# -*- coding: utf-8 -*-
"""Canonical fingerprints: what counts as the same case (WP-18).

Two failure modes, and they are not symmetric.

A **false distinction** - one case hashing two ways - lets a copy slip across
the partition and inflates a denominator. Every normalisation rule here exists
to remove one.

A **false collapse** - two cases hashing alike - hides a case entirely: the
second one silently disappears from a set somebody believes they have. That is
worse, and it is why the order-insensitive treatment is applied to three named
fields rather than to every list.

Both directions are tested, and the second half of this module is the more
important one.
"""

from __future__ import annotations

import unicodedata
import unittest

from pgx.validation.errors import FingerprintError
from pgx.validation.fingerprint import (CONTENT_FINGERPRINT_VERSION,
                                        ORDER_INSENSITIVE_FIELDS,
                                        canonical_content, content_fingerprint,
                                        derivation_family_fingerprint,
                                        normalise_text)


class TestItIgnoresWhatCarriesNoMeaning(unittest.TestCase):

    BASE = {"observations": [{"gene": "GENE:TESTGENE1", "value": "POOR"},
                             {"gene": "GENE:TESTGENE2", "value": "NORMAL"}],
            "medications": ["DRUG:testdrug-alpha", "DRUG:testdrug-beta"],
            "context": "a synthetic vignette"}

    def test_key_order_does_not_change_it(self):
        reordered = {"context": self.BASE["context"],
                     "medications": list(self.BASE["medications"]),
                     "observations": list(self.BASE["observations"])}
        self.assertEqual(content_fingerprint(self.BASE),
                         content_fingerprint(reordered))

    def test_observation_order_does_not_change_it(self):
        """A profile is a set of statements, not a sequence."""
        swapped = dict(self.BASE,
                       observations=list(reversed(self.BASE["observations"])))
        self.assertEqual(content_fingerprint(self.BASE),
                         content_fingerprint(swapped))

    def test_medication_order_does_not_change_it(self):
        swapped = dict(self.BASE,
                       medications=list(reversed(self.BASE["medications"])))
        self.assertEqual(content_fingerprint(self.BASE),
                         content_fingerprint(swapped))

    def test_nested_key_order_does_not_change_it(self):
        flipped = dict(self.BASE, observations=[
            {"value": "POOR", "gene": "GENE:TESTGENE1"},
            {"value": "NORMAL", "gene": "GENE:TESTGENE2"}])
        self.assertEqual(content_fingerprint(self.BASE),
                         content_fingerprint(flipped))

    def test_unicode_form_does_not_change_it(self):
        """The same Turkish string typed two ways is one string."""
        composed = unicodedata.normalize("NFC", "kısa açıklama")
        decomposed = unicodedata.normalize("NFD", "kısa açıklama")
        self.assertNotEqual(composed, decomposed)
        self.assertEqual(content_fingerprint(dict(self.BASE,
                                                  context=composed)),
                         content_fingerprint(dict(self.BASE,
                                                  context=decomposed)))

    def test_surrounding_whitespace_does_not_change_it(self):
        padded = dict(self.BASE, context="  a synthetic vignette\n")
        self.assertEqual(content_fingerprint(self.BASE),
                         content_fingerprint(padded))

    def test_it_is_stable_across_calls(self):
        first = content_fingerprint(self.BASE)
        for _ in range(5):
            self.assertEqual(content_fingerprint(self.BASE), first)

    def test_it_is_stable_across_processes(self):
        """Nothing here may depend on PYTHONHASHSEED or on ``id()``."""
        import subprocess
        import sys

        program = (
            "import json,sys;sys.path.insert(0,'.');"
            "from pgx.validation.fingerprint import content_fingerprint;"
            "print(content_fingerprint(json.loads(sys.argv[1])))")
        import json
        import os

        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        outputs = set()
        for seed in ("0", "1", "12345"):
            environment = dict(os.environ, PYTHONHASHSEED=seed)
            result = subprocess.run(
                [sys.executable, "-c", program, json.dumps(self.BASE)],
                cwd=root, capture_output=True, text=True, env=environment)
            self.assertEqual(result.returncode, 0, result.stderr[-500:])
            outputs.add(result.stdout.strip())
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs.pop(), content_fingerprint(self.BASE))


class TestItKeepsWhatDoesCarryMeaning(unittest.TestCase):
    """The dangerous direction. A collapse hides a case.

    Every pair below is two genuinely different cases that a sloppier
    normalisation would merge - similar display text, one changed token, one
    extra gene.
    """

    BASE = {"observations": [{"gene": "GENE:TESTGENE1", "value": "POOR"}],
            "medications": ["DRUG:testdrug-alpha"]}

    def test_a_changed_phenotype_changes_it(self):
        other = {"observations": [{"gene": "GENE:TESTGENE1",
                                   "value": "RAPID"}],
                 "medications": ["DRUG:testdrug-alpha"]}
        self.assertNotEqual(content_fingerprint(self.BASE),
                            content_fingerprint(other))

    def test_a_changed_gene_changes_it(self):
        other = {"observations": [{"gene": "GENE:TESTGENE2",
                                   "value": "POOR"}],
                 "medications": ["DRUG:testdrug-alpha"]}
        self.assertNotEqual(content_fingerprint(self.BASE),
                            content_fingerprint(other))

    def test_an_added_observation_changes_it(self):
        other = {"observations": [{"gene": "GENE:TESTGENE1", "value": "POOR"},
                                  {"gene": "GENE:TESTGENE2",
                                   "value": "NORMAL"}],
                 "medications": ["DRUG:testdrug-alpha"]}
        self.assertNotEqual(content_fingerprint(self.BASE),
                            content_fingerprint(other))

    def test_a_changed_medication_changes_it(self):
        other = dict(self.BASE, medications=["DRUG:testdrug-beta"])
        self.assertNotEqual(content_fingerprint(self.BASE),
                            content_fingerprint(other))

    def test_a_repeated_observation_is_not_a_duplicate_case(self):
        """Two identical observations are different content from one.

        Sorting must not silently de-duplicate: a profile stating a gene twice
        is malformed, and a fingerprint that hid that would hide the fault.
        """
        other = dict(self.BASE,
                     observations=self.BASE["observations"] * 2)
        self.assertNotEqual(content_fingerprint(self.BASE),
                            content_fingerprint(other))

    def test_two_cases_with_similar_titles_are_not_merged(self):
        """Display text is not part of the fingerprint at all.

        Two cases titled "Poor metaboliser, alpha" differ if their content
        differs, and are the same if their content is the same. The title has
        no vote either way.
        """
        left = dict(self.BASE, title="Poor metaboliser, alpha")
        right = dict(self.BASE, title="Poor metaboliser, alpha (v2)")
        self.assertNotEqual(content_fingerprint(left),
                            content_fingerprint(right))
        self.assertNotEqual(content_fingerprint(left),
                            content_fingerprint(self.BASE))

    def test_case_is_not_folded_in_governed_tokens(self):
        """Folding would let a malformed phenotype token pass as a valid one."""
        other = {"observations": [{"gene": "GENE:TESTGENE1", "value": "poor"}],
                 "medications": ["DRUG:testdrug-alpha"]}
        self.assertNotEqual(content_fingerprint(self.BASE),
                            content_fingerprint(other))


class TestTheOrderInsensitiveListIsShort(unittest.TestCase):

    def test_it_names_three_fields(self):
        """Sorting everything would erase order where order matters.

        That failure is a false collapse - the worse direction - so the list
        is enumerated rather than inferred.
        """
        self.assertEqual(sorted(ORDER_INSENSITIVE_FIELDS),
                         ["medications", "observations", "source_citations"])

    def test_an_unlisted_list_keeps_its_order(self):
        left = {"steps": ["a", "b"]}
        right = {"steps": ["b", "a"]}
        self.assertNotEqual(content_fingerprint(left),
                            content_fingerprint(right))


class TestItRefusesWhatItCannotHash(unittest.TestCase):

    def test_empty_content_is_refused(self):
        """An empty case would collide with every other empty case."""
        with self.assertRaises(FingerprintError):
            content_fingerprint({})

    def test_a_non_mapping_is_refused(self):
        with self.assertRaises(FingerprintError):
            content_fingerprint(["observations"])

    def test_bytes_are_refused(self):
        with self.assertRaises(FingerprintError):
            content_fingerprint({"blobbed": b"\x00"})

    def test_an_over_long_string_is_refused_rather_than_truncated(self):
        with self.assertRaises(FingerprintError):
            normalise_text("x" * 5000)


class TestTheDerivationFamily(unittest.TestCase):
    """The identity a content fingerprint cannot see."""

    def test_one_source_and_method_is_one_family(self):
        self.assertEqual(
            derivation_family_fingerprint("Smith 2019, Table 3", "manual"),
            derivation_family_fingerprint("smith 2019, table 3", "MANUAL"))

    def test_a_different_source_is_a_different_family(self):
        self.assertNotEqual(
            derivation_family_fingerprint("Smith 2019, Table 3", "manual"),
            derivation_family_fingerprint("Smith 2019, Table 4", "manual"))

    def test_a_different_method_is_a_different_family(self):
        self.assertNotEqual(
            derivation_family_fingerprint("Smith 2019, Table 3", "manual"),
            derivation_family_fingerprint("Smith 2019, Table 3", "scripted"))

    def test_an_empty_source_is_refused(self):
        with self.assertRaises(FingerprintError):
            derivation_family_fingerprint("   ", "manual")


class TestTheVersionIsPartOfTheHash(unittest.TestCase):

    def test_the_version_is_named(self):
        self.assertEqual(CONTENT_FINGERPRINT_VERSION,
                         "pgx-wp18-content-fingerprint/1")

    def test_canonical_content_is_inspectable(self):
        """A curator investigating a collision needs to see what was compared.

        Being told a digest and left to guess is not a usable answer.
        """
        shown = canonical_content({"observations": [
            {"gene": "GENE:TESTGENE2", "value": "NORMAL"},
            {"gene": "GENE:TESTGENE1", "value": "POOR"}]})
        self.assertEqual([item["gene"] for item in shown["observations"]],
                         ["GENE:TESTGENE1", "GENE:TESTGENE2"])
