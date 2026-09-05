# -*- coding: utf-8 -*-
"""Artifact classification and reading a snapshot into candidates (WP-07).

The role map is the decision that keeps a JSON document and the CSV derived
from it from being counted as two independent scientific records. Everything
below either checks that decision or checks that it is re-verified rather than
assumed.
"""

from __future__ import annotations

import ast
import io
import os
import unittest

from pgx.normalization.artifacts import (ARTIFACT_ROLE_MAP,
                                         ARTIFACT_ROLE_MAP_VERSION,
                                         ArtifactRole, classify_artifacts,
                                         role_of)
from pgx.normalization.extract import (EXTRACTION_RULE_VERSION,
                                       FORBIDDEN_INTERPRETATION_KEYS,
                                       extract_snapshot, json_pointer)
from pgx.normalization.models import EntityType

from tests.unit.normalization._snapshot import (REPO_ROOT, RealSnapshotTestCase,
                                                SyntheticSnapshotTestCase)

EXTRACT = os.path.join("pgx", "normalization", "extract.py")


def _source(relative: str) -> str:
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


class TestTheRoleMap(unittest.TestCase):

    def test_the_two_resolved_csvs_are_comparison_only(self):
        for name in ("resolved_genes.csv", "resolved_chemicals.csv"):
            with self.subTest(artifact=name):
                entry = role_of(name)
                self.assertIs(entry.role, ArtifactRole.DERIVED_LEGACY_COMPARISON)
                self.assertFalse(entry.counts_as_evidence)

    def test_a_derived_file_names_what_it_was_derived_from(self):
        for entry in ARTIFACT_ROLE_MAP:
            if entry.role is not ArtifactRole.DERIVED_LEGACY_COMPARISON:
                continue
            with self.subTest(artifact=entry.file_name):
                self.assertTrue(entry.rationale.strip())

    def test_the_candidate_edge_files_are_out_of_scope_for_p0(self):
        for name in ("mvp_candidate_drug_gene_edges.json",
                     "mvp_candidate_drug_gene_edges.csv"):
            with self.subTest(artifact=name):
                entry = role_of(name)
                self.assertIs(entry.role,
                              ArtifactRole.OUT_OF_SCOPE_P1_CANDIDATE_DATA)
                self.assertFalse(entry.counts_as_evidence)

    def test_the_openapi_document_carries_no_scientific_record(self):
        self.assertIs(role_of("openapi_snapshot.json").role,
                      ArtifactRole.API_SCHEMA_REFERENCE)

    def test_an_unmapped_name_is_unrecognised_rather_than_guessed(self):
        entry = role_of("something_new.json")
        self.assertIs(entry.role, ArtifactRole.UNRECOGNISED)
        self.assertFalse(entry.counts_as_evidence)
        self.assertIn("Classify it", entry.rationale)

    def test_exactly_four_artifacts_may_contribute_records(self):
        evidence = [entry.file_name for entry in ARTIFACT_ROLE_MAP
                    if entry.counts_as_evidence]
        self.assertEqual(sorted(evidence), [
            "pair_probe_raw.json",
            "resolved_chemicals.json",
            "resolved_genes.json",
            "variant_annotation_filtered_raw.json",
        ])

    def test_classify_reports_what_the_map_expected_and_did_not_find(self):
        entries, missing = classify_artifacts(["resolved_genes.json"])
        self.assertEqual(len(entries), 1)
        self.assertIn("pair_probe_raw.json", missing)

    def test_the_map_version_is_recorded(self):
        self.assertTrue(ARTIFACT_ROLE_MAP_VERSION.strip())


class TestJsonPointer(unittest.TestCase):

    def test_it_escapes_slashes_and_tildes(self):
        """A container name is source data; an unescaped slash would address
        something else entirely."""
        self.assertEqual(json_pointer("a/b"), "/a~1b")
        self.assertEqual(json_pointer("a~b"), "/a~0b")

    def test_it_renders_indices(self):
        self.assertEqual(json_pointer("CYP2C19::x", "pair", "v", 3),
                         "/CYP2C19::x/pair/v/3")


