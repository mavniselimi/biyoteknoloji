# -*- coding: utf-8 -*-
"""F. Escaping and injection.

A case label, a medication name or a canonical key is data. Rendered raw, a
value containing ``#`` becomes a heading, one containing ``|`` adds a table
column, one containing ``<script>`` becomes an element, and one containing a
newline ends whatever block it was in and starts something else.

Two layers stop that, and both are tested here: values carrying prose or
control characters are **refused** before they reach the renderer, and values
that are legal but hostile are **escaped** so they render as themselves.
"""

from __future__ import annotations

import re
import unittest

from pgx.reporting.errors import ReportInputError
from pgx.reporting.models import AxisFacts, MedicationFacts
from pgx.reporting.render import (MARKDOWN_ESCAPES,
                                  UNSAFE_IN_CODE_SPAN, escape_markdown)
from pgx.reporting.render import render_markdown
from tests.fixtures.wp13.synthetic import DRUG_1, GENE_1, GENE_2
from tests.fixtures.wp15.synthetic import INJECTION_CASE_IDS
from tests.unit.reporting._support import ReportingCase


class TestTheEscaper(unittest.TestCase):

    def test_a_heading_marker_cannot_start_a_heading(self):
        self.assertFalse(escape_markdown("# Rapor onaylandi").startswith("#"))

    def test_a_block_marker_cannot_start_a_block(self):
        """Every block-opening character is either backslash-escaped or
        replaced by an HTML entity, so the value begins as text."""
        for value in ("- madde", "* madde", "+ madde", "1. madde",
                      "2) madde", "> alinti", "# baslik", "=== ustcizgi",
                      ". nokta"):
            with self.subTest(value=value):
                rendered = escape_markdown(value)
                self.assertRegex(rendered, r"^(?:\\|&)")

    def test_a_pipe_cannot_add_a_table_column(self):
        self.assertNotIn("|", escape_markdown("A | B | C").replace("\\|", ""))

    def test_an_html_element_cannot_survive(self):
        rendered = escape_markdown("<script>alert(1)</script>")
        self.assertNotIn("<", rendered)
        self.assertNotIn(">", rendered)
        self.assertIn("&lt;", rendered)

    def test_an_ampersand_cannot_start_an_entity(self):
        self.assertEqual(escape_markdown("&lt;"), "&amp;lt;")

    def test_a_link_cannot_be_created(self):
        rendered = escape_markdown("[tikla](https://example.invalid)")
        self.assertNotIn("[tikla]", rendered)

    def test_emphasis_markers_are_escaped(self):
        self.assertEqual(escape_markdown("**GUVENLI**"),
                         "\\*\\*GUVENLI\\*\\*")

    def test_a_fence_cannot_open_a_code_block(self):
        rendered = escape_markdown("```\nrm -rf /\n```")
        self.assertNotIn("```", rendered)
        self.assertNotIn("\n", rendered)

    def test_a_newline_becomes_visible_text(self):
        rendered = escape_markdown("a\nb")
        self.assertNotIn("\n", rendered)
        self.assertTrue(rendered.endswith("nb"), rendered)
        self.assertEqual(escape_markdown("a\r\nb"), rendered)

    def test_a_control_character_becomes_a_visible_escape(self):
        for character, marker in (("\x07", "x07"), ("\x00", "x00"),
                                  ("\x1b", "x1B")):
            with self.subTest(character=repr(character)):
                rendered = escape_markdown("case%sid" % character)
                self.assertNotIn(character, rendered)
                self.assertIn(marker, rendered)

    def test_none_renders_as_nothing_not_as_a_repr(self):
        self.assertEqual(escape_markdown(None), "")

    def test_two_different_values_never_render_identically(self):
        """Deleting a control character rather than escaping it would make
        two different values indistinguishable in a document."""
        self.assertNotEqual(escape_markdown("case\x07id"),
                            escape_markdown("caseid"))

    def test_the_escape_set_is_published(self):
        for character in "\\`*_[]#+|~":
            with self.subTest(character=character):
                self.assertIn(character, MARKDOWN_ESCAPES)

    def test_the_code_span_exclusion_set_is_published(self):
        for character in "`|<>&*[]()#+~\\":
            with self.subTest(character=character):
                self.assertIn(character, UNSAFE_IN_CODE_SPAN)

    def test_governed_code_punctuation_keeps_its_code_span(self):
        """Underscore and hyphen are excluded on purpose: escaping them would
        print a governed code that is no longer that code."""
        for character in "_-":
            with self.subTest(character=character):
                self.assertNotIn(character, UNSAFE_IN_CODE_SPAN)

    def test_every_escaped_metacharacter_is_backslashed(self):
        for character in MARKDOWN_ESCAPES:
            with self.subTest(character=character):
                self.assertEqual(escape_markdown(character),
                                 "\\" + character)


