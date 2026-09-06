# -*- coding: utf-8 -*-
"""Where WP-14 stops (section J).

WP-14 calculates structured facts. It does not render them, and it does not
answer any of the questions the intended purpose puts outside this product's
scope. The strongest guarantee of that is absence rather than a check: there is
nowhere in a WP-14 model, schema, database row or CLI command to put a dose, a
recommendation, a ranking, a candidate preference or a sentence of prose.

This file asserts that absence four ways - as identifiers, as dataclass and
column names, as schema properties, and as CLI commands - so a rename cannot
smuggle one past a text search.

It also asserts the layer direction. WP-14's engine modules read the domain,
WP-11's rules, and WP-12's and WP-13's engines. They read no application
module, no infrastructure module, no network, no clock and no CSV. The
application service orchestrates ports and touches no database itself.
"""

from __future__ import annotations

import ast
import io
import json
import os
import unittest

from tests.unit.engine._support import (APPLICATION_DIR,
                                        ASSESSMENT_APPLICATION_MODULES,
                                        ENGINE_DIR, REPO_ROOT,
                                        WP14_ENGINE_MODULES, identifiers_of,
                                        imports_of, modules_of, source, tree,
                                        wp14_modules)

ALL_WP14_PATHS = wp14_modules()

WP14_SCHEMAS = ("assessment-input.schema.json",
                "assessment-finding.schema.json",
                "medication-assessment.schema.json",
                "assessment-computation.schema.json",
                "assessment-failure.schema.json",
                "assessment-regression-report.schema.json",
                "wp14-gate-status.schema.json")

#: Everything the intended purpose puts outside this product. Checked against
#: identifiers and field names rather than prose, because the modules
#: necessarily *say* these words in order to refuse them.
FORBIDDEN_CONCEPTS = ("dose", "dosage", "recommend", "recommendation",
                      "preferred", "safer", "suitability", "treatment",
                      "alternative", "rank", "ranking", "prescription",
                      "diagnos", "phenoconver", "interaction", "ddi",
                      "narrative", "prose", "render", "markdown", "template")

#: Names a module may hold when it does so in order to refuse the thing.
#: ``FORBIDDEN_SNAPSHOT_KEYS`` is WP-15's preflight addition: the stored input
#: snapshot enumerates ``genotype``, ``diplotype``, ``star_allele``, ``vcf``,
#: ``narrative`` and the rest so that a snapshot carrying one is *refused*.
#: Forbidding the words there would delete the scan, not the capability.
REFUSAL_MARKERS = ("REFUSED_INPUT_FIELDS", "REFUSED_FLAGS",
                   "_legacy_reads_mutable_csv", "v2_csv_modules",
                   "FORBIDDEN_SNAPSHOT_KEYS")

#: Concepts that are whole words rather than substrings. ``ddi`` appears
#: inside ``AssessmentExpecteDDIfference`` and ``rank`` inside ``ranking``:
#: a substring test on either finds a word that is not there, and a test that
#: fails on a name nobody wrote teaches people to weaken it.
WHOLE_WORD_CONCEPTS = ("ddi", "rank")

#: The legacy comparison must name the legacy engine's own functions and
#: fields - ``normalize_rule_group`` is the matcher being corrected, and
#: ``legacy_rendered_as_reassuring`` records how the old output was displayed.
#: A check that forbade them there would delete the description of the defect
#: rather than the defect. Bounded to the one module and the one schema, and
#: a separate test asserts the bound.
LEGACY_CITATION_MODULES = ("risk_legacy.py",)
LEGACY_CITATION_SCHEMAS = ("assessment-regression-report.schema.json",)
LEGACY_CITATION_PREFIX = "legacy_"


def offends(name, concept):
    """Whether ``name`` really contains ``concept``.

    Whole-word for the short ambiguous tokens, substring for the rest.
    """
    lowered = name.lower()
    if concept in WHOLE_WORD_CONCEPTS:
        import re
        return re.search(r"(^|[^a-z])%s([^a-z]|$)" % concept,
                         lowered) is not None
    return concept in lowered


