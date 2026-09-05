# -*- coding: utf-8 -*-
"""What WP-21 must not do, asserted rather than promised.

Four boundaries: production never imports tests; no expected answer was added
to WP-18; the committed artifacts reproduce byte for byte; and WP-21 stays
inside its own job - it benchmarks, and it does not authenticate, audit,
deploy, or inventory and gate the programme.

The fourth boundary used to be "WP-22, WP-23, WP-24 and WP-25 remain
unstarted". All four have now delivered. A boundary test that asserts a
neighbouring work package has not shipped stops being a boundary the day it
does; what survives is the property each successor was really protecting.
"""

from __future__ import annotations

import ast
import io
import json
import os
import unittest

from tests.unit.benchmark._support import REPO_ROOT, read_json

_WP21_MODULES = (
    "pgx/validation/metric_definitions.py",
    "pgx/validation/metrics.py",
    "pgx/validation/benchmark_models.py",
    "pgx/validation/benchmark.py",
    "pgx/validation/benchmark_report.py",
    "pgx/validation/benchmark_gate_status.py",
    "pgx/validation/dashboard_feed.py",
    "pgx/validation/benchmark_artifacts.py",
    "pgx/application/benchmark_schema.py",
    "pgx/application/benchmark_cli.py",
)


def _tree(relative: str) -> ast.AST:
    with io.open(os.path.join(REPO_ROOT, *relative.split("/")), "r",
                 encoding="utf-8") as handle:
        return ast.parse(handle.read())


