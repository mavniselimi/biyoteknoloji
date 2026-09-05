# -*- coding: utf-8 -*-
"""Who may act, and the four ways they may not.

The refusals here are graded by what they disclose. A wrong role gets a
specific code, because the caller already knows they are not a reviewer. A
wrong or absent assignment gets one code for three conditions, because
distinguishing them would hand anyone with reviewer credentials a way to
enumerate the holdout set.
"""

from __future__ import annotations

import unittest

from pgx.expert_review.errors import ExpertReviewError
from pgx.expert_review.models import ReviewAssignment
from pgx.expert_review.vocabulary import ReviewState
from tests.fixtures.wp22 import blind_review as F


def _code(callable_, **kwargs):
    try:
        callable_(**kwargs)
    except ExpertReviewError as error:
        return error.code
    return None


class TestOnlyTheExactRoleMayAct(unittest.TestCase):

    def setUp(self):
        self.service = F.service()

    def test_admin_does_not_implicitly_become_a_reviewer(self):
        """A hierarchy is convenient right until an administrator's action is
        indistinguishable from an independent expert's."""
        for operation, body in ((self.service.record_expectation,
                                 F.EXPECTED_BODY),
                                (self.service.reveal, {}),
                                (self.service.complete,
                                 {"decision": "AGREE"})):
            with self.subTest(operation=operation.__name__):
                self.assertEqual(
                    _code(operation, case_id=F.CASE_ID, actor=F.ADMIN_ACTOR,
                          role="ADMIN", body=body),
                    "EXPERT_REVIEW_ROLE_REQUIRED")

    def test_demo_user_is_forbidden(self):
        self.assertEqual(
            _code(self.service.record_expectation, case_id=F.CASE_ID,
                  actor="TEST-ONLY-demo-1", role="DEMO_USER",
                  body=F.EXPECTED_BODY),
            "EXPERT_REVIEW_ROLE_REQUIRED")

    def test_the_role_check_runs_before_any_store_lookup(self):
        """Otherwise the refusal timing would differ by case existence."""
        store = F.InMemoryReviewStore((F.assignment(),))
        looked_up = []

        original = store.assignment_for

        def _watch(**kwargs):
            looked_up.append(kwargs)
            return original(**kwargs)

        store.assignment_for = _watch  # type: ignore[assignment]
        service = F.service(store=store)
        _code(service.record_expectation, case_id=F.CASE_ID,
              actor=F.ADMIN_ACTOR, role="ADMIN", body=F.EXPECTED_BODY)
        self.assertEqual(looked_up, [])

    def test_an_assignment_cannot_carry_a_non_reviewer_role(self):
        with self.assertRaises(ExpertReviewError) as caught:
            F.assignment()  # valid
            ReviewAssignment(
                assignment_id="A-1", review_id="R-1", case_id=F.CASE_ID,
                case_role="EXPERT_HOLDOUT", reviewer_actor="x",
                reviewer_role="ADMIN",
                protocol_version="v", protocol_hash=F.CASE_MANIFEST_HASH,
                release_public_id=F.RELEASE_PUBLIC_ID,
                release_manifest_hash=F.RELEASE_MANIFEST_HASH,
                software_version=F.SOFTWARE_VERSION,
                software_hash=F.SOFTWARE_HASH,
                dataset_public_id=F.DATASET_PUBLIC_ID,
                dataset_content_hash=F.DATASET_HASH,
                ruleset_public_id=F.RULESET_PUBLIC_ID,
                ruleset_content_hash=F.RULESET_HASH,
                case_manifest_hash=F.CASE_MANIFEST_HASH, assigned_at=F.NOW)
        self.assertEqual(caught.exception.code, "EXPERT_REVIEW_ROLE_REQUIRED")


