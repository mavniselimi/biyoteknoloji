# -*- coding: utf-8 -*-
"""Runtime ASGI tests for the interface. Skipped here, and the skip says why.

These drive the real web application through a real HTTP client: they build it
with :func:`~apps.web.factory.create_web_app`, compose it with the synthetic
world, and request every one of the eleven pages over HTTP. They are written
and complete. They have never executed in this environment and nothing here
pretends otherwise.

They skip only where FastAPI, Starlette, Pydantic, HTTPX or python-multipart
is absent, and the skip names which. WP-17 was built on such a host, where the
package index was unreachable; the skip message names the packages rather than
saying "dependencies unavailable", because a skip nobody can act on is a skip
everyone learns to ignore.

What separates this file from WP-16's :mod:`tests.integration.api` sibling is
what *does* run here. Jinja2 is installed, so every page in this file is
rendered for real by ``tests/unit/web/test_pages.py``, scanned for real by
``test_safety.py``, parsed for real by ``test_accessibility.py``, and driven
end to end by ``test_e2e_flow.py`` - against the same provider, the same
templates and the same view models. The rendering half of the interface is
therefore executed. What is *not* executed, and what these tests exist to
cover, is the wiring between that half and the framework: route registration,
dependency injection, the static mount, form parsing, the exception handlers
and the response headers as Starlette actually emits them.

Run them by installing the ``web`` extra in an environment with a package
index. Nothing else needs to change.
"""

from __future__ import annotations

import unittest

_REQUIRED = ("fastapi", "starlette", "pydantic", "httpx", "multipart")

_MISSING = []
for _name in _REQUIRED:
    try:  # pragma: no cover - environment dependent
        __import__(_name)
    except ImportError:  # pragma: no cover - environment dependent
        _MISSING.append("python-multipart" if _name == "multipart" else _name)

SKIP_REASON = (
    "not installed in this environment: %s. The ASGI application cannot be "
    "constructed and no HTTP request can be issued against a page, so these "
    "tests did not execute here and are reported as BLOCKED, not as passing. "
    "The page rendering they wrap around *is* executed, by tests/unit/web. "
    "Install the 'web' extra to run them."
    % ", ".join(_MISSING)) if _MISSING else ""


#: A migrated case. Present in the shipped catalogue, and - because the
#: migrated profiles name real genes the synthetic ruleset does not govern -
#: assessed as INSUFFICIENT. Fine for every page that only needs a valid id.
CATALOG_CASE_ID = "WP17-CASE-P1"

#: The fixture case the synthetic ruleset actually covers, so a flow reaches a
#: finding and an evidence link. Deliberately absent from the shipped
#: catalogue, so a test that wants it must add it to the provider explicitly.
COVERED_CASE_ID = "WP17-CASE-FIXTURE-COVERED"


def _client(world, *, covered=False, authenticated=True,
            **provider_kwargs):  # pragma: no cover
    """Build the real web application over the synthetic world."""
    import dataclasses

    from fastapi.testclient import TestClient

    from apps.web.factory import create_web_app
    from tests.fixtures.wp17.synthetic import (COVERED_FIXTURE_CASE,
                                               development_cases,
                                               synthetic_providers,
                                               test_web_settings)

    settings = provider_kwargs.pop("settings", None) or test_web_settings()
    provider, api_provider = synthetic_providers(world, settings=settings,
                                                 **provider_kwargs)
    if covered:
        catalog = development_cases() + (COVERED_FIXTURE_CASE,)
        provider = dataclasses.replace(provider,
                                       case_catalog=lambda: catalog)
    # Both halves, composed together. Without the API provider every route
    # answers SERVICE_NOT_READY - the public ones too, because FastAPI
    # resolves require_access's dependency before the handler runs.
    #
    # The bearer token is WP-16's development static token, sent by default
    # because seven of the eleven routes require a principal and a suite that
    # silently got 401 everywhere would be asserting nothing. Pass
    # ``authenticated=False`` to exercise the refusal itself.
    from tests.fixtures.wp16.synthetic import TEST_DEMO_TOKEN

    headers = {"Authorization": "Bearer " + TEST_DEMO_TOKEN} \
        if authenticated else {}
    return TestClient(create_web_app(settings, provider,
                                     api_provider=api_provider),
                      headers=headers, raise_server_exceptions=False)


