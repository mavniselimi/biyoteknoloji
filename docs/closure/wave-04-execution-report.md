# Execution Wave 4 — internal validation, operational evidence, product surface

| Work package | Verdict |
|---|---|
| WP-C10 validation catalogue and holdout closure | **COMPLETE** |
| WP-C11 benchmark and metrics | **COMPLETE** |
| WP-C13 operational evidence | **PARTIAL** |
| WP-C14A product surface and demo UX closure | **PARTIAL** |
| WP-C14 representative candidate demonstration | **BLOCKED** |

Every figure below is read from
`data/closure/wave-04-execution-manifest.json`, which is generated from the
artifacts. Results are labelled `INTERNAL_VALIDATION` and nothing stronger.

## 1. The validation catalogue (WP-C10) — COMPLETE

67 cases, sealed before any benchmark ran. The seal refuses to be rewritten,
which is the only arrangement in which an expected answer means anything:
after sealing, a disagreement is a recorded issue, not a corrected
expectation.

| Partition | Count | Expected answers derived from |
|---|---|---|
| `DEVELOPMENT` | 34 | the curation that produced the rules |
| `INTERNAL_HOLDOUT` | 21 | the scope decisions and the guideline's silences — **not** from any rule's outcome |
| `EXPERT_HOLDOUT` | 12 | **nothing; they carry no expected answer** |

Separation audit: **0 issues**.

The internal holdout is the partition that can actually fail. It tests
refusals and boundaries no rule states — a missing gene axis, an undeclared
care setting, an unsupported phenotype, an out-of-scope drug, an observation
on a gene the drug's axis does not name — so a ruleset can encode every rule
correctly and still fail it.

The expert-reserved partition carries no expected answer because recording one
would invent the judgment the reviewer is being asked for. Each case is an
input and a question.

### The leakage detector earned its keep

The first expert partition asked good questions about single-drug
combinations, and the separation audit refused it. The development partition
enumerates every combination the rules encode, so any single-drug question
about a covered combination has the same content fingerprint as a case the
build has already been scored on — a reserved case that duplicates a
development case tells a reviewer nothing new.

The reserved cases are now multi-drug requests, mixed covered and out-of-scope
requests, and requests carrying an observation the drug's axis does not name:
shapes the development partition does not contain, and shapes a real user
would produce.

## 2. The benchmark (WP-C11) — COMPLETE

Thresholds are declared in `scripts/run_wave04_benchmark.py` **above the code
that measures anything**. A threshold chosen after seeing a number is a
description of the number.

| Metric | Threshold | Observed | |
|---|---|---|---|
| attention agreement | ≥ 1.0 | 1.0 | met |
| coverage agreement | ≥ 1.0 | 1.0 | met |
| refusal correctness | ≥ 1.0 | 1.0 | met |
| **unsafe false reassurance** | **= 0** | **0** | **met** |
| evidence traceability | ≥ 1.0 | 1.0 | met |
| deterministic repeatability | ≥ 1.0 | 1.0 | met |
| system failure rate | = 0.0 | 0.0 | met |
| expert-reserved payloads read | = 0 | 0 | met |

55 cases scored, 0 failures. Latency p50 5.128 ms, p95 5.303 ms.

Unsafe false reassurance counts cases where the release reported an attention
level *weaker* than expected, or reported `NO_ACTIVE_ATTENTION` where a
refusal was expected. Its threshold is zero and is not negotiable: every other
metric can degrade and leave a candidate demonstration honest, and this one
cannot.

**What this does not establish.** The rules, the cases and two of the three
partitions' expectations share one author. This measures whether the software
does what that author intended.

## 3. Operational evidence (WP-C13) — PARTIAL

### Verified

**A real PostgreSQL migration round-trip.** PostgreSQL 16.13, database
`pgx_w4`, all 12 migrations applied to head `0012_wave03b_candidate_capture`,
65 tables. Alembic could not connect — no `psycopg` driver on any reachable
host — so the upgrade was emitted with `alembic upgrade head --sql` in offline
mode and applied through `psql` with `ON_ERROR_STOP=1`.

Both new vocabulary values were exercised against the live constraints:

| Constraint | Accepts | Rejects |
|---|---|---|
| `ck_source_policies_acquisition_mode_enum` | `AGENT_TARGETED_RETRIEVAL` | `SCRAPED` |
| `ck_raw_snapshots_kind_enum` | `TRANSCRIPTION_CAPTURE` | `SCRAPE` |

