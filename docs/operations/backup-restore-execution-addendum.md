# Backup and restore — execution addendum (WP-24)

| Field | Value |
|---|---|
| Document ID | `DOC-OPS-024-E` |
| Addendum to | `docs/operations/backup-restore-runbook.md` (WP-23) |
| Supersedes | nothing. WP-23's artifact stands. |
| Status | **No backup has been taken. No restore has been verified.** |

---

## 0. This is an addendum, not a replacement

WP-23 wrote the procedure and recorded `backup_executed: false`. That artifact
is a **true statement about the moment it was written**, and rewriting it to
match a later run is exactly the failure this project is built against.

WP-24 publishes a successor observation —
`pgx.deployment.backup_execution.backup_execution_status()`, schema
`schemas/wp24/backup-restore-execution.schema.json` — which names what it
supersedes and is read alongside the original rather than instead of it.

## 1. The four conditions, and why there are four

A restore is `VERIFIED` only when **all four** hold. `pg_restore` exiting zero
satisfies none of them; it says the archive was readable.

| # | Condition | The failure it catches |
|---|---|---|
| RESTORE-01 | restored into a **separate** target database | restoring into the source proves the dump is readable and destroys the thing being protected |
| RESTORE-02 | the restored database is at the **exact** expected Alembic head | data that survived into a schema the application was not written for is data the system cannot use |
| RESTORE-03 | the governed audit chain verifies **and** its event count matches the separately exported head sequence | a truncated restore produces a chain that verifies perfectly and is short; only the separately exported head catches it |
| RESTORE-04 | every referenced release manifest hash resolves against the restored immutable manifests | a restore that kept the claims and lost what they were based on has preserved nothing that can be defended |

An unevaluated condition reports `null` — not `false`. A report with an
unevaluated condition has incomplete verification, and collapsing that into
`false` would make it indistinguishable from a condition that was checked and
failed.

## 2. What a backup covers

1. the PostgreSQL dump;
2. a **separate** governed audit export and its head sequence — separate
   precisely so RESTORE-03 has something independent to compare against;
3. the immutable artifact manifests;
4. restricted holdout storage, **when it actually exists**.

Item 4 reports `null` today, not `false`. "There is nothing to back up" and
"there was something and we did not back it up" are different facts, and
creating an empty directory to call it captured would be worse than both.

## 3. What is not a backup

A dump written to a temporary directory beside the source database. It shares
the disk, the host and the failure.

`backup_execution_status()` records `destination_kind` — `none`, `temporary`,
`local_path` or `remote` — and refuses `operational_status: VERIFIED` for a
temporary destination. The schema enforces the same rule, so a document
asserting otherwise cannot be published.

The destination is reported as a **kind**, never a path. A path can name a
host, a bucket, an account or a customer.

## 4. Local rehearsal

A local drill that satisfies all four conditions is recorded as
`LOCAL_REHEARSAL_VERIFIED`, with `state: TEST_ONLY_REHEARSAL`.

That is a real and useful result. It is not an operational backup, it never
closes a release gate, and the distinction is in a field rather than in a
sentence somebody could omit.

```bash
pgx-deploy backup --destination /var/backups/pgx-rehearsal
pgx-deploy restore-verify --target-url "$PGX_RESTORE_TARGET_URL" \
    --local-rehearsal
```

## 5. Secrets

- Encrypt PostgreSQL and restricted material **at rest, before transfer**.
- Never commit an encryption key. `PGX_BACKUP_ENCRYPTION_KEY_FILE` is read only
  by `pgx-deploy backup`, only while a backup is being taken.
- No DSN, path, credential or key appears in any artifact this produces.
- Temporary paths are created with restrictive permissions and plaintext is
  deleted only when the exact path has been resolved and is safe to remove.

## 6. Current status

```
backup_executed        false
destination_kind       none
restore_verified       false
conditions satisfied   0 of 4  (4 unevaluated)
operational_status     BLOCKED
```

Owners: `DEPLOY_BACKUP_NOT_EXECUTED` — WP-24 operation on a host with a
database and a destination. `DEPLOY_RESTORE_NOT_VERIFIED` — the same.
