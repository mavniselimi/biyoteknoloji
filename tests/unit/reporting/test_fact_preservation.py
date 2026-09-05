# -*- coding: utf-8 -*-
"""C. Fact preservation.

A report that dropped one evidence reference looks exactly like a report that
never had one. The ledger is what makes the difference detectable, and these
tests remove one fact at a time and check that the validator notices.
"""

from __future__ import annotations

import copy
import dataclasses
import unittest

from pgx.reporting.errors import ReportFactError
from pgx.reporting.validator import (FACT_LEDGER_SCHEMA_VERSION,
                                     REQUIRED_PROVENANCE_FIELDS,
                                     build_fact_ledger,
                                     validate_fact_preservation,
                                     validate_rendered_report)
from tests.fixtures.wp13.synthetic import DRUG_1, UNKNOWN_DRUG
from tests.unit.reporting._support import ReportingCase


class TestTheLedgerEnumeratesEveryFact(ReportingCase):

    def setUp(self):
        self.ledger = build_fact_ledger(self.result)

    def test_it_names_its_schema_version(self):
        self.assertEqual(self.ledger["fact_ledger_schema_version"],
                         FACT_LEDGER_SCHEMA_VERSION)

    def test_it_hashes_deterministically(self):
        self.assertEqual(build_fact_ledger(self.result)["ledger_hash"],
                         self.ledger["ledger_hash"])

    def test_it_lists_every_medication_axis_and_finding(self):
        self.assertEqual(len(self.ledger["medications"]),
                         len(self.result.medications))
        self.assertEqual(len(self.ledger["axes"]), len(self.result.axes))
        self.assertEqual(len(self.ledger["findings"]),
                         len(self.result.findings))

    def test_it_lists_every_evidence_reference(self):
        self.assertEqual(sorted(self.ledger["evidence_references"]),
                         sorted(self.result.evidence_references))
        self.assertTrue(self.ledger["evidence_references"])

    def test_it_lists_every_pinned_version(self):
        for name in REQUIRED_PROVENANCE_FIELDS:
            with self.subTest(field=name):
                self.assertTrue(self.ledger["release_provenance"][name])

    def test_it_counts_what_it_lists(self):
        counts = self.ledger["counts"]
        self.assertEqual(counts["axes"], len(self.ledger["axes"]))
        self.assertEqual(counts["findings"], len(self.ledger["findings"]))
        self.assertEqual(counts["observations"],
                         len(self.ledger["observations"]))


class TestAGoodReportPasses(ReportingCase):

    def test_the_report_this_result_produces_preserves_every_fact(self):
        ledger = validate_fact_preservation(self.result, self.report())
        self.assertEqual(ledger["ledger_hash"],
                         build_fact_ledger(self.result)["ledger_hash"])

    def test_both_locales_preserve_the_same_facts(self):
        for locale in ("tr", "en"):
            with self.subTest(locale=locale):
                validate_fact_preservation(self.result, self.report(locale))

    def test_the_rendered_document_shows_what_the_report_holds(self):
        from pgx.reporting.render import render_markdown
        report = self.report()
        ledger = validate_fact_preservation(self.result, report)
        record = validate_rendered_report(report, render_markdown(report),
                                          ledger)
        self.assertGreater(record["checked_facts"], 20)


