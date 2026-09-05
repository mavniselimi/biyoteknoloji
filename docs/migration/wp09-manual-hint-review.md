# Manual hint review (WP-09)

| Field | Value |
|---|---|
| Document ID | `DOC-MIG-009` |
| Inventory version | `pgx-curation-legacy-review/1` |
| Artifact | [`data/curation/protocol-v1/legacy-hint-review-inventory.json`](../../data/curation/protocol-v1/legacy-hint-review-inventory.json) |
| Proposals accounted for | **1,559** |
| Reviewed | **0** |

WP-08 recovered 1,559 conclusions this project had reached before any review
protocol existed. WP-09 turns them into a **review queue** — not into
curations, and not into evidence.

---

## 1. What these are

Historical project interpretations, recovered from three legacy files:

| Source | Rows |
|---|---:|
| `clinpgx_mvp_seed/phenotype_effect_rules.csv` | 3,084 field occurrences |
| `clinpgx_mvp_seed/drug_gene_guidelines.csv` | 36 |
| `clean_mvp_seed_dataset.py` (`MANUAL_EFFECT_HINTS`) | 11 |

The values they carry are exactly what an evidence record refuses and what a
curation record refuses:

| Field | Occurrences |
|---|---:|
| `usable_for_mvp` | 1,548 |
| `demo_risk_level` | 1,512 |
| `plain_language_mvp` | 1,512 |
| `evidence_strength` | 1,512 |
| `risk_meaning` | 1,512 |
| `normalized_phenotype_group` | 1,512 |
| `drug_behavior_hint` | 1,512 |
| `effect_direction` | 1,512 |
| `evidence_tier` | 36 |
| `manual_*` (six fields) | 11 each |

Every one of those names is on `PROHIBITED_CURATION_FIELDS`. A test asserts
that the curation prohibition is a **superset** of WP-08's evidence
prohibition: a name refused inside an evidence record must not become
admissible one stage later, where it would look like a reviewed conclusion
rather than a leftover.

## 2. What the inventory preserves

Per proposal, unchanged:

- proposal id and subject;
- legacy origin — relative path, file digest, and row or line number;
- linked evidence record natural keys and UUIDs;
- the legacy values themselves, in full;
- the four WP-08 warnings (`NOT_EVIDENCE`, `NOT_SCIENTIFICALLY_REVIEWED`,
  `NOT_EXECUTABLE`, `DO_NOT_USE_FOR_ASSESSMENT`);
- linkage status and, where unlinked, the note saying why;
- review state.

The legacy values are **retained rather than summarised**. The point of the
review is for a scientist to see exactly what the project previously claimed,
and a summary would decide in advance which parts mattered.

## 3. Accounting

Every proposal in the file becomes an entry, in the file's own order. None is
filtered out — a proposal that is unlinked, or whose values look unusable, is
exactly the kind a reviewer needs to see.

| Measure | Value |
|---|---:|
| Proposals | 1,559 |
| Linked to evidence | 1,526 |
| Unlinked (each with a note) | 33 |
| Reviewed | **0** |

The 33 unlinked are the 11 `MANUAL_EFFECT_HINTS` rows (keyed by gene and drug
rather than by a source record) and 22 rows whose `annotation_id` is not a `PA`
accession. They stay visible; none is attached to a plausible neighbour.

The inventory records the source file's SHA-256 so a later reader can tell
whether the queue was built from the file in front of them, and regenerating it
produces the same content hash.

## 4. Review states

| State | May this package assign it | Requires |
|---|:-:|---|
| `NOT_REVIEWED` | yes | — |
| `SELECTED_FOR_EXERCISE` | yes | Scheduling, not a review outcome |
| `UNDER_REVIEW` | no | A named human |
| `ACCEPTED_AS_DRAFT_INPUT` | no | A named human |
| `REJECTED_AS_DRAFT_INPUT` | no | A named human |
| `NEEDS_MORE_EVIDENCE` | no | A named human |

`LegacyProposalEntry` refuses the last three without a named reviewer, so in
practice this package can only ever produce the first two — which is the point.
All 1,559 are currently `NOT_REVIEWED`.

**`SELECTED_FOR_EXERCISE` is not a review.** It means a human is being asked to
look at this one. Three proposals carry it, being those linked to the exercise
cases.

## 5. What a legacy value may never become

- It may **not** be copied into a completed curation conclusion. The record's
  prohibited-field scan is recursive and covers the question, conclusion text,
  source-reported values, rationale and insufficiency statement.
- It may **not** be shown to a curator during initial evidence review. Exercise
  cases are blinded (see
  [inter-curator-exercise.md](../scientific/inter-curator-exercise.md) §4).
- It may **not** be accepted or rejected by a program. Both states require a
  name.

## 6. Reviewing one, when a human does

1. Read the linked evidence records first, without the hint.
2. Form a conclusion under the protocol, with a rationale.
3. Then read the legacy value.
4. Record `ACCEPTED_AS_DRAFT_INPUT` (the hint agrees and may seed a draft),
   `REJECTED_AS_DRAFT_INPUT` (it does not follow from the evidence), or
   `NEEDS_MORE_EVIDENCE`, with your name and a note.
5. Accepting a hint as a **draft input** is not curating it. It becomes a draft
   record that still requires a full rationale and an independent reviewer.

There is no path in which a legacy value becomes a `CURATED` conclusion without
someone writing the argument for it from the evidence.

## 7. Boundary note

`pgx/curation/legacy_review.py` reads the WP-08 proposal artifact, which is
this project's own output rather than the legacy seed files. The WP-02
dependency-boundary test that governs reading legacy seed data is therefore
unaffected: `pgx/evidence/draft_curation.py` remains the only exempted reader,
and this module reads what that one produced.
