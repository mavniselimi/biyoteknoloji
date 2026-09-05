# -*- coding: utf-8 -*-
"""Layer boundaries the source-governance package must not cross.

Four rules, each with a concrete failure it prevents.

**No infrastructure, no network.** Source policy has to be answerable in CI, by
a reviewer with a checkout and nothing installed. A module here that reached for
a session or a socket would make "may we publish?" a question you needed a
database and an internet connection to ask.

**No scientific interpretation.** This package decides whether a source may be
used, never what it means. Constructing an evidence record or a rule here would
put curation inside governance.

**No approval helper.** There is no function anywhere that sets a status to
APPROVED. The only route is a review record naming a human, and a convenience
wrapper would become the route everyone used.

**Nothing from WP-06 has started.** Snapshot storage and dataset builds are the
next work package.

Every check reads the AST, so nothing needs installing.
"""

from __future__ import annotations

import ast
import io
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
PACKAGE_DIR = os.path.join(REPO_ROOT, "pgx", "scientific")

EXPECTED_MODULES = (
    "__init__.py", "conflict.py", "errors.py", "inventory.py", "models.py",
    "policy.py", "ports.py", "publication_gate.py", "validation.py",
)


def _module_paths():
    for name in sorted(os.listdir(PACKAGE_DIR)):
        if name.endswith(".py"):
            yield name, os.path.join(PACKAGE_DIR, name)


