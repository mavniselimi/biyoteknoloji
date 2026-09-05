# -*- coding: utf-8 -*-
"""Identity, version and origin: three things WP-08 refuses to invent.

An identity is allocated, never derived. A version is what the source said, or
an honest statement that nobody knows. An origin is what the record itself
declares, or ``UNKNOWN`` - never a guess from the record looking
pharmacogenomic.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest

from pgx.evidence.allocation import (EVIDENCE_ALLOCATION_FORMAT_VERSION,
                                     EvidenceAllocation,
                                     EvidenceAllocationEntry,
                                     allocate_evidence_identities,
                                     read_evidence_allocation)
from pgx.evidence.errors import EvidenceAllocationError, SourceRecordError
from pgx.evidence.models import (EvidenceRecordType, OriginStatus,
                                 SourceAttribution, SourceRecordVersion,
                                 VersionStatus, normalize_source_record_id)

from tests.unit.evidence._support import (DATASET_ID, NOW, PROVIDER,
                                          RealEvidenceBuildTestCase, draft,
                                          natural_key)


class TestVersionHonesty(unittest.TestCase):

    def test_a_known_version_must_carry_the_value(self):
        with self.assertRaises(SourceRecordError):
            SourceRecordVersion(status=VersionStatus.KNOWN, value=None)

    def test_every_other_status_must_carry_no_value(self):
        """The one place a fabricated version could hide is beside a status
        that says the version is unknown."""
        for status in VersionStatus:
            if status is VersionStatus.KNOWN:
                continue
            with self.subTest(status=status):
                with self.assertRaises(SourceRecordError):
                    SourceRecordVersion(status=status, value="v1")

    def test_unknown_legacy_is_expressible_without_a_value(self):
        version = SourceRecordVersion(status=VersionStatus.UNKNOWN_LEGACY)
        self.assertIsNone(version.value)
        self.assertFalse(version.is_production_eligible)

    def test_a_source_that_publishes_no_versions_is_not_unknown_legacy(self):
        """Two different facts. ``SOURCE_UNVERSIONED`` means the source has no
        version concept; ``UNKNOWN_LEGACY`` means one existed and was lost."""
        unversioned = SourceRecordVersion(
            status=VersionStatus.SOURCE_UNVERSIONED)
        self.assertTrue(unversioned.is_production_eligible)
        self.assertFalse(SourceRecordVersion(
            status=VersionStatus.UNKNOWN_LEGACY).is_production_eligible)


class TestOriginHonesty(unittest.TestCase):

    def test_a_stated_origin_needs_the_key_it_states(self):
        with self.assertRaises(SourceRecordError):
            SourceAttribution(provider_source_key=PROVIDER,
                              origin_status=OriginStatus.STATED_BY_SOURCE)

    def test_an_unstated_origin_must_not_carry_a_key(self):
        """This is the shape a guess would take: a key beside a status saying
        the source never named one."""
        for status in (OriginStatus.NOT_STATED_BY_SOURCE,
                       OriginStatus.AMBIGUOUS, OriginStatus.UNREGISTERED):
            with self.subTest(status=status):
                with self.assertRaises(SourceRecordError):
                    SourceAttribution(provider_source_key=PROVIDER,
                                      origin_status=status,
                                      origin_source_key="cpic.publications")

    def test_the_provider_is_always_required(self):
        """Where the bytes came from is always known - it is how they arrived."""
        with self.assertRaises(SourceRecordError):
            SourceAttribution(provider_source_key="",
                              origin_status=OriginStatus.NOT_STATED_BY_SOURCE)

    def test_an_unregistered_origin_keeps_the_raw_value_it_could_not_resolve(self):
        attribution = SourceAttribution(
            provider_source_key=PROVIDER,
            origin_status=OriginStatus.UNREGISTERED,
            raw_origin_value="Some Society Nobody Registered")
        self.assertEqual(attribution.raw_origin_value,
                         "Some Society Nobody Registered")


class TestSourceRecordIdentityKeepsItsType(unittest.TestCase):

    def test_an_integer_identity_is_an_identity(self):
        """The source spells some identities as integers. Reporting those as
        anonymous because the column is a string would be a false statement
        about the source."""
        self.assertEqual(normalize_source_record_id(981351915),
                         ("981351915", "int"))

    def test_a_string_identity_keeps_its_type(self):
        self.assertEqual(normalize_source_record_id("PA166104948"),
                         ("PA166104948", "str"))

    def test_a_bool_is_refused_because_true_would_become_one(self):
        self.assertEqual(normalize_source_record_id(True), (None, "bool"))

    def test_a_float_is_refused_rather_than_rounded(self):
        value, kind = normalize_source_record_id(9.813519e08)
        self.assertIsNone(value)
        self.assertEqual(kind, "float")

    def test_absence_is_reported_as_absence(self):
        self.assertEqual(normalize_source_record_id(None), (None, "null"))


class TestIdentityIsAllocatedAndNeverDerived(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="wp08-alloc-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.path = os.path.join(self.root, "evidence-identity-allocation.json")

    def _keys(self, *ids):
        return [natural_key(source_record_id=value).to_string()
                for value in ids]

    def _allocate(self, ids, existing=None, allow_new=False):
        return allocate_evidence_identities(
            DATASET_ID, self._keys(*ids), existing=existing,
            allow_new=allow_new, now=NOW)

    def test_a_missing_identity_is_an_error_unless_allocation_is_permitted(self):
        with self.assertRaises(EvidenceAllocationError):
            self._allocate(("PA1",))

    def test_allocation_mints_only_when_asked(self):
        result = self._allocate(("PA1", "PA2"), allow_new=True)
        self.assertEqual(len(result.minted), 2)
        self.assertEqual(len(result.reused), 0)

    def test_rebuilding_with_the_same_allocation_reuses_every_identity(self):
        first = self._allocate(("PA1", "PA2"), allow_new=True)
        second = self._allocate(("PA1", "PA2"), existing=first.allocation)
        self.assertEqual(len(second.minted), 0)
        self.assertEqual(len(second.reused), 2)
        self.assertEqual(second.allocation.content_hash(),
                         first.allocation.content_hash())

    def test_a_removed_record_does_not_free_its_identity_for_reuse(self):
        """An identity that could be handed to a different record would make
        every citation of the old one silently point at the new one."""
        first = self._allocate(("PA1", "PA2"), allow_new=True)
        kept = {entry.natural_key: entry.record_uuid
                for entry in first.allocation.entries}
        second = self._allocate(("PA2", "PA3"), existing=first.allocation,
                                allow_new=True)
        after = {entry.natural_key: entry.record_uuid
                 for entry in second.allocation.entries}
        for key, value in kept.items():
            self.assertEqual(after[key], value)
        minted = set(after.values()) - set(kept.values())
        self.assertEqual(len(minted), 1)

    def test_a_changed_natural_key_becomes_a_new_record_not_a_mutation(self):
        first = self._allocate(("PA1",), allow_new=True)
        second = self._allocate(("PA1-corrected",), existing=first.allocation,
                                allow_new=True)
        self.assertEqual(len(second.allocation), 2)

    def _entry(self, source_record_id, record_uuid):
        return EvidenceAllocationEntry(
            natural_key=natural_key(source_record_id=source_record_id)
            .to_string(),
            record_uuid=record_uuid, first_allocated_at=NOW)

    def test_two_entries_may_not_share_a_key(self):
        with self.assertRaises(EvidenceAllocationError):
            EvidenceAllocation(
                dataset_public_id=DATASET_ID, created_at=NOW,
                entries=(self._entry("PA1", "11111111-1111-4111-8111-111111111111"),
                         self._entry("PA1", "22222222-2222-4222-8222-222222222222")))

    def test_two_entries_may_not_share_a_uuid(self):
        """One UUID naming two records would make every citation ambiguous."""
        with self.assertRaises(EvidenceAllocationError):
            EvidenceAllocation(
                dataset_public_id=DATASET_ID, created_at=NOW,
                entries=(self._entry("PA1", "11111111-1111-4111-8111-111111111111"),
                         self._entry("PA2", "11111111-1111-4111-8111-111111111111")))

    def test_an_identity_is_not_a_hash_of_the_content(self):
        """Content-derived identity would make a corrected record a different
        record, and would let the resolver mint silently."""
        first = self._allocate(("PA1",), allow_new=True)
        again = self._allocate(("PA1",), allow_new=True)
        self.assertNotEqual(first.allocation.entries[0].record_uuid,
                            again.allocation.entries[0].record_uuid)

    def test_a_written_allocation_reads_back_with_its_hash_recomputed(self):
        result = self._allocate(("PA1",), allow_new=True)
        with io.open(self.path, "w", encoding="utf-8") as handle:
            json.dump(result.allocation.to_json(), handle)
        loaded = read_evidence_allocation(self.path)
        self.assertEqual(loaded.content_hash(),
                         result.allocation.content_hash())
        self.assertEqual(loaded.allocation_format_version,
                         EVIDENCE_ALLOCATION_FORMAT_VERSION)


class TestTheRealBuildIsHonestAboutAllThree(RealEvidenceBuildTestCase):

    def test_no_stored_record_carries_a_version_it_does_not_know(self):
        offences = []
        for row in self.rows("evidence-records.ndjson"):
            version = row.get("version") or {}
            if version.get("status") != "KNOWN" and version.get("value"):
                offences.append((row["natural_key"]["natural_key"],
                                 version))
        self.assertEqual(offences, [])

    def test_unknown_legacy_is_the_recorded_answer_where_history_was_lost(self):
        counts = {}
        for row in self.rows("evidence-records.ndjson"):
            status = (row.get("version") or {}).get("status")
            counts[status] = counts.get(status, 0) + 1
        self.assertIn("UNKNOWN_LEGACY", counts)
        self.assertNotIn("v1", counts)

    def test_no_stored_record_names_an_origin_it_did_not_state(self):
        offences = []
        for row in self.rows("evidence-records.ndjson"):
            attribution = row.get("attribution") or {}
            stated = attribution.get("origin_status") == "STATED_BY_SOURCE"
            has_key = bool(attribution.get("origin_source_key"))
            if stated != has_key:
                offences.append(row["natural_key"]["natural_key"])
        self.assertEqual(offences, [])

    def test_cpic_is_not_assumed_for_records_that_merely_look_pharmacogenomic(self):
        """Most of this corpus is pharmacogenomic and states no origin. If a
        guess were being made, these would carry one."""
        unstated = [row for row in self.rows("evidence-records.ndjson")
                    if (row.get("attribution") or {}).get("origin_status")
                    == "NOT_STATED_BY_SOURCE"]
        self.assertTrue(unstated)
        for row in unstated:
            self.assertIsNone((row.get("attribution") or {})
                              .get("origin_source_key"))

    def test_integer_identities_survive_as_integers(self):
        kinds = {row.get("source_record_id_raw_type")
                 for row in self.rows("evidence-records.ndjson")}
        self.assertIn("int", kinds)
        self.assertIn("str", kinds)

    def test_every_allocated_identity_is_unique(self):
        uuids = [row["record_uuid"]
                 for row in self.rows("evidence-records.ndjson")]
        self.assertEqual(len(uuids), len(set(uuids)))
