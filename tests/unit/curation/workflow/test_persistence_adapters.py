# -*- coding: utf-8 -*-
"""The SQLAlchemy adapters, read as source (WP-10).

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
import io
import os
import unittest

from tests.unit.curation._support import REPO_ROOT

ADAPTERS = os.path.join(REPO_ROOT, "pgx", "infrastructure", "db",
                        "curation_workflow.py")
PORTS = os.path.join(REPO_ROOT, "pgx", "curation", "workflow", "ports.py")
MEMORY = os.path.join(REPO_ROOT, "pgx", "curation", "workflow", "memory.py")


def _tree(path):
    with io.open(path, encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=path)


def _classes(path):
    return {node.name: node for node in _tree(path).body
            if isinstance(node, ast.ClassDef)}


def _methods(node):
    return {child.name for child in node.body
            if isinstance(child, ast.FunctionDef)}


class TestTheGuardedUpdate(unittest.TestCase):

    def setUp(self):
        with io.open(ADAPTERS, encoding="utf-8") as handle:
            self.body = handle.read()
        self.repository = _classes(ADAPTERS)[
            "SqlAlchemyCurationWorkItemRepository"]

    def test_the_predicate_names_the_id_status_and_version(self):
        method = next(child for child in self.repository.body
                      if isinstance(child, ast.FunctionDef)
                      and child.name == "guarded_update")
        source = ast.dump(method)
        for column in ("work_item_id", "status", "version"):
            with self.subTest(column=column):
                self.assertIn(column, source)
        self.assertIn("expected_status", source)
        self.assertIn("expected_version", source)

    def test_the_version_is_incremented_by_the_database(self):
        """`version + 1` computed here would reintroduce the read-then-write
        window the guarded statement exists to close."""
        self.assertIn("CurationWorkItemORM.version + 1", self.body)

    def test_it_returns_a_row_count_and_not_a_boolean(self):
        method = next(child for child in self.repository.body
                      if isinstance(child, ast.FunctionDef)
                      and child.name == "guarded_update")
        returns = [node for node in ast.walk(method)
                   if isinstance(node, ast.Return)]
        self.assertTrue(returns)
        self.assertIn("rowcount", ast.dump(returns[-1]))

    def test_there_is_no_other_way_to_change_a_row(self):
        methods = _methods(self.repository)
        for forbidden in ("update", "set_status", "transition", "save",
                          "delete", "remove"):
            with self.subTest(method=forbidden):
                self.assertNotIn(forbidden, methods)


class TestTheAppendOnlyRepositories(unittest.TestCase):

    APPEND_ONLY = ("SqlAlchemyCurationRevisionRepository",
                   "SqlAlchemyCurationReviewRepository",
                   "SqlAlchemyCurationAdjudicationRepository",
                   "SqlAlchemyCurationProvenanceRepository",
                   "SqlAlchemyCurationAuditSink")

    def test_none_of_them_declares_a_mutation(self):
        classes = _classes(ADAPTERS)
        for name in self.APPEND_ONLY:
            with self.subTest(repository=name):
                methods = _methods(classes[name])
                for forbidden in ("update", "delete", "remove", "edit",
                                  "replace", "amend", "overwrite", "set"):
                    self.assertNotIn(forbidden, methods)

    def test_none_of_them_issues_a_delete_or_an_update_statement(self):
        classes = _classes(ADAPTERS)
        for name in self.APPEND_ONLY:
            source = ast.dump(classes[name])
            with self.subTest(repository=name):
                self.assertNotIn("'delete'", source.lower())
                self.assertNotIn("id='update'", source)


class TestTheAdapterMatchesTheReferenceImplementation(unittest.TestCase):
    """A port with two implementations that disagree is one implementation and
    one surprise."""

    PAIRS = (
        ("SqlAlchemyCurationWorkItemRepository", "_WorkItems"),
        ("SqlAlchemyCurationRevisionRepository", "_Revisions"),
        ("SqlAlchemyCurationReviewRepository", "_Reviews"),
        ("SqlAlchemyCurationAdjudicationRepository", "_Adjudications"),
        ("SqlAlchemyCurationProvenanceRepository", "_Provenance"),
        ("SqlAlchemyCurationAuditSink", "_Audit"),
    )

    def test_each_pair_offers_the_same_public_methods(self):
        sql = _classes(ADAPTERS)
        memory = _classes(MEMORY)
        for sql_name, memory_name in self.PAIRS:
            with self.subTest(port=sql_name):
                sql_methods = {name for name in _methods(sql[sql_name])
                               if not name.startswith("_")}
                memory_methods = {name for name in _methods(memory[memory_name])
                                  if not name.startswith("_")}
                self.assertEqual(sql_methods, memory_methods)

    def test_both_units_of_work_expose_the_same_repositories(self):
        """Wherever the repositories are wired up. The SQLAlchemy unit of work
        builds them in ``__enter__`` because they need a session that does not
        exist until then; the in-memory one builds them in ``__init__``
        because its store already exists. The set is what must match."""
        def attributes(path, class_name):
            node = _classes(path)[class_name]
            found = set()
            for child in node.body:
                if not isinstance(child, ast.FunctionDef):
                    continue
                if child.name not in ("__init__", "__enter__"):
                    continue
                for assign in ast.walk(child):
                    if isinstance(assign, ast.Attribute) and \
                            isinstance(assign.ctx, ast.Store) and \
                            not assign.attr.startswith("_"):
                        found.add(assign.attr)
            return found

        sql = attributes(ADAPTERS, "SqlAlchemyCurationWorkflowUnitOfWork")
        memory = attributes(MEMORY, "InMemoryWorkflowUnitOfWork")
        shared = {"work_items", "revisions", "reviews", "adjudications",
                  "provenance", "audit"}
        self.assertTrue(shared <= sql, sorted(shared - sql))
        self.assertTrue(shared <= memory, sorted(shared - memory))

    #: Each port and the class that implements it. Written out rather than
    #: matched by a name heuristic: a heuristic that guessed wrong would pass
    #: while pointing at the wrong class, which is worse than not testing.
    PORT_ADAPTERS = {
        "CurationWorkItemRepository": "SqlAlchemyCurationWorkItemRepository",
        "CurationRevisionRepository": "SqlAlchemyCurationRevisionRepository",
        "CurationReviewRepository": "SqlAlchemyCurationReviewRepository",
        "CurationAdjudicationRepository":
            "SqlAlchemyCurationAdjudicationRepository",
        "ProvenanceVerificationRepository":
            "SqlAlchemyCurationProvenanceRepository",
        "AuditSink": "SqlAlchemyCurationAuditSink",
        "CurationWorkflowUnitOfWork":
            "SqlAlchemyCurationWorkflowUnitOfWork",
    }

    def test_every_port_protocol_has_a_named_implementation(self):
        adapters = _classes(ADAPTERS)
        declared = {name for name in _classes(PORTS)
                    if name.endswith(("Repository", "Sink", "UnitOfWork"))}
        self.assertEqual(declared, set(self.PORT_ADAPTERS),
                         "a port was added or removed without an adapter")
        for port, adapter in sorted(self.PORT_ADAPTERS.items()):
            with self.subTest(port=port):
                self.assertIn(adapter, adapters)

    def test_each_adapter_implements_every_method_its_port_declares(self):
        ports = _classes(PORTS)
        adapters = _classes(ADAPTERS)
        for port, adapter in sorted(self.PORT_ADAPTERS.items()):
            declared = {name for name in _methods(ports[port])
                        if not name.startswith("_")}
            implemented = {name for name in _methods(adapters[adapter])
                           if not name.startswith("_")}
            with self.subTest(port=port):
                self.assertTrue(declared <= implemented,
                                sorted(declared - implemented))


class TestRollbackIsTheDefault(unittest.TestCase):

    def test_leaving_the_context_without_committing_rolls_back(self):
        node = _classes(ADAPTERS)["SqlAlchemyCurationWorkflowUnitOfWork"]
        exit_method = next(child for child in node.body
                           if isinstance(child, ast.FunctionDef)
                           and child.name == "__exit__")
        source = ast.dump(exit_method)
        self.assertIn("_committed", source)
        self.assertIn("rollback", source)

    def test_the_audit_sink_shares_the_unit_of_work_session(self):
        """One session, one transaction. An audit event written on a separate
        connection would survive a rollback and describe something that did
        not happen."""
        node = _classes(ADAPTERS)["SqlAlchemyCurationWorkflowUnitOfWork"]
        enter = next(child for child in node.body
                     if isinstance(child, ast.FunctionDef)
                     and child.name == "__enter__")
        source = ast.dump(enter)
        self.assertIn("SqlAlchemyCurationAuditSink", source)
        self.assertEqual(source.count("_session_factory"), 1,
                         "every repository must be given the same session")


class TestTheRoleProviderReadsTheEmptyTable(unittest.TestCase):

    def test_it_resolves_roles_from_the_assignment_table(self):
        node = _classes(ADAPTERS)["SqlAlchemyRoleProvider"]
        source = ast.dump(node)
        self.assertIn("CurationRoleAssignmentORM", source)

    def test_it_invents_no_role_when_the_table_is_empty(self):
        node = _classes(ADAPTERS)["SqlAlchemyRoleProvider"]
        source = ast.dump(node)
        self.assertIn("StaticRoleProvider", source)
        for forbidden in ("ADJUDICATOR", "SCIENTIFIC_CURATOR",
                          "INDEPENDENT_SCIENTIFIC_REVIEWER"):
            with self.subTest(role=forbidden):
                self.assertNotIn("'%s'" % forbidden, source)

    def test_it_offers_no_way_to_assign_a_role(self):
        methods = _methods(_classes(ADAPTERS)["SqlAlchemyRoleProvider"])
        for forbidden in ("assign", "grant", "add", "set_role", "elevate"):
            with self.subTest(method=forbidden):
                self.assertNotIn(forbidden, methods)


if __name__ == "__main__":
    unittest.main()
