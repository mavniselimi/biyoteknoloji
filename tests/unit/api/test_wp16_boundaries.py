# -*- coding: utf-8 -*-
"""A. Dependency and layering boundaries.

The API layer may import ``pgx``. Nothing in ``pgx`` may import ``apps``. The
domain must stay free of the framework, and the framework-free half of
``apps.api`` must stay free of it too - that half is where every decision
lives, and it is only testable here because it imports nothing that cannot be
installed.

Everything is read as a syntax tree. A text search for a forbidden word would
fail on the modules whose docstrings explain what they refuse and why, which
is most of them.
"""

from __future__ import annotations

import ast
import os
import unittest

from tests.unit.api._support import (API_DIR, APPS_DIR, FORBIDDEN_IMPORTS,
                                     FRAMEWORK_BOUND_MODULES,
                                     FRAMEWORK_FREE_MODULES, REPO_ROOT,
                                     api_modules, imports_of, module_path,
                                     tree)

_FRAMEWORK_PACKAGES = ("fastapi", "starlette", "pydantic", "uvicorn")


def _pgx_modules():
    found = []
    for root, _dirs, files in os.walk(os.path.join(REPO_ROOT, "pgx")):
        if "__pycache__" in root:
            continue
        for name in sorted(files):
            if name.endswith(".py"):
                found.append(os.path.join(root, name))
    return sorted(found)


class TestLayerDirection(unittest.TestCase):
    """``apps`` depends on ``pgx``; ``pgx`` does not know ``apps`` exists."""

    def test_no_pgx_module_imports_apps(self):
        for path in _pgx_modules():
            with self.subTest(module=os.path.relpath(path, REPO_ROOT)):
                for name in imports_of(path):
                    self.assertFalse(
                        name == "apps" or name.startswith("apps."),
                        "%s imports %s; the application layer must not know "
                        "the transport exists" % (path, name))

    def test_no_pgx_module_imports_a_web_framework(self):
        for path in _pgx_modules():
            with self.subTest(module=os.path.relpath(path, REPO_ROOT)):
                for name in imports_of(path):
                    self.assertNotIn(name.split(".")[0], _FRAMEWORK_PACKAGES)

    def test_the_domain_imports_nothing_but_the_standard_library(self):
        """Re-asserted here because WP-16 is the first layer above it that
        has a framework to leak downwards."""
        domain = os.path.join(REPO_ROOT, "pgx", "domain")
        for name in sorted(os.listdir(domain)):
            if not name.endswith(".py"):
                continue
            with self.subTest(module=name):
                for imported in imports_of(os.path.join(domain, name)):
                    root = imported.split(".")[0]
                    self.assertNotIn(root, _FRAMEWORK_PACKAGES)
                    self.assertNotEqual(root, "apps")


