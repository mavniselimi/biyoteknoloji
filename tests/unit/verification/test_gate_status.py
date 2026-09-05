# -*- coding: utf-8 -*-
"""The gate status keeps its components apart, and rejects stale evidence.

The failure mode this file exists to prevent is a single ``verified: true``.
The suite can be entirely green while PostgreSQL was never reached, coverage
was never measured, and the claim boundary is unapproved. One boolean cannot
say that, and any boolean that tried would be false in one direction or
misleading in the other.
"""

from __future__ import annotations

import copy
import io
import json
import os
import unittest

from pgx.application.verification_schema import validate_wp19_gate_status
from pgx.verification.coverage_report import blocked_summary
from pgx.verification.discovery import discover
from pgx.verification.gate_status import (
    BLOCKER_CODES,
    GATE_STATUS_PATH,
    build_wp19_gate_status,
)
from pgx.verification.inventory import build_inventory
from pgx.verification.matrix import build_matrix
from pgx.verification.model import Category, Outcome, SkipPolicy
from pgx.verification.results import build_profile_result
from pgx.verification.run_evidence import (
    NO_EVIDENCE,
    RUN_EVIDENCE_SCHEMA_VERSION,
    RUN_FAILED,
    STALE,
    VERIFIED,
    host_fingerprint,
    input_fingerprints,
    load_run_evidence,
    run_evidence_freshness,
)

from tests.unit.verification._support import (
    REPO_ROOT,
    entry,
    inventory,
    profile,
    report,
)


def _matrix():
    return build_matrix(build_inventory(discover(REPO_ROOT)))


def _status(results=None, coverage=None, flaky=None, reproducibility=None):
    return build_wp19_gate_status(
        REPO_ROOT, _matrix(), 5000, results or {},
        coverage or blocked_summary("coverage.py is absent"),
        flaky, reproducibility)


