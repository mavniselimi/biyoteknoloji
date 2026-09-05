# -*- coding: utf-8 -*-
"""WP-13 end to end on synthetic data (section G).

The unit tests hand the engine pieces. This one starts where a real run would:
a ruleset drafted, curated, validated, assembled and frozen through WP-11's own
services onto disk, loaded back through the frozen-ruleset registry, a coverage
scope declared over it and verified, a phenotype profile normalised through
WP-12's boundary, and a request evaluated against all of it.

Everything here is synthetic. The genes and drugs are invented, the approving
actors are invented, and nothing in this file was reviewed by anybody. That is
not a limitation of the test - it is the current state of the system, and the
gate-status assertions at the end say so in the same run.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import tempfile
import unittest

from pgx.application.coverage_gate_status import build_coverage_gate_status
from pgx.application.coverage_schema import (validate_axis_coverage,
                                             validate_coverage_result,
                                             validate_medication_coverage,
                                             validate_ruleset_coverage_manifest)
from pgx.domain.enums import CoverageReasonCode, CoverageStatus
from pgx.engine.coverage import evaluate_coverage
from pgx.engine.coverage_validator import validate_coverage_manifest
from pgx.rules.registry import FrozenRulesetRegistry
from tests.fixtures.wp13.synthetic import (DRUG_1, DRUG_2, GENE_1, GENE_2,
                                           GENE_3, SYNTHETIC_DRUG_CATALOGUE,
                                           SYNTHETIC_GENE_CATALOGUE,
                                           UNKNOWN_DRUG, declarations_for,
                                           synthetic_approval,
                                           synthetic_conflict,
                                           synthetic_evidence_resolver,
                                           synthetic_frozen_ruleset,
                                           synthetic_manifest,
                                           synthetic_profile)
from tests.unit.engine._coverage_support import REPO_ROOT

#: Module level rather than a class attribute: a plain function assigned to a
#: class becomes a bound method on attribute access, and the engine would then
#: be handed a two-argument callable where it expects one.
RESOLVER = synthetic_evidence_resolver()


class TestTheWholePathOnSyntheticData(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        destination = os.path.join(cls.tmp, "rulesets",
                                   "PGX-RULESET-29991231-001")
        cls.frozen, cls.definitions = synthetic_frozen_ruleset(destination,
                                                               count=2)
        cls.manifest = synthetic_manifest(cls.frozen, expected_extra_gene=True)
        cls.destination = destination

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def request(self, medications, phenotypes, **overrides):
        from pgx.engine.coverage import CoverageRequest
        return CoverageRequest(
            profile=synthetic_profile(phenotypes),
            medications=tuple(medications),
            manifest=overrides.pop("manifest", self.manifest),
            frozen_ruleset=overrides.pop("frozen", self.frozen),
            drug_catalogue=SYNTHETIC_DRUG_CATALOGUE,
            evidence_resolver=overrides.pop("resolver", RESOLVER),
            conflicts=tuple(overrides.pop("conflicts", ())))

    # -- the artifacts the run reads ------------------------------------

    def test_the_frozen_ruleset_came_off_disk_through_the_registry(self):
        """Not a fixture object handed straight over. The registry verifies
        the artifact's own hashes on load, so a coverage claim built on it is
        built on something that was checked."""
        registry = FrozenRulesetRegistry(os.path.dirname(self.destination))
        reloaded = registry.load("PGX-RULESET-29991231-001")
        self.assertEqual(reloaded.ruleset_content_hash,
                         self.frozen.ruleset_content_hash)
        self.assertEqual(reloaded.member_count, 2)

    def test_the_wp11_manifest_still_calls_its_axes_an_inventory(self):
        note = self.frozen.manifest.to_json().get("note", "")
        self.assertIn("structural", note.lower())

    def test_the_coverage_manifest_verifies_against_that_ruleset(self):
        report = validate_coverage_manifest(
            self.manifest, frozen_ruleset=self.frozen,
            drug_catalogue=SYNTHETIC_DRUG_CATALOGUE,
            gene_catalogue=SYNTHETIC_GENE_CATALOGUE,
            evidence_resolver=RESOLVER,
            declared_content_hash=self.manifest.content_hash())
        self.assertTrue(report.passed, report.to_json())

    def test_the_coverage_manifest_validates_against_its_published_schema(self):
        self.assertEqual(
            validate_ruleset_coverage_manifest(self.manifest.to_json()), ())

    # -- the four answers -----------------------------------------------

    def test_a_partially_covered_medication(self):
        result = evaluate_coverage(self.request(
            [DRUG_1], {GENE_1: "POOR", GENE_2: "POOR", GENE_3: "POOR"}))
        self.assertEqual(result.status, CoverageStatus.PARTIAL)
        self.assertIn(CoverageReasonCode.SOME_AXES_NOT_COVERED,
                      result.reason_codes)
        axes = {axis.gene_canonical_key: axis.status
                for axis in result.medications[0].axes}
        self.assertEqual(axes[GENE_1], CoverageStatus.FULL)
        self.assertEqual(axes[GENE_2], CoverageStatus.FULL)
        self.assertEqual(axes[GENE_3], CoverageStatus.INSUFFICIENT)

    def test_a_recognised_drug_nobody_declared_a_scope_for(self):
        result = evaluate_coverage(self.request([DRUG_2], {GENE_1: "POOR"}))
        self.assertEqual(result.status, CoverageStatus.INSUFFICIENT)
        self.assertIn(CoverageReasonCode.NO_VALIDATED_RULE_FOR_AXIS,
                      result.reason_codes)

    def test_a_drug_the_dataset_does_not_contain(self):
        result = evaluate_coverage(self.request([UNKNOWN_DRUG],
                                                {GENE_1: "POOR"}))
        self.assertEqual(result.status, CoverageStatus.UNSUPPORTED_DRUG)
        self.assertEqual(result.medications[0].axes, ())

    def test_an_unresolved_disagreement_reaches_the_top(self):
        result = evaluate_coverage(self.request(
            [DRUG_1, DRUG_2], {GENE_1: "POOR", GENE_2: "POOR"},
            conflicts=(synthetic_conflict(),)))
        self.assertEqual(result.status, CoverageStatus.SOURCE_CONFLICT)
        self.assertIn(CoverageReasonCode.VALIDATED_RULES_CONFLICT,
                      result.reason_codes)
        self.assertIn(CoverageReasonCode.NO_VALIDATED_RULE_FOR_AXIS,
                      result.reason_codes)

    def test_a_mixed_request_keeps_each_medication_distinct(self):
        result = evaluate_coverage(self.request(
            [DRUG_1, DRUG_2, UNKNOWN_DRUG],
            {GENE_1: "POOR", GENE_2: "POOR", GENE_3: "POOR"}))
        statuses = {item.medication.requested_value: item.status
                    for item in result.medications}
        self.assertEqual(statuses[DRUG_1], CoverageStatus.PARTIAL)
        self.assertEqual(statuses[DRUG_2], CoverageStatus.INSUFFICIENT)
        self.assertEqual(statuses[UNKNOWN_DRUG],
                         CoverageStatus.UNSUPPORTED_DRUG)
        self.assertEqual(result.status, CoverageStatus.PARTIAL)

    def test_a_fully_covered_medication_is_reachable(self):
        """Only with a declared scope that no gene falls outside. Reached here
        deliberately, so 'FULL is unreachable' cannot be why the FULL branch
        is never exercised."""
        manifest = synthetic_manifest(self.frozen, expected_extra_gene=False)
        result = evaluate_coverage(self.request(
            [DRUG_1], {GENE_1: "POOR", GENE_2: "POOR"}, manifest=manifest))
        self.assertEqual(result.status, CoverageStatus.FULL)
        self.assertEqual(result.reason_codes, ())

    # -- the whole result -----------------------------------------------

    def test_every_level_of_the_result_validates_against_its_schema(self):
        result = evaluate_coverage(self.request(
            [DRUG_1, DRUG_2, UNKNOWN_DRUG],
            {GENE_1: "POOR", GENE_2: "poor metabolizer"}))
        payload = result.to_json()
        self.assertEqual(validate_coverage_result(payload), ())
        for medication in payload["medications"]:
            with self.subTest(medication=medication["medication"]["drug_id"]):
                self.assertEqual(validate_medication_coverage(medication), ())
                for axis in medication["axes"]:
                    self.assertEqual(validate_axis_coverage(axis), ())

    def test_the_result_round_trips_through_json_unchanged(self):
        result = evaluate_coverage(self.request(
            [DRUG_1, UNKNOWN_DRUG], {GENE_1: "POOR"}))
        text = json.dumps(result.to_json(), indent=2, sort_keys=True,
                          ensure_ascii=False)
        self.assertEqual(json.loads(text), result.to_json())
        self.assertEqual(json.loads(text)["content_hash"],
                         result.content_hash())

    def test_the_same_run_twice_is_byte_identical(self):
        one = evaluate_coverage(self.request(
            [DRUG_1, DRUG_2, UNKNOWN_DRUG], {GENE_1: "POOR", GENE_3: "NORMAL"}))
        two = evaluate_coverage(self.request(
            [DRUG_1, DRUG_2, UNKNOWN_DRUG], {GENE_1: "POOR", GENE_3: "NORMAL"}))
        self.assertEqual(json.dumps(one.to_json(), sort_keys=True),
                         json.dumps(two.to_json(), sort_keys=True))

    def test_a_rebuilt_manifest_produces_the_identical_result(self):
        rebuilt = synthetic_manifest(self.frozen, expected_extra_gene=True)
        self.assertEqual(rebuilt.content_hash(), self.manifest.content_hash())
        one = evaluate_coverage(self.request([DRUG_1], {GENE_1: "POOR"}))
        two = evaluate_coverage(self.request([DRUG_1], {GENE_1: "POOR"},
                                             manifest=rebuilt))
        self.assertEqual(one.content_hash(), two.content_hash())

    def test_the_result_pins_the_ruleset_it_was_computed_against(self):
        result = evaluate_coverage(self.request([DRUG_1], {GENE_1: "POOR"}))
        self.assertEqual(result.ruleset_content_hash,
                         self.frozen.ruleset_content_hash)
        self.assertEqual(result.ruleset_public_id,
                         self.frozen.manifest.public_id.to_json())
        self.assertEqual(result.coverage_manifest_hash,
                         self.manifest.content_hash())

    def test_a_ruleset_rebuilt_underneath_the_manifest_fails_closed(self):
        second = os.path.join(self.tmp, "other", "PGX-RULESET-29991231-001")
        other, _definitions = synthetic_frozen_ruleset(second, count=3)
        result = evaluate_coverage(self.request([DRUG_1], {GENE_1: "POOR"},
                                                frozen=other))
        self.assertEqual(result.status, CoverageStatus.INSUFFICIENT)
        self.assertIn(CoverageReasonCode.DATASET_RULESET_MISMATCH,
                      result.reason_codes)


class TestTheRealStateIsUnchangedByAnyOfThis(unittest.TestCase):
    """The synthetic run above must leave no trace on the real repository."""

    @classmethod
    def setUpClass(cls):
        cls.status = build_coverage_gate_status(REPO_ROOT).to_json()

    def test_no_real_coverage_manifest_exists(self):
        for name, value in self.status["coverage_state"].items():
            with self.subTest(count=name):
                self.assertEqual(value, 0)

    def test_the_gate_reports_that_real_evaluation_is_blocked(self):
        self.assertIn("BLOCKED", self.status["assessment"])
        self.assertTrue(self.status["blockers"])

    def test_the_default_frozen_ruleset_registry_is_still_empty(self):
        from pgx.rules.registry import DEFAULT_RULESET_ROOT
        registry = FrozenRulesetRegistry(os.path.join(REPO_ROOT,
                                                      DEFAULT_RULESET_ROOT))
        self.assertEqual(registry.list_executable(), ())

    def test_the_coverage_directory_holds_no_manifest(self):
        directory = os.path.join(REPO_ROOT, "data", "coverage")
        present = sorted(name for name in os.listdir(directory)
                         if name.endswith(".json"))
        self.assertEqual(present, ["wp13-real-gate-status.json"])

    def test_the_curation_protocol_is_still_awaiting_review(self):
        import io
        path = os.path.join(REPO_ROOT, "config", "curation",
                            "protocol-v1.json")
        with io.open(path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["status"],
                             "AWAITING_EXPERT_REVIEW")


if __name__ == "__main__":
    unittest.main()
