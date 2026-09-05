# -*- coding: utf-8 -*-
"""The canonical governed audit trail (WP-23).

Four tamper shapes have to be detectable, and they are different problems:
editing a field, deleting an event, inserting one, and reordering two. A
timestamp catches none of them. A hash chain catches all four, and this file
demonstrates each separately rather than asserting "the chain works".

The other half of the file is about what an audit event may not contain. That
check walks nested structures, because the first version of any such check
looks at top-level keys and the first thing to defeat it is one level of
nesting.
"""

from __future__ import annotations

import datetime as _dt
import dataclasses
import unittest

from pgx.infrastructure.audit.models import (AUDIT_STREAM_ID,
                                             GovernedAuditEvent,
                                             ProhibitedAuditFieldError,
                                             canonical_bytes, next_event,
                                             verify_chain)
from pgx.infrastructure.audit.ports import InMemoryAuditStore
from pgx.infrastructure.audit.service import (AuditContext,
                                              GovernedAuditService)
from pgx.infrastructure.audit.vocabulary import (AUDIT_ACTION_AREAS,
                                                 AUDIT_ACTIONS,
                                                 GOVERNED_ACTION_REGISTRY,
                                                 OBJECT_TYPES,
                                                 PROHIBITED_AUDIT_FIELDS,
                                                 TYPED_METADATA_KEYS,
                                                 AuditOutcome, GovernedAction)
from pgx.security.errors import AuditAppendError
from pgx.security.vocabulary import AuthAssurance, AuthMechanism

NOW = _dt.datetime(2026, 9, 5, 12, 0, tzinfo=_dt.timezone.utc)


def _event(previous=None, *, sequence_hint=None, **overrides):
    fields = dict(
        event_id="EVT-TEST-ONLY-0001",
        action=GovernedAction.RELEASE_ACTIVATED,
        outcome=AuditOutcome.SUCCESS, result_code="RELEASE_ACTIVATED",
        object_type="RELEASE_BUNDLE", object_id="rel-1", occurred_at=NOW,
        actor_id="test-admin", actor_role="ADMIN")
    fields.update(overrides)
    del sequence_hint
    return next_event(previous, **fields)


class TestTheEventCarriesEveryTraceField(unittest.TestCase):

    def test_every_required_field_is_present_in_the_serialized_event(self):
        document = _event().to_json()
        for field in ("event_id", "schema_version", "sequence",
                      "previous_hash", "event_hash", "actor_id", "actor_role",
                      "auth_mechanism", "auth_assurance",
                      "session_reference", "occurred_at", "request_id",
                      "action", "object_type", "object_id", "outcome",
                      "result_code", "input_hash", "output_hash",
                      "software_id", "software_hash", "dataset_id",
                      "dataset_hash", "ruleset_id", "ruleset_hash",
                      "release_id", "release_manifest_hash", "metadata"):
            with self.subTest(field=field):
                self.assertIn(field, document)

    def test_previous_and_new_state_are_expressible(self):
        event = _event(metadata={"previous_state": "DRAFT",
                                 "new_state": "ACTIVE"})
        self.assertEqual(event.metadata["new_state"], "ACTIVE")

    def test_a_release_event_can_pin_the_whole_bundle(self):
        digest = "sha256:" + "0" * 64
        event = _event(software_id="sw-1", software_hash=digest,
                       dataset_id="ds-1", dataset_hash=digest,
                       ruleset_id="rs-1", ruleset_hash=digest,
                       release_id="rel-1", release_manifest_hash=digest)
        for field in ("software_hash", "dataset_hash", "ruleset_hash",
                      "release_manifest_hash"):
            with self.subTest(field=field):
                self.assertEqual(getattr(event, field), digest)

    def test_a_malformed_digest_is_refused(self):
        with self.assertRaises(ValueError):
            _event(input_hash="not-a-digest")

    def test_an_unknown_object_type_is_refused(self):
        with self.assertRaises(ValueError):
            _event(object_type="ANYTHING")

    def test_the_object_type_vocabulary_covers_every_governed_area(self):
        for required in ("USER", "SESSION", "ASSESSMENT", "RELEASE_BUNDLE",
                         "COMPUTABLE_RULE", "RULESET_VERSION",
                         "EXPERT_REVIEW"):
            with self.subTest(object_type=required):
                self.assertIn(required, OBJECT_TYPES)


