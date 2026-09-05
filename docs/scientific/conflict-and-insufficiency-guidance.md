# Conflict and insufficiency guidance (WP-09)

| Field | Value |
|---|---|
| Document ID | `DOC-SCI-012` |
| Protocol | `pgx-curation-protocol/1` (`AWAITING_EXPERT_REVIEW`) |
| Invariants | `SAFETY-INV-001`, `SAFETY-INV-008` |

Two situations, one failure mode. A reader takes "the sources disagree" or "we
did not establish this" as "there is nothing here". That reading — false
reassurance — is the highest-consequence error a pharmacogenomic tool can make,
because the clinician acts on the absence rather than on the uncertainty.

---

## 1. Conflict

### 1.1 There is no precedence rule

**This project has no rule that CPIC outranks DPWG, that a regulator label
outranks a guideline, that the newest record supersedes the older one, or that
a higher source score wins.**

There is no precedence field in `ConflictAnalysis`, no ranking function, no
merge and no "prefer" helper anywhere in `pgx/curation`. Two tests enforce
this: one reads the modules' identifiers and fails if a precedence name
appears, and one fails if a guideline body is named inside a comparison — because
a precedence rule hidden as a constant would have to name one.

WP-05 took this position for source conflicts. This is the same position one
stage later, and the reason has not changed: a global precedence order silently
answers every future disagreement, including ones nobody has looked at, using a
judgement made once in a different context.

### 1.2 What a recorded conflict must carry

| Field | Required when | Note |
|---|---|---|
| `conflicting_evidence_uuids` | always | At least two. A "conflict" naming one record is a note, and storing it as a conflict would inflate the count that blocks rules. |
| `disputed_field` | state ≠ NONE_IDENTIFIED | What precisely disagrees. |
| `source_versions` | recommended | Which versions were compared. |
| `applicability_differences` | where relevant | Two sources may be describing different populations rather than disagreeing. |
| `material` | state ≠ NONE_IDENTIFIED | Undetermined materiality is expressed as `UNRESOLVED` with `material=False` **and an explanation** — not by leaving it null. |
| `curator_analysis` | state ≠ NONE_IDENTIFIED | What the curator makes of it. |
| `adjudication_required` | always | Whether a third named person is needed. |

### 1.3 The four states

| State | Meaning | Blocks rules |
|---|---|:-:|
| `NONE_IDENTIFIED` | Nobody found a conflict. **Not** a finding of agreement. | no |
| `PRESENT` | A disagreement exists and has been assessed. | if material |
| `UNRESOLVED` | A disagreement exists and is not settled. | yes |
| `ADJUDICATION_REQUIRED` | A named third person must decide. | yes |

### 1.4 What `CONFLICTING` does not mean

A curator may reach a reviewed conclusion of `CONFLICTING`. That conclusion:

- does **not** resolve the underlying source disagreement;
- does **not** mean the combination is safe, low risk, or unremarkable
  (`SAFETY-INV-008`);
- does **not** permit a rule to be built over the disputed question.

A `CONFLICTING` conclusion whose text reads as reassurance is refused at
construction, with the offending phrase named.

### 1.5 Resolution

Requires a named human and explicit written reasons. WP-09 states this
requirement and provides the adjudication template; it does not perform the
workflow, which is WP-10's.

An adjudication **preserves both original responses**. One that replaced them
would erase the disagreement it was called to settle, and nobody could later
check whether the adjudicator was right either.

---

## 2. Insufficiency

### 2.1 It is an answer, not a failure to answer

`INSUFFICIENT` means: *the evidence reviewed does not support a stronger
statement*. It is a first-class member of `ConclusionState`, not a lesser
`SUPPORTED`. The vocabulary is non-ordered and comparing two members raises,
precisely so that no later stage can sort `INSUFFICIENT` below `SUPPORTED` and
render it as a low reading.

### 2.2 What it must state

- **what information is missing** — specifically, not "more evidence";
- **which evidence was reviewed** — an empty list is refused, because otherwise
  the conclusion cannot be told apart from nobody having looked;
- **why no stronger conclusion is supported**;
- **what scope remains unresolved**;
- **whether more evidence or adjudication is required**.

### 2.3 What it may never be rendered as

> low risk · no risk · not risky · risk-free · no effect · without effect ·
> safe · safely · reassuring · normal result · nothing to worry · no concern ·
> no action needed · negative evidence · rules out · ruled out · excludes risk

Both the conclusion text and the insufficiency statement itself are screened
against this list. The screen is on the *prose*, not only the vocabulary,
because the vocabulary can be respected perfectly while the sentence beside it
says "so this is probably fine" — and a reader takes away the sentence.

### 2.4 Unknown provenance stays visible

An unknown source version, an unstated origin, or evidence from a quarantined
build are **facts about the evidence**, and they remain in the record. They are
not folded into a confidence label — there is no confidence label, and adding
one would be the mechanism by which they disappeared.

This matters for the current corpus specifically: of 1,794 evidence records,
1,542 have no recoverable source version and 1,662 state no origin. A protocol
that let those be summarised as "lower confidence" would convert a large,
visible provenance problem into a small, invisible number.

---

## 3. Worked distinctions

| Situation | Correct | Wrong |
|---|---|---|
| Two guidelines describe opposite effect directions | `CONFLICTING`, both retained, adjudication required | Take the newer one |
| One guideline supports it, one older record contradicts | `SUPPORTED` or `CONFLICTING` with the contradiction assessed | Exclude the older record |
| No record addresses the asked phenotype scope | `INSUFFICIENT` naming the unaddressed scope | `NOT_APPLICABLE`, or a scope-widened `SUPPORTED` |
| The only record has no recoverable version | Cite it, record `UNKNOWN_LEGACY`, argue in the rationale | Exclude it as unversioned |
| Evidence exists but the question is about a different drug | `OUT_OF_SCOPE` | `INSUFFICIENT` |
| A source's `significance` says "yes" and nothing else does | `INSUFFICIENT`, explaining the flag is not an argument | `SUPPORTED` citing the flag |
