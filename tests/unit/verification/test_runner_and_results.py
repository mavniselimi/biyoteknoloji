# -*- coding: utf-8 -*-
"""The five outcomes stay apart, and no green light is free.

Every test here corresponds to a way the verification system could report
success without having verified anything: a skipped suite read as passing, a
selection that matched nothing, an unexplained skip waved through, a class-level
skip hiding seventy-seven tests, or a word found in stdout mistaken for a
result.
"""

from __future__ import annotations

import unittest

from pgx.verification.discovery import discover
from pgx.verification.errors import ProfileError, RunnerError
from pgx.verification.inventory import build_inventory
from pgx.verification.model import (
    Category,
    Criticality,
    Outcome,
    SkipClassification,
    SkipPolicy,
    SuiteSummary,
    is_passing,
    worst_outcome,
)
from pgx.verification.profiles import (
    FLAKY_SUBSET_MODULES,
    PROFILES,
    profile_named,
    profile_names,
)
from pgx.verification.results import (
    ISSUE_BELOW_MINIMUM,
    ISSUE_CATEGORY_BLOCKED,
    ISSUE_FAILURES,
    ISSUE_MISSING_RESULT,
    ISSUE_NO_TESTS_EXECUTED,
    ISSUE_UNEXPLAINED_SKIP,
    KNOWN_STDOUT_MARKERS,
    STDOUT_IS_NOT_A_RESULT,
    build_profile_result,
    classify_skip,
    result_signature,
)
from pgx.verification.runner import (
    DEFAULT_HASH_SEED,
    select_test_ids,
    worker_environment,
)

from tests.unit.verification._support import (
    REPO_ROOT,
    entry,
    inventory,
    profile,
    report,
)


class TestOutcomesCannotBeConflated(unittest.TestCase):

    def test_only_pass_passes(self):
        for outcome in Outcome:
            with self.subTest(outcome=outcome.value):
                self.assertEqual(is_passing(outcome),
                                 outcome is Outcome.PASS)

    def test_outcomes_refuse_to_be_ordered(self):
        """So that nobody can write ``max(outcomes)`` and turn a blocked
        category into a passing one."""
        with self.assertRaises(TypeError):
            _ = Outcome.SKIP < Outcome.PASS
        with self.assertRaises(TypeError):
            _ = sorted([Outcome.PASS, Outcome.FAIL])

    def test_combining_nothing_is_missing_and_not_pass(self):
        """Nothing observed is not the same as nothing wrong."""
        self.assertIs(worst_outcome([]), Outcome.MISSING)

    def test_the_precedence_is_explicit(self):
        self.assertIs(worst_outcome([Outcome.PASS, Outcome.SKIP]),
                      Outcome.SKIP)
        self.assertIs(worst_outcome([Outcome.PASS, Outcome.BLOCKED]),
                      Outcome.BLOCKED)
        self.assertIs(worst_outcome([Outcome.BLOCKED, Outcome.FAIL]),
                      Outcome.FAIL)
        self.assertIs(worst_outcome([Outcome.FAIL, Outcome.ERROR]),
                      Outcome.ERROR)
        self.assertIs(worst_outcome([Outcome.PASS, Outcome.PASS]),
                      Outcome.PASS)

    def test_a_summary_with_nothing_executed_is_not_clean(self):
        empty = SuiteSummary(discovered=10, executed=0, passed=0, failed=0,
                             errored=0, skipped=0, unexplained_skips=0,
                             not_executed=10)
        self.assertFalse(empty.is_clean)

    def test_a_summary_with_an_unexplained_skip_is_not_clean(self):
        summary = SuiteSummary(discovered=2, executed=2, passed=1, failed=0,
                               errored=0, skipped=1, unexplained_skips=1,
                               not_executed=0)
        self.assertFalse(summary.is_clean)


