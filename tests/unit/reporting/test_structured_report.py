# -*- coding: utf-8 -*-
"""B. The structured report contract.

Every governed value beside its label, the eight questions answered, the
canonical warning imported rather than written, both hashes distinguishable,
and absence rendered as an explicit section rather than as a gap.
"""

from __future__ import annotations

import unittest

from pgx.domain.claims import CANONICAL_CLINICAL_WARNING, canonical_clinical_warning
from pgx.reporting.errors import ReportInputError, ReportRenderError
from pgx.reporting.structured import (REPORT_SCHEMA_VERSION, MedicationSection,
                                      build_structured_report)
from pgx.reporting.templates import (ATTENTION_LABELS, COVERAGE_LABELS,
                                     COVERAGE_REASON_LABELS,
                                     MEDICATION_QUESTIONS, SUPPORTED_LOCALES,
                                     TEMPLATE_VERSION)
from tests.fixtures.wp13.synthetic import DRUG_1, DRUG_2, UNKNOWN_DRUG
from tests.unit.reporting._support import ReportingCase


class TestTheReportIdentity(ReportingCase):

    def test_it_names_its_schema_template_and_locale(self):
        report = self.report()
        self.assertEqual(report.report_schema_version, REPORT_SCHEMA_VERSION)
        self.assertEqual(report.template_version, TEMPLATE_VERSION)
        self.assertEqual(report.locale, "tr")

    def test_turkish_is_the_locale_it_is_built_in_by_default(self):
        from pgx.reporting.templates import DEFAULT_LOCALE
        self.assertEqual(DEFAULT_LOCALE, "tr")
        self.assertEqual(build_structured_report(self.result).locale, "tr")

    def test_an_unsupported_locale_is_refused(self):
        with self.assertRaises(ReportRenderError) as caught:
            build_structured_report(self.result, locale="de")
        self.assertEqual(caught.exception.code,
                         "REPORT_LOCALE_NOT_SUPPORTED")

    def test_an_unknown_template_is_refused(self):
        with self.assertRaises(ReportRenderError) as caught:
            build_structured_report(self.result,
                                    template_version="pgx-report-template/99")
        self.assertEqual(caught.exception.code, "REPORT_TEMPLATE_UNKNOWN")

    def test_only_a_canonical_result_is_accepted(self):
        with self.assertRaises(ReportInputError):
            build_structured_report({"overall_attention": "HIGH"})

    def test_the_report_hash_differs_from_the_output_hash(self):
        report = self.report()
        self.assertNotEqual(report.report_hash(), report.output_hash)

    def test_two_locales_share_the_output_hash_and_differ_in_report_hash(self):
        turkish = self.report("tr")
        english = self.report("en")
        self.assertEqual(turkish.output_hash, english.output_hash)
        self.assertNotEqual(turkish.report_hash(), english.report_hash())

    def test_the_report_hash_covers_the_template_and_the_locale(self):
        content = self.report().semantic_content()
        self.assertEqual(content["template_version"], TEMPLATE_VERSION)
        self.assertEqual(content["locale"], "tr")
        self.assertEqual(content["report_schema_version"],
                         REPORT_SCHEMA_VERSION)

    def test_the_report_hash_excludes_the_run_label(self):
        import dataclasses
        report = self.report()
        relabelled = dataclasses.replace(report, case_id="OTHER")
        self.assertEqual(relabelled.report_hash(), report.report_hash())


