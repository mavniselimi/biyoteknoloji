# WP-10 handoff

| Field | Value |
|---|---|
| Document ID | `DOC-HANDOFF-010` |
| Work package | WP-10 — Curation Workflow and Approval Governance |
| Status | **Offline scope complete. Nothing has been approved, no conclusion is `CURATED`, and no identity holds a role.** |
| Output for WP-11 | a state machine with persistence, thirteen gates that fail closed, an audit trail that cannot lie, 1,559 questions on a queue, and a rule-approval envelope contract |

> Read this before WP-11. Three items must not be presented as met.
> **A24**, a named expert approving a real curation, is **BLOCKED** — no
> scientist has approved the protocol, so no gate can open.
> **A25**, production authentication binding identity to roles, is **BLOCKED** —
> WP-23 owns it, and the role assignment set is deliberately empty.
> **A26**, the migration applying under Alembic itself, is **BLOCKED** — Alembic
> cannot be installed here; the rendered DDL was run against real PostgreSQL
> instead and that is supplementary evidence, not a substitute.
> WP-09's **A21**, **A22** and **A23** remain blocked and were not touched.

---

## 1. What exists now

| Artefact | What it is |
|---|---|
| `pgx/curation/workflow/models.py` | Work item, revision, submission, review, adjudication, provenance; `pgx-curation-workflow/1` |
| `pgx/curation/workflow/policy.py` | Thirteen gates, declared as data with owners |
| `pgx/curation/workflow/roles.py` | `ActorContext`, `RoleProvider`, an empty production assignment set |
| `pgx/curation/workflow/service.py` | The one place a work item moves |
| `pgx/curation/workflow/ports.py` | Six protocols; the append-only ones declare no mutation |
| `pgx/curation/workflow/memory.py` | The reference implementation of those ports |
| `pgx/curation/workflow/legacy.py` | The WP-08 proposal import |
| `pgx/curation/workflow/forms.py` | A transport-neutral console; no server |
| `pgx/curation/workflow/approval.py` | The WP-11 rule-approval envelope validator |
| `pgx/curation/workflow/errors.py` | Nine failure types, each carrying structured detail |
| `pgx/infrastructure/db/models.py` | Seven ORM classes added |
| `pgx/infrastructure/db/curation_workflow.py` | Repositories and a workflow unit of work |
| `pgx/application/curation_workflow_cli.py` | `pgx-curation-workflow`, ten commands |
| `pgx/application/curation_workflow_schema.py` | Loads and applies the six published schemas |
| `migrations/versions/0007_wp10_curation_workflow.py` | Seven tables, seven triggers, thirty-eight check constraints |
| `scripts/render_wp10_schema.py` | Renders 0007 to executable DDL |
| `scripts/build_wp10_migration.py` | Regenerates the migration artifacts byte-identically |
| `data/migration/wp10/` | 1,559 RAW work items, allocation, links, issues, manifest, checksums |
| `schemas/curation-work-item`, `curation-revision`, `curation-review`, `curation-adjudication`, `curation-audit-event`, `rule-approval-envelope` | Six published contracts |

Scientific: [curation-workflow](../scientific/curation-workflow.md),
[curation-role-matrix](../scientific/curation-role-matrix.md),
[curation-approval-gates](../scientific/curation-approval-gates.md).
Operations: [curation-admin-flow](../operations/curation-admin-flow.md).
Architecture: [wp10-curation-workflow](../architecture/wp10-curation-workflow.md),
[curation-workflow-contract](../data/curation-workflow-contract.md).
Migration: [wp10-legacy-work-items](../migration/wp10-legacy-work-items.md).
Risk: [wp10-approval-governance](../risk-management/wp10-approval-governance.md).
Evidence: [wp10-workflow-validation](../evidence/wp10-workflow-validation.md),
[wp10-schema-validation](../evidence/wp10-schema-validation.md).

## 2. How the WP-09 delta was resolved

WP-09's handoff recorded one: the protocol spells the first state `DRAFT`, the
persisted enum spells it `RAW`, and WP-10 had to either rename the enum in
migration 0007 or map the two explicitly without treating them as different
states.

**It was mapped, not renamed.** `RAW` remains the persisted state. `DRAFT`
describes a *revision's content* while its work item is `RAW`; the persisted
state describes where the *item* is. They are one state under two names, and a
test asserts that `DRAFT` is not a member of `CurationStatus` so a reader
cannot take it for a fifth state.

