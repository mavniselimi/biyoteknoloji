# -*- coding: utf-8 -*-
"""Dependency direction enforcement (WP-02).

AST-based, so the boundary is provable without SQLAlchemy or psycopg installed.
A test that needed the driver in order to prove the domain does not need the
driver would be self-defeating.
"""

from __future__ import annotations

import ast
import io
import os
import unittest

from tests.unit.domain._fixtures import REPO_ROOT

DOMAIN_DIR = os.path.join(REPO_ROOT, "pgx", "domain")
INFRA_DIR = os.path.join(REPO_ROOT, "pgx", "infrastructure")
PGX_DIR = os.path.join(REPO_ROOT, "pgx")

#: Nothing in pgx/domain may import any of these.
FORBIDDEN_DOMAIN_IMPORTS = (
    "sqlalchemy", "alembic", "psycopg", "psycopg2", "asyncpg",
    "fastapi", "starlette", "uvicorn", "pydantic",
    "requests", "httpx", "aiohttp", "urllib3",
    "jinja2", "mako", "chameleon",
    "google", "google.generativeai", "openai", "anthropic", "litellm",
    "pgx.infrastructure", "apps",
)

#: The seven frozen legacy root scripts. No V2 module may import them.
LEGACY_ROOT_MODULES = (
    "clinpgx_probe", "clinpgx_probe_v2", "clean_mvp_seed_dataset", "risk_engine",
    "gemini_report_generator", "candidate_onboarding", "alternative_ranker",
)


def _python_files(directory):
    for root, dirs, files in os.walk(directory):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if name.endswith(".py"):
                yield os.path.join(root, name)


def _imported_modules(path):
    """Return every module name imported by ``path``."""
    with io.open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                modules.add(node.module)
    return modules


def _relative(path):
    return os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")


class TestDomainIsFrameworkFree(unittest.TestCase):

    def test_domain_directory_is_not_empty(self):
        files = list(_python_files(DOMAIN_DIR))
        self.assertGreaterEqual(len(files), 6, "expected the full domain layer")

    def test_no_domain_module_imports_a_framework_or_driver(self):
        offences = []
        for path in _python_files(DOMAIN_DIR):
            for module in _imported_modules(path):
                root = module.split(".")[0]
                for forbidden in FORBIDDEN_DOMAIN_IMPORTS:
                    if module == forbidden or module.startswith(forbidden + ".") \
                            or root == forbidden.split(".")[0] and "." not in forbidden:
                        offences.append((_relative(path), module))
        self.assertEqual(offences, [])

    def test_domain_imports_only_stdlib_and_itself(self):
        allowed_roots = {
            "__future__", "abc", "collections", "contextlib", "dataclasses",
            "datetime", "decimal", "enum", "functools", "hashlib", "json", "math",
            "re", "types", "typing", "uuid", "pgx",
        }
        offences = []
        for path in _python_files(DOMAIN_DIR):
            for module in _imported_modules(path):
                root = module.split(".")[0]
                if root not in allowed_roots:
                    offences.append((_relative(path), module))
        self.assertEqual(offences, [])

    def test_domain_never_imports_infrastructure(self):
        for path in _python_files(DOMAIN_DIR):
            for module in _imported_modules(path):
                self.assertFalse(module.startswith("pgx.infrastructure"),
                                 "%s imports %s" % (_relative(path), module))


