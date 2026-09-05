# -*- coding: utf-8 -*-
"""Runtime ASGI tests. Skipped here, and the skip says exactly why.

These are the tests that drive the real application through a real HTTP client:
they build the app with :func:`~apps.api.factory.create_app`, override the
provider with the synthetic world, and exercise every route end to end. They
are written and complete. They do not run in the environment WP-16 was built
in, and nothing here pretends otherwise.

They skip only where the packages are absent, and the skip names which ones.
WP-16 was built on such a host - the package index was unreachable and
``pip download fastapi`` failed with a proxy tunnel error - and every skip
message names the missing package rather than saying "dependencies
unavailable", because a skip nobody can act on is a skip everyone learns to
ignore.

Whether these tests have *run* on a given checkout is recorded by
``python -m apps.api.runtime_verification`` and read by the gate status. This
module does not report that, and the difference matters: a suite that skipped
is not a suite that failed, and neither is evidence that anything passed.

Two things follow, and both are stated in the WP-16 gate status rather than
worked around:

- No test in this file has ever executed. They are not counted as passing
  anywhere, and the acceptance report reports them as blocked.
- The framework-free half of ``apps.api`` - which holds every decision this
  layer makes - *is* fully executed, by ``tests/unit/api``. What these tests
  add is proof that the wiring between that half and FastAPI is correct.

Run them by installing the ``api`` extra and the dev group in an environment
with a package index. Nothing else needs to change.
"""

from __future__ import annotations

import unittest

_MISSING = []
for _name in ("fastapi", "pydantic", "starlette", "httpx"):
    try:  # pragma: no cover - environment dependent
        __import__(_name)
    except ImportError:  # pragma: no cover - environment dependent
        _MISSING.append(_name)

SKIP_REASON = (
    "not installed in this environment: %s. The ASGI application cannot be "
    "constructed and no HTTP request can be issued, so these tests did not "
    "execute here and are reported as BLOCKED, not as passing. Install the "
    "'api' extra to run them."
    % ", ".join(_MISSING)) if _MISSING else ""


def _client(world, **provider_kwargs):  # pragma: no cover - needs the framework
    """Build the real application over the synthetic world."""
    from fastapi.testclient import TestClient

    from apps.api.factory import create_app
    from tests.fixtures.wp16.synthetic import synthetic_provider
    from tests.unit.api._support import test_settings

    settings = test_settings()
    provider = synthetic_provider(world, settings=settings, **provider_kwargs)
    return TestClient(create_app(settings, provider), raise_server_exceptions=False)


@unittest.skipIf(_MISSING, SKIP_REASON)
class TestTheApplicationComposes(unittest.TestCase):  # pragma: no cover

    def test_importing_the_application_opens_no_connection(self):
        import apps.api.main as main
        self.assertIsNotNone(main.app)

    def test_the_served_openapi_matches_the_committed_artifact(self):
        """Every path, operation, schema and limit. Not the attestation.

        ``compare_documents`` ignores ``x-pgx-runtime-verification`` and
        nothing else, and the exclusion is the point rather than a loophole.
        The committed artifact is a declaration - this is the API the contract
        describes - written always as unverified. What a running application
        serves carries the current attestation, read from recorded evidence.
        Comparing those two fields would compare a declaration with an
        attestation and fail whenever the second was true.

        The attestation is checked separately, below, against the evidence it
        comes from. Both sides of *this* comparison go through the one loader
        and the one renderer, so it cannot drift from the other callers by
        reading the file differently.
        """
        from apps.api.artifacts import load_openapi_document
        from apps.api.openapi import compare_documents
        from tests.unit.api._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        with _client(world) as client:
            served = client.get("/openapi.json").json()
        identical, differences = compare_documents(served,
                                                   load_openapi_document())
        self.assertTrue(identical, "\n".join(differences[:10]))

    def test_the_served_attestation_comes_from_recorded_evidence(self):
        """And says BLOCKED unless a current, passing run says otherwise."""
        from apps.api.openapi import RUNTIME_VERIFICATION_BLOCKED
        from apps.api.runtime_verification import (VERIFIED,
                                                   verified_runtime_status)
        from tests.unit.api._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        with _client(world) as client:
            served = client.get("/openapi.json").json()

        recorded = verified_runtime_status()["openapi_runtime_verified"]
        status = served["x-pgx-runtime-verification"]["status"]
        self.assertEqual(status,
                         VERIFIED if recorded
                         else RUNTIME_VERIFICATION_BLOCKED)

    def test_the_committed_artifact_never_attests_to_itself(self):
        """The file on disk is a declaration and stays one.

        If this ever fails, somebody has made the artifact a function of the
        evidence - and the evidence is a function of the artifact, so the two
        will chase each other.
        """
        from apps.api.artifacts import load_openapi_document
        from apps.api.openapi import RUNTIME_VERIFICATION_BLOCKED

        committed = load_openapi_document()
        self.assertEqual(
            committed["x-pgx-runtime-verification"]["status"],
            RUNTIME_VERIFICATION_BLOCKED)


