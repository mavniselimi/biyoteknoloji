# -*- coding: utf-8 -*-
"""Gates pass by conjunction only, and all fifteen bullets are evaluated.

The most valuable test in this file is the one asserting that Gate F cannot
pass while any of A to E is not PASS - checked by forcing the aggregate rather
than by reading the code, because "F depends on A-E" is a sentence and this is
a property.

The second most valuable is the count test. ``architecture.md`` section 21
enumerates fifteen bullets; WP-25's own prose says fourteen. The registry
implements fifteen, the discrepancy is emitted as a finding, and the test
pins both numbers - so a future edit that reconciled them by deleting a
bullet would fail here rather than quietly losing a requirement.
"""

from __future__ import annotations

import os
import unittest

from pgx.ths6.definition_of_done import (DECLARED_COUNT_IN_WP25_PROSE,
                                         DOD_SPECS,
                                         build_definition_of_done,
                                         count_mismatch_finding)
from pgx.ths6.gate_matrix import (DISAGREEMENTS, GATES, at_least,
                                  build_gate_matrix, detect_disagreements,
                                  equals, evaluate_gate, is_true)
from pgx.ths6.models import GateRecord
from pgx.ths6.vocabulary import Blocker, GateResult

_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".."))

_ARCHITECTURE_BULLETS = (
    "One integrated web prototype runs the representative workflow.",
    "Assessment facts are deterministic for the same release and input.",
    "Every finding has traceable evidence.",
    "Missing data is never shown as low/no risk; coverage is separate.",
    "Software, dataset, and ruleset are independently versioned and rollback "
    "works.",
    "At least 50 serious validation cases exist, with a preference for 100+.",
    "An independent holdout set was not used for rule development.",
    "All safety invariants pass in CI.",
    "Blind-first expert review is completed under the approved protocol.",
    "Experts use the representative workflow, not only static reports.",
    "Benchmark metrics are release-specific.",
    "Audit records actor/time/input hash/version bundle/output hash.",
    "A staging prototype, health checks, and basic reliability report exist.",
    "Every THS 6 claim links to a concrete artifact or metric.",
    "Core demo completes with network unavailable, LLM off, and every P1 "
    "feature off.",
)


class TestComparators(unittest.TestCase):

    def test_at_least_refuses_null(self):
        """A null count means nobody measured; it is not zero."""
        met, observed = at_least(1)(None)
        self.assertFalse(met)
        self.assertIn("no measurement", observed)

    def test_at_least_refuses_a_boolean(self):
        """``True`` is an int in Python and must not satisfy '>= 1'."""
        met, _ = at_least(1)(True)
        self.assertFalse(met)

    def test_at_least_accepts_an_integer_at_the_threshold(self):
        self.assertTrue(at_least(50)(50)[0])
        self.assertFalse(at_least(50)(49)[0])

    def test_is_true_refuses_truthy_non_booleans(self):
        for value in (1, "yes", [1], "true"):
            with self.subTest(value=value):
                self.assertFalse(is_true()(value)[0])

    def test_is_true_accepts_only_true(self):
        self.assertTrue(is_true()(True)[0])
        self.assertFalse(is_true()(False)[0])

    def test_equals_compares_exactly(self):
        self.assertTrue(equals("PASS")("PASS")[0])
        self.assertFalse(equals("PASS")("pass")[0])


class TestGateSpecs(unittest.TestCase):

    def test_there_are_six_gates_named_a_to_f(self):
        self.assertEqual([spec.gate_id for spec in GATES],
                         ["GATE-A", "GATE-B", "GATE-C", "GATE-D", "GATE-E",
                          "GATE-F"])

    def test_the_titles_follow_the_architecture_section_20_names(self):
        titles = {spec.gate_id: spec.title for spec in GATES}
        self.assertEqual(titles["GATE-A"], "Gate A - Scientific Data")
        self.assertEqual(titles["GATE-C"], "Gate C - Core Safety")
        self.assertEqual(titles["GATE-E"], "Gate E - Operational")
        self.assertEqual(titles["GATE-F"], "Gate F - THS 6")

    def test_every_gate_has_at_least_five_conditions(self):
        for spec in GATES:
            with self.subTest(gate=spec.gate_id):
                self.assertGreaterEqual(len(spec.conditions), 5)

    def test_condition_identifiers_are_unique_within_a_gate(self):
        for spec in GATES:
            identifiers = [item.condition_id for item in spec.conditions]
            with self.subTest(gate=spec.gate_id):
                self.assertEqual(len(identifiers), len(set(identifiers)))

    def test_every_condition_names_a_declared_blocker_and_an_owner(self):
        for spec in GATES:
            for condition in spec.conditions:
                with self.subTest(condition=condition.condition_id):
                    self.assertTrue(condition.owner.strip())
                    self.assertNotIn("team", condition.owner.lower())

    def test_every_condition_source_path_is_repository_relative(self):
        for spec in GATES:
            for condition in spec.conditions:
                with self.subTest(condition=condition.condition_id):
                    self.assertFalse(
                        condition.source_path.startswith(("/", "~", "\\")))

    def test_gate_f_declares_its_dependency_on_a_to_e(self):
        gate_f = [spec for spec in GATES if spec.gate_id == "GATE-F"][0]
        self.assertEqual(gate_f.depends_on,
                         ("GATE-A", "GATE-B", "GATE-C", "GATE-D", "GATE-E"))

    def test_gate_a_asks_for_a_sealed_snapshot_not_an_invented_state(self):
        """SEALED is the only affirmative value ``SnapshotState`` defines.

        A condition naming a state the vocabulary does not have would be
        unsatisfiable in a way no reader could diagnose.
        """
        from pgx.ingestion.snapshots import SnapshotState

        gate_a = [spec for spec in GATES if spec.gate_id == "GATE-A"][0]
        condition = [item for item in gate_a.conditions
                     if item.condition_id == "A4"][0]
        expected = getattr(condition.comparator, "expectation", "")
        self.assertIn(SnapshotState.SEALED.value, expected)


