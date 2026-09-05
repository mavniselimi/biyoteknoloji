# -*- coding: utf-8 -*-
"""The ``pgx-coverage`` CLI and the WP-13 gate status.

A command-line tool is where a boundary is most likely to be argued with, so
most of this file is about what the tool refuses. It cannot approve a manifest,
assign a reviewer, calculate attention, execute an assessment, force an invalid
manifest through, load a legacy CSV as coverage configuration, or reach a
ruleset except through the frozen registry. Each of those is checked twice -
once as a command that does not exist, once as a flag that is refused by name -
because the two failures look different to somebody trying to get past them.

The gate status is the other half: a report, computed from the real repository,
of why no real coverage claim can exist yet. It is deliberately not a constant.
Every count in it is read off disk, so the day any of it changes the report
changes and the change is visible in a diff.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import unittest

from pgx.application.coverage_cli import (EXIT_OK, EXIT_REFUSED,
                                          REFUSED_FLAGS, build_parser, main,
                                          refuse_unsafe_flags)
from pgx.application.coverage_gate_status import (BLOCKER_CODES,
                                                  COVERAGE_GATE_STATUS_VERSION,
                                                  DEFAULT_COVERAGE_ROOT,
                                                  GATE_STATUS_FILENAME,
                                                  build_coverage_gate_status)
from pgx.engine.coverage import COVERAGE_ENGINE_CONTRACT_VERSION
from tests.unit.engine._coverage_support import (COVERAGE_ROOT, GATE_STATUS,
                                                 REGRESSION_REPORT, REPO_ROOT,
                                                 SyntheticWorld)


def run(*argv):
    """Run the CLI, capturing stdout. Returns ``(exit_code, text)``."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(list(argv))
    return code, buffer.getvalue()


def run_json(*argv):
    code, text = run(*argv)
    return code, json.loads(text)


class TestTheToolRefusesWhatItMustNotDo(unittest.TestCase):

    def test_there_is_no_command_that_approves_or_assesses(self):
        commands = set()
        for action in build_parser()._actions:
            if getattr(action, "choices", None):
                commands.update(action.choices)
        self.assertEqual(commands, {
            "validate-manifest", "verify-manifest", "inspect-scope",
            "inspect-axes", "evaluate", "truth-table", "list-issue-codes",
            "legacy-regression", "verify-regression", "gate-status"})

    def test_every_refused_flag_is_refused_with_a_reason(self):
        for flag in REFUSED_FLAGS:
            with self.subTest(flag=flag):
                code, payload = run_json(flag)
                self.assertEqual(code, EXIT_REFUSED)
                self.assertTrue(payload["refused"])
                self.assertEqual(payload["code"], "FLAG_REFUSED")
                self.assertIn(flag, payload["error"])

    def test_a_refused_flag_is_refused_before_anything_is_read(self):
        """Checked ahead of argument parsing, so ``--force`` cannot be
        rejected only after the tool has already done half the work."""
        code, payload = run_json("gate-status", "--force")
        self.assertEqual(code, EXIT_REFUSED)
        self.assertEqual(payload["code"], "FLAG_REFUSED")

    def test_a_refused_flag_with_a_value_is_still_refused(self):
        for flag in REFUSED_FLAGS:
            with self.subTest(flag=flag):
                self.assertIsNotNone(refuse_unsafe_flags([flag + "=yes"]))

    def test_an_abbreviated_flag_cannot_reach_anything(self):
        parser = build_parser()
        self.assertFalse(parser.allow_abbrev)
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                parser.parse_args(["--rep", "x", "gate-status"])

    def test_the_nine_refusals_cover_the_named_shortcuts(self):
        self.assertEqual(set(REFUSED_FLAGS), {
            "--force", "--approve", "--as-reviewer", "--skip-evidence",
            "--infer-scope", "--from-structural-axes", "--attention",
            "--assume-covered", "--legacy-csv"})


