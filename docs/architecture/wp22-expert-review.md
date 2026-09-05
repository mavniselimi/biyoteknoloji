# WP-22 - Blind Expert Validation Protocol and Review Module

| Field | Value |
|---|---|
| Document ID | `DOC-ARCH-022` |
| Work package | WP-22 - Blind Expert Validation Protocol and Review Module |
| Status | **software IMPLEMENTED; protocol DRAFT; expert review gate BLOCKED** |
| Machine-readable | `pgx/expert_review/`, `pgx/infrastructure/db/expert_reviews.py` |
| Artifacts | `data/expert-review/wp22-*.json` |
| Schemas | `schemas/wp22/` |
| Migration | `migrations/versions/0010_wp22_expert_reviews.py` (not executed) |
| CLI | `pgx-expert-review` |
| Architecture source | `architecture.md` sections 12.2, 12.4, 16, 17 |
| Companion documents | `docs/validation/expert-protocol.md`, `docs/validation/expert-review-data-contract.md` |

> **This document describes machinery, not findings.** WP-22 builds the system
> under which an expert could review a case blind. No expert has done so. The
> protocol is a draft awaiting human and scientific review, there are zero
> expert-holdout cases, zero named reviewers and zero completed reviews. No
> clinical or scientific validation has been performed or is implied.

---

## 1. Two outcomes, and only one of them is in this repository

WP-22 has two separately reportable outcomes, and conflating them is the
failure this whole work package is arranged to prevent.

1. **The software and the protocol machinery are implemented.** That is a fact
   about files, measured by importing modules, walking the tree and running a
   test suite. It is true.
2. **Real, representative expert reviews have been completed.** That is a fact
   about people. It is false, and nothing in this repository can make it true.

Six preconditions for the second are missing, and five of them are owned by
people rather than by code: an approved protocol, at least one expert-holdout
case, at least one named reviewer, an active release, configured restricted
storage, and production authentication. A green test suite satisfies none of
them.

The gate document reports both answers in separate fields and lets them
disagree, which they currently do: `implementation_status: IMPLEMENTED`,
`expert_review_gate_status: BLOCKED`.

---

## 2. What blinding actually has to mean here

A blind review protocol that is enforced by discipline is not enforced. The
reviewer is looking at a web page; if the system's answer is anywhere in the
bytes that page is built from, the protocol has failed regardless of what the
template chose to render. A hidden input is disclosure. A field in a JSON
response that the client happens not to display is disclosure. A `display:
none` block is disclosure.

So blinding here is **structural**, in three layers, and each layer is
independently sufficient:

- **The view has no field.** `ReviewView` before a reveal is an object that
  physically lacks the result attributes. A dict would have let a caller write
  `view["attention_level"]` and a template read it; this cannot hold one until
  `with_result()` has been called, and that is called only after a reveal
  record exists.
- **The page model refuses the combination.** `ExpertReviewPageModel.__post_init__`
  raises if `blinded` is true and `result` is not `None`. The one defect this
  module exists to prevent is unconstructable, not merely unrendered.
- **The port is not consulted.** The system result is fetched from
  `RevealedResultPort` inside the reveal transition and nowhere else. The test
  fixture counts calls, so "the result was never requested" is asserted rather
  than assumed - a stronger statement than "the result was not shown".

The API response shape follows the same rule: `ExpertReviewStateResponse` has
no result field at all. The revealed result arrives as a separate response
model returned only by the reveal and complete operations.

---

## 3. Ordering as referential integrity, not as rules

The protocol's order is: record an expectation, then reveal, then complete.
A rule that checked this would be a rule that could be skipped - by a new
caller, a repair, a migration script, a well-meaning admin endpoint.

So the order is expressed as foreign keys instead:

| Record | Names | Consequence |
|---|---|---|
| reveal | an expectation revision id | there is no id to supply before one is recorded |
| completion | a reveal id | there is no id to supply before a reveal exists |
| correction | a target hash | it names what it amends; the target is never modified |

A reveal before any expectation is not refused. It is **unexpressible**: the
caller has no identifier to put in the required column. The service's own
state-machine check is the second line of defence, and the SQL triggers in
migration `0010` are the third.

The transition map itself is small enough to publish, and is published, in
`data/expert-review/wp22-review-workflow.json`:

```
ASSIGNED             -> EXPECTATION_RECORDED, INVALIDATED
EXPECTATION_RECORDED -> RESULT_REVEALED, INVALIDATED
RESULT_REVEALED      -> COMPLETED, INVALIDATED
COMPLETED            -> (terminal)
INVALIDATED          -> (terminal)
```

Terminal states are checked **first** in every operation. A completed review
asked to reveal again reports `ALREADY_COMPLETED`, not
`RESULT_ALREADY_REVEALED`: both statements are true, and only the first sends
the caller to the right remedy.

