# WP-23 - Security Evidence Report

| Field | Value |
|---|---|
| Document ID | `DOC-EVD-023` |
| Work package | WP-23 - Authentication, RBAC, Audit, and Security Baseline |
| Status | **software IMPLEMENTED; nothing configured; nothing operating; security gate BLOCKED** |
| Machine-readable | `data/security/wp23-real-gate-status.json` |

> **This report is evidence about software.** It records that an
> authentication, authorisation and audit system was built and that its tests
> pass. It is **not** a penetration test, a security audit, a certification,
> or evidence that this system is safe to expose. No such assessment has been
> performed, and none of the statements below should be read as one.

---

## 1. Three outcomes, reported separately

| Outcome | State | Measured by |
|---|---|---|
| 1. Security software implemented | **COMPLETE** | 15 module markers; 258 tests |
| 2. Configured in this deployment | **NONE** | no database, no Argon2, no HTTPS, no composed service |
| 3. Operating | **NONE** | 0 users, 0 sessions, 0 audit events, no backup |

Outcome 2 is not partially done. Outcome 3 is not zero-because-quiet; it is
zero because outcome 2 is zero.

---

## 2. What was built

| Component | Location | Notes |
|---|---|---|
| Argon2id hashing, versioned policy | `pgx/security/passwords.py` | no fallback path exists |
| User lifecycle: ACTIVE / DISABLED / LOCKED | `pgx/security/users.py` | no delete, ever |
| Opaque server-side sessions | `pgx/security/sessions.py` | 256-bit tokens; only digests stored |
| Session-bound CSRF, pre-auth token | `pgx/security/csrf.py` | login is not exempt |
| RBAC registry: 25 permissions | `pgx/security/rbac.py` | no hierarchy |
| Rate limits: 5 declared policies | `pgx/security/rate_limit.py` | fails closed |
| Login / validate / logout | `pgx/security/service.py` | ordering is the security content |
| Canonical hash-linked audit | `pgx/infrastructure/audit/` | 41 governed actions |
| Persistence: 5 tables | `pgx/infrastructure/db/security.py` | append-only trigger, chain guard |
| Migration `0011` | `migrations/versions/` | **not executed** |
| Session resolver | `apps/api/auth.py` | mode decides credential origin |
| Login/logout flow | `apps/web/` | real form, real revocation |
| Secret scanner: 7 rules | `pgx/security/secret_scan.py` | reports locations, never values |
| Backup plan + preflight | `pgx/security/backup.py` | runs nothing |
| CLIs | `pgx-auth`, `pgx-audit`, `pgx-security` | passwords via `getpass` only |
| Schemas | `schemas/wp23/` | 9 |
| Artifacts | `data/security/` | 6 |
| Documents | `docs/security/`, `docs/operations/`, `docs/architecture/` | 7 |

---

## 3. Test evidence

| Module | Tests | What it asserts |
|---|---|---|
| `test_passwords.py` | 20 (8 skipped) | Argon2id only; **no fallback exists**, asserted by AST |
| `test_users_and_sessions.py` | 32 | every revoking transition; exact expiry boundary; cookie policy |
| `test_authentication_service.py` | 33 | login ordering; identical failures; dummy verification; rotation |
| `test_rbac.py` | 23 | ADMIN ⊉ REVIEWER; no hierarchy; routes match the registry |
| `test_csrf_and_rate_limit.py` | 23 | cross-session tokens fail; limiter fails closed |
| `test_secret_scan_and_backup.py` | 25 | every rule fires on its control; no value printed; nothing executed |
| `test_persistence.py` | 38 (2 skipped) | table shapes, constraints, triggers, refusing downgrade |
| `test_artifacts_and_gate.py` | 28 | artifacts current; no secret published; three answers stay apart |
| `test_governed_audit.py` | 36 | four tamper shapes; atomicity; closed metadata |
| **Total** | **258** | 10 explained skips, 0 unexplained |

`pgx-verify run --profile security`: **PASS**, 258 executed, 248 passed, 0
failed, 10 skipped (0 unexplained).

Five assertions are worth naming because they would catch a real regression
rather than a typo:

- **No weaker algorithm exists**, proven by parsing the module's AST rather
  than by hashing something. It is the half of the suite that runs *when
  Argon2 is absent* - which is the situation the fallback would be reached in.
- **The unknown-username path pays the hashing cost**, asserted from the
  hasher's call count. "Both responses looked the same" is a weaker claim than
  "both took the same work".
- **A token minted for one session fails against another**, and does so
  because the MAC key differs, not because a check compares identifiers.
- **The chain detects all four tamper shapes separately** - edit, delete,
  insert, reorder - rather than one test asserting "the chain works".
- **A failed audit append rolls the governed change back**, exercised through
  `fail_next_append` rather than asserted.

---

## 4. What is deliberately absent

