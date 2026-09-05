# -*- coding: utf-8 -*-
"""The four published WP-12 schemas (WP-12, section 9).

Each is checked two ways: real output validates against it, and a document
that lies in the way a hand-edited file would most usefully lie does not. A
schema nothing has ever failed is a description, not a constraint.

The refusals that matter are the forbidden-field ones. WP-12 computes no
attention level and no coverage status, and the schemas are where that stays
true when somebody downstream finds it convenient to attach one to a match
result rather than carrying it separately.
"""

from __future__ import annotations

import copy
import io
import json
import os
import unittest

from pgx.application.phenotype_schema import (
    WP12_SCHEMA_PATHS, load_schema, validate_phenotype_match_result,
    validate_phenotype_normalization_result, validate_phenotype_profile,
    validate_phenotype_regression_report)
from pgx.domain.enums import Phenotype
from pgx.engine.phenotype import match_observation
from pgx.engine.phenotype_legacy import build_regression_report
from pgx.engine.phenotype_normalization import (normalize_phenotype,
                                                normalize_profile)
from tests.fixtures.wp12.synthetic import exact, observation, one_of
from tests.unit.engine._support import (REGRESSION_ALLOWLIST,
                                        REGRESSION_REPORT, REPO_ROOT)


class TestEverySchemaIsWellFormedAndUsed(unittest.TestCase):

    def test_all_four_are_published(self):
        for path in WP12_SCHEMA_PATHS:
            with self.subTest(schema=os.path.basename(path)):
                self.assertTrue(os.path.isfile(path))

    def test_each_declares_an_id_and_a_description(self):
        for path in WP12_SCHEMA_PATHS:
            document = load_schema(path)
            with self.subTest(schema=os.path.basename(path)):
                self.assertIn("$id", document)
                self.assertGreater(len(document["description"]), 100,
                                   "a schema whose description does not say "
                                   "what it refuses is documentation debt")

    def test_each_forbids_unknown_properties(self):
        for path in WP12_SCHEMA_PATHS:
            document = load_schema(path)
            with self.subTest(schema=os.path.basename(path)):
                self.assertIs(document["additionalProperties"], False)


class TestRealOutputValidates(unittest.TestCase):

    def test_a_real_profile_validates(self):
        profile = normalize_profile(
            {"CYP2C19": "poor", "CYP2D6": "", "CYP2C9": "PM",
             "CYP3A4": "INDETERMINATE"}, profile_id="TEST-1",
            metadata={"profile_name": "synthetic"})
        self.assertEqual(validate_phenotype_profile(profile.to_json()), ())

    def test_every_normalization_outcome_validates(self):
        for value in ("POOR", None, "", "INDETERMINATE", "PM",
                      "decreased_function", "*1/*2", 42, True, [], {}):
            payload = normalize_phenotype(
                value, gene_canonical_key="GENE:CYP2D6").to_json()
            with self.subTest(value=repr(value)):
                self.assertEqual(
                    validate_phenotype_normalization_result(payload), ())

    def test_every_match_outcome_validates(self):
        for value in ("POOR", "NORMAL", None, "INDETERMINATE", "PM"):
            payload = match_observation(observation(value),
                                        exact(Phenotype.POOR)).to_json()
            with self.subTest(value=repr(value)):
                self.assertEqual(validate_phenotype_match_result(payload), ())

    def test_a_one_of_decision_validates(self):
        payload = match_observation(
            observation("RAPID"),
            one_of(Phenotype.RAPID, Phenotype.ULTRARAPID)).to_json()
        self.assertEqual(validate_phenotype_match_result(payload), ())

    def test_the_published_regression_report_validates(self):
        with io.open(REGRESSION_REPORT, encoding="utf-8") as handle:
            self.assertEqual(
                validate_phenotype_regression_report(json.load(handle)), ())

    def test_a_freshly_built_report_validates(self):
        self.assertEqual(
            validate_phenotype_regression_report(
                build_regression_report(REPO_ROOT)), ())


