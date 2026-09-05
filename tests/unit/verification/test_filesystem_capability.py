# -*- coding: utf-8 -*-
"""The portable immutability probe, and why it cannot be fooled.

WP-06 seals a snapshot to ``0o444``. The test that proved it asserted both the
mode bits and that appending raised ``PermissionError``, and the second half
failed as ``uid 0`` - the superuser is exempt from mode-bit checks - on a tree
that was perfectly well sealed.

Making it portable introduced a way for it to say nothing: a host where no
meaningful attempt is possible skips, and a skip is easy to stop reading. These
tests hold the other end down. The probe must report a writable file as
``PERMITTED``, must know when its own answer is worthless, and must not change
what it looks at.
"""

from __future__ import annotations

import io
import os
import stat
import tempfile
import unittest

from pgx.verification.filesystem import (
    MutationAttempt,
    MutationOutcome,
    attempt_append_here,
    attempt_unprivileged_mutation,
    chmod_is_honoured,
    denies_all_writers,
    file_mode,
    mode_bits_restrict_current_user,
    unprivileged_account,
)


class _FilesystemTestCase(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="pgx-wp19-fs-")
        os.chmod(self.root, 0o701)   # traverse for others, list for nobody
        self.addCleanup(self._cleanup)
        if not chmod_is_honoured(self.root):
            self.skipTest("this filesystem ignores chmod, so no mode-bit "
                          "assertion here would mean anything")

    def _cleanup(self):
        import shutil
        for current, directories, files in os.walk(self.root, topdown=False):
            for name in directories + files:
                try:
                    os.chmod(os.path.join(current, name), 0o700)
                except OSError:
                    pass
        shutil.rmtree(self.root, ignore_errors=True)

    def file_at(self, mode: int, name: str = "manifest.json") -> str:
        path = os.path.join(self.root, name)
        with io.open(path, "wb") as handle:
            handle.write(b'{"sealed": true}')
        os.chmod(path, mode)
        return path


class TestTheProbeDistinguishesSealedFromWritable(_FilesystemTestCase):
    """The property the whole repair rests on."""

    def _attempt(self, mode: int, name: str) -> MutationAttempt:
        return attempt_unprivileged_mutation(
            self.file_at(mode, name), probe_directory=self.root,
            may_take_ownership=True)

    def test_a_read_only_file_is_refused(self):
        attempt = self._attempt(0o444, "sealed.json")
        if attempt.outcome is MutationOutcome.NOT_ATTEMPTABLE:
            self.skipTest("no writer subject to these mode bits can be "
                          "arranged here: %s" % attempt.detail)
        self.assertIs(attempt.outcome, MutationOutcome.REFUSED)
        self.assertTrue(attempt.discriminating)

    def test_an_owner_writable_file_is_permitted(self):
        """The anti-hiding assertion. If this ever reports REFUSED, the
        portable path has become a place a mutable snapshot can hide."""
        attempt = self._attempt(0o644, "writable.json")
        if attempt.outcome is MutationOutcome.NOT_ATTEMPTABLE:
            self.skipTest("no writer subject to these mode bits can be "
                          "arranged here: %s" % attempt.detail)
        self.assertIs(attempt.outcome, MutationOutcome.PERMITTED)

    def test_a_world_writable_file_is_permitted(self):
        attempt = self._attempt(0o666, "world.json")
        if attempt.outcome is MutationOutcome.NOT_ATTEMPTABLE:
            self.skipTest("no writer subject to these mode bits can be "
                          "arranged here: %s" % attempt.detail)
        self.assertIs(attempt.outcome, MutationOutcome.PERMITTED)

    def test_an_owner_only_writable_file_is_permitted(self):
        """0o600 refuses everyone except the owner, and the owner is exactly
        who would do the accidental rewrite."""
        attempt = self._attempt(0o600, "ownermode.json")
        if attempt.outcome is MutationOutcome.NOT_ATTEMPTABLE:
            self.skipTest("no writer subject to these mode bits can be "
                          "arranged here: %s" % attempt.detail)
        self.assertIs(attempt.outcome, MutationOutcome.PERMITTED)