class TestAssuranceCannotBeForged(unittest.TestCase):

    def test_only_a_session_may_claim_session_assurance(self):
        """A fixture token proves a test ran, not that a person acted."""
        with self.assertRaises(ValueError):
            _event(auth_mechanism=AuthMechanism.STATIC_TOKEN,
                   auth_assurance=AuthAssurance.SESSION)
        with self.assertRaises(ValueError):
            _event(auth_mechanism=AuthMechanism.NONE,
                   auth_assurance=AuthAssurance.SESSION)

    def test_a_session_event_must_name_its_session(self):
        with self.assertRaises(ValueError):
            _event(auth_mechanism=AuthMechanism.SESSION,
                   auth_assurance=AuthAssurance.SESSION,
                   session_reference=None)

    def test_a_static_token_event_is_permitted_and_stays_distinguishable(self):
        event = _event(auth_mechanism=AuthMechanism.STATIC_TOKEN,
                       auth_assurance=AuthAssurance.TEST_STATIC_TOKEN)
        self.assertFalse(event.auth_assurance.is_production_capable)


class TestProhibitedContent(unittest.TestCase):

    def test_a_password_is_refused_at_the_top_level(self):
        with self.assertRaises(ValueError):
            _event(metadata={"password": "anything"})

    def test_a_password_is_refused_when_nested(self):
        """Depth matters. The first thing that defeats a top-level-only check
        is one level of nesting."""
        with self.assertRaises(ProhibitedAuditFieldError):
            _event(metadata={"previous_state": {"password": "anything"}})

    def test_prohibition_reaches_inside_a_list(self):
        with self.assertRaises(ProhibitedAuditFieldError):
            _event(metadata={"previous_state": [{"session_token": "x"}]})

    def test_the_prohibited_set_covers_every_named_category(self):
        for field in ("password", "password_hash", "session_token",
                      "csrf_token", "cookie", "authorization", "phenotype",
                      "medications", "holdout_payload", "expected_response",
                      "request_body", "file_path", "dsn"):
            with self.subTest(field=field):
                self.assertIn(field, PROHIBITED_AUDIT_FIELDS)

    def test_metadata_is_a_closed_vocabulary(self):
        """An open bucket eventually receives a request body, because the
        place that builds an audit event is the place that has one."""
        with self.assertRaises(ValueError):
            _event(metadata={"anything_at_all": 1})
        for key in TYPED_METADATA_KEYS[:3]:
            with self.subTest(key=key):
                _event(metadata={key: "value"})

    def test_the_error_does_not_quote_the_refused_value(self):
        try:
            _event(metadata={"previous_state": {"password": "hunter2-secret"}})
        except ProhibitedAuditFieldError as error:
            self.assertNotIn("hunter2-secret", str(error))
        else:  # pragma: no cover
            self.fail("the prohibited field was accepted")


class TestTheChainDetectsEveryTamperShape(unittest.TestCase):

    def setUp(self):
        self.events = []
        previous = None
        for index in range(1, 6):
            previous = _event(previous, event_id="EVT-TEST-ONLY-%04d" % index,
                              object_id="rel-%d" % index)
            self.events.append(previous)

    def test_an_untampered_chain_verifies(self):
        intact, position, reason = verify_chain(tuple(self.events))
        self.assertTrue(intact, reason)
        self.assertIsNone(position)

    def test_an_edited_field_breaks_the_successor_link(self):
        edited = dataclasses.replace(self.events[2], result_code="EDITED")
        tampered = tuple(self.events[:2]) + (edited,) + tuple(self.events[3:])
        intact, position, reason = verify_chain(tampered)
        self.assertFalse(intact)
        self.assertEqual(position, 4)
        self.assertIn("predecessor hash", reason)

    def test_a_deleted_event_breaks_the_sequence(self):
        tampered = tuple(self.events[:2]) + tuple(self.events[3:])
        intact, position, _reason = verify_chain(tampered)
        self.assertFalse(intact)
        self.assertEqual(position, 4)

    def test_an_inserted_event_breaks_the_sequence(self):
        extra = _event(self.events[1], event_id="EVT-TEST-ONLY-9999",
                       object_id="rel-x")
        tampered = tuple(self.events[:2]) + (extra,) + tuple(self.events[2:])
        intact, _position, _reason = verify_chain(tampered)
        self.assertFalse(intact)

    def test_reordering_breaks_it(self):
        tampered = (self.events[0], self.events[2], self.events[1],
                    self.events[3], self.events[4])
        intact, _position, _reason = verify_chain(tampered)
        self.assertFalse(intact)

    def test_the_verification_reason_never_quotes_an_event(self):
        """Otherwise a command that checks integrity becomes a way to read
        audit content."""
        edited = dataclasses.replace(self.events[2],
                                     object_id="secret-object-name")
        tampered = tuple(self.events[:2]) + (edited,) + tuple(self.events[3:])
        _intact, _position, reason = verify_chain(tampered)
        self.assertNotIn("secret-object-name", reason)

    def test_serialization_is_order_independent(self):
        """A chain whose hashes depended on insertion order would verify on
        the machine that wrote it and nowhere else."""
        forward = {"b": 1, "a": 2, "c": {"z": 1, "y": 2}}
        backward = {"c": {"y": 2, "z": 1}, "a": 2, "b": 1}
        self.assertEqual(canonical_bytes(forward), canonical_bytes(backward))