class TestEveryCodeIsShownWithItsLabel(ReportingCase):

    def test_the_overall_status_shows_both_codes_and_both_labels(self):
        overall = self.report().overall
        self.assertEqual(overall.attention_label,
                         ATTENTION_LABELS[overall.attention_code]["tr"])
        self.assertEqual(overall.coverage_label,
                         COVERAGE_LABELS[overall.coverage_code]["tr"])

    def test_every_reason_code_has_its_own_label(self):
        for section in self.report().medications:
            with self.subTest(drug=section.drug_canonical_key):
                self.assertEqual(len(section.status.reason_codes),
                                 len(section.status.reason_labels))
                for code, text in zip(section.status.reason_codes,
                                      section.status.reason_labels):
                    self.assertEqual(text,
                                     COVERAGE_REASON_LABELS[code]["tr"])

    def test_every_axis_shows_its_coverage_code_and_label(self):
        for axis in self.report().axes:
            with self.subTest(gene=axis.gene_canonical_key):
                self.assertEqual(axis.coverage_label,
                                 COVERAGE_LABELS[axis.coverage_code]["tr"])

    def test_a_phenotype_is_shown_as_the_governed_value(self):
        """RAPID and ULTRARAPID are different governed values whose confusion
        is its own invariant. Neither is translated."""
        for axis in self.report().axes:
            if axis.observed_phenotype is None:
                continue
            with self.subTest(gene=axis.gene_canonical_key):
                self.assertEqual(axis.observed_phenotype,
                                 axis.observed_phenotype.upper())

    def test_an_unknown_code_has_no_invented_label(self):
        from pgx.reporting.templates import label
        with self.assertRaises(ReportRenderError) as caught:
            label(ATTENTION_LABELS, "SOMEWHAT_CONCERNING", "tr")
        self.assertEqual(caught.exception.code, "REPORT_LABEL_UNKNOWN")


class TestEverySectionAnswersEightQuestions(ReportingCase):

    def test_every_medication_section_answers_all_eight(self):
        for section in self.report().medications:
            with self.subTest(drug=section.drug_canonical_key):
                for identifier, _text in MEDICATION_QUESTIONS:
                    self.assertIn(identifier, section.answers)

    def test_no_answer_is_empty(self):
        for section in self.report().medications:
            for identifier, answer in section.answers.items():
                with self.subTest(drug=section.drug_canonical_key,
                                  question=identifier):
                    parts = (list(answer.get("values", ()))
                             + list(answer.get("codes", ()))
                             + list(answer.get("references", ()))
                             + list(answer.get("statements", ())))
                    self.assertTrue([item for item in parts if item])

    def test_a_section_missing_an_answer_is_refused(self):
        section = self.report().medications[0]
        answers = {key: dict(value) for key, value in section.answers.items()}
        answers.pop("evidence")
        with self.assertRaises(ReportInputError):
            MedicationSection(
                drug_canonical_key=section.drug_canonical_key,
                requested_value=section.requested_value,
                status=section.status, axes=section.axes,
                findings=section.findings,
                not_assessed_axes=section.not_assessed_axes,
                conflict_axes=section.conflict_axes,
                conflict_references=section.conflict_references,
                evidence_references=section.evidence_references,
                rule_references=section.rule_references, answers=answers)

    def test_the_versions_answer_names_the_release_ruleset_and_dataset(self):
        provenance = self.result.release_provenance
        for section in self.report().medications:
            codes = list(section.answers["versions"]["codes"])
            with self.subTest(drug=section.drug_canonical_key):
                self.assertIn(provenance["release_public_id"], codes)
                self.assertIn(provenance["ruleset_public_id"], codes)
                self.assertIn(provenance["dataset_public_id"], codes)

    def test_the_evidence_answer_names_every_evidence_record(self):
        for section in self.report().medications:
            expected = sorted({reference for finding in section.findings
                               for reference in finding.evidence_references})
            with self.subTest(drug=section.drug_canonical_key):
                self.assertEqual(
                    sorted(section.answers["evidence"]["references"]),
                    expected)


