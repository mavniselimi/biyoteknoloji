# -*- coding: utf-8 -*-
"""Legacy behaviour V2 coverage must not reproduce (section F).

The legacy engine reports ``overall_risk_level: "none"`` for three different
situations - the drug is unknown, no rule matched, and there is nothing to
report - and ``RISK_LABEL_TR`` renders all three as *"Düşük / uyarı yok"*
(`LEGACY-BUG-002`). Separately it attaches a 0-100 number to candidates whose
own data status is ``insufficient_pgx_rule_data`` (`LEGACY-BUG-009`).

Both are false reassurance, and both are corrected here - not by editing the
snapshots, which stay exactly as WP-01 captured them, but by recording what V2
says instead and requiring the difference to be an allowlisted one.

The four allowlist entries are computed rather than asserted: codeine and
warfarin really are in the pinned canonical catalogue and really have no
approved coverage, and prasugrel and ticagrelor really are absent from it. The
day either fact changes, this file changes with it and the change is visible.
"""

from __future__ import annotations

import io
import json
import os
import unittest

from pgx.domain.enums import CoverageReasonCode, CoverageStatus
from pgx.engine.coverage_legacy import (COVERAGE_ALLOWLIST_SCHEMA_VERSION,
                                        COVERAGE_REGRESSION_REPORT_VERSION,
                                        EXPECTED_DIFFERENCES,
                                        build_coverage_regression_report,
                                        coverage_expected_difference_allowlist,
                                        load_canonical_drug_catalogue)
from tests.unit.engine._coverage_support import (REGRESSION_ALLOWLIST,
                                                 REGRESSION_REPORT, REPO_ROOT)

P2_SNAPSHOT = os.path.join(REPO_ROOT, "data", "legacy-baseline", "snapshots",
                           "risk-p2-cyp2c19-poor.json")
CANDIDATE_SNAPSHOT = os.path.join(REPO_ROOT, "data", "legacy-baseline",
                                  "snapshots",
                                  "alternative-beta-clopidogrel.json")


def _read(path):
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


class LegacyCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.report = build_coverage_regression_report(REPO_ROOT)
        cls.catalogue, cls.identity = load_canonical_drug_catalogue(REPO_ROOT)
        cls.cases = {case["case_id"]: case for case in cls.report["cases"]}


class TestTheLegacySnapshotsWereNotEdited(LegacyCase):
    """The legacy value is the defect. Changing it would delete the evidence
    that the defect existed and make the correction invisible."""

    def test_the_p2_snapshot_still_reports_codeine_as_none(self):
        rows = {row["drug"]: row["overall_risk_level"]
                for row in _read(P2_SNAPSHOT)["drug_results"]}
        self.assertEqual(rows["codeine"], "none")

    def test_the_p2_snapshot_still_reports_warfarin_as_none(self):
        rows = {row["drug"]: row["overall_risk_level"]
                for row in _read(P2_SNAPSHOT)["drug_results"]}
        self.assertEqual(rows["warfarin"], "none")

    def test_the_p2_snapshot_still_carries_its_real_findings(self):
        """The snapshot is not a file of zeroes: clopidogrel and voriconazole
        are high in it, which is what makes the two 'none' rows a defect
        rather than an empty run."""
        rows = {row["drug"]: row["overall_risk_level"]
                for row in _read(P2_SNAPSHOT)["drug_results"]}
        self.assertEqual(rows["clopidogrel"], "high")
        self.assertEqual(rows["voriconazole"], "high")

    def test_the_candidate_snapshot_still_scores_prasugrel_and_ticagrelor(self):
        rows = {row["candidate_drug"]: row
                for row in _read(CANDIDATE_SNAPSHOT)["candidate_results"]}
        for name in ("prasugrel", "ticagrelor"):
            with self.subTest(drug=name):
                self.assertEqual(rows[name]["legacy_score_unprotected"], 59)
                self.assertEqual(rows[name]["mvp_data_status"],
                                 "insufficient_pgx_rule_data")


class TestWhatTheRealCatalogueContains(LegacyCase):
    """The two facts every expectation below is computed from."""

    def test_codeine_and_warfarin_are_in_the_pinned_catalogue(self):
        for name in ("codeine", "warfarin"):
            with self.subTest(drug=name):
                self.assertIn("DRUG:%s" % name, self.catalogue)

    def test_prasugrel_and_ticagrelor_are_not(self):
        for name in ("prasugrel", "ticagrelor"):
            with self.subTest(drug=name):
                self.assertNotIn("DRUG:%s" % name, self.catalogue)

    def test_the_catalogue_identity_is_pinned_in_the_report(self):
        self.assertEqual(self.report["canonical_build"], self.identity)
        self.assertTrue(self.identity["canonical_build_key"])
        self.assertTrue(
            self.identity["canonical_build_content_hash"].startswith("sha256:"))

    def test_the_dataset_is_still_not_published(self):
        """A BUILDING dataset is why no real coverage claim can exist. If this
        changes, every 'not assessed' answer below must be re-examined rather
        than inherited."""
        self.assertEqual(self.identity["dataset_lifecycle_state"], "BUILDING")