class TestHostileValuesAreRefusedBeforeRendering(unittest.TestCase):
    """Prose in a reference field is refused, not escaped.

    Escaping a newline would render it safely; refusing it says something
    stronger, which is that a governed reference is not where narrative
    arrives.
    """

    def test_a_newline_in_a_canonical_key_is_refused(self):
        with self.assertRaises(ReportInputError):
            AxisFacts(drug_canonical_key=DRUG_1,
                      gene_canonical_key="GENE:A\n# heading",
                      coverage_status="FULL")

    def test_a_newline_in_a_requested_value_is_refused(self):
        with self.assertRaises(ReportInputError):
            MedicationFacts(drug_canonical_key=DRUG_1,
                            requested_value="drug\n# heading",
                            attention_level="NOT_ASSESSED",
                            coverage_status="INSUFFICIENT",
                            coverage_reason_codes=("PHENOTYPE_NOT_PROVIDED",))

    def test_a_paragraph_in_a_rationale_reference_is_refused(self):
        from pgx.reporting.models import FindingFacts
        with self.assertRaises(ReportInputError):
            FindingFacts(drug_canonical_key=DRUG_1, gene_canonical_key=GENE_1,
                         phenotype="POOR", attention_level="HIGH",
                         rule_id="r", rule_family_id="f", rule_version=1,
                         rule_content_hash="sha256:" + "a" * 64,
                         rationale_reference="x" * 600,
                         curation_revision_id="c",
                         curation_revision_hash="sha256:" + "b" * 64,
                         evidence_references=("e",))