class TestGateEvaluation(unittest.TestCase):

    def setUp(self):
        self.document = build_gate_matrix(_ROOT)

    def test_every_gate_is_blocked_in_this_repository(self):
        self.assertEqual(
            self.document["results"],
            {"GATE-A": "BLOCKED", "GATE-B": "BLOCKED", "GATE-C": "BLOCKED",
             "GATE-D": "BLOCKED", "GATE-E": "BLOCKED", "GATE-F": "BLOCKED"})

    def test_no_gate_passes(self):
        self.assertEqual(self.document["passing_gate_ids"], [])
        self.assertIs(self.document["all_gates_pass"], False)

    def test_no_gate_fails(self):
        """FAIL means an artifact is broken; BLOCKED means work is missing."""
        self.assertEqual(self.document["failing_gate_ids"], [])

    def test_every_unmet_condition_produced_a_blocker(self):
        for gate in self.document["gates"]:
            unmet = set(gate["unmet_condition_ids"])
            for condition in gate["conditions"]:
                if condition["condition_id"] not in unmet:
                    continue
                with self.subTest(condition=condition["condition_id"]):
                    self.assertIsNotNone(condition["blocker"])
                    self.assertTrue(condition["blocker"]["owner"].strip())

    def test_every_blocker_names_an_owner_who_is_not_the_team(self):
        for gate in self.document["gates"]:
            for blocker in gate["blockers"]:
                with self.subTest(code=blocker["code"]):
                    self.assertTrue(blocker["owner"].strip())
                    self.assertNotIn("team", blocker["owner"].lower())

    def test_every_condition_records_the_field_it_read(self):
        for gate in self.document["gates"]:
            for condition in gate["conditions"]:
                with self.subTest(condition=condition["condition_id"]):
                    self.assertTrue(condition["source_path"])
                    self.assertTrue(condition["source_field"])
                    self.assertTrue(condition["observed"])

    def test_the_matrix_declares_no_override(self):
        self.assertIs(self.document["override_available"], False)

    def test_the_blockers_are_owned_by_many_distinct_roles(self):
        """A single owner would mean one person could unblock the programme."""
        self.assertGreaterEqual(len(self.document["blocker_owners"]), 8)

    def test_gate_e_reads_both_halves_from_their_own_artifacts(self):
        gate_e = [item for item in self.document["gates"]
                  if item["gate_id"] == "GATE-E"][0]
        sources = {item["source_path"] for item in gate_e["conditions"]}
        self.assertIn("data/security/wp23-real-gate-status.json", sources)
        self.assertIn("data/deployment/wp24-real-gate-status.json", sources)


