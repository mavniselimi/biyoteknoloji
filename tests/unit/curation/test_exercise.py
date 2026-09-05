# -*- coding: utf-8 -*-
"""The inter-curator exercise and its comparison (WP-09).

The comparison is the part most easily turned into something it must not be.
Reporting that two curators agreed is useful; reporting it as validity is not,
because two curators may agree and both be wrong.
"""

from __future__ import annotations

import io
import json
import os
import unittest

from pgx.application.curation_schema import (
    validate_inter_curator_comparison, validate_inter_curator_exercise)
from pgx.curation.errors import CurationError, RoleSeparationError
from pgx.curation.exercises import (CASE_SELECTORS, COMPARED_FIELDS,
                                    EXERCISE_STATUS_AWAITING, CuratorResponse,
                                    build_exercise_packet, compare_responses,
                                    response_template)
from pgx.curation.vocabulary import CaseRole

from tests.unit.curation._support import (EVIDENCE_BUILD, EXERCISE_DIR,
                                          PROPOSALS)


def _packet():
    return build_exercise_packet(EVIDENCE_BUILD, PROPOSALS)


def _answers(packet, **values):
    base = {"included_evidence": [], "excluded_evidence": [],
            "exclusion_reasons": {}, "normalized_phenotypes": [],
            "effect_dimension": "ACTIVATION", "conclusion_state": "SUPPORTED",
            "applicability": "APPLICABLE", "conflict_state": "NONE_IDENTIFIED",
            "insufficiency_reasons": []}
    base.update(values)
    return {case.case_id: dict(base,
                               included_evidence=list(case.evidence_record_uuids))
            for case in packet.cases}


def _response(packet, label, name, **values):
    return CuratorResponse(exercise_id=packet.exercise_id, curator_label=label,
                           curator_name=name,
                           answers=_answers(packet, **values), completed=True)


