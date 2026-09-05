# WP-15 — handoff

| Field | Value |
|---|---|
| Document ID | `DOC-HAND-015` |
| Work package | WP-15 — Canonical Structured Result and Deterministic Reporting |
| State | Implemented and verified against synthetic fixtures. Real publication is blocked |
| Hands to | WP-16 serialisation |

---

## 1. What WP-15 is

A projection. It turns structured facts that WP-14 already calculated into a
document a person can read, and it decides nothing. The pipeline is
`AssessmentResult -> StructuredReport -> deterministic renderer -> immutable
artifact + manifest`, one direction, no branches.

## 2. What it added

| Area | What |
|---|---|
| `pgx/reporting/` | eleven modules: the canonical result, the structured report, the templates, the renderer, the fact-preservation validator, the claim gate, the artifact writer, the legacy comparison, the language-model boundary, the errors and the package note |
| `pgx/application/` | `report_service.py`, `report_cli.py`, `report_schema.py`, `report_gate_status.py` |
| `schemas/` | five published JSON Schemas |
| `docs/` | four documents plus this handoff |
| `data/` | `data/reports/` (empty by design) and `data/migration/wp15/` |

WP-15 added **no** module to `pgx/engine`. It computes nothing.

## 3. The WP-14 preflight repairs

WP-15 could not be built on WP-14 as it stood. Five defects were repaired
first, in place, and each is proven by
`tests/unit/application/test_assessment_preflight.py`:

1. **Identities were minted, not resolved.** `_as_domain_assessment` called
   `DrugId.new()` and `GeneId.new()` once per row, so two runs of one question
   recorded two different drugs. Repaired with a canonical entity index on the
   pinned release context, which fails closed on an unresolvable or ambiguous
   key. A medication the pinned dataset does not contain records its canonical
   key with no identity rather than an invented one.
2. **The input snapshot dropped the phenotype profile.** Repaired with a
   versioned snapshot carrying the whole canonical input, which hashes back to
   `input_hash` and holds no raw supplied value.
3. **The coverage result was reduced to a hash.** Repaired by embedding the
   complete WP-13 result beside the retained hash, and verifying the two agree
   on read.
4. **Retrieval returned a summary.** Repaired with a lossless read model that
   reconstructs from stored rows and invokes no engine.
5. **The pointer generation was inside the output hash.** Repaired by lifting
   it out of the hashed projection while still recording it, so an activation
   elsewhere no longer makes an unchanged assessment look changed.

`ASSESSMENT_ENGINE_CONTRACT_VERSION` moved to `pgx-assessment-engine/2` and
the computation schema to `pgx-assessment-computation/2` as a result. **No
database migration was added**: the changes are Python and JSON serialiser
changes inside the existing `input_snapshot` and `output_snapshot` JSON
columns, and migration 0009's column shape already supports them.

## 4. What is blocked, and by whom

| Blocker | Owner |
|---|---|
| `REPORT_CLAIM_BOUNDARY_NOT_APPROVED` | the people named in the intended purpose, not code |
| `REPORT_NO_REAL_ASSESSMENT` | everything WP-14's own gate status blocks on |
| `REPORT_NO_DATABASE_RUNTIME` | an environment with SQLAlchemy, a driver and a server |
| `REPORT_TEMPLATES_NOT_REVIEWED` | a named reviewer, and for the Turkish text one who reads Turkish |
| `REPORT_NO_APPROVED_RULESET_OR_RELEASE` | the WP-11 and WP-03 governance chains |
| `REPORT_NO_HUMAN_ROLE_ASSIGNMENTS` | WP-23 authentication, then whoever assigns roles |

None of these can be cleared by writing code. `pgx-report gate-status` reads
all six off the repository and reports them; the machine-readable copy is
`data/reports/wp15-real-gate-status.json`.

## 5. Locales

`tr` is the primary locale and the default; `en` exists so a reviewer who does
not read Turkish can read the same report. Governed codes, reason codes,
phenotypes, identifiers and hashes are never translated in either.

Nobody has reviewed either label set. That is blocker four above, and it is a
human act rather than a test.

## 6. What was verified, and how

4,687 tests pass across WP-00–WP-15, 16 skipped (they require PostgreSQL,
which is unavailable in this environment). WP-15 contributes 442 of them:

| Tests | File |
|---|---|
| 30 | `tests/unit/reporting/test_canonical_result.py` |
| 33 | `tests/unit/reporting/test_structured_report.py` |
| 27 | `tests/unit/reporting/test_fact_preservation.py` |
| 29 | `tests/unit/reporting/test_safe_status_rendering.py` |
| 21 | `tests/unit/reporting/test_determinism.py` |
| 28 | `tests/unit/reporting/test_injection.py` |
| 24 | `tests/unit/reporting/test_artifacts.py` |
| 25 | `tests/unit/reporting/test_wp15_boundaries.py` |
| 29 | `tests/unit/reporting/test_wp15_documentation.py` |
| 20 | `tests/unit/reporting/test_legacy_report_regression.py` |
| 34 | `tests/unit/application/test_report_cli.py` |
| 70 | `tests/unit/application/test_assessment_preflight.py` |
| 26 | `tests/adversarial/test_report_claims.py` |
| 21 | `tests/contract/test_wp15_schemas.py` |
| 25 | `tests/integration/reporting/test_report_end_to_end.py` |

**PostgreSQL was not available.** SQLAlchemy, Alembic and a driver cannot be
installed in this environment, so migration 0009 was **not run**, no ORM class
was imported, and the production read port was never constructed. The lossless
read model was exercised in memory against the same builder the SQLAlchemy
adapter calls, and a test reads the adapter's source to assert the two shape
the same columns. No claim is made here that Alembic ran or that a trigger
fired.

**Everything WP-15 was verified against is synthetic.** No real assessment
exists in this repository, so no real report has been rendered, no artifact
has been published to `data/reports/`, and every document produced so far is
flagged `is_synthetic`.

**No language model was called.** Nothing in this path imports an SDK, reads a
key or opens a socket, and the legacy comparison reads source text and a
previously recorded offline observation rather than calling anything.

## 7. What WP-16 receives

- a `StructuredReport` that has already passed fact preservation, safe-status
  validation and the claim gate;
- a `report_hash` that covers the report plus its presentation contract, and a
  `rendered_checksum` that covers the bytes;
- an artifact manifest carrying both, the fact ledger and the scan evidence;
- five published JSON Schemas, each of which refuses every property it does
  not name.

## 8. What WP-16 must not undo

- attention and coverage are one block; a serialiser that splits them
  reintroduces the failure `SAFETY-INV-001` exists to prevent;
- `NOT_ASSESSED` is not a level and must not be ordered against one;
- every governed code travels with its label and is never replaced by it;
- the canonical warning has exactly one source, in `pgx/domain/claims.py`;
- the claim gate runs on anything a person will read, in whatever format.
