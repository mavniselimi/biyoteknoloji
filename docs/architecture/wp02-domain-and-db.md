# WP-02 - Domain Model and PostgreSQL Foundation

| Field | Value |
|---|---|
| Document ID | `DOC-ARCH-002` |
| Work package | WP-02 - V2 Repository, Domain Model, and PostgreSQL Foundation |
| Migration revision | `0001_wp02_foundation` (single head) |
| Companion documents | `docs/architecture/wp02-er-diagram.md`, `docs/ths6/wp02-foundation-evidence.md` |
| Architecture source | `architecture.md` sections 5, 6, 7, 8.4, 9, 14, 15, 17 (WP-02), 22 |
| Revision | WP-02 corrective passes 1 and 2, 2026-08-29 — see sections 12 and 13 |

> **Nothing here is scientific content.** WP-02 builds the type and storage
> contract that scientific work will later have to satisfy. It contains no
> evidence, no interpretation, no validated rule, and no assessment logic.
>
> **WP-00 approval remains BLOCKED** (`DRAFT / AWAITING HUMAN AND SCIENTIFIC
> REVIEW`) and **WP-01's Git checkpoint remains BLOCKED** (no commit exists).
> WP-02 changed neither.

---

## 1. Scope and non-goals

**In scope**

- installable package definition and tool configuration (`pyproject.toml`);
- a framework-free domain layer: identifiers, enums, models, errors, ports,
  canonical hashing;
- SQLAlchemy 2.x ORM models, explicit mappers, typed repositories, unit of work;
- the first Alembic migration creating eleven foundation tables;
- a deterministic, idempotent, non-scientific foundation seed;
- a development PostgreSQL service in `docker-compose.yml`.

**Explicitly out of scope** — each belongs to a later work package, and building
it now would imply an identity or capability that does not yet exist:

| Deferred | Owner |
|---|---|
| `software_versions`, ruleset versions and membership, `release_bundles`, `active_release`, activation and rollback | WP-03 |
| ClinPGx acquisition, raw artifacts, ingestion runs | WP-04, WP-06 |
| Canonical resolution, dedup, data quality | WP-07 |
| Curation workflow and rule approval governance | WP-09, WP-10 |
| Phenotype, coverage and assessment engines | WP-12 to WP-14 |
| Assessment persistence and reporting | WP-14, WP-15 |
| FastAPI, web UI, authentication, audit | WP-16, WP-17, WP-23 |
| Validation cases, expert review | WP-18, WP-22 |

`AssessmentRepository` is defined as a **port** so the domain boundary is
complete, but WP-02 ships no implementation and no assessment table: an
assessment requires a release bundle identity, and the release registry is
WP-03 (`SAFETY-INV-007`).

## 2. Dependency direction

```
apps/ (WP-16, WP-17)          not created yet
        |
        v
pgx.application (WP-14)       not created yet
        |
        v
pgx.infrastructure.db  ---->  pgx.domain
        (imports)             (imports nothing but the standard library)
```

The domain layer imports only `dataclasses`, `datetime`, `decimal`, `enum`,
`hashlib`, `json`, `math`, `re`, `typing`, `uuid` — and itself. This is verified
by `tests/unit/domain/test_dependency_boundaries.py`, which parses every module
with `ast` rather than importing it, so the guarantee holds in an environment
where SQLAlchemy is not installed at all.

`OperationMode` is **not** redefined here. WP-00 owns it in
`pgx/domain/claims.py`, and a test asserts it is declared exactly once in the
whole package.

## 3. Domain entities

| Domain model | Purpose | Key invariant |
|---|---|---|
| `SourceRegistryEntry` | A registered scientific or technical source | An `INTERNAL_SYSTEM` source can never be release-eligible |
| `DatasetVersion` | An immutable dataset build | `PUBLISHED` requires approver and approval time |
| `Gene`, `Drug` | Canonical entities plus aliases | Symbol/name must already be normalised |
| `EvidenceRecord` | Source truth | **No** attention, risk, dose or treatment field; no method producing a finding |
| `CuratedInterpretation` | A human curation decision | Requires ≥1 evidence record; `CURATED` requires rationale, reviewer, review time |
| `ComputableRule` | A machine-evaluable rule | Requires a curated interpretation; `condition` is declarative data, never code; `VALIDATED` requires approval **and** evidence |
| `RulesetVersion` | A versioned rule collection | `VALIDATED`/`FROZEN` require approval metadata |
| `ReleaseBundle` | Pinned software + dataset + ruleset | Requires both version identities |
| `Assessment` | One deterministic run | Requires a `ReleaseBundleId` and a canonical input hash |
| `CoverageAssessment` | What could be evaluated, and why not | Non-`FULL` coverage requires a reason code; only `FULL` permits `NO_ACTIVE_ATTENTION` |
| `AssessmentFinding` | One calculated finding | Requires rule identity **and** ≥1 evidence record; cannot be `NOT_ASSESSED`; carries no dose or preference field |

