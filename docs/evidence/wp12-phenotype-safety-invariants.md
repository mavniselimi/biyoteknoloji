# WP-12 phenotype safety-invariant evidence

| Field | Value |
|---|---|
| Document ID | `DOC-EVID-014` |
| Work package | WP-12 — Exact Phenotype Engine Migration |
| What this proves | the phenotype layer's behaviour under `SAFETY-INV-001`, `SAFETY-INV-003` and `SAFETY-INV-004`, by executable test |
| What this does **not** prove | that any rule is scientifically correct, that any protocol is approved, or anything at all about a medicine |

---

## 1. `SAFETY-INV-004` — `RAPID` must not implicitly equal `ULTRARAPID`

The invariant requires exact equality against the P0 model, with any rule
covering several phenotypes encoding an explicit set, and requires a matrix
test over all six values against rule phenotype sets.

**Evidence.** `tests/unit/engine/test_truth_matrix.py`:

| Assertion | Result |
|---|---|
| every determinate phenotype against every `EXACT` rule phenotype (25 pairs) | matches only itself; 5 matches, 20 `NO_MATCH` |
| `INDETERMINATE` against every rule phenotype (5 pairs) | `INPUT_INDETERMINATE`, 0 matches |
| `RAPID` vs `EXACT ULTRARAPID` | `NO_MATCH` |
| `ULTRARAPID` vs `EXACT RAPID` | `NO_MATCH` |
| `ONE_OF [RAPID, ULTRARAPID]` | matches both |
| `ONE_OF` naming only one of the pair | matches only that one |
| every subset of the five rule phenotypes (31 sets × 5 inputs) | matches exactly its members |
| `sorted([RAPID, ULTRARAPID])` | raises `TypeError`; the enum refuses ordering |

The subset test is the one that makes this evidence rather than illustration:
it covers every combination, not the combinations somebody thought of.

**Legacy contrast**, from `tests/unit/engine/test_legacy_regression.py`, which
imports `risk_engine` directly: `phenotype_matches("rapid", "ultrarapid")` is
`True` and `phenotype_matches("ultrarapid", "rapid")` is `True`. Both are
recorded in the allowlist under `LEGACY-BUG-001`.

## 2. `SAFETY-INV-001` — missing data must not produce low or no-active attention

WP-12 cannot violate this invariant by producing a reassuring value, because it
produces no attention value at all. The evidence is structural, and stronger
for it: there is no field to write one into.

**Evidence.** `tests/unit/engine/test_failure_modes.py`:

| Assertion | Result |
|---|---|
| `MatchDecision` declares no attention, risk, score, severity or priority field | passes |
| `MatchDecision` declares no coverage field | passes |
| `MatchDecision` declares no dose, recommendation, treatment, safety, finding or narrative field | passes |
| no match status string collides with an `AttentionLevel` value | passes |
| no match status string collides with a `CoverageStatus` value | passes |
| the serialised decision carries no forbidden key | passes |
| seven failing inputs × five rule phenotypes | never match |
| missing, indeterminate and unsupported produce three distinct statuses | passes |
| none of them is reported as `NO_MATCH` | passes |
| the reason code and observation status survive into the decision | passes |

And in the normaliser: no unrecognised value — `PM`, `unknown`, `n/a`, `?`,
`TBD`, `wild type`, `0`, `None`, `[]`, `{}` — ever yields `NORMAL`, or any
phenotype at all.

The published schemas repeat the refusal: adding `attention_level`,
`coverage_status`, `dose`, `recommendation`, `risk_score`, `safe`, `treatment`
or `finding` to a match result is rejected by
`schemas/phenotype-match-result.schema.json`.

## 3. `SAFETY-INV-003` — unvalidated rules must not execute

WP-11 decided what may execute. WP-12 does not re-litigate it and structurally
cannot: nothing in `pgx/engine` imports the rule registry, so there is no path
by which the engine could load a rule at all. It compares whatever condition it
is handed, and the only source of conditions is a verified frozen artifact.

**Evidence.** `tests/integration/engine/test_wp11_integration.py`:

| Assertion | Result |
|---|---|
| a synthetic ruleset built, frozen and loaded through WP-11's own registry | 2 members, both `VALIDATED` |
| every member's condition is accepted by the matcher unchanged | passes |
| only the declared phenotype matches a frozen rule | passes |
| a raw dictionary condition is refused | `PHENOTYPE_CONDITION_UNSUPPORTED_TYPE` |
| a legacy-style condition dictionary is refused | passes |
| no engine module imports `pgx.rules.registry` | passes |
| the matcher never names `outcome`, `provenance` or evidence | passes |
| the default real registry after all of it | **0 executable rulesets** |

## 4. Determinism

Two independent generations of the regression report, and the committed file,
are byte-identical:

```
368512b9c896f988b1940a3d462d7b82  /tmp/wp12_run_a.json
368512b9c896f988b1940a3d462d7b82  /tmp/wp12_run_b.json
368512b9c896f988b1940a3d462d7b82  data/migration/wp12/phenotype-regression-report.json
```

Content hash: `sha256:a648654036abc67a119b591370ba079fe237e63c61a8ec675d7f56629534f99b`.

The engine imports no clock, no `random`, no `uuid` and no network client, and
a boundary test asserts each absence. A profile's hash excludes insertion
order, display names, raw spellings, paths and timestamps.

## 5. What this evidence does not establish

Nothing here says any rule is correct, that any protocol has been approved, or
anything whatsoever about a medicine. The engine compares two values exactly.
Whether the values are the right ones, and whether the rule they are compared
against should exist, are scientific questions owned by people who have not yet
answered them: the curation protocol is still `AWAITING_EXPERT_REVIEW`, and
there are zero validated rules and zero frozen rulesets in this repository.
