# -*- coding: utf-8 -*-
"""WP-C14B - post-expert correction and revalidation machinery.

Empty on purpose. Every structure a correction loop needs exists here; not one
of them is populated, because populating them requires an external expert
response that does not exist.

The refusals are the design. :func:`refusals_for` is what stands between this
repository and a fabricated review: it rejects the template, it rejects a
response with any field still :data:`HUMAN_REQUIRED`, it rejects a response
with no reviewer and no signature, and it rejects one that answers nothing.
:func:`extract_feedback_items` derives every item from verbatim reviewer text
and carries the location it came from, so an item with no source text cannot
be constructed - there is no code path that makes one.

Nothing here decides a disposition. A disposition is a judgement about whether
the project agrees with a reviewer, and a judgement is a human act; what this
module does is refuse to let one be recorded without a reason.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "REGISTER_VERSION",
    "MATRIX_VERSION",
    "PRESERVED_VERSION",
    "DISPOSITIONS",
    "IMPACT_CLASSES",
    "SAFETY_CLASSES",
    "FEEDBACK_KINDS",
    "REFUSAL_CODES",
    "AFFECTED_TEST_MAP",
    "HUMAN_REQUIRED",
    "refusals_for",
    "preserved_response",
    "extract_feedback_items",
    "affected_tests_for",
    "benchmark_rerun_decision",
    "correction_impact_matrix",
    "empty_register",
    "empty_matrix",
]

REGISTER_VERSION = "pgx-wp-c14b-feedback-register/1"
MATRIX_VERSION = "pgx-wp-c14b-correction-impact-matrix/1"
PRESERVED_VERSION = "pgx-wp-c14b-preserved-response/1"

HUMAN_REQUIRED = "HUMAN_REQUIRED"

#: The five dispositions, and what each one commits the project to.
DISPOSITIONS: Mapping[str, str] = {
    "ACCEPTED":
        "the project agrees and will make the change as described",
    "ACCEPTED_WITH_MODIFICATION":
        "the project agrees there is a problem and will fix it differently; "
        "the difference must be written down",
    "NOT_APPLICABLE":
        "the item does not apply to this build, with the reason why",
    "DISAGREED_WITH_RATIONALE":
        "the project does not agree, and records its reasons in full beside "
        "the reviewer's; the reviewer's text is never removed",
    "REQUIRES_FUTURE_WORK":
        "the project agrees and cannot act now; what is missing and who "
        "would clear it are both named",
}

#: What a correction touches. Chosen so that the answer selects tests.
IMPACT_CLASSES: Mapping[str, str] = {
    "RULE_CONTENT": "a rule's condition or outcome changes",
    "RULESET_SCOPE": "a rule is added or removed from the release",
    "PHENOTYPE_MAPPING": "a source term maps differently, or stops mapping",
    "REFUSAL_BEHAVIOUR": "what is refused, or the reason code it is refused under",
    "EVIDENCE_OR_CITATION": "provenance, citation or lineage",
    "PRODUCT_PRESENTATION": "what a screen shows or how it is worded",
    "DOCUMENTATION": "a document only; no executable behaviour changes",
    "SCOPE_OR_GOVERNANCE": "what the project claims, or what it may do",
}

#: How dangerous the thing being corrected is. ``UNSAFE_OUTPUT`` forces a
#: benchmark rerun; see :func:`benchmark_rerun_decision`.
SAFETY_CLASSES: Mapping[str, str] = {
    "UNSAFE_OUTPUT":
        "the current behaviour could be read as reassurance when it is not",
    "INCORRECT_SCIENCE":
        "the current behaviour misstates the source, without being unsafe",
    "MISLEADING_PRESENTATION":
        "the science is right and the presentation could mislead",
    "INCOMPLETE":
        "something is missing rather than wrong",
    "NO_SAFETY_IMPACT":
        "no clinical reading changes",
}

#: Where in a response an item came from.
FEEDBACK_KINDS: Mapping[str, str] = {
    "QUESTIONNAIRE_ANSWER": "one of the twelve questions",
    "RESERVED_CASE_DISAGREEMENT":
        "a reserved case where the reviewer's recorded expectation differs "
        "from what the software returned",
    "RESERVED_CASE_PRODUCT_ANSWER":
        "a reserved case's product question, answered",
    "UNSAFE_OUTPUT_REPORT": "an entry in the unsafe-output table",
    "FREE_TEXT": "the overall free-text criticism",
}

#: Every reason intake refuses a response. A refused intake writes nothing.
REFUSAL_CODES: Mapping[str, str] = {
    "RESPONSE_IS_THE_TEMPLATE":
        "the file is the blank template, not a response",
    "HUMAN_REQUIRED_FIELD_REMAINS":
        "at least one field a person must complete is still HUMAN_REQUIRED",
    "REVIEWER_NOT_IDENTIFIED":
        "no reviewer name or qualification is recorded",
    "NOT_SIGNED":
        "no signed name and date are recorded",
    "CONFLICT_OF_INTEREST_NOT_DECLARED":
        "the conflict-of-interest block was not completed",
    "CONSENT_NOT_RECORDED":
        "the consent block was not completed",
    "NOTHING_ANSWERED":
        "no question, reserved case or free-text field carries content",
    "RELEASE_BINDING_ABSENT":
        "the response does not name the release and frozen hash it reviewed",
}

#: Which test selections a given impact class implies. Declared rather than
#: inferred: a correction loop that picked its own regression tests would be
#: choosing what could catch it.
AFFECTED_TEST_MAP: Mapping[str, Tuple[str, ...]] = {
    "RULE_CONTENT": ("tests/unit/closure/test_wave03b_assessment.py",
                     "tests/unit/engine", "tests/unit/closure",
                     "scripts/run_wave04_benchmark.py"),
    "RULESET_SCOPE": ("tests/unit/closure", "tests/unit/engine",
                      "tests/unit/application",
                      "scripts/run_wave04_benchmark.py"),
    "PHENOTYPE_MAPPING": ("tests/unit/domain", "tests/unit/engine",
                          "tests/unit/closure",
                          "scripts/run_wave04_benchmark.py"),
    "REFUSAL_BEHAVIOUR": ("tests/unit/engine", "tests/unit/application",
                          "tests/unit/web",
                          "scripts/run_wave04_benchmark.py"),
    "EVIDENCE_OR_CITATION": ("tests/unit/closure", "tests/unit/evidence",
                             "tests/unit/verification"),
    "PRODUCT_PRESENTATION": ("tests/unit/web", "tests/integration/web",
                             "scripts/build_wave04b_manifest.py"),
    "DOCUMENTATION": ("tests/unit/closure", "tests/unit/verification"),
    "SCOPE_OR_GOVERNANCE": ("tests/unit/closure", "tests/unit/safety",
                            "tests/unit/ths6", "tests/unit/verification"),
}

#: Safety classes that force a full benchmark rerun whatever else is true.
_FORCES_RERUN = ("UNSAFE_OUTPUT", "INCORRECT_SCIENCE")

#: Impact classes whose corrections change what the engine computes.
_EXECUTABLE_IMPACT = ("RULE_CONTENT", "RULESET_SCOPE", "PHENOTYPE_MAPPING",
                      "REFUSAL_BEHAVIOUR")


def _walk_for_marker(node: Any, path: str = "") -> List[str]:
    """Every path in ``node`` whose leaf is still HUMAN_REQUIRED."""
    found: List[str] = []
    if isinstance(node, Mapping):
        for key in sorted(node):
            found.extend(_walk_for_marker(node[key],
                                          "%s.%s" % (path, key) if path
                                          else str(key)))
    elif isinstance(node, (list, tuple)):
        for index, item in enumerate(node):
            found.extend(_walk_for_marker(item, "%s[%d]" % (path, index)))
    elif node == HUMAN_REQUIRED:
        found.append(path)
    return found


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) \
        and value.strip() != HUMAN_REQUIRED


def refusals_for(response: Mapping[str, Any]) -> Tuple[Tuple[str, str], ...]:
    """Every reason this response may not be accepted. Empty means acceptable.

    Acceptable means structurally complete and evidently written by a person.
    It does not mean correct, and this module never decides whether it is.
    """
    problems: List[Tuple[str, str]] = []

    if response.get("state") == "TEMPLATE_NOT_A_RESPONSE":
        problems.append(("RESPONSE_IS_THE_TEMPLATE",
                         REFUSAL_CODES["RESPONSE_IS_THE_TEMPLATE"]))

    remaining = _walk_for_marker(response)
    if remaining:
        problems.append((
            "HUMAN_REQUIRED_FIELD_REMAINS",
            "%d field(s) still HUMAN_REQUIRED, first: %s"
            % (len(remaining), remaining[0])))

    reviewer = response.get("reviewer") or {}
    if not (_has_text(reviewer.get("name"))
            and _has_text(reviewer.get("professional_qualification"))):
        problems.append(("REVIEWER_NOT_IDENTIFIED",
                         REFUSAL_CODES["REVIEWER_NOT_IDENTIFIED"]))

    signature = response.get("signature") or {}
    if not (_has_text(signature.get("signed_name"))
            and _has_text(signature.get("date"))):
        problems.append(("NOT_SIGNED", REFUSAL_CODES["NOT_SIGNED"]))

    coi = response.get("conflict_of_interest") or {}
    if not _has_text(coi.get("declaration")):
        problems.append(("CONFLICT_OF_INTEREST_NOT_DECLARED",
                         REFUSAL_CODES["CONFLICT_OF_INTEREST_NOT_DECLARED"]))

    consent = response.get("consent") or {}
    if not consent or all(not _has_text(str(value))
                          for value in consent.values()):
        problems.append(("CONSENT_NOT_RECORDED",
                         REFUSAL_CODES["CONSENT_NOT_RECORDED"]))

    if not (_has_text(response.get("reviewed_release_public_id"))
            and _has_text(response.get("reviewed_frozen_combined_hash"))):
        problems.append(("RELEASE_BINDING_ABSENT",
                         REFUSAL_CODES["RELEASE_BINDING_ABSENT"]))

    answered = any(
        _has_text(entry.get("answer"))
        for entry in response.get("questionnaire") or ()
        if isinstance(entry, Mapping))
    answered = answered or _has_text(response.get(
        "overall_free_text_criticism"))
    answered = answered or bool(response.get("reserved_case_answers"))
    if not answered:
        problems.append(("NOTHING_ANSWERED",
                         REFUSAL_CODES["NOTHING_ANSWERED"]))

    return tuple(problems)


def preserved_response(raw: bytes, *, received_relative: str,
                       reviewer_slug: str) -> Dict[str, Any]:
    """The immutable record of what arrived, hashed before anything reads it.

    The hash is of the bytes received. It is never recomputed from a parsed
    and re-serialised copy, because that would hash what this project made of
    the response rather than the response.
    """
    return {
        "schema_version": PRESERVED_VERSION,
        "reviewer_slug": reviewer_slug,
        "received_artifact": received_relative,
        "byte_length": len(raw),
        "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "immutability_note": (
            "This record is the response as received. Corrections are "
            "appended as separate records with their own author and instant; "
            "this file is never edited, and the hash above is of the bytes "
            "that arrived, not of any re-serialisation of them."),
    }


def extract_feedback_items(response: Mapping[str, Any], *,
                           reviewer_slug: str) -> Tuple[Dict[str, Any], ...]:
    """One item per discrete point the reviewer actually made.

    Every item carries the verbatim text it came from and the JSON path it
    was read from. There is no branch that constructs an item without those,
    so an item that no reviewer wrote cannot be produced by this function.

    Impact, safety and disposition are left :data:`HUMAN_REQUIRED`. Deciding
    them is the project's judgement, and inferring one from the reviewer's
    wording would put words in their mouth.
    """
    items: List[Dict[str, Any]] = []

    def add(kind: str, source_path: str, text: str,
            reviewer_severity: Any = None,
            reviewer_priority: Any = None,
            subject: Optional[str] = None) -> None:
        if not _has_text(text):
            return
        items.append({
            "item_id": "WPC14B-%s-%03d" % (reviewer_slug.upper(),
                                           len(items) + 1),
            "kind": kind,
            "source_path": source_path,
            "source_text_verbatim": text,
            "subject": subject,
            "reviewer_severity": reviewer_severity,
            "reviewer_correction_priority": reviewer_priority,
            "impact_class": HUMAN_REQUIRED,
            "safety_class": HUMAN_REQUIRED,
            "source_location": HUMAN_REQUIRED,
            "disposition": HUMAN_REQUIRED,
            "disposition_rationale": HUMAN_REQUIRED,
        })

    for index, entry in enumerate(response.get("questionnaire") or ()):
        if not isinstance(entry, Mapping):
            continue
        add("QUESTIONNAIRE_ANSWER",
            "questionnaire[%d].answer" % index,
            entry.get("answer", ""),
            entry.get("severity"), entry.get("correction_priority"),
            subject=entry.get("question_id"))

    reserved = response.get("reserved_case_answers") or {}
    if isinstance(reserved, Mapping):
        for case_id in sorted(reserved):
            answers = reserved[case_id]
            if not isinstance(answers, Mapping):
                continue
            add("RESERVED_CASE_PRODUCT_ANSWER",
                "reserved_case_answers.%s.reviewer_answer_to_the_question"
                % case_id,
                answers.get("reviewer_answer_to_the_question", ""),
                subject=case_id)
            add("RESERVED_CASE_DISAGREEMENT",
                "reserved_case_answers.%s.reviewer_expected_attention"
                % case_id,
                answers.get("reviewer_expected_attention", ""),
                subject=case_id)
            add("UNSAFE_OUTPUT_REPORT",
                "reserved_case_answers.%s.reviewer_unsafe_output_note"
                % case_id,
                answers.get("reviewer_unsafe_output_note", ""),
                subject=case_id)

    for index, entry in enumerate(
            response.get("unsafe_or_misleading_outputs") or ()):
        if isinstance(entry, Mapping):
            text = entry.get("why_unsafe") or entry.get("description") or ""
            add("UNSAFE_OUTPUT_REPORT",
                "unsafe_or_misleading_outputs[%d]" % index, text,
                entry.get("severity"), subject=entry.get("input"))
        else:
            add("UNSAFE_OUTPUT_REPORT",
                "unsafe_or_misleading_outputs[%d]" % index, str(entry))

    add("FREE_TEXT", "overall_free_text_criticism",
        response.get("overall_free_text_criticism", ""))

    return tuple(items)


def affected_tests_for(impact_class: str) -> Tuple[str, ...]:
    """The declared regression selection for one impact class."""
    return AFFECTED_TEST_MAP.get(impact_class, ())


def benchmark_rerun_decision(items: Sequence[Mapping[str, Any]]
                             ) -> Dict[str, Any]:
    """Whether the internal benchmark must run again, and why.

    Fails towards rerunning. An item whose impact or safety class has not been
    decided counts as requiring a rerun, so an undecided register cannot
    produce a decision not to re-measure.
    """
    undecided = [item["item_id"] for item in items
                 if item.get("impact_class") == HUMAN_REQUIRED
                 or item.get("safety_class") == HUMAN_REQUIRED]
    safety = [item["item_id"] for item in items
              if item.get("safety_class") in _FORCES_RERUN]
    executable = [item["item_id"] for item in items
                  if item.get("impact_class") in _EXECUTABLE_IMPACT]

    if not items:
        return {"rerun_required": False,
                "reason": "no feedback items exist; there is nothing to "
                          "re-measure and no review has been received",
                "undecided_item_ids": [], "safety_item_ids": [],
                "executable_item_ids": []}
    return {
        "rerun_required": bool(undecided or safety or executable),
        "reason": ("undecided classification" if undecided else
                   "a safety-classified correction" if safety else
                   "a correction that changes what the engine computes"
                   if executable else
                   "no item changes executable behaviour"),
        "undecided_item_ids": sorted(undecided),
        "safety_item_ids": sorted(safety),
        "executable_item_ids": sorted(executable),
    }


def correction_impact_matrix(items: Sequence[Mapping[str, Any]]
                             ) -> Dict[str, Any]:
    """Item → impact → affected tests → rerun decision, in one artifact."""
    rows = []
    for item in items:
        impact = item.get("impact_class")
        rows.append({
            "item_id": item["item_id"],
            "subject": item.get("subject"),
            "impact_class": impact,
            "safety_class": item.get("safety_class"),
            "disposition": item.get("disposition"),
            "source_location": item.get("source_location"),
            "affected_tests": list(affected_tests_for(impact))
            if impact != HUMAN_REQUIRED else [],
            "affected_tests_note": (
                "not selectable until impact_class is decided"
                if impact == HUMAN_REQUIRED else ""),
        })
    return {
        "schema_version": MATRIX_VERSION,
        "item_count": len(rows),
        "rows": rows,
        "benchmark_rerun": benchmark_rerun_decision(items),
        "before_metrics": HUMAN_REQUIRED if items else None,
        "after_metrics": HUMAN_REQUIRED if items else None,
        "representative_regression_demonstration":
            HUMAN_REQUIRED if items else None,
    }


def empty_register(*, reason: str) -> Dict[str, Any]:
    """The feedback register with nothing in it, and why."""
    return {
        "schema_version": REGISTER_VERSION,
        "state": "AWAITING_GENUINE_EXTERNAL_EXPERT_RESPONSE",
        "item_count": 0,
        "items": [],
        "reviewers": [],
        "preserved_responses": [],
        "empty_because": reason,
        "dispositions_vocabulary": dict(DISPOSITIONS),
        "impact_classes_vocabulary": dict(IMPACT_CLASSES),
        "safety_classes_vocabulary": dict(SAFETY_CLASSES),
        "feedback_kinds_vocabulary": dict(FEEDBACK_KINDS),
        "refusal_codes": dict(REFUSAL_CODES),
        "may_not": [
            "A feedback item may not be created without a preserved response "
            "file behind it.",
            "A disposition may not be recorded without a written rationale.",
            "A reviewer's text may not be edited; corrections are appended.",
            "A correction may not be implemented before its item exists.",
        ],
    }


def empty_matrix(*, reason: str) -> Dict[str, Any]:
    matrix = correction_impact_matrix(())
    matrix["state"] = "AWAITING_GENUINE_EXTERNAL_EXPERT_RESPONSE"
    matrix["empty_because"] = reason
    return matrix