class TestWp14CalculatesFactsAndRendersNothing(unittest.TestCase):

    def test_no_module_names_a_prohibited_concept(self):
        for path in ALL_WP14_PATHS:
            text = source(path)
            refuses = any(marker in text for marker in REFUSAL_MARKERS)
            names = {name.lower() for name in identifiers_of(path)}
            cites = os.path.basename(path) in LEGACY_CITATION_MODULES
            for forbidden in FORBIDDEN_CONCEPTS:
                with self.subTest(module=os.path.basename(path),
                                  concept=forbidden, refuses=refuses):
                    offenders = [name for name in names
                                 if offends(name, forbidden)]
                    if refuses:
                        # A refusing module may name the concept only inside
                        # its refusal table, never as a working identifier.
                        offenders = [name for name in offenders
                                     if name.upper() not in
                                     {marker.upper()
                                      for marker in REFUSAL_MARKERS}]
                        offenders = [name for name in offenders
                                     if not name.startswith("refuse")]
                    if cites:
                        offenders = [name for name in offenders
                                     if not name.startswith(
                                         LEGACY_CITATION_PREFIX)]
                    self.assertEqual(offenders, [],
                                     "%s names %s" % (path, offenders))

    def test_no_class_or_function_names_one(self):
        for path in ALL_WP14_PATHS:
            for node in ast.walk(tree(path)):
                if not isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                    continue
                with self.subTest(module=os.path.basename(path),
                                  name=node.name):
                    for forbidden in FORBIDDEN_CONCEPTS:
                        self.assertFalse(
                            offends(node.name, forbidden),
                            "%s defines %s" % (path, node.name))

    def test_no_dataclass_field_names_one(self):
        import dataclasses
        import importlib
        for name in WP14_ENGINE_MODULES:
            module = importlib.import_module(
                "pgx.engine.%s" % name[:-len(".py")])
            for attribute_name in dir(module):
                attribute = getattr(module, attribute_name)
                if not dataclasses.is_dataclass(attribute):
                    continue
                if getattr(attribute, "__module__", "") != module.__name__:
                    continue
                for field in dataclasses.fields(attribute):
                    for forbidden in FORBIDDEN_CONCEPTS:
                        with self.subTest(model=attribute_name,
                                          field=field.name,
                                          concept=forbidden):
                            self.assertNotIn(forbidden, field.name.lower())

    def test_no_published_schema_declares_one(self):
        for name in WP14_SCHEMAS:
            path = os.path.join(REPO_ROOT, "schemas", name)
            with io.open(path, encoding="utf-8") as handle:
                document = json.load(handle)
            cites = name in LEGACY_CITATION_SCHEMAS
            for key in self._properties(document):
                if key.lower().startswith(LEGACY_CITATION_PREFIX):
                    with self.subTest(schema=name, property=key):
                        self.assertTrue(
                            cites,
                            "%s names a legacy field outside a comparison"
                            % key)
                    continue
                for forbidden in FORBIDDEN_CONCEPTS:
                    with self.subTest(schema=name, property=key,
                                      concept=forbidden):
                        self.assertFalse(offends(key, forbidden))

    def _properties(self, node, found=None):
        found = set() if found is None else found
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "properties" and isinstance(value, dict):
                    found.update(value)
                self._properties(value, found)
        elif isinstance(node, list):
            for item in node:
                self._properties(item, found)
        return found

    def test_no_database_column_names_one(self):
        text = source(os.path.join(REPO_ROOT, "migrations", "versions",
                                   "0009_wp14_assessments.py"))
        columns = []
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Call) and \
                    getattr(node.func, "attr", "") == "Column" and node.args:
                if isinstance(node.args[0], ast.Constant):
                    columns.append(node.args[0].value)
        self.assertTrue(columns)
        for column in columns:
            for forbidden in FORBIDDEN_CONCEPTS:
                with self.subTest(column=column, concept=forbidden):
                    self.assertNotIn(forbidden, column.lower())

    def test_no_module_renders_text(self):
        """WP-15 renders. An engine that rendered would be deciding how its
        own facts read."""
        for path in ALL_WP14_PATHS:
            names = identifiers_of(path)
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("render", "render_markdown", "to_markdown",
                                  "format_report", "Template", "jinja",
                                  "describe", "humanize"):
                    self.assertNotIn(forbidden, names)

    def test_no_module_produces_a_clinical_sentence(self):
        for path in ALL_WP14_PATHS:
            text = source(path).lower()
            for phrase in ("is safe", "safe to", "safe for",
                           "recommended dose", "should be prescribed",
                           "contraindicated", "clinically validated",
                           "approved by", "treatment recommendation",
                           "is preferred", "is suitable", "we recommend"):
                with self.subTest(module=os.path.basename(path),
                                  phrase=phrase):
                    self.assertNotIn(phrase, text)


