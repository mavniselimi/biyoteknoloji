# -*- coding: utf-8 -*-
"""From an evidence record back to the bytes a source published (WP-08).

The chain has to survive being checked. Each test here re-derives one link of
it from the artifacts on disk rather than from the record's own claim about
itself, because a record that verified against its own summary would verify
against anything.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest

from pgx.evidence.detail import (ArtifactEvidenceDetailRepository,
                                 DuplicateNaturalKeyError,
                                 resolve_json_pointer)
from pgx.evidence.errors import EvidenceError

from tests.unit.evidence._support import RealEvidenceBuildTestCase


class TestJsonPointerResolution(unittest.TestCase):

    DOCUMENT = {"a": {"b": [{"id": 1}, {"id": 2}]}, "x/y": "escaped",
                "m~n": "tilde"}

    def test_it_reaches_a_nested_list_element(self):
        found, value = resolve_json_pointer(self.DOCUMENT, "/a/b/1")
        self.assertTrue(found)
        self.assertEqual(value, {"id": 2})

    def test_it_reports_absence_rather_than_returning_none(self):
        """``None`` is a value a document may legitimately hold."""
        found, value = resolve_json_pointer(self.DOCUMENT, "/a/b/9")
        self.assertFalse(found)
        self.assertIsNone(value)

    def test_it_decodes_rfc_6901_escapes(self):
        self.assertEqual(resolve_json_pointer(self.DOCUMENT, "/x~1y"),
                         (True, "escaped"))
        self.assertEqual(resolve_json_pointer(self.DOCUMENT, "/m~0n"),
                         (True, "tilde"))

    def test_the_empty_pointer_is_the_whole_document(self):
        self.assertEqual(resolve_json_pointer(self.DOCUMENT, ""),
                         (True, self.DOCUMENT))


class TestTraceOverTheRealBuild(RealEvidenceBuildTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.repository = ArtifactEvidenceDetailRepository(cls.build_path)

    def test_every_record_reaches_at_least_one_raw_locator(self):
        missing = [row["natural_key"]
                   for row in self.rows("evidence-records.ndjson")
                   if not row.get("locators")]
        self.assertEqual(missing, [])

    def test_a_trace_names_five_hashes_with_five_meanings(self):
        """Not one overloaded ``raw_hash``. Each answers a different question."""
        first = self.repository.list_for_build()[0]
        chain = self.repository.trace(first["record_uuid"])
        hashes = chain["hashes"]
        for key in ("raw_artifact_sha256", "source_payload_hash",
                    "evidence_content_hash", "evidence_build_content_hash",
                    "snapshot_manifest_hash"):
            self.assertIn(key, hashes)
        distinct = {hashes["source_payload_hash"],
                    hashes["evidence_content_hash"],
                    hashes["evidence_build_content_hash"],
                    hashes["snapshot_manifest_hash"]}
        self.assertEqual(len(distinct), 4,
                         "two of the four hashes are equal, so at least one "
                         "is not measuring what it claims")

    def test_a_trace_carries_no_project_interpretation(self):
        first = self.repository.list_for_build()[0]
        chain = self.repository.trace(first["record_uuid"])
        for forbidden in ("risk", "risk_level", "recommendation", "summary",
                          "attention_level", "evidence_strength"):
            self.assertNotIn(forbidden, chain)

    def test_the_whole_corpus_re_derives_from_the_raw_bytes(self):
        """Every record, not a sample. The claim is about the build."""
        if not os.path.isdir(self.snapshot_root):
            self.skipTest("no sealed snapshot at %s" % self.snapshot_root)
        problems = []
        for detail in self.repository.list_for_build():
            problems.extend(
                "%s: %s" % (detail["natural_key"], problem)
                for problem in self.repository.verify_trace(
                    detail["record_uuid"], self.snapshot_root))
        self.assertEqual(problems, [])

    def test_a_known_guideline_keeps_every_locator_it_was_found_under(self):
        """Seven pointers into one artifact, including both spellings.

        The two containers ``guidelineAnnotation`` and ``GuidelineAnnotation``
        returned the same record. Collapsing them to one locator would lose the
        evidence that the source answers to both.
        """
        key = ("PGX-DATA-20260830-900|clinpgx.api|GUIDELINE_ANNOTATION"
               "|PA166104948|0")
        detail = self.repository.get_by_natural_key(key)
        if detail is None:
            self.skipTest("PA166104948 is not in this build")
        containers = {item.get("requested_container")
                      for item in detail["locators"]}
        self.assertIn("guidelineAnnotation", containers)
        self.assertIn("GuidelineAnnotation", containers)
        self.assertGreater(len(detail["locators"]), 1)

    def test_a_publication_is_addressed_by_identity_and_never_by_title(self):
        with self.assertRaises(EvidenceError):
            self.repository.list_for_publication(
                "Pharmacogenetics: from bench to byte")
        rows = self.repository.list_for_publication("pmid:21412232")
        self.assertIsInstance(rows, (list, tuple))

    def test_verify_trace_reports_a_missing_artifact_rather_than_passing(self):
        first = self.repository.list_for_build()[0]
        empty = tempfile.mkdtemp(prefix="wp08-empty-snapshot-")
        try:
            problems = self.repository.verify_trace(first["record_uuid"], empty)
        finally:
            shutil.rmtree(empty, ignore_errors=True)
        self.assertTrue(problems)
        self.assertTrue(any("missing" in problem for problem in problems))


class TestNaturalKeyLookupDetectsCorruption(unittest.TestCase):
    """No ``LIMIT 1``. Two rows under one key is a fact the caller must learn."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="wp08-dup-build-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def _write(self, rows):
        with io.open(os.path.join(self.root, "manifest.json"), "w",
                     encoding="utf-8") as handle:
            json.dump({"evidence_build_key": "k", "content_hash": "sha256:0",
                       "lifecycle_labels": []}, handle)
        with io.open(os.path.join(self.root, "evidence-records.ndjson"), "w",
                     encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def _row(self, uuid_value):
        return {"record_uuid": uuid_value,
                "natural_key": {"natural_key": "D|p|T|1|0",
                                "record_type": "VARIANT_ANNOTATION",
                                "source_record_id": "1"},
                "attribution": {}, "version": {}, "locators": []}

    def test_one_row_is_returned(self):
        self._write([self._row("uuid-a")])
        repository = ArtifactEvidenceDetailRepository(self.root)
        self.assertEqual(repository.get_by_natural_key("D|p|T|1|0")
                         ["record_uuid"], "uuid-a")

    def test_two_rows_raise_instead_of_returning_the_first(self):
        self._write([self._row("uuid-a"), self._row("uuid-b")])
        repository = ArtifactEvidenceDetailRepository(self.root)
        with self.assertRaises(DuplicateNaturalKeyError) as caught:
            repository.get_by_natural_key("D|p|T|1|0")
        self.assertIn("corrupt", str(caught.exception))

    def test_an_absent_key_is_none_rather_than_an_error(self):
        self._write([self._row("uuid-a")])
        repository = ArtifactEvidenceDetailRepository(self.root)
        self.assertIsNone(repository.get_by_natural_key("D|p|T|9|0"))
