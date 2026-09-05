# WP-06 - Snapshot Verification Evidence

| Field | Value |
|---|---|
| Document ID | `DOC-EV-006` |
| Work package | WP-06 - Immutable Raw Snapshots and Dataset Build Start |
| Captured (UTC) | 2026-08-30 |
| Live API calls made | **zero** |
| Datasets marked QUALITY_CHECKED or PUBLISHED | **zero** |
| Real snapshots damaged by a test | **zero** |

> **This is a technical evidence artifact for WP-06 only.** It claims no
> scientific validation, no licensing conclusion and no clinical safety. It
> demonstrates that raw bytes can be captured, sealed and independently
> verified; it demonstrates nothing about whether those bytes are correct,
> complete relative to their upstream source, or permitted to be used.
>
> WP-00 approval remains **BLOCKED**; WP-01's Git checkpoint remains
> **BLOCKED**; the WP-02 toolchain blockers are unchanged; the six WP-03 review
> items are open in `docs/handoffs/wp03-open-items.md`; WP-05's human source
> approvals (A19) and official licensing evidence (A20) remain **BLOCKED**.
> WP-06 resolves none of them.

---

## 1. Four kinds of evidence, kept apart

| Kind | What it proves | What it cannot |
|---|---|---|
| **A. Offline behavioural** | Hash identity semantics, determinism, atomic sealing, corruption detection, policy fail-closed | Anything about a real source's data or terms |
| **B. Structural** | Layer boundaries; the absence of a publish path, an overwrite path and WP-07 logic | That anything has been reviewed by a human |
| **C. Executed schema** | The `0004` DDL is valid PostgreSQL 16.13 and its constraints reject the rows they target | Anything about Alembic's runner or revision stamping |
| **D. Real artifact** | The checked-in legacy snapshot is byte-identical to `clinpgx_outputs_v2/` and verifies | That those bytes are complete, current or usable |

## 2. Test results

```
python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -t .
Ran 1569 tests in 5.692s
OK (skipped=10)
```

Baseline before WP-06: 1298 tests. WP-06 adds 271 and converts nine
phase-obsolete assertions rather than deleting them (section 7).

| Module | Tests | What it covers |
|---|---:|---|
| `tests/unit/snapshots/test_content_identity.py` | 26 | Artifact / content / manifest hash semantics; replay equality; dataset-ID independence; deterministic NDJSON and checksums |
| `tests/unit/snapshots/test_snapshot_build.py` | 27 | Only a recomputed-complete run may build; cache re-verification; request-key collisions; atomic finalisation; overwrite refusal; no write API |
| `tests/unit/snapshots/test_snapshot_security.py` | 23 | Traversal, absolute paths, symlinks, FIFOs, hard links, case collisions, checksum escapes, unsupported algorithms, credentials |
| `tests/unit/snapshots/test_snapshot_verification.py` | 23 | Changed byte, truncation, removed file, added file, corrupt manifest, unknown field, bad schema version, edited digests |
| `tests/unit/snapshots/test_legacy_snapshot.py` | 26 | The real checked-in snapshot: byte-identical, quarantined, no fabricated acquisition metadata, source directory untouched |
| `tests/unit/snapshots/test_dataset_service.py` | 36 | WP-05 fail-closed gating; synthetic approval; `BUILDING` only; no approval metadata; the filesystem/database split |
| `tests/unit/snapshots/test_dataset_cli.py` | 24 | Exit codes; no publish command; no `--force`; no network import; no database import |
| `tests/unit/snapshots/test_snapshot_schema.py` | 22 | Schema currency; real manifests validate; the validator refuses unimplemented keywords |
| `tests/unit/snapshots/test_snapshot_boundaries.py` | 14 | No network, no ORM, no WP-07 concepts, no JSON parsing on the copy path |
| `tests/unit/snapshots/test_acquisition_manifest_io.py` | 16 | Stored status, publishability and content hash are recomputed, never trusted |
| `tests/unit/test_wp06_schema.py` | 30 | Migration shape, single head, only-adds, widening not weakening, identifier limits |

Zero skips among the WP-06 modules. The ten skips in the full run are the
pre-existing integration tests that need `TEST_DATABASE_URL`.

