# -*- coding: utf-8 -*-
"""What the canonical build changed relative to the legacy seed (WP-07).

The important test here is the one that fails: the ``1,572`` collision count
recorded in ``architecture.md`` is not reproducible from the real artifacts, and
the report says so rather than reshaping the dedup key until the number appears.
"""

from __future__ import annotations

import ast
import io
import json
import os
import unittest

from pgx.normalization.build import CanonicalBuildRequest, build_canonical_dataset
from pgx.normalization.legacy_diff import (LEGACY_DIFF_VERSION,
                                           LEGACY_EXPECTATIONS_PATH,
                                           LEGACY_SEED_FILES,
                                           build_legacy_difference_report,
                                           read_expectations)

from tests.unit.normalization._snapshot import REPO_ROOT, RealSnapshotTestCase

LEGACY_DIFF = os.path.join("pgx", "normalization", "legacy_diff.py")


def _source(relative: str) -> str:
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


class TestExpectationsAreDataNotCode(unittest.TestCase):

    def test_the_documented_figures_live_in_a_config_file(self):
        path = os.path.join(REPO_ROOT, LEGACY_EXPECTATIONS_PATH)
        self.assertTrue(os.path.isfile(path), LEGACY_EXPECTATIONS_PATH)
        claims = read_expectations(REPO_ROOT)
        self.assertIn("ARCH-8.3-DEDUP-COLLISIONS", claims)

    def test_no_production_module_hard_codes_the_collision_figure(self):
        """1572 must not appear as a constant anywhere under ``pgx/``.

        Read from the AST as a numeric literal, so the check is about a value
        the code depends on rather than about a string in a sentence.
        """
        offences = []
        for current, _, names in os.walk(os.path.join(REPO_ROOT, "pgx")):
            for name in sorted(names):
                if not name.endswith(".py"):
                    continue
                relative = os.path.relpath(os.path.join(current, name),
                                           REPO_ROOT)
                tree = ast.parse(_source(relative), filename=relative)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Constant) and node.value == 1572:
                        offences.append(relative)
        self.assertEqual(offences, [])

    def test_every_claim_cites_where_it_came_from(self):
        for claim_id, claim in read_expectations(REPO_ROOT).items():
            with self.subTest(claim=claim_id):
                self.assertTrue(str(claim.get("cited_from", "")).strip())
                self.assertIn(claim.get("kind"),
                              ("documented_expectation", "known_stale_value"))


