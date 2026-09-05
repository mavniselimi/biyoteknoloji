# WP-17 — Security boundary of the web interface

WP-16's boundary (`docs/api/security-boundary.md`) still holds; this document
covers only what the interface adds.

## What the interface accepts

Three path parameters, each pattern-constrained by the route table, and two
form fields on the two POST routes: a CSRF token and a list of medication
identifiers chosen from a rendered checkbox set.

That is the entire input surface. There is **no free-text field anywhere in the
interface** — no search box, no notes field, no comment, no file upload. A
route cannot grow one without failing
`tests/integration/web/test_asgi_web.py::test_no_route_accepts_free_text_or_an_uploaded_file`,
which reads the handler signatures rather than posting to them.

## What the interface refuses to accept, structurally

`apps/web/demo_cases.py` names 34 forbidden field names — `genotype`,
`diplotype`, `allele`, `vcf`, `patient_name`, `mrn`, `diagnosis`, `dose`,
`narrative`, and so on — and `DevelopmentCase.__post_init__` refuses any of
them at any nesting depth. A case that carried one could not be constructed,
so the catalogue cannot hold one and no page can display one.

The same constructor refuses any `case_role` other than `DEVELOPMENT`, and
refuses `is_validation_evidence` or `is_holdout` being true. See
`docs/web/demo-case-migration.md`.

## Authentication: an honest shell

There is none. `/login` renders a form that is **disabled**, with the reason
stated: authentication, sessions and password handling belong to WP-23.

- No credential is accepted, stored, compared or logged.
- No session cookie is set. There is no session store.
- `WebProvider` has **no field for a principal**. Principals come from WP-16's
  resolver through `apps/api/security.py`, so the interface cannot establish an
  identity the API would not.
- No production composition can create a test principal. The test principals
  live in `tests/fixtures/wp17/synthetic.py` and are reachable only from tests;
  `apps/web/main.py` composes `ServiceProvider` and `WebProvider` from settings
  alone.

`/logout` exists and verifies CSRF before doing anything, even though it has no
session to end — so the route cannot become a CSRF-exempt habit when WP-23
gives it something to do.

## CSRF: refused by default

`WebProvider.csrf` defaults to `UnconfiguredCsrf`, which refuses every token
and reports `configured = False`. Consequently `forms_available` is false and
every state-changing control renders **disabled with its reason** rather than
live. The fixture verifier (`StaticTokenCsrfVerifier`) is a single fixed
string, is refused outright by `WebSettings` in a production environment, and
is not a defence — it exists so the synthetic flow exercises the real
verification path instead of skipping it.

## Response headers

Set on every page by `apps/web/security.py`:

| Header | Value |
| --- | --- |
| `Content-Security-Policy` | `default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'` |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `no-referrer` |
| `Cross-Origin-Opener-Policy` | `same-origin` |
| `Cross-Origin-Resource-Policy` | `same-origin` |
| `Permissions-Policy` | camera, microphone, geolocation, payment, USB and five more all `()` |
| `Cache-Control` | `no-store` |

`default-src 'none'` rather than `'self'`: deny everything, then name the few
source types this origin actually serves. Every page also carries
`<meta name="robots" content="noindex, nofollow">`.

## No network egress from a page

No CDN, no remote font, no remote script, no analytics, no telemetry, no
external image. The only subresources are `/static/css/app.css` and
`/static/js/app.js`, both files in this repository. The claim gate's URL policy
permits **absolute internal paths, fragments and bare queries only — no scheme
of any kind**, so no parser has to decide which schemes are safe.

## The HTML claim-safety gate

`apps/web/claim_gate.py` scans every rendered page before it is served, over
four projections:

1. visible text, nodes joined with a space;
2. concatenated text, so markup inside a phrase does not break a match;
3. textual and `data-` attribute values, plus comments;
4. the raw markup.

Structural refusals: `INLINE_SCRIPT` (a `script` with no `src`, or with
content), `EVENT_HANDLER` (any `on*` attribute), `INLINE_STYLE`,
`EMBEDDED_CONTENT` (`iframe`, `object`, `embed`), `CONTROL_CHARACTER`.

Adversarial tests in `tests/unit/web/test_safety.py` attempt to smuggle a
prohibited claim through each projection — split across elements, hidden in an
attribute, placed in a comment, entity-encoded — and each attempt is refused.

### A limit of the scanner, stated rather than smoothed over

The scanner is **lexical**. It matches published patterns over folded text and
performs no semantic analysis. A clean scan is evidence that no published
pattern matched; it is never evidence that a page is safe.

One concrete asymmetry, discovered while building this layer and pinned by
`test_the_scanner_language_asymmetry_is_still_real`:

- The English string "…does not mean the medicine **is safe**…" is *matched and
  then suppressed*: the scanner sees the forbidden phrase, sees the denial
  around it, and reads the whole as a denial.
- The Turkish equivalent "…**güvenli olduğu anlamına gelmez**…" is *never
  matched at all*: no published pattern covers that construction, so the
  scanner reports neither a violation nor a suppression.

The two sentences say the same thing and the scanner treats them completely
differently. It follows that **a clean scan of a Turkish page is weaker
evidence than a clean scan of an English page**, and this interface is Turkish
first. The interface strings are therefore also checked a second way: every
string in the negation allowlist must contain an explicit denial marker in its
own language, asserted independently of the scanner. The allowlist is capped at
three entries so it cannot become a place things accumulate.

If the scanner gains a Turkish pattern for this construction, that test fails
and this section is updated rather than left stating something that stopped
being true.

## Errors leak nothing

Error pages carry a catalogue code and the request id. `map_exception` never
reads `str(error)`, so an exception message cannot reach a page. There is no
stack trace, no path, no SQL, no exception class name.

## Evidence provenance shows identity, not prose

The evidence page shows record identifiers, source policy identity, hashes and
counts. It renders **no source sentence, no abstract, no snippet and no
filesystem path** — reproducing a guideline's wording in a prototype interface
would be the clearest possible way to make it look like clinical advice.

## What has and has not been verified over HTTP

The header table above was checked against a real response from a real server:
`tests/integration/web/test_asgi_web.py` requests every page and compares each
header with `security_headers()`, and a browser confirmed the page issues **no
request to any origin but its own**.

Two things that were *not* true before that run, and are worth recording
because both were invisible until a request was actually made:

- **A web-only application refused every page.** Composed without the API's
  `ServiceProvider`, `require_access` could not resolve its dependency and all
  eleven routes answered `SERVICE_NOT_READY` — including the public ones,
  because FastAPI resolves that dependency before the handler runs.
  `create_web_app` now takes an `api_provider` and builds a fail-closed one
  when none is given.
- **API failures were rendered as HTML.** FastAPI keeps one handler per
  exception type, so mounting the interface's HTML handlers on the combined
  application replaced the API's JSON ones: `GET /api/v1/system/version` on an
  unconfigured deployment answered `503 text/html`, breaking the API
  contract's one unconditional promise. The handler now answers in the shape
  of whichever surface the path belongs to, decided by the same
  `RESERVED_PATH_PREFIXES` the route table uses to refuse shadowing.

Still not verified: anything requiring PostgreSQL, an active release, or a
human approval. Those are governance and environment states, not test gaps.
