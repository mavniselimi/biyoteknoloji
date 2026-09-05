# WP-10 approval governance risks

| Field | Value |
|---|---|
| Document ID | `DOC-RISK-010` |
| Work package | WP-10 — Curation Workflow and Approval Governance |
| Scope | how a wrong conclusion could reach a clinician through this workflow, and what stops it |

---

## 1. The failure this work package exists to prevent

A conclusion about a gene and a drug reaches somebody making a clinical
decision, carrying an approval that nobody actually gave.

Every control below is aimed at some version of that. They are listed with the
specific way each could fail, because a control whose failure mode is not
written down is a control nobody maintains.

## 2. Risks and controls

### R-10-01 — A curator approves their own conclusion

**How it happens.** The person who wrote a reading is also the person who signs
it off, because they are the only one who understands it, or because the
workflow made it easy.

**Controls.** Separation is checked in four places: the `CurationReview` value
object refuses a record where reviewer and author match (case-insensitively);
the service requires the `INDEPENDENT_SCIENTIFIC_REVIEWER` role, which the
curator does not hold; `GATE_REVIEWER_NOT_INDEPENDENT` refuses the approval;
and a database check constraint plus a trigger refuse the row — the trigger
comparing the reviewer against the *stored* revision, so a review row that lied
about its author is refused too.

**Residual.** One person holding two identities defeats all four. Only real
authentication closes that, and it is WP-23's.

### R-10-02 — A conclusion is approved over a shut gate

**How it happens.** Somebody adds a `--force` flag, or a "temporary" override
for a build that is quarantined "for now".

**Controls.** There is no override. No flag, no form field, no CLI argument,
and no code path. `--force`, `--skip-gates` and six other spellings are refused
by name so the message explains why. The console does not render an approval
control when a gate is shut — the option is absent from the select, not
disabled — and the blockers are listed with their owners in its place.

**Residual.** A future commit could add one. The tests that assert the absence
of each named flag and command exist to make that commit fail.

### R-10-03 — An audit trail describes something that did not happen

**How it happens.** The change rolls back and the audit event does not, because
they were written on different connections or in different transactions.

**Controls.** One session, one transaction, one commit. The in-memory unit of
work snapshots the audit list on entry and restores it on rollback — the audit
list is part of the snapshot precisely because an append-only sink cannot undo
itself. Tests assert that a blocked approval and a lost race each add zero
audit events.

**Residual.** None identified in-process. A future async or batched audit sink
would reintroduce it.

### R-10-04 — Two reviewers decide the same conclusion

**How it happens.** Both read version 3, both act, and the second silently
overwrites the first.

**Controls.** Every state change is a guarded `UPDATE` naming the expected
status and version, requiring exactly one affected row. Zero means somebody
moved first and raises. A database trigger refuses any update that does not
advance the version. A unique constraint stops one reviewer recording two
decisions on one version.

**Residual.** None identified. Verified against real PostgreSQL: the stale
predicate affects zero rows.

### R-10-05 — A reviewed revision is edited afterwards

**How it happens.** A typo is fixed "harmlessly" after submission, and the
approval now refers to text nobody approved.

**Controls.** Revisions, reviews, adjudications and provenance verifications
have no update path: the ports declare none, the repositories implement none,
and migration 0007 refuses `UPDATE` and `DELETE` at the row. A review pins the
revision's content hash, so an edit would be detectable even if a row changed;
a database trigger refuses a review whose pinned hash does not match the stored
revision.

**Residual.** A superuser with `ALTER TABLE ... DISABLE TRIGGER`. Out of scope
for application controls.

### R-10-06 — Legacy values are read as conclusions

**How it happens.** `demo_risk_level: high` sits in a work item and somebody —
a person reading a page, or a query — treats it as this project's finding.

**Controls.** Every legacy field is namespaced `legacy.`, enforced at build time
and by a database trigger, so no query for curated content matches one. The
console renders them in a visually distinct block labelled "unreviewed upstream
text", separate from curator text labelled "written by this project", and the
work item stays `RAW` with no revision.

**Residual.** A person can still misread a labelled block. The label and the
separation are the mitigation; they are not a guarantee.

### R-10-07 — An adjudication erases the disagreement it settled

**How it happens.** The adjudicator's decision replaces both positions, and a
year later nobody can tell what was disputed or whether the adjudicator was
right.

**Controls.** `curator_position` and `reviewer_position` are required, non-empty
and stored in full, enforced by the value object and by two check constraints.
The adjudicator may not be either party. No consensus is generated and nothing
is chosen automatically. The history page renders both positions with the note
that the adjudication settled which reading the project adopts and did not
erase the disagreement.

**Residual.** An adjudicator can write a thin position summary. Length is
checked; substance is not checkable by code.

### R-10-08 — A rule ships carrying an approval nobody gave

**How it happens.** WP-11 generates a rule from a conclusion and inherits a
looser approval contract written under delivery pressure.

**Controls.** The `RuleApprovalEnvelope` validator is written now, in WP-10,
because the requirements are governance requirements rather than rule-engine
ones. Twenty-one required fields, each with a stated reason; separation of
duties between creator, reviewer and approver; timestamp ordering; a `CURATED`
conclusion only; pinned hashes; and four forbidden fields (`auto_approve`,
`bypass_gates`, `rule_status`, `computable_rule`). It creates nothing and
transitions nothing.

**Residual.** WP-11 could ignore the validator. That is a review question, not
a code control.

### R-10-09 — Role stubs are mistaken for authentication

**How it happens.** A role table exists, so somebody assumes access control is
handled.

**Controls.** The production assignment set is empty and every lookup raises,
naming the reason. The database table is created empty and stays empty.
Synthetic actors must carry a `TEST-` prefix, in both directions. The CLI
refuses a role file naming a non-synthetic actor. Every document says WP-23
owns identity.

**Residual.** This is the largest open risk in the work package, and it is open
by design rather than by oversight. A role table with rows in it and no way to
prove who is using them would be worse than none: it would produce an audit
trail naming people who never acted.

### R-10-10 — The console is exposed

**How it happens.** Somebody wires `forms.py` to a web server and it becomes
reachable.

**Controls.** It is not a server. Pure functions from data to strings; no
framework import, nothing that binds or listens, asserted by test. Read
handlers receive a read-only façade with no mutating method, so a mutation in a
read handler is an `AttributeError` and not a review finding. Write routes
refuse a GET-like method before reading anything. Every value is escaped once,
in one function, with `quote=True`.

**Residual.** Whoever exposes it inherits the whole authentication problem.
WP-16 owns the transport, and this console is not it.

## 3. What no control here can do

None of this makes a conclusion correct. The workflow governs how a conclusion
is reached, by whom, and how it is recorded. A wrong reading of a study,
independently reviewed by somebody who makes the same mistake, passes every
gate in this document.

That is why `SAFETY-INV-001` — missing data is never a low-risk finding —
belongs to the record vocabulary and not to the workflow, and why the exercise
and the protocol still await human scientists.

## 4. Related

- `docs/architecture/wp10-curation-workflow.md`
- `docs/data/curation-workflow-contract.md`
- `docs/evidence/wp10-workflow-validation.md`
