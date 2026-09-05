# The curation workflow

| Field | Value |
|---|---|
| Document ID | `DOC-SCI-010` |
| Work package | WP-10 — Curation Workflow and Approval Governance |
| Audience | scientific curators, independent reviewers, adjudicators, data provenance stewards |
| Status | **The workflow is implemented. Nothing in this repository has passed through it, and nobody currently holds a role.** |

---

## 1. What this document is for

If you are curating, reviewing or adjudicating a pharmacogenomic conclusion in
this project, this is what happens to your work and why each step exists.

The short version: you write a claim, somebody else who did not write it checks
it, thirteen conditions must all be satisfied before it counts as this
project's conclusion, and every step of that is recorded in a way that cannot
be edited afterwards.

## 2. The five things a work item can be

A **work item** is one question: this gene, this drug, what does the evidence
say? It is not an answer. There are 1,559 of them and all of them are `RAW`.

```
    RAW  ──save a draft──▶  revision 1, 2, 3 …
    RAW  ──submit one──▶  UNDER_REVIEW

    UNDER_REVIEW ──approve──────────────▶  CURATED
    UNDER_REVIEW ──reject───────────────▶  REJECTED
    UNDER_REVIEW ──request changes──────▶  RAW  (write a new revision)
    UNDER_REVIEW ──refer to adjudication▶  UNDER_REVIEW, awaiting an adjudicator
```

`CURATED` and `REJECTED` are final. If a curated conclusion turns out to be
wrong, the correction is a **new work item that cites the old one** — never an
edit. That is not bureaucracy: a conclusion somebody acted on last year has to
stay readable as it was when they acted on it.

The protocol calls the first state `DRAFT` and the database calls it `RAW`.
They are the same state. `DRAFT` describes what your revision's *content* is
while the work item is `RAW`.

## 3. Writing a revision

A revision is one version of your conclusion. It records what you claimed, the
evidence you selected, the evidence you deliberately set aside, the protocol
version you worked under, and the evidence build you read from. All of it is
hashed together.

You can save as many revisions as you like while the item is `RAW`. Each one is
kept. Nothing is overwritten, so a reviewer looking at your work later can see
how it developed.

**Once you submit a revision it is frozen.** You cannot edit it, and neither
can anyone else. If a reviewer asks for changes, you write revision *N+1*
naming revision *N* as its parent.

If you cite no evidence, the revision is refused. A conclusion with nothing to
interpret is not a conclusion.

## 4. Being reviewed

An independent scientific reviewer reads your submitted revision and does one
of four things.

**Approve.** Your reading becomes this project's conclusion. This requires all
thirteen gates to be open — see
[curation-approval-gates](curation-approval-gates.md).

**Reject.** The reviewer does not accept the conclusion. This is available even
when gates are shut, and deliberately so: a reviewer must be able to refuse a
conclusion precisely when it cannot be approved.

**Request changes.** The item returns to `RAW` and you write a new revision.
Your old revision and the reviewer's rationale are both kept.

**Refer to adjudication.** The reviewer thinks you and they disagree in a way
neither of you can settle. The item stays `UNDER_REVIEW` and waits for an
adjudicator.

**The reviewer cannot be you.** This is checked in four places, and one of them
is a database constraint, so it holds even if the application is bypassed.

The reviewer's decision records the exact content hash of what they read. If
somebody later claimed a different revision had been approved, the hashes would
not match.

## 5. Adjudication

An adjudicator is a third person who is neither the curator nor the reviewer.
They read both positions and decide which reading the project adopts.

**Both positions are kept in full.** The adjudication does not replace them,
merge them, or compute a consensus. A year from now somebody must be able to
see what was disputed and judge whether the adjudicator got it right.

An adjudicator may approve, reject or request changes. They cannot refer the
dispute onward — that would be a loop with no exit — and an adjudicated
approval passes the same thirteen gates as any other. Settling a disagreement
between two scientists does not give anyone the power to approve over a
quarantined evidence build.

## 6. Provenance verification

A data provenance steward separately confirms that the evidence you cited
traces back to the raw bytes it claims to come from.

This is **not** a scientific review. The steward is checking the plumbing, not
your reasoning, and the workflow keeps the two apart on purpose: a system that
let a trace check stand in for a scientific one would be treating a filesystem
question as a scientific judgement.

Verifying provenance opens one gate. It does not move your work item.

## 7. What is recorded

Every step writes one entry to an append-only audit trail: who did what, to
which work item, when, and why. An approval additionally records the revision,
its content hash and the author it was checked against.

**A failed step records nothing.** If an approval is refused because a gate is
shut, no audit entry is written, no review is stored, and the work item does
not move. A trail describing something that did not happen would be worse than
no trail at all.

Audit entries are never edited or deleted.

## 8. Two people cannot decide the same thing

Every action carries the version of the work item you were looking at. If
somebody else acted between your reading the page and your submitting it, your
action is refused and you are told so.

This is why the console shows a version number and why the CLI requires
`--expected-version`. Without it, "approve this" would silently mean "approve
whatever it is now".

## 9. What the workflow cannot do for you

It cannot tell you whether a conclusion is right. A wrong reading of a study,
independently reviewed by somebody who makes the same mistake, passes every
gate in this document.

What it can do is make sure that a conclusion has an author, a reviewer who is
not the author, a stated rationale, cited evidence that traces to real bytes,
and a record of all of it that cannot be quietly changed.

## 10. Related

- [curation-role-matrix](curation-role-matrix.md) — who may do what
- [curation-approval-gates](curation-approval-gates.md) — the thirteen gates
- [curation-protocol-v1](curation-protocol-v1.md) — how to write the conclusion itself
- [curation-admin-flow](../operations/curation-admin-flow.md) — using the console and CLI
- [curation-workflow-contract](../data/curation-workflow-contract.md) — the same rules as a contract
