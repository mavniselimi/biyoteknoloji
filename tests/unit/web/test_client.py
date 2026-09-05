# -*- coding: utf-8 -*-
"""The client boundary: exact contracts in, typed refusals out.

The client is the only thing in the interface that knows what a WP-16 response
looks like. These tests check that it validates what it produces, preserves
what the API said, and never converts a failure into an empty success.
"""

from __future__ import annotations

import ast
import os
import unittest

from apps.api.contracts.validate import validate_document
from apps.web.client import (CLIENT_OPERATIONS, ClientResponse,
                             HttpApiClient, InProcessApiClient, PgxApiClient,
                             UnavailableApiClient)
from apps.web.errors import WebError
from tests.fixtures.wp13.synthetic import DRUG_1
from tests.fixtures.wp16.synthetic import create_request
from tests.fixtures.wp17.synthetic import (execution_context,
                                           synthetic_web_provider)
from tests.unit.web._support import (REPO_ROOT, module_path, source,
                                    synthetic_world)

EVIDENCE_ID = "aaaaaaaa-0000-4000-8000-000000000001"
MISSING_UUID = "99999999-9999-4999-8999-999999999999"


class TestThePortIsNarrow(unittest.TestCase):

    def test_the_port_exposes_exactly_the_declared_operations(self):
        methods = {name for name in dir(PgxApiClient)
                   if not name.startswith("_")}
        self.assertEqual(methods, set(CLIENT_OPERATIONS))

    def test_there_is_no_expert_review_operation(self):
        """A method that existed only to receive a 501 would invite a page to
        call it and render something."""
        for name in dir(PgxApiClient):
            with self.subTest(method=name):
                self.assertNotIn("expert", name.lower())
                self.assertNotIn("review", name.lower())

    def test_every_implementation_covers_the_port(self):
        for implementation in (InProcessApiClient, UnavailableApiClient,
                               HttpApiClient):
            for name in CLIENT_OPERATIONS:
                with self.subTest(client=implementation.__name__,
                                  operation=name):
                    self.assertTrue(hasattr(implementation, name))

    def test_a_response_of_an_unexpected_model_is_refused(self):
        with self.assertRaises(ValueError):
            ClientResponse(model="SomethingElse", document={},
                           request_id="x")


class _Composed(unittest.TestCase):

    def setUp(self):
        self.world = synthetic_world()
        self.addCleanup(self.world.close)
        self.provider = synthetic_web_provider(self.world)
        self.client = self.provider.client
        self.context = execution_context()
        self.request_id = self.context.request_id


class TestEveryResponseIsValidated(_Composed):

    def test_each_operation_returns_a_document_of_its_declared_model(self):
        created = self.client.create_assessment(create_request(),
                                                context=self.context)
        checks = {
            "create_assessment": created,
            "get_assessment": self.client.get_assessment(
                created.document["assessment_id"],
                request_id=self.request_id),
            "list_drugs": self.client.list_drugs(request_id=self.request_id),
            "list_genes": self.client.list_genes(request_id=self.request_id),
            "get_evidence": self.client.get_evidence(
                EVIDENCE_ID, request_id=self.request_id),
            "get_system_version": self.client.get_system_version(
                request_id=self.request_id),
            "get_readiness": self.client.get_readiness(
                request_id=self.request_id),
        }
        for operation, response in checks.items():
            with self.subTest(operation=operation):
                self.assertEqual(response.model, CLIENT_OPERATIONS[operation])
                self.assertTrue(validate_document(response.model,
                                                  response.document))

    def test_the_request_id_is_carried_through(self):
        response = self.client.get_system_version(request_id=self.request_id)
        self.assertEqual(response.request_id, self.request_id)

    def test_a_document_that_violates_the_contract_is_refused(self):
        """A server-side inconsistency, reported as one rather than rendered."""
        class _BadReader:
            def read_model(self, assessment_id):
                class _Model:
                    assessment_id = "not-a-uuid"
                    created_at = None
                    completed_at = None
                    input_hash = "not-a-hash"
                    output_hash = "not-a-hash"
                    input_snapshot = {}
                    computation = {}
                return _Model()

        provider = synthetic_web_provider(self.world)
        broken = InProcessApiClient(
            type("P", (), {
                "require_assessment_reader": lambda self: _BadReader(),
            })())
        with self.assertRaises(WebError) as caught:
            broken.get_assessment(MISSING_UUID, request_id=self.request_id)
        self.assertIn(caught.exception.code,
                      ("INTERNAL_ERROR", "STORED_RESULT_INCONSISTENT"))


class TestPostAndGetAgree(_Composed):

    def test_the_two_paths_return_identical_governed_facts(self):
        created = self.client.create_assessment(create_request(),
                                                context=self.context)
        fetched = self.client.get_assessment(
            created.document["assessment_id"], request_id=self.request_id)
        strip = lambda document: {key: value
                                  for key, value in document.items()
                                  if key != "created_at"}
        self.assertEqual(strip(created.document), strip(fetched.document))

    def test_reading_does_not_resolve_the_release_again(self):
        created = self.client.create_assessment(create_request(),
                                                context=self.context)
        before = self.world.resolver.pointer_reads
        self.client.get_assessment(created.document["assessment_id"],
                                   request_id=self.request_id)
        self.assertEqual(self.world.resolver.pointer_reads, before)

    def test_an_old_assessment_stays_pinned_after_the_release_moves(self):
        created = self.client.create_assessment(create_request(),
                                                context=self.context)
        pinned = created.document["release"]["release_public_id"]
        self.world.resolver.move_pointer()
        fetched = self.client.get_assessment(
            created.document["assessment_id"], request_id=self.request_id)
        self.assertEqual(fetched.document["release"]["release_public_id"],
                         pinned)


