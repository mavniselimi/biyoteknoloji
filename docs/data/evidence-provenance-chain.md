# Evidence provenance chain (WP-08)

Every evidence record can be walked back to the bytes a source published, and
the walk can be **re-executed** rather than merely displayed. This document
describes the chain, then shows one real trace end to end.

---

## 1. The chain

```
acquisition                    WP-06
  raw artifact file            responses/pair_probe_raw.json
    artifact_sha256            sha256:aeee3186...
  snapshot manifest            sha256:3b79e3bf...   state: QUARANTINED
        |
        v
locator                        WP-08
  artifact_path                relative, never absolute
  json_pointer  XOR  csv_row_number
  requested_container          the parameter it was fetched under
        |
        v
source record                  WP-08
  source_payload_hash          sha256:819d99f4...
        |
        v
evidence record                WP-08
  natural_key                  dataset|provider|type|source id|version
  record_uuid                  allocated, never derived
  evidence_content_hash        sha256:c8abf558...
        |
        +--> entity links  --> canonical gene / drug   WP-07
        +--> text fragments    source wording, per field
        +--> publications      pmid: or doi:, never a title
        |
        v
evidence build                 WP-08
  content_hash                 sha256:5a58c030...
  lifecycle labels             QUARANTINED, LEGACY_MIGRATION, ...
```

Each arrow is checkable. `verify_trace` re-reads the artifact, re-hashes it,
re-resolves the pointer, re-derives the payload, recomputes the record's
content hash from its stored fields, and cross-checks the canonical build key
on every entity link. A record that verified only against its own summary would
verify against anything.

## 2. Why a record has many locators

A locator is **one place a record was found**, and all of them are kept.

The source's `pair` endpoint answers to several container spellings and returns
overlapping results across queries, so one guideline annotation is genuinely
reachable at seven different pointers. Keeping one and discarding six would
destroy the evidence that the source answers to all of them — which is the
observation behind the `label`/`DrugLabel` finding in
[evidence-record-contract.md](evidence-record-contract.md) §3.

In the real build: 1,794 records, **4,051 locators**, and 1,732 records have
more than one.

A locator addresses a JSON pointer **or** a CSV row, never both and never
neither. This is a database constraint (`ck_evidence_provenance_addresses_one_record`),
and it is what stops the same record being imported once from the raw JSON and
again from the CSV derived from that same JSON.

## 3. When two containers disagree

Two payloads for one source identity are compared **recursively**, not with a
top-level `==`.

| Relation | Meaning | Action |
| --- | --- | --- |
| `IDENTICAL` | The same record twice. | Store once, keep both locators. |
| `PROJECTION` | One is a strict subset of the other, at every depth. | Store the maximal one, keep both locators. |
| `CONFLICT` | They disagree on a value. | **Block.** Emit an import issue, keep both locators, and do not choose. |

The recursion matters. A shallow comparison saw `{'id': 376523711}` against
`{'id': 376523711, 'phenotype': ...}` as a disagreement and reported **82**
variant-annotation groups as conflicts. Re-measured recursively, the answer is
**0**: guideline annotations 132 distinct / 29 projections / 0 conflicts;
variant annotations 1,662 distinct / 82 projections / 0 conflicts.

Lists must match in length element-wise. Padding or truncating would make two
different records agree.

Where a real conflict does occur, nothing picks a winner. Both locators are
preserved, a blocking import issue is emitted, and an OPEN source conflict is
the correct next step — a human's, not this importer's.

## 4. A worked trace, from the real quarantined build

CPIC's clopidogrel/CYP2C19 guideline annotation, `PA166104948`.