def _imports(relative: str):
    names = set()
    for node in ast.walk(_tree(relative)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


class TestProductionNeverImportsTests(unittest.TestCase):
    """Requirement 22. A wheel without the test tree must still import."""

    def test_no_wp21_module_imports_the_test_package(self):
        for relative in _WP21_MODULES:
            with self.subTest(module=relative):
                for imported in _imports(relative):
                    self.assertFalse(
                        imported == "tests" or imported.startswith("tests."),
                        "%s imports %s" % (relative, imported))

    def test_no_wp21_module_names_the_fixture_in_a_string(self):
        """A lazy import by name would evade the AST check above."""
        for relative in _WP21_MODULES:
            with self.subTest(module=relative):
                with io.open(os.path.join(REPO_ROOT,
                                          *relative.split("/")), "r",
                             encoding="utf-8") as handle:
                    source = handle.read()
                stripped = "\n".join(
                    line for line in source.splitlines()
                    if not line.lstrip().startswith("#"))
                self.assertNotIn("tests.fixtures", stripped)
                self.assertNotIn("synthetic_release", stripped)

    def test_the_cli_offers_no_test_fixture_switch(self):
        """A production flag that swapped emptiness for synthetic numbers
        would be one typo away from a fabricated validation result.

        Asserted against the parser's real options rather than the file's
        text: the module docstring explains *why* there is no such flag, so a
        substring search finds its own prose and passes for the wrong reason.
        """
        from pgx.application import benchmark_cli
        parser = benchmark_cli._parser()
        options = set()

        def _collect(target):
            for action in getattr(target, "_actions", ()):
                options.update(action.option_strings)
                options.add(action.dest)
                for choice in (getattr(action, "choices", None) or {}).values():
                    if hasattr(choice, "_actions"):
                        _collect(choice)

        _collect(parser)
        for forbidden in ("--use-test-fixture", "use_test_fixture",
                          "--fixture", "--synthetic", "--demo"):
            with self.subTest(option=forbidden):
                self.assertNotIn(forbidden, options)


class TestNoExpectedAnswerWasAddedToWp18(unittest.TestCase):
    """A11. WP-18's rule is that a case carries no answer; WP-21 keeps it."""

    _FORBIDDEN = ("expected_result", "expected_attention", "expected_coverage",
                  "gold_standard", "ground_truth", "answer_key", "score",
                  "concordance", "expert_decision")

    def test_the_case_model_still_prohibits_them(self):
        from pgx.validation.cases import PROHIBITED_CASE_FIELDS
        for name in ("expected_result", "gold_standard", "ground_truth",
                     "answer_key"):
            with self.subTest(field=name):
                self.assertIn(name, PROHIBITED_CASE_FIELDS)

    def test_the_committed_case_manifests_carry_none_of_them(self):
        for relative in ("data/validation/wp18-development-case-manifest.json",
                         "data/validation/wp18-holdout-case-manifest.json"):
            payload = json.dumps(read_json(relative)).lower()
            for name in self._FORBIDDEN:
                with self.subTest(manifest=relative, field=name):
                    self.assertNotIn('"%s"' % name, payload)

    def test_a_reference_judgment_is_a_separate_object(self):
        """Not a case field: its own record, with its own provenance."""
        from pgx.validation.benchmark_models import ReferenceJudgment
        from pgx.validation.cases import ValidationCaseMetadata
        self.assertFalse(hasattr(ValidationCaseMetadata,
                                 "expected_attention_level"))
        self.assertTrue(hasattr(ReferenceJudgment, "expected_attention_level"))

    def test_a_judgment_without_provenance_is_refused(self):
        from pgx.validation.benchmark_models import (BenchmarkError,
                                                     ReferenceJudgment)
        with self.assertRaises(BenchmarkError):
            ReferenceJudgment(case_id="x", expected_attention_level="HIGH",
                              expected_coverage_status="FULL", provenance="")


class TestTheArtifactsReproduce(unittest.TestCase):
    """Requirement 29 and A24."""

    @classmethod
    def setUpClass(cls):
        from pgx.validation.benchmark_artifacts import build_artifacts
        cls.first = build_artifacts(REPO_ROOT)
        cls.second = build_artifacts(REPO_ROOT)

    def test_two_builds_agree(self):
        self.assertEqual(sorted(self.first), sorted(self.second))
        for relative in sorted(self.first):
            with self.subTest(artifact=relative):
                self.assertEqual(self.first[relative], self.second[relative])

    def test_the_committed_bytes_equal_a_fresh_build(self):
        for relative, rendered in sorted(self.first.items()):
            with self.subTest(artifact=relative):
                path = os.path.join(REPO_ROOT, *relative.split("/"))
                with io.open(path, "r", encoding="utf-8") as handle:
                    self.assertEqual(handle.read(), rendered)

    def test_every_artifact_is_canonical_json(self):
        for relative, rendered in sorted(self.first.items()):
            with self.subTest(artifact=relative):
                document = json.loads(rendered)
                expected = json.dumps(document, indent=2, sort_keys=True,
                                      ensure_ascii=True) + "\n"
                self.assertEqual(rendered, expected)


class TestNoLaterWorkPackageWasStarted(unittest.TestCase):
    """A27. Measured from the tree, not asserted.

    WP-22 has since started, so the WP-22 assertions in this class have moved
    to what they were defending: not that the review module was absent, but
    that **WP-21 did not build it**. The metric layer must consume expert
    decisions through a port and must not contain a reveal, a blinding rule
    or a review workflow of its own - otherwise there would be two review
    implementations and only one of them under the protocol.
    """

    def test_wp21_contains_no_review_module_of_its_own(self):
        """WP-22's module exists; none of it lives inside WP-21."""
        for relative in ("pgx/validation/expert_review.py",
                         "pgx/validation/review.py",
                         "pgx/validation/blind_review.py",
                         "pgx/review"):
            with self.subTest(path=relative):
                self.assertFalse(os.path.exists(
                    os.path.join(REPO_ROOT, *relative.split("/"))))

    def test_wp21_reaches_expert_decisions_only_through_a_port(self):
        """The metric modules import no WP-22 record type.

        A metric module that imported ``CompletionDecision`` could read a
        review's internals - its note, its corrections, its audit chain -
        and summarise them. It consumes an injected port instead, so the
        only thing it can see is what the port hands it.
        """
        import ast
        forbidden = {"pgx.expert_review.models", "pgx.expert_review.service",
                     "pgx.expert_review.audit", "pgx.expert_review.protocol"}
        for relative in ("pgx/validation/benchmark.py",
                         "pgx/validation/metrics.py",
                         "pgx/validation/metric_definitions.py",
                         "pgx/validation/dashboard_feed.py"):
            with io.open(os.path.join(REPO_ROOT, *relative.split("/")),
                         encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                module = None
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                elif isinstance(node, ast.Import):
                    module = ",".join(alias.name for alias in node.names)
                if module:
                    with self.subTest(module=relative, imported=module):
                        for name in forbidden:
                            self.assertNotIn(name, module)

    def test_wp21_does_not_authenticate_authorise_or_audit(self):
        """WP-23 has delivered, so absence is no longer the property.

        This assertion used to be that ``pgx/auth``, ``pgx/audit`` and
        ``pgx/rbac`` did not exist. Those three paths were guesses at names
        WP-23 might choose; it chose ``pgx/security`` and
        ``pgx/infrastructure/audit`` instead, so the old test would have kept
        passing while the thing it was watching for arrived - which is worse
        than failing. What WP-21 must never do is decide who a caller is, what
        a caller may do, or write a governed audit record: benchmarking reads
        assessments, it does not gate them.
        """
        # WP-24 added a third. Benchmarking reads assessments; it does not
        # gate them, record them, or deploy anything.
        forbidden = ("pgx.security", "pgx.infrastructure.audit",
                     "pgx.deployment")
        for relative in _WP21_MODULES:
            with io.open(os.path.join(REPO_ROOT, *relative.split("/")), "r",
                         encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                module = None
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                elif isinstance(node, ast.Import):
                    module = ",".join(alias.name for alias in node.names)
                if module:
                    with self.subTest(module=relative, imported=module):
                        for name in forbidden:
                            self.assertNotIn(name, module)

    def test_wp21_does_not_inventory_or_gate_the_programme(self):
        """Renamed for the fourth and final time, and this one has no successor.

        The lineage: "no WP-22, WP-23, WP-24 or WP-25 package exists", then
        each in turn as they landed, and finally "no WP-25 evidence pack
        exists". WP-25 has now delivered ``pgx/ths6``, so that assertion
        would be asserting a delivered package was not delivered - the same
        mistake, four work packages running.

        The durable property is what WP-21 must never do: benchmarking reads
        assessments and computes metrics. It does not build an evidence
        inventory, evaluate a gate, or decide whether a programme has met a
        standard. Those belong to WP-25, and a WP-21 module importing
        ``pgx.ths6`` would mean the benchmark layer had started grading the
        project it is part of.
        """
        forbidden = ("pgx.ths6", "pgx.verification.gate_status")
        for relative in _WP21_MODULES:
            with io.open(os.path.join(REPO_ROOT, *relative.split("/")), "r",
                         encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                module = None
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                elif isinstance(node, ast.Import):
                    module = ",".join(alias.name for alias in node.names)
                if module:
                    with self.subTest(module=relative, imported=module):
                        for name in forbidden:
                            self.assertNotIn(name, module)

    def test_no_module_reimplements_the_pipeline_in_python(self):
        """``pgx/ci`` stays absent, and this one is still about absence.

        WP-24 put its pipeline in ``.github/workflows`` rather than in a
        Python package. A ``pgx/ci`` appearing later would be somebody
        re-implementing a pipeline in code, where it could not be executed by
        a provider and could quietly claim to have run.
        """
        self.assertFalse(os.path.exists(os.path.join(REPO_ROOT, "pgx", "ci")))

    def test_wp25_evidence_documents_stayed_out_of_the_wp_evidence_tree(self):
        """The final pack lives in its own directory, not among WP evidence.

        ``docs/evidence/`` holds one technical note per work package. The
        WP-25 pack is a different kind of document - it describes all of
        them - and mixing it in would make the per-WP notes look like part of
        an evidence pack they are not part of.
        """
        self.assertFalse(os.path.exists(
            os.path.join(REPO_ROOT, "docs", "evidence", "ths6")))
        self.assertTrue(os.path.isdir(
            os.path.join(REPO_ROOT, "docs", "ths6", "final")))

    def test_wp21_did_not_implement_a_reveal_protocol(self):
        """WP-22 owns reveal, review storage and expert decisions."""
        for relative in _WP21_MODULES:
            with io.open(os.path.join(REPO_ROOT, *relative.split("/")), "r",
                         encoding="utf-8") as handle:
                source = handle.read()
            body = "\n".join(line for line in source.splitlines()
                             if not line.lstrip().startswith("#"))
            for node in ast.walk(ast.parse(body)):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef)):
                    with self.subTest(module=relative, name=node.name):
                        lowered = node.name.lower()
                        self.assertNotIn("reveal", lowered)
                        self.assertNotIn("review_submission", lowered)

    def test_the_gate_status_reports_wp22_started_and_no_review_done(self):
        """The pair that must not be collapsed.

        This assertion used to be ``wp22_started is False``. It started. The
        durable statement is that WP-22 beginning - and finishing - changed
        nothing about whether an expert has completed a review, which is what
        every expert metric in this document is actually waiting for.
        """
        status = read_json("data/validation/wp21-real-gate-status.json")
        self.assertTrue(status["wp22_started"])
        self.assertTrue(status["expert_review_module_implemented"])
        self.assertFalse(status["expert_review_performed"])
        # Null, not zero: no review store was inspected by this document.
        self.assertIsNone(status["completed_expert_review_count"])
        self.assertNotEqual(status["benchmark_gate_status"], "PASS")


class TestTheMetricCoreNeedsNothingExternal(unittest.TestCase):
    """No network, no database, no LLM, no browser."""

    _FORBIDDEN_ROOTS = ("requests", "httpx", "urllib3", "psycopg",
                        "sqlalchemy", "openai", "anthropic", "playwright",
                        "selenium", "socket", "http")

    def test_no_wp21_module_imports_an_external_client(self):
        for relative in _WP21_MODULES:
            with self.subTest(module=relative):
                for imported in _imports(relative):
                    root = imported.split(".")[0]
                    self.assertNotIn(root, self._FORBIDDEN_ROOTS,
                                     "%s imports %s" % (relative, imported))

    def test_the_metric_core_imports_only_stdlib_and_pgx(self):
        for relative in ("pgx/validation/metric_definitions.py",
                         "pgx/validation/metrics.py",
                         "pgx/validation/benchmark.py"):
            with self.subTest(module=relative):
                for imported in _imports(relative):
                    root = imported.split(".")[0]
                    self.assertIn(root, {"pgx", "dataclasses", "decimal",
                                         "enum", "typing", "datetime",
                                         "__future__", "re", "os", "hashlib",
                                         "io", "json"},
                                  "%s imports %s" % (relative, imported))
