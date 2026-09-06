# H04-dataset-quality-decision - dataset quality decision mechanism and its first decision

**Status: PENDING_REVIEW.** Nothing in this package is approved.

WP-07 already carried the transition an approval causes. What was missing was the decision: no verdict field, so no way to record a rejection; no reviewer role; no binding to the source policy. Wave 2 implemented those and left the working parts alone. Nobody has been named as data owner and there is no legitimate dataset to decide about.

## Who decides

| Field | Value |
| --- | --- |
| Decision owner | a named data owner |
| Cannot be decided by | the quality report, which reports numbers and decides nothing |
| Blocks | dataset publication, release activation |
| Blocked by | a non-legacy dataset, which WP-C05 has not produced |

## The files

| File | What it is |
| --- | --- |
| `decision-context.md` | What has to be decided and why it cannot be decided by code. |
| `evidence-table.csv` | What the repository and the primary documents actually show. Each row cites where it was read. |
| `proposed-decisions.csv` | What the project proposes. Every row is `PENDING_REVIEW`. |
| `unresolved-questions.md` | What is not known, and what would have to happen to know it. |
| `risk-summary.md` | What goes wrong if this is decided wrongly, or not decided. |
| `approval-form.md` | Blank. A reviewer fills it in. |

## How to use this

Read `decision-context.md`, then check `proposed-decisions.csv` against `evidence-table.csv` rather than against the prose - the prose is the project's reading and the evidence is what it read. Then fill in `approval-form.md`. Approving something the evidence table does not support is the failure mode this layout exists to make visible.

