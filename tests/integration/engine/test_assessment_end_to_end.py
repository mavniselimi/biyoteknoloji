# -*- coding: utf-8 -*-
"""WP-14 end to end on synthetic data (section 17).

The unit tests hand the service pieces. This one starts where a real run would
and walks the whole chain: rules drafted, curated, independently validated,
assembled, validated and frozen through WP-11's own services onto disk; loaded
back through the frozen-ruleset registry; a coverage scope declared and
verified through WP-13's builder; an ACTIVE release naming all of it; a
phenotype profile normalised through WP-12's boundary; coverage calculated;
findings calculated; hashes taken; and the whole aggregate persisted in one
transaction with an audit event.

Everything here is synthetic. The claim boundary is a fixture that reads as
approved and says TEST ONLY in its status; the release is an object in memory;
the genes and drugs are invented. That is not a limitation of the test - it is
the current state of the system, and the last class in this file asserts that
the synthetic run left the real state exactly where it found it.
"""

from __future__ import annotations

import json
import os
import unittest

from pgx.application.assessment_gate_status import (
    build_assessment_gate_status)
from pgx.application.assessment_schema import (
    validate_assessment_computation, validate_assessment_finding,
    validate_assessment_input, validate_medication_assessment)
from pgx.domain.claims import DEFAULT_CLAIM_BOUNDARY, OperationMode
from pgx.domain.enums import AttentionLevel, CoverageStatus, ReleaseStatus
from pgx.rules.registry import FrozenRulesetRegistry
from tests.fixtures.wp13.synthetic import (DRUG_1, DRUG_2, GENE_1, GENE_2,
                                           GENE_3, UNKNOWN_DRUG)
from tests.fixtures.wp14.synthetic import TEST_ACTOR
from tests.unit.application._assessment_support import (
    REPO_ROOT, SyntheticAssessmentWorld)


