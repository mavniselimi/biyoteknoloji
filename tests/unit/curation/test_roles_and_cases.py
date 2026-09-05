# -*- coding: utf-8 -*-
"""Who may decide, and which cases may be used for what (WP-09)."""

from __future__ import annotations

import unittest

from pgx.curation.errors import (ApprovalError, CaseSeparationError,
                                 RoleSeparationError)
from pgx.curation.exercises import AdjudicationTemplate
from pgx.curation.models import ReviewSignature
from pgx.curation.protocol import (CASE_ROLE_RULES, ROLE_DEFINITIONS,
                                   CaseAssignment, RoleDefinition,
                                   check_case_separation)
from pgx.curation.vocabulary import (SCIENTIFIC_APPROVAL_ROLES, CaseRole,
                                     CurationRole, InterpretationStatus)

from tests.unit.curation._support import (AUTHOR, REVIEWER, NOW, rationale,
                                          record, signature)


class TestAuthorReviewerSeparation(unittest.TestCase):

    def test_the_same_person_cannot_review_their_own_conclusion(self):
        with self.assertRaises(RoleSeparationError) as caught:
            rationale(author=AUTHOR, reviewer=AUTHOR)
        self.assertIn("independent", str(caught.exception).lower())

    def test_the_comparison_is_case_insensitive(self):
        with self.assertRaises(RoleSeparationError):
            rationale(author="Dr Ayse Yilmaz", reviewer="dr ayse yilmaz")

    def test_two_different_people_are_accepted(self):
        item = rationale(author=AUTHOR, reviewer=REVIEWER)
        self.assertNotEqual(item.authored_by.person, item.reviewed_by.person)

    def test_curated_requires_a_named_reviewer(self):
        with self.assertRaises(RoleSeparationError):
            record(status=InterpretationStatus.CURATED,
                   rationale_obj=rationale(reviewer=None))

    def test_a_draft_needs_no_reviewer(self):
        item = record(status=InterpretationStatus.DRAFT,
                      rationale_obj=rationale(reviewer=None))
        self.assertIsNone(item.rationale.reviewed_by)


class TestOnlyScientificRolesApprove(unittest.TestCase):

    def test_engineering_and_provenance_roles_cannot_approve_science(self):
        for role in (CurationRole.ENGINEERING_OBSERVER,
                     CurationRole.DATA_PROVENANCE_STEWARD,
                     CurationRole.PROTOCOL_OWNER):
            with self.subTest(role=role):
                self.assertNotIn(role, SCIENTIFIC_APPROVAL_ROLES)

    def test_the_role_definitions_agree(self):
        for definition in ROLE_DEFINITIONS:
            with self.subTest(role=definition.role):
                if definition.may_approve_science:
                    self.assertIn(definition.role, SCIENTIFIC_APPROVAL_ROLES)

    def test_a_definition_claiming_otherwise_is_refused(self):
        with self.assertRaises(RoleSeparationError):
            RoleDefinition(
                role=CurationRole.ENGINEERING_OBSERVER,
                responsibility="Maintains tooling.",
                may_author_conclusion=False, may_review_conclusion=False,
                may_approve_science=True, may_adjudicate=False,
                notes="Should not be permitted.")

    def test_an_engineering_observer_cannot_be_an_independent_reviewer(self):
        with self.assertRaises(RoleSeparationError):
            rationale(reviewer=None).__class__(
                parts=rationale().parts,
                protocol_version="pgx-curation-protocol/1",
                authored_by=signature(AUTHOR),
                reviewed_by=signature(REVIEWER,
                                      CurationRole.ENGINEERING_OBSERVER,
                                      "Checked that the tooling ran."))

    def test_there_is_no_machine_curator_role(self):
        for member in CurationRole:
            with self.subTest(member=member):
                for forbidden in ("AI", "LLM", "MODEL", "AUTOMATED", "BOT"):
                    self.assertNotIn(forbidden, member.value)
        self.assertIn("no_machine_curator", CASE_ROLE_RULES)

    def test_a_placeholder_name_is_refused(self):
        for name in ("TEST_REVIEWER", "todo", "team", "scientific advisor",
                     "anonymous", "system", "Claude", "reviewer"):
            with self.subTest(name=name):
                with self.assertRaises(RoleSeparationError):
                    ReviewSignature(
                        person=name, role=CurationRole.SCIENTIFIC_CURATOR,
                        at=NOW,
                        rationale="Reviewed the evidence and the reasoning.")

    def test_a_real_name_is_accepted(self):
        item = ReviewSignature(
            person="Dr Ayse Yilmaz", role=CurationRole.SCIENTIFIC_CURATOR,
            at=NOW, rationale="Reviewed the evidence and the reasoning.")
        self.assertEqual(item.person, "Dr Ayse Yilmaz")

    def test_every_role_has_a_stated_responsibility(self):
        defined = {item.role for item in ROLE_DEFINITIONS}
        self.assertEqual(defined, set(CurationRole))


