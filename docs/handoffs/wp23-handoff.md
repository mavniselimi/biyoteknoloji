# WP-23 → WP-24 Handoff

| Field | Value |
|---|---|
| Document ID | `DOC-HAND-023` |
| From | WP-23 - Authentication, RBAC, Audit, and Security Baseline |
| To | WP-24 - CI/CD, Deployment, Performance, and Reliability |
| Status | **WP-23 software COMPLETE; nothing configured; security gate BLOCKED** |

---

## 1. What WP-23 leaves behind

A complete security layer that **no deployment is running**. Every mechanism
exists and is tested; none is composed, because composing any of it needs a
database, a package install and a TLS terminator - all three WP-24's.

Left in place: Argon2id hashing with no fallback, local user lifecycle,
opaque server-side sessions with idle and absolute bounds, session-bound CSRF
including a protected login, a 25-permission RBAC registry with no hierarchy,
five declared rate-limit policies that fail closed, a hash-linked
append-only canonical audit trail over 41 governed actions, five tables and
migration `0011`, three CLIs, nine schemas, six artifacts, seven documents and
258 tests.

Left unchanged: `expert_review_performed: false`,
`clinical_validation_performed: false`, every holdout count, and the WP-20
safety gate's BLOCKED state.

---

## 2. The five things WP-24 must supply

| # | Needed | Effect when supplied |
|---|---|---|
| 1 | `argon2-cffi` installed in the image | `argon2_available` becomes true; `password_hashing` readiness passes |
| 2 | PostgreSQL + `DATABASE_URL` | `database_available`, `session_store`, `governed_audit` become reachable |
| 3 | `alembic upgrade head` through `0011` | `migration_0011_executed` becomes true |
| 4 | **HTTPS termination** at the staging ingress | the `Secure` session cookie can be sent; `https_termination_observed` becomes true |
| 5 | Backup and restore **executed and verified** | `backup_executed`, `restore_verified` become true |

None of the five can be satisfied by editing code. A sixth - an administrator
running `pgx-auth bootstrap-admin` - is a person's act, not WP-24's.

### The exact integration points

**`ServiceProvider`** gained six optional capabilities, all factories except
the CSRF service: `authentication_service`, `csrf_service`, `rate_limiter`,
`audit_sink`, `audit_reader`, `user_administration`. Each is `None` by
default and each `require_*` accessor raises the typed 503 that names it.

**`WebProvider`** gained `csrf_factory` and `authentication_service`.
`csrf_for(session)` returns the refusing verifier when either is missing,
which is what makes an unauthenticated page render its forms as unavailable
rather than as controls that fail after they are filled in.

**`ReadinessProbes`** gained four blocking probes: `password_hashing`,
`session_store`, `governed_audit`, `rate_limiter`. Each reports by name, so an
operator learns which dependency is missing rather than that "security" is
unavailable.

**`PGX_API_AUTH_MODE=SESSION`** is the only production-capable mode.
`STATIC_TOKEN` is refused in `PRODUCTION` by `apps/api/config.py`.

---

## 3. What WP-24 must not do

- **Do not relax the cookie policy to run over plain HTTP.** `SessionPolicy`
  raises if `Secure` or `HttpOnly` is false and refuses `SameSite=None`, on
  purpose: a flag that could turn either off is a flag somebody sets while
  testing and never sets back. Terminate TLS instead; the tests use
  HTTPS-origin clients.
- **Do not add a fallback when the Argon2 install fails in CI.** The failure
  is the signal. A pipeline that fell back to PBKDF2 to stay green would ship
  an image that hashes passwords with something weaker and reports itself
  healthy.
- **Do not seed a user in a migration, a fixture or an image.** There is no
  default account and no code path that creates one outside
  `pgx-auth bootstrap-admin`, which is interactive and audited as a bootstrap
  rather than as an ordinary creation.
- **Do not put a credential in an image layer, a build arg or a compose file
  outside the documented development one.** `pgx-security secret-scan` runs
  clean today; keep it in the pipeline and treat a finding as a build failure.
- **Do not turn the append-only trigger off to make a migration test
  faster.** It is the half of the immutability guarantee that survives someone
  with a `psql` prompt.
- **Do not mark `restore_verified` from a successful `pg_restore` alone.** The
  runbook's four checks exist because a restore that only confirmed the
  database started would pass with an empty audit table.
- **Do not report a performance number in the rate-limit policy document.** It
  declares limits; WP-24 owns throughput, latency and load, and mixing them
  makes a limit read as a capacity claim.

---

## 4. Migration `0011`

Written, reviewed, and **not executed anywhere**.

It creates `security_users`, `security_sessions`,
`security_rate_limit_counters`, `governed_audit_events` and
`governed_audit_stream_head`; installs `pgx_governed_audit_append_only`
(refuses UPDATE and DELETE) and `pgx_governed_audit_chain_guard` (refuses an
insert whose sequence does not follow the recorded head, and advances the head
in the same statement); seeds one stream-head row; and replaces WP-22's
`actor_authenticated = false` check with one permitting `true`.

`downgrade()` **refuses** while any user, session or governed audit event
exists. Do not force it: dropping those tables destroys the account history
and the integrity chain together.

Two persistence tests skip without PostgreSQL, with named reasons. When a
database appears they run - do not remove the skip policy to make the suite
look cleaner.

---

## 5. Operational notes

- `pgx-security gate-status` exits **2**. Correct. Exit 0 would mean the
  security layer was configured, running and had verified its chain against a
  real store.
- `pgx-security backup-preflight` exits **2** while `restore_verified` is
  false. A preflight that exited 0 would be read in CI as "the backup is
  fine".
- `pgx-security secret-scan` exits **0** and should stay a blocking CI step.
- `pgx-audit verify` exits **2** with `verified: null` - no store was
  inspected. `null` is not a passing result and must not be treated as one.
- `pgx-auth status` exits **2**; every other `pgx-auth` subcommand refuses and
  changes nothing while Argon2 or the database is missing.
- `pgx-verify run --profile security` is the suite to run in CI.

---

## 6. What is still owned by people, not by WP-24

| Waiting on | Owner |
|---|---|
| an administrator bootstrapping the first account | whoever operates the deployment |
| protocol approval by four named signatories | human and scientific reviewers |
| expert-holdout cases | scientific curators |
| named expert reviewers | whoever recruits them |
| claim boundary approval | human and scientific reviewers |

WP-24 clears five of the nine WP-23 blockers. The other four are not
engineering work.

---

## 7. The sentence to carry forward

WP-23 built a security layer nobody is running. A green suite here means the
software authenticates, authorises and records correctly when it is composed;
it does not mean any deployment is secure, and no document produced by this
repository may be presented as though it did.
