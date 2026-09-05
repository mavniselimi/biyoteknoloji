# -*- coding: utf-8 -*-
"""A. The canonical result contract.

The boundary between what was calculated and what is shown needs a value
object that refuses everything it was not given. These tests assert the
refusals, because the refusals are the contract: a report cannot show a fact
this type would not accept, and cannot be built from facts that did not
verify.
"""

from __future__ import annotations

import copy
import io
import json
import os
import unittest

from pgx.reporting.errors import ReportInputError
from pgx.reporting.models import (CANONICAL_RESULT_SCHEMA_VERSION,
                                  MAX_REFERENCE_LENGTH, AxisFacts,
                                  CanonicalAssessmentResult, FindingFacts,
                                  MedicationFacts,
                                  canonical_result_from_document,
                                  canonical_result_from_read_model)
from tests.fixtures.wp13.synthetic import DRUG_1, DRUG_2, GENE_1, UNKNOWN_DRUG
from tests.unit.reporting._support import REPO_ROOT, ReportingCase

FIXTURE = os.path.join(REPO_ROOT, "tests", "fixtures", "wp15",
                       "synthetic-canonical-result.json")


class TestTheFactsItAccepts(ReportingCase):

    def test_it_names_its_schema_version(self):
        self.assertEqual(self.result.result_schema_version,
                         CANONICAL_RESULT_SCHEMA_VERSION)

    def test_it_carries_every_requested_medication(self):
        keys = [item.drug_canonical_key for item in self.result.medications]
        self.assertEqual(sorted(keys), sorted([DRUG_1, DRUG_2, UNKNOWN_DRUG]))

    def test_it_carries_every_axis_coverage_recorded(self):
        embedded = [axis for medication
                    in dict(self.view.coverage_result)["medications"]
                    for axis in medication["axes"]]
        self.assertEqual(len(self.result.axes), len(embedded))

    def test_it_carries_every_finding_with_its_chain(self):
        self.assertTrue(self.result.findings)
        for finding in self.result.findings:
            with self.subTest(gene=finding.gene_canonical_key):
                self.assertTrue(finding.rule_id)
                self.assertTrue(finding.rule_content_hash)
                self.assertTrue(finding.rationale_reference)
                self.assertTrue(finding.curation_revision_id)
                self.assertTrue(finding.evidence_references)

    def test_it_carries_every_phenotype_observation(self):
        genes = {item["gene_id"] for item in self.result.profile_observations}
        self.assertIn(GENE_1, genes)

    def test_it_carries_every_pinned_version(self):
        for name in ("release_public_id", "ruleset_content_hash",
                     "dataset_public_id", "coverage_manifest_hash"):
            with self.subTest(field=name):
                self.assertTrue(self.result.release_provenance[name])

    def test_it_hashes_deterministically(self):
        self.assertEqual(self.result.content_hash(),
                         self.result.content_hash())

    def test_the_hash_excludes_the_run_label(self):
        """Two runs of one question under different case labels are the same
        facts, and a hash that disagreed would make the comparison useless."""
        import dataclasses
        relabelled = dataclasses.replace(self.result, case_id="OTHER-CASE")
        self.assertEqual(relabelled.content_hash(),
                         self.result.content_hash())

    def test_it_is_deeply_immutable(self):
        with self.assertRaises(Exception):
            self.result.release_provenance["release_public_id"] = "x"
        with self.assertRaises(Exception):
            self.result.medications[0].axes[0].rule_references[0]["x"] = 1


