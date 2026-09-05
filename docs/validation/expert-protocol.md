# Blind Expert Validation Protocol

| Field | Value |
|---|---|
| Document ID | `DOC-EP-022` |
| Document version | `0.1.0-draft` |
| Status | **DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW** |
| Work package | WP-22 - Blind Expert Validation Protocol and Review Module |
| Machine-readable counterpart | `pgx/expert_review/protocol.py`, `data/expert-review/wp22-protocol-manifest.json` |
| Architecture source | `architecture.md` sections 11.2, 12.1, 12.3, 13, 17 |
| Approved by | *(not approved - section 15 is unsigned)* |

> **This protocol is not approved.** No named person has reviewed or signed
> it, no expert has been assigned a case, and no review has been conducted
> under it. The software that would run it exists; running it requires people
> this document does not have.

---

## 1. Purpose and scope

This protocol governs how a named clinical or pharmacogenetic expert reviews
one validation case *without first seeing what the system produced*, records
what they expected, and only afterwards compares.

**Non-clinical scope.** A review conducted under this protocol produces
evidence about a software system's outputs. It is not a clinical consultation,
does not concern any real patient, and produces no treatment recommendation.
Every case is synthetic or published-literature-derived; no reviewer is asked
what should be done for a person.

**Why blind-first.** A reviewer who has already seen the system's answer
cannot un-see it. Asked afterwards what they would have expected, they produce
a judgement contaminated by the answer - and the contamination is invisible in
the result. Recording the expectation first is the only measure that
distinguishes agreement from anchoring, and it cannot be applied retroactively.

## 2. Reviewer eligibility

A reviewer must:

- hold a relevant clinical or pharmacogenetic qualification and current
  practice or research standing;
- be independent of the rule authoring for the case under review;
- not have authored, curated, reviewed or approved any rule in the pinned
  ruleset that could fire for the case;
- not have seen the case payload or any system output for it before
  assignment;
- hold the `EXPERT_REVIEWER` role and no other role in the same session.

`ADMIN` does not confer reviewer standing. An administrator's action must
remain distinguishable from an independent expert's opinion, and a role
hierarchy would make it not.

## 3. Conflict-of-interest declaration

Before a first assignment, a reviewer declares in writing:

- any role in authoring, curating or approving rules in this system;
- any financial interest in the project or in a named medication that appears
  in the case set;
- any prior sight of the validation case material;
- any supervisory relationship with the development team.

A declared conflict on a specific case removes that case from the reviewer's
assignment pool. A conflict discovered mid-review invalidates that review
(`REVIEWER_CONFLICT_DECLARED`); the records are retained, and the case may be
re-assigned to a different reviewer as a new review.

## 4. Assignment

One reviewer, one case, one release, one protocol version. The assignment
pins, at creation: case identifier and role, reviewer actor and role, protocol
version and hash, release public ID and manifest hash, software version and
hash, dataset and ruleset identities and hashes, and the case-manifest hash.

Only an `EXPERT_HOLDOUT` case may be assigned. `DEVELOPMENT` cases shaped the
software; `INTERNAL_HOLDOUT` cases are withheld under a different protocol for
a different measurement. Assigning either would spend a case on a purpose it
was not reserved for.

Payload access is granted by an assignment-scoped permit binding the
assignment, the case, the reviewer, the protocol hash, the release hash and
the current stage. A reviewer cannot read a case they are not assigned, and a
completed review cannot re-open its material.

## 5. What is visible while blinded

The assigned reviewer may see:

- the permitted case input material for their assigned case;
- the case metadata WP-18 publishes (role, provenance summary, classification);
- the pinned release identity;
- the structured expected-response form;
- this protocol.

The reviewer must **not** see, in any surface - rendered page, API response,
hidden form field, data attribute, log line or error message:

- the calculated attention level;
- the calculated coverage status or reason;
- the firing rule;
- any report text, finding or evidence reference;
- the output hash;
- any comparison or agreement indication.

A hidden element is disclosure. The software enforces this structurally: the
pre-reveal view has no field in which a result could sit, and the result is
never fetched before a reveal.

## 6. The structured expected response

The reviewer records:

| Field | Required | Vocabulary |
|---|---|---|
| Expected attention level | yes | the system's attention vocabulary |
| Expected coverage status | yes | the system's coverage vocabulary |
| Expected coverage reason | no | the system's coverage reason vocabulary |
| Expected firing rule ID | no | a rule identifier |
| Traceable evidence required | yes | boolean |
| Rationale codes | no | `GUIDELINE_DIRECT`, `GUIDELINE_EXTRAPOLATED`, `PHENOTYPE_DETERMINATIVE`, `INSUFFICIENT_INPUT`, `NO_APPLICABLE_RULE`, `SOURCE_CONFLICT`, `EVIDENCE_INSUFFICIENT`, `OUT_OF_SCOPE` |
| Reviewer note | no | bounded free text, no clinical directive |

The expected response **may not** contain a treatment recommendation, a dose
or dose adjustment, a preferred medication, a patient narrative or any
free-form clinical directive. The software refuses a response containing one.

On submission the response is timestamped **by the server**, hashed, and
locked. A client-supplied timestamp is refused: a reviewer able to set their
own would be able to backdate a prediction.

## 7. Reveal

Reveal is permitted only when an expected response is locked, and happens once.

Reveal records the exact expectation revision hash it pinned, together with
the release, case-manifest and output hashes in force. Anything appended after
this moment - however sincere - is not what the reviewer predicted, and the
metrics that consume the expectation consume the pinned revision.

If the release, case manifest or protocol has changed since assignment, reveal
is refused and the review is invalidated rather than continued.

## 8. Completion

After reveal the reviewer records exactly one decision:

