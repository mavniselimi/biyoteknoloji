# Migration runbook (WP-24)

| Field | Value |
|---|---|
| Document ID | `DOC-OPS-024-B` |
| Chain | `0001` … `0011_wp23_auth_audit`, one head |
| Status | **`0011` has never been executed anywhere.** |

---

## 1. Why this is a person's command

An application that migrates itself on boot applies `0011` from whichever
replica starts first, concurrently. `0011`'s `downgrade()` then refuses to undo
it while any user, session or governed audit event exists — and that refusal is
correct, because dropping those tables destroys the account history and the
integrity chain together.

So the failure mode of automatic migration is a half-migrated schema that the
tool which half-migrated it cannot roll back. Nothing in this project runs
Alembic during application start-up, and
`tests/unit/deployment/test_container_and_build.py` asserts that the image's
`CMD` contains no migration.

## 2. Before

```bash
pgx-deploy migrate --dry-run
```

Prints:

- the **target**, with the credential removed and the host, port and database
  name intact;
- the revision chain read from the files with the AST — not by matching text,
  because `down_revision: Union[str, None] = "0010_…"` contains the word `None`
  in its *annotation*, and a line-matching reader finds no parents at all and
  reports eleven heads;
- how many heads there are, and whether the database is at the expected one.

Exactly one head, always. A branched history has no answer to "is this database
up to date".

## 3. Applying

```bash
pgx-deploy migrate
```

The DSN is passed through the environment, never on the command line: an
argument is visible in the process table to every user on the host, and a DSN
carries a password.

## 4. After

Readiness compares the database's `alembic_version` against
`PGX_API_MIGRATION_HEAD`. Set it to the head this build expects:

```
PGX_API_MIGRATION_HEAD=0011_wp23_auth_audit
```

A mismatch reports `migrations_behind` and readiness answers `NOT_READY`. The
probe reads `alembic_version` directly rather than importing Alembic: a health
check that loaded every revision module on every probe would take readiness
down for a broken revision file that has nothing to do with the database.

## 5. What `0011` installs

Five tables — `security_users`, `security_sessions`,
`security_rate_limit_counters`, `governed_audit_events`,
`governed_audit_stream_head` — and two trigger functions:

- `pgx_governed_audit_append_only()` rejects `UPDATE` and `DELETE`;
- `pgx_governed_audit_chain_guard()` locks the single head row `FOR UPDATE`,
  refuses an insert whose sequence does not follow it, and advances it in the
  same statement.

The application enforces the same chain rule in `SqlAlchemyAuditStore`. That is
not redundancy: the trigger is the half of the guarantee that survives a client
which does not use the ORM.

Do not disable the triggers to make a migration test faster.

## 6. Rolling back

**Do not.** `downgrade()` refuses while any user, session or governed audit
event exists, and forcing it destroys the account history and the chain.

A deployment rollback replaces the *image*, not the schema — see
`docs/operations/rollback-runbook.md`. That is only safe between images that
both work against the current schema, which is why the rollback drill records
two image identities rather than "the previous one".
