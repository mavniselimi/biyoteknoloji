# -*- coding: utf-8 -*-
"""Explicit identity allocation (WP-07).

Two requirements pull in opposite directions: a scientific UUID must not be a
function of a name, and a rebuild must produce the same UUIDs. The only way to
satisfy both is to write the mapping down. Everything below checks that the
mapping is the *only* route to an identity.
"""

from __future__ import annotations

import ast
import datetime as _dt
import io
import json
import os
import tempfile
import unittest
import uuid

from pgx.domain.identifiers import DrugId, GeneId, SourceRegistryEntryId
from pgx.normalization.allocation import (ALLOCATION_FORMAT_VERSION,
                                          ALLOCATOR_TOOL_ID, AllocationEntry,
                                          IdentityAllocation,
                                          allocate_identities, read_allocation)
from pgx.normalization.errors import AllocationError
from pgx.normalization.models import EntityType

from tests.unit.normalization._support import DATASET_ID, REPO_ROOT

ALLOCATION = os.path.join("pgx", "normalization", "allocation.py")
NOW = _dt.datetime(2026, 8, 30, 12, 0, tzinfo=_dt.timezone.utc)
KEYS = ("DRUG:clopidogrel", "GENE:CYP2C19", "GENE:CYP2D6")


def _source(relative: str) -> str:
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


def _allocate(keys=KEYS, **changes):
    kwargs = dict(existing=None, allow_new=True, now=NOW)
    kwargs.update(changes)
    return allocate_identities(DATASET_ID, keys, **kwargs)


class TestAllocationIsExplicit(unittest.TestCase):

    def test_minting_is_refused_unless_the_caller_asked(self):
        with self.assertRaises(AllocationError) as caught:
            allocate_identities(DATASET_ID, KEYS, now=NOW)
        self.assertIn("may not mint", str(caught.exception))

    def test_asking_explicitly_mints_exactly_the_missing_keys(self):
        result = _allocate()
        self.assertEqual(result.minted, tuple(sorted(KEYS)))
        self.assertEqual(result.reused, ())
        self.assertFalse(result.is_rebuild)

    def test_a_rebuild_reuses_and_mints_nothing(self):
        first = _allocate()
        second = allocate_identities(DATASET_ID, KEYS,
                                     existing=first.allocation, now=NOW)
        self.assertTrue(second.is_rebuild)
        self.assertEqual(second.minted, ())
        self.assertEqual(second.allocation.content_hash(),
                         first.allocation.content_hash())

    def test_a_rebuild_that_would_need_a_new_identity_fails_loudly(self):
        first = _allocate()
        with self.assertRaises(AllocationError):
            allocate_identities(DATASET_ID, KEYS + ("GENE:CYP3A4",),
                                existing=first.allocation, now=NOW)


class TestIdentitiesAreNeverDerived(unittest.TestCase):

    def test_two_allocations_of_the_same_key_differ(self):
        """A UUID derived from the name would make these equal.

        Two curation runs that observed the same source must produce two
        distinct identities unless they deliberately share an allocation.
        """
        left = _allocate(keys=("GENE:CYP2C19",))
        right = _allocate(keys=("GENE:CYP2C19",))
        self.assertNotEqual(left.allocation.uuid_for("GENE:CYP2C19"),
                            right.allocation.uuid_for("GENE:CYP2C19"))

    def test_gene_and_drug_identifiers_still_have_no_derive(self):
        self.assertFalse(hasattr(GeneId, "derive"))
        self.assertFalse(hasattr(DrugId, "derive"))

    def test_derive_still_exists_only_on_the_technical_source_id(self):
        self.assertTrue(hasattr(SourceRegistryEntryId, "derive"))

    def test_the_module_never_calls_uuid5(self):
        tree = ast.parse(_source(ALLOCATION), filename=ALLOCATION)
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    called.add(func.attr)
                elif isinstance(func, ast.Name):
                    called.add(func.id)
        self.assertNotIn("uuid5", called)
        self.assertNotIn("uuid3", called)
        self.assertNotIn("derive", called)

    def test_the_allocator_is_named_as_a_tool_not_a_person(self):
        """Allocation is bookkeeping; attributing it to a human would be a
        fabricated review."""
        self.assertIn("/", ALLOCATOR_TOOL_ID)
        self.assertEqual(_allocate().allocation.allocated_by, ALLOCATOR_TOOL_ID)


