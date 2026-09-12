# PGx Platform V2

A research and prototype decision-support demonstrator for traceable
pharmacogenetic assessment.

> **This is not a clinical decision-maker and not a medical device.** It does
> not diagnose, prescribe, dose, select a treatment, or declare anything safe.
> The authoritative statement of what the system does and does not do is
> [`docs/architecture/intended-purpose.md`](docs/architecture/intended-purpose.md),
> which is currently **DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW**.
>
> P0 processes only synthetic or protocol-defined data. It does not accept real
> VCF, EHR, genotype, or laboratory data.

## Status

The project is built in numbered work packages defined by `architecture.md`.

| Work package | State |
|---|---|
| WP-00 — intended purpose, claims boundary, safety contract | Software complete; **human and scientific approval BLOCKED** |
| WP-01 — legacy baseline and migration harness | Complete; **Git checkpoint BLOCKED** (no commit) |
| WP-02 — package, domain model, PostgreSQL foundation | Offline scope complete; **build, install and database criteria BLOCKED** (no package index, no Docker daemon) |
| WP-03 — version registry, release bundle, rollback | Offline scope complete; **Alembic, PostgreSQL and concurrency criteria BLOCKED** |
| WP-04 — ingestion foundation, ClinPGx adapter | Offline scope complete; **live connectivity and source licensing BLOCKED** |
| WP-05 — scientific source strategy, provenance, licensing | Offline scope complete; **human source review and official licensing evidence BLOCKED** |
| WP-06 — immutable raw snapshots, dataset build start | Offline scope complete; **dataset approval and publication BLOCKED** |
| WP-07 to WP-22 | Software complete; scientific and human gates BLOCKED |
| WP-23 — authentication, RBAC, audit, security baseline | Software complete; **nothing configured**, security gate BLOCKED |
| WP-24 — CI/CD, deployment, performance, reliability | Software complete; **nothing operational**, Gate E BLOCKED |
| WP-25 — THS 6 evidence pack and final demonstration | Software complete; **THS 6 NOT achieved** — all six gates BLOCKED, 1 of 15 Definition of Done items satisfied, demonstration not executed, 0 of 9 sign-offs |

**WP-25 implementation complete is not THS 6 complete.** The evidence pack
software is implemented and the pack passes its own integrity check; the
programme it describes is blocked. Those are two separate fields in
`data/ths6/wp25-ths6-status.json` — `evidence_pack_integrity` and
`ths6_achieved` — and neither is derived from the other. `pgx-ths6
verify-pack` exits `0`; `pgx-ths6 status` exits `2`.

## Layout

```
pgx/domain/            framework-free domain layer (standard library only)
pgx/application/       release, ingestion and source-policy services and CLIs
pgx/ingestion/         source acquisition (transport, retry, cache, ClinPGx adapter)
pgx/scientific/        source governance: policy, licensing, provenance, gates
data/raw/              immutable raw snapshots, one directory per dataset ID
pgx/infrastructure/db/ SQLAlchemy ORM, mappers, repositories, unit of work, CLIs
config/                the reviewed scientific source registry
migrations/            Alembic migrations (0001 foundation, 0002 releases, 0003 source policy, 0004 snapshots)
schemas/               published JSON Schemas (release manifest, source registry, snapshot manifest)
scripts/               thin CLI wrappers and frozen WP-01 baseline tooling
tests/unit/            domain and schema-contract tests
tests/failure/         boundary-violation tests
tests/integration/db/  PostgreSQL integration tests (need a real database)
tests/regression/      frozen WP-01 legacy baseline suite
apps/api/              the HTTP API (WP-16); framework-free core plus a thin FastAPI binding
apps/web/              the server-rendered clinician/demo interface (WP-17)
docs/                  architecture, risk management, migration, evidence
```

The seven legacy scripts in the repository root are frozen WP-01 baseline
artifacts. They are not part of this package, are never imported by V2 code,
and are never reformatted.

## Domain guarantees

The domain layer is standard library only and enforces its contracts at
construction rather than by convention:

- **Deeply immutable values.** Metadata mappings and rule conditions are frozen
  recursively — nested mappings become read-only mappings, nested sequences
  become tuples — and the caller's original object is copied, so mutating it
  afterwards cannot reach inside a model. Values outside the JSON data model
  (`NaN`, `Infinity`, `set`, `bytes`, callables, non-string keys) are rejected
  at construction rather than silently coerced, because a value that cannot
  round-trip through JSON cannot have a reproducible hash.
- **Typed operation modes.** An assessment's mode is the WP-00 `OperationMode`
  enum checked against the claim boundary, never a free string, so a mode the
  boundary disables cannot be smuggled in as text.
- **One-way pipeline.** `EvidenceRecord → CuratedInterpretation →
  ComputableRule → AssessmentFinding`. Each stage requires the previous stage's
  identity by construction; no function anywhere turns source text directly
  into a calculated result.

