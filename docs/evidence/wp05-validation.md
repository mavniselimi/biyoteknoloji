# WP-05 - Source Policy Validation Evidence

| Field | Value |
|---|---|
| Document ID | `DOC-EV-005` |
| Work package | WP-05 - Scientific Source Strategy, Provenance and Licensing Policy |
| Captured (UTC) | 2026-08-30 |
| Sources approved | **zero** |
| Official terms documents retrieved | **zero** |
| Network requests made | **two, both refused** (section 6) |
| Live scientific API ingestion | **none** |

> **This is a technical evidence artifact for WP-05 only.** It claims no
> scientific validation, no licensing conclusion, and no clinical safety. It
> demonstrates that the *governance mechanism* behaves as specified; it
> demonstrates nothing about what any real source permits.
>
> WP-00 approval remains **BLOCKED**; WP-01's Git checkpoint remains
> **BLOCKED**; the WP-02 and WP-03 toolchain blockers are unchanged; the WP-03
> review findings are open in `docs/handoffs/wp03-open-items.md`. WP-05
> resolves none of them and presents none of them as resolved.

---

## 1. Three kinds of evidence, kept apart

| Kind | What it proves | What it cannot |
|---|---|---|
| **A. Offline behavioural** | Fail-closed defaults, gate determinism, conflict blocking, review-integrity refusals, legacy-inventory determinism | Anything about what a real source permits |
| **B. Structural** | Layer boundaries; the absence of an approval path and of a precedence rule; the migration's shape | That any of it has been reviewed by a human |
| **C. Executed schema** | The `0003` DDL is valid PostgreSQL 16.13 and its constraints reject the rows they are meant to | Anything about Alembic's runner or revision stamping |
| **D. BLOCKED** | Nothing | Human review (A19); official licensing evidence (A20) |

Every claim below is A, B or C. **No source was approved, no licence
identifier was recorded, and no terms document was read at any point.**

## 2. Test results

```
python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -t .
Ran 1298 tests in 4.172s
OK (skipped=10)
```

Baseline before WP-05: 1040 tests. WP-05 adds 258, and converts three
phase-obsolete assertions rather than deleting them (section 5).

| Module | Tests | What it covers |
|---|---:|---|
| `tests/unit/scientific/test_vocabularies.py` | 25 | The ten vocabularies; unknown values refused; no ordering; no member for a non-authoritative evidence type; no scraping acquisition mode |
| `tests/unit/scientific/test_fail_closed.py` | 33 | A config cannot approve itself; `UNKNOWN` blocks as `PROHIBITED` does; an unregistered source has no permissions; a failed retrieval is not evidence; an expired approval is no approval |
| `tests/unit/scientific/test_registry_config.py` | 29 | The checked-in registry: nothing approved, no licence identifiers, every reuse cell `UNKNOWN`, no reviewer name anywhere in the file; the JSON schema matches the code |
| `tests/unit/scientific/test_publication_gate.py` | 27 | The real registry publishes nothing; intent decides which dimensions apply; the verdict is deterministic and digest-stable |
| `tests/unit/scientific/test_conflict_policy.py` | 28 | Detection, determinism, blocking scope; **no precedence rule exists**; settling requires a named human |
| `tests/unit/scientific/test_legacy_inventory.py` | 23 | Byte-identical re-runs; exact legacy text preserved; the allowlist and its documented exclusions |
| `tests/unit/scientific/test_source_policy_cli.py` | 27 | Exit codes; no `approve` subcommand; no network import; no database import |
| `tests/unit/scientific/test_scientific_boundaries.py` | 21 | No infrastructure, no sockets, no scientific record construction, no approval helper, no WP-06 surface |
| `tests/unit/application/test_release_source_gate.py` | 16 | `release_eligible` alone is refused; unavailable policy blocks; conflicts block only cited sources |
| `tests/unit/test_wp05_schema.py` | 27 | Migration shape, single head, only-adds, identifier limits, rendered constraint content |

Zero skips among the WP-05 modules. The ten skips in the full run are the
pre-existing integration tests that need `TEST_DATABASE_URL`.

## 3. The registry's current state

```
$ pgx-source-policy validate --as-of 2026-08-30T12:00:00Z
sources           20
approved           0
findings         216 blocking, 20 warning, 3 info
registry hash    sha256:308162c5fd0c55e1149321fdede9847e18ef2bb9e780eb02e7746324b3d014d3
exit code          1
```

