# -*- coding: utf-8 -*-
"""G. Artifacts and manifests.

A published report is a file somebody will read later and quote in a review.
These tests assert the three properties that make that safe: the name is a
function of the content, the same content rewrites idempotently while
different content refuses, and the manifest lands last and is verified on
read.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest

from pgx.reporting.artifacts import (ARTIFACT_MANIFEST_SCHEMA_VERSION,
                                     MANIFEST_FIELDS, artifact_name,
                                     read_artifact, write_artifact)
from pgx.reporting.errors import ReportArtifactError
from pgx.reporting.render import render_markdown
from tests.unit.reporting._support import ReportingCase


class ArtifactCase(ReportingCase):

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory, True)

    def publish(self, locale="tr"):
        return self.produced(locale=locale, directory=self.directory)


class TestTheNameIsAFunctionOfTheContent(ArtifactCase):

    def test_the_name_carries_the_assessment_locale_and_hash(self):
        name = artifact_name(assessment_id="abc", locale="tr",
                             report_hash="sha256:" + "d" * 64)
        self.assertEqual(name, "report-abc-tr-dddddddddddddddd")

    def test_two_locales_of_one_assessment_get_different_names(self):
        one = self.publish("tr")
        two = self.publish("en")
        self.assertNotEqual(one.artifact["document_path"],
                            two.artifact["document_path"])

    def test_the_name_carries_no_clock(self):
        produced = self.publish()
        name = os.path.basename(produced.artifact["document_path"])
        for fragment in ("2026", "2025", "T00", "Z."):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, name)

    def test_a_hostile_identity_cannot_escape_the_directory(self):
        name = artifact_name(assessment_id="../../etc/passwd", locale="tr",
                             report_hash="sha256:" + "e" * 64)
        self.assertNotIn("/", name)
        self.assertNotIn("..", name)

    def test_a_report_without_a_hash_cannot_be_named(self):
        with self.assertRaises(ReportArtifactError):
            artifact_name(assessment_id="abc", locale="tr", report_hash="")


class TestWritingIsAtomicAndAppendOnlyInSpirit(ArtifactCase):

    def test_it_writes_a_document_and_a_manifest(self):
        produced = self.publish()
        self.assertTrue(produced.artifact["written"])
        self.assertTrue(os.path.isfile(produced.artifact["document_path"]))
        self.assertTrue(os.path.isfile(produced.artifact["manifest_path"]))

    def test_it_leaves_no_temporary_file_behind(self):
        self.publish()
        leftovers = [name for name in os.listdir(self.directory)
                     if name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_rewriting_identical_content_is_a_no_op(self):
        first = self.publish()
        second = self.publish()
        self.assertTrue(first.artifact["written"])
        self.assertFalse(second.artifact["written"])
        self.assertEqual(second.artifact["reason"],
                         "identical content already published")

    def test_rewriting_different_content_under_one_name_is_refused(self):
        produced = self.publish()
        with io.open(produced.artifact["document_path"], "a",
                     encoding="utf-8") as handle:
            handle.write("\nsomething somebody added\n")
        with self.assertRaises(ReportArtifactError) as caught:
            self.publish()
        self.assertEqual(caught.exception.code, "REPORT_ARTIFACT_CONFLICT")

    def test_a_manifest_carries_every_published_field(self):
        manifest = self.publish().artifact["manifest"]
        for name in MANIFEST_FIELDS:
            with self.subTest(field=name):
                self.assertIn(name, manifest)
        self.assertEqual(manifest["manifest_schema_version"],
                         ARTIFACT_MANIFEST_SCHEMA_VERSION)

    def test_the_manifest_carries_three_distinguishable_digests(self):
        manifest = self.publish().artifact["manifest"]
        digests = {manifest["output_hash"], manifest["report_hash"],
                   manifest["rendered_checksum"]}
        self.assertEqual(len(digests), 3)

    def test_the_manifest_carries_the_fact_ledger_and_the_scan(self):
        manifest = self.publish().artifact["manifest"]
        self.assertTrue(manifest["fact_ledger"]["ledger_hash"])
        self.assertTrue(manifest["claim_scan"]["is_clean"])
        self.assertTrue(manifest["claim_scan"]["scanner_version"])
        self.assertTrue(manifest["claim_scan"]["limits"])

    def test_the_manifest_carries_every_pinned_version(self):
        manifest = self.publish().artifact["manifest"]
        self.assertEqual(dict(manifest["release_provenance"]),
                         dict(self.report().release_provenance))

    def test_the_manifest_is_deterministic_json(self):
        produced = self.publish()
        with io.open(produced.artifact["manifest_path"],
                     encoding="utf-8") as handle:
            text = handle.read()
        self.assertEqual(
            text,
            json.dumps(produced.artifact["manifest"], ensure_ascii=False,
                       sort_keys=True, indent=2) + "\n")

    def test_nothing_is_written_when_there_is_nothing_to_write(self):
        with self.assertRaises(ReportArtifactError):
            write_artifact(self.report(), rendered="",
                           fact_ledger={}, claim_scan={},
                           directory=self.directory)
        self.assertEqual(os.listdir(self.directory), [])


class TestReadingVerifies(ArtifactCase):

    def test_a_published_artifact_reads_back(self):
        produced = self.publish()
        record = read_artifact(produced.artifact["manifest_path"])
        self.assertTrue(record["verified"])
        self.assertEqual(record["rendered"], produced.markdown)

    def test_an_edited_document_is_refused(self):
        produced = self.publish()
        with io.open(produced.artifact["document_path"], "a",
                     encoding="utf-8") as handle:
            handle.write("edited\n")
        with self.assertRaises(ReportArtifactError) as caught:
            read_artifact(produced.artifact["manifest_path"])
        self.assertEqual(caught.exception.code,
                         "REPORT_ARTIFACT_HASH_MISMATCH")

    def test_a_manifest_without_its_document_is_refused(self):
        produced = self.publish()
        os.remove(produced.artifact["document_path"])
        with self.assertRaises(ReportArtifactError) as caught:
            read_artifact(produced.artifact["manifest_path"])
        self.assertEqual(caught.exception.code,
                         "REPORT_ARTIFACT_INCOMPLETE")

    def test_an_incomplete_manifest_is_refused(self):
        produced = self.publish()
        manifest = dict(produced.artifact["manifest"])
        manifest.pop("fact_ledger")
        with io.open(produced.artifact["manifest_path"], "w",
                     encoding="utf-8") as handle:
            json.dump(manifest, handle)
        with self.assertRaises(ReportArtifactError) as caught:
            read_artifact(produced.artifact["manifest_path"])
        self.assertEqual(caught.exception.code,
                         "REPORT_ARTIFACT_INCOMPLETE")

    def test_a_tampered_fact_ledger_is_refused(self):
        produced = self.publish()
        manifest = dict(produced.artifact["manifest"])
        ledger = dict(manifest["fact_ledger"])
        ledger["overall_attention"] = "NO_ACTIVE_ATTENTION"
        manifest["fact_ledger"] = ledger
        with io.open(produced.artifact["manifest_path"], "w",
                     encoding="utf-8") as handle:
            json.dump(manifest, handle)
        with self.assertRaises(ReportArtifactError) as caught:
            read_artifact(produced.artifact["manifest_path"])
        self.assertEqual(caught.exception.code,
                         "REPORT_ARTIFACT_HASH_MISMATCH")

    def test_a_missing_manifest_is_refused(self):
        with self.assertRaises(ReportArtifactError):
            read_artifact(os.path.join(self.directory, "nothing.json"))


class TestSyntheticOutputStaysOutOfProduction(ArtifactCase):

    def test_a_synthetic_report_refuses_the_production_directory(self):
        from pgx.reporting.errors import ReportError
        with self.assertRaises(ReportError) as caught:
            self.produced(directory=os.path.join(self.directory, "data",
                                                 "reports"))
        self.assertEqual(caught.exception.code,
                         "REPORT_SYNTHETIC_DESTINATION_REFUSED")

    def test_the_production_directory_holds_no_report(self):
        from tests.unit.reporting._support import REPO_ROOT
        root = os.path.join(REPO_ROOT, "data", "reports")
        # Matched on the artifact naming convention: the directory's README
        # and the machine-readable gate status are not published reports, and
        # the gate status exists precisely to record that there are none.
        present = [name for name in os.listdir(root)
                   if name.startswith("report-")] \
            if os.path.isdir(root) else []
        self.assertEqual(present, [])

    def test_a_produced_report_says_whether_it_is_synthetic(self):
        produced = self.publish()
        self.assertTrue(produced.is_synthetic)
        self.assertTrue(produced.to_json()["is_synthetic"])


if __name__ == "__main__":
    unittest.main()
