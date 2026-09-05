# -*- coding: utf-8 -*-
"""The blind review workflow, rendered page by page.

Eight screens from a blinded assignment to a completed, corrected review,
driven by the real service, the real view model and the real template. Nothing
here is a human review: the reviewer is a fixture string, the protocol is a
TEST-ONLY approved document that exists only in this process, and the system
result comes from a static port. **No page produced below is evidence that any
expert looked at anything.**

The flow uses a system result that *disagrees* with the recorded expectation.
A demonstration in which the reviewer always turns out to be right shows only
the screen nobody needs: the interesting page is the one where the expectation
and the result differ and both are on screen at once, unedited.

Two properties are asserted on every screen rather than at the end, because
either would be a defect the moment it appeared anywhere:

* before a reveal record exists, no token of the system result appears in the
  serialized HTML - not in a table, an attribute, a hidden input or a comment;
* the forms are inert unless a CSRF token was issued, which no deployment can
  currently do.
"""

from __future__ import annotations

import unittest

from apps.web.claim_gate import scan_page
from apps.web.pages import render_expert_review_page
from apps.web.render import jinja2_available
from apps.web.view_models.pages import (ExpertReviewPageModel,
                                        build_expert_review_page)
from pgx.domain.claims import canonical_clinical_warning
from tests.fixtures.wp17.synthetic import REVIEWER_PRINCIPAL, page_environment
from tests.fixtures.wp22 import blind_review as F
from tests.unit.web._support import inspect

#: A result that differs from :data:`F.EXPECTED_BODY` in every governed field,
#: so "the result is not on the page yet" is a statement about the result and
#: not accidentally a statement about the expectation.
DISAGREEING_RESULT = dict(
    F.SYSTEM_RESULT,
    attention_level="ROUTINE",
    coverage_status="INSUFFICIENT",
    coverage_reason="PHENOTYPE_NOT_PROVIDED",
    firing_rule_id="TEST-ONLY-RULE-DIFFERENT",
    finding_count=7,
    traceable_finding_count=3,
)

#: Tokens that may not appear before a reveal.
#:
#: The bare words ``ROUTINE`` and ``INSUFFICIENT`` are unusable as leak
#: markers, because they are substrings of governed rationale codes the
#: blinded form legitimately offers (``INSUFFICIENT_INPUT``,
#: ``EVIDENCE_INSUFFICIENT``). Searching for them would fail on a page that
#: leaked nothing, and the natural repair - deleting the assertion - would
#: leave the leak untested. So the rendered cell is matched instead, which is
#: what a leak would actually look like. The output hash needs no such care:
#: it exists nowhere but in the system result. The result heading is matched
#: as its caption element rather than as bare words, because the reveal
#: button's own label ("Sistem sonucunu goster") contains the heading as a
#: substring and appears one screen earlier, by design.
RESULT_TOKENS = ("<td>ROUTINE</td>", "<td>INSUFFICIENT</td>",
                 "PHENOTYPE_NOT_PROVIDED", "TEST-ONLY-RULE-DIFFERENT",
                 F.RESULT_OUTPUT_HASH, "<caption>Sistem sonucu</caption>",
                 "Sistem dikkat düzeyi")

CSRF = "TEST-ONLY-csrf-token"


def _service():
    """A wired TEST-ONLY service, plus the port whose call count matters."""
    from pgx.expert_review.service import ExpertReviewService

    protocol = F.approved_protocol()
    store = F.InMemoryReviewStore((F.assignment(protocol=protocol),))
    port = F.StaticResultPort(DISAGREEING_RESULT)
    service = ExpertReviewService(
        protocol=protocol, store=store, result_port=port,
        clock=F.CountingClock(), id_factory=F.SequentialIds())
    return service, port


