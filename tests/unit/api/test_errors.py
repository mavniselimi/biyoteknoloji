# -*- coding: utf-8 -*-
"""F. The error envelope, the mapper and the status table.

One shape, one catalogue, one mapper. What is checked here is that the shape
never varies, that no message is ever built from an exception, and that every
code an application or engine failure can carry has a status somebody chose.
"""

from __future__ import annotations

import unittest

from apps.api.contracts.spec import LIMITS
from apps.api.contracts.validate import ContractViolation, Issue, validate_document
from apps.api.errors import (ENGINE_CODE_STATUS, ERROR_CATALOGUE, ApiError,
                             ForbiddenError, NotFoundError, NotReadyError,
                             ExpertReviewApiError, RequestContractError,
                             UnauthenticatedError, error_envelope,
                             map_exception, status_for_code)
from apps.api.request_id import generate_request_id
from pgx.domain.claims import scan_claim_text
from pgx.engine.risk_errors import FAILURE_CODES

REQUEST_ID = "11111111-1111-4111-8111-111111111111"


class TestTheEnvelopeShape(unittest.TestCase):

    def test_the_envelope_has_exactly_one_shape(self):
        envelope = error_envelope("INTERNAL_ERROR", REQUEST_ID)
        self.assertEqual(sorted(envelope), ["error"])
        self.assertEqual(sorted(envelope["error"]),
                         ["code", "details", "message", "request_id"])

    def test_the_envelope_satisfies_the_contract(self):
        for code in ERROR_CATALOGUE:
            with self.subTest(code=code):
                self.assertTrue(validate_document(
                    "ErrorEnvelope", error_envelope(code, REQUEST_ID)))

    def test_the_request_id_is_carried_verbatim(self):
        envelope = error_envelope("INTERNAL_ERROR", REQUEST_ID)
        self.assertEqual(envelope["error"]["request_id"], REQUEST_ID)

    def test_an_unknown_code_becomes_the_generic_internal_error(self):
        envelope = error_envelope("NO-SUCH-CODE", REQUEST_ID)
        self.assertEqual(envelope["error"]["code"], "INTERNAL_ERROR")

    def test_details_are_bounded(self):
        issues = [{"location": "$.f%03d" % index, "code": "UNKNOWN_FIELD"}
                  for index in range(LIMITS["max_detail_entries"] * 3)]
        envelope = error_envelope("REQUEST_CONTRACT_VIOLATION", REQUEST_ID,
                                  details={"issues": issues})
        self.assertLessEqual(len(envelope["error"]["details"]["issues"]),
                             LIMITS["max_detail_entries"])


class TestTheCatalogue(unittest.TestCase):

    def test_every_message_is_fixed_and_safe(self):
        for code, (status, message) in ERROR_CATALOGUE.items():
            with self.subTest(code=code):
                self.assertIsInstance(message, str)
                self.assertTrue(message)
                self.assertNotIn("%", message)
                self.assertNotIn("{", message)

    def test_no_catalogue_message_makes_a_prohibited_claim(self):
        """Pre-scanned as a fixed catalogue, so that scanning an error message
        can never itself raise while an error is being handled."""
        for code, (_status, message) in ERROR_CATALOGUE.items():
            with self.subTest(code=code):
                report = scan_claim_text(message)
                self.assertEqual(
                    list(getattr(report, "violations", ()) or ()), [])

    def test_no_catalogue_message_names_an_internal_detail(self):
        forbidden = ("postgres", "postgresql", "sqlalchemy", "psycopg",
                     "traceback", "/var/", "/home/", "select ", "insert ",
                     "password", "secret", "token=", "http://", "https://")
        for code, (_status, message) in ERROR_CATALOGUE.items():
            lowered = message.lower()
            for needle in forbidden:
                with self.subTest(code=code, needle=needle):
                    self.assertNotIn(needle, lowered)

    def test_the_status_table_uses_only_the_mapped_statuses(self):
        """501 left the list at WP-22, and its absence is the point.

        The only 501 in this API was the expert-review stub. Those routes are
        service-backed now, so no route answers "not implemented" - and a
        catalogue that still offered the code would be a slot for a future
        half-built route to occupy.
        """
        self.assertEqual(
            sorted({status for status, _ in ERROR_CATALOGUE.values()}),
            [400, 401, 403, 404, 409, 422, 500, 503])

    def test_no_route_answers_not_implemented(self):
        from apps.api.routes import ROUTES
        self.assertEqual([route.operation_id for route in ROUTES
                          if route.success_status == 501], [])
        self.assertEqual([route.operation_id for route in ROUTES
                          if not route.implemented], [])

    def test_the_claim_boundary_gate_is_unavailability_not_bad_input(self):
        status, message = ERROR_CATALOGUE["CLAIM_BOUNDARY_NOT_APPROVED"]
        self.assertEqual(status, 503)
        self.assertIn("governance gate", message)


