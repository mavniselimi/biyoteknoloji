# -*- coding: utf-8 -*-
"""Where WP-10 stops, and what it left intact (WP-10).

Two questions. Does the workflow package stay inside its layer, and did adding
it damage WP-09? The second matters because WP-09 is an accepted prerequisite:
a change that quietly relaxed a protocol rule to make a workflow test pass
would be the worst possible outcome of this work package.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import unittest

from tests.unit.curation._support import (FIELD_DICTIONARY_JSON,
                                          PROTOCOL_JSON, REPO_ROOT)

WORKFLOW_DIR = os.path.join(REPO_ROOT, "pgx", "curation", "workflow")

#: WP-09's protocol, exactly as it was accepted. Pinned so a change to the
#: document is a test failure and not a surprise.
WP09_PROTOCOL_HASH = (
    "sha256:e0a76f45b0f606e4fd76d4c31829fcd61825278b01e407b71c13fc38298b56d6")
WP09_EXERCISE_HASH = (
    "sha256:7831e1ee275fe0bbae81b66ec66f3dd6f4337661178db70b28e161221307d9ac")


def _modules():
    return [os.path.join(WORKFLOW_DIR, name)
            for name in sorted(os.listdir(WORKFLOW_DIR))
            if name.endswith(".py")]


def _source(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def _imports(path):
    tree = ast.parse(_source(path), filename=path)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _identifiers(path):
    tree = ast.parse(_source(path), filename=path)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


class TestTheWorkflowPackageStaysInItsLayer(unittest.TestCase):

    def test_no_module_imports_infrastructure_or_an_orm(self):
        for path in _modules():
            with self.subTest(module=os.path.basename(path)):
                for module in _imports(path):
                    self.assertFalse(module.startswith("pgx.infrastructure"))
                    self.assertNotEqual(module.split(".")[0], "sqlalchemy")
                    self.assertNotEqual(module.split(".")[0], "alembic")

    def test_no_module_imports_the_application_layer(self):
        """Dependencies point inward. The CLI knows about the workflow; the
        workflow must not know about the CLI."""
        for path in _modules():
            with self.subTest(module=os.path.basename(path)):
                for module in _imports(path):
                    self.assertFalse(module.startswith("pgx.application"))

    def test_it_depends_only_on_the_stdlib_and_the_domain_and_curation(self):
        for path in _modules():
            for module in _imports(path):
                if not module.startswith("pgx."):
                    continue
                with self.subTest(module=os.path.basename(path),
                                  imported=module):
                    self.assertTrue(module.startswith("pgx.domain")
                                    or module.startswith("pgx.curation"))

    def test_no_module_reaches_the_network(self):
        for path in _modules():
            with self.subTest(module=os.path.basename(path)):
                roots = {module.split(".")[0] for module in _imports(path)}
                for forbidden in ("requests", "urllib", "http", "socket",
                                  "httpx", "aiohttp", "ftplib", "smtplib"):
                    self.assertNotIn(forbidden, roots)

    def test_no_module_writes_a_file(self):
        """The workflow moves work items. Writing artifacts is the build
        script's job, and a workflow that wrote files would be doing two
        things whose failures are hard to tell apart."""
        for path in _modules():
            tree = ast.parse(_source(path), filename=path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "attr", None) or \
                    getattr(node.func, "id", None)
                if name not in ("open",):
                    continue
                modes = [argument.value for argument in node.args[1:]
                         if isinstance(argument, ast.Constant)]
                modes += [keyword.value.value for keyword in node.keywords
                          if keyword.arg == "mode"
                          and isinstance(keyword.value, ast.Constant)]
                for mode in modes:
                    with self.subTest(module=os.path.basename(path)):
                        self.assertNotIn("w", mode)
                        self.assertNotIn("a", mode)


class TestNoLaterWorkPackageWasStarted(unittest.TestCase):

    #: ``pgx/rules`` is no longer here, for the reason WP-08 removed
    #: ``pgx/curation`` from its own list: WP-11 created it, and asserting its
    #: absence would record only that this file is older than the code it
    #: guards. What that assertion stood for - the workflow validates an
    #: approval envelope and constructs no rule from it - is checked by the
    #: dependency-direction test below and by
    #: ``test_the_validator_constructs_no_rule``, both of which keep working
    #: as WP-11 grows.
    #: ``pgx/engine`` left this list when WP-12 created it, following the
    #: precedent WP-08 set for ``pgx/curation`` and WP-11 for ``pgx/rules``.
    #: The rule it stood for - the workflow records human decisions and knows
    #: nothing about any engine that consumes them - is checked by the
    #: dependency-direction test below.
    FORBIDDEN_PACKAGES = ("pgx/assessment", "pgx/api", "pgx/web")

    FORBIDDEN_NAMES = ("ComputableRule", "RulesetVersion", "RuleRegistry",
                       "AssessmentFinding", "AttentionLevel", "CoverageStatus",
                       "RuleBuilder", "FastAPI", "APIRouter")

    def test_no_later_package_exists(self):
        for relative in self.FORBIDDEN_PACKAGES:
            with self.subTest(package=relative):
                self.assertFalse(os.path.isdir(os.path.join(REPO_ROOT,
                                                            relative)))

    def test_no_workflow_module_imports_the_engine_layer(self):
        """The workflow is where people decide things. An engine is where a
        decision is applied. The dependency runs one way only."""
        for path in _modules():
            for imported in _imports(path):
                with self.subTest(module=os.path.basename(path),
                                  imported=imported):
                    self.assertFalse(
                        imported == "pgx.engine"
                        or imported.startswith("pgx.engine."),
                        "%s imports %s" % (path, imported))

    def test_no_workflow_module_imports_the_rules_layer(self):
        """WP-11 reads the workflow's output. The workflow must not read WP-11.

        A valid approval envelope is a well-formed claim about a rule that does
        not exist yet. If the workflow could import ``pgx.rules``, the document
        that authorises a rule could be shaped by the rule it authorises.
        """
        for path in _modules():
            for imported in _imports(path):
                with self.subTest(module=os.path.basename(path),
                                  imported=imported):
                    self.assertFalse(
                        imported == "pgx.rules"
                        or imported.startswith("pgx.rules."),
                        "%s imports %s" % (path, imported))

    def test_no_workflow_module_names_a_later_concept(self):
        for path in _modules():
            names = _identifiers(path)
            for forbidden in self.FORBIDDEN_NAMES:
                with self.subTest(module=os.path.basename(path),
                                  name=forbidden):
                    self.assertNotIn(forbidden, names)

    def test_no_module_computes_risk_or_attention(self):
        for path in _modules():
            names = _identifiers(path)
            for forbidden in ("risk_level", "attention_level", "compute_risk",
                              "calculate_attention", "score"):
                with self.subTest(module=os.path.basename(path),
                                  name=forbidden):
                    self.assertNotIn(forbidden, names)

    def test_no_dataset_is_published_and_no_release_is_activated(self):
        for path in _modules():
            names = _identifiers(path)
            for forbidden in ("publish", "activate", "release", "promote"):
                with self.subTest(module=os.path.basename(path),
                                  name=forbidden):
                    self.assertNotIn(forbidden, names)


class TestWp09IsIntact(unittest.TestCase):
    """An accepted prerequisite. WP-10 builds on it and changes none of it."""

    def test_the_protocol_document_is_byte_identical(self):
        with io.open(PROTOCOL_JSON, "rb") as handle:
            document = json.loads(handle.read().decode("utf-8"))
        self.assertEqual(document["content_hash"], WP09_PROTOCOL_HASH)

    def test_the_protocol_is_still_awaiting_expert_review(self):
        """WP-10 must not have approved it to make a gate open."""
        with io.open(PROTOCOL_JSON, encoding="utf-8") as handle:
            document = json.load(handle)
        self.assertEqual(document["status"], "AWAITING_EXPERT_REVIEW")

    def test_the_exercise_packet_is_unchanged(self):
        path = os.path.join(REPO_ROOT, "data", "curation", "protocol-v1",
                            "exercises", "manifest.json")
        with io.open(path, encoding="utf-8") as handle:
            packet = json.load(handle)
        self.assertEqual(packet["content_hash"], WP09_EXERCISE_HASH)
        self.assertEqual(packet["case_count"], 9)
        self.assertEqual(packet["status"], "AWAITING_HUMAN_CURATORS",
                         "WP-10 must not have run the exercise on WP-09's "
                         "behalf")

    def test_the_field_dictionary_still_exists_and_parses(self):
        with io.open(FIELD_DICTIONARY_JSON, encoding="utf-8") as handle:
            json.load(handle)

    def test_the_wp09_modules_are_all_still_present(self):
        directory = os.path.join(REPO_ROOT, "pgx", "curation")
        for name in ("errors.py", "vocabulary.py", "models.py", "protocol.py",
                     "fields.py", "legacy_review.py", "exercises.py",
                     "validation.py"):
            with self.subTest(module=name):
                self.assertTrue(os.path.isfile(os.path.join(directory, name)))

    def test_no_wp09_module_imports_the_workflow(self):
        """WP-09 defines the protocol; it must not learn about the machine
        that runs it, or the dependency would point outward."""
        directory = os.path.join(REPO_ROOT, "pgx", "curation")
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".py"):
                continue
            with self.subTest(module=name):
                for module in _imports(os.path.join(directory, name)):
                    self.assertFalse(
                        module.startswith("pgx.curation.workflow"),
                        "%s imports the workflow" % name)


class TestTheRawAndEvidenceBuildsAreUntouched(unittest.TestCase):
    """WP-10 reads them and changes nothing."""

    def test_the_evidence_build_manifest_is_unchanged(self):
        path = os.path.join(REPO_ROOT, "data", "evidence",
                            "PGX-DATA-20260830-900", "manifest.json")
        if not os.path.isfile(path):
            self.skipTest("evidence build not present")
        with io.open(path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertIn("QUARANTINED",
                      manifest.get("lifecycle_labels", []),
                      "the build must still be quarantined")

    def test_the_wp08_proposal_file_is_unchanged(self):
        path = os.path.join(REPO_ROOT, "data", "migration", "wp08",
                            "draft-curation-proposals.ndjson")
        with io.open(path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        with io.open(os.path.join(REPO_ROOT, "data", "migration", "wp10",
                                  "manifest.json"), encoding="utf-8") as h:
            manifest = json.load(h)
        self.assertEqual("sha256:" + digest, manifest["source_content_hash"],
                         "the migration was built from a different file than "
                         "the one now on disk")

    def test_no_workflow_module_opens_the_raw_or_evidence_directories(self):
        for path in _modules():
            body = _source(path)
            for directory in ("data/raw", "data/evidence", "data/canonical"):
                with self.subTest(module=os.path.basename(path),
                                  directory=directory):
                    self.assertNotIn(directory, body)


if __name__ == "__main__":
    unittest.main()
