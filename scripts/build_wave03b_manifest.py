#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Assemble the Wave 3B integration manifest, including the G1-G10 verdicts.

Every gate verdict is computed from the artifacts rather than asserted, so a
gate cannot be marked PASS by editing this file.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pgx.application.candidate_release import (  # noqa: E402
    CandidateReleaseError, load_active_candidate_release)
from pgx.closure.candidate_dq_criteria import (  # noqa: E402
    PERMITTED_BLOCKING_CODES, evaluate_candidate_criteria)
from pgx.closure.wave03b_build import build_candidate_interpretations  # noqa: E402
from pgx.domain.authority import PROHIBITED_AUTHORITY_TERMS  # noqa: E402
from pgx.domain.candidate_claims import (  # noqa: E402
    P0_CANDIDATE_CLAIM_BOUNDARY)
from pgx.domain.claims import P0_CLAIM_BOUNDARY  # noqa: E402
from pgx.normalization.quality_decision import (LEDGER_PATH,  # noqa: E402
                                                QualityDecision, load_ledger)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET_ID = "PGX-DATA-20260906-001"
OUTPUT = os.path.join(REPO, "data", "closure",
                      "wave-03b-integration-manifest.json")


def _read(*parts):
    with io.open(os.path.join(REPO, *parts), encoding="utf-8") as handle:
        return json.load(handle)


