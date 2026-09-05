# WP-17 — Clinician/demo server-rendered web interface

## What this layer is

A view over the WP-16 response contract. One direction, no branches:

```
WP-16 response contract
  -> verified web client response      (apps/web/client.py)
  -> immutable presentation view model (apps/web/view_models/)
  -> server-rendered HTML template     (apps/web/templates/)
  -> HTML claim-safety gate            (apps/web/claim_gate.py)
  -> browser
```

Nothing flows the other way. A page may ask the client for a document, turn
that document into a frozen view model, render the view model, and refuse to
serve the result if the gate objects. It may not select a release, evaluate a
phenotype, inspect a rule, resolve evidence in order to calculate with it,
aggregate attention or coverage, regenerate a stored assessment, invent a
status or a sentence, or call an external network service.

The interface is a **research/prototype interface over synthetic and
development-only inputs**. It accepts no genotype, diplotype, allele, VCF, EHR
record, diagnosis, dose or narrative, and it has no field in which any of those
could be typed.

## What it may not import, and why that is checkable

`tests/unit/web/test_wp17_boundaries.py` reads every module under `apps/web`
as a syntax tree and refuses these imports outright:

| Forbidden | Because |
| --- | --- |
| `pgx.engine` (except one exemption below) | attention and coverage are computed once, upstream |
| assessment / coverage calculation | a second calculation is a second answer |
| rule selection, release repositories, evidence repositories | the release is pinned by the assessment, not by the page |
| SQLAlchemy models, any ORM | the interface has no database |
| `risk_engine.py`, `gemini_report_generator.py` | legacy modules, frozen |
| candidate ranking, any LLM adapter | there is nothing to rank and nothing to generate |

**One exemption.** `apps/web/demo_migration.py` imports
`pgx.engine.phenotype_normalization.normalize_profile` to canonicalise the six
legacy demo profiles. The alternative was a second normaliser inside the web
layer, which is the exact failure SAFETY-INV-004 exists to prevent — two
implementations of "what does this phenotype string mean" that drift. Two
compensating tests hold the exemption down: it reaches that one module and no
other, and no runtime module imports `demo_migration` (it is a build-time
migration, run by `python -m apps.web.artifacts`).

## Why `apps/web` is a separate package

`apps/api` and `apps/web` are siblings. Neither imports the other's routers.
The API ships no template directory, no static directory and no HTML response,
and `tests/unit/api/test_wp16_boundaries.py` asserts all three — so the API's
OpenAPI document cannot acquire an HTML route even in principle, because the
document is generated from the API route table and no page is in it.

They share two things deliberately: `apps/api/provider.py` (the composition
container, extracted at WP-17 so that composing an application does not
require a web framework to be installed) and `apps/api/security.py` (the
principal and role model, so the interface cannot establish an identity the
API would not).

## The framework split

Twenty-two of the twenty-five modules under `apps/web` import no web framework
at all. They hold every decision this layer makes: the route table, the labels,
the view models, the claim gate, the case catalogue, the migration, the
security headers, the error mapping — and the dependency container, which was
the reason `ServiceProvider` moved out of `apps/api/dependencies.py`. Three
modules — `factory.py`, `main.py` and `routers/pages.py` — are the FastAPI
binding, and they contain no decision that is not read from the framework-free
half.

This split is not a style preference. It was built where FastAPI, Starlette,
Pydantic, HTTPX, Uvicorn and python-multipart could not be installed, so the
framework-free half had to hold everything worth testing — and it does:
`tests/unit/web` executes it in 276 tests wherever Jinja2 is present, with no
web framework at all.

The binding is covered by `tests/integration/web/test_asgi_web.py` (21 tests),
which **has since run** against a real ASGI stack, and by
`tests/integration/web/test_browser_e2e.py`, which has run against a real
Chromium. Both skip, naming the exact missing packages, on a host that lacks
them. See `docs/evidence/wp17-ui-verification.md` for which environment ran
what.

The two providers this layer composes are worth naming here, because getting
one of them wrong made every page unreachable without a single test noticing.
`WebProvider` carries what the interface owns — the client, the case
catalogue, the CSRF verifier. The API's `ServiceProvider` carries the principal
resolver, and it must be on `app.state.provider`, because every page route is
guarded by WP-16's `require_access` and FastAPI resolves that dependency
*before* the handler decides whether the route is public. A web-only
application composed with only the first answered `SERVICE_NOT_READY` on all
eleven routes, the public ones included.

## The route table is the surface

`apps/web/routes.py` declares eleven routes. A router cannot introduce a
twelfth: every handler is registered from a `WebRoute` entry, and the table
checks itself at import time — no duplicate paths or names, no path that
shadows `/api/`, `/health/` or `/openapi`, and no POST route without
`requires_csrf`. `WebRoute.url()` is the only way a template obtains a link,
so no template contains a hand-written path.

See `docs/web/route-contract.md` for the table itself.

## The global page contract

Every page, without exception:

- carries the canonical research/prototype warning, fetched from
  `pgx/domain/claims.py` on every build. No template contains a copy of the
  text; a literal would be a second version that survives a change to the
  governed one, and the stale copy is the one a reader would see.
- renders that warning inside `<main>`, immediately after the `<h1>`, so the
  heading order is `h1` then the warning's `h2` rather than the reverse.
- is not dismissible: no close control, no script that hides it, no CSS class
  that collapses it.
- is Turkish-primary, with every label drawn from WP-15's tables via
  `pgx/reporting/templates.py`. There is no second label vocabulary.
- carries `Cache-Control: no-store`, `X-Frame-Options: DENY` and a
  content-security policy that begins `default-src 'none'`.

## Attention and coverage are one component

`templates/_status_pair.html` is the only renderer of attention or coverage
anywhere in the interface. There is no attention-only partial and no
coverage-only partial, and `StatusPair` refuses construction without both
values — so "show attention without coverage" is not something this layer can
express. That is the structural half of SAFETY-INV-001; the readable half is
that both render their governed code as text beside their label, so colour
never carries the meaning alone.

## Fact preservation is enforced at render time, not in tests

`apps/web/view_models/preservation.py` names thirteen protected assessment
facts, projects them out of the WP-16 response and out of the built view
model, and compares. The check runs on **every assessment page**, not only
under test: a view model that dropped, reordered, rounded or relabelled a
protected fact raises before the page is served.

## What is not here

Authentication and sessions (WP-23), the validation architecture (WP-18), the
validation metrics (WP-21), and the expert-review workflow (WP-22). Each has a
screen; each screen says what it is waiting for and offers no control that
would appear to work. None of them is simulated. See
`docs/web/security-boundary.md` and `docs/evidence/wp17-ui-verification.md`.
