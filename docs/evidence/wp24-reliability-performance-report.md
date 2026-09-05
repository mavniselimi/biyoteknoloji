# WP-24 reliability and performance report

| Field | Value |
|---|---|
| Document ID | `DOC-EVID-024-B` |
| Artifacts | `data/deployment/wp24-reliability-drills.json`, `wp24-performance-targets.json`, `wp24-real-gate-status.json` |
| Status | **Targets and drills declared. Nothing executed.** |

---

## 1. What this report is

A declaration and a null result, kept apart.

The **declarations** — thirteen reliability drills and five performance
targets — are real, complete, and were written before anything could be
measured. They are committed artifacts and they are what a later run will be
judged against.

The **results** are empty, and every number in them is `null`. That is the
finding, not an omission.

## 2. Performance

### Declared, before measurement

| Target | Metric | Bound | Unit |
|---|---|---|---|
| PERF-001 | `latency_p50_ms` | ≤ 250 | ms |
| PERF-002 | `latency_p95_ms` | ≤ 1000 | ms |
| PERF-003 | `throughput_rps` | ≥ 20 | req/s |
| PERF-004 | `error_rate` | ≤ 0.001 | fraction |
| PERF-005 | `output_determinism` | == 1.0 | fraction |

Every target carries a rationale of at least forty characters, enforced by the
schema. A number with no reason behind it cannot be argued with, and a target
nobody can argue with is one nobody will revise when it turns out to be wrong.

**These are engineering and prototype targets for a demonstration
deployment.** Not clinical performance claims, not a service level, and not
evidence that any assessment is correct.

### Measured

```
state                  BLOCKED
attempts_required      1000
attempted              0
completed              null
failed                 null
latency_p50_ms         null
latency_p95_ms         null
latency_p99_ms         null
throughput_rps         null
error_rate             null
input_mix_hash         null
release_id             null
release_manifest_hash  null
started_at             null
finished_at            null
```

Two blockers:

- `DEPLOY_NO_ELIGIBLE_RELEASE` — no active validated release exists with both a
  `release_id` and a `release_manifest_hash`. Owner: scientific curators,
  expert reviewers and an administrator. A release must be approved, registered
  and activated before anything can be measured against it.
- `DEPLOY_PERFORMANCE_NOT_EXECUTED` — no running deployment exists to send
  requests to. Owner: WP-24 operation on a host with a container runtime.

`execute_run()` refuses without an eligible release and there is no flag that
relaxes it. A throughput figure produced against a development fixture is a
figure about a fixture, and the moment it appears next to the words "1,000
assessments" it becomes a claim about the system.

### The arithmetic was tested even though the run was not

`summarise()` and `percentile()` are exercised directly:

- percentile of an empty sample is `None`, not `0.0`;
- a zero-attempt summary reports `null` for latency, throughput and error rate;
- a failed attempt that returned in 2 ms is counted in `error_rate` and
  excluded from latency — a request that errored quickly is not evidence that
  the system is fast;
- the schema *refuses* a document with `attempted: 0` and a numeric p95.

That last one is the load-bearing test. It means a false zero cannot be
published even if a future producer computed one.

## 3. Reliability

Thirteen drills declared, each naming what is broken and what must follow.

| # | Drill | Expected | Executed |
|---|---|---|---|
| REL-001 | liveness while PostgreSQL is down | 200 | no |
| REL-002 | readiness while PostgreSQL is down | NOT_READY, names `database` | no |
| REL-003 | readiness with a migration mismatch | NOT_READY, names `migrations` | no |
| REL-004 | readiness with no active release | NOT_READY, no assessment performed | no |
| REL-005 | ClinPGx / LLM outage | no P0 effect at all | no |
| REL-006 | restart with a persistent database | volume survives, chain verifies across it | no |
| REL-007 | graceful stop | in-flight requests complete, pool disposed | no |
| REL-008 | audit chain verification | verifies, or names the first break | no |
| REL-009 | rate-limit backend failure | refuses, fails closed | no |
| REL-010 | missing sealed artifact | refusal, never a partial assessment | no |
| REL-011 | governed audit append failure | the change rolls back | no |
| REL-012 | image rollback | both identities recorded, no schema downgrade | no |
| REL-013 | backup and restore | all four runbook conditions | no |

```
declared_count   13
executed_count   0
failed_count     0
passed_count     null      ← not zero
```

`passed_count` is `null` because nothing ran. Zero would read as "none of them
passed", which is a different and much worse claim than "none of them ran".

A drill with no runner is `BLOCKED` — never passed. The three states (verified,
executed-and-wrong, not run) need different actions from different people.

### The two expectations that get inverted

**A database outage must not affect liveness.** Liveness answers whether the
process is alive; readiness answers whether it should receive traffic. A
liveness probe consulting PostgreSQL would have an orchestrator kill every
replica during a failover that was about to resolve itself, turning a
thirty-second blip into an outage. The image's `HEALTHCHECK` calls
`/health/live` and a test asserts it does not call `/health/ready`.

**An external source or model outage must not affect P0 at all.** ClinPGx and
any LLM are ingestion-time and P1 concerns. If either could move a readiness
component, the offline deterministic demo that P0's Definition of Done requires
would depend on the internet.

## 4. Rollback

`BLOCKED`. There is at most one image identity and there are zero eligible
releases.

The machinery is exercised against labelled test doubles, and those results
carry `TEST_ONLY_REHEARSAL` — which `ExecutionState.may_close_a_release_gate`
refuses, by property rather than by a condition somebody could forget.

A rollback recorded between one image and "the previous one" names an operation
nobody can reconstruct, so the drill reports a blocker when either image is
identified by tag alone. `database_downgraded: true` makes the drill a
**failure**, not a success.

## 5. Backup and restore

`BLOCKED`. Nothing was taken and nothing was restored.

```
backup_executed        false
destination_kind       none
restore_verified       false
conditions satisfied   0 of 4   (4 unevaluated, reported as null)
operational_status     BLOCKED
```

WP-23's `backup_executed: false` artifact is **unchanged**. This is a successor
observation that names what it supersedes.

## 6. What this report does not establish

Nothing was deployed, nothing was measured, no failure was injected and no
recovery was performed. Every declaration here is a statement of intent that a
later run will be held to.

The one thing it does establish is that the machinery which would produce those
results exists, is tested, and cannot report a number nobody measured.
