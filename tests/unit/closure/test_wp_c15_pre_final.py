# -*- coding: utf-8 -*-
"""WP-C15 - the PRE-EXPERT / NOT FINAL inventory, and the Wave 5 status.

The interesting tests are the four forbidden values. Each is asserted false
here, and each is also guarded in the builder, so a future edit that sets one
fails twice.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
INVENTORY = os.path.join(REPO, "data", "closure", "wp-c15",
                         "pre-final-evidence-inventory.json")
TEMPLATES = os.path.join(REPO, "data", "closure", "wp-c15", "templates")
STATUS = os.path.join(REPO, "data", "closure", "wave-05-status.json")
HUMAN_REQUIRED = "HUMAN_REQUIRED"


def _read(path):
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


class TestTheInventoryIsNotFinal(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.inventory = _read(INVENTORY)

    def test_it_is_labelled_pre_expert_and_not_final(self):
        self.assertEqual(self.inventory["status"], "PRE-EXPERT / NOT FINAL")
        self.assertFalse(self.inventory["is_final"])

    def test_it_says_why_it_is_not_final(self):
        self.assertIn("WP-C12 has not happened",
                      self.inventory["why_not_final"])

    def test_every_expert_dependent_field_is_human_required(self):
        fields = self.inventory["expert_dependent_fields"]
        self.assertTrue(fields)
        for name, value in sorted(fields.items()):
            with self.subTest(field=name):
                self.assertEqual(value, HUMAN_REQUIRED)

    def test_no_listed_artifact_is_missing(self):
        self.assertEqual(self.inventory["missing_artifacts"], [])

    def test_every_evidence_row_says_what_it_does_not_establish(self):
        """An inventory that only listed files would let a reader assume
        each one proves something."""
        self.assertGreaterEqual(self.inventory["evidence_item_count"], 15)
        for row in self.inventory["evidence"]:
            with self.subTest(artifact=row["artifact"]):
                self.assertTrue(row["what_it_establishes"].strip())
                self.assertTrue(row["what_it_does_not_establish"].strip())

    def test_every_evidence_hash_still_matches_the_file(self):
        import hashlib
        for row in self.inventory["evidence"]:
            path = os.path.join(REPO, *row["artifact"].split("/"))
            with self.subTest(artifact=row["artifact"]):
                self.assertTrue(os.path.isfile(path))
                with io.open(path, "rb") as handle:
                    measured = ("sha256:"
                                + hashlib.sha256(handle.read()).hexdigest())
                self.assertEqual(row["sha256"], measured)

    def test_it_reports_wp25_values_rather_than_computing_them(self):
        carried = self.inventory["carried_from_wp25_unchanged"]
        status = _read(os.path.join(REPO, "data", "ths6",
                                    "wp25-ths6-status.json"))
        self.assertEqual(carried["ths6_achieved"], status["ths6_achieved"])
        self.assertEqual(carried["release_may_proceed"],
                         status["release_may_proceed"])
        self.assertIn("never overridden here", carried["note"])


class TestTheFourForbiddenValues(unittest.TestCase):
    """ths6_achieved, release_may_proceed, six passing gates, DoD 15/15."""

    @classmethod
    def setUpClass(cls):
        cls.carried = _read(INVENTORY)["carried_from_wp25_unchanged"]
        cls.summary = _read(os.path.join(TEMPLATES,
                                         "ths6-summary.template.json"))

    def test_ths6_is_not_achieved(self):
        self.assertIs(self.carried["ths6_achieved"], False)
        self.assertIs(self.summary["ths6_achieved"], False)

    def test_the_release_may_not_proceed(self):
        self.assertIs(self.carried["release_may_proceed"], False)
        self.assertIs(self.summary["release_may_proceed"], False)

    def test_the_gates_do_not_all_pass(self):
        self.assertIs(self.carried["all_gates_pass"], False)
        self.assertEqual(self.carried["passing_gate_count"], 0)
        self.assertEqual(self.carried["gate_count"], 6)

    def test_the_definition_of_done_is_not_fifteen_of_fifteen(self):
        self.assertEqual(self.carried["definition_of_done_enumerated"], 15)
        self.assertLess(self.carried["definition_of_done_satisfied"], 15)

    def test_no_attestation_is_signed(self):
        self.assertEqual(self.carried["signed_signoff_count"], 0)
        self.assertEqual(self.summary["signed_attestation_count"], 0)

    def test_the_builder_refuses_to_write_over_a_completed_state(self):
        """Mutate WP-25's own values in memory and check the guard fires."""
        sys.path.insert(0, REPO)
        from importlib import util
        spec = util.spec_from_file_location(
            "_wpc15", os.path.join(REPO, "scripts",
                                   "build_wp_c15_inventory.py"))
        module = util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module._guard({}, {}, {}), [])
        self.assertIn("ths6_achieved is true",
                      module._guard({"ths6_achieved": True}, {}, {}))
        self.assertIn("release_may_proceed is true",
                      module._guard({"release_may_proceed": True}, {}, {}))
        self.assertIn("all six gates pass",
                      module._guard({}, {"all_gates_pass": True}, {}))
        self.assertIn("all six gates pass",
                      module._guard({}, {"passing_gate_count": 6}, {}))
        self.assertIn("the Definition of Done is 15/15",
                      module._guard({}, {}, {"satisfied_count": 15}))


