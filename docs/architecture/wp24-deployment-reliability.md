# WP-24 — Deployment, CI/CD, Performance and Reliability

| Field | Value |
|---|---|
| Document ID | `DOC-ARCH-024` |
| Work package | WP-24 — CI/CD, Deployment, Performance, and Reliability |
| Source | `architecture.md` §14 (build, CI, deployment, reliability), §20 Gate E |
| Status | **Software IMPLEMENTED. Nothing operational. Gate E BLOCKED.** |

---

## 1. What this package is for

WP-23 built a security layer and composed none of it. WP-24 is the package
that would run it — and, in this repository, the package that reports
precisely why nothing is running it.

Its deliverables split into two kinds, and keeping them apart is most of the
design work:

- **Mechanism.** Composition, containers, pipelines, harnesses, drills. All of
  it exists and is tested.
- **Evidence.** A built image, an executed migration, an observed staging
  endpoint, a measured thousand assessments. Almost none of it exists, because
  the environment this was written in has no container runtime, no package
  index, no PostgreSQL server and no approved release.

Every artifact WP-24 produces reports both, in separate fields, and lets them
disagree.

## 2. The eight states

`pgx/deployment/vocabulary.py` defines them once. There is deliberately **no
`PASS`**, following WP-23's `OperationalStatus`.

| State | Means | Closes a gate? |
|---|---|---|
| `CONFIGURED` | a file, workflow or policy exists and was reviewed | no |
| `EXECUTED` | it ran here and completed | no |
| `OBSERVED` | a running system was watched answering | no |
| `VERIFIED` | it ran *and* its result was checked against a stated condition | **yes** |
| `BLOCKED` | a named precondition is absent, with an owner | no |
| `NOT_EXECUTED` | nothing prevented it; it has not been run | no |
| `STALE` | it ran against inputs that have since changed | no |
| `NOT_APPLICABLE` | the question was not asked | no |
| `TEST_ONLY_REHEARSAL` | it ran against labelled fixtures | no |

`EXECUTED` is not affirmative on purpose. A command completing is not a
condition holding, and a gate that accepted the first as the second is the
substitution this whole vocabulary exists to prevent.

`BLOCKED` and `NOT_EXECUTED` are separate because "there is no scanner" and
"nobody ran the scanner" need different actions from different people.

## 3. Runtime composition

```
                        ┌──────────────────────────────────────────┐
   HTTP request ───────▶│ RequestScopeMiddleware (raw ASGI)         │
                        │   _CURRENT_SCOPE.set(scope)               │
                        └───────────────┬──────────────────────────┘
                                        │
                        ┌───────────────▼──────────────────────────┐
                        │ RequestScope                              │
                        │   session   (lazy, one per request)       │
                        │   user_store ─┐                           │
                        │   session_store ─┤ all share that session │
                        │   audit_store ───┘                        │
                        │   rate_limiter ── own transaction ────────┼──▶ PG
                        └───────────────┬──────────────────────────┘
                                        │ finally: rollback, close
                        ┌───────────────▼──────────────────────────┐
                        │ ServiceProvider capability factories      │
                        │   each calls current_scope()              │
                        └──────────────────────────────────────────┘
```

Three properties, each a bug that would otherwise be found in production.

**One session per request, closed when the request ends.** A session opened at
import and shared is the classic web bug: two concurrent requests interleave
inside one transaction and one caller's commit publishes another's
half-finished work. The scope lives in a `ContextVar`, which is per-task by
construction — a thread-local would be shared between concurrent async
requests, which is precisely the failure being avoided.

The middleware is raw ASGI rather than `BaseHTTPMiddleware` for the same
reason: the latter runs the handler in a separate task, and a `ContextVar` set
in the middleware's task is not visible in the handler's. That failure is
silent — every capability raises "outside a request scope" — and it works in a
unit test and not under a server.

**A governed change and its audit record share one transaction.** Not "are
both written". Share one. `RequestScope.governed_transaction()` commits only
when the body completes, so an audit append that raises takes the change it was
recording down with it.

