# -*- coding: utf-8 -*-
"""Layer boundaries WP-07 must not cross.

The boundary most likely to erode is the WP-08 one. The moment something here
assigns a significance, a risk, a phenotype effect or a recommendation, WP-07
has started curating, and a canonical entity stops being a record of what the
source said. Every check reads the AST, so nothing needs installing.
"""

from __future__ import annotations

import ast
import io
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

PACKAGE = os.path.join("pgx", "normalization")

WP07_MODULES = tuple(
    os.path.join(PACKAGE, name) for name in (
        "__init__.py", "allocation.py", "artifacts.py", "build.py",
        "dedup.py", "errors.py", "extract.py", "legacy_diff.py", "models.py",
        "normalize.py", "ports.py", "quality.py", "quality_decision.py",
        "resolver.py",
    )
) + (os.path.join("pgx", "application", "normalize_cli.py"),)


def _source(relative: str) -> str:
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


def _imports(relative: str):
    tree = ast.parse(_source(relative), filename=relative)
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _identifiers(relative: str):
    tree = ast.parse(_source(relative), filename=relative)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
            names.update(alias.name for alias in node.names)
    return names


class TestEveryModuleIsListed(unittest.TestCase):

    def test_the_module_list_matches_the_package(self):
        """A new module must be added here deliberately.

        Otherwise a module could join the package and skip every boundary check
        below simply by not being named.
        """
        directory = os.path.join(REPO_ROOT, PACKAGE)
        present = {name for name in os.listdir(directory)
                   if name.endswith(".py")}
        listed = {os.path.basename(path) for path in WP07_MODULES
                  if path.startswith(PACKAGE)}
        self.assertEqual(present, listed)


class TestDependencyDirection(unittest.TestCase):

    def test_no_module_imports_the_database_layer(self):
        for relative in WP07_MODULES:
            for module in _imports(relative):
                with self.subTest(module=relative, imported=module):
                    self.assertFalse(module.startswith("pgx.infrastructure"))

    def test_no_module_imports_sqlalchemy_or_a_session(self):
        for relative in WP07_MODULES:
            identifiers = _identifiers(relative)
            for token in ("sqlalchemy", "Session", "Engine", "Connection",
                          "alembic"):
                with self.subTest(module=relative, token=token):
                    self.assertNotIn(token, identifiers)

    def test_the_domain_layer_never_imports_this_package(self):
        domain = os.path.join(REPO_ROOT, "pgx", "domain")
        for name in sorted(os.listdir(domain)):
            if not name.endswith(".py"):
                continue
            relative = os.path.join("pgx", "domain", name)
            for module in _imports(relative):
                with self.subTest(module=name, imported=module):
                    self.assertFalse(module.startswith("pgx.normalization"))

    def test_no_module_imports_a_legacy_root_script(self):
        legacy = ("clinpgx_probe", "clinpgx_probe_v2", "risk_engine",
                  "alternative_ranker", "candidate_onboarding",
                  "clean_mvp_seed_dataset", "gemini_report_generator")
        for relative in WP07_MODULES:
            for module in _imports(relative):
                with self.subTest(module=relative, imported=module):
                    self.assertNotIn(module.split(".")[0], legacy)

    def test_the_ports_module_names_no_infrastructure_type(self):
        identifiers = _identifiers(os.path.join(PACKAGE, "ports.py"))
        for token in ("Session", "Connection", "Engine", "Query", "Table",
                      "sqlalchemy", "cursor"):
            with self.subTest(token=token):
                self.assertNotIn(token, identifiers)


class TestNoWp08OrLaterConceptAppears(unittest.TestCase):
    """WP-07 says what the source contains. It never says what it means."""

    FORBIDDEN = (
        "EvidenceRecord", "CuratedInterpretation", "ComputableRule",
        "RulesetVersion", "AssessmentFinding", "Assessment",
        "AttentionLevel", "Phenotype", "attention_level", "risk_level",
        "significance", "evidence_strength", "recommendation",
        "phenotype_effect", "dosing", "treatment", "alternative_drug",
        "MANUAL_EFFECT_HINTS",
    )

    def test_no_module_names_a_curation_or_assessment_concept(self):
        for relative in WP07_MODULES:
            identifiers = _identifiers(relative)
            for token in self.FORBIDDEN:
                with self.subTest(module=relative, token=token):
                    self.assertNotIn(token, identifiers)

    def test_no_module_defines_a_scoring_or_ranking_function(self):
        for relative in WP07_MODULES:
            tree = ast.parse(_source(relative), filename=relative)
            names = {node.name for node in ast.walk(tree)
                     if isinstance(node, ast.FunctionDef)}
            for token in ("score", "rank", "prefer", "best", "weight",
                          "prioritise", "prioritize", "grade"):
                with self.subTest(module=relative, function=token):
                    self.assertNotIn(token, names)


