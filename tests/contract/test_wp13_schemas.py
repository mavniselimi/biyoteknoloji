# -*- coding: utf-8 -*-
"""The six WP-13 published schemas, as a downstream contract.

These documents are what a UI, a report renderer or another service reads
instead of reading this repository. Three properties matter.

They must be *checkable*: WP-06's validator raises on any keyword it does not
implement, so a schema using one would silently stop checking the constraint
its author wrote. Every schema here is run against a real document, which is
what proves no such keyword slipped in.

They must be *closed*: ``additionalProperties: false`` everywhere, so a field
nobody declared cannot arrive in a downstream reader looking official.

And they must *couple status to reason*, because that coupling is
SAFETY-INV-001 expressed in a format a downstream reader can enforce for
itself: FULL carries no reason, and everything else carries at least one.
"""

from __future__ import annotations

import io
import json
import os
import unittest

from pgx.application.coverage_gate_status import build_coverage_gate_status
from pgx.application.coverage_schema import (
    AXIS_COVERAGE_SCHEMA_PATH, COVERAGE_REGRESSION_REPORT_SCHEMA_PATH,
    COVERAGE_RESULT_SCHEMA_PATH, MEDICATION_COVERAGE_SCHEMA_PATH,
    RULESET_COVERAGE_MANIFEST_SCHEMA_PATH, WP13_GATE_STATUS_SCHEMA_PATH,
    WP13_SCHEMA_PATHS, load_schema, validate_axis_coverage,
    validate_coverage_regression_report, validate_coverage_result,
    validate_medication_coverage, validate_ruleset_coverage_manifest,
    validate_wp13_gate_status)
from pgx.domain.enums import CoverageReasonCode, CoverageStatus
from pgx.engine.coverage_legacy import build_coverage_regression_report
from tests.fixtures.wp13.synthetic import (DRUG_1, DRUG_2, GENE_1, GENE_2,
                                           GENE_3, UNKNOWN_DRUG,
                                           synthetic_conflict)
from tests.unit.engine._coverage_support import REPO_ROOT, SyntheticWorld


class Wp13SchemaCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.world = SyntheticWorld(expected_extra_gene=True)
        cls.manifest = cls.world.manifest.to_json()
        cls.result = cls.world.evaluate(
            medications=[DRUG_1, DRUG_2, UNKNOWN_DRUG],
            phenotypes={GENE_1: "POOR", GENE_2: "poor metabolizer",
                        GENE_3: "POOR"}).to_json()
        cls.conflicted = cls.world.evaluate(
            medications=[DRUG_1], phenotypes={GENE_1: "POOR"},
            conflicts=(synthetic_conflict(),)).to_json()
        cls.report = build_coverage_regression_report(REPO_ROOT)
        cls.status = build_coverage_gate_status(REPO_ROOT).to_json()

    @classmethod
    def tearDownClass(cls):
        cls.world.close()


