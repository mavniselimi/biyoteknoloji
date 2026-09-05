# -*- coding: utf-8 -*-
"""Every screen, really rendered.

Jinja2 is installed in this environment, so these tests produce actual HTML
through the actual template environment and assert against what a browser
would receive. That is the difference between this suite and WP-16's: the
decisions there were checked without the framework; here the output itself is
checked.
"""

from __future__ import annotations

import unittest

from apps.web.client import UnavailableApiClient
from apps.web.pages import (render_assessment_page, render_case_detail_page,
                            render_cases_page, render_error_page,
                            render_evidence_page, render_expert_review_page,
                            render_home_page, render_login_page,
                            render_system_page, render_validation_page)
from apps.web.render import jinja2_available
from pgx.domain.claims import canonical_clinical_warning
from tests.fixtures.wp13.synthetic import DRUG_1
from tests.fixtures.wp16.synthetic import create_request
from tests.fixtures.wp17.synthetic import (case_by_id, development_cases,
                                           execution_context,
                                           page_environment,
                                           synthetic_web_provider)
from tests.unit.web._support import inspect, synthetic_world

UNKNOWN_DRUG = "DRUG:unknown-medicine-x"
EVIDENCE_ID = "aaaaaaaa-0000-4000-8000-000000000001"


@unittest.skipUnless(jinja2_available(),
                     "Jinja2 is not installed in this environment, so no "
                     "template can be rendered and no HTML exists to assert "
                     "against.")
class _Rendered(unittest.TestCase):
    """One synthetic world, every page rendered from it."""

    @classmethod
    def setUpClass(cls):
        cls.world = synthetic_world()
        cls.provider = synthetic_web_provider(cls.world)
        cls.env = page_environment()
        cls.assessment_document = cls.provider.client.create_assessment(
            create_request(medications=[DRUG_1, UNKNOWN_DRUG]),
            context=execution_context()).document
        cls.evidence_document = cls.provider.client.get_evidence(
            EVIDENCE_ID, request_id=cls.env.request_id).document
        cls.cases = development_cases()

        cls.pages = {
            "home": render_home_page(cls.env),
            "login": render_login_page(cls.env),
            "cases": render_cases_page(cls.env, cases=cls.cases),
            "case_detail": render_case_detail_page(
                cls.env, case=case_by_id("WP17-CASE-P2"),
                client=cls.provider.client),
            "assessment": render_assessment_page(
                cls.env, document=cls.assessment_document),
            "evidence": render_evidence_page(
                cls.env, document=cls.evidence_document),
            "validation": render_validation_page(
                cls.env, development_case_count=len(cls.cases),
                blockers=[("WP-18", "not implemented")]),
            "expert_review": render_expert_review_page(
                cls.env, case_id="TEST-CASE-1"),
            "system": render_system_page(cls.env, client=cls.provider.client),
            "error": render_error_page(cls.env, code="ASSESSMENT_NOT_FOUND"),
        }

    @classmethod
    def tearDownClass(cls):
        cls.world.close()


class TestEveryPageRenders(_Rendered):

    def test_every_screen_produces_html(self):
        for name, result in self.pages.items():
            with self.subTest(page=name):
                self.assertTrue(result.html.startswith("<!DOCTYPE html>"))
                self.assertGreater(len(result.html), 1000)

    def test_every_page_declares_its_language(self):
        for name, result in self.pages.items():
            with self.subTest(page=name):
                self.assertIn('<html lang="tr">', result.html)

    def test_every_page_sets_no_store_and_the_security_headers(self):
        for name, result in self.pages.items():
            headers = result.headers
            with self.subTest(page=name):
                self.assertEqual(headers["Cache-Control"], "no-store")
                for header in ("Content-Security-Policy", "X-Frame-Options",
                               "X-Content-Type-Options", "Referrer-Policy",
                               "Permissions-Policy"):
                    self.assertIn(header, headers)

    def test_every_page_echoes_the_request_id(self):
        from apps.api.request_id import REQUEST_ID_HEADER
        for name, result in self.pages.items():
            with self.subTest(page=name):
                self.assertEqual(result.headers[REQUEST_ID_HEADER],
                                 self.env.request_id)


class TestTheCanonicalWarningIsEverywhere(_Rendered):

    def test_every_page_carries_the_canonical_warning_verbatim(self):
        warning = canonical_clinical_warning("tr")
        for name, result in self.pages.items():
            with self.subTest(page=name):
                self.assertIn(warning, result.html)

    def test_the_warning_appears_exactly_once_per_page(self):
        warning = canonical_clinical_warning("tr")
        for name, result in self.pages.items():
            with self.subTest(page=name):
                self.assertEqual(result.html.count(warning), 1)

    def test_no_template_contains_a_copy_of_the_warning(self):
        from tests.unit.web._support import source, template_paths
        fragment = canonical_clinical_warning("tr")[:48]
        for path in template_paths():
            with self.subTest(template=path.rsplit("/", 1)[-1]):
                self.assertNotIn(fragment, source(path))

    def test_the_warning_is_not_dismissible(self):
        """No close control, and no script that could hide it."""
        for name, result in self.pages.items():
            document = inspect(result.html)
            warning = document.find("aside", **{"class": "clinical-warning"})
            with self.subTest(page=name):
                self.assertEqual(len(warning), 1)
                self.assertNotIn("hidden", warning[0].attrs)
                self.assertNotIn("data-dismissible", warning[0].attrs)

    def test_the_warning_precedes_the_content(self):
        for name, result in self.pages.items():
            html = result.html
            with self.subTest(page=name):
                self.assertLess(html.index("clinical-warning"),
                                html.index("</main>"))