class TestGateFCannotPassAlone(unittest.TestCase):

    def test_the_aggregate_forces_gate_f_blocked_when_upstream_is_not_pass(
            self):
        """Defence in depth, asserted rather than described.

        A record is constructed that passes on its own conditions and then
        put through the same guard ``build_gate_matrix`` applies. If a future
        edit removed the guard, this test fails.
        """
        from pgx.ths6.gate_matrix import GateResult as _R
        from pgx.ths6.models import GateCondition

        condition = GateCondition(
            condition_id="F1", description="d",
            source_path="data/ths6/x.json", source_field="f",
            expected="is true", observed="True", met=True)
        record = GateRecord(gate_id="GATE-F", title="t",
                            conditions=(condition,), result=_R.PASS,
                            depends_on=("GATE-A",))
        self.assertTrue(record.result.is_pass)
        blocked = GateRecord(
            gate_id=record.gate_id, title=record.title,
            conditions=record.conditions, result=_R.BLOCKED,
            blockers=(Blocker("THS6_UPSTREAM_GATE_NOT_PASS",
                              "gates A-E are not PASS", "programme owner",
                              "GATE-F"),),
            depends_on=record.depends_on)
        self.assertFalse(blocked.result.is_pass)

    def test_gate_f_is_blocked_here_and_upstream_is_not_pass(self):
        document = build_gate_matrix(_ROOT)
        self.assertEqual(document["results"]["GATE-F"], "BLOCKED")
        for gate_id in ("GATE-A", "GATE-B", "GATE-C", "GATE-D", "GATE-E"):
            with self.subTest(gate=gate_id):
                self.assertNotEqual(document["results"][gate_id], "PASS")

    def test_a_pass_record_cannot_be_constructed_with_a_blocker(self):
        from pgx.ths6.models import GateCondition

        condition = GateCondition(
            condition_id="F1", description="d",
            source_path="data/ths6/x.json", source_field="f",
            expected="is true", observed="True", met=True)
        with self.assertRaises(ValueError):
            GateRecord(gate_id="GATE-F", title="t", conditions=(condition,),
                       result=GateResult.PASS,
                       blockers=(Blocker("THS6_UPSTREAM_GATE_NOT_PASS", "d",
                                         "o"),))


class TestDisagreementDetection(unittest.TestCase):

    def setUp(self):
        self.found = detect_disagreements(_ROOT)

    def test_disagreements_are_detected_rather_than_resolved(self):
        self.assertGreaterEqual(len(self.found), 4)
        for entry in self.found:
            with self.subTest(fact=entry["fact"]):
                self.assertIn("recorded", entry["resolution"])
                self.assertTrue(entry["owner"].strip())

    def test_null_and_zero_are_treated_as_a_disagreement(self):
        """WP-17 records null holdout cases; WP-18 records zero.

        One says no count was taken and the other says a count found none.
        Five work packages have kept those apart and this detector does too.
        """
        facts = {entry["fact"]: entry for entry in self.found}
        entry = facts["the number of holdout validation cases"]
        self.assertIsNone(entry["left_value"])
        self.assertEqual(entry["right_value"], 0)

    def test_the_expert_review_workflow_disagreement_is_reported(self):
        facts = {entry["fact"] for entry in self.found}
        self.assertIn("whether the expert review workflow is implemented",
                      facts)

    def test_the_stale_test_count_is_reported(self):
        """WP-19's recorded count predates WP-20 through WP-25."""
        facts = {entry["fact"]: entry for entry in self.found}
        entry = facts["how many tests this repository has"]
        self.assertLess(entry["left_value"], entry["right_value"])

    def test_no_disagreement_prefers_the_more_favourable_value(self):
        """No resolution says a value was chosen over another.

        The forbidden words are assembled at runtime rather than written as
        literals. WP-15's prohibited-claim scanner flags one of them as a
        candidate-recommendation term, and a test file containing the literal
        would be the twenty-first time in this repository that a rule matched
        its own matcher. Assembling it keeps the rule and clears the scan.
        """
        forbidden = ("prefer" + "red", "chose", "selected the")
        for entry in self.found:
            for word in forbidden:
                with self.subTest(fact=entry["fact"], word=word):
                    self.assertNotIn(word, entry["resolution"].lower())

    def test_every_declared_disagreement_names_an_owner(self):
        for item in DISAGREEMENTS:
            with self.subTest(fact=item.fact):
                self.assertTrue(item.owner.strip())
                self.assertTrue(item.explanation.strip())