class TestEverySchemaIsPresentAndWellFormed(Wp13SchemaCase):

    def test_all_six_documents_exist(self):
        self.assertEqual(len(WP13_SCHEMA_PATHS), 6)
        for path in WP13_SCHEMA_PATHS:
            with self.subTest(schema=os.path.basename(path)):
                self.assertTrue(os.path.isfile(path))

    def test_each_declares_an_identifier_and_a_description(self):
        for path in WP13_SCHEMA_PATHS:
            document = load_schema(path)
            with self.subTest(schema=os.path.basename(path)):
                self.assertTrue(document.get("$id"))
                self.assertTrue(document.get("title"))
                self.assertGreater(len(document.get("description", "")), 40)

    def test_each_is_a_closed_object(self):
        for path in WP13_SCHEMA_PATHS:
            document = load_schema(path)
            with self.subTest(schema=os.path.basename(path)):
                self.assertEqual(document.get("type"), "object")
                self.assertIs(document.get("additionalProperties"), False)

    def test_every_nested_object_is_closed_too(self):
        """A closed root with an open sub-object is an open document."""
        for path in WP13_SCHEMA_PATHS:
            document = load_schema(path)
            for where, node in self._objects(document):
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
        document through each schema is what proves this - a schema that
        merely *looked* fine could be silently checking less than it says."""
        for payload, validate in (
                (self.manifest, validate_ruleset_coverage_manifest),
                (self.result, validate_coverage_result),
                (self.result["medications"][0], validate_medication_coverage),
                (self.result["medications"][0]["axes"][0],
                 validate_axis_coverage),
                (self.report, validate_coverage_regression_report),
                (self.status, validate_wp13_gate_status)):
            with self.subTest(validator=validate.__name__):
                self.assertEqual(validate(payload), ())

    def test_contains_is_absent_from_every_schema(self):
        for path in WP13_SCHEMA_PATHS:
            with io.open(path, encoding="utf-8") as handle:
                text = handle.read()
            with self.subTest(schema=os.path.basename(path)):
                self.assertNotIn('"contains"', text)


class TestTheSchemasAcceptRealDocuments(Wp13SchemaCase):

    def test_the_coverage_manifest_validates(self):
        self.assertEqual(validate_ruleset_coverage_manifest(self.manifest), ())

    def test_every_status_the_engine_can_emit_validates(self):
        payloads = [self.result, self.conflicted]
        seen = set()
        for payload in payloads:
            self.assertEqual(validate_coverage_result(payload), ())
            seen.add(payload["status"])
            for medication in payload["medications"]:
                self.assertEqual(validate_medication_coverage(medication), ())
                seen.add(medication["status"])
                for axis in medication["axes"]:
                    self.assertEqual(validate_axis_coverage(axis), ())
                    seen.add(axis["status"])
        self.assertGreaterEqual(len(seen), 4)

    def test_the_regression_report_validates(self):
        self.assertEqual(validate_coverage_regression_report(self.report), ())

    def test_the_gate_status_validates(self):
        self.assertEqual(validate_wp13_gate_status(self.status), ())

    def test_the_stored_artifacts_on_disk_validate(self):
        for relative, validate in (
                (os.path.join("data", "coverage",
                              "wp13-real-gate-status.json"),
                 validate_wp13_gate_status),
                (os.path.join("data", "migration", "wp13",
                              "coverage-regression-report.json"),
                 validate_coverage_regression_report)):
            with io.open(os.path.join(REPO_ROOT, relative),
                         encoding="utf-8") as handle:
                document = json.load(handle)
            with self.subTest(artifact=relative):
                self.assertEqual(validate(document), ())


class TestTheSchemasRefuseWhatTheyShould(Wp13SchemaCase):

    def test_an_undeclared_field_is_refused(self):
        for payload, validate in (
                (self.manifest, validate_ruleset_coverage_manifest),
                (self.result, validate_coverage_result),
                (self.status, validate_wp13_gate_status)):
            broken = dict(payload)
            broken["overall_attention"] = "LOW"
            with self.subTest(validator=validate.__name__):
                self.assertTrue(validate(broken))

    def test_an_unknown_status_is_refused(self):
        broken = dict(self.result)
        broken["status"] = "NO_ACTIVE_ATTENTION"
        self.assertTrue(validate_coverage_result(broken))

    def test_an_unknown_reason_code_is_refused(self):
        broken = dict(self.result)
        broken["reason_codes"] = ["EVERYTHING_IS_FINE"]
        self.assertTrue(validate_coverage_result(broken))

    def test_a_full_result_carrying_a_reason_is_refused(self):
        """SAFETY-INV-001, enforced in the format a downstream reader gets."""
        broken = dict(self.result)
        broken["status"] = CoverageStatus.FULL.value
        broken["reason_codes"] = [
            CoverageReasonCode.SOME_AXES_NOT_COVERED.value]
        self.assertTrue(validate_coverage_result(broken))

    def test_a_non_full_result_with_no_reason_is_refused(self):
        broken = dict(self.result)
        broken["status"] = CoverageStatus.INSUFFICIENT.value
        broken["reason_codes"] = []
        self.assertTrue(validate_coverage_result(broken))

    def test_the_same_coupling_holds_at_the_axis_level(self):
        axis = dict(self.result["medications"][0]["axes"][0])
        axis["status"] = CoverageStatus.INSUFFICIENT.value
        axis["reason_codes"] = []
        self.assertTrue(validate_axis_coverage(axis))

    def test_the_same_coupling_holds_at_the_medication_level(self):
        medication = dict(self.result["medications"][0])
        medication["status"] = CoverageStatus.FULL.value
        medication["reason_codes"] = [
            CoverageReasonCode.NO_VALIDATED_RULE_FOR_AXIS.value]
        self.assertTrue(validate_medication_coverage(medication))

    def test_a_manifest_declaring_no_drug_is_refused(self):
        broken = dict(self.manifest)
        broken["declarations"] = []
        self.assertTrue(validate_ruleset_coverage_manifest(broken))

    def test_a_declaration_with_an_empty_expected_scope_is_refused(self):
        """The load-bearing constraint. A drug with an empty expected scope
        can never be incompletely covered."""
        broken = json.loads(json.dumps(self.manifest))
        broken["declarations"][0]["expected_gene_keys"] = []
        self.assertTrue(validate_ruleset_coverage_manifest(broken))

    def test_a_declaration_missing_its_expected_scope_is_refused(self):
        broken = json.loads(json.dumps(self.manifest))
        del broken["declarations"][0]["expected_gene_keys"]
        self.assertTrue(validate_ruleset_coverage_manifest(broken))

    def test_a_key_without_its_canonical_prefix_is_refused(self):
        broken = json.loads(json.dumps(self.manifest))
        broken["declarations"][0]["drug_id"] = "testdrug-alpha"
        self.assertTrue(validate_ruleset_coverage_manifest(broken))

    def test_a_pin_that_is_not_a_digest_is_refused(self):
        broken = dict(self.manifest)
        broken["ruleset_content_hash"] = "not-a-digest"
        self.assertTrue(validate_ruleset_coverage_manifest(broken))

    def test_the_gate_status_schema_can_describe_a_non_zero_count(self):
        """Deliberately not pinned to zero.

        The count is the real state being reported, not a constant being
        asserted. A schema that fixed it at zero would make the tool refuse
        its own honest output the day a manifest is genuinely approved -
        turning a report into a claim, and an eventual success into a crash.
        What guarantees the count is zero *today* is the repository, checked
        below, and what guarantees a non-zero count cannot pass unnoticed is
        the blocker list, not the format.
        """
        altered = json.loads(json.dumps(self.status))
        altered["coverage_state"]["real_coverage_manifests"] = 1
        self.assertEqual(validate_wp13_gate_status(altered), ())

    def test_the_real_count_is_zero_and_a_blocker_says_why(self):
        self.assertEqual(
            self.status["coverage_state"]["real_coverage_manifests"], 0)
        codes = {item["code"] for item in self.status["blockers"]}
        self.assertIn("NO_APPROVED_COVERAGE_MANIFEST", codes)

    def test_a_negative_count_is_refused(self):
        broken = json.loads(json.dumps(self.status))
        broken["coverage_state"]["real_coverage_manifests"] = -1
        self.assertTrue(validate_wp13_gate_status(broken))

    def test_a_gate_status_with_no_blocker_is_refused(self):
        broken = json.loads(json.dumps(self.status))
        broken["blockers"] = []
        self.assertTrue(validate_wp13_gate_status(broken))

    def test_a_regression_report_with_an_unexpected_difference_still_validates(
            self):
        """The schema describes the shape; whether the content is acceptable
        is the harness's judgement, and conflating the two would let a schema
        pass hide a real regression."""
        altered = json.loads(json.dumps(self.report))
        altered["unexpected_differences"] = [
            {"source": "risk-p2-cyp2c19-poor.json", "drug": "codeine",
             "legacy_value": "none", "v2_coverage_status": "FULL"}]
        self.assertEqual(validate_coverage_regression_report(altered), ())
        self.assertEqual(self.report["unexpected_differences"], [])


class TestTheSchemasCarryNoAttentionVocabulary(Wp13SchemaCase):

    def test_no_schema_enumerates_an_attention_level(self):
        from pgx.domain.enums import AttentionLevel
        for path in WP13_SCHEMA_PATHS:
            with io.open(path, encoding="utf-8") as handle:
                text = handle.read()
            for level in AttentionLevel:
                with self.subTest(schema=os.path.basename(path),
                                  level=level.value):
                    self.assertNotIn('"%s"' % level.value, text)

    def test_the_coverage_result_schema_states_the_separation(self):
        """The schema is where the separation is actually enforced - by
        ``additionalProperties: false`` - so it is also where it is stated,
        for the downstream reader who never sees this repository."""
        document = load_schema(COVERAGE_RESULT_SCHEMA_PATH)
        description = document["description"].lower()
        self.assertIn("wp-13 computes coverage; wp-14 computes attention",
                      description)
        self.assertIn("additionalproperties is false", description)

    def test_the_result_document_itself_denies_being_an_attention_level(self):
        self.assertIn("not an attention level", self.result["note"].lower())

    def test_every_schema_path_is_named_for_coverage_not_assessment(self):
        for path in WP13_SCHEMA_PATHS:
            name = os.path.basename(path)
            with self.subTest(schema=name):
                for forbidden in ("assessment", "finding", "attention",
                                  "risk"):
                    self.assertNotIn(forbidden, name)


if __name__ == "__main__":
    unittest.main()