class TestTheBlindingHoldsInTheViewModel(unittest.TestCase):
    """Runs without Jinja2: the guarantee is in the model, not the template."""

    def test_a_blinded_page_has_no_result_and_asks_for_none(self):
        """The pre-reveal model carries no result and consults no port."""
        service, port = _service()
        view = service.view(case_id=F.CASE_ID, actor=F.REVIEWER,
                            role="EXPERT_REVIEWER")
        model = build_expert_review_page(F.CASE_ID, view=view,
                                         protocol=service.protocol)
        self.assertTrue(model.blinded)
        self.assertIsNone(model.result)
        self.assertEqual(port.call_count, 0)

    def test_the_model_rejects_the_blinded_and_result_combination(self):
        from apps.web.view_models.pages import RevealedResultSummary

        service, _port = _service()
        service.record_expectation(case_id=F.CASE_ID, actor=F.REVIEWER,
                                   role="EXPERT_REVIEWER",
                                   body=dict(F.EXPECTED_BODY))
        service.reveal(case_id=F.CASE_ID, actor=F.REVIEWER,
                       role="EXPERT_REVIEWER")
        view = service.view(case_id=F.CASE_ID, actor=F.REVIEWER,
                            role="EXPERT_REVIEWER")
        revealed = build_expert_review_page(F.CASE_ID, view=view,
                                            protocol=service.protocol)
        self.assertFalse(revealed.blinded)
        self.assertIsInstance(revealed.result, RevealedResultSummary)
        # The same result, on a page that says it is still blinded, is
        # refused rather than rendered.
        with self.assertRaises(ValueError) as raised:
            build = dict(
                case_id=revealed.case_id, state="EXPECTATION_RECORDED",
                blinded=True, available=True, forms_enabled=False,
                unavailable_note="", order_note="", no_disclosure_note="",
                blinded_note="", phases=(), release_public_id="",
                protocol_version="", protocol_approved=True,
                protocol_note="", result=revealed.result)
            ExpertReviewPageModel(**build)
        self.assertIn("blinded", str(raised.exception))

    def test_a_form_without_a_csrf_token_is_refused(self):
        with self.assertRaises(ValueError):
            ExpertReviewPageModel(
                case_id=F.CASE_ID, state="ASSIGNED", blinded=True,
                available=True, forms_enabled=True, unavailable_note="",
                order_note="", no_disclosure_note="", blinded_note="",
                phases=(), release_public_id="", protocol_version="",
                protocol_approved=True, protocol_note="", csrf_token=None)


@unittest.skipUnless(jinja2_available(),
                     "Jinja2 is not installed in this environment, so no page "
                     "can be rendered and the flow produces no HTML.")
