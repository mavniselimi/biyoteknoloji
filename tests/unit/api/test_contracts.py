# -*- coding: utf-8 -*-
"""B. The request and response contracts.

Two layers are checked. The declarative contract and its validator run here,
so every bound, pattern, vocabulary and prohibition is tested by execution.
The generated Pydantic layer cannot be imported in this environment, so it is
checked by reading it: that it declares a model for every contract model, that
it forbids extra fields, and that it never falls back to an untyped mapping.
"""

from __future__ import annotations

import ast
import unittest

from apps.api.contracts.spec import (CONTRACT_VERSION, CONTROL_CHARACTER_RANGES,
                                     LIMITS, MODELS, PROHIBITED_REQUEST_FIELDS)
from apps.api.contracts.validate import (ContractViolation, Issue,
                                         contains_control_character,
                                         find_prohibited_fields,
                                         validate_document)
from tests.fixtures.wp16.synthetic import create_request
from tests.unit.api._support import module_path, source, tree

#: Every kind of input §6 requires the contract to refuse, recursively.
REFUSED_KINDS = (
    "genotype", "diplotype", "star_allele", "alleles", "activity_score",
    "vcf", "vcf_path", "ehr", "ehr_id", "patient_name", "date_of_birth",
    "mrn", "clinical_notes", "narrative", "diagnosis", "indication", "dose",
    "dosage", "actor", "role", "attention", "coverage", "findings",
    "evidence_references", "rule_id", "rule_version", "input_hash",
    "output_hash", "report_hash", "release_provenance",
)


class TestTheContractIsVersionedAndClosed(unittest.TestCase):

    def test_the_contract_is_versioned(self):
        self.assertEqual(CONTRACT_VERSION, "pgx-api-contract/1")

    def test_every_model_names_at_least_one_field(self):
        for name, model in MODELS.items():
            with self.subTest(model=name):
                self.assertTrue(model.fields)

    def test_every_referenced_model_exists(self):
        for name, model in MODELS.items():
            for field in model.fields:
                for reference in (field.model, field.item_model):
                    if reference:
                        with self.subTest(model=name, field=field.name):
                            self.assertIn(reference, MODELS)

    def test_no_field_is_an_untyped_mapping(self):
        for name, model in MODELS.items():
            for field in model.fields:
                if field.kind == "object":
                    with self.subTest(model=name, field=field.name):
                        self.assertIsNotNone(field.model)

    def test_every_string_field_is_bounded(self):
        for name, model in MODELS.items():
            for field in model.fields:
                if field.kind == "string":
                    with self.subTest(model=name, field=field.name):
                        self.assertIsNotNone(field.max_length)

    def test_every_collection_is_bounded(self):
        for name, model in MODELS.items():
            for field in model.fields:
                if field.kind == "array":
                    with self.subTest(model=name, field=field.name):
                        self.assertIsNotNone(field.max_items)

    def test_every_enum_field_lists_a_governed_vocabulary(self):
        for name, model in MODELS.items():
            for field in model.fields:
                if field.kind == "enum":
                    with self.subTest(model=name, field=field.name):
                        self.assertTrue(field.enum_values)
                if field.item_kind == "enum":
                    with self.subTest(model=name, field=field.name):
                        self.assertTrue(field.item_enum_values)


