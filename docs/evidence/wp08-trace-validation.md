# WP-08 verification evidence

What was executed, on what, and what it produced. Every command below is
reproducible from a clean checkout with no network access.

## 1. Environment

| Item | Value |
| --- | --- |
| Python | 3.10 (`python3`) |
| Test runner | `python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -t .` |
| PyPI | unreachable. No SQLAlchemy, Alembic, psycopg, pytest, ruff or mypy is installed. |
| Docker | no daemon available |
| PostgreSQL | 16.13 server binaries available; used directly, without Alembic |

`PYTHONDONTWRITEBYTECODE=1` is set for every run, because the working tree does
not permit removing `__pycache__`.

**The migration evidence below is rendered DDL executed on a real PostgreSQL
server. It is not Alembic evidence.** Alembic cannot be installed here, so
`scripts/render_wp08_schema.py` renders `migrations/versions/0006_*.py` to SQL
and that SQL is applied. The migration remains the authority; the renderer is
checked against it by 27 unit tests.

## 2. Test suite

```
$ PYTHONDONTWRITEBYTECODE=1 python3 -W error::ResourceWarning \
    -m unittest discover -s tests -p 'test_*.py' -t .
Ran 2170 tests in 85.815s
OK (skipped=10)
```

194 of those are new in WP-08 (167 under `tests/unit/evidence/`, 27 in
`tests/unit/test_wp08_schema.py`):

| File | Covers |
| --- | --- |
| `tests/unit/evidence/test_source_separation.py` | prohibited fields, the raw namespace, verbatim source wording |
| `tests/unit/evidence/test_traceability.py` | JSON pointers, whole-corpus re-derivation, duplicate-key corruption |
| `tests/unit/evidence/test_identity_and_version.py` | allocation, version honesty, origin honesty, identifier types |
| `tests/unit/evidence/test_record_types_and_publications.py` | object class vs container, `label`/`DrugLabel`, publication identity |
| `tests/unit/evidence/test_extraction.py` | pointers, one record per source record, entity links |
| `tests/unit/evidence/test_evidence_build.py` | recursive payload comparison, gates, sealing, reproducibility |
| `tests/unit/evidence/test_draft_curation.py` | AST reading without execution, fixed status and warnings |
| `tests/unit/evidence/test_evidence_cli.py` | CLI behaviour and its deliberate absences |
| `tests/unit/evidence/test_evidence_boundaries.py` | layer boundaries, no WP-09+ concept |
| `tests/unit/test_wp08_schema.py` | migration `0006` shape and rendered DDL |

The build, traceability, extraction and CLI tests run against the **real**
quarantined snapshot rather than a fixture, because the counts they assert are
claims about that data. Where a test could pass vacuously, it asserts the
precondition too — for example, the test that no project vocabulary reaches an
evidence record first asserts that the vocabulary is genuinely present in the
draft-curation artifact.

## 3. The evidence build

```
$ pgx-evidence build --dataset-id PGX-DATA-20260830-900 --mode LEGACY_MIGRATION \
    --snapshot data/raw/clinpgx-legacy-v2/PGX-DATA-20260830-900 \
    --canonical-build data/canonical/PGX-DATA-20260830-900 \
    --out data/evidence --allocate-new-identities --text

evidence build sealed at data/evidence/PGX-DATA-20260830-900
  build key      PGX-DATA-20260830-900/5a58c030d00dc649
  content hash   sha256:5a58c030d00dc6495d69c3ff9e1d76c6d6230caf7795871e4dfc4e8774fcb83e
  mode           LEGACY_MIGRATION
  records        1794
  issues         3486 (3235 blocking)
  identities     1794 minted, 0 reused
  labels         QUARANTINED, LEGACY_MIGRATION, NOT_CURATED, NOT_EXECUTABLE, NOT_PUBLICATION_ELIGIBLE
  dataset        BUILDING (a build is not an approval)
```

4,051 source-record observations became 1,794 evidence records.

| Measure | Value |
| --- | ---: |
| Evidence records | 1,794 |
| — `VARIANT_ANNOTATION` | 1,634 |
| — `GUIDELINE_ANNOTATION` | 132 |
| — `DRUG_LABEL_ANNOTATION` (all `PENDING_REVIEW`) | 28 |
| Raw locators retained | 4,051 |
| Records with more than one locator | 1,732 |
| Entity links | 4,284 (1,946 gene, 2,338 drug) |
| Records naming more than one gene | 130 |
| Records naming more than one drug | 210 |
| Source text fragments | 3,432 |
| Publication references | 1,952 (1,797 identified) |
| Distinct publications | 1,012 |
| Version status `KNOWN` / `UNKNOWN_LEGACY` / `MISSING` | 234 / 1,542 / 18 |
| Origin `STATED_BY_SOURCE` / `NOT_STATED_BY_SOURCE` | 132 / 1,662 |
| Payload relation `IDENTICAL` / `PROJECTION` / `CONFLICT` | 1,683 / 111 / 0 |
| Records complete in themselves | 132 |
| Records publishable | **0** (the build is quarantined) |
| Blocking issues | 3,235 |