@unittest.skipIf(_MISSING, SKIP_REASON)
class TestTheInterfaceComposes(unittest.TestCase):  # pragma: no cover

    def test_importing_the_application_opens_no_connection(self):
        import apps.web.main as main
        self.assertIsNotNone(main.app)

    def test_the_web_application_publishes_no_openapi_document(self):
        # A page is not an interface contract. Asking for a schema of the
        # pages must 404 rather than describe them, or a client will start
        # treating rendered HTML as a stable surface.
        from tests.unit.web._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        client = _client(world)
        for path in ("/openapi.json", "/docs", "/redoc"):
            self.assertEqual(client.get(path).status_code, 404, path)

    def test_the_combined_application_serves_both_and_confuses_neither(self):
        from apps.api.artifacts import load_openapi_document
        from apps.api.openapi import compare_documents
        from apps.web.factory import create_combined_app
        from apps.web.routes import WEB_ROUTES
        from fastapi.testclient import TestClient

        from tests.fixtures.wp16.synthetic import synthetic_provider
        from tests.fixtures.wp17.synthetic import (synthetic_web_provider,
                                                   test_web_settings)
        from tests.unit.web._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        settings = test_web_settings()
        app = create_combined_app(
            api_settings=settings.api,
            api_provider=synthetic_provider(world, settings=settings.api),
            web_provider=synthetic_web_provider(world, settings=settings))
        client = TestClient(app, raise_server_exceptions=False)

        # Surface comparison, not byte equality: the committed artifact is a
        # declaration and always carries an unverified attestation, while a
        # served document carries the current one from recorded evidence.
        # `compare_documents` ignores exactly that field and nothing else, so
        # this still fails on any real difference between the API the
        # combined deployment serves and the API the artifact describes.
        served = client.get("/openapi.json").json()
        identical, differences = compare_documents(served,
                                                   load_openapi_document())
        self.assertTrue(identical, "\n".join(differences[:10]))

        page_paths = {route.path for route in WEB_ROUTES}
        self.assertEqual(page_paths & set(served["paths"]), set())


@unittest.skipIf(_MISSING, SKIP_REASON)
class TestEveryPageIsReachable(unittest.TestCase):  # pragma: no cover

    def test_every_get_route_in_the_table_answers(self):
        from apps.web.routes import WEB_ROUTES
        from tests.unit.web._support import synthetic_world

        substitutions = {"case_id": CATALOG_CASE_ID,
                         "assessment_id": "", "evidence_id": ""}
        world = synthetic_world()
        self.addCleanup(world.close)
        client = _client(world)
        for route in WEB_ROUTES:
            if route.method != "GET":
                continue
            path = route.path
            skip = False
            for parameter in route.parameters:
                value = substitutions.get(parameter.name, "")
                if not value:
                    # Identifiers this fixture cannot know ahead of a
                    # submission are covered by the flow test below.
                    skip = True
                    break
                path = path.replace("{%s}" % parameter.name, value)
            if skip:
                continue
            # The token has to match the route's policy, or a route
            # restricted to one role answers 403 and the loop proves only
            # that the refusal works. The expert-review screen is the one
            # route not open to a demo user.
            from tests.fixtures.wp16.synthetic import (TEST_DEMO_TOKEN,
                                                       TEST_REVIEWER_TOKEN)

            token = (TEST_REVIEWER_TOKEN
                     if route.access.role_names == ("EXPERT_REVIEWER",)
                     else TEST_DEMO_TOKEN)
            response = client.get(
                path, headers={"Authorization": "Bearer " + token})
            self.assertEqual(response.status_code, 200, path)
            self.assertTrue(
                response.headers["content-type"].startswith("text/html"),
                path)

    def test_an_unknown_page_renders_html_rather_than_a_json_envelope(self):
        from tests.unit.web._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        response = _client(world).get("/no-such-page")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(
            response.headers["content-type"].startswith("text/html"))
        self.assertIn("<html", response.text)

    def test_an_unknown_case_renders_the_error_page_not_a_stack_trace(self):
        from tests.unit.web._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        response = _client(world).get("/cases/WP17-CASE-DOES-NOT-EXIST")
        self.assertEqual(response.status_code, 404)
        self.assertIn("RESOURCE_NOT_FOUND", response.text)
        self.assertNotIn("Traceback", response.text)


