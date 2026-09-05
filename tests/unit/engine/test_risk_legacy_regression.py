# -*- coding: utf-8 -*-
"""Legacy behaviour V2 assessment must not reproduce (section I).

The comparison is deliberately *behavioural* rather than clinical. This
repository has no approved ruleset, so there are zero comparable real cases and
zero real V2 assessments, and promoting a legacy clinical result as an
approved expected answer would be inventing agreement nobody established.

What is compared is what the legacy engine did with a situation and what V2
does with the same situation:

* ``LEGACY-BUG-002`` - ``overall_risk_level: "none"`` rendered as *"Düşük /
  uyarı yok"*. V2 reports ``NOT_ASSESSED`` with non-``FULL`` coverage, and no
  absence path anywhere reaches ``LOW`` or ``NO_ACTIVE_ATTENTION``.
* ``LEGACY-BUG-001`` - group-normalised phenotype matching, under which a
  ``RAPID`` profile can satisfy an ``ULTRARAPID`` rule. V2 matches exactly.
* ``LEGACY-BUG-007`` - a run-time seed-file dependency, under which the same
  input can produce a different answer after an unversioned edit. V2 consumes
  only pinned immutable release artifacts.

The legacy snapshots and the legacy script are never edited. The legacy
behaviour is the defect; recording it is what makes the correction visible.
"""

from __future__ import annotations

import io
import json
import os
import unittest

from pgx.domain.enums import AttentionLevel
from pgx.engine.risk_legacy import (ASSESSMENT_ALLOWLIST_SCHEMA_VERSION,
                                    ASSESSMENT_REGRESSION_REPORT_VERSION,
                                    EXPECTED_DIFFERENCES,
                                    assessment_expected_difference_allowlist,
                                    build_assessment_regression_report)
from tests.unit.application._assessment_support import REPO_ROOT

REPORT = os.path.join(REPO_ROOT, "data", "migration", "wp14",
                      "assessment-regression-report.json")
ALLOWLIST = os.path.join(REPO_ROOT, "data", "migration", "wp14",
                         "assessment-regression-allowlist.json")
P2_SNAPSHOT = os.path.join(REPO_ROOT, "data", "legacy-baseline", "snapshots",
                           "risk-p2-cyp2c19-poor.json")
LEGACY_SCRIPT = os.path.join(REPO_ROOT, "risk_engine.py")


def _read(path):
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


class LegacyCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.report = build_assessment_regression_report(REPO_ROOT)
        cls.cases = {case["case_id"]: case for case in cls.report["cases"]}


