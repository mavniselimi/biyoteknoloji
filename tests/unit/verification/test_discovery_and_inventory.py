# -*- coding: utf-8 -*-
"""Discovery is deterministic, and the inventory describes all of it.

The inventory is the foundation every other WP-19 number sits on. If it
enumerates a different set of tests than the runner executes, or if it lets a
test through uncategorised, then the matrix, the gate status and the coverage
report are all describing something other than this suite.
"""

from __future__ import annotations

import os
import unittest

from pgx.verification.discovery import (
    DEFAULT_PATTERN,
    DEFAULT_START_DIRECTORY,
    discover,
    flatten,
)
from pgx.verification.errors import DiscoveryError, InventoryError
from pgx.verification.inventory import (
    CATEGORY_RULES,
    CategoryRule,
    build_inventory,
)
from pgx.verification.model import Category, Criticality, REQUIRED_CATEGORIES

from tests.unit.verification._support import REPO_ROOT


class TestDiscoveryIsDeterministic(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.first = discover(REPO_ROOT)
        cls.second = discover(REPO_ROOT)

    def test_two_enumerations_of_one_tree_agree_exactly(self):
        """Including order. A committed artifact keyed on this must not move
        because a filesystem walked a directory differently."""
        self.assertEqual(self.first.ids(), self.second.ids())

    def test_it_finds_the_suite_and_not_a_fragment_of_it(self):
        self.assertGreater(self.first.count, 5000)

    def test_every_identifier_is_unique(self):
        """Two tests with one identifier cannot both be attributed a result."""
        self.assertEqual(len(set(self.first.ids())), self.first.count)

    def test_identifiers_are_the_names_unittest_uses(self):
        """``tests.unit...`` and not ``unit...``.

        Every artifact, every matrix row and every CI selector depends on this
        spelling, so it is asserted rather than assumed.
        """
        for identifier in self.first.ids()[:50]:
            with self.subTest(identifier=identifier):
                self.assertTrue(identifier.startswith("tests."))

    def test_a_module_that_cannot_be_imported_is_reported_not_dropped(self):
        """A syntax error contributes zero tests. So does a deleted file."""
        self.assertEqual(self.first.load_failures, ())

    def test_it_refuses_a_start_directory_that_is_not_there(self):
        with self.assertRaises(DiscoveryError):
            discover(REPO_ROOT, start_directory="tests-that-do-not-exist")

    def test_the_defaults_match_the_documented_command(self):
        self.assertEqual(DEFAULT_START_DIRECTORY, "tests")
        self.assertEqual(DEFAULT_PATTERN, "test_*.py")

    def test_flatten_returns_leaves_rather_than_the_next_level(self):
        suite = unittest.TestSuite([
            unittest.TestSuite([_Trivial("runTest")]),
            unittest.TestSuite([unittest.TestSuite([_Trivial("runTest")])]),
        ])
        self.assertEqual(len(flatten(suite)), 2)


class _Trivial(unittest.TestCase):
    def runTest(self):  # pragma: no cover - never executed, only flattened
        pass


class TestEveryTestIsDescribed(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.discovery = discover(REPO_ROOT)
        cls.inventory = build_inventory(cls.discovery)

    def test_the_inventory_covers_every_discovered_test(self):
        self.assertEqual(self.inventory.count, self.discovery.count)

    def test_nothing_is_left_unmapped(self):
        self.assertEqual(self.inventory.unmapped, ())

    def test_every_entry_records_which_rule_assigned_it(self):
        """"Why is this a SNAPSHOT test" must have an answer."""
        for entry in self.inventory.entries:
            with self.subTest(test=entry.test_id):
                self.assertTrue(entry.assigned_by)

    def test_every_entry_carries_a_runnable_command(self):
        for entry in self.inventory.entries[:200]:
            with self.subTest(test=entry.test_id):
                self.assertIn(entry.module, entry.command)
                self.assertTrue(entry.command.startswith("python -m unittest"))

    def test_every_required_category_has_at_least_one_test(self):
        populated = {entry.category for entry in self.inventory.entries}
        for category in REQUIRED_CATEGORIES:
            with self.subTest(category=category.value):
                self.assertIn(category, populated)

    def test_a_module_matching_no_rule_is_refused_rather_than_defaulted(self):
        """The whole point of the totality check.

        A new package with no rule would otherwise become ``UNIT``, which is
        the friendliest possible wrong answer: it looks fine in every report.
        """
        narrow = tuple(rule for rule in CATEGORY_RULES
                       if not rule.matches("tests.unit.domain.test_hashing"))
        with self.assertRaises(InventoryError) as raised:
            build_inventory(self.discovery, narrow)
        self.assertIn("tests.unit.domain.test_hashing",
                      raised.exception.issues)

    def test_the_refusal_lists_every_unmapped_module_at_once(self):
        """One missing rule usually means a whole package arrived."""
        with self.assertRaises(InventoryError) as raised:
            build_inventory(self.discovery, ())
        self.assertGreater(len(raised.exception.issues), 100)

    def test_a_module_rule_beats_a_package_rule(self):
        """Order is the semantics, so it is asserted rather than trusted."""
        by_id = self.inventory.by_id()
        security = [entry for entry in self.inventory.entries
                    if entry.module == "tests.unit.snapshots."
                                       "test_snapshot_security"]
        self.assertTrue(security)
        for entry in security:
            with self.subTest(test=entry.test_id):
                self.assertIs(entry.category, Category.SECURITY_BOUNDARY)
        del by_id

    def test_a_selector_does_not_capture_a_sibling_package(self):
        """``tests.unit.web`` must not match ``tests.unit.website``."""
        rule = CategoryRule("probe", "tests.unit.web", Category.UNIT, "WP-17")
        self.assertTrue(rule.matches("tests.unit.web"))
        self.assertTrue(rule.matches("tests.unit.web.test_pages"))
        self.assertFalse(rule.matches("tests.unit.website"))
        self.assertFalse(rule.matches("tests.unit.webbing.test_x"))

    def test_the_postgresql_tests_may_skip_and_say_what_for(self):
        entries = [entry for entry in self.inventory.entries
                   if entry.category is Category.POSTGRESQL_INTEGRATION]
        self.assertTrue(entries)
        for entry in entries:
            with self.subTest(test=entry.test_id):
                self.assertTrue(entry.permitted_skip_reasons)
                self.assertIn("psycopg", entry.dependencies)

    def test_most_tests_may_not_skip_at_all(self):
        """The permission is the exception, not the rule.

        If the majority of the suite were allowed to skip, the unexplained-skip
        check would be checking almost nothing.
        """
        from pgx.verification.model import SkipPolicy
        never = sum(1 for entry in self.inventory.entries
                    if entry.skip_policy is SkipPolicy.NEVER)
        self.assertGreater(never, int(0.9 * self.inventory.count))

    def test_the_critical_path_is_marked_critical(self):
        by_module = {entry.module: entry for entry in self.inventory.entries}
        for module in ("tests.unit.test_claims",
                       "tests.safety.test_coverage_safety",
                       "tests.unit.engine.test_truth_matrix",
                       "tests.unit.validation.test_separation",
                       "tests.unit.snapshots.test_snapshot_build"):
            with self.subTest(module=module):
                self.assertIs(by_module[module].criticality,
                              Criticality.P0_CRITICAL)

    def test_the_wp20_safety_suite_is_categorised_and_critical(self):
        """The inventory refused these modules when they first appeared,
        which is the fail-closed behaviour working. Adding a rule is how a
        new suite enters the inventory; being unable to classify a test must
        never mean quietly ignoring it."""
        by_module = {entry.module: entry for entry in self.inventory.entries}
        registered = [name for name in by_module
                      if name.startswith("tests.unit.safety.")]
        self.assertGreaterEqual(len(registered), 12)
        for module in registered:
            with self.subTest(module=module):
                self.assertIs(by_module[module].criticality,
                              Criticality.P0_CRITICAL)

    def test_the_negative_control_fixtures_are_fixtures_not_tests(self):
        """``tests/fixtures/wp20`` holds unsafe mutants on purpose. If the
        inventory ever counted one as a test, the suite would be reporting
        deliberately-broken code as coverage."""
        for entry in self.inventory.entries:
            with self.subTest(module=entry.module):
                self.assertFalse(
                    entry.module.startswith("tests.fixtures."))
