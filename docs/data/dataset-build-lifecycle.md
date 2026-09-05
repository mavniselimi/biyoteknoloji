# Dataset build lifecycle

| Field | Value |
|---|---|
| Document ID | `DOC-DATA-002` |
| Work package | WP-06 |
| Companion documents | `raw-snapshot-format.md`, `../scientific/source-strategy.md`, `../handoffs/wp06-handoff.md` |

> **WP-06 starts a dataset build. It never finishes one.** A dataset it
> registers is `BUILDING`, carries no `approved_by` and no `approved_at`, and
> cannot be promoted by anything in this work package. There is no `publish`
> command, no `quality-check` command, and no argument anywhere that names a
> reviewer.

---

## 1. Six operations that are often called "publishing a dataset"

| # | Operation | Owner | State after |
|---|---|---|---|
| 1 | Build a snapshot in a staging directory | WP-06 | nothing durable yet |
| 2 | Seal it - atomic rename into its final path | WP-06 | snapshot `SEALED` (or `QUARANTINED`) |
| 3 | Register a `DatasetVersion` | WP-06 | dataset `BUILDING` |
| 4 | Quality-check the dataset | **WP-07** | dataset `QUALITY_CHECKED` |
| 5 | Publish the dataset | WP-07 + a human approval | dataset `PUBLISHED` |
| 6 | Activate a release citing it | WP-03 + WP-05 gates | release `ACTIVE` |

WP-06 performs 1 to 3. Steps 4 to 6 are not implemented here and cannot be
reached from here.

The phrase "publish a snapshot directory" appears in `architecture.md` and means
the *filesystem* transition in step 2 - a staging directory becoming a final
one. It has nothing to do with `DatasetStatus.PUBLISHED`, and conflating the two
is exactly the mistake this table exists to prevent.

## 2. The order, and why it is that order

```text
evaluate WP-05 policy  →  build staging  →  seal  →  verify  →  register
        (no bytes written if this fails)                        (retryable)
```

**Policy first.** A source this project may not store is a source whose bytes
must not land on disk at all, so the gate runs before a byte is written rather
than as a flag on a finished manifest. A refused build leaves no staging
directory, no claim file and no snapshot.

**Verify before register.** Registering first would create a row pointing at
evidence nobody had checked, and the row would outlive the discovery that the
evidence was corrupt.

## 3. Two resources, one operation, no shared transaction

Sealing a directory and committing a database row cannot be one atomic act. The
order is chosen so the surviving state is always the safe one, and the outcome
is always reported rather than smoothed over:

| Outcome | Meaning | What to do |
|---|---|---|
| `REGISTERED` | Snapshot sealed and verified, dataset row created in `BUILDING` | nothing |
| `ALREADY_REGISTERED` | A `DatasetVersion` already uses that public ID | nothing; the operation is idempotent |
| `SEALED_UNREGISTERED` | The snapshot exists and verifies; the row does not | re-run `pgx-dataset register` |
| `NOT_ATTEMPTED` | A build was performed; registration was not asked for | run `register` when ready |

`SEALED_UNREGISTERED` is a real, reportable state, not an error to be hidden.
The snapshot is **never** deleted to tidy up a failed registration: destroying
verified immutable evidence to make a status line look neat is the wrong trade
in every direction.

`pgx-dataset status` reports both halves and changes neither. It is safe to run
repeatedly, which matters because it is the command an operator reaches for
during an incident.

## 4. What registration writes

One `DatasetVersion`:

| Column | Value |
|---|---|
| `public_id` | the explicit `PGX-DATA-YYYYMMDD-NNN` the caller supplied |
| `status` | `BUILDING`, always |
| `manifest_hash` | the snapshot's manifest hash |
| `created_at` | the injected clock's instant |
| `approved_by`, `approved_at` | **null**, always |
| `dq_report_path` | null - there is no data-quality report until WP-07 |

And one append-only `AuditEvent` with action `DATASET_BUILD_REGISTERED`, whose
metadata carries the snapshot kind and state, both hashes, the artifact and byte
counts, the acquisition run ID where one genuinely exists, the source-policy
status, and a scope note saying the dataset is `BUILDING` and not published. The
snapshot directory is recorded as its last three path segments, not as an
absolute path: an audit trail that recorded one machine's directory layout would
be unreadable on another.

`DATASET_BUILD_REGISTERED` is new in WP-06 and migration `0004` widens the
`audit_events` action constraint to admit it. Every previously permitted action
still passes; the append-only trigger is untouched.

## 5. Source policy at snapshot time

For an `ACQUISITION` or `CACHE_REPLAY` snapshot the WP-05 gate is consulted for
two separate questions:

- may this project **store** the source's records (`LOCAL_STORAGE`)?
- may they have been retrieved **by program** (`AUTOMATED_ACQUISITION`)?

Both must be `ALLOWED`, the source must be approved by a named human, active,
and its review unexpired. `UNKNOWN`, `RESTRICTED`, `PROHIBITED`, an unregistered
source and a registry that will not load all block. With the checked-in registry
- where every source is `PENDING_REVIEW` with every permission `UNKNOWN` - **no
production snapshot can be built today**, which is the correct behaviour and not
a defect.

The complete gate result is stored in the manifest whatever it said. A sealed
snapshot is never publication-eligible on its own: `publication_eligible` is
false in every manifest this work package writes, and a database check
constraint forbids a quarantined or legacy snapshot from ever setting it true.

A `LEGACY_IMPORT` is not gated on acquisition permission. Asking "were we
permitted to fetch this?" of bytes whose retrieval predates the adapter has no
honest answer, so the snapshot is `QUARANTINED` and permanently
non-publication-eligible instead, and the unknown policy state is recorded as a
limitation rather than resolved by assumption.

## 6. Commands

```bash
# Build from a WP-04 run. Refused today: no source is approved.
pgx-dataset build-from-run --dataset-id PGX-DATA-20260901-001 \
    --source-key clinpgx.api --acquisition-manifest run.json --cache-dir ./cache

# Package a legacy directory as a quarantined snapshot.
pgx-dataset import-legacy --dataset-id PGX-DATA-20260830-900 \
    --source-key clinpgx-legacy-v2 --source-dir clinpgx_outputs_v2

pgx-dataset verify   --source-key clinpgx-legacy-v2 --dataset-id PGX-DATA-20260830-900
pgx-dataset inspect  --source-key clinpgx-legacy-v2 --dataset-id PGX-DATA-20260830-900
pgx-dataset status   --source-key clinpgx-legacy-v2 --dataset-id PGX-DATA-20260830-900
pgx-dataset register --source-key clinpgx-legacy-v2 --dataset-id PGX-DATA-20260830-900 \
    --actor you@example.org --reason "start the WP-07 build"
```

Exit codes: `0` success, `1` refused or verification failed, `2` configuration
failure, `3` not found, `4` sealed but unregistered.
