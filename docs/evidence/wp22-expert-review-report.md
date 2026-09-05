# WP-22 - Expert Review Evidence Report

| Field | Value |
|---|---|
| Document ID | `DOC-EVD-022` |
| Work package | WP-22 - Blind Expert Validation Protocol and Review Module |
| Status | **software COMPLETE; protocol DRAFT; expert review gate BLOCKED** |
| Machine-readable | `data/expert-review/wp22-real-gate-status.json` |
| Companion documents | `docs/architecture/wp22-expert-review.md`, `docs/validation/expert-protocol.md`, `docs/validation/expert-review-data-contract.md` |

> **This report is evidence about software.** It records that a blind review
> system was built and that its tests pass. It is **not** evidence that any
> expert reviewed anything, that any release was validated, or that this
> system is safe for any patient. Those statements are false, and the sections
> below say so explicitly rather than leaving them to be inferred.

---

## 1. The two outcomes, reported separately

| Outcome | State | How it is measured |
|---|---|---|
| 1. Software and protocol machinery implemented | **COMPLETE** | ten module markers present; 177 tests pass |
| 2. Real representative expert reviews completed | **NOT DONE** | six missing preconditions, five owned by people |

Outcome 2 is not partially done, not in progress, and not blocked on code. It
is zero. Nothing in this repository can advance it, and this report does not
present outcome 1 as partial credit toward it.

---

## 2. What was built

| Component | Location | Size |
|---|---|---|
| Vocabulary: 5 states, 3 decisions, 8 rationale codes, 6 correction kinds, 6 invalidation reasons, 8 audit actions, 4 Likert dimensions, 18 refusal codes | `pgx/expert_review/vocabulary.py` | 1 module |
| Protocol manifest and approval contract | `pgx/expert_review/protocol.py` | 1 module |
| Records: assignment, expectation, reveal, completion, rating, correction | `pgx/expert_review/models.py` | 1 module |
| Payload permits | `pgx/expert_review/permits.py` | 1 module |
| Hash-linked audit chain | `pgx/expert_review/audit.py` | 1 module |
| Service, store port, result port, view | `pgx/expert_review/service.py` | 1 module |
| WP-21 consumption ports | `pgx/expert_review/ports.py` | 1 module |
| Gate status | `pgx/expert_review/gate_status.py` | 1 module |
| Artifacts | `pgx/expert_review/artifacts.py` | 1 module |
| Errors | `pgx/expert_review/errors.py` | 1 module |
| Persistence: 7 tables, repository | `pgx/infrastructure/db/expert_reviews.py` | 1 module |
| Migration `0010`: 7 tables, 2 trigger functions, refusing downgrade | `migrations/versions/0010_wp22_expert_reviews.py` | not executed |
| API: 6 operations, 16 error codes, request and response models | `apps/api/routers/expert_review.py`, `contracts/spec.py`, `routes.py`, `errors.py` | 6 of 14 routes |
| Web: 8-step state-aware workflow, 3 POST routes, ~30 labels | `apps/web/` | 1 template, 4 modules |
| CLI `pgx-expert-review`: 5 subcommands | `pgx/application/expert_review_cli.py` | exit codes 0/1/2/3 |
| Schemas | `schemas/wp22/` | 11 |
| Artifacts | `data/expert-review/` | 4 |
| Documents | `docs/` | 4 |

---

## 3. Test evidence

| Module | Tests | What it asserts |
|---|---|---|
| `tests/unit/expert_review/test_state_machine.py` | 24 | every permitted and refused transition; terminal states checked first |
| `tests/unit/expert_review/test_authorisation.py` | 24 | exact role match; three refusals indistinguishable; unapproved protocol refuses first |
| `tests/unit/expert_review/test_blinding.py` | 15 | no result field pre-reveal; the result port is not consulted |
| `tests/unit/expert_review/test_immutability_and_audit.py` | 33 | no update or delete path; chain links; rollback on audit failure |
| `tests/unit/expert_review/test_payload_access.py` | 15 | permits bind actor, case, stage; WP-18's blanket refusal intact |
| `tests/unit/expert_review/test_metric_supply.py` | 23 | eligibility rules; pin mismatch refuses rather than skips |
| `tests/unit/expert_review/test_persistence.py` | 35 (2 skipped) | table shapes, constraints, trigger DDL; 2 need PostgreSQL |
| `tests/unit/web/test_expert_review_flow.py` | 8 | the rendered 8-step flow; no result token pre-reveal |
| **Total** | **177** | 2 explained skips, 0 unexplained |

Profile `pgx-verify run --profile expert-review`: **PASS**, 177 executed, 175
passed, 0 failed, 0 errored, 2 skipped (0 unexplained).

Three assertions are worth naming because they are the ones that would catch a
real regression rather than a typo:

- **The result port's call count is zero before a reveal.** "The result was
  never requested" is a stronger statement than "the result was not shown",
  and only the first survives a template rewrite.
