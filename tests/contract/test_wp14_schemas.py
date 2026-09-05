# -*- coding: utf-8 -*-
"""The seven WP-14 published schemas, as a downstream contract.

These are what WP-15, an API, or another service reads instead of reading this
repository. Four properties matter.

*Checkable*: this project's validator raises on any keyword it does not
implement, so every schema is run against a real document - which is what
proves no unimplemented keyword slipped in and started silently checking
nothing.

*Closed*: ``additionalProperties: false`` at every level. This is where the
boundary is actually enforced. A dose, a recommendation, a ranking or a
rendered sentence cannot be attached to a calculated result by anything
downstream, because the schema refuses every property it does not name.

*Coupled*: ``NO_ACTIVE_ATTENTION`` requires ``FULL`` coverage, ``NOT_ASSESSED``
requires no findings, non-``FULL`` coverage requires a reason. That is
SAFETY-INV-001 in a form a downstream reader enforces for itself rather than
trusting this repository to have got right.

*Honest*: ``PILOT`` is absent from the mode enumeration rather than merely
refused at runtime, and the scientific codes are nullable because the governed
rule outcome carries none.
"""

from __future__ import annotations

import io
import json
import os
import unittest

from pgx.application.assessment_gate_status import (
    build_assessment_gate_status)
from pgx.application.assessment_schema import (
    ASSESSMENT_COMPUTATION_SCHEMA_PATH, WP14_SCHEMA_PATHS, load_schema,
    validate_assessment_computation, validate_assessment_failure,
    validate_assessment_finding, validate_assessment_input,
    validate_assessment_regression_report, validate_medication_assessment,
    validate_wp14_gate_status)
from pgx.domain.claims import OperationMode
from pgx.domain.enums import AttentionLevel, CoverageStatus
from pgx.engine.risk_errors import FAILURE_CODES, AssessmentInputError
from pgx.engine.risk_legacy import build_assessment_regression_report
from tests.fixtures.wp13.synthetic import (DRUG_1, DRUG_2, GENE_1, GENE_2,
                                           GENE_3, UNKNOWN_DRUG)
from tests.unit.application._assessment_support import (
    REPO_ROOT, SyntheticAssessmentWorld)


class Wp14SchemaCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.world = SyntheticAssessmentWorld(persist=False)
        cls.input = cls.world.input(medications=[DRUG_1, DRUG_2]).to_json()
        cls.computation = cls.world.dry_run(
            medications=[DRUG_1, DRUG_2, UNKNOWN_DRUG],
            phenotypes={GENE_1: "POOR", GENE_2: "POOR",
                        GENE_3: "POOR"}).to_json()
        cls.medication = [item for item in cls.computation["medications"]
                          if item["findings"]][0]
        cls.finding = cls.medication["findings"][0]
        cls.report = build_assessment_regression_report(REPO_ROOT)
        cls.status = build_assessment_gate_status(REPO_ROOT).to_json()
        cls.failure = AssessmentInputError(
            "x", code="ASSESSMENT_MODE_NOT_PERMITTED").to_json()

    @classmethod
    def tearDownClass(cls):
        cls.world.close()


class TestEverySchemaIsPresentAndWellFormed(Wp14SchemaCase):

    def test_all_seven_documents_exist(self):
        self.assertEqual(len(WP14_SCHEMA_PATHS), 7)
        for path in WP14_SCHEMA_PATHS:
            with self.subTest(schema=os.path.basename(path)):
                self.assertTrue(os.path.isfile(path))

    def test_each_declares_an_identifier_and_a_description(self):
        for path in WP14_SCHEMA_PATHS:
            document = load_schema(path)
            with self.subTest(schema=os.path.basename(path)):
                self.assertTrue(document.get("$id"))
                self.assertTrue(document.get("title"))
                self.assertGreater(len(document.get("description", "")), 40)

    def test_every_object_is_closed(self):
        for path in WP14_SCHEMA_PATHS:
            for where, node in self._objects(load_schema(path)):
                with self.subTest(schema=os.path.basename(path),
                                  location=where):
                    self.assertIs(node.get("additionalProperties"), False)

    def _objects(self, node, where="$", found=None):
        found = [] if found is None else found
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                found.append((where, node))
            for key, value in node.items():
                self._objects(value, "%s.%s" % (where, key), found)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                self._objects(item, "%s[%d]" % (where, index), found)
        return found

    def test_no_schema_uses_a_keyword_the_validator_cannot_check(self):
        """The validator raises on an unimplemented keyword, so running a real
        document through each schema is what proves this."""
        for payload, validate in (
                (self.input, validate_assessment_input),
                (self.computation, validate_assessment_computation),
                (self.medication, validate_medication_assessment),
                (self.finding, validate_assessment_finding),
                (self.failure, validate_assessment_failure),
                (self.report, validate_assessment_regression_report),
                (self.status, validate_wp14_gate_status)):
            with self.subTest(validator=validate.__name__):
                self.assertEqual(validate(payload), ())

    def test_contains_is_absent_from_every_schema(self):
        for path in WP14_SCHEMA_PATHS:
            with io.open(path, encoding="utf-8") as handle:
                text = handle.read()
            with self.subTest(schema=os.path.basename(path)):
                self.assertNotIn('"contains"', text)

    def test_the_stored_artifacts_on_disk_validate(self):
        for relative, validate in (
                (os.path.join("data", "assessments",
                              "wp14-real-gate-status.json"),
                 validate_wp14_gate_status),
                (os.path.join("data", "migration", "wp14",
                              "assessment-regression-report.json"),
                 validate_assessment_regression_report)):
            with io.open(os.path.join(REPO_ROOT, relative),
                         encoding="utf-8") as handle:
                document = json.load(handle)
            with self.subTest(artifact=relative):
                self.assertEqual(validate(document), ())


