# Data quality contract (WP-07)

What the DQ report asserts, how every number in it is produced, and what the
gate does and does not decide.

`pgx-data-quality/1`.

## 1. Every count is derived

Nothing in `pgx/normalization/quality.py` keeps a running tally that a human
typed. Metrics are computed from the same serialised rows the build writes, and
`recount_from_build_path` recomputes the headline counts a *second* time by
opening the sealed NDJSON files and counting lines and fields.

`pgx-normalize verify` runs both and compares them. A disagreement is itself a
blocking finding (`SUMMARY_DISAGREES_WITH_ARTIFACTS`), because a report that
cannot be reproduced from the artifacts it describes is not evidence of
anything.

The report carries **no generation timestamp**. When it was computed is a fact
about the run; the build manifest beside it already records `built_at`. Per-run
values such as how many identities this run minted are likewise excluded, so
two evaluations of one build produce identical bytes.

## 2. Reconciliation

For each stream the report states `input = accepted + rejected + deferred`, and
`Reconciliation` refuses to be rendered if the identity does not hold. A stream
whose parts do not add up has lost records between two counters, and publishing
the parts anyway would present the loss as a result.

`deferred` means **kept, counted, and waiting for a decision** — never dropped.

| Stream | accepted | rejected | deferred |
| --- | --- | --- | --- |
| `raw_artifacts` | read as evidence | derived, out-of-scope or reference-only, deliberately not read | unclassified by the role map |
| `entity_candidates` | normalised and contributed to an entity | value could not be normalised at all | — |
| `entity_references` | resolved to exactly one entity | could not be normalised | ambiguous, unresolved or broken; now in the queue |
| `source_record_observations` | distinct source records | **always 0** — no observation is discarded | further observations of a record already counted, every one retained inside its duplicate group |

Observed on the real snapshot:

```
raw_artifacts                input 12   = accepted 4    + rejected 8 + deferred 0
entity_candidates            input 16   = accepted 16   + rejected 0 + deferred 0
entity_references            input 29   = accepted 29   + rejected 0 + deferred 0
source_record_observations   input 3466 = accepted 1822 + rejected 0 + deferred 1644
```

The published schema asserts `balances: true` and `shortfall: 0` on every
reconciliation, so an imbalanced report cannot validate.

## 3. The gate fails closed

Every unanswered question blocks. A missing source approval blocks exactly as a
refused one does; an unrecognised artifact blocks; an ambiguity blocks; a
conflicting identity collision blocks. The default answer is "not quality
checked", which is the correct answer for a dataset nobody has reviewed.

There is no override argument, no severity threshold to lower and no allowlist
of codes to ignore. A gate that can be argued down is not a gate.

### Blocking codes

| Code | Raised when |
| --- | --- |
| `SNAPSHOT_QUARANTINED` | the raw snapshot is quarantined |
| `SNAPSHOT_NOT_SEALED` | the snapshot is not final |
| `SNAPSHOT_NOT_ACQUIRED` | it is a `LEGACY_IMPORT`; completeness upstream is unknown |
| `SNAPSHOT_COMPLETENESS_UNKNOWN` | an acquisition-backed snapshot that does not assert completeness. Partial counts read exactly like complete ones. |
| `SOURCE_POLICY_MISSING` | no source-policy approval is on record |
| `SOURCE_POLICY_NOT_APPROVED` | the recorded status is not `APPROVED` |
| `UNRECOGNISED_ARTIFACT` | the snapshot holds a file the role map does not classify |
| `REQUIRED_ARTIFACT_MISSING` | an artifact the role map treats as **evidence** is absent, so the dataset is missing records the source was expected to supply |
| `DERIVATION_CLAIM_BROKEN` | a "derived" file carries identifiers its source lacks |
| `CANDIDATE_NOT_NORMALIZABLE` | a value produced no canonical entity |
| `EXTERNAL_ID_CLAIMED_BY_SEVERAL_ENTITIES` | one accession names two entities |
| `AMBIGUOUS_RESOLUTION` | a value matched more than one entity |
| `UNRESOLVED_REFERENCE` | a value matched nothing at any stage |
| `BROKEN_REFERENCE` | a relationship names an absent entity |
| `INVALID_REFERENCE_INPUT` | a value could not be normalised |
| `CONFLICTING_IDENTITY_COLLISION` | one identity, different payloads |
| `RECORD_WITHOUT_SOURCE_IDENTITY` | a record cannot be deduplicated |
| `RECONCILIATION_BROKEN` | a stream does not balance |
| `SUMMARY_DISAGREES_WITH_ARTIFACTS` | the recorded summary disagrees with a re-count |

