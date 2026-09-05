"""Read one evidence record by its immutable identity.

The lookup is by record identity in the configured evidence build. A record a
stored assessment cited stays reachable by that identity; it is never
substituted with whatever record now holds the same natural key in a newer
build, because a citation that silently repoints is a citation that cannot be
audited.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from apps.api.adapters.evidence import evidence_detail_document
from apps.api.contracts.models import model_type
from apps.api.dependencies import (ServiceProvider, get_provider, parameter,
                                   require_access)
from apps.api.errors import NotFoundError
from apps.api.routes import operation

router = APIRouter(tags=["evidence"])

_READ = operation("getEvidenceRecord")


@router.get(_READ.path, operation_id=_READ.operation_id,
            status_code=_READ.success_status,
            response_model=model_type(_READ.response_model),
            summary=_READ.summary, description=_READ.description)
async def get_evidence_record(
        evidence_id: str = parameter(_READ, "evidence_id"),
        principal: Any = Depends(require_access(_READ.access,
                                                _READ.operation_id)),
        provider: ServiceProvider = Depends(get_provider)) -> Any:
    repository = provider.require_evidence_repository()
    detail = repository.get(evidence_id)
    if detail is None:
        raise NotFoundError("EVIDENCE_NOT_FOUND")
    build_key = repository.evidence_build_key()
    return evidence_detail_document(
        detail, evidence_build_key=build_key.get("evidence_build_key", ""),
        evidence_build_content_hash=build_key.get(
            "evidence_build_content_hash", ""))
