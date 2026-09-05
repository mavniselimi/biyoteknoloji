# -*- coding: utf-8 -*-
"""The published snapshot manifest schema, and the validator that applies it.

A schema nobody validates against is documentation, not a contract. These tests
check three things: that the checked-in schema is what the generator produces,
that a real manifest satisfies it, and that the validator refuses any keyword it
has not implemented - because a validator that silently ignored one would report
a manifest as valid while quietly not checking the constraint its author wrote.
"""

from __future__ import annotations

import io
import os
import sys
import unittest

from pgx.application.snapshot_schema import (
    SNAPSHOT_MANIFEST_SCHEMA_PATH,
    SchemaSupportError,
    load_snapshot_manifest_schema,
    validate_against_schema,
    validate_snapshot_manifest,
)
from pgx.ingestion.snapshots import (
    SNAPSHOT_MANIFEST_VERSION, ArtifactKind, SnapshotKind, SnapshotState,
)

from tests.unit.snapshots._support import SnapshotTestCase

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


class TestTheSchemaIsCurrent(unittest.TestCase):

    def test_the_checked_in_file_matches_the_generator(self):
        scripts = os.path.join(REPO_ROOT, "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from render_snapshot_manifest_schema import render
        with io.open(SNAPSHOT_MANIFEST_SCHEMA_PATH, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), render())

    def test_every_vocabulary_is_enumerated_completely(self):
        schema = load_snapshot_manifest_schema()
        cases = (
            (schema["properties"]["snapshot_kind"], SnapshotKind),
            (schema["properties"]["snapshot_state"], SnapshotState),
            (schema["$defs"]["artifact"]["properties"]["artifact_kind"]
             if "artifact" in schema.get("$defs", {})
             else schema["properties"]["artifacts"]["items"]["properties"][
                 "artifact_kind"], ArtifactKind),
        )
        for node, vocabulary in cases:
            with self.subTest(vocabulary=vocabulary.__name__):
                self.assertEqual(set(node["enum"]),
                                 {member.value for member in vocabulary})

    def test_the_schema_version_constant_agrees(self):
        schema = load_snapshot_manifest_schema()
        self.assertEqual(
            schema["properties"]["snapshot_manifest_version"]["const"],
            SNAPSHOT_MANIFEST_VERSION)

    def test_unknown_manifest_keys_are_refused_by_the_schema(self):
        self.assertFalse(load_snapshot_manifest_schema()["additionalProperties"])

    def test_unknown_artifact_keys_are_refused_by_the_schema(self):
        schema = load_snapshot_manifest_schema()
        self.assertFalse(
            schema["properties"]["artifacts"]["items"]["additionalProperties"])


class TestARealManifestValidates(SnapshotTestCase):

    def test_an_acquisition_manifest_validates(self):
        result = self.sealed()
        self.assertEqual(validate_snapshot_manifest(result.manifest.payload()), ())

    def test_a_legacy_manifest_validates(self):
        from pgx.ingestion.snapshots import SnapshotBuildRequest
        source = os.path.join(self.root, "legacy")
        os.makedirs(source)
        with io.open(os.path.join(source, "a.json"), "wb") as handle:
            handle.write(b"{}")
        built = self.manager.build(SnapshotBuildRequest(
            dataset_public_id="PGX-DATA-20260830-900", source_key="legacy",
            snapshot_kind=SnapshotKind.LEGACY_IMPORT, legacy_source_dir=source,
            limitations=("fixture: synthetic",)))
        self.assertTrue(built.sealed)
        self.assertEqual(validate_snapshot_manifest(built.manifest.payload()), ())


