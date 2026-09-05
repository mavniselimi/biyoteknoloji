"""The drug and gene catalogues for the pinned release.

Both routes resolve the release once, hand the governed artifacts to the
adapter, and return what it builds. Neither ranks, scores, filters by
attention or resolves a name: ordering is canonical-key order and the only
thing it means is alphabetical.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends

from apps.api.adapters.catalog import (drug_collection_document,
                                       gene_collection_document)
from apps.api.contracts.models import model_type
from apps.api.dependencies import (ServiceProvider, get_provider, parameter,
                                   require_access)
from apps.api.routes import operation

router = APIRouter(tags=["catalogue"])

_DRUGS = operation("listDrugs")
_GENES = operation("listGenes")


@router.get(_DRUGS.path, operation_id=_DRUGS.operation_id,
            status_code=_DRUGS.success_status,
            response_model=model_type(_DRUGS.response_model),
            summary=_DRUGS.summary, description=_DRUGS.description)
async def list_drugs(
        page_size: int = parameter(_DRUGS, "page_size"),
        cursor: Optional[str] = parameter(_DRUGS, "cursor"),
        principal: Any = Depends(require_access(_DRUGS.access,
                                                _DRUGS.operation_id)),
        provider: ServiceProvider = Depends(get_provider)) -> Any:
    pinned = provider.require_release()
    return drug_collection_document(
        manifest=pinned.coverage_manifest, provenance=pinned.provenance,
        drug_keys=pinned.drug_catalogue, aliases=provider.aliases_for_drugs(),
        page_size=page_size, cursor_token=cursor)


@router.get(_GENES.path, operation_id=_GENES.operation_id,
            status_code=_GENES.success_status,
            response_model=model_type(_GENES.response_model),
            summary=_GENES.summary, description=_GENES.description)
async def list_genes(
        page_size: int = parameter(_GENES, "page_size"),
        cursor: Optional[str] = parameter(_GENES, "cursor"),
        principal: Any = Depends(require_access(_GENES.access,
                                                _GENES.operation_id)),
        provider: ServiceProvider = Depends(get_provider)) -> Any:
    pinned = provider.require_release()
    return gene_collection_document(
        manifest=pinned.coverage_manifest, provenance=pinned.provenance,
        page_size=page_size, cursor_token=cursor)
