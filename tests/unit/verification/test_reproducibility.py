# -*- coding: utf-8 -*-
"""Deterministic things reproduce, and a test that wavers is reported as one.

Two mechanisms, tested here together because they answer the same question at
different scales: does running this again give the same answer?
"""

from __future__ import annotations

import unittest

from pgx.verification.flaky import NO_MAJORITY_VOTE, compare_runs
from pgx.verification.model import Outcome
from pgx.verification.profiles import FLAKY_SUBSET_MODULES, profile_named
from pgx.verification.reproducibility import (
    ENVIRONMENT_DEPENDENT,
    GENERATORS,
    SEED_A,
    SEED_B,
    check_generators,
    file_digest,
)
from pgx.verification.results import build_profile_result

from tests.unit.verification._support import (
    REPO_ROOT,
    entry,
    inventory,
    profile,
    report,
)


def _result(outcomes, entries):
    return build_profile_result(profile(), report(outcomes),
                               inventory(*entries), discovered=len(outcomes))


class TestFlakinessIsNotPutToAVote(unittest.TestCase):

    def test_two_passes_and_one_failure_is_flaky_not_a_majority_pass(self):
        """The rule this whole module exists for."""
        entries = [entry("m.C.test_a")]
        runs = [
            _result({"m.C.test_a": {"outcome": "PASS", "reason": ""}}, entries),
            _result({"m.C.test_a": {"outcome": "PASS", "reason": ""}}, entries),
            _result({"m.C.test_a": {"outcome": "FAIL", "reason": "x"}},
                    entries),
        ]
        flaky = compare_runs("flaky", runs, "1")
        self.assertEqual(flaky.status, "FLAKY")
        self.assertEqual(len(flaky.flaky), 1)
        self.assertEqual(flaky.flaky[0].test_id, "m.C.test_a")
        self.assertEqual(flaky.flaky[0].outcomes, ("PASS", "PASS", "FAIL"))

    def test_one_failure_and_two_passes_in_any_order_is_still_flaky(self):
        entries = [entry("m.C.test_a")]
        runs = [
            _result({"m.C.test_a": {"outcome": "FAIL", "reason": "x"}},
                    entries),
            _result({"m.C.test_a": {"outcome": "PASS", "reason": ""}}, entries),
            _result({"m.C.test_a": {"outcome": "PASS", "reason": ""}}, entries),
        ]
        self.assertEqual(compare_runs("flaky", runs, "1").status, "FLAKY")

    def test_agreeing_runs_are_stable(self):
        entries = [entry("m.C.test_a")]
        runs = [_result({"m.C.test_a": {"outcome": "PASS", "reason": ""}},
                        entries) for _ in range(3)]
        stable = compare_runs("flaky", runs, "1")
        self.assertEqual(stable.status, "STABLE")
        self.assertTrue(stable.is_stable)
        self.assertEqual(stable.flaky, ())

    def test_a_test_that_appeared_in_only_some_runs_is_a_different_fault(self):
        """The selection moved. Reported apart from flakiness so the two are
        never confused."""
        runs = [
            _result({"m.C.test_a": {"outcome": "PASS", "reason": ""}},
                    [entry("m.C.test_a")]),
            _result({"m.C.test_a": {"outcome": "PASS", "reason": ""},
                     "m.C.test_b": {"outcome": "PASS", "reason": ""}},
                    [entry("m.C.test_a"), entry("m.C.test_b")]),
        ]
        result = compare_runs("flaky", runs, "1")
        self.assertEqual(result.unstable_selection, ("m.C.test_b",))
        self.assertEqual(result.flaky, ())
        self.assertEqual(result.status, "FLAKY")

    def test_a_single_run_says_nothing_about_stability(self):
        """Reporting one run as STABLE would be a claim nothing supports."""
        runs = [_result({"m.C.test_a": {"outcome": "PASS", "reason": ""}},
                        [entry("m.C.test_a")])]
        result = compare_runs("flaky", runs, "1")
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("single run is not evidence", result.note)

    def test_every_repetition_is_recorded_even_when_they_agreed(self):
        """A report that kept only the differences could not tell "ran three
        times, identical" from "ran once"."""
        entries = [entry("m.C.test_a")]
        runs = [_result({"m.C.test_a": {"outcome": "PASS", "reason": ""}},
                        entries) for _ in range(3)]
        document = compare_runs("flaky", runs, "1").as_document()
        self.assertEqual(document["repetitions"], 3)
        self.assertEqual(len(document["counts_by_repetition"]), 3)

    def test_the_document_states_that_no_vote_was_taken(self):
        entries = [entry("m.C.test_a")]
        runs = [_result({"m.C.test_a": {"outcome": "PASS", "reason": ""}},
                        entries) for _ in range(2)]
        self.assertEqual(compare_runs("f", runs, "1").as_document()["note"],
                         NO_MAJORITY_VOTE)
        self.assertIn("No majority vote", NO_MAJORITY_VOTE)

    def test_the_seed_is_recorded_beside_the_result(self):
        entries = [entry("m.C.test_a")]
        runs = [_result({"m.C.test_a": {"outcome": "PASS", "reason": ""}},
                        entries) for _ in range(2)]
        self.assertEqual(compare_runs("f", runs, "20260904").hash_seed,
                         "20260904")


