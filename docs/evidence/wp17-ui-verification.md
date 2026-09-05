# WP-17 — UI verification evidence

What was actually executed, and what was not. Every "not" below is an
environment or governance fact, not a test failure.

## Two runs, and which is which

WP-17 was **built** where no ASGI stack and no browser could be installed, and
the first version of this document recorded exactly that. It has since been
**run** where both exist. The two are kept apart rather than merged, because
"written and skipped" and "passed" are different claims and only one of them is
evidence.

| | Build environment | Runtime environment |
| --- | --- | --- |
| Python | 3.10.12 | 3.11.15 |
| Jinja2 | 3.0.3 | 3.1.6 |
| FastAPI / Starlette | absent | 0.141.1 / 1.6.0 |
| Pydantic / Uvicorn / HTTPX | absent | 2.13.3 / 0.46.0 / 0.28.1 |
| python-multipart / lxml | absent | 0.0.26 / 6.1.0 |
| SQLAlchemy / Alembic | absent | 2.0.52 / 1.19.1 |
| Playwright + browser | absent | 1.62 + **Chromium 141.0.7390.37** |
| PostgreSQL | not running | **not running** |
| psycopg | absent | absent |

The FastAPI, Starlette, SQLAlchemy and Alembic versions in the runtime
environment are the ones installed in the repository host's own virtualenv. The
run therefore establishes that *this source at these package versions* serves
and behaves as described. It does not on its own establish anything about a
different interpreter version — re-running the same commands on the
repository's own host is one command each, and the handoff asks for it first.

## What executed in the runtime environment

| Suite | Tests | Result |
| --- | --- | --- |
| `tests/failure/test_domain_layer_violations.py` | 18 | pass |
| `tests/integration/api/test_asgi_runtime.py` | 27 | 26 pass, 1 skip |
| `tests/integration/web/test_asgi_web.py` | 21 | pass |
| `tests/integration/web/test_browser_e2e.py` | 13 | 11 pass, 2 skip |
| `tests/unit/web/` | 276 | 275 pass, 1 skip |
| Full suite | 5334 | 1 environment-only failure, 0 errors, 20 skips |

The API suite's single skip is `TestTheSkipIsHonest`, which by construction
applies only when the framework is *absent*; it now reports "the framework is
installed; the runtime tests ran". The browser suite's two skips are the
honesty checks that apply only on a host with no browser.

**The one full-suite failure is a privilege artifact, not a defect.**
`test_the_sealed_tree_is_read_only_where_supported` expects a `PermissionError`
when appending to a `0444` file; the runtime environment runs as `uid 0`, and
root ignores the mode bit. Re-run as an unprivileged user in the same
container, the same test passes. It passes on the repository's own host, which
does not run as root.

## What the web ASGI run actually exercised

Every declared GET route requested over HTTP and answered `200 text/html`, with
the token matching each route's policy — the expert-review screen is the one
route a demo principal may not reach, and it is requested with the reviewer
token rather than skipped. Both POST routes exercised with and without a CSRF
token. The static mount checked for directory listing and for path traversal.
The combined application's served OpenAPI document compared against the
committed artifact and identical, with no page path in it.

## Browser evidence: CAPTURED

Seven captures, in `tests/fixtures/wp17/browser/`:

`home.png`, `login.png`, `cases.png`, `case-detail.png`, `validation.png`,
`expert-review.png`, `system.png`

Every one is a real full-page capture of a real page from a real browser,
written by `test_every_page_is_captured` while Chromium was running against a
Uvicorn server on loopback that answered 200 for each. Nothing was drawn,
mocked or edited.

**What is in them.** `cases.png` and `case-detail.png` show public gene
symbols — CYP1A2, CYP2C19, CYP2C9, CYP2D6, CYP3A4 — because the six migrated
development cases name them and the migration deliberately kept the gene
identities rather than inventing substitutes. A gene symbol is published
nomenclature; it is not data about a person. Everything around it is
synthetic: the cases are development fixtures built by
`apps/web/demo_migration.py`, the assessments are computed against the WP-14
synthetic TESTGENE ruleset, and the evidence records are fixture constants.

**No real patient data, no real person, and no validation evidence appears in
any capture.** That is the claim these images support, and it is narrower than
"nothing real appears" — which would have been false the moment a gene symbol
was rendered.

Behaviour the browser established, which nothing else could:

- the clinical warning is visible in a 1280×800 viewport without scrolling;
- it survives a key press aimed at dismissing it, because nothing exists that
  could dismiss it;
- the page is usable with JavaScript disabled — the warning renders and the
  navigation links are present;
- each status pair keeps its attention and coverage halves together in a
  640×480 viewport;
- every interactive element is reachable by keyboard;
- the page issues **no request to any origin but its own**;
- the console is clean: no error, no page error.

`data/web/wp17-real-gate-status.json` records:

```
browser_runtime_available:    true
managed_browser_launchable:   true
managed_browser_version:      "141.0.7390.37"
screenshot_evidence_status:   "CAPTURED"
screenshot_evidence_count:    7
```

Those are measurements of the host that produced them and change on another
machine. Regenerating is `python -m apps.web.artifacts`.

### How availability is decided, and why it needed fixing

`_BROWSER_BINARIES` used to contain the string `playwright`. That is the Python
package's console script, so `shutil.which` found it the moment the package was
installed and the gate status reported a browser on a host that had none —
while `test_browser_e2e.py`, using a different list that omitted Playwright
entirely, skipped on a host that had one. Both were wrong about the same
machine, in opposite directions, and each looked reasonable on its own.