class TestTheReadOnlyCommands(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.world = SyntheticWorld(expected_extra_gene=True)
        import tempfile
        cls.tmp = tempfile.mkdtemp()
        cls.manifest_path = os.path.join(cls.tmp, "manifest.json")
        with io.open(cls.manifest_path, "w", encoding="utf-8") as handle:
            json.dump(cls.world.manifest.to_json(), handle)

    @classmethod
    def tearDownClass(cls):
        import shutil
        cls.world.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_validate_manifest_accepts_a_valid_document(self):
        code, payload = run_json("validate-manifest", self.manifest_path)
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(payload["passed"])

    def test_validate_manifest_says_what_it_did_not_check(self):
        """Schema validity is not truth about a ruleset, and a tool that let
        the two be confused would be the most useful place to confuse them."""
        _code, payload = run_json("validate-manifest", self.manifest_path)
        self.assertIn("schema validation only", payload["note"])

    def test_validate_manifest_refuses_an_invalid_document(self):
        broken = os.path.join(self.tmp, "broken.json")
        document = self.world.manifest.to_json()
        document["overall_attention"] = "LOW"
        with io.open(broken, "w", encoding="utf-8") as handle:
            json.dump(document, handle)
        code, payload = run_json("validate-manifest", broken)
        self.assertEqual(code, EXIT_REFUSED)
        self.assertFalse(payload["passed"])
        self.assertTrue(payload["issues"])

    def test_verify_manifest_prints_the_pins_without_loading_them(self):
        code, payload = run_json("verify-manifest", self.manifest_path)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["declared_content_hash"],
                         self.world.manifest.content_hash())
        self.assertIn("does not load them", payload["note"])

    def test_inspect_scope_prints_the_declared_expected_genes(self):
        code, payload = run_json("inspect-scope", self.manifest_path)
        self.assertEqual(code, EXIT_OK)
        row = payload["declarations"][0]
        self.assertEqual(len(row["expected_gene_keys"]), 3)
        self.assertEqual(row["supported_axis_count"], 2)
        self.assertIn("never derived", payload["note"])

    def test_inspect_axes_prints_the_rule_behind_each_axis(self):
        code, payload = run_json("inspect-axes", self.manifest_path)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["axis_count"], 2)
        for axis in payload["axes"]:
            with self.subTest(axis=axis["gene_id"]):
                self.assertTrue(axis["rule_id"])
                self.assertTrue(axis["rule_content_hash"])

    def test_truth_table_prints_all_three_tables(self):
        code, payload = run_json("truth-table")
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["coverage_engine_contract_version"],
                         COVERAGE_ENGINE_CONTRACT_VERSION)
        self.assertEqual(len(payload["axis"]), 9)
        self.assertEqual(len(payload["medication"]), 7)
        self.assertEqual(len(payload["overall"]), 6)

    def test_the_truth_table_denies_producing_an_attention_level(self):
        _code, payload = run_json("truth-table")
        self.assertIn("no row produces an attention level",
                      payload["note"].lower())

    def test_truth_table_renders_as_text_too(self):
        code, text = run("truth-table", "--text")
        self.assertEqual(code, EXIT_OK)
        for level in ("-- axis --", "-- medication --", "-- overall --"):
            self.assertIn(level, text)

    def test_list_issue_codes_prints_every_published_code(self):
        from pgx.engine.coverage_validator import MANIFEST_ISSUE_CODES
        code, payload = run_json("list-issue-codes")
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(set(payload["manifest_issue_codes"]),
                         set(MANIFEST_ISSUE_CODES))
        self.assertEqual(set(payload["gate_blocker_codes"]),
                         set(BLOCKER_CODES))
        self.assertEqual(payload["expected_differences"]["entry_count"], 4)

    def test_evaluate_validates_a_coverage_result_document(self):
        path = os.path.join(self.tmp, "result.json")
        result = self.world.evaluate(medications=["DRUG:testdrug-alpha"],
                                     phenotypes={"GENE:TESTGENE1": "POOR"})
        with io.open(path, "w", encoding="utf-8") as handle:
            json.dump(result.to_json(), handle)
        code, payload = run_json("evaluate", path)
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["status"], result.status.value)

    def test_evaluate_says_it_cannot_produce_one_for_real_data(self):
        """Written here rather than relying on a sibling test having run:
        tests are independent, and a fixture created by whichever test sorts
        first is a dependency nobody declared."""
        path = os.path.join(self.tmp, "note-check.json")
        result = self.world.evaluate(medications=["DRUG:testdrug-alpha"],
                                     phenotypes={"GENE:TESTGENE1": "POOR"})
        with io.open(path, "w", encoding="utf-8") as handle:
            json.dump(result.to_json(), handle)
        _code, payload = run_json("evaluate", path)
        self.assertIn("does not have for real data", payload["note"])

    def test_a_missing_file_is_a_stated_refusal_not_a_traceback(self):
        code, payload = run_json("validate-manifest",
                                 os.path.join(self.tmp, "absent.json"))
        self.assertEqual(payload["code"], "FILE_NOT_FOUND")
        self.assertTrue(payload["refused"])

    def test_malformed_json_is_a_stated_refusal(self):
        path = os.path.join(self.tmp, "bad.json")
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        code, payload = run_json("validate-manifest", path)
        self.assertEqual(payload["code"], "INVALID_JSON")

    def test_no_command_writes_to_the_repository(self):
        """Only ``legacy-regression --out`` writes, and only where told."""
        before = sorted(os.listdir(COVERAGE_ROOT))
        for argv in (("truth-table",), ("list-issue-codes",),
                     ("gate-status",),
                     ("validate-manifest", self.manifest_path),
                     ("inspect-scope", self.manifest_path)):
            with self.subTest(command=argv[0]):
                run(*argv)
        self.assertEqual(sorted(os.listdir(COVERAGE_ROOT)), before)