class TestTheFactsItRefuses(ReportingCase):

    def test_an_unknown_field_is_refused(self):
        document = self.result.to_json()
        document["dose_recommendation"] = "600 mg"
        with self.assertRaises(ReportInputError) as caught:
            canonical_result_from_document(document)
        self.assertEqual(caught.exception.code, "REPORT_UNKNOWN_FIELD")

    def test_an_unknown_field_on_a_medication_is_refused(self):
        document = copy.deepcopy(self.result.to_json())
        document["medications"][0]["suitability_score"] = 87
        with self.assertRaises(ReportInputError) as caught:
            canonical_result_from_document(document)
        self.assertEqual(caught.exception.code, "REPORT_UNKNOWN_FIELD")

    def test_an_unknown_field_on_a_finding_is_refused(self):
        document = copy.deepcopy(self.result.to_json())
        for medication in document["medications"]:
            if medication["findings"]:
                medication["findings"][0]["plain_language"] = "some prose"
                break
        with self.assertRaises(ReportInputError) as caught:
            canonical_result_from_document(document)
        self.assertEqual(caught.exception.code, "REPORT_UNKNOWN_FIELD")

    def test_a_tampered_content_hash_is_refused(self):
        document = copy.deepcopy(self.result.to_json())
        document["overall_attention"] = "HIGH"
        with self.assertRaises(ReportInputError) as caught:
            canonical_result_from_document(document)
        self.assertEqual(caught.exception.code, "REPORT_HASH_MISMATCH")

    def test_an_unknown_schema_version_is_refused(self):
        document = copy.deepcopy(self.result.to_json())
        document["result_schema_version"] = "pgx-something-else/9"
        with self.assertRaises(ReportInputError) as caught:
            canonical_result_from_document(document)
        self.assertEqual(caught.exception.code,
                         "REPORT_SCHEMA_VERSION_UNKNOWN")

    def test_prose_in_a_reference_field_is_refused(self):
        """A newline in a reference is prose arriving where an identifier
        belongs, and it is the shape a narrative would take."""
        with self.assertRaises(ReportInputError):
            AxisFacts(drug_canonical_key=DRUG_1,
                      gene_canonical_key="GENE:X\nGENE:Y",
                      coverage_status="FULL")

    def test_an_overlong_reference_is_refused(self):
        with self.assertRaises(ReportInputError):
            AxisFacts(drug_canonical_key=DRUG_1,
                      gene_canonical_key="G" * (MAX_REFERENCE_LENGTH + 1),
                      coverage_status="FULL")

    def test_a_finding_without_evidence_is_refused(self):
        with self.assertRaises(ReportInputError) as caught:
            FindingFacts(drug_canonical_key=DRUG_1, gene_canonical_key=GENE_1,
                         phenotype="POOR", attention_level="HIGH",
                         rule_id="r", rule_family_id="f", rule_version=1,
                         rule_content_hash="sha256:" + "a" * 64,
                         rationale_reference="ref", curation_revision_id="c",
                         curation_revision_hash="sha256:" + "b" * 64,
                         evidence_references=())
        self.assertEqual(caught.exception.code, "REPORT_EVIDENCE_MISSING")

    def test_a_not_assessed_finding_is_refused(self):
        with self.assertRaises(ReportInputError):
            FindingFacts(drug_canonical_key=DRUG_1, gene_canonical_key=GENE_1,
                         phenotype="POOR", attention_level="NOT_ASSESSED",
                         rule_id="r", rule_family_id="f", rule_version=1,
                         rule_content_hash="sha256:" + "a" * 64,
                         rationale_reference="ref", curation_revision_id="c",
                         curation_revision_hash="sha256:" + "b" * 64,
                         evidence_references=("e",))

    def test_no_active_attention_without_full_coverage_is_refused(self):
        with self.assertRaises(ReportInputError) as caught:
            MedicationFacts(drug_canonical_key=DRUG_1,
                            requested_value=DRUG_1,
                            attention_level="NO_ACTIVE_ATTENTION",
                            coverage_status="PARTIAL",
                            coverage_reason_codes=("SOME_AXES_NOT_COVERED",))
        self.assertEqual(caught.exception.code,
                         "REPORT_STATUS_RENDERING_UNSAFE")

    def test_incomplete_coverage_without_a_reason_is_refused(self):
        with self.assertRaises(ReportInputError) as caught:
            MedicationFacts(drug_canonical_key=DRUG_1,
                            requested_value=DRUG_1,
                            attention_level="NOT_ASSESSED",
                            coverage_status="PARTIAL")
        self.assertEqual(caught.exception.code,
                         "REPORT_STATUS_RENDERING_UNSAFE")

    def test_a_not_assessed_medication_with_findings_is_refused(self):
        finding = FindingFacts(
            drug_canonical_key=DRUG_1, gene_canonical_key=GENE_1,
            phenotype="POOR", attention_level="HIGH", rule_id="r",
            rule_family_id="f", rule_version=1,
            rule_content_hash="sha256:" + "a" * 64,
            rationale_reference="ref", curation_revision_id="c",
            curation_revision_hash="sha256:" + "b" * 64,
            evidence_references=("e",))
        with self.assertRaises(ReportInputError):
            MedicationFacts(drug_canonical_key=DRUG_1,
                            requested_value=DRUG_1,
                            attention_level="NOT_ASSESSED",
                            coverage_status="INSUFFICIENT",
                            coverage_reason_codes=("PHENOTYPE_NOT_PROVIDED",),
                            findings=(finding,))

    def test_an_empty_medication_list_is_refused(self):
        with self.assertRaises(ReportInputError):
            CanonicalAssessmentResult(
                assessment_id="a", mode="DEMO",
                input_kind="SYNTHETIC_PHENOTYPE_PROFILE",
                input_hash="sha256:" + "a" * 64,
                output_hash="sha256:" + "b" * 64,
                coverage_result_hash="sha256:" + "c" * 64,
                overall_attention="NOT_ASSESSED",
                overall_coverage="INSUFFICIENT",
                overall_coverage_reason_codes=("PHENOTYPE_NOT_PROVIDED",),
                medications=(), release_provenance={"x": 1},
                pointer_audit={})

    def test_missing_release_provenance_is_refused(self):
        medication = MedicationFacts(
            drug_canonical_key=DRUG_1, requested_value=DRUG_1,
            attention_level="NOT_ASSESSED", coverage_status="INSUFFICIENT",
            coverage_reason_codes=("PHENOTYPE_NOT_PROVIDED",))
        with self.assertRaises(ReportInputError) as caught:
            CanonicalAssessmentResult(
                assessment_id="a", mode="DEMO",
                input_kind="SYNTHETIC_PHENOTYPE_PROFILE",
                input_hash="sha256:" + "a" * 64,
                output_hash="sha256:" + "b" * 64,
                coverage_result_hash="sha256:" + "c" * 64,
                overall_attention="NOT_ASSESSED",
                overall_coverage="INSUFFICIENT",
                overall_coverage_reason_codes=("PHENOTYPE_NOT_PROVIDED",),
                medications=(medication,), release_provenance={},
                pointer_audit={})
        self.assertEqual(caught.exception.code,
                         "REPORT_RELEASE_PROVENANCE_MISSING")


