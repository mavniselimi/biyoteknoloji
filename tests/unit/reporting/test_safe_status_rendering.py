# -*- coding: utf-8 -*-
"""D. Safe status rendering.

The legacy renderer's central defect was a label: ``RISK_LABEL_TR["none"]``
was *"Düşük / uyarı yok"* - low, no warning - and it was printed for an axis
nothing had been evaluated on (``LEGACY-BUG-002``). These tests assert that
the same three situations now render as three different coverage statuses
beside ``NOT_ASSESSED``, and that no arrangement of this reporting layer can
put a reassuring word next to one.
"""

from __future__ import annotations

import dataclasses
import unittest

from pgx.reporting.errors import ReportFactError, ReportInputError
from pgx.reporting.render import render_markdown
from pgx.reporting.structured import (UNSAFE_NOT_ASSESSED_WORDS, OverallStatus,
                                      build_structured_report)
from pgx.reporting.templates import (ATTENTION_LABELS, SUPPORTED_LOCALES,
                                     statement)
from pgx.reporting.validator import (UNSAFE_LINE_TOKENS,
                                     validate_rendered_report,
                                     validate_safe_status_rendering)
from tests.fixtures.wp13.synthetic import (DRUG_1, DRUG_2, GENE_1, GENE_2,
                                           GENE_3, UNKNOWN_DRUG)
from tests.unit.reporting._support import ReportingCase


def _fold(text):
    from pgx.reporting.validator import _fold as fold
    return fold(text)


class TestAttentionAndCoverageAreAlwaysTogether(ReportingCase):

    def test_every_status_block_carries_both(self):
        report = self.report()
        blocks = [report.overall] + [section.status
                                     for section in report.medications]
        for status in blocks:
            with self.subTest(attention=status.attention_code):
                self.assertTrue(status.attention_code)
                self.assertTrue(status.coverage_code)
                self.assertTrue(status.attention_label)
                self.assertTrue(status.coverage_label)

    def test_every_status_block_says_they_are_separate_results(self):
        report = self.report()
        for status in [report.overall] + [section.status
                                          for section in report.medications]:
            with self.subTest(attention=status.attention_code):
                self.assertEqual(status.adjacency_note,
                                 statement("attention_and_coverage", "tr"))

    def test_they_are_rendered_adjacently(self):
        """Adjacent, not merely both present somewhere in the document."""
        text = render_markdown(self.report())
        lines = text.splitlines()
        attention_rows = [index for index, line in enumerate(lines)
                          if line.startswith("| Dikkat kodu |")]
        self.assertTrue(attention_rows)
        for index in attention_rows:
            window = lines[index:index + 4]
            with self.subTest(line=index):
                self.assertTrue(any(line.startswith("| Kapsam kodu |")
                                    for line in window))

    def test_the_validator_accepts_this_report(self):
        record = validate_safe_status_rendering(self.report())
        self.assertTrue(record["checked_blocks"])


