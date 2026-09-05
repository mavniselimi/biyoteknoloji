# WP-16 — FastAPI application layer

## What this layer is

A thin transport. One direction, no branches:

```
HTTP request
  -> strict Pydantic request contract
  -> request adapter
  -> existing application/domain service
  -> persisted immutable result
  -> strict response adapter
  -> Pydantic response contract
  -> JSON response
```

A router may validate a transport shape, resolve an injected dependency, pass
trusted operational context, invoke **one** application service, map a typed
result or failure to HTTP, and serialise a verified result. It may not select a
release, evaluate a phenotype, inspect a rule, resolve evidence in order to
calculate with it, aggregate attention or coverage, regenerate a stored
assessment, invent a status or a sentence, invoke a legacy module, or call an
external network service.

## The split that makes this layer testable

WP-16 was built where FastAPI, Pydantic, Starlette, Uvicorn and HTTPX could not
be installed — the package index was unreachable and `pip download fastapi`
failed with a proxy tunnel error. The design responded to that rather than
working around it, and the response outlived the constraint: the split is what
makes the layer testable on *any* host, and it is why installing the framework
later added so little to what was already proven.

`apps/api` is therefore two halves.

**The framework-free half holds every decision.** It imports only the standard
library and `pgx`:

| Module | Decides |
| --- | --- |
| `contracts/spec.py` | the whole request/response contract: fields, bounds, patterns, vocabularies, prohibitions |
| `contracts/validate.py` | whether a document satisfies it, and with which issue codes |
| `errors.py` | the error catalogue, the status table and the one exception mapper |
| `security.py` | the Principal contract, the roles, the access policies, the fail-closed resolver |
| `routes.py` | the closed route surface, with operation ids and role requirements |
| `config.py` | settings, and what production refuses |
| `catalog.py` | deterministic release-bound pagination |
| `readiness.py` | the component checks and the fixed detail catalogue |
| `adapters/*` | every translation between the wire and the application |
| `openapi.py` | the generated document |
| `gate_status.py`, `artifacts.py` | what this deployment can do, measured |

All of it runs here, and all of it is tested by execution.

**The framework-bound half holds no decisions.** `factory.py`,
`dependencies.py`, `middleware.py`, `contracts/models.py` and `routers/*` wire
the halves together. None of them can be imported here, so none of them may
decide anything: they are covered by tests that read them as syntax trees and
assert that every route they register comes from the route table, addressed by
operation id, with no hand-written path and no locally-built access policy.

`tests/unit/api/test_wp16_boundaries.py` asserts the split holds: no
framework-free module imports a framework, and every one of them actually
imports.


### Runtime status is recorded, never inferred

The half that needs a framework is covered by
`tests/integration/api/test_asgi_runtime.py`, which skips with a message naming
the missing packages where they are absent and runs where they are present.

Whether it *has* run is a separate question from whether it *could*, and the
gate status answers only the first. `apps/api/runtime_verification.py` performs
the checks — compose the application, serve `/openapi.json` and compare it with
the committed artifact, answer a liveness probe, run the ASGI suite — and
records the outcome in `data/api/wp16-runtime-verification.json`. The gate
status reads that file and reports `BLOCKED` when it is absent, when the run
failed, or when the `apps/api` source or the committed document has changed
since. Installed dependencies never make the flag true; that is asserted by a
test, because it is the repair somebody would otherwise reach for.

The module is framework-free at import and imports FastAPI only inside its
checks, so a host with no framework can still build a gate status that says
BLOCKED. A subprocess test imports it with the framework blocked to prove it.

## Layering

`apps` may import `pgx`. No module in `pgx` imports `apps`, and none imports a
web framework — asserted over every `pgx` module as a syntax tree. `pgx/domain`
remains standard-library only.

One module was added below the API: `pgx/application/execution_context.py`. It
is a frozen value type carrying the actor, the role, the channel and the
correlation id. It exists so the API can hand an audited actor to
`AssessmentService.execute` without `pgx/application` importing FastAPI, and it
is transport-neutral because a CLI, a scheduled job and a queue consumer all
need to record who acted just as much as an HTTP request does.

## Composition

`create_app(settings, provider) -> FastAPI` registers routers, installs
middleware and installs exception handlers. It performs no I/O: no database
connection, no active release resolution, no fixture load, no file read.
`import apps.api.main` therefore imports a servable application that has
touched nothing.

Capabilities arrive through `ServiceProvider`, and every field is optional. A
deployment with no database, no evidence build and no authentication — which is
this repository — produces an application whose health routes answer honestly
and whose every other route reports the typed unavailability for what it
needed. Asking for a capability that is absent raises `DATABASE_UNAVAILABLE`,
`ACTIVE_RELEASE_UNAVAILABLE`, `EVIDENCE_BUILD_UNAVAILABLE` or
`SERVICE_NOT_READY` — never `None`.

Startup opens only what the provider was configured with. A failed startup
leaves a provider without an assessment capability, so there is no path in
which a partially-initialised application answers `POST /assessments` with
anything but a refusal.

## Release pinning

The active pointer is read **exactly once per assessment**, inside
`AssessmentService`. No middleware, dependency or router resolves a release,
and the pinned context is a value rather than a lookup — so an activation
committing mid-request cannot reach a calculation already in flight.
`TestPointerMovementDuringExecution` moves the pointer after pinning and
asserts the response is unchanged.

`GET /assessments/{id}` reads the pointer zero times. It serialises stored rows
through the WP-15 lossless read model, verifying the stored hashes on the way
out, and reports the release the assessment was pinned to whatever is active
now.

## Serialisation guarantee

`POST` and a subsequent `GET` return **semantically identical governed facts**.
That is structural rather than tested-into-agreement: both feed
`build_assessment_document`, one from the executed result and one from the read
model, and `TestReadingAnAssessment` asserts the two documents are equal.

Attention and coverage are one `status` object at every level, so no
serialisation of this contract can carry one without the other
(SAFETY-INV-001). `NOT_ASSESSED`, `SOURCE_CONFLICT`, `UNSUPPORTED_DRUG`, every
reason code, every axis, every finding and every evidence reference survive
verbatim. `effect_code` and `explanation_code` are `None` in the governed
outcome and are serialised as `None`.

## What was not built

- No user interface, no template, no static mount (WP-17).
- No validation-dataset architecture (WP-18).
- No expert-review workflow logic — three routes exist and refuse (WP-22).
- No authentication mechanism — a Principal contract and a refusing default (WP-23).
- No report generation and no language-model path of any kind.
- No legacy module is imported or reachable.

## Related documents

- `docs/api/p0-contract.md` — the surface, the role matrix, the limits
- `docs/api/error-contract.md` — the envelope and the status mapping
- `docs/api/readiness.md` — what readiness checks and what it never checks
- `docs/api/security-boundary.md` — the authentication stub boundary
- `docs/evidence/wp16-api-contract-report.md` — what was verified, and how
- `docs/handoffs/wp16-handoff.md` — what WP-17 and WP-23 receive
