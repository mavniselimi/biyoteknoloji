# WP-03 - Release Registry Evidence Artifact

| Field | Value |
|---|---|
| Document ID | `DOC-THS6-003` |
| Work package | WP-03 - Version Registry, Release Bundle, and Rollback |
| Captured (UTC) | 2026-08-30 |
| Working machine | Linux aarch64, Python 3.10.12, uv 0.12.3 |
| Verification machine | Linux x86_64 build container, PostgreSQL 16.13 |
| Migration revision | `0002_wp03_release_registry` (parent `0001_wp02_foundation`) |

> **This is a technical evidence artifact for WP-03 only.** It claims no THS 6
> success, no scientific validation, and no clinical safety. WP-00's human and
> scientific approval is still **BLOCKED**, WP-01's Git checkpoint is still
> **BLOCKED**, and WP-02's toolchain criteria are still **BLOCKED**. WP-03
> resolves none of them and does not present any of them as resolved.

---

## 1. Four kinds of evidence, kept apart

The single most important thing in this document is that these are not mixed.

| Kind | What it can prove | What it cannot |
|---|---|---|
| **A. Offline service evidence** | The fourteen compatibility rules, activation sequencing, the idempotent no-op, the rollback contract, the audit shape, manifest determinism | Anything about transactions, locking, or the database |
| **B. Structural evidence** | That the migration, ports, CLI and repositories have the shape they claim - checked by parsing their AST | That any of it runs |
| **C. Real PostgreSQL evidence (rendered SQL)** | The schema is valid PostgreSQL; the CHECK, UNIQUE and FK constraints reject what they should; the append-only trigger works; `SELECT ... FOR UPDATE` blocks a second transaction | That **Alembic** runs, or that the SQLAlchemy repositories work |
| **D. BLOCKED** | Nothing | Alembic upgrade/downgrade, the psycopg driver, the repository/service integration tests |

Kind C runs the SQL **rendered from the migration**, not Alembic. That
distinction is load-bearing and is repeated wherever it applies.

## 2. Environment

Unchanged from WP-02, re-checked once and not revisited:

| Capability | Working machine | Build container |
|---|---|---|
| PyPI | unreachable (tunnel error) | 403 Forbidden |
| `uv lock` | exit 2, no lock written | exit 1 |
| SQLAlchemy / Alembic / psycopg | **absent** | **absent** |
| PostgreSQL server | absent | **16.13 present and usable** |
| Docker client / `compose config` | present / works | present / works |
| Docker daemon | unreachable | unreachable |

No `uv.lock` was fabricated. No result was simulated.

## 3. Test results

All runs use `PYTHONDONTWRITEBYTECODE=1` and `-W error::ResourceWarning`.

| Command | Exit | Result |
|---|---|---|
| `... discover -s tests/unit -p 'test_*.py' -q` | 0 | **652 tests, OK** |
| `... discover -s tests/failure -p 'test_*.py' -q` | 0 | **15 tests, OK** |
| `... discover -s tests/regression/legacy -p 'test_*.py' -q` | 0 | **151 tests, OK** |
| `... discover -s tests/integration -p 'test_*.py' -q` | 0 | **0 run, 10 skipped**, each with an explicit BLOCKED reason |
| `... discover -s tests -p 'test_*.py' -t .` | 0 | **818 tests, OK, 10 skipped** |

WP-03 added **179** tests, none of them a skip:

| Suite | Tests | Kind |
|---|---|---|
| `tests/unit/application/test_release_service.py` | 46 | A |
| `tests/unit/application/test_rollback.py` | 29 | A |
| `tests/unit/application/test_release_manifest.py` | 33 | A |
| `tests/unit/application/test_legacy_baseline.py` | 25 | A |
| `tests/unit/application/test_release_cli.py` | 22 | A + B |
| `tests/unit/application/test_release_boundaries.py` | 24 | B |
| `tests/integration/db/test_release_registry.py` | 0 run, **skipped** | D |

The 10 integration skips carry this reason:

```
PostgreSQL integration tests require sqlalchemy, alembic, psycopg, which are
not installed in this environment. ... This skip is NOT a pass: the WP-02
acceptance report records the PostgreSQL criteria as BLOCKED.
```

## 4. Release manifest

`schemas/release-manifest.schema.json` is committed. A valid example, five
invalid ones and a recorded digest live in `tests/fixtures/release-manifests/`.

Example (`valid.json`, identities from the fixture scenario):