class TestNotAssessedIsNeverReassuring(ReportingCase):

    def test_the_label_is_the_controlled_one(self):
        for locale in SUPPORTED_LOCALES:
            with self.subTest(locale=locale):
                report = self.report(locale)
                section = report.section_for(UNKNOWN_DRUG)
                self.assertEqual(section.status.attention_code,
                                 "NOT_ASSESSED")
                self.assertEqual(section.status.attention_label,
                                 ATTENTION_LABELS["NOT_ASSESSED"][locale])

    def test_the_label_contains_no_reassuring_word(self):
        for locale in SUPPORTED_LOCALES:
            folded = _fold(ATTENTION_LABELS["NOT_ASSESSED"][locale])
            for token in UNSAFE_LINE_TOKENS:
                with self.subTest(locale=locale, token=token):
                    self.assertNotIn(token, folded)

    def test_the_published_word_list_covers_the_legacy_label(self):
        """The legacy phrase was 'Düşük / uyarı yok'. Both halves are on the
        list, so the check that protects against it is the check that would
        have caught it."""
        self.assertIn("dusuk", UNSAFE_NOT_ASSESSED_WORDS)
        self.assertIn("uyari yok", UNSAFE_NOT_ASSESSED_WORDS)
        self.assertIn("dusuk", UNSAFE_LINE_TOKENS)
        self.assertIn("uyari yok", UNSAFE_LINE_TOKENS)

    def test_no_rendered_line_puts_a_reassuring_word_beside_it(self):
        for locale in SUPPORTED_LOCALES:
            report = self.report(locale)
            text = render_markdown(report)
            for number, line in enumerate(text.splitlines(), start=1):
                if "NOT_ASSESSED" not in line:
                    continue
                folded = _fold(line)
                for token in UNSAFE_LINE_TOKENS:
                    with self.subTest(locale=locale, line=number,
                                      token=token):
                        self.assertNotIn(token, folded)

    def test_it_always_carries_the_controlled_sentence(self):
        report = self.report()
        section = report.section_for(UNKNOWN_DRUG)
        self.assertTrue(section.status.carries(statement("not_assessed",
                                                         "tr")))

    def test_a_reassuring_label_is_refused(self):
        report = self.report()
        section = report.section_for(UNKNOWN_DRUG)
        forged = dataclasses.replace(section.status,
                                     attention_label="Düşük / uyarı yok")
        broken = dataclasses.replace(
            report,
            medications=tuple(
                dataclasses.replace(item, status=forged)
                if item.drug_canonical_key == UNKNOWN_DRUG else item
                for item in report.medications))
        with self.assertRaises(ReportFactError) as caught:
            validate_safe_status_rendering(broken)
        self.assertEqual(caught.exception.code,
                         "REPORT_STATUS_RENDERING_UNSAFE")

    def test_dropping_the_controlled_sentence_is_refused(self):
        report = self.report()
        section = report.section_for(UNKNOWN_DRUG)
        forged = section.status
        object.__setattr__(forged, "qualifier_statements",
                           (statement("full_coverage", "tr"),))
        broken = dataclasses.replace(
            report,
            medications=tuple(
                dataclasses.replace(item, status=forged)
                if item.drug_canonical_key == UNKNOWN_DRUG else item
                for item in report.medications))
        with self.assertRaises(ReportFactError) as caught:
            validate_safe_status_rendering(broken)
        self.assertEqual(caught.exception.code,
                         "REPORT_STATUS_RENDERING_UNSAFE")

    def test_a_reassuring_line_in_the_rendered_text_is_refused(self):
        report = self.report()
        text = render_markdown(report).replace(
            "| `NOT_ASSESSED` |",
            "| `NOT_ASSESSED` (dusuk) |")
        with self.assertRaises(ReportFactError) as caught:
            validate_rendered_report(report, text)
        self.assertEqual(caught.exception.code,
                         "REPORT_STATUS_RENDERING_UNSAFE")


