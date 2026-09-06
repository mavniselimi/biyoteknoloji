# -*- coding: utf-8 -*-
"""The one rendering of a candidate assessment (Wave 4B).

Both surfaces read this. The API edge serves it as JSON and the
server-rendered interface builds its page from the same dictionary, so there
is no second evaluator, no second document shape, and no way for the screen
and the endpoint to describe the same assessment differently.

**Why it is not the governed assessment document.** That document is built by
``apps/api/adapters/assessment.py`` from an ``AssessmentComputation``, verified
against its stored hashes, and refused unless it was persisted. Every one of
those properties is a governed guarantee a candidate result does not have and
must not appear to have: a candidate rule carries no WP-10 approval envelope,
and a candidate assessment is computed and shown rather than stored in the
governed assessment tables. Forcing one into the other's shape would make the
difference invisible exactly where it matters most.

So this document says what it is, in every copy of it: the runtime track, the
provisional authority, the pending review state, and a claim boundary that
reports itself unapproved. A reader who sees only this dictionary still cannot
mistake it for an approved answer.

**Refusals are not absences.** ``reason_codes`` are carried per medication and
per axis, and ``attention_level`` is never used to express one. An axis that
was refused says so with its code; it does not quietly report no attention,
which is the single most dangerous thing this document could do.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from pgx.application.runtime_track import RuntimeTrack

__all__ = [
    "CANDIDATE_ASSESSMENT_DOCUMENT_VERSION",
    "candidate_assessment_document",
    "candidate_assessment_input",
    "candidate_request_to_input",
    "refusal_codes_of",
]

CANDIDATE_ASSESSMENT_DOCUMENT_VERSION = "pgx-candidate-assessment-document/1"


def refusal_codes_of(document: Mapping[str, Any]) -> tuple:
    """Every refusal code in the document, deduplicated and ordered.

    Read by the page that has to show refusals *beside* attention rather than
    instead of it, and by the tests that assert a refusal never arrives as an
    attention level.
    """
    codes = set()
    for medication in document.get("medications", ()):
        codes.update(medication.get("reason_codes") or ())
        for axis in medication.get("axes", ()):
            codes.update(axis.get("reason_codes") or ())
    return tuple(sorted(codes))


def candidate_assessment_document(result: Any, *,
                                  case_id: Optional[str] = None,
                                  input_snapshot: Optional[Mapping[str, Any]]
                                  = None) -> Dict[str, Any]:
    """Serialise one :class:`CandidateAssessmentResult`.

    Args:
        result: what the composed candidate assessment service returned.
        case_id: the development case the request came from, when it came
            from one. Carried so a reader can trace the answer back to the
            question; never invented when absent.
        input_snapshot: the canonical input document, when the caller built
            one. Included verbatim so the question travels with the answer.
    """
    evaluation = result.evaluation.to_json()
    document: Dict[str, Any] = {
        "schema_version": CANDIDATE_ASSESSMENT_DOCUMENT_VERSION,
        "runtime_track": RuntimeTrack.CANDIDATE.value,
        # -- what answered --------------------------------------------------
        "release_public_id": result.release_public_id,
        "manifest_hash": result.manifest_hash,
        "ruleset_key": evaluation["ruleset_key"],
        "ruleset_content_hash": evaluation["ruleset_content_hash"],
        "dataset_public_id": evaluation["dataset_public_id"],
        "evaluation_version": evaluation["evaluation_version"],
        # -- under what authority -------------------------------------------
        "authority_state": result.authority_state,
        "review_state": result.review_state,
        "claim_boundary_status": result.claim_boundary_status,
        "claim_boundary_is_approved": result.claim_boundary_is_approved,
        "governed_registry_note": (
            "This answer came from a candidate release in the candidate-only "
            "lifecycle. It is not registered, approved or published through "
            "the governed WP-13 release registry, and no external expert has "
            "reviewed it."),
        # -- the answer ------------------------------------------------------
        "attention_level": evaluation["attention_level"],
        "status": evaluation["status"],
        "medications": evaluation["medications"],
        "refusal_codes": refusal_codes_of(evaluation),
        # -- identity ---------------------------------------------------------
        "input_hash": result.input_hash,
        "output_hash": result.output_hash,
        "computed_at": result.computed_at.isoformat().replace("+00:00", "Z"),
        "warning": result.warning,
        "case_id": case_id,
    }
    if input_snapshot is not None:
        document["input_snapshot"] = dict(input_snapshot)
    return document


def candidate_assessment_input(payload: Mapping[str, Any], *, profile: Any,
                               mode: Any, input_kind: Any) -> Any:
    """A canonical input for the candidate track, carrying the care setting.

    The governed wire contract has no ``care_setting`` field, and adding one
    to it would change a governed contract for a candidate feature. So the
    candidate path builds its input here instead: through the same
    ``build_assessment_input`` - which is what refuses a VCF path, an EHR
    reference or any other field this product does not accept - and then adds
    the one field the candidate ruleset needs.

    ``care_setting`` is validated by ``AssessmentInput`` itself against
    ``PERMITTED_CARE_SETTINGS``, so an invented context is refused here rather
    than reaching a rule that would ignore it.
    """
    from dataclasses import replace

    from pgx.application.assessment_models import build_assessment_input

    base = build_assessment_input(payload, profile=profile, mode=mode,
                                  input_kind=input_kind)
    care_setting = payload.get("care_setting")
    if care_setting in (None, ""):
        return base
    return replace(base, care_setting=str(care_setting))


def candidate_request_to_input(document: Mapping[str, Any]) -> Any:
    """One request document to one canonical candidate input.

    The whole conversion, in the application layer, because the caller that
    needs it most is the server-rendered interface - and
    ``tests/unit/web/test_wp17_boundaries.py`` forbids that layer from
    importing an engine. It is right to: a page that could normalise a
    phenotype profile is a page that could disagree with the service about
    what the profile means.
    """
    from apps.api.adapters.request import observations_to_mapping
    from pgx.domain.claims import OperationMode, PermittedInputKind
    from pgx.engine.phenotype_normalization import normalize_profile

    profile_document = document["profile"]
    profile = normalize_profile(
        observations_to_mapping(profile_document["observations"]),
        profile_id=profile_document.get("profile_id"),
        contract_version=profile_document.get("input_contract_version")
        or "pgx-phenotype-input/1")
    return candidate_assessment_input(
        document, profile=profile,
        mode=OperationMode(document["mode"]),
        input_kind=PermittedInputKind(document["input_kind"]))