class TestTheWarningAndTheDisclaimer(ReportingCase):

    def test_the_warning_is_the_one_the_domain_publishes(self):
        for locale in SUPPORTED_LOCALES:
            with self.subTest(locale=locale):
                self.assertEqual(self.report(locale).canonical_warning,
                                 canonical_clinical_warning(locale))

    def test_a_paraphrased_warning_is_refused(self):
        import dataclasses
        report = self.report()
        with self.assertRaises(ReportInputError) as caught:
            dataclasses.replace(
                report,
                canonical_warning=report.canonical_warning.replace(
                    "değildir", "degildir"))
        self.assertEqual(caught.exception.code,
                         "REPORT_STATUS_RENDERING_UNSAFE")

    def test_the_report_carries_a_research_prototype_disclaimer(self):
        report = self.report()
        self.assertIn("araştırma/prototip", report.disclaimer)
        self.assertIn("prototype", self.report("en").disclaimer)

    def test_the_warning_and_the_disclaimer_are_different_texts(self):
        report = self.report()
        self.assertNotEqual(report.canonical_warning, report.disclaimer)


class TestAbsenceIsASection(ReportingCase):

    def test_an_unsupported_medication_gets_a_not_assessed_status(self):
        section = self.report().section_for(UNKNOWN_DRUG)
        self.assertEqual(section.status.attention_code, "NOT_ASSESSED")
        self.assertTrue(section.status.qualifier_statements)
        self.assertTrue(section.status.reason_codes)

    def test_a_partially_covered_medication_lists_its_missing_axes(self):
        report = self.report()
        partial = [section for section in report.medications
                   if section.status.coverage_code == "PARTIAL"]
        self.assertTrue(partial)
        for section in partial:
            with self.subTest(drug=section.drug_canonical_key):
                self.assertTrue(section.not_assessed_axes)
                for axis in section.not_assessed_axes:
                    self.assertTrue(axis.reason_codes)

    def test_a_finding_without_governed_codes_says_so(self):
        report = self.report()
        self.assertTrue(report.findings)
        for finding in report.findings:
            with self.subTest(gene=finding.gene_canonical_key):
                self.assertIsNone(finding.effect_code)
                self.assertIsNone(finding.explanation_code)
                self.assertTrue(finding.codes_absent_statement)
                self.assertIn("etki/açıklama kodu",
                              finding.codes_absent_statement)

    def test_that_statement_still_points_at_the_governed_references(self):
        for finding in self.report().findings:
            with self.subTest(gene=finding.gene_canonical_key):
                self.assertTrue(finding.rationale_reference)
                self.assertTrue(finding.evidence_references)

    def test_the_uncertainty_section_names_every_unknown(self):
        report = self.report()
        kinds = {item.kind for item in report.uncertainty}
        self.assertIn("MEDICATION_NOT_ASSESSED", kinds)
        self.assertIn("NO_GOVERNED_CODES", kinds)
        self.assertIn("OBSERVATION_NOT_NORMALIZED", kinds)

    def test_every_uncertainty_item_carries_a_controlled_sentence(self):
        for item in self.report().uncertainty:
            with self.subTest(kind=item.kind, subject=item.subject):
                self.assertTrue(item.statement_text)


class TestCollectionsAreCanonicallyOrdered(ReportingCase):

    def test_medication_sections_are_sorted(self):
        keys = [section.drug_canonical_key
                for section in self.report().medications]
        self.assertEqual(keys, sorted(keys))

    def test_axes_are_sorted_inside_each_section(self):
        for section in self.report().medications:
            keys = [(axis.drug_canonical_key, axis.gene_canonical_key)
                    for axis in section.axes]
            with self.subTest(drug=section.drug_canonical_key):
                self.assertEqual(keys, sorted(keys))

    def test_observations_are_sorted(self):
        genes = [item["gene_id"]
                 for item in self.report().profile_observations]
        self.assertEqual(genes, sorted(genes))

    def test_evidence_and_conflict_references_are_sorted(self):
        report = self.report()
        self.assertEqual(list(report.evidence_references),
                         sorted(report.evidence_references))
        self.assertEqual(list(report.conflict_references),
                         sorted(report.conflict_references))


if __name__ == "__main__":
    unittest.main()
