# -*- coding: utf-8 -*-
"""What WP-19 is, and the four things it is not.

The verification system sits above every other layer and can see all of them,
which makes it the easiest place in the repository to accidentally start doing
somebody else's job. These tests draw the lines by reading syntax trees rather
than prose, so a violation fails the suite instead of contradicting a comment.
"""

from __future__ import annotations

import ast
import io
import json
import os
import tempfile
import unittest

from tests.unit.verification._support import REPO_ROOT

_PACKAGE = os.path.join(REPO_ROOT, "pgx", "verification")


def _committed_safety_status():
    """WP-20's own committed gate status, read the same way WP-19 reads it."""
    path = os.path.join(REPO_ROOT, "data", "safety",
                        "wp20-real-gate-status.json")
    if not os.path.exists(path):
        return "ABSENT"
    with io.open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)["safety_gate_status"]


def _modules():
    for name in sorted(os.listdir(_PACKAGE)):
        if name.endswith(".py"):
            yield name, os.path.join(_PACKAGE, name)


def _tree(path):
    with io.open(path, "r", encoding="utf-8") as handle:
        return ast.parse(handle.read())


def _names(node):
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module:
        return [node.module]
    return []


def _imports(path):
    """Every imported name anywhere in the module, from the syntax tree.

    A syntax tree rather than a text search, because half these modules
    document the imports they must not make, and a substring check would find
    its own docstring.
    """
    found = set()
    for node in ast.walk(_tree(path)):
        found.update(_names(node))
    return found


def _module_level_imports(path):
    """Only the imports that run when the module is imported.

    The distinction matters: an import inside a function that catches
    ``ImportError`` is how ``coverage_report`` asks whether coverage.py is
    installed without requiring it. An import at module level would make the
    whole verification system unimportable without it.
    """
    found = set()
    for node in _tree(path).body:
        found.update(_names(node))
    return found


class TestTheVerifierNeedsNothingInstalled(unittest.TestCase):
    """It must run where nothing can be installed, or it verifies only the
    environments that happen to be complete."""

    _FRAMEWORKS = ("fastapi", "starlette", "pydantic", "uvicorn", "jinja2",
                   "sqlalchemy", "alembic", "psycopg", "httpx", "playwright",
                   "lxml", "pytest", "coverage")

    def test_no_module_imports_a_third_party_package_at_import_time(self):
        for name, path in _modules():
            with self.subTest(module=name):
                for imported in _module_level_imports(path):
                    root = imported.split(".")[0]
                    self.assertNotIn(
                        root, self._FRAMEWORKS,
                        "%s imports %s; the verification system must run "
                        "where nothing can be installed" % (name, imported))

    def test_coverage_is_imported_inside_a_function_where_it_is_needed(self):
        """The one exception, and it is guarded: ``coverage_available``
        catches the ImportError and the caller reports BLOCKED."""
        path = os.path.join(_PACKAGE, "coverage_report.py")
        self.assertNotIn("coverage", _module_level_imports(path))
        self.assertIn("coverage", _imports(path))

    def test_every_deferred_framework_import_is_inside_a_try(self):
        """A deferred import that did not catch ImportError would turn an
        absent package into a crash rather than a BLOCKED report."""
        for name, path in _modules():
            tree = _tree(path)
            guarded = set()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Try):
                    continue
                handles_import = any(
                    isinstance(handler.type, ast.Name)
                    and handler.type.id in ("ImportError", "Exception")
                    for handler in node.handlers)
                if not handles_import:
                    continue
                for inner in ast.walk(node):
                    guarded.update(_names(inner))
            deferred = (_imports(path) - _module_level_imports(path))
            for imported in deferred:
                root = imported.split(".")[0]
                if root not in self._FRAMEWORKS:
                    continue
                with self.subTest(module=name, imported=imported):
                    self.assertIn(imported, guarded,
                                  "%s defers %s without catching ImportError"
                                  % (name, imported))

    def test_it_does_not_import_the_application_edge(self):
        """``pgx`` does not know ``apps`` exists. The verifier is in ``pgx``."""
        for name, path in _modules():
            with self.subTest(module=name):
                for imported in _imports(path):
                    self.assertFalse(imported == "apps"
                                     or imported.startswith("apps."),
                                     "%s imports %s" % (name, imported))