---

## 4. Approval is a structure, not a boolean

`ExpertProtocol.is_approved` is a computed property over a list of
signatories. It cannot be assigned. Approval requires four named people -
`PRODUCT_TECHNICAL_OWNER`, `SCIENTIFIC_ADVISOR`, `RISK_MANAGEMENT_OWNER`,
`INDEPENDENT_REVIEWER` - each with a name, an affiliation, a decision date, a
record reference, and the digest of the exact protocol text they signed.

Two consequences follow, and both are deliberate:

- **A signature is bound to bytes.** Edit `docs/validation/expert-protocol.md`
  and every existing signature stops matching, so the protocol reverts to
  unapproved. That is the correct outcome: a protocol amended after approval
  has not been approved.
- **No code path can supply signatories.** `load_protocol` takes them as an
  argument that defaults to empty and reads none from disk. A signature list
  parsed out of a file anybody could edit is not an approval record - it would
  put the approval of a clinical protocol one text editor away.

The TEST-ONLY approved protocol that lets the workflow tests exercise the
positive path is constructed inside `tests/fixtures/wp22/blind_review.py` and
injected. There is no production flag that substitutes it, and the CLI has no
`--approve` or `--use-test-protocol` option.

`require_approved()` is the **first** call in every governed operation, before
any record, permit, audit event or receipt can be produced. An unapproved
protocol cannot leave a partial trace.

---

## 5. One refusal for three conditions

Three conditions return `EXPERT_REVIEW_NOT_ASSIGNED`, HTTP 404, with empty
details:

- the case does not exist;
- the case exists but is not an expert-holdout case;
- the case is an expert-holdout case assigned to somebody else.

Distinguishing them would hand any reviewer an enumeration oracle for the
holdout set - the one set whose membership must not leak, because a curator
who knows which cases are holdout can shape the software around them. The web
page renders one controlled unavailable state for all three, and the rendered
bytes are identical apart from the case identifier the requester supplied.

---

## 6. Permits are values, not tokens

Reading an expert-holdout payload requires a `PayloadPermit`. A permit is not
a bearer credential: it is a value binding an assignment id, a review id, a
case id, an actor, a role, a workflow stage, the protocol hash and the release
and case manifest hashes. `permit_allows()` compares every field with
`hmac.compare_digest`.

WP-18's blanket refusal of expert-holdout payloads is unchanged. WP-22 adds
exactly one narrow path through it: `decide_access` widens only when the
context kind is `EXPERT_REVIEW` **and** a matching permit is presented. A rule
author holding a valid permit is still refused, because the context is wrong;
a reviewer presenting another reviewer's permit is refused, because the actor
is wrong; a permit issued at `ASSIGNED` does not authorise a read at
`COMPLETED`, because the stage is wrong.

Permits are refused at issue time for terminal states. A completed review has
nothing left to read.

---

## 7. Immutability, and what the audit chain is for

No record in this module is updated or deleted. The in-memory store used by
the tests has **no update method and no delete method** - not private ones,
none - because a test cannot demonstrate immutability against a store that
would have allowed a mutation if asked. It can only demonstrate that nobody
asked, which is a much weaker statement than the one the SQL layer makes.

At the database layer, migration `0010` installs
`pgx_expert_review_append_only()` on six tables (UPDATE and DELETE both raise)
and `pgx_expert_review_forward_only()` on the assignment table, which permits
only the transitions the vocabulary permits. `downgrade()` refuses to run
while any assignment exists: dropping the tables would destroy review records,
and a migration that quietly did so would be the most damaging thing in this
repository.

Amendment is expressed as an appended `Correction` naming a `target_hash`. The
corrected record is never touched. A correction appended **after** a reveal
carries `after_reveal: true`, and WP-21 consumes the expectation revision that
the *reveal* pinned - so a post-reveal amendment, however sincere, cannot
retroactively become the thing the reviewer predicted.

Every operation appends one hash-linked audit event inside the same unit of
work as the record it describes. If the audit append fails, the whole
operation is rolled back and `AuditChainError` is raised. A record without its
event would be a record whose provenance is unknown, which is worse than no
record.

`actor_authenticated` is `false` on every event and the schema pins it
`const: false`. There is no authentication in this system to have
authenticated anybody, and an event claiming otherwise would be claiming a
person.

---

## 8. The authentication boundary

WP-22 **uses**: the existing `Principal`, `Role.EXPERT_REVIEWER`,
`PrincipalResolver`, the static development principal, and the WP-18 access
policy machinery.

WP-22 **does not implement**: passwords, users, session cookies, Argon2,
login, logout, signup, password reset, SSO, JWT, production CSRF,
authentication tables, or any RBAC redesign. Those are WP-23's.

