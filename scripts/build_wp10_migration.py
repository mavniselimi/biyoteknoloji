#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the WP-10 legacy work-item migration artifacts.

Reads WP-08's ``draft-curation-proposals.ndjson`` and writes, under
``data/migration/wp10/``:

* ``legacy-work-item-allocation.json`` - the id each proposal was allocated,
  recorded so a rebuild cannot renumber anything;
* ``legacy-work-items.ndjson`` - 1,559 RAW work items;
* ``legacy-work-item-evidence-links.ndjson`` - the links the legacy extraction
  found, carried across as unreviewed;
* ``migration-issues.ndjson`` - one row per proposal with no link, saying why;
* ``manifest.json`` - counts, digests and the invariants asserted;
* ``checksums.sha256`` - so a reader can verify the set without this script.

Deterministic by construction. The import timestamp is derived from the input
file's content hash rather than from the clock, so re-running produces
byte-identical output; a wall-clock stamp would make "did the data change"
unanswerable without diffing every row.

This script writes nothing to a database and creates no interpretation. It
produces files describing 1,559 questions that nobody has answered.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import io
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from pgx.curation.workflow.legacy import (  # noqa: E402
    LEGACY_ALLOCATION_VERSION, LEGACY_MIGRATION_VERSION,
    LEGACY_VALUE_NAMESPACE, PROHIBITED_LEGACY_SOURCES, build_work_items,
    read_proposals)
from pgx.curation.workflow.models import LEGACY_MIGRATION_TAG  # noqa: E402
from pgx.domain.hashing import sha256_digest  # noqa: E402

PROPOSALS = os.path.join(REPO_ROOT, "data", "migration", "wp08",
                         "draft-curation-proposals.ndjson")
OUT_DIR = os.path.join(REPO_ROOT, "data", "migration", "wp10")

#: The epoch every derived import timestamp is measured from. A fixed anchor
#: plus a content-derived offset gives a stamp that is stable across rebuilds
#: and still changes when the input does.
_ANCHOR = _dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc)

IMPORTED_BY = "pgx-curation-workflow/import-legacy"


def _file_digest(path: str) -> str:
    digest = hashlib.sha256()
    with io.open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _derived_moment(input_digest: str) -> _dt.datetime:
    """A timestamp that is a function of the input, not of the clock."""
    offset = int(input_digest.split(":", 1)[1][:8], 16) % 86400
    return _ANCHOR + _dt.timedelta(seconds=offset)


def _write_json(path: str, payload) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_ndjson(path: str, rows) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    buffer = io.StringIO()
    for row in rows:
        buffer.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    text = buffer.getvalue()
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def build(out_dir: str = OUT_DIR, proposals_path: str = PROPOSALS) -> dict:
    input_digest = _file_digest(proposals_path)
    imported_at = _derived_moment(input_digest)

    report = build_work_items(read_proposals(proposals_path),
                              imported_at=imported_at,
                              imported_by=IMPORTED_BY)
    counts = report.counts()

    digests = {}
    digests["legacy-work-items.ndjson"] = _write_ndjson(
        os.path.join(out_dir, "legacy-work-items.ndjson"),
        [item.to_json() for item in report.work_items])
    digests["legacy-work-item-evidence-links.ndjson"] = _write_ndjson(
        os.path.join(out_dir, "legacy-work-item-evidence-links.ndjson"),
        report.evidence_links)
    digests["migration-issues.ndjson"] = _write_ndjson(
        os.path.join(out_dir, "migration-issues.ndjson"), report.issues)
    digests["legacy-work-item-allocation.json"] = _write_json(
        os.path.join(out_dir, "legacy-work-item-allocation.json"),
        {
            "allocation_format_version": LEGACY_ALLOCATION_VERSION,
            "allocated_by": IMPORTED_BY,
            "source_file": os.path.relpath(proposals_path, REPO_ROOT),
            "source_content_hash": input_digest,
            "allocated_at": imported_at.isoformat().replace("+00:00", "Z"),
            "entry_count": len(report.allocation),
            "entries": list(report.allocation),
            "note": (
                "A work item id is derived from its proposal id and recorded "
                "here. Ids are stable across rebuilds because every audit "
                "event that ever names one must keep pointing at the same "
                "question."),
        })

    manifest = {
        "migration_version": LEGACY_MIGRATION_VERSION,
        "generated_from": os.path.relpath(proposals_path, REPO_ROOT),
        "source_content_hash": input_digest,
        "imported_at": imported_at.isoformat().replace("+00:00", "Z"),
        "imported_by": IMPORTED_BY,
        "tag": LEGACY_MIGRATION_TAG,
        "legacy_value_namespace": LEGACY_VALUE_NAMESPACE,
        "counts": counts,
        "files": dict(digests),
        "excluded_sources": list(PROHIBITED_LEGACY_SOURCES),
        "invariants": [
            "every imported work item is RAW",
            "no work item is UNDER_REVIEW, CURATED or REJECTED",
            "no revision, review, adjudication or approval is created",
            "no CuratedInterpretation is created",
            "every work item carries the %s tag" % LEGACY_MIGRATION_TAG,
            "every legacy field is namespaced %s and is unreviewed input"
            % LEGACY_VALUE_NAMESPACE,
            "P1 candidate data is excluded by name, not by omission",
            "work item ids are allocated explicitly and are stable",
        ],
        "note": (
            "1,559 questions on a queue. The legacy values travel with them "
            "as upstream text so a curator can see what the old project "
            "claimed; none of it has been reviewed and none of it is a "
            "conclusion of this project."),
    }
    manifest["content_hash"] = sha256_digest(
        {key: value for key, value in manifest.items()
         if key != "content_hash"})
    digests["manifest.json"] = _write_json(
        os.path.join(out_dir, "manifest.json"), manifest)

    checksum_lines = "".join(
        "%s  %s\n" % (digests[name].split(":", 1)[1], name)
        for name in sorted(digests))
    with io.open(os.path.join(out_dir, "checksums.sha256"), "w",
                 encoding="utf-8", newline="\n") as handle:
        handle.write(checksum_lines)

    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=OUT_DIR)
    parser.add_argument("--proposals", default=PROPOSALS)
    args = parser.parse_args()

    manifest = build(args.out_dir, args.proposals)
    counts = manifest["counts"]
    sys.stdout.write(
        "wrote %d RAW work items (%d linked, %d unlinked) to %s\n"
        % (counts["work_items"], counts["linked_work_items"],
           counts["unlinked_work_items"],
           os.path.relpath(args.out_dir, REPO_ROOT)))
    sys.stdout.write("manifest content hash %s\n" % manifest["content_hash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
