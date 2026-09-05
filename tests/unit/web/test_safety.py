# -*- coding: utf-8 -*-
"""Claim safety over real rendered HTML, and the adversarial cases.

Every controlled string this interface can display is scanned, and so is every
page it can produce. Then the gate is attacked directly: a claim split by a
tag, a claim hidden in an attribute, a claim in a comment, injected markup, an
injected URL, and a page that would carry executable content.

The scanner's limits are stated rather than implied. It is lexical: it matches
published patterns over folded text and performs no semantic analysis. A clean
scan means no published pattern matched. It is never evidence that a page is
safe, and no document in this work package says otherwise.
"""

from __future__ import annotations

import json
import unittest

from apps.web.claim_gate import (MAX_DISPLAY_LENGTH, PageSafetyError,
                                 check_display_value, extract_attribute_text,
                                 extract_visible_text, gate_contract,
                                 require_safe_page, scan_page)
from apps.web.errors import WEB_ERROR_GUIDANCE
from apps.web.labels import UI_TEXT
from apps.web.render import (TEMPLATE_NAMES, TemplateNotAllowedError,
                             jinja2_available, render_page, render_template)
from pgx.domain.claims import canonical_clinical_warning, scan_claim_text
from tests.fixtures.wp17.synthetic import page_environment
from tests.unit.web._support import source, template_paths


def _violations(text):
    report = scan_claim_text(text)
    return list(getattr(report, "violations", ()) or ())


class TestEveryControlledStringIsClean(unittest.TestCase):
    """Scanned as a fixed catalogue, so the request path never scans one."""

    def test_every_interface_string_is_clean(self):
        for key, table in UI_TEXT.items():
            for locale, value in table.items():
                with self.subTest(key=key, locale=locale):
                    self.assertEqual(_violations(value), [])

    def test_every_error_guidance_string_is_clean(self):
        for code, table in WEB_ERROR_GUIDANCE.items():
            for locale, value in table.items():
                with self.subTest(code=code, locale=locale):
                    self.assertEqual(_violations(value), [])

    def test_every_template_literal_is_clean(self):
        """The static text of each template, with the markup removed."""
        import re
        for path in template_paths():
            text = source(path)
            literals = re.sub(r"\{[%{#].*?[%}#]\}", " ", text, flags=re.S)
            literals = re.sub(r"<[^>]+>", " ", literals)
            with self.subTest(template=path.rsplit("/", 1)[-1]):
                self.assertEqual(_violations(literals), [])


@unittest.skipUnless(jinja2_available(),
                     "Jinja2 is not installed in this environment, so no page "
                     "can be rendered and there is no HTML to scan.")
