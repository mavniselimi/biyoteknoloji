# -*- coding: utf-8 -*-
"""The WP-15 published schemas, and what they refuse.

``additionalProperties: false`` on the canonical result and the structured
report is where the claim boundary is actually enforced against everything
downstream: a dose, a recommendation, a score, a ranking, a suitability label
or an authored sentence cannot be attached to either document, because the
schema refuses every property it does not name.
"""

from __future__ import annotations

import copy
import io
import json
import os
import unittest

from pgx.application.report_schema import (CANONICAL_RESULT_SCHEMA_PATH,
                                           REPORT_ARTIFACT_MANIFEST_SCHEMA_PATH,
                                           REPORT_FACT_LEDGER_SCHEMA_PATH,
                                           STRUCTURED_REPORT_SCHEMA_PATH,
                                           WP15_GATE_STATUS_SCHEMA_PATH,
                                           WP15_SCHEMA_PATHS, load_schema,
                                           validate_canonical_assessment_result,
                                           validate_report_artifact_manifest,
                                           validate_report_fact_ledger,
                                           validate_structured_report,
                                           validate_wp15_gate_status)
from tests.unit.reporting._support import REPO_ROOT, ReportingCase

#: Keywords the WP-06 validator does not implement. A schema using one would
#: report documents as valid while silently not checking the constraint its
#: author wrote.
UNSUPPORTED_KEYWORDS = ("contains", "minContains", "maxContains",
                        "dependentSchemas", "unevaluatedProperties",
                        "patternProperties")

#: Fields the intended purpose puts outside this product.
FORBIDDEN_FIELDS = ("dose", "dosage", "recommendation", "recommended_drug",
                    "preferred", "safer", "suitability_score", "risk_score",
                    "rank", "ranking", "treatment", "alternative",
                    "diagnosis", "narrative", "prose", "plain_language")


class TestEverySchemaIsPresentAndReadable(unittest.TestCase):

    def test_five_schemas_are_published(self):
        self.assertEqual(len(WP15_SCHEMA_PATHS), 5)
        for path in WP15_SCHEMA_PATHS:
            with self.subTest(schema=os.path.basename(path)):
                self.assertTrue(os.path.isfile(path))

    def test_each_declares_an_id_and_a_dialect(self):
        for path in WP15_SCHEMA_PATHS:
            schema = load_schema(path)
            with self.subTest(schema=os.path.basename(path)):
                self.assertIn("$id", schema)
                self.assertIn("$schema", schema)
                self.assertIn("title", schema)
                self.assertIn("description", schema)

    def test_none_uses_a_keyword_the_validator_cannot_check(self):
        for path in WP15_SCHEMA_PATHS:
            text = json.dumps(load_schema(path))
            with self.subTest(schema=os.path.basename(path)):
                for keyword in UNSUPPORTED_KEYWORDS:
                    self.assertNotIn('"%s"' % keyword, text)

    def test_the_two_that_matter_refuse_unnamed_properties(self):
        for path in (CANONICAL_RESULT_SCHEMA_PATH,
                     STRUCTURED_REPORT_SCHEMA_PATH):
            schema = load_schema(path)
            with self.subTest(schema=os.path.basename(path)):
                self.assertFalse(schema["additionalProperties"])

    def test_no_schema_names_a_prohibited_field(self):
        for path in WP15_SCHEMA_PATHS:
            text = json.dumps(load_schema(path))
            with self.subTest(schema=os.path.basename(path)):
                for field in FORBIDDEN_FIELDS:
                    self.assertNotIn('"%s":' % field, text)


