# -*- coding: utf-8 -*-
"""Visibility, refusals, and the who-has-seen ledger (WP-18).

Three properties, and the third is the one that is easy to get wrong.

*Holdout payloads are hidden from author workflows.* Straightforward, and
tested first.

*Every attempt is recorded, allowed or refused.* A log of successes answers
"who read this" and not "who tried", and the second is the question an
investigation asks.

*A refusal teaches nothing.* This is the subtle one. If a denied read
distinguished "denied, and there is an answer here" from "denied, and there is
not", then being refused would be an oracle for the existence of holdout
answers, and anyone with metadata access could watch that oracle move.
"""

from __future__ import annotations

import datetime as _dt
import unittest

from pgx.validation.access import (ACCESS_EVENT_VERSION, AccessContext,
                                   AccessLedger, DENY_REASONS, decide_access)
from pgx.validation.errors import AccessDeniedError, VisibilityError
from pgx.validation.vocabulary import (AUTHOR_CONTEXTS, AccessAction,
                                       AccessContextKind, ValidationCaseRole)
from tests.fixtures.wp18.synthetic import (development_case,
                                           expert_holdout_case,
                                           internal_holdout_case)


def _clock():
    moment = {"t": _dt.datetime(2026, 3, 1, tzinfo=_dt.timezone.utc)}

    def tick():
        moment["t"] += _dt.timedelta(seconds=1)
        return moment["t"]
    return tick


AUTHOR = AccessContext("TEST-rule-author", AccessContextKind.RULE_AUTHORING)
CURATOR = AccessContext("TEST-curator", AccessContextKind.DATASET_CURATION)
RUNNER = AccessContext("TEST-runner", AccessContextKind.VALIDATION_RUN)
EXPERT = AccessContext("TEST-expert", AccessContextKind.EXPERT_REVIEW)


class TestTheContextIsAClaimNotAnIdentity(unittest.TestCase):

    def test_every_event_records_that_the_actor_is_unverified(self):
        self.assertIs(AUTHOR.to_json()["actor_authenticated"], False)

    def test_an_anonymous_context_is_refused(self):
        """An audit trail with no name is not an audit trail."""
        for actor in ("", "   ", "x"):
            with self.subTest(actor=actor):
                with self.assertRaises(VisibilityError):
                    AccessContext(actor, AccessContextKind.AUDIT)

    def test_a_context_kind_must_be_from_the_vocabulary(self):
        with self.assertRaises(VisibilityError):
            AccessContext("TEST-somebody", "RULE_AUTHORING")

    def test_no_code_path_sets_authenticated_true(self):
        """WP-23 owns identity; recording a claim as verified would be a lie."""
        import inspect

        from pgx.validation import access

        source = inspect.getsource(access)
        self.assertNotIn('"actor_authenticated": True', source)
        self.assertIn('"actor_authenticated": False', source)


