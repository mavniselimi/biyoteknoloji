# Authentication and Session Policy

| Field | Value |
|---|---|
| Document ID | `DOC-SEC-001` |
| Work package | WP-23 |
| Status | **policy defined; not configured in any deployment** |
| Machine-readable | `pgx/security/passwords.py`, `pgx/security/sessions.py` |

> No account exists in this repository. There is no default username, no
> default password, and no committed hash. Everything below describes what
> happens when a deployment is configured, and none is.

---

## 1. Password hashing

| Property | Value |
|---|---|
| Algorithm | **Argon2id**, and only Argon2id |
| Library | `argon2-cffi >= 23.1, < 26.0`, declared in `pyproject.toml` |
| Policy version | `pgx-wp23-password-policy/1` |
| Memory cost | 65536 KiB (64 MiB) |
| Time cost | 3 passes |
| Parallelism | 4 lanes |
| Hash length | 32 bytes |
| Salt length | 16 bytes |
| Storage format | the standard encoded PHC string, which carries its own parameters |

Parameters follow RFC 9106's second recommended option. The first (2 GiB) is
not used: this is a single-container prototype whose readiness budget is two
seconds, and a login path that allocated 2 GiB would be a memory-exhaustion
lever of its own.

### There is no fallback

If `argon2-cffi` cannot be imported, every entry point raises
`PASSWORD_HASHING_UNAVAILABLE` and readiness reports `password_hashing` as a
blocking failure. There is no PBKDF2 branch, no scrypt branch, no SHA path and
no development mode that skips hashing.

This is deliberate and is the single most important line in this document. A
fallback would be reached in exactly the situation where it must not be - an
install that silently failed - and would hash every password with something
weaker while the deployment reported itself healthy.

### Bounds

| Bound | Value | Why |
|---|---|---|
| Minimum length | 12 characters | A floor, not a strength claim. This system has no password-strength meter and does not pretend to. |
| Maximum size | 1024 bytes | Argon2's cost is set by its parameters, but the input is still encoded and copied. An unbounded password is a cheap way to make a server work. |
| Trimming | **none** | Silently changing a password makes a credential that worked once stop working, with no message anyone can act on. |
| Normalisation | **none** | Same reason. |

### Rehashing

`check_needs_rehash` is consulted **after** a successful verification and only
then. Rehashing on failure would let an attacker drive the hashing work with
wrong guesses; rehashing before verification would write a wrong password into
the account. A replacement is atomic with the login and is recorded in the
audit event as `rehashed: true`.

### Passwords never appear anywhere

Not in a log, an exception, a repr, an audit event, a CLI argument or an
artifact. `Password` wraps the plaintext with a fixed `__repr__`, compares in
constant time, and refuses to be a dictionary key. `pgx-auth` reads passwords
through `getpass` and has no `--password` flag - a command-line argument
appears in shell history, in `ps` output visible to every user on the host,
and in CI logs.

---

## 2. Account lifecycle

```
  bootstrap-admin ──▶ ACTIVE ──── disable ────▶ DISABLED
   (interactive,        │  ▲                       │
    audited as a        │  └──────── enable ───────┘
    bootstrap)          │
                   5 failed logins
                        ▼
                     LOCKED ──── 900s elapse, or admin unlock ──▶ ACTIVE
```

There is no `DELETED`, and no `pgx-auth delete-user`. A deleted user takes the
subject of their own audit history with them, and a trail whose actors can
vanish cannot answer the question it exists for.

**Every transition except a successful login increments `auth_generation`**,
which revokes every existing session for that account in one write. A
successful login is the exception because bumping there would revoke the
session the login just created.