class TestSkipsAreClassifiedAgainstTheirDeclaredPolicy(unittest.TestCase):

    def test_a_test_that_may_never_skip_is_unexplained_when_it_does(self):
        item = entry("m.C.test_a", skip_policy=SkipPolicy.NEVER)
        self.assertIs(classify_skip(item, "any reason at all"),
                      SkipClassification.UNEXPLAINED)

    def test_a_permitted_reason_is_allowed(self):
        item = entry("m.C.test_a",
                     skip_policy=SkipPolicy.ENVIRONMENT_DEPENDENCY,
                     permitted=("requires psycopg",))
        self.assertIs(
            classify_skip(item, "This suite requires psycopg, which is absent"),
            SkipClassification.ALLOWED)

    def test_the_wrong_excuse_does_not_work(self):
        """A browser test may not skip because a database is missing."""
        item = entry("m.C.test_a",
                     skip_policy=SkipPolicy.ENVIRONMENT_DEPENDENCY,
                     permitted=("browser",))
        self.assertIs(classify_skip(item, "requires psycopg"),
                      SkipClassification.UNEXPLAINED)

    def test_a_test_nobody_inventoried_gets_no_benefit_of_the_doubt(self):
        self.assertIs(classify_skip(None, "requires psycopg"),
                      SkipClassification.UNEXPLAINED)

    def test_a_policy_with_no_declared_reason_is_unexplained(self):
        item = entry("m.C.test_a", skip_policy=SkipPolicy.CAPABILITY,
                     permitted=())
        self.assertIs(classify_skip(item, "anything"),
                      SkipClassification.UNEXPLAINED)

    def test_any_one_of_several_declared_reasons_is_enough(self):
        """A module with more than one honest reason to stand down declares
        all of them; collapsing them into one phrase would either accept every
        skip or reject a real one."""
        item = entry("m.C.test_a", skip_policy=SkipPolicy.CAPABILITY,
                     permitted=("ignores chmod",
                                "no writer subject to these mode bits",
                                "can drop privileges"))
        for reason in ("this filesystem ignores chmod",
                       "no writer subject to these mode bits exists here",
                       "this platform can drop privileges"):
            with self.subTest(reason=reason):
                self.assertIs(classify_skip(item, reason),
                              SkipClassification.ALLOWED)
        self.assertIs(classify_skip(item, "felt like it"),
                      SkipClassification.UNEXPLAINED)


