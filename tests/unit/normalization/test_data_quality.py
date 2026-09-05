# -*- coding: utf-8 -*-
"""Data-quality metrics and the fail-closed gate (WP-07).

Two things are being protected. First, that every number in the report is
derived from the build's artifacts rather than typed by a person - checked by
recomputing all of them from the sealed files. Second, that the gate refuses
anything it cannot answer, and that nothing in this package can approve a
dataset.
"""

from __future__ import annotations

import ast
import io
import json
import os
import unittest

from pgx.normalization.build import (CanonicalBuildRequest,
                                     build_canonical_dataset, write_build)
from pgx.normalization.models import DuplicateClass
from pgx.normalization.quality import (DQ_REPORT_VERSION, DataQualityIssue,
                                       DataQualityIssueCode, GateDecision,
                                       Reconciliation, Severity,
                                       compare_with_artifacts, evaluate_quality,
                                       recount_from_build_path)
from pgx.normalization.errors import QualityGateError

from tests.unit.normalization._snapshot import (REPO_ROOT, RealSnapshotTestCase,
                                                SyntheticSnapshotTestCase)

QUALITY = os.path.join("pgx", "normalization", "quality.py")


def _source(relative: str) -> str:
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


class TestReconciliation(unittest.TestCase):

    def test_a_balanced_stream_balances(self):
        item = Reconciliation("s", 10, 6, 2, 2, "basis")
        self.assertTrue(item.balances)
        self.assertEqual(item.shortfall, 0)

    def test_an_unbalanced_stream_reports_its_shortfall(self):
        item = Reconciliation("s", 10, 6, 2, 0, "basis")
        self.assertFalse(item.balances)
        self.assertEqual(item.shortfall, 2)

    def test_a_negative_count_is_refused(self):
        with self.assertRaises(QualityGateError):
            Reconciliation("s", 10, -1, 0, 0, "basis")

    def test_a_boolean_is_not_an_integer_here(self):
        with self.assertRaises(QualityGateError):
            Reconciliation("s", 10, True, 0, 0, "basis")


class TestTheGateFailsClosed(unittest.TestCase):

    def _decision(self, issues):
        from pgx.normalization.quality import _decide
        return _decide(issues)

    def test_one_blocking_finding_refuses_the_check(self):
        decision = self._decision([DataQualityIssue(
            DataQualityIssueCode.SOURCE_POLICY_MISSING, Severity.BLOCKING,
            "d", "no approval on record")])
        self.assertFalse(decision.passed)
        self.assertEqual(decision.blocking_codes, ("SOURCE_POLICY_MISSING",))

    def test_advisory_findings_alone_do_not_block(self):
        decision = self._decision([DataQualityIssue(
            DataQualityIssueCode.SEMANTIC_DUPLICATE_CONTAINER,
            Severity.ADVISORY, "d", "case variants")])
        self.assertTrue(decision.passed)

    def test_a_passing_gate_says_it_is_not_a_decision(self):
        decision = self._decision([])
        self.assertTrue(decision.passed)
        self.assertIn("named reviewer", decision.rationale)

    def test_the_decision_has_no_override_argument(self):
        """A gate that can be argued down is not a gate."""
        names = set(GateDecision.__dataclass_fields__)
        for forbidden in ("override", "force", "ignore_codes", "threshold",
                          "allow"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, names)