Every model is `@dataclass(frozen=True, slots=True)`, rejects naive datetimes,
normalises aware datetimes to UTC, and refuses mutable collections.

### 3.1 The one-way pipeline

```
EvidenceRecord -> CuratedInterpretation -> ComputableRule -> AssessmentFinding
```

Each stage requires the previous stage's identity by construction. There is no
constructor, classmethod, or helper anywhere that accepts an `EvidenceRecord`
and returns an `AssessmentFinding`; a test asserts that no such function exists.
Source text can therefore never become a calculated result without passing
through curation and rule approval.

## 4. Domain to ORM mapping

Mapping is explicit and lives only in `pgx/infrastructure/db/mappers.py`. There
is no automap and no reflection, and the two class hierarchies are disjoint —
no domain dataclass inherits from `DeclarativeBase`, and every ORM class name
ends in `ORM`.

| Domain model | ORM model | Table | Mapper pair |
|---|---|---|---|
| `SourceRegistryEntry` | `SourceRegistryORM` | `source_registry` | `source_registry_to_orm` / `..._to_domain` |
| `DatasetVersion` | `DatasetVersionORM` | `dataset_versions` | `dataset_version_to_orm` / `..._to_domain` |
| `Gene` | `GeneORM` + `GeneAliasORM` | `genes`, `gene_aliases` | `gene_to_orm` / `gene_to_domain` |
| `Drug` | `DrugORM` + `DrugAliasORM` | `drugs`, `drug_aliases` | `drug_to_orm` / `drug_to_domain` |
| `EvidenceRecord` | `EvidenceRecordORM` | `evidence_records` | `evidence_to_orm` / `evidence_to_domain` |
| `CuratedInterpretation` | `CuratedInterpretationORM` + `InterpretationEvidenceORM` | `curated_interpretations`, `interpretation_evidence` | `interpretation_to_orm` / `..._to_domain` |
| `ComputableRule` | `ComputableRuleORM` + `RuleEvidenceORM` | `computable_rules`, `rule_evidence` | `rule_to_orm` / `rule_to_domain` |
| `RulesetVersion`, `ReleaseBundle`, `Assessment`, `AssessmentFinding`, `CoverageAssessment` | *(none)* | *(none)* | WP-03 and later |

Evidence identifiers are re-sorted on load, so a domain object never depends on
database row order.

## 5. Table ownership

| Table | Created by | Owned by |
|---|---|---|
| `source_registry`, `dataset_versions` | WP-02 | WP-05 (source policy), WP-06 (dataset build) |
| `genes`, `gene_aliases`, `drugs`, `drug_aliases` | WP-02 | WP-07 (canonical resolution) |
| `evidence_records` | WP-02 | WP-08 (evidence store) |
| `curated_interpretations`, `interpretation_evidence` | WP-02 | WP-09, WP-10 (curation) |
| `computable_rules`, `rule_evidence` | WP-02 | WP-11 (rule registry) |

## 6. Constraint enforcement matrix

This table is the honest answer to "where is this actually enforced?". A rule is
listed as PostgreSQL-enforced **only** where a real `CHECK`, `UNIQUE`, `NOT
NULL` or `FOREIGN KEY` does the work.

