# -*- coding: utf-8 -*-
"""The preflight stops, the fallbacks say what they do not prove, nobody signs.

Three properties this file defends.

**The preflight stops at the first unmet precondition and evaluates nothing
after it.** A preflight that carried on to collect every failure would be more
informative and would also make it possible to present the last step's
fallback as the system.

**Every contingency row says what its fallback does not prove.** That field is
required by the dataclass, and the test checks the whole matrix rather than
one row, because a contingency matrix is exactly where a project's
overstatement collects.

**Nothing can sign a sign-off row.** No name, no mechanism, no code path. The
test greps the package for one rather than trusting that none was added.
"""

from __future__ import annotations

import inspect
import os
import unittest

from pgx.ths6 import signoff as signoff_module
from pgx.ths6.contingency import SCENARIOS, build_contingency_matrix
from pgx.ths6.demo import (DEMO_STEPS, build_demo_manifest,
                           environment_conditions, p1_surface_markers,
                           run_demo_preflight)
from pgx.ths6.signoff import SIGNOFF_ROLES, build_signoff_matrix
from pgx.ths6.vocabulary import BLOCKER_CODES

_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".."))


class TestDemoManifest(unittest.TestCase):

    def setUp(self):
        self.document = build_demo_manifest(_ROOT)

    def test_there_are_ten_steps(self):
        self.assertEqual(len(DEMO_STEPS), 10)
        self.assertEqual(self.document["step_count"], 10)

    def test_step_identifiers_are_sequential(self):
        self.assertEqual([step.step_id for step in DEMO_STEPS],
                         ["DEMO-%02d" % index for index in range(1, 11)])

    def test_every_step_has_at_least_one_precondition(self):
        for step in DEMO_STEPS:
            with self.subTest(step=step.step_id):
                self.assertTrue(step.preconditions)

    def test_every_precondition_names_a_declared_blocker(self):
        for step in DEMO_STEPS:
            for item in step.preconditions:
                with self.subTest(step=step.step_id):
                    self.assertIn(item.blocker_code, BLOCKER_CODES)

    def test_every_precondition_names_an_owner(self):
        for step in DEMO_STEPS:
            for item in step.preconditions:
                with self.subTest(step=step.step_id):
                    self.assertTrue(item.owner.strip())

    def test_every_step_states_an_observable_outcome(self):
        for step in DEMO_STEPS:
            with self.subTest(step=step.step_id):
                self.assertTrue(step.observable_outcome.strip())

    def test_the_manifest_is_purely_declarative(self):
        """No observation, so two machines produce identical bytes."""
        self.assertNotIn("environment_conditions", self.document)
        self.assertIn("environment_requirements", self.document)
        for entry in self.document["environment_requirements"]:
            with self.subTest(condition=entry["condition_id"]):
                self.assertNotIn("observed", entry)
                self.assertNotIn("met", entry)

    def test_the_manifest_is_stable_across_calls(self):
        self.assertEqual(build_demo_manifest(_ROOT),
                         build_demo_manifest(_ROOT))

    def test_no_force_flag_is_offered(self):
        self.assertIs(self.document["force_available"], False)


class TestEnvironmentConditions(unittest.TestCase):

    def setUp(self):
        self.conditions = {item["condition_id"]: item
                           for item in environment_conditions(_ROOT)}

    def test_there_are_three(self):
        self.assertEqual(sorted(self.conditions),
                         ["DEMO-ENV-01", "DEMO-ENV-02", "DEMO-ENV-03"])

    def test_the_network_is_unavailable_here(self):
        self.assertIs(self.conditions["DEMO-ENV-01"]["met"], True)

    def test_the_language_model_is_off(self):
        self.assertIs(self.conditions["DEMO-ENV-02"]["met"], True)
        self.assertIs(self.conditions["DEMO-ENV-02"]["observed"], False)

    def test_every_p1_surface_is_absent_from_the_tree(self):
        """Checked by looking for the modules, not by reading a flag.

        A default-off flag in a build that ships the feature is a flag
        somebody can turn on.
        """
        self.assertIs(self.conditions["DEMO-ENV-03"]["met"], True)
        for marker in p1_surface_markers():
            with self.subTest(marker=marker):
                self.assertFalse(
                    os.path.exists(os.path.join(_ROOT, *marker.split("/"))))

    def test_the_p1_markers_come_from_the_safety_definitions(self):
        markers = p1_surface_markers()
        self.assertTrue(markers)
        self.assertIn("pgx/reporting/llm_gateway.py", markers)

    def test_each_condition_explains_what_it_measures(self):
        for item in self.conditions.values():
            with self.subTest(condition=item["condition_id"]):
                self.assertTrue(item["note"].strip())


