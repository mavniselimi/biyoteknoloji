# 5. Dataset provenance and the candidate-only DQ decision

Dataset: `PGX-DATA-20260906-001`
(`build_content_hash: sha256:9c0ebc65…d3c0d`,
`dq_report_hash: sha256:bbe4d909…bbefe4`).

## How the data got here

```
manually downloaded guideline document
        │  read by a person, entered by hand
        ▼
capture rows            data/... capture snapshot
        │  manifest hash sha256:4075ce58…8210d4
        ▼
canonical build         PGX-DATA-20260906-001
        │  35 observations, 6 entities (4 drugs, 2 genes)
        ▼
data-quality report     decision.passed = FALSE
        │
        ▼
candidate DQ decision   DQD-2710a01c386e9a1885f62a8e
                        ACCEPTED_FOR_CANDIDATE_USE
                        permits_transition = FALSE
```

Every capture row carries an identifier of the form
`capture:row:CYP2C19|clopidogrel|CYP2C19 intermediate metabolizer|ACS and/or PCI`,
and every rule names the capture rows behind it. The interface shows them.

## The size of it

| | |
|---|---|
| Distinct records | 35 |
| Entities | 6 — `DRUG` 4, `GENE` 2 |
| Provenance links | 6 |
| Duplicate groups | 0 exact, 0 semantic, 0 conflicting-identity |
| Resolution queue | 0 outstanding; 10 resolved |
| Entities with an external identifier | **0** |

That last row is an advisory finding, `ENTITY_WITHOUT_EXTERNAL_ID`: nothing in
this dataset is keyed to RxNorm, ATC, HGNC or any other external vocabulary.
Drugs and genes are identified by the project's own canonical keys. Whether
that is acceptable for a demonstration and unacceptable beyond one is part of
question **Q03**.

## Why the quality gate fails

Two blocking findings:

- **`SNAPSHOT_COMPLETENESS_UNKNOWN`** — the capture snapshot cannot show that
  it captured everything the source contains. Nobody enumerated the source to
  compare against. The gate fails closed: an unanswered question blocks
  exactly as a refused one does.
- **`SOURCE_POLICY_NOT_APPROVED`** — the source registry status, for the
  reasons in section 4, is still `PENDING_REVIEW`.

The gate's own report says what it is: *"A passing gate is a precondition for
a human quality decision, not the decision itself. Nothing here transitions a
dataset."* The dataset's lifecycle state is still `BUILDING`.

## The decision that was recorded instead

`ACCEPTED_FOR_CANDIDATE_USE`, naming both blocking codes as accepted-over, and
keeping `permits_transition = false`.

This is the distinction the whole project rests on, so it is worth stating
flatly: **the dataset was accepted for candidate use by a decision that
explicitly does not permit it to transition.** A reader who collapses those
two into "the data was approved" has misread the record. A reviewer who thinks
the distinction is a fiction — that accepting a dataset over a failed gate is
approval whatever it is called — should say so; that is a legitimate criticism
and question **Q10** has room for it.
