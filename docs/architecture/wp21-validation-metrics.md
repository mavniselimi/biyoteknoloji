# WP-21 - Benchmark and Validation Metrics

| Field | Value |
|---|---|
| Document ID | `DOC-ARCH-021` |
| Work package | WP-21 - Benchmark and Validation Metrics |
| Status | **software IMPLEMENTED; benchmark gate BLOCKED** |
| Machine-readable | `pgx/validation/metric_definitions.py`, `pgx/validation/benchmark.py` |
| Artifacts | `data/validation/wp21-*.json` |
| Schemas | `schemas/wp21/` |
| Architecture source | `architecture.md` sections 11.2, 12.1, 12.3, 16, 17 |
| Companion documents | `docs/validation/metric-definitions.md`, `docs/validation/benchmark-protocol.md` |

> **This document describes machinery, not results.** WP-21 builds the system
> that would produce a release validation table. No release has been
> benchmarked. Every metric in the committed report is `NOT_EXECUTED`, no
> percentage appears anywhere, and no clinical or scientific validation has
> been performed or is implied.

---

## 1. The problem WP-21 solves, and the one it must not create

Before WP-21 the reports in this repository showed examples and row counts.
Nothing said what a validation metric *was*: what its numerator counted, what
its denominator counted, which cases were eligible, or what it should report
when there was nothing to count.

That gap is dangerous in one specific direction. A system with no metric
definitions and a strong desire to look validated will reach for whatever
numbers it already has. This repository has plenty: 5,900 passing tests,
37/37 negative controls detected, 0 false-reassurance violations over a corpus
of 36. Every one of those is a real result about software, and every one of
them becomes a lie the moment it is presented as clinical or validation
evidence.

So WP-21's design constraint is not "compute metrics accurately". It is
**make the wrong number unrepresentable**:

- a rate with a zero denominator has no field to be `0` in;
- a development case has no path into a validation denominator;
- a pooled development-plus-holdout figure has no key in the schema;
- a threshold cannot be added without provenance;
- an unexecuted benchmark serialises differently from a measured zero.

Each of those is enforced by a type, a schema constraint or a refusal - not by
a convention someone must remember.

## 2. Six things that are not each other

The single most common category error in validation work is treating any of
these as evidence for the next one. They are listed in increasing order of
what they establish, and WP-21 delivers only the first.

| | What it is | Status here |
|---|---|---|
| 1. Metric implementation | Code that defines and computes a metric | **Complete** |
| 2. Benchmark execution | Running that code against one pinned release | **Not executed** - no release |
| 3. Development regression | Running the 7 development cases | Available; **not validation evidence** |
| 4. Holdout validation | A benchmark over cases withheld from development | **Impossible** - zero holdout cases |
| 5. Expert review | A named person working a case blind (WP-22) | **Not started** |
| 6. Clinical validation | Evidence the system is safe and correct for patients | **Not performed** |

1 does not imply 2. 2 over development cases is 3, never 4. 4 without 5 is
incomplete. And 6 is not the sum of the others - it is a scientific judgement
made by people who have 4 and 5 in front of them.

## 3. The metric registry

Fifteen definitions covering the ten metrics `architecture.md` section 12.3
requires. Ten becomes fifteen because the architecture states several as
"count and rate", which are two metrics with two denominators and two ways of
being unavailable; one record cannot be both an integer count and a
null-when-zero rate.

Each `MetricDefinition` carries: stable ID, title, plain meaning, kind
(`COUNT` / `RATE` / `DISTRIBUTION`), exact numerator, exact denominator,
eligible roles, whether it is validation evidence, required inputs, the
reason codes under which it may be unavailable, rounding policy, whether
expert review is required, and threshold plus threshold provenance.

**Every threshold is `None`.** A release threshold is a policy decision made
by named people before results exist. No such policy exists, so there is no
threshold. The dataclass refuses a threshold without provenance, so the
mechanism is available to a future policy while the shortcut is closed.

`docs/validation/metric-definitions.md` is the full table.

## 4. Metric value semantics

