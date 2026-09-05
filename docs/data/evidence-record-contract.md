# Evidence record contract (WP-08)

An evidence record is **one statement a source made**, stored with enough
provenance to find it again in the bytes it came from.

It is not a curation, not a rule, not an assessment, and not a claim by this
project that the statement is correct. Everything this project once concluded
about the science lives outside the evidence store, as an unreviewed proposal
(see [wp08-legacy-curation-extraction.md](../migration/wp08-legacy-curation-extraction.md)).

Published schema: [`schemas/evidence-record.schema.json`](../../schemas/evidence-record.schema.json).

---

## 1. The two layers, and why the boundary runs where it does

A record has two parts that must never merge.

| Part | Owner | Rule |
| --- | --- | --- |
| `raw_source_payload` | the source | Stored unchanged. Never edited, translated, summarised or grammar-repaired. |
| `normalized_metadata` | this project | Structural notes only. No scientific conclusion, enforced at construction. |

`PROHIBITED_METADATA_FIELDS` names eighteen field names — `risk_level`,
`demo_risk_level`, `plain_language_mvp`, `evidence_strength`,
`effect_direction`, `usable_for_mvp` and the rest. They are refused in
`normalized_metadata`, recursively, at any depth, when the record is
constructed. `find_prohibited_fields` reports a **dotted path** rather than a
bare name, so a nested offender says where to look.

**The scan does not run over `raw_source_payload`.** This is deliberate and it
is the point of the namespace. A source-owned field called `recommendation` is
the source's word, not a recommendation made here. Running a recursive
forbidden-key scan over an opaque source payload would reject real records for
using ordinary English, and would delete the evidence this project exists to
cite.

Source wording that reads like clinical advice is stored **verbatim**:

> Avoid clopidogrel in CYP2C19 poor metabolizers; consider prasugrel or
> ticagrelor at standard dose.

That is a quotation with a locator, a field name and two hashes. What is
forbidden is the same sentence appearing as *this project's* summary, risk
level or recommendation. Censoring the source would make the citation false;
promoting the source into a project claim would make the project dishonest.
Both are refused, in opposite directions.

## 2. Text fragments

Fields are kept apart rather than concatenated. A summary and a recommendation
joined into one blob cannot afterwards be attributed to the field each came
from, and a citation that cannot say which field it quotes is not a citation.

Each fragment carries two digests:

- `text_hash` — over whitespace-collapsed text, so two copies differing only in
  incidental spacing hash alike.
- `exact_text_hash` — over the bytes as written.

A fragment with no text is refused: nothing quoted is not a quotation, and it
would hash identically to every other empty one.

## 3. Record type comes from the object class, never from the container

The source's `pair` endpoint takes a container name as a **request parameter**.
One container returns several kinds of record: `variantAnnotation` alone
returns `Variant Phenotype Annotation` (1,937), `Variant Drug Annotation`
(1,285) and `Variant Functional Assay Annotation` (126). A type read off the
container would mislabel two of those three.

So the type is read from the record's own declared `objCls`, and the container
it was requested under is kept beside it in `requested_container`.

### `label` versus `DrugLabel`

29 records reached WP-08 under two container spellings. Three findings are
recorded as data in `CONTAINER_FINDINGS`:

1. The payloads returned under both spellings compare equal.
2. Both declare `objCls: "Label Annotation"`.
3. The OpenAPI document lists `label` and does not list `DrugLabel`.

That is strong. It is not proof, and the difference between strong and proven
is exactly what a review is for. So:

- both spellings map to `DRUG_LABEL_ANNOTATION`;
- the mapping status is **`PENDING_REVIEW`**, not `CONFIRMED`;
- the original spelling of each is retained rather than normalised away;
- the 28 affected records in the real build are **not production eligible**.

Nothing here decides the question. It records what was observed and leaves the
decision to someone who can make it.

## 4. Version: what the source said, or an honest absence

`source_record_version` is nullable, and a companion
`source_record_version_status` carries the reason. Only `KNOWN` may hold a
value — a database constraint, not a convention in a service.

| Status | Meaning |
| --- | --- |
| `KNOWN` | The source stated this version. |
| `SOURCE_UNVERSIONED` | The source publishes no versions at all. |
| `UNKNOWN_LEGACY` | A version existed and this import cannot recover it. |
| `MISSING` | The record should carry one and does not. |
| `INVALID` | Something is there and it is not a version. |

`SOURCE_UNVERSIONED` and `UNKNOWN_LEGACY` are different facts and are not
merged. The first is citable; the second is not.

**No `v1` is ever written.** A fabricated version string would make every
citation of that record a statement about a version that never existed. In the
real quarantined build: 234 `KNOWN`, 1,542 `UNKNOWN_LEGACY`, 18 `MISSING`.