class TestTheLayerDirection(unittest.TestCase):

    ALLOWED = ("pgx.domain", "pgx.rules", "pgx.normalization", "pgx.engine")

    def test_the_engine_depends_only_on_layers_beneath_it(self):
        for path in modules_of(WP14_ENGINE_MODULES):
            for name in imports_of(path):
                if not name.startswith("pgx."):
                    continue
                with self.subTest(module=os.path.basename(path),
                                  imported=name):
                    self.assertTrue(
                        any(name == prefix or name.startswith(prefix + ".")
                            for prefix in self.ALLOWED), name)

    def test_the_engine_imports_no_application_module(self):
        for path in modules_of(WP14_ENGINE_MODULES):
            for name in imports_of(path):
                with self.subTest(module=os.path.basename(path),
                                  imported=name):
                    self.assertFalse(name.startswith("pgx.application"))

    def test_the_engine_imports_no_infrastructure_module(self):
        for path in modules_of(WP14_ENGINE_MODULES):
            for name in imports_of(path):
                with self.subTest(module=os.path.basename(path),
                                  imported=name):
                    self.assertFalse(name.startswith("pgx.infrastructure"))

    def test_the_service_orchestrates_ports_and_touches_no_database(self):
        path = os.path.join(APPLICATION_DIR, "assessment_service.py")
        imported = imports_of(path)
        for forbidden in ("sqlalchemy", "psycopg2", "alembic"):
            with self.subTest(imported=forbidden):
                self.assertNotIn(forbidden, imported)
        for name in imported:
            with self.subTest(imported=name):
                self.assertFalse(name.startswith("pgx.infrastructure"))

    def test_the_infrastructure_adapter_leaks_no_orm_object(self):
        """It returns dictionaries and domain values, never a mapped row."""
        path = os.path.join(REPO_ROOT, "pgx", "infrastructure", "db",
                            "assessments.py")
        text = source(path)
        self.assertNotIn("(Base)", text)
        for node in ast.walk(tree(path)):
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name not in ("get", "list_for_release"):
                continue
            returned = ast.get_source_segment(text, node)
            with self.subTest(method=node.name):
                self.assertNotIn("return row\n", returned)

    def test_phenotype_matching_is_not_reimplemented(self):
        """WP-12 owns equality. The legacy comparison names the legacy
        matcher's own function names in order to report that they are being
        corrected, and is checked as identifiers rather than as prose."""
        engine = source(os.path.join(ENGINE_DIR, "risk.py"))
        self.assertIn("match_observation", engine)
        for path in ALL_WP14_PATHS:
            cites = os.path.basename(path) in LEGACY_CITATION_MODULES
            haystack = (" ".join(sorted(identifiers_of(path))) if cites
                        else source(path))
            with self.subTest(module=os.path.basename(path), cites=cites):
                for forbidden in ("PHENOTYPE_ALIASES", "PHENOTYPE_GROUPS",
                                  "normalize_rule_group", "phenotype_matches",
                                  "closest_phenotype"):
                    self.assertNotIn(forbidden, haystack)

    def test_the_citation_exemption_covers_only_what_it_names(self):
        self.assertEqual(LEGACY_CITATION_MODULES, ("risk_legacy.py",))
        self.assertEqual(LEGACY_CITATION_SCHEMAS,
                         ("assessment-regression-report.schema.json",))
        for path in ALL_WP14_PATHS:
            if os.path.basename(path) in LEGACY_CITATION_MODULES:
                continue
            for name in identifiers_of(path):
                with self.subTest(module=os.path.basename(path), name=name):
                    self.assertFalse(
                        name.lower().startswith(LEGACY_CITATION_PREFIX))

    def test_coverage_is_not_recomputed(self):
        engine = source(os.path.join(ENGINE_DIR, "risk.py"))
        self.assertNotIn("evaluate_coverage", engine)
        self.assertNotIn("AXIS_DECISION_TABLE", engine)

    def test_no_module_infers_a_phenotype_from_a_genotype(self):
        for path in ALL_WP14_PATHS:
            text = source(path)
            refuses = any(marker in text for marker in REFUSAL_MARKERS)
            haystack = (" ".join(sorted(identifiers_of(path))) if refuses
                        else text)
            with self.subTest(module=os.path.basename(path), refuses=refuses):
                for forbidden in ("star_allele", "diplotype", "activity_score",
                                  "allele_function", "haplotype",
                                  "phenoconversion", "infer_phenotype"):
                    self.assertNotIn(forbidden, haystack.lower())


