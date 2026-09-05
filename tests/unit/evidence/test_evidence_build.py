# -*- coding: utf-8 -*-
"""Gates, modes, sealing and reproducibility for an evidence build (WP-08).

Two modes with one difference. ``PRODUCTION`` fails closed on any blocking
finding. ``LEGACY_MIGRATION`` records the same findings, keeps them blocking,
and marks the whole build ineligible. Quarantine stores blockers; it never
softens them into warnings.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest

from pgx.evidence.build import (EVIDENCE_BUILD_FILES,
                                PROVENANCE_BEARING_FILES,
                                EvidenceBuildRequest, ImportMode,
                                build_evidence, compare_evidence_builds,
                                evidence_build_key, read_evidence_manifest,
                                verify_evidence_build, write_evidence_build)
from pgx.evidence.errors import EvidenceBuildError, EvidenceGateError
from pgx.evidence.payloads import (PayloadRelation, choose_maximal_payload,
                                   describe_payload_difference,
                                   is_projection_of)

from tests.unit.evidence._support import (CANONICAL_BUILD, DATASET_ID,
                                          RealEvidenceBuildTestCase,
                                          SNAPSHOT_ROOT,
                                          legacy_migration_build,
                                          require_sealed_inputs)


class TestPayloadComparisonIsRecursive(unittest.TestCase):
    """A shallow ``==`` mistook a projection for a disagreement.

    ``{'id': 1}`` against ``{'id': 1, 'phenotype': 'PM'}`` is one record seen
    through two containers, not two records that disagree. A top-level
    comparison reported 82 variant-annotation groups as conflicts; the answer
    is 0, and the difference is whether the check recurses.
    """

    def test_a_subset_at_the_top_level_is_a_projection(self):
        self.assertTrue(is_projection_of({"id": 1}, {"id": 1, "extra": 2}))

    def test_a_subset_nested_in_a_dict_is_still_a_projection(self):
        self.assertTrue(is_projection_of(
            {"a": {"id": 1}}, {"a": {"id": 1, "extra": 2}, "b": 3}))

    def test_a_subset_inside_a_list_element_is_still_a_projection(self):
        self.assertTrue(is_projection_of(
            {"xs": [{"id": 1}]}, {"xs": [{"id": 1, "extra": 2}]}))

    def test_lists_of_different_lengths_are_not_projections(self):
        """Padding or truncating would make two different records agree."""
        self.assertFalse(is_projection_of({"xs": [1]}, {"xs": [1, 2]}))

    def test_a_changed_value_is_a_conflict_not_a_projection(self):
        self.assertFalse(is_projection_of({"id": 1}, {"id": 2}))

    def test_the_maximal_payload_is_the_one_the_others_project_into(self):
        payloads = [{"id": 1}, {"id": 1, "extra": 2}, {"id": 1}]
        relation, chosen = choose_maximal_payload(payloads)
        self.assertEqual(relation, PayloadRelation.PROJECTION)
        self.assertEqual(chosen, {"id": 1, "extra": 2})

    def test_identical_payloads_are_reported_as_identical(self):
        relation, chosen = choose_maximal_payload([{"id": 1}, {"id": 1}])
        self.assertEqual(relation, PayloadRelation.IDENTICAL)
        self.assertEqual(chosen, {"id": 1})

    def test_a_real_disagreement_is_a_conflict_and_names_the_difference(self):
        relation, chosen = choose_maximal_payload([{"id": 1}, {"id": 2}])
        self.assertEqual(relation, PayloadRelation.CONFLICT)
        self.assertIsNone(chosen)
        self.assertTrue(describe_payload_difference({"id": 1}, {"id": 2}))


class TestTheProductionGateFailsClosed(unittest.TestCase):

    def _request(self, mode, output_root):
        return EvidenceBuildRequest(
            snapshot_root=SNAPSHOT_ROOT,
            canonical_build_path=CANONICAL_BUILD,
            output_root=output_root, mode=mode,
            allow_new_identities=True)

    def setUp(self):
        require_sealed_inputs(self)
        self.root = tempfile.mkdtemp(prefix="wp08-gate-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_a_quarantined_snapshot_refuses_a_production_import(self):
        with self.assertRaises(EvidenceGateError) as caught:
            build_evidence(self._request(ImportMode.PRODUCTION, self.root))
        codes = {issue.code.value if hasattr(issue.code, "value")
                 else issue.code for issue in caught.exception.issues}
        self.assertIn("RAW_SNAPSHOT_QUARANTINED", codes)
        self.assertIn("SOURCE_POLICY_MISSING", codes)

    def test_legacy_migration_proceeds_and_keeps_the_blockers_blocking(self):
        build = legacy_migration_build(self.root)
        self.assertTrue(build.blocking_issues)
        self.assertFalse(build.is_production_eligible)
        for issue in build.blocking_issues:
            self.assertEqual(str(issue.severity), "BLOCKING")

    def test_a_quarantined_build_wears_every_label_that_says_so(self):
        build = legacy_migration_build(self.root)
        for label in ("QUARANTINED", "LEGACY_MIGRATION", "NOT_CURATED",
                      "NOT_EXECUTABLE", "NOT_PUBLICATION_ELIGIBLE"):
            self.assertIn(label, build.lifecycle_labels)

    def test_the_manifest_carries_no_approval_and_no_reviewer(self):
        result = write_evidence_build(legacy_migration_build(self.root),
                                      self.root)
        manifest = read_evidence_manifest(result.build_path)
        self.assertTrue(manifest)
        for forbidden in ("approved_by", "approved_at", "reviewed_by",
                          "reviewer", "signed_off_by", "curated_by"):
            self.assertNotIn(forbidden, manifest)
        self.assertEqual(manifest["dataset_lifecycle_state"], "BUILDING")


class TestSealingIsAtomicAndFinal(unittest.TestCase):
    """One seal, shared by the tests that only read it.

    Sealing writes 36MB. Doing it per test spent most of this file's runtime
    re-writing identical bytes, so the read-only assertions share one sealed
    build and the one test that mutates a file makes its own.
    """

    @classmethod
    def setUpClass(cls):
        for path in (SNAPSHOT_ROOT, CANONICAL_BUILD):
            if not os.path.isdir(path):
                raise unittest.SkipTest("no sealed input at %s" % path)
        cls.root = tempfile.mkdtemp(prefix="wp08-seal-")
        cls.build = legacy_migration_build(cls.root)
        cls.result = write_evidence_build(cls.build, cls.root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "root", ""), ignore_errors=True)

    def test_a_sealed_build_holds_exactly_the_declared_files(self):
        present = sorted(name for name in os.listdir(self.result.build_path))
        self.assertEqual(present, sorted(EVIDENCE_BUILD_FILES))

    def test_a_second_write_is_refused_rather_than_overwriting(self):
        with self.assertRaises(EvidenceBuildError) as caught:
            write_evidence_build(self.build, self.root)
        self.assertEqual(getattr(caught.exception, "code", None),
                         "BUILD_ALREADY_EXISTS")

    def test_no_staging_directory_survives_a_successful_seal(self):
        leftovers = [name for name in os.listdir(self.root)
                     if name.startswith(".")]
        self.assertEqual(leftovers, [])

    def test_a_sealed_build_verifies_against_its_own_digests(self):
        ok, problems = verify_evidence_build(self.result.build_path)
        self.assertTrue(ok, problems)

    def test_a_tampered_file_fails_verification(self):
        copy_root = tempfile.mkdtemp(prefix="wp08-tamper-")
        self.addCleanup(shutil.rmtree, copy_root, True)
        copied = os.path.join(copy_root, DATASET_ID)
        shutil.copytree(self.result.build_path, copied)
        target = os.path.join(copied, "evidence-records.ndjson")
        os.chmod(target, 0o600)
        with io.open(target, "a", encoding="utf-8") as handle:
            handle.write('{"record_uuid": "smuggled"}\n')
        ok, problems = verify_evidence_build(copied)
        self.assertFalse(ok)
        self.assertTrue(problems)

    def test_the_build_key_names_the_dataset_and_its_content(self):
        key = evidence_build_key(DATASET_ID, "sha256:" + "ab" * 32)
        self.assertTrue(key.startswith(DATASET_ID + "/"))
        self.assertNotIn("sha256:", key)

    def test_the_manifest_records_no_absolute_path(self):
        text = json.dumps(read_evidence_manifest(self.result.build_path))
        self.assertNotIn(self.root, text)
        self.assertNotIn(os.path.abspath(SNAPSHOT_ROOT), text)


class TestReproducibility(unittest.TestCase):

    def setUp(self):
        require_sealed_inputs(self)
        self.left = tempfile.mkdtemp(prefix="wp08-left-")
        self.right = tempfile.mkdtemp(prefix="wp08-right-")
        self.addCleanup(shutil.rmtree, self.left, True)
        self.addCleanup(shutil.rmtree, self.right, True)

    def _build(self, output_root, allocation_path=None):
        if allocation_path is None:
            build = legacy_migration_build(output_root)
        else:
            # A reproduction run is the point of this class, so this one is
            # assembled fresh with the recorded allocation rather than reused.
            build = build_evidence(EvidenceBuildRequest(
                snapshot_root=SNAPSHOT_ROOT,
                canonical_build_path=CANONICAL_BUILD,
                output_root=output_root, mode=ImportMode.LEGACY_MIGRATION,
                allocation_path=allocation_path, allow_new_identities=False))
        return write_evidence_build(build, output_root)

    def test_the_same_allocation_reproduces_every_file_but_the_provenance_two(self):
        first = self._build(self.left)
        allocation = os.path.join(first.build_path,
                                  "evidence-identity-allocation.json")
        second = self._build(self.right, allocation_path=allocation)
        comparison = compare_evidence_builds(first.build_path,
                                             second.build_path)
        self.assertTrue(comparison.reproducible)
        self.assertEqual(sorted(comparison.differing_files),
                         sorted(PROVENANCE_BEARING_FILES))

    def test_two_empty_directories_do_not_count_as_reproducing_each_other(self):
        """The three other conditions are all satisfiable by equal emptiness."""
        first = self._build(self.left)
        bare_a = os.path.join(self.right, "a")
        bare_b = os.path.join(self.right, "b")
        for path in (bare_a, bare_b):
            os.makedirs(path)
            shutil.copy(os.path.join(first.build_path, "manifest.json"), path)
        comparison = compare_evidence_builds(bare_a, bare_b)
        self.assertTrue(comparison.content_hash_matches)
        self.assertFalse(comparison.both_complete)
        self.assertFalse(comparison.reproducible)


class TestTheRealBuildSummary(RealEvidenceBuildTestCase):

    def test_the_recorded_counts_agree_with_the_files_beside_them(self):
        summary = self.manifest()["summary"]
        self.assertEqual(summary["record_count"],
                         len(self.rows("evidence-records.ndjson")))
        self.assertEqual(summary["blocking_issue_count"],
                         sum(1 for row in self.rows("import-issues.ndjson")
                             if row.get("severity") == "BLOCKING"))

    def test_the_build_is_not_production_eligible(self):
        manifest = self.manifest()
        self.assertFalse(manifest["production_eligible"])
        self.assertIn("NOT_PUBLICATION_ELIGIBLE", manifest["lifecycle_labels"])

    def test_every_rule_version_the_build_depended_on_is_recorded(self):
        versions = self.manifest()["rule_versions"]
        for key in ("evidence_record_version", "record_type_map_version",
                    "extraction_rule_version", "publication_parser_version",
                    "allocation_format_version"):
            self.assertIn(key, versions)
            self.assertTrue(versions[key])
