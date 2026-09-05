# -*- coding: utf-8 -*-
"""Where WP-13 stops (section H).

Coverage and attention are separate first-class outputs (`architecture.md` 9.2,
9.3). WP-13 computes the first. The strongest guarantee that it never emits the
second is that there is nowhere in it to put one, and this file asserts that
absence directly: as identifiers, as dataclass fields, as schema properties and
as CLI commands, so a rename cannot smuggle one past a text search.

The other boundary asserted here is the one inside the answer. Aggregation must
be a decision table, never a comparison, because ``CoverageStatus`` has no
ordering and any code that compared two statuses would be inventing one.
``max`` and ``min`` are therefore absent from these modules entirely, and no
sort anywhere in them touches a status.
"""

from __future__ import annotations

import ast
import io
import json
import os
import unittest

from tests.unit.engine._support import (APPLICATION_DIR,
                                        COVERAGE_APPLICATION_MODULES,
                                        ENGINE_DIR, REPO_ROOT,
                                        WP13_ENGINE_MODULES, identifiers_of,
                                        imports_of, modules_of, source, tree,
                                        wp13_modules)

ALL_WP13_PATHS = wp13_modules()

WP13_SCHEMAS = ("ruleset-coverage-manifest.schema.json",
                "axis-coverage.schema.json",
                "medication-coverage.schema.json",
                "coverage-result.schema.json",
                "coverage-regression-report.schema.json",
                "wp13-gate-status.schema.json")

#: The attention separation contract, as names. No WP-13 model, schema or
#: module may contain one. The only permitted mention of attention is in
#: documentation explaining that WP-13 does not calculate it, which is why
#: this list is checked against identifiers and field names rather than prose.
FORBIDDEN_CONCEPTS = ("attention", "overall_attention", "risk", "risk_level",
                      "risk_score", "severity", "dose", "recommendation",
                      "preferred", "safer", "suitability_score", "treatment")

#: The one exemption, and it is narrow. The legacy comparison has to name the
#: legacy engine's own fields - ``legacy_overall_risk_level`` is what the WP-01
#: snapshot calls the value being corrected - and a report that could not quote
#: the field it corrects could not show the correction. A ``legacy_`` prefix
#: marks a name as a citation of the old system rather than a claim by this
#: one, so it is stripped before the check; a separate test asserts the prefix
#: appears only where a legacy comparison lives, so it cannot become a way of
#: naming a risk field in the engine itself.
LEGACY_CITATION_PREFIX = "legacy_"

#: Where a legacy citation is allowed to appear at all.
LEGACY_CITATION_MODULES = ("coverage_legacy.py",)
LEGACY_CITATION_SCHEMAS = ("coverage-regression-report.schema.json",)


def is_citation(name):
    """Whether a name is quoting the legacy engine rather than claiming.

    The whole name is exempt, not just the part after the prefix:
    ``legacy_overall_risk_level`` *is* the old system's field name, and a
    report that could only half-quote it could not show what it corrects.
    The exemption is bounded by where it may appear, not by what it says.
    """
    return name.lower().startswith(LEGACY_CITATION_PREFIX)