class TestItDoesNotDoWp20sJob(unittest.TestCase):
    """WP-20 owns the safety invariant registry and the blocking gate.

    Until WP-20 existed this class asserted that none of it had been built.
    WP-20 has since been built, so the assertion moves to its successor and
    does not weaken: WP-19 still must not *own*, *import*, *write* or
    *infer* any part of the safety gate. Deleting the class when the
    package appeared would have retired the boundary at the exact moment it
    started to matter.
    """

    def test_verification_never_imports_the_safety_package(self):
        """WP-19 reads WP-20's committed artifact. It does not link against
        the package, so a repository with the artifact and no package still
        reports a truthful state, and WP-19 cannot reach in and recompute a
        gate it does not own."""
        for name, path in _modules():
            with self.subTest(module=name):
                for imported in _imports(path):
                    self.assertFalse(
                        imported == "pgx.safety"
                        or imported.startswith("pgx.safety."),
                        "%s imports %s" % (name, imported))

    def test_it_writes_no_safety_artifact(self):
        """Every path WP-19 generates lives under its own trees."""
        from pgx.verification.artifacts import build_artifacts
        for relative in build_artifacts(REPO_ROOT):
            with self.subTest(path=relative):
                self.assertFalse(relative.startswith("data/safety/"))
                self.assertFalse(relative.startswith("schemas/wp20/"))
                self.assertNotIn("wp20", relative)

    def test_the_safety_gate_state_is_read_and_never_inferred(self):
        """An absent WP-20 artifact reports ABSENT. It never degrades to a
        satisfied state, and WP-19 never derives one from the presence of a
        package, a document or a test."""
        from pgx.verification.gate_status import _safety_gate_state
        with tempfile.TemporaryDirectory() as empty:
            absent = _safety_gate_state(empty)
        self.assertEqual(absent["safety_gate_status"], "ABSENT")
        self.assertIsNone(absent["safety_invariant_count"])
        self.assertIsNone(absent["safety_negative_control_count"])
        self.assertEqual(
            _safety_gate_state(REPO_ROOT)["safety_gate_status"],
            _committed_safety_status())

    def test_the_safety_map_is_a_map_and_declares_itself_one(self):
        from pgx.verification.requirements import SAFETY_MAP_DISCLAIMER
        self.assertIn("not an assertion that the invariants hold",
                      SAFETY_MAP_DISCLAIMER)
        self.assertIn("WP-20 owns", SAFETY_MAP_DISCLAIMER)

    def test_no_module_defines_a_safety_invariant_registry(self):
        """A map from an existing test to an invariant is a lookup table. A
        registry that decides whether an invariant *holds* is WP-20's."""
        for name, path in _modules():
            with self.subTest(module=name):
                for node in ast.walk(_tree(path)):
                    if isinstance(node, ast.ClassDef):
                        self.assertNotIn("SafetyInvariant", node.name)
                        self.assertNotIn("InvariantRegistry", node.name)

    def test_the_gate_status_records_the_boundary_as_a_blocker(self):
        """The blocker was replaced, not deleted. "WP-20 does not exist" was
        true once; "the safety gate is not passing" is its truthful
        successor, and it keeps blocking for as long as it is true."""
        from pgx.verification.gate_status import BLOCKER_CODES
        self.assertIn("VERIFICATION_SAFETY_GATE_NOT_PASSING", BLOCKER_CODES)
        self.assertNotIn("VERIFICATION_SAFETY_GATE_OWNED_BY_WP20",
                         BLOCKER_CODES)


