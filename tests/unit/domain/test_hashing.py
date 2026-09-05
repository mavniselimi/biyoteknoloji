# -*- coding: utf-8 -*-
"""Canonical hashing determinism (WP-02)."""

from __future__ import annotations

import datetime as _dt
import subprocess
import sys
import unittest
import uuid

from tests.unit.domain._fixtures import NAIVE, NOW, REPO_ROOT

from pgx.domain.enums import AttentionLevel, Phenotype
from pgx.domain.errors import CanonicalizationError, InvalidTemporalValueError
from pgx.domain.hashing import (
    DIGEST_PREFIX, canonical_json, ensure_utc, is_canonical_digest, sha256_digest,
)
from pgx.domain.identifiers import GeneId


class TestDigestFormat(unittest.TestCase):

    def test_digest_uses_the_documented_prefix(self):
        digest = sha256_digest({"a": 1})
        self.assertTrue(digest.startswith(DIGEST_PREFIX))
        self.assertTrue(is_canonical_digest(digest))
        self.assertEqual(len(digest), len(DIGEST_PREFIX) + 64)

    def test_is_canonical_digest_rejects_other_spellings(self):
        for bad in ("a" * 64, "sha256:" + "A" * 64, "sha1:" + "a" * 40,
                    "sha256:" + "a" * 63, "", None, 42):
            self.assertFalse(is_canonical_digest(bad), repr(bad))


class TestOrderSemantics(unittest.TestCase):

    def test_object_key_order_does_not_change_the_hash(self):
        first = {"b": 1, "a": {"y": 2, "x": [1, 2]}, "c": True}
        second = {"c": True, "a": {"x": [1, 2], "y": 2}, "b": 1}
        self.assertEqual(sha256_digest(first), sha256_digest(second))

    def test_array_order_changes_the_hash(self):
        self.assertNotEqual(sha256_digest([1, 2, 3]), sha256_digest([3, 2, 1]))
        self.assertNotEqual(sha256_digest({"x": ["a", "b"]}),
                            sha256_digest({"x": ["b", "a"]}))

    def test_set_member_order_does_not_change_the_hash(self):
        self.assertEqual(sha256_digest({"s": {1, 2, 3}}), sha256_digest({"s": {3, 1, 2}}))
        self.assertEqual(sha256_digest(frozenset(["b", "a"])),
                         sha256_digest(frozenset(["a", "b"])))

    def test_nested_structures_are_stable(self):
        payload = {"outer": [{"k": 1, "j": 2}, {"j": 4, "k": 3}]}
        mirrored = {"outer": [{"j": 2, "k": 1}, {"k": 3, "j": 4}]}
        self.assertEqual(sha256_digest(payload), sha256_digest(mirrored))


class TestTypeSupport(unittest.TestCase):

    def test_uuid_enum_and_aware_datetime_are_supported(self):
        payload = {
            "id": uuid.UUID("12345678-1234-5678-1234-567812345678"),
            "phenotype": Phenotype.POOR,
            "attention": AttentionLevel.HIGH,
            "at": NOW,
            "typed_id": GeneId(uuid.UUID("12345678-1234-5678-1234-567812345678")),
        }
        self.assertTrue(is_canonical_digest(sha256_digest(payload)))

    def test_enum_hashes_as_its_value(self):
        self.assertEqual(sha256_digest(Phenotype.POOR), sha256_digest("POOR"))

    def test_typed_identifier_hashes_as_its_uuid_string(self):
        value = uuid.uuid4()
        self.assertEqual(sha256_digest(GeneId(value)), sha256_digest(str(value)))

    def test_equivalent_instants_in_different_zones_hash_identically(self):
        istanbul = _dt.timezone(_dt.timedelta(hours=3))
        same_instant = _dt.datetime(2026, 8, 29, 15, 0, tzinfo=istanbul)
        self.assertEqual(sha256_digest(NOW), sha256_digest(same_instant))

    def test_date_and_datetime_are_distinct(self):
        self.assertNotEqual(sha256_digest(_dt.date(2026, 8, 29)), sha256_digest(NOW))

    def test_true_and_one_are_distinct(self):
        self.assertNotEqual(sha256_digest({"v": True}), sha256_digest({"v": 1}))


class TestRejections(unittest.TestCase):

    def test_nan_and_infinity_are_rejected(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(CanonicalizationError, msg=repr(bad)):
                sha256_digest({"v": bad})

    def test_naive_datetime_is_rejected(self):
        with self.assertRaises(InvalidTemporalValueError):
            sha256_digest({"at": NAIVE})
        with self.assertRaises(InvalidTemporalValueError):
            ensure_utc(NAIVE)

    def test_bytes_are_rejected(self):
        with self.assertRaises(CanonicalizationError):
            sha256_digest({"blob": b"\x00\x01"})

    def test_non_string_object_keys_are_rejected(self):
        with self.assertRaises(CanonicalizationError):
            sha256_digest({1: "a"})

    def test_unknown_types_are_rejected_rather_than_repr_hashed(self):
        class Opaque:
            pass

        with self.assertRaises(CanonicalizationError):
            sha256_digest({"v": Opaque()})

    def test_excessive_nesting_is_rejected(self):
        payload: object = "leaf"
        for _ in range(80):
            payload = {"n": payload}
        with self.assertRaises(CanonicalizationError):
            sha256_digest(payload)


class TestNoImplicitContext(unittest.TestCase):

    def test_no_timestamp_is_folded_into_the_payload(self):
        payload = {"a": 1}
        self.assertEqual(sha256_digest(payload), sha256_digest(payload))
        self.assertNotIn("timestamp", canonical_json(payload))
        self.assertEqual(canonical_json(payload), '{"a":1}')

    def test_canonical_json_uses_fixed_separators_and_keeps_unicode(self):
        self.assertEqual(canonical_json({"b": 2, "a": 1}), '{"a":1,"b":2}')
        self.assertEqual(canonical_json({"t": "ü"}), '{"t":"ü"}')

    def test_hash_is_identical_in_a_separate_process(self):
        """Guards against anything process-local leaking into the digest."""
        script = (
            "import sys; sys.path.insert(0, %r)\n"
            "from pgx.domain.hashing import sha256_digest\n"
            "print(sha256_digest({'b': [1, 2], 'a': 'x', 'c': {'d': True}}))\n"
            % REPO_ROOT
        )
        outputs = set()
        for seed in ("0", "1", "random"):
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=REPO_ROOT, env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            self.assertEqual(completed.returncode, 0,
                             completed.stderr.decode("utf-8", "replace"))
            outputs.add(completed.stdout.decode().strip())
        self.assertEqual(len(outputs), 1, outputs)
        self.assertEqual(outputs.pop(),
                         sha256_digest({"b": [1, 2], "a": "x", "c": {"d": True}}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