class TestWp13ComputesNoAttentionLevel(unittest.TestCase):

    def test_no_module_names_an_attention_concept(self):
        for path in ALL_WP13_PATHS:
            names = {name.lower() for name in identifiers_of(path)
                     if not is_citation(name)}
            for forbidden in FORBIDDEN_CONCEPTS:
                with self.subTest(module=os.path.basename(path),
                                  concept=forbidden):
                    for name in names:
                        self.assertNotIn(forbidden, name)

    def test_a_legacy_citation_appears_only_where_a_comparison_lives(self):
        """The exemption, bounded. ``legacy_`` may prefix a name in the
        legacy-comparison module and its report schema, and nowhere else -
        otherwise the prefix would become a way to call a field
        ``legacy_risk_level`` inside the engine and have it pass."""
        for path in ALL_WP13_PATHS:
            if os.path.basename(path) in LEGACY_CITATION_MODULES:
                continue
            for name in identifiers_of(path):
                with self.subTest(module=os.path.basename(path), name=name):
                    self.assertFalse(is_citation(name))

    def test_the_citation_exemption_covers_only_the_two_places_it_names(self):
        self.assertEqual(LEGACY_CITATION_MODULES, ("coverage_legacy.py",))
        self.assertEqual(LEGACY_CITATION_SCHEMAS,
                         ("coverage-regression-report.schema.json",))

    def test_a_legacy_citation_never_becomes_a_v2_field(self):
        """Inside the comparison module too, the corrected side carries no
        risk vocabulary: the report is legacy-named on one side and
        coverage-named on the other, which is what makes it a comparison."""
        from pgx.engine.coverage_legacy import build_coverage_regression_report
        report = build_coverage_regression_report(REPO_ROOT)
        for case in report["cases"]:
            for key in case:
                if key.startswith("v2_"):
                    for forbidden in FORBIDDEN_CONCEPTS:
                        with self.subTest(key=key, concept=forbidden):
                            self.assertNotIn(forbidden, key.lower())

    def test_no_module_imports_the_attention_vocabulary(self):
        for path in ALL_WP13_PATHS:
            names = identifiers_of(path)
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("AttentionLevel", "AssessmentFinding",
                                  "AssessmentResult", "CoverageAssessment",
                                  "calculate_attention", "assess",
                                  "AssessmentService", "max_attention"):
                    self.assertNotIn(forbidden, names)

    def test_no_class_or_function_names_a_later_concept(self):
        for path in ALL_WP13_PATHS:
            for node in ast.walk(tree(path)):
                if not isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                    continue
                lowered = node.name.lower()
                with self.subTest(module=os.path.basename(path),
                                  name=node.name):
                    for forbidden in ("attention", "risk", "assessment",
                                      "finding", "phenoconver", "interaction",
                                      "recommend", "rank", "score"):
                        self.assertNotIn(forbidden, lowered)

    def test_no_dataclass_field_names_one(self):
        import dataclasses
        import importlib
        for name in WP13_ENGINE_MODULES:
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
        for name in WP13_SCHEMAS:
            path = os.path.join(REPO_ROOT, "schemas", name)
            with io.open(path, encoding="utf-8") as handle:
                text = handle.read()
            document = json.loads(text)
            with self.subTest(schema=name):
                self.assertFalse(document.get("additionalProperties", True)
                                 is True and "properties" in document)
            citations_allowed = name in LEGACY_CITATION_SCHEMAS
            for key in self._properties(document):
                if is_citation(key):
                    with self.subTest(schema=name, property=key):
                        self.assertTrue(
                            citations_allowed,
                            "%s names a legacy field outside a comparison"
                            % key)
                    continue
                for forbidden in FORBIDDEN_CONCEPTS:
                    with self.subTest(schema=name, property=key,
                                      concept=forbidden):
                        self.assertNotIn(forbidden, key.lower())

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

    def test_no_coverage_status_value_is_an_attention_level(self):
        from pgx.domain.enums import AttentionLevel, CoverageStatus
        self.assertEqual({item.value for item in CoverageStatus}
                         & {item.value for item in AttentionLevel}, set())

    #: Words that make a mention of attention a denial of it. Read over a
    #: small window rather than a single line, because a sentence saying
    #: "there is no command that ... calculates attention" wraps, and the
    #: denial is usually on the line before the word.
    DENIAL_MARKERS = ("not", "no ", "none", "never", "nothing", "wp-14",
                      "separate", "nowhere", "absent", "refus", "belongs",
                      "does not", "cannot")

    def test_the_only_mention_of_attention_is_a_denial(self):
        """Prose may say what WP-13 does not do; it must say only that."""
        for path in ALL_WP13_PATHS:
            lines = source(path).lower().splitlines()
            for index, line in enumerate(lines):
                if "attention" not in line:
                    continue
                window = " ".join(lines[max(0, index - 3):index + 2])
                with self.subTest(module=os.path.basename(path),
                                  line=index + 1):
                    self.assertTrue(
                        any(marker in window
                            for marker in self.DENIAL_MARKERS),
                        "%s:%d %r" % (path, index + 1, line.strip()))


