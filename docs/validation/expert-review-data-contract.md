# WP-22 - Expert Review Data Contract

| Field | Value |
|---|---|
| Document ID | `DOC-VAL-022` |
| Work package | WP-22 - Blind Expert Validation Protocol and Review Module |
| Status | **contract IMPLEMENTED; no record of any kind exists** |
| Machine-readable | `schemas/wp22/`, `pgx/expert_review/models.py` |
| Artifacts | `data/expert-review/wp22-*.json` |
| Companion documents | `docs/validation/expert-protocol.md`, `docs/architecture/wp22-expert-review.md` |

> **No record described below exists in this repository.** The tables are
> empty, the migration has not been executed, and every example here is
> illustrative and marked TEST-ONLY. Nothing in this document is a review, an
> expert opinion, or evidence that either occurred.

---

## 1. What data this contract governs, and what it refuses

This module records **one expert's judgement about one case under one pinned
release**, and the sequence in which they formed it.

It does not accept, store, transport or display:

| Refused | Because |
|---|---|
| patient identifiers of any kind | no case here is a patient |
| VCF, FASTQ, BAM or any raw genotype file | the system takes phenotype profiles, not sequence |
| star alleles or diplotypes as free text | governed vocabularies only |
| EHR extracts, clinical records, notes about a person | out of scope for the product entirely |
| a reviewer's dose, drug or treatment recommendation | the note is bounded and a claim gate scans every rendered page |
| free-text case descriptions typed by a reviewer | there is one bounded note field and nothing else |

The reviewer's note is the **only** free-text field in the whole contract. It
is capped at 1000 characters, is never aggregated or summarised, is never read
by a language model, and never appears in the public aggregate.

---

## 2. The seven record types

Each is append-only. Each carries the hash of its predecessor, so a chain
reader can detect a removed link.

### 2.1 `ReviewAssignment`

One expert-holdout case assigned to one reviewer.

| Field | Type | Note |
|---|---|---|
| `assignment_id`, `review_id` | string | opaque identifiers |
| `case_id` | string | a WP-18 `PGX-VAL-*` identifier |
| `case_role` | `EXPERT_HOLDOUT` | const; nothing else may be assigned |
| `reviewer_actor`, `reviewer_role` | string | `reviewer_role` is const `EXPERT_REVIEWER` |
| `protocol_version` | string | const `pgx-wp22-expert-protocol/1` |
| `assigned_at` | timestamp | server clock, never client-supplied |
| `state` | enum | one of the five review states |
| **ten pins** | hashes and ids | `protocol_hash`, `release_public_id`, `release_manifest_hash`, `software_version`, `software_hash`, `dataset_public_id`, `dataset_content_hash`, `ruleset_public_id`, `ruleset_content_hash`, `case_manifest_hash` |

Every pin is **required**. An assignment that could omit one would not
identify what was reviewed, and a review of unidentified software is not
evidence about any software. Every subsequent record echoes these pins back
unchanged, and every operation re-checks them: a release swapped mid-review
makes the next operation fail rather than silently attributing a judgement to
the wrong build.

### 2.2 `ExpectedResponse`

What the reviewer expected, recorded before anything was revealed.

| Field | Type | Note |
|---|---|---|
| `revision_id`, `review_id`, `revision` | string, string, int | revisions are numbered from 1 |
| `expected_attention_level` | string | governed vocabulary |
| `expected_coverage_status` | string | governed vocabulary |
| `expected_coverage_reason` | string or null | governed code, or null |
| `expected_rule_id` | string or null | which rule they expected to fire |
| `requires_traceable_evidence` | boolean | whether they expect citable evidence |
| `rationale_codes` | array | from the eight-code vocabulary |
| `reviewer_note` | string | ≤ 1000 characters |
| `content_hash`, `revision_hash`, `previous_hash` | digests | content hash covers the judgement without identity or timing |

**There is no field here in which a system result could be written.** The
schema sets `additionalProperties: false`, so one cannot be added by a
producer either. The blinding is a property of the shape.

`PROHIBITED_EXPECTATION_FIELDS` and `PROHIBITED_REQUEST_FIELDS` (33 names)
are rejected at the service boundary with `EXPERT_REVIEW_FORGED_FIELD` before
anything is read: a request carrying its own `actor`, `recorded_at`,
`revision_hash`, `state` or any pin is refused rather than having the value
quietly ignored, because a silently-dropped field looks accepted.

### 2.3 `RevealRecord`

The one-way door, and what it pinned when it opened.

| Field | Type | Note |
|---|---|---|
| `reveal_id`, `review_id` | string | |
| `expectation_revision_id` | string | **required** |
| `expectation_revision_hash` | digest | **required** - the field that makes the protocol checkable afterwards |
| `attention_level`, `coverage_status`, `coverage_reason`, `firing_rule_id` | strings | the system's answer |
| `finding_count`, `traceable_finding_count` | integers | |
| `output_hash` | digest | which exact output was shown |
| `revealed_at`, `reveal_hash`, `previous_hash` | timestamp, digests | |

`expectation_revision_hash` is not optional and has no null form. A revealed
result is therefore always attached to the exact prediction that preceded it,
never to one appended afterwards.

### 2.4 `CompletionDecision`

The post-reveal comparison.

| Field | Type | Note |
|---|---|---|
| `completion_id`, `review_id` | string | |
| `reveal_id` | string | **required and non-null** - a completion that named no reveal would be a judgement of something never shown |
| `decision` | `AGREE` / `PARTIAL` / `DISAGREE` | |
| `ratings` | array of ≤ 4 | one per Likert dimension, 1-5 |
| `reviewer_note` | string | ≤ 1000 characters |
| `completed_at`, `completion_hash`, `previous_hash` | timestamp, digests | |

