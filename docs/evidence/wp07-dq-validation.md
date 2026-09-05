# WP-07 verification evidence

What was executed, on what, and what it produced. Every command below is
reproducible from a clean checkout with no network access.

## 1. Environment

| Item | Value |
| --- | --- |
| Python | 3.10 (`python3`) |
| Test runner | `python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -t .` |
| PyPI | unreachable. No SQLAlchemy, Alembic, psycopg, pytest, ruff or mypy is installed. |
| Docker | no daemon available |
| PostgreSQL | 16.13 server binaries available; used directly, without Alembic |

`PYTHONDONTWRITEBYTECODE=1` is set for every run, because the working tree does
not permit removing `__pycache__`.

## 2. Test suite

```
$ PYTHONDONTWRITEBYTECODE=1 python3 -W error::ResourceWarning \
    -m unittest discover -s tests -p 'test_*.py' -t .
Ran 1976 tests
OK (skipped=10)
```

402 of those are new in WP-07 (365 under `tests/unit/normalization/`, 37 in
`tests/unit/test_wp07_schema.py`):

| File | Covers |
| --- | --- |
| `tests/unit/normalization/test_normalize_rules.py` | normalisation, external identifiers |
| `tests/unit/normalization/test_canonical_models.py` | entities, locators, alias review, outcomes, duplicate groups |
| `tests/unit/normalization/test_strict_resolver.py` | stage order, ambiguity, no ranking or fuzzy matching |
| `tests/unit/normalization/test_deduplication.py` | three duplicate classes, provenance retention |
| `tests/unit/normalization/test_identity_allocation.py` | explicit allocation, no derivation, no reclamation |
| `tests/unit/normalization/test_artifact_extraction.py` | role map, derivation checks, integer identifiers |
| `tests/unit/normalization/test_canonical_build.py` | build assembly, atomic seal, reproducibility |
| `tests/unit/normalization/test_data_quality.py` | metrics, reconciliation, fail-closed gate, schema |
| `tests/unit/normalization/test_legacy_differences.py` | claim checks, candidate drift, stale totals |
| `tests/unit/normalization/test_normalize_cli.py` | CLI behaviour and its deliberate absences |
| `tests/unit/normalization/test_quality_transition.py` | the audited `BUILDING -> QUALITY_CHECKED` transition on a synthetic dataset |
| `tests/unit/normalization/test_build_safety.py` | corruption drills, unsafe paths, symlinks, sockets disabled |
| `tests/unit/normalization/test_wp07_documentation.py` | the document set and the claims it makes |
| `tests/unit/normalization/test_normalization_boundaries.py` | layer boundaries, no WP-08 concept |
| `tests/unit/test_wp07_schema.py` | migration `0005` shape and rendered DDL |

The build, quality, legacy-difference and CLI tests run against the **real**
quarantined snapshot rather than a fixture, because the counts they assert are
claims about that data. Negative cases use synthetic snapshots built into a
temporary directory; the real snapshot is never modified, and a test re-verifies
it after the CLI tests have run.

## 3. Migration executed on real PostgreSQL

The Alembic migration is authoritative. `scripts/render_wp07_schema.py` reads
its AST and emits equivalent DDL, so the two cannot drift.

**This is not Alembic evidence.** It shows the schema is valid PostgreSQL and
that its constraints behave as designed. It shows nothing about Alembic's
runner, its revision chain, or `alembic_version` stamping — those remain
BLOCKED for the same reason they were in WP-02 through WP-06.

```
$ python3 scripts/render_wp07_schema.py --check-identifiers --out build/wp07-schema.sql
wrote build/wp07-schema.sql (34 statements)
$ psql -d pgx_wp07 -f wp02-schema.sql -f wp03-schema.sql -f wp05-schema.sql \
                   -f wp06-schema.sql -f wp07-schema.sql
… applied, 29 tables in public
```

PostgreSQL 16.13 (Ubuntu 16.13-0ubuntu0.24.04.1).

### 3.1 Constraint drills

Thirty-two statements run against the executed schema. Every one behaved as
designed.

