# -*- coding: utf-8 -*-
"""Where WP-08 stops (WP-08).

Three boundaries. The evidence layer holds no infrastructure type; it holds no
project interpretation; and it starts none of WP-09's curation protocol,
WP-10's workflow or WP-11's rules.
"""

from __future__ import annotations

import ast
import os
import unittest

from tests.unit.evidence._support import REPO_ROOT, source

PACKAGE = os.path.join("pgx", "evidence")


def _modules():
    directory = os.path.join(REPO_ROOT, PACKAGE)
    return [os.path.join(PACKAGE, name)
            for name in sorted(os.listdir(directory))
            if name.endswith(".py")]


def _imports(relative):
    tree = ast.parse(source(relative), filename=relative)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


class TestTheEvidenceLayerDependsOnNoInfrastructure(unittest.TestCase):

    def test_no_module_imports_infrastructure_or_an_orm(self):
        for relative in _modules():
            with self.subTest(module=relative):
                for module in _imports(relative):
                    self.assertFalse(module.startswith("pgx.infrastructure"),
                                     "%s imports %s" % (relative, module))
                    self.assertNotEqual(module.split(".")[0], "sqlalchemy")
                    self.assertNotEqual(module.split(".")[0], "alembic")

    def test_no_module_imports_the_application_layer(self):
        """Dependencies point inward. The CLI knows about evidence; evidence
        must not know about the CLI, or the layering is a circle."""
        for relative in _modules():
            with self.subTest(module=relative):
                for module in _imports(relative):
                    self.assertFalse(module.startswith("pgx.application"),
                                     "%s imports %s" % (relative, module))

    def test_the_ports_module_names_no_concrete_type(self):
        for module in _imports(os.path.join(PACKAGE, "ports.py")):
            self.assertFalse(module.startswith("pgx.infrastructure"))
            self.assertNotEqual(module.split(".")[0], "sqlalchemy")

    def test_no_module_opens_a_network_connection(self):
        for relative in _modules():
            with self.subTest(module=relative):
                roots = {module.split(".")[0] for module in _imports(relative)}
                for forbidden in ("requests", "urllib", "http", "socket",
                                  "httpx", "aiohttp", "ftplib"):
                    self.assertNotIn(forbidden, roots)


class TestNoLaterWorkPackageWasStarted(unittest.TestCase):
    """WP-08 stores what sources stated. It curates, rules and assesses
    nothing, and the absence is checked by name rather than by intention."""

    #: ``pgx/curation`` is no longer here: WP-09 created it, and asserting its
    #: absence would only record that this file is older than the code it
    #: guards. The rule that assertion stood for - the evidence layer records
    #: what sources stated and knows nothing about how anyone interprets it -
    #: is checked by the dependency-direction test below, which keeps working
    #: as WP-09 grows.
    #: ``pgx/rules`` left this list for the same reason ``pgx/curation``
    #: did, one work package later: WP-11 created it. The rule it stood for -
    #: the evidence layer records what sources stated and knows nothing about
    #: any rule derived from it - is checked by the dependency-direction tests
    #: below.
    FORBIDDEN_PACKAGES = ("pgx/assessment",
                          "pgx/workflow", "pgx/api", "pgx/web")

    FORBIDDEN_NAMES = ("CuratedInterpretation", "CurationProtocol",
                       "ComputableRule", "RulesetVersion", "AssessmentFinding",
                       "RuleGenerator", "WorkflowState", "ReviewDecision")

    def test_no_later_package_exists(self):
        for relative in self.FORBIDDEN_PACKAGES:
            self.assertFalse(os.path.isdir(os.path.join(REPO_ROOT, relative)),
                             "%s exists" % relative)

    def test_no_evidence_module_imports_the_curation_layer(self):
        """WP-09 reads evidence. Evidence must not read WP-09.

        The dependency runs one way: ``pgx.curation`` cites evidence record
        identifiers, and nothing in the evidence layer may import back. A cycle
        here would mean an evidence record could be shaped by what a curator
        concluded about it, which is the separation this whole stage rests on.
        """
        for relative in _modules():
            with self.subTest(module=relative):
                for module in _imports(relative):
                    self.assertFalse(module.startswith("pgx.curation"),
                                     "%s imports %s" % (relative, module))

    def test_no_evidence_module_imports_the_rules_layer(self):
        """WP-11 cites evidence records. Evidence must not read WP-11.

        Same direction, one layer further on. An evidence record says what a
        source stated; if this layer could import ``pgx.rules``, what a source
        is recorded as having stated could be shaped by the rule that wanted to
        cite it.
        """
        for relative in _modules():
            with self.subTest(module=relative):
                for module in _imports(relative):
                    self.assertFalse(module == "pgx.rules"
                                     or module.startswith("pgx.rules."),
                                     "%s imports %s" % (relative, module))

    def test_no_evidence_module_defines_a_later_concept(self):
        for relative in _modules():
            tree = ast.parse(source(relative), filename=relative)
            defined = {node.name for node in ast.walk(tree)
                       if isinstance(node, (ast.ClassDef, ast.FunctionDef,
                                            ast.AsyncFunctionDef))}
            for name in self.FORBIDDEN_NAMES:
                with self.subTest(module=relative, name=name):
                    self.assertNotIn(name, defined)

    def test_the_draft_curation_module_creates_no_curation_type(self):
        """It is named for curation and must still define none. The one class
        it does define carries a status that says it is not one."""
        relative = os.path.join(PACKAGE, "draft_curation.py")
        tree = ast.parse(source(relative), filename=relative)
        defined = {node.name for node in ast.walk(tree)
                   if isinstance(node, ast.ClassDef)}
        self.assertNotIn("CuratedInterpretation", defined)
        self.assertIn("DraftCurationProposal", defined)


class TestThePackageExplainsItselfInIdentifiers(unittest.TestCase):

    def test_every_module_has_a_docstring(self):
        for relative in _modules():
            with self.subTest(module=relative):
                tree = ast.parse(source(relative), filename=relative)
                self.assertTrue(ast.get_docstring(tree),
                                "%s has no module docstring" % relative)

    def test_every_public_class_and_function_has_a_docstring(self):
        for relative in _modules():
            tree = ast.parse(source(relative), filename=relative)
            for node in tree.body:
                if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and \
                        not node.name.startswith("_"):
                    with self.subTest(module=relative, name=node.name):
                        self.assertTrue(ast.get_docstring(node),
                                        "%s.%s has no docstring"
                                        % (relative, node.name))
