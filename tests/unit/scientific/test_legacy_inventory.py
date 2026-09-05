# -*- coding: utf-8 -*-
"""The legacy source inventory: read-only, exact, and byte-identical on re-run.

Three properties, each guarding a specific way an inventory goes wrong:

* **Determinism.** No timestamp, sorted collections. A run that differed from
  the last one would make every regeneration a diff, and a real change to the
  data would be invisible inside the noise.
* **Exact text.** ``report/pair:variantAnnotation`` and
  ``report/pair:VariantAnnotation`` both occur in the frozen outputs and are
  counted separately. Merging them would be a normalisation decision this
  project has no standing to make about somebody else's data model.
* **An allowlist.** ``drug_graph_edges.csv`` has a column called ``source``
  that holds drug names. Counting it would invent scientific sources named
  after medicines.
"""

from __future__ import annotations

import io
import os
import unittest

from pgx.scientific.errors import LegacyInventoryError
from pgx.scientific.inventory import (
    EXCLUDED_COLUMNS,
    LEGACY_SOURCE_COLUMNS,
    LegacyColumn,
    SourceValueKind,
    build_inventory,
    render_markdown,
    unregistered_legacy_values,
)
from pgx.scientific.policy import load_registry

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
INVENTORY_JSON = os.path.join(REPO_ROOT, "data", "migration",
                              "legacy-source-inventory.json")
INVENTORY_MARKDOWN = os.path.join(REPO_ROOT, "docs", "migration",
                                  "legacy-source-inventory.md")
CONFIG_PATH = os.path.join(REPO_ROOT, "config", "scientific-sources.json")


def _read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


