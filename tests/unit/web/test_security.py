# -*- coding: utf-8 -*-
"""The security boundary: CSRF, redirects, headers, and what a form may say.

WP-23 supplies sessions and a real CSRF mechanism. What is checked here is
that WP-17 left a correctly-shaped hole rather than an open one: the verifier
refuses by default, redirects are route names rather than paths, no form
carries an actor or a role, and no page displays a credential.
"""

from __future__ import annotations

import unittest

from apps.api.config import ApiConfigurationError, Environment
from apps.web.config import WebSettings, load_web_settings
from apps.web.errors import WebError
from apps.web.routes import (STATE_CHANGING_ROUTES, WEB_ROUTES,
                             WEB_ROUTES_BY_NAME, web_route)
from apps.web.security import (CSRF_FIELD_NAME, SECURITY_HEADERS, CsrfError,
                               RedirectRefusedError, StaticTokenCsrfVerifier,
                               UnconfiguredCsrf, safe_redirect,
                               security_headers)
from apps.web.submission import build_assessment_request
from tests.fixtures.wp17.synthetic import (TEST_CSRF_TOKEN, case_by_id,
                                           test_web_settings)


class TestCsrfFailsClosed(unittest.TestCase):

    def test_the_default_verifier_refuses_every_token(self):
        verifier = UnconfiguredCsrf()
        for token in (None, "", "anything", TEST_CSRF_TOKEN):
            with self.subTest(token=repr(token)):
                with self.assertRaises(CsrfError) as caught:
                    verifier.verify(token)
                self.assertEqual(caught.exception.code, "CSRF_NOT_CONFIGURED")

    def test_the_default_verifier_issues_no_token(self):
        self.assertIsNone(UnconfiguredCsrf().issue())
        self.assertFalse(UnconfiguredCsrf().configured)

    def test_production_can_never_declare_csrf_configured(self):
        with self.assertRaises(ApiConfigurationError):
            WebSettings(api=load_web_settings({}).api, csrf_configured=True)

    def test_no_environment_variable_enables_csrf(self):
        settings = load_web_settings({"PGX_WEB_CSRF_CONFIGURED": "true",
                                      "PGX_API_ENV": "TEST"})
        self.assertFalse(settings.csrf_configured)

    def test_forms_are_unavailable_without_both_dependencies(self):
        settings = test_web_settings()
        self.assertFalse(settings.state_changing_routes_available)

    def test_the_development_verifier_compares_the_whole_token(self):
        verifier = StaticTokenCsrfVerifier(TEST_CSRF_TOKEN)
        verifier.verify(TEST_CSRF_TOKEN)
        for wrong in (TEST_CSRF_TOKEN[:-1], TEST_CSRF_TOKEN + "x", "",
                      None, TEST_CSRF_TOKEN.lower(),
                      TEST_CSRF_TOKEN.replace("WP17", "WP18")):
            with self.subTest(token=repr(wrong)):
                with self.assertRaises(CsrfError):
                    verifier.verify(wrong)

    def test_a_short_development_token_is_refused(self):
        with self.assertRaises(ValueError):
            StaticTokenCsrfVerifier("short")

    def test_every_state_changing_route_declares_csrf(self):
        self.assertTrue(STATE_CHANGING_ROUTES)
        for name in STATE_CHANGING_ROUTES:
            with self.subTest(route=name):
                self.assertTrue(WEB_ROUTES_BY_NAME[name].requires_csrf)

    def test_no_get_route_requires_csrf(self):
        for route in WEB_ROUTES:
            if route.method == "GET":
                with self.subTest(route=route.name):
                    self.assertFalse(route.requires_csrf)


class TestRedirectsCannotLeaveTheApplication(unittest.TestCase):

    def test_a_route_name_resolves(self):
        self.assertEqual(safe_redirect("web.cases"), "/cases")
        self.assertEqual(safe_redirect(None), "/")

    def test_every_open_redirect_shape_is_refused(self):
        for target in ("//evil.example", "https://evil.example",
                       "http:/evil.example", "\\\\evil.example",
                       "/\\evil.example", "javascript:alert(1)",
                       "/cases", "../admin", "%2f%2fevil.example",
                       "https://good.example@evil.example"):
            with self.subTest(target=target):
                with self.assertRaises(RedirectRefusedError):
                    safe_redirect(target)

    def test_a_path_is_refused_even_when_it_is_internal(self):
        """Only names resolve, so there is no path for a parser to get wrong."""
        with self.assertRaises(RedirectRefusedError):
            safe_redirect("/validation")

    def test_no_route_declares_a_next_parameter(self):
        for route in WEB_ROUTES:
            names = {parameter.name for parameter in route.parameters}
            with self.subTest(route=route.name):
                self.assertNotIn("next", names)
                self.assertNotIn("redirect", names)
                self.assertNotIn("return_to", names)