class TestFrameworkFreeHalf(unittest.TestCase):
    """The half that decides things imports nothing that cannot be installed.

    This is what makes WP-16 testable in an environment with no package index:
    every decision - validation, error mapping, authorisation, pagination,
    readiness, serialisation - is in a module that runs here.
    """

    #: The one module allowed to touch the framework, and only inside a
    #: function body. ``runtime_verification.py`` exists to *drive* the
    #: framework and record what happened, so it obviously needs it - and it
    #: must still import on a host that has none, because the gate status
    #: reads it in order to report BLOCKED. Module scope stays clean; the
    #: imports live in the checks. The next test proves the distinction rather
    #: than trusting it.
    LAZY_FRAMEWORK_MODULES = ("runtime_verification.py",)

    def test_no_framework_free_module_imports_a_framework(self):
        for relative in FRAMEWORK_FREE_MODULES:
            if relative in self.LAZY_FRAMEWORK_MODULES:
                continue
            with self.subTest(module=relative):
                for name in imports_of(module_path(relative)):
                    self.assertNotIn(
                        name.split(".")[0], _FRAMEWORK_PACKAGES,
                        "%s imports %s, so it could not be executed in an "
                        "environment without it" % (relative, name))

    def test_the_lazy_modules_import_the_framework_only_inside_functions(self):
        """Module scope decides whether a module loads at all.

        A framework import at module scope in ``runtime_verification.py``
        would make the gate status unbuildable on exactly the hosts it most
        needs to describe: the ones with no FastAPI, where the honest answer
        is BLOCKED. So the rule is not "no framework" but "not at import".
        """
        for relative in self.LAZY_FRAMEWORK_MODULES:
            with self.subTest(module=relative):
                parsed = tree(module_path(relative))
                for node in parsed.body:
                    names = []
                    if isinstance(node, ast.Import):
                        names = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        names = [node.module]
                    for name in names:
                        self.assertNotIn(
                            name.split(".")[0], _FRAMEWORK_PACKAGES,
                            "%s imports %s at module scope" % (relative, name))

    def test_the_lazy_modules_really_do_import_without_the_framework(self):
        """Proved by importing, in a subprocess that cannot see the packages."""
        import subprocess
        import sys
        import textwrap

        program = textwrap.dedent("""
            import sys
            class Block:
                def find_module(self, name, path=None):
                    root = name.split(".")[0]
                    return self if root in %r else None
                def load_module(self, name):
                    raise ImportError(name)
            sys.meta_path.insert(0, Block())
            import apps.api.runtime_verification as module
            status = module.verified_runtime_status()
            assert status["asgi_runtime_tests_executed"] in (True, False)
            print("imported without the framework")
        """ % (tuple(_FRAMEWORK_PACKAGES),))
        result = subprocess.run([sys.executable, "-c", program],
                                cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-800:])
        self.assertIn("imported without the framework", result.stdout)

    def test_every_framework_free_module_actually_imports(self):
        import importlib
        for relative in FRAMEWORK_FREE_MODULES:
            if relative.endswith("__init__.py"):
                continue
            dotted = "apps.api." + relative[:-3].replace(os.sep, ".")
            with self.subTest(module=dotted):
                importlib.import_module(dotted)

    def test_no_framework_free_module_imports_a_router(self):
        for relative in FRAMEWORK_FREE_MODULES:
            if relative in self.LAZY_FRAMEWORK_MODULES:
                # Same exemption, same reason, and the same proof: the
                # verification module builds the real application on purpose,
                # and does it inside a check rather than at import.
                continue
            with self.subTest(module=relative):
                for name in imports_of(module_path(relative)):
                    self.assertNotIn("apps.api.routers", name)
                    self.assertNotEqual(name, "apps.api.factory")
                    self.assertNotEqual(name, "apps.api.dependencies")
                    self.assertNotEqual(name, "apps.api.contracts.models")


class TestModuleInventory(unittest.TestCase):
    """The two halves cover the package, and neither grew silently."""

    def test_every_module_is_classified(self):
        expected = set()
        for relative in FRAMEWORK_FREE_MODULES + FRAMEWORK_BOUND_MODULES:
            expected.add(os.path.join(API_DIR, relative))
        expected.add(os.path.join(APPS_DIR, "__init__.py"))
        self.assertEqual(set(api_modules()), expected)


class TestNoLegacyOrNetworkPath(unittest.TestCase):
    """No legacy module, no model provider and no outbound network call."""

    def test_no_api_module_imports_a_legacy_or_network_module(self):
        for path in api_modules():
            with self.subTest(module=os.path.relpath(path, REPO_ROOT)):
                for name in imports_of(path):
                    self.assertNotIn(name.split(".")[0], FORBIDDEN_IMPORTS)

    def test_no_api_module_names_a_legacy_symbol(self):
        forbidden = {"RISK_LABEL_TR", "calculate_risk", "generate_report",
                     "rank_alternatives", "GEMINI_API_KEY"}
        for path in api_modules():
            names = set()
            for node in ast.walk(tree(path)):
                if isinstance(node, ast.Name):
                    names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    names.add(node.attr)
            with self.subTest(module=os.path.relpath(path, REPO_ROOT)):
                self.assertEqual(names & forbidden, set())

    def test_no_api_module_reads_the_environment_outside_configuration(self):
        """Only ``config.py`` reads ``os.environ``.

        A second module reading it would be a second place a deployment is
        configured from, and the first symptom would be a setting that appears
        to have no effect.
        """
        for path in api_modules():
            relative = os.path.relpath(path, API_DIR)
            if relative == "config.py":
                continue
            names = set()
            for node in ast.walk(tree(path)):
                if isinstance(node, ast.Attribute):
                    names.add(node.attr)
            with self.subTest(module=relative):
                self.assertNotIn("environ", names)
                self.assertNotIn("getenv", names)


