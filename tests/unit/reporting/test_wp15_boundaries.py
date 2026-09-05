# -*- coding: utf-8 -*-
"""H. What WP-15 may not do, asserted against identifiers rather than prose.

The reporting layer is a projection. The checks below are the ones that make
that a property of the code rather than a claim in a docstring: it computes
nothing, it reaches for nothing, it holds no model, it authors no sentence,
and the canonical warning exists in exactly one place in this repository.
"""

from __future__ import annotations

import ast
import os
import re
import unittest

from tests.unit.reporting._support import (APPLICATION_DIR,
                                           REPORT_APPLICATION_MODULES,
                                           REPO_ROOT, REPORTING_DIR,
                                           WP15_ENGINE_MODULES,
                                           WP15_REPORTING_MODULES,
                                           identifiers_of, imports_of,
                                           reporting_modules, source, tree,
                                           wp15_modules)

#: Everything the intended purpose puts outside this product. Checked against
#: identifiers and field names rather than prose, because the modules
#: necessarily *say* some of these words in order to refuse them.
FORBIDDEN_CONCEPTS = ("dose", "dosage", "recommend", "recommendation",
                      "preferred", "safer", "suitability", "treatment",
                      "alternative", "ranking", "prescription", "diagnos",
                      "phenoconver", "score")

#: Whole words rather than substrings, for the same reason WP-14 needed the
#: distinction: ``rank`` appears inside ``ranking`` and a substring test finds
#: words nobody wrote.
WHOLE_WORD_CONCEPTS = ("rank", "ddi")

#: Modules that legitimately name a forbidden concept because refusing it is
#: what they are for.
REFUSAL_MARKERS = ("REFUSED_FLAGS", "REPORT_FAILURE_CODES",
                   "REPORT_EXPECTED_DIFFERENCES", "NOT_PORTED",
                   "UNSAFE_NOT_ASSESSED_WORDS", "UNSAFE_LINE_TOKENS")

#: Calculation entry points no reporting module may call. Reporting reads a
#: stored assessment; it never re-runs one.
CALCULATION_SYMBOLS = ("calculate_assessment", "evaluate_coverage",
                       "evaluate_axis_finding", "aggregate_attention",
                       "match_observation", "normalize_profile",
                       "build_coverage_manifest", "AssessmentService")


def offends(name: str, concept: str) -> bool:
    lowered = name.lower()
    if concept in WHOLE_WORD_CONCEPTS:
        return re.search(r"(^|[^a-z])%s([^a-z]|$)" % concept,
                         lowered) is not None
    return concept in lowered


class TestThePackageIsWhatItSaysItIs(unittest.TestCase):

    def test_the_reporting_package_holds_exactly_these_modules(self):
        present = tuple(sorted(name for name in os.listdir(REPORTING_DIR)
                               if name.endswith(".py")))
        self.assertEqual(present, tuple(sorted(WP15_REPORTING_MODULES)))

    def test_wp15_adds_no_engine_module(self):
        """It computes nothing, so it has nothing to put in pgx/engine."""
        self.assertEqual(WP15_ENGINE_MODULES, ())

    def test_every_application_module_is_present(self):
        for name in REPORT_APPLICATION_MODULES:
            with self.subTest(module=name):
                self.assertTrue(os.path.isfile(os.path.join(APPLICATION_DIR,
                                                            name)))


