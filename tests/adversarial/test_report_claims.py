# -*- coding: utf-8 -*-
"""J. Adversarial claim tests.

Each fixture below is a sentence a report must never publish. The tests feed
them to the gate and assert that it blocks them - and, just as importantly,
that the reporting layer could not have produced them in the first place.

**The scanner is never weakened to make anything pass.** Where it misses a
claim, that is recorded here as a documented limit and the structural controls
are asserted instead. The scanner is lexical defence in depth behind an
architecture where there is no free text to scan: every sentence in a report
comes from a fixed table and every label from a fixed lookup.
"""

from __future__ import annotations

import os
import unittest

from pgx.domain.claims import DEFAULT_CLAIM_BOUNDARY, scan_claim_text
from pgx.reporting.errors import ReportClaimError
from pgx.reporting.gate import (SCANNER_LIMITS, claim_scan_evidence,
                                gate_contract, require_clean_report,
                                scan_report_text)
from tests.fixtures.wp15.synthetic import (ADVERSARIAL_TEXTS,
                                           HIDDEN_CLAIM_TEXTS,
                                           SCANNER_BLIND_SPOTS)
from tests.unit.reporting._support import (REPO_ROOT, REPORTING_DIR,
                                           reporting_modules, source)


class TestTheGateBlocksEveryProhibitedCategory(unittest.TestCase):

    def test_every_adversarial_sentence_is_blocked(self):
        for label, _category, sentence in ADVERSARIAL_TEXTS:
            with self.subTest(case=label):
                with self.assertRaises(ReportClaimError) as caught:
                    require_clean_report(sentence)
                self.assertEqual(caught.exception.code,
                                 "REPORT_PROHIBITED_CLAIM")

    def test_each_is_blocked_under_the_category_it_belongs_to(self):
        for label, category, sentence in ADVERSARIAL_TEXTS:
            with self.subTest(case=label):
                result = scan_report_text(sentence)
                self.assertIn(category,
                              [item.value for item in result.categories])

    def test_a_diagnosis_is_blocked(self):
        self.assertTrue(scan_report_text(
            "This report diagnoses the patient with a metabolic "
            "disorder.").has_violations)

    def test_a_suitability_claim_is_blocked(self):
        self.assertTrue(scan_report_text(
            "This medication is more suitable for this "
            "patient.").has_violations)

    def test_a_treatment_selection_is_blocked(self):
        self.assertTrue(scan_report_text(
            "Use warfarin instead of clopidogrel for this "
            "profile.").has_violations)

    def test_a_dose_instruction_is_blocked(self):
        self.assertTrue(scan_report_text(
            "The dose should be reduced for this patient.").has_violations)

    def test_a_candidate_safety_claim_is_blocked(self):
        self.assertTrue(scan_report_text(
            "This drug is completely safe for this profile.").has_violations)

    def test_low_risk_for_something_unassessed_is_blocked(self):
        self.assertTrue(scan_report_text(
            "Every unevaluated axis carries low risk.").has_violations)

    def test_false_certainty_about_validation_is_blocked(self):
        self.assertTrue(scan_report_text(
            "This system is clinically validated and approved for clinical "
            "use.").has_violations)

    def test_a_claim_hidden_in_markup_is_blocked(self):
        for label, text in HIDDEN_CLAIM_TEXTS:
            with self.subTest(case=label):
                self.assertTrue(scan_report_text(text).has_violations)

    def test_the_refusal_names_the_rules_without_repeating_the_sentence(self):
        sentence = "This drug is completely safe for this profile."
        with self.assertRaises(ReportClaimError) as caught:
            require_clean_report(sentence)
        detail = caught.exception.detail
        self.assertTrue(detail["rule_ids"])
        self.assertTrue(detail["offsets"])
        self.assertNotIn(sentence, str(detail))


class TestTheScannerIsNotWeakened(unittest.TestCase):

    def test_the_boundary_used_is_the_default_one(self):
        result = scan_report_text("harmless")
        self.assertEqual(result.boundary_version,
                         DEFAULT_CLAIM_BOUNDARY.version)

    def test_no_reporting_module_edits_a_scanner_rule(self):
        for path in reporting_modules():
            text = source(path)
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("_PATTERN_SPECS", "_COMPILED_PATTERNS",
                                  "ClaimPattern(", "_SAFE_CONTEXT_PATTERNS",
                                  "_NEGATION_MARKERS"):
                    self.assertNotIn(forbidden, text)

    def test_no_reporting_module_narrows_the_prohibited_categories(self):
        for path in reporting_modules():
            text = source(path)
            with self.subTest(module=os.path.basename(path)):
                self.assertNotIn("prohibited_categories=", text)
                self.assertNotIn("ClaimBoundary(", text)

    def test_the_gate_runs_on_every_produced_report(self):
        from pgx.application.report_service import ReportService
        text = source(os.path.join(REPO_ROOT, "pgx", "application",
                                   "report_service.py"))
        self.assertIn("require_clean_report", text)
        # Twice: once over the Markdown and once over the JSON. A report
        # published only as JSON would otherwise reach a reader through a
        # format the gate never saw.
        self.assertEqual(text.count("require_clean_report("), 2)