class TestPartialCoverageIsProminent(ReportingCase):

    def test_a_level_over_partial_coverage_carries_the_subset_sentence(self):
        report = self.report()
        partial = [section for section in report.medications
                   if section.status.coverage_code == "PARTIAL"
                   and section.status.attention_code in ("HIGH", "MEDIUM",
                                                         "LOW")]
        self.assertTrue(partial)
        for section in partial:
            with self.subTest(drug=section.drug_canonical_key):
                self.assertTrue(section.status.carries(statement(
                    "high_attention_partial_coverage", "tr")))

    def test_that_sentence_says_it_is_the_worst_of_the_evaluated_subset(self):
        text = statement("high_attention_partial_coverage", "tr")
        self.assertIn("yalnızca değerlendirilebilen eksenler", text)
        english = statement("high_attention_partial_coverage", "en")
        self.assertIn("evaluated subset", english)

    def test_partial_coverage_shows_its_reason_codes(self):
        for section in self.report().medications:
            if section.status.coverage_code == "FULL":
                continue
            with self.subTest(drug=section.drug_canonical_key):
                self.assertTrue(section.status.reason_codes)

    def test_partial_coverage_shows_every_missing_axis(self):
        report = self.report()
        text = render_markdown(report)
        record = validate_rendered_report(report, text)
        self.assertGreater(record["checked_facts"], 0)
        for section in report.medications:
            if section.status.coverage_code != "PARTIAL":
                continue
            for axis in section.not_assessed_axes:
                with self.subTest(gene=axis.gene_canonical_key):
                    self.assertIn(axis.gene_canonical_key, text)

    def test_removing_the_subset_sentence_is_refused(self):
        report = self.report()
        sections = []
        for section in report.medications:
            if section.status.coverage_code == "PARTIAL":
                object.__setattr__(section.status, "qualifier_statements",
                                   (statement("partial_coverage", "tr"),))
            sections.append(section)
        with self.assertRaises(ReportFactError) as caught:
            validate_safe_status_rendering(
                dataclasses.replace(report, medications=tuple(sections)))
        self.assertEqual(caught.exception.code,
                         "REPORT_STATUS_RENDERING_UNSAFE")


class TestFullCoverageInventsNoFailure(ReportingCase):

    #: No extra expected gene, so every declared axis is covered and the
    #: medication reaches FULL. That is the only shape in which "FULL invents
    #: no failure reason" is a statement about anything.
    WORLD_KWARGS = {"expected_extra_gene": False}
    MEDICATIONS = (DRUG_1,)
    PHENOTYPES = {GENE_1: "POOR", GENE_2: "POOR"}

    def test_a_fully_covered_medication_shows_no_reason_code(self):
        report = self.report()
        section = report.section_for(DRUG_1)
        self.assertEqual(section.status.coverage_code, "FULL")
        self.assertEqual(section.status.reason_codes, ())

    def test_it_still_says_what_full_coverage_means(self):
        section = self.report().section_for(DRUG_1)
        self.assertTrue(section.status.carries(statement("full_coverage",
                                                         "tr")))

    def test_an_invented_reason_on_full_coverage_is_refused(self):
        with self.assertRaises(ReportInputError):
            OverallStatus(attention_code="MEDIUM", attention_label="x",
                          coverage_code="FULL", coverage_label="y",
                          reason_codes=("SOME_AXES_NOT_COVERED",),
                          reason_labels=("z",), adjacency_note="n",
                          qualifier_statements=("q",))

    def test_the_validator_refuses_one_too(self):
        """The constructor refuses this, so the object is built valid and
        then mutated past it. Both layers check, because the validator is
        what runs over a report that arrived from somewhere else."""
        report = self.report()
        section = report.section_for(DRUG_1)
        forged = section.status
        object.__setattr__(forged, "reason_codes", ("SOME_AXES_NOT_COVERED",))
        object.__setattr__(forged, "reason_labels", ("invented",))
        broken = dataclasses.replace(
            report,
            medications=(dataclasses.replace(section, status=forged),))
        with self.assertRaises(ReportFactError) as caught:
            validate_safe_status_rendering(broken)
        self.assertEqual(caught.exception.code,
                         "REPORT_STATUS_RENDERING_UNSAFE")


class TestNoActiveAttentionNeedsFullCoverage(ReportingCase):

    def test_the_type_refuses_the_unsafe_pair(self):
        with self.assertRaises(ReportInputError) as caught:
            OverallStatus(attention_code="NO_ACTIVE_ATTENTION",
                          attention_label="x", coverage_code="PARTIAL",
                          coverage_label="y",
                          reason_codes=("SOME_AXES_NOT_COVERED",),
                          reason_labels=("z",), adjacency_note="n",
                          qualifier_statements=("q",))
        self.assertEqual(caught.exception.code,
                         "REPORT_STATUS_RENDERING_UNSAFE")

    def test_no_report_in_this_world_reaches_it(self):
        for section in self.report().medications:
            if section.status.attention_code != "NO_ACTIVE_ATTENTION":
                continue
            with self.subTest(drug=section.drug_canonical_key):
                self.assertEqual(section.status.coverage_code, "FULL")


