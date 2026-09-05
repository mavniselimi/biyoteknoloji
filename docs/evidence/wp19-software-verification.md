# WP-19 - Software verification evidence

| Field | Value |
|---|---|
| Document ID | `DOC-WP19-004` |
| Work package | WP-19 |
| Machine-readable | `data/verification/wp19-real-gate-status.json` |
| Recorded run | `data/verification/wp19-verification-run.json` |
| Produced on | Linux, CPython 3.11, `uid 0`, no PostgreSQL, no `coverage.py` |

> **Software verification only.** A green suite means the software behaved as
> its tests describe. It is not a validated ruleset, a reviewed validation
> case, an expert opinion, a clinical result, or an approval. No holdout case,
> metric, expert review or human signature exists, and none was produced here.

---

## 1. What was measured, and where

Two environments, kept apart in every claim below.

| | This run | The developer's macOS `.venv` |
|---|---|---|
| Platform | Linux, CPython 3.11.15 | macOS, CPython 3.14.7 |
| Effective user | `uid 0` | ordinary account |
| `psycopg` | absent | 3.3.5, **no server started** |
| `coverage.py` | absent | absent |
| Playwright / Chromium | present, 141.x | present, 151.x |
| Package index reachable | no | not attempted |

The recorded run carries a digest over every `.py` file in `pgx`, `apps` and
`tests`, plus the platform and package versions. Change any of those and the
gate status reports `STALE_EVIDENCE_REJECTED` rather than quoting a result
about different code on a different machine. **This document is evidence about
the Linux run only.** The macOS numbers must come from a run there.

## 2. Discovery and inventory

| | Count |
|---|---:|
| Tests discovered | **5,964** |
| Test suites (modules) | **218** |
| Suites matching no category rule | **0** |
| Modules that failed to import | **0** |
| Required categories with no test | **0** of 16 |
| Requirements with no test | **0** of 20 |
| `P0_CRITICAL` suites serving no requirement | **0** |
| Safety invariants with nothing mapped | **0** of 10 |

Discovery uses `unittest`'s own loader, so the inventory and the suite that
runs are the same enumeration. A module matching no category rule is *refused*,
not defaulted to `UNIT`.

## 3. The gap the inventory found first

`unittest` reports a failing `setUpClass` as **one** skip and never mentions the
tests inside that class.

| | Count |
|---|---:|
| Class-level skips the runner reports | 16 |
| Individual tests they suppress | **77** |
| `Ran N tests` printed by `unittest discover` | 5,887 |
| Tests that actually exist | **5,964** |

The 77 are the PostgreSQL integration suite. Before WP-19 they were invisible:
the runner's own output showed sixteen skip lines and a total that silently
excluded them. The gate status now reports `discovered_test_count` and
`executed` as separate fields, and `POSTGRESQL_INTEGRATION` as `BLOCKED` with
every suppressed identifier named.

## 4. Execution

Profile `full`, run in a fresh interpreter with `PYTHONHASHSEED=20260904`,
`PYTHONDONTWRITEBYTECODE=1`, `PYTHONWARNINGS=error::ResourceWarning`, and
non-loopback network connections refused.

| | Count |
|---|---:|
| Discovered | 5,964 |
| Executed | 5,964 |
| Passed | 5,882 |
| Failed | **0** |
| Errored | **0** |
| Skipped | **82** |
| **Unexplained skips** | **0** |
| Not executed | 0 |

Every skip is classified against the policy its inventory entry declares:

| Skips | Suite | Why |
|---:|---|---|
| 77 | `tests.integration.db.*` | `psycopg` absent; no disposable PostgreSQL. **BLOCKED, not passed.** |
| 3 | ASGI / browser / httpx honesty checks | inverted: they check another test's skip message and stand down when that dependency is present |
| 1 | `tests.unit.verification.test_coverage_and_database` | inverted: the measured-coverage path cannot run without `coverage.py` |
| 1 | `tests.unit.verification.test_filesystem_capability` | inverted: this platform *can* drop privileges, so the cannot-drop path is unreachable |

The 77 PostgreSQL skips are 72 in `POSTGRESQL_INTEGRATION` and 5 in
`MIGRATION`; the two categories are separate so that a report cannot show
migrations as green while every database test skipped.

**Zero unexplained skips.** A skip whose reason does not match one of the
substrings its suite declares is `UNEXPLAINED` and fails the profile.

### 4.1 Output a CI job must not parse

Two tests print `CONFIGURATION_FAILURE` on standard output **while passing**:

```
CONFIGURATION_FAILURE: allowlist entry XDIFF-LEGACY-BUG-001 references unknown bug id 'NOT-A-BUG'
CONFIGURATION_FAILURE: candidate input does not exist: <tmp>/wp01-harness-.../missing.json
```

They are negative tests demonstrating that a misconfiguration is reported
rather than silently accepted. A job that searched output for those words would
fail a green suite. Outcomes come from the runner's recorded result, which is
what `pgx-verify --format json` returns and what the exit code reflects.

