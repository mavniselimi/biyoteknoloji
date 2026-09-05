# -*- coding: utf-8 -*-
"""The SQLAlchemy adapters, read as source (WP-11).

SQLAlchemy cannot be installed in this environment, so these classes cannot be
imported here. What can be checked is their shape: that the guarded update is
one statement with the three-part predicate, that the append-only repositories
declare no mutation, and that they implement the same port surface the
in-memory reference implementation does.

The in-memory implementation is not a stand-in for these classes. It is the
reference: every rule the SQLAlchemy adapter delegates to PostgreSQL is
enforced in Python there, so the two can be compared. This file is what
compares their surfaces.
"""

from __future__ import annotations

import ast
import os
import unittest

from tests.unit.rules._support import REPO_ROOT, RULES_DIR, source, tree

ADAPTERS = os.path.join(REPO_ROOT, "pgx", "infrastructure", "db", "rules.py")
PORTS = os.path.join(RULES_DIR, "ports.py")
MEMORY = os.path.join(RULES_DIR, "memory.py")


def _classes(path):
    return {node.name: node for node in tree(path).body
            if isinstance(node, ast.ClassDef)}


def _methods(node):
    return {child.name for child in node.body
            if isinstance(child, ast.FunctionDef)}


def _public(names):
    return {name for name in names if not name.startswith("_")}


class TestTheAdaptersImplementThePorts(unittest.TestCase):

    PAIRS = (("RuleRepository", "SqlAlchemyRuleRepository"),
             ("RulesetRepository", "SqlAlchemyRulesetRepository"),
             ("RuleAuditSink", "SqlAlchemyRuleAuditSink"),
             ("RuleWorkflowUnitOfWork", "SqlAlchemyRuleWorkflowUnitOfWork"))

    @classmethod
    def setUpClass(cls):
        cls.ports = _classes(PORTS)
        cls.adapters = _classes(ADAPTERS)

    def test_every_port_has_an_adapter(self):
        for port, adapter in self.PAIRS:
            with self.subTest(port=port):
                self.assertIn(port, self.ports)
                self.assertIn(adapter, self.adapters)

    def test_every_port_method_is_implemented(self):
        for port, adapter in self.PAIRS:
            required = _public(_methods(self.ports[port]))
            provided = _public(_methods(self.adapters[adapter]))
            with self.subTest(port=port):
                self.assertEqual(required - provided, set())

    def test_the_in_memory_reference_implements_the_same_ports(self):
        memory = _classes(MEMORY)
        rules = _public(_methods(memory["_Rules"]))
        rulesets = _public(_methods(memory["_Rulesets"]))
        self.assertEqual(
            _public(_methods(self.ports["RuleRepository"])) - rules, set())
        self.assertEqual(
            _public(_methods(self.ports["RulesetRepository"])) - rulesets,
            set())


class TestTheUpdateIsGuardedAndSingleStatement(unittest.TestCase):
    """A read-then-write would let two sessions each read version 3 and both
    write version 4. The guard is in the ``WHERE`` clause, so the database
    decides and the affected-row count reports who lost."""

    @classmethod
    def setUpClass(cls):
        cls.text = source(ADAPTERS)

    def test_the_guarded_update_predicates_on_id_status_and_version(self):
        for fragment in ("expected_status", "expected_version"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.text)

    def test_it_returns_an_affected_row_count(self):
        self.assertIn("rowcount", self.text)

    def test_the_lifecycle_version_is_advanced_by_the_statement(self):
        self.assertIn("lifecycle_version", self.text)

    def test_no_adapter_reads_then_writes_a_status(self):
        """A ``get`` followed by a ``status =`` assignment in one method would
        be the read-then-write this design exists to avoid."""
        adapters = _classes(ADAPTERS)
        for name, node in adapters.items():
            for method in node.body:
                if not isinstance(method, ast.FunctionDef):
                    continue
                if method.name != "guarded_status_update":
                    continue
                body = ast.unparse(method)
                with self.subTest(adapter=name):
                    self.assertIn("update(", body)
                    self.assertNotIn(".first()", body)


class TestTheAppendOnlyRepositoriesDeclareNoMutation(unittest.TestCase):

    FORBIDDEN = ("update", "delete", "remove", "edit", "set_", "patch",
                 "overwrite", "purge")

    def test_no_adapter_declares_a_general_mutation_method(self):
        for name, node in _classes(ADAPTERS).items():
            for method in _public(_methods(node)):
                with self.subTest(adapter=name, method=method):
                    for forbidden in self.FORBIDDEN:
                        if method == "guarded_status_update":
                            continue
                        if method in ("remove_member",):
                            continue
                        self.assertFalse(
                            method.startswith(forbidden),
                            "%s.%s looks like unguarded mutation"
                            % (name, method))

    def test_the_audit_sink_only_records(self):
        sink = _classes(ADAPTERS)["SqlAlchemyRuleAuditSink"]
        self.assertEqual(_public(_methods(sink)), {"record"})

    def test_no_adapter_issues_a_raw_delete_of_a_rule_or_ruleset(self):
        text = source(ADAPTERS)
        for fragment in ("DELETE FROM computable_rules",
                         "DELETE FROM ruleset_versions",
                         "delete(ComputableRuleORM)",
                         "delete(RulesetVersionORM)"):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, text)


class TestTheAdaptersStayInTheirLayer(unittest.TestCase):

    def test_the_domain_package_imports_no_infrastructure(self):
        from tests.unit.rules._support import imports_of, rules_modules
        for path in rules_modules():
            imported = imports_of(path)
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("sqlalchemy", "pgx.infrastructure",
                                  "alembic", "psycopg2"):
                    self.assertNotIn(forbidden, imported)

    def test_the_domain_package_needs_no_network(self):
        from tests.unit.rules._support import imports_of, rules_modules
        for path in rules_modules():
            roots = {name.split(".")[0] for name in imports_of(path)}
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("requests", "httpx", "urllib", "socket",
                                  "aiohttp", "ftplib"):
                    self.assertNotIn(forbidden, roots)

    #: Modules allowed to touch a filesystem, and why each one is.
    #: ``builder.py`` is here for one line - deriving the artifact's directory
    #: name - and reads nothing; publication itself is delegated to
    #: ``serialization``. Everything else in the package works on values, which
    #: is what makes it testable without a disk.
    FILESYSTEM_MODULES = ("builder.py", "legacy.py", "registry.py",
                          "serialization.py")

    def test_only_these_modules_touch_the_filesystem(self):
        from tests.unit.rules._support import imports_of, rules_modules
        touching = set()
        for path in rules_modules():
            if {"os", "os.path", "io", "shutil", "tempfile"} & imports_of(path):
                touching.add(os.path.basename(path))
        self.assertEqual(sorted(touching), list(self.FILESYSTEM_MODULES))

    def test_the_builder_records_no_machine_dependent_path(self):
        """``os.path.relpath`` would resolve against the working directory, so
        the same build run from two places would record two paths. Checked as
        *calls* rather than as text: the module names the function in a
        comment saying why it is not used, and that comment should survive."""
        from tests.unit.rules._support import tree as parse
        called = set()
        for node in ast.walk(parse(os.path.join(RULES_DIR, "builder.py"))):
            if isinstance(node, ast.Call):
                called.add(ast.unparse(node.func))
        for forbidden in ("os.path.relpath", "os.path.abspath", "os.getcwd"):
            with self.subTest(call=forbidden):
                self.assertNotIn(forbidden, called)


if __name__ == "__main__":
    unittest.main()