class TestTheSchemasRefuseTheUsefulLies(unittest.TestCase):

    def setUp(self):
        self.profile = normalize_profile({"CYP2C19": "poor"},
                                         profile_id="TEST-1").to_json()
        self.result = normalize_phenotype(
            "poor", gene_canonical_key="GENE:CYP2C19").to_json()
        self.decision = match_observation(observation("POOR"),
                                          exact(Phenotype.POOR)).to_json()

    def _refused(self, payload, mutate, validator):
        document = copy.deepcopy(payload)
        mutate(document)
        return validator(document)

    def test_a_match_result_carrying_an_attention_level_is_refused(self):
        self.assertTrue(self._refused(
            self.decision, lambda doc: doc.update(attention_level="LOW"),
            validate_phenotype_match_result))

    def test_a_match_result_carrying_a_coverage_status_is_refused(self):
        self.assertTrue(self._refused(
            self.decision, lambda doc: doc.update(coverage_status="FULL"),
            validate_phenotype_match_result))

    def test_a_match_result_carrying_a_dose_is_refused(self):
        for field in ("dose", "dosage", "recommendation", "alternative",
                      "risk_score", "safe", "treatment", "finding",
                      "explanation"):
            with self.subTest(field=field):
                self.assertTrue(self._refused(
                    self.decision, lambda doc, f=field: doc.update({f: "x"}),
                    validate_phenotype_match_result))

    def test_a_profile_carrying_an_attention_or_coverage_field_is_refused(self):
        for field in ("attention_level", "coverage_status", "risk_level",
                      "recommendation", "medications"):
            with self.subTest(field=field):
                self.assertTrue(self._refused(
                    self.profile, lambda doc, f=field: doc.update({f: "x"}),
                    validate_phenotype_profile))

    def test_an_observation_claiming_indeterminate_as_a_phenotype_is_refused(self):
        self.assertTrue(self._refused(
            self.result,
            lambda doc: doc.update(phenotype="INDETERMINATE"),
            validate_phenotype_normalization_result))

    def test_a_failed_result_carrying_a_phenotype_is_refused(self):
        """The lie a hand-edited file would most usefully tell: an
        unsupported input with a phenotype attached anyway."""
        self.assertTrue(self._refused(
            self.result,
            lambda doc: doc.update(status="UNSUPPORTED", phenotype="NORMAL",
                                   reason_code="PHENOTYPE_INPUT_UNSUPPORTED"),
            validate_phenotype_normalization_result))

    def test_a_failed_profile_observation_carrying_a_phenotype_is_refused(self):
        def _mutate(doc):
            doc["observations"][0].update(
                status="UNSUPPORTED", phenotype="NORMAL",
                reason_code="PHENOTYPE_INPUT_UNSUPPORTED")
        self.assertTrue(self._refused(self.profile, _mutate,
                                      validate_phenotype_profile))

    def test_a_normalized_observation_with_a_failure_reason_is_refused(self):
        def _mutate(doc):
            doc["observations"][0]["reason_code"] = \
                "PHENOTYPE_INPUT_UNSUPPORTED"
        self.assertTrue(self._refused(self.profile, _mutate,
                                      validate_phenotype_profile))

    def test_an_undocumented_reason_code_is_refused(self):
        self.assertTrue(self._refused(
            self.result,
            lambda doc: doc.update(status="UNSUPPORTED", phenotype=None,
                                   reason_code="MADE_UP"),
            validate_phenotype_normalization_result))

    def test_an_unknown_match_status_is_refused(self):
        for status in ("PARTIAL_MATCH", "NEAR_MATCH", "PROBABLE", "OK"):
            with self.subTest(status=status):
                self.assertTrue(self._refused(
                    self.decision, lambda doc, s=status: doc.update(status=s),
                    validate_phenotype_match_result))

    def test_an_unknown_operator_is_refused(self):
        for operator in ("ANY", "REGEX", "NEAREST", "LIKE"):
            with self.subTest(operator=operator):
                self.assertTrue(self._refused(
                    self.decision,
                    lambda doc, o=operator: doc.update(operator=o),
                    validate_phenotype_match_result))

    def test_a_condition_declaring_indeterminate_is_refused(self):
        self.assertTrue(self._refused(
            self.decision,
            lambda doc: doc.update(declared_phenotypes=["INDETERMINATE"]),
            validate_phenotype_match_result))

    def test_a_match_without_an_observed_phenotype_is_refused(self):
        self.assertTrue(self._refused(
            self.decision, lambda doc: doc.update(observed_phenotype=None),
            validate_phenotype_match_result))

    def test_a_report_hiding_its_unexpected_differences_is_refused(self):
        with io.open(REGRESSION_REPORT, encoding="utf-8") as handle:
            report = json.load(handle)
        report.pop("unexpected_differences")
        self.assertTrue(validate_phenotype_regression_report(report))

    def test_a_report_whose_broad_group_case_resolved_is_refused(self):
        """The schema pins the answer rather than trusting the producer: a
        broad functional group must never resolve to a P0 phenotype."""
        with io.open(REGRESSION_REPORT, encoding="utf-8") as handle:
            report = json.load(handle)
        report["constructed_broad_group_case"].update(v2_status="NORMALIZED",
                                                      v2_phenotype="POOR")
        self.assertTrue(validate_phenotype_regression_report(report))

    def test_an_allowlist_entry_without_a_safety_rationale_is_refused(self):
        with io.open(REGRESSION_REPORT, encoding="utf-8") as handle:
            report = json.load(handle)
        report["expected_differences"][0]["safety_rationale"] = "because"
        self.assertTrue(validate_phenotype_regression_report(report))


class TestThePublishedArtifactsAreConsistent(unittest.TestCase):

    def test_the_allowlist_file_is_valid_json_and_complete(self):
        with io.open(REGRESSION_ALLOWLIST, encoding="utf-8") as handle:
            allowlist = json.load(handle)
        self.assertEqual(allowlist["allowlist_schema_version"],
                         "pgx-phenotype-regression-allowlist/1")
        self.assertEqual(allowlist["entry_count"],
                         len(allowlist["entries"]))
        for entry in allowlist["entries"]:
            with self.subTest(entry=entry["difference_id"]):
                self.assertGreater(len(entry["safety_rationale"]), 40)

    def test_the_report_and_the_allowlist_agree(self):
        with io.open(REGRESSION_REPORT, encoding="utf-8") as handle:
            report = json.load(handle)
        with io.open(REGRESSION_ALLOWLIST, encoding="utf-8") as handle:
            allowlist = json.load(handle)
        self.assertEqual(
            [entry["difference_id"] for entry in report["expected_differences"]],
            [entry["difference_id"] for entry in allowlist["entries"]])


if __name__ == "__main__":
    unittest.main()
