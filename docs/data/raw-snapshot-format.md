# Immutable raw snapshot format

| Field | Value |
|---|---|
| Document ID | `DOC-DATA-001` |
| Work package | WP-06 - Immutable Raw Snapshots and Dataset Build Start |
| Companion documents | `dataset-build-lifecycle.md`, `../migration/clinpgx-v2-legacy-snapshot.md`, `../evidence/wp06-snapshot-verification.md` |
| Schema | `schemas/raw-snapshot-manifest.schema.json` |
| Example | `docs/examples/raw-snapshot-manifest.json` |

> A snapshot is raw source bytes and nothing else. It is not canonical data, not
> curated evidence, not an interpretation, and not a scientifically approved
> dataset. Sealing one asserts that these bytes are what the source returned; it
> asserts nothing about whether they are correct, complete relative to the
> upstream source, or permitted to be used.

---

## 1. Layout

```text
data/raw/<source-key>/<dataset-id>/
├── manifest.json          the machine-readable account of the snapshot
├── requests.ndjson        one canonical JSON object per retrieved page
├── responses/
│   └── <request-key-hex>.json   exact response bytes, one file per request
└── checksums.sha256       sha256sum-format digests of the files above
```

`<dataset-id>` is an explicit `PGX-DATA-YYYYMMDD-NNN` supplied by the caller.
Nothing scans the raw root for "the next number": two builders doing that would
race, and a dataset's identity would depend on what else happened to be on disk.

For a `LEGACY_IMPORT` the same layout is used and `responses/` holds the copied
files under their original names. The directory keeps its name so verification
is one code path; the artifacts are marked `LEGACY_FILE` and each records its
`source_relative_path`.

## 2. Three hash identities, deliberately separate

| Identity | Over what | Includes | Excludes |
|---|---|---|---|
| **Artifact hash** | one file's exact bytes | — | — |
| **Snapshot content hash** | sorted artifact content identities | relative path, artifact kind, SHA-256, byte length, request key, endpoint, page, cursor | creation time, staging path, absolute path, cache HIT/MISS, retry timing, **the dataset ID**, the request log |
| **Manifest hash** | the whole manifest payload | everything, dataset ID and creation instant included | only the `manifest_hash` field itself |

Two consequences worth stating plainly:

- **A cache replay matches the network run it replays.** Both produce the same
  content hash, so "do we already have this data?" is answerable without
  re-downloading it.
- **Two dataset IDs over identical bytes share a content hash and differ in
  manifest hash.** Content identity is reusable across IDs; manifest identity is
  not, because the manifest names the dataset.

The request log is excluded from the content hash because it carries retrieval
timestamps and retry counts. Those are provenance an operator needs and content
identity must not depend on.

## 3. `requests.ndjson`

One canonical JSON object per line - sorted keys, fixed separators - ordered by
request key then page number, ending with exactly one newline. Empty (zero
bytes) when there were no requests, which is the case for every legacy import:
reconstructing a request chronology that was never recorded would be a
fabrication.

Each line carries the request key, endpoint, method, URL **with its query
stripped**, the sanitised query as ordered `[name, value]` pairs (so
`?id=1&id=2` survives as two entries), page, cursor, status code, content type,
byte length, the artifact path and digest, the cache state, the retrieval
instant and the retry count.

The query is recorded from WP-04's sanitised list rather than from the URL, and
a parameter whose name looks like a credential fails the build. A snapshot is
kept forever; a secret written into one cannot be recalled.

## 4. `checksums.sha256`

`sha256sum` format - `<64 lowercase hex><two spaces><relative path>`, sorted by
path, one trailing newline - so a reviewer can verify a snapshot with the system
tool and no project code at all:

```bash
cd data/raw/<source-key>/<dataset-id> && sha256sum -c checksums.sha256
```

It covers `requests.ndjson` and every response artifact. It does **not** list
`manifest.json` and does not list itself. That avoids the obvious cycle: the
manifest records the checksum file's contents, so a checksum file containing its
own digest could never be written. There is no special case anywhere.

## 5. Atomic finalisation