class TestAProfileCannotPassWithoutRunning(unittest.TestCase):

    def _result(self, outcomes, entries, minimum=1, planned=None,
                not_executed=()):
        return build_profile_result(
            profile(minimum=minimum),
            report(outcomes, planned=planned, not_executed=not_executed),
            inventory(*entries), discovered=100)

    def test_zero_executed_tests_is_an_error_not_a_pass(self):
        result = self._result({}, [], planned=[])
        self.assertIs(result.outcome, Outcome.ERROR)
        self.assertIn(ISSUE_NO_TESTS_EXECUTED, result.issue_codes)

    def test_fewer_tests_than_the_declared_floor_is_an_error(self):
        """The cheapest false green: a selector stops matching and the profile
        goes green in two seconds."""
        result = self._result({"m.C.test_a": {"outcome": "PASS",
                                              "reason": ""}},
                              [entry("m.C.test_a")], minimum=50)
        self.assertIs(result.outcome, Outcome.ERROR)
        self.assertIn(ISSUE_BELOW_MINIMUM, result.issue_codes)

    def test_a_suite_that_only_skipped_is_blocked_not_passed(self):
        result = self._result(
            {"m.C.test_a": {"outcome": "SKIP", "reason": "requires psycopg"}},
            [entry("m.C.test_a",
                   skip_policy=SkipPolicy.ENVIRONMENT_DEPENDENCY,
                   permitted=("requires psycopg",))])
        self.assertIs(result.outcome, Outcome.BLOCKED)
        self.assertIn("psycopg", result.blocked_reason)

    def test_an_unexplained_skip_fails_the_profile(self):
        result = self._result(
            {"m.C.test_a": {"outcome": "PASS", "reason": ""},
             "m.C.test_b": {"outcome": "SKIP", "reason": "felt like it"}},
            [entry("m.C.test_a"), entry("m.C.test_b")])
        self.assertIs(result.outcome, Outcome.FAIL)
        self.assertIn(ISSUE_UNEXPLAINED_SKIP, result.issue_codes)
        self.assertEqual(result.summary.unexplained_skips, 1)

    def test_a_planned_test_with_no_result_is_an_error(self):
        """Not a failure. Nothing is known about it, which is worse than
        knowing it failed and must not read as knowing it passed."""
        result = self._result(
            {"m.C.test_a": {"outcome": "PASS", "reason": ""}},
            [entry("m.C.test_a"), entry("m.C.test_b")],
            planned=["m.C.test_a", "m.C.test_b"],
            not_executed=["m.C.test_b"])
        self.assertIs(result.outcome, Outcome.ERROR)
        self.assertIn(ISSUE_MISSING_RESULT, result.issue_codes)
        self.assertEqual(result.summary.not_executed, 1)

    def test_a_failure_is_a_failure(self):
        result = self._result(
            {"m.C.test_a": {"outcome": "FAIL", "reason": "AssertionError: x"}},
            [entry("m.C.test_a")])
        self.assertIs(result.outcome, Outcome.FAIL)
        self.assertIn(ISSUE_FAILURES, result.issue_codes)

    def test_an_error_outranks_a_failure(self):
        result = self._result(
            {"m.C.test_a": {"outcome": "FAIL", "reason": "x"},
             "m.C.test_b": {"outcome": "ERROR", "reason": "y"}},
            [entry("m.C.test_a"), entry("m.C.test_b")])
        self.assertIs(result.outcome, Outcome.ERROR)

    def test_an_unrecognised_worker_outcome_becomes_an_error(self):
        """An unreadable result is not a pass."""
        result = self._result(
            {"m.C.test_a": {"outcome": "PROBABLY_FINE", "reason": ""}},
            [entry("m.C.test_a")])
        self.assertIs(result.outcome, Outcome.ERROR)

    def test_a_healthy_run_passes(self):
        result = self._result(
            {"m.C.test_a": {"outcome": "PASS", "reason": ""},
             "m.C.test_b": {"outcome": "PASS", "reason": ""}},
            [entry("m.C.test_a"), entry("m.C.test_b")])
        self.assertIs(result.outcome, Outcome.PASS)
        self.assertEqual(result.issue_codes, ())

    def test_a_blocked_category_is_reported_even_when_the_profile_passes(self):
        """A profile can be PASS while a category inside it is BLOCKED. That
        is not a contradiction; it is why the table exists."""
        result = self._result(
            {"m.C.test_a": {"outcome": "PASS", "reason": ""},
             "d.C.test_b": {"outcome": "SKIP", "reason": "requires psycopg"}},
            [entry("m.C.test_a", category=Category.UNIT),
             entry("d.C.test_b", category=Category.POSTGRESQL_INTEGRATION,
                   skip_policy=SkipPolicy.ENVIRONMENT_DEPENDENCY,
                   permitted=("requires psycopg",))])
        self.assertIs(result.outcome, Outcome.PASS)
        self.assertIn(ISSUE_CATEGORY_BLOCKED, result.issue_codes)
        self.assertEqual(result.blocked_categories,
                         ("POSTGRESQL_INTEGRATION",))


class TestStdoutIsNotAResult(unittest.TestCase):
    """Several negative tests print CONFIGURATION_FAILURE while passing."""

    def test_the_marker_is_documented_so_a_ci_job_does_not_grep_for_it(self):
        self.assertIn("CONFIGURATION_FAILURE", KNOWN_STDOUT_MARKERS)
        self.assertIn("CONFIGURATION_FAILURE", STDOUT_IS_NOT_A_RESULT)

    def test_a_passing_run_that_printed_the_marker_still_passes(self):
        loud = report({"m.C.test_a": {"outcome": "PASS", "reason": ""}})
        loud = loud.__class__(
            outcomes=loud.outcomes, planned=loud.planned,
            not_executed=loud.not_executed,
            runner_tests_run=loud.runner_tests_run,
            elapsed_seconds_approximate=0,
            subtest_failure_counts={},
            stdout="CONFIGURATION_FAILURE: this is deliberate\n",
            stderr="", exit_code=0)
        result = build_profile_result(profile(), loud,
                                      inventory(entry("m.C.test_a")), 1)
        self.assertIs(result.outcome, Outcome.PASS)

    def test_the_note_travels_with_every_result(self):
        result = build_profile_result(
            profile(), report({"m.C.test_a": {"outcome": "PASS",
                                              "reason": ""}}),
            inventory(entry("m.C.test_a")), 1)
        self.assertEqual(result.as_document()["stdout_note"],
                         STDOUT_IS_NOT_A_RESULT)