class TestWp14ReachesForNothingItWasNotGiven(unittest.TestCase):

    def test_the_engine_needs_no_network_and_no_model(self):
        for path in ALL_WP14_PATHS:
            roots = {name.split(".")[0] for name in imports_of(path)}
            names = {name.lower() for name in identifiers_of(path)}
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("requests", "httpx", "urllib", "socket",
                                  "aiohttp", "openai", "anthropic",
                                  "transformers", "torch"):
                    self.assertNotIn(forbidden, roots)
                for forbidden in ("completion", "embedding", "llm", "chat"):
                    for name in names:
                        self.assertNotIn(forbidden, name)

    def test_the_engine_needs_no_clock(self):
        for path in modules_of(WP14_ENGINE_MODULES):
            roots = {name.split(".")[0] for name in imports_of(path)}
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("datetime", "time", "random", "secrets",
                                  "calendar", "uuid"):
                    self.assertNotIn(forbidden, roots)

    def test_no_module_reads_a_mutable_csv(self):
        for path in ALL_WP14_PATHS:
            text = source(path)
            detects = any(marker in text for marker in REFUSAL_MARKERS)
            with self.subTest(module=os.path.basename(path)):
                self.assertNotIn("csv", imports_of(path))
                if not detects:
                    self.assertNotIn(".csv", text)

    def test_no_module_imports_the_legacy_script(self):
        for path in ALL_WP14_PATHS:
            with self.subTest(module=os.path.basename(path)):
                self.assertNotIn("risk_engine", imports_of(path))

    def test_no_production_module_imports_a_fixture(self):
        for path in ALL_WP14_PATHS:
            for name in imports_of(path):
                with self.subTest(module=os.path.basename(path),
                                  imported=name):
                    self.assertFalse(name.startswith("tests."))

    #: The only two modules under ``pgx/`` that may construct a claim
    #: boundary. ``claims.py`` is the WP-00 owner of the type and the P0
    #: instance. ``candidate_claims.py`` was added because ``claims.py`` is a
    #: frozen WP-01 baseline artifact and could not be edited to carry the
    #: provisional candidate boundary; it is exempted here and paid for by
    #: ``test_no_boundary_an_owner_ships_is_approved_or_enables_pilot``, which
    #: checks what the exemption could otherwise hide.
    BOUNDARY_OWNERS = (os.path.join("pgx", "domain", "claims.py"),
                       os.path.join("pgx", "domain", "candidate_claims.py"))

    def test_only_a_boundary_owner_constructs_a_claim_boundary(self):
        """The one thing a fixture may do that production code may not.

        ``synthetic_claim_boundary()`` builds a boundary whose status reads as
        approved, and it lives in a test fixture. The two owner modules
        legitimately define the type and its instances, and nothing else under
        ``pgx/`` constructs one, so no service can quietly hand itself a
        boundary that permits execution.
        """
        for root, dirs, files in os.walk(os.path.join(REPO_ROOT, "pgx")):
            dirs[:] = [name for name in dirs if name != "__pycache__"]
            for name in sorted(files):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                if os.path.relpath(path, REPO_ROOT) in self.BOUNDARY_OWNERS:
                    continue
                text = source(path)
                with self.subTest(module=os.path.relpath(path, REPO_ROOT)):
                    self.assertNotIn("ClaimBoundary(", text)
                    self.assertNotIn("DEFAULT_CLAIM_BOUNDARY =", text)
                    self.assertNotIn("is_approved = True", text)

    def test_no_boundary_an_owner_ships_is_approved_or_enables_pilot(self):
        """What the second owner buys itself an exemption to do, checked.

        An owner may *build* a boundary; neither may *bless* one. Every
        boundary either module exposes at import time is inspected as an
        object rather than as text, so a status string, an overridden
        property or a future field cannot talk its way past this.
        """
        import importlib

        from pgx.domain.claims import ClaimBoundary, OperationMode

        found = []
        for relative in self.BOUNDARY_OWNERS:
            module_name = relative[:-len(".py")].replace(os.sep, ".")
            module = importlib.import_module(module_name)
            for name in sorted(dir(module)):
                value = getattr(module, name)
                if isinstance(value, ClaimBoundary):
                    found.append((module_name, name, value))
        # P0_CLAIM_BOUNDARY, DEFAULT_CLAIM_BOUNDARY and the candidate one.
        self.assertGreaterEqual(len(found), 3)
        self.assertEqual(
            {module_name for module_name, _, _ in found},
            {relative[:-len(".py")].replace(os.sep, ".")
             for relative in self.BOUNDARY_OWNERS})
        for module_name, name, boundary in found:
            with self.subTest(module=module_name, constant=name):
                self.assertFalse(boundary.is_approved)
                self.assertNotIn(OperationMode.PILOT, boundary.enabled_modes)

    def test_the_boundary_wp00_ships_is_not_approved(self):
        """The other half: the module that may build one builds an
        unapproved one, and says so in its status."""
        from pgx.domain.claims import DEFAULT_CLAIM_BOUNDARY, P0_CLAIM_BOUNDARY
        self.assertFalse(DEFAULT_CLAIM_BOUNDARY.is_approved)
        self.assertFalse(P0_CLAIM_BOUNDARY.is_approved)
        self.assertIn("DRAFT", DEFAULT_CLAIM_BOUNDARY.status)


