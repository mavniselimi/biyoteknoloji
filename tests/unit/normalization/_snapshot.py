# -*- coding: utf-8 -*-
"""Shared access to the real WP-06 legacy snapshot, plus synthetic ones.

The WP-07 build tests run against the actual quarantined snapshot rather than a
fixture, because the numbers they check - the case-variant collision count, the
candidate-merge drift, the derivation of the CSVs from the JSON beside them -
are claims about *that* data. A fixture would let all of them pass while the
real snapshot said something else.

Synthetic snapshots are built alongside for the negative cases: an unrecognised
artifact, a corrupt payload, a conflicting identity. Those must never be
produced by editing the real one.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import os
import shutil
import stat
import tempfile
import unittest
from typing import Optional

from pgx.ingestion.snapshots import (SnapshotBuildRequest, SnapshotKind,
                                     SnapshotManager)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
RAW_ROOT = os.path.join(REPO_ROOT, "data", "raw")
SOURCE_KEY = "clinpgx-legacy-v2"
DATASET_ID = "PGX-DATA-20260830-900"
NOW = _dt.datetime(2026, 8, 30, 12, 0, tzinfo=_dt.timezone.utc)


def make_writable(root: str) -> None:
    """Restore write permission so a sealed temporary snapshot can be removed."""
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


class RealSnapshotTestCase(unittest.TestCase):
    """Reads the real sealed snapshot. Never writes to it."""

    @classmethod
    def setUpClass(cls):
        cls.manager = SnapshotManager(RAW_ROOT)
        if not cls.manager.exists(SOURCE_KEY, DATASET_ID):
            raise unittest.SkipTest(
                "the legacy snapshot has not been built; run "
                "python3 scripts/import_legacy_snapshot.py")
        cls.snapshot_path = cls.manager.snapshot_path(SOURCE_KEY, DATASET_ID)
        cls.snapshot_manifest = cls.manager.inspect(SOURCE_KEY, DATASET_ID)

    def temp_output(self) -> str:
        """A disposable output root, cleaned up even after a sealed write."""
        directory = tempfile.mkdtemp(prefix="pgx-wp07-out-")
        self.addCleanup(lambda: (make_writable(directory),
                                 shutil.rmtree(directory, ignore_errors=True)))
        return directory


class SyntheticSnapshotTestCase(unittest.TestCase):
    """Builds throwaway legacy-import snapshots from arbitrary files.

    Used for every negative case. The real snapshot is never modified, and a
    companion test in :mod:`test_build_safety` asserts that no WP-07 test path
    writes into ``data/raw``.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="pgx-wp07-")
        self.addCleanup(self._cleanup)
        self.raw_root = os.path.join(self.root, "raw")
        self.manager = SnapshotManager(self.raw_root, clock=lambda: NOW,
                                       token_factory=lambda: "fixed")

    def _cleanup(self):
        make_writable(self.root)
        shutil.rmtree(self.root, ignore_errors=True)

    def seal(self, files, dataset_id: str = "PGX-DATA-20260830-001",
             source_key: str = "fixture-source") -> str:
        """Write ``files`` into a directory and seal it as a legacy import.

        Keys may be written either bare (``resolved_genes.json``) or with the
        ``responses/`` prefix the sealed layout uses; the prefix is stripped
        before copying, because the importer adds it. Writing it twice produced
        ``responses/responses/...``, which still worked - the role map is keyed
        by base name - while making every path in a test's assertions wrong.
        """
        source_dir = os.path.join(self.root, "source-" + dataset_id)
        os.makedirs(source_dir, exist_ok=True)
        for name, payload in files.items():
            relative = name[len("responses/"):] \
                if name.startswith("responses/") else name
            target = os.path.join(source_dir, relative)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            data = (payload if isinstance(payload, bytes)
                    else json.dumps(payload).encode("utf-8"))
            with io.open(target, "wb") as handle:
                handle.write(data)
        result = self.manager.build(SnapshotBuildRequest(
            dataset_public_id=dataset_id,
            source_key=source_key,
            snapshot_kind=SnapshotKind.LEGACY_IMPORT,
            legacy_source_dir=source_dir,
            legacy_origin={"source_directory": os.path.basename(source_dir),
                           "produced_by": "a WP-07 unit test fixture"},
            limitations=("synthetic: no acquisition run backs this snapshot",)))
        if not result.sealed:
            raise AssertionError([issue.render() for issue in result.issues])
        return self.manager.snapshot_path(source_key, dataset_id)

    def output_root(self) -> str:
        directory = os.path.join(self.root, "canonical")
        os.makedirs(directory, exist_ok=True)
        return directory