216 blocking findings is the intended output, not a defect. Every external
source is missing its version policy, citation policy, licence identifier,
official evidence, review, acquisition mode, claim categories and all ten reuse
answers, because no review has been done. The three `INFO` findings are the
three `INTERNAL_SYSTEM` entries noting that they are bookkeeping.

```
$ pgx-source-policy evaluate-publication --dataset PGX-DS-DEMO \
      --source cpic.database --claim PRIMARY_GUIDELINE_RECOMMENDATION
decision: BLOCKED
exit code: 1
```

## 4. Legacy source inventory

```
$ pgx-source-policy inventory-legacy --write
distinct values      18
total occurrences 11308
columns scanned       9
excluded columns      3
content hash      sha256:8f9890ff74ba0b393a5c50e51c21e0aa70ed2b1baf1d2e1edabf37d23cf92b5d
```

Determinism, verified by re-running and diffing:

```
$ pgx-source-policy inventory-legacy --check   # exit 0: artefacts current
$ cp data/migration/legacy-source-inventory.json /tmp/inv1.json
$ pgx-source-policy inventory-legacy --write
$ diff -q /tmp/inv1.json data/migration/legacy-source-inventory.json
# no output: byte-identical
```

The output carries no wall-clock timestamp, which is what makes a diff in it
mean the *data* changed. Staleness is detectable from the per-input SHA-256
digests instead.

Two facts the inventory records without resolving them:

- `report/pair:variantAnnotation` and `report/pair:VariantAnnotation` both
  occur, 4718 times each across three columns. They are counted separately.
  Whether they name the same container is a question for the source owner,
  not a normalisation this project may apply. The same holds for
  `report/pair:guidelineAnnotation` and `report/pair:GuidelineAnnotation`.
- Two rows carry a blank source value. Their provenance is unrecorded and
  cannot be inferred.

`drug_graph_edges.csv::source` and `candidate_alternatives.csv::source_drug`
carry drug names and are excluded with the reason recorded, so the omission
reads as a decision rather than an oversight.

Every legacy source *name* resolves to a registered policy via
`legacy_aliases`: `CPIC`, `DPWG`, `RNPGx`, `AHA`, `AusNZ`, `CPNDS`, `ClinPGx`.
Resolving is not approving - all seven targets are `PENDING_REVIEW`.

## 5. Executed schema evidence (PostgreSQL 16.13)

