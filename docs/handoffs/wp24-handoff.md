# WP-24 → WP-25 Handoff

| Field | Value |
|---|---|
| Document ID | `DOC-HAND-024` |
| From | WP-24 — CI/CD, Deployment, Performance, and Reliability |
| To | WP-25 — THS 6 Evidence Pack and Final Demonstration |
| Status | **WP-24 software COMPLETE. Nothing operational. Gate E BLOCKED.** |

---

## 1. The direct answers WP-25 needs

The brief for this handoff asks twelve questions. Here they are, in order,
without qualification:

| Question | Answer |
|---|---|
| What was implemented? | The whole WP-24 software surface — see §2 |
| What was actually executed? | Targeted tests, the full suite, the artifact generators, one `uv lock` attempt, one secret scan. Nothing else. |
| What remains blocked? | 17 of 19 required release gates — see §4 |
| Does a real staging endpoint exist? | **No.** None has ever existed. |
| Was TLS actually observed? | **No.** No handshake has been performed against anything. |
| Did migration 0011 run? | **No.** Against no database, anywhere, ever. |
| Backup: operational or rehearsal? | **Neither.** No backup was taken at all. |
| Did the 1,000-assessment run occur? | **No**, and it could not: there is no eligible release. |
| Was rollback exercised? | **No.** Fewer than two image identities and zero eligible releases exist. |
| Was CI ever run by a provider? | **No.** This repository has no commits, so nothing has been run against. |
| Was an image built, scanned, published or deployed? | **None of the four.** |
| Exact remaining human/scientific actions | §5 |

## 2. What WP-24 leaves behind

**`pgx/deployment/` — 20 modules.** An eight-state vocabulary with no `PASS`;
an environment probe that measures rather than declares; `*_FILE` secret
reading that refuses ambiguity; the runtime composition (request-scoped
sessions, one transaction for a governed change and its audit record, a
PostgreSQL rate-limit counter as one atomic statement); the row-to-record
seam; provenance, runtime assets, packaging, image, migration, smoke,
performance, reliability, rollback, backup execution, supply chain, release
validation, gate status, artifacts, CI status.

**`apps/api/deployment.py`.** The ASGI half: a raw-ASGI request-scope
middleware, a request-scoped principal resolver, four real readiness probes,
and the provider they compose into.

**Build and deploy surface.** `Dockerfile` (two stages, non-root, no compiler
in runtime, explicit runtime assets), `.dockerignore`,
`docker-compose.wp24.yml` (app, postgres, restore target, staging proxy,
one-shot ops), `deploy/proxy/Caddyfile`, `deploy/secrets/` and `deploy/tls/`
with READMEs and no working examples.

**Pipelines.** `build-and-verify.yml` and `release-validation.yml`, implementing
`architecture.md` §14.2 in order. `safety-gate.yml` is untouched.

**One command.** `pgx-deploy`, fifteen subcommands, exit codes 0/1/2/3.

**Seventeen schemas, nine committed artifacts, 163 tests, ten documents.**

## 3. The five things a later environment must supply

None of these can be satisfied by editing code.

| # | Needed | Effect when supplied |
|---|---|---|
| 1 | a reachable package index | `uv lock` produces a real lockfile; `argon2-cffi` installs; `hatchling` installs and the double-build runs |
| 2 | a container runtime | the image builds; content audit, non-root check and SBOM become possible |
| 3 | a PostgreSQL server | `0011` executes; the counter, the triggers and the chain guard are exercised for the first time |
| 4 | a staging host with a real certificate | TLS is observed; the `Secure` cookie can be sent; `https_termination_observed` becomes true |
| 5 | a CI provider and a commit to run against | `ci_executed` stops being `null` |

A sixth — an administrator running `pgx-auth bootstrap-admin` — is a person's
act, exactly as it was at the WP-23 handoff.

## 4. The gate, exactly

```
WP-24 implementation       IMPLEMENTED
WP-24 deployment gate      BLOCKED
Gate E                     BLOCKED
required gates satisfied   2 of 19
release_may_proceed        false
```

The two that pass: `runtime_assets` (eleven declared files, all present, all
checksums recorded) and `secret_scan` (CLEAN, 1,214 files, 0 findings).

The seventeen that do not, with owners:

