# -*- coding: utf-8 -*-
"""Where WP-11 stops, and what it left intact.

Two questions, the same two every work package in this repository has asked.
Does the rules package stay inside its layer, and did adding it damage what
came before? The second matters most: WP-08, WP-09 and WP-10 are accepted
prerequisites, and a change that quietly relaxed one of their rules to make a
WP-11 test pass would be the worst possible outcome of this work.

WP-11 also has a boundary in front of it. It says what may be executed; it
executes nothing. Phenotype matching, patient assessment, phenoconversion,
drug-interaction adjustment and dose reasoning all belong to WP-12 and later,
and none of them may appear here - not as a module, not as a function, not as
a field somebody could fill in.
"""

from __future__ import annotations

import ast
import os
import unittest

from tests.unit.rules._support import (APPLICATION_DIR, REPO_ROOT, RULES_DIR,
                                       RULE_APPLICATION_MODULES,
                                       identifiers_of, imports_of,
                                       rules_modules, source, tree)

WP11_APPLICATION_PATHS = [os.path.join(APPLICATION_DIR, name)
                          for name in RULE_APPLICATION_MODULES]

#: WP-09's protocol and WP-10's envelope contract, pinned by hash. A change to
#: either is a test failure here rather than a surprise later.
WP09_PROTOCOL_HASH = (
    "sha256:e0a76f45b0f606e4fd76d4c31829fcd61825278b01e407b71c13fc38298b56d6")


class TestTheRulesPackageStaysInItsLayer(unittest.TestCase):

    def test_it_imports_no_infrastructure_and_no_framework(self):
        for path in rules_modules() + WP11_APPLICATION_PATHS:
            imported = imports_of(path)
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("sqlalchemy", "alembic", "fastapi",
                                  "flask", "django", "pydantic"):
                    self.assertNotIn(forbidden, imported)

    def test_the_domain_package_imports_no_application_module(self):
        for path in rules_modules():
            imported = imports_of(path)
            with self.subTest(module=os.path.basename(path)):
                for name in imported:
                    self.assertFalse(name.startswith("pgx.application"))

    def test_it_depends_only_on_layers_beneath_it(self):
        """``pgx.domain``, ``pgx.curation`` and ``pgx.normalization`` are all
        below the rules layer: a rule pins a curated revision and names a
        canonical entity, so depending on both is the direction the pipeline
        already runs."""
        allowed = ("pgx.domain", "pgx.curation", "pgx.normalization",
                   "pgx.rules")
        for path in rules_modules():
            for name in imports_of(path):
                if not name.startswith("pgx."):
                    continue
                with self.subTest(module=os.path.basename(path),
                                  imported=name):
                    self.assertTrue(
                        any(name == prefix or name.startswith(prefix + ".")
                            for prefix in allowed),
                        "%s imports %s" % (path, name))


class TestWp12AndLaterWereNotStarted(unittest.TestCase):

    #: ``pgx/engine`` left this list when WP-12 created it. WP-11 says what
    #: may be executed; WP-12 executes phenotype equality against it. The rule
    #: this assertion stood for - the rules layer defines conditions and never
    #: evaluates one against an input - is checked by the dependency-direction
    #: test below, and by WP-12's own boundary tests asserting that its matcher
    #: never reads a rule's outcome.
    FORBIDDEN_PACKAGES = ("pgx/assessment", "pgx/api",
                          "pgx/web")

    #: Concepts that belong to WP-12 and later. Checked as identifiers rather
    #: than as prose so a rename cannot smuggle one in.
    FORBIDDEN_NAMES = ("AssessmentFinding", "PatientAssessment", "Patient",
                       "Phenoconversion", "phenoconvert", "DrugInteraction",
                       "adjust_dose", "recommend", "recommendation",
                       "CoverageStatus", "diagnose", "prescribe",
                       "match_phenotype", "evaluate_rule", "apply_rules")

    def test_no_later_package_exists(self):
        for relative in self.FORBIDDEN_PACKAGES:
            with self.subTest(package=relative):
                self.assertFalse(
                    os.path.isdir(os.path.join(REPO_ROOT, relative)),
                    "%s exists" % relative)

    def test_no_rules_module_imports_the_engine_layer(self):
        """WP-12 consumes WP-11's conditions. WP-11 must not consume WP-12,
        or a condition's meaning could depend on how something matched it."""
        for path in rules_modules() + WP11_APPLICATION_PATHS:
            for imported in imports_of(path):
                with self.subTest(module=os.path.basename(path),
                                  imported=imported):
                    self.assertFalse(
                        imported == "pgx.engine"
                        or imported.startswith("pgx.engine."),
                        "%s imports %s" % (path, imported))

    def test_no_rules_module_names_a_later_concept(self):
        for path in rules_modules() + WP11_APPLICATION_PATHS:
            names = identifiers_of(path)
            for forbidden in self.FORBIDDEN_NAMES:
                with self.subTest(module=os.path.basename(path),
                                  name=forbidden):
                    self.assertNotIn(forbidden, names)

    def test_nothing_here_evaluates_a_rule_against_anything(self):
        """WP-11 says what a rule denotes. Deciding whether a *person* matches
        one is WP-12, and there is deliberately no function here that takes a
        phenotype and returns an outcome."""
        for path in rules_modules():
            for node in ast.walk(tree(path)):
                if not isinstance(node, ast.FunctionDef):
                    continue
                arguments = {argument.arg for argument in node.args.args}
                with self.subTest(module=os.path.basename(path),
                                  function=node.name):
                    for patient_field in ("patient", "patient_id", "subject",
                                          "genotype", "diplotype", "sample"):
                        self.assertNotIn(patient_field, arguments)

    def test_no_module_reads_a_patient_or_ehr_field(self):
        for path in rules_modules() + WP11_APPLICATION_PATHS:
            text = source(path).lower()
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("ehr", "fhir", "hl7", "mrn", "patient_id"):
                    self.assertNotIn(forbidden, text)


