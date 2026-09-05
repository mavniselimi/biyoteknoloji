# -*- coding: utf-8 -*-
"""Groups C, D, E, G: offline legacy reproduction and preservation.

Every rerun writes to a TemporaryDirectory. The active seed is read-only, and
its hashes are asserted unchanged after each run. No network call is made and
GEMINI_API_KEY is stripped from every child process.

    python3 -m unittest tests.regression.legacy.test_legacy_reproduction -v
"""

from __future__ import annotations

import os
import unittest

from tests.regression.legacy._support import (
    LEGACY_MODULES, REPO_ROOT, SEED_FILES, WP00_FILES, BaselineRequiredMixin,
    manifest, missing_baseline_artifacts, snapshot,
)

from legacy_baseline_lib import (
    LegacyRunError, assert_not_live_seed, csv_row_count, read_json, require_files,
    run_legacy, sha256_file, temp_workspace,
)

SEED_DIR = "clinpgx_mvp_seed"
CLEANER_ARTIFACTS = ("supported_genes.csv", "supported_drugs.csv",
                     "drug_gene_guidelines.csv", "phenotype_effect_rules.csv",
                     "mvp_demo_profiles.json", "mvp_seed_summary.json")


def seed_hashes():
    """Hash every active seed file that exists, for before/after comparison."""
    return {p: sha256_file(os.path.join(REPO_ROOT, p))
            for p in SEED_FILES if os.path.isfile(os.path.join(REPO_ROOT, p))}


