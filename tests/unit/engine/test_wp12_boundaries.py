# -*- coding: utf-8 -*-
"""Where WP-12 stops, and what it left intact (section H).

The engine package answers one question. This file asserts that it has not
quietly started answering others, that nothing earlier in the pipeline now
depends on it, and that the work packages in front of it have not been begun.

The dependency direction matters as much here as anywhere: WP-12 reads WP-11's
conditions and the domain's phenotype vocabulary, and nothing below it may
read WP-12. A curation module that could import the engine would be a
scientific conclusion shaped by what a matcher needed it to say.
"""

from __future__ import annotations

import ast
import os
import unittest

from tests.unit.engine._support import (APPLICATION_DIR,
                                        ASSESSMENT_APPLICATION_MODULES,
                                        COVERAGE_APPLICATION_MODULES,
                                        ENGINE_APPLICATION_MODULES, ENGINE_DIR,
                                        REPO_ROOT, WP12_ENGINE_MODULES,
                                        WP13_ENGINE_MODULES,
                                        WP14_ENGINE_MODULES, engine_modules,
                                        identifiers_of, imports_of,
                                        modules_of, source, tree,
                                        wp12_modules)

#: WP-12's own modules. The checks that say what *WP-12* must not become are
#: run over exactly these, because running them over WP-13's coverage modules
#: would assert that a coverage engine contains no coverage - which is not a
#: boundary, it is a contradiction, and the usual way of resolving it is to
#: delete the boundary.
ALL_WP12_PATHS = wp12_modules()

#: Every module in the engine layer and its application surface, whoever wrote
#: it. The checks that apply to the layer rather than to one work package -
#: no network, no clock, no framework, no mutable CSV, no genotype inference,
#: no clinical claim - are run over these, so WP-13 is held to them too and a
#: WP-14 module will be the day it appears.
ALL_ENGINE_PATHS = (engine_modules()
                    + modules_of(ENGINE_APPLICATION_MODULES, APPLICATION_DIR)
                    + modules_of(COVERAGE_APPLICATION_MODULES,
                                 APPLICATION_DIR)
                    + modules_of(ASSESSMENT_APPLICATION_MODULES,
                                 APPLICATION_DIR))

#: The engine layer minus WP-14. Used by the checks that assert *this* layer
#: names no attention or assessment concept - which WP-14's modules
#: legitimately do, since calculating attention is what WP-14 is for.
ENGINE_PATHS_BEFORE_WP14 = [
    path for path in ALL_ENGINE_PATHS
    if os.path.basename(path) not in
    (WP14_ENGINE_MODULES + ASSESSMENT_APPLICATION_MODULES)]


