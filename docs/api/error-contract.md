# Error contract

## One shape

Every 4xx and 5xx response, from every route, is exactly this:

```json
{
  "error": {
    "code": "STABLE_MACHINE_CODE",
    "message": "Controlled safe message.",
    "details": {},
    "request_id": "uuid"
  }
}
```

There is no second shape and no route-specific variation. FastAPI's own
validation error and Starlette's own HTTP exception are both converted into
this envelope by handlers installed in `apps/api/factory.py`, because
neither is an application error and both would otherwise emit a body in a
shape this API promises never to return.

## The message is never built from an exception

`message` is always the catalogue's fixed text for the code. It is never
`str(error)`, never a format string filled at runtime, and never anything a
caller sent. `map_exception` is total: anything it does not recognise
becomes `INTERNAL_ERROR` with the generic message and empty details.

This is what keeps a traceback, a SQL fragment, a filesystem path, a
connection string, a credential, a phenotype profile and a medication list
out of every response. `tests/unit/api/test_errors.py` raises exceptions
carrying each of those and asserts none reaches the envelope.

Database and configuration messages pass through WP-02's existing
`sanitize_message` before they are logged internally — the same redaction,
not a second one written here.

## `details` is bounded and closed

Only five keys may appear — `issues`, `components`, `required_role`,
`work_package`, `limit` — and every list among them is truncated to
`max_detail_entries`. The filtering happens in `error_envelope`, once, so no
caller can widen the envelope by handing it a larger mapping.

Validation issues carry a **location and a code only**, never a value:

```json
{"location": "$.profile.observations[0].gene", "code": "DUPLICATE_ITEM"}
```

Locations are normalised to the same `$.a.b[0]` form whether they came from
the framework-free validator or from Pydantic, and issues are sorted by
`(location, code)` so the same bad request always produces the same body.

## The catalogue

