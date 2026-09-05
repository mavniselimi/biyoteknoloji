# The curation workflow contract

| Field | Value |
|---|---|
| Document ID | `DOC-DATA-010` |
| Work package | WP-10 — Curation Workflow and Approval Governance |
| Model version | `pgx-curation-workflow/1` |
| Status | **The machine is implemented. Nothing in this repository has passed through it.** |

---

## 1. What a work item is

A work item is **one question nobody has answered yet**: this gene, this drug,
what does the evidence say? It is not a conclusion, and its existence asserts
nothing. There are 1,559 of them, all `RAW`.

A work item carries the legacy values WP-08 extracted, namespaced `legacy.`, as
**unreviewed upstream input**. Those values are what the old project believed.
Nobody has checked them, they are not evidence, and the namespace is what stops
a query for curated content from matching one by accident. The console renders
them in a visually distinct block labelled "unreviewed upstream text" for the
same reason: a curator must be able to tell what a source said from what a
colleague concluded.

## 2. The states

| State | Meaning | What may happen next |
|---|---|---|
| `RAW` | a question on the queue, or a draft being written | a revision may be saved; one may be submitted |
| `UNDER_REVIEW` | one revision is with an independent reviewer | approve, reject, request changes, refer |
| `CURATED` | a conclusion this project stands behind | nothing — terminal |
| `REJECTED` | a conclusion this project refused | nothing — terminal |

WP-09's `DRAFT` is not a fifth state. It is what a revision's content is while
its work item is `RAW`. One state, two vocabularies, and the mapping is
asserted by test.

## 3. Revisions

A revision is one immutable version of a curation payload. It pins:

- the WP-09 payload,
- the protocol version and content hash it was written under,
- the evidence build and the exact records selected (and those deliberately
  excluded),
- the curator who wrote it, and when,
- its parent, unless it is the first.

Its content hash covers all of that and excludes the timestamp: two identical
claims written a minute apart are one claim, and a hash that disagreed would
make "did this change" unanswerable.

**Submitted revisions are frozen.** Nothing in the service edits one, the
repositories offer no update method, and migration 0007 refuses `UPDATE` and
`DELETE` at the row. A correction after a change request is revision *N+1*
naming revision *N* as its parent; a correction to a `CURATED` conclusion is a
new work item citing the old one.

## 4. Reviews

A review is one independent reviewer's decision about one submitted revision.
It pins the revision **and its content hash**, so "was this reviewed" is
answerable by comparing bytes rather than by trusting a foreign key to have
pointed at the same content all along. It pins the author too, so "was the
reviewer independent" is answerable from the review alone.

**No review overwrites another.** Two reviews of one revision are two records.
Which one governed is decided by the work item's state transitions, not by one
silently replacing the other. A review that asked for changes before a later
approval is part of how the conclusion was reached, and the history shows it.

One reviewer may decide one work-item version once. Changing your mind means
reviewing the next version.

## 5. Adjudication

When a curator and a reviewer disagree, the reviewer may refer the dispute. A
third named person — an adjudicator, who may be neither party — settles it.

An adjudication record preserves **both positions in full** and the disputed
evidence. It does not generate a consensus, merge the two readings, or choose
automatically. An adjudication that replaced the positions would erase the
disagreement it was called to settle, and nobody could later check whether the
adjudicator was right.

An adjudicator may approve, reject, or request changes. They may not refer the
dispute onward: that would be a loop with no exit.

An adjudicated approval runs the same thirteen gates. Settling a disagreement
between two people does not confer the power to approve over a quarantined
build.

## 6. Roles

| Role | May | May not |
|---|---|---|
| `SCIENTIFIC_CURATOR` | write and submit revisions | review or approve their own work |
| `INDEPENDENT_SCIENTIFIC_REVIEWER` | approve, reject, request changes, refer | review a revision they authored |
| `ADJUDICATOR` | settle a referred dispute | adjudicate a dispute they are a party to |
| `DATA_PROVENANCE_STEWARD` | verify that cited evidence traces to raw bytes | advance a conclusion |
| `PROTOCOL_OWNER` | own the protocol document | approve a curation |
| `ENGINEERING_OBSERVER` | read | anything else |

Roles are **looked up, never asserted**. The service takes an actor id and
resolves it through an injected `RoleProvider`; it refuses an `ActorContext`
passed in place of an id. There is no `--role`, no `--as`, no role form field,
and no override flag anywhere.

**The production assignment set is empty.** No identity holds any role, so no
real workflow operation can run. That is the honest state of a project with no
authentication, and WP-23 owns closing it.

Synthetic test actors carry a `TEST-` prefix, enforced in both directions by
the value object and a database check constraint, so a fixture cannot be
mistaken for a person and a person cannot be handed a fixture's id.

## 7. The gates

Thirteen checks, all of which must be open for `CURATED`. Each fails closed:
an unknown answer is a closed gate, because the alternative is that a missing
input reads as permission. Each names the person who could open it.

They are listed with their owners in
`docs/architecture/wp10-curation-workflow.md` §5 and declared as data in
`pgx/curation/workflow/policy.py`, so a document, a CLI and a test all cite the
same codes.

Only `APPROVE` runs them. A reviewer must be able to refuse a conclusion
precisely when it cannot be approved.

## 8. Concurrency

Every state change is a guarded `UPDATE` naming the expected status and version
and requiring exactly one affected row. Two reviewers cannot both decide the
same work-item version: the second is told that somebody moved first, and
writes nothing.

## 9. Audit

Every successful operation writes exactly one append-only `AuditEvent` in the
same transaction as the change. A failed operation writes none — the work-item
change, the review and the event roll back together.

The event names the actor, the object, the action, and for an approval the
revision, its content hash and the author it was checked against. "Who approved
what, independently of whom" is answerable from the trail alone.

## 10. What this contract does not cover

Authentication (WP-23), rule generation (WP-11), the API (WP-16), and whether
any conclusion is scientifically correct. The workflow governs *how* a
conclusion is reached and recorded. It cannot make one true.
