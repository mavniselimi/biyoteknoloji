# -*- coding: utf-8 -*-
"""Every WP-24 document tells the truth about what did not happen (WP-24).

This file is the one that would catch the failure the whole work package is
built against: a report that reads as a success because a measurement nobody
took came back as zero, or because a rehearsal serialised under a name that
means something else.

Four properties, each checked across every producing module rather than at one
call site:

1. **A measurement nobody took is null, never zero.** A p95 of ``0`` reads as
   an extraordinarily fast system. An ``error_rate`` of ``0.0`` for a run that
   never started is the single most misleading number this package could
   produce.
2. **A rehearsal carries its label and cannot serialise as staging.**
3. **Nothing affirmative comes from a fixture.** ``TEST_ONLY_REHEARSAL`` never
   closes a gate, and that is a property of the enum rather than of a
   condition somebody could forget.
4. **Every blocker names an owner.** A blocker whose owner is unnamed is one
   nobody will clear.
"""

from __future__ import annotations

import unittest

from pgx.deployment.backup_execution import (backup_execution_status,
                                             evaluate_restore)
from pgx.deployment.ci_status import ci_status
from pgx.deployment.gate_status import (build_gate_e_status,
                                        build_wp24_gate_status)
from pgx.deployment.migration import migration_status
from pgx.deployment.performance import (execute_run, percentile, summarise,
                                        target_registry)
from pgx.deployment.release_validation import build_release_validation
from pgx.deployment.reliability import drill_catalogue, run_drills
from pgx.deployment.rollback import (governed_release_rollback_status,
                                     image_rollback_drill)
from pgx.deployment.smoke import smoke_check
from pgx.deployment.supply_chain import supply_chain_status
from pgx.deployment.vocabulary import (REHEARSAL_LABEL,
                                       DeploymentEnvironmentKind,
                                       ExecutionState)


def _every_document():
    """One of each, in the state this repository is actually in."""
    validation = build_release_validation(".")
    gate = build_wp24_gate_status(".", release_validation=validation)
    return {
        "performance": execute_run(),
        "reliability": run_drills(),
        "smoke": smoke_check(None),
        "rollback_image": image_rollback_drill(),
        "rollback_release": governed_release_rollback_status(),
        "backup": backup_execution_status(),
        "supply_chain": supply_chain_status(secret_scan_status="CLEAN",
                                            secret_finding_count=0),
        "migration": migration_status("."),
        "ci": ci_status(".", environ={}),
        "release_validation": validation,
        "wp24_gate": gate,
        "gate_e": build_gate_e_status(".", wp24=gate),
    }


class TestNoMeasurementIsAFalseZero(unittest.TestCase):
    """Null, not zero, for everything nobody measured."""

    def test_an_unrun_performance_report_has_null_metrics(self):
        result = execute_run()
        for field in ("latency_p50_ms", "latency_p95_ms", "latency_p99_ms",
                      "throughput_rps", "error_rate", "completed", "failed",
                      "input_mix_hash", "started_at", "finished_at"):
            with self.subTest(field=field):
                self.assertIsNone(result[field])

    def test_the_percentile_of_an_empty_sample_is_null(self):
        """A zero here is what almost every naive implementation returns, and
        it reads as instantaneous."""
        self.assertIsNone(percentile([], 50))
        self.assertIsNone(percentile([], 95))

    def test_a_zero_attempt_summary_reports_no_rate(self):
        """A rate over zero attempts is undefined, not zero."""
        summary = summarise([], attempted=0, wall_seconds=0.0)
        self.assertIsNone(summary["error_rate"])
        self.assertIsNone(summary["throughput_rps"])
        self.assertIsNone(summary["latency_p50_ms"])

    def test_failed_attempts_are_excluded_from_latency_and_counted_in_error(
            self):
        """A request that errored in 2 ms is not evidence that the system is
        fast."""
        observations = [
            {"ok": True, "latency_ms": 100.0},
            {"ok": True, "latency_ms": 200.0},
            {"ok": False, "latency_ms": 2.0, "code": "500"},
        ]
        summary = summarise(observations, attempted=3, wall_seconds=1.0)
        self.assertEqual(summary["latency_p50_ms"], 100.0)
        self.assertEqual(summary["failed"], 1)
        self.assertAlmostEqual(float(summary["error_rate"]), 1 / 3, places=5)

    def test_no_drill_pass_count_when_nothing_was_executed(self):
        """Zero would read as 'none of them passed', which is a different
        and much worse claim than 'none of them ran'."""
        result = run_drills()
        self.assertEqual(result["executed_count"], 0)
        self.assertIsNone(result["passed_count"])

    def test_ci_executed_is_null_rather_than_false(self):
        """'Nobody has run it' and 'a run failed' need different actions."""
        self.assertIsNone(ci_status(".", environ={})["ci_executed"])

    def test_the_gate_status_carries_null_for_unmeasured_fields(self):
        gate = build_wp24_gate_status(".")
        self.assertIsNone(gate["performance_completed"])
        self.assertIsNone(gate["reliability_executed_count"])
        self.assertIsNone(gate["ci_executed"])


