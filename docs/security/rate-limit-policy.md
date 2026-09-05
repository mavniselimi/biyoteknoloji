# Rate Limit Policy

| Field | Value |
|---|---|
| Document ID | `DOC-SEC-004` |
| Work package | WP-23 |
| Machine-readable | `pgx/security/rate_limit.py`, `data/security/wp23-rate-limit-policy.json` |
| Policy version | `pgx-wp23-rate-limit-policy/1` |
| Status | **implemented; no backend is composed, so every governed path fails closed** |

> This document declares limits. It reports **no** throughput, latency or load
> figure: WP-24 owns those, and a limit document carrying a performance number
> would be read as a capacity claim.

---

## The policies

| Policy | Scope | Limit | Window | Retry-After |
|---|---|:-:|:-:|:-:|
| `LOGIN_PER_USERNAME` | username digest | 5 | 300 s | 60 s |
| `LOGIN_PER_ORIGIN` | origin digest | 20 | 300 s | 60 s |
| `ASSESSMENT_PER_ACTOR` | actor digest | 60 | 300 s | 30 s |
| `EXPERT_REVIEW_MUTATION_PER_ACTOR` | actor digest | 30 | 300 s | 30 s |
| `ADMIN_MUTATION_PER_ACTOR` | actor digest | 30 | 300 s | 30 s |

Declared **before** any result was observed, for the reason WP-21 declares
metrics before any benchmark runs: a limit chosen after seeing traffic is a
limit chosen to permit the traffic.

---

## Semantics

**Windows are fixed and epoch-aligned.** A window starts at
`floor(now / window_seconds) * window_seconds`. Fixed rather than sliding on
purpose: a sliding window needs per-request history, and that history is a
table of timestamps keyed by the thing being limited - a far better log of who
tried what than the audit trail is allowed to be.

The count is incremented **before** the decision, so the attempt that exceeds
the limit is itself counted.

**`Retry-After` is bounded by the window.** A larger value would tell a client
to wait longer than the limit lasts, and the bound is enforced in
`RateLimitPolicy.__post_init__` rather than trusted.

---

## Three properties

### Failure is denial

A backend that cannot answer raises `RATE_LIMIT_UNAVAILABLE`. Login and
governed mutations fail closed rather than running unmetered.

Allow-on-error is the design that turns a database blip into an unlimited
password-guessing window. It is not implemented here and the fail-closed path
is exercised by test rather than asserted: `InMemoryRateLimitStore.fail_next`
exists so that a limiter which is *said* to fail closed has actually been run
in that state.

### A limiter can only deny

`check()` returns `None` or raises. There is no truthy return value, so no
call site can treat "the limiter said fine" as an authorisation, and no code
path where consulting the limiter turns a refused action into a permitted one.

An undeclared policy id raises `KeyError` rather than silently not limiting.

### Keys are digests

Every key is `sha256("pgx-wp23-rate-limit|" + identity)`. No username, actor
identifier or network address is stored, so a leaked rate-limit table reports
that *some* key was tried *n* times and names nobody.

The login limit applies **before** the user lookup, so unknown and known
usernames take the identical path and the limiter is not an enumeration oracle
either.

---

## Proxy headers

`X-Forwarded-For` is **not trusted and not read.** Until a trusted-proxy
policy is explicitly configured, the origin key is whatever the server itself
observed.

A spoofable header used as a limit key is a limit an attacker sets: they
choose a fresh value per request and the per-origin policy stops existing.
