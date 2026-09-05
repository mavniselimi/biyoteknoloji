# `data/safety/` — WP-20 safety invariant artifacts

Everything here describes **software detectors and software behaviour**. It is
not clinical validation, scientific validation, expert review, or evidence that
the system is safe for any patient. No holdout result, metric, expert opinion
or human approval is asserted or implied.

## What is in here

| File | Deterministic? | What it says |
| --- | --- | --- |
| `wp20-invariant-registry.json` | yes | The twelve invariants: enforcement surfaces, owning WPs, test selectors, negative controls, legacy defects, refusal codes, blockers. |
| `wp20-negative-controls.json` | yes | Every deliberately unsafe fixture and the code its evaluator must return. |
| `wp20-safety-report.json` | no | One run: controls, tests, the false-reassurance corpus, the claim-surface count. |
| `wp20-safety-execution.json` | no | The record freshness is checked against. Written **only on PASS**. |
| `wp20-real-gate-status.json` | no | Every component reported separately, plus `release_may_proceed`. |

"Deterministic" means a fresh build must equal the committed bytes. The other
three record a run and an environment, and must differ between machines.

## The two-halves rule

Every invariant carries two executions, and both must happen:

- a **safe control** — the conforming case, through the real evaluator;
- a **negative control** — a deliberately unsafe case that the *same* evaluator
  must reject with a named code.

The second half is why this exists. A check that has never rejected anything is
indistinguishable from a check that does nothing, and a suite where every test
passes while a mutant slips through has demonstrated that the tests agree with
the code — not that the invariant holds.

**Asserting that a fixture contains unsafe text is not sufficient.** The mutant
goes through the same gate whose success is being claimed.

## Reading a result

Six execution states, none of them interchangeable:

| State | Means |
| --- | --- |
| `PASS` | ran, held, every control satisfied |
| `FAIL` | ran and did not hold — or a detector accepted its mutant |
| `ERROR` | raised before deciding |
| `BLOCKED` | a later WP or an absent dependency owns part of the enforcement |
| `NOT_EXECUTED` | nothing ran. Never folded into `PASS` |
| `STALE` | ran and passed, about code that has since changed |

`null` means nobody measured it. `0` means somebody measured it and found none.

## Regenerating

```
pgx-safety registry             # the twelve, validated
pgx-safety negative-controls    # every mutant, through its evaluator
pgx-safety check --write        # the gate. Non-zero on anything but PASS
pgx-safety report
pgx-safety gate-status --write
pgx-safety artifacts            # the deterministic documents and schemas
```

Without an installed package: `python -m pgx.application.safety_cli ...`.

## Exit codes — what CI branches on

| Code | Meaning |
| --- | --- |
| `0` | PASS |
| `1` | FAIL — an invariant failed, or a mutant was not detected |
| `2` | BLOCKED, NOT_EXECUTED or STALE — nothing is *known* |
| `3` | usage error, or the registry refused to load |

`1` and `2` are different on purpose. **Never parse stdout**: several tests in
this repository print `CONFIGURATION_FAILURE` while passing, and a job grepping
for it would fail a green suite.

## Why `release_may_proceed` is false

It is the conjunction of every field above it, and it is false whenever
anything is failed, blocked, stale or unexecuted — even when nothing is wrong.
Today five invariants are `BLOCKED` by declared later-WP or P1 dependencies, the
claim boundary is `DRAFT`, no PostgreSQL was reached, and no CI provider has run
the job. Each is its own field with a named owner.