class TestARehearsalCannotBecomeStaging(unittest.TestCase):
    """The label travels with the result."""

    def test_a_local_result_carries_the_rehearsal_label(self):
        for name, document in (
                ("smoke", smoke_check(None)),
                ("reliability", run_drills()),
                ("performance", execute_run()),
                ("rollback", image_rollback_drill())):
            with self.subTest(document=name):
                self.assertEqual(document["environment_kind"],
                                 DeploymentEnvironmentKind
                                 .LOCAL_REHEARSAL.value)
                self.assertEqual(document["rehearsal_label"],
                                 REHEARSAL_LABEL)

    def test_a_staging_result_carries_no_rehearsal_label(self):
        result = smoke_check(
            None, environment=DeploymentEnvironmentKind.STAGING)
        self.assertIsNone(result["rehearsal_label"])

    def test_only_staging_may_be_called_staging(self):
        for kind in DeploymentEnvironmentKind:
            with self.subTest(kind=kind.value):
                self.assertEqual(
                    kind.may_be_called_staging,
                    kind is DeploymentEnvironmentKind.STAGING)

    def test_tls_is_not_observed_from_a_local_rehearsal(self):
        gate = build_wp24_gate_status(
            ".", smoke={"tls_used": True,
                        "environment_kind":
                            DeploymentEnvironmentKind.LOCAL_REHEARSAL.value,
                        "state": ExecutionState.OBSERVED.value})
        self.assertFalse(gate["tls_observed"])


class TestAFixtureNeverClosesAGate(unittest.TestCase):
    """Enforced by the enum, not by a condition somebody could forget."""

    def test_test_only_rehearsal_may_not_close_a_gate(self):
        self.assertFalse(
            ExecutionState.TEST_ONLY_REHEARSAL.may_close_a_release_gate)

    def test_only_verified_closes_a_gate(self):
        for state in ExecutionState:
            with self.subTest(state=state.value):
                self.assertEqual(state.may_close_a_release_gate,
                                 state is ExecutionState.VERIFIED)

    def test_executed_is_not_affirmative(self):
        """A command that completed is not a condition that held."""
        self.assertFalse(ExecutionState.EXECUTED.is_affirmative)
        self.assertFalse(ExecutionState.OBSERVED.is_affirmative)
        self.assertTrue(ExecutionState.VERIFIED.is_affirmative)

    def test_there_is_no_pass_state(self):
        """Following WP-23's OperationalStatus. VERIFIED is the only
        affirmative value and it means something specific."""
        self.assertNotIn("PASS", [item.value for item in ExecutionState])

    def test_the_release_validation_refuses_the_current_state(self):
        validation = build_release_validation(".")
        self.assertFalse(validation["release_may_proceed"])
        self.assertTrue(validation["unmet_required_gates"])

    def test_an_image_may_be_built_without_being_released(self):
        validation = build_release_validation(".")
        self.assertFalse(validation["image_released"])
        self.assertFalse(validation["image_published"])


class TestEveryBlockerNamesAnOwner(unittest.TestCase):
    """A blocker nobody owns is one nobody clears."""

    def test_every_document_names_an_owner_for_every_blocker(self):
        for name, document in _every_document().items():
            for entry in document.get("blockers") or []:
                with self.subTest(document=name, code=entry.get("code")):
                    self.assertTrue(str(entry.get("owner") or "").strip())
                    self.assertTrue(str(entry.get("detail") or "").strip())

    def test_every_blocker_code_is_declared(self):
        from pgx.deployment.vocabulary import DEPLOYMENT_BLOCKER_CODES

        for name, document in _every_document().items():
            for entry in document.get("blockers") or []:
                with self.subTest(document=name, code=entry.get("code")):
                    self.assertIn(entry.get("code"), DEPLOYMENT_BLOCKER_CODES)

    def test_an_undeclared_code_is_refused(self):
        from pgx.deployment.vocabulary import DeploymentBlocker

        with self.assertRaises(ValueError):
            DeploymentBlocker(code="DEPLOY_MADE_UP", detail="x", owner="y")

    def test_a_blocker_without_an_owner_is_refused(self):
        from pgx.deployment.vocabulary import DeploymentBlocker

        with self.assertRaises(ValueError):
            DeploymentBlocker(code="DEPLOY_IMAGE_NOT_BUILT",
                              detail="x", owner="  ")