class TestNothingIsEverReclaimed(unittest.TestCase):

    def test_a_key_that_disappears_keeps_its_identity(self):
        first = _allocate()
        original = first.allocation.uuid_for("GENE:CYP2D6")
        second = allocate_identities(DATASET_ID, ("GENE:CYP2C19",),
                                     existing=first.allocation, now=NOW)
        self.assertEqual(len(second.allocation), 3)
        self.assertEqual(second.allocation.uuid_for("GENE:CYP2D6"), original)

    def test_unused_keys_are_reported_rather_than_dropped(self):
        first = _allocate()
        second = allocate_identities(DATASET_ID, ("GENE:CYP2C19",),
                                     existing=first.allocation, now=NOW)
        self.assertEqual(second.unused, ("DRUG:clopidogrel", "GENE:CYP2D6"))

    def test_a_key_that_reappears_gets_the_identity_it_had(self):
        first = _allocate()
        original = first.allocation.uuid_for("GENE:CYP2D6")
        narrowed = allocate_identities(DATASET_ID, ("GENE:CYP2C19",),
                                       existing=first.allocation, now=NOW)
        restored = allocate_identities(DATASET_ID, KEYS,
                                       existing=narrowed.allocation, now=NOW)
        self.assertTrue(restored.is_rebuild)
        self.assertEqual(restored.allocation.uuid_for("GENE:CYP2D6"), original)


class TestMalformedKeysAreRefused(unittest.TestCase):

    def test_an_unnormalised_key_is_refused(self):
        """``GENE:cyp2c19`` beside ``GENE:CYP2C19`` would split one gene."""
        for key in ("GENE:cyp2c19", "DRUG:Clopidogrel", "GENE:CYP 2C19"):
            with self.subTest(key=key):
                with self.assertRaises(AllocationError):
                    _allocate(keys=(key,))

    def test_an_unknown_entity_type_is_refused(self):
        with self.assertRaises(AllocationError):
            _allocate(keys=("PROTEIN:abc",))

    def test_a_key_with_no_value_is_refused(self):
        with self.assertRaises(AllocationError):
            _allocate(keys=("GENE:",))

    def test_a_key_with_no_type_is_refused(self):
        with self.assertRaises(AllocationError):
            _allocate(keys=("CYP2C19",))


class TestCollisionsAreRefused(unittest.TestCase):

    def test_one_key_allocated_twice_is_refused(self):
        entry = AllocationEntry(EntityType.GENE, "GENE:CYP2C19",
                                str(uuid.uuid4()), NOW)
        other = AllocationEntry(EntityType.GENE, "GENE:CYP2C19",
                                str(uuid.uuid4()), NOW)
        with self.assertRaises(AllocationError):
            IdentityAllocation(DATASET_ID, (entry, other), NOW)

    def test_one_identity_shared_by_two_keys_is_refused(self):
        value = str(uuid.uuid4())
        left = AllocationEntry(EntityType.GENE, "GENE:CYP2C19", value, NOW)
        right = AllocationEntry(EntityType.GENE, "GENE:CYP2D6", value, NOW)
        with self.assertRaises(AllocationError):
            IdentityAllocation(DATASET_ID, (left, right), NOW)

    def test_a_factory_that_repeats_itself_is_refused(self):
        fixed = uuid.uuid4()
        with self.assertRaises(AllocationError):
            _allocate(uuid_factory=lambda: fixed)

    def test_a_factory_returning_the_wrong_type_is_refused(self):
        with self.assertRaises(AllocationError):
            _allocate(uuid_factory=lambda: "not-a-uuid")


