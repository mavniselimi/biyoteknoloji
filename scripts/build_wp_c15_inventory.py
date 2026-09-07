#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WP-C15 - the PRE-EXPERT / NOT FINAL evidence inventory and its templates.

Two jobs.

*Inventory*: hash every artifact that currently constitutes valid candidate
evidence, and record beside each one what it establishes and what it does not.
An inventory that only listed files would let a reader assume each one proves
something.

*Templates*: the five documents a final THS-6 pack needs, unsigned, with every
expert-dependent field HUMAN_REQUIRED. They are templates and they say so in a
field, not only in a filename.

The script refuses to write if any forbidden value would be recorded:
``ths6_achieved`` true, ``release_may_proceed`` true, six passing gates, or a
Definition of Done at 15/15. Those come from WP-25's own artifacts and are
never overridden here - the guard exists so that a future edit to this script
cannot quietly set one.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from pgx.closure.wave05_expert_package import HUMAN_REQUIRED  # noqa: E402

OUT = "data/closure/wp-c15"
STATUS = "PRE-EXPERT / NOT FINAL"

#: Every artifact that is currently valid candidate evidence, with the claim
#: it supports and the claim it does not. Declared, not globbed: a file that
#: appears in the tree does not become evidence by being there.
EVIDENCE = (
    ("data/closure/h01-source-policy-decision.json",
     "SOURCE_POLICY",
     "a named pharmacist approved four sources under recorded conditions on "
     "2026-09-06, and the five reviewed artifacts still hash to what he "
     "attested",
     "it approves no rule, no interpretation and no clinical use, and the "
     "source registry is still PENDING_REVIEW because six named provenance "
     "gaps remain"),
    ("data/canonical/PGX-DATA-20260906-001/manifest.json",
     "DATASET",
     "the canonical dataset exists, is content-hashed, and holds 35 "
     "observations over 4 drugs and 2 genes",
     "it is not an approved dataset; its lifecycle state is BUILDING"),
    ("data/canonical/PGX-DATA-20260906-001/dq-report.json",
     "DATA_QUALITY",
     "the data-quality gate ran and recorded its findings",
     "the gate FAILED on SNAPSHOT_COMPLETENESS_UNKNOWN and "
     "SOURCE_POLICY_NOT_APPROVED; the candidate decision accepted it over "
     "both and keeps permits_transition false"),
    ("data/candidate-rulesets/PGX-CANDIDATE-RULESET-WAVE03B/manifest.json",
     "RULESET",
     "26 candidate rules, 12 of them joint, with 13 recorded curation "
     "refusals, frozen under one content hash",
     "no rule carries a WP-10 approval envelope, because no approving "
     "curator exists; is_governed_ruleset is false"),
    ("data/candidate-rulesets/PGX-CANDIDATE-RULESET-WAVE03B/rules.ndjson",
     "RULESET",
     "each rule names its capture records, citations, interpretation key and "
     "source policy status",
     "provenance completeness is not scientific correctness"),
    ("data/candidate-rulesets/PGX-CANDIDATE-RULESET-WAVE03B/provenance.json",
     "RULESET",
     "the thirteen refusals are recorded as data, with source term, reason "
     "and code",
     "the refusals were decided by an automated pass with no second reader"),
    ("data/releases/PGX-CANDIDATE-REL-20260906-001/manifest.json",
     "RELEASE",
     "an active candidate release exists, pinned to one dataset and one "
     "ruleset, permitting DEMO and VALIDATION and prohibiting PILOT",
     "it is not registered in the WP-13 governed registry and the governed "
     "active-release pointer does not exist"),
    ("data/closure/wave-04-catalogue/manifest.json",
     "VALIDATION",
     "67 cases in three partitions, sealed before any benchmark ran, with a "
     "clean ten-rule separation audit",
     "the partitions are separated from each other and none of them is "
     "independent of the build it tests"),
    ("data/closure/wave-04-catalogue/separation-audit.json",
     "VALIDATION",
     "zero separation issues across ten checks",
     "separation is not independence"),
    ("data/closure/wave-04-benchmark/metrics.json",
     "VALIDATION",
     "55 cases scored; attention, coverage, refusal-reason and traceability "
     "agreement all 1.0; zero unsafe false reassurances; zero reserved "
     "payloads read",
     "agreement with expectations the same process wrote is internal "
     "consistency evidence, not accuracy against clinical truth"),
    ("data/closure/wave-04-benchmark/run-manifest.json",
     "VALIDATION",
     "the benchmark run is reproducible and identifies exactly what it ran "
     "against",
     "it did not run the twelve reserved cases and was not meant to"),
    ("data/closure/wave-04-operational-evidence.json",
     "OPERATIONAL",
     "what was verified operationally, per item",
     "each blocked item carries a measured reason; blocked is not skipped "
     "and is not passed"),
    ("data/closure/wave-04b-runtime-product-manifest.json",
     "PRODUCT",
     "WP-C14A and WP-C14 pass on measurement: the composed application "
     "reaches the candidate release over a real database with "
     "authentication, CSRF, authorisation, rate limiting and audit, and the "
     "sixteen-step flow completes with no expectation failure",
     "it ran in one local representative environment on one machine; it is "
     "not external staging and there has been no staging deployment"),
    ("data/closure/wave-05-frozen-candidate-version.json",
     "FREEZE",
     "58 artifacts hashed under one combined hash, so the version an expert "
     "reviews cannot later be confused with a changed one",
     "freezing approves nothing"),
    ("data/expert-package/package-manifest.json",
     "EXPERT_PACKAGE",
     "the evaluation package exists, is complete, and is bound by hash to "
     "the frozen version",
     "it has not been reviewed; it is the thing to be reviewed"),
    ("data/expert-package/expert-reserved-seal.json",
     "EXPERT_PACKAGE",
     "the twelve reserved cases are byte-hashed, carry no expected answer, "
     "and this project's own access policy refused all twelve payload reads "
     "to the process that built the package",
     "a byte hash proves a case did not change, not that it is a good "
     "question"),
    ("data/closure/wp-c14b/feedback-register.json",
     "CORRECTION_LOOP",
     "the post-review correction machinery exists and runs",
     "it is empty, and it refuses to hold an item with no real response "
     "behind it"),
    ("data/ths6/wp25-ths6-status.json",
     "THS6",
     "the evidence-pack software is implemented and produces an honest "
     "status",
     "ths6_achieved is false, release_may_proceed is false, no gate passes "
     "and the Definition of Done stands at 1 of 15"),
    ("data/verification/wp19-test-inventory.json",
     "VERIFICATION",
     "the software verification inventory is current and every module "
     "imports on the host that generated it",
     "an inventory of tests is not evidence that the tests are the right "
     "ones"),
)

