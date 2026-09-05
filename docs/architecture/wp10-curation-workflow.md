# WP-10 curation workflow and approval governance

| Field | Value |
|---|---|
| Document ID | `DOC-ARCH-010` |
| Work package | WP-10 — Curation Workflow and Approval Governance |
| Status | **Offline scope complete. Nothing in this repository has been approved, and no `CuratedInterpretation` exists.** |
| Depends on | WP-02 (schema), WP-07 (canonical entities), WP-08 (evidence store), WP-09 (curation protocol) |

---

## 1. What this work package is for

WP-09 wrote down how a person turns evidence into a reviewed conclusion. It
defined a contract and performed no curation. WP-10 builds the machine that
would run it: a state machine with persistence behind it, roles that are looked
up rather than asserted, gates that fail closed, and an audit trail that cannot
describe something that did not happen.

The machine exists and works. Against this repository it approves nothing, and
that is the correct output. The protocol is `AWAITING_EXPERT_REVIEW`, the
evidence build is `QUARANTINED`, no source policy carries a human approval, and
no identity holds any role. Every one of those is a fact about the state of the
science and the project, not a gap in the code, and none of them can be closed
by writing more code.

## 2. The state machine

```
    RAW  ──save──▶  revision 1, 2, 3 …            (each immutable once written)
    RAW  ──submit revision N──▶  UNDER_REVIEW     (that revision frozen forever)

    UNDER_REVIEW ──APPROVE──────────────▶  CURATED    (terminal)
    UNDER_REVIEW ──REJECT───────────────▶  REJECTED   (terminal)
    UNDER_REVIEW ──REQUEST_CHANGES──────▶  RAW        (a new revision is required)
    UNDER_REVIEW ──REFER_TO_ADJUDICATION▶  UNDER_REVIEW, adjudication pending
```

The persisted states are WP-02's `CurationStatus`: `RAW`, `UNDER_REVIEW`,
`CURATED`, `REJECTED`. WP-09's `DRAFT` is **not** a fifth state. It describes a
revision's *content* while its work item is `RAW`; the persisted state describes
where the *item* is. They are one state under two names, and the mapping is
asserted by test rather than assumed, because a reader who took `DRAFT` for a
persisted state would look for a transition that does not exist.

**A referral advances the version without changing the state.** Referring a
dispute is not deciding it, so the item stays `UNDER_REVIEW`; but it is an
event, and a reviewer holding the old version must not be able to act as though
it had not happened.

**Terminal means terminal.** A `CURATED` conclusion is never edited. A
correction is a new work item whose lineage cites the old one. This is enforced
in three places — the value object's `require_transition`, the service, and
migration 0007's trigger — and that is not duplication: the rule is "a decided
conclusion never silently changes", and the service is one process among
several that can reach the table.

## 3. Where each rule lives

| Rule | Value object | Service | Database |
|---|---|---|---|
| Permitted transitions | `require_transition()` | checked before every move | `trg_curation_work_items_guarded` |
| A decided item is immutable | `TERMINAL_STATES` | refuses | trigger |
| An update advances the version | — | guarded statement | trigger |
| Reviewer ≠ author | `CurationReview.__post_init__` | `require_role` + gate | check constraint **and** trigger |
| A revision is authored by a curator | `__post_init__` | `require_role` | check constraint |
| Revision lineage is complete | `__post_init__` | — | check constraint |
| One reviewer decides one version once | — | guarded update | unique constraint |
| Legacy values are namespaced | `namespace_legacy_values` | — | `trg_curation_work_items_legacy_namespaced` |
| Revisions/reviews are append-only | ports offer no update | repositories offer no update | immutability triggers |
| An adjudicator is a third party | `__post_init__` | `require_role` | check constraint |
| Both positions are preserved | `__post_init__` | — | check constraints |

The pattern is deliberate. A value object refuses a nonsensical record at
construction; the service refuses a nonsensical *operation*; the database
refuses a nonsensical *row* however it arrives. "We always go through the
service" is a claim about developer behaviour, not about the data.

## 4. Optimistic concurrency

Every state change is one statement:

```sql
UPDATE curation_work_items
   SET status = :new_status, version = version + 1, …
 WHERE work_item_id = :id
   AND status = :expected_status
   AND version = :expected_version
```

The caller requires **exactly one** affected row. Zero means somebody moved
first, and is raised as `ConcurrencyError`. More than one is impossible against
a primary key and would mean the store is not a keyed table, so it is raised as
`AuditIntegrityError` rather than accepted as success.

Read-then-write would leave a window in which two reviewers both read version 3
and both write version 4. The predicate is evaluated by the database at write
time, so it cannot.

`version + 1` is computed by the database for the same reason.

## 5. The thirteen gates

`CURATED` is reachable only when all thirteen are open. Every one fails closed:
an unknown answer is a closed gate, because the alternative is that a missing
input reads as permission.

