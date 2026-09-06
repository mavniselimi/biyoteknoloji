# WP-02 - Foundation Evidence Artifact

| Field | Value |
|---|---|
| Document ID | `DOC-THS6-002` |
| Work package | WP-02 - V2 Repository, Domain Model, and PostgreSQL Foundation |
| Captured (UTC) | 2026-08-29T21:39:58Z |
| Corrective pass re-captured (UTC) | 2026-08-29T22:51Z |
| Second corrective pass (UTC) | 2026-08-29T23:40Z |
| Working machine | Linux aarch64, Python 3.10.12, uv 0.12.3 |
| Verification machine | Linux x86_64 build container, PostgreSQL 16.13 (Ubuntu 16.13-0ubuntu0.24.04.1) |
| Migration revision | `0001_wp02_foundation` (single head) |

> **This is a technical evidence artifact for WP-02 only.** It claims no THS 6
> success, no scientific validation, and no clinical safety. WP-00's human and
> scientific approval is still **BLOCKED**, and WP-01's Git checkpoint is still
> **BLOCKED** with no commit.

---

## 1. Environment constraints that shaped this WP

Package installation is unavailable in both reachable environments:

Re-verified on 2026-08-29 during the corrective pass; nothing had changed.

| Capability | Working machine (repository) | Build container |
|---|---|---|
| PyPI | **unreachable** (`tunnel error: unsuccessful`) | **403 Forbidden** (no valid credentials) |
| Ubuntu apt archive | no privilege | **403 via proxy** |
| uv | 0.12.3 present, **`uv lock` exits 2** | present, **`uv lock` exits 1** |
| Docker CLI | **present** on the macOS host (`/usr/local/bin/docker`); absent from the sandboxed Linux VM | present (29.4.3) with Compose v5.1.3 |
| `docker compose config` | **works** (client-only) | **works**, exit 0 |
| Docker daemon | **not reachable** — `permission denied` on `~/.docker/run/docker.sock` | **not reachable** — no `/var/run/docker.sock` |
| PostgreSQL server | absent (`psql` absent) | **16.13 present and usable** |
| SQLAlchemy / Alembic / psycopg | **absent** | **absent** |
| pytest / ruff / mypy | **absent** | **absent** |

Consequences, stated plainly: `uv.lock` cannot be produced from a genuine
resolution, and Alembic, SQLAlchemy, psycopg, ruff and mypy cannot be executed.
No lock file was fabricated and no result was simulated.

The one capability that *was* available — a real PostgreSQL 16.13 server — was
used, and it earned its keep (section 4).

## 2. Commands actually executed

### 2.1 Tooling

| Command | Exit | Result |
|---|---|---|
| `uv version` | 0 | parsed `pgx-platform 0.2.0.dev0` — `pyproject.toml` is valid |
| `uv tree --offline` | 1 | `alembic was not found in the cache` — resolution genuinely impossible |
| `uv lock` (working machine, corrective pass) | **2** | `Failed to fetch https://pypi.org/simple/psycopg/` → `tunnel error: unsuccessful`. **No `uv.lock` written** — verified absent afterwards. |
| `uv lock` (build container, isolated probe) | **1** | `An index URL (https://pypi.org/simple) could not be queried due to a lack of valid authentication credentials (403 Forbidden)` |
| `pip download sqlalchemy` (build container) | **1** | `Could not find a version that satisfies the requirement sqlalchemy (from versions: none)` |
| `uv sync` | — | **not run**: would fail on the same 403 |
| `uv lock --check` | — | **not run**: there is no lock file, and inventing one is forbidden |
| `uv run ruff check` | — | **BLOCKED**: ruff not installable |
| `uv run mypy` | — | **BLOCKED**: mypy not installable |

> The lock file remains **absent on purpose**. `uv 0.12.3` is installed and the
> command was really attempted; it failed at the network. Writing a `uv.lock` by
> hand would assert a dependency resolution that never happened.

### 2.2 Compilation and domain tests

Counts below are from the corrective pass (2026-08-29), run with
`python3 -W error::ResourceWarning` so an unclosed file handle fails the run.

