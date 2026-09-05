# -*- coding: utf-8 -*-
"""E. Catalogues, evidence and system version.

All three read governed artifacts and derive nothing. What is checked here is
mostly what they *do not* do: no ranking, no scoring, no fuzzy matching, no
unbounded page, no source prose, no filesystem path, and never two releases in
one answer.
"""

from __future__ import annotations

import json
import unittest

from apps.api.adapters.catalog import (catalogue_context,
                                       drug_collection_document,
                                       gene_collection_document,
                                       supported_phenotype_vocabulary)
from apps.api.adapters.evidence import evidence_detail_document
from apps.api.adapters.version import system_version_document
from apps.api.catalog import (Cursor, decode_cursor, encode_cursor, paginate)
from apps.api.contracts.spec import LIMITS
from apps.api.contracts.validate import validate_document
from apps.api.errors import ApiError, status_for_code
from tests.fixtures.wp13.synthetic import DRUG_1, DRUG_2, GENE_1
from tests.fixtures.wp16.synthetic import (SyntheticEvidenceRepository,
                                           evidence_detail)
from tests.unit.api._support import synthetic_world


class _Pinned(unittest.TestCase):

    def setUp(self):
        self.world = synthetic_world()
        self.addCleanup(self.world.close)
        self.pinned = self.world.resolver.resolve()

    def drugs(self, **kwargs):
        return drug_collection_document(
            manifest=self.pinned.coverage_manifest,
            provenance=self.pinned.provenance,
            drug_keys=self.pinned.drug_catalogue, **kwargs)

    def genes(self, **kwargs):
        return gene_collection_document(
            manifest=self.pinned.coverage_manifest,
            provenance=self.pinned.provenance, **kwargs)


class TestDrugCatalogue(_Pinned):

    def test_the_document_satisfies_the_contract(self):
        self.assertTrue(validate_document("DrugCollectionResponse",
                                          self.drugs()))

    def test_it_is_ordered_by_canonical_key(self):
        keys = [item["drug"] for item in self.drugs()["items"]]
        self.assertEqual(keys, sorted(keys))

    def test_it_reports_the_release_it_was_read_from(self):
        release = self.drugs()["release"]
        self.assertEqual(release["release_public_id"],
                         self.pinned.release_public_id)
        self.assertEqual(release["coverage_manifest_hash"],
                         self.pinned.provenance.coverage_manifest_hash)

    def test_coverage_is_reported_as_counts_from_the_manifest(self):
        by_key = {item["drug"]: item for item in self.drugs()["items"]}
        declared = by_key[DRUG_1]
        self.assertTrue(declared["declared"])
        self.assertEqual(declared["supported_axis_count"],
                         len(self.pinned.coverage_manifest
                             .declaration_for(DRUG_1).supported_axes))
        self.assertTrue(declared["declaration_id"])

    def test_an_undeclared_drug_is_visible_rather_than_omitted(self):
        by_key = {item["drug"]: item for item in self.drugs()["items"]}
        self.assertIn(DRUG_2, by_key)
        self.assertFalse(by_key[DRUG_2]["declared"])
        self.assertEqual(by_key[DRUG_2]["supported_axis_count"], 0)

    def test_no_item_carries_a_score_ranking_or_suitability_verdict(self):
        forbidden = {"score", "rank", "ranking", "suitability", "recommended",
                     "safe", "risk", "preference", "best", "alternative"}
        for item in self.drugs()["items"]:
            with self.subTest(drug=item["drug"]):
                self.assertEqual(set(item) & forbidden, set())

    def test_the_display_value_is_derived_from_the_key_alone(self):
        for item in self.drugs()["items"]:
            with self.subTest(drug=item["drug"]):
                tail = item["drug"].split(":", 1)[1]
                self.assertEqual(item["display_name"],
                                 tail.replace("-", " ").replace("_", " "))


