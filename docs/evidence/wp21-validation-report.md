# WP-21 - Validation metric evidence

| Field | Value |
|---|---|
| Document ID | `DOC-WP21-004` |
| Work package | WP-21 - Benchmark and Validation Metrics |
| Machine-readable | `data/validation/wp21-real-gate-status.json` |
| Public report | `data/validation/wp21-validation-report.json` |
| Dashboard feed | `data/validation/wp21-dashboard-feed.json` |
| Registry | `data/validation/wp21-metric-definitions.json`, `data/validation/wp21-failure-path-catalogue.json` |
| Produced on | Linux, CPython 3.11, `uid 0`, no PostgreSQL, no `coverage.py`, no network |

> **No validation result is reported here, because none exists.** This
> document records that the metric machinery is implemented and that every
> metric is `NOT_EXECUTED`. It is not clinical validation, not scientific
> validation, not expert review, and no number in it establishes that the
> system is safe for any patient.

---

## 1. Result

| Measure | Value |
|---|---|
| Metric framework implemented | **true** |
| Metric definitions | 15 |
| Failure paths (predeclared) | 10 |
| Thresholds declared | **0** |
| Benchmark executed against active release | **false** |
| Active release available | **false** |
| DEVELOPMENT cases | 7 |
| INTERNAL_HOLDOUT cases | **0** |
| EXPERT_HOLDOUT cases | **0** |
| Validation evidence cases | **0** |
| Reference judgments supplied | **0** |
| Restricted storage configured | **false** |
| Separation audit | **clean**, 7 cases, 10 rules, 0 issues |
| Numeric validation metrics | **0** |
| Clinical validation performed | **false** |
| Expert review performed | **false** |
| Benchmark gate | **BLOCKED** |
| Release may proceed | **false** |
| Blockers | 8 |

## 2. Every metric, and why it has no value

45 metric values were produced - fifteen metrics across three partitions - and
all 45 are `NOT_EXECUTED` with reason `BENCHMARK_NOT_EXECUTED`.

`NOT_EXECUTED` is deliberately distinct from the other empty states. Its
`numerator` and `denominator` are both `null`, because nobody counted
anything. An `UNAVAILABLE` metric may report a real counted denominator of
zero; this one cannot, because no counting happened.

| Section | Role | Validation evidence | Cases | Metrics | With a value |
|---|---|---|---|---|---|
| `DEVELOPMENT_REGRESSION` | DEVELOPMENT | **no** | 7 | 15 | 0 |
| `INTERNAL_HOLDOUT` | INTERNAL_HOLDOUT | yes | 0 | 15 | 0 |
| `EXPERT_HOLDOUT` | EXPERT_HOLDOUT | yes | 0 | 15 | 0 |

`combined_overall_metric` is `null` and the schema pins it there. There is no
field in which a pooled development-plus-holdout figure could be published.

The committed report contains no `%` character, no rate string and no
percentage. This was verified by scanning the serialised bytes, not by
inspection.

## 3. Development is excluded, structurally

The seven development cases shaped the software. They appear under
`DEVELOPMENT_REGRESSION`, carry `is_validation_evidence: false`, and cannot
enter a validation denominator. Three independent layers:

1. `MetricDefinition` raises if a metric claims to be validation evidence and
   lists `DEVELOPMENT` among its eligible roles - the combination cannot be
   constructed.
2. `BenchmarkEngine.compute` returns one result set per role and has no
   operation that merges them.
3. The report schema rejects a document where the `DEVELOPMENT_REGRESSION`
   section claims `is_validation_evidence: true`.

The view model adds a fourth at the presentation layer: a
`ValidationBoardModel` holding a development section marked as evidence raises
before the page can render.

## 4. The capability, demonstrated where demonstrating it is honest

A repository that can only report emptiness has not shown that its metric
engine works. So the engine is exercised end to end against a **TEST-ONLY
synthetic release** in `tests/fixtures/wp21/synthetic_release.py`, and the
resulting table is asserted:

| Metric | INTERNAL_HOLDOUT | EXPERT_HOLDOUT |
|---|---|---|
| `PGX-VAL-001` concordance | `0.7500` (6/8) | `0.6667` (2/3) |
| `PGX-VAL-003` false reassurance | `1` (1/8) | `0` (0/3) |
| `PGX-VAL-006` evidence traceability rate | `0.9000` (18/20) | `0.8333` (5/6) |
| `PGX-VAL-008` repeatability rate | `0.8750` (7/8) | `1.0000` (3/3) |
| `PGX-VAL-010` holdout pass rate | `0.6250` (5/8) | `0.6667` (2/3) |
| `PGX-VAL-015` failure-path coverage | `0.5000` (5/10) | `0.0000` (0/10) |