## 5. The repaired sealed-tree test

**Before.** `tests/unit/snapshots/test_snapshot_build.py` asserted the manifest
was `0o444` *and* that appending raised `PermissionError`. As `uid 0` the second
fails, because the superuser is exempt from mode-bit checks. The suite reported
one failure on a tree that was perfectly well sealed, and leaked a file handle
doing so:

```
FAIL: test_the_sealed_tree_is_read_only_where_supported
AssertionError: PermissionError not raised
ResourceWarning: unclosed file .../manifest.json
```

**After.** The two questions are separated, and a third is asked that the old
test never did.

| Question | How it is answered | Result here |
|---|---|---|
| Are the mode bits right? | `denies_all_writers`: no write bit for owner, group or other | PASS, never skipped |
| Is a writer subject to those bits refused? | fork, drop to `nobody` **as the file's owner**, attempt a zero-byte append | **PASS - executed, not skipped** |
| Could that attempt have told the difference? | `discriminating` is true only when the writer owned the file | PASS |

The third question is the one that matters. A child running as `nobody` is
refused by a `0o644` file too, because it is not the owner - so an attempt like
that would report a tree its owner could rewrite at will as sealed. Ownership of
the *test's own scratch file* is transferred for the duration of the attempt and
restored in a `finally`.

**Proof it cannot hide a writable tree.**
`TestThePortabilityHandlingCannotHideAWritableTree` seals a snapshot for real,
relaxes one artifact, and requires the same helper to report it `PERMITTED`:

| Mode | `denies_all_writers` | Mutation attempt |
|---|---|---|
| `0o444` | true | **REFUSED** |
| `0o644` | false | **PERMITTED** |
| `0o666` | false | **PERMITTED** |
| `0o600` | false | **PERMITTED** |

Plus: the probe leaves content, mode, ownership, size and modification time
unchanged; it writes no scratch inside the sealed tree; and it changes no mode
inside it. The only permission it touches is the test's own `mkdtemp` root,
raised to `0o701` - traverse, not read, not write - because `nobody` cannot
otherwise reach the file, and a refusal caused by the scratch directory would
say nothing about the snapshot.

Result: **34 tests in `test_snapshot_build`, zero skips, zero failures**, where
before there was one unfixable failure and no unprivileged attempt at all.

## 6. Coverage - BLOCKED

```
status         BLOCKED
line percent   null
branch percent null
tool version   null
reason         coverage.py is not importable in this interpreter, so no line or
               branch percentage has been measured.
```

`coverage.py` is absent from this container **and** from the developer's macOS
`.venv` (verified by reading its `site-packages`), and no package index is
reachable from here.

What was done instead of inventing a number:

- `coverage[toml]>=7.4,<8.0` added to the `dev` dependency group;
- `[tool.coverage.run]` with `branch = true`, `source = ["pgx", "apps"]`, and an
  `omit` list excluding the tests, the frozen WP-01 baseline scripts and their
  tooling, generated revision scripts and data artifacts;
- `[tool.coverage.report]` with `show_missing`, and **no `fail_under`**;
- the `omit` list is read back from `pyproject.toml` at runtime, so the artifact
  cannot describe exclusions the tool is not applying.

**No percentage is reported, estimated, carried over, or replaced with zero.**
`null` is what an unmeasured number looks like; `0.0` would mean the tool ran
and found nothing executed.

`DECLARED_LINE_THRESHOLD = 80.0` lives in `pgx/verification/coverage_report.py`
and was written before any measurement was taken, so it cannot be the number
that happened to come out. It lists critical modules *for attention*; there is
deliberately no gate.

**To unblock, on macOS:**

```
.venv/bin/python -m pip install 'coverage[toml]>=7.4,<8.0'
.venv/bin/python -m pgx.application.verification_cli coverage --write
```

## 7. Reproducibility - REPRODUCIBLE

Four generators, each rebuilt twice in fresh interpreters under two different
non-zero hash seeds (`1` and `524287`), and compared with the committed bytes.

| Generator | Artifacts | Differed between runs | Stale in the tree |
|---|---:|---:|---:|
| `validation` (`pgx.application.validation_cli`) | 9 | 0 | 0 |
| `api` (`apps.api.artifacts`) | 8 | 0 | 0 |
| `web` (`apps.web.artifacts`) | 6 | 0 | 0 |
| `verification` (`pgx.verification.artifacts`) | 10 | 0 | 0 |
| **Total** | **33** | **0** | **0** |

Two *different* seeds on purpose: a document whose key order follows a set's
iteration order reproduces perfectly within one interpreter and differs between
two. Zero is never used, because it disables hash randomisation entirely and
would make the check prove nothing.

Five artifacts are excluded from the committed-bytes comparison by name, not by
guesswork - the WP-16/17/18/19 gate statuses and the WP-16 runtime verification
record. Each records the environment it was produced in and *must* differ
between machines; comparing one would report an honest document as stale.

