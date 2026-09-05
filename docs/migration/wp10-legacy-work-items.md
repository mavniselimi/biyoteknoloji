# WP-10 legacy work-item migration

| Field | Value |
|---|---|
| Document ID | `DOC-MIG-010` |
| Work package | WP-10 — Curation Workflow and Approval Governance |
| Input | `data/migration/wp08/draft-curation-proposals.ndjson`, 1,559 rows |
| Output | `data/migration/wp10/`, six files |
| Result | **1,559 RAW work items. No revision, no reviewer, no approval, no `CuratedInterpretation`.** |

---

## 1. What was migrated, and what it is not

WP-08 pulled the old project's interpretations out of the evidence store,
where they did not belong, into `draft-curation-proposals.ndjson`. Those 1,559
rows carry exactly the fields the evidence store refuses by name —
`demo_risk_level`, `plain_language_mvp`, `evidence_strength`,
`effect_direction`, and the rest. Nobody reviewed them. They are not evidence
and they are not conclusions.

This migration gives each of them a place in the workflow: **one question on a
queue**. Not an answer.

An import that quietly turned 1,559 unreviewed values into 1,559 conclusions
would undo WP-08 while looking like progress. Everything below is arranged so
that cannot happen, and so that a reader can check it did not.

## 2. The counts

| Count | Value |
|---|---|
| Work items created | 1,559 |
| `RAW` | 1,559 |
| `UNDER_REVIEW` | 0 |
| `CURATED` | 0 |
| `REJECTED` | 0 |
| Tagged `LEGACY_MIGRATION` | 1,559 |
| Linked to at least one evidence record | 1,526 |
| Unlinked, each with a stated reason | 33 |
| Revisions created | 0 |
| Reviewers recorded | 0 |
| Approvals recorded | 0 |
| `CuratedInterpretation` rows created | 0 |
| Role assignments created | 0 |

The counts are computed from what was built, never asserted. `assert_invariants`
runs against the constructed objects before anything is written, so a report
claiming 1,559 while 1,558 work items exist is not producible.

The linkage split is WP-08's, carried across unchanged: 1,526 proposals name a
source record id that an evidence record in this build also carries; 33 do not.
Eleven of those came from `MANUAL_EFFECT_HINTS`, which is keyed by gene and drug
rather than by a source record, and twenty-two carry an `annotation_id` that is
not a `PA` accession. **None of them was attached to a plausible neighbour.** An
unlinked work item is a smaller loss than a wrong link, because a wrong link
would later look like evidence that a source said something it did not.

## 3. Legacy values are namespaced

Every legacy field is stored under a `legacy.` prefix:

```json
"legacy_values": {
  "legacy.demo_risk_level": "high",
  "legacy.drug_behavior_hint": "prodrug_activation",
  "legacy.effect_direction": "decreased_activation",
  "legacy.evidence_strength": "high_guideline_supported",
  "legacy.plain_language_mvp": "CYP2C19 aktivitesi düşük olduğunda …",
  "legacy.risk_meaning": "reduced_response_attention",
  "legacy.usable_for_mvp": "yes"
}
```

A reader who sees `legacy.demo_risk_level` cannot mistake it for a curated
field, and a query for curated content cannot match one. The prefix is enforced
by `namespace_legacy_values` at build time and by
`trg_curation_work_items_legacy_namespaced` in the database — a trigger rather
than a check constraint, because PostgreSQL refuses a subquery inside `CHECK`
and "every key of this document is namespaced" cannot be written without one.

A legacy field that would *assert a review* — `reviewed_by`, `approved_by`,
`rationale`, `status` and six others — is **refused outright** rather than
prefixed. The problem with those is not their name.

## 4. P1 candidate data is excluded by name

`mvp_candidate_drug_gene_edges` was excluded from P0 at canonicalisation
(8,182 records, counted and not imported). It is excluded again here, by an
explicit refusal in `PROHIBITED_LEGACY_SOURCES` rather than by not happening to
look. A future change that starts feeding it in fails loudly instead of quietly
onboarding P1 data into P0.

The match is on the distinctive stem rather than a full path: a path would be
defeated by the file moving.

## 5. Identity is allocated explicitly and does not move

A work-item id is derived from its proposal id by digest:

```
CWI-LEGACY-<first 16 hex of sha256({proposal_id, allocation_version})>
```

and recorded in `legacy-work-item-allocation.json`, one entry per work item,
with its question id, canonical keys and the proposal's own content hash.

Derived rather than counted, because a counter would renumber everything if one
proposal were added or removed, and every audit event pointing at an old number
would silently point somewhere else. Recorded as well as derived, so the
derivation can change in future without existing ids moving.

## 6. Regeneration is byte-identical

The import timestamp is derived from the input file's content hash, not from
the clock:

```
imported_at = 2026-01-01T00:00:00Z + (first 8 hex of the input digest mod 86400) seconds
```

So re-running `scripts/build_wp10_migration.py` over the same input produces
identical bytes, and a change in the output means a change in the data. A
wall-clock stamp would make "did the data change" unanswerable without diffing
every row.

Verified by re-running the build and comparing checksums, and asserted by a
test that rebuilds in memory and compares to the file on disk.

## 7. The files

| File | What it holds |
|---|---|
| `manifest.json` | counts, digests, the excluded sources, and the invariants asserted |
| `legacy-work-item-allocation.json` | the id allocated to each proposal, 1,559 entries |
| `legacy-work-items.ndjson` | 1,559 RAW work items |
| `legacy-work-item-evidence-links.ndjson` | 1,526 links, every one marked `reviewed: false` |
| `migration-issues.ndjson` | 33 unlinked proposals, each with a reason and a resolution |
| `checksums.sha256` | so a reader can verify the set without the build script |

Manifest content hash:
`sha256:5296fcc10794718ced36691c18c195460ccdacf15ae1618d624ded0e00067ee4`
Input content hash:
`sha256:c8b5460f254756eac422c6d78940cd376913389c28d676eafce9892ccfb36c7a`

## 8. Every link is unreviewed

`reviewed` is `false` on every one of the 1,526 links, and the database column
defaults to `false`. A link records which evidence an old interpretation was
*about*; nobody has confirmed that the evidence supports anything, and a
default of `true` would assert that they had.

A curator selects evidence when they write a revision. These links are a
starting point for that, not a substitute for it.

## 9. Loaded into real PostgreSQL

All 1,559 rows were loaded into a database holding the 0001–0007 schema. Every
count that must be zero was zero, the namespacing trigger admitted all of them,
and the downgrade was permitted — because rows that assert nothing are rows a
downgrade may drop. The transcript is in
`docs/evidence/wp10-schema-validation.md` §4.