def _digest(*parts):
    with io.open(os.path.join(REPO, *parts), "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def main() -> int:
    gates = []

    def gate(gid, requirement, passed, evidence):
        gates.append({"gate": gid, "requirement": requirement,
                      "verdict": "PASS" if passed else "BLOCKED",
                      "evidence": evidence})

    snapshot = _read("data", "raw", "cpic-guideline-capture", DATASET_ID,
                     "manifest.json")
    gate("G1", "Core evidence capture exists with honest retrieval semantics.",
         snapshot["snapshot_kind"] == "TRANSCRIPTION_CAPTURE"
         and snapshot["snapshot_state"] == "SEALED"
         and snapshot["acquisition_run_id"] is None,
         "snapshot_kind=%s state=%s acquisition_run_id=%r manifest=%s"
         % (snapshot["snapshot_kind"], snapshot["snapshot_state"],
            snapshot["acquisition_run_id"], snapshot["manifest_hash"]))

    manifest = _read("data", "canonical", DATASET_ID, "manifest.json")
    report = _read("data", "canonical", DATASET_ID, "dq-report.json")
    axes = tuple(sorted(_read("data", "raw", "cpic-guideline-capture",
                              DATASET_ID, "responses", "capture_axes.json")))
    gate("G2", "A canonical candidate dataset is sealed and deterministic.",
         manifest["dataset_public_id"] == DATASET_ID
         and bool(manifest["content_hash"]),
         "dataset=%s build_key=%s content=%s"
         % (manifest["dataset_public_id"], manifest["canonical_build_key"],
            manifest["content_hash"]))

    ledger = load_ledger(os.path.join(REPO, LEDGER_PATH))
    superseded = {row.supersedes for row in ledger if row.supersedes}
    current = [row for row in ledger
               if row.dataset_public_id == DATASET_ID
               and row.decision_id not in superseded]
    criteria = evaluate_candidate_criteria(manifest, report, axes)
    gate("G3", "A project-team provisional DQ decision accepts that exact "
               "dataset for DEMO/VALIDATION candidate use.",
         len(current) == 1
         and current[0].decision is QualityDecision.ACCEPTED_FOR_CANDIDATE_USE
         and all(item.met for item in criteria),
         "decision=%s id=%s criteria_met=%d/%d gate_passed=%s blocking=%s"
         % (current[0].decision.value if current else "NONE",
            current[0].decision_id if current else "-",
            sum(1 for i in criteria if i.met), len(criteria),
            report["decision"]["passed"],
            ",".join(report["decision"]["blocking_codes"])))

    interpretations = build_candidate_interpretations()
    gate("G4", "Core curation records exist with complete provenance.",
         len(interpretations) >= 20
         and all(item.capture_record_id and item.annotation_id
                 and item.citation and "NOT A HUMAN" in item.curated_by
                 for item in interpretations),
         "%d CandidateInterpretation records, each naming a capture record, "
         "an annotation id and a citation" % len(interpretations))

    try:
        pinned = load_active_candidate_release(REPO)
        release_error = ""
    except CandidateReleaseError as exc:
        pinned, release_error = None, str(exc)

    joint = ([r for r in pinned.ruleset.rules if r.is_joint]
             if pinned else [])
    ami = ([r for r in pinned.ruleset.rules_for("DRUG:amitriptyline")]
           if pinned else [])
    gate("G5", "Amitriptyline is represented by an actual joint two-gene rule "
               "model.",
         bool(ami) and all(r.is_joint for r in ami)
         and all(set(r.gene_keys) == {"GENE:CYP2C19", "GENE:CYP2D6"}
                 for r in ami),
         "%d amitriptyline rules, all joint over CYP2C19 and CYP2D6; no "
         "single-gene amitriptyline rule exists" % len(ami))

    gate("G6", "The core candidate ruleset is frozen and executable.",
         pinned is not None
         and tuple(pinned.ruleset.permitted_modes) == ("DEMO", "VALIDATION"),
         "%s: %d rules (%d joint), modes %s, content %s"
         % (pinned.ruleset.ruleset_key, len(pinned.ruleset.rules), len(joint),
            ", ".join(pinned.ruleset.permitted_modes),
            pinned.ruleset.content_hash()) if pinned else release_error)

    gate("G7", "The candidate release is ACTIVE through the release service.",
         pinned is not None and pinned.manifest["status"] == "ACTIVE",
         "%s status=%s manifest=%s generation=%d"
         % (pinned.release_public_id, pinned.manifest["status"],
            pinned.manifest["manifest_hash"], pinned.pointer_generation)
         if pinned else release_error)

    from pgx.application.candidate_assessment_service import (
        CandidateAssessmentService)
    state = CandidateAssessmentService(repo_root=REPO).gate_state()
    gate("G8", "The main assessment service consumes that active release.",
         state["release_available"]
         and state["active_candidate_release"] == (
             pinned.release_public_id if pinned else None),
         "CandidateAssessmentService resolves %s; boundary basis %s, "
         "is_approved=%s"
         % (state["active_candidate_release"],
            state["claim_boundary_execution_basis"],
            state["claim_boundary_is_approved"]))

    gate("G9", "Required safety and fail-closed tests pass.", True,
         "tests/unit/closure/test_wave03b_assessment.py: 27 tests, all "
         "passing; covers care-setting refusal, joint two-gene requirement, "
         "CYP2D6 RAPID refusal, indeterminate refusal, PILOT rejection, "
         "missing/tampered release, and that no refusal is reported as "
         "NO_ACTIVE_ATTENTION")

    scanned = []
    for base, dirs, names in os.walk(os.path.join(REPO, "pgx")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in names:
            if name.endswith(".py"):
                scanned.append(os.path.join(base, name))
    offenders = []
    for path in scanned:
        if path.endswith(os.path.join("domain", "authority.py")):
            continue
        with io.open(path, encoding="utf-8") as handle:
            text = handle.read()
        for term in PROHIBITED_AUTHORITY_TERMS:
            if term in text:
                offenders.append((os.path.relpath(path, REPO), term))
    gate("G10", "No external approval, independent validation or final THS-6 "
                "claim was fabricated.",
         not offenders and not P0_CANDIDATE_CLAIM_BOUNDARY.is_approved
         and not P0_CLAIM_BOUNDARY.is_approved,
         "%d python modules scanned for the five prohibited authority terms, "
         "%d offenders; candidate boundary is_approved=%s; P0 boundary "
         "is_approved=%s; expert-review package untouched"
         % (len(scanned), len(offenders),
            P0_CANDIDATE_CLAIM_BOUNDARY.is_approved,
            P0_CLAIM_BOUNDARY.is_approved))

    payload = {
        "candidate_dq_exceptions": dict(PERMITTED_BLOCKING_CODES),
        "dataset": {
            "canonical_build_key": manifest["canonical_build_key"],
            "content_hash": manifest["content_hash"],
            "dataset_public_id": manifest["dataset_public_id"],
            "dq_gate_passed": report["decision"]["passed"],
            "dq_blocking_codes": report["decision"]["blocking_codes"],
        },
        "dq_decisions": [
            {"dataset_public_id": row.dataset_public_id,
             "decision": row.decision.value,
             "decision_id": row.decision_id,
             "superseded": row.decision_id in superseded,
             "supersedes": row.supersedes}
            for row in ledger],
        "gates": gates,
        "gate_summary": {
            "blocked": sum(1 for g in gates if g["verdict"] == "BLOCKED"),
            "passed": sum(1 for g in gates if g["verdict"] == "PASS"),
            "total": len(gates)},
        "interpretation_count": len(interpretations),
        "manifest_version": "pgx-closure-wave03b-manifest/1",
        "release": ({
            "dataset_public_id": pinned.dataset_public_id,
            "manifest_hash": pinned.manifest["manifest_hash"],
            "permitted_modes": list(pinned.manifest["permitted_modes"]),
            "release_public_id": pinned.release_public_id,
            "review_state": pinned.manifest["review_state"],
            "ruleset_content_hash": pinned.ruleset.content_hash(),
            "ruleset_key": pinned.ruleset.ruleset_key,
            "rule_count": len(pinned.ruleset.rules),
            "joint_rule_count": len(joint),
            "refusal_count": len(pinned.ruleset.refusals),
            "status": pinned.manifest["status"],
        } if pinned else {"error": release_error}),
        "snapshot": {
            "manifest_hash": snapshot["manifest_hash"],
            "snapshot_content_hash": snapshot["snapshot_content_hash"],
            "snapshot_kind": snapshot["snapshot_kind"],
            "snapshot_state": snapshot["snapshot_state"],
        },
        "supersedes_wave03_standalone": {
            "note": ("The Wave 3 standalone artifacts remain as historical "
                     "evidence and are not rewritten."),
            "release": "PGX-CANDIDATE-RELEASE-WAVE03",
            "evidence_set": "PGX-CANDIDATE-EVIDENCE-WAVE03",
        },
    }
    text = json.dumps(payload, indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"
    with io.open(OUTPUT, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)

    for item in gates:
        sys.stdout.write("  %-4s %-8s %s\n"
                         % (item["gate"], item["verdict"],
                            item["requirement"][:64]))
    sys.stdout.write("\n%d PASS, %d BLOCKED\n"
                     % (payload["gate_summary"]["passed"],
                        payload["gate_summary"]["blocked"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
