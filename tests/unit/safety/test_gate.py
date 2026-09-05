# -*- coding: utf-8 -*-
"""The gate cannot report a pass it did not earn.

Every test here removes something the gate depends on and asserts that the gate
notices. Passing ordinary unit tests must not imply that the safety gate
passed - that is the whole distinction between WP-19 and WP-20, and this module
is where it is held down.
"""

from __future__ import annotations

import unittest

from pgx.safety.definitions import definitions_by_id
from pgx.safety.execution import (ControlOutcome, SafetyExecution,
                                  build_invariant_execution, summarise)
from pgx.safety.gate_status import (build_wp20_gate_status, safety_gate_state)
from pgx.safety.registry import load_registry
from pgx.safety.vocabulary import (ComplianceState, ExecutionState,
                                   InvariantId)
from tests.unit.safety._support import REPO_ROOT

_CLEAN = {"executed": 10, "passed": 10, "failed": 0, "errored": 0,
          "skipped": 0, "unexplained_skips": 0}


def _controls(satisfied=True, count=2, kind="NEGATIVE"):
    return tuple(
        ControlOutcome("NC-TEST-%d" % index, kind,
                       detected=(True if satisfied else False),
                       expected_refusal_code="SAFETY_TEST",
                       observed_refusal_code=("SAFETY_TEST" if satisfied
                                              else ""))
        for index in range(count))


def _safe(satisfied=True):
    return ControlOutcome("SC-TEST", "SAFE",
                          detected=(False if satisfied else True))


class TestZeroExecutionCannotPass(unittest.TestCase):

    def setUp(self):
        self.definition = definitions_by_id()["SAFETY-INV-001"]

    def test_no_tests_executed_is_not_executed(self):
        """The single most dangerous state to confuse with PASS."""
        result = build_invariant_execution(
            self.definition, (_safe(),) + _controls(),
            {"executed": 0, "passed": 0, "failed": 0, "errored": 0,
             "skipped": 0, "unexplained_skips": 0})
        self.assertIs(result.execution_state, ExecutionState.NOT_EXECUTED)
        self.assertIs(result.compliance_state, ComplianceState.UNKNOWN)

    def test_no_controls_at_all_is_not_executed(self):
        result = build_invariant_execution(self.definition, (), _CLEAN)
        self.assertIs(result.execution_state, ExecutionState.NOT_EXECUTED)

    def test_not_executed_never_permits_a_release(self):
        from pgx.safety.vocabulary import is_release_permitting
        self.assertFalse(is_release_permitting(ExecutionState.NOT_EXECUTED))


class TestAnUndetectedMutantBlocks(unittest.TestCase):
    """A suite where every test passes but a mutant slipped through has not
    demonstrated the invariant."""

    def setUp(self):
        self.definition = definitions_by_id()["SAFETY-INV-001"]

    def test_a_detector_that_accepts_its_mutant_fails(self):
        result = build_invariant_execution(
            self.definition, (_safe(),) + _controls(satisfied=False), _CLEAN)
        self.assertIs(result.execution_state, ExecutionState.FAIL)
        self.assertIn("accepted", result.reason)

    def test_the_tests_all_passing_does_not_rescue_it(self):
        """Ten passing tests and one undetected mutant is still a failure."""
        result = build_invariant_execution(
            self.definition, (_safe(),) + _controls(satisfied=False),
            dict(_CLEAN, executed=100, passed=100))
        self.assertIs(result.execution_state, ExecutionState.FAIL)

    def test_a_control_that_did_not_run_is_not_satisfied(self):
        """``detected=None`` means nobody tried, which is never a pass."""
        never_ran = ControlOutcome("NC-TEST-X", "NEGATIVE", detected=None,
                                   expected_refusal_code="SAFETY_TEST")
        self.assertFalse(never_ran.satisfied)
        result = build_invariant_execution(self.definition,
                                           (_safe(), never_ran), _CLEAN)
        self.assertIs(result.execution_state, ExecutionState.FAIL)

    def test_the_wrong_refusal_code_is_not_a_detection(self):
        """Rejecting the mutant for an unrelated reason proves nothing about
        the invariant this control belongs to."""
        wrong = ControlOutcome("NC-TEST-Y", "NEGATIVE", detected=True,
                               expected_refusal_code="SAFETY_TEST",
                               observed_refusal_code="SAFETY_SOMETHING_ELSE")
        self.assertFalse(wrong.satisfied)

    def test_a_rejected_safe_control_also_fails(self):
        """A detector that rejects everything is not a working detector."""
        result = build_invariant_execution(
            self.definition, (_safe(satisfied=False),) + _controls(), _CLEAN)
        self.assertIs(result.execution_state, ExecutionState.FAIL)
        self.assertIn("safe control", result.reason)


