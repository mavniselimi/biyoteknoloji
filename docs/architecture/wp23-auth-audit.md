# WP-23 - Authentication, RBAC, Audit, and Security Baseline

| Field | Value |
|---|---|
| Document ID | `DOC-ARCH-023` |
| Work package | WP-23 - Authentication, RBAC, Audit, and Security Baseline |
| Status | **software IMPLEMENTED; nothing configured; security gate BLOCKED** |
| Machine-readable | `pgx/security/`, `pgx/infrastructure/audit/`, `pgx/infrastructure/db/security.py` |
| Artifacts | `data/security/wp23-*.json` |
| Schemas | `schemas/wp23/` |
| Migration | `migrations/versions/0011_wp23_auth_audit.py` (not executed) |
| CLI | `pgx-auth`, `pgx-audit`, `pgx-security` |
| Architecture source | `architecture.md` sections 13, 14, 16, 17, 20 |
| Companion documents | `docs/security/*.md`, `docs/operations/backup-restore-runbook.md` |

> **This document describes machinery, not a secured deployment.** WP-23 builds
> authentication, sessions, CSRF, RBAC, rate limiting and a canonical audit
> trail. This repository configures none of it: there is no database, no
> Argon2 package installed, no HTTPS termination, no secret configuration and
> no user account. No penetration test, security audit or certification has
> been performed, and nothing here is one.

---

## 1. Three answers, and why they must stay apart

Every status field in this work package belongs to exactly one of three
questions:

| Question | Kind of fact | Current answer |
|---|---|---|
| Is the security software implemented? | about files | **yes** |
| Is it configured in this deployment? | about the environment | **no** |
| Is it operating? | about what has happened | **no** |

Collapsing any two produces the sentence WP-23 exists to avoid: *"security:
done"*. A reader shown one boolean is told the third answer while being shown
the first, and the gap between them is a database, a TLS terminator, a package
install and an administrator.

So `data/security/wp23-real-gate-status.json` reports all three, in separate
fields, and lets them disagree - `implementation_status: IMPLEMENTED`,
`security_gate_status: BLOCKED`.

---

## 2. Argon2id, or an error. There is no third outcome

`pgx/security/passwords.py` imports `argon2` and nothing else. There is no
`hashlib` import, no PBKDF2 branch, no scrypt branch and no development mode
that skips hashing. If `argon2-cffi` is not installed, every entry point
raises `PASSWORD_HASHING_UNAVAILABLE` and readiness reports
`password_hashing` as a blocking failure.

That refusal is the design. A fallback would be reached in exactly the
situation where it must not be - a deployment whose dependency install
silently failed - and would then hash every password with something weaker
while reporting itself healthy. `tests/unit/security/test_passwords.py`
asserts the absence by parsing this module's AST, so a future edit that adds a
fallback fails a test rather than a review.

**In this environment `argon2-cffi` is not installed** and no package index is
reachable, so the behavioural half of that test suite skips with a named
reason. The structural half runs, and it is the half that matters: it is what
proves no weaker path exists *when Argon2 is absent*.

Parameters are RFC 9106's second recommended option - 64 MiB, three passes,
four lanes - recorded as a versioned policy so `check_needs_rehash` can
recognise an obsolete hash and replace it after a successful login. Rehashing
happens after verification and only then: rehashing on failure would let an
attacker drive the work, and rehashing before verification would write a wrong
password into the account.

---

## 3. Sessions: opaque, server-side, and revocable in one write

```
  LOGIN                                    SESSION ROW
  ─────                                    ───────────
  rate limit (username digest, origin)     session_id
      │  fail closed                       user_id, role
  pre-auth CSRF verify                     token_digest   ← sha256(token)
      │                                    csrf_secret    ← per session
  lookup user  ─── unknown? ──┐            auth_generation
      │                       │            created_at
  argon2id verify        dummy_verify      last_seen_at  → idle bound
      │                       │            absolute_expires_at (never moves)
  status ACTIVE?              │            revoked_at / revocation_reason
      │                       │
      ├── any failure ────────┴──▶ AuthenticationFailed
      │                             one code, empty details
      ▼
  revoke every existing session   ← session fixation cannot survive login
  create new session + new CSRF secret
  audit LOGIN_SUCCEEDED + SESSION_CREATED, same transaction
      │
      ▼
  Set-Cookie: __Host-pgx_session=<raw token>; Path=/; SameSite=Strict; Secure; HttpOnly
```

