# -*- coding: utf-8 -*-
"""What WP-20 is, and the four things it is not.

The safety package sits above every layer and can see all of them, which makes
it the easiest place in the repository to start doing somebody else's job. The
lines are drawn by reading syntax trees, so a violation fails the suite rather
than contradicting a comment.
"""

from __future__ import annotations

import ast
import io
import os
import unittest

from tests.unit.safety._support import REPO_ROOT

_PACKAGE = os.path.join(REPO_ROOT, "pgx", "safety")


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


def _module_level_imports(path):
    found = set()
    for node in _tree(path).body:
        found.update(_names(node))
    return found


def _all_imports(path):
    found = set()
    for node in ast.walk(_tree(path)):
        found.update(_names(node))
    return found


class TestTheGateNeedsNothingInstalled(unittest.TestCase):
    """It must run where nothing can be installed and nothing is reachable."""

    _FORBIDDEN = ("fastapi", "starlette", "pydantic", "uvicorn", "jinja2",
                  "sqlalchemy", "alembic", "psycopg", "httpx", "requests",
                  "playwright", "openai", "anthropic", "urllib3", "socket")

    def test_no_module_imports_a_framework_or_client_at_import_time(self):
        for name, path in _modules():
            with self.subTest(module=name):
                for imported in _module_level_imports(path):
                    root = imported.split(".")[0]
                    self.assertNotIn(
                        root, self._FORBIDDEN,
                        "%s imports %s; the safety gate must run offline with "
                        "nothing installed" % (name, imported))

    def test_nothing_connects_to_a_database_or_a_network(self):
        for name, path in _modules():
            with self.subTest(module=name):
                for imported in _all_imports(path):
                    root = imported.split(".")[0]
                    self.assertNotIn(root, ("socket", "http", "urllib",
                                            "requests", "httpx"))

    def test_no_module_imports_the_application_edge(self):
        """``pgx`` does not know ``apps`` exists."""
        for name, path in _modules():
            with self.subTest(module=name):
                for imported in _all_imports(path):
                    self.assertFalse(imported == "apps"
                                     or imported.startswith("apps."),
                                     "%s imports %s" % (name, imported))

    def test_no_module_imports_the_test_fixtures_at_import_time(self):
        """The control driver lives under ``tests`` and is loaded lazily by
        name. A shipped wheel has no ``tests``, and the gate must report
        NOT_EXECUTED there rather than failing to import."""
        for name, path in _modules():
            with self.subTest(module=name):
                for imported in _module_level_imports(path):
                    self.assertFalse(imported.startswith("tests"),
                                     "%s imports %s at import time"
                                     % (name, imported))

    def test_the_driver_is_referenced_by_name_not_by_import(self):
        from pgx.safety.report import CONTROL_DRIVER_MODULE
        self.assertEqual(CONTROL_DRIVER_MODULE, "tests.fixtures.wp20.driver")

    def test_a_missing_driver_yields_none_rather_than_raising(self):
        from pgx.safety.report import load_control_driver
        self.assertIsNone(load_control_driver("tests.fixtures.wp20.absent"))


class TestNoFixtureReachesProductionCode(unittest.TestCase):
    """The mutants are doubles. Nothing shipped may import one."""

    def _shipped_modules(self):
        for package in ("pgx", "apps"):
            base = os.path.join(REPO_ROOT, package)
            for current, directories, files in os.walk(base):
                directories[:] = [d for d in directories
                                  if d != "__pycache__"]
                for name in sorted(files):
                    if name.endswith(".py"):
                        yield os.path.join(current, name)

    def test_nothing_under_pgx_or_apps_imports_the_wp20_fixtures(self):
        for path in self._shipped_modules():
            relative = os.path.relpath(path, REPO_ROOT)
            with self.subTest(module=relative):
                for imported in _all_imports(path):
                    self.assertFalse(
                        imported.startswith("tests.fixtures.wp20"),
                        "%s imports a negative-control fixture" % relative)

    def test_no_fixture_writes_to_disk(self):
        """A mutation test that edited production source would leave the
        repository broken if it were interrupted, and would make the suite's
        result depend on the order it ran in."""
        base = os.path.join(REPO_ROOT, "tests", "fixtures", "wp20")
        for name in sorted(os.listdir(base)):
            if not name.endswith(".py"):
                continue
            path = os.path.join(base, name)
            with self.subTest(fixture=name):
                for node in ast.walk(_tree(path)):
                    if isinstance(node, ast.Call) and isinstance(
                            node.func, ast.Name) and node.func.id == "open":
                        self.fail("%s opens a file" % name)
                    if isinstance(node, ast.Attribute) and node.attr in (
                            "write_text", "unlink", "remove", "rmtree",
                            "chmod", "rename"):
                        self.fail("%s calls %s" % (name, node.attr))