class TestTheWholePathOnSyntheticData(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.world = SyntheticAssessmentWorld(expected_extra_gene=True)
        cls.result = cls.world.execute(
            medications=[DRUG_1, DRUG_2, UNKNOWN_DRUG],
            phenotypes={GENE_1: "POOR", GENE_2: "POOR", GENE_3: "POOR"})

    @classmethod
    def tearDownClass(cls):
        cls.world.close()

    # -- the governed artifacts the run reads ---------------------------

    def test_1_the_claim_boundary_is_synthetic_and_says_so(self):
        boundary = self.world.boundary
        self.assertTrue(boundary.is_approved)
        self.assertIn("TEST ONLY", boundary.status)
        self.assertIn("NOT A REAL APPROVAL", boundary.status)
        self.assertNotEqual(boundary.status, DEFAULT_CLAIM_BOUNDARY.status)

    def test_2_the_frozen_ruleset_came_off_disk_through_the_registry(self):
        """Not a fixture object handed straight over: the registry verifies
        the artifact's own hashes on load."""
        registry = FrozenRulesetRegistry(
            os.path.join(self.world.tmp, "rulesets"))
        reloaded = registry.load("PGX-RULESET-29991231-001")
        self.assertEqual(reloaded.ruleset_content_hash,
                         self.world.frozen.ruleset_content_hash)
        self.assertEqual(reloaded.member_count, 2)

    def test_3_every_member_rule_carries_an_approval_record(self):
        approvals = {record.rule_id.to_json()
                     for record in self.world.frozen.approvals}
        for definition in self.world.frozen.rules():
            with self.subTest(rule=definition.rule_id.to_json()):
                self.assertIn(definition.rule_id.to_json(), approvals)

    def test_4_the_coverage_manifest_verifies_against_that_ruleset(self):
        from pgx.engine.coverage_validator import validate_coverage_manifest
        report = validate_coverage_manifest(
            self.world.manifest, frozen_ruleset=self.world.frozen,
            evidence_resolver=self.world.resolver.evidence_resolver,
            declared_content_hash=self.world.manifest.content_hash())
        self.assertTrue(report.passed, report.to_json())

    def test_5_the_release_is_active_and_its_manifest_verifies(self):
        self.assertIs(self.world.release.status, ReleaseStatus.ACTIVE)
        from pgx.domain.hashing import sha256_digest
        self.assertEqual(sha256_digest(dict(self.world.release.manifest)),
                         self.world.release.manifest_hash)

    # -- the calculation ------------------------------------------------

    def test_6_the_input_validates_against_its_published_schema(self):
        document = self.world.input(
            medications=[DRUG_1, DRUG_2]).to_json()
        self.assertEqual(validate_assessment_input(document), ())

    def test_7_the_phenotype_was_matched_exactly(self):
        for finding in self.result.computation.findings:
            with self.subTest(gene=finding.gene_canonical_key):
                self.assertEqual(finding.phenotype.value, "POOR")

    def test_8_coverage_was_calculated_before_any_finding(self):
        computation = self.result.computation
        self.assertIsNotNone(computation.coverage_result)
        covered = {axis.axis_key
                   for medication in computation.coverage_result.medications
                   for axis in medication.axes
                   if axis.status is CoverageStatus.FULL}
        found = {(finding.drug_canonical_key, finding.gene_canonical_key)
                 for finding in computation.findings}
        self.assertTrue(found)
        self.assertTrue(found.issubset(covered))

    def test_9_every_finding_came_from_a_governed_rule_outcome(self):
        outcomes = {definition.rule_id.to_json(): definition.outcome
                    for definition in self.world.frozen.rules()}
        for finding in self.result.computation.findings:
            with self.subTest(rule=finding.rule_id):
                outcome = outcomes[finding.rule_id]
                self.assertIs(finding.attention_level,
                              outcome.attention_level)
                self.assertEqual(finding.rationale_reference,
                                 outcome.rationale_reference)

    def test_10_every_finding_is_evidence_linked(self):
        resolver = self.world.resolver.evidence_resolver
        for finding in self.result.computation.findings:
            with self.subTest(gene=finding.gene_canonical_key):
                self.assertTrue(finding.evidence_references)
                for reference in finding.evidence_references:
                    self.assertTrue(resolver(reference))

    def test_11_medication_attention_aggregates_its_findings(self):
        for medication in self.result.computation.medications:
            with self.subTest(drug=medication.drug_canonical_key):
                if medication.findings:
                    levels = {finding.attention_level
                              for finding in medication.findings}
                    self.assertIn(medication.attention_level, levels)
                else:
                    self.assertIs(medication.attention_level,
                                  AttentionLevel.NOT_ASSESSED)

    def test_12_overall_attention_aggregates_the_medications(self):
        computation = self.result.computation
        calculated = {item.attention_level
                      for item in computation.medications
                      if item.attention_level
                      is not AttentionLevel.NOT_ASSESSED}
        self.assertIn(computation.overall_attention, calculated)
        self.assertIs(computation.overall_coverage, CoverageStatus.PARTIAL)

    def test_13_the_hashes_are_deterministic(self):
        again = self.world.execute(
            medications=[DRUG_1, DRUG_2, UNKNOWN_DRUG],
            phenotypes={GENE_1: "POOR", GENE_2: "POOR", GENE_3: "POOR"})
        self.assertEqual(again.input_hash, self.result.input_hash)
        self.assertEqual(again.output_hash, self.result.output_hash)
        self.assertNotEqual(again.assessment_id, self.result.assessment_id)

    def test_14_the_whole_aggregate_was_persisted(self):
        row = self.world.store.row(self.result.assessment_id)
        self.assertIsNotNone(row)
        self.assertEqual(row["assessment"].output_hash,
                         self.result.output_hash)
        self.assertEqual(len(row["computation"].medications), 3)

    def test_15_retrieval_returns_identical_structured_facts(self):
        row = self.world.store.row(self.result.assessment_id)
        self.assertEqual(row["output_snapshot"],
                         self.result.computation.to_json())
        self.assertEqual(
            self.world.store.get(self.result.assessment_id).output_hash,
            self.result.output_hash)

    def test_16_a_success_audit_was_written(self):
        self.assertIn("ASSESSMENT_COMPLETED", self.world.audit.actions)
        record = [item for item in self.world.audit.records
                  if item.get("action") == "ASSESSMENT_COMPLETED"][0]
        self.assertEqual(record["actor"], TEST_ACTOR)

    def test_17_a_pointer_change_after_pinning_causes_no_drift(self):
        before = self.result.output_hash
        self.world.resolver.move_pointer()
        after = self.world.execute(
            medications=[DRUG_1, DRUG_2, UNKNOWN_DRUG],
            phenotypes={GENE_1: "POOR", GENE_2: "POOR", GENE_3: "POOR"})
        # The calculated facts are unchanged, and so is the output hash. The
        # pointer moved because this is a *new* run pinning a later pointer,
        # and where the pointer had got to is audit metadata about the
        # execution rather than a fact about the case (WP-15 preflight 3.5):
        # the same question against the same release bundle, with the same
        # content hashes, has the same answer either way.
        self.assertEqual(
            after.computation.overall_attention,
            self.result.computation.overall_attention)
        self.assertEqual(after.computation.overall_coverage,
                         self.result.computation.overall_coverage)
        self.assertEqual(after.output_hash, before)
        self.assertEqual(after.pinned.active_pointer_generation, 2)
        self.assertEqual(
            after.computation.to_json()["pointer_audit"][
                "active_pointer_generation"], 2)

    # -- the whole document ---------------------------------------------

    def test_every_level_of_the_result_validates_against_its_schema(self):
        payload = self.result.computation.to_json()
        self.assertEqual(validate_assessment_computation(payload), ())
        for medication in payload["medications"]:
            with self.subTest(drug=medication["drug_id"]):
                self.assertEqual(validate_medication_assessment(medication),
                                 ())
                for finding in medication["findings"]:
                    self.assertEqual(validate_assessment_finding(finding), ())

    def test_the_result_round_trips_through_json_unchanged(self):
        payload = self.result.computation.to_json()
        text = json.dumps(payload, indent=2, sort_keys=True,
                          ensure_ascii=False)
        self.assertEqual(json.loads(text), payload)

    def test_the_three_medication_outcomes_are_all_distinct(self):
        statuses = {item.drug_canonical_key:
                    (item.coverage_status, item.attention_level)
                    for item in self.result.computation.medications}
        self.assertEqual(statuses[DRUG_1][0], CoverageStatus.PARTIAL)
        self.assertEqual(statuses[DRUG_2],
                         (CoverageStatus.INSUFFICIENT,
                          AttentionLevel.NOT_ASSESSED))
        self.assertEqual(statuses[UNKNOWN_DRUG],
                         (CoverageStatus.UNSUPPORTED_DRUG,
                          AttentionLevel.NOT_ASSESSED))


class TestTheRealStateIsUnchangedByAnyOfThis(unittest.TestCase):
    """The synthetic run above must leave no trace on the real repository."""

    @classmethod
    def setUpClass(cls):
        cls.status = build_assessment_gate_status(REPO_ROOT).to_json()

    def test_no_real_assessment_exists(self):
        for name, value in self.status["assessment_state"].items():
            with self.subTest(count=name):
                self.assertEqual(value, 0)

    def test_the_gate_reports_that_execution_is_blocked(self):
        self.assertIn("BLOCKED", self.status["assessment"])
        self.assertTrue(self.status["blockers"])

    def test_the_shipped_claim_boundary_is_still_draft(self):
        self.assertFalse(DEFAULT_CLAIM_BOUNDARY.is_approved)
        self.assertIn("DRAFT", DEFAULT_CLAIM_BOUNDARY.status)
        self.assertFalse(self.status["claim_boundary"]["approved"])

    def test_the_default_frozen_ruleset_registry_is_still_empty(self):
        from pgx.rules.registry import DEFAULT_RULESET_ROOT
        registry = FrozenRulesetRegistry(os.path.join(REPO_ROOT,
                                                      DEFAULT_RULESET_ROOT))
        self.assertEqual(registry.list_executable(), ())

    def test_no_release_is_active(self):
        self.assertEqual(self.status["upstream_state"]["active_releases"], 0)

    def test_the_assessment_directory_holds_only_its_gate_status(self):
        directory = os.path.join(REPO_ROOT, "data", "assessments")
        present = sorted(name for name in os.listdir(directory)
                         if name.endswith(".json"))
        self.assertEqual(present, ["wp14-real-gate-status.json"])

    def test_the_curation_protocol_is_still_awaiting_review(self):
        import io
        path = os.path.join(REPO_ROOT, "config", "curation",
                            "protocol-v1.json")
        with io.open(path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["status"],
                             "AWAITING_EXPERT_REVIEW")


if __name__ == "__main__":
    unittest.main()
