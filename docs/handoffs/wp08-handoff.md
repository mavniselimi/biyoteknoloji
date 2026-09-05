# WP-08 handoff

| Field | Value |
|---|---|
| Document ID | `DOC-HANDOFF-008` |
| Work package | WP-08 - Evidence Store Migration and End-to-End Traceability |
| Status | **Offline scope complete. Nothing is curated, approved, executable or publishable.** |
| Output for WP-09 | one sealed, reproducible, quarantined evidence build with a verified provenance chain, and 1,559 unreviewed curation candidates outside it |

> Read this before WP-09. Three items must not be presented as met.
> **A11**, the documented 1,572 collision figure, is still **FAIL** — inherited
> from WP-07, unresolved, and deliberately not forced.
> **A24**, a quality-checked dataset, is still **BLOCKED**.
> **A25**, a production evidence import, is **BLOCKED** because the snapshot is
> quarantined and no human has approved the source. It was not fabricated.

---

## 1. What exists now

| Artefact | What it is |
|---|---|
| `pgx/evidence/models.py` | Records, natural keys, versions, attributions, fragments, links, issues; `pgx-evidence-record/1` |
| `pgx/evidence/record_types.py` | Object class to record type; the `label`/`DrugLabel` findings as data; `pgx-evidence-record-types/1` |
| `pgx/evidence/payloads.py` | Recursive projection and conflict detection |
| `pgx/evidence/publications.py` | PMID/DOI parsing; no title matching, no network; `pgx-evidence-publications/1` |
| `pgx/evidence/extract.py` | Reads a snapshot into source-record observations; `pgx-evidence-extraction/1` |
| `pgx/evidence/allocation.py` | Explicit identity allocation; `pgx-evidence-identity-allocation/1` |
| `pgx/evidence/build.py` | Gates, assembly, atomic seal, comparison; `pgx-evidence-build/1` |
| `pgx/evidence/detail.py` | Artifact-backed detail and trace repository; raises on duplicate keys |
| `pgx/evidence/draft_curation.py` | Legacy interpretations read by AST, never executed; `pgx-draft-curation/1` |
| `pgx/evidence/ports.py` | Persistence ports; **no implementation exists** |
| `pgx/application/evidence_cli.py` | `pgx-evidence`, nine read/build commands |
| `pgx/application/evidence_schema.py` | Loads and applies the three published schemas |
| `migrations/versions/0006_wp08_evidence_store.py` | Eight tables, fourteen columns, one constraint replacement, whole-row immutability trigger |
| `schemas/evidence-record.schema.json` | The record contract |
| `schemas/evidence-build-manifest.schema.json` | The build manifest contract |
| `schemas/draft-curation-proposal.schema.json` | The proposal contract |
| `scripts/evidence.py`, `scripts/render_wp08_schema.py` | Operator and evidence tooling |
| `scripts/sql/wp08-constraint-drills.sql` | 38 reproducible database drills |
| `data/evidence/PGX-DATA-20260830-900/` | The sealed evidence build |
| `data/migration/wp08/draft-curation-proposals.ndjson` | 1,559 unreviewed candidates, outside the store |

Policy documents:
[evidence-record-contract](../data/evidence-record-contract.md),
[evidence-provenance-chain](../data/evidence-provenance-chain.md),
[evidence-import-policy](../data/evidence-import-policy.md).
Evidence: [wp08-trace-validation](../evidence/wp08-trace-validation.md).
Migration: [wp08-legacy-curation-extraction](../migration/wp08-legacy-curation-extraction.md).

## 2. What the build contains

`data/evidence/PGX-DATA-20260830-900/`, key
`PGX-DATA-20260830-900/5a58c030d00dc649`, content hash
`sha256:5a58c030d00dc6495d69c3ff9e1d76c6d6230caf7795871e4dfc4e8774fcb83e`.

| Measure | Value |
| --- | ---: |
| Evidence records | 1,794 |
| Raw locators | 4,051 |
| Entity links | 4,284 |
| Text fragments | 3,432 |
| Publication references | 1,952 (1,797 identified, 1,012 distinct) |
| Import issues | 3,486 (3,235 blocking) |
| Records complete in themselves | 132 |
| Records publishable | **0** |

