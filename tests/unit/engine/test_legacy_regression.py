# -*- coding: utf-8 -*-
"""The legacy P1-P6 comparison (WP-12, section G).

Two things are proved here. The transcription of legacy behaviour in
``phenotype_legacy`` still matches what ``risk_engine`` actually does - checked
by importing the real module, which a test may do and production code may not.
And the comparison it drives is deterministic, complete over P1-P6, and
explains every difference it finds.

``LEGACY-BUG-001`` gets its own class. The demo profiles contain no RAPID
value, which is precisely why WP-01 registered the bug without a selector
rather than fabricating one; the report supplies the missing direction as a
clearly-labelled constructed case instead.
"""

from __future__ import annotations

import hashlib
import os
import io
import json
import unittest

from pgx.domain.enums import Phenotype
from pgx.engine.phenotype import match_observation
from pgx.engine.phenotype_legacy import (EXPECTED_DIFFERENCES,
                                         LEGACY_MATCH_GROUPS,
                                         build_regression_report,
                                         expected_difference_allowlist,
                                         legacy_matches,
                                         legacy_normalize_profile_phenotype,
                                         load_demo_profiles)
from pgx.engine.phenotype_normalization import normalize_phenotype
from tests.fixtures.wp12.synthetic import exact, one_of
from tests.unit.engine._support import (LEGACY_PROFILES, REGRESSION_ALLOWLIST,
                                        REGRESSION_REPORT, REPO_ROOT, source)

#: What the legacy demo profiles contain, pinned. A change is a change to a
#: WP-01 protected artifact and should fail loudly.
EXPECTED_PROFILES = ("P1_normal", "P2_cyp2c19_poor", "P3_cyp2d6_poor",
                     "P4_cyp2d6_ultrarapid", "P5_cyp2c9_decreased",
                     "P6_mixed_high_attention")


class TestTheLegacyTranscriptionIsFaithful(unittest.TestCase):
    """``pgx/engine`` may not import the legacy script, so it transcribes the
    behaviour. This test imports the real thing and checks the transcription
    still agrees - if somebody edits the legacy table, this fails rather than
    the comparison quietly describing behaviour legacy no longer has."""

    def test_the_match_group_table_matches_the_real_one(self):
        import risk_engine
        self.assertEqual(
            {key: set(value) for key, value in LEGACY_MATCH_GROUPS.items()},
            {key: set(value)
             for key, value in risk_engine.PROFILE_MATCH_GROUPS.items()})

    def test_the_normalizer_agrees_over_every_value_the_report_uses(self):
        import risk_engine
        values = ["poor", "intermediate", "normal", "rapid", "ultrarapid",
                  "POOR", " Poor ", "pm", "im", "nm", "rm", "um",
                  "poor metabolizer", "zayıf", "hızlı", "decreased_function",
                  "decreased", "ultra-rapid", "poor response", "unknown", "",
                  "normal function", "ULTRA RAPID"]
        for value in values:
            with self.subTest(value=repr(value)):
                self.assertEqual(
                    legacy_normalize_profile_phenotype(value),
                    risk_engine.normalize_profile_phenotype(value))

    def test_the_matcher_agrees_over_every_pair_the_report_uses(self):
        import risk_engine
        left = ["poor", "intermediate", "normal", "rapid", "ultrarapid",
                "decreased_function", "unknown", ""]
        right = ["poor", "intermediate", "normal", "rapid", "ultrarapid",
                 "decreased_function"]
        for profile_value in left:
            for rule_group in right:
                with self.subTest(profile=profile_value, rule=rule_group):
                    self.assertEqual(
                        legacy_matches(profile_value, rule_group),
                        risk_engine.phenotype_matches(profile_value,
                                                      rule_group))

    def test_production_engine_code_does_not_import_the_legacy_script(self):
        from tests.unit.engine._support import ENGINE_DIR, imports_of
        import os
        for name in sorted(os.listdir(ENGINE_DIR)):
            if not name.endswith(".py"):
                continue
            with self.subTest(module=name):
                self.assertNotIn("risk_engine",
                                 imports_of(os.path.join(ENGINE_DIR, name)))