class TestTheStoreCannotMutate(unittest.TestCase):

    def test_the_repository_exposes_no_update_or_delete(self):
        store = InMemoryAuditStore()
        for name in ("update", "delete", "remove", "truncate", "rewrite",
                     "purge", "edit", "replace"):
            with self.subTest(method=name):
                self.assertFalse(hasattr(store, name))

    def test_the_port_classes_declare_no_mutation(self):
        from pgx.infrastructure.audit import ports

        for class_name in ("AuditSink", "AuditReader"):
            klass = getattr(ports, class_name)
            for name in ("update", "delete", "remove", "truncate"):
                with self.subTest(cls=class_name, method=name):
                    self.assertFalse(hasattr(klass, name))

    def test_a_concurrent_append_cannot_fork_the_chain(self):
        """Two callers who both read the same tail: the second is refused
        rather than producing a second event at the same sequence."""
        store = InMemoryAuditStore()
        first = _event(store.head(), event_id="EVT-TEST-ONLY-0001")
        store.append(first)
        tail = store.head()
        racer_a = _event(tail, event_id="EVT-TEST-ONLY-0002")
        racer_b = _event(tail, event_id="EVT-TEST-ONLY-0003")
        store.append(racer_a)
        with self.assertRaises(RuntimeError):
            store.append(racer_b)
        intact, _position, reason = verify_chain(store.all_events())
        self.assertTrue(intact, reason)


class TestTheServiceIsAtomicAndFailsCorrectly(unittest.TestCase):

    def setUp(self):
        self.store = InMemoryAuditStore()
        self.counter = [0]
        self.service = GovernedAuditService(
            self.store, clock=lambda: NOW, id_factory=self._ids)

    def _ids(self):
        self.counter[0] += 1
        return "EVT-TEST-ONLY-%04d" % self.counter[0]

    def test_a_successful_append_extends_the_chain(self):
        self.service.record(
            GovernedAction.RELEASE_ACTIVATED, outcome=AuditOutcome.SUCCESS,
            result_code="OK", object_type="RELEASE_BUNDLE",
            object_id="rel-1",
            context=AuditContext(actor_id="test-admin", actor_role="ADMIN"))
        self.assertEqual(len(self.store), 1)
        self.assertEqual(self.store.head().stream_id, AUDIT_STREAM_ID)

    def test_an_append_failure_raises_so_the_caller_rolls_back(self):
        self.store.fail_next_append = True
        with self.assertRaises(AuditAppendError) as raised:
            self.service.record(
                GovernedAction.RELEASE_ACTIVATED,
                outcome=AuditOutcome.SUCCESS, result_code="OK",
                object_type="RELEASE_BUNDLE", object_id="rel-1")
        self.assertEqual(raised.exception.code, "AUDIT_APPEND_FAILED")
        self.assertEqual(len(self.store), 0)

    def test_no_sink_at_all_raises(self):
        with self.assertRaises(AuditAppendError):
            GovernedAuditService(None).record(
                GovernedAction.LOGOUT, outcome=AuditOutcome.SUCCESS,
                result_code="OK", object_type="SESSION", object_id="s-1")

    def test_a_refusal_record_never_raises(self):
        """An audit outage must not convert a controlled refusal into a 500,
        which is a different answer from a refusal."""
        self.store.fail_next_append = True
        self.assertFalse(self.service.record_refusal(
            GovernedAction.LOGIN_FAILED, result_code="AUTHENTICATION_FAILED",
            object_type="USER", object_id="unknown"))
        self.assertFalse(GovernedAuditService(None).record_refusal(
            GovernedAction.LOGIN_FAILED, result_code="X",
            object_type="USER", object_id="unknown"))

    def test_a_refusal_record_reports_whether_it_was_written(self):
        self.assertTrue(self.service.record_refusal(
            GovernedAction.ASSESSMENT_REFUSED, result_code="REFUSED",
            object_type="ASSESSMENT", object_id="a-1"))