| Command | Exit | Result |
|---|---|---|
| `python3 -m py_compile` over every new module | 0 | all compile |
| `... -m unittest discover -s tests/unit -p 'test_*.py' -q` | 0 | **470 tests, OK** |
| `... -m unittest discover -s tests/failure -p 'test_*.py' -q` | 0 | **12 tests, OK** |
| `... -m unittest discover -s tests/regression/legacy -p 'test_*.py' -q` | 0 | **151 tests, OK** |
| `... -m unittest discover -s tests/integration -p 'test_*.py' -q` | 0 | **0 run, 6 skipped**, each with an explicit BLOCKED reason |
| `... -m unittest discover -s tests -p 'test_*.py' -t .` | 0 | **633 tests, OK, 6 skipped** |

All runs use `PYTHONDONTWRITEBYTECODE=1` and `-W error::ResourceWarning`, so a
stray `.pyc` cannot mask a stale module and an unclosed file handle fails the
run rather than printing a warning nobody reads.

Suite breakdown:

| Suite | Tests | Introduced |
|---|---|---|
| `tests/unit/test_claims.py` (WP-00, unchanged) | 65 | WP-00 |
| `tests/unit/domain/test_identifiers.py` | 20 | WP-02 |
| `tests/unit/domain/test_models.py` | 43 | WP-02 |
| `tests/unit/domain/test_hashing.py` | 21 | WP-02 |
| `tests/unit/domain/test_ports.py` | 12 | WP-02 |
| `tests/unit/domain/test_dependency_boundaries.py` | 13 | WP-02 |
| `tests/unit/domain/test_immutability.py` | **72** | corrective 1 (46) + 2 (26) |
| `tests/unit/domain/test_typed_boundaries.py` | 23 | corrective 1 |
| `tests/unit/infrastructure/test_configuration_policy.py` | **67** | corrective 1 (27) + 2 (40) |
| `tests/unit/infrastructure/test_packaging_and_environment.py` | 24 | corrective 1 |
| `tests/unit/infrastructure/test_seed_and_cleanup_safety.py` | **67** | corrective 1 (33) + 2 (34) |
| `tests/unit/test_manifest_amendment.py` | 27 | corrective 1 |
| `tests/unit/test_schema_rendering.py` | 16 | WP-02 |
| `tests/failure/test_domain_layer_violations.py` | 12 | WP-02 |
| `tests/regression/**` (WP-01) | 151 | WP-01 + 1 authorised amendment |

The second corrective pass added **100** tests. None of them is a skip.

> **On structural tests.** Several of these read code rather than run it (AST
> parsing of `ports.py`, `_support.py`, the CLI wrappers). They are written to
> read *code*, never prose: docstrings are excluded from the AST scan and
> comments never reach it, so a docstring explaining why `CASCADE` is forbidden
> cannot be mistaken for a `CASCADE` statement. An earlier draft of these tests
> had exactly that flaw and passed for the wrong reason.

### 2.3 WP-00 and WP-01 regression

| Command | Exit | Result |
|---|---|---|
| `python3 -m unittest tests.unit.test_claims` | 0 | **65 tests, OK** |
| `python3 -m unittest discover -s tests/regression -p 'test_*.py' -t .` | 0 | **151 tests, OK** (was 150 with 1 failure; see section 8) |
| `compare_legacy_v2.py verify-manifest` | 0 | **MATCH: 64/64 legacy artifacts, 22/22 evidence artifacts, 0 problems** |

### 2.4 Docker Compose

> **Correction.** The previous revision of this document said `docker: command
> not found`. That was observed in the sandboxed Linux VM this session's shell
> runs in, and reported as if it described the developer machine. It does not:
> on the macOS host the client is installed at `/usr/local/bin/docker` and runs.
> Generalising from one shell to the whole environment was the error, and the
> table above now separates the two.

Compose splits cleanly into two capabilities, and only one of them is blocked.

