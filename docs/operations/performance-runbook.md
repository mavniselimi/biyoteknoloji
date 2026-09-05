# Performance runbook (WP-24)

| Field | Value |
|---|---|
| Document ID | `DOC-OPS-024-C` |
| Targets | `pgx/deployment/performance.py`, `data/deployment/wp24-performance-targets.json` |
| Status | **Targets declared. The 1,000-assessment run has not been executed.** |

---

## 1. The order matters

Targets are declared **before** any measurement, as `architecture.md` §14.3
requires. They live in code as a constant with a version, are committed as an
artifact, and are the same discipline WP-21 applies to its metric registry.

A target chosen after the numbers is not a target. It is a description.

| Target | Metric | Bound | Why that number |
|---|---|---|---|
| PERF-001 | `latency_p50_ms` | ≤ 250 | a demonstration is a person clicking through cases; a deterministic rule evaluation with no model call has nothing that should take longer |
| PERF-002 | `latency_p95_ms` | ≤ 1000 | the tail is what a demonstration trips over; a slower tail usually means a connection-pool wait rather than computation |
| PERF-003 | `throughput_rps` | ≥ 20 | one container with the recorded CPU and memory limits; not a capacity claim and does not extrapolate |
| PERF-004 | `error_rate` | ≤ 0.001 | a deterministic engine given permitted input has no legitimate reason to fail, so any error is a defect rather than a load characteristic |
| PERF-005 | `output_determinism` | == 1.0 | identical input against the same release must produce byte-identical output |

**These are engineering and prototype targets for a demonstration deployment.**
They are not clinical performance claims, not a service level, and not evidence
that any assessment is correct.

## 2. Percentile arithmetic, fixed in advance

Nearest-rank on the sorted sample of **completed** observations:

```
index = ceil(p / 100 × n),  clamped to [1, n]
```

- Failed attempts are counted in `error_rate` and **excluded** from latency. A
  request that errored in 2 ms is not evidence that the system is fast.
- With `n == 0` every percentile and the throughput are **`null`**. Never zero:
  zero milliseconds reads as instantaneous and zero requests per second reads
  as measured.
- A rate over zero attempts is undefined, not zero. An `error_rate` of `0.0`
  for a run that never started is the single most misleading number this
  harness could produce.

## 3. Preconditions

The run **refuses** without an active validated release carrying **both** a
`release_id` and a `release_manifest_hash`. Both, not either: an id without a
manifest hash names a release whose contents are not pinned, and a measurement
attached to it could not be reproduced or contested.

There is no flag that relaxes this.

Inputs are permitted synthetic or validation cases only. No raw patient,
genotype, VCF or EHR input ever enters this harness — WP-11's safety invariant
covers that, and the input mix is recorded as case ids plus a hash.

## 4. Running it

```bash
pgx-deploy performance --environment STAGING
```

Records, all of it:

attempted (exactly 1,000) · completed · failed · warm-up policy (50, declared
in the registry rather than chosen at run time, so a slow run cannot be
improved by warming up for longer) · concurrency · p50 · p95 · p99 · min · max
· throughput · error rate · response-code distribution · input mix ids and hash
· release, software, dataset and ruleset ids · release manifest hash · image
digest · CPU/memory/pids limits · host and container platform · start and end
timestamps · target registry version.

Never records: a response body, a credential, a session cookie, a CSRF token,
or any holdout content. Outputs are compared by hash.

## 5. Determinism is reported separately from latency

Latency varies legitimately between runs. Output does not. A single "stable"
figure covering both could hide a nondeterministic result inside a spread of
timings, so `output_determinism` is its own field with its own target.

## 6. The rehearsal path

A `TEST_ONLY_REHEARSAL` run exists to prove the percentile arithmetic and the
request generation. It is labelled in the artifact, it never closes a gate
(`ExecutionState.TEST_ONLY_REHEARSAL.may_close_a_release_gate` is `False`), and
it does not relax the release requirement — it changes what the result is
*called*.

## 7. Current status

`BLOCKED`, twice over:

- `DEPLOY_NO_ELIGIBLE_RELEASE` — no approved, registered, activated release
  exists. Owner: scientific curators, expert reviewers and an administrator.
- `DEPLOY_PERFORMANCE_NOT_EXECUTED` — no deployment exists to send requests to.
  Owner: WP-24 operation on a host with a container runtime.

Every metric in the committed result is `null`.
