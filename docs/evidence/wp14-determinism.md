# WP-14 — determinism and the attention table

| Field | Value |
|---|---|
| Document ID | `DOC-EVID-014A` |
| Work package | WP-14 — Deterministic PGx Assessment Engine Migration |
| Contract version | `pgx-assessment-engine/2` |
| Source | `pgx/engine/risk.py`, `pgx/engine/risk_models.py`; printed by `pgx-assess attention-table` |
| Tests | `tests/unit/application/test_assessment_determinism.py`, `tests/safety/test_assessment_safety.py` |

---

## 1. The attention aggregation table

Generated from `ATTENTION_AGGREGATION_TABLE` rather than transcribed, so this
document and the engine cannot drift. A test asserts every row is reachable.

**Precedence:** `HIGH`, `MEDIUM`, `LOW`, `NO_ACTIVE_ATTENTION` — read top to bottom, first level present wins.

**Excluded from every maximum:** `NOT_ASSESSED`.

That exclusion is the specification, not an omission. `NOT_ASSESSED` means *we
did not look*, which is not a magnitude; every possible position for it in a
ranking is wrong, so it does not enter one. Passing it into an aggregation
raises.

| Case | When | Coverage | Result |
|---|---|---|---|
| `calculated_findings_present` | at least one validated matched rule produced a level | `any` | `the first level in ATTENTION_PRECEDENCE that is present` |
| `no_finding_full_coverage` | no calculated level, and coverage is FULL | `FULL` | `NO_ACTIVE_ATTENTION` |
| `no_finding_partial_coverage` | no calculated level, and coverage is PARTIAL | `PARTIAL` | `NOT_ASSESSED` |
| `no_finding_insufficient` | no calculated level, and coverage is INSUFFICIENT | `INSUFFICIENT` | `NOT_ASSESSED` |
| `no_finding_unsupported_drug` | no calculated level, and the dataset lacks the drug | `UNSUPPORTED_DRUG` | `NOT_ASSESSED` |
| `no_finding_unsupported_phenotype` | no calculated level, and the phenotype could not be used | `UNSUPPORTED_PHENOTYPE` | `NOT_ASSESSED` |
| `no_finding_source_conflict` | no calculated level, and validated sources disagree | `SOURCE_CONFLICT` | `NOT_ASSESSED` |

Coverage never *lowers* a calculated level. A medication with one `HIGH`
finding and one unevaluable axis is `HIGH` **with `PARTIAL` beside it** —
coverage and attention are separate first-class outputs and neither summarises
the other.

## 2. The finding gate

A finding is emitted only for an axis WP-13 reported `FULL`, and only when all
of these hold:

1. the axis names exactly one supporting rule
2. that rule is a member of the pinned frozen ruleset
3. its content hash equals what coverage recorded
4. the frozen artifact carries an approval record for that exact content (SAFETY-INV-003)
5. its condition names this exact drug and gene
6. WP-12's exact matcher reports MATCH (SAFETY-INV-004)
7. its evidence is non-empty and resolves (SAFETY-INV-006)

**On disagreement:** the assessment fails closed. A FULL axis whose rule does not verify is corruption, not absence, and is never downgraded to NOT_ASSESSED

Each check re-verifies something coverage checked already, on purpose. Coverage
was computed against a manifest; this runs against the artifact. The point of
doing it twice is the case where the two disagree.

## 3. What the output hash covers

Every calculated fact and every pinned version: the input hash, the overall
coverage and attention, every medication result and finding, the coverage
result's own hash, and the complete release provenance.

## 4. What the output hash excludes

- `assessment_id`
- `created_at`
- `completed_at`
- `actor`
- `database insertion order`
- `local paths`
- `wall-clock time`
- `process id`
- `runtime duration`
- `UI labels`
- `report prose`
- `active_pointer_generation`

The last of those is the WP-15 preflight correction. The active pointer
generation says where in the WP-03 pointer's history a release was pinned. It
is audit metadata about *this execution*, not a fact about the case: the same
question, against the same release bundle with the same content hashes, has
the same answer whether it was pinned at generation 3 or at generation 40.
While it was hashed, an activation elsewhere in the system - one touching
neither this release, nor this ruleset, nor this dataset - made an unchanged
assessment look changed, which destroys the single comparison the output hash
exists to support. It is still written to the assessment row, still returned
under `pointer_audit`, and still auditable; it simply does not enter the hash.
`engine_contract()["recorded_but_not_hashed"]` publishes the distinction.

Two executions of the same question against the same pinned release therefore
produce identical structured content and identical hashes even when their
assessment ids, actors and execution timestamps differ. Tested by running one
input under two different injected clocks against the same artifacts, and by
running it twice with different generated ids and actors.

## 5. What must change the hash

The converse matters as much: a version identity that did not affect the hash
would be one nobody could verify. A changed phenotype, a changed medication
set, a changed ruleset content hash, a changed dataset, a changed release, or a
changed active-pointer generation each produce a different output hash.

## 6. Canonical ordering

Sorted by explicit stable keys before hashing: medications by canonical drug
key, axes by drug and gene, findings by drug, gene and phenotype, evidence
references sorted and deduplicated, reason codes ordered by WP-13's declared
order. Persistence ordinals are assigned from these sorted collections, so the
stored order is the canonical order rather than insertion order.

## 7. What this does not establish

That the semantics are the *right* semantics. They match `architecture.md` 9.3
and the safety contract; whether that is what a pharmacogenomics expert would
approve is a question for a reviewer, and the curation protocol is still
`AWAITING_EXPERT_REVIEW`. Every fixture is synthetic and no real assessment has
been executed.
