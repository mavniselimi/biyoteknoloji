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
section 12 require an ADR for any change to the claim boundary. This is it.

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

Add `pgx/domain/candidate_claims.py`, a new module holding:

- `ClaimBoundaryAuthority` — `HUMAN_APPROVAL_REQUIRED` (what every boundary in
  `claims.py` means) and `PROJECT_TEAM_PROVISIONAL` (a strictly weaker statement
  this project makes about its own prototype);
- `CandidateClaimBoundary`, a subclass of `ClaimBoundary` whose `is_approved` is
  the constant `False` and whose `permits_execution(mode)` admits only a mode the
  boundary already enables;
- `P0_CANDIDATE_CLAIM_BOUNDARY`: identical to `P0_CLAIM_BOUNDARY` in every
  restriction — same prohibited categories, same permitted input kinds, same two
  modes, same canonical warning — differing only in its authority and status;
- `is_provisional(boundary)`, `permits_execution(boundary, mode)` and
  `execution_basis_of(boundary)`, so a call site holding a plain `ClaimBoundary`
  asks these questions in one place rather than with `getattr`.

`pgx/domain/claims.py`, `P0_CLAIM_BOUNDARY` and `DEFAULT_CLAIM_BOUNDARY` are
byte-for-byte unchanged. The candidate boundary is never the default; a caller
has to name it, so the candidate path is visible at every call site instead of
being inherited by accident.

## Why a new module, and not an edit to `claims.py`

The first version of this change put all of the above **inside** `claims.py`.
That was wrong for a reason that has nothing to do with the design:

`pgx/domain/claims.py` is a frozen WP-01 legacy baseline artifact. Its SHA-256 is
pinned in `data/legacy-baseline/manifest.json` with `mutable_legacy_state: false`,
and `scripts/amend_legacy_manifest.py` refuses to amend a legacy entry at all —
not its hash, not its metadata, not its count. The baseline is evidence of what
WP-00 shipped. Evidence that gets rewritten when it becomes inconvenient is not
evidence, and the amendment tool exists to make that impossible rather than
merely discouraged.

The edit was caught by
`tests/unit/test_manifest_amendment.py::test_every_legacy_artifact_hash_still_matches_disk`,
which is precisely the guard that exists to catch it. The file has been restored
to its baseline content; the whole baseline — 64 legacy artifacts and 22 evidence
artifacts — matches disk again.

## What was explicitly not done

**`ClaimBoundary.is_approved` was not widened, and it was not narrowed either.**
It is frozen, so it still reads exactly as it did at WP-00: a substring test for
"DRAFT" and "AWAITING" over a free-text status.

That property is a real hazard, and it is why the candidate boundary had to be a
distinct *type* rather than a differently-configured instance. The candidate
status is `"PROJECT_TEAM_PROVISIONAL / PENDING EXTERNAL EXPERT REVIEW"`, which
contains neither word — so a candidate boundary built as a plain `ClaimBoundary`
reports itself **approved**. A boundary signed by nobody would have claimed a
human approval. The first version of this work did exactly that before the
authority check was added.

`CandidateClaimBoundary.is_approved` therefore does not consult the status at all.
It returns `False` — not "usually false", not "false unless the status says
otherwise". No status wording, and no later edit to a status string, can move it.
`tests/unit/closure/test_wave03b_capture.py::test_a_provisional_status_cannot_
manufacture_an_approval` demonstrates the hazard on the frozen class and its
closure on the candidate class in the same test, so the reason this type exists
cannot be forgotten.

`permits_execution` cannot enable a mode the boundary does not already enable, so
a provisional boundary can never unlock `PILOT`. Unlocking `PILOT` needs the
signatures, which is the point.

## Consequences

- **Safety.** The prohibited-claim list, permitted input kinds, canonical warning
  and `PILOT` prohibition are untouched. The only new capability is executing
  DEMO and VALIDATION assessments under a boundary that reports itself as
  unapproved and provisional wherever it is displayed.
- **Migration.** None. No existing boundary, field or default changes.
- **A second boundary owner.** `tests/unit/engine/test_wp14_boundaries.py`
  enforced that only `pgx/domain/claims.py` constructs a `ClaimBoundary`. It now
  admits `candidate_claims.py` as well, and pays for the exemption with
  `test_no_boundary_an_owner_ships_is_approved_or_enables_pilot`, which inspects
  every boundary either owner exposes as an object — not as text — and requires
  that none reports itself approved and none enables `PILOT`.
- **Validation.** Results produced under this boundary are `INTERNAL_VALIDATION`
  at best. They are not clinical, independent or expert validation.
- **Reversal.** Deleting `pgx/domain/candidate_claims.py` and its call sites
  returns the system to refusing every assessment. Nothing in `claims.py` would
  need to be undone, because nothing in it was done.

## Approvers

None. This ADR is a project-team provisional record; it is not a human approval
and does not satisfy section 11, which remains unsigned.
