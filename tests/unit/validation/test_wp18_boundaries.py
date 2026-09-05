# -*- coding: utf-8 -*-
"""What WP-18 may not import, compute or become (WP-18).

Read as syntax trees, never as prose. Every module in this package talks about
metrics, holdout answers and patient data in order to refuse them, so a text
search would fail on the docstrings that explain the refusals.
"""

from __future__ import annotations

import ast
import io
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
PACKAGE = os.path.join(REPO_ROOT, "pgx", "validation")


#: The modules WP-18 owns. Named explicitly rather than "everything under
#: pgx/validation", because WP-21 later put the metric engine in this package -
#: it depends on the partition it must not violate, so it belongs beside it.
#: Walking the directory would make these boundary tests fail the moment WP-21
#: did its job, which would say nothing about WP-18.
WP18_MODULES = (
    "__init__.py", "access.py", "cases.py", "catalog.py", "compatibility.py",
    "errors.py", "fingerprint.py", "gate_status.py", "manifests.py",
    "restricted_import.py", "separation.py", "vocabulary.py",
)

#: WP-21's modules, listed so a new file in this package is classified
#: deliberately rather than silently exempted by either list.
WP21_MODULES = (
    "benchmark.py", "benchmark_artifacts.py", "benchmark_gate_status.py",
    "benchmark_models.py", "benchmark_report.py", "dashboard_feed.py",
    "metric_definitions.py", "metrics.py",
)


def _all_module_names():
    return tuple(sorted(name for name in os.listdir(PACKAGE)
                        if name.endswith(".py")))


def _modules(names=None):
    """WP-18's own modules by default."""
    return [os.path.join(PACKAGE, name) for name in (names or WP18_MODULES)]


def _tree(path):
    with io.open(path, encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=path)


def _imports(path):
    found = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


class TestTheLayerIsFrameworkFree(unittest.TestCase):
    """Standard library and ``pgx`` only. No web, no ORM, no network."""

    FORBIDDEN_ROOTS = ("fastapi", "starlette", "pydantic", "uvicorn", "httpx",
                       "requests", "urllib3", "sqlalchemy", "alembic",
                       "psycopg", "jinja2", "flask", "django", "openai",
                       "anthropic", "google", "transformers", "torch")

    def test_no_module_imports_a_framework_or_a_client(self):
        for path in _modules():
            relative = os.path.relpath(path, REPO_ROOT)
            for name in _imports(path):
                with self.subTest(module=relative, imported=name):
                    self.assertNotIn(name.split(".")[0], self.FORBIDDEN_ROOTS)

    def test_no_module_imports_apps(self):
        """``apps`` may import ``pgx``; the reverse would invert the layers."""
        for path in _modules():
            relative = os.path.relpath(path, REPO_ROOT)
            for name in _imports(path):
                with self.subTest(module=relative, imported=name):
                    self.assertNotEqual(name.split(".")[0], "apps")

    def test_no_module_opens_a_socket(self):
        for path in _modules():
            relative = os.path.relpath(path, REPO_ROOT)
            for name in _imports(path):
                with self.subTest(module=relative, imported=name):
                    self.assertNotIn(name.split(".")[0],
                                     ("socket", "http", "ftplib", "smtplib",
                                      "telnetlib", "asyncio"))

    def test_every_module_imports_in_a_bare_interpreter(self):
        import importlib

        for path in _modules():
            name = os.path.relpath(path, REPO_ROOT)[:-3].replace(os.sep, ".")
            if name.endswith(".__init__"):
                name = name[:-len(".__init__")]
            with self.subTest(module=name):
                importlib.import_module(name)


class TestNoMetricIsComputedHere(unittest.TestCase):
    """WP-18's own modules compute no metric. WP-21's do, and should.

    Before WP-21 this ranged over every file under ``pgx/validation`` and
    asserted that none of them named a numerator or performed a division.
    WP-21 then put the metric engine in this package - deliberately, because
    a metric that may not pool roles has to sit next to the code that defines
    the roles - so the original assertion would now fail for the right reason,
    which is the same as failing for no reason.

    The successor keeps the boundary where it was always meaningful: the
    twelve WP-18 modules still compute nothing, and
    :meth:`test_every_module_belongs_to_one_package` makes sure a new file
    cannot slip past both lists.

    The check is on *identifiers* - a name somebody could call - rather than on
    words, because every module here discusses denominators in order to
    explain why it has none.
    """

    def test_every_module_belongs_to_one_package(self):
        """No file in ``pgx/validation`` is unclassified.

        Without this, adding a module would exempt it from both boundary
        checks by being on neither list, which is the quietest possible way
        to lose a guarantee.
        """
        self.assertEqual(set(_all_module_names()),
                         set(WP18_MODULES) | set(WP21_MODULES))

    FORBIDDEN_NAMES = ("concordance", "accuracy", "precision", "recall",
                       "f1_score", "pass_rate", "hit_rate", "percentage",
                       "percent", "denominator", "numerator", "auc",
                       "sensitivity", "specificity", "agreement_rate")

    def test_no_function_or_variable_names_a_metric(self):
        for path in _modules():
            relative = os.path.relpath(path, REPO_ROOT)
            parsed = _tree(path)
            names = set()
            for node in ast.walk(parsed):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef)):
                    names.add(node.name.lower())
                elif isinstance(node, ast.Name):
                    names.add(node.id.lower())
                elif isinstance(node, ast.arg):
                    names.add(node.arg.lower())
            for forbidden in self.FORBIDDEN_NAMES:
                with self.subTest(module=relative, name=forbidden):
                    self.assertNotIn(forbidden, names)

    def test_no_division_appears_in_wp18s_modules(self):
        """A rate is a division. WP-18 performs none, and that is the point."""
        for path in _modules():
            relative = os.path.relpath(path, REPO_ROOT)
            for node in ast.walk(_tree(path)):
                if isinstance(node, ast.BinOp) and isinstance(
                        node.op, (ast.Div, ast.FloorDiv)):
                    self.fail("%s computes a quotient at line %d"
                              % (relative, node.lineno))