class TestNoAssessmentCanBeManufactured(unittest.TestCase):

    def test_the_cli_offers_no_command_that_bypasses_a_gate(self):
        from pgx.application.assessment_cli import build_parser
        commands = set()
        for action in build_parser()._actions:
            if getattr(action, "choices", None):
                commands.update(action.choices)
        for forbidden in ("approve-boundary", "approve", "activate-release",
                          "seed-assessment", "render-report", "recommend",
                          "rank", "force"):
            with self.subTest(command=forbidden):
                self.assertNotIn(forbidden, commands)

    def test_the_cli_refuses_every_shortcut_flag(self):
        from pgx.application.assessment_cli import (REFUSED_FLAGS,
                                                    refuse_unsafe_flags)
        for flag in ("--force-release", "--bypass-approval",
                     "--allow-draft-rule", "--ignore-coverage",
                     "--ignore-evidence", "--assume-normal",
                     "--clinical-mode", "--patient-mode", "--dose",
                     "--recommend", "--rank"):
            with self.subTest(flag=flag):
                self.assertIn(flag, REFUSED_FLAGS)
                self.assertIsNotNone(refuse_unsafe_flags([flag]))
                self.assertIsNotNone(refuse_unsafe_flags([flag + "=1"]))

    def test_every_refused_flag_states_why(self):
        from pgx.application.assessment_cli import REFUSED_FLAGS
        for flag, reason in REFUSED_FLAGS.items():
            with self.subTest(flag=flag):
                self.assertGreater(len(reason), 20)

    def test_abbreviations_cannot_reach_a_refused_flag(self):
        from pgx.application.assessment_cli import build_parser
        self.assertFalse(build_parser().allow_abbrev)

    def test_no_module_writes_an_approval_or_activates_a_release(self):
        for path in ALL_WP14_PATHS:
            names = identifiers_of(path)
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("approve", "activate", "activate_release",
                                  "sign", "authorize", "grant_role",
                                  "assign_role", "set_status"):
                    self.assertNotIn(forbidden, names)

    def test_the_default_gate_still_reports_zero(self):
        from pgx.application.assessment_gate_status import (
            build_assessment_gate_status)
        status = build_assessment_gate_status(REPO_ROOT).to_json()
        for name, value in status["assessment_state"].items():
            with self.subTest(count=name):
                self.assertEqual(value, 0)

    def test_the_assessment_directory_holds_no_assessment(self):
        directory = os.path.join(REPO_ROOT, "data", "assessments")
        present = sorted(name for name in os.listdir(directory)
                         if name.endswith(".json"))
        self.assertEqual(present, ["wp14-real-gate-status.json"])