## 3. The checked-in legacy snapshot

```
data/raw/clinpgx-legacy-v2/PGX-DATA-20260830-900/
kind / state        LEGACY_IMPORT / QUARANTINED
artifacts / bytes   12 / 36,567,083
content hash        sha256:c36a5c3a69bc96ea2094a257250d3bd01289201f3d85ca90b275feba98fd44f2
manifest hash       sha256:3b79e3bfdde2de49d5a1a217e56d217455bd0fe9503929293ca95dda485075b7
complete            false
publication_eligible false
limitations         9
requests.ndjson     0 bytes (no request chronology exists; none was invented)
```

Independent verification, with no project code:

```
$ cd data/raw/clinpgx-legacy-v2/PGX-DATA-20260830-900 && sha256sum -c checksums.sha256
responses/guideline_annotation_rows.csv: OK
... (13 lines, all OK)
```

With project code:

```
$ python3 scripts/import_legacy_snapshot.py --verify
ok: true | checked_artifacts: 13 | issues: 0
```

Byte-preservation, checked directly against the source directory:

```
12/12 files byte-identical
```

Source directory unchanged, checked by re-hashing all twelve files before and
after the import:

```
SOURCE DIRECTORY UNCHANGED (12/12 digests identical)
```

## 4. Determinism

| Property | Result |
|---|---|
| Same bytes → same artifact hash | equal across two dataset IDs |
| Network run vs cache replay | **same content hash** |
| Different dataset ID | same content hash, **different** manifest hash |
| Different staging directory | same content hash |
| Different creation instant | same content hash, different manifest hash |
| Four retries vs one attempt | same content hash |
| Artifact order reversed | same content hash |
| `requests.ndjson` across two builds | byte-identical |
| `checksums.sha256` across two builds | byte-identical |

## 5. Executed schema evidence (PostgreSQL 16.13)