class TestLegacyBug001IsReproducedAndFixed(unittest.TestCase):

    def test_legacy_lets_rapid_satisfy_an_ultrarapid_rule(self):
        self.assertTrue(legacy_matches("rapid", "ultrarapid"))

    def test_legacy_lets_ultrarapid_satisfy_a_rapid_rule(self):
        self.assertTrue(legacy_matches("ultrarapid", "rapid"))

    def test_v2_refuses_both_directions(self):
        for observed, declared in ((Phenotype.RAPID, Phenotype.ULTRARAPID),
                                   (Phenotype.ULTRARAPID, Phenotype.RAPID)):
            with self.subTest(observed=observed.value):
                decision = match_observation(
                    normalize_phenotype(observed.value,
                                        gene_canonical_key="GENE:CYP2D6"),
                    exact(declared))
                self.assertEqual(decision.status, "NO_MATCH")

    def test_v2_matches_both_when_a_one_of_declares_both(self):
        both = one_of(Phenotype.RAPID, Phenotype.ULTRARAPID)
        for observed in (Phenotype.RAPID, Phenotype.ULTRARAPID):
            with self.subTest(observed=observed.value):
                self.assertEqual(
                    match_observation(
                        normalize_phenotype(observed.value,
                                            gene_canonical_key="GENE:CYP2D6"),
                        both).status, "MATCH")

    def test_the_report_carries_both_directions_as_constructed_cases(self):
        report = build_regression_report(REPO_ROOT)
        cases = {(case["observed"], tuple(case["declared"])): case
                 for case in report["constructed_cross_match_cases"]}
        for observed, declared in (("RAPID", ("ULTRARAPID",)),
                                   ("ULTRARAPID", ("RAPID",))):
            case = cases[(observed, declared)]
            with self.subTest(observed=observed):
                self.assertTrue(case["legacy_matched"])
                self.assertFalse(case["v2_matched"])
                self.assertTrue(case["differs"])
                self.assertIn("LEGACY-BUG-001", case["expected_difference_id"])


class TestBroadDecreasedFunctionGroupingIsGone(unittest.TestCase):

    def test_legacy_expands_the_invented_group_into_two_phenotypes(self):
        self.assertTrue(legacy_matches("poor", "decreased_function"))
        self.assertTrue(legacy_matches("intermediate", "decreased_function"))

    def test_v2_treats_the_group_as_an_unsupported_input(self):
        observation = normalize_phenotype("decreased_function",
                                          gene_canonical_key="GENE:CYP2C9")
        self.assertEqual(observation.status, "UNSUPPORTED")
        self.assertEqual(observation.reason_code,
                         "PHENOTYPE_INPUT_BROAD_GROUP_NOT_ALLOWED")
        self.assertIsNone(observation.phenotype)

    def test_poor_does_not_implicitly_match_a_broad_group(self):
        """There is no condition a rule could declare that would do it: the
        group is not in the rule phenotype vocabulary at all."""
        from pgx.rules.conditions import RULE_PHENOTYPES
        self.assertNotIn("DECREASED_FUNCTION",
                         {member.value for member in RULE_PHENOTYPES})

    def test_the_report_records_the_group_case(self):
        case = build_regression_report(REPO_ROOT)["constructed_broad_group_case"]
        self.assertEqual(case["v2_status"], "UNSUPPORTED")
        self.assertIsNone(case["v2_phenotype"])
        self.assertTrue(case["legacy_matches_poor_rule"])


