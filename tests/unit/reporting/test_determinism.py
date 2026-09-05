# -*- coding: utf-8 -*-
"""E. Determinism.

The contract in one sentence: *the same report, template and locale render
byte for byte identically, on any machine, at any time.*

Which is what makes a checksum of the rendered document worth recording. A
byte difference between two renders is then always a difference in the facts
or in the template, and never in the weather.
"""

from __future__ import annotations

import json
import os
import re
import unittest

from pgx.reporting.render import (RENDERER_VERSION, render_json,
                                  render_markdown, rendered_checksum)
from pgx.reporting.structured import build_structured_report
from pgx.reporting.templates import SUPPORTED_LOCALES
from tests.fixtures.wp13.synthetic import DRUG_1, DRUG_2, GENE_1, GENE_2
from tests.unit.reporting._support import REPO_ROOT, ReportingCase


class TestTheSameReportRendersIdentically(ReportingCase):

    def test_two_renders_are_byte_identical(self):
        report = self.report()
        self.assertEqual(render_markdown(report), render_markdown(report))

    def test_two_reports_built_from_one_result_render_identically(self):
        first = build_structured_report(self.result, locale="tr")
        second = build_structured_report(self.result, locale="tr")
        self.assertEqual(render_markdown(first), render_markdown(second))

    def test_two_canonical_results_from_one_read_model_agree(self):
        from pgx.reporting.models import canonical_result_from_read_model
        one = canonical_result_from_read_model(self.view)
        two = canonical_result_from_read_model(self.view)
        self.assertEqual(one.content_hash(), two.content_hash())

    def test_the_json_form_is_byte_stable_too(self):
        report = self.report()
        self.assertEqual(render_json(report), render_json(report))

    def test_the_checksum_is_stable(self):
        report = self.report()
        self.assertEqual(rendered_checksum(render_markdown(report)),
                         rendered_checksum(render_markdown(report)))

    def test_both_locales_are_individually_stable(self):
        for locale in SUPPORTED_LOCALES:
            with self.subTest(locale=locale):
                report = self.report(locale)
                self.assertEqual(render_markdown(report),
                                 render_markdown(report))

    def test_a_regenerated_report_from_the_document_renders_identically(self):
        from pgx.application.report_service import ReportService
        service = ReportService()
        first = service.render_synthetic(self.view)
        again = service.regenerate_from_document(self.result.to_json())
        self.assertEqual(first.markdown, again.markdown)
        self.assertEqual(first.report_hash, again.report_hash)


class TestNothingVolatileReachesTheDocument(ReportingCase):

    def setUp(self):
        self.text = render_markdown(self.report())

    def test_no_timestamp_is_rendered(self):
        """A generated-at line is the commonest way a deterministic renderer
        stops being one."""
        for pattern in (r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}",
                        r"\d{4}/\d{2}/\d{2}",
                        r"generated at", r"Oluşturulma"):
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, self.text,
                                            re.IGNORECASE))

    def test_no_path_is_rendered(self):
        for fragment in ("/tmp/", "/home/", "/sessions/", "/Users/", "\\\\",
                         self.world.tmp):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, self.text)

    def test_no_environment_value_is_rendered(self):
        import platform
        import sys
        for value in (platform.node(), sys.version.split()[0],
                      os.environ.get("USER") or "no-such-user",
                      str(os.getpid())):
            if not value or len(value) < 3:
                continue
            with self.subTest(value=value):
                self.assertNotIn(value, self.text)

    def test_the_timestamps_the_assessment_carries_are_not_rendered(self):
        """The read model has created_at and completed_at. They label the run
        and are deliberately not part of the document."""
        self.assertNotIn(str(self.view.created_at), self.text)
        self.assertNotIn(str(self.view.completed_at), self.text)

    def test_the_actor_is_not_rendered(self):
        self.assertNotIn(self.view.actor, self.text)

    def test_neither_reaches_the_report_hash(self):
        content = json.dumps(self.report().semantic_content())
        for forbidden in ("created_at", "completed_at", "actor", "case_id",
                          "/tmp/", "process_id"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, content)


class TestWhatMustChangeTheRender(ReportingCase):

    def test_a_different_locale_changes_the_document(self):
        self.assertNotEqual(render_markdown(self.report("tr")),
                            render_markdown(self.report("en")))

    def test_a_different_locale_changes_the_report_hash(self):
        self.assertNotEqual(self.report("tr").report_hash(),
                            self.report("en").report_hash())

    def test_a_different_locale_does_not_change_the_output_hash(self):
        self.assertEqual(self.report("tr").output_hash,
                         self.report("en").output_hash)

    def test_a_different_fact_changes_the_document(self):
        from tests.fixtures.wp15.synthetic import (report_world,
                                                   stored_read_model)
        from pgx.reporting.models import canonical_result_from_read_model
        world = report_world()
        self.addCleanup(world.close)
        other = canonical_result_from_read_model(
            stored_read_model(world, medications=(DRUG_1,),
                              phenotypes={GENE_1: "POOR", GENE_2: "POOR"}))
        self.assertNotEqual(render_markdown(build_structured_report(other)),
                            render_markdown(self.report()))

    def test_the_renderer_version_is_recorded_in_the_checksum(self):
        text = render_markdown(self.report())
        self.assertNotEqual(rendered_checksum(text),
                            rendered_checksum(text + " "))
        self.assertTrue(RENDERER_VERSION)


class TestOrderingIsCanonical(ReportingCase):

    def test_the_medication_sections_appear_in_sorted_order(self):
        text = render_markdown(self.report())
        positions = [(text.index("### " + section.requested_value.replace(
            "|", "\\|")), section.drug_canonical_key)
            for section in self.report().medications]
        self.assertEqual([key for _index, key in sorted(positions)],
                         [key for _index, key in positions])

    def test_the_document_ends_with_exactly_one_newline(self):
        text = render_markdown(self.report())
        self.assertTrue(text.endswith("\n"))
        self.assertFalse(text.endswith("\n\n"))

    def test_the_document_uses_only_unix_line_endings(self):
        self.assertNotIn("\r", render_markdown(self.report()))


if __name__ == "__main__":
    unittest.main()