| Command | Exit | Result |
|---|---|---|
| `docker compose --env-file .env.example config` | **0** | resolved config printed |
| `docker compose --env-file .env.example --profile test config` | **0** | resolved config printed, including `postgres-test` |
| `docker compose --profile test up -d postgres-test` | **1** | `failed to connect to the docker API at unix:///var/run/docker.sock` |
| `docker info` (server section) | — | same connection failure |

`config` is a **client-only** operation: it parses the file, interpolates the
env file and resolves profiles without contacting a daemon. It therefore runs
here, and its output is real evidence about the compose file. Starting a
container is not: the daemon socket is unreachable (permission denied on the
macOS host, absent in the build container).

What the resolved `--profile test` config confirms — read off the command's own
output, not off the source file:

| Property | Resolved value |
|---|---|
| `postgres` database / published port | `pgx_dev` / `55433` (moved from `5432` in Wave 4B: PostgreSQL's default port is the one a developer machine most often already has, and a shadowed publish presents as `role "pgx_dev" does not exist`) |
| `postgres-test` database / published port | `pgx_test` / `55432` |
| `postgres-test` storage | `tmpfs: [/var/lib/postgresql/data]`, **no volume entry** |
| `container_name` occurrences | **0** |
| Volume name | `<project>_pgx_postgres_data` — project-prefixed, so no global explicit name |
| Services defined | exactly two; **no application service** |
| `command:` / `entrypoint:` | none — migrations and the seed cannot be a start-up side effect |
| Image | `postgres:16.13-bookworm` on both services |

Both `config` runs were executed in the build container against the repository's
own `docker-compose.yml` and `.env.example`. The compose *file* is therefore
verified; container *runtime* is not, and `docker compose config` succeeding is
**not** presented as a container having started.

`tests/unit/infrastructure/test_packaging_and_environment.py` (24 tests) checks
the same properties offline, so the guarantee survives on a machine with no
Docker at all.

## 3. Migration and schema

| Item | Value |
|---|---|
| Revision | `0001_wp02_foundation` |
| `down_revision` | `None` (single head) |
| Tables created | 11 |
| Tables dropped by `downgrade()` | 11, in exact reverse order (verified by test) |
| Indexes created / dropped | 7 / 7 |

Tables: `source_registry`, `dataset_versions`, `genes`, `gene_aliases`, `drugs`,
`drug_aliases`, `evidence_records`, `curated_interpretations`,
`interpretation_evidence`, `computable_rules`, `rule_evidence`.

No table belonging to WP-03 or later was created; a test asserts this.

## 4. Real PostgreSQL 16.13 verification

Alembic could not be executed, so the schema was verified a different way. The
migration's `upgrade()` was rendered to SQL by `scripts/render_wp02_schema.py`,
which parses the migration's AST — the SQL is **generated from the migration**,
not hand-maintained, so the two cannot drift. That SQL was executed against a
real PostgreSQL 16.13 cluster.

**What this proves:** the DDL, constraints, types and drop order are correct on
real PostgreSQL. **What it does not prove:** that the Alembic runner itself
works — `alembic_version` stamping and revision resolution were not exercised.
A6 and A7 therefore remain **BLOCKED**, and this section is supplementary
evidence, not a substitute.

### 4.1 Schema applied

```
11 tables, 22 CHECK constraints, 11 foreign keys, 6 unique constraints, 24 indexes
constraints at exactly 63 characters (possible truncation): 0
```

### 4.2 Defect found and fixed by this run

The first attempt produced:

```
NOTICE: identifier "fk_interpretation_evidence_interpretation_id_curated_interpretations"
        will be truncated to "fk_interpretation_evidence_interpretation_id_curated_interpreta"
```

PostgreSQL truncates identifiers at 63 bytes. The name was 68. A silently
truncated constraint name is a real defect: `downgrade()` and any later
migration would reference a name the database does not have. The constraint was
renamed to `fk_interpretation_evidence_interpretation_id` (43 bytes), and
`tests/unit/test_schema_rendering.py` now fails the build if any identifier
exceeds the limit.

### 4.3 Constraint behaviour — 29 cases, 29 as designed

| Case | Expected | Enforcing constraint |
|---|---|---|
| duplicate `source_key` | rejected | `uq_source_registry_source_key` |
| invalid `role` | rejected | `ck_source_registry_role_enum` |
| `INTERNAL_SYSTEM` marked release-eligible | rejected | `ck_source_registry_internal_source_not_release_eligible` |
| `INTERNAL_SYSTEM` not release-eligible | accepted | — |
| malformed dataset public ID | rejected | `ck_dataset_versions_public_id_format` |
| malformed SHA-256 | rejected | `ck_dataset_versions_manifest_hash_format` |
| `PUBLISHED` without approval | rejected | `ck_dataset_versions_published_requires_approval` |
| `PUBLISHED` with approval | accepted | — |
| lower-case gene symbol | rejected | `ck_genes_symbol_normalized` |
| duplicate gene symbol | rejected | `uq_genes_normalized_symbol` |
| upper-case drug name | rejected | `ck_drugs_name_normalized` |
| `CURATED` without reviewer | rejected | `ck_curated_interpretations_curated_requires_review_metadata` |
| `CURATED` with full metadata | accepted | — |
| invalid phenotype | rejected | `ck_curated_interpretations_phenotype_enum` |
| `RAPID` accepted, `ULTRARAPID` accepted | both accepted, distinct | — |
| rule with NULL interpretation | rejected | `NOT NULL` |
| `VALIDATED` without approval | rejected | `ck_computable_rules_validated_requires_approval` |
| `VALIDATED` with approval | accepted | — |
| duplicate rule version | rejected | `uq_computable_rules_interpretation_version` |
| `rule_version = 0` | rejected | `ck_computable_rules_rule_version_positive` |
| orphan `rule_evidence` link | rejected | `fk_rule_evidence_rule_id_computable_rules` |
| same alias on two different genes | accepted (ambiguity preserved) | — |
| duplicate alias within one gene | rejected | `pk_gene_aliases` |
| `TIMESTAMPTZ` retains an offset | accepted | — |
| `JSONB` is queryable | accepted | — |

**Result: 29 passed, 0 failed.**

### 4.4 upgrade → downgrade → upgrade

| Step | Result |
|---|---|
| apply generated DDL | 11 tables |
| run `downgrade()` order (18 statements) | exit 0, **0 tables remaining** |
| re-apply | **11 tables** |

No PostgreSQL function or trigger is created, so none needed dropping. The
temporary cluster was created by this session and removed afterwards; no
pre-existing database, container, or volume was touched.

## 5. Deterministic seed

| Field | Value |
|---|---|
| `seed_schema_version` | `wp02-foundation-seed/2` (v1 omitted `created_at` from drift comparison) |
| Row | `pgx-internal-system`, role `INTERNAL_SYSTEM`, `release_eligible=false` |
| Fixed identity (UUID5) | `4f88dfe7-b85b-5bf0-b387-860bf3fe44fa` |
| Canonical payload hash (v2) | `sha256:0a291ceb9a5f0f070c4f1ecbe0f633325dae6babeb0b1f9518e4136c19a2289a` |
| Hash under `PYTHONHASHSEED` 1, 2, 3 | **identical** |
| Compared fields | `source_key`, `display_name`, `role`, `version_policy`, `license_policy`, `citation_policy`, `release_eligible`, `active`, **`created_at`** |

The hash changed from the first WP-02 draft because the schema version is part
of the canonical payload and it moved from `/1` to `/2`. The seeded *row* is
unchanged: same key, same UUID5 identity, same fixed epoch.

Drift detection is exercised without a database by
`tests/unit/infrastructure/test_seed_and_cleanup_safety.py` (33 tests), which
drives `detect_drift()` with mutated rows:

| Mutation | Detected |
|---|---|
| `created_at` + 1 second | **yes** (the v1 gap) |
| `created_at` moved a year | **yes** |
| same instant expressed in UTC+03:00 | **no** — correctly, it is the same instant |
| `display_name` changed | **yes**, reporting both expected and stored values |
| `active` flipped | **yes** |
| two fields at once | **both** reported |
| `release_eligible` set true | *unreachable* — the domain refuses to construct the row at all (`INTERNAL_SYSTEM` can never be release-eligible), a stronger guarantee than drift detection |

A further test asserts that the compared-field set equals the seeded payload's
fields, so adding a seed field without adding it to the drift check fails.

Row-count idempotency (`created_count=0` on the second run) against a real
database remains covered only by `tests/integration/db/test_seed.py`, which is
**BLOCKED** on the driver.

## 6. Corrective pass — what was rejected and what changed

The first WP-02 delivery was **rejected**. Seven network-independent defects
were named; all seven are fixed, each behind tests that fail if it returns.

| # | Defect | Fix | Proof |
|---|---|---|---|
| 1 | `dict(value)` is not immutability; `_EMPTY_METADATA = {}` was mutable shared state | `pgx/domain/immutable.py`: `FrozenMapping`, recursive `freeze_json`/`thaw_json`, immutable `EMPTY_MAPPING` | `test_immutability.py` — 46 tests |
| 2 | `Assessment.mode` was `str`, accepting `"PILOT"` and arbitrary text | typed as WP-00 `OperationMode`, checked against `P0_CLAIM_BOUNDARY` | `test_typed_boundaries.py` |
| 3 | `derive()` on the `EntityId` base offered derivation to every identifier | moved to `SourceRegistryEntryId` only | `test_typed_boundaries.py` |
| 4 | `object` annotations in ports enforced nothing | real types everywhere, incl. `__exit__` | AST test over `ports.py` |
| 5 | `README.md` missing; console scripts pointed at unpackaged `scripts.*` | README written; implementations moved to `pgx.infrastructure.db.cli_seed` / `cli_check`; `scripts/*.py` reduced to wrappers | `test_packaging_and_environment.py` |
| 6 | Seed drift ignored `created_at`; errors could echo a password | `created_at` compared; `sanitize_message()` on every failure path | `test_seed_and_cleanup_safety.py`, `test_configuration_policy.py` |
| 7 | Compose created only `pgx_dev` while `.env` targeted `pgx_test`; teardown used `CASCADE` | `postgres-test` service on port 55432 with tmpfs; teardown drops/deletes child-first without `CASCADE` | `test_packaging_and_environment.py`, `test_seed_and_cleanup_safety.py` |

Two supporting changes came out of the same pass:

- **Driver policy.** A bare `postgresql://` URL could resolve to psycopg2, which
  this project does not ship. It is now normalised to `postgresql+psycopg://`
  and the normalisation is recorded; an explicitly named other driver is
  rejected rather than silently rewritten.
- **Canonical hashing.** `hashing.py` now treats any `Mapping` as an object, so
  a frozen payload hashes identically to the plain dict it came from — verified
  by asserting equal digests for both forms.

### 6.1 Two mistakes made during this pass, and their corrections

Recorded because a corrective pass that hides its own errors is not evidence.

1. **Scope creep into a frozen file.** Adding a helper back into
   `tests/regression/legacy/_support.py` would have widened the authorised
   amendment beyond the one file. It was reverted, and `_support.py` is again
   byte-identical to its manifest entry (`ec071378ee117f67…`). Only
   `test_legacy_reproduction.py` differs.
2. **Structural tests that read prose.** The first drafts of the compose and
   `CASCADE` checks matched raw file text, so a comment saying "no
   `container_name:`" and a docstring explaining why `CASCADE` is forbidden both
   registered as violations — and, worse, the same flaw would have let a real
   violation hide inside a string. They were rewritten to parse the AST and
   strip YAML comments, so they assert on code only.

## 7. WP-01 obsolete test — authorised amendment

`test_no_wp02_packaging_or_database_artifacts_were_added` was written during
WP-01, when WP-02 had not started, and asserted that `pyproject.toml`,
`alembic.ini` and `migrations/` must **not** exist. WP-02 was required to create
exactly those files, so the assertion became false-by-design rather than
protective.

With explicit human authorisation it was replaced by two tests that keep the
protection that was actually worth having:

| Test | Asserts |
|---|---|
| `test_wp01_baseline_does_not_absorb_wp02_artifacts` | the WP-01 manifest neither hashes nor owns any WP-02 path, and no `pgx/infrastructure/` or `migrations/` path appears in either artifact list |
| `test_wp01_baseline_scope_is_unchanged` | 64 legacy artifacts, 22 evidence artifacts |

Neither test expects WP-02 files to be absent from disk — only that the WP-01
baseline does not claim them.

## 8. Controlled manifest amendment

The amended test file is itself a WP-01 evidence artifact, so its pinned hash
had to change. This was done as a **controlled amendment**, not a re-collection.

| Field | Value |
|---|---|
| Path | `tests/regression/legacy/test_legacy_reproduction.py` |
| Old SHA-256 | `474e1793360182295ce2f671209e93da795229fd5cdfaf8063fe615297220681` (17,810 bytes) |
| New SHA-256 | `e38fb05b6d2a005d1796f63b64bd13a5055749630c7feda256d248d02dc8a2be` (19,921 bytes) |
| Amended (UTC) | 2026-08-29 |
| Note | `WP-02 phase transition; legacy artifacts unchanged` |
| `rebuild_performed` | `false` |
| Legacy artifacts verified unchanged | **64 / 64** |
| Evidence artifacts | **22**, count unchanged |
| Tool | `scripts/amend_legacy_manifest.py` |

The record is stored in `manifest["amendments"]`, alongside the reason text.
`build_legacy_baseline.py` was **not** run: a full re-collection would silently
re-bless anything else that had drifted.

`scripts/amend_legacy_manifest.py` refuses to proceed if any of the following
holds — each refusal is exercised by a test:

- the target is one of the 64 legacy/WP-00 artifacts;
- the target is not already an evidence entry (it never creates entries);
- any legacy artifact hash no longer matches disk;
- any evidence artifact *other than* the target has drifted;
- the artifact counts are not 64 and 22;
- the file already matches the manifest.

Default behaviour is a dry run; `--apply` writes. Verification after the
amendment:

```
verify-manifest: MATCH (64 legacy artifacts declared / 64 verified;
                        22 evidence artifacts declared / 22 verified; 0 problem(s))
```

Regression suite: **151 tests, OK** (was 150 with 1 failure).

## 9. Preservation

| Scope | Files | Result |
|---|---|---|
| Seven legacy Python modules | 7 | **unchanged** |
| `architecture.md` | 1 | **unchanged** |
| WP-00 documents, code, tests | 8 | **unchanged** |
| Legacy seed, backups, raw outputs, reports, candidate seeds | 48 | **unchanged** |
| **Total protected** | **64** | **0 differences** |

| Governance state | Value |
|---|---|
| `CLAIM_BOUNDARY_STATUS` | `DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW` (unchanged) |
| `P0_CLAIM_BOUNDARY.is_approved` | `False` (unchanged) |
| WP-01 Git checkpoint | **BLOCKED**, no commit on branch `main` |
| Legacy rule rows imported | **0** — the 3,084 legacy rows were not touched |
| Network calls made | **0** — no ClinPGx, no Gemini, no LLM |
| WP-00 files changed by the corrective pass | **0** — `claims.py`, `test_claims.py` and both WP-00 documents are byte-identical |
| WP-01 files changed by the corrective pass | **1** — `tests/regression/legacy/test_legacy_reproduction.py`, under explicit authorisation |
| WP-03 work started | **none** — no release bundle, ruleset version, activation, API, UI, LLM, VCF or EHR code exists |

Confirmed after the corrective pass by re-running `verify-manifest`: all 64
legacy and WP-00 artifacts still hash to their recorded digests, and the only
evidence artifact whose digest moved is the one file the amendment covers.

## 10. Second corrective pass — adversarial probes

An adversarial review of the first corrective pass found three offline defects.
Each was reproduced first, fixed second, and re-probed third. The probe output
below is verbatim.

### 10.1 `FrozenMapping` mutability

**Before** — every guarantee the class advertised was one attribute access away
from being false:

```
A. f._data['new']='MUTATED'          -> SUCCEEDED  *** LEAK ***
B. f['outer']._data['value']=999     -> SUCCEEDED  *** LEAK ***
C. f._data.update()/pop()            -> SUCCEEDED  *** LEAK ***
D. constructor aliasing              -> SUCCEEDED  *** LEAK ***  | g['items'] = ['mutation']
E. constructor nested type           -> list (mutable)
F. hash after _data mutation         -> cached -1576536357797754615
                                        vs recomputed 2759061546627316759  *** STALE ***
G. is_frozen_json(NaN)               -> True   (must be False)
H. is_frozen_json(+Inf)              -> True   (must be False)
I. is_frozen_json(-Inf)              -> True   (must be False)
```

**After**:

```
f._data['new'] = 'MUTATED'        -> blocked: TypeError:
                                     'mappingproxy' object does not support item assignment
f['outer']._data['value'] = 999   -> blocked: TypeError:
                                     'mappingproxy' object does not support item assignment
del f._data['outer']              -> blocked: TypeError:
                                     'mappingproxy' object does not support item deletion
f._data.update({'u': 1})          -> blocked: AttributeError
f._data.clear()                   -> blocked: AttributeError
f._data.pop('outer')              -> blocked: AttributeError
f._data = {}                      -> blocked: DomainInvariantError
f._hash = 0                       -> blocked: DomainInvariantError
del f._data                       -> blocked: DomainInvariantError
f['new'] = 1                      -> blocked: DomainInvariantError
constructor aliasing              -> isolated              (g['items'] = ())
constructor nested types          -> tuple / FrozenMapping
is_frozen_json(constructed)       -> True
storage type                      -> mappingproxy
hash stable & correct             -> True
is_frozen_json non-finite         -> NaN=False +Inf=False -Inf=False
freeze idempotent                 -> True
repr                              -> FrozenMapping({'a': 1})
```

Covered by 26 new tests in `tests/unit/domain/test_immutability.py`
(72 total), including all eight the review required.

### 10.2 Credential leakage

**Before** — the userinfo password was masked and nothing else was:

```
redact_url  query sslpassword  *** LEAKS ['secret', 'querysecret'] ***
    -> postgresql+psycopg://user:***@host/db?sslpassword=querysecret
redact_url  fragment           *** LEAKS ['fragsecret'] ***
sanitize    libpq password=    *** LEAKS ['secret'] ***
    -> connection failed: password=secret host=localhost dbname=pgx_test
sanitize    spaced password =  *** LEAKS ['spacedsecret'] ***
sanitize    quoted single      *** LEAKS ['quotedsecret'] ***
sanitize    quoted double      *** LEAKS ['dqsecret'] ***
sanitize    sslpassword=       *** LEAKS ['sslsecret'] ***
sanitize    api_key in url     *** LEAKS ['apisecret'] ***
sanitize    two dsn secrets    *** LEAKS ['one', 'two'] ***
```

**After** — every case clean:

```
redact_url  query sslpassword  -> postgresql+psycopg://user:***@host/db?sslpassword=***
redact_url  UPPERCASE key      -> postgresql+psycopg://u:***@h/db?SSLPassword=***
redact_url  fragment           -> postgresql+psycopg://u:***@h/db
redact_url  percent-encoded    -> postgresql+psycopg://u:***@h/db
redact_url  opaque query       -> postgresql+psycopg://u:***@h/db?***
sanitize    libpq password=    -> connection failed: password=*** host=localhost dbname=pgx_test
sanitize    spaced password =  -> DSN: password = *** host=localhost
sanitize    quoted single      -> DSN: password=*** host=localhost
sanitize    quoted double      -> DSN: password=*** host=localhost
sanitize    sslpassword=       -> libpq: sslpassword=*** sslmode=require
sanitize    PASSWORD= upper    -> libpq: PASSWORD=***
sanitize    api_key in url     -> GET https://api.example.com/v1?api_key=*** failed
sanitize    two dsn secrets    -> a password=*** and b sslpassword=***
sanitize    url + dsn together -> postgresql+psycopg://u:***@h/db failed; password=***
sanitize    two urls           -> postgresql://a:***@h/db and postgresql://b:***@h/db
sanitize    url ending a sentence -> could not reach postgresql://u:***@h/db.

innocent message untouched: 'relation "genes" does not exist'
malformed input:            '<invalid-url>'  (never the input echoed back)
```

Both CLIs are driven into failure with an exception that quotes the URL *and* a
DSN password, and their combined stdout+stderr is asserted clean — the sanitizer
is only worth anything on the path the user actually sees. 40 new tests in
`tests/unit/infrastructure/test_configuration_policy.py` (67 total).

### 10.3 Test-database guard

**Before** — substring matching and raw string equality:

```
db 'pgx_test'                     ACCEPTED
db 'financial'                    ACCEPTED  *** WRONG ***
db 'production_ci_backup'         ACCEPTED  *** WRONG ***
db 'contest'                      ACCEPTED  *** WRONG ***
db 'latest_production'            ACCEPTED  *** WRONG ***
same db, different driver         ACCEPTED  *** WRONG ***
same db, different credentials    ACCEPTED  *** WRONG ***
same db, localhost vs 127.0.0.1   ACCEPTED  *** WRONG ***
```

**After** — exact name plus canonical endpoint comparison:

```
1. exact 'pgx_test'                   ACCEPTED  ok
2. configured exact CI name           ACCEPTED  ok
3. 'financial'                        rejected  ok
4. 'production_ci_backup'             rejected  ok
5. 'contest'                          rejected  ok
   'latest_production'                rejected  ok
   'clinical'                         rejected  ok
   'pgx_testing' (near miss)          rejected  ok
   'test' alone                       rejected  ok
6. same db, different driver          rejected  ok
7. same db, different credentials     rejected  ok
8. localhost vs 127.0.0.1             rejected  ok
   localhost vs ::1                   rejected  ok
   query order differs                rejected  ok
   default port vs explicit 5432      rejected  ok
9. genuinely different database       ACCEPTED  ok
   different host, same db name       ACCEPTED  ok
   different port, same db name       ACCEPTED  ok
   no database in url                 rejected  ok
10. error text carries credential?    no
    collision error carries credential? no
```

Endpoint equivalence, shown directly:

```
canonical_endpoint("postgresql://app:one@localhost:5432/pgx_test")
  == canonical_endpoint("postgresql+psycopg://test:two@127.0.0.1:5432/pgx_test")
  -> ('postgresql', 'localhost', 5432, 'pgx_test') == same -> True
```

34 new tests in `tests/unit/infrastructure/test_seed_and_cleanup_safety.py`
(67 total), including all ten the review required. Two further tests assert the
guard runs **before** any `execute()` inside each destructive helper, and that
the old `_TEST_DATABASE_MARKERS` substring rule is gone from the source.

## 11. Corrections to earlier claims in this document

Recorded rather than quietly edited, because a document that revises itself
silently is not evidence.

| Earlier claim | Correction |
|---|---|
| "`docker: command not found`" | Observed in the sandboxed Linux VM this session's shell runs in, then reported as if it described the developer machine. The Docker **client is installed** on the macOS host at `/usr/local/bin/docker`, and `docker compose config` runs. Only the **daemon** is unreachable. Section 2.4 now separates client from daemon. |
| "Compose is BLOCKED" | Too coarse. Compose *file validation* is **PASS** — both `config` commands exit 0. Compose *container runtime* is **BLOCKED**. A successful `config` is not a started container, and is not presented as one. |
| A1 "installable package — PASS" | Wrong classification. The static structure is verified, but no wheel was ever built, no fresh environment installed, and no installed console entry point executed. A1 is **BLOCKED**; see the acceptance table. |
| A3 "immutability — PASS" | Premature. The `_data` backdoor above meant the property did not hold. PASS is claimed only now, behind section 10.1. |
| A12 "no credential leakage — PASS" | Premature. Query-string and DSN secrets leaked. PASS is claimed only now, behind section 10.2. |
| A14 "test DB safety — PASS" | Premature. The guard accepted `financial` and `production_ci_backup`. PASS is claimed only now, behind section 10.3. |
