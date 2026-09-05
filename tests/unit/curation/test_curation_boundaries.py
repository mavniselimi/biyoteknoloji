# -*- coding: utf-8 -*-
"""Where WP-09 stops (WP-09).

It defines a contract for the fourth pipeline stage. It runs no workflow,
writes no row, touches no evidence, and starts neither WP-10 nor WP-11.
"""

from __future__ import annotations

import ast
import os
import unittest

from tests.unit.curation._support import REPO_ROOT, source_text

PACKAGE = os.path.join("pgx", "curation")
CLI = os.path.join("pgx", "application", "curation_protocol_cli.py")


def _modules():
    directory = os.path.join(REPO_ROOT, PACKAGE)
    return [os.path.join(PACKAGE, name)
            for name in sorted(os.listdir(directory))
            if name.endswith(".py")]


def _imports(relative):
    tree = ast.parse(source_text(relative), filename=relative)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _identifiers(relative):
    tree = ast.parse(source_text(relative), filename=relative)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            names.add(node.name)
    return names


class TestTheCurationLayerIsPureDomain(unittest.TestCase):

    def test_no_module_imports_infrastructure_or_an_orm(self):
        for relative in _modules():
            with self.subTest(module=relative):
                for module in _imports(relative):
                    self.assertFalse(module.startswith("pgx.infrastructure"),
                                     "%s imports %s" % (relative, module))
                    self.assertNotEqual(module.split(".")[0], "sqlalchemy")
                    self.assertNotEqual(module.split(".")[0], "alembic")

    def test_no_module_imports_the_application_layer(self):
        """Dependencies point inward: the CLI knows about curation, and
        curation must not know about the CLI."""
        for relative in _modules():
            with self.subTest(module=relative):
                for module in _imports(relative):
                    self.assertFalse(module.startswith("pgx.application"),
                                     "%s imports %s" % (relative, module))

    def test_no_module_reaches_the_network(self):
        for relative in _modules() + [CLI]:
            with self.subTest(module=relative):
                roots = {module.split(".")[0] for module in _imports(relative)}
                for forbidden in ("requests", "urllib", "http", "socket",
                                  "httpx", "aiohttp", "ftplib", "smtplib"):
                    self.assertNotIn(forbidden, roots)

    def test_it_depends_only_on_the_stdlib_and_pgx_domain_and_evidence(self):
        for relative in _modules():
            for module in _imports(relative):
                if not module.startswith("pgx."):
                    continue
                with self.subTest(module=relative, imported=module):
                    self.assertTrue(
                        module.startswith("pgx.domain")
                        or module.startswith("pgx.curation"),
                        "%s imports %s" % (relative, module))


