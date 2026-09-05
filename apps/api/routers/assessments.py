"""Create and read assessments.

``POST`` performs the §8 sequence and nothing else: a validated document
becomes a canonical input, the service executes it exactly once, and a
response is built from what was stored. There is no ``dry_run`` before the
``execute``, no retry after an unknown failure, and no release resolution
here - the service pins the release, reading the active pointer once, and this
router never sees a pointer at all.

``GET`` reads through the lossless read model. It runs no engine, consults no
active pointer and re-derives nothing: an assessment stored against a release
that has since been superseded comes back reporting the release it was pinned
to, because that is what was true when it was calculated.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from apps.api.adapters.assessment import (assessment_document_from_read_model,
                                          assessment_document_from_result)
from apps.api.adapters.request import adapt_assessment_request
from apps.api.contracts.models import model_type
from apps.api.dependencies import (ServiceProvider, get_execution_context,
                                   get_provider, parameter, require_access)
from apps.api.errors import NotFoundError
from apps.api.routes import operation
from pgx.application.assessment_snapshot import build_input_snapshot
from pgx.domain.identifiers import AssessmentId

router = APIRouter(tags=["assessments"])

_CREATE = operation("createAssessment")
_READ = operation("getAssessment")


@router.post(_CREATE.path, operation_id=_CREATE.operation_id,
             status_code=_CREATE.success_status,
             response_model=model_type(_CREATE.response_model),
             summary=_CREATE.summary, description=_CREATE.description)
async def create_assessment(
        request: Request,
        response: Response,
        body: model_type(_CREATE.request_model),  # type: ignore[valid-type]
        principal: Any = Depends(require_access(_CREATE.access,
                                                _CREATE.operation_id)),
        provider: ServiceProvider = Depends(get_provider)) -> Any:
    # 1-2. The request id is already established by the middleware and the
    #      principal by the dependency above; both come from the server.
    context = get_execution_context(request, principal)

    # 3-4. Strict validation happened in the model; the adapter turns the
    #      validated document into the canonical input using the governed
    #      normaliser and builder.
    payload = body.model_dump(mode="json", exclude_unset=False)
    assessment_input = adapt_assessment_request(payload)

    # 5-7. One call. The service pins the release once, calculates, and
    #      persists the assessment, its children and its audit event in one
    #      transaction, or raises. A failure leaves nothing stored and is not
    #      retried here: retrying an unknown failure is how one request
    #      becomes two assessments.
    service = provider.require_assessment_service()
    result = service.execute(assessment_input, context=context)

    # 8-10. Built only after persistence, from the exact stored facts, with
    #       the canonical warning attached by the adapter.
    document = assessment_document_from_result(
        result, input_snapshot=build_input_snapshot(assessment_input))
    response.headers["Location"] = "%s/%s" % (_CREATE.path,
                                              document["assessment_id"])
    return document


@router.get(_READ.path, operation_id=_READ.operation_id,
            status_code=_READ.success_status,
            response_model=model_type(_READ.response_model),
            summary=_READ.summary, description=_READ.description)
async def get_assessment(
        assessment_id: str = parameter(_READ, "assessment_id"),
        principal: Any = Depends(require_access(_READ.access,
                                                _READ.operation_id)),
        provider: ServiceProvider = Depends(get_provider)) -> Any:
    reader = provider.require_assessment_reader()
    read_model = reader.read_model(AssessmentId.parse(assessment_id))
    if read_model is None:
        raise NotFoundError("ASSESSMENT_NOT_FOUND")
    return assessment_document_from_read_model(read_model)
