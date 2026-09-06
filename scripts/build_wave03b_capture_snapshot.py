#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seal the candidate capture snapshot and build the canonical dataset (WP-C05).

Two steps, in the real core machinery rather than beside it:

1. ``SnapshotManager.build`` writes a ``TRANSCRIPTION_CAPTURE`` snapshot under
   ``data/raw/cpic-guideline-capture/<dataset id>``, sealed, read-only, with
   its own checksums and a retrieval log naming the four documents that were
   read.
2. ``build_canonical_dataset`` + ``write_build`` turn that snapshot into a
   canonical dataset under ``data/canonical/<dataset id>``, through the same
   extraction, identity-allocation and data-quality path every other dataset in
   this repository goes through.

A new dataset identifier is minted. ``PGX-DATA-20260830-900`` is untouched and
stays rejected: its rejection is a record of a real decision, and a wave that
quietly reused the identifier would erase it.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pgx.closure.capture_payloads import (CAPTURE_LIMITATIONS,  # noqa: E402
                                          CAPTURE_SOURCE_KEY,
                                          build_capture_files,
                                          build_capture_reads)
from pgx.ingestion.snapshots import (SnapshotBuildRequest,  # noqa: E402
                                     SnapshotKind, SnapshotManager)
from pgx.normalization.build import (CanonicalBuildRequest,  # noqa: E402
                                     build_canonical_dataset, write_build)
from pgx.normalization.quality import evaluate_quality  # noqa: E402
from pgx.scientific.policy import (default_config_path,  # noqa: E402
                                   load_registry)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_ROOT = os.path.join(REPO, "data", "raw")
CANONICAL_ROOT = os.path.join(REPO, "data", "canonical")

#: Minted once and pinned. Deriving it from today's date would make every
#: rebuild produce a different dataset, and a dataset identity that depends on
#: when the build ran is not an identity.
CANDIDATE_DATASET_ID = "PGX-DATA-20260906-001"

#: A fixed build instant, for the same reason every Wave 3 builder has one:
#: when a build ran is git's to record, and a timestamp inside the artifact
#: makes "is the committed dataset the one this code produces" unanswerable.
BUILD_INSTANT = _dt.datetime(2026, 9, 6, 12, 0, 0, tzinfo=_dt.timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-id", default=CANDIDATE_DATASET_ID)
    args = parser.parse_args()

    manager = SnapshotManager(RAW_ROOT, clock=lambda: BUILD_INSTANT)
    snapshot_path = manager.snapshot_path(CAPTURE_SOURCE_KEY, args.dataset_id)

    if os.path.isdir(snapshot_path):
        sys.stdout.write("snapshot already sealed at %s\n"
                         % os.path.relpath(snapshot_path, REPO))
        manifest = manager.inspect_path(snapshot_path)
    else:
        result = manager.build(SnapshotBuildRequest(
            dataset_public_id=args.dataset_id,
            source_key=CAPTURE_SOURCE_KEY,
            snapshot_kind=SnapshotKind.TRANSCRIPTION_CAPTURE,
            capture_files=build_capture_files(),
            capture_reads=build_capture_reads(),
            limitations=CAPTURE_LIMITATIONS))
        if not result.sealed:
            sys.stderr.write("snapshot refused:\n")
            for issue in result.issues:
                sys.stderr.write("  %s %s (%s)\n"
                                 % (issue.code.value, issue.detail,
                                    issue.subject))
            return 2
        manifest = result.manifest
        snapshot_path = result.snapshot_path

    sys.stdout.write(
        "sealed %s\n  kind        %s\n  state       %s\n"
        "  artifacts   %d\n  complete    %s\n  content     %s\n"
        "  manifest    %s\n"
        % (args.dataset_id, manifest.snapshot_kind.value,
           manifest.snapshot_state.value, len(manifest.artifacts),
           manifest.complete, manifest.snapshot_content_hash,
           manifest.manifest_hash))

    # write_build creates <output_root>/<dataset id>, so the root is the
    # canonical directory itself. Passing the dataset directory would nest it
    # one level deeper and produce a path no reader expects.
    output_root = CANONICAL_ROOT
    build_root = os.path.join(CANONICAL_ROOT, args.dataset_id)
    if os.path.isdir(build_root):
        sys.stdout.write("canonical build already present at %s\n"
                         % os.path.relpath(build_root, REPO))
        return 0

    build = build_canonical_dataset(CanonicalBuildRequest(
        snapshot_root=snapshot_path,
        output_root=output_root,
        allow_new_identities=True,
        now=BUILD_INSTANT,
        build_note=("Wave 3B candidate dataset, built from the sealed CPIC "
                    "guideline capture. Candidate use only: DEMO and "
                    "VALIDATION, pending external expert review.")))
    # The source-policy status is read from the registry rather than assumed,
    # so a report can never describe a dataset as built under a policy that
    # was not in force. PENDING_REVIEW is the honest value today and produces
    # a blocking SOURCE_POLICY_NOT_APPROVED issue, which is correct.
    registry = load_registry(default_config_path())
    capture = [item for item in registry.records
               if item.source_key == "cpic.guideline-capture"]
    policy_status = capture[0].status.value if capture else None
    report = evaluate_quality(build, source_policy_status=policy_status)

    written = write_build(build, output_root,
                          extra_documents={"dq-report.json": report.to_json()})

    sys.stdout.write(
        "canonical build written to %s\n  build key   %s\n"
        "  content     %s\n  files       %d\n"
        % (os.path.relpath(written.build_path, REPO),
           written.manifest["canonical_build_key"],
           written.manifest["content_hash"], len(written.file_digests)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
