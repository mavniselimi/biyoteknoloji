# H01-source-policy - scientific source policy

**Status: PENDING_REVIEW.** Nothing in this package is approved.

Twenty registered sources, all `PENDING_REVIEW`, every reuse dimension `UNKNOWN`. Eight were researched against primary documents this wave; twelve are proposed for deferral because the first release does not need them. Four carry conflicts that a maintainer must not resolve.

## Who decides

| Field | Value |
| --- | --- |
| Decision owner | source policy approver, with legal counsel on the conflicting terms |
| Cannot be decided by | a maintainer; these are readings of licences and jurisdictional judgements |
| Blocks | all acquisition, curated interpretation, rule creation, release activation |
| Blocked by | nothing; this can be decided now |

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

