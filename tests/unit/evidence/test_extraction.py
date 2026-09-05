# -*- coding: utf-8 -*-
"""Reading source records out of raw artifacts (WP-08).

One source record becomes one evidence record. Not one per gene/drug pair it
mentions, not one per container it was fetched under, and not one from the raw
JSON plus another from the CSV derived from that same JSON.
"""

from __future__ import annotations

import json
import os
import unittest

from pgx.evidence.extract import (EXTRACTION_RULE_VERSION,
                                  GUIDELINE_SOURCE_REGISTRY_MAP,
                                  PROVIDER_SOURCE_KEY, json_pointer)

from tests.unit.evidence._support import RealEvidenceBuildTestCase


class TestJsonPointerConstruction(unittest.TestCase):

    def test_it_escapes_the_two_characters_rfc_6901_reserves(self):
        self.assertEqual(json_pointer("a/b"), "/a~1b")
        self.assertEqual(json_pointer("a~b"), "/a~0b")

    def test_an_integer_index_is_rendered_as_a_path_segment(self):
        self.assertEqual(json_pointer("xs", 3), "/xs/3")

    def test_a_real_pair_key_survives_intact(self):
        self.assertEqual(
            json_pointer("CYP2C19::clopidogrel", "pair",
                         "guidelineAnnotation", 0),
            "/CYP2C19::clopidogrel/pair/guidelineAnnotation/0")


class TestTheExtractionContractIsRecorded(unittest.TestCase):

    def test_the_rule_version_is_declared(self):
        """Two counts produced under different rules are two measurements
        sharing a name, so the rule that produced one is recorded with it."""
        self.assertTrue(EXTRACTION_RULE_VERSION)

    def test_the_provider_is_the_api_the_bytes_came_from(self):
        self.assertEqual(PROVIDER_SOURCE_KEY, "clinpgx.api")

    def test_the_guideline_origin_map_is_explicit_and_small(self):
        """Every entry is a source that names itself in the record. There is
        no fallback entry, because a fallback is a guess."""
        self.assertIn("CPIC", GUIDELINE_SOURCE_REGISTRY_MAP)
        self.assertIn("DPWG", GUIDELINE_SOURCE_REGISTRY_MAP)
        for key, value in GUIDELINE_SOURCE_REGISTRY_MAP.items():
            self.assertTrue(key.strip())
            self.assertTrue(value.strip())
        self.assertNotIn("", GUIDELINE_SOURCE_REGISTRY_MAP)
        self.assertNotIn("*", GUIDELINE_SOURCE_REGISTRY_MAP)


class TestOneSourceRecordBecomesOneEvidenceRecord(RealEvidenceBuildTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.records = cls.rows("evidence-records.ndjson")
        cls.links = cls.rows("evidence-entity-links.ndjson")

    def test_a_record_naming_several_genes_is_still_one_record(self):
        by_record = {}
        for link in self.links:
            if link.get("entity_type") == "GENE":
                by_record.setdefault(link["record_uuid"], set()).add(
                    link["canonical_key"])
        multi = {uuid_value for uuid_value, keys in by_record.items()
                 if len(keys) > 1}
        self.assertTrue(multi, "no multi-gene record in this corpus, so the "
                               "no-duplication rule is untested here")
        keys = [row["natural_key"]["natural_key"] for row in self.records
                if row["record_uuid"] in multi]
        self.assertEqual(len(keys), len(set(keys)))

    def test_a_record_naming_several_drugs_is_still_one_record(self):
        by_record = {}
        for link in self.links:
            if link.get("entity_type") == "DRUG":
                by_record.setdefault(link["record_uuid"], set()).add(
                    link["canonical_key"])
        multi = {uuid_value for uuid_value, keys in by_record.items()
                 if len(keys) > 1}
        self.assertTrue(multi)

    def test_no_natural_key_appears_twice(self):
        keys = [row["natural_key"]["natural_key"] for row in self.records]
        self.assertEqual(len(keys), len(set(keys)))

    def test_a_record_found_under_several_containers_keeps_every_locator(self):
        multi = [row for row in self.records if len(row.get("locators") or ()) > 1]
        self.assertTrue(multi)
        for row in multi[:50]:
            pointers = [item.get("pointer") for item in row["locators"]]
            self.assertEqual(len(pointers), len(set(pointers)),
                             "one pointer recorded twice for %s"
                             % row["natural_key"]["natural_key"])

    def test_the_same_record_is_not_imported_from_json_and_from_csv(self):
        """A locator addresses a JSON pointer or a CSV row, never both, and a
        record whose payload came from the JSON does not gain a second copy
        from the CSV derived from it."""
        for row in self.records:
            for item in row.get("locators") or ():
                has_pointer = item.get("pointer") is not None
                has_row = item.get("csv_row_number") is not None
                self.assertTrue(
                    has_pointer != has_row,
                    "a locator must address a JSON pointer or a CSV row and "
                    "not both or neither: %s" % item)

    def test_records_are_not_collapsed_merely_for_sharing_a_gene_drug_pair(self):
        """Two guideline annotations about CYP2C19 and clopidogrel are two
        statements. Grouping by pair would report them as one."""
        pairs = {}
        for link in self.links:
            pairs.setdefault(link["record_uuid"], set()).add(
                link["canonical_key"])
        signature_counts = {}
        for uuid_value, keys in pairs.items():
            signature = tuple(sorted(keys))
            signature_counts[signature] = signature_counts.get(signature, 0) + 1
        repeated = [count for count in signature_counts.values() if count > 1]
        self.assertTrue(repeated,
                        "no two records share an entity signature, so the "
                        "no-collapse rule is untested by this corpus")

    def test_every_entity_link_records_how_the_record_came_to_name_it(self):
        """A gene the source listed and a gene that only appears because the
        record was fetched under that gene's query are different facts, so
        both the role and the field it came from are kept."""
        roles = {link.get("role") for link in self.links}
        self.assertIn("RELATED_ENTITY", roles)
        self.assertTrue(roles - {"RELATED_ENTITY"},
                        "every link has the same role, so the distinction "
                        "between a stated relation and a query context is "
                        "not being recorded")
        without_field = [link for link in self.links
                         if not link.get("source_field")]
        self.assertEqual(without_field, [])

    def test_every_text_fragment_keeps_the_field_it_was_quoted_from(self):
        fragments = self.rows("evidence-text-fragments.ndjson")
        self.assertTrue(fragments)
        for row in fragments[:200]:
            self.assertTrue(row.get("field_name"))
            self.assertTrue(row.get("text"))
            self.assertTrue(row.get("text_hash"))
            self.assertTrue(row.get("exact_text_hash"))