```
$ pgx-evidence trace --build data/evidence/PGX-DATA-20260830-900 \
    --natural-key 'PGX-DATA-20260830-900|clinpgx.api|GUIDELINE_ANNOTATION|PA166104948|0' \
    --verify-against-raw data/raw/clinpgx-legacy-v2/PGX-DATA-20260830-900 --text

trace a833a633-b15e-466b-bfd9-678dd918c9e3
  natural key     PGX-DATA-20260830-900|clinpgx.api|GUIDELINE_ANNOTATION|PA166104948|0
  record type     GUIDELINE_ANNOTATION (CONFIRMED)
  retrieved from  clinpgx.api
  asserted by     cpic.publications (STATED_BY_SOURCE)
  source version  0 (KNOWN)
  raw locators    7
    responses/pair_probe_raw.json /CYP2C19::amitriptyline/guidelineAnnotation/22
    responses/pair_probe_raw.json /CYP2C19::citalopram/guidelineAnnotation/22
    responses/pair_probe_raw.json /CYP2C19::clopidogrel/guidelineAnnotation/1
    responses/pair_probe_raw.json /CYP2C19::clopidogrel/pair/GuidelineAnnotation/0
    responses/pair_probe_raw.json /CYP2C19::clopidogrel/pair/guidelineAnnotation/0
    responses/pair_probe_raw.json /CYP2C19::sertraline/guidelineAnnotation/22
    responses/pair_probe_raw.json /CYP2C19::voriconazole/guidelineAnnotation/23
  hashes
    raw artifact     sha256:aeee31863ac82f799b3ee220a893f905554fcd3ddd1d08ff4b78a566447ad2cf
    source payload   sha256:819d99f40b04176b6a7bd31fba3aaa17678f69c88a04857650449a54f8972746
    evidence record  sha256:c8abf55804b3c3e50452673d850f46800d51d56937451aca4eaed700b86638d5
    evidence build   sha256:5a58c030d00dc6495d69c3ff9e1d76c6d6230caf7795871e4dfc4e8774fcb83e
    snapshot         sha256:3b79e3bfdde2de49d5a1a217e56d217455bd0fe9503929293ca95dda485075b7
  entities        8
  publications    3
  text fragments  3
  record complete True
  publishable     no - the build is quarantined
  labels          QUARANTINED, LEGACY_MIGRATION, NOT_CURATED, NOT_EXECUTABLE, NOT_PUBLICATION_ELIGIBLE
  re-derived from data/raw/clinpgx-legacy-v2/PGX-DATA-20260830-900: ok
```

Read that from the bottom up.

- **`re-derived ... ok`** — the artifact was re-read, re-hashed, the pointer
  re-resolved and the payload hash recomputed. This is not the record
  describing itself.
- **`record complete True` beside `publishable no`** — two different
  statements. This record satisfies every eligibility condition on its own, and
  the build it belongs to is quarantined, so it may not be published. Printing
  only the first would read as permission.
- **Seven locators, both container spellings** — `guidelineAnnotation` and
  `GuidelineAnnotation` both returned it. Both survive.
- **`asserted by cpic.publications (STATED_BY_SOURCE)`** — the record itself
  names CPIC. It was not inferred from the record looking like a CPIC
  guideline.
- **Five hashes** — the artifact's bytes, the extracted source record, this
  project's rendering of it, the build, and the acquisition it is rooted in.

The same walk in SQL, against migration 0006's tables loaded with the same
corpus:

```sql
SELECT r.natural_key, sr.source_key AS retrieved_from,
       o.source_key AS asserted_by, r.source_record_version AS version
FROM evidence_records r
JOIN source_registry sr ON sr.id = r.source_registry_id
LEFT JOIN source_registry o ON o.id = r.origin_source_id
WHERE r.source_record_id = 'PA166104948';

 natural_key                                                          | retrieved_from | asserted_by       | version
 PGX-DATA-20260830-900|clinpgx.api|GUIDELINE_ANNOTATION|PA166104948|0 | clinpgx.api    | cpic.publications | 0
```

Its publications, addressed by identity:

```
 identity      | publication_year | title
 pmid:35034351 |             2022 | Clinical Pharmacogenetics Implementation Consortium Guidel...
 pmid:23698643 |             2013 | Clinical Pharmacogenetics Implementation Consortium guidel...
 pmid:21716271 |             2011 | Clinical Pharmacogenetics Implementation Consortium guidel...
```

## 5. Whole-corpus verification

The trace above is one record. The same check runs over all of them:

```
$ pgx-evidence verify --build data/evidence/PGX-DATA-20260830-900 \
    --snapshot data/raw/clinpgx-legacy-v2/PGX-DATA-20260830-900 --trace-limit 0 --text
verify data/evidence/PGX-DATA-20260830-900
  checksums          ok
  files              ok
  published schemas  ok (1794 records)
  traces re-derived  1794 checked, ok
```

## 6. Lookup refuses to hide corruption

`get_by_natural_key` returns one row or raises. Two rows under one key is
corruption — the schema declares that key unique — and returning the first
would answer the caller's question while concealing that the store cannot be
trusted. There is no `LIMIT 1` anywhere in this path.

A publication lookup refuses a title outright rather than doing a best-effort
match, for the reason in §8 of the record contract.
