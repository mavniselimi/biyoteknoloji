"""The P0 surface, declared once.

Every route this API exposes is a row in :data:`ROUTES`. Three things read
that table and nothing else defines them: the FastAPI routers register from
it, the OpenAPI document is generated from it, and the boundary tests assert
against it. Declaring the surface rather than growing it out of decorators is
what makes "is this endpoint documented, authorised and tested?" a question
with a mechanical answer instead of a review question.

The list is closed. §7 of the work package names eleven operations, and a
twelfth added here without a corresponding line in ``docs/api/p0-contract.md``
fails :mod:`tests.unit.api.test_route_surface`. An admin endpoint that is
convenient during development is exactly the kind of thing that survives into
a deployment, so the cost of adding one is deliberately not zero.

Three of the eleven are disabled stubs. The expert-review operations exist as
routes because WP-22 owns the workflow and P0 should not leave their paths
free for something else to claim, and because a documented 501 is a clearer
statement to a client than a 404 that reads as "wrong URL". They enforce
their role before refusing: a route that answered "not implemented" to anyone
would tell an unauthenticated caller which paths exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Tuple

from apps.api import API_ROOT_PATH
from apps.api.contracts.spec import LIMITS
from apps.api.security import PUBLIC, AccessPolicy, Role, roles

__all__ = [
    "HEALTH_OPERATIONS",
    "ParameterSpec",
    "ROUTES",
    "ROUTES_BY_OPERATION",
    "RouteSpec",
    "STUB_OPERATIONS",
    "operation",
]

_ANY_USER = roles(Role.DEMO_USER, Role.EXPERT_REVIEWER, Role.ADMIN)
_REVIEWER = roles(Role.EXPERT_REVIEWER)

_UUID_PATTERN = (r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                 r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_CASE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"

#: Errors every route can produce, so no route has to remember them. A caller
#: reading the generated document sees them on every operation because they
#: are true of every operation, not because they were pasted eleven times.
_UNIVERSAL_ERRORS: Tuple[str, ...] = (
    "REQUEST_MALFORMED",
    "REQUEST_ID_INVALID",
    "INTERNAL_ERROR",
)

_AUTHENTICATED_ERRORS: Tuple[str, ...] = (
    "UNAUTHENTICATED",
    "FORBIDDEN_ROLE",
    "AUTHENTICATION_NOT_CONFIGURED",
)


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    """One path or query parameter, with the bound that makes it safe.

    Every parameter carries either a pattern or a numeric range. An
    unconstrained string parameter reaching a repository is how an identifier
    lookup becomes an injection surface, and an unconstrained integer is how a
    page size becomes a denial of service.
    """

    name: str
    location: str
    kind: str
    required: bool
    description: str
    pattern: Optional[str] = None
    max_length: Optional[int] = None
    minimum: Optional[int] = None
    maximum: Optional[int] = None
    default: Optional[object] = None

    def __post_init__(self) -> None:
        if self.location not in ("path", "query"):
            raise ValueError("a P0 parameter is a path or query parameter")
        if self.kind not in ("string", "integer"):
            raise ValueError("a P0 parameter is a string or an integer")
        if self.kind == "string" and self.pattern is None:
            raise ValueError(
                "a string parameter declares the exact shape it accepts")
        if self.kind == "integer" and (self.minimum is None
                                       or self.maximum is None):
            raise ValueError("an integer parameter declares its range")
        if self.location == "path" and not self.required:
            raise ValueError("a path parameter is always required")


@dataclass(frozen=True, slots=True)
class RouteSpec:
    """One operation: its address, its contracts, and who may reach it."""

    operation_id: str
    method: str
    path: str
    summary: str
    description: str
    tag: str
    access: AccessPolicy
    success_status: int
    response_model: str
    request_model: Optional[str] = None
    parameters: Tuple[ParameterSpec, ...] = ()
    error_codes: Tuple[str, ...] = ()
    implemented: bool = True
    superseded_by: Optional[str] = None
    cache_control: str = "no-store"

    def __post_init__(self) -> None:
        if self.method not in ("GET", "POST"):
            raise ValueError("the P0 surface is GET and POST only")
        if not self.path.startswith("/"):
            raise ValueError("a route path is absolute")
        if self.request_model is not None and self.method == "GET":
            raise ValueError("a GET route carries no request body")
        if not self.implemented and self.superseded_by is None:
            raise ValueError(
                "a disabled route names the work package that replaces it, so "
                "a reader is never left to guess whether it was forgotten")

    @property
    def all_error_codes(self) -> Tuple[str, ...]:
        """Declared errors plus the universal ones, deduplicated and sorted."""
        universal = _UNIVERSAL_ERRORS
        if not self.access.public:
            universal = universal + _AUTHENTICATED_ERRORS
        return tuple(sorted(set(self.error_codes) | set(universal)))

    @property
    def path_parameters(self) -> Tuple[ParameterSpec, ...]:
        return tuple(item for item in self.parameters
                     if item.location == "path")

    @property
    def query_parameters(self) -> Tuple[ParameterSpec, ...]:
        return tuple(item for item in self.parameters
                     if item.location == "query")


_ASSESSMENT_ID = ParameterSpec(
    name="assessment_id", location="path", kind="string", required=True,
    description="The immutable identity of a stored assessment.",
    pattern=_UUID_PATTERN, max_length=36)

_EVIDENCE_ID = ParameterSpec(
    name="evidence_id", location="path", kind="string", required=True,
    description="The immutable record identity of one evidence record.",
    pattern=_UUID_PATTERN, max_length=36)

_CASE_ID = ParameterSpec(
    name="case_id", location="path", kind="string", required=True,
    description="An expert-review case identifier. Not resolved in P0.",
    pattern=_CASE_ID_PATTERN, max_length=64)

_PAGE_SIZE = ParameterSpec(
    name="page_size", location="query", kind="integer", required=False,
    description="Items per page. Bounded; an unbounded catalogue page is a "
                "denial-of-service surface, not a convenience.",
    minimum=1, maximum=LIMITS["max_page_size"], default=LIMITS["default_page_size"])

_CURSOR = ParameterSpec(
    name="cursor", location="query", kind="string", required=False,
    description="An opaque cursor from a previous page of this catalogue. A "
                "cursor is bound to the release that produced it and is "
                "refused against any other.",
    pattern=r"^[A-Za-z0-9_-]{1,%d}$" % LIMITS["max_cursor_length"],
    max_length=LIMITS["max_cursor_length"])


ROUTES: Tuple[RouteSpec, ...] = (
    RouteSpec(
        operation_id="createAssessment",
        method="POST",
        path=API_ROOT_PATH + "/assessments",
        summary="Execute and store one assessment",
        description=(
            "Validates the transport shape, adapts it to the canonical "
            "application input, and invokes the assessment service exactly "
            "once. The release is pinned by the service, not by this route. "
            "A result is returned only after it has been stored."),
        tag="assessments",
        access=_ANY_USER,
        success_status=201,
        request_model="AssessmentCreateRequest",
        response_model="AssessmentResponse",
        error_codes=(
            "REQUEST_TOO_LARGE", "REQUEST_CONTRACT_VIOLATION",
            "PROHIBITED_INPUT_FIELD", "UNSUPPORTED_PHENOTYPE",
            "ASSESSMENT_INPUT_INVALID", "MODE_NOT_PERMITTED",
            "INPUT_KIND_NOT_PERMITTED", "RELEASE_NOT_ACTIVE",
            "CLAIM_BOUNDARY_NOT_APPROVED", "ACTIVE_RELEASE_UNAVAILABLE",
            "DATABASE_UNAVAILABLE", "PERSISTENCE_REFUSED",
            "ARTIFACT_INCONSISTENT", "SERVICE_NOT_READY"),
    ),
    RouteSpec(
        operation_id="getAssessment",
        method="GET",
        path=API_ROOT_PATH + "/assessments/{assessment_id}",
        summary="Read one stored assessment",
        description=(
            "Serialises what was stored, verified against its own hashes. No "
            "engine runs, no rule is re-selected, and the currently active "
            "release is not consulted: the assessment is returned against the "
            "release it was pinned to, whatever is active now."),
        tag="assessments",
        access=_ANY_USER,
        success_status=200,
        response_model="AssessmentResponse",
        parameters=(_ASSESSMENT_ID,),
        error_codes=("ASSESSMENT_NOT_FOUND", "STORED_RESULT_INCONSISTENT",
                     "DATABASE_UNAVAILABLE", "SERVICE_NOT_READY"),
    ),
    RouteSpec(
        operation_id="listDrugs",
        method="GET",
        path=API_ROOT_PATH + "/drugs",
        summary="List the medications the pinned release covers",
        description=(
            "A deterministic page of the canonical drug catalogue, with the "
            "coverage the governed manifest declares for each. Coverage is "
            "read from the manifest, never derived here, and the list is "
            "ordered by canonical key - never by attention, and never by any "
            "score."),
        tag="catalogue",
        access=_ANY_USER,
        success_status=200,
        response_model="DrugCollectionResponse",
        parameters=(_PAGE_SIZE, _CURSOR),
        error_codes=("CURSOR_RELEASE_MISMATCH", "ACTIVE_RELEASE_UNAVAILABLE",
                     "CATALOGUE_UNAVAILABLE", "SERVICE_NOT_READY"),
    ),
    RouteSpec(
        operation_id="listGenes",
        method="GET",
        path=API_ROOT_PATH + "/genes",
        summary="List the genes and phenotype vocabulary the release supports",
        description=(
            "The governed supported genes and the phenotype vocabulary an "
            "observation may use. A gene appears here because the coverage "
            "manifest declares axes for it, which is not the same as full "
            "coverage of every medication that names it."),
        tag="catalogue",
        access=_ANY_USER,
        success_status=200,
        response_model="GeneCollectionResponse",
        parameters=(_PAGE_SIZE, _CURSOR),
        error_codes=("CURSOR_RELEASE_MISMATCH", "ACTIVE_RELEASE_UNAVAILABLE",
                     "CATALOGUE_UNAVAILABLE", "SERVICE_NOT_READY"),
    ),
    RouteSpec(
        operation_id="getEvidenceRecord",
        method="GET",
        path=API_ROOT_PATH + "/evidence/{evidence_id}",
        summary="Read one evidence record's immutable projection",
        description=(
            "Identity, origin and provenance for one evidence record, so a "
            "finding cited on an old assessment stays auditable by identity. "
            "Carries no raw source payload, no filesystem path and no "
            "clinical prose."),
        tag="evidence",
        access=_ANY_USER,
        success_status=200,
        response_model="EvidenceDetailResponse",
        parameters=(_EVIDENCE_ID,),
        error_codes=("EVIDENCE_NOT_FOUND", "EVIDENCE_BUILD_UNAVAILABLE",
                     "ARTIFACT_INCONSISTENT", "SERVICE_NOT_READY"),
    ),
    RouteSpec(
        operation_id="getSystemVersion",
        method="GET",
        path=API_ROOT_PATH + "/system/version",
        summary="The active release and the exact governed versions it pins",
        description=(
            "The active-release pointer is read once for this response. Every "
            "identity and hash reported comes from that one release; two "
            "releases are never combined into one answer."),
        tag="system",
        access=PUBLIC,
        success_status=200,
        response_model="SystemVersionResponse",
        error_codes=("ACTIVE_RELEASE_UNAVAILABLE", "SERVICE_NOT_READY"),
    ),
    RouteSpec(
        operation_id="listExpertReviewAssignments",
        method="GET",
        path=API_ROOT_PATH + "/expert-reviews",
        summary="The calling reviewer's own assignments",
        description=(
            "Returns only assignments held by the authenticated principal. "
            "A reviewer who could list another's would learn which holdout "
            "cases exist and who holds them, which is the linkage a blind "
            "protocol keeps closed."),
        tag="expert-review",
        access=_REVIEWER,
        success_status=200,
        response_model="ExpertReviewAssignmentListResponse",
        error_codes=("EXPERT_REVIEW_NOT_AVAILABLE", "EXPERT_REVIEW_NOT_ASSIGNED",
                     "EXPERT_REVIEW_PROTOCOL_NOT_APPROVED",
                     "EXPERT_REVIEW_INVALID_TRANSITION",
                     "EXPERT_REVIEW_FORGED_FIELD",
                     "EXPERT_REVIEW_ROLE_REQUIRED",
                     "EXPERT_REVIEW_RELEASE_MISMATCH",
                     "EXPERT_REVIEW_CASE_MANIFEST_MISMATCH",
                     "EXPERT_REVIEW_PROTOCOL_MISMATCH",
                     "EXPERT_REVIEW_AUDIT_FAILED"),
    ),
    RouteSpec(
        operation_id="getExpertReviewState",
        method="GET",
        path=API_ROOT_PATH + "/expert-reviews/{case_id}",
        summary="One assignment's state, blinded until reveal",
        description=(
            "The response model has no result field before a reveal exists - "
            "not an optional one and not a nullable one. A hidden value is "
            "still disclosure, so the pre-reveal shape has nowhere to put "
            "one. A missing or foreign assignment returns the same refusal as "
            "an unknown case."),
        tag="expert-review",
        access=_REVIEWER,
        success_status=200,
        response_model="ExpertReviewStateResponse",
        parameters=(_CASE_ID,),
        error_codes=("EXPERT_REVIEW_NOT_AVAILABLE", "EXPERT_REVIEW_NOT_ASSIGNED",
                     "EXPERT_REVIEW_PROTOCOL_NOT_APPROVED",
                     "EXPERT_REVIEW_INVALID_TRANSITION",
                     "EXPERT_REVIEW_FORGED_FIELD",
                     "EXPERT_REVIEW_ROLE_REQUIRED",
                     "EXPERT_REVIEW_RELEASE_MISMATCH",
                     "EXPERT_REVIEW_CASE_MANIFEST_MISMATCH",
                     "EXPERT_REVIEW_PROTOCOL_MISMATCH",
                     "EXPERT_REVIEW_AUDIT_FAILED"),
    ),
    RouteSpec(
        operation_id="submitExpertReviewExpected",
        method="POST",
        path=API_ROOT_PATH + "/expert-reviews/{case_id}/expected",
        summary="Record a reviewer's expected result, before any reveal",
        description=(
            "Locks what the reviewer expects, timestamped by the server and "
            "hashed. A body supplying an actor, a timestamp, a status or any "
            "hash is refused rather than having it stripped: a caller who "
            "tried to set their own timestamp has told you something. There "
            "is no second expectation - a change is an appended correction."),
        tag="expert-review",
        access=_REVIEWER,
        success_status=201,
        request_model="ExpertReviewExpectedRequest",
        response_model="ExpertReviewExpectedResponse",
        parameters=(_CASE_ID,),
        error_codes=("EXPERT_REVIEW_NOT_AVAILABLE", "EXPERT_REVIEW_NOT_ASSIGNED",
                     "EXPERT_REVIEW_PROTOCOL_NOT_APPROVED",
                     "EXPERT_REVIEW_INVALID_TRANSITION",
                     "EXPERT_REVIEW_FORGED_FIELD",
                     "EXPERT_REVIEW_ROLE_REQUIRED",
                     "EXPERT_REVIEW_RELEASE_MISMATCH",
                     "EXPERT_REVIEW_CASE_MANIFEST_MISMATCH",
                     "EXPERT_REVIEW_PROTOCOL_MISMATCH",
                     "EXPERT_REVIEW_AUDIT_FAILED",
                     "EXPERT_REVIEW_EXPECTATION_ALREADY_LOCKED"),
    ),
    RouteSpec(
        operation_id="revealExpertReviewResult",
        method="POST",
        path=API_ROOT_PATH + "/expert-reviews/{case_id}/reveal",
        summary="Reveal the computed result, pinned to the locked expectation",
        description=(
            "Permitted only when an expectation is locked, and only once. The "
            "response records the exact expectation revision hash it pinned, "
            "so a correction appended later cannot retroactively become what "
            "the reviewer predicted. A release or manifest that moved since "
            "assignment refuses the reveal rather than revealing something "
            "else."),
        tag="expert-review",
        access=_REVIEWER,
        success_status=200,
        request_model="ExpertReviewRevealRequest",
        response_model="ExpertReviewRevealResponse",
        parameters=(_CASE_ID,),
        error_codes=("EXPERT_REVIEW_NOT_AVAILABLE", "EXPERT_REVIEW_NOT_ASSIGNED",
                     "EXPERT_REVIEW_PROTOCOL_NOT_APPROVED",
                     "EXPERT_REVIEW_INVALID_TRANSITION",
                     "EXPERT_REVIEW_FORGED_FIELD",
                     "EXPERT_REVIEW_ROLE_REQUIRED",
                     "EXPERT_REVIEW_RELEASE_MISMATCH",
                     "EXPERT_REVIEW_CASE_MANIFEST_MISMATCH",
                     "EXPERT_REVIEW_PROTOCOL_MISMATCH",
                     "EXPERT_REVIEW_AUDIT_FAILED",
                     "EXPERT_REVIEW_EXPECTATION_REQUIRED",
                     "EXPERT_REVIEW_RESULT_ALREADY_REVEALED"),
    ),
    RouteSpec(
        operation_id="completeExpertReview",
        method="POST",
        path=API_ROOT_PATH + "/expert-reviews/{case_id}/complete",
        summary="Close one expert review with a governed decision",
        description=(
            "Accepts exactly AGREE, PARTIAL or DISAGREE plus optional bounded "
            "ratings on declared dimensions. Impossible before a reveal, and "
            "impossible twice. The record is immutable afterwards; later "
            "changes are appended corrections."),
        tag="expert-review",
        access=_REVIEWER,
        success_status=201,
        request_model="ExpertReviewCompleteRequest",
        response_model="ExpertReviewCompleteResponse",
        parameters=(_CASE_ID,),
        error_codes=("EXPERT_REVIEW_NOT_AVAILABLE", "EXPERT_REVIEW_NOT_ASSIGNED",
                     "EXPERT_REVIEW_PROTOCOL_NOT_APPROVED",
                     "EXPERT_REVIEW_INVALID_TRANSITION",
                     "EXPERT_REVIEW_FORGED_FIELD",
                     "EXPERT_REVIEW_ROLE_REQUIRED",
                     "EXPERT_REVIEW_RELEASE_MISMATCH",
                     "EXPERT_REVIEW_CASE_MANIFEST_MISMATCH",
                     "EXPERT_REVIEW_PROTOCOL_MISMATCH",
                     "EXPERT_REVIEW_AUDIT_FAILED",
                     "EXPERT_REVIEW_REVEAL_REQUIRED",
                     "EXPERT_REVIEW_ALREADY_COMPLETED"),
    ),
    RouteSpec(
        operation_id="appendExpertReviewCorrection",
        method="POST",
        path=API_ROOT_PATH + "/expert-reviews/{case_id}/corrections",
        summary="Append an amendment; the corrected record is never touched",
        description=(
            "Corrections append. A correction before a reveal may become the "
            "revision the reveal pins; one after a reveal is annotation only "
            "and cannot change the reference a metric consumes. Nothing here "
            "updates or deletes a stored record."),
        tag="expert-review",
        access=_REVIEWER,
        success_status=201,
        request_model="ExpertReviewCorrectionRequest",
        response_model="ExpertReviewCorrectionResponse",
        parameters=(_CASE_ID,),
        error_codes=("EXPERT_REVIEW_NOT_AVAILABLE", "EXPERT_REVIEW_NOT_ASSIGNED",
                     "EXPERT_REVIEW_PROTOCOL_NOT_APPROVED",
                     "EXPERT_REVIEW_INVALID_TRANSITION",
                     "EXPERT_REVIEW_FORGED_FIELD",
                     "EXPERT_REVIEW_ROLE_REQUIRED",
                     "EXPERT_REVIEW_RELEASE_MISMATCH",
                     "EXPERT_REVIEW_CASE_MANIFEST_MISMATCH",
                     "EXPERT_REVIEW_PROTOCOL_MISMATCH",
                     "EXPERT_REVIEW_AUDIT_FAILED"),
    ),
    RouteSpec(
        operation_id="getLiveness",
        method="GET",
        path="/health/live",
        summary="Whether this process can serve",
        description=(
            "Process and event loop only. Touches no database, resolves no "
            "release and calls nothing external, so a dependency outage never "
            "causes an orchestrator to restart a process that was working."),
        tag="health",
        access=PUBLIC,
        success_status=200,
        response_model="LivenessResponse",
    ),
    RouteSpec(
        operation_id="getReadiness",
        method="GET",
        path="/health/ready",
        summary="Whether every blocking dependency is ready",
        description=(
            "Independent bounded checks over configuration, the database, "
            "migration compatibility, the active release, the claim boundary "
            "and the authentication provider. 200 only when every blocking "
            "component is ready; 503 otherwise, with component names and no "
            "connection strings, paths or exception text."),
        tag="health",
        access=PUBLIC,
        success_status=200,
        response_model="ReadinessResponse",
        error_codes=("SERVICE_NOT_READY",),
    ),
)

ROUTES_BY_OPERATION: Mapping[str, RouteSpec] = {
    route.operation_id: route for route in ROUTES}

#: The operations that answer without any principal.
HEALTH_OPERATIONS: Tuple[str, ...] = ("getLiveness", "getReadiness")

#: The operations that exist only to refuse, and the work package that will
#: replace each. Named so the documentation generator and the gate report read
#: the same list rather than two lists that agree today.
STUB_OPERATIONS: Mapping[str, str] = {
    route.operation_id: route.superseded_by
    for route in ROUTES if not route.implemented}


def operation(operation_id: str) -> RouteSpec:
    """Look up one route, or fail loudly.

    Raises:
        KeyError: no such operation. Routers and generators address routes by
            operation id, so a typo should stop a start-up rather than quietly
            register an endpoint nothing documents.
    """
    try:
        return ROUTES_BY_OPERATION[operation_id]
    except KeyError:  # pragma: no cover - defensive
        raise KeyError("no P0 operation named %r" % operation_id) from None


def _check_table() -> None:
    """Invariants the table must satisfy, checked at import.

    Cheap, and it turns three classes of editing mistake - a duplicated
    operation id, a route addressing a model that does not exist, a stub that
    forgot its role check - into an ImportError at start-up instead of a
    surprise in production.
    """
    from apps.api.contracts.spec import MODELS

    seen_ids = set()
    seen_addresses = set()
    for route in ROUTES:
        if route.operation_id in seen_ids:
            raise ValueError("duplicate operation id %r" % route.operation_id)
        seen_ids.add(route.operation_id)
        address = (route.method, route.path)
        if address in seen_addresses:
            raise ValueError("duplicate route %s %s" % address)
        seen_addresses.add(address)
        if route.response_model not in MODELS:
            raise ValueError("route %s names unknown response model %r"
                             % (route.operation_id, route.response_model))
        if route.request_model is not None and route.request_model not in MODELS:
            raise ValueError("route %s names unknown request model %r"
                             % (route.operation_id, route.request_model))
        declared = {item.name for item in route.path_parameters}
        in_path = {segment[1:-1] for segment in route.path.split("/")
                   if segment.startswith("{") and segment.endswith("}")}
        if declared != in_path:
            raise ValueError(
                "route %s declares path parameters %s and its path names %s"
                % (route.operation_id, sorted(declared), sorted(in_path)))
        if not route.implemented and route.access.public:
            raise ValueError(
                "disabled route %s must still check its role before refusing, "
                "or its 501 tells an anonymous caller which paths exist"
                % route.operation_id)


_check_table()
