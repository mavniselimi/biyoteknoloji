#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Record the provisional dataset-quality decision (WP-C06 use, Wave 3 D).

Wave 2 built the mechanism and left the ledger empty, which was correct: a
mechanism for recording a decision is not a decision. This script records the
first one.

The decision is **REJECTED**, and it is not a close call. The build's own
``dq-report.json`` reports ``passed: false`` with three blocking codes -
``SNAPSHOT_NOT_ACQUIRED``, ``SNAPSHOT_QUARANTINED`` and
``SOURCE_POLICY_MISSING`` - and Wave 1's disposition work found that all 33
legacy rule candidates in this dataset name no upstream record at all. There
is no reading of this dataset on which it is fit for a candidate release.

Recording a rejection is worth doing rather than leaving the ledger empty,
because an empty ledger and a recorded rejection look identical to a gate and
completely different to a person. The first says nobody has looked; the second
says somebody looked and said no.

**Who decided.** An automated pass, named as one. The reviewer fields carry a
process identifier that cannot be mistaken for a person, and the rationale says
so in its first clause. Wave 3 is forbidden to invent a human reviewer, and a
plausible-looking name in this field is exactly how that prohibition would be
broken while appearing to be followed.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pgx.application.quality_decision_service import (  # noqa: E402
    record_dataset_quality_decision)
from pgx.closure.authority import CandidateAuthorityState  # noqa: E402
from pgx.normalization.quality_decision import (LEDGER_PATH,  # noqa: E402
                                                DatasetQualityDecision,
                                                QualityDecision,
                                                load_ledger, measure_binding,
                                                render_review_record)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_PATH = os.path.join(REPO, "data", "canonical", "PGX-DATA-20260830-900")
REGISTRY_PATH = os.path.join(REPO, "config", "scientific-sources.json")
LEDGER = os.path.join(REPO, LEDGER_PATH)

REVIEWER_NAME = ("pgx-closure-wave03 automated quality pass "
                 "(NOT A HUMAN REVIEWER)")
REVIEWER_ROLE = "AUTOMATED_PROJECT_TEAM_PASS"

RATIONALE = (
    "Recorded by an automated pass, not by a person, and provisional under "
    "%s pending %s. The build's own dq-report.json reports passed=false with "
    "three blocking codes: SNAPSHOT_NOT_ACQUIRED (the snapshot is a "
    "LEGACY_IMPORT with no acquisition run behind it), SNAPSHOT_QUARANTINED "
    "(building from it is permitted so the data can be examined; passing a "
    "quality check on it is not), and SOURCE_POLICY_MISSING (no source-policy "
    "approval is on record for this dataset). Independently, the WP-C00 "
    "disposition work established that all 33 legacy rule candidates carried "
    "by this dataset name no upstream record: 1,526 linked proposals each "
    "carry an accession in their subject and none of the 33 does. This "
    "dataset is not a basis for a candidate release and is rejected as one. "
    "The rejection is about fitness for release; it does not destroy the "
    "dataset, which remains available for examination."
    % (CandidateAuthorityState.PROJECT_TEAM_PROVISIONAL.value,
       CandidateAuthorityState.PENDING_EXTERNAL_EXPERT_REVIEW.value))


def main() -> int:
    binding = measure_binding(BUILD_PATH, REGISTRY_PATH)
    missing = [name for name, value in binding.items() if not value]
    if missing:
        sys.stderr.write("cannot bind a decision; missing: %s\n"
                         % ", ".join(sorted(missing)))
        return 2

    report = json.load(open(os.path.join(BUILD_PATH, "dq-report.json"),
                            encoding="utf-8"))
    if report.get("decision", {}).get("passed") is not False:
        sys.stderr.write(
            "refusing: the dq report no longer reports passed=false, so the "
            "rationale this script would record is no longer accurate\n")
        return 2

    decision = DatasetQualityDecision(
        dataset_public_id=binding["dataset_public_id"],
        canonical_build_key=binding["canonical_build_key"],
        decision=QualityDecision.REJECTED,
        reviewer_name=REVIEWER_NAME,
        reviewer_role=REVIEWER_ROLE,
        decided_at=_dt.datetime.now(_dt.timezone.utc).replace(microsecond=0),
        rationale=RATIONALE,
        dq_artifact_hash=binding["dq_artifact_hash"],
        source_policy_hash=binding["source_policy_hash"])

    result = record_dataset_quality_decision(
        decision, BUILD_PATH, REGISTRY_PATH, LEDGER)

    sys.stdout.write("outcome: %s\n" % result.decision_result.outcome.value)
    if result.decision_result.detail:
        sys.stdout.write("detail: %s\n" % result.decision_result.detail)
    if result.transition_detail:
        sys.stdout.write("transition: %s\n" % result.transition_detail)
    sys.stdout.write("ledger rows: %d\n" % len(load_ledger(LEDGER)))
    sys.stdout.write("\n" + render_review_record(load_ledger(LEDGER)))
    return 0 if result.decision_result.outcome.is_recorded else 1


if __name__ == "__main__":
    raise SystemExit(main())