1. An exclusive claim file `<final>.claim` is created with `O_CREAT|O_EXCL`. A
   second builder racing for the same dataset ID fails here with
   `DATASET_ID_ALREADY_CLAIMED`.
2. A staging directory is created **in the same parent** as the final path. A
   rename across filesystems is a copy and a delete, with a window in the middle
   where a reader sees a half-written snapshot.
3. Every file is written and re-hashed immediately after writing.
4. The final path is re-checked under the claim, then `os.rename(staging, final)`.
5. The tree is made read-only and the claim file is removed.

`os.replace` is never used, and a test fails the build if it appears.
`os.replace` overwrites its target, and overwriting a sealed snapshot is the one
thing this module exists to prevent. `os.rename` refuses a non-empty target, and
an *empty* directory left by a concurrent builder is excluded by the pre-check
taken under the exclusive claim.

A build that fails at any point removes its staging directory and leaves no
snapshot. A build that finds anything at the final path is refused, **even when
the incoming content is byte-identical**: a dataset ID is claimed once, and a new
acquisition gets a new ID.

## 6. What "immutable" means here, precisely

The project enforces:

- no supported API reopens a sealed snapshot for writing - there is no `write`,
  `update`, `append`, `reopen` or `overwrite` on the manager, and a test asserts
  their absence;
- files become `0444` and directories `0555` where the platform permits;
- a dataset ID cannot be claimed twice;
- verification detects any post-seal change;
- the database row's identity columns cannot be updated and the row cannot be
  deleted (`trg_raw_snapshots_identity_immutable`).

The project does **not** provide WORM storage. Ordinary filesystem permissions
stop an accident and a careless script; they do not stop the directory's owner,
who can `chmod` it back and edit it. That is precisely why verification exists
and why the manifest carries the hashes needed to run it. Some filesystems - a
network mount, for instance - ignore `chmod` entirely; the read-only step is
best-effort and the test that checks it skips where the platform does not honour
permissions.

No hard links are used when importing, and a hard-linked file inside a sealed
snapshot fails verification: bytes reachable through a second name can be
rewritten through that name without the snapshot appearing to change. Symlinks
are refused for the same reason, and neither the builder nor the verifier ever
follows one.

## 7. Verification

`pgx-dataset verify --source-key <k> --dataset-id <id>` re-derives everything
from the snapshot's own bytes:

- the manifest satisfies the published JSON Schema;
- the manifest's payload still digests to its recorded `manifest_hash`;
- the artifact descriptors still digest to the recorded content hash;
- every file on disk is re-hashed and compared against both the manifest and
  `checksums.sha256`;
- the tree contains no symlink, no special file and no hard-linked file;
- no file is present that the manifest does not describe, and none named by the
  manifest is missing.

Nothing is repaired. Every problem is reported, not just the first, and the
command exits non-zero.

## 8. Stable issue codes

Build and verification failures carry a `SnapshotIssueCode`. These are a public
contract; renaming one is a breaking change. The families are: acquisition input
(`ACQUISITION_NOT_COMPLETE`, `REQUIRED_ENDPOINT_INCOMPLETE`,
`PAGINATION_NOT_TERMINAL`, …), bytes and cache (`CACHE_BLOB_MISSING`,
`ARTIFACT_HASH_MISMATCH`, `REQUEST_KEY_COLLISION`, …), path safety
(`PATH_TRAVERSAL`, `ABSOLUTE_PATH`, `SYMLINK_PRESENT`, `HARD_LINK_PRESENT`, …),
finalisation (`SNAPSHOT_ALREADY_EXISTS`, `DATASET_ID_ALREADY_CLAIMED`, …),
verification (`MANIFEST_HASH_MISMATCH`, `UNEXPECTED_FILE`, `ARTIFACT_MISSING`, …)
and policy (`SOURCE_POLICY_BLOCKED`, `STORAGE_NOT_PERMITTED`, …).

## 9. Storage cost

A snapshot is a **copy**. The checked-in legacy snapshot duplicates 36.6 MB of
`clinpgx_outputs_v2/`, and that duplication is deliberate: a hard link or a
symlink would make the snapshot's contents changeable through another name.
