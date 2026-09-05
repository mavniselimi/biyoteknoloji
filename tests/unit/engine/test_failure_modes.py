# -*- coding: utf-8 -*-
"""Missing, indeterminate and unsupported input (WP-12, section D).

Three ways of not having a phenotype, and they stay three ways all the way to
the match decision. That is the whole content of this file, and it is the
single most consequential design decision in the work package.

Collapsing them would be easy and would look tidy: all three fail to match, so
why not report ``NO_MATCH``? Because ``NO_MATCH`` is a statement about the
input - it says a phenotype was observed and the rule does not cover it -
while the other three say no phenotype was observed at all. Downstream,
WP-13 has to report the second class as an absence of coverage and WP-14 has
to report it as ``NOT_ASSESSED``. If the distinction is lost here, at the
earliest possible point, nothing downstream can recover it, and the system
reports "no rule applies" where the truth is "we could not look"
(``SAFETY-INV-001``).
"""

from __future__ import annotations

import unittest

from pgx.domain.enums import AttentionLevel, CoverageStatus, Phenotype
from pgx.engine.phenotype import match_observation
from pgx.engine.phenotype_models import MatchDecision, PhenotypeObservation
from pgx.rules.conditions import RULE_PHENOTYPES
from tests.fixtures.wp12.synthetic import exact, observation, one_of

FAILING_INPUTS = (
    (None, "MISSING", "INPUT_MISSING"),
    ("", "MISSING", "INPUT_MISSING"),
    ("INDETERMINATE", "INDETERMINATE", "INPUT_INDETERMINATE"),
    ("PM", "UNSUPPORTED", "INPUT_UNSUPPORTED"),
    ("decreased_function", "UNSUPPORTED", "INPUT_UNSUPPORTED"),
    ("*1/*2", "UNSUPPORTED", "INPUT_UNSUPPORTED"),
    (42, "UNSUPPORTED", "INPUT_UNSUPPORTED"),
)


class TestNoneOfThemEverMatches(unittest.TestCase):

    def test_no_failing_input_matches_any_exact_rule(self):
        for value, _status, _match_status in FAILING_INPUTS:
            for declared in RULE_PHENOTYPES:
                with self.subTest(value=repr(value), declared=declared.value):
                    self.assertFalse(
                        match_observation(observation(value),
                                          exact(declared)).matched)

    def test_no_failing_input_matches_a_one_of_naming_everything(self):
        """Even a condition listing every phenotype does not match an input
        that is not a phenotype."""
        everything = one_of(*RULE_PHENOTYPES)
        for value, _status, _match_status in FAILING_INPUTS:
            with self.subTest(value=repr(value)):
                self.assertFalse(
                    match_observation(observation(value), everything).matched)


class TestTheThreeFailuresStayDistinct(unittest.TestCase):

    def test_each_failing_input_produces_its_own_match_status(self):
        for value, expected_observation, expected_match in FAILING_INPUTS:
            with self.subTest(value=repr(value)):
                obs = observation(value)
                self.assertEqual(obs.status, expected_observation)
                decision = match_observation(obs, exact(Phenotype.POOR))
                self.assertEqual(decision.status, expected_match)

    def test_none_of_them_is_reported_as_no_match(self):
        """``NO_MATCH`` means a phenotype was observed and the rule does not
        cover it. None of these observed a phenotype."""
        for value, _status, _match_status in FAILING_INPUTS:
            with self.subTest(value=repr(value)):
                self.assertNotEqual(
                    match_observation(observation(value),
                                      exact(Phenotype.POOR)).status,
                    "NO_MATCH")

    def test_the_reason_code_survives_into_the_decision(self):
        for value, _status, _match_status in FAILING_INPUTS:
            with self.subTest(value=repr(value)):
                obs = observation(value)
                decision = match_observation(obs, exact(Phenotype.POOR))
                self.assertEqual(decision.reason_code, obs.reason_code)

    def test_the_observation_status_survives_into_the_decision(self):
        for value, expected_observation, _match in FAILING_INPUTS:
            with self.subTest(value=repr(value)):
                self.assertEqual(
                    match_observation(observation(value),
                                      exact(Phenotype.POOR)).observation_status,
                    expected_observation)

    def test_missing_and_unsupported_are_not_the_same_answer(self):
        """The one comparison that matters: nobody supplied a value, versus
        somebody supplied something that is not a phenotype."""
        missing = match_observation(observation(None), exact(Phenotype.POOR))
        unsupported = match_observation(observation("PM"),
                                        exact(Phenotype.POOR))
        self.assertNotEqual(missing.status, unsupported.status)
        self.assertNotEqual(missing.reason_code, unsupported.reason_code)


