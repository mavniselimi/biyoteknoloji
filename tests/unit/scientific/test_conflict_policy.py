# -*- coding: utf-8 -*-
"""Source conflicts: detected automatically, resolved only by a human.

The property this suite exists to protect is an absence. There is no precedence
table, no "newest wins", no merge function - so no future refactor can quietly
give one source authority over another. The tests below check both halves:
that a disagreement is found and blocks, and that nothing in the package will
settle it on its own.
"""

from __future__ import annotations

import ast
import io
import os
import unittest

from pgx.scientific.conflict import (
    ConflictRegister,
    SourceStatement,
    conflict_key_for,
    detect_conflicts,
    unresolved_material_conflicts,
)
from pgx.scientific.errors import (
    ConflictRegistryError,
    SourcePolicyValidationError,
)
from pgx.scientific.models import (
    ConflictMateriality,
    ConflictResolution,
    ConflictStatus,
    SourceConflict,
)
from pgx.scientific.policy import SourcePolicyRegistry
from pgx.scientific.publication_gate import (
    PublicationDecision,
    PublicationIntent,
    evaluate_publication,
)
from pgx.scientific.validation import PolicyIssueCode

from tests.unit.scientific import _fixtures as fx

CONFLICT_MODULE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))),
    "pgx", "scientific", "conflict.py")


def _statements():
    return (
        SourceStatement("CYP2C19:clopidogrel", "fixture.alpha", "AVOID"),
        SourceStatement("CYP2C19:clopidogrel", "fixture.beta", "ALTERNATIVE"),
    )


class TestDetection(unittest.TestCase):

    def test_two_sources_agreeing_produce_no_conflict(self):
        agreed = (SourceStatement("s", "fixture.alpha", "SAME"),
                  SourceStatement("s", "fixture.beta", "SAME"))
        self.assertEqual(detect_conflicts(agreed), ())

    def test_two_sources_disagreeing_produce_one_conflict(self):
        conflicts = detect_conflicts(_statements())
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(set(conflicts[0].source_keys),
                         {"fixture.alpha", "fixture.beta"})

    def test_a_detected_conflict_starts_open_and_undetermined(self):
        conflict = detect_conflicts(_statements())[0]
        self.assertIs(conflict.status, ConflictStatus.OPEN)
        self.assertIs(conflict.materiality, ConflictMateriality.UNDETERMINED)

    def test_the_description_quotes_both_statements(self):
        conflict = detect_conflicts(_statements())[0]
        self.assertIn("AVOID", conflict.description)
        self.assertIn("ALTERNATIVE", conflict.description)

    def test_a_source_contradicting_itself_is_also_a_conflict(self):
        conflicts = detect_conflicts((
            SourceStatement("s", "fixture.alpha", "ONE"),
            SourceStatement("s", "fixture.alpha", "TWO")))
        self.assertEqual(len(conflicts), 1)

    def test_the_key_is_stable_whatever_order_the_sources_arrive_in(self):
        forward = detect_conflicts(_statements())[0].conflict_key
        backward = detect_conflicts(tuple(reversed(_statements())))[0].conflict_key
        self.assertEqual(forward, backward)

    def test_detection_is_deterministic(self):
        first = [c.to_json() for c in detect_conflicts(_statements())]
        second = [c.to_json() for c in detect_conflicts(tuple(reversed(_statements())))]
        self.assertEqual(first, second)

    def test_subjects_are_processed_in_sorted_order(self):
        statements = (
            SourceStatement("zeta", "fixture.alpha", "A"),
            SourceStatement("zeta", "fixture.beta", "B"),
            SourceStatement("alpha", "fixture.alpha", "A"),
            SourceStatement("alpha", "fixture.beta", "B"),
        )
        subjects = [c.subject for c in detect_conflicts(statements)]
        self.assertEqual(subjects, sorted(subjects))

    def test_a_key_needs_two_distinct_sources(self):
        with self.assertRaises(ConflictRegistryError):
            conflict_key_for("s", ["fixture.alpha", "fixture.alpha"])

    def test_a_statement_must_carry_text(self):
        with self.assertRaises(ConflictRegistryError):
            SourceStatement("s", "fixture.alpha", "   ")


