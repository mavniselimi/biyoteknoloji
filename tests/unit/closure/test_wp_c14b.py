# -*- coding: utf-8 -*-
"""WP-C14B - the correction machinery, and the refusals that keep it empty.

The tests that matter here are the ones that try to get a fabricated review
in. Each one constructs the most plausible fake it can and asserts that the
intake refuses it.
"""

from __future__ import annotations

import copy
import io
import json
import os
import subprocess
import sys
import unittest

from pgx.closure.wp_c14b import (DISPOSITIONS, HUMAN_REQUIRED,
                                 IMPACT_CLASSES, REFUSAL_CODES,
                                 SAFETY_CLASSES, affected_tests_for,
                                 benchmark_rerun_decision,
                                 correction_impact_matrix, empty_matrix,
                                 empty_register, extract_feedback_items,
                                 preserved_response, refusals_for)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
TEMPLATE = os.path.join(REPO, "data", "expert-package",
                        "reviewer-response-template.json")
REGISTER = os.path.join(REPO, "data", "closure", "wp-c14b",
                        "feedback-register.json")
MATRIX = os.path.join(REPO, "data", "closure", "wp-c14b",
                      "correction-impact-matrix.json")


def _read(path):
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _plausible_response():
    """The most convincing forgery this test can build, short of a person.

    Everything structurally required is filled in with something that looks
    like an answer. It is used to prove the intake accepts a *complete*
    response - and every other test in this class removes one thing from it
    and proves the intake stops.
    """
    return {
        "schema_version": "pgx-wave05-reviewer-response/1",
        "reviewed_release_public_id": "PGX-CANDIDATE-REL-20260906-001",
        "reviewed_frozen_combined_hash": "sha256:" + "a" * 64,
        "reviewed_package_manifest_hash": "sha256:" + "b" * 64,
        "reviewer": {"name": "A Reviewer",
                     "professional_qualification": "clinical pharmacist"},
        "conflict_of_interest": {"declaration": "none to declare"},
        "consent": {"consents_to_name_being_recorded": "yes"},
        "questionnaire": [
            {"question_id": "Q06-AMITRIPTYLINE-JOINT-REPRESENTATION",
             "answer": "the POOR/NORMAL cell is wrong",
             "severity": "MAJOR", "correction_priority": "P1"},
            {"question_id": "Q09-UNSAFE-REASSURANCE",
             "answer": "", "severity": None, "correction_priority": None},
        ],
        "unsafe_or_misleading_outputs": [
            {"input": "codeine + clopidogrel, no care setting",
             "why_unsafe": "the refusal reads as reassurance",
             "severity": "BLOCKING"},
        ],
        "overall_free_text_criticism": "the scope is too narrow to be useful",
        "signature": {"signed_name": "A Reviewer",
                      "signature_method": "TYPED_NAME",
                      "date": "2026-09-10"},
    }


