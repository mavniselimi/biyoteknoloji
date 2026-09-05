# -*- coding: utf-8 -*-
"""The one error envelope, and the one place status is decided (WP-16).

Every failure this API returns has the same shape and is mapped here. Routers
raise or propagate typed errors; none of them chooses a status code, because
a status chosen in eleven places is eleven chances for the same condition to
mean two things.

**Messages come from a fixed catalogue.** :data:`ERROR_CATALOGUE` holds every
message this API can emit. Nothing is formatted from an exception, a query, a
path or a value the caller supplied, so there is no route by which a driver
error, a stack frame or a phenotype token reaches a client. A test scans the
whole catalogue with the prohibited-claim scanner, and it scans it *once at
import*, before any error is handled - so a failure inside the scanner can
never itself become an error that needs scanning.

**An unapproved claim boundary is a 503, not a 4xx.** The caller did nothing
wrong: the product is not yet permitted to answer. Returning 422 would tell an
operator their input was bad and send them looking for a fix that does not
exist.

**Unexpected exceptions become one generic 500.** The code, the message and
the details are fixed; the original is logged behind the sanitiser, never
returned. A stack trace in a response body is a map of the server.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from apps.api.contracts.spec import LIMITS

__all__ = [
    "ERROR_CATALOGUE",
    "ENGINE_CODE_STATUS",
    "ApiError",
    "ForbiddenError",
    "NotFoundError",
    "ExpertReviewApiError",
    "NotReadyError",
    "RequestContractError",
    "UnauthenticatedError",
    "error_envelope",
    "map_exception",
    "status_for_code",
]


#: Every message this API can return, with the status it is returned under.
#:
#: Fixed strings, never templates. A message that interpolated anything would
#: eventually interpolate the thing it was written to keep out.
ERROR_CATALOGUE: Mapping[str, Tuple[int, str]] = {
    # -- 400 -------------------------------------------------------------
    "REQUEST_MALFORMED": (
        400, "The request body could not be read as JSON."),
    "REQUEST_TOO_LARGE": (
        400, "The request body exceeds the accepted size."),
    "REQUEST_ID_INVALID": (
        400, "The supplied request identifier is not a canonical UUID."),
    # -- 401 -------------------------------------------------------------
    "UNAUTHENTICATED": (
        401, "This endpoint requires an authenticated principal."),
    # -- 403 -------------------------------------------------------------
    "FORBIDDEN_ROLE": (
        403, "The authenticated principal does not hold the required role."),
    "MODE_NOT_PERMITTED": (
        403, "The requested operation mode is not enabled for this product "
             "phase."),
    "INPUT_KIND_NOT_PERMITTED": (
        403, "The supplied input kind is not permitted for this product "
             "phase."),
    # -- 404 -------------------------------------------------------------
    "ASSESSMENT_NOT_FOUND": (
        404, "No stored assessment carries that identifier."),
    "EVIDENCE_NOT_FOUND": (
        404, "No evidence record carries that identifier in the pinned "
             "build."),
    "RESOURCE_NOT_FOUND": (
        404, "No resource carries that identifier."),
    # -- 409 -------------------------------------------------------------
    "RELEASE_NOT_ACTIVE": (
        409, "The requested release is not the active release."),
    "CURSOR_RELEASE_MISMATCH": (
        409, "The supplied cursor was created for a different release."),
    "CONCURRENT_STATE_CHANGE": (
        409, "Stored state moved while this request was being served."),
    # -- 422 -------------------------------------------------------------
    "REQUEST_CONTRACT_VIOLATION": (
        422, "The request is valid JSON but does not satisfy the governed "
             "input contract."),
    "PROHIBITED_INPUT_FIELD": (
        422, "The request carries a field this product does not accept."),
    "UNSUPPORTED_PHENOTYPE": (
        422, "The phenotype value is not supported by the active release."),
    "ASSESSMENT_INPUT_INVALID": (
        422, "The assessment input could not be read as a canonical input."),
    # -- 403, expert review ----------------------------------------------
    #
    # The status choices here are deliberate. A wrong role gets 403 because
    # the caller already knows they are not a reviewer. A missing, foreign or
    # nonexistent assignment gets **404 with one code**, so that three
    # conditions are indistinguishable: three codes would hand anyone with
    # reviewer credentials a way to enumerate the holdout set by probing.
    "EXPERT_REVIEW_ROLE_REQUIRED": (
        403, "Only the exact EXPERT_REVIEWER role may act in the blind "
             "review protocol."),
    "EXPERT_REVIEW_PROTOCOL_NOT_APPROVED": (
        403, "The blind review protocol has not been approved by named human "
             "and scientific reviewers."),
    "EXPERT_REVIEW_FORGED_FIELD": (
        422, "The request supplied a field the server owns."),
    # -- 404, deliberately coarse ----------------------------------------
    "EXPERT_REVIEW_NOT_ASSIGNED": (
        404, "No active assignment. Returned identically whether the case is "
             "unknown, is not an expert-holdout case, or belongs to another "
             "reviewer."),
    # -- 409, the protocol ordering --------------------------------------
    "EXPERT_REVIEW_EXPECTATION_REQUIRED": (
        409, "The expected response must be recorded before anything is "
             "revealed."),
    "EXPERT_REVIEW_EXPECTATION_ALREADY_LOCKED": (
        409, "An expected response is already recorded; it cannot be "
             "replaced, only corrected by appending."),
    "EXPERT_REVIEW_REVEAL_REQUIRED": (
        409, "The system result must be revealed before a decision is "
             "recorded."),
    "EXPERT_REVIEW_RESULT_ALREADY_REVEALED": (
        409, "The result was revealed once; a second reveal cannot "
             "recalculate it."),
    "EXPERT_REVIEW_ALREADY_COMPLETED": (
        409, "This review is complete and immutable."),
    "EXPERT_REVIEW_INVALIDATED": (
        409, "This review was invalidated and cannot be continued."),
    "EXPERT_REVIEW_INVALID_TRANSITION": (
        409, "The requested move is not permitted from the current state."),
    "EXPERT_REVIEW_RELEASE_MISMATCH": (
        409, "The pinned release no longer matches the one this review began "
             "under."),
    "EXPERT_REVIEW_CASE_MANIFEST_MISMATCH": (
        409, "The case manifest hash no longer matches the pinned one."),
    "EXPERT_REVIEW_PROTOCOL_MISMATCH": (
        409, "The protocol hash no longer matches the pinned one."),
    "EXPERT_REVIEW_PERMIT_INVALID": (
        403, "No assignment-scoped permit authorises this payload read."),
    # -- 500 -------------------------------------------------------------
    "EXPERT_REVIEW_AUDIT_FAILED": (
        500, "The audit event could not be appended, so the governed action "
             "was rolled back."),
    # -- 503 -------------------------------------------------------------
    "EXPERT_REVIEW_NOT_AVAILABLE": (
        503, "The expert review service, its store or its dependencies are "
             "unavailable."),
    # -- 503 -------------------------------------------------------------
    "SERVICE_NOT_READY": (
        503, "A required component is not ready to serve this endpoint."),
    "CLAIM_BOUNDARY_NOT_APPROVED": (
        503, "The claim boundary has not been approved, so no assessment may "
             "be executed. This is a governance gate, not a problem with the "
             "request."),
    "ACTIVE_RELEASE_UNAVAILABLE": (
        503, "No governed active release is available."),
    "DATABASE_UNAVAILABLE": (
        503, "The database is not available."),
    "AUTHENTICATION_NOT_CONFIGURED": (
        503, "No authentication provider is configured."),
    "EVIDENCE_BUILD_UNAVAILABLE": (
        503, "No sealed evidence build is available."),
    "CATALOGUE_UNAVAILABLE": (
        503, "No governed catalogue is available for the active release."),
    # -- 500 -------------------------------------------------------------
    "INTERNAL_ERROR": (
        500, "The request could not be completed."),
    "STORED_RESULT_INCONSISTENT": (
        500, "A stored result did not verify against its recorded hashes and "
             "was not returned."),
    "ARTIFACT_INCONSISTENT": (
        500, "Two governed artifacts disagree, so no answer was produced."),
    "PERSISTENCE_REFUSED": (
        500, "The calculated assessment could not be stored, so nothing was "
             "stored."),
}


#: How each WP-14 engine failure code leaves the building.
#:
#: The split is by *who has to act*. A boundary, release, dataset, ruleset or
#: manifest that is missing or unapproved is the deployment's problem, so it
#: is a 503 and the caller is told to wait rather than to change their input.
#: A rule that does not verify against the artifact coverage recorded is
#: corruption, so it is a 500 and the code is preserved for whoever reads the
#: log. Only two conditions are actually the caller's: an input that is not a
#: canonical input, and a mode or input kind the boundary does not enable.
ENGINE_CODE_STATUS: Mapping[str, str] = {
    "ASSESSMENT_CLAIM_BOUNDARY_NOT_APPROVED": "CLAIM_BOUNDARY_NOT_APPROVED",
    "ASSESSMENT_MODE_NOT_PERMITTED": "MODE_NOT_PERMITTED",
    "ASSESSMENT_INPUT_KIND_NOT_PERMITTED": "INPUT_KIND_NOT_PERMITTED",
    "ASSESSMENT_INPUT_INVALID": "ASSESSMENT_INPUT_INVALID",
    "ASSESSMENT_INPUT_SNAPSHOT_INVALID": "STORED_RESULT_INCONSISTENT",
    "ASSESSMENT_ACTIVE_RELEASE_MISSING": "ACTIVE_RELEASE_UNAVAILABLE",
    "ASSESSMENT_RELEASE_NOT_ACTIVE": "RELEASE_NOT_ACTIVE",
    "ASSESSMENT_RELEASE_MANIFEST_INVALID": "ACTIVE_RELEASE_UNAVAILABLE",
    "ASSESSMENT_DATASET_NOT_PUBLISHED": "SERVICE_NOT_READY",
    "ASSESSMENT_RULESET_NOT_FROZEN": "SERVICE_NOT_READY",
    "ASSESSMENT_RULESET_ARTIFACT_INVALID": "SERVICE_NOT_READY",
    "ASSESSMENT_COVERAGE_MANIFEST_MISSING": "SERVICE_NOT_READY",
    "ASSESSMENT_COVERAGE_MANIFEST_INVALID": "ARTIFACT_INCONSISTENT",
    "ASSESSMENT_VERSION_MISMATCH": "ARTIFACT_INCONSISTENT",
    "ASSESSMENT_RULE_NOT_EXECUTABLE": "ARTIFACT_INCONSISTENT",
    "ASSESSMENT_RULE_HASH_MISMATCH": "ARTIFACT_INCONSISTENT",
    "ASSESSMENT_RULE_DID_NOT_MATCH": "ARTIFACT_INCONSISTENT",
    "ASSESSMENT_EVIDENCE_MISSING": "ARTIFACT_INCONSISTENT",
    "ASSESSMENT_CONFLICT_UNRESOLVED": "ARTIFACT_INCONSISTENT",
    "ASSESSMENT_ENTITY_NOT_RESOLVABLE": "ARTIFACT_INCONSISTENT",
    "ASSESSMENT_PERSISTENCE_REFUSED": "PERSISTENCE_REFUSED",
    "ASSESSMENT_CONCURRENT_STATE_ERROR": "CONCURRENT_STATE_CHANGE",
}


def status_for_code(code: str) -> int:
    """The HTTP status one API code is returned under.

    Unknown codes are 500 rather than an exception: a mapper that could itself
    fail is a mapper that turns one failure into two.
    """
    entry = ERROR_CATALOGUE.get(code)
    return entry[0] if entry else 500


class ApiError(Exception):
    """A failure this API knows how to return.

    Carries a catalogue code and bounded details. It deliberately does not
    carry a message: the message belongs to the code, so two occurrences of
    one condition cannot be described two ways.
    """

    code = "INTERNAL_ERROR"

    def __init__(self, code: Optional[str] = None,
                 details: Optional[Mapping[str, Any]] = None) -> None:
        chosen = code or self.code
        super().__init__(chosen)
        self.code = chosen
        self.details: Dict[str, Any] = dict(details or {})

    @property
    def http_status(self) -> int:
        return status_for_code(self.code)


class RequestContractError(ApiError):
    """The request does not satisfy the governed input contract."""

    code = "REQUEST_CONTRACT_VIOLATION"


class UnauthenticatedError(ApiError):
    code = "UNAUTHENTICATED"


class ForbiddenError(ApiError):
    code = "FORBIDDEN_ROLE"


class NotFoundError(ApiError):
    code = "RESOURCE_NOT_FOUND"


class NotReadyError(ApiError):
    code = "SERVICE_NOT_READY"


class ExpertReviewApiError(ApiError):
    """A WP-22 refusal, carrying its domain code unchanged.

    Replaces ``NotImplementedStubError``, which existed while the expert
    review routes were 501 stubs. They are service-backed now, so a class
    whose whole purpose was to refuse would be a surface somebody eventually
    implemented against.
    """

    code = "EXPERT_REVIEW_NOT_AVAILABLE"


#: The only keys ``details`` may carry, matching the ``ErrorDetails`` contract.
#: A key outside this set is dropped rather than passed through: details are
#: assembled by several callers, and an open mapping is where a value nobody
#: reviewed eventually appears.
_DETAIL_KEYS: Tuple[str, ...] = ("issues", "components", "required_role",
                                 "work_package", "limit")


def _bounded_details(details: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Keep the declared detail keys, and bound every list among them.

    Bounding happens here rather than in each caller. ``ContractViolation``
    truncates its own issues, but the FastAPI validation handler, the
    middleware and the readiness path all build details of their own, and a
    rule enforced in four places is a rule enforced in three.
    """
    if not details:
        return {}
    bounded: Dict[str, Any] = {}
    for key in _DETAIL_KEYS:
        if key not in details:
            continue
        value = details[key]
        if isinstance(value, (list, tuple)):
            bounded[key] = list(value)[:LIMITS["max_detail_entries"]]
        else:
            bounded[key] = value
    return bounded