class TestItDoesNotDoWp21OrWp22sJob(unittest.TestCase):

    def test_no_metrics_or_expert_review_package_lives_inside_wp20(self):
        """WP-21 and WP-22 have both built theirs. Neither is in here.

        The original assertion listed the packages as forbidden anywhere,
        which stopped being meaningful the moment they were legitimately
        built. What WP-20 actually owns is that the safety layer does not
        grow a metric engine or a review workflow of its own - it evaluates
        invariants, and an invariant that scored or reviewed anything would
        be the safety gate quietly becoming the thing it checks.
        """
        for relative in ("pgx/safety/metrics.py", "pgx/safety/benchmark.py",
                         "pgx/safety/expert_review.py",
                         "pgx/safety/review.py"):
            with self.subTest(path=relative):
                self.assertFalse(
                    os.path.exists(os.path.join(REPO_ROOT,
                                                *relative.split("/"))))

    def test_no_module_computes_a_validation_metric(self):
        forbidden = ("sensitivity", "specificity", "precision", "recall",
                     "f1_score", "concordance", "accuracy_rate",
                     "agreement_rate", "pooled")
        for name, path in _modules():
            with self.subTest(module=name):
                for node in ast.walk(_tree(path)):
                    if isinstance(node, (ast.FunctionDef,
                                         ast.AsyncFunctionDef)):
                        for word in forbidden:
                            self.assertNotIn(word, node.name.lower())

    def test_no_function_approves_or_certifies_anything(self):
        forbidden = ("approve", "sign_off", "signoff", "certify", "attest",
                     "authorise", "authorize", "validate_clinically")
        for name, path in _modules():
            with self.subTest(module=name):
                for node in ast.walk(_tree(path)):
                    if isinstance(node, (ast.FunctionDef,
                                         ast.AsyncFunctionDef)):
                        for word in forbidden:
                            self.assertNotIn(word, node.name.lower(),
                                             "%s defines %s"
                                             % (name, node.name))