class TestNoPrecedenceIsEverApplied(unittest.TestCase):
    """The absence is the contract."""

    @classmethod
    def setUpClass(cls):
        with io.open(CONFLICT_MODULE, encoding="utf-8") as handle:
            cls.source = handle.read()
        cls.tree = ast.parse(cls.source, filename=CONFLICT_MODULE)

    def _identifiers(self):
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef):
                names.add(node.name)
            elif isinstance(node, ast.ClassDef):
                names.add(node.name)
            elif isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
        return names

    def test_no_function_merges_or_prefers_a_source(self):
        names = self._identifiers()
        for forbidden in ("merge", "prefer_source", "resolve_automatically",
                          "precedence", "rank_sources", "winner", "supersede"):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, names)

    def test_no_real_source_is_named_in_the_module(self):
        """A precedence rule hidden as a constant would name a body."""
        for body in ("CPIC", "DPWG", "ClinPGx", "RNPGx", "CPNDS"):
            with self.subTest(body=body):
                self.assertNotIn(body, self._identifiers())

    def test_the_only_way_to_settle_a_conflict_is_a_resolution_record(self):
        conflict = detect_conflicts(_statements())[0]
        with self.assertRaises(ConflictRegistryError):
            SourceConflict(
                conflict_key=conflict.conflict_key, subject=conflict.subject,
                source_keys=conflict.source_keys,
                description=conflict.description,
                status=ConflictStatus.RESOLVED)

    def test_a_resolution_requires_a_named_decider_and_a_rationale(self):
        with self.assertRaises(SourcePolicyValidationError):
            ConflictResolution(decision_summary="alpha wins", rationale="",
                               decided_by="", decided_at=fx.NOW)

    def test_a_resolution_may_only_prefer_a_source_in_the_conflict(self):
        conflict = detect_conflicts(_statements())[0]
        with self.assertRaises(ConflictRegistryError):
            SourceConflict(
                conflict_key=conflict.conflict_key, subject=conflict.subject,
                source_keys=conflict.source_keys,
                description=conflict.description,
                status=ConflictStatus.RESOLVED,
                resolution=ConflictResolution(
                    decision_summary="a third source wins",
                    rationale="fixture", decided_by=fx.TEST_SCIENTIFIC_REVIEWER,
                    decided_at=fx.NOW,
                    preferred_source_key="fixture.gamma"))

    def test_an_unsettled_conflict_may_not_carry_a_resolution(self):
        conflict = detect_conflicts(_statements())[0]
        with self.assertRaises(ConflictRegistryError):
            SourceConflict(
                conflict_key=conflict.conflict_key, subject=conflict.subject,
                source_keys=conflict.source_keys,
                description=conflict.description,
                status=ConflictStatus.OPEN,
                resolution=ConflictResolution(
                    decision_summary="s", rationale="r",
                    decided_by=fx.TEST_SCIENTIFIC_REVIEWER, decided_at=fx.NOW))


