# Container and CI security (WP-24)

| Field | Value |
|---|---|
| Document ID | `DOC-SEC-024` |
| Companion to | `docs/security/secret-management.md` (WP-23) |
| Status | Policy implemented. **No image built, no pipeline run.** |

---

## 1. The image

| Control | Implementation | Verified by |
|---|---|---|
| non-root runtime | `USER 10001:10001`, fixed uid so volume ownership is predictable | Dockerfile test; CI asserts `Config.User` |
| no compiler in runtime | `build-essential`/`libpq-dev` only in the builder stage | Dockerfile test |
| read-only filesystem | `read_only: true` + a 64 MB `/tmp` tmpfs | compose test |
| dropped capabilities | `cap_drop: ALL`, `no-new-privileges:true` | compose test |
| bounded resources | cpus, memory, `pids_limit` | compose test |
| pinned runtime | `python:3.11.9-slim-bookworm` | Dockerfile test |
| frozen dependencies | `uv sync --frozen` | Dockerfile test |
| no secret in a layer | `.dockerignore` + post-build filesystem audit | `audit_image_contents()` |

Code and sealed artifacts are owned by root and the process runs as `pgx`. The
application can read them and modify none — a container that cannot rewrite its
own ruleset is one whose release identity means something.

## 2. What may not be in an image

Checked on the **built filesystem**, not read off `.dockerignore`. An ignore
file states an intention; the audit measures the result, and only the second
would catch a `COPY` that named a path the ignore file did not anticipate.

- secrets and key material: `.env`, `*.pem`, `*.key`, `*.p12`, `deploy/secrets`,
  `deploy/tls`, `id_rsa`, `id_ed25519`;
- restricted and scientific input: `data/raw`, `data/canonical`,
  `data/evidence`, `data/legacy-baseline`, `data/migration`, `data/curation`,
  **`data/holdout`**;
- the test suite — not because it is secret, but because it carries the WP-20
  unsafe controls, which are deliberately dangerous code that exists to be
  detected;
- the seven frozen legacy scripts. `architecture.md` §15 step 10: legacy
  entrypoints are evidence, never application startup code.

`data/holdout/` does not exist yet. The prefix is in the list so that the day it
does, an image cannot quietly acquire it.

## 3. Runtime assets are an allowlist of files

Never `COPY data/`. A directory is a promise about what somebody will remember
not to put in it.

`pgx/deployment/runtime_assets.py` lists eleven files, each with a reason and a
checksum recorded at build time. The build fails on two distinct conditions:

- **absent** — the image would start and serve a page saying the catalogue is
  unavailable, which is honest but is not what was asked for;
- **checksum disagrees** — the artifact is not the one that was reviewed, and
  shipping it would attach a build's provenance to content nobody checked.

## 4. The pipeline

| Control | Implementation |
|---|---|
| least privilege | `permissions: contents: read` at the top level of both workflows |
| no `pull_request_target` | absent — it runs the base repository's token against a fork's code |
| no secrets to fork code | the integration database uses an ephemeral credential in the workflow, not a repository secret |
| isolated database | a per-job PostgreSQL service on port 55432; never the development compose service, which the integration suite would `downgrade base` |
| action pinning | every `uses:` must be a commit SHA; a job that uses **no action** verifies this first |
| concurrency + timeouts | per-ref groups, per-job `timeout-minutes` |
| cache correctness | `cache-dependency-glob: uv.lock` — a coarser key serves a dependency set from a different lock |
| no publish | there is no push step and no registry credential anywhere |

### The all-zero action pin

Resolving a tag to a commit SHA requires reaching the registry. The environment
these workflows were written in had none.

Rather than invent forty hex characters — a pin that looks precise, is wrong,
and would either fail confusingly or resolve to something nobody reviewed —
every `uses:` carries `0000000000000000000000000000000000000000`, which is
guaranteed not to be a commit in any git repository.

It fails loudly. It is unmistakably a placeholder. `action_pins()` classifies
it as `unresolved` and `pgx-deploy` reports it as a blocker. And
`scripts/resolve_action_pins.sh` turns every one into a real pin with one
command, refusing to write if any tag cannot be resolved — because a partially
pinned workflow is one where the unpinned entries are the ones nobody notices.

The pin-check job runs first and uses no action of its own: it clones with
`git` and the automatic token, so the check that verifies the pins does not
depend on an unpinned one.

## 5. Supply chain

**SBOM** is generated from real image or lockfile contents, never from
`pyproject.toml`. That file declares *ranges*; a bill of materials built from a
range lists what might be there.

**Vulnerability scanning** records scanner name, scanner version, advisory
database identity and date, image digest, result counts by severity, the
severity policy applied, and the exit code. When any of those is unavailable
the status is `BLOCKED` or `NOT_EXECUTED` — **never `PASS`**. A scan that could
not run is not a clean scan, and this is the most common way a supply-chain
report becomes false.

Severity policy: `CRITICAL` and `HIGH` block the release path. `UNKNOWN` is
reviewed as though `HIGH` until classified, because an unclassified finding is
not a low one.

**Ignores** are exact, justified, time-bounded and attributed. There is no
wildcard, no severity floor and no blanket ignore of a base image: an unbounded
ignore outlives the reason it was added, and the person who added it is rarely
the person who finds out. The current list is empty and is declared as an empty
tuple rather than omitted, so a reviewer can see there are none.

**Secret scanning** stays WP-23's `pgx-security secret-scan`, blocking, in the
pipeline. It reports a path, a line and a rule id; no matched value reaches a
log, an artifact or this document.

## 6. Secrets at deploy time

Files, mounted at `/run/secrets/<name>`. An environment variable is visible in
`docker inspect`, in a crash dump and in the process table.

Setting both `X` and `X_FILE` is **refused**, not resolved: a precedence rule
would let a rotated file be ignored in favour of a stale variable with nothing
anywhere saying so. An unreadable mount is a configuration failure, not an
absent secret — treating it as absent would start an application with
authentication silently unconfigured.

Nothing read as a secret reaches an exception message, a readiness detail, an
audit field or an artifact. Not the value, not a length, not a prefix, not a
digest — a digest of a low-entropy secret is a secret.

## 7. What is deliberately absent

- No switch that weakens `Secure`, `HttpOnly` or `SameSite`. Terminate TLS.
- No fallback when the Argon2 install fails. The failure is the signal.
- No image publish path.
- No `pgx-deploy` subcommand that deletes a volume, creates an account,
  activates a release, or approves anything.