class TestCleanerReproduction(BaselineRequiredMixin, unittest.TestCase):
    """Group C: the original cleaner rebuilds 5 / 11 / 30 / 3084 into a temp dir."""

    @classmethod
    def setUpClass(cls):
        cls.before = seed_hashes()
        cls.tmp = temp_workspace("wp01-test-cleaner-")
        out_dir = cls.tmp.name
        assert_not_live_seed(out_dir, REPO_ROOT)
        code, out, err = run_legacy(
            ["clean_mvp_seed_dataset.py", "--input-dir", "clinpgx_outputs_v2",
             "--out-dir", out_dir], cwd=REPO_ROOT)
        cls.exit_code, cls.stderr, cls.out_dir = code, err, out_dir

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_run_succeeded(self):
        self.assertEqual(self.exit_code, 0, self.stderr[:500])

    def test_output_went_to_a_temporary_directory_not_the_seed(self):
        self.assertNotIn(os.path.join(REPO_ROOT, SEED_DIR), self.out_dir)
        with self.assertRaises(LegacyRunError):
            assert_not_live_seed(os.path.join(REPO_ROOT, SEED_DIR), REPO_ROOT)

    def test_active_seed_hashes_are_unchanged(self):
        self.assertEqual(seed_hashes(), self.before)

    def test_expected_artifact_set_is_produced(self):
        self.assertEqual(sorted(os.listdir(self.out_dir)), sorted(CLEANER_ARTIFACTS))

    def test_rebuild_counts_are_five_eleven_thirty_3084(self):
        counts = {
            "supported_genes": csv_row_count(os.path.join(self.out_dir, "supported_genes.csv")),
            "supported_drugs": csv_row_count(os.path.join(self.out_dir, "supported_drugs.csv")),
            "guideline_rows": csv_row_count(os.path.join(self.out_dir, "drug_gene_guidelines.csv")),
            "effect_rule_rows": csv_row_count(os.path.join(self.out_dir, "phenotype_effect_rules.csv")),
        }
        self.assertEqual(counts, {"supported_genes": 5, "supported_drugs": 11,
                                  "guideline_rows": 30, "effect_rule_rows": 3084})

    def test_rebuild_differs_from_the_active_seed_in_exactly_two_files(self):
        differing = []
        for name in CLEANER_ARTIFACTS:
            active = os.path.join(REPO_ROOT, SEED_DIR, name)
            if os.path.isfile(active) and \
                    sha256_file(active) != sha256_file(os.path.join(self.out_dir, name)):
                differing.append(name)
        self.assertEqual(sorted(differing),
                         ["drug_gene_guidelines.csv", "supported_drugs.csv"])

    def test_stale_summary_is_proven_by_the_rebuild(self):
        """The active summary equals a fresh pre-merge rebuild: LEGACY-BUG-007."""
        active = os.path.join(REPO_ROOT, SEED_DIR, "mvp_seed_summary.json")
        self.assertEqual(sha256_file(active),
                         sha256_file(os.path.join(self.out_dir, "mvp_seed_summary.json")))
        self.assertEqual(read_json(active)["counts"]["supported_drugs"], 11)
        self.assertEqual(csv_row_count(os.path.join(REPO_ROOT, SEED_DIR,
                                                    "supported_drugs.csv")), 15)

    def test_missing_input_produces_a_precise_failure(self):
        with self.assertRaises(LegacyRunError) as ctx:
            require_files(REPO_ROOT, ["clinpgx_outputs_v2/__does_not_exist__.csv"],
                          "cleaner reproduction")
        message = str(ctx.exception)
        self.assertIn("__does_not_exist__.csv", message)
        self.assertIn("cleaner reproduction", message)

    def test_legacy_silently_falls_back_on_a_bad_input_dir(self):
        """Observed legacy behaviour WP01-OBS-001 - recorded, never protected.

        clean_mvp_seed_dataset.py:239 falls back to ``cwd/clinpgx_outputs_v2``
        when a file is absent from ``--input-dir``. A nonexistent --input-dir
        therefore still exits 0 and emits a full, correct-looking seed built
        from a different source. WP-01 records this; it does not fix it, and it
        is NOT accepted as correct behaviour.
        """
        with temp_workspace("wp01-test-badinput-") as tmp:
            code, out, err = run_legacy(
                ["clean_mvp_seed_dataset.py", "--input-dir", "__no_such_dir__",
                 "--out-dir", tmp], cwd=REPO_ROOT)
            self.assertEqual(code, 0, "documenting the observed silent fallback")
            self.assertTrue(os.path.exists(os.path.join(tmp, "supported_drugs.csv")),
                            "the fallback produces a full seed despite a bad input dir")
            self.assertIn("__no_such_dir__", out,
                          "the run still prints the input dir it did not use")

    def test_the_wp01_harness_catches_a_missing_input_precisely(self):
        """A10: the WP-01 harness must fail loudly where the legacy script does not."""
        with self.assertRaises(LegacyRunError) as ctx:
            require_files(REPO_ROOT,
                          ["__no_such_dir__/resolved_genes.json",
                           "__no_such_dir__/pair_probe_raw.json"],
                          "original cleaner reproduction")
        message = str(ctx.exception)
        self.assertIn("original cleaner reproduction", message)
        self.assertIn("resolved_genes.json", message)
        self.assertIn("pair_probe_raw.json", message)