class TestFailuresAreNeverEmptySuccesses(_Composed):

    def test_a_missing_assessment_raises(self):
        with self.assertRaises(WebError) as caught:
            self.client.get_assessment(MISSING_UUID,
                                       request_id=self.request_id)
        self.assertEqual(caught.exception.code, "ASSESSMENT_NOT_FOUND")
        self.assertEqual(caught.exception.status, 404)

    def test_a_missing_evidence_record_raises(self):
        with self.assertRaises(WebError) as caught:
            self.client.get_evidence(MISSING_UUID,
                                     request_id=self.request_id)
        self.assertEqual(caught.exception.code, "EVIDENCE_NOT_FOUND")

    def test_a_prohibited_field_keeps_the_api_code(self):
        with self.assertRaises(WebError) as caught:
            self.client.create_assessment(
                dict(create_request(), genotype="*1/*2"),
                context=self.context)
        self.assertEqual(caught.exception.code, "PROHIBITED_INPUT_FIELD")
        self.assertNotIn("*1/*2", repr(caught.exception.details))

    def test_each_missing_capability_gets_its_own_code(self):
        cases = {
            "with_client": ("SERVICE_NOT_READY", None),
        }
        del cases
        provider = synthetic_web_provider(self.world)
        from tests.fixtures.wp16.synthetic import synthetic_provider
        bare = InProcessApiClient(
            synthetic_provider(self.world, settings=provider.settings.api,
                               with_reader=False, with_release=False,
                               with_evidence=False))
        expected = {
            "DATABASE_UNAVAILABLE":
                lambda: bare.get_assessment(MISSING_UUID, request_id="r"),
            "ACTIVE_RELEASE_UNAVAILABLE":
                lambda: bare.list_drugs(request_id="r"),
            "EVIDENCE_BUILD_UNAVAILABLE":
                lambda: bare.get_evidence(EVIDENCE_ID, request_id="r"),
        }
        for code, call in expected.items():
            with self.subTest(code=code):
                with self.assertRaises(WebError) as caught:
                    call()
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.status, 503)

    def test_the_unavailable_client_refuses_every_operation(self):
        client = UnavailableApiClient()
        calls = {
            "get_assessment": lambda: client.get_assessment("x",
                                                            request_id="r"),
            "list_drugs": lambda: client.list_drugs(request_id="r"),
            "list_genes": lambda: client.list_genes(request_id="r"),
            "get_evidence": lambda: client.get_evidence("x", request_id="r"),
            "get_system_version":
                lambda: client.get_system_version(request_id="r"),
            "get_readiness": lambda: client.get_readiness(request_id="r"),
        }
        for name, call in calls.items():
            with self.subTest(operation=name):
                with self.assertRaises(WebError):
                    call()

    def test_no_failure_returns_none(self):
        """Every operation either returns a validated response or raises."""
        try:
            self.client.get_assessment(MISSING_UUID,
                                       request_id=self.request_id)
        except WebError:
            pass
        else:  # pragma: no cover - the assertion is the else branch
            self.fail("a missing assessment returned instead of raising")


class TestTheClientUsesTheSameAdaptersAsTheApi(unittest.TestCase):
    """The in-process path and the HTTP path must produce one document.

    Asserted by comparing which adapter functions each side calls. A client
    that built a document some other way would be a second serialiser, and the
    two would drift on the first change to either.
    """

    def _adapter_calls(self, path):
        found = set()
        for node in ast.walk(ast.parse(source(path))):
            if isinstance(node, ast.ImportFrom) and node.module and \
                    node.module.startswith("apps.api.adapters"):
                found.update(alias.name for alias in node.names)
        return found

    def test_the_client_calls_the_adapters_the_routers_call(self):
        client = self._adapter_calls(module_path("client.py"))
        routers = set()
        api_routers = os.path.join(REPO_ROOT, "apps", "api", "routers")
        for name in sorted(os.listdir(api_routers)):
            if name.endswith(".py"):
                routers |= self._adapter_calls(os.path.join(api_routers,
                                                            name))
        self.assertTrue(client)
        self.assertEqual(client, routers,
                         "the interface and the API build documents with "
                         "different adapters")


class TestTheHttpClientIsWrittenButUnexercised(unittest.TestCase):

    def test_it_preserves_the_servers_request_id(self):
        text = source(module_path("client.py"))
        self.assertIn("response.headers.get(REQUEST_ID_HEADER", text)

    def test_it_validates_what_it_receives(self):
        text = source(module_path("client.py"))
        self.assertIn("_validated(model, document, correlation)", text)

    def test_it_cannot_be_used_without_httpx(self):
        import importlib
        try:
            importlib.import_module("httpx")
        except ImportError:
            client = HttpApiClient("http://127.0.0.1:8000")
            with self.assertRaises(WebError):
                client._client()
        else:  # pragma: no cover - depends on the environment
            self.skipTest("httpx is installed in this environment, so the "
                          "missing-dependency path cannot be exercised")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