| Operation | Revokes sessions | Audit action |
|---|:-:|---|
| bootstrap admin | — | `USER_BOOTSTRAPPED` |
| create user | — | `USER_CREATED` |
| change password | ✅ | `USER_PASSWORD_CHANGED` |
| change role | ✅ | `USER_ROLE_CHANGED` |
| disable | ✅ | `USER_DISABLED` |
| enable | ✅ | `USER_ENABLED` |
| lock (automatic) | ✅ | `USER_LOCKED` |
| unlock | ✅ | `USER_UNLOCKED` |
| revoke sessions | ✅ | `SESSION_REVOKED` |

### Usernames are identifiers, not people

3-64 characters from `a-z 0-9 . _ -`, starting alphanumeric, lowercased once
in `canonical_username`. ASCII only, which removes the whole class of
homoglyph-confusable identifiers rather than trying to detect them.

**An email address is refused as a username.** This system stores no name, no
email address, no telephone number and no personal detail: none is needed to
authorise a route or fill an audit row, and each would be personal data held
by a system with no reason to hold any.

---

## 3. Sessions

| Property | Value |
|---|---|
| Token | `secrets.token_urlsafe(32)` - 256 bits |
| Stored | `sha256(token)` only |
| Cookie | `__Host-pgx_session` |
| Attributes | `Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/`, no `Domain` |
| Idle expiry | 30 minutes, slides on use |
| Absolute expiry | 12 hours, never moves |
| Boundary | `now >= expires_at` is expired |
| Rotation | on every successful login |

The raw token is returned once and forgotten. A database dump contains nothing
replayable.

`sha256` rather than a password KDF for the digest, deliberately: the input is
256 bits of `secrets` output, so there is no dictionary to attack and no
entropy to stretch, and a KDF's cost would be paid on *every authenticated
request* for nothing.

### Checks that run on every request

1. the presented token's digest matches a stored session;
2. the session is not revoked;
3. `now < expires_at` on both bounds;
4. the account still exists and is `ACTIVE`;
5. `session.auth_generation == user.auth_generation`.

A session is not a fact established once at login. The account may have been
disabled, re-roled or had its password changed a second after it was issued,
and each must take effect on the next request rather than at the next expiry.

### The cookie policy is not configurable downward

`SessionPolicy` raises if `cookie_secure` or `cookie_http_only` is false, and
refuses `SameSite=None` and any path other than `/`. A flag that could turn
either off is a flag somebody sets while testing over plain HTTP and never
sets back.

**HTTPS is required.** The session cookie is `Secure`, so it is not sent over
plain HTTP, and login cannot complete without it. The policy is not relaxed
for local development: tests use HTTPS-origin test clients instead. WP-24 owns
the staging TLS terminator.

---

## 4. Login

Order, and every step matters:

1. **rate limit** on the username digest and the origin digest - before the
   lookup, so unknown and known usernames take the identical path;
2. **look up**, and run `dummy_verify()` when there is no such account;
3. **verify** the password with Argon2id;
4. **check status** - after verification, because returning early for a
   disabled account would answer faster than for an active one;
5. **rehash** if the stored parameters are obsolete;
6. **rotate** - revoke every existing session, then create a new one;
7. **audit** `LOGIN_SUCCEEDED` and `SESSION_CREATED` in the same transaction.

Steps 2, 3 and 4 all end in one `AuthenticationFailed` with one code and empty
details. The reason is recorded server-side and never travels.

### Logout

Revoke server-side **first**, then clear the cookie. Clearing first would
leave a live session the user believes is closed, usable by anyone holding a
copy of the token - and the user could not discover it, because their own
browser no longer has the cookie.

---

## 5. What is deliberately absent

| Absent | Why |
|---|---|
| public signup | P0 has no self-service accounts. `architecture.md` §13. |
| password-reset email | No email address is stored, and no mail path exists. |
| SSO / OAuth / external IdP | Out of scope for P0. |
| JWT as the browser session | A bearer token in a browser cannot be revoked server-side, which is the property sessions exist for. |
| default account | There is none, in any deployment, at any time. |
| `--password` flag | Shell history, `ps`, CI logs. |
| `delete-user` | Audit history needs its subject. |