class TestTheTemplatesAreUnsigned(unittest.TestCase):

    EXPECTED = (
        ("final-gate-report.template.json", "TEMPLATE_NOT_A_REPORT"),
        ("definition-of-done.template.json", "TEMPLATE_NOT_A_REPORT"),
        ("human-attestation-packet.template.json",
         "TEMPLATE_NOT_AN_ATTESTATION"),
        ("final-release-decision.template.json", "TEMPLATE_NOT_A_DECISION"),
        ("ths6-summary.template.json", "TEMPLATE_NOT_A_SUMMARY"),
    )

    def test_all_five_exist_and_declare_themselves_templates(self):
        for name, state in self.EXPECTED:
            path = os.path.join(TEMPLATES, name)
            with self.subTest(template=name):
                self.assertTrue(os.path.isfile(path))
                self.assertEqual(_read(path)["state"], state)

    def test_all_five_are_labelled_pre_expert(self):
        for name, _ in self.EXPECTED:
            with self.subTest(template=name):
                self.assertEqual(_read(os.path.join(TEMPLATES, name))
                                 ["status"], "PRE-EXPERT / NOT FINAL")

    def test_no_attestation_packet_carries_a_signature(self):
        packets = _read(os.path.join(
            TEMPLATES, "human-attestation-packet.template.json"))
        self.assertEqual(packets["signed_count"], 0)
        self.assertTrue(packets["packets"])
        for packet in packets["packets"]:
            for field in ("signatory_name", "signature_text", "signed_at",
                          "professional_qualification"):
                with self.subTest(role=packet["role_id"], field=field):
                    self.assertEqual(packet[field], HUMAN_REQUIRED)

    def test_no_attestation_packet_invents_a_person(self):
        packets = _read(os.path.join(
            TEMPLATES, "human-attestation-packet.template.json"))
        rendered = json.dumps(packets)
        for name in ("Mehmet", "Yetiş", "Abdülkadir"):
            with self.subTest(name=name):
                self.assertNotIn(name, rendered)

    def test_identity_verification_is_not_overclaimed(self):
        packets = _read(os.path.join(
            TEMPLATES, "human-attestation-packet.template.json"))
        self.assertEqual(packets["identity_verification"], "NONE_PERFORMED")

    def test_no_gate_carries_a_final_status(self):
        report = _read(os.path.join(TEMPLATES,
                                    "final-gate-report.template.json"))
        self.assertEqual(report["all_gates_pass"], HUMAN_REQUIRED)
        self.assertTrue(report["gates"])
        for row in report["gates"]:
            with self.subTest(gate=row["gate_id"]):
                self.assertEqual(row["final_status"], HUMAN_REQUIRED)

    def test_no_definition_of_done_item_is_marked_satisfied(self):
        dod = _read(os.path.join(TEMPLATES,
                                 "definition-of-done.template.json"))
        self.assertEqual(dod["satisfied_count"], HUMAN_REQUIRED)
        self.assertEqual(dod["all_items_satisfied"], HUMAN_REQUIRED)
        self.assertEqual(len(dod["items"]), 15)
        for item in dod["items"]:
            with self.subTest(item=item["dod_id"]):
                self.assertEqual(item["final_state"], HUMAN_REQUIRED)

    def test_the_release_decision_names_its_preconditions(self):
        decision = _read(os.path.join(
            TEMPLATES, "final-release-decision.template.json"))
        self.assertEqual(decision["decision"], HUMAN_REQUIRED)
        joined = " ".join(decision["preconditions_that_must_hold_first"])
        self.assertIn("genuine external expert response", joined)
        self.assertIn("disposition and a written rationale", joined)
        self.assertIn("WP-13 governed path", joined)

    def test_the_ths6_summary_records_false_rather_than_blank(self):
        """A blank could be completed by filling it in. False is the value."""
        summary = _read(os.path.join(TEMPLATES,
                                     "ths6-summary.template.json"))
        self.assertIs(summary["ths6_achieved"], False)
        self.assertIs(summary["external_expert_review_received"], False)
        self.assertIn("not HUMAN_REQUIRED", summary["ths6_achieved_note"])