class TestALostFactIsRefused(ReportingCase):

    def report_without(self, **changes):
        return dataclasses.replace(self.report(), **changes)

    def assertRefuses(self, report, code):
        with self.assertRaises(ReportFactError) as caught:
            validate_fact_preservation(self.result, report)
        self.assertEqual(caught.exception.code, code)

    def test_a_dropped_medication_is_refused(self):
        report = self.report()
        self.assertRefuses(
            dataclasses.replace(report, medications=report.medications[:-1]),
            "REPORT_FACT_LOST")

    def test_a_dropped_axis_is_refused(self):
        report = self.report()
        sections = list(report.medications)
        for index, section in enumerate(sections):
            if section.axes:
                sections[index] = dataclasses.replace(
                    section, axes=section.axes[:-1],
                    not_assessed_axes=tuple(
                        axis for axis in section.axes[:-1]
                        if not axis.is_covered))
                break
        self.assertRefuses(
            dataclasses.replace(report, medications=tuple(sections)),
            "REPORT_FACT_LOST")

    def test_a_dropped_finding_is_refused(self):
        report = self.report()
        sections = list(report.medications)
        for index, section in enumerate(sections):
            if section.findings:
                sections[index] = dataclasses.replace(
                    section, findings=section.findings[:-1])
                break
        self.assertRefuses(
            dataclasses.replace(report, medications=tuple(sections)),
            "REPORT_FACT_LOST")

    def test_a_dropped_evidence_reference_is_refused(self):
        report = self.report()
        sections = list(report.medications)
        for index, section in enumerate(sections):
            if section.findings:
                finding = section.findings[0]
                trimmed = dataclasses.replace(
                    finding,
                    evidence_references=finding.evidence_references[:1])
                sections[index] = dataclasses.replace(
                    section, findings=(trimmed,) + section.findings[1:],
                    evidence_references=tuple(
                        sorted(set(trimmed.evidence_references))))
                break
        self.assertRefuses(
            dataclasses.replace(report, medications=tuple(sections)),
            "REPORT_EVIDENCE_MISSING")

    def test_a_missing_pinned_version_is_refused(self):
        report = self.report()
        provenance = dict(report.release_provenance)
        provenance.pop("ruleset_content_hash")
        self.assertRefuses(
            dataclasses.replace(report, release_provenance=provenance),
            "REPORT_RELEASE_PROVENANCE_MISSING")

    def test_a_changed_pinned_version_is_refused(self):
        report = self.report()
        provenance = dict(report.release_provenance)
        provenance["ruleset_public_id"] = "PGX-RULESET-19700101-001"
        self.assertRefuses(
            dataclasses.replace(report, release_provenance=provenance),
            "REPORT_RELEASE_PROVENANCE_MISSING")

    def test_a_changed_rule_reference_is_refused(self):
        report = self.report()
        sections = list(report.medications)
        for index, section in enumerate(sections):
            if section.findings:
                finding = dataclasses.replace(
                    section.findings[0],
                    rule_content_hash="sha256:" + "0" * 64)
                sections[index] = dataclasses.replace(
                    section, findings=(finding,) + section.findings[1:])
                break
        self.assertRefuses(
            dataclasses.replace(report, medications=tuple(sections)),
            "REPORT_RULE_PROVENANCE_MISSING")

    def test_an_invented_effect_code_is_refused(self):
        report = self.report()
        sections = list(report.medications)
        for index, section in enumerate(sections):
            if section.findings:
                finding = dataclasses.replace(
                    section.findings[0], effect_code="DECREASED_ACTIVATION",
                    codes_absent_statement=None)
                sections[index] = dataclasses.replace(
                    section, findings=(finding,) + section.findings[1:])
                break
        self.assertRefuses(
            dataclasses.replace(report, medications=tuple(sections)),
            "REPORT_FACT_LOST")

    def test_an_invented_medication_is_refused(self):
        report = self.report()
        extra = dataclasses.replace(report.medications[0],
                                    drug_canonical_key="DRUG:invented")
        self.assertRefuses(
            dataclasses.replace(report,
                                medications=report.medications + (extra,)),
            "REPORT_ENTITY_NOT_PRESENT")

    def test_a_changed_status_is_refused(self):
        report = self.report()
        overall = dataclasses.replace(report.overall,
                                      attention_code="NOT_ASSESSED",
                                      attention_label="x")
        self.assertRefuses(dataclasses.replace(report, overall=overall),
                           "REPORT_FACT_LOST")

    def test_a_report_built_from_other_facts_is_refused(self):
        report = self.report()
        self.assertRefuses(
            dataclasses.replace(report,
                                canonical_result_hash="sha256:" + "0" * 64),
            "REPORT_HASH_MISMATCH")

    def test_a_changed_output_hash_is_refused(self):
        report = self.report()
        self.assertRefuses(
            dataclasses.replace(report, output_hash="sha256:" + "0" * 64),
            "REPORT_HASH_MISMATCH")

    def test_a_changed_coverage_hash_is_refused(self):
        report = self.report()
        self.assertRefuses(
            dataclasses.replace(report,
                                coverage_result_hash="sha256:" + "0" * 64),
            "REPORT_COVERAGE_UNVERIFIABLE")

    def test_a_dropped_observation_is_refused(self):
        report = self.report()
        self.assertRefuses(
            dataclasses.replace(
                report,
                profile_observations=report.profile_observations[:-1]),
            "REPORT_FACT_LOST")