| Absent | Why |
|---|---|
| any user account | none created; no default, no fixture, no bootstrap has run |
| any password hash in the repository | `SEC-007` exists so that stays true |
| any session, cookie or CSRF token | none issued |
| any audit event | the stream is empty |
| a weaker hashing path | it would be reached exactly when it must not be |
| a `--password` CLI flag | shell history, `ps`, CI logs |
| `delete-user` | audit history needs its subject |
| public signup, password reset | out of P0 scope |
| JWT as the browser session | it cannot be revoked server-side |
| SSO, OAuth, external IdP | out of P0 scope |
| a `PASS` in the backup vocabulary | it would be assigned by somebody who meant "configuration looks right" |

---

## 5. Integrations, and what each still reports false

| WP | Changed | Still false |
|---|---|---|
| 16 | `AuthMode.SESSION`; assurance on `Principal`; 4 new blocking readiness probes | `authentication_configured`, all four probes |
| 17 | session-bound CSRF; real login/logout; `csrf_configured` may now be true in production | `production_forms_available` |
| 18 / 21 | untouched | holdout counts, validation results |
| 19 | `VER-REQ-024`; 9 category rules; `security` profile; artifact generator | coverage, CI, PostgreSQL |
| 20 | SAFETY-INV-007 and -012 audit blockers re-owned from WP-23 to WP-24 | both invariants still blocked; safety gate still BLOCKED |
| 22 | `actor_authenticated` may now be `true` for a session; schema pin changed in the open | `expert_review_performed`, protocol approval |

**WP-20's blockers changed owner, not existence.** WP-23 implemented the
enforcement, so the blocker naming WP-23 as the implementer is gone. What
replaced it says the mechanism exists and no deployment is running it - which
is WP-24's, and is still a blocker. Neither invariant became satisfied, and
the safety gate did not become PASS.

Fifteen tests across six suites asserted "WP-23 absent" or pinned a list WP-23
legitimately extended. None was deleted; each became the property it was
defending, with a docstring recording the move.

---

## 6. Gate status, verbatim

```
work package         WP-23
implementation       IMPLEMENTED
security gate        BLOCKED

-- implemented ------------------------------------
  authentication_software_implemented        True
  session_management_implemented             True
  csrf_implemented                           True
  rate_limiting_implemented                  True
  canonical_audit_implemented                True
  argon2_dependency_declared                 True

-- configured -------------------------------------
  argon2_available                           False
  database_available                         False
  migration_0011_executed                    False
  authentication_configured                  False
  csrf_operational                           False
  rate_limiting_operational                  False
  https_termination_observed                 False

-- operating --------------------------------------
  real_users_configured                      null (nothing was inspected)
  audit_chain_verified                       None
  secret_scan_status                         CLEAN
  backup_executed                            False
  restore_verified                           False
  expert_review_performed                    False
  clinical_validation_performed              False
  release_may_proceed                        False
```

Nine blockers, each with a named owner:

| Code | Owner |
|---|---|
| `SECURITY_ARGON2_UNAVAILABLE` | deployment |
| `SECURITY_DATABASE_UNAVAILABLE` | deployment |
| `SECURITY_MIGRATION_NOT_EXECUTED` | deployment |
| `SECURITY_NO_REAL_USERS` | an administrator running `pgx-auth bootstrap-admin` |
| `SECURITY_AUTHENTICATION_NOT_CONFIGURED` | deployment |
| `SECURITY_HTTPS_NOT_OBSERVED` | WP-24 staging deployment |
| `SECURITY_AUDIT_CHAIN_NOT_VERIFIED` | deployment |
| `SECURITY_BACKUP_NOT_EXECUTED` | WP-24 operation |
| `SECURITY_CLAIM_BOUNDARY_NOT_APPROVED` | named human and scientific reviewers |

---

## 7. Argon2 is declared and not installed here

`argon2-cffi >= 23.1, < 26.0` is declared in `pyproject.toml` with a comment
explaining why there is no alternative. **It is not installed in this
environment and no package index is reachable from either the container or the
device VM**, so:

- `argon2_available` is `false` and readiness reports `password_hashing` as a
  blocking failure - which is the designed behaviour, not a workaround;
- eight behavioural tests skip with a named reason;
- the twelve structural tests run, and they are the ones that matter: they
  prove no weaker path exists *in the state where a fallback would be
  reached*.

This is reported rather than worked around. Installing the package is a
deployment step, and claiming Argon2 works here without having run it would be
the kind of statement this whole work package is arranged to prevent.

---

## 8. What this report does not establish

It does not establish that this system is secure. It does not establish that
the implementation is free of vulnerabilities - no penetration test has been
run and no third party has reviewed it. It does not establish that a
deployment configured from these modules would be safe, because no deployment
has been configured. It does not establish that the audit chain works against
real data, because there is no real data.

What it establishes is narrower: **if** a database is provisioned, **and**
`argon2-cffi` is installed, **and** HTTPS terminates in front of the
application, **and** an administrator bootstraps an account, **and** WP-24
executes a backup and verifies a restore - then this software will
authenticate that person, authorise them against an explicit matrix, and
record what they did in a chain nobody can afterwards edit.

That is the entire claim.
