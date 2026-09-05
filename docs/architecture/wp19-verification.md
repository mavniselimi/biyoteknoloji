# WP-19 - Software Verification Suite

| Field | Value |
|---|---|
| Document ID | `DOC-WP19-001` |
| Work package | WP-19 - Software Verification Suite |
| Owns | `pgx/verification/`, `pgx/application/verification_{cli,schema}.py`, `tests/unit/verification/`, `schemas/wp19/`, `data/verification/` |
| Command | `pgx-verify` (`python -m pgx.application.verification_cli`) |
| Depends on | WP-00 through WP-18 |
| Does **not** own | the SAFETY-INV registry and blocking job (WP-20), validation metrics (WP-21), expert review (WP-22), CI (WP-24) |

> **This is software verification.** A green result means the software behaved
> as its tests describe. It is not a validated ruleset, a reviewed validation
> case, an expert opinion, a clinical result, or an approval.

---

## 1. What problem this solves

Before WP-19 the repository had 5,688 tests and no way to say what they
verified. `unittest discover` printed a number and a dot per test. That answers
"did anything break". It does not answer:

- Which of the sixteen kinds of verification are represented, and which are
  not running here?
- Which critical requirement has tests behind it, and which has none?
- Is a skip legitimate, or did something quietly stop running?
- Did the suite execute every test it discovered?
- Is the coverage number real, or is there no coverage number?
- Does anything in here reach the network?

WP-19 is the instrument that answers those. It does not replace the suite; it
describes and drives it.

### 1.1 The number that started this

`unittest` reports a failing `setUpClass` as **one** skip, and never mentions
the tests inside that class. This repository has sixteen such skips, and behind
them sit **seventy-seven** PostgreSQL tests that never ran. The runner's
`testsRun` is therefore not the number of tests that exist, and the difference
is not visible anywhere in its output.

Everything in this package follows from taking that seriously.
`discovered_test_count` and `executed_test_count` are separate fields, the
worker attributes a class-level skip to every test it suppressed, and
`POSTGRESQL_INTEGRATION` reports `BLOCKED` rather than being absent from the
report.

## 2. Architecture

```
pgx/verification/
  model.py             Outcome, Category, Criticality, SkipPolicy, TestEntry,
                       SuiteSummary, ProfileResult - the vocabulary
  errors.py            faults in the instrument, distinct from test failures
  discovery.py         unittest's own loader, sorted, total, deterministic
  inventory.py         ordered category rules; every test described or refused
  requirements.py      the P0 requirement registry and the safety-invariant map
  matrix.py            requirement x test, and everything not covered
  profiles.py          seven named selections, each with a contract
  runner.py            subprocess isolation, fixed hash seed, exact counts
  _worker.py           the process that runs tests and writes a report file
  results.py           the five outcomes, kept apart
  offline.py           refuses non-loopback connections for the duration
  coverage_report.py   measure, or report BLOCKED with an install command
  flaky.py             repeated runs compared; no majority vote
  reproducibility.py   generators rebuilt twice under two hash seeds
  filesystem.py        the portable sealed-tree immutability probe
  run_evidence.py      a recorded run that can be disqualified
  gate_status.py       every component separately
  artifacts.py         the committed documents
  scrub.py             no host paths, credentials or clinical payloads
```

The package imports **no third-party module at import time**. That is asserted
by `tests/unit/verification/test_wp19_boundaries.py` reading syntax trees. The
reason is not purity: a verifier that needed something installed could only
verify the environments that happened to be complete, and the environment where
a release is built is the one most likely to be bare.

### 2.1 Why a rule table rather than a list of tests

Categories are assigned by an ordered table of rules in `inventory.py`, matched
against the module's dotted name, first match wins. A per-test list would be
more precise on the day it was written and wrong by the end of the week.

Two properties make the table safe to rely on:

- **Totality is checked.** A test matching no rule is *refused*, not defaulted.
  Adding a package without a rule fails the build with the package name in it,
  rather than silently making it `UNIT` - the friendliest possible wrong answer,
  because it looks fine in every report.
- **The rule is recorded.** Every inventory row carries `assigned_by`, so "why
  is this a `SECURITY_BOUNDARY` test" has an answer.

### 2.2 Why the runner never runs a test in-process

`runner.py` writes a plan, starts `pgx.verification._worker` with
`sys.executable`, and reads a report **file**. Three reasons, in order of how
much trouble they save:

1. **State.** The suite imports two hundred modules, several with module-level
   state. A profile run after another profile in the same process would be
   measuring the first one's leftovers.
2. **Survival.** A test that segfaults or calls `sys.exit` takes the worker
   down, not the verifier - and a worker that dies without a report is a
   `RunnerError`, never a failing result. Nothing is known about those tests,
   which is different from knowing they failed and *very* different from
   knowing they passed.
3. **stdout.** Several negative tests print `CONFIGURATION_FAILURE` while
   passing. The report is a file precisely so that nothing has to read stdout
   to learn an outcome.

`sys.executable` rather than `python`: a verifier that ran whatever `python`
meant on `PATH` would be measuring a different installation than the one being
released.

## 3. The five outcomes

| Outcome | Means | Never means |
|---|---|---|
| `PASS` | executed, assertions satisfied | - |
| `FAIL` | executed, assertions not satisfied | that the test is broken |
| `ERROR` | executed, raised before deciding | that the code is wrong |
| `SKIP` | did not execute, and said why | a pass |
| `BLOCKED` | could not execute; something outside the repository is absent | a pass, or a failure |
| `MISSING` | no test exists | that it was blocked |

They are `str` enums with ordering **explicitly disabled**. The moment
`SKIP < PASS` type-checks, somebody writes `max(outcomes)` and a blocked
category becomes a passing one. Combining is done by `worst_outcome`, whose
precedence is written out, and whose answer for an empty sequence is `MISSING` -
nothing observed is not the same as nothing wrong.

## 4. Skips

Every test's inventory entry declares a `SkipPolicy` and the reasons it may
skip for:

| Policy | Meaning |
|---|---|
| `NEVER` | a skip here is unexplained by definition (over 90% of the suite) |
| `ENVIRONMENT_DEPENDENCY` | may skip when a declared external dependency is absent |
| `CAPABILITY` | may skip when the host cannot perform the operation under test |
| `INVERTED` | exists to check another test's skip message, and stands down when that dependency is present |

An observed skip is `ALLOWED` only when its reason contains one of the declared
substrings. "PostgreSQL is missing" does not excuse a browser test. A test with
no inventory entry gets no benefit of the doubt. **Any unexplained skip fails
its profile.**

## 5. Profiles

Seven, each a selection *plus a contract*. The contract is the half that
matters: a selection alone can be satisfied by running nothing.

| Profile | Selects | Floor | Repeats | Required |
|---|---|---|---|---|
| `fast` | everything except database, migration, ASGI, browser, legacy | 3000 | 1 | yes |
| `p0` | every `P0_CRITICAL` test, whatever category | 3000 | 1 | yes |
| `runtime` | `ASGI_RUNTIME` + `BROWSER_E2E` | 40 | 1 | yes |
| `database` | `POSTGRESQL_INTEGRATION` + `MIGRATION` | 60 | 1 | **no** |
| `full` | `unittest discover`, exactly as documented | 5000 | 1 | yes |
| `reproducibility` | the deterministic critical subset | 200 | 2 | yes |
| `flaky` | the same subset | 200 | 3 | yes |

`minimum_tests` is the floor below which a run is an `ERROR` rather than a
pass. It is the cheapest defence against the commonest false green: a selector
stops matching, and the profile goes green in two seconds.

`database` is the one profile that is not required. No PostgreSQL exists in
every environment, and a required profile that cannot run would block every
release for a reason unrelated to the software. Its real state is still
reported by the gate status as `BLOCKED`, which is not a pass.