```json
{
  "schema_version": "pgx-release-manifest/1",
  "release":  {"public_id": "PGX-REL-20260829-001"},
  "software": {
    "id": "...", "version": "0.3.0.dev0", "source_commit": "0123456789abcdef",
    "source_tree_hash": "sha256:...", "manifest_hash": "sha256:..."
  },
  "dataset":  {"id": "...", "public_id": "PGX-DATA-20260829-001",
               "status": "PUBLISHED", "manifest_hash": "sha256:..."},
  "ruleset":  {"id": "...", "public_id": "PGX-RULESET-20260829-001",
               "status": "FROZEN", "manifest_hash": "sha256:...",
               "member_count": 1, "rule_ids": ["..."]}
}
```

Recorded digest of that fixture:

```
sha256:bd25d0e2b8d17cf44e9f4593d74fa051771fb230569b93801c0c8b8981798488
```

`test_the_valid_fixture_matches_its_recorded_digest` recomputes it from the file
on every run, so the fixture and its digest cannot drift apart.

Invalid fixtures, one per failure family: `invalid-schema-version.json`,
`invalid-missing-section.json`, `invalid-bad-digest.json`,
`invalid-member-count-mismatch.json`, `invalid-unknown-key.json`.

Determinism is asserted directly: the same records produce the same payload and
the same digest; key insertion order does not change the digest; a different
membership does; and an AST test fails the build if the manifest module ever
reads the clock.

## 5. Offline activation and rollback drill (kind A)

`python3 scripts/release_drill.py`, exit 0. Transcript, lightly trimmed:

```
1. Initial state          active=none generation=0
2. Validate               compatible: True   problems: none
3. Activate               changed=True generation=1  first -> ACTIVE
4. Re-activate the same   changed=False generation=1  audit events: 1   (no-op)
5. Activate the second    changed=True generation=2
                          first -> ROLLED_BACK   second -> ACTIVE
6. Incompatible release   refused: SOFTWARE_VERSION_NOT_REGISTERED
                          generation 2 -> 2, audit events 2 -> 2 (unchanged)
7. Roll back to the first changed=True generation=3
                          first -> ACTIVE   second -> ROLLED_BACK
8. Rollback to a release
   that never ran         refused: "has never been activated"
9. Immutable artifacts    both manifest hashes unchanged
                          ruleset membership: 1 rule, unchanged
                          dataset status: PUBLISHED
10. Legacy baseline       created=True  PGX-REL-20260829-999  status=RETIRED
                          ruleset members=0
                          activation refused: RELEASE_RETIRED,
                          DATASET_NOT_PUBLISHED, RULESET_NOT_FROZEN,
                          RULESET_MEMBERSHIP_EMPTY
11. Audit trail           4 events, oldest first:
                          RELEASE_ACTIVATED    previous=None new=first
                          RELEASE_ACTIVATED    previous=first new=second
                          RELEASE_ROLLED_BACK  previous=second new=first
                          LEGACY_BASELINE_REGISTERED  previous=None new=None
12. Final state           active=PGX-REL-20260829-001 generation=3
```

Note step 7: the generation goes **up**, to 3. A rollback is a new event in
history, not an erasure of an old one.

Note step 6: the generation and the audit count are printed before and after the
rejection, because "changed nothing" is the claim being made.

> **The drill runs against an in-memory unit of work.** It proves the rules and
> the sequencing. It proves nothing about transactions, isolation or row
> locking, and the script prints that disclaimer in its own header.

## 6. Real PostgreSQL 16.13 evidence (kind C)

Alembic cannot be installed here, so the migration's `upgrade()` was rendered to
SQL by `scripts/render_wp03_schema.py`, which parses the migration's AST - the
SQL is *generated from the migration*, so the two cannot drift - and executed on
a real PostgreSQL 16.13 cluster on top of the WP-02 schema.

The renderer output is byte-identical on both machines:

```
sha256:16c034060207f7a44e1e34cfb87723427d9afce899c76446fc4d5a218a3f8a07
```

### 6.1 Schema applied

```
0001 applied -> 11 tables
0002 applied -> 17 tables
singleton row: singleton_id=1  release_id=NULL  generation=0
               updated_by=system:migration/0002_wp03_release_registry
identifiers at or over PostgreSQL's 63-byte limit: 0
WP-03 tables 6 | foreign keys 19 | check constraints 43 | triggers 1 | functions 1
```

### 6.2 Constraint behaviour

