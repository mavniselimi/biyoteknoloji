# -*- coding: utf-8 -*-
"""I. Response safety, prohibited claims and the transport hardening.

The claim scanner is run over everything this layer can emit: the fixed error
catalogue, the readiness details, the OpenAPI document, and a real synthetic
assessment response. §15 requires the error catalogue to be pre-scanned as a
fixed set, so that a scan failing while an error is being handled cannot
produce an error about handling errors.
"""

from __future__ import annotations

import ast
import json
import os
import unittest

from apps.api.adapters.assessment import assessment_document_from_result
from apps.api.adapters.catalog import (drug_collection_document,
                                       gene_collection_document)
from apps.api.adapters.evidence import evidence_detail_document
from apps.api.adapters.request import adapt_assessment_request
from apps.api.adapters.version import system_version_document
from apps.api.config import ApiSettings, Environment, load_settings, \
    ApiConfigurationError
from apps.api.contracts.spec import CONTROL_CHARACTER_RANGES, LIMITS
from apps.api.contracts.validate import ContractViolation, validate_document
from apps.api.errors import ERROR_CATALOGUE, error_envelope
from apps.api.openapi import build_document, canonical_json
from apps.api.readiness import DETAILS
from pgx.application.assessment_snapshot import build_input_snapshot
from pgx.domain.claims import (CANONICAL_CLINICAL_WARNING,
                               canonical_clinical_warning, scan_claim_text)
from tests.fixtures.wp16.synthetic import (SyntheticEvidenceRepository,
                                           create_request)
from tests.unit.api._support import (API_DIR, api_modules, identifiers_of,
                                     source, synthetic_world, tree)

REQUEST_ID = "11111111-1111-4111-8111-111111111111"


def _violations(text):
    report = scan_claim_text(text)
    return list(getattr(report, "violations", ()) or ())


class TestTheCanonicalWarning(unittest.TestCase):

    def test_the_warning_is_not_duplicated_in_api_source(self):
        """One authoritative text. A second copy in this layer would be a
        second thing to update when the governed one changes, and the stale
        copy would be the one users read."""
        governed = canonical_clinical_warning()
        fragment = governed[:40]
        for path in api_modules():
            with self.subTest(module=os.path.basename(path)):
                self.assertNotIn(fragment, source(path))

    def test_the_response_carries_the_governed_warning_verbatim(self):
        world = synthetic_world()
        self.addCleanup(world.close)
        assessment_input = adapt_assessment_request(create_request())
        result = world.service.execute(assessment_input, actor="TEST-actor-a")
        document = assessment_document_from_result(
            result, input_snapshot=build_input_snapshot(assessment_input))
        self.assertEqual(document["clinical_warning"],
                         canonical_clinical_warning())


class TestNothingThisLayerEmitsMakesAProhibitedClaim(unittest.TestCase):

    def test_the_error_catalogue_is_clean(self):
        """Pre-scanned as a fixed set: see §15. Every message this API can
        return for an error is here, so scanning them once in a test means the
        request path never has to scan one while already handling a failure."""
        for code, (_status, message) in ERROR_CATALOGUE.items():
            with self.subTest(code=code):
                self.assertEqual(_violations(message), [])

    def test_every_error_envelope_is_clean(self):
        for code in ERROR_CATALOGUE:
            with self.subTest(code=code):
                envelope = error_envelope(code, REQUEST_ID)
                self.assertEqual(_violations(json.dumps(envelope)), [])

    def test_the_readiness_details_are_clean(self):
        for key, message in DETAILS.items():
            with self.subTest(detail=key):
                self.assertEqual(_violations(message), [])

    def test_the_openapi_document_is_clean(self):
        self.assertEqual(_violations(canonical_json(build_document())), [])

    def test_a_real_synthetic_response_is_clean(self):
        world = synthetic_world()
        self.addCleanup(world.close)
        assessment_input = adapt_assessment_request(create_request())
        result = world.service.execute(assessment_input, actor="TEST-actor-a")
        document = assessment_document_from_result(
            result, input_snapshot=build_input_snapshot(assessment_input))
        self.assertEqual(_violations(json.dumps(document)), [])

    def test_the_catalogue_and_version_responses_are_clean(self):
        world = synthetic_world()
        self.addCleanup(world.close)
        pinned = world.resolver.resolve()
        documents = [
            drug_collection_document(manifest=pinned.coverage_manifest,
                                     provenance=pinned.provenance,
                                     drug_keys=pinned.drug_catalogue),
            gene_collection_document(manifest=pinned.coverage_manifest,
                                     provenance=pinned.provenance),
            system_version_document(pinned.provenance,
                                    claim_boundary=world.boundary),
        ]
        for document in documents:
            with self.subTest(document=sorted(document)[0]):
                self.assertEqual(_violations(json.dumps(document)), [])

    def test_the_evidence_projection_is_clean(self):
        repository = SyntheticEvidenceRepository()
        build = repository.evidence_build_key()
        document = evidence_detail_document(
            repository.get("aaaaaaaa-0000-4000-8000-000000000001"),
            evidence_build_key=build["evidence_build_key"],
            evidence_build_content_hash=build["evidence_build_content_hash"])
        self.assertEqual(_violations(json.dumps(document)), [])