class TestReportingRendersAndCalculatesNothing(unittest.TestCase):

    def test_no_module_calls_a_calculation_entry_point(self):
        for path in wp15_modules():
            names = identifiers_of(path)
            with self.subTest(module=os.path.basename(path)):
                for symbol in CALCULATION_SYMBOLS:
                    self.assertNotIn(symbol, names)

    def test_no_module_imports_an_engine_calculation(self):
        allowed = {"pgx.engine.risk_errors"}
        for path in wp15_modules():
            with self.subTest(module=os.path.basename(path)):
                for module in imports_of(path):
                    if not module.startswith("pgx.engine"):
                        continue
                    self.assertIn(module, allowed | {"pgx.engine.risk"})

    def test_only_the_read_model_reaches_the_assessment_layer(self):
        """Reporting reads one thing from WP-14: the lossless read model and
        the documents it returns."""
        allowed = {"pgx.application.assessment_read_model",
                   "pgx.application.assessment_gate_status",
                   "pgx.application.snapshot_schema"}
        for path in wp15_modules():
            with self.subTest(module=os.path.basename(path)):
                for module in imports_of(path):
                    if not module.startswith("pgx.application.assessment"):
                        continue
                    self.assertIn(module, allowed)

    def test_no_module_names_a_prohibited_concept(self):
        for path in wp15_modules():
            text = source(path)
            refuses = any(marker in text for marker in REFUSAL_MARKERS)
            names = {name.lower() for name in identifiers_of(path)}
            for forbidden in FORBIDDEN_CONCEPTS:
                with self.subTest(module=os.path.basename(path),
                                  concept=forbidden, refuses=refuses):
                    offenders = [name for name in names
                                 if offends(name, forbidden)]
                    if refuses:
                        offenders = [name for name in offenders
                                     if name.upper() not in
                                     {marker.upper()
                                      for marker in REFUSAL_MARKERS}]
                        offenders = [name for name in offenders
                                     if not name.startswith("refuse")]
                    self.assertEqual(offenders, [],
                                     "%s names %s" % (path, offenders))

    def test_no_class_or_function_names_one(self):
        for path in wp15_modules():
            for node in ast.walk(tree(path)):
                if not isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                    continue
                with self.subTest(module=os.path.basename(path),
                                  name=node.name):
                    for forbidden in FORBIDDEN_CONCEPTS:
                        self.assertFalse(offends(node.name, forbidden))

    def test_no_dataclass_field_names_one(self):
        import dataclasses
        import importlib
        for name in WP15_REPORTING_MODULES:
            if name == "__init__.py":
                continue
            module = importlib.import_module("pgx.reporting.%s"
                                             % name[:-len(".py")])
            for attribute_name in dir(module):
                attribute = getattr(module, attribute_name)
                if not dataclasses.is_dataclass(attribute):
                    continue
                if getattr(attribute, "__module__", "") != module.__name__:
                    continue
                for field in dataclasses.fields(attribute):
                    with self.subTest(type=attribute_name, field=field.name):
                        for forbidden in FORBIDDEN_CONCEPTS:
                            self.assertFalse(offends(field.name, forbidden))


class TestReportingReachesForNothing(unittest.TestCase):

    def test_it_needs_no_network(self):
        for path in wp15_modules():
            roots = {name.split(".")[0] for name in imports_of(path)}
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("requests", "httpx", "urllib", "socket",
                                  "aiohttp", "ftplib", "smtplib", "http",
                                  "ssl"):
                    self.assertNotIn(forbidden, roots)

    def test_it_imports_no_model_sdk(self):
        for path in wp15_modules():
            roots = {name.split(".")[0] for name in imports_of(path)}
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("google", "openai", "anthropic",
                                  "google_genai", "genai", "transformers",
                                  "torch"):
                    self.assertNotIn(forbidden, roots)

    def test_it_never_imports_the_legacy_generator(self):
        for path in wp15_modules():
            with self.subTest(module=os.path.basename(path)):
                self.assertNotIn("gemini_report_generator", imports_of(path))
                self.assertNotIn("risk_engine", imports_of(path))

    def test_it_reads_no_environment_variable(self):
        """Checked against identifiers, not text.

        Several of these modules *say* "environment" in a docstring, and the
        CLI names ``--api-key`` in order to refuse it. A text scan fails on
        the explanation and teaches the next person to delete it, which is
        the failure mode every boundary check in this repository is written
        to avoid.
        """
        for path in wp15_modules():
            names = identifiers_of(path)
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("getenv", "environ", "environb",
                                  "putenv", "expandvars"):
                    self.assertNotIn(forbidden, names)

    def test_no_module_reads_a_key_from_anywhere(self):
        for path in wp15_modules():
            names = identifiers_of(path)
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("API_KEY", "GEMINI_API_KEY",
                                  "OPENAI_API_KEY", "credentials",
                                  "authenticate"):
                    self.assertNotIn(forbidden, names)

    def test_the_reporting_package_needs_no_clock(self):
        """A report of one stored assessment is the same document whenever it
        is rendered, which is only true if nothing here reads a clock."""
        for path in reporting_modules():
            roots = {name.split(".")[0] for name in imports_of(path)}
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("datetime", "time", "calendar", "random",
                                  "uuid", "secrets"):
                    self.assertNotIn(forbidden, roots)

    def test_the_reporting_package_touches_no_database(self):
        for path in reporting_modules():
            roots = {name.split(".")[0] for name in imports_of(path)}
            with self.subTest(module=os.path.basename(path)):
                self.assertNotIn("sqlalchemy", roots)
                self.assertNotIn("psycopg2", roots)

    def test_only_the_artifact_writer_touches_the_filesystem(self):
        """Rendering is pure. Writing is one module, and it is named."""
        allowed = {"artifacts.py", "legacy_regression.py"}
        for path in reporting_modules():
            name = os.path.basename(path)
            if name in allowed:
                continue
            with self.subTest(module=name):
                self.assertNotIn("os", {item.split(".")[0]
                                        for item in imports_of(path)})
                self.assertNotIn("io", {item.split(".")[0]
                                        for item in imports_of(path)})