class TestTheRegisterIsEmptyAndSaysWhy(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.register = _read(REGISTER)
        cls.matrix = _read(MATRIX)

    def test_it_holds_no_items(self):
        self.assertEqual(self.register["item_count"], 0)
        self.assertEqual(self.register["items"], [])

    def test_it_holds_no_preserved_response(self):
        self.assertEqual(self.register["preserved_responses"], [])
        self.assertEqual(self.register["reviewers"], [])

    def test_its_state_names_what_it_is_waiting_for(self):
        self.assertEqual(self.register["state"],
                         "AWAITING_GENUINE_EXTERNAL_EXPERT_RESPONSE")
        self.assertIn("WP-C12 is a human step",
                      self.register["empty_because"])

    def test_all_five_dispositions_are_defined(self):
        self.assertEqual(
            sorted(self.register["dispositions_vocabulary"]),
            ["ACCEPTED", "ACCEPTED_WITH_MODIFICATION",
             "DISAGREED_WITH_RATIONALE", "NOT_APPLICABLE",
             "REQUIRES_FUTURE_WORK"])
        self.assertEqual(sorted(DISPOSITIONS), sorted(
            self.register["dispositions_vocabulary"]))

    def test_the_impact_and_safety_vocabularies_are_defined(self):
        self.assertEqual(sorted(self.register["impact_classes_vocabulary"]),
                         sorted(IMPACT_CLASSES))
        self.assertEqual(sorted(self.register["safety_classes_vocabulary"]),
                         sorted(SAFETY_CLASSES))

    def test_it_records_what_it_may_not_do(self):
        joined = " ".join(self.register["may_not"])
        self.assertIn("without a preserved response file behind it", joined)
        self.assertIn("without a written rationale", joined)

    def test_the_matrix_is_empty_and_demands_nothing_invented(self):
        self.assertEqual(self.matrix["item_count"], 0)
        self.assertIsNone(self.matrix["before_metrics"])
        self.assertIsNone(self.matrix["after_metrics"])
        self.assertIsNone(
            self.matrix["representative_regression_demonstration"])
        self.assertFalse(self.matrix["benchmark_rerun"]["rerun_required"])
        self.assertIn("no review has been received",
                      self.matrix["benchmark_rerun"]["reason"])


class TestTheIntakeRefusesEverythingButARealResponse(unittest.TestCase):

    def test_it_refuses_the_blank_template(self):
        codes = {code for code, _ in refusals_for(_read(TEMPLATE))}
        self.assertIn("RESPONSE_IS_THE_TEMPLATE", codes)
        self.assertIn("HUMAN_REQUIRED_FIELD_REMAINS", codes)
        self.assertIn("NOT_SIGNED", codes)
        self.assertIn("REVIEWER_NOT_IDENTIFIED", codes)

    def test_it_accepts_a_structurally_complete_response(self):
        self.assertEqual(refusals_for(_plausible_response()), ())

    def test_one_remaining_human_required_field_is_enough_to_refuse(self):
        response = _plausible_response()
        response["questionnaire"][1]["answer"] = HUMAN_REQUIRED
        codes = {code for code, _ in refusals_for(response)}
        self.assertIn("HUMAN_REQUIRED_FIELD_REMAINS", codes)

    def test_a_human_required_field_is_found_however_deeply_nested(self):
        response = _plausible_response()
        response["reserved_case_answers"] = {
            "PGX-VAL-W4-EXP-01-TWO-DRUGS-ONE-GENE": {
                "reviewer_expected_attention": HUMAN_REQUIRED}}
        codes = {code for code, _ in refusals_for(response)}
        self.assertIn("HUMAN_REQUIRED_FIELD_REMAINS", codes)

    def test_it_refuses_an_unsigned_response(self):
        for field in ("signed_name", "date"):
            response = _plausible_response()
            response["signature"][field] = ""
            with self.subTest(missing=field):
                self.assertIn("NOT_SIGNED",
                              {c for c, _ in refusals_for(response)})

    def test_it_refuses_an_unidentified_reviewer(self):
        for field in ("name", "professional_qualification"):
            response = _plausible_response()
            response["reviewer"][field] = ""
            with self.subTest(missing=field):
                self.assertIn("REVIEWER_NOT_IDENTIFIED",
                              {c for c, _ in refusals_for(response)})

    def test_it_refuses_an_undeclared_conflict_of_interest(self):
        response = _plausible_response()
        response["conflict_of_interest"] = {}
        self.assertIn("CONFLICT_OF_INTEREST_NOT_DECLARED",
                      {c for c, _ in refusals_for(response)})

    def test_it_refuses_a_response_with_no_consent(self):
        response = _plausible_response()
        response["consent"] = {}
        self.assertIn("CONSENT_NOT_RECORDED",
                      {c for c, _ in refusals_for(response)})

    def test_it_refuses_a_response_that_answers_nothing(self):
        response = _plausible_response()
        response["questionnaire"] = []
        response["unsafe_or_misleading_outputs"] = []
        response["overall_free_text_criticism"] = ""
        self.assertIn("NOTHING_ANSWERED",
                      {c for c, _ in refusals_for(response)})

    def test_it_refuses_a_response_not_bound_to_a_release(self):
        response = _plausible_response()
        response["reviewed_frozen_combined_hash"] = ""
        self.assertIn("RELEASE_BINDING_ABSENT",
                      {c for c, _ in refusals_for(response)})

    def test_every_refusal_code_is_documented(self):
        response = _read(TEMPLATE)
        for code, _ in refusals_for(response):
            with self.subTest(code=code):
                self.assertIn(code, REFUSAL_CODES)


class TestFeedbackItemsComeOnlyFromReviewerText(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.items = extract_feedback_items(_plausible_response(),
                                           reviewer_slug="areviewer")

    def test_every_item_carries_verbatim_source_text(self):
        for item in self.items:
            with self.subTest(item=item["item_id"]):
                self.assertTrue(item["source_text_verbatim"].strip())

    def test_every_item_carries_the_path_it_was_read_from(self):
        for item in self.items:
            with self.subTest(item=item["item_id"]):
                self.assertTrue(item["source_path"])

    def test_an_unanswered_question_produces_no_item(self):
        """The second questionnaire entry is empty and must not appear."""
        subjects = [item["subject"] for item in self.items]
        self.assertIn("Q06-AMITRIPTYLINE-JOINT-REPRESENTATION", subjects)
        self.assertNotIn("Q09-UNSAFE-REASSURANCE", subjects)

    def test_an_empty_response_produces_no_items_at_all(self):
        self.assertEqual(extract_feedback_items({}, reviewer_slug="x"), ())

    def test_classification_and_disposition_are_left_to_a_person(self):
        for item in self.items:
            with self.subTest(item=item["item_id"]):
                self.assertEqual(item["impact_class"], HUMAN_REQUIRED)
                self.assertEqual(item["safety_class"], HUMAN_REQUIRED)
                self.assertEqual(item["disposition"], HUMAN_REQUIRED)
                self.assertEqual(item["disposition_rationale"],
                                 HUMAN_REQUIRED)

    def test_the_reviewers_own_severity_is_carried_unaltered(self):
        answered = [i for i in self.items
                    if i["subject"] == "Q06-AMITRIPTYLINE-JOINT-"
                                       "REPRESENTATION"]
        self.assertEqual(answered[0]["reviewer_severity"], "MAJOR")
        self.assertEqual(answered[0]["reviewer_correction_priority"], "P1")

    def test_item_identifiers_are_unique(self):
        identifiers = [item["item_id"] for item in self.items]
        self.assertEqual(len(identifiers), len(set(identifiers)))


class TestPreservationHashesWhatArrived(unittest.TestCase):

    def test_the_hash_is_of_the_received_bytes(self):
        import hashlib
        raw = b'{"a": 1}\n'
        record = preserved_response(raw, received_relative="x.json",
                                    reviewer_slug="r")
        self.assertEqual(record["sha256"],
                         "sha256:" + hashlib.sha256(raw).hexdigest())
        self.assertEqual(record["byte_length"], len(raw))

    def test_reserialising_would_produce_a_different_hash(self):
        """Which is why the record hashes bytes and not a parsed copy."""
        raw = b'{"a":  1}\n'
        reserialised = (json.dumps(json.loads(raw), indent=2,
                                   sort_keys=True) + "\n").encode("utf-8")
        self.assertNotEqual(raw, reserialised)
        self.assertNotEqual(
            preserved_response(raw, received_relative="x",
                               reviewer_slug="r")["sha256"],
            preserved_response(reserialised, received_relative="x",
                               reviewer_slug="r")["sha256"])


class TestTheRerunDecisionFailsTowardsRerunning(unittest.TestCase):

    @staticmethod
    def _item(impact, safety, item_id="I-1"):
        return {"item_id": item_id, "impact_class": impact,
                "safety_class": safety}

    def test_no_items_means_nothing_to_re_measure(self):
        decision = benchmark_rerun_decision(())
        self.assertFalse(decision["rerun_required"])
        self.assertIn("no review has been received", decision["reason"])

    def test_an_unclassified_item_forces_a_rerun(self):
        decision = benchmark_rerun_decision(
            [self._item(HUMAN_REQUIRED, HUMAN_REQUIRED)])
        self.assertTrue(decision["rerun_required"])
        self.assertEqual(decision["reason"], "undecided classification")

    def test_an_unsafe_item_forces_a_rerun(self):
        decision = benchmark_rerun_decision(
            [self._item("DOCUMENTATION", "UNSAFE_OUTPUT")])
        self.assertTrue(decision["rerun_required"])

    def test_incorrect_science_forces_a_rerun(self):
        self.assertTrue(benchmark_rerun_decision(
            [self._item("DOCUMENTATION", "INCORRECT_SCIENCE")]
        )["rerun_required"])

    def test_an_executable_impact_forces_a_rerun(self):
        for impact in ("RULE_CONTENT", "RULESET_SCOPE", "PHENOTYPE_MAPPING",
                       "REFUSAL_BEHAVIOUR"):
            with self.subTest(impact=impact):
                self.assertTrue(benchmark_rerun_decision(
                    [self._item(impact, "NO_SAFETY_IMPACT")]
                )["rerun_required"])

    def test_a_documentation_only_change_does_not(self):
        decision = benchmark_rerun_decision(
            [self._item("DOCUMENTATION", "NO_SAFETY_IMPACT")])
        self.assertFalse(decision["rerun_required"])
        self.assertEqual(decision["reason"],
                         "no item changes executable behaviour")

    def test_every_impact_class_selects_at_least_one_test_target(self):
        for impact in IMPACT_CLASSES:
            with self.subTest(impact=impact):
                self.assertTrue(affected_tests_for(impact))

    def test_an_undecided_impact_selects_nothing_and_says_so(self):
        matrix = correction_impact_matrix(
            [self._item(HUMAN_REQUIRED, HUMAN_REQUIRED)])
        self.assertEqual(matrix["rows"][0]["affected_tests"], [])
        self.assertIn("not selectable", matrix["rows"][0]
                      ["affected_tests_note"])

    def test_a_matrix_with_items_demands_before_and_after_metrics(self):
        matrix = correction_impact_matrix(
            [self._item("RULE_CONTENT", "UNSAFE_OUTPUT")])
        self.assertEqual(matrix["before_metrics"], HUMAN_REQUIRED)
        self.assertEqual(matrix["after_metrics"], HUMAN_REQUIRED)
        self.assertEqual(matrix["representative_regression_demonstration"],
                         HUMAN_REQUIRED)


class TestTheIntakeScriptRefusesAndWritesNothing(unittest.TestCase):
    """End to end, through the command the submission procedure documents."""

    def test_running_it_on_the_template_exits_three_and_writes_nothing(self):
        before = _read(REGISTER)
        result = subprocess.run(
            [sys.executable, "scripts/wp_c14b_intake.py",
             "--response", TEMPLATE, "--reviewer-slug", "not-a-reviewer"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(result.returncode, 3)
        self.assertIn("RESPONSE_IS_THE_TEMPLATE", result.stderr)
        self.assertIn("nothing was written", result.stderr)
        self.assertFalse(os.path.exists(os.path.join(
            REPO, "data", "expert-review",
            "wp-c12-response-not-a-reviewer.json")))
        self.assertEqual(_read(REGISTER), before)

    def test_a_bad_reviewer_slug_is_refused(self):
        result = subprocess.run(
            [sys.executable, "scripts/wp_c14b_intake.py",
             "--response", TEMPLATE, "--reviewer-slug", "Not A Slug"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)

    def test_running_it_with_no_response_rebuilds_the_empty_register(self):
        before, before_matrix = _read(REGISTER), _read(MATRIX)
        result = subprocess.run(
            [sys.executable, "scripts/wp_c14b_intake.py"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(_read(REGISTER), before)
        self.assertEqual(_read(MATRIX), before_matrix)


class TestTheEmptyArtifactsAreRegenerated(unittest.TestCase):

    def test_a_fresh_register_matches_the_committed_one(self):
        committed = _read(REGISTER)
        fresh = empty_register(reason=committed["empty_because"])
        self.assertEqual(fresh, committed)

    def test_a_fresh_matrix_matches_the_committed_one(self):
        committed = _read(MATRIX)
        fresh = empty_matrix(reason=committed["empty_because"])
        self.assertEqual(fresh, committed)

    def test_the_committed_register_is_not_quietly_populated(self):
        """If a future edit adds an item, this is what notices."""
        committed = copy.deepcopy(_read(REGISTER))
        self.assertEqual(committed["items"], [])
        self.assertEqual(committed["item_count"], 0)


if __name__ == "__main__":
    unittest.main()