class TestTheValidatorRefusesBadDocuments(unittest.TestCase):

    def setUp(self):
        self.schema = load_snapshot_manifest_schema()

    def _payload(self):
        return {
            "snapshot_manifest_version": SNAPSHOT_MANIFEST_VERSION,
            "dataset_public_id": "PGX-DATA-20260830-001",
            "source_key": "s",
            "snapshot_kind": "ACQUISITION",
            "snapshot_state": "SEALED",
            "snapshot_content_hash": "sha256:" + "0" * 64,
            "manifest_hash": "sha256:" + "1" * 64,
            "created_at": "2026-08-30T12:00:00Z",
            "artifact_count": 0,
            "total_byte_count": 0,
            "artifacts": [],
            "complete": True,
            "publication_eligible": False,
            "scope_note": "raw bytes",
        }

    def test_a_minimal_valid_document_passes(self):
        self.assertEqual(validate_snapshot_manifest(self._payload(),
                                                    self.schema), ())

    def test_a_missing_required_field_is_reported(self):
        payload = self._payload()
        del payload["manifest_hash"]
        problems = validate_snapshot_manifest(payload, self.schema)
        self.assertTrue(any("manifest_hash" in problem for problem in problems))

    def test_an_unknown_field_is_reported(self):
        payload = self._payload()
        payload["surprise"] = 1
        problems = validate_snapshot_manifest(payload, self.schema)
        self.assertTrue(any("surprise" in problem for problem in problems))

    def test_a_malformed_dataset_id_is_reported(self):
        payload = self._payload()
        payload["dataset_public_id"] = "DATASET-1"
        self.assertTrue(validate_snapshot_manifest(payload, self.schema))

    def test_a_malformed_digest_is_reported(self):
        payload = self._payload()
        payload["manifest_hash"] = "md5:abc"
        self.assertTrue(validate_snapshot_manifest(payload, self.schema))

    def test_a_naive_timestamp_is_reported(self):
        payload = self._payload()
        payload["created_at"] = "2026-08-30T12:00:00"
        self.assertTrue(validate_snapshot_manifest(payload, self.schema))

    def test_an_unknown_snapshot_kind_is_reported(self):
        payload = self._payload()
        payload["snapshot_kind"] = "GUESSED"
        self.assertTrue(validate_snapshot_manifest(payload, self.schema))

    def test_an_absolute_artifact_path_is_reported(self):
        payload = self._payload()
        payload["artifacts"] = [{
            "relative_path": "/etc/passwd", "artifact_kind": "RESPONSE_BODY",
            "byte_length": 1, "sha256": "sha256:" + "0" * 64}]
        self.assertTrue(validate_snapshot_manifest(payload, self.schema))

    def test_a_traversing_artifact_path_is_reported(self):
        payload = self._payload()
        payload["artifacts"] = [{
            "relative_path": "responses/../x.json",
            "artifact_kind": "RESPONSE_BODY", "byte_length": 1,
            "sha256": "sha256:" + "0" * 64}]
        self.assertTrue(validate_snapshot_manifest(payload, self.schema))

    def test_a_negative_byte_count_is_reported(self):
        payload = self._payload()
        payload["total_byte_count"] = -1
        self.assertTrue(validate_snapshot_manifest(payload, self.schema))

    def test_every_problem_is_reported_not_only_the_first(self):
        payload = self._payload()
        payload["surprise"] = 1
        payload["dataset_public_id"] = "nope"
        self.assertGreaterEqual(
            len(validate_snapshot_manifest(payload, self.schema)), 2)


class TestTheValidatorRefusesUnimplementedKeywords(unittest.TestCase):
    """A published constraint that is not checked is a false assurance."""

    def test_an_unimplemented_keyword_raises(self):
        with self.assertRaises(SchemaSupportError):
            validate_against_schema({}, {"type": "object",
                                         "dependentRequired": {"a": ["b"]}})

    def test_the_error_names_the_keyword(self):
        """The example is a keyword that is still unimplemented. It used to be
        ``uniqueItems``, which WP-08 implemented so its published schemas could
        actually be checked, and then ``propertyNames``, which WP-10
        implemented for the same reason - an implemented keyword makes a poor
        example of a refused one."""
        with self.assertRaises(SchemaSupportError) as caught:
            validate_against_schema([], {"type": "array", "contains":
                                         {"type": "string"}})
        self.assertIn("contains", str(caught.exception))


