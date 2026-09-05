# WP-21 - Metric definitions

| Field | Value |
|---|---|
| Document ID | `DOC-VAL-021` |
| Work package | WP-21 |
| Machine-readable | `pgx/validation/metric_definitions.py` |
| Generated artifact | `data/validation/wp21-metric-definitions.json` |
| Registry version | `pgx-wp21-metric-registry/1` |
| Architecture source | `architecture.md` section 12.3 |

> Every definition here was written **before** any result existed - while this
> repository had zero holdout cases and no active release, and therefore while
> nobody could tune a definition to make a number look better. No metric
> carries a threshold. Nothing in this document is a result.

---

## 1. Why definitions come first

A metric defined after its first result has been seen is not a measurement; it
is a description of that result. The ordering is the only thing that makes the
difference, and it cannot be recovered later - so the registry is committed
now, in an empty repository, where the incentive to shape it does not yet
exist.

Three consequences are enforced rather than documented:

- **No thresholds.** `threshold` is `null` for all fifteen. A release
  threshold is a policy decision by named people with recorded provenance.
  There is no such policy. `MetricDefinition` refuses a threshold without
  provenance, so a real policy can use the field later and an implementer
  cannot use it now.
- **Eligible roles are part of the definition.** Excluding development from a
  validation metric is not a rule the runner remembers; it is a property of
  the metric that the runner reads. The dataclass refuses a metric that
  claims to be validation evidence and accepts `DEVELOPMENT`.
- **Unavailability is enumerated.** Each metric names the reason codes that
  can make it unavailable. A metric returning a reason its definition never
  listed raises, because either the runner or the definition is wrong and
  both need a person.

## 2. The registry

`architecture.md` section 12.3 lists ten metrics. This registry holds fifteen
definitions, because the architecture states several as "count and rate" -
two metrics with two denominators and two ways of being unavailable. One
record cannot be both an integer count and a null-when-zero rate.

Roles: `DEV` = DEVELOPMENT, `INTERNAL` = INTERNAL_HOLDOUT, `EXPERT` =
EXPERT_HOLDOUT.

| ID | Title | Kind | Eligible roles | Validation evidence | Needs expert |
|---|---|---|---|---|---|
| `PGX-VAL-001` | Guideline and rule concordance | RATE | INTERNAL/EXPERT | yes | no |
| `PGX-VAL-002` | Coverage correctness | RATE | INTERNAL/EXPERT | yes | no |
| `PGX-VAL-003` | Unsafe false reassurance | COUNT | INTERNAL/EXPERT | yes | no |
| `PGX-VAL-004` | Unsafe false reassurance rate | RATE | INTERNAL/EXPERT | yes | no |
| `PGX-VAL-005` | Evidence traceability | COUNT | INTERNAL/EXPERT | yes | no |
| `PGX-VAL-006` | Evidence traceability rate | RATE | INTERNAL/EXPERT | yes | no |
| `PGX-VAL-007` | Deterministic repeatability | COUNT | DEV/INTERNAL/EXPERT | no | no |
| `PGX-VAL-008` | Deterministic repeatability rate | RATE | DEV/INTERNAL/EXPERT | no | no |
| `PGX-VAL-009` | Holdout pass count | COUNT | INTERNAL/EXPERT | yes | no |
| `PGX-VAL-010` | Holdout pass rate | RATE | INTERNAL/EXPERT | yes | no |
| `PGX-VAL-011` | Expert agreement distribution | DISTRIBUTION | EXPERT | yes | yes |
| `PGX-VAL-012` | Expert Likert dimensions | DISTRIBUTION | EXPERT | yes | yes |
| `PGX-VAL-013` | Unresolved source conflicts | COUNT | DEV/INTERNAL/EXPERT | no | no |
| `PGX-VAL-014` | Failure-path coverage | COUNT | DEV/INTERNAL/EXPERT | no | no |
| `PGX-VAL-015` | Failure-path coverage rate | RATE | DEV/INTERNAL/EXPERT | no | no |