## 5. Origin: who asserted it, or `UNKNOWN`

Two different sources are recorded per record, because they answer two
different questions.

- **`provider_source_key`** — where the bytes were retrieved from. Always
  known, because it is how they arrived. Here: `clinpgx.api`.
- **`origin_source_key`** — who the record itself says asserted it. Present
  **exactly when** `origin_status` is `STATED_BY_SOURCE`, and absent under
  every other status.

CPIC is never assigned because a record looks pharmacogenomic. Most of this
corpus *is* pharmacogenomic and states no origin: 1,662 records are
`NOT_STATED_BY_SOURCE`, and not one of them carries an origin key. Where the
source did state an origin, the raw value it wrote is kept beside the resolved
key, including when it resolves to nothing registered.

Real distribution of stated origins: `dpwg.knmp` 77, `cpic.publications` 44,
`rnpgx` 6, `cpnds` 3, `ausnz` 1, `aha` 1.

## 6. Identity

`source_record_id` keeps the source's own spelling and records its type. An
integer identity is an identity: `981351915` is reported as
`source_record_id: "981351915"` with `source_record_id_raw_type: "int"`.
Reporting it as anonymous because the domain column is a string would be a
false statement about the source. `bool` is refused (Python's `True` is an
`int` and would become the id `"1"`); `float` is refused rather than rounded.

The **natural key** has five parts joined by `|`:

```
PGX-DATA-20260830-900|clinpgx.api|GUIDELINE_ANNOTATION|PA166104948|0
dataset               provider     record type          source id   version part
```

Namespaced by dataset and provider, so one source's identifier cannot collide
with another's.

`record_uuid` is **allocated, never derived**. There is no UUID5 over the
content. A content-derived identity would make a corrected record a different
record, and would let an importer mint identities silently. See
[evidence-import-policy.md](evidence-import-policy.md) §3.

## 7. Entity links

A record naming three genes produces **three links**, not three copies of the
record. Duplicating a source record once per gene/drug pair to fit scalar
`gene_id` and `drug_id` columns would make one statement look like several and
every count over it wrong.

Each link records how the record came to name that entity:

| Role | Meaning |
| --- | --- |
| `RELATED_ENTITY` | The source listed it, in a field the link names. |
| `QUERY_CONTEXT` | It appears because the record was fetched under that entity's query. |
| `MENTIONED_IN_TEXT` | It appears in source wording only. |

A gene the source listed and a gene that only appears because of how the record
was retrieved are different facts, and collapsing them would let a query
artefact read as a source claim.

In the real build: 1,946 gene links and 2,338 drug links over 1,794 records;
130 records name more than one gene and 210 more than one drug.

## 8. Publications

A publication is addressed by **`pmid:<digits>` or `doi:<doi>`, and by nothing
else**. Identity prefers PMID, then DOI, and is never derived from a title: two
records printing one title have not been shown to cite one article, and fuzzy
title similarity would silently merge two papers into one citation.

No network lookup enriches a missing publication. A reference this project
cannot identify from the bytes it was given stays unidentified and says so;
1,797 of 1,952 references carry an identity.

Parallel columns in the legacy CSVs (titles, PMIDs, DOIs, years as four
independently separated strings) are checked for equal length. When they
disagree, every value is kept in its own column-scoped reference and **nothing
is paired by position**, because pairing the third title with the third PMID
across unequal lists invents a citation.

Unusable identifiers are **kept beside the problem** rather than deleted:
`validate_pmid`, `normalize_doi` and `validate_year` each return
`(value, problem)`. An implausible year is reported and still stored, because
the source printed it.

## 9. Five hashes, five meanings

One overloaded `raw_hash` would make every one of these unanswerable.

| Hash | Answers |
| --- | --- |
| `artifact_sha256` | Are these the same raw bytes the snapshot recorded? |
| `source_payload_hash` | Is this the same source record that was extracted? |
| `evidence_content_hash` | Is this the same rendering of it by this project? |
| build `content_hash` | Is this the same evidence build? |
| `snapshot_manifest_hash` | Which acquisition is all of this rooted in? |

`evidence_content_hash` excludes the allocated UUID, so two projects that
allocated different identities still agree on what the record says.

## 10. Production eligibility

A record is eligible only when **all** of these hold:

- its record-type mapping is `CONFIRMED`;
- its version status is `KNOWN` or `SOURCE_UNVERSIONED`;
- its origin status is `STATED_BY_SOURCE`;
- it carries no blocking issue.

A build-level quarantine overrides every record-level answer. In the real
build, 132 records are complete in themselves and **0** are publishable,
because the build is quarantined. `pgx-evidence trace` prints both lines
separately for exactly this reason.
