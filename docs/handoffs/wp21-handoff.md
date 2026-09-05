# WP-21 handoff

## State

The benchmark and validation metric system is implemented.

`pgx/validation/` gains 8 modules, `pgx-benchmark`, 6 published schemas, 5
data artifacts, 4 documents, 182 new tests. For the first time the repository
can say what a validation metric *is* - numerator, denominator, eligible
roles, and what it reports when there is nothing to count - and it says all of
that while having nothing to count.

```
pgx-benchmark definitions      # the registry and the failure-path catalogue
pgx-benchmark report           # the public aggregate report
pgx-benchmark gate-status      # implemented; not validated
pgx-benchmark artifacts        # regenerate, deterministically
pgx-benchmark run              # refuses: nothing to pin, nothing to run
```

Current result: **metric framework implemented, benchmark gate `BLOCKED`,
release may not proceed, 15 metric definitions, 10 failure paths, 0
thresholds, 0 numeric validation metrics, 7 development cases, 0 holdout
cases.**

## What the next work package inherits

### Implemented is not computed, and computed is not validated

The single most important thing to carry forward. Three separate facts, three
separate fields, allowed to disagree:

```
metric_framework_implemented              true    software exists
benchmark_executed_against_active_release false   nobody ran it
clinical_validation_performed             false   nobody judged it
```

A future package that reports one boolean for "is validation done" will be
wrong in at least two directions at once. WP-18 learned this the hard way and
so did WP-20; the pattern is now three deep.

### Nobody looked, we looked and found nothing, and we found zero

Three states that a naive serialisation collapses into `0`:

| | `value` | `numerator` | `denominator` |
|---|---|---|---|
| Measured zero over 8 cases | `"0.0000"` | `0` | `8` |
| Zero denominator | `null` | `0` | `0` |
| Never executed | `null` | `null` | `null` |

`MetricValue.__post_init__` refuses an `AVAILABLE` rate over a zero
denominator and a `NOT_EXECUTED` value carrying a denominator. The published
schema enforces both independently, so a hand-edited artifact fails validation
rather than being believed. Do not add a code path that fills a denominator
into a `NOT_EXECUTED` value "for completeness".

`build_real_report` and `BenchmarkEngine.compute` are deliberately different
functions. Running the engine over an empty observation list would produce a
table of `UNAVAILABLE` values that looks almost identical to the real report
and means something different. Keep them apart.

### Rates are decimal strings, not floats

`format_rate` uses `decimal` with banker's rounding and returns a string. No
float repr reaches an artifact, so the committed bytes do not depend on the
platform. A future package that "simplifies" this to `round(n/d, 4)` will make
the artifacts non-reproducible across machines and the reproducibility test
will catch it - but only after somebody has committed the change.

### The catalogue is the denominator

`PGX-VAL-014` and `PGX-VAL-015` divide by the size of the predeclared
failure-path catalogue, never by the paths a run happened to exercise. A run
touching two paths reports **2/10**.

Adding a failure path changes what "complete" means, which is why
`FAILURE_PATH_CATALOGUE_VERSION` is separate from the metric registry version.
Bump it.

### Thresholds need provenance, and the mechanism is deliberately open

Every `threshold` is `None` today. `MetricDefinition` refuses a threshold
whose `threshold_provenance` is empty, so a real predeclared policy can use
the field and an implementer cannot.

Do not add a threshold because a number looked good. A threshold derived after
viewing results describes those results; it does not judge them.

### There is no combining operation, and adding one is a defect

`compute` returns `{role: [values]}` and nothing merges them.
`combined_overall_metric` is pinned `null` in the schema, so a pooled figure
has no field to live in.

The synthetic fixture demonstrates why: internal concordance is 6/8, expert is
2/3, and pooling gives 8/11 - neither partition's answer, and a number whose
reader cannot tell which partition carried it.

### A mismatch refuses the whole run

Not the row. If one observation names a different release hash, the run raises
`PinMismatchError` and produces nothing. Dropping the bad row and continuing
would produce a report whose title is false about its contents, and the
exclusion would be invisible.

Similarly, a dirty separation audit stops everything before any observation is
collected - not "the clean partitions only".

### Production never imports tests, and there is no fixture switch

