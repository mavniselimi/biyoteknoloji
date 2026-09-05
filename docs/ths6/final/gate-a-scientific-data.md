# Gate A — Scientific Data

**Result: BLOCKED.** 0 of 5 mandatory conditions met. 5 blockers.

`architecture.md` §20 states Gate A's PASS condition as: *immutable dataset,
complete source policy, canonical DQ report, traceable evidence.* That is a
sentence, and a sentence cannot be evaluated, so it is expanded into five
fields read from committed artifacts.

| # | Condition | Read from | Required | Observed |
|---|---|---|---|---|
| A1 | at least one scientific source is approved | `data/rulesets/wp11-real-gate-status.json` → `upstream_state.source_registry_approved` | ≥ 1 | 0 |
| A2 | a canonical dataset is published | same → `upstream_state.canonical_dataset_published` | true | false |
| A3 | the raw snapshot is complete | `data/canonical/PGX-DATA-20260830-900/manifest.json` → `snapshot_complete` | true | false |
| A4 | the raw snapshot is SEALED | same → `snapshot_state` | `SEALED` | `QUARANTINED` |
| A5 | the evidence build is approved for rules | `data/rulesets/wp11-real-gate-status.json` → `upstream_state.evidence_build_approved_for_rules` | true | false |

## A4 deserves a note

`SnapshotState` defines three values: `STAGING`, `SEALED` and `QUARANTINED`,
and its own docstring says there is **no transition out of `SEALED` or
`QUARANTINED`** — a snapshot is not reopened, it is superseded by a new
dataset identifier.

So A4 cannot be satisfied by promoting the current snapshot. It can only be
satisfied by re-ingesting under a new dataset id, and the condition says so in
its own text rather than leaving a reader to discover it. An earlier draft of
this condition named a target state (`VERIFIED`) that the vocabulary does not
have, which would have made the gate unsatisfiable in a way nobody could
have traced.

## Blockers and owners

| Code | Owner |
|---|---|
| `THS6_NO_APPROVED_SOURCE` | scientific source approver |
| `THS6_DATASET_NOT_PUBLISHED` | data owner |
| `THS6_SNAPSHOT_QUARANTINED` (×2) | data owner |
| `THS6_EVIDENCE_BUILD_NOT_APPROVED` | curation lead |

## What exists

Twenty sources are registered, with a review checklist, a source strategy, a
conflict policy and a licensing matrix. A canonical build ran and produced a
manifest, an identity allocation and a data-quality report. An evidence build
ran and produced a manifest.

Every one of those is machinery working correctly over content nobody has
approved. `PGX-DATA-20260830-900` is labelled `BUILDING`, its snapshot is
`QUARANTINED`, and its evidence build carries the labels `QUARANTINED`,
`LEGACY_MIGRATION`, `NOT_CURATED`, `NOT_EXECUTABLE` and
`NOT_PUBLICATION_ELIGIBLE`.