def _source(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def _imports(path):
    tree = ast.parse(_source(path), filename=path)
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _identifiers(path):
    """Every name the module actually uses, docstrings and comments excluded."""
    tree = ast.parse(_source(path), filename=path)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


class TestThePackageIsWhatWp05Specified(unittest.TestCase):

    def test_every_required_module_exists(self):
        actual = tuple(name for name, _ in _module_paths())
        self.assertEqual(actual, EXPECTED_MODULES)


class TestNoInfrastructureAndNoNetwork(unittest.TestCase):

    def test_no_module_imports_sqlalchemy_or_an_orm(self):
        for name, path in _module_paths():
            for module in _imports(path):
                with self.subTest(module=name, imported=module):
                    self.assertNotEqual(module.split(".")[0], "sqlalchemy")
                    self.assertNotEqual(module.split(".")[0], "alembic")

    def test_no_module_imports_pgx_infrastructure(self):
        for name, path in _module_paths():
            for module in _imports(path):
                with self.subTest(module=name, imported=module):
                    self.assertFalse(module.startswith("pgx.infrastructure"))

    def test_no_module_opens_a_socket_or_fetches_a_url(self):
        for name, path in _module_paths():
            for module in _imports(path):
                with self.subTest(module=name, imported=module):
                    self.assertNotIn(module.split(".")[0],
                                     ("urllib", "http", "socket", "ssl",
                                      "requests", "httpx", "ftplib", "telnetlib"))

    def test_no_module_imports_pydantic_or_a_web_framework(self):
        for name, path in _module_paths():
            for module in _imports(path):
                with self.subTest(module=name, imported=module):
                    self.assertNotIn(module.split(".")[0],
                                     ("pydantic", "fastapi", "starlette",
                                      "flask", "django"))

    def test_it_imports_only_the_standard_library_and_pgx(self):
        allowed = {"__future__", "csv", "dataclasses", "datetime", "enum",
                   "hashlib", "io", "json", "os", "types", "typing", "pgx"}
        for name, path in _module_paths():
            for module in _imports(path):
                with self.subTest(module=name, imported=module):
                    self.assertIn(module.split(".")[0], allowed, module)

    def test_it_depends_on_the_domain_and_never_the_reverse(self):
        domain_dir = os.path.join(REPO_ROOT, "pgx", "domain")
        for name in sorted(os.listdir(domain_dir)):
            if not name.endswith(".py"):
                continue
            for module in _imports(os.path.join(domain_dir, name)):
                with self.subTest(module=name, imported=module):
                    self.assertFalse(module.startswith("pgx.scientific"))

    def test_ingestion_does_not_depend_on_source_policy(self):
        """Acquisition must not be able to consult, or set, an approval."""
        ingestion = os.path.join(REPO_ROOT, "pgx", "ingestion")
        for root, _dirs, files in os.walk(ingestion):
            if "__pycache__" in root:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                for module in _imports(os.path.join(root, name)):
                    with self.subTest(module=name, imported=module):
                        self.assertFalse(module.startswith("pgx.scientific"))


class TestNoScientificInterpretationHappensHere(unittest.TestCase):

    FORBIDDEN = ("EvidenceRecord", "CuratedInterpretation", "ComputableRule",
                 "Assessment", "AssessmentFinding", "Phenotype",
                 "AttentionLevel")

    def test_no_module_constructs_a_scientific_record(self):
        for name, path in _module_paths():
            identifiers = _identifiers(path)
            for token in self.FORBIDDEN:
                with self.subTest(module=name, token=token):
                    self.assertNotIn(token, identifiers)

    def test_no_module_imports_the_domain_model_module(self):
        """The vocabulary of roles is shared; the entity types are not."""
        for name, path in _module_paths():
            with self.subTest(module=name):
                self.assertNotIn("pgx.domain.models", _imports(path))


class TestNothingCanApproveASourceInCode(unittest.TestCase):

    def test_no_module_defines_an_approval_helper(self):
        for name, path in _module_paths():
            identifiers = _identifiers(path)
            for token in ("approve_source", "approve", "grant_approval",
                          "set_approved", "mark_approved", "auto_approve"):
                with self.subTest(module=name, token=token):
                    self.assertNotIn(token, identifiers)

    def test_no_module_assigns_an_approving_status_to_anything(self):
        """The approving members appear only where they are compared against.

        ``models.py`` is exempt because it *defines* the vocabulary. Everywhere
        else, ``SourcePolicyStatus.APPROVED`` on the right of an assignment
        would be a source being approved in code.
        """
        approving = {"APPROVED", "APPROVED_WITH_RESTRICTIONS"}
        for name, path in _module_paths():
            if name == "models.py":
                continue
            tree = ast.parse(_source(path), filename=path)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                for value in ast.walk(node.value) if node.value else ():
                    if (isinstance(value, ast.Attribute)
                            and value.attr in approving):
                        self.fail("%s assigns %s" % (name, value.attr))
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if (isinstance(target, ast.Attribute)
                                and target.attr == "status"):
                            self.fail("%s assigns a status attribute" % name)

    def test_the_registry_offers_no_write_method(self):
        from pgx.scientific.policy import SourcePolicyRegistry
        for forbidden in ("save", "write", "update", "set_status", "approve",
                          "delete", "remove"):
            with self.subTest(name=forbidden):
                self.assertFalse(hasattr(SourcePolicyRegistry, forbidden))


class TestThePortsCarryNoInfrastructureTypes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = os.path.join(PACKAGE_DIR, "ports.py")
        cls.tree = ast.parse(_source(cls.path), filename=cls.path)

    def _protocols(self):
        return [node for node in self.tree.body if isinstance(node, ast.ClassDef)]

    def test_every_port_is_a_runtime_checkable_protocol(self):
        for node in self._protocols():
            with self.subTest(port=node.name):
                decorators = {getattr(d, "id", getattr(d, "attr", ""))
                              for d in node.decorator_list}
                self.assertIn("runtime_checkable", decorators)
                bases = {getattr(b, "id", getattr(b, "attr", "")) for b in node.bases}
                self.assertIn("Protocol", bases)

    def test_no_port_declares_a_generic_save(self):
        for node in self._protocols():
            methods = {item.name for item in node.body
                       if isinstance(item, ast.FunctionDef)}
            for forbidden in ("save", "store", "persist", "put"):
                with self.subTest(port=node.name, method=forbidden):
                    self.assertNotIn(forbidden, methods)

    def test_the_append_only_ports_declare_no_update_or_delete(self):
        append_only = {"SourcePolicySnapshotRepository",
                       "PublicationEvaluationRepository"}
        for node in self._protocols():
            if node.name not in append_only:
                continue
            methods = {item.name for item in node.body
                       if isinstance(item, ast.FunctionDef)}
            for forbidden in ("update", "delete", "remove", "edit", "purge"):
                with self.subTest(port=node.name, method=forbidden):
                    self.assertNotIn(forbidden, methods)

    def test_every_parameter_of_every_port_method_is_annotated(self):
        for node in self._protocols():
            for item in node.body:
                if not isinstance(item, ast.FunctionDef):
                    continue
                for argument in item.args.args:
                    if argument.arg == "self":
                        continue
                    with self.subTest(port=node.name, method=item.name,
                                      argument=argument.arg):
                        self.assertIsNotNone(argument.annotation)

    def test_no_port_mentions_a_session_or_an_orm_type(self):
        identifiers = _identifiers(self.path)
        for forbidden in ("Session", "Connection", "Engine", "Query", "Table"):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, identifiers)