class TestTheRealComparison(RealSnapshotTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        build = build_canonical_dataset(CanonicalBuildRequest(
            snapshot_root=cls.snapshot_path,
            output_root=os.path.join(cls.snapshot_path, "unused"),
            allow_new_identities=True))
        cls.report = build_legacy_difference_report(build, REPO_ROOT)

    def test_the_documented_collision_figure_is_not_reproducible(self):
        """Reported as a disagreement, not resolved by redefining the key."""
        checks = {check.claim_id: check for check in self.report.claim_checks}
        collision = checks["ARCH-8.3-DEDUP-COLLISIONS"]
        self.assertFalse(collision.agrees)
        self.assertTrue(collision.is_surprising)
        self.assertEqual(collision.claimed_value, 1572)
        self.assertEqual(collision.observed_value, 1644)

    def test_the_alternatives_are_stated_so_the_gap_can_be_judged(self):
        checks = {check.claim_id: check for check in self.report.claim_checks}
        alternatives = checks["ARCH-8.3-DEDUP-COLLISIONS"].alternative_measurements
        self.assertTrue(alternatives)
        self.assertNotIn(1572, alternatives.values(),
                         "no defined measurement yields the documented figure")

    def test_the_stale_seed_summary_is_expected_to_disagree(self):
        checks = {check.claim_id: check for check in self.report.claim_checks}
        for claim_id in ("SEED-SUMMARY-SUPPORTED-DRUGS",
                         "SEED-SUMMARY-GUIDELINE-ROWS"):
            with self.subTest(claim=claim_id):
                check = checks[claim_id]
                self.assertFalse(check.agrees)
                self.assertFalse(check.is_surprising)
                self.assertEqual(check.legacy_bug, "LEGACY-BUG-007")

    def test_only_the_architecture_claim_is_unexplained(self):
        self.assertEqual([check.claim_id
                          for check in self.report.surprising_claims],
                         ["ARCH-8.3-DEDUP-COLLISIONS"])

    def test_the_candidate_merge_drift_is_named_drug_by_drug(self):
        drift = self.report.candidate_merge_drift
        self.assertEqual(sorted(drift["drugs_added_by_candidate_onboarding"]),
                         ["nortriptyline", "pantoprazole", "prasugrel",
                          "ticagrelor"])
        self.assertEqual(drift["cleaner_output_drug_count"], 11)
        self.assertEqual(drift["active_seed_drug_count"], 15)

    def test_the_added_pairs_are_named_too(self):
        drift = self.report.candidate_merge_drift
        self.assertEqual(sorted(drift["pairs_added_by_candidate_onboarding"]),
                         ["CYP2C19::pantoprazole", "CYP2C19::prasugrel",
                          "CYP2C19::ticagrelor", "CYP2D6::nortriptyline"])

    def test_the_stale_totals_are_reported_with_their_bug_id(self):
        metrics = {entry["metric"]: entry for entry in self.report.stale_totals}
        self.assertEqual(metrics["supported_drugs"]["claimed"], 11)
        self.assertEqual(metrics["supported_drugs"]["observed"], 15)
        self.assertEqual(metrics["guideline_rows"]["claimed"], 30)
        self.assertEqual(metrics["guideline_rows"]["observed"], 36)
        for entry in self.report.stale_totals:
            self.assertEqual(entry["legacy_bug"], "LEGACY-BUG-007")

    def test_the_canonical_build_excludes_the_candidate_additions(self):
        difference = [item for item in self.report.differences
                      if item.right_label == "canonical_p0"
                      and "drugs" in item.subject][0]
        self.assertEqual(difference.right_count, 11)
        self.assertEqual(sorted(difference.only_left),
                         ["nortriptyline", "pantoprazole", "prasugrel",
                          "ticagrelor"])
        self.assertEqual(difference.only_right, ())

    def test_the_genes_agree_because_both_came_from_one_query_set(self):
        difference = [item for item in self.report.differences
                      if item.subject.startswith("genes")][0]
        self.assertTrue(difference.identical, difference.to_json())

    def test_the_duplicate_collapse_says_what_it_measured(self):
        collapse = self.report.duplicate_collapse
        self.assertIn("definition", collapse)
        self.assertIn("case-folded container family", collapse["definition"])
        self.assertEqual(
            collapse["pair_container_case_variant_duplicate_observations"],
            1644)

    def test_the_candidate_lookup_is_counted_and_not_imported(self):
        self.assertEqual(
            self.report.candidate_merge_drift["candidate_alternatives_row_count"],
            4)
        self.assertTrue(any("imported nowhere" in finding
                            for finding in self.report.findings))

    def test_every_legacy_file_is_digested_so_drift_is_detectable(self):
        for snapshot in self.report.files:
            with self.subTest(label=snapshot.label):
                if snapshot.exists:
                    self.assertTrue(snapshot.sha256.startswith("sha256:"))
                    self.assertIn("never modified", snapshot.note)

    def test_the_report_carries_no_timestamp_so_it_is_reproducible(self):
        payload = json.dumps(self.report.to_json())
        for token in ("generated_at", "created_at", "timestamp"):
            with self.subTest(token=token):
                self.assertNotIn(token, payload)

    def test_two_runs_produce_identical_bytes(self):
        build = build_canonical_dataset(CanonicalBuildRequest(
            snapshot_root=self.snapshot_path,
            output_root=os.path.join(self.snapshot_path, "unused"),
            allow_new_identities=True))
        again = build_legacy_difference_report(build, REPO_ROOT)
        self.assertEqual(again.duplicate_collapse,
                         self.report.duplicate_collapse)
        self.assertEqual([item.to_json() for item in again.claim_checks],
                         [item.to_json() for item in self.report.claim_checks])

    def test_the_reading_rule_disclaims_coverage_language(self):
        self.assertIn("not validated coverage",
                      self.report.to_json()["reading_rule"].casefold())

    def test_the_version_is_recorded(self):
        self.assertEqual(self.report.legacy_diff_version, LEGACY_DIFF_VERSION)


class TestItOnlyReads(unittest.TestCase):

    def test_it_opens_no_legacy_file_for_writing(self):
        tree = ast.parse(_source(LEGACY_DIFF), filename=LEGACY_DIFF)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and \
                    isinstance(node.func, ast.Name) and node.func.id == "open":
                modes = [argument.value for argument in node.args[1:]
                         if isinstance(argument, ast.Constant)]
                for mode in modes:
                    for forbidden in ("w", "a", "+", "x"):
                        with self.subTest(mode=mode, forbidden=forbidden):
                            self.assertNotIn(forbidden, mode)

    def test_it_imports_no_interpretation_column(self):
        """Reading a legacy CSV's identifier column is counting; reading its
        significance column would be importing."""
        text = _source(LEGACY_DIFF)
        for column in ("significance", "polarity", "candidate_score",
                       "evidence_tier", "recommendation", "usable_for_mvp"):
            with self.subTest(column=column):
                self.assertNotIn('"%s"' % column, text)

    def test_every_legacy_file_it_names_actually_exists(self):
        for label, relative in LEGACY_SEED_FILES.items():
            with self.subTest(label=label):
                self.assertTrue(
                    os.path.isfile(os.path.join(REPO_ROOT, relative)),
                    "%s (%s) is missing" % (label, relative))


if __name__ == "__main__":
    unittest.main()