Note the two columns disagree, deliberately. Pooling them would give 8/11 for
concordance - neither partition's answer, and a figure whose reader could not
tell which partition carried it. That is why there is no pooled figure.

Note also `PGX-VAL-003` reporting `0` for the expert partition alongside a
denominator of 3. That is a **measured zero**: three cases ran and none was
falsely reassuring. It serialises differently from the zero-denominator case
and differently again from the unexecuted case, which is the distinction this
whole work package is built around.

Every identifier in that fixture begins `TEST-ONLY-` or `SYNTH-`. A test
asserts that no such string appears in the committed report.

**These numbers describe nothing.** They are a synthetic release that does not
exist, judged against synthetic reference judgments nobody wrote. They prove
the arithmetic and nothing else.

## 5. Blockers

Eight, and none can be closed by writing code.

| Code | Owner |
|---|---|
| `BENCHMARK_NO_ACTIVE_RELEASE` | WP-03 operation |
| `BENCHMARK_NO_HOLDOUT_CASES` | scientific curators; a holdout case cannot be generated |
| `BENCHMARK_NO_VALIDATION_EVIDENCE_CASES` | scientific curators |
| `BENCHMARK_NO_REFERENCE_JUDGMENT` | scientific curators under the WP-22 protocol |
| `BENCHMARK_RESTRICTED_STORAGE_NOT_CONFIGURED` | deployment |
| `BENCHMARK_EXPERT_REVIEW_NOT_IMPLEMENTED` | WP-22 and named experts |
| `BENCHMARK_NOT_EXECUTED` | whoever runs a benchmark once a release exists |
| `BENCHMARK_CLAIM_BOUNDARY_NOT_APPROVED` | named human and scientific reviewers |

## 6. What is not inherited from WP-20

WP-20 reported 37/37 negative controls detected and 0 false-reassurance
violations over a corpus of 36. Those are software detector results about
constructed unsafe states.

None of them appears in this report. `PGX-VAL-003` and `PGX-VAL-004` measure
something else entirely - eligible observations under a pinned release - and
with no such observations they are unavailable, not zero.

The separation is structural: `pgx/validation` imports nothing from
`pgx/safety`, asserted by reading the AST of every module in the package.

## 7. The public boundary

The committed report and feed carry release identity and hashes, versions,
partition names, per-metric numerator, denominator, value, status and reason,
case counts, artifact hashes and blocker summaries.

They carry no case identifier, observation, phenotype, medication, expected
answer, expert response, filesystem path, username, hostname or credential.
`assert_public_report_is_safe` walks the finished document and refuses on any
of them, including path-shaped string *values*, so a detail message cannot
leak the build machine into an evidence artifact.

`restricted_case_evidence_artifact` is `null`. Case-level execution evidence
is a separate restricted artifact; none exists and none was generated.

## 8. Dashboard

`/validation` shows three tables, never combined, read from the committed
public feed through an adapter that imports no benchmark engine and holds no
port to restricted storage.

Every metric value renders as *Kullanılamıyor* / *Unavailable*. The rendered
page contains no `%` character and no metric value cell carrying a number.

One `0` does appear, twice: the holdout **case count**. That is a counted zero
and printing it is correct - there really are zero holdout cases. A counted
zero prints; an uncomputed metric does not. Asserting that no `0` appears
anywhere on the page would have forced the honest count into hiding.

## 9. Reproducing this

```
pgx-benchmark definitions
pgx-benchmark report
pgx-benchmark gate-status
pgx-benchmark run
pgx-benchmark artifacts
python -m unittest discover -s tests/unit/benchmark -p 'test_*.py' -t .
```

`report`, `gate-status` and `run` exit `2`. That is the correct outcome.

The four deterministic artifacts rebuild byte for byte; a test builds each
twice and compares, then compares against the committed bytes.

## 10. Explicit non-claims

- No benchmark was executed against any release.
- No validation percentage, rate or ratio is reported.
- No clinical validation was performed.
- No scientific validation was performed.
- No expert review was performed or obtained.
- No holdout case exists; none was created.
- No reference judgment exists; none was invented.
- No threshold was declared.
- No release was activated.
- No expected answer was added to any WP-18 case or manifest.
- No PostgreSQL, network, LLM or browser was required or used.
- No coverage percentage is claimed; `coverage.py` is absent.

**WP-21's software is complete. The benchmark gate is BLOCKED. Both are true,
and the second governs release.**