class TestAggregationIsNotAComparison(unittest.TestCase):

    def test_no_module_uses_max_or_min(self):
        """A maximum over statuses is an ordering, and an ordering over
        CoverageStatus is a severity ranking nobody declared."""
        for path in ALL_WP13_PATHS:
            names = identifiers_of(path)
            with self.subTest(module=os.path.basename(path)):
                self.assertNotIn("max", names)
                self.assertNotIn("min", names)

    def test_no_sort_anywhere_touches_a_status(self):
        """``sorted`` is used for deterministic serialisation and for nothing
        else. A sort over statuses would be a maximum with extra steps."""
        for path in ALL_WP13_PATHS:
            text = source(path)
            module = tree(path)
            for node in ast.walk(module):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                name = getattr(function, "id", getattr(function, "attr", ""))
                if name not in ("sorted", "sort"):
                    continue
                segment = ast.get_source_segment(text, node) or ""
                with self.subTest(module=os.path.basename(path),
                                  call=segment[:60]):
                    self.assertNotIn("status", segment.lower())

    def test_the_decision_tables_are_published_data(self):
        from pgx.engine.coverage import (AXIS_DECISION_TABLE,
                                         MEDICATION_DECISION_TABLE,
                                         OVERALL_DECISION_TABLE, truth_table)
        for table in (AXIS_DECISION_TABLE, MEDICATION_DECISION_TABLE,
                      OVERALL_DECISION_TABLE):
            self.assertIsInstance(table, tuple)
            self.assertTrue(table)
        published = truth_table()
        self.assertEqual(len(published["axis"]), len(AXIS_DECISION_TABLE))
        self.assertEqual(len(published["medication"]),
                         len(MEDICATION_DECISION_TABLE))
        self.assertEqual(len(published["overall"]),
                         len(OVERALL_DECISION_TABLE))
        self.assertIn("no ordering", published["note"])

    def test_the_reason_order_denies_being_a_severity_ranking(self):
        text = source(os.path.join(ENGINE_DIR, "coverage_models.py"))
        self.assertIn("not** a severity ranking", text)


class TestWp13ReachesForNothingItWasNotGiven(unittest.TestCase):

    def test_the_engine_modules_need_no_network_and_no_model(self):
        for path in ALL_WP13_PATHS:
            roots = {name.split(".")[0] for name in imports_of(path)}
            names = identifiers_of(path)
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("requests", "httpx", "urllib", "socket",
                                  "aiohttp", "openai", "anthropic",
                                  "transformers", "torch"):
                    self.assertNotIn(forbidden, roots)
                for forbidden in ("completion", "embedding", "prompt",
                                  "llm", "chat"):
                    for name in names:
                        self.assertNotIn(forbidden, name.lower())

    def test_the_engine_modules_need_no_clock(self):
        for path in modules_of(WP13_ENGINE_MODULES):
            roots = {name.split(".")[0] for name in imports_of(path)}
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("datetime", "time", "random", "uuid",
                                  "secrets", "calendar"):
                    self.assertNotIn(forbidden, roots)

    def test_the_engine_modules_persist_nothing(self):
        for path in ALL_WP13_PATHS:
            names = identifiers_of(path)
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("session", "commit", "insert", "Repository",
                                  "UnitOfWork", "engine_from_config",
                                  "sessionmaker"):
                    self.assertNotIn(forbidden, names)

    def test_no_module_reads_a_mutable_csv(self):
        for path in ALL_WP13_PATHS:
            with self.subTest(module=os.path.basename(path)):
                self.assertNotIn("csv", imports_of(path))
                self.assertNotIn(".csv", source(path))

    def test_no_module_imports_the_legacy_script(self):
        for path in ALL_WP13_PATHS:
            with self.subTest(module=os.path.basename(path)):
                self.assertNotIn("risk_engine", imports_of(path))

    def test_the_engine_layer_depends_only_on_what_is_beneath_it(self):
        allowed = ("pgx.domain", "pgx.rules", "pgx.normalization", "pgx.engine")
        for path in modules_of(WP13_ENGINE_MODULES):
            for name in imports_of(path):
                if not name.startswith("pgx."):
                    continue
                with self.subTest(module=os.path.basename(path),
                                  imported=name):
                    self.assertTrue(
                        any(name == prefix or name.startswith(prefix + ".")
                            for prefix in allowed), name)

    def test_the_engine_imports_no_application_module(self):
        for path in modules_of(WP13_ENGINE_MODULES):
            for name in imports_of(path):
                with self.subTest(module=os.path.basename(path),
                                  imported=name):
                    self.assertFalse(name.startswith("pgx.application"))

    def test_the_engine_reads_the_frozen_registry_rather_than_a_copy(self):
        """A coverage claim is a claim about one specific frozen artifact, so
        the artifact is loaded through WP-11's registry, which verifies its
        hashes, and never reconstructed from a description of it."""
        text = source(os.path.join(APPLICATION_DIR, "coverage_cli.py"))
        self.assertNotIn("FrozenRuleset(", text)
        for path in ALL_WP13_PATHS:
            with self.subTest(module=os.path.basename(path)):
                self.assertNotIn("load_frozen_ruleset", identifiers_of(path))

    def test_no_module_infers_a_phenotype_from_a_genotype(self):
        for path in ALL_WP13_PATHS:
            haystack = source(path).lower()
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("star_allele", "diplotype", "activity_score",
                                  "allele_function", "haplotype",
                                  "phenoconversion", "infer_phenotype"):
                    self.assertNotIn(forbidden, haystack)

    def test_no_module_reimplements_phenotype_equality(self):
        """WP-12 owns it. A second equality rule is a second place for RAPID
        to start meaning ULTRARAPID."""
        engine = source(os.path.join(ENGINE_DIR, "coverage.py"))
        self.assertIn("match_observation", engine)
        for path in ALL_WP13_PATHS:
            text = source(path)
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("PHENOTYPE_ALIASES", "PHENOTYPE_GROUPS",
                                  "normalize_phenotype_value",
                                  "closest_phenotype"):
                    self.assertNotIn(forbidden, text)