class TestItDoesNotDoWp23sJob(unittest.TestCase):
    """WP-23 built the security layer. None of it lives inside WP-20.

    The original assertion listed ``pgx/security`` and ``apps/api/auth.py``
    as files that must not exist, which was the right shape while WP-23 was
    unstarted and expired the moment it shipped. What WP-20 actually owns is
    that the safety layer does not grow an authentication system or an audit
    writer of its own - a safety gate that authenticated anybody would be
    the gate quietly becoming the thing it checks.
    """

    def test_no_authentication_or_audit_writer_lives_inside_wp20(self):
        for relative in ("pgx/safety/auth.py", "pgx/safety/security.py",
                         "pgx/safety/audit.py",
                         "pgx/safety/audit_writer.py"):
            with self.subTest(path=relative):
                self.assertFalse(
                    os.path.exists(os.path.join(REPO_ROOT,
                                                *relative.split("/"))))

    def test_no_safety_module_imports_the_security_layer(self):
        """WP-20 reads WP-23's *marker files* from the tree, which is a
        string comparison. Importing its service would let the safety gate
        establish a principal, which is not a thing a gate may do."""
        import ast
        import io as _io

        directory = os.path.join(REPO_ROOT, "pgx", "safety")
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".py"):
                continue
            with _io.open(os.path.join(directory, name),
                          encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                for module in modules:
                    with self.subTest(module=name, imported=module):
                        self.assertFalse(
                            module.startswith("pgx.security.service"))
                        self.assertFalse(
                            module.startswith("pgx.infrastructure.audit"))

    def test_the_audit_half_of_inv_012_is_still_blocked(self):
        """The blocker changed owner, not existence.

        WP-23 implemented the enforcement, so the blocker naming WP-23 as the
        *implementer* is gone. What replaced it says the mechanism exists and
        no deployment is running it - which is WP-24's, and is still a
        blocker. The invariant did not become satisfied.
        """
        from pgx.safety.definitions import definitions_by_id

        blockers = definitions_by_id()["SAFETY-INV-012"].blockers
        self.assertTrue(blockers, "the audit half must stay declared")
        codes = {item.code for item in blockers}
        self.assertIn("SAFETY_AUDIT_COMPLETENESS_NOT_OPERATIONAL", codes)
        # No blocker still claims WP-23 owes an implementation.
        self.assertFalse([item for item in blockers
                          if item.owner.value == "WP-23"])


class TestItDoesNotDoWp24sJob(unittest.TestCase):
    """WP-24 has delivered. What WP-20 must not do has not changed.

    This class asserted that ``safety-gate.yml`` was the only workflow, which
    was the right shape while WP-24 was unwritten. WP-24 has since added the
    build and release pipelines, so the durable statement is the one that was
    always underneath: WP-20's file is a safety-only job, it does not build,
    deploy or release anything, and no other workflow re-implements a safety
    rule in YAML.
    """

    def test_the_wp20_workflow_is_still_safety_only(self):
        path = os.path.join(REPO_ROOT, ".github", "workflows",
                            "safety-gate.yml")
        if not os.path.isfile(path):
            return
        with io.open(path, encoding="utf-8") as handle:
            text = handle.read()
        directives = "\n".join(line for line in text.splitlines()
                                if not line.lstrip().startswith("#"))
        for forbidden in ("docker build", "docker push", "uv sync",
                          "alembic upgrade", "release-validation"):
            with self.subTest(step=forbidden):
                self.assertNotIn(forbidden, directives)

    def test_no_workflow_reimplements_a_safety_rule(self):
        """A workflow may depend on the gate. It may not decide it.

        The first version of this asked whether any workflow *mentioning*
        safety called the command, which failed on a file that only mentions
        it in a comment explaining that it depends on the gate rather than
        running it. What is durable is narrower and sharper: no workflow may
        name an invariant id, grep the gate's output, or hardcode a refusal
        code. If a rule and a job could disagree, one of them would be wrong
        and nobody would know which.
        """
        workflows = os.path.join(REPO_ROOT, ".github", "workflows")
        if not os.path.isdir(workflows):
            return
        for name in sorted(os.listdir(workflows)):
            if not name.endswith((".yml", ".yaml")):
                continue
            with io.open(os.path.join(workflows, name),
                         encoding="utf-8") as handle:
                directives = "\n".join(
                    line for line in handle.read().splitlines()
                    if not line.lstrip().startswith("#"))
            with self.subTest(workflow=name):
                self.assertNotIn("SAFETY-INV-", directives,
                                 "%s names an invariant id" % name)
                self.assertNotIn("SAFETY_", directives,
                                 "%s hardcodes a refusal code" % name)
                self.assertNotIn("grep", directives,
                                 "%s branches on gate output rather than on "
                                 "its exit code" % name)

    def test_the_gate_is_run_through_its_own_command_where_it_is_run(self):
        """WP-20's file is the one that runs it, and it does so by name."""
        path = os.path.join(REPO_ROOT, ".github", "workflows",
                            "safety-gate.yml")
        if not os.path.isfile(path):
            return
        with io.open(path, encoding="utf-8") as handle:
            self.assertIn("safety_cli check", handle.read())

    def test_the_ci_job_is_reported_configured_not_executed(self):
        from pgx.safety.gate_status import _ci_job
        facts = _ci_job(REPO_ROOT)
        self.assertFalse(facts["ci_job_executed"])


class TestWp21Started(unittest.TestCase):
    """WP-21 exists now. What WP-20 must not do about it has not changed.

    This class asserted that no WP-21 marker existed - the right shape while
    WP-20 was the newest package. WP-21 has since been built, so the
    assertion moves to its successor: WP-20 still must not compute a
    validation metric, must not read WP-21's engine, and must not report
    WP-21's existence as a validation result.

    Deleting the class when WP-21 arrived would have retired the boundary at
    the moment it started to matter.
    """

    def test_the_safety_package_computes_no_validation_metric(self):
        """A rate is a division. WP-20 performs none, and that is the point.

        A safety detector answers yes or no. The moment it starts computing
        proportions it is doing WP-21's job with WP-20's vocabulary, and a
        reader would have no way to tell which package's disclaimers apply.
        """
        import ast
        import io as _io
        package = os.path.join(REPO_ROOT, "pgx", "safety")
        for name in sorted(os.listdir(package)):
            if not name.endswith(".py"):
                continue
            with _io.open(os.path.join(package, name), "r",
                          encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.BinOp) and isinstance(
                        node.op, (ast.Div, ast.FloorDiv)):
                    self.fail("pgx/safety/%s computes a quotient at line %d"
                              % (name, node.lineno))

    def test_the_safety_package_does_not_import_the_benchmark_engine(self):
        import ast
        import io as _io
        package = os.path.join(REPO_ROOT, "pgx", "safety")
        forbidden = ("pgx.validation.benchmark", "pgx.validation.metrics",
                     "pgx.validation.metric_definitions",
                     "pgx.validation.dashboard_feed")
        for name in sorted(os.listdir(package)):
            if not name.endswith(".py"):
                continue
            with _io.open(os.path.join(package, name), "r",
                          encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    with self.subTest(module=name, imported=node.module):
                        self.assertNotIn(node.module, forbidden)

    def test_wp21_existing_is_reported_and_is_not_a_validation_result(self):
        """``validation_metrics_implemented`` is true and changes nothing."""
        import json
        path = os.path.join(REPO_ROOT, "data", "safety",
                            "wp20-real-gate-status.json")
        with open(path, "r", encoding="utf-8") as handle:
            status = json.load(handle)
        self.assertTrue(status["validation_metrics_implemented"])
        self.assertTrue(status["wp21_started"])
        self.assertFalse(status["clinical_validation_performed"])
        self.assertFalse(status["expert_review_performed"])
        self.assertNotEqual(status["safety_gate_status"], "PASS")

    def test_inv_009_still_blocks_on_zero_holdout_cases(self):
        """WP-21 closed the pooled-metric blocker and only that one.

        The separation mechanism is enforced and proven; there are still zero
        holdout cases to separate, which is scientific and no code closes it.
        """
        from pgx.safety.definitions import definitions_by_id
        definition = definitions_by_id()["SAFETY-INV-009"]
        codes = {blocker.code for blocker in definition.blockers}
        self.assertIn("SAFETY_NO_HOLDOUT_CASES_EXIST", codes)
        self.assertNotIn("SAFETY_POOLED_METRIC_CHECK_OWNED_BY_WP21", codes)


class TestWp22StartedAndChangedNothingHere(unittest.TestCase):
    """The next work package started. Measured from the tree, not asserted.

    This class was ``TestWp22WasNotStarted``. Its assertion had the shelf
    life every "the next work package has not begun" assertion has, and it
    expired. The durable statement is the one below: WP-22 exists, and the
    safety gate reports exactly what it reported before - no expert review,
    no clinical validation, no release.
    """

    def test_the_wp22_module_exists(self):
        for relative in ("pgx/expert_review/service.py",
                         "pgx/expert_review/protocol.py",
                         "docs/validation/expert-protocol.md"):
            with self.subTest(path=relative):
                self.assertTrue(
                    os.path.exists(os.path.join(REPO_ROOT,
                                                *relative.split("/"))))

    def test_the_safety_gate_still_reports_no_expert_review(self):
        """A review module existing is not a review having happened."""
        import json
        with io.open(os.path.join(REPO_ROOT, "data", "safety",
                                  "wp20-real-gate-status.json"),
                     encoding="utf-8") as handle:
            status = json.load(handle)
        self.assertTrue(status["wp22_started"])
        self.assertFalse(status["expert_review_performed"])
        self.assertFalse(status["clinical_validation_performed"])
        self.assertFalse(status["active_release_available"])