class TestNoIdentityIsDerived(unittest.TestCase):

    def test_only_the_allocation_module_touches_uuid(self):
        allowed = {os.path.join(PACKAGE, "allocation.py")}
        for relative in WP07_MODULES:
            if relative in allowed:
                continue
            identifiers = _identifiers(relative)
            for token in ("uuid", "uuid4", "uuid5"):
                with self.subTest(module=relative, token=token):
                    self.assertNotIn(token, identifiers)

    def test_no_module_calls_derive(self):
        for relative in WP07_MODULES:
            tree = ast.parse(_source(relative), filename=relative)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and \
                        isinstance(node.func, ast.Attribute):
                    with self.subTest(module=relative):
                        self.assertNotEqual(node.func.attr, "derive")

    def test_no_module_adds_derive_to_an_identifier_class(self):
        identifiers_module = os.path.join("pgx", "domain", "identifiers.py")
        tree = ast.parse(_source(identifiers_module),
                         filename=identifiers_module)
        with_derive = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = {child.name for child in node.body
                           if isinstance(child, ast.FunctionDef)}
                if "derive" in methods:
                    with_derive.add(node.name)
        self.assertEqual(with_derive, {"SourceRegistryEntryId"})


class TestNoApprovalOrPublicationPath(unittest.TestCase):

    def test_no_module_defines_an_approval_or_publication_function(self):
        for relative in WP07_MODULES:
            tree = ast.parse(_source(relative), filename=relative)
            names = {node.name for node in ast.walk(tree)
                     if isinstance(node, ast.FunctionDef)}
            for token in ("approve", "approve_alias", "publish", "activate",
                          "mark_quality_checked", "promote", "sign_off",
                          "auto_approve", "retire"):
                with self.subTest(module=relative, function=token):
                    self.assertNotIn(token, names)

    def test_no_module_writes_a_published_state(self):
        for relative in WP07_MODULES:
            tree = ast.parse(_source(relative), filename=relative)
            constants = {node.value for node in ast.walk(tree)
                         if isinstance(node, ast.Constant)
                         and isinstance(node.value, str)}
            for token in ("PUBLISHED", "RELEASE_ACTIVATED"):
                with self.subTest(module=relative, constant=token):
                    self.assertNotIn(token, constants)

    def test_only_the_report_may_mention_quality_checked_and_only_as_prose(self):
        """The phrase appears in explanations of what WP-07 will not do.

        Never as a value written to a state field: a test in
        ``test_data_quality`` asserts the only lifecycle state this package
        writes is ``BUILDING``.
        """
        for relative in WP07_MODULES:
            tree = ast.parse(_source(relative), filename=relative)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign):
                    continue
                if isinstance(node.value, ast.Constant) and \
                        node.value.value == "QUALITY_CHECKED":
                    self.fail("%s assigns QUALITY_CHECKED" % relative)


class TestNoFuzzyMatchingAnywhere(unittest.TestCase):

    FORBIDDEN = ("difflib", "SequenceMatcher", "get_close_matches",
                 "rapidfuzz", "fuzzywuzzy", "Levenshtein", "levenshtein",
                 "jellyfish", "soundex", "metaphone", "embedding", "openai",
                 "anthropic", "transformers")

    def test_no_module_references_a_fuzzy_or_model_based_matcher(self):
        for relative in WP07_MODULES:
            identifiers = _identifiers(relative)
            for token in self.FORBIDDEN:
                with self.subTest(module=relative, token=token):
                    self.assertNotIn(token, identifiers)


class TestNoNetworkAccess(unittest.TestCase):

    def test_no_module_imports_a_networking_library(self):
        for relative in WP07_MODULES:
            for module in _imports(relative):
                root = module.split(".")[0]
                with self.subTest(module=relative, imported=module):
                    self.assertNotIn(root, ("requests", "urllib", "http",
                                            "socket", "httpx", "aiohttp",
                                            "ftplib", "smtplib"))


class TestTheDomainIsUntouched(unittest.TestCase):

    def test_the_wp02_alias_tables_keep_their_composite_primary_key(self):
        """A globally unique alias constraint would make ambiguity unstorable.

        Checked against the ``0001`` migration, which WP-07 does not rewrite.
        """
        relative = os.path.join("migrations", "versions",
                                "0001_wp02_foundation.py")
        text = _source(relative)
        self.assertIn('sa.PrimaryKeyConstraint("gene_id", "normalized_alias"',
                      text)
        self.assertIn('sa.PrimaryKeyConstraint("drug_id", "normalized_alias"',
                      text)

    def test_find_by_alias_still_returns_a_sequence(self):
        relative = os.path.join("pgx", "domain", "ports.py")
        tree = ast.parse(_source(relative), filename=relative)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and \
                    node.name == "find_by_alias":
                rendered = ast.dump(node.returns)
                self.assertIn("Sequence", rendered)
                return
        self.fail("find_by_alias not found in pgx/domain/ports.py")


if __name__ == "__main__":
    unittest.main()