class TestNoModuleManufacturesApprovalOrScope(unittest.TestCase):

    def test_the_cli_offers_no_command_that_approves_anything(self):
        from pgx.application.coverage_cli import build_parser
        parser = build_parser()
        commands = set()
        for action in parser._actions:
            if getattr(action, "choices", None):
                commands.update(action.choices)
        for forbidden in ("approve-manifest", "approve", "assign-reviewer",
                          "calculate-attention", "assess", "execute",
                          "import-legacy-coverage", "publish"):
            with self.subTest(command=forbidden):
                self.assertNotIn(forbidden, commands)

    def test_the_cli_refuses_every_flag_that_would_shortcut_governance(self):
        from pgx.application.coverage_cli import (REFUSED_FLAGS,
                                                  refuse_unsafe_flags)
        for flag in ("--force", "--approve", "--as-reviewer", "--skip-evidence",
                     "--infer-scope", "--from-structural-axes", "--attention",
                     "--assume-covered", "--legacy-csv"):
            with self.subTest(flag=flag):
                self.assertIn(flag, REFUSED_FLAGS)
                self.assertIsNotNone(refuse_unsafe_flags([flag]))
                self.assertIsNotNone(refuse_unsafe_flags([flag + "=1"]))

    def test_every_refused_flag_states_why(self):
        from pgx.application.coverage_cli import REFUSED_FLAGS
        for flag, reason in REFUSED_FLAGS.items():
            with self.subTest(flag=flag):
                self.assertGreater(len(reason), 20)

    def test_abbreviations_cannot_reach_a_refused_flag(self):
        from pgx.application.coverage_cli import build_parser
        self.assertFalse(build_parser().allow_abbrev)

    def test_no_module_writes_an_approval(self):
        for path in ALL_WP13_PATHS:
            names = identifiers_of(path)
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("approve", "sign", "authorize", "grant_role",
                                  "assign_role", "self_approve"):
                    self.assertNotIn(forbidden, names)

    def test_no_module_derives_expected_scope(self):
        for path in ALL_WP13_PATHS:
            names = identifiers_of(path)
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("infer_scope", "derive_scope",
                                  "expand_scope", "scope_from_rules",
                                  "scope_from_structural_axes"):
                    self.assertNotIn(forbidden, names)

    def test_nothing_reads_structural_axes_as_a_coverage_claim(self):
        for path in ALL_WP13_PATHS:
            with self.subTest(module=os.path.basename(path)):
                self.assertNotIn("structural_axes", identifiers_of(path))

    def test_the_wp11_manifest_was_not_relabelled(self):
        """WP-11 says its structural axes are a membership inventory. WP-13
        must not have edited that sentence into a coverage claim."""
        text = source(os.path.join(REPO_ROOT, "pgx", "rules", "models.py"))
        self.assertIn("structural_axes", text)
        lowered = text.lower()
        self.assertIn("membership", lowered)
        self.assertNotIn("structural axes are the coverage", lowered)

    def test_only_validated_rules_can_support_a_claim(self):
        for path in modules_of(WP13_ENGINE_MODULES):
            text = source(path)
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("RuleStatus.DRAFT", "RuleStatus.CURATED",
                                  '"DRAFT"', '"CURATED"'):
                    self.assertNotIn(forbidden, text)