@unittest.skipIf(_MISSING, SKIP_REASON)
class TestTheResponsesCarryTheContract(unittest.TestCase):  # pragma: no cover

    def test_every_page_carries_the_security_headers(self):
        from apps.web.security import security_headers
        from tests.unit.web._support import synthetic_world

        expected = security_headers()
        world = synthetic_world()
        self.addCleanup(world.close)
        response = _client(world).get("/")
        for header, value in expected.items():
            self.assertEqual(response.headers.get(header), value, header)

    def test_every_page_carries_the_canonical_warning(self):
        from pgx.domain.claims import canonical_clinical_warning
        from tests.unit.web._support import synthetic_world

        warning = canonical_clinical_warning("tr")
        world = synthetic_world()
        self.addCleanup(world.close)
        client = _client(world)
        for path in ("/", "/login", "/cases", "/validation", "/system"):
            self.assertIn(warning, client.get(path).text, path)

    def test_the_content_security_policy_permits_no_remote_origin(self):
        from tests.unit.web._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        policy = _client(world).get("/").headers["Content-Security-Policy"]
        self.assertNotIn("http://", policy)
        self.assertNotIn("https://", policy)
        # Deny by default, then name the few sources this origin serves
        # itself. `default-src 'self'` would silently permit whole classes of
        # subresource the interface has no use for.
        self.assertIn("default-src 'none'", policy)
        self.assertIn("script-src 'self'", policy)
        self.assertIn("style-src 'self'", policy)
        self.assertIn("frame-ancestors 'none'", policy)

    def test_the_static_mount_serves_the_two_local_assets_and_no_listing(self):
        from tests.unit.web._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        client = _client(world)
        self.assertEqual(client.get("/static/css/app.css").status_code, 200)
        self.assertEqual(client.get("/static/js/app.js").status_code, 200)
        self.assertNotEqual(client.get("/static/").status_code, 200)
        self.assertNotEqual(
            client.get("/static/../factory.py").status_code, 200)


@unittest.skipIf(_MISSING, SKIP_REASON)
class TestTheFormBoundary(unittest.TestCase):  # pragma: no cover

    def test_a_post_without_a_csrf_token_is_refused(self):
        from tests.unit.web._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        client = _client(world, with_csrf=True)
        response = client.post("/cases/%s/assess" % CATALOG_CASE_ID,
                               data={"medications": ["DRUG:testdrug-alpha"]})
        self.assertEqual(response.status_code, 403)

    def test_a_post_with_the_token_produces_an_assessment_page(self):
        from tests.fixtures.wp17.synthetic import TEST_CSRF_TOKEN
        from tests.unit.web._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        client = _client(world, with_csrf=True)
        response = client.post(
            "/cases/%s/assess" % CATALOG_CASE_ID,
            data={"csrf_token": TEST_CSRF_TOKEN,
                  "medications": ["DRUG:testdrug-alpha"]})
        self.assertEqual(response.status_code, 200)
        self.assertIn("<html", response.text)

    def test_the_form_is_absent_when_no_csrf_verifier_is_configured(self):
        # The repository's real state: WP-23 has not happened, so the page
        # must render the control disabled rather than offer a form that
        # fails after the operator has filled it in.
        from tests.unit.web._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        client = _client(world, with_csrf=False)
        page = client.get("/cases/%s" % CATALOG_CASE_ID).text
        self.assertIn("disabled", page)

    def test_an_oversized_form_body_is_refused_before_it_is_parsed(self):
        from tests.fixtures.wp17.synthetic import TEST_CSRF_TOKEN
        from tests.unit.web._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        client = _client(world, with_csrf=True)
        response = client.post(
            "/cases/%s/assess" % CATALOG_CASE_ID,
            data={"csrf_token": TEST_CSRF_TOKEN,
                  "medications": ["DRUG:x" * 4096] * 64})
        self.assertNotEqual(response.status_code, 200)

    def test_no_route_accepts_free_text_or_an_uploaded_file(self):
        # Structural rather than behavioural: the signatures are read, so a
        # future route that adds a text area fails here even if no test
        # thinks to post to it.
        import inspect

        from apps.web.routers import pages as router_module

        for name, function in vars(router_module).items():
            if not callable(function) or name.startswith("_"):
                continue
            for parameter in inspect.signature(function).parameters.values():
                annotation = str(parameter.annotation)
                self.assertNotIn("UploadFile", annotation, name)
                self.assertNotIn("File", annotation.split("[")[0], name)


