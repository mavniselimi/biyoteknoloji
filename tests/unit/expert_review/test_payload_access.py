# -*- coding: utf-8 -*-
"""The one widening of WP-18's boundary, and everything it does not widen.

WP-18 refuses every EXPERT_HOLDOUT payload read. WP-22 adds exactly one path:
an assignment-scoped permit. These tests exist to show that the path is as
narrow as claimed - in particular that holding a valid permit does not help a
rule author, a development context, or the reviewer next door.
"""

from __future__ import annotations

import unittest

from pgx.validation.access import AccessContext, decide_access
from pgx.validation.vocabulary import (AccessAction, AccessContextKind,
                                       ValidationCaseRole)
from tests.fixtures.wp18.synthetic import case
from tests.fixtures.wp22 import blind_review as F

_READ = AccessAction.READ_PAYLOAD


def _case(case_id: str = F.CASE_ID,
          role: ValidationCaseRole = ValidationCaseRole.EXPERT_HOLDOUT):
    return case(case_id, role)


def _permit(case_id: str = F.CASE_ID, actor: str = F.REVIEWER):
    service = F.service(store=F.InMemoryReviewStore(
        (F.assignment(case_id=case_id, reviewer=actor),)))
    return service.payload_permit(case_id=case_id, actor=actor,
                                  role="EXPERT_REVIEWER")


def _context(kind: AccessContextKind, actor: str = F.REVIEWER):
    return AccessContext(actor=actor, kind=kind)


class TestTheBoundaryHoldsWithoutAPermit(unittest.TestCase):
    """Every WP-18 refusal is unchanged when no permit is presented."""

    def test_an_expert_review_context_alone_is_still_refused(self):
        decision = decide_access(_case(),
                                 _context(AccessContextKind.EXPERT_REVIEW),
                                 _READ)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code,
                         "EXPERT_HOLDOUT_REQUIRES_PERMITTED_WORKFLOW")

    def test_a_rule_author_is_still_refused(self):
        self.assertFalse(decide_access(
            _case(), _context(AccessContextKind.RULE_AUTHORING),
            _READ).allowed)

    def test_a_development_context_is_still_refused(self):
        self.assertFalse(decide_access(
            _case(), _context(AccessContextKind.DEVELOPMENT_WORKFLOW),
            _READ).allowed)

    def test_metadata_reads_are_unaffected(self):
        for action in (AccessAction.LIST_METADATA, AccessAction.READ_METADATA,
                       AccessAction.AUDIT_PARTITION):
            with self.subTest(action=action.value):
                self.assertTrue(decide_access(
                    _case(), _context(AccessContextKind.RULE_AUTHORING),
                    action).allowed)


class TestAPermitOpensExactlyOneDoor(unittest.TestCase):

    def test_the_assigned_reviewer_with_a_matching_permit_may_read(self):
        decision = decide_access(_case(),
                                 _context(AccessContextKind.EXPERT_REVIEW),
                                 _READ, _permit())
        self.assertTrue(decision.allowed)

    def test_a_permit_does_not_help_a_rule_author(self):
        """The refusal there is about what the caller is doing, not what they
        hold. A rule author with a reviewer's permit is still a rule author."""
        self.assertFalse(decide_access(
            _case(), _context(AccessContextKind.RULE_AUTHORING),
            _READ, _permit()).allowed)

    def test_a_permit_does_not_help_a_development_context(self):
        self.assertFalse(decide_access(
            _case(), _context(AccessContextKind.DEVELOPMENT_WORKFLOW),
            _READ, _permit()).allowed)

    def test_a_permit_for_one_case_does_not_open_another(self):
        """The two cases a reviewer might later be asked to compare."""
        other = _case("PGX-VAL-TEST-ONLY-EH-0002")
        self.assertFalse(decide_access(
            other, _context(AccessContextKind.EXPERT_REVIEW),
            _READ, _permit()).allowed)

    def test_a_permit_belonging_to_another_reviewer_does_not_help(self):
        self.assertFalse(decide_access(
            _case(), _context(AccessContextKind.EXPERT_REVIEW,
                              F.OTHER_REVIEWER),
            _READ, _permit()).allowed)

    def test_a_permit_from_a_completed_review_cannot_be_obtained(self):
        from pgx.expert_review.errors import PermitError
        service = F.service()
        service.record_expectation(case_id=F.CASE_ID, actor=F.REVIEWER,
                                   role="EXPERT_REVIEWER",
                                   body=F.EXPECTED_BODY)
        service.reveal(case_id=F.CASE_ID, actor=F.REVIEWER,
                       role="EXPERT_REVIEWER")
        service.complete(case_id=F.CASE_ID, actor=F.REVIEWER,
                         role="EXPERT_REVIEWER", body={"decision": "AGREE"})
        with self.assertRaises(PermitError):
            service.payload_permit(case_id=F.CASE_ID, actor=F.REVIEWER,
                                   role="EXPERT_REVIEWER")


class TestRefusalDisclosesNothing(unittest.TestCase):
    """A refusal must not answer "is there a payload here?"."""

    def test_the_refusal_is_identical_with_and_without_a_payload(self):
        with_payload = _case()
        without = case(F.CASE_ID, ValidationCaseRole.EXPERT_HOLDOUT)
        first = decide_access(with_payload,
                              _context(AccessContextKind.RULE_AUTHORING),
                              _READ)
        second = decide_access(without,
                               _context(AccessContextKind.RULE_AUTHORING),
                               _READ)
        self.assertEqual(first.reason_code, second.reason_code)

    def test_the_reason_code_names_no_case(self):
        decision = decide_access(_case(),
                                 _context(AccessContextKind.EXPERT_REVIEW),
                                 _READ)
        self.assertNotIn("EH-0001", decision.reason_code)

    def test_the_policy_never_consults_whether_a_payload_exists(self):
        """Asserted against the source: a branch on payload presence would
        answer "is there an answer here?" for free."""
        import ast
        import inspect
        from pgx.validation import access
        tree = ast.parse(inspect.getsource(access.decide_access))
        names = {node.attr for node in ast.walk(tree)
                 if isinstance(node, ast.Attribute)}
        for forbidden in ("payload", "payload_hash", "payload_reference"):
            with self.subTest(attribute=forbidden):
                self.assertNotIn(forbidden, names)


class TestTheWideningIsNotAllExpertReviewers(unittest.TestCase):
    """The rule the brief names explicitly: do not widen to the role."""

    def test_the_policy_does_not_branch_on_the_role_alone(self):
        import ast
        import inspect
        from pgx.validation import access
        source = inspect.getsource(access._permit_authorises)
        tree = ast.parse(source)
        # Every path to True must pass through permit_allows, which binds
        # actor and case. A branch returning True on context kind alone would
        # be the widening this test forbids.
        returns_true = [node for node in ast.walk(tree)
                        if isinstance(node, ast.Return)
                        and isinstance(node.value, ast.Constant)
                        and node.value.value is True]
        self.assertEqual(returns_true, [])

    def test_an_expert_reviewer_with_no_assignment_is_refused(self):
        service = F.service(store=F.InMemoryReviewStore(()))
        from pgx.expert_review.errors import NotAssignedError
        with self.assertRaises(NotAssignedError):
            service.payload_permit(case_id=F.CASE_ID, actor=F.REVIEWER,
                                   role="EXPERT_REVIEWER")
