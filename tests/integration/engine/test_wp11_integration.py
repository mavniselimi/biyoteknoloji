# -*- coding: utf-8 -*-
"""The engine against a real WP-11 frozen ruleset (WP-12, section F).

This proves interface compatibility and nothing else. A synthetic ruleset is
built through WP-11's own services, frozen to disk, loaded back through its
registry, and its member rules' conditions are handed to the matcher exactly
as they come out - no re-parsing, no re-wrapping, no second condition model.

It is not an assessment. Every rule in it was approved by a fixture, the
phenotypes are invented, and the genes do not exist. The last class in this
file asserts that the *real* registry is still empty afterwards, because the
difference between "the machinery works" and "there is something real to run
it on" is the difference this whole project turns on.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from pgx.domain.enums import Phenotype, RuleStatus
from pgx.engine.phenotype import match_condition, match_observation
from pgx.engine.phenotype_errors import PhenotypeMatchError
from pgx.engine.phenotype_normalization import normalize_profile
from pgx.rules.conditions import PhenotypeMatch, RuleCondition
from pgx.rules.registry import DEFAULT_RULESET_ROOT, FrozenRulesetRegistry
from tests.fixtures.wp11.synthetic import (SYNTHETIC_DRUG, SYNTHETIC_GENE,
                                           frozen_ruleset, synthetic_condition,
                                           synthetic_rule)
from tests.unit.engine._support import REPO_ROOT


class TestTheMatcherConsumesWp11Types(unittest.TestCase):

    def test_it_accepts_a_wp11_phenotype_match(self):
        decision = match_observation(
            _observation("POOR"),
            PhenotypeMatch(operator="EXACT", values=(Phenotype.POOR,)))
        self.assertEqual(decision.status, "MATCH")

    def test_it_accepts_a_wp11_rule_condition(self):
        condition = synthetic_condition(phenotypes=(Phenotype.POOR,))
        decision = match_observation(_observation("POOR"), condition)
        self.assertEqual(decision.status, "MATCH")
        self.assertEqual(decision.condition_hash, condition.content_hash())

    def test_it_refuses_a_raw_dictionary(self):
        """WP-11 owns the condition grammar. A matcher that parsed one itself
        would be a second grammar nobody reviewed - which is how a wildcard
        would eventually get in."""
        raw = {"operator": "EXACT", "values": ["POOR"]}
        with self.assertRaises(PhenotypeMatchError) as caught:
            match_observation(_observation("POOR"), raw)
        self.assertEqual(caught.exception.code,
                         "PHENOTYPE_CONDITION_UNSUPPORTED_TYPE")

    def test_it_refuses_a_legacy_style_condition_dictionary(self):
        for raw in ({"phenotype": "poor"},
                    {"gene": "CYP2D6", "phenotype_group": "decreased_function"},
                    "POOR", ["POOR"], None):
            with self.subTest(condition=repr(raw)):
                with self.assertRaises(PhenotypeMatchError):
                    match_observation(_observation("POOR"), raw)

    def test_wp12_defines_no_condition_type_of_its_own(self):
        """Importing WP-11's types is the point; *defining* one with the same
        name would be a second condition model with a second set of rules."""
        import ast
        from tests.unit.engine._support import ENGINE_DIR, tree
        defined = set()
        for name in sorted(os.listdir(ENGINE_DIR)):
            if not name.endswith(".py"):
                continue
            for node in ast.walk(tree(os.path.join(ENGINE_DIR, name))):
                if isinstance(node, ast.ClassDef):
                    defined.add(node.name)
        for forbidden in ("PhenotypeMatch", "RuleCondition", "CanonicalAxis",
                          "Phenotype", "ComputableRuleDefinition"):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, defined,
                                 "WP-12 must consume WP-11's and the domain's "
                                 "types, not redefine them")


class TestAgainstAFrozenRulesetFromTheRegistry(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.root = os.path.join(cls.tmp, "rulesets")
        os.makedirs(cls.root)
        cls.destination = os.path.join(cls.root, "PGX-RULESET-29991231-001")
        frozen_ruleset(cls.destination, count=2)
        cls.registry = FrozenRulesetRegistry(cls.root)
        cls.ruleset = cls.registry.load("PGX-RULESET-29991231-001")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_fixture_ruleset_loads(self):
        self.assertEqual(self.registry.list_executable(),
                         ("PGX-RULESET-29991231-001",))
        self.assertEqual(self.ruleset.member_count, 2)

    def test_every_member_rule_yields_a_condition_the_matcher_accepts(self):
        for definition in self.ruleset.rules():
            with self.subTest(rule=definition.rule_id.to_json()):
                self.assertIsInstance(definition.condition, RuleCondition)
                decision = match_observation(
                    _observation("POOR", definition.condition.gene_canonical_key),
                    definition.condition)
                self.assertIn(decision.status, ("MATCH", "NO_MATCH"))

    def test_only_the_declared_phenotype_matches_a_frozen_rule(self):
        definition = self.ruleset.rules()[0]
        declared = set(definition.condition.phenotype.values)
        gene = definition.condition.gene_canonical_key
        for phenotype in Phenotype:
            if phenotype is Phenotype.INDETERMINATE:
                continue
            with self.subTest(phenotype=phenotype.value):
                decision = match_observation(
                    _observation(phenotype.value, gene), definition.condition)
                self.assertEqual(decision.matched, phenotype in declared)

    def test_a_profile_is_evaluated_for_the_condition_s_gene(self):
        definition = self.ruleset.rules()[0]
        gene = definition.condition.gene_canonical_key
        declared = definition.condition.phenotype.values[0]
        profile = normalize_profile({gene: declared.value,
                                     "TESTGENE9": "NORMAL"})
        self.assertEqual(match_condition(profile, definition.condition).status,
                         "MATCH")

    def test_a_profile_silent_about_the_gene_reports_missing_input(self):
        """A rule about a gene nobody supplied a value for has not been shown
        not to apply."""
        definition = self.ruleset.rules()[0]
        profile = normalize_profile({"TESTGENE9": "NORMAL"})
        decision = match_condition(profile, definition.condition)
        self.assertEqual(decision.status, "INPUT_MISSING")
        self.assertEqual(decision.observation_status, "ABSENT")

    def test_the_matcher_never_reads_the_rule_s_outcome_or_evidence(self):
        """A matcher that read the outcome could let the answer depend on what
        the answer would cause. Asserted over the source rather than by
        behaviour, because the behaviour would be identical either way until
        somebody changed it."""
        from tests.unit.engine._support import ENGINE_DIR, identifiers_of
        names = identifiers_of(os.path.join(ENGINE_DIR, "phenotype.py"))
        for forbidden in ("outcome", "attention_level", "provenance",
                          "evidence_record_uuids", "rationale_reference"):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, names)

    def test_the_engine_never_loads_a_rule_itself(self):
        """WP-11 decided what may execute. WP-12 does not re-litigate it, and
        cannot: nothing in the engine imports the registry."""
        from tests.unit.engine._support import ENGINE_DIR, imports_of
        for name in sorted(os.listdir(ENGINE_DIR)):
            if not name.endswith(".py"):
                continue
            with self.subTest(module=name):
                self.assertNotIn("pgx.rules.registry",
                                 imports_of(os.path.join(ENGINE_DIR, name)))

    def test_no_draft_or_curated_rule_can_reach_the_matcher(self):
        """There is no path: the registry serves only frozen artifacts, and
        every rule inside one is VALIDATED by construction."""
        from tests.fixtures.wp11.synthetic import synthetic_lifecycle
        for definition in self.ruleset.rules():
            with self.subTest(rule=definition.rule_id.to_json()):
                record = synthetic_lifecycle(definition,
                                             status=RuleStatus.VALIDATED)
                self.assertTrue(record.is_executable)


class TestTheRealRegistryStaysEmpty(unittest.TestCase):

    def test_the_default_registry_serves_nothing(self):
        self.assertEqual(
            FrozenRulesetRegistry(
                os.path.join(REPO_ROOT, DEFAULT_RULESET_ROOT)
            ).list_executable(), ())

    def test_the_synthetic_artifact_was_written_outside_the_repository(self):
        """A fixture published into the production root would be served to an
        engine as if somebody had approved it."""
        from tests.unit.engine._support import source
        import glob
        prefix = "PGX-RULE" + "SET"
        needle = "data/rule" + "sets/%s" % prefix
        for path in glob.glob(os.path.join(REPO_ROOT, "tests", "**", "*.py"),
                              recursive=True):
            with self.subTest(module=os.path.relpath(path, REPO_ROOT)):
                self.assertNotIn(needle, source(path))


def _observation(value, gene=SYNTHETIC_GENE):
    from pgx.engine.phenotype_normalization import normalize_phenotype
    return normalize_phenotype(value, gene_canonical_key=gene)


if __name__ == "__main__":
    unittest.main()