class TestHostileValuesInARealReport(unittest.TestCase):
    """The single-line hostile values that *are* legal, end to end."""

    #: The single-line hostile values. ``**GUVENLI**`` is excluded here and
    #: exercised in its own class below, because it trips the NOT_ASSESSED
    #: line check - which is the correct outcome and a different property.
    HOSTILE = tuple(value for _name, value in INJECTION_CASE_IDS
                    if "\n" not in value and "\x00" not in value
                    and "\x07" not in value and "GUVENLI" not in value)

    @classmethod
    def setUpClass(cls):
        from tests.fixtures.wp15.synthetic import report_world
        cls.world = report_world()

    @classmethod
    def tearDownClass(cls):
        cls.world.close()

    def render_with(self, medication):
        from pgx.application.report_service import ReportService
        from tests.fixtures.wp15.synthetic import stored_read_model
        view = stored_read_model(
            self.world, medications=(DRUG_1, medication),
            phenotypes={GENE_1: "POOR", GENE_2: "POOR"},
            case_id=medication)
        return ReportService().render_synthetic(view).markdown

    def test_a_hostile_medication_name_adds_no_heading_level(self):
        """It appears inside the section heading it belongs to, escaped, and
        opens no heading of its own."""
        text = self.render_with("# Rapor onaylandi")
        self.assertIn("### \\# Rapor onaylandi", text)
        self.assertNotIn("### # Rapor onaylandi", text)
        for line in text.splitlines():
            if not line.startswith("#"):
                continue
            with self.subTest(line=line):
                self.assertIsNone(re.match(r"^#{1,6}\s+#", line))

    def test_a_hostile_medication_name_cannot_add_a_table_column(self):
        """Every row of a table has the same number of unescaped pipes as its
        header, which is the property a pipe in a value would break."""
        text = self.render_with("A | B | C")
        block = []
        for line in text.splitlines() + [""]:
            if line.startswith("|"):
                block.append(line)
                continue
            if len(block) > 1:
                widths = {line.replace("\\|", "").count("|")
                          for line in block}
                with self.subTest(rows=len(block)):
                    self.assertEqual(len(widths), 1, block)
            block = []

    def test_a_hostile_medication_name_cannot_inject_html(self):
        text = self.render_with("<script>alert(1)</script>")
        self.assertNotIn("<script>", text)
        self.assertNotIn("</script>", text)
        self.assertIn("&lt;script&gt;", text)

    def test_a_hostile_medication_name_cannot_inject_a_link(self):
        text = self.render_with("[tikla](https://example.invalid)")
        self.assertNotIn("[tikla](https://example.invalid)", text)
        self.assertIn("\\[tikla\\]", text)

    def test_a_hostile_case_label_is_escaped_wherever_it_appears(self):
        text = self.render_with("**PARLAK**")
        self.assertNotIn("**PARLAK**", text)
        self.assertIn("\\*\\*PARLAK\\*\\*", text)

    def test_every_hostile_value_is_still_shown(self):
        """Escaped is not deleted: the reader must still see what was
        requested, or the report has hidden the input instead of neutralising
        it."""
        text = self.render_with("# Rapor onaylandi")
        self.assertIn("Rapor onaylandi", text)

    def test_hostile_but_inert_values_still_produce_a_clean_scan(self):
        from pgx.application.report_service import ReportService
        from tests.fixtures.wp15.synthetic import stored_read_model
        for value in self.HOSTILE:
            with self.subTest(value=value):
                view = stored_read_model(
                    self.world, medications=(DRUG_1, value),
                    phenotypes={GENE_1: "POOR", GENE_2: "POOR"},
                    case_id=value)
                produced = ReportService().render_synthetic(view)
                self.assertTrue(produced.claim_scan["is_clean"])


class TestAReassuringWordInSuppliedDataBlocksPublication(unittest.TestCase):
    """A documented, deliberate cost of the NOT_ASSESSED line check.

    The check asks whether a reassurance word shares a rendered line with
    ``NOT_ASSESSED``, and it does not ask where the word came from. A
    medication whose *name* contains one therefore blocks publication.

    That is the safe direction and it is chosen on purpose. The alternative -
    exempting text that arrived as data - is exactly the exemption an attacker
    would use, and a reader looking at the line cannot tell which half of it
    was data either. The remedy is a curated display name, not a weaker check,
    and the refusal is loud and carries a stable code.
    """

    @classmethod
    def setUpClass(cls):
        from tests.fixtures.wp15.synthetic import report_world
        cls.world = report_world()

    @classmethod
    def tearDownClass(cls):
        cls.world.close()

    def test_a_medication_named_with_a_reassurance_word_is_refused(self):
        from pgx.application.report_service import ReportService
        from pgx.reporting.errors import ReportFactError
        from tests.fixtures.wp15.synthetic import stored_read_model
        view = stored_read_model(
            self.world, medications=(DRUG_1, "GUVENLI-ilac"),
            phenotypes={GENE_1: "POOR", GENE_2: "POOR"},
            case_id="TEST-CASE-1")
        with self.assertRaises(ReportFactError) as caught:
            ReportService().render_synthetic(view)
        self.assertEqual(caught.exception.code,
                         "REPORT_STATUS_RENDERING_UNSAFE")

    def test_the_same_medication_without_the_word_publishes(self):
        from pgx.application.report_service import ReportService
        from tests.fixtures.wp15.synthetic import stored_read_model
        view = stored_read_model(
            self.world, medications=(DRUG_1, "DRUG:testdrug-zeta"),
            phenotypes={GENE_1: "POOR", GENE_2: "POOR"},
            case_id="TEST-CASE-1")
        produced = ReportService().render_synthetic(view)
        self.assertTrue(produced.claim_scan["is_clean"])


if __name__ == "__main__":
    unittest.main()
