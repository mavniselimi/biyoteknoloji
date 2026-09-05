# `data/verification/` - WP-19 software verification artifacts

Everything here is **software verification**. A green result means the software
behaved as its tests describe. It is not a validated ruleset, a reviewed
validation case, an expert opinion, a clinical result, or an approval. Those
are produced by people under WP-21 and WP-22 and cannot be produced by running
tests.

## What is in here

| File | Deterministic? | What it says |
| --- | --- | --- |
| `wp19-test-inventory.json` | yes | Every discovered test suite, with its category, owning work package, requirements, runtime dependencies and skip policy. |
| `wp19-requirement-matrix.json` | yes | Which tests are claimed to verify which requirement - and everything that is not covered. |
| `wp19-verification-profiles.json` | yes | The seven execution profiles and the contract each one carries. |
| `wp19-verification-run.json` | no | A recorded run: what it found, on what code, on what kind of machine. |
| `wp19-coverage-summary.json` | no | Line and branch coverage, or an explicit statement that none was measured. |
| `wp19-reproducibility-report.json` | no | Each deterministic generator rebuilt twice under two different hash seeds. |
| `wp19-real-gate-status.json` | no | What WP-19 may say, component by component. |

"Deterministic" means a fresh build must equal the committed bytes;
`pgx-verify reproducibility` checks that on every run. The others record an
environment - which packages were importable, whether a database was reachable,
whether a browser launched - and *must* differ between machines. Comparing one
of those with its committed copy would report an honest document as stale, so
they are excluded from that comparison by name rather than by guesswork.

## Regenerating

```
pgx-verify artifacts                       # the three deterministic documents and the schemas
pgx-verify run --profile full --write      # record a run
pgx-verify coverage --write                # measure, or report BLOCKED
pgx-verify reproducibility --write         # rebuild everything twice and compare
pgx-verify gate-status --run full --reproducibility --write
```

Without an installed package, the same commands are
`python -m pgx.application.verification_cli ...`.

## Reading a result

Five outcomes, and they are not interchangeable:

- **PASS** - executed and satisfied its assertions.
- **FAIL** - executed and did not. The software is wrong, or the test is.
- **ERROR** - executed and raised before it could decide.
- **SKIP** - did not execute, and said why. Never a pass.
- **BLOCKED** - could not execute because something outside the repository is
  absent. Never a pass, and distinguished from SKIP because a skip is a
  decision the test made and a block is a decision the world made.
- **MISSING** - no test exists for this at all.

A count that is `null` means nobody measured it. A count that is `0` means
somebody measured it and found none. The two are different answers and the
schemas keep them apart.

## One thing a CI job must not do

Several negative tests print `CONFIGURATION_FAILURE` on standard output **while
passing**. That is what those tests are for. A job that searched output for
words like that would fail a green suite. Outcomes come from the test runner's
recorded result, which is what `pgx-verify --format json` returns and what the
exit code reflects.