class TestTheSchemasRefuseWhatTheyShould(Wp14SchemaCase):

    def test_an_undeclared_field_is_refused(self):
        for payload, validate in (
                (self.input, validate_assessment_input),
                (self.computation, validate_assessment_computation),
                (self.finding, validate_assessment_finding),
                (self.status, validate_wp14_gate_status)):
            broken = dict(payload)
            broken["recommended_dose"] = "500mg"
            with self.subTest(validator=validate.__name__):
                self.assertTrue(validate(broken))

    def test_pilot_cannot_be_expressed_in_an_input_document(self):
        """Absent from the enumeration rather than refused at runtime: a
        document that could express a PILOT assessment could be stored."""
        broken = dict(self.input)
        broken["mode"] = OperationMode.PILOT.value
        self.assertTrue(validate_assessment_input(broken))

    def test_an_input_carrying_a_genotype_field_is_refused(self):
        for field in ("genotype", "diplotype", "vcf", "ehr",
                      "patient_narrative"):
            broken = dict(self.input)
            broken[field] = "anything"
            with self.subTest(field=field):
                self.assertTrue(validate_assessment_input(broken))

    def test_a_duplicate_medication_is_refused(self):
        broken = dict(self.input)
        broken["medications"] = [DRUG_1, DRUG_1]
        self.assertTrue(validate_assessment_input(broken))

    def test_an_empty_medication_list_is_refused(self):
        broken = dict(self.input)
        broken["medications"] = []
        self.assertTrue(validate_assessment_input(broken))

    def test_a_finding_cannot_be_not_assessed(self):
        broken = dict(self.finding)
        broken["attention_level"] = AttentionLevel.NOT_ASSESSED.value
        self.assertTrue(validate_assessment_finding(broken))

    def test_a_finding_cannot_cite_no_evidence(self):
        broken = dict(self.finding)
        broken["evidence_references"] = []
        self.assertTrue(validate_assessment_finding(broken))

    def test_a_finding_cannot_omit_its_rationale(self):
        broken = dict(self.finding)
        broken["rationale_reference"] = ""
        self.assertTrue(validate_assessment_finding(broken))

    def test_a_finding_may_omit_the_scientific_codes(self):
        """The governed rule outcome carries neither, so a schema requiring
        them would force every row to invent one."""
        payload = dict(self.finding)
        payload["effect_code"] = None
        payload["explanation_code"] = None
        self.assertEqual(validate_assessment_finding(payload), ())

    def test_a_finding_may_not_carry_a_blank_scientific_code(self):
        for field in ("effect_code", "explanation_code"):
            broken = dict(self.finding)
            broken[field] = ""
            with self.subTest(field=field):
                self.assertTrue(validate_assessment_finding(broken))

    def test_no_active_attention_requires_full_coverage(self):
        broken = json.loads(json.dumps(self.medication))
        broken["attention_level"] = AttentionLevel.NO_ACTIVE_ATTENTION.value
        broken["coverage_status"] = CoverageStatus.PARTIAL.value
        self.assertTrue(validate_medication_assessment(broken))

    def test_not_assessed_forbids_findings(self):
        broken = json.loads(json.dumps(self.medication))
        broken["attention_level"] = AttentionLevel.NOT_ASSESSED.value
        self.assertTrue(validate_medication_assessment(broken))

    def test_non_full_coverage_requires_a_reason(self):
        broken = json.loads(json.dumps(self.medication))
        broken["coverage_status"] = CoverageStatus.INSUFFICIENT.value
        broken["coverage_reason_codes"] = []
        self.assertTrue(validate_medication_assessment(broken))

    def test_full_coverage_carries_no_reason(self):
        broken = json.loads(json.dumps(self.medication))
        broken["coverage_status"] = CoverageStatus.FULL.value
        broken["coverage_reason_codes"] = ["SOME_AXES_NOT_COVERED"]
        self.assertTrue(validate_medication_assessment(broken))

    def test_the_same_couplings_hold_at_the_top_of_a_computation(self):
        broken = json.loads(json.dumps(self.computation))
        broken["overall_attention"] = \
            AttentionLevel.NO_ACTIVE_ATTENTION.value
        broken["overall_coverage"] = CoverageStatus.PARTIAL.value
        self.assertTrue(validate_assessment_computation(broken))

    def test_a_computation_missing_its_provenance_is_refused(self):
        broken = json.loads(json.dumps(self.computation))
        del broken["release_provenance"]
        self.assertTrue(validate_assessment_computation(broken))

    def test_a_provenance_missing_a_pinned_version_is_refused(self):
        for field in ("ruleset_content_hash", "coverage_manifest_hash",
                      "release_manifest_hash", "dataset_public_id",
                      "software_version_id"):
            broken = json.loads(json.dumps(self.computation))
            del broken["release_provenance"][field]
            with self.subTest(field=field):
                self.assertTrue(validate_assessment_computation(broken))

    def test_a_hash_that_is_not_a_digest_is_refused(self):
        broken = json.loads(json.dumps(self.computation))
        broken["output_hash"] = "not-a-digest"
        self.assertTrue(validate_assessment_computation(broken))

    def test_an_unknown_failure_code_is_refused(self):
        broken = dict(self.failure)
        broken["code"] = "ASSESSMENT_EVERYTHING_IS_FINE"
        self.assertTrue(validate_assessment_failure(broken))

    def test_every_published_failure_code_is_accepted(self):
        for code in FAILURE_CODES:
            payload = dict(self.failure)
            payload["code"] = code
            with self.subTest(code=code):
                self.assertEqual(validate_assessment_failure(payload), ())

    def test_a_refusal_cannot_claim_success(self):
        broken = dict(self.failure)
        broken["refused"] = False
        self.assertTrue(validate_assessment_failure(broken))

    def test_a_gate_status_with_no_blocker_is_refused(self):
        broken = json.loads(json.dumps(self.status))
        broken["blockers"] = []
        self.assertTrue(validate_wp14_gate_status(broken))

    def test_a_negative_assessment_count_is_refused(self):
        broken = json.loads(json.dumps(self.status))
        broken["assessment_state"]["real_completed_assessments"] = -1
        self.assertTrue(validate_wp14_gate_status(broken))

    def test_the_gate_schema_can_describe_a_non_zero_count(self):
        """Deliberately not pinned to zero: the count is the real state being
        reported, and a schema that fixed it would make the tool refuse its own
        honest output the day an assessment is legitimately executed."""
        altered = json.loads(json.dumps(self.status))
        altered["assessment_state"]["real_completed_assessments"] = 1
        self.assertEqual(validate_wp14_gate_status(altered), ())

    def test_the_real_counts_are_zero_today(self):
        for name, value in self.status["assessment_state"].items():
            with self.subTest(count=name):
                self.assertEqual(value, 0)


