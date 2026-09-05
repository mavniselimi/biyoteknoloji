"""Liveness and readiness.

``/health/live`` answers from the process. It opens nothing, resolves nothing
and calls nothing external, so it stays 200 while every dependency is down -
which is the point: restarting a working process does not repair a database.

``/health/ready`` runs the component checks and returns 200 only when every
blocking one is ready. In this repository it will report not-ready, because
the claim boundary is unapproved and no release is active. That is the correct
answer and it is not bypassed.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response

from apps.api.contracts.models import model_type
from apps.api.dependencies import ServiceProvider, get_provider, require_access
from apps.api.readiness import evaluate_readiness, liveness_document
from apps.api.routes import operation

router = APIRouter(tags=["health"])

_LIVE = operation("getLiveness")
_READY = operation("getReadiness")


@router.get(_LIVE.path, operation_id=_LIVE.operation_id,
            status_code=_LIVE.success_status,
            response_model=model_type(_LIVE.response_model),
            summary=_LIVE.summary, description=_LIVE.description)
async def get_liveness(
        principal: Any = Depends(require_access(_LIVE.access,
                                                _LIVE.operation_id))) -> Any:
    return liveness_document()


@router.get(_READY.path, operation_id=_READY.operation_id,
            status_code=_READY.success_status,
            response_model=model_type(_READY.response_model),
            summary=_READY.summary, description=_READY.description)
async def get_readiness(
        response: Response,
        principal: Any = Depends(require_access(_READY.access,
                                                _READY.operation_id)),
        provider: ServiceProvider = Depends(get_provider)) -> Any:
    document = evaluate_readiness(provider.settings,
                                  claim_boundary=provider.claim_boundary,
                                  probes=provider.readiness_probes)
    if document["blocking_failures"]:
        response.status_code = 503
    return document