The `full` profile uses discovery rather than a list of identifiers, so the
profile a release is judged on and the command in the documentation are the
same enumeration. If they ever disagree, the inventory is describing a
different suite than the one that runs and every other number is suspect.

## 6. Coverage

`coverage.py` is declared in the dev dependency group and configured in
`[tool.coverage.run]` / `[tool.coverage.report]`, with `branch = true` because a
line-only number over-reports: a line with an untaken `else` counts as covered.

When the tool is absent, `pgx-verify coverage` reports `BLOCKED`, names the
package, gives the exact install command, and returns `None` for every
percentage. There is no third path. A number is never estimated, never carried
over from an earlier run, and never derived from how many test files import a
module. `null` is the honest value for a measurement nobody took; `0.0` is not,
because zero means the tool ran and found nothing executed.

`DECLARED_LINE_THRESHOLD` lives in `coverage_report.py` and was written before
any measurement was taken, so it cannot be the number that happened to come
out. It lists critical modules *for attention*. There is deliberately no
`fail_under` in `pyproject.toml`: a passing bar for a measurement nobody has
taken would be the same error in the other direction.

The `omit` list is read from `pyproject.toml` at runtime rather than restated
in Python, so the artifact cannot describe exclusions the tool is not applying.

## 7. Flakiness and reproducibility

**Flakiness** repeats a documented critical subset - eleven modules, named in
`profiles.FLAKY_SUBSET_MODULES` - three times, each in a fresh interpreter with
the same recorded hash seed. The comparison is over `{test id: outcome}` and
nothing else: durations differ between runs by definition, and a skip reason can
name a package version.

> A test that passes twice and fails once is reported as **flaky**, not as a
> majority pass. Majority voting on test results is how an intermittent failure
> becomes invisible.

Running the full 5,600-test suite three times to produce that claim would cost
twelve minutes to learn what the subset answers in seconds, so the subset is
bounded and written down where it can be reviewed.

**Reproducibility** rebuilds every deterministic artifact generator twice, in
two fresh interpreters, under two *different* non-zero hash seeds, and compares
digests. Two different seeds on purpose: a document whose key order follows a
set's iteration order reproduces perfectly within one interpreter and differs
between two, and that is the bug this check exists to find. Zero is not used,
because it disables hash randomisation entirely.

Generators whose output records the environment - gate statuses, runtime
verification - are compared with **each other** and not with the committed copy.
A gate status is supposed to differ between machines; comparing one would report
an honest document as stale. Those paths are named in
`reproducibility.ENVIRONMENT_DEPENDENT` rather than guessed from a filename.

## 8. Database tests

`TEST_DATABASE_URL` is forwarded to the worker untouched and nothing else is
done. WP-19 never invents a URL, never points a suite at a database of its own
choosing, and never starts or stops a server. The refusals that matter - the
database name must contain the configured test name, SQLite is rejected,
teardown removes only what the suite created - live in
`tests/integration/db/_support.py` where they always did.

Three things this package will not do:

- report a `PASS` from schema inspection;
- treat an installed `psycopg` as a reachable database;
- use SQLite as evidence of PostgreSQL behaviour.

When no server is reachable, `POSTGRESQL_INTEGRATION` is `BLOCKED`, the exact
skipped test identifiers are recorded, and `release_may_proceed` is false.

## 9. The portable sealed-tree check

WP-06 seals a raw snapshot to `0o444`. The test that proved it asserted the
mode bits *and* that appending raised `PermissionError`. As `uid 0` the second
fails - the superuser is exempt from mode-bit checks - on a tree that is
perfectly well sealed.

`pgx/verification/filesystem.py` separates the two questions the old test
conflated, and is careful about a third that is easy to get wrong:

1. **Are the mode bits right?** `denies_all_writers` reads them: no write bit
   for owner, group or other. Answerable wherever `chmod` sticks, never skipped
   there, and stricter than comparing with `0o444` - that is how it is spelled;
   this is what is meant.