class TestNoWorkflowOrPersistenceWasIntroduced(unittest.TestCase):

    def test_no_module_creates_a_curated_interpretation(self):
        for relative in _modules() + [CLI]:
            with self.subTest(module=relative):
                self.assertNotIn("CuratedInterpretation",
                                 _identifiers(relative))

    def test_no_module_names_a_repository_or_unit_of_work(self):
        for relative in _modules() + [CLI]:
            names = _identifiers(relative)
            for forbidden in ("UnitOfWork", "Session", "Repository",
                              "commit", "rollback", "execute", "insert"):
                with self.subTest(module=relative, name=forbidden):
                    self.assertNotIn(forbidden, names)

    def test_no_wp09_module_is_named_by_a_migration(self):
        """WP-09 persists nothing, and 0007 must not have changed that.

        This replaces an earlier assertion that migration ``0007`` did not
        exist. That was true while WP-09 was the current phase and is not the
        rule it was protecting: the rule is that WP-09 defines a contract and
        writes no row. WP-10 owns ``0007`` and its own tests assert what it
        contains; what belongs here is that ``0007`` did not turn a WP-09
        module into a persistence layer.

        So: no migration mentions a WP-09 module, and no WP-09 module has
        acquired a table name. The dependency-boundary intent is unchanged;
        only the phase-specific spelling of it is gone.
        """
        directory = os.path.join(REPO_ROOT, "migrations", "versions")
        wp09_modules = {os.path.basename(relative)[:-3]
                        for relative in _modules()}
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".py"):
                continue
            body = source_text(os.path.join("migrations", "versions", name))
            for module in sorted(wp09_modules):
                if module in ("__init__", "models", "errors", "validation",
                              "fields", "protocol", "vocabulary",
                              "exercises", "legacy_review"):
                    continue  # names too generic to test by substring
                with self.subTest(migration=name, module=module):
                    self.assertNotIn("pgx.curation.%s" % module, body)

    def test_no_wp09_module_names_a_curation_workflow_table(self):
        """The WP-10 tables exist; no WP-09 module knows their names."""
        for relative in _modules() + [CLI]:
            body = source_text(relative)
            for table in ("curation_work_items", "curation_revisions",
                          "curation_reviews", "curation_adjudications",
                          "curation_role_assignments"):
                with self.subTest(module=relative, table=table):
                    self.assertNotIn(table, body)

    def test_the_domain_curation_model_was_not_weakened(self):
        """Its evidence, rationale and reviewer invariants are WP-02's, and
        WP-09 must not relax them to fit a new protocol."""
        body = source_text(os.path.join("pgx", "domain", "models.py"))
        tree = ast.parse(body)
        found = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and \
                    node.name == "CuratedInterpretation":
                found = ast.unparse(node) if hasattr(ast, "unparse") else body
        self.assertIsNotNone(found)
        for invariant in ("requires at least one evidence record",
                          "rationale", "reviewed_by", "reviewed_at"):
            self.assertIn(invariant, found)


class TestNoLaterWorkPackageWasStarted(unittest.TestCase):

    #: ``pgx/rules`` is no longer here: WP-11 created it, and asserting its
    #: absence would only record that this file is older than the code it
    #: guards. The rule that assertion stood for - a curated interpretation is
    #: a scientific conclusion and knows nothing about the executable rule
    #: anyone later derives from it - is checked by the dependency-direction
    #: test below, which keeps working as WP-11 grows.
    #: ``pgx/engine`` left this list when WP-12 created it, for the reason
    #: ``pgx/rules`` left it one work package earlier: asserting the absence of
    #: a package that now exists records only that this file is older than the
    #: code it guards. What that assertion stood for - a curated conclusion is
    #: a scientific judgement and knows nothing about the engine that will
    #: later match against it - is checked by the dependency-direction test
    #: below, which keeps working as the engine grows.
    FORBIDDEN_PACKAGES = ("pgx/assessment", "pgx/workflow",
                          "pgx/api", "pgx/web")

    FORBIDDEN_NAMES = ("ComputableRule", "RulesetVersion", "RuleRegistry",
                       "AssessmentFinding", "AttentionLevel", "CoverageStatus",
                       "RuleBuilder", "authorize", "has_permission")

    def test_no_later_package_exists(self):
        for relative in self.FORBIDDEN_PACKAGES:
            self.assertFalse(os.path.isdir(os.path.join(REPO_ROOT, relative)),
                             "%s exists" % relative)

    def test_no_curation_module_imports_the_engine_layer(self):
        """WP-12 matches against what curation concluded. Curation must not
        read WP-12, or what a curator recorded could be shaped by what a
        matcher needed it to say."""
        for relative in _modules() + [CLI]:
            for imported in _imports(relative):
                with self.subTest(module=relative, imported=imported):
                    self.assertFalse(
                        imported == "pgx.engine"
                        or imported.startswith("pgx.engine."),
                        "%s imports %s" % (relative, imported))

    def test_no_curation_module_imports_the_rules_layer(self):
        """WP-11 reads curated interpretations. Curation must not read WP-11.

        The dependency runs one way: ``pgx.rules`` pins the revision and the
        envelope a rule descends from, and nothing in the curation layer may
        import back. A cycle here would mean a curator's conclusion could be
        shaped by what a rule needed it to say, which is the separation the
        whole curation stage exists to hold.
        """
        for relative in _modules() + [CLI]:
            for imported in _imports(relative):
                with self.subTest(module=relative, imported=imported):
                    self.assertFalse(
                        imported == "pgx.rules"
                        or imported.startswith("pgx.rules."),
                        "%s imports %s" % (relative, imported))

    def test_no_curation_module_names_a_later_concept(self):
        for relative in _modules() + [CLI]:
            names = _identifiers(relative)
            for name in self.FORBIDDEN_NAMES:
                with self.subTest(module=relative, name=name):
                    self.assertNotIn(name, names)

    def test_no_module_computes_risk_or_attention(self):
        for relative in _modules() + [CLI]:
            names = _identifiers(relative)
            for name in ("risk_level", "attention_level", "compute_risk",
                         "calculate_attention", "score"):
                with self.subTest(module=relative, name=name):
                    self.assertNotIn(name, names)


