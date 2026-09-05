# -*- coding: utf-8 -*-
"""SAFETY-INV-002: an optional LLM must never alter calculated facts.

P0 ships no renderer, so this invariant is enforced two ways and both are
tested here:

* **Structurally.** No LLM is required for deterministic output, the default is
  disabled, and the marker paths a gateway would occupy do not exist. If one
  appears, ``TestTheFeatureIsStillAbsent`` fails and the registry's
  ``NOT_PRESENT`` answer expires.
* **By detector.** The negative controls are test-only adversarial renderers.
  Driving them through the fact-preservation evaluator proves the check works
  *before* the feature exists, rather than after it has already rendered
  something wrong.
"""

from __future__ import annotations

import os
import unittest

from pgx.safety.controls import controls_for
from pgx.safety.definitions import definitions_by_id
from pgx.safety.evaluators import evaluate_renderer_preserves_facts
from pgx.safety.vocabulary import ComplianceState, InvariantId
from tests.fixtures.wp20 import unsafe_renderer
from tests.unit.safety._support import REPO_ROOT


def _evaluate(renderer):
    return evaluate_renderer_preserves_facts(
        renderer, unsafe_renderer.sample_reports())


class TestTheFeatureIsStillAbsent(unittest.TestCase):
    """``NOT_PRESENT`` is only honest while it is true."""

    def setUp(self):
        self.definition = definitions_by_id()["SAFETY-INV-002"]

    def test_the_registry_records_it_as_not_present(self):
        self.assertIs(self.definition.implementation_state,
                      ComplianceState.NOT_PRESENT)

    def test_no_marker_path_exists(self):
        """The obligation that comes with NOT_PRESENT: adding the feature has
        to invalidate this answer rather than quietly inherit it."""
        self.assertTrue(self.definition.absence_markers)
        for marker in self.definition.absence_markers:
            with self.subTest(marker=marker):
                self.assertFalse(
                    os.path.exists(os.path.join(REPO_ROOT,
                                                *marker.split("/"))),
                    "%s exists; SAFETY-INV-002 may no longer be reported "
                    "NOT_PRESENT" % marker)

    def test_the_narration_port_is_disabled_by_default(self):
        from pgx.reporting.llm import LLM_ENABLED, LLM_PROVIDER
        self.assertFalse(LLM_ENABLED)
        self.assertIsNone(LLM_PROVIDER)

    def test_the_deterministic_report_needs_no_model(self):
        """The strongest form of this invariant: the feature is not merely off,
        it is unnecessary."""
        import ast
        import inspect

        import pgx.reporting.structured as structured

        source = inspect.getsource(structured)
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for forbidden in ("openai", "anthropic", "httpx", "requests",
                          "urllib3"):
            self.assertNotIn(forbidden, imported)


class TestEveryNegativeControlIsDetected(unittest.TestCase):

    def test_a_faithful_renderer_is_accepted(self):
        """A fact-preservation check that rejected everything would be
        indistinguishable from one that works."""
        verdict = _evaluate(unsafe_renderer.SAFE_SUBJECT)
        self.assertTrue(verdict.compliant, verdict.violations)
        self.assertTrue(verdict.is_meaningful)

    def test_each_adversarial_renderer_is_rejected(self):
        for control in controls_for(InvariantId.INV_002):
            with self.subTest(control=control.control_id):
                subject = unsafe_renderer.UNSAFE_SUBJECTS[control.control_id]
                verdict = _evaluate(subject)
                self.assertFalse(verdict.compliant,
                                 "%s was NOT detected" % control.control_id)
                self.assertEqual(verdict.refusal_code,
                                 "SAFETY_LLM_ALTERED_FACT")

    def test_a_changed_attention_level_is_what_is_caught(self):
        verdict = _evaluate(unsafe_renderer.changes_attention)
        self.assertTrue(any("attention" in v.lower()
                            for v in verdict.violations), verdict.violations)

    def test_an_invented_dose_is_what_is_caught(self):
        verdict = _evaluate(unsafe_renderer.invents_dose)
        self.assertTrue(any("dose" in v.lower() for v in verdict.violations),
                        verdict.violations)

    def test_the_catalogue_and_the_fixtures_agree(self):
        declared = {c.control_id for c in controls_for(InvariantId.INV_002)}
        self.assertEqual(declared, set(unsafe_renderer.UNSAFE_SUBJECTS))
