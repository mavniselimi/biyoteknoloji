# -*- coding: utf-8 -*-
"""Paths, links and special files a snapshot must refuse.

A snapshot is bytes this project will still be relying on years later, so the
things it must never contain are the things whose contents can change without
the snapshot changing - a symlink, a hard link - and the things that let a path
name something outside the snapshot at all.

The path rules are checked at the level that matters: a *normalised* path,
compared against the input. Rejecting ``..`` and then normalising would accept
``a/b/../c`` and store it as ``a/c``, so the manifest would describe a path
nobody wrote.
"""

from __future__ import annotations

import io
import os
import unittest

from pgx.ingestion.snapshots import (
    SnapshotBuildRequest,
    SnapshotError,
    SnapshotIssueCode,
    SnapshotKind,
    parse_checksums,
    safe_relative_path,
)

from tests.unit.snapshots import _builders as builders
from tests.unit.snapshots._support import SnapshotTestCase


class TestPathSafety(unittest.TestCase):

    UNSAFE = (
        ("responses/../../etc/passwd", SnapshotIssueCode.PATH_TRAVERSAL),
        ("../escape.json", SnapshotIssueCode.PATH_TRAVERSAL),
        ("a/../b.json", SnapshotIssueCode.PATH_TRAVERSAL),
        ("/etc/passwd", SnapshotIssueCode.ABSOLUTE_PATH),
        ("C:/windows/system32", SnapshotIssueCode.ABSOLUTE_PATH),
        ("responses\\a.json", SnapshotIssueCode.UNSAFE_PATH),
        ("responses//a.json", SnapshotIssueCode.UNSAFE_PATH),
        ("responses/./a.json", SnapshotIssueCode.UNSAFE_PATH),
        ("responses/a.json/", SnapshotIssueCode.UNSAFE_PATH),
        ("responses/a\x00.json", SnapshotIssueCode.UNSAFE_PATH),
        ("responses/a\nb.json", SnapshotIssueCode.UNSAFE_PATH),
        ("", SnapshotIssueCode.UNSAFE_PATH),
        (".", SnapshotIssueCode.UNSAFE_PATH),
        ("..", SnapshotIssueCode.PATH_TRAVERSAL),
    )

    def test_every_unsafe_path_is_refused_under_its_own_code(self):
        for value, code in self.UNSAFE:
            with self.subTest(path=value):
                with self.assertRaises(SnapshotError) as caught:
                    safe_relative_path(value)
                self.assertEqual(caught.exception.code, code)

    def test_safe_paths_are_returned_unchanged(self):
        for value in ("responses/a.json", "manifest.json",
                      "responses/nested/b.csv", "requests.ndjson"):
            with self.subTest(path=value):
                self.assertEqual(safe_relative_path(value), value)

    def test_an_absurdly_deep_path_is_refused(self):
        with self.assertRaises(SnapshotError):
            safe_relative_path("/".join(["a"] * 40))

    def test_an_absurdly_long_segment_is_refused(self):
        with self.assertRaises(SnapshotError):
            safe_relative_path("responses/" + "a" * 500 + ".json")