## 4. Gates

```
$ pgx-evidence build --dataset-id PGX-DATA-20260830-900 --snapshot ... --canonical-build ...
import refused: 3 blocking finding(s) refuse a production evidence import:
RAW_SNAPSHOT_NOT_ACQUIRED, RAW_SNAPSHOT_QUARANTINED, SOURCE_POLICY_MISSING.
exit=1

$ pgx-evidence build --dataset-id PGX-DATA-99999999-001 --mode LEGACY_MIGRATION ...
DATASET_ID_MISMATCH: --dataset-id says PGX-DATA-99999999-001 but the inputs
declare PGX-DATA-20260830-900. Nothing was written.
exit=2                                    # and the output directory is empty

$ pgx-evidence build ... --out data/evidence      # a second time
an evidence build already exists at data/evidence/PGX-DATA-20260830-900.
Sealed builds are never overwritten; write the new build elsewhere and compare.
exit=1
```

## 5. Verification and reproducibility

```
$ pgx-evidence verify --build data/evidence/PGX-DATA-20260830-900 \
    --snapshot data/raw/clinpgx-legacy-v2/PGX-DATA-20260830-900 --trace-limit 0 --text
verify data/evidence/PGX-DATA-20260830-900
  checksums          ok
  files              ok
  published schemas  ok (1794 records)
  traces re-derived  1794 checked, ok
```

Every one of the 1,794 records was re-derived from the raw bytes: artifact
re-read, re-hashed, pointer re-resolved, payload hash recomputed, record
content hash recomputed from its stored fields.

Rebuilding into a second root with the recorded allocation:

```
$ pgx-evidence build ... --out /tmp/evrepro --allocation .../evidence-identity-allocation.json
  identities     0 minted, 1794 reused

$ pgx-evidence compare-builds --left data/evidence/PGX-DATA-20260830-900 --right /tmp/evrepro/...
  reproducible   True
  content hash   matches
  complete       yes
  identical      7 files
  differing      checksums.sha256, manifest.json
```

The two differing files carry `built_at`. Every other byte matches.

A negative control: two directories holding only a matching `manifest.json`
satisfy "content hash matches", "nothing differs" and "no file is only on one
side" — and are correctly reported `reproducible False`, because
`both_complete` is false. That check was added after the first version of
`compare-builds` would have called them reproducible.

## 6. The published schemas

```
manifest.json                       valid
evidence-records.ndjson             0 of 1794 records fail
draft-curation-proposals.ndjson     0 of 1559 proposals fail
```

Each constraint was confirmed to bite rather than pass silently:

```
smuggled project field in normalized_metadata -> $.normalized_metadata: matches a forbidden form
a record with no locator                      -> $.locators: 0 items is below the minimum of 1
a proposal claiming APPROVED                  -> $.status: expected 'UNREVIEWED_LEGACY_MIGRATION_CANDIDATE'
a proposal with one warning instead of four   -> $.warnings: 1 items is below the minimum of 4
```

The WP-06 validator raises on any keyword it does not implement, so these
schemas needed `not`, `minItems`, `maxItems`, `uniqueItems`, `maximum` and
`minProperties` implemented before they could be published. Six new tests
assert each of those actually refuses something.

## 7. Migration 0006 on real PostgreSQL

```
$ initdb -D "$PGDATA" -U pgx
$ pg_ctl -D "$PGDATA" -o "-p 55408 -k /tmp/pgsock08 -c listen_addresses=" start
$ createdb -h /tmp/pgsock08 -p 55408 -U pgx pgx_wp08
$ for f in wp02 wp03 wp05 wp06 wp07 wp08; do
    psql ... -v ON_ERROR_STOP=1 -f build/$f-schema.sql
  done
### tables: 37
```

All six rendered schemas apply cleanly. `evidence_records.source_record_version`
is nullable; `source_record_version_status` is `NOT NULL`.

### Constraint drills

`scripts/sql/wp08-constraint-drills.sql`, 38 cases, each stating whether the
database is expected to accept or refuse it.

```
drills: 38   mismatches: 0
```

Three of those drills exist because they **failed** when first written, each
exposing a real schema defect:

- **E21 / E33** — `identity IS NULL OR identity = 'pmid:' || pmid OR identity =
  'doi:' || doi` accepted `identity = 'title:something'` on a row whose `doi`
  was NULL. `'doi:' || NULL` is NULL, so the disjunction evaluated to NULL, and
  a CHECK admits a row it cannot refuse. Each arm now names its own column
  `IS NOT NULL` first.
- **E34** — `ck_evidence_records_eligible_is_complete` collapsed the same way
  when `record_type_mapping_status` was NULL, letting an unmapped record be
  marked production eligible. The nullable column is now tested for NULL
  explicitly.