class TestTheMapper(unittest.TestCase):

    def test_every_engine_failure_code_is_mapped(self):
        for code in FAILURE_CODES:
            with self.subTest(code=code):
                self.assertIn(code, ENGINE_CODE_STATUS)

    def test_every_mapping_target_exists_in_the_catalogue(self):
        for code, target in ENGINE_CODE_STATUS.items():
            with self.subTest(code=code):
                self.assertIn(target, ERROR_CATALOGUE)

    def test_an_api_error_keeps_its_own_code(self):
        for error, expected in ((UnauthenticatedError("UNAUTHENTICATED"),
                                 "UNAUTHENTICATED"),
                                (ForbiddenError("FORBIDDEN_ROLE"),
                                 "FORBIDDEN_ROLE"),
                                (NotFoundError("ASSESSMENT_NOT_FOUND"),
                                 "ASSESSMENT_NOT_FOUND"),
                                (NotReadyError("DATABASE_UNAVAILABLE"),
                                 "DATABASE_UNAVAILABLE"),
                                (ExpertReviewApiError(
                                    "EXPERT_REVIEW_NOT_AVAILABLE"),
                                 "EXPERT_REVIEW_NOT_AVAILABLE")):
            with self.subTest(code=expected):
                self.assertEqual(map_exception(error)[0], expected)

    def test_a_contract_violation_maps_by_its_issue_codes(self):
        prohibited = ContractViolation(
            "AssessmentCreateRequest", [Issue("$.genotype",
                                              "PROHIBITED_FIELD")])
        self.assertEqual(map_exception(prohibited)[0], "PROHIBITED_INPUT_FIELD")
        ordinary = ContractViolation(
            "AssessmentCreateRequest", [Issue("$.mode", "ENUM_INVALID")])
        self.assertEqual(map_exception(ordinary)[0],
                         "REQUEST_CONTRACT_VIOLATION")

    def test_an_unexpected_exception_becomes_a_generic_internal_error(self):
        secret = "postgresql://user:hunter2@db:5432/pgx"
        code, details = map_exception(RuntimeError("connect failed " + secret))
        self.assertEqual(code, "INTERNAL_ERROR")
        envelope = error_envelope(code, REQUEST_ID, details=details)
        rendered = repr(envelope)
        self.assertNotIn(secret, rendered)
        self.assertNotIn("hunter2", rendered)
        self.assertNotIn("connect failed", rendered)

    def test_the_mapper_is_total(self):
        class _Odd(Exception):
            pass
        for error in (Exception("x"), _Odd(), ValueError(), KeyError("k"),
                      TypeError(), ZeroDivisionError()):
            with self.subTest(error=type(error).__name__):
                code, _ = map_exception(error)
                self.assertIn(code, ERROR_CATALOGUE)

    def test_no_response_ever_carries_exception_text(self):
        for error in (RuntimeError("Traceback (most recent call last)"),
                      OSError("/home/pgx/secret.key not found"),
                      ValueError("SELECT * FROM assessments WHERE id = 1")):
            code, details = map_exception(error)
            envelope = error_envelope(code, REQUEST_ID, details=details)
            rendered = repr(envelope).lower()
            with self.subTest(error=str(error)[:20]):
                self.assertNotIn("traceback", rendered)
                self.assertNotIn("/home/", rendered)
                self.assertNotIn("select", rendered)


class TestStatusMapping(unittest.TestCase):
    """§11's table, asserted code by code."""

    EXPECTED = {
        "REQUEST_MALFORMED": 400,
        "UNAUTHENTICATED": 401,
        "FORBIDDEN_ROLE": 403,
        "MODE_NOT_PERMITTED": 403,
        "ASSESSMENT_NOT_FOUND": 404,
        "EVIDENCE_NOT_FOUND": 404,
        "RELEASE_NOT_ACTIVE": 409,
        "CURSOR_RELEASE_MISMATCH": 409,
        "REQUEST_CONTRACT_VIOLATION": 422,
        "PROHIBITED_INPUT_FIELD": 422,
        "UNSUPPORTED_PHENOTYPE": 422,
        "EXPERT_REVIEW_NOT_AVAILABLE": 503,
        "EXPERT_REVIEW_NOT_ASSIGNED": 404,
        "EXPERT_REVIEW_ROLE_REQUIRED": 403,
        "EXPERT_REVIEW_ALREADY_COMPLETED": 409,
        "SERVICE_NOT_READY": 503,
        "CLAIM_BOUNDARY_NOT_APPROVED": 503,
        "ACTIVE_RELEASE_UNAVAILABLE": 503,
        "DATABASE_UNAVAILABLE": 503,
        "AUTHENTICATION_NOT_CONFIGURED": 503,
        "INTERNAL_ERROR": 500,
    }

    def test_each_code_carries_the_status_the_contract_assigns(self):
        for code, status in self.EXPECTED.items():
            with self.subTest(code=code):
                self.assertEqual(status_for_code(code), status)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestMalformedIdentifiersAreCallerErrors(unittest.TestCase):
    """A malformed path identifier is a 4xx, and never quotes the value.

    Two lines of defence, because the first one lives in a layer that cannot
    be executed here: the routers build their path parameters from the route
    table, so FastAPI refuses a non-UUID before the handler runs, and
    ``map_exception`` handles the case where one reaches the domain parser
    anyway. The domain parser's message quotes what it could not read, which
    is exactly the sort of value that must not become a response body.
    """

    def test_a_malformed_identifier_is_a_contract_violation(self):
        from pgx.domain.identifiers import AssessmentId
        for value in ("not-a-uuid", "", "11111111-1111-4111-8111-1111111111"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(Exception) as caught:
                    AssessmentId.parse(value)
                code, details = map_exception(caught.exception)
                self.assertEqual(code, "REQUEST_CONTRACT_VIOLATION")
                self.assertEqual(status_for_code(code), 422)
                self.assertEqual(details["issues"][0]["code"], "UUID_INVALID")

    def test_the_rejected_identifier_is_not_echoed(self):
        from pgx.domain.identifiers import AssessmentId
        secret = "SECRET-IDENTIFIER-VALUE"
        with self.assertRaises(Exception) as caught:
            AssessmentId.parse(secret)
        code, details = map_exception(caught.exception)
        envelope = error_envelope(code, REQUEST_ID, details=details)
        self.assertNotIn(secret, repr(envelope))
