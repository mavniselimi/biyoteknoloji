# Legacy curation extraction (WP-08)

Before WP-08 this project had reached conclusions about the science: risk
levels, patient-facing sentences in Turkish, effect directions, an
MVP-usability flag. Those conclusions are **not evidence** and must not enter
the evidence store. They are also not worthless — someone did the work — so
they are recovered, labelled, and left outside the store for review.

Output: `data/migration/wp08/draft-curation-proposals.ndjson`
Schema: [`schemas/draft-curation-proposal.schema.json`](../../schemas/draft-curation-proposal.schema.json)

---

## 1. What a proposal is not

Every row carries, immutably:

```
status    UNREVIEWED_LEGACY_MIGRATION_CANDIDATE
warnings  NOT_EVIDENCE, NOT_SCIENTIFICALLY_REVIEWED, NOT_EXECUTABLE,
          DO_NOT_USE_FOR_ASSESSMENT
```

The constructor refuses any other status and refuses trimmed warnings. The
published schema fixes both with `const` and a four-item `enum`, so a file that
merely hand-edited them into something friendlier does not validate.

No `CuratedInterpretation` row is created. No `created_by`, no reviewer name,
no approval timestamp appears anywhere — a proposal with an author would be
asserting that somebody reviewed it, and nobody has.

## 2. Legacy Python is parsed, never executed

`MANUAL_EFFECT_HINTS` lives in `clean_mvp_seed_dataset.py`, a script that
**writes files at import time**. Importing it to read one constant would run
every top-level statement in it, including its own file writing — a migration
that rewrote its own inputs while reading them.

So the file is parsed to an AST, the one assignment is located, and its value
is evaluated with `ast.literal_eval`, which evaluates literals and nothing
else: no calls, no attribute access, no imports. A test asserts that
`exec`, `eval`, `compile`, `import_module`, `__import__`, `run_path` and
`spec_from_file_location` appear nowhere in the module, and that
`clean_mvp_seed_dataset` is never imported.

The module also opens nothing for writing. The CLI writes the artifact; the
extractor only reads.

## 3. Linking is a lookup, not a guess

A proposal is attached to the evidence it would be about using an identifier
**the source itself published** — or it stays unattached and says so.

The legacy CSVs and the evidence store spell a record's identity differently. A
variant annotation's `id` is the numeric one the source returns (`376523711`),
and that is what the evidence record is keyed on; the legacy flattening wrote
the `accessionId` (`PA166338861`) into its `annotation_id` column instead.

Both are fields the source published, so matching on either is a lookup. Naive
matching on the numeric id alone linked **0 of 1,559** proposals. Indexing
evidence records by both source-declared identifiers links **1,526**.

The remaining 33 are reported unlinked, each with a `linkage_note`:

- 11 rows from `MANUAL_EFFECT_HINTS`, which is keyed by gene and drug rather
  than by a source record;
- 22 rows whose `annotation_id` is not a `PA` accession.

None of them is attached to a plausible neighbour. An unlinked proposal is a
smaller loss than a wrong link, because a wrong link would later look like
evidence that a source said something it did not.

## 4. What was recovered

1,559 proposals, from three legacy files. Field categories by occurrence:

| Field | Occurrences |
| --- | ---: |
| `usable_for_mvp` | 3,120 |
| `demo_risk_level` | 3,084 |
| `plain_language_mvp` | 3,084 |
| `evidence_strength` | 3,084 |
| `risk_meaning` | 3,084 |
| `normalized_phenotype_group` | 3,084 |
| `drug_behavior_hint` | 3,084 |
| `effect_direction` | 3,084 |
| `evidence_tier` | 36 |
| `manual_*` (six fields) | 11 each |

Every one of those field names is on `PROHIBITED_METADATA_FIELDS`. That is the
point: this file holds exactly what the evidence store refuses.

A representative row's recovered values:

```json
{
  "demo_risk_level": "high",
  "drug_behavior_hint": "prodrug_activation",
  "effect_direction": "decreased_activation",
  "evidence_strength": "high_guideline_supported",
  "normalized_phenotype_group": "other",
  "plain_language_mvp": "CYP2C19 aktivitesi düşük olduğunda clopidogrel aktif metabolite daha az dönüşebilir; bu durum antiplatelet yanıtın azalması açısından dikkat gerektirir.",
  "risk_meaning": "reduced_response_attention",
  "usable_for_mvp": "yes"
}
```

## 5. Provenance of a proposal

Each carries at least one origin — relative path, file digest, and a row or
line number. A proposal that cannot say which file and row it came from is an
assertion with no provenance, and the constructor refuses it. The file digest
lets a later reader tell whether the legacy file has changed since.

Extraction is deterministic: two runs produce the same content hash. The CLI
refuses to overwrite an existing artifact; a second run goes elsewhere and is
compared.

## 6. Where this sits in the layering

The brief describes four layers. WP-08 implements **1 to 3**, and layer 3 only
as an unreviewed migration artifact outside the evidence store.

| Layer | | Status |
| --- | --- | --- |
| 1 | raw source bytes | sealed in WP-06 |
| 2 | normalized evidence records | this work package |
| 3 | draft curation candidates | this file, unreviewed, outside the store |
| 4 | reviewed curation, rules, assessment | **not started** |

The curation protocol that would turn a proposal into a `CuratedInterpretation`
belongs to WP-09. Nothing here begins it.

## 7. Boundary check

A WP-02 test asserts that no V2 module reads the legacy seed data, protecting
the rule *"the 3,084 legacy rule rows must not be imported into the database"*.

`pgx/evidence/draft_curation.py` reads those files, so it is added to that
test's narrow exemption list — and the companion test that applies to **every**
exempt module still holds for it unchanged: it opens nothing for writing,
constructs no domain record, and names no repository, unit of work or ORM
type. The rule being protected was never "do not open these files"; it was "do
not let 3,084 unreviewed legacy rows become scientific content", and that rule
is intact.