class TestTheElevenRequiredCases(LegacyCase):
    """Each of the situations the work package names, and what V2 says."""

    def test_codeine_is_insufficient_not_low(self):
        case = self.cases["P2-codeine"]
        self.assertEqual(case["legacy_overall_risk_level"], "none")
        self.assertTrue(case["legacy_rendered_as_reassuring"])
        self.assertTrue(case["v2_recognized"])
        self.assertEqual(case["v2_coverage_status"],
                         CoverageStatus.INSUFFICIENT.value)
        self.assertEqual(case["v2_reason_codes"],
                         [CoverageReasonCode.NO_VALIDATED_RULE_FOR_AXIS.value])

    def test_warfarin_is_insufficient_not_low(self):
        case = self.cases["P2-warfarin"]
        self.assertEqual(case["legacy_overall_risk_level"], "none")
        self.assertEqual(case["v2_coverage_status"],
                         CoverageStatus.INSUFFICIENT.value)
        self.assertEqual(case["v2_reason_codes"],
                         [CoverageReasonCode.NO_VALIDATED_RULE_FOR_AXIS.value])

    def test_prasugrel_is_unsupported_and_carries_no_score(self):
        case = self.cases["CANDIDATE-prasugrel"]
        self.assertEqual(case["legacy_score"], 59)
        self.assertIsNone(case["v2_score"])
        self.assertFalse(case["v2_recognized"])
        self.assertEqual(case["v2_coverage_status"],
                         CoverageStatus.UNSUPPORTED_DRUG.value)
        self.assertEqual(
            case["v2_reason_codes"],
            [CoverageReasonCode.DRUG_NOT_IN_CANONICAL_DATASET.value])

    def test_ticagrelor_is_unsupported_and_carries_no_score(self):
        case = self.cases["CANDIDATE-ticagrelor"]
        self.assertEqual(case["legacy_score"], 59)
        self.assertIsNone(case["v2_score"])
        self.assertEqual(case["v2_coverage_status"],
                         CoverageStatus.UNSUPPORTED_DRUG.value)

    def test_a_drug_in_no_catalogue_at_all_is_unsupported(self):
        case = self.cases["UNKNOWN-DRUG"]
        self.assertFalse(case["v2_recognized"])
        self.assertEqual(case["v2_coverage_status"],
                         CoverageStatus.UNSUPPORTED_DRUG.value)
        self.assertIsNone(case["v2_score"])

    def test_a_recognised_drug_with_no_coverage_says_so_explicitly(self):
        """Recognition is not coverage. Every recognised drug in the P2
        snapshot lands here today, because no coverage manifest exists."""
        recognised = [case for case in self.report["cases"]
                      if case["v2_recognized"]]
        self.assertTrue(recognised)
        for case in recognised:
            with self.subTest(case=case["case_id"]):
                self.assertEqual(case["v2_coverage_status"],
                                 CoverageStatus.INSUFFICIENT.value)
                self.assertIn("recognition is not coverage",
                              case["v2_explanation"])

    def test_no_case_anywhere_reports_full_coverage(self):
        for case in self.report["cases"]:
            with self.subTest(case=case["case_id"]):
                self.assertNotEqual(case["v2_coverage_status"],
                                    CoverageStatus.FULL.value)

    def test_no_case_anywhere_carries_a_v2_score(self):
        for case in self.report["cases"]:
            with self.subTest(case=case["case_id"]):
                self.assertIsNone(case["v2_score"])

    def test_every_case_carries_at_least_one_reason_code(self):
        for case in self.report["cases"]:
            with self.subTest(case=case["case_id"]):
                self.assertTrue(case["v2_reason_codes"])

    def test_the_report_states_that_no_real_manifest_exists(self):
        self.assertEqual(self.report["real_coverage_manifests"], 0)

    def test_the_missing_and_unsupported_phenotype_cases_are_covered_by_the_engine_tests(self):
        """The harness compares drugs, because that is what the legacy
        snapshots record; a phenotype-level comparison would need a legacy
        answer that does not exist. The missing-phenotype, unsupported-
        phenotype, partial-multi-axis, source-conflict and fully-covered cases
        are exercised against the engine itself, on synthetic data, and this
        test asserts those files are present rather than restating them.
        """
        for relative in ("tests/unit/engine/test_coverage_axis.py",
                         "tests/unit/engine/test_coverage_aggregation.py",
                         "tests/safety/test_coverage_safety.py",
                         "tests/integration/engine/test_coverage_end_to_end.py"):
            with self.subTest(path=relative):
                self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT,
                                                            relative)))