- **E36 / E37** — the immutability trigger named thirteen protected columns,
  which let an `UPDATE` rewrite `source_text` on a finalized record: the
  source's own wording, under a content hash that no longer described it. An
  enumerated list is an allowlist by omission and every column added later
  would default to mutable, so the trigger now compares whole rows with
  `NEW IS DISTINCT FROM OLD`.

A structural test (`test_every_nullable_column_named_in_a_check_is_null_guarded`)
sweeps the rendered DDL so the first class of defect cannot reappear silently.

### Upgrade / downgrade cycle

```
state@0005        tables=29  fingerprint=b5165e709d91b538337cd11f211d23cf
upgrade 1 -> 0006 tables=37  fingerprint=69663669030b84b3fcda6dea29308921
downgrade -> 0005 tables=29  fingerprint=b5165e709d91b538337cd11f211d23cf   restores 0005 exactly: YES
upgrade 2 -> 0006 tables=37  fingerprint=69663669030b84b3fcda6dea29308921   upgrade 1 == upgrade 2: YES
```

The fingerprint is an md5 over every column, constraint, index and trigger in
the public schema.

The downgrade correctly **refuses** on a database holding a record with no
source record version, because restoring 0001's `NOT NULL` would require
writing a version nobody knows:

```
ERROR: column "source_record_version" of relation "evidence_records" contains null values
  tables after refused downgrade = 37 (unchanged)
  evidence_builds still present  = 1
  legacy row survived            = 1
```

That refusal was originally *partial* — psql auto-commits each DDL statement,
so eight tables had already been dropped by the time the restore failed. Both
directions are now wrapped in one transaction, as Alembic runs them, so a
refusal leaves the schema untouched. Re-applying `0006` to a database that
already has it fails on the first `CREATE TABLE` and changes nothing.

### The real corpus in the real schema

The 38 drills are synthetic. `pgx-evidence render-rows` renders the actual
build as the rows migration 0006 declares, and they were loaded into the live
schema with every constraint active:

```
evidence_builds            1
evidence_records        1794
evidence_genes          1946
evidence_drugs          2338
evidence_text_fragments 3432
publication_references  1012
evidence_publications   1952
evidence_provenance     4051
evidence_import_issues  3486
                       -----
                       20012 rows, loaded in one transaction
```

Queried back:

| Check | Result |
| --- | --- |
| Records carrying a version they do not know | 0 |
| Records naming an origin they did not state | 0 |
| Duplicate natural keys | 0 |
| Orphans across every new foreign key | 0 |
| Records with no raw locator | 0 |
| Project interpretation columns in the evidence store | 0 |
| `UPDATE` on a finalized record | refused by trigger |
| `DELETE` on any record | refused by trigger |
| `dataset_versions.status` | `BUILDING` |

## 8. Draft curation extraction

```
$ pgx-evidence extract-draft-curation --build data/evidence/PGX-DATA-20260830-900 \
    --out data/migration/wp08/draft-curation-proposals.ndjson --text
wrote 1559 draft curation proposals to data/migration/wp08/draft-curation-proposals.ndjson
  linked to evidence   1526
  unlinked             33
  status               UNREVIEWED_LEGACY_MIGRATION_CANDIDATE
  warnings             NOT_EVIDENCE, NOT_SCIENTIFICALLY_REVIEWED, NOT_EXECUTABLE, DO_NOT_USE_FOR_ASSESSMENT
  content hash         sha256:ac30783a3c718851dda81fa5a29769e8c84d5b867b3fdebb0e41f1d67ed675a6
  published schema     ok

$ pgx-evidence extract-draft-curation ... --out <the same path>
OUTPUT_EXISTS: data/migration/wp08/draft-curation-proposals.ndjson
exit=1
```

## 9. Inherited open finding: 1,572 versus 1,644

`architecture.md` states that legacy deduplication produced **1,572**
collisions. WP-07 measured **1,644** against the real snapshot and could not
reproduce 1,572 under any documented key.

**This remains open and unresolved.** WP-08 did not change the WP-07
deduplication key to force the architectural figure, and did not edit
`architecture.md` to match the measurement. The discrepancy is carried forward
as an inherited finding for a human to settle: either the architecture's figure
was produced under a key nobody wrote down, or the legacy run it describes
differed from the snapshot now sealed. Both possibilities are checkable by
someone with access to the original run; neither is checkable from here.

Recorded as **A11: FAIL** in the WP-07 report and unchanged by this work
package.

## 10. Known limitations

- There is no evidence-store persistence adapter. The ports exist, migration
  0006 exists, and `render-rows` produces the rows — inserting them needs a
  driver this environment cannot install.
- 3,235 blocking issues means this build is quarantined and nothing in it is
  publishable. That is the honest state of a legacy import over an unapproved
  source, not a defect to be worked around.
- The `label`/`DrugLabel` equivalence is unresolved by design; 28 records wait
  on a human.
- 251 entity references remain unresolved (advisory), inherited from WP-07's
  resolution queue.