class TestNoScientificLogicInTheApiLayer(unittest.TestCase):
    """No API module calculates coverage, attention, rules or findings."""

    #: Engine entry points. Named as identifiers, so a module may *mention*
    #: them in a docstring explaining that it does not call them.
    CALCULATION_ENTRY_POINTS = frozenset({
        "calculate_assessment", "evaluate_coverage", "match_observation",
        "CalculationRequest", "CoverageRequest"})

    def test_no_api_module_calls_an_engine_entry_point(self):
        for path in api_modules():
            called = set()
            for node in ast.walk(tree(path)):
                if isinstance(node, ast.Call):
                    target = node.func
                    if isinstance(target, ast.Name):
                        called.add(target.id)
                    elif isinstance(target, ast.Attribute):
                        called.add(target.attr)
            with self.subTest(module=os.path.relpath(path, REPO_ROOT)):
                self.assertEqual(called & self.CALCULATION_ENTRY_POINTS, set())

    def test_no_router_imports_the_engine_or_infrastructure(self):
        routers = os.path.join(API_DIR, "routers")
        for name in sorted(os.listdir(routers)):
            if not name.endswith(".py"):
                continue
            with self.subTest(router=name):
                for imported in imports_of(os.path.join(routers, name)):
                    self.assertFalse(imported.startswith("pgx.engine"))
                    self.assertFalse(imported.startswith("pgx.rules"))
                    self.assertFalse(imported.startswith("pgx.coverage"))
                    self.assertFalse(imported.startswith("pgx.infrastructure"))

    def test_no_adapter_imports_infrastructure(self):
        adapters = os.path.join(API_DIR, "adapters")
        for name in sorted(os.listdir(adapters)):
            if not name.endswith(".py"):
                continue
            with self.subTest(adapter=name):
                for imported in imports_of(os.path.join(adapters, name)):
                    self.assertFalse(imported.startswith("pgx.infrastructure"))


class TestTheApiShipsNoUserInterface(unittest.TestCase):
    """WP-16 ships an API. The interface is a separate package.

    This class asserted the absence of ``apps/web`` until WP-17 created it -
    the same way earlier work packages' "next package does not exist" checks
    were retired when the next package arrived. What the absence stood for is
    asserted directly instead: no *API* module renders HTML, serves a
    template or mounts a static directory, whatever exists beside it.
    """

    def test_the_api_package_holds_no_templates_or_static_assets(self):
        for relative in ("templates", "static", "views"):
            with self.subTest(directory=relative):
                self.assertFalse(
                    os.path.isdir(os.path.join(API_DIR, relative)),
                    "the API package must not carry presentation assets")

    def test_no_api_module_imports_a_template_engine(self):
        for path in api_modules():
            with self.subTest(module=os.path.relpath(path, REPO_ROOT)):
                for name in imports_of(path):
                    self.assertNotIn(name.split(".")[0],
                                     ("jinja2", "markupsafe", "chameleon",
                                      "mako"))

    def test_no_api_module_imports_the_web_package(self):
        """The direction is one way: the interface consumes the API."""
        for path in api_modules():
            with self.subTest(module=os.path.relpath(path, REPO_ROOT)):
                for name in imports_of(path):
                    self.assertFalse(name.startswith("apps.web"))

    def test_no_api_module_renders_html_or_mounts_static_files(self):
        forbidden = {"HTMLResponse", "Jinja2Templates", "StaticFiles",
                     "TemplateResponse", "mount"}
        for path in api_modules():
            names = set()
            for node in ast.walk(tree(path)):
                if isinstance(node, ast.Name):
                    names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    names.add(node.attr)
                elif isinstance(node, ast.alias):
                    names.add((node.asname or node.name).split(".")[-1])
            with self.subTest(module=os.path.relpath(path, REPO_ROOT)):
                self.assertEqual(names & forbidden, set())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
