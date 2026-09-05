#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline acquisition, replay and partial-failure drill (WP-04).

    python3 scripts/ingestion_drill.py [--out DIRECTORY]

Runs the ingestion service end to end against a **scripted fake transport** and
prints what happened. It writes three example manifests: a complete run, a
cache-only replay, and a run with a failed required endpoint.

**No network call is made, here or anywhere in WP-04.** The transport is a
script; the replay uses a transport that raises if anything calls it. This
proves the rules, the completeness arithmetic and the determinism boundary. It
proves nothing about ClinPGx itself - whether these endpoints paginate the way
the catalog declares can only be settled against the live API, and WP-04 records
that as BLOCKED.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from pgx.application.ingestion_service import IngestionService  # noqa: E402
from pgx.ingestion.common.cache import ResponseCache  # noqa: E402
from pgx.ingestion.common.models import AcquisitionRunId  # noqa: E402
from pgx.ingestion.common.retry import RetryPolicy  # noqa: E402
from tests.unit.ingestion._fakes import (  # noqa: E402
    ForbiddenTransport, RecordingSleeper, ScriptedTransport, StepClock,
    data_page, fixed_random, json_response, raw_response,
)

PARAMETERS = {
    "symbol": "CYP2C19", "name": "clopidogrel",
    "gene_accession_id": "PA124", "chemical_accession_id": "PA449053",
    "view": "base",
}

ENDPOINTS = ["gene_lookup", "chemical_lookup", "guideline_annotation_by_pair",
             "guideline_annotation_by_gene"]

#: Synthetic records. Field names echo the source's shape; the values are
#: obviously fabricated and assert nothing about any real gene or drug.
GENE_PAGE_1 = [{"id": "FIXTURE-GENE-1", "symbol": "CYP2C19"},
               {"id": "FIXTURE-GENE-2", "symbol": "CYP2C19P1"}]
CHEMICAL_PAGE_1 = [{"id": "FIXTURE-CHEM-1", "name": "clopidogrel"}]
GUIDELINE_PAGE_1 = [{"id": "FIXTURE-GUIDE-1", "source": "fixture"}]


def _rule(title: str) -> None:
    print("\n" + title)
    print("-" * len(title))


def _service(cache, transport, run_id, step=0.0):
    return IngestionService(
        cache=cache, transport_factory=lambda: transport,
        retry_policy=RetryPolicy(max_attempts=3, initial_delay_seconds=0.5),
        clock=StepClock(step_seconds=step), sleeper=RecordingSleeper(),
        random_source=fixed_random(),
        new_run_id=lambda: AcquisitionRunId.parse(run_id))


def _write(directory, name, manifest):
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, name)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(manifest.to_json(), indent=2, sort_keys=True,
                                default=str) + "\n")
    return path


def _report(manifest) -> None:
    print("  status            : %s" % manifest.status.value)
    print("  publishable       : %s" % manifest.is_publishable)
    print("  endpoints         : %d (%d required)"
          % (len(manifest.endpoints), len(manifest.required_endpoints)))
    print("  pages / records   : %d / %d"
          % (manifest.total_pages, manifest.total_records))
    print("  content hash      : %s" % manifest.content_hash)
    for endpoint in manifest.endpoints:
        print("    %-34s %-8s %-9s pages=%d terminal=%s (%s)"
              % (endpoint.endpoint_id,
                 "required" if endpoint.required else "optional",
                 endpoint.outcome.value, endpoint.pagination.pages_fetched,
                 endpoint.pagination.terminal,
                 endpoint.pagination.termination_reason))
    for warning in manifest.warnings:
        print("  WARNING: %s" % warning)
    for failure in manifest.failures:
        print("  FAILURE: %s" % failure)