class TestLinksAndSpecialFilesAreRefused(SnapshotTestCase):

    def _legacy_dir(self) -> str:
        source = os.path.join(self.root, "legacy")
        os.makedirs(source, exist_ok=True)
        with io.open(os.path.join(source, "real.json"), "wb") as handle:
            handle.write(b'{"real": true}')
        return source

    def _import(self, source: str, dataset_id="PGX-DATA-20260830-001"):
        return self.manager.build(SnapshotBuildRequest(
            dataset_public_id=dataset_id, source_key="legacy",
            snapshot_kind=SnapshotKind.LEGACY_IMPORT,
            legacy_source_dir=source,
            limitations=("fixture: synthetic legacy directory",)))

    def test_a_symlinked_file_is_reported_and_never_followed(self):
        source = self._legacy_dir()
        os.symlink(os.path.join(source, "real.json"),
                   os.path.join(source, "link.json"))
        result = self._import(source)
        self.assertFalse(result.sealed)
        self.assertIn(SnapshotIssueCode.SYMLINK_PRESENT,
                      {issue.code for issue in result.issues})

    def test_a_symlink_escaping_the_source_is_not_followed(self):
        source = self._legacy_dir()
        os.symlink("/etc/passwd", os.path.join(source, "escape.json"))
        result = self._import(source)
        self.assertFalse(result.sealed)
        self.assertIn(SnapshotIssueCode.SYMLINK_PRESENT,
                      {issue.code for issue in result.issues})

    def test_a_symlinked_directory_is_reported(self):
        source = self._legacy_dir()
        other = os.path.join(self.root, "elsewhere")
        os.makedirs(other)
        os.symlink(other, os.path.join(source, "sub"))
        result = self._import(source)
        self.assertFalse(result.sealed)
        self.assertIn(SnapshotIssueCode.SYMLINK_PRESENT,
                      {issue.code for issue in result.issues})

    def test_a_fifo_is_reported_and_never_read(self):
        source = self._legacy_dir()
        try:
            os.mkfifo(os.path.join(source, "pipe"))
        except (AttributeError, OSError):  # pragma: no cover - platform
            self.skipTest("this platform cannot create a FIFO")
        result = self._import(source)
        self.assertFalse(result.sealed)
        self.assertIn(SnapshotIssueCode.SPECIAL_FILE_PRESENT,
                      {issue.code for issue in result.issues})

    def test_the_import_copies_and_never_hard_links(self):
        """A hard link would let the original's owner rewrite the snapshot."""
        source = self._legacy_dir()
        result = self._import(source)
        self.assertTrue(result.sealed)
        for descriptor in result.manifest.artifacts:
            path = os.path.join(result.snapshot_path,
                                *descriptor.relative_path.split("/"))
            with self.subTest(artifact=descriptor.relative_path):
                self.assertEqual(os.stat(path).st_nlink, 1)

    def test_a_hard_link_inside_a_sealed_snapshot_fails_verification(self):
        source = self._legacy_dir()
        result = self._import(source)
        self.unlock(result.snapshot_path)
        original = os.path.join(result.snapshot_path, "responses", "real.json")
        try:
            os.link(original, os.path.join(self.root, "outside.json"))
        except OSError:  # pragma: no cover - platform
            self.skipTest("this platform cannot create a hard link")
        verification = self.manager.verify_path(result.snapshot_path)
        self.assertFalse(verification.ok)
        self.assertIn(SnapshotIssueCode.HARD_LINK_PRESENT.value,
                      verification.codes)

    def test_the_legacy_source_directory_is_never_modified(self):
        source = self._legacy_dir()
        before = _digests(source)
        self._import(source)
        self.assertEqual(before, _digests(source))

    def test_a_missing_legacy_directory_is_refused(self):
        result = self._import(os.path.join(self.root, "no-such-dir"))
        self.assertFalse(result.sealed)
        self.assertIn(SnapshotIssueCode.LEGACY_SOURCE_MISSING,
                      {issue.code for issue in result.issues})

    def test_an_empty_legacy_directory_is_refused(self):
        source = os.path.join(self.root, "empty")
        os.makedirs(source)
        result = self._import(source)
        self.assertFalse(result.sealed)
        self.assertIn(SnapshotIssueCode.LEGACY_SOURCE_EMPTY,
                      {issue.code for issue in result.issues})


def _digests(directory: str) -> dict:
    """SHA-256 of every file in a directory, for an unchanged-source check."""
    import hashlib
    result = {}
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if not os.path.isfile(path) or os.path.islink(path):
            continue
        with io.open(path, "rb") as handle:
            result[name] = hashlib.sha256(handle.read()).hexdigest()
    return result


