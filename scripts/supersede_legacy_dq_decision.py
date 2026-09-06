#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-bind the legacy dataset's rejection to the current source policy.

Wave 3 rejected ``PGX-DATA-20260830-900`` and bound that decision to the
source-policy registry as it stood. Wave 3B registered the CPIC guideline
capture interface, which changed the registry's bytes and therefore its digest,
so the earlier decision no longer describes what is on disk - ``verify_decision``
reports a stale ``source_policy_hash``.

The verdict has not changed and is not being revisited. The dataset's own
``dq-report.json`` still reports ``passed: false`` with the same three blocking
codes, and all 33 of its legacy rule candidates still name no upstream record.
What changed is the world the decision was measured against, and a stale
binding on a *current* decision is a defect whether or not the conclusion still
holds: it means nobody can tell, from the ledger alone, whether the rejection
was reasoned about today's registry or yesterday's.

So the rejection is restated and re-bound, and the original stays in the ledger
marked superseded. Re-binding the old row in place would have been an edit.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pgx.application.quality_decision_service import (  # noqa: E402
    record_dataset_quality_decision)
from pgx.normalization.quality_decision import (LEDGER_PATH,  # noqa: E402
                                                DatasetQualityDecision,
                                                QualityDecision, load_ledger,
                                                measure_binding,
                                                render_review_record)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET_ID = "PGX-DATA-20260830-900"
BUILD_PATH = os.path.join(REPO, "data", "canonical", DATASET_ID)
REGISTRY_PATH = os.path.join(REPO, "config", "scientific-sources.json")
LEDGER = os.path.join(REPO, LEDGER_PATH)

DECIDED_AT = _dt.datetime(2026, 9, 6, 12, 5, 0, tzinfo=_dt.timezone.utc)


def main() -> int:
    ledger = load_ledger(LEDGER)
    superseded = {row.supersedes for row in ledger if row.supersedes}
    current = [row for row in ledger
               if row.dataset_public_id == DATASET_ID
               and row.decision_id not in superseded]
    if not current:
        sys.stderr.write("no current decision for %s to supersede\n"
                         % DATASET_ID)
        return 2
    prior = current[-1]

    binding = measure_binding(BUILD_PATH, REGISTRY_PATH)
    if binding["source_policy_hash"] == prior.source_policy_hash:
        sys.stdout.write("binding is already current; nothing to do\n")
        return 0

    with io.open(os.path.join(BUILD_PATH, "dq-report.json"),
                 encoding="utf-8") as handle:
        report = json.load(handle)
    blocking = report.get("decision", {}).get("blocking_codes") or []
    if report.get("decision", {}).get("passed") is not False:
        sys.stderr.write("refusing: the dq report no longer reports "
                         "passed=false\n")
        return 2

    record = DatasetQualityDecision(
        dataset_public_id=binding["dataset_public_id"],
        canonical_build_key=binding["canonical_build_key"],
        decision=QualityDecision.REJECTED,
        reviewer_name=prior.reviewer_name,
        reviewer_role=prior.reviewer_role,
        decided_at=DECIDED_AT,
        rationale=(
            "Restatement of the Wave 3 rejection, re-bound to the current "
            "source-policy registry. The verdict is unchanged and was not "
            "revisited: the build's own dq-report.json still reports "
            "passed=false with the blocking codes %s, and all 33 of its "
            "legacy rule candidates still name no upstream record. Only the "
            "binding moved, because registering the CPIC guideline capture "
            "interface changed the registry's digest."
            % ", ".join(blocking)),
        dq_artifact_hash=binding["dq_artifact_hash"],
        source_policy_hash=binding["source_policy_hash"],
        supersedes=prior.decision_id,
        supersedes_reason=(
            "The superseded decision was bound to the source-policy registry "
            "as it stood before the CPIC guideline capture interface was "
            "registered. Its source_policy_hash no longer matches the file on "
            "disk, so verify_decision reports it stale. The rejection itself "
            "is unchanged."))

    result = record_dataset_quality_decision(
        record, BUILD_PATH, REGISTRY_PATH, LEDGER)
    sys.stdout.write("outcome: %s\n" % result.decision_result.outcome.value)
    if result.decision_result.detail:
        sys.stdout.write("detail: %s\n" % result.decision_result.detail)
    sys.stdout.write("ledger rows: %d\n" % len(load_ledger(LEDGER)))
    sys.stdout.write("\n" + render_review_record(load_ledger(LEDGER)))
    return 0 if result.decision_result.outcome.is_recorded else 1


if __name__ == "__main__":
    raise SystemExit(main())