class TestTheEnginePackageStaysInItsLayer(unittest.TestCase):

    #: What the engine is allowed to depend on. WP-11 for the condition
    #: grammar, WP-07 for gene normalisation, the domain for the phenotype
    #: vocabulary and hashing. Everything else is either above it or beside it.
    ALLOWED_PGX_PREFIXES = ("pgx.domain", "pgx.rules", "pgx.normalization",
                            "pgx.engine")

    def test_it_depends_only_on_layers_beneath_it(self):
        for path in engine_modules():
            for name in imports_of(path):
                if not name.startswith("pgx."):
                    continue
                with self.subTest(module=os.path.basename(path),
                                  imported=name):
                    self.assertTrue(
                        any(name == prefix or name.startswith(prefix + ".")
                            for prefix in self.ALLOWED_PGX_PREFIXES),
                        "%s imports %s" % (path, name))

    def test_it_imports_no_application_module(self):
        for path in engine_modules():
            for name in imports_of(path):
                with self.subTest(module=os.path.basename(path),
                                  imported=name):
                    self.assertFalse(name.startswith("pgx.application"))

    def test_it_imports_no_infrastructure_and_no_framework(self):
        for path in ALL_ENGINE_PATHS:
            imported = imports_of(path)
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("sqlalchemy", "alembic", "fastapi", "flask",
                                  "django", "pydantic", "psycopg2"):
                    self.assertNotIn(forbidden, imported)

    def test_it_needs_no_network(self):
        for path in ALL_ENGINE_PATHS:
            roots = {name.split(".")[0] for name in imports_of(path)}
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("requests", "httpx", "urllib", "socket",
                                  "aiohttp", "ftplib", "smtplib", "http"):
                    self.assertNotIn(forbidden, roots)

    #: Modules that legitimately hold a clock. The assessment service records
    #: *when* a run happened, which is a fact about the run and not about the
    #: case - so it is excluded from the output hash rather than from the
    #: codebase. The property the clock ban protects is asserted directly by
    #: ``test_the_clock_cannot_reach_a_calculated_fact`` below and by the
    #: determinism tests, which run one input under different injected clocks
    #: and compare hashes.
    #: ``assessment_read_model.py`` joins it for WP-15's preflight: it
    #: *formats* the timestamps a stored row already holds, and reads none. The
    #: distinction is asserted rather than assumed by
    #: ``test_the_read_model_reads_no_clock`` below.
    #: A service stamps when a result was produced; a matcher must not. The
    #: candidate service is exempt for the same reason ``assessment_service``
    #: is - it records ``computed_at`` on the result and nothing else - and the
    #: candidate release module because a release manifest records instants.
    #: Neither clock reaches the evaluation:
    #: ``pgx/engine/candidate_evaluation.py`` is not exempt and imports none.
    CLOCK_BEARING_MODULES = ("assessment_service.py",
                             "assessment_read_model.py",
                             "candidate_assessment_service.py",
                             "candidate_release.py")

    def test_it_needs_no_clock(self):
        """A matcher whose answer could depend on when it ran would make an
        assessment irreproducible."""
        for path in ALL_ENGINE_PATHS:
            if os.path.basename(path) in self.CLOCK_BEARING_MODULES:
                continue
            roots = {name.split(".")[0] for name in imports_of(path)}
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("datetime", "time", "calendar", "random",
                                  "uuid", "secrets"):
                    self.assertNotIn(forbidden, roots)

    def test_the_read_model_reads_no_clock(self):
        """It formats stored timestamps; it never asks what time it is.

        A read model that consulted a clock could produce two different views
        of one immutable stored assessment, which is the whole failure the
        clock ban exists to prevent - and it would do so in the layer a report
        is rendered from, where nobody would look for it.
        """
        text = source(os.path.join(APPLICATION_DIR, "assessment_read_model.py"))
        for forbidden in ("now(", "utcnow(", "today(", "time.time",
                          "monotonic", "perf_counter"):
            with self.subTest(call=forbidden):
                self.assertNotIn(forbidden, text)

    def test_the_clock_cannot_reach_a_calculated_fact(self):
        """The engine that computes the facts holds no clock at all, and the
        service that holds one declares it excluded from the hash."""
        from pgx.engine.risk import engine_contract
        for path in modules_of(WP14_ENGINE_MODULES):
            roots = {name.split(".")[0] for name in imports_of(path)}
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("datetime", "time", "random", "secrets"):
                    self.assertNotIn(forbidden, roots)
        excluded = engine_contract()["excluded_from_output_hash"]
        for name in ("created_at", "wall-clock time", "runtime duration",
                     "actor", "assessment_id"):
            with self.subTest(excluded=name):
                self.assertIn(name, excluded)

    def test_no_module_evaluates_a_string_or_a_regular_expression(self):
        """``re`` is absent entirely: a regular expression over an input value
        is one edit away from becoming a matcher."""
        for path in ALL_ENGINE_PATHS:
            names = identifiers_of(path)
            roots = {name.split(".")[0] for name in imports_of(path)}
            with self.subTest(module=os.path.basename(path)):
                self.assertNotIn("re", roots)
                for forbidden in ("eval", "exec", "compile", "difflib",
                                  "SequenceMatcher", "get_close_matches",
                                  "fnmatch", "levenshtein"):
                    self.assertNotIn(forbidden, names)

    def test_production_engine_code_does_not_import_the_legacy_script(self):
        for path in engine_modules():
            with self.subTest(module=os.path.basename(path)):
                self.assertNotIn("risk_engine", imports_of(path))

    #: A module may name a mutable-CSV path when it does so in order to
    #: *detect* one. ``risk_legacy`` scans the V2 calculation modules for
    #: exactly that string and reports the absence as migration evidence; a
    #: check that forbade it there would remove the scanner rather than the
    #: dependency. The same shape as the genotype refusal below.
    CSV_REFUSAL_MARKERS = ("_legacy_reads_mutable_csv", "v2_csv_modules")

    def test_the_engine_reads_no_mutable_csv(self):
        for path in ALL_ENGINE_PATHS:
            text = source(path)
            detects = any(marker in text
                          for marker in self.CSV_REFUSAL_MARKERS)
            with self.subTest(module=os.path.basename(path),
                              detects=detects):
                self.assertNotIn("csv", imports_of(path))
                if not detects:
                    self.assertNotIn(".csv", text)

    def test_the_csv_scanner_still_finds_nothing(self):
        """The exemption above is worth having only while the scan it protects
        actually passes."""
        from pgx.engine.risk_legacy import build_assessment_regression_report
        report = build_assessment_regression_report(REPO_ROOT)
        case = [item for item in report["cases"]
                if item["case_id"] == "BEHAVIOUR-mutable-csv"][0]
        self.assertIn("0 of", case["v2_explanation"])