`pgx/validation` and `pgx/application/benchmark_*` import nothing from
`tests.*`, asserted by AST and by a string scan of non-comment lines. The
synthetic release is injected through the ports.

There is no `--use-test-fixture` flag and there must not be one. A production
switch that swapped real emptiness for synthetic numbers would be one
command-line typo away from a fabricated validation result. The boundary test
asserts this against the argparse parser's real options rather than the file's
text - the module docstring explains why the flag is absent, so a substring
search finds its own prose and passes for the wrong reason.

### The web layer sees one file

`apps/web/validation_feed.py` opens `data/validation/wp21-dashboard-feed.json`
and returns it. It imports no `pgx` module at all, holds no port, and has no
path to restricted storage - so a request handler using it cannot reach a
holdout payload even by mistake.

A missing or malformed feed returns `None` and the page renders its empty
state. It does not fall back to computing one: a dashboard that recomputed its
own numbers would be the one place where a page could disagree with the
committed evidence.

## What WP-22 must supply

WP-21 declared the port and left it empty:

```python
class ReferenceJudgmentPort:
    def judgments(self, *, role) -> Mapping[str, ReferenceJudgment]: ...
```

A `ReferenceJudgment` is a **separate immutable record with provenance**, not
a field on a case. WP-18 stores no expected answer so that authoring a case
cannot double as writing its answer key, and WP-21 preserved that: no field
named `expected_result`, `expected_attention`, `expected_coverage`,
`gold_standard`, `ground_truth`, `answer_key`, `score`, `concordance` or
`expert_decision` was added to any case or manifest. A test asserts it.
Do not add one.

`ReferenceJudgment` refuses construction with empty provenance. An expected
answer nobody signed may not enter a denominator.

`PGX-VAL-011` and `PGX-VAL-012` are the expert metrics. Their handlers exist
and are unreachable while `requires_expert_review` short-circuits them to
`EXPERT_REVIEW_NOT_IMPLEMENTED` - deliberately, so WP-22 wires a port rather
than writing the metrics from scratch.

Note also that a reference judgment and an expert decision are **different
inputs**. The synthetic fixture supplies judgments and the expert distribution
stays unavailable, which is asserted. Conflating them would let a curator's
expected answer be reported as an expert's opinion.

WP-21 implemented no part of the reveal protocol, review storage or expert
decision capture. A boundary test walks the AST of every WP-21 module and
fails on a function or class whose name contains `reveal`.

## What WP-24 will need

`pgx-benchmark` exits `2` for `run`, `report`, `feed` and `gate-status` in
this repository, and that is the correct outcome. A CI job that treats
non-zero as failure will go red on a truthful state; a job that treats `2` as
"blocked, not broken" is the one worth writing. Exit `1` is a real defect.

The four deterministic artifacts must rebuild byte for byte. The gate status
is excluded from that check because it reads the environment - same reason
WP-19 excludes its own.

## What changed outside `pgx/validation/`

### WP-18: one blocker replaced, three marker paths corrected

`VALIDATION_METRICS_NOT_IMPLEMENTED` is gone, replaced by
`VALIDATION_BENCHMARK_NOT_PASSING`, which reads WP-21's committed gate status
rather than asserting one. "Not implemented" would now send a reader to the
wrong place: there is nothing left to build and something left to author.

`validation_metrics_implemented` became `true` and its schema pin changed from
`{"const": false}` to `{"type": "boolean"}` in the same change.
`validation_metric_count` stays `null` - it counts metrics *computed for a
release*, and none was. A new `validation_metric_definition_count` carries the
15, so the two can never be read as one number.

`expert_review_implemented` was not touched. `clinical_validation_performed`
was not touched.

WP-18's WP-21 marker paths were wrong: it guessed `pgx/benchmark` and
`pgx/metrics`, neither of which was ever built, because the metric code
depends on the partition it must not violate and therefore lives inside
`pgx/validation`. Left uncorrected, WP-18 would have reported
`wp21_started: false` forever while WP-21 was finished.

### WP-20: one field, one schema pin, one blocker

`validation_metrics_implemented` went `false` → `true`, and
`schemas/wp20/wp20-gate-status.schema.json` changed from `{"const": false}` to
`{"type": "boolean"}` in the same visible change. It was always a statement
about software; once the software existed, pinning it false would have made
the schema assert something untrue.