class TestAdjudicationPreservesResponses(unittest.TestCase):

    def _responses(self):
        return ({"curator_label": "A", "curator_name": "Dr Ayse Yilmaz",
                 "answers": {"CASE-01": {"conclusion_state": "SUPPORTED"}}},
                {"curator_label": "B", "curator_name": "Dr Mehmet Kaya",
                 "answers": {"CASE-01": {"conclusion_state": "INSUFFICIENT"}}})

    def test_both_responses_are_kept(self):
        template = AdjudicationTemplate(
            exercise_id="x", disputed_case_ids=("CASE-01",),
            preserved_responses=self._responses(),
            adjudicator_name="Dr Zeynep Demir",
            decision="The reviewed answer for CASE-01 is INSUFFICIENT.",
            rationale="Neither reading is superseded and the cited evidence "
                      "does not settle the scope.")
        payload = template.to_json()
        self.assertEqual(len(payload["preserved_responses"]), 2)
        names = {item["curator_name"] for item in payload["preserved_responses"]}
        self.assertEqual(names, {"Dr Ayse Yilmaz", "Dr Mehmet Kaya"})

    def test_fewer_than_two_preserved_responses_is_refused(self):
        with self.assertRaises(Exception):
            AdjudicationTemplate(exercise_id="x", disputed_case_ids=(),
                                 preserved_responses=(self._responses()[0],))

    def test_a_decision_requires_a_named_adjudicator(self):
        with self.assertRaises(RoleSeparationError):
            AdjudicationTemplate(
                exercise_id="x", disputed_case_ids=("CASE-01",),
                preserved_responses=self._responses(),
                decision="INSUFFICIENT")

    def test_an_undecided_template_is_not_decided(self):
        template = AdjudicationTemplate(
            exercise_id="x", disputed_case_ids=(),
            preserved_responses=self._responses())
        self.assertFalse(template.is_decided)


class TestCaseSeparation(unittest.TestCase):
    """SAFETY-INV-009."""

    def test_a_case_holding_two_roles_is_reported(self):
        problems = check_case_separation((
            CaseAssignment("CASE-01", CaseRole.DEVELOPMENT, "legacy seed"),
            CaseAssignment("CASE-01", CaseRole.EXPERT_HOLDOUT, "expert set")))
        self.assertTrue(problems)
        self.assertIn("CASE-01", problems[0])

    def test_distinct_cases_in_different_roles_are_fine(self):
        self.assertEqual(check_case_separation((
            CaseAssignment("CASE-01", CaseRole.DEVELOPMENT, "legacy seed"),
            CaseAssignment("CASE-02", CaseRole.EXPERT_HOLDOUT, "expert set"))),
            ())

    def test_the_same_case_repeated_in_one_role_is_fine(self):
        self.assertEqual(check_case_separation((
            CaseAssignment("CASE-01", CaseRole.DEVELOPMENT, "a"),
            CaseAssignment("CASE-01", CaseRole.DEVELOPMENT, "b"))), ())

    def test_a_case_without_an_origin_is_refused(self):
        with self.assertRaises(CaseSeparationError):
            CaseAssignment("CASE-01", CaseRole.DEVELOPMENT, "")

    def test_the_rules_state_the_four_separations_that_matter(self):
        for key in ("one_role_per_case", "development_and_holdout_disjoint",
                    "legacy_and_demo_are_development",
                    "derived_cases_are_not_external",
                    "no_expected_answers_in_blind_packets",
                    "no_machine_curator"):
            self.assertIn(key, CASE_ROLE_RULES)

    def test_legacy_and_demo_cases_are_development_or_training(self):
        rule = CASE_ROLE_RULES["legacy_and_demo_are_development"].upper()
        self.assertIn("DEVELOPMENT", rule)
        self.assertIn("TRAINING", rule)
        self.assertNotIn("HOLDOUT", rule.split("ONLY")[0])

    def test_cases_from_the_current_evidence_set_are_not_external(self):
        self.assertIn("not independent",
                      CASE_ROLE_RULES["derived_cases_are_not_external"])