class TestOnlyTheAssignedReviewerMayAct(unittest.TestCase):

    def setUp(self):
        self.service = F.service()

    def test_another_reviewer_is_refused(self):
        self.assertEqual(
            _code(self.service.record_expectation, case_id=F.CASE_ID,
                  actor=F.OTHER_REVIEWER, role="EXPERT_REVIEWER",
                  body=F.EXPECTED_BODY),
            "EXPERT_REVIEW_NOT_ASSIGNED")

    def test_an_unknown_case_gives_the_identical_refusal(self):
        """The point of the shared code: these two must be indistinguishable,
        or a reviewer can probe for which holdout cases exist."""
        unknown = _code(self.service.record_expectation,
                        case_id="PGX-VAL-TEST-ONLY-EH-9999", actor=F.REVIEWER,
                        role="EXPERT_REVIEWER", body=F.EXPECTED_BODY)
        other = _code(self.service.record_expectation, case_id=F.CASE_ID,
                      actor=F.OTHER_REVIEWER, role="EXPERT_REVIEWER",
                      body=F.EXPECTED_BODY)
        self.assertEqual(unknown, other)
        self.assertEqual(unknown, "EXPERT_REVIEW_NOT_ASSIGNED")

    def test_the_refusal_details_disclose_nothing(self):
        try:
            self.service.reveal(case_id="PGX-VAL-TEST-ONLY-EH-9999",
                                actor=F.REVIEWER, role="EXPERT_REVIEWER")
        except ExpertReviewError as error:
            self.assertEqual(error.details, {})
            self.assertNotIn("EH-9999", str(error))

    def test_a_reviewer_sees_only_their_own_assignments(self):
        store = F.InMemoryReviewStore((
            F.assignment(),
            F.assignment(case_id="PGX-VAL-TEST-ONLY-EH-0002",
                         reviewer=F.OTHER_REVIEWER),
        ))
        mine = store.assignments_for_actor(F.REVIEWER)
        self.assertEqual([item.case_id for item in mine], [F.CASE_ID])


class TestOnlyExpertHoldoutIsAssignable(unittest.TestCase):

    def test_a_development_case_cannot_be_assigned(self):
        with self.assertRaises(ExpertReviewError) as caught:
            F.assignment(case_role="DEVELOPMENT")
        self.assertEqual(caught.exception.code,
                         "EXPERT_REVIEW_CASE_NOT_ELIGIBLE")

    def test_an_internal_holdout_case_cannot_be_assigned(self):
        """A different partition with a different protocol. Treating one as
        the other would spend an internal holdout on a blind review it was
        never withheld for."""
        with self.assertRaises(ExpertReviewError) as caught:
            F.assignment(case_role="INTERNAL_HOLDOUT")
        self.assertEqual(caught.exception.code,
                         "EXPERT_REVIEW_CASE_NOT_ELIGIBLE")


class TestTheRequestCannotForgeIdentityOrPins(unittest.TestCase):

    def setUp(self):
        self.service = F.service()

    def test_a_body_supplying_an_actor_is_refused(self):
        body = dict(F.EXPECTED_BODY, actor="TEST-ONLY-somebody-else")
        self.assertEqual(
            _code(self.service.record_expectation, case_id=F.CASE_ID,
                  actor=F.REVIEWER, role="EXPERT_REVIEWER", body=body),
            "EXPERT_REVIEW_FORGED_FIELD")

    def test_a_body_supplying_a_timestamp_is_refused(self):
        body = dict(F.EXPECTED_BODY, recorded_at="2020-01-01T00:00:00Z")
        self.assertEqual(
            _code(self.service.record_expectation, case_id=F.CASE_ID,
                  actor=F.REVIEWER, role="EXPERT_REVIEWER", body=body),
            "EXPERT_REVIEW_FORGED_FIELD")

    def test_a_body_supplying_a_hash_is_refused(self):
        for field in ("expectation_hash", "release_manifest_hash",
                      "case_manifest_hash", "protocol_hash", "chain_hash"):
            with self.subTest(field=field):
                body = dict(F.EXPECTED_BODY, **{field: F.CASE_MANIFEST_HASH})
                self.assertEqual(
                    _code(self.service.record_expectation, case_id=F.CASE_ID,
                          actor=F.REVIEWER, role="EXPERT_REVIEWER",
                          body=body),
                    "EXPERT_REVIEW_FORGED_FIELD")

    def test_a_body_supplying_a_status_is_refused(self):
        body = dict(F.EXPECTED_BODY, state="COMPLETED")
        self.assertEqual(
            _code(self.service.record_expectation, case_id=F.CASE_ID,
                  actor=F.REVIEWER, role="EXPERT_REVIEWER", body=body),
            "EXPERT_REVIEW_FORGED_FIELD")

    def test_forged_fields_are_refused_rather_than_stripped(self):
        """Silently ignoring one loses the fact that somebody tried."""
        try:
            self.service.record_expectation(
                case_id=F.CASE_ID, actor=F.REVIEWER, role="EXPERT_REVIEWER",
                body=dict(F.EXPECTED_BODY, role="ADMIN"))
        except ExpertReviewError as error:
            self.assertIn("role", error.details["fields"])
        self.assertEqual(
            self.service._store.expectations(F.review_id_for()), ())

    def test_the_recorded_identity_comes_from_the_principal(self):
        expectation = self.service.record_expectation(
            case_id=F.CASE_ID, actor=F.REVIEWER, role="EXPERT_REVIEWER",
            body=F.EXPECTED_BODY)
        chain = self.service._store.audit_chain(F.review_id_for())
        self.assertEqual(chain[-1].actor, F.REVIEWER)
        self.assertEqual(chain[-1].actor_role, "EXPERT_REVIEWER")
        self.assertFalse(chain[-1].actor_authenticated)