| # | Attempt | Result |
| --- | --- | --- |
| D1 | insert an alias the pre-`0005` way | accepted, `status = PENDING_REVIEW` |
| D2 | `APPROVED` alias with no reviewer | refused, `ck_gene_aliases_approval_names_reviewer` |
| D3 | `APPROVED` alias with reviewer and instant | accepted |
| D4 | the same alias on two different genes | **accepted** — ambiguity is storable |
| D5 | alias status `AUTO_APPROVED` | refused, `ck_gene_aliases_status_enum` |
| D6 | insert a canonical build | accepted |
| D7 | `dq_gate_passed = true` while listing blocking codes | refused, `ck_canonical_builds_pass_has_no_blocking_codes` |
| D8 | rewrite a recorded build's `content_hash` | refused, `trg_canonical_builds_immutable` |
| D9 | delete a recorded build | refused, `trg_canonical_builds_immutable` |
| D10 | attach a `dq_report_hash` afterwards | accepted — not an identity field |
| D11 | entity whose `canonical_key` disagrees with its value | refused |
| D12 | gene entity with a lowercase normalised value | refused |
| D13 | entity with `locator_count = 0` | refused, `ck_..._has_provenance` |
| D14 | well-formed entity | accepted |
| D15 | a `RESOLVED` outcome in the review queue | refused, `ck_..._needs_review` |
| D16 | `AMBIGUOUS` item carrying one candidate | refused |
| D17 | `AMBIGUOUS` item carrying both candidates | accepted |
| D18 | decision with no rationale | refused, `ck_resolution_queue_decision_is_complete` |
| D19 | decision choosing a non-candidate | refused, `ck_resolution_queue_choice_was_a_candidate` |
| D20 | complete decision choosing a real candidate | accepted |
| D21 | non-blocking `CONFLICTING_IDENTITY` group | refused, `ck_duplicate_groups_conflict_blocks` |
| D22 | blocking conflict stating no differences | refused |
| D23 | blocking conflict stating its differences | accepted |
| D24 | duplicate group with one member | refused, `ck_duplicate_groups_member_count` |
| D25 | `QUALITY_CHECKED` with no named approver | refused, `ck_dataset_versions_approval_requires_reviewer` |
| D26 | read the dataset back | still `BUILDING` |
| D27 | audit `DATASET_QUALITY_CHECKED` | accepted |
| D28 | audit `DATASET_AUTO_APPROVED` | refused, `ck_audit_events_action_enum` |
| D29 | two member rows for one duplicate group | accepted, both locators kept |
| D30 | absolute artifact path in a member | refused, `ck_..._path_relative` |
| D31 | `UPDATE audit_events` | refused, still append-only |
| D32 | `QUALITY_CHECKED` **with** approver and instant | accepted |

D8 and D9 raise the trigger's own messages:

```
ERROR:  a recorded canonical build is immutable: its identity, hashes and rule
        versions describe bytes that already exist on disk.
ERROR:  canonical_builds rows are not deletable: a recorded build is the thing
        every canonical entity, queue item and duplicate group points at, and
        removing it would orphan all of them.
```

### 3.2 Downgrade

Rendered from `downgrade()` by the same script, so the down path cannot drift
from the migration.

On a clean database:

```
tables: after-upgrade=29  after-downgrade=24  after-reupgrade=29
leftover alias review columns after downgrade: 0
leftover trigger function after downgrade: 0
audit action list after downgrade: DATASET_QUALITY_CHECKED absent
approval constraint after downgrade: ck_dataset_versions_published_requires_approval
WP-06 tables still present: 2
```

On a database holding a `DATASET_QUALITY_CHECKED` audit event the downgrade is
**refused**:

```
ERROR:  check constraint "ck_audit_events_action_enum" of relation
        "audit_events" is violated by some row
```

That refusal is the documented and correct outcome, not a defect. `audit_events`
is append-only, so retro-narrowing the constraint would mean either lying about
the constraint or destroying history, and the migration declines to choose for
the operator.

## 4. The real canonical build

```
$ python3 scripts/normalize.py build \
    --snapshot data/raw/clinpgx-legacy-v2/PGX-DATA-20260830-900 \
    --allocate-new-identities --text
canonical build sealed at data/canonical/PGX-DATA-20260830-900
  identities   16 minted, 0 reused
  dataset      BUILDING (a build is not an approval)
```

```
$ python3 scripts/normalize.py verify \
    --build data/canonical/PGX-DATA-20260830-900 --text
  checksums              ok
  summary vs artifacts   ok
  published schemas      ok
```

### 4.1 Reproducibility

```
$ python3 scripts/normalize.py build --snapshot <same> --out /tmp/rebuild \
    --allocation data/canonical/PGX-DATA-20260830-900/identity-allocation.json
  identities   0 minted, 16 reused

$ python3 scripts/normalize.py compare-builds --left <first> --right <second> --text
  reproducible          True
  content hash matches  True
  byte-identical apart from provenance  True
  differs: checksums.sha256
  differs: manifest.json
```

`manifest.json` differs because it records `built_at` and this run's mint/reuse
counts; `checksums.sha256` differs because it covers the manifest. Every other
file — including `dq-report.json` and `legacy-differences.json` — is
byte-identical.

