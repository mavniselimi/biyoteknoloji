"""The active release and the versions it pins.

Public, because a version endpoint that required a principal would be
unreadable by the monitoring that most needs it, and because everything it
reports is a governed identity rather than anything about a case.

The pointer is read once, by the release resolver, and every field of the
response comes from that single pinned context.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from apps.api.adapters.version import system_version_document
from apps.api.contracts.models import model_type
from apps.api.dependencies import ServiceProvider, get_provider, require_access
from apps.api.routes import operation

router = APIRouter(tags=["system"])

_VERSION = operation("getSystemVersion")


@router.get(_VERSION.path, operation_id=_VERSION.operation_id,
            status_code=_VERSION.success_status,
            response_model=model_type(_VERSION.response_model),
            summary=_VERSION.summary, description=_VERSION.description)
async def get_system_version(
        principal: Any = Depends(require_access(_VERSION.access,
                                                _VERSION.operation_id)),
        provider: ServiceProvider = Depends(get_provider)) -> Any:
    pinned = provider.require_release()
    return system_version_document(pinned.provenance,
                                   claim_boundary=provider.claim_boundary)