class TestTheKeywordsWp10AddedActuallyCheck(unittest.TestCase):
    """WP-10 needed three more, for constraints its schemas could not state.

    ``allOf`` so several conditions can hold at once; ``if``/``then`` so a work
    item's required fields can depend on its state ("a CURATED one names the
    revision that was decided"); ``propertyNames`` so every key of
    ``legacy_values`` can be required to carry its namespace. Each is tested
    for refusing something, because a keyword that parsed but never failed
    would be the false assurance this validator exists to prevent.
    """

    def test_all_of_requires_every_subschema(self):
        schema = {"allOf": [{"type": "object", "required": ["a"]},
                            {"type": "object", "required": ["b"]}]}
        self.assertEqual(validate_against_schema({"a": 1, "b": 2}, schema), ())
        problems = validate_against_schema({"a": 1}, schema)
        self.assertTrue(problems)
        self.assertIn("b", " ".join(problems))

    def test_all_of_reports_every_failing_branch_not_just_the_first(self):
        schema = {"allOf": [{"type": "object", "required": ["a"]},
                            {"type": "object", "required": ["b"]}]}
        self.assertEqual(len(validate_against_schema({}, schema)), 2)

    def test_if_then_applies_only_when_the_condition_matches(self):
        schema = {
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "if": {"properties": {"status": {"const": "CURATED"}},
                   "required": ["status"]},
            "then": {"required": ["revision_id"]},
        }
        self.assertEqual(
            validate_against_schema({"status": "RAW"}, schema), ())
        self.assertTrue(
            validate_against_schema({"status": "CURATED"}, schema))
        self.assertEqual(
            validate_against_schema(
                {"status": "CURATED", "revision_id": "r"}, schema), ())

    def test_a_failing_condition_is_not_itself_reported(self):
        """A value that does not match ``if`` has not done anything wrong; it
        has selected the other branch."""
        schema = {"type": "object",
                  "if": {"required": ["a"]},
                  "then": {"required": ["b"]}}
        self.assertEqual(validate_against_schema({}, schema), ())

    def test_else_is_applied_when_the_condition_fails(self):
        schema = {"type": "object",
                  "if": {"required": ["a"]},
                  "then": {"required": ["b"]},
                  "else": {"required": ["c"]}}
        self.assertTrue(validate_against_schema({}, schema))
        self.assertEqual(validate_against_schema({"c": 1}, schema), ())

    def test_property_names_refuses_a_key_that_breaks_the_pattern(self):
        schema = {"type": "object", "propertyNames": {"pattern": "^legacy\\."}}
        self.assertEqual(
            validate_against_schema({"legacy.risk": "high"}, schema), ())
        problems = validate_against_schema({"demo_risk_level": "high"}, schema)
        self.assertTrue(problems)
        self.assertIn("demo_risk_level", " ".join(problems))

    def test_property_names_reports_every_offending_key(self):
        schema = {"type": "object", "propertyNames": {"pattern": "^legacy\\."}}
        problems = validate_against_schema({"a": 1, "b": 2}, schema)
        self.assertEqual(len(problems), 2)

    def test_a_schema_valued_additional_properties_now_checks_values(self):
        """It used to be accepted and ignored. A schema saying 'every source
        version is a non-empty string' checked nothing, which is the false
        assurance this validator exists to prevent."""
        schema = {"type": "object",
                  "additionalProperties": {"type": "string", "minLength": 1}}
        self.assertEqual(validate_against_schema({"a": "x"}, schema), ())
        self.assertTrue(validate_against_schema({"a": ""}, schema))
        self.assertTrue(validate_against_schema({"a": 1}, schema))

    def test_a_listed_property_is_not_re_checked_as_an_additional_one(self):
        schema = {"type": "object",
                  "properties": {"a": {"type": "integer"}},
                  "additionalProperties": {"type": "string"}}
        self.assertEqual(validate_against_schema({"a": 1, "b": "x"}, schema),
                         ())

    def test_an_additional_properties_that_is_neither_raises(self):
        with self.assertRaises(SchemaSupportError):
            validate_against_schema({"a": 1},
                                    {"type": "object",
                                     "additionalProperties": ["nonsense"]})


class TestTheKeywordsWp08AddedActuallyCheck(unittest.TestCase):
    """Implementing a keyword only helps if it refuses something.

    Each of these was added so a WP-08 schema could state a constraint in the
    schema rather than only in its description. A keyword that parsed but never
    failed would be the same false assurance the validator exists to prevent.
    """

    def test_min_items_refuses_a_short_array(self):
        self.assertTrue(validate_against_schema(
            [], {"type": "array", "minItems": 1}))
        self.assertEqual(validate_against_schema(
            [1], {"type": "array", "minItems": 1}), ())

    def test_max_items_refuses_a_long_array(self):
        self.assertTrue(validate_against_schema(
            [1, 2], {"type": "array", "maxItems": 1}))

    def test_unique_items_refuses_a_repeat_including_an_unhashable_one(self):
        self.assertTrue(validate_against_schema(
            ["a", "a"], {"type": "array", "uniqueItems": True}))
        self.assertTrue(validate_against_schema(
            [{"a": 1}, {"a": 1}], {"type": "array", "uniqueItems": True}))
        self.assertEqual(validate_against_schema(
            [{"a": 1}, {"a": 2}], {"type": "array", "uniqueItems": True}), ())

    def test_not_refuses_the_forbidden_shape(self):
        schema = {"type": "object", "not": {"required": ["risk_level"]}}
        self.assertTrue(validate_against_schema({"risk_level": "high"}, schema))
        self.assertEqual(validate_against_schema({"other": 1}, schema), ())

    def test_maximum_refuses_a_large_number(self):
        self.assertTrue(validate_against_schema(
            5, {"type": "integer", "maximum": 4}))

    def test_min_properties_refuses_an_empty_object(self):
        self.assertTrue(validate_against_schema(
            {}, {"type": "object", "minProperties": 1}))

    def test_a_remote_reference_is_refused(self):
        with self.assertRaises(SchemaSupportError):
            validate_against_schema({}, {"$ref": "https://example.invalid/s.json"})

    def test_the_published_schema_uses_only_implemented_keywords(self):
        """If this fails, the schema grew a constraint nothing enforces."""
        self.assertEqual(
            validate_snapshot_manifest({
                "snapshot_manifest_version": SNAPSHOT_MANIFEST_VERSION,
                "dataset_public_id": "PGX-DATA-20260830-001",
                "source_key": "s", "snapshot_kind": "ACQUISITION",
                "snapshot_state": "SEALED",
                "snapshot_content_hash": "sha256:" + "0" * 64,
                "manifest_hash": "sha256:" + "1" * 64,
                "created_at": "2026-08-30T12:00:00Z", "artifact_count": 0,
                "total_byte_count": 0, "artifacts": [], "complete": True,
                "publication_eligible": False, "scope_note": "raw bytes",
            }), ())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