class TestWp14AndLaterWereNotStarted(unittest.TestCase):
    """The boundary in front of the engine, one work package later.

    This class used to be named for WP-13 as well. WP-13 has since been
    implemented, so the assertion that ``coverage.py`` is physically absent is
    obsolete and has been replaced - by an inventory that names the modules
    WP-13 legitimately added and continues to refuse the ones WP-14 will own.
    Nothing else about the boundary moved: the per-module checks below still
    run over WP-12's modules only, so "WP-12 names no coverage concept" is
    still asserted about WP-12 rather than quietly asserted about nobody.
    """

    #: ``pgx/reporting`` left this list when WP-15 created it, on the same
    #: terms ``coverage.py`` and ``risk.py`` left the module list below. What
    #: it stood for - the engine renders nothing - is still asserted, by
    #: ``FORBIDDEN_ENGINE_MODULES`` here and by WP-15's own boundary file,
    #: which asserts the converse: the reporting package calculates nothing.
    FORBIDDEN_PACKAGES = ("pgx/assessment", "pgx/api", "pgx/web", "pgx/llm")

    #: Modules a later work package would own. ``coverage.py`` left this list
    #: when WP-13 created it and ``risk.py`` left it when WP-14 did; what they
    #: stood for - the engine answers one question at a time - is carried by
    #: the inventory below and by each work package's own boundary file.
    #: ``reporting.py`` is here now: rendering is WP-15's, and an engine that
    #: rendered would be deciding how its own facts read.
    FORBIDDEN_ENGINE_MODULES = ("assessment.py", "attention.py",
                                "aggregation.py", "reporting.py",
                                "report.py", "narrative.py")

    #: Concepts belonging to later work packages, checked as identifiers so a
    #: rename cannot smuggle one in. ``CoverageStatus`` and the coverage names
    #: stay on this list: they are checked against WP-12's modules, where they
    #: are still as out of place as they ever were.
    FORBIDDEN_NAMES = ("AssessmentFinding", "CoverageAssessment",
                       "CoverageStatus", "AttentionLevel", "assess",
                       "calculate_attention", "calculate_coverage",
                       "aggregate", "max_attention", "phenoconvert",
                       "Phenoconversion", "DrugInteraction", "recommend",
                       "AssessmentService")

    def test_no_later_package_exists(self):
        for relative in self.FORBIDDEN_PACKAGES:
            with self.subTest(package=relative):
                self.assertFalse(
                    os.path.isdir(os.path.join(REPO_ROOT, relative)),
                    "%s exists" % relative)

    def test_the_engine_package_holds_only_wp12_to_wp14_modules(self):
        """The inventory, enumerated rather than counted.

        An exact set rather than a maximum: a module nobody meant to add fails
        this test as loudly as a forbidden one, which is the property that
        makes the check worth keeping now that the package has three owners.
        """
        present = {name for name in os.listdir(ENGINE_DIR)
                   if name.endswith(".py")}
        self.assertEqual(
            present,
            {"__init__.py"} | set(WP12_ENGINE_MODULES)
            | set(WP13_ENGINE_MODULES) | set(WP14_ENGINE_MODULES))
        for forbidden in self.FORBIDDEN_ENGINE_MODULES:
            with self.subTest(module=forbidden):
                self.assertNotIn(forbidden, present)

    def test_no_wp12_module_names_a_later_concept(self):
        for path in ALL_WP12_PATHS:
            names = identifiers_of(path)
            for forbidden in self.FORBIDDEN_NAMES:
                with self.subTest(module=os.path.basename(path),
                                  name=forbidden):
                    self.assertNotIn(forbidden, names)

    def test_no_wp12_module_defines_a_coverage_or_attention_type(self):
        for path in ALL_WP12_PATHS:
            for node in ast.walk(tree(path)):
                if not isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                    continue
                lowered = node.name.lower()
                with self.subTest(module=os.path.basename(path),
                                  name=node.name):
                    for forbidden in ("coverage", "attention", "risk",
                                      "assessment", "finding", "aggregate"):
                        self.assertNotIn(forbidden, lowered)

    def test_no_pre_wp14_engine_module_defines_an_attention_or_risk_type(self):
        """The half of the check above that outlived WP-12.

        WP-13 may name coverage; it may not name attention, risk, an
        assessment or a finding. WP-14's own modules are excluded, because
        calculating attention from governed rule outcomes is precisely what
        WP-14 is for and a check forbidding it there would be asserting that
        an assessment engine contains no assessment. What WP-14 must not
        contain is checked in ``test_wp14_boundaries.py`` instead: no dose, no
        recommendation, no ranking, no report prose.
        """
        for path in ENGINE_PATHS_BEFORE_WP14:
            for node in ast.walk(tree(path)):
                if not isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                    continue
                lowered = node.name.lower()
                with self.subTest(module=os.path.basename(path),
                                  name=node.name):
                    for forbidden in ("attention", "risk", "assessment",
                                      "finding", "severity", "recommend"):
                        self.assertNotIn(forbidden, lowered)

    #: The one module that may drive a transaction. Persisting a calculated
    #: assessment is an application responsibility and WP-14's service is
    #: where it lives - through an injected unit-of-work port, so the service
    #: names ``commit`` and knows nothing about a database. Every engine
    #: module remains unable to persist anything, which is what the check
    #: below asserts.
    PERSISTENCE_ORCHESTRATING_MODULES = ("assessment_service.py",)

    def test_nothing_in_this_layer_persists_anything(self):
        for path in ALL_ENGINE_PATHS:
            if os.path.basename(path) in \
                    self.PERSISTENCE_ORCHESTRATING_MODULES:
                continue
            names = identifiers_of(path)
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("session", "commit", "insert", "Repository",
                                  "UnitOfWork", "engine_from_config"):
                    self.assertNotIn(forbidden, names)

    def test_the_orchestrating_module_still_touches_no_database(self):
        """It drives a transaction through a port and imports no ORM, no
        driver and no session factory."""
        for name in self.PERSISTENCE_ORCHESTRATING_MODULES:
            path = os.path.join(APPLICATION_DIR, name)
            imported = imports_of(path)
            with self.subTest(module=name):
                for forbidden in ("sqlalchemy", "psycopg2",
                                  "pgx.infrastructure.db.models",
                                  "pgx.infrastructure.db.session"):
                    self.assertNotIn(forbidden, imported)
                for value in imported:
                    self.assertFalse(value.startswith("pgx.infrastructure"))

    def test_no_migration_was_added_for_wp12_or_wp13(self):
        """Phenotype matching and coverage evaluation are pure operations over
        values. A migration would mean something here had acquired state, and
        neither work package has: WP-13 reads a manifest it is handed and
        writes nothing back.

        WP-14 *does* persist, so migration 0009 exists and is expected, and
        WP-22 persists review records, so 0010 exists too. Pinning the total
        was the wrong way to state this: it made every later work package's
        legitimate migration look like a WP-12 violation. What WP-12 owns is
        that **no migration is named for it**, so the successor checks that
        instead, and the count follows from the directory."""
        versions = os.path.join(REPO_ROOT, "migrations", "versions")
        present = sorted(name for name in os.listdir(versions)
                         if name.endswith(".py") and not name.startswith("__"))
        for name in present:
            with self.subTest(migration=name):
                self.assertNotIn("wp12", name)
                self.assertNotIn("wp13", name)