Availability is now one measurement, `apps.web.gate_status.managed_browser_status()`,
shared by the gate status and the test module. It imports Playwright, resolves
the executable it would launch, checks the file exists, then **launches it and
reads its version**. A package is not a browser; a resolved path is not a
browser; a browser is a process that answered.

## HTML snapshots: rendered output, not captures

`tests/fixtures/wp17/snapshots/` holds **eight rendered HTML files**, and they
are a different kind of artifact from the PNGs above. Each begins with:

```html
<!-- Rendered template output from the WP-17 synthetic fixtures.
     Not a screenshot. Not a browser capture. Not real data. -->
```

They are the exact bytes the template layer produces for fixed synthetic
inputs, so a template change shows up as a readable diff.
`tests/unit/web/test_snapshots.py` re-renders each one and fails if it is
stale, and re-applies the whole page contract — canonical warning, claim gate,
one `h1`, landmarks, no remote origin — to the committed bytes.

**Three pages are deliberately not snapshotted:** the two assessment pages and
the system page each carry a value that is new on every run (an assessment
identifier allocated at submission; the fingerprint of a frozen ruleset built
into a fresh temporary directory). Committing them would mean either a file
that fails every run or a file with those values quietly edited out — and an
artifact with its volatile parts overwritten is exactly the kind of doctored
evidence this work package may not produce.

## How the API side records that it ran

The WP-17 suites report themselves through the test runner. WP-16's do not:
its gate status is a committed artifact, and an artifact cannot notice that a
suite has since been run. It used to hard-code `asgi_runtime_tests_executed:
false` and an OpenAPI `runtime_verification: BLOCKED`, and went on saying both
after the ASGI suite had executed and passed.

That is now recorded rather than assumed. `python -m
apps.api.runtime_verification` composes the application, serves
`/openapi.json` and compares it with the committed artifact, answers a
liveness probe, runs `tests/integration/api/test_asgi_runtime.py`, and writes
the outcome to `data/api/wp16-runtime-verification.json`. Absent evidence,
failed evidence and evidence whose inputs have changed all read as `BLOCKED`.
Installed dependencies never make the flag true — the packages being present
says nothing about whether anything ran.

## What did not execute, and the exact reason

| Not executed | Reason |
| --- | --- |
| Any PostgreSQL query | no server is running in either environment; `postgresql_runtime_available: false` |
| Any real assessment or report | no active release; the API answers `ACTIVE_RELEASE_UNAVAILABLE` |
| Anything presented as approved | claim boundary is P0, `is_approved: false` |
| Any authenticated session | there is none to test; WP-23 |
| Any accessibility audit | no axe or equivalent is installed |

## What a browser still could not verify

| Requirement | Status |
| --- | --- |
| 1.4.3 / 1.4.11 contrast ratios | **UNVERIFIED** — no measuring tool; the values were chosen against the thresholds arithmetically |
| 4.1.2 assistive-technology announcement | **UNVERIFIED** — no screen reader, and no automated substitute exists |
| WCAG 2.1 AA conformance as a whole | **UNVERIFIED** — nothing here is an audit |

`docs/web/accessibility-checklist.md` marks every row with the test that
established it, or with the reason it remains open.

## Fact preservation: enforced at runtime

`apps/web/view_models/preservation.py` names thirteen protected assessment
facts, projects them out of the WP-16 response and out of the built view model,
and compares. **This runs on every assessment page, not only in tests.** A view
model that dropped, reordered, rounded or relabelled a protected fact raises
before the page is served.

`test_view_models.py` attacks it directly: reordering findings, rounding a
count, substituting a label for a code, and dropping an axis each fail the
check.

## Claim safety: executed against real HTML

The claim gate ran against every rendered page produced by the suite —
`claim_scan_executed: true`, `claim_scan_clean: true` in the gate status. The
adversarial tests attempt to smuggle a prohibited claim through each of the
four scanned projections and each attempt is refused.

One real limitation was found and is documented rather than smoothed over: the
scanner is lexical with uneven per-language coverage, and the Turkish
construction "güvenli olduğu anlamına gelmez" is never matched at all where its
English equivalent is matched-and-suppressed. Since this interface is Turkish
first, a clean scan here is *weaker* evidence than a clean scan of an English
page. `docs/web/security-boundary.md` states this; a test pins it so the
documentation fails if the scanner ever changes.

## The claim boundary

`DEFAULT_CLAIM_BOUNDARY` is phase P0, `is_approved: false`, status
`DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW`. Nothing in WP-17 changes that,
and no page presents anything as approved.

## Gate status

`data/web/wp17-real-gate-status.json` is generated by
`python -m apps.web.artifacts` from the filesystem and the interpreter, not
written by hand. In the runtime environment **five** blockers remain, all
`blocking: true`:

`WEB_NO_ACTIVE_RELEASE`, `WEB_CLAIM_BOUNDARY_NOT_APPROVED`,
`WEB_AUTHENTICATION_NOT_IMPLEMENTED`, `WEB_EXPERT_REVIEW_NOT_IMPLEMENTED`,
`WEB_VALIDATION_ARCHITECTURE_UNAVAILABLE`.

`WEB_ASGI_RUNTIME_UNAVAILABLE` and `WEB_BROWSER_RUNTIME_UNAVAILABLE` are absent
because those runtimes are present — not because anything was relaxed. On a
host without them they return, with the same detail text.

`may_serve_real_traffic: false`. `real_assessment_count: 0`,
`real_report_count: 0`, `real_validation_case_count: 0`.
`holdout_case_count: null` — null rather than zero, because holdout storage is
not implemented, so no count was taken and reporting `0` would be a measurement
that never happened.
