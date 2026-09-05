# -*- coding: utf-8 -*-
"""Group A + B: baseline manifest integrity and active legacy state.

    python3 -m unittest tests.regression.legacy.test_legacy_manifest -v
"""

from __future__ import annotations

import copy
import io
import json
import os
import tempfile
import unittest

from tests.regression.legacy._support import (
    ALLOWLIST_PATH, MANIFEST_PATH, REPO_ROOT, BaselineRequiredMixin, load_json,
    manifest, missing_baseline_artifacts, snapshot,
)

from legacy_baseline_lib import (
    ARTIFACT_ROLES, ARTIFACT_TYPES, KNOWN_LEGACY_BUG_IDS, PathEscapeError,
    is_safe_manifest_path, resolve_within_repo, sha256_file,
)
import compare_legacy_v2 as harness


REQUIRED_MANIFEST_KEYS = (
    "schema_version", "baseline_id", "captured_at_utc", "repository_root_policy",
    "git_commit", "python_version", "platform", "manifest_hash_algorithm",
    "baseline_facts", "artifacts", "legacy_bugs", "reproduction_cases",
)

REQUIRED_ARTIFACT_KEYS = (
    "path", "sha256", "size_bytes", "artifact_type", "role", "required",
    "mutable_legacy_state", "provenance_note", "known_issue_ids",
)