class TestRiskReproduction(BaselineRequiredMixin, unittest.TestCase):
    """Group D: the recorded P2 CYP2C19-poor case, reproduced offline."""

    @classmethod
    def setUpClass(cls):
        cls.before = seed_hashes()
        cls.tmp = temp_workspace("wp01-test-risk-")
        out_dir = cls.tmp.name
        assert_not_live_seed(out_dir, REPO_ROOT)
        code, out, err = run_legacy(
            ["risk_engine.py", "--seed-dir", SEED_DIR, "--profile-id", "P2_cyp2c19_poor",
             "--drugs", "clopidogrel,voriconazole,codeine,warfarin,amitriptyline",
             "--out-dir", out_dir], cwd=REPO_ROOT)
        cls.exit_code, cls.stderr, cls.out_dir = code, err, out_dir
        path = os.path.join(out_dir, "risk_result_full.json")
        cls.result = read_json(path) if os.path.exists(path) else {}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _drug(self, name):
        for entry in self.result.get("drug_results", []):
            if entry.get("drug") == name:
                return entry
        self.fail("drug %s missing from the reproduced result" % name)

    def test_run_succeeded(self):
        self.assertEqual(self.exit_code, 0, self.stderr[:500])

    def test_active_seed_hashes_are_unchanged(self):
        self.assertEqual(seed_hashes(), self.before)

    def test_overall_result_is_high_with_three_flags(self):
        self.assertEqual(self.result.get("overall_risk_level"), "high")
        self.assertEqual(self.result.get("risk_flag_count"), 3)

    def test_clopidogrel_is_a_high_active_flag(self):
        entry = self._drug("clopidogrel")
        self.assertEqual(entry["overall_risk_level"], "high")
        self.assertTrue(any(f.get("status") == "risk_flag" for f in entry["findings"]))

    def test_voriconazole_is_a_high_active_flag(self):
        entry = self._drug("voriconazole")
        self.assertEqual(entry["overall_risk_level"], "high")
        self.assertTrue(any(f.get("status") == "risk_flag" for f in entry["findings"]))

    def test_amitriptyline_is_a_medium_active_flag(self):
        entry = self._drug("amitriptyline")
        self.assertEqual(entry["overall_risk_level"], "medium")
        self.assertTrue(any(f.get("status") == "risk_flag" for f in entry["findings"]))

    def test_codeine_and_warfarin_reproduce_the_legacy_none_defect(self):
        """LEGACY-BUG-002 recorded, never protected as correct."""
        for name in ("codeine", "warfarin"):
            entry = self._drug(name)
            self.assertEqual(entry["overall_risk_level"], "none", name)
            self.assertFalse(any(f.get("status") == "risk_flag"
                                 for f in entry["findings"]), name)
        registered = {b["bug_id"]: b for b in manifest()["legacy_bugs"]}
        self.assertIn("LEGACY-BUG-002", registered)
        self.assertIs(registered["LEGACY-BUG-002"]["protected_as_correct"], False)

    def test_legacy_warning_text_is_captured_verbatim(self):
        warning = self.result.get("clinical_warning")
        self.assertTrue(warning)
        self.assertIn("klinik karar", warning.lower())
        self.assertEqual(snapshot("risk-p2-cyp2c19-poor")["legacy_clinical_warning_text"],
                         warning)

    def test_legacy_warning_is_not_presented_as_canonical(self):
        self.require_baseline()
        from pgx.domain.claims import CANONICAL_CLINICAL_WARNING_TR
        self.assertNotEqual(self.result.get("clinical_warning"),
                            CANONICAL_CLINICAL_WARNING_TR)

    def test_expected_artifacts_are_produced(self):
        self.assertEqual(
            sorted(os.listdir(self.out_dir)),
            ["gemini_input.json", "risk_findings.csv", "risk_report.md",
             "risk_result_full.json"])

    def test_rerun_is_byte_deterministic(self):
        with temp_workspace("wp01-test-risk2-") as tmp:
            code, out, err = run_legacy(
                ["risk_engine.py", "--seed-dir", SEED_DIR, "--profile-id",
                 "P2_cyp2c19_poor", "--drugs",
                 "clopidogrel,voriconazole,codeine,warfarin,amitriptyline",
                 "--out-dir", tmp], cwd=REPO_ROOT)
            self.assertEqual(code, 0, err[:300])
            for name in sorted(os.listdir(self.out_dir)):
                self.assertEqual(sha256_file(os.path.join(self.out_dir, name)),
                                 sha256_file(os.path.join(tmp, name)), name)

    def test_unknown_profile_fails_with_a_precise_message(self):
        with temp_workspace("wp01-test-badprofile-") as tmp:
            code, out, err = run_legacy(
                ["risk_engine.py", "--seed-dir", SEED_DIR, "--profile-id",
                 "__no_such_profile__", "--drugs", "clopidogrel",
                 "--out-dir", tmp], cwd=REPO_ROOT)
            combined = (out + err)
            self.assertTrue(code != 0 or "__no_such_profile__" in combined,
                            "an unknown profile must not silently succeed")