class TestALostFactInTheRenderedTextIsRefused(ReportingCase):

    def test_a_removed_evidence_reference_is_noticed(self):
        from pgx.reporting.render import render_markdown
        report = self.report()
        text = render_markdown(report)
        reference = report.evidence_references[0]
        with self.assertRaises(ReportFactError) as caught:
            validate_rendered_report(report, text.replace(reference, "xxx"))
        self.assertEqual(caught.exception.code, "REPORT_FACT_LOST")

    def test_a_removed_warning_is_noticed(self):
        from pgx.reporting.render import render_markdown
        report = self.report()
        text = render_markdown(report).replace(report.canonical_warning, "")
        with self.assertRaises(ReportFactError) as caught:
            validate_rendered_report(report, text)
        self.assertIn(caught.exception.code,
                      ("REPORT_FACT_LOST", "REPORT_STATUS_RENDERING_UNSAFE"))

    def test_an_empty_document_is_refused(self):
        with self.assertRaises(ReportFactError):
            validate_rendered_report(self.report(), "   ")


class TestASourceConflictReferenceIsNeverLost(unittest.TestCase):
    """SAFETY-INV-008 in the reporting layer.

    The synthetic world produces no conflict - WP-13 is told about conflicts
    rather than detecting them - so the property is asserted on a report whose
    conflict references have been removed from the section while the
    assessment still records them.
    """

    def test_a_removed_conflict_reference_is_refused(self):
        import dataclasses
        from pgx.reporting.models import (AxisFacts, CanonicalAssessmentResult,
                                          MedicationFacts)
        from pgx.reporting.structured import build_structured_report
        axis = AxisFacts(
            drug_canonical_key=DRUG_1, gene_canonical_key="GENE:TESTGENE1",
            coverage_status="SOURCE_CONFLICT",
            coverage_reason_codes=("VALIDATED_RULES_CONFLICT",),
            conflict_references=("TEST-CONFLICT-1",))
        medication = MedicationFacts(
            drug_canonical_key=DRUG_1, requested_value=DRUG_1,
            attention_level="NOT_ASSESSED", coverage_status="SOURCE_CONFLICT",
            coverage_reason_codes=("VALIDATED_RULES_CONFLICT",),
            axis_count=1, conflicted_axis_count=1, axes=(axis,))
        provenance = {name: ("sha256:" + "a" * 64) if name.endswith("_hash")
                      else "X" for name in REQUIRED_PROVENANCE_FIELDS}
        result = CanonicalAssessmentResult(
            assessment_id="TEST-SYNTHETIC-1", mode="DEMO",
            input_kind="SYNTHETIC_PHENOTYPE_PROFILE",
            input_hash="sha256:" + "b" * 64,
            output_hash="sha256:" + "c" * 64,
            coverage_result_hash="sha256:" + "d" * 64,
            overall_attention="NOT_ASSESSED",
            overall_coverage="SOURCE_CONFLICT",
            overall_coverage_reason_codes=("VALIDATED_RULES_CONFLICT",),
            medications=(medication,), release_provenance=provenance,
            pointer_audit={"active_pointer_generation": 1})
        report = build_structured_report(result)
        self.assertEqual(report.conflict_references, ("TEST-CONFLICT-1",))
        validate_fact_preservation(result, report)

        stripped = dataclasses.replace(
            report.medications[0], conflict_references=())
        with self.assertRaises(ReportFactError) as caught:
            validate_fact_preservation(
                result, dataclasses.replace(report, medications=(stripped,)))
        self.assertEqual(caught.exception.code,
                         "REPORT_CONFLICT_REFERENCE_LOST")


if __name__ == "__main__":
    unittest.main()