class TestEveryRenderedPageIsClean(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from tests.unit.web.test_pages import _Rendered
        _Rendered.setUpClass()
        cls.pages = _Rendered.pages
        cls._rendered = _Rendered

    @classmethod
    def tearDownClass(cls):
        cls._rendered.tearDownClass()

    def test_every_success_page_passes_the_gate(self):
        for name, result in self.pages.items():
            with self.subTest(page=name):
                report = scan_page(result.html)
                self.assertTrue(report.is_clean,
                                "%s: %s" % (name, report.to_json()))

    def test_every_error_page_passes_the_gate(self):
        from apps.api.errors import ERROR_CATALOGUE
        from apps.web.pages import render_error_page
        environment = page_environment()
        for code in ERROR_CATALOGUE:
            with self.subTest(code=code):
                result = render_error_page(environment, code=code)
                self.assertTrue(scan_page(result.html).is_clean)

    def test_every_empty_state_passes_the_gate(self):
        from apps.web.client import UnavailableApiClient
        from apps.web.pages import (render_case_detail_page, render_cases_page,
                                    render_system_page,
                                    render_validation_page)
        from tests.fixtures.wp17.synthetic import case_by_id
        environment = page_environment()
        empties = {
            "cases": render_cases_page(environment, cases=(),
                                       available=False),
            "case": render_case_detail_page(
                environment, case=case_by_id("WP17-CASE-P1"),
                client=UnavailableApiClient()),
            "system": render_system_page(environment,
                                         client=UnavailableApiClient()),
            "validation": render_validation_page(environment,
                                                 development_case_count=0),
        }
        for name, result in empties.items():
            with self.subTest(page=name):
                self.assertTrue(scan_page(result.html).is_clean)

    def test_the_canonical_warning_passes_by_its_own_handling(self):
        """Not by a bypass: the scanner is run over the warning itself."""
        for locale in ("tr", "en"):
            with self.subTest(locale=locale):
                self.assertEqual(
                    _violations(canonical_clinical_warning(locale)), [])


class TestTheGateBlocksADirtyPage(unittest.TestCase):

    #: Each pair is a page the gate must refuse and the reason it must.
    ADVERSARIAL = {
        "plain claim": "<p>Bu ilaç güvenlidir.</p>",
        "claim split by a tag": "<p>Bu ilaç gü<b></b>venlidir.</p>",
        "claim split by a span": "<p>Bu ilaç gü<span>ven</span>lidir.</p>",
        "claim in a title attribute": "<p title='Bu ilaç güvenlidir'>x</p>",
        "claim in an aria-label": "<p aria-label='Bu ilaç güvenlidir'>x</p>",
        "claim in a data attribute": "<p data-note='Bu ilaç güvenlidir'>x</p>",
        "claim in a comment": "<!-- Bu ilaç güvenlidir --><p>x</p>",
        "english dosing claim": "<p>Reduce the dose to 50 mg daily.</p>",
        "english preference claim":
            "<p>Clopidogrel is the preferred alternative.</p>",
    }

    def test_every_adversarial_page_is_refused(self):
        for name, html in self.ADVERSARIAL.items():
            with self.subTest(case=name):
                report = scan_page(html)
                self.assertFalse(report.is_clean,
                                 "%s was not detected" % name)
                with self.assertRaises(PageSafetyError):
                    require_safe_page(html)

    def test_a_refusal_names_no_sentence(self):
        with self.assertRaises(PageSafetyError) as caught:
            require_safe_page("<p>Bu ilaç güvenlidir.</p>")
        rendered = str(caught.exception) + json.dumps(caught.exception.detail)
        self.assertNotIn("güvenlidir", rendered)

    def test_concatenated_text_defeats_tag_splitting(self):
        html = "<p>Bu ilaç gü<b></b>venlidir.</p>"
        self.assertNotIn("güvenlidir", extract_visible_text(html))
        self.assertFalse(scan_page(html).is_clean)

    def test_attribute_text_is_extracted(self):
        html = "<p title='gizli metin' aria-label='başka metin'>x</p>"
        extracted = extract_attribute_text(html)
        self.assertIn("gizli metin", extracted)
        self.assertIn("başka metin", extracted)


class TestTheGateBlocksUnsafeMarkup(unittest.TestCase):

    UNSAFE = {
        "inline script": "<script>alert(1)</script>",
        "script with content": "<script src='/x.js'>alert(1)</script>",
        "external script": "<script src='https://evil.example/x.js'></script>",
        "event handler": "<div onclick='x()'>y</div>",
        "event handler uppercase": "<div ONCLICK='x()'>y</div>",
        "inline style": "<div style='color:red'>y</div>",
        "iframe": "<iframe src='/x'></iframe>",
        "object": "<object data='/x'></object>",
        "javascript url": "<a href='javascript:alert(1)'>x</a>",
        "data url": "<img src='data:text/html,<script>'>",
        "protocol relative": "<a href='//evil.example'>x</a>",
        "external image": "<img src='https://evil.example/x.png'>",
        "external stylesheet":
            "<link rel='stylesheet' href='https://cdn.example/x.css'>",
        "external form action": "<form action='https://evil.example'></form>",
        "control character": "<p>a\x07b</p>",
    }

    def test_every_unsafe_page_is_refused(self):
        for name, html in self.UNSAFE.items():
            with self.subTest(case=name):
                self.assertFalse(scan_page(html).is_clean,
                                 "%s was not detected" % name)
                with self.assertRaises(PageSafetyError):
                    require_safe_page(html)

    def test_safe_internal_markup_is_allowed(self):
        safe = ("<a href='/cases/WP17-CASE-P1'>x</a>"
                "<a href='#main'>y</a>"
                "<link rel='stylesheet' href='/static/css/app.css?v=1'>"
                "<script src='/static/js/app.js' defer></script>"
                "<form action='/cases/WP17-CASE-P1/assess' method='post'>"
                "</form>")
        self.assertTrue(scan_page(safe).is_clean)

    def test_the_gate_publishes_its_limits(self):
        contract = gate_contract()
        self.assertIn("lexical", " ".join(contract["limits"]))
        self.assertIn("never evidence that a page is safe",
                      " ".join(contract["limits"]))


class TestDataOriginatedValuesAreChecked(unittest.TestCase):

    def test_a_control_character_is_refused(self):
        with self.assertRaises(PageSafetyError):
            check_display_value("a\x00b", location="$.x")

    def test_an_overlong_value_is_refused(self):
        with self.assertRaises(PageSafetyError):
            check_display_value("x" * (MAX_DISPLAY_LENGTH + 1),
                                location="$.x")

    def test_a_refusal_names_the_location_not_the_value(self):
        secret = "SECRET" + "\x07"
        with self.assertRaises(PageSafetyError) as caught:
            check_display_value(secret, location="$.case_id")
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertEqual(caught.exception.detail["location"], "$.case_id")


@unittest.skipUnless(jinja2_available(),
                     "Jinja2 is not installed, so escaping cannot be "
                     "exercised.")
class TestEscapingAndTemplateLoading(unittest.TestCase):

    def test_a_malicious_identifier_is_escaped_not_executed(self):
        from apps.web.pages import render_expert_review_page
        payload = "TEST<script>alert(1)</script>"
        result = render_expert_review_page(page_environment(),
                                           case_id=payload)
        self.assertNotIn("<script>alert(1)</script>", result.html)
        self.assertIn("&lt;script&gt;", result.html)

    def test_an_injected_attribute_break_is_escaped(self):
        from apps.web.pages import render_expert_review_page
        payload = 'x" onmouseover="alert(1)'
        result = render_expert_review_page(page_environment(),
                                           case_id=payload)
        self.assertNotIn('onmouseover="alert(1)"', result.html)

    def test_no_template_marks_a_data_value_safe(self):
        for path in template_paths():
            text = source(path)
            with self.subTest(template=path.rsplit("/", 1)[-1]):
                self.assertNotIn("|safe", text)
                self.assertNotIn("| safe", text)
                self.assertNotIn("autoescape false", text)
                self.assertNotIn("Markup(", text)

    def test_a_template_outside_the_allowlist_is_refused(self):
        for name in ("../../etc/passwd", "secret.html", "base.html/../x",
                     "/etc/passwd"):
            with self.subTest(name=name):
                with self.assertRaises(TemplateNotAllowedError):
                    render_template(name, {})

    def test_the_allowlist_matches_what_ships(self):
        present = sorted(path.rsplit("/", 1)[-1]
                         for path in template_paths())
        self.assertEqual(sorted(TEMPLATE_NAMES), present)

    def test_an_undefined_field_raises_rather_than_rendering_blank(self):
        from jinja2 import UndefinedError
        with self.assertRaises(UndefinedError):
            render_template("home.html", {})

    def test_the_gate_blocks_a_page_the_renderer_produced(self):
        """A dirty page is never returned, even from a real render."""
        import os
        import shutil
        import tempfile

        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        with open(os.path.join(directory, "home.html"), "w",
                  encoding="utf-8") as handle:
            handle.write("<html><body><p>Bu ilaç güvenlidir.</p></body></html>")
        with self.assertRaises(PageSafetyError):
            render_page("home.html", {}, directory=directory)


class TestNoUnsafeLanguageAnywhere(unittest.TestCase):
    """Terms that would turn a factual screen into a recommendation."""

    FORBIDDEN_TR = ("güvenli", "uygundur", "tercih edilir", "önerilir",
                    "tavsiye", "doz ayarla", "ilacı değiştir", "risk yok",
                    "sorun yok", "doğrulanmıştır", "onaylanmıştır")
    FORBIDDEN_EN = ("is safe", "is suitable", "preferred", "recommended",
                    "advise", "adjust the dose", "switch to", "no risk",
                    "validated for clinical", "clinically proven")

    #: Strings that contain a forbidden term in order to deny it.
    #:
    #: ``assessment.no_findings`` says that no finding does *not* mean the
    #: medicine is safe - which is the sentence SAFETY-INV-001 asks for, and
    #: it cannot be written without the word. Pinned by key so a new
    #: exception has to be added here deliberately, and checked below to be a
    #: genuine negation rather than an assertion with a caveat attached.
    NEGATION_EXCEPTIONS = {"assessment.no_findings"}

    def test_no_interface_string_uses_a_forbidden_term(self):
        for key, table in UI_TEXT.items():
            if key in self.NEGATION_EXCEPTIONS:
                continue
            for locale, value in table.items():
                lowered = value.lower()
                terms = (self.FORBIDDEN_TR if locale == "tr"
                         else self.FORBIDDEN_EN)
                for term in terms:
                    with self.subTest(key=key, locale=locale, term=term):
                        self.assertNotIn(term, lowered)

    #: The negation each exception must carry, per locale.
    NEGATION_MARKERS = {"tr": ("anlamına gelmez", "değildir", "gelmez"),
                        "en": ("does not mean", "is not")}

    def test_every_exception_is_a_genuine_negation(self):
        """No violation, and an explicit denial in the sentence itself.

        Two assertions rather than one, because the scanner alone is not
        enough here and the reason is worth recording. Given
        ``assessment.no_findings``:

        - the English sentence is *matched and suppressed* - the scanner sees
          "is safe", sees "does not mean", and reads the whole as a denial;
        - the Turkish sentence is *never matched at all* - no published
          pattern covers "güvenli olduğu anlamına gelmez", so the scanner
          reports neither a violation nor a suppression.

        That asymmetry is a real limit of a lexical scanner with uneven
        per-language coverage, and it is documented in
        ``docs/web/security-boundary.md`` rather than smoothed over. Requiring
        a suppression would fail on the Turkish string for a reason that has
        nothing to do with the string being wrong; requiring only the absence
        of a violation would pass a sentence the scanner simply cannot see. So
        both are checked: the scanner must not object, and the sentence must
        contain an explicit denial.
        """
        for key in self.NEGATION_EXCEPTIONS:
            for locale, value in UI_TEXT[key].items():
                report = scan_claim_text(value)
                with self.subTest(key=key, locale=locale):
                    self.assertEqual(
                        list(getattr(report, "violations", ()) or ()), [],
                        "%s/%s is not read as a denial" % (key, locale))
                    lowered = value.lower()
                    self.assertTrue(
                        any(marker in lowered
                            for marker in self.NEGATION_MARKERS[locale]),
                        "%s/%s contains a forbidden term without an explicit "
                        "denial" % (key, locale))

    def test_the_scanner_language_asymmetry_is_still_real(self):
        """Pinned, so the documented limitation stays accurate.

        If the scanner gains a Turkish pattern for this construction, this
        test fails and the documentation that describes the gap is updated
        rather than left stating something that stopped being true.
        """
        english = scan_claim_text(UI_TEXT["assessment.no_findings"]["en"])
        turkish = scan_claim_text(UI_TEXT["assessment.no_findings"]["tr"])
        self.assertTrue(getattr(english, "suppressed", ()),
                        "the English denial is no longer matched at all")
        self.assertEqual(list(getattr(turkish, "suppressed", ()) or ()), [],
                         "the scanner now matches the Turkish construction; "
                         "update docs/web/security-boundary.md")

    def test_the_exception_list_is_not_a_place_things_accumulate(self):
        self.assertLessEqual(len(self.NEGATION_EXCEPTIONS), 3)

    def test_no_interface_string_claims_validation(self):
        for key, table in UI_TEXT.items():
            for locale, value in table.items():
                lowered = value.lower()
                for term in ("doğrulama tamamlandı", "validation passed",
                             "validation complete", "başarıyla doğrulandı"):
                    with self.subTest(key=key, term=term):
                        self.assertNotIn(term, lowered)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