class TestCandidateRegression(BaselineRequiredMixin, unittest.TestCase):
    """Group E: prasugrel/ticagrelor beta behaviour, score explicitly unprotected."""

    @classmethod
    def setUpClass(cls):
        cls.before = seed_hashes()
        cls.tmp = temp_workspace("wp01-test-alt-")
        out_dir = cls.tmp.name
        assert_not_live_seed(out_dir, REPO_ROOT)
        code, out, err = run_legacy(
            ["alternative_ranker.py", "--seed-dir", SEED_DIR, "--source-drug",
             "clopidogrel", "--profile-id", "P2_cyp2c19_poor", "--current-drugs",
             "clopidogrel,voriconazole,codeine,warfarin,amitriptyline",
             "--candidate-file", "candidate_alternatives.csv",
             "--graph-file", "drug_graph_edges.csv", "--out-dir", out_dir],
            cwd=REPO_ROOT)
        cls.exit_code, cls.stderr, cls.out_dir = code, err, out_dir
        path = os.path.join(out_dir, "alternative_result_full.json")
        cls.result = read_json(path) if os.path.exists(path) else {}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _candidates(self):
        return {c.get("candidate_drug"): c
                for c in self.result.get("candidate_results", [])}

    def test_run_succeeded(self):
        self.assertEqual(self.exit_code, 0, self.stderr[:500])

    def test_active_seed_hashes_are_unchanged(self):
        self.assertEqual(seed_hashes(), self.before)

    def test_prasugrel_and_ticagrelor_are_present(self):
        candidates = self._candidates()
        self.assertIn("prasugrel", candidates)
        self.assertIn("ticagrelor", candidates)

    def test_both_report_insufficient_pgx_rule_data(self):
        for name, entry in self._candidates().items():
            if name in ("prasugrel", "ticagrelor"):
                self.assertEqual(entry.get("mvp_data_status"),
                                 "insufficient_pgx_rule_data", name)

    def test_score_is_recorded_but_never_protected_as_correct(self):
        self.require_baseline()
        snap = snapshot("alternative-beta-clopidogrel")
        disposition = snap["score_disposition"]
        self.assertEqual(disposition["bug_id"], "LEGACY-BUG-009")
        self.assertIs(disposition["protected_as_correct"], False)
        registered = {b["bug_id"]: b for b in manifest()["legacy_bugs"]}
        self.assertIs(registered["LEGACY-BUG-009"]["protected_as_correct"], False)

    def test_a_score_exists_alongside_insufficient_data(self):
        """The defect itself: a number attached to a candidate with no usable rule."""
        candidates = self._candidates()
        for name in ("prasugrel", "ticagrelor"):
            self.assertEqual(candidates[name].get("mvp_data_status"),
                             "insufficient_pgx_rule_data")
            self.assertIsNotNone(candidates[name].get("score"), name)

    def test_snapshot_makes_no_candidate_preference_claim(self):
        self.require_baseline()
        snap = snapshot("alternative-beta-clopidogrel")
        self.assertIn("no_candidate_preference_claim", snap)
        for entry in snap["candidate_results"]:
            self.assertNotIn("safer", str(entry).lower())
            self.assertNotIn("preferred", str(entry).lower())

    def test_missing_candidate_file_fails_precisely(self):
        with self.assertRaises(LegacyRunError) as ctx:
            require_files(REPO_ROOT, ["__no_candidates__.csv"], "candidate regression")
        self.assertIn("__no_candidates__.csv", str(ctx.exception))