class TestTheCanonicalWarningHasOneSource(unittest.TestCase):

    #: A distinctive fragment of each canonical warning. Long enough that a
    #: paraphrase would not match it and a duplicate would.
    TR_FRAGMENT = "Eksik veri düşük risk anlamına gelmez"
    EN_FRAGMENT = "Missing data does not mean low risk"

    def test_the_warning_text_appears_in_exactly_one_module(self):
        found = []
        for root, _dirs, files in os.walk(os.path.join(REPO_ROOT, "pgx")):
            if "__pycache__" in root:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                text = source(path)
                if self.TR_FRAGMENT in text or self.EN_FRAGMENT in text:
                    found.append(os.path.relpath(path, REPO_ROOT))
        self.assertEqual(found, [os.path.join("pgx", "domain", "claims.py")])

    def test_the_reporting_package_imports_it_rather_than_writing_it(self):
        text = source(os.path.join(REPORTING_DIR, "structured.py"))
        self.assertIn("canonical_clinical_warning", text)
        self.assertNotIn(self.TR_FRAGMENT, text)

    def test_no_template_holds_a_second_warning(self):
        text = source(os.path.join(REPORTING_DIR, "templates.py"))
        self.assertNotIn(self.TR_FRAGMENT, text)
        self.assertNotIn(self.EN_FRAGMENT, text)


class TestNoAdversarialTextLivesInProduction(unittest.TestCase):
    """The prohibited sentences exist only in a test fixture."""

    def test_no_production_module_contains_one(self):
        from tests.fixtures.wp15.synthetic import ADVERSARIAL_TEXTS
        for root, _dirs, files in os.walk(os.path.join(REPO_ROOT, "pgx")):
            if "__pycache__" in root:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                text = source(os.path.join(root, name))
                for _label, _category, sentence in ADVERSARIAL_TEXTS:
                    with self.subTest(module=name, sentence=sentence[:32]):
                        self.assertNotIn(sentence, text)


class TestNoLanguageModelIsReachable(unittest.TestCase):

    def test_the_boundary_says_it_is_disabled(self):
        from pgx.reporting.llm import LLM_ENABLED, llm_boundary_contract
        contract = llm_boundary_contract()
        self.assertFalse(LLM_ENABLED)
        self.assertFalse(contract["provider_implemented"])
        self.assertFalse(contract["requires_api_key"])
        self.assertFalse(contract["requires_network"])
        self.assertFalse(contract["sends_case_content_anywhere"])

    def test_the_port_refuses(self):
        from pgx.reporting.errors import ReportError
        from pgx.reporting.llm import DisabledNarrationPort
        port = DisabledNarrationPort()
        self.assertFalse(port.is_available())
        with self.assertRaises(ReportError) as caught:
            port.narrate(object())
        self.assertEqual(caught.exception.code, "REPORT_LLM_DISABLED")

    def test_no_provider_class_exists_anywhere_in_reporting(self):
        for path in reporting_modules():
            names = identifiers_of(path)
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("GenerativeModel", "ChatCompletion",
                                  "generate_content", "complete", "Client"):
                    self.assertNotIn(forbidden, names)

    def test_the_service_produces_a_report_with_no_provider_configured(self):
        """The offline document is the report, not a fallback."""
        from tests.fixtures.wp15.synthetic import (report_world,
                                                   stored_read_model)
        from pgx.application.report_service import ReportService
        world = report_world()
        self.addCleanup(world.close)
        produced = ReportService().render_synthetic(stored_read_model(world))
        self.assertTrue(produced.markdown)
        self.assertNotIn("fallback", produced.markdown.lower())


if __name__ == "__main__":
    unittest.main()