The consequence is visible on the page and is stated there: every form control
renders disabled, because a control that cannot submit is worse than none - a
reviewer would fill it in and believe it had been recorded. The web layer
verifies CSRF *first* in every POST handler, before anything is read or
written, so these routes cannot become a CSRF-exempt habit on the day WP-23
gives the verifier something to do.

WP-18's access ledger actor is **not** marked authenticated by this work
package.

---

## 9. What WP-21 may consume, and what it may not

`pgx/expert_review/ports.py` is the only surface WP-21 sees. It exposes
`CompletedReview` objects through `eligible_completed_reviews()`, which:

- accepts only reviews in state `COMPLETED`;
- refuses a review whose completion does not pin the expectation the reveal
  pinned;
- filters by case role, so a development case can never enter an expert
  denominator;
- refuses - rather than skips - a pin mismatch, because a review conducted
  under a different release than the metric claims is a contradiction, not a
  gap.

WP-21's metric modules import none of `pgx.expert_review.models`, `.service`
or `.audit`; a test asserts the import direction by AST. So a metric cannot
read a reviewer's note, their corrections or their audit chain. It sees a
decision and a set of ratings, and nothing else.

Two metrics changed shape at WP-22. `PGX-VAL-011` (expert agreement) now
computes a real AGREE/PARTIAL/DISAGREE distribution when decisions exist, over
a denominator of completed decisions matching the observations.
`PGX-VAL-012` (Likert) computes over a denominator of **completed ratings, not
completed reviews** - because ratings are optional, and declining to rate must
not be counted as a low score. Both report `NO_COMPLETED_EXPERT_REVIEWS` in
this repository, which is a renaming of WP-21's
`EXPERT_REVIEW_NOT_IMPLEMENTED`: the module is implemented now, and what is
still missing is a person.

---

## 10. No language model touches a review

No module in `pgx/expert_review/`, `apps/api/routers/expert_review.py` or the
web layer imports a model client, and a test asserts it by AST import
inspection plus a name check for completion-style APIs. A reviewer's note is
stored as typed, is never summarised, scored, rewritten or embedded, and never
appears in the public aggregate. It leaves the review system only as the
reviewer wrote it, to a human auditor.

This is not a style preference. An LLM that rephrased an expert's disagreement
would be manufacturing the expert opinion this work package exists to record
faithfully.

---

## 11. The public aggregate is null, not zero

`data/expert-review/wp22-public-summary.json` reports
`completed_review_count: 0` and `agreement_distribution: null`,
`likert_summaries: null`.

Zero completed reviews does not produce a 0% agreement rate. It produces no
rate. The published schema enforces this with an `if/then`: a document whose
completed count is `0` must carry null summaries, so the misleading version
cannot be written even by a later caller who wanted to. The empty case is
built by a separate function that never calls an aggregation, for the same
reason WP-21 separates `build_real_report` from `compute` - "we summarised and
everybody disagreed" and "nobody reviewed anything" must not be one code path.

Nullable counts elsewhere follow the same discipline: `assigned_review_count`
and `completed_review_count` in the gate status are `null` when no review
store was inspected and `0` when an inspected store held none. A reader must
be able to tell "we did not look" from "we looked and found none".

---

## 12. Current state, in one table

| Question | Answer | Where it is measured |
|---|---|---|
| Is the review module implemented? | yes | `expert_review_module_markers()` |
| Is the protocol documented? | yes | `protocol_document_digest()` |
| Is the protocol approved? | **no** - DRAFT | `ExpertProtocol.is_approved` |
| How many expert-holdout cases exist? | 0 | WP-18 separation audit |
| How many reviewers are named? | 0 | no review store inspected |
| How many reviews were completed? | `null` - none inspected | injected store |
| Is there an active release? | no | no resolver wired |
| Is restricted storage configured? | no | `PGX_VALIDATION_RESTRICTED_ROOT` |
| Is there production authentication? | no | WP-23 |
| Has an expert reviewed anything? | **no** | six missing preconditions |
| Has clinical validation happened? | **no** | not producible by software |
| May a release proceed? | **no** | gate BLOCKED |

---

## 13. What would have to happen next

Not code. In order:

1. Four named people review `docs/validation/expert-protocol.md` and sign its
   exact digest, with records an auditor can follow.
2. Scientific curators author expert-holdout cases. These cannot be generated,
   derived from development cases, or synthesised.
3. A release is registered and activated (WP-03), so a review can pin what it
   judged.
4. Restricted storage is configured (deployment).
5. WP-23 supplies authentication, so an actor string identifies a person.
6. Named experts accept assignments, declare conflicts of interest, and
   conduct reviews.

Only after all six does `completed_review_count` become a number rather than
`null`, and only then does `expert_review_gate_status` have any path to
`PASS`.