class TestTheRenderedWorkflow(unittest.TestCase):
    """Eight screens, in the only order the service permits."""

    def setUp(self):
        self.env = page_environment()
        self.service, self.port = _service()
        self.protocol = self.service.protocol
        self.warning = canonical_clinical_warning("tr")
        self.screens = []

    # -- helpers ---------------------------------------------------------

    def _view(self, actor=F.REVIEWER, role="EXPERT_REVIEWER"):
        try:
            return self.service.view(case_id=F.CASE_ID, actor=actor,
                                     role=role)
        except Exception:  # noqa: BLE001 - refusals render the empty state
            return None

    def _screen(self, name, *, view=None, forms=True):
        """Render one screen and assert what must hold on every one of them."""
        result = render_expert_review_page(
            self.env, case_id=F.CASE_ID, view=view, protocol=self.protocol,
            csrf_token=CSRF if forms else None, forms_enabled=forms)
        self.screens.append((name, result))
        self.assertEqual(result.status, 200)
        # The clinical warning and the claim gate apply to review pages too.
        self.assertIn(self.warning, result.html)
        self.assertTrue(scan_page(result.html).is_clean)
        # And the standing disclaimer: recording a review correctly is not
        # evidence that a clinician looked at anything.
        self.assertIn("klinik geçerlilik kanıtı değildir", result.html)
        return result.html

    def _assert_no_result_tokens(self, html, screen):
        for token in RESULT_TOKENS:
            with self.subTest(screen=screen, token=token):
                self.assertNotIn(token, html)

    # -- the flow --------------------------------------------------------

    def test_the_blind_review_flow_completes(self):
        # 1. The blinded page. An assignment exists, the reviewer is the
        #    assignee, and the system result is nowhere on it.
        self.assertEqual(REVIEWER_PRINCIPAL.role.value, "EXPERT_REVIEWER")
        blinded = self._screen("blinded", view=self._view())
        self.assertIn(F.CASE_ID, blinded)
        self.assertIn(F.RELEASE_PUBLIC_ID, blinded)
        self.assertIn("Beklenen yanıtınız kilitlenene kadar", blinded)
        self._assert_no_result_tokens(blinded, "blinded")
        # The result port has not been asked for anything yet, which is a
        # stronger statement than "the page did not show it".
        self.assertEqual(self.port.call_count, 0)

        # 2. The expectation form, live, with a CSRF token and no result.
        document = inspect(blinded)
        names = {control.attrs.get("name") for control in
                 document.form_controls}
        self.assertIn("expected_attention_level", names)
        self.assertIn("csrf_token", names)
        for control in document.form_controls:
            with self.subTest(control=control.attrs.get("name")):
                self.assertNotIn("disabled", control.attrs)
        # No control could carry a result even if a template tried.
        self.assertNotIn("attention_level\"", blinded.replace(
            "expected_attention_level\"", ""))

        # 3. The locked receipt. Recording the expectation replaces the form
        #    with a receipt: it is not editable, and it carries the revision
        #    hash the reveal will pin.
        expectation = self.service.record_expectation(
            case_id=F.CASE_ID, actor=F.REVIEWER, role="EXPERT_REVIEWER",
            body=dict(F.EXPECTED_BODY))
        locked = self._screen("locked", view=self._view())
        self.assertIn(expectation.revision_hash(), locked)
        self.assertIn("HIGH", locked)
        self.assertIn("GUIDELINE_DIRECT", locked)
        self.assertNotIn("expected_attention_level", locked)
        self._assert_no_result_tokens(locked, "locked")
        self.assertEqual(self.port.call_count, 0)

        # 4. The reveal action, with its warning. This is the only screen
        #    that offers it, and it appears only once an expectation exists.
        self.assertIn("/expert-reviews/%s/reveal" % F.CASE_ID, locked)
        self.assertIn("geri alınamaz", locked)
        self.assertNotIn("/expert-reviews/%s/reveal" % F.CASE_ID, blinded)

        # 5. The revealed result, beside the locked expectation. Both are on
        #    screen, they disagree, and neither was edited to fit the other.
        reveal = self.service.reveal(case_id=F.CASE_ID, actor=F.REVIEWER,
                                     role="EXPERT_REVIEWER")
        revealed = self._screen("revealed", view=self._view())
        self.assertEqual(self.port.call_count, 1)
        self.assertIn("<td>ROUTINE</td>", revealed)
        self.assertIn("<td>INSUFFICIENT</td>", revealed)
        self.assertIn("TEST-ONLY-RULE-DIFFERENT", revealed)
        self.assertIn(F.RESULT_OUTPUT_HASH, revealed)
        self.assertIn("<caption>Sistem sonucu</caption>", revealed)
        # The result table carries its own row labels. Borrowing the
        # expectation's ("expected attention level" above a system value)
        # would mislabel the one comparison this screen exists to show.
        self.assertIn("Sistem dikkat düzeyi", revealed)
        self.assertIn("Sistemin çalıştırdığı kural", revealed)
        # The expectation is unchanged and still shows what was predicted.
        self.assertIn("HIGH", revealed)
        self.assertIn("TEST-ONLY-RULE-1", revealed)
        self.assertIn(expectation.revision_hash(), revealed)
        # The reveal names the revision it pinned, so a later amendment
        # cannot be mistaken for the prediction.
        self.assertEqual(reveal.expectation_revision_hash,
                         expectation.revision_hash())
        self.assertIn(reveal.expectation_revision_hash, revealed)
        # The reveal action is gone; there is nothing left to reveal.
        self.assertNotIn("/expert-reviews/%s/reveal" % F.CASE_ID, revealed)

        # 6-7. The decision form and the optional ratings, on one screen.
        self.assertIn("/expert-reviews/%s/complete" % F.CASE_ID, revealed)
        for choice in ("AGREE", "PARTIAL", "DISAGREE"):
            with self.subTest(choice=choice):
                self.assertIn('value="%s"' % choice, revealed)
        for dimension in ("CLARITY", "TRACEABILITY", "CLINICAL_USEFULNESS",
                          "SAFETY_FRAMING"):
            with self.subTest(dimension=dimension):
                self.assertIn("rating_%s" % dimension, revealed)
        # Not lowercased: Turkish "İ" lowercases to a combining sequence, so
        # a case-insensitive match here would silently stop matching.
        self.assertIn("İsteğe bağlı", revealed)

        # 8. The completed summary. Immutable, and the review is closed.
        self.service.complete(
            case_id=F.CASE_ID, actor=F.REVIEWER, role="EXPERT_REVIEWER",
            body={"decision": "DISAGREE",
                  "ratings": {"CLARITY": 4, "SAFETY_FRAMING": 2},
                  "reviewer_note": "TEST-ONLY note."})
        completed = self._screen("completed", view=self._view())
        self.assertIn("DISAGREE", completed)
        self.assertIn("CLARITY", completed)
        self.assertIn("SAFETY_FRAMING", completed)
        # A closed review offers no control at all, even with a token.
        self.assertNotIn("<form", completed)
        self.assertIn("değiştirilemez", completed)

        # 9. The correction history, append-only, marked as post-reveal.
        correction = self.service.append_correction(
            case_id=F.CASE_ID, actor=F.REVIEWER, role="EXPERT_REVIEWER",
            body={"target_hash": expectation.revision_hash(),
                  "kind": "RATIONALE_AMENDED",
                  "reason_code": "TEST_ONLY_CLARIFIED_WORDING"})
        corrected = self._screen("corrected", view=self._view())
        self.assertTrue(correction.after_reveal)
        self.assertIn("RATIONALE_AMENDED", corrected)
        self.assertIn("TEST_ONLY_CLARIFIED_WORDING", corrected)
        self.assertIn("gösterimden sonra", corrected)
        # The corrected record itself is still on the page, unedited.
        self.assertIn(expectation.revision_hash(), corrected)
        self.assertIn("HIGH", corrected)

        # The audit chain over the whole flow verifies.
        intact, reason = self.service.verify(
            F.review_id_for(F.CASE_ID))
        self.assertTrue(intact, reason)

    def test_every_screen_in_the_flow_is_clean(self):
        self.test_the_blind_review_flow_completes()
        for name, result in self.screens:
            with self.subTest(screen=name):
                self.assertTrue(scan_page(result.html).is_clean,
                                scan_page(result.html).to_json())

    def test_no_screen_accepts_free_text_beyond_the_governed_note(self):
        """A review page must not become a place to type patient detail."""
        blinded = self._screen("blinded", view=self._view())
        document = inspect(blinded)
        for control in document.form_controls:
            with self.subTest(control=control.attrs.get("name")):
                self.assertNotEqual(control.attrs.get("type"), "file")
                self.assertNotEqual(control.attrs.get("type"), "password")
        areas = document.find("textarea")
        self.assertEqual(len(areas), 1)
        self.assertEqual(areas[0].attrs.get("name"), "reviewer_note")
        self.assertEqual(areas[0].attrs.get("maxlength"), "1000")