class TestChecksumFileParsing(unittest.TestCase):

    def test_a_well_formed_file_parses(self):
        digests, issues = parse_checksums(
            "%s  responses/a.json\n" % ("0" * 64))
        self.assertEqual(issues, ())
        self.assertEqual(digests, {"responses/a.json": "sha256:" + "0" * 64})

    def test_a_path_escaping_the_root_is_reported_under_its_own_code(self):
        _digests, issues = parse_checksums(
            "%s  ../../etc/passwd\n" % ("0" * 64))
        self.assertIn(SnapshotIssueCode.CHECKSUM_ESCAPES_ROOT,
                      {issue.code for issue in issues})

    def test_an_absolute_path_is_reported_as_escaping(self):
        _digests, issues = parse_checksums("%s  /etc/passwd\n" % ("0" * 64))
        self.assertIn(SnapshotIssueCode.CHECKSUM_ESCAPES_ROOT,
                      {issue.code for issue in issues})

    def test_a_non_sha256_digest_is_refused(self):
        """MD5 lines are a different algorithm, not a shorter SHA-256."""
        _digests, issues = parse_checksums(
            "%s  responses/a.json\n" % ("0" * 32))
        self.assertIn(SnapshotIssueCode.UNSUPPORTED_HASH_ALGORITHM,
                      {issue.code for issue in issues})

    def test_uppercase_hex_is_refused(self):
        _digests, issues = parse_checksums("%s  a.json\n" % ("A" * 64))
        self.assertIn(SnapshotIssueCode.UNSUPPORTED_HASH_ALGORITHM,
                      {issue.code for issue in issues})

    def test_a_malformed_line_is_reported(self):
        _digests, issues = parse_checksums("not a checksum line\n")
        self.assertIn(SnapshotIssueCode.CHECKSUMS_MALFORMED,
                      {issue.code for issue in issues})

    def test_a_repeated_path_is_reported(self):
        text = ("%s  a.json\n" % ("0" * 64)) + ("%s  a.json\n" % ("1" * 64))
        _digests, issues = parse_checksums(text)
        self.assertIn(SnapshotIssueCode.DUPLICATE_ARTIFACT_PATH,
                      {issue.code for issue in issues})

    def test_every_bad_line_is_reported_not_just_the_first(self):
        text = "bad line one\nbad line two\n"
        _digests, issues = parse_checksums(text)
        self.assertEqual(len(issues), 2)


class TestCredentialsNeverEnterASnapshot(SnapshotTestCase):

    def test_a_credential_shaped_query_parameter_is_refused(self):
        from pgx.ingestion.common.manifest import build_acquisition_manifest
        from pgx.ingestion.common.models import AcquisitionRunId
        cache, _ = self.complete_run("secret")
        data = builders.body(1)
        key = builders.request_key("page-1")
        leaky = builders.record(key, data)
        leaky = type(leaky)(**{
            **{field: getattr(leaky, field) for field in leaky.__slots__},
            "safe_query": (("api_key", "s3cr3t"),)})
        manifest = build_acquisition_manifest(
            run_id=AcquisitionRunId("fixture-run-secret"),
            source_id=builders.SOURCE_KEY, started_at=builders.NOW,
            completed_at=builders.LATER,
            endpoints=(builders.endpoint([leaky]),))
        result = self.build_acquisition("PGX-DATA-20260830-001", cache=cache,
                                        manifest=manifest)
        self.assertFalse(result.sealed)
        self.assertIn(SnapshotIssueCode.CREDENTIAL_IN_REQUEST_METADATA,
                      {issue.code for issue in result.issues})
        self.assertNotIn("s3cr3t", " ".join(i.detail for i in result.issues))

    def test_no_secret_reaches_disk_when_the_build_is_refused(self):
        self.test_a_credential_shaped_query_parameter_is_refused()
        for current, _dirs, files in os.walk(self.root):
            for name in files:
                path = os.path.join(current, name)
                if not path.endswith((".json", ".ndjson", ".sha256")):
                    continue
                with io.open(path, "rb") as handle:
                    with self.subTest(path=path):
                        self.assertNotIn(b"s3cr3t", handle.read())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