**A rate-limit hit does not share that transaction.** It is the one thing that
must survive the rollback. A failed login is refused, its transaction rolls
back, and the attempt must still be counted — or the limiter is off for exactly
the caller it is watching. `SqlAlchemyRateLimitStore` takes a *factory* and
commits for itself.

### The PostgreSQL counter

```sql
INSERT INTO security_rate_limit_counters
        (id, policy_id, key_digest, window_start, hit_count)
VALUES  (:row_id, :policy_id, :key_digest, :window_start, 1)
ON CONFLICT ON CONSTRAINT uq_security_rate_limit_counters_bucket
DO UPDATE SET hit_count = security_rate_limit_counters.hit_count + 1
RETURNING hit_count
```

One statement. The read-then-write alternative interleaves as read(4), read(4),
write(5), write(5) — and the fifth and sixth attempts both pass a limit of
five, in exactly the window a credential-stuffing client operates in.

The increment reads `security_rate_limit_counters.hit_count`, not
`EXCLUDED.hit_count`: the proposed value is always 1, so an `EXCLUDED`-based
increment would reset the counter on every conflict.

### "Configured" is measured, never declared

`compose_from_environment()` returns a `CompositionResult` whose `composed`
field is true only when an engine and an Argon2 hasher were actually built. It
is never read from `PGX_API_AUTH_MODE`: a variable can name a configuration the
host cannot provide, and a deployment claiming `SESSION` with no database, no
driver and no Argon2 is a deployment that cannot authenticate anybody.

## 4. The image

One image serves the API and the interface and runs every one-shot operation.
An operational command run from a *different* image is a command whose
dependency set nobody verified against the one serving traffic.

| Property | How |
|---|---|
| pinned runtime | `python:3.11.9-slim-bookworm`, exact patch |
| base digest | **not pinned** — see §8 |
| non-root | uid/gid 10001, fixed so volume ownership is predictable |
| no compiler in runtime | `build-essential` and `libpq-dev` exist only in the builder stage |
| frozen install | `uv sync --frozen` refuses when the lock and `pyproject.toml` disagree |
| Argon2 checked at build | `import argon2` runs in the builder; the build fails rather than shipping something that cannot hash |
| explicit runtime assets | seven named `data/` subdirectories, never `COPY data/` |
| no migration on start | `CMD` serves; migration is `pgx-deploy migrate` |
| liveness healthcheck | `/health/live` only — readiness in a `HEALTHCHECK` restarts a container because its database was briefly unreachable |

The runtime-asset allowlist is a list of **files with reasons**, not a
directory. A directory is a promise about what somebody will remember not to
put in it, and `data/` currently holds the raw ClinPGx snapshot, the legacy
baseline and every regression report — and would hold a restricted holdout
payload the day one exists.

`.dockerignore` states the intent; `audit_image_contents()` measures the built
filesystem afterwards. The two disagree the moment a `COPY` names a path the
ignore file did not anticipate, and only the second would catch it.

## 5. The pipeline

`architecture.md` §14.2's order, split across two workflows because "the
software works" and "this may be released" are different claims:

```
build-and-verify.yml                    release-validation.yml
  0. action pins (no action used)         9.  holdout regression
  1. format-check                        10.  build image (never published)
  2. lint                                11.  vulnerability + secret checks
  3. type-check                          12.  release validation artifact
  4. unit
  5. integration + migration  ── isolated PostgreSQL service
  6. API contract
  7. legacy regression
  8. safety invariants        ── pgx-safety check, by exit code
```

The software half runs while the release half is blocked. That is the point of
the split: engineering can proceed and be measured while the scientific gates
stay closed.

`holdout-regression` **fails** when the authorized holdout count is zero. Not
skips, not warns. A job that went green there would close the release path on
the scientific curators' behalf.

There is no push step anywhere. The absence is the policy.

## 6. Performance

