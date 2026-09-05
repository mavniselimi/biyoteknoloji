# Legacy snapshot: `clinpgx_outputs_v2`

| Field | Value |
|---|---|
| Document ID | `DOC-MIG-006` |
| Work package | WP-06 |
| Dataset ID | `PGX-DATA-20260830-900` |
| Source key | `clinpgx-legacy-v2` |
| Path | `data/raw/clinpgx-legacy-v2/PGX-DATA-20260830-900/` |
| Kind / state | `LEGACY_IMPORT` / `QUARANTINED` |
| Publication eligible | **no**, permanently |
| Artifacts / bytes | 12 files / 36 567 083 bytes |
| Content hash | `sha256:c36a5c3a69bc96ea2094a257250d3bd01289201f3d85ca90b275feba98fd44f2` |
| Manifest hash | `sha256:3b79e3bfdde2de49d5a1a217e56d217455bd0fe9503929293ca95dda485075b7` |
| Rebuild command | `python3 scripts/import_legacy_snapshot.py` |
| Verify command | `python3 scripts/import_legacy_snapshot.py --verify` |

> This snapshot preserves bytes the legacy probe scripts downloaded. It does not
> claim they were produced by the WP-04 adapter, and it invents no run ID, no
> request chronology, no retrieval timestamps and no completeness figure. It is
> quarantined because the questions a snapshot normally answers cannot be
> answered for it.

---

## 1. What was imported

The twelve files in `clinpgx_outputs_v2/`, copied byte for byte into
`responses/` under their original names. Six JSON documents and six CSVs,
including the two largest probe outputs (`pair_probe_raw.json` and
`variant_annotation_filtered_raw.json`).

`clinpgx_outputs_v2/` itself is **unchanged**: the import reads it and never
writes to it, and no manifest, checksum file or marker was placed inside it. A
test re-hashes all twelve source files and compares them against the copies.

## 2. Why this dataset ID

`PGX-DATA-20260830-900` is unclaimed, valid against `DatasetPublicId`, and dated
to the day the import ran.

The `9xx` band is already this project's convention for legacy identities:
`pgx/application/legacy_baseline.py` reserves `PGX-DATA-20260829-999` for the
frozen WP-01 baseline. That is **a different artifact** - the WP-01 baseline
captures legacy *script outputs* for regression comparison, whereas this
snapshot captures the legacy probe's *raw downloads* - so reusing `-999` would
have merged two unrelated identities. `900` sits in the same legacy band, cannot
collide with a normal sequential build (`001`…), and reads as legacy at a
glance. A test asserts the two identities differ.

The ID is pinned in `scripts/import_legacy_snapshot.py` rather than derived.
Scanning the raw root for "the next free number" is a race, and it would make an
identity depend on what else happened to be on disk.

## 3. Why a separate source key

`clinpgx-legacy-v2` is not a registered scientific source, and a test asserts
that `config/scientific-sources.json` has no entry for it. These bytes are a
project artifact of unknown provenance, not an authenticated retrieval from
ClinPGx. Filing them under `clinpgx.api` would imply the adapter fetched them
under a reviewed policy, which is exactly the claim that cannot be made.

## 4. Recorded limitations

Nine, stored in the manifest and enforced by a database check constraint that
refuses a `LEGACY_IMPORT` row with an empty limitations list:

1. Not produced by the WP-04 ClinPGx adapter; no acquisition run backs these
   files.
2. No trustworthy acquisition run identifier exists, and none was invented -
   `acquisition_run_id`, `acquisition_status` and `acquisition_content_hash`
   are all null.
3. Request chronology is unavailable: which endpoint produced which file, in
   what order, with what query, is recorded nowhere. `requests.ndjson` is
   therefore **empty (0 bytes)** rather than reconstructed.
4. Retry counts, HTTP status codes and rate-limit metadata are unavailable.
5. Retrieval timestamps are unavailable. `created_at` is when the import ran,
   not when the source was queried.
6. Completeness relative to the upstream ClinPGx source is unknown. Every file
   present was copied; what fraction of the source that represents is not
   established and is not implied. `complete` is `false`.
7. The source policy for these bytes is unknown - no named human has reviewed
   whether ClinPGx data may be stored, transformed or redistributed - so the
   snapshot is `QUARANTINED` and permanently non-publication-eligible.
8. Legacy naming and layout are preserved verbatim, including the mixed CSV and
   JSON shapes and the case-variant container spellings recorded in
   `legacy-source-inventory.md`.
9. No canonical resolution, no deduplication, no data-quality assessment, no
   evidence extraction and no interpretation has been applied.

## 5. What is *not* claimed

| Question | Answer |
|---|---|
| Were these files fetched by the WP-04 adapter? | No. |
| Do we know when they were fetched? | No. |
| Do we know which endpoint produced each one? | No. |
| Do we know they are a complete view of the source? | No. |
| Are we permitted to use them? | Unknown; no review has been done. |
| Can this dataset be published? | No, and no code path can make it publishable. |
| Are the bytes intact and byte-identical to the legacy directory? | **Yes** - verifiable independently. |

Only the last row is a claim, and it is the one this snapshot exists to support.

## 6. Independent verification

Without any project code:

```bash
cd data/raw/clinpgx-legacy-v2/PGX-DATA-20260830-900
sha256sum -c checksums.sha256
```

With it:

```bash
python3 scripts/import_legacy_snapshot.py --verify
pgx-dataset verify --source-key clinpgx-legacy-v2 --dataset-id PGX-DATA-20260830-900
```

The second form additionally validates the manifest against the published JSON
Schema, recomputes both the manifest hash and the content hash, and refuses
symlinks, special files, hard-linked artifacts and any file the manifest does
not describe.

## 7. Rebuilding it

`python3 scripts/import_legacy_snapshot.py` refuses to run while the snapshot
exists - a dataset ID is claimed once. To rebuild after deliberately removing
the directory, note that the content hash is reproducible (the same bytes give
the same content hash) but the manifest hash is **not**, because `created_at`
changes. That is the intended difference between the two identities; see
`../data/raw-snapshot-format.md` section 2.

## 8. Storage cost

The snapshot duplicates 36.6 MB. The duplication is deliberate: a hard link or a
symlink would leave the snapshot's bytes reachable - and therefore changeable -
through another name, which would make "immutable" false.

## 9. What WP-07 may do with it

Read it. It is the raw input a canonical build starts from. WP-07 must treat
every limitation above as still true: nothing about this snapshot licenses
inferring completeness, provenance or permission, and its quarantine state
does not lift because a later work package found it useful.