class TestTheWave5Status(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.status = _read(STATUS)

    def test_the_vocabulary_is_the_required_five_lines(self):
        self.assertEqual(self.status["status_vocabulary"], [
            "AUTONOMOUS PREPARATION COMPLETE",
            "AWAITING GENUINE EXTERNAL EXPERT EVALUATION",
            "WP-C12 HUMAN STEP OPEN",
            "WP-C14B NOT STARTED",
            "WP-C15 NOT FINAL",
        ])

    def test_every_check_passed_and_none_was_removed(self):
        self.assertEqual(self.status["failed_checks"], [])
        self.assertTrue(self.status["autonomous_preparation_complete"])
        self.assertGreaterEqual(self.status["check_count"], 20)
        self.assertEqual(len(self.status["checks"]),
                         self.status["check_count"])
        for check in self.status["checks"]:
            with self.subTest(check=check["check"]):
                self.assertTrue(check["passed"])

    def test_each_of_b1_to_b6_is_checked(self):
        scopes = {check["scope"] for check in self.status["checks"]}
        for scope in ("B1", "B2", "B3", "B4", "B5", "B6", "GUARD"):
            with self.subTest(scope=scope):
                self.assertIn(scope, scopes)

    def test_the_three_work_packages_are_open(self):
        states = {row["work_package"]: row["state"]
                  for row in self.status["work_packages"]}
        self.assertEqual(states["WP-C12"], "HUMAN_STEP_OPEN")
        self.assertEqual(states["WP-C14B"], "NOT_STARTED")
        self.assertEqual(states["WP-C15"], "NOT_FINAL")

    def test_it_names_the_exact_human_action_required(self):
        actions = self.status["exact_human_action_required"]
        self.assertGreaterEqual(len(actions), 5)
        joined = " ".join(actions)
        self.assertIn("scripts/wp_c14b_intake.py", joined)
        self.assertIn("blind-first", joined)

    def test_it_does_not_claim_the_software_is_correct(self):
        joined = " ".join(self.status["what_this_status_is_not"])
        self.assertIn("not a claim that the software is correct", joined)
        self.assertIn("not a claim that anything has been reviewed", joined)

    def test_the_status_builder_is_deterministic(self):
        result = subprocess.run(
            [sys.executable, "scripts/build_wave05_status.py"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(_read(STATUS), self.status)


if __name__ == "__main__":
    unittest.main()