class TestBlockingBehaviour(unittest.TestCase):

    def setUp(self):
        self.conflict = detect_conflicts(_statements())[0]

    def test_an_open_undetermined_conflict_blocks(self):
        self.assertTrue(self.conflict.blocks_publication)

    def test_a_material_conflict_blocks(self):
        material = SourceConflict(
            conflict_key=self.conflict.conflict_key, subject="s",
            source_keys=self.conflict.source_keys, description="d",
            materiality=ConflictMateriality.MATERIAL)
        self.assertTrue(material.blocks_publication)

    def test_an_open_non_material_conflict_does_not_block(self):
        """Somebody judged it harmless; that judgement is on the record."""
        harmless = SourceConflict(
            conflict_key=self.conflict.conflict_key, subject="s",
            source_keys=self.conflict.source_keys, description="d",
            materiality=ConflictMateriality.NON_MATERIAL)
        self.assertFalse(harmless.blocks_publication)

    def test_a_settled_conflict_stops_blocking(self):
        settled = SourceConflict(
            conflict_key=self.conflict.conflict_key, subject="s",
            source_keys=self.conflict.source_keys, description="d",
            materiality=ConflictMateriality.MATERIAL,
            status=ConflictStatus.RESOLVED,
            resolution=ConflictResolution(
                decision_summary="fixture decision", rationale="fixture",
                decided_by=fx.TEST_SCIENTIFIC_REVIEWER, decided_at=fx.NOW,
                preferred_source_key="fixture.alpha"))
        self.assertFalse(settled.blocks_publication)
        self.assertTrue(settled.is_settled)

    def test_undetermined_materiality_is_reported_separately(self):
        register = ConflictRegister.from_records((self.conflict,))
        codes = {issue.code for issue in register.issues()}
        self.assertIn(PolicyIssueCode.CONFLICT_MATERIALITY_UNDETERMINED, codes)
        self.assertIn(PolicyIssueCode.CONFLICT_UNRESOLVED, codes)

    def test_blocking_conflicts_are_returned_in_key_order(self):
        many = detect_conflicts((
            SourceStatement("zz", "fixture.alpha", "A"),
            SourceStatement("zz", "fixture.beta", "B"),
            SourceStatement("aa", "fixture.alpha", "A"),
            SourceStatement("aa", "fixture.beta", "B"),
        ))
        keys = [c.conflict_key for c in unresolved_material_conflicts(many)]
        self.assertEqual(keys, sorted(keys))


class TestAConflictBlocksOnlyTheSourcesItTouches(unittest.TestCase):

    def setUp(self):
        self.registry = SourcePolicyRegistry(
            records=(fx.approved_source(source_key="fixture.alpha"),
                     fx.approved_source(source_key="fixture.beta"),
                     fx.approved_source(source_key="fixture.gamma")),
            conflicts=detect_conflicts(_statements()))

    def _evaluate(self, *keys):
        return evaluate_publication(
            self.registry,
            PublicationIntent(dataset_key="d", source_keys=keys), fx.NOW)

    def test_a_dataset_citing_a_conflicting_source_is_blocked(self):
        result = self._evaluate("fixture.alpha")
        self.assertIs(result.decision, PublicationDecision.BLOCKED)
        self.assertIn(PolicyIssueCode.CONFLICT_UNRESOLVED.value,
                      result.blocking_codes)

    def test_a_dataset_citing_only_uninvolved_sources_is_not_held_up(self):
        result = self._evaluate("fixture.gamma")
        self.assertIs(result.decision, PublicationDecision.ELIGIBLE)


class TestTheRegisterIsImmutable(unittest.TestCase):
    """Deleting a conflict is not resolving it."""

    def test_it_offers_no_removal_method(self):
        for forbidden in ("remove", "delete", "discard", "pop", "clear"):
            with self.subTest(name=forbidden):
                self.assertFalse(hasattr(ConflictRegister, forbidden))

    def test_duplicate_keys_are_refused(self):
        conflict = detect_conflicts(_statements())[0]
        with self.assertRaises(ConflictRegistryError):
            ConflictRegister((conflict, conflict))

    def test_records_are_stored_in_key_order(self):
        many = detect_conflicts((
            SourceStatement("zz", "fixture.alpha", "A"),
            SourceStatement("zz", "fixture.beta", "B"),
            SourceStatement("aa", "fixture.alpha", "A"),
            SourceStatement("aa", "fixture.beta", "B"),
        ))
        register = ConflictRegister(tuple(reversed(many)))
        keys = [c.conflict_key for c in register.conflicts]
        self.assertEqual(keys, sorted(keys))


class TestARegistryRefusesAConflictAboutUnregisteredSources(unittest.TestCase):

    def test_it_is_a_registry_gap_not_a_conflict(self):
        with self.assertRaises(ConflictRegistryError):
            SourcePolicyRegistry(
                records=(fx.approved_source(source_key="fixture.alpha"),),
                conflicts=detect_conflicts(_statements()))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
