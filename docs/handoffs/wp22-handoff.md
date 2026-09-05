# WP-22 → WP-23 Handoff

| Field | Value |
|---|---|
| Document ID | `DOC-HAND-022` |
| From | WP-22 - Blind Expert Validation Protocol and Review Module |
| To | WP-23 - Authentication, Authorisation and Audit |
| Status | **WP-22 software COMPLETE; protocol DRAFT; expert review gate BLOCKED** |

---

## 1. What WP-22 leaves behind

A complete blind review system with **no way to identify the person using
it**. That single gap is WP-23's, and it is the reason every form control in
the reviewer's page renders disabled.

Concretely, WP-22 built and left in place:

- a protocol manifest whose approval is a list of four named signatories, not
  a boolean;
- a five-state machine whose ordering is enforced by referential integrity;
- structural blinding in three independent layers;
- seven append-only record types, hash-linked, with no update or delete path
  at any layer;
- payload permits that bind assignment, case, actor, stage and release;
- 6 API operations, an 8-step web workflow, 11 schemas, 4 artifacts, a CLI;
- 177 tests, 2 explained skips.

And it left these facts, unchanged and unchangeable by software:
`expert_review_performed: false`, `clinical_validation_performed: false`,
`release_may_proceed: false`.

---

## 2. What WP-23 must supply, precisely

WP-22 deliberately did **not** implement, and WP-23 owns:

| Needed | Where WP-22 stubs it |
|---|---|
| password storage, Argon2 or equivalent | nowhere - no user table exists |
| user records | nowhere |
| login, logout, signup, password reset | `apps/web/templates/login.html` is an honest shell |
| session cookies | `WebProvider` has no session |
| production CSRF verification | `provider.csrf.issue()` raises `CsrfError` in every deployment; the web handlers already call `verify()` **first** |
| SSO, JWT | nowhere |
| `PrincipalResolver` backed by real credentials | the static development principal is what exists |
| marking an actor as authenticated | `ReviewAuditEvent` **refuses** `actor_authenticated=True` today |

### The three integration points, named

1. **`ReviewAuditEvent.actor_authenticated`.** It is `False` on every event and
   the schema pins it `const: false`. WP-23 must change the schema in the open
   when authentication exists. Do not flip the field without changing the
   schema: the pin is the thing that makes the change visible in review.

2. **`WebProvider.csrf`.** Supply a verifier whose `issue()` returns a token.
   The moment it does, `_expert_page()` sets `forms_enabled=True` for a live
   assignment and the workflow becomes usable. No other web change is needed;
   the handlers, routes, labels and template are already written for the
   enabled case and are exercised by `tests/unit/web/test_expert_review_flow.py`.

3. **`build_wp22_gate_status(principal_resolver=...)`.** The gate asks the
   resolver for an `authenticates` attribute and treats a resolver that does
   not answer as not authenticating - the failure direction that under-claims.
   Supply a resolver that answers truthfully and the
   `EXPERT_REVIEW_NO_PRODUCTION_AUTHENTICATION` blocker clears. It is one of
   six, and clearing it alone changes nothing about the gate.

---

## 3. What WP-23 must not do

- **Do not mark WP-18's access-ledger actor as authenticated.** WP-22 did not,
  and the ledger's meaning depends on it: the actor recorded there is a
  configured principal, not a person, until real authentication exists.
- **Do not add an `approve` path to the protocol.** `load_protocol` reads no
  signatories from disk, and that is not an oversight. If WP-23 introduces a
  credential system, the temptation to let an authenticated admin "approve the
  protocol" will be immediate. Approval is four named people signing a
  document digest with auditable records, not a privileged button.
- **Do not make the TEST-ONLY protocol reachable from production.** The
  approved fixture lives in `tests/fixtures/wp22/blind_review.py`. There is no
  flag, no environment variable and no CLI option that substitutes it, and
  none should be added.
- **Do not give any role a path around the reveal.** No admin, support or
  superuser role may read an expert-holdout payload outside an
  `EXPERT_REVIEW` context with a matching permit, and none may read a system
  result on behalf of a reviewer who has not locked an expectation.
- **Do not let a role redesign collapse `EXPERT_REVIEWER`.** The service
  requires an exact role match, not a permission check that a broader role
  could satisfy. A "reviewer or admin" check would let the people who built
  the software review it.

---

## 4. What the other work packages are still waiting for

WP-22 is not the bottleneck for any of these. Each is owned by people.

| Waiting on | Owner | Blocks |
|---|---|---|
| protocol approval by four named signatories | human and scientific reviewers | every governed operation |
| expert-holdout cases (cannot be generated) | scientific curators | assignments, WP-21's expert metrics |
| an active release | WP-03 operation | every pin in every record |
| restricted storage configuration | deployment | reading any holdout payload |
| named reviewers with declared conflicts of interest | whoever recruits them | assignments |
| claim boundary approval | human and scientific reviewers | presenting any result as a claim |

---

## 5. Operational notes for whoever runs this next

- `pgx-expert-review gate-status` exits **2**. That is correct. Exit 0 would
  mean an expert had completed a review.
- `pgx-expert-review protocol` exits **2** until the protocol is approved.
- `pgx-expert-review summary` exits **2** while the completed count is zero.
- `pgx-expert-review workflow` exits **0**: the workflow is defined, which is
  a statement about a definition and not about a review.
- `pgx-expert-review artifacts` regenerates the three deterministic documents.
  The gate status is written by its own subcommand with `--write`, because it
  reads the environment and would otherwise break WP-19's byte comparison.
- Migration `0010` has **not** been executed. Its `downgrade()` refuses while
  any assignment exists; do not force it.
- Two tests in `test_persistence.py` skip without PostgreSQL, with named
  reasons. If a database appears, they run - do not remove the skip policy to
  make the suite look cleaner.

---

## 6. The sentence to carry forward

WP-22 built the machinery under which an expert could review a case blind.
No expert has. A green suite in this work package means the software records a
review correctly; it does not mean a clinician looked at anything, and no
document produced by this repository may be presented as though it did.