class TestBrokenTestsBlock(unittest.TestCase):

    def setUp(self):
        self.definition = definitions_by_id()["SAFETY-INV-001"]

    def test_a_failing_test_fails_the_invariant(self):
        result = build_invariant_execution(
            self.definition, (_safe(),) + _controls(),
            dict(_CLEAN, failed=1))
        self.assertIs(result.execution_state, ExecutionState.FAIL)

    def test_an_errored_test_fails_the_invariant(self):
        result = build_invariant_execution(
            self.definition, (_safe(),) + _controls(),
            dict(_CLEAN, errored=1))
        self.assertIs(result.execution_state, ExecutionState.FAIL)

    def test_an_unexplained_skip_fails_the_invariant(self):
        result = build_invariant_execution(
            self.definition, (_safe(),) + _controls(),
            dict(_CLEAN, skipped=1, unexplained_skips=1))
        self.assertIs(result.execution_state, ExecutionState.FAIL)

    def test_a_permitted_skip_does_not(self):
        result = build_invariant_execution(
            self.definition, (_safe(),) + _controls(),
            dict(_CLEAN, skipped=1, unexplained_skips=0))
        self.assertIsNot(result.execution_state, ExecutionState.FAIL)


class TestALaterWorkPackageBlocksWithoutFailing(unittest.TestCase):
    """A blocked invariant is not a broken one, and must not read as either a
    failure or a pass."""

    def test_a_declared_blocker_produces_blocked(self):
        definition = definitions_by_id()["SAFETY-INV-012"]
        result = build_invariant_execution(
            definition, (_safe(),) + _controls(), _CLEAN)
        self.assertIs(result.execution_state, ExecutionState.BLOCKED)
        self.assertTrue(result.blockers)

    def test_blocked_still_stops_a_release(self):
        from pgx.safety.vocabulary import is_release_permitting
        self.assertFalse(is_release_permitting(ExecutionState.BLOCKED))

    def test_an_invariant_with_no_blocker_passes(self):
        definition = definitions_by_id()["SAFETY-INV-001"]
        result = build_invariant_execution(
            definition, (_safe(),) + _controls(), _CLEAN)
        self.assertIs(result.execution_state, ExecutionState.PASS)