class TestTheScannerLimitsAreDocumentedNotHidden(unittest.TestCase):
    """The honest half.

    A clean scan is evidence that no published pattern matched. It is not
    evidence that a document is safe, and these tests exist so that claim is
    never made by omission.
    """

    def test_the_published_limits_are_not_empty(self):
        self.assertGreaterEqual(len(SCANNER_LIMITS), 4)
        self.assertTrue(all(limit.strip() for limit in SCANNER_LIMITS))

    def test_the_contract_publishes_them(self):
        self.assertEqual(list(gate_contract()["limits"]),
                         list(SCANNER_LIMITS))

    def test_every_scan_record_carries_them(self):
        evidence = claim_scan_evidence(scan_report_text("harmless"))
        self.assertEqual(list(evidence["limits"]), list(SCANNER_LIMITS))

    def test_the_documented_blind_spots_really_are_blind_spots(self):
        """Asserted, not assumed. If a future scanner rule catches one of
        these, this test fails and the limit is removed from the docs rather
        than quietly staying there as a false confession."""
        for label, text, _reason in SCANNER_BLIND_SPOTS:
            with self.subTest(case=label):
                self.assertFalse(scan_claim_text(text).has_violations)

    def test_no_blind_spot_sentence_could_be_produced_by_this_layer(self):
        """The structural control that actually stops them: there is no free
        text in a report. Every sentence comes from a fixed table."""
        from pgx.reporting.templates import CONTROLLED_STATEMENTS
        published = {value for entry in CONTROLLED_STATEMENTS.values()
                     for value in entry.values()}
        for label, text, _reason in SCANNER_BLIND_SPOTS:
            with self.subTest(case=label):
                self.assertNotIn(text, published)
                for sentence in published:
                    self.assertNotIn(text, sentence)

    def test_the_report_types_have_nowhere_to_put_an_authored_sentence(self):
        import dataclasses
        from pgx.reporting.structured import (FindingLine, MedicationSection,
                                              StructuredReport)
        for kind in (StructuredReport, MedicationSection, FindingLine):
            names = {field.name for field in dataclasses.fields(kind)}
            with self.subTest(type=kind.__name__):
                for forbidden in ("narrative", "prose", "summary_text",
                                  "explanation", "commentary", "advice",
                                  "interpretation"):
                    self.assertNotIn(forbidden, names)


class TestARealReportPassesTheGate(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from tests.fixtures.wp15.synthetic import (report_world,
                                                   stored_read_model)
        cls.world = report_world()
        cls.view = stored_read_model(cls.world)

    @classmethod
    def tearDownClass(cls):
        cls.world.close()

    def test_both_locales_scan_clean(self):
        from pgx.application.report_service import ReportService
        for locale in ("tr", "en"):
            with self.subTest(locale=locale):
                produced = ReportService().render_synthetic(self.view,
                                                            locale=locale)
                self.assertTrue(produced.claim_scan["is_clean"])
                self.assertEqual(produced.claim_scan["violation_count"], 0)

    def test_the_scan_evidence_is_recorded(self):
        from pgx.application.report_service import ReportService
        produced = ReportService().render_synthetic(self.view)
        evidence = produced.claim_scan
        self.assertTrue(evidence["scanner_version"])
        self.assertTrue(evidence["boundary_version"])
        self.assertIn("suppressed", evidence)
        self.assertGreater(evidence["text_length"], 1000)

    def test_a_report_carrying_a_prohibited_sentence_is_not_published(self):
        """Injected after rendering, which is the only way to get one in."""
        import shutil
        import tempfile
        from pgx.application.report_service import ReportService
        from pgx.reporting.artifacts import write_artifact
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        produced = ReportService().render_synthetic(self.view)
        poisoned = produced.markdown + \
            "\n\nThis drug is completely safe for this profile.\n"
        with self.assertRaises(ReportClaimError):
            require_clean_report(poisoned)
        self.assertEqual(os.listdir(directory), [])

    def test_every_controlled_sentence_scans_clean(self):
        from pgx.reporting.templates import CONTROLLED_STATEMENTS
        for key, entry in CONTROLLED_STATEMENTS.items():
            for locale, text in entry.items():
                with self.subTest(statement=key, locale=locale):
                    self.assertFalse(scan_report_text(text).has_violations)

    def test_every_controlled_label_scans_clean(self):
        import pgx.reporting.templates as templates
        for name in ("ATTENTION_LABELS", "COVERAGE_LABELS",
                     "COVERAGE_REASON_LABELS", "OBSERVATION_STATE_LABELS",
                     "MODE_LABELS", "INPUT_KIND_LABELS", "SECTION_TITLES",
                     "FIELD_LABELS"):
            table = getattr(templates, name)
            for code, entry in table.items():
                for locale, text in entry.items():
                    with self.subTest(table=name, code=code, locale=locale):
                        self.assertFalse(
                            scan_report_text(text).has_violations)


if __name__ == "__main__":
    unittest.main()
