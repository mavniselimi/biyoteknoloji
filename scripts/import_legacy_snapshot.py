#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Package ``clinpgx_outputs_v2/`` as the checked-in legacy raw snapshot (WP-06).

    python3 scripts/import_legacy_snapshot.py            # build it
    python3 scripts/import_legacy_snapshot.py --verify   # check it is intact

A thin, single-purpose wrapper around ``pgx-dataset import-legacy`` that pins
the dataset identity, the source key and the limitation text, so the snapshot
this repository ships is reproducible from one command rather than from a
remembered set of flags.

**Why this dataset ID.** ``PGX-DATA-20260830-900`` is unclaimed, valid, and
dated to the day the import was performed. The ``9xx`` band is already the
project's convention for legacy identities - :mod:`pgx.application.legacy_baseline`
reserves ``PGX-DATA-20260829-999`` for the frozen WP-01 baseline, which is a
different artifact - so ``900`` cannot collide with a normal sequential build
(``001`` onward) and reads as legacy at a glance. It is recorded here rather than
generated, because scanning for "the next number" is a race and would make an
identity depend on what else happened to be on disk.

**What this import is not.** It does not claim the files were produced by the
WP-04 adapter, and it invents no run ID, no request chronology, no retrieval
timestamps and no completeness figure. The snapshot is ``LEGACY_IMPORT`` and
``QUARANTINED``, and every one of those absences is recorded as a limitation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from pgx.application.dataset_service import DatasetService  # noqa: E402
from pgx.application.snapshot_schema import validate_snapshot_manifest  # noqa: E402
from pgx.ingestion.snapshots import SnapshotManager  # noqa: E402

#: The frozen legacy directory. Read only; never written by this script.
LEGACY_SOURCE_DIR = os.path.join(REPO_ROOT, "clinpgx_outputs_v2")

#: Where the snapshot lives. A distinct source key from any registered
#: scientific source: these bytes are a project artifact of unknown provenance,
#: not an authenticated retrieval from ClinPGx.
SOURCE_KEY = "clinpgx-legacy-v2"

LEGACY_DATASET_PUBLIC_ID = "PGX-DATA-20260830-900"

RAW_ROOT = os.path.join(REPO_ROOT, "data", "raw")

#: Facts about what is absent. Each one is a question this snapshot cannot
#: answer, written for whoever reaches for it in WP-07 and after.
LIMITATIONS = (
    "Not produced by the WP-04 ClinPGx adapter. These files were written by "
    "the frozen legacy probe scripts, and no WP-04 acquisition run backs them.",
    "No trustworthy acquisition run identifier exists, and none has been "
    "invented. acquisition_run_id, acquisition_status and "
    "acquisition_content_hash are all null.",
    "Request chronology is unavailable: which endpoint produced which file, in "
    "what order, with what query parameters, is not recorded anywhere. "
    "requests.ndjson is therefore empty rather than reconstructed.",
    "Retry counts, HTTP status codes and rate-limit metadata are unavailable.",
    "Retrieval timestamps are unavailable. The snapshot's created_at is when "
    "the import ran, not when the source was queried.",
    "Completeness relative to the upstream ClinPGx source is unknown. Every "
    "file present was copied; what fraction of the source that represents is "
    "not established and is not implied.",
    "The source policy for these bytes is unknown. No named human has reviewed "
    "whether ClinPGx data may be stored, transformed or redistributed, so this "
    "snapshot is QUARANTINED and permanently non-publication-eligible.",
    "Legacy file naming and directory layout are preserved verbatim, including "
    "the mixed CSV and JSON shapes and the case-variant container spellings "
    "recorded in docs/migration/legacy-source-inventory.md.",
    "No canonical gene or drug resolution, no deduplication, no data-quality "
    "assessment, no evidence extraction and no interpretation has been applied.",
)

ORIGIN = {
    "source_directory": "clinpgx_outputs_v2",
    "produced_by": "frozen WP-01 legacy probe scripts (clinpgx_probe_v2.py)",
    "imported_by": "scripts/import_legacy_snapshot.py",
    "wp01_baseline_relationship": (
        "Distinct from the WP-01 legacy baseline (PGX-DATA-20260829-999), which "
        "captures legacy script *outputs* for regression comparison. This "
        "snapshot captures the legacy probe's raw downloads."),
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true",
                        help="verify the checked-in snapshot instead of building")
    parser.add_argument("--raw-root", default=RAW_ROOT)
    args = parser.parse_args(argv)

    manager = SnapshotManager(args.raw_root)
    if args.verify:
        result = manager.verify(SOURCE_KEY, LEGACY_DATASET_PUBLIC_ID,
                                schema_validator=validate_snapshot_manifest)
        sys.stdout.write(json.dumps(result.to_json(), indent=2) + "\n")
        return 0 if result.ok else 1

    service = DatasetService(manager)
    result = service.import_legacy(
        dataset_public_id=LEGACY_DATASET_PUBLIC_ID,
        source_key=SOURCE_KEY,
        legacy_source_dir=LEGACY_SOURCE_DIR,
        limitations=LIMITATIONS,
        legacy_origin=ORIGIN)
    sys.stdout.write(json.dumps(result.to_json(), indent=2) + "\n")
    return 0 if result.snapshot.sealed else 1


if __name__ == "__main__":
    raise SystemExit(main())
