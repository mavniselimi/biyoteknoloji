# -*- coding: utf-8 -*-
"""The legacy manual-hint queue, and what it must not become (WP-09).

1,559 conclusions this project reached before any review protocol existed.
They are accounted for, unreviewed, and kept out of every completed
conclusion.
"""

from __future__ import annotations

import io
import json
import os
import unittest

from pgx.curation.errors import CurationError
from pgx.curation.legacy_review import (LEGACY_PROJECT_VALUE_FIELDS,
                                        LegacyProposalEntry,
                                        build_review_inventory)
from pgx.curation.models import PROHIBITED_CURATION_FIELDS
from pgx.curation.vocabulary import LegacyReviewState

from tests.unit.curation._support import PROPOSALS, REPO_ROOT

INVENTORY_JSON = os.path.join(REPO_ROOT, "data", "curation", "protocol-v1",
                              "legacy-hint-review-inventory.json")


class TestEveryProposalIsAccountedFor(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(PROPOSALS):
            raise unittest.SkipTest("no WP-08 proposals in this checkout")
        cls.inventory = build_review_inventory(PROPOSALS)
        with io.open(PROPOSALS, encoding="utf-8") as handle:
            cls.rows = [json.loads(line) for line in handle if line.strip()]

    def test_all_1559_proposals_are_present(self):
        self.assertEqual(len(self.inventory.entries), 1559)
        self.assertEqual(len(self.inventory.entries), len(self.rows))

    def test_not_one_proposal_id_was_dropped(self):
        expected = {str(row["proposal_id"]) for row in self.rows}
        actual = {item.proposal_id for item in self.inventory.entries}
        self.assertEqual(actual, expected)

    def test_unlinked_proposals_stay_visible(self):
        counts = self.inventory.counts()
        self.assertEqual(counts["unlinked_count"], 33)
        unlinked = [item for item in self.inventory.entries
                    if not item.is_linked]
        self.assertEqual(len(unlinked), 33)
        for item in unlinked:
            self.assertTrue(item.linkage_note,
                            "%s is unlinked with no note" % item.proposal_id)

    def test_the_legacy_values_are_retained_not_summarised(self):
        with_values = [item for item in self.inventory.entries
                       if item.legacy_values]
        self.assertTrue(with_values)
        seen = set()
        for item in with_values:
            seen.update(item.legacy_values)
        self.assertTrue(seen & set(LEGACY_PROJECT_VALUE_FIELDS))

    def test_the_inventory_is_deterministic(self):
        again = build_review_inventory(PROPOSALS)
        self.assertEqual(again.content_hash(), self.inventory.content_hash())

    def test_the_source_digest_is_recorded(self):
        self.assertTrue(self.inventory.source_sha256.startswith("sha256:"))
        self.assertFalse(os.path.isabs(self.inventory.source_path))


class TestLegacyHintsStayUnreviewed(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(PROPOSALS):
            raise unittest.SkipTest("no WP-08 proposals in this checkout")
        cls.inventory = build_review_inventory(PROPOSALS)

    def test_nothing_is_reviewed(self):
        self.assertEqual(self.inventory.counts()["reviewed_count"], 0)

    def test_every_entry_is_not_reviewed(self):
        states = {item.review_state for item in self.inventory.entries}
        self.assertEqual(states, {LegacyReviewState.NOT_REVIEWED})

    def test_selection_for_an_exercise_is_not_a_review(self):
        first = self.inventory.entries[0].proposal_id
        selected = build_review_inventory(PROPOSALS,
                                          selected_proposal_ids=(first,))
        entry = next(item for item in selected.entries
                     if item.proposal_id == first)
        self.assertEqual(entry.review_state,
                         LegacyReviewState.SELECTED_FOR_EXERCISE)
        self.assertIsNone(entry.reviewed_by)

    def test_a_decided_state_requires_a_named_reviewer(self):
        for state in (LegacyReviewState.ACCEPTED_AS_DRAFT_INPUT,
                      LegacyReviewState.REJECTED_AS_DRAFT_INPUT,
                      LegacyReviewState.NEEDS_MORE_EVIDENCE):
            with self.subTest(state=state):
                with self.assertRaises(CurationError):
                    LegacyProposalEntry(
                        proposal_id="P1", subject="s", review_state=state,
                        linked_evidence=(), linked_record_uuids=(),
                        legacy_values={}, warnings=(), origins=())

    def test_a_decided_state_with_a_reviewer_is_expressible(self):
        """The protocol permits the state; nothing in this package can reach
        it, because nothing here can supply the person."""
        entry = LegacyProposalEntry(
            proposal_id="P1", subject="s",
            review_state=LegacyReviewState.REJECTED_AS_DRAFT_INPUT,
            linked_evidence=(), linked_record_uuids=(), legacy_values={},
            warnings=(), origins=(), reviewed_by="Dr Ayse Yilmaz",
            review_note="The legacy value is not supported by the linked "
                        "evidence.")
        self.assertTrue(entry.is_reviewed)

    def test_selecting_an_unknown_proposal_is_refused(self):
        with self.assertRaises(CurationError):
            build_review_inventory(PROPOSALS,
                                   selected_proposal_ids=("NO-SUCH-ID",))


class TestLegacyValuesNeverBecomeConclusions(unittest.TestCase):

    def test_every_legacy_project_field_is_prohibited_in_a_record(self):
        """The two lists exist for opposite reasons - one names what the
        queue holds, the other what a conclusion may not - and every value in
        the queue must be refused by a conclusion."""
        for name in LEGACY_PROJECT_VALUE_FIELDS:
            with self.subTest(name=name):
                self.assertIn(name, PROHIBITED_CURATION_FIELDS)

    def test_the_curation_prohibition_covers_wp08s_evidence_prohibition(self):
        """A name WP-08 refuses inside an evidence record must not become
        admissible one stage later, where it would look like a reviewed
        conclusion rather than a leftover."""
        from pgx.evidence.models import PROHIBITED_METADATA_FIELDS
        missing = sorted(set(PROHIBITED_METADATA_FIELDS)
                         - set(PROHIBITED_CURATION_FIELDS))
        self.assertEqual(missing, [])

    def test_the_warnings_survive_into_the_inventory(self):
        if not os.path.isfile(PROPOSALS):
            self.skipTest("no WP-08 proposals in this checkout")
        inventory = build_review_inventory(PROPOSALS)
        for entry in inventory.entries[:20]:
            self.assertIn("NOT_EVIDENCE", entry.warnings)
            self.assertIn("DO_NOT_USE_FOR_ASSESSMENT", entry.warnings)


class TestTheWrittenInventory(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(INVENTORY_JSON):
            raise unittest.SkipTest("no inventory artifact in this checkout")
        with io.open(INVENTORY_JSON, encoding="utf-8") as handle:
            cls.payload = json.load(handle)

    def test_it_accounts_for_every_proposal(self):
        self.assertEqual(self.payload["counts"]["proposal_count"], 1559)

    def test_no_entry_is_accepted_or_rejected(self):
        states = set(self.payload["counts"]["by_review_state"])
        self.assertTrue(states <= {"NOT_REVIEWED", "SELECTED_FOR_EXERCISE"})

    def test_it_says_what_it_is(self):
        self.assertIn("not scientific truth", self.payload["note"])
