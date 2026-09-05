# WP-17 handoff

## What exists now

A server-rendered clinician/demo web interface at `apps/web/`: 25 modules
(22 of them framework-free), 14 templates, 2 static assets, 11 routes,
276 tests under `tests/unit/web`, 34 under `tests/integration/web` (all of
which now execute where the stack and a browser are present), 3 schemas,
3 data artifacts, 8 committed HTML snapshots, 7 real browser captures, and
8 documents.

Entry points:

```
pgx-web        # combined: WP-16's API plus the eleven pages, one process
pgx-api        # unchanged, API only
```

Install: `pip install -e '.[web]'` (a superset of `.[api]` adding Jinja2 and
python-multipart).

## What the next work package inherits

### The one WP-16 change

`ServiceProvider` moved from `apps/api/dependencies.py` to a new
`apps/api/provider.py` and is re-exported from its old home, so no import
anywhere breaks. The reason: composition happens in a CLI, in tests and in the
web layer, none of which should need FastAPI installed to describe what they
are composed with. This was done because it blocked WP-17, and nothing else in
WP-16 was touched.

Two WP-16 tests changed as a consequence, both because they had become stale
rather than because they had become inconvenient:

- `TestWp17WasNotStarted` → `TestTheApiShipsNoUserInterface`. The API must ship
  no templates, no static directory, no Jinja import and no `apps.web` import —
  which is the property that assertion was actually protecting.
- `test_openapi.py`'s `assertFalse(wp17_started)` → an assertion that the flag
  *agrees with the filesystem*. The gate-status schema for `wp17_started`
  loosened from `{"const": false}` to `{"type": "boolean"}` for the same
  reason: it is a measurement, not a constant.

### The framework split

Twenty-two of the twenty-five `apps/web` modules import no web framework.
Everything that decides anything is in that half and is fully executed. Keep it
that way: `tests/unit/web/test_wp17_boundaries.py` asserts the split by reading
syntax trees, so a decision that migrates into a router will fail the suite.

### The one permitted `pgx.engine` import

`apps/web/demo_migration.py` imports `normalize_profile`. It is a build-time
migration (run by `python -m apps.web.artifacts`), no runtime module imports
it, and two tests hold both of those facts down. Do not add a second exemption
without the same pair of compensating tests.

## What has since run, and what is still blocked

The ASGI and browser suites are no longer hypothetical. Both have executed
against a real stack — FastAPI 0.141.1, Starlette 1.6.0, Uvicorn 0.46.0,
Chromium 141.0.7390.37 — and both are green. Seven real browser captures are in
`tests/fixtures/wp17/browser/`. `docs/evidence/wp17-ui-verification.md` says
which environment ran what.

Four defects only a runtime could expose were found and repaired in the
process; they are listed under "Repairs made after the first runtime" below.

Still blocked, and none of it by code:

| Blocked | Unblocked by |
| --- | --- |
| Any PostgreSQL query | a running server; `psycopg` is also absent from the runtime environment |
| Any real assessment | an active release |
| Anything presented as approved | human and scientific review of the claim boundary (currently P0, `is_approved: false`) |
| Contrast ratios, screen-reader announcement | a measuring tool and a person; a browser is not enough |

**First thing to do on a fresh host:** regenerate the two gate statuses.

```
python -m apps.api.artifacts
python -m apps.web.artifacts
```

They are *measurements* — which packages import, whether a browser launches,
what its version is, how many captures exist. A committed copy describes the
machine that produced it, so it is stale on any other machine by design, and
`test_every_artifact_is_committed_and_current` says so rather than tolerating
it.

## Repairs made after the first runtime

Each of these was invisible until something actually made a request.

1. **The prohibited-field scan never ran in a deployment.** Pydantic rejected
   `genotype` as an unknown field while FastAPI resolved parameters, so the
   response was `REQUEST_CONTRACT_VIOLATION` — a framework rule classifying a
   refusal the contract owns. `ProhibitedFieldMiddleware` now runs the scan in
   front of routing, on declared body-bearing routes only, and after the size
   limiter.
2. **A web-only application refused every page.** `create_web_app` never set
   `app.state.provider`, so `require_access` could not resolve its dependency
   and all eleven routes answered `SERVICE_NOT_READY` — public ones included,
   because FastAPI resolves that dependency before the handler runs. It now
   takes an `api_provider` and builds a fail-closed one by default.
3. **API failures were rendered as HTML in the combined deployment.** One
   handler per exception type means the interface's replaced the API's.
   `GET /api/v1/system/version` answered `503 text/html`. The handler now
   answers in the shape of the surface the path belongs to.
