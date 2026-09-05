# The thirteen approval gates

| Field | Value |
|---|---|
| Document ID | `DOC-SCI-012` |
| Work package | WP-10 — Curation Workflow and Approval Governance |
| Status | **Seven gates are shut in this repository for reasons no code can close.** |

---

## 1. What a gate is

A conclusion reaches `CURATED` only when all thirteen conditions below hold. A
reviewer clicking approve is necessary and not sufficient.

**Every gate fails closed.** An unknown answer is a closed gate, not an open
one, because the alternative is that a missing input reads as permission — and
"nobody has checked" would become indistinguishable from "somebody checked and
it was fine".

**All thirteen are evaluated every time**, even after one fails. Returning on
the first shut gate would hide the other twelve and make fixing them a
round-trip each.

**Only approval runs them.** Rejecting a conclusion, asking for changes and
referring a dispute are all things a reviewer must be able to do precisely
*when* the gates are shut. Gating rejection behind the approval gates would
trap every blocked item under review forever.

## 2. The gates

### Protocol

| Gate | What it asks | Who can open it |
|---|---|---|
| `GATE_PROTOCOL_NOT_APPROVED` | Has a named scientific expert approved the protocol? | a named scientific expert |
| `GATE_PROTOCOL_HASH_MISMATCH` | Was this revision written under the protocol now in force? | the curator, by rewriting under it |
| `GATE_PROTOCOL_EXPIRED` | Has the protocol been superseded, or is its review overdue? | the protocol owner |

`APPROVED` as a status is not enough: the gate additionally requires a **named
approver**. A status with nobody behind it is a claim nobody made.

### Evidence

| Gate | What it asks | Who can open it |
|---|---|---|
| `GATE_EVIDENCE_MISSING` | Do all the cited records exist in the build? | the curator, by correcting the selection |
| `GATE_EVIDENCE_TRACE_UNVERIFIED` | Has a steward confirmed every cited trace? | the data provenance steward |
| `GATE_EVIDENCE_WRONG_BUILD` | Does the cited build match the one in force? | the curator, by re-selecting |
| `GATE_EVIDENCE_QUARANTINED` | Is the evidence build out of quarantine? | acquisition and source policy, not curation |

### Source policy and conflict

| Gate | What it asks | Who can open it |
|---|---|---|
| `GATE_SOURCE_POLICY_MISSING` | Is there an approved policy for the sources used? | a named source-policy approver |
| `GATE_UNRESOLVED_CONFLICT` | Is any material conflict unresolved? | an adjudicator |

### The conclusion itself

| Gate | What it asks | Who can open it |
|---|---|---|
| `GATE_PROVENANCE_VERIFICATION_MISSING` | Has any steward verified this at all? | the data provenance steward |
| `GATE_RATIONALE_INCOMPLETE` | Is the structured rationale complete? | the curator |

`GATE_PROVENANCE_VERIFICATION_MISSING` and `GATE_EVIDENCE_TRACE_UNVERIFIED` are
separate on purpose. The first asks whether anybody looked; the second asks
whether what they found was clean. A steward who reports problems has looked
and has *not* verified, and one gate cannot express both.

### Independence and freshness

| Gate | What it asks | Who can open it |
|---|---|---|
| `GATE_REVIEWER_NOT_INDEPENDENT` | Is the approver someone other than the author, holding a role that may approve science? | a qualified reviewer who is not the author |
| `GATE_VERSION_STALE` | Is the approver acting on the current version? | the caller, by re-reading |

## 3. Where this repository stands

Seven gates are shut, and four of them cannot be opened by any amount of code:

| Shut gate | Why | Closable by code? |
|---|---|---|
| `GATE_PROTOCOL_NOT_APPROVED` | the protocol is `AWAITING_EXPERT_REVIEW`; no scientist has read it | **no** |
| `GATE_EVIDENCE_QUARANTINED` | the build is `QUARANTINED`, `NOT_PUBLICATION_ELIGIBLE` | **no** |
| `GATE_SOURCE_POLICY_MISSING` | no source policy carries a human approval | **no** |
| `GATE_PROVENANCE_VERIFICATION_MISSING` | no steward exists to verify anything | **no** |
| `GATE_EVIDENCE_TRACE_UNVERIFIED` | consequence of the above | no |
| `GATE_EVIDENCE_MISSING` | depends on what a revision cites | yes, by citing real records |
| `GATE_EVIDENCE_WRONG_BUILD` | depends on what a revision cites | yes, by citing the build in force |

So all 1,559 legacy work items stay `RAW`, and no `CuratedInterpretation`
exists.

Making them pass would require changing the protocol's approval state or the
evidence build's quarantine. **That is not a test fixture problem; it is the
state of the science.** The successful path is exercised instead by synthetic
fixtures that carry their own approved protocol and unquarantined build, kept
outside the shipped package so production code has no route to build that world
by accident.

## 4. Seeing which gates are shut

```
python3 -m pgx.application.curation_workflow_cli gate-status <work-item-id> --text
```

reports each shut gate, why, and who could open it — without attempting
anything. Exit code `1` means at least one is shut. The console shows the same
list in place of the approval control.

You should never have to attempt an approval to discover why it would fail.

## 5. What the gates cannot check

Whether the conclusion is correct. Thirteen open gates mean the process was
followed by qualified people working from traceable evidence under an approved
protocol. They do not mean the science is right.

## 6. Related

- [curation-workflow](curation-workflow.md)
- [curation-role-matrix](curation-role-matrix.md)
- [wp10-approval-governance](../risk-management/wp10-approval-governance.md)