@unittest.skipIf(_MISSING, SKIP_REASON)
class TestTheFlowOverHttp(unittest.TestCase):  # pragma: no cover
    """The unit flow test's route, driven over HTTP instead of in process."""

    def test_a_case_becomes_an_assessment_and_then_evidence(self):
        import re

        from tests.fixtures.wp17.synthetic import TEST_CSRF_TOKEN
        from tests.unit.web._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        client = _client(world, with_csrf=True, covered=True)

        listing = client.get("/cases")
        self.assertEqual(listing.status_code, 200)
        self.assertIn(COVERED_CASE_ID, listing.text)

        detail = client.get("/cases/%s" % COVERED_CASE_ID)
        self.assertEqual(detail.status_code, 200)

        assessment = client.post(
            "/cases/%s/assess" % COVERED_CASE_ID,
            data={"csrf_token": TEST_CSRF_TOKEN,
                  "medications": ["DRUG:testdrug-alpha"]})
        self.assertEqual(assessment.status_code, 200)

        links = re.findall(r'href="(/evidence/[^"]+)"', assessment.text)
        for link in links:
            page = client.get(link)
            self.assertEqual(page.status_code, 200, link)
            self.assertIn("<html", page.text)


@unittest.skipIf(_MISSING, SKIP_REASON)
class TestTheCombinedAppAnswersInEachSurfacesShape(unittest.TestCase):
    """One process, two contracts, and the error handler has to know which.

    FastAPI keeps one handler per exception type, so the interface's HTML
    handlers replace the API's JSON ones when both are mounted on the same
    application. Unqualified, that turned every API failure into an HTML page:
    ``GET /api/v1/system/version`` on an unconfigured deployment answered
    ``503 text/html``, and a client parsing it for a governed code got a
    syntax error instead.

    The API contract's one unconditional promise is that an API path always
    answers with the JSON error envelope. These pin it.
    """

    def _combined(self, world):
        from apps.web.factory import create_combined_app
        from fastapi.testclient import TestClient

        from tests.fixtures.wp16.synthetic import synthetic_provider
        from tests.fixtures.wp17.synthetic import (synthetic_providers,
                                                   test_web_settings)

        settings = test_web_settings()
        web_provider, _api = synthetic_providers(world, settings=settings)
        app = create_combined_app(
            api_settings=settings.api,
            api_provider=synthetic_provider(world, settings=settings.api),
            web_provider=web_provider)
        return TestClient(app, raise_server_exceptions=False)

    def test_an_unknown_api_path_answers_with_a_json_envelope(self):
        from tests.unit.web._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        response = self._combined(world).get("/api/v1/no-such-thing")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(response.headers["content-type"].startswith(
            "application/json"))
        self.assertEqual(response.json()["error"]["code"],
                         "RESOURCE_NOT_FOUND")

    def test_an_unknown_page_path_answers_with_html(self):
        from tests.unit.web._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        response = self._combined(world).get("/no-such-page")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(response.headers["content-type"].startswith(
            "text/html"))
        self.assertIn("<html", response.text)

    def test_an_unauthenticated_api_call_answers_with_a_json_envelope(self):
        from tests.unit.web._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        response = self._combined(world).get("/api/v1/drugs")
        self.assertTrue(response.headers["content-type"].startswith(
            "application/json"))
        self.assertIn("error", response.json())

    def test_a_health_path_is_never_rendered_as_a_page(self):
        from tests.unit.web._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        for path in ("/health/live", "/health/ready"):
            with self.subTest(path=path):
                response = self._combined(world).get(path)
                self.assertTrue(response.headers["content-type"].startswith(
                    "application/json"), path)

    def test_the_split_follows_the_reserved_prefixes(self):
        """The two answers come from one declaration, so they cannot drift.

        A page may not live under a reserved prefix; a failure under one is
        therefore not a page's failure. Same table, both directions.
        """
        import inspect

        from apps.web import factory
        from apps.web.routes import RESERVED_PATH_PREFIXES

        source = inspect.getsource(factory._install_error_handler)
        self.assertIn("RESERVED_PATH_PREFIXES", source)
        self.assertIn("/api/", RESERVED_PATH_PREFIXES)
        self.assertIn("/health/", RESERVED_PATH_PREFIXES)