class TestTheGovernedActionRegistry(unittest.TestCase):
    """A governed action with no audit mapping must fail a test, not pass."""

    def test_every_action_is_registered(self):
        self.assertEqual(set(AUDIT_ACTIONS), set(GOVERNED_ACTION_REGISTRY))

    def test_every_registered_action_belongs_to_exactly_one_area(self):
        seen = {}
        for area, names in AUDIT_ACTION_AREAS.items():
            for name in names:
                with self.subTest(action=name):
                    self.assertNotIn(name, seen)
                    seen[name] = area
        self.assertEqual(set(seen), set(AUDIT_ACTIONS))

    def test_the_required_coverage_areas_are_all_present(self):
        for area, required in (
                ("authentication", ("USER_BOOTSTRAPPED", "LOGIN_SUCCEEDED",
                                    "LOGIN_FAILED", "USER_LOCKED",
                                    "SESSION_CREATED", "SESSION_EXPIRED",
                                    "LOGOUT", "USER_PASSWORD_CHANGED",
                                    "USER_ROLE_CHANGED", "USER_DISABLED")),
                ("assessment", ("ASSESSMENT_REQUESTED",
                                "ASSESSMENT_COMPLETED",
                                "ASSESSMENT_REFUSED")),
                ("release", ("RELEASE_REGISTERED", "RELEASE_ACTIVATED",
                             "RELEASE_ROLLED_BACK", "RELEASE_RETIRED")),
                ("curation_and_rules",
                 ("CURATION_REVISION_CREATED", "CURATION_REVISION_SUBMITTED",
                  "CURATION_REVIEWED", "CURATION_APPROVED",
                  "CURATION_REJECTED", "CURATION_ADJUDICATED",
                  "RULE_VALIDATED", "RULE_DEPRECATED", "RULESET_VALIDATED",
                  "RULESET_FROZEN", "RULESET_REOPENED", "RULESET_RETIRED")),
                ("expert_review",
                 ("REVIEW_ASSIGNED", "REVIEW_EXPECTATION_RECORDED",
                  "REVIEW_RESULT_REVEALED", "REVIEW_COMPLETED",
                  "REVIEW_CORRECTION_APPENDED", "REVIEW_INVALIDATED"))):
            for action in required:
                with self.subTest(area=area, action=action):
                    self.assertIn(action, AUDIT_ACTION_AREAS[area])

    def test_every_state_changing_action_requires_an_atomic_append(self):
        exempt = {"LOGIN_FAILED", "SESSION_EXPIRED", "AUDIT_CHAIN_VERIFIED",
                  "ASSESSMENT_REFUSED", "RELEASE_REFUSED"}
        for action, entry in GOVERNED_ACTION_REGISTRY.items():
            with self.subTest(action=action):
                self.assertEqual(entry["requires_atomic_audit"],
                                 action not in exempt)


class TestSafeProjections(unittest.TestCase):

    def test_the_recent_projection_omits_input_and_output_hashes(self):
        """A reader with a candidate input could otherwise confirm a match."""
        digest = "sha256:" + "1" * 64
        projection = _event(input_hash=digest,
                            output_hash=digest).safe_projection()
        self.assertNotIn("input_hash", projection)
        self.assertNotIn("output_hash", projection)
        self.assertNotIn(digest, str(projection))

    def test_the_repr_is_fixed_and_small(self):
        rendered = repr(_event(metadata={"target_user_id": "u-1"}))
        self.assertNotIn("u-1", rendered)
        self.assertIn("GovernedAuditEvent", rendered)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