| Code | Status | Message |
| --- | :-: | --- |
| `ACTIVE_RELEASE_UNAVAILABLE` | 503 | No governed active release is available. |
| `ARTIFACT_INCONSISTENT` | 500 | Two governed artifacts disagree, so no answer was produced. |
| `ASSESSMENT_INPUT_INVALID` | 422 | The assessment input could not be read as a canonical input. |
| `ASSESSMENT_NOT_FOUND` | 404 | No stored assessment carries that identifier. |
| `AUTHENTICATION_NOT_CONFIGURED` | 503 | No authentication provider is configured. |
| `CATALOGUE_UNAVAILABLE` | 503 | No governed catalogue is available for the active release. |
| `CLAIM_BOUNDARY_NOT_APPROVED` | 503 | The claim boundary has not been approved, so no assessment may be executed. This is a governance gate, not a problem with the request. |
| `CONCURRENT_STATE_CHANGE` | 409 | Stored state moved while this request was being served. |
| `CURSOR_RELEASE_MISMATCH` | 409 | The supplied cursor was created for a different release. |
| `DATABASE_UNAVAILABLE` | 503 | The database is not available. |
| `EVIDENCE_BUILD_UNAVAILABLE` | 503 | No sealed evidence build is available. |
| `EVIDENCE_NOT_FOUND` | 404 | No evidence record carries that identifier in the pinned build. |
| `EXPERT_REVIEW_ALREADY_COMPLETED` | 409 | This review is complete and immutable. |
| `EXPERT_REVIEW_AUDIT_FAILED` | 500 | The audit event could not be appended, so the governed action was rolled back. |
| `EXPERT_REVIEW_CASE_MANIFEST_MISMATCH` | 409 | The case manifest hash no longer matches the pinned one. |
| `EXPERT_REVIEW_EXPECTATION_ALREADY_LOCKED` | 409 | An expected response is already recorded; it cannot be replaced, only corrected by appending. |
| `EXPERT_REVIEW_EXPECTATION_REQUIRED` | 409 | The expected response must be recorded before anything is revealed. |
| `EXPERT_REVIEW_FORGED_FIELD` | 422 | The request supplied a field the server owns. |
| `EXPERT_REVIEW_INVALIDATED` | 409 | This review was invalidated and cannot be continued. |
| `EXPERT_REVIEW_INVALID_TRANSITION` | 409 | The requested move is not permitted from the current state. |
| `EXPERT_REVIEW_NOT_ASSIGNED` | 404 | No active assignment. Returned identically whether the case is unknown, is not an expert-holdout case, or belongs to another reviewer. |
| `EXPERT_REVIEW_NOT_AVAILABLE` | 503 | The expert review service, its store or its dependencies are unavailable. |
| `EXPERT_REVIEW_PERMIT_INVALID` | 403 | No assignment-scoped permit authorises this payload read. |
| `EXPERT_REVIEW_PROTOCOL_MISMATCH` | 409 | The protocol hash no longer matches the pinned one. |
| `EXPERT_REVIEW_PROTOCOL_NOT_APPROVED` | 403 | The blind review protocol has not been approved by named human and scientific reviewers. |
| `EXPERT_REVIEW_RELEASE_MISMATCH` | 409 | The pinned release no longer matches the one this review began under. |
| `EXPERT_REVIEW_RESULT_ALREADY_REVEALED` | 409 | The result was revealed once; a second reveal cannot recalculate it. |
| `EXPERT_REVIEW_REVEAL_REQUIRED` | 409 | The system result must be revealed before a decision is recorded. |
| `EXPERT_REVIEW_ROLE_REQUIRED` | 403 | Only the exact EXPERT_REVIEWER role may act in the blind review protocol. |
| `FORBIDDEN_ROLE` | 403 | The authenticated principal does not hold the required role. |
| `INPUT_KIND_NOT_PERMITTED` | 403 | The supplied input kind is not permitted for this product phase. |
| `INTERNAL_ERROR` | 500 | The request could not be completed. |
| `MODE_NOT_PERMITTED` | 403 | The requested operation mode is not enabled for this product phase. |
| `PERSISTENCE_REFUSED` | 500 | The calculated assessment could not be stored, so nothing was stored. |
| `PROHIBITED_INPUT_FIELD` | 422 | The request carries a field this product does not accept. |
| `RELEASE_NOT_ACTIVE` | 409 | The requested release is not the active release. |
| `REQUEST_CONTRACT_VIOLATION` | 422 | The request is valid JSON but does not satisfy the governed input contract. |
| `REQUEST_ID_INVALID` | 400 | The supplied request identifier is not a canonical UUID. |
| `REQUEST_MALFORMED` | 400 | The request body could not be read as JSON. |
| `REQUEST_TOO_LARGE` | 400 | The request body exceeds the accepted size. |
| `RESOURCE_NOT_FOUND` | 404 | No resource carries that identifier. |
| `SERVICE_NOT_READY` | 503 | A required component is not ready to serve this endpoint. |
| `STORED_RESULT_INCONSISTENT` | 500 | A stored result did not verify against its recorded hashes and was not returned. |
| `UNAUTHENTICATED` | 401 | This endpoint requires an authenticated principal. |
| `UNSUPPORTED_PHENOTYPE` | 422 | The phenotype value is not supported by the active release. |

Every message in this table is scanned by the prohibited-claim scanner in
`tests/unit/api/test_safety.py`. It is scanned as a **fixed catalogue**,
once, in a test — never at request time. Scanning a message while an error
is already being handled is how a failure in the scanner produces an error
about handling errors.

## Status mapping

| Status | Means |
| :-: | --- |
| 400 | malformed transport: unparseable body, bad `Content-Length`, malformed `X-Request-ID`, oversized body |
| 401 | no principal could be established |
| 403 | a principal was established and its role or the requested mode is not permitted |
| 404 | an immutable resource with that identity does not exist |
| 409 | a release or lifecycle conflict: the release moved, or a cursor was made for another one |
| 422 | the request violated the governed input contract |
| 503 | a dependency is not ready: database, active release, claim boundary, authentication provider |
| 500 | unexpected, or a stored document that no longer agrees with itself |

**A missing claim-boundary approval is 503, not 4xx.** It says the server
is not permitted to answer clinical questions yet — a governance gate — and
not that the caller supplied bad clinical data. The catalogue message says
so in words, because an operator who reads "not ready" and starts checking
the database will not find anything wrong with it.

**A persistence failure is 500, not 503.** The request was valid and the
failure is the server's, but 503 promises "temporarily unavailable, retry"
— and `PERSISTENCE_REFUSED` also covers a duplicate assessment identity,
which no amount of retrying resolves. A promise the code cannot keep is
worse than a generic one.

