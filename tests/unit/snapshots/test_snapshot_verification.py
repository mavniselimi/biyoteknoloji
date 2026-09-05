# -*- coding: utf-8 -*-
"""Verification: does this snapshot still say what it said when it was sealed?

The project cannot guarantee WORM storage - a directory's owner can always
chmod it back and edit it - so the guarantee it *does* offer is detection. Every
test here damages a snapshot in one specific way and checks that verification
notices, names the file, and does not repair anything.

Every snapshot damaged here is a temporary one the test built itself. The
checked-in legacy snapshot is never touched; ``test_legacy_snapshot.py``
verifies it read-only.
"""

from __future__ import annotations

import io
import json
import os
import unittest

from pgx.application.snapshot_schema import validate_snapshot_manifest
from pgx.ingestion.snapshots import SnapshotIssueCode

from tests.unit.snapshots._support import SnapshotTestCase


class VerificationTestCase(SnapshotTestCase):

    def setUp(self):
        super().setUp()
        self.result = self.sealed()
        self.path = self.result.snapshot_path
        self.artifact = self.result.manifest.artifacts[0].relative_path

    def verify(self, schema: bool = False):
        return self.manager.verify_path(
            self.path,
            schema_validator=validate_snapshot_manifest if schema else None)

    def rewrite_manifest(self, **changes):
        self.unlock(self.path)
        target = os.path.join(self.path, "manifest.json")
        with io.open(target, encoding="utf-8") as handle:
            payload = json.loads(handle.read())
        payload.update(changes)
        with io.open(target, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2) + "\n")


class TestAnIntactSnapshotVerifies(VerificationTestCase):

    def test_it_verifies(self):
        result = self.verify()
        self.assertTrue(result.ok, [i.render() for i in result.issues])

    def test_it_verifies_against_the_published_schema_too(self):
        self.assertTrue(self.verify(schema=True).ok)

    def test_it_reports_how_many_artifacts_it_checked(self):
        self.assertEqual(self.verify().checked_artifacts,
                         self.result.manifest.artifact_count + 1)

    def test_verification_changes_nothing(self):
        before = sorted(os.listdir(os.path.join(self.path, "responses")))
        self.verify()
        self.assertEqual(sorted(os.listdir(os.path.join(self.path, "responses"))),
                         before)