class TestItVerifiesBeforeItConstructs(ReportingCase):

    def test_a_read_model_whose_row_disagrees_is_refused(self):
        import dataclasses
        broken = dataclasses.replace(
            self.view,
            verification=dict(dict(self.view.verification),
                              row_and_snapshot_agree=False))
        with self.assertRaises(ReportInputError) as caught:
            canonical_result_from_read_model(broken)
        self.assertEqual(caught.exception.code,
                         "REPORT_ROW_SNAPSHOT_DISAGREEMENT")

    def test_a_read_model_whose_output_hash_disagrees_is_refused(self):
        import dataclasses
        broken = dataclasses.replace(
            self.view,
            verification=dict(dict(self.view.verification),
                              recomputed_output_hash="sha256:" + "0" * 64))
        with self.assertRaises(ReportInputError) as caught:
            canonical_result_from_read_model(broken)
        self.assertEqual(caught.exception.code, "REPORT_HASH_MISMATCH")

    def test_a_read_model_whose_coverage_does_not_verify_is_refused(self):
        import dataclasses
        broken = dataclasses.replace(
            self.view,
            coverage_result=dict(dict(self.view.coverage_result),
                                 content_hash="sha256:" + "0" * 64))
        with self.assertRaises(ReportInputError) as caught:
            canonical_result_from_read_model(broken)
        self.assertEqual(caught.exception.code,
                         "REPORT_COVERAGE_UNVERIFIABLE")


class TestTheCheckedInFixture(unittest.TestCase):
    """The synthetic document the CLI is demonstrated with."""

    def setUp(self):
        with io.open(FIXTURE, encoding="utf-8") as handle:
            self.document = json.load(handle)

    def test_it_loads_as_a_canonical_result(self):
        result = canonical_result_from_document(self.document)
        self.assertEqual(result.result_schema_version,
                         CANONICAL_RESULT_SCHEMA_VERSION)

    def test_it_says_it_is_synthetic_in_its_own_case_label(self):
        self.assertIn("SYNTHETIC", self.document["case_id"])
        self.assertIn("NOT-A-REAL-CASE", self.document["case_id"])

    def test_it_names_no_real_gene_or_drug(self):
        text = json.dumps(self.document)
        for real in ("CYP2D6", "CYP2C19", "codeine", "clopidogrel",
                     "warfarin"):
            with self.subTest(name=real):
                self.assertNotIn(real, text)

    def test_it_lives_outside_every_production_directory(self):
        self.assertIn(os.path.join("tests", "fixtures"), FIXTURE)
        self.assertNotIn(os.path.join("data", "reports"), FIXTURE)


if __name__ == "__main__":
    unittest.main()
