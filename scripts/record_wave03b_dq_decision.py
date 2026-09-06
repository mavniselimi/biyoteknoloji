#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Record the project-team provisional DQ decision on the candidate dataset.

Runs the declared candidate criteria against what is on disk, then records the
decision the criteria produce - ``ACCEPTED`` only if every criterion is met,
``REJECTED`` otherwise. The script has no way to record an acceptance the
criteria did not support, which is the only reason declaring criteria in
advance is worth anything.

The rationale states, on the decision's own face, that the data-quality gate
did **not** pass and names the two blocking issues it carries. An acceptance
that omitted them would be the exact failure this repository keeps guarding
against: a provisional decision read later as a clean bill of health.

The existing rejection of ``PGX-DATA-20260830-900`` is untouched. Two rows in
one ledger, about two datasets, saying different things, is what an append-only
ledger is for.
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
from pgx.closure.authority import CandidateAuthorityState  # noqa: E402
from pgx.closure.candidate_dq_criteria import (  # noqa: E402
    CANDIDATE_DQ_CRITERIA_VERSION, PERMITTED_BLOCKING_CODES,
    evaluate_candidate_criteria)
from pgx.normalization.quality_decision import (LEDGER_PATH,  # noqa: E402
                                                DatasetQualityDecision,
                                                QualityDecision, load_ledger,
                                                measure_binding,
                                                render_review_record)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET_ID = "PGX-DATA-20260906-001"
BUILD_PATH = os.path.join(REPO, "data", "canonical", DATASET_ID)
REGISTRY_PATH = os.path.join(REPO, "config", "scientific-sources.json")
LEDGER = os.path.join(REPO, LEDGER_PATH)

REVIEWER_NAME = ("pgx-closure-wave03b automated quality pass "
                 "(NOT A HUMAN REVIEWER)")
REVIEWER_ROLE = "AUTOMATED_PROJECT_TEAM_PASS"
DECIDED_AT = _dt.datetime(2026, 9, 6, 12, 0, 0, tzinfo=_dt.timezone.utc)

#: The first verdict this script recorded on this build, and why it was wrong.
#:
#: Kept rather than hidden. The criterion that failed, CD-08, read the
#: manifest's ``source_observed_axes`` as a list of axis names when it is a
#: counts object, so it found none of the five axes in a dataset that carries
#: all five. The dataset was never at fault. Both rows stay in the ledger.
FIRST_VERDICT_REASON = (
    "The superseded REJECTED verdict was produced by a defect in the "
    "candidate-criteria evaluator, not by anything about the dataset: "
    "criterion CD-08 read the canonical manifest's source_observed_axes field "
    "as a list of gene-drug axis names, when that field is an object of "
    "counts, so every axis appeared to be missing. CD-08 now reads the axes "
    "from the sealed capture artifact that actually lists them.")

REBIND_REASON = (
    "The superseded decision was bound to the source-policy registry before "
    "it was rewritten in the canonical form the project's own renderer "
    "produces. Its source_policy_hash no longer matches the file on disk, so "
    "verify_decision reports it stale. The verdict is unchanged.")


def _supersession(ledger, binding):
    """Which prior decision this run replaces, and why - or neither.

    Computed rather than hard-coded so the script is re-runnable: a decision
    that already describes what is on disk is left alone, and one that does
    not is superseded with the reason that actually applies.
    """
    superseded = {row.supersedes for row in ledger if row.supersedes}
    current = [row for row in ledger
               if row.dataset_public_id == DATASET_ID
               and row.decision_id not in superseded]
    if not current:
        return None, None
    prior = current[-1]
    if prior.decision is QualityDecision.REJECTED:
        return prior.decision_id, FIRST_VERDICT_REASON
    if prior.source_policy_hash != binding["source_policy_hash"] \
            or prior.dq_artifact_hash != binding["dq_artifact_hash"]:
        return prior.decision_id, REBIND_REASON
    return prior.decision_id, None


