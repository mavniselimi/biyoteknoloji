# Liveness and readiness

Two endpoints answering two different questions. Confusing them is how a
working process gets restarted because a database is down.

## `GET /health/live`

Whether **this process** can serve. Process and event loop only: it opens
no connection, resolves no release, reads no pointer and calls nothing
external. It returns `200 {"status": "LIVE"}` and stays 200 while every
dependency below is failing.

It reports **no version and no release**. A liveness probe that reported a
version would be making a claim it has not checked, and one that reported a
release would be reading the pointer — which is a database call, which is
the thing liveness must not do. The handler takes no provider argument at
all, so it has nothing to reach a database with.

## `GET /health/ready`

Whether this instance should receive traffic. **200 only when every
blocking component is ready; 503 otherwise.**

### Blocking components

| Component | Ready when |
| --- | --- |
| `configuration` | settings loaded and accepted |
| `database` | the configured database answered within the probe budget |
| `migrations` | the schema is at the revision this build expects |
| `active_release` | a release is registered, active and verified against its recorded hashes |
| `claim_boundary` | named humans have approved the claim boundary |
| `authentication` | an authentication provider is configured |
| `password_hashing` | Argon2id is available, so a password can be verified |
| `session_store` | a server-side session store is composed |
| `governed_audit` | a canonical governed audit sink is composed |
| `rate_limiter` | a rate-limit backend is composed |
| `service_composition` | every service this environment requires is configured |

The four security components arrived with WP-23 and each blocks on its own.
They are separate rows rather than one `security` row because an operator
needs to know *which* dependency is missing, and because they fail for
different reasons: `password_hashing` is a missing Python package,
`session_store` and `governed_audit` are a missing database, and
`rate_limiter` is a missing backend. A single boolean covering all four would
report "security is not ready" and send somebody looking in the wrong place.

`password_hashing` failing is not a degraded mode. There is no weaker
algorithm to fall back to, by design: see `docs/security/authentication-and-session-policy.md`.

### Advisory components

| Component | Ready when | Blocks? |
| --- | --- | :-: |
| `evidence_build` | an evidence build is configured and readable | no |

The evidence build is advisory because the evidence endpoint needs it and
an assessment does not: an assessment reads evidence through the release it
pinned.

## Four properties, enforced once

**Independent.** Every component is probed on its own and reported on its
own. A readiness response that collapsed to one boolean would tell an
operator that something is wrong and nothing about what.

**Bounded.** Each probe runs inside a deadline and every exception it can
raise is caught, `ImportError` included — which is the honest answer where a
driver was never installed, and far more useful than a 500 saying the
readiness endpoint itself is broken.

**Silent about specifics.** `detail` is chosen from a fixed catalogue.
Never a DSN, never a path, never a hostname, never `str(exception)`. This
endpoint is unauthenticated, so everything in it is written as though a
stranger will read it.

**Read-only.** No probe writes, migrates, activates or assesses. Executing
an assessment as a health check would create a real stored assessment on a
schedule, from a synthetic input, in the table real ones live in — and the
count of real assessments is something this project has to be able to state
honestly.

## The detail catalogue

| Key | Text |
| --- | --- |
| `auth_not_configured` | No authentication provider is configured. |
| `auth_not_permitted` | The configured authentication provider is not permitted in this environment. |
| `claim_boundary_not_approved` | The claim boundary has not been approved by the named human and scientific reviewers. This is a governance gate, not a fault. |
| `composition_incomplete` | A service this environment requires is not configured. |
| `config_invalid` | Application configuration is incomplete or refused. |
| `argon2_missing` | Argon2id password hashing is unavailable, and there is no weaker algorithm to fall back to. |
| `audit_chain_unverified` | The governed audit chain has not been verified in this deployment. |
| `audit_sink_missing` | No canonical governed audit sink is composed, so no governed state change may proceed. |
| `database_not_configured` | No database connection is configured. |
| `database_unreachable` | The database did not answer within the probe budget. |
| `driver_missing` | The database driver is not installed in this deployment. |
| `evidence_build_missing` | No evidence build is configured, so evidence records cannot be read. |
| `migrations_behind` | The database schema is not at the revision this build expects. |
| `migrations_unknown` | The schema revision could not be determined. |
| `not_checked` | Not checked in this deployment. |
| `ok` | Ready. |
| `probe_failed` | The check did not complete. |
| `release_invalid` | The active release did not verify against its recorded hashes. |
| `rate_limiter_missing` | No rate-limit backend is composed; login and governed mutations fail closed. |
| `release_missing` | No active release is registered. |
| `session_store_missing` | No server-side session store is composed, so no session can be created or validated. |

## External services are not components

ClinPGx, any network dependency and any model provider are **deliberately
absent** from the component list. P0 readiness must not depend on a third
party's availability, and a probe that reached one would make an outage
elsewhere look like an outage here. `apps/api/readiness.py` imports nothing
that can open a socket, and a test asserts it.

## What this repository actually reports

Generated by running the checks against this repository as it stands:

```json
{
  "blocking_failures": [
    "active_release",
    "authentication",
    "claim_boundary",
    "database",
    "governed_audit",
    "migrations",
    "password_hashing",
    "rate_limiter",
    "service_composition",
    "session_store"
  ],
  "components": [
    {
      "blocking": true,
      "component": "active_release",
      "detail": "No active release is registered.",
      "ready": false
    },
    {
      "blocking": true,
      "component": "authentication",
      "detail": "No authentication provider is configured.",
      "ready": false
    },
    {
      "blocking": true,
      "component": "claim_boundary",
      "detail": "The claim boundary has not been approved by the named human and scientific reviewers. This is a governance gate, not a fault.",
      "ready": false
    },
    {
      "blocking": true,
      "component": "configuration",
      "detail": "Ready.",
      "ready": true
    },
    {
      "blocking": true,
      "component": "database",
      "detail": "No database connection is configured.",
      "ready": false
    },
    {
      "blocking": false,
      "component": "evidence_build",
      "detail": "No evidence build is configured, so evidence records cannot be read.",
      "ready": false
    },
    {
      "blocking": true,
      "component": "governed_audit",
      "detail": "No canonical governed audit sink is composed, so no governed state change may proceed.",
      "ready": false
    },
    {
      "blocking": true,
      "component": "migrations",
      "detail": "The schema revision could not be determined.",
      "ready": false
    },
    {
      "blocking": true,
      "component": "password_hashing",
      "detail": "Argon2id password hashing is unavailable, and there is no weaker algorithm to fall back to.",
      "ready": false
    },
    {
      "blocking": true,
      "component": "rate_limiter",
      "detail": "No rate-limit backend is composed; login and governed mutations fail closed.",
      "ready": false
    },
    {
      "blocking": true,
      "component": "service_composition",
      "detail": "A service this environment requires is not configured.",
      "ready": false
    },
    {
      "blocking": true,
      "component": "session_store",
      "detail": "No server-side session store is composed, so no session can be created or validated.",
      "ready": false
    }
  ],
  "status": "NOT_READY"
}
```

**This is the correct answer and it is not bypassed.** The claim boundary
is unapproved, no authentication provider is configured, no database is
configured, no migration revision can be determined, no release is active,
and none of the four WP-23 security dependencies is composed. Any one of
those is enough on its own; all of them are true. Liveness is 200
throughout.