class TestAllocationIsBoundToItsDataset(unittest.TestCase):

    def test_reusing_another_datasets_allocation_is_refused(self):
        first = _allocate()
        with self.assertRaises(AllocationError):
            allocate_identities("PGX-DATA-20260830-901", KEYS,
                                existing=first.allocation, allow_new=True,
                                now=NOW)


class TestSerialisation(unittest.TestCase):

    def test_a_round_trip_preserves_the_content_hash(self):
        allocation = _allocate().allocation
        payload = json.loads(json.dumps(allocation.to_json()))
        self.assertEqual(IdentityAllocation.from_json(payload).content_hash(),
                         allocation.content_hash())

    def test_an_edited_entry_is_detected(self):
        allocation = _allocate().allocation
        payload = json.loads(json.dumps(allocation.to_json()))
        payload["entries"][0]["entity_uuid"] = str(uuid.uuid4())
        with self.assertRaises(AllocationError):
            IdentityAllocation.from_json(payload)

    def test_an_edited_entry_count_is_detected(self):
        allocation = _allocate().allocation
        payload = json.loads(json.dumps(allocation.to_json()))
        payload["entry_count"] = 99
        with self.assertRaises(AllocationError):
            IdentityAllocation.from_json(payload)

    def test_a_foreign_format_version_is_refused_not_upgraded(self):
        allocation = _allocate().allocation
        payload = json.loads(json.dumps(allocation.to_json()))
        payload["allocation_format_version"] = "pgx-identity-allocation/99"
        with self.assertRaises(AllocationError):
            IdentityAllocation.from_json(payload)

    def test_the_content_hash_excludes_every_timestamp(self):
        early = _allocate()
        late = allocate_identities(
            DATASET_ID, KEYS, existing=early.allocation,
            now=_dt.datetime(2027, 1, 1, tzinfo=_dt.timezone.utc))
        self.assertEqual(early.allocation.content_hash(),
                         late.allocation.content_hash())

    def test_reading_a_missing_file_names_the_path(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(AllocationError) as caught:
                read_allocation(os.path.join(directory, "absent.json"))
            self.assertIn("absent.json", str(caught.exception))

    def test_reading_an_unparsable_file_is_an_allocation_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "identity-allocation.json")
            with io.open(path, "w", encoding="utf-8") as handle:
                handle.write("{ not json")
            with self.assertRaises(AllocationError):
                read_allocation(path)

    def test_a_written_allocation_reads_back_identically(self):
        allocation = _allocate().allocation
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "identity-allocation.json")
            with io.open(path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(allocation.to_json()))
            self.assertEqual(read_allocation(path).content_hash(),
                             allocation.content_hash())


class TestLookup(unittest.TestCase):

    def test_a_missing_identity_raises_rather_than_minting(self):
        allocation = _allocate(keys=("GENE:CYP2C19",)).allocation
        with self.assertRaises(AllocationError) as caught:
            allocation.uuid_for("GENE:CYP2D6")
        self.assertIn("explicit step", str(caught.exception))

    def test_get_returns_none_without_raising(self):
        allocation = _allocate(keys=("GENE:CYP2C19",)).allocation
        self.assertIsNone(allocation.get("GENE:CYP2D6"))

    def test_missing_for_lists_what_a_build_would_need(self):
        allocation = _allocate(keys=("GENE:CYP2C19",)).allocation
        self.assertEqual(allocation.missing_for(KEYS),
                         ("DRUG:clopidogrel", "GENE:CYP2D6"))

    def test_entries_are_sorted_so_two_files_agree(self):
        allocation = _allocate(keys=tuple(reversed(KEYS))).allocation
        self.assertEqual(allocation.canonical_keys, tuple(sorted(KEYS)))

    def test_the_format_version_is_recorded(self):
        self.assertEqual(_allocate().allocation.allocation_format_version,
                         ALLOCATION_FORMAT_VERSION)


if __name__ == "__main__":
    unittest.main()
