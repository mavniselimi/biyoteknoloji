# -*- coding: utf-8 -*-
"""Assembling and sealing a canonical build (WP-07).

Two properties matter more than any single count: the build is reproducible
from the same snapshot and the same identity allocation, and a sealed build can
never be overwritten. Both are checked against the real legacy snapshot, so a
regression shows up on the data this project actually holds.
"""

from __future__ import annotations

import ast
import io
import json
import os
import shutil
import tempfile
import unittest

from pgx.normalization.build import (BUILD_FILES, CANONICAL_BUILD_LAYOUT_VERSION,
                                     PROVENANCE_BEARING_FILES,
                                     CanonicalBuildRequest,
                                     build_canonical_dataset, compare_builds,
                                     read_build_manifest, verify_build,
                                     write_build)
from pgx.normalization.errors import AllocationError, CanonicalBuildError
from pgx.normalization.models import EntityType
from pgx.normalization.quality import evaluate_quality

from tests.unit.normalization._snapshot import (DATASET_ID, REPO_ROOT,
                                                RealSnapshotTestCase,
                                                SyntheticSnapshotTestCase,
                                                make_writable)

BUILD = os.path.join("pgx", "normalization", "build.py")


def _source(relative: str) -> str:
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


class TestBuildingTheRealSnapshot(RealSnapshotTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.build = build_canonical_dataset(CanonicalBuildRequest(
            snapshot_root=cls.snapshot_path,
            output_root=os.path.join(cls.snapshot_path, "unused"),
            allow_new_identities=True))

    def test_it_produces_the_five_queried_genes(self):
        self.assertEqual(
            [entity.normalized_value for entity in self.build.genes],
            ["CYP1A2", "CYP2C19", "CYP2C9", "CYP2D6", "CYP3A4"])

    def test_it_produces_the_eleven_source_resolved_drugs(self):
        """Eleven, not the fifteen in the mutated legacy seed.

        The four extra drugs there came from candidate onboarding, not from a
        source response, and importing them would add drugs no reviewer chose.
        """
        names = [entity.normalized_value for entity in self.build.drugs]
        self.assertEqual(len(names), 11)
        for excluded in ("nortriptyline", "pantoprazole", "prasugrel",
                         "ticagrelor"):
            self.assertNotIn(excluded, names)

    def test_every_entity_carries_provenance(self):
        for entity in self.build.entities:
            with self.subTest(key=entity.canonical_key):
                self.assertTrue(entity.locators)
                self.assertEqual(entity.locators[0].dataset_public_id,
                                 DATASET_ID)

    def test_every_entity_carries_its_source_accession(self):
        for entity in self.build.entities:
            with self.subTest(key=entity.canonical_key):
                namespaces = {item.namespace for item in entity.external_ids}
                self.assertIn("clinpgx", namespaces)

    def test_every_entity_has_an_allocated_identity(self):
        for entity in self.build.entities:
            with self.subTest(key=entity.canonical_key):
                self.assertEqual(
                    entity.entity_uuid,
                    self.build.allocation.uuid_for(entity.canonical_key))

    def test_no_alias_is_approved_because_nobody_approved_one(self):
        for entity in self.build.entities:
            with self.subTest(key=entity.canonical_key):
                self.assertEqual(entity.approved_aliases, ())

    def test_the_case_variant_collisions_are_all_semantic_duplicates(self):
        """LEGACY-BUG-004, measured on the real response.

        The count is asserted as an equality so a change to the dedup key or to
        the snapshot shows up rather than passing quietly; the exact figure is
        reported in the legacy difference report and in the handoff.
        """
        summary = self.build.summary()
        self.assertEqual(summary["duplicate_group_count"], 1644)
        self.assertEqual(summary["duplicate_observation_count"], 1644)
        self.assertEqual(summary["blocking_duplicate_group_count"], 0)

    def test_no_conflicting_identity_collision_exists_in_this_snapshot(self):
        from pgx.normalization.models import DuplicateClass
        self.assertEqual(
            self.build.dedup.of_class(DuplicateClass.CONFLICTING_IDENTITY), ())

    def test_every_pair_reference_resolves(self):
        unresolved = [item for item in self.build.resolutions
                      if not item.is_resolved]
        self.assertEqual(unresolved, [])
        self.assertEqual(self.build.queue, ())

    def test_the_axes_are_named_for_observation_not_for_coverage(self):
        axes = self.build.extraction.source_observed_axes
        for key in axes:
            with self.subTest(key=key):
                self.assertFalse(key.startswith("validated"))
                self.assertFalse(key.startswith("clinical"))
                self.assertFalse(key.startswith("supported"))
        self.assertIn("source_observed_gene_count", axes)
        self.assertIn("not validated coverage", axes["basis"].casefold())

    def test_candidate_data_is_counted_and_excluded(self):
        excluded = self.build.extraction.excluded_record_counts
        self.assertTrue(excluded)
        self.assertGreater(sum(excluded.values()), 0)
        # And none of it became an entity.
        names = {entity.normalized_value for entity in self.build.drugs}
        self.assertNotIn("prasugrel", names)

    def test_the_derived_csvs_are_confirmed_derived_on_every_build(self):
        checks = {check.derived_artifact: check
                  for check in self.build.extraction.derivation_checks}
        self.assertIn("resolved_genes.csv", checks)
        self.assertIn("resolved_chemicals.csv", checks)
        for name, check in checks.items():
            with self.subTest(artifact=name):
                self.assertTrue(check.consistent, check.to_json())

    def test_the_json_and_its_derived_csv_are_not_counted_twice(self):
        reports = {report.file_name: report
                   for report in self.build.extraction.reports}
        self.assertTrue(reports["resolved_genes.json"].read)
        self.assertFalse(reports["resolved_genes.csv"].read)
        self.assertEqual(reports["resolved_genes.csv"].entity_candidate_count, 0)

    def test_the_snapshot_stays_quarantined_and_the_dataset_stays_building(self):
        self.assertEqual(self.build.snapshot_state, "QUARANTINED")
        report = evaluate_quality(self.build)
        self.assertEqual(report.dataset_lifecycle_state, "BUILDING")

    def test_every_rule_version_is_recorded(self):
        for name, value in self.build.rule_versions.items():
            with self.subTest(rule=name):
                self.assertTrue(str(value).strip())


class TestSealing(RealSnapshotTestCase):
    """One sealed build, inspected many ways.

    Sealed once in ``setUpClass`` rather than once per test: building the real
    snapshot takes a second or two, and eight rebuilds of the same bytes would
    buy nothing. The one test that genuinely needs a second write - the
    overwrite refusal - makes its own.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._roots = []
        cls.result = cls._seal(cls)

    @classmethod
    def tearDownClass(cls):
        for root in cls._roots:
            make_writable(root)
            shutil.rmtree(root, ignore_errors=True)

    @staticmethod
    def _seal(owner, output_root=None, allocation=None):
        root = output_root
        if root is None:
            root = tempfile.mkdtemp(prefix="pgx-wp07-seal-")
            TestSealing._roots.append(root)
        build = build_canonical_dataset(CanonicalBuildRequest(
            snapshot_root=TestSealing.snapshot_path, output_root=root,
            allocation_path=allocation,
            allow_new_identities=allocation is None))
        report = evaluate_quality(build)
        return write_build(build, root,
                           extra_documents={"dq-report.json": report.to_json()})

    def test_it_writes_every_layout_file_it_produced(self):
        present = set(os.listdir(self.result.build_path))
        expected = set(BUILD_FILES) - {"legacy-differences.json"}
        self.assertEqual(present, expected)

    def test_a_sealed_build_verifies_against_its_own_checksums(self):
        ok, problems = verify_build(self.result.build_path)
        self.assertTrue(ok, problems)

    def test_a_second_write_to_the_same_place_is_refused(self):
        root = self.temp_output()
        self._seal(self, root)
        with self.assertRaises(CanonicalBuildError) as caught:
            self._seal(self, root)
        self.assertEqual(caught.exception.code, "BUILD_ALREADY_EXISTS")

    def test_no_staging_directory_survives_a_successful_seal(self):
        root = os.path.dirname(self.result.build_path)
        leftovers = [name for name in os.listdir(root)
                     if name.startswith(".staging")]
        self.assertEqual(leftovers, [])

    def test_the_manifest_records_the_layout_version(self):
        manifest = read_build_manifest(self.result.build_path)
        self.assertEqual(manifest["canonical_build_layout_version"],
                         CANONICAL_BUILD_LAYOUT_VERSION)

    def test_the_manifest_says_the_dataset_is_still_building(self):
        manifest = read_build_manifest(self.result.build_path)
        self.assertEqual(manifest["dataset_lifecycle_state"], "BUILDING")
        self.assertNotIn("QUALITY_CHECKED", json.dumps(manifest["summary"]))

    def test_the_ndjson_files_are_sorted_and_canonically_encoded(self):
        path = os.path.join(self.result.build_path, "genes.ndjson")
        with io.open(path, encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        keys = [row["canonical_key"] for row in rows]
        self.assertEqual(keys, sorted(keys))
        with io.open(path, encoding="utf-8") as handle:
            first = handle.readline()
        self.assertNotIn(", ", first, "canonical JSON uses tight separators")

    def test_provenance_has_one_row_per_entity_locator(self):
        with io.open(os.path.join(self.result.build_path, "provenance.ndjson"),
                     encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        expected = sum(len(entity.locators)
                       for entity in self.result.build.entities)
        self.assertEqual(len(rows), expected)


class TestReproducibility(RealSnapshotTestCase):

    def test_the_same_snapshot_and_allocation_rebuild_identically(self):
        first_root = self.temp_output()
        second_root = self.temp_output()

        first_build = build_canonical_dataset(CanonicalBuildRequest(
            snapshot_root=self.snapshot_path, output_root=first_root,
            allow_new_identities=True))
        first = write_build(
            first_build, first_root,
            extra_documents={"dq-report.json":
                             evaluate_quality(first_build).to_json()})

        allocation = os.path.join(first.build_path, "identity-allocation.json")
        second_build = build_canonical_dataset(CanonicalBuildRequest(
            snapshot_root=self.snapshot_path, output_root=second_root,
            allocation_path=allocation, allow_new_identities=False))
        second = write_build(
            second_build, second_root,
            extra_documents={"dq-report.json":
                             evaluate_quality(second_build).to_json()})

        comparison = compare_builds(first.build_path, second.build_path)
        self.assertTrue(comparison.reproducible, comparison.to_json())
        self.assertEqual(set(comparison.differing_files),
                         set(PROVENANCE_BEARING_FILES))

    def test_a_rebuild_mints_no_identity(self):
        root = self.temp_output()
        build = build_canonical_dataset(CanonicalBuildRequest(
            snapshot_root=self.snapshot_path, output_root=root,
            allow_new_identities=True))
        result = write_build(build, root, extra_documents={
            "dq-report.json": evaluate_quality(build).to_json()})
        rebuilt = build_canonical_dataset(CanonicalBuildRequest(
            snapshot_root=self.snapshot_path,
            output_root=self.temp_output(),
            allocation_path=os.path.join(result.build_path,
                                         "identity-allocation.json")))
        self.assertEqual(rebuilt.allocation_result.minted, ())

    def test_building_without_an_allocation_and_without_permission_fails(self):
        with self.assertRaises(AllocationError):
            build_canonical_dataset(CanonicalBuildRequest(
                snapshot_root=self.snapshot_path,
                output_root=self.temp_output()))


class TestUnknownArtifactsAreReportedNotInterpreted(SyntheticSnapshotTestCase):

    def _build(self, files):
        snapshot = self.seal(files)
        return build_canonical_dataset(CanonicalBuildRequest(
            snapshot_root=snapshot, output_root=self.output_root(),
            allow_new_identities=True))

    def test_an_unmapped_artifact_is_named_and_left_unread(self):
        build = self._build({
            "responses/resolved_genes.json": {
                "CYP2C19": {"objCls": "Gene", "id": "PA124",
                            "symbol": "CYP2C19", "name": "cytochrome"}},
            "responses/mystery_payload.json": {"rows": [{"id": "X1"}]},
        })
        self.assertIn("mystery_payload.json",
                      build.extraction.unrecognised_artifacts)
        reports = {item.file_name: item for item in build.extraction.reports}
        self.assertFalse(reports["mystery_payload.json"].read)

    def test_nothing_from_an_unmapped_artifact_becomes_an_entity(self):
        build = self._build({
            "responses/resolved_genes.json": {
                "CYP2C19": {"objCls": "Gene", "id": "PA124",
                            "symbol": "CYP2C19", "name": "cytochrome"}},
            "responses/mystery_payload.json": {
                "CYP3A5": {"objCls": "Gene", "id": "PA999",
                           "symbol": "CYP3A5", "name": "invented"}},
        })
        self.assertEqual([entity.normalized_value for entity in build.genes],
                         ["CYP2C19"])

    def test_an_unmapped_artifact_blocks_the_quality_gate(self):
        build = self._build({
            "responses/resolved_genes.json": {
                "CYP2C19": {"objCls": "Gene", "id": "PA124",
                            "symbol": "CYP2C19", "name": "cytochrome"}},
            "responses/mystery_payload.json": {"rows": []},
        })
        report = evaluate_quality(build)
        self.assertIn("UNRECOGNISED_ARTIFACT", report.decision.blocking_codes)


class TestBuilderMintsNoIdentity(unittest.TestCase):

    def test_the_build_module_never_calls_uuid(self):
        """Identity comes from the allocation artifact and nowhere else."""
        tree = ast.parse(_source(BUILD), filename=BUILD)
        identifiers = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                identifiers.add(node.attr)
            elif isinstance(node, ast.Import):
                identifiers.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                identifiers.add(node.module)
        for token in ("uuid", "uuid4", "uuid5", "GeneId", "DrugId", "derive"):
            with self.subTest(token=token):
                self.assertNotIn(token, identifiers)

    def test_the_seal_uses_rename_and_never_replace(self):
        """``os.replace`` overwrites an existing target; ``os.rename`` refuses.

        Matched on ``os.<attr>`` specifically. A bare "replace" search would
        also catch ``str.replace``, which this module uses for timestamp
        spelling and which has nothing to do with sealing.
        """
        tree = ast.parse(_source(BUILD), filename=BUILD)
        os_calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and \
                    isinstance(node.func, ast.Attribute) and \
                    isinstance(node.func.value, ast.Name) and \
                    node.func.value.id == "os":
                os_calls.add(node.func.attr)
        self.assertIn("rename", os_calls)
        self.assertNotIn("replace", os_calls)

    def test_no_force_or_overwrite_parameter_exists(self):
        tree = ast.parse(_source(BUILD), filename=BUILD)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                names = {argument.arg for argument in node.args.args}
                names |= {argument.arg for argument in node.args.kwonlyargs}
                for forbidden in ("force", "overwrite", "replace_existing",
                                  "allow_overwrite"):
                    with self.subTest(function=node.name, argument=forbidden):
                        self.assertNotIn(forbidden, names)


if __name__ == "__main__":
    unittest.main()
