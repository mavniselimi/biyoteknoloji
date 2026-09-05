# -*- coding: utf-8 -*-
"""The synthetic end-to-end flow, run without a server.

Fifteen steps from the login screen to a second assessment, through the real
client, the real engine, the real templates and the real claim gate. No ASGI
server is involved, because none can run here - but everything below the HTTP
layer is the production path, and every page is HTML a browser could render.

**This flow is synthetic implementation evidence. It is not a clinical
assessment of anyone, and no page it produces may be presented as one.**

The mandatory insufficiency case is step 15 and is not optional: a
demonstration that only ever shows a covered result is a demonstration that
hides the state SAFETY-INV-001 exists for.
"""

from __future__ import annotations

import re
import unittest

from apps.web.claim_gate import scan_page
from apps.web.pages import (render_assessment_page, render_case_detail_page,
                            render_cases_page, render_evidence_page,
                            render_expert_review_page, render_home_page,
                            render_login_page, render_system_page,
                            render_validation_page)
from apps.web.render import jinja2_available
from apps.web.submission import build_assessment_request
from pgx.domain.claims import canonical_clinical_warning
from tests.fixtures.wp13.synthetic import DRUG_1, DRUG_2
from tests.fixtures.wp17.synthetic import (COVERED_FIXTURE_CASE,
                                           DEMO_PRINCIPAL, REVIEWER_PRINCIPAL,
                                           case_by_id, development_cases,
                                           execution_context,
                                           page_environment,
                                           synthetic_web_provider)
from tests.unit.web._support import inspect, synthetic_world

UNKNOWN_DRUG = "DRUG:unknown-medicine-x"


@unittest.skipUnless(jinja2_available(),
                     "Jinja2 is not installed in this environment, so no page "
                     "can be rendered and the flow cannot produce HTML.")