**The raw token exists in two places and neither is storage.** It is returned
once by the service, placed in a `Set-Cookie` header, and forgotten. The store
holds `sha256(token)`, so a database dump contains nothing replayable.
`SessionRecord` has no field a raw token could occupy, and its `__repr__` is
fixed so a dataclass repr cannot print the digest or the CSRF key material.

**Expiry is a boundary written once.** `now >= expires_at` is expired, defined
in `SessionRecord.is_expired_at` and used everywhere - "expired" implemented
twice becomes `>` in one place and `>=` in the other, and the session that
lives one extra second is the one nobody can reproduce.

**`auth_generation` is the whole revocation mechanism.** Password change, role
change, disable and lock each increment it, and every session created before
the increment stops validating on its next request. One integer beats a sweep
over a session table: the sweep can be interrupted halfway, and the half that
did not run is a set of live sessions belonging to an account somebody just
disabled.

**The cookie policy cannot be weakened by configuration.** `SessionPolicy`
raises if `cookie_secure` or `cookie_http_only` is false and refuses
`SameSite=None`. A flag that could turn either off is a flag somebody sets
while testing over plain HTTP and never sets back. The `__Host-` prefix is
enforced by the browser itself, so a misconfiguration that widened the
cookie's scope stops the cookie being accepted rather than silently
broadening it.

---

## 4. Every login failure looks the same

Unknown username, wrong password, disabled account, locked account and even a
malformed username all raise one `AuthenticationFailed` with one code and
empty details. The *reason* is recorded server-side in the audit row and never
travels.

Sameness of response is not enough on its own. An unknown username would
otherwise return in microseconds while a known one paid 64 MiB and three
passes, and the difference is measurable from outside regardless of how
identical the body is. So the unknown path runs `dummy_verify()` against a
fixed hash of a value nobody knows, and a disabled account is verified
*before* being refused - returning early for it would answer faster than for
an active one, which is a status oracle.

`tests/unit/security/test_authentication_service.py` asserts the hasher's call
counts, not just the response bodies: "the expensive work happened" is a
stronger claim than "the responses matched".

---

## 5. CSRF is bound to a session, and login is not exempt

The token is `HMAC-SHA256(session_csrf_secret, session_id || bucket)`. A token
minted for session A cannot verify against session B - not because a check
compares two identifiers, but because the key differs and the MAC does not
match. Rotating the session mints new key material in the same write, which is
what makes "the previous token stops working" structural rather than a cleanup
step somebody could omit.

The token contains no session identifier: a page that is cached,
screenshotted or pasted into a bug report must not hand over the session's
name.

**Login is protected too.** A login form without CSRF lets an attacker post
their own credentials on a victim's behalf; the victim then works inside a
session the attacker controls and can read. There is no session yet at that
point, so the binding comes from a short-lived host-scoped
`__Host-pgx_preauth` cookie the server set when it rendered the form - same
construction, different key source, same refusal when it is absent.

WP-17's `StaticTokenCsrfVerifier` remains as a development fixture and is
honest about being one: a single process-global token protects nothing once an
attacker has seen one page.

---

## 6. RBAC: 25 permissions, no hierarchy, and ADMIN is not a reviewer

`pgx/security/rbac.py` is the authoritative registry. Every permission names
its holders explicitly; there is no inheritance, no wildcard and no "admin can
do anything" shortcut. A hierarchy is convenient right until a role is added
in the middle of it, and then every gate written to mean "only a reviewer"
quietly means "a reviewer or anyone above one".

**ADMIN holds no `expert_review.*` permission at all.** An administrator who
could review would destroy the property WP-22 exists for: a review is evidence
only if the reviewer did not build the thing they reviewed. An administrator
who must review holds a second account whose exact role is `EXPERT_REVIEWER` -
and even then WP-22's assignment check and payload permit still apply. This
registry grants the *ability to attempt* an operation; it never grants an
assignment.

`DEMO_USER` is a subset of both other roles. That is architecture.md §13's
explicit design - "EXPERT_REVIEWER: demo permissions plus assigned blind
reviews" - written out permission by permission rather than inherited, and
safe only because `role_holds` is literal membership. A test asserts the two
containments that must *never* exist: ADMIN ⊉ EXPERT_REVIEWER, and
EXPERT_REVIEWER ⊉ ADMIN.