| Decision | Meaning |
|---|---|
| `AGREE` | the system's output matches what the reviewer expected in every respect they considered material |
| `PARTIAL` | the output matches in some material respects and not others |
| `DISAGREE` | the output does not match what the reviewer expected |

`PARTIAL` is a third answer, not a midpoint. These values are never ordered,
summed or averaged; a "mean agreement score" is not a quantity this protocol
produces.

The reviewer may add a bounded note explaining the decision.

## 9. Optional rating dimensions

Optionally, on a 1-5 scale, per dimension:

| Dimension | Question |
|---|---|
| `CLARITY` | is the output's meaning unambiguous to a reading clinician? |
| `TRACEABILITY` | can each finding be followed to its evidence? |
| `CLINICAL_USEFULNESS` | would this output help a clinician decide what to look at next? |
| `SAFETY_FRAMING` | does the output make missing data distinguishable from low risk? |

Ratings are optional. An unrated review is complete; the Likert denominator
counts completed ratings, not completed reviews, so declining to rate does not
register as a low score.

## 10. Corrections

Records are never edited or deleted. A change is an appended correction naming
what it corrects, of what kind, for what reason, by whom, at a server
timestamp, chained to the previous correction.

- A correction **before** reveal may become the revision that reveal pins.
- A correction **after** reveal is annotation only. It is retained, visible to
  an auditor, and cannot change the blinded reference used for metrics.
- No correction may change the case, reviewer, release or protocol identity.
- No correction may backdate itself.

Corrections are restricted material and appear in no public artifact.

## 11. Invalidation, withdrawal and abandonment

A review is invalidated - terminal, records retained - for:

| Reason | Condition |
|---|---|
| `RELEASE_CHANGED` | the pinned release moved during the review |
| `CASE_MANIFEST_CHANGED` | the case manifest hash changed |
| `PROTOCOL_APPROVAL_WITHDRAWN` | approval was withdrawn mid-review |
| `BLINDING_COMPROMISED` | the reviewer saw the result before locking an expectation |
| `REVIEWER_CONFLICT_DECLARED` | a conflict emerged after assignment |
| `ASSIGNMENT_SUPERSEDED` | the assignment was replaced |

A reviewer may withdraw at any point by appending a
`WITHDRAWN_BY_REVIEWER` correction. An abandoned review - assigned, never
completed - remains `ASSIGNED` and contributes to no metric. Neither is
deleted: the fact that a review was attempted and not finished is itself worth
knowing, and a dataset showing only completed reviews would overstate how
readily the material can be reviewed.

## 12. Data access and confidentiality

Case payloads are restricted. A reviewer may read only their assigned case,
only through the assignment-scoped permit, and only while the review is live.
Every attempt - permitted or refused - is recorded in the WP-18 access ledger.

Reviewers must not copy, transcribe, photograph or discuss case material
outside the review interface, and must not discuss a case with another
reviewer before both have completed it.

No case contains real patient, genotype, VCF, EHR or laboratory-record data,
and none may be introduced.

## 13. Audit

Every governed act appends one event carrying: actor and role, identity
assurance, UTC timestamp, action, previous and new state, outcome code,
protocol/release/case-manifest hashes, and the hashes of records produced.
Each event names the hash of the one before it, so editing, deleting or
reordering is detectable.

Audit events carry **hashes and codes, never expert content**. An audit trail
is read by people who are not the reviewer, often before the study is
finished.

The state transition and its audit event are written in one transaction. If
the event cannot be appended, the act is rolled back.

**Identity assurance is currently absent.** Every event records
`actor_authenticated: false`. WP-23 owns authenticated identity; until it
lands, a recorded actor is a claim the server cannot verify, and no review
conducted under these conditions should be presented as attributable.

## 14. Metric eligibility

A review contributes to a metric only if it is `COMPLETED`, its expectation is
the revision the reveal pinned, and its case, role, protocol hash and all
release/dataset/ruleset/software/case-manifest hashes match the benchmark's.

A record that disagrees on any pin **refuses the benchmark input** rather than
being skipped. A silently dropped record makes the denominator describe a
different set than the report names.

The locked pre-reveal expectation supplies WP-21's reference judgment. The
post-reveal decision supplies `PGX-VAL-011` and the ratings supply
`PGX-VAL-012`. These are different inputs and are never interchanged.

## 15. Limitations

- A blind review measures whether one expert's expectation matched one
  system output for one case under one release. It is not a clinical outcome.
- Expert agreement is not correctness. Two experts may agree with each other
  and both be wrong, and the protocol produces no measure of that.
- The case set is synthetic or literature-derived. Agreement on constructed
  cases does not establish behaviour on real ones.
- The reviewer count needed for a defensible claim is a scientific question
  this document does not settle.
- No number produced under this protocol is clinical validation.

## 16. Sign-off

This protocol takes effect when all four rows below are completed by the named
person. Until then it is a **proposal**, the machine-readable manifest reports
`approved: false`, and every governed operation refuses.

| Role | Name | Affiliation | Decision | Date | Record reference |
|---|---|---|---|---|---|
| Product / technical owner | *(pending)* | | *(pending)* | | |
| Scientific advisor (pharmacogenetics / clinical pharmacology) | *(pending)* | | *(pending)* | | |
| Risk management owner | *(pending)* | | *(pending)* | | |
| Independent reviewer | *(pending)* | | *(pending)* | | |

Each signature names the exact document digest approved. Amending this
document after signature invalidates every existing signature, which is the
correct outcome: an amended protocol has not been approved.

## 17. Change control

Changes to the state machine, the expected-response fields, the decision
vocabulary, the rating dimensions, the correction rules or the metric
eligibility criteria require an Architecture Decision Record under
`docs/architecture/decisions/` (`architecture.md` section 23) and re-approval
of section 16.