class TestProhibitedInput(unittest.TestCase):
    """Every refused kind is refused, at any depth, without being echoed."""

    def test_every_required_field_name_is_prohibited(self):
        for name in REFUSED_KINDS:
            with self.subTest(field=name):
                self.assertIn(name, PROHIBITED_REQUEST_FIELDS)

    def test_a_prohibited_field_is_found_at_the_top_level(self):
        document = dict(create_request(), genotype="*1/*2")
        self.assertEqual(find_prohibited_fields(document), ("$.genotype",))

    def test_a_prohibited_field_is_found_inside_a_nested_object(self):
        document = create_request()
        document["profile"]["observations"][0]["diplotype"] = "*1/*17"
        self.assertEqual(find_prohibited_fields(document),
                         ("$.profile.observations[0].diplotype",))

    def test_a_prohibited_field_is_found_inside_an_unexpected_container(self):
        document = dict(create_request(), extra=[{"vcf_path": "/tmp/x.vcf"}])
        self.assertEqual(find_prohibited_fields(document),
                         ("$.extra[0].vcf_path",))

    def test_a_prohibited_request_is_refused_as_a_whole(self):
        """Its other problems are not reported: nothing about a request
        carrying a genotype should read as partly acceptable."""
        document = dict(create_request(), genotype="*1/*2", surprise=1,
                        mode="NOT-A-MODE")
        with self.assertRaises(ContractViolation) as caught:
            validate_document("AssessmentCreateRequest", document)
        self.assertEqual(caught.exception.codes, ("PROHIBITED_FIELD",))

    def test_the_rejected_value_is_never_echoed(self):
        secret = "SECRET-VALUE-THAT-MUST-NOT-COME-BACK"
        document = dict(create_request(), patient_name=secret)
        with self.assertRaises(ContractViolation) as caught:
            validate_document("AssessmentCreateRequest", document)
        rendered = repr(caught.exception.to_json()) + str(caught.exception)
        self.assertNotIn(secret, rendered)

    def test_the_prohibition_applies_to_requests_only(self):
        """A response carries attention, coverage, findings and hashes by
        definition; refusing them there would refuse every valid answer."""
        request_models = [name for name, model in MODELS.items()
                          if model.direction == "request"]
        response_models = [name for name, model in MODELS.items()
                           if model.direction == "response"]
        self.assertTrue(request_models and response_models)
        for name in response_models:
            model = MODELS[name]
            overlap = {field.name for field in model.fields} \
                & set(PROHIBITED_REQUEST_FIELDS)
            if overlap:
                break
        else:  # pragma: no cover - the contract would have to change
            self.fail("no response model carries a request-prohibited name, "
                      "so this test proves nothing")


class TestControlCharacters(unittest.TestCase):

    def test_the_ranges_cover_c0_c1_and_the_separators(self):
        self.assertIn((0x00, 0x08), CONTROL_CHARACTER_RANGES)
        self.assertIn((0x7F, 0x9F), CONTROL_CHARACTER_RANGES)
        self.assertIn((0x2028, 0x2029), CONTROL_CHARACTER_RANGES)

    def test_control_characters_are_detected(self):
        for value in ("a\x00b", "a\x07b", "a\x1fb", "a\x7fb", "a b"):
            with self.subTest(value=repr(value)):
                self.assertTrue(contains_control_character(value))

    def test_ordinary_text_is_not(self):
        for value in ("TEST-CASE-1", "GENE:TESTGENE1", "a b", "ü"):
            with self.subTest(value=value):
                self.assertFalse(contains_control_character(value))

    def test_a_control_character_refuses_the_document(self):
        with self.assertRaises(ContractViolation) as caught:
            validate_document("AssessmentCreateRequest",
                              dict(create_request(), case_id="a\x07b"))
        self.assertEqual(caught.exception.codes, ("CONTROL_CHARACTER",))


class TestRequestValidation(unittest.TestCase):

    def test_the_synthetic_request_validates(self):
        self.assertTrue(validate_document("AssessmentCreateRequest",
                                          create_request()))

    def test_an_unknown_field_is_refused(self):
        with self.assertRaises(ContractViolation) as caught:
            validate_document("AssessmentCreateRequest",
                              dict(create_request(), surprise=1))
        self.assertEqual(caught.exception.codes, ("UNKNOWN_FIELD",))

    def test_a_missing_required_field_is_refused(self):
        document = create_request()
        del document["medications"]
        with self.assertRaises(ContractViolation) as caught:
            validate_document("AssessmentCreateRequest", document)
        self.assertEqual(caught.exception.codes, ("FIELD_REQUIRED",))

    def test_an_ungoverned_mode_is_refused(self):
        with self.assertRaises(ContractViolation) as caught:
            validate_document("AssessmentCreateRequest",
                              create_request(mode="CLINICAL"))
        self.assertEqual(caught.exception.codes, ("ENUM_INVALID",))

    def test_duplicate_medications_are_refused(self):
        with self.assertRaises(ContractViolation) as caught:
            validate_document(
                "AssessmentCreateRequest",
                create_request(medications=["DRUG:testdrug-alpha",
                                            "DRUG:testdrug-alpha"]))
        self.assertEqual(caught.exception.codes, ("DUPLICATE_ITEM",))

    def test_too_many_medications_are_refused(self):
        many = ["DRUG:testdrug-%03d" % index
                for index in range(LIMITS["max_medications"] + 1)]
        with self.assertRaises(ContractViolation) as caught:
            validate_document("AssessmentCreateRequest",
                              create_request(medications=many))
        self.assertEqual(caught.exception.codes, ("TOO_MANY_ITEMS",))

    def test_a_malformed_release_id_is_refused(self):
        with self.assertRaises(ContractViolation) as caught:
            validate_document(
                "AssessmentCreateRequest",
                create_request(requested_release_public_id="not-a-release"))
        self.assertEqual(caught.exception.codes, ("PATTERN_MISMATCH",))

    def test_issues_are_reported_in_a_deterministic_order(self):
        document = create_request()
        document["zeta"] = 1
        document["alpha"] = 1
        with self.assertRaises(ContractViolation) as caught:
            validate_document("AssessmentCreateRequest", document)
        locations = [issue.location for issue in caught.exception.issues]
        self.assertEqual(locations, sorted(locations))

    def test_details_are_bounded(self):
        document = create_request()
        for index in range(LIMITS["max_detail_entries"] * 3):
            document["extra%03d" % index] = 1
        with self.assertRaises(ContractViolation) as caught:
            validate_document("AssessmentCreateRequest", document)
        self.assertLessEqual(len(caught.exception.to_json()["issues"]),
                             LIMITS["max_detail_entries"])