`clinical_validation_performed` and `expert_review_performed` remain `false`
and remain `const`. Those are people's acts and no work package flips them.

`SAFETY_POOLED_METRIC_CHECK_OWNED_BY_WP21` was removed from `SAFETY-INV-009`
and **only that one**. It said the pooling and zero-denominator questions were
unanswerable until metrics existed; they exist now and both are enforced.
`SAFETY_NO_HOLDOUT_CASES_EXIST` stays: zero holdout cases is a scientific fact
no code closes, and removing both would have turned a real gap into a green
row. `SAFETY-INV-009` remains `BLOCKED`.

The WP-20 safety gate remains `BLOCKED` with 11 blockers.

### WP-19: eight rules, one requirement, one profile

The inventory refused the eight new WP-21 test modules on first run -
fail-closed working exactly as documented. Rules added per module rather than
wholesale, because what each asserts differs: the metric registry is a
`DOMAIN_INVARIANT` (a metric that pooled roles would be a safety defect, not a
wrong number), the contract tests are `FAILURE_NEGATIVE`, the report tests are
`ARTIFACT_SCHEMA`, the dashboard tests are `SNAPSHOT`.

`VER-REQ-022` added (22 total), mapped to `SAFETY-INV-009`: pooling roles is
the same violation the invariant names, expressed as arithmetic rather than as
a case set.

A `validation` profile covers `tests.unit.validation`,
`tests.unit.benchmark` and `tests.integration.validation` with a floor of 350.
No existing selector or floor was weakened.

WP-19's gate status now also reads WP-21's committed benchmark state through
`_benchmark_gate_state`, which reports `ABSENT` when the file is missing and
never infers `PASS`. **WP-19 does not block on it.** A verification suite is
not a validation result, and making a green test run wait on a scientific gate
would blur the line both packages exist to defend.

### WP-17: one boundary assertion moved, openly

`test_no_web_module_stores_a_case_role_other_than_development` asserted that
the two holdout role names appeared nowhere in `apps/web`. That was right
while the interface had no validation architecture to talk about; WP-21 gives
the page one section per partition, so it must be able to write the headings.

The assertion moved to what it was always defending - no web module may hold a
holdout *case*, identifier or payload - and a new test states that directly.
The neighbouring tests that enforce it are unchanged. Naming a partition in a
heading leaks nothing; holding one of its cases does.

### WP-18's own boundary tests, scoped

`TestNoMetricIsComputedHere` walked every file under `pgx/validation` and
asserted none named a numerator or performed a division. WP-21 put the metric
engine in that package - deliberately - so the original assertion would now
fail for the right reason, which is the same as failing for no reason.

It now ranges over WP-18's twelve named modules, and a new test asserts that
every file in the package is on exactly one of the two lists. Without that, a
new module would be exempt from both checks by being on neither, which is the
quietest possible way to lose a guarantee.

## Blocked, and none of it by code

Eight blockers on the WP-21 gate:

| Blocker | Who closes it |
|---|---|
| `BENCHMARK_NO_ACTIVE_RELEASE` | WP-03 operation |
| `BENCHMARK_NO_HOLDOUT_CASES` | scientific curators |
| `BENCHMARK_NO_VALIDATION_EVIDENCE_CASES` | scientific curators |
| `BENCHMARK_NO_REFERENCE_JUDGMENT` | scientific curators under WP-22 |
| `BENCHMARK_RESTRICTED_STORAGE_NOT_CONFIGURED` | deployment |
| `BENCHMARK_EXPERT_REVIEW_NOT_IMPLEMENTED` | WP-22 and named experts |
| `BENCHMARK_NOT_EXECUTED` | whoever runs a benchmark once a release exists |
| `BENCHMARK_CLAIM_BOUNDARY_NOT_APPROVED` | named human and scientific reviewers |

**WP-21's software is complete and the benchmark gate is `BLOCKED`.** Both are
true. The second governs release.

## Not started

WP-22, WP-23, WP-24 and WP-25 are not started. No marker for any of them
exists in this repository - measured from the tree, not asserted - and a
boundary test fails if one appears.
