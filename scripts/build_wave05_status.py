#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wave 5 status - measured, not declared.

Every line of the status vocabulary is earned by a check against an artifact
on disk. If a check fails the status narrows rather than the check being
removed, which is the only way a status statement is worth reading.
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

from pgx.closure.wave05_expert_package import QUESTION_IDS  # noqa: E402

OUTPUT = "data/closure/wave-05-status.json"

READY_VOCABULARY = (
    "AUTONOMOUS PREPARATION COMPLETE",
    "AWAITING GENUINE EXTERNAL EXPERT EVALUATION",
    "WP-C12 HUMAN STEP OPEN",
    "WP-C14B NOT STARTED",
    "WP-C15 NOT FINAL",
)

INCOMPLETE_VOCABULARY = (
    "AUTONOMOUS PREPARATION INCOMPLETE",
    "AWAITING GENUINE EXTERNAL EXPERT EVALUATION",
    "WP-C12 HUMAN STEP OPEN",
    "WP-C14B NOT STARTED",
    "WP-C15 NOT FINAL",
)


def _load(relative):
    path = os.path.join(REPO, *relative.split("/"))
    if not os.path.isfile(path):
        return None
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _exists(relative):
    return os.path.isfile(os.path.join(REPO, *relative.split("/")))


def _digest(relative):
    path = os.path.join(REPO, *relative.split("/"))
    if not os.path.isfile(path):
        return None
    with io.open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def main() -> int:
    frozen = _load("data/closure/wave-05-frozen-candidate-version.json") or {}
    manifest = _load("data/expert-package/package-manifest.json") or {}
    seal = _load("data/expert-package/expert-reserved-seal.json") or {}
    worksheet = _load(
        "data/expert-package/expert-reserved-worksheet.json") or {}
    template = _load(
        "data/expert-package/reviewer-response-template.json") or {}
    register = _load("data/closure/wp-c14b/feedback-register.json") or {}
    matrix = _load(
        "data/closure/wp-c14b/correction-impact-matrix.json") or {}
    inventory = _load(
        "data/closure/wp-c15/pre-final-evidence-inventory.json") or {}
    ths6 = _load("data/ths6/wp25-ths6-status.json") or {}

    reviewer_docs = (
        "docs/expert-package/reviewer/00-reviewer-instructions.md",
        "docs/expert-package/reviewer/01-qualification-and-identity.md",
        "docs/expert-package/reviewer/02-conflict-of-interest.md",
        "docs/expert-package/reviewer/03-consent-and-data-handling.md",
        "docs/expert-package/reviewer/04-blind-first-workflow.md",
        "docs/expert-package/reviewer/05-review-questionnaire.md",
        "docs/expert-package/reviewer/06-submission-procedure.md",
    )
    questionnaire = ""
    path = os.path.join(REPO, "docs", "expert-package", "reviewer",
                        "05-review-questionnaire.md")
    if os.path.isfile(path):
        with io.open(path, encoding="utf-8") as handle:
            questionnaire = handle.read()

    checks = [
        ("B1", "the evaluated candidate version is frozen under one hash",
         bool(frozen.get("combined_hash"))
         and frozen.get("artifact_count", 0) >= 50),
        ("B2", "the evaluation package has all sixteen sections and an index",
         manifest.get("file_count", 0) >= 27
         and not manifest.get("missing_files")),
        ("B2", "the package states it has not been reviewed",
         manifest.get("reviewed_by_anyone_outside_this_project") is False),
        ("B3", "twelve reserved cases are byte-sealed",
         seal.get("reserved_case_count") == 12),
        ("B3", "no reserved case carries an expected answer",
         seal.get("expected_is_null_for_every_case") is True),
        ("B3", "no reserved payload read was allowed, and the ledger chain "
               "is intact",
         seal.get("payload_reads_allowed") == 0
         and seal.get("access_chain_intact") is True),
        ("B3", "no reserved case was evaluated against the build",
         seal.get("evaluated_against_the_build") is False),
        ("B3", "the reviewer worksheet has twelve cases and no answers",
         worksheet.get("case_count") == 12
         and all(value == "HUMAN_REQUIRED"
                 for case in worksheet.get("cases", ())
                 for value in case.get("reviewer_answer", {}).values())),
        ("B4", "all seven reviewer workflow documents exist",
         all(_exists(name) for name in reviewer_docs)),
        ("B4", "the questionnaire asks all twelve criticism areas",
         all(qid in questionnaire for qid, _ in QUESTION_IDS)),
        ("B4", "the response template is a template and is unsigned",
         template.get("state") == "TEMPLATE_NOT_A_RESPONSE"),
        ("B5", "the correction register exists and is empty",
         register.get("item_count") == 0
         and register.get("state")
         == "AWAITING_GENUINE_EXTERNAL_EXPERT_RESPONSE"),
        ("B5", "all five dispositions are defined",
         sorted(register.get("dispositions_vocabulary", {})) ==
         ["ACCEPTED", "ACCEPTED_WITH_MODIFICATION",
          "DISAGREED_WITH_RATIONALE", "NOT_APPLICABLE",
          "REQUIRES_FUTURE_WORK"]),
        ("B5", "the impact matrix is empty and demands nothing invented",
         matrix.get("item_count") == 0
         and matrix.get("before_metrics") is None),
        ("B6", "the WP-C15 inventory is PRE-EXPERT / NOT FINAL",
         inventory.get("status") == "PRE-EXPERT / NOT FINAL"
         and inventory.get("is_final") is False),
        ("B6", "five unsigned templates are prepared",
         len(inventory.get("templates_prepared_unsigned", ())) == 5),
        ("B6", "every expert-dependent field is HUMAN_REQUIRED",
         bool(inventory.get("expert_dependent_fields"))
         and all(value == "HUMAN_REQUIRED" for value
                 in inventory.get("expert_dependent_fields", {}).values())),
        ("GUARD", "THS-6 is not achieved",
         ths6.get("ths6_achieved") is False),
        ("GUARD", "the release may not proceed",
         ths6.get("release_may_proceed") is False),
        ("GUARD", "no gate passes",
         ths6.get("passing_gate_count") == 0),
        ("GUARD", "the Definition of Done is not 15/15",
         ths6.get("definition_of_done_satisfied_count", 0) < 15),
        ("GUARD", "no external expert response is preserved",
         not register.get("preserved_responses")),
    ]

    failed = [(scope, text) for scope, text, ok in checks if not ok]
    payload = {
        "schema_version": "pgx-wave05-status/1",
        "wave": "Wave 5",
        "status_vocabulary": list(READY_VOCABULARY if not failed
                                  else INCOMPLETE_VOCABULARY),
        "autonomous_preparation_complete": not failed,
        "check_count": len(checks),
        "checks": [{"scope": scope, "check": text, "passed": ok}
                   for scope, text, ok in checks],
        "failed_checks": [{"scope": scope, "check": text}
                          for scope, text in failed],
        "frozen_version": {
            "release_public_id": frozen.get("release_public_id"),
            "combined_hash": frozen.get("combined_hash"),
            "artifact_count": frozen.get("artifact_count"),
            "commit": frozen.get("commit"),
        },
        "package_manifest_sha256":
            _digest("data/expert-package/package-manifest.json"),
        "work_packages": [
            {"work_package": "WP-C12",
             "subject": "final external expert evaluation",
             "state": "HUMAN_STEP_OPEN",
             "autonomous_part": "COMPLETE",
             "human_part": "NOT_STARTED",
             "who": "an external pharmacogenetics expert, recruited by the "
                    "project owner"},
            {"work_package": "WP-C14B",
             "subject": "post-expert correction and revalidation",
             "state": "NOT_STARTED",
             "autonomous_part": "MACHINERY_COMPLETE_AND_EMPTY",
             "human_part": "BLOCKED_ON_WP-C12",
             "who": "the project, once a real response exists"},
            {"work_package": "WP-C15",
             "subject": "final THS-6 evidence pack",
             "state": "NOT_FINAL",
             "autonomous_part": "PRE-EXPERT_INVENTORY_AND_TEMPLATES_COMPLETE",
             "human_part": "BLOCKED_ON_WP-C12_AND_WP-C14B",
             "who": "the nine named signoff roles, none of them signed"},
        ],
        "exact_human_action_required": [
            "Recruit an external pharmacogenetics expert - a clinical "
            "pharmacologist, clinical pharmacist, medical geneticist or "
            "pharmacogenomics scientist - who is not this project.",
            "Send them docs/expert-package/README.md and the four JSON "
            "companions in data/expert-package/.",
            "Have them complete the conflict-of-interest and consent forms "
            "BEFORE reading the scientific sections.",
            "Have them answer the twelve reserved cases blind-first, "
            "recording their expectation before running anything.",
            "Have them sign and date the review personally.",
            "Import it with: python3 scripts/wp_c14b_intake.py --response "
            "<file> --reviewer-slug <name>",
        ],
        "what_this_status_is_not": [
            "It is not a claim that the software is correct.",
            "It is not a claim that anything has been reviewed.",
            "Completing the autonomous scope is the successful end of what "
            "this session could do without a person, not the end of the "
            "work.",
        ],
    }

    path = os.path.join(REPO, *OUTPUT.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True,
                                ensure_ascii=False) + "\n")

    for scope, text, ok in checks:
        print("  %-6s %-4s %s" % (scope, "OK" if ok else "FAIL", text))
    print()
    for line in payload["status_vocabulary"]:
        print(line)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