class TestHoldoutIsHiddenFromAuthors(unittest.TestCase):

    def test_an_author_may_not_read_an_internal_holdout_payload(self):
        decision = decide_access(internal_holdout_case(), AUTHOR,
                                 AccessAction.READ_PAYLOAD)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code,
                         "AUTHOR_CONTEXT_MAY_NOT_READ_HOLDOUT")

    def test_an_author_may_not_read_an_expert_holdout_payload(self):
        decision = decide_access(expert_holdout_case(), AUTHOR,
                                 AccessAction.READ_PAYLOAD)
        self.assertFalse(decision.allowed)

    def test_nobody_reads_an_expert_holdout_payload_yet(self):
        """Not even an expert. WP-22 owns the workflow that releases one."""
        for context in (AUTHOR, CURATOR, RUNNER, EXPERT):
            with self.subTest(context=context.kind.value):
                decision = decide_access(expert_holdout_case(), context,
                                         AccessAction.READ_PAYLOAD)
                self.assertFalse(decision.allowed)
                self.assertEqual(
                    decision.reason_code,
                    "EXPERT_HOLDOUT_REQUIRES_PERMITTED_WORKFLOW")

    def test_a_development_payload_is_author_visible(self):
        self.assertTrue(decide_access(development_case(), AUTHOR,
                                      AccessAction.READ_PAYLOAD).allowed)

    def test_a_validation_run_may_read_an_internal_holdout(self):
        """The one context internal holdout exists for."""
        self.assertTrue(decide_access(internal_holdout_case(), RUNNER,
                                      AccessAction.READ_PAYLOAD).allowed)

    def test_every_author_context_is_refused_not_just_one(self):
        for kind in AUTHOR_CONTEXTS:
            with self.subTest(kind=kind.value):
                context = AccessContext("TEST-somebody", kind)
                self.assertFalse(decide_access(internal_holdout_case(),
                                               context,
                                               AccessAction.READ_PAYLOAD
                                               ).allowed)

    def test_metadata_is_readable_by_everybody(self):
        """Hiding a case's existence would not hide anything.

        Its identity, role and provenance summary are what a manifest
        publishes anyway.
        """
        for context in (AUTHOR, CURATOR, RUNNER, EXPERT):
            for action in (AccessAction.READ_METADATA,
                           AccessAction.LIST_METADATA):
                with self.subTest(context=context.kind.value,
                                  action=action.value):
                    self.assertTrue(decide_access(expert_holdout_case(),
                                                  context, action).allowed)


class TestARefusalTeachesNothing(unittest.TestCase):

    def test_the_decision_does_not_depend_on_whether_a_payload_exists(self):
        """Two cases, one with a payload hash and one without, refuse alike."""
        with_payload = internal_holdout_case(
            "PGX-VAL-INT-WITH", payload_hash="sha256:" + "c" * 64)
        without = internal_holdout_case("PGX-VAL-INT-WITHOUT")
        left = decide_access(with_payload, AUTHOR, AccessAction.READ_PAYLOAD)
        right = decide_access(without, AUTHOR, AccessAction.READ_PAYLOAD)
        self.assertEqual((left.allowed, left.reason_code),
                         (right.allowed, right.reason_code))

    def test_the_error_carries_a_code_and_the_case_id_and_nothing_else(self):
        ledger = AccessLedger(clock=_clock())
        case = internal_holdout_case()
        with self.assertRaises(AccessDeniedError) as caught:
            ledger.read_payload(case, AUTHOR,
                                lambda: {"secret": "TEST-NEVER-SEEN"})
        self.assertNotIn("TEST-NEVER-SEEN", str(caught.exception))
        self.assertIn(case.case_id.value, str(caught.exception))
        self.assertIn(caught.exception.reason_code, DENY_REASONS)

    def test_the_loader_is_not_called_when_the_read_is_refused(self):
        """So a refusal cannot even be timed against restricted storage."""
        calls = []
        ledger = AccessLedger(clock=_clock())
        with self.assertRaises(AccessDeniedError):
            ledger.read_payload(internal_holdout_case(), AUTHOR,
                                lambda: calls.append(1))
        self.assertEqual(calls, [])

    def test_the_deny_reasons_are_coarse(self):
        """Four broad rules, not a per-case explanation."""
        self.assertLessEqual(len(DENY_REASONS), 6)


