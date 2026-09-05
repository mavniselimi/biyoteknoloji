# -*- coding: utf-8 -*-
"""The registry contains exactly twelve, and fails closed on anything else.

Every check here has a plausible-looking wrong alternative, and the wrong one
always makes a build succeed. That is why they are tests rather than comments.
"""

from __future__ import annotations

import unittest

from pgx.safety.controls import NEGATIVE_CONTROLS, controls_by_id
from pgx.safety.definitions import INVARIANT_DEFINITIONS, definitions_by_id
from pgx.safety.errors import (DuplicateInvariant, InvariantNotRegistered,
                               NegativeControlMissing, RegistryError,
                               SelectorError, UnknownInvariant)
from pgx.safety.evaluators import EVALUATORS
from pgx.safety.registry import load_registry, validate_registry
from pgx.safety.vocabulary import (INVARIANT_IDS, ComplianceState,
                                   ExecutionState, InvariantId,
                                   is_release_permitting)
from tests.unit.safety._support import REPO_ROOT


class TestExactlyTwelveInvariants(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry(REPO_ROOT)

    def test_there_are_twelve(self):
        """Not ten. The architecture says 'at least 010'; the safety contract
        defines twelve, and stopping at ten would drop real-patient-data and
        determinism."""
        self.assertEqual(self.registry.invariant_count, 12)
        self.assertEqual(len(INVARIANT_IDS), 12)

    def test_the_identifiers_are_001_through_012(self):
        self.assertEqual(
            [d.invariant_id.value for d in self.registry.definitions],
            list(INVARIANT_IDS))

    def test_they_are_unique(self):
        identifiers = [d.invariant_id.value for d in INVARIANT_DEFINITIONS]
        self.assertEqual(len(set(identifiers)), 12)

    def test_they_are_in_order(self):
        identifiers = [d.invariant_id.value for d in INVARIANT_DEFINITIONS]
        self.assertEqual(identifiers, sorted(identifiers))

    def test_the_registry_matches_the_contract_document(self):
        """The document is normative; this file is what a build can execute.
        A registry that had drifted from the contract would be worse than no
        registry, because it would look authoritative."""
        import io
        import os
        import re
        path = os.path.join(REPO_ROOT, "docs", "risk-management",
                            "safety-contract.md")
        with io.open(path, encoding="utf-8") as handle:
            text = handle.read()
        headings = re.findall(r"^### `(SAFETY-INV-\d{3})`", text, re.MULTILINE)
        self.assertEqual(headings, list(INVARIANT_IDS))

    def test_every_invariant_has_a_detector(self):
        for invariant in InvariantId:
            with self.subTest(invariant=invariant.value):
                self.assertIn(invariant, EVALUATORS)

    def test_every_invariant_names_a_normative_source(self):
        for definition in INVARIANT_DEFINITIONS:
            with self.subTest(invariant=definition.invariant_id.value):
                self.assertIn("safety-contract.md",
                              definition.requirement_reference)
                self.assertTrue(definition.owning_work_packages)
                self.assertTrue(definition.refusal_code.startswith("SAFETY_"))

    def test_every_invariant_has_at_least_one_negative_control(self):
        for definition in INVARIANT_DEFINITIONS:
            with self.subTest(invariant=definition.invariant_id.value):
                self.assertTrue(definition.negative_controls)

    def test_every_selector_resolves_to_a_real_module(self):
        for identifier, modules in self.registry.resolved_modules.items():
            with self.subTest(invariant=identifier):
                self.assertTrue(modules)

    def test_every_required_legacy_mapping_is_present(self):
        """The seven the work package named, held by identifier."""
        expected = {
            "LEGACY-BUG-001": "SAFETY-INV-004",
            "LEGACY-BUG-002": "SAFETY-INV-001",
            "LEGACY-BUG-005": "SAFETY-INV-006",
            "LEGACY-BUG-006": "SAFETY-INV-003",
            "LEGACY-BUG-009": "SAFETY-INV-005",
            "LEGACY-BUG-012": "SAFETY-INV-010",
        }
        registry = definitions_by_id()
        for bug, invariant in sorted(expected.items()):
            with self.subTest(bug=bug):
                self.assertIn(bug, registry[invariant].legacy_bugs)
        # LEGACY-BUG-007 maps to two invariants, both of which it broke.
        for invariant in ("SAFETY-INV-007", "SAFETY-INV-012"):
            with self.subTest(bug="LEGACY-BUG-007", invariant=invariant):
                self.assertIn("LEGACY-BUG-007", registry[invariant].legacy_bugs)

    def test_every_legacy_reference_names_a_known_frozen_defect(self):
        import sys
        import os
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
        try:
            import legacy_bug_registry
        finally:
            sys.path.pop(0)
        known = set(legacy_bug_registry.bug_ids())
        for definition in INVARIANT_DEFINITIONS:
            for bug in definition.legacy_bugs:
                with self.subTest(bug=bug):
                    self.assertIn(bug, known)


class TestTheRegistryFailsClosed(unittest.TestCase):
    """Each of these has a wrong alternative that makes a build succeed."""

    def _modules(self):
        return tuple(m for modules in
                     load_registry(REPO_ROOT).resolved_modules.values()
                     for m in modules)

    def test_a_missing_invariant_is_refused(self):
        """Deleting a safety requirement must not be a way of satisfying it."""
        with self.assertRaises(InvariantNotRegistered):
            validate_registry(REPO_ROOT, self._modules(),
                              INVARIANT_DEFINITIONS[:-1])

    def test_a_duplicate_identifier_is_refused(self):
        with self.assertRaises(DuplicateInvariant):
            validate_registry(REPO_ROOT, self._modules(),
                              INVARIANT_DEFINITIONS + (
                                  INVARIANT_DEFINITIONS[0],))

    def test_an_unknown_identifier_is_refused(self):
        import dataclasses

        class _Fake:
            value = "SAFETY-INV-013"

        extra = dataclasses.replace(INVARIANT_DEFINITIONS[0],
                                    invariant_id=_Fake())
        with self.assertRaises((UnknownInvariant, DuplicateInvariant,
                                RegistryError)):
            validate_registry(REPO_ROOT, self._modules(),
                              INVARIANT_DEFINITIONS + (extra,))

    def test_a_selector_matching_nothing_is_refused(self):
        """A row that reads convincingly while its tests were renamed is worse
        than no row."""
        import dataclasses
        broken = dataclasses.replace(
            INVARIANT_DEFINITIONS[0],
            test_selectors=("tests.unit.package_that_was_deleted",))
        with self.assertRaises(SelectorError):
            validate_registry(REPO_ROOT, self._modules(),
                              (broken,) + INVARIANT_DEFINITIONS[1:])

    def test_an_invariant_with_no_negative_control_is_refused(self):
        import dataclasses
        stripped = dataclasses.replace(INVARIANT_DEFINITIONS[0],
                                       negative_controls=())
        with self.assertRaises(NegativeControlMissing):
            validate_registry(REPO_ROOT, self._modules(),
                              (stripped,) + INVARIANT_DEFINITIONS[1:])

    def test_a_control_naming_a_missing_fixture_is_refused(self):
        import dataclasses
        control = dataclasses.replace(NEGATIVE_CONTROLS[0],
                                      fixture="tests.fixtures.wp20.nonexistent")
        with self.assertRaises(NegativeControlMissing):
            validate_registry(REPO_ROOT, self._modules(),
                              INVARIANT_DEFINITIONS,
                              (control,) + NEGATIVE_CONTROLS[1:])

    def test_a_control_claimed_by_the_wrong_invariant_is_refused(self):
        import dataclasses
        stolen = dataclasses.replace(
            INVARIANT_DEFINITIONS[0],
            negative_controls=("NC-INV-012-WALL-CLOCK-IN-OUTPUT",))
        with self.assertRaises(NegativeControlMissing):
            validate_registry(REPO_ROOT, self._modules(),
                              (stolen,) + INVARIANT_DEFINITIONS[1:])

    def test_a_not_present_invariant_whose_feature_appeared_is_refused(self):
        """NOT_PRESENT must never excuse an unsafe feature that exists."""
        import dataclasses
        appeared = dataclasses.replace(
            definitions_by_id()["SAFETY-INV-002"],
            absence_markers=("pyproject.toml",))     # a path that does exist
        others = tuple(d for d in INVARIANT_DEFINITIONS
                       if d.invariant_id is not appeared.invariant_id)
        rebuilt = tuple(sorted(others + (appeared,),
                               key=lambda d: d.invariant_id.value))
        with self.assertRaises(RegistryError) as raised:
            validate_registry(REPO_ROOT, self._modules(), rebuilt)
        self.assertTrue(any("the feature has appeared" in issue
                            for issue in raised.exception.issues),
                        raised.exception.issues)

    def test_a_not_present_invariant_with_no_markers_is_refused(self):
        import dataclasses
        blind = dataclasses.replace(definitions_by_id()["SAFETY-INV-005"],
                                    absence_markers=())
        others = tuple(d for d in INVARIANT_DEFINITIONS
                       if d.invariant_id is not blind.invariant_id)
        rebuilt = tuple(sorted(others + (blind,),
                               key=lambda d: d.invariant_id.value))
        with self.assertRaises(RegistryError):
            validate_registry(REPO_ROOT, self._modules(), rebuilt)


class TestTheVocabularyCannotBeCollapsed(unittest.TestCase):

    def test_only_pass_permits_a_release(self):
        for state in ExecutionState:
            with self.subTest(state=state.value):
                self.assertEqual(is_release_permitting(state),
                                 state is ExecutionState.PASS)

    def test_blocked_not_executed_and_stale_all_stop_a_release(self):
        """"We do not know" is not a reason to ship."""
        for state in (ExecutionState.BLOCKED, ExecutionState.NOT_EXECUTED,
                      ExecutionState.STALE):
            with self.subTest(state=state.value):
                self.assertFalse(is_release_permitting(state))

    def test_the_states_refuse_to_be_ordered(self):
        with self.assertRaises(TypeError):
            _ = ExecutionState.BLOCKED < ExecutionState.PASS
        with self.assertRaises(TypeError):
            _ = sorted([ComplianceState.COMPLIANT, ComplianceState.VIOLATED])

    def test_every_control_belongs_to_a_registered_invariant(self):
        registered = {d.invariant_id for d in INVARIANT_DEFINITIONS}
        for control in NEGATIVE_CONTROLS:
            with self.subTest(control=control.control_id):
                self.assertIn(control.invariant_id, registered)

    def test_control_identifiers_are_unique(self):
        self.assertEqual(len(controls_by_id()), len(NEGATIVE_CONTROLS))