class TestSourceConflictIsProminent(unittest.TestCase):

    def build(self):
        from pgx.reporting.models import (AxisFacts, CanonicalAssessmentResult,
                                          MedicationFacts)
        from pgx.reporting.validator import REQUIRED_PROVENANCE_FIELDS
        axis = AxisFacts(
            drug_canonical_key=DRUG_1, gene_canonical_key=GENE_1,
            coverage_status="SOURCE_CONFLICT",
            coverage_reason_codes=("VALIDATED_RULES_CONFLICT",),
            conflict_references=("TEST-CONFLICT-1", "TEST-CONFLICT-2"))
        medication = MedicationFacts(
            drug_canonical_key=DRUG_1, requested_value=DRUG_1,
            attention_level="NOT_ASSESSED", coverage_status="SOURCE_CONFLICT",
            coverage_reason_codes=("VALIDATED_RULES_CONFLICT",),
            axis_count=1, conflicted_axis_count=1, axes=(axis,))
        provenance = {name: ("sha256:" + "a" * 64) if name.endswith("_hash")
                      else "X" for name in REQUIRED_PROVENANCE_FIELDS}
        return CanonicalAssessmentResult(
            assessment_id="TEST-SYNTHETIC-CONFLICT", mode="DEMO",
            input_kind="SYNTHETIC_PHENOTYPE_PROFILE",
            input_hash="sha256:" + "b" * 64,
            output_hash="sha256:" + "c" * 64,
            coverage_result_hash="sha256:" + "d" * 64,
            overall_attention="NOT_ASSESSED",
            overall_coverage="SOURCE_CONFLICT",
            overall_coverage_reason_codes=("VALIDATED_RULES_CONFLICT",),
            medications=(medication,), release_provenance=provenance,
            pointer_audit={"active_pointer_generation": 1})

    def test_it_carries_the_controlled_sentence(self):
        report = build_structured_report(self.build())
        self.assertTrue(report.overall.carries(statement("source_conflict",
                                                         "tr")))

    def test_it_carries_the_not_assessed_sentence_as_well(self):
        """Both, not the first one that matched. A conflict that is also
        NOT_ASSESSED needs the reader told both things."""
        report = build_structured_report(self.build())
        self.assertTrue(report.overall.carries(statement("not_assessed",
                                                         "tr")))

    def test_that_sentence_says_the_conflict_is_preserved_not_resolved(self):
        text = statement("source_conflict", "tr")
        self.assertIn("çözülmemiş", text)
        self.assertIn("korunmuştur", text)

    def test_every_conflict_reference_is_displayed(self):
        report = build_structured_report(self.build())
        text = render_markdown(report)
        for reference in ("TEST-CONFLICT-1", "TEST-CONFLICT-2"):
            with self.subTest(reference=reference):
                self.assertIn(reference, text)

    def test_a_conflict_axis_without_its_reference_is_refused(self):
        report = build_structured_report(self.build())
        stripped = dataclasses.replace(report.medications[0],
                                       conflict_references=())
        with self.assertRaises(ReportFactError) as caught:
            validate_safe_status_rendering(
                dataclasses.replace(report, medications=(stripped,)))
        self.assertEqual(caught.exception.code,
                         "REPORT_CONFLICT_REFERENCE_LOST")

    def test_the_conflict_is_never_rendered_as_a_level(self):
        report = build_structured_report(self.build())
        self.assertEqual(report.overall.attention_code, "NOT_ASSESSED")
        text = render_markdown(report)
        for number, line in enumerate(text.splitlines(), start=1):
            if "SOURCE_CONFLICT" not in line:
                continue
            folded = _fold(line)
            for token in UNSAFE_LINE_TOKENS:
                with self.subTest(line=number, token=token):
                    self.assertNotIn(token, folded)


if __name__ == "__main__":
    unittest.main()