@unittest.skipIf(_MISSING, SKIP_REASON)
class TestHealthRoutes(unittest.TestCase):  # pragma: no cover

    def test_liveness_answers_without_any_dependency(self):
        from apps.api.factory import create_app
        from apps.api.dependencies import ServiceProvider
        from fastapi.testclient import TestClient
        from tests.unit.api._support import test_settings

        settings = test_settings()
        app = create_app(settings, ServiceProvider(settings=settings))
        with TestClient(app) as client:
            response = client.get("/health/live")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "LIVE"})

    def test_readiness_is_503_while_a_blocking_component_is_not_ready(self):
        from apps.api.factory import create_app
        from apps.api.dependencies import ServiceProvider
        from fastapi.testclient import TestClient
        from tests.unit.api._support import test_settings

        settings = test_settings()
        app = create_app(settings, ServiceProvider(settings=settings))
        with TestClient(app) as client:
            response = client.get("/health/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "NOT_READY")


@unittest.skipIf(_MISSING, SKIP_REASON)
class TestAuthenticationBoundary(unittest.TestCase):  # pragma: no cover

    def test_an_unauthenticated_assessment_request_is_401(self):
        from tests.fixtures.wp16.synthetic import create_request
        from tests.unit.api._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        with _client(world) as client:
            response = client.post("/api/v1/assessments",
                                   json=create_request())
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "UNAUTHENTICATED")

    def test_a_demo_user_may_not_reach_an_expert_review_route(self):
        from tests.fixtures.wp16.synthetic import TEST_DEMO_TOKEN
        from tests.unit.api._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        with _client(world) as client:
            response = client.post(
                "/api/v1/expert-reviews/TEST-CASE-1/expected", json={},
                headers={"Authorization": "Bearer " + TEST_DEMO_TOKEN})
        self.assertEqual(response.status_code, 403)

    def test_an_expert_review_route_refuses_when_no_service_is_wired(self):
        """The route was a 501 stub until WP-22 implemented the workflow.

        It answers 503 now, and the difference is the point: 501 said "this
        product has no such feature", which stopped being true. 503 says the
        feature exists and this deployment has no review service configured -
        which is what is actually the case, in this and every deployment,
        until a store and an approved protocol are supplied.

        The refusal is fail-closed by construction: the provider's
        ``expert_review_service`` defaults to ``None``, so a deployment that
        forgets to wire one refuses rather than silently accepting a review
        nobody can attribute.
        """
        from tests.fixtures.wp16.synthetic import TEST_REVIEWER_TOKEN
        from tests.unit.api._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        # A well-formed body, deliberately. An empty one is refused at 422 by
        # the request contract before the route runs, which would prove that
        # validation works rather than that the service is fail-closed.
        body = {"expected_attention_level": "HIGH",
                "expected_coverage_status": "FULL",
                "requires_traceable_evidence": True,
                "rationale_codes": ["GUIDELINE_DIRECT"]}
        with _client(world) as client:
            response = client.post(
                "/api/v1/expert-reviews/TEST-CASE-1/expected", json=body,
                headers={"Authorization": "Bearer " + TEST_REVIEWER_TOKEN})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"],
                         "EXPERT_REVIEW_NOT_AVAILABLE")

    def test_an_unauthenticated_review_request_is_401_not_503(self):
        """Otherwise the routes tell a stranger which paths exist.

        Unchanged in substance from the 501 era: whatever the refusal for an
        authenticated caller is, an unauthenticated one must be turned away
        before the route's own state is consulted.
        """
        from tests.unit.api._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        with _client(world) as client:
            response = client.post(
                "/api/v1/expert-reviews/TEST-CASE-1/reveal", json={})
        self.assertEqual(response.status_code, 401)