def main(argv=None) -> int:
    """Run the drill."""
    parser = argparse.ArgumentParser(prog="ingestion_drill.py")
    parser.add_argument("--out", default=None,
                        help="Directory to write example manifests into.")
    args = parser.parse_args(argv)

    import tempfile

    print("=" * 78)
    print("WP-04 OFFLINE INGESTION DRILL")
    print("=" * 78)
    print("Scripted fake transport. No socket is opened at any point.")
    print("Proves the retry, cache, pagination and completeness rules, and the")
    print("determinism boundary. Proves NOTHING about the live ClinPGx API:")
    print("whether these endpoints paginate as declared is BLOCKED on a live")
    print("call, which WP-04 did not make.")

    cache_dir = tempfile.mkdtemp(prefix="pgx-drill-cache-")
    cache = ResponseCache(cache_dir)

    # ---- 1. A complete run, with a retry along the way -------------------
    _rule("1. Network acquisition (one 503, retried)")
    transport = ScriptedTransport([
        json_response({}, status_code=503, headers={"Retry-After": "2"}),
        data_page(GENE_PAGE_1), data_page([]),
        data_page(CHEMICAL_PAGE_1), data_page([]),
        data_page(GUIDELINE_PAGE_1), data_page([]),
        data_page(GUIDELINE_PAGE_1), data_page([]),
    ])
    service = _service(cache, transport,
                       "00000000-0000-4000-8000-000000000001", step=0.5)
    complete = service.acquire(PARAMETERS, ENDPOINTS)
    _report(complete)
    print("  transport calls   : %d" % transport.call_count)
    first = complete.endpoints[0].records[0]
    print("  first page retries: %d" % first.retry_count)
    print("  first page digest : %s" % first.raw_sha256)

    # ---- 2. Cache-only replay -------------------------------------------
    _rule("2. Cache-only replay (transport raises if called)")
    forbidden = ForbiddenTransport()
    replay = _service(cache, forbidden,
                      "00000000-0000-4000-8000-000000000002", step=9.0
                      ).replay_from_cache(PARAMETERS, ENDPOINTS)
    _report(replay)
    print("  transport calls   : %d" % forbidden.call_count)
    print("  content hash equal to the network run: %s"
          % (replay.content_hash == complete.content_hash))
    print("  run id differs                       : %s"
          % (replay.run_id.to_json() != complete.run_id.to_json()))
    print("  every page a cache hit               : %s"
          % all(record.cache_state.value == "HIT"
                for endpoint in replay.endpoints
                for record in endpoint.records))

    # ---- 3. Partial failure ---------------------------------------------
    _rule("3. Partial failure (required endpoint returns corrupt JSON)")
    broken_cache = ResponseCache(tempfile.mkdtemp(prefix="pgx-drill-broken-"))
    broken = ScriptedTransport([
        data_page(GENE_PAGE_1), data_page([]),
        raw_response(b'{"data": ['),                  # required, corrupt
        data_page(GUIDELINE_PAGE_1), data_page([]),
        data_page(GUIDELINE_PAGE_1), data_page([]),
    ])
    failed = _service(broken_cache, broken,
                      "00000000-0000-4000-8000-000000000003").acquire(
        PARAMETERS, ENDPOINTS)
    _report(failed)
    print("  raw bytes of the corrupt page were still stored: %s"
          % (failed.endpoints[1].records[0].raw_sha256 is not None))

    # ---- 4. Optional failure is only a warning ---------------------------
    _rule("4. Optional endpoint fails (run still publishable)")
    warn_cache = ResponseCache(tempfile.mkdtemp(prefix="pgx-drill-warn-"))
    warned = _service(warn_cache, ScriptedTransport([
        data_page(GENE_PAGE_1), data_page([]),
        data_page(CHEMICAL_PAGE_1), data_page([]),
        data_page(GUIDELINE_PAGE_1), data_page([]),
        raw_response(b"<html>error</html>", content_type="text/html"),
    ]), "00000000-0000-4000-8000-000000000004").acquire(PARAMETERS, ENDPOINTS)
    _report(warned)

    # ---- 5. Written examples --------------------------------------------
    if args.out:
        _rule("5. Example manifests written")
        for name, manifest in (("acquisition-manifest-complete.json", complete),
                               ("acquisition-manifest-replay.json", replay),
                               ("acquisition-manifest-failed.json", failed)):
            print("  %s" % _write(args.out, name, manifest))

    _rule("6. Summary")
    print("  complete run : %s (publishable=%s)"
          % (complete.status.value, complete.is_publishable))
    print("  replay       : %s (publishable=%s, zero network calls)"
          % (replay.status.value, replay.is_publishable))
    print("  failed run   : %s (publishable=%s)"
          % (failed.status.value, failed.is_publishable))
    print("  warned run   : %s (publishable=%s)"
          % (warned.status.value, warned.is_publishable))
    print("\nDrill complete. Offline evidence only; no live ClinPGx call was made.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
