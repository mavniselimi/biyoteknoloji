# WP-13 — legacy risk versus V2 coverage

| Field | Value |
|---|---|
| Document ID | `DOC-MIG-013` |
| Work package | WP-13 — Coverage Engine |
| Report | `data/migration/wp13/coverage-regression-report.json` |
| Allowlist | `data/migration/wp13/coverage-regression-allowlist.json` |
| Report content hash | `sha256:4ede0b448d49c08c2488ac58e83810b46a296287f1d96fb93dd2bab239d735bd` |
| Harness | `pgx/engine/coverage_legacy.py`; tests in `tests/unit/engine/test_coverage_legacy_regression.py` |

---

## 1. What is being compared

The legacy engine has no coverage concept. It reports one
`overall_risk_level` per drug, and it uses `"none"` for three different
situations: the drug is unknown, no rule matched, and there is nothing to
report. `RISK_LABEL_TR` then renders `"none"` as *"Düşük / uyarı yok"* —
low, no warning.

That is `LEGACY-BUG-002`, and it is the false-reassurance failure in its
original form: three kinds of *we did not look* presented as one kind of *we
looked and it is fine*.

Separately, the legacy candidate path attaches a 0–100 score to prasugrel and
ticagrelor while recording their own data status as
`insufficient_pgx_rule_data` — `LEGACY-BUG-009`. A number between 0 and 100
beside a drug name reads as a ranking however it is labelled.

This harness states, for each of those drugs, what V2 coverage says instead.

## 2. The legacy snapshots were not edited

The WP-01 snapshots are unchanged and a test asserts each defective value is
still there: codeine `none`, warfarin `none`, prasugrel 59, ticagrelor 59.
The legacy value **is** the defect. Editing it would delete the evidence that
the defect existed and make the correction invisible.

The same test asserts the P2 snapshot still carries its real findings —
clopidogrel `high`, voriconazole `high` — because that is what makes the two
`none` rows a defect rather than an empty run.

## 3. The two facts everything is computed from

Both are read from the pinned canonical build rather than asserted, so the day
either changes this report changes with it:

- **codeine and warfarin are in the catalogue.** The dataset has the chemical
  and no approved coverage scope exists for it, so V2 reports `INSUFFICIENT`
  with `NO_VALIDATED_RULE_FOR_AXIS` — *recognition is not coverage*.
- **prasugrel and ticagrelor are not in the catalogue.** No axis exists to
  evaluate and none is fabricated, so V2 reports `UNSUPPORTED_DRUG` with
  `DRUG_NOT_IN_CANONICAL_DATASET`, and no score anywhere: a coverage result
  has no field one could be written into.

## 4. The allowlist

Four entries across the two bugs, two per bug, each addressing one drug by
identity so that a fix covering only one drug cannot satisfy a single-entry
allowlist and a reordered list cannot move one expectation onto another.

| Entry | Bug | Legacy | V2 coverage |
|---|---|---|---|
| `LEGACY-BUG-002-CODEINE-NONE-TO-INSUFFICIENT` | 002 | `none`, rendered "low / no warning" | `INSUFFICIENT` / `NO_VALIDATED_RULE_FOR_AXIS` |
| `LEGACY-BUG-002-WARFARIN-NONE-TO-INSUFFICIENT` | 002 | `none`, same label | `INSUFFICIENT` / `NO_VALIDATED_RULE_FOR_AXIS` |
| `LEGACY-BUG-009-PRASUGREL-SCORE-REMOVED` | 009 | score 59 on `insufficient_pgx_rule_data` | `UNSUPPORTED_DRUG` / `DRUG_NOT_IN_CANONICAL_DATASET`, no score |
| `LEGACY-BUG-009-TICAGRELOR-SCORE-REMOVED` | 009 | identical score 59 | `UNSUPPORTED_DRUG` / `DRUG_NOT_IN_CANONICAL_DATASET`, no score |

The harness fails if an entry's difference stops appearing, if a difference
appears that no entry covers, or if the report is not reproducible byte for
byte. In the current run all four entries are hit exactly once, none went
unobserved, and there are no unexpected differences.

## 5. The cases

Eight, covering the drugs both snapshots record plus a drug in no catalogue at
all. Sorted, carrying no timestamp, path or host, and pinned to the exact
canonical build identity they were computed against.

No case reports `FULL`. No case carries a V2 score. Every case carries at
least one machine-readable reason code — which is the correction, stated
positively: where the legacy engine said "low / no warning", V2 says *not
assessed*, and says why.

The remaining situations the work package names — a missing phenotype, an
unsupported phenotype, a partially covered multi-axis drug, a source conflict,
and a fully covered drug — have no legacy counterpart to compare against,
because the legacy snapshots record a risk level per drug and nothing about
axes. They are exercised against the engine itself on synthetic data in
`tests/unit/engine/test_coverage_axis.py`,
`tests/unit/engine/test_coverage_aggregation.py`,
`tests/safety/test_coverage_safety.py` and
`tests/integration/engine/test_coverage_end_to_end.py`.

## 6. What this report is not

Migration evidence, not clinical validation. No approved coverage manifest
exists, so every V2 answer here is a form of *not assessed, and here is the
machine-readable reason*. That is the whole correction. No coverage status in
this report asserts safety, preference or suitability for any medicine.