class TestTheRealSnapshotIsBlocked(RealSnapshotTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.build = build_canonical_dataset(CanonicalBuildRequest(
            snapshot_root=cls.snapshot_path,
            output_root=os.path.join(cls.snapshot_path, "unused"),
            allow_new_identities=True))
        cls.report = evaluate_quality(cls.build)

    def test_the_gate_is_blocked(self):
        self.assertFalse(self.report.decision.passed)

    def test_a_quarantined_snapshot_blocks(self):
        self.assertIn("SNAPSHOT_QUARANTINED",
                      self.report.decision.blocking_codes)

    def test_a_legacy_import_blocks_because_completeness_is_unknown(self):
        self.assertIn("SNAPSHOT_NOT_ACQUIRED",
                      self.report.decision.blocking_codes)

    def test_a_missing_source_approval_blocks(self):
        self.assertIn("SOURCE_POLICY_MISSING",
                      self.report.decision.blocking_codes)

    def test_a_pending_source_policy_blocks_exactly_as_a_missing_one_does(self):
        pending = evaluate_quality(self.build, source_policy_status="PENDING")
        self.assertFalse(pending.decision.passed)
        self.assertIn("SOURCE_POLICY_NOT_APPROVED",
                      pending.decision.blocking_codes)

    def test_the_case_variant_duplicates_are_advisory_not_blocking(self):
        """The payloads are identical; only the container spelling differs."""
        self.assertIn("SEMANTIC_DUPLICATE_CONTAINER",
                      self.report.decision.advisory_codes)
        self.assertNotIn("SEMANTIC_DUPLICATE_CONTAINER",
                         self.report.decision.blocking_codes)

    def test_the_container_synonym_finding_is_reported_not_folded(self):
        """``label`` and ``DrugLabel`` are not case variants of each other."""
        codes = {issue.code.value for issue in self.report.issues}
        self.assertIn("CONTAINER_SYNONYM_UNREVIEWED", codes)

    def test_every_stream_reconciles(self):
        for item in self.report.reconciliations:
            with self.subTest(stream=item.stream):
                self.assertTrue(item.balances, item.to_json())

    def test_the_observation_stream_accounts_for_every_record(self):
        stream = {item.stream: item for item in self.report.reconciliations}
        observations = stream["source_record_observations"]
        self.assertEqual(observations.input_count,
                         self.build.dedup.total_observations)
        self.assertEqual(observations.rejected, 0,
                         "no observation is ever discarded")

    def test_the_report_is_deterministic(self):
        again = evaluate_quality(self.build)
        self.assertEqual(again.to_json(), self.report.to_json())
        self.assertEqual(again.content_hash(), self.report.content_hash())

    def test_the_report_carries_no_generation_timestamp(self):
        """A wall-clock value would make two evaluations of one build differ."""
        payload = json.dumps(self.report.to_json())
        for token in ("generated_at", "evaluated_at", "timestamp"):
            with self.subTest(token=token):
                self.assertNotIn(token, payload)

    def test_the_lifecycle_state_stays_building(self):
        self.assertEqual(self.report.dataset_lifecycle_state, "BUILDING")
        self.assertIn("remains BUILDING", self.report.to_json()["lifecycle_note"])

    def test_the_axes_use_observation_language(self):
        payload = json.dumps(self.report.to_json()).casefold()
        for forbidden in ("validated coverage", "clinical coverage",
                          "supported treatment", "safe alternative",
                          "executable pgx rule"):
            with self.subTest(phrase=forbidden):
                # Present only inside the explicit disclaimer, never as a label.
                index = payload.find(forbidden)
                if index >= 0:
                    prefix = payload[max(0, index - 4):index]
                    self.assertIn("not ", prefix)


class TestCountsComeFromTheArtifacts(RealSnapshotTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._root = None

    def _sealed(self):
        root = self.temp_output()
        build = build_canonical_dataset(CanonicalBuildRequest(
            snapshot_root=self.snapshot_path, output_root=root,
            allow_new_identities=True))
        report = evaluate_quality(build)
        return build, write_build(build, root, extra_documents={
            "dq-report.json": report.to_json()})

    def test_an_independent_recount_agrees_with_the_manifest(self):
        _, result = self._sealed()
        ok, problems = compare_with_artifacts(result.build_path)
        self.assertTrue(ok, problems)

    def test_the_recount_reads_the_files_rather_than_the_summary(self):
        build, result = self._sealed()
        counts = recount_from_build_path(result.build_path)
        self.assertEqual(counts["gene_count"], len(build.genes))
        self.assertEqual(counts["drug_count"], len(build.drugs))
        self.assertEqual(counts["duplicate_group_count"],
                         len(build.dedup.groups))

    def test_an_edited_summary_is_detected(self):
        """A report that cannot be reproduced from its artifacts is not
        evidence of anything."""
        _, result = self._sealed()
        manifest_path = os.path.join(result.build_path, "manifest.json")
        os.chmod(manifest_path, 0o600)
        with io.open(manifest_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["summary"]["gene_count"] = 99
        with io.open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        ok, problems = compare_with_artifacts(result.build_path)
        self.assertFalse(ok)
        self.assertTrue(any("gene_count" in problem for problem in problems))


class TestSyntheticFailures(SyntheticSnapshotTestCase):

    def _report(self, files):
        snapshot = self.seal(files)
        build = build_canonical_dataset(CanonicalBuildRequest(
            snapshot_root=snapshot, output_root=self.output_root(),
            allow_new_identities=True))
        return build, evaluate_quality(build)

    GENE_FILE = {"CYP2C19": {"objCls": "Gene", "id": "PA124",
                             "symbol": "CYP2C19", "name": "cytochrome"}}

    def test_a_broken_reference_blocks(self):
        """A pair naming a gene the dataset does not contain."""
        _, report = self._report({
            "responses/resolved_genes.json": self.GENE_FILE,
            "responses/pair_probe_raw.json": {
                "CYP3A5::aspirin": {"pair": {"variantAnnotation": []}}},
        })
        self.assertIn("BROKEN_REFERENCE", report.decision.blocking_codes)

    def test_a_conflicting_identity_collision_blocks(self):
        _, report = self._report({
            "responses/resolved_genes.json": self.GENE_FILE,
            "responses/pair_probe_raw.json": {
                "CYP2C19::x": {"pair": {
                    "variantAnnotation": [{"id": 1, "v": "left"}],
                    "VariantAnnotation": [{"id": 1, "v": "right"}]}}},
        })
        self.assertIn("CONFLICTING_IDENTITY_COLLISION",
                      report.decision.blocking_codes)

    def test_a_record_with_no_source_identity_blocks(self):
        _, report = self._report({
            "responses/resolved_genes.json": self.GENE_FILE,
            "responses/variant_annotation_filtered_raw.json": {
                "CYP2C19": [{"accessionId": "PA1", "note": "no id field"}]},
        })
        self.assertIn("RECORD_WITHOUT_SOURCE_IDENTITY",
                      report.decision.blocking_codes)

    def test_two_entities_claiming_one_accession_blocks(self):
        _, report = self._report({
            "responses/resolved_genes.json": {
                "CYP2C19": {"objCls": "Gene", "id": "PA124",
                            "symbol": "CYP2C19", "name": "a"},
                "CYP2D6": {"objCls": "Gene", "id": "PA124",
                           "symbol": "CYP2D6", "name": "b"}},
        })
        self.assertIn("EXTERNAL_ID_CLAIMED_BY_SEVERAL_ENTITIES",
                      report.decision.blocking_codes)

    def test_an_unnormalisable_candidate_blocks(self):
        _, report = self._report({
            "responses/resolved_genes.json": {
                "CYP2C19": {"objCls": "Gene", "id": "PA124",
                            "symbol": "CYP2C19", "name": "a"},
                "BAD": {"objCls": "Gene", "id": "PA999",
                        "symbol": "***", "name": "b"}},
        })
        self.assertIn("CANDIDATE_NOT_NORMALIZABLE",
                      report.decision.blocking_codes)


class TestNoApprovalPathExists(unittest.TestCase):

    def test_the_module_defines_no_approval_function(self):
        tree = ast.parse(_source(QUALITY), filename=QUALITY)
        names = {node.name for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)}
        for forbidden in ("approve", "mark_quality_checked", "publish",
                          "activate", "promote", "transition", "sign_off",
                          "auto_approve"):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, names)

    def test_no_published_or_activated_state_is_referenced(self):
        tree = ast.parse(_source(QUALITY), filename=QUALITY)
        constants = {node.value for node in ast.walk(tree)
                     if isinstance(node, ast.Constant)
                     and isinstance(node.value, str)}
        self.assertNotIn("PUBLISHED", constants)
        self.assertNotIn("ACTIVE", constants)

    def test_the_only_lifecycle_state_it_writes_is_building(self):
        from pgx.normalization.quality import DataQualityReport
        self.assertEqual(
            DataQualityReport.__dataclass_fields__[
                "dataset_lifecycle_state"].default, "BUILDING")

    def test_the_report_version_is_recorded(self):
        self.assertTrue(DQ_REPORT_VERSION.strip())


class TestIssueCodesAreStable(unittest.TestCase):

    def test_every_code_is_screaming_snake_case_and_matches_its_value(self):
        for code in DataQualityIssueCode:
            with self.subTest(code=code.name):
                self.assertEqual(code.name, code.value)
                self.assertEqual(code.value, code.value.upper())

    def test_examples_are_bounded_so_a_report_stays_readable(self):
        issue = DataQualityIssue(
            DataQualityIssueCode.SEMANTIC_DUPLICATE_CONTAINER,
            Severity.ADVISORY, "s", "d", count=2000,
            examples=tuple(str(index) for index in range(100)))
        self.assertEqual(len(issue.examples), 5)
        self.assertEqual(issue.count, 2000,
                         "the count is the whole finding, not the sample size")


if __name__ == "__main__":
    unittest.main()


class TestThePublishedSchemasAreApplied(RealSnapshotTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.build = build_canonical_dataset(CanonicalBuildRequest(
            snapshot_root=cls.snapshot_path,
            output_root=os.path.join(cls.snapshot_path, "unused"),
            allow_new_identities=True))

    def test_the_dq_report_validates(self):
        from pgx.application.canonical_schema import validate_dq_report
        report = evaluate_quality(self.build).to_json()
        self.assertEqual(validate_dq_report(report), ())

    def test_a_report_with_an_imbalanced_stream_fails_the_schema(self):
        """input = accepted + rejected + deferred is asserted in the schema,
        not only in prose."""
        from pgx.application.canonical_schema import validate_dq_report
        report = evaluate_quality(self.build).to_json()
        report["reconciliations"][0]["balances"] = False
        report["reconciliations"][0]["shortfall"] = 3
        self.assertNotEqual(validate_dq_report(report), ())

    def test_a_report_claiming_quality_checked_fails_the_schema(self):
        from pgx.application.canonical_schema import validate_dq_report
        report = evaluate_quality(self.build).to_json()
        report["dataset_lifecycle_state"] = "QUALITY_CHECKED"
        self.assertNotEqual(validate_dq_report(report), ())

    def test_the_schema_validator_refuses_an_unimplemented_keyword(self):
        """A published constraint that is silently unchecked is worse than
        none: the schema would look enforced and would not be."""
        from pgx.application.snapshot_schema import (SchemaSupportError,
                                                     validate_against_schema)
        with self.assertRaises(SchemaSupportError):
            validate_against_schema({}, {"type": "object",
                                         "unevaluatedProperties": False})