class TestAnExpectationCarriesNoClinicalDirective(unittest.TestCase):

    def setUp(self):
        self.service = F.service()

    def test_a_note_naming_a_dose_is_refused(self):
        for note in ("reduce the dose to 25 mg daily",
                     "recommendation: switch therapy",
                     "preferred medication is the alternative"):
            with self.subTest(note=note):
                body = dict(F.EXPECTED_BODY, reviewer_note=note)
                self.assertEqual(
                    _code(self.service.record_expectation, case_id=F.CASE_ID,
                          actor=F.REVIEWER, role="EXPERT_REVIEWER",
                          body=body),
                    "EXPERT_REVIEW_FORGED_FIELD")

    def test_an_ordinary_note_about_the_axis_is_accepted(self):
        expectation = self.service.record_expectation(
            case_id=F.CASE_ID, actor=F.REVIEWER, role="EXPERT_REVIEWER",
            body=dict(F.EXPECTED_BODY,
                      reviewer_note="the CYP2C19 axis is determinative"))
        self.assertIn("determinative", expectation.reviewer_note)

    def test_rationale_codes_are_controlled(self):
        body = dict(F.EXPECTED_BODY, rationale_codes=("BECAUSE_I_SAID_SO",))
        self.assertEqual(
            _code(self.service.record_expectation, case_id=F.CASE_ID,
                  actor=F.REVIEWER, role="EXPERT_REVIEWER", body=body),
            "EXPERT_REVIEW_INVALID_TRANSITION")


class TestAnUnapprovedProtocolStopsEverything(unittest.TestCase):

    def setUp(self):
        self.service = F.service(protocol=F.unapproved_protocol())

    def test_every_operation_refuses(self):
        for operation, body in ((self.service.view, None),
                                (self.service.record_expectation,
                                 F.EXPECTED_BODY),
                                (self.service.reveal, {}),
                                (self.service.complete,
                                 {"decision": "AGREE"})):
            with self.subTest(operation=operation.__name__):
                kwargs = {"case_id": F.CASE_ID, "actor": F.REVIEWER,
                          "role": "EXPERT_REVIEWER"}
                if body is not None:
                    kwargs["body"] = body
                self.assertEqual(_code(operation, **kwargs),
                                 "EXPERT_REVIEW_PROTOCOL_NOT_APPROVED")

    def test_nothing_was_written(self):
        _code(self.service.record_expectation, case_id=F.CASE_ID,
              actor=F.REVIEWER, role="EXPERT_REVIEWER", body=F.EXPECTED_BODY)
        self.assertEqual(
            self.service._store.audit_chain(F.review_id_for()), ())

    def test_the_check_runs_before_the_role_check(self):
        """An unapproved protocol refuses everyone, including a valid
        reviewer, so the protocol code is the one a client should see."""
        self.assertEqual(
            _code(self.service.record_expectation, case_id=F.CASE_ID,
                  actor=F.ADMIN_ACTOR, role="ADMIN", body=F.EXPECTED_BODY),
            "EXPERT_REVIEW_PROTOCOL_NOT_APPROVED")


class TestAnUnavailableServiceRefusesFirst(unittest.TestCase):

    def test_no_store_means_no_operation(self):
        from pgx.expert_review.service import ExpertReviewService
        service = ExpertReviewService(protocol=F.approved_protocol())
        self.assertFalse(service.available)
        self.assertEqual(
            _code(service.record_expectation, case_id=F.CASE_ID,
                  actor=F.REVIEWER, role="EXPERT_REVIEWER",
                  body=F.EXPECTED_BODY),
            "EXPERT_REVIEW_NOT_AVAILABLE")

    def test_a_store_without_a_result_port_is_still_unavailable(self):
        """Otherwise a reviewer could lock an expectation that could never be
        revealed, stranding them mid-protocol."""
        from pgx.expert_review.service import ExpertReviewService
        service = ExpertReviewService(
            protocol=F.approved_protocol(),
            store=F.InMemoryReviewStore((F.assignment(),)))
        self.assertFalse(service.available)
        self.assertEqual(service.gate_state()["refusal_code"],
                         "EXPERT_REVIEW_NOT_AVAILABLE")