class TestNoFailureBecomesAReassuringResult(unittest.TestCase):
    """``SAFETY-INV-001`` at this layer. WP-12 produces no attention level at
    all, which is the strongest possible version of "absence never produces
    LOW" - there is no field it could be written into."""

    def test_a_decision_carries_no_attention_field(self):
        fields = set(MatchDecision.__dataclass_fields__)
        for forbidden in ("attention", "attention_level", "risk", "risk_level",
                          "risk_score", "score", "severity", "priority"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, fields)

    def test_a_decision_carries_no_coverage_field(self):
        fields = set(MatchDecision.__dataclass_fields__)
        for forbidden in ("coverage", "coverage_status", "coverage_reason",
                          "covered", "completeness"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, fields)

    def test_a_decision_carries_no_clinical_instruction_field(self):
        fields = set(MatchDecision.__dataclass_fields__)
        for forbidden in ("dose", "dosage", "recommendation", "alternative",
                          "treatment", "safe", "is_safe", "safety",
                          "instruction", "diagnosis", "finding", "report",
                          "explanation", "narrative"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, fields)

    def test_no_status_string_resembles_an_attention_level(self):
        from pgx.engine.phenotype_models import MATCH_STATUSES
        attention = {member.value for member in AttentionLevel}
        self.assertEqual(set(MATCH_STATUSES) & attention, set())

    def test_no_status_string_resembles_a_coverage_status(self):
        from pgx.engine.phenotype_models import MATCH_STATUSES
        coverage = {member.value for member in CoverageStatus}
        self.assertEqual(set(MATCH_STATUSES) & coverage, set())

    def test_the_serialized_decision_carries_no_forbidden_key(self):
        payload = match_observation(observation(None),
                                    exact(Phenotype.POOR)).to_json()
        for forbidden in ("attention_level", "coverage_status", "dose",
                          "recommendation", "risk_score", "safe", "finding"):
            with self.subTest(key=forbidden):
                self.assertNotIn(forbidden, payload)


class TestAnObservationCannotLieAboutItself(unittest.TestCase):

    def test_a_failed_observation_cannot_carry_a_phenotype(self):
        """Carrying one would invite a reader to use it."""
        with self.assertRaises(Exception):
            PhenotypeObservation(
                gene_canonical_key="GENE:TESTGENE1", status="UNSUPPORTED",
                phenotype=Phenotype.NORMAL,
                reason_code="PHENOTYPE_INPUT_UNSUPPORTED")

    def test_a_successful_observation_cannot_carry_a_failure_reason(self):
        with self.assertRaises(Exception):
            PhenotypeObservation(
                gene_canonical_key="GENE:TESTGENE1", status="NORMALIZED",
                phenotype=Phenotype.POOR,
                reason_code="PHENOTYPE_INPUT_UNSUPPORTED")

    def test_indeterminate_cannot_be_recorded_as_a_normalized_phenotype(self):
        with self.assertRaises(Exception):
            PhenotypeObservation(
                gene_canonical_key="GENE:TESTGENE1", status="NORMALIZED",
                phenotype=Phenotype.INDETERMINATE)

    def test_an_unknown_status_is_refused(self):
        for status in ("OK", "FAILED", "PARTIAL", "NORMAL", ""):
            with self.subTest(status=status):
                with self.assertRaises(Exception):
                    PhenotypeObservation(
                        gene_canonical_key="GENE:TESTGENE1", status=status)

    def test_a_failed_observation_needs_a_documented_reason_code(self):
        with self.assertRaises(Exception):
            PhenotypeObservation(
                gene_canonical_key="GENE:TESTGENE1", status="UNSUPPORTED",
                reason_code="MADE_UP_CODE")


if __name__ == "__main__":
    unittest.main()