| Gate | Who can open it | Against this repository |
|---|---|---|
| `GATE_PROTOCOL_NOT_APPROVED` | a named scientific expert | **shut** — `AWAITING_EXPERT_REVIEW` |
| `GATE_PROTOCOL_HASH_MISMATCH` | the curator, by re-writing under the protocol in force | open when the revision was written under the current protocol |
| `GATE_PROTOCOL_EXPIRED` | the protocol owner | open |
| `GATE_EVIDENCE_MISSING` | the curator, by citing records that exist | depends on the citation |
| `GATE_EVIDENCE_TRACE_UNVERIFIED` | a data provenance steward | **shut** — nobody has verified |
| `GATE_EVIDENCE_WRONG_BUILD` | the curator | depends on the citation |
| `GATE_EVIDENCE_QUARANTINED` | whoever lifts the quarantine | **shut** — `QUARANTINED`, `NOT_PUBLICATION_ELIGIBLE` |
| `GATE_SOURCE_POLICY_MISSING` | a source policy reviewer | **shut** — no human approval |
| `GATE_UNRESOLVED_CONFLICT` | an adjudicator | open when no material conflict is identified |
| `GATE_PROVENANCE_VERIFICATION_MISSING` | a data provenance steward | **shut** |
| `GATE_RATIONALE_INCOMPLETE` | the curator | depends on the draft |
| `GATE_REVIEWER_NOT_INDEPENDENT` | a reviewer who is not the author | **shut** — no identity holds a role |
| `GATE_VERSION_STALE` | the caller, by re-reading | open when the caller is current |

Every gate is evaluated even after one fails. Returning on the first shut gate
would hide the other twelve and make fixing them a round-trip each.

**Only `APPROVE` runs the gates.** Rejecting, requesting changes and referring
a dispute are all things a reviewer must be able to do precisely *when* the
gates are shut. Gating rejection behind the approval gates would trap every
blocked item under review forever.

**An adjudicated approval runs the same gates.** An adjudicator settles a
disagreement between two people; they do not thereby acquire the power to
approve over a quarantined build, because that is not what the two disagreed
about.

## 6. Roles

Actor roles come from an injected `RoleProvider`. The production provider holds
`EMPTY_ROLE_ASSIGNMENTS` — an empty mapping — so every lookup raises
`ActorError` and no real workflow can run. `curation_role_assignments` is
created empty by migration 0007 and stays empty.

An `ActorContext` cannot be constructed with roles directly: `__post_init__`
refuses one that was not issued by a provider. The service takes an *actor id*
and refuses an `ActorContext` passed in its place, so a caller cannot assert its
own permissions. The CLI has no `--role`, no `--as`, no `--force`; each is
refused by name, and `allow_abbrev=False` stops `--role` being absorbed as a
prefix of `--roles`. The console has no role field, and one posted anyway is
refused rather than honoured.

Synthetic actors are prefixed `TEST-`, and the prefix and the `synthetic` flag
must agree — in the value object and in a database check constraint. So a
fixture cannot be mistaken for a person in an audit trail, and a person cannot
be handed a fixture's id. **These are not credentials and they are not
authentication.** WP-23 owns identity; until it exists, nobody holds a role.

## 7. Audit

Every successful operation writes exactly one `AuditEvent` in the same unit of
work as the change. A failed operation writes none: the in-memory unit of work
snapshots the audit list on entry and restores it on a rollback, and the
SQLAlchemy one shares a single session and transaction. An audit trail
describing a transition that rolled back is worse than no trail, because
somebody would believe it.

Eight actions were added to `AuditAction`, and migration 0007 widens
`ck_audit_events_action_enum` to admit them. The widening is strict: every
action the old constraint admitted, the new one admits.

## 8. What WP-10 does not do

- It creates no `CuratedInterpretation`. The identifier appears nowhere in
  `pgx/curation/workflow`.
- It creates no `ComputableRule`, no rules package, and transitions no rule to
  `VALIDATED`. `approval.py` validates an envelope and grants nothing.
- It starts no FastAPI application and no server. `forms.py` is functions from
  data to strings; nothing binds or listens.
- It publishes no dataset and activates no release.
- It computes no risk level, attention level or score.
- It alters no raw, canonical or evidence build.

## 9. Related documents

- `docs/data/curation-workflow-contract.md` — the states, the gates and the
  roles as a contract
- `docs/migration/wp10-legacy-work-items.md` — the 1,559 imported questions
- `docs/evidence/wp10-workflow-validation.md` — one synthetic audited walk and
  one real blocked item
- `docs/evidence/wp10-schema-validation.md` — the rendered DDL against real
  PostgreSQL
- `docs/risk-management/wp10-approval-governance.md` — what could go wrong
- `docs/handoffs/wp10-handoff.md` — what WP-11 inherits