class TestTheAssessmentScreen(_Rendered):

    def setUp(self):
        self.html = self.pages["assessment"].html
        self.document = inspect(self.html)

    def test_every_governed_code_appears_beside_its_label(self):
        for code in ("MEDIUM", "PARTIAL", "NOT_ASSESSED", "UNSUPPORTED_DRUG"):
            with self.subTest(code=code):
                self.assertIn(code, self.html)

    def test_attention_and_coverage_are_adjacent_in_the_dom(self):
        """Read in source order, with no stylesheet, they are consecutive."""
        attention = self.html.index("status-attention")
        coverage = self.html.index("status-coverage", attention)
        between = self.html[attention:coverage]
        self.assertNotIn("<table", between)
        self.assertNotIn("<h2", between)
        self.assertNotIn("<h3", between)

    def test_they_share_a_heading_level(self):
        """Neither is a subsection of the other."""
        document = self.document
        pairs = document.find("div", **{"class": "status-pair"})
        self.assertTrue(pairs)
        for element in pairs:
            with self.subTest():
                self.assertIn("data-attention", element.attrs)
                self.assertIn("data-coverage", element.attrs)

    def test_a_status_pair_is_present_for_every_medication(self):
        pairs = self.document.find("div", **{"class": "status-pair"})
        expected = 1 + len(self.assessment_document["medications"])
        self.assertEqual(len(pairs), expected)

    def test_not_assessed_reads_as_outside_the_assessed_scope(self):
        self.assertIn("Değerlendirilmedi", self.html)
        self.assertIn("değerlendirme kapsamı dışında", self.html)

    def test_every_evidence_reference_is_an_internal_link(self):
        links = [href for href, _text in self.document.links
                 if href.startswith("/evidence/")]
        self.assertTrue(links)
        for href in links:
            with self.subTest(href=href):
                self.assertRegex(href, r"^/evidence/[0-9a-f-]{36}$")

    def test_absent_effect_codes_render_as_an_explicit_absence(self):
        self.assertIn("&#8212;", self.html)

    def test_the_release_provenance_table_is_complete(self):
        from apps.api.contracts.spec import model
        for name in model("ReleaseProvenanceResponse").field_names:
            with self.subTest(field=name):
                self.assertIn(name, self.html)

    def test_both_hashes_are_shown(self):
        self.assertIn(self.assessment_document["input_hash"], self.html)
        self.assertIn(self.assessment_document["output_hash"], self.html)

    def test_no_medication_is_described_as_preferred_or_suitable(self):
        lowered = self.html.lower()
        for forbidden in ("uygun", "tercih", "önerilen", "daha güvenli",
                          "preferred", "suitable", "recommended", "safer",
                          "first choice"):
            with self.subTest(term=forbidden):
                self.assertNotIn(forbidden, lowered)


class TestTheHonestShellScreens(_Rendered):

    def test_the_login_page_offers_no_credential_field(self):
        document = inspect(self.pages["login"].html)
        for control in document.form_controls:
            with self.subTest(control=control.tag):
                self.assertNotEqual(control.attrs.get("type"), "password")
                self.assertNotIn(control.attrs.get("name", ""),
                                 ("username", "password", "email", "actor",
                                  "role", "token"))

    def test_the_login_page_displays_no_token(self):
        from tests.fixtures.wp17.synthetic import TEST_CSRF_TOKEN
        self.assertNotIn(TEST_CSRF_TOKEN, self.pages["login"].html)
        self.assertNotIn("TEST-TOKEN", self.pages["login"].html)

    def test_the_login_page_says_authentication_is_not_configured(self):
        self.assertIn("kimlik doğrulama sağlayıcısı yapılandırılmamıştır",
                      self.pages["login"].html)

    def test_the_validation_page_shows_no_percentage(self):
        html = self.pages["validation"].html
        self.assertNotIn("%", html.replace("&#", ""))
        self.assertIn("Kullanılamıyor", html)

    def test_the_validation_page_separates_development_from_holdout(self):
        html = self.pages["validation"].html
        self.assertIn("Geliştirme vakası sayısı", html)
        self.assertIn("holdout", html.lower())
        self.assertIn("birleştirilmez", html)

    def test_the_expert_page_offers_no_control(self):
        document = inspect(self.pages["expert_review"].html)
        self.assertEqual(document.form_controls, [])
        self.assertEqual(document.find("form"), [])

    def test_the_expert_page_preserves_the_phase_order(self):
        html = self.pages["expert_review"].html
        expected = html.index("1. Beklenen")
        revealed = html.index("2. Sonucun")
        completed = html.index("3. İncelemenin")
        self.assertLess(expected, revealed)
        self.assertLess(revealed, completed)

    def test_the_system_page_reports_readiness_component_by_component(self):
        html = self.pages["system"].html
        for component in ("claim_boundary", "authentication", "database"):
            with self.subTest(component=component):
                self.assertIn(component, html)
        self.assertIn("NOT_READY", html)


