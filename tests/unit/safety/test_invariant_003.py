# -*- coding: utf-8 -*-
"""SAFETY-INV-003: only VALIDATED rules from the pinned ruleset execute.

``LEGACY-BUG-006``: legacy ``MANUAL_EFFECT_HINTS`` was curated content applied
at assessment time with no review record, which makes an approval workflow
decorative.

The safe control reads ``VALIDATED`` from the shipped ``RuleStatus`` enum, so
renaming or adding a lifecycle state reaches this check rather than leaving it
comparing against a string that no longer exists.
"""

from __future__ import annotations

import unittest

from pgx.domain.enums import RuleStatus
from pgx.safety.controls import controls_for
from pgx.safety.evaluators import evaluate_only_validated_rules_execute
from pgx.safety.vocabulary import InvariantId
from tests.fixtures.wp20 import unsafe_ruleset
from tests.unit.safety._support import production_rule_selector


def _evaluate(selector):
    return evaluate_only_validated_rules_execute(
        selector, unsafe_ruleset.rule_set(), unsafe_ruleset.PINNED_RULESET)


class TestOnlyValidatedPinnedRulesExecute(unittest.TestCase):

    def setUp(self):
        self.verdict = _evaluate(production_rule_selector())

    def test_it_is_compliant(self):
        self.assertTrue(self.verdict.compliant, self.verdict.violations)

    def test_every_non_executable_lifecycle_state_is_exercised(self):
        """Not just DRAFT: every state the vocabulary allows that is not
        VALIDATED appears in the fixture, so a new state cannot slip past."""
        statuses = {rule["status"] for rule in unsafe_ruleset.rule_set()}
        for state in RuleStatus:
            if state is RuleStatus.VALIDATED:
                continue
            with self.subTest(status=state.value):
                self.assertIn(state.value, statuses)

    def test_the_shipped_predicate_agrees_with_the_safe_control(self):
        """``is_executable`` on the shipped rule model is the production
        predicate. The safe control must mean the same thing, or this test is
        proving a detector against a rule the engine does not use.

        Read as a syntax tree rather than by importing a class whose name may
        change: what is asserted is that exactly one lifecycle state is
        executable, and that it is VALIDATED.
        """
        import ast
        import inspect

        from pgx.rules import models

        tree = ast.parse(inspect.getsource(models))
        executable = [node for node in ast.walk(tree)
                      if isinstance(node, ast.FunctionDef)
                      and node.name == "is_executable"]
        self.assertTrue(executable,
                        "the shipped rule model no longer declares "
                        "is_executable; SAFETY-INV-003 has lost its "
                        "production predicate")
        for node in executable:
            body = ast.dump(node)
            with self.subTest(line=node.lineno):
                self.assertIn("VALIDATED", body)
                for other in ("DRAFT", "CURATED", "DEPRECATED"):
                    self.assertNotIn(other, body,
                                     "is_executable admits %s" % other)


class TestEveryNegativeControlIsDetected(unittest.TestCase):

    def test_each_permissive_selector_is_rejected(self):
        for control in controls_for(InvariantId.INV_003):
            with self.subTest(control=control.control_id):
                subject = unsafe_ruleset.UNSAFE_SUBJECTS[control.control_id]
                verdict = _evaluate(subject)
                self.assertFalse(verdict.compliant,
                                 "%s was NOT detected" % control.control_id)
                self.assertEqual(verdict.refusal_code,
                                 "SAFETY_UNVALIDATED_RULE_EXECUTED")

    def test_a_draft_rule_firing_is_what_is_caught(self):
        verdict = _evaluate(unsafe_ruleset.draft_rule_fires)
        self.assertTrue(any("DRAFT" in v for v in verdict.violations),
                        verdict.violations)

    def test_an_unpinned_ruleset_is_caught_even_though_every_rule_is_valid(
            self):
        """The subtle one: status is right, provenance is not."""
        verdict = _evaluate(unsafe_ruleset.unpinned_ruleset_accepted)
        self.assertFalse(verdict.compliant)
        self.assertTrue(any("pinned" in v for v in verdict.violations),
                        verdict.violations)

    def test_an_empty_result_is_not_a_clean_result(self):
        """An invalid ruleset must fail closed, not silently filter to nothing
        and return a reassuring answer."""
        verdict = _evaluate(lambda rules, pinned: [])
        self.assertFalse(verdict.compliant)

    def test_the_catalogue_and_the_fixtures_agree(self):
        declared = {c.control_id for c in controls_for(InvariantId.INV_003)}
        self.assertEqual(declared, set(unsafe_ruleset.UNSAFE_SUBJECTS))
