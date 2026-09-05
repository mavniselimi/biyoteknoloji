# -*- coding: utf-8 -*-
"""§12. Correlation identity, and the boundary it may not cross.

A request id has to reach the audit trail and must not reach any semantic
hash. Those are two assertions about the same value, and both are here so a
change to either is visible next to the other.

The acceptance contract for a caller-supplied ``X-Request-ID`` is also tested
here: canonical UUIDs are echoed, anything else is refused rather than
silently replaced, and an absent header produces a generated id.
"""

from __future__ import annotations

import unittest

from apps.api.adapters.request import adapt_assessment_request
from apps.api.errors import ApiError, status_for_code
from apps.api.request_id import (REQUEST_ID_HEADER, REQUEST_ID_LENGTH,
                                 generate_request_id, is_valid_request_id,
                                 resolve_request_id)
from pgx.application.execution_context import (EXECUTION_CONTEXT_VERSION,
                                               GOVERNED_ACTOR_ROLES,
                                               ExecutionChannel,
                                               ExecutionContext,
                                               audit_context_fields)
from tests.fixtures.wp13.synthetic import DRUG_1, GENE_1
from tests.fixtures.wp16.synthetic import (DEMO_PRINCIPAL, TEST_REQUEST_ID,
                                           create_request)
from tests.unit.api._support import synthetic_world


def _context(request_id: str = TEST_REQUEST_ID) -> ExecutionContext:
    return ExecutionContext(actor=DEMO_PRINCIPAL.actor,
                            role=DEMO_PRINCIPAL.role.value,
                            channel=ExecutionChannel.API,
                            request_id=request_id,
                            authenticated_by=DEMO_PRINCIPAL.authenticated_by)


class TestTheRequestIdContract(unittest.TestCase):

    def test_a_generated_id_is_canonical(self):
        for _ in range(20):
            value = generate_request_id()
            with self.subTest(value=value):
                self.assertTrue(is_valid_request_id(value))
                self.assertEqual(len(value), REQUEST_ID_LENGTH)

    def test_an_absent_header_produces_a_generated_id(self):
        self.assertTrue(is_valid_request_id(resolve_request_id(None)))

    def test_a_canonical_id_is_echoed_unchanged(self):
        self.assertEqual(resolve_request_id(TEST_REQUEST_ID), TEST_REQUEST_ID)

    def test_a_malformed_id_is_refused_rather_than_replaced(self):
        """Substituting one silently would leave the client's logs and the
        server's naming different ids for the same call."""
        for value in ("not-a-uuid", "", "x" * REQUEST_ID_LENGTH,
                      "11111111-1111-4111-8111-11111111111",
                      "ABCDEF01-1111-4111-8111-111111111111",
                      "{11111111-1111-4111-8111-111111111111}",
                      "11111111111141118111111111111111"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ApiError) as caught:
                    resolve_request_id(value)
                self.assertEqual(caught.exception.code, "REQUEST_ID_INVALID")
                self.assertEqual(status_for_code(caught.exception.code), 400)

    def test_the_rejected_value_is_not_echoed(self):
        with self.assertRaises(ApiError) as caught:
            resolve_request_id("<script>alert(1)</script>")
        self.assertNotIn("script", repr(caught.exception.details))

    def test_the_header_name_is_the_conventional_one(self):
        self.assertEqual(REQUEST_ID_HEADER, "X-Request-ID")


