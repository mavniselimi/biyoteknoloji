# WP-19 handoff

## State

The software verification system is implemented.

`pgx/verification/` (18 modules, framework-free), `pgx-verify`, 7 published
schemas, 6 data artifacts, 4 documents, 267 new tests. The suite is **5,963
tests, zero failures, zero errors, zero unexplained skips**, and for the first
time the repository can say what those tests verify and what they do not.

```
pgx-verify inventory        # every suite, described
pgx-verify matrix           # what verifies what, and what verifies nothing
pgx-verify run --profile p0 # a named subset, with a contract
pgx-verify gate-status      # component by component
```

## What the next work package inherits

### The inventory is refused, not defaulted

A test module matching no category rule fails the build with the module name in
it. It does **not** quietly become `UNIT`.

That matters more than it sounds. `UNIT` is the friendliest possible wrong
answer: a whole new package silently reclassified, looking fine in every report.
If you add `tests/unit/safety/` for WP-20 and see `InventoryError`, that is the
system working. Add a rule in `pgx/verification/inventory.py` and the entry
records which rule fired, so "why is this a `SECURITY_BOUNDARY` test" has an
answer.

### A skip is never a pass, and the policy is per-suite

Over 90% of the suite is `SkipPolicy.NEVER`. The exceptions each declare the
*substrings* their skip reason must contain. "PostgreSQL is missing" does not
excuse a browser test.

**If you add a test that can skip, declare why in the rule table.** An
undeclared skip is `UNEXPLAINED` and fails its profile - and that is not a
formality: it is what stopped the coverage and filesystem-capability skips in
this very package from being waved through.

### `discovered` is not `executed`

`unittest` reports a failing `setUpClass` as one skip and never mentions the
tests inside. Sixteen such skips hide seventy-seven PostgreSQL tests, and
`Ran 5886 tests` is 77 short of the 5,963 that exist.

The worker attributes a class-level skip to every test it suppressed. **Do not
collapse those two counts.** Every artifact keeps them apart, and a future
reporting layer that averaged them would recreate exactly the blind spot this
package was built to remove.

### `null` is not zero, still

WP-18's rule, kept. `line_percent`, `branch_percent`, `flaky_repeat_status` and
`reproducibility_status` are `null` when nobody measured them. Rendering one as
`0` or `"STABLE"` would turn "we did not look" into "we looked and found none".

## What WP-20 must not inherit from here

**WP-19 maps tests to `SAFETY-INV-001..010`. It does not enforce them.**

`requirements.SAFETY_INVARIANT_MAP` says which existing tests *relate to* each
invariant, so thin coverage is visible before WP-20 exists. It is not a claim
that any invariant holds, and `matrix.is_complete` deliberately ignores it - an
unmapped invariant is a WP-20 gap, and letting it fail WP-19's completeness
check would push this package into claiming a gate it does not own.

The gate status pins `safety_invariant_map_only: true` with `const` in its
published schema. **When WP-20 builds the real registry, that field and that
schema change together, in the open.** Do not flip it from the WP-19 side.

`data/verification/wp19-real-gate-status.json` carries
`VERIFICATION_SAFETY_GATE_OWNED_BY_WP20` as a standing blocker owned by WP-20.
Removing it is WP-20's first honest act, not WP-19's.

## What WP-24 will need, and what it must not do

Everything is already machine-readable. `--format json` on every subcommand
returns the same document the artifacts hold, so a job and a person cannot read
different numbers.

| Exit code | Meaning |
|---|---|
| `0` | succeeded |
| `1` | a required profile failed or errored |
| `2` | a required component is blocked - nothing is *known* about it |
| `3` | the command was wrong |

`1` and `2` are different on purpose. A job that treated them alike would either
ignore real failures or block on every machine without PostgreSQL.

> **Do not grep stdout.** Two negative tests print `CONFIGURATION_FAILURE`
> while passing; that is what they are for. A job searching output for words
> like that would fail a green suite. This warning is repeated in the inventory
> artifact, in `data/verification/README.md`, and in every result document,
> because it is the single easiest way to build a CI job that is wrong.

A sensible pipeline is `fast` on every push, `full` plus `reproducibility` on a
merge, `database` where a server exists, and the gate status as the artifact.
`database` returns `0` even when blocked, so it does not stop a pipeline; its
real state still reaches the gate status.

## Things to be careful with

**The `full` profile must stay a discovery.** It runs
`unittest discover -s tests -p 'test_*.py' -t .`, not a list of identifiers, so
the profile a release is judged on and the documented command are the same
enumeration. If they ever disagree, the inventory is describing a different
suite than the one that runs and every other number is suspect.