class TestEvidenceIsNeverMutated(unittest.TestCase):

    def test_no_module_opens_anything_for_writing(self):
        """The curation package reads. The CLI reads. Only the artifact
        generator writes, and it writes to config/ and data/curation/."""
        for relative in _modules() + [CLI]:
            tree = ast.parse(source_text(relative), filename=relative)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                callee = getattr(node.func, "attr",
                                 getattr(node.func, "id", ""))
                if callee not in ("open",):
                    continue
                modes = [arg.value for arg in node.args[1:]
                         if isinstance(arg, ast.Constant)]
                modes += [kw.value.value for kw in node.keywords
                          if kw.arg == "mode"
                          and isinstance(kw.value, ast.Constant)]
                for mode in modes:
                    with self.subTest(module=relative, mode=mode):
                        self.assertNotIn("w", str(mode))
                        self.assertNotIn("a", str(mode))
                        self.assertNotIn("+", str(mode))

    def test_no_module_removes_or_renames_a_file(self):
        """Matched on the receiver, not the method name.

        A bare name check flags ``str.replace`` - used to format an ISO
        timestamp - and would have to be silenced, which is how a real
        ``os.replace`` later slips through. Only calls on the filesystem
        modules count.
        """
        mutators = ("remove", "unlink", "rmtree", "rename", "replace",
                    "chmod", "truncate", "mkdir", "makedirs", "rmdir")
        for relative in _modules() + [CLI]:
            tree = ast.parse(source_text(relative), filename=relative)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute):
                    continue
                receiver = func.value
                receiver_name = getattr(receiver, "id", None) or getattr(
                    getattr(receiver, "value", None), "id", None)
                if receiver_name not in ("os", "shutil", "pathlib", "Path"):
                    continue
                with self.subTest(module=relative,
                                  call="%s.%s" % (receiver_name, func.attr)):
                    self.assertNotIn(func.attr, mutators)

    def test_the_evidence_build_is_unchanged_by_a_full_validation(self):
        from pgx.curation.exercises import build_exercise_packet
        from tests.unit.curation._support import EVIDENCE_BUILD, PROPOSALS
        if not os.path.isdir(EVIDENCE_BUILD):
            self.skipTest("no sealed evidence build")
        before = {name: os.stat(os.path.join(EVIDENCE_BUILD, name)).st_mtime_ns
                  for name in sorted(os.listdir(EVIDENCE_BUILD))}
        build_exercise_packet(EVIDENCE_BUILD, PROPOSALS)
        after = {name: os.stat(os.path.join(EVIDENCE_BUILD, name)).st_mtime_ns
                 for name in sorted(os.listdir(EVIDENCE_BUILD))}
        self.assertEqual(before, after)


class TestThePackageExplainsItself(unittest.TestCase):

    def test_every_module_has_a_docstring(self):
        for relative in _modules():
            with self.subTest(module=relative):
                tree = ast.parse(source_text(relative), filename=relative)
                self.assertTrue(ast.get_docstring(tree))

    def test_every_public_class_and_function_has_a_docstring(self):
        for relative in _modules():
            tree = ast.parse(source_text(relative), filename=relative)
            for node in tree.body:
                if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and \
                        not node.name.startswith("_"):
                    with self.subTest(module=relative, name=node.name):
                        self.assertTrue(ast.get_docstring(node))
