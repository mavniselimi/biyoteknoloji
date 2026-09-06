# Execution Wave 4B — runtime and product closure

| Work package | Verdict |
|---|---|
| WP-C14A product surface and demo UX closure | **PASS** |
| WP-C14 representative candidate demonstration | **PASS** |

Every figure below is read from
`data/closure/wave-04b-runtime-product-manifest.json`, which is generated from
the artifacts and from the composed application itself, and which rebuilds
byte-identically.

```
COMPLETE CANDIDATE PROJECT
SOURCE_GROUNDED
PROJECT_TEAM_PROVISIONAL
INTERNALLY_VALIDATED
PENDING_EXTERNAL_EXPERT_REVIEW
```

That vocabulary is available only because WP-C14A and WP-C14 now pass on
measurement. Nothing in it says approved, reviewed, validated by anyone
outside this project, or fit for clinical use — see section 8.

## 1. What Wave 4B started from

Wave 4B began at `fab7c8d` with the status Wave 4's correction left behind:
the candidate scientific engine complete, the internal benchmark complete, and
the runtime and product composition **incomplete**. Three defects stood
between the candidate release and a browser, and each one had been invisible
for a different reason.

## 2. The port collision

The project owner's Docker PostgreSQL started cleanly and every migration and
bootstrap attempt failed with `role "pgx_dev" does not exist`. A native macOS
PostgreSQL was already listening on `127.0.0.1:5432`, so the container's
published port was shadowed and every connection reached the other server —
which answered, and then refused a role it had never heard of.

The compose default moved to **55433**; `.env.example` moves with it and
`POSTGRES_HOST_PORT` still overrides. Nothing was stopped, reset or deleted:
the native PostgreSQL is untouched, no volume was removed, no database was
dropped. The port-consistency guards in `test_packaging_and_environment.py`
already required the published port and `DATABASE_URL` to agree, and they held
the change together.

## 3. Every governed mutation over HTTP was rolled back

WP-24 built `RequestScope.governed_transaction` and **nothing under `apps/`
ever entered it**. `RequestScope.close` rolls back anything uncommitted, so
every governed mutation served over HTTP was flushed and then discarded.

The symptom was the worst kind available. A login authenticated the user,
wrote the session row, appended `LOGIN_SUCCEEDED` and `SESSION_CREATED`,
returned `Set-Cookie` — and then the scope closed and rolled all of it back.
The browser held a token for a session the store had never heard of, the next
request answered 401, and nothing raised, logged or recorded a failure. The
login *looked* like it worked. Two earlier runs read that as a CSRF or cookie
problem and were wrong; the reproduction that settled it was a POST returning
a session cookie followed by a `SELECT` finding no session row.

Every WP-23 unit test passed throughout, because each drives the service
directly and opens its own transaction. The middleware is the only place the
mistake was visible, so that is where the tests now look.

`RequestScopeMiddleware` opens the transaction for unsafe methods only. A
`GET` opens none; a `POST` that returns a refusal still commits, because a
refusal the audit trail recorded is a refusal that happened; a `POST` that
raises rolls the change and its audit row back together.

## 4. Three stale WP-17 assumptions, each true when written

Every state-changing form on the interface was disabled, for three
independent reasons that had all become false when WP-23 shipped session CSRF:

| | What it asked | Why the answer was wrong |
|---|---|---|
| `WebSettings.csrf_configured` | hard-coded `False` | its comment said no verifier existed; `SessionBoundCsrfVerifier` had existed since WP-23 and the login form was already using it |
| `WebProvider.forms_available` | is the module-level verifier configured? | that verifier is the *refusing* one, so the answer is `False` on exactly the deployments able to offer a form |
| `build_login_page` | drop the CSRF token when the login form is disabled | which is precisely when a visitor is signed in and looking at a **logout** button; every sign-out failed CSRF with 403 |

`csrf_configured` is now derived from `production_authentication_available` —
`SESSION` only, because a token is bound to a session's secret and a static
development token has none. A deployment on static tokens keeps its forms
disabled exactly as before.

## 5. The environment

`LOCAL_REPRESENTATIVE_ENVIRONMENT`. Not external staging, and not described as
one.