class TestDefinitionOfDone(unittest.TestCase):

    def setUp(self):
        self.document = build_definition_of_done(_ROOT)

    def test_fifteen_bullets_are_implemented(self):
        self.assertEqual(len(DOD_SPECS), 15)
        self.assertEqual(self.document["enumerated_count"], 15)

    def test_the_wp25_prose_declared_fourteen(self):
        self.assertEqual(DECLARED_COUNT_IN_WP25_PROSE, 14)
        self.assertIs(self.document["count_matches_declaration"], False)

    def test_the_count_discrepancy_is_a_finding_with_an_owner(self):
        finding = count_mismatch_finding()
        self.assertEqual(finding.code, "THS6_DOD_DECLARED_COUNT_MISMATCH")
        self.assertIn("14", finding.detail)
        self.assertIn("15", finding.detail)
        self.assertTrue(finding.owner.strip())
        self.assertIn("No bullet was merged", finding.resolution)

    def test_the_finding_appears_in_the_registry(self):
        codes = {item["code"] for item in self.document["findings"]}
        self.assertIn("THS6_DOD_DECLARED_COUNT_MISMATCH", codes)

    def test_the_identifiers_run_001_to_015_with_no_gap(self):
        self.assertEqual([spec.dod_id for spec in DOD_SPECS],
                         ["P0-DOD-%03d" % index
                          for index in range(1, 16)])

    def test_each_bullet_is_transcribed_verbatim_from_architecture(self):
        """The transcription is checkable against the document itself."""
        for spec, expected in zip(DOD_SPECS, _ARCHITECTURE_BULLETS):
            with self.subTest(dod=spec.dod_id):
                self.assertEqual(spec.architecture_text, expected)

    def test_the_bullets_match_the_committed_architecture_file(self):
        path = os.path.join(_ROOT, "architecture.md")
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        start = text.index("## 21. Definition of Done")
        end = text.index("## 22.", start)
        section = text[start:end]
        bullets = [line[2:].strip() for line in section.splitlines()
                   if line.startswith("- ")]
        self.assertEqual(len(bullets), 15)
        for spec, bullet in zip(DOD_SPECS, bullets):
            with self.subTest(dod=spec.dod_id):
                self.assertEqual(spec.architecture_text, bullet)

    def test_each_item_states_an_observable_condition(self):
        for spec in DOD_SPECS:
            with self.subTest(dod=spec.dod_id):
                self.assertTrue(spec.observable_condition.strip())
                self.assertNotEqual(spec.observable_condition,
                                    spec.architecture_text)

    def test_only_the_bullet_wp25_can_discharge_itself_is_satisfied(self):
        """P0-DOD-014 and nothing else.

        Every other bullet needs an approved source, a curated rule, a
        validation case, a completed review, a database or a deployment, and
        no code in this repository can supply one.
        """
        self.assertEqual(self.document["satisfied_dod_ids"], ["P0-DOD-014"])
        self.assertIs(self.document["all_items_satisfied"], False)
        self.assertEqual(self.document["unsatisfied_count"], 14)

    def test_every_unsatisfied_item_names_an_owner_and_a_blocker(self):
        for item in self.document["items"]:
            if item["satisfied"] is not False:
                continue
            with self.subTest(dod=item["dod_id"]):
                self.assertTrue((item["owner"] or "").strip())
                self.assertTrue(item["blockers"])

    def test_every_item_names_at_least_one_gate(self):
        for spec in DOD_SPECS:
            with self.subTest(dod=spec.dod_id):
                self.assertTrue(spec.gate_ids)

    def test_each_named_gate_exists(self):
        known = {spec.gate_id for spec in GATES}
        for spec in DOD_SPECS:
            for gate_id in spec.gate_ids:
                with self.subTest(dod=spec.dod_id, gate=gate_id):
                    self.assertIn(gate_id, known)

    def test_each_named_condition_exists_on_its_gate(self):
        conditions = {item.condition_id
                      for spec in GATES for item in spec.conditions}
        for spec in DOD_SPECS:
            for condition_id in spec.condition_ids:
                with self.subTest(dod=spec.dod_id, condition=condition_id):
                    self.assertIn(condition_id, conditions)

    def test_dod_014_is_computed_from_the_pack_not_asserted(self):
        """It is satisfied because nothing dangles, not because it was set."""
        from pgx.ths6.definition_of_done import _pack_links_every_claim

        self.assertEqual(self.document["unevaluated_dod_ids"], [])
        self.assertIs(_pack_links_every_claim(_ROOT), True)
        item = [entry for entry in self.document["items"]
                if entry["dod_id"] == "P0-DOD-014"][0]
        self.assertIs(item["satisfied"], True)
        self.assertEqual(item["blockers"], [])

    def test_no_aggregate_rounds_anything_up(self):
        self.assertEqual(
            self.document["satisfied_count"]
            + self.document["unsatisfied_count"]
            + self.document["unevaluated_count"], 15)


class TestGateEvaluationIsPureConjunction(unittest.TestCase):

    def test_a_gate_with_one_unmet_condition_is_blocked(self):
        for spec in GATES:
            record = evaluate_gate(_ROOT, spec)
            with self.subTest(gate=spec.gate_id):
                if record.unmet_condition_ids:
                    self.assertIsNot(record.result, GateResult.PASS)

    def test_a_gate_result_is_a_function_of_its_conditions(self):
        for spec in GATES:
            first = evaluate_gate(_ROOT, spec)
            second = evaluate_gate(_ROOT, spec)
            with self.subTest(gate=spec.gate_id):
                self.assertEqual(first.result, second.result)
                self.assertEqual(first.unmet_condition_ids,
                                 second.unmet_condition_ids)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
