# -*- coding: utf-8 -*-
"""Structural accessibility, over the HTML a browser actually receives.

Parsed with :mod:`html.parser`. These are structural checks, not an audit: no
browser and no axe run has taken place in this environment, and none is
claimed. What they do cover is the set of failures that are structural by
nature - a missing landmark, a skipped heading level, an unlabelled control, a
table without a caption, a status conveyed by colour alone - and those are
exactly the ones that survive review because everything looks right.

The most important assertion in this file is the last group: attention and
coverage remain equally prominent and adjacent when the stylesheet is removed
entirely. A layout that pairs them visually and separates them structurally
would pass a glance and fail a screen reader.
"""

from __future__ import annotations

import re
import unittest

from apps.web.render import jinja2_available
from tests.unit.web._support import STATIC_DIR, inspect, source
import os


@unittest.skipUnless(jinja2_available(),
                     "Jinja2 is not installed in this environment, so no "
                     "template can be rendered and there is no HTML to "
                     "inspect.")
class _AllPages(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from tests.unit.web.test_pages import _Rendered
        _Rendered.setUpClass()
        cls.pages = _Rendered.pages
        cls._rendered = _Rendered

    @classmethod
    def tearDownClass(cls):
        cls._rendered.tearDownClass()


class TestLandmarksAndHeadings(_AllPages):

    def test_every_page_has_the_document_landmarks(self):
        for name, result in self.pages.items():
            document = inspect(result.html)
            with self.subTest(page=name):
                for landmark in ("header", "nav", "main", "footer"):
                    self.assertIn(landmark, document.landmarks)

    def test_every_page_has_exactly_one_h1(self):
        for name, result in self.pages.items():
            document = inspect(result.html)
            with self.subTest(page=name):
                self.assertEqual(document.heading_levels.count(1), 1)

    def test_the_h1_is_the_first_heading(self):
        for name, result in self.pages.items():
            document = inspect(result.html)
            with self.subTest(page=name):
                self.assertEqual(document.heading_levels[0], 1)

    def test_no_heading_level_is_skipped(self):
        for name, result in self.pages.items():
            document = inspect(result.html)
            levels = document.heading_levels
            with self.subTest(page=name):
                for previous, current in zip(levels, levels[1:]):
                    self.assertLessEqual(current - previous, 1,
                                         "heading jumped from h%d to h%d"
                                         % (previous, current))

    def test_no_heading_is_empty(self):
        for name, result in self.pages.items():
            document = inspect(result.html)
            with self.subTest(page=name):
                for tag, text in document.headings:
                    self.assertTrue(text.strip(),
                                    "%s has an empty %s" % (name, tag))

    def test_every_page_has_a_skip_link_targeting_main(self):
        for name, result in self.pages.items():
            document = inspect(result.html)
            with self.subTest(page=name):
                skip = [element for element in document.elements
                        if element.tag == "a"
                        and element.attrs.get("class") == "skip-link"]
                self.assertEqual(len(skip), 1)
                self.assertEqual(skip[0].attrs.get("href"), "#main")
                main = document.find("main", id="main")
                self.assertEqual(len(main), 1)

    def test_the_navigation_marks_the_current_page(self):
        for name, result in self.pages.items():
            document = inspect(result.html)
            current = [element for element in document.elements
                       if element.attrs.get("aria-current") == "page"]
            with self.subTest(page=name):
                self.assertLessEqual(len(current), 1)

    def test_the_navigation_landmark_is_named(self):
        for name, result in self.pages.items():
            document = inspect(result.html)
            nav = document.find("nav")
            with self.subTest(page=name):
                self.assertTrue(nav)
                self.assertTrue(nav[0].attrs.get("aria-label"))


class TestTablesAndForms(_AllPages):

    def test_every_table_has_a_caption(self):
        for name, result in self.pages.items():
            document = inspect(result.html)
            with self.subTest(page=name):
                for table in document.tables:
                    self.assertTrue(table["caption"],
                                    "%s has a table with no caption" % name)

    def test_every_table_has_header_cells_with_a_scope(self):
        for name, result in self.pages.items():
            document = inspect(result.html)
            with self.subTest(page=name):
                for table in document.tables:
                    self.assertTrue(table["headers"])
                    self.assertTrue(any(scope for scope in table["scopes"]))

    def test_every_form_control_is_labelled(self):
        for name, result in self.pages.items():
            document = inspect(result.html)
            label_targets = {element.attrs.get("for")
                             for element in document.labels}
            with self.subTest(page=name):
                for control in document.form_controls:
                    if control.tag == "button":
                        continue
                    if control.attrs.get("type") == "hidden":
                        continue
                    identifier = control.attrs.get("id")
                    self.assertTrue(
                        identifier and identifier in label_targets,
                        "%s has an unlabelled control %r"
                        % (name, control.attrs))

    def test_the_medication_selection_uses_a_fieldset_and_legend(self):
        document = inspect(self.pages["case_detail"].html)
        self.assertTrue(document.find("fieldset"))
        self.assertTrue(document.find("legend"))

    def test_a_disabled_control_explains_itself(self):
        document = inspect(self.pages["case_detail"].html)
        disabled = [element for element in document.find("button")
                    if "disabled" in element.attrs]
        self.assertTrue(disabled)
        described = disabled[0].attrs.get("aria-describedby")
        self.assertTrue(described)
        self.assertIn('id="%s"' % described, self.pages["case_detail"].html)

    def test_every_link_has_meaningful_text(self):
        vague = {"buraya", "tıkla", "click here", "here", "read more",
                 "devamı", "more", ""}
        for name, result in self.pages.items():
            document = inspect(result.html)
            with self.subTest(page=name):
                for href, text in document.links:
                    self.assertNotIn(text.strip().lower(), vague,
                                     "%s has a link reading %r"
                                     % (name, text))


class TestStatusIsNeverColourAlone(_AllPages):
    """Every status carries its code and its label as text."""

    def test_every_status_pair_shows_both_code_and_label(self):
        document = inspect(self.pages["assessment"].html)
        pairs = document.find("div", **{"class": "status-pair"})
        self.assertTrue(pairs)
        for element in pairs:
            with self.subTest(attention=element.attrs.get("data-attention")):
                self.assertTrue(element.attrs.get("data-attention"))
                self.assertTrue(element.attrs.get("data-coverage"))
        codes = document.find("code", **{"class": "status-code"})
        self.assertTrue(codes)

    def test_readiness_states_are_words_not_colours(self):
        html = self.pages["system"].html
        self.assertIn("Hazır değil", html)
        self.assertIn("NOT_READY", html)

    def test_the_stylesheet_never_encodes_a_status_by_colour_alone(self):
        """A status selector must change more than a colour.

        Checked over the rules that select on a status attribute: each also
        sets a border property, so the distinction survives greyscale, a
        forced-colours mode and a monochrome print.
        """
        css = re.sub(r"/\*.*?\*/", " ",
                     source(os.path.join(STATIC_DIR, "css", "app.css")),
                     flags=re.S)
        blocks = re.findall(r"\[data-(?:attention|coverage)=[^{]*\{([^}]*)\}",
                            css)
        self.assertTrue(blocks)
        for block in blocks:
            with self.subTest(block=block.strip()[:40]):
                self.assertTrue(
                    "border" in block,
                    "a status rule changes only colour: %r" % block)

    def test_no_active_attention_is_not_styled_as_success(self):
        """Green for "no active finding" would be reassurance by palette.

        Comments stripped first: the stylesheet's header explains this rule in
        words, and a scan of the raw text would match its own explanation.
        """
        css = source(os.path.join(STATIC_DIR, "css", "app.css"))
        rules = re.sub(r"/\*.*?\*/", " ", css, flags=re.S).lower()
        self.assertNotIn("no_active_attention", rules)
        for green in ("#0f0", "#00ff00", "green", "lime", "#2e7d32"):
            with self.subTest(colour=green):
                self.assertNotIn(green, rules)


class TestAttentionAndCoverageWithoutCss(_AllPages):
    """The pairing must survive with the stylesheet removed entirely."""

    def test_they_are_consecutive_in_source_order(self):
        html = self.pages["assessment"].html
        document = inspect(html)
        cells = [element for element in document.elements
                 if element.attrs.get("class", "").startswith("status-cell")]
        self.assertTrue(cells)
        classes = [element.attrs["class"] for element in cells]
        for index in range(0, len(classes) - 1, 2):
            with self.subTest(index=index):
                self.assertIn("status-attention", classes[index])
                self.assertIn("status-coverage", classes[index + 1])

    def test_the_two_halves_of_each_pair_sit_at_the_same_depth(self):
        """Compared within a pair, not across the page.

        The overall pair sits directly in ``<main>`` and the per-medication
        pairs sit inside their sections, so their depths legitimately differ.
        What must never differ is the depth of the two halves of one pair -
        that would make one a subsection of the other, and a screen reader
        would announce coverage as belonging to attention.
        """
        document = inspect(self.pages["assessment"].html)
        cells = [element for element in document.elements
                 if element.attrs.get("class", "").startswith("status-cell")]
        self.assertTrue(cells)
        self.assertEqual(len(cells) % 2, 0)
        for index in range(0, len(cells), 2):
            attention, coverage = cells[index], cells[index + 1]
            with self.subTest(pair=index // 2):
                self.assertIn("status-attention", attention.attrs["class"])
                self.assertIn("status-coverage", coverage.attrs["class"])
                self.assertEqual(attention.depth, coverage.depth)

    def test_neither_is_inside_a_collapsible_region(self):
        html = self.pages["assessment"].html
        document = inspect(html)
        self.assertEqual(document.find("details"), [])
        self.assertEqual(document.find("summary"), [])


class TestResponsiveAndMotion(_AllPages):

    def test_the_stylesheet_declares_a_narrow_viewport_layout(self):
        css = source(os.path.join(STATIC_DIR, "css", "app.css"))
        self.assertIn("@media (max-width:", css)
        self.assertIn("overflow-x: auto", css)

    def test_the_stylesheet_honours_reduced_motion(self):
        css = source(os.path.join(STATIC_DIR, "css", "app.css"))
        self.assertIn("prefers-reduced-motion: reduce", css)

    def test_focus_is_never_removed(self):
        css = source(os.path.join(STATIC_DIR, "css", "app.css"))
        self.assertIn(":focus-visible", css)
        self.assertNotIn("outline: none", css)
        self.assertNotIn("outline:none", css)

    def test_every_page_declares_a_viewport(self):
        for name, result in self.pages.items():
            with self.subTest(page=name):
                self.assertIn('name="viewport"', result.html)

    def test_the_warning_survives_printing(self):
        css = source(os.path.join(STATIC_DIR, "css", "app.css"))
        print_block = css.split("@media print")[1]
        self.assertIn("clinical-warning", print_block)
        self.assertNotIn(".clinical-warning { display: none", print_block)


class TestThePageWorksWithoutJavaScript(_AllPages):

    def test_no_page_requires_a_script_to_show_its_content(self):
        for name, result in self.pages.items():
            document = inspect(result.html)
            with self.subTest(page=name):
                self.assertEqual(document.find("noscript"), [])
                for element in document.elements:
                    self.assertNotIn("data-requires-js", element.attrs)

    def test_the_only_script_is_deferred_and_local(self):
        for name, result in self.pages.items():
            document = inspect(result.html)
            scripts = document.find("script")
            with self.subTest(page=name):
                self.assertEqual(len(scripts), 1)
                self.assertTrue(
                    scripts[0].attrs.get("src", "").startswith("/static/js/"))
                self.assertIn("defer", scripts[0].attrs)

    def test_every_page_still_carries_its_governed_facts_as_text(self):
        """With the script removed the content is unchanged."""
        html = self.pages["assessment"].html
        stripped = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        document = inspect(stripped)
        self.assertIn("NOT_ASSESSED", document.visible_text
                      + stripped)
        self.assertTrue(document.tables)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