class TestTheLegacyArtifactsWereNotEdited(LegacyCase):

    def test_the_p2_snapshot_still_reports_codeine_as_none(self):
        rows = {row["drug"]: row["overall_risk_level"]
                for row in _read(P2_SNAPSHOT)["drug_results"]}
        self.assertEqual(rows["codeine"], "none")

    def test_the_p2_snapshot_still_reports_warfarin_as_none(self):
        rows = {row["drug"]: row["overall_risk_level"]
                for row in _read(P2_SNAPSHOT)["drug_results"]}
        self.assertEqual(rows["warfarin"], "none")

    def test_the_p2_snapshot_still_carries_its_real_findings(self):
        """Not a file of zeroes: clopidogrel and voriconazole are high in it,
        which is what makes the two 'none' rows a defect rather than an empty
        run."""
        rows = {row["drug"]: row["overall_risk_level"]
                for row in _read(P2_SNAPSHOT)["drug_results"]}
        self.assertEqual(rows["clopidogrel"], "high")
        self.assertEqual(rows["voriconazole"], "high")

    def test_the_legacy_script_still_matches_phenotypes_by_group(self):
        with io.open(LEGACY_SCRIPT, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("def normalize_rule_group", source)
        self.assertIn("def phenotype_matches", source)

    def test_the_legacy_script_still_reads_its_seed_files(self):
        with io.open(LEGACY_SCRIPT, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("import csv", source)
        self.assertIn("def read_csv", source)


class TestTheCorrections(LegacyCase):

    def test_codeine_is_not_assessed_rather_than_low(self):
        case = self.cases["P2-codeine"]
        self.assertEqual(case["legacy_value"], "none")
        self.assertTrue(case["legacy_rendered_as_reassuring"])
        self.assertEqual(case["v2_attention"],
                         AttentionLevel.NOT_ASSESSED.value)
        self.assertFalse(case["v2_coverage_is_full"])
        self.assertFalse(case["v2_emits_low"])
        self.assertFalse(case["v2_emits_no_active_attention"])

    def test_warfarin_is_not_assessed_rather_than_low(self):
        case = self.cases["P2-warfarin"]
        self.assertEqual(case["legacy_value"], "none")
        self.assertEqual(case["v2_attention"],
                         AttentionLevel.NOT_ASSESSED.value)
        self.assertFalse(case["v2_emits_low"])

    def test_no_case_emits_a_reassuring_level(self):
        for case in self.report["cases"]:
            with self.subTest(case=case["case_id"]):
                self.assertFalse(case["v2_emits_low"])
                self.assertFalse(case["v2_emits_no_active_attention"])

    def test_no_case_reports_full_coverage(self):
        for case in self.report["cases"]:
            with self.subTest(case=case["case_id"]):
                self.assertFalse(case["v2_coverage_is_full"])

    def test_every_case_explains_itself(self):
        for case in self.report["cases"]:
            with self.subTest(case=case["case_id"]):
                self.assertGreater(len(case["v2_explanation"]), 20)

    def test_the_phenotype_matching_case_records_the_exact_matcher(self):
        case = self.cases["BEHAVIOUR-phenotype-matching"]
        self.assertEqual(case["v2_attention"], "NO_IMPLICIT_MATCH")
        self.assertIn("ULTRARAPID", case["v2_explanation"])
        self.assertIn("SAFETY-INV-004", case["v2_explanation"])

    def test_the_mutable_seed_case_records_that_v2_reads_none(self):
        case = self.cases["BEHAVIOUR-mutable-csv"]
        self.assertEqual(case["v2_attention"], "PINNED_ARTIFACTS_ONLY")
        self.assertIn("0 of", case["v2_explanation"])

    def test_the_v2_calculation_path_really_reads_no_seed_file(self):
        """The claim above, checked against the modules rather than asserted."""
        from pgx.engine.risk_legacy import _v2_calculation_modules
        for relative in _v2_calculation_modules():
            with io.open(os.path.join(REPO_ROOT, relative),
                         encoding="utf-8") as handle:
                source = handle.read()
            with self.subTest(module=relative):
                self.assertNotIn("import csv", source)
                self.assertNotIn(".csv", source)


class TestTheAllowlist(LegacyCase):

    def test_there_are_four_entries_across_three_legacy_bugs(self):
        self.assertEqual(len(EXPECTED_DIFFERENCES), 4)
        bugs = {entry.legacy_bug_id for entry in EXPECTED_DIFFERENCES}
        self.assertEqual(bugs, {"LEGACY-BUG-001", "LEGACY-BUG-002",
                                "LEGACY-BUG-007"})

    def test_every_entry_names_a_bug_a_behaviour_and_a_rationale(self):
        for entry in EXPECTED_DIFFERENCES:
            with self.subTest(entry=entry.difference_id):
                self.assertGreater(len(entry.observed_legacy_behavior), 40)
                self.assertGreater(len(entry.required_v2_behavior), 40)
                self.assertGreater(len(entry.safety_rationale), 40)
                self.assertTrue(entry.reference)

    def test_the_two_bug_002_drugs_are_addressed_separately(self):
        """A fix covering only one drug cannot satisfy a single-entry
        allowlist, and a reordered list cannot move one expectation onto the
        other."""
        selectors = [(entry.comparison_selector.get("artifact_id"),
                      entry.comparison_selector.get("drug"),
                      entry.comparison_selector.get("behaviour"))
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

    def test_an_unexpected_difference_would_be_reported(self):
        """The harness is only worth having if it can fail. Proved on a copy
        of the repository whose V2 side names a seed file."""
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        for relative in ("risk_engine.py",):
            os.makedirs(os.path.join(tmp, os.path.dirname(relative) or "."),
                        exist_ok=True)
            shutil.copy(os.path.join(REPO_ROOT, relative),
                        os.path.join(tmp, relative))
        shutil.copytree(os.path.join(REPO_ROOT, "data", "legacy-baseline"),
                        os.path.join(tmp, "data", "legacy-baseline"))
        shutil.copytree(os.path.join(REPO_ROOT, "pgx"),
                        os.path.join(tmp, "pgx"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        target = os.path.join(tmp, "pgx", "engine", "risk.py")
        with io.open(target, "a", encoding="utf-8") as handle:
            handle.write('\n_SEED = "seed/rules.csv"\n')
        report = build_assessment_regression_report(tmp)
        self.assertTrue(report["unexpected_differences"])
        self.assertIn("MUTABLE-CSV-DEPENDENCY-REMOVED",
                      report["expected_differences_not_observed"])

    def test_the_allowlist_document_states_its_policy(self):
        document = assessment_expected_difference_allowlist()
        self.assertEqual(document["allowlist_schema_version"],
                         ASSESSMENT_ALLOWLIST_SCHEMA_VERSION)
        self.assertEqual(document["entry_count"], 4)
        self.assertIn("never edited", document["policy"])


class TestTheReportIsHonestAboutRealData(LegacyCase):

    def test_it_reports_zero_approved_comparable_real_cases(self):
        self.assertEqual(self.report["approved_comparable_real_cases"], 0)

    def test_it_reports_zero_real_v2_assessments(self):
        self.assertEqual(self.report["real_v2_assessments_executed"], 0)

    def test_it_reports_zero_real_persisted_findings(self):
        self.assertEqual(self.report["real_findings_persisted"], 0)

    def test_the_note_denies_promoting_legacy_clinical_results(self):
        note = self.report["note"].lower()
        self.assertIn("not clinical validation", note)
        self.assertIn("no legacy clinical result is promoted", note)


class TestTheReportIsDeterministic(LegacyCase):

    def test_two_runs_produce_the_identical_document(self):
        self.assertEqual(build_assessment_regression_report(REPO_ROOT),
                         build_assessment_regression_report(REPO_ROOT))

    def test_the_content_hash_is_stable(self):
        again = build_assessment_regression_report(REPO_ROOT)
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
        self.assertTrue(os.path.isfile(REPORT))
        self.assertEqual(_read(REPORT), self.report)

    def test_the_stored_allowlist_matches_the_module(self):
        self.assertTrue(os.path.isfile(ALLOWLIST))
        self.assertEqual(_read(ALLOWLIST),
                         assessment_expected_difference_allowlist())

    def test_the_report_declares_its_schema_version(self):
        self.assertEqual(self.report["report_schema_version"],
                         ASSESSMENT_REGRESSION_REPORT_VERSION)

    def test_a_missing_artifact_is_a_stated_refusal(self):
        from pgx.engine.risk_errors import AssessmentEngineError
        with self.assertRaises(AssessmentEngineError) as caught:
            build_assessment_regression_report(
                os.path.join(REPO_ROOT, "does-not-exist"))
        self.assertEqual(caught.exception.code, "ASSESSMENT_INPUT_INVALID")


if __name__ == "__main__":
    unittest.main()