Labels: `QUARANTINED`, `LEGACY_MIGRATION`, `NOT_CURATED`, `NOT_EXECUTABLE`,
`NOT_PUBLICATION_ELIGIBLE`. Dataset lifecycle state: `BUILDING`.

## 3. What WP-09 inherits as open work

Each of these is a decision this work package deliberately did not make.

| # | Open item | Count | Why it is open |
|---|---|---:|---|
| 1 | `label` vs `DrugLabel` equivalence | 28 records | Three findings support equivalence; none proves it. Both types retained, mapping `PENDING_REVIEW`, records quarantined. |
| 2 | Records stating no origin | 1,662 | The source does not name who asserted them. Guessing CPIC from subject matter would be a scientific claim. |
| 3 | Records with no recoverable version | 1,542 | The legacy flattening discarded it. `UNKNOWN_LEGACY`, never `v1`. |
| 4 | Unresolved entity references | 251 | Inherited from WP-07's resolution queue; advisory. |
| 5 | Unlinked curation proposals | 33 | 11 keyed by gene+drug rather than a source record; 22 without a `PA` accession. |
| 6 | 1,572 vs 1,644 collisions | — | Inherited from WP-07. Unresolved. Not forced, not edited away. |
| 7 | No source policy on record | — | A human must approve the source before any production import. |
| 8 | No persistence adapter | — | Ports and migration exist; no driver is installable here. |

## 4. Defects this work package found and fixed

Recorded because each was found by a test that failed, and each would have been
invisible without one.

| What | How it was found |
|---|---|
| A shallow payload comparison reported 82 non-conflicts as conflicts | Re-measured recursively: 0 conflicts |
| Draft curation linked 0 of 1,559 proposals | The legacy CSV keys on `accessionId`, not the numeric `id` |
| `CREATE INDEX` emitted before its `ADD COLUMN` | PostgreSQL refused the rendered DDL |
| Publication identity CHECK admitted `title:...` beside a NULL `doi` | Drill E21; SQL three-valued logic |
| Eligibility CHECK admitted an unmapped record as eligible | Drill E34; same NULL collapse |
| The immutability trigger let `source_text` be rewritten after finalization | Drill R11 against the real corpus |
| `DROP TABLE` before `DROP COLUMN` in the downgrade | The FK refused it |
| A refused downgrade left the schema half-applied | Both directions are now one transaction |
| `compare-builds` called two near-empty directories reproducible | A negative-control test |
| Whole-corpus trace verification took over two minutes | One artifact is now hashed and parsed once per run, not per record |

## 5. What WP-09 must not assume

- **The evidence store is not a curation store.** Nothing in it says whether a
  source statement is correct, applicable, or safe to act on.
- **`production_eligible: true` on a record is not permission.** The build is
  quarantined; the record-level flag says only that the record is complete in
  itself. Both are printed separately for this reason.
- **A draft curation proposal is not a curation.** It has no author, no
  reviewer and no approval, and its status and four warnings are fixed by the
  published schema.
- **The three blocking gate findings are the real state of this dataset.** They
  are not configuration to be relaxed.
- **`render-rows` writes no database.** It renders the rows migration 0006
  declares, and nothing here inserts them.

## 6. Reproducing everything in this handoff

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -W error::ResourceWarning \
  -m unittest discover -s tests -p 'test_*.py' -t .

python3 scripts/evidence.py verify \
  --build data/evidence/PGX-DATA-20260830-900 \
  --snapshot data/raw/clinpgx-legacy-v2/PGX-DATA-20260830-900 \
  --trace-limit 0 --text

python3 scripts/render_wp08_schema.py --check-identifiers --out build/wp08-schema.sql
python3 scripts/render_wp08_schema.py --direction downgrade --out build/wp08-downgrade.sql
# then apply build/wp0{2,3,5,6,7,8}-schema.sql to a PostgreSQL 16 database and
# run scripts/sql/wp08-constraint-drills.sql
```

No step needs the network.