class TestTheGateStatusKeepsItsFieldsApart(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry(REPO_ROOT)

    def _status(self, executions, evidence_state="CURRENT", **kwargs):
        execution = SafetyExecution(tuple(executions), {}, {}, complete=True)
        report = {"false_reassurance": {"corpus_size": 36,
                                        "violation_count": 0},
                  "prohibited_claim_surfaces": {"surface_count": 6,
                                                "known_gap_count": 0}}
        return build_wp20_gate_status(REPO_ROOT, self.registry, execution,
                                      report, evidence_state=evidence_state,
                                      **kwargs)

    def _all_passing(self):
        return [build_invariant_execution(definition,
                                          (_safe(),) + _controls(), _CLEAN)
                for definition in self.registry.definitions
                if not definition.blockers]

    def test_stale_evidence_blocks_even_when_every_check_passed(self):
        status = self._status(self._all_passing(), evidence_state="STALE")
        self.assertFalse(status["release_may_proceed"])
        codes = {b["code"] for b in status["blockers"]}
        self.assertIn("SAFETY_EVIDENCE_STALE", codes)

    def test_absent_evidence_blocks(self):
        status = self._status(self._all_passing(), evidence_state="ABSENT")
        self.assertFalse(status["release_may_proceed"])
        self.assertIn("SAFETY_EVIDENCE_ABSENT",
                      {b["code"] for b in status["blockers"]})

    def test_an_unapproved_claim_boundary_blocks(self):
        status = self._status(self._all_passing())
        self.assertFalse(status["claim_boundary_approved"])
        self.assertIn("SAFETY_CLAIM_BOUNDARY_NOT_APPROVED",
                      {b["code"] for b in status["blockers"]})

    def test_a_ci_job_is_never_reported_as_executed_from_a_file(self):
        """Configured and executed are different facts."""
        status = self._status(self._all_passing())
        self.assertFalse(status["ci_job_executed"])
        self.assertIn("CONFIGURED, not EXECUTED",
                      status["ci_job_execution_note"])

    def test_nothing_measured_is_null_not_zero(self):
        status = self._status(self._all_passing(), postgresql_available=None,
                              active_release_available=None,
                              holdout_case_count=None)
        self.assertIsNone(status["postgresql_available"])
        self.assertIsNone(status["active_release_available"])
        self.assertIsNone(status["holdout_case_count"])

    def test_no_clinical_or_expert_claim_is_made(self):
        """Even with every invariant passing, no human act is claimed."""
        status = self._status(self._all_passing())
        self.assertFalse(status["clinical_validation_performed"])
        self.assertFalse(status["expert_review_performed"])
        self.assertIn("not clinical validation",
                      status["not_clinical_validation"].lower())

    def test_metrics_being_implemented_is_not_a_clinical_claim(self):
        """WP-21 exists, so this field is true - and changes nothing.

        Kept as its own test rather than deleted from the one above, because
        the interesting assertion is precisely that a true value here does
        not move any of the claims that matter.
        """
        status = self._status(self._all_passing())
        self.assertTrue(status["validation_metrics_implemented"])
        self.assertFalse(status["clinical_validation_performed"])
        self.assertFalse(status["expert_review_performed"])
        self.assertIn("Implemented is not computed",
                      status["validation_metrics_note"])

    def test_the_gate_state_is_chosen_by_explicit_precedence(self):
        definition = definitions_by_id()["SAFETY-INV-001"]
        passing = build_invariant_execution(definition,
                                            (_safe(),) + _controls(), _CLEAN)
        failing = build_invariant_execution(
            definition, (_safe(),) + _controls(satisfied=False), _CLEAN)
        blocked = build_invariant_execution(
            definitions_by_id()["SAFETY-INV-012"],
            (_safe(),) + _controls(), _CLEAN)
        unexecuted = build_invariant_execution(definition, (), _CLEAN)

        self.assertIs(safety_gate_state(
            SafetyExecution((passing,), {}, {}, True)), ExecutionState.PASS)
        self.assertIs(safety_gate_state(
            SafetyExecution((passing, blocked), {}, {}, True)),
            ExecutionState.BLOCKED)
        self.assertIs(safety_gate_state(
            SafetyExecution((passing, unexecuted), {}, {}, True)),
            ExecutionState.NOT_EXECUTED)
        self.assertIs(safety_gate_state(
            SafetyExecution((passing, blocked, failing), {}, {}, True)),
            ExecutionState.FAIL)

    def test_an_empty_execution_is_not_executed(self):
        self.assertIs(safety_gate_state(SafetyExecution((), {}, {}, True)),
                      ExecutionState.NOT_EXECUTED)