```
AVAILABLE       computed from real observations; value is a measurement
UNAVAILABLE     the benchmark ran; this number does not exist (usually a
                zero denominator). May carry a real counted denominator of 0.
NOT_EXECUTED    nobody ran it. numerator and denominator are both null.
BLOCKED         a precondition outside the metric's control failed; the
                computation was refused rather than attempted.
NOT_APPLICABLE  the metric genuinely does not apply. Used sparingly.
```

The three states that look alike in a naive serialisation are kept apart by
construction:

| | `value` | `numerator` | `denominator` |
|---|---|---|---|
| Measured zero over 8 cases | `"0.0000"` | `0` | `8` |
| Zero denominator | `null` | `0` | `0` |
| Never executed | `null` | `null` | `null` |

`MetricValue.__post_init__` refuses an `AVAILABLE` rate with a zero
denominator and a `NOT_EXECUTED` value carrying a denominator. The published
schema enforces the same two rules independently, so a hand-edited artifact
fails validation rather than being believed.

Rates serialise as fixed-point decimal **strings** through `decimal` with
banker's rounding. No float repr reaches an artifact, so the bytes do not
depend on the platform that produced them.

## 5. Partition separation

WP-21 reads `ValidationCaseMetadata.is_validation_evidence` and does not
re-decide it. Three enforcement layers:

1. **Definition.** `MetricDefinition` raises if a metric claims to be
   validation evidence and lists `DEVELOPMENT` among its eligible roles. The
   combination is unconstructable.
2. **Computation.** `BenchmarkEngine.compute` returns `{role: [values]}` and
   has no operation that merges roles. `INTERNAL_HOLDOUT` and
   `EXPERT_HOLDOUT` are computed independently; there is no cross-holdout
   aggregate either.
3. **Report.** Development results appear only under the section named
   `DEVELOPMENT_REGRESSION`, and the schema rejects a document where that
   section claims `is_validation_evidence: true`. `combined_overall_metric`
   is pinned to `null`.

`audit_partition` runs **before** any metric is computed. A dirty audit raises
`SeparationNotCleanError` and nothing is computed - not "the clean partitions
only". A case set whose roles may have leaked produces measurements about
memory rather than generalisation, and no later analysis undoes that.

Determinism, conflict counts and failure-path coverage *are* computed over
development cases, because those are software properties worth regressing.
Every such value is marked `is_validation_evidence: false`.

## 6. The benchmark contract

A `BenchmarkPlan` pins, before anything executes: protocol version, release
public ID, release manifest hash, software version and hash, dataset public
ID and content hash, ruleset public ID and content hash, one case-manifest
hash **per role**, metric registry version and digest, declared metric IDs,
failure-path catalogue version, the roles, and the repeat count.

The release is resolved **once**, through `ReleaseResolutionPort`, and held in
the plan. Nothing re-reads an active-release pointer mid-run: an activation
committing during a benchmark changes the next run, not this one.

Every observation echoes the pinned identities back. **Any mismatch refuses
the whole run**, not the offending row. Dropping a disagreeing observation and
continuing would produce a report whose title is false about its contents.

Observations are ordered deterministically at serialisation, so input order
cannot change the report hash. The scientific digest excludes timestamps -
otherwise "did two runs agree" could never be true.

### Ports

```
ReleaseResolutionPort      resolve() -> PinnedRelease
RestrictedObservationPort  observe(role, plan) -> [BenchmarkObservation]
ReferenceJudgmentPort      judgments(role) -> {case_id: ReferenceJudgment}
```

Production code never imports `tests.*`. The synthetic release that proves the
engine can render a numerical table is injected in the test suite; there is no
`--use-test-fixture` production switch, because one typo away from a
fabricated validation result is too close.

## 7. Reference judgments, and why WP-18 has none

WP-18 deliberately stores no expected answer: authoring a case must not double
as writing its answer key. WP-21 preserves that. A reference judgment is a
**separate immutable record** with its own provenance, supplied through a
port.