Building without an allocation and without `--allocate-new-identities` is
refused:

```
16 canonical key(s) have no allocated identity and this run may not mint one …
Allocation is a deliberate state change; run it explicitly rather than letting
a build create identities.
```

### 4.2 Refusals

```
$ python3 scripts/normalize.py build --snapshot <same>          # over an existing build
a canonical build already exists at data/canonical/PGX-DATA-20260830-900.
Sealed builds are never overwritten; write the new build elsewhere and compare
the two.
```

## 5. Data quality gate

```
$ python3 scripts/normalize.py quality-check \
    --build data/canonical/PGX-DATA-20260830-900 --text
quality gate for PGX-DATA-20260830-900/…: BLOCKED
  blocking  SNAPSHOT_NOT_ACQUIRED
  blocking  SNAPSHOT_QUARANTINED
  blocking  SOURCE_POLICY_MISSING
  advisory  CONTAINER_SYNONYM_UNREVIEWED
  advisory  SEMANTIC_DUPLICATE_CONTAINER
  the dataset remains BUILDING; this command changed nothing.
```

Exit code 1. The three blocking findings are correct: the snapshot is a
quarantined legacy import with no acquisition run behind it, and no human has
approved the ClinPGx source.

Reconciliations, all balancing:

```
raw_artifacts                input 12   = accepted 4    + rejected 8 + deferred 0
entity_candidates            input 16   = accepted 16   + rejected 0 + deferred 0
entity_references            input 29   = accepted 29   + rejected 0 + deferred 0
source_record_observations   input 3466 = accepted 1822 + rejected 0 + deferred 1644
```

Independent re-count from the sealed files, agreeing with the manifest summary:

```
{"gene_count": 5, "drug_count": 11, "membership_count": 16,
 "queue_item_count": 0, "duplicate_group_count": 1644,
 "provenance_link_count": 16, "duplicate_group_member_count": 3288,
 "blocking_duplicate_group_count": 0, "duplicate_observation_count": 1644,
 "identity_allocation_size": 16, "entity_count": 16}
```

## 6. Legacy comparison

Reported in full in
[../migration/wp07-legacy-differences.md](../migration/wp07-legacy-differences.md).
The headline: the documented figure of **1,572** dedup collisions is not
reproducible from the real artifacts, which yield **1,644** under the
per-pair case-folded container-family measure. No alternative measurement that
can be defined precisely yields 1,572 either. The count is reported as observed
and the dedup key was not reshaped; acceptance item A11 is recorded FAIL.

## 7. The audited transition, on a synthetic dataset

The real dataset is refused, naming every blocking code and writing nothing:

```
outcome              REFUSED_GATE_BLOCKED
blocking_codes       SNAPSHOT_NOT_ACQUIRED, SNAPSHOT_QUARANTINED,
                     SOURCE_POLICY_MISSING
committed            0
audit events         0
dataset state        BUILDING (unchanged)
```

A clean **synthetic** dataset — a synthetic snapshot, an approved synthetic
source-policy status, and the shouted reviewer identity
`TEST_SCIENTIFIC_REVIEWER` — passes the gate and transitions:

```
outcome              QUALITY_CHECKED
committed            1
audit events         1  (DATASET_QUALITY_CHECKED, actor TEST_SCIENTIFIC_REVIEWER)
recorded             dq_report_path, dq_report_hash, canonical_build_key
```

A second attempt on the same dataset is refused (`REFUSED_WRONG_STATE`) and
writes nothing. A build whose bytes were altered is refused
(`REFUSED_BUILD_UNVERIFIED`). An unknown dataset is refused
(`DATASET_NOT_FOUND`). None of the refusals commits or appends.

The unit of work in these drills is a fake that records what it was asked to do,
so the behaviour is pinned before any database adapter exists. Nothing in this
section touches the real registry, the real snapshot or a real database.

## 8. What remains BLOCKED, and why

| Item | State | Reason |
| --- | --- | --- |
| Alembic runner, revision chain, `alembic_version` stamping | BLOCKED | Alembic cannot be installed; rendered DDL is supplementary evidence, not a substitute |
| ORM mapping and repository implementations for the WP-07 tables | BLOCKED | SQLAlchemy cannot be installed. The ports exist and the transition service is tested against a fake unit of work; no adapter exists. |
| A quality-checked dataset | BLOCKED | the snapshot is quarantined, no acquisition run backs it, and no human has approved the source |
| Source policy approval for ClinPGx | BLOCKED | no named reviewer has recorded a decision (WP-05, A19/A20) |

None of these is fabricated as passing anywhere in this repository.