class TestGeneCatalogue(_Pinned):

    def test_the_document_satisfies_the_contract(self):
        self.assertTrue(validate_document("GeneCollectionResponse",
                                          self.genes()))

    def test_the_phenotype_vocabulary_is_the_governed_one(self):
        from pgx.domain.enums import Phenotype
        self.assertEqual(self.genes()["phenotype_vocabulary"],
                         [item.value for item in Phenotype])

    def test_rapid_and_ultrarapid_stay_distinct(self):
        vocabulary = supported_phenotype_vocabulary()
        self.assertIn("RAPID", vocabulary)
        self.assertIn("ULTRARAPID", vocabulary)
        self.assertNotEqual(vocabulary.index("RAPID"),
                            vocabulary.index("ULTRARAPID"))

    def test_a_gene_reports_only_the_phenotypes_a_rule_covers(self):
        by_key = {item["gene"]: item for item in self.genes()["items"]}
        entry = by_key[GENE_1]
        self.assertTrue(entry["supported_phenotypes"])
        self.assertLessEqual(set(entry["supported_phenotypes"]),
                             set(supported_phenotype_vocabulary()))

    def test_a_gene_expected_with_no_declared_axis_is_not_reported_as_full(self):
        """SAFETY-INV-001 in catalogue form: the fixture's extra expected gene
        has no axis, and the gene it belongs to must not read as covered."""
        entries = {item["gene"]: item for item in self.genes()["items"]}
        incomplete = [item for item in entries.values()
                      if not item["fully_declared"]]
        self.assertTrue(
            incomplete,
            "the synthetic world declares an expected gene with no axis; if "
            "that stopped being true this test proves nothing")


class TestPagination(_Pinned):

    def test_the_default_page_size_is_bounded(self):
        self.assertEqual(self.drugs()["page"]["page_size"],
                         LIMITS["default_page_size"])

    def test_an_oversized_page_is_refused_rather_than_reduced(self):
        with self.assertRaises(ApiError) as caught:
            self.drugs(page_size=LIMITS["max_page_size"] + 1)
        self.assertEqual(status_for_code(caught.exception.code), 422)

    def test_a_cursor_from_another_release_is_refused(self):
        first = paginate([DRUG_1, DRUG_2], collection="drugs",
                         context=catalogue_context(self.pinned.provenance),
                         page_size=1)
        other = dict(catalogue_context(self.pinned.provenance),
                     release_public_id="PGX-REL-29990101-999")
        with self.assertRaises(ApiError) as caught:
            paginate([DRUG_1, DRUG_2], collection="drugs", context=other,
                     cursor_token=first.next_cursor)
        self.assertEqual(caught.exception.code, "CURSOR_RELEASE_MISMATCH")
        self.assertEqual(status_for_code(caught.exception.code), 409)

    def test_a_drugs_cursor_is_refused_against_genes(self):
        first = paginate([DRUG_1, DRUG_2], collection="drugs",
                         context=catalogue_context(self.pinned.provenance),
                         page_size=1)
        with self.assertRaises(ApiError):
            paginate([GENE_1], collection="genes",
                     context=catalogue_context(self.pinned.provenance),
                     cursor_token=first.next_cursor)

    def test_paging_returns_every_item_exactly_once(self):
        context = catalogue_context(self.pinned.provenance)
        keys = ["DRUG:testdrug-%03d" % index for index in range(1, 12)]
        seen, cursor = [], None
        for _ in range(10):
            page = paginate(keys, collection="drugs", context=context,
                            page_size=4, cursor_token=cursor)
            seen.extend(page.items)
            cursor = page.next_cursor
            if cursor is None:
                break
        self.assertEqual(seen, keys)

    def test_a_cursor_is_deterministic(self):
        context = catalogue_context(self.pinned.provenance)
        first = paginate([DRUG_1, DRUG_2], collection="drugs",
                         context=context, page_size=1)
        again = paginate([DRUG_1, DRUG_2], collection="drugs",
                         context=context, page_size=1)
        self.assertEqual(first.next_cursor, again.next_cursor)

    def test_a_cursor_fits_the_declared_bound(self):
        context = catalogue_context(self.pinned.provenance)
        token = encode_cursor(Cursor(
            collection="drugs",
            release_public_id=context["release_public_id"],
            dataset_public_id=context["dataset_public_id"],
            coverage_manifest_hash=context["coverage_manifest_hash"],
            after_key="DRUG:" + "x" * 49))
        self.assertLessEqual(len(token), LIMITS["max_cursor_length"])


