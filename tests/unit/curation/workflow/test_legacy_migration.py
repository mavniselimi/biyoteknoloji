# -*- coding: utf-8 -*-
"""The legacy import: 1,559 questions, no answers (WP-10).

WP-08 pulled the old project's interpretations out of the evidence store. This
work package gives each of them a place on a queue. The tests here are mostly
about what did *not* happen, because that is the risk: an import that quietly
turned 1,559 unreviewed values into 1,559 conclusions would undo WP-08 while
looking like progress.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import io
import json
import os
import unittest

from pgx.curation.workflow.errors import WorkflowError
from pgx.curation.workflow.legacy import (LEGACY_VALUE_NAMESPACE,
                                          PROHIBITED_LEGACY_SOURCES,
                                          allocate_work_item_id,
                                          build_work_items,
                                          namespace_legacy_values,
                                          read_proposals)
from pgx.curation.workflow.models import LEGACY_MIGRATION_TAG
from pgx.domain.enums import CurationStatus
from tests.unit.curation._support import PROPOSALS, REPO_ROOT

WP10_DIR = os.path.join(REPO_ROOT, "data", "migration", "wp10")
IMPORTED_AT = _dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc)
IMPORTED_BY = "pgx-curation-workflow/import-legacy"

EXPECTED_TOTAL = 1559
EXPECTED_LINKED = 1526
EXPECTED_UNLINKED = 33


def _report():
    return build_work_items(read_proposals(PROPOSALS),
                            imported_at=IMPORTED_AT, imported_by=IMPORTED_BY)


class TestTheCounts(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.report = _report()
        cls.counts = cls.report.counts()

    def test_every_proposal_became_exactly_one_work_item(self):
        self.assertEqual(self.counts["work_items"], EXPECTED_TOTAL)

    def test_the_linkage_split_matches_what_wp08_found(self):
        self.assertEqual(self.counts["linked_work_items"], EXPECTED_LINKED)
        self.assertEqual(self.counts["unlinked_work_items"], EXPECTED_UNLINKED)

    def test_every_unlinked_proposal_says_why(self):
        self.assertEqual(len(self.report.issues), EXPECTED_UNLINKED)
        for issue in self.report.issues:
            with self.subTest(work_item=issue["work_item_id"]):
                self.assertTrue(issue["detail"].strip())
                self.assertTrue(issue["resolution"].strip())

    def test_nothing_is_under_review_curated_or_rejected(self):
        self.assertEqual(self.counts["by_status"],
                         {CurationStatus.RAW.value: EXPECTED_TOTAL})

    def test_no_revision_reviewer_or_approval_was_created(self):
        for name in ("revisions", "reviewers", "approvals",
                     "curated_interpretations"):
            with self.subTest(count=name):
                self.assertEqual(self.counts[name], 0)

    def test_every_work_item_carries_the_migration_tag(self):
        for item in self.report.work_items:
            with self.subTest(work_item=item.work_item_id):
                self.assertIn(LEGACY_MIGRATION_TAG, item.tags)
                self.assertTrue(item.is_legacy)

    def test_no_work_item_names_a_revision(self):
        for item in self.report.work_items:
            with self.subTest(work_item=item.work_item_id):
                self.assertIsNone(item.current_revision_id)
                self.assertIsNone(item.submitted_revision_id)

    def test_every_legacy_value_is_namespaced(self):
        for item in self.report.work_items:
            for key in item.legacy_values:
                with self.subTest(work_item=item.work_item_id, key=key):
                    self.assertTrue(key.startswith(LEGACY_VALUE_NAMESPACE))

    def test_every_link_is_marked_unreviewed(self):
        for link in self.report.evidence_links:
            with self.subTest(work_item=link["work_item_id"]):
                self.assertFalse(link["reviewed"])


class TestWhatTheImportRefuses(unittest.TestCase):

    def _proposal(self, **overrides):
        base = {
            "proposal_id": "MIGRATION-PROPOSAL-test",
            "status": "UNREVIEWED_LEGACY_MIGRATION_CANDIDATE",
            "subject": "CYP2C19::clopidogrel/PA166146879",
            "legacy_values": {"demo_risk_level": "high"},
            "linked_record_uuids": [],
            "linkage_note": "none",
            "origins": [],
        }
        base.update(overrides)
        return base

    def test_a_proposal_claiming_a_review_is_refused(self):
        with self.assertRaises(WorkflowError) as caught:
            build_work_items(
                [self._proposal(status="REVIEWED")],
                imported_at=IMPORTED_AT, imported_by=IMPORTED_BY)
        self.assertIn("imports only", str(caught.exception))

    def test_p1_candidate_data_is_refused_by_name(self):
        """Excluded from P0 at canonicalisation, and excluded again here by an
        explicit refusal rather than by not happening to look."""
        for source in PROHIBITED_LEGACY_SOURCES:
            with self.subTest(source=source):
                with self.assertRaises(WorkflowError) as caught:
                    build_work_items(
                        [self._proposal(origins=[
                            {"relative_path": "somewhere/%s.csv" % source}])],
                        imported_at=IMPORTED_AT, imported_by=IMPORTED_BY)
                self.assertIn("P1 candidate data", str(caught.exception))

    def test_a_legacy_field_that_would_assert_a_review_is_refused(self):
        for field in ("reviewed_by", "approved_by", "rationale", "status"):
            with self.subTest(field=field):
                with self.assertRaises(WorkflowError) as caught:
                    namespace_legacy_values({field: "somebody"})
                self.assertIn("refuses it", str(caught.exception))

    def test_a_duplicate_proposal_id_is_refused(self):
        with self.assertRaises(WorkflowError):
            build_work_items([self._proposal(), self._proposal()],
                             imported_at=IMPORTED_AT, imported_by=IMPORTED_BY)

    def test_a_subject_without_a_gene_and_drug_is_refused(self):
        with self.assertRaises(WorkflowError):
            build_work_items([self._proposal(subject="CYP2C19")],
                             imported_at=IMPORTED_AT, imported_by=IMPORTED_BY)


class TestIdentityIsAllocatedAndStable(unittest.TestCase):

    def test_an_id_is_a_pure_function_of_the_proposal_id(self):
        self.assertEqual(allocate_work_item_id("MIGRATION-PROPOSAL-abc"),
                         allocate_work_item_id("MIGRATION-PROPOSAL-abc"))

    def test_different_proposals_get_different_ids(self):
        self.assertNotEqual(allocate_work_item_id("A"),
                            allocate_work_item_id("B"))

    def test_an_id_is_not_a_counter(self):
        """A counter would renumber everything when one proposal is added, and
        every audit event pointing at an old number would silently point
        somewhere else."""
        report = _report()
        ids = [item.work_item_id for item in report.work_items]
        self.assertEqual(len(set(ids)), len(ids))
        self.assertNotEqual(sorted(ids), ids[:1] * len(ids))
        for entry in report.allocation[:20]:
            with self.subTest(proposal=entry["proposal_id"]):
                self.assertEqual(entry["work_item_id"],
                                 allocate_work_item_id(entry["proposal_id"]))

    def test_the_allocation_file_records_every_work_item(self):
        with io.open(os.path.join(WP10_DIR,
                                  "legacy-work-item-allocation.json"),
                     encoding="utf-8") as handle:
            allocation = json.load(handle)
        self.assertEqual(allocation["entry_count"], EXPECTED_TOTAL)
        self.assertEqual(len(allocation["entries"]), EXPECTED_TOTAL)


class TestTheCheckedInArtifacts(unittest.TestCase):
    """The files on disk say the same thing the code does."""

    @classmethod
    def setUpClass(cls):
        with io.open(os.path.join(WP10_DIR, "manifest.json"),
                     encoding="utf-8") as handle:
            cls.manifest = json.load(handle)

    def test_the_manifest_reports_the_expected_counts(self):
        counts = self.manifest["counts"]
        self.assertEqual(counts["work_items"], EXPECTED_TOTAL)
        self.assertEqual(counts["linked_work_items"], EXPECTED_LINKED)
        self.assertEqual(counts["unlinked_work_items"], EXPECTED_UNLINKED)
        self.assertEqual(counts["under_review"], 0)
        self.assertEqual(counts["curated"], 0)
        self.assertEqual(counts["curated_interpretations"], 0)

    def test_the_work_item_file_holds_only_raw_items(self):
        statuses = set()
        count = 0
        with io.open(os.path.join(WP10_DIR, "legacy-work-items.ndjson"),
                     encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                statuses.add(row["status"])
                count += 1
        self.assertEqual(count, EXPECTED_TOTAL)
        self.assertEqual(statuses, {"RAW"})

    def test_every_checksum_matches_its_file(self):
        with io.open(os.path.join(WP10_DIR, "checksums.sha256"),
                     encoding="utf-8") as handle:
            lines = [line.split() for line in handle if line.strip()]
        self.assertTrue(lines)
        for digest, name in lines:
            with self.subTest(file=name):
                with io.open(os.path.join(WP10_DIR, name), "rb") as handle:
                    actual = hashlib.sha256(handle.read()).hexdigest()
                self.assertEqual(actual, digest)

    def test_the_manifest_lists_every_file_it_shipped(self):
        for name in ("legacy-work-items.ndjson",
                     "legacy-work-item-evidence-links.ndjson",
                     "migration-issues.ndjson",
                     "legacy-work-item-allocation.json"):
            with self.subTest(file=name):
                self.assertIn(name, self.manifest["files"])

    def test_rebuilding_produces_identical_work_items(self):
        """Byte-identical regeneration, asserted by rebuilding in memory and
        comparing to what is on disk. A build whose output moved between runs
        would make 'did the data change' unanswerable without a diff."""
        rebuilt = build_work_items(
            read_proposals(PROPOSALS),
            imported_at=_dt.datetime.fromisoformat(
                self.manifest["imported_at"].replace("Z", "+00:00")),
            imported_by=self.manifest["imported_by"])
        rendered = "".join(
            json.dumps(item.to_json(), sort_keys=True, ensure_ascii=False)
            + "\n" for item in rebuilt.work_items)
        with io.open(os.path.join(WP10_DIR, "legacy-work-items.ndjson"),
                     encoding="utf-8") as handle:
            self.assertEqual(rendered, handle.read())


if __name__ == "__main__":
    unittest.main()