class TestTheSchemasStateTheBoundary(Wp14SchemaCase):

    def test_the_computation_schema_states_the_separation(self):
        description = load_schema(
            ASSESSMENT_COMPUTATION_SCHEMA_PATH)["description"].lower()
        self.assertIn("wp-14 calculates structured facts; wp-15 renders them",
                      description)
        self.assertIn("additionalproperties is false", description)

    def test_the_computation_schema_lists_what_the_hash_excludes(self):
        description = load_schema(
            ASSESSMENT_COMPUTATION_SCHEMA_PATH)["description"].lower()
        for excluded in ("assessment id", "actor", "clock", "insertion order",
                         "local paths", "report prose"):
            with self.subTest(excluded=excluded):
                self.assertIn(excluded, description)

    def test_the_computation_document_denies_being_a_report(self):
        note = self.computation["note"].lower()
        self.assertIn("not a report", note)
        self.assertIn("not a recommendation", note)

    def test_no_schema_is_named_for_a_report(self):
        for path in WP14_SCHEMA_PATHS:
            name = os.path.basename(path)
            with self.subTest(schema=name):
                for forbidden in ("report-", "rendered", "narrative",
                                  "markdown"):
                    self.assertNotIn(forbidden, name)


if __name__ == "__main__":
    unittest.main()