class TestItDoesNotDoWp21OrWp22sJob(unittest.TestCase):
    """A metric is WP-21's, a review workflow is WP-22's, and neither is here.

    The assertion below used to be that those packages did not exist at all.
    Both have since been built, and the check was defending the wrong thing:
    WP-19 verifies software, and what must remain true is that **it does not
    contain** a metric engine or a review workflow of its own. A verification
    layer that computed an agreement rate would be reporting a scientific
    result under the heading "the tests passed".
    """

    def test_no_metrics_or_review_module_lives_inside_wp19(self):
        for relative in ("pgx/verification/metrics.py",
                         "pgx/verification/benchmark.py",
                         "pgx/verification/expert_review.py",
                         "pgx/verification/review.py"):
            with self.subTest(path=relative):
                self.assertFalse(
                    os.path.exists(os.path.join(REPO_ROOT,
                                                *relative.split("/"))))

    def test_wp19_imports_no_wp22_record_type(self):
        """WP-19 may name WP-22's test modules; it may not read its records.

        The inventory categorises ``tests.unit.expert_review`` by module name,
        which is a string. Importing ``CompletionDecision`` would let a
        verification module open a review and describe what it found, and the
        first thing built on that would be a coverage figure over expert
        opinions.
        """
        forbidden = ("pgx.expert_review.models", "pgx.expert_review.service",
                     "pgx.expert_review.audit")
        for name, path in _modules():
            with io.open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                module = None
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                elif isinstance(node, ast.Import):
                    module = ",".join(alias.name for alias in node.names)
                if module:
                    with self.subTest(module=name, imported=module):
                        for item in forbidden:
                            self.assertNotIn(item, module)

    def test_no_module_computes_a_validation_metric(self):
        forbidden = ("sensitivity", "specificity", "precision", "recall",
                     "f1_score", "concordance", "accuracy_rate",
                     "agreement_rate")
        for name, path in _modules():
            with self.subTest(module=name):
                for node in ast.walk(_tree(path)):
                    if isinstance(node, (ast.FunctionDef,
                                         ast.AsyncFunctionDef)):
                        for word in forbidden:
                            self.assertNotIn(word, node.name.lower())

    def test_nothing_here_creates_or_reads_a_validation_case(self):
        """WP-18 owns the partition. WP-19 maps its tests and touches nothing
        inside it."""
        for name, path in _modules():
            with self.subTest(module=name):
                for imported in _imports(path):
                    self.assertFalse(
                        imported.startswith("pgx.validation"),
                        "%s imports %s" % (name, imported))


class TestItClaimsNoScientificOrHumanApproval(unittest.TestCase):

    def test_no_function_approves_anything(self):
        forbidden = ("approve", "sign_off", "signoff", "certify", "attest",
                     "validate_scientifically", "authorise", "authorize")
        for name, path in _modules():
            with self.subTest(module=name):
                for node in ast.walk(_tree(path)):
                    if isinstance(node, (ast.FunctionDef,
                                         ast.AsyncFunctionDef)):
                        for word in forbidden:
                            self.assertNotIn(
                                word, node.name.lower(),
                                "%s defines %s" % (name, node.name))

    def test_the_gate_status_pins_scientific_validation_to_false(self):
        from pgx.application.verification_schema import (
            GATE_STATUS_SCHEMA_PATH, build_schemas)
        schema = build_schemas()[GATE_STATUS_SCHEMA_PATH]
        self.assertEqual(
            schema["properties"]["scientific_validation_performed"],
            {"const": False})

    def test_the_cli_help_says_what_it_does_not_do(self):
        from pgx.application import verification_cli
        text = verification_cli.__doc__ or ""
        self.assertIn("verification", text.lower())
        parser = verification_cli._parser()
        self.assertIn("no scientific validation", parser.description.lower())

    def test_no_subcommand_could_approve_a_release(self):
        from pgx.application import verification_cli
        parser = verification_cli._parser()
        actions = [action for action in parser._actions
                   if hasattr(action, "choices") and action.choices
                   and isinstance(action.choices, dict)]
        names = set()
        for action in actions:
            names.update(action.choices)
        self.assertTrue(names)
        for forbidden in ("approve", "sign", "certify", "release", "validate"):
            for name in names:
                with self.subTest(command=name, forbidden=forbidden):
                    self.assertNotIn(forbidden, name)


class TestTheExistingContractsAreIntact(unittest.TestCase):
    """WP-19 changed as little as it could. This says what, and no more."""

    def test_the_console_script_is_declared(self):
        import io as _io
        with _io.open(os.path.join(REPO_ROOT, "pyproject.toml"), "r",
                      encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("pgx-verify = "
                      '"pgx.application.verification_cli:main"', text)

    def test_no_application_or_scientific_module_was_touched(self):
        """WP-19 verifies. It does not change what is verified.

        Asserted by the WP-16 runtime evidence still being about the same
        ``apps/api`` source: if this package had edited the API, that digest
        would have moved and the evidence would read STALE for a reason that
        had nothing to do with a runtime change.
        """
        from apps.api.runtime_verification import input_fingerprints
        current = input_fingerprints(REPO_ROOT)
        self.assertTrue(current["api_source_sha256"])
        self.assertEqual(current["openapi_document_sha256"],
                         current["committed_openapi_sha256"])
