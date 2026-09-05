# -*- coding: utf-8 -*-
"""SAFETY-INV-010: prohibited claim text must block release.

``LEGACY-BUG-012``: legacy carried source summaries containing dosing language
straight into user-facing output.

The safe control is the **shipped scanner**, ``pgx.domain.claims
.scan_claim_text``. Both directions are swept: prohibited text must block, and
compliant text must not - a scanner that blocked safe output would be switched
off within a week, which is a slower way of having no scanner.

The scanner's documented limits are real and are asserted here rather than
quietly assumed away: it is lexical, paraphrase evades it, and a clean scan
means "no known prohibited pattern was found", never "this text is safe".
"""

from __future__ import annotations

import unittest

from pgx.safety.controls import controls_for
from pgx.safety.evaluators import evaluate_no_prohibited_claim
from pgx.safety.vocabulary import InvariantId
from tests.fixtures.wp20 import unsafe_text
from tests.unit.safety._support import production_claim_scanner


def _evaluate(scanner, surfaces=None):
    return evaluate_no_prohibited_claim(
        scanner, surfaces if surfaces is not None else unsafe_text.SURFACES)


class TestTheShippedScannerBlocksAndPermits(unittest.TestCase):

    def setUp(self):
        self.verdict = _evaluate(production_claim_scanner())

    def test_it_is_compliant(self):
        self.assertTrue(self.verdict.compliant, self.verdict.violations)

    def test_every_surface_was_scanned(self):
        self.assertEqual(self.verdict.examined, len(unsafe_text.SURFACES))

    def test_all_three_release_surfaces_are_covered(self):
        """Report, API string and rendered template - not just the report."""
        surfaces = {label.split("/")[0] for label, _, _ in unsafe_text.SURFACES}
        self.assertEqual(surfaces, {"report", "api", "template"})

    def test_compliant_text_is_not_blocked(self):
        scan = production_claim_scanner()
        for label, text, blocking in unsafe_text.SURFACES:
            if blocking:
                continue
            with self.subTest(surface=label):
                self.assertFalse(scan(text).has_violations)

    def test_prohibited_text_is_blocked(self):
        scan = production_claim_scanner()
        for label, text, blocking in unsafe_text.SURFACES:
            if not blocking:
                continue
            with self.subTest(surface=label):
                self.assertTrue(scan(text).has_violations)

    def test_the_failure_mode_is_refusal_not_repair(self):
        """Never auto-edit the offending text into compliance."""
        from pgx.domain.claims import (ProhibitedClaimError,
                                       assert_claim_text_allowed)
        with self.assertRaises(ProhibitedClaimError):
            assert_claim_text_allowed(unsafe_text.SURFACES[3][1])

    def test_the_scanner_limits_stay_documented(self):
        """Structural checks supplement it; the limits are not hidden."""
        import io
        import os
        from tests.unit.safety._support import REPO_ROOT
        path = os.path.join(REPO_ROOT, "docs", "risk-management",
                            "safety-contract.md")
        with io.open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("lexical", text)
        self.assertIn("paraphrase evades it", text)


class TestTheScannerHasKnownGaps(unittest.TestCase):
    """A measured finding about the shipped scanner, not a WP-20 defect.

    Four unambiguously prohibited phrasings pass ``scan_claim_text`` clean.
    Two of them are not paraphrase at all - "We recommend X for this patient"
    is the most direct English form of a recommendation there is.

    WP-20 does not fix this. The pattern registry in ``pgx/domain/claims.py``
    is a reviewed governance artifact, and adding clinical phrasings to it on
    an implementer's judgement would be exactly the unreviewed claim the system
    exists to prevent. What WP-20 does is measure the gap, count it in the
    gate status, and hold it here so that closing one is visible.

    If a test in this class fails because the scanner now *catches* the
    phrasing, that is good news: move the entry from ``KNOWN_SCANNER_GAPS``
    into ``SURFACES`` and the count drops.
    """

    def test_each_known_gap_is_still_missed(self):
        scan = production_claim_scanner()
        for label, text in unsafe_text.KNOWN_SCANNER_GAPS:
            with self.subTest(gap=label):
                self.assertFalse(
                    scan(text).has_violations,
                    "%s is now caught by the scanner - move it from "
                    "KNOWN_SCANNER_GAPS into SURFACES and reduce the reported "
                    "gap count" % label)

    def test_the_gap_is_not_empty_and_not_unbounded(self):
        """A finding with no entries would be decoration; one with fifty would
        mean the scanner is not a control at all."""
        self.assertGreaterEqual(len(unsafe_text.KNOWN_SCANNER_GAPS), 1)
        self.assertLessEqual(len(unsafe_text.KNOWN_SCANNER_GAPS), 20)

    def test_a_structural_check_supplements_the_lexical_one(self):
        """The contract requires supplementary structural checks where the
        scanner is weak. The report layer refuses to release text it did not
        generate from a safe template, which does not depend on wording."""
        from pgx.reporting import gate
        self.assertTrue(hasattr(gate, "require_clean_report"))
        self.assertTrue(hasattr(gate, "gate_contract"))

    def test_the_gap_does_not_excuse_the_surfaces_that_do_work(self):
        """The three blocking surfaces are still blocked; a known gap
        elsewhere is not a reason to stop enforcing where enforcement works."""
        scan = production_claim_scanner()
        blocking = [text for _, text, expected in unsafe_text.SURFACES
                    if expected]
        self.assertEqual(len(blocking), 3)
        for text in blocking:
            with self.subTest(text=text[:40]):
                self.assertTrue(scan(text).has_violations)


class TestEveryNegativeControlIsDetected(unittest.TestCase):

    def test_each_prohibited_surface_is_blocked_by_the_real_scanner(self):
        scan = production_claim_scanner()
        for control in controls_for(InvariantId.INV_010):
            with self.subTest(control=control.control_id):
                surfaces = unsafe_text.UNSAFE_SUBJECTS[control.control_id]()
                verdict = evaluate_no_prohibited_claim(scan, surfaces)
                self.assertTrue(
                    verdict.compliant,
                    "%s: the shipped scanner failed to block prohibited text"
                    % control.control_id)

    def test_a_scanner_that_finds_nothing_is_rejected(self):
        """The mutant here is the *detector*, not the text: a scanner whose
        registry was emptied, or whose call site was commented out."""
        verdict = _evaluate(unsafe_text.permissive_scanner)
        self.assertFalse(verdict.compliant)
        self.assertEqual(verdict.refusal_code, "SAFETY_PROHIBITED_CLAIM")
        self.assertTrue(any("was released" in v for v in verdict.violations),
                        verdict.violations)

    def test_an_over_blocking_scanner_is_also_rejected(self):
        class _Always:
            has_violations = True

        verdict = _evaluate(lambda text: _Always())
        self.assertFalse(verdict.compliant)
        self.assertTrue(any("compliant text was blocked" in v
                            for v in verdict.violations), verdict.violations)

    def test_the_legacy_defect_is_mapped(self):
        controls = {c.control_id: c for c in controls_for(InvariantId.INV_010)}
        self.assertEqual(
            controls["NC-INV-010-REPORT-CARRIES-RECOMMENDATION"].legacy_bug,
            "LEGACY-BUG-012")