class TestNoLaterWorkPackageIsStarted(unittest.TestCase):

    def test_no_module_implements_authentication(self):
        """WP-23 owns identity. An access context is a claim, not a login."""
        forbidden = ("password", "hash_password", "verify_password",
                     "session_token", "login", "logout", "authenticate",
                     "jwt", "oauth", "cookie")
        for path in _modules():
            relative = os.path.relpath(path, REPO_ROOT)
            names = {node.name.lower() for node in ast.walk(_tree(path))
                     if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
            for name in forbidden:
                with self.subTest(module=relative, name=name):
                    self.assertNotIn(name, names)

    def test_no_module_implements_an_expert_review_workflow(self):
        """WP-22 owns reveal, adjudication and expert answers."""
        forbidden = ("reveal", "unblind", "adjudicate", "expert_answer",
                     "record_answer", "submit_review", "score_case")
        for path in _modules():
            relative = os.path.relpath(path, REPO_ROOT)
            names = {node.name.lower() for node in ast.walk(_tree(path))
                     if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
            for name in forbidden:
                with self.subTest(module=relative, name=name):
                    self.assertNotIn(name, names)

    def test_nothing_approves_anything(self):
        forbidden = ("approve", "activate_release", "promote", "publish",
                     "mark_validated", "accept_evidence", "sign_off")
        for path in _modules():
            relative = os.path.relpath(path, REPO_ROOT)
            names = {node.name.lower() for node in ast.walk(_tree(path))
                     if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
            for name in forbidden:
                with self.subTest(module=relative, name=name):
                    self.assertNotIn(name, names)

    def test_no_llm_or_generated_answer_path_exists(self):
        forbidden_roots = ("openai", "anthropic", "llm", "transformers",
                           "langchain")
        for path in _modules():
            relative = os.path.relpath(path, REPO_ROOT)
            for name in _imports(path):
                with self.subTest(module=relative, imported=name):
                    self.assertNotIn(name.split(".")[0], forbidden_roots)


class TestTheRealDataBoundaryHolds(unittest.TestCase):

    def test_the_prohibited_list_covers_every_named_category(self):
        from pgx.validation.cases import PROHIBITED_CASE_FIELDS

        required = {
            "raw sequencing": ("vcf", "fastq", "bam", "cram"),
            "genotype level": ("genotype", "diplotype", "star_allele",
                               "activity_score"),
            "laboratory and EHR": ("lab_report", "ehr", "clinical_note"),
            "identifiers": ("patient_name", "mrn", "date_of_birth",
                            "national_id"),
            "clinical decisions": ("diagnosis", "indication", "dose"),
            "free text": ("free_text", "narrative"),
            "uploads": ("upload", "uploaded_file", "attachment"),
            "expected answers": ("expected_result", "gold_standard",
                                 "ground_truth", "answer_key"),
        }
        present = {name.lower() for name in PROHIBITED_CASE_FIELDS}
        for category, names in required.items():
            for name in names:
                with self.subTest(category=category, field=name):
                    self.assertIn(name, present)

    def test_public_gene_symbols_are_not_prohibited(self):
        """Governed vocabulary, not data about a person.

        Refusing them would make the package unable to describe a case at all,
        and would confuse a published nomenclature with a medical record.
        """
        from pgx.validation.cases import PROHIBITED_CASE_FIELDS

        present = {name.lower() for name in PROHIBITED_CASE_FIELDS}
        for permitted in ("gene", "genes", "observations", "medications",
                          "phenotype_value", "drug"):
            with self.subTest(field=permitted):
                self.assertNotIn(permitted, present)

    def test_there_is_no_real_patient_classification(self):
        from pgx.validation.vocabulary import DataClassification

        values = {member.value for member in DataClassification}
        self.assertEqual(values, {"SYNTHETIC",
                                  "PUBLISHED_LITERATURE_DERIVED"})

    def test_no_module_reads_an_environment_variable_for_patient_data(self):
        from pgx.validation.gate_status import RESTRICTED_STORAGE_ENV

        self.assertEqual(RESTRICTED_STORAGE_ENV,
                         "PGX_VALIDATION_RESTRICTED_ROOT")


class TestTheVocabulariesAgree(unittest.TestCase):

    def test_every_validation_role_maps_onto_a_curation_role(self):
        """WP-09 has six roles, WP-18 has three, and they must not drift."""
        from pgx.curation.vocabulary import CaseRole
        from pgx.validation.vocabulary import (CURATION_ROLE_EQUIVALENT,
                                               ValidationCaseRole)

        curation = {member.value for member in CaseRole}
        for role in ValidationCaseRole:
            with self.subTest(role=role.value):
                mapped = CURATION_ROLE_EQUIVALENT[role.value]
                self.assertIn(mapped, curation)

    def test_the_map_is_total(self):
        from pgx.validation.vocabulary import (CURATION_ROLE_EQUIVALENT,
                                               ValidationCaseRole)

        self.assertEqual(sorted(CURATION_ROLE_EQUIVALENT),
                         sorted(role.value for role in ValidationCaseRole))

    def test_the_three_roles_are_not_ordered(self):
        """None of these vocabularies is a scale."""
        from pgx.validation.vocabulary import ValidationCaseRole

        with self.assertRaises(TypeError):
            ValidationCaseRole.DEVELOPMENT < ValidationCaseRole.EXPERT_HOLDOUT