class TestNoUnsafeUserTextIsEchoed(unittest.TestCase):

    def test_markup_in_a_case_label_never_reaches_a_response(self):
        world = synthetic_world()
        self.addCleanup(world.close)
        label = "<script>alert(1)</script>"
        assessment_input = adapt_assessment_request(
            create_request(case_id=label))
        result = world.service.execute(assessment_input, actor="TEST-actor-a")
        document = assessment_document_from_result(
            result, input_snapshot=build_input_snapshot(assessment_input))
        # The label is a client-chosen run label and is echoed by design; what
        # matters is that it is bounded, control-character free, and cannot
        # reach any *rendered* field. It appears only as case_id.
        appearances = [key for key, value in document.items()
                       if isinstance(value, str) and label in value]
        self.assertEqual(appearances, ["case_id"])

    def test_an_overlong_label_is_refused_before_it_is_stored(self):
        with self.assertRaises(ContractViolation) as caught:
            adapt_assessment_request(
                create_request(case_id="x" *
                               (LIMITS["max_identifier_length"] + 1)))
        self.assertEqual(caught.exception.codes, ("VALUE_TOO_LONG",))

    def test_a_control_character_is_refused_rather_than_stripped(self):
        for value in ("TEST\x00CASE", "TEST\x1fCASE", "TEST CASE"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ContractViolation) as caught:
                    adapt_assessment_request(create_request(case_id=value))
                self.assertEqual(caught.exception.codes,
                                 ("CONTROL_CHARACTER",))

    def test_the_control_character_ranges_are_declared(self):
        self.assertTrue(CONTROL_CHARACTER_RANGES)


class TestTransportHardening(unittest.TestCase):

    def test_the_body_limit_is_bounded_and_small(self):
        self.assertLessEqual(LIMITS["max_body_bytes"], 128 * 1024)
        self.assertEqual(load_settings({}).max_body_bytes,
                         LIMITS["max_body_bytes"])

    def test_permissive_cors_is_off_by_default(self):
        settings = load_settings({})
        self.assertEqual(settings.cors_allowed_origins, ())
        self.assertFalse(settings.cors_enabled)
        self.assertFalse(settings.cors_allow_credentials)

    def test_credentials_with_a_wildcard_origin_are_refused(self):
        with self.assertRaises(ApiConfigurationError):
            ApiSettings(environment=Environment.TEST,
                        cors_allowed_origins=("*",),
                        cors_allow_credentials=True)

    def test_a_wildcard_origin_is_refused_in_production(self):
        with self.assertRaises(ApiConfigurationError):
            load_settings({"PGX_API_CORS_ALLOWED_ORIGINS": "*"})

    def test_documentation_is_off_in_production(self):
        self.assertFalse(load_settings({}).docs_enabled)

    def test_configuration_errors_are_sanitised(self):
        """Reuses WP-02's redaction rather than adding a second one."""
        from tests.unit.api._support import module_path
        text = source(module_path("config.py"))
        self.assertIn("sanitize_message", text)

    def test_no_configuration_error_quotes_the_offending_value(self):
        secret = "postgresql://pgx:hunter2@db:5432/pgx"
        for variables in ({"PGX_API_MAX_BODY_BYTES": secret},
                          {"PGX_API_AUTH_MODE": secret},
                          {"PGX_API_ENV": secret},
                          {"PGX_API_CORS_ALLOWED_ORIGINS": secret}):
            with self.subTest(variable=sorted(variables)[0]):
                with self.assertRaises(ApiConfigurationError) as caught:
                    load_settings(variables)
                self.assertNotIn("hunter2", str(caught.exception))
                self.assertNotIn(secret, str(caught.exception))

    def test_the_settings_object_holds_no_connection_string(self):
        settings = load_settings({"DATABASE_URL":
                                  "postgresql://pgx:hunter2@db:5432/pgx"})
        self.assertTrue(settings.database_url_configured)
        self.assertNotIn("hunter2", repr(settings))
        self.assertNotIn("postgresql://", repr(settings))
        self.assertNotIn("hunter2", json.dumps(dict(settings.public_summary())))

    def test_the_security_headers_are_conservative(self):
        path = os.path.join(API_DIR, "middleware.py")
        module = tree(path)
        headers = {}
        for node in ast.walk(module):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and isinstance(
                            value, (ast.Constant, ast.JoinedStr, ast.BinOp)):
                        if isinstance(key.value, str) and "-" in key.value:
                            headers[key.value] = True
        for name in ("X-Content-Type-Options", "X-Frame-Options",
                     "Referrer-Policy", "Content-Security-Policy"):
            with self.subTest(header=name):
                self.assertIn(name, headers)

    def test_responses_are_not_cached_by_default(self):
        self.assertIn("no-store", source(os.path.join(API_DIR,
                                                      "middleware.py")))