2. **Is a writer subject to those bits refused?** By a direct attempt when the
   current user is subject to them, and otherwise by forking and dropping to a
   genuinely unprivileged account.
3. **Could the attempt have told the difference?** This is the subtle one. A
   child running as `nobody` is refused by a `0o644` file too, because it is not
   the owner - so that attempt would report a tree its owner could rewrite at
   will as sealed. An attempt is `discriminating` only when the writer is the
   file's **owner**, and `may_take_ownership` (passed only for a tree the test
   created itself) is what arranges that.

The probe opens for append and closes, writing nothing, so content, mode,
ownership and modification time are unchanged. It never chmods a production
artifact to make an assertion pass; the only permissions it changes belong to
scratch files it created.

`TestThePortabilityHandlingCannotHideAWritableTree` builds a genuinely writable
sealed tree at four different modes and requires the same helper to report it
`PERMITTED`. Without it, making the check portable would have introduced a way
for it to say nothing.

## 10. Evidence and staleness

A run writes `data/verification/wp19-verification-run.json` carrying enough to
be **disqualified**:

- a digest over every `.py` file in `pgx`, `apps` and `tests`, path included -
  change a line and the recorded result is about different code;
- the interpreter, platform, architecture and the versions of the packages the
  run depended on - a run on Linux says nothing about macOS, and a run without
  `psycopg` says nothing about a machine that has it.

Never recorded: hostname, username, or any absolute path. The question is "is
this the same kind of machine running the same stack", not "whose machine is
this". `scrub.py` refuses any document that still contains one.

This mirrors `apps/api/runtime_verification.py` on purpose. Two mechanisms with
different staleness rules would eventually disagree, and a reader would have to
learn both.

## 11. The gate status

Every component is its own field. The temptation is one boolean and it is
always wrong here: the suite can be entirely green while PostgreSQL was never
reached, coverage was never measured and the claim boundary is unapproved.
`verified: true` would be false; `verified: false` would suggest the software is
broken.

`release_may_proceed` exists, but it is the *conjunction* of the fields above
it, computed rather than asserted, and false whenever anything is blocked.

Three claims the document explicitly does not make, each pinned by a `const` in
the published schema so that changing one needs a schema change in the open:

- `scientific_validation_performed` is `false`;
- `safety_invariant_map_only` is `true` - WP-19 maps tests to
  `SAFETY-INV-001..010` so thin coverage is visible; **WP-20 owns the registry
  and the blocking job**;
- `claim_boundary_approved` is read from `docs/architecture/intended-purpose.md`,
  not asserted, and is `false` while that document is `DRAFT`.

## 12. What a CI job must not do

Several negative tests print `CONFIGURATION_FAILURE` on standard output **while
passing**. That is what those tests are for.

A job that searched output for words like that would fail a green suite.
Outcomes come from the test runner's recorded result. `pgx-verify --format
json` returns it, and the exit code reflects it:

| Code | Meaning |
|---|---|
| `0` | the thing asked for succeeded |
| `1` | a required profile failed or errored |
| `2` | a required component is blocked - nothing is known about it |
| `3` | the command itself was wrong |

`1` and `2` are different on purpose. A job that treated them alike would either
ignore real failures or block on every machine without PostgreSQL.

## 13. What WP-19 did not do

- No application, engine, rules, reporting, API or web logic was changed.
- No assertion was weakened, no blanket skip added, no exception swallowed.
- No test was deleted.
- No scientific validation, expert review, human approval or clinical result
  was produced or implied.
- WP-20 and later were not started.

The one behavioural change outside `pgx/verification` is the sealed-tree test,
which now makes its mutation attempt from a process the mode bits actually
govern. That is a repair to a test that was failing for a reason unrelated to
the software, and it made the assertion *stronger*: what used to be an
unexecutable claim on a root host is now an executed one, with a companion test
proving it cannot hide a writable tree.