def error_envelope(code: str, request_id: str, *,
                   details: Optional[Mapping[str, Any]] = None
                   ) -> Dict[str, Any]:
    """Build the one error shape this API returns.

    An unknown code becomes ``INTERNAL_ERROR`` rather than being echoed into
    the response: a code the catalogue does not define has no message anybody
    wrote, and inventing one is how an internal string reaches a client.

    ``details`` is filtered to the declared keys and bounded, so no caller can
    widen the envelope by handing it a larger mapping.
    """
    known = code if code in ERROR_CATALOGUE else "INTERNAL_ERROR"
    _status, message = ERROR_CATALOGUE[known]
    return {
        "error": {
            "code": known,
            "message": message,
            "details": _bounded_details(details),
            "request_id": request_id,
        }
    }


def map_exception(error: BaseException) -> Tuple[str, Dict[str, Any]]:
    """Turn any exception into a catalogue code and bounded details.

    Total by construction. Anything this function does not recognise becomes
    ``INTERNAL_ERROR`` with empty details, because the alternative - letting
    an unrecognised exception describe itself to a client - is how a driver
    message, a file path or a fragment of SQL leaves the building.
    """
    from apps.api.contracts.validate import ContractViolation
    from pgx.domain.identifiers import InvalidIdentifierError

    if isinstance(error, ApiError):
        return error.code, dict(error.details)

    if isinstance(error, InvalidIdentifierError):
        # A malformed identifier reaching the domain parser is a caller error,
        # not a server failure. The declared path patterns normally refuse it
        # first; this is the second line, and it exists because the identifier
        # error's own message quotes the value it could not parse - which must
        # never become a response body.
        return "REQUEST_CONTRACT_VIOLATION", {
            "issues": [{"location": "$.path", "code": "UUID_INVALID"}]}

    if isinstance(error, ContractViolation):
        prohibited = [issue for issue in error.issues
                      if issue.code == "PROHIBITED_FIELD"]
        code = ("PROHIBITED_INPUT_FIELD" if prohibited
                else "REQUEST_CONTRACT_VIOLATION")
        return code, error.to_json()

    code = getattr(error, "code", None)
    if isinstance(code, str):
        mapped = ENGINE_CODE_STATUS.get(code)
        if mapped is not None:
            return mapped, {}
        if code in ERROR_CATALOGUE:
            return code, {}

    # Phenotype and coverage errors carry their own vocabularies. A governed
    # input that the normaliser refuses is the caller's to fix; everything
    # else at this point is ours.
    name = type(error).__name__
    if name in ("PhenotypeProfileError", "PhenotypeNormalizationError"):
        return "UNSUPPORTED_PHENOTYPE", {}
    if name in ("DomainInvariantError", "TraceabilityError",
                "LifecycleError"):
        return "ARTIFACT_INCONSISTENT", {}

    return "INTERNAL_ERROR", {}