#: Expert-dependent fields. Every one is HUMAN_REQUIRED until a real external
#: response, a real correction loop and real attestations exist.
_EXPERT_DEPENDENT = (
    "external_expert_review_received",
    "external_expert_findings_summary",
    "external_expert_disposition_summary",
    "correction_loop_outcome",
    "revalidation_outcome",
)


def _digest(relative: str):
    path = os.path.join(REPO, *relative.split("/"))
    if not os.path.isfile(path):
        return None, None
    with io.open(path, "rb") as handle:
        raw = handle.read()
    return "sha256:" + hashlib.sha256(raw).hexdigest(), len(raw)


def _load(relative: str):
    path = os.path.join(REPO, *relative.split("/"))
    if not os.path.isfile(path):
        return {}
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _write(relative: str, payload: object) -> str:
    path = os.path.join(REPO, *relative.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True,
                                ensure_ascii=False) + "\n")
    return relative


def _guard(status, gates, dod) -> list:
    """Every forbidden value, checked before anything is written."""
    problems = []
    if status.get("ths6_achieved"):
        problems.append("ths6_achieved is true")
    if status.get("release_may_proceed"):
        problems.append("release_may_proceed is true")
    if gates.get("all_gates_pass") or gates.get("passing_gate_count") == 6:
        problems.append("all six gates pass")
    if dod.get("all_items_satisfied") or dod.get("satisfied_count") == 15:
        problems.append("the Definition of Done is 15/15")
    return problems


