# -*- coding: utf-8 -*-
"""The matrix finds gaps, and cannot be satisfied by a row that reads well.

A hand-written requirement matrix answers "what verifies this" and can never
answer "what verifies nothing", because a requirement whose tests were deleted
still has a row in it. These tests hold down the second question.
"""

from __future__ import annotations

import unittest

from pgx.verification.discovery import discover
from pgx.verification.inventory import build_inventory
from pgx.verification.matrix import build_matrix
from pgx.verification.model import Category, Criticality, Outcome
from pgx.verification.requirements import (
    REQUIREMENTS,
    SAFETY_INVARIANT_MAP,
    SAFETY_MAP_DISCLAIMER,
    Requirement,
    requirements_by_id,
    selectors_match,
)

from tests.unit.verification._support import REPO_ROOT


class TestTheMatrixResolvesAgainstRealTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.inventory = build_inventory(discover(REPO_ROOT))
        cls.matrix = build_matrix(cls.inventory)

    def test_every_requirement_row_points_at_tests_that_exist(self):
        """A selector is resolved, not asserted. A renamed package empties the
        row, and the empty row is the finding."""
        known = {entry.test_id for entry in self.inventory.entries}
        for coverage in self.matrix.requirements:
            with self.subTest(requirement=coverage.requirement.requirement_id):
                for test_id in coverage.test_ids:
                    self.assertIn(test_id, known)

    def test_no_requirement_is_uncovered(self):
        self.assertEqual(self.matrix.uncovered_requirements, ())

    def test_no_critical_test_serves_no_requirement(self):
        """A P0 test nobody can name a reason for is either a missing
        requirement or a mis-set criticality. Both need a person."""
        self.assertEqual(self.matrix.unmapped_critical_modules, ())

    def test_every_required_category_is_populated(self):
        self.assertEqual(self.matrix.empty_categories, ())

    def test_a_category_is_never_reported_as_passing_before_it_runs(self):
        """Static analysis of a suite says a test exists. Only an execution
        says it passed."""
        for coverage in self.matrix.categories:
            with self.subTest(category=coverage.category.value):
                self.assertIn(coverage.static_outcome,
                              (Outcome.BLOCKED, Outcome.MISSING))
                self.assertIsNot(coverage.static_outcome, Outcome.PASS)

    def test_an_empty_category_is_missing_and_a_populated_one_is_blocked(self):
        for coverage in self.matrix.categories:
            with self.subTest(category=coverage.category.value):
                expected = (Outcome.MISSING if not coverage.test_ids
                            else Outcome.BLOCKED)
                self.assertIs(coverage.static_outcome, expected)

    def test_a_deleted_requirement_target_is_detected(self):
        """The property that makes this matrix worth computing."""
        broken = Requirement(
            requirement_id="VER-REQ-999",
            title="a requirement whose tests do not exist",
            source="this test",
            work_packages=("WP-TEST",),
            selectors=("tests.unit.package_that_was_deleted",),
            criticality=Criticality.P0_CRITICAL)
        import pgx.verification.matrix as matrix_module
        original = matrix_module.REQUIREMENTS
        try:
            matrix_module.REQUIREMENTS = original + (broken,)
            rebuilt = build_matrix(self.inventory)
        finally:
            matrix_module.REQUIREMENTS = original
        self.assertIn("VER-REQ-999", rebuilt.uncovered_requirements)
        self.assertFalse(rebuilt.is_complete)

    def test_completeness_is_all_three_conditions(self):
        self.assertTrue(self.matrix.is_complete)
        self.assertEqual(self.matrix.uncovered_requirements, ())
        self.assertEqual(self.matrix.unmapped_critical_modules, ())
        self.assertEqual(self.matrix.empty_categories, ())