class TestTheLedgerIsAppendOnly(unittest.TestCase):

    def test_an_allowed_read_is_recorded(self):
        ledger = AccessLedger(clock=_clock())
        case = development_case()
        ledger.read_payload(case, AUTHOR, lambda: {"ok": True})
        events = ledger.events_for(case.case_id.value)
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].allowed)
        self.assertEqual(events[0].actor, AUTHOR.actor)

    def test_a_refused_read_is_recorded_too(self):
        ledger = AccessLedger(clock=_clock())
        case = internal_holdout_case()
        with self.assertRaises(AccessDeniedError):
            ledger.read_payload(case, AUTHOR, lambda: None)
        events = ledger.events_for(case.case_id.value)
        self.assertEqual(len(events), 1)
        self.assertFalse(events[0].allowed)

    def test_who_has_seen_lists_only_allowed_payload_reads(self):
        ledger = AccessLedger(clock=_clock())
        case = development_case()
        ledger.read_payload(case, AUTHOR, lambda: {})
        ledger.attempt(case, CURATOR, AccessAction.READ_METADATA)
        self.assertEqual(ledger.who_has_seen(case.case_id.value),
                         (AUTHOR.actor,))

    def test_the_ledger_exposes_no_way_to_remove_an_event(self):
        for name in ("delete", "remove", "pop", "clear", "update", "replace",
                     "__setitem__", "__delitem__"):
            with self.subTest(method=name):
                self.assertFalse(hasattr(AccessLedger, name))

    def test_the_returned_history_is_a_tuple(self):
        ledger = AccessLedger(clock=_clock())
        ledger.attempt(development_case(), AUTHOR, AccessAction.READ_METADATA)
        self.assertIsInstance(ledger.events(), tuple)

    def test_the_chain_is_intact_after_ordinary_use(self):
        ledger = AccessLedger(clock=_clock())
        case = development_case()
        for _ in range(4):
            ledger.attempt(case, CURATOR, AccessAction.READ_METADATA)
        self.assertEqual(ledger.verify_chain(), (True, None))

    def test_changing_an_old_event_breaks_the_chain_at_that_point(self):
        """The append-only proof.

        The events are frozen, so this test has to reach past the type to
        simulate tampering - which is the point: the only way to alter one is
        to do something no ordinary caller can, and the chain notices anyway.
        """
        ledger = AccessLedger(clock=_clock())
        case = development_case()
        for _ in range(3):
            ledger.attempt(case, CURATOR, AccessAction.READ_METADATA)
        tampered = ledger.events()[1]
        object.__setattr__(tampered, "actor", "TEST-someone-else")
        intact, index = ledger.verify_chain()
        self.assertFalse(intact)
        self.assertEqual(index, 1)

    def test_an_event_records_the_controlled_metadata(self):
        ledger = AccessLedger(clock=_clock())
        case = internal_holdout_case()
        ledger.attempt(case, RUNNER, AccessAction.READ_PAYLOAD)
        document = ledger.events()[0].to_json()
        for field in ("case_id", "case_role", "actor", "context_kind",
                      "action", "allowed", "reason_code", "occurred_at",
                      "manifest_hash", "actor_authenticated"):
            with self.subTest(field=field):
                self.assertIn(field, document)
        self.assertEqual(document["schema_version"], ACCESS_EVENT_VERSION)

    def test_an_event_carries_no_payload_content(self):
        ledger = AccessLedger(clock=_clock())
        case = internal_holdout_case()
        ledger.read_payload(case, RUNNER,
                            lambda: {"observations": ["TEST-SECRET"]})
        import json

        self.assertNotIn("TEST-SECRET", json.dumps(ledger.to_json()))


class TestListingIsNotAnOracle(unittest.TestCase):

    def test_the_ledger_offers_no_all_cases_call(self):
        """A count spanning both partitions would measure holdout size."""
        for name in ("all_cases", "list_all", "count_all", "cases"):
            with self.subTest(method=name):
                self.assertFalse(hasattr(AccessLedger, name))

    def test_history_is_scoped_by_case(self):
        ledger = AccessLedger(clock=_clock())
        ledger.attempt(development_case("PGX-VAL-DEV-SCOPE"), AUTHOR,
                       AccessAction.READ_METADATA)
        ledger.attempt(internal_holdout_case("PGX-VAL-INT-SCOPE"), RUNNER,
                       AccessAction.READ_METADATA)
        self.assertEqual(len(ledger.events_for("PGX-VAL-DEV-SCOPE")), 1)
        self.assertEqual(len(ledger.events_for("PGX-VAL-NOT-A-CASE")), 0)