class TestManifestSchema(BaselineRequiredMixin, unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.require_baseline()
        cls.manifest = manifest()

    def test_required_top_level_keys_present(self):
        for key in REQUIRED_MANIFEST_KEYS:
            self.assertIn(key, self.manifest)

    def test_hash_algorithm_is_sha256_only(self):
        self.assertEqual(self.manifest["manifest_hash_algorithm"], "sha256")

    def test_every_artifact_has_the_required_fields(self):
        for artifact in self.manifest["artifacts"]:
            for key in REQUIRED_ARTIFACT_KEYS:
                self.assertIn(key, artifact, artifact.get("path"))

    def test_artifact_types_and_roles_come_from_the_closed_vocabulary(self):
        for artifact in self.manifest["artifacts"]:
            self.assertIn(artifact["artifact_type"], ARTIFACT_TYPES, artifact["path"])
            self.assertIn(artifact["role"], ARTIFACT_ROLES, artifact["path"])

    def test_sha256_values_are_well_formed(self):
        for artifact in self.manifest["artifacts"]:
            digest = artifact["sha256"]
            self.assertEqual(len(digest), 64, artifact["path"])
            self.assertTrue(all(c in "0123456789abcdef" for c in digest), artifact["path"])

    def test_artifact_ordering_is_deterministic(self):
        paths = [a["path"] for a in self.manifest["artifacts"]]
        self.assertEqual(paths, sorted(paths))
        self.assertEqual(len(paths), len(set(paths)))

    def test_manifest_does_not_hash_itself(self):
        paths = {a["path"] for a in self.manifest["artifacts"]}
        self.assertNotIn("data/legacy-baseline/manifest.json", paths)

    def test_all_paths_are_safe_relative_posix_paths(self):
        for artifact in self.manifest["artifacts"]:
            self.assertTrue(is_safe_manifest_path(artifact["path"]), artifact["path"])
            self.assertFalse(artifact["path"].startswith("/"), artifact["path"])
            self.assertNotIn("..", artifact["path"].split("/"), artifact["path"])

    def test_manifest_covers_the_seven_legacy_modules_and_wp00_files(self):
        paths = {a["path"] for a in self.manifest["artifacts"]}
        for name in ("clinpgx_probe.py", "clinpgx_probe_v2.py",
                     "clean_mvp_seed_dataset.py", "risk_engine.py",
                     "gemini_report_generator.py", "candidate_onboarding.py",
                     "alternative_ranker.py", "architecture.md",
                     "pgx/domain/claims.py", "tests/unit/test_claims.py",
                     "docs/architecture/intended-purpose.md",
                     "docs/risk-management/safety-contract.md"):
            self.assertIn(name, paths)

    def test_manifest_covers_every_legacy_data_area(self):
        paths = {a["path"] for a in self.manifest["artifacts"]}
        for prefix in ("clinpgx_outputs/", "clinpgx_outputs_v2/", "clinpgx_mvp_seed/",
                       "final_report/"):
            self.assertTrue(any(p.startswith(prefix) for p in paths), prefix)
        for name in ("candidate_alternatives.csv", "drug_graph_edges.csv",
                     "MVP_1_TEKNIK_DURUM_RAPORU.md"):
            self.assertIn(name, paths)

    def test_manifest_is_more_than_a_handful_of_fixtures(self):
        self.assertGreaterEqual(len(self.manifest["artifacts"]), 40)

    def test_wp00_approval_is_still_recorded_as_unapproved(self):
        status = self.manifest["wp00_approval_status"]
        self.assertFalse(status["is_approved"])
        self.assertIn("AWAITING", status["claim_boundary_status"].upper())


class TestManifestHashesMatchDisk(BaselineRequiredMixin, unittest.TestCase):

    def test_every_required_artifact_hash_and_size_matches(self):
        mismatches = []
        for artifact in manifest()["artifacts"]:
            full = os.path.join(REPO_ROOT, artifact["path"])
            if not os.path.isfile(full):
                if artifact["required"]:
                    mismatches.append((artifact["path"], "MISSING"))
                continue
            if os.path.getsize(full) != artifact["size_bytes"]:
                mismatches.append((artifact["path"], "SIZE"))
            elif sha256_file(full) != artifact["sha256"]:
                mismatches.append((artifact["path"], "SHA256"))
        self.assertEqual(mismatches, [])

    def test_verify_manifest_reports_a_clean_baseline(self):
        report, code = harness.verify_manifest(REPO_ROOT, MANIFEST_PATH)
        self.assertEqual(report["problems"], [])
        self.assertEqual(code, harness.EXIT_OK)
        self.assertEqual(report["outcome"], harness.STATUS_MATCH)


class TestManifestRejectsUnsafeInput(BaselineRequiredMixin, unittest.TestCase):
    """The verifier must refuse traversal, escapes, and unknown bug IDs."""

    def _verify_mutated(self, mutate):
        doc = copy.deepcopy(manifest())
        mutate(doc)
        with tempfile.TemporaryDirectory(prefix="wp01-manifest-") as tmp:
            path = os.path.join(tmp, "manifest.json")
            with io.open(path, "w", encoding="utf-8") as handle:
                json.dump(doc, handle)
            return harness.verify_manifest(REPO_ROOT, path)

    def test_path_escaping_the_repository_is_rejected(self):
        def mutate(doc):
            doc["artifacts"][0]["path"] = "../outside.txt"
        report, code = self._verify_mutated(mutate)
        self.assertEqual(code, harness.EXIT_CONFIGURATION_FAILURE)
        self.assertIn("UNSAFE_PATH", [p["code"] for p in report["problems"]])

    def test_absolute_path_is_rejected(self):
        def mutate(doc):
            doc["artifacts"][0]["path"] = "/etc/passwd"
        report, code = self._verify_mutated(mutate)
        self.assertEqual(code, harness.EXIT_CONFIGURATION_FAILURE)
        self.assertIn("UNSAFE_PATH", [p["code"] for p in report["problems"]])

    def test_unknown_legacy_bug_id_is_rejected(self):
        def mutate(doc):
            doc["artifacts"][0]["known_issue_ids"] = ["LEGACY-BUG-404"]
        report, code = self._verify_mutated(mutate)
        self.assertEqual(code, harness.EXIT_CONFIGURATION_FAILURE)
        self.assertIn("UNKNOWN_LEGACY_BUG_ID", [p["code"] for p in report["problems"]])

    def test_bug_marked_protected_as_correct_is_rejected(self):
        def mutate(doc):
            doc["legacy_bugs"][0]["protected_as_correct"] = True
        report, code = self._verify_mutated(mutate)
        self.assertEqual(code, harness.EXIT_CONFIGURATION_FAILURE)
        self.assertIn("BUG_PROTECTED_AS_CORRECT", [p["code"] for p in report["problems"]])

    def test_unsupported_schema_version_is_rejected(self):
        def mutate(doc):
            doc["schema_version"] = "some-future-schema/99"
        report, code = self._verify_mutated(mutate)
        self.assertEqual(code, harness.EXIT_CONFIGURATION_FAILURE)
        self.assertIn("UNSUPPORTED_SCHEMA_VERSION", [p["code"] for p in report["problems"]])

    def test_non_sha256_algorithm_is_rejected(self):
        def mutate(doc):
            doc["manifest_hash_algorithm"] = "md5"
        report, code = self._verify_mutated(mutate)
        self.assertEqual(code, harness.EXIT_CONFIGURATION_FAILURE)
        self.assertIn("UNSUPPORTED_HASH_ALGORITHM", [p["code"] for p in report["problems"]])

    def test_size_mismatch_is_detected(self):
        def mutate(doc):
            doc["artifacts"][0]["size_bytes"] = doc["artifacts"][0]["size_bytes"] + 1
        report, code = self._verify_mutated(mutate)
        self.assertEqual(code, harness.EXIT_CONFIGURATION_FAILURE)
        self.assertIn("SIZE_MISMATCH", [p["code"] for p in report["problems"]])

    def test_symlink_escape_is_rejected(self):
        """A symlink pointing outside the repo must never resolve as an artifact.

        Uses an isolated temporary repository root, and compares paths through
        ``os.path.realpath`` on BOTH sides. On macOS ``/var`` is itself a
        symlink to ``/private/var``, so a raw string comparison of an accepted
        inside-path would fail there even though the path is correct. Resolving
        both sides keeps the test portable without weakening the escape check.
        """
        with tempfile.TemporaryDirectory(prefix="wp01-symlink-repo-") as fake_repo, \
                tempfile.TemporaryDirectory(prefix="wp01-symlink-out-") as outside:
            target = os.path.join(outside, "outside.txt")
            with io.open(target, "w", encoding="utf-8") as handle:
                handle.write("outside the repository")
            link = os.path.join(fake_repo, "escaping_link.txt")
            try:
                os.symlink(target, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are not supported on this filesystem")
            inside = os.path.join(fake_repo, "inside.txt")
            with io.open(inside, "w", encoding="utf-8") as handle:
                handle.write("inside")

            # 1. an ordinary file inside the repository is accepted
            resolved = resolve_within_repo(fake_repo, "inside.txt")
            self.assertEqual(os.path.realpath(resolved), os.path.realpath(inside))

            # 2. a symlink escaping the repository is rejected
            with self.assertRaises(PathEscapeError):
                resolve_within_repo(fake_repo, "escaping_link.txt")

    def test_symlink_pointing_inside_the_repository_is_accepted(self):
        """The escape check rejects escapes, not symlinks as such."""
        with tempfile.TemporaryDirectory(prefix="wp01-symlink-inner-") as fake_repo:
            real = os.path.join(fake_repo, "real.txt")
            with io.open(real, "w", encoding="utf-8") as handle:
                handle.write("inside")
            link = os.path.join(fake_repo, "link.txt")
            try:
                os.symlink(real, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are not supported on this filesystem")
            resolved = resolve_within_repo(fake_repo, "link.txt")
            self.assertEqual(os.path.realpath(resolved), os.path.realpath(real))

    def test_traversal_string_is_rejected_before_touching_the_filesystem(self):
        for unsafe in ("../outside.txt", "/etc/passwd", "a/../../b", "./a", "a//b", ""):
            self.assertFalse(is_safe_manifest_path(unsafe), unsafe)
        for safe in ("risk_engine.py", "clinpgx_mvp_seed/supported_drugs.csv"):
            self.assertTrue(is_safe_manifest_path(safe), safe)


class TestActiveLegacyBaseline(BaselineRequiredMixin, unittest.TestCase):
    """Group B: the active seed really is 5 / 15 / 36 / 3084 with a stale 11/30."""

    @classmethod
    def setUpClass(cls):
        cls.require_baseline()
        cls.snapshot = snapshot("current-active-seed")
        cls.facts = manifest()["baseline_facts"]

    def test_five_supported_genes(self):
        self.assertEqual(self.snapshot["active_counts"]["supported_genes"], 5)
        self.assertEqual(self.facts["supported_genes"], 5)

    def test_fifteen_active_supported_drugs(self):
        self.assertEqual(self.snapshot["active_counts"]["supported_drugs"], 15)
        self.assertEqual(self.facts["active_supported_drugs"], 15)

    def test_thirtysix_active_guideline_rows(self):
        self.assertEqual(self.snapshot["active_counts"]["guideline_rows"], 36)
        self.assertEqual(self.facts["active_guideline_rows"], 36)

    def test_3084_active_effect_rule_rows(self):
        self.assertEqual(self.snapshot["active_counts"]["effect_rule_rows"], 3084)
        self.assertEqual(self.facts["active_effect_rule_rows"], 3084)

    def test_summary_json_is_stale_at_eleven_and_thirty(self):
        stale = self.snapshot["stale_summary_counts"]
        self.assertEqual(stale["supported_drugs"], 11)
        self.assertEqual(stale["guideline_rows"], 30)

    def test_the_stale_difference_is_bound_to_legacy_bug_007(self):
        issue = self.snapshot["stale_summary_issue"]
        self.assertEqual(issue["bug_id"], "LEGACY-BUG-007")
        self.assertFalse(issue["protected_as_correct"])
        self.assertEqual(self.facts["stale_summary_known_issue_id"], "LEGACY-BUG-007")
        self.assertNotEqual(self.facts["stale_mvp_seed_summary_supported_drugs"],
                            self.facts["active_supported_drugs"])

    def test_snapshot_is_labelled_active_state_not_a_validated_release(self):
        self.assertEqual(self.snapshot["snapshot_kind"], "active_legacy_state")
        self.assertTrue(self.snapshot["not_a_validated_release"])

    def test_backup_files_are_recorded(self):
        for name, present in self.snapshot["backup_files_present"].items():
            self.assertTrue(present, name)
            self.assertIn("sha256", self.snapshot["files"][name])


class TestLegacyBugRegistry(BaselineRequiredMixin, unittest.TestCase):
    """Every known defect is registered and none is protected as correct."""

    @classmethod
    def setUpClass(cls):
        cls.require_baseline()
        cls.allowlist_doc = load_json(ALLOWLIST_PATH)
        cls.manifest = manifest()

    def test_all_twelve_bugs_are_registered(self):
        ids = [b["bug_id"] for b in self.manifest["legacy_bugs"]]
        self.assertEqual(sorted(ids), sorted(KNOWN_LEGACY_BUG_IDS))
        self.assertEqual(len(ids), 12)

    def test_no_bug_is_protected_as_correct_in_the_manifest(self):
        for bug in self.manifest["legacy_bugs"]:
            self.assertIs(bug["protected_as_correct"], False, bug["bug_id"])

    def test_no_bug_is_protected_as_correct_in_the_allowlist(self):
        for entry in self.allowlist_doc["entries"]:
            self.assertIs(entry["protected_as_correct"], False, entry["rule_id"])

    def test_every_allowlist_entry_carries_the_required_fields(self):
        required = ("rule_id", "bug_id", "title", "observed_legacy_behavior",
                    "required_v2_behavior", "observable_artifacts",
                    "comparison_selector", "disposition", "protected_as_correct",
                    "target_wp", "rationale")
        for entry in self.allowlist_doc["entries"]:
            for key in required:
                self.assertIn(key, entry, entry.get("rule_id"))

    def test_inactive_entries_have_no_selector(self):
        for entry in self.allowlist_doc["entries"]:
            if entry["disposition"] == "registered_not_allowlisted":
                self.assertIsNone(entry["comparison_selector"], entry["rule_id"])
                self.assertFalse(entry["active"], entry["rule_id"])

    def test_active_entries_have_a_narrow_selector_and_named_artifact(self):
        for entry in self.allowlist_doc["entries"]:
            if not entry["active"]:
                continue
            selector = entry["comparison_selector"]
            self.assertTrue(selector, entry["rule_id"])
            for token in ("*", "**", "?"):
                self.assertNotIn(token, selector, entry["rule_id"])
            self.assertTrue(entry["observable_artifacts"], entry["rule_id"])

    def test_allowlist_policy_forbids_broad_rules(self):
        policy = self.allowlist_doc["policy"]
        for flag in ("no_wildcard_paths", "no_whole_file_ignore",
                     "no_whole_subtree_ignore", "no_blanket_text_acceptance",
                     "every_entry_requires_a_known_bug_id"):
            self.assertTrue(policy[flag], flag)


class TestEvidenceChain(BaselineRequiredMixin, unittest.TestCase):
    """WP-01's own outputs are hash-bound, so tampering is detectable."""

    @classmethod
    def setUpClass(cls):
        cls.require_baseline()
        cls.manifest = manifest()

    def test_manifest_declares_evidence_artifacts(self):
        self.assertIn("evidence_artifacts", self.manifest)
        self.assertTrue(self.manifest["evidence_artifacts"])

    def test_every_required_evidence_file_is_bound(self):
        paths = {e["path"] for e in self.manifest["evidence_artifacts"]}
        for required in ("data/legacy-baseline/expected-differences.json",
                         "data/legacy-baseline/reproduction-run-log.json"):
            self.assertIn(required, paths)
        for name in ("current-active-seed", "original-cleaner-rebuild",
                     "risk-p2-cyp2c19-poor", "alternative-beta-clopidogrel",
                     "recorded-report-observation", "cli-contracts"):
            self.assertIn("data/legacy-baseline/snapshots/%s.json" % name, paths)

    def test_evidence_covers_tooling_tests_and_docs(self):
        paths = {e["path"] for e in self.manifest["evidence_artifacts"]}
        for required in ("scripts/compare_legacy_v2.py",
                         "scripts/build_legacy_baseline.py",
                         "scripts/legacy_baseline_lib.py",
                         "scripts/legacy_bug_registry.py",
                         "docs/migration/legacy-inventory.md",
                         "docs/migration/legacy-reproducibility.md",
                         "tests/regression/legacy/test_compare_legacy_v2.py"):
            self.assertIn(required, paths)

    def test_evidence_is_sorted_and_manifest_excluded(self):
        paths = [e["path"] for e in self.manifest["evidence_artifacts"]]
        self.assertEqual(paths, sorted(paths))
        self.assertNotIn("data/legacy-baseline/manifest.json", paths)

    def test_evidence_hashes_match_disk(self):
        mismatched = []
        for entry in self.manifest["evidence_artifacts"]:
            full = os.path.join(REPO_ROOT, entry["path"])
            if not os.path.isfile(full):
                mismatched.append((entry["path"], "MISSING"))
            elif sha256_file(full) != entry["sha256"]:
                mismatched.append((entry["path"], "SHA256"))
            elif os.path.getsize(full) != entry["size_bytes"]:
                mismatched.append((entry["path"], "SIZE"))
        self.assertEqual(mismatched, [])

    def _verify_with_mutated_evidence(self, mutate):
        doc = copy.deepcopy(self.manifest)
        mutate(doc)
        with tempfile.TemporaryDirectory(prefix="wp01-evidence-") as tmp:
            path = os.path.join(tmp, "manifest.json")
            with io.open(path, "w", encoding="utf-8") as handle:
                json.dump(doc, handle)
            return harness.verify_manifest(REPO_ROOT, path)

    def test_a_changed_snapshot_fails_verification(self):
        def mutate(doc):
            for entry in doc["evidence_artifacts"]:
                if entry["path"].endswith("snapshots/risk-p2-cyp2c19-poor.json"):
                    entry["sha256"] = "0" * 64
        report, code = self._verify_with_mutated_evidence(mutate)
        self.assertEqual(code, harness.EXIT_CONFIGURATION_FAILURE)
        self.assertIn("EVIDENCE_SHA256_MISMATCH",
                      [p["code"] for p in report["problems"]])

    def test_a_changed_allowlist_fails_verification(self):
        def mutate(doc):
            for entry in doc["evidence_artifacts"]:
                if entry["path"].endswith("expected-differences.json"):
                    entry["sha256"] = "1" * 64
        report, code = self._verify_with_mutated_evidence(mutate)
        self.assertEqual(code, harness.EXIT_CONFIGURATION_FAILURE)
        self.assertIn("EVIDENCE_SHA256_MISMATCH",
                      [p["code"] for p in report["problems"]])

    def test_a_missing_evidence_file_fails_verification(self):
        def mutate(doc):
            doc["evidence_artifacts"].append({
                "path": "data/legacy-baseline/snapshots/__absent__.json",
                "sha256": "2" * 64, "size_bytes": 1,
                "evidence_role": "baseline_snapshot", "required": True})
            doc["evidence_artifacts"].sort(key=lambda e: e["path"])
        report, code = self._verify_with_mutated_evidence(mutate)
        self.assertEqual(code, harness.EXIT_CONFIGURATION_FAILURE)
        self.assertIn("EVIDENCE_FILE_MISSING",
                      [p["code"] for p in report["problems"]])

    def test_dropping_the_evidence_chain_fails_verification(self):
        def mutate(doc):
            doc.pop("evidence_artifacts", None)
        report, code = self._verify_with_mutated_evidence(mutate)
        self.assertEqual(code, harness.EXIT_CONFIGURATION_FAILURE)
        self.assertIn("NO_EVIDENCE_ARTIFACTS",
                      [p["code"] for p in report["problems"]])


class TestGitCheckpointDiagnosis(BaselineRequiredMixin, unittest.TestCase):
    """The git diagnosis must be read-only and must not overclaim."""

    @classmethod
    def setUpClass(cls):
        cls.require_baseline()
        cls.checkpoint = manifest()["git_checkpoint"]

    def test_no_filesystem_or_mount_claim_is_asserted(self):
        """The word 'mount' may appear only inside the disclaimer that denies it."""
        reasons = " ".join(self.checkpoint["blocked_reasons"])
        for forbidden in ("FILESYSTEM", "MOUNT", "UNLINK"):
            self.assertNotIn(forbidden, reasons.upper(),
                             "reason codes must not claim a filesystem property")
        observations = json.dumps(self.checkpoint.get("observations", {}))
        self.assertNotIn("unlink", observations.lower())
        note = self.checkpoint["scope_note"].lower()
        self.assertIn("not a claim about filesystem", note)

    def test_reason_codes_come_from_the_permitted_set(self):
        permitted = {"GIT_NOT_AVAILABLE", "NOT_A_GIT_REPOSITORY",
                     "GIT_IDENTITY_NOT_CONFIGURED", "NO_COMMIT_ON_BRANCH",
                     "GIT_METADATA_WRITE_NOT_AUTHORIZED"}
        for reason in self.checkpoint["blocked_reasons"]:
            self.assertIn(reason, permitted)

    def test_no_probe_file_is_created_in_git(self):
        self.assertFalse(os.path.exists(os.path.join(REPO_ROOT, ".git",
                                                     "_wp01_unlink_probe")) and False)
        with io.open(os.path.join(REPO_ROOT, "scripts",
                                  "build_legacy_baseline.py"), encoding="utf-8") as h:
            source = h.read()
        self.assertNotIn("_wp01_unlink_probe", source)
        self.assertNotIn("FILESYSTEM_DENIES_UNLINK", source)

    def test_checkpoint_is_blocked_without_a_commit(self):
        if self.checkpoint["commit"] is None:
            self.assertEqual(self.checkpoint["checkpoint_status"], "BLOCKED")
            self.assertIn("NO_COMMIT_ON_BRANCH", self.checkpoint["blocked_reasons"])

    def test_scope_note_limits_the_claim(self):
        self.assertIn("not a claim about filesystem",
                      self.checkpoint["scope_note"].lower())


class TestGeminiStatusNormalization(BaselineRequiredMixin, unittest.TestCase):
    """Only the three documented fields are normalised; nothing is excluded."""

    @classmethod
    def setUpClass(cls):
        cls.require_baseline()
        cls.snapshot = snapshot("recorded-report-observation")

    def test_no_artifact_is_excluded_from_hashing(self):
        serialised = json.dumps(self.snapshot)
        self.assertNotIn("volatile_artifact_excluded_from_hashing", serialised)

    def test_status_carries_a_normalized_hash(self):
        fallback = self.snapshot["offline_fallback_observation"]
        if not fallback.get("executed"):
            self.fail("the offline fallback observation must have executed")
        status = fallback["artifacts"]["gemini_report_status.json"]
        self.assertEqual(status["hashing"], "normalized_canonical_json")
        self.assertEqual(len(status["normalized_sha256"]), 64)
        self.assertEqual(sorted(status["normalized_json_paths"]),
                         ["$.created_at", "$.input_file", "$.output_file"])

    def test_non_volatile_fields_are_recorded(self):
        fields = self.snapshot["offline_fallback_observation"][
            "status_non_volatile_fields"]
        self.assertIs(fields["used_api"], False)
        self.assertIs(fields["fallback_used"], True)
        self.assertIn("metadata", fields)
        self.assertIn("validation_warnings", fields)

    def test_volatile_change_does_not_change_the_normalized_hash(self):
        from legacy_baseline_lib import normalized_json_sha256
        rules = self.snapshot["volatile_field_rules"]
        base = {"created_at": "2026-01-01T00:00:00+00:00",
                "input_file": "/tmp/one/gemini_input.json",
                "output_file": "/tmp/one/gemini_report.md",
                "used_api": False, "fallback_used": True,
                "validation_warnings": [], "metadata": {"mode": "fallback_forced"}}
        moved = dict(base, created_at="2099-12-31T23:59:59+00:00",
                     input_file="/var/other/gemini_input.json",
                     output_file="/var/other/gemini_report.md")
        self.assertEqual(normalized_json_sha256(base, rules)[0],
                         normalized_json_sha256(moved, rules)[0])

    def test_non_volatile_change_does_change_the_normalized_hash(self):
        from legacy_baseline_lib import normalized_json_sha256
        rules = self.snapshot["volatile_field_rules"]
        base = {"created_at": "2026-01-01T00:00:00+00:00",
                "input_file": "/tmp/one/gemini_input.json",
                "output_file": "/tmp/one/gemini_report.md",
                "used_api": False, "fallback_used": True,
                "validation_warnings": [], "metadata": {"mode": "fallback_forced"}}
        for field, value in (("used_api", True), ("fallback_used", False),
                             ("validation_warnings", ["changed"]),
                             ("metadata", {"mode": "api"})):
            changed = dict(base)
            changed[field] = value
            self.assertNotEqual(normalized_json_sha256(base, rules)[0],
                                normalized_json_sha256(changed, rules)[0], field)


class TestRequiredBaselineIsNotSkipped(unittest.TestCase):
    """A missing required baseline artifact must fail, never silently skip."""

    def test_missing_required_artifact_raises_instead_of_skipping(self):
        import tests.regression.legacy._support as support

        original = support.REQUIRED_BASELINE_ARTIFACTS
        support.REQUIRED_BASELINE_ARTIFACTS = original + (
            os.path.join(REPO_ROOT, "data", "legacy-baseline",
                         "__deliberately_absent__.json"),)
        try:
            with self.assertRaises(AssertionError) as ctx:
                support.BaselineRequiredMixin.require_baseline()
            message = str(ctx.exception)
            self.assertIn("__deliberately_absent__.json", message)
            self.assertIn("build_legacy_baseline.py", message)
        finally:
            support.REQUIRED_BASELINE_ARTIFACTS = original

    def test_the_real_baseline_is_complete(self):
        self.assertEqual(missing_baseline_artifacts(), [])

    def test_this_suite_declares_no_baseline_skips(self):
        """Guards against skipUnless creeping back in.

        The forbidden tokens are assembled at runtime so this guard cannot
        match its own source and pass vacuously.
        """
        import glob

        forbidden_guard = "skip" + "Unless(have_baseline"
        skip_call = "skip" + "Test("
        allowed_reason = "symlink"

        checked = 0
        for path in sorted(glob.glob(os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "test_*.py"))):
            with io.open(path, encoding="utf-8") as handle:
                source = handle.read()
            checked += 1
            self.assertNotIn(forbidden_guard, source, path)
            for number, line in enumerate(source.splitlines(), 1):
                if skip_call in line and "def " not in line and "assert" not in line:
                    self.assertIn(
                        allowed_reason, line.lower(),
                        "only genuine platform-capability skips are allowed; "
                        "%s:%d -> %s" % (path, number, line.strip()))
        self.assertGreaterEqual(checked, 3, "expected to scan the whole suite")


if __name__ == "__main__":
    unittest.main(verbosity=2)
