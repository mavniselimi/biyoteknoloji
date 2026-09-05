# Verification profiles - what each run is allowed to conclude

| Field | Value |
|---|---|
| Document ID | `DOC-WP19-003` |
| Work package | WP-19 |
| Command | `pgx-verify run --profile <name>` |
| Machine-readable | `data/verification/wp19-verification-profiles.json` |

---

## 1. A profile is a selection plus a contract

The selection says which tests run. The contract says how many must run, how
often, whether the network is reachable, and whether a failure blocks a
release. The contract is the half that matters, because a selection on its own
can be satisfied by running nothing.

```
pgx-verify profiles                        # the registry
pgx-verify run --profile fast              # a developer's pre-push check
pgx-verify run --profile full --write      # the release run, recorded
pgx-verify run --profile p0 --format json  # for a machine
```

## 2. The seven

| Profile | Selects | Floor | Repeats | Required | Typical wall clock |
|---|---|---:|---:|---|---|
| `fast` | everything except database, migration, ASGI, browser and legacy regression | 3000 | 1 | yes | ~2 min |
| `p0` | every test the inventory marks `P0_CRITICAL` | 3000 | 1 | yes | ~3 min |
| `runtime` | `ASGI_RUNTIME` + `BROWSER_E2E` | 40 | 1 | yes | ~20 s |
| `database` | `POSTGRESQL_INTEGRATION` + `MIGRATION` | 60 | 1 | **no** | ~5 s blocked, longer with a server |
| `full` | `unittest discover -s tests -p 'test_*.py' -t .` | 5000 | 1 | yes | ~5 min |
| `reproducibility` | the deterministic critical subset | 200 | 2 | yes | ~10 s |
| `flaky` | the same subset | 200 | 3 | yes | ~15 s |

### `fast`

For the loop a developer is actually in. It removes the five categories that
need a database, a browser, an ASGI server, or several minutes.

Excluding a category here **does not mark it verified**. Its real state -
executed or `BLOCKED` - is reported by `full` and by the gate status.

### `p0`

Every test on the P0 critical path, whatever category it is in - which means it
*includes* the PostgreSQL tests and will report them `BLOCKED` where no server
is reachable. That is the point. A critical profile that quietly dropped the
tests it could not run would look healthier than it is.

### `runtime`

The ASGI application and the browser end-to-end suite: the parts that need a
real server or a real browser rather than a description of one. Skips here are
permitted and classified - the ASGI suite carries an *inverted* skip that
stands down when the framework is present, because it exists to check that the
other suite's missing-dependency message is honest.

### `database`

The only profile that is not required. No PostgreSQL exists in every
environment, and a required profile that cannot run would make every release
blocked for a reason unrelated to the software.

Its real state is still reported. When no server is reachable,
`POSTGRESQL_INTEGRATION` is `BLOCKED`, the exact skipped identifiers are
recorded, and `release_may_proceed` is false.

To run it for real:

```
docker compose --profile test up -d postgres-test
TEST_DATABASE_URL='postgresql://pgx_dev:pgx_dev_password@localhost:55432/pgx_test' \
  pgx-verify run --profile database
```

WP-19 forwards `TEST_DATABASE_URL` untouched and decides nothing about it. The
suite's own refusals - the database name must match the configured test name,
SQLite is rejected, teardown removes only what the suite created - are where
they always were, in `tests/integration/db/_support.py`.

### `full`

The whole suite, discovered exactly as the documented command discovers it.
This is deliberate: the profile a release is judged on and the command in the
documentation must be the same enumeration. If they ever disagree, the
inventory is describing a different suite than the one that runs, and every
other number is suspect.

`--write` records the run as evidence the gate status can read - and later
reject as stale when the code changes or the machine differs.

### `reproducibility` and `flaky`

The same eleven-module subset, run twice and three times respectively. The
subset is named in `pgx/verification/profiles.py` where it can be reviewed,
rather than inferred from a run.

Two runs answer "is this deterministic". Three answer "is this flaky".

> A test that passes twice and fails once is reported as **flaky**, not as a
> majority pass.

The comparison is over `{test id: outcome}` and nothing else. Durations differ
between runs by definition; a skip reason can name a package version. What must
not change is which test did what.

Running the full 5,600-test suite three times to produce a flakiness claim would
cost twelve minutes to learn what this subset answers in seconds.

## 3. The floor

Every profile declares `minimum_tests`, below which a run is an `ERROR` rather
than a pass. It is the cheapest defence against the commonest false green: a
selector stops matching - a package is renamed, a category rule changes - and
the profile goes green in two seconds having verified an empty set.

Zero executed tests is never a pass, in any profile, for any reason.

## 4. Exit codes

| Code | Meaning | A CI job should |
|---|---|---|
| `0` | the thing asked for succeeded | continue |
| `1` | a required profile failed or errored | stop; something is wrong |
| `2` | a required component is blocked | stop; nothing is *known* about it |
| `3` | the command itself was wrong | fix the invocation |

`1` and `2` are different on purpose. A job that treated them alike would either
ignore real failures or block on every machine without PostgreSQL.

An optional profile - `database` - returns `0` even when blocked, so it does not
stop a pipeline. Its state still reaches the gate status.

## 5. What a CI job must not parse

Several negative tests print `CONFIGURATION_FAILURE` on standard output **while
passing**. That is what those tests are for: they demonstrate that a
misconfiguration is reported rather than silently accepted.

A job that searched output for words like that would fail a green suite.
Outcomes come from the test runner's recorded result. Use the exit code, or
`--format json` and read `result.outcome` and `result.summary`.

## 6. The environment a worker gets

Every profile runs in a fresh interpreter started with `sys.executable`, with:

| Variable | Value | Why |
|---|---|---|
| `PYTHONHASHSEED` | `20260904` | fixed and recorded, so a difference between runs is meaningful. Not `0`, which disables randomisation entirely and would hide a genuine ordering dependency |
| `PYTHONDONTWRITEBYTECODE` | `1` | so a repeat cannot be faster - or different - because the first run left a cache |
| `PYTHONWARNINGS` | `error::ResourceWarning` | matching the documented command; a leaked file handle is a defect the suite already catches |
| `TEST_DATABASE_URL` | forwarded untouched | WP-19 never invents one |

Non-loopback network connections are refused for the duration by a guard on
`socket.socket.connect`. Loopback stays open because the ASGI and browser
suites legitimately talk to `127.0.0.1`, and refusing that would replace a real
check with a broken one.
