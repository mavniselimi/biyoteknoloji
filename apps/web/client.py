"""The one boundary between the interface and the application.

Route handlers depend on :class:`PgxApiClient` and on nothing else. They do
not import an engine, a repository, an ORM model or a legacy module, and they
cannot: the port exposes seven operations, each returning a document that has
already been checked against the WP-16 response contract.

**Every response is validated before a page is built.** Not because the API is
untrusted, but because the alternative is a page that renders whatever it was
given. A field renamed on one side and not the other would otherwise surface
as a blank cell where a governed code belongs - which is invisible in review
and reads as "nothing to report".

**A failure is never an empty success.** Each operation either returns a
validated document or raises :class:`~apps.web.errors.WebError` carrying
WP-16's own code and request id. There is no path that returns ``None`` for a
caller to render around.

Two implementations:

:class:`InProcessApiClient` calls the same WP-16 adapters the API routers
call, in this process, with no HTTP. That is what the interface uses when the
web and the API run in one image - the deployment architecture.md describes -
and it is what makes the whole flow testable in an environment where no ASGI
server can run. It is *not* a shortcut around the contract: it validates every
document it produces against the same models the HTTP path would.

:class:`HttpApiClient` speaks to a running API over HTTPX, for a deployment
that separates them. It is written and cannot be exercised here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from apps.api.contracts.validate import ContractViolation, validate_document
from apps.api.errors import ApiError, map_exception
from apps.web.errors import WebError
from pgx.application.execution_context import (ExecutionChannel,
                                               ExecutionContext)

__all__ = [
    "CLIENT_PORT_VERSION",
    "ClientResponse",
    "HttpApiClient",
    "InProcessApiClient",
    "PgxApiClient",
    "UnavailableApiClient",
]

CLIENT_PORT_VERSION = "pgx-web-api-client/1"

#: The operations the interface needs, and the response model each returns.
#:
#: A closed list. The UI cannot reach an API route that is not here, so
#: widening what a page can ask for is a visible change in one place.
CLIENT_OPERATIONS: Mapping[str, str] = {
    "create_assessment": "AssessmentResponse",
    "get_assessment": "AssessmentResponse",
    "list_drugs": "DrugCollectionResponse",
    "list_genes": "GeneCollectionResponse",
    "get_evidence": "EvidenceDetailResponse",
    "get_system_version": "SystemVersionResponse",
    "get_readiness": "ReadinessResponse",
}


@dataclass(frozen=True, slots=True)
class ClientResponse:
    """One validated API document, with the correlation id that produced it."""

    model: str
    document: Mapping[str, Any]
    request_id: str

    def __post_init__(self) -> None:
        if self.model not in set(CLIENT_OPERATIONS.values()):
            raise ValueError("unexpected response model %r" % self.model)


class PgxApiClient:
    """Port: the seven operations the interface may perform.

    Deliberately narrower than the API. There is no way to reach the
    expert-review paths through this port at all: they refuse, they will be
    replaced by WP-22, and a client method that existed only to receive a 501
    would invite a page to call it and render something.
    """

    def create_assessment(self, document: Mapping[str, Any], *,
                          context: ExecutionContext
                          ) -> ClientResponse:  # pragma: no cover - protocol
        raise NotImplementedError

    def get_assessment(self, assessment_id: str, *, request_id: str
                       ) -> ClientResponse:  # pragma: no cover - protocol
        raise NotImplementedError

    def list_drugs(self, *, request_id: str, page_size: Optional[int] = None,
                   cursor: Optional[str] = None
                   ) -> ClientResponse:  # pragma: no cover - protocol
        raise NotImplementedError

    def list_genes(self, *, request_id: str, page_size: Optional[int] = None,
                   cursor: Optional[str] = None
                   ) -> ClientResponse:  # pragma: no cover - protocol
        raise NotImplementedError

    def get_evidence(self, evidence_id: str, *, request_id: str
                     ) -> ClientResponse:  # pragma: no cover - protocol
        raise NotImplementedError

    def get_system_version(self, *, request_id: str
                           ) -> ClientResponse:  # pragma: no cover - protocol
        raise NotImplementedError

    def get_readiness(self, *, request_id: str
                      ) -> ClientResponse:  # pragma: no cover - protocol
        raise NotImplementedError


def _validated(model: str, document: Mapping[str, Any],
               request_id: str) -> ClientResponse:
    """Check one document against its WP-16 model, or refuse to use it.

    A contract violation here is a server-side inconsistency, not a caller
    error: the API produced a document its own contract rejects. It is
    reported as ``INTERNAL_ERROR`` rather than passed through as a validation
    failure, because a page reader can do nothing about it and the detail
    belongs in a log.
    """
    try:
        validate_document(model, document)
    except ContractViolation as error:
        raise WebError("INTERNAL_ERROR", request_id=request_id,
                       details={"model": model,
                                "issues": [issue.code
                                           for issue in error.issues[:10]]}
                       ) from error
    return ClientResponse(model=model, document=dict(document),
                          request_id=request_id)


def _as_web_error(error: BaseException, request_id: str) -> WebError:
    """Map any application failure to WP-16's own code.

    ``map_exception`` is the API's total mapper, so the code a page shows is
    the code the API would have returned for the same failure. Nothing here
    reads ``str(error)``.
    """
    code, details = map_exception(error)
    safe = {key: value for key, value in details.items()
            if key in ("components", "required_role", "work_package",
                       "limit")}
    return WebError(code, request_id=request_id, details=safe)


class UnavailableApiClient(PgxApiClient):
    """A client for a deployment that has no application to talk to.

    Every operation raises the typed unavailability rather than returning an
    empty document. It exists so that composing a web application without an
    API is a supported configuration whose pages say what is missing - not an
    import error, and not a set of blank screens.
    """

    def __init__(self, code: str = "SERVICE_NOT_READY") -> None:
        self._code = code

    def _refuse(self, request_id: str) -> ClientResponse:
        raise WebError(self._code, request_id=request_id,
                       details={"components": ["application"]})

    def create_assessment(self, document, *, context):
        del document, context
        return self._refuse(getattr(context, "request_id", "") or "")

    def get_assessment(self, assessment_id, *, request_id):
        del assessment_id
        return self._refuse(request_id)

    def list_drugs(self, *, request_id, page_size=None, cursor=None):
        del page_size, cursor
        return self._refuse(request_id)

    def list_genes(self, *, request_id, page_size=None, cursor=None):
        del page_size, cursor
        return self._refuse(request_id)

    def get_evidence(self, evidence_id, *, request_id):
        del evidence_id
        return self._refuse(request_id)

    def get_system_version(self, *, request_id):
        return self._refuse(request_id)

    def get_readiness(self, *, request_id):
        return self._refuse(request_id)


class InProcessApiClient(PgxApiClient):
    """The API, called in this process, through its own adapters.

    Composed with a :class:`~apps.api.dependencies.ServiceProvider` - the same
    object the API routers are composed with - so "what the UI can reach" and
    "what the API can serve" are one configuration. A deployment with no
    database produces the same typed unavailability here as it does over HTTP.

    The adapter functions used are exactly the ones the API routers use;
    ``tests/unit/web/test_client.py`` asserts that set is identical, so this
    path and the HTTP path cannot drift into producing different documents.
    """

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    # -- assessments ------------------------------------------------------

    def create_assessment(self, document: Mapping[str, Any], *,
                          context: ExecutionContext) -> ClientResponse:
        from apps.api.adapters.assessment import assessment_document_from_result
        from apps.api.adapters.request import adapt_assessment_request
        from pgx.application.assessment_snapshot import build_input_snapshot

        request_id = context.request_id or ""
        try:
            assessment_input = adapt_assessment_request(document)
            service = self._provider.require_assessment_service()
            result = service.execute(assessment_input, context=context)
            page_document = assessment_document_from_result(
                result, input_snapshot=build_input_snapshot(assessment_input))
        except Exception as error:  # noqa: BLE001 - mapped, never displayed
            raise _as_web_error(error, request_id) from error
        return _validated("AssessmentResponse", page_document, request_id)

    def get_assessment(self, assessment_id: str, *,
                       request_id: str) -> ClientResponse:
        from apps.api.adapters.assessment import (
            assessment_document_from_read_model)
        from pgx.domain.identifiers import AssessmentId

        try:
            reader = self._provider.require_assessment_reader()
            read_model = reader.read_model(AssessmentId.parse(assessment_id))
            if read_model is None:
                raise WebError("ASSESSMENT_NOT_FOUND", request_id=request_id)
            page_document = assessment_document_from_read_model(read_model)
        except WebError:
            raise
        except Exception as error:  # noqa: BLE001
            raise _as_web_error(error, request_id) from error
        return _validated("AssessmentResponse", page_document, request_id)

    # -- catalogues -------------------------------------------------------

    def list_drugs(self, *, request_id: str, page_size: Optional[int] = None,
                   cursor: Optional[str] = None) -> ClientResponse:
        from apps.api.adapters.catalog import drug_collection_document

        try:
            pinned = self._provider.require_release()
            page_document = drug_collection_document(
                manifest=pinned.coverage_manifest,
                provenance=pinned.provenance,
                drug_keys=pinned.drug_catalogue,
                aliases=self._provider.aliases_for_drugs(),
                page_size=page_size, cursor_token=cursor)
        except Exception as error:  # noqa: BLE001
            raise _as_web_error(error, request_id) from error
        return _validated("DrugCollectionResponse", page_document, request_id)

    def list_genes(self, *, request_id: str, page_size: Optional[int] = None,
                   cursor: Optional[str] = None) -> ClientResponse:
        from apps.api.adapters.catalog import gene_collection_document

        try:
            pinned = self._provider.require_release()
            page_document = gene_collection_document(
                manifest=pinned.coverage_manifest,
                provenance=pinned.provenance,
                page_size=page_size, cursor_token=cursor)
        except Exception as error:  # noqa: BLE001
            raise _as_web_error(error, request_id) from error
        return _validated("GeneCollectionResponse", page_document, request_id)

    # -- evidence ---------------------------------------------------------

    def get_evidence(self, evidence_id: str, *,
                     request_id: str) -> ClientResponse:
        from apps.api.adapters.evidence import evidence_detail_document

        try:
            repository = self._provider.require_evidence_repository()
            detail = repository.get(evidence_id)
            if detail is None:
                raise WebError("EVIDENCE_NOT_FOUND", request_id=request_id)
            build = repository.evidence_build_key()
            page_document = evidence_detail_document(
                detail,
                evidence_build_key=build.get("evidence_build_key", ""),
                evidence_build_content_hash=build.get(
                    "evidence_build_content_hash", ""))
        except WebError:
            raise
        except Exception as error:  # noqa: BLE001
            raise _as_web_error(error, request_id) from error
        return _validated("EvidenceDetailResponse", page_document, request_id)

    # -- system -----------------------------------------------------------

    def get_system_version(self, *, request_id: str) -> ClientResponse:
        from apps.api.adapters.version import system_version_document

        try:
            pinned = self._provider.require_release()
            page_document = system_version_document(
                pinned.provenance,
                claim_boundary=self._provider.claim_boundary)
        except Exception as error:  # noqa: BLE001
            raise _as_web_error(error, request_id) from error
        return _validated("SystemVersionResponse", page_document, request_id)

    def get_readiness(self, *, request_id: str) -> ClientResponse:
        from apps.api.readiness import evaluate_readiness

        try:
            page_document = evaluate_readiness(
                self._provider.settings,
                claim_boundary=self._provider.claim_boundary,
                probes=self._provider.readiness_probes)
        except Exception as error:  # noqa: BLE001
            raise _as_web_error(error, request_id) from error
        return _validated("ReadinessResponse", page_document, request_id)


class HttpApiClient(PgxApiClient):
    """The same seven operations over HTTP, for a split deployment.

    Written and never exercised in this environment: HTTPX is not installed
    here, so no request from this class has been issued. It validates the
    documents it receives against the same models the in-process client does,
    and it preserves the server's ``X-Request-ID`` rather than generating one
    - a correlation id invented by the client would name a call the server
    never logged.
    """

    def __init__(self, base_url: str, *, transport: Any = None,
                 timeout: float = 10.0,
                 headers: Optional[Mapping[str, str]] = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._timeout = timeout
        self._headers = dict(headers or {})

    def _client(self):  # pragma: no cover - requires httpx
        try:
            import httpx
        except ImportError as error:
            raise WebError("SERVICE_NOT_READY",
                           details={"components": ["http_client"]}) from error
        return httpx.Client(base_url=self._base_url, timeout=self._timeout,
                            transport=self._transport,
                            headers=self._headers)

    def _request(self, method: str, path: str, *, model: str,
                 request_id: str, json: Any = None,
                 params: Optional[Mapping[str, Any]] = None
                 ) -> ClientResponse:  # pragma: no cover - requires httpx
        from apps.api.request_id import REQUEST_ID_HEADER

        headers = {REQUEST_ID_HEADER: request_id} if request_id else {}
        with self._client() as client:
            response = client.request(method, path, json=json, params=params,
                                      headers=headers)
        correlation = response.headers.get(REQUEST_ID_HEADER, request_id)
        document = response.json()
        if response.status_code >= 400:
            body = (document or {}).get("error") or {}
            raise WebError(str(body.get("code") or "INTERNAL_ERROR"),
                           request_id=str(body.get("request_id")
                                          or correlation))
        return _validated(model, document, correlation)

    def create_assessment(self, document, *, context):  # pragma: no cover
        return self._request("POST", "/api/v1/assessments",
                             model="AssessmentResponse",
                             request_id=context.request_id or "",
                             json=dict(document))

    def get_assessment(self, assessment_id, *, request_id):  # pragma: no cover
        return self._request("GET", "/api/v1/assessments/%s" % assessment_id,
                             model="AssessmentResponse",
                             request_id=request_id)

    def list_drugs(self, *, request_id, page_size=None,
                   cursor=None):  # pragma: no cover
        params = {key: value for key, value in
                  (("page_size", page_size), ("cursor", cursor))
                  if value is not None}
        return self._request("GET", "/api/v1/drugs",
                             model="DrugCollectionResponse",
                             request_id=request_id, params=params)

    def list_genes(self, *, request_id, page_size=None,
                   cursor=None):  # pragma: no cover
        params = {key: value for key, value in
                  (("page_size", page_size), ("cursor", cursor))
                  if value is not None}
        return self._request("GET", "/api/v1/genes",
                             model="GeneCollectionResponse",
                             request_id=request_id, params=params)

    def get_evidence(self, evidence_id, *, request_id):  # pragma: no cover
        return self._request("GET", "/api/v1/evidence/%s" % evidence_id,
                             model="EvidenceDetailResponse",
                             request_id=request_id)

    def get_system_version(self, *, request_id):  # pragma: no cover
        return self._request("GET", "/api/v1/system/version",
                             model="SystemVersionResponse",
                             request_id=request_id)

    def get_readiness(self, *, request_id):  # pragma: no cover
        return self._request("GET", "/health/ready",
                             model="ReadinessResponse",
                             request_id=request_id)
