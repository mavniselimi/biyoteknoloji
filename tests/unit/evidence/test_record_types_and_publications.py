# -*- coding: utf-8 -*-
"""Record kinds and publication identity: two places WP-08 refuses to guess.

A container name is a request parameter, not a record type. Two annotations
printing one title have not been shown to cite one article. Both refusals cost
this project reported precision, and both are the reason the numbers it does
report can be believed.
"""

from __future__ import annotations

import unittest

from pgx.evidence.publications import (PUBLICATION_PARSER_VERSION,
                                       normalize_doi, parse_literature_objects,
                                       parse_parallel_lists, validate_pmid,
                                       validate_year)
from pgx.evidence.record_types import (CONTAINER_FINDINGS, OBJECT_CLASS_MAP,
                                       UNRESOLVED_ALIAS_CONTAINERS,
                                       map_record_type)
from pgx.evidence.models import (EvidenceRecordType, RecordTypeMappingStatus)

from tests.unit.evidence._support import RealEvidenceBuildTestCase


class TestRecordTypeComesFromTheObjectClass(unittest.TestCase):

    def test_the_container_alone_does_not_decide_the_type(self):
        """``variantAnnotation`` returns three different kinds of record, so a
        type read off the container would mislabel two of them."""
        phenotype = map_record_type("Variant Phenotype Annotation",
                                    "variantAnnotation")
        functional = map_record_type("Variant Functional Assay Annotation",
                                     "variantAnnotation")
        self.assertEqual(phenotype.record_type, functional.record_type)
        self.assertNotEqual(phenotype.source_object_class,
                            functional.source_object_class)

    def test_an_unknown_object_class_is_unmapped_not_guessed(self):
        mapping = map_record_type("Something Nobody Registered", "pair")
        self.assertEqual(mapping.status, RecordTypeMappingStatus.UNMAPPED)
        self.assertEqual(mapping.record_type, EvidenceRecordType.UNKNOWN)

    def test_the_requested_container_is_kept_beside_the_object_class(self):
        mapping = map_record_type("Guideline Annotation", "GuidelineAnnotation")
        self.assertEqual(mapping.requested_container, "GuidelineAnnotation")
        self.assertEqual(mapping.source_object_class, "Guideline Annotation")

    def test_every_registered_object_class_maps_to_a_real_type(self):
        for object_class in OBJECT_CLASS_MAP:
            with self.subTest(object_class=object_class):
                mapping = map_record_type(object_class, "pair")
                self.assertNotEqual(mapping.record_type,
                                    EvidenceRecordType.UNKNOWN)


class TestLabelAndDrugLabelStayUnproven(unittest.TestCase):
    """29 records reached WP-08 under two container spellings.

    The evidence that they are the same thing is strong: identical payloads,
    one declared ``objCls``, and only one of the two spellings in the OpenAPI
    document. Strong is not proven, and the difference between the two is
    exactly what a review is for.
    """

    def test_both_spellings_are_still_recognised(self):
        for container in UNRESOLVED_ALIAS_CONTAINERS:
            with self.subTest(container=container):
                mapping = map_record_type("Label Annotation", container)
                self.assertEqual(mapping.record_type,
                                 EvidenceRecordType.DRUG_LABEL_ANNOTATION)

    def test_neither_spelling_is_confirmed(self):
        for container in UNRESOLVED_ALIAS_CONTAINERS:
            with self.subTest(container=container):
                self.assertEqual(
                    map_record_type("Label Annotation", container).status,
                    RecordTypeMappingStatus.PENDING_REVIEW)

    def test_the_original_spelling_is_retained_rather_than_normalised(self):
        lower = map_record_type("Label Annotation", "label")
        upper = map_record_type("Label Annotation", "DrugLabel")
        self.assertEqual(lower.requested_container, "label")
        self.assertEqual(upper.requested_container, "DrugLabel")

    def test_the_findings_behind_the_decision_are_recorded(self):
        """A judgement with no recorded basis cannot be reviewed later."""
        self.assertTrue(CONTAINER_FINDINGS)
        identifiers = set()
        for finding in CONTAINER_FINDINGS:
            self.assertTrue(finding.statement)
            self.assertTrue(finding.supports)
            self.assertTrue(finding.evidence,
                            "%s states a finding with no evidence"
                            % finding.finding_id)
            identifiers.add(finding.finding_id)
        self.assertEqual(len(identifiers), len(CONTAINER_FINDINGS))