def main() -> int:
    status = _load("data/ths6/wp25-ths6-status.json")
    gates = _load("data/ths6/wp25-gate-matrix.json")
    dod = _load("data/ths6/wp25-definition-of-done.json")
    signoff = _load("data/ths6/wp25-signoff-matrix.json")
    frozen = _load("data/closure/wave-05-frozen-candidate-version.json")
    register = _load("data/closure/wp-c14b/feedback-register.json")

    problems = _guard(status, gates, dod)
    if problems:
        sys.stderr.write(
            "refusing to write a PRE-EXPERT inventory over a state that "
            "claims completion: %s\n" % "; ".join(problems))
        return 2

    rows, missing = [], []
    for relative, category, establishes, does_not in EVIDENCE:
        digest, size = _digest(relative)
        if digest is None:
            missing.append(relative)
            continue
        rows.append({"artifact": relative, "category": category,
                     "sha256": digest, "byte_length": size,
                     "what_it_establishes": establishes,
                     "what_it_does_not_establish": does_not})

    inventory = {
        "schema_version": "pgx-wp-c15-pre-final-inventory/1",
        "status": STATUS,
        "is_final": False,
        "why_not_final": (
            "WP-C12 has not happened. No external expert has reviewed any of "
            "this, so no correction loop has run, no revalidation has run, "
            "and no attestation exists to sign."),
        "frozen_version": {
            "release_public_id": frozen.get("release_public_id"),
            "combined_hash": frozen.get("combined_hash"),
            "commit": frozen.get("commit"),
        },
        "evidence_item_count": len(rows),
        "evidence": rows,
        "missing_artifacts": missing,
        "carried_from_wp25_unchanged": {
            "ths6_achieved": status.get("ths6_achieved"),
            "release_may_proceed": status.get("release_may_proceed"),
            "gate_count": gates.get("gate_count"),
            "passing_gate_count": gates.get("passing_gate_count"),
            "all_gates_pass": gates.get("all_gates_pass"),
            "definition_of_done_enumerated": dod.get("enumerated_count"),
            "definition_of_done_satisfied": dod.get("satisfied_count"),
            "signoff_role_count": signoff.get("role_count"),
            "signed_signoff_count": signoff.get("signed_count"),
            "note": ("read from WP-25's own artifacts and never overridden "
                     "here; this inventory reports them and does not "
                     "compute them"),
        },
        "expert_dependent_fields": {name: HUMAN_REQUIRED
                                    for name in _EXPERT_DEPENDENT},
        "correction_loop": {
            "state": register.get("state"),
            "feedback_item_count": register.get("item_count"),
        },
        "templates_prepared_unsigned": [
            "data/closure/wp-c15/templates/final-gate-report.template.json",
            "data/closure/wp-c15/templates/definition-of-done.template.json",
            "data/closure/wp-c15/templates/human-attestation-packet."
            "template.json",
            "data/closure/wp-c15/templates/final-release-decision."
            "template.json",
            "data/closure/wp-c15/templates/ths6-summary.template.json",
        ],
        "what_this_inventory_is_not": [
            "It is not the final THS-6 evidence pack.",
            "It is not a gate report; no gate was evaluated by writing it.",
            "It is not signed, and nothing in it may be signed until the "
            "work each attestation names has actually been done.",
            "It does not make any claim about clinical validity.",
        ],
    }
    _write("%s/pre-final-evidence-inventory.json" % OUT, inventory)

    gate_rows = [{"gate_id": row.get("gate_id"), "title": row.get("title"),
                  "final_status": HUMAN_REQUIRED,
                  "current_wp25_blocker_count": len(row.get("blockers") or ()),
                  "evaluated_by": HUMAN_REQUIRED,
                  "evaluated_at": HUMAN_REQUIRED}
                 for row in gates.get("gates", ())]
    _write("%s/templates/final-gate-report.template.json" % OUT, {
        "schema_version": "pgx-wp-c15-final-gate-report/1-template",
        "state": "TEMPLATE_NOT_A_REPORT",
        "status": STATUS,
        "gates": gate_rows,
        "all_gates_pass": HUMAN_REQUIRED,
        "note": ("A gate's final status is set by evaluating it after the "
                 "expert review and correction loop, not by filling this in."),
    })

    _write("%s/templates/definition-of-done.template.json" % OUT, {
        "schema_version": "pgx-wp-c15-definition-of-done/1-template",
        "state": "TEMPLATE_NOT_A_REPORT",
        "status": STATUS,
        "enumerated_count": dod.get("enumerated_count"),
        "items": [{"dod_id": item.get("dod_id"),
                   "observable_condition": item.get("observable_condition"),
                   "final_state": HUMAN_REQUIRED,
                   "evidence_ids": HUMAN_REQUIRED}
                  for item in dod.get("items", ())],
        "satisfied_count": HUMAN_REQUIRED,
        "all_items_satisfied": HUMAN_REQUIRED,
        "note": ("An item becomes satisfied when its observable condition is "
                 "observed. Writing 15 here would not satisfy anything."),
    })

    _write("%s/templates/human-attestation-packet.template.json" % OUT, {
        "schema_version": "pgx-wp-c15-human-attestation/1-template",
        "state": "TEMPLATE_NOT_AN_ATTESTATION",
        "status": STATUS,
        "signature_mechanism": "TYPED_NAME",
        "identity_verification": "NONE_PERFORMED",
        "identity_verification_note": (
            "This project performs no electronic identity verification and "
            "holds no signature infrastructure. An attestation records that "
            "a typed statement naming a person was relayed to this "
            "repository."),
        "packets": [{"role_id": role.get("role_id"),
                     "role": role.get("role"),
                     "attests_to": role.get("attests_to"),
                     "must_have_reviewed": role.get("must_have_reviewed"),
                     "reviewed_artifact_hashes": HUMAN_REQUIRED,
                     "signatory_name": HUMAN_REQUIRED,
                     "professional_qualification": HUMAN_REQUIRED,
                     "signature_text": HUMAN_REQUIRED,
                     "signed_at": HUMAN_REQUIRED}
                    for role in signoff.get("roles", ())],
        "signed_count": 0,
        "note": ("Each packet binds what the signatory must have read to the "
                 "hashes of those artifacts, so an attestation cannot later "
                 "be read as covering a different version."),
    })

    _write("%s/templates/final-release-decision.template.json" % OUT, {
        "schema_version": "pgx-wp-c15-final-release-decision/1-template",
        "state": "TEMPLATE_NOT_A_DECISION",
        "status": STATUS,
        "release_public_id": frozen.get("release_public_id"),
        "decision": HUMAN_REQUIRED,
        "decision_vocabulary": ["APPROVE", "APPROVE_WITH_CONDITIONS",
                                "REFUSE", "DEFER"],
        "decided_by": HUMAN_REQUIRED,
        "professional_qualification": HUMAN_REQUIRED,
        "decided_at": HUMAN_REQUIRED,
        "conditions": HUMAN_REQUIRED,
        "rationale": HUMAN_REQUIRED,
        "preconditions_that_must_hold_first": [
            "a genuine external expert response exists and is preserved",
            "every feedback item carries a disposition and a written "
            "rationale",
            "the benchmark has been rerun and before/after metrics recorded",
            "the data-quality gate's two blocking findings are cleared, or a "
            "named human accepts them in a governed decision",
            "the source registry's six provenance gaps are cleared",
            "the release is registered through the WP-13 governed path",
        ],
        "note": ("Recording APPROVE here changes nothing on its own. The "
                 "candidate release is not in the governed registry, and "
                 "putting it there is a separate governed act."),
    })

    _write("%s/templates/ths6-summary.template.json" % OUT, {
        "schema_version": "pgx-wp-c15-ths6-summary/1-template",
        "state": "TEMPLATE_NOT_A_SUMMARY",
        "status": STATUS,
        "ths6_achieved": False,
        "ths6_achieved_note": (
            "False, and not HUMAN_REQUIRED. A template that left this blank "
            "could be completed by filling it in; the honest current value is "
            "false and it is recorded as false."),
        "release_may_proceed": False,
        "passing_gate_count": HUMAN_REQUIRED,
        "definition_of_done_satisfied_count": HUMAN_REQUIRED,
        "external_expert_review_received": False,
        "signed_attestation_count": 0,
        "unmet_conditions": status.get("unmet_conditions"),
        "note": ("THS-6 closes when its conditions are observed to hold. "
                 "This template records that they do not."),
    })

    print("  evidence items          %d" % len(rows))
    if missing:
        print("  MISSING                 %s" % ", ".join(missing))
    print("  status                  %s" % STATUS)
    print("  ths6_achieved           %s (carried from WP-25)"
          % status.get("ths6_achieved"))
    print("  release_may_proceed     %s (carried from WP-25)"
          % status.get("release_may_proceed"))
    print("  gates passing           %s of %s"
          % (gates.get("passing_gate_count"), gates.get("gate_count")))
    print("  definition of done      %s of %s"
          % (dod.get("satisfied_count"), dod.get("enumerated_count")))
    print("  templates               5, all unsigned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
