# H02-curation-protocol - curation protocol and scientific scope

> **Historical checkpoint notice (2026-09-06):** This package was created under the original intermediate-human-gate policy. Its evidence and any genuine human response remain valid audit inputs, but an unsigned form no longer blocks construction of the candidate prototype. Open questions must be resolved in traceable `SOURCE_GROUNDED_INTERNAL_DECISION` or `PROJECT_TEAM_PROVISIONAL` records and remain `PENDING_EXTERNAL_EXPERT_REVIEW`. See `../../current-execution-policy.md`.

**Status: PENDING_REVIEW.** Nothing in this package is approved.

The protocol declares itself draft and its `approval` field is null. Beyond approving it, five places were found where the primary sources do not fit the shape the project has described its scope in, and the protocol is silent on all five.

## Who decides

| Field | Value |
| --- | --- |
| Decision owner | curation protocol approver and clinical pharmacogenomics reviewer |
| Cannot be decided by | a maintainer; the protocol says explicitly that owning it is not approving the science it governs |
| Blocks | every curated interpretation, rule creation, validation |
| Blocked by | H01-source-policy, for anything to curate from |

## The files

| File | What it is |
| --- | --- |
| `decision-context.md` | What has to be decided and why it cannot be decided by code. |
| `evidence-table.csv` | What the repository and the primary documents actually show. Each row cites where it was read. |
| `proposed-decisions.csv` | What the project proposes. Every row is `PENDING_REVIEW`. |
| `unresolved-questions.md` | What is not known, and what would have to happen to know it. |
| `risk-summary.md` | What goes wrong if this is decided wrongly, or not decided. |
| `approval-form.md` | Blank. A reviewer fills it in. |
| `clinical-review-table.csv` | Every decision in seven parts: what the source says, what this repository assumes, what the owner directed, what is proposed, what goes wrong, what is unknown, and what you are being asked to decide. |

## How to use this

Read `decision-context.md`, then check `proposed-decisions.csv` against `evidence-table.csv` rather than against the prose - the prose is the project's reading and the evidence is what it read. Then fill in `approval-form.md`. Approving something the evidence table does not support is the failure mode this layout exists to make visible.
