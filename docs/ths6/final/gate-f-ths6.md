# Gate F — THS 6

**Result: BLOCKED.** 0 of 5 mandatory conditions met. 5 blockers.

`architecture.md` §20: *representative demo, traceability/evidence pack, all
DoD items pass.*

| # | Condition | Read from | Required | Observed |
|---|---|---|---|---|
| F1 | the release validation permits a release | `data/deployment/wp24-release-validation.json` → `release_may_proceed` | true | false |
| F2 | every required release gate is satisfied | same → `satisfied_required_count` | ≥ 19 | 2 |
| F3 | the safety gate permits a release | `data/safety/wp20-real-gate-status.json` → `release_may_proceed` | true | false |
| F4 | the validation dashboard is populated | `data/web/wp17-real-gate-status.json` → `validation_dashboard_status` | `POPULATED` | `EMPTY_STATE_ONLY` |
| F5 | the verification run evidence is fresh | `data/verification/wp19-real-gate-status.json` → `run_evidence_status` | `FRESH` | `STALE_EVIDENCE_REJECTED` |

## F cannot pass while A to E do not — checked twice

Gate F declares `depends_on = (GATE-A, GATE-B, GATE-C, GATE-D, GATE-E)`. That
dependency is enforced in two independent places:

1. **F's own conditions** read artifacts that cannot be satisfied while A–E
   are blocked.
2. **The aggregate builder** re-checks after evaluating F: if any of A–E is
   not `PASS` and F somehow came out `PASS`, the result is replaced with
   `BLOCKED` carrying `THS6_UPSTREAM_GATE_NOT_PASS`, owned by the programme
   owner.

Two checks rather than one because the single most valuable thing an
adversarial edit to this pack could do is make F pass alone. A unit test
constructs a passing record and asserts the guard rewrites it.

## There is no override

No `--force`, no `--assume`, no `--fixture`, no `--ignore-blocker`. `argparse`
would reject those as unknown arguments, and no code path accepts an override
under any other spelling — a test greps every module in the package for each
spelling. More fundamentally, `GateRecord` refuses at construction to hold
`PASS` beside an unmet condition, so the absence of an override is a property
of the type rather than a promise about the command line.

## F5 and the stale verification evidence

WP-19 rejects its own recorded run as stale: the source or test tree changed
after the run was recorded, so *"the recorded result is about different
code."* That is WP-19 behaving correctly, and it also means Gate F has no
fresh verification evidence to read.

The same artifact records `discovered_test_count: 6374`. This pack
independently counts 6,996 test functions defined under `tests/` by parsing
them, and reports the difference as a source-artifact disagreement rather than
regenerating another work package's artifact.

## Evidence pack integrity is not Gate F

`pgx-ths6 verify-pack` exits `0` today. That is a statement about this pack's
bytes: every member present, every digest agreeing, the manifest covering
everything but itself.

Gate F is `BLOCKED`. `pgx-ths6 status` exits `2`.

Those two results are separate fields in
`data/ths6/wp25-ths6-status.json`, they have separate exit codes, and the
schema refuses a document that derives either from the other.