class TestPreservation(BaselineRequiredMixin, unittest.TestCase):
    """Group G: WP-01 changed nothing it was told to preserve."""

    def _expected(self, path):
        for artifact in manifest()["artifacts"]:
            if artifact["path"] == path:
                return artifact
        self.fail("manifest does not cover %s" % path)

    def test_seven_legacy_modules_are_byte_identical(self):
        for name in LEGACY_MODULES:
            artifact = self._expected(name)
            full = os.path.join(REPO_ROOT, name)
            self.assertTrue(os.path.isfile(full), name)
            self.assertEqual(sha256_file(full), artifact["sha256"], name)
            self.assertEqual(os.path.getsize(full), artifact["size_bytes"], name)

    def test_architecture_md_is_byte_identical(self):
        artifact = self._expected("architecture.md")
        self.assertEqual(sha256_file(os.path.join(REPO_ROOT, "architecture.md")),
                         artifact["sha256"])

    def test_wp00_docs_code_and_tests_are_byte_identical(self):
        for name in WP00_FILES:
            artifact = self._expected(name)
            self.assertEqual(sha256_file(os.path.join(REPO_ROOT, name)),
                             artifact["sha256"], name)

    def test_legacy_data_and_output_artifacts_are_byte_identical(self):
        mismatched = []
        for artifact in manifest()["artifacts"]:
            if artifact["role"] not in ("legacy_seed_dataset", "legacy_seed_backup",
                                        "legacy_raw_output", "legacy_derived_output",
                                        "legacy_report_artifact",
                                        "legacy_candidate_seed",
                                        "legacy_historical_doc"):
                continue
            full = os.path.join(REPO_ROOT, artifact["path"])
            if not os.path.isfile(full) or sha256_file(full) != artifact["sha256"]:
                mismatched.append(artifact["path"])
        self.assertEqual(mismatched, [])

    def test_wp00_approval_status_was_not_changed(self):
        from pgx.domain.claims import (CLAIM_BOUNDARY_STATUS, P0_CLAIM_BOUNDARY)
        self.assertEqual(CLAIM_BOUNDARY_STATUS,
                         "DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW")
        self.assertFalse(P0_CLAIM_BOUNDARY.is_approved)

    def test_wp01_baseline_does_not_absorb_wp02_artifacts(self):
        """The WP-01 manifest must not claim ownership of WP-02 files.

        Amended during the WP-02 phase transition. The original assertion was
        that files like ``pyproject.toml`` must not exist at all, which was true
        only while WP-02 had not started. WP-02 was required to create exactly
        those files, so the assertion is now inverted to the property that
        actually matters and stays true forever: whatever later work packages
        add, the frozen WP-01 baseline neither hashes nor owns it.

        The legacy artifacts themselves are unchanged; that is asserted by the
        other tests in this class.
        """
        self.require_baseline()
        document = manifest()
        legacy_paths = {artifact["path"] for artifact in document["artifacts"]}
        evidence_paths = {artifact["path"]
                          for artifact in document.get("evidence_artifacts", [])}

        wp02_artifacts = (
            "pyproject.toml", "uv.lock", "docker-compose.yml", "Dockerfile",
            "alembic.ini", "README.md", ".env.example",
            "migrations/env.py", "migrations/versions/0001_wp02_foundation.py",
            "pgx/domain/models.py", "pgx/domain/enums.py",
            "pgx/domain/identifiers.py", "pgx/domain/hashing.py",
            "pgx/domain/immutable.py", "pgx/domain/ports.py",
            "pgx/infrastructure/db/models.py",
            "pgx/infrastructure/db/repositories.py",
            "pgx/infrastructure/db/cli_seed.py",
            "tests/unit/domain/test_models.py",
            "tests/integration/db/test_migrations.py",
        )
        for path in wp02_artifacts:
            self.assertNotIn(path, legacy_paths,
                             "WP-01 legacy baseline must not own %s" % path)
            self.assertNotIn(path, evidence_paths,
                             "WP-01 evidence chain must not own %s" % path)

        for path in legacy_paths | evidence_paths:
            self.assertFalse(path.startswith("pgx/domain/enums"), path)
            self.assertFalse(path.startswith("pgx/infrastructure/"), path)
            self.assertFalse(path.startswith("migrations/"), path)

    def test_wp01_baseline_scope_is_unchanged(self):
        """The amendment must not have grown or shrunk the baseline."""
        self.require_baseline()
        document = manifest()
        self.assertEqual(len(document["artifacts"]), 64)
        self.assertEqual(len(document["evidence_artifacts"]), 22)


if __name__ == "__main__":
    unittest.main(verbosity=2)