@unittest.skipUnless(jinja2_available(),
                     "Jinja2 is not installed in this environment.")
class TestTheRefusalsAreIndistinguishable(unittest.TestCase):
    """Three different refusals, one page. Byte-identical, deliberately."""

    def setUp(self):
        self.env = page_environment()
        self.service, self.port = _service()

    def _empty_page(self, case_id=F.CASE_ID):
        return render_expert_review_page(
            self.env, case_id=case_id, view=None,
            protocol=self.service.protocol).html

    def test_unknown_not_holdout_and_another_reviewers_case_look_the_same(self):
        pages = {}
        for name, actor, case_id in (
                ("unknown", F.REVIEWER, "PGX-VAL-TEST-ONLY-NOSUCH-0001"),
                ("not-mine", F.OTHER_REVIEWER, F.CASE_ID),
                ("not-a-reviewer", F.ADMIN_ACTOR, F.CASE_ID)):
            with self.subTest(condition=name):
                try:
                    view = self.service.view(
                        case_id=case_id, actor=actor,
                        role=("EXPERT_REVIEWER" if actor != F.ADMIN_ACTOR
                              else "SYSTEM_ADMIN"))
                except Exception:  # noqa: BLE001 - every one refuses
                    view = None
                self.assertIsNone(view)
            pages[name] = render_expert_review_page(
                self.env, case_id=case_id, view=None,
                protocol=self.service.protocol).html
        # The two that name the same case are byte-identical. The third
        # differs only where the URL path segment is echoed back, which the
        # requester supplied and already knows.
        self.assertEqual(pages["not-mine"], pages["not-a-reviewer"])
        self.assertEqual(
            pages["unknown"].replace("PGX-VAL-TEST-ONLY-NOSUCH-0001",
                                     F.CASE_ID),
            pages["not-mine"])

    def test_the_empty_state_carries_no_form_and_no_result_field(self):
        html = self._empty_page()
        self.assertNotIn("<form", html)
        self.assertNotIn("csrf_token", html)
        for token in RESULT_TOKENS:
            with self.subTest(token=token):
                self.assertNotIn(token, html)
        self.assertIn("var olup olmadığını bildirmez", html)


if __name__ == "__main__":  # pragma: no cover - a developer entry point
    unittest.main()