Six metrics are **not** validation evidence: determinism (`007`, `008`),
unresolved conflicts (`013`) and failure-path coverage (`014`, `015`). Those
are software properties, computable over development cases and useful as
regression signals. Marking everything as evidence would be the easy lie;
marking nothing would make the flag useless.

## 3. Numerators and denominators

The exact text of each is in the committed artifact. The four that are easy
to get wrong:

| ID | Numerator | Denominator | The mistake it avoids |
|---|---|---|---|
| `PGX-VAL-001` | observations matching the reference judgment on attention, coverage and rule | observations **that have a supplied reference judgment** | counting unjudged cases as failures |
| `PGX-VAL-005` | findings with a resolvable pinned evidence reference | **emitted findings**, not cases | one untraceable finding hiding behind a traceable sibling in the same case |
| `PGX-VAL-007` | observations whose output hash was identical across every repeat | observations **with at least two repeats** | a single execution counted as proof of repeatability |
| `PGX-VAL-014` | distinct catalogue paths observed at least once | **the whole predeclared catalogue** | a run touching two paths reporting 2/2 |

## 4. Unavailable reason codes

| Code | Meaning |
|---|---|
| `ZERO_DENOMINATOR` | the denominator is zero; there is no rate, and 0 and 100 would both be inventions |
| `NO_ACTIVE_RELEASE` | nothing can be pinned, so no result can name what it measured |
| `NO_HOLDOUT_CASES` | no case is held out from development |
| `NO_REFERENCE_JUDGMENT` | no answer key has been supplied; WP-18 stores none by design |
| `EXPERT_REVIEW_NOT_IMPLEMENTED` | WP-22 owns the blind protocol and has not started |
| `SEPARATION_AUDIT_FAILED` | the partition audit is not clean, so no metric may be computed at all |
| `RESTRICTED_STORAGE_NOT_CONFIGURED` | holdout payloads are unreachable |
| `RELEASE_NOT_PINNED` | the plan does not pin one release with all hashes |
| `RELEASE_HASH_MISMATCH` | an observation names a release that disagrees with the pinned one |
| `CASE_MANIFEST_HASH_MISMATCH` | the case manifest hash disagrees with the plan |
| `INPUT_INCOMPATIBLE` | the supplied input does not satisfy the metric's declared requirements |
| `BENCHMARK_NOT_EXECUTED` | nobody looked |
| `NO_ELIGIBLE_OBSERVATIONS` | no observation belongs to a role this metric accepts |

## 5. The failure-path catalogue

Ten paths, versioned as `pgx-wp21-failure-paths/1` separately from the metric
registry: adding one changes what "complete" means even when no metric
definition changed.

| ID | Title | Meaning |
|---|---|---|
| `FP-001` | Unsupported medication | The medication is not in the pinned release's drug catalogue. |
| `FP-002` | Missing required gene or axis | An axis the rule needs has no phenotype supplied. |
| `FP-003` | Indeterminate phenotype | A phenotype is supplied but is indeterminate for this axis. |
| `FP-004` | Partial coverage | Some but not all required axes resolve. |
| `FP-005` | Insufficient coverage | Coverage is below the manifest's minimum for this medication. |
| `FP-006` | Conflicting sources or rules | Two validated rules or two sources disagree for one axis. |
| `FP-007` | No applicable validated rule | The pinned ruleset holds no VALIDATED rule for this combination. |
| `FP-008` | Invalid or unpinned release | The release is missing, inactive, or its manifest hash disagrees. |
| `FP-009` | Missing evidence reference | A finding would be emitted with no resolvable evidence. |
| `FP-010` | Prohibited input kind or field | The input carries a real-patient, genotype or raw-sequencing field. |

## 6. What none of this establishes

These are definitions. No metric in this registry currently has a value, and
a value would not by itself be clinical validation, scientific validation or
expert review. Those are produced by people under WP-21 operation and WP-22,
and cannot be produced by running code.