class TestPublicationIdentity(unittest.TestCase):

    def test_a_pmid_is_digits_and_a_rejection_says_why(self):
        """Each validator returns ``(value, issue)``. A bare ``None`` would
        say a value was unusable without saying what was wrong with it."""
        self.assertEqual(validate_pmid("21412232"), ("21412232", None))
        self.assertEqual(validate_pmid("pmid:21412232"), ("21412232", None))
        self.assertEqual(validate_pmid(""), (None, None))

    def test_an_unusable_identifier_is_kept_beside_the_problem(self):
        """Uniform across the three validators: what the source wrote survives
        and the problem is reported next to it. A validator that returned only
        ``None`` would silently delete the source's own text, and the record
        would then disagree with the bytes it cites."""
        for validator, given in ((validate_pmid, "PMID21412232"),
                                 (normalize_doi, "not-a-doi"),
                                 (validate_year, "3000")):
            with self.subTest(validator=validator.__name__):
                value, issue = validator(given)
                self.assertIsNotNone(value)
                self.assertTrue(issue)

    def test_a_doi_loses_its_resolver_prefix_and_case(self):
        for spelling in ("10.1038/CLPT.2011.34",
                         "https://doi.org/10.1038/clpt.2011.34",
                         "doi:10.1038/clpt.2011.34"):
            with self.subTest(spelling=spelling):
                self.assertEqual(normalize_doi(spelling),
                                 ("10.1038/clpt.2011.34", None))

    def test_an_implausible_year_is_reported_and_still_kept(self):
        """Reported, not discarded. The source printed that year, and deleting
        it would make the stored reference disagree with the bytes it cites -
        which is a worse failure than carrying a flagged oddity."""
        self.assertEqual(validate_year(2011), (2011, None))
        for implausible in (1500, 3000):
            with self.subTest(year=implausible):
                value, issue = validate_year(implausible)
                self.assertEqual(value, implausible)
                self.assertIn("plausible range", issue)

    def test_a_year_that_is_not_a_number_yields_no_year_at_all(self):
        value, issue = validate_year("last spring")
        self.assertIsNone(value)
        self.assertTrue(issue)

    def test_a_literature_object_yields_pmid_doi_and_year(self):
        parsed = parse_literature_objects([{
            "objCls": "Literature",
            "title": "T",
            "pubDate": "2011-05-01T00:00:00-07:00",
            "crossReferences": [
                {"resource": "PubMed", "resourceId": "21412232"},
                {"resource": "DOI", "resourceId": "10.1038/clpt.2011.34"}]}])
        reference = parsed.references[0]
        self.assertEqual(reference.pmid, "21412232")
        self.assertEqual(reference.doi, "10.1038/clpt.2011.34")
        self.assertEqual(reference.year, 2011)
        self.assertEqual(reference.identity, "pmid:21412232")

    def test_identity_prefers_pmid_then_doi_and_never_the_title(self):
        parsed = parse_literature_objects([
            {"objCls": "Literature", "title": "Only a title"}])
        self.assertIsNone(parsed.references[0].identity)

    def test_parallel_lists_of_unequal_length_are_not_paired_by_position(self):
        """Pairing them anyway would attach a real PMID to the wrong title."""
        parsed = parse_parallel_lists(titles="A|B|C", pmids="1;2",
                                      dois="", years="")
        self.assertTrue(parsed.issues)
        # Every value survives, but none of them claims to be a citation:
        # no reference carries a title and a PMID together, which is exactly
        # the pairing that positional reconciliation would have invented.
        for reference in parsed.references:
            self.assertFalse(reference.title and reference.pmid)
            self.assertTrue(reference.issues)
        self.assertEqual(
            sorted(item.title for item in parsed.references if item.title),
            ["A", "B", "C"])
        self.assertEqual(
            sorted(item.pmid for item in parsed.references if item.pmid),
            ["1", "2"])

    def test_parallel_lists_of_equal_length_are_paired(self):
        parsed = parse_parallel_lists(titles="A|B", pmids="1;2",
                                      dois="", years="")
        self.assertEqual([item.pmid for item in parsed.references],
                         ["1", "2"])
        self.assertEqual(parsed.issues, ())

    def test_the_parser_version_is_recorded(self):
        self.assertTrue(PUBLICATION_PARSER_VERSION)


class TestPublicationsInTheRealBuild(RealEvidenceBuildTestCase):

    def test_no_identity_is_derived_from_a_title(self):
        for row in self.rows("publication-references.ndjson"):
            identity = row.get("identity")
            if identity:
                self.assertTrue(identity.startswith(("pmid:", "doi:")),
                                "%r is neither a pmid nor a doi" % identity)

    def test_an_unidentified_reference_keeps_its_raw_value(self):
        unidentified = [row for row in self.rows("publication-references.ndjson")
                        if not row.get("identity")]
        for row in unidentified:
            self.assertTrue(row.get("raw_value") or row.get("title"),
                            "an unidentified reference kept nothing at all")

    def test_two_references_sharing_a_title_are_not_merged(self):
        """Merging on title is the failure this refuses. If the corpus holds
        one title under two identities, both must survive."""
        by_title = {}
        for row in self.rows("publication-references.ndjson"):
            title = (row.get("title") or "").strip()
            if title:
                by_title.setdefault(title, set()).add(row.get("identity"))
        shared = {title: ids for title, ids in by_title.items()
                  if len(ids) > 1}
        for title, identities in shared.items():
            self.assertGreater(len(identities), 1,
                               "%r collapsed to one identity" % title)

    def test_the_label_annotations_are_quarantined_pending_review(self):
        pending = [row for row in self.rows("evidence-records.ndjson")
                   if (row.get("record_type_mapping") or {}).get("status")
                   == "PENDING_REVIEW"]
        self.assertTrue(pending)
        for row in pending:
            self.assertFalse(row.get("production_eligible"))