class TestReadingTheRealSnapshot(RealSnapshotTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.result = extract_snapshot(cls.snapshot_path, cls.snapshot_manifest)

    def test_every_artifact_in_the_snapshot_is_classified(self):
        self.assertEqual(self.result.unrecognised_artifacts, ())
        self.assertEqual(self.result.missing_artifacts, ())

    def test_only_the_evidence_artifacts_were_read(self):
        read = {report.file_name for report in self.result.reports
                if report.read}
        self.assertEqual(read, {
            "resolved_genes.json", "resolved_chemicals.json",
            "pair_probe_raw.json", "variant_annotation_filtered_raw.json"})

    def test_every_observation_carries_a_source_record_identity(self):
        """Integer identifiers count. The variant annotations use them, and a
        reader that only accepted strings would report 3,348 anonymous records.
        """
        self.assertEqual(self.result.records_without_source_id, {})
        missing = [item for item in self.result.observations
                   if item.source_record_id is None]
        self.assertEqual(missing, [])

    def test_an_integer_source_id_is_rendered_exactly(self):
        variant = [item for item in self.result.observations
                   if item.record_type == "variant_annotation"][0]
        self.assertTrue(variant.source_record_id.isdigit())

    def test_the_label_containers_are_reported_as_synonyms_not_folded(self):
        synonyms = self.result.container_synonyms
        self.assertEqual(len(synonyms), 1)
        self.assertEqual(sorted(synonyms[0]["container_families"]),
                         ["druglabel", "label"])
        self.assertEqual(synonyms[0]["record_count"], 29)

    def test_the_case_variant_containers_are_folded_into_one_family(self):
        families = self.result.source_observed_axes[
            "source_observed_container_families"]
        self.assertEqual(sorted(families["variantannotation"]),
                         ["VariantAnnotation", "variantAnnotation"])

    def test_every_candidate_carries_a_locator_with_an_artifact_digest(self):
        for candidate in self.result.candidates:
            with self.subTest(value=candidate.submitted_value):
                self.assertTrue(
                    candidate.locator.artifact_sha256.startswith("sha256:"))

    def test_candidates_come_only_from_the_two_entity_inputs(self):
        paths = {candidate.locator.artifact_path
                 for candidate in self.result.candidates}
        self.assertEqual(paths, {"responses/resolved_genes.json",
                                 "responses/resolved_chemicals.json"})

    def test_the_pair_keys_produce_gene_and_drug_references(self):
        genes = [item for item in self.result.references
                 if item.entity_type is EntityType.GENE]
        drugs = [item for item in self.result.references
                 if item.entity_type is EntityType.DRUG]
        self.assertEqual(len(drugs), 13, "one per pair query")
        self.assertGreaterEqual(len(genes), 13)

    def test_candidate_edge_records_are_counted_and_excluded(self):
        self.assertIn("candidate_edge", self.result.excluded_record_counts)
        self.assertGreater(self.result.excluded_record_counts["candidate_edge"],
                           0)

    def test_the_derived_csvs_share_their_sources_identifier_set(self):
        for check in self.result.derivation_checks:
            with self.subTest(artifact=check.derived_artifact):
                self.assertTrue(check.consistent, check.to_json())

    def test_the_legacy_flattenings_are_flagged_as_interpretive(self):
        reports = {report.file_name: report for report in self.result.reports}
        note = reports["guideline_annotation_rows.csv"].note or ""
        self.assertIn("project-derived interpretation", note)

    def test_the_rule_version_is_recorded(self):
        self.assertEqual(self.result.extraction_rule_version,
                         EXTRACTION_RULE_VERSION)


class TestSyntheticShapes(SyntheticSnapshotTestCase):

    def _extract(self, files):
        from pgx.ingestion.snapshots import SnapshotManager
        snapshot = self.seal(files)
        manifest = SnapshotManager(self.raw_root).inspect_path(snapshot)
        return extract_snapshot(snapshot, manifest)

    def test_a_queried_name_that_differs_from_the_symbol_becomes_a_proposal(self):
        result = self._extract({"responses/resolved_genes.json": {
            "CYP2C19P1": {"objCls": "Gene", "id": "PA124",
                          "symbol": "CYP2C19", "name": "cytochrome"}}})
        candidate = result.candidates[0]
        self.assertEqual(candidate.normalized_value, "CYP2C19")
        aliases = [item.normalized_alias for item in candidate.alias_proposals]
        self.assertEqual(aliases, ["CYP2C19P1"])

    def test_a_proposal_arrives_unreviewed(self):
        result = self._extract({"responses/resolved_genes.json": {
            "CYP2C19P1": {"objCls": "Gene", "id": "PA124",
                          "symbol": "CYP2C19", "name": "cytochrome"}}})
        for proposal in result.candidates[0].alias_proposals:
            with self.subTest(alias=proposal.normalized_alias):
                self.assertFalse(proposal.resolves)
                self.assertIsNone(proposal.reviewed_by)

    def test_an_unnormalisable_symbol_becomes_a_finding_not_an_entity(self):
        result = self._extract({"responses/resolved_genes.json": {
            "BAD": {"objCls": "Gene", "id": "PA1", "symbol": "***",
                    "name": "x"}}})
        candidate = result.candidates[0]
        self.assertIsNone(candidate.normalized_value)
        self.assertTrue(candidate.findings)

    def test_a_malformed_accession_is_kept_with_its_problem(self):
        result = self._extract({"responses/resolved_genes.json": {
            "CYP2C19": {"objCls": "Gene", "id": "not-an-id",
                        "symbol": "CYP2C19", "name": "x"}}})
        candidate = result.candidates[0]
        self.assertEqual([item.to_json() for item in candidate.external_ids],
                         ["clinpgx:not-an-id"])
        self.assertTrue(candidate.findings)

    def test_a_cross_reference_is_read_with_its_own_namespace(self):
        result = self._extract({"responses/resolved_genes.json": {
            "CYP2C19": {"objCls": "Gene", "id": "PA124", "symbol": "CYP2C19",
                        "name": "x", "crossReferences": [
                            {"resource": "HGNC", "resourceId": "HGNC:2621"}]}}})
        values = {item.to_json() for item in result.candidates[0].external_ids}
        self.assertIn("hgnc:HGNC:2621", values)


class TestExtractionCarriesNoInterpretation(unittest.TestCase):

    def test_the_forbidden_key_list_covers_the_legacy_columns(self):
        for token in ("significance", "polarity", "score", "severity",
                      "manual_effect_hint", "recommendation", "risk"):
            with self.subTest(token=token):
                self.assertIn(token, FORBIDDEN_INTERPRETATION_KEYS)

    def test_no_forbidden_key_is_ever_read_from_a_record(self):
        """Every ``record.get("...")`` in the extractor, checked by name."""
        tree = ast.parse(_source(EXTRACT), filename=EXTRACT)
        read_keys = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and \
                    isinstance(node.func, ast.Attribute) and \
                    node.func.attr == "get" and node.args and \
                    isinstance(node.args[0], ast.Constant) and \
                    isinstance(node.args[0].value, str):
                read_keys.add(node.args[0].value)
        for token in FORBIDDEN_INTERPRETATION_KEYS:
            with self.subTest(key=token):
                self.assertNotIn(token, read_keys)

    def test_the_extractor_resolves_nothing(self):
        tree = ast.parse(_source(EXTRACT), filename=EXTRACT)
        identifiers = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                identifiers.add(node.attr)
            elif isinstance(node, ast.ImportFrom) and node.module:
                identifiers.add(node.module)
        for token in ("EntityResolver", "CanonicalCatalog", "resolve",
                      "resolve_reference", "uuid4", "allocate_identities"):
            with self.subTest(token=token):
                self.assertNotIn(token, identifiers)


if __name__ == "__main__":
    unittest.main()