class TestTheRegressionCommands(unittest.TestCase):

    def test_legacy_regression_reproduces_the_stored_report(self):
        code, payload = run_json("legacy-regression")
        self.assertEqual(code, EXIT_OK)
        with io.open(REGRESSION_REPORT, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), payload)

    def test_verify_regression_confirms_the_stored_report(self):
        code, payload = run_json("verify-regression")
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(payload["matches"])
        self.assertEqual(payload["stored_hash"], payload["rebuilt_hash"])
        self.assertEqual(payload["unexpected_differences"], 0)

    def test_verify_regression_refuses_a_stale_report(self):
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "stale.json")
            with io.open(REGRESSION_REPORT, encoding="utf-8") as handle:
                document = json.load(handle)
            document["case_count"] = 999
            with io.open(path, "w", encoding="utf-8") as handle:
                json.dump(document, handle)
            code, payload = run_json("verify-regression", "--path", path)
            self.assertEqual(code, EXIT_REFUSED)
            self.assertFalse(payload["matches"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_missing_report_is_a_stated_refusal(self):
        code, payload = run_json("verify-regression", "--path",
                                 os.path.join(REPO_ROOT, "nowhere.json"))
        self.assertEqual(payload["code"], "REPORT_MISSING")

    def test_writing_the_report_twice_produces_identical_bytes(self):
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        try:
            one = os.path.join(tmp, "one.json")
            two = os.path.join(tmp, "two.json")
            run("legacy-regression", "--out", one)
            run("legacy-regression", "--out", two)
            with io.open(one, encoding="utf-8") as first, \
                    io.open(two, encoding="utf-8") as second:
                self.assertEqual(first.read(), second.read())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestTheGateStatus(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.status = build_coverage_gate_status(REPO_ROOT).to_json()

    def test_the_command_reports_blocked_and_exits_refused(self):
        code, payload = run_json("gate-status")
        self.assertEqual(code, EXIT_REFUSED)
        self.assertIn("BLOCKED", payload["assessment"])

    def test_the_command_agrees_with_the_stored_file(self):
        _code, payload = run_json("gate-status")
        with io.open(GATE_STATUS, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), payload)

    def test_every_real_count_is_zero(self):
        for name, value in self.status["coverage_state"].items():
            with self.subTest(count=name):
                self.assertEqual(value, 0)

    def test_the_three_counts_the_work_package_names_are_zero(self):
        state = self.status["coverage_state"]
        self.assertEqual(state["real_coverage_manifests"], 0)
        self.assertEqual(state["real_evaluable_axes"], 0)
        self.assertEqual(state["real_coverage_executions"], 0)

    def test_all_eight_blockers_are_reported(self):
        codes = {item["code"] for item in self.status["blockers"]}
        self.assertEqual(codes, set(BLOCKER_CODES))

    def test_each_blocker_names_an_owner_and_what_it_unblocks(self):
        for blocker in self.status["blockers"]:
            with self.subTest(code=blocker["code"]):
                self.assertGreater(len(blocker["meaning"]), 20)
                self.assertGreater(len(blocker["owner"]), 10)
                self.assertGreater(len(blocker["unblocks"]), 10)
                self.assertTrue(blocker["detail"])

    def test_no_blocker_can_be_cleared_by_writing_code(self):
        self.assertIn("none of the blockers above can be cleared by "
                      "writing code", self.status["note"].lower())
        self.assertTrue(self.status["next_required_human_actions"])

    def test_the_upstream_state_is_read_not_asserted(self):
        upstream = self.status["upstream_state"]
        self.assertEqual(upstream["curation_protocol_status"],
                         "AWAITING_EXPERT_REVIEW")
        self.assertFalse(upstream["curation_protocol_approved"])
        self.assertEqual(upstream["canonical_dataset_state"], "BUILDING")
        self.assertFalse(upstream["canonical_dataset_published"])
        self.assertEqual(upstream["frozen_rulesets"], 0)
        self.assertTrue(upstream["evidence_build_labels"])

    def test_the_report_declares_its_version_and_hashes_itself(self):
        self.assertEqual(self.status["gate_status_version"],
                         COVERAGE_GATE_STATUS_VERSION)
        self.assertTrue(self.status["content_hash"].startswith("sha256:"))

    def test_two_builds_agree(self):
        self.assertEqual(build_coverage_gate_status(REPO_ROOT).to_json(),
                         self.status)

    def test_the_scanner_skips_its_own_output(self):
        """The report lives in the directory it scans. Without this the count
        would include the report itself, or a half-written copy of it."""
        self.assertEqual(GATE_STATUS_FILENAME,
                         os.path.basename(GATE_STATUS))
        self.assertEqual(DEFAULT_COVERAGE_ROOT,
                         os.path.join("data", "coverage"))
        self.assertEqual(self.status["coverage_state"]
                         ["real_coverage_manifests"], 0)

    def test_a_manifest_in_the_directory_would_be_counted(self):
        """The count is a scan, not a constant. Proved on a temporary copy,
        so the real directory is never written to."""
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        try:
            root = os.path.join(tmp, "data", "coverage")
            os.makedirs(root)
            with io.open(os.path.join(root, "some-manifest.json"), "w",
                         encoding="utf-8") as handle:
                json.dump({"coverage_schema_version":
                           "pgx-ruleset-coverage-manifest/1"}, handle)
            counted = build_coverage_gate_status(tmp).to_json()
            self.assertEqual(
                counted["coverage_state"]["real_coverage_manifests"], 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_an_unreadable_file_is_visible_rather_than_ignored(self):
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        try:
            root = os.path.join(tmp, "data", "coverage")
            os.makedirs(root)
            with io.open(os.path.join(root, "corrupt.json"), "w",
                         encoding="utf-8") as handle:
                handle.write("{ truncated")
            status = build_coverage_gate_status(tmp).to_json()
            blocker = [item for item in status["blockers"]
                       if item["code"] == "NO_APPROVED_COVERAGE_MANIFEST"][0]
            self.assertIn("1 unreadable", blocker["detail"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