class TestTheHeaderPolicy(unittest.TestCase):

    def test_the_policy_allows_only_this_origin(self):
        policy = SECURITY_HEADERS["Content-Security-Policy"]
        self.assertIn("default-src 'none'", policy)
        self.assertIn("frame-ancestors 'none'", policy)
        self.assertIn("form-action 'self'", policy)
        self.assertIn("base-uri 'none'", policy)

    def test_the_policy_permits_no_inline_or_remote_code(self):
        policy = SECURITY_HEADERS["Content-Security-Policy"]
        for forbidden in ("unsafe-inline", "unsafe-eval", "http:", "https:",
                          "*"):
            with self.subTest(term=forbidden):
                self.assertNotIn(forbidden, policy)

    def test_every_required_header_is_present(self):
        for header in ("X-Content-Type-Options", "X-Frame-Options",
                       "Referrer-Policy", "Permissions-Policy",
                       "Cache-Control", "Cross-Origin-Opener-Policy"):
            with self.subTest(header=header):
                self.assertIn(header, SECURITY_HEADERS)

    def test_responses_are_never_stored(self):
        self.assertEqual(SECURITY_HEADERS["Cache-Control"], "no-store")

    def test_the_permissions_policy_grants_nothing(self):
        policy = SECURITY_HEADERS["Permissions-Policy"]
        for feature in ("camera", "microphone", "geolocation", "payment"):
            with self.subTest(feature=feature):
                self.assertIn("%s=()" % feature, policy)

    def test_the_header_table_cannot_be_mutated_by_a_caller(self):
        headers = security_headers()
        headers["X-Frame-Options"] = "ALLOWALL"
        self.assertEqual(SECURITY_HEADERS["X-Frame-Options"], "DENY")


class TestNoFormCarriesAnIdentityOrFreeText(unittest.TestCase):

    def test_the_submission_builder_takes_no_identity_argument(self):
        import inspect as _inspect
        signature = _inspect.signature(build_assessment_request)
        self.assertEqual(sorted(signature.parameters),
                         ["case", "max_medications", "medications"])

    def test_the_built_request_carries_no_actor_or_role(self):
        document = build_assessment_request(
            case_by_id("WP17-CASE-P1"),
            medications=["DRUG:testdrug-alpha"])
        for forbidden in ("actor", "role", "principal", "input_hash",
                          "output_hash", "release_provenance", "attention",
                          "coverage", "findings"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, document)

    def test_the_built_request_carries_no_clinical_or_personal_field(self):
        document = build_assessment_request(
            case_by_id("WP17-CASE-P1"),
            medications=["DRUG:testdrug-alpha"])
        rendered = repr(document)
        for forbidden in ("patient", "genotype", "diplotype", "vcf", "ehr",
                          "diagnosis", "indication", "dose", "narrative",
                          "mrn", "date_of_birth"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, rendered)

    def test_a_medication_that_is_not_a_canonical_key_is_refused(self):
        for value in ("<script>alert(1)</script>", "aspirin", "DRUG:",
                      "drug:lowercase-prefix", "../../etc/passwd",
                      "DRUG:x" + "y" * 100):
            with self.subTest(value=value):
                with self.assertRaises(WebError) as caught:
                    build_assessment_request(case_by_id("WP17-CASE-P1"),
                                             medications=[value])
                self.assertEqual(caught.exception.code,
                                 "REQUEST_CONTRACT_VIOLATION")

    def test_a_refusal_never_echoes_the_rejected_value(self):
        payload = "<script>alert('SECRET')</script>"
        with self.assertRaises(WebError) as caught:
            build_assessment_request(case_by_id("WP17-CASE-P1"),
                                     medications=[payload])
        self.assertNotIn("SECRET", repr(caught.exception.details))
        self.assertNotIn("script", repr(caught.exception.details))

    def test_selected_medications_are_sorted_not_ordered_by_the_caller(self):
        document = build_assessment_request(
            case_by_id("WP17-CASE-P1"),
            medications=["DRUG:testdrug-beta", "DRUG:testdrug-alpha"])
        self.assertEqual(document["medications"],
                         ["DRUG:testdrug-alpha", "DRUG:testdrug-beta"])

    def test_the_form_field_name_is_the_declared_one(self):
        self.assertEqual(CSRF_FIELD_NAME, "csrf_token")


class TestBoundedInput(unittest.TestCase):

    def test_the_form_limit_is_small_and_bounded(self):
        settings = load_web_settings({})
        self.assertLessEqual(settings.max_form_bytes, 65536)
        self.assertGreaterEqual(settings.max_form_bytes, 512)

    def test_an_unbounded_form_limit_is_refused(self):
        with self.assertRaises(ApiConfigurationError):
            load_web_settings({"PGX_WEB_MAX_FORM_BYTES": "10000000"})

    def test_every_path_parameter_is_patterned_and_bounded(self):
        for route in WEB_ROUTES:
            for parameter in route.parameters:
                with self.subTest(route=route.name, param=parameter.name):
                    if parameter.kind == "string":
                        self.assertIsNotNone(parameter.pattern)
                        self.assertIsNotNone(parameter.max_length)
                        self.assertLessEqual(parameter.max_length, 128)

    def test_too_many_medications_are_refused(self):
        with self.assertRaises(WebError):
            build_assessment_request(
                case_by_id("WP17-CASE-P1"),
                medications=["DRUG:testdrug-%03d" % index
                             for index in range(40)],
                max_medications=32)


class TestConfigurationLeaksNothing(unittest.TestCase):

    def test_the_settings_object_holds_no_connection_string(self):
        settings = load_web_settings(
            {"DATABASE_URL": "postgresql://pgx:hunter2@db:5432/pgx"})
        self.assertNotIn("hunter2", repr(settings))
        self.assertNotIn("postgresql://", repr(settings))

    def test_the_public_summary_holds_no_secret(self):
        import json
        settings = load_web_settings(
            {"DATABASE_URL": "postgresql://pgx:hunter2@db:5432/pgx"})
        self.assertNotIn("hunter2",
                         json.dumps(dict(settings.public_summary())))

    def test_a_configuration_error_never_quotes_its_value(self):
        secret = "postgresql://pgx:hunter2@db:5432/pgx"
        with self.assertRaises(ApiConfigurationError) as caught:
            load_web_settings({"PGX_WEB_MAX_FORM_BYTES": secret})
        self.assertNotIn("hunter2", str(caught.exception))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