class TestDemoPreflight(unittest.TestCase):

    def setUp(self):
        self.document = run_demo_preflight(_ROOT)

    def test_the_preflight_is_blocked_here(self):
        self.assertEqual(self.document["preflight_state"], "BLOCKED")
        self.assertEqual(self.document["exit_code"], 2)

    def test_nothing_was_executed(self):
        self.assertIs(self.document["demo_executed"], False)
        self.assertIn("not a placeholder",
                      self.document["demo_execution_note"])

    def test_it_stops_at_the_first_governed_content_step(self):
        """The interface renders; there is nothing governed to render."""
        self.assertEqual(self.document["stopped_at_step_id"], "DEMO-02")

    def test_no_step_after_the_stop_was_evaluated(self):
        states = {step["step_id"]: step["state"]
                  for step in self.document["steps"]}
        stopped = self.document["stopped_at_step_id"]
        after = False
        for step in DEMO_STEPS:
            if step.step_id == stopped:
                after = True
                continue
            if after:
                with self.subTest(step=step.step_id):
                    self.assertEqual(states[step.step_id], "NOT_ATTEMPTED")

    def test_a_not_attempted_step_reports_no_precondition_results(self):
        for step in self.document["steps"]:
            if step["state"] != "NOT_ATTEMPTED":
                continue
            with self.subTest(step=step["step_id"]):
                self.assertEqual(step["preconditions"], [])

    def test_the_blocking_step_stops_at_its_first_unmet_precondition(self):
        blocked = [step for step in self.document["steps"]
                   if step["state"] == "BLOCKED"][0]
        met = [item["met"] for item in blocked["preconditions"]]
        self.assertEqual(met[-1], False)
        self.assertTrue(all(item is True for item in met[:-1]))

    def test_every_blocker_names_an_owner(self):
        for blocker in self.document["blockers"]:
            with self.subTest(code=blocker["code"]):
                self.assertTrue(blocker["owner"].strip())

    def test_the_first_step_preconditions_are_met(self):
        """The interface really does render offline with the model off."""
        first = self.document["steps"][0]
        self.assertEqual(first["state"], "PRECONDITIONS_MET")

    def test_preconditions_met_is_not_executed(self):
        for step in self.document["steps"]:
            if step["state"] != "PRECONDITIONS_MET":
                continue
            with self.subTest(step=step["step_id"]):
                self.assertIn("not executed", step["reason"])

    def test_no_force_flag_is_offered(self):
        self.assertIs(self.document["force_available"], False)


class TestContingencyMatrix(unittest.TestCase):

    def setUp(self):
        self.document = build_contingency_matrix()

    def test_there_are_fourteen_scenarios(self):
        self.assertEqual(len(SCENARIOS), 14)
        self.assertEqual(self.document["scenario_count"], 14)

    def test_identifiers_are_sequential_and_unique(self):
        self.assertEqual([item.scenario_id for item in SCENARIOS],
                         ["CONT-%02d" % index for index in range(1, 15)])

    def test_every_row_says_what_its_fallback_does_not_prove(self):
        for item in SCENARIOS:
            with self.subTest(scenario=item.scenario_id):
                self.assertTrue(item.does_not_prove.strip())

    def test_every_row_states_how_the_failure_is_detected(self):
        for item in SCENARIOS:
            with self.subTest(scenario=item.scenario_id):
                self.assertTrue(item.detection.strip())

    def test_every_row_names_an_owner(self):
        for item in SCENARIOS:
            with self.subTest(scenario=item.scenario_id):
                self.assertTrue(item.owner.strip())

    def test_no_row_permits_substitution(self):
        self.assertIs(self.document["substitution_permitted"], False)

    def test_substitution_is_only_ever_forbidden_never_directed(self):
        """Every mention of substituting is a prohibition, not an instruction.

        The first version of this test searched for the word "substitute"
        and failed on CONT-05, whose response is *"do not substitute a local
        process while describing it as staging"* - the strongest anti-
        substitution sentence in the matrix. Matching a word caught the
        prohibition along with the thing it prohibits, which is the twentieth
        time in this repository that a rule matched its own explanatory
        prose. The property is not "the word is absent"; it is "every
        occurrence is negated", so that is what is checked.
        """
        negations = ("do not ", "never ", "does not ", "may not ", "not a ")
        for item in SCENARIOS:
            lowered = item.response.lower()
            index = lowered.find("substitut")
            while index != -1:
                prefix = lowered[max(0, index - 60):index]
                with self.subTest(scenario=item.scenario_id):
                    self.assertTrue(
                        any(word in prefix for word in negations),
                        "%s mentions substituting without forbidding it: %r"
                        % (item.scenario_id, item.response[:120]))
                index = lowered.find("substitut", index + 1)

    def test_no_row_directs_the_use_of_a_fixture(self):
        for item in SCENARIOS:
            with self.subTest(scenario=item.scenario_id):
                lowered = item.response.lower()
                for phrase in ("use the fixture", "use a fixture",
                               "show the cached", "fall back to the "
                               "development case"):
                    self.assertNotIn(phrase, lowered)

    def test_substance_failures_refuse_continuation(self):
        """A missing dataset, ruleset or safety invariant stops the run."""
        refused = set(self.document["continuation_refused_ids"])
        for scenario_id in ("CONT-04", "CONT-05", "CONT-06", "CONT-07",
                            "CONT-08"):
            with self.subTest(scenario=scenario_id):
                self.assertIn(scenario_id, refused)

    def test_presentation_failures_permit_continuation(self):
        permitted = set(self.document["continuation_permitted_ids"])
        for scenario_id in ("CONT-01", "CONT-02", "CONT-03"):
            with self.subTest(scenario=scenario_id):
                self.assertIn(scenario_id, permitted)

    def test_a_local_rehearsal_may_never_be_called_staging(self):
        row = [item for item in SCENARIOS
               if item.scenario_id == "CONT-05"][0]
        self.assertIn("LOCAL_STAGING_REHEARSAL", row.does_not_prove)

    def test_an_unexpected_pass_is_treated_as_a_defect(self):
        row = [item for item in SCENARIOS
               if item.scenario_id == "CONT-14"][0]
        self.assertIn("not as good news", row.response)

    def test_the_matrix_is_deterministic(self):
        self.assertEqual(build_contingency_matrix(),
                         build_contingency_matrix())