Renaming would have been a migration rewriting `0001`, which this work package
does not do, for a cosmetic gain.

`CuratedInterpretation` was not weakened. Its invariants — at least one
evidence record; `CURATED` additionally requires a rationale, a reviewer and a
review timestamp — are unchanged, and WP-10 creates no row in that table.

## 3. What WP-11 inherits

**A settled approval contract.** `RuleApprovalEnvelope` states what a rule
approval must carry: twenty-one fields, each with a reason; separation between
creator, reviewer and approver; timestamp ordering; a `CURATED` conclusion
only; pinned hashes for the rule, the revision, the protocol and the evidence
build; enumerated evidence and source versions. It refuses `auto_approve`,
`bypass_gates`, `rule_status` and `computable_rule`.

It creates nothing. There is no `ComputableRule`, no rules package, and no path
to `VALIDATED`.

**A validator, not an approval.** A valid envelope is a well-formed claim. The
people it names must be real and hold real credentials, which is WP-23's work.
`RuleApprovalValidation.advisory` says so in every result, so a caller cannot
read `valid: true` as permission.

**Zero conclusions to build rules from.** There is no `CURATED` work item and
no `CuratedInterpretation`. WP-11 cannot generate a rule from real content
until a scientist approves the protocol, the evidence build leaves quarantine,
a source policy gains human approval, and a curator and an independent reviewer
exist. That is four blockers, and none of them is code.

## 4. Using the CLI

Offline, no database, no network. Reads the migration artifacts into an
in-memory store and runs the real service over them.

```
python3 -m pgx.application.curation_workflow_cli import-legacy --text
python3 -m pgx.application.curation_workflow_cli list --limit 5 --text
python3 -m pgx.application.curation_workflow_cli show CWI-LEGACY-… --text
python3 -m pgx.application.curation_workflow_cli gate-status CWI-LEGACY-… --text
python3 -m pgx.application.curation_workflow_cli history CWI-LEGACY-…
python3 -m pgx.application.curation_workflow_cli render-form detail --work-item CWI-LEGACY-…
```

Exit codes: `0` answered, `1` refused, `2` configuration failure, `3` not found.
Output is JSON unless `--text`.

Every mutating command refuses, and the refusal is the deliverable:

```
$ … submit CWI-LEGACY-… --revision REV-1 --expected-version 0 --actor TEST-curator-1
{
  "code": "ActorError",
  "detail": "no roles are assigned to 'TEST-curator-1'. This repository's
             production role assignment set is empty: no real curator,
             reviewer or adjudicator identity exists, so no real workflow
             can run.",
  "refused": true
}
```

There is no `--role`, `--as`, `--force` or `--skip-gates`; each is refused by
name. `allow_abbrev=False`, so `--role` cannot be absorbed as a prefix of
`--roles`. A role file may be supplied for exercising the workflow and is
refused unless every actor in it is `TEST-` prefixed.

## 5. What must not be presented as done

| Criterion | State | Why |
|---|---|---|
| A24 — a named expert approves a real curation | **BLOCKED** | the protocol is `AWAITING_EXPERT_REVIEW`; no scientist has read it |
| A25 — production authentication binds identity to roles | **BLOCKED** | WP-23 owns identity; the assignment set is empty by design |
| A26 — 0007 applies and reverts under Alembic | **BLOCKED** | Alembic cannot be installed here; rendered DDL was run instead |
| A21–A23 (WP-09) | **BLOCKED** | unchanged by this work package |

None of these was fabricated, and none can be produced by code.

## 6. Open items for whoever comes next

1. **WP-23 owes authentication.** Until it exists, `curation_role_assignments`
   stays empty and no real workflow runs. Adding rows without a way to prove
   who is using them would be worse than the empty table.
2. **The evidence build is quarantined.** `GATE_EVIDENCE_QUARANTINED` and
   `GATE_SOURCE_POLICY_MISSING` are shut for reasons owned by acquisition and
   source policy, not by curation.
3. **The 33 unlinked work items** stay unlinked. A curator selects evidence when
   they write a revision; guessing a link would manufacture a citation the
   source never made.
4. **The console has no transport.** WP-16 owns that, and inherits the whole
   authentication problem with it.
5. **`legacy_values` are still upstream text.** Nothing in this work package
   reviewed any of them, and the 1,559-entry WP-09 review queue is still
   entirely `NOT_REVIEWED`.