## Engine and application failure codes

Every one of the 22 WP-14 failure codes has a mapping. They are split by
*who has to act*: a caller who sent something the contract refuses, an
operator whose environment is incomplete, or an engineer whose artifacts
disagree with each other.

| Engine code | API code | Status |
| --- | --- | :-: |
| `ASSESSMENT_ACTIVE_RELEASE_MISSING` | `ACTIVE_RELEASE_UNAVAILABLE` | 503 |
| `ASSESSMENT_CLAIM_BOUNDARY_NOT_APPROVED` | `CLAIM_BOUNDARY_NOT_APPROVED` | 503 |
| `ASSESSMENT_CONCURRENT_STATE_ERROR` | `CONCURRENT_STATE_CHANGE` | 409 |
| `ASSESSMENT_CONFLICT_UNRESOLVED` | `ARTIFACT_INCONSISTENT` | 500 |
| `ASSESSMENT_COVERAGE_MANIFEST_INVALID` | `ARTIFACT_INCONSISTENT` | 500 |
| `ASSESSMENT_COVERAGE_MANIFEST_MISSING` | `SERVICE_NOT_READY` | 503 |
| `ASSESSMENT_DATASET_NOT_PUBLISHED` | `SERVICE_NOT_READY` | 503 |
| `ASSESSMENT_ENTITY_NOT_RESOLVABLE` | `ARTIFACT_INCONSISTENT` | 500 |
| `ASSESSMENT_EVIDENCE_MISSING` | `ARTIFACT_INCONSISTENT` | 500 |
| `ASSESSMENT_INPUT_INVALID` | `ASSESSMENT_INPUT_INVALID` | 422 |
| `ASSESSMENT_INPUT_KIND_NOT_PERMITTED` | `INPUT_KIND_NOT_PERMITTED` | 403 |
| `ASSESSMENT_INPUT_SNAPSHOT_INVALID` | `STORED_RESULT_INCONSISTENT` | 500 |
| `ASSESSMENT_MODE_NOT_PERMITTED` | `MODE_NOT_PERMITTED` | 403 |
| `ASSESSMENT_PERSISTENCE_REFUSED` | `PERSISTENCE_REFUSED` | 500 |
| `ASSESSMENT_RELEASE_MANIFEST_INVALID` | `ACTIVE_RELEASE_UNAVAILABLE` | 503 |
| `ASSESSMENT_RELEASE_NOT_ACTIVE` | `RELEASE_NOT_ACTIVE` | 409 |
| `ASSESSMENT_RULESET_ARTIFACT_INVALID` | `SERVICE_NOT_READY` | 503 |
| `ASSESSMENT_RULESET_NOT_FROZEN` | `SERVICE_NOT_READY` | 503 |
| `ASSESSMENT_RULE_DID_NOT_MATCH` | `ARTIFACT_INCONSISTENT` | 500 |
| `ASSESSMENT_RULE_HASH_MISMATCH` | `ARTIFACT_INCONSISTENT` | 500 |
| `ASSESSMENT_RULE_NOT_EXECUTABLE` | `ARTIFACT_INCONSISTENT` | 500 |
| `ASSESSMENT_VERSION_MISMATCH` | `ARTIFACT_INCONSISTENT` | 500 |

`tests/unit/api/test_errors.py` asserts that every code in
`pgx.engine.risk_errors.FAILURE_CODES` appears here and that every target
exists in the catalogue, so an engine code added later cannot fall through
to a generic 500 unnoticed.

## Correlation

Every response — success, refusal or 500 — carries `X-Request-ID`, and the
value in an error body is the same value as in the header. Both are read
from request state rather than from the header twice, so they cannot
diverge.

A caller may supply `X-Request-ID`. It is accepted only if it is a
canonical lowercase UUID; anything else is **refused** with 400
`REQUEST_ID_INVALID` rather than quietly replaced. Silently substituting one
would leave the client's logs and the server's naming different ids for the
same call, with no way for the client to notice. An absent header is the
benign case and is generated.

The request id reaches the audit trail and **never reaches any hash** —
not `input_hash`, not `output_hash`, not the coverage result hash, not a
report hash. Mixing a per-call value into one would make every assessment
unique and the determinism claim untestable.
