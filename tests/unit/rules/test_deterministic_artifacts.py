# -*- coding: utf-8 -*-
"""Determinism and immutability of the frozen artifact (WP-11, section F).

A ruleset's identity is its content, not the circumstances of its build. Two
people building the same set on different machines, in a different order, at
different times, must produce byte-identical rules and manifest and the same
semantic hash - otherwise "is this the ruleset that was approved?" has no
answer.

The build log is the deliberate exception: it records who built it and when,
and it is excluded from every hash. Keeping the operational facts *somewhere*
matters; letting them into the identity would make the identity unusable.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import os
import shutil
import tempfile
import unittest

from pgx.rules.builder import compose_artifact
from pgx.rules.errors import ArtifactIntegrityError, FrozenArtifactExistsError
from pgx.rules.identifiers import RulesetBuildId
from pgx.rules.serialization import (ARTIFACT_FILES, CHECKSUM_FILE,
                                     canonical_bytes, publish_atomically,
                                     verify_checksums)
from tests.fixtures.wp11.synthetic import (synthetic_build_inputs,
                                           synthetic_condition, synthetic_rule)

EARLY = _dt.datetime(2099, 1, 1, 0, 0, tzinfo=_dt.timezone.utc)
LATE = _dt.datetime(2099, 6, 30, 23, 59, 59, tzinfo=_dt.timezone.utc)


def _rules(count=3):
    genes = ("GENE:TESTGENE1", "GENE:TESTGENE2", "GENE:TESTGENE3")
    return tuple(synthetic_rule(condition=synthetic_condition(gene=gene))
                 for gene in genes[:count])


def _compose(definitions, *, built_by="TEST-rule-builder-1", started=EARLY,
             completed=EARLY, build="dddddddd-0000-4000-8000-000000000001"):
    return compose_artifact(
        synthetic_build_inputs(definitions), built_by=built_by,
        started_at=started, completed_at=completed,
        build_id=RulesetBuildId.parse(build),
        artifact_relative_path="PGX-RULESET-29991231-001")


class TestTheSameSetProducesTheSameBytes(unittest.TestCase):

    def test_input_order_does_not_change_the_artifact(self):
        definitions = _rules()
        first_manifest, first_files, first_hash = _compose(definitions)
        _second_manifest, second_files, second_hash = _compose(
            tuple(reversed(definitions)))
        self.assertEqual(first_hash, second_hash)
        for name in ("manifest.json", "rules.ndjson", "approval-list.json"):
            with self.subTest(file=name):
                self.assertEqual(first_files[name], second_files[name])

    def test_the_builder_and_the_clock_do_not_change_the_artifact(self):
        definitions = _rules()
        _first_manifest, first_files, first_hash = _compose(definitions)
        _second_manifest, second_files, second_hash = _compose(
            definitions, built_by="TEST-rule-validator-1", started=LATE,
            completed=LATE, build="dddddddd-0000-4000-8000-000000000002")
        self.assertEqual(first_hash, second_hash)
        for name in ("manifest.json", "rules.ndjson", "approval-list.json"):
            with self.subTest(file=name):
                self.assertEqual(first_files[name], second_files[name])

    def test_the_build_log_is_the_one_file_that_does_differ(self):
        definitions = _rules()
        _m1, first_files, _h1 = _compose(definitions)
        _m2, second_files, _h2 = _compose(
            definitions, built_by="TEST-rule-validator-1", started=LATE,
            completed=LATE, build="dddddddd-0000-4000-8000-000000000002")
        self.assertNotEqual(first_files["build-log.json"],
                            second_files["build-log.json"])

    def test_nothing_in_the_build_log_reaches_the_semantic_hash(self):
        _manifest, files, digest = _compose(_rules())
        log = json.loads(files["build-log.json"].decode("utf-8"))
        for operational in ("built_by", "started_at", "completed_at",
                            "build_id"):
            with self.subTest(field=operational):
                self.assertNotIn(str(log[operational]), digest)
        manifest = json.loads(files["manifest.json"].decode("utf-8"))
        for operational in ("built_by", "started_at", "completed_at",
                            "build_id", "hostname", "duration",
                            "artifact_absolute_path"):
            with self.subTest(field=operational):
                self.assertNotIn(operational, manifest)

    def test_no_absolute_path_appears_anywhere_in_the_artifact(self):
        """A path that depended on where the build ran would make the same
        ruleset different on two machines."""
        _manifest, files, _digest = _compose(_rules())
        for name, payload in files.items():
            text = payload.decode("utf-8")
            with self.subTest(file=name):
                self.assertNotIn(tempfile.gettempdir(), text)
                self.assertNotIn(os.path.sep + "home" + os.path.sep, text)


class TestCanonicalSerialization(unittest.TestCase):

    def test_dictionary_insertion_order_does_not_change_the_bytes(self):
        self.assertEqual(canonical_bytes({"b": 1, "a": 2}),
                         canonical_bytes({"a": 2, "b": 1}))

    def test_the_encoding_is_stable_and_compact(self):
        payload = canonical_bytes({"a": 1, "b": "x"})
        self.assertEqual(payload, b'{\n  "a":1,\n  "b":"x"\n}\n')

    def test_non_ascii_survives_a_round_trip(self):
        payload = canonical_bytes({"note": "protéin"})
        self.assertEqual(json.loads(payload.decode("utf-8"))["note"],
                         "protéin")


class TestTheArtifactCarriesItsOwnChecksums(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.destination = os.path.join(self.tmp, "artifact")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        _manifest, self.files, self.digest = _compose(_rules())
        publish_atomically(self.destination, self.files)

    def test_the_expected_files_are_written(self):
        self.assertEqual(sorted(os.listdir(self.destination)),
                         sorted(ARTIFACT_FILES + (CHECKSUM_FILE,)))

    def test_a_clean_artifact_verifies(self):
        """On success the digest of every file is returned, so a caller can
        record what it verified rather than only that it did."""
        verified = verify_checksums(self.destination)
        self.assertEqual(sorted(verified), sorted(ARTIFACT_FILES))

    def test_a_changed_byte_is_detected(self):
        """Verification fails closed: it raises rather than returning a
        report a caller could forget to read."""
        path = os.path.join(self.destination, "rules.ndjson")
        with io.open(path, "a", encoding="utf-8") as handle:
            handle.write("\n")
        with self.assertRaises(ArtifactIntegrityError) as caught:
            verify_checksums(self.destination)
        self.assertEqual(caught.exception.code, "ARTIFACT_CHECKSUM_MISMATCH")

    def test_a_missing_file_is_detected(self):
        os.remove(os.path.join(self.destination, "approval-list.json"))
        with self.assertRaises(ArtifactIntegrityError) as caught:
            verify_checksums(self.destination)
        self.assertEqual(caught.exception.code, "ARTIFACT_MEMBER_MISSING")

    def test_an_unlisted_extra_file_is_detected(self):
        """Content nobody checksummed is content nobody verified."""
        with io.open(os.path.join(self.destination, "extra.json"), "w",
                     encoding="utf-8") as handle:
            handle.write("{}")
        with self.assertRaises(ArtifactIntegrityError) as caught:
            verify_checksums(self.destination)
        self.assertEqual(caught.exception.code, "ARTIFACT_UNEXPECTED_FILE")

    def test_a_missing_checksum_file_is_detected(self):
        os.remove(os.path.join(self.destination, CHECKSUM_FILE))
        with self.assertRaises(ArtifactIntegrityError) as caught:
            verify_checksums(self.destination)
        self.assertEqual(caught.exception.code,
                         "ARTIFACT_CHECKSUM_FILE_MISSING")

    def test_the_checksum_file_is_sha256sum_compatible(self):
        with io.open(os.path.join(self.destination, CHECKSUM_FILE),
                     encoding="utf-8") as handle:
            lines = [line.rstrip("\n") for line in handle if line.strip()]
        self.assertEqual(len(lines), len(ARTIFACT_FILES))
        for line in lines:
            digest, _sep, name = line.partition("  ")
            with self.subTest(line=line):
                self.assertEqual(len(digest), 64)
                self.assertIn(name, ARTIFACT_FILES)


class TestPublicationIsAtomicAndRefusesToOverwrite(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.destination = os.path.join(self.tmp, "artifact")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_publishing_over_an_existing_artifact_is_refused(self):
        _manifest, files, _digest = _compose(_rules())
        publish_atomically(self.destination, files)
        with self.assertRaises(FrozenArtifactExistsError):
            publish_atomically(self.destination, files)

    def test_the_refusal_leaves_the_original_untouched(self):
        _manifest, first_files, _digest = _compose(_rules())
        publish_atomically(self.destination, first_files)
        manifest_path = os.path.join(self.destination, "manifest.json")
        with io.open(manifest_path, "rb") as handle:
            original = handle.read()
        _manifest, second_files, _digest = _compose(_rules(2))
        with self.assertRaises(FrozenArtifactExistsError):
            publish_atomically(self.destination, second_files)
        with io.open(manifest_path, "rb") as handle:
            self.assertEqual(handle.read(), original)

    def test_no_staging_directory_is_left_behind(self):
        _manifest, files, _digest = _compose(_rules())
        publish_atomically(self.destination, files)
        siblings = os.listdir(self.tmp)
        self.assertEqual(siblings, ["artifact"])


class TestTheManifestDescribesMembershipNotCoverage(unittest.TestCase):

    def test_the_axis_list_is_named_structural_and_carries_a_warning(self):
        manifest, files, _digest = _compose(_rules())
        payload = json.loads(files["manifest.json"].decode("utf-8"))
        self.assertIn("structural_axes", payload)
        self.assertIn("not a claim of clinical coverage", payload["note"])

    def test_the_manifest_carries_no_coverage_or_completeness_field(self):
        _manifest, files, _digest = _compose(_rules())
        payload = json.loads(files["manifest.json"].decode("utf-8"))
        for absent in ("coverage", "coverage_percent", "completeness",
                       "covered_genes", "covered_drugs", "quality_score",
                       "confidence"):
            with self.subTest(field=absent):
                self.assertNotIn(absent, payload)

    def test_every_member_is_pinned_by_content_hash(self):
        definitions = _rules()
        _manifest, files, _digest = _compose(definitions)
        payload = json.loads(files["manifest.json"].decode("utf-8"))
        pinned = {member["rule_id"]: member["content_hash"]
                  for member in payload["members"]}
        for definition in definitions:
            with self.subTest(rule=definition.rule_id.to_json()):
                self.assertEqual(pinned[definition.rule_id.to_json()],
                                 definition.content_hash())

    def test_changing_one_member_changes_the_ruleset_hash(self):
        first = _rules()
        _m, _f, first_hash = _compose(first)
        _m, _f, second_hash = _compose(first[:2])
        self.assertNotEqual(first_hash, second_hash)


class TestTamperingIsDetectedNotRepaired(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.destination = os.path.join(self.tmp, "artifact")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        _manifest, files, self.digest = _compose(_rules())
        publish_atomically(self.destination, files)

    def test_an_edited_rule_fails_verification(self):
        path = os.path.join(self.destination, "rules.ndjson")
        with io.open(path, encoding="utf-8") as handle:
            text = handle.read()
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(text.replace('"MEDIUM"', '"HIGH"'))
        with self.assertRaises(ArtifactIntegrityError) as caught:
            verify_checksums(self.destination)
        self.assertEqual(caught.exception.code, "ARTIFACT_CHECKSUM_MISMATCH")

    def test_loading_a_tampered_artifact_raises_rather_than_repairing(self):
        from pgx.rules.registry import load_frozen_ruleset
        path = os.path.join(self.destination, "manifest.json")
        with io.open(path, encoding="utf-8") as handle:
            text = handle.read()
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(text.replace('"member_count":3', '"member_count":2'))
        with self.assertRaises(ArtifactIntegrityError):
            load_frozen_ruleset(self.destination)


if __name__ == "__main__":
    unittest.main()