class TestNoGenotypeInferenceAnywhere(unittest.TestCase):

    #: Markers that a mention of a genotype concept is a *refusal* of it.
    #: ``GENOTYPE_MARKERS`` is the normaliser's refusal table;
    #: ``--infer-from-genotype`` is the CLI flag that does not exist. Both name
    #: the concept in order to reject it, and neither can cause a value to be
    #: accepted.
    #: ``REFUSED_INPUT_FIELDS`` joins this list for WP-14: the assessment
    #: input contract names ``diplotype``, ``star_allele`` and
    #: ``activity_score`` in order to *refuse* a request carrying one, and a
    #: check that forbade the words there would delete the refusal rather than
    #: the capability.
    #: ``FORBIDDEN_SNAPSHOT_KEYS`` joins it for WP-15's preflight, on exactly
    #: the same terms: the stored input snapshot names ``genotype``,
    #: ``diplotype`` and ``star_allele`` in order to *refuse a snapshot that
    #: carries one*, and forbidding the words there would delete the scan
    #: rather than the capability.
    REFUSAL_MARKERS = ("GENOTYPE_MARKERS", "GENOTYPE_NOT_ALLOWED",
                       "--infer-from-genotype", "REFUSED_INPUT_FIELDS",
                       "FORBIDDEN_SNAPSHOT_KEYS")

    def test_no_module_names_a_genotype_concept_except_to_refuse_it(self):
        """A module may mention diplotypes only in order to reject them.

        Checked as identifiers rather than as text for the modules that carry
        a refusal, because their prose necessarily says the words: the risk is
        code that *reads* a genotype, not a sentence explaining that nothing
        does.
        """
        for path in ALL_ENGINE_PATHS:
            text = source(path)
            refuses = any(marker in text for marker in self.REFUSAL_MARKERS)
            haystack = (" ".join(sorted(identifiers_of(path))) if refuses
                        else text)
            with self.subTest(module=os.path.basename(path),
                              refuses=refuses):
                for forbidden in ("star_allele", "diplotype", "activity_score",
                                  "allele_function", "haplotype"):
                    self.assertNotIn(forbidden, haystack.lower())

    def test_no_module_maps_an_allele_to_a_phenotype(self):
        for path in ALL_ENGINE_PATHS:
            names = identifiers_of(path)
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("ALLELE_FUNCTIONS", "ACTIVITY_SCORES",
                                  "DIPLOTYPE_TABLE", "infer_phenotype",
                                  "phenotype_from_genotype"):
                    self.assertNotIn(forbidden, names)


