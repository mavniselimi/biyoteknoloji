# -*- coding: utf-8 -*-
"""Shared scaffolding for the WP-06 tests.

Every test builds into a temporary directory it created itself and removes
afterwards. Nothing here touches ``data/raw/`` - the checked-in legacy snapshot
is verified read-only by ``test_legacy_snapshot.py`` and is never a test's
scratch space, because a corruption drill that ran against the real evidence
would destroy the thing it was checking.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
import unittest
from typing import Optional

from pgx.ingestion.common.models import CacheState
from pgx.ingestion.snapshots import (
    SnapshotBuildRequest,
    SnapshotKind,
    SnapshotManager,
)
from pgx.verification.filesystem import (
    MutationAttempt,
    attempt_unprivileged_mutation,
    chmod_is_honoured,
)

from tests.unit.snapshots import _builders as builders


def make_writable(root: str) -> None:
    """Restore write permission so a sealed test snapshot can be removed.

    Sealing makes a tree read-only, which is the point; a test that could not
    clean up after itself would leak temporary directories on every run.
    """
    for current, directory_names, file_names in os.walk(root, topdown=False):
        for name in directory_names:
            try:
                os.chmod(os.path.join(current, name), 0o700)
            except OSError:
                pass
        for name in file_names:
            try:
                os.chmod(os.path.join(current, name), 0o600)
            except OSError:
                pass
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass


class SnapshotTestCase(unittest.TestCase):
    """A temporary raw root, a pinned clock, and helpers to build into it."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="pgx-wp06-")
        self.addCleanup(self._cleanup)
        self.raw_root = os.path.join(self.root, "raw")
        self.manager = SnapshotManager(self.raw_root, clock=lambda: builders.NOW,
                                       token_factory=lambda: "fixed")

    def _cleanup(self):
        make_writable(self.root)
        shutil.rmtree(self.root, ignore_errors=True)

    # -- building ---------------------------------------------------------

    def complete_run(self, name: str = "cache", pages: int = 2,
                     cache_state: CacheState = CacheState.MISS):
        return builders.complete_run(os.path.join(self.root, name), pages=pages,
                                     cache_state=cache_state)

    def build_acquisition(
        self,
        dataset_id: str = "PGX-DATA-20260830-001",
        cache=None,
        manifest=None,
        kind: SnapshotKind = SnapshotKind.ACQUISITION,
        manager: Optional[SnapshotManager] = None,
        source_key: str = builders.SOURCE_KEY,
    ):
        if cache is None or manifest is None:
            cache, manifest = self.complete_run("cache-" + dataset_id)
        return (manager or self.manager).build(SnapshotBuildRequest(
            dataset_public_id=dataset_id,
            source_key=source_key,
            snapshot_kind=kind,
            acquisition_manifest=manifest,
            cache=cache))

    def sealed(self, dataset_id: str = "PGX-DATA-20260830-001", **kwargs):
        """Build a snapshot and assert it sealed, returning the result."""
        result = self.build_acquisition(dataset_id, **kwargs)
        self.assertTrue(result.sealed,
                        [issue.render() for issue in result.issues])
        return result

    # -- tampering (only ever on a test's own temporary snapshot) ----------

    def unlock(self, snapshot_path: str) -> None:
        make_writable(snapshot_path)

    def overwrite(self, snapshot_path: str, relative: str, data: bytes) -> None:
        self.unlock(snapshot_path)
        target = os.path.join(snapshot_path, *relative.split("/"))
        with io.open(target, "wb") as handle:
            handle.write(data)

    def remove(self, snapshot_path: str, relative: str) -> None:
        self.unlock(snapshot_path)
        os.unlink(os.path.join(snapshot_path, *relative.split("/")))

    def add_file(self, snapshot_path: str, relative: str,
                 data: bytes = b"{}") -> None:
        self.unlock(snapshot_path)
        target = os.path.join(snapshot_path, *relative.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with io.open(target, "wb") as handle:
            handle.write(data)

    def flip_one_byte(self, snapshot_path: str, relative: str) -> None:
        """Change exactly one byte of one artifact."""
        self.unlock(snapshot_path)
        target = os.path.join(snapshot_path, *relative.split("/"))
        with io.open(target, "rb") as handle:
            data = bytearray(handle.read())
        data[0] = data[0] ^ 0x01
        with io.open(target, "wb") as handle:
            handle.write(bytes(data))

    def first_response(self, manifest) -> str:
        return manifest.artifacts[0].relative_path

    def supports_permissions(self) -> bool:
        """True when this filesystem honours ``chmod``.

        The project's own working tree is sometimes a network mount that
        silently ignores permission changes. A read-only assertion there would
        fail for a reason that has nothing to do with the code, so the test
        that makes it skips instead - and says so.

        Delegates to WP-19 so that the probe itself has tests
        (``tests/unit/verification/test_filesystem_capability.py``). It used to
        be written out here, where nothing could check it.
        """
        return chmod_is_honoured(self.root)

    def mutation_attempt(self, path: str) -> MutationAttempt:
        """Try to append to ``path`` in a way that is actually meaningful.

        The old test opened the file for append and asserted ``PermissionError``.
        As ``uid 0`` that append succeeds - the superuser is exempt from mode
        bits - so the assertion failed on a tree that was perfectly well
        sealed, and it leaked the file handle while doing so.

        ``may_take_ownership`` is true here and nowhere else: the tree under
        test was created by ``setUp`` in a temporary directory this test case
        owns, so lending one file to an unprivileged account for the duration
        of a zero-byte append and taking it straight back is a legitimate thing
        to do to scratch. It is what makes the attempt *discriminating* - an
        attempt by a non-owner is refused by a writable file too, and would
        report a mutable tree as sealed. No committed artifact is ever passed
        to this helper.

        The probe writes its own scratch into ``self.root``, never into the
        sealed tree, and changes no mode bit on the file it probes.
        """
        self._allow_traversal_of_the_scratch_root()
        return attempt_unprivileged_mutation(path,
                                             probe_directory=self.root,
                                             may_take_ownership=True)

    def _allow_traversal_of_the_scratch_root(self) -> None:
        """Let an unprivileged process reach into this test's own temp root.

        ``tempfile.mkdtemp`` creates ``0o700``, so a forked child running as
        ``nobody`` cannot traverse into it and reports the attempt as
        unreachable - a skip caused by the scratch directory rather than by the
        snapshot. Everything the snapshot manager creates below here is already
        world-traversable (``0o755`` for the source directories, ``0o555`` for
        the sealed snapshot), so this one directory is the whole obstacle.

        ``0o701`` adds execute for others and nothing else: traverse, but not
        list, not read and not write. Only ``self.root`` is touched - a
        directory this test case created in ``setUp`` and removes in cleanup.
        No mode inside the sealed tree is changed, which is the line that
        matters: relaxing the artifact under test to make its own test pass
        would be the fabrication this repair exists to avoid.
        """
        os.chmod(self.root, 0o701)