class TestTheFixturesAreMarkedAndUnreachableFromProduction(unittest.TestCase):

    FIXTURE = os.path.join(REPO_ROOT, "tests", "fixtures", "wp13",
                           "synthetic.py")

    def test_the_fixture_carries_every_synthetic_marker(self):
        from tests.fixtures.wp13.synthetic import SYNTHETIC_MARKERS
        text = source(self.FIXTURE)
        for marker in SYNTHETIC_MARKERS:
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_the_fixture_uses_no_real_gene_or_drug_name(self):
        """Checked over the fixture's *code* - its identifiers and its string
        values - rather than its prose. The module docstring says why it uses
        invented entities, and naming them in order to refuse them is the
        opposite of the failure this guards against: a fixture that declared
        coverage for a real gene would read as a claim about it, and
        screenshots of tests outlive their context.
        """
        module = tree(self.FIXTURE)
        used = {name.lower() for name in identifiers_of(self.FIXTURE)}
        docstring = ast.get_docstring(module, clean=False)
        for node in ast.walk(module):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value == docstring:
                    continue
                used.add(node.value.lower())
        haystack = " ".join(sorted(used))
        for forbidden in ("cyp2d6", "cyp2c19", "cyp2c9", "cyp3a4", "cyp1a2",
                          "clopidogrel", "warfarin", "codeine", "tamoxifen"):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, haystack)

    def test_no_production_module_imports_a_fixture(self):
        for path in ALL_WP13_PATHS:
            for name in imports_of(path):
                with self.subTest(module=os.path.basename(path),
                                  imported=name):
                    self.assertFalse(name.startswith("tests."))

    def test_no_production_module_names_the_fixture_directory(self):
        for path in ALL_WP13_PATHS:
            text = source(path)
            with self.subTest(module=os.path.basename(path)):
                self.assertNotIn("tests/fixtures", text)
                self.assertNotIn("fixtures/wp13", text)

    def test_the_default_production_path_scans_no_fixture(self):
        from pgx.application.coverage_gate_status import (
            DEFAULT_COVERAGE_ROOT, build_coverage_gate_status)
        self.assertEqual(DEFAULT_COVERAGE_ROOT,
                         os.path.join("data", "coverage"))
        status = build_coverage_gate_status(REPO_ROOT).to_json()
        self.assertEqual(status["coverage_state"]["real_coverage_manifests"],
                         0)


