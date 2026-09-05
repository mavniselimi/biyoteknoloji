# -*- coding: utf-8 -*-
"""SAFETY-INV-005: no candidate may be labelled safer, preferred or scored.

``LEGACY-BUG-009``: a 0-100 suitability score that mixed *we have data* with
*this is a good choice*. P0 ships no candidate exploration at all, so this is
enforced structurally and by detector, exactly as SAFETY-INV-002 is.
"""

from __future__ import annotations

import os
import unittest

from pgx.safety.controls import controls_for
from pgx.safety.definitions import definitions_by_id
from pgx.safety.evaluators import evaluate_no_candidate_preference
from pgx.safety.vocabulary import ComplianceState, InvariantId
from tests.fixtures.wp20 import unsafe_candidates
from tests.unit.safety._support import REPO_ROOT


def _evaluate(listing):
    return evaluate_no_candidate_preference([listing])


class TestTheFeatureIsStillAbsent(unittest.TestCase):

    def setUp(self):
        self.definition = definitions_by_id()["SAFETY-INV-005"]

    def test_the_registry_records_it_as_not_present(self):
        self.assertIs(self.definition.implementation_state,
                      ComplianceState.NOT_PRESENT)

    def test_no_candidate_module_exists(self):
        self.assertTrue(self.definition.absence_markers)
        for marker in self.definition.absence_markers:
            with self.subTest(marker=marker):
                self.assertFalse(
                    os.path.exists(os.path.join(REPO_ROOT,
                                                *marker.split("/"))),
                    "%s exists; SAFETY-INV-005 may no longer be reported "
                    "NOT_PRESENT" % marker)

    def test_the_claim_scanner_carries_the_category(self):
        """The scanner is the surface that catches preference language wherever
        it appears, feature or no feature."""
        from pgx.domain.claims import ProhibitedClaimCategory
        self.assertIn("CANDIDATE_PREFERENCE",
                      [c.value for c in ProhibitedClaimCategory])


class TestEveryNegativeControlIsDetected(unittest.TestCase):

    def test_a_data_status_listing_is_accepted(self):
        """Reporting what the dataset contains is legitimate and must stay so;
        a detector that blocked it would block the honest version too."""
        verdict = _evaluate(unsafe_candidates.SAFE_SUBJECT())
        self.assertTrue(verdict.compliant, verdict.violations)
        self.assertTrue(verdict.is_meaningful)

    def test_each_ranking_listing_is_rejected(self):
        for control in controls_for(InvariantId.INV_005):
            with self.subTest(control=control.control_id):
                build = unsafe_candidates.UNSAFE_SUBJECTS[control.control_id]
                verdict = _evaluate(build())
                self.assertFalse(verdict.compliant,
                                 "%s was NOT detected" % control.control_id)
                self.assertEqual(verdict.refusal_code,
                                 "SAFETY_CANDIDATE_PREFERENCE")

    def test_the_score_field_is_what_is_caught(self):
        verdict = _evaluate(unsafe_candidates.with_safety_score())
        self.assertTrue(any("safety_score" in v for v in verdict.violations),
                        verdict.violations)

    def test_ordering_alone_is_enough_to_be_caught(self):
        """No score, no label - still a ranking."""
        verdict = _evaluate(unsafe_candidates.ordered_by_attention())
        self.assertFalse(verdict.compliant)

    def test_preference_language_is_caught_in_both_languages(self):
        verdict = _evaluate(unsafe_candidates.preferred_label())
        self.assertFalse(verdict.compliant)
        joined = " ".join(verdict.violations)
        self.assertTrue("preferred" in joined or "guvenli" in joined, joined)

    def test_the_catalogue_and_the_fixtures_agree(self):
        declared = {c.control_id for c in controls_for(InvariantId.INV_005)}
        self.assertEqual(declared, set(unsafe_candidates.UNSAFE_SUBJECTS))