class TestTheFixturesAreMarkedAndUnreachable(unittest.TestCase):

    FIXTURE = os.path.join(REPO_ROOT, "tests", "fixtures", "wp14",
                           "synthetic.py")

    def test_the_fixture_carries_every_synthetic_marker(self):
        from tests.fixtures.wp14.synthetic import SYNTHETIC_MARKERS
        text = source(self.FIXTURE)
        for marker in SYNTHETIC_MARKERS:
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_the_synthetic_boundary_says_it_is_not_a_real_approval(self):
        from tests.fixtures.wp14.synthetic import SYNTHETIC_BOUNDARY_STATUS
        self.assertIn("TEST ONLY", SYNTHETIC_BOUNDARY_STATUS)
        self.assertIn("NOT A REAL APPROVAL", SYNTHETIC_BOUNDARY_STATUS)

    def test_the_synthetic_boundary_still_prohibits_every_category(self):
        """An approved boundary is not an unrestricted one."""
        from pgx.domain.claims import ProhibitedClaimCategory
        from tests.fixtures.wp14.synthetic import synthetic_claim_boundary
        boundary = synthetic_claim_boundary()
        for category in ProhibitedClaimCategory:
            with self.subTest(category=category.value):
                self.assertTrue(boundary.is_category_prohibited(category))

    def test_the_fixture_uses_no_real_gene_or_drug_name(self):
        module = tree(self.FIXTURE)
        used = {name.lower() for name in identifiers_of(self.FIXTURE)}
        docstring = ast.get_docstring(module, clean=False)
        for node in ast.walk(module):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value == docstring:
                    continue
                used.add(node.value.lower())
        haystack = " ".join(sorted(used))
        for forbidden in ("cyp2d6", "cyp2c19", "cyp2c9", "clopidogrel",
                          "warfarin", "codeine", "tamoxifen"):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, haystack)

    def test_no_production_module_names_the_fixture_directory(self):
        for path in ALL_WP14_PATHS:
            text = source(path)
            with self.subTest(module=os.path.basename(path)):
                self.assertNotIn("tests/fixtures", text)
                self.assertNotIn("fixtures/wp14", text)


class TestWp16AndLaterWereNotStarted(unittest.TestCase):
    """``pgx/reporting`` left this class when WP-15 created it.

    It was here to assert that WP-14 rendered nothing. That property did not
    go away when WP-15 arrived - it moved: WP-14's own boundary tests still
    assert that no assessment module renders prose, and WP-15's assert that
    no reporting module calculates. What is checked here now is the *next*
    boundary: no serialisation package, no API, no web surface, and above all
    no language-model adapter anywhere.
    """

    def test_no_later_package_exists(self):
        for relative in ("pgx/api", "pgx/web", "pgx/llm", "pgx/assessment",
                         "pgx/serialization"):
            with self.subTest(package=relative):
                self.assertFalse(os.path.isdir(os.path.join(REPO_ROOT,
                                                            relative)))

    def test_no_engine_module_renders_anything(self):
        present = {name for name in os.listdir(ENGINE_DIR)
                   if name.endswith(".py")}
        for name in ("reporting.py", "report.py", "structured.py",
                     "deterministic.py", "narrative.py", "render.py",
                     "templates.py"):
            with self.subTest(module=name):
                self.assertNotIn(name, present)

    def test_no_language_model_adapter_appeared(self):
        for directory in (ENGINE_DIR, APPLICATION_DIR,
                          os.path.join(REPO_ROOT, "pgx", "reporting")):
            present = {name for name in os.listdir(directory)
                       if name.endswith(".py")}
            for name in ("llm_adapter.py", "gemini.py", "openai.py",
                         "narration.py", "narrator.py", "prompt.py"):
                with self.subTest(directory=os.path.basename(directory),
                                  module=name):
                    self.assertNotIn(name, present)

    def test_no_schema_describes_a_serialised_api_response(self):
        present = sorted(os.listdir(os.path.join(REPO_ROOT, "schemas")))
        for name in present:
            with self.subTest(schema=name):
                for forbidden in ("api-", "response-", "narrative",
                                  "rendered-prose"):
                    self.assertNotIn(forbidden, name)

    def test_wp14_added_exactly_one_migration(self):
        """0010 arrived with WP-22, which persists expert review records.

        This assertion used to be "no migration beyond 0009 exists", which
        was a claim about later work packages rather than about WP-14 and
        expired as soon as one of them needed a table. WP-14's own property
        is that it contributed exactly one migration, and that its migration
        is still where the chain says it is.
        """
        versions = os.path.join(REPO_ROOT, "migrations", "versions")
        present = sorted(name for name in os.listdir(versions)
                         if name.endswith(".py") and not name.startswith("__"))
        mine = [name for name in present if "wp14" in name]
        self.assertEqual(mine, ["0009_wp14_assessments.py"])
        self.assertIn("0009_wp14_assessments.py", present)

    def test_no_ddi_or_phenoconversion_module_exists(self):
        for root, dirs, files in os.walk(os.path.join(REPO_ROOT, "pgx")):
            dirs[:] = [name for name in dirs if name != "__pycache__"]
            for name in sorted(files):
                with self.subTest(module=name):
                    for forbidden in ("ddi", "interaction", "phenoconver"):
                        self.assertNotIn(forbidden, name.lower())


if __name__ == "__main__":
    unittest.main()