| # | Invariant | Domain | Repository / UoW | PostgreSQL | Future WP |
|---|---|---|---|---|---|
| 1 | Naive datetime is rejected | yes | — | yes (`TIMESTAMPTZ`) | — |
| 2 | Identifier of the wrong entity type is rejected | yes | yes | — (all UUID) | — |
| 3 | Dataset public ID format | yes | — | yes (`ck_dataset_versions_public_id_format`) | — |
| 4 | SHA-256 digest format | yes | — | yes (`ck_*_hash_format`) | — |
| 5 | Lifecycle value is valid | yes (enum) | — | yes (`ck_*_status_enum`) | — |
| 6 | `PUBLISHED` dataset requires approval | yes | — | yes (`ck_dataset_versions_published_requires_approval`) | — |
| 7 | `CURATED` interpretation requires rationale, reviewer, review time | yes | — | yes (`ck_curated_interpretations_curated_requires_review_metadata`) | — |
| 8 | `VALIDATED` rule requires approval metadata | yes | — | yes (`ck_computable_rules_validated_requires_approval`) | — |
| 9 | Rule requires an interpretation | yes | — | yes (`NOT NULL` + FK) | — |
| 10 | **`VALIDATED` rule requires ≥1 evidence row** | yes (in-object) | **yes (UoW commit)** | **no** | WP-11 may add a deferred constraint trigger |
| 11 | **`VALIDATED` rule requires a `CURATED` interpretation** | — | **yes (UoW commit)** | **no** | WP-10/WP-11 |
| 12 | Interpretation requires ≥1 evidence record | yes | — | no | WP-09 |
| 13 | Canonical gene/drug key is unique | — | — | yes (`uq_*`) | — |
| 14 | Alias unique within one entity, ambiguous across entities | — | — | yes (composite PK) | WP-07 resolution queue |
| 15 | Orphan link row is impossible | — | — | yes (FK) | — |
| 16 | Duplicate association is impossible | yes | — | yes (composite PK) | — |
| 17 | `INTERNAL_SYSTEM` source is never release-eligible | yes | — | yes (`ck_source_registry_internal_source_not_release_eligible`) | — |
| 18 | Evidence provenance is unique per dataset build | — | — | yes (`uq_evidence_records_provenance`) | — |
| 19 | Repository accepts only its own domain type | — | **yes (runtime `TypeError`)** | — | — |
| 20 | Assessment requires a release bundle | yes | — | n/a (no table yet) | WP-03 |

**Rows 10 and 11 are the two invariants that are not database-enforced.** They
are cross-row facts that a single-row `CHECK` cannot express, so
`SqlAlchemyUnitOfWork.commit()` validates them and refuses the transaction. A
PostgreSQL deferred constraint trigger is the natural home for them and is left
to WP-11, when the rule registry owns these tables. They must not be reported as
"database enforced" until that trigger exists.

## 7. Transaction policy

- Repositories **stage**; only `SqlAlchemyUnitOfWork` commits or rolls back.
- Leaving the context without an explicit `commit()` rolls back, so a forgotten
  commit cannot leave a half-written aggregate.
- `commit()` flushes, validates rows 10 and 11 above, then commits.
- `expire_on_commit=False`: repositories return plain domain dataclasses, which
  stay readable after the session closes without a lazy refresh.
- Repositories return domain objects only. No ORM instance crosses the boundary,
  so no caller can hold a detached row.

## 8. Test database safety

Integration tests are constrained before a single statement runs:

- they **connect** only through `TEST_DATABASE_URL`; `DATABASE_URL` is read
  once, and only to refuse a target that turns out to be the same database;
- the target database name must **exactly equal** the configured test database
  name — `pgx_test`, or the exact value of `PGX_TEST_DATABASE_NAME`. There is
  no substring rule: a name that merely contains `test` or `ci` is refused,
  because `financial`, `contest`, `latest_production` and
  `production_ci_backup` all qualify under one (section 13.3);
- the two URLs are compared as canonical endpoints — `(driver family, host,
  port, database)` — so different credentials, a different driver spelling, a
  loopback alias or a reordered query string cannot disguise the application
  database as a test one;
- a `sqlite://` URL is rejected by the config validator, and the suite never
  falls back to another engine;
- `assert_engine_targets_test_database()` re-runs the name and collision checks
  from the engine's own URL immediately before **every** destructive helper,
  not only when the engine is built;
- teardown drops only the eleven WP-02 tables plus `alembic_version` — never a
  database, never a schema, never a Docker volume — and uses no `CASCADE`;
- if the database holds a table WP-02 does not own, the suite **fails** rather
  than cleaning up around it;
- no safety message quotes a credential: only host, port and database name;
- when the driver or the URL is missing the suite skips with an explicit
  message stating that the skip is **not** a pass and that the criterion is
  BLOCKED, and pointing at the disposable `postgres-test` service rather than
  the development database.

## 9. Deterministic foundation seed

