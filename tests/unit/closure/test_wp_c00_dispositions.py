# -*- coding: utf-8 -*-
"""WP-C00 section A.5: a disposition for every unlinked legacy candidate.

The WP-11 inventory reports 33 unlinked candidates. This report says what
happens to each of them. Most of this file exists to keep it from saying
anything more than that: no link is written, no blocker is cleared, no legacy
opinion is copied forward as a value.

Counts are pinned against the real repository rather than a fixture. If one
changes, that is either a real change to the data or a defect, and either way
somebody should look.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest

from pgx.application.snapshot_schema import validate_against_schema
from pgx.closure.legacy_dispositions import (DISPOSITIONS, FIRST_RELEASE_AXES,
                                             REPORT_VERSION,
                                             _decide,
                                             _exact_evidence_matches,
                                             build_report, canonical_json,
                                             render_markdown)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
REPORT_JSON = os.path.join(REPO_ROOT, "data", "closure",
                           "wp-c00-legacy-candidate-dispositions.json")
SUMMARY_MD = os.path.join(REPO_ROOT, "docs", "closure",
                          "wp-c00-legacy-candidate-dispositions.md")
SCHEMA_JSON = os.path.join(REPO_ROOT, "schemas",
                           "closure-legacy-candidate-disposition.schema.json")
INVENTORY_JSON = os.path.join(REPO_ROOT, "data", "migration", "wp11",
                              "legacy-rule-candidate-inventory.json")
PROPOSALS_NDJSON = os.path.join(REPO_ROOT, "data", "migration", "wp08",
                                "draft-curation-proposals.ndjson")

#: The state of the real repository. Exact, not a lower bound.
EXPECTED_UNLINKED = 33
EXPECTED_IN_SCOPE = 13
EXPECTED_OUTSIDE_SCOPE = 20
EXPECTED_CSV_ORIGIN = 22
EXPECTED_PYTHON_ORIGIN = 11


def _read_json(path):
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


class TestTheReportCoversEveryUnlinkedCandidate(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.report = build_report(REPO_ROOT)
        cls.inventory = _read_json(INVENTORY_JSON)

    def test_the_unlinked_count_is_the_inventorys_own(self):
        unlinked = [item for item in self.inventory["candidates"]
                    if not item["linked"]]
        self.assertEqual(len(unlinked), EXPECTED_UNLINKED)
        self.assertEqual(self.report["counts"]["unlinked_candidates"],
                         EXPECTED_UNLINKED)

    def test_every_unlinked_candidate_appears_exactly_once(self):
        expected = sorted(item["candidate_id"]
                          for item in self.inventory["candidates"]
                          if not item["linked"])
        actual = sorted(item["candidate_id"]
                        for item in self.report["candidates"])
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), len(set(actual)))

    def test_no_linked_candidate_leaks_into_the_report(self):
        linked = {item["candidate_id"] for item in self.inventory["candidates"]
                  if item["linked"]}
        named = {item["candidate_id"] for item in self.report["candidates"]}
        self.assertEqual(linked & named, set())

    def test_each_candidate_carries_exactly_one_known_disposition(self):
        for item in self.report["candidates"]:
            self.assertIn(item["disposition"], DISPOSITIONS,
                          item["candidate_id"])
            self.assertTrue(item["disposition_basis"], item["candidate_id"])

    def test_the_disposition_counts_add_up(self):
        counts = self.report["counts"]["by_disposition"]
        self.assertEqual(sum(counts.values()), EXPECTED_UNLINKED)
        self.assertEqual(counts["MISSING_EVIDENCE_REQUIRES_CURATOR"],
                         EXPECTED_IN_SCOPE)
        self.assertEqual(counts["OUTSIDE_FIRST_RELEASE_SCOPE"],
                         EXPECTED_OUTSIDE_SCOPE)


class TestWhatTheReportMeasured(unittest.TestCase):
    """The claims that carry the argument are measured, not asserted."""

    @classmethod
    def setUpClass(cls):
        cls.report = build_report(REPO_ROOT)

    def test_every_origin_pointer_still_resolves(self):
        counts = self.report["counts"]
        self.assertEqual(counts["origins_resolving"], EXPECTED_UNLINKED)
        for item in self.report["candidates"]:
            self.assertTrue(item["origin"]["origin_file_present"],
                            item["candidate_id"])
            self.assertTrue(
                item["origin"]["origin_file_sha256_matches_migration"],
                item["candidate_id"])

    def test_the_two_origin_files_split_as_the_migration_recorded(self):
        by_file = self.report["counts"]["by_origin_file"]
        self.assertEqual(
            by_file["clinpgx_mvp_seed/phenotype_effect_rules.csv"],
            EXPECTED_CSV_ORIGIN)
        self.assertEqual(by_file["clean_mvp_seed_dataset.py"],
                         EXPECTED_PYTHON_ORIGIN)

    def test_no_unlinked_candidate_names_an_upstream_record(self):
        """The reason none is linked, stated as the measurement it came from.

        Every linked proposal names an upstream accession in its subject and
        none of the unlinked ones does. That contrast is the whole finding: a
        candidate that names no identifier cannot be looked up, and attaching
        it to a record with a matching gene and drug would be the guess the
        migration already refused.
        """
        state = self.report["upstream_state"]
        self.assertEqual(state["unlinked_proposals_naming_an_upstream_accession"],
                         0)
        self.assertEqual(state["linked_proposals_naming_an_upstream_accession"],
                         state["linked_candidates"])
        self.assertEqual(self.report["counts"]["naming_an_upstream_record"], 0)

    def test_the_scope_split_uses_the_declared_first_release_axes(self):
        axes = {"%s::%s" % pair for pair in FIRST_RELEASE_AXES}
        self.assertEqual(
            sorted(self.report["first_release_scope"]["axes"]), sorted(axes))
        for item in self.report["candidates"]:
            self.assertEqual(item["in_first_release_scope"],
                             item["axis"] in axes, item["candidate_id"])

    def test_the_evidence_build_is_reported_as_quarantined(self):
        labels = self.report["upstream_state"][
            "evidence_build_lifecycle_labels"]
        self.assertIn("QUARANTINED", labels)


class TestTheReportPromotesNothing(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.report = build_report(REPO_ROOT)
        cls.proposals = {}
        with io.open(PROPOSALS_NDJSON, encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    row = json.loads(line)
                    cls.proposals[row["proposal_id"]] = row

    def test_no_candidate_is_marked_eligible(self):
        for item in self.report["candidates"]:
            self.assertFalse(item["eligible_for_rule_creation"],
                             item["candidate_id"])

    def test_no_blocker_is_cleared(self):
        for item in self.report["candidates"]:
            self.assertTrue(item["blocker_codes"], item["candidate_id"])
            self.assertIn("NO_EVIDENCE_LINK", item["blocker_codes"],
                          item["candidate_id"])

    def test_no_evidence_record_uuid_is_attached(self):
        for item in self.report["candidates"]:
            self.assertEqual(item["upstream_record"]
                             ["exact_evidence_record_uuids"], [])
            self.assertEqual(item["upstream_record"]["declared_record_uuids"],
                             [])

    def test_no_legacy_value_is_copied_into_the_report(self):
        """Field names may appear; the values behind them may not.

        ``legacy_values_present`` deliberately lists the names of the legacy
        fields a record carries, because whether a row had a risk level is a
        fact about the record. What it said is the previous project's
        unreviewed opinion. Short strings are skipped because a three-letter
        value would collide with ordinary prose and prove nothing.
        """
        for item in self.report["candidates"]:
            rendered = json.dumps(item, sort_keys=True, ensure_ascii=False)
            legacy = self.proposals[item["legacy_proposal_id"]][
                "legacy_values"]
            for name, value in legacy.items():
                self.assertIn(name, item["legacy_values_present"],
                              item["candidate_id"])
                if isinstance(value, str) and len(value) >= 8:
                    self.assertNotIn(value, rendered,
                                     "%s leaked %s" % (item["candidate_id"],
                                                       name))

    def test_outside_scope_is_not_a_scientific_rejection(self):
        meaning = self.report["disposition_meanings"][
            "OUTSIDE_FIRST_RELEASE_SCOPE"]
        self.assertIn("not a scientific rejection", meaning)
        for item in self.report["candidates"]:
            if item["disposition"] == "OUTSIDE_FIRST_RELEASE_SCOPE":
                self.assertIn("NO_EVIDENCE_LINK", item["blocker_codes"])

    def test_in_scope_candidates_stay_visibly_human_blocked(self):
        for item in self.report["candidates"]:
            if item["disposition"] == "MISSING_EVIDENCE_REQUIRES_CURATOR":
                self.assertIn("curator", item["human_action_required"])


class TestTheDecisionProcedure(unittest.TestCase):
    """The branches the real data does not currently reach, exercised."""

    ORIGIN_OK = {
        "relative_path": "seed.csv",
        "origin_file_present": True,
        "origin_file_sha256_matches_migration": True,
        "pointer_resolves": True,
        "pointer_kind": "CSV_ROW",
    }
    NO_UPSTREAM = {"names_upstream_record": False, "upstream_record_id": None}
    UPSTREAM = {"names_upstream_record": True,
                "upstream_record_id": "PA166000001"}

    def test_an_exact_single_match_is_mechanically_linkable(self):
        disposition, basis = _decide(True, self.ORIGIN_OK, self.UPSTREAM,
                                     None, ["uuid-1"])
        self.assertEqual(disposition, "MECHANICALLY_LINKABLE")
        self.assertIn("PA166000001", basis[0])

    def test_two_matches_are_not_a_link(self):
        disposition, _ = _decide(True, self.ORIGIN_OK, self.UPSTREAM, None,
                                 ["uuid-1", "uuid-2"])
        self.assertEqual(disposition, "MISSING_EVIDENCE_REQUIRES_CURATOR")

    def test_a_missing_origin_file_is_unresolvable(self):
        origin = dict(self.ORIGIN_OK, origin_file_present=False)
        disposition, _ = _decide(True, origin, self.NO_UPSTREAM, None, [])
        self.assertEqual(disposition,
                         "MALFORMED_OR_UNRESOLVABLE_MIGRATION_RECORD")

    def test_a_changed_origin_file_is_unresolvable(self):
        origin = dict(self.ORIGIN_OK,
                      origin_file_sha256_matches_migration=False)
        disposition, _ = _decide(True, origin, self.NO_UPSTREAM, None, [])
        self.assertEqual(disposition,
                         "MALFORMED_OR_UNRESOLVABLE_MIGRATION_RECORD")

    def test_an_unresolvable_pointer_is_unresolvable(self):
        origin = dict(self.ORIGIN_OK, pointer_resolves=False)
        disposition, _ = _decide(True, origin, self.NO_UPSTREAM, None, [])
        self.assertEqual(disposition,
                         "MALFORMED_OR_UNRESOLVABLE_MIGRATION_RECORD")

    def test_a_twin_supersedes(self):
        disposition, basis = _decide(True, self.ORIGIN_OK, self.NO_UPSTREAM,
                                     "MIGRATION-PROPOSAL-twin", [])
        self.assertEqual(disposition,
                         "DUPLICATE_OR_SUPERSEDED_MIGRATION_ITEM")
        self.assertIn("MIGRATION-PROPOSAL-twin", basis[0])

    def test_out_of_scope_beats_the_curator_default(self):
        disposition, _ = _decide(False, self.ORIGIN_OK, self.NO_UPSTREAM,
                                 None, [])
        self.assertEqual(disposition, "OUTSIDE_FIRST_RELEASE_SCOPE")

    def test_a_resolvable_in_scope_candidate_falls_to_the_curator(self):
        disposition, _ = _decide(True, self.ORIGIN_OK, self.NO_UPSTREAM,
                                 None, [])
        self.assertEqual(disposition, "MISSING_EVIDENCE_REQUIRES_CURATOR")


class TestTheEvidenceLookup(unittest.TestCase):
    """The lookup matches whole accessions and agreeing entities, or nothing."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="pgx-closure-test-")
        directory = os.path.join(self.root, "data", "evidence",
                                 "PGX-DATA-20260830-900")
        os.makedirs(directory)
        rows = [
            {"record_uuid": "uuid-exact",
             "raw_source_payload": {"accessionId": "PA166000001"},
             "entity_links": [
                 {"entity_type": "GENE", "canonical_key": "GENE:CYP2C19"},
                 {"entity_type": "DRUG", "canonical_key": "DRUG:clopidogrel"}]},
            {"record_uuid": "uuid-wrong-drug",
             "raw_source_payload": {"accessionId": "PA166000002"},
             "entity_links": [
                 {"entity_type": "GENE", "canonical_key": "GENE:CYP2C19"},
                 {"entity_type": "DRUG", "canonical_key": "DRUG:omeprazole"}]},
            {"record_uuid": "uuid-longer-accession",
             "raw_source_payload": {"accessionId": "PA1660000039"},
             "entity_links": [
                 {"entity_type": "GENE", "canonical_key": "GENE:CYP2D6"},
                 {"entity_type": "DRUG", "canonical_key": "DRUG:codeine"}]},
        ]
        with io.open(os.path.join(directory, "evidence-records.ndjson"), "w",
                     encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_an_agreeing_record_resolves(self):
        found = _exact_evidence_matches(
            self.root, {"c1": ("PA166000001", "CYP2C19::clopidogrel")})
        self.assertEqual(found["c1"], ["uuid-exact"])

    def test_a_record_whose_drug_disagrees_does_not_resolve(self):
        found = _exact_evidence_matches(
            self.root, {"c2": ("PA166000002", "CYP2C19::clopidogrel")})
        self.assertEqual(found["c2"], [])

    def test_a_prefix_is_not_a_match(self):
        """``PA166000003`` is a prefix of ``PA1660000039`` and must not match."""
        found = _exact_evidence_matches(
            self.root, {"c3": ("PA166000003", "CYP2D6::codeine")})
        self.assertEqual(found["c3"], [])

    def test_nothing_wanted_reads_nothing(self):
        self.assertEqual(_exact_evidence_matches(self.root, {}), {})


class TestTheCommittedArtifact(unittest.TestCase):

    def test_the_committed_file_is_what_the_producer_writes(self):
        with io.open(REPORT_JSON, encoding="utf-8") as handle:
            committed = handle.read()
        self.assertEqual(committed, canonical_json(build_report(REPO_ROOT)))

    def test_rebuilding_produces_identical_bytes(self):
        self.assertEqual(canonical_json(build_report(REPO_ROOT)),
                         canonical_json(build_report(REPO_ROOT)))

    def test_the_artifact_validates_against_its_schema(self):
        errors = validate_against_schema(_read_json(REPORT_JSON),
                                         _read_json(SCHEMA_JSON))
        self.assertEqual(list(errors), [])

    def test_the_version_is_the_one_the_schema_pins(self):
        self.assertEqual(_read_json(REPORT_JSON)["disposition_report_version"],
                         REPORT_VERSION)

    def test_the_committed_summary_is_what_the_renderer_writes(self):
        with io.open(SUMMARY_MD, encoding="utf-8") as handle:
            committed = handle.read()
        self.assertEqual(committed, render_markdown(build_report(REPO_ROOT)))

    def test_the_summary_names_every_candidate_exactly_once(self):
        """The prose and the JSON cannot disagree about who is in the list."""
        with io.open(SUMMARY_MD, encoding="utf-8") as handle:
            rendered = handle.read()
        for item in build_report(REPO_ROOT)["candidates"]:
            self.assertEqual(rendered.count("`%s`" % item["candidate_id"]), 1,
                             item["candidate_id"])

    def test_the_content_hash_covers_the_document(self):
        document = _read_json(REPORT_JSON)
        recomputed = build_report(REPO_ROOT)["content_hash"]
        self.assertEqual(document["content_hash"], recomputed)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