class TestEvidenceProjection(unittest.TestCase):

    def setUp(self):
        self.repository = SyntheticEvidenceRepository()
        build = self.repository.evidence_build_key()
        self.document = evidence_detail_document(
            self.repository.get("aaaaaaaa-0000-4000-8000-000000000001"),
            evidence_build_key=build["evidence_build_key"],
            evidence_build_content_hash=build["evidence_build_content_hash"])

    def test_the_document_satisfies_the_contract(self):
        self.assertTrue(validate_document("EvidenceDetailResponse",
                                          self.document))

    def test_the_provenance_chain_is_complete(self):
        for name in ("record_uuid", "natural_key", "record_type",
                     "provider_source_key", "origin_source_key",
                     "origin_status", "version_status",
                     "source_payload_hash", "content_hash",
                     "evidence_build_key", "evidence_build_content_hash"):
            with self.subTest(field=name):
                self.assertTrue(self.document[name])

    def test_no_source_prose_is_returned(self):
        rendered = json.dumps(self.document)
        self.assertNotIn("unreviewed source prose", rendered)
        self.assertEqual(self.document["text_fragment_count"], 1)

    def test_no_filesystem_path_is_returned(self):
        rendered = json.dumps(self.document)
        self.assertNotIn("/var/lib", rendered)
        for locator in self.document["locators"]:
            with self.subTest(locator=locator["artifact_id"]):
                self.assertNotIn("path", locator)

    def test_publications_are_identifiers_only(self):
        for publication in self.document["publications"]:
            with self.subTest(publication=publication["identifier"]):
                self.assertEqual(sorted(publication),
                                 ["identifier", "identifier_type"])

    def test_entity_links_use_the_governed_type_vocabulary(self):
        for link in self.document["genes"] + self.document["drugs"]:
            with self.subTest(entity=link["canonical_key"]):
                self.assertIn(link["entity_type"], ("GENE", "DRUG"))

    def test_a_missing_record_is_not_invented(self):
        self.assertIsNone(self.repository.get("no-such-record"))

    def test_the_locators_are_read_from_the_real_wp08_keys(self):
        """The fixture carries WP-08's own key names, so this proves the
        projection against the shape the repository actually returns rather
        than against a shape invented to match the projection."""
        locator = self.document["locators"][0]
        self.assertTrue(locator["snapshot_id"].startswith("sha256:"))
        self.assertTrue(locator["artifact_digest"].startswith("sha256:"))
        self.assertEqual(locator["json_pointer"], "/items/0")
        self.assertEqual(sorted(locator),
                         ["artifact_digest", "artifact_id", "json_pointer",
                          "snapshot_id"])

    def test_the_record_type_mapping_carries_identifiers_and_no_rationale(self):
        mapping = self.document["record_type_mapping"]
        self.assertEqual(sorted(mapping),
                         ["map_version", "production_eligible", "record_type",
                          "status"])
        self.assertNotIn("rationale", mapping)
        self.assertNotIn("curation prose", json.dumps(self.document))

    def test_the_sources_own_request_vocabulary_is_not_echoed(self):
        self.assertNotIn("TestContainer", json.dumps(self.document))


class TestSystemVersion(_Pinned):

    def setUp(self):
        super().setUp()
        self.document = system_version_document(
            self.pinned.provenance, claim_boundary=self.world.boundary)

    def test_the_document_satisfies_the_contract(self):
        self.assertTrue(validate_document("SystemVersionResponse",
                                          self.document))

    def test_every_version_comes_from_one_release(self):
        provenance = self.pinned.provenance.to_json()
        for name, value in self.document.items():
            if name in provenance:
                with self.subTest(field=name):
                    self.assertEqual(value, provenance[name])

    def test_the_pointer_generation_is_reported_here(self):
        self.assertEqual(self.document["active_pointer_generation"],
                         self.pinned.active_pointer_generation)

    def test_the_claim_boundary_is_reported(self):
        self.assertEqual(self.document["claim_boundary_approved"],
                         self.world.boundary.is_approved)
        self.assertTrue(self.document["claim_boundary_phase"])

    def test_the_pointer_is_read_once_for_one_answer(self):
        before = self.world.resolver.pointer_reads
        pinned = self.world.resolver.resolve()
        system_version_document(pinned.provenance,
                                claim_boundary=self.world.boundary)
        self.assertEqual(self.world.resolver.pointer_reads - before, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
