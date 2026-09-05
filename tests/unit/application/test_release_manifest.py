# -*- coding: utf-8 -*-
"""The release manifest: determinism, validation, and the schema (WP-03).

The manifest's digest is what makes a release re-verifiable. Three properties
carry that weight, and each is tested here rather than assumed: the same
records always produce the same bytes, no wall-clock value leaks into the
payload, and key insertion order is irrelevant.

Standard library only. The schema file is read and compared against the
validator, so the two cannot drift apart silently.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import os
import unittest

from pgx.application.release_schema import (
    RELEASE_MANIFEST_SCHEMA_PATH, load_release_manifest_schema,
)
from pgx.domain.hashing import sha256_digest
from pgx.domain.identifiers import ReleasePublicId
from pgx.domain.immutable import FrozenMapping, is_frozen_json
from pgx.domain.release_manifest import (
    RELEASE_MANIFEST_SCHEMA_VERSION, ManifestValidationError,
    build_release_manifest, manifest_digest, validate_release_manifest,
    verify_release_manifest,
)

from tests.unit.application._scenario import Scenario

FIXTURE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "fixtures", "release-manifests")


def _manifest(scenario: Scenario):
    return build_release_manifest(
        release_public_id=ReleasePublicId("PGX-REL-20260829-001"),
        software=scenario.software, dataset=scenario.dataset,
        ruleset=scenario.ruleset)


class TestManifestIsDeterministic(unittest.TestCase):

    def setUp(self):
        self.scenario = Scenario()

    def test_the_same_records_produce_the_same_payload(self):
        self.assertEqual(_manifest(self.scenario), _manifest(self.scenario))

    def test_the_same_records_produce_the_same_digest(self):
        self.assertEqual(manifest_digest(_manifest(self.scenario)),
                         manifest_digest(_manifest(self.scenario)))

    def test_key_insertion_order_does_not_change_the_digest(self):
        payload = dict(_manifest(self.scenario))
        reordered = {key: payload[key] for key in reversed(list(payload))}
        self.assertEqual(sha256_digest(payload), sha256_digest(reordered))

    def test_no_wall_clock_value_appears_in_the_payload(self):
        """Nothing here may depend on when the manifest was built."""
        text = json.dumps(
            json.loads(json.dumps(_manifest(self.scenario), default=str)))
        today = _dt.datetime.now(_dt.timezone.utc)
        for fragment in (today.strftime("%H:%M"), today.strftime("%Y-%m-%dT")):
            self.assertNotIn(fragment, text)

    def test_the_builder_never_reads_the_clock(self):
        import ast
        import inspect

        from pgx.domain import release_manifest

        tree = ast.parse(inspect.getsource(release_manifest))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, ("now", "utcnow", "today", "time"),
                                 "the manifest module must not read the clock")

    def test_membership_order_is_the_rulesets_order(self):
        manifest = _manifest(self.scenario)
        self.assertEqual(list(manifest["ruleset"]["rule_ids"]),
                         [rule_id.to_json() for rule_id in self.scenario.ruleset.rule_ids])

    def test_a_different_membership_gives_a_different_digest(self):
        import dataclasses

        from pgx.domain.identifiers import ComputableRuleId

        other = dataclasses.replace(
            self.scenario.ruleset,
            rule_ids=self.scenario.ruleset.rule_ids + (ComputableRuleId.new(),))
        first = manifest_digest(_manifest(self.scenario))
        second = manifest_digest(build_release_manifest(
            release_public_id=ReleasePublicId("PGX-REL-20260829-001"),
            software=self.scenario.software, dataset=self.scenario.dataset,
            ruleset=other))
        self.assertNotEqual(first, second)

    def test_the_payload_is_deeply_immutable(self):
        manifest = _manifest(self.scenario)
        self.assertIsInstance(manifest, FrozenMapping)
        self.assertTrue(is_frozen_json(manifest))
        with self.assertRaises(Exception):
            manifest["software"]["version"] = "tampered"


class TestManifestValidation(unittest.TestCase):

    def setUp(self):
        self.scenario = Scenario()
        self.manifest = _manifest(self.scenario)

    def _broken(self, **changes):
        from pgx.domain.release_manifest import as_plain_json

        payload = as_plain_json(self.manifest)
        for path, value in changes.items():
            parts = path.split(".")
            target = payload
            for part in parts[:-1]:
                target = target[part]
            if value is None:
                target.pop(parts[-1], None)
            else:
                target[parts[-1]] = value
        return payload

    def test_a_built_manifest_is_valid(self):
        self.assertEqual(validate_release_manifest(self.manifest), ())

    def test_verification_accepts_the_matching_digest(self):
        verify_release_manifest(self.manifest, manifest_digest(self.manifest))

    def test_a_wrong_schema_version_is_rejected(self):
        problems = validate_release_manifest(
            self._broken(schema_version="pgx-release-manifest/99"))
        self.assertTrue(any("schema_version" in problem for problem in problems))

    def test_a_missing_section_is_rejected(self):
        for section in ("release", "software", "dataset", "ruleset"):
            with self.subTest(section=section):
                problems = validate_release_manifest(self._broken(**{section: None}))
                self.assertTrue(problems)

    def test_an_unknown_top_level_key_is_rejected(self):
        problems = validate_release_manifest(self._broken(surprise="value"))
        self.assertTrue(any("unknown top-level key" in problem
                            for problem in problems))

    def test_a_malformed_digest_is_rejected(self):
        problems = validate_release_manifest(
            self._broken(**{"dataset.manifest_hash": "not-a-digest"}))
        self.assertTrue(any("dataset.manifest_hash" in problem
                            for problem in problems))

    def test_a_malformed_public_id_is_rejected(self):
        problems = validate_release_manifest(
            self._broken(**{"release.public_id": "PGX-REL-BAD"}))
        self.assertTrue(problems)

    def test_a_member_count_that_disagrees_is_rejected(self):
        problems = validate_release_manifest(
            self._broken(**{"ruleset.member_count": 99}))
        self.assertTrue(any("member_count" in problem for problem in problems))

    def test_duplicate_rule_ids_are_rejected(self):
        rule_id = list(self.manifest["ruleset"]["rule_ids"])[0]
        problems = validate_release_manifest(
            self._broken(**{"ruleset.rule_ids": [rule_id, rule_id],
                            "ruleset.member_count": 2}))
        self.assertTrue(any("duplicate" in problem for problem in problems))

    def test_a_non_object_is_rejected(self):
        for payload in ([], "text", 7, None):
            with self.subTest(payload=payload):
                self.assertTrue(validate_release_manifest(payload))

    def test_every_problem_is_reported_not_just_the_first(self):
        problems = validate_release_manifest(
            self._broken(schema_version="wrong",
                         **{"dataset.manifest_hash": "bad",
                            "ruleset.member_count": 42}))
        self.assertGreaterEqual(len(problems), 3)

    def test_verification_rejects_a_mismatched_digest(self):
        with self.assertRaises(ManifestValidationError) as caught:
            verify_release_manifest(self.manifest, sha256_digest({"other": 1}))
        self.assertIn("hash mismatch", str(caught.exception))

    def test_verification_rejects_a_malformed_expected_digest(self):
        with self.assertRaises(ManifestValidationError):
            verify_release_manifest(self.manifest, "not-a-digest")

    def test_verification_rejects_an_invalid_manifest(self):
        with self.assertRaises(ManifestValidationError):
            verify_release_manifest(self._broken(schema_version="wrong"))


class TestTheJsonSchemaMatchesTheValidator(unittest.TestCase):
    """The schema file is the published contract; the validator enforces it.

    They are written separately, so they are compared here. A schema that
    documents a field nothing checks is worse than no schema at all.
    """

    @classmethod
    def setUpClass(cls):
        cls.schema = load_release_manifest_schema()

    def test_the_schema_file_exists_and_parses(self):
        self.assertTrue(os.path.isfile(RELEASE_MANIFEST_SCHEMA_PATH))
        self.assertEqual(self.schema["type"], "object")

    def test_the_schema_version_constant_matches(self):
        self.assertEqual(
            self.schema["properties"]["schema_version"]["const"],
            RELEASE_MANIFEST_SCHEMA_VERSION)

    def test_the_required_keys_match_the_validator(self):
        scenario = Scenario()
        manifest = _manifest(scenario)
        self.assertEqual(set(self.schema["required"]), set(manifest))

    def test_the_schema_forbids_extra_top_level_keys(self):
        self.assertFalse(self.schema["additionalProperties"])

    def test_every_section_forbids_extra_keys(self):
        for section in ("release", "software", "dataset", "ruleset"):
            with self.subTest(section=section):
                self.assertFalse(
                    self.schema["properties"][section]["additionalProperties"])

    def test_the_built_manifest_carries_every_declared_property(self):
        manifest = _manifest(Scenario())
        for section in ("release", "software", "dataset", "ruleset"):
            declared = set(self.schema["properties"][section]["properties"])
            self.assertEqual(set(manifest[section]), declared,
                             "%s does not match the schema" % section)

    def test_the_digest_pattern_matches_the_domains_spelling(self):
        self.assertEqual(self.schema["$defs"]["digest"]["pattern"],
                         r"^sha256:[0-9a-f]{64}$")


class TestManifestFixtures(unittest.TestCase):
    """Committed valid and invalid examples, checked against the validator."""

    def _load(self, name):
        with io.open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as handle:
            return json.load(handle)

    def test_the_valid_fixture_validates(self):
        self.assertEqual(validate_release_manifest(self._load("valid.json")), ())

    def test_the_valid_fixture_matches_its_recorded_digest(self):
        document = self._load("valid.json")
        expected = self._load("valid.digest.json")["manifest_hash"]
        verify_release_manifest(document, expected)

    def test_each_invalid_fixture_is_rejected(self):
        for name in sorted(os.listdir(FIXTURE_DIR)):
            if not name.startswith("invalid-"):
                continue
            with self.subTest(fixture=name):
                self.assertTrue(validate_release_manifest(self._load(name)),
                                "%s should not validate" % name)

    def test_there_is_at_least_one_invalid_fixture_per_failure_family(self):
        names = set(os.listdir(FIXTURE_DIR))
        for expected in ("invalid-schema-version.json",
                         "invalid-missing-section.json",
                         "invalid-bad-digest.json",
                         "invalid-member-count-mismatch.json",
                         "invalid-unknown-key.json"):
            self.assertIn(expected, names)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