@unittest.skipIf(_MISSING, SKIP_REASON)
class TestTheEndToEndFlow(unittest.TestCase):  # pragma: no cover
    """POST, then GET, then evidence, then version - all agreeing.

    This test is synthetic implementation evidence, not a real clinical
    assessment.
    """

    def test_a_full_round_trip_agrees_at_every_step(self):
        from tests.fixtures.wp16.synthetic import (TEST_DEMO_TOKEN,
                                                   create_request)
        from tests.unit.api._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        headers = {"Authorization": "Bearer " + TEST_DEMO_TOKEN}
        with _client(world) as client:
            created = client.post("/api/v1/assessments",
                                  json=create_request(), headers=headers)
            self.assertEqual(created.status_code, 201)
            self.assertIn("Location", created.headers)
            self.assertIn("X-Request-ID", created.headers)
            body = created.json()

            # The release was pinned exactly once for the whole request.
            self.assertEqual(world.resolver.pointer_reads, 1)

            fetched = client.get("/api/v1/assessments/%s"
                                 % body["assessment_id"], headers=headers)
            self.assertEqual(fetched.status_code, 200)
            stored = fetched.json()
            self.assertEqual(
                {k: v for k, v in body.items() if k != "created_at"},
                {k: v for k, v in stored.items() if k != "created_at"})

            # Reading did not resolve the pointer again.
            self.assertEqual(world.resolver.pointer_reads, 1)

            reference = body["medications"][0]["findings"][0][
                "evidence_references"][0]
            evidence = client.get("/api/v1/evidence/%s" % reference,
                                  headers=headers)
            self.assertIn(evidence.status_code, (200, 404))

            version = client.get("/api/v1/system/version")
            self.assertEqual(version.status_code, 200)
            self.assertEqual(version.json()["release_public_id"],
                             body["release"]["release_public_id"])

    def test_a_prohibited_field_is_refused_without_being_echoed(self):
        from tests.fixtures.wp16.synthetic import (TEST_DEMO_TOKEN,
                                                   create_request)
        from tests.unit.api._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        document = dict(create_request(), genotype="TEST-*1/*2")
        with _client(world) as client:
            response = client.post(
                "/api/v1/assessments", json=document,
                headers={"Authorization": "Bearer " + TEST_DEMO_TOKEN})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"],
                         "PROHIBITED_INPUT_FIELD")
        self.assertNotIn("TEST-*1/*2", response.text)

    def test_the_request_id_is_echoed_and_matches_the_envelope(self):
        from tests.unit.api._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        request_id = "11111111-1111-4111-8111-111111111111"
        with _client(world) as client:
            response = client.get("/api/v1/assessments/not-a-uuid",
                                  headers={"X-Request-ID": request_id})
        self.assertEqual(response.headers["X-Request-ID"], request_id)
        self.assertEqual(response.json()["error"]["request_id"], request_id)

    def test_a_malformed_request_id_is_refused(self):
        from tests.unit.api._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        with _client(world) as client:
            response = client.get("/health/live",
                                  headers={"X-Request-ID": "not-a-uuid"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"],
                         "REQUEST_ID_INVALID")

    def test_an_oversized_body_is_refused_before_it_is_parsed(self):
        from tests.fixtures.wp16.synthetic import TEST_DEMO_TOKEN
        from tests.unit.api._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        with _client(world) as client:
            response = client.post(
                "/api/v1/assessments",
                content=b"x" * (128 * 1024),
                headers={"Authorization": "Bearer " + TEST_DEMO_TOKEN,
                         "Content-Type": "application/json"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"],
                         "REQUEST_TOO_LARGE")

    def test_every_response_carries_the_security_headers(self):
        from tests.unit.api._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        with _client(world) as client:
            response = client.get("/health/live")
        for header in ("X-Content-Type-Options", "X-Frame-Options",
                       "Referrer-Policy", "Content-Security-Policy",
                       "Cache-Control"):
            with self.subTest(header=header):
                self.assertIn(header, response.headers)


@unittest.skipIf(_MISSING, SKIP_REASON)
class TestUnavailableCapabilities(unittest.TestCase):  # pragma: no cover

    def test_a_missing_database_is_reported_as_unavailability(self):
        from tests.fixtures.wp16.synthetic import TEST_DEMO_TOKEN
        from tests.unit.api._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        with _client(world, with_reader=False) as client:
            response = client.get(
                "/api/v1/assessments/11111111-1111-4111-8111-111111111111",
                headers={"Authorization": "Bearer " + TEST_DEMO_TOKEN})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"],
                         "DATABASE_UNAVAILABLE")

    def test_a_missing_release_is_reported_as_unavailability(self):
        from tests.unit.api._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        with _client(world, with_release=False) as client:
            response = client.get("/api/v1/system/version")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"],
                         "ACTIVE_RELEASE_UNAVAILABLE")