class TestTheRequirementRegistry(unittest.TestCase):

    def test_identifiers_are_unique(self):
        identifiers = [item.requirement_id for item in REQUIREMENTS]
        self.assertEqual(len(set(identifiers)), len(identifiers))

    def test_every_requirement_names_a_document_it_came_from(self):
        for requirement in REQUIREMENTS:
            with self.subTest(requirement=requirement.requirement_id):
                self.assertTrue(requirement.source)
                self.assertTrue(requirement.work_packages)
                self.assertTrue(requirement.selectors)

    def test_the_eleven_named_p0_requirements_are_all_present(self):
        """The list the work package asked for, held down by identifier so a
        rewording cannot quietly drop one."""
        registry = requirements_by_id()
        for identifier in ("VER-REQ-001", "VER-REQ-002", "VER-REQ-003",
                           "VER-REQ-004", "VER-REQ-005", "VER-REQ-006",
                           "VER-REQ-007", "VER-REQ-008", "VER-REQ-009",
                           "VER-REQ-010", "VER-REQ-011"):
            with self.subTest(requirement=identifier):
                self.assertIn(identifier, registry)
                self.assertIs(registry[identifier].criticality,
                              Criticality.P0_CRITICAL)

    def test_the_wp20_safety_requirement_is_registered_and_covered(self):
        """WP-19 had twenty requirements and no requirement that the safety
        invariants be *enforced* - only that tests exist. VER-REQ-021 is that
        requirement, and it is covered by a suite that actually runs."""
        registry = requirements_by_id()
        self.assertIn("VER-REQ-021", registry)
        requirement = registry["VER-REQ-021"]
        self.assertIs(requirement.criticality, Criticality.P0_CRITICAL)
        self.assertEqual(requirement.work_packages, ("WP-20",))
        self.assertEqual(len(requirement.safety_invariants), 12)
        matrix = build_matrix(build_inventory(discover(REPO_ROOT)))
        self.assertNotIn("VER-REQ-021", matrix.uncovered_requirements)
        covered = {item.requirement.requirement_id: item
                   for item in matrix.requirements}
        self.assertTrue(covered["VER-REQ-021"].test_ids)

    def test_a_selector_matches_exactly_or_as_a_dotted_prefix(self):
        self.assertTrue(selectors_match("tests.unit.web", ("tests.unit.web",)))
        self.assertTrue(selectors_match("tests.unit.web.test_pages",
                                        ("tests.unit.web",)))
        self.assertFalse(selectors_match("tests.unit.website",
                                         ("tests.unit.web",)))


class TestTheSafetyMapIsAMapAndSaysSo(unittest.TestCase):
    """WP-20 owns the safety gate. WP-19 owns a map to it and no more."""

    @classmethod
    def setUpClass(cls):
        cls.inventory = build_inventory(discover(REPO_ROOT))
        cls.matrix = build_matrix(cls.inventory)

    def test_all_twelve_invariants_appear(self):
        """``architecture.md`` names ten. WP-20 registers twelve, because two
        requirements already in the safety contract had no invariant ID of
        their own. The map follows the registry, not the smaller number."""
        for index in range(1, 13):
            with self.subTest(invariant=index):
                self.assertIn("SAFETY-INV-%03d" % index, SAFETY_INVARIANT_MAP)
        self.assertEqual(len(SAFETY_INVARIANT_MAP), 12)

    def test_the_map_covers_exactly_what_wp20_registers(self):
        """Two maps of the same invariants that disagree are worse than one.
        If WP-20 adds or renames an invariant, this fails here rather than
        leaving WP-19 quietly describing a set that no longer exists."""
        from pgx.safety.definitions import definitions_by_id
        self.assertEqual(set(SAFETY_INVARIANT_MAP),
                         set(definitions_by_id()))

    def test_every_mapped_selector_names_a_module_that_exists(self):
        self.assertEqual(self.matrix.stale_safety_selectors, ())

    def test_no_invariant_is_left_with_nothing_mapped(self):
        self.assertEqual(self.matrix.unmapped_safety_invariants, ())

    def test_the_document_says_it_is_not_a_gate(self):
        document = self.matrix.as_document()
        self.assertEqual(document["safety_map_disclaimer"],
                         SAFETY_MAP_DISCLAIMER)
        self.assertIn("WP-20", SAFETY_MAP_DISCLAIMER)
        self.assertIn("not an assertion that the invariants hold",
                      SAFETY_MAP_DISCLAIMER)

    def test_completeness_does_not_depend_on_the_safety_map(self):
        """An unmapped invariant is a WP-20 gap.

        Letting it fail WP-19's completeness check would push this package into
        claiming a gate it does not own - in the direction of appearing
        stricter, which is exactly how a boundary gets crossed by accident.
        """
        import pgx.verification.matrix as matrix_module
        original = matrix_module.SAFETY_INVARIANT_MAP
        try:
            matrix_module.SAFETY_INVARIANT_MAP = dict(
                original, **{"SAFETY-INV-001": ()})
            rebuilt = build_matrix(self.inventory)
        finally:
            matrix_module.SAFETY_INVARIANT_MAP = original
        self.assertIn("SAFETY-INV-001", rebuilt.unmapped_safety_invariants)
        self.assertTrue(rebuilt.is_complete)
