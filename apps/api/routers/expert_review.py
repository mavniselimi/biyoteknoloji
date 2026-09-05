# -*- coding: utf-8 -*-
"""The expert-review surface, service-backed (WP-22).

These six routes were three 501 stubs until WP-22. They now execute the blind
protocol through :class:`~pgx.expert_review.service.ExpertReviewService`, and
the properties the stubs were written to preserve are preserved by the real
implementation rather than by doing nothing:

**Role first, store second.** ``require_access`` runs before any handler body,
so a caller without the exact ``EXPERT_REVIEWER`` role never reaches a lookup.
The refusal therefore cannot differ in timing by whether a case exists.

**One refusal for three conditions.** An unknown case, a case that is not
expert-holdout, and a case assigned to somebody else all return
``EXPERT_REVIEW_NOT_ASSIGNED`` with an empty details map. Three distinguishable
codes would be an enumeration tool for the holdout set.

**No result before a reveal.** ``ExpertReviewStateResponse`` has no result
field - not optional, not nullable. The pre-reveal shape cannot carry one, so
no serialisation mistake can leak one.

**Identity comes from the principal.** Actor, role, timestamps, status and
every hash come from the authenticated principal and the stored assignment. A
body supplying one is refused, not stripped.

**Fail closed.** With no review service configured - this repository's state -
every route answers ``EXPERT_REVIEW_NOT_AVAILABLE`` (503) having consulted
nothing.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from fastapi import APIRouter, Depends

from apps.api.contracts.models import model_type
from apps.api.dependencies import get_provider, parameter, require_access
from apps.api.errors import ApiError, ExpertReviewApiError
from apps.api.routes import operation

router = APIRouter(tags=["expert-review"])

_LIST = operation("listExpertReviewAssignments")
_STATE = operation("getExpertReviewState")
_EXPECTED = operation("submitExpertReviewExpected")
_REVEAL = operation("revealExpertReviewResult")
_COMPLETE = operation("completeExpertReview")
_CORRECTION = operation("appendExpertReviewCorrection")


def _service(provider: Any) -> Any:
    """The review service, or a fail-closed refusal.

    ``None`` is the configured state of this repository: no review store and
    no result port exist. Refusing here means no route consults anything, so
    the 503 cannot vary by case.
    """
    service = getattr(provider, "expert_review_service", None)
    if service is None or not getattr(service, "available", False):
        raise ExpertReviewApiError(
            "EXPERT_REVIEW_NOT_AVAILABLE",
            details={"components": ["expert_review_service"]})
    return service


def _translate(error: Exception) -> ApiError:
    """Carry a domain refusal out as its own code, or fail closed.

    A domain code that the API catalogue does not know becomes
    ``EXPERT_REVIEW_NOT_AVAILABLE`` rather than an internal error: an unmapped
    refusal is a gap in this translation, and answering 503 keeps the caller
    from acting on a condition nobody described.
    """
    from apps.api.errors import ERROR_CATALOGUE
    code = getattr(error, "code", None)
    if code in ERROR_CATALOGUE:
        return ExpertReviewApiError(code, details=_safe_details(error))
    return ExpertReviewApiError("EXPERT_REVIEW_NOT_AVAILABLE")


def _safe_details(error: Exception) -> Mapping[str, Any]:
    """Only bounded, non-disclosing details reach a client.

    The domain never puts case content or expert content in its details, and
    this is the second line: a details map is serialised to whoever called,
    and "belt and braces" is cheap where the cost of being wrong is a leaked
    expectation.
    """
    details = dict(getattr(error, "details", {}) or {})
    permitted = {"fields", "components", "permitted", "from", "to"}
    return {key: value for key, value in details.items() if key in permitted}


def _body(model: Any) -> Dict[str, Any]:
    """A request model as a plain mapping, with unset fields omitted.

    ``exclude_unset`` matters: a field the caller did not send must not arrive
    at the domain as an explicit ``None``, because the domain distinguishes
    "not supplied" from "supplied as null" for the optional expectation
    fields.
    """
    return model.model_dump(exclude_unset=True)


@router.get(_LIST.path, operation_id=_LIST.operation_id,
            status_code=_LIST.success_status,
            response_model=model_type(_LIST.response_model),
            summary=_LIST.summary, description=_LIST.description)
async def list_assignments(
        principal: Any = Depends(require_access(_LIST.access,
                                                _LIST.operation_id)),
        provider: Any = Depends(get_provider)) -> Any:
    service = _service(provider)
    try:
        assignments = service.assignments_for(actor=principal.actor,
                                              role=principal.role.value)
    except Exception as error:  # noqa: BLE001 - translated below
        raise _translate(error) from error
    return {"assignments": [item for item in assignments],
            "count": len(assignments)}


@router.get(_STATE.path, operation_id=_STATE.operation_id,
            status_code=_STATE.success_status,
            response_model=model_type(_STATE.response_model),
            summary=_STATE.summary, description=_STATE.description)
async def get_state(
        case_id: str = parameter(_STATE, "case_id"),
        principal: Any = Depends(require_access(_STATE.access,
                                                _STATE.operation_id)),
        provider: Any = Depends(get_provider)) -> Any:
    service = _service(provider)
    try:
        view = service.view(case_id=case_id, actor=principal.actor,
                            role=principal.role.value)
    except Exception as error:  # noqa: BLE001
        raise _translate(error) from error
    payload = view.to_json()
    # The response model has no result field, so a post-reveal result is
    # dropped here rather than rejected by serialisation. A reviewer wanting
    # the result calls reveal, which is the operation that records that they
    # saw it.
    payload.pop("result", None)
    payload.pop("revealed_at", None)
    payload.pop("decision", None)
    payload.pop("case_role", None)
    return payload


@router.post(_EXPECTED.path, operation_id=_EXPECTED.operation_id,
             status_code=_EXPECTED.success_status,
             response_model=model_type(_EXPECTED.response_model),
             summary=_EXPECTED.summary, description=_EXPECTED.description)
async def submit_expected(
        body: model_type(_EXPECTED.request_model),  # type: ignore[valid-type]
        case_id: str = parameter(_EXPECTED, "case_id"),
        principal: Any = Depends(require_access(_EXPECTED.access,
                                                _EXPECTED.operation_id)),
        provider: Any = Depends(get_provider)) -> Any:
    service = _service(provider)
    try:
        expectation = service.record_expectation(
            case_id=case_id, actor=principal.actor,
            role=principal.role.value, body=_body(body))
    except Exception as error:  # noqa: BLE001
        raise _translate(error) from error
    return {
        "review_id": expectation.review_id,
        "revision_id": expectation.revision_id,
        "revision": expectation.revision,
        "recorded_at": expectation.recorded_at.isoformat().replace(
            "+00:00", "Z"),
        "content_hash": expectation.content_hash(),
        "revision_hash": expectation.revision_hash(),
        "state": "EXPECTATION_RECORDED",
    }


@router.post(_REVEAL.path, operation_id=_REVEAL.operation_id,
             status_code=_REVEAL.success_status,
             response_model=model_type(_REVEAL.response_model),
             summary=_REVEAL.summary, description=_REVEAL.description)
async def reveal_result(
        body: model_type(_REVEAL.request_model),  # type: ignore[valid-type]
        case_id: str = parameter(_REVEAL, "case_id"),
        principal: Any = Depends(require_access(_REVEAL.access,
                                                _REVEAL.operation_id)),
        provider: Any = Depends(get_provider)) -> Any:
    service = _service(provider)
    try:
        reveal = service.reveal(case_id=case_id, actor=principal.actor,
                                role=principal.role.value, body=_body(body))
    except Exception as error:  # noqa: BLE001
        raise _translate(error) from error
    return {
        "review_id": reveal.review_id,
        "reveal_id": reveal.reveal_id,
        "expectation_revision_id": reveal.expectation_revision_id,
        "expectation_revision_hash": reveal.expectation_revision_hash,
        "revealed_at": reveal.revealed_at.isoformat().replace("+00:00", "Z"),
        "reveal_hash": reveal.reveal_hash(),
        "state": "RESULT_REVEALED",
        "result": reveal.result(),
    }


@router.post(_COMPLETE.path, operation_id=_COMPLETE.operation_id,
             status_code=_COMPLETE.success_status,
             response_model=model_type(_COMPLETE.response_model),
             summary=_COMPLETE.summary, description=_COMPLETE.description)
async def complete_review(
        body: model_type(_COMPLETE.request_model),  # type: ignore[valid-type]
        case_id: str = parameter(_COMPLETE, "case_id"),
        principal: Any = Depends(require_access(_COMPLETE.access,
                                                _COMPLETE.operation_id)),
        provider: Any = Depends(get_provider)) -> Any:
    service = _service(provider)
    payload = _body(body)
    # The wire shape is a list of {dimension, value}; the domain takes a map.
    # Converted here rather than in the domain, because the list shape exists
    # for JSON schema reasons and the domain should not know about them.
    ratings = {item["dimension"]: item["value"]
               for item in payload.pop("ratings", ()) or ()}
    payload["ratings"] = ratings
    try:
        completion = service.complete(case_id=case_id, actor=principal.actor,
                                      role=principal.role.value,
                                      body=payload)
    except Exception as error:  # noqa: BLE001
        raise _translate(error) from error
    return {
        "review_id": completion.review_id,
        "completion_id": completion.completion_id,
        "decision": completion.decision.value,
        # Which dimensions were rated, not the values. A receipt does not need
        # to echo the reviewer's scores back over the wire.
        "rated_dimensions": sorted(completion.rating_map()),
        "completed_at": completion.completed_at.isoformat().replace(
            "+00:00", "Z"),
        "completion_hash": completion.completion_hash(),
        "state": "COMPLETED",
    }


@router.post(_CORRECTION.path, operation_id=_CORRECTION.operation_id,
             status_code=_CORRECTION.success_status,
             response_model=model_type(_CORRECTION.response_model),
             summary=_CORRECTION.summary,
             description=_CORRECTION.description)
async def append_correction(
        body: model_type(_CORRECTION.request_model),  # type: ignore[valid-type]
        case_id: str = parameter(_CORRECTION, "case_id"),
        principal: Any = Depends(require_access(_CORRECTION.access,
                                                _CORRECTION.operation_id)),
        provider: Any = Depends(get_provider)) -> Any:
    service = _service(provider)
    try:
        correction = service.append_correction(
            case_id=case_id, actor=principal.actor,
            role=principal.role.value, body=_body(body))
    except Exception as error:  # noqa: BLE001
        raise _translate(error) from error
    return {
        "review_id": correction.review_id,
        "correction_id": correction.correction_id,
        "kind": correction.kind.value,
        "after_reveal": correction.after_reveal,
        "recorded_at": correction.recorded_at.isoformat().replace(
            "+00:00", "Z"),
        "correction_hash": correction.correction_hash(),
    }