`pgx.infrastructure.db.cli_seed` (console script `pgx-db-seed`; `scripts/db_seed.py` is a thin wrapper) inserts exactly one technical
bookkeeping row:

| Field | Value |
|---|---|
| `source_key` | `pgx-internal-system` |
| `id` | `4f88dfe7-b85b-5bf0-b387-860bf3fe44fa` (UUID5, fixed) |
| `role` | `INTERNAL_SYSTEM` |
| `release_eligible` | `false` |
| `license_policy`, `citation_policy`, `version_policy` | `NOT_APPLICABLE_INTERNAL` |
| Canonical payload hash | `sha256:e65ca0af82f4979b21bcb6b4056115a7298d85014ceae05910329169f8440c56` |

This row is **not** a scientific source, **not** ClinPGx, **not** release
evidence, and expresses **no** validation or approval. The database itself
refuses to make it release-eligible.

Determinism and idempotency: identity is UUID5 over a fixed key; the payload
carries a fixed epoch instead of wall-clock time, so the hash is stable across
runs and processes; a second run reports `created_count=0`; content that has
drifted is **reported and refused**, never silently overwritten.

Drift comparison covers every seeded field **including `created_at`**
(`SEED_SCHEMA_VERSION = wp02-foundation-seed/2`). An earlier draft omitted the
timestamp, so a row whose `created_at` had been rewritten reported "already
present, no drift" — for a record whose entire purpose is byte-reproducibility.
Both sides are normalised to explicit UTC before comparison, so the same instant
stored in another offset is not reported as drift while a different instant is.

The URL is read from an environment variable, never a command-line argument, and
only its password-redacted form is ever printed. Failure text from the driver —
which quotes the connection string back — is passed through
`config.sanitize_message()` before it reaches stdout, stderr, or an exception.

## 10. Known gaps and blockers

Re-verified on 2026-08-29 during the corrective pass, on **both** machines
available to this session (the local VM and the cloud build container).

| Item | Status | Evidence |
|---|---|---|
| Wheel build / fresh-environment install | **BLOCKED** | No build backend (`hatchling`) and no index, so `pgx-platform` has never been built or installed and the console scripts have never run as installed entry points. Structure is checked offline; the build is not. |
| `uv.lock` | **BLOCKED** | `uv 0.12.3` is installed, but `uv lock` fails: local VM `tunnel error: unsuccessful` on `https://pypi.org/simple/psycopg/`; cloud container `403 Forbidden (no valid authentication credentials)`. Exit code 2, and **no `uv.lock` was written**. A hand-written lock file would be a fabrication, so none exists. |
| `uv sync`, `ruff`, `mypy`, `pytest` | **BLOCKED** | Same cause. `sqlalchemy`, `alembic`, `psycopg`, `pytest`, `ruff` and `mypy` are all absent from both interpreters. |
| Alembic `upgrade` / `downgrade` execution | **BLOCKED** | Alembic cannot be installed. The schema *itself* was exercised on real PostgreSQL 16.13 by rendering the migration to SQL — supplementary evidence only, see the caveat below and `docs/ths6/wp02-foundation-evidence.md`. |
| PostgreSQL integration tests | **BLOCKED** | Written and guarded; they need the psycopg driver. Six tests skip with a message that states the skip is **not** a pass. |
| Compose file validity | **PASS** | `docker compose --env-file .env.example config` and the same command with `--profile test` both exit 0 and resolve to the documented two services. `config` is client-only, so it needs no daemon. |
| Compose container runtime | **BLOCKED** | The daemon socket is unreachable (permission denied on `~/.docker/run/docker.sock` on the macOS host; no `/var/run/docker.sock` in the build container). `docker compose up` fails at the API connection. A successful `config` is not a started container. |
| Deferred constraint trigger for rows 10/11 | Deferred | WP-11 |

> **The AST renderer is not Alembic.** `scripts/render_wp02_schema.py` derives SQL
> from the migration's AST. It proves the *schema* is valid PostgreSQL and that
> its constraints behave as designed. It does **not** prove that Alembic's
> `upgrade()`/`downgrade()` run, that the revision chain resolves, or that
> SQLAlchemy emits the same DDL. Those criteria stay BLOCKED until the real
> toolchain is installable.

## 11. Responsibilities handed to WP-03

