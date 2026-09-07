# 14. The representative demonstration

Evidence: `data/closure/wave-04b-runtime-product-manifest.json` and
`docs/closure/wave-04b-runtime-product-report.md`.

## What was demonstrated, and where

A `LOCAL_REPRESENTATIVE_ENVIRONMENT`. Not external staging, and not described
as one.

| | |
|---|---|
| Database | PostgreSQL 16.13, migrated to head `0012_wave03b_candidate_capture` through the ordinary alembic path |
| Password hashing | argon2-cffi, Argon2id, exercised live |
| Web stack | FastAPI, Starlette, uvicorn, Jinja2, over TLS |
| Runtime track | `CANDIDATE`, explicitly set |
| Composed | authentication, CSRF, authorisation, rate limiting, audit sink and reader, user administration |
| LLM | off. No P1/P2 feature enabled. No uncontrolled network dependency. |
| Viewport | 1440×900 |

## The sixteen steps

Every navigation after sign-in is a click on a link in the page and every
submission a click on the form's own button, because the session cookie is
`__Host-pgx_session` with `SameSite=Strict`.

| Step | Result |
|---|---|
| landing, anonymous | 200 |
| anonymous request for a guarded page | **401** |
| unknown path | **404** |
| sign-in form | rendered, live |
| wrong password | refused |
| real sign-in | session established |
| case catalogue | 7 development cases |
| case input | four candidate drugs, care-setting control present |
| clopidogrel, no care setting | **`CARE_SETTING_NOT_DECLARED`** |
| clopidogrel in `ACS_OR_PCI` | answered; release and ruleset shown |
| amitriptyline over both genes | answered |
| amitriptyline without both | refused |
| validation dashboard | `INTERNAL_VALIDATION`, partition counts, limitations |
| system / release | candidate and governed tracks, separately |
| sign-out | session revoked |
| after sign-out | **401** |

The canonical clinical warning appeared on all sixteen pages. No horizontal
overflow on any. No expectation failure. The audit trail afterwards held
`USER_CREATED` ×2, `LOGIN_SUCCEEDED`, `LOGIN_FAILED`, `SESSION_CREATED` and
`LOGOUT`, in a hash chain.

## The demonstration cases are synthetic

Seven development cases, labelled as demonstration data in the interface.
Gene symbols, drug names, phenotype labels and a care setting from a closed
vocabulary. **No patient data has ever been in this system**, no VCF or other
genomic file format is supported, and there is no EHR integration.

## What you should look at

If you have access to the running application, drive it yourself; the runbook
is `docs/demo/jury-demo-runbook.md`. If you do not, the report above records
each step.

What is worth your attention is not whether the pages load. It is whether the
clopidogrel refusal, sitting next to three answered drugs, reads as *"nothing
to worry about here"* — and whether a joint amitriptyline finding is
distinguishable from the single-gene finding beside it. Questions **Q08** and
**Q09**.

## What the demonstration does not establish

That the software works outside one laptop-class environment; that it works
under load; that it works with more than a handful of users; that any answer
it gave was clinically correct. It establishes that the composed application
reaches the candidate release and refuses what it says it refuses.
