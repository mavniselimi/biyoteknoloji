# -*- coding: utf-8 -*-
"""Shared paths, worlds and AST helpers for the WP-15 tests."""

from __future__ import annotations

import ast
import io
import os
import unittest
from typing import Set

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

REPORTING_DIR = os.path.join(REPO_ROOT, "pgx", "reporting")
APPLICATION_DIR = os.path.join(REPO_ROOT, "pgx", "application")

#: The engine modules WP-15 owns. None: WP-15 adds no engine module, because
#: it computes nothing. The empty tuple is the assertion.
WP15_ENGINE_MODULES = ()

#: The reporting package, enumerated rather than derived, on the same terms as
#: every earlier work package's list: a module added later is not silently
#: absorbed into WP-15's boundary checks and does not silently escape its own.
WP15_REPORTING_MODULES = (
    "__init__.py", "artifacts.py", "errors.py", "gate.py",
    "legacy_regression.py", "llm.py", "models.py", "render.py",
    "structured.py", "templates.py", "validator.py")

#: WP-15's application modules.
REPORT_APPLICATION_MODULES = ("report_cli.py", "report_gate_status.py",
                              "report_schema.py", "report_service.py")


def source(path: str) -> str:
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def tree(path: str) -> ast.Module:
    return ast.parse(source(path), filename=path)


def reporting_modules():
    """Every Python module physically present in ``pgx/reporting``.

    Read from the filesystem rather than from a list, so a new module is
    covered by the package-wide checks the moment it appears.
    """
    return [os.path.join(REPORTING_DIR, name)
            for name in sorted(os.listdir(REPORTING_DIR))
            if name.endswith(".py")]


def wp15_modules():
    """WP-15's own modules: reporting and application."""
    return (reporting_modules()
            + [os.path.join(APPLICATION_DIR, name)
               for name in REPORT_APPLICATION_MODULES])


def imports_of(path: str) -> Set[str]:
    found: Set[str] = set()
    for node in ast.walk(tree(path)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def identifiers_of(path: str) -> Set[str]:
    names: Set[str] = set()
    for node in ast.walk(tree(path)):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
    return names


class ReportingCase(unittest.TestCase):
    """One synthetic world per test class, built once.

    Building a frozen WP-11 ruleset is the expensive part, and every test in a
    class asks the same question of the same world, so it is built in
    ``setUpClass``. Tests that need a *different* world build their own.
    """

    MEDICATIONS = None
    PHENOTYPES = None
    #: Passed to the synthetic world. ``expected_extra_gene`` adds a gene to
    #: the declared scope that no rule covers, which is how a partially
    #: covered drug is expressed; a class that wants FULL coverage turns it
    #: off here.
    WORLD_KWARGS = {}

    @classmethod
    def setUpClass(cls):
        from tests.fixtures.wp15.synthetic import (MIXED_MEDICATIONS,
                                                   MIXED_PHENOTYPES,
                                                   report_world,
                                                   stored_read_model)
        cls.world = report_world(**cls.WORLD_KWARGS)
        cls.view = stored_read_model(
            cls.world,
            medications=cls.MEDICATIONS or MIXED_MEDICATIONS,
            phenotypes=cls.PHENOTYPES or MIXED_PHENOTYPES)

    @classmethod
    def tearDownClass(cls):
        cls.world.close()

    @property
    def result(self):
        from pgx.reporting.models import canonical_result_from_read_model
        return canonical_result_from_read_model(self.view)

    def report(self, locale="tr"):
        from pgx.reporting.structured import build_structured_report
        return build_structured_report(self.result, locale=locale)

    def produced(self, locale="tr", directory=None):
        from pgx.application.report_service import ReportService
        return ReportService().render_synthetic(self.view, locale=locale,
                                                directory=directory)