class TestTheP1ToP6Comparison(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.report = build_regression_report(REPO_ROOT)
        cls.by_id = {row["profile_id"]: row for row in cls.report["profiles"]}

    def test_all_six_profiles_are_present(self):
        self.assertEqual(tuple(sorted(self.by_id)), EXPECTED_PROFILES)

    def test_every_gene_of_every_profile_is_represented(self):
        raw = load_demo_profiles(REPO_ROOT)
        for profile_id, row in self.by_id.items():
            with self.subTest(profile=profile_id):
                self.assertEqual(row["gene_count"],
                                 len(raw[profile_id]["phenotypes"]))

    def _phenotype(self, profile_id, gene):
        for entry in self.by_id[profile_id]["genes"]:
            if entry["gene_id"] == gene:
                return entry
        raise AssertionError("%s has no %s" % (profile_id, gene))

    def test_p1_normal_values_normalize_deterministically(self):
        for entry in self.by_id["P1_normal"]["genes"]:
            with self.subTest(gene=entry["gene_id"]):
                self.assertEqual(entry["v2_status"], "NORMALIZED")
                self.assertEqual(entry["v2_phenotype"], "NORMAL")

    def test_p2_cyp2c19_poor_normalizes_exactly(self):
        entry = self._phenotype("P2_cyp2c19_poor", "GENE:CYP2C19")
        self.assertEqual(entry["v2_phenotype"], "POOR")

    def test_p3_cyp2d6_poor_normalizes_exactly(self):
        entry = self._phenotype("P3_cyp2d6_poor", "GENE:CYP2D6")
        self.assertEqual(entry["v2_phenotype"], "POOR")

    def test_p4_cyp2d6_ultrarapid_normalizes_exactly(self):
        entry = self._phenotype("P4_cyp2d6_ultrarapid", "GENE:CYP2D6")
        self.assertEqual(entry["v2_phenotype"], "ULTRARAPID")

    def test_p5_cyp2c9_intermediate_normalizes_exactly(self):
        entry = self._phenotype("P5_cyp2c9_decreased", "GENE:CYP2C9")
        self.assertEqual(entry["v2_phenotype"], "INTERMEDIATE")

    def test_p6_mixed_values_normalize_independently(self):
        expected = {"GENE:CYP2C19": "POOR", "GENE:CYP2D6": "POOR",
                    "GENE:CYP2C9": "INTERMEDIATE", "GENE:CYP3A4": "NORMAL",
                    "GENE:CYP1A2": "NORMAL"}
        for gene, phenotype in expected.items():
            with self.subTest(gene=gene):
                self.assertEqual(
                    self._phenotype("P6_mixed_high_attention",
                                    gene)["v2_phenotype"], phenotype)

    def test_p4_ultrarapid_does_not_satisfy_a_rapid_rule(self):
        """The profile-level evidence for SAFETY-INV-004: the one demo profile
        with an ultrarapid value does not match a rule written for rapid, and
        legacy says it does."""
        entry = self._phenotype("P4_cyp2d6_ultrarapid", "GENE:CYP2D6")
        rows = {tuple(row["declared"]): row for row in entry["match_rows"]}
        rapid = rows[("RAPID",)]
        self.assertTrue(rapid["legacy_matched"])
        self.assertEqual(rapid["v2_status"], "NO_MATCH")
        self.assertEqual(rapid["expected_difference_id"],
                         "LEGACY-BUG-001-ULTRARAPID-TO-RAPID")

    def test_every_profile_carries_its_own_content_hash(self):
        for profile_id, row in self.by_id.items():
            with self.subTest(profile=profile_id):
                self.assertTrue(
                    row["profile_content_hash"].startswith("sha256:"))


class TestTheAllowlistGovernsEveryDifference(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.report = build_regression_report(REPO_ROOT)

    def test_there_are_no_unexpected_differences(self):
        self.assertEqual(self.report["unexpected_differences"], [])

    def test_every_allowlisted_difference_was_observed(self):
        """An intended difference that quietly stops happening is as much a
        change as one that appears."""
        self.assertEqual(self.report["expected_differences_not_observed"], [])

    def test_the_three_required_entries_are_present(self):
        ids = {entry.difference_id for entry in EXPECTED_DIFFERENCES}
        for required in ("LEGACY-BUG-001-RAPID-TO-ULTRARAPID",
                         "LEGACY-BUG-001-ULTRARAPID-TO-RAPID",
                         "LEGACY-BROAD-DECREASED-FUNCTION-GROUPING"):
            with self.subTest(entry=required):
                self.assertIn(required, ids)

    def test_every_entry_is_complete(self):
        for entry in EXPECTED_DIFFERENCES:
            with self.subTest(entry=entry.difference_id):
                self.assertTrue(entry.legacy_bug_id.startswith("LEGACY-BUG-"))
                self.assertGreater(len(entry.observed_legacy_behavior), 40)
                self.assertGreater(len(entry.required_v2_behavior), 30)
                self.assertGreater(len(entry.safety_rationale), 40)
                self.assertTrue(entry.reference)
                self.assertTrue(entry.comparison_selector)
                self.assertTrue(entry.expected_status)

    def test_every_entry_names_a_known_legacy_bug(self):
        with io.open(os.path.join(REPO_ROOT, "data", "legacy-baseline",
                                  "expected-differences.json"),
                     encoding="utf-8") as handle:
            known = set(json.load(handle)["known_bug_ids"])
        for entry in EXPECTED_DIFFERENCES:
            with self.subTest(entry=entry.difference_id):
                self.assertIn(entry.legacy_bug_id, known)

    def test_an_unexplained_difference_would_be_reported(self):
        """The harness is only worth having if it can fail. A difference with
        no allowlist entry lands in unexpected_differences rather than being
        absorbed."""
        from pgx.engine import phenotype_legacy
        row = {"operator": "EXACT", "declared": ["POOR"]}
        self.assertIsNone(phenotype_legacy._difference_id_for("RAPID", row))

    def test_the_published_allowlist_matches_the_code(self):
        with io.open(REGRESSION_ALLOWLIST, encoding="utf-8") as handle:
            published = json.load(handle)
        self.assertEqual(published, expected_difference_allowlist())


class TestTheReportIsDeterministicAndPublished(unittest.TestCase):

    def test_two_generations_are_identical(self):
        self.assertEqual(build_regression_report(REPO_ROOT),
                         build_regression_report(REPO_ROOT))

    def test_the_content_hash_is_stable(self):
        self.assertEqual(build_regression_report(REPO_ROOT)["content_hash"],
                         build_regression_report(REPO_ROOT)["content_hash"])

    def test_the_published_report_matches_a_fresh_build(self):
        with io.open(REGRESSION_REPORT, encoding="utf-8") as handle:
            published = json.load(handle)
        self.assertEqual(published, build_regression_report(REPO_ROOT))

    def test_the_report_carries_no_timestamp_host_or_path(self):
        """Anything that varied by run or by machine would make "did the
        comparison change" unanswerable.

        Checked over the report's *keys*, walked recursively, rather than over
        its serialised text: a substring scan for "pid" finds it inside
        "RAPID", and a test that fails on its own subject matter teaches
        nobody anything.
        """
        forbidden = {"generated_at", "built_at", "timestamp", "created_at",
                     "hostname", "host", "duration", "pid", "process_id",
                     "elapsed", "machine", "cwd", "absolute_path"}

        def _keys(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    yield key
                    for found in _keys(value):
                        yield found
            elif isinstance(node, list):
                for item in node:
                    for found in _keys(item):
                        yield found

        report = build_regression_report(REPO_ROOT)
        self.assertEqual(set(_keys(report)) & forbidden, set())

    def test_the_report_carries_no_absolute_path(self):
        text = json.dumps(build_regression_report(REPO_ROOT))
        for prefix in ("/Users/", "/home/", "C:\\", "/tmp/", "/sessions/"):
            with self.subTest(prefix=prefix):
                self.assertNotIn(prefix, text)

    def test_the_source_profile_file_is_unchanged(self):
        """WP-01 protects this artifact. The harness reads it and must never
        write it."""
        with io.open(LEGACY_PROFILES, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        build_regression_report(REPO_ROOT)
        with io.open(LEGACY_PROFILES, "rb") as handle:
            self.assertEqual(hashlib.sha256(handle.read()).hexdigest(), digest)

    def test_the_harness_opens_no_file_for_writing(self):
        import ast
        from tests.unit.engine._support import ENGINE_DIR, tree
        import os as _os
        for node in ast.walk(tree(_os.path.join(ENGINE_DIR,
                                                "phenotype_legacy.py"))):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(
                node.func, "id", None)
            if name != "open":
                continue
            modes = [argument.value for argument in node.args[1:]
                     if isinstance(argument, ast.Constant)]
            modes += [keyword.value.value for keyword in node.keywords
                      if keyword.arg == "mode"
                      and isinstance(keyword.value, ast.Constant)]
            for mode in modes:
                with self.subTest(mode=mode):
                    self.assertNotIn("w", mode)
                    self.assertNotIn("a", mode)

    def test_the_report_compares_no_clinical_output(self):
        report = build_regression_report(REPO_ROOT)
        text = json.dumps(report)
        for forbidden in ("attention_level", "coverage_status", "risk_level",
                          "dose", "recommendation", "medication", "drug_id"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