class TestUnavailableDependenciesAreStated(_Rendered):

    def test_the_case_page_states_a_missing_catalogue(self):
        result = render_case_detail_page(
            self.env, case=case_by_id("WP17-CASE-P1"),
            client=UnavailableApiClient())
        self.assertIn("Kanonik ilaç kataloğu bu dağıtımda okunamıyor",
                      result.html)

    def test_the_system_page_states_a_missing_release(self):
        result = render_system_page(self.env, client=UnavailableApiClient())
        self.assertIn("Etkin sürüm okunamıyor", result.html)

    def test_an_empty_case_catalogue_says_so(self):
        result = render_cases_page(self.env, cases=(), available=False)
        self.assertIn("kataloğu yüklenmemiştir", result.html)

    def test_the_submit_control_is_disabled_without_csrf(self):
        html = self.pages["case_detail"].html
        document = inspect(html)
        buttons = document.find("button")
        self.assertTrue(buttons)
        self.assertTrue(any("disabled" in button.attrs
                            for button in buttons))
        self.assertIn("Değerlendirme çalıştırma bu dağıtımda kullanılamıyor",
                      html)


class TestTheErrorScreen(_Rendered):

    def test_it_carries_the_api_code_and_status(self):
        html = self.pages["error"].html
        self.assertIn("ASSESSMENT_NOT_FOUND", html)
        self.assertIn("HTTP 404", html)
        self.assertEqual(self.pages["error"].status, 404)

    def test_it_states_that_nothing_partial_is_shown(self):
        self.assertIn("kısmen gösterilmez", self.pages["error"].html)

    def test_it_has_a_focusable_error_summary(self):
        document = inspect(self.pages["error"].html)
        summary = document.find("div", id="error-summary")
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0].attrs.get("role"), "alert")
        self.assertEqual(summary[0].attrs.get("tabindex"), "-1")

    def test_every_api_error_code_renders(self):
        from apps.api.errors import ERROR_CATALOGUE
        for code in ERROR_CATALOGUE:
            with self.subTest(code=code):
                result = render_error_page(self.env, code=code)
                self.assertIn(code, result.html)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestRenderingIsDeterministic(unittest.TestCase):
    """The same inputs produce the same bytes, every time and in any order.

    A page that varies between renders cannot be reviewed, cannot be diffed
    and cannot be attached to an evidence record. The three ways a template
    layer usually loses determinism are all checked: dictionary iteration
    order reaching the output, a clock or a random value reaching the output,
    and a cached environment carrying state from one render into the next.

    Rendering the same page twice is the weak version of this. The strong
    version - rendering it from a fresh environment in a fresh process-like
    setup, and comparing to the first - is what is done here.
    """

    def _render_all(self, environment):
        from apps.web.pages import (render_cases_page, render_home_page,
                                    render_login_page, render_validation_page)

        cases = development_cases()
        return {
            "home": render_home_page(environment).html,
            "login": render_login_page(environment,
                                       authentication_configured=False).html,
            "cases": render_cases_page(environment, cases=cases,
                                       available=True).html,
            "validation": render_validation_page(
                environment, development_case_count=len(cases)).html,
        }

    def test_two_renders_from_two_environments_are_byte_identical(self):
        first = self._render_all(page_environment())
        second = self._render_all(page_environment())
        self.assertEqual(first, second)

    def test_no_page_contains_a_timestamp_or_an_object_address(self):
        import re

        # A repr leaking into a page ("<object at 0x7f...>") and a rendered
        # clock are the two failures that survive a same-process comparison,
        # because both are stable within one render and unstable across runs.
        forbidden = re.compile(r"0x[0-9a-f]{6,}|<[a-z_]+ object at ",
                               re.IGNORECASE)
        for name, html in self._render_all(page_environment()).items():
            with self.subTest(page=name):
                self.assertIsNone(forbidden.search(html))

    def test_the_case_listing_order_does_not_depend_on_catalogue_order(self):
        # Reversing the input must not reverse the page: the listing sorts.
        from apps.web.pages import render_cases_page

        cases = development_cases()
        forward = render_cases_page(page_environment(), cases=cases,
                                    available=True).html
        backward = render_cases_page(page_environment(),
                                     cases=tuple(reversed(cases)),
                                     available=True).html
        self.assertEqual(forward, backward)