`PARTIAL` is a **third answer, not a midpoint**. The enum disables ordering
(`__lt__` raises), so no code in this repository can sort or average the three
values. A "mean agreement score" is not a number this contract can produce.

Ratings are optional. The Likert metric's denominator counts completed
**ratings**, not completed reviews, so declining to rate a dimension is not
counted as a low score.

### 2.5 `Correction`

An appended amendment. The corrected record is never modified.

| Field | Type | Note |
|---|---|---|
| `correction_id`, `review_id` | string | |
| `target_hash` | digest | what is being amended |
| `kind` | enum | `TYPOGRAPHIC`, `RATIONALE_AMENDED`, `EXPECTATION_AMENDED`, `DECISION_ANNOTATED`, `RATING_ANNOTATED`, `WITHDRAWN_BY_REVIEWER` |
| `reason_code` | string | |
| `actor`, `actor_role`, `recorded_at` | | |
| `replacement` | object or null | governed expectation fields only; an open object would be the hole a treatment recommendation eventually arrives through |
| `after_reveal` | boolean | set by the server from the store, never by the client |
| `correction_hash`, `previous_hash` | digests | |

A correction with `after_reveal: true` is **annotation only**. WP-21 consumes
the expectation revision the reveal pinned, so no post-reveal amendment can
become the thing the reviewer predicted.

### 2.6 `ReviewAuditEvent`

One hash-linked event per operation, written in the same unit of work as the
record it describes.

| Field | Type | Note |
|---|---|---|
| `schema_version`, `event_id`, `sequence` | | sequence starts at 1 |
| `review_id`, `action` | | eight audit actions |
| `actor`, `actor_role` | | |
| `actor_authenticated` | **const false** | there is no authentication to have authenticated anybody |
| `occurred_at` | timestamp | |
| `previous_state`, `new_state`, `outcome_code` | | |
| `protocol_hash`, `release_manifest_hash`, `case_manifest_hash` | digests | |
| `record_hashes` | object | the records this event covers |
| `previous_hash`, `event_hash` | digests | `previous_hash` is null only at sequence 1 |

`append_event()` derives the sequence and the predecessor hash from the chain
tail rather than accepting them, so a caller cannot insert an event out of
order or claim a predecessor that is not the actual tail.

### 2.7 `PayloadPermit`

Not a bearer token. A value binding assignment, review, case, actor, role,
stage, protocol hash, release manifest hash and case manifest hash, compared
field by field with `hmac.compare_digest`. Refused at issue time for terminal
states.

---

## 3. What crosses each boundary

| Boundary | May carry | May never carry |
|---|---|---|
| reviewer's browser, pre-reveal | assignment pins, the expectation form | any system result, in any field, hidden or otherwise |
| reviewer's browser, post-reveal | the locked expectation and the revealed result, side by side | any edit control over the locked expectation |
| API, pre-reveal | `ExpertReviewStateResponse` - which has no result field | |
| API, post-reveal | `ExpertReviewResultBlock` | reviewer identity of any other reviewer |
| WP-21 metric layer | `CompletedReview`: decision, ratings, pins, case role | the reviewer's note, their corrections, their audit chain, their identity |
| public aggregate | counts, and nulls while the count is zero | any free text, any reviewer name, any per-case result |
| restricted storage | the case payload, under a matching permit | anything without a permit; anything at all outside `EXPERT_REVIEW` context |

---

## 4. Retention, deletion and the reviewer's own data

There is no delete. Not in the service, not in the in-memory store used by
tests, and not in the database - `pgx_expert_review_append_only()` raises on
DELETE as well as UPDATE.

This is a deliberate trade. A review record is evidence about a release; being
able to remove one would make the remaining set unreliable, because nobody
could tell a set of three reviews from a set of five with two removed. A
reviewer who wishes to retract appends a `WITHDRAWN_BY_REVIEWER` correction,
which is visible in the chain and is what the metric layer's eligibility rules
must then account for.

The only personal data a record holds is an actor string and a role. There is
no reviewer name, email, affiliation or credential anywhere in the seven
record types. Names appear in exactly one place in this work package - the
protocol signatory list - and there are currently none.

---

## 5. Migration `0010`, and why it has not run

`migrations/versions/0010_wp22_expert_reviews.py` creates seven tables and
installs two trigger functions:

- `pgx_expert_review_append_only()` on six tables - UPDATE and DELETE both
  raise;
- `pgx_expert_review_forward_only()` on the assignment table - only the
  transitions the vocabulary permits are allowed, so the database refuses a
  backwards state change even if the service were bypassed entirely.

It also widens the WP-09 audit action check constraint to include the eight
review actions.

`downgrade()` **refuses to run while any assignment exists.** Dropping these
tables would destroy review records, and a downgrade that quietly did so would
be the single most damaging operation in this repository.

The migration has not been executed. There is no PostgreSQL instance in this
environment, and WP-22 does not start one, install a driver or perform
deployment work. The tests that would exercise the DDL are declared with an
environment-dependency skip policy and named skip reasons, so the two skips
are reported as explained rather than counted as coverage.

---

## 6. Current contents

| Table | Rows |
|---|---|
| `expert_review_assignments` | 0 |
| `expert_review_expectations` | 0 |
| `expert_review_reveals` | 0 |
| `expert_review_completions` | 0 |
| `expert_review_ratings` | 0 |
| `expert_review_corrections` | 0 |
| `expert_review_audit_events` | 0 |

The tables do not exist yet, so "0" here means "none, and no schema to hold
any". It is not a measurement taken against a live database.
