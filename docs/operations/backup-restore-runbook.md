# Backup and Restore Runbook

| Field | Value |
|---|---|
| Document ID | `DOC-OPS-001` |
| Work package | WP-23 (plan) / WP-24 (execution) |
| Machine-readable | `pgx/security/backup.py`, `data/security/wp23-backup-restore-status.json` |
| Plan version | `pgx-wp23-backup-restore/1` |
| **Current status** | **`backup_executed: false`, `restore_executed: false`, `restore_verified: false`, operational status `BLOCKED`** |

> **No backup has been taken and no restore has been performed.** This
> document is the procedure. WP-24 owns running it. Nothing in this repository
> may be read as saying a backup exists.

---

## 1. Scope: four things, and all four together

| Item | Kind | Encrypted at rest | Retention | Rotation |
|---|---|:-:|---|---|
| `POSTGRESQL_LOGICAL_DUMP` | PostgreSQL | ✅ | 90 days | daily; 90 daily + 12 monthly |
| `GOVERNED_AUDIT_STREAM` | PostgreSQL | ✅ | 10 years | daily, independent of the dump |
| `IMMUTABLE_ARTIFACT_MANIFESTS` | artifact | — | 10 years | on release, indefinite |
| `RESTRICTED_HOLDOUT_STORAGE` | restricted | ✅ | 10 years | on change |

**Why the pair, not just the database.** Audit rows and assessments pin
release, dataset and ruleset hashes. Restoring the database against a
different set of artifacts produces a system whose audit rows reference
releases it cannot resolve - so the two are captured and restored together or
the restore is not a restore.

**Why the audit stream separately.** A restore that silently dropped audit
rows would produce a chain that *verifies* - the remaining links are
internally consistent - while being incomplete. Exporting the stream with its
head sequence makes a truncated restore detectable.

**Why the artifact manifests are not encrypted.** They are published documents
containing no credential and no payload. Encrypting them would imply they were
sensitive and invite somebody to treat an unencrypted copy as a leak.

**What losing the holdout storage costs.** The set cannot be regenerated: a
regenerated case is a case the software has now seen. Losing it ends the
validation programme rather than delaying it.

---

## 2. Preflight

```
pgx-security backup-preflight
```

Reads configuration and the filesystem. **Runs no `pg_dump`, writes no
archive, restores nothing and contacts no database.**

| Check | Satisfied when |
|---|---|
| `DATABASE_CONFIGURED` | `DATABASE_URL` is set |
| `BACKUP_DESTINATION_CONFIGURED` | `PGX_BACKUP_DESTINATION` is set |
| `ARTIFACT_MANIFESTS_PRESENT` | the `data/` directory is readable |
| `RESTRICTED_STORAGE_CONFIGURED` | `PGX_VALIDATION_RESTRICTED_ROOT` is set |
| `RESTORE_TARGET_CONFIGURED` | `PGX_RESTORE_TARGET_URL` is set |

Its best possible outcome is `NOT_EXECUTED`, and it exits `2` while
`restore_verified` is false. **A preflight that exited 0 would be read in CI as
"the backup is fine".**

Current unmet checks: `DATABASE_CONFIGURED`,
`BACKUP_DESTINATION_CONFIGURED`, `RESTRICTED_STORAGE_CONFIGURED`,
`RESTORE_TARGET_CONFIGURED`.

---

## 3. Backup procedure (WP-24 executes)

1. Confirm the preflight reports no unmet check.
2. `pg_dump --format=custom --no-owner --no-privileges "$DATABASE_URL"` to a
   temporary path with mode `0600`.
3. Export `governed_audit_events` and `governed_audit_stream_head`
   separately, recording the head sequence in the manifest.
4. Copy the artifact manifests under `data/` by content hash.
5. Copy restricted holdout storage.
6. Encrypt every item whose kind is `POSTGRESQL` or `RESTRICTED` before it
   leaves the host.
7. Write a manifest naming each item, its size, its sha256 and the head
   sequence of the audit stream at the moment of capture.
8. Transfer to `PGX_BACKUP_DESTINATION`.
9. Remove the temporary files.

Nothing in this repository performs any of these steps.

---

## 4. Restore verification (WP-24 executes)

A restore is verified only when **all four** hold:

1. the dump restores into `PGX_RESTORE_TARGET_URL` - a **separate** target; a
   restore verified into the production database is not a verification, it is
   an outage;
2. the migration head check reports the expected revision;
3. `pgx-audit verify` reports the chain intact **and** its event count matches
   the head sequence recorded in the backup manifest;
4. every `release_manifest_hash` referenced by a restored audit row resolves
   against the restored artifact manifests.

A restore that only checked the database started would pass with an empty
audit table.

---

## 5. Status vocabulary

| Value | Meaning |
|---|---|
| `NOT_EXECUTED` | the procedure exists and has not been run |
| `BLOCKED` | a precondition is unmet, so it cannot be run |
| `EXECUTED_UNVERIFIED` | a backup was taken; no restore has been verified from it |
| `EXECUTED_VERIFIED` | a restore was performed and all four checks passed |

There is deliberately **no `PASS`**. A vocabulary containing one would
eventually have something assigned to it by a caller who meant "the
configuration looks right".

The published schema pins `backup_executed`, `restore_executed` and
`restore_verified` as `const: false`, and refuses `EXECUTED_VERIFIED` while
any of them is false. Changing that requires editing the schema in the open.