Assessment and report determinism for a pinned input is separately covered by
`tests.unit.reporting.test_determinism` and
`tests.unit.application.test_assessment_determinism`, both in the
`reproducibility` profile.

## 8. Flakiness - STABLE

```
status       STABLE
repetitions  3
flaky tests  0
```

The `flaky` profile repeats eleven documented critical modules three times,
each in a fresh interpreter with the same recorded hash seed, comparing
`{test id: outcome}` only.

> A test that passes twice and fails once is reported as **flaky**, not as a
> majority pass.

Durations and skip reasons are excluded from the comparison: the first differ
between runs by definition and the second can name a package version.

The full 5,900-test suite is **not** repeated three times. That would cost
fifteen minutes to learn what the subset answers in seconds, and every
repetition is recorded so that "ran three times, identical" is distinguishable
from "ran once".

## 9. PostgreSQL - BLOCKED

No server was started or reached. `psycopg` is not importable in this
container.

- **77 tests** in `tests/integration/db` did not execute. Every identifier is
  recorded.
- `POSTGRESQL_INTEGRATION` reports **`BLOCKED`**, never `PASS`.
- No schema was inspected and reported as a database result.
- No SQLite database was used as evidence of PostgreSQL behaviour.
- No database was started, created or destroyed by WP-19.

`TEST_DATABASE_URL` is forwarded to the worker untouched. The refusals that
matter - the target database name must match the configured test name, SQLite
is rejected, teardown removes only what the suite created - remain in
`tests/integration/db/_support.py`.

**To unblock:**

```
docker compose --profile test up -d postgres-test
TEST_DATABASE_URL='postgresql://pgx_dev:pgx_dev_password@localhost:55432/pgx_test' \
  .venv/bin/python -m pgx.application.verification_cli run --profile database
```

## 10. ASGI runtime and browser

Both executed here and both passed: 50 ASGI tests and 13 browser end-to-end
tests. The browser was Chromium 141.x under Playwright in this container.

The developer's macOS `.venv` has Chromium 151.x - **a different binary, so
this run is not evidence about that one.** The `runtime` profile must be run
there for a macOS claim.

Neither result is inferred from an installed package. The WP-16 mechanism
records an execution and rejects it when the API source or the served OpenAPI
document changes.

## 11. Offline

Every profile installs a guard on `socket.socket.connect` and `connect_ex` that
refuses any non-loopback address for the duration of the run. Loopback stays
open because the ASGI and browser suites legitimately talk to `127.0.0.1`.

The full suite ran with the guard installed and produced **zero** network
refusals. No live source, no LLM endpoint, no package index was contacted.

## 12. Evidence hygiene

Every committed document passes through `scrub.safe_render`, which rewrites the
repository root, home directory and temporary directory as `<repo>`, `<home>`
and `<tmp>`, then **refuses** anything that still matches:

an absolute POSIX or Windows home path; a private temporary directory; a
database URL carrying a password; a credential assignment; a bearer token; a
private key block; or a clinical payload field
(`patient_name`, `patient_id`, `mrn`, `date_of_birth`, `diplotype`,
`star_allele`, `genotype`, `vcf`, `fastq`, `bam`).

Refused rather than silently edited: a document with text quietly removed from
it is no longer the evidence it claims to be. The refusal message truncates its
sample, so a credential does not reach a build log by another route.

The recorded run's host fingerprint carries the interpreter, platform,
architecture and package versions - and **no hostname, username or path**.

## 13. What this evidence does not establish

| Not established | Owner |
|---|---|
| That any pharmacogenetic rule is scientifically correct | WP-11 curators, WP-22 experts |
| That any validation case is valid | scientific curators |
| Any sensitivity, specificity, concordance or agreement figure | WP-21 |
| Any expert review or blind holdout result | WP-22 |
| That the claim boundary is approved | named human and scientific reviewers |
| That `SAFETY-INV-001..010` hold | **WP-20** |
| That the software behaves correctly against a real PostgreSQL | blocked above |
| Line or branch coverage | blocked above |
| Anything at all about macOS | the developer's run |

The gate status pins `scientific_validation_performed: false` and
`safety_invariant_map_only: true` with `const` in its published schema, so
changing either requires a schema change in the open.

## 14. Gate status summary

```
work package        WP-19
discovered tests    5964
execution status    PASS
run evidence        VERIFIED
coverage            BLOCKED
postgresql          BLOCKED
asgi runtime        PASS
browser e2e         PASS
reproducibility     REPRODUCIBLE
flaky               STABLE
claim boundary      DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW
wp20 started        False
release may proceed False
```

`release_may_proceed` is **false**, and correctly so: coverage was never
measured, PostgreSQL was never reached, the claim boundary is unapproved, and
WP-20 owns a gate that does not exist yet. Each of those is a separate field
with a named owner, because collapsing them into one boolean would be false in
one direction and misleading in the other.
