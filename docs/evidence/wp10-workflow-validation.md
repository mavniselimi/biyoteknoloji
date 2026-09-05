# WP-10 workflow validation evidence

| Field | Value |
|---|---|
| Document ID | `DOC-EVID-010` |
| Work package | WP-10 — Curation Workflow and Approval Governance |
| What this proves | the machine runs, and against this repository it approves nothing |
| What this does **not** prove | that any conclusion is scientifically correct, or that anybody has approved anything |

---

## 1. What was run

Two walks through the same `CurationWorkflowService`, differing only in the
`WorkflowPolicy` handed to it.

**A** uses a synthetic policy: a protocol that is `APPROVED` by a named
approver, an evidence build that is not quarantined, a source policy that is
`APPROVED`, and five `TEST-` actors each holding exactly one role. **No such
world exists in this repository.** It exists in `tests/support/`, outside the
shipped package, so production code has no route to build it by accident. It
exists at all because the successful path has to be exercisable; the
alternative would be to change the real protocol's approval state or the real
build's quarantine, which this work package forbids and which would be a lie
about the science rather than a test fixture.

**B** uses the repository as it is: protocol `AWAITING_EXPERT_REVIEW`, build
`QUARANTINED` and `NOT_PUBLICATION_ELIGIBLE`, no source policy approval. The
work item is the first of the 1,559 imported from WP-08, with its real id, its
real gene/drug pair and its real legacy values.

Reproduce with:

```
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
    -s tests/unit/curation/workflow -p 'test_*.py' -t .
```

## 2. Transcript

```
== A: one synthetic workflow, every gate open ==
  seeded            TEST-WI-0001 RAW v0
  provenance        PROV-000001 by TEST-steward-1 (not a transition; still RAW v0)
  revision REV-000002   by TEST-curator-1 -> RAW v1
    content hash    sha256:cd2bbd940fef95d3c3445da0d5f6328ac6c3230dc4c68e9b85ba6a7a56767b4c
  submit            -> UNDER_REVIEW v2
  gates             13 of 13 open
  approve           by TEST-reviewer-1 -> CURATED v3
  audit trail       CURATION_REVISION_CREATED -> CURATION_REVISION_SUBMITTED -> CURATION_APPROVED
  review pins       author=TEST-curator-1 hash=sha256:cd2bbd940fef95d3...
  re-review         REFUSED: only an UNDER_REVIEW work item can be reviewed; TEST-WI-0001 is CURATED

== B: one real legacy work item, under the real policy ==
  CWI-LEGACY-2a3e8cb9a5db451a  RAW v0  tags=LEGACY_MIGRATION
  legacy fields     legacy.demo_risk_level, legacy.drug_behavior_hint, legacy.effect_direction, ...
  gate-status       this work item has no revision, so there is no conclusion to evaluate gates against
  approve           REFUSED, 7 gate(s) shut:
      GATE_EVIDENCE_MISSING                  the curator, by correcting the selection
      GATE_EVIDENCE_QUARANTINED              acquisition and source policy, not curation
      GATE_EVIDENCE_TRACE_UNVERIFIED         the data/provenance steward
      GATE_EVIDENCE_WRONG_BUILD              the curator, by re-selecting from the expected build
      GATE_PROTOCOL_NOT_APPROVED             a named scientific expert
      GATE_PROVENANCE_VERIFICATION_MISSING   the data/provenance steward
      GATE_SOURCE_POLICY_MISSING             a named source-policy approver
  state after       UNDER_REVIEW v2
  audit events added by the refused approval: 0
  reviews written by the refused approval:    0

== C: the production role provider ==
  is_empty          True
  lookup            REFUSED: no roles are assigned to 'any.real.person'. This repository's production role assignment set is empt
```

## 3. What each part shows

**A — the successful path is audited, and each step is one event.** Three
transitions produced three audit events, in order, one per operation. The
approval names the reviewer, the revision, its content hash and the author it
was checked against, so "who approved what, independently of whom" is
answerable from the trail without joining back to anything that might have
changed since.

Verifying provenance advanced nothing. A steward confirms that the cited
evidence traces back to raw bytes; that opens one gate and is not a statement
that the conclusion is right, so it must not look like a transition.

The `CURATED` item then refused a second review. A decided conclusion is
terminal; a correction is a new work item citing this one.

**B — the real item is blocked, and the refusal names owners.** Seven gates are
shut. Four of them (`GATE_PROTOCOL_NOT_APPROVED`, `GATE_EVIDENCE_QUARANTINED`,
`GATE_SOURCE_POLICY_MISSING`, `GATE_PROVENANCE_VERIFICATION_MISSING`) are shut
because of the state of the project, and no amount of code closes them. The
other three are shut because the synthetic evidence snapshot used to drive the
walk does not match the real build — which is itself correct behaviour: a
revision citing a build that is not the one in force must not be approvable.

Each blocker names who could open it. A shut gate that nobody owns is a shut
gate nobody opens.

**The refused approval wrote nothing.** No audit event, no review row, and the
work item stayed at `UNDER_REVIEW` version 2. This is the property that matters
most in this file: an audit trail describing a transition that rolled back
would be worse than no trail, because somebody would believe it.

**C — no identity holds any role.** The production `StaticRoleProvider` is
empty and every lookup raises. This is not a configuration gap to be filled in
a later commit; it is the honest state of a project with no authentication.

## 4. Why the synthetic actors are not project personnel

Every actor in the successful walk is prefixed `TEST-`. The prefix is enforced
by `ActorContext` itself and by a database check constraint: an id starting
with `TEST-` must declare `synthetic=True`, and an id that does not must not.
So a synthetic actor cannot appear in an audit trail looking like a person, and
a person cannot be given a fixture's id.

None of these names belongs to anyone. `TEST-curator-1` did not read any
evidence, `TEST-reviewer-1` did not check anything, and `TEST-steward-1` did
not verify any trace. They are the smallest thing that makes the state machine
exercisable, and nothing they "did" is a scientific claim.

## 5. Why secure authentication remains WP-23

Roles here come from an injected `RoleProvider`. That is the right shape — a
caller cannot assert its own permissions, and the CLI and the console offer no
way to supply one — but a provider is not authentication. It answers "what may
this id do", not "is this caller who they say they are". Nothing in WP-10
establishes identity, verifies a credential, or resists an actor id being typed
by somebody else.

So the production provider is empty, and every real workflow operation fails
before it reaches the state machine. That is deliberate. A role table with rows
in it, and no way to prove who is using them, would be worse than no role table
at all: it would produce an audit trail naming people who never acted.

**A24** (a named expert approves a real curation) and **A25** (production
authentication binds identity to roles) remain **BLOCKED**. Neither can be
produced by code.