class TestTheProfileRegistry(unittest.TestCase):

    def test_the_named_profiles_exist(self):
        """Seven at WP-19, plus ``safety`` (WP-20), ``validation`` (WP-21),
        ``expert-review`` (WP-22), ``security`` (WP-23), ``deployment``
        (WP-24) and ``ths6`` (WP-25).

        The set is pinned so a profile cannot appear or vanish without a test
        saying so - including one that quietly narrowed an existing profile
        rather than adding its own. Each later work package that adds a
        profile edits this line, in the open, which is the point.
        """
        self.assertEqual(
            set(profile_names()),
            {"fast", "p0", "runtime", "database", "full", "reproducibility",
             "flaky", "safety", "validation", "expert-review", "security",
             "deployment", "ths6"})

    def test_the_validation_profile_covers_both_packages(self):
        """WP-18 decides which cases may be counted; WP-21 counts them. A
        profile holding only one of the two would let the other regress."""
        from pgx.verification.profiles import profile_named
        selected = profile_named("validation")
        self.assertGreaterEqual(selected.minimum_tests, 350)
        self.assertIn("tests.unit.validation", selected.modules)
        self.assertIn("tests.unit.benchmark", selected.modules)

    def test_the_safety_profile_selects_the_invariant_modules(self):
        """WP-20's profile is a named subset with a floor, not a filter that
        can silently select nothing."""
        from pgx.verification.profiles import (SAFETY_INVARIANT_MODULES,
                                               profile_named)
        selected = profile_named("safety")
        self.assertGreaterEqual(selected.minimum_tests, 300)
        self.assertTrue(SAFETY_INVARIANT_MODULES)
        for module in SAFETY_INVARIANT_MODULES:
            with self.subTest(module=module):
                self.assertTrue(module.startswith("tests."))

    def test_an_unknown_profile_raises_rather_than_defaulting(self):
        """A typo that silently ran ``fast`` instead of ``full`` would produce
        a green result for a profile nobody executed."""
        with self.assertRaises(ProfileError):
            profile_named("fastt")

    def test_every_profile_declares_a_floor_above_zero(self):
        for item in PROFILES:
            with self.subTest(profile=item.name):
                self.assertGreaterEqual(item.minimum_tests, 1)

    def test_every_profile_is_offline(self):
        for item in PROFILES:
            with self.subTest(profile=item.name):
                self.assertTrue(item.offline)

    def test_the_flaky_and_reproducibility_profiles_repeat(self):
        self.assertEqual(profile_named("flaky").repeats, 3)
        self.assertEqual(profile_named("reproducibility").repeats, 2)

    def test_the_repeated_subset_is_bounded_and_written_down(self):
        """Repeating five thousand tests three times to learn one fact is not
        a design, it is a bill."""
        self.assertGreater(len(FLAKY_SUBSET_MODULES), 5)
        self.assertLess(len(FLAKY_SUBSET_MODULES), 30)

    def test_the_repeated_subset_names_modules_that_exist(self):
        known = {row.module for row in
                 build_inventory(discover(REPO_ROOT)).entries}
        for module in FLAKY_SUBSET_MODULES:
            with self.subTest(module=module):
                self.assertIn(module, known)

    def test_the_full_profile_uses_discovery_not_a_list_of_ids(self):
        """So that the profile a release is judged on is the same enumeration
        as the documented command."""
        self.assertTrue(profile_named("full").discover)

    def test_the_database_profile_is_not_required(self):
        """No PostgreSQL exists in every environment, and a required profile
        that cannot run would block every release for an unrelated reason. Its
        real state is reported by the gate status as BLOCKED, not as a pass."""
        self.assertFalse(profile_named("database").required)