| Probe | Result |
|---|---|
| second pointer row (`singleton_id = 2`) | rejected - `ck_active_release_singleton` |
| `generation = -1` | rejected - `ck_active_release_generation_not_negative` |
| `generation = 1` with `release_id` NULL | rejected - `ck_active_release_moved_pointer_names_a_release` |
| `DRAFT` release given `activated_by` | rejected - `ck_release_bundles_activation_metadata_matches_status` |
| `status = 'ACTIVE'` with no activation metadata | rejected - same constraint |
| valid activation of the row | accepted |
| pointer moved with a generation bump | accepted, generation 0 -> 1 |
| deleting a release the pointer names | rejected - `fk_active_release_release_id_release_bundles` |
| deleting a ruleset a release pins | rejected - `fk_release_bundles_ruleset_version_id_ruleset_versions` |
| unknown audit action | rejected - `ck_audit_events_action_enum` |
| `RELEASE_ACTIVATED` with no `new_release_id` | rejected - `ck_audit_events_pointer_event_names_new_release` |

### 6.3 Append-only audit trail

```
INSERT                     -> accepted
UPDATE audit_events ...    -> ERROR: audit_events is append-only: UPDATE is not
                              permitted. An audit trail that can be rewritten
                              answers no question worth asking.
DELETE FROM audit_events   -> ERROR: ... DELETE is not permitted.
row after both attempts    -> actor still 'probe@example.org'
```

### 6.4 Schema cycle

```
0002 downgrade -> 11 tables remain (0001 intact), 0 leftover trigger functions
0002 upgrade   -> 17 tables, exactly 1 singleton row
```

Drop order is child-first with no `CASCADE`; every statement succeeded, which is
itself the proof that the ordering is right.

### 6.5 Concurrent activation

Two `psql` sessions, both intending to move the pointer from generation 1:

```
A: BEGIN; SELECT ... FOR UPDATE  -> "A locked at generation 1"
B: BEGIN; SELECT ... FOR UPDATE  -> blocks
A: UPDATE ... AND generation = 1 -> UPDATE 1 ; COMMIT
B: (lock released) sees generation 2
B: UPDATE ... AND generation = 1 -> UPDATE 0
final pointer: generation = 2, updated_by = A
```

A second run with a 1500 ms `lock_timeout` on B produced
`ERROR: canceling statement due to lock timeout ... while locking tuple (0,1) in
relation "active_release"`, confirming B was genuinely blocked rather than
merely slow.

Both halves of the design are visible here: the lock made B *wait*, and the
generation guard made B's stale write affect **zero rows** instead of silently
overwriting A.

> **This is not evidence that the service or its repositories work.** It is
> evidence that the schema this session generated behaves correctly on real
> PostgreSQL. Exercising `SqlAlchemyActiveReleaseRepository.get_for_update()`
> against a database requires psycopg, which cannot be installed here. A15 and
> A16 remain **BLOCKED**.

## 7. Compose

Re-verified, unchanged from WP-02: `docker compose --env-file .env.example
config` and the `--profile test` variant both exit 0; the daemon is unreachable,
so no container was started. WP-03 added no service and changed no compose
setting.

## 8. Preservation

| Scope | Result |
|---|---|
| WP-00 `claims.py`, `test_claims.py`, both documents | **byte-identical** |
| `architecture.md` | **byte-identical** |
| Seven legacy Python modules | **unchanged** |
| WP-01 manifest | **64/64 legacy, 22/22 evidence, 0 problems** |
| WP-01 amendments | **1** - the WP-02 record; no second amendment |
| `migrations/versions/0001_wp02_foundation.py` | **unchanged** |
| Legacy CSV/JSON outputs | **unchanged** - read and hashed, never written |
| `uv.lock` | **absent** - none fabricated |

| Governance state | Value |
|---|---|
| `CLAIM_BOUNDARY_STATUS` | `DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW` |
| `P0_CLAIM_BOUNDARY.is_approved` | `False` |
| `PILOT` enabled | `False` |
| Legacy rule rows imported | **0** |
| Network calls made | **0** |
| WP-04 artifacts | **none** |

## 9. Two WP-02 tests amended, and why

Both were correct for WP-02 and became false-by-design once WP-03 legitimately
created the release registry. Neither is a WP-00 or WP-01 frozen file.

| Test | Was | Now |
|---|---|---|
| `test_no_assessment_orm_model_exists` | forbade `ReleaseBundleORM`, `RulesetVersionORM`, `SoftwareVersionORM`, `ActiveReleaseORM` | forbids assessment, validation, user and ingestion ORM classes - the ones that still belong to later work packages. A companion test asserts the WP-03 classes **are** present. |
| `test_migration_creates_no_assessment_or_release_table` | forbade release tables in `0001` | still forbids them in `0001` (which must remain exactly eleven tables) and adds a check that **neither** migration creates a WP-04+ table |

One further test was scoped rather than weakened:
`test_no_repository_method_returns_an_orm_type` now applies to public methods,
because a private helper that fetches a row is how every repository works
internally. A second test was added asserting no public method returns the raw
result of such a helper, so the boundary guarantee is unchanged.