| | |
|---|---|
| Database | PostgreSQL 16.13, migrated to `0012_wave03b_candidate_capture` through the ordinary alembic path over psycopg — not SQL text |
| Driver | psycopg 3.2.10, built from upstream source (no package index is reachable from either host) |
| Password hashing | argon2-cffi 25.1.0 with its vendored reference implementation, Argon2id verified live |
| Web stack | fastapi 0.141.1, starlette, uvicorn 0.46.0, jinja2 3.1.6, python-multipart 0.0.26, pydantic 2.13.3 |
| Browser | Chromium via playwright 1.56.0 at 1440×900 |
| Composed | authentication, CSRF, authorisation, rate limiting, audit sink and reader, user administration — all measured, not declared |
| LLM | off. No P1/P2 feature is enabled. No uncontrolled network dependency. |

**This ran in the session's Linux container, not on the owner's Mac.** The
collision fix is in the repository and applies there; the demonstration itself
has not yet been executed on that machine.

## 6. What the browser did

Sixteen steps, every navigation a click on a link in the page and every
submission a click on the form's own button — because the session cookie is
`__Host-pgx_session` with `SameSite=Strict`, and Chromium withholds a Strict
cookie on a driver-initiated navigation with no same-site initiator. A harness
built on `page.goto` reports 401 for pages a clicking human reaches, which is
the wrong conclusion drawn from a real observation.

| Step | Result |
|---|---|
| landing, anonymous | 200 |
| anonymous request for a guarded page | **401** |
| unknown path | **404** |
| login form | rendered, live |
| wrong password | refused |
| real login | session established, `__Host-pgx_session` set |
| case catalogue | 7 development cases |
| case input | four candidate drugs, care-setting control present |
| clopidogrel, no care setting | **`CARE_SETTING_NOT_DECLARED`** |
| clopidogrel in `ACS_OR_PCI` | answered, release and ruleset shown |
| amitriptyline over both genes | answered |
| amitriptyline without both | refused |
| validation dashboard | `INTERNAL_VALIDATION`, partition counts, limitations |
| system / release | candidate and governed tracks, separately |
| logout | session revoked |
| after logout | **401** |

Canonical clinical warning on **all sixteen**. No horizontal overflow on any.
No expectation failure. The three console errors are the 401 and 404 the walk
deliberately visits.

Audit trail after the run: `USER_CREATED` ×2, `LOGIN_SUCCEEDED`,
`LOGIN_FAILED`, `SESSION_CREATED`, `LOGOUT` — all persisted, in a chain whose
second event could not have been written a day ago.

## 7. What the candidate demonstration shows

| | |
|---|---|
| Release | `PGX-CANDIDATE-REL-20260906-001` |
| Manifest hash | `sha256:0cd22a88…581d01` |
| Dataset | `PGX-DATA-20260906-001` |
| Ruleset | `PGX-CANDIDATE-RULESET-WAVE03B` / `sha256:29ca1949…c7c71a` |
| Authority | `PROJECT_TEAM_PROVISIONAL` |
| Review state | `PENDING_EXTERNAL_EXPERT_REVIEW` |
| Claim boundary approved | **false** |

The assessment page carries all of it, on every result, alongside the refusal
list and the evidence lineage — capture record ids, citations, the matched
rule key and its content hash, and whether the rule was joint or single-gene.

## 8. What is still not available

- **No external expert has reviewed any of this.** The twelve expert-reserved
  cases remain sealed and carry no expected answers.
- No independent validation exists. No clinical validation exists.
- The candidate source policy is still `PENDING_REVIEW`, and the ordinary DQ
  gate still fails on `SNAPSHOT_COMPLETENESS_UNKNOWN` and
  `SOURCE_POLICY_NOT_APPROVED`.
- The candidate DQ decision keeps `permits_transition = false`. Candidate-only
  acceptance is not governed publication approval, and this wave did not make
  it one.
- The candidate release is **not** registered in the WP-13 governed registry.
  The governed active-release pointer does not exist and was not written.
- THS-6 is not closed and no THS-6 gate was touched.
- `OR-01`…`OR-04`, `OR-06`, `OR-07` and `OR-10` remain blocked on network
  egress and on hosts neither environment has. `OR-05` is cleared: the ORM
  path is exercised.

## 9. Wave 5 entry

The Wave 4B exit gate passes on the twelve items it names. Wave 5's autonomous
scope — freezing the evaluated version, assembling the external-expert
evaluation package, preparing the reviewer workflow and the post-review
machinery, and building a `PRE-EXPERT / NOT FINAL` evidence inventory — can
begin. WP-C12 itself cannot: a real external expert response is a human step,
and nothing in this repository may author it.