**The round-trip found a real defect in migration 0012.** It passed the full
constraint name to `op.create_check_constraint`, and the metadata naming
convention `ck_%(table_name)s_%(constraint_name)s` prefixed it again, producing
`ck_source_policies_ck_source_policies_acquisition_mode_enum`. The check still
worked, under a name no later migration could drop. The emitted SQL reads
correctly either way; only applying it to a real server surfaced this. Fixed by
passing the suffix and letting the convention compose the name.

**The application runs.** `apps.web.main:app` served by uvicorn 0.46.0,
startup complete, pages rendered.

**1,000 assessments.** p50 5.135 ms, p95 5.851 ms, p99 6.556 ms, max 17.341
ms, 0 errors. In-process, single-threaded, no HTTP, no database — stated in
the artifact, because a latency figure without its stack is a number without a
question.

### Blocked, each with a measured reason

`OR-01` `uv.lock` · `OR-02` CI linter pins · `OR-03` CI action SHAs · `OR-04`
wheel and sdist · `OR-05` `psycopg` · `OR-06` container image and SBOM ·
`OR-07` staging deployment · `OR-10` WP-19 verification artifacts · `W4-01`
the authenticated web flow.

A localhost process in an ephemeral container is not staging and is not
described as one.

## 4. Product surface (WP-C14A) — PARTIAL

15 web routes and 14 API routes audited. Nine states verified through Chromium
at 1440×900, with screenshots in `data/web/wave-04-browser/`.

| State | HTTP | |
|---|---|---|
| `/` landing | 200 | renders |
| `/login` | 200 | renders |
| `/system` | 200 | renders, reports `NOT_READY` per component |
| `/cases` | 503 | `AUTHENTICATION_NOT_CONFIGURED` |
| `/validation` | 503 | `AUTHENTICATION_NOT_CONFIGURED` |
| `/assessments/{id}` | 503 | `AUTHENTICATION_NOT_CONFIGURED` |
| `/evidence/{id}` | 503 | `AUTHENTICATION_NOT_CONFIGURED` |
| `/expert-reviews/{id}` | 503 | `AUTHENTICATION_NOT_CONFIGURED` |
| `/no-such-page` | 404 | honest not-found |

The canonical clinical warning appears on **every** page including the error
states, navigation is present on every page, and no page overflows the
viewport. The console errors are the 404 and 503 responses themselves, not
JavaScript faults.

### What the blocked states get right

The 503 is not a fault. It reads, in Turkish: *"No authentication provider is
configured in this deployment. This is not a request error, it is an
incomplete installation"*, followed by *"An incomplete or inconsistent result
is not shown in part. This page stands in place of a half-assessment."* That
is the fail-closed behaviour WP-C14A asks for, working.

`/system` is the most useful page for a jury: it lists every readiness
component with its blocking status and a sentence saying why, including
*"The claim boundary has not been approved by the named human and scientific
reviewers. This is a governance gate, not a fault."*

### What is not done

**The web surface is not wired to the candidate release.** `/system` reports
`active_release: No active release is registered`, and it is right to — the web
provider reads the *governed* active-release pointer and the candidate release
has its own. Wiring them is remaining work.

**Four of the six jury-flow screens are behind authentication**, which cannot
be composed without a session store, which needs a database driver that cannot
be installed on any reachable host. So the full Case Input → Assessment →
Finding Detail → Validation Dashboard → Expert Review → System Information walk
cannot be completed in a browser today. `docs/demo/jury-demo-runbook.md` states
this rather than leaving a demonstrator to discover it live.

## 5. Representative demonstration (WP-C14) — BLOCKED

Its prerequisites are a deployed web/API in a production-like environment and
a real PostgreSQL behind the application. The database exists and was
exercised. The deployment does not: a localhost process in an ephemeral
container is not staging, and relabelling it would be the misdescription this
project has refused throughout. Four of the six flow screens are additionally
unreachable for the reason in section 4.

WP-C14A was completed as far as the environment allows and WP-C14 is marked
BLOCKED, which is what the brief directs.

## 6. What remains unavailable

No external expert has seen any of this. No independent validation exists. No
clinical validation exists. The claim boundary is unapproved and reports
itself as unapproved. THS-6 is not closed and no gate in the THS-6 matrix was
touched.