class TestIdentifierAndDigestFormats(unittest.TestCase):

    def test_a_malformed_uuid_is_refused(self):
        for value in ("not-a-uuid", "11111111-1111-4111-8111-11111111111",
                      "{11111111-1111-4111-8111-111111111111}"):
            with self.subTest(value=value):
                with self.assertRaises(ContractViolation) as caught:
                    validate_document("ErrorBody",
                                      {"code": "INTERNAL_ERROR",
                                       "message": "x", "details": {},
                                       "request_id": value})
                self.assertIn("UUID_INVALID", caught.exception.codes)

    def test_a_malformed_digest_is_refused(self):
        document = {"attention": "MEDIUM", "coverage": "FULL",
                    "coverage_reason_codes": []}
        self.assertTrue(validate_document("StatusBlock", document))
        with self.assertRaises(ContractViolation) as caught:
            validate_document("ReleaseProvenanceResponse", {
                "release_public_id": "PGX-REL-20990101-001",
                "release_manifest_hash": "sha256:NOTHEX",
                "software_version": "0.0.0", "software_source_tree_hash":
                    "sha256:" + "a" * 64,
                "dataset_public_id": "PGX-DATA-20990101-001",
                "canonical_build_content_hash": "sha256:" + "a" * 64,
                "ruleset_public_id": "PGX-RULESET-20990101-001",
                "ruleset_content_hash": "sha256:" + "a" * 64,
                "evidence_build_key": "TEST/1",
                "evidence_build_content_hash": "sha256:" + "a" * 64,
                "coverage_manifest_hash": "sha256:" + "a" * 64,
                "protocol_version": "p/1",
                "protocol_content_hash": "sha256:" + "a" * 64,
                "source_policy_version": "s/1",
                "source_policy_content_hash": "sha256:" + "a" * 64})
        self.assertIn("DIGEST_INVALID", caught.exception.codes)


class TestGeneratedPydanticLayer(unittest.TestCase):
    """Read, not executed: Pydantic is not installable in this environment.

    What is asserted is that the generator covers the whole contract and
    cannot silently produce a permissive model - not that Pydantic behaves,
    which is Pydantic's business.
    """

    def setUp(self):
        self.path = module_path("contracts/models.py")
        self.text = source(self.path)
        self.tree = tree(self.path)

    def test_models_are_generated_from_the_contract_declaration(self):
        self.assertIn("from apps.api.contracts.spec import", self.text)
        self.assertIn("create_model", self.text)

    def test_every_model_is_generated(self):
        """The generator walks ``MODELS``, so coverage is structural: it
        cannot omit one without omitting all."""
        found = [node for node in ast.walk(self.tree)
                 if isinstance(node, ast.FunctionDef)
                 and node.name == "rebuild_models"]
        self.assertEqual(len(found), 1)
        self.assertIn("_dependency_order()", ast.unparse(found[0]))

    def test_extra_fields_are_forbidden(self):
        self.assertIn('extra="forbid"', self.text)

    def test_identifiers_are_patterned_strings_rather_than_uuid_objects(self):
        names = {node.id for node in ast.walk(self.tree)
                 if isinstance(node, ast.Name)}
        self.assertNotIn("UUID", names)
        self.assertIn("_UUID_PATTERN", names)

    def test_no_untyped_mapping_annotation_is_generated(self):
        self.assertNotIn("Dict[str, Any]]", self.text.replace(
            "Dict[str, Any] = ", ""))

    def test_control_characters_are_rejected_by_a_validator(self):
        self.assertIn("contains_control_character", self.text)
        self.assertIn("field_validator", self.text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
