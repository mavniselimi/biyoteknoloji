# Staging deployment runbook (WP-24)

| Field | Value |
|---|---|
| Document ID | `DOC-OPS-024-A` |
| Applies to | `docker-compose.wp24.yml`, `pgx-deploy` |
| Status | **Procedure documented. Never executed.** No staging environment exists. |

---

## 0. Read this first

Running this file on a laptop produces a **`LOCAL_STAGING_REHEARSAL`**. It is
not a staging deployment, nobody else can reach it, and no document produced
from it may call it one. `pgx-deploy` stamps the label into every artifact and
the schemas refuse a result that carries `environment_kind: LOCAL_REHEARSAL`
without it.

A real staging deployment additionally has: a hostname somebody else can
resolve, a certificate issued by an authority the client did not generate, and
an operator who is not the person who wrote the code.

## 1. Preflight

```bash
pgx-deploy preflight
```

Exit 0 means every prerequisite is present. Exit 2 lists what is missing, by
name, with an owner. In this repository it exits 2.

It measures rather than assumes: whether a container runtime *answered*
(`docker info`, not `docker --version` — the version command answers happily
with no daemon), whether an index *resolved*, whether `argon2` *imports*.

## 2. Secrets

Every secret is a **file**, mounted at `/run/secrets/<name>`. An environment
variable is visible in `docker inspect`, in a crash dump and in the process
table.

```bash
umask 077
mkdir -p deploy/secrets
printf '%s' 'postgresql+psycopg://USER:PASSWORD@postgres:5432/pgx_staging' \
    > deploy/secrets/database_url
printf '%s' 'USER'     > deploy/secrets/postgres_user
printf '%s' 'PASSWORD' > deploy/secrets/postgres_password
```

There are no defaults and no working examples. An example credential that
happens to be valid is a credential.

Setting both `X` and `X_FILE` is **refused**, not resolved. A precedence rule
would let an operator who rotated the file and forgot the variable keep running
on the old secret with nothing saying so.

## 3. Build

```bash
pgx-deploy build --reference pgx-platform:wp24-local
```

Verifies the runtime-asset manifest *first* — a build that produced an image
and then discovered a sealed artifact was missing would leave a tagged image
nobody should use, and the next `docker run` would find it.

Then: wheel and sdist built twice from clean staging directories with
`SOURCE_DATE_EPOCH` pinned, and the image built and inspected.

## 4. Start

```bash
docker compose -p pgx_wp24_rehearsal -f docker-compose.wp24.yml up -d
```

The project name is **not optional**. Compose derives one from the directory
when none is given, which would make this topology share a namespace — and
volumes — with the development one, so `down -v` in either would reach the
other's data.

Nothing runs an operation on start-up: no migration, no seed, no ingestion, no
release activation, no admin bootstrap, no backup.

## 5. Migrate — explicitly, once, by a person

```bash
pgx-deploy migrate --dry-run     # prints the target and the chain, changes nothing
pgx-deploy migrate               # applies
```

The target is printed **before** anything runs, with the credential removed and
the host, port and database name intact — those are what a wrong target looks
like.

Never automatic. An application that upgraded its own schema would apply `0011`
from whichever replica booted first, concurrently, against a database whose
`downgrade()` refuses to run while any user, session or governed audit event
exists.

## 6. Bootstrap the first account

```bash
docker compose -p pgx_wp24_rehearsal -f docker-compose.wp24.yml \
    --profile ops run --rm ops -m pgx.application.auth_cli bootstrap-admin
```

Interactive. `pgx-deploy` has no path to this and no subcommand that creates an
account: there is no default username and no default password anywhere in this
project, and the first account is a person's act, audited as a bootstrap rather
than as an ordinary creation.

## 7. TLS

```bash
# real staging
cp /path/to/server.crt deploy/tls/server.crt
cp /path/to/server.key deploy/tls/server.key
docker compose -p pgx_wp24_rehearsal -f docker-compose.wp24.yml \
    --profile staging up -d proxy
```

The application port is **not published** in the staging configuration. Ingress
reaches it over the internal network, which is what makes "HTTPS terminates at
the ingress" true rather than aspirational — a published app port is a
plaintext path around the terminator.

The session cookie is never weakened to accommodate HTTP. WP-23's
`SessionPolicy` raises if `Secure` or `HttpOnly` is false and refuses
`SameSite=None`, deliberately: a flag that could turn either off is a flag
somebody sets while testing and never sets back.

### Local rehearsal TLS

Permitted, under three conditions `pgx-deploy` enforces rather than suggests:

1. the result is labelled `LOCAL_STAGING_REHEARSAL` in every artifact;
2. verification runs **against the generated CA**, passed explicitly:
   `pgx-deploy smoke --url https://localhost:8443 --ca-bundle deploy/tls/ca.crt`;
3. `curl -k` is never used as evidence. Disabling verification does not
   demonstrate TLS — it demonstrates that verification was switched off, and a
   report containing it describes an experiment that did not test what it
   claims.

`smoke_check` has no parameter that disables verification. There is nothing to
pass.

## 8. Smoke

```bash
pgx-deploy smoke --url https://localhost:8443 --ca-bundle deploy/tls/ca.crt \
    --environment LOCAL_REHEARSAL
```

Checks, in order: liveness answers 200; readiness reports the truth with named
components; every `Set-Cookie` carries `Secure`, `HttpOnly`, `SameSite=Strict`,
and — for a `__Host-` cookie — no `Domain` and `Path=/`.

Checked on the wire, not in the source. The question is whether a proxy or a
framework setting changed the policy between the code and the browser.

No response body is recorded. A smoke report that captured bodies would capture
whatever the deployment was serving.

## 9. Stop

```bash
pgx-deploy stop
```

Stops containers. **Never** passes `-v`. There is no `pgx-deploy` subcommand
that deletes a volume: destroying a database volume is a decision a person
makes with a command they typed, and a tool that offered it would eventually be
run with it by somebody who meant `--verbose`.

## 10. Exit codes

| Code | Means |
|---|---|
| 0 | the work ran and the condition held |
| 1 | the work ran and something was wrong |
| 2 | blocked, not executed, or stale |
| 3 | malformed request |

Exit 2 is not a failure of the software. It is a statement that the thing being
asked about did not happen — which is what almost every subcommand returns in
this repository, correctly.