class TestTheAllowlistIsTiedToTheTwoLegacyBugs(LegacyCase):

    def test_there_are_four_entries_across_two_bugs(self):
        self.assertEqual(len(EXPECTED_DIFFERENCES), 4)
        bugs = {entry.legacy_bug_id for entry in EXPECTED_DIFFERENCES}
        self.assertEqual(bugs, {"LEGACY-BUG-002", "LEGACY-BUG-009"})

    def test_every_entry_names_a_bug_a_behaviour_and_a_rationale(self):
        for entry in EXPECTED_DIFFERENCES:
            with self.subTest(entry=entry.difference_id):
                self.assertGreater(len(entry.observed_legacy_behavior), 40)
                self.assertGreater(len(entry.required_v2_behavior), 40)
                self.assertGreater(len(entry.safety_rationale), 40)
                self.assertTrue(entry.reference)
                self.assertIn(entry.expected_coverage_status,
                              [status.value for status in CoverageStatus])
                self.assertIn(entry.expected_reason_code,
                              [code.value for code in CoverageReasonCode])

    def test_each_entry_addresses_one_drug_by_identity(self):
        """Two entries per bug, so a fix covering only one drug cannot satisfy
        a single-entry allowlist, and a reordered list cannot move one
        expectation onto the other."""
        selectors = [(entry.comparison_selector["artifact_id"],
                      entry.comparison_selector["drug"])
                     for entry in EXPECTED_DIFFERENCES]
        self.assertEqual(len(set(selectors)), 4)

    def test_every_entry_is_observed_exactly_once(self):
        for name, count in self.report["expected_difference_hits"].items():
            with self.subTest(entry=name):
                self.assertEqual(count, 1)

    def test_no_entry_went_unobserved(self):
        """An allowlisted difference that stopped appearing means either the
        legacy defect was edited away or V2 quietly started agreeing with it."""
        self.assertEqual(self.report["expected_differences_not_observed"], [])

    def test_no_unexpected_difference_appeared(self):
        self.assertEqual(self.report["unexpected_differences"], [])

    def test_the_entry_expectations_match_what_the_report_computed(self):
        by_selector = {(entry.comparison_selector["artifact_id"],
                        entry.comparison_selector["drug"]): entry
                       for entry in EXPECTED_DIFFERENCES}
        for case in self.report["cases"]:
            key = (case["source"], case["drug_id"].split(":", 1)[1])
            if key not in by_selector:
                continue
            entry = by_selector[key]
            with self.subTest(entry=entry.difference_id):
                self.assertEqual(case["v2_coverage_status"],
                                 entry.expected_coverage_status)
                self.assertIn(entry.expected_reason_code,
                              case["v2_reason_codes"])

    def test_the_allowlist_document_states_its_policy(self):
        document = coverage_expected_difference_allowlist()
        self.assertEqual(document["allowlist_schema_version"],
                         COVERAGE_ALLOWLIST_SCHEMA_VERSION)
        self.assertEqual(document["entry_count"], 4)
        self.assertIn("never edited", document["policy"])


class TestTheReportIsDeterministicAndOnDisk(LegacyCase):

    def test_two_runs_produce_the_identical_document(self):
        self.assertEqual(build_coverage_regression_report(REPO_ROOT),
                         build_coverage_regression_report(REPO_ROOT))

    def test_the_content_hash_is_stable(self):
        again = build_coverage_regression_report(REPO_ROOT)
        self.assertEqual(again["content_hash"], self.report["content_hash"])
        self.assertTrue(self.report["content_hash"].startswith("sha256:"))

    def test_it_carries_no_timestamp_path_or_host(self):
        text = json.dumps(self.report)
        for forbidden in ("generated_at", "timestamp", "hostname", "/home/",
                          "/Users/", "/sessions/", "C:\\"):
            with self.subTest(marker=forbidden):
                self.assertNotIn(forbidden, text)

    def test_the_cases_are_sorted(self):
        ids = [case["case_id"] for case in self.report["cases"]]
        self.assertEqual(ids, sorted(ids))

    def test_the_stored_report_matches_a_fresh_build(self):
        self.assertTrue(os.path.isfile(REGRESSION_REPORT))
        self.assertEqual(_read(REGRESSION_REPORT), self.report)

    def test_the_stored_allowlist_matches_the_module(self):
        self.assertTrue(os.path.isfile(REGRESSION_ALLOWLIST))
        self.assertEqual(_read(REGRESSION_ALLOWLIST),
                         coverage_expected_difference_allowlist())

    def test_the_report_declares_its_schema_version(self):
        self.assertEqual(self.report["report_schema_version"],
                         COVERAGE_REGRESSION_REPORT_VERSION)

    def test_the_report_note_denies_being_clinical_validation(self):
        note = self.report["note"].lower()
        self.assertIn("not clinical validation", note)
        self.assertIn("no score appears anywhere", note)

    def test_a_missing_artifact_is_a_stated_refusal(self):
        from pgx.engine.coverage_errors import CoverageEngineError
        with self.assertRaises(CoverageEngineError) as caught:
            build_coverage_regression_report(
                os.path.join(REPO_ROOT, "does-not-exist"))
        self.assertEqual(caught.exception.code,
                         "COVERAGE_LEGACY_ARTIFACT_MISSING")


if __name__ == "__main__":
    unittest.main()