class TestWp15AndLaterWereNotStarted(unittest.TestCase):
    """The boundary in front of WP-13, one work package later.

    This class used to assert that WP-14 had not been started. WP-14 has been,
    so the assertions naming ``risk.py`` and counting the application layer at
    three modules are obsolete and have been replaced - by an inventory that
    names what WP-14 legitimately added and continues to refuse what WP-15 and
    beyond will own. Everything else in this file is unchanged: WP-13's own
    modules are still held to naming no attention vocabulary at all.
    """

    def test_no_later_package_exists(self):
        #: ``pgx/reporting`` left this list when WP-15 created it. The
        #: property it stood for - WP-13 computes coverage and renders
        #: nothing - is asserted directly by this file's own per-module
        #: checks, which run over WP-13's modules only.
        for relative in ("pgx/assessment", "pgx/api", "pgx/web", "pgx/llm"):
            with self.subTest(package=relative):
                self.assertFalse(os.path.isdir(os.path.join(REPO_ROOT,
                                                            relative)))

    def test_no_wp15_module_appeared_in_the_engine(self):
        """Rendering belongs to WP-15 and to its own package. An engine that
        rendered would be deciding how its own facts read."""
        present = {name for name in os.listdir(ENGINE_DIR)
                   if name.endswith(".py")}
        for forbidden in ("assessment.py", "attention.py", "aggregation.py",
                          "findings.py", "reporting.py", "report.py",
                          "structured.py", "deterministic.py",
                          "narrative.py", "templates.py"):
            with self.subTest(module=forbidden):
                self.assertNotIn(forbidden, present)

    def test_wp13_added_exactly_three_application_modules(self):
        """WP-13's three are present, and no *coverage* service exists:
        evaluating coverage transitions nothing, so there is no audited state
        change for one to drive. WP-14's modules are expected now and are
        checked by their own inventory."""
        present = {name for name in os.listdir(APPLICATION_DIR)
                   if name.endswith(".py")}
        for name in COVERAGE_APPLICATION_MODULES:
            with self.subTest(module=name):
                self.assertIn(name, present)
        # ``report_service.py`` left this list when WP-15 created it; a
        # coverage *service* is still refused, because evaluating coverage
        # transitions nothing and a service implies an audited state change.
        for forbidden in ("coverage_service.py", "attention_cli.py",
                          "reporting_cli.py", "llm_adapter.py"):
            with self.subTest(module=forbidden):
                self.assertNotIn(forbidden, present)

    def test_no_migration_was_added_for_wp13(self):
        """Evaluating coverage transitions nothing, so WP-13 added none.

        0009 belongs to WP-14, which persists a calculated assessment, and
        0010 to WP-22, which persists review records. The half of this
        assertion that said "nothing beyond 0009" was a statement about
        *other* work packages and expired the moment one of them shipped a
        migration. The durable half is that WP-13 acquired no state of its
        own, which is what the successor checks."""
        versions = os.path.join(REPO_ROOT, "migrations", "versions")
        present = sorted(name for name in os.listdir(versions)
                         if name.endswith(".py") and not name.startswith("__"))
        for name in present:
            with self.subTest(migration=name):
                self.assertNotIn("wp13", name)

    def test_no_earlier_package_imports_the_engine(self):
        # ``infrastructure`` left this list when WP-14 added the assessment
        # adapter, which maps engine result types into rows. That is the
        # dependency running in the correct direction; the reverse is asserted
        # in ``test_the_engine_imports_no_application_module``.
        for package in ("domain", "normalization", "scientific", "ingestion",
                        "evidence", "curation", "rules"):
            directory = os.path.join(REPO_ROOT, "pgx", package)
            for root, dirs, files in os.walk(directory):
                dirs[:] = [name for name in dirs if name != "__pycache__"]
                for name in sorted(files):
                    if not name.endswith(".py"):
                        continue
                    path = os.path.join(root, name)
                    with self.subTest(module=os.path.relpath(path, REPO_ROOT)):
                        for imported in imports_of(path):
                            self.assertFalse(imported.startswith("pgx.engine"))


class TestNoModuleMakesAClinicalClaim(unittest.TestCase):

    #: Phrases that would be a claim rather than a description. Deliberately
    #: not "no risk" or "low risk": those appear inside denials - "there is no
    #: attention level here, no risk score" - and a check that failed on a
    #: sentence saying the system makes no claim would push the denial out of
    #: the file rather than the claim.
    FORBIDDEN_PHRASES = ("is safe", "safe to", "safe for", "recommended dose",
                         "should be prescribed", "contraindicated",
                         "clinically validated", "approved by",
                         "treatment recommendation", "is preferred",
                         "is suitable")

    def test_no_module_states_a_clinical_claim(self):
        for path in ALL_WP13_PATHS:
            text = source(path).lower()
            for phrase in self.FORBIDDEN_PHRASES:
                with self.subTest(module=os.path.basename(path),
                                  phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_no_module_declares_a_dose_or_a_medication_list(self):
        for path in ALL_WP13_PATHS:
            names = identifiers_of(path)
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("DOSES", "MEDICATIONS", "DRUG_LIST",
                                  "RECOMMENDATIONS", "dose_for",
                                  "ALTERNATIVES"):
                    self.assertNotIn(forbidden, names)

    def test_no_published_artifact_claims_a_real_coverage_manifest(self):
        for relative in (os.path.join("data", "coverage",
                                      "wp13-real-gate-status.json"),
                         os.path.join("data", "migration", "wp13",
                                      "coverage-regression-report.json")):
            path = os.path.join(REPO_ROOT, relative)
            with io.open(path, encoding="utf-8") as handle:
                text = handle.read().lower()
            with self.subTest(artifact=relative):
                for phrase in ("is safe", "clinically validated",
                               "recommended"):
                    self.assertNotIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