class TestSelection(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.inventory = build_inventory(discover(REPO_ROOT))

    def test_the_p0_profile_selects_only_critical_tests(self):
        selected = set(select_test_ids(profile_named("p0"), self.inventory))
        by_id = self.inventory.by_id()
        self.assertTrue(selected)
        for test_id in list(selected)[:500]:
            with self.subTest(test=test_id):
                self.assertIs(by_id[test_id].criticality,
                              Criticality.P0_CRITICAL)

    def test_the_fast_profile_excludes_the_bound_categories(self):
        selected = set(select_test_ids(profile_named("fast"), self.inventory))
        by_id = self.inventory.by_id()
        excluded = {Category.POSTGRESQL_INTEGRATION, Category.MIGRATION,
                    Category.ASGI_RUNTIME, Category.BROWSER_E2E,
                    Category.LEGACY_REGRESSION}
        for test_id in selected:
            self.assertNotIn(by_id[test_id].category, excluded)

    def test_selection_is_deterministic(self):
        first = select_test_ids(profile_named("p0"), self.inventory)
        second = select_test_ids(profile_named("p0"), self.inventory)
        self.assertEqual(first, second)
        self.assertEqual(list(first), sorted(first))

    def test_the_database_profile_selects_the_postgresql_tests(self):
        selected = set(select_test_ids(profile_named("database"),
                                       self.inventory))
        by_id = self.inventory.by_id()
        categories = {by_id[test_id].category for test_id in selected}
        self.assertEqual(categories, {Category.POSTGRESQL_INTEGRATION,
                                      Category.MIGRATION})


class TestTheWorkerEnvironmentIsDeliberate(unittest.TestCase):

    def test_the_hash_seed_is_fixed_and_not_zero(self):
        """Zero disables hash randomisation entirely, which would hide a
        genuine ordering dependency rather than expose it."""
        environment = worker_environment()
        self.assertEqual(environment["PYTHONHASHSEED"], DEFAULT_HASH_SEED)
        self.assertNotEqual(DEFAULT_HASH_SEED, "0")

    def test_bytecode_writing_is_off(self):
        """So a repeat cannot differ because the first run left a cache."""
        self.assertEqual(worker_environment()["PYTHONDONTWRITEBYTECODE"], "1")

    def test_resource_warnings_are_errors_as_in_the_documented_command(self):
        self.assertEqual(worker_environment()["PYTHONWARNINGS"],
                         "error::ResourceWarning")

    def test_a_supplied_database_url_is_passed_through_untouched(self):
        """WP-19 never invents one and never points a suite at a database of
        its own choosing; the database tests decide for themselves whether
        what they were given is disposable."""
        environment = worker_environment(
            base={"TEST_DATABASE_URL": "postgresql://x@y/pgx_test"})
        self.assertEqual(environment["TEST_DATABASE_URL"],
                         "postgresql://x@y/pgx_test")

    def test_no_database_url_is_added_when_none_was_given(self):
        self.assertNotIn("TEST_DATABASE_URL", worker_environment(base={}))


class TestResultSignaturesExcludeWhatMustVary(unittest.TestCase):

    def test_the_signature_is_test_id_to_outcome_and_nothing_else(self):
        result = build_profile_result(
            profile(),
            report({"m.C.test_a": {"outcome": "SKIP",
                                   "reason": "psycopg 3.3.5 is absent"}}),
            inventory(entry("m.C.test_a",
                            skip_policy=SkipPolicy.ENVIRONMENT_DEPENDENCY,
                            permitted=("psycopg",))), 1)
        signature = result_signature(result)
        self.assertEqual(signature, {"m.C.test_a": "SKIP"})
        self.assertNotIn("psycopg 3.3.5 is absent", str(signature))

    def test_two_runs_that_differ_only_in_reason_have_one_signature(self):
        """A skip reason can name a package version, and a version bump is not
        a flaky test."""
        def build(reason):
            return result_signature(build_profile_result(
                profile(),
                report({"m.C.test_a": {"outcome": "SKIP", "reason": reason}}),
                inventory(entry("m.C.test_a",
                                skip_policy=SkipPolicy.ENVIRONMENT_DEPENDENCY,
                                permitted=("psycopg",))), 1))
        self.assertEqual(build("psycopg 3.3.5 absent"),
                         build("psycopg 3.4.0 absent"))
