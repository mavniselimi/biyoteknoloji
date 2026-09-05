# WP-21 - Benchmark protocol

| Field | Value |
|---|---|
| Document ID | `DOC-VAL-022` |
| Work package | WP-21 |
| Protocol version | `pgx-wp21-benchmark-protocol/1` |
| Machine-readable | `pgx/validation/benchmark_models.py`, `pgx/validation/benchmark.py` |
| Schema | `schemas/wp21/benchmark-plan.schema.json` |
| Command | `pgx-benchmark run` |

> No benchmark has been executed in this repository. This document describes
> how one would run and what it would refuse; it reports no result.

---

## 1. Order of operations

The order is the safety property, so it is stated before the detail.

```
1. audit the case set          →  not clean?  compute NOTHING and stop
2. resolve exactly one release →  once, held in the plan, never re-read
3. collect observations        →  per role, through the injected port
4. verify every observation    →  one mismatch refuses the WHOLE run
5. compute metrics             →  per role; there is no combining step
```

Step 1 is not "audit the partitions you plan to use". If the audit is dirty
anywhere, every metric downstream is a statement about roles that may not mean
what they say, so `SeparationNotCleanError` is raised and nothing is computed.

Step 5 has no aggregate. An overall figure across development and holdout
would let seven fixtures that shaped the software carry a partition meant to
be independent of it; an aggregate across the two holdout roles would let the
larger carry the smaller.

## 2. What a plan pins

```
protocol_version                    pgx-wp21-benchmark-protocol/1
plan_id
pinned_release.release_public_id
pinned_release.release_manifest_hash        sha256:...
pinned_release.software_version
pinned_release.software_hash                sha256:...
pinned_release.dataset_public_id
pinned_release.dataset_content_hash         sha256:...
pinned_release.ruleset_public_id
pinned_release.ruleset_content_hash         sha256:...
pinned_release.active_pointer_generation    the WP-03 pointer seen at pin time
case_manifest_hashes[<role>]                one per role, never one for the union
declared_metric_ids                         chosen before the run
metric_registry_version + digest
failure_path_catalogue_version
roles
repeat_count
```

Each is required. `BenchmarkPlan` raises `UnpinnedError` on a missing hash, a
role with no case-manifest hash, or an empty metric list - choosing metrics
after seeing the run is how a flattering subset gets picked.

One hash **per partition** rather than one for the union: the partitions are
reported separately, and a combined hash would make a case moving between them
invisible.

## 3. Resolving the release exactly once

`ReleaseResolutionPort.resolve()` is called once, before any case executes,
and the result is frozen into the plan. Nothing downstream consults the port
again.

An activation committing while a benchmark runs therefore changes the *next*
run. The running one holds a `PinnedRelease` that cannot be reached from the
active-release pointer, which is the same discipline `AssessmentService` uses
for a single assessment, applied to a whole benchmark.

## 4. Verification, and why a mismatch is fatal

Every observation echoes back all eight release identities plus the
case-manifest hash for its role. `verify_observation` compares them and raises
`PinMismatchError` on the first disagreement, naming the field, both values
and the case.

The run is refused - not the row. A report that silently excluded a
disagreeing observation would describe a different run than the one it names,
and the exclusion would be invisible in the artifact. If one observation came
from a different release, the honest reading is that the run measured
something other than what it claims, and no subset of it is trustworthy
without knowing why.

## 5. Determinism

Observations are sorted by `(role, case_id)` at serialisation, so input order
cannot change the report hash: two runs executing the same cases in different
orders serialise identically, and a hash comparison tests the science rather
than the scheduler.

`BenchmarkRun.scientific_digest()` covers the plan and the observations and
**excludes timestamps**. Including them would make "did two identical reruns
agree" permanently false.

`repeat_count` of at least two is what makes `PGX-VAL-007` computable. A
single execution reports `repeats_agree = None`, not `True` - one run cannot
demonstrate repeatability, and counting it as agreement would put a case in
the numerator of a metric it never tested.

## 6. Ports

| Port | Responsibility | Present here |
|---|---|---|
| `ReleaseResolutionPort` | resolve and pin one release | no |
| `RestrictedObservationPort` | execute a role's cases, return observations | no |
| `ReferenceJudgmentPort` | supply immutable reference judgments | no (returns empty) |

Holdout payloads live in restricted storage; the observation port is the only
way the benchmark sees them, and it returns observations rather than payload
content, so nothing downstream can leak a case into a public artifact.

Production code never imports `tests.*`. The synthetic release used to prove
the engine works is injected in the test suite. There is no
`--use-test-fixture` production switch.

## 7. Reference judgments

A judgment is a separate immutable record with its own provenance - not a
field on a case. WP-18 stores no expected answer so that authoring a case
cannot double as writing its answer key, and WP-21 preserves that.

`ReferenceJudgment` refuses construction without provenance: an expected
answer nobody signed may not enter a denominator.

None exists here, so concordance, coverage correctness and holdout pass rate
report `NO_REFERENCE_JUDGMENT`. WP-22 will supply them under the blind
protocol.

## 8. Running one

```
pgx-benchmark definitions      # the registry and the catalogue
pgx-benchmark run              # exits 2 here: nothing to pin, nothing to run
pgx-benchmark report           # exits 2 here: no benchmark was executed
pgx-benchmark gate-status      # exits 2 here: BLOCKED
pgx-benchmark artifacts        # regenerate the committed documents
```

| Exit | Meaning |
|---|---|
| `0` | a benchmark produced an eligible result |
| `1` | an invariant, schema or calculation failure |
| `2` | blocked: a precondition outside the command's control is unmet |
| `3` | invalid usage |

`run` currently prints what is missing and writes nothing:

```
active release            False
validation evidence cases 0
reference judgments       0
restricted storage        False
```

Exit `2` is the correct outcome, not a tooling defect. Exit `0` would mean a
release had been validated.

## 9. What a run would still not establish

A completed benchmark with numeric results would be **software measurement
under a named release**. It would not be clinical validation, scientific
validation or expert review, and it would not establish that the system is
safe for any patient. Those require WP-22's blind expert protocol and a
scientific judgement by people who have both the holdout results and the
expert reviews in front of them.
