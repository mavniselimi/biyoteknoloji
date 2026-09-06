# ADR 0001 — A provisional claim boundary for the candidate build

| | |
|---|---|
| Status | ACCEPTED (project-team provisional) |
| Authority | `PROJECT_TEAM_PROVISIONAL` |
| Review state | `PENDING_EXTERNAL_EXPERT_REVIEW` |
| Date | 2026-09-06 |
| Recorded by | pgx-closure-wave03b automated pass (NOT A HUMAN) |
| Supersedes | — |

`architecture.md` section 23 and `docs/architecture/intended-purpose.md`
section 12 require an ADR for any change to `pgx/domain/claims.py`. This is it.

## Context

`P0_CLAIM_BOUNDARY.is_approved` is `False`, and `AssessmentInput.require_permitted`
refuses every assessment with `ASSESSMENT_CLAIM_BOUNDARY_NOT_APPROVED` while it
stays that way. That is correct and deliberate: section 11 of the intended-purpose
document requires four named people to sign, and none has.

The consequence is that the assessment path cannot execute at all. Wave 3 built
source-grounded candidate rules but could not run them through the application,
so it ran them through a parallel evaluator under `pgx/closure` — a second
assessment engine, which is worse than the problem it solved.

The current execution policy says missing *external expert* approval must not
block construction, integration, internal validation or browser demonstration of
the candidate prototype. It does not say the human approval record may be forged.

## Decision

Add `ClaimBoundaryAuthority` with two members, defaulting to the pre-existing
meaning, and a `permits_execution(mode)` predicate that admits two distinct
bases:

- **approved** — the section 11 record is signed. Unchanged, and still false.
- **provisional** — a project team recorded a candidate decision, and the
  requested mode is one P0 already enables.

Add `P0_CANDIDATE_CLAIM_BOUNDARY`: identical to `P0_CLAIM_BOUNDARY` in every
restriction — same prohibited categories, same permitted input kinds, same two
modes, same canonical warning — differing only in its authority and status.

`P0_CLAIM_BOUNDARY` and `DEFAULT_CLAIM_BOUNDARY` are unchanged. The candidate
boundary is never the default; a caller has to name it, so the candidate path is
visible at every call site instead of being inherited by accident.

## What was explicitly not done

**`is_approved` was not widened.** It was *narrowed*: a boundary whose authority
is provisional now returns `False` regardless of its status text.

That narrowing was not a precaution. The first version of this change defined the
candidate status as `"PROJECT_TEAM_PROVISIONAL / PENDING EXTERNAL EXPERT REVIEW"`,
and `is_approved` returned **`True`** for it — because the property was a
substring test for "DRAFT" and "AWAITING" over free text, and that string contains
neither. A boundary that had been signed by nobody reported itself as approved.
The authority check now runs first, so the wording of a status can no longer
manufacture an approval.

`permits_execution` cannot enable a mode the boundary does not already enable, so
a provisional boundary can never unlock `PILOT`. Unlocking `PILOT` needs the
signatures, which is the point.

## Consequences

- **Safety.** The prohibited-claim list, permitted input kinds, canonical warning
  and `PILOT` prohibition are untouched. The only new capability is executing
  DEMO and VALIDATION assessments under a boundary that reports itself as
  unapproved and provisional wherever it is displayed.
- **Migration.** None. The field defaults to the old meaning.
- **Validation.** Results produced under this boundary are `INTERNAL_VALIDATION`
  at best. They are not clinical, independent or expert validation.
- **Reversal.** Deleting `P0_CANDIDATE_CLAIM_BOUNDARY` and its call sites returns
  the system to refusing every assessment.

## Approvers

None. This ADR is a project-team provisional record; it is not a human approval
and does not satisfy section 11, which remains unsigned.