class TestTheProbeKnowsWhenItsAnswerIsWorthless(_FilesystemTestCase):

    def test_an_attempt_by_a_non_owner_is_not_discriminating(self):
        """A process running as ``nobody`` is refused by a 0o644 file too,
        because it is not the owner. Reporting that as REFUSED would call a
        tree sealed that its owner could rewrite at will."""
        attempt = MutationAttempt(MutationOutcome.REFUSED,
                                  "dropped-privileges", "refused", False)
        self.assertFalse(attempt.discriminating)

    def test_an_unattemptable_result_is_never_discriminating(self):
        attempt = MutationAttempt(MutationOutcome.NOT_ATTEMPTABLE, "none",
                                  "nothing to try", True)
        self.assertFalse(attempt.discriminating)

    def test_without_permission_to_take_ownership_a_root_probe_declines(self):
        """Rather than returning an answer it cannot stand behind."""
        if mode_bits_restrict_current_user(self.root):
            self.skipTest("this user is subject to mode bits, so the direct "
                          "attempt is already meaningful and no ownership "
                          "transfer is needed")
        attempt = attempt_unprivileged_mutation(
            self.file_at(0o444, "declined.json"), probe_directory=self.root)
        self.assertIs(attempt.outcome, MutationOutcome.NOT_ATTEMPTABLE)
        self.assertIn("ownership", attempt.detail)


class TestTheProbeChangesNothing(_FilesystemTestCase):

    def test_it_leaves_content_mode_owner_and_time_alone(self):
        path = self.file_at(0o444, "untouched.json")
        with io.open(path, "rb") as handle:
            before_bytes = handle.read()
        before = os.stat(path)
        attempt_unprivileged_mutation(path, probe_directory=self.root,
                                      may_take_ownership=True)
        after = os.stat(path)
        with io.open(path, "rb") as handle:
            self.assertEqual(handle.read(), before_bytes)
        self.assertEqual(stat.S_IMODE(after.st_mode),
                         stat.S_IMODE(before.st_mode))
        self.assertEqual(after.st_uid, before.st_uid)
        self.assertEqual(after.st_gid, before.st_gid)
        self.assertEqual(after.st_size, before.st_size)
        self.assertEqual(after.st_mtime, before.st_mtime)

    def test_ownership_is_restored_even_for_a_writable_file(self):
        path = self.file_at(0o666, "restored.json")
        before = os.stat(path)
        attempt_unprivileged_mutation(path, probe_directory=self.root,
                                      may_take_ownership=True)
        self.assertEqual(os.stat(path).st_uid, before.st_uid)

    def test_the_capability_probe_removes_its_own_scratch(self):
        before = sorted(os.listdir(self.root))
        mode_bits_restrict_current_user(self.root)
        chmod_is_honoured(self.root)
        self.assertEqual(sorted(os.listdir(self.root)), before)

    def test_a_permitted_append_writes_no_bytes(self):
        path = self.file_at(0o644, "append.json")
        before = os.stat(path).st_size
        self.assertIs(attempt_append_here(path), MutationOutcome.PERMITTED)
        self.assertEqual(os.stat(path).st_size, before)


class TestTheBitLevelCheckNeedsNoPrivilegeAtAll(_FilesystemTestCase):
    """The half of the invariant that is answerable everywhere chmod sticks."""

    def test_a_sealed_manifest_denies_every_writer(self):
        self.assertTrue(denies_all_writers(self.file_at(0o444, "a.json")))

    def test_read_only_for_owner_alone_still_denies_every_writer(self):
        self.assertTrue(denies_all_writers(self.file_at(0o400, "b.json")))

    def test_any_write_bit_at_all_fails_it(self):
        for index, mode in enumerate((0o644, 0o464, 0o446, 0o600, 0o666,
                                      0o200, 0o020, 0o002)):
            with self.subTest(mode=oct(mode)):
                self.assertFalse(
                    denies_all_writers(self.file_at(mode, "c%d.json" % index)))

    def test_it_is_stricter_than_comparing_with_0o444(self):
        """0o444 is how it is spelled; "no write bit" is what is meant."""
        path = self.file_at(0o440, "d.json")
        self.assertNotEqual(file_mode(path), 0o444)
        self.assertTrue(denies_all_writers(path))


class TestTheUnprivilegedAccount(unittest.TestCase):

    def test_a_candidate_is_never_the_superuser(self):
        """An account called ``nobody`` that happened to be uid 0 would
        produce a confident and completely wrong REFUSED."""
        account = unprivileged_account()
        if account is None:
            self.skipTest("no non-root account is available on this host")
        name, uid, gid = account
        self.assertNotEqual(uid, 0)
        self.assertNotEqual(gid, 0)
        self.assertTrue(name)

    def test_it_is_absent_where_privileges_cannot_be_dropped(self):
        if hasattr(os, "fork") and hasattr(os, "setuid"):
            self.skipTest("this platform can drop privileges, so the absent "
                          "path cannot be exercised here")
        self.assertIsNone(unprivileged_account())  # pragma: no cover
