# -*- coding: utf-8 -*-
"""Wave 5 - assemble the external expert evaluation package (WP-C12 input).

What this module may do and what it may not do is the whole design.

It may: hash artifacts, copy questions that were written to *be* questions,
render an empty worksheet for a reviewer to fill in, and drive WP-18's access
ledger so that what this project did to the reserved cases is on the record.

It may not: write an expected answer, evaluate the build against a reserved
case, or describe the package as reviewed. Two of those are prevented here by
construction rather than by discipline - :func:`reviewer_worksheet` has no
field an expected answer could occupy, and :func:`seal_report` records the
access ledger's own refusal rather than a claim that nothing was read.

The reserved-case boundary is not secrecy. The twelve requests are committed
in this repository in plain text and always have been. What is reserved is the
*judgment*: no expected answer exists for any of them, and this package is
built so that none can be added by accident.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import io
import json
import os
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.validation.access import (AccessContext, AccessLedger,
                                   decide_access)
from pgx.validation.vocabulary import (AccessAction, AccessContextKind,
                                       ValidationCaseRole)

__all__ = [
    "PACKAGE_VERSION",
    "SEAL_VERSION",
    "WORKSHEET_VERSION",
    "RESPONSE_TEMPLATE_VERSION",
    "HUMAN_REQUIRED",
    "QUESTION_IDS",
    "digest_bytes",
    "digest_file",
    "package_manifest",
    "reviewer_worksheet",
    "reviewer_response_template",
    "seal_report",
]

PACKAGE_VERSION = "pgx-wave05-expert-package/1"
SEAL_VERSION = "pgx-wave05-expert-reserved-seal/1"
WORKSHEET_VERSION = "pgx-wave05-reviewer-worksheet/1"
RESPONSE_TEMPLATE_VERSION = "pgx-wave05-reviewer-response/1"

#: The single marker for a field only a person can fill. One spelling, so a
#: scan for unfinished fields is a string comparison and not a judgement call.
HUMAN_REQUIRED = "HUMAN_REQUIRED"

#: The twelve criticism areas B4 requires, as stable identifiers. The
#: questionnaire document and the machine-readable response template are
#: generated from this one tuple, so a question cannot exist in one and be
#: missing from the other.
QUESTION_IDS: Tuple[Tuple[str, str], ...] = (
    ("Q01-SCIENTIFIC-APPROPRIATENESS",
     "Is the overall scientific approach appropriate for what this software "
     "claims to be, and where is it not?"),
    ("Q02-PGX-INTERPRETATION-QUALITY",
     "Is the pharmacogenetic interpretation of each covered axis correct, "
     "and where would you interpret differently?"),
    ("Q03-SOURCE-SELECTION",
     "Are the selected sources the right ones for a first release, and what "
     "is missing or should not be there?"),
    ("Q04-SOURCE-CONFLICT-HANDLING",
     "Where sources disagree, is the project's handling defensible, and what "
     "would you do instead?"),
    ("Q05-PHENOTYPE-AND-ACTIVITY-SCORE-MAPPING",
     "Is the phenotype vocabulary and its mapping from source terms correct, "
     "including what the project refuses to map?"),
    ("Q06-AMITRIPTYLINE-JOINT-REPRESENTATION",
     "Is modelling amitriptyline as one joint CYP2C19+CYP2D6 decision "
     "correct, and is the twelve-cell table right?"),
    ("Q07-CLOPIDOGREL-ACS-PCI-RESTRICTION",
     "Is restricting clopidogrel to an explicitly declared ACS/PCI context "
     "correct, and is refusing without it the right behaviour?"),
    ("Q08-COVERAGE-AND-MISSING-DATA",
     "Is the coverage and missing-data behaviour correct, and does the "
     "output make the difference between a finding and a refusal clear?"),
    ("Q09-UNSAFE-REASSURANCE",
     "Is there anywhere a clinician could read this output as reassurance "
     "when it is not? Name each place."),
    ("Q10-WARNINGS-AND-CLAIMS",
     "Are the warnings and the claim boundary adequate, honest and correctly "
     "placed?"),
    ("Q11-USEFULNESS",
     "Would this be useful to a pharmacist or clinician in its intended "
     "demonstration role, and what would make it useless?"),
    ("Q12-RECOMMENDED-CORRECTIONS",
     "What must be corrected before this could be considered further, in "
     "your order of priority?"),
)


def digest_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def digest_file(path: str) -> str:
    with io.open(path, "rb") as handle:
        return digest_bytes(handle.read())


def _canonical(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------
# B3 - the reserved-case seal
# --------------------------------------------------------------------------

def seal_report(cases: Sequence[Any], *, catalogue_path: str,
                catalogue_relative: str,
                actor: str,
                clock: Optional[Callable[[], _dt.datetime]] = None
                ) -> Dict[str, Any]:
    """Byte-level integrity plus a recorded access ledger for the reserved set.

    Two things are measured here, and neither is asserted.

    *Integrity*: the committed artifact is hashed as bytes, and each case's
    own record is hashed from the canonical rendering the sealing script
    wrote. A changed reserved case changes a hash here.

    *Access*: every case is put through :func:`decide_access` twice - once for
    the partition audit this function is performing, which the policy allows,
    and once for a payload read, which the policy refuses because this caller
    holds no WP-22 assignment permit. Both outcomes are appended to the
    ledger. The refusal is the evidence: it is this project's own access
    policy declining to hand the reserved payloads to the process that built
    the package, recorded in a hash-chained ledger rather than claimed in
    prose.
    """
    reserved = [case for case in cases
                if case.metadata.role is ValidationCaseRole.EXPERT_HOLDOUT]
    ledger = AccessLedger(clock=clock)
    audit_context = AccessContext(
        actor=actor, kind=AccessContextKind.AUDIT,
        purpose="Wave 5 reserved-case integrity seal")
    read_context = AccessContext(
        actor=actor, kind=AccessContextKind.EXPERT_REVIEW,
        purpose="attempted payload read, holding no assignment permit")

    rows: List[Dict[str, Any]] = []
    for case in reserved:
        ledger.attempt(case.metadata, audit_context,
                       AccessAction.AUDIT_PARTITION)
        # No permit is passed. This is the point: the policy's blanket
        # EXPERT_HOLDOUT refusal applies to this process too.
        decision = decide_access(case.metadata, read_context,
                                 AccessAction.READ_PAYLOAD)
        ledger.record(case.metadata, read_context, AccessAction.READ_PAYLOAD,
                      decision)
        rows.append({
            "case_id": case.metadata.case_id.value,
            "title": case.metadata.title,
            "role": case.metadata.role.value,
            "visibility": case.metadata.visibility.value,
            "content_fingerprint": case.metadata.content_fingerprint,
            "metadata_hash": case.metadata.metadata_hash(),
            "record_sha256": digest_bytes(
                _canonical(case.to_json()).encode("utf-8")),
            "expected_is_null": case.expected is None,
            "question_present": bool(case.question),
        })

    intact, broken_at = ledger.verify_chain()
    events = ledger.to_json()
    allowed_payload_reads = sum(
        1 for event in events["events"]
        if event["action"] == AccessAction.READ_PAYLOAD.value
        and event["allowed"])

    return {
        "schema_version": SEAL_VERSION,
        "reserved_case_count": len(reserved),
        "catalogue_artifact": catalogue_relative,
        "catalogue_sha256": digest_file(catalogue_path),
        "cases": sorted(rows, key=lambda row: row["case_id"]),
        "expected_is_null_for_every_case": all(row["expected_is_null"]
                                               for row in rows),
        "question_present_for_every_case": all(row["question_present"]
                                               for row in rows),
        "evaluated_against_the_build": False,
        "evaluated_against_the_build_note": (
            "No reserved case was evaluated against the candidate release by "
            "this wave or the last. The benchmark's own access ledger records "
            "zero events, and expert_reserved_payloads_read is 0 in its "
            "metrics."),
        "access_ledger": events,
        "access_chain_intact": intact,
        "access_chain_first_broken_index": broken_at,
        "payload_reads_allowed": allowed_payload_reads,
        "payload_read_refusal_code": "EXPERT_HOLDOUT_REQUIRES_PERMITTED_WORKFLOW",
        "what_the_seal_is_not": [
            "It is not secrecy. The twelve requests are committed in this "
            "repository in plain text; a reviewer needs to see them to answer.",
            "What is reserved is the judgment. No expected answer exists for "
            "any of the twelve, and none was written to build this package.",
            "A byte hash proves a case did not change. It proves nothing "
            "about whether the case is a good question.",
        ],
    }


# --------------------------------------------------------------------------
# B3/B4 - the reviewer worksheet
# --------------------------------------------------------------------------

#: What a reviewer records per reserved case. There is deliberately no
#: ``expected`` key: the worksheet cannot carry a pre-written answer, because
#: it has nowhere to put one.
_ANSWER_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("reviewer_expected_attention",
     "What attention level, if any, do you consider correct for each drug in "
     "this request - before you look at what the software returned?"),
    ("reviewer_expected_refusals",
     "Which parts of this request should be refused rather than answered, "
     "and under what reason?"),
    ("reviewer_rationale",
     "Why. Cite the guideline or evidence you are relying on."),
    ("reviewer_answer_to_the_question",
     "The product question asked above, answered in your own words."),
    ("reviewer_unsafe_output_note",
     "If any part of the software's output on this case could mislead a "
     "clinician, describe it here."),
)


def reviewer_worksheet(cases: Sequence[Any], *, release_public_id: str,
                       release_manifest_hash: str,
                       catalogue_sha256: str) -> Dict[str, Any]:
    """The blank worksheet for the twelve reserved cases.

    Every answer field is :data:`HUMAN_REQUIRED`. The request and the question
    are copied verbatim from the sealed catalogue; nothing else crosses.
    """
    reserved = [case for case in cases
                if case.metadata.role is ValidationCaseRole.EXPERT_HOLDOUT]
    entries = []
    for case in sorted(reserved, key=lambda c: c.metadata.case_id.value):
        entries.append({
            "case_id": case.metadata.case_id.value,
            "title": case.metadata.title,
            "product_question": case.question,
            "request": dict(case.request),
            "reviewer_answer": {name: HUMAN_REQUIRED
                                for name, _ in _ANSWER_FIELDS},
        })
    return {
        "schema_version": WORKSHEET_VERSION,
        "status": "PRE-EXPERT / NOT FINAL",
        "release_public_id": release_public_id,
        "release_manifest_hash": release_manifest_hash,
        "catalogue_sha256": catalogue_sha256,
        "answer_field_definitions": [{"field": name, "prompt": prompt}
                                     for name, prompt in _ANSWER_FIELDS],
        "blind_first_note": (
            "Fill in reviewer_expected_attention, reviewer_expected_refusals "
            "and reviewer_rationale BEFORE running the case in the software. "
            "That ordering is the only thing that makes the answer evidence "
            "rather than agreement."),
        "cases": entries,
        "case_count": len(entries),
        "no_expected_answers_note": (
            "This worksheet has no field for a pre-written expected answer, "
            "and the catalogue it was generated from records none. Nothing in "
            "this repository has an opinion about what the right answer is."),
    }


# --------------------------------------------------------------------------
# B4 - the structured response envelope
# --------------------------------------------------------------------------

def reviewer_response_template(*, release_public_id: str,
                               frozen_combined_hash: str,
                               package_manifest_hash: str) -> Dict[str, Any]:
    """The empty envelope a real reviewer's answers are imported through.

    Every identity, judgement and signature field is HUMAN_REQUIRED. The
    WP-C14B intake refuses a response in which any of them still is.
    """
    return {
        "schema_version": RESPONSE_TEMPLATE_VERSION,
        "state": "TEMPLATE_NOT_A_RESPONSE",
        "reviewed_release_public_id": release_public_id,
        "reviewed_frozen_combined_hash": frozen_combined_hash,
        "reviewed_package_manifest_hash": package_manifest_hash,
        "reviewer": {
            "name": HUMAN_REQUIRED,
            "professional_qualification": HUMAN_REQUIRED,
            "registration_or_licence_reference": HUMAN_REQUIRED,
            "affiliation": HUMAN_REQUIRED,
            "years_of_relevant_practice": HUMAN_REQUIRED,
            "contact": HUMAN_REQUIRED,
            "identity_verification": "NONE_PERFORMED",
            "identity_verification_note": (
                "This project performs no electronic identity verification "
                "and this is not a cryptographic signature."),
        },
        "conflict_of_interest": {
            "has_financial_interest_in_this_project": HUMAN_REQUIRED,
            "has_personal_relationship_with_the_author": HUMAN_REQUIRED,
            "has_competing_product_interest": HUMAN_REQUIRED,
            "other_interests_to_declare": HUMAN_REQUIRED,
            "declaration": HUMAN_REQUIRED,
        },
        "consent": {
            "understands_review_will_be_stored_and_published_in_repository":
                HUMAN_REQUIRED,
            "understands_no_patient_data_is_involved": HUMAN_REQUIRED,
            "consents_to_name_being_recorded": HUMAN_REQUIRED,
        },
        "blind_first_confirmation": {
            "recorded_expectations_before_running_the_software":
                HUMAN_REQUIRED,
            "note": HUMAN_REQUIRED,
        },
        "reserved_case_answers": HUMAN_REQUIRED,
        "questionnaire": [
            {"question_id": qid, "question": text,
             "answer": HUMAN_REQUIRED,
             "severity": HUMAN_REQUIRED,
             "correction_priority": HUMAN_REQUIRED}
            for qid, text in QUESTION_IDS
        ],
        "unsafe_or_misleading_outputs": HUMAN_REQUIRED,
        "overall_free_text_criticism": HUMAN_REQUIRED,
        "signature": {
            "signed_name": HUMAN_REQUIRED,
            "signature_method": HUMAN_REQUIRED,
            "date": HUMAN_REQUIRED,
        },
        "severity_vocabulary": ["BLOCKING", "MAJOR", "MINOR", "OBSERVATION"],
        "correction_priority_vocabulary": ["P0", "P1", "P2", "P3", "NONE"],
        "not_an_approval": (
            "Completing this form is a scientific review. It is not approval "
            "for clinical use, not independent validation, and not a release "
            "decision."),
    }


# --------------------------------------------------------------------------
# B2 - the package manifest
# --------------------------------------------------------------------------

def package_manifest(repo: str, relative_paths: Sequence[str], *,
                     frozen: Mapping[str, Any],
                     seal: Mapping[str, Any]) -> Dict[str, Any]:
    """Hash every file in the package and bind it to the frozen version."""
    files = []
    missing = []
    for relative in sorted(set(relative_paths)):
        path = os.path.join(repo, *relative.split("/"))
        if not os.path.isfile(path):
            missing.append(relative)
            continue
        files.append({"path": relative, "sha256": digest_file(path)})
    return {
        "schema_version": PACKAGE_VERSION,
        "status": "PRE-EXPERT / NOT FINAL",
        "review_state": "PENDING_EXTERNAL_EXPERT_REVIEW",
        "reviewed_by_anyone_outside_this_project": False,
        "frozen_version": {
            "release_public_id": frozen["release_public_id"],
            "combined_hash": frozen["combined_hash"],
            "commit": frozen["commit"],
            "artifact_count": frozen["artifact_count"],
        },
        "reserved_cases": {
            "count": seal["reserved_case_count"],
            "expected_is_null_for_every_case":
                seal["expected_is_null_for_every_case"],
            "payload_reads_allowed": seal["payload_reads_allowed"],
            "evaluated_against_the_build": seal["evaluated_against_the_build"],
        },
        "file_count": len(files),
        "files": files,
        "missing_files": missing,
        "questions_for_the_expert": [qid for qid, _ in QUESTION_IDS],
        "what_this_package_is_not": [
            "It has not been reviewed. It is the thing to be reviewed.",
            "It contains no expert judgment, no approval and no signature.",
            "It is not independent validation and is not clinical validation.",
            "Nothing in it changes the candidate release's authority state, "
            "which remains PROJECT_TEAM_PROVISIONAL.",
        ],
    }