class TestSourcePolicyStaysSeparateFromSnapshots(unittest.TestCase):
    """WP-05 governs sources. It does not store snapshots or build datasets.

    WP-06 has since created ``pgx/ingestion/snapshots.py``, ``scripts/dataset.py``
    and ``data/raw/``, so their absence is no longer the thing worth asserting.
    What was actually being protected is the *direction* of the dependency:
    source policy is consulted by the snapshot layer and knows nothing about it.
    That is what is checked now, along with the packages that genuinely have not
    started.
    """

    FORBIDDEN_PATHS = ("pgx/assessment", "pgx/api")

    #: WP-07 has since created ``pgx/normalization`` and WP-09
    #: ``pgx/curation``, so their absence stopped being the assertion worth
    #: making. The rule they protected - source policy is consulted by later
    #: layers and never consults them - is checked directly instead, by the
    #: test below.
    STARTED_LATER_PACKAGES = ("pgx/normalization", "pgx/curation")

    def test_no_later_work_package_package_exists(self):
        for relative in self.FORBIDDEN_PATHS:
            with self.subTest(path=relative):
                self.assertFalse(os.path.exists(os.path.join(REPO_ROOT, relative)))

    def test_no_scientific_module_imports_a_package_that_started_later(self):
        """Direction, not existence.

        ``pgx/normalization`` exists now and legitimately reads source policy
        status when it evaluates a quality gate. What must never happen is the
        reverse: a governance module that imported the canonicalization layer
        would make "may this source be used" depend on what a build produced,
        which is the wrong way round and would make the gate un-runnable
        without a build.
        """
        prefixes = tuple(relative.replace("/", ".")
                         for relative in self.STARTED_LATER_PACKAGES)
        for name, path in _module_paths():
            for module in _imports(path):
                with self.subTest(module=name, imported=module):
                    self.assertFalse(module.startswith(prefixes))

    def test_no_scientific_module_names_a_canonicalization_type(self):
        """An import is not the only way to couple two layers.

        Naming ``CanonicalEntity`` or ``EntityResolver`` here - even in a type
        comment or a string - would mean the governance layer had started
        modelling what a build contains.
        """
        for name, path in _module_paths():
            identifiers = _identifiers(path)
            for token in ("CanonicalEntity", "CanonicalBuild", "EntityResolver",
                          "DuplicateGroup", "ResolutionQueueItem",
                          "IdentityAllocation", "DataQualityReport"):
                with self.subTest(module=name, token=token):
                    self.assertNotIn(token, identifiers)

    def test_no_scientific_module_imports_the_snapshot_layer(self):
        """The gate is called by WP-06; it must not call back into it."""
        for name, path in _module_paths():
            for module in _imports(path):
                with self.subTest(module=name, imported=module):
                    self.assertFalse(module.startswith("pgx.ingestion"))

    def test_no_scientific_module_knows_where_snapshots_live(self):
        for name, path in _module_paths():
            identifiers = _identifiers(path)
            for token in ("SnapshotManager", "SnapshotManifest",
                          "RawArtifactDescriptor", "build_inventory_snapshot"):
                with self.subTest(module=name, token=token):
                    self.assertNotIn(token, identifiers)

    def test_no_scientific_module_writes_a_snapshot_or_builds_a_dataset(self):
        for name, path in _module_paths():
            identifiers = _identifiers(path)
            for token in ("build_dataset", "publish_dataset", "write_snapshot",
                          "freeze_snapshot", "SnapshotManager"):
                with self.subTest(module=name, token=token):
                    self.assertNotIn(token, identifiers)

    def test_the_gate_decides_eligibility_and_publishes_nothing(self):
        from pgx.scientific import publication_gate
        for forbidden in ("publish", "publish_dataset", "activate"):
            with self.subTest(name=forbidden):
                self.assertFalse(hasattr(publication_gate, forbidden))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