This repository has none, so `PGX-VAL-001`, `PGX-VAL-002`, `PGX-VAL-009` and
`PGX-VAL-010` report `NO_REFERENCE_JUDGMENT`. That is a different statement
from "zero correct", and the artifact keeps them different.

No field named `expected_result`, `expected_attention`, `expected_coverage`,
`gold_standard`, `ground_truth`, `answer_key`, `score`, `concordance` or
`expert_decision` was added to any case or manifest. A test asserts it.

## 8. The false-reassurance boundary

WP-20 reported 37/37 negative controls detected and 0 violations over a corpus
of 36. Those are **software detector results**.

`PGX-VAL-003` and `PGX-VAL-004` are a different measurement: eligible
benchmark observations under a pinned release, counted where a reassuring
attention level accompanied incomplete coverage. With no such observations
they are unavailable.

The two are kept apart structurally: `pgx/validation` imports nothing from
`pgx/safety`, and a test reads the AST to prove it.

## 9. The failure-path catalogue

Ten predeclared paths (`FP-001` .. `FP-010`), versioned separately from the
metric registry because adding one changes what "complete" means.

This catalogue is the denominator for `PGX-VAL-014` and `PGX-VAL-015`. A run
exercising two paths reports **2 out of 10**, never 2 out of 2. Inferring the
denominator from the paths that happened to run would give the least thorough
possible run the most flattering possible score.

## 10. Public versus restricted output

The public report and the dashboard feed carry: release identity and hashes,
protocol and registry versions, partition names, per-metric numerator,
denominator, value, status and reason code, case counts, artifact hashes and
blocker summaries.

They carry **no** case identifier, observation, phenotype, medication,
expected answer, expert response, filesystem path, username, hostname or
credential. `assert_public_report_is_safe` walks the finished document and
refuses on any of them - including path-shaped *values*, so a detail message
cannot leak the build machine into an evidence artifact.

Case-level execution evidence is a separate restricted artifact.
`restricted_case_evidence_artifact` is `null` here, and its absence is
reported rather than filled.

## 11. Dashboard

`/validation` reads `data/validation/wp21-dashboard-feed.json` through
`apps/web/validation_feed.py` - an adapter that opens one committed file. It
imports no benchmark engine, holds no port and has no path to restricted
storage, so a request handler using it cannot reach a holdout payload.

The page shows three tables, never combined. `DEVELOPMENT_REGRESSION` is a
separate section under a heading that says it is not validation evidence, with
its own warning block and its own CSS class. Unavailable metrics render as
*Kullanılamıyor* / *Unavailable*, never as `0` or `0%`. Every page keeps the
`Research/Prototype Use Only` banner.

The one `0` visible on the real page is the holdout **case count**, which is a
counted zero and correct. That distinction - a counted zero prints, an
uncomputed metric does not - is the page's whole design.

## 12. Current state

| Measure | Value |
|---|---|
| Metric framework implemented | **true** |
| Metric definitions | 15 |
| Failure paths | 10 |
| Thresholds | **0** |
| Benchmark executed against active release | **false** |
| Active release available | **false** |
| DEVELOPMENT cases | 7 |
| INTERNAL_HOLDOUT cases | **0** |
| EXPERT_HOLDOUT cases | **0** |
| Validation evidence cases | **0** |
| Reference judgments | **0** |
| Numeric validation metrics | **0** |
| Clinical validation performed | **false** |
| Expert review performed | **false** |
| Benchmark gate | **BLOCKED** |
| Release may proceed | **false** |

**WP-21's software is complete and the benchmark gate is BLOCKED.** Both are
true. The second governs release.

## 13. Change control

Adding, removing or restating a metric changes what this system claims to
measure. Any such change requires an update to this document, a corresponding
change to `pgx/validation/metric_definitions.py` and its tests, and - where it
touches the safety contract's invariants - an Architecture Decision Record
under `docs/architecture/decisions/` (`architecture.md` section 23).

Adding a threshold additionally requires a predeclared, reviewable policy with
recorded provenance, decided before results exist. A threshold derived after
viewing results describes those results; it does not judge them.