class TestTheSyntheticFlow(unittest.TestCase):
    """One operator, one synthetic case, every screen."""

    def setUp(self):
        self.world = synthetic_world()
        self.addCleanup(self.world.close)
        self.provider = synthetic_web_provider(self.world)
        self.env = page_environment()
        self.warning = canonical_clinical_warning("tr")
        self.visited = []

    def _visit(self, name, result):
        """Record a page and assert what must be true of every one of them."""
        self.visited.append((name, result))
        self.assertIn(self.warning, result.html)
        self.assertTrue(scan_page(result.html).is_clean)
        document = inspect(result.html)
        self.assertEqual(document.heading_levels.count(1), 1)
        self.assertEqual(result.headers["Cache-Control"], "no-store")
        return result

    def test_the_representative_flow_completes(self):
        # 1. The login screen, before anything is authenticated.
        login = self._visit("login", render_login_page(self.env))
        self.assertIn("yapılandırılmamıştır", login.html)

        # 2. A synthetic principal, injected. There is no route that mints one.
        principal = DEMO_PRINCIPAL
        context = execution_context(principal)

        # 3. The development case list.
        cases = development_cases()
        listing = self._visit("cases",
                              render_cases_page(self.env, cases=cases))
        self.assertIn("WP17-CASE-P2", listing.html)
        self.assertIn("DEVELOPMENT", listing.html)

        # 4-5. One case, its observations and the canonical medications.
        #
        # The covered fixture case rather than a migrated one. The six
        # migrated profiles name real genes and the synthetic world's ruleset
        # covers TESTGENE axes, so a migrated case here would legitimately
        # come back INSUFFICIENT with no finding and no evidence to follow -
        # which is demonstrated separately, twice, below.
        case = COVERED_FIXTURE_CASE
        detail = self._visit("case_detail", render_case_detail_page(
            self.env, case=case, client=self.provider.client))
        self.assertIn(case.observations[0].gene, detail.html)
        self.assertIn(DRUG_1, detail.html)

        # 6-7. Submit, and receive a persisted assessment through the client.
        request = build_assessment_request(case,
                                           medications=[DRUG_1, DRUG_2])
        response = self.provider.client.create_assessment(request,
                                                          context=context)
        self.assertTrue(response.document["persisted"])

        # 8-9. The assessment page, with attention and coverage adjacent.
        assessment = self._visit("assessment", render_assessment_page(
            self.env, document=response.document))
        attention = assessment.html.index("status-attention")
        coverage = assessment.html.index("status-coverage", attention)
        self.assertNotIn("<h2", assessment.html[attention:coverage])

        # The output hash on the page is the one the client received.
        self.assertIn(response.document["output_hash"], assessment.html)

        # 10-11. Follow an evidence link and check the provenance.
        links = re.findall(r'href="(/evidence/[0-9a-f-]{36})"',
                           assessment.html)
        self.assertTrue(links)
        evidence_id = links[0].rsplit("/", 1)[1]
        evidence = self.provider.client.get_evidence(
            evidence_id, request_id=self.env.request_id)
        evidence_page = self._visit("evidence", render_evidence_page(
            self.env, document=evidence.document))
        self.assertIn(evidence.document["content_hash"], evidence_page.html)
        self.assertIn(evidence.document["evidence_build_key"],
                      evidence_page.html)

        # 12. System information.
        system = self._visit("system",
                             render_system_page(self.env,
                                                client=self.provider.client))
        self.assertIn("NOT_READY", system.html)

        # 13. The validation empty state.
        validation = self._visit("validation", render_validation_page(
            self.env, development_case_count=len(cases)))
        self.assertIn("Kullanılamıyor", validation.html)

        # 14. The expert-review page, for a reviewer.
        #
        #     This step used to assert the page said the workflow was "not
        #     implemented". WP-22 implemented it, so that sentence would now
        #     be false and the assertion was defending a claim rather than a
        #     property. What it was really defending is that a reviewer with
        #     no assignment is told nothing: no case is confirmed to exist and
        #     no system result appears. That is what the successor pins, and
        #     it stays true after the workflow was built - which the old
        #     wording could not.
        self.assertEqual(REVIEWER_PRINCIPAL.role.value, "EXPERT_REVIEWER")
        review = self._visit("expert_review", render_expert_review_page(
            self.env, case_id="TEST-CASE-1"))
        # The controlled unavailable state, identical for a case that exists
        # and one that does not.
        self.assertIn("size atanmış etkin bir inceleme yok", review.html)
        self.assertIn("var olup olmadığını bildirmez", review.html)
        # The protocol is a draft, and the page says so rather than offering
        # a workflow that cannot lawfully run.
        self.assertIn("TASLAK", review.html)
        # No control can submit, because nothing here is authenticated yet.
        self.assertNotIn("<form", review.html)
        # And - the point of the whole module - the serialized page carries no
        # system result, in any block, hidden field or attribute.
        for leak in ("expert-result", "system_result", "Sistem sonucu",
                     "attention_level", "coverage_status"):
            with self.subTest(leak=leak):
                self.assertNotIn(leak, review.html)

        # 15a. A migrated profile against this ruleset. The six migrated
        #      profiles describe real genes; the synthetic world's released
        #      ruleset governs TESTGENE axes. Those axes therefore receive no
        #      phenotype at all from this profile, which is a different
        #      insufficiency from "no rule exists for this axis": the axis is
        #      governed, the observation is ABSENT. The page has to say which
        #      of the two it is rather than render an empty result, so the
        #      assertion pins the reason code the engine actually derives.
        migrated = case_by_id("WP17-CASE-P2")
        migrated_response = self.provider.client.create_assessment(
            build_assessment_request(migrated, medications=[DRUG_1]),
            context=context)
        migrated_page = self._visit("migrated_insufficient",
                                    render_assessment_page(
                                        self.env,
                                        document=migrated_response.document))
        self.assertEqual(migrated_response.document["status"]["coverage"],
                         "INSUFFICIENT")
        self.assertEqual(migrated_response.document["status"]["attention"],
                         "NOT_ASSESSED")
        self.assertIn("PHENOTYPE_NOT_PROVIDED", migrated_page.html)
        self.assertIn("ABSENT", migrated_page.html)
        # The distinction is only meaningful if the other code is genuinely
        # absent here, so that a future engine change cannot quietly collapse
        # the two insufficiencies into one without failing this test.
        self.assertNotIn("NO_VALIDATED_RULE_FOR_AXIS", migrated_page.html)

        # 15b. The authored insufficiency case.
        insufficient_case = case_by_id("WP17-CASE-INSUFFICIENT")
        insufficient_request = build_assessment_request(
            insufficient_case, medications=[UNKNOWN_DRUG])
        insufficient = self.provider.client.create_assessment(
            insufficient_request, context=context)
        page = self._visit("insufficient", render_assessment_page(
            self.env, document=insufficient.document))
        self.assertEqual(insufficient.document["status"]["attention"],
                         "NOT_ASSESSED")
        self.assertIn("Değerlendirilmedi", page.html)
        self.assertIn("UNSUPPORTED_DRUG", page.html)

        self.assertEqual(len(self.visited), 10)

    def test_the_flow_reads_the_release_pointer_once_per_assessment(self):
        case = case_by_id("WP17-CASE-P1")
        context = execution_context()
        before = self.world.resolver.pointer_reads
        self.provider.client.create_assessment(
            build_assessment_request(case, medications=[DRUG_1]),
            context=context)
        self.assertEqual(self.world.resolver.pointer_reads - before, 1)

    def test_presentation_never_changes_the_output_hash(self):
        case = case_by_id("WP17-CASE-P1")
        response = self.provider.client.create_assessment(
            build_assessment_request(case, medications=[DRUG_1]),
            context=execution_context())
        before = response.document["output_hash"]
        render_assessment_page(self.env, document=response.document)
        fetched = self.provider.client.get_assessment(
            response.document["assessment_id"],
            request_id=self.env.request_id)
        self.assertEqual(fetched.document["output_hash"], before)

    def test_an_old_assessment_stays_pinned_after_the_release_moves(self):
        case = case_by_id("WP17-CASE-P1")
        response = self.provider.client.create_assessment(
            build_assessment_request(case, medications=[DRUG_1]),
            context=execution_context())
        pinned = response.document["release"]["release_public_id"]
        page_before = render_assessment_page(self.env,
                                             document=response.document).html

        self.world.resolver.move_pointer()

        fetched = self.provider.client.get_assessment(
            response.document["assessment_id"],
            request_id=self.env.request_id)
        page_after = render_assessment_page(self.env,
                                            document=fetched.document).html
        self.assertIn(pinned, page_after)
        self.assertEqual(
            re.sub(r"<time[^>]*>.*?</time>", "", page_before),
            re.sub(r"<time[^>]*>.*?</time>", "", page_after))

    def test_no_page_in_the_flow_carries_a_prohibited_claim(self):
        self.test_the_representative_flow_completes()
        for name, result in self.visited:
            with self.subTest(page=name):
                report = scan_page(result.html)
                self.assertTrue(report.is_clean, report.to_json())

    def test_development_cases_are_never_counted_as_validation(self):
        cases = development_cases()
        page = render_validation_page(self.env,
                                      development_case_count=len(cases)).html
        self.assertIn("Geliştirme vakası sayısı", page)
        self.assertIn("doğrulama kanıtı değildir", page)
        for case in cases:
            with self.subTest(case=case.case_id):
                self.assertFalse(case.is_validation_evidence)

    def test_no_page_accepts_free_text_or_personal_data(self):
        case = case_by_id("WP17-CASE-P1")
        detail = render_case_detail_page(self.env, case=case,
                                         client=self.provider.client)
        document = inspect(detail.html)
        for control in document.form_controls:
            with self.subTest(control=control.attrs.get("name")):
                self.assertNotEqual(control.attrs.get("type"), "file")
                self.assertNotEqual(control.attrs.get("type"), "password")
                self.assertIn(control.attrs.get("name", "csrf_token"),
                              ("medications", "csrf_token"))
        self.assertEqual(document.find("textarea"), [])