The `0003` migration was rendered to DDL by `scripts/render_wp05_schema.py`
(which reads the migration's AST, so the two cannot drift) and executed on a
real server.

```
PostgreSQL 16.13 (Ubuntu 16.13-0ubuntu0.24.04.1) on x86_64-pc-linux-gnu
0001 applied -> 0002 applied -> 0003 applied
22 tables in public, including the five WP-05 tables
```

**This is not Alembic evidence.** It proves the DDL is valid PostgreSQL and
that the constraints behave as designed. It proves nothing about Alembic's
runner, its revision chain, or `alembic_version` stamping. Those remain BLOCKED
for the same reason as in WP-02 and WP-03: the package index is unreachable and
SQLAlchemy, Alembic, psycopg, pytest, ruff and mypy cannot be installed.

### 5.1 Constraints that rejected the rows they are meant to

| # | Attempted row | Constraint that refused it |
|---|---|---|
| 1 | `source_policies` with `status = 'APPROVED'` and `review_id` NULL | `ck_source_policies_approving_needs_review` |
| 2 | `source_policy_reviews` with `decision = 'APPROVE'` and empty `evidence_urls` | `ck_source_policy_reviews_approval_needs_evidence` |
| 3 | `APPROVE_WITH_RESTRICTIONS` naming no restrictions | `ck_source_policy_reviews_restricted_names_terms` |
| 4 | `PENDING_REVIEW` policy naming a claim category | `ck_source_policies_categories_need_approval` |
| 5 | `source_conflicts` with `status = 'RESOLVED'` and no resolution | `ck_source_conflicts_settled_has_resolution` |
| 6 | `ELIGIBLE` verdict carrying a `BLOCKER` issue | `ck_publication_evaluations_eligible_has_no_blocker` |
| 7 | `VERIFIED` evidence with no URL | `ck_source_policy_evidence_verified_is_specific` |
| 8 | Conflict naming one source | `ck_source_conflicts_needs_two_sources` |
| 9 | `INTERNAL_SYSTEM` policy claiming `PHENOTYPE_MAPPING` | `ck_source_policies_internal_system_claims` |

### 5.2 The happy path, and the append-only guards

A review row naming `TEST_SCIENTIFIC_REVIEWER` with a cited evidence URL
inserted successfully, and an `APPROVED` policy pointing at it then inserted
successfully - so the constraint refuses forgery, not approval itself. Then:

```
UPDATE source_policy_reviews ...
ERROR:  table source_policy_reviews is append-only: UPDATE is not permitted.
DELETE FROM source_policy_reviews ...
ERROR:  table source_policy_reviews is append-only: DELETE is not permitted.
DELETE FROM dataset_publication_evaluations ...
ERROR:  table dataset_publication_evaluations is append-only: DELETE is not permitted.
```

### 5.3 Downgrade round trip

`downgrade()` was rendered from its own AST and executed:

```
0003 -> 0002:  five tables dropped, function pgx_wp05_append_only() gone (0 rows in pg_proc)
0002 -> 0003:  re-applied cleanly; 22 tables; the four WP-02/WP-03 tables checked all present
```

The `0002 -> 0003 -> 0002 -> 0003` cycle is clean and nothing belonging to
`0001` or `0002` was touched.

## 6. The network attempt, recorded honestly

One retrieval attempt was made, at the start of WP-05, to establish whether
official ClinPGx terms could be read:

```
https://api.clinpgx.org/  -> URLError <urlopen error Tunnel connection failed: 403 Forbidden>
https://www.clinpgx.org/  -> URLError <urlopen error Tunnel connection failed: 403 Forbidden>
```

No retry was made. The result is recorded on both ClinPGx registry entries as
an evidence reference with `evidence_type: NOT_OBTAINED`,
`verification: BLOCKED`, and the exact error text in `blocked_reason`.

What this **did not** produce: a licence identifier, a reuse permission, a
claim category, or a status change. Both entries still report
`MISSING_OFFICIAL_EVIDENCE` alongside `EVIDENCE_RETRIEVAL_BLOCKED`. Network
failure was not converted into approval, and no other source was probed at all.

No live scientific API ingestion was performed. The WP-04 ClinPGx adapter was
not invoked.

## 7. Toolchain status - unchanged and still BLOCKED

| Tool | Status |
|---|---|
| `ruff` | **NOT INSTALLED** - package index unreachable |
| `mypy` | **NOT INSTALLED** |
| `pytest` | **NOT INSTALLED** - the suite runs under `unittest` |
| `alembic` | **NOT INSTALLED** |
| `sqlalchemy` | **NOT INSTALLED** (`ModuleNotFoundError`) |
| `python3` | 3.10.12 |

WP-05 makes no claim of lint or type-check cleanliness. Nothing in this work
package resolves the WP-02 toolchain blocker.

## 8. Phase-obsolete assertions, converted rather than deleted

Three WP-03/WP-04-era tests asserted things WP-05 legitimately changes. Each
was converted to the invariant it was actually protecting, and none was
deleted.

| Test | Was | Now |
|---|---|---|
| `test_no_v2_module_reads_the_legacy_seed_data` | No V2 module may name a legacy data path | Unchanged, except `pgx/scientific/inventory.py`, which WP-05's brief requires - plus a new companion test that the exemption is read-only: no write mode, no domain record, no repository, no session |
| `test_no_migration_creates_an_ingestion_or_snapshot_table` | `source_licenses` among the forbidden tables | Source-policy tables are now legitimate; acquisition and snapshot tables (`raw_snapshots`, `dataset_artifacts`, …) are still forbidden, and a new test asserts the five WP-05 tables come from `0003` alone |
| `test_the_application_layer_holds_only_release_and_ingestion_modules` | Two module groups | Three, with `source_policy_cli.py` named explicitly |

One authorised fixture amendment: the WP-03 release fixtures now pass a
`fixture_source_policy` that approves the synthetic `fixture-source` under the
shouted identity `TEST_SCIENTIFIC_REVIEWER`. Without it every WP-03 activation
test would fail, **which is the correct new behaviour** - a release may no
longer activate on `release_eligible` alone. The fixture touches no real source
and is never loaded from `config/`; a test asserts that the string
`TEST_SCIENTIFIC_REVIEWER` appears nowhere in the checked-in registry.

## 9. What this evidence does not show

- That any source may be used. Nothing has been reviewed.
- That the ClinPGx, CPIC, DPWG or drug-label terms say anything in particular.
  None has been read.
- That Alembic can run these migrations.
- That the reuse matrix is complete or correct for any real source. Every cell
  is `UNKNOWN`.
- That the project may publish a dataset. It may not, and the gate says so.