class TestNothingIsCollapsedIntoOneBoolean(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.document = _status()

    def test_it_validates(self):
        self.assertEqual(validate_wp19_gate_status(self.document), ())

    def test_each_component_has_its_own_field(self):
        for field in ("execution_status", "coverage_tool_available",
                      "postgresql_test_status", "asgi_runtime_status",
                      "browser_e2e_status", "flaky_repeat_status",
                      "reproducibility_status", "run_evidence_status",
                      "claim_boundary_approved", "wp20_started",
                      "release_may_proceed"):
            with self.subTest(field=field):
                self.assertIn(field, self.document)

    def test_discovered_and_executed_are_separate_numbers(self):
        """A class-level skip suppresses tests the runner never reports, so
        `testsRun` is not the number of tests that exist."""
        counts = self.document["counts"]
        self.assertIn("discovered", counts)
        self.assertIn("executed", counts)
        self.assertIn("not_executed", counts)

    def test_a_component_nobody_measured_is_null_not_zero(self):
        """WP-18's rule, kept. Zero means somebody looked and found none."""
        self.assertIsNone(self.document["flaky_repeat_status"])
        self.assertIsNone(self.document["reproducibility_status"])
        self.assertIsNone(self.document["coverage"]["line_percent"])
        self.assertIsNone(self.document["counts"]["executed"])

    def test_release_may_proceed_is_computed_rather_than_asserted(self):
        self.assertFalse(self.document["release_may_proceed"])
        self.assertGreater(self.document["blocker_count"], 0)

    def test_every_blocker_names_an_owner_that_is_not_the_code(self):
        for blocker in self.document["blockers"]:
            with self.subTest(code=blocker["code"]):
                self.assertTrue(blocker["owner"])
                self.assertNotEqual(blocker["owner"], "code")
                self.assertIn(blocker["code"], BLOCKER_CODES)

    def test_it_says_it_is_not_scientific_validation(self):
        self.assertFalse(self.document["scientific_validation_performed"])
        for phrase in ("software verification", "WP-21", "WP-22"):
            self.assertIn(phrase, self.document["not_scientific_validation"])

    def test_it_does_not_claim_the_wp20_safety_gate(self):
        """WP-20 exists now. WP-19 still does not own its gate: it reports
        WP-20's measured state verbatim and blocks while that state is not
        PASS. Reporting somebody else's result is not claiming it."""
        self.assertIn("WP-20", self.document["safety_gate_note"])
        self.assertIn("never as satisfied", self.document["safety_gate_note"])
        codes = {blocker["code"] for blocker in self.document["blockers"]}
        self.assertIn("VERIFICATION_SAFETY_GATE_NOT_PASSING", codes)
        self.assertNotEqual(self.document["safety_gate_status"], "PASS")

    def test_the_safety_gate_state_is_wp20s_committed_state(self):
        """Copied from WP-20's artifact, never recomputed here. If the file
        is missing the state is ABSENT; there is no path to a value WP-19
        made up."""
        path = os.path.join(REPO_ROOT, "data", "safety",
                            "wp20-real-gate-status.json")
        if not os.path.exists(path):
            self.assertEqual(self.document["safety_gate_status"], "ABSENT")
            self.assertIsNone(self.document["safety_invariant_count"])
            return
        with io.open(path, "r", encoding="utf-8") as handle:
            committed = json.load(handle)
        self.assertEqual(self.document["safety_gate_status"],
                         committed["safety_gate_status"])
        self.assertEqual(self.document["safety_invariant_count"],
                         committed["registered_invariant_count"])
        self.assertEqual(self.document["safety_negative_control_count"],
                         committed["negative_control_count"])
        self.assertEqual(self.document["safety_negative_controls_detected"],
                         committed["detected_negative_control_count"])

    def test_the_map_only_flag_follows_whether_a_registry_exists(self):
        """WP-19 pinned this true with ``const`` and said it would change in
        the open when WP-20 built the real registry. It did."""
        self.assertEqual(self.document["safety_invariant_map_only"],
                         not os.path.exists(os.path.join(
                             REPO_ROOT, "pgx", "safety", "definitions.py")))

    def test_it_does_not_approve_the_claim_boundary(self):
        self.assertFalse(self.document["claim_boundary_approved"])
        self.assertIn("DRAFT", self.document["claim_boundary_status"].upper())

    def test_the_claim_boundary_status_is_read_from_the_document(self):
        """Not pinned here. If somebody approves it, this field follows."""
        import io
        with io.open(os.path.join(REPO_ROOT, "docs", "architecture",
                                  "intended-purpose.md"), "r",
                     encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn(self.document["claim_boundary_status"], text)

    def test_later_packages_are_measured_from_the_tree(self):
        """A pinned false has to be deleted the day the next package starts,
        and until somebody notices it is a lie."""
        self.assertEqual(
            self.document["wp20_started"],
            os.path.exists(os.path.join(REPO_ROOT, "pgx", "safety"))
            or os.path.exists(os.path.join(
                REPO_ROOT, "docs", "architecture",
                "wp20-safety-invariants.md")))


class TestABlockedComponentIsNeverAPass(unittest.TestCase):

    def _with_postgres_skipped(self):
        entries = [
            entry("u.C.test_a", category=Category.UNIT),
            entry("d.C.test_b", category=Category.POSTGRESQL_INTEGRATION,
                  skip_policy=SkipPolicy.ENVIRONMENT_DEPENDENCY,
                  permitted=("requires psycopg",)),
        ]
        result = build_profile_result(
            profile(name="full"),
            report({"u.C.test_a": {"outcome": "PASS", "reason": ""},
                    "d.C.test_b": {"outcome": "SKIP",
                                   "reason": "requires psycopg"}}),
            inventory(*entries), 2)
        return _status({"full": result})

    def test_postgresql_reports_blocked_when_every_test_skipped(self):
        document = self._with_postgres_skipped()
        self.assertEqual(document["postgresql_test_status"],
                         Outcome.BLOCKED.value)
        self.assertNotEqual(document["postgresql_test_status"],
                            Outcome.PASS.value)

    def test_a_blocked_database_blocks_the_release(self):
        document = self._with_postgres_skipped()
        codes = {blocker["code"] for blocker in document["blockers"]}
        self.assertIn("VERIFICATION_POSTGRESQL_NOT_EXERCISED", codes)
        self.assertFalse(document["release_may_proceed"])

    def test_a_category_with_no_executed_result_is_not_pass(self):
        document = _status()
        for name, info in document["category_status"].items():
            with self.subTest(category=name):
                self.assertNotEqual(info["outcome"], Outcome.PASS.value)

    def test_coverage_absence_is_a_blocker_with_an_install_command(self):
        document = _status()
        blockers = {blocker["code"]: blocker["detail"]
                    for blocker in document["blockers"]}
        self.assertIn("VERIFICATION_COVERAGE_NOT_MEASURED", blockers)
        self.assertFalse(document["coverage_tool_available"])
        # The command lives on the coverage block, where a reader looking at
        # the measurement finds it, and the blocker carries the reason.
        self.assertIn("pip install", document["coverage"]["install_command"])
        self.assertEqual(blockers["VERIFICATION_COVERAGE_NOT_MEASURED"],
                         document["coverage"]["reason"])

    def test_the_real_coverage_reason_names_the_install_command(self):
        from pgx.verification.coverage_report import (
            INSTALL_COMMAND, coverage_available, measure_coverage)
        if coverage_available():
            self.skipTest("coverage.py is installed here, so the absent "
                          "reason cannot be produced")
        self.assertIn(INSTALL_COMMAND, measure_coverage(REPO_ROOT).reason)


class TestStaleEvidenceIsRejected(unittest.TestCase):
    """A recorded run that is no longer about this code is not evidence."""

    def _evidence(self, **overrides):
        document = {
            "environment": host_fingerprint(),
            "hash_seed": "20260904",
            "inputs": input_fingerprints(REPO_ROOT),
            "issue_codes": [],
            "passed": True,
            "profile": "full",
            "schema_version": RUN_EVIDENCE_SCHEMA_VERSION,
        }
        document.update(overrides)
        return document

    def test_a_matching_record_is_accepted(self):
        status, reason = run_evidence_freshness(self._evidence(), REPO_ROOT)
        self.assertEqual(status, VERIFIED)
        self.assertEqual(reason, "")

    def test_no_record_is_blocked_and_says_what_to_run(self):
        status, reason = run_evidence_freshness(None, REPO_ROOT)
        self.assertEqual(status, NO_EVIDENCE)
        self.assertIn("verification_cli", reason)

    def test_a_failed_run_is_recorded_as_failed_not_absent(self):
        """"The last run failed" and "there was no run" need different
        answers from an operator."""
        status, reason = run_evidence_freshness(
            self._evidence(passed=False, issue_codes=["VERIFY_TEST_FAILURES"]),
            REPO_ROOT)
        self.assertEqual(status, RUN_FAILED)
        self.assertIn("VERIFY_TEST_FAILURES", reason)

    def test_a_changed_source_tree_makes_the_record_stale(self):
        evidence = self._evidence()
        evidence["inputs"] = dict(evidence["inputs"], pgx_sha256="0" * 64)
        status, reason = run_evidence_freshness(evidence, REPO_ROOT)
        self.assertEqual(status, STALE)
        self.assertIn("changed", reason)

    def test_a_changed_test_tree_makes_the_record_stale(self):
        evidence = self._evidence()
        evidence["inputs"] = dict(evidence["inputs"], tests_sha256="0" * 64)
        self.assertEqual(run_evidence_freshness(evidence, REPO_ROOT)[0], STALE)

    def test_a_record_from_another_machine_is_stale(self):
        """An attestation does not travel between machines: a run on Linux
        says nothing about macOS, and a run without psycopg says nothing about
        a machine that has it."""
        evidence = self._evidence()
        evidence["environment"] = dict(evidence["environment"],
                                       system="Plan9")
        status, reason = run_evidence_freshness(evidence, REPO_ROOT)
        self.assertEqual(status, STALE)
        self.assertIn("different host", reason)

    def test_a_record_with_different_packages_is_stale(self):
        evidence = self._evidence()
        packages = dict(evidence["environment"]["packages"])
        packages["psycopg"] = "9.9.9"
        evidence["environment"] = dict(evidence["environment"],
                                       packages=packages)
        self.assertEqual(run_evidence_freshness(evidence, REPO_ROOT)[0], STALE)

    def test_a_record_from_an_older_schema_is_stale(self):
        evidence = self._evidence(schema_version="pgx-wp19-something-else/0")
        self.assertEqual(run_evidence_freshness(evidence, REPO_ROOT)[0], STALE)

    def test_an_unreadable_record_is_treated_as_no_record(self):
        """Not a crash. A gate status that died because somebody hand-edited a
        JSON file would be worse than one that reports BLOCKED."""
        import tempfile
        workspace = tempfile.mkdtemp()
        path = os.path.join(workspace, "data", "verification")
        os.makedirs(path)
        with open(os.path.join(path, "wp19-verification-run.json"), "w") as h:
            h.write("{not json")
        self.assertIsNone(load_run_evidence(workspace))

    def test_the_fingerprint_records_no_machine_identity(self):
        """The question is "is this the same kind of machine running the same
        stack", not "whose machine is this"."""
        rendered = json.dumps(host_fingerprint())
        import getpass
        import platform
        for secret in (platform.node(), getpass.getuser(),
                       os.path.expanduser("~")):
            if secret and len(secret) > 3:
                with self.subTest(value=secret):
                    self.assertNotIn(secret, rendered)


class TestTheCommittedGateStatus(unittest.TestCase):
    """The gate status this repository ships.

    Asserted to exist rather than skipped when absent. Every other work
    package commits one, and a missing gate status is a gap somebody should
    hear about rather than a reason to say nothing.
    """

    @classmethod
    def setUpClass(cls):
        path = os.path.join(REPO_ROOT, *GATE_STATUS_PATH.split("/"))
        with open(path, "r", encoding="utf-8") as handle:
            cls.document = json.load(handle)

    def test_it_validates(self):
        self.assertEqual(validate_wp19_gate_status(self.document), ())

    def test_it_is_this_work_package(self):
        self.assertEqual(self.document["work_package"], "WP-19")

    def test_it_claims_no_scientific_validation(self):
        self.assertFalse(self.document["scientific_validation_performed"])
        self.assertNotEqual(self.document["safety_gate_status"], "PASS")

    def test_it_reports_the_environment_it_was_produced_in(self):
        """A run on one machine is not evidence about another, so the status
        carries whether its own evidence is still acceptable here."""
        self.assertIn(self.document["run_evidence_status"],
                      ("VERIFIED", "BLOCKED", "RUN_FAILED",
                       "STALE_EVIDENCE_REJECTED"))