class TestArtifactsRebuildToTheSameBytes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.report = check_generators(REPO_ROOT)

    def test_every_generator_reproduces(self):
        self.assertEqual(self.report.status, "REPRODUCIBLE",
                         [item.as_document() for item in self.report.generators
                          if item.status != "REPRODUCIBLE"])

    def test_no_generator_produced_different_bytes_twice(self):
        for item in self.report.generators:
            with self.subTest(generator=item.generator):
                self.assertEqual(item.unstable_artifacts, ())

    def test_no_committed_artifact_is_stale(self):
        for item in self.report.generators:
            with self.subTest(generator=item.generator):
                self.assertEqual(item.stale_committed_artifacts, ())
                self.assertEqual(item.missing_committed_artifacts, ())

    def test_the_two_seeds_differ_and_neither_is_zero(self):
        """Zero disables hash randomisation, under which an order-dependent
        document reproduces perfectly and the check proves nothing."""
        self.assertNotEqual(SEED_A, SEED_B)
        self.assertNotIn("0", (SEED_A, SEED_B))

    def test_every_excluded_artifact_measures_its_environment(self):
        """The exclusion list admits only documents that read the world.

        The check was a name test - "gate-status" or "runtime-verification"
        in the path - which worked while those were the only two kinds. WP-23
        added a secret-scan report, which walks the filesystem and so
        legitimately differs between a full checkout and a sparse one, and
        the name test would have forced it to be renamed to be excluded.

        Naming is not the property. The property is that the document is a
        *measurement of the environment* rather than a function of the
        source, so the successor enumerates the excluded set with the reason
        each is in it - which is what a reader of this list needs, and what
        stops a genuinely deterministic artifact being excluded to make a
        staleness failure go away.
        """
        reasons = {
            "data/api/wp16-real-gate-status.json": "reads settings and probes",
            "data/web/wp17-real-gate-status.json": "reads settings and probes",
            "data/validation/wp18-real-gate-status.json": "reads the tree",
            "data/verification/wp19-real-gate-status.json": "reads the tree",
            "data/api/wp16-runtime-verification.json": "records the runtime",
            "data/expert-review/wp22-real-gate-status.json": "reads the tree",
            "data/security/wp23-real-gate-status.json":
                "reads environment variables and the tree",
            "data/security/wp23-secret-scan-report.json":
                "walks the filesystem, so a different checkout differs",
            "data/deployment/wp24-real-gate-status.json":
                "reads the tree, the environment probe and a clock",
            "data/deployment/wp24-release-validation.json":
                "reads every upstream gate artifact and a clock",
            "data/deployment/wp24-gate-e-status.json":
                "reads WP-23's and WP-24's own artifacts and a clock",
            "data/deployment/wp24-build-provenance.json":
                "hashes the whole source tree and records the interpreter, "
                "the platform and whether a lockfile exists",
            "data/deployment/wp24-secret-configuration.json":
                "reads environment variables to report which secrets are "
                "configured, by mechanism and never by value",
            "data/ths6/wp25-evidence-registry.json":
                "hashes every declared artifact in the working tree, so a "
                "different checkout differs",
            "data/ths6/wp25-claim-registry.json":
                "reads gate-status artifacts that are themselves "
                "environment-dependent",
            "data/ths6/wp25-traceability-matrix.json":
                "checks whether each cited module and test file exists in "
                "this tree",
            "data/ths6/wp25-gate-matrix.json":
                "reads every upstream gate artifact and parses the test tree "
                "to detect a stale recorded count",
            "data/ths6/wp25-definition-of-done.json":
                "evaluates gate conditions read from environment-dependent "
                "artifacts",
            "data/ths6/wp25-demo-preflight.json":
                "measures the environment: package-index reachability, the "
                "LLM switch and whether the P1 modules exist on disk",
            "data/ths6/wp25-findings.json":
                "gathers findings produced by the measuring documents above",
            "data/ths6/wp25-ths6-status.json":
                "aggregates every measuring document",
            "data/ths6/wp25-evidence-pack-manifest.json":
                "hashes every pack member, so a different checkout differs",
        }
        self.assertEqual(set(ENVIRONMENT_DEPENDENT), set(reasons))
        for path, reason in sorted(reasons.items()):
            with self.subTest(path=path):
                self.assertTrue(reason)

    def test_the_exclusions_are_reported_rather_than_silent(self):
        excluded = {path for item in self.report.generators
                    for path in item.excluded_from_committed_comparison}
        self.assertTrue(excluded)
        for path in excluded:
            with self.subTest(path=path):
                self.assertIn(path, ENVIRONMENT_DEPENDENT)

    def test_the_verification_generator_is_itself_checked(self):
        names = {item.generator for item in self.report.generators}
        self.assertIn("verification", names)

    def test_every_generator_names_a_real_module(self):
        import importlib
        for generator in GENERATORS:
            with self.subTest(generator=generator.name):
                module = importlib.import_module(generator.module)
                self.assertTrue(hasattr(module, "build_artifacts"))

    def test_a_missing_file_has_no_digest_rather_than_a_wrong_one(self):
        self.assertIsNone(file_digest("/nonexistent/path/for/a/test"))


class TestTheRepeatedSubsetIsDeterministicByDesign(unittest.TestCase):

    def test_the_subset_needs_no_database_browser_or_network(self):
        """A module that is *meant* to vary would manufacture a flaky report
        that says nothing about stability."""
        from pgx.verification.discovery import discover
        from pgx.verification.inventory import build_inventory
        from pgx.verification.model import Category
        inventoried = build_inventory(discover(REPO_ROOT))
        bound = {Category.POSTGRESQL_INTEGRATION, Category.BROWSER_E2E,
                 Category.ASGI_RUNTIME}
        for item in inventoried.entries:
            if item.module in FLAKY_SUBSET_MODULES:
                with self.subTest(module=item.module):
                    self.assertNotIn(item.category, bound)
                    self.assertTrue(item.offline)

    def test_the_reproducibility_profile_repeats_the_same_subset(self):
        self.assertEqual(profile_named("reproducibility").modules,
                         profile_named("flaky").modules)