class TestTheScanIsDeterministic(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.first = build_inventory(REPO_ROOT)
        cls.second = build_inventory(REPO_ROOT)

    def test_two_runs_hash_identically(self):
        self.assertEqual(self.first.content_hash(), self.second.content_hash())

    def test_two_runs_render_byte_identical_json(self):
        self.assertEqual(self.first.render_json(), self.second.render_json())

    def test_two_runs_render_byte_identical_markdown(self):
        self.assertEqual(render_markdown(self.first, "t"),
                         render_markdown(self.second, "t"))

    def test_the_output_carries_no_wall_clock_timestamp(self):
        """A timestamp would make every regeneration a diff."""
        document = self.first.to_json()
        for key in ("generated_at", "created_at", "timestamp", "run_at"):
            self.assertNotIn(key, document)

    def test_staleness_is_detectable_from_input_digests_instead(self):
        self.assertTrue(self.first.input_digests)
        for path, digest in self.first.input_digests.items():
            with self.subTest(path=path):
                self.assertTrue(digest.startswith("sha256:"))

    def test_the_input_digests_cannot_be_edited_after_the_scan(self):
        """A mutated digest would make a stale inventory look current."""
        with self.assertRaises(TypeError):
            self.first.input_digests["clinpgx_mvp_seed/x.csv"] = "sha256:0"

    def test_values_are_sorted(self):
        keys = [(value.kind.value, value.value) for value in self.first.values]
        self.assertEqual(keys, sorted(keys))


class TestTheCheckedInArtefactsAreCurrent(unittest.TestCase):

    def test_the_json_matches_a_fresh_scan(self):
        self.assertEqual(_read(INVENTORY_JSON),
                         build_inventory(REPO_ROOT).render_json())

    def test_the_markdown_matches_a_fresh_scan(self):
        self.assertEqual(
            _read(INVENTORY_MARKDOWN),
            render_markdown(build_inventory(REPO_ROOT), "Legacy source inventory"))


class TestExactTextIsPreserved(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.inventory = build_inventory(REPO_ROOT)
        cls.values = {(v.kind.value, v.value) for v in cls.inventory.values}

    def test_case_variants_are_counted_separately(self):
        lower = ("SOURCE_CONTAINER", "report/pair:variantAnnotation")
        upper = ("SOURCE_CONTAINER", "report/pair:VariantAnnotation")
        self.assertIn(lower, self.values)
        self.assertIn(upper, self.values)

    def test_case_variants_are_reported_rather_than_merged(self):
        joined = " ".join(self.inventory.observations)
        self.assertIn("case", joined.lower())

    def test_the_guideline_bodies_appear_with_their_legacy_spelling(self):
        for spelling in ("CPIC", "DPWG", "RNPGx", "AHA", "AusNZ", "CPNDS"):
            with self.subTest(value=spelling):
                self.assertIn(("SOURCE_NAME", spelling), self.values)

    def test_a_blank_source_value_is_reported_not_dropped(self):
        blank = [v for v in self.inventory.values if v.is_blank]
        self.assertTrue(blank, "a row with no recorded provenance is a finding")

    def test_every_value_records_which_columns_it_came_from(self):
        for value in self.inventory.values:
            with self.subTest(value=value.value):
                self.assertTrue(value.columns)
                self.assertEqual(list(value.columns), sorted(value.columns))


class TestTheAllowlistIsExplicit(unittest.TestCase):

    def test_the_drug_column_named_source_is_excluded_with_a_reason(self):
        excluded = {(item.relative_path, item.column): item.reason
                    for item in EXCLUDED_COLUMNS}
        self.assertIn(("drug_graph_edges.csv", "source"), excluded)
        self.assertIn(("candidate_alternatives.csv", "source_drug"), excluded)
        for reason in excluded.values():
            self.assertTrue(reason.strip())

    def test_no_excluded_column_is_also_scanned(self):
        scanned = {(c.relative_path, c.column) for c in LEGACY_SOURCE_COLUMNS}
        for item in EXCLUDED_COLUMNS:
            with self.subTest(column=item.label):
                self.assertNotIn((item.relative_path, item.column), scanned)

    def test_no_drug_name_leaked_into_the_source_values(self):
        values = {v.value for v in build_inventory(REPO_ROOT).values}
        for drug in ("clopidogrel", "warfarin", "codeine"):
            with self.subTest(drug=drug):
                self.assertNotIn(drug, values)

    def test_every_scanned_column_names_why_it_is_scanned(self):
        for column in LEGACY_SOURCE_COLUMNS:
            with self.subTest(column=column.label):
                self.assertTrue(column.note.strip())
                self.assertIsInstance(column.kind, SourceValueKind)

    def test_the_scan_is_limited_to_the_allowlist(self):
        limited = build_inventory(
            REPO_ROOT,
            columns=(LEGACY_SOURCE_COLUMNS[0],),
            exclusions=())
        self.assertEqual(len(limited.columns_scanned), 1)


class TestAnUnreadableInputIsNotSkipped(unittest.TestCase):

    def test_a_column_that_vanished_from_a_file_raises(self):
        bogus = LegacyColumn(
            "clinpgx_mvp_seed/drug_gene_guidelines.csv", "no_such_column",
            SourceValueKind.SOURCE_NAME, "fixture")
        with self.assertRaises(LegacyInventoryError):
            build_inventory(REPO_ROOT, columns=(bogus,), exclusions=())

    def test_a_missing_file_is_recorded_rather_than_raising(self):
        absent = LegacyColumn("no_such_file.csv", "source",
                              SourceValueKind.SOURCE_NAME, "fixture")
        inventory = build_inventory(REPO_ROOT, columns=(absent,), exclusions=())
        self.assertEqual(inventory.missing_inputs, ("no_such_file.csv",))


class TestEveryLegacySourceNameHasAPolicy(unittest.TestCase):

    def test_nothing_in_the_frozen_data_cites_an_unregistered_source(self):
        issues = unregistered_legacy_values(
            build_inventory(REPO_ROOT), load_registry(CONFIG_PATH))
        self.assertEqual([issue.subject for issue in issues], [])

    def test_matching_is_exact_and_never_fuzzy(self):
        """A near-match would be a mapping decision made by a distance function."""
        class _Registry:
            records = ()
        issues = unregistered_legacy_values(build_inventory(REPO_ROOT), _Registry())
        subjects = {issue.subject for issue in issues}
        self.assertIn("CPIC", subjects)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
