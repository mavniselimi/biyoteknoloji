# H03-claims-boundary - claims boundary and clinical warning

**Status: PENDING_REVIEW.** Nothing in this package is approved.

The boundary is written and enforced literally by code, at version 0.1.0-draft, and declares itself awaiting human and scientific review. What is approved is the exact wording and the exact lists, because that is what the scanner compares.

## Who decides

| Field | Value |
| --- | --- |
| Decision owner | clinical and legal approver, jointly |
| Cannot be decided by | a maintainer; this is what the platform is permitted to say |
| Blocks | report issuance, the security gate, release activation |
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