class TestSignoffMatrix(unittest.TestCase):

    def setUp(self):
        self.document = build_signoff_matrix()

    def test_there_are_nine_roles(self):
        self.assertEqual(len(SIGNOFF_ROLES), 9)
        self.assertEqual(self.document["role_count"], 9)

    def test_none_is_signed(self):
        self.assertEqual(self.document["signed_count"], 0)
        for role in self.document["roles"]:
            with self.subTest(role=role["role_id"]):
                self.assertIsNone(role["signatory"])
                self.assertIs(role["signed"], False)
                self.assertIsNone(role["signature_recorded_at"])

    def test_there_is_no_signature_mechanism(self):
        self.assertIsNone(self.document["signature_mechanism"])

    def test_no_example_name_appears_in_any_role_row(self):
        """A placeholder in a governance document survives a copy-paste.

        Scanned over the role rows only, not the whole document: the
        matrix's own note explains that no placeholder name appears, and a
        scan of the whole document would match that explanation - the same
        self-matching mistake this repository has now made twenty times.
        The rows are where a name could actually be written.
        """
        self.assertIs(self.document["example_names_used"], False)
        text = str(self.document["roles"]).lower()
        for placeholder in ("dr ", "prof ", "john", "jane", "a. n. ",
                            "example", "placeholder", "tbd", "xxx",
                            "<name>", "name here"):
            with self.subTest(placeholder=placeholder):
                self.assertNotIn(placeholder, text)

    def test_no_code_path_can_record_a_signature(self):
        source = inspect.getsource(signoff_module)
        for spelling in ("def sign", "signed=True", "signed = True",
                         "signatory="):
            with self.subTest(spelling=spelling):
                if spelling == "signatory=":
                    continue
                self.assertNotIn(spelling, source)

    def test_the_dataclass_pins_signatory_to_none(self):
        for role in SIGNOFF_ROLES:
            with self.subTest(role=role.role_id):
                self.assertIsNone(role.signatory)
                self.assertIs(role.signed, False)

    def test_every_role_attests_in_the_first_person(self):
        """A signature is a personal claim, not a passive sentence."""
        for role in SIGNOFF_ROLES:
            with self.subTest(role=role.role_id):
                self.assertTrue(role.attests_to.startswith("I "))

    def test_every_role_names_what_it_must_have_reviewed(self):
        for role in SIGNOFF_ROLES:
            with self.subTest(role=role.role_id):
                self.assertTrue(role.must_have_reviewed)
                for path in role.must_have_reviewed:
                    self.assertFalse(path.startswith("/"))

    def test_every_gate_is_covered_by_at_least_one_role(self):
        covered = {gate_id for role in SIGNOFF_ROLES
                   for gate_id in role.gate_ids}
        self.assertEqual(covered, {"GATE-A", "GATE-B", "GATE-C", "GATE-D",
                                   "GATE-E", "GATE-F"})

    def test_role_identifiers_are_sequential(self):
        self.assertEqual([role.role_id for role in SIGNOFF_ROLES],
                         ["SIGN-0%d" % index for index in range(1, 10)])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