def _read(name: str) -> dict:
    with io.open(os.path.join(BUILD_PATH, name), encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    manifest = _read("manifest.json")
    dq_report = _read("dq-report.json")
    with io.open(os.path.join(
            REPO, "data", "raw", "cpic-guideline-capture", DATASET_ID,
            "responses", "capture_axes.json"), encoding="utf-8") as handle:
        observed_axes = tuple(sorted(json.load(handle)))
    results = evaluate_candidate_criteria(manifest, dq_report, observed_axes)
    failed = [item for item in results if not item.met]

    for item in results:
        sys.stdout.write("  %-7s %s  %s\n"
                         % (item.criterion_id,
                            "MET    " if item.met else "NOT MET",
                            item.requirement))
    sys.stdout.write("\n")

    binding = measure_binding(BUILD_PATH, REGISTRY_PATH)
    missing = [k for k, v in binding.items() if not v]
    if missing:
        sys.stderr.write("cannot bind a decision; missing: %s\n"
                         % ", ".join(sorted(missing)))
        return 2

    blocking = tuple(dq_report.get("decision", {}).get("blocking_codes") or ())
    exceptions = "; ".join(
        "%s (%s)" % (code, PERMITTED_BLOCKING_CODES[code])
        for code in blocking if code in PERMITTED_BLOCKING_CODES)

    if failed:
        decision = QualityDecision.REJECTED
        rationale = (
            "Recorded by an automated pass, not by a person, and provisional "
            "under %s pending %s. The candidate criteria (%s) were not met: "
            "%s. The dataset is not accepted for candidate use."
            % (CandidateAuthorityState.PROJECT_TEAM_PROVISIONAL.value,
               CandidateAuthorityState.PENDING_EXTERNAL_EXPERT_REVIEW.value,
               CANDIDATE_DQ_CRITERIA_VERSION,
               "; ".join("%s %s (%s)" % (i.criterion_id, i.requirement,
                                         i.observed) for i in failed)))
    else:
        decision = QualityDecision.ACCEPTED_FOR_CANDIDATE_USE
        rationale = (
            "Recorded by an automated pass, not by a person, and provisional "
            "under %s pending %s. ACCEPTED FOR CANDIDATE DEMO AND VALIDATION "
            "USE ONLY. This is not an approval for publication, pilot or "
            "clinical use, and it is not independent, clinical or expert "
            "validation. THE DATA-QUALITY GATE DID NOT PASS: the report "
            "records passed=false with the blocking issues %s. Both are "
            "structural to a transcription capture rather than defects, both "
            "were declared in advance as the closed exception list in %s, and "
            "a candidate release claims neither completeness relative to the "
            "upstream corpus nor an approved acquisition route. Every other "
            "criterion was met: the snapshot is SEALED, every artifact is "
            "classified, no evidence artifact is missing, every transcribed "
            "record carries a source identity, there is no blocking duplicate "
            "group, all five first-release axes are present, and no legacy "
            "scientific row is mixed in."
            % (CandidateAuthorityState.PROJECT_TEAM_PROVISIONAL.value,
               CandidateAuthorityState.PENDING_EXTERNAL_EXPERT_REVIEW.value,
               exceptions or "(none)", CANDIDATE_DQ_CRITERIA_VERSION))

    ledger = load_ledger(LEDGER)
    supersedes, supersedes_reason = _supersession(ledger, binding)
    if supersedes is not None and supersedes_reason is None:
        sys.stdout.write("the current decision already describes what is on "
                         "disk; nothing to record\n")
        sys.stdout.write(render_review_record(ledger))
        return 0

    record = DatasetQualityDecision(
        dataset_public_id=binding["dataset_public_id"],
        canonical_build_key=binding["canonical_build_key"],
        decision=decision,
        reviewer_name=REVIEWER_NAME,
        reviewer_role=REVIEWER_ROLE,
        decided_at=DECIDED_AT,
        rationale=rationale,
        dq_artifact_hash=binding["dq_artifact_hash"],
        source_policy_hash=binding["source_policy_hash"],
        supersedes=supersedes,
        supersedes_reason=supersedes_reason)

    result = record_dataset_quality_decision(
        record, BUILD_PATH, REGISTRY_PATH, LEDGER)

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
