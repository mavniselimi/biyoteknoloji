# Gate D — Validation

**Result: BLOCKED.** 0 of 9 mandatory conditions met. 9 blockers.

`architecture.md` §20: *independent holdout results, metrics, blind expert
review.*

| # | Condition | Read from | Required | Observed |
|---|---|---|---|---|
| D1 | at least fifty validation cases | `data/validation/wp18-real-gate-status.json` → `real_patient_case_count` | ≥ 50 | 0 |
| D2 | an independent holdout set exists | same → `holdout_case_count` | ≥ 1 | 0 |
| D3 | a metric has a computed value | `data/validation/wp21-real-gate-status.json` → `computed_metric_value_count` | ≥ 1 | 0 |
| D4 | a reference judgment exists | same → `reference_judgment_count` | ≥ 1 | 0 |
| D5 | a benchmark ran against the active release | same → `benchmark_executed_against_active_release` | true | false |
| D6 | the expert protocol has a signatory | `data/expert-review/wp22-real-gate-status.json` → `protocol_signatory_count` | ≥ 1 | 0 |
| D7 | an expert reviewer is named | same → `named_reviewer_count` | ≥ 1 | 0 |
| D8 | an expert review is completed | same → `completed_review_count` | ≥ 1 | null |
| D9 | the expert review gate reports PASS | same → `expert_review_gate_status` | `PASS` | `BLOCKED` |

## D8 is null, not zero

WP-22 records `completed_review_count: null` with the source note *"null
rather than zero: no review store was inspected, so no count was taken."*
This pack preserves that distinction and does not treat null as zero. The
comparator refuses a null outright and says so in the observation column
(*"null (no measurement was taken)"*), rather than silently comparing `None`
against `1`.

## The seven development cases

Seven development cases exist. They shaped the software. WP-18's own contract
excludes them from validation evidence, WP-22 records that assigning one to an
expert would produce *"a review of the material the system was built on, which
is not evidence about anything else"*, and this pack types them
`TEST_ONLY_REHEARSAL` so that no claim can cite them.

The separation audit runs over those seven and passes. That is a check with
nothing to separate them from, and the audit's entry in this inventory says so
as a limitation with the validation owner as its gap owner.

## `real_patient_case_count` is structurally zero

WP-18's note: *"structurally zero: the case model refuses every real-patient,
genotype and raw-sequencing field at any depth, so there is no path by which
one could exist."* Real-patient ingestion is P2 scope and is not implemented.

D1 is therefore not a matter of authoring more cases in the current model. It
requires a validation case architecture that does not yet exist, and that
work is owned by the validation owner rather than by anyone who could ship it
this week.

## What exists

Fifteen metric definitions, ten declared failure paths, a benchmark protocol,
an expert protocol document, an eight-step blind-first review workflow with
append-only records and an audit chain, a payload permit model, four Likert
dimensions, a public summary structure and an empty-state dashboard feed.

The machinery is complete and empty. WP-22's artifact lists six missing
preconditions and notes that five of them are owned by people.