`0004` was rendered to DDL by `scripts/render_wp06_schema.py` (which reads the
migration's AST, so the two cannot drift) and executed on a real server after
`0001`, `0002` and `0003`.

```
PostgreSQL 16.13 (Ubuntu 16.13-0ubuntu0.24.04.1)
0001 → 0002 → 0003 → 0004 applied; 24 tables in public
```

**This is not Alembic evidence.** It proves the DDL is valid PostgreSQL and that
the constraints behave as designed. It proves nothing about Alembic's runner,
its revision chain or `alembic_version` stamping. Those remain BLOCKED for the
same reason as in WP-02, WP-03 and WP-05: the package index is unreachable and
SQLAlchemy, Alembic, psycopg, pytest, ruff and mypy cannot be installed.

### 5.1 Constraints that rejected the rows they target

| # | Attempted row | Constraint that refused it |
|---|---|---|
| 1 | Legacy import claiming `publication_eligible = true` | `ck_raw_snapshots_quarantine_not_publishable` |
| 2 | Legacy import carrying a fabricated `acquisition_run_id` | `ck_raw_snapshots_legacy_has_no_acquisition` |
| 3 | Legacy import stating no limitations | `ck_raw_snapshots_legacy_states_limitations` |
| 4 | A row in `STAGING` state | `ck_raw_snapshots_never_staging` |
| 5 | Half-recorded registration (`registered_by` alone) | `ck_raw_snapshots_registration_is_complete` |
| 6 | Absolute `root_relative_path` | `ck_raw_snapshots_root_path_relative` |
| 7 | Artifact path containing `..` | `ck_raw_artifacts_relative_path` |
| 8 | `LEGACY_FILE` artifact carrying a request key | `ck_raw_artifacts_legacy_has_no_request` |
| 9 | Duplicate artifact path in one snapshot | `uq_raw_artifacts_snapshot_id_relative_path` |

### 5.2 The identity trigger and the audit widening

```
UPDATE raw_snapshots SET snapshot_content_hash = ...
ERROR:  a sealed snapshot identity is immutable: only dataset_version_id and
        registration metadata may change after sealing.
DELETE FROM raw_snapshots ...
ERROR:  raw_snapshots rows are not deletable: a sealed snapshot is evidence...
```

The permitted update succeeded: linking `dataset_version_id`, `registered_at`
and `registered_by` was accepted, which is what makes a registration retry
possible after a failed one.

Audit-action parity, verified in both directions:

```
INSERT ... 'DATASET_BUILD_REGISTERED'    → accepted (the new action)
INSERT ... 'LEGACY_BASELINE_REGISTERED'  → accepted (widening, not replacement)
INSERT ... 'DATASET_PUBLISHED'           → ERROR: ck_audit_events_action_enum
UPDATE audit_events ...                  → ERROR: audit_events is append-only
```

### 5.3 Migration round trip

On a clean database:

```
0001→0002→0003→0004 applied
0004 → 0003 OK   (2 tables gone, function gone, five-action constraint restored)
0003 → 0004 OK   (cycle clean, 24 tables)
```

**One documented downgrade limitation, observed rather than assumed.** On a
database that already holds a `DATASET_BUILD_REGISTERED` event, the downgrade is
*refused*:

```
ERROR:  check constraint "ck_audit_events_action_enum" of relation
        "audit_events" is violated by some row
```

That is the correct outcome. Restoring the narrower constraint would require
either lying about it or deleting an append-only audit row. The migration will
not decide that for an operator; it stops and says so.

## 6. Security and failure cases exercised

Path traversal · absolute paths · backslashes · empty and `.` segments · NUL and
control characters · over-deep paths · over-long segments · symlinked files ·
symlinked directories · symlinks escaping the source · FIFOs · hard links ·
case-colliding paths · request-key collisions with differing content · checksum
mismatch · byte-length mismatch · missing response body · corrupt cache blob ·
missing manifest · corrupt manifest JSON · unknown manifest field · wrong schema
version · malformed `checksums.sha256` · checksum entries escaping the root ·
non-SHA-256 digests · uppercase hex · a forged `COMPLETE` status · a forged
`is_publishable` flag · a forged content hash · a required endpoint that never
reached terminal pagination · `FAILED` acquisitions · an existing final
directory · an existing *empty* final directory · a held concurrent claim · a
cache blob deleted mid-build · database registration failure after a filesystem
seal · one byte changed after sealing · one file removed · one file added.

Every corruption drill runs against a snapshot the test built in its own
temporary directory. The real legacy snapshot is only ever verified.

## 7. Phase-obsolete assertions, converted rather than deleted

| Test | Was | Now |
|---|---|---|
| `test_no_later_work_package_artefact_exists` (WP-05) | `pgx/ingestion/snapshots.py`, `scripts/dataset.py` and `data/raw` must not exist | Those exist now; the invariant kept is the *dependency direction* - no `pgx.scientific` module imports `pgx.ingestion` or names a snapshot type |
| `test_no_migration_creates_an_ingestion_or_snapshot_table` | `raw_snapshots` / `raw_artifacts` forbidden | WP-07/WP-08 tables forbidden instead, plus a new test that the two WP-06 tables come from `0004` alone |
| `test_ingestion_never_creates_a_scientific_record` | `DatasetVersion` among forbidden tokens, matched against raw text | Reads identifiers, not prose; `DatasetVersion` moved to its own test asserting ingestion *names* a dataset but never constructs one |
| `test_ingestion_publishes_no_dataset` | `DatasetPublicId` forbidden in `pgx/ingestion` | Naming a dataset ID is not publishing one; `PUBLISHED`, `QUALITY_CHECKED` and `approved_by` are forbidden instead |
| `test_the_application_layer_holds_only_release_and_ingestion_modules` | Three module groups | Four, with the WP-06 modules named explicitly |
| `test_every_entry_point_is_declared` | Five console scripts | Six, including `pgx-dataset` |
| `test_the_revision_chain_has_exactly_one_head` (WP-05) | `0003` must be the head | Exactly one head, and `0003` must still be somebody's parent - the invariant is linearity, not which revision is last |

## 8. What this evidence does not show

- That the legacy bytes are complete, current, or permitted to be used.
- That any source is approved: the checked-in registry still approves nothing.
- That Alembic can run these migrations.
- That a dataset can be quality-checked or published. It cannot, from here.
- That normal filesystem permissions provide WORM storage. They do not; see
  `docs/data/raw-snapshot-format.md` section 6.