class TestTargetsPrecedeMeasurement(unittest.TestCase):
    """A target chosen after the numbers is a description."""

    def test_the_registry_declares_itself_predeclared(self):
        registry = target_registry()
        self.assertTrue(registry["declared_before_measurement"])
        self.assertEqual(registry["required_attempts"], 1000)

    def test_every_target_carries_a_rationale(self):
        for target in target_registry()["targets"]:
            with self.subTest(target=target["target_id"]):
                self.assertGreaterEqual(len(target["rationale"]), 40)

    def test_the_percentile_definition_is_stated_before_any_run(self):
        registry = target_registry()
        self.assertIn("nearest-rank",
                      str(registry["percentile_definition"]).lower())
        self.assertIn("null",
                      str(registry["zero_denominator_behaviour"]).lower())

    def test_the_targets_are_not_a_clinical_claim(self):
        self.assertIn("not clinical performance claims",
                      str(target_registry()["not_a_clinical_claim"]))

    def test_the_drill_catalogue_is_declared_before_execution(self):
        catalogue = drill_catalogue()
        self.assertGreaterEqual(int(catalogue["drill_count"]), 12)
        for drill in catalogue["drills"]:
            with self.subTest(drill=drill["drill_id"]):
                self.assertTrue(drill["injected_failure"].strip())
                self.assertTrue(drill["expected_behaviour"].strip())


class TestWp23HistoryIsNotRewritten(unittest.TestCase):
    """WP-24 publishes successors, never replacements."""

    def test_the_backup_document_declares_what_it_supersedes(self):
        document = backup_execution_status()
        self.assertEqual(document["supersedes"],
                         "data/security/wp23-backup-restore-status.json")
        self.assertIn("true statement", str(document["supersedes_note"]))

    def test_wp23s_committed_artifact_still_reports_its_own_state(self):
        """Read from disk. If WP-24 had rewritten it, this would fail - and
        it is the check that would notice."""
        import io
        import json

        with io.open("data/security/wp23-backup-restore-status.json",
                     encoding="utf-8") as handle:
            wp23 = json.load(handle)
        self.assertFalse(wp23["backup_executed"])
        self.assertFalse(wp23["restore_executed"])

    def test_gate_e_reads_both_halves_and_infers_neither(self):
        gate = build_wp24_gate_status(".")
        status = build_gate_e_status(".", wp24=gate)
        self.assertEqual(status["gate_e_status"], "BLOCKED")
        self.assertEqual(status["wp23_security_gate_status"], "BLOCKED")
        self.assertIn("neither is inferred from the other",
                      str(status["note"]))


class TestTheFourRestoreConditions(unittest.TestCase):
    """All four, or the restore is not verified."""

    def test_an_unevaluated_condition_is_null_not_false(self):
        result = evaluate_restore()
        self.assertEqual(result["unevaluated_count"], 4)
        for condition in result["conditions"]:
            with self.subTest(condition=condition["condition_id"]):
                self.assertIsNone(condition["satisfied"])

    def test_three_of_four_is_not_verified(self):
        result = evaluate_restore(
            separate_target=True,
            restored_head="0011_wp23_auth_audit",
            expected_head="0011_wp23_auth_audit",
            chain_verified=True, restored_event_count=10,
            exported_head_sequence=10,
            unresolved_manifest_hashes=["sha256:missing"])
        self.assertEqual(result["satisfied_count"], 3)
        self.assertFalse(result["all_satisfied"])

    def test_a_truncated_restore_is_caught_by_the_count_comparison(self):
        """The chain verifies perfectly and is short. Only comparing against
        the separately exported head sequence notices."""
        result = evaluate_restore(
            separate_target=True,
            restored_head="0011_wp23_auth_audit",
            expected_head="0011_wp23_auth_audit",
            chain_verified=True, restored_event_count=7,
            exported_head_sequence=10,
            unresolved_manifest_hashes=[])
        chain = [item for item in result["conditions"]
                 if item["condition_id"] == "RESTORE-03"][0]
        self.assertFalse(chain["satisfied"])

    def test_restoring_into_the_source_is_not_a_verification(self):
        result = evaluate_restore(separate_target=False)
        first = result["conditions"][0]
        self.assertFalse(first["satisfied"])

    def test_a_temporary_destination_is_not_an_operational_backup(self):
        document = backup_execution_status(
            destination="/tmp/pgx-dump", backup_taken=True)
        self.assertEqual(document["destination_kind"], "temporary")
        self.assertNotEqual(document["operational_status"], "VERIFIED")

    def test_a_local_drill_is_labelled_rather_than_promoted(self):
        satisfied = evaluate_restore(
            separate_target=True,
            restored_head="0011_wp23_auth_audit",
            expected_head="0011_wp23_auth_audit",
            chain_verified=True, restored_event_count=10,
            exported_head_sequence=10, unresolved_manifest_hashes=[])
        document = backup_execution_status(
            destination="/var/backups/pgx", backup_taken=True,
            restore=satisfied, local_rehearsal=True)
        self.assertEqual(document["operational_status"],
                         "LOCAL_REHEARSAL_VERIFIED")
        self.assertEqual(document["state"],
                         ExecutionState.TEST_ONLY_REHEARSAL.value)

    def test_absent_holdout_storage_is_null_not_false(self):
        """'There is nothing to back up' and 'there was something and we did
        not' are different facts."""
        document = backup_execution_status()
        self.assertIsNone(
            document["scope"]["restricted_holdout_storage"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