class TestCorruption(VerificationTestCase):

    def test_one_changed_byte_is_detected(self):
        self.flip_one_byte(self.path, self.artifact)
        result = self.verify()
        self.assertFalse(result.ok)
        self.assertIn(SnapshotIssueCode.ARTIFACT_HASH_MISMATCH.value,
                      result.codes)
        self.assertIn(self.artifact,
                      {issue.subject for issue in result.issues})

    def test_a_truncated_artifact_is_detected_as_both_hash_and_length(self):
        self.overwrite(self.path, self.artifact, b"{}")
        result = self.verify()
        self.assertIn(SnapshotIssueCode.ARTIFACT_HASH_MISMATCH.value,
                      result.codes)
        self.assertIn(SnapshotIssueCode.ARTIFACT_LENGTH_MISMATCH.value,
                      result.codes)

    def test_a_removed_artifact_is_detected(self):
        self.remove(self.path, self.artifact)
        result = self.verify()
        self.assertIn(SnapshotIssueCode.ARTIFACT_MISSING.value, result.codes)

    def test_a_removed_request_log_is_detected(self):
        self.remove(self.path, "requests.ndjson")
        result = self.verify()
        self.assertIn(SnapshotIssueCode.REQUESTS_LOG_MISSING.value, result.codes)

    def test_an_added_file_is_detected(self):
        self.add_file(self.path, "responses/intruder.json", b'{"extra": true}')
        result = self.verify()
        self.assertIn(SnapshotIssueCode.UNEXPECTED_FILE.value, result.codes)

    def test_an_added_file_outside_responses_is_detected(self):
        self.add_file(self.path, "notes.txt", b"hello")
        result = self.verify()
        self.assertIn(SnapshotIssueCode.UNEXPECTED_FILE.value, result.codes)

    def test_a_removed_checksum_file_is_detected(self):
        self.remove(self.path, "checksums.sha256")
        result = self.verify()
        self.assertIn(SnapshotIssueCode.CHECKSUMS_MISSING.value, result.codes)

    def test_a_malformed_checksum_file_is_detected(self):
        self.overwrite(self.path, "checksums.sha256", b"garbage\n")
        result = self.verify()
        self.assertIn(SnapshotIssueCode.CHECKSUMS_MALFORMED.value, result.codes)

    def test_a_checksum_edited_to_match_a_tampered_file_still_fails(self):
        """Editing both the file and its checksum does not survive the manifest."""
        import hashlib
        self.flip_one_byte(self.path, self.artifact)
        target = os.path.join(self.path, *self.artifact.split("/"))
        with io.open(target, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        lines = []
        checksums = os.path.join(self.path, "checksums.sha256")
        with io.open(checksums, encoding="utf-8") as handle:
            for line in handle.read().splitlines():
                if line.endswith(self.artifact):
                    line = "%s  %s" % (digest, self.artifact)
                lines.append(line)
        with io.open(checksums, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        result = self.verify()
        self.assertFalse(result.ok)
        self.assertIn(SnapshotIssueCode.ARTIFACT_HASH_MISMATCH.value,
                      result.codes)

    def test_every_problem_is_reported_not_only_the_first(self):
        self.flip_one_byte(self.path, self.artifact)
        self.add_file(self.path, "responses/intruder.json")
        result = self.verify()
        self.assertGreaterEqual(len(result.issues), 2)


class TestManifestDamage(VerificationTestCase):

    def test_a_missing_manifest_is_detected(self):
        self.remove(self.path, "manifest.json")
        result = self.verify()
        self.assertIn(SnapshotIssueCode.MANIFEST_MISSING.value, result.codes)

    def test_a_corrupt_manifest_is_detected(self):
        self.overwrite(self.path, "manifest.json", b"{not json")
        result = self.verify()
        self.assertIn(SnapshotIssueCode.MANIFEST_CORRUPT.value, result.codes)

    def test_an_unknown_manifest_field_is_refused(self):
        self.rewrite_manifest(surprise=True)
        result = self.verify()
        self.assertIn(SnapshotIssueCode.MANIFEST_UNKNOWN_FIELD.value,
                      result.codes)

    def test_an_unknown_schema_version_is_refused(self):
        self.rewrite_manifest(snapshot_manifest_version="pgx-raw-snapshot/99")
        result = self.verify()
        self.assertIn(SnapshotIssueCode.MANIFEST_SCHEMA_VERSION.value,
                      result.codes)

    def test_an_edited_manifest_field_breaks_the_manifest_hash(self):
        self.rewrite_manifest(complete=False)
        result = self.verify()
        self.assertIn(SnapshotIssueCode.MANIFEST_HASH_MISMATCH.value,
                      result.codes)

    def test_an_edited_artifact_digest_breaks_the_content_hash(self):
        self.unlock(self.path)
        target = os.path.join(self.path, "manifest.json")
        with io.open(target, encoding="utf-8") as handle:
            payload = json.loads(handle.read())
        payload["artifacts"][0]["sha256"] = "sha256:" + "0" * 64
        with io.open(target, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2) + "\n")
        result = self.verify()
        self.assertIn(SnapshotIssueCode.SNAPSHOT_CONTENT_HASH_MISMATCH.value,
                      result.codes)

    def test_a_manifest_naming_an_absolute_path_is_refused(self):
        self.unlock(self.path)
        target = os.path.join(self.path, "manifest.json")
        with io.open(target, encoding="utf-8") as handle:
            payload = json.loads(handle.read())
        payload["artifacts"][0]["relative_path"] = "/etc/passwd"
        with io.open(target, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2) + "\n")
        result = self.verify()
        self.assertFalse(result.ok)
        self.assertIn(SnapshotIssueCode.ABSOLUTE_PATH.value, result.codes)

    def test_a_missing_snapshot_directory_is_detected(self):
        result = self.manager.verify_path(os.path.join(self.root, "nowhere"))
        self.assertIn(SnapshotIssueCode.MANIFEST_MISSING.value, result.codes)


class TestSymlinksInASealedSnapshot(VerificationTestCase):

    def test_a_symlink_replacing_an_artifact_is_detected_not_followed(self):
        self.unlock(self.path)
        target = os.path.join(self.path, *self.artifact.split("/"))
        decoy = os.path.join(self.root, "decoy.json")
        with io.open(decoy, "wb") as handle:
            handle.write(b'{"decoy": true}')
        os.unlink(target)
        os.symlink(decoy, target)
        result = self.verify()
        self.assertFalse(result.ok)
        self.assertIn(SnapshotIssueCode.SYMLINK_PRESENT.value, result.codes)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