class TestTheEarlierWorkPackagesAreIntact(unittest.TestCase):

    def test_the_wp09_protocol_document_is_unchanged(self):
        import io
        import json
        path = os.path.join(REPO_ROOT, "config", "curation",
                            "protocol-v1.json")
        with io.open(path, encoding="utf-8") as handle:
            document = json.load(handle)
        self.assertEqual(document["content_hash"], WP09_PROTOCOL_HASH)

    def test_the_protocol_is_still_awaiting_expert_review(self):
        """WP-11 must not have approved it to open a gate. If this ever
        changes, it should change because an expert read it."""
        import io
        import json
        path = os.path.join(REPO_ROOT, "config", "curation",
                            "protocol-v1.json")
        with io.open(path, encoding="utf-8") as handle:
            document = json.load(handle)
        self.assertEqual(document["status"], "AWAITING_EXPERT_REVIEW")

    def test_the_evidence_build_is_still_quarantined(self):
        """The same, one layer up: WP-11 must not have re-labelled the
        evidence build to make a rule eligible."""
        import io
        import json
        path = os.path.join(REPO_ROOT, "data", "evidence",
                            "PGX-DATA-20260830-900", "manifest.json")
        with io.open(path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertIn("QUARANTINED", manifest["lifecycle_labels"])
        self.assertIn("NOT_EXECUTABLE", manifest["lifecycle_labels"])
        self.assertFalse(manifest["production_eligible"])
        self.assertEqual(manifest["dataset_lifecycle_state"], "BUILDING")

    def test_the_curation_layer_does_not_import_the_rules_layer(self):
        curation = os.path.join(REPO_ROOT, "pgx", "curation")
        for root, dirs, files in os.walk(curation):
            dirs[:] = [name for name in dirs if name != "__pycache__"]
            for name in sorted(files):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                with self.subTest(module=os.path.relpath(path, REPO_ROOT)):
                    for imported in imports_of(path):
                        self.assertFalse(
                            imported == "pgx.rules"
                            or imported.startswith("pgx.rules."))

    def test_the_evidence_layer_does_not_import_the_rules_layer(self):
        evidence = os.path.join(REPO_ROOT, "pgx", "evidence")
        for name in sorted(os.listdir(evidence)):
            if not name.endswith(".py"):
                continue
            with self.subTest(module=name):
                for imported in imports_of(os.path.join(evidence, name)):
                    self.assertFalse(imported == "pgx.rules"
                                     or imported.startswith("pgx.rules."))

    def test_the_release_registry_does_not_import_the_rules_layer(self):
        for name in ("release_service.py", "release_cli.py",
                     "release_schema.py"):
            with self.subTest(module=name):
                for imported in imports_of(os.path.join(APPLICATION_DIR,
                                                        name)):
                    self.assertFalse(imported.startswith("pgx.rules"))


class TestNothingHereApprovesAnything(unittest.TestCase):

    def test_no_module_constructs_an_approval_or_a_signature(self):
        """WP-10 validates an approval envelope; WP-23 will authenticate the
        people it names. WP-11 may read one and may never write one."""
        for path in rules_modules() + WP11_APPLICATION_PATHS:
            names = identifiers_of(path)
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("ReviewSignature", "sign", "issue_approval",
                                  "grant_role", "assign_role",
                                  "create_envelope", "make_approval"):
                    self.assertNotIn(forbidden, names)

    def test_no_module_writes_into_the_curation_store(self):
        for path in rules_modules() + WP11_APPLICATION_PATHS:
            names = identifiers_of(path)
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("CurationWorkflowService", "submit",
                                  "review", "adjudicate"):
                    self.assertNotIn(forbidden, names)

    def test_the_role_provider_is_injected_never_constructed_with_roles(self):
        for name in ("rule_service.py", "ruleset_service.py"):
            text = source(os.path.join(APPLICATION_DIR, name))
            with self.subTest(module=name):
                self.assertIn("role_provider", text)
                self.assertNotIn("StaticRoleProvider({", text)


if __name__ == "__main__":
    unittest.main()