- `software_versions`, ruleset version and membership tables;
- `release_bundles` and the `active_release` pointer;
- release activation, rollback, and their audit records;
- allocation of the next `PGX-DATA` / `PGX-RULESET` / `PGX-REL` sequence number
  (WP-02 defines only the value-object format);
- the PostgreSQL implementation of `AssessmentRepository`, which cannot exist
  before a release identity does.

## 12. Corrective pass (2026-08-29)

The first WP-02 delivery was rejected in review. Seven network-independent
defects were fixed; each is now backed by tests that fail if it returns.

### 12.1 Deep immutability — the claim is now literally true

`@dataclass(frozen=True)` stops attribute *rebinding* and nothing else. The
models stored plain `dict` objects, so `record.evidence_metadata["k"] = "v"`
succeeded, and the module-level default `_EMPTY_METADATA = {}` was mutable
shared state that one caller could have poisoned for every instance.

`pgx/domain/immutable.py` now provides:

| Name | Purpose |
|---|---|
| `FrozenMapping` | `Mapping`, never `MutableMapping`: no `__setitem__`, `__delitem__`, `update`, `pop`, `popitem`, `clear` or `setdefault`; `__slots__` and a blocked `__setattr__` so the backing store cannot be swapped |
| `freeze_json(value)` | Recursive: mappings → `FrozenMapping`, sequences → `tuple`, all the way down; copies the caller's object; depth-capped at 64 |
| `thaw_json(value)` | The inverse, used at the ORM/JSONB boundary where psycopg needs real containers; returns a detached copy |
| `EMPTY_MAPPING` | The shared default — immutable, so it cannot be poisoned |
| `freeze_metadata(value, field)` | Field-level entry point used by every model |

Values outside the JSON data model are **rejected at construction**, not
coerced: `NaN`, `±Infinity`, non-string mapping keys, `set`, `bytes`, callables
and arbitrary objects. A rejection names the failing JSON path (`$.a.b[1]`).
Rejection matters beyond tidiness — a value that cannot round-trip through JSON
cannot have a reproducible canonical hash.

Freezing is invisible to identity: `pgx/domain/hashing.py` treats any
`Mapping` (not only `dict`) as an object, so a frozen payload and the plain
dict it came from produce the **same** `sha256:` digest. Key order still does
not matter; array order still does.

The word "immutable" is used in this document only because
`tests/unit/domain/test_immutability.py` proves every required property against
real model instances. The first corrective pass got the *shape* of this right
and the *seal* wrong; section 13.1 records what was still open and how it was
closed.

### 12.2 Operation mode is typed

`Assessment.mode` was `str`, so `mode="PILOT"` — a mode WP-00 disables in P0 —
and `mode="clinical-production"` were both accepted. It is now
`pgx.domain.claims.OperationMode`, validated against the claim boundary:

- `DEMO`, `VALIDATION` — accepted;
- `PILOT` — `ModeNotPermittedError` (a subclass of `DomainInvariantError`),
  because `P0_CLAIM_BOUNDARY` does not enable it;
- any `str`, `None` or `int` — `DomainInvariantError`, because a free string
  cannot be checked against the boundary at all.

The domain does not define a second mode vocabulary; WP-00 remains the owner.

### 12.3 Identifier derivation is restricted

`derive()` was on the `EntityId` base, offering deterministic identity to every
identifier — including scientific records whose identity must be explicitly
minted. It now exists on `SourceRegistryEntryId` alone, where the input is a
stable curated technical key. A test enumerates every `EntityId` subclass and
asserts the set that offers `derive()` is exactly `{SourceRegistryEntryId}`.

### 12.4 Ports carry no untyped holes

`object` in a port signature compiles, reads like a type and enforces nothing.
Every parameter and return annotation in `pgx/domain/ports.py` is now a real
type: `list_for_dataset_version(dataset_version_id: DatasetVersionId)`,
`list_by_status(status: CurationStatus)`, and `__exit__` typed with
`Optional[Type[BaseException]]` / `Optional[TracebackType]`. An AST test fails
the build if `object` reappears anywhere in an annotation.

### 12.5 The package is installable