| Gate | Blocker | Owner |
|---|---|---|
| lockfile | `DEPLOY_LOCKFILE_ABSENT` | the build environment |
| distributions | `DEPLOY_BUILD_BACKEND_UNAVAILABLE` | the build environment |
| image_build | `DEPLOY_IMAGE_NOT_BUILT` | a host with a container runtime |
| image_contents | `DEPLOY_IMAGE_NOT_BUILT` | a host with a container runtime |
| migration | `DEPLOY_MIGRATION_NOT_EXECUTED` | an operator |
| staging_smoke | `DEPLOY_STAGING_NOT_DEPLOYED` | WP-24 operation |
| tls_termination | `DEPLOY_TLS_NOT_OBSERVED` | whoever provisions the ingress |
| safety_gate | `DEPLOY_SAFETY_GATE_BLOCKED` | WP-20 and the scientific track |
| holdout_regression | `DEPLOY_NO_HOLDOUT_EVIDENCE` | **scientific curators** |
| expert_review | `DEPLOY_EXPERT_REVIEW_NOT_PERFORMED` | **named expert reviewers** |
| claim_boundary | `DEPLOY_CLAIM_BOUNDARY_NOT_APPROVED` | **named human and scientific reviewers** |
| security_gate | `DEPLOY_SAFETY_GATE_BLOCKED` | the deployment |
| vulnerability_scan | `DEPLOY_VULNERABILITY_SCANNER_UNAVAILABLE` | the build host |
| sbom | `DEPLOY_SBOM_NOT_GENERATED` | the build host |
| backup_restore | `DEPLOY_RESTORE_NOT_VERIFIED` | WP-24 operation |
| rollback_drill | `DEPLOY_ROLLBACK_NOT_EXERCISED` | WP-24 operation |
| performance | `DEPLOY_PERFORMANCE_NOT_EXECUTED` | WP-24 operation against an eligible release |

The three in bold are not engineering work and no environment closes them.

## 5. What is owned by people

| Waiting on | Owner |
|---|---|
| claim boundary approval | named human and scientific reviewers |
| protocol approval by four signatories | human and scientific reviewers |
| expert-holdout cases | scientific curators |
| named expert reviewers, and a completed blind review | whoever recruits them |
| an administrator bootstrapping the first account | whoever operates the deployment |
| a decision to provision staging infrastructure | whoever owns the budget |

## 6. What WP-25 must not do with this

- **Do not present a local rehearsal as staging.** Every WP-24 artifact carries
  `environment_kind`, and a `LOCAL_REHEARSAL` result carries
  `LOCAL_STAGING_REHEARSAL` in a field the schema requires. If WP-25 ever runs
  the rehearsal topology, that label goes into the evidence pack with the
  numbers.
- **Do not cite a `TEST_ONLY_REHEARSAL` as evidence.** It never closes a gate,
  by property rather than by convention.
- **Do not read `null` as `0`.** Every unmeasured field in every WP-24 document
  is `null` on purpose. A THS claim built on a zero latency or a zero error
  rate would be built on a run that never happened.
- **Do not resolve the action pins by hand.** Run
  `scripts/resolve_action_pins.sh` on a host with network. The all-zero
  placeholder is deliberate and is guaranteed not to be a commit; a
  hand-written SHA would either fail confusingly or resolve to something nobody
  reviewed.
- **Do not rewrite WP-23's artifacts, and do not rewrite WP-24's.** Publish
  successors, as WP-24 did.

## 7. Where the numbers are

| Claim WP-25 might make | Artifact |
|---|---|
| what a build would be made from | `data/deployment/wp24-build-provenance.json` |
| what the image must contain | `data/deployment/wp24-runtime-asset-manifest.json` |
| the declared performance targets | `data/deployment/wp24-performance-targets.json` |
| the declared reliability drills | `data/deployment/wp24-reliability-drills.json` |
| the four restore conditions | `data/deployment/wp24-restore-conditions.json` |
| which secrets exist, by mechanism | `data/deployment/wp24-secret-configuration.json` |
| every gate and its state | `data/deployment/wp24-release-validation.json` |
| the WP-24 gate | `data/deployment/wp24-real-gate-status.json` |
| Gate E | `data/deployment/wp24-gate-e-status.json` |

Each validates against a schema under `schemas/wp24/`, and each schema refuses
the document nobody should be able to publish.

## 8. The sentence to carry forward

WP-23 built a security layer nobody was running. WP-24 built the deployment
that would run it, and nobody is running that either — so what this repository
now has is a complete, tested, honest account of a system that has never been
deployed. A green suite here means the deployment software behaves as its tests
describe. It does not mean anything is deployed, and no document produced from
this repository may be presented as though it did.