class TestTheExecutionContext(unittest.TestCase):

    def test_it_is_versioned(self):
        self.assertEqual(EXECUTION_CONTEXT_VERSION, "pgx-execution-context/1")

    def test_it_records_only_the_circumstances(self):
        """The set is closed, and WP-23 added two members to it.

        ``assurance`` and ``session_reference`` joined at WP-23 because an
        audit row that says who acted without saying *on what basis the server
        believed it* cannot distinguish a person from a development fixture.
        The list is still enumerated rather than loosened: the property this
        test defends is that the context has no free-form slot, and a context
        that could carry arbitrary keys would eventually carry a medication
        list, because the place that builds it is the place that has one.
        """
        fields = _context().audit_metadata()
        self.assertEqual(sorted(fields),
                         ["actor", "assurance", "authenticated_by", "channel",
                          "execution_context_version", "request_id", "role"])

    def test_a_session_reference_appears_only_when_there_is_a_session(self):
        """Absent rather than null, so a row never claims a session it had
        no way to name."""
        self.assertNotIn("session_reference", _context().audit_metadata())
        with_session = ExecutionContext(
            actor="TEST-actor", role="ADMIN", channel=ExecutionChannel.API,
            assurance="SESSION", session_reference="SES-TEST-ONLY-1")
        self.assertEqual(
            with_session.audit_metadata()["session_reference"],
            "SES-TEST-ONLY-1")

    def test_the_default_assurance_claims_nothing(self):
        """A context built without an authenticated session says NONE, not
        SESSION. The CLI and WP-14's existing callers land here."""
        self.assertEqual(_context().audit_metadata()["assurance"], "NONE")
        self.assertFalse(_context().is_session_authenticated)

    def test_session_assurance_without_a_session_is_refused(self):
        with self.assertRaises(ValueError):
            ExecutionContext(actor="TEST-actor", role="ADMIN",
                             channel=ExecutionChannel.API,
                             assurance="SESSION")

    def test_an_ungoverned_assurance_level_is_refused(self):
        for level in ("TRUSTED", "HIGH", "1", ""):
            with self.subTest(assurance=level):
                with self.assertRaises(ValueError):
                    ExecutionContext(actor="TEST-actor", role="ADMIN",
                                     channel=ExecutionChannel.API,
                                     assurance=level)

    def test_it_refuses_an_ungoverned_role(self):
        with self.assertRaises(ValueError):
            ExecutionContext(actor="TEST-actor", role="SUPERUSER",
                             channel=ExecutionChannel.API)
        self.assertEqual(GOVERNED_ACTOR_ROLES,
                         frozenset({"DEMO_USER", "EXPERT_REVIEWER", "ADMIN"}))

    def test_it_refuses_a_malformed_correlation_id(self):
        with self.assertRaises(ValueError):
            ExecutionContext(actor="TEST-actor", role="ADMIN",
                             channel=ExecutionChannel.API,
                             request_id="not-a-uuid")

    def test_an_absent_context_records_nothing_rather_than_inventing_an_actor(self):
        self.assertEqual(dict(audit_context_fields(None)), {})


class TestRequestMetadataNeverReachesAHash(unittest.TestCase):
    """§12: correlation metadata is recorded and never hashed."""

    def setUp(self):
        self.world = synthetic_world()
        self.addCleanup(self.world.close)

    def execute(self, document=None, *, context=None):
        document = create_request() if document is None else document
        assessment_input = adapt_assessment_request(document)
        result = self.world.service.execute(assessment_input,
                                            context=context or _context())
        return assessment_input, result

    def test_the_request_id_changes_no_semantic_hash(self):
        _, first = self.execute(context=_context(TEST_REQUEST_ID))
        _, second = self.execute(
            context=_context("22222222-2222-4222-8222-222222222222"))
        self.assertEqual(first.input_hash, second.input_hash)
        self.assertEqual(first.output_hash, second.output_hash)
        self.assertEqual(first.computation.coverage_result.content_hash(),
                         second.computation.coverage_result.content_hash())

    def test_the_actor_and_role_change_no_semantic_hash(self):
        _, first = self.execute(context=_context())
        other = ExecutionContext(actor="TEST-admin-1", role="ADMIN",
                                 channel=ExecutionChannel.CLI)
        _, second = self.execute(context=other)
        self.assertEqual(first.input_hash, second.input_hash)
        self.assertEqual(first.output_hash, second.output_hash)

    def test_the_request_id_reaches_the_audit_trail(self):
        self.execute(context=_context())
        completions = [record for record in self.world.audit.records
                       if record.get("action") == "ASSESSMENT_COMPLETED"]
        self.assertTrue(completions)
        self.assertEqual(completions[-1]["request_id"], TEST_REQUEST_ID)
        self.assertEqual(completions[-1]["role"], "DEMO_USER")
        self.assertEqual(completions[-1]["channel"], "API")

    def test_a_refusal_audit_carries_the_code_and_no_case_content(self):
        with self.assertRaises(Exception):
            self.execute(
                create_request(requested_release_public_id="PGX-REL-29990101-999"),
                context=_context())
        refusals = [record for record in self.world.audit.records
                    if record.get("action") == "ASSESSMENT_REFUSED"]
        self.assertTrue(refusals)
        record = refusals[-1]
        self.assertTrue(record["code"])
        self.assertEqual(record["request_id"], TEST_REQUEST_ID)
        rendered = repr(record)
        self.assertNotIn(DRUG_1, rendered)
        self.assertNotIn(GENE_1, rendered)
        for name in ("medications", "profile", "phenotypes", "narrative",
                     "case_id"):
            with self.subTest(field=name):
                self.assertNotIn(name, record)


