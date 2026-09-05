# Secret Management

| Field | Value |
|---|---|
| Document ID | `DOC-SEC-005` |
| Work package | WP-23 |
| Machine-readable | `pgx/security/secret_scan.py`, `data/security/wp23-secret-scan-report.json` |
| Scanner version | `pgx-wp23-secret-scan/1` |
| Current result | **CLEAN** - 0 findings, 31 classified, 1130 files scanned |

---

## 1. Where secrets come from, and where they never are

Secrets are supplied by **deployment configuration** and are never
source-controlled. `architecture.md` §13.

| Variable | Holds | Committed |
|---|---|:-:|
| `DATABASE_URL` | the application DSN | never |
| `PGX_BACKUP_DESTINATION` | encrypted backup target | never |
| `PGX_RESTORE_TARGET_URL` | restore-verification target | never |
| `PGX_VALIDATION_RESTRICTED_ROOT` | restricted holdout storage path | never |

`.env` is excluded by `.gitignore`. `.env.example` is committed and is a
**template** - it contains the shape of the configuration and no value, and
says so on its third line.

Settings objects never carry the DSN. `ApiSettings` records only *whether*
`DATABASE_URL` is set; readiness reads it at check time. A settings object
carrying a DSN is a settings object that appears in a repr, a log line and an
exception, which is exactly how credentials leak.

---

## 2. The scanner reports locations, never values

Every finding is a **path, a line number and a rule id**. Nothing else.

A scanner that printed the match would put the secret into CI logs, terminal
scrollback, a bug report and eventually a ticket - the same disclosure it
exists to prevent, arriving through the tool that found it. The published
schema has no `value`, `match`, `snippet` or `context` property and sets
`additionalProperties: false`, so a producer cannot add one.

`matched_length` is the only thing recorded about a match, so a reviewer can
tell a two-character false positive from a forty-character token without
seeing either.

Rule patterns are **not published**. A published regex is a published
description of what the scanner does not catch, which is more useful to
someone hiding a secret than to anyone else.

---

## 3. The rules

| Rule | Detects | Severity |
|---|---|---|
| `SEC-001-PRIVATE-KEY` | PEM private-key headers | CRITICAL |
| `SEC-002-CLOUD-TOKEN` | AWS, GitHub, OpenAI, Slack token shapes | CRITICAL |
| `SEC-003-BEARER-LITERAL` | `Authorization: Bearer` / session-cookie literals | HIGH |
| `SEC-004-PASSWORD-ASSIGNMENT` | non-placeholder credential assignments | HIGH |
| `SEC-005-DSN-CREDENTIAL` | connection strings with inline credentials | CRITICAL |
| `SEC-006-COMMITTED-ENV-FILE` | a committed `.env` (not `.env.example`) | HIGH |
| `SEC-007-ARGON2-HASH` | a committed password hash | HIGH |

Each has a **negative control** in `tests/fixtures/wp23/negative_controls.py`
proving it fires. A rule with no fixture proving it detects anything is a rule
nobody has run, and the first time anyone finds out is when it fails to catch
a real secret.

### Two refinements, and why

The first run reported 97 findings, every one a false positive. Two rules were
narrowed rather than allowlisted:

**`SEC-005`** now excludes placeholder credentials (`USER:PASSWORD@`,
`user:pw@`, `u:***@`) and development hosts (`localhost`, `127.0.0.1`, the
compose service names). Both are shapes that can never be a production
credential, and both are the *documented development configuration* the work
package explicitly scopes out. A DSN with a real-looking password pointing at
a real hostname still fires.

**`SEC-006`** now treats `.env.example`, `.env.sample`, `.env.template` and
`.env.dist` as templates.

The alternative was 97 permanent findings, and a rule that always reports 97
findings is a rule nobody reads - which is how the real one gets ignored too.

---

## 4. Allowlist: exact, scoped, explained

One entry. It names one path, one rule and one reason:

| Path | Rule | Reason |
|---|---|---|
| `docker-compose.yml` | `SEC-004-PASSWORD-ASSIGNMENT` | The documented development-only password for the disposable local PostgreSQL container. Not a production credential; no deployment reads it. |

There is **no directory-wide exclusion and no "skip tests"**. An excluded
directory is one where a real secret can later be committed unnoticed, and the
exception above is deliberately this one file and this one rule - a pattern
covering the directory would also cover a production DSN committed beside it.

---

## 5. Negative fixtures are classified, not ignored

Fourteen files contain deliberately unsafe-looking strings that prove *other*
work packages' redaction works - WP-19's scrubber tests, WP-02's
configuration-policy tests, WP-16's runtime-evidence tests, and WP-23's own
negative controls.

Each is named individually with what it is proving. Their findings still
appear in the scan report with `classification: NEGATIVE_FIXTURE`, so a
reader still sees them and a **real** secret committed into one of those files
would still be visible. The classification changes only that they do not count
toward the blocking total.

That is the difference between classifying and ignoring, and it is the
difference the work package asked for.

---

## 6. No real secret was introduced for testing

Every string in the negative controls is invented, matches no real system and
authenticates nobody. The private-key body is the word `NOT` repeated; every
token is a fixed literal with an obviously synthetic body.

No password hash is committed anywhere in this repository, real or otherwise -
`SEC-007` exists so that stays true.
