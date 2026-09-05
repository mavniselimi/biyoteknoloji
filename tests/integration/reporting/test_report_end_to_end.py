# -*- coding: utf-8 -*-
"""K. The whole path, on synthetic data.

One governed world, built through each work package's own services: a frozen
WP-11 ruleset, a verified WP-13 coverage manifest, an ACTIVE synthetic
release, a WP-14 assessment executed and persisted, its WP-14 read model, and
then every WP-15 stage in order.

Numbered so a failure names the step. Everything here is synthetic and is
flagged as such; nothing in this file is evidence about any medicine.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

from pgx.application.report_schema import (validate_canonical_assessment_result,
                                           validate_report_artifact_manifest,
                                           validate_report_fact_ledger,
                                           validate_structured_report)
from pgx.application.report_service import ReportService
from pgx.reporting.artifacts import read_artifact
from pgx.reporting.errors import ReportInputError
from pgx.reporting.models import canonical_result_from_read_model
from pgx.reporting.render import render_markdown, rendered_checksum
from pgx.reporting.structured import build_structured_report
from pgx.reporting.validator import (build_fact_ledger,
                                     validate_fact_preservation,
                                     validate_rendered_report,
                                     validate_safe_status_rendering)
from tests.fixtures.wp13.synthetic import DRUG_1, DRUG_2, UNKNOWN_DRUG
from tests.fixtures.wp15.synthetic import (MIXED_MEDICATIONS,
                                           MIXED_PHENOTYPES, report_world,
                                           stored_read_model)


class TestTheWholePathOnSyntheticData(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.world = report_world()
        cls.view = stored_read_model(cls.world,
                                     medications=MIXED_MEDICATIONS,
                                     phenotypes=MIXED_PHENOTYPES)
        cls.result = canonical_result_from_read_model(cls.view)
        cls.report = build_structured_report(cls.result, locale="tr")
        cls.markdown = render_markdown(cls.report)

    @classmethod
    def tearDownClass(cls):
        cls.world.close()

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory, True)

    # -- 1-4: the read model becomes facts -------------------------------

    def test_01_the_assessment_was_stored_and_reads_back(self):
        self.assertTrue(self.view.verification["row_and_snapshot_agree"])
        self.assertEqual(self.view.verification["recomputed_output_hash"],
                         self.view.output_hash)

    def test_02_the_read_model_becomes_a_canonical_result(self):
        self.assertEqual(self.result.output_hash, self.view.output_hash)
        self.assertEqual(len(self.result.medications), 3)
        self.assertEqual(validate_canonical_assessment_result(
            self.result.to_json()), ())

    def test_03_every_medication_survives_the_projection(self):
        keys = {item.drug_canonical_key for item in self.result.medications}
        self.assertEqual(keys, {DRUG_1, DRUG_2, UNKNOWN_DRUG})

    def test_04_the_unnormalised_observation_survives(self):
        states = {item["gene_id"]: item["status"]
                  for item in self.result.profile_observations}
        self.assertIn("UNSUPPORTED", set(states.values()))

    # -- 5-8: the facts become a report ----------------------------------

    def test_05_the_report_validates_against_its_schema(self):
        self.assertEqual(validate_structured_report(self.report.to_json()),
                         ())

    def test_06_the_fact_ledger_validates_and_is_satisfied(self):
        ledger = validate_fact_preservation(self.result, self.report)
        self.assertEqual(validate_report_fact_ledger(ledger), ())

    def test_07_every_status_is_displayed_safely(self):
        record = validate_safe_status_rendering(self.report)
        self.assertEqual(len(record["checked_blocks"]), 4)

    def test_08_the_rendered_document_shows_every_recorded_fact(self):
        record = validate_rendered_report(self.report, self.markdown)
        self.assertGreater(record["checked_facts"], 30)

    # -- 9-12: the report becomes a document -----------------------------

    def test_09_the_document_carries_the_canonical_warning_twice(self):
        self.assertEqual(self.markdown.count(self.report.canonical_warning),
                         2)

    def test_10_the_document_carries_the_research_disclaimer(self):
        self.assertIn(self.report.disclaimer, self.markdown)

    def test_11_the_document_shows_attention_and_coverage_together(self):
        """Four status blocks - one overall, one per medication - and each
        carries both rows. Counted on lines that *begin* with the label,
        because 'Kapsam kodu' is also an axis-table column heading."""
        lines = self.markdown.splitlines()
        attention = [line for line in lines
                     if line.startswith("| Dikkat kodu |")]
        coverage = [line for line in lines
                    if line.startswith("| Kapsam kodu |")]
        self.assertEqual(len(attention), 4)
        self.assertEqual(len(coverage), 4)
        for index, line in enumerate(lines):
            if not line.startswith("| Dikkat kodu |"):
                continue
            with self.subTest(line=index):
                self.assertTrue(any(
                    other.startswith("| Kapsam kodu |")
                    for other in lines[index:index + 4]))

    def test_12_the_document_names_every_pinned_version(self):
        provenance = dict(self.result.release_provenance)
        for name in ("release_public_id", "ruleset_content_hash",
                     "dataset_public_id", "coverage_manifest_hash"):
            with self.subTest(field=name):
                self.assertIn(provenance[name], self.markdown)

    # -- 13-16: the gate and the artifact --------------------------------

    def test_13_the_claim_scan_is_clean(self):
        produced = ReportService().render_synthetic(self.view)
        self.assertTrue(produced.claim_scan["is_clean"])
        self.assertEqual(produced.claim_scan["violation_count"], 0)

    def test_14_the_artifact_and_its_manifest_are_written(self):
        produced = ReportService().render_synthetic(self.view,
                                                    directory=self.directory)
        self.assertTrue(produced.artifact["written"])
        self.assertEqual(validate_report_artifact_manifest(
            dict(produced.artifact["manifest"])), ())

    def test_15_the_artifact_reads_back_and_verifies(self):
        produced = ReportService().render_synthetic(self.view,
                                                    directory=self.directory)
        record = read_artifact(produced.artifact["manifest_path"])
        self.assertTrue(record["verified"])
        self.assertEqual(record["rendered"], produced.markdown)

    def test_16_the_manifest_carries_the_ledger_and_the_scan(self):
        produced = ReportService().render_synthetic(self.view,
                                                    directory=self.directory)
        manifest = produced.artifact["manifest"]
        self.assertEqual(manifest["fact_ledger"]["ledger_hash"],
                         build_fact_ledger(self.result)["ledger_hash"])
        self.assertTrue(manifest["claim_scan"]["limits"])

    # -- 17-20: the properties that hold across runs ---------------------

    def test_17_two_runs_produce_byte_identical_documents(self):
        one = ReportService().render_synthetic(self.view)
        two = ReportService().render_synthetic(self.view)
        self.assertEqual(one.markdown, two.markdown)
        self.assertEqual(one.json_text, two.json_text)
        self.assertEqual(rendered_checksum(one.markdown),
                         rendered_checksum(two.markdown))

    def test_18_two_locales_share_the_facts_and_differ_as_documents(self):
        turkish = ReportService().render_synthetic(self.view, locale="tr")
        english = ReportService().render_synthetic(self.view, locale="en")
        self.assertEqual(turkish.output_hash, english.output_hash)
        self.assertNotEqual(turkish.report_hash, english.report_hash)
        self.assertNotEqual(turkish.markdown, english.markdown)

    def test_19_a_report_regenerated_from_its_document_is_the_same(self):
        first = ReportService().render_synthetic(self.view)
        again = ReportService().regenerate_from_document(
            self.result.to_json())
        self.assertEqual(first.markdown, again.markdown)
        self.assertEqual(first.report_hash, again.report_hash)

    def test_20_rendering_a_stored_assessment_runs_no_engine(self):
        """The pointer is never consulted, and nothing is recalculated."""
        before = self.world.resolver.pointer_reads
        ReportService().render_synthetic(self.view)
        self.assertEqual(self.world.resolver.pointer_reads, before)

    # -- 21-24: what the whole path refuses ------------------------------

    def test_21_a_real_report_is_refused_by_the_claim_boundary(self):
        with self.assertRaises(ReportInputError) as caught:
            ReportService().generate("some-assessment-id")
        self.assertEqual(caught.exception.code,
                         "REPORT_CLAIM_BOUNDARY_NOT_APPROVED")

    def test_22_a_missing_assessment_fails_closed(self):
        from pgx.domain.claims import ClaimPhase
        from tests.fixtures.wp14.synthetic import synthetic_claim_boundary

        class EmptyStore:
            def read_model(self, assessment_id):
                return None

        service = ReportService(read_port=EmptyStore(),
                                claim_boundary=synthetic_claim_boundary())
        with self.assertRaises(ReportInputError) as caught:
            service.generate("no-such-assessment")
        self.assertEqual(caught.exception.code,
                         "REPORT_ASSESSMENT_NOT_FOUND")

    def test_23_a_service_with_no_read_port_fails_closed(self):
        from tests.fixtures.wp14.synthetic import synthetic_claim_boundary
        service = ReportService(claim_boundary=synthetic_claim_boundary())
        with self.assertRaises(ReportInputError) as caught:
            service.generate("no-such-assessment")
        self.assertEqual(caught.exception.code,
                         "REPORT_ASSESSMENT_NOT_FOUND")

    def test_24_an_approved_boundary_reports_a_stored_assessment(self):
        """The one path that would work if a boundary were ever approved, run
        against an explicitly synthetic one that only tests construct."""
        from tests.fixtures.wp14.synthetic import synthetic_claim_boundary

        class OneAssessment:
            def __init__(self, view):
                self._view = view

            def read_model(self, assessment_id):
                return self._view

        service = ReportService(read_port=OneAssessment(self.view),
                                claim_boundary=synthetic_claim_boundary())
        produced = service.generate(self.view.assessment_id,
                                    directory=self.directory)
        self.assertFalse(produced.is_synthetic)
        self.assertTrue(produced.artifact["written"])
        self.assertEqual(produced.markdown, self.markdown)

    # -- 25: the document itself -----------------------------------------

    def test_25_the_document_is_substantial_and_well_formed(self):
        self.assertGreater(len(self.markdown), 8000)
        self.assertTrue(self.markdown.startswith("# "))
        self.assertTrue(self.markdown.endswith("\n"))
        self.assertNotIn("\r", self.markdown)
        self.assertNotIn("None", self.markdown)


if __name__ == "__main__":
    unittest.main()