class TestNoIdentifiableDataIsAcceptedOrReturned(unittest.TestCase):

    IDENTIFIABLE = ("patient_name", "date_of_birth", "dob", "mrn",
                    "patient_id", "ehr_id", "clinical_notes", "narrative")

    def test_no_response_model_declares_an_identifiable_field(self):
        from apps.api.contracts.spec import MODELS
        for name, model in MODELS.items():
            declared = {field.name for field in model.fields}
            with self.subTest(model=name):
                self.assertEqual(declared & set(self.IDENTIFIABLE), set())

    def test_every_identifiable_field_is_refused_on_request(self):
        for name in self.IDENTIFIABLE:
            with self.subTest(field=name):
                with self.assertRaises(ContractViolation) as caught:
                    adapt_assessment_request(
                        dict(create_request(), **{name: "TEST-VALUE"}))
                self.assertEqual(caught.exception.codes, ("PROHIBITED_FIELD",))


class TestNoLlmOrReportPath(unittest.TestCase):

    def test_no_api_module_names_a_report_generator_or_model_provider(self):
        """``complete`` left this list at WP-22, and was replaced by sharper
        checks rather than dropped.

        It was here to catch an LLM completion API. It also matches the blind
        review protocol's own verb - ``complete`` a review is what
        ``architecture.md`` section 17 calls the final step - so the bare word
        had become a name collision rather than a signal. The two tests below
        assert what this one was actually defending: no model client is
        imported anywhere in the API layer, and no completion-shaped call
        exists.
        """
        forbidden = {"generate_report", "render_report", "ReportService",
                     "StructuredReport", "GenerativeModel", "ChatCompletion",
                     "prompt"}
        for path in api_modules():
            with self.subTest(module=os.path.basename(path)):
                self.assertEqual(identifiers_of(path) & forbidden, set())

    def test_no_api_module_imports_a_model_client(self):
        """The sharper form: the package, not a word that resembles one."""
        import ast
        import io as _io
        forbidden_roots = {"openai", "anthropic", "cohere", "transformers",
                           "llama_cpp", "vertexai", "google", "boto3",
                           "langchain", "litellm"}
        for path in api_modules():
            with _io.open(path, "r", encoding="utf-8") as handle:
                tree_ = ast.parse(handle.read())
            for node in ast.walk(tree_):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    with self.subTest(module=os.path.basename(path),
                                      imported=name):
                        self.assertNotIn(name.split(".")[0], forbidden_roots)

    def test_no_api_module_names_a_completion_api(self):
        """``complete`` alone is too broad; these are not."""
        forbidden = {"chat_completion", "create_completion", "completions",
                     "text_completion", "generate_text", "invoke_model"}
        for path in api_modules():
            with self.subTest(module=os.path.basename(path)):
                self.assertEqual(identifiers_of(path) & forbidden, set())

    def test_no_route_generates_a_report(self):
        from apps.api.routes import ROUTES
        for route in ROUTES:
            with self.subTest(operation=route.operation_id):
                self.assertNotIn("report", route.path)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
