# WP-06 handoff

| Field | Value |
|---|---|
| Document ID | `DOC-HANDOFF-006` |
| Work package | WP-06 - Immutable Raw Snapshots and Dataset Build Start |
| Status | **Offline scope complete. No dataset is approved or publishable.** |
| Output for WP-07 | one verified, quarantined legacy snapshot |

> Read this before WP-07. The one criterion that must not be presented as met is
> A22: no real dataset is scientifically or source-policy approved, because
> WP-05's human approvals are absent and WP-07's quality checks do not exist.

---

## 1. What exists now

| Artefact | What it is |
|---|---|
| `pgx/ingestion/snapshots.py` | Snapshot domain and manager: kinds, states, descriptors, manifest, atomic seal, verification |
| `pgx/ingestion/common/manifest_io.py` | Reads a WP-04 run manifest back and refuses to trust its own claims |
| `pgx/application/dataset_service.py` | Policy gate, build orchestration, `BUILDING` registration |
| `pgx/application/dataset_cli.py` | `pgx-dataset`, six read/build commands |
| `pgx/application/snapshot_schema.py` | Loads and applies the published manifest schema |
| `schemas/raw-snapshot-manifest.schema.json` | Generated from the vocabularies |
| `migrations/versions/0004_wp06_raw_snapshots.py` | `raw_snapshots`, `raw_artifacts`, identity trigger, audit-action widening |
| `data/raw/clinpgx-legacy-v2/PGX-DATA-20260830-900/` | The quarantined legacy snapshot |
| `scripts/dataset.py`, `scripts/import_legacy_snapshot.py`, `scripts/render_wp06_schema.py`, `scripts/render_snapshot_manifest_schema.py` | Operator and evidence tooling |

## 2. What is blocked

### 2.1 No production snapshot can be built (A11 as applied today)

Every source in `config/scientific-sources.json` is `PENDING_REVIEW` with every
reuse permission `UNKNOWN`, so the WP-05 gate refuses `LOCAL_STORAGE` and
`AUTOMATED_ACQUISITION` for all of them. `pgx-dataset build-from-run` therefore
exits 1 for any real source key, and writes nothing.

**This is the mechanism working, not a defect.** The tests exercise the
successful path with explicit synthetic approved policies naming
`TEST_SCIENTIFIC_REVIEWER`; the real registry is never edited. Unblocking means
a named human completing `docs/scientific/source-review-checklist.md` for a
source - not a code change here.

### 2.2 A22: no dataset is approved or publishable

The only dataset this work package can create is `BUILDING`, with null
`approved_by` and null `approved_at`. There is no code path to
`QUALITY_CHECKED` (WP-07) or `PUBLISHED` (WP-07 plus a human approval), and the
CLI has no command that could reach either.

### 2.3 Alembic, PostgreSQL and the toolchain

Unchanged from WP-02: the package index is unreachable, so `alembic`,
`sqlalchemy`, `psycopg`, `pytest`, `ruff` and `mypy` cannot be installed and the
Docker daemon is unreachable. Migration evidence is rendered DDL executed on a
real PostgreSQL 16.13, explicitly **not** Alembic evidence.

## 3. Open items WP-06 did not fix

### 3.1 No repository implements the snapshot tables

`0004` creates `raw_snapshots` and `raw_artifacts`, and nothing writes to them
yet. `DatasetService.register` creates the `DatasetVersion` and the audit event
through the existing ports; persisting the snapshot row and its artifact
descriptors needs a SQLAlchemy repository that does not exist. Until it does, an
empty `raw_snapshots` table is **not** evidence that no snapshot was built - the
filesystem is the record.

### 3.2 The legacy snapshot is registered nowhere

It is sealed and verified but no `DatasetVersion` names it, because registration
needs a database this environment does not have. Run
`pgx-dataset register --source-key clinpgx-legacy-v2 --dataset-id
PGX-DATA-20260830-900 --actor <you>` where one is available; the result today is
`SEALED_UNREGISTERED`, which is the correct report.

### 3.3 Downgrading `0004` is refused once a build has been registered

By design - see `docs/evidence/wp06-snapshot-verification.md` section 5.3. An
operator who genuinely needs that downgrade must decide explicitly what happens
to the append-only `DATASET_BUILD_REGISTERED` rows.

### 3.4 Read-only sealing is best-effort

Verified working on an ordinary filesystem (`0444` files, `0555` directories,
`PermissionError` on write). The project's own working tree is sometimes a
network mount that silently ignores `chmod`, and the test that checks
permissions skips there. Detection through verification is the guarantee that
does not depend on the platform.

### 3.5 The snapshot duplicates 36.6 MB

Deliberate: hard links and symlinks are both refused, because either would leave
the bytes changeable through another name.

### 3.6 One source key per snapshot

A snapshot names exactly one `source_key`. A dataset built from two sources
would need two snapshots and a decision about how a dataset relates to them.
That decision belongs to whoever builds the first multi-source dataset.

## 4. What WP-07 may and may not assume

**May assume.** The snapshot layout, the three hash identities and the stable
issue codes are fixed. A sealed snapshot verifies independently, and
`sha256sum -c checksums.sha256` is sufficient to check the bytes. The legacy
snapshot's twelve files are byte-identical to `clinpgx_outputs_v2/`. Building
and verifying need no database and no network.

**May not assume.** That the legacy bytes are complete, current, correctly
retrieved, or permitted to be used. That any dataset is approved. That
`raw_snapshots` holds anything. That a quarantine lifts because a later work
package found the data useful.

**Must not do.** Reopen a sealed snapshot; add a `--force`; promote a dataset
past `BUILDING` without the WP-07 quality gate and a human approval; add
canonical resolution, deduplication or data-quality logic to `pgx/ingestion`;
or register the legacy snapshot against a real scientific source key.

## 5. Inherited blockers, unchanged

WP-06 resolves none of these and presents none of them as resolved:

- WP-00 claim-boundary approval: **BLOCKED**.
- WP-01 Git checkpoint: **BLOCKED**.
- WP-02 toolchain and Docker: **BLOCKED**.
- WP-03: six items open in `docs/handoffs/wp03-open-items.md`, untouched.
- WP-04: no live ClinPGx call has been made; the adapter remains unexercised
  against the real API.
- WP-05: A19 (named human source approval) and A20 (official licensing
  evidence) remain **BLOCKED**; the registry still approves nothing.