- **The in-memory store has no update and no delete method.** A test cannot
  demonstrate immutability against a store that would have allowed a mutation
  if asked; it can only demonstrate that nobody asked.
- **Six leak tokens are absent from the serialized HTML of every pre-reveal
  screen**, including the rendered table cell and the output hash. The flow
  deliberately uses a system result that *disagrees* with the reviewer's
  expectation, because a demonstration in which the reviewer is always right
  never shows the screen that matters.

---

## 4. What is deliberately absent

| Absent | Why |
|---|---|
| any reviewer name | none exists; the only place a name could appear is the protocol signatory list, which is empty |
| any expert opinion | none was given |
| any protocol approval | four required signatory roles, zero signed |
| any completed review | zero |
| any agreement percentage | zero completed reviews produce no rate |
| any Likert average | ratings are optional and no rating exists |
| any active release | no resolver wired |
| any executed migration | no PostgreSQL in this environment |
| any authentication | WP-23 owns it |
| any language model | no module imports a model client; asserted by AST |
| a `--approve` or `--use-test-protocol` flag | approval would be one typo away |

---

## 5. Integrations, and what each one now reports

| Work package | Change | Still false |
|---|---|---|
| WP-18 | `expert_review_implemented: true`; blocker renamed `VALIDATION_EXPERT_REVIEW_NOT_IMPLEMENTED` → `VALIDATION_NO_COMPLETED_EXPERT_REVIEWS`; marker paths corrected | `expert_review_performed: false`; `expert_reviewed_case_count: null` |
| WP-19 | `VER-REQ-023` added; 8 category rules; `expert-review` profile; marker paths corrected | verification is software verification, not validation |
| WP-20 | marker paths corrected; artifacts regenerated | `expert_review_performed: false`; gate BLOCKED |
| WP-21 | `EXPERT_REVIEW_NOT_IMPLEMENTED` → `NO_COMPLETED_EXPERT_REVIEWS`; `PGX-VAL-011` and `PGX-VAL-012` now compute from decisions when they exist; `expert_review_module_implemented: true` | `completed_expert_review_count: null`; every metric `NOT_EXECUTED` |
| WP-17 | `WEB_EXPERT_REVIEW_NOT_IMPLEMENTED` → `WEB_EXPERT_REVIEW_FORMS_DISABLED` | forms cannot submit; no reviewer can be identified |
| WP-16 | 3 stub routes answering 501 → 6 real operations; the 501 status is gone from the contract | no route produces a review without a reviewer |

Eleven tests across five suites asserted "WP-22 does not exist" in one form or
another. None was deleted. Each was converted to the property it was actually
defending, with a docstring recording the move - usually *software existing
reports no human act*, which is the durable version of the claim and does not
expire the way "the next work package has not begun" does.

---

## 6. Gate status, verbatim from the artifact

```
work package        WP-22
implementation      IMPLEMENTED
expert review gate  BLOCKED
module implemented  True
protocol documented True
protocol approved   False
protocol status     DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW
named reviewers     0
assigned reviews    null (no review store was inspected)
completed reviews   null (no review store was inspected)
expert holdout      0
active release      False
restricted storage  False
production auth     False
expert review done  False
clinical validation False
release may proceed False
```

Eight blockers, each with a named owner:

| Code | Owner |
|---|---|
| `EXPERT_REVIEW_PROTOCOL_NOT_APPROVED` | named human and scientific reviewers |
| `EXPERT_REVIEW_NO_EXPERT_HOLDOUT_CASES` | scientific curators; a holdout case cannot be generated |
| `EXPERT_REVIEW_NO_NAMED_REVIEWERS` | whoever recruits reviewers under the approved protocol |
| `EXPERT_REVIEW_NO_ACTIVE_RELEASE` | WP-03 operation |
| `EXPERT_REVIEW_RESTRICTED_STORAGE_NOT_CONFIGURED` | deployment |
| `EXPERT_REVIEW_NO_PRODUCTION_AUTHENTICATION` | WP-23 |
| `EXPERT_REVIEW_NONE_COMPLETED` | named experts under the approved protocol |
| `EXPERT_REVIEW_CLAIM_BOUNDARY_NOT_APPROVED` | named human and scientific reviewers |

---

## 7. What this report does not establish

It does not establish that the system produces correct pharmacogenetic
assessments. It does not establish that an expert would agree with any output.
It does not establish that the blinding protocol is scientifically adequate -
that judgement belongs to the scientific advisor who has not yet reviewed the
protocol document. It does not establish that the case sample would be
representative, because there is no case sample.

What it establishes is narrower and worth stating precisely: **if** four named
people approve the protocol, **and** curators author expert-holdout cases,
**and** a release is activated, **and** restricted storage is configured,
**and** WP-23 supplies authentication, **and** named experts conduct reviews -
then this software will record what they did, in the order they did it, in
records nobody can afterwards edit.

That is the entire claim.