class TestTheSkipIsHonest(unittest.TestCase):
    """Runs everywhere. Asserts that the skip above states a real reason."""

    def test_the_reason_names_the_missing_packages(self):
        if not _MISSING:
            self.skipTest("the framework is installed; the runtime tests ran")
        for name in _MISSING:
            self.assertIn(name, SKIP_REASON)
        self.assertIn("BLOCKED", SKIP_REASON)

    def test_no_runtime_test_is_counted_as_passing_when_skipped(self):
        """A guard against the one repair nobody should make: replacing the
        missing framework with a stand-in and calling the result a pass."""
        import os
        from tests.unit.api._support import REPO_ROOT
        vendored = [name for name in ("fastapi", "pydantic", "starlette",
                                      "uvicorn", "httpx")
                    if os.path.isdir(os.path.join(REPO_ROOT, name))]
        self.assertEqual(vendored, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


@unittest.skipIf(_MISSING, SKIP_REASON)
class TestTheProhibitedScanOutranksTheFramework(unittest.TestCase):
    """The classification is the contract's, not Pydantic's.

    A request carrying ``genotype`` used to come back
    ``REQUEST_CONTRACT_VIOLATION``: the model forbids extra fields, Pydantic
    rejected the unknown key while FastAPI was resolving parameters, and the
    authoritative scan in ``apps/api/contracts/validate.py`` never ran. The
    right code says *this product does not accept this kind of data*; the
    wrong one says *your JSON was the wrong shape*, and a reviewer asking
    whether anyone had ever sent a genotype would have got the wrong answer.

    These pin the properties the repair has to keep, not the repair itself.
    """

    PROHIBITED_VALUE = "TEST-*1/*2-NEVER-ECHO"

    def _post(self, document, path="/api/v1/assessments", token=True):
        from tests.fixtures.wp16.synthetic import TEST_DEMO_TOKEN
        from tests.unit.api._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        headers = {"Authorization": "Bearer " + TEST_DEMO_TOKEN} if token \
            else {}
        with _client(world) as client:
            return client.post(path, json=document, headers=headers)

    def test_a_top_level_prohibited_field_is_classified_as_prohibited(self):
        from tests.fixtures.wp16.synthetic import create_request

        response = self._post(dict(create_request(),
                                   genotype=self.PROHIBITED_VALUE))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"],
                         "PROHIBITED_INPUT_FIELD")

    def test_a_nested_prohibited_field_is_found_at_depth(self):
        """One extra layer of nesting must not satisfy the refusal."""
        from tests.fixtures.wp16.synthetic import create_request

        document = dict(create_request())
        document["observations"] = [
            {"gene": "GENE:TESTGENE1", "phenotype": "POOR",
             "extra": {"deeper": {"genotype": self.PROHIBITED_VALUE}}}]
        response = self._post(document)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"],
                         "PROHIBITED_INPUT_FIELD")

    def test_no_prohibited_value_is_echoed_anywhere_in_the_response(self):
        from tests.fixtures.wp16.synthetic import create_request

        response = self._post(dict(create_request(),
                                   genotype=self.PROHIBITED_VALUE))
        self.assertNotIn(self.PROHIBITED_VALUE, response.text)
        for issue in response.json()["error"]["details"]["issues"]:
            self.assertEqual(sorted(issue), ["code", "location"])
            self.assertEqual(issue["code"], "PROHIBITED_FIELD")

    def test_the_location_is_reported_and_it_is_a_path_not_a_value(self):
        from tests.fixtures.wp16.synthetic import create_request

        response = self._post(dict(create_request(),
                                   genotype=self.PROHIBITED_VALUE))
        locations = [issue["location"]
                     for issue in response.json()["error"]["details"]["issues"]]
        self.assertIn("$.genotype", locations)

    def test_an_otherwise_valid_request_still_succeeds(self):
        """The scan must not refuse traffic it has no business refusing."""
        from tests.fixtures.wp16.synthetic import create_request

        response = self._post(create_request())
        self.assertEqual(response.status_code, 201, response.text)

    def test_a_shape_error_without_a_prohibited_field_keeps_its_own_code(self):
        response = self._post({"not_a_declared_field": 1})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"],
                         "REQUEST_CONTRACT_VIOLATION")

    def test_an_undeclared_path_is_not_turned_into_an_oracle(self):
        """A scan in front of routing must not answer for paths that do not
        exist, or an anonymous caller learns which addresses are real by
        posting a genotype at each of them."""
        response = self._post({"genotype": self.PROHIBITED_VALUE},
                              path="/api/v1/no-such-operation", token=False)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"],
                         "RESOURCE_NOT_FOUND")
        self.assertNotIn(self.PROHIBITED_VALUE, response.text)

    def test_the_refusal_carries_a_correlation_id(self):
        from apps.api.request_id import REQUEST_ID_HEADER
        from tests.fixtures.wp16.synthetic import create_request

        response = self._post(dict(create_request(),
                                   genotype=self.PROHIBITED_VALUE))
        self.assertIn(REQUEST_ID_HEADER, response.headers)
        self.assertEqual(response.headers[REQUEST_ID_HEADER],
                         response.json()["error"]["request_id"])

    def test_it_runs_after_the_size_limiter_not_before(self):
        """An unbounded body must be disconnected, not buffered and parsed."""
        from apps.api.factory import create_app
        from apps.api.middleware import (BodySizeLimitMiddleware,
                                         ProhibitedFieldMiddleware)
        from tests.unit.api._support import test_settings

        from tests.fixtures.wp16.synthetic import synthetic_provider
        from tests.unit.api._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        settings = test_settings()
        app = create_app(settings, synthetic_provider(world,
                                                      settings=settings))
        classes = [entry.cls for entry in app.user_middleware]
        # Outermost first. The size limiter must appear before the scan.
        self.assertIn(BodySizeLimitMiddleware, classes)
        self.assertIn(ProhibitedFieldMiddleware, classes)
        self.assertLess(classes.index(BodySizeLimitMiddleware),
                        classes.index(ProhibitedFieldMiddleware))