`README.md` did not exist, so `readme = "README.md"` made the wheel unbuildable;
and `[project.scripts]` pointed at `scripts.db_seed:main`, which is not in the
wheel — `pgx-db-seed` would have raised `ModuleNotFoundError` on any installed
copy. Both entry points now resolve inside the package
(`pgx.infrastructure.db.cli_seed:main`, `...cli_check:main`), the implementations
moved there, and `scripts/db_seed.py` / `scripts/db_check.py` are thin wrappers
holding no seed logic. Tests parse `pyproject.toml`, confirm each target module
exists on disk and each named `main` is actually defined.

### 12.6 Driver policy

A bare `postgresql://` URL lets SQLAlchemy fall back to psycopg2 — not a
dependency of this project, and different around JSONB adaptation. Such a URL is
now normalised to `postgresql+psycopg://` and the normalisation is recorded on
`DatabaseConfig.driver_was_normalized`. Any *explicitly named* other driver
(`+psycopg2`, `+asyncpg`, `+pg8000`, …) is **rejected**, not rewritten: an
explicit choice signals an expectation this project does not meet.

### 12.7 Compose and `.env` agree

`docker-compose.yml` created only `pgx_dev`, while `.env.example` pointed
`TEST_DATABASE_URL` at `pgx_test` on a port nothing published — the documented
test setup could not work. There are now two services: `postgres` (persistent,
5432) and `postgres-test` (profile `test`, host port 55432, `POSTGRES_DB`
defaulting to `pgx_test`, **tmpfs** storage so it never shares the development
volume). No `container_name:`, no global `name:` on the volume, no application
service, and no `command:`/`entrypoint:` — migrations are never a container
start-up side effect. A test parses both files and compares them.

### 12.8 Teardown without `CASCADE`

Integration cleanup used `DROP … CASCADE` and `TRUNCATE … CASCADE`. `CASCADE`
follows dependency edges this suite does not own, so in a shared database it can
remove objects belonging to a later work package. Teardown now runs
`DROP TABLE IF EXISTS "x"` and `DELETE FROM "x"` child-first, and
`assert_disposable_test_schema()` **fails** rather than cleaning up around a
table WP-02 does not own. The checks read the module's AST, so a docstring
explaining why `CASCADE` is forbidden is not mistaken for a `CASCADE` statement.

### 12.9 Controlled WP-01 manifest amendment

The WP-01 test `test_no_wp02_packaging_or_database_artifacts_were_added` asserted
that no packaging or database artifacts existed. WP-02 legitimately created them,
so the assertion had become false-by-design rather than protective. With explicit
human authorisation it was replaced by two tests that keep the protection worth
having:

- `test_wp01_baseline_does_not_absorb_wp02_artifacts` — the WP-01 manifest must
  not own or hash any WP-02 path, and no `pgx/infrastructure/` or `migrations/`
  path may appear in either artifact list;
- `test_wp01_baseline_scope_is_unchanged` — 64 legacy artifacts, 22 evidence
  artifacts.

The manifest was amended by `scripts/amend_legacy_manifest.py`, which re-pins one
evidence hash and appends an audit record. It **refuses** to touch a legacy
artifact, to create an entry, or to run at all if anything other than the amended
file has drifted — and it never re-runs the baseline builder. Details and the
before/after digests are in `docs/ths6/wp02-foundation-evidence.md` section 8.

## 13. Second corrective pass (2026-08-29)

An adversarial review of the first corrective pass found three offline defects
and two misclassified acceptance criteria. All five are addressed here. Nothing
about WP-03 was started, and the WP-01 baseline was not touched — no builder
run, no second manifest amendment, and the regression file is unchanged.

### 13.1 `FrozenMapping` was still mutable

The first pass replaced plain dicts with a `FrozenMapping` that had no
`__setitem__` — and then stored a live `dict` in its `_data` slot. Everything
the class promised was one ordinary attribute access from being false:

```python
f = freeze_json({"outer": {"value": 1}, "items": [1, 2]})
f._data["new"] = "MUTATED"          # succeeded
f["outer"]._data["value"] = 999     # succeeded
f._data.update({...}); f._data.clear()   # succeeded
```

Worse, the cached hash was computed from that mutable dict, so a mutation left
the object claiming a digest that no longer described it.

The public constructor had a second, independent hole. It copied only the top
level, so nested containers stayed shared with the caller:

```python
original = {"items": []}
f = FrozenMapping(original)
original["items"].append("mutation")   # visible inside f
```

Three changes close both:

| Change | Effect |
|---|---|
| `_data` holds a `types.MappingProxyType` | The slot exposes a read-only view. `_data["k"] = v` raises `TypeError`; `update`, `clear`, `pop`, `popitem`, `setdefault` do not exist on it at all. The dict behind the proxy is created inside `_install` and never handed out. |
| The public constructor freezes recursively | `FrozenMapping(mapping)` puts every value through `freeze_json`, so nested dicts become `FrozenMapping` and nested lists become tuples, and the caller's originals are copied. It rejects exactly what `freeze_json` rejects. |
| `FrozenMapping._from_frozen` | The private fast path `freeze_json` uses when it has *already* frozen every value. Without it the two would recurse through each other and freezing would be quadratic; with it, `freeze_json(existing_frozen_mapping)` returns the object unchanged. |

The hash cache is now sound rather than merely lucky: the only reference to the
backing dict lives inside the proxy, so the content it summarises cannot change.
Equality, iteration order, `repr` and hashing are unchanged — a frozen payload
still produces the same `sha256:` digest as the plain dict it came from.

This does not attempt to defend against Python's deliberate low-level escapes
(`object.__setattr__`, `gc.get_referents`); those are not accidents.
`mapping._data[...] = ...` is, and it no longer works.

Separately, `is_frozen_json` returned `True` for `NaN` and `±Infinity` — values
`freeze_json` refuses. The two now agree: non-finite floats are not frozen JSON.

### 13.2 The credential sanitizer covered one shape out of three

It masked the URI userinfo password and nothing else, so a secret in a query
parameter or in a libpq DSN fragment travelled into the log untouched:

```
redact_url(".../db?sslpassword=querysecret")   -> querysecret survived
sanitize_message("... password=secret host=localhost")  -> secret survived
```

`redact_url` now also masks credential-bearing query parameters — matched
case-insensitively against `CREDENTIAL_PARAMETER_NAMES` (`password`, `pass`,
`pwd`, `sslpassword`, `secret`, `token`, `access_token`, `api_key` and others)
— and **drops the fragment entirely**, since nothing in a database URL needs one
and it is a convenient place for a secret to hide. A query that is not
`key=value` shaped carries no key to judge it by, so it is withheld whole rather
than echoed on the assumption that it is harmless.

`sanitize_message` gained the libpq/DSN shape, which is not a URL at all:
`password=x`, `password = x`, `password='x'`, `password="x"`, `sslpassword=x`,
in any case, every occurrence in a message, alongside any number of URLs.
Alternatives are matched longest-first so `sslpassword` is never matched as
`password` with a stray `ssl` left in front of it.

Both functions are fail-safe: input they cannot parse comes back as a
placeholder, never as itself. Failing open would print the secret the function
exists to hide. Neighbouring non-credential fields (`host=`, `dbname=`) and
credential-free messages are left exactly as they were.

### 13.3 The test-database guard accepted real databases

Two independent false positives.

**Substring matching.** The rule accepted any database whose name contained
`test` or `ci`. That is not a narrow class: `financial` contains `ci`,
`contest` and `latest_production` contain `test`, and `production_ci_backup`
contains both. Each would have been cleared for `alembic downgrade base`.

The name must now **equal** the configured test database name — `pgx_test` by
default, or the exact value of `PGX_TEST_DATABASE_NAME`. There is no pattern
and no substring rule left in the module, and a test asserts the old markers
tuple is gone.

**Raw string equality.** The collision check refused `TEST_DATABASE_URL` only
when it was byte-identical to `DATABASE_URL`, so the same database reached
through a different driver spelling or a different login passed:

```
DATABASE_URL      = postgresql://app:one@localhost:5432/pgx_test
TEST_DATABASE_URL = postgresql+psycopg://test:two@localhost:5432/pgx_test
```

Both URLs are now reduced to a canonical endpoint — `(driver family, host,
port, database)` — before comparison. Credentials, driver spelling, query
parameters and their order are discarded, because none of them change which
bytes on which server get dropped. `postgresql` and `postgresql+psycopg`
collapse to one family; `localhost`, `127.0.0.1`, `::1` and an empty host
collapse to one host; an omitted port is 5432.

`assert_engine_targets_test_database()` re-runs both checks from the engine's
own URL immediately before every destructive helper, so a guard that passed at
construction time cannot be the last word. No safety message quotes a
credential — only host, port and database name.

The skip message now points at the disposable service
(`docker compose --profile test up -d postgres-test`) rather than the
development database these tests would destroy.