Targets are declared in `pgx/deployment/performance.py` as a constant, before
any measurement exists — the same discipline as WP-21's metric registry, and
what `architecture.md` §14.3 requires.

| Target | Metric | Bound |
|---|---|---|
| PERF-001 | `latency_p50_ms` | ≤ 250 |
| PERF-002 | `latency_p95_ms` | ≤ 1000 |
| PERF-003 | `throughput_rps` | ≥ 20 |
| PERF-004 | `error_rate` | ≤ 0.001 |
| PERF-005 | `output_determinism` | == 1.0 |

Engineering and prototype targets for a demonstration deployment. Not clinical
performance claims, not a service level, and not evidence that any assessment
is correct.

**Percentile definition, fixed before any run:** nearest-rank on the sorted
sample of *completed* observations, `ceil(p/100 × n)` clamped to `[1, n]`.
Failed attempts count in `error_rate` and are excluded from latency — a request
that errored in 2 ms is not evidence that the system is fast. With `n == 0`
every percentile is `null`.

`execute_run()` refuses without an active validated release carrying **both** a
`release_id` and a `release_manifest_hash`. There is no flag that relaxes this.
Output determinism is reported separately from latency because latency varies
legitimately and output does not.

## 7. Reliability, rollback, backup

Thirteen declared drills (`REL-001` … `REL-013`), each naming the failure it
injects and the behaviour that must follow. A drill with no runner is
`BLOCKED` — never passed.

The two expectations that get inverted in practice:

- **A database outage must not affect liveness.** Liveness answers whether the
  process is alive; readiness answers whether it should receive traffic. A
  liveness probe consulting PostgreSQL has an orchestrator kill every replica
  during a failover that was about to resolve itself.
- **An external source or model outage must not affect P0 at all.** If either
  could move a readiness component, the offline deterministic demo that P0's
  Definition of Done requires would depend on the internet.

**Rollback** names two different operations. A deployment rollback replaces the
running image and must not downgrade the schema — `0011`'s `downgrade()`
refuses while any user, session or governed audit event exists, and that
refusal is correct. A governed release rollback moves the active pointer and
never edits a manifest: a release is immutable, and rolling back means pointing
somewhere else.

**Backup** is verified only when all four WP-23 runbook conditions hold: a
separate target, the exact Alembic head, a chain that verifies *and* whose
event count matches the separately exported head sequence, and every referenced
release manifest hash resolving. `pg_restore` exiting zero satisfies none of
them.

## 8. What this environment could not do, and what was written instead

| Needed | State here | What WP-24 did |
|---|---|---|
| package index | 403 from the proxy | one `uv lock` attempt, `BLOCKED`; **no lockfile fabricated** |
| `argon2-cffi` | not installable | composition blocks; no fallback exists |
| container runtime | `docker info` fails | image code exercised through an injected runner |
| build backend | `hatchling` absent | double-build code written; reports `BLOCKED` |
| PostgreSQL | no server, no driver | migration and counter written and structurally asserted |
| action SHAs | registry unreachable | all-zero sentinel + a resolver script |
| SBOM / vuln scanner | none installed | both report `BLOCKED`, never `PASS` |

The action-pin sentinel deserves a sentence. Resolving a tag to a commit needs
the registry. Rather than invent forty hex characters — a pin that looks
precise, is wrong, and would either fail confusingly or resolve to something
nobody reviewed — the workflows carry `0000…0000`, which is guaranteed not to
be a commit in any repository. It fails loudly, it is unmistakably a
placeholder, `pgx-deploy` reports it, and `scripts/resolve_action_pins.sh`
turns every one into a real pin with one command.

## 9. What WP-24 does not do

- It does not publish an image, deploy remotely, or activate a release.
- It does not create a user, a password, an approval or an expert.
- It does not delete a volume — there is no subcommand that can.
- It does not rewrite WP-23's artifacts; it publishes successors.
- It does not weaken the session cookie to accommodate HTTP.
- It does not let a fixture close a gate.
