#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The WP-C13 1,000-assessment performance run against the active release.

Measures what it can measure honestly. This is an in-process run against the
candidate assessment service: no HTTP, no database, no network. Those are named
as limitations rather than implied away, because a latency figure that omits
its stack is a number without a question.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pgx.application.assessment_models import AssessmentInput  # noqa: E402
from pgx.application.candidate_assessment_service import (  # noqa: E402
    CandidateAssessmentService)
from pgx.application.candidate_release import (  # noqa: E402
    load_active_candidate_release)
from pgx.domain.claims import OperationMode, PermittedInputKind  # noqa: E402
from pgx.domain.enums import Phenotype  # noqa: E402
from pgx.engine.phenotype_models import (PhenotypeObservation,  # noqa: E402
                                         PhenotypeProfile)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(REPO, "data", "validation", "wave-04-performance.json")
RUNS = 1000

LIMITATIONS = (
    "in-process: the candidate assessment service is called directly, so no "
    "HTTP, ASGI, serialisation, authentication or database cost is included",
    "no database: this host has no Python PostgreSQL driver, so no persistence "
    "happened and none is measured",
    "single process, single thread, no concurrency; these are not throughput "
    "figures",
    "the release artifacts are read once at resolution and held, as they are "
    "in a real run, so filesystem cost appears once rather than per request",
)

_CASES = (
    ({"GENE:CYP2C19": Phenotype.POOR}, ["DRUG:clopidogrel"], "ACS_OR_PCI"),
    ({"GENE:CYP2C19": Phenotype.NORMAL}, ["DRUG:omeprazole"], None),
    ({"GENE:CYP2D6": Phenotype.ULTRARAPID}, ["DRUG:codeine"], None),
    ({"GENE:CYP2C19": Phenotype.NORMAL,
      "GENE:CYP2D6": Phenotype.INTERMEDIATE}, ["DRUG:amitriptyline"], None),
    ({"GENE:CYP2D6": Phenotype.RAPID}, ["DRUG:codeine"], None),
)


def main() -> int:
    pinned = load_active_candidate_release(REPO)
    service = CandidateAssessmentService(repo_root=REPO)
    inputs = []
    for phenotypes, medications, care in _CASES:
        inputs.append(AssessmentInput(
            mode=OperationMode.VALIDATION,
            input_kind=PermittedInputKind.SYNTHETIC_PHENOTYPE_PROFILE,
            profile=PhenotypeProfile(
                observations=tuple(
                    PhenotypeObservation(gene_canonical_key=gene,
                                         status="NORMALIZED", phenotype=value)
                    for gene, value in sorted(phenotypes.items())),
                input_contract_version="pgx-wave04-performance/1"),
            medications=tuple(medications), care_setting=care))

    latencies = []
    errors = 0
    for index in range(RUNS):
        assessment = inputs[index % len(inputs)]
        started = time.perf_counter()
        try:
            service.execute(assessment)
        except Exception:  # noqa: BLE001 - a failure is a datum
            errors += 1
        latencies.append((time.perf_counter() - started) * 1000.0)

    ordered = sorted(latencies)
    payload = {
        "authority_state": pinned.manifest["authority_state"],
        "error_count": errors,
        "error_rate": round(errors / RUNS, 6),
        "latency_max_ms": round(ordered[-1], 4),
        "latency_mean_ms": round(statistics.fmean(latencies), 4),
        "latency_min_ms": round(ordered[0], 4),
        "latency_p50_ms": round(statistics.median(latencies), 4),
        "latency_p95_ms": round(ordered[int(RUNS * 0.95) - 1], 4),
        "latency_p99_ms": round(ordered[int(RUNS * 0.99) - 1], 4),
        "limitations": list(LIMITATIONS),
        "measurement": "in-process candidate assessment service",
        "release_manifest_hash": pinned.manifest["manifest_hash"],
        "release_public_id": pinned.release_public_id,
        "review_state": pinned.manifest["review_state"],
        "run_count": RUNS,
        "ruleset_content_hash": pinned.ruleset.content_hash(),
        "schema_version": "pgx-wave04-performance/1",
    }
    with io.open(OUTPUT, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True,
                                ensure_ascii=False) + "\n")
    sys.stdout.write(
        "%d assessments against %s\n  p50 %.3f ms  p95 %.3f ms  p99 %.3f ms  "
        "max %.3f ms\n  errors %d (%.4f%%)\n"
        % (RUNS, pinned.release_public_id, payload["latency_p50_ms"],
           payload["latency_p95_ms"], payload["latency_p99_ms"],
           payload["latency_max_ms"], errors, payload["error_rate"] * 100))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
