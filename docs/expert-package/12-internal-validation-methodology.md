# 12. Internal validation methodology and metrics

Artifacts: `data/closure/wave-04-catalogue/`,
`data/closure/wave-04-benchmark/`. Protocol:
`docs/validation/benchmark-protocol.md`,
`docs/validation/metric-definitions.md`.

## The catalogue

67 cases in three partitions, sealed **before** any benchmark ran. The sealing
script refuses to rewrite a sealed catalogue, so an expected answer cannot be
edited after a run disagrees with it.

| Partition | Count | Has expected answers | Purpose |
|---|---|---|---|
| `DEVELOPMENT` | 34 | yes | does the ruleset encode what its author intended |
| `INTERNAL_HOLDOUT` | 21 | yes | refusal and boundary behaviour no rule states |
| `EXPERT_HOLDOUT` | 12 | **no** | reserved, unopened, for you |

A separation audit runs ten checks — role overlap, content duplication within
and across partitions, derivation-family splits, holdout-derived-from-
development, missing holdout provenance, payload hash mismatch, release
compatibility conflict, restricted fields in a public manifest, development
relabelled as holdout. `issue_count: 0`.

## The benchmark

55 cases scored — development plus internal holdout. The twelve reserved cases
were not run.

| Metric | Value |
|---|---|
| attention_agreement | 1.0 |
| coverage_agreement | 1.0 |
| refusal_correctness | 1.0 |
| evidence_traceability | 1.0 |
| deterministic_repeatability | 1.0 |
| system_failure_rate | 0.0 |
| failed_case_count | 0 |
| **unsafe_false_reassurance_count** | **0** |
| expert_reserved_payloads_read | **0** |
| latency p50 / p95 | 5.13 ms / 5.30 ms |

## What each metric actually asserts

- **attention_agreement** — for the 55 scored cases, the attention level the
  release returned equalled the one recorded when the catalogue was sealed.
- **coverage_agreement** — the coverage status matched too: a case expected to
  be refused was refused, and one expected to be answered was answered.
- **refusal_correctness** — the *reason codes* on each refusal matched, not
  merely the fact of refusal. A case refused for the right reason and a case
  refused for the wrong one are different results here.
- **evidence_traceability** — every answered case named a matched rule whose
  provenance resolved to a capture record and a citation. A finding with no
  reachable lineage fails.
- **deterministic_repeatability** — repeated runs produced identical output.
- **unsafe_false_reassurance_count** — the count of cases where a refusal or a
  missing-data condition was presented as an attention level implying safety.
  Zero. This is the metric the project cares about most, and section 13
  explains why zero here is weaker evidence than it looks.
- **expert_reserved_payloads_read** — the benchmark's own access ledger
  recorded zero events against the reserved partition.

## Latency

p50 5.13 ms, p95 5.30 ms, in-process, against a frozen ruleset held in memory.
That is a measurement of a hash lookup and a table match, not of a system
under load. It should not be quoted as a performance characteristic.

## What these numbers are not

They are not accuracy against clinical truth. They are agreement with
expectations that the same process wrote, on cases that the same process
authored, for rules that the same process built. Section 13.