## Requirements

- Python 3.10 or newer
- PostgreSQL 16 (the schema uses JSONB, `TIMESTAMPTZ`, and named constraints)
- [uv](https://docs.astral.sh/uv/) for dependency management

Dependencies are resolved in `uv.lock`. Container builds use
`uv sync --frozen`, so a changed `pyproject.toml` cannot silently produce a
different dependency set.

## Getting started

```bash
uv sync                                   # install dependencies
cp .env.example .env                      # then edit the placeholders

docker compose up -d postgres             # development database
docker compose --profile test up -d postgres-test   # disposable test database

uv run alembic upgrade head               # create the schema
uv run pgx-db-seed                        # deterministic foundation seed
uv run pgx-db-check                       # connectivity and schema report

uv run pgx-release show-active            # which release is in force
uv run pgx-release validate --public-id PGX-REL-20260829-001

# Acquisition. `plan` and `replay-cache` open no connection; `acquire` does.
uv run pgx-ingest-clinpgx plan --cache-dir ./cache --symbol CYP2C19
uv run pgx-ingest-clinpgx replay-cache --cache-dir ./cache --symbol CYP2C19

# Source policy. Reads a reviewed file; opens no connection and no database.
uv run pgx-source-policy validate               # exit 1 while any source blocks
uv run pgx-source-policy show cpic.database     # one source and what is outstanding
uv run pgx-source-policy review-checklist       # the steps a human works through
uv run pgx-source-policy inventory-legacy --check

# Raw snapshots. No network, no implicit overwrite, no publish command.
uv run pgx-dataset verify  --source-key clinpgx-legacy-v2 --dataset-id PGX-DATA-20260830-900
uv run pgx-dataset inspect --source-key clinpgx-legacy-v2 --dataset-id PGX-DATA-20260830-900

# Canonicalization. No network, no overwrite, no way to approve or settle anything.
uv run pgx-normalize verify        --build data/canonical/PGX-DATA-20260830-900
uv run pgx-normalize dq            --build data/canonical/PGX-DATA-20260830-900
uv run pgx-normalize queue         --build data/canonical/PGX-DATA-20260830-900
uv run pgx-normalize quality-check --build data/canonical/PGX-DATA-20260830-900
```

No scientific source is approved. Every entry in `config/scientific-sources.json`
is `PENDING_REVIEW` with every reuse permission `UNKNOWN`, because no official
terms document has been retrieved and no named human has reviewed one. The
publication gate therefore refuses every dataset, and a release may not be
activated on `source_registry.release_eligible` alone. There is no subcommand
that approves a source: approval is a human decision recorded in a reviewed
file. See `docs/scientific/source-strategy.md`.

Acquisition preserves raw source bytes and records what was retrieved. It
performs no resolution, deduplication or interpretation, and an acquisition run
asserts nothing about scientific validity or release eligibility.

Canonicalization turns a sealed snapshot into canonical genes and drugs, a
record of what could not be resolved, and data-quality metrics. It interprets
nothing: no significance, risk, severity, phenotype effect or recommendation
appears on a canonical record. An ambiguous name is never settled by ranking or
by taking the first result - it goes to a review queue with every candidate
attached. Identity is allocated explicitly and written down, never derived from
a name. Deduplication discards nothing: every provenance link survives, and two
records claiming one identity while disagreeing always block. The quality gate
fails closed and decides nothing: a passing gate is a precondition for a human
decision, and there is no command that marks a dataset quality checked,
publishes one or activates a release. See `docs/data/canonicalization-policy.md`.

### The web interface

```
pip install -e '.[web]'
uv run pgx-web        # WP-16's API and the eleven pages, one process
uv run pgx-api        # the API alone
```

A **research/prototype interface over synthetic and development-only inputs.**
It accepts no genotype, diplotype, allele, VCF, EHR record, diagnosis, dose or
narrative, and has no field in which any of those could be typed. Every page
carries the canonical research/prototype warning, fetched from
`pgx/domain/claims.py` rather than copied into a template, and it cannot be
dismissed.

Sign-in is an honest shell: no credential is accepted, stored or compared, and
no session exists (WP-23). The validation dashboard shows an empty state and
computes no percentage, because there is no denominator (WP-18, WP-21). The
expert-review screen is disabled with its reason stated (WP-22). None of the
three is simulated.

The seven cases in `data/demo/wp17-development-cases.json` are **development
fixtures, not validation evidence**: every one is `case_role: DEVELOPMENT`,
`is_validation_evidence: false`, `is_holdout: false`, and the case type has no
field for an expected result. See `docs/architecture/wp17-server-rendered-web.md`.

`pgx-db-seed` is idempotent: running it twice creates nothing the second time
and reports the same canonical payload hash. If the stored row has drifted from
the canonical payload it reports the drift and refuses to overwrite it.

## Tests

```bash
# Everything that needs no database and no third-party package:
python3 -m unittest discover -s tests -p 'test_*.py' -t .

uv run pytest tests/unit tests/failure                 # same suites under pytest

export TEST_DATABASE_URL=postgresql+psycopg://pgx_dev:pgx_dev_password@localhost:55432/pgx_test
uv run pytest tests/integration/db                     # needs PostgreSQL
```

The unit, failure and regression suites need only the standard library, so
they run before `uv sync` does. Integration tests **skip** without a database,
and each skip says so explicitly — a skip is not a pass.

## THS 6 evidence pack (WP-25)

```
pgx-ths6 status           # pack integrity and THS 6 achievement, separately
pgx-ths6 gates            # gates A-F rebuilt from their source artifacts
pgx-ths6 dod              # all fifteen P0 Definition of Done items
pgx-ths6 demo-preflight   # the demonstration's preconditions, in order
pgx-ths6 verify-pack      # recompute the pack's hashes and compare
```

The pack is `data/ths6/` (12 artifacts), `schemas/wp25/` (20 schemas) and
`docs/ths6/final/` (22 documents, with the executive summary and demo runbook
in Turkish). Start at `docs/ths6/final/README.md`.

There is no override: no `--force`, no `--assume`, no `--fixture` and no
`--ignore-blocker`. A gate's result is the conjunction of its conditions, and
the record type refuses at construction to hold `PASS` beside an unmet one.

`docs/ths6/` also holds three preliminary WP-local notes (WP-02, WP-03,
WP-04) that predate the pack. They are preserved unchanged and are not pack
members.

## Deployment (WP-24)

For a public single-host AWS EC2 deployment with automatic HTTPS on ports 80
and 443, use [`deploy/aws/README.md`](deploy/aws/README.md). The AWS topology
keeps both the application port and PostgreSQL off the public host interface.

One documented command. Every subcommand exits `0` only for work that ran and
held, `1` for a failure, `2` for blocked / not executed / stale, and `3` for a
malformed request. In this repository almost everything exits `2`, correctly:
there is no container runtime, no package index, no database, no release and
no approval.

```bash
pgx-deploy preflight              # measure this host: runtime, index, modules, assets, chain
pgx-deploy lock --check           # frozen check: does uv.lock match pyproject.toml?
pgx-deploy build                  # wheel and sdist twice, then the image
pgx-deploy migrate --dry-run      # print the target and the chain; change nothing
pgx-deploy migrate                # alembic upgrade head, explicitly, by a person
pgx-deploy staging-up             # start the isolated rehearsal topology
pgx-deploy smoke --url https://…  # liveness, readiness, cookie policy on the wire
pgx-deploy performance            # the 1,000-assessment run; refuses without a release
pgx-deploy backup --destination … # a temporary directory is not a destination
pgx-deploy restore-verify         # all four runbook conditions, or not verified
pgx-deploy rollback               # between two *identified* images
pgx-deploy release-validation     # aggregate every gate
pgx-deploy stop                   # stops containers; never deletes a volume
```

There is no subcommand that deletes a volume, creates a user, activates a
release or approves anything.

```bash
docker compose -p pgx_wp24_rehearsal -f docker-compose.wp24.yml up -d
```

The project name is not optional: Compose derives one from the directory when
none is given, which would make this topology share volumes with the
development one. Running this on a laptop produces a `LOCAL_STAGING_REHEARSAL`
— not a staging deployment, and no document may call it one.

Runbooks: [staging](docs/operations/staging-deployment-runbook.md) ·
[migration](docs/operations/migration-runbook.md) ·
[performance](docs/operations/performance-runbook.md) ·
[rollback](docs/operations/rollback-runbook.md) ·
[backup execution](docs/operations/backup-restore-execution-addendum.md).

Integration tests read **only** `TEST_DATABASE_URL`, refuse to run unless the
database name marks it as a test database, and never touch `DATABASE_URL`.

## Safety contract

Every design decision here answers to
[`docs/risk-management/safety-contract.md`](docs/risk-management/safety-contract.md).
The invariants that shape this codebase most visibly:

- missing data never becomes low or no risk (`SAFETY-INV-001`);
- only `VALIDATED` rules may execute (`SAFETY-INV-003`);
- `RAPID` and `ULTRARAPID` are distinct and never aliased (`SAFETY-INV-004`);
- every calculated finding carries traceable evidence (`SAFETY-INV-006`);
- an assessment without a release bundle cannot be persisted (`SAFETY-INV-007`);
- an assessment keeps the exact release it ran under, even after the active
  release moves on (WP-03).

## Licence

Proprietary. Not for distribution.