**`minimum_tests` is not decoration.** Every profile declares a floor below
which a run is an `ERROR`. It is the cheapest defence against a selector that
stops matching and takes the profile green in two seconds. Lowering one to make
a run pass would remove the only thing standing between you and a verified
empty set.

**Two hash seeds, neither of them zero.** The reproducibility check rebuilds
each generator under `1` and `524287`. A document whose key order follows a
set's iteration order reproduces perfectly within one interpreter and differs
between two - which is the bug being looked for. `PYTHONHASHSEED=0` disables
randomisation and would make the check prove nothing.

**The environment-dependent artifact list is explicit.**
`reproducibility.ENVIRONMENT_DEPENDENT` names five paths excluded from the
committed-bytes comparison because they record the machine they were built on.
It is a list, not a filename heuristic. Adding a sixth is a decision.

**The sealed-tree probe needs ownership, and only of scratch.**
`may_take_ownership` is passed by exactly one caller,
`tests/unit/snapshots/_support.py`, for a tree that test case created in
`setUp`. Passing it for a committed artifact would be chowning production data
to make a test pass. Without it, the probe reports `NOT_ATTEMPTABLE` rather than
an answer it cannot stand behind.

**`discriminating` is the field that matters.** An attempt by a non-owner is
refused by a writable file too. A caller that read `outcome` without checking
`discriminating` would call a mutable tree sealed.

## Blocked, and none of it by code

| Blocker | Owner |
| --- | --- |
| Coverage never measured; `coverage.py` absent from both environments and no index reachable | deployment: `.venv/bin/python -m pip install 'coverage[toml]'` |
| PostgreSQL never reached; 77 tests did not execute | deployment: `docker compose --profile test up -d postgres-test` |
| Browser evidence is from Chromium 141 on Linux, not 151 on macOS | the developer, on macOS |
| Claim boundary `DRAFT` | named human and scientific reviewers |
| `SAFETY-INV-001..010` unenforced | WP-20 |
| Zero holdout cases (unchanged by WP-19) | scientific curators |
| No metric, no expert review | WP-21, WP-22 |
| No CI | WP-24 |
| **`release_may_proceed`** | all of the above |

## What changed outside `pgx/verification/`

Deliberately little. Six files, each for a reason that survives review.

| File | Change | Why |
|---|---|---|
| `pyproject.toml` | `coverage[toml]` in the dev group; `[tool.coverage.*]`; `pgx-verify` script | the tool must be declared even where it cannot be installed |
| `tests/unit/snapshots/_support.py` | `supports_permissions` delegates to WP-19; new `mutation_attempt` | the probe now has tests; it used to be written where nothing could check it |
| `tests/unit/snapshots/test_snapshot_build.py` | mode-bit half separated from mutation half; 6 tests added | the uid-0 repair, and the proof it cannot hide a writable tree |
| `tests/unit/application/test_release_boundaries.py`, `tests/unit/snapshots/test_snapshot_boundaries.py` | the two new `pgx/application` modules registered | the inventories are exhaustive by design |
| `tests/unit/infrastructure/test_packaging_and_environment.py` | `pgx-verify` added to the console-script list | same |
| `tests/unit/validation/test_artifacts.py` | `wp19_started` assertions moved from a pinned `false` to filesystem agreement | WP-19 started; see below |

**No `apps/`, `pgx/engine`, `pgx/rules`, `pgx/reporting`, `pgx/validation` or
assessment logic was touched.** The WP-16 runtime-verification evidence is
unaffected, which
`test_wp19_boundaries.py::test_no_application_or_scientific_module_was_touched`
asserts by checking that the committed OpenAPI still matches the generator.

### The `wp19_started` correction

WP-18's gate status measures `wp19_started` from the filesystem, and three
tests asserted it was `false`. WP-19 starting made those assertions false for
the best possible reason.

What they were protecting was never "WP-19 has not begun" - a fact with a shelf
life - but "this document reports the truth about what has begun", which does
not. So the assertion moved to *agreement with the filesystem*, exactly the
correction WP-17 made to `wp17_started`. WP-21 and WP-22 remain pinned
unstarted, because they still are, and a fourth test now asserts that WP-19
starting changed nothing about the validation partition: still seven
development cases, still zero holdout, still `null` metrics.

## Not started

WP-20, WP-21, WP-22, WP-23, WP-24, WP-25.

Measured from the filesystem in the WP-19 gate status (`wp20_started`,
`wp21_started`, `wp24_started`), not asserted - and
`tests/unit/verification/test_wp19_boundaries.py` reads syntax trees to check
that no module here defines a safety-invariant registry, computes a validation
metric, imports `pgx.validation`, or defines a function whose name approves,
certifies or attests to anything.