class TestExerciseReferencesRealEvidence(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(EVIDENCE_BUILD):
            raise unittest.SkipTest("no sealed evidence build")
        cls.packet = _packet()
        with io.open(os.path.join(EVIDENCE_BUILD, "evidence-records.ndjson"),
                     encoding="utf-8") as handle:
            cls.uuids = {json.loads(line)["record_uuid"]
                         for line in handle if line.strip()}

    def test_every_cited_record_exists_in_the_build(self):
        for case in self.packet.cases:
            for uuid_value in case.evidence_record_uuids:
                with self.subTest(case=case.case_id):
                    self.assertIn(uuid_value, self.uuids)

    def test_the_packet_names_the_build_it_came_from(self):
        self.assertTrue(self.packet.evidence_build_content_hash
                        .startswith("sha256:"))

    def test_generation_is_deterministic(self):
        self.assertEqual(_packet().content_hash(),
                         self.packet.content_hash())

    def test_no_record_is_used_by_two_cases(self):
        used = [uuid_value for case in self.packet.cases
                for uuid_value in case.evidence_record_uuids]
        self.assertEqual(len(used), len(set(used)))

    def test_the_packet_covers_several_record_types(self):
        types = {case.record_types[0] for case in self.packet.cases}
        self.assertGreaterEqual(len(types), 3)

    def test_every_case_holds_the_exercise_role_only(self):
        for case in self.packet.cases:
            self.assertEqual(case.case_role, CaseRole.INTER_CURATOR_EXERCISE)

    def test_situations_this_corpus_lacks_are_recorded_not_omitted(self):
        selectors = {name for name, _ in CASE_SELECTORS}
        covered = {case.selector for case in self.packet.cases}
        recorded = {item["selector"] for item in self.packet.unmatched_selectors}
        self.assertEqual(covered | recorded, selectors)

    def test_the_packet_validates_against_its_schema(self):
        payload = self.packet.to_json()
        self.assertEqual(validate_inter_curator_exercise(payload), ())


class TestNoExpectedAnswersInTheBlindPacket(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(EVIDENCE_BUILD):
            raise unittest.SkipTest("no sealed evidence build")
        cls.packet = _packet()

    def test_no_case_carries_an_answer_field(self):
        for case in self.packet.cases:
            payload = case.to_json()
            for forbidden in ("expected_answer", "answer", "correct",
                              "conclusion_state", "effect_dimension",
                              "gold", "reference_answer"):
                with self.subTest(case=case.case_id, field=forbidden):
                    self.assertNotIn(forbidden, payload)

    def test_a_template_is_not_a_completed_response(self):
        template = response_template(self.packet, "A")
        response = CuratorResponse(
            exercise_id=template["exercise_id"],
            curator_label="A", curator_name=template["curator_name"],
            answers=template["answers"], completed=template["completed"])
        self.assertFalse(response.is_complete)

    def test_a_named_curator_with_blank_answers_is_still_incomplete(self):
        template = response_template(self.packet, "A")
        response = CuratorResponse(
            exercise_id=self.packet.exercise_id, curator_label="A",
            curator_name="Dr Ayse Yilmaz", answers=template["answers"],
            completed=True)
        self.assertFalse(response.is_complete)

    def test_an_unnamed_curator_with_full_answers_is_incomplete(self):
        response = CuratorResponse(
            exercise_id=self.packet.exercise_id, curator_label="A",
            curator_name=None, answers=_answers(self.packet), completed=True)
        self.assertFalse(response.is_complete)


class TestLegacyHintsAreBlinded(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(EVIDENCE_BUILD):
            raise unittest.SkipTest("no sealed evidence build")
        cls.packet = _packet()

    def test_every_case_is_blinded(self):
        for case in self.packet.cases:
            self.assertTrue(case.legacy_hint_blinded)

    def test_a_case_carries_the_hint_id_but_never_the_hint(self):
        linked = [case for case in self.packet.cases
                  if case.linked_legacy_proposal_ids]
        self.assertTrue(linked, "no case links a legacy hint, so blinding is "
                                "untested by this packet")
        for case in linked:
            payload = json.dumps(case.to_json())
            for forbidden in ("demo_risk_level", "risk_meaning",
                              "plain_language_mvp", "effect_direction",
                              "evidence_strength", "usable_for_mvp"):
                with self.subTest(case=case.case_id, field=forbidden):
                    self.assertNotIn(forbidden, payload)

    def test_an_unblinded_case_is_refused(self):
        case = self.packet.cases[0]
        with self.assertRaises(CurationError):
            type(case)(**dict(
                {name: getattr(case, name)
                 for name in case.__dataclass_fields__},
                legacy_hint_blinded=False))


class TestComparisonRequiresCompletedResponses(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(EVIDENCE_BUILD):
            raise unittest.SkipTest("no sealed evidence build")
        cls.packet = _packet()

    def test_two_blank_templates_are_refused(self):
        template = response_template(self.packet, "A")
        blank = CuratorResponse(self.packet.exercise_id, "A", None,
                                template["answers"], False)
        with self.assertRaises(CurationError) as caught:
            compare_responses(self.packet, blank, blank)
        self.assertIn("blank template", str(caught.exception).lower())

    def test_two_responses_by_one_person_are_refused(self):
        a = _response(self.packet, "A", "Dr Ayse Yilmaz")
        b = _response(self.packet, "B", "dr ayse yilmaz")
        with self.assertRaises(RoleSeparationError):
            compare_responses(self.packet, a, b)

    def test_a_response_to_another_exercise_is_refused(self):
        a = _response(self.packet, "A", "Dr Ayse Yilmaz")
        b = CuratorResponse("other-exercise", "B", "Dr Mehmet Kaya",
                            _answers(self.packet), True)
        with self.assertRaises(CurationError):
            compare_responses(self.packet, a, b)


class TestComparisonDoesNotAdjudicate(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(EVIDENCE_BUILD):
            raise unittest.SkipTest("no sealed evidence build")
        cls.packet = _packet()
        cls.a = _response(cls.packet, "A", "Dr Ayse Yilmaz")
        cls.b_agree = _response(cls.packet, "B", "Dr Mehmet Kaya")
        cls.b_differ = _response(
            cls.packet, "B", "Dr Mehmet Kaya",
            conclusion_state="INSUFFICIENT",
            effect_dimension="INSUFFICIENT_TO_CLASSIFY",
            applicability="UNCLEAR", conflict_state="PRESENT")

    def test_it_reports_no_winner_consensus_or_score(self):
        payload = compare_responses(self.packet, self.a,
                                    self.b_differ).to_json()
        for forbidden in ("winner", "correct_response", "consensus",
                          "merged_response", "agreement_score", "validity",
                          "resolution", "adjudication"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, payload)

    def test_it_says_agreement_is_not_correctness(self):
        payload = compare_responses(self.packet, self.a,
                                    self.b_agree).to_json()
        self.assertIn("Agreement is not evidence of correctness",
                      payload["note"])

    def test_synthetic_disagreement_is_reported_per_field(self):
        report = compare_responses(self.packet, self.a, self.b_differ)
        summary = report.summary()
        self.assertGreater(summary["fields_differing"], 0)
        for name in ("conclusion_state", "effect_dimension", "applicability",
                     "conflict_state"):
            self.assertEqual(summary["by_field"][name]["agree"], 0)

    def test_synthetic_agreement_is_reported_as_agreement(self):
        summary = compare_responses(self.packet, self.a,
                                    self.b_agree).summary()
        self.assertEqual(summary["fields_differing"], 0)

    def test_both_values_are_reported_even_when_they_agree(self):
        """A report showing only differences would let a reader assume the
        rest was verified, when two people merely said the same thing."""
        report = compare_responses(self.packet, self.a, self.b_agree)
        field = report.case_results[0]["fields"]["conclusion_state"]
        self.assertIn("a", field)
        self.assertIn("b", field)

    def test_evidence_sets_are_compared_as_sets(self):
        """The order a curator listed evidence in is not a disagreement."""
        first = self.packet.cases[0]
        reversed_answers = dict(self.a.answers)
        reversed_answers[first.case_id] = dict(
            reversed_answers[first.case_id],
            included_evidence=list(reversed(
                reversed_answers[first.case_id]["included_evidence"])))
        b = CuratorResponse(self.packet.exercise_id, "B", "Dr Mehmet Kaya",
                            reversed_answers, True)
        report = compare_responses(self.packet, self.a, b)
        self.assertTrue(
            report.case_results[0]["fields"]["included_evidence"]["agree"])

    def test_every_declared_field_is_compared(self):
        report = compare_responses(self.packet, self.a, self.b_differ)
        compared = set(report.case_results[0]["fields"])
        self.assertEqual(compared, {name for name, _ in COMPARED_FIELDS})

    def test_the_report_validates_against_its_schema(self):
        payload = compare_responses(self.packet, self.a,
                                    self.b_differ).to_json()
        payload["status"] = "COMPLETED"
        self.assertEqual(validate_inter_curator_comparison(payload), ())


class TestTheRealExerciseRemainsPending(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(EXERCISE_DIR):
            raise unittest.SkipTest("no exercise artifacts in this checkout")

    def _read(self, name):
        with io.open(os.path.join(EXERCISE_DIR, name),
                     encoding="utf-8") as handle:
            return json.load(handle)

    def test_the_status_is_awaiting_human_curators(self):
        self.assertEqual(self._read("status.json")["status"],
                         EXERCISE_STATUS_AWAITING)

    def test_neither_curator_is_assigned(self):
        status = self._read("status.json")
        for label in ("curator_a", "curator_b"):
            self.assertFalse(status[label]["assigned"])
            self.assertIsNone(status[label]["name"])
            self.assertFalse(status[label]["completed"])

    def test_the_comparison_is_pending_rather_than_empty(self):
        payload = self._read("comparison.pending.json")
        self.assertEqual(payload["status"], "PENDING_TWO_COMPLETED_RESPONSES")
        self.assertIsNone(payload["cases"])
        self.assertTrue(payload["blocked_by"])

    def test_the_templates_are_blank(self):
        for name in ("curator-a.template.json", "curator-b.template.json"):
            payload = self._read(name)
            with self.subTest(template=name):
                self.assertIsNone(payload["curator_name"])
                self.assertFalse(payload["completed"])
                for answer in payload["answers"].values():
                    self.assertIsNone(answer["conclusion_state"])

    def test_the_adjudication_template_is_undecided(self):
        payload = self._read("adjudication.template.json")
        self.assertFalse(payload["is_decided"])
        self.assertIsNone(payload["adjudicator_name"])
        self.assertEqual(len(payload["preserved_responses"]), 2)