Authentication roles do not touch curation roles. `curation.administer` means
"may operate the curation tooling", not "may approve their own revision";
WP-09's separation-of-duty rules are untouched, and this registry deliberately
has no permission naming a curation *decision*.

---

## 7. The canonical audit trail

A fifth stream, beside the four that already existed, and **beside** them
rather than on top:

| Trail | Owner | Chained? | Status |
|---|---|---|---|
| `audit_events` | WP-03 | no | unchanged, rows and meaning intact |
| assessment audit | WP-14 | no | unchanged |
| curation audit | WP-10 | no | unchanged |
| `expert_review_audit_events` | WP-22 | yes | unchanged except `actor_authenticated` |
| `governed_audit_events` | **WP-23** | yes | new, empty |

**Nothing is backfilled.** A historical row was written by a system with no
authentication, and giving it an actor and an assurance level would be
manufacturing provenance - the exact failure an audit trail exists to prevent.
A test asserts migration 0011 contains no `INSERT ... SELECT` into the new
stream and no `UPDATE` of any historical table.

Each event carries: event id, schema version, stream and sequence, previous
hash, event hash, actor, role, **authentication mechanism and assurance**,
session reference, UTC time, correlation id, action, object type and id,
outcome, result code, input and output hashes, the software / dataset /
ruleset / release identity and hashes, previous and new governed state, and
**typed** metadata from a closed vocabulary. There is no free-form bucket: a
mapping that accepted arbitrary keys would sooner or later receive a request
body, because the place that builds an audit event is the place that has one.

Forty-three field names are refused at any nesting depth - password, token,
cookie, phenotype, medication list, holdout payload, expected response,
request body, filesystem path. The check walks nested mappings and lists,
because the first version of any such check looks at top-level keys and the
first thing to defeat it is one level of nesting.

### 7.1 Four tamper shapes, one mechanism

Editing a field, deleting an event, inserting one and reordering two are four
different problems. A timestamp catches none of them.

```
event_hash = sha256(canonical(previous_hash, payload))

  edit    → the event's own hash changes → successor's previous_hash mismatches
  delete  → the sequence is no longer contiguous
  insert  → same
  reorder → both
```

Serialization is canonical - sorted keys, fixed separators, ASCII-escaped - so
a chain verifies identically on every machine. A chain whose hashes depended
on dictionary insertion order would verify where it was written and fail
everywhere else, which is indistinguishable from tampering.

### 7.2 Two appenders cannot fork the chain

`governed_audit_stream_head` holds one row per stream, locked `FOR UPDATE`
before every append. `SELECT max(sequence)` followed by an insert is a
read-then-write race whose losing side is a forked chain: two events at the
same sequence, each linking to the same predecessor, both of which verify in
isolation. The trigger `pgx_governed_audit_chain_guard` additionally refuses
any insert whose sequence does not follow the recorded head, so a caller that
skipped the lock is refused by the server rather than trusted.

### 7.3 Atomicity, in both directions

For a **successful** governed state change, the change and the audit append
commit together. `GovernedAuditService.record` raises `AuditAppendError`, the
caller's transaction does not commit, and the change is gone. A success nobody
can account for is worse than a refusal: the refusal tells the operator
something happened.

For a **refused** operation, `record_refusal` swallows its own failure and
returns `False`. If it raised, an audit outage would convert every controlled
refusal into a 500 - and a 500 is a different answer from a refusal, which is
how "the audit system is down" becomes "the request was actually processed".

---

## 8. Rate limiting denies; it never permits

Policies are declared before any result is observed, for the reason WP-21
declares metrics before any benchmark runs: a limit chosen after seeing
traffic is a limit chosen to permit the traffic.

`RateLimiter.check` returns `None` or raises. There is no truthy return value,
so no call site can treat "the limiter said fine" as an authorisation. A
backend that cannot answer **denies** - allow-on-error is the design that
turns a database blip into an unlimited password-guessing window.

Keys are digests. A login limit is keyed by `sha256(username)` and
`sha256(origin)`, so a leaked rate-limit table says some key was tried *n*
times and names nobody. `X-Forwarded-For` is not read: a spoofable header used
as a limit key is a limit an attacker sets.

The limit applies **before** the user lookup, so unknown and known usernames
take the identical path and the limiter is not an enumeration oracle either.

---

## 9. The authentication mode decides where a credential is read from

