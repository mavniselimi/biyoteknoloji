# -*- coding: utf-8 -*-
"""The ``pgx-assess`` CLI and the WP-14 gate status.

A command-line tool is where a boundary is most likely to be argued with, so
most of this file is about what the tool refuses - and refuses *by name*, so a
caller reaching for ``--force-release`` gets a stated reason rather than an
unrecognised-argument message that reads like an oversight.

The default execution path refuses outright. ``execute`` and ``dry-run`` exist
as commands and both decline, because a tool whose execute command was missing
would look unfinished, whereas one that declines and says why is stating the
governance position.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import unittest

from pgx.application.assessment_cli import (EXIT_OK, EXIT_REFUSED,
                                            REFUSED_FLAGS, build_parser, main,
                                            refuse_unsafe_flags)
from pgx.application.assessment_gate_status import (
    ASSESSMENT_GATE_STATUS_VERSION, BLOCKER_CODES, DEFAULT_ASSESSMENT_ROOT,
    GATE_STATUS_FILENAME, build_assessment_gate_status)
from pgx.engine.risk import ASSESSMENT_ENGINE_CONTRACT_VERSION
from pgx.engine.risk_errors import FAILURE_CODES
from tests.fixtures.wp13.synthetic import DRUG_1, DRUG_2, GENE_1
from tests.unit.application._assessment_support import (
    REPO_ROOT, SyntheticAssessmentWorld)

GATE_STATUS = os.path.join(REPO_ROOT, "data", "assessments",
                           GATE_STATUS_FILENAME)
REGRESSION_REPORT = os.path.join(REPO_ROOT, "data", "migration", "wp14",
                                 "assessment-regression-report.json")


def run(*argv):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(list(argv))
    return code, buffer.getvalue()


def run_json(*argv):
    code, text = run(*argv)
    return code, json.loads(text)


class TestTheToolRefusesWhatItMustNotDo(unittest.TestCase):

    def test_the_command_set_is_exactly_these(self):
        commands = set()
        for action in build_parser()._actions:
            if getattr(action, "choices", None):
                commands.update(action.choices)
        self.assertEqual(commands, {
            "validate-input", "verify-hashes", "show-assessment",
            "gate-status", "attention-table", "list-failure-codes",
            "legacy-regression", "verify-regression", "dry-run", "execute"})

    def test_every_refused_flag_is_refused_with_a_reason(self):
        for flag in REFUSED_FLAGS:
            with self.subTest(flag=flag):
                code, payload = run_json(flag)
                self.assertEqual(code, EXIT_REFUSED)
                self.assertTrue(payload["refused"])
                self.assertEqual(payload["code"], "FLAG_REFUSED")
                self.assertIn(flag, payload["error"])

    def test_a_refused_flag_is_refused_before_anything_is_read(self):
        code, payload = run_json("gate-status", "--force-release")
        self.assertEqual(code, EXIT_REFUSED)
        self.assertEqual(payload["code"], "FLAG_REFUSED")

    def test_the_twelve_refusals_cover_the_named_shortcuts(self):
        self.assertEqual(set(REFUSED_FLAGS), {
            "--force-release", "--bypass-approval", "--allow-draft-rule",
            "--ignore-coverage", "--ignore-evidence", "--assume-normal",
            "--clinical-mode", "--patient-mode", "--dose", "--recommend",
            "--rank", "--as-approver"})

    def test_an_abbreviated_flag_cannot_reach_anything(self):
        parser = build_parser()
        self.assertFalse(parser.allow_abbrev)
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                parser.parse_args(["--rep", "x", "gate-status"])


class TestExecutionIsRefusedByDefault(unittest.TestCase):

    def test_execute_refuses_and_names_the_claim_boundary(self):
        code, payload = run_json("execute", "/tmp/anything.json")
        self.assertEqual(code, EXIT_REFUSED)
        self.assertEqual(payload["code"],
                         "ASSESSMENT_CLAIM_BOUNDARY_NOT_APPROVED")
        self.assertIn("DRAFT", payload["claim_boundary_status"])

    def test_dry_run_refuses_too(self):
        code, payload = run_json("dry-run", "/tmp/anything.json")
        self.assertEqual(code, EXIT_REFUSED)
        self.assertEqual(payload["code"],
                         "ASSESSMENT_CLAIM_BOUNDARY_NOT_APPROVED")

    def test_the_refusal_says_no_flag_changes_it(self):
        _code, payload = run_json("execute", "/tmp/anything.json")
        self.assertIn("no flag in this tool sets that approval",
                      payload["error"])

    def test_the_refusal_happens_before_the_file_is_read(self):
        """A missing path is not the reason. The boundary is."""
        code, payload = run_json("execute",
                                 os.path.join(REPO_ROOT, "does-not-exist"))
        self.assertEqual(payload["code"],
                         "ASSESSMENT_CLAIM_BOUNDARY_NOT_APPROVED")


class TestTheReadOnlyCommands(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.world = SyntheticAssessmentWorld(persist=False)
        cls.tmp = tempfile.mkdtemp()
        cls.input_path = os.path.join(cls.tmp, "input.json")
        with io.open(cls.input_path, "w", encoding="utf-8") as handle:
            json.dump(cls.world.input(medications=[DRUG_1, DRUG_2]).to_json(),
                      handle)
        cls.result_path = os.path.join(cls.tmp, "result.json")
        with io.open(cls.result_path, "w", encoding="utf-8") as handle:
            json.dump(cls.world.dry_run(medications=[DRUG_1]).to_json(),
                      handle)

    @classmethod
    def tearDownClass(cls):
        import shutil
        cls.world.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_validate_input_accepts_a_valid_document(self):
        code, payload = run_json("validate-input", self.input_path)
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(payload["passed"])

    def test_validate_input_says_what_it_did_not_check(self):
        _code, payload = run_json("validate-input", self.input_path)
        self.assertIn("schema validation only", payload["note"])
        self.assertIn("claim boundary", payload["note"])

    def test_validate_input_refuses_an_invalid_document(self):
        broken = os.path.join(self.tmp, "broken.json")
        document = self.world.input(medications=[DRUG_1]).to_json()
        document["genotype"] = "*1/*2"
        with io.open(broken, "w", encoding="utf-8") as handle:
            json.dump(document, handle)
        code, payload = run_json("validate-input", broken)
        self.assertEqual(code, EXIT_REFUSED)
        self.assertFalse(payload["passed"])

    def test_show_assessment_prints_the_calculated_facts(self):
        code, payload = run_json("show-assessment", self.result_path)
        self.assertEqual(code, EXIT_OK)
        self.assertIn("overall_coverage", payload)
        self.assertIn("overall_attention", payload)

    def test_verify_hashes_recomputes_the_output_hash(self):
        code, payload = run_json("verify-hashes", self.result_path)
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(payload["matches"])
        self.assertEqual(payload["declared_output_hash"],
                         payload["recomputed_output_hash"])

    def test_verify_hashes_detects_a_tampered_document(self):
        tampered = os.path.join(self.tmp, "tampered.json")
        document = self.world.dry_run(medications=[DRUG_1]).to_json()
        document["overall_attention"] = "HIGH"
        with io.open(tampered, "w", encoding="utf-8") as handle:
            json.dump(document, handle)
        code, payload = run_json("verify-hashes", tampered)
        self.assertEqual(code, EXIT_REFUSED)
        self.assertFalse(payload["matches"])

    def test_verify_hashes_says_what_the_hash_excludes(self):
        _code, payload = run_json("verify-hashes", self.result_path)
        self.assertIn("excludes the assessment", payload["note"])

    def test_attention_table_prints_the_precedence_and_the_exclusion(self):
        code, payload = run_json("attention-table")
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["attention"]["precedence"],
                         ["HIGH", "MEDIUM", "LOW", "NO_ACTIVE_ATTENTION"])
        self.assertEqual(payload["attention"]["excluded_from_maximum"],
                         ["NOT_ASSESSED"])
        self.assertEqual(payload["assessment_engine_contract_version"],
                         ASSESSMENT_ENGINE_CONTRACT_VERSION)

    def test_attention_table_renders_as_text_too(self):
        code, text = run("attention-table", "--text")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("precedence:", text)
        self.assertIn("NOT_ASSESSED", text)

    def test_the_engine_contract_is_printed_with_the_table(self):
        _code, payload = run_json("attention-table")
        contract = payload["engine_contract"]
        self.assertIn("finding_gate", contract)
        self.assertIn("conflict", contract)
        self.assertIn("excluded_from_output_hash", contract)

    def test_list_failure_codes_prints_every_published_code(self):
        code, payload = run_json("list-failure-codes")
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(set(payload["failure_codes"]), set(FAILURE_CODES))
        self.assertEqual(set(payload["gate_blocker_codes"]),
                         set(BLOCKER_CODES))
        self.assertEqual(set(payload["refused_flags"]), set(REFUSED_FLAGS))

    def test_a_missing_file_is_a_stated_refusal_not_a_traceback(self):
        code, payload = run_json("validate-input",
                                 os.path.join(self.tmp, "absent.json"))
        self.assertEqual(payload["code"], "FILE_NOT_FOUND")
        self.assertTrue(payload["refused"])

    def test_malformed_json_is_a_stated_refusal(self):
        path = os.path.join(self.tmp, "bad.json")
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        code, payload = run_json("validate-input", path)
        self.assertEqual(payload["code"], "INVALID_JSON")

    def test_no_command_writes_to_the_repository(self):
        before = sorted(os.listdir(os.path.join(REPO_ROOT, "data",
                                                "assessments")))
        for argv in (("attention-table",), ("list-failure-codes",),
                     ("gate-status",), ("validate-input", self.input_path)):
            with self.subTest(command=argv[0]):
                run(*argv)
        self.assertEqual(
            sorted(os.listdir(os.path.join(REPO_ROOT, "data",
                                           "assessments"))), before)


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
        self.assertEqual(payload["unexpected_differences"], 0)

    def test_verify_regression_refuses_a_stale_report(self):
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "stale.json")
        with io.open(REGRESSION_REPORT, encoding="utf-8") as handle:
            document = json.load(handle)
        document["case_count"] = 999
        with io.open(path, "w", encoding="utf-8") as handle:
            json.dump(document, handle)
        code, payload = run_json("verify-regression", "--path", path)
        self.assertEqual(code, EXIT_REFUSED)
        self.assertFalse(payload["matches"])

    def test_writing_the_report_twice_produces_identical_bytes(self):
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        one = os.path.join(tmp, "one.json")
        two = os.path.join(tmp, "two.json")
        run("legacy-regression", "--out", one)
        run("legacy-regression", "--out", two)
        with io.open(one, encoding="utf-8") as first, \
                io.open(two, encoding="utf-8") as second:
            self.assertEqual(first.read(), second.read())


class TestTheGateStatus(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.status = build_assessment_gate_status(REPO_ROOT).to_json()

    def test_the_command_reports_blocked_and_exits_refused(self):
        code, payload = run_json("gate-status")
        self.assertEqual(code, EXIT_REFUSED)
        self.assertIn("BLOCKED", payload["assessment"])

    def test_the_command_agrees_with_the_stored_file(self):
        _code, payload = run_json("gate-status")
        with io.open(GATE_STATUS, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), payload)

    def test_every_real_count_is_zero(self):
        for name, value in self.status["assessment_state"].items():
            with self.subTest(count=name):
                self.assertEqual(value, 0)

    def test_the_three_counts_the_work_package_names_are_zero(self):
        state = self.status["assessment_state"]
        self.assertEqual(state["real_completed_assessments"], 0)
        self.assertEqual(state["real_findings"], 0)
        self.assertEqual(state["real_executable_release_contexts"], 0)

    def test_all_nine_blockers_are_reported(self):
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
        self.assertIn("none of the blockers above can be cleared by writing "
                      "code", self.status["note"].lower())
        self.assertTrue(self.status["next_required_human_actions"])

    def test_the_claim_boundary_is_reported_as_unapproved(self):
        boundary = self.status["claim_boundary"]
        self.assertFalse(boundary["approved"])
        self.assertIn("DRAFT", boundary["status"])

    def test_the_upstream_state_is_read_not_asserted(self):
        upstream = self.status["upstream_state"]
        self.assertEqual(upstream["curation_protocol_status"],
                         "AWAITING_EXPERT_REVIEW")
        self.assertEqual(upstream["canonical_dataset_state"], "BUILDING")
        self.assertFalse(upstream["canonical_dataset_published"])
        self.assertEqual(upstream["frozen_rulesets"], 0)
        self.assertEqual(upstream["approved_coverage_manifests"], 0)
        self.assertTrue(upstream["evidence_build_labels"])

    def test_the_report_declares_its_version_and_hashes_itself(self):
        self.assertEqual(self.status["gate_status_version"],
                         ASSESSMENT_GATE_STATUS_VERSION)
        self.assertTrue(self.status["content_hash"].startswith("sha256:"))

    def test_two_builds_agree(self):
        self.assertEqual(build_assessment_gate_status(REPO_ROOT).to_json(),
                         self.status)

    def test_the_scanner_skips_its_own_output(self):
        self.assertEqual(GATE_STATUS_FILENAME,
                         os.path.basename(GATE_STATUS))
        self.assertEqual(DEFAULT_ASSESSMENT_ROOT,
                         os.path.join("data", "assessments"))
        self.assertEqual(
            self.status["assessment_state"]["real_completed_assessments"], 0)

    def test_an_assessment_in_the_directory_would_be_counted(self):
        """The count is a scan, not a constant. Proved on a temporary copy so
        the real directory is never written to."""
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        root = os.path.join(tmp, "data", "assessments")
        os.makedirs(root)
        with io.open(os.path.join(root, "some-assessment.json"), "w",
                     encoding="utf-8") as handle:
            json.dump({"assessment_id": "00000000-0000-4000-8000-000000000001"},
                      handle)
        counted = build_assessment_gate_status(tmp).to_json()
        self.assertEqual(
            counted["assessment_state"]["real_completed_assessments"], 1)


if __name__ == "__main__":
    unittest.main()