class TestNoModuleMakesAClinicalClaim(unittest.TestCase):

    #: Phrases that would be a claim rather than a comparison. Checked over
    #: the source of every WP-12 module, including its comments: a sentence in
    #: a docstring is read by more people than most code.
    FORBIDDEN_PHRASES = ("is safe", "safe to", "recommended dose",
                         "should be prescribed", "contraindicated",
                         "clinically validated", "approved by",
                         "treatment recommendation")

    def test_no_module_states_a_clinical_claim(self):
        for path in ALL_ENGINE_PATHS:
            text = source(path).lower()
            for phrase in self.FORBIDDEN_PHRASES:
                with self.subTest(module=os.path.basename(path),
                                  phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_no_module_declares_a_dose_or_a_medication_list(self):
        for path in ALL_ENGINE_PATHS:
            names = identifiers_of(path)
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("DOSES", "MEDICATIONS", "DRUG_LIST",
                                  "RECOMMENDATIONS", "dose_for"):
                    self.assertNotIn(forbidden, names)


class TestTheEarlierWorkPackagesAreIntact(unittest.TestCase):

    #: Every package that existed before WP-12. None may import the engine:
    #: the pipeline runs one way, and a curated conclusion shaped by what a
    #: matcher needed it to say would invert it.
    #: ``infrastructure`` left this list when WP-14 created
    #: ``pgx/infrastructure/db/assessments.py``: persisting a calculated
    #: assessment means mapping the engine's result types, which is the
    #: dependency running in the correct direction - infrastructure adapts to
    #: the domain and engine above it, and nothing in the engine imports
    #: infrastructure back. The reverse direction is asserted separately.
    EARLIER_PACKAGES = ("domain", "normalization", "scientific", "ingestion",
                        "evidence", "curation", "rules")

    def test_no_earlier_package_imports_the_engine(self):
        for package in self.EARLIER_PACKAGES:
            directory = os.path.join(REPO_ROOT, "pgx", package)
            for root, dirs, files in os.walk(directory):
                dirs[:] = [name for name in dirs if name != "__pycache__"]
                for name in sorted(files):
                    if not name.endswith(".py"):
                        continue
                    path = os.path.join(root, name)
                    with self.subTest(module=os.path.relpath(path, REPO_ROOT)):
                        for imported in imports_of(path):
                            self.assertFalse(
                                imported == "pgx.engine"
                                or imported.startswith("pgx.engine."),
                                "%s imports %s" % (path, imported))

    def test_no_earlier_application_module_imports_the_engine(self):
        for name in sorted(os.listdir(APPLICATION_DIR)):
            if not name.endswith(".py") or name in (
                    ENGINE_APPLICATION_MODULES
                    + COVERAGE_APPLICATION_MODULES
                    + ASSESSMENT_APPLICATION_MODULES):
                continue
            with self.subTest(module=name):
                for imported in imports_of(os.path.join(APPLICATION_DIR,
                                                        name)):
                    self.assertFalse(imported.startswith("pgx.engine"))

    def test_the_wp09_protocol_is_still_awaiting_review(self):
        import io as _io
        import json as _json
        path = os.path.join(REPO_ROOT, "config", "curation",
                            "protocol-v1.json")
        with _io.open(path, encoding="utf-8") as handle:
            document = _json.load(handle)
        self.assertEqual(document["status"], "AWAITING_EXPERT_REVIEW")

    def test_the_default_rule_registry_is_still_empty(self):
        from pgx.rules.registry import DEFAULT_RULESET_ROOT, FrozenRulesetRegistry
        self.assertEqual(
            FrozenRulesetRegistry(
                os.path.join(REPO_ROOT, DEFAULT_RULESET_ROOT)
            ).list_executable(), ())

    def test_the_wp11_gate_status_still_reports_zero_real_rules(self):
        from pgx.application.rule_gate_status import build_gate_status
        state = build_gate_status(REPO_ROOT).to_json()["rule_state"]
        for name, value in state.items():
            with self.subTest(count=name):
                self.assertEqual(value, 0)


if __name__ == "__main__":
    unittest.main()