| Mode | Reads | Production-capable |
|---|---|:-:|
| `UNCONFIGURED` | nothing; answers 503 | — |
| `STATIC_TOKEN` | the `Authorization` bearer header | no |
| `SESSION` | the `__Host-pgx_session` cookie | **yes** |

The dependency is the security content. `get_principal` reads the cookie under
`SESSION` and the header under `STATIC_TOKEN`, and never tries both. A
resolver that accepted either and used whichever worked would leave a
production deployment honouring development tokens - silently, because the
routes would keep working and nobody would look.

**Assurance is a governed vocabulary value, not a number.** Only a validated
server-side session may carry `SESSION`; a development token carries
`TEST_STATIC_TOKEN` forever. `GovernedAuditEvent` refuses the combination
`assurance=SESSION` with any other mechanism, and so does a database check
constraint - because a direct insert bypasses the model and cannot bypass the
server.

---

## 10. Secret scanning: locations, never values

Seven rules, each with a negative-control fixture proving it fires. Every
finding is a path, a line number and a rule id. A scanner that printed the
match would put the secret into CI logs, terminal scrollback, a bug report and
eventually a ticket - the same disclosure it exists to prevent, arriving
through the tool that found it. The published schema has no `value`, `match`
or `snippet` property and sets `additionalProperties: false`, so one cannot be
added by a producer.

Allowlist entries are exact - one path, one rule, one reason. There is no
directory-wide exclusion and no "skip tests", because an excluded directory is
one where a real secret can later be committed unnoticed.

Existing negative fixtures are **classified, not ignored**. Fourteen files
carry deliberately unsafe-looking strings that prove other work packages'
redaction works; each is named individually with what it is proving, and its
findings still appear in the scan output with `classification:
NEGATIVE_FIXTURE`. A real secret committed into one of those files would still
be visible to a reader.

Two rule refinements were made after the first run reported 97 findings, all
false positives: a DSN whose credentials are placeholders or whose host is
`localhost` is documented development configuration, and `.env.example` is a
template rather than a secret. A rule that reported ninety false positives
forever is a rule nobody reads, which is how the real one gets ignored too.

---

## 11. Backup and restore: the plan is WP-23's, running it is WP-24's

Four scope items - the database dump, the audit stream exported separately,
the immutable artifact manifests, and restricted holdout storage - each with a
retention period, a rotation policy, an encryption requirement and a statement
of what is lost without it.

`pgx-security backup-preflight` reads configuration and reports what is
missing. It runs no `pg_dump`, writes no archive, restores nothing and
contacts no database, and its best possible outcome is `NOT_EXECUTED`. A
preflight that exited 0 would be read in CI as "the backup is fine".

`backup_executed`, `restore_executed` and `restore_verified` are all `false`
and are `const: false` in the published schema. They are not placeholders
awaiting a flag: there is no code path in the module that sets any of them
true, because setting one truthfully would require observing an execution and
this module observes configuration.

---

## 12. Current state, in one table

| Question | Answer | Where it is measured |
|---|---|---|
| Is the security software implemented? | yes | `security_module_markers()` |
| Is `argon2-cffi` declared? | yes | `pyproject.toml` |
| Is Argon2 available here? | **no** | import attempt |
| Is a database configured? | **no** | `DATABASE_URL` |
| Has migration 0011 run? | **no** | not executed anywhere |
| Is authentication configured? | **no** | provider composition |
| Is CSRF operational? | **no** | provider composition |
| Is rate limiting operational? | **no** | provider composition |
| How many real users exist? | `null` - no store inspected | injected store |
| Has the audit chain been verified? | `null` - no store inspected | injected reader |
| Is HTTPS termination observed? | **no** | WP-24 |
| Secret scan | CLEAN, 0 findings, 31 classified | live scan |
| Has a backup run? | **no** | nothing executed |
| Has an expert reviewed anything? | **no** | unchanged by WP-23 |
| Has clinical validation happened? | **no** | unchanged by WP-23 |
| May a release proceed? | **no** | gate BLOCKED |

---

## 13. What WP-24 owns

CI pipeline and its ordering; the Docker image and its provenance; staging
deployment and **HTTPS termination**; the 1,000-assessment performance run;
the rollback drill; **executing** backup and restore and reporting what
happened; repeat-run determinism across deployments; vulnerability scanning of
built images.

WP-23 wrote the checklist and the preflight. WP-24 runs them, and only then
can `backup_executed` and `https_termination_observed` become true.