### Advisory and informational codes

`SEMANTIC_DUPLICATE_CONTAINER`, `CONTAINER_SYNONYM_UNREVIEWED`,
`ALIAS_AWAITING_REVIEW`, `MALFORMED_EXTERNAL_IDENTIFIER`,
`ENTITY_WITHOUT_EXTERNAL_ID`, `EXPECTED_ARTIFACT_MISSING` (a comparison-only
or reference artifact is absent; it contributes no records, so the canonical
dataset is unaffected and only the legacy comparison is) and
`CANDIDATE_DISPLAY_DISAGREEMENT` (two source
records normalise to one entity but print different preferred names; the first
by locator order is stored and the disagreement is reported, because no name is
judged better than another) are advisory — real findings a reviewer should
see, not reasons the data is unusable. `EXACT_DUPLICATE_OBSERVATION` and
`OUT_OF_SCOPE_DATA_EXCLUDED` are informational.

Codes are stable strings. A code that stops applying is retired rather than
repurposed, because dashboards and tests match on them.

## 4. The gate decides nothing about the lifecycle

A passing gate is a **precondition** for a human quality decision, not the
decision. There is no function in this package that marks a dataset
`QUALITY_CHECKED`, publishes one, or activates a release; the CLI's
`quality-check` command computes and prints the gate and says, in its own
output, that it changed nothing.

Migration `0005` adds the `DATASET_QUALITY_CHECKED` audit action so a real
decision has somewhere to go, and narrows
`ck_dataset_versions_approval_requires_reviewer` so that a dataset reaching
`QUALITY_CHECKED` **must** name an approver and an instant.

### The one transition that exists

`pgx.application.canonical_service.CanonicalDatasetService.record_quality_check`
performs `BUILDING -> QUALITY_CHECKED`, and nothing else. There is no `publish`,
no `activate`, no `retire` and no `rollback` in that module; publication and
release activation belong to WP-03's release registry and to a human.

It refuses unless every one of these holds:

- the build matches its own recorded digests;
- its summary agrees with an independent re-count of its artifacts;
- both documents validate against the published schemas;
- the build describes the dataset being transitioned;
- the quality gate passed;
- the dataset is currently in the state the caller said it expected.

`reviewed_by`, `reviewed_at` and `rationale` are required arguments with no
defaults, so a decision with no author cannot be constructed. The transition
runs inside one unit of work, records the DQ report's path and content hash
alongside the state change, and appends one `DATASET_QUALITY_CHECKED` audit
event. A refusal commits nothing and appends nothing.

The state guard is applied as a condition of the update, so a repeated attempt
is refused rather than silently re-run.

**The CLI cannot reach this function.** `pgx-normalize quality-check` computes
the gate, prints it, and stops; a test asserts the CLI module does not so much
as name the service. WP-07 records no real decision: the mechanism is exercised
only on synthetic datasets, with the shouted synthetic reviewer identity
`TEST_SCIENTIFIC_REVIEWER`, and the real dataset's gate is blocked.

## 5. Naming

Counts of what a snapshot mentions are `source_observed_*`. They are not
validated coverage, not clinical coverage, not supported treatment, not safe
alternatives and not executable pharmacogenetic rules, and the reports say so on
every page where the counts appear.

## 6. Current status of `PGX-DATA-20260830-900`

`BUILDING`. Gate **BLOCKED** on three findings, all correct:

- `SNAPSHOT_QUARANTINED` — the snapshot is a quarantined legacy import.
- `SNAPSHOT_NOT_ACQUIRED` — no WP-04 acquisition run backs it, so completeness
  relative to the upstream source is unknown and is not inferred from the fact
  that every file present was copied.
- `SOURCE_POLICY_MISSING` — no human has approved the ClinPGx source.

Advisory: `SEMANTIC_DUPLICATE_CONTAINER` (1,644),
`CONTAINER_SYNONYM_UNREVIEWED` (29). Informational:
`OUT_OF_SCOPE_DATA_EXCLUDED` (8,182 candidate-edge records counted and
excluded).