class TestRealDocumentsValidate(ReportingCase):

    def test_the_canonical_result_validates(self):
        self.assertEqual(
            validate_canonical_assessment_result(self.result.to_json()), ())

    def test_the_structured_report_validates_in_both_locales(self):
        for locale in ("tr", "en"):
            with self.subTest(locale=locale):
                self.assertEqual(
                    validate_structured_report(self.report(locale).to_json()),
                    ())

    def test_the_fact_ledger_validates(self):
        from pgx.reporting.validator import build_fact_ledger
        self.assertEqual(
            validate_report_fact_ledger(build_fact_ledger(self.result)), ())

    def test_the_manifest_validates(self):
        import shutil
        import tempfile
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        produced = self.produced(directory=directory)
        self.assertEqual(
            validate_report_artifact_manifest(
                dict(produced.artifact["manifest"])), ())

    def test_the_gate_status_validates(self):
        from pgx.application.report_gate_status import build_report_gate_status
        self.assertEqual(
            validate_wp15_gate_status(
                build_report_gate_status(REPO_ROOT).to_json()), ())


class TestTheSchemasRefuseWhatTheyShould(ReportingCase):

    def test_a_dose_cannot_be_attached_to_a_result(self):
        document = self.result.to_json()
        document["dose"] = "600 mg"
        self.assertTrue(validate_canonical_assessment_result(document))

    def test_a_score_cannot_be_attached_to_a_medication(self):
        document = copy.deepcopy(self.result.to_json())
        document["medications"][0]["suitability_score"] = 87
        self.assertTrue(validate_canonical_assessment_result(document))

    def test_a_recommendation_cannot_be_attached_to_a_report(self):
        document = self.report().to_json()
        document["recommendation"] = "switch"
        self.assertTrue(validate_structured_report(document))

    def test_a_narrative_cannot_be_attached_to_a_section(self):
        document = copy.deepcopy(self.report().to_json())
        document["medications"][0]["narrative"] = "some prose"
        self.assertTrue(validate_structured_report(document))

    def test_no_active_attention_needs_full_coverage_in_the_schema(self):
        document = copy.deepcopy(self.result.to_json())
        document["overall_attention"] = "NO_ACTIVE_ATTENTION"
        document["overall_coverage"] = "PARTIAL"
        self.assertTrue(validate_canonical_assessment_result(document))

    def test_full_coverage_carries_no_reason_in_the_schema(self):
        document = copy.deepcopy(self.result.to_json())
        for medication in document["medications"]:
            medication["coverage_status"] = "FULL"
            medication["coverage_reason_codes"] = ["SOME_AXES_NOT_COVERED"]
        self.assertTrue(validate_canonical_assessment_result(document))

    def test_a_finding_without_evidence_fails_the_schema(self):
        document = copy.deepcopy(self.result.to_json())
        for medication in document["medications"]:
            for finding in medication["findings"]:
                finding["evidence_references"] = []
        self.assertTrue(validate_canonical_assessment_result(document))

    def test_a_status_without_a_controlled_sentence_fails_the_schema(self):
        document = copy.deepcopy(self.report().to_json())
        document["overall"]["qualifier_statements"] = []
        self.assertTrue(validate_structured_report(document))

    def test_a_section_missing_a_question_fails_the_schema(self):
        document = copy.deepcopy(self.report().to_json())
        document["medications"][0]["answers"].pop("evidence")
        self.assertTrue(validate_structured_report(document))

    def test_a_clean_scan_with_violations_fails_the_manifest_schema(self):
        import shutil
        import tempfile
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        produced = self.produced(directory=directory)
        manifest = copy.deepcopy(dict(produced.artifact["manifest"]))
        manifest["claim_scan"]["is_clean"] = True
        manifest["claim_scan"]["violation_count"] = 1
        self.assertTrue(validate_report_artifact_manifest(manifest))


class TestTheEmbeddedCoverageSchemaCannotDrift(unittest.TestCase):
    """The computation schema inlines the coverage-result schema.

    Inlining is what lets one document be checked whole; a copy that drifted
    from the original would check a shape nothing produces.
    """

    def test_the_inlined_copy_equals_the_published_schema(self):
        computation = load_schema(os.path.join(
            REPO_ROOT, "schemas", "assessment-computation.schema.json"))
        coverage = load_schema(os.path.join(
            REPO_ROOT, "schemas", "coverage-result.schema.json"))
        expected = {key: value for key, value in coverage.items()
                    if key not in ("$id", "$schema", "title")}
        self.assertEqual(computation["$defs"]["coverageResult"], expected)


if __name__ == "__main__":
    unittest.main()
