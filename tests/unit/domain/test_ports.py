# -*- coding: utf-8 -*-
"""Repository port contracts (WP-02).

These tests read the port module's AST rather than importing infrastructure, so
they run with no database driver installed.
"""

from __future__ import annotations

import ast
import inspect
import io
import os
import unittest

from tests.unit.domain._fixtures import REPO_ROOT

from pgx.domain import ports

PORTS_PATH = os.path.join(REPO_ROOT, "pgx", "domain", "ports.py")

REQUIRED_PORTS = (
    "SourceRegistryRepository", "GeneRepository", "DrugRepository",
    "EvidenceRepository", "InterpretationRepository", "RuleRepository",
    "AssessmentRepository", "UnitOfWork",
)

#: Names that must never appear in a port signature or annotation.
FORBIDDEN_ANNOTATION_TOKENS = (
    "Session", "Engine", "Connection", "sqlalchemy", "ORM", "Query", "Row",
    "DeclarativeBase", "sessionmaker",
)


def _ports_ast() -> ast.Module:
    with io.open(PORTS_PATH, encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=PORTS_PATH)


def _annotation_names(node: ast.AST) -> set:
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            names.add(child.value)
    return names


class TestPortsExist(unittest.TestCase):

    def test_every_required_port_is_defined(self):
        for name in REQUIRED_PORTS:
            self.assertTrue(hasattr(ports, name), name)
            self.assertIn(name, ports.__all__)

    def test_ports_are_protocols(self):
        from typing import Protocol
        for name in REQUIRED_PORTS:
            port = getattr(ports, name)
            self.assertTrue(issubclass(port, Protocol), name)


class TestNoGenericSaveMethod(unittest.TestCase):
    """One port per entity: there is no ``save(anything)`` anywhere."""

    def test_no_port_declares_a_generic_save(self):
        tree = _ports_ast()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                self.assertNotEqual(node.name, "save",
                                    "a generic save() would erase the type boundary")
                self.assertNotIn(node.name, ("persist", "store", "put", "upsert"))

    def test_each_add_method_declares_exactly_one_concrete_domain_type(self):
        tree = _ports_ast()
        expected = {
            "SourceRegistryRepository": "SourceRegistryEntry",
            "GeneRepository": "Gene",
            "DrugRepository": "Drug",
            "EvidenceRepository": "EvidenceRecord",
            "InterpretationRepository": "CuratedInterpretation",
            "RuleRepository": "ComputableRule",
            "AssessmentRepository": "Assessment",
        }
        seen = {}
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node.name not in expected:
                continue
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "add":
                    argument = item.args.args[1]
                    self.assertIsNotNone(argument.annotation, node.name)
                    names = _annotation_names(argument.annotation)
                    self.assertIn(expected[node.name], names, node.name)
                    seen[node.name] = names
        self.assertEqual(sorted(seen), sorted(expected))

    def test_evidence_port_never_mentions_assessment(self):
        tree = _ports_ast()
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "EvidenceRepository":
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        for argument in item.args.args[1:]:
                            if argument.annotation is not None:
                                names = _annotation_names(argument.annotation)
                                self.assertNotIn("Assessment", names)
                                self.assertNotIn("AssessmentFinding", names)
                        if item.returns is not None:
                            names = _annotation_names(item.returns)
                            self.assertNotIn("Assessment", names)
                            self.assertNotIn("AssessmentFinding", names)
                return
        self.fail("EvidenceRepository not found")

    def test_rule_port_accepts_only_computable_rule(self):
        tree = _ports_ast()
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "RuleRepository":
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "add":
                        names = _annotation_names(item.args.args[1].annotation)
                        self.assertIn("ComputableRule", names)
                        self.assertNotIn("CuratedInterpretation", names)
                        self.assertNotIn("EvidenceRecord", names)
                return
        self.fail("RuleRepository not found")

    def test_rule_port_exposes_no_method_returning_unvalidated_rules(self):
        tree = _ports_ast()
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "RuleRepository":
                method_names = [item.name for item in node.body
                                if isinstance(item, ast.FunctionDef)]
                self.assertIn("list_validated", method_names)
                for forbidden in ("list_all", "list_executable", "list_draft"):
                    self.assertNotIn(forbidden, method_names)
                return
        self.fail("RuleRepository not found")


class TestNoInfrastructureTypesInPorts(unittest.TestCase):

    def test_no_annotation_references_an_orm_or_session_type(self):
        tree = _ports_ast()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            annotations = [argument.annotation for argument in node.args.args
                           if argument.annotation is not None]
            if node.returns is not None:
                annotations.append(node.returns)
            for annotation in annotations:
                names = _annotation_names(annotation)
                for forbidden in FORBIDDEN_ANNOTATION_TOKENS:
                    self.assertNotIn(forbidden, names,
                                     "%s annotation leaks %s" % (node.name, forbidden))

    def test_ports_module_imports_nothing_from_infrastructure(self):
        tree = _ports_ast()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                self.assertFalse(module.startswith("pgx.infrastructure"), module)
                self.assertFalse(module.startswith("sqlalchemy"), module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertFalse(alias.name.startswith("sqlalchemy"), alias.name)
                    self.assertFalse(alias.name.startswith("pgx.infrastructure"), alias.name)

    def test_unit_of_work_declares_repository_attributes_not_a_session(self):
        annotations = getattr(ports.UnitOfWork, "__annotations__", {})
        self.assertIn("evidence", annotations)
        self.assertIn("rules", annotations)
        self.assertNotIn("session", annotations)
        self.assertNotIn("engine", annotations)

    def test_unit_of_work_owns_commit_and_rollback(self):
        source = inspect.getsource(ports)
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "UnitOfWork":
                names = [item.name for item in node.body
                         if isinstance(item, ast.FunctionDef)]
                self.assertIn("commit", names)
                self.assertIn("rollback", names)
                return
        self.fail("UnitOfWork not found")

    def test_no_repository_port_declares_commit(self):
        tree = _ports_ast()
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node.name == "UnitOfWork":
                continue
            names = [item.name for item in node.body if isinstance(item, ast.FunctionDef)]
            self.assertNotIn("commit", names,
                             "%s must not control the transaction" % node.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