class TestTheGateStatusAgreesWithTheHost(unittest.TestCase):
    """Runs everywhere, including without Jinja2 and without a browser.

    This class used to assert that no browser existed, that no screenshot was
    committed and that no ASGI test had run. Those were true statements about
    the machine WP-17 was built on, written as if they were properties of the
    repository - so the moment a browser was installed, three honest
    measurements started failing and the only way to make them pass again
    would have been to stop measuring.

    The property actually worth defending is narrower and survives both
    environments: **the gate status must describe this host, and a committed
    screenshot must be backed by a browser that can run.** A capture with no
    browser is a fabricated artifact; a browser with no capture is fine and
    ordinary. So the implication is checked in one direction only.
    """

    @classmethod
    def setUpClass(cls):
        from apps.web.gate_status import build_ui_gate_status

        cls.status = build_ui_gate_status()

    #: The one place a browser capture may live. An image anywhere else under
    #: the fixtures is not evidence of anything, because nothing writes one
    #: there.
    CAPTURE_DIR = ("tests", "fixtures", "wp17", "browser")

    def _images_under_fixtures(self):
        import os

        from tests.unit.web._support import REPO_ROOT

        fixtures = os.path.join(REPO_ROOT, "tests", "fixtures", "wp17")
        found = []
        if os.path.isdir(fixtures):
            for root, _dirs, files in os.walk(fixtures):
                for name in sorted(files):
                    if name.lower().endswith((".png", ".jpg", ".jpeg",
                                              ".webp", ".gif")):
                        found.append(os.path.join(root, name))
        return found

    def test_a_committed_image_is_a_real_capture_file(self):
        """Genuineness, not local capability.

        The first version of this asked whether *this host* could launch a
        browser, and failed on any machine that merely lacked one - a
        colleague's laptop, a lint job, the repository's own host running a
        bare interpreter. That is not the property worth defending: a
        repository with captures checked in is perfectly ordinary on a machine
        with no browser.

        What must not happen is a *fabricated* capture. So each committed
        image is checked for being what it claims: a real PNG, of a size a
        rendered page actually produces, in the one directory the capture path
        writes to. Nothing else in the repository writes an image, so an image
        anywhere else is unexplained by construction.
        """
        import os

        from tests.unit.web._support import REPO_ROOT

        capture_dir = os.path.join(REPO_ROOT, *self.CAPTURE_DIR)
        for path in self._images_under_fixtures():
            relative = os.path.relpath(path, REPO_ROOT)
            with self.subTest(image=relative):
                self.assertEqual(
                    os.path.dirname(path), capture_dir,
                    "%s is outside the capture directory; nothing writes an "
                    "image there" % relative)
                self.assertTrue(path.lower().endswith(".png"),
                                "%s is not a PNG" % relative)
                with open(path, "rb") as handle:
                    self.assertEqual(handle.read(8), b"\x89PNG\r\n\x1a\n",
                                     "%s is not a PNG" % relative)
                self.assertGreater(os.path.getsize(path), 1024, relative)

    def test_the_screenshot_status_matches_what_is_on_disk(self):
        import os

        from apps.web.gate_status import SCREENSHOT_DIR

        on_disk = sorted(
            name for name in (os.listdir(SCREENSHOT_DIR)
                              if os.path.isdir(SCREENSHOT_DIR) else [])
            if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")))
        self.assertEqual(list(self.status["screenshot_evidence_files"]),
                         on_disk)
        self.assertEqual(self.status["screenshot_evidence_count"],
                         len(on_disk))
        self.assertEqual(self.status["screenshot_evidence_status"],
                         "CAPTURED" if on_disk else "NONE")

    def test_the_browser_claim_is_a_launch_not_an_installed_package(self):
        """A package on the path is not a browser, and never counts as one."""
        from apps.web.gate_status import _BROWSER_BINARIES

        self.assertNotIn("playwright", _BROWSER_BINARIES)
        self.assertNotIn("selenium", _BROWSER_BINARIES)
        if self.status["browser_runtime_available"]:
            self.assertTrue(self.status["browser_binaries_found"]
                            or self.status["managed_browser_launchable"],
                            "a browser was claimed with neither a system "
                            "binary nor a launched managed browser behind it")
        if self.status["managed_browser_launchable"]:
            self.assertTrue(self.status["managed_browser_exists"])
            self.assertTrue(self.status["managed_browser_version"])

    def test_the_asgi_claim_matches_whether_the_stack_imports(self):
        import importlib

        importable = True
        for name in ("fastapi", "starlette", "uvicorn", "httpx", "multipart"):
            try:
                importlib.import_module(name)
            except Exception:  # noqa: BLE001
                importable = False
        self.assertEqual(self.status["asgi_runtime_tests_executed"],
                         importable)

    def test_no_rendered_snapshot_is_ever_called_a_capture(self):
        """The two kinds of artifact must not be described as one kind.

        Rendered HTML under ``snapshots/`` is template output; PNGs under
        ``browser/`` are captures. The note has to keep them apart whichever
        state the host is in.
        """
        note = self.status["screenshot_evidence_note"]
        self.assertIn("snapshots/", note)
        self.assertTrue("not browser captures" in note
                        or "not captures" in note, note)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