4. **Browser availability was decided by a console script.** `shutil.which`
   found `playwright` — the package's CLI — and the gate status reported a
   browser on a host that had none, while the tests skipped on a host that had
   one. Availability is now a launch, shared by both.

Two smaller ones: `RulesetBuildORM` referenced `_RULESET_BUILD_OUTCOMES`
before it was defined, making `pgx/infrastructure/db/models.py` un-importable
in a fresh process (the visible symptom was a duplicate-table error four
modules away); and the WP-16 evidence fixture seeded one of the two records its
own ruleset cites, so half the evidence links a page renders were 404.

Nothing in the source needs to change to run any of the suites. The skip
messages name the exact missing packages rather than saying "dependencies
unavailable", because a skip nobody can act on is a skip everyone learns to
ignore.

## Explicitly not started

**WP-18** (validation architecture), **WP-21** (validation metrics), **WP-22**
(expert-review persistence and reveal logic), **WP-23** (authentication,
sessions, passwords). Each has a screen in this interface; each screen states
what it is waiting for and offers no control that appears to work. None is
simulated.

`wp18_started: false` and `wp18_markers_found: []` in the gate status are
measured from the filesystem, not asserted.

## What each unstarted package will find waiting

### WP-18 / WP-21 — validation

`/validation` renders an empty state and nothing else. It shows the development
case count, labelled as development cases, and it computes **no percentage**:
there is no denominator, and a percentage over a zero denominator is a number
that looks like a result. `validation_blockers()` in `apps/web/gate_status.py`
supplies the reasons the page displays.

The trap to avoid: `data/demo/wp17-development-cases.json` is *not* a
validation set. Every case is `case_role: DEVELOPMENT`,
`is_validation_evidence: false`, `is_holdout: false`, and `DevelopmentCase` has
**no field for an expected result** — `FORBIDDEN_CASE_FIELDS` refuses one under
any plausible name. That is structural on purpose: a catalogue with an answer
key is a scoreable set, and scoring these would be the first step towards
reporting a validation metric over demo fixtures.

### WP-22 — expert review

`/expert-reviews/{case_id}` renders a disabled shell that preserves the
expected shape of the eventual workflow — expected → reveal → complete — with
every control disabled and the reason stated. The route performs **no lookup**:
the identifier is echoed and nothing is consulted, so the response is identical
whether or not a case with that id exists. Do not add a lookup without deciding
what a reviewer is allowed to learn from a 404.

### WP-23 — authentication

`/login` is an honest shell: no credential is accepted, stored, compared or
logged, and no session cookie is set. `WebProvider` has **no field for a
principal**; principals come from WP-16's resolver.

`WebProvider.csrf` defaults to `UnconfiguredCsrf`, which refuses every token,
which makes `forms_available` false, which makes every state-changing control
render disabled with its reason. Supplying a real verifier turns the two POST
routes on; nothing else needs to change. `/logout` already verifies CSRF before
doing anything, so it will not need to be retrofitted.

## Things to be careful with

**The status pair.** `templates/_status_pair.html` is the only renderer of
attention or coverage anywhere. `StatusPair` refuses construction without both
values. Adding a second renderer, or a partial that shows one alone, breaks
SAFETY-INV-001 structurally rather than by convention.

**Fact preservation runs in production.** `require_preserved()` executes on
every assessment page, not only under test. If a future view model needs to
present a protected fact differently, change `PROTECTED_ASSESSMENT_FACTS`
deliberately — do not weaken the check.

**The claim scanner is weaker in Turkish than in English.** Documented in
`docs/web/security-boundary.md` with a test pinning it. A clean scan of a
Turkish page is not the same strength of evidence as a clean scan of an English
one, and this interface is Turkish first.

**The label vocabulary is WP-15's.** `apps/web/labels.py` re-exports
`ATTENTION_LABELS`, `COVERAGE_LABELS`, `COVERAGE_REASON_LABELS`,
`OBSERVATION_STATE_LABELS`, `MODE_LABELS`, `INPUT_KIND_LABELS` and
`FIELD_LABELS` rather than defining a second set. A new governed code needs a
label in WP-15, not here.

**Regenerate artifacts after changing routes, cases or the gate.**

```
python -m apps.web.artifacts
python -m tests.fixtures.wp17.snapshots
```

Both are deterministic and both have tests that fail if the committed output is
stale.

## Housekeeping left behind

`_to_delete/wp17-stale-snapshots/` holds three HTML files that were generated
during development and then excluded from the committed snapshot set. File
deletion was not available in the environment this was built in, so they were
moved rather than removed. They are safe to delete and are referenced by
nothing.