class TestInfrastructureMayImportDomain(unittest.TestCase):

    def test_infrastructure_imports_the_domain(self):
        imports_domain = False
        for path in _python_files(INFRA_DIR):
            if any(module.startswith("pgx.domain") for module in _imported_modules(path)):
                imports_domain = True
                break
        self.assertTrue(imports_domain,
                        "infrastructure is expected to depend on the domain")

    def test_orm_models_live_only_in_infrastructure_db(self):
        """Every DeclarativeBase subclass is defined in exactly one module."""
        orm_modules = set()
        for path in _python_files(PGX_DIR):
            with io.open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    base_names = {
                        base.id if isinstance(base, ast.Name) else
                        getattr(base, "attr", "") for base in node.bases}
                    if "Base" in base_names or "DeclarativeBase" in base_names:
                        orm_modules.add(_relative(path))
        # The directory property first, which is what this test is named
        # for and what actually matters: an ORM class anywhere else would be
        # persistence leaking into the domain.
        for module in sorted(orm_modules):
            with self.subTest(module=module):
                self.assertTrue(module.startswith("pgx/infrastructure/db/"),
                                "ORM classes must exist only in "
                                "infrastructure/db")
        # Then the exact set, so a stray new persistence module is noticed
        # rather than absorbed. WP-22 added expert_reviews.py, which holds
        # the seven append-only review tables.
        self.assertEqual(
            orm_modules,
            {"pgx/infrastructure/db/base.py",
             "pgx/infrastructure/db/models.py",
             "pgx/infrastructure/db/expert_reviews.py",
             # WP-23: users, sessions, rate-limit counters, the governed
             # audit stream and its head row.
             "pgx/infrastructure/db/security.py"},
            "ORM classes must exist only in infrastructure/db")

    def test_no_domain_model_subclasses_the_orm_base(self):
        for path in _python_files(DOMAIN_DIR):
            with io.open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for base in node.bases:
                        name = base.id if isinstance(base, ast.Name) else getattr(
                            base, "attr", "")
                        self.assertNotIn(name, ("Base", "DeclarativeBase"),
                                         "%s.%s subclasses the ORM base"
                                         % (_relative(path), node.name))

    def test_orm_and_domain_hierarchies_are_disjoint(self):
        """An ORM class is never a domain dataclass and vice versa."""
        with io.open(os.path.join(INFRA_DIR, "db", "models.py"), encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        orm_names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
        with io.open(os.path.join(DOMAIN_DIR, "models.py"), encoding="utf-8") as handle:
            domain_tree = ast.parse(handle.read())
        domain_names = {node.name for node in domain_tree.body
                        if isinstance(node, ast.ClassDef)}
        self.assertEqual(orm_names & domain_names, set(),
                         "ORM and domain class names must not collide")
        for name in orm_names:
            self.assertTrue(name.endswith("ORM"), name)


def _callee_name(node):
    """Dotted name of a call's target, e.g. ``io.open`` - or '' if unnameable."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return "%s.%s" % (func.value.id, func.attr)
    return ""


class TestLegacyIsolation(unittest.TestCase):

    def test_no_v2_module_imports_a_legacy_root_script(self):
        offences = []
        for path in _python_files(PGX_DIR):
            for module in _imported_modules(path):
                if module.split(".")[0] in LEGACY_ROOT_MODULES:
                    offences.append((_relative(path), module))
        self.assertEqual(offences, [])

    def test_wp02_scripts_do_not_import_legacy_modules(self):
        for name in ("db_seed.py", "db_check.py"):
            path = os.path.join(REPO_ROOT, "scripts", name)
            for module in _imported_modules(path):
                self.assertNotIn(module.split(".")[0], LEGACY_ROOT_MODULES,
                                 "%s imports %s" % (name, module))

    #: The V2 modules allowed to name a legacy data path, and why each one is.
    #: WP-05's brief requires an inventory of the source values already in the
    #: frozen files, WP-07's requires a report of what the canonical build
    #: changed relative to the legacy seed, and WP-08's requires the legacy
    #: project interpretations to be read out as unreviewed migration
    #: candidates (``architecture.md``, WP-05, WP-07 "Migration", WP-08
    #: "Draft curation"), so naming them is part of all three jobs. What must
    #: still never happen is *loading* those rows as scientific content, which
    #: is what the companion test below checks for every exempt module.
    LEGACY_READING_EXEMPTIONS = (
        "pgx/scientific/inventory.py",
        "pgx/normalization/legacy_diff.py",
        "pgx/evidence/draft_curation.py",
        # WP-12's brief requires a deterministic comparison of the six legacy
        # demo profiles at the phenotype-normalisation level, so this module
        # names that file. It reads six synthetic profiles, not the 3,084 rule
        # rows this rule exists to keep out, and the companion test below holds
        # it to the same narrow terms as the other three: read the file, load
        # nothing from it.
        "pgx/engine/phenotype_legacy.py",
    )

    LEGACY_DATA_PATHS = ("clinpgx_mvp_seed", "phenotype_effect_rules.csv",
                         "drug_gene_guidelines.csv", "clinpgx_outputs")

    @staticmethod
    def _code_strings(path):
        """Every string constant in ``path`` that is not a docstring.

        Docstrings and comments are excluded because the rule is about what a
        module *reads*, not about which filenames it is allowed to mention.
        WP-11's legacy inventory explains, in its module docstring, why the
        rows in ``phenotype_effect_rules.csv`` cannot become rules - and it
        opens nothing. Treating that sentence as an offence would push the
        explanation out of the module that most needs to carry it.

        The narrowing costs nothing: each of the three exempt modules still
        names a legacy path in code, so removing any exemption still fails
        this test.

        **Exclusion lists are also skipped**, and for the same reason rather
        than as a second favour. WP-24's ``FORBIDDEN_IMAGE_PREFIXES`` names
        ``clinpgx_mvp_seed/`` and ``clinpgx_outputs/`` in order to keep them
        *out* of a deployment image - which is the opposite of reading them,
        and is a stronger guarantee than the exemption list could give,
        because it is a property of where the literal sits rather than of
        which file it sits in. Adding ``runtime_assets.py`` to
        LEGACY_READING_EXEMPTIONS would have exempted the whole module; this
        exempts one syntactic position and would still fire on an ``open()``
        three lines below.
        """
        with io.open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        docstrings = set()
        excluded = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                first = node.body[0] if node.body else None
                if (isinstance(first, ast.Expr)
                        and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    docstrings.add(id(first.value))
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (node.targets if isinstance(node, ast.Assign)
                           else [node.target])
                names = {target.id for target in targets
                         if isinstance(target, ast.Name)}
                if any(name.startswith(("FORBIDDEN_", "EXCLUDED_",
                                        "_FORBIDDEN_", "_EXCLUDED_"))
                       for name in names) and node.value is not None:
                    for child in ast.walk(node.value):
                        if isinstance(child, ast.Constant) and \
                                isinstance(child.value, str):
                            excluded.add(id(child))
        return [node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and id(node) not in excluded]

    def test_no_v2_module_reads_the_legacy_seed_data(self):
        """The 3,084 legacy rule rows must not be imported into the database."""
        offences = []
        for directory in (PGX_DIR, os.path.join(REPO_ROOT, "scripts")):
            for path in _python_files(directory):
                relative = _relative(path)
                if relative in self.LEGACY_READING_EXEMPTIONS:
                    continue
                if relative.startswith("scripts/") and \
                        os.path.basename(path) not in ("db_seed.py", "db_check.py"):
                    continue  # frozen WP-01 tooling legitimately reads the seed
                literals = self._code_strings(path)
                for forbidden in self.LEGACY_DATA_PATHS:
                    if any(forbidden in literal for literal in literals):
                        offences.append((relative, forbidden))
        self.assertEqual(offences, [])

    def test_an_exclusion_list_is_not_a_read_but_an_open_still_is(self):
        """The narrowing above is a position, not a permission.

        A legacy path inside a ``FORBIDDEN_*`` tuple is an exclusion. The same
        path passed to ``open()`` in the same module is still an offence, and
        this proves the distinction holds rather than trusting it.
        """
        source = (
            "FORBIDDEN_IMAGE_PREFIXES = ('clinpgx_mvp_seed/',)\n"
            "def read():\n"
            "    return open('clinpgx_outputs/legacy.csv')\n")
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                         encoding="utf-8") as handle:
            handle.write(source)
            path = handle.name
        try:
            literals = self._code_strings(path)
            self.assertNotIn("clinpgx_mvp_seed/", literals)
            self.assertIn("clinpgx_outputs/legacy.csv", literals)
        finally:
            os.unlink(path)

    def test_the_deployment_image_forbids_the_legacy_directories(self):
        """The reason the exclusion above exists, asserted directly.

        WP-24 names these paths so an image cannot acquire them. If the list
        ever stopped naming them, this fails - which is the check the
        narrowing must not have removed.
        """
        from pgx.deployment.runtime_assets import FORBIDDEN_IMAGE_PREFIXES

        for prefix in ("clinpgx_mvp_seed/", "clinpgx_outputs/"):
            with self.subTest(prefix=prefix):
                self.assertIn(prefix, FORBIDDEN_IMAGE_PREFIXES)

    def test_the_exemptions_are_all_still_earning_their_place(self):
        """Each exempt module still names a legacy path in code.

        Without this, narrowing the scan above to code could have made the
        exemption list decorative - three modules excused from a test they
        would no longer fail - and nobody would have noticed.
        """
        for relative in self.LEGACY_READING_EXEMPTIONS:
            literals = self._code_strings(os.path.join(REPO_ROOT, relative))
            with self.subTest(module=relative):
                self.assertTrue(
                    any(forbidden in literal
                        for literal in literals
                        for forbidden in self.LEGACY_DATA_PATHS),
                    "%s no longer names a legacy path in code; its exemption "
                    "should be removed rather than left standing" % relative)

    def test_every_exempt_module_only_counts_and_never_loads(self):
        """The exemption is narrow: read the files, load nothing from them.

        The rule the original test protected was never "do not open these
        files"; it was "do not let 3,084 unreviewed legacy rows become
        scientific content". So an exempt module may read them, and may not do
        any of the things that would turn a reading into an import: open one
        for writing, construct a domain record, or reach a repository.

        Applied to every exempt module rather than to one by name, so adding an
        exemption cannot quietly add an unchecked one.
        """
        for relative in self.LEGACY_READING_EXEMPTIONS:
            with self.subTest(module=relative):
                self._assert_reads_but_never_loads(relative)

    def _assert_reads_but_never_loads(self, relative):
        path = os.path.join(REPO_ROOT, relative)
        self.assertTrue(os.path.isfile(path), relative)
        with io.open(path, encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source, filename=path)

        # Not a single write mode reaches io.open/open in this module.
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _callee_name(node) in ("open", "io.open"):
                modes = [arg.value for arg in node.args[1:]
                         if isinstance(arg, ast.Constant) and isinstance(arg.value, str)]
                modes += [kw.value.value for kw in node.keywords
                          if kw.arg == "mode" and isinstance(kw.value, ast.Constant)]
                for mode in modes:
                    self.assertNotIn("w", mode, "%s must never write" % relative)
                    self.assertNotIn("a", mode, "%s must never append" % relative)
                    self.assertNotIn("+", mode, "%s must never update" % relative)

        # And it constructs no scientific record and touches no repository.
        # Read from identifiers, never from the file's text: a module's own
        # prose says "in this repository", and a substring search would have
        # failed on a docstring while missing a real call.
        identifiers = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                identifiers.add(node.attr)
            elif isinstance(node, ast.Import):
                identifiers.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    identifiers.add(node.module)
                identifiers.update(alias.name for alias in node.names)
        forbidden = ("EvidenceRecord", "CuratedInterpretation", "ComputableRule",
                     "Assessment", "UnitOfWork", "Session", "sqlalchemy",
                     "pgx.domain.models", "pgx.domain.ports",
                     "pgx.infrastructure.db")
        for token in forbidden:
            self.assertNotIn(token, identifiers,
                             "%r in %s would turn counting into loading"
                             % (token, relative))


class TestClaimsModuleIsTheOnlyOperationMode(unittest.TestCase):
    """WP-00 owns OperationMode; WP-02 must not redefine or duplicate it."""

    def test_operation_mode_is_defined_exactly_once(self):
        definitions = []
        for path in _python_files(PGX_DIR):
            with io.open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == "OperationMode":
                    definitions.append(_relative(path))
        self.assertEqual(definitions, ["pgx/domain/claims.py"])

    def test_wp00_claims_module_is_importable_and_unchanged_in_contract(self):
        from pgx.domain.claims import CLAIM_BOUNDARY_STATUS, OperationMode
        self.assertEqual([mode.value for mode in OperationMode],
                         ["DEMO", "VALIDATION", "PILOT"])
        self.assertEqual(CLAIM_BOUNDARY_STATUS,
                         "DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW")


if __name__ == "__main__":
    unittest.main(verbosity=2)
